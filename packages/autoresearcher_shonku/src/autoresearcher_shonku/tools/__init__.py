"""Built-in tools for autoresearcher agents."""

from autoresearcher_shonku.tools.analysis import analyze_metric_trends
from autoresearcher_shonku.tools.improvement import generate_prompt_improvement
from autoresearcher_shonku.tools.safety import check_safety_rails
from autoresearcher_shonku.tools.validation import compute_similarity, validate_template_vars

__all__ = [
    "analyze_metric_trends",
    "check_safety_rails",
    "compute_similarity",
    "generate_prompt_improvement",
    "validate_template_vars",
]
