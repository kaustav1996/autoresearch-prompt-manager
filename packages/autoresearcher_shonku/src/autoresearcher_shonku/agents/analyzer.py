"""PromptAnalyzerAgent -- analyzes prompt metrics to find improvement opportunities."""

from __future__ import annotations

import json
import statistics

from shonku.agent import ShonkuAgent
from shonku.decorators import tool


class PromptAnalyzerAgent(ShonkuAgent):
    """Analyzes prompt performance metrics and identifies improvement areas."""

    name = "prompt-analyzer"
    description = "Analyzes prompt metrics to identify improvement opportunities"
    instructions = (
        "You are a prompt analysis expert. Given a prompt and its metrics:\n"
        "1. Use get_metrics to fetch performance data\n"
        "2. Use get_sample_interactions to see real examples\n"
        "3. Use analyze_metric_trends to identify patterns\n"
        "4. Return a structured analysis with strengths, weaknesses, and hypotheses.\n\n"
        "Respond with JSON: "
        '{"strengths": [...], "weaknesses": [...], "hypotheses": [...], "priority_area": "..."}'
    )

    required_tools = ["get_metrics", "get_prompt", "get_sample_interactions"]

    @tool(description="Analyze metric trends over time")
    def analyze_metric_trends(self, metrics_json: str) -> str:
        """Compute trend analysis from metric data.

        Expects JSON: ``{"metric_name": [value1, value2, ...], ...}``
        """
        metrics: dict[str, list[float]] = json.loads(metrics_json)
        result: dict[str, dict] = {}

        for name, values in metrics.items():
            if not values:
                result[name] = {"error": "no data"}
                continue

            mean = statistics.mean(values)
            std = statistics.stdev(values) if len(values) > 1 else 0.0

            # Trend direction
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

            # Anomalies: more than 2 std from mean
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
