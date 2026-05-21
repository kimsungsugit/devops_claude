"""SwIT (Software Integration Test) Coverage Report v2.02 xlsx 빌더 (33차).

SwUT Coverage Report v3.01 빌더 (30~32차 완성)와 동일 시트 구조 (Cover /
Test Summary / 1.Traceability / 2.Consistency / 3.Coverage / History).
회사 v2.02 양식 (HDPDM01_GN7) 호환 — v3.01 양식과 시트 명명 동일하나
헤더 위치 / 일부 컬럼 변동 가능 (33-fix 라운드에서 실 양식 확인 후 조정).

기존 자산 100% 재활용:
    - 시트 writer 6개 (Cover / Test Summary / Coverage / Traceability /
      Consistency / History) — `swut_coverage_aggregator` 그대로 import
    - ASIL 분포 / 자체 일관성 계산 함수 — `_compute_asil_distribution` /
      `_compute_self_consistency` import
    - excel_template_utils 헬퍼 (safe_write / validate_* / collect_git_history)

SwIT 도구별 차이 (33차):
    1. 파일명 — `(HDPDM01)SwIT Coverage Report_v<VER>_<DATE>_R.xlsx`
    2. 결과 dataclass — `SwitCoverageBuildResult` (xlsx_io 등 SwUT 동일 패턴)
    3. tool_qualification asil_b_c_d_usage 문구는 SwUT와 동일 (manual review
       의무)

ISO 26262 Integration test:
    SwIT는 ASIL B+ 이상에서 의무 (분기 커버리지 + 인터페이스 테스트). evidence
    "auto-generated draft" 정책 유지 — manual review 의무.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import Any

try:
    import openpyxl
    from openpyxl.workbook.workbook import Workbook
except ImportError:  # pragma: no cover
    openpyxl = None  # type: ignore[assignment]

from backend.services.excel_layout_resolver import inspect_swit_layout
from backend.services.excel_template_utils import (
    build_release_history_row,
    short_date,
    validate_build_meta,
    validate_xlsx_template_bytes,
)
from backend.services.swit_meta import SwitCoverageBuildMeta
from backend.services.swut_builder_helpers import extract_warnings_from_session
from backend.services.swut_coverage_aggregator import (
    _compute_asil_distribution,
    _write_consistency_sheet,
    _write_cover_sheet,
    _write_coverage_sheet,
    _write_history_sheet,
    _write_test_summary_sheet,
    _write_traceability_sheet,
)
from backend.services.swut_input_adapter import (
    SwUTSession,
    aggregate_session,
)


@dataclass
class SwitCoverageBuildResult:
    """SwIT Coverage Report 빌드 결과 (SwUT `CoverageBuildResult` 패턴 동일).

    14차 W1 메모리 절약 — ``xlsx_io: BytesIO`` 주 저장소.
    """
    ok: bool
    xlsx_io: io.BytesIO = field(default_factory=io.BytesIO)
    filename: str = ""
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    incomplete_sheets: list[str] = field(default_factory=list)
    tool_qualification: dict[str, Any] = field(
        default_factory=lambda: {
            "evidence_class": "auto-generated draft",
            "asil_a_usage": "reviewer 승인 후 evidence로 사용 가능",
            "asil_b_c_d_usage": "단독 evidence 사용 금지 — manual review 의무",
        }
    )

    @property
    def xlsx_bytes(self) -> bytes:
        pos = self.xlsx_io.tell()
        self.xlsx_io.seek(0)
        try:
            return self.xlsx_io.read()
        finally:
            self.xlsx_io.seek(pos)

    @property
    def result_size_bytes(self) -> int:
        pos = self.xlsx_io.tell()
        self.xlsx_io.seek(0, 2)
        size = self.xlsx_io.tell()
        self.xlsx_io.seek(pos)
        return size

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "filename": self.filename,
            "result_size_bytes": self.result_size_bytes,
            "warnings": self.warnings,
            "incomplete_sheets": self.incomplete_sheets,
            "summary": self.summary,
            "tool_qualification": self.tool_qualification,
        }


def build_swit_coverage_report(
    session: SwUTSession,
    meta: SwitCoverageBuildMeta,
    template_bytes: bytes,
    swuds_function_ids: set[str] | None = None,
) -> SwitCoverageBuildResult:
    """SwIT Coverage Report v2.02 xlsx 생성.

    Args:
        session: SwIT session (input_adapter 출력 — SwUT와 동일 구조).
        meta: 빌드 메타.
        template_bytes: v2.02 빈 xlsx 템플릿 bytes.
        swuds_function_ids: 옵션 — SwUDS 함수 ID set. 제공 시 2.Consistency에
            SwUDS↔SwIT 매핑 row 추가.

    Returns:
        SwitCoverageBuildResult — xlsx_io 채워짐.
    """
    if openpyxl is None:
        raise RuntimeError("openpyxl is required for SwIT Coverage Report builder")

    # 입력 메타 검증 (SwUT와 동일 정책).
    validate_build_meta(
        meta.release_sw_version, meta.test_date,
        doc_id_sequence=meta.doc_id_sequence,
        test_engineer=meta.test_engineer,
        author=meta.default_author,
        approver=meta.default_approver or meta.approver_override,
        reviewer=meta.default_reviewer or meta.reviewer_override,
    )
    validate_xlsx_template_bytes(template_bytes, label="SwIT Coverage Report template")

    template_sha256_12 = hashlib.sha256(template_bytes).hexdigest()[:12]
    # 37차 fix → 38차 W1 DRY: extract_warnings_from_session helper로 추출.
    warnings: list[str] = extract_warnings_from_session(session)

    # 54차 T280 — v2.02 양식 layout 자동 추출 (sha256 keying + LRU)
    layout = inspect_swit_layout(template_bytes, "coverage")
    if layout.warnings:
        warnings.extend([f"[layout] {w}" for w in layout.warnings])

    wb: Workbook = openpyxl.load_workbook(io.BytesIO(template_bytes), data_only=False)
    sheet_names = wb.sheetnames

    agg = aggregate_session(session)

    # 30차 W21 + 31차 W29: 함수별 ASIL 분포 (SwUT 함수 재활용).
    asil_distribution, ids_by_asil = _compute_asil_distribution(
        agg.get("function_rows") or [],
        agg.get("function_asil_map") or {},
    )

    summary: dict[str, Any] = {
        "environments": len(session.environments),
        "total_tcs": agg["total_tcs"],
        "passed": agg["passed"],
        "failed": agg["failed"],
        "function_rows": agg["function_count"],
        # 30차 W21 + 31차 W29 + 32차 W28: ASIL 분포 + 등급별 함수 ID + 정책 메타.
        "asil_distribution": asil_distribution,
        "asil_b_function_ids": ids_by_asil.get("B", []),
        "asil_c_function_ids": ids_by_asil.get("C", []),
        "asil_d_function_ids": ids_by_asil.get("D", []),
        "asil_highlight_policy": (
            "B=파랑(#E2F0FF) / C=주황(#FFE5CC) / D=빨강(#FFC7CE) — "
            "31차 비표준 audit 확장 (회사 v2.02 양식은 빨강만 사용)"
        ),
    }

    # Cover
    cover_ws = next((wb[n] for n in sheet_names if n.lower() == "cover"), None)
    if cover_ws is None:
        warnings.append("Cover 시트 미발견 — Doc ID/Author 등 미기록")
    else:
        # 54차 T282: layout 전달 — v2.02 cover_labels 동적 매칭.
        _write_cover_sheet(cover_ws, meta, out_warnings=warnings, layout=layout)

    # Test Summary — 53차 fix: SwIT v2.02 양식은 "1.Test Summary"라 substring 매칭으로 변경.
    # SwUT v3.01의 "Test Summary"도 substring으로 포함되어 호환 유지.
    ts_ws = next((wb[n] for n in sheet_names if "test summary" in n.lower()), None)
    if ts_ws is None:
        warnings.append("Test Summary 시트 미발견")
    else:
        # 54차 T282/T283: layout + summary 전달 — v2.02 label + B17 TC stats + B22.
        _write_test_summary_sheet(
            ts_ws, meta, agg, out_warnings=warnings,
            layout=layout, summary=summary,
        )

    # 3.Coverage
    incomplete_sheets: list[str] = []
    cov_ws = next(
        (wb[n] for n in sheet_names
         if "coverage" in n.lower() and "traceability" not in n.lower()
         and "consistency" not in n.lower()),
        None,
    )
    if cov_ws is None:
        warnings.append("3.Coverage 시트 미발견")
    else:
        n_written = _write_coverage_sheet(cov_ws, agg)
        summary["coverage_rows_written"] = n_written

    # 1.Traceability
    trace_ws = next((wb[n] for n in sheet_names if "traceability" in n.lower()), None)
    if trace_ws is None:
        warnings.append("1.Traceability 시트 미발견")
    else:
        n_o = _write_traceability_sheet(trace_ws, session, out_warnings=warnings)
        summary["traceability_o_cells"] = n_o
        if n_o == 0:
            incomplete_sheets.append("1.Traceability")

    # 2.Consistency — 34차 C2 fix: test_kind="SwIT" (intro/row 5 item 라벨 치환)
    cons_ws = next((wb[n] for n in sheet_names if "consistency" in n.lower()), None)
    if cons_ws is not None:
        n_cons = _write_consistency_sheet(
            cons_ws, session,
            swuds_function_ids=swuds_function_ids,
            out_warnings=warnings,
            test_kind="SwIT",
        )
        summary["consistency_self_check_rows"] = n_cons
        if swuds_function_ids is not None:
            summary["consistency_swuds_compared"] = True
        else:
            summary["consistency_swuds_compared"] = False
            incomplete_sheets.append("2.Consistency (SwUDS 비교 partial)")
    else:
        warnings.append("2.Consistency 시트 미발견")
        incomplete_sheets.append("2.Consistency")

    # History — 55-fix: single-row release entry (사용자 결정 B)
    hist_ws = next((wb[n] for n in sheet_names if n.lower() == "history"), None)
    if hist_ws is not None:
        release_rows = build_release_history_row(meta, doc_kind="SwIT Coverage")
        n_h = _write_history_sheet(hist_ws, release_rows, out_warnings=warnings)
        summary["history_rows_written"] = n_h
        if n_h == 0:
            incomplete_sheets.append("History")

    # 14차 W1: BytesIO 그대로 result에 저장.
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    wb.close()

    filename = (
        f"({meta.project_id})SwIT Coverage Report_"
        f"v{meta.release_sw_version}_{short_date(meta.test_date)}_R.xlsx"
    )

    summary["template_sha256_12"] = template_sha256_12
    summary["build_timestamp"] = meta.build_timestamp
    return SwitCoverageBuildResult(
        ok=True,
        xlsx_io=out,
        filename=filename,
        warnings=warnings,
        incomplete_sheets=incomplete_sheets,
        summary=summary,
    )


__all__ = [
    "SwitCoverageBuildResult",
    "build_swit_coverage_report",
]
