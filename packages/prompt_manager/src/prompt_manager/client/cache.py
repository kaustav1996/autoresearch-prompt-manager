"""Simple in-memory TTL cache for resolved prompts."""

from __future__ import annotations

import time
from typing import Any


class TTLCache:
    """Thread-safe TTL cache backed by a plain dict.

    Expired entries are evicted lazily on access.
    """

    def __init__(self, ttl: float = 60.0, max_size: int = 1024) -> None:
        self._ttl = ttl
        self._max_size = max_size
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        """Return cached value or ``None`` if missing / expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        """Store a value with the configured TTL."""
        if len(self._store) >= self._max_size:
            self._evict_expired()
        if len(self._store) >= self._max_size:
            # Drop oldest entry
            oldest_key = next(iter(self._store))
            del self._store[oldest_key]
        self._store[key] = (time.monotonic() + self._ttl, value)

    def invalidate(self, key: str) -> None:
        """Remove an entry from the cache."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all entries."""
        self._store.clear()

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, (exp, _) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
