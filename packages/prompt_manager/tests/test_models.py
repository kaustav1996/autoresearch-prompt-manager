"""Tests for core domain models."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from prompt_manager.core.enums import ExperimentStatus, VersionSource
from prompt_manager.core.models import (
    Experiment,
    ExperimentArm,
    MetricEvent,
    Prompt,
    PromptVersion,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TestPrompt:
    def test_create_minimal(self) -> None:
        p = Prompt(id=uuid4(), slug="test", name="Test", created_at=_now(), updated_at=_now())
        assert p.slug == "test"
        assert p.tags == []
        assert p.metadata == {}
        assert p.current_version == 1

    def test_create_full(self) -> None:
        p = Prompt(
            id=uuid4(),
            slug="full-test",
            name="Full",
            description="A full prompt",
            tags=["tag1", "tag2"],
            metadata={"key": "val"},
            current_version=3,
            created_at=_now(),
            updated_at=_now(),
        )
        assert p.description == "A full prompt"
        assert len(p.tags) == 2
        assert p.current_version == 3

    def test_missing_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            Prompt(id=uuid4(), slug="x")  # type: ignore[call-arg]


class TestPromptVersion:
    def test_create(self) -> None:
        v = PromptVersion(
            id=uuid4(),
            prompt_id=uuid4(),
            version=1,
            body="Hello {{name}}",
            content_hash="abc123",
            created_at=_now(),
        )
        assert v.source == VersionSource.MANUAL
        assert v.parent_version is None
        assert v.template_vars == []

    def test_source_enum(self) -> None:
        v = PromptVersion(
            id=uuid4(),
            prompt_id=uuid4(),
            version=2,
            body="body",
            content_hash="def456",
            source=VersionSource.OPTIMIZATION,
            created_at=_now(),
        )
        assert v.source == "optimization"


class TestExperiment:
    def test_defaults(self) -> None:
        e = Experiment(
            id=uuid4(), prompt_id=uuid4(), name="exp1", created_at=_now()
        )
        assert e.status == ExperimentStatus.DRAFT
        assert e.sticky is True
        assert e.auto_optimize is False
        assert e.min_sample_size == 100


class TestExperimentArm:
    def test_create(self) -> None:
        a = ExperimentArm(
            id=uuid4(), experiment_id=uuid4(), version_id=uuid4(), weight=50.0
        )
        assert a.weight == 50.0
        assert a.label is None


class TestMetricEvent:
    def test_minimal(self) -> None:
        m = MetricEvent(
            prompt_id=uuid4(),
            version_id=uuid4(),
            metric_name="latency",
            metric_value=42.0,
        )
        assert m.experiment_id is None
        assert m.metadata == {}

    def test_full(self) -> None:
        m = MetricEvent(
            prompt_id=uuid4(),
            version_id=uuid4(),
            experiment_id=uuid4(),
            arm_id=uuid4(),
            session_id="sess-123",
            metric_name="accuracy",
            metric_value=0.95,
            metadata={"model": "gpt-4"},
        )
        assert m.session_id == "sess-123"
        assert m.metadata["model"] == "gpt-4"
