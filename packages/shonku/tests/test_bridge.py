"""Tests for the agno bridge -- agno is mocked so tests run without it."""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shonku.agent import ShonkuAgent
from shonku.config import LLMConfig
from shonku.decorators import tool
from shonku.errors import LLMConfigError
from shonku.types import AgentResult, ToolSpec


# -- fixtures ------------------------------------------------------------


class ResearchAgent(ShonkuAgent):
    name = "researcher"
    instructions = "You research topics."
    required_tools = ["web_search"]

    @tool(description="Summarise text")
    def summarise(self, text: str) -> str:
        return text[:100]


def _web_search(query: str) -> str:
    """Search the web."""
    return f"results for {query}"


WEB_SEARCH_SPEC = ToolSpec(
    name="web_search",
    description="Search the web",
    callable=_web_search,
)

LLM = LLMConfig(provider="anthropic", model="claude-sonnet-4-5", api_key="sk-test")


# -- tests: create_agno_model -------------------------------------------


class TestCreateAgnoModel:
    def test_anthropic(self) -> None:
        mock_claude = MagicMock()
        # Inject a fake agno.models.anthropic module so the lazy import works
        fake_mod = ModuleType("agno.models.anthropic")
        fake_mod.Claude = mock_claude  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"agno.models.anthropic": fake_mod}):
            from shonku.bridge import create_agno_model

            create_agno_model(LLM)
            mock_claude.assert_called_once_with(id="claude-sonnet-4-5", api_key="sk-test")

    def test_openai(self) -> None:
        mock_oai = MagicMock()
        fake_mod = ModuleType("agno.models.openai")
        fake_mod.OpenAIChat = mock_oai  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"agno.models.openai": fake_mod}):
            from shonku.bridge import create_agno_model

            cfg = LLMConfig(provider="openai", model="gpt-4o", api_key="sk-oai")
            create_agno_model(cfg)
            mock_oai.assert_called_once_with(id="gpt-4o", api_key="sk-oai")

    def test_unsupported_provider_raises(self) -> None:
        from shonku.bridge import create_agno_model

        cfg = LLMConfig(provider="unsupported", model="x")
        with pytest.raises(LLMConfigError):
            create_agno_model(cfg)


# -- tests: execute_agent -----------------------------------------------


class TestExecuteAgent:
    def test_successful_run(self) -> None:
        mock_result = MagicMock()
        mock_result.content = "Here are the findings..."
        mock_result.messages = [
            MagicMock(role="tool"),
            MagicMock(role="assistant"),
            MagicMock(role="tool"),
        ]

        mock_agno_cls = MagicMock()
        mock_agno_instance = MagicMock()
        mock_agno_instance.arun = AsyncMock(return_value=mock_result)
        mock_agno_cls.return_value = mock_agno_instance

        with patch("shonku.bridge.AgnoAgent", mock_agno_cls), \
             patch("shonku.bridge.create_agno_model", return_value=MagicMock()):
            from shonku.bridge import execute_agent

            agent = ResearchAgent()
            result = asyncio.run(
                execute_agent(agent, "Find papers on RAG", LLM, [WEB_SEARCH_SPEC], None)
            )

        assert isinstance(result, AgentResult)
        assert result.success is True
        assert result.content == "Here are the findings..."
        assert result.tool_calls_made == 2

    def test_run_failure_returns_error_result(self) -> None:
        mock_agno_cls = MagicMock()
        mock_agno_instance = MagicMock()
        mock_agno_instance.arun = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        mock_agno_cls.return_value = mock_agno_instance

        with patch("shonku.bridge.AgnoAgent", mock_agno_cls), \
             patch("shonku.bridge.create_agno_model", return_value=MagicMock()):
            from shonku.bridge import execute_agent

            agent = ResearchAgent()
            result = asyncio.run(
                execute_agent(agent, "query", LLM, [WEB_SEARCH_SPEC], None)
            )

        assert result.success is False
        assert "LLM timeout" in (result.error or "")

    def test_context_injected_into_instructions(self) -> None:
        mock_agno_cls = MagicMock()
        mock_agno_instance = MagicMock()
        mock_agno_instance.arun = AsyncMock(
            return_value=MagicMock(content="ok", messages=[])
        )
        mock_agno_cls.return_value = mock_agno_instance

        with patch("shonku.bridge.AgnoAgent", mock_agno_cls), \
             patch("shonku.bridge.create_agno_model", return_value=MagicMock()):
            from shonku.bridge import execute_agent

            agent = ResearchAgent()
            asyncio.run(
                execute_agent(
                    agent, "query", LLM, [WEB_SEARCH_SPEC],
                    context={"user": "alice", "org": "acme"},
                )
            )

        call_kwargs = mock_agno_cls.call_args[1]
        assert "alice" in call_kwargs["instructions"]
        assert "acme" in call_kwargs["instructions"]
