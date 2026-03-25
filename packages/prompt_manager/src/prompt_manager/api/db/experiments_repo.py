"""Repository for ``experiments`` and ``experiment_arms`` tables."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]

from prompt_manager.core.enums import ExperimentStatus
from prompt_manager.core.models import Experiment, ExperimentArm


def _row_to_experiment(row: asyncpg.Record) -> Experiment:
    return Experiment(
        id=row["id"],
        prompt_id=row["prompt_id"],
        name=row["name"],
        status=ExperimentStatus(row["status"]),
        sticky=row["sticky"],
        auto_optimize=row["auto_optimize"],
        min_sample_size=row["min_sample_size"],
        created_at=row["created_at"],
    )


def _row_to_arm(row: asyncpg.Record) -> ExperimentArm:
    return ExperimentArm(
        id=row["id"],
        experiment_id=row["experiment_id"],
        version_id=row["version_id"],
        weight=row["weight"],
        label=row["label"],
    )


async def create(
    conn: asyncpg.Connection,
    *,
    prompt_id: UUID,
    name: str,
    sticky: bool = True,
    auto_optimize: bool = False,
    min_sample_size: int = 100,
) -> Experiment:
    now = datetime.now(timezone.utc)
    row = await conn.fetchrow(
        """
        INSERT INTO experiments
            (id, prompt_id, name, status, sticky, auto_optimize, min_sample_size, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING *
        """,
        uuid4(),
        prompt_id,
        name,
        ExperimentStatus.DRAFT.value,
        sticky,
        auto_optimize,
        min_sample_size,
        now,
    )
    return _row_to_experiment(row)


async def add_arm(
    conn: asyncpg.Connection,
    *,
    experiment_id: UUID,
    version_id: UUID,
    weight: float,
    label: str | None = None,
) -> ExperimentArm:
    row = await conn.fetchrow(
        """
        INSERT INTO experiment_arms (id, experiment_id, version_id, weight, label)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *
        """,
        uuid4(),
        experiment_id,
        version_id,
        weight,
        label,
    )
    return _row_to_arm(row)


async def get_by_id(conn: asyncpg.Connection, experiment_id: UUID) -> Experiment | None:
    row = await conn.fetchrow("SELECT * FROM experiments WHERE id = $1", experiment_id)
    return _row_to_experiment(row) if row else None


async def get_running_for_prompt(conn: asyncpg.Connection, prompt_id: UUID) -> Experiment | None:
    row = await conn.fetchrow(
        "SELECT * FROM experiments WHERE prompt_id = $1 AND status = $2 LIMIT 1",
        prompt_id,
        ExperimentStatus.RUNNING.value,
    )
    return _row_to_experiment(row) if row else None


async def get_arms(conn: asyncpg.Connection, experiment_id: UUID) -> list[ExperimentArm]:
    rows = await conn.fetch(
        "SELECT * FROM experiment_arms WHERE experiment_id = $1 ORDER BY weight DESC",
        experiment_id,
    )
    return [_row_to_arm(r) for r in rows]


async def update_status(
    conn: asyncpg.Connection, experiment_id: UUID, status: ExperimentStatus
) -> Experiment | None:
    row = await conn.fetchrow(
        "UPDATE experiments SET status = $1 WHERE id = $2 RETURNING *",
        status.value,
        experiment_id,
    )
    return _row_to_experiment(row) if row else None


async def get_session_assignment(
    conn: asyncpg.Connection, experiment_id: UUID, session_id: str
) -> UUID | None:
    return await conn.fetchval(
        "SELECT arm_id FROM session_assignments WHERE experiment_id = $1 AND session_id = $2",
        experiment_id,
        session_id,
    )


async def save_session_assignment(
    conn: asyncpg.Connection,
    experiment_id: UUID,
    session_id: str,
    arm_id: UUID,
) -> None:
    await conn.execute(
        """
        INSERT INTO session_assignments (experiment_id, session_id, arm_id, created_at)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (experiment_id, session_id) DO NOTHING
        """,
        experiment_id,
        session_id,
        arm_id,
        datetime.now(timezone.utc),
    )
