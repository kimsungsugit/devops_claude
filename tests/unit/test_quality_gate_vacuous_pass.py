"""품질 게이트의 vacuous truth — "검사 0건" 이 PASS 로 기록되던 것.

## 왜 이 테스트가 있나 (실측)

`recorder.py` 의 판정이 이랬다:

    gate_pass = all(m.get("gate_pass", True) for m in metrics if m.get("gate_pass") is not None)

필터를 거친 제너레이터가 비면 `all([])` 은 **True** 다. 실측 2건:

| 상황 | 옛 결과 |
|---|---|
| 알 수 없는 `doc_type` → `metrics=[]` | `gate_pass=True`, score=0.0 — 점수 0인데 통과 |
| `config.UDS_QUALITY_GATE_THRESHOLDS` 부재/import 실패 | 지표 11개 전부 `threshold=None` → 검사 0건인데 `gate_pass=True`. FAIL 페널티가 사라져 점수가 **오른다**(64.71 → 68.0) |

두 번째가 특히 나쁘다. `try/except Exception: thresholds = {}` 가 어떤 config 실패든 삼키고,
`getattr(config, ..., {})` 가 키 rename/삭제도 삼킨다 — 즉 config 리팩터 한 번으로 UDS
게이트가 **경고 한 줄 없이 꺼지고**, 그 상태가 "통과" 로 DB 에 남는다.

ISO 26262 품질 게이트에서 "검사하지 않음" 을 통과로 기록하면 그게 곧 거짓 증거다.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from workflow.quality.evaluator import (
    compute_gate_verdict,
    compute_overall_score,
    evaluate_coverage,
    evaluate_sits,
    evaluate_sts,
    evaluate_suts,
    evaluate_swreport,
    evaluate_swsa,
    evaluate_uds,
)


@pytest.fixture
def qdb():
    return pathlib.Path(tempfile.mkdtemp()) / "q.db"


def _m(name, value, gate_pass=None, threshold=None):
    return {"metric_name": name, "value": value, "gate_pass": gate_pass, "threshold": threshold}


# ==============================================================
# 1. compute_gate_verdict — 판정 단일 출처
# ==============================================================

class TestGateVerdict:
    def test_empty_metrics_is_not_pass(self):
        """`all([])` == True 라 옛 코드가 통과로 기록했다.

        뮤테이션: `if not gated: return {...False...}` 를 없애면 `not failed` 가 True 라 실패.
        """
        v = compute_gate_verdict([])
        assert v["gate_pass"] is False
        assert v["gated_count"] == 0
        assert v["reason"] == "no_gated_metric"

    def test_all_ungated_metrics_is_not_pass(self):
        """지표가 있어도 전부 threshold=None 이면 검사한 게 없다 — UDS threshold 부재 케이스."""
        metrics = [_m("a_pct", 96.0), _m("b_pct", 91.0), _m("c_pct", 88.0)]
        v = compute_gate_verdict(metrics)
        assert v["gate_pass"] is False
        assert v["gated_count"] == 0
        assert v["reason"] == "no_gated_metric"

    def test_single_gated_pass(self):
        """음성 대조군 — 가드가 정상 통과까지 막지 않는다.

        이게 없으면 `return False` 를 무조건 실행하도록 바꿔도 위 두 테스트는 통과한다.
        """
        v = compute_gate_verdict([_m("x_pct", 100.0, gate_pass=True, threshold=90.0)])
        assert v["gate_pass"] is True
        assert v["gated_count"] == 1
        assert v["failed_count"] == 0
        assert v["reason"] is None

    def test_one_failure_fails_the_gate(self):
        v = compute_gate_verdict([
            _m("x_pct", 100.0, gate_pass=True, threshold=90.0),
            _m("y_pct", 10.0, gate_pass=False, threshold=90.0),
            _m("z_pct", 50.0),   # 비게이트 — 판정에 안 들어간다
        ])
        assert v["gate_pass"] is False
        assert v["gated_count"] == 2
        assert v["failed_count"] == 1
        assert v["reason"] is None

    def test_ungated_metrics_do_not_dilute_the_count(self):
        """비게이트 지표를 아무리 붙여도 gated_count 는 안 늘어난다."""
        metrics = [_m("x_pct", 100.0, gate_pass=True, threshold=90.0)]
        metrics += [_m(f"ref{i}", 0.0) for i in range(20)]
        assert compute_gate_verdict(metrics)["gated_count"] == 1


# ==============================================================
# 2. 모든 evaluator 는 게이트 항목을 최소 1개 내야 한다
# ==============================================================

@pytest.mark.parametrize("name,fn", [
    ("uds", lambda: evaluate_uds({})),
    ("sts", lambda: evaluate_sts({})),
    ("suts", lambda: evaluate_suts({})),
    ("sits", lambda: evaluate_sits({})),
    ("swreport", lambda: evaluate_swreport({})),
    ("coverage", lambda: evaluate_coverage({})),
    ("swsa", lambda: evaluate_swsa({})),
])
def test_every_evaluator_is_fail_closed_on_empty_input(name, fn):
    """빈 입력 = 데이터 없음 → fail-closed 여야 한다(미측정을 통과로 바꾸지 않는다).

    (R32 B-9) 분모 0 인 축은 비게이트(`_gate_if_applicable`)라 suts/sits/swsa 는 빈 입력에서 게이트 항목이
    0개가 되고, 그땐 `compute_gate_verdict` 가 `no_gated_metric` 으로 **판정 불가**를 낸다 — "0% FAIL" 이
    아니라 "잴 것이 없었다" 다. 둘 다 fail-closed 이므로 여기서는 그 둘만 허용한다.
    """
    v = compute_gate_verdict(fn())
    assert v["gate_pass"] is False, f"{name}: 빈 입력인데 통과"
    assert v["gated_count"] >= 1 or v["reason"] == "no_gated_metric", name


@pytest.mark.parametrize("name,fn", [
    ("uds", lambda: evaluate_uds({})),
    ("sts", lambda: evaluate_sts({"total_test_cases": 1})),
    ("suts", lambda: evaluate_suts({"total_test_cases": 1})),
    ("sits", lambda: evaluate_sits({"total_test_cases": 1})),
    ("swreport", lambda: evaluate_swreport({})),
    ("coverage", lambda: evaluate_coverage({})),
    ("swsa", lambda: evaluate_swsa({"his_metrics": [{"total": 1, "fail": 0, "unbinned": 0}]})),
])
def test_every_evaluator_gates_at_least_one_metric(name, fn):
    """**실 문서 형태**(분모 ≥1)에서 게이트 대상이 0개면 그 doc_type 은 판정이 성립하지 않는다.

    지표를 추가하다 threshold 를 다 떼면 이 테스트가 깨지면서 알려준다.
    """
    v = compute_gate_verdict(fn())
    assert v["gated_count"] >= 1, f"{name}: 게이트 항목 0개 — 판정이 성립하지 않는다"


# ==============================================================
# 3. UDS — config threshold 소실이 조용히 게이트를 끄던 것
# ==============================================================

_UDS_FULL_RATES = {
    "called_fill": 96.0, "calling_fill": 95.0, "input_fill": 92.0, "output_fill": 91.0,
    "description_fill": 88.0, "asil_fill": 30.0, "related_fill": 40.0,
}


class TestUdsThresholdLoss:
    def _uds(self):
        return {"quick_gate": {"rates": dict(_UDS_FULL_RATES)}, "gate_pass": False}

    def test_missing_thresholds_is_fail_closed_and_flagged(self, monkeypatch):
        """threshold 를 못 읽으면 판정 불가 + 사유가 지표로 남아야 한다.

        뮤테이션: `quality_thresholds_missing` 지표를 없애면 KeyError·StopIteration 으로 실패.
        """
        import config
        monkeypatch.setattr(config, "UDS_QUALITY_GATE_THRESHOLDS", {}, raising=False)
        metrics = evaluate_uds(self._uds())
        v = compute_gate_verdict(metrics)
        assert v["reason"] == "no_gated_metric"
        assert v["gate_pass"] is False
        flag = next(m for m in metrics if m["metric_name"] == "quality_thresholds_missing")
        assert flag["value"] == 1.0

    def test_present_thresholds_are_gated_and_flag_is_zero(self, monkeypatch):
        """음성 대조군 — 정상 config 에서는 7개가 게이트되고 flag 는 0."""
        metrics = evaluate_uds(self._uds())
        v = compute_gate_verdict(metrics)
        assert v["gated_count"] == 7
        flag = next(m for m in metrics if m["metric_name"] == "quality_thresholds_missing")
        assert flag["value"] == 0.0

    def test_score_scale_changes_when_gate_is_lost(self, monkeypatch):
        """threshold 를 떼면 점수가 **다른 규칙**으로 계산된다 — 추이 비교에 쓸 수 없다.

        게이트 있음: threshold 보유 지표만, FAIL 은 0.5x 페널티.
        게이트 없음: 이름이 `_pct` 로 끝나는 **모든** 지표의 단순 평균(페널티 없음).

        방향은 데이터에 달렸다(참고지표 global/static 값에 좌우된다). 실측 두 사례:
        `global=50/static=30` → 64.71 **상승** 68.0 / `global=0/static=0` → 64.71 하락 59.11.
        즉 "항상 오른다" 가 아니라 **비교 불가**가 핵심이다. 그래서 판정은 `gated_count` 가
        하고 점수는 하지 않는다.
        """
        import config
        data = self._uds()
        gated_score = compute_overall_score(evaluate_uds(data))
        monkeypatch.setattr(config, "UDS_QUALITY_GATE_THRESHOLDS", {}, raising=False)
        ungated_score = compute_overall_score(evaluate_uds(data))
        assert ungated_score != gated_score, (
            "같은 데이터인데 점수가 같으면 척도 차이를 못 드러낸다 — 계약이 무의미해진다"
        )
        assert compute_gate_verdict(evaluate_uds(data))["gate_pass"] is False

    def test_score_can_rise_when_gate_is_lost(self, monkeypatch):
        """참고지표가 높으면 게이트를 잃은 쪽 점수가 **더 높다** — 점수만 보면 개선처럼 보인다.

        이게 척도 혼용의 실질 피해다: 대시보드 추이에서 "게이트가 꺼진 실행" 이 개선으로 읽힌다.
        """
        import config
        data = self._uds()
        # 참고지표를 **전부** 높게 채운다. 게이트를 잃으면 점수가 `_pct` 로 끝나는 모든
        # 지표의 평균이 되므로, 일부만 채우면 나머지가 0.0 으로 잡혀 방향이 뒤집힌다 —
        # 그건 계약("참고지표가 높으면 오를 수 있다")의 반증이 아니라 **데이터 부족**이다.
        # 2026-08-24 에 참고지표 5개(input_real/output_real + trusted 3축)가 추가되면서
        # 실제로 그렇게 뒤집혔다. 위 docstring 이 말하는 "방향은 데이터에 달렸다" 가 이것.
        # ⚠ 참고지표가 늘면 여기도 함께 채울 것. 게이트가 살아 있을 때의 점수는 threshold
        #   보유 지표만 쓰므로 참고지표를 늘려도 변하지 않는다(실측 72.00 → 72.00).
        data["quick_gate"]["rates"].update({
            "global_fill": 50.0, "static_fill": 30.0,
            "input_real_fill": 80.0, "output_real_fill": 80.0,
            "description_trusted_fill": 90.0, "asil_trusted_fill": 90.0,
            "related_trusted_fill": 90.0,
        })
        gated_score = compute_overall_score(evaluate_uds(data))
        monkeypatch.setattr(config, "UDS_QUALITY_GATE_THRESHOLDS", {}, raising=False)
        ungated_score = compute_overall_score(evaluate_uds(data))
        assert ungated_score > gated_score, f"{gated_score} → {ungated_score}"


# ==============================================================
# 4. recorder / advisor 통합 — DB 에 남는 값
# ==============================================================

class TestRecorderIntegration:
    def test_unknown_doc_type_is_recorded_as_not_passing(self, qdb):
        """알 수 없는 doc_type 은 metrics=[] 이라 옛 코드가 gate=True 로 기록했다.

        뮤테이션: recorder 를 옛 `all(...)` 인라인으로 되돌리면 gate_pass=True 가 되어 실패.
        """
        from workflow.quality.advisor import suggest_improvements
        from workflow.quality.recorder import record_run

        rid = record_run("bogus_type", {"x": 1}, db_path=qdb)
        assert rid > 0
        out = suggest_improvements(rid, db_path=qdb)
        assert out["gate_pass"] is False
        assert out["gated_metric_count"] == 0
        assert "판정이 성립하지 않습니다" in out["summary"]
        assert "통과 아님" in out["summary"]

    def test_gated_metric_count_is_persisted(self, qdb):
        """DB 만 보고도 "게이트 항목이 몇 개였나" 를 알 수 있어야 한다."""
        from workflow.quality.db import get_session
        from workflow.quality.models import QualityScore
        from workflow.quality.recorder import record_run

        rid = record_run("sits", {"requirement_traceability_pct": 80.0,
                                  "io_coverage_pct": 90.0, "total_test_cases": 5}, db_path=qdb)
        with get_session(qdb) as s:
            rows = {r.metric_name: r for r in s.query(QualityScore).filter_by(run_id=rid).all()}
        assert "gated_metric_count" in rows
        assert rows["gated_metric_count"].value == 2.0
        # 비게이트여야 한다 — 이 지표 자체가 판정에 끼어들면 안 된다
        assert rows["gated_metric_count"].gate_pass is None
        assert rows["gated_metric_count"].threshold is None

    def test_gate_definition_is_persisted_so_two_definitions_are_distinguishable(self, qdb):
        """**같은 doc_type 인데 호출 경로마다 `gate_pass` 의 정의가 다르다.**

        UDS 실측(2026-08-03): `/api/local/uds/generate`(동기)만 `_build_quality_evaluation`
        을 통해 quick AND confidence AND report 3중 판정을 기록하고, 나머지 3경로
        (`local generate-async` · `jenkins generate` · `jenkins generate-async`)는
        **bare quick_gate** 를 기록한다. `quality_summaries.gate_pass` 한 컬럼에 두 정의가
        섞여 있는데 그걸 가를 근거가 DB 어디에도 없었다 — 이 컬럼을 읽는 쪽(후보 22 검토 탭)이
        무엇을 비교하는지 모르게 된다.

        정의 통일은 기록 값 자체를 바꾸므로 정책 결정으로 남기고, **어느 정의였는지**만
        additive 로 남긴다(스키마 변경 없음, 판정 무영향).
        """
        from workflow.quality.db import get_session
        from workflow.quality.models import QualityScore
        from workflow.quality.recorder import record_run

        def _defs(rid: int) -> list[str]:
            with get_session(qdb) as s:
                return [r.metric_name for r in s.query(QualityScore).filter_by(run_id=rid).all()
                        if r.metric_name.startswith("gate_definition:")]

        # 3중 판정 경로 — _build_quality_evaluation 이 gate_source 를 실어 보낸다
        rid_merged = record_run(
            "sits",
            {"requirement_traceability_pct": 80.0, "io_coverage_pct": 90.0,
             "total_test_cases": 5, "gate_source": "quick_confidence_and_report"},
            db_path=qdb,
        )
        assert _defs(rid_merged) == ["gate_definition:quick_confidence_and_report"]

        # bare quick_gate 경로 — gate_source 가 아예 없다. 그 **부재 자체**가 기록돼야 한다.
        rid_bare = record_run(
            "sits",
            {"requirement_traceability_pct": 80.0, "io_coverage_pct": 90.0,
             "total_test_cases": 5},
            db_path=qdb,
        )
        assert _defs(rid_bare) == ["gate_definition:quick_gate_only"]

        # 판정에 끼어들면 안 된다 — 비게이트 지표다
        with get_session(qdb) as s:
            row = (s.query(QualityScore)
                   .filter_by(run_id=rid_bare, metric_name="gate_definition:quick_gate_only")
                   .one())
            assert row.gate_pass is None
            assert row.threshold is None

    def test_normal_run_still_passes(self, qdb):
        """음성 대조군 — 정상 통과 실행이 fail-closed 로 오염되지 않는다."""
        from workflow.quality.advisor import suggest_improvements
        from workflow.quality.recorder import record_run

        rid = record_run("swreport", {"performed_count": 10, "fail_count": 0,
                                      "overall_result": "pass"}, db_path=qdb)
        out = suggest_improvements(rid, db_path=qdb)
        assert out["gate_pass"] is True
        assert out["gated_metric_count"] == 1

    def test_legacy_run_without_the_metric_reports_none(self, qdb):
        """이 지표가 없던 구 실행은 `None`(판별 불가) — 0 으로 접어 "판정 불가" 로 오기재하지 않는다."""
        from workflow.quality.advisor import suggest_improvements
        from workflow.quality.db import get_session, init_db
        from workflow.quality.models import GenerationRun, QualityScore, QualitySummary

        init_db(qdb)
        with get_session(qdb) as s:
            run = GenerationRun(run_uuid="legacy-1", doc_type="uds", status="success")
            s.add(run)
            s.flush()
            s.add(QualityScore(run_id=run.id, metric_name="called_pct", value=99.0,
                               gate_pass=True, threshold=95.0))
            s.add(QualitySummary(run_id=run.id, overall_score=99.0, gate_pass=True))
            rid = run.id
        out = suggest_improvements(rid, db_path=qdb)
        assert out["gated_metric_count"] is None
        assert "판정이 성립하지 않습니다" not in out["summary"]


class TestAdvisorContradiction:
    def test_gate_fail_with_no_suggestions_does_not_claim_all_passed(self, qdb):
        """게이트 미통과인데 제안 0건이면 "모든 항목 통과" 로 말하면 안 된다.

        실패 지표에 advice 규칙이 없을 때 발생한다. 옛 문구는 게이트 결과와 정면 모순이었다.

        뮤테이션: `elif not suggestions and not gate:` 분기를 없애면 "모든 항목이 임계값을
        통과했습니다" 가 나와 실패.
        """
        from workflow.quality.advisor import suggest_improvements
        from workflow.quality.db import get_session, init_db
        from workflow.quality.models import GenerationRun, QualityScore, QualitySummary

        init_db(qdb)
        with get_session(qdb) as s:
            run = GenerationRun(run_uuid="nosug-1", doc_type="uds", status="success")
            s.add(run)
            s.flush()
            # advice 규칙에 없는 지표만 FAIL → 제안 0건
            s.add(QualityScore(run_id=run.id, metric_name="unknown_metric_pct", value=1.0,
                               gate_pass=False, threshold=90.0))
            s.add(QualityScore(run_id=run.id, metric_name="gated_metric_count", value=1.0))
            s.add(QualitySummary(run_id=run.id, overall_score=1.0, gate_pass=False))
            rid = run.id
        out = suggest_improvements(rid, db_path=qdb)
        assert out["suggestion_count"] == 0
        assert out["gate_pass"] is False
        assert "모든 항목이 임계값을 통과" not in out["summary"]
        assert "게이트 미통과" in out["summary"]

    def test_genuine_all_pass_still_says_so(self, qdb):
        """음성 대조군 — 진짜 전부 통과한 실행은 그대로 "모든 항목 통과"."""
        from workflow.quality.advisor import suggest_improvements
        from workflow.quality.db import get_session, init_db
        from workflow.quality.models import GenerationRun, QualityScore, QualitySummary

        init_db(qdb)
        with get_session(qdb) as s:
            run = GenerationRun(run_uuid="allpass-1", doc_type="uds", status="success")
            s.add(run)
            s.flush()
            s.add(QualityScore(run_id=run.id, metric_name="called_pct", value=99.0,
                               gate_pass=True, threshold=95.0))
            s.add(QualityScore(run_id=run.id, metric_name="gated_metric_count", value=1.0))
            s.add(QualitySummary(run_id=run.id, overall_score=99.0, gate_pass=True))
            rid = run.id
        out = suggest_improvements(rid, db_path=qdb)
        assert out["suggestion_count"] == 0
        assert "모든 항목이 임계값을 통과" in out["summary"]
