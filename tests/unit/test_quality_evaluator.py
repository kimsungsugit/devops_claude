"""Unit tests for workflow.quality.evaluator — metric helpers, evaluate, overall score."""
from __future__ import annotations

import pytest

from workflow.quality.evaluator import (
    _metric,
    _safe_float,
    evaluate_uds,
    evaluate_sts,
    evaluate_suts,
    compute_overall_score,
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
