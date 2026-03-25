"""Composite metric scoring utilities."""

from __future__ import annotations

from autoresearcher_shonku.errors import ScoringError

DEFAULT_WEIGHTS: dict[str, float] = {
    "accuracy": 0.4,
    "latency": 0.2,
    "cost": 0.2,
    "user_satisfaction": 0.2,
}


def compute_composite_score(
    metrics: dict[str, float],
    weights: dict[str, float] | None = None,
) -> float:
    """Compute weighted composite from multiple metrics.

    Parameters
    ----------
    metrics:
        Metric name to value mapping. Values should be normalized to [0, 1].
    weights:
        Metric name to weight mapping. Weights are normalized to sum to 1.
        Defaults to ``DEFAULT_WEIGHTS`` for known keys, equal weight otherwise.

    Returns
    -------
    float
        Composite score in [0, 1].
    """
    if not metrics:
        raise ScoringError("Cannot compute composite score from empty metrics")

    if weights is None:
        weights = {k: DEFAULT_WEIGHTS.get(k, 1.0) for k in metrics}

    # Only use weights for metrics that are present
    active_weights = {k: weights.get(k, 1.0) for k in metrics}
    total_weight = sum(active_weights.values())

    if total_weight == 0:
        raise ScoringError("Total weight is zero — cannot normalize")

    score = sum(metrics[k] * active_weights[k] for k in metrics) / total_weight
    return round(max(0.0, min(1.0, score)), 6)


def is_improvement(
    new_score: float,
    baseline_score: float,
    threshold: float,
    direction: str = "maximize",
) -> bool:
    """Check if new score is an improvement over baseline.

    Parameters
    ----------
    new_score:
        The candidate score.
    baseline_score:
        The current baseline score.
    threshold:
        Minimum absolute improvement required.
    direction:
        ``"maximize"`` or ``"minimize"``.

    Returns
    -------
    bool
        True if new_score is better than baseline by at least threshold.
    """
    if direction == "maximize":
        return (new_score - baseline_score) >= threshold
    elif direction == "minimize":
        return (baseline_score - new_score) >= threshold
    else:
        raise ScoringError(f"Unknown direction: {direction!r}. Use 'maximize' or 'minimize'.")
