"""Unit tests for report_gen.validation pure-logic functions."""
from __future__ import annotations

import pytest


class TestValidCallNames:
    def test_filters_keywords_and_short_upper(self):
        from report_gen.validation import _valid_call_names

        result = _valid_call_names(["if", "for", "U8", "MotorCtrl_Run", "sizeof"])
        assert result == ["MotorCtrl_Run"]

    def test_deduplicates(self):
        from report_gen.validation import _valid_call_names

        result = _valid_call_names(["FuncA", "FuncB", "FuncA"])
        assert result == ["FuncA", "FuncB"]

    def test_rejects_invalid_identifiers(self):
        from report_gen.validation import _valid_call_names

        # _valid_call_names normalizes via _normalize_symbol_name, extracting
        # the first valid identifier token from each input string.
        result = _valid_call_names(["foo bar", "123bad", "good_func"])
        assert "good_func" in result

    def test_string_input_extracted(self):
        from report_gen.validation import _valid_call_names

        result = _valid_call_names("MotorPwm_Set()\nLinDrv_Init()")
        assert "MotorPwm_Set" in result
        assert "LinDrv_Init" in result

    def test_empty_input(self):
        from report_gen.validation import _valid_call_names

        assert _valid_call_names([]) == []
        assert _valid_call_names("") == []


class TestPayloadFunctionDetailsByName:
    def test_extracts_from_both_keys(self):
        from report_gen.validation import _payload_function_details_by_name

        payload = {
            "function_details_by_name": {
                "FuncA": {"name": "FuncA", "desc": "a"}
            },
            "function_details": {
                "SwUFn_01": {"name": "FuncB", "desc": "b"}
            },
        }
        result = _payload_function_details_by_name(payload)
        assert "funca" in result
        assert "funcb" in result

    def test_empty_payload(self):
        from report_gen.validation import _payload_function_details_by_name

        assert _payload_function_details_by_name({}) == {}

    def test_skips_non_dict_info(self):
        from report_gen.validation import _payload_function_details_by_name

        payload = {"function_details": {"x": "not_a_dict"}}
        assert _payload_function_details_by_name(payload) == {}


class TestHasDocOutputSlot:
    def test_void_returns_false(self):
        from report_gen.validation import _has_doc_output_slot

        assert _has_doc_output_slot("void Foo(void)") is False

    def test_const_ptr_returns_false(self):
        from report_gen.validation import _has_doc_output_slot

        assert _has_doc_output_slot("void Foo(const uint8 *src)") is False

    def test_mutable_ptr_returns_true(self):
        from report_gen.validation import _has_doc_output_slot

        assert _has_doc_output_slot("void Foo(uint8 *dst)") is True

    def test_struct_param_returns_true(self):
        from report_gen.validation import _has_doc_output_slot

        assert _has_doc_output_slot("void Foo(struct Config cfg)") is True

    def test_no_parens_returns_false(self):
        from report_gen.validation import _has_doc_output_slot

        assert _has_doc_output_slot("just_text") is False

    def test_empty_returns_false(self):
        from report_gen.validation import _has_doc_output_slot

        assert _has_doc_output_slot("") is False


class TestHasDocInputSlot:
    def test_void_returns_false(self):
        from report_gen.validation import _has_doc_input_slot

        assert _has_doc_input_slot("void Foo(void)") is False

    def test_with_params_returns_true(self):
        from report_gen.validation import _has_doc_input_slot

        assert _has_doc_input_slot("void Foo(uint8 x)") is True

    def test_empty_returns_false(self):
        from report_gen.validation import _has_doc_input_slot

        assert _has_doc_input_slot("") is False


class TestSplitCsvish:
    def test_comma_separated(self):
        from report_gen.validation import _split_csvish

        assert _split_csvish("a, b, c") == ["a", "b", "c"]

    def test_mixed_separators(self):
        from report_gen.validation import _split_csvish

        result = _split_csvish("a/b;c,d")
        assert result == ["a", "b", "c", "d"]

    def test_deduplicates(self):
        from report_gen.validation import _split_csvish

        assert _split_csvish("a, b, a") == ["a", "b"]

    def test_empty(self):
        from report_gen.validation import _split_csvish

        assert _split_csvish("") == []


class TestCleanParamLines:
    def test_filters_na_and_empty(self):
        from report_gen.validation import _clean_param_lines

        result = _clean_param_lines(["uint8 x", "N/A", "", "TBD", "uint16 y"])
        assert result == ["uint8 x", "uint16 y"]

    def test_filters_header_row(self):
        from report_gen.validation import _clean_param_lines

        result = _clean_param_lines(["No Name Type Range Reset Description"])
        assert result == []

    def test_deduplicates(self):
        from report_gen.validation import _clean_param_lines

        result = _clean_param_lines(["param_a", "param_a"])
        assert result == ["param_a"]

    def test_string_input(self):
        from report_gen.validation import _clean_param_lines

        result = _clean_param_lines("single_param")
        assert result == ["single_param"]


class TestParseAccuracySummary:
    def test_parses_full_report(self):
        from report_gen.validation import _parse_accuracy_summary

        text = (
            "# Called/Calling Accuracy Report\n"
            "- Total functions compared: `42`\n"
            "- Called exact match: `35` / `42` (83.3%)\n"
            "- Calling exact match: `30` / `42` (71.4%)\n"
            "\n"
            "## SwCom_01\n"
            "- Functions: `10`\n"
            "- Called exact match: `8` / `10` (80.0%)\n"
            "- Calling exact match: `7` / `10` (70.0%)\n"
        )
        result = _parse_accuracy_summary(text)
        assert result["total_functions"] == 42
        assert result["called_exact_match"] == "83.3%"
        assert result["calling_exact_match"] == "71.4%"
        assert result["swcom_01_called_exact_match"] == "80.0%"
        assert result["swcom_01_calling_exact_match"] == "70.0%"

    def test_empty_text(self):
        from report_gen.validation import _parse_accuracy_summary

        result = _parse_accuracy_summary("")
        assert result["total_functions"] == 0


class TestParseQualityGateSummary:
    def test_parses_gate_and_metrics(self):
        from report_gen.validation import _parse_quality_gate_summary

        text = (
            "- Gate pass: `true`\n"
            "- Description fill: `30` / `42` (71.4%)\n"
            "- Called fill: `25` / `42` (59.5%)\n"
        )
        result = _parse_quality_gate_summary(text)
        assert result["gate_pass"] == "true"
        assert "description_fill" in result["metrics"]
        assert result["metrics"]["description_fill"] == "71.4%"

    def test_empty(self):
        from report_gen.validation import _parse_quality_gate_summary

        result = _parse_quality_gate_summary("")
        assert result["gate_pass"] == ""
        assert result["metrics"] == {}


class TestLoadUdsPayloadForDocx:
    def test_no_file_returns_empty(self, tmp_path):
        from report_gen.validation import _load_uds_payload_for_docx

        result = _load_uds_payload_for_docx(str(tmp_path / "nonexist.docx"))
        assert result == {}

    def test_loads_payload_json(self, tmp_path):
        import json
        from report_gen.validation import _load_uds_payload_for_docx

        docx_path = tmp_path / "test.docx"
        docx_path.write_text("dummy")
        payload_path = tmp_path / "test.payload.full.json"
        payload_path.write_text(json.dumps({"functions": 42}), encoding="utf-8")
        result = _load_uds_payload_for_docx(str(docx_path))
        assert result == {"functions": 42}


class TestGenerateUdsConstraintsReport:
    def test_generates_report(self, tmp_path):
        from report_gen.validation import generate_uds_constraints_report

        payload = {
            "function_details_by_name": {
                "motor_init": {
                    "id": "SwUFn_0101",
                    "name": "Motor_Init",
                    "description": "Init motor",
                    "asil": "B",
                    "related": "SwTR_001",
                }
            }
        }
        out = tmp_path / "constraints.md"
        result = generate_uds_constraints_report(payload, str(out))
        assert (tmp_path / "constraints.md").exists()
        text = out.read_text(encoding="utf-8")
        assert "UDS Constraint" in text
        assert "Functions: `1`" in text

    def test_empty_payload(self, tmp_path):
        from report_gen.validation import generate_uds_constraints_report

        out = tmp_path / "constraints.md"
        generate_uds_constraints_report({}, str(out))
        text = out.read_text(encoding="utf-8")
        assert "Functions: `0`" in text

    def test_function_details_fallback(self, tmp_path):
        from report_gen.validation import generate_uds_constraints_report

        payload = {
            "function_details": {
                "SwUFn_0101": {
                    "id": "SwUFn_0101",
                    "name": "Func_A",
                    "description": "Desc",
                }
            }
        }
        out = tmp_path / "constraints2.md"
        generate_uds_constraints_report(payload, str(out))
        text = out.read_text(encoding="utf-8")
        assert "Functions: `1`" in text


class TestGenerateUdsValidationReport:
    """Test the MD report generation (docx structure is mocked via validate)."""

    def test_generates_report_file(self, tmp_path, monkeypatch):
        from report_gen.validation import generate_uds_validation_report

        # Mock validate_uds_docx_structure to avoid needing real docx
        fake_report = {
            "docx_path": "test.docx",
            "ok": True,
            "table_count": 5,
            "image_count": 2,
            "swufn_heading_count": 3,
            "function_info_table_count": 3,
            "logic_row_count": 3,
            "logic_with_image_count": 3,
            "top_headers": [{"header": "H1", "count": 5}],
            "issues": [],
        }
        monkeypatch.setattr(
            "report_gen.validation.validate_uds_docx_structure",
            lambda _: fake_report,
        )
        out = tmp_path / "validation.md"
        generate_uds_validation_report("test.docx", str(out))
        text = out.read_text(encoding="utf-8")
        assert "# UDS Validation Report" in text
        assert "OK: `True`" in text
        assert "Tables: `5`" in text


class TestValidateUdsDocxStructure:
    def test_missing_docx(self, tmp_path):
        from report_gen.validation import validate_uds_docx_structure

        result = validate_uds_docx_structure(str(tmp_path / "missing.docx"))
        assert result["ok"] is False
        assert any("not found" in i for i in result["issues"])

    def test_docx_not_installed(self, monkeypatch):
        from report_gen.validation import validate_uds_docx_structure
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "docx":
                raise ImportError("No module named 'docx'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        result = validate_uds_docx_structure("test.docx")
        assert result["ok"] is False


class TestGenerateAsilConfidenceReportAdvanced:
    """Test the confidence report with payload that covers many code paths."""

    def test_multiple_sources(self, tmp_path):
        from report_gen.validation import generate_asil_related_confidence_report

        payload = {
            "function_details_by_name": {
                "motor_init": {
                    "id": "SwUFn_0101",
                    "name": "Motor_Init",
                    "description": "Init motor module",
                    "description_source": "sds",
                    "description_source_detail": "hsis+sds_match",
                    "description_evidence_sources": ["sds", "code", "hsis"],
                    "asil": "B",
                    "asil_source": "srs",
                    "related": "SwTR_001",
                    "related_source": "sds",
                    "related_source_detail": "hsis+sds",
                    "related_evidence_sources": ["sds", "hsis"],
                },
                "sensor_check": {
                    "id": "SwUFn_0102",
                    "name": "Sensor_Check",
                    "description": "Check sensors",
                    "description_source": "comment",
                    "comment_description": "Read sensor values",
                    "asil": "A",
                    "asil_source": "inference",
                    "related": "TBD",
                    "related_source": "inference",
                },
                "unknown_func": {
                    "id": "SwUFn_0203",
                    "name": "UnknownFunc",
                    "description": "",
                    "description_source": "",
                    "asil": "",
                    "asil_source": "",
                    "related": "",
                    "related_source": "",
                },
            }
        }
        out = tmp_path / "confidence.md"
        generate_asil_related_confidence_report(payload, str(out))
        text = out.read_text(encoding="utf-8")
        assert "# ASIL/Related ID Confidence Report" in text
        assert "Total functions: `3`" in text
        assert "## Description Source" in text
        assert "## ASIL Source" in text
        assert "## Low Confidence Samples" in text
        assert "## Evidence Samples" in text
        assert "## Component (SwCom) Low Confidence Ratio" in text
        assert "SwCom_01" in text  # from SwUFn_0101, SwUFn_0102
        assert "SwCom_02" in text  # from SwUFn_0203

    def test_empty_payload(self, tmp_path):
        from report_gen.validation import generate_asil_related_confidence_report

        out = tmp_path / "confidence_empty.md"
        generate_asil_related_confidence_report({}, str(out))
        text = out.read_text(encoding="utf-8")
        assert "Total functions: `0`" in text

    def test_with_function_details_key(self, tmp_path):
        from report_gen.validation import generate_asil_related_confidence_report

        payload = {
            "function_details": {
                "SwUFn_0101": {
                    "id": "SwUFn_0101",
                    "name": "Motor_Init",
                    "description": "Init motor module",
                    "description_source": "ai",
                    "asil": "B",
                    "asil_source": "rule",
                    "related": "SwTR_001",
                    "related_source": "reference",
                }
            }
        }
        out = tmp_path / "confidence_alt.md"
        generate_asil_related_confidence_report(payload, str(out))
        text = out.read_text(encoding="utf-8")
        assert "Total functions: `1`" in text
