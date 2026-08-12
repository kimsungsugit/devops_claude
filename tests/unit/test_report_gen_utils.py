"""Unit tests for report_gen.utils — text processing, normalization, helpers."""
from __future__ import annotations

import pytest


class TestSafeDict:
    def test_dict_passthrough(self):
        from report_gen.utils import _safe_dict

        d = {"a": 1}
        assert _safe_dict(d) is d

    def test_none_returns_empty(self):
        from report_gen.utils import _safe_dict

        assert _safe_dict(None) == {}

    def test_list_returns_empty(self):
        from report_gen.utils import _safe_dict

        assert _safe_dict([1, 2]) == {}


class TestSafeList:
    def test_list_passthrough(self):
        from report_gen.utils import _safe_list

        lst = [1, 2]
        assert _safe_list(lst) is lst

    def test_none_returns_empty(self):
        from report_gen.utils import _safe_list

        assert _safe_list(None) == []

    def test_dict_returns_empty(self):
        from report_gen.utils import _safe_list

        assert _safe_list({"a": 1}) == []


class TestFmtBool:
    def test_true(self):
        from report_gen.utils import _fmt_bool

        assert _fmt_bool(True) == "YES"

    def test_false(self):
        from report_gen.utils import _fmt_bool

        assert _fmt_bool(False) == "NO"

    def test_none(self):
        from report_gen.utils import _fmt_bool

        assert _fmt_bool(None) == "N/A"

    def test_string(self):
        from report_gen.utils import _fmt_bool

        assert _fmt_bool("something") == "N/A"


class TestExtractSimpleCallNames:
    def test_basic_calls(self):
        from report_gen.utils import _extract_simple_call_names

        result = _extract_simple_call_names("foo(); bar(1);")
        assert "foo" in result
        assert "bar" in result

    def test_skips_keywords(self):
        from report_gen.utils import _extract_simple_call_names

        result = _extract_simple_call_names("if (x) { return(0); }")
        assert "if" not in result
        assert "return" not in result

    def test_skips_all_upper_macros(self):
        from report_gen.utils import _extract_simple_call_names

        result = _extract_simple_call_names("MACRO(x); func(y);")
        assert "MACRO" not in result
        assert "func" in result

    def test_function_pointer_call(self):
        from report_gen.utils import _extract_simple_call_names

        result = _extract_simple_call_names("(*pfCallback)(arg);")
        assert "pfCallback" in result

    def test_empty(self):
        from report_gen.utils import _extract_simple_call_names

        assert _extract_simple_call_names("") == []


class TestTableRowsFromTexts:
    def test_pads_short_rows(self):
        from report_gen.utils import _table_rows_from_texts

        result = _table_rows_from_texts(["col1  col2"], 4)
        assert len(result) == 1
        assert len(result[0]) == 4
        assert result[0][0] == "col1"
        assert result[0][1] == "col2"

    def test_trims_excess_cols(self):
        from report_gen.utils import _table_rows_from_texts

        result = _table_rows_from_texts(["a  b  c  d  e"], 3)
        assert len(result[0]) == 3

    def test_empty_rows_skipped(self):
        from report_gen.utils import _table_rows_from_texts

        result = _table_rows_from_texts(["", "  ", "a  b"], 2)
        assert len(result) == 1


class TestBuildGlobalRows:
    def test_basic_row_with_labels(self):
        from report_gen.utils import _build_global_rows

        header = ["Name", "Type", "Value Range", "Reset Value", "Description"]
        info = {"g_var": {"type": "uint8", "range": "0..255", "init": "0", "desc": "counter"}}
        rows = _build_global_rows(["g_var"], info, header, with_labels=True)
        assert len(rows) == 1
        assert "Name=g_var" in rows[0][0]
        assert "Type=uint8" in rows[0][1]

    def test_without_labels(self):
        from report_gen.utils import _build_global_rows

        header = ["Name", "Type"]
        info = {"x": {"type": "int"}}
        rows = _build_global_rows(["x"], info, header, with_labels=False)
        assert rows[0][0] == "x"
        assert rows[0][1] == "int"

    def test_empty_names(self):
        from report_gen.utils import _build_global_rows

        assert _build_global_rows([], {}, ["Name", "Type"]) == []


class TestInferTypeFromDecl:
    def test_empty(self):
        from report_gen.utils import _infer_type_from_decl

        assert _infer_type_from_decl("", "") == ""

    def test_missing_name(self):
        from report_gen.utils import _infer_type_from_decl

        assert _infer_type_from_decl("uint8 x;", "") == ""


class TestGenerateMarkdownSummary:
    def test_creates_file(self, tmp_path):
        from report_gen.utils import generate_markdown_summary

        out = tmp_path / "summary.md"
        summary = {
            "project_root": "/some/project",
            "exit_code": 0,
            "generated_at": "2025-01-01T00:00:00",
        }
        result = generate_markdown_summary(summary, str(out))
        assert out.exists()
        text = out.read_text(encoding="utf-8")
        assert "# project" in text.lower() or "project" in text.lower()
        assert "Exit code: 0" in text


class TestTypeInferenceFallbacks:
    r"""raw 문자열 안의 `\\b`·`\\s` 때문에 **한 번도 매치된 적 없던** 폴백 두 개.

    raw 에서 `\\b` 는 정규식으로 "역슬래시 다음에 b" 다. C 소스엔 그런 문자열이
    없으므로 두 함수는 항상 빈 값을 돌려줬고, 그건 "타입을 못 구했다" 와 구분되지
    않아 조용했다(2026-08-12 발견, `report_gen/utils.py` 주석 참조).

    ⚠ KJPDS02 에서는 이 fix 로 **산출물이 바뀌지 않는다** — tree-sitter 가 이미 모든
      전역에 타입을 준다(`typeless_dropped` 0). 회수가 아니라 폴백의 복구다.
    """

    @pytest.mark.parametrize(
        "decl,name,expect",
        [
            ("extern volatile ADC0STSSTR _ADC0STS;", "_ADC0STS", "ADC0STSSTR"),
            ("static const U8 u8s_Buf[10]", "u8s_Buf", "U8"),
            ("U16 g_Counter = 0", "g_Counter", "U16"),
        ],
    )
    def test_decl_type_is_actually_extracted(self, decl, name, expect):
        from report_gen.utils import _infer_type_from_decl

        assert _infer_type_from_decl(decl, name) == expect

    def test_decl_without_the_name_yields_nothing(self):
        """대조군 — 정규식을 고치면서 아무거나 반환하게 되면 없는 타입을 지어낸다."""
        from report_gen.utils import _infer_type_from_decl

        assert _infer_type_from_decl("extern U8 other_var;", "_ADC0STS") == ""

    def test_file_type_is_actually_extracted(self, tmp_path):
        from report_gen.utils import _infer_type_from_file

        f = tmp_path / "IO_Map.h"
        f.write_text("extern volatile ADC0STSSTR _ADC0STS;\n", encoding="utf-8")
        gtype, init = _infer_type_from_file(str(f), "_ADC0STS")
        assert gtype == "ADC0STSSTR" and init == ""

    def test_file_type_reaches_declarations_past_the_old_cap(self, tmp_path):
        """상한이 여기 박혀 있으면(옛 판 `200_000`) 파일 뒤쪽 선언은 폴백조차 못 탄다."""
        from report_gen.utils import _infer_type_from_file

        f = tmp_path / "IO_Map.h"
        pad = "\n".join(f"#define PAD_{i:06d} {i}" for i in range(12_000))
        f.write_text(pad + "\nextern volatile ADC0STSSTR _ADC0STS;\n", encoding="utf-8")
        assert f.stat().st_size > 200_000, "테스트 전제(옛 캡 초과)가 깨졌다"
        assert _infer_type_from_file(str(f), "_ADC0STS")[0] == "ADC0STSSTR"

    def test_function_declarations_are_skipped(self):
        """`(` 가 있으면 함수다 — 타입으로 잡으면 없는 전역이 생긴다."""
        from report_gen.utils import _infer_type_from_file

        assert _infer_type_from_file("", "x") == ("", "")
