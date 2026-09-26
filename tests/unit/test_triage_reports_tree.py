"""`reports/` 분류 규칙이 실제로 **가르는지** (R44 N13).

사용자 결정: *"식별 규칙부터 만들어 보고"*. 그래서 이 스크립트는 세기만 하고 지우지
않는다 — 이 가드는 ① 지우는 코드가 없다는 것, ② 서명을 못 읽으면 **판정하지 않는다**는
것, ③ 판정이 실제로 두 갈래를 만든다는 것을 고정한다.

⚠ 첫 판의 규칙(파일명 앞부분을 scm_id 로 해석)은 **83%를 '미상'** 으로 만들어 아무것도
못 갈랐다. 내용 서명 축이 들어오자 갈렸다.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "triage_reports_tree.py"


def _load():
    spec = importlib.util.spec_from_file_location("triage_reports_tree", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["triage_reports_tree"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_script_never_deletes() -> None:
    """분류는 판정이 아니라 보고다 — 삭제 호출이 하나라도 있으면 실패."""
    tree = ast.parse(SCRIPT.read_text("utf-8"))
    banned = {"rmtree", "unlink", "remove", "rmdir", "removedirs", "move", "rename"}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in banned:
                found.append((name, node.lineno))
    assert found == [], f"분류 스크립트가 파일을 건드린다: {found}"


def test_no_signatures_means_no_verdict(monkeypatch, capsys) -> None:
    """서명을 못 읽으면 **판정하지 않는다**.

    빈 서명으로 계속 돌면 모든 디렉터리가 '테스트 산물' 로 보인다 — 그 상태로 사람이
    지우면 실물이 사라진다. 미측정을 판정으로 바꾸지 않는 것이 이 저장소의 규약이다.
    """
    mod = _load()
    monkeypatch.setattr(mod, "_real_signatures", lambda: ([], []))
    monkeypatch.setattr(sys, "argv", ["triage", "--sample", "1"])
    rc = mod.main()
    out = capsys.readouterr().out
    assert rc == 1, "서명이 없는데 정상 종료했다"
    assert "판정하지 않습니다" in out


def test_signatures_come_from_the_registry_not_a_literal() -> None:
    """실물 id 를 코드에 적어 두면 프로젝트가 늘 때 반드시 빠진다."""
    src = SCRIPT.read_text("utf-8")
    assert "scm_registry.json" in src
    for hardcoded in ("kjpds02", "hdpdm01"):
        assert hardcoded not in src.lower(), f"실물 id 가 하드코딩돼 있다: {hardcoded}"


def test_verdict_splits_by_signature_ratio(monkeypatch, tmp_path: Path, capsys) -> None:
    """규칙이 실제로 **두 갈래를 만든다** — 서명 있는 트리와 없는 트리를 다르게 부른다."""
    mod = _load()
    reports = tmp_path / "reports"
    real = reports / "with_sig"
    fake = reports / "without_sig"
    real.mkdir(parents=True)
    fake.mkdir(parents=True)
    for i in range(5):
        (real / f"r{i}.json").write_text('{"scm_id": "myproj"}', encoding="utf-8")
        (fake / f"f{i}.json").write_text('{"scm_id": "fixture-xyz"}', encoding="utf-8")

    monkeypatch.setattr(mod, "REPORTS", reports)
    monkeypatch.setattr(mod, "_real_signatures", lambda: (["myproj"], []))
    monkeypatch.setattr(mod, "LIVE_DAYS", 10_000)      # 방금 만든 파일 = 활동중
    monkeypatch.setattr(sys, "argv", ["triage", "--sample", "0"])
    assert mod.main() == 0
    out = capsys.readouterr().out

    # ⚠ 두 표가 같은 이름으로 시작한다(활동 표 · 서명 표) — 판정 열이 있는 줄만 본다.
    verdict_lines = [ln for ln in out.splitlines() if "유력" in ln or "혼재" in ln]
    with_sig = next(ln for ln in verdict_lines if ln.startswith("with_sig"))
    without_sig = next(ln for ln in verdict_lines if ln.startswith("without_sig"))
    assert "실물 유력" in with_sig, with_sig
    assert "테스트 산물 유력" in without_sig, without_sig


def test_it_runs_on_the_real_tree_without_crashing(monkeypatch, capsys) -> None:
    """실제 트리에서 **실제로 돈다** — 판정 내용은 데이터에 달렸으므로 단언하지 않는다.

    ⚠ (리뷰 W8) 첫 판은 이름과 달리 `main()` 을 부르지 않고 `_real_signatures()` 만 봤다.
    레지스트리가 없어 `([], [])` 가 와도 통과하는 vacuous 단언이었다.
    """
    if not (ROOT / "reports").is_dir():
        pytest.skip("reports/ 없음")
    mod = _load()
    if not any(mod._real_signatures()):
        pytest.skip("레지스트리 서명 없음 — 이 환경에선 판정이 성립하지 않는다")
    monkeypatch.setattr(sys, "argv", ["triage", "--sample", "3"])
    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "활동중" in out and "삭제는 사람의 판단" in out


def test_binary_files_are_not_counted_as_missing_signature(monkeypatch, tmp_path, capsys) -> None:
    """(리뷰 C1) 판독 불가는 **'서명 없음' 이 아니라 '판정 불가'** 다.

    PNG 를 `errors="ignore"` 로 읽으면 서명은 절대 안 맞는데, 그 파일이 분모에 들어가면
    비율이 눌려 실물 트리가 '테스트 산물' 로 보인다. 실측에서 `uds_local` 2,192개(PNG 78%)가
    그렇게 뒤집혔고, 그 표를 보고 지웠다면 실물이 사라졌다.
    """
    mod = _load()
    reports = tmp_path / "reports"
    d = reports / "mostly_binary"
    d.mkdir(parents=True)
    for i in range(40):
        # 진짜 PNG 시그니처(NUL 포함) — 텍스트로는 판독할 수 없는 파일.
        sig = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
        (d / f"img{i}.png").write_bytes(sig + bytes(64))
    for i in range(2):
        (d / f"r{i}.json").write_text('{"scm_id": "myproj"}', encoding="utf-8")

    monkeypatch.setattr(mod, "REPORTS", reports)
    monkeypatch.setattr(mod, "_real_signatures", lambda: (["myproj"], []))
    monkeypatch.setattr(mod, "LIVE_DAYS", 10_000)
    monkeypatch.setattr(sys, "argv", ["triage", "--sample", "0"])
    assert mod.main() == 0
    out = capsys.readouterr().out

    line = next(ln for ln in out.splitlines()
                if ln.startswith("mostly_binary") and ("유력" in ln or "혼재" in ln or "불가" in ln))
    assert "테스트 산물 유력" not in line, f"이진이 분모를 채워 판정을 뒤집었다: {line}"
    assert "실물 유력" in line, line
