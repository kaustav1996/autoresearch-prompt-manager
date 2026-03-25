"""Safety rail checks for prompt proposals."""

from __future__ import annotations

import json
from difflib import SequenceMatcher


def check_safety_rails(
    original_prompt: str,
    proposed_prompt: str,
    iteration: str,
    max_iterations: str,
) -> str:
    """Check if a proposed prompt change is safe to deploy.

    Parameters
    ----------
    original_prompt:
        The current prompt text.
    proposed_prompt:
        The proposed replacement text.
    iteration:
        Current iteration number (as string for tool compatibility).
    max_iterations:
        Maximum allowed iterations (as string for tool compatibility).

    Returns
    -------
    str
        JSON with ``{"safe": bool, "checks": {...}, "similarity": float}``.
    """
    similarity = SequenceMatcher(None, original_prompt, proposed_prompt).ratio()
    iteration_num = int(iteration)
    max_iter = int(max_iterations)
    original_len = max(len(original_prompt), 1)

    checks = {
        "similarity_ok": similarity >= 0.3,
        "not_empty": len(proposed_prompt.strip()) > 10,
        "within_budget": iteration_num <= max_iter,
        "length_reasonable": 0.3 <= len(proposed_prompt) / original_len <= 3.0,
    }

    all_passed = all(checks.values())
    return json.dumps({
        "safe": all_passed,
        "checks": checks,
        "similarity": round(similarity, 3),
    })
