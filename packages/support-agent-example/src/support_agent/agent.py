"""CustomerSupportAgent -- a shonku agent that handles customer support interactions."""

from __future__ import annotations

import json

from shonku import ShonkuAgent, tool


class CustomerSupportAgent(ShonkuAgent):
    """Handles customer support interactions using optimized prompts from prompt-manager.

    This agent demonstrates the full stack: it resolves prompt templates via
    the prompt-manager client, generates support responses, self-evaluates quality
    across support-specific metrics, and reports them back so that
    autoresearcher-shonku can improve the prompts over time.
    """

    name = "customer-support-agent"
    description = "Handles customer support interactions using optimized prompts"
    version = "0.1.0"
    instructions = (
        "You are a customer support specialist. When asked to handle a support request:\n"
        "1. Use resolve_prompt to get the best prompt template for the scenario type\n"
        "2. Use the template with the provided context to draft the support response\n"
        "3. Rate the response quality using rate_response\n"
        "4. Report the metrics with report_metric\n"
        "5. Return the final response\n"
        "\n"
        "Always aim for empathetic, clear, and resolution-focused responses."
    )

    required_tools = ["resolve_prompt", "report_metric"]

    @tool(description="Rate a support response across CSAT, tone, and resolution dimensions")
    def rate_response(self, response: str, scenario_type: str) -> str:
        """Self-evaluate a support response using heuristics.

        Parameters
        ----------
        response:
            The generated support response to evaluate.
        scenario_type:
            The support scenario type (ticket, faq, escalation, sentiment).

        Returns
        -------
        JSON string with ``csat_score``, ``tone_score``, ``resolution_score``,
        and ``first_contact_score`` keys (all on a 1-10 scale).
        """
        csat = 5.0
        tone = 5.0
        resolution = 5.0
        first_contact = 5.0

        response_lower = response.lower()

        # Length rewards — too short responses are unhelpful
        if len(response) > 100:
            csat += 0.5
            resolution += 0.5
        if len(response) > 300:
            csat += 0.5
            resolution += 0.5

        # Empathy signals improve CSAT and tone
        empathy_phrases = [
            "apologize", "sorry", "understand", "frustration",
            "appreciate", "thank you", "i hear you", "i can see",
        ]
        if any(p in response_lower for p in empathy_phrases):
            csat += 1.0
            tone += 1.5

        # Professional tone markers
        if any(p in response_lower for p in ["please", "kindly", "happy to help", "let me"]):
            tone += 1.0

        # Resolution clarity signals
        resolution_phrases = ["steps", "solution", "resolved", "fix", "here's how", "follow these"]
        if any(p in response_lower for p in resolution_phrases):
            resolution += 1.5
            first_contact += 1.0

        # CTA / next step signals raise first-contact resolution likelihood
        cta_phrases = ["let me know", "reach out", "feel free", "contact us"]
        if any(p in response_lower for p in cta_phrases):
            first_contact += 1.0

        # Scenario-specific bonuses
        if scenario_type == "escalation" and "escalate" in response_lower:
            resolution += 1.0
        if scenario_type == "sentiment" and any(
            p in response_lower for p in ["understand your frustration", "sincerely apologize"]
        ):
            csat += 1.0
            tone += 0.5
        if scenario_type == "faq" and any(p in response_lower for p in ["faq", "article", "guide"]):
            first_contact += 0.5

        return json.dumps(
            {
                "csat_score": min(csat, 10.0),
                "tone_score": min(tone, 10.0),
                "resolution_score": min(resolution, 10.0),
                "first_contact_score": min(first_contact, 10.0),
            }
        )
