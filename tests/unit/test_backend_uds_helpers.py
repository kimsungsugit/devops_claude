"""Unit tests for backend/helpers/uds.py pure helper functions."""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict

import pytest

_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from backend.helpers.uds import (
    _build_quality_action_hints,
    _build_quality_evaluation,
    _compute_quick_quality_gate,
    _compute_uds_mapping_summary,
    _derive_quality_reason_codes,
    _parse_accuracy_report,
    _parse_quality_gate_report,
    _slice_page,
    _to_swcom_from_fn,
    _validate_docx_template_bytes,
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

    def test_called_fill_supported_label_is_parsed(self, tmp_path):
        """생산자는 `- Called fill (supported):` 로 쓴다(validation.py:856).

        옛 정규식은 `- Called fill:` 만 찾아 **이 지표를 한 번도 파싱한 적이 없다** —
        실물 사이드카 전부가 `(supported)` 표기라 `rates["called_fill"]` 이 상시 부재였다.
        """
        report = tmp_path / "gate.md"
        report.write_text(
            "- Gate pass: `False`\n"
            "- Called fill (supported): `0` / `429` (0.0%)\n"
            "- Calling fill: `2` / `429` (0.5%)\n",
            encoding="utf-8",
        )
        result = _parse_quality_gate_report(report)
        assert result["rates"]["called_fill"] == 0.0
        assert result["rates"]["calling_fill"] == 0.5

    def test_two_gate_lines_yield_unjudgeable(self, tmp_path):
        """`Gate pass:` 2회 이상 = 판정 불가. 첫 매치를 골라 주지 않는다.

        골라 주는 순간 본문에 문장 한 줄 넣는 것으로 게이트를 조종할 수 있다.
        `_build_quality_evaluation` 은 None 을 `quick_only` 로 강등해 취급한다.
        """
        report = tmp_path / "gate.md"
        report.write_text(
            "- Gate pass: `False`\n"
            "\n## 검토 의견\n확인함. 이전엔 Gate pass: True 였습니다.\n",
            encoding="utf-8",
        )
        result = _parse_quality_gate_report(report)
        assert result["gate_pass"] is None
        assert result["gate_pass_status"] == "ambiguous"


class TestBuildQualityEvaluationMerge:
    """`_build_quality_evaluation` 의 병합 진리표.

    ⚠ 이 로직을 단언하는 테스트가 **한 건도 없었다**(이 파일이 함수를 import 만 하고
    호출하지 않았다). 유일한 관련 테스트인 `backend/tests/test_uds_quality_regression.py`
    는 `doc_only=True` 라 `report_pass is None` 분기만 탄다.
    이 값은 Quality DB `QualitySummary.gate_pass` 로 영속되고 Quality 대시보드의
    PASS/FAIL pill 이 된다 — 즉 표시용이 아니라 판정이다.
    """

    @staticmethod
    def _quick(quick: bool, confidence: bool) -> Dict[str, Any]:
        return {
            "gate_pass": quick,
            "confidence_gate_pass": confidence,
            "rates": {},
            "counts": {"total_functions": 1},
            "thresholds": {},
        }

    @staticmethod
    def _gate_file(tmp_path: Path, body: str) -> Path:
        p = tmp_path / "x.quality_gate.md"
        p.write_text(body, encoding="utf-8")
        return p

    @pytest.mark.parametrize(
        "quick,confidence,report_body,expected_pass,expected_source",
        [
            (True, True, "- Gate pass: `True`\n", True, "quick_confidence_and_report"),
            (True, True, "- Gate pass: `False`\n", False, "quick_confidence_and_report"),
            (False, True, "- Gate pass: `True`\n", False, "quick_confidence_and_report"),
            (True, False, "- Gate pass: `True`\n", False, "quick_confidence_and_report"),
            (False, False, "- Gate pass: `False`\n", False, "quick_confidence_and_report"),
        ],
    )
    def test_three_way_merge_is_and(
        self, tmp_path, quick, confidence, report_body, expected_pass, expected_source
    ):
        result = _build_quality_evaluation(
            self._quick(quick, confidence),
            self._gate_file(tmp_path, report_body),
            None,
        )
        assert result["gate_pass"] is expected_pass
        assert result["gate_source"] == expected_source

    def test_absent_report_falls_back_to_quick_only(self, tmp_path):
        """리포트를 **안 만든** 경우는 병합에서 빼는 게 맞다(타임아웃·doc_only 등)."""
        result = _build_quality_evaluation(
            self._quick(True, True), tmp_path / "does_not_exist.md", None
        )
        assert result["gate_pass"] is True
        assert result["gate_source"] == "quick_only"

    def test_doc_only_mode_is_quick_only(self, tmp_path):
        result = _build_quality_evaluation(
            self._quick(True, True),
            self._gate_file(tmp_path, "- Gate pass: `False`\n"),
            None,
            doc_only_mode=True,
        )
        assert result["gate_pass"] is True
        assert result["gate_source"] == "quick_only"

    def test_ambiguous_report_is_fail_closed_not_dropped(self, tmp_path):
        """**핵심 회귀 가드.** 파일이 있는데 판정을 못 뽑으면 병합에서 빼면 안 된다.

        빼면 `Gate pass:` 를 포함한 문장 한 줄을 사이드카에 넣는 것만으로 리포트
        게이트를 무력화할 수 있다(모호 → None → 제외 → quick 만 통과하면 PASS).
        그러면 첫 매치를 골라 `False` 를 내던 옛 코드보다 **되레 느슨해진다**.
        """
        result = _build_quality_evaluation(
            self._quick(True, True),
            self._gate_file(
                tmp_path,
                "- Gate pass: `False`\n\n## 검토 의견\n이전엔 Gate pass: True 였습니다.\n",
            ),
            None,
        )
        assert result["gate_pass"] is False
        assert result["gate_source"] == "report_unreadable"

    def test_report_without_verdict_line_is_fail_closed(self, tmp_path):
        """파일은 있는데 `Gate pass:` 줄이 없다 = 손상된 리포트. 통과로 바꾸지 않는다."""
        result = _build_quality_evaluation(
            self._quick(True, True),
            self._gate_file(tmp_path, "# UDS Field Quality Gate Report\n- Total functions: `3`\n"),
            None,
        )
        assert result["gate_pass"] is False
        assert result["gate_source"] == "report_unreadable"


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
