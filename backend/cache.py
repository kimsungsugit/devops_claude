# backend/cache.py
"""Simple TTL cache for API responses."""

from __future__ import annotations

import time
import threading
from typing import Any, Callable, Optional


class TTLCache:
    """Thread-safe TTL cache with max-size eviction."""

    def __init__(self, ttl_seconds: float = 30.0, max_size: int = 128):
        self._ttl = ttl_seconds
        self._max = max_size
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, val = entry
            if time.monotonic() - ts > self._ttl:
                del self._store[key]
                return None
            return val

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if len(self._store) >= self._max:
                oldest_key = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest_key]
            self._store[key] = (time.monotonic(), value)

    def invalidate(self, key: str = "") -> None:
        with self._lock:
            if key:
                self._store.pop(key, None)
            else:
                self._store.clear()


_api_cache = TTLCache(ttl_seconds=30.0, max_size=64)


def cached_response(key: str, fn: Callable[[], Any], ttl: float = 30.0) -> Any:
    """Return cached value or compute and cache it."""
    val = _api_cache.get(key)
    if val is not None:
        return val
    result = fn()
    _api_cache.set(key, result)
    return result


def invalidate_cache(key: str = "") -> None:
    _api_cache.invalidate(key)
