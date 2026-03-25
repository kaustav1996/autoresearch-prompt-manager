"""Application configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class PromptManagerSettings(BaseSettings):
    """All settings are read from env vars prefixed with ``PM_``."""

    model_config = SettingsConfigDict(env_prefix="PM_", env_file=".env")

    # Database
    database_url: str = "postgresql://localhost:5432/prompt_manager"
    db_pool_min: int = 2
    db_pool_max: int = 10

    # HTTP server
    host: str = "0.0.0.0"
    port: int = 8910

    # LLM for optimisation (forwarded to autoresearcher-shonku)
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-20250514"
    llm_api_key: str | None = None
    llm_api_base: str | None = None


def get_settings() -> PromptManagerSettings:
    """Return a cached settings instance."""
    return PromptManagerSettings()
