"""
Example: Customer Support Agent with Auto-Optimizing Prompts

This demonstrates the full stack:
  support-agent-example
    -> prompt-manager (API + client)
    -> autoresearcher-shonku
    -> shonku
    -> agno

Workflow:
1. Connect to the prompt-manager API
2. Seed initial support prompt templates
3. Run the support agent to handle customer requests
4. Collect quality metrics (CSAT, tone, resolution)
5. Autoresearcher improves prompts over time

Usage::

    # First, start the prompt-manager API:
    #   PM_DATABASE_URL=postgresql://... python -m prompt_manager.api.main

    # Then run the example:
    python -m support_agent.main
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from prompt_manager.client import PromptManagerClient
from shonku import LLMConfig
from support_agent.agent import CustomerSupportAgent
from support_agent.config import SupportAgentConfig
from support_agent.tools import create_prompt_manager_tools


async def seed_prompts(client: PromptManagerClient) -> None:
    """Seed the prompt manager with initial support templates."""
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


async def handle_support_requests(
    agent: CustomerSupportAgent,
    llm_config: LLMConfig,
    tools: list,
) -> None:
    """Handle various support scenarios and display results."""
    tasks = [
        "A customer reports they cannot log into their account after resetting their password",
        "A customer is asking how to export their data from the platform",
        "A customer is very frustrated — their order has been delayed 3 times"
        " and they want a refund",
        "Decide whether to escalate: customer claims a bug caused"
        " data loss affecting their business",
    ]

    for task in tasks:
        print(f"\n{'=' * 60}")
        print(f"Request: {task}")
        print(f"{'=' * 60}")
        result = await agent.run(
            input=task,
            llm_config=llm_config,
            tools=tools,
        )
        print(f"\nResponse:\n{result.content}")
        print(f"\nTool calls: {result.tool_calls_made}")


async def main() -> None:
    """Run the full support agent example."""
    config = SupportAgentConfig()

    llm_config = LLMConfig(
        provider=config.llm_provider,
        model=config.llm_model,
        api_key=config.llm_api_key,
    )

    client = PromptManagerClient(base_url=config.prompt_manager_url)
    tools = create_prompt_manager_tools(client)
    agent = CustomerSupportAgent()

    print("=== Customer Support Agent Example ===\n")

    # Step 1: Seed prompts
    print("1. Seeding support prompt templates...")
    await seed_prompts(client)

    # Step 2: Handle support requests
    print("\n2. Handling customer support requests...")
    await handle_support_requests(agent, llm_config, tools)

    # Step 3: Show how optimization would work
    print(f"\n{'=' * 60}")
    print("3. Optimization loop (conceptual)")
    print(f"{'=' * 60}")
    print("   In production, autoresearcher-shonku would:")
    print("   - Analyze CSAT, tone, and resolution metrics per prompt version")
    print("   - Propose improved versions (more empathetic, clearer CTAs)")
    print("   - Shadow test improvements at 5% traffic")
    print("   - Promote winners, discard losers")
    print("   - Continuously improve support quality")

    await client.close()
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
