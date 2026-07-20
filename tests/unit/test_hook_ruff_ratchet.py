"""scripts/ruff_ratchet.py — 변경 라인만 검사하는 ruff ratchet 게이트.

핵심 계약: 저장소 ruff backlog(1072건/247파일)에 익사하지 않도록 **추가된 라인의
신규 위반만** 차단하고 **레거시는 통과**시킨다. 이 두 방향이 다 맞아야 게이트가
① 무력(전부 통과)하지도 ② 폭주(레거시까지 차단)하지도 않는다.

subprocess(git diff, ruff)는 fake 로 갈아끼워 in-process 로 검증한다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import ruff_ratchet  # noqa: E402


def _cp(stdout: str = "", stderr: str = "", rc: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["x"], rc, stdout, stderr)


def _fake_run(diff_out: str, ruff_out: str, ruff_rc: int = 1, ruff_err: str = ""):
    """git diff / ruff 호출을 명령으로 구분해 canned 결과를 돌려주는 fake."""
    def _run(cmd):
        if cmd and cmd[0] == "git":
            return _cp(stdout=diff_out)
        return _cp(stdout=ruff_out, stderr=ruff_err, rc=ruff_rc)
    return _run


def _abs(rel: str) -> str:
    return str((_ROOT / rel).resolve())


def _ruff_json(*viols: tuple[str, str, int], fname: str = "x.py") -> str:
    """(code, msg, row) 들을 ruff --output-format=json 형태로. json.dumps 로
    Windows 경로 백슬래시를 올바로 이스케이프(수기 문자열 포매팅은 JSON 을 깬다)."""
    return json.dumps([
        {"filename": _abs(fname), "code": c, "message": m, "location": {"row": r}}
        for c, m, r in viols
    ])


def test_new_violation_flagged_legacy_excluded(monkeypatch, capsys):
    """라인 3 = 추가됨(신규), 라인 10 = 레거시. 신규만 잡고 rc=1."""
    diff = "--- a/x.py\n+++ b/x.py\n@@ -3,0 +3,1 @@\n+import os\n"
    ruff_json = _ruff_json(("F401", "os unused", 3), ("E711", "legacy", 10))
    monkeypatch.setattr(ruff_ratchet, "_run", _fake_run(diff, ruff_json))
    rc = ruff_ratchet.main(["x.py"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "F401" in out           # 신규 위반은 보고
    assert "E711" not in out       # 레거시는 제외
    assert ":3:" in out and ":10:" not in out


def test_rename_does_not_flag_legacy(monkeypatch, capsys):
    """C1 회귀: `git mv old new` + 소규모 편집 시 파일 전체가 아니라 실제 추가 라인만
    net-new. rename 감지(-M, pathspec 없음)가 빠지면 diff 가 `@@ -0,0 +1,N @@`로 전체를
    added 로 잡아 레거시(라인 3)까지 차단 → FAIL. 여기선 rename diff 를 주입해 라인
    7만 net-new 로 봐야 함을 잠근다."""
    diff = (
        "diff --git a/old.py b/new.py\n"
        "similarity index 85%\nrename from old.py\nrename to new.py\n"
        "--- a/old.py\n+++ b/new.py\n@@ -6,0 +7,2 @@\n+def d():\n+    return 4\n"
    )
    ruff_json = _ruff_json(("E711", "legacy", 3), ("F401", "new unused", 7), fname="new.py")
    monkeypatch.setattr(ruff_ratchet, "_run", _fake_run(diff, ruff_json))
    rc = ruff_ratchet.main(["new.py"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "F401" in out and ":7:" in out    # 신규(추가 라인)만
    assert "E711" not in out and ":3:" not in out  # 레거시(리네임 원본)는 제외


def test_all_legacy_passes(monkeypatch, capsys):
    """변경 라인에 위반이 하나도 없으면 레거시가 많아도 통과(rc=0)."""
    diff = "--- a/x.py\n+++ b/x.py\n@@ -3,0 +3,1 @@\n+x = 1\n"
    ruff_json = _ruff_json(("E711", "legacy", 10))
    monkeypatch.setattr(ruff_ratchet, "_run", _fake_run(diff, ruff_json))
    rc = ruff_ratchet.main(["x.py"])
    assert rc == 0
    assert "레거시" in capsys.readouterr().out  # 제외됐음을 명시


def test_clean_returns_zero(monkeypatch):
    monkeypatch.setattr(ruff_ratchet, "_run", _fake_run("", "[]", ruff_rc=0))
    assert ruff_ratchet.main(["x.py"]) == 0


def test_ruff_missing_is_disabled_not_pass(monkeypatch):
    """ruff 미설치(rc≠0 + 'No module named ruff')는 DISABLED(2), 통과(0) 아님."""
    err = "C:/msys64/mingw64/bin/python.exe: No module named ruff"
    monkeypatch.setattr(ruff_ratchet, "_run", _fake_run("", "", ruff_rc=1, ruff_err=err))
    assert ruff_ratchet.main(["x.py"]) == 2


def test_ruff_crash_is_not_fake_clean(monkeypatch, capsys):
    """C2 회귀: ruff 가 module-missing 이 **아닌** 이유로 실패(설정 오류 등, rc≠0 +
    빈 stdout)하면 fail-open('clean', 0)이 아니라 DISABLED(2) 여야 한다.
    이 가드를 제거하면(빈 stdout→[]→clean) FAIL — fake-green 재도입 방지."""
    err = "ruff.toml: TOML parse error: key with no value, expected `=`"
    monkeypatch.setattr(ruff_ratchet, "_run", _fake_run("", "", ruff_rc=2, ruff_err=err))
    rc = ruff_ratchet.main(["x.py"])
    assert rc == 2
    assert "clean" not in capsys.readouterr().out


def test_no_py_files_is_noop(monkeypatch):
    """대상 .py 가 없으면 subprocess 도 안 부르고 0."""
    def _boom(cmd):
        raise AssertionError("should not run subprocess")
    monkeypatch.setattr(ruff_ratchet, "_run", _boom)
    assert ruff_ratchet.main(["README.md"]) == 0


def test_cached_and_base_flags_parsed(monkeypatch):
    """--cached / --base 가 파싱되고 파일 인자와 분리되는지. git diff 는 rename 감지를
    위해 **pathspec 없이**(-M + spec) 돌고, 파일은 ruff 쪽으로 간다."""
    seen = {}

    def _capture(cmd):
        if cmd[0] == "git":
            seen["diff"] = cmd
            return _cp(stdout="")
        seen["ruff"] = cmd
        return _cp(stdout="[]", rc=0)

    monkeypatch.setattr(ruff_ratchet, "_run", _capture)
    ruff_ratchet.main(["--base", "HEAD~1", "a.py"])
    assert "HEAD~1" in seen["diff"] and "-M" in seen["diff"]
    assert "a.py" not in seen["diff"]   # pathspec 아님 (rename 감지 유지)
    assert "a.py" in seen["ruff"]       # 파일은 ruff 로
    seen.clear()
    monkeypatch.setattr(ruff_ratchet, "_run", _capture)
    ruff_ratchet.main(["--cached", "a.py"])
    assert "--cached" in seen["diff"] and "-M" in seen["diff"]


def test_rel_normalizes_abs_to_repo_relative():
    assert ruff_ratchet._rel(_abs("scripts/x.py")) == "scripts/x.py"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


# ── fail-open 방어 (deep-review 실측 재현, eslint 판과 동일 결함) ─────────
# 이 두 결함은 eslint_ratchet 을 이 파일의 미러로 만들면서 **복제된 채 발견**됐다.
# 둘 다 "위반이 있는데 rc=0" 이고, 그때 `"레거시 N건은 ratchet 로 제외"` 라는
# 적극적 안심 문구까지 출력해 사용자가 "내 변경은 깨끗하다"로 읽게 만든다.

def test_git_diff_failure_is_disabled_not_clean(monkeypatch, capsys):
    """git diff 실패는 rc=2. 0이면 게이트 전면 무력화다.

    실측: 잘못된 `--base` 로 실재하는 위반이 통과했다. git 이 실패하면 stdout 이 비어
    added={} 가 되고 모든 위반이 '레거시'로 재분류된다. base 오타뿐 아니라
    index.lock 경합(훅이 도는 동안 다른 프로세스가 git add)처럼 일상적 원인도 있다.
    """
    def _run(cmd):
        if cmd and cmd[0] == "git":
            return _cp(stdout="", stderr="fatal: unknown revision", rc=128)
        return _cp(stdout=_ruff_json(("F401", "unused", 3)), rc=1)

    monkeypatch.setattr(ruff_ratchet, "_run", _run)
    rc = ruff_ratchet.main(["x.py"])
    assert rc == 2
    assert "git diff 실패" in capsys.readouterr().err


def test_quoted_path_in_diff_matches_violation(monkeypatch, capsys):
    """따옴표+8진 이스케이프 경로(한글 파일명)도 위반과 조인돼야 한다.

    `core.quotepath` 기본값 탓에 비ASCII 경로는 `+++ "b/…"` 로 나온다. 파서가 못 풀면
    키가 어긋나 그 파일 위반이 전부 '레거시'가 된다 — 한글 파일명 하나로 게이트가
    무력화됐다(실측 재현).
    """
    kor = "scripts/한글probe.py"
    octal = "".join(f"\\{b:03o}" for b in "한글probe".encode())
    diff = (f'--- /dev/null\n+++ "b/scripts/{octal}.py"\n'
            "@@ -0,0 +1,1 @@\n+import os\n")
    monkeypatch.setattr(ruff_ratchet, "_run",
                        _fake_run(diff, _ruff_json(("F401", "os unused", 1), fname=kor)))
    rc = ruff_ratchet.main([kor])
    out = capsys.readouterr().out
    assert rc == 1, "따옴표 경로가 조인되지 않아 위반이 '레거시'로 샜다"
    assert "F401" in out
