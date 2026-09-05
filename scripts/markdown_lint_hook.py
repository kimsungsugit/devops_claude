"""PostToolUse hook for markdown files — light consistency check.

Reads Claude Code's PostToolUse JSON payload from stdin, identifies the
edited file, and runs a small set of checks if it is `.md`:

- Heading level jump (e.g. H1 → H3 with no H2 between)
- Broken internal `.md` links (relative path doesn't exist)

Output: prints a single JSON line to stdout in the
`hookSpecificOutput.additionalContext` envelope so Claude Code surfaces
the result back into the conversation. Always exit 0 — this is advisory.
"""
from __future__ import annotations

import json
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _payload_file(payload: dict) -> str:
    return (
        payload.get("tool_input", {}).get("file_path")
        or payload.get("tool_response", {}).get("filePath")
        or ""
    )


def _emit(msg: str) -> None:
    # ensure_ascii=False — 한글 메시지가 \uXXXX 로 깨지면 읽을 수 없다.
    # (posttoolbatch_report.py 와 같은 규약)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"markdown: {msg}",
        }
    }, ensure_ascii=False))


def main(payload: dict | None = None) -> None:
    if payload is None:
        try:
            payload = json.load(sys.stdin)
        except Exception:
            return
    if not isinstance(payload, dict):
        return
    fpath = _payload_file(payload)
    if not fpath or not fpath.endswith(".md"):
        return
    if not os.path.isfile(fpath):
        return

    try:
        with open(fpath, encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return

    issues: list[str] = []

    # SKILL.md — frontmatter 는 조용히 실패한다. `trigger:` 같은 미지 필드도,
    # `when_to_use` 부재도 하네스가 아무 말 없이 넘어가므로 눈으로는 못 본다.
    # (2026-07-17에 스킬 16개 — 프로젝트 14 + 플러그인 2 — **전부** 트리거 0이었다.)
    #
    # "스킬이 뭐냐"는 `check_skill_frontmatter.skill_location()` **단일 정의**를
    # 따른다. 여기서 basename 만 보고 판정하면 `.venv/**/SKILL.md` 같은 서드파티
    # 파일까지 우리 규칙으로 신고하게 되고, CLI 스캔과도 갈라진다.
    if os.path.basename(fpath) == "SKILL.md":
        try:
            from pathlib import Path

            _here = os.path.dirname(os.path.abspath(__file__))
            if _here not in sys.path:
                sys.path.insert(0, _here)
            from check_skill_frontmatter import check_file, skill_location

            if skill_location(Path(fpath))[0] != "unknown":
                issues.extend(f"frontmatter: {m}" for m in check_file(Path(fpath)))
        except Exception as e:
            # 침묵하면 "검사했고 깨끗함"과 구분이 안 된다 — 이 저장소의 fake-green.
            issues.append(f"frontmatter: 검사 불가 ({type(e).__name__}) — 통과 아님")

    # 하네스 문서 **본문**의 코드 참조 실재 검사. frontmatter 검사기는 구조만 보므로
    # "없는 함수 사용법"·"무관한 줄번호"·"통째로 허구인 에이전트 문서" 를 못 봤다
    # (2026-08-03 감사에서 9건). 여기서는 **이 파일에 새로 생긴 위반만** 신고한다.
    _rel = os.path.abspath(fpath)
    if _rel.startswith(str(_ROOT)) and (
        os.sep + ".claude" + os.sep in _rel or os.path.basename(fpath) == "CLAUDE.md"
    ):
        try:
            from pathlib import Path

            _here = os.path.dirname(os.path.abspath(__file__))
            if _here not in sys.path:
                sys.path.insert(0, _here)
            import check_doc_references as _cdr

            _md_rel = Path(_rel).relative_to(_ROOT).as_posix()
            _paths, _by_name = _cdr._tracked_index()
            issues.extend(
                f"doc-ref: {h[2]} {h[3]} (L{h[1]})"
                for h in _cdr.scan([_md_rel], _paths, _by_name)
            )
        except Exception as e:
            issues.append(f"doc-ref: 검사 불가 ({type(e).__name__}) — 통과 아님")

    in_code = False
    prev_level = 0
    base_dir = os.path.dirname(fpath)

    # Strip inline code spans `...` so example links/headings inside backticks
    # (e.g. ` ```[text](nope.md) ``` ` 같은 예시) don't trigger false positives.
    _INLINE_CODE = re.compile(r"`+[^`\n]*`+")

    for i, line in enumerate(content.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue

        # Indented code block (4+ leading spaces) — also code, skip
        if line.startswith("    ") and stripped:
            continue

        # Mask inline code before checking links/headings
        masked = _INLINE_CODE.sub("", line)

        m_heading = re.match(r"^(#+)\s", masked)
        if m_heading:
            lvl = len(m_heading.group(1))
            if prev_level and lvl > prev_level + 1:
                issues.append(f"L{i}: heading level jump (H{prev_level}→H{lvl})")
            prev_level = lvl

        for link_m in re.finditer(r"\]\(([^)#]+\.md)(?:#[^)]*)?\)", masked):
            target = link_m.group(1).strip()
            if target.startswith(("http://", "https://")):
                continue
            target_path = os.path.normpath(os.path.join(base_dir, target))
            if not os.path.exists(target_path):
                issues.append(f"L{i}: broken link → {target}")

        # @import 라인 (CLAUDE.md/메모리 파일) 대상 존재 검증 — `](path)` 링크와 달리
        # 기존 broken-link 검사가 못 잡던 always-on import 깨짐을 포착.
        m_import = re.match(r"^@([\w./~+-]+)$", masked.strip())
        if m_import:
            imp = m_import.group(1)
            # 경로꼴(슬래시 포함 또는 알려진 확장자)일 때만 검증 — `@mention` 류 오탐 방지
            if "/" in imp or imp.endswith((".md", ".json", ".txt")):
                if imp.startswith("~"):
                    imp_path = os.path.expanduser(imp)
                elif os.path.isabs(imp):
                    imp_path = imp
                else:
                    imp_path = os.path.normpath(os.path.join(base_dir, imp))
                if not os.path.exists(imp_path):
                    issues.append(f"L{i}: broken @import → {imp}")

    if not issues:
        _emit("clean")
    else:
        head = "; ".join(issues[:3])
        more = f" (+{len(issues) - 3} more)" if len(issues) > 3 else ""
        _emit(f"{len(issues)} issue(s): {head}{more}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Hook failures must never block the parent tool call.
        pass
