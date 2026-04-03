"""Unit tests for report_gen pure-logic functions (utils, uds_text, function_analyzer)."""
from __future__ import annotations

import pytest


class TestExtractIssuesCounts:
    def test_from_issue_counts(self):
        from report_gen.utils import _extract_issue_counts
        summary = {"static": {"cppcheck": {"issue_counts": {"total": 5, "error": 2, "warning": 3}}}}
        result = _extract_issue_counts(summary)
        assert result == {"total": 5, "error": 2, "warning": 3}

    def test_from_issues_list(self):
        from report_gen.utils import _extract_issue_counts
        summary = {"static": {"cppcheck": {"data": {"issues": [1, 2, 3]}}}}
        result = _extract_issue_counts(summary)
        assert result["total"] == 3

    def test_empty(self):
        from report_gen.utils import _extract_issue_counts
        assert _extract_issue_counts({})["total"] == 0


class TestNormalizeSwufnId:
    def test_standard(self):
        from report_gen.utils import _normalize_swufn_id
        assert _normalize_swufn_id("swufn_0042") == "SwUFn_0042"
        assert _normalize_swufn_id("SWUFN_123") == "SwUFn_123"

    def test_passthrough(self):
        from report_gen.utils import _normalize_swufn_id
        assert _normalize_swufn_id("other_id") == "other_id"

    def test_empty(self):
        from report_gen.utils import _normalize_swufn_id
        assert _normalize_swufn_id("") == ""


class TestNormalizeCallField:
    def test_dedup_lines(self):
        from report_gen.utils import _normalize_call_field
        assert _normalize_call_field("foo\nbar\nfoo") == "foo\nbar"

    def test_empty_lines_stripped(self):
        from report_gen.utils import _normalize_call_field
        assert _normalize_call_field("a\n\n\nb") == "a\nb"


class TestDedupeMultilineText:
    def test_basic(self):
        from report_gen.utils import _dedupe_multiline_text
        assert _dedupe_multiline_text("a\nb\na") == "a\nb"

    def test_na_removal(self):
        from report_gen.utils import _dedupe_multiline_text
        assert _dedupe_multiline_text("data\nN/A\nnone", na_to_empty=True) == "data"


class TestNormalizeAsilValue:
    def test_single(self):
        from report_gen.utils import _normalize_asil_value
        assert _normalize_asil_value("ASIL-B") == "B"

    def test_multiple(self):
        from report_gen.utils import _normalize_asil_value
        result = _normalize_asil_value("A, B, QM")
        assert "A" in result and "B" in result and "QM" in result

    def test_plain_letter(self):
        from report_gen.utils import _normalize_asil_value
        assert _normalize_asil_value("D") == "D"


class TestNormalizeRelatedIds:
    def test_dedup(self):
        from report_gen.utils import _normalize_related_ids
        assert _normalize_related_ids("SwTR_001, SwTR_002; SwTR_001") == "SwTR_001, SwTR_002"


class TestNormalizeSwcomLabel:
    def test_normalize(self):
        from report_gen.utils import _normalize_swcom_label
        assert _normalize_swcom_label("Sw Com 1") == "SwCom_01"

    def test_empty(self):
        from report_gen.utils import _normalize_swcom_label
        assert _normalize_swcom_label("") == ""


class TestExtractCallNames:
    def test_basic(self):
        from report_gen.utils import _extract_call_names
        names = _extract_call_names("foo()\nbar(int x)\nvoid")
        assert "foo" in names
        assert "bar" in names
        assert "void" not in names

    def test_skips_keywords(self):
        from report_gen.utils import _extract_call_names
        names = _extract_call_names("if(x)\nreturn(0)")
        assert names == []


class TestTitleCaseLine:
    def test_basic(self):
        from report_gen.uds_text import _title_case_line
        assert _title_case_line("hello world") == "Hello world"

    def test_empty(self):
        from report_gen.uds_text import _title_case_line
        assert _title_case_line("") == ""


class TestSplitSentences:
    def test_basic(self):
        from report_gen.uds_text import _split_sentences
        result = _split_sentences("First. Second! Third?")
        assert len(result) == 3

    def test_empty(self):
        from report_gen.uds_text import _split_sentences
        assert _split_sentences("") == []


class TestTrimSentenceWords:
    def test_short_unchanged(self):
        from report_gen.uds_text import _trim_sentence_words
        assert _trim_sentence_words("hello world", 10) == "hello world"

    def test_truncated(self):
        from report_gen.uds_text import _trim_sentence_words
        result = _trim_sentence_words("a b c d e f", 3)
        assert result == "a b c..."


class TestSplitSignatureParamChunks:
    def test_simple(self):
        from report_gen.function_analyzer import _split_signature_param_chunks
        result = _split_signature_param_chunks("int x, float y, char *z")
        assert result == ["int x", "float y", "char *z"]

    def test_nested_parens(self):
        from report_gen.function_analyzer import _split_signature_param_chunks
        result = _split_signature_param_chunks("void (*cb)(int, int), int x")
        assert len(result) == 2

    def test_empty(self):
        from report_gen.function_analyzer import _split_signature_param_chunks
        assert _split_signature_param_chunks("") == []


class TestExtractParamSymbol:
    def test_basic(self):
        from report_gen.function_analyzer import _extract_param_symbol
        assert _extract_param_symbol("uint8_t value") == "value"

    def test_pointer(self):
        from report_gen.function_analyzer import _extract_param_symbol
        assert _extract_param_symbol("uint8_t *buf") == "buf"

    def test_func_ptr(self):
        from report_gen.function_analyzer import _extract_param_symbol
        assert _extract_param_symbol("void (*callback)(int)") == "callback"

    def test_array(self):
        from report_gen.function_analyzer import _extract_param_symbol
        assert _extract_param_symbol("uint8_t data[8]") == "data"

    def test_empty(self):
        from report_gen.function_analyzer import _extract_param_symbol
        assert _extract_param_symbol("") == ""
