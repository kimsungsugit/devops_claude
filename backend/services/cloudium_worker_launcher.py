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


# 충돌 확정 전 재확인 ping 의 타임아웃. `file_resolver._PING_TIMEOUT`(0.5s)은 게이트
# **live-ness** 검사용이라 짧다. 여기선 반대로 **틀린 단정을 피하는 게** 목적이라 넉넉히
# 준다 — 1회만 더 쓰는 비용이고, 이 경로는 이미 실패가 확정된 뒤라 지연이 문제되지 않는다.
_CONFIRM_PING_TIMEOUT = 2.0


def _worker_version_report() -> dict:
    """도는 워커가 **소스와 같은 판인지** 본다. 다르면 exe 재빌드가 필요하다는 뜻.

    왜 필요한가 — `dist/excel_rename_gui_v2.exe` 는 gitignore 대상이라 소스를 고쳐도
    **배포본은 그대로다.** 그 어긋남은 아무 신호도 안 낸다: 게이트는 초록이고 read 도
    되는데 고친 동작만 빠져 있다. 2026-08-19 에 `allow_reuse_address` 를 껐는데 도는
    exe 는 옛 판이라 포트 가로채기가 여전히 가능했다 — 그런 걸 눈으로 잡을 수는 없다.

    기대값은 **소스 상수를 직접 읽는다**(`cloudium_worker.worker.WORKER_VERSION`).
    두 벌로 적으면 그것부터 갈라진다. 워커 모듈은 최상단에서 tkinter 를 import 하지
    않으므로(GUI 는 `_run_gui` 안에서 lazy) 백엔드가 import 해도 안전하다.

    조회 실패는 **모른다고 말한다** — 낡음/최신 어느 쪽으로도 단정하지 않는다.
    """
    import json
    import socket

    from backend.services.file_resolver import _worker_endpoint

    try:
        from cloudium_worker.worker import WORKER_VERSION as expected
    except Exception as exc:  # noqa: BLE001 — 소스 부재/임포트 실패도 '모름'이다
        return {"worker_version": None, "version_check": f"unavailable({type(exc).__name__})"}

    host, port = _worker_endpoint()
    try:
        with socket.create_connection((host, port), timeout=2.0) as s:
            s.sendall(json.dumps({"id": "v", "op": "version", "args": {}}).encode() + b"\n")
            s.settimeout(2.0)
            buf = b""
            while b"\n" not in buf and len(buf) < 4096:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        running = json.loads(buf.split(b"\n", 1)[0].decode("utf-8")).get("result")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"worker_version": None,
                "version_check": f"unavailable({type(exc).__name__})"}

    if running == expected:
        return {"worker_version": running, "version_check": "match"}
    # ⚠ 방향을 단정하지 않는다. 흔한 건 "exe 가 낡음" 이지만 **소스를 되돌린 경우**
    #   (옛 커밋 체크아웃 등)엔 exe 가 더 새 판이다. "낡았다" 고 적으면 그 경우엔
    #   거짓말이 된다 — 두 값을 다 보여주고 판단은 사람에게 넘긴다.
    #   조치(재빌드)는 어느 방향이든 같으므로 안내는 유지한다.
    _log.warning(
        "Cloudium worker 판이 소스와 **어긋난다** — 도는 exe %s · 소스 %s. "
        "`cloudium_worker/worker.py` 를 고쳐도 exe 를 다시 빌드하지 않으면 반영되지 "
        "않는다(반대로 소스를 되돌렸다면 exe 쪽이 새 판이다). 재빌드: "
        "pyinstaller --onefile --name excel_rename_gui_v2 --noconsole "
        "cloudium_worker\\worker.py", running, expected,
    )
    return {"worker_version": running, "expected_worker_version": expected,
            "version_check": "stale_exe"}


def _port_held_by_other() -> "tuple[bool, int]":
    """워커 포트를 **다른 프로세스**가 쥐고 있나. 반환 ``(그렇다, 포트)``.

    호출부는 ping 이 이미 실패한 뒤에만 쓴다. 그 상태에서 TCP 연결이 **되면**
    누군가 듣고 있는데 우리 워커가 아니라는 뜻이다.

    왜 굳이 가르나 — 이 둘은 **처방이 정반대**인데 증상이 같다:

      · 아직 안 떴다        → 기다리면 된다(타임아웃을 늘리는 게 맞다)
      · 남이 포트를 쥐었다  → **아무리 기다려도 안 된다**. 포트를 옮겨야 한다

    2026-08-19 실사고: 무관한 앱이 8765 를 점유해 워커가 바인딩에서 죽었는데,
    `worker.py` 의 TCP 서버가 `allow_reuse_address=True`(SO_REUSEADDR) 라 Windows 가
    익숙한 10048("포트 사용 중") 대신 **10013("액세스 권한")** 을 돌려준다. 그래서
    로그만 보면 권한 문제로 읽히고, 여기가 "타임아웃을 늘리라" 고 안내하면 사용자는
    영원히 낫지 않는 처방을 따르게 된다.
    """
    import socket

    from backend.services.file_resolver import _ping_worker, _worker_endpoint

    host, port = _worker_endpoint()
    try:
        with socket.create_connection((host, port), timeout=0.5):
            pass
    except OSError:
        return False, port          # 아무도 안 듣는다 = 충돌 아님(그냥 안 뜬 것)

    # ⚠ **연결만으로 단정하지 않는다.** 우리 워커가 이미 바인딩했는데 ping 응답만
    #   늦은 경우(GUI 기동 중·부하)에도 연결은 성공한다. 그걸 충돌로 부르면 사용자를
    #   **멀쩡한 포트를 옮기게** 만든다 — 위 표의 반대 방향 오진단이다.
    #   그래서 넉넉한 타임아웃으로 한 번 더 물어본다. pong 이 오면 우리 것이다.
    #   (판정 불가 쪽으로 기울인다: 충돌을 놓치면 로그가 한 줄 덜 친절할 뿐이지만,
    #    없는 충돌을 외치면 사람이 엉뚱한 조치를 한다.)
    if _ping_worker(host, port, timeout=_CONFIRM_PING_TIMEOUT):
        return False, port
    return True, port


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
            # ⚠ 여기가 **평상시 경로**다(워커가 이미 떠 있음). spawn 쪽에만 버전 점검을
            #   달면 재기동해도 낡은 exe 를 영영 못 본다 — 정작 매번 지나는 길이 여기다.
            return {"action": "already_running", **_worker_version_report()}

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
            result = {"action": "spawned", "path": str(worker_exe),
                      "ready": ready, "waited_s": round(waited, 1)}
            if ready:
                result.update(_worker_version_report())
            if not ready:
                # ⚠ '안 떴다' 와 '남이 포트를 쥐었다' 는 처방이 정반대다. 안 가르면
                #   포트 충돌인데 "타임아웃을 늘리라" 고 안내하게 되고, 그 처방은
                #   **영원히 듣지 않는다**(2026-08-19 실사고 — 위 `_port_held_by_other`).
                taken, port = _port_held_by_other()
                if taken:
                    result["port_conflict"] = True
                    result["port"] = port
                    _log.warning(
                        "Cloudium worker 기동 실패 — 포트 %d 를 **다른 프로세스가 점유** 중이다. "
                        "타임아웃 문제가 아니므로 늘려도 안 된다. worker 는 SO_REUSEADDR 를 쓰므로 "
                        "바인딩이 WinError 10013('액세스 권한')으로 죽어 권한 문제처럼 보인다. "
                        "점유자 확인: netstat -ano | findstr \":%d \" · 해결: 그 프로세스를 내리거나 "
                        ".env 의 CLOUDIUM_WORKER_PORT 를 빈 포트로 바꾸고 백엔드 재기동", port, port,
                    )
                else:
                    _log.warning(
                        "Cloudium worker spawned but NOT ready after %.1fs — 기동 직후 문서 요청이 "
                        "403(접근 거부)로 보일 수 있다. worker 를 직접 실행하거나 "
                        "CLOUDIUM_WORKER_READY_TIMEOUT 을 늘릴 것: %s", waited, worker_exe,
                    )
            return result
        except (OSError, subprocess.SubprocessError) as e:
            _log.warning("Cloudium worker auto-start failed: %s", e)
            return {"action": "failed", "error": str(e)}
