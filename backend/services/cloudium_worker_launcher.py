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
import time
from pathlib import Path

_log = logging.getLogger("devops_api.worker_launcher")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPAWN_LOCK = threading.Lock()


def _is_disabled() -> bool:
    """env 토글 — '0'/'false'/'no'/'off' 모두 비활성으로 인식 (W5)."""
    val = os.environ.get("CLOUDIUM_AUTO_START_WORKER", "1").strip().lower()
    return val in {"0", "false", "no", "off"}


def _ready_budget_s() -> float:
    """spawn 후 worker 준비를 기다릴 상한(초). 0 이하면 대기 없음(옛 동작)."""
    try:
        return max(0.0, float(os.environ.get("CLOUDIUM_WORKER_READY_TIMEOUT", "8")))
    except ValueError:
        return 8.0


def _wait_ready(budget_s: float, *, poll_s: float = 0.25) -> tuple[bool, float]:
    """worker 가 ping 에 응답할 때까지 **상한 내에서** 기다린다. 반환 ``(준비됨, 대기초)``.

    ⚠ 이게 없으면 spawn 직후 바로 서비스가 열리고, worker TCP 서버가 뜨기 전에 도착한
    요청이 전부 **403 "접근 거부"** 가 된다. 실체는 '아직 준비 중'인데 사용자에겐 권한
    문제로 보인다 — 이 저장소가 반복해 고쳐온 "원인과 무관한 사유" 그 형태다.
    (실측 2026-08-07: 기동 직후 체인 8단계가 전부 403. 게이트 캐시 TTL 이 1초라
     나중엔 자가 회복되지만, 그 창에 걸린 요청은 그냥 실패한다.)
    """
    from backend.services.file_resolver import is_gate_running

    if budget_s <= 0:
        return is_gate_running(force=True), 0.0
    deadline = time.monotonic() + budget_s
    waited = 0.0
    while True:
        if is_gate_running(force=True):
            return True, waited
        if time.monotonic() >= deadline:
            return False, waited
        time.sleep(poll_s)
        waited += poll_s


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
            # spawn 직후 바로 반환하면 worker TCP 서버가 뜨기 전 요청이 403 이 된다.
            # 상한 내에서 준비를 기다리고, **못 기다렸으면 못 기다렸다고 말한다**
            # (ready=False 를 성공으로 위장하지 않는다 — 호출부가 로그로 볼 수 있게).
            ready, waited = _wait_ready(_ready_budget_s())
            if ready:
                _log.info("Cloudium worker spawned + ready in %.1fs: %s", waited, worker_exe)
            else:
                _log.warning(
                    "Cloudium worker spawned but NOT ready after %.1fs — 기동 직후 문서 요청이 "
                    "403(접근 거부)로 보일 수 있다. worker 를 직접 실행하거나 "
                    "CLOUDIUM_WORKER_READY_TIMEOUT 을 늘릴 것: %s", waited, worker_exe,
                )
            return {"action": "spawned", "path": str(worker_exe),
                    "ready": ready, "waited_s": round(waited, 1)}
        except (OSError, subprocess.SubprocessError) as e:
            _log.warning("Cloudium worker auto-start failed: %s", e)
            return {"action": "failed", "error": str(e)}
