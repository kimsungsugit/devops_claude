"""Unit tests for backend/helpers/common.py pure utility functions."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import pytest

_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from backend.helpers.common import (
    _extract_param_name_simple,
    _has_meaningful_value,
    _has_trace_token,
    _is_relative_to,
    _json_safe,
    _normalize_asil_simple,
    _normalize_field_source,
    _normalize_symbol_simple,
    _compact_symbol_simple,
    _parse_path_list,
    _parse_signature_params_simple,
    _parse_signature_outputs_simple,
    _read_json,
    _safe_extract_zip,
    _safe_int,
    _split_csv,
    _split_signature_params,
    _write_json,
    _build_excel_artifact_summary,
    _infer_related_id_simple,
    _is_allowed_req_doc,
)


class TestSplitSignatureParams:
    def test_simple_params(self):
        assert _split_signature_params("int a, float b") == ["int a", "float b"]

    def test_nested_parens(self):
        result = _split_signature_params("void (*cb)(int), int x")
        assert len(result) == 2
        assert "(*cb)(int)" in result[0]

    def test_empty(self):
        assert _split_signature_params("") == []
        assert _split_signature_params(None) == []

    def test_single_param(self):
        assert _split_signature_params("int x") == ["int x"]


class TestExtractParamName:
    def test_simple(self):
        assert _extract_param_name_simple("int count") == "count"

    def test_pointer(self):
        assert _extract_param_name_simple("int *ptr") == "ptr"

    def test_function_pointer(self):
        assert _extract_param_name_simple("void (*callback)(int)") == "callback"

    def test_array(self):
        assert _extract_param_name_simple("int buf[10]") == "buf"

    def test_empty(self):
        assert _extract_param_name_simple("") == ""
        assert _extract_param_name_simple(None) == ""


class TestHasMeaningfulValue:
    def test_empty_string(self):
        assert _has_meaningful_value("") is False

    def test_na_values(self):
        assert _has_meaningful_value("N/A") is False
        assert _has_meaningful_value("TBD") is False
        assert _has_meaningful_value("-") is False

    def test_valid_string(self):
        assert _has_meaningful_value("some description") is True

    def test_list_with_items(self):
        assert _has_meaningful_value(["a", "b"]) is True

    def test_empty_list(self):
        assert _has_meaningful_value([]) is False

    def test_list_with_blanks(self):
        assert _has_meaningful_value(["", "  "]) is False


class TestNormalizeAsilSimple:
    def test_valid_levels(self):
        assert _normalize_asil_simple("ASIL-D") == "D"
        assert _normalize_asil_simple("A") == "A"
        assert _normalize_asil_simple("QM") == "QM"

    def test_invalid(self):
        assert _normalize_asil_simple("N/A") == ""
        assert _normalize_asil_simple("") == ""
        assert _normalize_asil_simple("X") == ""


class TestNormalizeFieldSource:
    def test_known(self):
        assert _normalize_field_source("comment") == "comment"
        assert _normalize_field_source("sds") == "sds"
        assert _normalize_field_source("rule") == "rule"

    def test_unknown(self):
        assert _normalize_field_source("unknown") == "inference"
        assert _normalize_field_source("") == "inference"


class TestHasTraceToken:
    def test_with_token(self):
        assert _has_trace_token("SwCom_001") is True
        assert _has_trace_token("related to SwFn_42") is True

    def test_without_token(self):
        assert _has_trace_token("no trace here") is False
        assert _has_trace_token("") is False


class TestNormalizeSymbol:
    def test_basic(self):
        assert _normalize_symbol_simple("Foo_Bar") == "foo_bar"

    def test_compact(self):
        assert _compact_symbol_simple("Foo_Bar") == "foobar"


class TestParsePathList:
    def test_json_array(self):
        assert _parse_path_list('["a.c", "b.c"]') == ["a.c", "b.c"]

    def test_csv(self):
        assert _parse_path_list("a.c, b.c") == ["a.c", "b.c"]

    def test_empty(self):
        assert _parse_path_list("") == []

    def test_semicolon(self):
        assert _parse_path_list("a.c;b.c") == ["a.c", "b.c"]


class TestParseSignatureParams:
    def test_void_params(self):
        result = _parse_signature_params_simple("void foo(void)")
        assert result == ["[IN] (none)"]

    def test_with_params(self):
        result = _parse_signature_params_simple("int add(int a, int b)")
        assert len(result) == 2
        assert all(r.startswith("[IN]") for r in result)

    def test_no_parens(self):
        assert _parse_signature_params_simple("int x") == []


class TestParseSignatureOutputs:
    def test_return_type(self):
        result = _parse_signature_outputs_simple("int foo(void)")
        assert any("[OUT] return int" in r for r in result)

    def test_void_return(self):
        result = _parse_signature_outputs_simple("void foo(int *buf)")
        assert any("buf" in r for r in result)

    def test_no_output(self):
        result = _parse_signature_outputs_simple("void foo(const int *buf)")
        # const pointer -> not output; void return -> "[OUT] (none)"
        assert result == ["[OUT] (none)"]


class TestJsonSafe:
    def test_path(self):
        assert isinstance(_json_safe(Path("/tmp")), str)

    def test_set(self):
        result = _json_safe({1, 2})
        assert isinstance(result, list)

    def test_nested_dict(self):
        result = _json_safe({"a": Path("/x")})
        assert result == {"a": "/x"} or result == {"a": "\\x"}


class TestSafeInt:
    def test_valid(self):
        assert _safe_int("5", 0) == 5

    def test_default(self):
        assert _safe_int(None, 10) == 10
        assert _safe_int("abc", 10) == 10

    def test_clamp(self):
        assert _safe_int("1", 5, low=3) == 3
        assert _safe_int("100", 5, high=50) == 50


class TestSplitCsv:
    def test_string(self):
        assert _split_csv("a, b, c") == ["a", "b", "c"]

    def test_list_passthrough(self):
        assert _split_csv(["x"]) == ["x"]

    def test_none(self):
        assert _split_csv(None) == []


class TestIsRelativeTo:
    def test_true(self):
        assert _is_relative_to(Path("/a/b/c"), Path("/a/b")) is True

    def test_false(self):
        assert _is_relative_to(Path("/x/y"), Path("/a/b")) is False


class TestReadWriteJson:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / "test.json"
        _write_json(p, {"key": "value"})
        assert _read_json(p, {}) == {"key": "value"}

    def test_read_missing(self, tmp_path):
        assert _read_json(tmp_path / "nope.json", {"default": True}) == {"default": True}


class TestIsAllowedReqDoc:
    def test_allowed(self):
        assert _is_allowed_req_doc(Path("spec.txt")) is True
        assert _is_allowed_req_doc(Path("doc.pdf")) is True

    def test_disallowed(self):
        assert _is_allowed_req_doc(Path("image.png")) is False


class TestInferRelatedIdSimple:
    def test_with_swcom(self):
        assert _infer_related_id_simple({"related": "SwCom_123"}) == "SwCom_123"

    def test_with_swufn(self):
        result = _infer_related_id_simple({"related": "SwUFn_42"})
        assert "SwFn_42" in result

    def test_empty(self):
        assert _infer_related_id_simple({}) == ""
        assert _infer_related_id_simple({"related": "N/A"}) == ""


class TestBuildExcelArtifactSummary:
    def test_sts_type(self):
        result = _build_excel_artifact_summary("sts", {"test_case_count": 10})
        assert result["artifact_type"] == "sts"
        assert len(result["primary"]) > 0

    def test_suts_type(self):
        result = _build_excel_artifact_summary("suts", {"test_case_count": 5})
        assert result["artifact_type"] == "suts"

    def test_unknown_type(self):
        result = _build_excel_artifact_summary("unknown", {})
        assert result["primary"] == []


class TestSafeExtractZip:
    def test_extract(self, tmp_path):
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("a.txt", "hello")
            zf.writestr("sub/b.txt", "world")
        dest = tmp_path / "out"
        dest.mkdir()
        count = _safe_extract_zip(zip_path, dest)
        assert count == 2
        assert (dest / "a.txt").read_text() == "hello"
