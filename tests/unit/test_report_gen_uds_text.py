"""Unit tests for report_gen.uds_text — text formatting and UDS rules."""
from __future__ import annotations

import pytest


class TestApplySentenceRules:
    def test_truncates_sentences(self):
        from report_gen.uds_text import _apply_sentence_rules

        result = _apply_sentence_rules(
            "First sentence. Second sentence. Third sentence.",
            max_sentences=2, max_words=0, max_chars=0, ensure_period=False,
        )
        assert "Third" not in result
        assert "First" in result

    def test_truncates_words(self):
        from report_gen.uds_text import _apply_sentence_rules

        result = _apply_sentence_rules(
            "one two three four five six seven",
            max_sentences=0, max_words=3, max_chars=0, ensure_period=False,
        )
        assert result == "one two three..."

    def test_ensures_period(self):
        from report_gen.uds_text import _apply_sentence_rules

        result = _apply_sentence_rules(
            "no period here",
            max_sentences=0, max_words=0, max_chars=0, ensure_period=True,
        )
        assert result.endswith(".")

    def test_max_chars_truncation(self):
        from report_gen.uds_text import _apply_sentence_rules

        long_text = "A" * 200
        result = _apply_sentence_rules(
            long_text,
            max_sentences=0, max_words=0, max_chars=50, ensure_period=False,
        )
        assert len(result) <= 53  # 50 + "..."
        assert result.endswith("...")

    def test_empty(self):
        from report_gen.uds_text import _apply_sentence_rules

        assert _apply_sentence_rules("", 0, 0, 0, False) == ""


class TestAiSectionText:
    def test_dict_with_text(self):
        from report_gen.uds_text import _ai_section_text

        sections = {"overview": {"text": "Hello world"}}
        assert _ai_section_text(sections, "overview") == "Hello world"

    def test_string_value(self):
        from report_gen.uds_text import _ai_section_text

        sections = {"notes": "Simple string"}
        assert _ai_section_text(sections, "notes") == "Simple string"

    def test_missing_key(self):
        from report_gen.uds_text import _ai_section_text

        assert _ai_section_text({"a": "b"}, "missing") == ""

    def test_non_dict_input(self):
        from report_gen.uds_text import _ai_section_text

        assert _ai_section_text("not_dict", "key") == ""
        assert _ai_section_text(None, "key") == ""


class TestAiQualityWarnings:
    def test_returns_warnings(self):
        from report_gen.uds_text import _ai_quality_warnings

        sections = {"quality_warnings": ["warn1", "warn2", ""]}
        result = _ai_quality_warnings(sections)
        assert result == ["warn1", "warn2"]

    def test_non_list(self):
        from report_gen.uds_text import _ai_quality_warnings

        assert _ai_quality_warnings({"quality_warnings": "not_list"}) == []

    def test_non_dict(self):
        from report_gen.uds_text import _ai_quality_warnings

        assert _ai_quality_warnings(None) == []


class TestMergeSectionText:
    def test_ai_text_overrides_base(self):
        from report_gen.uds_text import _merge_section_text

        sections = {"overview": {"text": "AI text"}}
        result = _merge_section_text("base text", sections, "overview")
        assert result == "AI text"

    def test_falls_back_to_base(self):
        from report_gen.uds_text import _merge_section_text

        result = _merge_section_text("base", {}, "overview")
        assert result == "base"

    def test_append_base(self):
        from report_gen.uds_text import _merge_section_text

        sections = {"overview": {"text": "AI text"}}
        result = _merge_section_text("base", sections, "overview", append_base=True)
        assert "AI text" in result
        assert "base" in result


class TestMergeLogicAiItems:
    def test_replaces_matching_title(self):
        from report_gen.uds_text import _merge_logic_ai_items

        logic = [{"title": "Step1", "description": "old"}]
        ai = {"logic_diagrams": [{"title": "Step1", "description": "new"}]}
        result = _merge_logic_ai_items(logic, ai)
        assert result[0]["description"] == "new"

    def test_no_ai_returns_original(self):
        from report_gen.uds_text import _merge_logic_ai_items

        items = [{"title": "A", "description": "d"}]
        result = _merge_logic_ai_items(items, None)
        assert result == items

    def test_empty_list(self):
        from report_gen.uds_text import _merge_logic_ai_items

        assert _merge_logic_ai_items([], {"logic_diagrams": []}) == []


class TestAiEvidenceLines:
    def test_formats_evidence(self):
        from report_gen.uds_text import _ai_evidence_lines

        sections = {
            "overview": {
                "text": "x",
                "evidence": [
                    {"source_type": "rag", "source_file": "doc.pdf", "content": "snippet"},
                ],
            }
        }
        result = _ai_evidence_lines(sections)
        assert len(result) >= 1
        assert "rag" in result[0].lower()

    def test_non_dict(self):
        from report_gen.uds_text import _ai_evidence_lines

        assert _ai_evidence_lines(None) == []
