# /app/tests/unit/test_c_parsing.py
"""Unit tests for report/c_parsing.py - C code parsing functions."""

from __future__ import annotations

from report.c_parsing import (
    _strip_c_comments,
    _extract_c_prototypes,
    _extract_c_definitions,
    _extract_c_function_bodies,
    _extract_simple_call_names,
    _extract_c_macros,
    _extract_c_macro_defs,
    _extract_c_global_candidates,
)
from workflow.code_parser.c_parser import _parse_comment_fields, _extract_function_defs_regex_fallback


class TestStripCComments:
    def test_removes_block_comments(self):
        src = "int x; /* block */ int y;"
        assert "block" not in _strip_c_comments(src)

    def test_removes_line_comments(self):
        src = "int x; // line\nint y;"
        result = _strip_c_comments(src)
        assert "line" not in result
        assert "int y;" in result


class TestExtractCPrototypes:
    def test_extern_prototype(self):
        src = "extern int foo(int a, int b);"
        result = _extract_c_prototypes(src)
        assert len(result) >= 1
        name, params, is_extern = result[0]
        assert name == "foo"
        assert is_extern is True

    def test_non_extern(self):
        src = "void bar(void);"
        result = _extract_c_prototypes(src)
        assert len(result) >= 1
        assert result[0][0] == "bar"
        assert result[0][2] is False

    def test_empty_text(self):
        assert _extract_c_prototypes("") == []


class TestExtractCDefinitions:
    def test_normal_function(self):
        src = "int foo(int a) {\n  return a;\n}"
        result = _extract_c_definitions(src)
        assert len(result) >= 1
        assert result[0][0] == "foo"
        assert result[0][2] is False

    def test_static_function(self):
        src = "static void bar(void) {\n}"
        result = _extract_c_definitions(src)
        assert len(result) >= 1
        assert result[0][0] == "bar"
        assert result[0][2] is True

    def test_skips_keywords(self):
        src = "if (x) {\n}\nfor (int i = 0; i < 10; i++) {\n}"
        result = _extract_c_definitions(src)
        names = [r[0] for r in result]
        assert "if" not in names
        assert "for" not in names


class TestExtractCFunctionBodies:
    def test_extracts_body(self):
        src = "int foo(void) {\n  return 42;\n}\n"
        result = _extract_c_function_bodies(src)
        assert "foo" in result
        assert "42" in result["foo"]

    def test_nested_braces(self):
        src = "void bar(int x) {\n  if (x) {\n    return;\n  }\n}\n"
        result = _extract_c_function_bodies(src)
        assert "bar" in result


class TestExtractSimpleCallNames:
    def test_basic_calls(self):
        body = "foo(); bar(x); baz(1, 2);"
        result = _extract_simple_call_names(body)
        assert "foo" in result
        assert "bar" in result
        assert "baz" in result

    def test_skips_keywords(self):
        body = "if (x) { return 0; } sizeof(int);"
        result = _extract_simple_call_names(body)
        assert "if" not in result
        assert "return" not in result
        assert "sizeof" not in result

    def test_skips_macros(self):
        body = "MACRO_CALL(); normal_func();"
        result = _extract_simple_call_names(body)
        assert "MACRO_CALL" not in result
        assert "normal_func" in result


class TestExtractCMacros:
    def test_basic_define(self):
        src = "#define MAX_SIZE 100\n#define VERSION 2"
        result = _extract_c_macros(src)
        assert "MAX_SIZE" in result
        assert "VERSION" in result

    def test_empty(self):
        assert _extract_c_macros("") == []


class TestExtractCMacroDefs:
    def test_name_and_value(self):
        src = "#define BUF_SIZE 256"
        result = _extract_c_macro_defs(src)
        assert len(result) >= 1
        assert result[0] == ("BUF_SIZE", "256")


class TestExtractCGlobalCandidates:
    def test_simple_global(self):
        src = "uint8_t g_counter = 0;"
        result = _extract_c_global_candidates(src)
        assert len(result) >= 1
        assert result[0]["name"] == "g_counter"
        assert result[0]["type"] == "uint8_t"

    def test_static_global(self):
        src = "static uint16_t s_value;"
        result = _extract_c_global_candidates(src)
        assert len(result) >= 1
        assert result[0]["static"] == "true"

    def test_skips_functions(self):
        src = "int foo(int x);"
        result = _extract_c_global_candidates(src)
        assert len(result) == 0

    def test_empty(self):
        assert _extract_c_global_candidates("") == []


class TestCommentFieldParsing:
    def test_extracts_hyphenated_asil(self):
        comment = """
        /**
         * Description: sample
         * ASIL: ASIL-B
         * Related ID: SwTSR_0101
         */
        """
        _, asil, related, _, _, _, _ = _parse_comment_fields(comment)
        assert asil == "ASIL-B"
        assert related == "SwTSR_0101"


class TestCodeParserRegexFallback:
    def test_extracts_signature_and_comments_from_c_definition(self):
        src = """
        /**
         * @brief Buzzer control main function
         * @param state current state
         * @return updated state
         */
        void g_Ap_BuzzerCtrl_Func(void)
        {
            helper_call();
        }
        """
        result = _extract_function_defs_regex_fallback(src, "Ap_BuzzerCtrl_PDS.c", set())
        assert len(result) == 1
        fn = result[0]
        assert fn.name == "g_Ap_BuzzerCtrl_Func"
        assert fn.signature == "void g_Ap_BuzzerCtrl_Func(void)"
        assert "helper_call" in fn.calls
        assert "Buzzer control main function" in (fn.comment_desc or "")
