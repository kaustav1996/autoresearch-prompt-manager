"""Repository for the ``metric_events`` table."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]

from prompt_manager.core.models import MetricEvent
from prompt_manager.core.schemas import MetricAggregation


async def insert(conn: asyncpg.Connection, event: MetricEvent) -> UUID:
    """Insert a single metric event and return its id."""
    event_id = uuid4()
    await conn.execute(
        """
        INSERT INTO metric_events
            (id, prompt_id, version_id, experiment_id, arm_id, session_id,
             metric_name, metric_value, metadata, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
        """,
        event_id,
        event.prompt_id,
        event.version_id,
        event.experiment_id,
        event.arm_id,
        event.session_id,
        event.metric_name,
        event.metric_value,
        json.dumps(event.metadata),
        datetime.now(timezone.utc),
    )
    return event_id


async def insert_batch(conn: asyncpg.Connection, events: list[MetricEvent]) -> int:
    """Insert a batch of metric events. Returns number of rows inserted."""
    now = datetime.now(timezone.utc)
    records = [
        (
            uuid4(),
            e.prompt_id,
            e.version_id,
            e.experiment_id,
            e.arm_id,
            e.session_id,
            e.metric_name,
            e.metric_value,
            json.dumps(e.metadata),
            now,
        )
        for e in events
    ]
    await conn.executemany(
        """
        INSERT INTO metric_events
            (id, prompt_id, version_id, experiment_id, arm_id, session_id,
             metric_name, metric_value, metadata, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
        """,
        records,
    )
    return len(records)


async def aggregate_by_version(
    conn: asyncpg.Connection,
    prompt_id: UUID,
    metric_name: str,
) -> list[MetricAggregation]:
    """Aggregate a metric grouped by version_id."""
    rows = await conn.fetch(
        """
        SELECT
            version_id,
            $2 AS metric_name,
            count(*)::int AS count,
            avg(metric_value)::float AS mean,
            stddev(metric_value)::float AS stddev,
            min(metric_value)::float AS min_val,
            max(metric_value)::float AS max_val
        FROM metric_events
        WHERE prompt_id = $1 AND metric_name = $2
        GROUP BY version_id
        """,
        prompt_id,
        metric_name,
    )
    return [
        MetricAggregation(
            version_id=r["version_id"],
            metric_name=r["metric_name"],
            count=r["count"],
            mean=r["mean"],
            stddev=r["stddev"],
            min_val=r["min_val"],
            max_val=r["max_val"],
        )
        for r in rows
    ]
