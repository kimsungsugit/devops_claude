"""Unit tests for backend/cache.py TTLCache and helpers."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from backend.cache import TTLCache, cached_response, invalidate_cache


class TestTTLCache:
    def test_set_and_get(self):
        cache = TTLCache(ttl_seconds=10.0, max_size=10)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_missing(self):
        cache = TTLCache(ttl_seconds=10.0)
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        cache = TTLCache(ttl_seconds=0.05, max_size=10)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        time.sleep(0.08)
        assert cache.get("key1") is None

    def test_max_size_eviction(self):
        cache = TTLCache(ttl_seconds=60.0, max_size=2)
        cache.set("a", 1)
        time.sleep(0.01)
        cache.set("b", 2)
        time.sleep(0.01)
        cache.set("c", 3)  # should evict "a" (oldest)
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3

    def test_invalidate_single_key(self):
        cache = TTLCache(ttl_seconds=60.0)
        cache.set("x", 10)
        cache.set("y", 20)
        cache.invalidate("x")
        assert cache.get("x") is None
        assert cache.get("y") == 20

    def test_invalidate_all(self):
        cache = TTLCache(ttl_seconds=60.0)
        cache.set("x", 10)
        cache.set("y", 20)
        cache.invalidate()
        assert cache.get("x") is None
        assert cache.get("y") is None

    def test_overwrite_key(self):
        cache = TTLCache(ttl_seconds=60.0)
        cache.set("k", "old")
        cache.set("k", "new")
        assert cache.get("k") == "new"

    def test_stores_various_types(self):
        cache = TTLCache(ttl_seconds=60.0)
        cache.set("dict", {"a": 1})
        cache.set("list", [1, 2, 3])
        cache.set("none", None)
        assert cache.get("dict") == {"a": 1}
        assert cache.get("list") == [1, 2, 3]
        # None is stored but get returns None for missing too
        # The implementation returns None for both missing and None values


class TestCachedResponse:
    def test_caches_result(self):
        call_count = 0

        def compute():
            nonlocal call_count
            call_count += 1
            return {"data": 42}

        # Clear module-level cache first
        invalidate_cache()
        r1 = cached_response("test_key_cr", compute)
        r2 = cached_response("test_key_cr", compute)
        assert r1 == {"data": 42}
        assert r2 == {"data": 42}
        assert call_count == 1
        invalidate_cache()

    def test_different_keys_call_separately(self):
        invalidate_cache()
        fn1 = MagicMock(return_value="a")
        fn2 = MagicMock(return_value="b")
        assert cached_response("k1_diff", fn1) == "a"
        assert cached_response("k2_diff", fn2) == "b"
        fn1.assert_called_once()
        fn2.assert_called_once()
        invalidate_cache()


class TestInvalidateCache:
    def test_invalidate_specific(self):
        invalidate_cache()
        cached_response("inv_a", lambda: 1)
        invalidate_cache("inv_a")
        call_count = 0

        def recompute():
            nonlocal call_count
            call_count += 1
            return 2

        result = cached_response("inv_a", recompute)
        assert result == 2
        assert call_count == 1
        invalidate_cache()
