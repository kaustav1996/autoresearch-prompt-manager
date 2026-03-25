"""Data models for autoresearcher-shonku."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Analysis(BaseModel):
    """Result of analyzing a prompt's performance."""

    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    priority_area: str = ""
    metrics_summary: dict[str, Any] = Field(default_factory=dict)


class Proposal(BaseModel):
    """A proposed prompt improvement."""

    improved_prompt: str
    reasoning: str = ""
    expected_improvement: str = ""
    risk: str = "low"  # low | medium | high
    template_vars_valid: bool = True
    similarity: float = 1.0


class SafetyCheck(BaseModel):
    """Result of running safety checks on a proposal."""

    safe: bool = False
    checks: dict[str, bool] = Field(default_factory=dict)
    similarity: float = 0.0
    blocked_reason: str | None = None


class ExperimentResult(BaseModel):
    """Outcome of a prompt experiment."""

    experiment_id: str = ""
    action: str = ""  # created | monitoring | concluded
    winner_version: str | None = None
    baseline_score: float = 0.0
    candidate_score: float = 0.0
    improved: bool = False
