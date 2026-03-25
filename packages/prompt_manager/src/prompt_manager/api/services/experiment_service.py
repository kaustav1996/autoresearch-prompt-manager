"""Service layer for experiment lifecycle and weighted routing."""

from __future__ import annotations

import logging
import random
import struct
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from prompt_manager.api.db import experiments_repo, versions_repo
from prompt_manager.core.enums import ExperimentStatus
from prompt_manager.core.exceptions import (
    ExperimentNotFoundError,
    ExperimentStateError,
    InvalidWeightsError,
    PromptNotFoundError,
)
from prompt_manager.core.models import Experiment, ExperimentArm, PromptVersion
from prompt_manager.core.schemas import ArmCreate

logger = logging.getLogger(__name__)

# ── MurmurHash3 (32-bit, pure-Python) ────────────────────────────────────

def _murmur3_32(key: bytes, seed: int = 0) -> int:
    """MurmurHash3 32-bit implementation for deterministic routing."""
    length = len(key)
    h = seed & 0xFFFFFFFF
    c1 = 0xCC9E2D51
    c2 = 0x1B873593
    idx = 0

    # body
    while idx + 4 <= length:
        k = struct.unpack_from("<I", key, idx)[0]
        k = (k * c1) & 0xFFFFFFFF
        k = ((k << 15) | (k >> 17)) & 0xFFFFFFFF
        k = (k * c2) & 0xFFFFFFFF
        h ^= k
        h = ((h << 13) | (h >> 19)) & 0xFFFFFFFF
        h = (h * 5 + 0xE6546B64) & 0xFFFFFFFF
        idx += 4

    # tail
    tail = length - idx
    k = 0
    if tail >= 3:
        k ^= key[idx + 2] << 16
    if tail >= 2:
        k ^= key[idx + 1] << 8
    if tail >= 1:
        k ^= key[idx]
        k = (k * c1) & 0xFFFFFFFF
        k = ((k << 15) | (k >> 17)) & 0xFFFFFFFF
        k = (k * c2) & 0xFFFFFFFF
        h ^= k

    # finalisation
    h ^= length
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & 0xFFFFFFFF
    h ^= h >> 16
    return h


def pick_arm_deterministic(
    arms: list[ExperimentArm], experiment_id: UUID, session_id: str
) -> ExperimentArm:
    """Deterministic arm selection using MurmurHash3."""
    key = f"{experiment_id}:{session_id}".encode()
    h = _murmur3_32(key)
    bucket = (h % 10000) / 100.0  # 0 .. 99.99
    cumulative = 0.0
    for arm in arms:
        cumulative += arm.weight
        if bucket < cumulative:
            return arm
    return arms[-1]


def pick_arm_random(arms: list[ExperimentArm]) -> ExperimentArm:
    """Weighted random arm selection."""
    weights = [a.weight for a in arms]
    return random.choices(arms, weights=weights, k=1)[0]


# ── Valid state transitions ───────────────────────────────────────────────

_VALID_TRANSITIONS: dict[ExperimentStatus, set[ExperimentStatus]] = {
    ExperimentStatus.DRAFT: {ExperimentStatus.RUNNING},
    ExperimentStatus.RUNNING: {ExperimentStatus.PAUSED, ExperimentStatus.CONCLUDED},
    ExperimentStatus.PAUSED: {ExperimentStatus.RUNNING, ExperimentStatus.CONCLUDED},
    ExperimentStatus.CONCLUDED: set(),
}


# ── Public API ────────────────────────────────────────────────────────────

async def create_experiment(
    conn: asyncpg.Connection,
    *,
    prompt_id: UUID,
    name: str,
    sticky: bool = True,
    auto_optimize: bool = False,
    min_sample_size: int = 100,
    arms: list[ArmCreate] | None = None,
) -> tuple[Experiment, list[ExperimentArm]]:
    if arms:
        total = sum(a.weight for a in arms)
        if abs(total - 100.0) > 0.01:
            raise InvalidWeightsError(total)

    experiment = await experiments_repo.create(
        conn,
        prompt_id=prompt_id,
        name=name,
        sticky=sticky,
        auto_optimize=auto_optimize,
        min_sample_size=min_sample_size,
    )
    created_arms: list[ExperimentArm] = []
    for arm_data in (arms or []):
        arm = await experiments_repo.add_arm(
            conn,
            experiment_id=experiment.id,
            version_id=arm_data.version_id,
            weight=arm_data.weight,
            label=arm_data.label,
        )
        created_arms.append(arm)
    return experiment, created_arms


async def update_status(
    conn: asyncpg.Connection, experiment_id: UUID, new_status: ExperimentStatus
) -> Experiment:
    exp = await experiments_repo.get_by_id(conn, experiment_id)
    if exp is None:
        raise ExperimentNotFoundError(str(experiment_id))
    allowed = _VALID_TRANSITIONS.get(exp.status, set())
    if new_status not in allowed:
        raise ExperimentStateError(exp.status.value, new_status.value)
    updated = await experiments_repo.update_status(conn, experiment_id, new_status)
    if updated is None:
        raise ExperimentNotFoundError(str(experiment_id))
    return updated


async def resolve_arm(
    conn: asyncpg.Connection,
    experiment: Experiment,
    session_id: str | None,
) -> tuple[ExperimentArm, PromptVersion]:
    """Pick an arm for this request and return (arm, version)."""
    arms = await experiments_repo.get_arms(conn, experiment.id)
    if not arms:
        raise ExperimentNotFoundError(str(experiment.id))

    arm: ExperimentArm
    if session_id and experiment.sticky:
        # Check for existing assignment
        existing_arm_id = await experiments_repo.get_session_assignment(
            conn, experiment.id, session_id
        )
        if existing_arm_id:
            arm = next((a for a in arms if a.id == existing_arm_id), arms[0])
        else:
            arm = pick_arm_deterministic(arms, experiment.id, session_id)
            await experiments_repo.save_session_assignment(
                conn, experiment.id, session_id, arm.id
            )
    elif session_id:
        arm = pick_arm_deterministic(arms, experiment.id, session_id)
    else:
        arm = pick_arm_random(arms)

    version = await versions_repo.get_by_id(conn, arm.version_id)
    if version is None:
        raise PromptNotFoundError(f"version {arm.version_id}")
    return arm, version
