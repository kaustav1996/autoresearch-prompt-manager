"""Tests for the marketing content agent example."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from marketing_agent.agent import MarketingContentAgent
from marketing_agent.config import MarketingAgentConfig
from marketing_agent.tools import create_prompt_manager_tools

# ---------------------------------------------------------------------------
# Agent tests
# ---------------------------------------------------------------------------


class TestMarketingContentAgent:
    """Tests for MarketingContentAgent class attributes and built-in tools."""

    def test_agent_metadata(self):
        agent = MarketingContentAgent()
        assert agent.name == "marketing-content-agent"
        assert agent.version == "0.1.0"
        assert "instagram" in agent.description.lower() or "content" in agent.description.lower()

    def test_required_tools_declared(self):
        agent = MarketingContentAgent()
        assert "resolve_prompt" in agent.required_tools
        assert "report_metric" in agent.required_tools

    def test_rate_content_is_own_tool(self):
        agent = MarketingContentAgent()
        assert "rate_content" in agent.list_own_tools()

    def test_rate_content_basic_scoring(self):
        agent = MarketingContentAgent()
        # Short content with no signals gets base score
        result = json.loads(agent.rate_content("Hi", "caption"))
        assert result["quality_score"] == 5.0

        # Caption with Instagram engagement signals scores higher
        good_caption = "✨ Double tap if you agree! " + "x" * 100 + " #inspiration save this"
        result = json.loads(agent.rate_content(good_caption, "caption"))
        assert result["quality_score"] > 5.0

    def test_rate_content_instagram_engagement_bonus(self):
        agent = MarketingContentAgent()
        # Caption with all signals: len>50, len>200, emoji, hashtag, CTA
        caption = "✨ Transform your mornings! " + "x" * 180 + " #wellness #morning link in bio"
        result = json.loads(agent.rate_content(caption, "caption"))
        # base(5) + len>50(1) + len>200(0.5) + emoji(0.5) + hashtag(0.5) + CTA(1.0) = 8.5
        assert result["quality_score"] == 8.5

    def test_rate_content_reel_script_bonus(self):
        agent = MarketingContentAgent()
        script = "✨ Hook! " + "x" * 60 + " #reel\nVO: This is scene 1 save this"
        result = json.loads(agent.rate_content(script, "reel_script"))
        # base(5) + len>50(1) + emoji(0.5) + hashtag(0.5) + CTA(1.0) + reel(0.5) = 8.5
        assert result["quality_score"] == 8.5

    def test_rate_content_capped_at_ten(self):
        agent = MarketingContentAgent()
        content = "✨ Save this! link in bio #wellness #fitness " * 10
        result = json.loads(agent.rate_content(content, "caption"))
        assert result["quality_score"] <= 10.0


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
        assert len(prompts) > 0

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
    """Tests for MarketingAgentConfig defaults."""

    def test_default_values(self):
        config = MarketingAgentConfig()
        assert config.prompt_manager_url == "http://localhost:8910"
        assert config.llm_provider == "anthropic"
        assert config.auto_optimize is True

    def test_override_values(self):
        config = MarketingAgentConfig(
            prompt_manager_url="http://custom:9999",
            llm_provider="openai",
            llm_model="gpt-4o",
            auto_optimize=False,
        )
        assert config.prompt_manager_url == "http://custom:9999"
        assert config.llm_provider == "openai"
        assert config.llm_model == "gpt-4o"
        assert config.auto_optimize is False
