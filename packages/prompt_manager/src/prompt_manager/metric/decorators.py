"""Decorator for automatic metric tracking."""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, TypeVar

from prompt_manager.metric.collector import MetricCollector

F = TypeVar("F", bound=Callable[..., Any])


def track_metric(
    collector: MetricCollector,
    *,
    metric_name: str = "latency_ms",
    prompt_id: str | None = None,
    version_id: str | None = None,
    extract_ids: Callable[..., dict[str, str]] | None = None,
) -> Callable[[F], F]:
    """Decorator that measures execution time and pushes a metric event.

    If ``extract_ids`` is provided it is called with the same args/kwargs
    as the wrapped function and must return a dict containing at least
    ``prompt_id`` and ``version_id``.

    Usage::

        @track_metric(collector, metric_name="latency_ms",
                       prompt_id="...", version_id="...")
        async def my_llm_call(text: str) -> str:
            ...
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            ids = _resolve_ids(args, kwargs)
            start = time.perf_counter()
            try:
                result = await fn(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                event: dict[str, Any] = {
                    **ids,
                    "metric_name": metric_name,
                    "metric_value": elapsed_ms,
                }
                collector.push(event)
            return result

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            ids = _resolve_ids(args, kwargs)
            start = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                event: dict[str, Any] = {
                    **ids,
                    "metric_name": metric_name,
                    "metric_value": elapsed_ms,
                }
                collector.push(event)
            return result

        def _resolve_ids(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, str]:
            if extract_ids is not None:
                return extract_ids(*args, **kwargs)
            ids: dict[str, str] = {}
            if prompt_id is not None:
                ids["prompt_id"] = prompt_id
            if version_id is not None:
                ids["version_id"] = version_id
            return ids

        import asyncio

        if asyncio.iscoroutinefunction(fn):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator
