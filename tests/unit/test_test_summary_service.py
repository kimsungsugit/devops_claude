"""Tests for backend.services.test_summary_service."""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.test_summary_service import (
    classify_failure,
    classify_failures_bulk,
    build_unit_breakdown,
    evaluate_quality_gates,
    build_trend_analysis,
    build_requirement_test_map,
    generate_executive_summary,
)


class TestClassifyFailure:
    def test_assertion(self):
        assert classify_failure({"result": "FAIL MISMATCH"}) == "assertion"
        assert classify_failure({"result": "FAIL", "actual_result": "EXPECTED 5 got 3"}) == "assertion"

    def test_timeout(self):
        assert classify_failure({"result": "TIMEOUT"}) == "timeout"
        assert classify_failure({"result": "FAIL TIMED OUT"}) == "timeout"

    def test_crash(self):
        assert classify_failure({"result": "CRASH"}) == "crash"
        assert classify_failure({"result": "FAIL", "description": "SEGFAULT at 0x00"}) == "crash"

    def test_environment(self):
        assert classify_failure({"result": "FAIL SETUP error"}) == "environment"
        assert classify_failure({"result": "FAIL", "error_message": "LICENSE expired"}) == "environment"

    def test_unknown(self):
        assert classify_failure({"result": "FAIL"}) == "unknown"
        assert classify_failure({}) == "unknown"

    def test_bulk(self):
        rows = [
            {"result": "PASS"},
            {"result": "FAIL MISMATCH"},
            {"result": "FAIL TIMEOUT"},
            {"result": "FAIL"},
            {"result": "SKIP"},
        ]
        cats = classify_failures_bulk(rows)
        assert cats["assertion"] == 1
        assert cats["timeout"] == 1
        assert cats["unknown"] == 1


class TestBuildUnitBreakdown:
    def test_dict_input(self):
        test_results = {
            "TC_001": [
                {"header": {"unit_name": "Lib_A"}, "passed": True},
                {"header": {"unit_name": "Lib_A"}, "passed": False},
            ],
            "TC_002": [
                {"header": {"unit_name": "Lib_B"}, "passed": True},
            ],
        }
        result = build_unit_breakdown(test_results)
        assert len(result) == 2
        lib_a = next(r for r in result if r["unit_name"] == "Lib_A")
        assert lib_a["passed"] == 1
        assert lib_a["failed"] == 1
        assert lib_a["pass_rate"] == 0.5

    def test_empty(self):
        assert build_unit_breakdown({}) == []


class TestEvaluateQualityGates:
    def test_all_pass(self):
        # Default gates: 99% pass_rate, 90% line, 85% branch
        summary = {"pass_rate": 0.995, "coverage_line": 0.92, "coverage_branch": 0.88, "new_failures": 0}
        result = evaluate_quality_gates(summary)
        assert result["overall_pass"] is True
        assert all(g["status"] != "fail" for g in result["gates"])

    def test_fail_pass_rate(self):
        summary = {"pass_rate": 0.80, "coverage_line": 0.85, "coverage_branch": 0.75, "new_failures": 0}
        result = evaluate_quality_gates(summary)
        assert result["overall_pass"] is False
        rate_gate = next(g for g in result["gates"] if "통과율" in g["name"])
        assert rate_gate["status"] == "fail"

    def test_fail_new_failures(self):
        summary = {"pass_rate": 0.995, "coverage_line": 0.95, "coverage_branch": 0.90, "new_failures": 3}
        result = evaluate_quality_gates(summary)
        assert result["overall_pass"] is False

    def test_custom_gates(self):
        summary = {"pass_rate": 0.90, "coverage_line": 0.70, "coverage_branch": 0.60, "new_failures": 0}
        gates = {"pass_rate_min": 85.0, "coverage_line_min": 60.0, "coverage_branch_min": 50.0, "max_new_failures": 0}
        result = evaluate_quality_gates(summary, gates)
        assert result["overall_pass"] is True


class TestBuildTrendAnalysis:
    def test_no_previous(self):
        result = build_trend_analysis({"pass_rate": 0.95, "total": 100, "failed": 5})
        assert result["available"] is False

    def test_improvement(self):
        current = {"pass_rate": 0.98, "total": 110, "failed": 2}
        previous = {"pass_rate": 0.95, "total": 100, "failed": 5}
        result = build_trend_analysis(current, previous)
        assert result["available"] is True
        assert result["improved"] is True
        assert result["resolved_failures"] == 3

    def test_regression(self):
        current = {"pass_rate": 0.90, "total": 100, "failed": 10}
        previous = {"pass_rate": 0.95, "total": 100, "failed": 5}
        result = build_trend_analysis(current, previous)
        assert result["improved"] is False
        assert result["new_failures"] == 5


class TestBuildRequirementTestMap:
    def test_extraction(self):
        test_data = {
            "SwUTC_SwUFn_0101__SEQ_01": [{"description": "Test for SwTR_BR_001"}],
            "SwUTC_SwUFn_0102__SEQ_01": [{"description": "Normal test"}],
        }
        req_map = build_requirement_test_map(test_data)
        assert "SwTR_BR_001" in req_map  # from description
        assert "SwUFn_0101" in req_map   # exact ID from TC name (not __SEQ suffix)
        assert "SwUFn_0102" in req_map   # exact ID from TC name


class TestGenerateExecutiveSummary:
    def test_pass_verdict(self):
        summary = {"total": 100, "passed": 100, "failed": 0, "skipped": 0, "pass_rate": 1.0}
        gates = {"overall_pass": True, "gates": []}
        result = generate_executive_summary(summary, gates)
        assert result["verdict"] == "PASS"
        assert "generated_at" in result

    def test_fail_verdict(self):
        summary = {"total": 100, "passed": 80, "failed": 20, "skipped": 0, "pass_rate": 0.80}
        gates = {"overall_pass": False, "gates": [{"name": "테스트 통과율", "status": "fail"}]}
        result = generate_executive_summary(summary, gates)
        assert result["verdict"] == "FAIL"

    def test_with_all_sections(self):
        summary = {"total": 50, "passed": 48, "failed": 2, "skipped": 0, "pass_rate": 0.96}
        gates = {"overall_pass": True, "gates": []}
        units = [{"unit_name": "Lib_A", "passed": 8, "failed": 2, "total": 10, "pass_rate": 0.8}]
        cats = {"assertion": 1, "timeout": 1}
        trend = {"available": True, "pass_rate_delta": 1.0, "improved": True}
        result = generate_executive_summary(summary, gates, units, cats, trend)
        assert result["worst_units"][0]["unit_name"] == "Lib_A"
        assert "assertion" in result["failure_analysis"]["summary"]
        assert "개선" in result["trend_text"]
