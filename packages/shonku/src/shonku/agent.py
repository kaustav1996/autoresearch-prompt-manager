"""ShonkuAgent -- the base class developers subclass to build agents."""

from __future__ import annotations

import asyncio
from typing import Any

from shonku.config import LLMConfig
from shonku.types import AgentResult, ToolSpec


class ShonkuAgent:
    """Base class for shonku agents.

    Subclass this, add ``@tool``-decorated methods, and call ``run()``
    with an ``LLMConfig`` plus any external tools the caller provides.
    """

    name: str = "unnamed"
    description: str = ""
    version: str = "0.1.0"
    instructions: str = ""
    required_tools: list[str] = []
    max_steps: int = 50

    def __init__(self) -> None:
        self._own_tools: list[ToolSpec] = []
        self._collect_tools()

    # -- introspection ---------------------------------------------------

    def _collect_tools(self) -> None:
        """Gather methods decorated with ``@tool``."""
        for attr_name in dir(self):
            if attr_name.startswith("__"):
                continue
            try:
                attr = getattr(self, attr_name)
            except Exception:
                continue
            if getattr(attr, "_shonku_tool", False):
                self._own_tools.append(
                    ToolSpec(
                        name=attr._shonku_tool_name,
                        description=attr._shonku_tool_description,
                        callable=attr,
                    )
                )

    def list_own_tools(self) -> list[str]:
        """Return the names of the agent's built-in tools."""
        return [t.name for t in self._own_tools]

    # -- execution -------------------------------------------------------

    async def run(
        self,
        input: str,
        llm_config: LLMConfig,
        tools: list[ToolSpec | Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Run the agent asynchronously.

        Parameters
        ----------
        input:
            The user message / task description.
        llm_config:
            LLM credentials and model selection -- passed at runtime.
        tools:
            External tools (``ToolSpec`` or plain callables) to inject.
        context:
            Arbitrary key-value pairs appended to the system prompt.
        """
        from shonku.bridge import execute_agent

        return await execute_agent(self, input, llm_config, tools, context)

    def run_sync(
        self,
        input: str,
        llm_config: LLMConfig,
        **kwargs: Any,
    ) -> AgentResult:
        """Synchronous convenience wrapper around :meth:`run`."""
        return asyncio.run(self.run(input, llm_config, **kwargs))
