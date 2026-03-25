"""Router for /resolve/{slug} -- the hot path."""

from __future__ import annotations

from typing import Annotated

import asyncpg  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from prompt_manager.api.db import experiments_repo
from prompt_manager.api.deps import get_conn
from prompt_manager.api.services import experiment_service, prompt_service
from prompt_manager.core.exceptions import PromptNotFoundError, VersionNotFoundError
from prompt_manager.core.schemas import ResolveResponse

router = APIRouter(prefix="/resolve", tags=["resolve"])

Conn = Annotated[asyncpg.Connection, Depends(get_conn)]


@router.get("/{slug}", response_model=ResolveResponse)
async def resolve_prompt(
    slug: str,
    conn: Conn,
    version: int | None = Query(None, description="Pin to a specific version"),
    session_id: str | None = Query(None, description="Session ID for sticky routing"),
) -> JSONResponse:
    """Resolve the active prompt body for a given slug.

    Resolution order:
    1. If ``version`` is specified, return that exact version.
    2. If a running experiment exists and ``session_id`` is provided,
       use deterministic hash routing.
    3. If a running experiment exists without ``session_id``,
       use weighted random routing.
    4. Otherwise return the latest version.
    """
    try:
        prompt = await prompt_service.get_prompt(conn, slug)
    except PromptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    experiment_id = None
    arm_id = None

    if version is not None:
        # Pinned version
        try:
            pv = await prompt_service.get_version(conn, slug, version)
        except VersionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    else:
        # Check for running experiment
        experiment = await experiments_repo.get_running_for_prompt(conn, prompt.id)
        if experiment is not None:
            arm, pv = await experiment_service.resolve_arm(conn, experiment, session_id)
            experiment_id = experiment.id
            arm_id = arm.id
        else:
            try:
                pv = await prompt_service.get_latest_version(conn, slug)
            except VersionNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc))

    body = ResolveResponse(
        slug=slug,
        version=pv.version,
        body=pv.body,
        model_hint=pv.model_hint,
        template_vars=pv.template_vars,
        content_hash=pv.content_hash,
        experiment_id=experiment_id,
        arm_id=arm_id,
        version_id=pv.id,
    )

    headers: dict[str, str] = {
        "X-Prompt-Version": str(pv.version),
        "X-Content-Hash": pv.content_hash,
    }
    if experiment_id:
        headers["X-Experiment-Id"] = str(experiment_id)
    if arm_id:
        headers["X-Arm-Id"] = str(arm_id)

    return JSONResponse(content=body.model_dump(mode="json"), headers=headers)
