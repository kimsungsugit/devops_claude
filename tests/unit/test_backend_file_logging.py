"""백엔드 파일 로그 — 죽고 나서 볼 것이 있는가 (2026-08-05).

## 왜 생겼나

``scripts/start.bat:37`` 이 uvicorn 을 **리다이렉션 없이** 띄운다. 로그가 콘솔
창에만 남으므로 창이 닫히거나 프로세스가 죽으면 증거가 0 이다. 2026-08-04
"클라우디움 먹통" 진단에서 원인(백엔드 미기동)을 특정하는 데 네 번의 조사가
필요했던 이유가 이것이다 — 사후에 볼 파일이 없었다.

## 이 파일이 고정하는 계약

1. 파일 핸들러가 실제로 붙고 **회전 상한**이 있다(디스크 무한 증가 금지)
2. ``uvicorn.error`` 에도 붙는다 — 기동 실패·미포착 예외 traceback 이 그쪽으로
   가므로, ``devops_api`` 만 붙이면 **정작 크래시가 파일에 안 남는다**
3. ``uvicorn.access`` 에는 **안 붙는다** — 요청마다 한 줄이라 회전이 너무 빨라
   크래시 직전 구간이 밀려난다(로그가 있는데 쓸모없어지는 형태)
4. 파일을 못 열면 **조용히 넘어가지 않고 사유를 보고**한다. 빈 로그를 "문제 없음"
   으로 읽는 것이 이 저장소가 반복해 겪은 fake-green 이다
5. 콘솔과 달리 **날짜를 포함**한다 — 사후 분석에서 시:분:초만으로는 어느 날인지 모른다
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

pytest.importorskip("backend.main")

import backend.main as bmain  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_handlers():
    """전역 로거를 건드리므로 **원래 핸들러 목록을 그대로 복원**한다.

    ⚠ 특정 값으로 고정하지 말 것 — 전역 싱글톤을 teardown 에서 고정했다가 단독
      실행이 무더기로 깨진 전례가 있다(CLAUDE.md 격리 규약).
    """
    names = ("devops_api", "uvicorn.error", "uvicorn.access")
    saved = {n: list(logging.getLogger(n).handlers) for n in names}
    yield
    for n, hs in saved.items():
        lg = logging.getLogger(n)
        for h in list(lg.handlers):
            if h not in hs:
                lg.removeHandler(h)
                try:
                    h.close()
                except (OSError, ValueError):
                    # 이미 닫힌 핸들러 / 파일 잠김. 정리 실패가 테스트 결과를
                    # 바꾸면 안 되므로 넘어가되, 예외 종류는 좁혀 둔다.
                    pass
        for h in hs:
            if h not in lg.handlers:
                lg.addHandler(h)


def _file_handlers(name: str) -> list[RotatingFileHandler]:
    return [h for h in logging.getLogger(name).handlers
            if isinstance(h, RotatingFileHandler)]


def test_attaches_rotating_file_handler(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVOPS_LOG_DIR", str(tmp_path / "logs"))
    path = bmain._attach_file_log()

    assert path, "파일 로그 경로를 돌려주지 않았다"
    hs = _file_handlers("devops_api")
    assert hs, "devops_api 에 파일 핸들러가 안 붙었다"
    h = hs[-1]
    assert h.maxBytes > 0, "회전 상한이 없다 — 디스크가 무한히 찬다"
    assert h.backupCount > 0, "백업 개수가 0 이면 회전 시 이전 내용이 통째로 사라진다"

    logging.getLogger("devops_api").error("포렌식 테스트 라인 — 한글")
    h.flush()
    text = Path(path).read_text(encoding="utf-8")
    assert "포렌식 테스트 라인 — 한글" in text, "한글이 파일에 안 남는다(인코딩)"


def test_uvicorn_error_is_captured_but_access_is_not(tmp_path, monkeypatch):
    """크래시 traceback 은 잡고, 요청 로그는 안 잡는다."""
    monkeypatch.setenv("DEVOPS_LOG_DIR", str(tmp_path / "logs"))
    before_access = len(_file_handlers("uvicorn.access"))
    path = bmain._attach_file_log()

    assert _file_handlers("uvicorn.error"), (
        "uvicorn.error 에 안 붙었다 — 기동 실패·미포착 예외가 파일에 안 남는다"
    )
    assert len(_file_handlers("uvicorn.access")) == before_access, (
        "uvicorn.access 에 붙였다 — 요청마다 한 줄이라 회전이 너무 빨라져 "
        "크래시 직전 구간이 밀려난다"
    )

    logging.getLogger("uvicorn.error").error("startup failed: boom")
    for h in _file_handlers("uvicorn.error"):
        h.flush()
    assert "startup failed: boom" in Path(path).read_text(encoding="utf-8")


def test_log_line_carries_the_date(tmp_path, monkeypatch):
    """콘솔 포맷은 %H:%M:%S 뿐이다 — 파일은 날짜가 있어야 사후 분석이 된다."""
    monkeypatch.setenv("DEVOPS_LOG_DIR", str(tmp_path / "logs"))
    path = bmain._attach_file_log()
    logging.getLogger("devops_api").info("datestamp probe")
    for h in _file_handlers("devops_api"):
        h.flush()
    line = next(ln for ln in Path(path).read_text(encoding="utf-8").splitlines()
                if "datestamp probe" in ln)
    import re
    assert re.search(r"\d{4}-\d{2}-\d{2}", line), f"날짜가 없다: {line}"


def test_unopenable_path_is_reported_not_silent(tmp_path, monkeypatch, capsys):
    """열 수 없으면 **빈 로그가 아니라 사유**를 남긴다."""
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("DEVOPS_LOG_DIR", str(blocker / "logs"))

    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    cap = _Capture()
    logging.getLogger("devops_api").addHandler(cap)
    path = bmain._attach_file_log()

    assert path == "", "실패했는데 경로를 돌려줬다"
    assert any("파일 로그를 열지 못했다" in m for m in records), (
        f"실패를 로그로 보고하지 않았다: {records}"
    )
    assert "파일 로그를 열지 못했다" in capsys.readouterr().err, (
        "stderr 로도 알리지 않았다 — 이 시점엔 파일 로그가 없어 콘솔이 유일한 통로다"
    )


def test_repeat_attach_does_not_duplicate(tmp_path, monkeypatch):
    """uvicorn --reload 는 모듈을 다시 import 한다 — 핸들러가 겹치면 안 된다."""
    monkeypatch.setenv("DEVOPS_LOG_DIR", str(tmp_path / "logs"))
    first = bmain._attach_file_log()
    n1 = len(_file_handlers("devops_api"))
    second = bmain._attach_file_log()
    n2 = len(_file_handlers("devops_api"))

    assert first == second
    assert n1 == n2, f"재호출로 핸들러가 늘었다({n1} → {n2}) — 같은 줄이 여러 번 쓰인다"


def test_bad_env_values_fall_back_instead_of_crashing(tmp_path, monkeypatch):
    """상한 env 가 정수가 아니어도 기동을 막지 않는다(로그는 부가 기능이다)."""
    monkeypatch.setenv("DEVOPS_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DEVOPS_LOG_MAX_MB", "twenty")
    path = bmain._attach_file_log()
    assert path, "잘못된 env 값 때문에 파일 로그가 통째로 사라졌다"
    assert _file_handlers("devops_api")[-1].maxBytes > 0
