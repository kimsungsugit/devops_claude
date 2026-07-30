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

    def test_dimension_mismatch_returns_zero(self):
        """차원 불일치는 **0.0**(관계 미확인) — 예전엔 zero-pad 해서 1.0 을 냈다.

        pad 는 "없는 차원의 값이 전부 0" 이라는 근거 없는 가정이고, 실제로는 64차원 폴백
        KB 와 768차원 Gemini 질의를 앞 64차원만으로 비교해 **무의미한 수를 그럴듯한
        유사도로 위장**했다. 상세: `tests/unit/test_rag_embed_provenance.py`.
        """
        from workflow.rag.embedder import cosine_similarity
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0, 0.0]) == 0.0

    def test_zero_vector(self):
        from workflow.rag.embedder import cosine_similarity
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


class TestCache:
    def test_cache_put_get(self, monkeypatch):
        from workflow.rag.embedder import _cache_put, _cache_get, _embed_cache
        # C3 — 캐시는 이제 설정 dim 과 일치하는 벡터만 담는다(혼합차원 방지). 이 테스트의
        # 2-차원 벡터가 담기도록 dim 을 2 로 고정.
        monkeypatch.setattr("workflow.rag.embedder.get_embed_dim", lambda: 2)
        monkeypatch.setattr("workflow.rag.embedder.get_embed_model", lambda: "m")
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
        # C3 — 1-차원 벡터가 담기도록 dim 을 1 로 고정(설정 dim 불일치 시 거부됨).
        monkeypatch.setattr("workflow.rag.embedder.get_embed_dim", lambda: 1)
        monkeypatch.setattr("workflow.rag.embedder.get_embed_model", lambda: "m")
        try:
            for i in range(5):
                _cache_put(f"k{i}", [float(i)])
            # oldest entries should be evicted
            assert _cache_get("k0") is None
            assert _cache_get("k1") is None
            assert _cache_get("k4") == [4.0]
        finally:
            _embed_cache.clear()


def _cfg_embed(monkeypatch, model, dim):
    from workflow.rag import embedder
    monkeypatch.setattr(embedder, "get_embed_model", lambda: model)
    monkeypatch.setattr(embedder, "get_embed_dim", lambda: dim)


class TestCacheDimAware:
    """C3 — 캐시키에 model+dim 포함 + 설정 차원과 다른 벡터 거부 + get(pop 아님).

    폴백 체인(Gemini 768 ↔ local 384 ↔ random 64)이 오가도 같은 text 가 혼합차원
    벡터로 pin 되지 않도록. `_cache_get` 은 pop 이 아닌 get 이라 동시 eviction 시 KeyError 무.
    """
    def test_roundtrip_correct_dim(self, monkeypatch):
        from workflow.rag import embedder
        _cfg_embed(monkeypatch, "m1", 4)
        embedder._embed_cache.clear()
        embedder._cache_put("foo", [1.0, 2.0, 3.0, 4.0])
        assert embedder._cache_get("foo") == [1.0, 2.0, 3.0, 4.0]
        embedder._embed_cache.clear()

    def test_wrong_dim_vector_not_cached(self, monkeypatch):
        """설정 차원과 다른 폴백 벡터(384/64)는 캐시 안 함 — 혼합차원 pin 방지.

        뮤테이션: `if len(vec) != get_embed_dim(): return` 을 제거하면 dim-3 이 캐시돼 실패.
        """
        from workflow.rag import embedder
        _cfg_embed(monkeypatch, "m1", 4)
        embedder._embed_cache.clear()
        embedder._cache_put("foo", [1.0, 2.0, 3.0])   # dim 3 != 4
        assert embedder._cache_get("foo") is None
        assert len(embedder._embed_cache) == 0

    def test_dim_change_does_not_return_stale_vector(self, monkeypatch):
        """dim 이 바뀌면 키가 바뀌어 stale 다른-차원 벡터를 안 되쓴다.

        뮤테이션: `_cache_key` 를 `return text` 로 되돌리면 dim=8 조회가 dim-4 를 반환해 실패.
        """
        from workflow.rag import embedder
        _cfg_embed(monkeypatch, "m1", 4)
        embedder._embed_cache.clear()
        embedder._cache_put("foo", [1.0, 2.0, 3.0, 4.0])
        assert embedder._cache_get("foo") == [1.0, 2.0, 3.0, 4.0]
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 8)
        assert embedder._cache_get("foo") is None
        embedder._embed_cache.clear()

    def test_model_change_does_not_return_stale_vector(self, monkeypatch):
        from workflow.rag import embedder
        _cfg_embed(monkeypatch, "m1", 4)
        embedder._embed_cache.clear()
        embedder._cache_put("foo", [1.0, 2.0, 3.0, 4.0])
        monkeypatch.setattr(embedder, "get_embed_model", lambda: "m2")
        assert embedder._cache_get("foo") is None
        embedder._embed_cache.clear()

    def test_get_after_eviction_is_none_not_keyerror(self, monkeypatch):
        """get 이 pop 아닌 get 이라 eviction 후에도 KeyError 없이 None (TOCTOU 제거)."""
        from workflow.rag import embedder
        _cfg_embed(monkeypatch, "m1", 2)
        monkeypatch.setattr(embedder, "_get_cache_max", lambda: 1)   # max 1 → 즉시 eviction
        embedder._embed_cache.clear()
        embedder._cache_put("a", [1.0, 2.0])
        embedder._cache_put("b", [3.0, 4.0])   # a evicted
        assert embedder._cache_get("a") is None
        assert embedder._cache_get("b") == [3.0, 4.0]
        embedder._embed_cache.clear()


class TestGetEmbedding:
    def test_empty_input_returns_empty(self):
        from workflow.rag.embedder import get_embedding
        assert get_embedding("") == []
        assert get_embedding(None) == []

    def test_fallback_returns_vector(self, monkeypatch):
        """With all external backends disabled, should fall back to random."""
        from workflow.rag import embedder
        monkeypatch.setattr(embedder, "_embed_gemini", lambda t, reasons=None: None)
        monkeypatch.setattr(embedder, "_embed_http", lambda t, reasons=None: None)
        monkeypatch.setattr(embedder, "_embed_local", lambda t, reasons=None: None)
        embedder._embed_cache.clear()
        vec = embedder.get_embedding("test input")
        assert len(vec) == 64  # random fallback dim
        assert all(isinstance(x, float) for x in vec)
        embedder._embed_cache.clear()
