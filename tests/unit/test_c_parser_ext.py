# tests/unit/test_c_parser_ext.py
"""Extended tests for workflow.code_parser.c_parser (not in test_c_parsing.py)."""
from __future__ import annotations

import pytest

from workflow.code_parser.c_parser import (
    _parse_comment_fields,
    _extract_function_defs_regex_fallback,
    _extract_calls_from_body_text,
    _extract_leading_comment,
    CFunction,
)


class TestParseCommentFields:
    def test_brief(self):
        comment = "@brief Initialize module"
        desc, asil, related, pre, rng, params, ret = _parse_comment_fields(comment)
        assert "Initialize module" in desc

    def test_brief_with_param(self):
        # @param without [in] bracket is matched by the regex
        comment = "@brief Initialize module\n@param cfg Configuration"
        desc, asil, related, pre, rng, params, ret = _parse_comment_fields(comment)
        assert "Initialize module" in desc
        assert len(params) == 1
        assert params[0]["name"] == "cfg"

    def test_asil(self):
        comment = "ASIL: B\n@brief Some function"
        _, asil, _, _, _, _, _ = _parse_comment_fields(comment)
        assert asil == "B"

    def test_related_id(self):
        comment = "Related ID: SwTR_001, SwTR_002"
        _, _, related, _, _, _, _ = _parse_comment_fields(comment)
        assert "SwTR_001" in related

    def test_precondition(self):
        comment = "@pre Module must be initialized"
        _, _, _, pre, _, _, _ = _parse_comment_fields(comment)
        assert "initialized" in pre

    def test_range(self):
        comment = "Range: 0..255"
        _, _, _, _, rng, _, _ = _parse_comment_fields(comment)
        assert "0..255" in rng

    def test_return_desc(self):
        comment = "@return Status code"
        desc, _, _, _, _, _, ret = _parse_comment_fields(comment)
        assert "Status code" in ret

    def test_empty(self):
        desc, asil, related, pre, rng, params, ret = _parse_comment_fields("")
        assert desc == ""
        assert params == []

    def test_noise_description_filtered(self):
        comment = "Description: ----===----"
        desc, _, _, _, _, _, _ = _parse_comment_fields(comment)
        assert "---" not in desc

    def test_details_appended(self):
        comment = "@brief Init\n@details Detailed explanation here"
        desc, _, _, _, _, _, _ = _parse_comment_fields(comment)
        assert "Detailed explanation" in desc

    def test_multiple_params(self):
        # Use format without [in]/[out] brackets (space-separated)
        comment = "@param a First\n@param b Second\n@return Result"
        desc, _, _, _, _, params, ret = _parse_comment_fields(comment)
        assert len(params) == 2
        assert params[0]["name"] == "a"
        assert params[1]["name"] == "b"
        assert "Result" in ret


class TestExtractCallsFromBodyText:
    def test_basic(self):
        body = "foo(); bar(x);"
        result = _extract_calls_from_body_text(body)
        assert "foo" in result
        assert "bar" in result

    def test_skips_keywords(self):
        body = "if (x) { while (1) {} return 0; sizeof(int); }"
        result = _extract_calls_from_body_text(body)
        assert "if" not in result
        assert "while" not in result
        assert "sizeof" not in result

    def test_skips_stdlib(self):
        body = "memcpy(dst, src, n); printf(msg); my_func();"
        result = _extract_calls_from_body_text(body)
        assert "memcpy" not in result
        assert "printf" not in result
        assert "my_func" in result

    def test_empty(self):
        assert _extract_calls_from_body_text("") == []


class TestExtractLeadingComment:
    def test_block_comment(self):
        src = b"/* This is a comment */\nvoid foo() {}"
        result = _extract_leading_comment(src, src.index(b"void"))
        assert "This is a comment" in result

    def test_line_comments(self):
        src = b"// line1\n// line2\nvoid bar() {}"
        result = _extract_leading_comment(src, src.index(b"void"))
        assert "line1" in result
        assert "line2" in result

    def test_no_comment(self):
        src = b"void baz() {}"
        result = _extract_leading_comment(src, 0)
        assert result == ""


class TestExtractFunctionDefsRegexFallback:
    def test_basic_function(self):
        text = "void foo(int x) {\n  return;\n}\n"
        result = _extract_function_defs_regex_fallback(text, "test.c", set())
        assert len(result) >= 1
        assert result[0].name == "foo"

    def test_static_function(self):
        text = "static int bar(void) {\n  return 0;\n}\n"
        result = _extract_function_defs_regex_fallback(text, "test.c", set())
        assert len(result) >= 1
        assert result[0].is_static is True

    def test_globals_detected(self):
        text = "void baz(void) {\n  g_counter++;\n}\n"
        result = _extract_function_defs_regex_fallback(text, "test.c", {"g_counter"})
        assert len(result) >= 1
        assert "g_counter" in result[0].used_globals

    def test_empty_text(self):
        assert _extract_function_defs_regex_fallback("", "test.c", set()) == []

    def test_calls_extracted(self):
        text = "void run(void) {\n  init(); process();\n}\n"
        result = _extract_function_defs_regex_fallback(text, "test.c", set())
        if result:
            assert "init" in result[0].calls
            assert "process" in result[0].calls
