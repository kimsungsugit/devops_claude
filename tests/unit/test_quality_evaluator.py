"""Unit tests for workflow.quality.evaluator — metric helpers, evaluate, overall score."""
from __future__ import annotations

import pytest

from workflow.quality.evaluator import (
    _metric,
    _safe_float,
    compute_overall_score,
    evaluate_coverage,
    evaluate_sits,
    evaluate_sts,
    evaluate_suts,
    evaluate_swreport,
    evaluate_swsa,
    evaluate_uds,
)


class TestMetric:
    def test_without_threshold(self):
        m = _metric("test", 75.0)
        assert m["metric_name"] == "test"
        assert m["value"] == 75.0
        assert m["gate_pass"] is None
        assert m["threshold"] is None

    def test_with_threshold_pass(self):
        m = _metric("test", 80.0, threshold=70.0)
        assert m["gate_pass"] is True

    def test_with_threshold_fail(self):
        m = _metric("test", 50.0, threshold=70.0)
        assert m["gate_pass"] is False

    def test_rounding(self):
        m = _metric("test", 33.3333)
        assert m["value"] == 33.33


class TestSafeFloat:
    def test_valid_key(self):
        assert _safe_float({"val": "3.14"}, "val") == pytest.approx(3.14)

    def test_missing_key(self):
        assert _safe_float({"a": 1}, "b") == 0.0

    def test_none_value(self):
        assert _safe_float({"a": None}, "a") == 0.0

    def test_not_dict(self):
        assert _safe_float("string", "key") == 0.0
        assert _safe_float(None, "key") == 0.0

    def test_custom_default(self):
        assert _safe_float({}, "x", default=99.0) == 99.0


class TestEvaluateUDS:
    def test_basic_fields(self):
        data = {
            "quick_gate": {
                "fields": {
                    "called_pct": 90.0,
                    "calling_pct": 85.0,
                    "description_pct": 70.0,
                }
            },
            "gate_pass": True,
            "confidence_gate_pass": False,
        }
        metrics = evaluate_uds(data)
        names = [m["metric_name"] for m in metrics]
        assert "called_pct" in names
        assert "calling_pct" in names
        assert "description_pct" in names
        assert "gate_pass" in names
        assert "confidence_gate_pass" in names

        gate_m = next(m for m in metrics if m["metric_name"] == "gate_pass")
        assert gate_m["value"] == 100.0
        conf_m = next(m for m in metrics if m["metric_name"] == "confidence_gate_pass")
        assert conf_m["value"] == 0.0

    def test_empty_data(self):
        metrics = evaluate_uds({})
        assert len(metrics) > 0  # still produces all field metrics (with 0 values)

    def test_fields_from_rates_shape(self):
        """실제 생산자 _compute_quick_quality_gate 의 quick_gate.rates.*_fill(0~100) 소비."""
        data = {
            "quick_gate": {
                "rates": {
                    "called_fill": 90.0,
                    "calling_fill": 80.0,
                    "description_fill": 70.0,
                },
                "counts": {"total_functions": 5},
            },
            "gate_pass": True,
        }
        by_name = {m["metric_name"]: m for m in evaluate_uds(data)}
        assert by_name["called_pct"]["value"] == 90.0
        assert by_name["calling_pct"]["value"] == 80.0
        assert by_name["description_pct"]["value"] == 70.0


class TestEvaluateSTS:
    def test_basic(self):
        data = {
            "total_test_cases": 100,
            "completeness_pct": 85.0,
            "safety_test_cases": 20,
            "requirement_coverage": {"covered_pct": 90.0},
            "test_method_distribution": {"equivalence": 10, "boundary": 5, "stress": 3},
        }
        metrics = evaluate_sts(data)
        names = [m["metric_name"] for m in metrics]
        assert "completeness_pct" in names
        assert "safety_tc_pct" in names
        assert "requirement_coverage_pct" in names
        assert "method_diversity_pct" in names

        safety = next(m for m in metrics if m["metric_name"] == "safety_tc_pct")
        assert safety["value"] == 20.0

        cov = next(m for m in metrics if m["metric_name"] == "requirement_coverage_pct")
        assert cov["value"] == 90.0


class TestEvaluateSUTS:
    def test_basic(self):
        data = {
            "total_test_cases": 50,
            "function_coverage_pct": 88.0,
            "io_coverage_pct": 75.0,
            "avg_sequences_per_tc": 4.5,
            "with_logic_count": 30,
            "total_sequences": 200,
        }
        metrics = evaluate_suts(data)
        names = [m["metric_name"] for m in metrics]
        assert "function_coverage_pct" in names
        assert "io_coverage_pct" in names
        assert "sequence_fidelity_pct" in names
        assert "logic_flow_pct" in names

        seq = next(m for m in metrics if m["metric_name"] == "sequence_fidelity_pct")
        assert seq["value"] == 75.0  # 4.5/6.0 * 100

        logic = next(m for m in metrics if m["metric_name"] == "logic_flow_pct")
        assert logic["value"] == 60.0  # 30/50 * 100


class TestEvaluateSITS:
    def test_basic(self):
        data = {
            "total_test_cases": 10,
            "related_coverage_pct": 100.0,          # 합성 SwCom 포함 — 서식 채움 지표
            "requirement_traceability_pct": 80.0,   # 합성 제외 — 게이트 대상
            "io_coverage_pct": 65.0,
            "avg_sub_cases_per_tc": 3.5,
            "gen_method_distribution": {"normal": 5, "boundary": 3, "stress": 2},
        }
        by_name = {m["metric_name"]: m for m in evaluate_sits(data)}
        assert by_name["requirement_traceability_pct"]["value"] == 80.0
        assert by_name["requirement_traceability_pct"]["threshold"] == 70.0
        assert by_name["io_coverage_pct"]["value"] == 65.0
        # method_diversity: 3 종류 / 3 = 100%
        assert by_name["method_diversity_pct"]["value"] == 100.0
        # integration_density: 3.5 / 7 = 50%
        assert by_name["integration_density_pct"]["value"] == 50.0

    def test_related_field_fill_is_not_traceability(self):
        """합성 SwCom으로 Related ID가 다 차 있어도 요구 추적성 게이트는 통과하지 않는다.

        회귀 대상: evaluate_sits가 related_coverage_pct(항상 ~100%)를
        requirement_traceability_pct로 그대로 썼다 → 요구 링크 0건도 threshold 70 통과.
        """
        data = {
            "total_test_cases": 10,
            "related_coverage_pct": 100.0,
            "requirement_traceability_pct": 0.0,
            "synthetic_only_related_count": 10,
        }
        by_name = {m["metric_name"]: m for m in evaluate_sits(data)}
        assert by_name["requirement_traceability_pct"]["value"] == 0.0
        assert by_name["requirement_traceability_pct"]["gate_pass"] is False
        # 서식 채움 지표는 보존하되 점수/게이트에 반영하지 않는다
        assert by_name["related_field_filled_pct"]["value"] == 100.0
        assert by_name["related_field_filled_pct"]["threshold"] is None
        assert by_name["synthetic_only_related_count"]["value"] == 10.0

    def test_missing_new_key_is_fail_closed(self):
        """새 키가 없는 구 리포트는 0.0(미측정)으로 떨어져 게이트가 실패해야 한다."""
        by_name = {m["metric_name"]: m for m in evaluate_sits({
            "total_test_cases": 5, "related_coverage_pct": 100.0,
        })}
        assert by_name["requirement_traceability_pct"]["value"] == 0.0
        assert by_name["requirement_traceability_pct"]["gate_pass"] is False

    def test_empty(self):
        assert len(evaluate_sits({})) > 0


class TestEvaluateSwReport:
    def test_pass_rate(self):
        data = {"performed_count": 10, "fail_count": 2, "overall_result": "Fail"}
        by_name = {m["metric_name"]: m for m in evaluate_swreport(data)}
        assert by_name["pass_rate_pct"]["value"] == 80.0  # (10-2)/10
        assert by_name["pass_rate_pct"]["threshold"] == 100.0
        assert by_name["overall_pass"]["value"] == 0.0

    def test_all_pass(self):
        data = {"performed_count": 5, "fail_count": 0, "overall_result": "Pass"}
        by_name = {m["metric_name"]: m for m in evaluate_swreport(data)}
        assert by_name["pass_rate_pct"]["value"] == 100.0
        assert by_name["overall_pass"]["value"] == 100.0


class TestEvaluateCoverage:
    def test_asil_d_gates_mcdc(self):
        summary = {
            "overall_statement_pct": 90.0, "overall_branch_pct": 80.0,
            "overall_mcdc_pct": 50.0, "passed": 11, "failed": 1, "total_tcs": 12,
        }
        by_name = {m["metric_name"]: m for m in evaluate_coverage(summary, asil="D")}
        assert by_name["statement_coverage_pct"]["value"] == 90.0
        assert by_name["mcdc_coverage_pct"]["value"] == 50.0
        assert by_name["mcdc_coverage_pct"]["threshold"] == 100.0  # ASIL D: gated
        assert by_name["branch_coverage_pct"]["threshold"] == 100.0
        # pass_rate = 11/12 (여기선 passed+failed == total_tcs, 미실행 0)
        assert by_name["pass_rate_pct"]["value"] == round(11 / 12 * 100, 2)

    def test_pass_rate_penalizes_not_executed_tcs(self):
        """미실행 TC(시험 공백)는 pass_rate 분모(tested+not_executed)에 포함돼야 한다.

        안 그러면 스위트의 일부만 돌려도 100% 통과로 품질게이트를 지난다 — ISO 26262
        시험 완전성이 은폐된다. name 단위 일치: passed/failed/not_executed 모두 이름 단위
        (total_tcs 는 compound TC 서브아이템 granular라 분모로 안 씀 — deep-review W1).
        """
        # 실행 10개 전부 통과 + 미실행 90개 → 분모 100
        summary = {"passed": 10, "failed": 0, "not_executed": 90}
        by_name = {m["metric_name"]: m for m in evaluate_coverage(summary, asil="D")}
        assert by_name["pass_rate_pct"]["value"] == 10.0  # 10/100, NOT 10/10=100
        assert by_name["pass_rate_pct"]["threshold"] == 100.0  # → 게이트 미충족

    def test_pass_rate_falls_back_when_not_executed_absent(self):
        """not_executed 부재면 실행분(passed+failed)으로 폴백 — 데이터부재 과도 penalty 방지.

        not_executed 는 항상 ≥0 이라 분모 ≥ tested → pass_rate 는 결코 100% 를 넘지 않는다.
        """
        # not_executed 키 없음 → 실행분 분모
        by_name = {m["metric_name"]: m for m in evaluate_coverage({"passed": 5, "failed": 0})}
        assert by_name["pass_rate_pct"]["value"] == 100.0
        # not_executed=0 명시 + 일부 실패 → 실행분 기준
        by_name = {m["metric_name"]: m for m in evaluate_coverage({"passed": 4, "failed": 1, "not_executed": 0})}
        assert by_name["pass_rate_pct"]["value"] == 80.0  # 4/5

    def test_asil_a_mcdc_info_only(self):
        summary = {"overall_statement_pct": 100.0, "overall_mcdc_pct": 0.0, "passed": 5, "failed": 0}
        by_name = {m["metric_name"]: m for m in evaluate_coverage(summary, asil="A")}
        # ASIL A: branch/mcdc 는 참고지표(threshold None) → 0% 라도 점수 미반영
        assert by_name["mcdc_coverage_pct"]["threshold"] is None
        assert by_name["branch_coverage_pct"]["threshold"] is None
        assert by_name["statement_coverage_pct"]["threshold"] == 100.0


class TestEvaluateSwSA:
    def test_his_pass_excludes_unbinned(self):
        data = {
            "his_metrics": [
                {"total": 10, "fail": 1, "unbinned": 1},  # (10-1-1)/10 = 80%
                {"total": 10, "fail": 0, "unbinned": 0},  # 100%
            ],
            "misra_active": 7, "secure_active": 3, "pmd_fail": 2,
        }
        by_name = {m["metric_name"]: m for m in evaluate_swsa(data)}
        assert by_name["his_pass_pct"]["value"] == 90.0  # (80+100)/2
        assert by_name["his_pass_pct"]["threshold"] == 80.0
        # 위반 수는 참고지표 (threshold 없음 → 점수 미반영)
        assert by_name["misra_active_violations"]["threshold"] is None
        assert by_name["misra_active_violations"]["value"] == 7.0


class TestComputeOverallScore:
    def test_with_thresholds(self):
        metrics = [
            _metric("a", 80.0, threshold=70.0),
            _metric("b", 50.0, threshold=70.0),  # fail -> 0.5x penalty
        ]
        score = compute_overall_score(metrics)
        # a=80 (pass), b=50*0.5=25 (fail), avg=(80+25)/2=52.5
        assert score == 52.5

    def test_all_pass(self):
        metrics = [
            _metric("a", 100.0, threshold=70.0),
            _metric("b", 90.0, threshold=70.0),
        ]
        score = compute_overall_score(metrics)
        assert score == 95.0

    def test_no_thresholds_uses_pct_average(self):
        metrics = [
            _metric("x_pct", 80.0),
            _metric("y_pct", 60.0),
            _metric("z_count", 10.0),  # not _pct, excluded
        ]
        score = compute_overall_score(metrics)
        assert score == 70.0

    def test_empty_metrics(self):
        assert compute_overall_score([]) == 0.0
