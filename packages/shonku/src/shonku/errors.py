"""Shonku error hierarchy."""

from __future__ import annotations


class ShonkuError(Exception):
    """Base exception for all shonku errors."""


class ToolConflictError(ShonkuError):
    """Raised when two tools share the same name."""

    def __init__(self, name: str) -> None:
        self.tool_name = name
        super().__init__(f"Tool name conflict: '{name}' is already registered")


class MissingToolError(ShonkuError):
    """Raised when a required tool is not provided."""

    def __init__(self, missing: list[str]) -> None:
        self.missing_tools = missing
        names = ", ".join(f"'{n}'" for n in missing)
        super().__init__(f"Required tools not provided: {names}")


class LLMConfigError(ShonkuError):
    """Raised for invalid or unsupported LLM configuration."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"Unsupported LLM provider: '{provider}'")


class AgentRunError(ShonkuError):
    """Raised when an agent run fails."""

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        self.cause = cause
        super().__init__(message)
