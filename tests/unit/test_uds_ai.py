# /app/tests/unit/test_uds_ai.py
"""Unit tests for workflow/uds_ai.py - UDS AI section helpers (no LLM calls)."""

from __future__ import annotations

import json
from unittest.mock import patch

from workflow.uds_ai import (
    _trim_text,
    _normalize_evidence_item,
    _normalize_evidence_list,
    _normalize_section,
    _extract_json_payload,
    _parse_decision,
    _quality_warnings,
    _validate_sections,
    _repair_missing_sections,
    _build_section_prompt,
)


class TestTrimText:
    def test_short_text(self):
        assert _trim_text("hello", 1000) == "hello"

    def test_long_text(self):
        text = "x" * 5000
        result = _trim_text(text, 500)
        assert len(result) < 5000
        assert "truncated" in result

    def test_none(self):
        assert _trim_text(None, 100) == ""


class TestNormalizeEvidenceItem:
    def test_dict_with_fields(self):
        item = {"source_type": "rag", "source_file": "a.c", "excerpt": "line 1"}
        result = _normalize_evidence_item(item)
        assert result is not None
        assert result["source_type"] == "rag"

    def test_string_item(self):
        result = _normalize_evidence_item("some note")
        assert result is not None
        assert result["source_type"] == "note"
        assert result["excerpt"] == "some note"

    def test_empty_dict(self):
        result = _normalize_evidence_item({})
        assert result is None

    def test_none(self):
        assert _normalize_evidence_item(None) is None


class TestNormalizeEvidenceList:
    def test_normal_list(self):
        items = [{"source_type": "rag", "excerpt": "test"}]
        result = _normalize_evidence_list(items)
        assert len(result) == 1

    def test_non_list(self):
        assert _normalize_evidence_list("not a list") == []

    def test_filters_invalid(self):
        items = [{}, {"source_type": "x", "excerpt": "ok"}, None]
        result = _normalize_evidence_list(items)
        assert len(result) == 1


class TestNormalizeSection:
    def test_dict_section(self):
        section = {"text": "Overview text", "evidence": []}
        result = _normalize_section(section)
        assert result["text"] == "Overview text"

    def test_string_section(self):
        result = _normalize_section("Some text")
        assert result["text"] == "Some text"
        assert len(result["evidence"]) == 1

    def test_na_section(self):
        result = _normalize_section("N/A")
        assert result["text"] == "N/A"
        assert result["evidence"] == []

    def test_none(self):
        result = _normalize_section(None)
        assert result["text"] == ""


class TestExtractJsonPayload:
    def test_valid_json(self):
        result = _extract_json_payload('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_with_extra_text(self):
        result = _extract_json_payload('Some text {"key": "value"} more text')
        assert result == {"key": "value"}

    def test_invalid_json(self):
        result = _extract_json_payload("not json at all")
        assert result is None

    def test_empty(self):
        assert _extract_json_payload("") is None
        assert _extract_json_payload(None) is None


class TestParseDecision:
    def test_accept(self):
        decision, reason = _parse_decision('{"decision": "accept", "reason": "good"}')
        assert decision == "accept"

    def test_retry(self):
        decision, reason = _parse_decision('{"decision": "retry", "reason": "bad format"}')
        assert decision == "retry"

    def test_keyword_fallback(self):
        decision, _ = _parse_decision("The output is acceptable, accept it.")
        assert decision == "accept"

    def test_empty(self):
        decision, _ = _parse_decision("")
        assert decision == "retry"


class TestQualityWarnings:
    def test_no_evidence_warning(self):
        sections = {
            "overview": {"text": "Some overview", "evidence": []},
            "requirements": {"text": "N/A", "evidence": []},
            "interfaces": {"text": "", "evidence": []},
            "uds_frames": {"text": "Frames text", "evidence": [{"source_type": "rag"}]},
            "notes": {"text": "Note", "evidence": []},
        }
        warnings = _quality_warnings(sections)
        assert any("overview" in w for w in warnings)
        assert any("notes" in w for w in warnings)
        assert not any("requirements" in w for w in warnings)

    def test_no_warnings_when_complete(self):
        sections = {
            "overview": {"text": "N/A", "evidence": []},
            "requirements": {"text": "N/A", "evidence": []},
            "interfaces": {"text": "N/A", "evidence": []},
            "uds_frames": {"text": "N/A", "evidence": []},
            "notes": {"text": "N/A", "evidence": []},
        }
        assert _quality_warnings(sections) == []


class TestValidateSections:
    def test_valid_payload(self):
        payload = {
            "overview": {"text": "t", "evidence": []},
            "requirements": {"text": "t", "evidence": []},
            "interfaces": {"text": "t", "evidence": []},
            "uds_frames": {"text": "t", "evidence": []},
            "notes": {"text": "t", "evidence": []},
            "document": "full doc",
        }
        assert _validate_sections(payload, detailed=True) is not None

    def test_missing_key(self):
        # Only 1 key present (< 2 required) → returns None
        payload = {
            "overview": {},
        }
        assert _validate_sections(payload, detailed=False) is None


class TestBuildSectionPrompt:
    def test_normal_prompt_no_repair_marker(self):
        prompt = _build_section_prompt("interfaces")
        assert "interfaces" in prompt
        assert "UDS Writer" in prompt
        assert "REPAIR" not in prompt

    def test_repair_prompt_has_marker(self):
        prompt = _build_section_prompt("interfaces", repair=True)
        assert "REPAIR" in prompt
        assert "interfaces" in prompt
        assert "UDS Writer" in prompt

    def test_repair_prompt_contains_all_normal_content(self):
        normal = _build_section_prompt("uds_frames")
        repair = _build_section_prompt("uds_frames", repair=True)
        # repair prompt는 normal보다 길어야 함
        assert len(repair) > len(normal)
        # ASIL/Related 규칙은 repair에도 포함
        assert "ASIL" in repair
        assert "Related ID" in repair


class TestRepairMissingSections:
    def _make_raw(self, **overrides):
        base = {
            "overview": {"text": "real overview", "evidence": []},
            "requirements": {"text": "real reqs", "evidence": []},
            "interfaces": {"text": "N/A", "evidence": []},
            "uds_frames": {"text": "N/A", "evidence": []},
            "notes": {"text": "N/A", "evidence": []},
        }
        base.update(overrides)
        return base

    def test_no_repair_when_all_present(self):
        raw = {k: {"text": "real content", "evidence": []} for k in
               ["overview", "requirements", "interfaces", "uds_frames", "notes"]}
        result = _repair_missing_sections(raw, cfg={}, user_payload={}, analysis_payload={})
        assert result is raw

    def test_repairs_na_sections(self):
        raw = self._make_raw()
        repaired_section = {"text": "Interfaces description", "evidence": []}

        def mock_call_role(cfg, *, role, stage, messages, temperature=0.2):
            return {"output": json.dumps(repaired_section)}

        with patch("workflow.uds_ai._call_role", side_effect=mock_call_role):
            result = _repair_missing_sections(
                raw, cfg={}, user_payload={}, analysis_payload={}
            )

        assert result["interfaces"]["text"] == "Interfaces description"
        assert result["uds_frames"]["text"] == "Interfaces description"
        assert result["notes"]["text"] == "Interfaces description"
        assert result["overview"]["text"] == "real overview"
        assert result["requirements"]["text"] == "real reqs"

    def test_keeps_na_when_repair_fails(self):
        raw = self._make_raw()

        def mock_call_role(cfg, *, role, stage, messages, temperature=0.2):
            return {"output": json.dumps({"text": "N/A", "evidence": []})}

        with patch("workflow.uds_ai._call_role", side_effect=mock_call_role):
            result = _repair_missing_sections(
                raw, cfg={}, user_payload={}, analysis_payload={}
            )

        assert result["interfaces"]["text"] == "N/A"

    def test_already_generated_included_in_prompt(self):
        raw = self._make_raw()
        captured_messages = []

        def mock_call_role(cfg, *, role, stage, messages, temperature=0.2):
            captured_messages.extend(messages)
            return {"output": json.dumps({"text": "repaired", "evidence": []})}

        with patch("workflow.uds_ai._call_role", side_effect=mock_call_role):
            _repair_missing_sections(raw, cfg={}, user_payload={}, analysis_payload={})

        user_content = json.loads(captured_messages[1]["content"])
        assert "already_generated" in user_content
        assert "overview" in user_content["already_generated"]
