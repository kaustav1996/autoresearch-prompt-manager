"""Pydantic domain models for the prompt-manager."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from prompt_manager.core.enums import ExperimentStatus, VersionSource


class Prompt(BaseModel):
    """A managed prompt, addressed by a human-readable slug."""

    id: UUID
    slug: str
    name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    current_version: int = 1
    created_at: datetime
    updated_at: datetime


class PromptVersion(BaseModel):
    """Immutable, append-only snapshot of a prompt body."""

    id: UUID
    prompt_id: UUID
    version: int
    body: str
    model_hint: str | None = None
    template_vars: list[str] = Field(default_factory=list)
    content_hash: str
    parent_version: int | None = None
    source: VersionSource = VersionSource.MANUAL
    created_at: datetime


class Experiment(BaseModel):
    """An A/B experiment attached to a prompt."""

    id: UUID
    prompt_id: UUID
    name: str
    status: ExperimentStatus = ExperimentStatus.DRAFT
    sticky: bool = True
    auto_optimize: bool = False
    min_sample_size: int = 100
    created_at: datetime


class ExperimentArm(BaseModel):
    """One arm (variant) in an experiment, pointing to a prompt version."""

    id: UUID
    experiment_id: UUID
    version_id: UUID
    weight: float  # 0-100, basis-points internally
    label: str | None = None


class MetricEvent(BaseModel):
    """A single metric data-point reported against a prompt version."""

    prompt_id: UUID
    version_id: UUID
    experiment_id: UUID | None = None
    arm_id: UUID | None = None
    session_id: str | None = None
    metric_name: str
    metric_value: float
    metadata: dict = Field(default_factory=dict)
