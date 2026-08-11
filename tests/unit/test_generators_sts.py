# tests/unit/test_generators_sts.py
"""Unit tests for generators.sts core functions."""

from __future__ import annotations

import pytest

from generators.sts import (
    _classify_req_type,
    _make_tc_id,
    generate_quality_report,
    generate_test_cases,
    generate_traceability_matrix,
    map_requirements_to_functions,
    parse_requirements_structured,
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
        from generators.sts import _HEADER_ROW, _SPEC_SHEET_NAME, STS_COL
        openpyxl = pytest.importorskip("openpyxl")
        path = self._write(tmp_path, [self._tc()])
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        # ⚠ 정본 시트명. 예전엔 SwITS 의 `3.SW Integration Test Spec` 에 쓰고 있었다.
        ws = wb[_SPEC_SHEET_NAME]
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
        from generators.sts import _COL_HEADERS, _HEADER_ROW, _SPEC_SHEET_NAME, validate_sts_xlsm
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = _SPEC_SHEET_NAME
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
        from generators.sts import _HEADER_ROW, _SPEC_SHEET_NAME, STS_COL, validate_sts_xlsm
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = _SPEC_SHEET_NAME
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


class TestHsisSignalCache:
    r"""HSIS 파서 캐시/행 판정 회귀.

    회귀 대상 2건 (실측 HDPDM01_HSIS v5.00):
      1) 캐시가 경로를 무시하는 단일 전역이라, 서버가 프로젝트 A의 HSIS를 한 번 읽으면
         이후 프로젝트 B의 STS/SUTS/SITS가 A의 HW 신호를 **동일 객체로** 받았다.
      2) `HSI_\d+` ID가 있는 행만 채택해, ID 열이 빈 행이 통째로 버려졌다(21건 중 1건 —
         'Battery Power / u16g_ApiIn_Vsup / SyEI_01').
    """

    # OLD 파서의 고정 0-based 열 → openpyxl 1-based
    _C_ID, _C_NAME, _C_TYPE = 6, 7, 8
    _C_DIR, _C_CHAR, _C_SWVAR, _C_REL = 12, 13, 20, 21

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        """모듈 전역 캐시는 테스트 간 누설되면 안 된다 — 원래 내용을 복원한다."""
        from generators.sts import _HSIS_SIGNALS_CACHE
        saved = dict(_HSIS_SIGNALS_CACHE)
        _HSIS_SIGNALS_CACHE.clear()
        yield
        _HSIS_SIGNALS_CACHE.clear()
        _HSIS_SIGNALS_CACHE.update(saved)

    def _write(self, path, rows):
        """rows: [(id, signal_name, sw_var, related), ...]"""
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "2.HSIS"
        ws.cell(row=4, column=self._C_ID, value="ID")
        ws.cell(row=4, column=self._C_NAME, value="Signal Name")
        ws.cell(row=4, column=self._C_SWVAR, value="SW Variable Name")
        ws.cell(row=4, column=self._C_REL, value="Related ID")
        for i, (sid, name, swvar, rel) in enumerate(rows):
            r = 5 + i
            ws.cell(row=r, column=self._C_ID, value=sid)
            ws.cell(row=r, column=self._C_NAME, value=name)
            ws.cell(row=r, column=self._C_TYPE, value="Digital")
            ws.cell(row=r, column=self._C_DIR, value="IN")
            ws.cell(row=r, column=self._C_CHAR, value="0...255")
            ws.cell(row=r, column=self._C_SWVAR, value=swvar)
            ws.cell(row=r, column=self._C_REL, value=rel)
        wb.save(str(path))
        wb.close()
        return str(path)

    def test_different_files_do_not_share_a_cached_result(self, tmp_path):
        from generators.sts import _load_hsis_signals
        a = self._write(tmp_path / "a.xlsx", [("HSI_01", "SIG_A", "u8g_A", "SwTR_0001")])
        b = self._write(tmp_path / "b.xlsx", [("HSI_02", "SIG_B", "u8g_B", "SwTR_0002")])

        ra = _load_hsis_signals(a)
        rb = _load_hsis_signals(b)

        assert ra["sw_var_names"] == ["u8g_A"]
        # 과거엔 여기서 A의 결과가 그대로 나왔다(경고 없음)
        assert rb["sw_var_names"] == ["u8g_B"], "두 번째 파일이 첫 파일 캐시를 받았다"
        assert rb is not ra

    def test_same_file_is_cached(self, tmp_path):
        from generators.sts import _load_hsis_signals
        p = self._write(tmp_path / "a.xlsx", [("HSI_01", "SIG_A", "u8g_A", "SwTR_0001")])
        assert _load_hsis_signals(p) is _load_hsis_signals(p)

    def test_cache_invalidates_when_file_changes(self, tmp_path):
        import time as _t

        from generators.sts import _load_hsis_signals
        p = tmp_path / "a.xlsx"
        self._write(p, [("HSI_01", "SIG_A", "u8g_A", "SwTR_0001")])
        first = _load_hsis_signals(str(p))
        _t.sleep(0.01)
        self._write(p, [("HSI_01", "SIG_A", "u8g_CHANGED", "SwTR_0001")])
        second = _load_hsis_signals(str(p))
        assert second["sw_var_names"] == ["u8g_CHANGED"], "mtime/size 변경이 무효화되지 않았다"
        assert second is not first

    def test_cache_is_bounded(self, tmp_path):
        from generators.sts import _HSIS_CACHE_MAX, _HSIS_SIGNALS_CACHE, _load_hsis_signals
        for i in range(_HSIS_CACHE_MAX + 4):
            p = self._write(tmp_path / f"f{i}.xlsx", [(f"HSI_{i:02d}", "S", f"u8g_{i}", "SwTR_1")])
            _load_hsis_signals(p)
        assert len(_HSIS_SIGNALS_CACHE) <= _HSIS_CACHE_MAX

    def test_row_without_hsi_id_is_kept_when_related_has_req_id(self, tmp_path):
        """ID 열이 비어도 Related에 Sw/Sy 요구 ID가 있으면 데이터 행이다."""
        from generators.sts import _load_hsis_signals, parse_hsis_signals
        p = self._write(tmp_path / "a.xlsx", [
            ("HSI_01", "SIG_A", "u8g_A", "SwTR_0001"),
            ("", "Battery Power", "u16g_ApiIn_Vsup", "SyEI_01"),   # 과거 여기서 버려졌다
            ("", "설명 문구일 뿐", "", ""),                          # 진짜 비데이터 행 — 여전히 제외
        ])
        old = _load_hsis_signals(p)
        assert len(old["signals"]) == 2
        assert "u16g_ApiIn_Vsup" in old["sw_var_names"]

        # 두 파서가 같은 판정을 써야 한다(한쪽만 고치면 다른 쪽이 잠복한다)
        new = parse_hsis_signals(p)
        assert {(s["id"], s["sw_var_name"], s["related_id"]) for s in old["signals"]} == \
               {(s["id"], s["sw_var_name"], s["related_id"]) for s in new["signals"]}

    def test_data_row_predicate_rejects_noise(self):
        from generators.sts import _is_hsis_data_row
        assert _is_hsis_data_row("HSI_12", "")
        assert _is_hsis_data_row("HSI12", "")
        assert _is_hsis_data_row("", "SyEI_01")
        assert _is_hsis_data_row("", "SwTR_0101")
        assert not _is_hsis_data_row("", "")
        assert not _is_hsis_data_row("설명", "해당 없음")
        assert not _is_hsis_data_row(None, None)

    def test_unparseable_file_does_not_poison_other_files(self, tmp_path):
        """빈/깨진 HSIS의 empty 결과가 전역을 덮어 다른 파일까지 비우면 안 된다."""
        openpyxl = pytest.importorskip("openpyxl")
        from generators.sts import _load_hsis_signals
        blank = tmp_path / "blank.xlsx"
        wb = openpyxl.Workbook()
        wb.active.title = "2.HSIS"
        wb.save(str(blank))
        wb.close()

        assert _load_hsis_signals(str(blank))["signals"] == []
        good = self._write(tmp_path / "good.xlsx", [("HSI_01", "SIG_A", "u8g_A", "SwTR_0001")])
        assert _load_hsis_signals(good)["sw_var_names"] == ["u8g_A"]


class TestCoverageSeparatesVerificationMethod:
    r"""커버리지가 실행시험과 코드리뷰(RVW)를 구분해야 한다.

    회귀 대상: `generate_traceability_matrix`가 `test_method`를 전혀 보지 않고
    `srs_id`만으로 covered를 세, `_generate_review_steps`가 만든 RVW TC("소스 코드에서
    구현부 확인")가 실행 시험과 동일하게 계상됐다.
    실측(HDPDM01 SRS 63건): 보고 100.0% vs 실행시험 87.3% = 12.7%p 부풀림.
    """

    @staticmethod
    def _tc(tid, srs, method):
        return {"id": tid, "srs_id": srs, "test_method": method}

    @staticmethod
    def _reqs(*ids):
        return [{"id": i} for i in ids]

    def test_review_only_req_is_excluded_from_executable_axis(self):
        from generators.sts import generate_traceability_matrix
        trace = generate_traceability_matrix(
            [self._tc("T1", "SwTR_0001", "FIT"), self._tc("T2", "SwTR_0002", "RVW")],
            self._reqs("SwTR_0001", "SwTR_0002"),
        )
        cov = trace["coverage"]
        assert cov["covered_reqs"] == 2 and cov["pct"] == 100.0   # 기존 계약 불변
        assert cov["executable_covered_reqs"] == 1
        assert cov["executable_pct"] == 50.0
        assert cov["review_only_reqs"] == ["SwTR_0002"]
        assert cov["review_only_count"] == 1

    def test_req_with_both_methods_counts_as_executable(self):
        """같은 요구에 실행 TC가 하나라도 있으면 review-only가 아니다."""
        from generators.sts import generate_traceability_matrix
        cov = generate_traceability_matrix(
            [self._tc("T1", "SwTR_0001", "RVW"), self._tc("T2", "SwTR_0001", "FNCT")],
            self._reqs("SwTR_0001"),
        )["coverage"]
        assert cov["executable_covered_reqs"] == 1
        assert cov["review_only_reqs"] == []

    def test_all_executable_methods_count(self):
        from generators.sts import generate_traceability_matrix
        methods = ["FIT", "FNCT", "RBT", "ELCT"]
        tcs = [self._tc(f"T{i}", f"SwTR_000{i}", m) for i, m in enumerate(methods, 1)]
        cov = generate_traceability_matrix(tcs, self._reqs(*[t["srs_id"] for t in tcs]))["coverage"]
        assert cov["executable_covered_reqs"] == 4
        assert cov["review_only_count"] == 0

    def test_method_case_is_normalized(self):
        from generators.sts import generate_traceability_matrix
        cov = generate_traceability_matrix(
            [self._tc("T1", "SwTR_0001", "rvw")], self._reqs("SwTR_0001"))["coverage"]
        assert cov["review_only_count"] == 1

    def test_quality_report_names_the_review_only_reqs(self):
        from generators.sts import generate_quality_report, generate_traceability_matrix
        reqs = self._reqs("SwTR_0001", "SwTR_0002")
        tcs = [self._tc("T1", "SwTR_0001", "FIT"), self._tc("T2", "SwTR_0002", "RVW")]
        qr = generate_quality_report(tcs, generate_traceability_matrix(tcs, reqs))
        warns = qr["coverage_warnings"]
        assert len(warns) == 1
        assert "SwTR_0002" in warns[0] and "100.0" in warns[0] and "50.0" in warns[0]

    def test_no_warning_when_everything_is_executable(self):
        """대조군: 실행시험만 있으면 경고가 없어야 한다(무조건 경고 방지)."""
        from generators.sts import generate_quality_report, generate_traceability_matrix
        reqs = self._reqs("SwTR_0001")
        tcs = [self._tc("T1", "SwTR_0001", "FNCT")]
        qr = generate_quality_report(tcs, generate_traceability_matrix(tcs, reqs))
        assert qr["coverage_warnings"] == []


class TestReqFunctionMappingSdsSource:
    r"""요구-함수 매핑의 SDS 폴백은 프로젝트에 종속돼야 한다.

    회귀 대상: `map_requirements_to_functions`가 `_load_default_sds_map()`(저장소 docs/
    글롭)만 봤다. 실측(HDPDM01): 요구-함수 링크 5,992건이 **100%** 이 폴백에서 나왔고
    (끄면 0/63), 요구 ID는 프로젝트 간 네임스페이스가 겹쳐 오매핑이 걸러지지도 않는다.
    """

    _REQS = [{"id": "SwTR_0001"}, {"id": "SwTR_0002"}]
    _FD = {"SwUFn_001": {"id": "SwUFn_001", "name": "S_Motor_Init",
                         "module_name": "MotorCtrl", "related": ""}}

    def test_injected_map_wins_over_repo_docs_fallback(self, monkeypatch):
        from generators import sts as gsts
        monkeypatch.setattr(gsts, "_load_default_sds_map",
                            lambda: {"motorctrl": {"related": "SwTR_0002", "asil": "", "description": ""}})
        got = gsts.map_requirements_to_functions(
            self._REQS, self._FD,
            sds_map={"motorctrl": {"related": "SwTR_0001", "asil": "", "description": ""}},
        )
        assert got["SwTR_0001"] == ["SwUFn_001"], "주입한 SDS 맵이 무시됐다"
        assert got["SwTR_0002"] == [], "저장소 폴백이 주입을 덮었다"

    def test_none_still_uses_fallback(self, monkeypatch):
        """대조군: 안 주면 기존 폴백 동작 유지(후방 호환)."""
        from generators import sts as gsts
        monkeypatch.setattr(gsts, "_load_default_sds_map",
                            lambda: {"motorctrl": {"related": "SwTR_0002", "asil": "", "description": ""}})
        got = gsts.map_requirements_to_functions(self._REQS, self._FD)
        assert got["SwTR_0002"] == ["SwUFn_001"]

    def test_empty_injected_map_does_not_silently_fall_back(self, monkeypatch):
        """빈 dict를 명시로 주면 폴백을 쓰지 않는다(None과 구분)."""
        from generators import sts as gsts
        monkeypatch.setattr(gsts, "_load_default_sds_map",
                            lambda: {"motorctrl": {"related": "SwTR_0002", "asil": "", "description": ""}})
        got = gsts.map_requirements_to_functions(self._REQS, self._FD, sds_map={})
        assert got["SwTR_0001"] == [] and got["SwTR_0002"] == []


class TestTcCapTruncationIsSurfaced:
    r"""요구당 TC 상한이 끊어낸 함수들이 기록돼야 한다.

    회귀 대상: `max_tc_per_req`(기본 5)는 요구당 **함수 루프 자체**를 끊는다. 요구에
    함수가 수백 개 매핑되면 대부분이 시험 없이 남는데 그 사실이 어디에도 없었다.
    실측(HDPDM01): 매핑 함수 747개 중 TC 보유 48개(6.4%), 요구 35/37 이 상한 도달,
    그런데 요구 커버리지는 100.0%.
    """

    @staticmethod
    def _fd(n):
        return {f"SwUFn_{i:03d}": {"id": f"SwUFn_{i:03d}", "name": f"S_Fn_{i}",
                                   "prototype": f"void S_Fn_{i}(void)",
                                   "inputs": [], "outputs": [], "logic_flow": []}
                for i in range(1, n + 1)}

    def test_stats_record_functions_left_untested(self):
        from generators.sts import generate_test_cases
        fd = self._fd(10)
        stats = {}
        tcs = generate_test_cases(
            [{"id": "SwTR_0001", "req_type": "TR"}], fd,
            {"SwTR_0001": list(fd)}, {"max_tc_per_req": 5}, stats_out=stats,
        )
        assert len(tcs) == 5
        assert stats["max_tc_per_req"] == 5
        assert stats["mapped_functions"] == 10
        assert stats["functions_with_tc"] == 5
        assert stats["functions_without_tc"] == 5
        assert stats["function_tc_coverage_pct"] == 50.0
        assert stats["requirements_truncated"] == ["SwTR_0001"]
        assert stats["requirements_truncated_count"] == 1

    def test_no_truncation_recorded_when_under_cap(self):
        """대조군: 상한에 안 닿으면 절단 기록이 없어야 한다(무조건 경고 방지)."""
        from generators.sts import generate_test_cases
        fd = self._fd(2)
        stats = {}
        generate_test_cases([{"id": "SwTR_0001", "req_type": "TR"}], fd,
                            {"SwTR_0001": list(fd)}, {"max_tc_per_req": 5}, stats_out=stats)
        assert stats["functions_without_tc"] == 0
        assert stats["requirements_truncated"] == []
        assert stats["function_tc_coverage_pct"] == 100.0

    def test_stats_out_is_optional(self):
        """기존 호출부(4-arg)는 그대로 동작해야 한다."""
        from generators.sts import generate_test_cases
        fd = self._fd(3)
        assert generate_test_cases([{"id": "SwTR_0001", "req_type": "TR"}], fd,
                                   {"SwTR_0001": list(fd)}) != []

    def test_quality_report_warns_with_function_axis(self):
        from generators.sts import (
            generate_quality_report,
            generate_test_cases,
            generate_traceability_matrix,
        )
        fd = self._fd(10)
        reqs = [{"id": "SwTR_0001", "req_type": "TR"}]
        stats = {}
        tcs = generate_test_cases(reqs, fd, {"SwTR_0001": list(fd)},
                                  {"max_tc_per_req": 5}, stats_out=stats)
        qr = generate_quality_report(tcs, generate_traceability_matrix(tcs, reqs),
                                     generation_stats=stats)
        hit = [w for w in qr["coverage_warnings"] if "max_tc_per_req" in w]
        assert len(hit) == 1, qr["coverage_warnings"]
        assert "747" not in hit[0]                     # 실측 수치 하드코딩 금지
        assert "10개 중 5개" in hit[0] and "SwTR_0001" in hit[0]
        assert qr["generation_stats"]["functions_without_tc"] == 5

    def test_no_truncation_warning_when_all_functions_tested(self):
        from generators.sts import (
            generate_quality_report,
            generate_test_cases,
            generate_traceability_matrix,
        )
        fd = self._fd(2)
        reqs = [{"id": "SwTR_0001", "req_type": "TR"}]
        stats = {}
        tcs = generate_test_cases(reqs, fd, {"SwTR_0001": list(fd)},
                                  {"max_tc_per_req": 5}, stats_out=stats)
        qr = generate_quality_report(tcs, generate_traceability_matrix(tcs, reqs),
                                     generation_stats=stats)
        assert [w for w in qr["coverage_warnings"] if "max_tc_per_req" in w] == []

    def test_quality_report_without_stats_stays_backward_compatible(self):
        from generators.sts import generate_quality_report, generate_traceability_matrix
        tcs = [{"id": "T1", "srs_id": "SwTR_0001", "test_method": "FNCT",
                "steps": [{"action": "a", "expected": "b"}, {"action": "c", "expected": "d"}]}]
        qr = generate_quality_report(tcs, generate_traceability_matrix(tcs, [{"id": "SwTR_0001"}]))
        assert qr["generation_stats"] == {}
        assert [w for w in qr["coverage_warnings"] if "max_tc_per_req" in w] == []
