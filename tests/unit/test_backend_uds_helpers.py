"""Unit tests for backend/helpers/uds.py pure helper functions."""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from backend.helpers.uds import (
    _compute_quick_quality_gate,
    _derive_quality_reason_codes,
    _build_quality_action_hints,
    _build_quality_evaluation,
    _parse_quality_gate_report,
    _parse_accuracy_report,
    _to_swcom_from_fn,
    _validate_docx_template_bytes,
    _slice_page,
    _compute_uds_mapping_summary,
)


class TestComputeQuickQualityGate:
    def test_no_functions(self):
        result = _compute_quick_quality_gate({})
        assert result["gate_pass"] is False
        assert result["reason"] == "no functions"
        assert result["counts"]["total_functions"] == 0

    def test_with_functions(self):
        by_name = {
            "func_a": {
                "name": "func_a",
                "inputs": ["[IN] int x"],
                "outputs": ["[OUT] return int"],
                "called": "func_b",
                "calling": "main",
                "globals_global": "g_var",
                "globals_static": "s_var",
                "description": "Does something",
                "asil": "B",
                "related": "SwCom_01",
                "description_source": "sds",
                "asil_source": "sds",
                "related_source": "sds",
            },
        }
        result = _compute_quick_quality_gate({"function_details_by_name": by_name})
        assert result["counts"]["total_functions"] == 1
        assert result["rates"]["input_fill"] == 100.0
        assert result["rates"]["output_fill"] == 100.0


class TestValidateDocxTemplateBytes:
    def test_empty_bytes(self):
        ok, msg = _validate_docx_template_bytes(None)
        assert ok is False
        assert "empty" in msg

    def test_valid_docx(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", "<w:document/>")
        ok, msg = _validate_docx_template_bytes(buf.getvalue())
        assert ok is True
        assert msg == ""

    def test_invalid_zip(self):
        ok, msg = _validate_docx_template_bytes(b"not a zip")
        assert ok is False
        assert "invalid" in msg.lower()

    def test_missing_document_xml(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("other.xml", "<x/>")
        ok, msg = _validate_docx_template_bytes(buf.getvalue())
        assert ok is False
        assert "document.xml" in msg


class TestParseQualityGateReport:
    def test_none_path(self):
        result = _parse_quality_gate_report(None)
        assert result["gate_pass"] is None

    def test_parse_content(self, tmp_path):
        report = tmp_path / "gate.md"
        report.write_text(
            "- Gate pass: `True`\n"
            "- Description fill: `8` / `10` (80.0%)\n"
            "- Called fill: `9` / `10` (90.0%)\n",
            encoding="utf-8",
        )
        result = _parse_quality_gate_report(report)
        assert result["gate_pass"] is True
        assert result["rates"]["description_fill"] == 80.0
        assert result["rates"]["called_fill"] == 90.0


class TestParseAccuracyReport:
    def test_none_path(self):
        result = _parse_accuracy_report(None)
        assert result["called_exact_match"] is None

    def test_parse_content(self, tmp_path):
        report = tmp_path / "acc.md"
        report.write_text(
            "Called exact match: 45/50 (90.0%)\n"
            "Calling exact match: 40/50 (80.0%)\n",
            encoding="utf-8",
        )
        result = _parse_accuracy_report(report)
        assert result["called_exact_match"] == 90.0
        assert result["calling_exact_match"] == 80.0


class TestDeriveQualityReasonCodes:
    def test_no_functions(self):
        codes = _derive_quality_reason_codes({})
        assert "NO_FUNCTIONS" in codes

    def test_low_called(self):
        gate = {
            "rates": {"called_fill": 50.0},
            "thresholds": {"called_min": 95.0},
            "counts": {"total_functions": 10},
        }
        codes = _derive_quality_reason_codes(gate)
        assert "CALLED_LOW" in codes

    def test_template_invalid(self):
        gate = {"counts": {"total_functions": 1}, "rates": {}, "thresholds": {}}
        codes = _derive_quality_reason_codes(gate, template_warning="bad template")
        assert "TEMPLATE_INVALID" in codes


class TestBuildQualityActionHints:
    def test_called_low(self):
        hints = _build_quality_action_hints(["CALLED_LOW"])
        assert len(hints) == 1
        assert "called" in hints[0].lower()

    def test_empty(self):
        assert _build_quality_action_hints([]) == []

    def test_multiple(self):
        hints = _build_quality_action_hints(["INPUT_PARSE_LOW", "NO_FUNCTIONS"])
        assert len(hints) == 2


class TestToSwcomFromFn:
    def test_with_swcom(self):
        assert _to_swcom_from_fn({"swcom": "SwCom_01"}) == "SwCom_01"

    def test_from_id(self):
        result = _to_swcom_from_fn({"id": "SwUFn_03_something"})
        assert result == "SwCom_03"

    def test_unmapped(self):
        assert _to_swcom_from_fn({"id": "random"}) == "UNMAPPED"


class TestSlicePage:
    def test_first_page(self):
        rows = [{"i": i} for i in range(100)]
        page, total = _slice_page(rows, 1, 10)
        assert len(page) == 10
        assert total == 100
        assert page[0]["i"] == 0

    def test_second_page(self):
        rows = [{"i": i} for i in range(25)]
        page, total = _slice_page(rows, 2, 10)
        assert len(page) == 10
        assert page[0]["i"] == 10

    def test_beyond_last(self):
        rows = [{"i": i} for i in range(5)]
        page, total = _slice_page(rows, 10, 10)
        assert page == []
        assert total == 5


class TestComputeUdsMappingSummary:
    def test_dict_input(self):
        rows = {
            "f1": {"sds_match_scope": "function", "asil": "B"},
            "f2": {"sds_match_scope": "swcom", "asil": "TBD", "related": ""},
        }
        result = _compute_uds_mapping_summary(rows)
        assert result["total"] == 2
        assert result["direct"] == 1
        assert result["fallback"] == 1
        assert result["residual_tbd_count"] == 1

    def test_empty(self):
        result = _compute_uds_mapping_summary([])
        assert result["total"] == 0
