"""eslint 를 **변경 라인만** 검사하는 ratchet 게이트 (훅·pre-commit·CI 공용).

`ruff_ratchet.py` 의 JS 판이다. 구조·CLI·종료코드 규약을 의도적으로 동일하게 맞췄다 —
소비자(pre-commit / ci.yml)가 두 언어에 같은 분기 로직을 쓸 수 있어야 하기 때문.

왜 필요한가: frontend-v2 는 74파일 / 31,818줄이 **한 번도 린트된 적이 없다**(config 도
의존성도 없어 PostToolUse 훅의 `npx eslint` 가 매번 ERROR 만 냈다). 게이트를 켜는 순간
error 101 / warning 36 (2026-07-20 실측) 이 드러나는데, `eslint <file>` 은 파일 **전체**를
보므로 그 파일을 건드리기만 해도 무관한 레거시가 터져 commit 을 막는다 → `--no-verify`
도피 → 게이트 무력화. ruff 가 1072건 backlog 로 겪은 그대로다.

그래서 **HEAD(또는 지정 base) 대비 추가/수정된 라인의 신규 위반만** 차단한다.

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
from collections.abc import Set as AbstractSet
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_env import project_eslint  # noqa: E402  npx 우회 + 부재 판별 단일소스
from _silence_check import (  # noqa: E402  공용 unified-diff 파서
    _iter_added_lines,
    _unquote_diff_path,
)


class _AllLines(frozenset):
    """'이 파일의 모든 라인이 신규' 를 뜻하는 sentinel 집합(untracked 파일용).

    라인 수를 세지 않고도 `line in _ALL_LINES` 가 항상 참이 되게 한다.
    """

    def __contains__(self, _item: object) -> bool:
        return True


_ALL_LINES = _AllLines()

_ROOT = Path(__file__).resolve().parents[1]
_FRONTEND = _ROOT / "frontend-v2"
# ⚠ eslint.config.js 의 `files: ['**/*.{js,jsx}']` 와 **반드시 같은 범위**여야 한다.
# 여기만 ts/tsx 를 받으면 config 가 없는 파일이 eslint 로 넘어가 severity 1
# "File ignored because no matching configuration was supplied" 로 조용히 통과한다
# — 4곳(여기·pre-commit·ci.yml·gitlab)이 "ts/tsx 도 검사한다"고 선언하면서 실제론
# 무검사인 상태였다. TS 를 도입하려면 config 와 이 목록을 **함께** 늘릴 것.
_EXTS = (".js", ".jsx")


class _PathOutsideRepo(Exception):
    """eslint 가 repo 밖(또는 해석 불가) 경로를 보고했다 — 판정 보류 사유."""


def _rel(path: str) -> str:
    """eslint 가 준 절대경로를 repo-상대 forward-slash 로 (added-lines 키와 정합).

    ⚠ 폴백으로 원본을 돌려주면 안 된다. added 키는 repo-상대인데 절대경로를 돌려주면
    영원히 miss → 그 파일의 위반이 전부 '레거시'로 분류돼 **조용히 통과**한다.
    정규화에 실패하면 통과가 아니라 판정 보류(rc=2)로 올린다.
    """
    try:
        return Path(path).resolve().relative_to(_ROOT).as_posix()
    except (ValueError, OSError) as e:
        raise _PathOutsideRepo(path) from e


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd), timeout=120)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    diff_spec: list[str] = ["HEAD"]
    if "--cached" in args:
        args.remove("--cached")
        diff_spec = ["--cached"]
    if "--base" in args:
        i = args.index("--base")
        diff_spec = [args[i + 1]]
        del args[i:i + 2]
    # frontend-v2 밖의 JS(예: scripts/ 하위 도구)는 이 config 범위가 아니다.
    files = [a for a in args if a.endswith(_EXTS) and "frontend-v2" in a.replace("\\", "/")]
    if not files:
        return 0

    # 1) 신규(추가/수정)된 라인 집합. rename-aware(-M) + **pathspec 없이**.
    #    -M 은 old/new 를 둘 다 봐야 rename 을 감지하는데 `-- files` 로 좁히면 old 가
    #    배제돼 rename 이 안 잡혀 파일 전체가 'added' 로 폭주한다(ruff_ratchet 실측).
    #    eslint 는 files 만 검사하므로 위반은 자연히 제한되고, added 는 파일 키로 조회된다.
    #    `-c core.quotepath=false` — 한글 등 비ASCII 경로를 8진 이스케이프 없이 받는다
    #    (남는 따옴표는 _unquote_diff_path 가 처리).
    dh = _run(["git", "-c", "core.quotepath=false", "diff", "-M", "-U0", *diff_spec], cwd=_ROOT)
    if dh.returncode != 0:
        # ⚠ 여기를 안 막으면 게이트가 통째로 무력화된다. git 이 실패하면 stdout 이 비고
        # → added={} → 모든 위반이 '레거시'로 재분류 → **rc=0 + "레거시 N건 제외"** 라는
        # 적극적 안심 문구까지 출력된다. 실측: `--base doesnotexist99` 로 위반 7건이 있는
        # 파일이 통과했다. 원인은 base 오타·index.lock 경합(훅이 7초 도는 동안 다른
        # 프로세스가 git add)·detached 상태 등 다양하다.
        print(
            f"git diff 실패(rc={dh.returncode}) — 변경 라인을 알 수 없어 판정 불가: "
            f"{(dh.stderr or '').strip()[:200]}",
            file=sys.stderr,
        )
        return 2
    # 값 타입이 set[int] | _AllLines 라 명시 annotation 을 둔다(untracked sentinel).
    added: dict[str, AbstractSet[int]] = dict(_iter_added_lines(dh.stdout))

    # untracked 파일은 diff 에 안 나와 added 가 비는데, HEAD 에 없던 파일이 '레거시'
    # 위반을 가질 수는 없다. 전 라인을 신규로 본다(PostToolUse 워킹트리 모드에서
    # 에이전트가 막 만든 .jsx 가 무검사로 빠지던 경로).
    un = _run(["git", "-c", "core.quotepath=false", "ls-files", "--others",
               "--exclude-standard", "--", *files], cwd=_ROOT)
    if un.returncode == 0:
        for line in un.stdout.splitlines():
            rel = _unquote_diff_path(line.strip())
            if rel:
                added[rel] = _ALL_LINES

    # 2) eslint 위반 (JSON). npx 가 아니라 로컬 바이너리를 직접 부른다.
    eslint = project_eslint()
    if eslint is None:
        print(
            "eslint DISABLED (frontend-v2/node_modules 에 없음 — `npm ci` 확인). "
            "lint 미검증(통과 아님).",
            file=sys.stderr,
        )
        return 2
    # eslint 는 파일 경로를 cwd 기준으로 받는다. repo-상대 경로를 절대경로로 넘겨 모호성 제거.
    abs_files = [str((_ROOT / f).resolve()) for f in files]
    rf = _run([eslint, "--format", "json", "--no-error-on-unmatched-pattern", *abs_files], cwd=_FRONTEND)
    if rf.returncode != 0 and not rf.stdout.strip():
        # eslint 위반은 stdout(JSON)으로 나온다. rc≠0인데 stdout까지 비었으면 위반 0건이
        # 아니라 eslint **자체 실패**(flat-config 오류·plugin 부재·크래시)다. 빈 걸 []로
        # 읽으면 "clean"으로 위장하는 fail-open — ruff_ratchet 과 동일하게 fail-closed.
        print(
            f"eslint 실행 실패(rc={rf.returncode}) — lint 미검증: {(rf.stderr or '').strip()[:200]}",
            file=sys.stderr,
        )
        return 2
    try:
        results = json.loads(rf.stdout or "[]")
    except json.JSONDecodeError:
        print(f"eslint 출력 파싱 실패(rc={rf.returncode}): {(rf.stderr or '')[:200]}", file=sys.stderr)
        return 2

    # 3) 추가 라인에 걸린 위반만 남긴다 (net-new ratchet).
    #    severity 는 구분하지 않고 **둘 다 차단**한다. 실측 warning 36건이 36/36
    #    `react-hooks/exhaustive-deps` 인데, 그건 이 프로젝트가 미니 체크리스트 #6 으로
    #    매 리뷰 의무화한 X2(stale closure) 그 자체다. 영구 비차단이면 유일한 자동 X2
    #    검사가 아무것도 막지 않는 셈이라, ratchet(레거시 면제) 위에서는 막는 게 맞다.
    new_hits = []
    legacy = 0
    for f in results:
        try:
            rel = _rel(f.get("filePath", ""))
        except _PathOutsideRepo as e:
            print(f"경로 정규화 실패 — 판정 보류: {e}", file=sys.stderr)
            return 2
        rows = added.get(rel, set())
        for m in f.get("messages") or []:
            line = m.get("line")
            if line is not None and line in rows:
                sev = "error" if m.get("severity") == 2 else "warn"
                new_hits.append((rel, line, m.get("ruleId") or "(parse)",
                                 f"[{sev}] {(m.get('message') or '').strip()}"))
            else:
                legacy += 1

    if not new_hits:
        if legacy and not added:
            # ⚠ "레거시 N건 제외" 는 **적극적 안심 문구**다. added 가 통째로 비었는데
            # 위반이 있으면 그건 '남의 빚'이 아니라 변경 라인 정보를 못 얻은 것일 수
            # 있다(위 git 가드를 빠져나온 잔여 경우). 안심시키지 말고 보류로 알린다.
            print(f"eslint: 변경 라인 정보 없음 — 판정 보류 (위반 {legacy}건 미분류)", file=sys.stderr)
            return 2
        if legacy:
            print(f"eslint: 신규 위반 0건 (레거시 {legacy}건은 ratchet 로 제외)")
        else:
            print("eslint: clean")
        return 0

    print(f"eslint: 신규 위반 {len(new_hits)}건 (변경 라인 한정):")
    for rel, row, rule, msg in sorted(new_hits):
        print(f"  {rel}:{row}: {rule} {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
