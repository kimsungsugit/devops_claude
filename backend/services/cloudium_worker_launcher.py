"""Cloudium worker(excel_rename_gui_v2.exe) 자동 실행 헬퍼.

호출 시점:
1. backend startup이 cloudium 모드 — main.py _lifespan
2. cloudium 모드로 전환 — health.py set_file_mode

동기화: module-level Lock으로 동시 spawn race 방지 (W1).
TTL 캐시 우회: is_gate_running(force=True)로 stale read 방지 (W2).
fd 분리: stdin/stdout/stderr=DEVNULL로 worker fully detached (W3).

권한 모델 주의 (project_cloudium_model.md):
backend python.exe는 클라우디움 권한 없음. spawn한 worker exe가 GUI subsystem +
이름 패턴(excel_rename_gui_v2.exe)으로 자체 권한 받는지는 사용자 PC 검증 필요.
권한 못 받으면 사용자가 직접 더블클릭 실행해야 함.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

_log = logging.getLogger("devops_api.worker_launcher")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPAWN_LOCK = threading.Lock()


def _is_disabled() -> bool:
    """env 토글 — '0'/'false'/'no'/'off' 모두 비활성으로 인식 (W5)."""
    val = os.environ.get("CLOUDIUM_AUTO_START_WORKER", "1").strip().lower()
    return val in {"0", "false", "no", "off"}


def ensure_cloudium_worker_running() -> dict:
    """cloudium worker가 떠 있지 않으면 자동 spawn.

    Returns: {"action": "spawned" | "already_running" | "disabled" |
                       "exe_missing" | "failed", ...}
    """
    if _is_disabled():
        return {"action": "disabled"}

    from backend.services.file_resolver import is_gate_running

    # W1: 동시 호출 race 방지 — Lock 안에서 ping + spawn 일관 처리.
    # W2: force=True로 TTL 캐시 우회 — 가장 최근 상태 확보.
    with _SPAWN_LOCK:
        if is_gate_running(force=True):
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
            # W3: 명시 stdio 분리 — uvicorn pipe 상속 차단
            subprocess.Popen(
                [str(worker_exe)],
                creationflags=flags,
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _log.info("Cloudium worker spawned: %s", worker_exe)
            return {"action": "spawned", "path": str(worker_exe)}
        except (OSError, subprocess.SubprocessError) as e:
            _log.warning("Cloudium worker auto-start failed: %s", e)
            return {"action": "failed", "error": str(e)}
