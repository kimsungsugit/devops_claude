#!/usr/bin/env python3
"""PreToolUse(Bash) — 백엔드 API 를 부르려는데 서버가 안 떠 있으면 미리 알린다.

## 왜 .sh 에서 옮겨왔나 (2026-08-03)

앞선 `validate-api-call.sh` 는 stdin JSON 을 `jq` 로 팠는데 **이 환경엔 jq 가 없다**.
jq 가 없으면 `COMMAND` 가 빈 문자열이 되고 `grep -q` 가 매치에 실패해 **아무 일도
없이 exit 0** 한다. 즉 활성화된 채로 한 번도 동작한 적이 없다.
같은 경위는 `check_secrets.py` docstring 참조.

stdlib 만 쓴다(`json`/`re`/`urllib`). 외부 도구 부재로 다시 죽지 않는다.

## 계약

- **훅은 명령을 막지 않는다** — 항상 exit 0. 경고만 붙인다.
- 헬스체크는 2초 타임아웃. 훅이 Bash 호출마다 지연을 만들면 안 된다.
- 입력 이상은 침묵하지 않고 보고한다.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request

# CLAUDE.md 기준 백엔드 포트는 9000 (구 저장소의 8000 아님).
_PORT = 9000
_HEALTH_URL = f"http://127.0.0.1:{_PORT}/api/health"
_TARGET_RE = re.compile(rf"curl[^\n]*(?:127\.0\.0\.1|localhost):{_PORT}", re.I)
_TIMEOUT = 2.0


def _emit(msg: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": msg,
        }
    }, ensure_ascii=False))


def _backend_alive() -> bool:
    try:
        with urllib.request.urlopen(_HEALTH_URL, timeout=_TIMEOUT) as resp:
            return 200 <= int(getattr(resp, "status", 0) or 0) < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        return
    try:
        payload = json.loads(raw)
    except Exception as exc:
        _emit(f"api-precheck: DISABLED — stdin 이 JSON 이 아니다 ({type(exc).__name__}). 확인하지 **않았다**.")
        return
    if not isinstance(payload, dict):
        return

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    command = str(tool_input.get("command") or "")
    if not command or not _TARGET_RE.search(command):
        return

    if not _backend_alive():
        _emit(
            f"api-precheck: 백엔드(:{_PORT})가 응답하지 않는다. 먼저 기동할 것 — "
            f"`backend/.venv/Scripts/python.exe -m uvicorn main:app --reload --port {_PORT}` "
            f"(canonical 은 scripts/start.bat). 맨 `uvicorn` 은 bcrypt 부재로 죽는다."
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # 훅이 명령을 막아서는 안 된다 — 단, 침묵하지도 않는다.
        _emit(f"api-precheck: 검사기 자체가 실패했다 ({type(exc).__name__}: {exc}). 확인하지 **않았다**.")
