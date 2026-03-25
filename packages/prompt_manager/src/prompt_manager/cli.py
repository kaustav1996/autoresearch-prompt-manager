"""CLI entry points for prompt-manager."""

from __future__ import annotations

import argparse
import asyncio
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="prompt-manager", description="Prompt Manager CLI")
    sub = parser.add_subparsers(dest="command")

    # serve
    serve_p = sub.add_parser("serve", help="Start the API server")
    serve_p.add_argument("--host", default=None, help="Bind host (default: from PM_HOST)")
    serve_p.add_argument("--port", type=int, default=None, help="Bind port (default: from PM_PORT)")

    # migrate
    sub.add_parser("migrate", help="Run database migrations")

    # health
    sub.add_parser("health", help="Check API health")

    args = parser.parse_args()

    if args.command == "serve":
        _serve(args)
    elif args.command == "migrate":
        asyncio.run(_migrate())
    elif args.command == "health":
        asyncio.run(_health())
    else:
        parser.print_help()
        sys.exit(1)


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    from prompt_manager.api.app import create_app
    from prompt_manager.core.config import PromptManagerSettings

    settings = PromptManagerSettings()
    host = args.host or settings.host
    port = args.port or settings.port

    app = create_app(settings)
    uvicorn.run(app, host=host, port=port)


async def _migrate() -> None:
    from prompt_manager.api.db.engine import run_migrations
    from prompt_manager.core.config import PromptManagerSettings

    settings = PromptManagerSettings()
    print(f"Running migrations against {settings.database_url[:40]}...")
    await run_migrations(settings)
    print("Migrations complete.")


async def _health() -> None:
    import httpx

    from prompt_manager.core.config import PromptManagerSettings

    settings = PromptManagerSettings()
    url = f"http://{settings.host}:{settings.port}/health"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=5)
            print(f"{resp.status_code} {resp.json()}")
    except Exception as e:
        print(f"Health check failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
