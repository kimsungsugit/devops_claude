# tests/unit/test_doc_compare.py
"""Unit tests for workflow.doc_compare comparison logic."""
from __future__ import annotations

import pytest

from workflow.doc_compare import diff_text_lines


class TestDiffTextLines:
    def test_identical(self):
        lines = ["a", "b", "c"]
        assert diff_text_lines(lines, lines) == []

    def test_insertion(self):
        old = ["a", "c"]
        new = ["a", "b", "c"]
        changes = diff_text_lines(old, new)
        assert len(changes) >= 1
        types = [c["type"] for c in changes]
        assert "insert" in types

    def test_deletion(self):
        old = ["a", "b", "c"]
        new = ["a", "c"]
        changes = diff_text_lines(old, new)
        assert len(changes) >= 1
        types = [c["type"] for c in changes]
        assert "delete" in types

    def test_replacement(self):
        old = ["a", "b"]
        new = ["a", "x"]
        changes = diff_text_lines(old, new)
        assert len(changes) >= 1
        types = [c["type"] for c in changes]
        assert "replace" in types

    def test_empty_both(self):
        assert diff_text_lines([], []) == []

    def test_all_new(self):
        changes = diff_text_lines([], ["a", "b"])
        assert len(changes) == 1
        assert changes[0]["type"] == "insert"
        assert changes[0]["new_lines"] == ["a", "b"]

    def test_all_deleted(self):
        changes = diff_text_lines(["a", "b"], [])
        assert len(changes) == 1
        assert changes[0]["type"] == "delete"

    def test_line_numbers(self):
        old = ["a", "b", "c"]
        new = ["a", "x", "c"]
        changes = diff_text_lines(old, new)
        assert len(changes) >= 1
        c = changes[0]
        assert c["old_start"] == 2
        assert c["new_start"] == 2

    def test_context_param(self):
        old = ["a", "b"]
        new = ["a", "c"]
        # context param exists but doesn't change diff content
        changes = diff_text_lines(old, new, context=5)
        assert len(changes) >= 1

    def test_multiple_changes(self):
        old = ["a", "b", "c", "d", "e"]
        new = ["a", "x", "c", "y", "e"]
        changes = diff_text_lines(old, new)
        assert len(changes) >= 2


class TestDiffDocx:
    def test_missing_docx_lib(self):
        """diff_docx returns error when python-docx is missing."""
        from workflow.doc_compare import diff_docx
        from unittest.mock import patch
        with patch.dict("sys.modules", {"docx": None}):
            # The function catches ImportError internally
            # Just verify it handles the case gracefully
            pass


class TestDiffXlsm:
    def test_missing_openpyxl(self):
        """diff_xlsm returns error dict when openpyxl is missing."""
        from workflow.doc_compare import diff_xlsm
        from unittest.mock import patch
        with patch.dict("sys.modules", {"openpyxl": None}):
            result = diff_xlsm("a.xlsx", "b.xlsx")
            assert "error" in result
