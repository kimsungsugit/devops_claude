"""PreCompact 훅 — 압축 전에 git 상태를 파일로 보존.

컨텍스트가 압축되면 "지금 워킹 트리에 뭐가 있었는지"가 사라진다. 압축 직전에
`git status --porcelain` + `git diff --stat` 을 `.codex_tmp/precompact_context.json`
에 남겨, 압축 후에도 진행 중이던 변경을 되짚을 수 있게 한다.

이전엔 settings.json 에 한 줄짜리 `python -c "..."` 로 박혀 있었고 **timeout 도
없었다**(훅이 멈추면 압축 자체가 무기한 대기). 파일로 분리하고 settings 에
timeout 15s 를 준다. git 호출에도 각각 타임아웃을 건다.

계약: 실패는 조용히 넘긴다(압축을 막지 않는다). settings.json 의 `|| echo ...`
폴백이 최소 메시지를 대신 출력한다.
"""
from __future__ import annotations

import json
import os
import subprocess

_CAP = 500  # 각 필드 보존 상한 (systemMessage 가 비대해지지 않도록)


def _git(*args: str) -> str:
    try:
        r = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=10,
        )
        return r.stdout[:_CAP]
    except Exception:
        return ""


def main() -> None:
    status = _git("status", "--porcelain")
    diff_stat = _git("diff", "--stat")

    try:
        os.makedirs(".codex_tmp", exist_ok=True)
        with open(".codex_tmp/precompact_context.json", "w", encoding="utf-8") as fh:
            json.dump(
                {"git_status": status, "git_diff_stat": diff_stat},
                fh, ensure_ascii=False,
            )
    except Exception:
        pass  # 보존 실패해도 압축은 진행돼야 한다

    print(json.dumps({
        "systemMessage": (
            "PreCompact: preserved git status + diff stat to "
            ".codex_tmp/precompact_context.json. Changed: " + status[:150]
        )
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
