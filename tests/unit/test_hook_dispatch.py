"""scripts/posttool_dispatch.py — PostToolUse 통합 dispatcher 의 anti-fake-green 계약.

핵심 계약(형제 분기 전부 동일):
  도구(ruff/pytest/eslint)가 **실행 자체에 실패**하면(미설치·config 오류·plugin 부재)
  rc≠0 + 빈 stdout 이 된다. 이 조합을 '위반 없음(clean)'으로 읽으면 fake-green 이다.
  위반은 도구가 stdout 으로 보고하므로, rc≠0 인데 stdout 이 비었다는 것은
  '통과'가 아니라 '도구가 안 돌았다'는 뜻 → ERROR/DISABLED 로 표면화해야 한다.

배경 — 왜 이 테스트가 있나:
ruff/pytest 분기는 폴백 통일(67623fd) 때 가드를 받았는데 **eslint 분기만
`(stdout or "clean")` 옛 관용구로 남아** eslint 가 안 떠도 "eslint: clean" 을
찍고 있었다(감사가 posttool_dispatch.py:140 에서 발견). 이 파일은 그 분기와
형제 분기가 **rc 가드를 실제로 쓰는지** end-to-end 로 고정한다. 아래 각 테스트는
가드를 제거하면(구 코드로 되돌리면) FAIL 하도록 설계됐다(= 진짜 회귀 게이트).
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import posttool_dispatch  # noqa: E402


def _cp(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _fixed_run(cp: subprocess.CompletedProcess):
    """subprocess.run 자리에 꽂아 고정된 CompletedProcess 를 돌려주는 fake."""
    def _run(*_a, **_k):
        return cp
    return _run


def _dispatch(monkeypatch, capsys, file_path: str, cp: subprocess.CompletedProcess) -> str:
    """dispatcher 를 in-process 로 1회 실행하고 additionalContext 문자열을 돌려준다.

    subprocess.run 은 fake 로, stdin 은 payload 로 갈아끼운다. 출력이 없으면 "".
    """
    monkeypatch.setattr(posttool_dispatch.subprocess, "run", _fixed_run(cp))
    payload = json.dumps({"tool_input": {"file_path": file_path}})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    posttool_dispatch.main()
    out = capsys.readouterr().out.strip()
    if not out:
        return ""
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


# ── eslint 분기 (수정 대상) ────────────────────────────────────────────────

_JSX = "frontend-v2/src/components/Foo.jsx"


# JS 분기는 이제 eslint 를 직접 부르지 않고 scripts/eslint_ratchet.py 를 부른다
# (변경 라인 한정 + --fix 제거). 계약이 rc 0/1/2 로 바뀌었으므로 아래 세 테스트도
# 그 규약을 검증한다 — 다만 **지켜야 할 속성은 그대로**다: 도구가 안 돌았을 때
# 'clean' 으로 위장하지 않는 것.

def test_eslint_disabled_is_not_stamped_clean(monkeypatch, capsys):
    """ratchet 이 rc=2(DISABLED)면 'clean' 이 아니라 DISABLED 여야 한다.

    rc=2 는 eslint 미설치(node_modules 부재)·flat-config 오류·크래시다. 이걸 통과로
    읽으면 lint 가 통째로 죽은 채 초록불이 켜진다 — 이 저장소가 ruff/pytest 에서
    이미 겪은 fake-green 이다.
    """
    cp = _cp(2, stdout="", stderr="eslint DISABLED (frontend-v2/node_modules 에 없음)")
    ctx = _dispatch(monkeypatch, capsys, _JSX, cp)
    assert "eslint: DISABLED" in ctx
    assert "clean" not in ctx


def test_eslint_clean_when_rc0(monkeypatch, capsys):
    """신규 위반 0건이면 ratchet 이 rc=0 + 'eslint: clean' 을 stdout 으로 낸다."""
    ctx = _dispatch(monkeypatch, capsys, _JSX, _cp(0, stdout="eslint: clean", stderr=""))
    assert "eslint: clean" in ctx


def test_eslint_new_violations_are_surfaced(monkeypatch, capsys):
    """변경 라인의 신규 위반(rc=1)은 규칙명·위치까지 그대로 노출돼야 한다."""
    report = ("eslint: 신규 위반 1건 (변경 라인 한정):\n"
              "  frontend-v2/src/components/Foo.jsx:3: no-undef 'x' is not defined")
    ctx = _dispatch(monkeypatch, capsys, _JSX, _cp(1, stdout=report, stderr=""))
    assert "no-undef" in ctx
    assert "DISABLED" not in ctx   # 위반 보고이지 도구 실패가 아니다


def test_eslint_legacy_only_reports_ratchet_exclusion(monkeypatch, capsys):
    """레거시만 있으면 통과시키되 **몇 건을 제외했는지 밝힌다**.

    조용히 통과시키면 backlog 가 있는지조차 모르게 된다.
    """
    out = "eslint: 신규 위반 0건 (레거시 16건은 ratchet 로 제외)"
    ctx = _dispatch(monkeypatch, capsys, _JSX, _cp(0, stdout=out, stderr=""))
    assert "레거시 16건" in ctx


# ── ruff 분기 (형제 계약 end-to-end 잠금) ──────────────────────────────────
# 실재 .py 파일이라야 syntax 체크(ast.parse)가 통과하고 ruff subprocess 로 넘어간다.
# dispatcher 자기 자신을 대상으로 쓴다(workflow/report_gen 스코프 밖 → auto-test 미발동).
_REAL_PY = str(_SCRIPTS / "posttool_dispatch.py")


def test_ruff_launch_failure_is_not_stamped_clean(monkeypatch, capsys):
    cp = _cp(2, stdout="", stderr="ruff: some internal error")
    ctx = _dispatch(monkeypatch, capsys, _REAL_PY, cp)
    assert "ruff: ERROR" in ctx


def test_ruff_missing_reports_disabled_not_clean(monkeypatch, capsys):
    """ruff 미설치(runpy 형식 stderr)는 DISABLED 로 표면화(침묵 green 아님)."""
    cp = _cp(1, stdout="", stderr="C:/msys64/mingw64/bin/python.exe: No module named ruff")
    ctx = _dispatch(monkeypatch, capsys, _REAL_PY, cp)
    assert "ruff: DISABLED" in ctx


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
