"""SwUT SUTR (Software Unit Test Result) v3.01 xlsm 빌더.

기존 v3.01 xlsm 템플릿을 BytesIO로 로드 → 5시트 셀 치환 → bytes 반환.
스타일/머지셀/매크로 보존 (template-copy 전략, keep_vba=True).

## 시트 매핑 (5 시트)

| 시트 | 출처 |
|------|------|
| Cover | meta (Doc ID / Project / ASIL / Author) |
| History | git log + 사람 입력 (다음 라운드, 본 라운드 placeholder) |
| Test Summary | SwUTSession 집계 (Total/Tested/Passed/Failed/Deviated/NotExec) |
| Deviation | swut_deviation_generator 자동 호출 (DRAFT 라벨) |
| Test Log | per-TC input/expected/actual/pass (각 환경 TestCaseData 통합) |

## ISO 26262 Tool Qualification
ASIL A 한정 draft. B/C/D는 manual review 의무.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from typing import Any

try:
    import openpyxl
    from openpyxl.workbook.workbook import Workbook
except ImportError:  # pragma: no cover
    openpyxl = None  # type: ignore[assignment]

from backend.services.excel_template_utils import (
    build_release_history_row,
    find_kv_row,
    has_vba_macros,
    inspect_vba_refs,
    mark_asil_b_function,
    mark_asil_c_function,
    mark_asil_d_function,
    mark_user_input_required,
    safe_write,
    short_date,
    truncate_cell_text,
    validate_build_meta,
    validate_xlsx_template_bytes,
    write_label_or_mark,
    write_value_after_label,
)

# 31차 W27: TC name에서 SwUFn_NNNN 함수 ID 추출 (Coverage builder와 동일 패턴).
_TC_FN_RE = re.compile(r"(SwUFn_\d+)")
from backend.services.swut_builder_helpers import extract_warnings_from_session
from backend.services.swut_input_adapter import SwUTSession, aggregate_session
from backend.services.swut_meta import BuildMetaBase


@dataclass
class SutrBuildMeta(BuildMetaBase):
    """SUTR 빌드 메타 — base에 SUTR 전용 2 필드 + final_test_result default override.

    T137 (W3 fix): `CoverageBuildMeta` 와 17 공통 필드를 `BuildMetaBase` 단일 출처로.
    """
    doc_id_base: str = "HDPDM01-SUTR"
    target_coverage: float = 1.0
    target_pass_ratio: float = 1.0
    final_test_result: str = "OK"  # Coverage는 "PASS", SUTR은 "OK"


@dataclass
class SutrBuildResult:
    """SUTR 빌드 결과.

    14차 W1: 메모리 절약 — ``xlsm_io: BytesIO`` 가 주 저장소. ``xlsm_bytes`` 는
    backward compat property — 호출 시점에 ``getvalue()`` (1회 copy).
    """
    ok: bool
    xlsm_io: io.BytesIO = field(default_factory=io.BytesIO)
    filename: str = ""
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    incomplete_sheets: list[str] = field(default_factory=list)
    # VBA 매크로 ZIP entry 존재 여부 (deep-reviewer W2) — 실제 실행 검증은 사용자 의무.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# helper 함수는 backend/services/excel_template_utils.py 로 통합 (reviewer 권고 X5).


# _aggregate 는 swut_input_adapter.aggregate_session 으로 통합 (deep-reviewer W3).


# ---------------------------------------------------------------------------
# Sheet writers
# ---------------------------------------------------------------------------

_OPTIONAL_LABELS = {"Build Timestamp", "Reviewer", "Doc. ID"}


def _write_label(ws, label: str, value: Any, out_warnings: list[str] | None) -> None:
    """K1 (reviewer): 라벨 미발견 시 warnings 누적 — 단 optional 라벨은 silent OK."""
    ok = write_value_after_label(ws, label, value)
    if not ok and label not in _OPTIONAL_LABELS and out_warnings is not None:
        out_warnings.append(f"라벨 '{label}' 미발견 — 셀 쓰기 skip")


def _write_label_or_mark(
    ws, label: str, value: Any, hint: str,
    out_warnings: list[str] | None,
) -> None:
    """23차 T192/W12: excel_template_utils.write_label_or_mark 래퍼 — _OPTIONAL_LABELS 주입."""
    write_label_or_mark(
        ws, label, value, hint=hint,
        optional_labels=_OPTIONAL_LABELS,
        out_warnings=out_warnings,
    )


def _write_cover(
    ws, meta: SutrBuildMeta, out_warnings: list[str] | None = None,
    *, layout: Any = None,
) -> None:
    """54차 T282: layout 제공 시 cover_labels 매핑으로 v2.02 양식 동적 호환."""
    labels = layout.cover_labels if layout else {}
    _write_label(ws, labels.get("project_full_name", "Project"),
                 meta.project_full_name, out_warnings)
    _write_label(ws, labels.get("asil_level", "ASIL Level"),
                 meta.asil_level, out_warnings)
    _write_label(ws, labels.get("status", "Status"),
                 "DRAFT — PENDING REVIEW", out_warnings)
    # 23차 T192: 비어있으면 노란 강조 (audit reviewer 가시성)
    _write_label_or_mark(ws, labels.get("validation_date", "Validation Date"),
                         meta.validation_date,
                         "yyyy-mm-dd 형식 검증 완료일", out_warnings)
    _write_label_or_mark(ws, labels.get("author", "Author"), meta.author,
                         "test_engineer 또는 default_author", out_warnings)
    _write_label_or_mark(ws, labels.get("approver", "Approver"), meta.approver,
                         "승인자 이름 (필수)", out_warnings)
    if meta.doc_id_sequence:
        _write_label(ws, labels.get("doc_id", "Doc. ID"),
                     f"{meta.doc_id_base}-{meta.doc_id_sequence}", out_warnings)
    _write_label(ws, labels.get("version", "Version"),
                 f"v{meta.release_sw_version}", out_warnings)
    # optional — 회사 v3.01 template에 라벨이 없을 수 있어 silent skip 허용.
    _write_label(ws, labels.get("build_timestamp", "Build Timestamp"),
                 meta.build_timestamp, out_warnings)


def _write_test_summary(
    ws, meta: SutrBuildMeta, agg: dict[str, Any],
    out_warnings: list[str] | None = None,
    *, layout: Any = None, summary: dict[str, Any] | None = None,
) -> None:
    """54차 T282/T283: layout 제공 시 v2.02 양식 동적 호환."""
    labels = layout.test_summary_labels if layout else {}
    _write_label(ws, labels.get("project_full_name", "Project Name"),
                 meta.project_full_name, out_warnings)
    _write_label(ws, labels.get("release_sw_version", "Release Name(SW)"),
                 meta.release_sw_version, out_warnings)
    _write_label(ws, labels.get("hw_version", "Test Target Version(HW)"),
                 meta.hw_version, out_warnings)
    _write_label(ws, labels.get("test_date", "Test Date"),
                 meta.test_date, out_warnings)
    # 24차: Test Engineer 빈 시 노란 강조 (Coverage와 대칭)
    _write_label_or_mark(ws, labels.get("test_engineer", "Test Engineer"),
                         meta.test_engineer,
                         "테스트 엔지니어 이름", out_warnings)
    _write_label(ws, labels.get("target_coverage", "Target Coverage"),
                 meta.target_coverage, out_warnings)
    # deep-reviewer X7: 0/N의 silent wrong-pick 회피 — N=0이면 "N/A" 명시.
    # 24차: agg.total == 0 → N/A는 input 데이터 부재 의미, 노란 강조로 reviewer 가시화.
    if agg["total"] > 0:
        _write_label(ws, labels.get("actual_coverage", "Actual Coverage"),
                     agg["tested"] / agg["total"], out_warnings)
    else:
        _write_label_or_mark(ws, labels.get("actual_coverage", "Actual Coverage"), "",
                             "VectorCAST 데이터 부재 — log_folder 재확인", out_warnings)
    _write_label(ws, labels.get("target_pass_ratio", "Target Pass ratio"),
                 meta.target_pass_ratio, out_warnings)
    if agg["tested"] > 0:
        _write_label(ws, labels.get("actual_pass_ratio", "Actual Pass ratio"),
                     agg["passed"] / agg["tested"], out_warnings)
    else:
        _write_label_or_mark(ws, labels.get("actual_pass_ratio", "Actual Pass ratio"), "",
                             "실행된 TC 없음 — log 또는 deviation 확인", out_warnings)
    _write_label(ws, labels.get("final_test_result", "Final Test Result"),
                 meta.final_test_result, out_warnings)

    # 55-fix-3 W10: helper 추출 — swut_coverage와 단일 source. inline 중복 제거.
    from backend.services.swut_coverage_aggregator import (
        _write_v202_requirements_row,
        _write_v202_tc_stats_row,
    )
    _write_v202_tc_stats_row(
        ws, agg, layout, summary, out_warnings, total_key="total",
    )
    _write_v202_requirements_row(ws, layout, summary, out_warnings)


def _deviation_case_fields(case: Any) -> tuple[str, str, str, str] | None:
    """case → (tc_id, tc_no, issue_text, auto_rationale).

    deep-reviewer W6/X7: dict/DeviationCase 외 shape는 명시적 거부.
    5차 H3 Critical: issue_text/auto_rationale은 xlsx 셀 한도 방어용 truncate.
    """
    if isinstance(case, dict):
        tc_id_v = str(case.get("tc_id", "") or "")
        tc_no_v = str(case.get("tc_no", "") or "")
        if not tc_id_v:
            return None
        issue, _ = truncate_cell_text(case.get("issue_text", ""))
        rationale, _ = truncate_cell_text(case.get("auto_rationale", ""))
        return (tc_id_v, tc_no_v, issue, rationale)
    tc_id = getattr(case, "tc_id", None)
    if not tc_id:
        return None
    issue, _ = truncate_cell_text(getattr(case, "issue_text", ""))
    rationale, _ = truncate_cell_text(getattr(case, "auto_rationale", ""))
    return (str(tc_id), str(getattr(case, "tc_no", "") or ""), issue, rationale)


def _write_deviation(ws, deviation_cases: list[Any], out_warnings: list[str] | None = None) -> int:
    """Deviation 시트 — swut_deviation_generator 결과 기록.

    Returns: 쓰여진 행 수.
    """
    if not deviation_cases:
        return 0
    pos = find_kv_row(ws, "Test Case ID", max_row=10)
    if pos is None:
        if out_warnings is not None:
            out_warnings.append("Deviation 시트 'Test Case ID' 헤더 미발견 — skip")
        return 0
    start_row = pos[0] + 1
    written = 0
    skipped = 0
    for case in deviation_cases:
        fields = _deviation_case_fields(case)
        if fields is None:
            skipped += 1
            continue
        tc_id_v, tc_no_v, issue, rationale = fields
        tc_label = f"{tc_id_v} ({tc_no_v})" if tc_no_v else tc_id_v
        r = start_row + written
        safe_write(ws, r, pos[1], tc_label)
        safe_write(ws, r, pos[1] + 1, issue)
        safe_write(ws, r, pos[1] + 2, rationale)
        safe_write(ws, r, pos[1] + 3, "Auto-Generated")
        written += 1
    if skipped and out_warnings is not None:
        out_warnings.append(
            f"Deviation case shape 검증 실패 — {skipped}건 skip (dict 또는 DeviationCase 필요)"
        )
    return written


def _write_test_log(
    ws,
    session: SwUTSession,
    function_asil_map: dict[str, str] | None = None,
    out_warnings: list[str] | None = None,
    *,
    layout: Any = None,
) -> int:
    """Test Log 시트 — TC별 input/expected/actual/pass.

    회사 표준 layout (TC ID / Title / Method / Unit / Total + pass/fail) 단순화:
    각 환경 / 각 TC 단위 한 행씩.

    31차 W27: col+4 Function ID + col+5 ASIL 컬럼 추가 (function_asil_map 제공 시).
    회사 양식 col+3까지만 사용 — col+4/5는 빈 영역 활용. ASIL D row는
    mark_asil_d_function 적용 (audit 검토 우선순위 시각).
    """
    if not ws:
        return 0
    # 헤더 찾기
    pos = find_kv_row(ws, "Test Case ID", max_row=10)
    if pos is None:
        pos = find_kv_row(ws, "TC ID", max_row=10)
    if pos is None:
        return 0
    start_row = pos[0] + 1
    col = pos[1]
    asil_map = function_asil_map or {}

    # 31차 W27 reviewer W3 + 31-fix D10: col+4/5 빈 영역 가정 검증.
    # 헤더 row의 col+4/5 셀이 비어있는지 확인 — 회사 v3.01 양식 업그레이드 시
    # 데이터 덮어쓰기 위험 가시화. logger.warning은 backend 로그 전용 → 사용자
    # UI에 표시 안 됨. out_warnings에도 누적해서 X-SwUT-Warnings 헤더 통해
    # frontend "Warnings" 패널에 노출.
    header_col4 = ws.cell(pos[0], col + 4).value
    header_col5 = ws.cell(pos[0], col + 5).value
    if header_col4 or header_col5:
        msg = (
            f"SUTR Test Log col+4/5 not empty (col+4={header_col4!r}, "
            f"col+5={header_col5!r}) — 회사 양식 업그레이드 가능성, ASIL "
            "컬럼 덮어쓰기 진행. audit reviewer 확인 권장"
        )
        import logging
        logging.getLogger(__name__).warning(msg)
        if out_warnings is not None:
            out_warnings.append(msg)

    # 57차 T314 — Coverage Traceability와 동일 TC source 사용 (환경 union → unique TC).
    # 환경별 iterate 대신 1941 unique TC name을 한 번에 stamp + 회사 v2.02 양식의
    # 1 TC당 6 row step 자동 적용. SITR도 동일 함수 import로 동시 효과.
    from backend.services.swut_coverage_aggregator import _collect_tc_to_function
    tc_to_fn_id = _collect_tc_to_function(session)  # {tc_name: fn_id}

    # tc_name → 첫 매칭 env (component_name + test_results 조회용).
    # 환경별 동일 TC가 중복 정의되면 첫 환경 우선 (Coverage source semantic 일치).
    tc_to_env: dict[str, Any] = {}
    for env in session.environments:
        for tc_name in env.test_cases:
            if tc_name not in tc_to_env:
                tc_to_env[tc_name] = env

    tc_row_step = (
        getattr(layout, "test_log_tc_row_step", 1) if layout is not None else 1
    )

    written = 0
    for tc_name in sorted(tc_to_fn_id.keys()):
        r = start_row + (written * tc_row_step)
        env = tc_to_env.get(tc_name)
        component_name = env.component_name if env is not None else ""
        exec_r = env.test_results.get(tc_name) if env is not None else None
        safe_write(ws, r, col, tc_name)
        safe_write(ws, r, col + 1, component_name)
        safe_write(ws, r, col + 2, "AEC, ABV")
        safe_write(
            ws, r, col + 3,
            "Pass" if exec_r and exec_r.passed else "Fail" if exec_r else "N/A",
        )

        # 31차 W27: TC name에서 SwUFn_NNNN 추출 → Function ID + ASIL 컬럼.
        # T314: tc_to_fn_id에 이미 추출돼 있어 dict lookup 사용 (regex 중복 제거).
        fn_id = tc_to_fn_id.get(tc_name, "")
        asil = asil_map.get(fn_id, "") if fn_id else ""
        safe_write(ws, r, col + 4, fn_id)
        safe_write(ws, r, col + 5, f"ASIL {asil}" if asil else "")
        # ASIL B/C/D 시각 강조 — 30차 W21 + 31차 W29 정책.
        _asil_marker = {
            "B": mark_asil_b_function,
            "C": mark_asil_c_function,
            "D": mark_asil_d_function,
        }.get(asil)
        if _asil_marker:
            _asil_marker(ws, r, col + 5)

        # 54차 T283 + 54-fix W4: v2.02 양식 AL column marker.
        # exec_r 없음 → "" (미실행). exec_r.passed=True → "✓".
        # exec_r.passed=False → "✗". exec_r.passed=None (결과 unset) → "—"
        # (silent wrong-pick 방지 — Fail로 표기 안 함).
        if layout is not None and layout.test_log_extra_marker_col is not None:
            al_col = layout.test_log_extra_marker_col
            marker = ""
            if exec_r is not None:
                if exec_r.passed is True:
                    marker = "✓"
                elif exec_r.passed is False:
                    marker = "✗"
                else:
                    marker = "—"  # passed=None unset case
            safe_write(ws, r, al_col, marker)

        written += 1
    return written


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_sutr(
    session: SwUTSession,
    meta: SutrBuildMeta,
    template_bytes: bytes,
    deviation_cases: list[Any] | None = None,
    swuds_function_ids: set[str] | None = None,
) -> SutrBuildResult:
    """SUTR v3.01 xlsm 생성.

    Args:
        session: input_adapter 출력.
        meta: 빌드 메타.
        template_bytes: 기존 v3.01 xlsm 파일 bytes.
        deviation_cases: swut_deviation_generator 결과 (None이면 빈 Deviation 시트).
        swuds_function_ids: 17차 — SwUDS 함수 ID set (옵션). 제공되면 2.Consistency에
            SwUDS↔SwUTS 매핑 row 추가. Coverage builder와 대칭.
    """
    if openpyxl is None:
        raise RuntimeError("openpyxl is required for SwUT SUTR builder")

    # deep-reviewer X3 + 5차 H1/H2: 입력 메타 종합 검증.
    validate_build_meta(
        meta.release_sw_version, meta.test_date,
        doc_id_sequence=meta.doc_id_sequence,
        test_engineer=meta.test_engineer,
        author=meta.default_author,
        approver=meta.default_approver or meta.approver_override,
        reviewer=meta.default_reviewer or meta.reviewer_override,
    )
    # Critical (reviewer S): ZIP bomb / magic byte 검증.
    validate_xlsx_template_bytes(template_bytes, label="SUTR template")

    # 5차 L1 (ISO F3 추적성): 입력 template hash — audit 시 입력 동일성 검증용.
    template_sha256_12 = hashlib.sha256(template_bytes).hexdigest()[:12]

    # 37차 fix → 38차 W1 DRY: extract_warnings_from_session helper로 추출.
    warnings: list[str] = extract_warnings_from_session(session)

    # 54-fix C1: SwUT 라우터에 v2.02 template 잘못 입력 시 silent 빈 셀 차단.
    # v3.01 SUTR 양식은 fallback_to_v301=True로 hardcode 동작과 동등.
    from backend.services.excel_layout_resolver import inspect_swit_layout
    layout = inspect_swit_layout(template_bytes, "sitr")
    if layout.warnings:
        warnings.extend([f"[layout] {w}" for w in layout.warnings])

    # deep-reviewer W2: VBA 매크로 ZIP entry 존재 여부 사전 측정.
    template_has_vba = has_vba_macros(template_bytes)
    vba_refs_found: list[str] = []
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

    # 30차 W21 + 31차 W29: ASIL 분포 — Coverage builder와 동일 키 (대칭).
    from backend.services.swut_coverage_aggregator import _compute_asil_distribution
    asil_distribution, ids_by_asil = _compute_asil_distribution(
        agg.get("function_rows") or [],
        agg.get("function_asil_map") or {},
    )

    summary = {
        "environments": len(session.environments),
        "total": agg["total"],
        "tested": agg["tested"],
        "passed": agg["passed"],
        "failed": agg["failed"],
        "deviation_cases_written": 0,
        "test_log_rows_written": 0,
        # 30차 W21 + 31차 W29: Coverage builder와 동일 키 — UI 노출 통일.
        "asil_distribution": asil_distribution,
        "asil_b_function_ids": ids_by_asil.get("B", []),
        "asil_c_function_ids": ids_by_asil.get("C", []),
        "asil_d_function_ids": ids_by_asil.get("D", []),
        # 31-fix D15: audit 공지 메타 — Coverage builder와 대칭.
        "asil_highlight_policy": (
            "B=파랑(#E2F0FF) / C=주황(#FFE5CC) / D=빨강(#FFC7CE) — "
            "31차 비표준 audit 확장 (회사 v3.01 양식은 빨강만 사용)"
        ),
    }

    cover_ws = next((wb[n] for n in sheet_names if n.lower() == "cover"), None)
    if cover_ws is None:
        warnings.append("Cover 시트 미발견")
    else:
        # 54-fix C1: layout 전달
        _write_cover(cover_ws, meta, out_warnings=warnings, layout=layout)

    # 54-fix C1: 53차 SwIT 패턴과 대칭 — v2.02 "1.Test Summary" 등 prefix 호환 substring.
    ts_ws = next((wb[n] for n in sheet_names if "test summary" in n.lower()), None)
    if ts_ws is None:
        warnings.append("Test Summary 시트 미발견")
    else:
        # 54-fix C1: layout + summary 전달
        _write_test_summary(
            ts_ws, meta, agg, out_warnings=warnings,
            layout=layout, summary=summary,
        )

    # 54-fix C1: substring 대칭
    dev_ws = next((wb[n] for n in sheet_names if "deviation" in n.lower()), None)
    if dev_ws is None:
        warnings.append("Deviation 시트 미발견")
    elif deviation_cases:
        n = _write_deviation(dev_ws, deviation_cases, out_warnings=warnings)
        summary["deviation_cases_written"] = n

    # 54-fix C1: substring 대칭
    log_ws = next((wb[n] for n in sheet_names if "test log" in n.lower()), None)
    if log_ws is None:
        warnings.append("Test Log 시트 미발견")
    else:
        # 54-fix C1: layout 전달 — AL marker
        n = _write_test_log(
            log_ws, session,
            function_asil_map=agg.get("function_asil_map"),
            out_warnings=warnings,
            layout=layout,
        )
        summary["test_log_rows_written"] = n

    incomplete_sheets: list[str] = []
    # History — 55-fix: 사용자 결정 B (single-row release entry).
    hist_ws = next((wb[n] for n in sheet_names if n.lower() == "history"), None)
    if hist_ws is not None:
        from backend.services.swut_coverage_aggregator import _write_history_sheet
        # 55-fix-2 W2: SwUT prefix 명시 (vs SwIT SITR)
        # 55-fix-2 W6: out_warnings 전달
        release_rows = build_release_history_row(
            meta, doc_kind="SwUT SUTR", out_warnings=warnings,
        )
        n_h = _write_history_sheet(hist_ws, release_rows, out_warnings=warnings)
        summary["history_rows_written"] = n_h
        if n_h == 0:
            incomplete_sheets.append("History")

    # 17차 T171: 2.Consistency 시트 — Coverage builder와 대칭.
    # SUTR 템플릿에 시트가 없으면 silent skip (Hyundai 양식 변형 안전).
    cons_ws = next((wb[n] for n in sheet_names if "consistency" in n.lower()), None)
    if cons_ws is not None:
        from backend.services.swut_coverage_aggregator import _write_consistency_sheet
        n_cons = _write_consistency_sheet(
            cons_ws, session,
            swuds_function_ids=swuds_function_ids,
            out_warnings=warnings,
        )
        summary["consistency_self_check_rows"] = n_cons
        if swuds_function_ids is not None:
            summary["consistency_swuds_compared"] = True
        else:
            summary["consistency_swuds_compared"] = False
            incomplete_sheets.append("2.Consistency (SwUDS 비교 partial — v3.02)")

    # 14차 W1: BytesIO 그대로 result에 저장 — getvalue() copy 회피.
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    wb.close()

    filename = (
        f"({meta.project_id}_SUTR) Software Unit Test Result_"
        f"v{meta.release_sw_version}_{short_date(meta.test_date)}_R.xlsm"
    )

    summary["template_sha256_12"] = template_sha256_12
    summary["build_timestamp"] = meta.build_timestamp
    return SutrBuildResult(
        ok=True,
        xlsm_io=out,
        filename=filename,
        warnings=warnings,
        incomplete_sheets=incomplete_sheets,
        vba_macros_preserved=template_has_vba,
        summary=summary,
    )


# `short_date`는 excel_template_utils에서 import — 모듈 하단 중복 정의 제거 (deep-reviewer C1).


# 38차 W2 — public API 명시. SwIT SITR aggregator가 본 모듈의 _write_cover /
# _write_test_summary / _write_deviation / _write_test_log private 함수들을 직접
# import 중 (35차 SwIT 라운드 강결합 보류). 본 __all__로 강결합 경계를 명시화:
# signature 변경 시 SwIT 회귀(test_swit_sitr_aggregator.py) 동시 검증 의무.
__all__ = [
    # Public API
    "SutrBuildMeta",
    "SutrBuildResult",
    "build_sutr",
    # Private 함수 — SwIT SITR이 import 중. 명시로 강결합 가시화.
    "_write_cover",
    "_write_deviation",
    "_write_test_log",
    "_write_test_summary",
]
