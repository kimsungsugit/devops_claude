"""POST /api/jenkins/prqa-trend — PRQA 정적분석 빌드별 트렌드(analysis_summary.json 직독)."""
from __future__ import annotations

import json
from pathlib import Path


def _write_summary(reports_dir: Path, *, violations, diagnostics, compliance, extra_summary=None):
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "Rule Violation Count": violations,
        "Diagnostic Count": diagnostics,
        "Project Compliance Index": compliance,
        "Lines of Code (including headers)": 64805,
        "Number of Files (including CMA)": 126,
    }
    if extra_summary:
        summary.update(extra_summary)
    (reports_dir / "analysis_summary.json").write_text(
        json.dumps({
            "prqa": {"rcr": {"ok": True, "summary": summary}},
            "code_metrics": {"code_files": None, "functions": None, "nloc": None},
        }),
        encoding="utf-8",
    )


def test_prqa_trend_builds_series_oldest_to_newest(monkeypatch, tmp_path):
    from backend.routers import jenkins

    d125, d124 = tmp_path / "b125", tmp_path / "b124"
    _write_summary(d125, violations=562, diagnostics=502, compliance=91)
    _write_summary(d124, violations=552, diagnostics=492, compliance=91)
    monkeypatch.setattr(jenkins, "list_cached_builds", lambda **k: [
        {"build_number": 125, "reports_dir": str(d125)},
        {"build_number": 124, "reports_dir": str(d124)},
    ])
    resp = jenkins.jenkins_prqa_trend({"job_url": "http://j/", "cache_root": ".devops_pro_cache"})
    assert resp["available"] is True
    assert resp["count"] == 2
    # 트렌드 X축 = 오래된→최신 (124, 125)
    assert [b["build_number"] for b in resp["builds"]] == [124, 125]
    assert resp["builds"][-1]["violations"] == 562
    assert resp["builds"][-1]["diagnostics"] == 502
    assert resp["builds"][-1]["compliance"] == 91
    assert resp["builds"][0]["violations"] == 552
    assert resp["builds"][-1]["loc"] == 64805  # code_metrics None → rcr.summary LOC 폴백


def test_prqa_trend_no_job_url():
    from backend.routers import jenkins

    resp = jenkins.jenkins_prqa_trend({})
    assert resp["available"] is False
    assert resp["builds"] == []


def test_prqa_trend_missing_summary_skipped_fail_soft(monkeypatch, tmp_path):
    """analysis_summary.json 없는 빌드는 스킵(트렌드 전체를 죽이지 않음)."""
    from backend.routers import jenkins

    monkeypatch.setattr(jenkins, "list_cached_builds", lambda **k: [
        {"build_number": 1, "reports_dir": str(tmp_path / "empty")},
    ])
    resp = jenkins.jenkins_prqa_trend({"job_url": "http://j/"})
    assert resp["available"] is False
    assert resp["count"] == 0


def test_prqa_trend_comma_number_parsed(monkeypatch, tmp_path):
    """RCR summary의 '1,234' 콤마 문자열도 정수로 파싱(_num 콤마 처리)."""
    from backend.routers import jenkins

    d = tmp_path / "b"
    _write_summary(d, violations="1,234", diagnostics=5, compliance=88)
    monkeypatch.setattr(jenkins, "list_cached_builds", lambda **k: [
        {"build_number": 3, "reports_dir": str(d)},
    ])
    resp = jenkins.jenkins_prqa_trend({"job_url": "http://j/"})
    assert resp["available"] is True
    assert resp["builds"][0]["violations"] == 1234


def test_prqa_trend_adjacent_delta(monkeypatch, tmp_path):
    """인접 빌드 delta(오래된→최신) — 첫 빌드는 기준이 없어 null."""
    from backend.routers import jenkins

    d125, d124 = tmp_path / "b125", tmp_path / "b124"
    _write_summary(d125, violations=562, diagnostics=502, compliance=91)
    _write_summary(d124, violations=552, diagnostics=492, compliance=91)
    monkeypatch.setattr(jenkins, "list_cached_builds", lambda **k: [
        {"build_number": 125, "reports_dir": str(d125)},
        {"build_number": 124, "reports_dir": str(d124)},
    ])
    resp = jenkins.jenkins_prqa_trend({"job_url": "http://j/"})
    assert resp["builds"][0]["violations_delta"] is None  # 최고(最古) 빌드
    assert resp["builds"][-1]["violations_delta"] == 10
    assert resp["builds"][-1]["diagnostics_delta"] == 10


def test_prqa_trend_delta_null_when_side_missing(monkeypatch, tmp_path):
    """중간 빌드 지표 결측 시 양측 delta는 null — 0으로 위장하지 않는다(ISO 정직성)."""
    from backend.routers import jenkins

    da, db, dc = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    _write_summary(da, violations=500, diagnostics=400, compliance=90)
    _write_summary(db, violations=None, diagnostics=None, compliance=None)
    _write_summary(dc, violations=520, diagnostics=410, compliance=90)
    monkeypatch.setattr(jenkins, "list_cached_builds", lambda **k: [
        {"build_number": 3, "reports_dir": str(dc)},
        {"build_number": 2, "reports_dir": str(db)},
        {"build_number": 1, "reports_dir": str(da)},
    ])
    resp = jenkins.jenkins_prqa_trend({"job_url": "http://j/"})
    by = {b["build_number"]: b for b in resp["builds"]}
    assert by[2]["violations_delta"] is None  # 자신 결측
    assert by[3]["violations_delta"] is None  # 직전(2) 결측 — 3-1=20으로 건너뛰어 계산하지 않음
    assert by[1]["violations_delta"] is None


def test_prqa_trend_available_false_when_no_prqa(monkeypatch, tmp_path):
    from backend.routers import jenkins

    d = tmp_path / "b"
    d.mkdir()
    (d / "analysis_summary.json").write_text(json.dumps({"prqa": {}, "code_metrics": {}}), encoding="utf-8")
    monkeypatch.setattr(jenkins, "list_cached_builds", lambda **k: [
        {"build_number": 3, "reports_dir": str(d)},
    ])
    resp = jenkins.jenkins_prqa_trend({"job_url": "http://j/"})
    # PRQA 지표 전부 None → available False(빌드 산출물에 PRQA 미포함)
    assert resp["available"] is False
    assert resp["count"] == 1
