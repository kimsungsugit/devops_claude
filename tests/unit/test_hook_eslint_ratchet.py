"""scripts/eslint_ratchet.py — 변경 라인만 검사하는 eslint ratchet 게이트.

핵심 계약은 ruff 판(`test_hook_ruff_ratchet.py`)과 같다: **추가된 라인의 신규 위반만**
차단하고 **레거시는 통과**시킨다. 두 방향이 다 맞아야 게이트가 ① 무력(전부 통과)하지도
② 폭주(레거시까지 차단)하지도 않는다.

eslint 고유 계약이 셋 더 있다:
  - severity 는 구분하지 않고 **둘 다 차단** — warning 36건이 36/36 exhaustive-deps
    (= 이 프로젝트가 매 리뷰 의무화한 X2)이라 영구 비차단이면 규칙이 꺼진 것과 같다
  - eslint 부재·git 실패는 rc=2(DISABLED). **빈 출력을 clean 으로 읽으면 fake-green**
  - frontend-v2 밖의 JS 는 이 config 범위가 아니라 대상에서 제외

subprocess(git diff, eslint)는 fake 로 갈아끼워 in-process 로 검증한다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import eslint_ratchet  # noqa: E402

_F = "frontend-v2/src/x.jsx"


def _cp(stdout: str = "", stderr: str = "", rc: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["x"], rc, stdout, stderr)


def _fake_run(diff_out: str, eslint_out: str, eslint_rc: int = 1, eslint_err: str = ""):
    """git diff / eslint 호출을 명령으로 구분해 canned 결과를 돌려주는 fake."""
    def _run(cmd, cwd=None):
        if cmd and cmd[0] == "git":
            return _cp(stdout=diff_out)
        return _cp(stdout=eslint_out, stderr=eslint_err, rc=eslint_rc)
    return _run


def _abs(rel: str) -> str:
    return str((_ROOT / rel).resolve())


def _eslint_json(*msgs: tuple[str, int, int], fname: str = _F) -> str:
    """(ruleId, line, severity) 들을 eslint --format json 형태로.

    json.dumps 로 Windows 경로 백슬래시를 올바로 이스케이프한다(수기 포매팅은 JSON 을 깬다).
    """
    return json.dumps([{
        "filePath": _abs(fname),
        "messages": [
            {"ruleId": r, "line": ln, "severity": sv, "message": f"{r} 위반"}
            for r, ln, sv in msgs
        ],
    }])


def _patch_ok(monkeypatch, diff: str, eslint_out: str, rc: int = 1, err: str = "") -> None:
    monkeypatch.setattr(eslint_ratchet, "_run", _fake_run(diff, eslint_out, rc, err))
    monkeypatch.setattr(eslint_ratchet, "project_eslint", lambda: "/fake/eslint")


# ── ratchet 본질: 신규만 차단, 레거시는 통과 ──────────────────────────────

def test_new_violation_flagged_legacy_excluded(monkeypatch, capsys):
    """라인 3 = 추가됨(신규), 라인 10 = 레거시. 신규만 잡고 rc=1."""
    diff = f"--- a/{_F}\n+++ b/{_F}\n@@ -3,0 +3,1 @@\n+const x = 1;\n"
    _patch_ok(monkeypatch, diff, _eslint_json(("no-unused-vars", 3, 2), ("no-empty", 10, 2)))
    rc = eslint_ratchet.main([_F])
    out = capsys.readouterr().out
    assert rc == 1
    assert "no-unused-vars" in out       # 신규는 보고
    assert "no-empty" not in out         # 레거시는 침묵


def test_legacy_only_passes(monkeypatch, capsys):
    """변경 라인에 위반이 없으면 레거시가 아무리 많아도 rc=0.

    이게 안 되면 개발자는 곧 --no-verify 로 도망가고 게이트가 통째로 무력화된다.
    """
    diff = f"--- a/{_F}\n+++ b/{_F}\n@@ -3,0 +3,1 @@\n+// 주석만 추가\n"
    _patch_ok(monkeypatch, diff, _eslint_json(("no-empty", 10, 2), ("no-empty", 99, 2)))
    rc = eslint_ratchet.main([_F])
    out = capsys.readouterr().out
    assert rc == 0
    assert "레거시 2건" in out           # 숨기지 않고 몇 건인지 알린다


# ── DISABLED(rc=2): 빈 출력을 clean 으로 읽지 않는다 ──────────────────────

def test_eslint_missing_is_disabled_not_clean(monkeypatch, capsys):
    """eslint 바이너리 부재 → rc=2. 0(통과)이면 fake-green 회귀다."""
    monkeypatch.setattr(eslint_ratchet, "project_eslint", lambda: None)
    rc = eslint_ratchet.main([_F])
    err = capsys.readouterr().err
    assert rc == 2
    assert "DISABLED" in err


def test_eslint_crash_is_disabled_not_clean(monkeypatch, capsys):
    """rc≠0 + 빈 stdout = 위반 0건이 아니라 eslint 자체 실패(flat-config 오류 등)."""
    diff = f"--- a/{_F}\n+++ b/{_F}\n@@ -3,0 +3,1 @@\n+const x = 1;\n"
    _patch_ok(monkeypatch, diff, "", rc=2, err="Cannot find module 'eslint-plugin-x'")
    rc = eslint_ratchet.main([_F])
    err = capsys.readouterr().err
    assert rc == 2
    assert "실행 실패" in err


def test_unparsable_output_is_disabled(monkeypatch, capsys):
    diff = f"--- a/{_F}\n+++ b/{_F}\n@@ -3,0 +3,1 @@\n+const x = 1;\n"
    _patch_ok(monkeypatch, diff, "not json at all", rc=1)
    rc = eslint_ratchet.main([_F])
    assert rc == 2
    assert "파싱 실패" in capsys.readouterr().err


# ── 대상 파일 선별 ────────────────────────────────────────────────────────

def test_non_js_files_are_noop(monkeypatch):
    """대상 확장자가 없으면 eslint 를 아예 부르지 않는다(rc=0)."""
    called = {"n": 0}

    def _boom(cmd, cwd=None):
        called["n"] += 1
        return _cp()

    monkeypatch.setattr(eslint_ratchet, "_run", _boom)
    assert eslint_ratchet.main(["README.md", "scripts/x.py"]) == 0
    assert called["n"] == 0


def test_js_outside_frontend_is_excluded(monkeypatch):
    """frontend-v2 밖의 JS 는 이 flat config 범위가 아니라 대상에서 뺀다."""
    called = {"n": 0}

    def _boom(cmd, cwd=None):
        called["n"] += 1
        return _cp()

    monkeypatch.setattr(eslint_ratchet, "_run", _boom)
    assert eslint_ratchet.main(["tools/helper.js", "_archive/frontend/src/a.jsx"]) == 0
    assert called["n"] == 0


# ── diff spec 전달 ────────────────────────────────────────────────────────

def test_cached_and_base_reach_git_diff(monkeypatch):
    """--cached / --base 가 git diff 인자로 전달되는지. 틀리면 비교 기준이 어긋나
    '신규'를 잘못 계산한다(레거시를 신규로 잡거나 그 반대)."""
    seen: list[list[str]] = []

    def _run(cmd, cwd=None):
        seen.append(list(cmd))
        if cmd and cmd[0] == "git":
            return _cp(stdout="")
        return _cp(stdout="[]", rc=0)

    monkeypatch.setattr(eslint_ratchet, "_run", _run)
    monkeypatch.setattr(eslint_ratchet, "project_eslint", lambda: "/fake/eslint")

    eslint_ratchet.main(["--cached", _F])
    assert seen[0] == ["git", "-c", "core.quotepath=false", "diff", "-M", "-U0", "--cached"]

    seen.clear()
    eslint_ratchet.main(["--base", "origin/main", _F])
    assert seen[0] == ["git", "-c", "core.quotepath=false", "diff", "-M", "-U0", "origin/main"]


def test_git_diff_has_no_pathspec(monkeypatch):
    """`-- <files>` pathspec 을 붙이면 -M 이 rename 의 old 를 못 봐 파일 전체가
    'added' 로 폭주한다(ruff_ratchet 이 실측으로 남긴 함정). 그래서 붙이지 않는다."""
    seen: list[list[str]] = []

    def _run(cmd, cwd=None):
        seen.append(list(cmd))
        if cmd and cmd[0] == "git":
            return _cp(stdout="")
        return _cp(stdout="[]", rc=0)

    monkeypatch.setattr(eslint_ratchet, "_run", _run)
    monkeypatch.setattr(eslint_ratchet, "project_eslint", lambda: "/fake/eslint")
    eslint_ratchet.main([_F])
    assert "--" not in seen[0]
    assert _F not in seen[0]


# ── fail-open 방어 (deep-review 에서 **실측 재현된** 3건) ─────────────────
# 셋 다 "위반이 있는데 rc=0" 이었다. 게이트가 없는 것보다 나쁜 이유는 그때
# `"신규 위반 0건 (레거시 N건은 ratchet 로 제외)"` 라는 **적극적 안심 문구**를
# 출력했기 때문이다 — 사용자는 "내 변경은 깨끗하다"로 읽는다.

def test_git_diff_failure_is_disabled_not_clean(monkeypatch, capsys):
    """git diff 가 실패하면 rc=2. 0이면 게이트 전면 무력화다.

    실측: `--base doesnotexist99` 로 위반 7건이 있는 파일이 통과했다. git 이 실패하면
    stdout 이 비어 added={} 가 되고 **모든 위반이 '레거시'로 재분류**된다. 원인은
    base 오타뿐 아니라 index.lock 경합(훅이 수 초 도는 동안 다른 프로세스가 git add)
    처럼 일상적인 것도 있다.
    """
    def _run(cmd, cwd=None):
        if cmd and cmd[0] == "git":
            return _cp(stdout="", stderr="fatal: unknown revision", rc=128)
        return _cp(stdout=_eslint_json(("no-unused-vars", 3, 2)), rc=1)

    monkeypatch.setattr(eslint_ratchet, "_run", _run)
    monkeypatch.setattr(eslint_ratchet, "project_eslint", lambda: "/fake/eslint")
    rc = eslint_ratchet.main([_F])
    assert rc == 2
    assert "git diff 실패" in capsys.readouterr().err


def test_quoted_path_in_diff_matches_violation(monkeypatch, capsys):
    """git 이 따옴표+8진 이스케이프로 낸 경로도 위반과 조인돼야 한다.

    `core.quotepath` 기본값 때문에 한글 파일명은 `+++ "b/…/\355\225\234…"` 로 나온다.
    파서가 이걸 못 풀면 키가 어긋나 그 파일의 위반이 전부 '레거시'가 된다 — 한글
    파일명 하나로 게이트가 통째로 무력화됐다(실측 재현).
    """
    kor = "frontend-v2/src/한글Probe.jsx"
    octal = "".join(f"\\{b:03o}" for b in "한글Probe".encode())
    diff = (f'--- /dev/null\n+++ "b/frontend-v2/src/{octal}.jsx"\n'
            "@@ -0,0 +1,1 @@\n+var x = 1;\n")
    monkeypatch.setattr(eslint_ratchet, "_run",
                        _fake_run(diff, _eslint_json(("no-unused-vars", 1, 2), fname=kor)))
    monkeypatch.setattr(eslint_ratchet, "project_eslint", lambda: "/fake/eslint")
    rc = eslint_ratchet.main([kor])
    out = capsys.readouterr().out
    assert rc == 1, "따옴표 경로가 조인되지 않아 위반이 '레거시'로 샜다"
    assert "no-unused-vars" in out


def test_untracked_file_violations_are_new_not_legacy(monkeypatch, capsys):
    """untracked 신규 파일의 위반은 전부 '신규'다 — HEAD 에 없던 파일이 레거시 빚을
    가질 수 없다. PostToolUse 워킹트리 모드(에이전트가 막 만든 .jsx)의 주 경로다."""
    def _run(cmd, cwd=None):
        if cmd and cmd[0] == "git" and "ls-files" in cmd:
            return _cp(stdout=f"{_F}\n")
        if cmd and cmd[0] == "git":
            return _cp(stdout="")            # diff 는 비어 있다(untracked)
        return _cp(stdout=_eslint_json(("no-unused-vars", 1, 2), ("no-empty", 9, 2)), rc=1)

    monkeypatch.setattr(eslint_ratchet, "_run", _run)
    monkeypatch.setattr(eslint_ratchet, "project_eslint", lambda: "/fake/eslint")
    rc = eslint_ratchet.main([_F])
    out = capsys.readouterr().out
    assert rc == 1
    assert "no-unused-vars" in out and "no-empty" in out


def test_rel_fallback_is_fail_closed(monkeypatch, capsys):
    """repo 밖 경로를 정규화 못 하면 통과가 아니라 판정 보류(rc=2).

    예전 폴백은 절대경로를 그대로 돌려줘 added 키와 영원히 miss → 그 파일 위반이
    전부 '레거시' → 조용히 통과했다.
    """
    diff = f"--- a/{_F}\n+++ b/{_F}\n@@ -1,0 +1,1 @@\n+var x = 1;\n"
    outside = json.dumps([{
        "filePath": "/somewhere/else/x.jsx",
        "messages": [{"ruleId": "no-unused-vars", "line": 1, "severity": 2, "message": "m"}],
    }])
    monkeypatch.setattr(eslint_ratchet, "_run", _fake_run(diff, outside))
    monkeypatch.setattr(eslint_ratchet, "project_eslint", lambda: "/fake/eslint")
    assert eslint_ratchet.main([_F]) == 2
    assert "판정 보류" in capsys.readouterr().err


def test_warning_on_changed_line_now_blocks(monkeypatch, capsys):
    """severity 1 도 변경 라인이면 차단한다.

    실측 warning 36건이 36/36 `react-hooks/exhaustive-deps` 인데, 그건 이 프로젝트가
    미니 체크리스트 #6 으로 매 리뷰 의무화한 X2(stale closure) 그 자체다. 영구 비차단이면
    유일한 자동 X2 검사가 아무것도 막지 않는다.
    """
    diff = f"--- a/{_F}\n+++ b/{_F}\n@@ -3,0 +3,1 @@\n+  }}, []);\n"
    monkeypatch.setattr(eslint_ratchet, "_run",
                        _fake_run(diff, _eslint_json(("react-hooks/exhaustive-deps", 3, 1))))
    monkeypatch.setattr(eslint_ratchet, "project_eslint", lambda: "/fake/eslint")
    rc = eslint_ratchet.main([_F])
    out = capsys.readouterr().out
    assert rc == 1
    assert "exhaustive-deps" in out and "[warn]" in out
