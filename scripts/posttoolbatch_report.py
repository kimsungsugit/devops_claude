"""PostToolBatch hook — 병렬 도구 일괄 완료 후 보고.

Claude Code가 한 응답에서 여러 Write/Edit/Bash 등을 병렬 호출하면,
모든 도구가 끝난 시점에 본 훅이 1회 발동한다. 목적:

1. 변경된 파일 목록을 한 번에 집계해서 (확장자별, 위치별) 보고
2. CLAUDE.md L106 "능동 보고" 의 X1~X8 mini-checklist 골격을
   `additionalContext` 로 메인 에이전트에게 push — 메인은 이를 그대로
   commit 직전 응답에 포함하면 됨

설계 원칙:
- payload shape가 공식 문서에 안정화되지 않았으므로 다중 키 탐색
  (`tool_calls` / `tools` / `batch` / `operations` / `tool_uses`)
- 빈 batch나 변경 파일 0개면 silent exit (출력 없음)
- 자체 에러는 PostToolUse dispatcher와 동일하게 hook 자체 침묵 + exit 0
  (stdout BrokenPipe 포함 — 메인 에이전트가 hook output을 소비하지 않는
   경우에도 hook 자체는 절대 부모 도구 호출을 막지 않음)
- 출력은 schema 정합 (`hookSpecificOutput.hookEventName="PostToolBatch"`)
- 단일 파일 turn은 PostToolUse가 이미 보고하므로 silent (단, ASIL C/H는 예외)
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

_TOOL_LIST_KEYS = ("tool_calls", "tools", "batch", "operations", "tool_uses")
_WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}


def _extract_tool_entries(payload: dict) -> list[dict]:
    for key in _TOOL_LIST_KEYS:
        v = payload.get(key)
        if isinstance(v, list):
            return [e for e in v if isinstance(e, dict)]
    for v in payload.values():
        if isinstance(v, list) and v and isinstance(v[0], dict) and "tool_name" in v[0]:
            return v
    return []


def _entry_tool(entry: dict) -> str:
    return entry.get("tool_name") or entry.get("name") or entry.get("tool") or ""


def _entry_file(entry: dict) -> str:
    inp = entry.get("tool_input") or entry.get("input") or {}
    resp = entry.get("tool_response") or entry.get("response") or {}
    return (
        inp.get("file_path")
        or inp.get("notebook_path")
        or resp.get("filePath")
        or ""
    )


def _classify(path: str) -> str:
    p = path.replace("\\", "/")
    if p.endswith(".py"):
        return "py"
    if p.endswith((".jsx", ".tsx")):
        return "jsx"
    if p.endswith((".js", ".ts")) and "frontend-v2" in p:
        return "js"
    if p.endswith(".md"):
        return "md"
    if p.endswith((".c", ".h")):
        return "c"
    if p.endswith(".json"):
        return "json"
    return "other"


def _build_report(entries: list[dict]) -> str | None:
    files: list[tuple[str, str]] = []
    for e in entries:
        if _entry_tool(e) not in _WRITE_TOOLS:
            continue
        f = _entry_file(e)
        if f:
            files.append((Path(f).name, _classify(f)))
    if not files:
        return None

    counts = Counter(cat for _, cat in files)
    has_asil = bool(counts.get("c"))

    # 단일 파일 turn은 PostToolUse(파일별 lint)가 이미 보고 — 중복 노이즈 방지.
    # ASIL C/H 파일은 단독이어도 hint를 띄워야 하므로 예외.
    if len(files) < 2 and not has_asil:
        return None

    summary = ", ".join(f"{cat}:{n}" for cat, n in sorted(counts.items()))
    head = f"[PostToolBatch] {len(files)} file(s) written — {summary}"
    asil_hint = " (C/H 변경 — ASIL 태그 확인)" if has_asil else ""

    checklist = (
        "X-check 자동 보고 trigger: 다음 응답에 (1) 변경 요약 표 "
        "(2) X1~X8 mini-checklist 표 (3) 잠재 문제 표 (4) 결론 1줄을 "
        "포함하라 (CLAUDE.md L106)."
    )

    # ASIL(c/h) 파일을 앞으로 정렬해 truncation 시 hint 누락 방지.
    ordered = sorted(files, key=lambda x: 0 if x[1] == "c" else 1)
    file_list = ", ".join(name for name, _ in ordered[:8])
    if len(ordered) > 8:
        file_list += f" (+{len(ordered) - 8} more)"

    return f"{head}{asil_hint} | files: {file_list} | {checklist}"


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    if not isinstance(payload, dict):
        return

    entries = _extract_tool_entries(payload)
    if not entries:
        return

    msg = _build_report(entries)
    if not msg:
        return

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolBatch",
            "additionalContext": msg,
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
