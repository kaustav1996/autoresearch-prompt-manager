"""Service layer for prompt CRUD and version management."""

from __future__ import annotations

import asyncpg  # type: ignore[import-untyped]

from prompt_manager.api.db import prompts_repo, versions_repo
from prompt_manager.core.enums import VersionSource
from prompt_manager.core.exceptions import (
    DuplicateContentError,
    DuplicateSlugError,
    PromptNotFoundError,
    VersionNotFoundError,
)
from prompt_manager.core.models import Prompt, PromptVersion
from prompt_manager.core.schemas import PromptCreate, PromptUpdate


async def create_prompt(
    conn: asyncpg.Connection, data: PromptCreate
) -> tuple[Prompt, PromptVersion]:
    """Create a new prompt with its initial version."""
    existing = await prompts_repo.get_by_slug(conn, data.slug)
    if existing is not None:
        raise DuplicateSlugError(data.slug)

    prompt = await prompts_repo.create(
        conn,
        slug=data.slug,
        name=data.name,
        description=data.description,
        tags=data.tags,
        metadata=data.metadata,
    )
    version = await versions_repo.create(
        conn,
        prompt_id=prompt.id,
        body=data.body,
        model_hint=data.model_hint,
        template_vars=data.template_vars,
        source=VersionSource.MANUAL,
    )
    return prompt, version


async def get_prompt(conn: asyncpg.Connection, slug: str) -> Prompt:
    prompt = await prompts_repo.get_by_slug(conn, slug)
    if prompt is None:
        raise PromptNotFoundError(slug)
    return prompt


async def list_prompts(
    conn: asyncpg.Connection, *, limit: int = 50, offset: int = 0
) -> tuple[list[Prompt], int]:
    return await prompts_repo.list_prompts(conn, limit=limit, offset=offset)


async def update_prompt(conn: asyncpg.Connection, slug: str, data: PromptUpdate) -> Prompt:
    fields = data.model_dump(exclude_none=True)
    prompt = await prompts_repo.update(conn, slug, **fields)
    if prompt is None:
        raise PromptNotFoundError(slug)
    return prompt


async def add_version(
    conn: asyncpg.Connection,
    slug: str,
    *,
    body: str,
    model_hint: str | None = None,
    template_vars: list[str] | None = None,
    source: VersionSource = VersionSource.MANUAL,
) -> PromptVersion:
    """Add a new immutable version to a prompt. Dedup by content hash."""
    prompt = await get_prompt(conn, slug)
    chash = versions_repo.content_hash(body)
    if await versions_repo.hash_exists(conn, prompt.id, chash):
        raise DuplicateContentError(chash)
    version = await versions_repo.create(
        conn,
        prompt_id=prompt.id,
        body=body,
        model_hint=model_hint,
        template_vars=template_vars,
        source=source,
    )
    await prompts_repo.set_current_version(conn, prompt.id, version.version)
    return version


async def get_version(conn: asyncpg.Connection, slug: str, version: int) -> PromptVersion:
    prompt = await get_prompt(conn, slug)
    pv = await versions_repo.get_by_version(conn, prompt.id, version)
    if pv is None:
        raise VersionNotFoundError(slug, version)
    return pv


async def get_latest_version(conn: asyncpg.Connection, slug: str) -> PromptVersion:
    prompt = await get_prompt(conn, slug)
    pv = await versions_repo.get_latest(conn, prompt.id)
    if pv is None:
        raise VersionNotFoundError(slug, 0)
    return pv


async def list_versions(conn: asyncpg.Connection, slug: str) -> list[PromptVersion]:
    prompt = await get_prompt(conn, slug)
    return await versions_repo.list_versions(conn, prompt.id)


async def archive_prompt(conn: asyncpg.Connection, slug: str) -> bool:
    return await prompts_repo.archive(conn, slug)
