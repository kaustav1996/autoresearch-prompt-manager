"""Tests for request/response schema serialisation."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from prompt_manager.core.enums import VersionSource
from prompt_manager.core.schemas import (
    ArmCreate,
    ExperimentCreate,
    MetricIngest,
    PromptCreate,
    PromptResponse,
    PromptUpdate,
    ResolveResponse,
    VersionCreate,
    VersionResponse,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TestPromptCreate:
    def test_valid(self) -> None:
        data = PromptCreate(slug="my-prompt", name="My Prompt", body="Hello!")
        assert data.slug == "my-prompt"
        assert data.tags == []
        assert data.metadata == {}

    def test_missing_body_fails(self) -> None:
        with pytest.raises(ValidationError):
            PromptCreate(slug="x", name="X")  # type: ignore[call-arg]


class TestPromptUpdate:
    def test_partial(self) -> None:
        u = PromptUpdate(name="New Name")
        dump = u.model_dump(exclude_none=True)
        assert dump == {"name": "New Name"}

    def test_empty(self) -> None:
        u = PromptUpdate()
        assert u.model_dump(exclude_none=True) == {}


class TestPromptResponse:
    def test_roundtrip(self) -> None:
        pid = uuid4()
        r = PromptResponse(
            id=pid,
            slug="test",
            name="Test",
            tags=["a"],
            metadata={"k": "v"},
            current_version=2,
            created_at=_now(),
            updated_at=_now(),
        )
        data = r.model_dump(mode="json")
        assert data["id"] == str(pid)
        assert data["tags"] == ["a"]


class TestVersionCreate:
    def test_defaults(self) -> None:
        v = VersionCreate(body="prompt body")
        assert v.source == VersionSource.MANUAL
        assert v.template_vars == []


class TestVersionResponse:
    def test_serialize(self) -> None:
        vid = uuid4()
        r = VersionResponse(
            id=vid,
            prompt_id=uuid4(),
            version=3,
            body="hello",
            template_vars=["name"],
            content_hash="abc",
            source=VersionSource.MANUAL,
            created_at=_now(),
        )
        data = r.model_dump(mode="json")
        assert data["version"] == 3
        assert data["source"] == "manual"


class TestExperimentCreate:
    def test_with_arms(self) -> None:
        e = ExperimentCreate(
            prompt_slug="test",
            name="A/B Test",
            arms=[
                ArmCreate(version_id=uuid4(), weight=50.0),
                ArmCreate(version_id=uuid4(), weight=50.0),
            ],
        )
        assert len(e.arms) == 2
        assert sum(a.weight for a in e.arms) == 100.0


class TestMetricIngest:
    def test_valid(self) -> None:
        m = MetricIngest(
            prompt_id=uuid4(),
            version_id=uuid4(),
            metric_name="latency",
            metric_value=100.0,
        )
        assert m.experiment_id is None


class TestResolveResponse:
    def test_serialize(self) -> None:
        r = ResolveResponse(
            slug="test",
            version=1,
            body="Hello {{name}}",
            template_vars=["name"],
            content_hash="abc123",
            version_id=uuid4(),
        )
        data = r.model_dump(mode="json")
        assert data["slug"] == "test"
        assert data["experiment_id"] is None
