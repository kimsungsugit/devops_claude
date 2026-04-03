"""Unit tests for report_gen.uds_generator — helper functions."""
from __future__ import annotations

import pytest


class TestGroupFunctionBlocksBySwcom:
    def test_groups_by_swcom(self):
        from report_gen.uds_generator import _group_function_blocks_by_swcom

        blocks = [
            {"swcom": "SwCom_01", "name": "A"},
            {"swcom": "SwCom_02", "name": "B"},
            {"swcom": "SwCom_01", "name": "C"},
        ]
        result = _group_function_blocks_by_swcom(blocks)
        assert len(result["SwCom_01"]) == 2
        assert len(result["SwCom_02"]) == 1

    def test_missing_swcom_gets_unknown(self):
        from report_gen.uds_generator import _group_function_blocks_by_swcom

        blocks = [{"name": "X"}]
        result = _group_function_blocks_by_swcom(blocks)
        assert "SwCom_Unknown" in result

    def test_empty(self):
        from report_gen.uds_generator import _group_function_blocks_by_swcom

        assert _group_function_blocks_by_swcom([]) == {}


class TestFormatFunctionBlockLines:
    def test_basic_block(self):
        from report_gen.uds_generator import _format_function_block_lines

        block = {
            "header": "SwUFn_0101: Motor_Init",
            "id": "SwUFn_0101",
            "name": "Motor_Init",
            "prototype": "void Motor_Init(void)",
            "description": "Init motor",
            "asil": "B",
            "related": "SwTR_001",
            "called": "Helper_A",
            "calling": "Main",
        }
        lines = _format_function_block_lines(block)
        assert any("SwUFn_0101" in ln for ln in lines)
        assert any("Motor_Init" in ln for ln in lines)
        assert any("ASIL" in ln for ln in lines)
        assert any("Called Function" in ln for ln in lines)

    def test_with_io_params(self):
        from report_gen.uds_generator import _format_function_block_lines

        block = {
            "header": "SwUFn_0101: Func",
            "inputs": ["[IN] uint8 x"],
            "outputs": ["[OUT] return uint8"],
            "logic": "present",
        }
        lines = _format_function_block_lines(block)
        assert any("Input Parameters" in ln for ln in lines)
        assert any("Output Parameters" in ln for ln in lines)
        assert any("Logic Diagram" in ln for ln in lines)

    def test_empty_block(self):
        from report_gen.uds_generator import _format_function_block_lines

        assert _format_function_block_lines({}) == []


class TestParseUdsPreviewHtml:
    def test_parses_sections(self):
        from report_gen.uds_generator import parse_uds_preview_html

        html = (
            "<h3>Overview</h3><ul><li>Item1</li><li>Item2</li></ul>"
            "<h3>Requirements</h3><ul><li>Req1</li></ul>"
            "<h3>Interfaces</h3><ul></ul>"
            "<h3>UDS Frames</h3><ul><li>Frame1</li></ul>"
            "<h3>Notes</h3><ul><li>Note1</li></ul>"
        )
        result = parse_uds_preview_html(html)
        assert len(result["Overview"]) == 2
        assert result["Requirements"] == ["Req1"]
        assert result["UDS Frames"] == ["Frame1"]

    def test_empty(self):
        from report_gen.uds_generator import parse_uds_preview_html

        assert parse_uds_preview_html("") == {}


class TestGenerateUdsPreviewMarkdown:
    def test_basic(self):
        from report_gen.uds_generator import generate_uds_preview_markdown

        payload = {
            "project_name": "TestProject",
            "overview": "Overview text",
            "requirements": "Req text",
            "interfaces": "Interface text",
            "uds_frames": "Frame text",
            "notes": "Note text",
        }
        result = generate_uds_preview_markdown(payload)
        assert "# TestProject" in result
        assert "## Overview" in result
        assert "## Requirements" in result
        assert "## Interfaces" in result

    def test_empty_payload(self):
        from report_gen.uds_generator import generate_uds_preview_markdown

        result = generate_uds_preview_markdown({})
        assert "# UDS Spec" in result  # default project name
        assert "## Overview" in result

    def test_with_ai_sections(self):
        from report_gen.uds_generator import generate_uds_preview_markdown

        payload = {
            "ai_sections": {
                "overview": {"text": "AI overview text"},
                "notes": {"text": "AI notes"},
            },
        }
        result = generate_uds_preview_markdown(payload)
        assert "AI overview" in result


class TestGenerateUdsLogicItems:
    def test_call_tree_mode(self):
        from report_gen.uds_generator import generate_uds_logic_items

        text = (
            "SwUFn_0101: Motor_Init\n"
            "Called Function FuncA\n"
            "FuncB\n"
            "Calling Function FuncC\n"
        )
        items = generate_uds_logic_items([text], "call_tree")
        assert len(items) >= 1
        assert "Called" in items[0]["description"] or "Calling" in items[0]["description"]

    def test_state_table_mode(self):
        from report_gen.uds_generator import generate_uds_logic_items

        text = (
            "SwUFn_0101: StateHandler\n"
            "transition ST_IDLE to ST_RUNNING\n"
        )
        items = generate_uds_logic_items([text], "state_table")
        assert len(items) >= 1
        assert "ST_IDLE" in items[0]["description"] or "N/A" in items[0]["description"]

    def test_invalid_mode(self):
        from report_gen.uds_generator import generate_uds_logic_items

        assert generate_uds_logic_items(["text"], "invalid") == []

    def test_empty(self):
        from report_gen.uds_generator import generate_uds_logic_items

        assert generate_uds_logic_items([], "call_tree") == []


class TestFunctionAnalyzerHelpers:
    """Additional coverage for function_analyzer pure functions used by uds_gen."""

    def test_strip_comments_and_strings(self):
        from report_gen.function_analyzer import _strip_comments_and_strings

        result = _strip_comments_and_strings('int x = 1; /* block */ // line\nchar *s = "hello";')
        assert "block" not in result
        assert "line" not in result
        assert "int x" in result

    def test_safe_eval_int(self):
        from report_gen.function_analyzer import _safe_eval_int

        assert _safe_eval_int("42") == 42
        assert _safe_eval_int("0x10") == 16
        assert _safe_eval_int("2 + 3") == 5
        assert _safe_eval_int("abc") is None
        assert _safe_eval_int("") is None

    def test_normalize_bracket_expr(self):
        from report_gen.function_analyzer import _normalize_bracket_expr

        text, val = _normalize_bracket_expr("MAX_SIZE", {"MAX_SIZE": "256"})
        assert text == "256"
        assert val == 256

    def test_normalize_bracket_expr_no_macro(self):
        from report_gen.function_analyzer import _normalize_bracket_expr

        text, val = _normalize_bracket_expr("10", {})
        assert text == "10"
        assert val == 10

    def test_split_param(self):
        from report_gen.function_analyzer import _split_param

        t, n, a = _split_param("uint8_t data[8]")
        assert n == "data"
        assert "8" in a

    def test_split_param_simple(self):
        from report_gen.function_analyzer import _split_param

        t, n, a = _split_param("int value")
        assert n == "value"
        assert a == ""

    def test_split_param_empty(self):
        from report_gen.function_analyzer import _split_param

        assert _split_param("") == ("", "", "")

    def test_extract_return_type(self):
        from report_gen.function_analyzer import _extract_return_type

        assert _extract_return_type("static uint8 Motor_Init(void)", "Motor_Init") == "uint8"
        assert _extract_return_type("void foo(void)", "foo") == "void"
        assert _extract_return_type("", "foo") == ""

    def test_classify_param_direction(self):
        from report_gen.function_analyzer import _classify_param_direction

        assert _classify_param_direction("const uint8 *src") == "[IN]"
        assert _classify_param_direction("uint8 *dst") == "[INOUT]"
        assert _classify_param_direction("uint8 data[8]") == "[INOUT]"
        assert _classify_param_direction("uint8 value") == "[IN]"

    def test_is_generic_description(self):
        from report_gen.function_analyzer import _is_generic_description

        assert _is_generic_description("") is True
        assert _is_generic_description("TBD") is True
        assert _is_generic_description("N/A") is True
        assert _is_generic_description("Actual motor init description") is False

    def test_classify_description_quality(self):
        from report_gen.function_analyzer import _classify_description_quality

        assert _classify_description_quality("", "") == "low"
        assert _classify_description_quality("Good motor description", "sds") == "high"
        assert _classify_description_quality("TBD", "sds") == "medium"
        assert _classify_description_quality("TBD", "") == "low"

    def test_split_func_name_words(self):
        from report_gen.function_analyzer import _split_func_name_words

        words = _split_func_name_words("s_MotorCtrl_Init")
        assert "Motor" in words or "MotorCtrl" in words
        assert "Init" in words

    def test_normalize_symbol_name(self):
        from report_gen.function_analyzer import _normalize_symbol_name

        assert _normalize_symbol_name("  Motor_Init  ") == "Motor_Init"
        assert _normalize_symbol_name("") == ""
        assert _normalize_symbol_name("a|b,c") == "a"

    def test_is_static_var(self):
        from report_gen.function_analyzer import _is_static_var

        assert _is_static_var("s_counter", {"s_counter": True}) is True
        assert _is_static_var("g_var", {"g_var": False}) is False

    def test_parse_signature_params(self):
        from report_gen.function_analyzer import _parse_signature_params

        result = _parse_signature_params("void foo(uint8 x, uint16 *y)")
        assert len(result) == 2
        assert _parse_signature_params("void foo(void)") == []
        assert _parse_signature_params("") == []

    def test_parse_signature_params_with_direction(self):
        from report_gen.function_analyzer import _parse_signature_params

        result = _parse_signature_params("void foo(const uint8 *src, uint8 *dst)", tag_direction=True)
        assert any("[IN]" in p for p in result)
        assert any("[INOUT]" in p for p in result)

    def test_parse_signature_outputs(self):
        from report_gen.function_analyzer import _parse_signature_outputs

        result = _parse_signature_outputs("uint8 foo(const uint8 *src, uint8 *dst)", "foo")
        assert any("return" in o for o in result)
        assert any("dst" in o for o in result)

    def test_parse_signature_outputs_void(self):
        from report_gen.function_analyzer import _parse_signature_outputs

        result = _parse_signature_outputs("void foo(uint8 x)", "foo")
        assert not any("return" in o for o in result)

    def test_fallback_function_description(self):
        from report_gen.function_analyzer import _fallback_function_description

        result = _fallback_function_description("Motor_Init")
        assert "초기화" in result
        result2 = _fallback_function_description("DiagCheck", ["Helper_A"])
        assert "Helper_A" in result2

    def test_enhance_function_description_main(self):
        from report_gen.function_analyzer import _enhance_function_description

        result = _enhance_function_description("main", ["Init_System", "Run_Task"])
        assert "POR" in result or "Power On Reset" in result

    def test_enhance_function_description_init_prefix(self):
        from report_gen.function_analyzer import _enhance_function_description

        result = _enhance_function_description("s_init_Motor")
        assert "초기화" in result

    def test_enhance_description_text_auto_gen(self):
        from report_gen.function_analyzer import _enhance_description_text

        result = _enhance_description_text("Motor_Init", "Auto-generated from code")
        assert "Motor" in result

    def test_enhance_description_text_empty_desc(self):
        from report_gen.function_analyzer import _enhance_description_text

        result = _enhance_description_text("DiagChecker", "")
        assert "점검" in result or "진단" in result

    def test_enhance_description_text_with_called(self):
        from report_gen.function_analyzer import _enhance_description_text

        result = _enhance_description_text("Motor_Update", "", ["Helper_A"])
        assert "Helper_A" in result

    def test_is_exact_generic(self):
        from report_gen.function_analyzer import _is_exact_generic

        assert _is_exact_generic("function") is True
        assert _is_exact_generic("N/A") is True
        assert _is_exact_generic("") is True
        assert _is_exact_generic("Motor init desc") is False

    def test_extract_condition_branch_calls_if(self):
        from report_gen.function_analyzer import _extract_condition_branch_calls

        body = "if (x) { FuncA(); } else { FuncB(); }"
        true_calls, false_calls = _extract_condition_branch_calls(body)
        assert "FuncA" in true_calls
        assert "FuncB" in false_calls

    def test_extract_condition_branch_calls_empty(self):
        from report_gen.function_analyzer import _extract_condition_branch_calls

        assert _extract_condition_branch_calls("") == ([], [])

    def test_extract_logic_terminal_paths(self):
        from report_gen.function_analyzer import _extract_logic_terminal_paths

        r, e = _extract_logic_terminal_paths("return 0;")
        assert r == "Return"
        # Test error detection with standalone keyword
        _, e2 = _extract_logic_terminal_paths("if (error) { goto fail; }")
        assert e2 == "Error End"

    def test_extract_logic_terminal_paths_empty(self):
        from report_gen.function_analyzer import _extract_logic_terminal_paths

        assert _extract_logic_terminal_paths("") == ("", "")

    def test_extract_primary_condition_if(self):
        from report_gen.function_analyzer import _extract_primary_condition

        result = _extract_primary_condition("if (g_state == RUNNING) { do_work(); }")
        assert "g_state" in result or "RUNNING" in result

    def test_extract_primary_condition_switch(self):
        from report_gen.function_analyzer import _extract_primary_condition

        body = "switch (mode) { case MODE_A: break; case MODE_B: break; }"
        result = _extract_primary_condition(body)
        assert "switch" in result.lower()
        assert "MODE_A" in result

    def test_extract_primary_condition_empty(self):
        from report_gen.function_analyzer import _extract_primary_condition

        assert _extract_primary_condition("") == ""

    def test_infer_precondition_from_body(self):
        from report_gen.function_analyzer import _infer_precondition_from_body

        body = "if (!initialized) { return; } do_work();"
        result = _infer_precondition_from_body(body, "process_data")
        assert "initialized" in result.lower()

    def test_infer_precondition_init_func(self):
        from report_gen.function_analyzer import _infer_precondition_from_body

        result = _infer_precondition_from_body("x = 0;", "Motor_Init")
        assert "N/A" in result

    def test_infer_precondition_empty(self):
        from report_gen.function_analyzer import _infer_precondition_from_body

        assert _infer_precondition_from_body("") == ""

    def test_format_param_entry_basic(self):
        from report_gen.function_analyzer import _format_param_entry

        result = _format_param_entry(
            "data", "uint8", "[8]", [], {}, False,
        )
        assert "data" in result
        assert "uint8" in result

    def test_format_param_entry_with_index(self):
        from report_gen.function_analyzer import _format_param_entry

        result = _format_param_entry(
            "buf", "uint8", "[MAX]", ["i"], {"MAX": "10"}, False,
        )
        assert "10" in result
        assert "idx" in result

    def test_format_param_entry_divisor(self):
        from report_gen.function_analyzer import _format_param_entry

        result = _format_param_entry("x", "int", "", [], {}, False, divisor=True)
        assert "divisor" in result

    def test_finalize_function_fields(self):
        from report_gen.function_analyzer import _finalize_function_fields

        info = {
            "name": "Motor_Init",
            "description": "",
            "asil": "",
            "related": "",
            "precondition": "",
            "inputs": None,
            "outputs": None,
            "globals_global": None,
            "globals_static": None,
            "called": "",
            "calling": "",
        }
        result = _finalize_function_fields(info)
        assert result["asil"] == "QM"
        assert result["related"] == "TBD"
        assert result["precondition"] == "N/A"
        assert isinstance(result["inputs"], list)
        assert result["description"]  # should be auto-generated

    def test_finalize_main(self):
        from report_gen.function_analyzer import _finalize_function_fields

        result = _finalize_function_fields({"name": "main"})
        assert "SwST_01" in result.get("related", "")

    def test_collect_var_usage_basic(self):
        from report_gen.function_analyzer import _collect_var_usage

        body = "g_counter = 5;\nif (g_counter > 0) { return; }"
        result = _collect_var_usage(body, ["g_counter"])
        assert result["g_counter"]["lhs"] is True
        assert result["g_counter"]["rhs"] is True

    def test_collect_var_usage_empty(self):
        from report_gen.function_analyzer import _collect_var_usage

        result = _collect_var_usage("", ["x"])
        assert result["x"]["lhs"] is False

    def test_build_function_info_rows(self):
        from report_gen.function_analyzer import _build_function_info_rows

        info = {
            "id": "SwUFn_0101",
            "name": "Motor_Init",
            "prototype": "void Motor_Init(void)",
            "description": "Init motor",
            "asil": "B",
            "related": "SwTR_001",
        }
        rows = _build_function_info_rows(info, 6)
        assert len(rows) > 0
        # Check that ID row is present
        flat = str(rows)
        assert "SwUFn_0101" in flat
