"""Async HTTP client SDK for the Prompt Manager API."""

from __future__ import annotations

from typing import Any

import httpx

from prompt_manager.client.cache import TTLCache
from prompt_manager.client.models import ResolvedPrompt


class PromptManagerClient:
    """Async client for resolving prompts and reporting metrics.

    Usage::

        async with PromptManagerClient("http://localhost:8910") as pm:
            prompt = await pm.resolve("my-prompt", session_id="user-123")
            rendered = prompt.render(name="Alice")
            await pm.report_metric(
                slug="my-prompt",
                version_id=str(prompt.version_id),
                metric_name="latency_ms",
                value=120.5,
            )
    """

    def __init__(
        self,
        base_url: str,
        *,
        cache_ttl: float | None = 60.0,
        timeout: float = 5.0,
    ) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._cache: TTLCache | None = TTLCache(ttl=cache_ttl) if cache_ttl else None

    async def __aenter__(self) -> PromptManagerClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    # ── Resolve ───────────────────────────────────────────────────────────

    async def resolve(
        self,
        slug: str,
        *,
        version: int | None = None,
        session_id: str | None = None,
        variables: dict[str, str] | None = None,
    ) -> ResolvedPrompt:
        """Resolve a prompt by slug, optionally pinning version or session."""
        cache_key = f"{slug}:v={version}:s={session_id}"

        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        params: dict[str, Any] = {}
        if version is not None:
            params["version"] = version
        if session_id is not None:
            params["session_id"] = session_id

        resp = await self._client.get(f"/resolve/{slug}", params=params)
        resp.raise_for_status()
        resolved = ResolvedPrompt.model_validate(resp.json())

        if self._cache is not None:
            self._cache.set(cache_key, resolved)

        return resolved

    # ── Metrics ───────────────────────────────────────────────────────────

    async def report_metric(
        self,
        slug: str,
        version_id: str,
        metric_name: str,
        value: float,
        *,
        prompt_id: str | None = None,
        session_id: str | None = None,
        experiment_id: str | None = None,
        arm_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Report a single metric event to the API."""
        # If prompt_id not provided, resolve it
        if prompt_id is None:
            resp = await self._client.get(f"/prompts/{slug}")
            resp.raise_for_status()
            prompt_id = resp.json()["id"]

        payload: dict[str, Any] = {
            "prompt_id": prompt_id,
            "version_id": version_id,
            "metric_name": metric_name,
            "metric_value": value,
        }
        if session_id is not None:
            payload["session_id"] = session_id
        if experiment_id is not None:
            payload["experiment_id"] = experiment_id
        if arm_id is not None:
            payload["arm_id"] = arm_id
        if metadata:
            payload["metadata"] = metadata

        resp = await self._client.post("/metrics", json=payload)
        resp.raise_for_status()
