"""Tests for AutoResearcherConfig and composite scoring."""

from __future__ import annotations

import pytest

from autoresearcher_shonku.config import AutoResearcherConfig
from autoresearcher_shonku.errors import ScoringError
from autoresearcher_shonku.scoring import compute_composite_score, is_improvement


class TestAutoResearcherConfig:
    def test_defaults(self) -> None:
        config = AutoResearcherConfig()
        assert config.max_iterations == 10
        assert config.min_sample_size == 100
        assert config.improvement_threshold == 0.01
        assert config.max_edit_distance == 0.5
        assert config.canary_weight == 5.0
        assert config.cooldown_minutes == 30
        assert config.rollback_on_regression is True
        assert config.simplicity_preference is True

    def test_custom_values(self) -> None:
        config = AutoResearcherConfig(
            max_iterations=5,
            min_sample_size=50,
            improvement_threshold=0.05,
        )
        assert config.max_iterations == 5
        assert config.min_sample_size == 50
        assert config.improvement_threshold == 0.05

    def test_validation_max_iterations(self) -> None:
        with pytest.raises(Exception):
            AutoResearcherConfig(max_iterations=0)

    def test_validation_threshold_range(self) -> None:
        with pytest.raises(Exception):
            AutoResearcherConfig(improvement_threshold=2.0)

    def test_serialization(self) -> None:
        config = AutoResearcherConfig()
        data = config.model_dump()
        assert isinstance(data, dict)
        assert "max_iterations" in data
        restored = AutoResearcherConfig(**data)
        assert restored == config


class TestCompositeScoring:
    def test_equal_weights(self) -> None:
        metrics = {"a": 0.8, "b": 0.6}
        score = compute_composite_score(metrics, weights={"a": 1.0, "b": 1.0})
        assert score == pytest.approx(0.7, abs=0.01)

    def test_weighted(self) -> None:
        metrics = {"accuracy": 0.9, "latency": 0.5}
        score = compute_composite_score(metrics, weights={"accuracy": 3.0, "latency": 1.0})
        # (0.9*3 + 0.5*1) / 4 = 3.2 / 4 = 0.8
        assert score == pytest.approx(0.8, abs=0.01)

    def test_default_weights(self) -> None:
        metrics = {"accuracy": 0.8, "latency": 0.6}
        score = compute_composite_score(metrics)
        assert 0.0 <= score <= 1.0

    def test_empty_metrics_raises(self) -> None:
        with pytest.raises(ScoringError):
            compute_composite_score({})

    def test_single_metric(self) -> None:
        score = compute_composite_score({"accuracy": 0.75})
        assert score == pytest.approx(0.75, abs=0.01)

    def test_clamped_to_unit(self) -> None:
        # Even with out-of-range input, score is clamped
        score = compute_composite_score({"x": 1.5}, weights={"x": 1.0})
        assert score <= 1.0


class TestIsImprovement:
    def test_improvement_maximize(self) -> None:
        assert is_improvement(0.85, 0.80, threshold=0.01) is True

    def test_no_improvement_maximize(self) -> None:
        assert is_improvement(0.805, 0.80, threshold=0.01) is False

    def test_improvement_minimize(self) -> None:
        assert is_improvement(0.15, 0.20, threshold=0.01, direction="minimize") is True

    def test_no_improvement_minimize(self) -> None:
        assert is_improvement(0.195, 0.20, threshold=0.01, direction="minimize") is False

    def test_exact_threshold(self) -> None:
        assert is_improvement(0.81, 0.80, threshold=0.01) is True

    def test_unknown_direction_raises(self) -> None:
        with pytest.raises(ScoringError):
            is_improvement(0.8, 0.7, threshold=0.01, direction="unknown")
