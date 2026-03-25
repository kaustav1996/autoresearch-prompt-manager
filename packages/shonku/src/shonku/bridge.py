"""Bridge to agno — the ONLY file that imports agno.

agno (https://agno.com) provides the production-grade agent runtime,
LLM provider integrations, and tool execution. shonku delegates all
agent execution to agno via this bridge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agno.agent import Agent as AgnoAgent

from shonku.errors import LLMConfigError
from shonku.tool_set import ToolSet
from shonku.types import AgentResult

if TYPE_CHECKING:
    from shonku.agent import ShonkuAgent
    from shonku.config import LLMConfig
    from shonku.types import ToolSpec


# -- public API ----------------------------------------------------------


async def execute_agent(
    shonku_agent: ShonkuAgent,
    input_text: str,
    llm_config: LLMConfig,
    external_tools: list[ToolSpec | Any] | None,
    context: dict[str, Any] | None,
) -> AgentResult:
    """Build an agno Agent from *shonku_agent*, run it, and return the result."""
    # 1. Model
    model = create_agno_model(llm_config)

    # 2. Merge tools
    tool_set = ToolSet()
    for t in shonku_agent._own_tools:
        tool_set.add(t)
    if external_tools:
        for t in external_tools:
            tool_set.add(t)

    # 3. Validate
    tool_set.validate_required(shonku_agent.required_tools)

    # 4. Build instructions (optionally inject context)
    instructions = shonku_agent.instructions
    if context:
        ctx_lines = "\n".join(f"- {k}: {v}" for k, v in context.items())
        instructions = f"{instructions}\n\nContext:\n{ctx_lines}"

    # 5. Create agno agent
    agno_agent = AgnoAgent(
        name=shonku_agent.name,
        model=model,
        tools=tool_set.to_agno_tools(),
        instructions=instructions,
        tool_call_limit=shonku_agent.max_steps,
    )

    # 6. Run
    try:
        result = await agno_agent.arun(input_text)
    except Exception as exc:
        return AgentResult(
            content="",
            success=False,
            error=str(exc),
        )

    # 7. Convert
    content = _extract_content(result)
    tool_calls_made = _extract_tool_call_count(result)

    return AgentResult(
        content=content,
        success=True,
        tool_calls_made=tool_calls_made,
    )


# -- helpers -------------------------------------------------------------


def create_agno_model(config: LLMConfig) -> Any:
    """Instantiate the correct agno model wrapper from an LLMConfig."""
    kwargs: dict[str, Any] = {"id": config.model}
    if config.api_key:
        kwargs["api_key"] = config.api_key
    if config.api_base:
        kwargs["api_base"] = config.api_base

    provider = config.provider.lower()

    if provider == "anthropic":
        from agno.models.anthropic import Claude

        return Claude(**kwargs)
    if provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(**kwargs)
    if provider == "groq":
        from agno.models.groq import Groq

        return Groq(**kwargs)
    if provider == "gemini":
        from agno.models.google import Gemini

        return Gemini(**kwargs)
    if provider == "openrouter":
        from agno.models.openrouter import OpenRouter

        return OpenRouter(**kwargs)

    raise LLMConfigError(provider)


def _extract_content(result: Any) -> str:
    """Pull text content out of an agno RunResponse."""
    if hasattr(result, "content"):
        return str(result.content)
    return str(result)


def _extract_tool_call_count(result: Any) -> int:
    """Best-effort extraction of tool-call count from an agno result."""
    if hasattr(result, "messages") and result.messages:
        return sum(
            1
            for m in result.messages
            if getattr(m, "role", None) == "tool"
        )
    return 0
