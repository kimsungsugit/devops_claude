# tests/unit/test_static.py
"""Unit tests for workflow.static parsing functions."""
from __future__ import annotations

from pathlib import Path

import pytest

from workflow.common import Issue
from workflow.static import parse_clang_tidy_output, _parse_semgrep_results


class TestParseClangTidyOutput:
    def test_basic_warning(self):
        # Use Unix-style paths (regex expects no colon in path prefix)
        output = "/proj/src/main.c:10:5: warning: some issue [bugprone-check]"
        issues = parse_clang_tidy_output(output, Path("/proj"))
        assert len(issues) == 1
        assert issues[0].line == 10
        assert issues[0].severity == "warning"
        assert issues[0].id == "bugprone-check"
        assert issues[0].tool == "clang-tidy"

    def test_error_severity(self):
        output = "/proj/lib.c:5:1: error: use of undeclared [misc-check]"
        issues = parse_clang_tidy_output(output, Path("/proj"))
        assert len(issues) == 1
        assert issues[0].severity == "error"

    def test_empty_output(self):
        assert parse_clang_tidy_output("", Path(".")) == []

    def test_non_matching_lines(self):
        output = "note: compiling...\nBuilding CXX object..."
        assert parse_clang_tidy_output(output, Path(".")) == []

    def test_multiple_issues(self):
        output = (
            "/proj/a.c:1:1: warning: msg1 [check1]\n"
            "/proj/b.c:2:1: error: msg2 [check2]\n"
        )
        issues = parse_clang_tidy_output(output, Path("/proj"))
        assert len(issues) == 2


class TestParseSemgrepResults:
    def test_basic(self):
        payload = {
            "results": [
                {
                    "path": "/proj/src/main.c",
                    "start": {"line": 42},
                    "extra": {"message": "potential bug", "severity": "warning"},
                    "check_id": "rule-001",
                }
            ]
        }
        issues = _parse_semgrep_results(payload, Path("/proj"))
        assert len(issues) == 1
        assert issues[0].line == 42
        assert issues[0].tool == "semgrep"
        assert issues[0].id == "rule-001"

    def test_empty_results(self):
        assert _parse_semgrep_results({"results": []}, Path("/proj")) == []

    def test_no_results_key(self):
        assert _parse_semgrep_results({}, Path("/proj")) == []

    def test_non_dict_items_skipped(self):
        payload = {"results": ["not a dict", None, 42]}
        assert _parse_semgrep_results(payload, Path("/proj")) == []

    def test_relative_path(self):
        # Use Unix-style paths (relative_to only works when both are absolute on same OS)
        payload = {
            "results": [
                {
                    "path": "/proj/lib/util.c",
                    "start": {"line": 1},
                    "extra": {"message": "x", "severity": "info"},
                    "check_id": "r1",
                }
            ]
        }
        issues = _parse_semgrep_results(payload, Path("/proj"))
        assert "util.c" in issues[0].file

    def test_missing_extra(self):
        payload = {
            "results": [
                {
                    "path": "a.c",
                    "start": {"line": 1},
                    "message": "fallback msg",
                    "severity": "error",
                    "check_id": "r2",
                }
            ]
        }
        issues = _parse_semgrep_results(payload, Path("/proj"))
        assert len(issues) == 1
        assert issues[0].message == "fallback msg"
