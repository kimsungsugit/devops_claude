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


def _payload_file(payload: dict) -> str:
    return (
        payload.get("tool_input", {}).get("file_path")
        or payload.get("tool_response", {}).get("filePath")
        or ""
    )


def _emit(msg: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"markdown: {msg}",
        }
    }))


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
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
