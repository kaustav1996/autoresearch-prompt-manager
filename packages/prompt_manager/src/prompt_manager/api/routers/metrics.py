"""Router for /metrics ingest and aggregation."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, HTTPException, Query

from prompt_manager.api.deps import get_conn
from prompt_manager.api.services import metric_service
from prompt_manager.core.schemas import (
    MetricAggregation,
    MetricBatchIngest,
    MetricIngest,
)

router = APIRouter(prefix="/metrics", tags=["metrics"])

Conn = Annotated[asyncpg.Connection, Depends(get_conn)]


@router.post("", status_code=201)
async def ingest_metric(data: MetricIngest, conn: Conn) -> dict[str, str]:
    event_id = await metric_service.ingest(conn, data)
    return {"id": str(event_id)}


@router.post("/batch", status_code=201)
async def ingest_batch(data: MetricBatchIngest, conn: Conn) -> dict[str, int]:
    count = await metric_service.ingest_batch(conn, data.events)
    return {"inserted": count}


@router.get("/aggregate", response_model=list[MetricAggregation])
async def get_aggregation(
    prompt_id: UUID = Query(...),
    metric_name: str = Query(...),
    conn: Conn = None,  # type: ignore[assignment]
) -> list[MetricAggregation]:
    results = await metric_service.aggregate(conn, prompt_id, metric_name)
    if not results:
        raise HTTPException(status_code=404, detail="No metrics found")
    return results
