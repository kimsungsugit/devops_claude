# /app/tests/unit/test_constants.py
"""Unit tests for report/constants.py."""

from __future__ import annotations

from report.constants import (
    UDS_RULES,
    UDS_PLACEHOLDERS,
    GLOBALS_FORMAT_ORDER,
    DEFAULT_TYPE_RANGES,
)


class TestUDSRules:
    def test_has_section_order(self):
        assert "section_order" in UDS_RULES
        assert isinstance(UDS_RULES["section_order"], list)

    def test_has_formatting(self):
        fmt = UDS_RULES.get("formatting", {})
        assert "max_sentences" in fmt
        assert "max_chars" in fmt

    def test_has_sections(self):
        sections = UDS_RULES.get("sections", {})
        assert "overview" in sections
        assert "requirements" in sections
        assert "notes" in sections


class TestUDSPlaceholders:
    def test_contains_project_name(self):
        assert "{{project_name}}" in UDS_PLACEHOLDERS

    def test_contains_overview(self):
        assert "{{overview}}" in UDS_PLACEHOLDERS


class TestGlobalsFormatOrder:
    def test_has_name(self):
        assert "Name" in GLOBALS_FORMAT_ORDER


class TestDefaultTypeRanges:
    def test_u8_range(self):
        assert "U8" in DEFAULT_TYPE_RANGES
        assert "255" in DEFAULT_TYPE_RANGES["U8"]

    def test_s16_range(self):
        assert "S16" in DEFAULT_TYPE_RANGES
