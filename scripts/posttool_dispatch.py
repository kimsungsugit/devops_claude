"""PostToolUse 통합 dispatcher.

매 Write|Edit 후 단일 인터프리터로 확장자별 lint/test를 실행한다.
이전: settings.json PostToolUse의 인라인 hook 5개 (Python 인터프리터 5회 기동).
이후: 본 dispatcher 1회 호출.

각 분기는 try/except로 격리되어 한 단계 실패가 다른 단계를 막지 않는다.
모든 결과는 results 리스트에 누적되어 단일 hookSpecificOutput으로 출력된다.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# 같은 scripts/ 디렉터리 — sys.path[0]로 해석된다. 단 이 import가 실패하면
# 훅 커맨드의 `2>/dev/null || true`가 traceback을 삼켜 **훅이 통째로 침묵**하므로
# (= 이 파일이 막으려는 바로 그 fake-green) 폴백을 둔다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _hook_env

    _PY = _hook_env.project_py()
    _module_missing = _hook_env.module_missing
except Exception:  # pragma: no cover - 방어
    _PY = sys.executable

    def _module_missing(r: subprocess.CompletedProcess) -> bool:
        # _hook_env.module_missing 과 **같은 allowlist 정규식**이어야 한다.
        # (blocklist 형태는 `ImportError("No module named x")` 를 오탐한다)
        tail = (r.stderr or "").strip().splitlines()
        return bool(r.returncode != 0 and tail
                    and re.match(r"^\S+: No module named \w+$", tail[-1].strip()))

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

        # `--fix` 미사용은 의도. (1) 훅이 방금 쓴 파일을 재작성하면 편집 도구의
        # in-memory 내용이 stale 해진다. (2) 이 게이트는 오래 fake-green이었어서
        # 위반 backlog가 쌓여 있고, --fix는 편집과 무관한 코드까지 한꺼번에
        # 자동 변형한다(실제로 workflow/common.py의 `import sys`가 그렇게 지워졌다).
        # 보고만 하고 변형 여부는 사람이 결정한다.
        try:
            r = subprocess.run(
                [_PY, "-m", "ruff", "check", f],
                capture_output=True, text=True, timeout=10,
            )
            if _module_missing(r):
                results.append("ruff: DISABLED (ruff 미설치 — 품질 게이트 비활성, venv 확인)")
            elif r.returncode != 0 and not r.stdout.strip():
                # 위반이 아니라 ruff 자체 실패. 빈 stdout을 clean으로 읽으면 fake-green.
                results.append(f"ruff: ERROR {(r.stderr.strip() or 'unknown')[:150]}")
            else:
                results.append(f"ruff: {(r.stdout.strip() or 'clean')[:200]}")
        except Exception as e:
            results.append(f"ruff: skipped ({type(e).__name__})")

        # auto-test: 변경 모듈의 테스트 파일만.
        # 과거 workflow/* 분기는 tests/unit/ 전체를 30s cap으로 돌렸는데, 훅
        # 인터프리터(mingw)엔 bcrypt가 없어 수집 에러로 3.5초 만에 죽었다.
        # 모듈 스코프 + 프로젝트 venv면 실제 신호가 남는다.
        _in_scope = "/workflow/" in f_norm or "/report_gen/" in f_norm
        tests: str | None = None
        if _in_scope:
            _cand = f"tests/unit/test_{Path(f).stem}.py"
            if (_ROOT / _cand).is_file():
                tests = _cand
            elif "/report_gen/" in f_norm and (_ROOT / "tests/unit/test_report_gen.py").is_file():
                tests = "tests/unit/test_report_gen.py"
        if _in_scope and not tests:
            # 침묵하면 "테스트 통과"와 "테스트 없음"이 구분되지 않는다.
            results.append(f"auto-test: no_module_tests (tests/unit/test_{Path(f).stem}.py 없음 — 회귀 미검증)")
        if tests:
            try:
                r = subprocess.run(
                    [_PY, "-m", "pytest", tests, "-x", "-q",
                     "--tb=line", "--no-header"],
                    capture_output=True, text=True, timeout=45,
                )
                if _module_missing(r):
                    results.append("auto-test: DISABLED (pytest 미설치 — venv 확인)")
                elif r.returncode != 0 and not r.stdout.strip():
                    # 수집 실패 등 pytest 자체 오류. 빈 stdout을 pass로 읽으면 fake-green.
                    results.append(f"auto-test: ERROR {(r.stderr.strip() or 'unknown')[:150]}")
                else:
                    results.append(
                        f"auto-test[{Path(tests).name}]: {(r.stdout.strip()[-200:] or 'pass')}"
                    )
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
            if r.returncode != 0 and not r.stdout.strip():
                # eslint/npx 자체 실행 실패(미설치·flat-config 오류·plugin 부재).
                # eslint 위반은 stdout(stylish 포맷)으로 나오므로, rc≠0 + 빈 stdout 은
                # '위반 없음'이 아니라 도구가 안 돈 것 — 빈 stdout 을 clean 으로 읽으면
                # fake-green. ruff/pytest 분기와 동일 가드(_module_missing 은 파이썬
                # 전용 패턴이라 Node 도구엔 안 걸려 rc 가드로 대체).
                results.append(f"eslint: ERROR {(r.stderr.strip() or 'unknown')[:150]}")
            else:
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
