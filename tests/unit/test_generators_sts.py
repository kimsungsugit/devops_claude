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


class TestStsColumnSchemaSsot:
    """writer와 validator가 같은 열 스키마를 본다.

    회귀 대상(P0): writer는 11/12/13열(Action/Expected/SRS)에 쓰는데 validator는
    5/6/4열(TestEnvironment/TestMethod/SafetyRelated)을 읽었다 → Action·Expected가 전부
    비어도 "이상 없음"이고, req_linkage_pct는 Safety Related 채움률을 보고했다.
    """

    @staticmethod
    def _tc(idx=1, *, steps=None, srs="SwTR_0101", title="정상 동작 확인"):
        return {
            "id": f"STS_{idx:03d}", "title": title, "safety_related": "X",
            "test_environment": "SwTE_01", "test_method": "FNCT", "gen_method": "ABV",
            "fs_req": "", "description": "설명", "precondition": "전원 인가",
            "srs_id": srs,
            "steps": steps if steps is not None else [
                {"action": "입력을 최소값으로 설정", "expected": "출력이 0"},
                {"action": "입력을 최대값으로 설정", "expected": "출력이 255"},
            ],
        }

    def _write(self, tmp_path, test_cases, name="sts.xlsx"):
        from generators.sts import generate_sts_xlsm
        out = tmp_path / name
        generate_sts_xlsm(None, test_cases, {"coverage": {}}, str(out), {"project_id": "T"})
        return str(out)

    def test_schema_is_single_source(self):
        from generators.sts import _COL_HEADERS, _STS_SCHEMA, STS_COL
        assert STS_COL["action"] == 11 and STS_COL["expected"] == 12 and STS_COL["srs"] == 13
        # 헤더 리스트는 스키마에서 유도된다 — 따로 관리되면 다시 어긋난다
        assert _COL_HEADERS == [label for _, _, label in _STS_SCHEMA]

    def test_writer_columns_match_schema(self, tmp_path):
        from generators.sts import _HEADER_ROW, STS_COL
        openpyxl = pytest.importorskip("openpyxl")
        path = self._write(tmp_path, [self._tc()])
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb["3.SW Integration Test Spec"]
        r = _HEADER_ROW + 1
        assert ws.cell(row=r, column=STS_COL["tc_id"]).value == "STS_001"
        assert ws.cell(row=r, column=STS_COL["action"]).value == "입력을 최소값으로 설정"
        assert ws.cell(row=r, column=STS_COL["expected"]).value == "출력이 0"
        assert ws.cell(row=r, column=STS_COL["srs"]).value == "SwTR_0101"
        wb.close()

    def test_validator_reads_real_action_and_expected(self, tmp_path):
        """정상 산출물: Action/Expected/요구링크가 실제 열에서 읽혀야 한다."""
        from generators.sts import validate_sts_xlsm
        pytest.importorskip("openpyxl")
        res = validate_sts_xlsm(self._write(tmp_path, [self._tc(1), self._tc(2)]))
        st = res["stats"]
        assert st["tc_count"] == 2
        assert st["no_step_tcs"] == 0        # 과거엔 TestEnvironment 채움을 보고 판단했다
        assert st["no_expected_tcs"] == 0    # 과거엔 TestMethod 채움을 보고 판단했다
        assert st["reqs_linked"] == 2 and st["req_linkage_pct"] == 100.0
        assert res["valid"] is True

    def test_empty_action_and_expected_is_a_defect_not_a_pass(self, tmp_path):
        """Action·Expected가 비었는데 다른 열이 차 있으면 — 정확히 과거의 거짓 PASS 조건."""
        from generators.sts import validate_sts_xlsm
        pytest.importorskip("openpyxl")
        blank = [{"action": "", "expected": ""}]
        path = self._write(tmp_path, [self._tc(1, steps=blank), self._tc(2, steps=blank)])
        res = validate_sts_xlsm(path)
        st = res["stats"]
        assert st["tc_count"] == 2
        assert st["no_step_tcs"] == 2
        assert st["no_expected_tcs"] == 2
        assert res["valid"] is False, res
        assert any("action steps" in i for i in res["issues"]), res["issues"]
        assert any("expected results" in i for i in res["issues"]), res["issues"]

    def test_requirement_linkage_is_not_safety_flag(self, tmp_path):
        """요구 링크율은 SRS 열에서 온다 — Safety Related 채움률이 아니다."""
        from generators.sts import validate_sts_xlsm
        pytest.importorskip("openpyxl")
        # safety_related는 두 TC 모두 "X"(채움), srs_id는 하나만 있음
        path = self._write(tmp_path, [self._tc(1, srs="SwTR_0101"), self._tc(2, srs="")])
        st = validate_sts_xlsm(path)["stats"]
        assert st["reqs_linked"] == 1
        assert st["req_linkage_pct"] == 50.0

    def test_multi_step_tc_counted_once(self, tmp_path):
        """Action/Expected는 스텝마다 있고 TC ID는 첫 행에만 있다 — TC 블록 단위 판정."""
        from generators.sts import validate_sts_xlsm
        pytest.importorskip("openpyxl")
        steps = [{"action": "", "expected": ""}, {"action": "두번째 스텝", "expected": "결과"}]
        st = validate_sts_xlsm(self._write(tmp_path, [self._tc(1, steps=steps)]))["stats"]
        assert st["tc_count"] == 1
        assert st["no_step_tcs"] == 0        # 블록 안 어딘가에 Action이 있으면 보유로 본다
        assert st["no_expected_tcs"] == 0

    def test_shifted_template_is_read_by_header(self, tmp_path):
        """템플릿 열이 밀려도 헤더 라벨로 따라간다(상수만 믿으면 엉뚱한 열을 읽는다)."""
        from generators.sts import _COL_HEADERS, _HEADER_ROW, validate_sts_xlsm
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "3.SW Integration Test Spec"
        shift = 2
        for ci, hdr in enumerate(_COL_HEADERS, 1):
            ws.cell(row=_HEADER_ROW, column=ci + shift, value=hdr)
        r = _HEADER_ROW + 1
        ws.cell(row=r, column=2 + shift, value="STS_001")
        ws.cell(row=r, column=3 + shift, value="제목")
        ws.cell(row=r, column=11 + shift, value="액션")
        ws.cell(row=r, column=12 + shift, value="기대결과")
        ws.cell(row=r, column=13 + shift, value="SwTR_0101")
        out = tmp_path / "shifted.xlsx"
        wb.save(str(out))
        st = validate_sts_xlsm(str(out))["stats"]
        assert st["tc_count"] == 1
        assert st["no_step_tcs"] == 0 and st["no_expected_tcs"] == 0
        assert st["reqs_linked"] == 1

    def test_missing_header_falls_back_and_warns(self, tmp_path):
        """헤더가 없는 산출물은 상수 위치로 읽되, 그 사실을 경고로 남긴다(침묵 금지)."""
        from generators.sts import _HEADER_ROW, STS_COL, validate_sts_xlsm
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "3.SW Integration Test Spec"
        r = _HEADER_ROW + 1
        ws.cell(row=r, column=STS_COL["tc_id"], value="STS_001")
        ws.cell(row=r, column=STS_COL["action"], value="액션")
        ws.cell(row=r, column=STS_COL["expected"], value="기대결과")
        out = tmp_path / "noheader.xlsx"
        wb.save(str(out))
        res = validate_sts_xlsm(str(out))
        assert res["stats"]["tc_count"] == 1
        assert any("상수 위치로 판독" in w for w in res["warnings"]), res["warnings"]

    def test_suts_module_reexport_uses_sts_impl(self, tmp_path):
        """기존 import 경로(generators.suts)도 새 구현을 쓴다."""
        from generators.sts import validate_sts_xlsm as via_sts
        from generators.suts import validate_sts_xlsm as via_suts
        pytest.importorskip("openpyxl")
        path = self._write(tmp_path, [self._tc()])
        assert via_suts(path)["stats"] == via_sts(path)["stats"]
