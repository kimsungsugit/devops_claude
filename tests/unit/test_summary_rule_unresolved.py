"""rule-unresolved-evidence — 미해소 규칙×파일 구간 증거(변경/무변경/정직 reason/counts 독립)."""
from __future__ import annotations

from pathlib import Path


def _rcr(foo_r1: int) -> str:
    """WorstRules(Rule-1.1) + FileStatus 최소 RCR — 파일 경로는 APP\\foo.c(정규화 후 APP/foo.c)."""
    return f"""<html><head><title>Helix QAC Rule Compliance Report</title></head><body>
 <div class="sec"><h3><a name="WorstRules1">Most Violated Rules</a></h3></div>
 <table border="1">
  <tr><th>Files</th><th>Rule-1.1</th></tr>
  <tr><td align="left"><a href="APP\\foo.c" title="APP\\foo.c">foo.c</a></td><td>{foo_r1}</td></tr>
 </table>
 <div class="sec"><h3><a name="FileStatus">File Status</a></h3></div>
 <table border="1">
  <tr><th>Files</th><th>Violated Rules</th><th>Violation Count</th></tr>
  <tr><td align="left"><a href="APP\\foo.c" title="APP\\foo.c">foo.c</a></td><td>1</td><td>{foo_r1}</td></tr>
 </table>
</body></html>"""


def _snap(tmp_path: Path, n: int, files: dict, *, rcr_r1: int | None = None) -> Path:
    root = tmp_path / f"build_{n}"
    (root / "report").mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        p = root / "source" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    if rcr_r1 is not None:
        (root / f"X_RCR_0101202{n % 10}.html").write_text(_rcr(rcr_r1), encoding="utf-8")
    return root


def _wire(monkeypatch, a_root: Path, b_root: Path):
    from backend.routers import summary_insight as si

    metas = [
        {"build_number": 125, "build_root": str(b_root), "reports_dir": str(b_root / "report")},
        {"build_number": 122, "build_root": str(a_root), "reports_dir": str(a_root / "report")},
    ]
    monkeypatch.setattr("backend.services.build_inventory.list_cached_builds_meta", lambda **k: metas)
    return si


_BODY = {"job_url": "http://j/", "rule": "Rule-1.1", "file": "APP/foo.c",
         "from_build": 122, "to_build": 125}


def test_changed_file_evidence_with_counts(tmp_path, monkeypatch):
    a = _snap(tmp_path, 122, {"APP/foo.c": "int x = 42;\n"}, rcr_r1=6)
    b = _snap(tmp_path, 125, {"APP/foo.c": "int x = X_INIT;\n"}, rcr_r1=6)
    si = _wire(monkeypatch, a, b)
    r = si.summary_rule_unresolved_evidence(dict(_BODY))
    assert r["available"] is True and r["file_changed"] is True
    assert "-int x = 42;" in r["diff"]["text"]
    assert r["counts"] == {"from": 6, "to": 6}          # RCR 카운트 조인(파일 경로 키 일치)
    assert "인과" in r["note"]                            # 서버 고정 note 상시


def test_unchanged_file_is_valid_evidence_not_failure(tmp_path, monkeypatch):
    # 무변경은 실패가 아니라 유효 증거 — '위반 잔존 + 구간 내 파일 미수정' 관측.
    a = _snap(tmp_path, 122, {"APP/foo.c": "same\n"}, rcr_r1=6)
    b = _snap(tmp_path, 125, {"APP/foo.c": "same\n"}, rcr_r1=6)
    si = _wire(monkeypatch, a, b)
    r = si.summary_rule_unresolved_evidence(dict(_BODY))
    assert r["available"] is True and r["file_changed"] is False and r["diff"] is None
    assert r["counts"] == {"from": 6, "to": 6}


def test_counts_independent_of_missing_rcr(tmp_path, monkeypatch):
    # RCR 없음 → counts는 None(0 위장 금지) + counts_reason, diff 증거는 독립 반환.
    a = _snap(tmp_path, 122, {"APP/foo.c": "a\n"})
    b = _snap(tmp_path, 125, {"APP/foo.c": "b\n"})
    si = _wire(monkeypatch, a, b)
    r = si.summary_rule_unresolved_evidence(dict(_BODY))
    assert r["available"] is True and r["file_changed"] is True
    assert r["counts"] == {"from": None, "to": None} and r["counts_reason"] == "no_rcr"


def test_honest_failure_reasons(tmp_path, monkeypatch):
    a = _snap(tmp_path, 122, {"APP/foo.c": "a\n"})
    b = _snap(tmp_path, 125, {"APP/foo.c": "b\n"})
    si = _wire(monkeypatch, a, b)
    # 스냅샷에 없는 파일
    r = si.summary_rule_unresolved_evidence({**_BODY, "file": "ghost.c"})
    assert r["available"] is False and r["reason"] == "file_not_in_snapshot"
    assert r["file_changed"] is None and r["diff"] is None
    # 캐시에 없는 빌드 / 파라미터 누락
    r2 = si.summary_rule_unresolved_evidence({**_BODY, "to_build": 999})
    assert r2["available"] is False and r2["reason"] == "build_not_cached"
    r3 = si.summary_rule_unresolved_evidence({"job_url": "http://j/"})
    assert r3["available"] is False and r3["reason"] == "params_required"


def test_ambiguous_basename_honest(tmp_path, monkeypatch):
    a = _snap(tmp_path, 122, {"APP/config.c": "a\n", "BOOT/config.c": "b\n"})
    b = _snap(tmp_path, 125, {"APP/config.c": "a2\n", "BOOT/config.c": "b\n"})
    si = _wire(monkeypatch, a, b)
    r = si.summary_rule_unresolved_evidence({**_BODY, "file": "config.c"})
    assert r["available"] is False and r["reason"] == "file_ambiguous_in_snapshot"
