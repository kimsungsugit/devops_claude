# /app/tests/unit/test_utils.py
"""Unit tests for utils/ package."""

from __future__ import annotations

from pathlib import Path

import pytest

from utils.types import safe_dict, safe_list, fmt_bool, safe_int, safe_float
from utils.text import trim_text, strip_c_comments, normalize_whitespace, split_sentences, title_case_first
from utils.file_io import read_text_limited, read_text_safe, write_text_safe, load_json_safe, write_json_safe


class TestSafeDict:
    def test_returns_dict_when_dict(self):
        d = {"a": 1}
        assert safe_dict(d) is d

    def test_returns_empty_for_none(self):
        assert safe_dict(None) == {}

    def test_returns_empty_for_list(self):
        assert safe_dict([1, 2]) == {}

    def test_returns_empty_for_string(self):
        assert safe_dict("hello") == {}


class TestSafeList:
    def test_returns_list_when_list(self):
        lst = [1, 2, 3]
        assert safe_list(lst) is lst

    def test_returns_empty_for_none(self):
        assert safe_list(None) == []

    def test_returns_empty_for_dict(self):
        assert safe_list({"a": 1}) == []


class TestFmtBool:
    def test_true(self):
        assert fmt_bool(True) == "YES"

    def test_false(self):
        assert fmt_bool(False) == "NO"

    def test_none(self):
        assert fmt_bool(None) == "N/A"

    def test_string(self):
        assert fmt_bool("maybe") == "N/A"


class TestSafeInt:
    def test_valid_int(self):
        assert safe_int("42") == 42

    def test_invalid(self):
        assert safe_int("abc", default=-1) == -1

    def test_none(self):
        assert safe_int(None) == 0


class TestSafeFloat:
    def test_valid(self):
        assert safe_float("3.14") == pytest.approx(3.14)

    def test_invalid(self):
        assert safe_float("xyz") == 0.0


class TestTrimText:
    def test_short_text_unchanged(self):
        assert trim_text("hello", 100) == "hello"

    def test_long_text_truncated(self):
        text = "a" * 500
        result = trim_text(text, 300)
        assert len(result) < 500
        assert "truncated" in result

    def test_empty_text(self):
        assert trim_text("", 100) == ""


class TestStripCComments:
    def test_block_comment(self):
        assert strip_c_comments("int x; /* comment */ int y;") == "int x;  int y;"

    def test_line_comment(self):
        assert strip_c_comments("int x; // comment\nint y;") == "int x; \nint y;"

    def test_empty(self):
        assert strip_c_comments("") == ""


class TestNormalizeWhitespace:
    def test_multiple_spaces(self):
        assert normalize_whitespace("  hello   world  ") == "hello world"

    def test_tabs_and_newlines(self):
        assert normalize_whitespace("hello\t\n  world") == "hello world"

    def test_empty(self):
        assert normalize_whitespace("") == ""


class TestSplitSentences:
    def test_basic(self):
        result = split_sentences("First sentence. Second sentence.")
        assert len(result) == 2

    def test_empty(self):
        assert split_sentences("") == []


class TestTitleCaseFirst:
    def test_basic(self):
        assert title_case_first("hello") == "Hello"

    def test_empty(self):
        assert title_case_first("") == ""


class TestFileIO:
    def test_read_text_limited(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        assert read_text_limited(f) == "hello world"

    def test_read_text_limited_nonexistent(self, tmp_path: Path):
        f = tmp_path / "nonexistent.txt"
        assert read_text_limited(f) == ""

    def test_read_text_limited_max_bytes(self, tmp_path: Path):
        f = tmp_path / "big.txt"
        f.write_text("a" * 1000, encoding="utf-8")
        result = read_text_limited(f, max_bytes=100)
        assert len(result) == 100

    def test_read_text_safe(self, tmp_path: Path):
        f = tmp_path / "safe.txt"
        f.write_text("content", encoding="utf-8")
        assert read_text_safe(f) == "content"

    def test_write_text_safe(self, tmp_path: Path):
        f = tmp_path / "subdir" / "out.txt"
        assert write_text_safe(f, "data")
        assert f.read_text() == "data"

    def test_write_json_safe(self, tmp_path: Path):
        f = tmp_path / "data.json"
        assert write_json_safe(f, {"key": "value"})
        import json
        assert json.loads(f.read_text()) == {"key": "value"}

    def test_load_json_safe(self, tmp_path: Path):
        f = tmp_path / "data.json"
        f.write_text('{"a": 1}', encoding="utf-8")
        assert load_json_safe(f) == {"a": 1}

    def test_load_json_safe_missing(self, tmp_path: Path):
        f = tmp_path / "missing.json"
        assert load_json_safe(f, default={}) == {}
