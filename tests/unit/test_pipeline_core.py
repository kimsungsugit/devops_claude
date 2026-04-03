"""Unit tests for workflow.pipeline utility functions."""
from __future__ import annotations

from pathlib import Path

import pytest


class TestCmakeQuote:
    def test_backslash_to_forward(self):
        from workflow.pipeline import _cmake_quote
        assert _cmake_quote("C:\\Users\\test") == '"C:/Users/test"'

    def test_empty_string(self):
        from workflow.pipeline import _cmake_quote
        assert _cmake_quote("") == '""'

    def test_none_becomes_empty(self):
        from workflow.pipeline import _cmake_quote
        assert _cmake_quote(None) == '""'

    def test_already_forward(self):
        from workflow.pipeline import _cmake_quote
        assert _cmake_quote("/usr/local/include") == '"/usr/local/include"'


class TestNormalizeDefine:
    def test_strip_dash_d(self):
        from workflow.pipeline import _normalize_define
        assert _normalize_define("-DFOO") == "FOO"

    def test_plain_define(self):
        from workflow.pipeline import _normalize_define
        assert _normalize_define("BAR=1") == "BAR=1"

    def test_whitespace_returns_none(self):
        from workflow.pipeline import _normalize_define
        assert _normalize_define("FOO BAR") is None

    def test_quotes_returns_none(self):
        from workflow.pipeline import _normalize_define
        assert _normalize_define('FOO="bar"') is None

    def test_empty_returns_none(self):
        from workflow.pipeline import _normalize_define
        assert _normalize_define("") is None
        assert _normalize_define(None) is None
        assert _normalize_define("   ") is None


class TestNormalizeIncludeDir:
    def test_relative_path(self):
        from workflow.pipeline import _normalize_include_dir
        root = Path("/project")
        result = _normalize_include_dir(root, "./src/include")
        assert result == "${PROJECT_SOURCE_DIR}/src/include"

    def test_empty_returns_none(self):
        from workflow.pipeline import _normalize_include_dir
        assert _normalize_include_dir(Path("/p"), "") is None
        assert _normalize_include_dir(Path("/p"), None) is None

    def test_strips_quotes(self):
        from workflow.pipeline import _normalize_include_dir
        result = _normalize_include_dir(Path("/p"), '"src/inc"')
        assert "${PROJECT_SOURCE_DIR}" in result


class TestWriteText:
    def test_writes_file(self, tmp_path):
        from workflow.pipeline import _write_text
        p = tmp_path / "sub" / "test.txt"
        _write_text(p, "hello")
        assert p.read_text(encoding="utf-8") == "hello"

    def test_none_text_writes_empty(self, tmp_path):
        from workflow.pipeline import _write_text
        p = tmp_path / "empty.txt"
        _write_text(p, None)
        assert p.read_text(encoding="utf-8") == ""


class TestWriteJson:
    def test_writes_json(self, tmp_path):
        import json
        from workflow.pipeline import _write_json
        p = tmp_path / "data.json"
        _write_json(p, {"key": "value"})
        assert json.loads(p.read_text(encoding="utf-8")) == {"key": "value"}


class TestHasTestMainFile:
    def test_with_main(self, tmp_path):
        from workflow.pipeline import _has_test_main_file
        f = tmp_path / "test.c"
        f.write_text("int main(void) { return 0; }", encoding="utf-8")
        assert _has_test_main_file(f) is True

    def test_without_main(self, tmp_path):
        from workflow.pipeline import _has_test_main_file
        f = tmp_path / "lib.c"
        f.write_text("void foo(void) {}", encoding="utf-8")
        assert _has_test_main_file(f) is False

    def test_nonexistent(self, tmp_path):
        from workflow.pipeline import _has_test_main_file
        assert _has_test_main_file(tmp_path / "missing.c") is False
