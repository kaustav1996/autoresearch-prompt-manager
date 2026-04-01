"""MarketingContentAgent -- a shonku agent that generates Instagram content."""

from __future__ import annotations

import json

from shonku import ShonkuAgent, tool


class MarketingContentAgent(ShonkuAgent):
    """Generates Instagram content using optimized prompts from prompt-manager.

    This agent demonstrates the full stack: it resolves prompt templates via
    the prompt-manager client, generates Instagram content, self-evaluates
    engagement quality, and reports metrics back so that autoresearcher-shonku
    can improve the prompts over time.
    """

    name = "marketing-content-agent"
    description = "Generates instagram content using optimized prompts"
    version = "0.1.0"
    instructions = (
        "You are an Instagram content specialist. When asked to generate content:\n"
        "1. Use resolve_prompt to get the best prompt template for the content type\n"
        "2. Use the template with the provided variables to generate content\n"
        "3. Rate the engagement quality of your output (1-10) using rate_content\n"
        "4. Return the generated content\n"
        "\n"
        "Always aim for scroll-stopping hooks, authentic tone, clear CTAs, and\n"
        "strategic hashtag use. Optimise for saves, shares, and comments."
    )

    required_tools = ["resolve_prompt", "report_metric"]

    @tool(description="Rate Instagram content engagement quality on a 1-10 scale")
    def rate_content(self, content: str, content_type: str) -> str:
        """Self-evaluate Instagram content quality using engagement heuristics.

        Parameters
        ----------
        content:
            The generated content to evaluate.
        content_type:
            The type of content (caption, reel_script, design_brief, hashtags).

        Returns
        -------
        JSON string with a ``quality_score`` key.
        """
        score = 5.0

        # Length rewards — Instagram captions sweet spot is 125-2200 chars
        if len(content) > 50:
            score += 1.0
        if len(content) > 200:
            score += 0.5

        # Emoji presence (Unicode > U+00FF covers emoji ranges)
        if any(ord(c) > 255 for c in content):
            score += 0.5

        # Hashtag usage
        if "#" in content:
            score += 0.5

        # CTA signals that drive engagement
        cta_keywords = ["link in bio", "save this", "comment", "swipe", "follow", "tag a friend"]
        if any(w in content.lower() for w in cta_keywords):
            score += 1.0

        # Reel script structure: scene markers or VO cues
        if content_type == "reel_script" and (
            "scene" in content.lower() or "vo:" in content.lower() or "cut to" in content.lower()
        ):
            score += 0.5

        return json.dumps({"quality_score": min(score, 10.0)})
