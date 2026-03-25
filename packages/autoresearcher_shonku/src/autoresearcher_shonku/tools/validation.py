"""Validation tools for prompt proposals."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher


def validate_template_vars(original: str, proposed: str) -> str:
    """Check that all ``{var}`` placeholders in original exist in proposed.

    Returns JSON: ``{"valid": bool, "missing": [...], "vars": [...]}``
    """
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


def compute_similarity(text_a: str, text_b: str) -> str:
    """Compute similarity ratio between two texts.

    Returns JSON: ``{"similarity": float, "edit_distance_pct": float}``
    """
    ratio = SequenceMatcher(None, text_a, text_b).ratio()
    return json.dumps({
        "similarity": round(ratio, 3),
        "edit_distance_pct": round(1 - ratio, 3),
    })
