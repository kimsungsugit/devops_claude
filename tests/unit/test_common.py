"""Unit tests for workflow.common helper functions."""
from __future__ import annotations

from pathlib import Path

import pytest

from workflow.common import (
    PipelineStopRequested,
    check_stop,
    Issue,
    normalize_whitespace,
    standardize_result,
    read_excerpt,
    create_backup,
    restore_from_backup,
)


class TestCheckStop:
    def test_no_args_does_nothing(self):
        check_stop()

    def test_callback_raises(self):
        def raise_stop():
            raise PipelineStopRequested("user stopped")
        with pytest.raises(PipelineStopRequested):
            check_stop(stop_check=raise_stop)

    def test_stop_flag_file(self, tmp_path):
        flag = tmp_path / "STOP"
        flag.write_text("stop", encoding="utf-8")
        with pytest.raises(PipelineStopRequested):
            check_stop(stop_flag=flag)

    def test_stop_flag_missing(self, tmp_path):
        flag = tmp_path / "STOP"
        check_stop(stop_flag=flag)  # should not raise


class TestIssue:
    def test_dataclass_fields(self):
        issue = Issue(file="main.c", line=10, severity="error", message="bug", id="E001")
        assert issue.file == "main.c"
        assert issue.tool == "cppcheck"
        assert issue.cwe is None


class TestNormalizeWhitespace:
    def test_multiple_spaces(self):
        assert normalize_whitespace("  a   b  ") == "a b"

    def test_tabs_newlines(self):
        assert normalize_whitespace("a\t\nb") == "a b"


class TestStandardizeResult:
    def test_ok_result(self):
        r = standardize_result(True, "success")
        assert r["ok"] is True
        assert r["reason"] == "success"
        assert "timestamp" in r

    def test_fail_result_with_data(self):
        r = standardize_result(False, "fail", {"detail": 1})
        assert r["ok"] is False
        assert r["data"] == {"detail": 1}

    def test_none_data_becomes_empty(self):
        r = standardize_result(True)
        assert r["data"] == {}


class TestReadExcerpt:
    def test_reads_file(self, tmp_path):
        f = tmp_path / "code.c"
        lines = ["line %d" % i for i in range(200)]
        f.write_text("\n".join(lines), encoding="utf-8")
        result = read_excerpt(f, max_lines=10)
        assert result.count("\n") == 9  # 10 lines, 9 newlines

    def test_nonexistent(self, tmp_path):
        assert read_excerpt(tmp_path / "no.txt") == ""


class TestBackupRestore:
    def test_create_and_restore(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("original", encoding="utf-8")
        bak = create_backup(f)
        assert bak is not None
        assert bak.exists()

        f.write_text("modified", encoding="utf-8")
        assert restore_from_backup(f) is True
        assert f.read_text(encoding="utf-8") == "original"

    def test_backup_not_overwritten(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("v1", encoding="utf-8")
        create_backup(f)

        f.write_text("v2", encoding="utf-8")
        create_backup(f)  # should not overwrite

        restore_from_backup(f)
        assert f.read_text(encoding="utf-8") == "v1"

    def test_restore_no_backup(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("data", encoding="utf-8")
        assert restore_from_backup(f) is False
