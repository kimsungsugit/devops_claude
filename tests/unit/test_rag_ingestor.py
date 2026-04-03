# tests/unit/test_rag_ingestor.py
"""Unit tests for workflow.rag.ingestor helper functions."""
from __future__ import annotations

from pathlib import Path

import pytest

from workflow.rag.ingestor import (
    _split_paths,
    _collect_files_from_paths,
    _infer_vectorcast_tags,
)


class TestSplitPaths:
    def test_none(self):
        assert _split_paths(None) == []

    def test_empty_string(self):
        assert _split_paths("") == []

    def test_comma_separated(self):
        result = _split_paths("/a, /b, /c")
        assert result == ["/a", "/b", "/c"]

    def test_semicolon_separated(self):
        result = _split_paths("/a;/b;/c")
        assert result == ["/a", "/b", "/c"]

    def test_newline_separated(self):
        result = _split_paths("/a\n/b\n/c")
        assert result == ["/a", "/b", "/c"]

    def test_list_input(self):
        result = _split_paths(["/a", "/b"])
        assert result == ["/a", "/b"]

    def test_strips_whitespace(self):
        result = _split_paths("  /a , /b  ")
        assert result == ["/a", "/b"]

    def test_filters_empty(self):
        result = _split_paths(",,,/a,,,")
        assert result == ["/a"]


class TestCollectFilesFromPaths:
    def test_single_file(self, tmp_path):
        f = tmp_path / "test.c"
        f.write_text("int x;", encoding="utf-8")
        result = _collect_files_from_paths([str(f)])
        assert len(result) == 1
        assert result[0].name == "test.c"

    def test_directory_with_ext_filter(self, tmp_path):
        (tmp_path / "a.c").write_text("int a;", encoding="utf-8")
        (tmp_path / "b.h").write_text("int b;", encoding="utf-8")
        (tmp_path / "c.txt").write_text("text", encoding="utf-8")
        result = _collect_files_from_paths([str(tmp_path)], exts=(".c", ".h"))
        names = {r.name for r in result}
        assert "a.c" in names
        assert "b.h" in names
        assert "c.txt" not in names

    def test_max_files(self, tmp_path):
        for i in range(10):
            (tmp_path / f"f{i}.c").write_text(f"int x{i};", encoding="utf-8")
        result = _collect_files_from_paths([str(tmp_path)], exts=(".c",), max_files=3)
        assert len(result) <= 3

    def test_deduplication(self, tmp_path):
        f = tmp_path / "a.c"
        f.write_text("int a;", encoding="utf-8")
        result = _collect_files_from_paths([str(f), str(f)])
        assert len(result) == 1

    def test_nonexistent_path(self):
        result = _collect_files_from_paths(["/nonexistent/path/xyz"])
        assert result == []

    def test_glob_pattern(self, tmp_path):
        sub = tmp_path / "src"
        sub.mkdir()
        (sub / "main.c").write_text("int x;", encoding="utf-8")
        (sub / "util.h").write_text("int y;", encoding="utf-8")
        result = _collect_files_from_paths([str(tmp_path)], globs=["**/*.c"])
        names = {r.name for r in result}
        assert "main.c" in names


class TestInferVectorcastTags:
    def test_unit_test(self):
        tags = _infer_vectorcast_tags(Path("ut_report.html"))
        assert "vectorcast" in tags
        assert "ut" in tags

    def test_integration(self):
        tags = _infer_vectorcast_tags(Path("integration_results.csv"))
        assert "it" in tags

    def test_coverage(self):
        tags = _infer_vectorcast_tags(Path("coverage_summary.txt"))
        assert "coverage" in tags

    def test_plain(self):
        tags = _infer_vectorcast_tags(Path("results.log"))
        assert tags == ["vectorcast"]
