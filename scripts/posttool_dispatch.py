"""PostToolUse 통합 dispatcher.

매 Write|Edit 후 단일 인터프리터로 확장자별 lint/test를 실행한다.
이전: settings.json L91~L126의 5개 인라인 hook (Python 인터프리터 5회 기동).
이후: 본 dispatcher 1회 호출.

각 분기는 try/except로 격리되어 한 단계 실패가 다른 단계를 막지 않는다.
모든 결과는 results 리스트에 누적되어 단일 hookSpecificOutput으로 출력된다.
"""
from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

_t0 = time.perf_counter()
_ROOT = Path(__file__).resolve().parents[1]
_NPX = shutil.which("npx") or shutil.which("npx.cmd") or "npx"


def _payload_file(payload: dict) -> str:
    return (
        payload.get("tool_input", {}).get("file_path")
        or payload.get("tool_response", {}).get("filePath")
        or ""
    )


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    f = _payload_file(payload)
    if not f:
        return
    f_norm = f.replace("\\", "/")
    fname = Path(f).name

    results: list[str] = []

    # .py — syntax + ruff + auto-test
    if f.endswith(".py"):
        try:
            with open(f, encoding="utf-8", errors="ignore") as src:
                ast.parse(src.read(), filename=f)
            results.append(f"syntax OK: {fname}")
        except SyntaxError as e:
            results.append(f"syntax FAIL: {e.msg} (line {e.lineno})")
        except Exception as e:
            results.append(f"syntax skipped ({type(e).__name__})")

        try:
            r = subprocess.run(
                [sys.executable, "-m", "ruff", "check", "--fix", f],
                capture_output=True, text=True, timeout=10,
            )
            results.append(f"ruff: {(r.stdout.strip() or 'clean')[:200]}")
        except Exception as e:
            results.append(f"ruff: skipped ({type(e).__name__})")

        tests: str | None = None
        if "/workflow/" in f_norm:
            tests = "tests/unit/"
        elif "/report_gen/" in f_norm:
            tests = "tests/unit/test_report_gen.py"
        if tests:
            try:
                r = subprocess.run(
                    [sys.executable, "-m", "pytest", tests, "-x", "-q",
                     "--tb=line", "--no-header"],
                    capture_output=True, text=True, timeout=30,
                )
                results.append(f"auto-test: {(r.stdout.strip()[-200:] or 'pass')}")
            except Exception as e:
                results.append(f"auto-test: skipped ({type(e).__name__})")

    # .jsx/.tsx/.ts/.js (frontend-v2/) — eslint --fix
    elif f.endswith((".jsx", ".tsx", ".ts", ".js")) and "frontend-v2" in f_norm:
        try:
            r = subprocess.run(
                [_NPX, "eslint", "--fix", "--no-error-on-unmatched-pattern", f],
                capture_output=True, text=True, cwd=str(_ROOT / "frontend-v2"),
                timeout=30, shell=False,
            )
            results.append(f"eslint: {(r.stdout.strip() or 'clean')[:200]}")
        except Exception as e:
            results.append(f"eslint: skipped ({type(e).__name__})")

    # .md — markdown_lint_hook.main(payload) 직접 호출
    elif f.endswith(".md"):
        try:
            sys.path.insert(0, str(_ROOT / "scripts"))
            from markdown_lint_hook import main as md_main
            md_main(payload)
            return
        except Exception as e:
            results.append(f"md-lint: skipped ({type(e).__name__})")

    # .c/.h — PreToolUse ASIL 경고로 충분, skip

    elapsed = time.perf_counter() - _t0
    if results:
        out = " | ".join(results) + f" [{elapsed:.2f}s]"
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": out,
            }
        }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
