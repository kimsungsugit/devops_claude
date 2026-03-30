# tests/unit/test_generators_sts.py
"""Unit tests for generators.sts core functions."""

from __future__ import annotations

import pytest

from generators.sts import (
    parse_requirements_structured,
    generate_test_cases,
    generate_traceability_matrix,
    generate_quality_report,
    map_requirements_to_functions,
    _classify_req_type,
    _make_tc_id,
)


class TestClassifyReqType:
    def test_ei(self):
        assert _classify_req_type("SwEI_0001") == "EI"

    def test_tsr(self):
        assert _classify_req_type("SwTSR_0001") == "TSR"

    def test_ntsr(self):
        assert _classify_req_type("SwNTSR_0001") == "NTSR"

    def test_ntr(self):
        assert _classify_req_type("SwNTR_0001") == "NTR"

    def test_tr(self):
        assert _classify_req_type("SwTR_0001") == "TR"

    def test_other(self):
        assert _classify_req_type("UNKNOWN_001") == "OTHER"


class TestMakeTcId:
    def test_format(self):
        assert _make_tc_id("SwTR_0101", 1) == "SwTC_SwTR_0101_01"
        assert _make_tc_id("SwTR_0101", 12) == "SwTC_SwTR_0101_12"


class TestParseRequirementsStructured:
    def test_empty_input(self):
        result = parse_requirements_structured([])
        assert result == []

    def test_single_req(self):
        lines = [
            "SwTR_0101 - Auto Close: The window shall close automatically | ASIL: A | Related ID: SyTR_0701"
        ]
        result = parse_requirements_structured(lines)
        assert len(result) == 1
        assert result[0]["id"] == "SwTR_0101"
        assert result[0]["req_type"] == "TR"
        assert result[0]["asil"] == "A"

    def test_deduplication(self):
        lines = [
            "SwTR_0101 short",
            "SwTR_0101 - A much longer description with more detail here",
        ]
        result = parse_requirements_structured(lines)
        assert len(result) == 1

    def test_multiple_ids_different(self):
        lines = [
            "SwTR_0101 - First req",
            "SwEI_0001 - Second req",
        ]
        result = parse_requirements_structured(lines)
        assert len(result) == 2
        ids = {r["id"] for r in result}
        assert ids == {"SwTR_0101", "SwEI_0001"}


class TestGenerateTestCases:
    @pytest.fixture()
    def sample_requirements(self):
        return [
            {
                "id": "SwTR_0101",
                "name": "Auto Close",
                "description": "Window closes automatically",
                "asil": "A",
                "related_id": "SyTR_0701",
                "req_type": "TR",
            },
        ]

    @pytest.fixture()
    def sample_function_details(self):
        return {
            "SwUFn_001": {
                "id": "SwUFn_001",
                "name": "S_Window_Close",
                "prototype": "void S_Window_Close(U8 mode)",
                "inputs": ["[IN] U8 mode"],
                "outputs": [],
                "logic_flow": [],
            },
        }

    def test_generates_cases_without_functions(self, sample_requirements):
        result = generate_test_cases(sample_requirements, {}, {})
        assert len(result) > 0
        assert result[0]["srs_id"] == "SwTR_0101"
        assert result[0]["id"].startswith("SwTC_SwTR_0101_")

    def test_generates_cases_with_functions(
        self, sample_requirements, sample_function_details
    ):
        req_to_fids = {"SwTR_0101": ["SwUFn_001"]}
        result = generate_test_cases(
            sample_requirements, sample_function_details, req_to_fids
        )
        assert len(result) > 0
        assert "SwTR_0101" in result[0]["id"]
        assert result[0]["title"].endswith("S_Window_Close")

    def test_empty_requirements(self):
        result = generate_test_cases([], {}, {})
        assert result == []

    def test_max_tc_config(self, sample_requirements):
        config = {"max_tc_per_req": 1}
        result = generate_test_cases(sample_requirements, {}, {}, config)
        assert len(result) <= 1


class TestRequirementMapping:
    def test_maps_from_function_related_field(self):
        requirements = [{"id": "SwTR_0101"}]
        function_details = {
            "SwUFn_001": {
                "name": "S_Window_Close",
                "related": "SwTR_0101",
            }
        }

        result = map_requirements_to_functions(requirements, function_details)

        assert result["SwTR_0101"] == ["SwUFn_001"]

    def test_maps_from_sds_when_related_field_is_missing(self, monkeypatch):
        requirements = [{"id": "SwTR_0101"}]
        function_details = {
            "SwUFn_001": {
                "name": "S_Window_Close",
                "module_name": "MotorCtrl_PDS",
                "related": "",
            }
        }

        monkeypatch.setattr(
            "generators.sts._load_default_sds_map",
            lambda: {
                "motor control": {
                    "related": "SwTR_0101",
                    "asil": "A",
                    "description": "Motor control logic",
                }
            },
        )

        result = map_requirements_to_functions(requirements, function_details)

        assert result["SwTR_0101"] == ["SwUFn_001"]


class TestGenerateTraceabilityMatrix:
    def test_basic_traceability(self):
        test_cases = [
            {"id": "SwTC_SwTR_0101_01", "srs_id": "SwTR_0101", "title": "Auto Close - S_Window_Close"},
        ]
        requirements = [
            {"id": "SwTR_0101", "name": "Auto Close", "description": "", "asil": "A", "related_id": "", "req_type": "TR"},
        ]
        matrix = generate_traceability_matrix(test_cases, requirements)
        assert matrix["req_ids"] == ["SwTR_0101"]
        assert matrix["tc_ids"] == ["SwTC_SwTR_0101_01"]
        assert matrix["coverage"]["covered_reqs"] == 1

    def test_empty(self):
        matrix = generate_traceability_matrix([], [])
        assert matrix["req_ids"] == []
        assert matrix["tc_ids"] == []
        assert matrix["coverage"]["covered_reqs"] == 0


class TestGenerateQualityReport:
    def test_basic_report(self):
        test_cases = [
            {
                "id": "SwTC_SwTR_0101_01",
                "srs_id": "SwTR_0101",
                "title": "Auto Close - S_Window_Close",
                "test_method": "FNCT",
                "gen_method": "review",
                "steps": [{"action": "Call function", "expected": "Returns OK"}],
            },
        ]
        trace = generate_traceability_matrix(
            test_cases,
            [{"id": "SwTR_0101", "name": "Auto Close", "description": "", "asil": "A", "related_id": "", "req_type": "TR"}],
        )
        report = generate_quality_report(test_cases, trace)
        assert "total_test_cases" in report
        assert report["total_test_cases"] >= 1
