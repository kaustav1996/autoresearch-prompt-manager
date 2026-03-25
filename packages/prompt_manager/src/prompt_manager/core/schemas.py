"""Request / response schemas for the prompt-manager API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from prompt_manager.core.enums import ExperimentStatus, VersionSource

# ── Prompt ────────────────────────────────────────────────────────────────

class PromptCreate(BaseModel):
    slug: str
    name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    body: str  # initial version body
    model_hint: str | None = None
    template_vars: list[str] = Field(default_factory=list)


class PromptUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    metadata: dict | None = None


class PromptResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str | None = None
    tags: list[str]
    metadata: dict
    current_version: int
    created_at: datetime
    updated_at: datetime


class PromptListResponse(BaseModel):
    items: list[PromptResponse]
    total: int


# ── Version ───────────────────────────────────────────────────────────────

class VersionCreate(BaseModel):
    body: str
    model_hint: str | None = None
    template_vars: list[str] = Field(default_factory=list)
    source: VersionSource = VersionSource.MANUAL


class VersionResponse(BaseModel):
    id: UUID
    prompt_id: UUID
    version: int
    body: str
    model_hint: str | None = None
    template_vars: list[str]
    content_hash: str
    parent_version: int | None = None
    source: VersionSource
    created_at: datetime


# ── Experiment ────────────────────────────────────────────────────────────

class ArmCreate(BaseModel):
    version_id: UUID
    weight: float
    label: str | None = None


class ExperimentCreate(BaseModel):
    prompt_slug: str
    name: str
    sticky: bool = True
    auto_optimize: bool = False
    min_sample_size: int = 100
    arms: list[ArmCreate] = Field(default_factory=list)


class ExperimentStatusUpdate(BaseModel):
    status: ExperimentStatus


class ArmResponse(BaseModel):
    id: UUID
    experiment_id: UUID
    version_id: UUID
    weight: float
    label: str | None = None


class ExperimentResponse(BaseModel):
    id: UUID
    prompt_id: UUID
    name: str
    status: ExperimentStatus
    sticky: bool
    auto_optimize: bool
    min_sample_size: int
    arms: list[ArmResponse] = Field(default_factory=list)
    created_at: datetime


# ── Metric ────────────────────────────────────────────────────────────────

class MetricIngest(BaseModel):
    prompt_id: UUID
    version_id: UUID
    experiment_id: UUID | None = None
    arm_id: UUID | None = None
    session_id: str | None = None
    metric_name: str
    metric_value: float
    metadata: dict = Field(default_factory=dict)


class MetricBatchIngest(BaseModel):
    events: list[MetricIngest]


class MetricAggregation(BaseModel):
    version_id: UUID
    metric_name: str
    count: int
    mean: float
    stddev: float | None = None
    min_val: float
    max_val: float


# ── Resolve ───────────────────────────────────────────────────────────────

class ResolveResponse(BaseModel):
    slug: str
    version: int
    body: str
    model_hint: str | None = None
    template_vars: list[str]
    content_hash: str
    experiment_id: UUID | None = None
    arm_id: UUID | None = None
    version_id: UUID


# ── Optimize ──────────────────────────────────────────────────────────────

class OptimizeRequest(BaseModel):
    prompt_slug: str
    objective: str | None = None


class OptimizeResponse(BaseModel):
    status: str
    message: str
