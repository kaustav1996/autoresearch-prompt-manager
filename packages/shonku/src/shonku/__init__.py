"""shonku -- Build, publish, and run AI agents (wraps agno)."""

from shonku.agent import ShonkuAgent
from shonku.config import AgentConfig, LLMConfig
from shonku.decorators import agent, tool
from shonku.errors import (
    AgentRunError,
    LLMConfigError,
    MissingToolError,
    ShonkuError,
    ToolConflictError,
)
from shonku.manifest import AgentManifest
from shonku.runner import NodeRunner
from shonku.tool_set import ToolSet
from shonku.types import AgentResult, ToolSpec

__all__ = [
    # Core
    "ShonkuAgent",
    "ToolSet",
    "NodeRunner",
    # Decorators
    "agent",
    "tool",
    # Config / types
    "LLMConfig",
    "AgentConfig",
    "AgentResult",
    "AgentManifest",
    "ToolSpec",
    # Errors
    "ShonkuError",
    "ToolConflictError",
    "MissingToolError",
    "LLMConfigError",
    "AgentRunError",
]

__version__ = "0.1.0"
