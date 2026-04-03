# tests/unit/test_uds_ai_helpers.py
"""Extended tests for workflow.uds_ai helpers not covered by test_uds_ai.py."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from workflow.uds_ai import (
    _extract_style_excerpt,
    _validate_sections,
    _extract_json_payload,
)


class TestExtractStyleExcerpt:
    def test_empty(self):
        assert _extract_style_excerpt("") == ""
        assert _extract_style_excerpt(None) == ""

    def test_front_matter_extracted(self):
        lines = [f"Line {i}" for i in range(200)]
        text = "\n".join(lines)
        result = _extract_style_excerpt(text)
        assert "Line 0" in result
        assert len(result) > 0

    def test_contents_section(self):
        lines = ["Title", "Author", ""] + [f"p{i}" for i in range(50)]
        lines.insert(5, "Contents")
        lines.insert(6, "1. Introduction")
        text = "\n".join(lines)
        result = _extract_style_excerpt(text)
        assert "[Contents]" in result

    def test_function_detail(self):
        lines = ["Header"] * 10
        lines.append("Function Name: foo_bar")
        lines.extend(["param: x", "return: void"] + ["body"] * 20)
        text = "\n".join(lines)
        result = _extract_style_excerpt(text)
        assert "[FunctionDetail]" in result

    def test_max_chars_respected(self):
        text = "A " * 10000
        result = _extract_style_excerpt(text, max_chars=500)
        assert len(result) <= 500


class TestValidateSections:
    def test_valid_payload(self):
        payload = {
            "overview": {"text": "test", "evidence": []},
            "requirements": {"text": "req", "evidence": []},
            "interfaces": {"text": "iface", "evidence": []},
            "uds_frames": {"text": "frames", "evidence": []},
            "notes": {"text": "notes", "evidence": []},
        }
        result = _validate_sections(payload, detailed=False)
        assert result is not None

    def test_auto_fills_missing_keys(self):
        payload = {
            "overview": {"text": "test", "evidence": []},
            "requirements": {"text": "req", "evidence": []},
            "interfaces": {"text": "iface", "evidence": []},
        }
        result = _validate_sections(payload, detailed=False)
        assert result is not None
        assert "uds_frames" in result
        assert "notes" in result

    def test_too_few_keys_returns_none(self):
        payload = {"overview": {"text": "x", "evidence": []}}
        result = _validate_sections(payload, detailed=False)
        assert result is None

    def test_not_dict(self):
        assert _validate_sections("string", detailed=False) is None

    def test_empty_dict(self):
        assert _validate_sections({}, detailed=False) is None

    def test_string_values_converted(self):
        payload = {
            "overview": "text value",
            "requirements": "req",
            "interfaces": "iface",
            "uds_frames": "frames",
            "notes": "notes",
        }
        result = _validate_sections(payload, detailed=False)
        assert isinstance(result["overview"], dict)
        assert result["overview"]["text"] == "text value"

    def test_detailed_adds_document(self):
        payload = {
            "overview": {"text": "t", "evidence": []},
            "requirements": {"text": "r", "evidence": []},
            "interfaces": {"text": "i", "evidence": []},
            "uds_frames": {"text": "u", "evidence": []},
            "notes": {"text": "n", "evidence": []},
        }
        result = _validate_sections(payload, detailed=True)
        assert "document" in result

    def test_logic_diagrams_cleaned(self):
        payload = {
            "overview": {"text": "t", "evidence": []},
            "requirements": {"text": "r", "evidence": []},
            "interfaces": {"text": "i", "evidence": []},
            "uds_frames": {"text": "u", "evidence": []},
            "notes": {"text": "n", "evidence": []},
            "logic_diagrams": [
                {"title": "flow", "description": "d"},
                "not a dict",
                {"no_title": True},  # missing both title and description
            ],
        }
        result = _validate_sections(payload, detailed=False)
        diagrams = result["logic_diagrams"]
        assert len(diagrams) == 1
        assert diagrams[0]["title"] == "flow"


class TestExtractJsonPayload:
    def test_plain_json(self):
        text = '{"key": "value"}'
        result = _extract_json_payload(text)
        assert result == {"key": "value"}

    def test_fenced_json(self):
        text = '```json\n{"key": "value"}\n```'
        result = _extract_json_payload(text)
        assert result == {"key": "value"}

    def test_json_with_preamble(self):
        text = 'Here is the result:\n{"key": "val"}'
        result = _extract_json_payload(text)
        assert result is not None
        assert result["key"] == "val"

    def test_trailing_comma_fixed(self):
        text = '{"a": 1, "b": 2,}'
        result = _extract_json_payload(text)
        assert result is not None

    def test_empty(self):
        assert _extract_json_payload("") is None
        assert _extract_json_payload(None) is None

    def test_non_dict_json(self):
        text = "[1, 2, 3]"
        assert _extract_json_payload(text) is None
