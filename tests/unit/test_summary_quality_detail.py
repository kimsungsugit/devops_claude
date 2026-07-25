"""quality-detail — 함수단위 커버리지 worst 정렬·미커버·섹션별 available 분리."""
from __future__ import annotations

import json
from pathlib import Path


def _prep(tmp_path: Path, *, detail: bool = True, rag: bool = True) -> dict:
    root = tmp_path / "build_125"
    rd = root / "report"
    rd.mkdir(parents=True)
    summary: dict = {}
    if detail:
        summary["vectorcast_detail"] = {
            "aggregate_coverage": {
                "ok": True,
                "entries": [
                    {"unit": "u1", "subprogram": "full_fn", "ccn": 3,
                     "statements": {"covered": 10, "total": 10, "rate": 100.0},
                     "branches": {"covered": 4, "total": 4, "rate": 100.0}},
                    {"unit": "u1", "subprogram": "half_fn", "ccn": 8,
                     "statements": {"covered": 5, "total": 10, "rate": 50.0},
                     "branches": {"covered": 1, "total": 6, "rate": 16.7}},
                    {"unit": "u2", "subprogram": "zero_fn", "ccn": 22,
                     "statements": {"covered": 0, "total": 40, "rate": 0.0},
                     "branches": {"covered": 0, "total": 18, "rate": 0.0}},
                ],
            }
        }
    (rd / "analysis_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    if rag:
        (rd / "vectorcast_rag.json").write_text(json.dumps({
            "failures": [{"testcase": "TC_zero_1", "result": "FAIL"}],
        }), encoding="utf-8")
    return {"build_root": str(root), "build_number": 125, "reports_dir": str(rd), "mtime": 0}


def test_quality_detail_worst_sorted_and_totals(tmp_path, monkeypatch):
    from backend.routers import summary_insight as si

    meta = _prep(tmp_path)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    resp = si.summary_quality_detail({"job_url": "http://j/"})
    assert resp["available"] is True and resp["build_number"] == 125
    fc = resp["function_coverage"]
    assert fc["available"] is True
    assert fc["totals"]["functions"] == 3
    assert fc["totals"]["fully_covered"] == 1
    assert fc["totals"]["uncovered"] == 1
    assert fc["totals"]["statements"] == {"covered": 15, "total": 60, "rate": 25.0}
    # worst는 rate 오름차순 — zero_fn 먼저
    assert [w["subprogram"] for w in fc["worst"]] == ["zero_fn", "half_fn", "full_fn"]
    assert fc["uncovered"] == [{"unit": "u2", "subprogram": "zero_fn"}]
    ft = resp["failed_testcases"]
    assert ft["available"] is True and ft["count"] == 1
    assert ft["items"][0]["testcase"] == "TC_zero_1"


def test_quality_detail_sections_independent(tmp_path, monkeypatch):
    """vectorcast_detail 부재여도 실패 TC 섹션은 산다(역도 성립) — 증거부재≠0."""
    from backend.routers import summary_insight as si

    meta = _prep(tmp_path, detail=False, rag=True)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    resp = si.summary_quality_detail({"job_url": "http://j/"})
    assert resp["function_coverage"]["available"] is False
    assert resp["function_coverage"]["reason"] == "no_vectorcast_detail"
    assert resp["failed_testcases"]["available"] is True

    meta2 = _prep(tmp_path / "x", detail=True, rag=False)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta2])
    resp2 = si.summary_quality_detail({"job_url": "http://j/"})
    assert resp2["function_coverage"]["available"] is True
    assert resp2["failed_testcases"]["available"] is False


def test_quality_detail_no_cached_build(monkeypatch):
    from backend.routers import summary_insight as si

    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [])
    resp = si.summary_quality_detail({"job_url": "http://j/"})
    assert resp["available"] is False and resp["reason"] == "no_cached_build"


# ── K1: _ccn_map — vectorcast_detail(빈 규약) → vectorcast.ut/it_metrics 폴백 ──

def test_ccn_map_vectorcast_metrics_fallback(tmp_path):
    from backend.routers.summary_insight import _ccn_map

    (tmp_path / "analysis_summary.json").write_text(json.dumps({
        "vectorcast_detail": {},  # 실측: 전 캐시 빌드에서 빈 dict — 구 코드는 여기서 {} 반환
        "vectorcast": {
            "ut_metrics": {"entries": [{"subprogram": "f1", "ccn": 3}]},
            "it_metrics": {"entries": [{"subprogram": "f1", "ccn": 5}, {"subprogram": "g", "ccn": 2}]},
        },
    }), encoding="utf-8")
    assert _ccn_map(tmp_path) == {"f1": 5, "g": 2}  # UT/IT 병합, 중복 함수는 max


def test_ccn_map_detail_takes_precedence_when_populated(tmp_path):
    from backend.routers.summary_insight import _ccn_map

    (tmp_path / "analysis_summary.json").write_text(json.dumps({
        "vectorcast_detail": {"aggregate_coverage": {"entries": [{"subprogram": "d", "ccn": 9}]}},
        "vectorcast": {"ut_metrics": {"entries": [{"subprogram": "f1", "ccn": 3}]}},
    }), encoding="utf-8")
    assert _ccn_map(tmp_path) == {"d": 9}  # 구 규약이 채워져 있으면 그대로(폴백 미발동)
