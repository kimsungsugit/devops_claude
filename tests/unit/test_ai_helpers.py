# tests/unit/test_ai_helpers.py
"""Unit tests for workflow.ai pure helper functions (no LLM calls)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from workflow.ai import (
    _extract_gemini_text,
    _extract_json_from_reply,
    _format_rag_context,
    _has_test_main,
    _extract_test_body,
    _looks_like_c_family_code,
    _param_placeholder,
    _parse_param_name,
    _alt_buffer,
    _parse_list_str,
    _parse_review_decision,
    _parse_search_replace_blocks,
    _make_unified_diff,
    _is_simple_signature,
    _role_system_prompt,
    _plan_has_requirement_id,
    _validate_plan_obj,
)


class TestExtractGeminiText:
    def test_text_attribute(self):
        class Resp:
            text = "hello world"
        assert _extract_gemini_text(Resp()) == "hello world"

    def test_candidates_path(self):
        class Part:
            text = "from part"
        class Content:
            parts = [Part()]
        class Candidate:
            text = None
            content = Content()
        class Resp:
            text = None
            candidates = [Candidate()]
        assert "from part" in _extract_gemini_text(Resp())

    def test_none_response(self):
        assert _extract_gemini_text(None) is None

    def test_dict_candidate(self):
        class Resp:
            text = None
            candidates = [{"content": "dict text"}]
        assert "dict text" in _extract_gemini_text(Resp())


class TestExtractJsonFromReply:
    def test_extracts_json_block(self):
        reply = 'some preamble {"key": "val"} trailing'
        assert _extract_json_from_reply(reply) == '{"key": "val"}'

    def test_no_braces(self):
        assert _extract_json_from_reply("no json") == "no json"


class TestFormatRagContext:
    def test_basic(self):
        entries = [{"error_clean": "null ptr", "fix": "add check", "role": "fixer"}]
        result = _format_rag_context(entries)
        assert "null ptr" in result
        assert "add check" in result

    def test_empty(self):
        result = _format_rag_context([])
        assert "Knowledge base" in result


class TestHasTestMain:
    def test_has_main(self):
        assert _has_test_main("int main(void) { return 0; }") is True

    def test_no_main(self):
        assert _has_test_main("void foo() {}") is False

    def test_empty(self):
        assert _has_test_main("") is False


class TestExtractTestBody:
    def test_fenced_c(self):
        reply = "```c\n#include <stdio.h>\nint main() {}\n```"
        result = _extract_test_body(reply, is_cpp=False)
        assert "#include" in result

    def test_no_code_signals(self):
        assert _extract_test_body("just some text", is_cpp=False) == ""

    def test_unity_replaced_cpp(self):
        reply = '#include "unity.h"\nint main() {}'
        result = _extract_test_body(reply, is_cpp=True)
        assert "cassert" in result
        assert "unity.h" not in result


class TestLooksLikeCFamilyCode:
    def test_valid_c(self):
        assert _looks_like_c_family_code("#include <stdio.h>\nint main() {}") is True

    def test_sdk_response(self):
        assert _looks_like_c_family_code("candidates=[Candidate(text=...)]") is False

    def test_empty(self):
        assert _looks_like_c_family_code("") is False


class TestParamPlaceholder:
    def test_void(self):
        assert _param_placeholder("void") == (None, None)

    def test_pointer_uint8(self):
        expr, kind = _param_placeholder("uint8_t *buf")
        assert expr == "buf_u8a"
        assert kind == "u8"

    def test_bool_param(self):
        assert _param_placeholder("bool flag")[0] == "false"

    def test_variadic(self):
        assert _param_placeholder("...")[0] == "0"


class TestParseParamName:
    def test_basic(self):
        assert _parse_param_name("uint8_t length") == "length"

    def test_empty(self):
        assert _parse_param_name("") == ""


class TestAltBuffer:
    def test_swap(self):
        assert _alt_buffer("buf_u8a") == "buf_u8b"
        assert _alt_buffer("buf_u32a") == "buf_u32b"


class TestParseListStr:
    def test_list_input(self):
        assert _parse_list_str(["a", "b"]) == ["a", "b"]

    def test_csv_string(self):
        assert _parse_list_str("a, b, c") == ["a", "b", "c"]

    def test_none(self):
        assert _parse_list_str(None) == []


class TestParseReviewDecision:
    def test_json_accept(self):
        text = '{"decision": "accept", "reason": "looks good"}'
        d, r = _parse_review_decision(text)
        assert d == "accept"

    def test_keyword_fallback(self):
        d, _ = _parse_review_decision("I think we should reject this")
        assert d == "reject"

    def test_empty(self):
        d, _ = _parse_review_decision(None)
        assert d == "retry"


class TestParseSearchReplaceBlocks:
    def test_single_block(self):
        reply = '<<<<SEARCH_BLOCK[main.c]\nold code\n<<<<REPLACE_BLOCK[main.c]\nnew code\n'
        blocks = _parse_search_replace_blocks(reply)
        assert len(blocks) == 1
        assert blocks[0]["file"] == "main.c"
        assert "old code" in blocks[0]["search"]

    def test_no_blocks(self):
        assert _parse_search_replace_blocks("plain text") == []


class TestMakeUnifiedDiff:
    def test_basic_diff(self):
        result = _make_unified_diff(Path("a.c"), "line1\n", "line1\nline2\n")
        assert "+line2" in result


class TestIsSimpleSignature:
    def test_simple(self):
        assert _is_simple_signature("void", "int x", header_found=False) is True

    def test_struct_ret(self):
        assert _is_simple_signature("struct Foo", "int x", header_found=False) is False

    def test_custom_type_with_header(self):
        assert _is_simple_signature("MyType_t", "void", header_found=True) is True


class TestRoleSystemPrompt:
    def test_known_role(self):
        assert "Planner" in _role_system_prompt("planner")

    def test_unknown_role(self):
        assert "helpful" in _role_system_prompt("nonexistent")


class TestValidatePlanObj:
    def test_valid(self):
        obj = {
            "file": "a.c",
            "language": "c",
            "functions": [
                {"name": "foo", "cases": [{"id": "tc1", "inputs": {}, "expected": {}}]}
            ],
        }
        assert _validate_plan_obj(obj) is True

    def test_missing_file(self):
        assert _validate_plan_obj({"language": "c", "functions": []}) is False

    def test_not_dict(self):
        assert _validate_plan_obj("string") is False
