"""Quality advisor 제안 생성 테스트 (swut/swit/swreport/swsa/sits 규칙 포함)."""
from __future__ import annotations

import uuid

import pytest

from workflow.quality.advisor import suggest_improvements
from workflow.quality.db import get_session, init_db, reset_engine
from workflow.quality.models import GenerationRun, QualityScore, QualitySummary


@pytest.fixture
def tmp_db(tmp_path):
    db = tmp_path / "q.sqlite"
    reset_engine()
    init_db(db)
    yield db
    reset_engine()


def _make_run(db, doc_type, scores, *, overall=50.0, gate=False):
    """scores: list of (metric_name, value, gate_pass, threshold) → run_id."""
    with get_session(db) as s:
        run = GenerationRun(run_uuid=str(uuid.uuid4()), doc_type=doc_type, status="success")
        s.add(run)
        s.flush()
        for name, val, gp, th in scores:
            s.add(QualityScore(run_id=run.id, metric_name=name, value=val, gate_pass=gp, threshold=th))
        s.add(QualitySummary(run_id=run.id, overall_score=overall, gate_pass=gate))
        rid = run.id
    return rid


def test_swut_fail_suggests_statement(tmp_db):
    """QM 모듈 swut FAIL — 구문 커버리지만 제안, branch/mcdc 는 과잉 제안 안 함."""
    rid = _make_run(tmp_db, "swut", [
        ("statement_coverage_pct", 0.0, False, 100.0),
        ("branch_coverage_pct", 0.0, None, None),   # QM — DB threshold 없음
        ("mcdc_coverage_pct", 0.0, None, None),
        ("pass_rate_pct", 100.0, True, 100.0),
    ])
    res = suggest_improvements(rid, db_path=tmp_db)
    assert res["unsupported"] is False
    metrics = {s["metric"] for s in res["suggestions"]}
    assert "statement_coverage_pct" in metrics
    # 게이트 비대상(threshold None)인 branch/mcdc 는 제안에서 제외
    assert "branch_coverage_pct" not in metrics
    assert "mcdc_coverage_pct" not in metrics


def test_swut_asil_d_suggests_branch_mcdc(tmp_db):
    """ASIL D — branch/mcdc 에 threshold 기록됨 → 미달 시 제안."""
    rid = _make_run(tmp_db, "swut", [
        ("statement_coverage_pct", 100.0, True, 100.0),
        ("branch_coverage_pct", 80.0, False, 100.0),
        ("mcdc_coverage_pct", 50.0, False, 100.0),
        ("pass_rate_pct", 100.0, True, 100.0),
    ])
    res = suggest_improvements(rid, db_path=tmp_db)
    metrics = {s["metric"] for s in res["suggestions"]}
    assert "branch_coverage_pct" in metrics
    assert "mcdc_coverage_pct" in metrics
    assert "statement_coverage_pct" not in metrics  # 통과 → 제안 없음


def test_swit_uses_same_rules_as_swut(tmp_db):
    rid = _make_run(tmp_db, "swit", [
        ("statement_coverage_pct", 60.0, False, 100.0),
        ("pass_rate_pct", 100.0, True, 100.0),
    ])
    res = suggest_improvements(rid, db_path=tmp_db)
    assert res["unsupported"] is False
    assert any(s["metric"] == "statement_coverage_pct" for s in res["suggestions"])


def test_swreport_fail_suggests_pass_rate(tmp_db):
    rid = _make_run(tmp_db, "swreport", [
        ("pass_rate_pct", 50.0, False, 100.0),
        ("overall_pass", 0.0, None, None),  # rule threshold 100 폴백
    ])
    res = suggest_improvements(rid, db_path=tmp_db)
    metrics = {s["metric"] for s in res["suggestions"]}
    assert "pass_rate_pct" in metrics
    assert "overall_pass" in metrics


def test_swsa_fail_suggests_his(tmp_db):
    rid = _make_run(tmp_db, "swsa", [
        ("his_pass_pct", 40.0, False, 80.0),
        ("misra_active_violations", 12.0, None, None),  # 참고지표 — 제안 안 함
    ])
    res = suggest_improvements(rid, db_path=tmp_db)
    metrics = {s["metric"] for s in res["suggestions"]}
    assert "his_pass_pct" in metrics
    assert "misra_active_violations" not in metrics


def test_sits_supported(tmp_db):
    rid = _make_run(tmp_db, "sits", [
        ("requirement_traceability_pct", 40.0, False, 70.0),
        ("io_coverage_pct", 30.0, False, 60.0),
    ])
    res = suggest_improvements(rid, db_path=tmp_db)
    assert res["unsupported"] is False
    assert res["suggestion_count"] == 2


def test_unknown_doc_type_unsupported(tmp_db):
    """미정의 doc_type — '제안 없음(양호)'이 아니라 unsupported 로 명시."""
    rid = _make_run(tmp_db, "weird", [("x_pct", 0.0, None, None)])
    res = suggest_improvements(rid, db_path=tmp_db)
    assert res["unsupported"] is True
    assert res["suggestions"] == []


def test_suts_pass_no_suggestions(tmp_db):
    """기존 suts 회귀 — 모두 통과면 제안 0, unsupported=False."""
    rid = _make_run(tmp_db, "suts", [
        ("function_coverage_pct", 100.0, True, 80.0),
        ("io_coverage_pct", 90.0, True, 70.0),
    ], overall=90.0, gate=True)
    res = suggest_improvements(rid, db_path=tmp_db)
    assert res["unsupported"] is False
    assert res["suggestion_count"] == 0


def test_missing_run_returns_error(tmp_db):
    res = suggest_improvements(99999, db_path=tmp_db)
    assert "error" in res
