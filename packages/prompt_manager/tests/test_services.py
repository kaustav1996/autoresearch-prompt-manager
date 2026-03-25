"""Tests for service layer with mocked repositories."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from prompt_manager.core.enums import ExperimentStatus, VersionSource
from prompt_manager.core.exceptions import (
    DuplicateContentError,
    DuplicateSlugError,
    ExperimentStateError,
    InvalidWeightsError,
    PromptNotFoundError,
)
from prompt_manager.core.models import Experiment, Prompt, PromptVersion
from prompt_manager.core.schemas import ArmCreate, PromptCreate, PromptUpdate


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_prompt(slug: str = "test") -> Prompt:
    return Prompt(
        id=uuid4(),
        slug=slug,
        name="Test",
        created_at=_now(),
        updated_at=_now(),
    )


def _make_version(prompt_id=None, version: int = 1, body: str = "hello") -> PromptVersion:
    return PromptVersion(
        id=uuid4(),
        prompt_id=prompt_id or uuid4(),
        version=version,
        body=body,
        content_hash=hashlib.sha256(body.encode()).hexdigest(),
        created_at=_now(),
    )


class TestPromptService:
    @pytest.mark.asyncio
    @patch("prompt_manager.api.services.prompt_service.versions_repo")
    @patch("prompt_manager.api.services.prompt_service.prompts_repo")
    async def test_create_prompt(self, mock_pr: MagicMock, mock_vr: MagicMock) -> None:
        prompt = _make_prompt()
        version = _make_version(prompt.id)

        mock_pr.get_by_slug = AsyncMock(return_value=None)
        mock_pr.create = AsyncMock(return_value=prompt)
        mock_vr.create = AsyncMock(return_value=version)

        from prompt_manager.api.services.prompt_service import create_prompt

        conn = AsyncMock()
        data = PromptCreate(slug="test", name="Test", body="hello")
        p, v = await create_prompt(conn, data)
        assert p.slug == "test"
        assert v.version == 1
        mock_pr.create.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("prompt_manager.api.services.prompt_service.prompts_repo")
    async def test_create_duplicate_slug(self, mock_pr: MagicMock) -> None:
        mock_pr.get_by_slug = AsyncMock(return_value=_make_prompt())

        from prompt_manager.api.services.prompt_service import create_prompt

        conn = AsyncMock()
        data = PromptCreate(slug="test", name="Test", body="hello")
        with pytest.raises(DuplicateSlugError):
            await create_prompt(conn, data)

    @pytest.mark.asyncio
    @patch("prompt_manager.api.services.prompt_service.prompts_repo")
    async def test_get_prompt_not_found(self, mock_pr: MagicMock) -> None:
        mock_pr.get_by_slug = AsyncMock(return_value=None)

        from prompt_manager.api.services.prompt_service import get_prompt

        with pytest.raises(PromptNotFoundError):
            await get_prompt(AsyncMock(), "nonexistent")

    @pytest.mark.asyncio
    @patch("prompt_manager.api.services.prompt_service.prompts_repo")
    @patch("prompt_manager.api.services.prompt_service.versions_repo")
    async def test_add_version_dedup(self, mock_vr: MagicMock, mock_pr: MagicMock) -> None:
        prompt = _make_prompt()
        mock_pr.get_by_slug = AsyncMock(return_value=prompt)
        mock_vr.content_hash = lambda body: hashlib.sha256(body.encode()).hexdigest()
        mock_vr.hash_exists = AsyncMock(return_value=True)

        from prompt_manager.api.services.prompt_service import add_version

        with pytest.raises(DuplicateContentError):
            await add_version(AsyncMock(), "test", body="duplicate body")


class TestExperimentService:
    @pytest.mark.asyncio
    @patch("prompt_manager.api.services.experiment_service.experiments_repo")
    async def test_invalid_weights(self, mock_er: MagicMock) -> None:
        from prompt_manager.api.services.experiment_service import create_experiment

        arms = [
            ArmCreate(version_id=uuid4(), weight=60.0),
            ArmCreate(version_id=uuid4(), weight=30.0),
        ]
        with pytest.raises(InvalidWeightsError):
            await create_experiment(
                AsyncMock(),
                prompt_id=uuid4(),
                name="bad",
                arms=arms,
            )

    @pytest.mark.asyncio
    @patch("prompt_manager.api.services.experiment_service.experiments_repo")
    async def test_invalid_state_transition(self, mock_er: MagicMock) -> None:
        exp = Experiment(
            id=uuid4(),
            prompt_id=uuid4(),
            name="exp",
            status=ExperimentStatus.CONCLUDED,
            created_at=_now(),
        )
        mock_er.get_by_id = AsyncMock(return_value=exp)

        from prompt_manager.api.services.experiment_service import update_status

        with pytest.raises(ExperimentStateError):
            await update_status(AsyncMock(), exp.id, ExperimentStatus.RUNNING)

    @pytest.mark.asyncio
    @patch("prompt_manager.api.services.experiment_service.experiments_repo")
    async def test_valid_state_transition(self, mock_er: MagicMock) -> None:
        exp = Experiment(
            id=uuid4(),
            prompt_id=uuid4(),
            name="exp",
            status=ExperimentStatus.DRAFT,
            created_at=_now(),
        )
        updated = Experiment(**{**exp.model_dump(), "status": ExperimentStatus.RUNNING})
        mock_er.get_by_id = AsyncMock(return_value=exp)
        mock_er.update_status = AsyncMock(return_value=updated)

        from prompt_manager.api.services.experiment_service import update_status

        result = await update_status(AsyncMock(), exp.id, ExperimentStatus.RUNNING)
        assert result.status == ExperimentStatus.RUNNING


class TestOptimizationService:
    @pytest.mark.asyncio
    async def test_missing_api_key_returns_error(self) -> None:
        from unittest.mock import AsyncMock

        from prompt_manager.api.services.optimization_service import trigger_optimization
        from prompt_manager.core.config import PromptManagerSettings
        from prompt_manager.core.schemas import OptimizeRequest

        mock_conn = AsyncMock()
        settings = PromptManagerSettings(llm_api_key=None)
        result = await trigger_optimization(
            OptimizeRequest(prompt_slug="test"), mock_conn, settings
        )
        assert result.status == "error"
        assert "API_KEY" in result.message or "not installed" in result.message
