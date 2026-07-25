"""test-design 라우터 — 섹션 분리 available: 커버리지↔추적 링크 상보 상황(HDPDM01↔KJPDS02 재현)."""
from __future__ import annotations

import json
from pathlib import Path


def _mk(tmp_path: Path, *, with_coverage: bool, with_link_table: bool) -> dict:
    root = tmp_path / "build_1"
    rd = root / "report"
    rd.mkdir(parents=True)
    summary: dict = {"vectorcast_detail": {}}
    if with_coverage:
        summary["vectorcast"] = {
            "ut_metrics": {"entries": [
                {"unit": "a.c", "subprogram": "f_half", "ccn": 12,
                 "statements": {"covered": 5, "total": 10}, "branches": {"covered": 1, "total": 4}},
            ]},
            "it_metrics": {"entries": []},
        }
    (rd / "analysis_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    if with_link_table:
        (rd / "trace_link_table.json").write_text(json.dumps({"links": [
            {"related_type": "UDS_FUNCTION", "related_id": "fn_a", "target_id": "REQ-1"},
            {"related_type": "UDS_FUNCTION", "related_id": "fn_b", "target_id": "REQ-2"},
            {"related_type": "SUTS_TEST", "related_id": "SwUTC_1", "target_id": "REQ-1"},
            {"related_type": "VCAST_FUNCTION", "related_id": "fn_a (2 TC)", "target_id": "REQ-1"},
        ]}), encoding="utf-8")
    return {"build_root": str(root), "build_number": 1, "reports_dir": str(rd), "mtime": 0}


def _call(monkeypatch, meta):
    from backend.routers import summary_insight as si

    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    return si.summary_test_design({"job_url": "http://j/"})


def test_coverage_only_like_hdpdm01(tmp_path, monkeypatch):
    """커버리지만 있는 잡 — 기법 권고는 살고 설계-시험 갭은 정직 부재(no_trace_link_table)."""
    resp = _call(monkeypatch, _mk(tmp_path, with_coverage=True, with_link_table=False))
    assert resp["available"] is True
    tech = resp["technique_recommendations"]
    assert tech["available"] is True and tech["source_coverage"] == "vectorcast_metrics"
    # 스냅샷 없는 픽스처 — ASIL 소스 부재를 침묵하지 않음
    assert tech["asil_source"] == "no_source_snapshot"
    assert tech["coverage_join"] == {"entries": 1, "with_asil": 0, "asil_unknown": 1}
    assert tech["items"][0]["function"] == "f_half"
    assert resp["design_test_gap"] == {"available": False, "reason": "no_trace_link_table"}
    assert "미측정≠미달" in resp["mcdc_note"]


def test_link_table_only_like_kjpds02(tmp_path, monkeypatch):
    """추적 링크만 있는 잡 — 갭은 살고 기법 권고는 정직 부재(no_coverage_entries)."""
    resp = _call(monkeypatch, _mk(tmp_path, with_coverage=False, with_link_table=True))
    assert resp["available"] is True
    assert resp["technique_recommendations"] == {"available": False, "reason": "no_coverage_entries"}
    gap = resp["design_test_gap"]
    assert gap["available"] is True
    assert gap["totals"]["targets_with_uds"] == 2
    assert gap["targets_with_uds_no_suts"] == [{"target_id": "REQ-2", "uds_count": 1}]


def test_no_cached_build(monkeypatch):
    from backend.routers import summary_insight as si

    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [])
    resp = si.summary_test_design({"job_url": "http://j/"})
    assert resp["available"] is False and resp["reason"] == "no_cached_build"
