"""Service layer for metric ingestion and aggregation."""

from __future__ import annotations

from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from prompt_manager.api.db import metrics_repo
from prompt_manager.core.models import MetricEvent
from prompt_manager.core.schemas import MetricAggregation, MetricIngest


async def ingest(conn: asyncpg.Connection, data: MetricIngest) -> UUID:
    """Ingest a single metric event."""
    event = MetricEvent(**data.model_dump())
    return await metrics_repo.insert(conn, event)


async def ingest_batch(conn: asyncpg.Connection, events: list[MetricIngest]) -> int:
    """Ingest a batch of metric events. Returns count inserted."""
    models = [MetricEvent(**e.model_dump()) for e in events]
    return await metrics_repo.insert_batch(conn, models)


async def aggregate(
    conn: asyncpg.Connection,
    prompt_id: UUID,
    metric_name: str,
) -> list[MetricAggregation]:
    """Return aggregated stats per version for the given metric."""
    return await metrics_repo.aggregate_by_version(conn, prompt_id, metric_name)
