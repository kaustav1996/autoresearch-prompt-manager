"""Tests for safety rail checks."""

from __future__ import annotations

import json

from autoresearcher_shonku.agents.autoresearcher import AutoResearcherAgent
from autoresearcher_shonku.tools.safety import check_safety_rails


class TestSafetyRailsStandalone:
    """Test the standalone safety tool."""

    def test_safe_proposal(self) -> None:
        result = json.loads(check_safety_rails(
            original_prompt="You are a helpful assistant that answers questions.",
            proposed_prompt="You are a helpful, concise assistant that answers questions clearly.",
            iteration="1",
            max_iterations="10",
        ))
        assert result["safe"] is True
        assert all(result["checks"].values())

    def test_empty_proposal(self) -> None:
        result = json.loads(check_safety_rails(
            original_prompt="You are a helpful assistant.",
            proposed_prompt="   ",
            iteration="1",
            max_iterations="10",
        ))
        assert result["safe"] is False
        assert result["checks"]["not_empty"] is False

    def test_too_different(self) -> None:
        result = json.loads(check_safety_rails(
            original_prompt="You are a helpful assistant.",
            proposed_prompt="xyz abc 123 completely unrelated text that shares nothing.",
            iteration="1",
            max_iterations="10",
        ))
        assert result["checks"]["similarity_ok"] is False

    def test_over_budget(self) -> None:
        result = json.loads(check_safety_rails(
            original_prompt="You are a helpful assistant.",
            proposed_prompt="You are a helpful and kind assistant.",
            iteration="11",
            max_iterations="10",
        ))
        assert result["safe"] is False
        assert result["checks"]["within_budget"] is False

    def test_too_long(self) -> None:
        original = "Short prompt."
        proposed = "A" * 1000  # Way too long relative to original
        result = json.loads(check_safety_rails(
            original_prompt=original,
            proposed_prompt=proposed,
            iteration="1",
            max_iterations="10",
        ))
        assert result["checks"]["length_reasonable"] is False

    def test_too_short(self) -> None:
        original = "A" * 200
        proposed = "Very short."  # Much shorter than original but > 10 chars
        result = json.loads(check_safety_rails(
            original_prompt=original,
            proposed_prompt=proposed,
            iteration="1",
            max_iterations="10",
        ))
        assert result["checks"]["length_reasonable"] is False


class TestSafetyRailsOnAgent:
    """Test the safety tool via the AutoResearcherAgent."""

    def setup_method(self) -> None:
        self.agent = AutoResearcherAgent()

    def test_agent_has_safety_tool(self) -> None:
        assert "check_safety_rails" in self.agent.list_own_tools()

    def test_agent_safety_check_passes(self) -> None:
        result = json.loads(self.agent.check_safety_rails(
            original_prompt="Answer the user's question about {topic}.",
            proposed_prompt="Provide a clear answer about {topic} using simple language.",
            iteration="1",
            max_iterations="10",
        ))
        assert result["safe"] is True
        assert result["similarity"] > 0.0
