"""Unit tests for workflow.rag.embedder — cache, fallback, cosine similarity."""
from __future__ import annotations

import pytest
import numpy as np


class TestEmbedRandom:
    def test_deterministic(self):
        from workflow.rag.embedder import _embed_random
        v1 = _embed_random("hello", dim=32)
        v2 = _embed_random("hello", dim=32)
        assert v1 == v2

    def test_different_input_different_vector(self):
        from workflow.rag.embedder import _embed_random
        v1 = _embed_random("hello", dim=32)
        v2 = _embed_random("world", dim=32)
        assert v1 != v2

    def test_dimension(self):
        from workflow.rag.embedder import _embed_random
        v = _embed_random("test", dim=128)
        assert len(v) == 128

    def test_returns_float_list(self):
        from workflow.rag.embedder import _embed_random
        v = _embed_random("test", dim=8)
        assert all(isinstance(x, float) for x in v)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        from workflow.rag.embedder import cosine_similarity
        v = [1.0, 2.0, 3.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors(self):
        from workflow.rag.embedder import cosine_similarity
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-6)

    def test_opposite_vectors(self):
        from workflow.rag.embedder import cosine_similarity
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0, abs=1e-6)

    def test_empty_vectors(self):
        from workflow.rag.embedder import cosine_similarity
        assert cosine_similarity([], []) == 0.0

    def test_dimension_mismatch_pads(self):
        from workflow.rag.embedder import cosine_similarity
        a = [1.0, 0.0]
        b = [1.0, 0.0, 0.0, 0.0]
        result = cosine_similarity(a, b)
        assert result == pytest.approx(1.0, abs=1e-6)

    def test_zero_vector(self):
        from workflow.rag.embedder import cosine_similarity
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


class TestCache:
    def test_cache_put_get(self):
        from workflow.rag.embedder import _cache_put, _cache_get, _embed_cache
        _embed_cache.clear()
        _cache_put("test_key", [1.0, 2.0])
        result = _cache_get("test_key")
        assert result == [1.0, 2.0]
        _embed_cache.clear()

    def test_cache_miss(self):
        from workflow.rag.embedder import _cache_get, _embed_cache
        _embed_cache.clear()
        assert _cache_get("nonexistent") is None

    def test_cache_lru_eviction(self, monkeypatch):
        from workflow.rag.embedder import _cache_put, _cache_get, _embed_cache
        _embed_cache.clear()
        # _cache_put calls _get_cache_max() which reads config, so mock it
        monkeypatch.setattr("workflow.rag.embedder._get_cache_max", lambda: 3)
        try:
            for i in range(5):
                _cache_put(f"k{i}", [float(i)])
            # oldest entries should be evicted
            assert _cache_get("k0") is None
            assert _cache_get("k1") is None
            assert _cache_get("k4") == [4.0]
        finally:
            _embed_cache.clear()


class TestGetEmbedding:
    def test_empty_input_returns_empty(self):
        from workflow.rag.embedder import get_embedding
        assert get_embedding("") == []
        assert get_embedding(None) == []

    def test_fallback_returns_vector(self, monkeypatch):
        """With all external backends disabled, should fall back to random."""
        from workflow.rag import embedder
        monkeypatch.setattr(embedder, "_embed_gemini", lambda t: None)
        monkeypatch.setattr(embedder, "_embed_http", lambda t: None)
        monkeypatch.setattr(embedder, "_embed_local", lambda t: None)
        embedder._embed_cache.clear()
        vec = embedder.get_embedding("test input")
        assert len(vec) == 64  # random fallback dim
        assert all(isinstance(x, float) for x in vec)
        embedder._embed_cache.clear()
