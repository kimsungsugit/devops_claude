"""Comprehensive quality check — runs after code changes.

Checks:
1. Python syntax (py_compile)
2. Ruff lint
3. pytest (unit tests)
4. Frontend build (vite)
5. Frontend tests (vitest)
6. Code pattern issues (hardcoded values, missing null guards, etc.)

Usage:
    python scripts/quality_check.py              # single run
    python scripts/quality_check.py --round 1    # round 1 of 3 (focus: critical)
    python scripts/quality_check.py --round 2    # round 2 of 3 (focus: quality warnings)
    python scripts/quality_check.py --round 3    # round 3 of 3 (focus: regression/edge)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Parse CLI args
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--round", type=int, default=0, choices=[0, 1, 2, 3])
_parser.add_argument("--json", action="store_true", help="Output structured JSON only")
_args, _ = _parser.parse_known_args()
_ROUND = _args.round
_JSON_ONLY = _args.json

_ROUND_FOCUS = {
    0: "full",
    1: "critical — tests + build + syntax",
    2: "quality — warnings + patterns",
    3: "regression — edge cases + full suite",
}

_ROOT = Path(__file__).resolve().parents[1]
_FE = _ROOT / "frontend-v2"
_NPM = shutil.which("npm") or "npm"
_NPX = shutil.which("npx") or "npx"

issues: list[dict] = []
summary: dict[str, str] = {}


def _run(cmd: list[str], *, cwd: str | Path | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd or _ROOT, timeout=timeout)


def _add(severity: str, category: str, file: str, message: str):
    issues.append({"severity": severity, "category": category, "file": file, "message": message})


# ── 1. Detect changed files ──────────────────────────────────────────
# Early exit: nothing changed in working tree → skip all checks. This is the
# common case for conversational turns (질의/설명/계획 논의) where Stop hook
# would otherwise spend ~2s just to report 0 issues. Set QUALITY_CHECK_FORCE=1
# to bypass (e.g. CI sanity sweep on a clean tree).
changed_raw = _run(["git", "diff", "--name-only"]).stdout + _run(["git", "diff", "--name-only", "--cached"]).stdout
if not changed_raw.strip() and not os.environ.get("QUALITY_CHECK_FORCE"):
    if _JSON_ONLY:
        print(json.dumps({
            "round": _ROUND,
            "focus": _ROUND_FOCUS.get(_ROUND, "full"),
            "counts": {"critical": 0, "warning": 0, "info": 0},
            "next_action": "proceed",
            "issues": [],
            "skipped": "no_changes",
        }))
    sys.exit(0)

changed_files = [f.strip() for f in changed_raw.splitlines() if f.strip()]
py_files = [f for f in changed_files if f.endswith(".py")]
jsx_files = [f for f in changed_files if f.endswith((".jsx", ".tsx", ".js", ".ts")) and "frontend-v2" in f]

summary["changed_files"] = str(len(changed_files))
summary["changed_py"] = str(len(py_files))
summary["changed_jsx"] = str(len(jsx_files))

# ── 2. Python syntax check ───────────────────────────────────────────
for f in py_files:
    fp = _ROOT / f
    if not fp.exists():
        continue
    try:
        import py_compile
        py_compile.compile(str(fp), doraise=True)
    except py_compile.PyCompileError as e:
        _add("Critical", "syntax", f, str(e))

# ── 3. Ruff lint ─────────────────────────────────────────────────────
if py_files:
    r = _run([sys.executable, "-m", "ruff", "check", "--output-format=json"] + py_files)
    if r.stdout.strip():
        try:
            ruff_issues = json.loads(r.stdout)
            for ri in ruff_issues[:10]:
                _add("Warning", "lint", ri.get("filename", "?"), f'{ri.get("code","")}: {ri.get("message","")}')
        except json.JSONDecodeError:
            pass

# ── 4. pytest (unit) ─────────────────────────────────────────────────
if py_files:
    r = _run([sys.executable, "-m", "pytest", "tests/unit/", "-x", "-q", "--tb=line", "--no-header"], timeout=90)
    lines = r.stdout.strip().splitlines()
    last = lines[-1] if lines else ""
    if "failed" in last:
        _add("Critical", "test", "tests/unit/", last)
        summary["pytest"] = "FAIL"
    else:
        summary["pytest"] = "PASS"
else:
    summary["pytest"] = "skipped"

# ── 5. Frontend build ────────────────────────────────────────────────
if jsx_files:
    r = _run([_NPM, "run", "build"], cwd=_FE, timeout=60)
    if r.returncode != 0:
        err = r.stderr[-300:] if r.stderr else r.stdout[-300:]
        _add("Critical", "build", "frontend-v2/", f"vite build failed: {err}")
        summary["vite_build"] = "FAIL"
    else:
        summary["vite_build"] = "PASS"
else:
    summary["vite_build"] = "skipped"

# ── 6. Frontend test ─────────────────────────────────────────────────
if jsx_files:
    r = _run([_NPX, "vitest", "run"], cwd=_FE, timeout=120)
    if "failed" in r.stdout.lower():
        fail_line = [ln for ln in r.stdout.splitlines() if "failed" in ln.lower()]
        _add("Critical", "test", "frontend-v2/", fail_line[0] if fail_line else "vitest failed")
        summary["vitest"] = "FAIL"
    else:
        summary["vitest"] = "PASS"
else:
    summary["vitest"] = "skipped"

# ── 7. Code pattern issues (changed files only) ─────────────────────

for f in jsx_files:
    fp = _ROOT / f
    if not fp.exists():
        continue
    content = fp.read_text(encoding="utf-8", errors="ignore")
    lines = content.splitlines()

    # 7a. Hardcoded colors in JSX (should use CSS variables)
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if "style=" in stripped and ("#" in stripped or "rgb(" in stripped):
            # Exclude comments
            if not stripped.startswith("//") and not stripped.startswith("*"):
                _add("Info", "pattern", f"{f}:{i}", f"Hardcoded color in inline style — use CSS variable")

    # 7b. Missing toLocaleString for large numbers
    for i, line in enumerate(lines, 1):
        if ".length}" in line or "Count}" in line or "total}" in line:
            if "toLocaleString" not in line and "Locale" not in line:
                pass  # May be intentional for small counts

    # 7c. Missing null/undefined guard
    for i, line in enumerate(lines, 1):
        if ".map(" in line and "||" not in line and "?." not in line and "Array.isArray" not in line:
            # Check if preceded by a guard
            prev = lines[i - 2].strip() if i >= 2 else ""
            if "&&" not in prev and "?" not in prev and "length" not in prev:
                _add("Warning", "pattern", f"{f}:{i}", "Possible .map() without null guard — add ?. or Array.isArray check")

for f in py_files:
    fp = _ROOT / f
    if not fp.exists():
        continue
    content = fp.read_text(encoding="utf-8", errors="ignore")
    lines = content.splitlines()

    # 7d. Bare except in Python
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped == "except:" or stripped == "except Exception:":
            _add("Warning", "pattern", f"{f}:{i}", "Bare except — consider catching specific exception types")

    # 7e. HTTPException swallowed by broad except
    in_try = False
    has_http_raise = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("try:"):
            in_try = True
            has_http_raise = False
        elif in_try and "raise HTTPException" in stripped:
            has_http_raise = True
        elif in_try and stripped.startswith("except Exception") and has_http_raise:
            # Check if there's a re-raise for HTTPException before this
            prev_lines = [lines[j].strip() for j in range(max(0, i - 3), i - 1)]
            if not any("except HTTPException" in pl for pl in prev_lines):
                _add("Warning", "pattern", f"{f}:{i}", "HTTPException may be swallowed by broad except — add 'except HTTPException: raise' before")
            in_try = False
            has_http_raise = False


# ── Output ────────────────────────────────────────────────────────────
critical = [i for i in issues if i["severity"] == "Critical"]
warnings = [i for i in issues if i["severity"] == "Warning"]
infos = [i for i in issues if i["severity"] == "Info"]

# Round-aware header
round_tag = f"Round {_ROUND}/3 ({_ROUND_FOCUS[_ROUND]})" if _ROUND > 0 else "Single run"

# Structured result (machine-parseable)
structured = {
    "round": _ROUND,
    "focus": _ROUND_FOCUS[_ROUND],
    "pytest": summary.get("pytest", "skipped"),
    "vite_build": summary.get("vite_build", "skipped"),
    "vitest": summary.get("vitest", "skipped"),
    "counts": {
        "critical": len(critical),
        "warning": len(warnings),
        "info": len(infos),
    },
    "next_action": "proceed" if not critical else "fix_required",
    "issues": issues[:30],
}

if _JSON_ONLY:
    print(json.dumps(structured, ensure_ascii=False))
else:
    result_lines = [
        f"[{round_tag}] pytest: {summary.get('pytest', '-')} | vite: {summary.get('vite_build', '-')} | vitest: {summary.get('vitest', '-')}",
        f"Issues: {len(critical)} critical, {len(warnings)} warning, {len(infos)} info",
    ]
    if issues:
        for issue in issues[:15]:
            result_lines.append(f"  [{issue['severity']}] {issue['category']}: {issue['file']} — {issue['message']}")

    msg = " | ".join(result_lines[:2])
    detail = "\n".join(result_lines)
    print(json.dumps({
        "systemMessage": f"[Quality Check] {msg}",
        "detail": detail,
        "structured": structured,
    }, ensure_ascii=False))

# Exit code:
#   0 — no critical issues
#   1 — critical issues found (caller should fix and re-run)
sys.exit(1 if critical else 0)
