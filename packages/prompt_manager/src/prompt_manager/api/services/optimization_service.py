"""Service layer for prompt optimisation via autoresearcher-shonku.

This wires prompt-manager tools into the AutoResearcherAgent from
autoresearcher-shonku, which runs on top of shonku → agno.
"""

from __future__ import annotations

import json
import logging

import asyncpg  # type: ignore[import-untyped]

from prompt_manager.api.db import experiments_repo, metrics_repo, prompts_repo, versions_repo
from prompt_manager.core.config import PromptManagerSettings
from prompt_manager.core.schemas import OptimizeRequest, OptimizeResponse

logger = logging.getLogger(__name__)


def _build_tools(conn: asyncpg.Connection) -> list:
    """Build the tools that autoresearcher-shonku requires.

    These are plain async callables that close over the DB connection.
    The autoresearcher agent will call them via the LLM tool-calling loop.
    """

    async def get_prompt(slug: str) -> str:
        """Get a prompt by slug, returns JSON with id, slug, body, version."""
        prompt = await prompts_repo.get_by_slug(conn, slug)
        if prompt is None:
            return json.dumps({"error": f"Prompt '{slug}' not found"})
        version = await versions_repo.get_latest(conn, prompt["id"])
        return json.dumps({
            "id": str(prompt["id"]),
            "slug": prompt["slug"],
            "name": prompt["name"],
            "current_version": prompt["current_version"],
            "body": version["body"] if version else "",
            "version_id": str(version["id"]) if version else None,
        })

    async def get_metrics(prompt_id: str, version_id: str, metric_name: str = "quality") -> str:
        """Get aggregated metrics for a prompt version."""
        from uuid import UUID

        rows = await metrics_repo.aggregate_by_version(
            conn, UUID(prompt_id), UUID(version_id), metric_name
        )
        return json.dumps(rows if rows else {"count": 0, "mean": 0, "message": "No metrics yet"})

    async def get_sample_interactions(prompt_id: str, limit: str = "5") -> str:
        """Get recent metric events as sample interactions."""
        from uuid import UUID

        rows = await metrics_repo.get_recent(conn, UUID(prompt_id), int(limit))
        return json.dumps([dict(r) for r in rows] if rows else [])

    async def create_version(slug: str, content: str) -> str:
        """Create a new version for a prompt."""
        prompt = await prompts_repo.get_by_slug(conn, slug)
        if prompt is None:
            return json.dumps({"error": f"Prompt '{slug}' not found"})
        version = await versions_repo.create(
            conn,
            prompt_id=prompt["id"],
            body=content,
            source="optimization",
        )
        return json.dumps({
            "version_id": str(version["id"]),
            "version": version["version"],
        })

    async def create_experiment(
        prompt_id: str, baseline_version_id: str, new_version_id: str, weight: str = "5"
    ) -> str:
        """Create an A/B experiment between baseline and new version."""
        from uuid import UUID

        experiment = await experiments_repo.create(
            conn,
            prompt_id=UUID(prompt_id),
            name=f"auto-optimize-{new_version_id[:8]}",
        )
        await experiments_repo.add_arm(
            conn, experiment["id"], UUID(baseline_version_id), 100.0 - float(weight), "baseline"
        )
        await experiments_repo.add_arm(
            conn, experiment["id"], UUID(new_version_id), float(weight), "candidate"
        )
        await experiments_repo.update_status(conn, experiment["id"], "running")
        return json.dumps({"experiment_id": str(experiment["id"]), "status": "running"})

    async def conclude_experiment(experiment_id: str) -> str:
        """Conclude an experiment."""
        from uuid import UUID

        await experiments_repo.update_status(conn, UUID(experiment_id), "concluded")
        return json.dumps({"experiment_id": experiment_id, "status": "concluded"})

    return [
        get_prompt, get_metrics, get_sample_interactions,
        create_version, create_experiment, conclude_experiment,
    ]


async def trigger_optimization(
    data: OptimizeRequest,
    conn: asyncpg.Connection,
    settings: PromptManagerSettings,
) -> OptimizeResponse:
    """Trigger an optimization run using autoresearcher-shonku.

    This builds prompt-manager tools, wraps them, and delegates to the
    AutoResearcherAgent which runs on shonku → agno.
    """
    try:
        from autoresearcher_shonku import AutoResearcherAgent
        from shonku import LLMConfig
    except ImportError:
        return OptimizeResponse(
            status="error",
            message=(
                "autoresearcher-shonku is not installed. "
                "Install with: pip install autoresearcher-shonku"
            ),
        )

    if not settings.llm_api_key:
        return OptimizeResponse(
            status="error",
            message="PM_LLM_API_KEY is not configured. Set it to enable optimization.",
        )

    llm_config = LLMConfig(
        provider=settings.llm_provider,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        api_base=settings.llm_api_base,
    )

    tools = _build_tools(conn)
    agent = AutoResearcherAgent()

    logger.info("Starting optimization for prompt '%s'", data.prompt_slug)

    objective = data.objective or f"Improve prompt '{data.prompt_slug}' based on collected metrics"
    input_text = (
        f"Optimize the prompt with slug '{data.prompt_slug}'. "
        f"Objective: {objective}. "
        "Run one iteration of the autoresearch loop: analyze, propose, validate safety, "
        "and report your findings."
    )

    try:
        result = await agent.run(
            input=input_text,
            llm_config=llm_config,
            tools=tools,
        )
        logger.info(
            "Optimization for '%s' %s (%d tool calls)",
            data.prompt_slug,
            "succeeded" if result.success else "failed",
            result.tool_calls_made,
        )
        return OptimizeResponse(
            status="completed" if result.success else "failed",
            message=result.content,
        )
    except Exception as exc:
        logger.exception("Optimization for '%s' raised an exception", data.prompt_slug)
        return OptimizeResponse(
            status="error",
            message=f"Optimization failed: {exc}",
        )
