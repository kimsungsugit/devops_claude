"""Unit tests for workflow.rag.searcher — tokenizer, keyword search, RRF."""
from __future__ import annotations

import pytest

from workflow.rag.searcher import (
    _tokenize,
    keyword_search,
    _rrf_merge,
    _apply_boosts,
)


class TestTokenize:
    def test_basic_split(self):
        tokens = _tokenize("undefined reference to foo_bar")
        assert "undefined" in tokens
        assert "reference" in tokens
        assert "foo_bar" in tokens

    def test_short_tokens_dropped(self):
        tokens = _tokenize("a b cd ef")
        assert "a" not in tokens
        assert "b" not in tokens
        assert "cd" in tokens

    def test_dedup_preserves_order(self):
        tokens = _tokenize("error error warning error")
        assert tokens == ["error", "warning"]

    def test_empty_input(self):
        assert _tokenize("") == []

    def test_special_chars(self):
        tokens = _tokenize("E2E_Calculate [CRC8] ok")
        assert "e2e_calculate" in tokens
        assert "crc8" in tokens


class TestKeywordSearch:
    SAMPLE_DATA = [
        {"error_raw": "undefined reference to foo", "fix": "add foo.c to build", "context": "linker"},
        {"error_raw": "null pointer dereference", "fix": "add null check", "context": "runtime"},
        {"error_raw": "undefined symbol bar", "fix": "link libbar", "context": "linker"},
    ]

    def test_basic_search(self):
        results = keyword_search(self.SAMPLE_DATA, "undefined reference")
        assert len(results) >= 1
        assert results[0]["error_raw"] == "undefined reference to foo"

    def test_empty_query(self):
        assert keyword_search(self.SAMPLE_DATA, "") == []

    def test_empty_data(self):
        assert keyword_search([], "test") == []

    def test_top_k(self):
        results = keyword_search(self.SAMPLE_DATA, "undefined", top_k=1)
        assert len(results) == 1

    def test_category_filter(self):
        data = [
            {"error_raw": "error", "category": "build"},
            {"error_raw": "error", "category": "test"},
        ]
        results = keyword_search(data, "error", categories=["build"])
        assert len(results) == 1
        assert results[0]["category"] == "build"

    def test_role_filter(self):
        data = [
            {"error_raw": "error", "role": "fixer"},
            {"error_raw": "error", "role": "reviewer"},
        ]
        results = keyword_search(data, "error", role="fixer")
        assert len(results) == 1


class TestRRFMerge:
    def test_merge_two_lists(self):
        list1 = [{"id": "a", "score": 10}, {"id": "b", "score": 5}]
        list2 = [{"id": "b", "score": 8}, {"id": "c", "score": 3}]
        merged = _rrf_merge([list1, list2], k=60, top_k=10)
        # b appears in both, should rank higher
        ids = [m["id"] for m in merged]
        assert "b" in ids
        assert ids.index("b") == 0  # b should be first due to dual presence

    def test_empty_lists(self):
        assert _rrf_merge([[], []], k=60, top_k=5) == []

    def test_top_k_limit(self):
        big_list = [{"id": str(i), "score": i} for i in range(20)]
        merged = _rrf_merge([big_list], k=60, top_k=3)
        assert len(merged) == 3


class TestApplyBoosts:
    def test_role_boost(self):
        items = [{"score": 1.0, "role": "fixer"}, {"score": 1.0, "role": "other"}]
        boosted = _apply_boosts(items, "query", role="fixer")
        assert boosted[0]["role"] == "fixer"
        assert boosted[0]["score"] > 1.0

    def test_stage_boost(self):
        items = [{"score": 1.0, "stage": "build"}, {"score": 1.0, "stage": "test"}]
        boosted = _apply_boosts(items, "query", stage="build")
        assert boosted[0]["stage"] == "build"
