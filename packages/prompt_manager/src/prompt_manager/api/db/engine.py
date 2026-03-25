"""asyncpg connection-pool management."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg  # type: ignore[import-untyped]

from prompt_manager.core.config import PromptManagerSettings

_pool: asyncpg.Pool | None = None


async def create_pool(settings: PromptManagerSettings) -> asyncpg.Pool:
    """Create and return an asyncpg connection pool."""
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
    )
    return _pool


async def close_pool() -> None:
    """Close the global pool if it exists."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """Return the current pool, raising if not initialised."""
    if _pool is None:
        raise RuntimeError("Database pool has not been initialised.")
    return _pool


@asynccontextmanager
async def get_connection() -> AsyncIterator[asyncpg.Connection]:
    """Acquire a connection from the pool as an async context manager."""
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn


async def run_migrations(settings: PromptManagerSettings) -> None:
    """Apply SQL migrations from the migrations directory."""
    import pathlib

    migrations_dir = pathlib.Path(__file__).parent.parent.parent.parent.parent / "migrations"
    if not migrations_dir.exists():
        return

    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        applied = {row["name"] for row in await conn.fetch("SELECT name FROM _migrations")}

        # If tables already exist (e.g. from Docker initdb.d) but not tracked,
        # mark the initial migration as applied without re-running it.
        if not applied:
            has_tables = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'prompts')"
            )
            if has_tables:
                for sql_file in sorted(migrations_dir.glob("*.sql")):
                    await conn.execute(
                        "INSERT INTO _migrations (name) VALUES ($1)", sql_file.name
                    )
                return

        for sql_file in sorted(migrations_dir.glob("*.sql")):
            if sql_file.name not in applied:
                sql = sql_file.read_text()
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO _migrations (name) VALUES ($1)", sql_file.name
                )
    finally:
        await conn.close()
