"""Unit tests for report_gen.source_parser — C parsing helpers."""
from __future__ import annotations

import pytest


class TestStripCComments:
    def test_block_comment(self):
        from report_gen.source_parser import _strip_c_comments

        result = _strip_c_comments("int x; /* comment */ int y;")
        assert "comment" not in result
        assert "int x" in result
        assert "int y" in result

    def test_line_comment(self):
        from report_gen.source_parser import _strip_c_comments

        result = _strip_c_comments("int x; // line comment\nint y;")
        assert "line comment" not in result
        assert "int y" in result

    def test_empty(self):
        from report_gen.source_parser import _strip_c_comments

        assert _strip_c_comments("") == ""


class TestExtractCPrototypes:
    def test_finds_prototypes(self):
        from report_gen.source_parser import _extract_c_prototypes

        code = "void foo(int x);\nint bar(void);\n"
        result = _extract_c_prototypes(code)
        names = [r[0] for r in result]
        assert "foo" in names
        assert "bar" in names

    def test_extern_flag(self):
        from report_gen.source_parser import _extract_c_prototypes

        code = "extern void ext_func(void);\n"
        result = _extract_c_prototypes(code)
        assert len(result) >= 1
        assert result[0][2] is True  # is_extern

    def test_empty(self):
        from report_gen.source_parser import _extract_c_prototypes

        assert _extract_c_prototypes("") == []


class TestExtractCDefinitions:
    def test_finds_definitions(self):
        from report_gen.source_parser import _extract_c_definitions

        code = "void foo(int x) {\n  return;\n}\nstatic int bar(void) {\n  return 1;\n}\n"
        result = _extract_c_definitions(code)
        names = [r[0] for r in result]
        assert "foo" in names
        assert "bar" in names

    def test_static_flag(self):
        from report_gen.source_parser import _extract_c_definitions

        code = "static void helper(void) { }\n"
        result = _extract_c_definitions(code)
        assert len(result) >= 1
        assert result[0][2] is True  # is_static

    def test_skips_keywords(self):
        from report_gen.source_parser import _extract_c_definitions

        code = "if (cond) {\n}\n"
        result = _extract_c_definitions(code)
        names = [r[0] for r in result]
        assert "if" not in names

    def test_empty(self):
        from report_gen.source_parser import _extract_c_definitions

        assert _extract_c_definitions("") == []


class TestExtractCFunctionBodies:
    def test_extracts_body(self):
        from report_gen.source_parser import _extract_c_function_bodies

        code = "void foo(void) {\n  int x = 1;\n  bar();\n}\n"
        result = _extract_c_function_bodies(code)
        assert "foo" in result
        assert "bar()" in result["foo"]

    def test_empty(self):
        from report_gen.source_parser import _extract_c_function_bodies

        assert _extract_c_function_bodies("") == {}


class TestExtractCMacros:
    def test_finds_defines(self):
        from report_gen.source_parser import _extract_c_macros

        code = "#define FOO 1\n#define BAR(x) (x+1)\nint y;\n"
        result = _extract_c_macros(code)
        assert "FOO" in result
        assert "BAR" in result

    def test_empty(self):
        from report_gen.source_parser import _extract_c_macros

        assert _extract_c_macros("") == []


class TestExtractCMacroDefs:
    def test_finds_name_value_pairs(self):
        from report_gen.source_parser import _extract_c_macro_defs

        code = "#define MAX_SIZE 256\n#define PI 3.14\n"
        result = _extract_c_macro_defs(code)
        names = [r[0] for r in result]
        assert "MAX_SIZE" in names
        assert "PI" in names
        vals = {r[0]: r[1] for r in result}
        assert vals["MAX_SIZE"] == "256"

    def test_empty(self):
        from report_gen.source_parser import _extract_c_macro_defs

        assert _extract_c_macro_defs("") == []


class TestExtractCommentLines:
    def test_line_comments(self):
        from report_gen.source_parser import _extract_comment_lines

        text = "int x; // important note\nint y;\n"
        result = _extract_comment_lines(text)
        assert "important note" in result

    def test_block_comments(self):
        from report_gen.source_parser import _extract_comment_lines

        text = "/* line1\n * line2\n */\n"
        result = _extract_comment_lines(text)
        assert any("line1" in r for r in result)
        assert any("line2" in r for r in result)

    def test_empty(self):
        from report_gen.source_parser import _extract_comment_lines

        assert _extract_comment_lines("") == []


class TestExtractDoxygenAsilTags:
    def test_extracts_asil_and_req(self):
        from report_gen.source_parser import _extract_doxygen_asil_tags

        text = (
            "/**\n"
            " * @brief Init motor\n"
            " * @asil B\n"
            " * @requirement SwTR_001\n"
            " */\n"
            "void Motor_Init(void) {\n"
            "}\n"
        )
        result = _extract_doxygen_asil_tags(text)
        assert "Motor_Init" in result
        assert result["Motor_Init"]["asil"] == "B"
        assert "SwTR_001" in result["Motor_Init"]["requirement"]

    def test_safety_tag_fallback(self):
        from report_gen.source_parser import _extract_doxygen_asil_tags

        text = (
            "/**\n"
            " * @safety ASIL-D rated\n"
            " */\n"
            "void SafeFunc(void) {\n"
            "}\n"
        )
        result = _extract_doxygen_asil_tags(text)
        assert "SafeFunc" in result
        assert result["SafeFunc"]["asil"] == "D"

    def test_empty(self):
        from report_gen.source_parser import _extract_doxygen_asil_tags

        assert _extract_doxygen_asil_tags("") == {}


class TestExtractFileHeaderAsil:
    def test_finds_asil_in_header(self):
        from report_gen.source_parser import _extract_file_header_asil

        text = "/**\n * @file motor.c\n * @asil B\n */\nint x;\n"
        result = _extract_file_header_asil(text)
        assert "B" in result

    def test_empty(self):
        from report_gen.source_parser import _extract_file_header_asil

        assert _extract_file_header_asil("") == ""


class TestParseCDeclarationStatement:
    def test_simple_var(self):
        from report_gen.source_parser import _parse_c_declaration_statement

        result = _parse_c_declaration_statement("static uint8 g_counter")
        assert len(result) == 1
        assert result[0]["name"] == "g_counter"
        assert result[0]["static"] == "true"

    def test_multi_decl(self):
        from report_gen.source_parser import _parse_c_declaration_statement

        result = _parse_c_declaration_statement("static uint8 a, b, c")
        assert len(result) == 3
        names = [r["name"] for r in result]
        assert "a" in names and "b" in names and "c" in names

    def test_typedef_skipped(self):
        from report_gen.source_parser import _parse_c_declaration_statement

        assert _parse_c_declaration_statement("typedef unsigned char U8") == []

    def test_empty(self):
        from report_gen.source_parser import _parse_c_declaration_statement

        assert _parse_c_declaration_statement("") == []

    def test_extern_decl(self):
        from report_gen.source_parser import _parse_c_declaration_statement

        result = _parse_c_declaration_statement("extern uint16 g_speed")
        assert len(result) == 1
        assert result[0]["extern"] == "true"

    def test_function_pointer(self):
        from report_gen.source_parser import _parse_c_declaration_statement

        result = _parse_c_declaration_statement("static void (*pfCb)(void)")
        assert len(result) == 1
        assert result[0]["name"] == "pfCb"

    def test_rejects_control_flow(self):
        from report_gen.source_parser import _parse_c_declaration_statement

        assert _parse_c_declaration_statement("if (x == 0)") == []
        assert _parse_c_declaration_statement("for (i = 0; i < n; i++)") == []


class TestIterCStatements:
    def test_splits_on_semicolons(self):
        from report_gen.source_parser import _iter_c_statements

        result = _iter_c_statements("int x = 1; int y = 2;")
        assert len(result) == 2

    def test_skips_preprocessor(self):
        from report_gen.source_parser import _iter_c_statements

        result = _iter_c_statements("#include <stdio.h>\nint x = 1;")
        assert any("int x" in s for s in result)

    def test_empty(self):
        from report_gen.source_parser import _iter_c_statements

        assert _iter_c_statements("") == []


class TestSplitDeclItems:
    def test_splits_comma(self):
        from report_gen.source_parser import _split_decl_items

        result = _split_decl_items("a, b, c")
        assert result == ["a", "b", "c"]

    def test_preserves_function_pointer(self):
        from report_gen.source_parser import _split_decl_items

        result = _split_decl_items("void (*cb)(int, int), int x")
        assert len(result) == 2

    def test_empty(self):
        from report_gen.source_parser import _split_decl_items

        assert _split_decl_items("") == []


class TestExtractDeclNameAndType:
    def test_basic_var(self):
        from report_gen.source_parser import _extract_decl_name_and_type

        name, dtype = _extract_decl_name_and_type("g_counter", "uint8")
        assert name == "g_counter"
        assert dtype == "uint8"

    def test_pointer(self):
        from report_gen.source_parser import _extract_decl_name_and_type

        name, dtype = _extract_decl_name_and_type("*p_data", "uint8")
        assert name == "p_data"
        assert "*" in dtype

    def test_func_ptr(self):
        from report_gen.source_parser import _extract_decl_name_and_type

        name, dtype = _extract_decl_name_and_type("(*pfCb)(void)", "void")
        assert name == "pfCb"

    def test_empty(self):
        from report_gen.source_parser import _extract_decl_name_and_type

        assert _extract_decl_name_and_type("", "uint8") == ("", "")
