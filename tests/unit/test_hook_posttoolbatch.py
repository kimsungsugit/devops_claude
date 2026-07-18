"""scripts/posttoolbatch_report.py — PostToolBatch 일괄 보고 훅.

계약:
1. 단일 파일 turn 은 silent (PostToolUse 가 이미 파일별 보고) — **단 ASIL C/H 는 예외**.
2. 2개+ 변경이면 X1~X9 능동보고 trigger + 확장자 집계를 push.
3. ASIL(c/h) 파일은 file_list 앞으로 정렬 → truncation(>8) 에도 hint 누락 방지.
4. payload shape 가 불안정하므로 다중 키(tool_calls/tools/batch/operations/tool_uses)
   + 휴리스틱으로 tool entry 를 뽑는다.

아래 각 테스트는 해당 분기를 뒤집으면 FAIL 하도록 설계됐다(진짜 회귀 게이트).
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

import posttoolbatch_report as pb  # noqa: E402


def _entry(tool: str, path: str) -> dict:
    return {"tool_name": tool, "tool_input": {"file_path": path}}


# ── _classify ──────────────────────────────────────────────────────────────

def test_classify_extensions():
    assert pb._classify("a/b.py") == "py"
    assert pb._classify("x.jsx") == "jsx"
    assert pb._classify("frontend-v2/src/x.js") == "js"
    assert pb._classify("x.js") == "other"  # frontend-v2 밖의 .js
    assert pb._classify("README.md") == "md"
    assert pb._classify("mod.c") == "c"
    assert pb._classify("mod.h") == "c"
    assert pb._classify("config.json") == "json"
    assert pb._classify("Makefile") == "other"
    assert pb._classify("a\\b\\win.py") == "py"  # 백슬래시 정규화


# ── _build_report ──────────────────────────────────────────────────────────

def test_single_non_asil_file_is_silent():
    """계약 1: 단일 비-ASIL 파일 → None. `len(files) < 2` 분기를 지우면 FAIL."""
    assert pb._build_report([_entry("Write", "a.py")]) is None


def test_single_asil_file_is_reported():
    """계약 1 예외: 단일 c/h 파일은 hint 를 띄운다."""
    msg = pb._build_report([_entry("Write", "safety.c")])
    assert msg is not None
    assert "ASIL" in msg


def test_two_files_emit_checklist():
    """계약 2: 2개+ → X1~X9 trigger + 집계."""
    msg = pb._build_report([_entry("Write", "a.py"), _entry("Edit", "b.jsx")])
    assert msg is not None
    assert "X1~X9" in msg
    assert "py:1" in msg and "jsx:1" in msg
    assert "2 file(s)" in msg


def test_non_write_tools_are_ignored():
    """Bash/Read 등 비-Write 도구는 파일 집계에서 빠진다 → 단독 Write 1개면 silent."""
    entries = [_entry("Write", "a.py"), _entry("Bash", ""), {"tool_name": "Read", "tool_input": {"file_path": "z.py"}}]
    assert pb._build_report(entries) is None


def test_asil_sorted_first_under_truncation():
    """계약 3: 9개 파일(c 1개 포함) — c 가 file_list 맨 앞, truncation 표기 존재."""
    entries = [_entry("Write", f"m{i}.py") for i in range(8)] + [_entry("Write", "safety.c")]
    msg = pb._build_report(entries)
    assert msg is not None
    files_part = msg.split("files:", 1)[1]
    assert files_part.lstrip().startswith("safety.c")  # ASIL 최우선
    assert "more)" in msg  # 8개 초과 truncation


def test_asil_hint_present_for_c():
    msg = pb._build_report([_entry("Write", "a.py"), _entry("Write", "drv.c")])
    assert "ASIL 태그 확인" in msg


# ── _extract_tool_entries (shape 불안정성 방어) ────────────────────────────

@pytest.mark.parametrize("key", ["tool_calls", "tools", "batch", "operations", "tool_uses"])
def test_extract_known_keys(key):
    payload = {key: [_entry("Write", "a.py")]}
    assert pb._extract_tool_entries(payload) == [_entry("Write", "a.py")]


def test_extract_heuristic_fallback():
    """알려진 키가 없어도 tool_name 을 가진 dict 리스트면 찾아낸다."""
    payload = {"weird_key": [{"tool_name": "Write", "tool_input": {"file_path": "a.py"}}]}
    assert pb._extract_tool_entries(payload)[0]["tool_name"] == "Write"


def test_extract_empty_payload():
    assert pb._extract_tool_entries({}) == []


def test_entry_file_key_variants():
    assert pb._entry_file({"tool_input": {"file_path": "a"}}) == "a"
    assert pb._entry_file({"input": {"notebook_path": "n"}}) == "n"
    assert pb._entry_file({"tool_response": {"filePath": "r"}}) == "r"
    assert pb._entry_file({}) == ""


# ── main() (stdin → stdout 계약) ───────────────────────────────────────────

def _run_main(monkeypatch, capsys, payload: dict) -> str:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    pb.main()
    return capsys.readouterr().out.strip()


def test_main_emits_schema_for_batch(monkeypatch, capsys):
    out = _run_main(monkeypatch, capsys, {"tool_calls": [_entry("Write", "a.py"), _entry("Edit", "b.py")]})
    obj = json.loads(out)
    assert obj["hookSpecificOutput"]["hookEventName"] == "PostToolBatch"
    assert "X1~X9" in obj["hookSpecificOutput"]["additionalContext"]


def test_main_silent_for_single_file(monkeypatch, capsys):
    assert _run_main(monkeypatch, capsys, {"tool_calls": [_entry("Write", "only.py")]}) == ""


def test_main_silent_on_garbage(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    pb.main()
    assert capsys.readouterr().out.strip() == ""


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
