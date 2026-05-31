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
    mark_asil_a_function,
    mark_asil_b_function,
    mark_asil_c_function,
    mark_asil_d_function,
    mark_asil_qm_function,
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

_OPTIONAL_LABELS = {
    "Build Timestamp", "Reviewer", "Doc. ID",
    # 라운드 F7 D11 fix: 회사 표준 양식 (★개발템플릿 V3) Cover에 부재 — 1.Test
    # Summary로 이동 완료. silent OK (warning emit X).
    "Project", "ASIL Level", "Validation Date", "Status", "Version",
}


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

    라운드 F7 T707: clear policy — deviation_cases 빈 list 또는 신규 stamp 후
    양식 default deviation 데이터 clear (Appendix sentinel 보존).

    Returns: 쓰여진 행 수.
    """
    pos = find_kv_row(ws, "Test Case ID", max_row=10)
    if pos is None:
        if out_warnings is not None:
            out_warnings.append("Deviation 시트 'Test Case ID' 헤더 미발견 — skip")
        return 0
    start_row = pos[0] + 1
    written = 0
    skipped = 0
    for case in deviation_cases or []:
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

    # 라운드 F7 T707: clear policy — 신규 stamp 후 다음 row부터 양식 default clear.
    # 'Appendix' sentinel ('■ Appendix' 등)을 만나면 그 직전까지만 clear. 양식의
    # 기존 deviation 4건 default (다른 release 데이터)가 신규 빌드에 보존되는
    # partial overwrite 결함 차단.
    try:
        from backend.services.excel_template_utils import clear_data_range
        clear_start = start_row + written
        clear_end = ws.max_row
        # Appendix sentinel 위치 탐지 — 그 직전까지 clear
        appendix_row = None
        for r in range(clear_start, min(clear_end + 1, clear_start + 100)):
            cell_value = ws.cell(r, 2).value
            if isinstance(cell_value, str) and "Appendix" in cell_value:
                appendix_row = r
                break
        actual_end = (appendix_row - 1) if appendix_row else min(clear_end, clear_start + 50)
        if actual_end >= clear_start:
            cleared = clear_data_range(
                ws,
                start_row=clear_start, end_row=actual_end,
                start_col=pos[1], end_col=pos[1] + 4,
                preserve_formula=True, preserve_merged_anchor=True,
            )
            if out_warnings is not None and cleared > 0:
                out_warnings.append(
                    f"[clear] Deviation row {clear_start}~{actual_end} 양식 default "
                    f"{cleared} cell clear (partial overwrite 차단)"
                )
    except ImportError:
        pass
    return written


def _write_variable_name_header_row(
    ws,
    layout: Any,
    session: SwUTSession,
    *,
    input_col: int,
    expected_col: int,
    actual_col: int,
    input_max: int,
    expected_max: int,
    actual_max: int,
    out_warnings: list[str] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """59차 F4-A — Test Log 변수명 헤더 row stamp + 환경 합집합 sorted list 반환.

    KJPDS02 v1.01 양식은 row 5 col 10~ 에 변수명 (예: u16g_SysDiag_SystemStatus)
    stamp 후 row 6~ 에 값. 우리 추출은 환경별 dict[변수명, 값] 보유 — env가 여러
    개일 때 같은 변수가 일부 env에만 있을 수 있어 **전체 환경 합집합 + sorted**
    를 헤더로 stamp하고 TC stamp는 그 col 순서대로 lookup.

    Args:
        ws: openpyxl worksheet.
        layout: SwitLayout — test_log_variable_header_row None이면 skip.
        session: SwUTSession — environments 순회.
        input_col / expected_col / actual_col: column 시작 위치.
        input_max / expected_max / actual_max: block 최대 stamp 수.
        out_warnings: diag 누적용.

    Returns:
        (input_var_names, expected_var_names, actual_var_names) — sorted union list,
        max_count 적용 후. empty 3-tuple이면 backward-compat (caller가 dict.values()
        순서 사용).
    """
    if layout is None or getattr(layout, "test_log_variable_header_row", None) is None:
        return [], [], []

    header_row = layout.test_log_variable_header_row

    input_keys: set[str] = set()
    expected_keys: set[str] = set()
    actual_keys: set[str] = set()

    for env in session.environments:
        # TestCaseItem.input_data / expected_result 추출 — env.test_cases는
        # dict[str, List[TestCaseItem]] (TCBank.test_cases carry forward 패턴).
        for tc_items in env.test_cases.values():
            items = tc_items if isinstance(tc_items, list) else [tc_items]
            for tc_item in items:
                input_keys.update(getattr(tc_item, "input_data", {}) or {})
                expected_keys.update(getattr(tc_item, "expected_result", {}) or {})
        # ExecutionRow.actual_result (58차 F1 BeautifulSoup 추출) 우선
        for exec_r in env.test_results.values():
            actual_keys.update(getattr(exec_r, "actual_result", {}) or {})
        # TestResultItem.actual_result (vcast_parser TestResultItem) fallback
        for tr_items in getattr(env, "tc_result_items", {}).values():
            items = tr_items if isinstance(tr_items, list) else [tr_items]
            for tr_item in items:
                actual_keys.update(getattr(tr_item, "actual_result", {}) or {})

    input_list = sorted(input_keys)[: max(0, input_max)]
    expected_list = sorted(expected_keys)[: max(0, expected_max)]
    actual_list = sorted(actual_keys)[: max(0, actual_max)]

    for i, name in enumerate(input_list):
        safe_write(ws, header_row, input_col + i, name)
    for i, name in enumerate(expected_list):
        safe_write(ws, header_row, expected_col + i, name)
    for i, name in enumerate(actual_list):
        safe_write(ws, header_row, actual_col + i, name)

    if out_warnings is not None:
        msg = (
            f"F4-A: 변수명 헤더 row {header_row} stamp — "
            f"input/expected/actual = "
            f"{len(input_list)}/{len(expected_list)}/{len(actual_list)} variables "
            f"(union sorted, max {input_max}/{expected_max}/{actual_max})"
        )
        out_warnings.append(f"[diag] {msg}")

    return input_list, expected_list, actual_list


def _build_fn_id_to_component_map(session: SwUTSession) -> dict[str, str]:
    """라운드 80 T1407: 세션 단위 fn_id → component_name 캐시.

    환경별 function_coverage iterate 1회로 ``SwUFn_NNNN`` → ``SwCom_NN`` (또는
    별칭) 매핑 dict 구축. SDS 컴포넌트 ASIL fallback에서 사용.

    component_name 값에 ``"SwCom_01\\n(System OS)"`` 같은 multi-line 양식 가능 —
    첫 줄 (SwCom_NN 부분) 우선, 다음 줄 (별칭) 둘 다 등록.
    """
    cache: dict[str, str] = {}
    for env in session.environments:
        for fc in env.function_coverage:
            fn_id = getattr(fc, "unit_id", "") or getattr(fc, "function_id", "")
            comp_raw = getattr(fc, "component_name", "") or ""
            if not fn_id or not comp_raw:
                continue
            # SwUFn_NNNN 부분 추출
            import re as _re_fn
            m = _re_fn.search(r"SwUFn_\d+", fn_id)
            if m:
                cache.setdefault(m.group(0), comp_raw)
    return cache


def _resolve_component_asil(
    fn_id: str,
    fn_to_comp: dict[str, str],
    sds_map: dict[str, str],
) -> str:
    """라운드 80 T1407: fn_id → component_name → SDS ASIL lookup.

    component_name 양식이 ``"SwCom_01\\n(System OS)"`` 다양 — 후보 키 여러 개
    시도 (SwCom_NN / strip / 별칭). 매칭 0 시 빈 string.
    """
    if not fn_id or not sds_map:
        return ""
    comp_raw = fn_to_comp.get(fn_id, "")
    if not comp_raw:
        return ""
    # 후보 키들 — SwCom_NN, 첫 줄, 전체 strip
    import re as _re_cn
    candidates = []
    m_swcom = _re_cn.search(r"SwCom_\d+", comp_raw)
    if m_swcom:
        candidates.append(m_swcom.group(0))
    for line in comp_raw.splitlines():
        stripped = line.strip().strip("()").strip()
        if stripped and stripped not in candidates:
            candidates.append(stripped)
    candidates.append(comp_raw.strip())
    for k in candidates:
        if k in sds_map:
            return sds_map[k]
    return ""


def _write_test_log(
    ws,
    session: SwUTSession,
    function_asil_map: dict[str, str] | None = None,
    out_warnings: list[str] | None = None,
    *,
    layout: Any = None,
    swuts_map: dict[str, Any] | None = None,
    c_function_map: dict[str, dict[str, Any]] | None = None,
) -> int:
    """Test Log 시트 — TC별 input/expected/actual/pass.

    회사 표준 layout (TC ID / Title / Method / Unit / Total + pass/fail) 단순화:
    각 환경 / 각 TC 단위 한 행씩.

    31차 W27: col+4 Function ID + col+5 ASIL 컬럼 추가 (function_asil_map 제공 시).
    회사 양식 col+3까지만 사용 — col+4/5는 빈 영역 활용. ASIL D row는
    mark_asil_d_function 적용 (audit 검토 우선순위 시각).

    60차 F6-A: swuts_map 제공 시 (SwUTS xlsm parser 결과) col B/C/D + Precondition
    col에 spec docx 데이터 stamp. 매핑 fallback chain — 직접 tc_name 매칭 →
    function_id (SwUFn_NNNN) 매칭 → 없으면 기존 하드코딩 ("AEC, ABV").
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

    # 라운드 80 T1407: 세션 단위 fn_id → component_name cache (SDS ASIL fallback용).
    _fn_to_comp_cache = _build_fn_id_to_component_map(session)

    # tc_name → 첫 매칭 env (component_name + test_results 조회용).
    # 환경별 동일 TC가 중복 정의되면 첫 환경 우선 (Coverage source semantic 일치).
    tc_to_env: dict[str, Any] = {}
    total_tcs_in_envs = 0
    for env in session.environments:
        for tc_name in env.test_cases:
            total_tcs_in_envs += 1
            if tc_name not in tc_to_env:
                tc_to_env[tc_name] = env

    tc_row_step = (
        getattr(layout, "test_log_tc_row_step", 1) if layout is not None else 1
    )

    # 57차 T314 diag: 진단용 — backend log 및 out_warnings에 데이터 흐름 출력
    diag_msg = (
        f"SUTR _write_test_log diag: environments={len(session.environments)}, "
        f"total_tcs_in_envs={total_tcs_in_envs}, "
        f"tc_to_fn_id_size={len(tc_to_fn_id)}, "
        f"tc_row_step={tc_row_step}, start_row={start_row}, col={col}"
    )
    import logging as _logging
    _logging.getLogger(__name__).info(diag_msg)
    if out_warnings is not None:
        out_warnings.append(f"[diag] {diag_msg}")

    # 57차 T319 fix — Template block (row 5~base+row_step*template_count) 의
    # merge pattern + style 추출 → 새 TC block (template 영역 밖)에 동일 확장.
    # 회사 v2.02 SUTR 양식: 6 TC × 6 row × 38 col merge/style pattern.
    # audit reviewer가 일관 양식으로 산출물 검토.
    import copy as _copy
    template_block_count = 6  # 회사 양식 표준 default 6 TC blocks
    template_merges_local: list[tuple[int, int, int, int]] = []
    for _mc in list(ws.merged_cells.ranges):
        if (start_row <= _mc.min_row <= start_row + tc_row_step - 1 and
                _mc.max_row <= start_row + tc_row_step - 1):
            # template block 1번 내부 merge — offset 0 row 시작
            template_merges_local.append(
                (_mc.min_row - start_row, _mc.max_row - start_row,
                 _mc.min_col, _mc.max_col)
            )

    # 58차 F3 — column 매핑 layout-aware (layout 제공 시 동적, None이면 v3.01 hardcode):
    #   회사 v3.01 SUTR (SwUT): F=Input, P=Expected, Z=Actual, AJ=Pass/Fail Unit,
    #       AK=Pass/Fail Total, AL=Log Data
    #   회사 v2.02 SITR (SwIT): H=Input, R=Expected, AB=Actual, AL=Pass/Fail,
    #       AN=Log Data (Pass/Fail Total 없음)
    # SwitLayout.test_log_input_col 등 6 field 우선 사용 → None이면 v3.01 hardcode.
    # 57차 T319 fix: 이전 col+3/+4/+5 잘못 stamp 정정 후 hardcode 36/37/38.
    # layout이 6개 column 중 1개라도 보유하면 layout-aware (v2.02). 모두 None이면 v3.01 hardcode.
    _layout_has_col = layout is not None and any(
        getattr(layout, attr, None)
        for attr in (
            "test_log_input_col", "test_log_expected_col", "test_log_actual_col",
            "test_log_pass_fail_col", "test_log_log_data_col",
        )
    )
    if _layout_has_col:
        # v3.01 hardcode default을 fallback으로 사용 (각 col이 None이면 적용).
        INPUT_COL = layout.test_log_input_col or 6
        EXPECTED_COL = layout.test_log_expected_col or 16
        ACTUAL_COL = layout.test_log_actual_col or 26
        PASS_FAIL_UNIT_COL = layout.test_log_pass_fail_col or 36
        PASS_FAIL_TOTAL_COL = layout.test_log_pass_fail_total_col or 0  # 0 = skip stamp
        LOG_DATA_COL = layout.test_log_log_data_col or 38
    else:
        # v3.01 backward-compat hardcode (SwUT SUTR 양식)
        INPUT_COL = 6     # F
        EXPECTED_COL = 16  # P
        ACTUAL_COL = 26    # Z
        PASS_FAIL_UNIT_COL = 36   # AJ
        PASS_FAIL_TOTAL_COL = 37  # AK
        LOG_DATA_COL = 38         # AL

    # 59차 F4-A — block max counts (layout 기반 동적). layout None backward-compat 10.
    input_max = (
        getattr(layout, "test_log_input_max_count", 10) if layout is not None else 10
    )
    expected_max = (
        getattr(layout, "test_log_expected_max_count", 10) if layout is not None else 10
    )
    actual_max = (
        getattr(layout, "test_log_actual_max_count", 10) if layout is not None else 10
    )

    # 59차 F4-A — 변수명 헤더 row stamp + 환경 합집합 sorted list 산출.
    # KJPDS02 v1.01 양식: row 5에 변수명 stamp 후 TC 값은 col 순서대로 lookup.
    # layout.test_log_variable_header_row None이면 빈 list 반환 (v2.02/v3.01 동작).
    input_var_list, expected_var_list, actual_var_list = _write_variable_name_header_row(
        ws,
        layout,
        session,
        input_col=INPUT_COL,
        expected_col=EXPECTED_COL,
        actual_col=ACTUAL_COL,
        input_max=input_max,
        expected_max=expected_max,
        actual_max=actual_max,
        out_warnings=out_warnings,
    )

    # 라운드 73 T806 — SwIT Test Log row 자동 확장. SwIT SITR v2.02 양식 max_row=31
    # 인데 12 TC × 6 step = 72 row 필요 → 4 TC만 stamp되던 결함. SwUT SUTR도 5000+ TC
    # 미래에 대비.
    sorted_tc_names = sorted(tc_to_fn_id.keys())
    if sorted_tc_names:
        needed_last_row = start_row + (len(sorted_tc_names) - 1) * tc_row_step + (tc_row_step - 1)
        if needed_last_row > ws.max_row:
            try:
                from backend.services.excel_template_utils import (
                    auto_expand_row_block, push_sentinel_to_last_row,
                )
                shortage = needed_last_row - ws.max_row
                # template block 1번 (start_row ~ start_row + tc_row_step - 1) 다음에 row 확장.
                inserted = auto_expand_row_block(
                    ws,
                    insert_at_row=start_row + tc_row_step,
                    amount=shortage,
                    template_row_idx=start_row,
                    copy_style=True, copy_merge=True, copy_dimension=True,
                )
                push_sentinel_to_last_row(ws)
                if inserted < shortage and out_warnings is not None:
                    out_warnings.append(
                        f"[row_expand] Test Log row 부족 ({shortage}개 필요, "
                        f"{inserted}개 확장) — stamp 일부 누락 가능"
                    )
            except ImportError:
                pass

    written = 0
    for tc_name in sorted_tc_names:
        r = start_row + (written * tc_row_step)
        env = tc_to_env.get(tc_name)
        component_name = env.component_name if env is not None else ""
        exec_r = env.test_results.get(tc_name) if env is not None else None
        result_str = (
            "Pass" if exec_r and exec_r.passed else
            "Fail" if exec_r else
            "N/A"
        )

        # 60차 F6-A — SwUTS spec lookup (fallback chain).
        # 1순위: tc_name 직접 매칭 (예: 'SwUTC_0121' 또는 'SwUFn_0121')
        # 2순위: tc_name에서 SwUFn_NNNN 추출 → by_function_id 첫 entry
        # 3순위: 없음 → 기존 하드코딩 fallback
        # F6 자체평가 Round 1 C1 (re-fix): SwIT TC name 'SwITC_SwUFn_0121.001' 호환
        # — re.match (^anchor) → re.search. 34차 deep-reviewer C1과 동일 회귀.
        swuts_entry = None
        if swuts_map:
            swuts_entry = swuts_map.get(tc_name)
            if swuts_entry is None:
                # function_id fallback — VectorCAST 'SwUFn_0121.001' / spec 'SwUTC_0121'
                # 두 형식 모두 SwUFn_0121 substring 가짐. swuts_map은 by_tc_id 형식.
                # re.search로 SwUT 'SwUFn_0121.001' + SwIT 'SwITC_SwUFn_0121.001' 모두 매칭.
                _fn_match = re.search(r"SwUFn_(\d+)", tc_name)
                if _fn_match:
                    _fn_id = _fn_match.group(0)
                    # by_tc_id에서 ``SwUTC_<digits>`` 형식이 ``SwUFn_<digits>`` 와
                    # 1:1 대응되는 SwUTC 찾기 (KJPDS02 SwUTS 패턴)
                    _candidate_tc = f"SwUTC_{_fn_match.group(1)}"
                    swuts_entry = swuts_map.get(_candidate_tc)
                    if swuts_entry is None:
                        # HDPDM01 'SwUTC_SwUFn_NNNN' 형식 시도
                        swuts_entry = swuts_map.get(f"SwUTC_{_fn_id}")
                    if swuts_entry is None:
                        # SwIT spec key는 'SwITC_NNNN' (function_id 4자리 그대로) 형식
                        # 가능성 시도. KJPDS02 SwITS의 2자리 (`SwITC_NN`) 매핑은 본
                        # 시도로 매칭 안 됨 — by_function_id 기반 lookup이 필요한 케이스는
                        # 별도 라운드에서 처리 (Round 2 N1).
                        swuts_entry = swuts_map.get(f"SwITC_{_fn_match.group(1)}")

        # B/C/D — TC ID / Title / Method (SwUTS spec 우선, 없으면 기존 fallback)
        if swuts_entry is not None:
            _display_tc_id = getattr(swuts_entry, "tc_id", "") or tc_name
            _display_description = (
                getattr(swuts_entry, "description", "")
                or getattr(swuts_entry, "unit_name", "")
                or component_name
            )
            _method = getattr(swuts_entry, "test_method", "")
            _gen_method = getattr(swuts_entry, "generation_method", "")
            if _method and _gen_method:
                _display_method = f"{_method}, {_gen_method}"
            elif _method:
                _display_method = _method
            elif _gen_method:
                _display_method = _gen_method
            else:
                _display_method = "AEC, ABV"
            safe_write(ws, r, col, _display_tc_id)
            safe_write(ws, r, col + 1, _display_description)
            safe_write(ws, r, col + 2, _display_method)
            # Precondition stamp (layout 제공 시) — 회사 양식에 별도 col 존재할 때만.
            _precondition_col = (
                getattr(layout, "test_log_precondition_col", None)
                if layout is not None else None
            )
            _precondition = getattr(swuts_entry, "precondition", "")
            if _precondition_col and _precondition:
                safe_write(ws, r, _precondition_col, _precondition)
        else:
            # F8 N8 fix: VectorCAST 'SwITC_SwUFn_NNNN.NNN' → 회사 표준 'SwITC_NNNN'
            # 변환 (SwITCV 2.Traceability T705 stamp와 일관성). sub-index는 step row
            # C3에 1~5 stamp되므로 anchor row는 SwITC ID prefix만.
            # SwUT 형식 'SwUFn_NNNN.NNN' 또는 다른 prefix는 그대로 유지.
            _display_tc_id = tc_name
            _switc_fn = re.match(r"^SwITC_SwUFn_(\d+)", tc_name)
            if _switc_fn:
                _display_tc_id = f"SwITC_{_switc_fn.group(1)}"
            safe_write(ws, r, col, _display_tc_id)
            safe_write(ws, r, col + 1, component_name)
            safe_write(ws, r, col + 2, "AEC, ABV")
        # E (col 5) — TC ID row는 빈 cell (Pass/Fail 자리가 아님)
        # sub-row E6~E10에 Params 1~5 stamp (template default 패턴)
        if tc_row_step >= 2:
            for sub_i in range(1, tc_row_step):
                sub_r = r + sub_i
                if ws.cell(sub_r, 5).value is None:  # col 5 = E
                    safe_write(ws, sub_r, 5, sub_i)

        # 59차 F4-B — step 분배: input_data_steps 있으면 sub-row에 step별 input stamp.
        # layout.test_log_step_layout=='step_in_rows' (v2.02 6 row pattern) + tc_item에
        # input_data_steps 보유 시. HDPDM01 fixture는 input_data_steps 빈 list →
        # 기존 동작 (TC ID row에만 stamp). KJPDS02 v1.01 호환 인프라.
        _step_in_rows = (
            layout is not None
            and getattr(layout, "test_log_step_layout", "single_row") == "step_in_rows"
            and tc_row_step >= 2
        )

        # 57차 T319 fix → 59차 F4-A 일반화 — Input/Expected/Actual stamp.
        # VectorCAST TestCaseItem (vcast_parser.py:179) 에 input_data / expected_result
        # / actual_result dict 보유. env.test_cases[tc_name] = List[TestCaseItem] —
        # 첫 item 사용. F4-A: input_var_list (합집합 sorted) 있으면 그 col 순서 lookup,
        # 없으면 backward-compat dict.values()[:input_max].
        if env is not None:
            tc_items = env.test_cases.get(tc_name) or []
            tc_item = tc_items[0] if tc_items else None
            if tc_item is not None:
                input_data = getattr(tc_item, "input_data", {}) or {}
                expected_data = getattr(tc_item, "expected_result", {}) or {}
                # Input Params — col 순서 lookup 또는 dict.values()
                if input_var_list:
                    for pi, var_name in enumerate(input_var_list):
                        val = input_data.get(var_name, "")
                        safe_write(ws, r, INPUT_COL + pi, str(val) if val else "")
                else:
                    input_vals = list(input_data.values())[:input_max]
                    for pi, val in enumerate(input_vals):
                        safe_write(ws, r, INPUT_COL + pi, str(val) if val else "")
                # Expected Result Params
                if expected_var_list:
                    for pi, var_name in enumerate(expected_var_list):
                        val = expected_data.get(var_name, "")
                        safe_write(ws, r, EXPECTED_COL + pi, str(val) if val else "")
                else:
                    expected_vals = list(expected_data.values())[:expected_max]
                    for pi, val in enumerate(expected_vals):
                        safe_write(ws, r, EXPECTED_COL + pi, str(val) if val else "")
                # Actual Result Params
                # 58차 F1: ExecutionRow.actual_result 우선 (BeautifulSoup 추출),
                # 57차 T321 fallback: env.tc_result_items (vcast_parser TestResultItem).
                # actual_result: Dict[str, Tuple[str, str]] — (actual_val, expected_val) tuple.
                actual_dict: dict = {}
                exec_r2 = env.test_results.get(tc_name) if env is not None else None
                if exec_r2 is not None:
                    actual_dict = getattr(exec_r2, "actual_result", {}) or {}
                if not actual_dict:
                    tr_items = getattr(env, "tc_result_items", {}).get(tc_name, [])
                    tr_item = tr_items[0] if tr_items else None
                    if tr_item is not None:
                        actual_dict = getattr(tr_item, "actual_result", {}) or {}
                if actual_dict:
                    if actual_var_list:
                        for pi, var_name in enumerate(actual_var_list):
                            t = actual_dict.get(var_name, "")
                            val = (
                                t[0] if isinstance(t, tuple) and t
                                else (str(t) if t else "")
                            )
                            safe_write(ws, r, ACTUAL_COL + pi, str(val) if val else "")
                    else:
                        actual_vals = [
                            t[0] if isinstance(t, tuple) and t else (str(t) if t else "")
                            for t in list(actual_dict.values())[:actual_max]
                        ]
                        for pi, val in enumerate(actual_vals):
                            safe_write(ws, r, ACTUAL_COL + pi, str(val) if val else "")

                # 59차 F4-B — step 분배 stamp.
                # input_data_steps / expected_result_steps / actual_result_steps가
                # 채워져 있을 때 sub-row (step 2~N) 에 각 step의 input 값 stamp.
                # TC ID row (r) = step 1, sub_r = r + step_idx = step 1 + step_idx.
                # HDPDM01 fixture는 steps 빈 list → skip (backward-compat).
                if _step_in_rows:
                    input_steps = (
                        getattr(tc_item, "input_data_steps", []) or []
                    )
                    expected_steps = (
                        getattr(tc_item, "expected_result_steps", []) or []
                    )
                    actual_steps: list = []
                    if exec_r2 is not None:
                        actual_steps = (
                            getattr(exec_r2, "actual_result_steps", []) or []
                        )
                    # max iteration step count (각 list 길이 최댓값)
                    max_step_count = max(
                        len(input_steps), len(expected_steps), len(actual_steps),
                    )
                    for step_idx in range(1, min(tc_row_step, max_step_count)):
                        sub_r = r + step_idx
                        # input
                        if step_idx < len(input_steps):
                            sd = input_steps[step_idx]
                            if input_var_list:
                                for pi, var_name in enumerate(input_var_list):
                                    val = sd.get(var_name, "")
                                    safe_write(
                                        ws, sub_r, INPUT_COL + pi,
                                        str(val) if val else "",
                                    )
                            else:
                                vals = list(sd.values())[:input_max]
                                for pi, val in enumerate(vals):
                                    safe_write(
                                        ws, sub_r, INPUT_COL + pi,
                                        str(val) if val else "",
                                    )
                        # expected
                        if step_idx < len(expected_steps):
                            sd = expected_steps[step_idx]
                            if expected_var_list:
                                for pi, var_name in enumerate(expected_var_list):
                                    val = sd.get(var_name, "")
                                    safe_write(
                                        ws, sub_r, EXPECTED_COL + pi,
                                        str(val) if val else "",
                                    )
                            else:
                                vals = list(sd.values())[:expected_max]
                                for pi, val in enumerate(vals):
                                    safe_write(
                                        ws, sub_r, EXPECTED_COL + pi,
                                        str(val) if val else "",
                                    )
                        # actual (tuple — t[0] 사용)
                        if step_idx < len(actual_steps):
                            sd = actual_steps[step_idx]
                            if actual_var_list:
                                for pi, var_name in enumerate(actual_var_list):
                                    t = sd.get(var_name, "")
                                    val = (
                                        t[0] if isinstance(t, tuple) and t
                                        else (str(t) if t else "")
                                    )
                                    safe_write(
                                        ws, sub_r, ACTUAL_COL + pi,
                                        str(val) if val else "",
                                    )
                            else:
                                vals = [
                                    t[0] if isinstance(t, tuple) and t
                                    else (str(t) if t else "")
                                    for t in list(sd.values())[:actual_max]
                                ]
                                for pi, val in enumerate(vals):
                                    safe_write(
                                        ws, sub_r, ACTUAL_COL + pi,
                                        str(val) if val else "",
                                    )

        # Pass/Fail stamp — Unit (필수) + Total (v3.01만, v2.02는 PASS_FAIL_TOTAL_COL=0이라 skip).
        # F7 자체평가 R2 N1 fix: anchor row만 stamp가 양식 default 'Pass' 잔존
        # (step row R+1~R+step-1) → 'Fail' anchor인데 step rows 'Pass' 표시되어
        # audit reviewer false success. 모든 step row에 동일 result 동기 + log_path
        # 도 첫 row만, step row는 None clear (default 'Pass' 차단).
        safe_write(ws, r, PASS_FAIL_UNIT_COL, result_str)
        if PASS_FAIL_TOTAL_COL > 0:
            safe_write(ws, r, PASS_FAIL_TOTAL_COL, result_str)
        # step row Pass/Fail clear — 양식 default 'Pass' 잔존 차단 (N1)
        if tc_row_step > 1:
            for sub_offset in range(1, tc_row_step):
                sub_r = r + sub_offset
                if PASS_FAIL_UNIT_COL > 0:
                    safe_write(ws, sub_r, PASS_FAIL_UNIT_COL, None)
                if PASS_FAIL_TOTAL_COL > 0:
                    safe_write(ws, sub_r, PASS_FAIL_TOTAL_COL, None)

        # Log Data — VectorCAST log file path 추정.
        log_path = ""
        if env is not None and getattr(env, "env_name", ""):
            log_path = f"{env.env_name}/{tc_name}.log"
        safe_write(ws, r, LOG_DATA_COL, log_path)

        # 31차 W27: TC name에서 SwUFn_NNNN 추출 → ASIL 시각 강조 (AJ 컬럼)
        # 이전: col+5 (G=Param2) 잘못 강조. 현재: AJ row 시각 강조 (사용자 입력 영역 미침범).
        fn_id = tc_to_fn_id.get(tc_name, "")
        asil = asil_map.get(fn_id, "") if fn_id else ""
        # 라운드 78 T1302 — c_function_map.comment_asil fallback.
        # 라이브 v11/v12 측정: 1941 TC 중 ASIL 강조 0건 (asil_map 빈 dict).
        # swuts_map.unit_name이 시그너처 형식 (`'void main( void )'`)이라 c_function_map
        # key (함수명 `'main'`)와 직접 매칭 안 됨 → regex로 함수명 추출.
        if not asil and c_function_map and tc_name:
            # 1) swuts_map.unit_name 시그너처에서 함수명 추출
            _cand_name = ""
            if swuts_map:
                _swuts_entry = swuts_map.get(tc_name)
                if _swuts_entry is None:
                    import re as _re_t
                    _fm = _re_t.search(r"SwUFn_(\d+)", tc_name)
                    if _fm:
                        _swuts_entry = swuts_map.get(f"SwUTC_{_fm.group(1)}")
                if _swuts_entry:
                    _sig = getattr(_swuts_entry, "unit_name", "") or ""
                    # 시그너처 패턴: `[modifiers] return_type fn_name(args)`.
                    # 함수명 = `(` 직전 마지막 토큰. 예: 'static void s_SystemOperation( void )'
                    # → 's_SystemOperation'.
                    import re as _re_sig
                    _match = _re_sig.search(r"(\w+)\s*\(", _sig)
                    if _match:
                        _cand_name = _match.group(1)
                    else:
                        _cand_name = _sig.strip()
            # 2) cand_name으로 c_function_map lookup
            if _cand_name:
                _c_entry = c_function_map.get(_cand_name)
                if _c_entry:
                    _ca = (_c_entry.get("comment_asil") or "").strip().upper()
                    if _ca in {"A", "B", "C", "D", "QM"}:
                        asil = _ca

        # 라운드 80 T1407 — ISO 26262 추적성 체인 fallback chain.
        # 우선순위: c_source(위) → SUDS function 직접 → SDS component → SRS 보조.
        if not asil and fn_id:
            # 1) SUDS function ASIL (fn_id 직접 매칭 — 라이브 409건 검증)
            _suds_map = getattr(session, "function_asil_from_suds", {}) or {}
            _sasil = _suds_map.get(fn_id)
            if _sasil:
                asil = _sasil
        if not asil and fn_id:
            # 2) SDS component ASIL (fn_id → component_name → SwCom/별칭 lookup)
            _sds_map = getattr(session, "component_asil_from_sds", {}) or {}
            if _sds_map:
                _casil = _resolve_component_asil(fn_id, _fn_to_comp_cache, _sds_map)
                if _casil:
                    asil = _casil
        if not asil:
            # 3) SRS function ASIL 보조 (함수명 매칭)
            _srs_map = getattr(session, "function_asil_from_srs", {}) or {}
            _srs_key = ""
            if _srs_map:
                # _cand_name이 c_function_map fallback에서 추출됐으면 활용
                _srs_key = locals().get("_cand_name", "") or ""
                if not _srs_key and swuts_map:
                    _entry_x = swuts_map.get(tc_name)
                    if _entry_x:
                        _sig_x = getattr(_entry_x, "unit_name", "") or ""
                        import re as _re_srs
                        _m_srs = _re_srs.search(r"(\w+)\s*\(", _sig_x)
                        if _m_srs:
                            _srs_key = _m_srs.group(1)
                if _srs_key:
                    _rasil = _srs_map.get(_srs_key)
                    if _rasil:
                        asil = _rasil
        # 라운드 81 T1503: ASIL 5단계 그라데이션 — A/QM 추가 (audit reviewer 친화).
        _asil_marker = {
            "A": mark_asil_a_function,
            "B": mark_asil_b_function,
            "C": mark_asil_c_function,
            "D": mark_asil_d_function,
            "QM": mark_asil_qm_function,
        }.get(asil)
        if _asil_marker:
            _asil_marker(ws, r, PASS_FAIL_UNIT_COL)

        # 54차 T283 + 54-fix W4: v2.02 양식 AL column marker.
        # AL = Log Data column (38). exec_r markers (✓/✗/—)는 별도 col에 stamp.
        # AL과 충돌 시 skip.
        if layout is not None and layout.test_log_extra_marker_col is not None:
            al_col = layout.test_log_extra_marker_col
            if al_col != LOG_DATA_COL:  # AL과 충돌 회피
                marker = ""
                if exec_r is not None:
                    if exec_r.passed is True:
                        marker = "✓"
                    elif exec_r.passed is False:
                        marker = "✗"
                    else:
                        marker = "—"
                safe_write(ws, r, al_col, marker)

        # 57차 T319 fix — 새 TC block (template 영역 밖)은 template style + merge
        # 복사. 사용자 결정 — "빌드 속도는 좀 느려도 된다 정확하고 필요한 데이터는
        # 다 쓸수있게해야해". Style copy 1941 TC × 6 row × 38 col = ~440k cell ops
        # (~50초 추가), merge ~5800개 (~1초). audit 양식 일관성 100% 확보.
        block_idx = written
        if block_idx >= template_block_count and tc_row_step >= 2:
            max_col_n = ws.max_column or 38
            for offset in range(tc_row_step):
                src_row = start_row + offset
                dst_row = r + offset
                if dst_row == src_row:
                    continue
                for c_n in range(1, max_col_n + 1):
                    src_cell = ws.cell(src_row, c_n)
                    dst_cell = ws.cell(dst_row, c_n)
                    if src_cell.has_style:
                        dst_cell.font = _copy.copy(src_cell.font)
                        dst_cell.border = _copy.copy(src_cell.border)
                        dst_cell.fill = _copy.copy(src_cell.fill)
                        dst_cell.alignment = _copy.copy(src_cell.alignment)
                        dst_cell.number_format = src_cell.number_format
                        dst_cell.protection = _copy.copy(src_cell.protection)
            # Merge cells 적용 — template block의 local merge를 새 block 위치에 복사
            for off_start, off_end, mc_min_col, mc_max_col in template_merges_local:
                new_min_r = r + off_start
                new_max_r = r + off_end
                try:
                    ws.merge_cells(
                        start_row=new_min_r, end_row=new_max_r,
                        start_column=mc_min_col, end_column=mc_max_col,
                    )
                except (ValueError, AttributeError):
                    pass

        written += 1

    # 라운드 F7 T707: clear policy — 신규 stamp 후 다음 row부터 양식 default clear.
    # SwUTR/SwITR 회사 표준 양식이 R5/R7에 SwUTC_0101 default 데이터 보유 →
    # 신규 session TC 2건 stamp 후 R17~ default 보존되어 partial overwrite 결함.
    # clear_data_range로 stamp 끝 다음 row부터 ws.max_row까지 cell 비움.
    if written > 0:
        try:
            from backend.services.excel_template_utils import clear_data_range
            clear_start = start_row + (written * tc_row_step)
            clear_end = ws.max_row
            if clear_end >= clear_start:
                # F7 자체평가 R1 C1/C3 fix: col range 1~20 → 1~40 확장 (양식 default
                # 'Pass' 텍스트가 col 36/37에 prefill되어 잔존). sentinel_patterns로
                # '< End of Document >' / '■ Appendix' 같은 양식 끝 마커 보존.
                cleared = clear_data_range(
                    ws,
                    start_row=clear_start, end_row=clear_end,
                    start_col=1, end_col=40,
                    preserve_formula=True, preserve_merged_anchor=True,
                    sentinel_patterns=[
                        "End of Document", "< End", "■ Appendix",
                        "Appendix", "※",
                    ],
                )
                if out_warnings is not None and cleared > 0:
                    out_warnings.append(
                        f"[clear] Test Log/Result row {clear_start}~{clear_end} "
                        f"양식 default {cleared} cell clear (partial overwrite 차단)"
                    )
        except ImportError:
            pass
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
    swuts_map: dict[str, Any] | None = None,
) -> SutrBuildResult:
    """SUTR v3.01 xlsm 생성.

    Args:
        session: input_adapter 출력.
        meta: 빌드 메타.
        template_bytes: 기존 v3.01 xlsm 파일 bytes.
        deviation_cases: swut_deviation_generator 결과 (None이면 빈 Deviation 시트).
        swuds_function_ids: 17차 — SwUDS 함수 ID set (옵션). 제공되면 2.Consistency에
            SwUDS↔SwUTS 매핑 row 추가. Coverage builder와 대칭.
        swuts_map: 60차 F6-A — SwUTS xlsm parser 결과 (옵션). 제공되면 Test Log의
            col B/C/D + Precondition col에 spec docx 데이터 stamp. None이면 기존
            하드코딩 ("AEC, ABV") fallback (backward-compat).
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

    # 라운드 73 T816 — 입력 자산 활용도 진단.
    from backend.services.swut_builder_helpers import diagnose_asset_usage
    warnings.extend(diagnose_asset_usage(
        swuts_map=swuts_map,
        c_function_map=session.c_function_map or None,
        swuds_function_map=session.swuds_function_map or None,
    ))

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

    # 30차 W21 + 31차 W29 + 라운드 84 T1801 + 85 T1903 + 86 T2001: unmapped fc list.
    from backend.services.swut_coverage_aggregator import _compute_asil_distribution
    asil_distribution, ids_by_asil, unmapped_fns = _compute_asil_distribution(
        agg.get("function_rows") or [],
        agg.get("function_asil_map") or {},
        function_asil_from_suds=agg.get("function_asil_from_suds"),
        component_asil_from_sds=agg.get("component_asil_from_sds"),
        function_asil_from_srs=agg.get("function_asil_from_srs"),
        function_name_to_swufn_from_suds=agg.get("function_name_to_swufn_from_suds"),
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
        # 라운드 86 T2002: UNKNOWN 함수 list (audit 진단용).
        "unmapped_function_names": unmapped_fns,
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
    # 59차 F4-C: KJPDS02 v1.01 양식은 Deviation 시트 없음 — layout.deviation_sheet_present
    # False면 시트 미발견을 정상으로 처리 + parse_warnings 안내 메시지 변경.
    dev_ws = next((wb[n] for n in sheet_names if "deviation" in n.lower()), None)
    deviation_required = (
        layout is None or getattr(layout, "deviation_sheet_present", True)
    )
    if dev_ws is None:
        if deviation_required:
            warnings.append("Deviation 시트 미발견")
        else:
            warnings.append(
                "Deviation 시트 미발견 — v1.01 양식 (정상, layout.deviation_sheet_present=False)"
            )
    elif deviation_cases:
        n = _write_deviation(dev_ws, deviation_cases, out_warnings=warnings)
        summary["deviation_cases_written"] = n

    # 57차 T314 fix: 회사 v2.02 SUTR 양식 시트명이 '3.Test Result' (Log 아닌 Result).
    # 54-fix C1 substring 매칭에 'test result'도 포함 — SwUT SUTR (v2.02 Result) /
    # SwIT SITR (Log) 모두 호환.
    log_ws = next(
        (wb[n] for n in sheet_names
         if "test log" in n.lower() or "test result" in n.lower()),
        None,
    )
    if log_ws is None:
        warnings.append("Test Log/Result 시트 미발견")
    else:
        # 54-fix C1: layout 전달 — AL marker
        # 라운드 78 T1303: c_function_map 전달 — ASIL fallback (asil_map 빈 dict 시
        # c_parser comment_asil 매핑으로 ASIL 강조 적용).
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

    summary["template_sha256_12"] = template_sha256_12
    summary["build_timestamp"] = meta.build_timestamp

    # 라운드 83 T1703: AuditLog 시트 신규 추가 (Coverage 대칭, 회사 양식 영향 0).
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

    # 14차 W1: BytesIO 그대로 result에 저장 — getvalue() copy 회피.
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    wb.close()

    filename = (
        f"({meta.project_id}_SUTR) Software Unit Test Result_"
        f"v{meta.release_sw_version}_{short_date(meta.test_date)}_R.xlsm"
    )

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
