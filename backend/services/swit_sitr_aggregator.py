"""SwIT (Software Integration Test) SITR v2.02 xlsm 빌더 (34차).

SwUT SUTR 빌더 (17차 + 31차 W27 + 31-fix D10/D15) 패턴 90% 차용. xlsm 매크로
보존 (keep_vba=True) — 회사 v2.02 양식 (HDPDM01_GN7) 호환.

기존 자산 100% 재활용:
    - 시트 writer 5개 (Cover / Test Summary / Deviation / Test Log / History)
      — `swut_sutr_aggregator` import (private 함수 그대로 사용)
    - History writer — `swut_coverage_aggregator._write_history_sheet`
    - ASIL 분포 — `swut_coverage_aggregator._compute_asil_distribution`
    - 자체 일관성 (2.Consistency) — `swut_coverage_aggregator._write_consistency_sheet`
    - VBA 보존 sanity — `excel_template_utils.has_vba_macros` + `inspect_vba_refs`

SwIT 도구별 차이 (34차):
    1. 파일명 — `(HDPDM01_SITR) Software Integration Test Result_v<VER>_<DATE>_R.xlsm`
       (사용자 레퍼런스 `(HDPDM01_SITR) Software Integration Test Result_v2.02_240219.xlsm`
       패턴 정확 매칭)
    2. 결과 dataclass — `SwitSitrBuildResult` (xlsm_io 등 SwUT SutrBuildResult 동일)
    3. tool_qualification — manual review 의무 동일

ISO 26262 Integration test:
    SwIT SITR은 ASIL B+ 이상의 evidence — 분기 커버리지 + 인터페이스 테스트 결과 +
    Deviation 기록. ASIL D Test Log row 시각 강조 (31차 W27 col+4/5).
    evidence "auto-generated draft" — manual review 의무.
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

from backend.services.excel_template_utils import (
    collect_git_history,
    has_vba_macros,
    inspect_vba_refs,
    short_date,
    validate_build_meta,
    validate_xlsx_template_bytes,
)
from backend.services.swit_meta import SwitSitrBuildMeta
from backend.services.swut_builder_helpers import extract_warnings_from_session
from backend.services.swut_coverage_aggregator import (
    _compute_asil_distribution,
    _write_consistency_sheet,
    _write_history_sheet,
)
from backend.services.swut_input_adapter import (
    SwUTSession,
    aggregate_session,
)
from backend.services.swut_sutr_aggregator import (
    _write_cover,
    _write_deviation,
    _write_test_log,
    _write_test_summary,
)


@dataclass
class SwitSitrBuildResult:
    """SwIT SITR 빌드 결과 (SwUT `SutrBuildResult` 패턴 동일).

    14차 W1 메모리 절약 — ``xlsm_io: BytesIO`` 주 저장소.
    """
    ok: bool
    xlsm_io: io.BytesIO = field(default_factory=io.BytesIO)
    filename: str = ""
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    incomplete_sheets: list[str] = field(default_factory=list)
    # VBA 매크로 ZIP entry 존재 여부 (deep-reviewer W2) — 실제 실행은 사용자 의무.
    vba_macros_preserved: bool = False
    tool_qualification: dict[str, Any] = field(
        default_factory=lambda: {
            "evidence_class": "auto-generated draft",
            "asil_a_usage": "reviewer 승인 후 evidence로 사용 가능",
            "asil_b_c_d_usage": "단독 evidence 사용 금지 — manual review 의무",
        }
    )

    @property
    def xlsm_bytes(self) -> bytes:
        """Backward compat — BytesIO 전체를 bytes로 복사 (테스트/감사용)."""
        pos = self.xlsm_io.tell()
        self.xlsm_io.seek(0)
        try:
            return self.xlsm_io.read()
        finally:
            self.xlsm_io.seek(pos)

    @property
    def result_size_bytes(self) -> int:
        pos = self.xlsm_io.tell()
        self.xlsm_io.seek(0, 2)
        size = self.xlsm_io.tell()
        self.xlsm_io.seek(pos)
        return size

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "filename": self.filename,
            "result_size_bytes": self.result_size_bytes,
            "warnings": self.warnings,
            "incomplete_sheets": self.incomplete_sheets,
            "vba_macros_preserved": self.vba_macros_preserved,
            "summary": self.summary,
            "tool_qualification": self.tool_qualification,
        }


def build_swit_sitr_report(
    session: SwUTSession,
    meta: SwitSitrBuildMeta,
    template_bytes: bytes,
    deviation_cases: list[Any] | None = None,
    swuds_function_ids: set[str] | None = None,
) -> SwitSitrBuildResult:
    """SwIT SITR v2.02 xlsm 생성.

    Args:
        session: SwIT session (input_adapter 출력 — SwUT와 동일 구조).
        meta: 빌드 메타 (doc_id_base="HDPDM01-SITR").
        template_bytes: 회사 v2.02 빈 xlsm 템플릿 bytes (VBA 매크로 포함 가능).
        deviation_cases: deviation 결과 (None이면 빈 Deviation 시트).
        swuds_function_ids: 옵션 — SwUDS 함수 ID set. 제공 시 2.Consistency에
            SwUDS↔SwIT 매핑 row 추가 (시트 존재 시).

    Returns:
        SwitSitrBuildResult — xlsm_io 채워짐. 매크로 ZIP entry는 보존되나
        실행 동작은 사용자가 Excel에서 확인 필요 (deep-reviewer W2).
    """
    if openpyxl is None:
        raise RuntimeError("openpyxl is required for SwIT SITR builder")

    # 입력 메타 검증 (SwUT SUTR과 동일 정책).
    validate_build_meta(
        meta.release_sw_version, meta.test_date,
        doc_id_sequence=meta.doc_id_sequence,
        test_engineer=meta.test_engineer,
        author=meta.default_author,
        approver=meta.default_approver or meta.approver_override,
        reviewer=meta.default_reviewer or meta.reviewer_override,
    )
    # Critical (reviewer S): ZIP bomb / magic byte 검증 (xlsm도 ZIP 기반).
    validate_xlsx_template_bytes(template_bytes, label="SwIT SITR template")

    template_sha256_12 = hashlib.sha256(template_bytes).hexdigest()[:12]
    # 37차 fix → 38차 W1 DRY: extract_warnings_from_session helper로 추출.
    warnings: list[str] = extract_warnings_from_session(session)

    # deep-reviewer W2: VBA 매크로 ZIP entry 존재 여부 사전 측정.
    template_has_vba = has_vba_macros(template_bytes)
    if template_has_vba:
        warnings.append(
            "VBA macro execution NOT verified — open output xlsm in Excel and verify "
            "macros before submitting as evidence (ZIP entry preserved but stale ref 위험)"
        )
        # 5차 reviewer I1: VBA stale ref 의심 패턴 grep.
        vba_refs_found = inspect_vba_refs(template_bytes)
        if vba_refs_found:
            warnings.append(
                f"VBA stale ref 위험 패턴 발견 — {vba_refs_found} 패턴이 vbaProject.bin에 "
                "존재하며 셀/시트 이동 시 매크로 깨질 위험 (수동 검증 의무)"
            )

    # keep_vba=True — .xlsm 매크로 보존
    wb: Workbook = openpyxl.load_workbook(
        io.BytesIO(template_bytes), keep_vba=True, data_only=False,
    )
    sheet_names = wb.sheetnames

    agg = aggregate_session(session)

    # 30차 W21 + 31차 W29: ASIL 분포 — SwUT Coverage builder 재활용 (대칭 키).
    asil_distribution, ids_by_asil = _compute_asil_distribution(
        agg.get("function_rows") or [],
        agg.get("function_asil_map") or {},
    )

    summary: dict[str, Any] = {
        "environments": len(session.environments),
        "total": agg["total"],
        "tested": agg["tested"],
        "passed": agg["passed"],
        "failed": agg["failed"],
        "deviation_cases_written": 0,
        "test_log_rows_written": 0,
        # 30차 W21 + 31차 W29: SwUT Coverage/SUTR과 동일 키 — UI 노출 통일.
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
        warnings.append("Cover 시트 미발견")
    else:
        _write_cover(cover_ws, meta, out_warnings=warnings)

    # Test Summary
    ts_ws = next((wb[n] for n in sheet_names if n.lower() == "test summary"), None)
    if ts_ws is None:
        warnings.append("Test Summary 시트 미발견")
    else:
        _write_test_summary(ts_ws, meta, agg, out_warnings=warnings)

    # Deviation
    dev_ws = next((wb[n] for n in sheet_names if n.lower() == "deviation"), None)
    if dev_ws is None:
        warnings.append("Deviation 시트 미발견")
    elif deviation_cases:
        n = _write_deviation(dev_ws, deviation_cases, out_warnings=warnings)
        summary["deviation_cases_written"] = n

    # Test Log (31차 W27 ASIL col+4/5 — _write_test_log 내부에서 자동 처리)
    log_ws = next((wb[n] for n in sheet_names if n.lower() == "test log"), None)
    if log_ws is None:
        warnings.append("Test Log 시트 미발견")
    else:
        n = _write_test_log(
            log_ws, session,
            function_asil_map=agg.get("function_asil_map"),
            out_warnings=warnings,
        )
        summary["test_log_rows_written"] = n

    incomplete_sheets: list[str] = []

    # History
    hist_ws = next((wb[n] for n in sheet_names if n.lower() == "history"), None)
    if hist_ws is not None:
        git_rows = collect_git_history(limit=10)
        if git_rows:
            n_h = _write_history_sheet(hist_ws, git_rows, out_warnings=warnings)
            summary["history_rows_written"] = n_h
            if n_h == 0:
                incomplete_sheets.append("History")
        else:
            warnings.append("git log 가져오기 실패 — History 시트 placeholder")
            incomplete_sheets.append("History")

    # 2.Consistency — SUTR v3.01과 마찬가지로 옵션 (양식에 없으면 silent skip).
    # 34차 C2 fix: test_kind="SwIT" — intro 텍스트 + row 5 item label 치환.
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

    # 14차 W1: BytesIO 그대로 result에 저장.
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    wb.close()

    # 사용자 레퍼런스 파일명 패턴 정확 매칭:
    # `(HDPDM01_SITR) Software Integration Test Result_v2.02_240219.xlsm`
    filename = (
        f"({meta.project_id}_SITR) Software Integration Test Result_"
        f"v{meta.release_sw_version}_{short_date(meta.test_date)}_R.xlsm"
    )

    summary["template_sha256_12"] = template_sha256_12
    summary["build_timestamp"] = meta.build_timestamp
    return SwitSitrBuildResult(
        ok=True,
        xlsm_io=out,
        filename=filename,
        warnings=warnings,
        incomplete_sheets=incomplete_sheets,
        vba_macros_preserved=template_has_vba,
        summary=summary,
    )


__all__ = [
    "SwitSitrBuildResult",
    "build_swit_sitr_report",
]
