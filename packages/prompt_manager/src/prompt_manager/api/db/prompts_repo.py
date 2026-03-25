"""Repository for the ``prompts`` table."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]

from prompt_manager.core.models import Prompt


def _row_to_prompt(row: asyncpg.Record) -> Prompt:
    tags = row["tags"] or []
    raw = row["metadata"]
    meta = json.loads(raw) if isinstance(raw, str) else (raw or {})
    return Prompt(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        description=row["description"],
        tags=tags,
        metadata=meta,
        current_version=row["current_version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create(
    conn: asyncpg.Connection,
    *,
    slug: str,
    name: str,
    description: str | None = None,
    tags: list[str] | None = None,
    metadata: dict | None = None,
) -> Prompt:
    now = datetime.now(timezone.utc)
    row = await conn.fetchrow(
        """
        INSERT INTO prompts (id, slug, name, description, tags,
            metadata, current_version, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, 1, $7, $7)
        RETURNING *
        """,
        uuid4(),
        slug,
        name,
        description,
        tags or [],
        json.dumps(metadata or {}),
        now,
    )
    return _row_to_prompt(row)


async def get_by_slug(conn: asyncpg.Connection, slug: str) -> Prompt | None:
    row = await conn.fetchrow("SELECT * FROM prompts WHERE slug = $1", slug)
    return _row_to_prompt(row) if row else None


async def list_prompts(
    conn: asyncpg.Connection,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Prompt], int]:
    total: int = await conn.fetchval("SELECT count(*) FROM prompts")
    rows = await conn.fetch(
        "SELECT * FROM prompts ORDER BY created_at DESC LIMIT $1 OFFSET $2",
        limit,
        offset,
    )
    return [_row_to_prompt(r) for r in rows], total


async def update(
    conn: asyncpg.Connection,
    slug: str,
    **fields: Any,
) -> Prompt | None:
    sets: list[str] = []
    vals: list[Any] = []
    idx = 1
    for key, val in fields.items():
        if val is None:
            continue
        if key == "metadata":
            sets.append(f"metadata = ${idx}::jsonb")
            vals.append(json.dumps(val))
        else:
            sets.append(f"{key} = ${idx}")
            vals.append(val)
        idx += 1
    if not sets:
        return await get_by_slug(conn, slug)
    sets.append(f"updated_at = ${idx}")
    vals.append(datetime.now(timezone.utc))
    idx += 1
    vals.append(slug)
    query = f"UPDATE prompts SET {', '.join(sets)} WHERE slug = ${idx} RETURNING *"
    row = await conn.fetchrow(query, *vals)
    return _row_to_prompt(row) if row else None


async def set_current_version(conn: asyncpg.Connection, prompt_id: UUID, version: int) -> None:
    await conn.execute(
        "UPDATE prompts SET current_version = $1, updated_at = $2 WHERE id = $3",
        version,
        datetime.now(timezone.utc),
        prompt_id,
    )


async def archive(conn: asyncpg.Connection, slug: str) -> bool:
    result = await conn.execute("DELETE FROM prompts WHERE slug = $1", slug)
    return result == "DELETE 1"
