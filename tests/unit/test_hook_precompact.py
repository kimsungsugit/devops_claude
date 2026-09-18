"""scripts/precompact_context.py — PreCompact git 상태 보존 훅.

계약:
1. 압축 직전 `git status --porcelain` + `git diff --stat` 을
   `.codex_tmp/precompact_context.json` 에 보존.
2. systemMessage 로 요약을 출력.
3. git 호출 실패는 조용히 "" — 압축을 막지 않는다.

⚠ main() 은 CWD 상대(`.codex_tmp/`)로 쓴다. conftest 의 `tmp_path` 는
`<repo>/.codex_tmp/pytest-<uuid>/` 이므로 **monkeypatch.chdir(tmp_path)** 로
격리하지 않으면 실제 `.codex_tmp/precompact_context.json` 을 덮어쓴다.
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

import precompact_context as pc  # noqa: E402


def _fake_run(stdout: str):
    def _run(*_a, **_k):
        return subprocess.CompletedProcess(["git"], 0, stdout, "")
    return _run


def test_preserves_git_status_to_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pc.subprocess, "run", _fake_run("M scripts/x.py\n"))
    pc.main()

    out = tmp_path / ".codex_tmp" / "precompact_context.json"
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["git_status"] == "M scripts/x.py\n"
    assert "git_diff_stat" in data

    msg = json.loads(capsys.readouterr().out.strip())["systemMessage"]
    assert "PreCompact" in msg
    assert "scripts/x.py" in msg  # status 앞부분 에코


def test_git_failure_is_swallowed(tmp_path, monkeypatch, capsys):
    """git 이 죽어도(_git → "") 파일은 쓰이고 압축은 진행된다."""
    monkeypatch.chdir(tmp_path)

    def _boom(*_a, **_k):
        raise OSError("git not found")

    monkeypatch.setattr(pc.subprocess, "run", _boom)
    pc.main()

    data = json.loads((tmp_path / ".codex_tmp" / "precompact_context.json").read_text(encoding="utf-8"))
    assert data["git_status"] == ""
    assert data["git_diff_stat"] == ""
    assert "PreCompact" in json.loads(capsys.readouterr().out.strip())["systemMessage"]


def test_status_is_capped(tmp_path, monkeypatch):
    """거대한 status 는 _CAP(500) 로 잘려 systemMessage 가 비대해지지 않는다."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pc.subprocess, "run", _fake_run("X " * 5000))
    pc.main()
    data = json.loads((tmp_path / ".codex_tmp" / "precompact_context.json").read_text(encoding="utf-8"))
    assert len(data["git_status"]) <= pc._CAP


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
