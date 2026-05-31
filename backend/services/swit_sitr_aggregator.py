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

from backend.services.excel_layout_resolver import inspect_swit_layout
from backend.services.excel_template_utils import (
    build_release_history_row,
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
    swuts_map: dict[str, Any] | None = None,
) -> SwitSitrBuildResult:
    """SwIT SITR v2.02 xlsm 생성.

    Args:
        session: SwIT session (input_adapter 출력 — SwUT와 동일 구조).
        meta: 빌드 메타 (doc_id_base="HDPDM01-SITR").
        template_bytes: 회사 v2.02 빈 xlsm 템플릿 bytes (VBA 매크로 포함 가능).
        deviation_cases: deviation 결과 (None이면 빈 Deviation 시트).
        swuds_function_ids: 옵션 — SwUDS 함수 ID set. 제공 시 2.Consistency에
            SwUDS↔SwIT 매핑 row 추가 (시트 존재 시).
        swuts_map: 60차 F6-A — SwITS xlsm parser 결과 (옵션, SwUT swuts_map 인자명 재사용).
            제공 시 Test Log B/C/D + Precondition col에 spec 데이터 stamp.

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

    # 라운드 73 T816 — 입력 자산 활용도 진단.
    from backend.services.swut_builder_helpers import diagnose_asset_usage
    warnings.extend(diagnose_asset_usage(
        swits_map=swuts_map,  # SITR는 swuts_map kwarg로 SwITS 받음
        c_function_map=session.c_function_map or None,
        swuds_function_map=session.swuds_function_map or None,
    ))

    # 54차 T280 — v2.02 양식 layout 자동 추출 (sha256 keying + LRU).
    layout = inspect_swit_layout(template_bytes, "sitr")
    if layout.warnings:
        warnings.extend([f"[layout] {w}" for w in layout.warnings])

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

    # 30차 W21 + 31차 W29 + 라운드 84 T1801 + 85 T1903 + 86 T2001: unmapped fc list.
    asil_distribution, ids_by_asil, unmapped_fns = _compute_asil_distribution(
        agg.get("function_rows") or [],
        agg.get("function_asil_map") or {},
        function_asil_from_suds=agg.get("function_asil_from_suds"),
        component_asil_from_sds=agg.get("component_asil_from_sds"),
        function_asil_from_srs=agg.get("function_asil_from_srs"),
        function_name_to_swufn_from_suds=agg.get("function_name_to_swufn_from_suds"),
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
        # 라운드 86 T2002: UNKNOWN 함수 list (audit 진단용).
        "unmapped_function_names": unmapped_fns,
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
        # 54차 T282: layout 전달
        _write_cover(cover_ws, meta, out_warnings=warnings, layout=layout)

    # Test Summary — 53차 fix: SwIT v2.02 양식의 "1.Test Summary" 등 prefix 호환 substring 매칭.
    ts_ws = next((wb[n] for n in sheet_names if "test summary" in n.lower()), None)
    if ts_ws is None:
        warnings.append("Test Summary 시트 미발견")
    else:
        # 54차 T282/T283: layout + summary → v2.02 label + B17 TC stats + B22
        _write_test_summary(
            ts_ws, meta, agg, out_warnings=warnings,
            layout=layout, summary=summary,
        )

    # Deviation — 53차 fix: substring 매칭
    dev_ws = next((wb[n] for n in sheet_names if "deviation" in n.lower()), None)
    if dev_ws is None:
        # 라운드 74 T903 — Deviation 시트 fallback warning 톤 분리.
        # 회사 KJPDS02 v1.01 양식은 SwITR 4 시트만 (Cover/History/1.Test Summary/2.Test Log)
        # → Deviation 시트 미정의가 정상. WARN 톤 → INFO 톤으로 분리 (audit reviewer 혼동 해소).
        # layout.deviation_sheet_present=False는 inspect_swit_layout이 v1.01 양식 인식한 결과.
        if getattr(layout, "deviation_sheet_present", True) is False:
            warnings.append(
                "[양식정상] Deviation 시트 미발견 — 회사 v1.01 양식 표준 (4 시트). "
                "audit reviewer는 deviation 발생 시 별도 첨부 필요."
            )
        else:
            warnings.append(
                "[양식손상] Deviation 시트 미발견 — v2.02/v3.01 양식은 Deviation 시트 정의 필수. "
                "template 손상 가능성 — 입력 template 확인 의무."
            )
    elif deviation_cases:
        n = _write_deviation(dev_ws, deviation_cases, out_warnings=warnings)
        summary["deviation_cases_written"] = n

    # Test Log — 53차 fix: substring 매칭. 57차 T314: 'test result'도 포함 (v2.02
    # SUTR/SITR 회사 양식 시트명 'Test Result' 호환).
    log_ws = next(
        (wb[n] for n in sheet_names
         if "test log" in n.lower() or "test result" in n.lower()),
        None,
    )
    if log_ws is None:
        warnings.append("Test Log/Result 시트 미발견")
    else:
        # 54차 T283: layout 전달 — v2.02 AL column marker fill
        # 라운드 78 T1303: c_function_map 전달 — ASIL fallback (SwUT 대칭).
        n = _write_test_log(
            log_ws, session,
            function_asil_map=agg.get("function_asil_map"),
            out_warnings=warnings,
            layout=layout,
            swuts_map=swuts_map,
            c_function_map=session.c_function_map or None,
        )
        summary["test_log_rows_written"] = n

    incomplete_sheets: list[str] = []

    # History — 55-fix: single-row release entry (사용자 결정 B)
    hist_ws = next((wb[n] for n in sheet_names if n.lower() == "history"), None)
    if hist_ws is not None:
        # 55-fix-2 W2: 4 aggregator 명명 통일
        # 55-fix-2 W6: out_warnings 전달
        release_rows = build_release_history_row(
            meta, doc_kind="SwIT SITR", out_warnings=warnings,
        )
        n_h = _write_history_sheet(hist_ws, release_rows, out_warnings=warnings)
        summary["history_rows_written"] = n_h
        if n_h == 0:
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

    # 라운드 83 T1703: AuditLog 시트 신규 추가 (SwUT 대칭).
    try:
        from backend.services.swut_coverage_aggregator import _write_audit_log_sheet
        if "AuditLog" not in wb.sheetnames:
            audit_ws = wb.create_sheet("AuditLog")
            n_audit = _write_audit_log_sheet(
                audit_ws, meta, summary, agg, session, warnings,
            )
            summary["audit_log_rows_written"] = n_audit
            summary["audit_log_sheet_added"] = True
    except Exception as _e:  # pragma: no cover — fail-safe
        warnings.append(
            f"AuditLog 시트 작성 실패 (산출물 영향 0): {type(_e).__name__}: {str(_e)[:80]}"
        )

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
