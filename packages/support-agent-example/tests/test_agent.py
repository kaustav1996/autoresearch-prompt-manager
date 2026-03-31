"""Tests for the customer support agent example."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from support_agent.agent import CustomerSupportAgent
from support_agent.config import SupportAgentConfig
from support_agent.tools import create_prompt_manager_tools


# ---------------------------------------------------------------------------
# Agent tests
# ---------------------------------------------------------------------------


class TestCustomerSupportAgent:
    """Tests for CustomerSupportAgent class attributes and built-in tools."""

    def test_agent_metadata(self):
        agent = CustomerSupportAgent()
        assert agent.name == "customer-support-agent"
        assert agent.version == "0.1.0"
        assert "support" in agent.description.lower()

    def test_required_tools_declared(self):
        agent = CustomerSupportAgent()
        assert "resolve_prompt" in agent.required_tools
        assert "report_metric" in agent.required_tools

    def test_rate_response_is_own_tool(self):
        agent = CustomerSupportAgent()
        assert "rate_response" in agent.list_own_tools()

    def test_rate_response_base_scores(self):
        agent = CustomerSupportAgent()
        # Very short response — no bonuses
        result = json.loads(agent.rate_response("Ok.", "ticket"))
        assert result["csat_score"] == 5.0
        assert result["tone_score"] == 5.0
        assert result["resolution_score"] == 5.0
        assert result["first_contact_score"] == 5.0

    def test_rate_response_empathy_boosts_csat_and_tone(self):
        agent = CustomerSupportAgent()
        empathetic = (
            "I sincerely apologize for the trouble you've experienced. "
            "I completely understand your frustration. " * 5
        )
        result = json.loads(agent.rate_response(empathetic, "ticket"))
        assert result["csat_score"] > 5.0
        assert result["tone_score"] > 5.0

    def test_rate_response_resolution_steps_boost_resolution(self):
        agent = CustomerSupportAgent()
        response = (
            "Here's how to fix this issue — follow these steps: "
            "1. Reset your password. 2. Clear cookies. Let me know if that helps. " * 3
        )
        result = json.loads(agent.rate_response(response, "ticket"))
        assert result["resolution_score"] > 5.0
        assert result["first_contact_score"] > 5.0

    def test_rate_response_escalation_scenario_bonus(self):
        agent = CustomerSupportAgent()
        response = (
            "We will escalate this to our specialist team. " * 4
            + "Please let me know if you have any questions."
        )
        result = json.loads(agent.rate_response(response, "escalation"))
        assert result["resolution_score"] > 5.0

    def test_rate_response_sentiment_scenario_bonus(self):
        agent = CustomerSupportAgent()
        response = (
            "I understand your frustration and sincerely apologize. " * 4
            + "I will personally ensure this is resolved."
        )
        result = json.loads(agent.rate_response(response, "sentiment"))
        assert result["csat_score"] > 6.0

    def test_rate_response_capped_at_ten(self):
        agent = CustomerSupportAgent()
        # Maximize every heuristic signal
        response = (
            "I sincerely apologize and understand your frustration. "
            "I appreciate your patience. Happy to help. "
            "Here are the steps to fix this and resolve the solution: "
            "Follow these steps. Let me know. Feel free to reach out. "
            "Contact us anytime. "
        ) * 10
        result = json.loads(agent.rate_response(response, "sentiment"))
        assert result["csat_score"] <= 10.0
        assert result["tone_score"] <= 10.0
        assert result["resolution_score"] <= 10.0
        assert result["first_contact_score"] <= 10.0

    def test_rate_response_returns_all_keys(self):
        agent = CustomerSupportAgent()
        result = json.loads(agent.rate_response("Hello", "faq"))
        assert set(result.keys()) == {
            "csat_score", "tone_score", "resolution_score", "first_contact_score"
        }


# ---------------------------------------------------------------------------
# Seed prompts tests
# ---------------------------------------------------------------------------


class TestSeedPrompts:
    """Tests for the seed_prompts.json file."""

    def test_seed_file_exists(self):
        seed_file = Path(__file__).parent.parent / "prompts" / "seed_prompts.json"
        assert seed_file.exists(), f"Seed file not found at {seed_file}"

    def test_seed_file_is_valid_json(self):
        seed_file = Path(__file__).parent.parent / "prompts" / "seed_prompts.json"
        prompts = json.loads(seed_file.read_text())
        assert isinstance(prompts, list)
        assert len(prompts) >= 4

    def test_seed_prompts_have_required_fields(self):
        seed_file = Path(__file__).parent.parent / "prompts" / "seed_prompts.json"
        prompts = json.loads(seed_file.read_text())
        for p in prompts:
            assert "slug" in p, f"Missing 'slug' in {p}"
            assert "name" in p, f"Missing 'name' in {p}"
            assert "content" in p, f"Missing 'content' in {p}"
            assert "tags" in p, f"Missing 'tags' in {p}"
            assert isinstance(p["tags"], list)

    def test_seed_prompts_have_unique_slugs(self):
        seed_file = Path(__file__).parent.parent / "prompts" / "seed_prompts.json"
        prompts = json.loads(seed_file.read_text())
        slugs = [p["slug"] for p in prompts]
        assert len(slugs) == len(set(slugs)), "Duplicate slugs found"

    def test_seed_prompts_use_template_syntax(self):
        """Verify templates use the {{var}} placeholder syntax."""
        seed_file = Path(__file__).parent.parent / "prompts" / "seed_prompts.json"
        prompts = json.loads(seed_file.read_text())
        for p in prompts:
            assert "{{" in p["content"], (
                f"Prompt '{p['slug']}' has no template variables"
            )

    def test_seed_prompts_cover_required_scenarios(self):
        """Verify all four required support scenarios are present."""
        seed_file = Path(__file__).parent.parent / "prompts" / "seed_prompts.json"
        prompts = json.loads(seed_file.read_text())
        slugs = {p["slug"] for p in prompts}
        assert "ticket-response" in slugs
        assert "faq-answer" in slugs
        assert "escalation-decision" in slugs
        assert "sentiment-handling" in slugs


# ---------------------------------------------------------------------------
# Tools tests
# ---------------------------------------------------------------------------


class TestTools:
    """Tests for the prompt-manager tool bridge."""

    def test_create_tools_returns_two_tool_specs(self):
        mock_client = MagicMock()
        tools = create_prompt_manager_tools(mock_client)
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"resolve_prompt", "report_metric"}

    def test_tools_have_descriptions(self):
        mock_client = MagicMock()
        tools = create_prompt_manager_tools(mock_client)
        for t in tools:
            assert t.description, f"Tool '{t.name}' has no description"

    def test_tools_are_callable(self):
        mock_client = MagicMock()
        tools = create_prompt_manager_tools(mock_client)
        for t in tools:
            assert callable(t.callable), f"Tool '{t.name}' is not callable"


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestConfig:
    """Tests for SupportAgentConfig defaults."""

    def test_default_values(self):
        config = SupportAgentConfig()
        assert config.prompt_manager_url == "http://localhost:8910"
        assert config.llm_provider == "anthropic"
        assert config.auto_optimize is True

    def test_override_values(self):
        config = SupportAgentConfig(
            prompt_manager_url="http://custom:9999",
            llm_provider="openai",
            llm_model="gpt-4o",
            auto_optimize=False,
        )
        assert config.prompt_manager_url == "http://custom:9999"
        assert config.llm_provider == "openai"
        assert config.llm_model == "gpt-4o"
        assert config.auto_optimize is False
