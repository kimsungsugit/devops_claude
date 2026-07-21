"""Comprehensive quality check — runs after code changes (Stop 훅).

Checks:
1. Python syntax (py_compile)
2. Ruff lint
3. pytest — 변경 모듈에 대응하는 test_<모듈>.py 만 (--round 3 은 전체 스위트)
4. Frontend build (vite)
5. Frontend tests (vitest)
6. Code pattern issues (hardcoded values, missing null guards, etc.)

이 게이트는 **advisory**다. 전체 회귀(tests/unit/ = 3486개 / **약 280s**, 2회 실측
274s·281s)는 Stop 훅 예산(기본 240s)에 살짝 못 들어가므로 `--round 3`에서 수행한다.

⚠ 전체 회귀를 **강제**하는 통제는 `.githooks/pre-commit` 뿐이고, `--no-verify`
커밋이면 건너뛴다. 이 스크립트의 기본 모드는 변경 모듈 스코프(1급 모듈의
31.6%만 매핑)라 전체 회귀를 대신하지 못한다.

모듈 스코프가 성립하려면 각 테스트 파일이 **단독으로 통과**해야 한다(그래야 여기서
나온 FAIL 을 진짜 회귀로 믿을 수 있다). 한때 test_routers.py 가 단독 14 F / 전체 0 F
였는데, 원인은 test_file_resolver_cloudium.py 가 teardown 에서 전역 resolver 를
Local 로 **고정**(복원이 아니라)하고 가는 누설이었다 → 수정됨(584833e).
`tests/unit/conftest.py` 의 `_default_local_resolver` / `_default_admin_users` 가
머신 상태로부터 격리한다. **전역 싱글톤을 teardown 에서 특정 값으로 고정하지 말 것 —
반드시 원래 값 복원.**

설계 불변식: **못 돌렸으면 PASS라고 쓰지 않는다.** 도구 부재는 DISABLED,
시간 초과는 TIMEOUT, 대응 테스트 없음은 no_module_tests로 구분 보고한다.
(과거엔 mingw 인터프리터 탓에 pytest가 bcrypt 수집 에러로 3.5초 만에 죽었는데도
마지막 줄 "1 error"에 "failed"가 없다는 이유로 **PASS**라고 보고했다.)
⚠ 단, 이 상태들은 `counts.critical`에 안 잡히므로 machine 소비자에겐
non-blocking이다 — `structured.not_run` 을 함께 읽을 것.

Env:
    QUALITY_CHECK_FORCE=1    무변경 조기종료 우회 (clean tree에서도 전수 점검)
                             — `--round 3`은 이 값 없이도 강제 실행된다
    QUALITY_CHECK_BUDGET=N   전역 예산 초 (기본 240, round 3은 900)
                             — Stop 훅 timeout(현재 300) 안에 들어가야 함
    DEVOPS_HOOK_PY=<path>    인터프리터 강제 지정 (진단·CI용)

Usage:
    python scripts/quality_check.py              # single run
    python scripts/quality_check.py --round 1    # round 1 of 3 (focus: critical)
    python scripts/quality_check.py --round 2    # round 2 of 3 (focus: quality warnings)
    python scripts/quality_check.py --round 3    # round 3 of 3 (focus: regression — 전체 스위트)
"""
from __future__ import annotations

import argparse
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# 같은 scripts/ 디렉터리 — sys.path[0]로 해석된다. 단 이 import가 실패하면
# 훅 커맨드의 `2>/dev/null || true`가 traceback을 삼켜 **게이트가 통째로 침묵**하므로
# (= 이 스크립트가 막으려는 바로 그 fake-green) 폴백을 둔다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
_hook_env_error: str | None = None
try:
    import _hook_env

    _project_py = _hook_env.project_py
    _module_missing = _hook_env.module_missing
except Exception as _e:  # pragma: no cover - 방어
    # 폴백 사실을 반드시 남긴다. 안 그러면 "ruff DISABLED — venv 확인" 만 보이는데
    # 진짜 원인은 _hook_env.py 파손이라 개발자를 애먼 venv 디버깅으로 보낸다.
    _hook_env_error = f"{type(_e).__name__}: {_e}"

    def _project_py() -> str:
        return sys.executable

    def _module_missing(r: subprocess.CompletedProcess) -> bool:
        tail = (r.stderr or "").strip().splitlines()
        return bool(r.returncode != 0 and tail
                    and re.match(r"^\S+: No module named \w+$", tail[-1].strip()))

# 침묵-except 분류기 (§7d). import 실패해도 게이트는 계속 — 침묵 검사만 skip 한다.
# advisory 기능이라 조용히 disable 해도 "PASS 위장"이 아니다(findings 가 안 나올 뿐).
_silence_import_error: str = ""
try:
    from _silence_check import _iter_added_lines, silent_excepts
    _silence_ok = True
except Exception as _se:  # 예외를 표면화하므로(아래) silent 아님
    _silence_ok = False
    _silence_import_error = f"{type(_se).__name__}: {_se}"

    def silent_excepts(source: str) -> list[tuple[int, str]]:  # 폴백 스텁
        return []

    def _iter_added_lines(diff: str) -> dict[str, set[int]]:  # 폴백 스텁
        return {}

# Parse CLI args
_parser = argparse.ArgumentParser(add_help=False)
# start-work 스킬의 적응형 루프는 MAX_ROUNDS=5까지 돈다. choices=[0..3]이던 시절
# --round 4/5는 argparse error → exit 2 / stdout 빈 값 → 소비자의
# result["counts"]["critical"] 파싱이 깨졌다.
_parser.add_argument("--round", type=int, default=0, choices=[0, 1, 2, 3, 4, 5])
_parser.add_argument("--json", action="store_true", help="Output structured JSON only")
_args, _ = _parser.parse_known_args()
_ROUND = _args.round
_JSON_ONLY = _args.json

_ROUND_FOCUS = {
    0: "full",
    1: "critical — tests + build + syntax",
    2: "quality — warnings + patterns",
    3: "regression — edge cases + full suite",
    4: "adaptive — 잔존 Critical 재확인",
    5: "adaptive — 최종 확인",
}

_ROOT = Path(__file__).resolve().parents[1]
_FE = _ROOT / "frontend-v2"
_NPM = shutil.which("npm") or "npm"
_NPX = shutil.which("npx") or "npx"
_PY = _project_py()

# 전역 예산. Stop 훅의 timeout 안에서 반드시 스스로 끝내고 보고까지 마쳐야 한다.
# 예산을 넘겨 훅이 밖에서 kill 되면 `2>/dev/null || true` 탓에 아무 출력도 남지
# 않아 "이상 없음"처럼 보인다(침묵 = fake-green). 남은 예산이 없으면 각 단계를
# 건너뛰되 그 사실을 명시 보고한다.
# round 3은 Stop 훅이 아니라 사람이 명시 호출하는 전체 회귀라 예산이 따로다
# (스위트 ~280s + vite/vitest + 여유).
_BUDGET = float(os.environ.get("QUALITY_CHECK_BUDGET", "900" if _ROUND == 3 else "240"))
_DEADLINE = time.monotonic() + _BUDGET
_TIMED_OUT = 124  # GNU timeout 관례

issues: list[dict] = []
summary: dict[str, str] = {}


def _budget_left(reserve: float = 8.0) -> float:
    """보고 출력분(reserve)을 남긴 잔여 예산(초)."""
    return max(0.0, _DEADLINE - time.monotonic() - reserve)


def _run(cmd: list[str], *, cwd: str | Path | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    """절대 예외를 던지지 않는 실행기.

    TimeoutExpired가 전파되면 스크립트가 죽고, 훅 커맨드의 `2>/dev/null || true`가
    그 죽음을 삼켜 Stop 게이트가 통째로 침묵한다(= 이상 없음처럼 보임).
    변경 전엔 이 방어가 없었다. 다만 **과거에 실제로 타임아웃이 났던 건 아니다** —
    그땐 훅 인터프리터가 mingw python이라 pytest가 bcrypt 수집 에러로 3.5초 만에
    죽었고(rc=1, "1 error in 3.48s"), 90s cap에 닿을 일이 없었다.
    이제 실패는 returncode로 표현되고 호출부가 명시 보고한다.
    """
    try:
        # encoding/errors 를 **명시**한다. 안 하면 text=True 가
        # locale.getpreferredencoding() 에 의존하는데, 한글 Windows 에서
        # ① 로케일이 cp949 면 git·ruff 의 UTF-8 JSON 을 오독하고
        # ② 로케일이 utf-8 이어도 npm/vitest 가 뱉는 cp949 바이트(예: 0xbe)에
        #    reader thread 가 strict 디코드로 죽어, 그 스트림이 **조용히 ""** 가 된다.
        #    (subprocess 의 _readerthread 예외는 main 으로 전파 안 되고 buffer 만 빈다)
        # 빈 stdout 을 verdict 로 쓰면 fail-green 벡터다. utf-8 고정(정본)+replace 로
        # ASCII verdict 마커("passed"/"FAIL"/JSON)는 보존하고 잔여 바이트만 U+FFFD.
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              cwd=cwd or _ROOT, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, _TIMED_OUT, "", f"TIMEOUT after {timeout}s")
    except (FileNotFoundError, OSError) as e:
        return subprocess.CompletedProcess(cmd, 127, "", f"NOT FOUND: {e}")


def _add(severity: str, category: str, file: str, message: str):
    issues.append({"severity": severity, "category": category, "file": file, "message": message})


#: "안 돌렸음" 을 뜻하는 상태들. 이 값이 하나라도 있으면 verified=False.
#: RAN 상태(clean / "N issues" / PASS… / FAIL)는 절대 여기 들어가면 안 된다.
_NOT_RUN_STATES = {
    "DISABLED", "TIMEOUT", "no_module_tests", "budget_exceeded",
    "PARSE_ERROR", "ERROR", "FALLBACK",
}
#: not_run 순회 대상 — summary 엔 changed_files 같은 메타도 섞여 있어 전체를 돌면 오염된다.
_CHECK_KEYS = ("ruff", "pytest", "vite_build", "vitest", "hook_env")


def _build_structured(*, not_run: dict | None = None, skipped: str = "") -> dict:
    """`--json` 계약의 **단일 빌더**.

    조기종료(무변경)와 주 경로가 각자 dict 를 조립하면 한쪽만 바뀌어 드리프트가
    생긴다(실제로 그랬다). 소비자(`.claude/skills/start-work/SKILL.md` Gate 5)는
    `counts.critical` 과 `verified`/`not_run` 을 읽으므로 **어느 경로로 끝나든
    이 키들이 같은 의미로 나와야 한다**.

    ⚠ `verified=False` 면 `critical==0` 이 "깨끗함" 을 뜻하지 않는다 —
    "Critical 로 분류된 게 없음" 일 뿐이다(아무것도 안 돌렸을 수 있다).
    """
    nr = dict(not_run) if not_run is not None else {
        k: summary[k] for k in _CHECK_KEYS if summary.get(k) in _NOT_RUN_STATES
    }
    crit = [i for i in issues if i["severity"] == "Critical"]
    out = {
        "round": _ROUND,
        "focus": _ROUND_FOCUS.get(_ROUND, "full"),
        "pytest": summary.get("pytest", "skipped"),
        "ruff": summary.get("ruff", "skipped"),
        "vite_build": summary.get("vite_build", "skipped"),
        "vitest": summary.get("vitest", "skipped"),
        # verified=False 면 "Critical 0"이 "검증했고 깨끗함"을 뜻하지 않는다.
        "verified": not nr,
        "not_run": nr,
        "counts": {
            "critical": len(crit),
            "warning": len([i for i in issues if i["severity"] == "Warning"]),
            "info": len([i for i in issues if i["severity"] == "Info"]),
        },
        "next_action": "proceed" if not crit else "fix_required",
        "issues": issues[:30],
    }
    if skipped:
        out["skipped"] = skipped
    return out


if _hook_env_error:
    # 폴백 중이라는 사실 자체가 finding이다. 이게 없으면 "ruff DISABLED — venv 확인"만
    # 보이고 진짜 원인(_hook_env.py 파손)은 어디에도 안 나온다.
    _add("Critical", "hook", "scripts/_hook_env.py",
         "_hook_env import 실패 → 인터프리터 해석 폴백 중(도구가 DISABLED로 보일 수 있음). "
         f"venv가 아니라 이 파일을 먼저 확인: {_hook_env_error}")
    summary["hook_env"] = "FALLBACK"

if not _silence_ok:
    # _hook_env 와 같은 원칙 — "못 돌렸으면 PASS라고 쓰지 않는다". 침묵-except 검사가
    # import 실패로 죽으면 §7d findings 0 은 "깨끗함"이 아니라 "안 돌렸음"이다.
    # advisory 기능이라 Critical 은 아니지만 반드시 신호한다(조용히 죽으면 fake-green).
    _add("Warning", "hook", "scripts/_silence_check.py",
         f"침묵-except 검사 비활성(import 실패) — §7d 미검증: {_silence_import_error}")
    summary["silence"] = "DISABLED"


# ── 1. Detect changed files ──────────────────────────────────────────
# Early exit: nothing changed in working tree → skip all checks. This is the
# common case for conversational turns (질의/설명/계획 논의) where Stop hook
# would otherwise spend ~2s just to report 0 issues. Set QUALITY_CHECK_FORCE=1
# to bypass (e.g. CI sanity sweep on a clean tree).
#
# round 3(전체 회귀)은 강제 실행한다. 이 모드를 돌릴 시점은 보통 **커밋 직후**인데
# 그때 트리가 clean이라, 조기 종료하면 "전체 회귀를 돌렸다"면서 실제로는 아무것도
# 안 도는 no-op이 된다 — 이 스크립트가 없애려는 fake-green과 같은 결말.
_FORCE = bool(os.environ.get("QUALITY_CHECK_FORCE")) or _ROUND == 3
changed_raw = _run(["git", "diff", "--name-only"]).stdout + _run(["git", "diff", "--name-only", "--cached"]).stdout

# untracked(아직 `git add` 안 한 신규 파일)도 '변경'이다. 이게 빠져 있어서 새로
# 만든 파일은 이 스크립트의 **모든 검사에서 통째로 빠졌다** — syntax·ruff·모듈
# 테스트·패턴(§7a~7e)·침묵 except 전부. 실측: `except Exception: pass` 와
# `subprocess.run(cmd, shell=True)` 가 든 untracked .py 를 두고 돌렸더니
# `Issues: 0 critical, 0 warning` + `verified: true` + `proceed` 가 나왔다.
# 검사하지 않은 걸 '검증됨'이라 쓰는 건 이 스크립트가 없애려는 fake-green 그 자체다.
#
# 아래 캐시 제거 주석(§결과 캐시)이 이미 같은 교훈을 담고 있다 — "tracked diff 는
# untracked 변경을 못 본다". 그때는 **캐시 키**만 고치고 **파일 목록**은 같은
# tracked-only 신호를 계속 썼다. 두 곳이 같은 결함이었다.
#
# `--exclude-standard` 로 .gitignore 를 존중한다(빌드 산출물·스크래치 제외).
# 실측 0.2s / 2건이라 비용도 노이즈도 없다. git 실패 시엔 조용히 건너뛰지 않고
# 아래 §7d 에서 판정 보류로 표면화한다.
_untracked_cp = _run(["git", "ls-files", "--others", "--exclude-standard"])
_untracked_raw = _untracked_cp.stdout if _untracked_cp.returncode == 0 else ""
changed_raw += _untracked_raw
untracked_files = {f.strip().replace("\\", "/") for f in _untracked_raw.splitlines() if f.strip()}

if not changed_raw.strip() and not _FORCE:
    if _JSON_ONLY:
        print(json.dumps(
            _build_structured(not_run={"all": "no_changes"}, skipped="no_changes"),
            ensure_ascii=False,
        ))
    sys.exit(0)

changed_files = [f.strip() for f in changed_raw.splitlines() if f.strip()]

# 결과 캐시는 의도적으로 두지 않는다.
# 한때 sha256(_ROUND + git diff + git diff --cached)를 키로 결과를 캐시했으나,
# 그 키는 **tracked diff만** 담는 반면 실제 검사(pytest/ruff/vite/vitest)는
# 워킹 트리 전체 + 설치된 의존성 + env를 읽는다 → 키가 진짜 입력의 진부분집합.
# 실증: untracked `tests/unit/conftest.py`가 import를 깨뜨려도 키가 그대로라
# cache hit → 진실이 critical=1/fix_required인데 PASS/proceed를 반환했다.
# 즉 캐시가 이 스크립트의 유일한 존재 이유(= 안 돌렸으면 PASS라고 쓰지 않기)를
# 스스로 깨뜨렸다. 게다가 round가 매 턴 교대(0↔1/2/3)라 단일 슬롯 hit률은
# 정작 비싼 deep 루프에서 ~0이었다. 정확히 캐시하려면 워킹 트리 전체를
# 해싱해야 하는데 그건 배터리보다 비싸다.
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
        py_compile.compile(str(fp), doraise=True)
    except py_compile.PyCompileError as e:
        _add("Critical", "syntax", f, str(e))

# ── 3. Ruff lint ─────────────────────────────────────────────────────
if py_files:
    r = _run([_PY, "-m", "ruff", "check", "--output-format=json"] + py_files, timeout=30)
    if _module_missing(r):
        # 예전엔 여기서 stdout이 비어 `if r.stdout.strip()`이 거짓 → lint 이슈가
        # 영구히 0건이었다. 도구 부재는 "이상 없음"이 아니라 게이트 고장이다.
        _add("Critical", "lint", "scripts/", "ruff 미설치 — lint 게이트 비활성(DISABLED). venv 확인 필요")
        summary["ruff"] = "DISABLED"
    elif r.returncode == _TIMED_OUT:
        _add("Warning", "lint", "scripts/", "ruff 타임아웃 — lint 미검증")
        summary["ruff"] = "TIMEOUT"
    elif r.returncode != 0 and not r.stdout.strip():
        # ruff는 위반이 있으면 rc=1이라 rc만으로는 판정 못 한다. 하지만 rc!=0인데
        # stdout까지 비었으면 그건 "위반 0건"이 아니라 ruff 자체 실패(설정 오류,
        # 인터프리터 소실 등)다. 빈 stdout을 []→"clean"으로 읽으면 원래 버그 복원.
        _add("Critical", "lint", "scripts/", f"ruff 실행 실패(rc={r.returncode}) — lint 미검증: {(r.stderr or '').strip()[:120]}")
        summary["ruff"] = "ERROR"
    else:
        try:
            ruff_issues = json.loads(r.stdout) if r.stdout.strip() else []
            for ri in ruff_issues[:10]:
                _add("Warning", "lint", ri.get("filename", "?"), f'{ri.get("code","")}: {ri.get("message","")}')
            summary["ruff"] = f"{len(ruff_issues)} issues" if ruff_issues else "clean"
        except json.JSONDecodeError:
            _add("Warning", "lint", "scripts/", f"ruff 출력 파싱 실패: {(r.stderr or r.stdout)[:120]}")
            summary["ruff"] = "PARSE_ERROR"
else:
    summary["ruff"] = "skipped"

# ── 4. pytest ────────────────────────────────────────────────────────
# 전체 tests/unit/은 3486개 / 약 280s 라 Stop 훅 예산(240s)에 살짝 못 들어간다.
# 그래서 기본(round 0/1/2)은 **변경 모듈에 대응하는 테스트만** 돌리고,
# 전체 회귀는 명시 요청(--round 3)에서 수행한다.
# ⚠ 커버리지 한계: 1급 모듈 중 test_<stem>.py 매핑은 66/209(31.6%)뿐이고,
#   모듈 스코프는 교차 모듈 회귀를 못 잡는다. 이 게이트는 advisory이며
#   전체 회귀를 대신하지 않는다.
# ⚠ 단독 실행 전제: 각 테스트 파일이 단독으로 통과해야 여기 FAIL 을 믿을 수 있다
#   (격리 규약은 위 독스트링 + tests/unit/conftest.py 참조).
def _module_tests(files: list[str]) -> list[str]:
    targets: set[str] = set()
    for f in files:
        if f.startswith("tests/") and Path(f).name.startswith("test_"):
            targets.add(f)  # 테스트 자체를 고친 경우
            continue
        cand = f"tests/unit/test_{Path(f).stem}.py"
        if (_ROOT / cand).is_file():
            targets.add(cand)
    return sorted(targets)


_full_suite = _ROUND == 3
_test_targets = ["tests/unit/"] if _full_suite else _module_tests(py_files)

if not py_files and not _full_suite:
    # 전체 회귀(round 3)는 변경 파일 목록과 무관하게 돈다 — 커밋 직후 clean tree가
    # 정확히 그걸 돌릴 시점이라, py_files가 비었다고 skip하면 no-op이 된다.
    summary["pytest"] = "skipped"
elif not _test_targets:
    # "PASS"라고 쓰면 안 된다 — 아무것도 안 돌렸다.
    summary["pytest"] = "no_module_tests"
    _add("Info", "test", "tests/unit/", f"변경 {len(py_files)}개 .py에 대응하는 test_<모듈>.py 없음 — 회귀 미검증")
elif _budget_left() < 15:
    summary["pytest"] = "budget_exceeded"
    _add("Warning", "test", "tests/unit/", "예산 초과로 pytest 미실행 — 회귀 미검증")
else:
    # round 3의 cap은 실측 스위트(~280s)보다 넉넉해야 한다. cap이 스위트보다 짧으면
    # 전체 회귀가 항상 TIMEOUT→Warning→proceed 로 빠져 "전체를 돌렸다"는 착각만 남는다.
    _t_budget = int(min(900 if _full_suite else 150, _budget_left()))
    r = _run([_PY, "-m", "pytest", *_test_targets, "-x", "-q", "--tb=line", "--no-header"], timeout=_t_budget)
    _scope = "full" if _full_suite else f"{len(_test_targets)} module tests"
    if _module_missing(r):
        _add("Critical", "test", "tests/unit/", "pytest 미설치 — 테스트 게이트 비활성(DISABLED). venv 확인 필요")
        summary["pytest"] = "DISABLED"
    elif r.returncode == _TIMED_OUT:
        _add("Warning", "test", "tests/unit/", f"pytest 타임아웃({_t_budget}s) — 회귀 미검증({_scope})")
        summary["pytest"] = "TIMEOUT"
    elif r.returncode != 0:
        # returncode 기준. 예전엔 마지막 줄의 "failed" 문자열만 봤기 때문에
        # 수집 에러("1 error in 0.5s")가 조용히 PASS로 보고됐다.
        lines = r.stdout.strip().splitlines()
        last = lines[-1] if lines else (r.stderr or "")[-160:]
        _add("Critical", "test", ", ".join(_test_targets)[:80], f"exit={r.returncode}: {last[:160]}")
        summary["pytest"] = "FAIL"
    else:
        summary["pytest"] = f"PASS ({_scope})"

# ── 5. Frontend build ────────────────────────────────────────────────
if not jsx_files:
    summary["vite_build"] = "skipped"
elif _budget_left() < 15:
    summary["vite_build"] = "budget_exceeded"
    _add("Warning", "build", "frontend-v2/", "예산 초과로 vite build 미실행 — 빌드 미검증")
else:
    r = _run([_NPM, "run", "build"], cwd=_FE, timeout=int(min(90, _budget_left())))
    if r.returncode == _TIMED_OUT:
        _add("Warning", "build", "frontend-v2/", "vite build 타임아웃 — 빌드 미검증")
        summary["vite_build"] = "TIMEOUT"
    elif r.returncode != 0:
        err = r.stderr[-300:] if r.stderr else r.stdout[-300:]
        _add("Critical", "build", "frontend-v2/", f"vite build failed: {err}")
        summary["vite_build"] = "FAIL"
    else:
        summary["vite_build"] = "PASS"

# ── 6. Frontend test ─────────────────────────────────────────────────
if not jsx_files:
    summary["vitest"] = "skipped"
elif _budget_left() < 15:
    summary["vitest"] = "budget_exceeded"
    _add("Warning", "test", "frontend-v2/", "예산 초과로 vitest 미실행 — 프론트 회귀 미검증")
else:
    r = _run([_NPX, "vitest", "run"], cwd=_FE, timeout=int(min(120, _budget_left())))
    if r.returncode == _TIMED_OUT:
        _add("Warning", "test", "frontend-v2/", "vitest 타임아웃 — 프론트 회귀 미검증")
        summary["vitest"] = "TIMEOUT"
    elif r.returncode != 0:
        # returncode 기준. stdout에서 "failed" 문자열만 찾던 예전 방식은 vitest가
        # 아예 기동 실패했을 때(=출력에 failed 없음) PASS로 보고했다.
        fail_line = [ln for ln in r.stdout.splitlines() if "failed" in ln.lower()]
        detail = fail_line[0] if fail_line else (r.stderr or r.stdout)[-160:]
        _add("Critical", "test", "frontend-v2/", f"exit={r.returncode}: {detail}")
        summary["vitest"] = "FAIL"
    else:
        summary["vitest"] = "PASS"

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
                _add("Info", "pattern", f"{f}:{i}", "Hardcoded color in inline style — use CSS variable")

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

# 침묵 except ratchet: HEAD 대비 **추가된 라인**만 net-new 로 본다. 레거시 backlog
# (침묵 except 1294개, 정당한 것 포함)는 건드리는 파일이어도 침묵 — posttool_dispatch
# .py:78-82 의 "레거시를 자동 변형 말고 사람이 결정" 과 같은 ratchet 원칙.
# git diff -U0 HEAD 는 staged+unstaged 를 한 번에, 현재 워킹 파일 기준 라인번호로 준다.
_added_lines: dict[str, set[int]] = {}
if _silence_ok and py_files:
    # rename-aware(-M) + **pathspec 없이**. `-- files` 로 좁히면 -M 이 old 를 못 봐
    # rename 이 안 잡히고 파일 전체가 net-new 로 오인된다(실측). _added_lines 는
    # 아래에서 파일 키로 조회하므로 전체 diff 를 받아도 무방하다.
    _dh = _run(["git", "diff", "-M", "-U0", "HEAD"])
    if _dh.returncode == 0:
        _added_lines = _iter_added_lines(_dh.stdout)
    else:
        # 조용히 {} 로 두면 tracked 파일의 신규 침묵-except 가 전부 '레거시'로
        # 재분류돼 §7d 가 아무것도 안 잡는다 — 그런데 출력은 "0 warning" 이다.
        _add("Info", "hook", "scripts/quality_check.py",
             f"git diff 실패(rc={_dh.returncode}) — §7d 신규 침묵-except 판정 보류")

for f in py_files:
    fp = _ROOT / f
    if not fp.exists():
        continue
    content = fp.read_text(encoding="utf-8", errors="ignore")
    lines = content.splitlines()

    # 7d. 침묵 except (AST body-aware, net-new ratchet). ruff/E722 는 bare `except:`
    #     만 보고 `except Exception: pass` 를 못 본다 — 그 사각지대를 AST 로 보강.
    #     위험/정당은 구조가 동일해 구분 불가(사람 판단) → net-new 만 advisory Warning.
    if _silence_ok:
        _addset = _added_lines.get(f) or _added_lines.get(f.replace("\\", "/")) or set()
        # untracked 신규 파일은 diff 에 안 나와 _addset 이 빈다. 하지만 HEAD 에 없던
        # 파일이 '레거시' 빚을 가질 수는 없다 — 전 라인이 net-new 다. 이 분기가 없으면
        # 새 파일에 침묵 except 를 아무리 넣어도 §7d 가 한 건도 안 잡는다.
        _all_new = f.replace("\\", "/") in untracked_files
        for _ln, _reason in silent_excepts(content):
            if _all_new or _ln in _addset:
                _add("Warning", "pattern", f"{f}:{_ln}",
                     f"신규 침묵 except ({_reason}) — broad 예외를 삼킴. 예외를 좁히거나 "
                     f"로깅 추가, 의도면 `# silent-ok` 마커")

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
round_tag = f"Round {_ROUND} ({_ROUND_FOCUS.get(_ROUND, 'full')})" if _ROUND > 0 else "Single run"

# Structured result (machine-parseable) — 조기종료 경로와 **같은 빌더**를 쓴다.
# (예전엔 두 곳이 각자 dict 를 조립해 한쪽만 바뀌는 드리프트가 필연이었다)
structured = _build_structured()
_not_run = structured["not_run"]

_exit_code = 1 if critical else 0

# 사람용 문자열은 모드와 무관하게 항상 만든다. --json 이든 아니든 같은 내용을
# 캐시에 넣어야, 저장한 모드와 읽는 모드가 달라도 올바른 shape가 나온다.
result_lines = [
    f"[{round_tag}] pytest: {summary.get('pytest', '-')} | ruff: {summary.get('ruff', '-')} | vite: {summary.get('vite_build', '-')} | vitest: {summary.get('vitest', '-')}",
    f"Issues: {len(critical)} critical, {len(warnings)} warning, {len(infos)} info"
    + ("" if not _not_run else f" — ⚠ 미검증: {', '.join(f'{k}={v}' for k, v in _not_run.items())}"),
]
for issue in issues[:15]:
    result_lines.append(f"  [{issue['severity']}] {issue['category']}: {issue['file']} — {issue['message']}")

_detail = "\n".join(result_lines)

# 능동 보고 리마인더. 정책 본문은 .claude/rules/self-review.md ## 보고 방식
# (always-on @import). 모델은 이 change set을 다루는 다음 사용자 응답에
# 4구획 능동 보고를 반드시 포함해야 한다.
reminder = (
    "⚠️ 능동 보고 필수 (.claude/rules/self-review.md ## 보고 방식): 다음 응답에 "
    "(1) 변경 요약 표 (2) X1~X9 mini-checklist 표 (3) 잠재 문제 표 (있을 때) "
    "(4) 결론 1줄을 자동 포함하라. 변경 파일 수: "
    f"{summary.get('changed_files','?')} (py {summary.get('changed_py','?')}, "
    f"jsx {summary.get('changed_jsx','?')})."
)
_sys_msg = f"[Quality Check] {' | '.join(result_lines[:2])}\n{reminder}"

if _JSON_ONLY:
    print(json.dumps(structured, ensure_ascii=False))
else:
    print(json.dumps({
        "systemMessage": _sys_msg,
        "detail": _detail,
        "structured": structured,
    }, ensure_ascii=False))

# Exit code:
#   0 — no critical issues
#   1 — critical issues found (caller should fix and re-run)
sys.exit(_exit_code)
