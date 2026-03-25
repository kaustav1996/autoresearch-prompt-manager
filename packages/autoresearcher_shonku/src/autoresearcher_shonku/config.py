"""Configuration for AutoResearcher agents."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AutoResearcherConfig(BaseModel):
    """Runtime configuration for the autonomous prompt optimization loop."""

    max_iterations: int = Field(default=10, ge=1, le=100)
    min_sample_size: int = Field(default=100, ge=10)
    improvement_threshold: float = Field(default=0.01, ge=0.0, le=1.0)
    max_edit_distance: float = Field(default=0.5, ge=0.0, le=1.0)
    canary_weight: float = Field(default=5.0, ge=0.0, le=100.0)
    cooldown_minutes: int = Field(default=30, ge=0)
    rollback_on_regression: bool = True
    simplicity_preference: bool = True
