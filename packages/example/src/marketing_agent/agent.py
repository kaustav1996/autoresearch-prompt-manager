"""MarketingContentAgent -- a shonku agent that generates marketing content."""

from __future__ import annotations

import json

from shonku import ShonkuAgent, tool


class MarketingContentAgent(ShonkuAgent):
    """Generates marketing content using optimized prompts from prompt-manager.

    This agent demonstrates the full stack: it resolves prompt templates via
    the prompt-manager client, generates content, self-evaluates quality, and
    reports metrics back so that autoresearcher-shonku can improve the prompts
    over time.
    """

    name = "marketing-content-agent"
    description = "Generates marketing content using optimized prompts"
    version = "0.1.0"
    instructions = (
        "You are a marketing content specialist. When asked to generate content:\n"
        "1. Use resolve_prompt to get the best prompt template for the content type\n"
        "2. Use the template with the provided variables to generate content\n"
        "3. Rate the quality of your own output (1-10) using rate_content\n"
        "4. Return the generated content\n"
        "\n"
        "Always aim for engaging, clear, and action-oriented content."
    )

    required_tools = ["resolve_prompt", "report_metric"]

    @tool(description="Rate content quality on a 1-10 scale")
    def rate_content(self, content: str, content_type: str) -> str:
        """Self-evaluate content quality using simple heuristics.

        Parameters
        ----------
        content:
            The generated content to evaluate.
        content_type:
            The type of content (email, social, ad, product).

        Returns
        -------
        JSON string with a ``quality_score`` key.
        """
        score = 5.0

        # Length rewards
        if len(content) > 50:
            score += 1
        if len(content) > 200:
            score += 1

        # Engagement signals
        if "!" in content:
            score += 0.5
        if any(w in content.lower() for w in ["free", "exclusive", "limited"]):
            score += 0.5

        # Type-specific checks
        if content_type == "email" and "subject:" in content.lower():
            score += 1

        return json.dumps({"quality_score": min(score, 10.0)})
