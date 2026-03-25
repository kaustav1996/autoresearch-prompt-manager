"""Repository for the ``prompt_versions`` table."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]

from prompt_manager.core.enums import VersionSource
from prompt_manager.core.models import PromptVersion


def _row_to_version(row: asyncpg.Record) -> PromptVersion:
    tvars = row["template_vars"] or []
    return PromptVersion(
        id=row["id"],
        prompt_id=row["prompt_id"],
        version=row["version"],
        body=row["body"],
        model_hint=row["model_hint"],
        template_vars=tvars,
        content_hash=row["content_hash"],
        parent_version=row["parent_version"],
        source=VersionSource(row["source"]),
        created_at=row["created_at"],
    )


def content_hash(body: str) -> str:
    """SHA-256 hash of the prompt body for dedup."""
    return hashlib.sha256(body.encode()).hexdigest()


async def create(
    conn: asyncpg.Connection,
    *,
    prompt_id: UUID,
    body: str,
    model_hint: str | None = None,
    template_vars: list[str] | None = None,
    source: VersionSource = VersionSource.MANUAL,
) -> PromptVersion:
    """Append a new immutable version (auto-increments version number)."""
    latest_version: int = await conn.fetchval(
        "SELECT COALESCE(MAX(version), 0) FROM prompt_versions WHERE prompt_id = $1",
        prompt_id,
    )
    new_version = latest_version + 1
    chash = content_hash(body)
    now = datetime.now(timezone.utc)
    row = await conn.fetchrow(
        """
        INSERT INTO prompt_versions
            (id, prompt_id, version, body, model_hint, template_vars,
             content_hash, parent_version, source, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING *
        """,
        uuid4(),
        prompt_id,
        new_version,
        body,
        model_hint,
        template_vars or [],
        chash,
        latest_version if latest_version > 0 else None,
        source.value,
        now,
    )
    return _row_to_version(row)


async def get_latest(conn: asyncpg.Connection, prompt_id: UUID) -> PromptVersion | None:
    row = await conn.fetchrow(
        "SELECT * FROM prompt_versions WHERE prompt_id = $1 ORDER BY version DESC LIMIT 1",
        prompt_id,
    )
    return _row_to_version(row) if row else None


async def get_by_version(
    conn: asyncpg.Connection, prompt_id: UUID, version: int
) -> PromptVersion | None:
    row = await conn.fetchrow(
        "SELECT * FROM prompt_versions WHERE prompt_id = $1 AND version = $2",
        prompt_id,
        version,
    )
    return _row_to_version(row) if row else None


async def get_by_id(conn: asyncpg.Connection, version_id: UUID) -> PromptVersion | None:
    row = await conn.fetchrow("SELECT * FROM prompt_versions WHERE id = $1", version_id)
    return _row_to_version(row) if row else None


async def list_versions(
    conn: asyncpg.Connection, prompt_id: UUID
) -> list[PromptVersion]:
    rows = await conn.fetch(
        "SELECT * FROM prompt_versions WHERE prompt_id = $1 ORDER BY version ASC",
        prompt_id,
    )
    return [_row_to_version(r) for r in rows]


async def hash_exists(conn: asyncpg.Connection, prompt_id: UUID, chash: str) -> bool:
    val = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM prompt_versions WHERE prompt_id = $1 AND content_hash = $2)",
        prompt_id,
        chash,
    )
    return bool(val)
