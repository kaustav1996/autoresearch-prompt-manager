"""arpm-api CLI — manage the prompt-manager API server.

Commands:
    arpm-api up        Start PostgreSQL via Docker Compose
    arpm-api start     Run migrations + start the API server
    arpm-api migrate   Run database migrations only
    arpm-api health    Check API health
    arpm-api stop      Stop Docker Compose services
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="arpm-api",
        description="Autoresearch Prompt Manager — API server",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("up", help="Start PostgreSQL via Docker Compose")

    start_p = sub.add_parser("start", help="Run migrations + start API server")
    start_p.add_argument("--host", default=None, help="Bind host")
    start_p.add_argument("--port", type=int, default=None, help="Bind port")

    sub.add_parser("migrate", help="Run database migrations only")
    sub.add_parser("health", help="Check API health")
    sub.add_parser("stop", help="Stop Docker Compose services")

    args = parser.parse_args()

    if args.command == "up":
        _up()
    elif args.command == "start":
        _start(args)
    elif args.command == "migrate":
        asyncio.run(_migrate())
    elif args.command == "health":
        asyncio.run(_health())
    elif args.command == "stop":
        _stop()
    else:
        parser.print_help()
        sys.exit(1)


def _find_compose_file() -> str | None:
    """Walk up from cwd to find docker-compose.yml."""
    d = os.getcwd()
    for _ in range(10):
        candidate = os.path.join(d, "docker-compose.yml")
        if os.path.exists(candidate):
            return candidate
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _up() -> None:
    compose = _find_compose_file()
    if not compose:
        print("docker-compose.yml not found. Run from the project root.")
        sys.exit(1)
    print("Starting PostgreSQL...")
    subprocess.run(
        ["docker", "compose", "-f", compose, "up", "-d"],
        check=True,
    )
    print("PostgreSQL is running. Set PM_DATABASE_URL if needed.")


def _stop() -> None:
    compose = _find_compose_file()
    if not compose:
        print("docker-compose.yml not found.")
        sys.exit(1)
    subprocess.run(
        ["docker", "compose", "-f", compose, "down"],
        check=True,
    )
    print("Services stopped.")


def _start(args: argparse.Namespace) -> None:
    import uvicorn

    from prompt_manager.api.app import create_app
    from prompt_manager.core.config import PromptManagerSettings

    settings = PromptManagerSettings()
    host = args.host or settings.host
    port = args.port or settings.port

    print(f"Starting Prompt Manager API on {host}:{port}")
    print(f"  Database: {settings.database_url[:50]}...")
    print(f"  Docs: http://{host}:{port}/docs")
    print()

    app = create_app(settings)
    uvicorn.run(app, host=host, port=port)


async def _migrate() -> None:
    from prompt_manager.api.db.engine import run_migrations
    from prompt_manager.core.config import PromptManagerSettings

    settings = PromptManagerSettings()
    print(f"Running migrations against {settings.database_url[:50]}...")
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
