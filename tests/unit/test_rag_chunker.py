# tests/unit/test_rag_chunker.py
"""Unit tests for workflow.rag.chunker text splitting functions."""
from __future__ import annotations

import pytest

from workflow.rag.chunker import (
    _chunk_text,
    _extract_req_ids_from_text,
    _chunk_by_req_ids,
    REQ_ID_PATTERN,
)


class TestChunkText:
    def test_empty(self):
        assert _chunk_text("") == []
        assert _chunk_text(None) == []

    def test_short_text(self):
        result = _chunk_text("hello", chunk_size=100, overlap=10)
        assert result == ["hello"]

    def test_splits_long_text(self):
        text = "a" * 500
        result = _chunk_text(text, chunk_size=200, overlap=50)
        assert len(result) > 1
        assert all(len(c) <= 200 for c in result)

    def test_overlap(self):
        text = "a" * 300
        result = _chunk_text(text, chunk_size=200, overlap=100)
        assert len(result) >= 2
        # chunks should overlap
        if len(result) >= 2:
            assert len(result[0]) == 200

    def test_zero_chunk_size(self):
        text = "hello world"
        result = _chunk_text(text, chunk_size=0)
        assert result == [text]

    def test_whitespace_only(self):
        assert _chunk_text("   ") == []


class TestReqIdPattern:
    def test_matches_req(self):
        assert REQ_ID_PATTERN.search("REQ-001")

    def test_matches_sds(self):
        assert REQ_ID_PATTERN.search("SDS_FunctionName")

    def test_matches_sws(self):
        assert REQ_ID_PATTERN.search("SWS-1234")

    def test_no_match(self):
        assert not REQ_ID_PATTERN.search("just normal text")


class TestExtractReqIds:
    def test_multiple_ids(self):
        text = "REQ-001 and SDS_Foo plus SWR-002"
        result = _extract_req_ids_from_text(text)
        assert len(result) >= 2
        assert any("REQ" in r for r in result)

    def test_deduplication(self):
        text = "REQ-001 REQ-001 REQ-001"
        result = _extract_req_ids_from_text(text)
        assert len(result) == 1

    def test_empty(self):
        assert _extract_req_ids_from_text("") == []
        assert _extract_req_ids_from_text(None) == []


class TestChunkByReqIds:
    def test_no_req_ids_falls_back(self):
        text = "just plain text without requirements"
        result = _chunk_by_req_ids(text, chunk_size=100, overlap=20)
        assert len(result) >= 1

    def test_splits_by_req(self):
        text = "REQ-001 first section content\nREQ-002 second section content"
        result = _chunk_by_req_ids(text, chunk_size=500, overlap=50)
        assert len(result) >= 2
        assert any("REQ-001" in c for c in result)
        assert any("REQ-002" in c for c in result)

    def test_empty(self):
        assert _chunk_by_req_ids("", chunk_size=100, overlap=20) == []

    def test_single_req_id(self):
        text = "REQ-001 only one requirement here"
        result = _chunk_by_req_ids(text, chunk_size=500, overlap=50)
        assert len(result) >= 1

    def test_large_segment_re_chunked(self):
        text = "REQ-001 " + "x" * 2000 + "\nREQ-002 small"
        result = _chunk_by_req_ids(text, chunk_size=200, overlap=50)
        # large segment should be re-chunked
        assert len(result) > 2
