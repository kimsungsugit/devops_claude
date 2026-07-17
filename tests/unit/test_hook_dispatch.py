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


def test_eslint_launch_failure_is_not_stamped_clean(monkeypatch, capsys):
    """eslint 가 못 뜨면(rc≠0 + 빈 stdout) 'clean' 이 아니라 ERROR 여야 한다.

    구 코드(`(r.stdout.strip() or 'clean')`)는 여기서 'eslint: clean' 을 냈다 → FAIL.
    """
    cp = _cp(1, stdout="", stderr="npm error could not determine executable to run")
    ctx = _dispatch(monkeypatch, capsys, _JSX, cp)
    assert "eslint: ERROR" in ctx
    assert "clean" not in ctx  # 도구가 안 돌았는데 clean 으로 위장하면 안 됨


def test_eslint_clean_when_rc0(monkeypatch, capsys):
    """모두 통과(또는 --fix 로 전부 교정)면 rc=0 + 빈 stdout → 'clean' 이 맞다."""
    ctx = _dispatch(monkeypatch, capsys, _JSX, _cp(0, stdout="", stderr=""))
    assert "eslint: clean" in ctx


def test_eslint_violations_are_surfaced(monkeypatch, capsys):
    """실제 위반(rc≠0 + stdout 보고)은 그대로 노출돼야 한다(ERROR 가드에 삼켜지면 안 됨)."""
    report = "Foo.jsx\n  3:1  error  'x' is not defined  no-undef"
    ctx = _dispatch(monkeypatch, capsys, _JSX, _cp(1, stdout=report, stderr=""))
    assert "no-undef" in ctx
    assert "ERROR" not in ctx  # stdout 이 있으므로 도구 실패가 아니라 위반 보고


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
