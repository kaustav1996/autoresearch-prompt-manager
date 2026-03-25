"""Router for /optimize trigger."""

from __future__ import annotations

import asyncpg  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends

from prompt_manager.api.deps import get_conn, get_settings
from prompt_manager.api.services import optimization_service
from prompt_manager.core.config import PromptManagerSettings
from prompt_manager.core.schemas import OptimizeRequest, OptimizeResponse

router = APIRouter(prefix="/optimize", tags=["optimize"])


@router.post("", response_model=OptimizeResponse, status_code=202)
async def trigger_optimization(
    data: OptimizeRequest,
    conn: asyncpg.Connection = Depends(get_conn),
    settings: PromptManagerSettings = Depends(get_settings),
) -> OptimizeResponse:
    return await optimization_service.trigger_optimization(data, conn, settings)
