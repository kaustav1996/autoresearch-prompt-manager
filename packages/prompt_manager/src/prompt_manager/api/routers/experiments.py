"""Router for /experiments CRUD."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, HTTPException

from prompt_manager.api.db import experiments_repo
from prompt_manager.api.deps import get_conn
from prompt_manager.api.services import experiment_service, prompt_service
from prompt_manager.core.exceptions import (
    ExperimentNotFoundError,
    ExperimentStateError,
    InvalidWeightsError,
    PromptNotFoundError,
)
from prompt_manager.core.schemas import (
    ArmResponse,
    ExperimentCreate,
    ExperimentResponse,
    ExperimentStatusUpdate,
)

router = APIRouter(prefix="/experiments", tags=["experiments"])

Conn = Annotated[asyncpg.Connection, Depends(get_conn)]


@router.post("", response_model=ExperimentResponse, status_code=201)
async def create_experiment(data: ExperimentCreate, conn: Conn) -> ExperimentResponse:
    try:
        prompt = await prompt_service.get_prompt(conn, data.prompt_slug)
    except PromptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        exp, arms = await experiment_service.create_experiment(
            conn,
            prompt_id=prompt.id,
            name=data.name,
            sticky=data.sticky,
            auto_optimize=data.auto_optimize,
            min_sample_size=data.min_sample_size,
            arms=data.arms or None,
        )
    except InvalidWeightsError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ExperimentResponse(
        **exp.model_dump(),
        arms=[ArmResponse(**a.model_dump()) for a in arms],
    )


@router.get("/{experiment_id}", response_model=ExperimentResponse)
async def get_experiment(experiment_id: UUID, conn: Conn) -> ExperimentResponse:
    exp = await experiments_repo.get_by_id(conn, experiment_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    arms = await experiments_repo.get_arms(conn, experiment_id)
    return ExperimentResponse(
        **exp.model_dump(),
        arms=[ArmResponse(**a.model_dump()) for a in arms],
    )


@router.patch("/{experiment_id}/status", response_model=ExperimentResponse)
async def update_experiment_status(
    experiment_id: UUID, data: ExperimentStatusUpdate, conn: Conn
) -> ExperimentResponse:
    try:
        exp = await experiment_service.update_status(conn, experiment_id, data.status)
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ExperimentStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    arms = await experiments_repo.get_arms(conn, experiment_id)
    return ExperimentResponse(
        **exp.model_dump(),
        arms=[ArmResponse(**a.model_dump()) for a in arms],
    )
