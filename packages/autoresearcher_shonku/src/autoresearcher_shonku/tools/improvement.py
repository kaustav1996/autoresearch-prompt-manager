"""Prompt improvement generation tool."""

from __future__ import annotations

import json


def generate_prompt_improvement(
    current_prompt: str,
    analysis_json: str,
    strategy: str = "clarity",
) -> str:
    """Generate a structured improvement proposal.

    This is a utility tool that packages the improvement request into a
    structured format. The actual rewriting is done by the LLM via the
    optimizer agent's instructions. This tool validates the request and
    returns a structured template for the agent to fill in.

    Parameters
    ----------
    current_prompt:
        The current prompt text.
    analysis_json:
        JSON string with the analysis (strengths, weaknesses, etc.).
    strategy:
        Improvement strategy: ``"clarity"``, ``"specificity"``,
        ``"conciseness"``, ``"structure"``, or ``"examples"``.
    """
    valid_strategies = {"clarity", "specificity", "conciseness", "structure", "examples"}
    if strategy not in valid_strategies:
        return json.dumps({
            "error": f"Unknown strategy: {strategy!r}. Choose from: {sorted(valid_strategies)}"
        })

    try:
        analysis = json.loads(analysis_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid analysis JSON"})

    strategy_guidance = {
        "clarity": "Make instructions unambiguous. Replace vague terms with specific ones.",
        "specificity": "Add concrete examples, constraints, or format specifications.",
        "conciseness": "Remove redundant phrases. Tighten wording without losing meaning.",
        "structure": "Reorganize with numbered steps, sections, or clear delimiters.",
        "examples": "Add few-shot examples demonstrating the desired output format.",
    }

    return json.dumps({
        "current_prompt": current_prompt,
        "strategy": strategy,
        "guidance": strategy_guidance[strategy],
        "weaknesses_to_address": analysis.get("weaknesses", []),
        "priority_area": analysis.get("priority_area", ""),
        "instruction": (
            "Rewrite the prompt following the guidance above. "
            "Preserve ALL template variables ({var} placeholders). "
            "Make ONE focused change aligned with the strategy."
        ),
    })
