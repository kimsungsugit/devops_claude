"""테스트는 사용자의 `logs/backend.log` 에 쓰지 않는다 (R47 N21, 2026-09-10).

## 왜 생겼나

`backend.main` 은 import 시점에 `_attach_file_log()` 로 `RotatingFileHandler` 를 붙인다.
`DEVOPS_LOG_DIR` 이 비어 있으면 그 경로는 저장소 `logs/backend.log` 다. 테스트 모듈 수십 개가
모듈 상단에서 `backend.main` 을 import 하므로 `-n auto` 워커 18개가 전부 실 로그를 연 채 돌았다.

실측(2026-09-10): `logs/backend.log` 116,400줄 중 pytest 임시경로가 찍힌 줄만 2,838줄. 회전 파일이
`.1`·`.5` 만 남고 `.2~.4` 가 없다 — 여러 프로세스가 같은 파일을 동시에 회전한 흔적이다.
R36(`quality.sqlite`)·R38(`reports/` 5곳)과 같은 계열이다: **게이트가 자기가 재는 데이터를 만든다.**

## 이 파일이 고정하는 계약

1. pytest 아래에서 `DEVOPS_LOG_DIR` 은 `.codex_tmp` 밑 pid 별 디렉터리다(`tests/conftest.py`).
2. `backend.main` 이 실제로 붙인 핸들러는 **그 디렉터리**를 가리키고, 저장소 `logs/` 를
   가리키는 파일 핸들러는 어느 로거에도 없다.
3. 관측량: `devops_api` 로 한 줄을 쓰면 격리 파일에 남고 저장소 `logs/backend.log` 에는 없다.

뮤테이션(2026-09-10): conftest 의 `os.environ["DEVOPS_LOG_DIR"] = …` 한 줄을 지우면
`test_file_handlers_point_at_isolated_dir` 와 `test_warning_lands_in_isolated_file_not_prod` 가 죽는다.
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

import pytest

pytest.importorskip("backend.main")

import backend.main as bmain  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROD_LOG_DIR = _REPO_ROOT / "logs"


def _under(path: str | Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _all_file_handlers() -> list[logging.FileHandler]:
    out: list[logging.FileHandler] = []
    loggers = [logging.getLogger()] + [
        lg for lg in logging.Logger.manager.loggerDict.values() if isinstance(lg, logging.Logger)
    ]
    for lg in loggers:
        for h in lg.handlers:
            if isinstance(h, logging.FileHandler):
                out.append(h)
    return out


def test_env_points_into_codex_tmp_per_process() -> None:
    val = os.environ.get("DEVOPS_LOG_DIR", "")
    assert val, "conftest 가 DEVOPS_LOG_DIR 을 넣지 않았다 — 테스트가 실 logs/ 에 쓴다"
    assert _under(val, _REPO_ROOT / ".codex_tmp"), val
    assert Path(val).name == f"logs-test-{os.getpid()}", (
        "pid 별 디렉터리가 아니다 — xdist 워커끼리 같은 파일을 회전하게 된다")
    assert not _under(val, _PROD_LOG_DIR)


def test_file_handlers_point_at_isolated_dir() -> None:
    """backend.main 이 import 시점에 붙인 핸들러가 격리 디렉터리를 가리킨다."""
    isolated = Path(os.environ["DEVOPS_LOG_DIR"])
    # 실제로 붙었는가(붙이지 못했으면 빈 문자열을 돌려주고 stderr 로 사유를 낸다).
    assert bmain._LOG_FILE_PATH, "파일 로그가 붙지 않았다 — 격리 여부 이전에 계약 1 이 깨졌다"
    assert _under(bmain._LOG_FILE_PATH, isolated), bmain._LOG_FILE_PATH

    prod_hits = [h.baseFilename for h in _all_file_handlers() if _under(h.baseFilename, _PROD_LOG_DIR)]
    assert not prod_hits, f"저장소 logs/ 를 가리키는 핸들러가 남아 있다: {prod_hits}"


def test_warning_lands_in_isolated_file_not_prod() -> None:
    """관측량으로 확인한다 — 한 줄을 쓰면 격리 파일에만 남는다."""
    marker = f"r47-n21-probe-{uuid.uuid4().hex}"
    logging.getLogger("devops_api").warning(marker)
    for h in _all_file_handlers():
        h.flush()

    isolated_file = Path(bmain._LOG_FILE_PATH)
    assert isolated_file.exists(), isolated_file
    assert marker in isolated_file.read_text(encoding="utf-8", errors="replace")

    prod_file = _PROD_LOG_DIR / "backend.log"
    if prod_file.exists():
        # 실 로그는 수십 MB 일 수 있고 라이브 백엔드가 동시에 쓴다 — 꼬리만 읽는다.
        with open(prod_file, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 2 * 1024 * 1024))
            tail = fh.read().decode("utf-8", errors="replace")
        assert marker not in tail, "테스트 로그 한 줄이 사용자의 logs/backend.log 에 찍혔다"
