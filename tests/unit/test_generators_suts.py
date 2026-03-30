# tests/unit/test_generators_suts.py
"""Unit tests for generators.suts core functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from generators.suts import (
    collect_unit_functions,
    determine_test_method,
    infer_variable_type,
    get_boundary_values,
    determine_gen_method,
    generate_sequences,
    generate_suts_xlsm,
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
        wb = openpyxl.load_workbook(str(out_path), read_only=True, data_only=True)
        ws = wb["2.SW Unit Test Spec"]
        assert ws.cell(row=7, column=4).value == "S_Motor_Init"
        assert ws.cell(row=7, column=5).value
        assert ws.cell(row=7, column=6).value == "X"
        assert ws.cell(row=7, column=7).value == "SwTE_01"
        assert ws.cell(row=7, column=8).value == "FNCT"
        assert ws.cell(row=7, column=9).value
        assert ws.cell(row=7, column=10).value == "Power on reset complete"
        wb.close()
