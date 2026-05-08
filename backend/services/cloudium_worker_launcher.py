"""Cloudium worker(excel_rename_gui_v2.exe) 자동 실행 헬퍼.

호출 시점:
1. backend startup이 cloudium 모드 — main.py _lifespan
2. cloudium 모드로 전환 — health.py set_file_mode

이미 실행 중이면 skip (TCP ping 8765). exe 없으면 warning만.
환경변수 CLOUDIUM_AUTO_START_WORKER=0으로 비활성 가능.

권한 모델 주의 (project_cloudium_model.md):
backend python.exe는 클라우디움 권한 없음. spawn한 worker exe가 GUI subsystem +
이름 패턴(excel_rename_gui_v2.exe)으로 자체 권한 받는지는 사용자 PC 검증 필요.
권한 못 받으면 사용자가 직접 더블클릭 실행해야 함 (경험상 spawn해도 OK일 가능성).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

_log = logging.getLogger("devops_api.worker_launcher")
_REPO_ROOT = Path(__file__).resolve().parents[2]


def ensure_cloudium_worker_running() -> dict:
    """cloudium worker가 떠 있지 않으면 자동 spawn.

    Returns: {"action": "spawned" | "already_running" | "disabled" |
                       "exe_missing" | "failed", ...}
    """
    if os.environ.get("CLOUDIUM_AUTO_START_WORKER", "1") != "1":
        return {"action": "disabled"}

    from backend.services.file_resolver import is_gate_running
    if is_gate_running():
        return {"action": "already_running"}

    worker_exe = _REPO_ROOT / "dist" / "excel_rename_gui_v2.exe"
    if not worker_exe.exists():
        _log.warning("Cloudium worker exe not found at %s", worker_exe)
        return {"action": "exe_missing", "path": str(worker_exe)}

    try:
        flags = 0
        if sys.platform == "win32":
            flags = (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        subprocess.Popen(
            [str(worker_exe)],
            creationflags=flags,
            close_fds=True,
        )
        _log.info("Cloudium worker spawned: %s", worker_exe)
        return {"action": "spawned", "path": str(worker_exe)}
    except Exception as e:
        _log.warning("Cloudium worker auto-start failed: %s", e)
        return {"action": "failed", "error": str(e)}
