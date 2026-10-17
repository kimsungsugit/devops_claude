#!/usr/bin/env python3
"""PostToolUse — 편집된 파일에 자격증명이 들어갔는지 검사한다.

## 왜 .sh 에서 옮겨왔나 (2026-08-03)

앞선 `check-secrets.sh` 는 stdin JSON 을 `jq` 로 팠는데 **이 환경엔 jq 가 없다**
(`command -v jq` → not found). jq 가 없으면 `$(echo "$INPUT" | jq -r …)` 가 빈
문자열이 되고 바로 다음 줄 `[ -z "$FILE_PATH" ] && exit 0` 에 걸려 **아무 경고도
없이 통과**한다. 즉 이 훅은 활성화(`enabledPlugins`)돼 매 Edit/Write 마다 발화하면서
**한 번도 검사한 적이 없다**. 도구 부재를 clean 으로 읽던 이 저장소의 fake-green
패턴 그대로다 — 프로젝트 Python 훅들이 도구 부재를 `DISABLED` 로 명시 보고하는 것과 대조.

stdlib 만 쓰므로(`json`/`re`/`os`) 외부 도구 부재로 다시 죽을 일이 없다.

## 계약

- **훅은 편집을 막지 않는다** — 항상 exit 0. 발견은 advisory 로만 보고.
- **값은 절대 출력하지 않는다.** 키 이름과 줄 번호만 남긴다 — 경고문이 그 자체로
  비밀값을 대화 기록에 복사하면 검사기가 유출 경로가 된다.
- **입력 이상은 침묵하지 않는다.** stdin 이 JSON 이 아니거나 모양이 다르면 그 사실을
  보고한다(빈 출력 = 깨끗함 으로 읽히면 안 된다).
"""
from __future__ import annotations

import json
import os
import re
import sys

# 앞선 .sh 의 패턴을 그대로 옮긴다(의도 보존). 값 뒤 8자 이상만 — 짧은 건 대개 placeholder.
_SECRET_RE = re.compile(
    r"(API_KEY|SECRET_KEY|SECRET|PASSWORD|PASSWD|TOKEN|PRIVATE_KEY|AWS_ACCESS_KEY"
    r"|AWS_SECRET|GOOGLE_API_KEY|JENKINS_TOKEN|DATABASE_URL|DSN|CONNECTION_STRING"
    r"|AUTH_SECRET)\s*=\s*['\"][^'\"]{8,}",
    re.I,
)

# 큰 파일은 훅 지연이 크고 자격증명이 있을 자리도 아니다.
_MAX_BYTES = 2 * 1024 * 1024
_MAX_REPORT = 5


def _emit(msg: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": msg,
        }
    }, ensure_ascii=False))


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        return  # 훅이 입력 없이 불린 경우 — 정상 종료(검사 대상 자체가 없음)
    try:
        payload = json.loads(raw)
    except Exception as exc:
        _emit(f"secret-scan: DISABLED — stdin 이 JSON 이 아니다 ({type(exc).__name__}). 검사하지 **않았다**.")
        return
    if not isinstance(payload, dict):
        _emit(f"secret-scan: DISABLED — payload 가 dict 가 아니다({type(payload).__name__}). 검사하지 **않았다**.")
        return

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    fp = str(tool_input.get("file_path") or "").strip()
    if not fp or not os.path.isfile(fp):
        return

    try:
        if os.path.getsize(fp) > _MAX_BYTES:
            return
        with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
    except OSError as exc:
        _emit(f"secret-scan: DISABLED — {os.path.basename(fp)} 를 못 읽었다 ({type(exc).__name__}). 검사하지 **않았다**.")
        return

    hits = []
    for i, line in enumerate(lines, 1):
        m = _SECRET_RE.search(line)
        if m:
            hits.append((i, str(m.group(1)).upper()))

    if not hits:
        return

    shown = hits[:_MAX_REPORT]
    detail = ", ".join(f"{key}@L{ln}" for ln, key in shown)
    more = f" (외 {len(hits) - len(shown)}건)" if len(hits) > len(shown) else ""
    _emit(
        f"secret-scan: {os.path.basename(fp)} 에 자격증명 형태 {len(hits)}건 — {detail}{more}. "
        f"커밋 전 확인할 것 (값은 의도적으로 출력하지 않음)."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # 훅이 편집을 막아서는 안 된다 — 단, 침묵하지도 않는다.
        _emit(f"secret-scan: 검사기 자체가 실패했다 ({type(exc).__name__}: {exc}). 검사하지 **않았다**.")
