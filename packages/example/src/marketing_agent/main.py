"""
Example: Marketing Content Agent with Auto-Optimizing Prompts

This demonstrates the full stack:
  example (marketing-agent)
    -> prompt-manager (API + client)
    -> autoresearcher-shonku
    -> shonku
    -> agno

Workflow:
1. Connect to the prompt-manager API
2. Seed initial prompt templates
3. Run the marketing agent to generate content
4. Collect quality metrics
5. Autoresearcher improves prompts over time

Usage::

    # First, start the prompt-manager API:
    #   PM_DATABASE_URL=postgresql://... python -m prompt_manager.api.main

    # Then run the example:
    python -m marketing_agent.main
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from marketing_agent.agent import MarketingContentAgent
from marketing_agent.config import MarketingAgentConfig
from marketing_agent.tools import create_prompt_manager_tools
from prompt_manager.client import PromptManagerClient
from shonku import LLMConfig


async def seed_prompts(client: PromptManagerClient) -> None:
    """Seed the prompt manager with initial marketing templates."""
    seed_file = Path(__file__).parent.parent.parent / "prompts" / "seed_prompts.json"
    if not seed_file.exists():
        print("  No seed file found, skipping seeding")
        return

    prompts = json.loads(seed_file.read_text())
    for p in prompts:
        try:
            resp = await client._client.post(
                "/prompts",
                json={
                    "slug": p["slug"],
                    "name": p["name"],
                    "description": p.get("description", ""),
                    "body": p["content"],
                    "tags": p.get("tags", []),
                },
            )
            if resp.status_code == 201:
                print(f"  Seeded: {p['slug']}")
            elif resp.status_code == 409:
                print(f"  Exists: {p['slug']}")
            else:
                print(f"  Unexpected status {resp.status_code} for {p['slug']}")
        except Exception as e:
            print(f"  Error seeding {p['slug']}: {e}")


async def generate_content(
    agent: MarketingContentAgent,
    llm_config: LLMConfig,
    tools: list,
) -> None:
    """Generate various marketing content pieces and display results."""
    tasks = [
        "Generate a welcome email for a new user named Alice joining TechCorp",
        "Write an engaging social media post announcing a new AI feature at TechCorp",
        "Create ad copy for TechCorp's new productivity tool that saves 2 hours per day",
        "Write a compelling product description for TechCorp's AI Assistant",
    ]

    for task in tasks:
        print(f"\n{'=' * 60}")
        print(f"Task: {task}")
        print(f"{'=' * 60}")
        result = await agent.run(
            input=task,
            llm_config=llm_config,
            tools=tools,
        )
        print(f"\nResult:\n{result.content}")
        print(f"\nTool calls: {result.tool_calls_made}")


async def main() -> None:
    """Run the full marketing agent example."""
    config = MarketingAgentConfig()

    llm_config = LLMConfig(
        provider=config.llm_provider,
        model=config.llm_model,
        api_key=config.llm_api_key,
    )

    client = PromptManagerClient(base_url=config.prompt_manager_url)
    tools = create_prompt_manager_tools(client)
    agent = MarketingContentAgent()

    print("=== Marketing Content Agent Example ===\n")

    # Step 1: Seed prompts
    print("1. Seeding prompt templates...")
    await seed_prompts(client)

    # Step 2: Generate content
    print("\n2. Generating marketing content...")
    await generate_content(agent, llm_config, tools)

    # Step 3: Show how optimization would work
    print(f"\n{'=' * 60}")
    print("3. Optimization loop (conceptual)")
    print(f"{'=' * 60}")
    print("   In production, autoresearcher-shonku would:")
    print("   - Analyze metrics collected from generated content")
    print("   - Propose improved prompt versions")
    print("   - Shadow test improvements at 5% traffic")
    print("   - Promote winners, discard losers")
    print("   - Continuously improve prompt quality")

    await client.close()
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
