"""Batched async sender for metric events."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class MetricReporter:
    """Sends batches of metric events to the Prompt Manager API."""

    def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def send_batch(self, events: list[dict[str, Any]]) -> int:
        """POST a batch of events. Returns the number of events inserted."""
        resp = await self._client.post("/metrics/batch", json={"events": events})
        resp.raise_for_status()
        data = resp.json()
        inserted: int = data.get("inserted", 0)
        logger.debug("Sent batch of %d metric events", inserted)
        return inserted

    async def send_single(self, event: dict[str, Any]) -> str:
        """POST a single event. Returns the event id."""
        resp = await self._client.post("/metrics", json=event)
        resp.raise_for_status()
        return resp.json()["id"]

    async def close(self) -> None:
        await self._client.aclose()
