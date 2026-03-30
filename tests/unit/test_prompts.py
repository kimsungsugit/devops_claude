# /app/tests/unit/test_prompts.py
"""Unit tests for prompts/ loader."""

from __future__ import annotations

from prompts import load_prompt


class TestLoadPrompt:
    def test_load_existing_prompt(self):
        text = load_prompt("uds_writer")
        assert len(text) > 0
        assert "UDS Writer" in text

    def test_load_with_substitution(self):
        text = load_prompt("uds_section_writer", section_key="overview")
        assert "overview" in text

    def test_load_missing_prompt(self):
        text = load_prompt("nonexistent_prompt_file_xyz")
        assert text == ""

    def test_reviewer_prompt(self):
        text = load_prompt("uds_reviewer")
        assert "decision" in text

    def test_auditor_prompt(self):
        text = load_prompt("uds_auditor")
        assert "evidence" in text.lower()
