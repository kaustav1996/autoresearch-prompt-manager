"""
Full Loop Demo: Multi-version prompts, experiment routing, autoresearcher optimization

This script demonstrates the complete autoresearch-prompt-manager stack:

1. Create a prompt with 2 versions (formal vs casual)
2. Set up an A/B experiment with 50/50 routing
3. Run the marketing agent multiple times — it gets routed to different versions
4. Agent rates each version and reports metrics
5. Autoresearcher analyzes metrics, proposes a NEW improved version, deploys it

Stack: marketing-agent → prompt-manager → autoresearcher-shonku → shonku → agno → Groq

Usage:
    # Start API first:
    PM_DATABASE_URL=postgresql://prompt_manager:prompt_manager@localhost:15432/prompt_manager \
        python3 -m prompt_manager.api.main

    # Then run:
    python3 -m marketing_agent.demo_full_loop
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx

from marketing_agent.agent import MarketingContentAgent
from marketing_agent.tools import create_prompt_manager_tools
from prompt_manager.client import PromptManagerClient
from shonku import LLMConfig
from shonku.types import ToolSpec

GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
API_URL = os.environ.get("PM_API_URL", "http://localhost:8910")
DB_URL = os.environ.get(
    "PM_DATABASE_URL",
    "postgresql://prompt_manager:prompt_manager@localhost:15432/prompt_manager",
)


async def setup_prompt_and_versions(api: httpx.AsyncClient) -> dict:
    """Create a prompt with 2 versions and return IDs."""
    print("=" * 60)
    print("STEP 1: Create prompt with 2 versions")
    print("=" * 60)

    # Create prompt (v1 - formal)
    resp = await api.post("/prompts", json={
        "slug": "welcome-demo",
        "name": "Welcome Email Demo",
        "body": (
            "Dear {name},\n\n"
            "We are pleased to inform you that your account at {company} "
            "has been successfully created.\n\n"
            "Please proceed to your dashboard to configure your settings.\n\n"
            "Regards,\nThe {company} Team"
        ),
        "tags": ["email", "onboarding"],
    })
    data = resp.json()
    prompt_id = data["id"]
    print(f"  v1 (formal): {prompt_id}")

    # Get v1 ID
    resp = await api.get("/prompts/welcome-demo/versions")
    v1_id = resp.json()[0]["id"]

    # Create v2 (casual)
    resp = await api.post("/prompts/welcome-demo/versions", json={
        "body": (
            "Hey {name}! 🎉\n\n"
            "Welcome to {company}! We're SO excited you're here.\n\n"
            "Jump right in and explore what we've built for you. "
            "Trust us, you're going to love it!\n\n"
            "Cheers,\nThe {company} Crew"
        ),
    })
    v2_id = resp.json()["id"]
    print(f"  v2 (casual): {v2_id}")

    return {"prompt_id": prompt_id, "v1_id": v1_id, "v2_id": v2_id}


async def create_experiment(api: httpx.AsyncClient, ids: dict) -> str:
    """Create a 50/50 A/B experiment."""
    print("\n" + "=" * 60)
    print("STEP 2: Create A/B experiment (50/50 routing)")
    print("=" * 60)

    resp = await api.post("/experiments", json={
        "prompt_slug": "welcome-demo",
        "name": "formal-vs-casual",
        "arms": [
            {"version_id": ids["v1_id"], "weight": 50, "label": "formal"},
            {"version_id": ids["v2_id"], "weight": 50, "label": "casual"},
        ],
    })
    exp_id = resp.json()["id"]
    print(f"  Experiment: {exp_id}")

    # Start it
    await api.patch(f"/experiments/{exp_id}/status", json={"status": "running"})
    print("  Status: RUNNING")

    return exp_id


async def run_agent_sessions(
    client: PromptManagerClient,
    llm_config: LLMConfig,
    n_sessions: int = 6,
) -> None:
    """Run the marketing agent N times with different sessions."""
    print("\n" + "=" * 60)
    print(f"STEP 3: Run agent {n_sessions} times (routed by experiment)")
    print("=" * 60)

    tools = create_prompt_manager_tools(client)
    agent = MarketingContentAgent()

    for i in range(n_sessions):
        session_id = f"demo-user-{i}"
        print(f"\n  --- Session: {session_id} ---")

        result = await agent.run(
            input=(
                f"Generate a welcome email for user '{session_id}' joining TechCorp. "
                f"Use resolve_prompt with slug='welcome-demo' and session_id='{session_id}'. "
                "Generate content from the template. "
                "Rate it with rate_content. "
                "Report the metric with report_metric."
            ),
            llm_config=llm_config,
            tools=tools,
        )

        # Extract which version was used from the output
        version_hint = "v?"
        if "Dear" in result.content or "pleased" in result.content:
            version_hint = "v1 (formal)"
        elif "Hey" in result.content or "excited" in result.content or "🎉" in result.content:
            version_hint = "v2 (casual)"

        content_preview = result.content[:100].replace("\n", " ")
        print(f"  Routed to: {version_hint}")
        print(f"  Tool calls: {result.tool_calls_made}")
        print(f"  Preview: {content_preview}...")

        # Rate limit pause
        await asyncio.sleep(2)


async def check_metrics(api: httpx.AsyncClient, prompt_id: str) -> dict:
    """Check collected metrics per version."""
    print("\n" + "=" * 60)
    print("STEP 4: Check metrics per version")
    print("=" * 60)

    resp = await api.get(
        f"/metrics/aggregate?prompt_id={prompt_id}&metric_name=quality_score"
    )
    metrics = resp.json()

    # Get version numbers for display
    resp = await api.get("/prompts/welcome-demo/versions")
    versions = {v["id"]: v["version"] for v in resp.json()}

    for m in metrics:
        v_num = versions.get(m["version_id"], "?")
        print(
            f"  v{v_num}: count={m['count']}, "
            f"mean={m['mean']:.2f}, "
            f"min={m['min_val']:.1f}, max={m['max_val']:.1f}"
        )

    return {m["version_id"]: m for m in metrics}


async def run_autoresearcher(
    api: httpx.AsyncClient,
    client: PromptManagerClient,
    llm_config: LLMConfig,
    ids: dict,
    exp_id: str,
) -> None:
    """Run the autoresearcher to propose and deploy an improved version."""
    print("\n" + "=" * 60)
    print("STEP 5: Autoresearcher proposes improved version")
    print("=" * 60)

    from autoresearcher_shonku import AutoResearcherAgent

    # Build tools that autoresearcher needs (wrapping the API)
    async def get_prompt(slug: str) -> str:
        resp = await api.get(f"/prompts/{slug}")
        p = resp.json()
        resp2 = await api.get(f"/prompts/{slug}/versions")
        versions = resp2.json()
        latest = versions[-1]
        return json.dumps({
            "id": p["id"], "slug": p["slug"],
            "body": latest["body"], "version": latest["version"],
            "version_id": latest["id"],
        })

    async def get_metrics(
        prompt_id: str, version_id: str, metric_name: str = "quality_score"
    ) -> str:
        resp = await api.get(
            f"/metrics/aggregate?prompt_id={prompt_id}&metric_name={metric_name}"
        )
        return json.dumps(resp.json())

    async def get_sample_interactions(
        prompt_id: str, limit: str = "3"
    ) -> str:
        resp = await api.get("/prompts/welcome-demo/versions")
        versions = resp.json()
        samples = []
        for v in versions:
            samples.append({
                "version": v["version"],
                "body": v["body"][:100],
                "source": v.get("source", "manual"),
            })
        return json.dumps(samples)

    async def create_version(slug: str, content: str) -> str:
        resp = await api.post(
            f"/prompts/{slug}/versions", json={"body": content}
        )
        d = resp.json()
        return json.dumps({
            "version_id": d["id"], "version": d["version"]
        })

    async def create_experiment(
        prompt_id: str, baseline_version_id: str,
        new_version_id: str, weight: str = "10"
    ) -> str:
        # Conclude old experiment first
        await api.patch(
            f"/experiments/{exp_id}/status",
            json={"status": "concluded"},
        )
        # Create new one with 3 arms
        resp = await api.get("/prompts/welcome-demo/versions")
        versions = resp.json()
        v1 = versions[0]["id"]
        v2 = versions[1]["id"]
        arms = [
            {"version_id": v1, "weight": 30, "label": "formal"},
            {"version_id": v2, "weight": 30, "label": "casual"},
            {"version_id": new_version_id, "weight": 40, "label": "optimized"},
        ]
        resp = await api.post("/experiments", json={
            "prompt_slug": "welcome-demo",
            "name": "optimized-routing",
            "arms": arms,
        })
        new_exp = resp.json()
        await api.patch(
            f"/experiments/{new_exp['id']}/status",
            json={"status": "running"},
        )
        return json.dumps({
            "experiment_id": new_exp["id"],
            "status": "running",
            "arms": [
                {"label": a["label"], "weight": a["weight"]}
                for a in arms
            ],
        })

    async def conclude_experiment(experiment_id: str) -> str:
        await api.patch(
            f"/experiments/{experiment_id}/status",
            json={"status": "concluded"},
        )
        return json.dumps({"status": "concluded"})

    ar_tools = [
        ToolSpec(name="get_prompt", description="Get prompt by slug", callable=get_prompt),
        ToolSpec(name="get_metrics", description="Get metrics", callable=get_metrics),
        ToolSpec(
            name="get_sample_interactions",
            description="Get sample versions",
            callable=get_sample_interactions,
        ),
        ToolSpec(
            name="create_version",
            description="Create improved prompt version",
            callable=create_version,
        ),
        ToolSpec(
            name="create_experiment",
            description="Create experiment with routing",
            callable=create_experiment,
        ),
        ToolSpec(
            name="conclude_experiment",
            description="Conclude experiment",
            callable=conclude_experiment,
        ),
    ]

    agent = AutoResearcherAgent()
    result = await agent.run(
        input=(
            "Analyze the 'welcome-demo' prompt. There are 2 versions: "
            "v1 (formal, stiff) and v2 (casual, enthusiastic). "
            "Metrics show both score around 7-8/10. "
            "Create a NEW v3 that combines the best of both: "
            "professional but warm, with a clear CTA. "
            "Then deploy a new experiment with v1=30%, v2=30%, v3=40%. "
            "Use the tools provided. Do NOT invent tool names."
        ),
        llm_config=llm_config,
        tools=ar_tools,
    )

    print(f"  Success: {result.success}")
    print(f"  Tool calls: {result.tool_calls_made}")
    print(f"  Summary: {result.content[:300]}")

    # Show what versions exist now
    resp = await api.get("/prompts/welcome-demo/versions")
    versions = resp.json()
    print(f"\n  Versions after optimization: {len(versions)}")
    for v in versions:
        label = v.get("source", "manual")
        print(f"    v{v['version']} ({label}): {v['body'][:60]}...")


async def verify_new_routing(
    api: httpx.AsyncClient,
    client: PromptManagerClient,
    llm_config: LLMConfig,
) -> None:
    """Run agent again to see it get routed to the new version."""
    print("\n" + "=" * 60)
    print("STEP 6: Verify new routing includes optimized version")
    print("=" * 60)

    versions_seen = set()
    for i in range(6):
        session_id = f"verify-user-{i}"
        resp = await client._client.get(
            f"/resolve/welcome-demo?session_id={session_id}"
        )
        data = resp.json()
        versions_seen.add(data["version"])
        print(f"  {session_id} → v{data['version']}")

    print(f"\n  Versions routed to: {sorted(versions_seen)}")
    if len(versions_seen) >= 2:
        print("  Multi-version routing confirmed!")


async def main():
    print("=" * 60)
    print("  FULL LOOP DEMO: Autoresearch Prompt Manager")
    print("  Model: Groq gpt-oss-120b")
    print("=" * 60)

    if not GROQ_KEY:
        print("\nError: GROQ_API_KEY environment variable is required.")
        print("  export GROQ_API_KEY=gsk_...")
        return

    api = httpx.AsyncClient(base_url=API_URL, timeout=60)
    client = PromptManagerClient(base_url=API_URL)
    llm_config = LLMConfig(
        provider="groq",
        model="openai/gpt-oss-120b",
        api_key=GROQ_KEY,
    )

    # Clean slate
    import asyncpg
    conn = await asyncpg.connect(DB_URL)
    for t in [
        "metric_events", "session_assignments", "experiment_arms",
        "experiments", "optimization_runs", "prompt_versions", "prompts",
    ]:
        await conn.execute(f"DELETE FROM {t}")
    await conn.close()

    try:
        # Step 1: Create prompt + versions
        ids = await setup_prompt_and_versions(api)

        # Step 2: Create experiment
        exp_id = await create_experiment(api, ids)

        # Step 3: Run agent multiple times
        await run_agent_sessions(client, llm_config, n_sessions=4)

        # Step 4: Check metrics
        await check_metrics(api, ids["prompt_id"])

        # Step 5: Autoresearcher creates v3 and adjusts routing
        await run_autoresearcher(api, client, llm_config, ids, exp_id)

        # Step 6: Verify new routing
        await verify_new_routing(api, client, llm_config)

    finally:
        await api.aclose()
        await client.close()

    print("\n" + "=" * 60)
    print("  DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
