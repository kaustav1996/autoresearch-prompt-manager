"""FastAPI dependency-injection helpers."""

from __future__ import annotations

from typing import AsyncIterator

import asyncpg  # type: ignore[import-untyped]

from prompt_manager.api.db.engine import get_pool
from prompt_manager.core.config import PromptManagerSettings


async def get_conn() -> AsyncIterator[asyncpg.Connection]:
    """Yield a connection from the asyncpg pool."""
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn


_settings: PromptManagerSettings | None = None


def get_settings() -> PromptManagerSettings:
    """Return a cached settings singleton."""
    global _settings
    if _settings is None:
        _settings = PromptManagerSettings()
    return _settings
