"""eslint 를 **변경 라인만** 검사하는 ratchet 게이트 (훅·pre-commit·CI 공용).

`ruff_ratchet.py` 의 JS 판이다. 판정 로직은 `_ratchet_core.py` 로 **공유**한다 —
예전엔 이 파일이 ruff 판의 복제였고, 미러링 중 발견한 fail-open 을 여기만 고쳐
두 게이트의 방어 수준이 갈라졌다(코어 모듈 docstring 의 실측 참조).

왜 ratchet 인가: frontend-v2 는 74파일 / 31,818줄이 **한 번도 린트된 적이 없다**
(config 도 의존성도 없어 PostToolUse 훅의 `npx eslint` 가 매번 ERROR 만 냈다).
게이트를 켜는 순간 error 101 / warning 36 (2026-07-20 실측) 이 드러나는데,
`eslint <file>` 은 파일 **전체**를 보므로 그 파일을 건드리기만 해도 무관한 레거시가
터져 commit 을 막는다 → `--no-verify` 도피 → 게이트 무력화. ruff 가 1072건
backlog 로 겪은 그대로다.

여기 남은 건 eslint 고유의 세 가지다: 대상 범위(frontend-v2 의 js/jsx),
실행 경로(node_modules 직접 해석 — npx 우회), JSON 어댑터(중첩
`[{filePath, messages:[{line, ruleId, severity}]}]`).

사용:
    eslint_ratchet.py --cached <f.jsx> ...      # pre-commit (staged vs HEAD)
    eslint_ratchet.py --base HEAD~1 <f.jsx> ... # CI (base 대비)
    eslint_ratchet.py <f.jsx> ...               # working tree vs HEAD

exit 0 = 신규 위반 없음 / 1 = 신규 위반 있음 / 2 = eslint 미설치·자체실패(DISABLED — 통과 아님)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ratchet_core as core  # noqa: E402  판정 로직 단일 출처
from _hook_env import project_eslint  # noqa: E402  npx 우회 + 부재 판별 단일소스

_ROOT = core.ROOT
_FRONTEND = _ROOT / "frontend-v2"
_TOOL = "eslint"

# ⚠ eslint.config.js 의 `files: ['**/*.{js,jsx}']` 와 **반드시 같은 범위**여야 한다.
# 여기만 ts/tsx 를 받으면 config 가 없는 파일이 eslint 로 넘어가 severity 1
# "File ignored because no matching configuration was supplied" 로 조용히 통과한다
# — 4곳(여기·pre-commit·ci.yml·gitlab)이 "ts/tsx 도 검사한다"고 선언하면서 실제론
# 무검사인 상태였다. TS 를 도입하려면 config 와 이 목록을 **함께** 늘릴 것.
_EXTS = (".js", ".jsx")


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    # encoding 고정 + replace — ruff_ratchet._run / quality_check._run 과 동일.
    # git/eslint 출력은 UTF-8 정본. text=True 만이면 cp949 로케일 오독 또는 잔여
    # non-utf8 바이트에 reader thread 사망 → 빈 stream → 위반 '레거시' 오분류.
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          cwd=str(cwd), timeout=120)


def _collect(files: list[str]) -> list[core.Hit]:
    """eslint 를 돌려 위반을 공용 `Hit` 형태로. 실패는 core.Disabled 로 올린다.

    severity 는 구분하지 않고 **둘 다 보고**한다. 실측 warning 36건이 36/36
    `react-hooks/exhaustive-deps` 인데, 그건 이 프로젝트가 미니 체크리스트 #6 으로
    매 리뷰 의무화한 X2(stale closure) 그 자체다. 영구 비차단이면 유일한 자동 X2
    검사가 아무것도 막지 않는 셈이라, ratchet(레거시 면제) 위에서는 막는 게 맞다.
    """
    eslint = project_eslint()  # npx 가 아니라 로컬 바이너리를 직접 부른다
    if eslint is None:
        raise core.Disabled(
            "eslint DISABLED (frontend-v2/node_modules 에 없음 — `npm ci` 확인). "
            "lint 미검증(통과 아님)."
        )
    # eslint 는 파일 경로를 cwd 기준으로 받는다. 절대경로로 넘겨 모호성 제거.
    abs_files = [str((_ROOT / f).resolve()) for f in files]
    rf = _run(
        [eslint, "--format", "json", "--no-error-on-unmatched-pattern", *abs_files],
        cwd=_FRONTEND,
    )
    core.ensure_tool_ran(_TOOL, rf)
    try:
        results = json.loads(rf.stdout or "[]")
    except json.JSONDecodeError as e:
        raise core.Disabled(
            f"eslint 출력 파싱 실패(rc={rf.returncode}): {(rf.stderr or '')[:200]}"
        ) from e
    hits: list[core.Hit] = []
    for f in results:
        path = core.rel(f.get("filePath", ""))
        for m in f.get("messages") or []:
            sev = "error" if m.get("severity") == 2 else "warn"
            hits.append((
                path,
                m.get("line"),
                m.get("ruleId") or "(parse)",
                f"[{sev}] {(m.get('message') or '').strip()}",
            ))
    return hits


def _main(argv: list[str] | None = None) -> int:
    diff_spec, args = core.parse_cli(sys.argv[1:] if argv is None else argv)
    # frontend-v2 밖의 JS(예: scripts/ 하위 도구)는 이 config 범위가 아니다.
    files = [a for a in args if a.endswith(_EXTS) and "frontend-v2" in a.replace("\\", "/")]
    if not files:
        return 0

    added = core.added_lines(
        _run(core.git_diff_cmd(diff_spec), cwd=_ROOT),
        _run(core.git_untracked_cmd(files), cwd=_ROOT),
    )
    new_hits, legacy = core.split_new_vs_legacy(_collect(files), added)
    return core.emit(_TOOL, new_hits, legacy, added)


def main(argv: list[str] | None = None) -> int:
    return core.run_guarded(lambda: _main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
