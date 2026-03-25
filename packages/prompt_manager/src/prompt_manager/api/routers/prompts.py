"""CRUD router for /prompts."""

from __future__ import annotations

from typing import Annotated

import asyncpg  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, HTTPException, Query

from prompt_manager.api.deps import get_conn
from prompt_manager.api.services import prompt_service
from prompt_manager.core.exceptions import DuplicateSlugError, PromptNotFoundError
from prompt_manager.core.schemas import (
    PromptCreate,
    PromptListResponse,
    PromptResponse,
    PromptUpdate,
)

router = APIRouter(prefix="/prompts", tags=["prompts"])

Conn = Annotated[asyncpg.Connection, Depends(get_conn)]


@router.post("", response_model=PromptResponse, status_code=201)
async def create_prompt(data: PromptCreate, conn: Conn) -> PromptResponse:
    try:
        prompt, _version = await prompt_service.create_prompt(conn, data)
    except DuplicateSlugError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return PromptResponse(**prompt.model_dump())


@router.get("", response_model=PromptListResponse)
async def list_prompts(
    conn: Conn,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> PromptListResponse:
    items, total = await prompt_service.list_prompts(conn, limit=limit, offset=offset)
    return PromptListResponse(
        items=[PromptResponse(**p.model_dump()) for p in items],
        total=total,
    )


@router.get("/{slug}", response_model=PromptResponse)
async def get_prompt(slug: str, conn: Conn) -> PromptResponse:
    try:
        prompt = await prompt_service.get_prompt(conn, slug)
    except PromptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return PromptResponse(**prompt.model_dump())


@router.patch("/{slug}", response_model=PromptResponse)
async def update_prompt(slug: str, data: PromptUpdate, conn: Conn) -> PromptResponse:
    try:
        prompt = await prompt_service.update_prompt(conn, slug, data)
    except PromptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return PromptResponse(**prompt.model_dump())


@router.delete("/{slug}", status_code=204)
async def delete_prompt(slug: str, conn: Conn) -> None:
    deleted = await prompt_service.archive_prompt(conn, slug)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Prompt not found: {slug}")
