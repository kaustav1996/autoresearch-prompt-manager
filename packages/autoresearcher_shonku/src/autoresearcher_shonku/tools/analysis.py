"""Metric trend analysis tool."""

from __future__ import annotations

import json
import statistics


def analyze_metric_trends(metrics_json: str) -> str:
    """Compute trend analysis from metric data.

    Expects a JSON string with structure:
    ``{"metric_name": [value1, value2, ...], ...}``

    Returns JSON with per-metric summary: mean, std, trend direction, anomalies.
    """
    metrics: dict[str, list[float]] = json.loads(metrics_json)
    result: dict[str, dict] = {}

    for name, values in metrics.items():
        if not values:
            result[name] = {"error": "no data"}
            continue

        mean = statistics.mean(values)
        std = statistics.stdev(values) if len(values) > 1 else 0.0

        # Trend: compare first-half mean to second-half mean
        mid = len(values) // 2
        if mid > 0:
            first_half = statistics.mean(values[:mid])
            second_half = statistics.mean(values[mid:])
            if second_half > first_half * 1.01:
                trend = "improving"
            elif second_half < first_half * 0.99:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        # Anomalies: values more than 2 std from mean
        anomalies: list[dict] = []
        if std > 0:
            for i, v in enumerate(values):
                if abs(v - mean) > 2 * std:
                    anomalies.append({"index": i, "value": round(v, 4)})

        result[name] = {
            "mean": round(mean, 4),
            "std": round(std, 4),
            "trend": trend,
            "anomalies": anomalies,
            "n": len(values),
        }

    return json.dumps(result)
