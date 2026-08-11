# tests/unit/test_generators_suts.py
"""Unit tests for generators.suts core functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from generators.suts import (
    collect_unit_functions,
    determine_gen_method,
    determine_test_method,
    generate_sequences,
    generate_suts_xlsm,
    get_boundary_values,
    infer_variable_type,
)


class TestCollectUnitFunctions:
    @pytest.fixture()
    def sample_function_details(self):
        return {
            "SwUFn_001": {
                "id": "SwUFn_001",
                "name": "S_Motor_Init",
                "prototype": "void S_Motor_Init(U8 mode)",
                "inputs": ["[IN] U8 mode"],
                "outputs": [],
                "globals_global": ["g_MotorState"],
                "globals_static": ["s_MotorFlag"],
                "logic_flow": [],
            },
        }

    def test_basic_collection(self, sample_function_details):
        units = collect_unit_functions(sample_function_details)
        assert len(units) == 1
        assert units[0]["name"] == "S_Motor_Init"
        assert units[0]["fid"] == "SwUFn_001"

    def test_empty_details(self):
        units = collect_unit_functions({})
        assert units == []

    def test_ignores_invalid_entries(self):
        details = {"SwUFn_001": "not_a_dict"}
        units = collect_unit_functions(details)
        assert units == []

    def test_ignores_nameless(self):
        details = {"SwUFn_001": {"id": "SwUFn_001", "name": ""}}
        units = collect_unit_functions(details)
        assert units == []

    def test_fills_asil_from_sds_when_missing(self, monkeypatch):
        details = {
            "SwUFn_001": {
                "id": "SwUFn_001",
                "name": "S_Motor_Init",
                "prototype": "void S_Motor_Init(void)",
                "module_name": "MotorCtrl_PDS",
                "asil": "TBD",
            }
        }

        monkeypatch.setattr(
            "generators.suts._load_default_sds_map",
            lambda: {
                "motor control": {
                    "asil": "A",
                    "related": "SwTR_0101",
                    "description": "Motor control logic",
                }
            },
        )

        units = collect_unit_functions(details)

        assert units[0]["asil"] == "A"


class TestInferVariableType:
    def test_uint8_prefix(self):
        result = infer_variable_type("u8_MotorSpeed")
        assert "8" in result or "uint" in result.lower()

    def test_bool_prefix(self):
        result = infer_variable_type("b_IsReady")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_unknown(self):
        result = infer_variable_type("someRandomVar")
        assert isinstance(result, str)
        assert len(result) > 0


class TestGetBoundaryValues:
    def test_uint8(self):
        bv = get_boundary_values("uint8_t")
        assert "min" in bv
        assert "max" in bv
        assert bv["min"] == 0
        assert bv["max"] == 255

    def test_uint16(self):
        bv = get_boundary_values("uint16_t")
        assert bv["max"] == 65535

    def test_unknown_defaults(self):
        bv = get_boundary_values("completely_unknown_type")
        assert "min" in bv
        assert "max" in bv


class TestDetermineGenMethod:
    def test_with_logic(self):
        unit = {"logic_flow": [{"type": "if", "condition": "x > 0"}], "input_vars": ["x"]}
        method = determine_gen_method(unit)
        assert isinstance(method, str)
        assert len(method) > 0

    def test_without_logic(self):
        unit = {"logic_flow": [], "input_vars": ["x"]}
        method = determine_gen_method(unit)
        assert isinstance(method, str)


class TestDetermineTestMethod:
    def test_review_when_no_inputs_and_no_logic(self):
        unit = {"logic_flow": [], "input_vars": []}
        assert determine_test_method(unit) == "RVW"

    def test_fit_when_inputs_exist(self):
        unit = {"logic_flow": [], "input_vars": ["x"]}
        assert determine_test_method(unit) == "FIT"

    def test_fnct_when_logic_exists(self):
        unit = {"logic_flow": [{"type": "if", "condition": "x > 0"}], "input_vars": ["x"]}
        assert determine_test_method(unit) == "FNCT"


class TestGenerateSequences:
    def test_basic_sequences(self):
        unit = {
            "name": "S_Motor_Init",
            "input_vars": ["u8_mode"],
            "output_vars": ["g_MotorState"],
            "logic_flow": [],
        }
        seqs = generate_sequences(unit)
        assert len(seqs) >= 1
        for seq in seqs:
            assert "seq_num" in seq
            assert "inputs" in seq
            assert "expected" in seq
            assert "strategy" in seq

    def test_no_vars(self):
        unit = {"name": "S_Nop", "input_vars": [], "output_vars": [], "logic_flow": []}
        seqs = generate_sequences(unit)
        assert len(seqs) == 3
        assert [seq["strategy"] for seq in seqs] == ["NORMAL_CALL", "ERROR_PATH", "REPEAT_CALL"]

    def test_max_seq_limit(self):
        unit = {
            "name": "S_Motor_Init",
            "input_vars": ["u8_mode"],
            "output_vars": [],
            "logic_flow": [],
        }
        seqs = generate_sequences(unit, max_seq=2)
        assert len(seqs) <= 2


class TestGenerateSutsWorkbook:
    def test_fixed_columns_are_populated(self, tmp_path: Path):
        units = [{
            "fid": "SwUFn_001",
            "name": "S_Motor_Init",
            "prototype": "void S_Motor_Init(U8 mode)",
            "component": "SwCom_01\n(Module)",
            "input_vars": ["u8_mode"],
            "output_vars": ["u8g_status"],
            "logic_flow": [{"type": "if", "condition": "u8_mode > 0"}],
            "calls_list": [],
            "description": "Initialize motor state",
            "asil": "ASIL-B",
            "precondition": "Power on reset complete",
        }]
        all_sequences = {
            "SwUFn_001": [{
                "seq_num": 1,
                "inputs": {"u8_mode": 0},
                "expected": {"u8g_status": 1},
                "strategy": "BV_MIN",
            }]
        }
        out_path = tmp_path / "suts_test.xlsx"

        generate_suts_xlsm(None, units, all_sequences, str(out_path), {"project_id": "TEST"})

        openpyxl = pytest.importorskip("openpyxl")
        from generators.suts import (
            _COL_GEN,
            _COL_INDEX,
            _COL_METHOD,
            _COL_SAFETY,
            _COL_TC_ID,
            _COL_UNIT,
            _DATA_START_ROW,
            _SEQ_COL,
        )
        wb = openpyxl.load_workbook(str(out_path), read_only=True, data_only=True)
        ws = wb["2.SW Unit Test Spec"]
        tc_row = _DATA_START_ROW          # 변수명 행(정본 구조)
        seq_row = _DATA_START_ROW + 1     # 첫 시퀀스 행
        assert ws.cell(row=tc_row, column=_COL_INDEX).value == 1
        assert ws.cell(row=tc_row, column=_COL_TC_ID).value == "SwUTC_SwUFn_001"
        assert ws.cell(row=tc_row, column=_COL_UNIT).value == "S_Motor_Init"
        # ⚠ `O` 여야 한다. 예전엔 안전 관련에 `X` 를 찍어 **정본과 의미가 반대**였다.
        assert ws.cell(row=tc_row, column=_COL_SAFETY).value == "O"
        # Test Method / TC Gen Method 는 TC 행이 아니라 **시퀀스 그룹 행**에 온다.
        assert ws.cell(row=tc_row, column=_COL_METHOD).value is None
        assert ws.cell(row=seq_row, column=_SEQ_COL).value == 1
        assert ws.cell(row=seq_row, column=_COL_METHOD).value == "REQ"
        assert ws.cell(row=seq_row, column=_COL_GEN).value == "AOR/ABV"
        wb.close()

    def test_out_of_range_sequences_are_marked_fault_injection(self, tmp_path):
        """정본은 유효 범위 밖 시퀀스를 `FI` 로 묶는다 — 한 method 로 뭉치면 안 된다."""
        from generators.suts import _COL_METHOD, _DATA_START_ROW, generate_suts_xlsm

        units = [{
            "fid": "SwUFn_001", "name": "f", "component": "SwCom_01",
            "input_vars": ["a"], "output_vars": [], "asil": "QM",
        }]
        seqs = {"SwUFn_001": [
            {"seq_num": 1, "strategy": "BV_MID", "inputs": {"a": 1}, "expected": {}},
            {"seq_num": 2, "strategy": "BV_MAX_INV", "inputs": {"a": 256}, "expected": {}},
        ]}
        out = tmp_path / "fi.xlsx"
        generate_suts_xlsm(None, units, seqs, str(out), {"project_id": "T"})

        openpyxl = pytest.importorskip("openpyxl")
        ws = openpyxl.load_workbook(str(out), read_only=True, data_only=True)["2.SW Unit Test Spec"]
        assert ws.cell(row=_DATA_START_ROW + 1, column=_COL_METHOD).value == "REQ"
        assert ws.cell(row=_DATA_START_ROW + 2, column=_COL_METHOD).value == "FI"

    def test_safety_related_never_invents_a_verdict(self):
        """근거 없는 ASIL 을 `X`(=확인했고 비안전)로 단정하지 않는다."""
        from generators.suts import resolve_safety_related

        assert resolve_safety_related("A") == "O"
        assert resolve_safety_related("ASIL-B") == "O"
        assert resolve_safety_related("QM") == "X"
        # 모르는 것은 빈칸이다 — `X` 로 적으면 under-classification 이다.
        assert resolve_safety_related("") == ""
        assert resolve_safety_related("TBD") == ""
        assert resolve_safety_related(None) == ""


class TestResolvedDocInput:
    r"""문서 입력(SRS/UDS/HSIS)은 resolver 경유로 확보한다.

    회귀 대상: `Path(p).is_file()`만 보던 코드는 cloudium worker-only 경로(U:\ 등)에서
    항상 False라 보강 블록을 **경고 없이** 통째로 건너뛰었다.
    """

    def test_local_file_is_passed_through_without_copy(self, tmp_path):
        from generators.suts import _resolved_doc_input
        src = tmp_path / "SRS.docx"
        src.write_bytes(b"payload")
        with _resolved_doc_input(str(src), "SRS") as p:
            assert p == str(src)      # 로컬이면 임시 복사 없음

    def test_blank_path_yields_none(self):
        from generators.suts import _resolved_doc_input
        with _resolved_doc_input("", "SRS") as p:
            assert p is None
        with _resolved_doc_input(None, "UDS") as p:
            assert p is None

    def test_worker_only_path_is_materialized(self, monkeypatch, tmp_path):
        """로컬에 없지만 resolver가 읽을 수 있으면 임시 파일로 실체화한다."""
        import backend.services.file_resolver as fr
        from generators.suts import _resolved_doc_input

        remote = "U:/docs/HSIS.xlsx"

        class _Worker:
            mode = "cloudium"
            def is_file(self, p):
                return str(p) == remote
            def read_bytes(self, p):
                return b"remote-bytes"

        monkeypatch.setattr(fr, "get_resolver", lambda: _Worker())
        seen = {}
        with _resolved_doc_input(remote, "HSIS") as p:
            assert p is not None and p != remote
            assert Path(p).read_bytes() == b"remote-bytes"
            assert Path(p).suffix == ".xlsx"   # 파서가 확장자로 분기하므로 보존 필수
            seen["path"] = p
        # with 종료 시 정리
        assert not Path(seen["path"]).exists()

    def test_missing_everywhere_yields_none_with_warning(self, monkeypatch, caplog):
        import backend.services.file_resolver as fr
        from generators.suts import _resolved_doc_input

        class _Empty:
            mode = "cloudium"
            def is_file(self, p):
                return False
            def read_bytes(self, p):
                raise AssertionError("read_bytes must not be called when is_file() is False")

        monkeypatch.setattr(fr, "get_resolver", lambda: _Empty())
        with caplog.at_level("WARNING", logger="generators.suts"):
            with _resolved_doc_input("U:/nope.docx", "SRS") as p:
                assert p is None
        # 침묵 skip이 원래 결함이었다 — 사유가 반드시 남아야 한다
        assert "SRS" in caplog.text and "nope.docx" in caplog.text, caplog.text

    def test_read_failure_does_not_raise(self, monkeypatch):
        """resolver가 있다고 했는데 읽기가 깨져도 생성 자체는 계속된다(보강만 생략)."""
        import backend.services.file_resolver as fr
        from generators.suts import _resolved_doc_input

        class _Broken:
            mode = "cloudium"
            def is_file(self, p):
                return True
            def read_bytes(self, p):
                raise OSError("worker timeout")

        monkeypatch.setattr(fr, "get_resolver", lambda: _Broken())
        with _resolved_doc_input("U:/x.docx", "UDS") as p:
            assert p is None


class TestSdsMapIsProjectScoped:
    """`sds_docx_path`가 실제로 ASIL 출처가 되어야 한다.

    회귀 대상: 이 인자는 시그니처·docstring에만 있고 본문에서 쓰이지 않아, ASIL이 항상
    저장소 `docs/` 글롭(현재 HDPDM01 SDS)에서 채워졌다 — 다른 프로젝트의 SUTS를 만들어도
    HDPDM01의 안전 등급이 조용히 섞이는 경로였다.
    """

    _DETAILS = {
        "SwUFn_001": {
            "id": "SwUFn_001",
            "name": "S_Motor_Init",
            "prototype": "void S_Motor_Init(void)",
            "module_name": "MotorCtrl_PDS",
            "asil": "TBD",
        }
    }

    def test_injected_map_wins_over_repo_docs_fallback(self, monkeypatch):
        from generators import suts as gsuts

        called = {"default": 0}
        monkeypatch.setattr(gsuts, "_load_default_sds_map",
                            lambda: called.__setitem__("default", called["default"] + 1) or {
                                "motor control": {"asil": "D", "related": "", "description": ""}})

        units = gsuts.collect_unit_functions(
            self._DETAILS, None,
            sds_map={"motor control": {"asil": "A", "related": "SwTR_0101", "description": ""}},
        )
        assert units[0]["asil"] == "A", "주입한 SDS 맵이 무시되고 폴백이 쓰였다"
        assert called["default"] == 0, "sds_map을 줬는데도 저장소 docs/ 폴백을 읽었다"

    def test_no_map_still_uses_fallback(self, monkeypatch):
        """대조군: 맵을 안 주면 기존 폴백 동작이 그대로여야 한다."""
        from generators import suts as gsuts
        monkeypatch.setattr(gsuts, "_load_default_sds_map",
                            lambda: {"motor control": {"asil": "D", "related": "", "description": ""}})
        units = gsuts.collect_unit_functions(self._DETAILS, None)
        assert units[0]["asil"] == "D"

    def test_resolve_returns_none_and_warns_when_path_unusable(self, monkeypatch, caplog):
        """지정했는데 못 쓰면 폴백이 조용히 대신하면 안 된다 — 경고가 남아야 한다."""
        import backend.services.file_resolver as fr
        from generators.suts import _resolve_sds_map

        class _Empty:
            mode = "cloudium"
            def is_file(self, p):
                return False
            def read_bytes(self, p):
                raise AssertionError("호출되면 안 됨")

        monkeypatch.setattr(fr, "get_resolver", lambda: _Empty())
        with caplog.at_level("WARNING", logger="generators.suts"):
            assert _resolve_sds_map("U:/nope/SDS.docx") is None
        assert "SDS" in caplog.text and "폴백" in caplog.text, caplog.text

    def test_resolve_returns_none_and_warns_when_map_is_empty(self, monkeypatch, caplog, tmp_path):
        from generators import suts as gsuts
        src = tmp_path / "SDS.docx"
        src.write_bytes(b"x")
        monkeypatch.setattr(gsuts, "load_sds_map_from", lambda p: {})
        with caplog.at_level("WARNING", logger="generators.suts"):
            assert gsuts._resolve_sds_map(str(src)) is None
        assert "파티션 0건" in caplog.text, caplog.text

    def test_resolve_passes_map_through(self, monkeypatch, tmp_path):
        from generators import suts as gsuts
        src = tmp_path / "SDS.docx"
        src.write_bytes(b"x")
        expected = {"motor control": {"asil": "B", "related": "", "description": ""}}
        monkeypatch.setattr(gsuts, "load_sds_map_from", lambda p: expected)
        assert gsuts._resolve_sds_map(str(src)) == expected

    def test_blank_path_is_not_an_error(self):
        from generators.suts import _resolve_sds_map
        assert _resolve_sds_map(None) is None
        assert _resolve_sds_map("") is None

    def test_load_sds_map_from_survives_parse_failure(self, monkeypatch, caplog):
        from generators import suts as gsuts

        def _boom(_p):
            raise ValueError("깨진 docx")

        monkeypatch.setattr(gsuts, "_extract_sds_partition_map", _boom)
        with caplog.at_level("WARNING", logger="generators.suts"):
            assert gsuts.load_sds_map_from("x.docx") == {}
        assert "파싱 실패" in caplog.text
