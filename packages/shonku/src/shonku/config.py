"""Configuration models for LLM providers and agent behaviour."""

from __future__ import annotations

from pydantic import BaseModel

SUPPORTED_PROVIDERS = frozenset(
    {
        "anthropic",
        "openai",
        "groq",
        "gemini",
        "bedrock",
        "openrouter",
        "custom",
    }
)


class LLMConfig(BaseModel):
    """LLM provider configuration. Passed at runtime -- never stored."""

    provider: str  # one of SUPPORTED_PROVIDERS
    model: str
    api_key: str | None = None
    api_base: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096


class AgentConfig(BaseModel):
    """Optional runtime knobs for agent execution."""

    max_steps: int = 50
    timeout: float = 300.0
