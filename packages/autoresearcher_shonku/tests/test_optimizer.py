"""Tests for PromptOptimizerAgent tools: validate_template_vars and compute_similarity."""

from __future__ import annotations

import json

from autoresearcher_shonku.agents.optimizer import PromptOptimizerAgent


class TestPromptOptimizerAgent:
    def setup_method(self) -> None:
        self.agent = PromptOptimizerAgent()

    def test_agent_metadata(self) -> None:
        assert self.agent.name == "prompt-optimizer"
        assert "get_prompt" in self.agent.required_tools

    def test_own_tools_collected(self) -> None:
        tool_names = self.agent.list_own_tools()
        assert "validate_template_vars" in tool_names
        assert "compute_similarity" in tool_names


class TestValidateTemplateVars:
    def setup_method(self) -> None:
        self.agent = PromptOptimizerAgent()

    def test_all_vars_preserved(self) -> None:
        original = "Hello {name}, your order {order_id} is ready."
        proposed = "Hi {name}! Order {order_id} is prepared."
        result = json.loads(self.agent.validate_template_vars(original, proposed))
        assert result["valid"] is True
        assert result["missing"] == []

    def test_missing_var(self) -> None:
        original = "Hello {name}, your order {order_id} is ready."
        proposed = "Hi {name}! Your order is prepared."
        result = json.loads(self.agent.validate_template_vars(original, proposed))
        assert result["valid"] is False
        assert "order_id" in result["missing"]

    def test_added_var(self) -> None:
        original = "Hello {name}."
        proposed = "Hello {name}, today is {date}."
        result = json.loads(self.agent.validate_template_vars(original, proposed))
        assert result["valid"] is True
        assert "date" in result["added"]

    def test_no_vars(self) -> None:
        result = json.loads(self.agent.validate_template_vars("hello", "hi there"))
        assert result["valid"] is True
        assert result["missing"] == []


class TestComputeSimilarity:
    def setup_method(self) -> None:
        self.agent = PromptOptimizerAgent()

    def test_identical_texts(self) -> None:
        result = json.loads(self.agent.compute_similarity("hello world", "hello world"))
        assert result["similarity"] == 1.0
        assert result["edit_distance_pct"] == 0.0

    def test_completely_different(self) -> None:
        result = json.loads(self.agent.compute_similarity("aaaa", "zzzz"))
        assert result["similarity"] < 0.1

    def test_similar_texts(self) -> None:
        result = json.loads(self.agent.compute_similarity(
            "You are a helpful assistant.", "You are a very helpful assistant."
        ))
        assert result["similarity"] > 0.8
