"""Router for /prompts/{slug}/versions."""

from __future__ import annotations

from typing import Annotated

import asyncpg  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, HTTPException

from prompt_manager.api.deps import get_conn
from prompt_manager.api.services import prompt_service
from prompt_manager.core.exceptions import (
    DuplicateContentError,
    PromptNotFoundError,
    VersionNotFoundError,
)
from prompt_manager.core.schemas import VersionCreate, VersionResponse

router = APIRouter(prefix="/prompts/{slug}/versions", tags=["versions"])

Conn = Annotated[asyncpg.Connection, Depends(get_conn)]


@router.post("", response_model=VersionResponse, status_code=201)
async def create_version(slug: str, data: VersionCreate, conn: Conn) -> VersionResponse:
    try:
        version = await prompt_service.add_version(
            conn,
            slug,
            body=data.body,
            model_hint=data.model_hint,
            template_vars=data.template_vars,
            source=data.source,
        )
    except PromptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DuplicateContentError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return VersionResponse(**version.model_dump())


@router.get("", response_model=list[VersionResponse])
async def list_versions(slug: str, conn: Conn) -> list[VersionResponse]:
    try:
        versions = await prompt_service.list_versions(conn, slug)
    except PromptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return [VersionResponse(**v.model_dump()) for v in versions]


@router.get("/latest", response_model=VersionResponse)
async def get_latest_version(slug: str, conn: Conn) -> VersionResponse:
    try:
        version = await prompt_service.get_latest_version(conn, slug)
    except (PromptNotFoundError, VersionNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return VersionResponse(**version.model_dump())


@router.get("/{version}", response_model=VersionResponse)
async def get_version(slug: str, version: int, conn: Conn) -> VersionResponse:
    try:
        v = await prompt_service.get_version(conn, slug, version)
    except (PromptNotFoundError, VersionNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return VersionResponse(**v.model_dump())
