"""Configuration for the marketing content agent."""

from __future__ import annotations

from pydantic import BaseModel


class MarketingAgentConfig(BaseModel):
    """Runtime configuration for the marketing agent example."""

    prompt_manager_url: str = "http://localhost:8910"
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-20250514"
    llm_api_key: str | None = None
    auto_optimize: bool = True
    optimization_interval_hours: int = 6
