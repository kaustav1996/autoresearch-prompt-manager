"""Tests for PromptAnalyzerAgent tool collection."""

from __future__ import annotations

import json

from autoresearcher_shonku.agents.analyzer import PromptAnalyzerAgent


class TestPromptAnalyzerAgent:
    def setup_method(self) -> None:
        self.agent = PromptAnalyzerAgent()

    def test_agent_metadata(self) -> None:
        assert self.agent.name == "prompt-analyzer"
        assert "improvement" in self.agent.description.lower()

    def test_required_tools(self) -> None:
        assert "get_metrics" in self.agent.required_tools
        assert "get_prompt" in self.agent.required_tools
        assert "get_sample_interactions" in self.agent.required_tools

    def test_own_tools_collected(self) -> None:
        tool_names = self.agent.list_own_tools()
        assert "analyze_metric_trends" in tool_names

    def test_analyze_metric_trends_improving(self) -> None:
        metrics = {"accuracy": [0.5, 0.55, 0.6, 0.7, 0.8, 0.85]}
        result = json.loads(self.agent.analyze_metric_trends(json.dumps(metrics)))
        assert result["accuracy"]["trend"] == "improving"
        assert result["accuracy"]["n"] == 6

    def test_analyze_metric_trends_declining(self) -> None:
        metrics = {"accuracy": [0.9, 0.85, 0.8, 0.7, 0.6, 0.5]}
        result = json.loads(self.agent.analyze_metric_trends(json.dumps(metrics)))
        assert result["accuracy"]["trend"] == "declining"

    def test_analyze_metric_trends_stable(self) -> None:
        metrics = {"accuracy": [0.8, 0.8, 0.8, 0.8, 0.8, 0.8]}
        result = json.loads(self.agent.analyze_metric_trends(json.dumps(metrics)))
        assert result["accuracy"]["trend"] == "stable"

    def test_analyze_metric_trends_empty(self) -> None:
        metrics = {"accuracy": []}
        result = json.loads(self.agent.analyze_metric_trends(json.dumps(metrics)))
        assert result["accuracy"]["error"] == "no data"

    def test_analyze_metric_trends_anomalies(self) -> None:
        metrics = {"latency": [1.0, 1.0, 1.0, 1.0, 1.0, 5.0]}
        result = json.loads(self.agent.analyze_metric_trends(json.dumps(metrics)))
        assert len(result["latency"]["anomalies"]) > 0

    def test_analyze_multiple_metrics(self) -> None:
        metrics = {
            "accuracy": [0.7, 0.75, 0.8],
            "latency": [0.5, 0.4, 0.3],
        }
        result = json.loads(self.agent.analyze_metric_trends(json.dumps(metrics)))
        assert "accuracy" in result
        assert "latency" in result
