"""단일 산출물 직접 파싱 summarizer 단위 테스트 (2026-06-24).

정합성 비교(check_swut_consistency, 두 문서 cross-validate) 없이 빌더 산출물 1개만
파싱해 결과 요약을 뽑는 summarize_coverage_report / summarize_test_report + SwIT thin
wrapper를 검증한다. extractor(_extract_coverage_summary/_extract_sutr_summary) 내부는
기존 consistency 테스트가 이미 커버하므로, 여기서는 새로 추가한 wrapper 계층
(시트 누락 경고 / not_executed read-side 보정 / SwITC prefix 위임)만 정밀 검증한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services import swit_consistency_checker as sc  # noqa: E402
from backend.services import swut_consistency_checker as cc  # noqa: E402
from backend.services.swit_consistency_checker import (  # noqa: E402
    summarize_swit_coverage_report,
    summarize_swit_test_report,
)
from backend.services.swut_consistency_checker import (  # noqa: E402
    summarize_coverage_report,
    summarize_test_report,
)


class _FakeWB:
    def __init__(self, names):
        self.sheetnames = names


def test_coverage_summary_missing_sheets_warns(monkeypatch):
    """Traceability/Coverage 시트 없는 워크북 → parse_warnings에 누락 경고, 예외 없음."""
    monkeypatch.setattr(cc, "_load_workbook", lambda src: _FakeWB(["Sheet1"]))
    monkeypatch.setattr(
        cc, "_extract_coverage_summary",
        lambda wb, *, out_warnings, tc_prefix="SwUTC": {"total_tcs": 10},
    )
    out = summarize_coverage_report(b"x")
    assert out["coverage_summary"] == {"total_tcs": 10}
    assert any("Traceability" in w for w in out["parse_warnings"])
    assert any("Coverage" in w for w in out["parse_warnings"])


def test_coverage_summary_present_sheets_no_warn(monkeypatch):
    """정상 시트명(2.Traceability/4.Coverage/Test Summary) → 누락 경고 없음."""
    monkeypatch.setattr(
        cc, "_load_workbook",
        lambda src: _FakeWB(["2.Traceability", "4.Coverage", "1.Test Summary"]),
    )
    monkeypatch.setattr(
        cc, "_extract_coverage_summary",
        lambda wb, *, out_warnings, tc_prefix="SwUTC": {"total_tcs": 5},
    )
    out = summarize_coverage_report(b"x")
    assert out["parse_warnings"] == []
    assert out["coverage_summary"]["total_tcs"] == 5


def test_test_report_missing_summary_warns(monkeypatch):
    """Test Summary 시트 없으면 경고. sutr_summary는 그대로 반환."""
    monkeypatch.setattr(cc, "_load_workbook", lambda src: _FakeWB(["Sheet1"]))
    monkeypatch.setattr(
        cc, "_extract_sutr_summary",
        lambda wb, *, tc_prefix="SwUTC": {"total_tcs": 0, "not_executed_tcs": []},
    )
    out = summarize_test_report(b"x")
    assert "sutr_summary" in out
    assert any("Test Summary" in w for w in out["parse_warnings"])


def test_not_executed_reconciled_from_list(monkeypatch):
    """빌더가 not_executed를 0으로 남기는 결함 → not_executed_tcs 길이로 보정."""
    monkeypatch.setattr(cc, "_load_workbook", lambda src: _FakeWB(["1.Test Summary"]))
    monkeypatch.setattr(
        cc, "_extract_sutr_summary",
        lambda wb, *, tc_prefix="SwUTC": {
            "total_tcs": 30, "tested": 28, "passed": 26, "failed": 2,
            "deviated": 0, "not_executed": 0,
            "not_executed_tcs": ["SwITC_1", "SwITC_2"], "deviation_tcs": [],
            "final_result": "PASS",
        },
    )
    out = summarize_test_report(b"x", tc_prefix="SwITC")
    assert out["sutr_summary"]["not_executed"] == 2   # 0 → len(list)
    assert out["parse_warnings"] == []                # 시트 존재 → 경고 없음


def test_not_executed_not_overwritten_when_nonzero(monkeypatch):
    """이미 not_executed>0이면 보정하지 않는다(원값 보존 — 목록 길이와 달라도)."""
    monkeypatch.setattr(cc, "_load_workbook", lambda src: _FakeWB(["1.Test Summary"]))
    monkeypatch.setattr(
        cc, "_extract_sutr_summary",
        lambda wb, *, tc_prefix="SwUTC": {
            "not_executed": 5, "not_executed_tcs": ["SwITC_1"],
        },
    )
    out = summarize_test_report(b"x")
    assert out["sutr_summary"]["not_executed"] == 5


def test_swit_wrappers_delegate_with_swit_prefix(monkeypatch):
    """SwIT thin wrapper가 tc_prefix='SwITC'로 swut summarizer에 위임한다."""
    seen: dict[str, str] = {}
    monkeypatch.setattr(
        sc, "summarize_coverage_report",
        lambda src, *, tc_prefix="SwUTC": (
            seen.update(cov=tc_prefix) or {"coverage_summary": {}, "parse_warnings": []}
        ),
    )
    monkeypatch.setattr(
        sc, "summarize_test_report",
        lambda src, *, tc_prefix="SwUTC": (
            seen.update(rep=tc_prefix) or {"sutr_summary": {}, "parse_warnings": []}
        ),
    )
    summarize_swit_coverage_report(b"x")
    summarize_swit_test_report(b"x")
    assert seen == {"cov": "SwITC", "rep": "SwITC"}
