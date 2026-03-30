# /app/tests/unit/test_test_helpers.py
"""Unit tests for workflow/test_helpers.py."""

from __future__ import annotations

from workflow.test_helpers import (
    strip_c_comments,
    param_placeholder,
    parse_param_name,
    alt_buffer,
    build_call_variants,
    is_simple_signature,
)


class TestStripCComments:
    def test_block_comment(self):
        assert "comment" not in strip_c_comments("x /* comment */ y")

    def test_line_comment(self):
        result = strip_c_comments("x // comment\ny")
        assert "comment" not in result
        assert "y" in result


class TestParamPlaceholder:
    def test_void(self):
        assert param_placeholder("void") == (None, None)

    def test_pointer_uint8(self):
        expr, kind = param_placeholder("uint8_t *data")
        assert expr == "buf_u8a"
        assert kind == "u8"

    def test_bool(self):
        expr, kind = param_placeholder("bool flag")
        assert expr == "false"
        assert kind is None

    def test_int(self):
        expr, kind = param_placeholder("int count")
        assert expr == "0"
        assert kind is None

    def test_float(self):
        expr, kind = param_placeholder("float val")
        assert expr == "0.0"


class TestParseParamName:
    def test_basic(self):
        assert parse_param_name("int count") == "count"

    def test_pointer(self):
        assert parse_param_name("uint8_t *data") == "data"

    def test_empty(self):
        assert parse_param_name("") == ""


class TestAltBuffer:
    def test_swap(self):
        assert alt_buffer("buf_u8a") == "buf_u8b"
        assert alt_buffer("buf_u16a") == "buf_u16b"

    def test_no_change(self):
        assert alt_buffer("0") == "0"


class TestBuildCallVariants:
    def test_simple_function(self):
        variants = build_call_variants("foo", ["int x"])
        assert len(variants) >= 1
        assert variants[0] == ["0"]

    def test_with_pointer(self):
        variants = build_call_variants("bar", ["uint8_t *data", "int len"])
        assert len(variants) >= 2

    def test_cap_at_12(self):
        variants = build_call_variants("baz", ["int pid", "int x"])
        assert len(variants) <= 12


class TestIsSimpleSignature:
    def test_simple(self):
        assert is_simple_signature("int", "int a", header_found=True) is True

    def test_no_header(self):
        assert is_simple_signature("int", "int a", header_found=False) is False

    def test_typedef(self):
        assert is_simple_signature("typedef void", "int a", header_found=True) is False

    def test_variadic(self):
        assert is_simple_signature("int", "int a, ...", header_found=True) is False
