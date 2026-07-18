"""scripts/pretool_asil_check.py — PreToolUse ASIL C/D 수정 전 경고 훅.

계약:
1. C/H 파일을 수정하기 직전 기존 내용에 `@asil C|D` 가 있으면 경고를 push.
2. **절대 차단하지 않는다** — 경고만. 태그 없음/비-C·H/없는 파일/파싱 실패는 silent.
3. `@asil A|B|QM` 은 대상 아님(C/D 만).

각 테스트는 해당 조건을 뒤집으면 FAIL 하도록 설계됐다.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import pretool_asil_check as asil  # noqa: E402


def _run(monkeypatch, capsys, file_path: str) -> str:
    payload = {"tool_input": {"file_path": file_path}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    asil.main()
    return capsys.readouterr().out.strip()


def _cfile(tmp_path: Path, body: str, name: str = "mod.c") -> str:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_asil_d_warns(tmp_path, monkeypatch, capsys):
    f = _cfile(tmp_path, "/** @asil D */\nvoid safety(void) {}\n")
    out = _run(monkeypatch, capsys, f)
    obj = json.loads(out)
    ctx = obj["hookSpecificOutput"]["additionalContext"]
    assert obj["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "ASIL D" in ctx
    assert f in ctx


def test_asil_c_warns(tmp_path, monkeypatch, capsys):
    out = _run(monkeypatch, capsys, _cfile(tmp_path, "// @asil C\nint x;\n"))
    assert "ASIL C" in json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_asil_lowercase_is_normalized(tmp_path, monkeypatch, capsys):
    """`@asil d` (소문자)도 잡고 'ASIL D' 로 표기(re.IGNORECASE + .upper())."""
    out = _run(monkeypatch, capsys, _cfile(tmp_path, "/* @asil d */\n"))
    assert "ASIL D" in json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_header_file_also_checked(tmp_path, monkeypatch, capsys):
    out = _run(monkeypatch, capsys, _cfile(tmp_path, "/* @asil C */\n", name="drv.h"))
    assert out != ""


def test_asil_ab_qm_not_warned(tmp_path, monkeypatch, capsys):
    """A/B/QM 은 대상 아님 — silent."""
    assert _run(monkeypatch, capsys, _cfile(tmp_path, "/* @asil B */\nint x;\n")) == ""
    assert _run(monkeypatch, capsys, _cfile(tmp_path, "/* @asil QM */\n")) == ""


def test_no_tag_is_silent(tmp_path, monkeypatch, capsys):
    assert _run(monkeypatch, capsys, _cfile(tmp_path, "int plain(void){return 0;}\n")) == ""


def test_non_c_file_is_silent(tmp_path, monkeypatch, capsys):
    """확장자가 .c/.h 가 아니면 태그가 있어도 검사 안 함."""
    f = tmp_path / "notc.txt"
    f.write_text("/* @asil D */\n", encoding="utf-8")
    assert _run(monkeypatch, capsys, str(f)) == ""


def test_missing_file_is_silent(tmp_path, monkeypatch, capsys):
    assert _run(monkeypatch, capsys, str(tmp_path / "nope.c")) == ""


def test_garbage_stdin_is_silent(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("<<<not json>>>"))
    asil.main()
    assert capsys.readouterr().out.strip() == ""


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
