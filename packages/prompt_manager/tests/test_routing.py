"""Tests for experiment routing: deterministic hash and weighted random."""

from __future__ import annotations

from collections import Counter
from uuid import UUID, uuid4

from prompt_manager.api.services.experiment_service import (
    _murmur3_32,
    pick_arm_deterministic,
    pick_arm_random,
)
from prompt_manager.core.models import ExperimentArm


def _arm(weight: float, label: str | None = None) -> ExperimentArm:
    return ExperimentArm(
        id=uuid4(),
        experiment_id=uuid4(),
        version_id=uuid4(),
        weight=weight,
        label=label,
    )


class TestMurmurHash3:
    def test_deterministic(self) -> None:
        h1 = _murmur3_32(b"hello")
        h2 = _murmur3_32(b"hello")
        assert h1 == h2

    def test_different_inputs(self) -> None:
        h1 = _murmur3_32(b"hello")
        h2 = _murmur3_32(b"world")
        assert h1 != h2

    def test_seed_matters(self) -> None:
        h1 = _murmur3_32(b"test", seed=0)
        h2 = _murmur3_32(b"test", seed=42)
        assert h1 != h2

    def test_returns_32bit(self) -> None:
        h = _murmur3_32(b"some key")
        assert 0 <= h < 2**32

    def test_empty_key(self) -> None:
        h = _murmur3_32(b"")
        assert isinstance(h, int)


class TestDeterministicRouting:
    def test_same_session_same_arm(self) -> None:
        arms = [_arm(50.0, "A"), _arm(50.0, "B")]
        exp_id = uuid4()
        session = "user-123"
        results = {pick_arm_deterministic(arms, exp_id, session).id for _ in range(100)}
        assert len(results) == 1  # always the same arm

    def test_different_sessions_distribute(self) -> None:
        arms = [_arm(50.0, "A"), _arm(50.0, "B")]
        exp_id = uuid4()
        chosen_ids = set()
        for i in range(200):
            arm = pick_arm_deterministic(arms, exp_id, f"session-{i}")
            chosen_ids.add(arm.id)
        # With 50/50 weights and 200 sessions, both arms should appear
        assert len(chosen_ids) == 2

    def test_single_arm(self) -> None:
        arms = [_arm(100.0, "only")]
        arm = pick_arm_deterministic(arms, uuid4(), "any-session")
        assert arm.label == "only"

    def test_weight_distribution_approximate(self) -> None:
        """With 80/20 weights, the distribution should be roughly proportional."""
        arm_a = _arm(80.0, "A")
        arm_b = _arm(20.0, "B")
        arms = [arm_a, arm_b]
        exp_id = uuid4()
        counts: Counter[UUID] = Counter()
        n = 5000
        for i in range(n):
            chosen = pick_arm_deterministic(arms, exp_id, f"sess-{i}")
            counts[chosen.id] += 1
        ratio_a = counts[arm_a.id] / n
        # Should be roughly 0.80 +/- 0.05
        assert 0.70 < ratio_a < 0.90


class TestWeightedRandom:
    def test_single_arm(self) -> None:
        arms = [_arm(100.0, "only")]
        arm = pick_arm_random(arms)
        assert arm.label == "only"

    def test_distribution_approximate(self) -> None:
        arm_a = _arm(70.0, "A")
        arm_b = _arm(30.0, "B")
        arms = [arm_a, arm_b]
        counts: Counter[UUID] = Counter()
        n = 3000
        for _ in range(n):
            chosen = pick_arm_random(arms)
            counts[chosen.id] += 1
        ratio_a = counts[arm_a.id] / n
        # Should be roughly 0.70 +/- 0.10
        assert 0.55 < ratio_a < 0.85
