"""ruff 를 **변경 라인만** 검사하는 ratchet 게이트 (pre-commit·CI 공용).

왜 필요한가: 저장소에 ruff 위반 backlog 가 **1072건 / 247파일**(2026-07-18 실측)
쌓여 있다. `ruff check <file>` 은 파일 **전체**를 보므로, 이 247개 중 하나라도
건드리면 무관한 레거시 위반이 터져 commit/CI 를 막는다 → 개발자는 곧 `--no-verify`
로 도망가고 게이트가 무력화된다.

그래서 이 스크립트는 **HEAD(또는 지정 base) 대비 추가/수정된 라인의 신규 위반만**
차단한다. 레거시 backlog 는 건드리는 파일이어도 통과시킨다 — silence 게이트와
같은 ratchet 원칙이고, `posttool_dispatch.py` 의 "레거시를 자동 변형 말고 사람이
결정" 과 정합한다.

판정 로직(추가 라인 계산·untracked·경로 정규화·신규/레거시 분류·rc 규약)은
`_ratchet_core.py` 에 있다 — eslint 판과 **같은 코드**를 쓴다. 여기 남은 건 ruff
고유의 두 가지뿐이다: 실행 경로(`sys.executable -m ruff` + 부재 판별)와
JSON 어댑터(flat `[{filename, location:{row}, code}]`).

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
import _ratchet_core as core  # noqa: E402  판정 로직 단일 출처
from _hook_env import module_missing as _module_missing  # noqa: E402  단일소스 판별

_ROOT = core.ROOT
_TOOL = "ruff"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    # encoding 고정 + replace — quality_check._run 과 동일 계약. git/ruff 출력은
    # UTF-8 정본인데 text=True 만이면 locale(cp949)로 오독하거나, 잔여 non-utf8
    # 바이트에 reader thread 가 죽어 stream 이 조용히 빈다 → 위반이 '레거시'로
    # 오분류돼 통과. 판정 신호는 ASCII(경로/JSON)라 replace 로도 보존된다.
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          cwd=str(_ROOT), timeout=60)


def _rel(path: str) -> str:
    """ruff 절대경로 → repo-상대. 실패는 통과가 아니라 판정 보류(core.Disabled)."""
    return core.rel(path)


def _collect(files: list[str]) -> list[core.Hit]:
    """ruff 를 돌려 위반을 공용 `Hit` 형태로. 실패는 core.Disabled 로 올린다."""
    rf = _run([sys.executable, "-m", "ruff", "check", "--output-format=json", *files])
    if _module_missing(rf):  # 단일소스 판별(_hook_env) — 3벌 정규식과 파리티
        raise core.Disabled("ruff DISABLED (미설치 — venv 확인). lint 미검증(통과 아님).")
    core.ensure_tool_ran(_TOOL, rf)
    try:
        violations = json.loads(rf.stdout or "[]")
    except json.JSONDecodeError as e:
        raise core.Disabled(
            f"ruff 출력 파싱 실패(rc={rf.returncode}): {(rf.stderr or '')[:200]}"
        ) from e
    return [
        (
            _rel(v.get("filename", "")),
            (v.get("location") or {}).get("row"),
            v.get("code") or "?",
            (v.get("message") or "").strip(),
        )
        for v in violations
    ]


def _main(argv: list[str] | None = None) -> int:
    diff_spec, args = core.parse_cli(sys.argv[1:] if argv is None else argv)
    files = [a for a in args if a.endswith(".py")]
    if not files:
        return 0

    added = core.added_lines(
        _run(core.git_diff_cmd(diff_spec)),
        _run(core.git_untracked_cmd(files)),
    )
    new_hits, legacy = core.split_new_vs_legacy(_collect(files), added)
    return core.emit(_TOOL, new_hits, legacy, added)


def main(argv: list[str] | None = None) -> int:
    return core.run_guarded(lambda: _main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
