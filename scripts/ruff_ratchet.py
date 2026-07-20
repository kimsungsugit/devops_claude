"""ruff 를 **변경 라인만** 검사하는 ratchet 게이트 (pre-commit·CI 공용).

왜 필요한가: 저장소에 ruff 위반 backlog 가 **1072건 / 247파일**(2026-07-18 실측)
쌓여 있다. `ruff check <file>` 은 파일 **전체**를 보므로, 이 247개 중 하나라도
건드리면 무관한 레거시 위반이 터져 commit/CI 를 막는다 → 개발자는 곧 `--no-verify`
로 도망가고 게이트가 무력화된다.

그래서 이 스크립트는 **HEAD(또는 지정 base) 대비 추가/수정된 라인의 신규 위반만**
차단한다. 레거시 backlog 는 건드리는 파일이어도 통과시킨다 — silence 게이트와
같은 ratchet 원칙이고, `posttool_dispatch.py` 의 "레거시를 자동 변형 말고 사람이
결정" 과 정합한다.

사용:
    ruff_ratchet.py --cached <file.py> ...      # pre-commit (staged vs HEAD)
    ruff_ratchet.py --base HEAD~1 <file.py> ... # CI (직전 커밋 대비)
    ruff_ratchet.py <file.py> ...               # working tree vs HEAD

exit 0 = 신규 위반 없음 / 1 = 신규 위반 있음 / 2 = ruff 미설치(DISABLED — 통과 아님)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_env import module_missing as _module_missing  # noqa: E402  단일소스 판별
from _silence_check import _iter_added_lines  # noqa: E402  공용 unified-diff 파서

_ROOT = Path(__file__).resolve().parents[1]


def _rel(path: str) -> str:
    """ruff 가 준 절대경로를 repo-상대 forward-slash 로 (added-lines 키와 정합)."""
    try:
        return Path(path).resolve().relative_to(_ROOT).as_posix()
    except (ValueError, OSError):
        return path.replace("\\", "/")


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(_ROOT), timeout=60)


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
    files = [a for a in args if a.endswith(".py")]
    if not files:
        return 0

    # 1) 신규(추가/수정)된 라인 집합. rename-aware(-M) + **pathspec 없이**.
    #    -M 은 old/new 를 둘 다 봐야 rename 을 감지하는데 `-- files` 로 좁히면 old 가
    #    배제돼 rename 이 안 잡혀 파일 전체가 'added' 로 폭주한다(실측). ruff 는 files
    #    만 검사하므로 위반은 자연히 files 로 제한되고, added 는 파일 키로 조회된다.
    #    `-c core.quotepath=false` — 비ASCII 경로(한글 파일명)를 8진 이스케이프 없이 받는다.
    #    이게 없으면 `+++ "b/scripts/\355..."` 형태라 `b/` 접두사가 안 떨어지고 키가 어긋나
    #    그 파일의 위반이 전부 '레거시'로 오분류돼 **조용히 통과**한다(실측 재현).
    dh = _run(["git", "-c", "core.quotepath=false", "diff", "-M", "-U0", *diff_spec])
    if dh.returncode != 0:
        # ⚠ git 실패를 안 막으면 게이트가 통째로 무력화된다. stdout 이 비어 added={} 가
        # 되고 모든 위반이 '레거시'로 재분류돼 rc=0 + "레거시 N건 제외" 라는 안심 문구까지
        # 나온다. 원인: base 오타(`--base` 오입력), index.lock 경합, detached 상태 등.
        print(
            f"git diff 실패(rc={dh.returncode}) — 변경 라인을 알 수 없어 판정 불가: "
            f"{(dh.stderr or '').strip()[:200]}",
            file=sys.stderr,
        )
        return 2
    added = _iter_added_lines(dh.stdout)  # {repo-rel path: {line, ...}}

    # 2) ruff 위반 (JSON)
    rf = _run([sys.executable, "-m", "ruff", "check", "--output-format=json", *files])
    if _module_missing(rf):  # 단일소스 판별(_hook_env) — 3벌 정규식과 파리티
        print("ruff DISABLED (미설치 — venv 확인). lint 미검증(통과 아님).", file=sys.stderr)
        return 2
    if rf.returncode != 0 and not rf.stdout.strip():
        # ruff 위반은 stdout(JSON)으로 나온다. rc≠0인데 stdout까지 비었으면 위반
        # 0건이 아니라 ruff **자체 실패**(설정 오류·내부 크래시)다. 빈 걸 []로 읽으면
        # "clean"으로 위장하는 fail-open — quality_check.py §3 이 이미 막는 패턴을
        # 그대로 이식해 fail-closed(DISABLED) 로 표면화한다.
        print(f"ruff 실행 실패(rc={rf.returncode}) — lint 미검증: {(rf.stderr or '').strip()[:200]}", file=sys.stderr)
        return 2
    try:
        violations = json.loads(rf.stdout or "[]")
    except json.JSONDecodeError:
        print(f"ruff 출력 파싱 실패(rc={rf.returncode}): {(rf.stderr or '')[:200]}", file=sys.stderr)
        return 2

    # 3) 추가 라인에 걸린 위반만 남긴다 (net-new ratchet)
    new_hits = []
    for v in violations:
        rel = _rel(v.get("filename", ""))
        row = (v.get("location") or {}).get("row")
        if row is not None and row in added.get(rel, set()):
            new_hits.append((rel, row, v.get("code") or "?", (v.get("message") or "").strip()))

    if not new_hits:
        total = len(violations)
        if total:
            print(f"ruff: 신규 위반 0건 (레거시 {total}건은 ratchet 로 제외)")
        else:
            print("ruff: clean")
        return 0

    print(f"ruff: 신규 위반 {len(new_hits)}건 (변경 라인 한정):")
    for rel, row, code, msg in sorted(new_hits):
        print(f"  {rel}:{row}: {code} {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
