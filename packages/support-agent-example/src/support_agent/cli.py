"""arpm-support CLI — run the customer support agent example.

Commands:
    arpm-support seed    Seed prompt templates into the API
    arpm-support run     Handle a support request with the agent
    arpm-support loop    Run the full autoresearch optimization loop
    arpm-support status  Check API connection and prompt count
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def _get_config():
    """Load config from env vars."""
    api_url = os.environ.get("PM_API_URL", "http://localhost:8910")
    llm_provider = os.environ.get("PM_LLM_PROVIDER", "groq")
    llm_model = os.environ.get("PM_LLM_MODEL", "openai/gpt-oss-120b")
    llm_api_key = os.environ.get("PM_LLM_API_KEY") or os.environ.get("GROQ_API_KEY")
    db_url = os.environ.get(
        "PM_DATABASE_URL",
        "postgresql://prompt_manager:prompt_manager@localhost:15432/prompt_manager",
    )
    return {
        "api_url": api_url,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "llm_api_key": llm_api_key,
        "db_url": db_url,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="arpm-support",
        description="Autoresearch Prompt Manager — Customer Support Agent Example",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("seed", help="Seed prompt templates into the API")

    run_p = sub.add_parser("run", help="Handle a support request with the agent")
    run_p.add_argument(
        "task",
        nargs="?",
        default="A customer says their account is locked and they cannot log in",
        help="Support request to handle",
    )

    sub.add_parser("loop", help="Run the full autoresearch optimization loop")
    sub.add_parser("status", help="Check API connection and prompt count")

    args = parser.parse_args()

    if args.command == "seed":
        asyncio.run(_seed())
    elif args.command == "run":
        asyncio.run(_run(args.task))
    elif args.command == "loop":
        asyncio.run(_loop())
    elif args.command == "status":
        asyncio.run(_status())
    else:
        parser.print_help()
        print("\nRequired env vars:")
        print("  PM_LLM_API_KEY  or  GROQ_API_KEY    LLM API key")
        print()
        print("Optional env vars:")
        print("  PM_API_URL       http://localhost:8910")
        print("  PM_LLM_PROVIDER  groq")
        print("  PM_LLM_MODEL     openai/gpt-oss-120b")
        print("  PM_DATABASE_URL  postgresql://...")
        sys.exit(1)


async def _seed() -> None:
    import httpx

    cfg = _get_config()
    seed_file = Path(__file__).parent.parent.parent / "prompts" / "seed_prompts.json"
    if not seed_file.exists():
        print(f"Seed file not found: {seed_file}")
        sys.exit(1)

    prompts = json.loads(seed_file.read_text())
    async with httpx.AsyncClient(base_url=cfg["api_url"], timeout=10) as client:
        for p in prompts:
            resp = await client.post("/prompts", json={
                "slug": p["slug"],
                "name": p["name"],
                "description": p.get("description", ""),
                "body": p["content"],
                "tags": p.get("tags", []),
            })
            if resp.status_code == 201:
                print(f"  Seeded: {p['slug']}")
            elif resp.status_code == 409:
                print(f"  Exists: {p['slug']}")
            else:
                print(f"  Error ({resp.status_code}): {p['slug']}")

    print("Done.")


async def _run(task: str) -> None:
    from support_agent.agent import CustomerSupportAgent
    from support_agent.tools import create_prompt_manager_tools
    from prompt_manager.client import PromptManagerClient
    from shonku import LLMConfig

    cfg = _get_config()
    if not cfg["llm_api_key"]:
        print("Error: Set PM_LLM_API_KEY or GROQ_API_KEY")
        sys.exit(1)

    client = PromptManagerClient(base_url=cfg["api_url"])
    tools = create_prompt_manager_tools(client)
    agent = CustomerSupportAgent()
    llm_config = LLMConfig(
        provider=cfg["llm_provider"],
        model=cfg["llm_model"],
        api_key=cfg["llm_api_key"],
    )

    print(f"Task: {task}")
    print(f"Model: {cfg['llm_provider']}/{cfg['llm_model']}")
    print()

    result = await agent.run(
        input=(
            f"{task}. Use resolve_prompt to get a template, "
            "rate_response to score CSAT/tone/resolution, report_metric to log."
        ),
        llm_config=llm_config,
        tools=tools,
    )

    print(result.content)
    print(f"\nTool calls: {result.tool_calls_made}")
    await client.close()


async def _loop() -> None:
    """Run the full autoresearch loop from demo_full_loop."""
    from support_agent.demo_full_loop import main as loop_main

    await loop_main()


async def _status() -> None:
    import httpx

    cfg = _get_config()
    try:
        async with httpx.AsyncClient(base_url=cfg["api_url"], timeout=5) as client:
            health = await client.get("/health")
            prompts = await client.get("/prompts")
            data = prompts.json()
            count = data.get("total", len(data.get("items", [])))
            print(f"API: {cfg['api_url']} ({health.status_code})")
            print(f"Prompts: {count}")
            print(f"LLM: {cfg['llm_provider']}/{cfg['llm_model']}")
            print(f"API key: {'set' if cfg['llm_api_key'] else 'NOT SET'}")
    except Exception as e:
        print(f"Cannot connect to API: {e}")
        print("  Is the API running? Try: arpm-api start")
        sys.exit(1)


if __name__ == "__main__":
    main()
