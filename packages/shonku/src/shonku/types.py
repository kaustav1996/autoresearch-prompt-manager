"""Core types used throughout shonku."""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """Specification for a single tool that can be given to an agent."""

    name: str
    description: str = ""
    callable: Callable[..., Any]

    model_config = {"arbitrary_types_allowed": True}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ToolSpec):
            return NotImplemented
        return self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)


class AgentResult(BaseModel):
    """Result returned after an agent run completes."""

    content: str
    success: bool = True
    tool_calls_made: int = 0
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
