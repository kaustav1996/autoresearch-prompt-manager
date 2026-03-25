"""MetricCollector: async queue with periodic flush."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from prompt_manager.metric.reporter import MetricReporter

logger = logging.getLogger(__name__)


class MetricCollector:
    """Collects metric events in an async queue and flushes them in batches.

    Usage::

        collector = MetricCollector(base_url="http://localhost:8910")
        await collector.start()

        collector.push({
            "prompt_id": "...",
            "version_id": "...",
            "metric_name": "latency_ms",
            "metric_value": 123.4,
        })

        await collector.stop()  # flushes remaining
    """

    def __init__(
        self,
        base_url: str,
        *,
        batch_size: int = 50,
        flush_interval: float = 5.0,
        max_queue_size: int = 10_000,
        timeout: float = 10.0,
    ) -> None:
        self._reporter = MetricReporter(base_url=base_url, timeout=timeout)
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_queue_size)
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """Start the background flush loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        """Stop the flush loop and drain remaining events."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Final flush
        await self._flush()
        await self._reporter.close()

    def push(self, event: dict[str, Any]) -> None:
        """Enqueue a metric event (non-blocking, drops if full)."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Metric queue full – dropping event")

    async def _flush_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._flush_interval)
            await self._flush()

    async def _flush(self) -> None:
        """Drain up to ``_batch_size`` events and send them."""
        batch: list[dict[str, Any]] = []
        while not self._queue.empty() and len(batch) < self._batch_size:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if batch:
            try:
                await self._reporter.send_batch(batch)
            except Exception:
                logger.exception("Failed to send metric batch (%d events)", len(batch))
