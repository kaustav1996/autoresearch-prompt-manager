"""
Full Loop Demo: Multi-version prompts, experiment routing, autoresearcher optimization

This script demonstrates the complete autoresearch-prompt-manager stack for
Instagram content creation:

1. Create an Instagram caption prompt with 2 versions (minimal vs emoji-rich)
2. Set up an A/B experiment with 50/50 routing
3. Run the Instagram content agent multiple times — routed to different versions
4. Agent rates each version and reports engagement_rate metrics
5. Autoresearcher analyzes metrics, proposes a NEW improved version, deploys it

Stack: marketing-agent → prompt-manager → autoresearcher-shonku → shonku → agno → Groq

Metrics tracked per version:
  - engagement_rate  (composite: likes + comments + shares + saves / views)
  - views            (simulated impressions)
  - likes, comments, shares, saves (simulated interaction counts)

Usage:
    # Start API first:
    PM_DATABASE_URL=postgresql://prompt_manager:prompt_manager@localhost:15432/prompt_manager \\
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

PROMPT_SLUG = "ig-post-caption"


async def setup_prompt_and_versions(api: httpx.AsyncClient) -> dict:
    """Create an Instagram caption prompt with 2 versions and return IDs."""
    print("=" * 60)
    print("STEP 1: Create Instagram caption prompt with 2 versions")
    print("=" * 60)

    # v1 — minimal, clean style
    resp = await api.post("/prompts", json={
        "slug": PROMPT_SLUG,
        "name": "Instagram Post Caption",
        "body": (
            "{hook}\n\n"
            "{body}\n\n"
            "👇 {call_to_action}\n\n"
            "#{niche} #{brand}"
        ),
        "tags": ["instagram", "caption"],
    })
    data = resp.json()
    prompt_id = data["id"]
    print(f"  v1 (minimal): {prompt_id}")

    # Get v1 ID
    resp = await api.get(f"/prompts/{PROMPT_SLUG}/versions")
    v1_id = resp.json()[0]["id"]

    # v2 — emoji-rich, high-energy style
    resp = await api.post(f"/prompts/{PROMPT_SLUG}/versions", json={
        "body": (
            "✨ {hook} ✨\n\n"
            "🔥 {body} 🔥\n\n"
            "💬 Comment your thoughts below!\n"
            "❤️ Save this for later\n"
            "👉 Link in bio\n\n"
            "#instagood #{niche} #{brand} #viral #explore #trending"
        ),
    })
    v2_id = resp.json()["id"]
    print(f"  v2 (emoji-rich): {v2_id}")

    return {"prompt_id": prompt_id, "v1_id": v1_id, "v2_id": v2_id}


async def create_experiment(api: httpx.AsyncClient, ids: dict) -> str:
    """Create a 50/50 A/B experiment."""
    print("\n" + "=" * 60)
    print("STEP 2: Create A/B experiment (50/50 routing)")
    print("=" * 60)

    resp = await api.post("/experiments", json={
        "prompt_slug": PROMPT_SLUG,
        "name": "minimal-vs-emoji-rich",
        "arms": [
            {"version_id": ids["v1_id"], "weight": 50, "label": "minimal"},
            {"version_id": ids["v2_id"], "weight": 50, "label": "emoji-rich"},
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
    """Run the Instagram content agent N times with different sessions."""
    print("\n" + "=" * 60)
    print(f"STEP 3: Run agent {n_sessions} times (routed by experiment)")
    print("=" * 60)

    tools = create_prompt_manager_tools(client)
    agent = MarketingContentAgent()

    for i in range(n_sessions):
        session_id = f"creator-{i}"
        print(f"\n  --- Session: {session_id} ---")

        result = await agent.run(
            input=(
                f"Generate an Instagram post caption for session '{session_id}'. "
                f"Use resolve_prompt with slug='{PROMPT_SLUG}' and session_id='{session_id}'. "
                "Fill in variables: hook='Your morning routine is wrong', "
                "body='Here are 3 habits that changed everything for me', "
                "call_to_action='Save this post and try it tomorrow', "
                "niche='wellness', brand='dailyrise'. "
                "Rate it with rate_content using content_type='caption'. "
                "Report the engagement_rate metric with report_metric."
            ),
            llm_config=llm_config,
            tools=tools,
        )

        # Detect which version was served
        version_hint = "v?"
        if "✨" in result.content or "🔥" in result.content or "#viral" in result.content:
            version_hint = "v2 (emoji-rich)"
        elif "#wellness" in result.content or "👇" in result.content:
            version_hint = "v1 (minimal)"

        content_preview = result.content[:100].replace("\n", " ")
        print(f"  Routed to: {version_hint}")
        print(f"  Tool calls: {result.tool_calls_made}")
        print(f"  Preview: {content_preview}...")

        # Rate limit pause
        await asyncio.sleep(2)


async def check_metrics(api: httpx.AsyncClient, prompt_id: str) -> dict:
    """Check collected engagement_rate metrics per version."""
    print("\n" + "=" * 60)
    print("STEP 4: Check engagement_rate metrics per version")
    print("=" * 60)

    resp = await api.get(
        f"/metrics/aggregate?prompt_id={prompt_id}&metric_name=engagement_rate"
    )
    metrics = resp.json()

    # Get version numbers for display
    resp = await api.get(f"/prompts/{PROMPT_SLUG}/versions")
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
    """Run the autoresearcher to propose and deploy an improved caption version."""
    print("\n" + "=" * 60)
    print("STEP 5: Autoresearcher proposes improved Instagram caption version")
    print("=" * 60)

    from autoresearcher_shonku import AutoResearcherAgent

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
        prompt_id: str, version_id: str, metric_name: str = "engagement_rate"
    ) -> str:
        resp = await api.get(
            f"/metrics/aggregate?prompt_id={prompt_id}&metric_name={metric_name}"
        )
        return json.dumps(resp.json())

    async def get_sample_interactions(
        prompt_id: str, limit: str = "3"
    ) -> str:
        resp = await api.get(f"/prompts/{PROMPT_SLUG}/versions")
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
        # Create new 3-arm experiment
        resp = await api.get(f"/prompts/{PROMPT_SLUG}/versions")
        versions = resp.json()
        v1 = versions[0]["id"]
        v2 = versions[1]["id"]
        arms = [
            {"version_id": v1, "weight": 30, "label": "minimal"},
            {"version_id": v2, "weight": 30, "label": "emoji-rich"},
            {"version_id": new_version_id, "weight": 40, "label": "optimized"},
        ]
        resp = await api.post("/experiments", json={
            "prompt_slug": PROMPT_SLUG,
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
        ToolSpec(name="get_metrics", description="Get engagement metrics", callable=get_metrics),
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
            f"Analyze the '{PROMPT_SLUG}' Instagram caption prompt. "
            "There are 2 versions: v1 (minimal, clean) and v2 (emoji-rich, high-energy). "
            "Metrics show both score around 7-8/10 engagement_rate. "
            "Create a NEW v3 that combines the best of both: "
            "uses 1-2 strategic emojis, a strong scroll-stopping hook, "
            "a single clear CTA ('save this' or 'link in bio'), "
            "and 5-8 niche hashtags instead of generic viral ones. "
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
    resp = await api.get(f"/prompts/{PROMPT_SLUG}/versions")
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
    """Run agent again to verify routing includes the optimized v3."""
    print("\n" + "=" * 60)
    print("STEP 6: Verify new routing includes optimized version")
    print("=" * 60)

    versions_seen = set()
    for i in range(6):
        session_id = f"verify-creator-{i}"
        resp = await client._client.get(
            f"/resolve/{PROMPT_SLUG}?session_id={session_id}"
        )
        data = resp.json()
        versions_seen.add(data["version"])
        print(f"  {session_id} → v{data['version']}")

    print(f"\n  Versions routed to: {sorted(versions_seen)}")
    if len(versions_seen) >= 2:
        print("  Multi-version routing confirmed!")


async def main():
    print("=" * 60)
    print("  FULL LOOP DEMO: Instagram Content Autoresearch")
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
