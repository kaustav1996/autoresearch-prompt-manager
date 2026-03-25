"""PromptOptimizerAgent -- proposes improved prompt versions based on analysis."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from shonku.agent import ShonkuAgent
from shonku.decorators import tool


class PromptOptimizerAgent(ShonkuAgent):
    """Proposes improved prompt versions based on performance analysis."""

    name = "prompt-optimizer"
    description = "Proposes improved prompt versions based on analysis"
    instructions = (
        "You are an expert prompt engineer. Given analysis of a prompt's performance:\n"
        "1. Use get_prompt to read the current prompt text\n"
        "2. Propose ONE focused improvement based on the analysis\n"
        "3. Use validate_template_vars to ensure your improved prompt "
        "keeps all template variables\n"
        "4. Use compute_similarity to check you haven't drifted too far\n\n"
        "Respond with JSON: "
        '{"improved_prompt": "...", "reasoning": "...", '
        '"expected_improvement": "...", "risk": "low|medium|high"}'
    )

    required_tools = ["get_prompt"]

    @tool(description="Validate template variables are preserved")
    def validate_template_vars(self, original: str, proposed: str) -> str:
        """Check that all {var} placeholders in original exist in proposed."""
        original_vars = set(re.findall(r"\{(\w+)\}", original))
        proposed_vars = set(re.findall(r"\{(\w+)\}", proposed))
        missing = sorted(original_vars - proposed_vars)
        added = sorted(proposed_vars - original_vars)

        return json.dumps({
            "valid": len(missing) == 0,
            "missing": missing,
            "added": added,
            "vars": sorted(proposed_vars),
        })

    @tool(description="Compute text similarity between original and proposed prompt")
    def compute_similarity(self, text_a: str, text_b: str) -> str:
        """Compute similarity ratio between two texts."""
        ratio = SequenceMatcher(None, text_a, text_b).ratio()
        return json.dumps({
            "similarity": round(ratio, 3),
            "edit_distance_pct": round(1 - ratio, 3),
        })
