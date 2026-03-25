"""MCP server exposing prompt management tools.

Run standalone:
    python -m prompt_manager.api.mcp.server

Or start alongside the FastAPI app via the ``--mcp`` flag.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from prompt_manager.api.db import experiments_repo, metrics_repo, prompts_repo, versions_repo
from prompt_manager.core.config import PromptManagerSettings

try:
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False


def _json(data: Any) -> list:
    """Helper to return MCP TextContent with JSON payload."""
    return [TextContent(type="text", text=json.dumps(data, default=str))]


def create_mcp_server(settings: PromptManagerSettings) -> "Server":
    """Build an MCP server with prompt management tools."""
    if not _MCP_AVAILABLE:
        raise ImportError("mcp package is not installed. pip install mcp")

    server = Server("prompt-manager")
    _pool: asyncpg.Pool | None = None

    async def _get_conn() -> asyncpg.Connection:
        nonlocal _pool
        if _pool is None:
            _pool = await asyncpg.create_pool(dsn=settings.database_url, min_size=1, max_size=3)
        return await _pool.acquire()

    async def _release(conn: asyncpg.Connection) -> None:
        if _pool:
            await _pool.release(conn)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="list_prompts",
                description="List all prompts with optional tag filter",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string", "description": "Filter by tag"},
                    },
                },
            ),
            Tool(
                name="get_prompt",
                description="Get a prompt by slug with its latest version content",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string", "description": "Prompt slug"},
                    },
                    "required": ["slug"],
                },
            ),
            Tool(
                name="resolve_prompt",
                description="Resolve a prompt (experiment-aware). Returns the content to use.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string"},
                        "session_id": {"type": "string"},
                        "version": {"type": "integer"},
                    },
                    "required": ["slug"],
                },
            ),
            Tool(
                name="create_prompt",
                description="Create a new prompt with initial content",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string"},
                        "name": {"type": "string"},
                        "content": {"type": "string"},
                        "description": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["slug", "name", "content"],
                },
            ),
            Tool(
                name="create_version",
                description="Create a new version of an existing prompt",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["slug", "content"],
                },
            ),
            Tool(
                name="get_experiment",
                description="Get experiment status and metrics for a prompt",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "prompt_slug": {"type": "string"},
                    },
                    "required": ["prompt_slug"],
                },
            ),
            Tool(
                name="optimize_prompt",
                description="Trigger LLM-based optimization for a prompt",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string"},
                        "objective": {"type": "string"},
                    },
                    "required": ["slug"],
                },
            ),
            Tool(
                name="report_metric",
                description="Report a quality metric for a prompt version",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "prompt_id": {"type": "string"},
                        "version_id": {"type": "string"},
                        "metric_name": {"type": "string"},
                        "value": {"type": "number"},
                    },
                    "required": ["prompt_id", "version_id", "metric_name", "value"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list:
        conn = await _get_conn()
        try:
            if name == "list_prompts":
                rows = await prompts_repo.list_all(conn)
                return _json([dict(r) for r in rows])

            elif name == "get_prompt":
                prompt = await prompts_repo.get_by_slug(conn, arguments["slug"])
                if not prompt:
                    return _json({"error": f"Prompt '{arguments['slug']}' not found"})
                version = await versions_repo.get_latest(conn, prompt["id"])
                return _json({
                    **dict(prompt),
                    "body": version["body"] if version else None,
                    "version": version["version"] if version else None,
                })

            elif name == "resolve_prompt":
                from prompt_manager.api.services.experiment_service import resolve_prompt

                result = await resolve_prompt(
                    conn,
                    arguments["slug"],
                    version=arguments.get("version"),
                    session_id=arguments.get("session_id"),
                )
                return _json(result)

            elif name == "create_prompt":
                from prompt_manager.api.services.prompt_service import create_prompt
                from prompt_manager.core.schemas import PromptCreate

                data = PromptCreate(
                    slug=arguments["slug"],
                    name=arguments["name"],
                    body=arguments["content"],
                    description=arguments.get("description"),
                    tags=arguments.get("tags", []),
                )
                prompt, version = await create_prompt(conn, data)
                return _json({"prompt_id": str(prompt.id), "version": version.version})

            elif name == "create_version":
                prompt = await prompts_repo.get_by_slug(conn, arguments["slug"])
                if not prompt:
                    return _json({"error": f"Prompt '{arguments['slug']}' not found"})
                version = await versions_repo.create(
                    conn, prompt_id=prompt["id"], body=arguments["content"], source="manual"
                )
                return _json({"version_id": str(version["id"]), "version": version["version"]})

            elif name == "get_experiment":
                prompt = await prompts_repo.get_by_slug(conn, arguments["prompt_slug"])
                if not prompt:
                    return _json({"error": "Prompt not found"})
                exp = await experiments_repo.get_running_for_prompt(conn, prompt["id"])
                if not exp:
                    return _json({"status": "no_running_experiment"})
                arms = await experiments_repo.get_arms(conn, exp["id"])
                return _json({"experiment": dict(exp), "arms": [dict(a) for a in arms]})

            elif name == "optimize_prompt":
                from prompt_manager.api.services.optimization_service import trigger_optimization
                from prompt_manager.core.schemas import OptimizeRequest

                result = await trigger_optimization(
                    OptimizeRequest(
                        prompt_slug=arguments["slug"],
                        objective=arguments.get("objective"),
                    ),
                    conn,
                    PromptManagerSettings(),
                )
                return _json({"status": result.status, "message": result.message})

            elif name == "report_metric":
                from uuid import UUID

                await metrics_repo.insert(
                    conn,
                    prompt_id=UUID(arguments["prompt_id"]),
                    version_id=UUID(arguments["version_id"]),
                    metric_name=arguments["metric_name"],
                    metric_value=arguments["value"],
                )
                return _json({"status": "recorded"})

            else:
                return _json({"error": f"Unknown tool: {name}"})
        finally:
            await _release(conn)

    return server


async def main() -> None:
    """Run the MCP server on stdio."""
    from mcp.server.stdio import stdio_server

    settings = PromptManagerSettings()
    server = create_mcp_server(settings)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream)


if __name__ == "__main__":
    asyncio.run(main())
