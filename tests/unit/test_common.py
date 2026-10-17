"""Unit tests for workflow.common helper functions."""
from __future__ import annotations

import pytest

from workflow.common import (
    Issue,
    PipelineStopRequested,
    check_stop,
    create_backup,
    normalize_whitespace,
    read_excerpt,
    restore_from_backup,
    standardize_result,
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

    # ── 무엇을 삼키고 무엇을 안 삼키는가 (2026-09-02) ────────────────────────
    #
    # 이 함수의 `""` 는 소비처 5곳(`workflow/ai.py`·`workflow/pipeline.py`)에서 **AI 입력으로
    # 그대로** 간다 — "못 읽었다"가 "비어 있다"로 전달된다. 그래서 삼키는 범위가 계약이다.
    #
    # 예전 판은 맨 `except:` 였다가(Ctrl+C 까지 삼킴) `except Exception` 을 거쳐 지금
    # `except OSError` 다. 넓힐 근거로 쓰였던 "OSError 아닌 실패가 실제로 난다"는
    # 2026-09-02 계측(전체 스위트 2회, 기록된 예외 = FileNotFoundError 1건)으로 반증됐다.
    # 아래 두 테스트가 그 계약을 **양방향**으로 못박는다 — 넓히면 두 번째가, 좁히다 못해
    # 지워버리면 첫 번째가 깨진다.

    def test_swallows_os_errors(self, tmp_path):
        """읽기 실패(OSError 계열)는 삼키고 `""` — 이게 소비처 5곳이 기대하는 계약."""
        d = tmp_path / "dir_not_file"
        d.mkdir()
        assert read_excerpt(d) == ""              # IsADirectoryError/PermissionError
        assert read_excerpt(tmp_path / "x.txt") == ""   # FileNotFoundError

    def test_does_not_swallow_non_os_errors(self):
        """OSError 아닌 실패는 **통과시킨다** — 정체 모를 예외를 `""` 로 위장하지 않는다."""
        class Boom:
            def read_text(self, **_kw):
                raise ValueError("I/O operation on closed file")

        with pytest.raises(ValueError):
            read_excerpt(Boom())

    def test_malformed_path_is_not_disguised_as_empty(self):
        """NUL 경로는 `read_text` 가 `ValueError` 를 낸다 — **잡지 않는다**(실 Path 로 실증).

        이건 읽기 실패가 아니라 **경로가 망가진 것**이다. `""` 로 바꾸면 소비처 5곳이
        AI 에게 "코드가 비어 있다"는 **틀린 사실**을 전달한다. 안 나는 경우를 위해
        catch 를 넓히는 건 R19 에서 틀렸다고 확인한 그 행동이라, 여기서는 넓히지 않는다.
        """
        import pathlib

        with pytest.raises(ValueError):
            read_excerpt(pathlib.Path("bad\x00name.c"))

    def test_records_what_it_swallowed(self, tmp_path, monkeypatch):
        """삼킨 것은 **관측 가능**해야 한다 — 침묵을 없앨 수 없으면 보이게라도 둔다."""
        dest = tmp_path / "trace.log"
        monkeypatch.setenv("ARIA_READ_EXCERPT_TRACE", str(dest))
        assert read_excerpt(tmp_path / "gone.txt") == ""

        written = list(tmp_path.glob("trace.log.*"))
        assert written, "삼킨 예외가 아무 데도 안 남았다"
        body = written[0].read_text(encoding="utf-8")
        assert "FileNotFoundError" in body          # 무엇을
        assert "gone.txt" in body                   # 어디서
        assert "read_excerpt" in body               # 어느 호출 경로로

    def test_recorder_is_off_by_default(self, tmp_path, monkeypatch):
        """env 미설정이면 아무것도 안 쓴다 — 운영 경로 부담 0."""
        monkeypatch.delenv("ARIA_READ_EXCERPT_TRACE", raising=False)
        assert read_excerpt(tmp_path / "gone.txt") == ""
        assert not list(tmp_path.iterdir()), "env 미설정인데 파일을 만들었다"


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
