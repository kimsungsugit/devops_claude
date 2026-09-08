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


def test_swit_has_its_own_rules_not_swuts(tmp_db):
    """2026-08-26 — SwIT 은 SwUT 표를 **더는 공유하지 않는다**.

    옛 판은 `statement_coverage_pct` 제안이 나오는지를 봤다. 그런데 SwITCV 는 구문
    커버리지를 재지 않는 문서라(빌더가 O/X 표식으로 덮어쓴다) 그 제안은 "실행되지 않은
    코드 라인을 위한 TC를 추가하라" 는 **실행 불가능한 조치**였다. 지금은 정본
    `4.Coverage` 가 싣는 축으로 제안한다 — `evaluate_swit_coverage` docstring 참조.
    """
    rid = _make_run(tmp_db, "swit", [
        ("function_achievement_pct", 99.61, False, 100.0),
        ("function_call_coverage_pct", 97.91, False, 100.0),
        ("pass_rate_pct", 100.0, True, 100.0),
    ])
    res = suggest_improvements(rid, db_path=tmp_db)
    assert res["unsupported"] is False
    metrics = {s["metric"] for s in res["suggestions"]}
    assert "function_achievement_pct" in metrics
    assert "function_call_coverage_pct" in metrics


def test_swit_no_longer_advises_statement_coverage(tmp_db):
    """SwUT 표가 되붙으면 이 테스트가 잡는다 — 재지 않는 축의 조치문은 나가면 안 된다."""
    rid = _make_run(tmp_db, "swit", [
        ("statement_coverage_pct", 0.0, False, 100.0),   # 옛 경로가 남기던 값
        ("pass_rate_pct", 100.0, True, 100.0),
    ])
    res = suggest_improvements(rid, db_path=tmp_db)
    assert not any(s["metric"] == "statement_coverage_pct" for s in res["suggestions"])


def test_swut_still_advises_statement_coverage(tmp_db):
    """과잉 분리 방지 — SwUTCV 는 실측 구문 커버리지를 내므로 조치문이 그대로여야 한다."""
    rid = _make_run(tmp_db, "swut", [
        ("statement_coverage_pct", 60.0, False, 100.0),
        ("pass_rate_pct", 100.0, True, 100.0),
    ])
    res = suggest_improvements(rid, db_path=tmp_db)
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


class TestAdviceEndpointDoesNotHideErrorsBehind200:
    """(R39 N9) `/advice` 만 `200 + {"error"}` 로 남아 있었다 — 형제는 이미 404 다.

    `frontend-v2/src/api.js` 헬퍼는 `res.ok` 만 보므로 200 이면 **에러를 성공으로 삼킨다**.
    실제 피해는 `DocGenStatusBoard` 에서 났다: `detail.advice?.summary || '제안 없음'` 이라
    **조회 실패가 "제안 없음"**(= 개선할 게 없다)으로 화면에 나온다 — 두 사실이 한 문장으로 접힌다.
    같은 라우터 안에서 `get_run` 은 *바로 이 이유로* 404 로 고쳐져 있었으므로, 계약이 갈려 있었다.
    """

    def _client(self, tmp_db, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from backend.dependencies.auth import require_user
        from backend.routers import quality as quality_router
        from workflow.quality import db as qdb

        monkeypatch.setattr(qdb, "_default_db_path", lambda: tmp_db)
        app = FastAPI()
        app.include_router(quality_router.router)
        # 라우터 전체가 `require_user` 를 건다. 여기서 재는 것은 **상태코드 계약**이지 인증이
        # 아니므로 신원만 통과시킨다(인증 자체는 `test_admin_gate` 계열이 따로 잰다).
        app.dependency_overrides[require_user] = lambda: "tester"
        return TestClient(app, raise_server_exceptions=False)

    def test_missing_run_is_404_not_200(self, tmp_db, monkeypatch):
        res = self._client(tmp_db, monkeypatch).post("/api/quality/runs/999999/advice")
        assert res.status_code == 404, (
            f"없는 run 에 {res.status_code} — 200 이면 프론트가 성공으로 읽고 '제안 없음' 을 그린다"
        )

    def test_existing_run_still_returns_advice(self, tmp_db, monkeypatch):
        """조이고 나서 정상 경로가 막히면 그건 고친 게 아니다."""
        init_db(tmp_db)
        with get_session(tmp_db) as s:
            run = GenerationRun(run_uuid=str(uuid.uuid4()), doc_type="swut", status="success")
            s.add(run)
            s.flush()
            s.add(QualitySummary(run_id=run.id, overall_score=50.0, gate_pass=False))
            s.add(QualityScore(run_id=run.id, metric_name="pass_rate_pct", value=50.0,
                               gate_pass=False, threshold=100.0))
            rid = run.id
        res = self._client(tmp_db, monkeypatch).post(f"/api/quality/runs/{rid}/advice")
        assert res.status_code == 200, res.text
        assert "summary" in res.json()
