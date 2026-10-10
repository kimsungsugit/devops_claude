"""PreToolUse 훅 — ASIL C/D 소스 수정 전 경고.

C/H 파일을 Write/Edit 하기 **직전에** 기존 내용을 읽어 `@asil C|D` 태그가 있으면
경고를 메인 에이전트에 push 한다. CLAUDE.md 안전 규칙:
"안전 관련 함수(ASIL C/D) 변경 시: reviewer 리뷰 필수".

이전엔 settings.json 에 한 줄짜리 `python -c "..."` 로 박혀 있었다. 읽을 수도
고칠 수도 테스트할 수도 없었고, JSON 안의 이스케이프(`\\s`, 중첩 따옴표)가
조금만 틀어져도 조용히 죽는 구조였다. 동작은 그대로 두고 파일로만 분리한다.

계약:
- **절대 차단하지 않는다**(경고만). 예외/파싱 실패는 침묵 종료 — PreToolUse 훅이
  죽어서 편집 자체를 막으면 안 된다.
- 경고가 없으면 아무것도 출력하지 않는다.
- stdlib 만 사용 → 훅의 mingw python 으로도 동작(도구 의존 없음, _hook_env 불필요).
"""
from __future__ import annotations

import json
import os
import re
import sys

_EXTS = (".c", ".h")
#: Doxygen 주석의 `@asil C` / `@asil  d` 등. CLAUDE.md "ASIL 탐지 기준" 1번.
_ASIL_RE = re.compile(r"@asil\s+(C|D)\b", re.IGNORECASE)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    f = payload.get("tool_input", {}).get("file_path") or ""
    if not f.endswith(_EXTS) or not os.path.isfile(f):
        return

    try:
        with open(f, encoding="utf-8", errors="ignore") as src:
            content = src.read()
    except Exception:
        return

    m = _ASIL_RE.search(content)
    if not m:
        return

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"WARNING: ASIL {m.group(1).upper()} file — reviewer approval required "
                f"before modifying: {f}"
            ),
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # 훅이 편집을 막아선 안 된다
