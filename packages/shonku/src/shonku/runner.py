"""NodeRunner -- execute a ShonkuAgent as a standalone node."""

from __future__ import annotations

from typing import Any

from shonku.config import LLMConfig
from shonku.types import AgentResult, ToolSpec


class NodeRunner:
    """Instantiate and run a ShonkuAgent subclass in one call.

    Typical usage::

        result = await NodeRunner.run(
            MyAgent,
            input="Summarise the latest papers on RAG",
            llm_config=LLMConfig(provider="anthropic", model="claude-sonnet-4-5"),
            tools=[search_arxiv],
        )
    """

    @staticmethod
    async def run(
        agent_class: type,
        input: str,
        llm_config: LLMConfig,
        tools: list[ToolSpec | Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Create an agent instance and run it."""
        agent = agent_class()
        return await agent.run(input, llm_config, tools=tools, context=context)

    @staticmethod
    def run_sync(
        agent_class: type,
        input: str,
        llm_config: LLMConfig,
        tools: list[ToolSpec | Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Synchronous convenience wrapper."""
        agent = agent_class()
        return agent.run_sync(input, llm_config, tools=tools, context=context)
