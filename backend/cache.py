# backend/cache.py
"""Simple TTL cache for API responses."""

from __future__ import annotations

import threading
import time
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


class KeyedBuildLocks:
    """키별 빌드 락 — 캐시 miss 가 겹칠 때 같은 계산을 N번 하지 않게 한다(single-flight).

    **TTL 캐시만으로는 pile-up 을 못 막는다.** 락을 캐시 *조회*에만 걸고 계산은 락 밖에서
    하면, cold key 에 동시 도착한 N개 요청이 **전부** 계산한다 — 캐시는 "누군가 먼저
    끝낸 다음"부터만 듣는다. 계산이 비쌀수록(원격 IPC·수십 MB 파싱) 이 구멍이 커진다.

    실측(2026-08-06, KJPDS02_PV): cloudium VectorCAST 폴더 파싱이 단독 233초인데,
    같은 폴더를 요구하는 요청 둘이 겹치자 **460초**가 됐다(워커는 하나라 서로 경합).
    `_VCAST_CLOUDIUM_PARSE_CACHE` 와 `_UDS_MAPPING_CACHE` 둘 다 "동시 miss 는 redundant
    parse 허용(락 점유 최소화)" 라고 적어 두고 정확히 그 비용을 치르고 있었다.

    ⚠ 이 락은 **정확성 장치가 아니라 중복 제거 최적화**다. 그래서 상한 초과 시 사용
    중인 락을 버려도 안전하다(새 락으로 다시 직렬화될 뿐, 캐시 쓰기 자체는 원자적).
    전역 단일 락으로 만들면 서로 다른 키끼리도 직렬화되므로 반드시 키별로 나눈다.
    """

    def __init__(self, max_keys: int = 16):
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._max = max_keys

    def get(self, key: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                if len(self._locks) >= self._max:
                    self._locks.clear()
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def run(self, key: str, cache_get: Callable[[], Any], build: Callable[[], Any]) -> Any:
        """double-checked single-flight — 조회 → 락 → **재확인** → 계산.

        재확인이 핵심이다. 이걸 빼면 대기하던 쪽이 먼저 끝낸 쪽의 결과를 안 쓰고
        똑같이 계산해, 직렬화만 하고 중복은 그대로 남는다(더 나빠진다).

        `cache_get()` 은 신선한 값이 있으면 그 값을, 없으면 **None** 을 반환해야 한다.
        ⚠ `None` 자체를 유효한 캐시 값으로 쓰는 캐시(예: `_SCM_VCAST_METRICS_CACHE`)
        에는 그대로 쓸 수 없다 — sentinel 을 따로 두거나 `get()` 을 직접 쓸 것.
        """
        hit = cache_get()
        if hit is not None:
            return hit
        with self.get(key):
            hit = cache_get()
            if hit is not None:
                return hit
            return build()


_api_cache = TTLCache(ttl_seconds=30.0, max_size=64)


_api_build_locks = KeyedBuildLocks(max_keys=32)


def cached_response(key: str, fn: Callable[[], Any]) -> Any:
    """Return cached value or compute and cache it (single-flight).

    TTL 은 `_api_cache` 의 것(30초)을 쓴다. 예전 시그니처엔 `ttl` 인자가 있었으나
    **본문에서 한 번도 쓰이지 않았다** — 호출자가 30.0 을 넘겨 우연히 일치했을 뿐,
    다른 값을 주면 조용히 무시됐다. 거짓 인자를 남기느니 없앤다.
    """
    def _get() -> Any:
        return _api_cache.get(key)

    def _build() -> Any:
        result = fn()
        _api_cache.set(key, result)
        return result

    return _api_build_locks.run(key, _get, _build)


def invalidate_cache(key: str = "") -> None:
    _api_cache.invalidate(key)
