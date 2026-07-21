"""ratchet 게이트 공용 코어 — ruff/eslint **판정 로직의 단일 출처**.

## 왜 생겼나

`eslint_ratchet.py` 는 `ruff_ratchet.py` 의 "미러"로 만들어졌는데, 미러링 도중
발견한 fail-open 을 **eslint 판에만 고쳤다**. 그래서 2026-07-21 실측 시점에 두
스크립트의 방어 수준이 갈라져 있었다 — 같은 조건(추적되지 않는 신규 파일)에서:

    ruff_ratchet.py   _ratchet_probe.py      → rc=0 "레거시 4건은 ratchet 로 제외"
    eslint_ratchet.py _ratchet_probe.jsx     → rc=1 no-unused-vars 보고

방금 만든 파일의 위반을 **'레거시'라고 부르며 통과**시킨 것이다. 문구까지 적극적
안심형이라 사용자는 "내 변경은 깨끗하다"로 읽는다. 게이트가 없는 것보다 나쁘다.

원인은 개별 버그가 아니라 **구조**다. 판정 로직이 두 벌 복제돼 있으면 한쪽에 가한
수정이 다른 쪽에 전파되지 않고, 그 격차는 조용하다(둘 다 rc=0 을 내므로 다른 게
드러나지 않는다). 세 번째 ratchet(stylelint·tsc 등)이 생기면 3벌이 된다.

그래서 **"어떤 위반이 신규인가"를 정하는 코드는 여기 하나뿐**이다. 각 모듈은
도구 호출과 JSON 어댑터만 갖는다.

## 무엇이 여기 있고 무엇이 모듈에 남나

여기(공용): CLI 파싱 · git 명령 구성 · 추가 라인 계산 · untracked 처리 ·
경로 정규화 · 도구 실패 판별 · 신규/레거시 분류 결과 보고 · rc 규약.

모듈(고유): 대상 확장자와 범위 · 도구 실행 경로(venv/node_modules) 및 부재 판별 ·
도구 JSON → `Hit` 어댑터.

subprocess 실행 자체는 **각 모듈의 `_run` 에 남겼다**. 두 테스트 스위트가 그걸
monkeypatch 해 in-process 로 검증하고 있어서, 코어가 실행까지 삼키면 그 지점이
사라진다. 코어는 "무엇을 실행할지"(명령)와 "결과를 어떻게 읽을지"(판정)만 정한다.

## rc 규약 (세 소비자가 공유)

    0 = 신규 위반 없음   1 = 신규 위반 있음   2 = DISABLED(판정 불가 — 통과 아님)

2 를 통과로 읽으면 fake-green 이다. 로컬(pre-commit)은 2 를 ⚠경고 후 허용,
CI 는 실패로 다룬다 — 의도적 비대칭(통제된 환경의 도구 부재 = 인프라 이상).
"""
from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable, Sequence
from collections.abc import Set as AbstractSet
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _silence_check import (  # noqa: E402  공용 unified-diff 파서
    _iter_added_lines,
    _unquote_diff_path,
)

ROOT = Path(__file__).resolve().parents[1]

#: 보고 한 건: (repo-상대 경로, 라인, 규칙코드, 메시지).
#: 라인은 int | None — eslint fatal parse-error 등은 라인을 안 준다.
#: split_new_vs_legacy 는 line=None 을 (라인 국소화 불가라) legacy 로 둔다.
Hit = tuple[str, int | None, str, str]


class Disabled(Exception):
    """판정 불가 — rc=2 로 올릴 사유.

    "위반 0건"과 **반드시 구분**돼야 하는 상태다. 도구 부재·git 실패·경로 해석
    실패처럼 '검사를 못 했다'는 사실을 통과로 위장하지 않기 위한 단일 통로.
    메시지는 그대로 stderr 로 나간다.
    """


class _AllLines(frozenset):
    """'이 파일의 모든 라인이 신규'를 뜻하는 sentinel 집합.

    라인 수를 세지 않고도 `line in ALL_LINES` 가 항상 참이 되게 한다.
    """

    def __contains__(self, _item: object) -> bool:
        return True


#: untracked 파일용 sentinel. HEAD 에 없던 파일은 '레거시' 위반을 가질 수 없다.
ALL_LINES = _AllLines()


def parse_cli(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """`--cached` / `--base <ref>` 를 뽑아 `(diff_spec, 나머지 인자)` 반환.

    기본은 `["HEAD"]`(working tree vs HEAD). 세 소비자가 같은 CLI 를 쓰도록
    여기서만 정의한다 — pre-commit 은 `--cached`, CI 는 `--base <ref>`,
    PostToolUse 훅은 무인자.
    """
    args = list(argv)
    diff_spec: list[str] = ["HEAD"]
    if "--cached" in args:
        args.remove("--cached")
        diff_spec = ["--cached"]
    if "--base" in args:
        i = args.index("--base")
        diff_spec = [args[i + 1]]
        del args[i:i + 2]
    return diff_spec, args


def git_diff_cmd(diff_spec: Sequence[str]) -> list[str]:
    """추가 라인 계산용 git diff 명령.

    ⚠ 두 가지가 실측으로 못박혀 있다:

    `-M` **+ pathspec 없이** — `-M` 은 old/new 를 둘 다 봐야 rename 을 감지하는데
    `-- <files>` 로 좁히면 old 가 배제돼 rename 이 안 잡히고 파일 전체가 'added' 로
    폭주한다. 도구는 files 만 검사하므로 위반은 자연히 제한되고, added 는 파일
    키로 조회된다.

    `-c core.quotepath=false` — 비ASCII 경로(한글 파일명)를 8진 이스케이프 없이
    받는다. 없으면 `+++ "b/scripts/\\355..."` 형태라 `b/` 접두사가 안 떨어지고 키가
    어긋나 **그 파일의 위반이 전부 '레거시'로 오분류돼 조용히 통과**한다.
    (남는 따옴표는 `_unquote_diff_path` 가 처리한다.)
    """
    return ["git", "-c", "core.quotepath=false", "diff", "-M", "-U0", *diff_spec]


def git_untracked_cmd(files: Sequence[str]) -> list[str]:
    """untracked 파일 조회 명령 — diff 에 안 나오는 신규 파일을 건지기 위해."""
    return ["git", "-c", "core.quotepath=false", "ls-files", "--others",
            "--exclude-standard", "--", *files]


def added_lines(
    diff_cp: subprocess.CompletedProcess,
    untracked_cp: subprocess.CompletedProcess | None = None,
) -> dict[str, AbstractSet[int]]:
    """git 결과 → `{repo-상대 경로: 신규 라인 집합}`.

    git diff 실패는 **Disabled** 로 올린다. 이걸 안 막으면 게이트가 통째로
    무력화된다 — stdout 이 비어 `added={}` 가 되고 모든 위반이 '레거시'로
    재분류돼 `rc=0` + "레거시 N건 제외" 라는 안심 문구까지 나온다. 실측:
    `--base doesnotexist99` 로 위반 7건이 있는 파일이 통과했다. 원인은 base
    오타뿐 아니라 index.lock 경합(훅이 도는 동안 다른 프로세스가 `git add`),
    detached 상태 등 일상적이다.

    `untracked_cp` 를 주면 그 목록의 파일은 **전 라인을 신규**로 본다. HEAD 에
    없던 파일이 '레거시' 위반을 가질 수는 없기 때문이다. 이게 빠지면 방금 만든
    파일이 무검사로 빠진다(실측: untracked `.py` 4위반 → rc=0 "레거시 4건 제외").
    조회 자체가 실패하면(rc≠0) 조용히 건너뛴다 — untracked 는 **보강**이지
    판정의 근간이 아니라서, 여기서 Disabled 를 올리면 tracked 파일만 다루는
    정상 흐름까지 막힌다.
    """
    if diff_cp.returncode != 0:
        raise Disabled(
            f"git diff 실패(rc={diff_cp.returncode}) — 변경 라인을 알 수 없어 판정 불가: "
            f"{(diff_cp.stderr or '').strip()[:200]}"
        )
    added: dict[str, AbstractSet[int]] = dict(_iter_added_lines(diff_cp.stdout))
    if untracked_cp is not None and untracked_cp.returncode == 0:
        for line in untracked_cp.stdout.splitlines():
            rel_path = _unquote_diff_path(line.strip())
            if rel_path:
                added[rel_path] = ALL_LINES
    return added


def rel(path: str) -> str:
    """도구가 준 절대경로를 repo-상대 forward-slash 로 (added 키와 정합).

    ⚠ 폴백으로 원본을 돌려주면 안 된다. added 키는 repo-상대인데 절대경로를
    돌려주면 영원히 miss → 그 파일의 위반이 전부 '레거시'로 분류돼 **조용히
    통과**한다. 정규화 실패는 통과가 아니라 판정 보류(Disabled)다.
    """
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except (ValueError, OSError) as e:
        raise Disabled(f"경로 정규화 실패 — 판정 보류: {path}") from e


def ensure_tool_ran(tool: str, cp: subprocess.CompletedProcess) -> None:
    """rc≠0 인데 stdout 까지 비었으면 위반 0건이 아니라 **도구 자체 실패**다.

    위반은 stdout(JSON)으로 나온다. 빈 걸 `[]` 로 읽으면 "clean" 으로 위장하는
    fail-open — 설정 오류·플러그인 부재·내부 크래시가 전부 통과가 된다.
    """
    if cp.returncode != 0 and not cp.stdout.strip():
        raise Disabled(
            f"{tool} 실행 실패(rc={cp.returncode}) — lint 미검증: "
            f"{(cp.stderr or '').strip()[:200]}"
        )


def split_new_vs_legacy(
    violations: Iterable[Hit],
    added: dict[str, AbstractSet[int]],
) -> tuple[list[Hit], int]:
    """위반을 (변경 라인에 걸린 신규, 레거시 건수)로 가른다."""
    new_hits: list[Hit] = []
    legacy = 0
    for hit in violations:
        path, line = hit[0], hit[1]
        if line is not None and line in added.get(path, frozenset()):
            new_hits.append(hit)
        else:
            legacy += 1
    return new_hits, legacy


def emit(
    tool: str,
    new_hits: Sequence[Hit],
    legacy: int,
    added: dict[str, AbstractSet[int]],
) -> int:
    """판정 결과를 출력하고 rc 를 돌려준다. 보류 사유가 있으면 Disabled."""
    if new_hits:
        print(f"{tool}: 신규 위반 {len(new_hits)}건 (변경 라인 한정):")
        for path, line, code, msg in sorted(new_hits):
            print(f"  {path}:{line}: {code} {msg}")
        return 1
    if legacy and not added:
        # ⚠ "레거시 N건 제외" 는 **적극적 안심 문구**다. added 가 통째로 비었는데
        # 위반이 있으면 그건 '남의 빚'이 아니라 변경 라인 정보를 못 얻은 것일 수
        # 있다(위 git 가드를 빠져나온 잔여 경우). 안심시키지 말고 보류로 알린다.
        raise Disabled(f"{tool}: 변경 라인 정보 없음 — 판정 보류 (위반 {legacy}건 미분류)")
    if legacy:
        print(f"{tool}: 신규 위반 0건 (레거시 {legacy}건은 ratchet 로 제외)")
    else:
        print(f"{tool}: clean")
    return 0


def run_guarded(fn) -> int:
    """`Disabled` 를 stderr + rc=2 로 변환하는 단일 통로.

    각 모듈의 `main()` 이 이걸 통해 돌면 '판정 불가'가 통과로 새는 경로가
    구조적으로 하나로 좁혀진다.
    """
    try:
        return fn()
    except Disabled as e:
        print(str(e), file=sys.stderr)
        return 2
