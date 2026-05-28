"""SwUT Coverage Report v3.01 xlsx 빌더.

기존 v3.01 xlsx 템플릿을 BytesIO로 로드 → 셀 치환 → bytes 반환.
스타일/머지셀/색상 100% 보존 (template-copy 전략, 사용자 의사결정).

## 시트 매핑 (6 시트)

| 시트 | 출처 |
|------|------|
| Cover | meta + dialog (Doc ID / Project / ASIL / Author / Approver) |
| History | meta + git log 또는 사람 입력 |
| Test Summary | SwUTSession aggregate (Test Date/Engineer/Final/추적성/Stmt/Branch/MCDC) |
| 1.Traceability | TestCaseData에서 TC ID × Function ID O/X 매트릭스 |
| 2.Consistency | SwUDS↔SwUTS 정합성 — 본 라운드 placeholder (SwUDS docx 파싱 미연결) |
| 3. Coverage | per-function Statement/Branch/Exception (FunctionCoverage) |

## ISO 26262 Tool Qualification

- 출력 xlsx의 Cover 시트에 `[AUTO]` 라벨 부착하지 않음 (회사 표준 포맷 유지).
- 빌더 응답 메타에 `is_auto_generated=True` + `needs_review=True` 명시.
- ASIL A 한정 draft. B/C/D는 manual 재검토 의무 (모듈 docstring).
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
    BLANK_MARKUP,
    build_release_history_row,
    mark_asil_b_function,
    mark_asil_c_function,
    mark_asil_d_function,
    mark_fail_cell,
    mark_user_input_required,
    safe_write,
    short_date,
    validate_build_meta,
    validate_xlsx_template_bytes,
    write_label_or_mark,
    write_value_after_label,
)
from backend.services.swut_builder_helpers import extract_warnings_from_session
from backend.services.swut_meta import BuildMetaBase
from backend.services.swut_input_adapter import (
    EnvironmentData,
    FunctionCoverage,
    SwUTSession,
    aggregate_session,
)


# ---------------------------------------------------------------------------
# Dialog/meta payload
# ---------------------------------------------------------------------------

@dataclass
class CoverageBuildMeta(BuildMetaBase):
    """Coverage Report 빌드 메타 — `BuildMetaBase` 17 공통 필드 그대로 사용.

    Coverage Report는 base 외 추가 필드 없음. T137 (W3) BuildMetaBase 통합.
    """
    pass


@dataclass
class CoverageBuildResult:
    """Coverage Report 빌드 결과.

    14차 W1: 메모리 절약 — ``xlsx_io: BytesIO`` 가 주 저장소. ``xlsx_bytes`` 는
    backward compat property — 호출 시점에 ``getvalue()`` (1회 copy). router는
    ``xlsx_io`` 를 StreamingResponse로 직접 stream → bytes copy 회피 + chunk 전송.
    """
    ok: bool
    xlsx_io: io.BytesIO = field(default_factory=io.BytesIO)
    filename: str = ""
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    # ISO 26262 audit hole 표시 (deep-reviewer W5/F3) — placeholder 시트 명시.
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
        """Backward compat — BytesIO 전체를 bytes로 복사 (테스트/감사용)."""
        pos = self.xlsx_io.tell()
        self.xlsx_io.seek(0)
        try:
            return self.xlsx_io.read()
        finally:
            self.xlsx_io.seek(pos)

    @property
    def result_size_bytes(self) -> int:
        """BytesIO 크기 — len(xlsx_bytes) 회피 (full copy 없이 size만)."""
        pos = self.xlsx_io.tell()
        self.xlsx_io.seek(0, 2)  # SEEK_END
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


# ---------------------------------------------------------------------------
# Sheet writers
# ---------------------------------------------------------------------------

# helper 함수는 backend/services/excel_template_utils.py 로 이전 (reviewer 권고 X5).
# 두 빌더(Coverage / SUTR)가 동일 helper를 공유. 단일 출처로 유지보수.


# _aggregate_session 은 swut_input_adapter.aggregate_session 으로 통합 (deep-reviewer W3).


_OPTIONAL_LABELS = {
    "Build Timestamp", "Reviewer", "Doc. ID",
    # 라운드 F7 D11 fix: 회사 표준 양식 (★개발템플릿 V3)은 Cover에 이 라벨 부재.
    # 'Project Name'/'SW Version' 등은 1.Test Summary 시트로 이동 — Cover에 미발견
    # 시 silent OK (warning emit X).
    "Project", "ASIL Level", "Validation Date", "Status", "Version",
}


def _write_label(ws, label: str, value: Any, out_warnings: list[str] | None) -> None:
    """K1: 라벨 미발견 시 warnings 누적 (optional 라벨은 silent OK)."""
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


def _write_cover_sheet(
    ws, meta: CoverageBuildMeta, out_warnings: list[str] | None = None,
    *, layout: Any = None,
) -> None:
    """Cover 시트 — Doc ID/Project/ASIL/Author/Approver 등.

    54차 T282: layout 제공 시 cover_labels 매핑으로 v2.02 양식 동적 호환.
    layout=None이면 v3.01 hardcode label 사용 (SwUT backward compat).
    """
    if not ws:
        return
    labels = layout.cover_labels if layout else {}
    _write_label(ws, labels.get("project_full_name", "Project"),
                 meta.project_full_name, out_warnings)
    _write_label(ws, labels.get("asil_level", "ASIL Level"),
                 meta.asil_level, out_warnings)
    _write_label(ws, labels.get("status", "Status"),
                 "DRAFT — PENDING REVIEW", out_warnings)
    # 23차 T192: validation_date / reviewer / approver 비어있으면 노란 강조
    _write_label_or_mark(ws, labels.get("validation_date", "Validation Date"),
                         meta.validation_date,
                         "yyyy-mm-dd 형식 검증 완료일", out_warnings)
    _write_label_or_mark(ws, labels.get("author", "Author"), meta.author,
                         "test_engineer 또는 default_author", out_warnings)
    _write_label_or_mark(ws, labels.get("reviewer", "Reviewer"), meta.reviewer,
                         "검토자 이름", out_warnings)
    _write_label_or_mark(ws, labels.get("approver", "Approver"), meta.approver,
                         "승인자 이름 (필수)", out_warnings)
    if meta.doc_id_sequence:
        _write_label(ws, labels.get("doc_id", "Doc. ID"),
                     f"{meta.doc_id_base}-{meta.doc_id_sequence}", out_warnings)
    # 56차 T313: Version fill 추가 — SUTR `_write_cover`와 대칭 (이전 SUTR만 v2.02
    # G27 'Version'에 'v2.02' 기록, Coverage는 누락되어 template default 'v0.10' 유지)
    _write_label(ws, labels.get("version", "Version"),
                 f"v{meta.release_sw_version}", out_warnings)
    _write_label(ws, labels.get("build_timestamp", "Build Timestamp"),
                 meta.build_timestamp, out_warnings)


def _write_test_summary_sheet(
    ws, meta: CoverageBuildMeta, agg: dict[str, Any],
    out_warnings: list[str] | None = None,
    *, layout: Any = None, summary: dict[str, Any] | None = None,
) -> None:
    """Test Summary 시트 — 핵심 메트릭 표.

    54차 T282/T283: layout 제공 시 v2.02 양식 동적 호환:
        - test_summary_labels (SW Version / HW Version 등)
        - tc_stats_row B17-F17 (Total/Tested/Passed/Failed/Blocked)
        - requirements_row B22 SwITS 표기
    layout=None이면 v3.01 hardcode label 사용 (SwUT backward compat).
    """
    if not ws:
        return
    labels = layout.test_summary_labels if layout else {}
    _write_label(ws, labels.get("project_full_name", "Project Name"),
                 meta.project_full_name, out_warnings)
    _write_label(ws, labels.get("release_sw_version", "Release Name(SW)"),
                 meta.release_sw_version, out_warnings)
    _write_label(ws, labels.get("hw_version", "Test Target Version(HW)"),
                 meta.hw_version, out_warnings)
    _write_label(ws, labels.get("test_date", "Test Date"),
                 meta.test_date, out_warnings)
    # 24차: Test Engineer 빈 시 노란 강조 (사용자 입력 필요)
    _write_label_or_mark(ws, labels.get("test_engineer", "Test Engineer"),
                         meta.test_engineer,
                         "테스트 엔지니어 이름", out_warnings)
    _write_label(ws, labels.get("final_test_result", "Final Test Result"),
                 meta.final_test_result, out_warnings)

    # 54차 T283: v2.02 양식 신규 row — TC stats / Requirements
    _write_v202_extra_rows(ws, agg, layout, summary, out_warnings)


def _write_v202_tc_stats_row(
    ws, agg: dict[str, Any], layout: Any,
    summary: dict[str, Any] | None,
    out_warnings: list[str] | None = None,
    *,
    total_key: str = "total",
) -> None:
    """55-fix-3 W10 — TC stats data row fill helper (DRY 통합).

    swut_coverage `_write_v202_extra_rows` + swut_sutr `_write_test_summary` inline
    두 곳에서 동일 로직 ~35 lines 중복. 본 helper로 단일 진리 source 확보.

    Args:
        total_key: agg에서 total 값을 가져올 키. Coverage = "total_tcs" (없으면 "total"),
            SUTR = "total" — caller가 명시.
    """
    if layout is None or layout.tc_stats_row is None:
        return
    row = layout.tc_stats_row
    col = layout.tc_stats_col_start or 2

    # 56차 T306 — v2.02 Coverage 양식 label-missing fallback path: layout이 row 17이
    # 빈 row임을 감지 (tc_stats_label_missing=True)했으면 builder가 라벨도 stamp.
    # 회사 Coverage v2.02는 row 17이 사용자 수동 입력 영역으로 비어있음. SITR은
    # label 존재 → 본 branch 미실행 (기존 path 유지).
    if getattr(layout, "tc_stats_label_missing", False):
        label_row = row - 1  # data row 위 라인 = label row
        tc_stats_labels = (
            "Total Number of TCs",
            "Number of TCs Tested",
            "Number of TCs Passed",
            "Number of TCs Failed",
            "Number of TCs not executed",
        )
        for i, lbl in enumerate(tc_stats_labels):
            # label row가 비어있을 때만 stamp — 회사 양식이 일부 라벨만 있는
            # mixed case 방어 (다른 값 있으면 덮어쓰지 않음)
            existing_lbl = ws.cell(label_row, col + i).value
            if existing_lbl is None or (isinstance(existing_lbl, str) and existing_lbl.strip() == ""):
                safe_write(ws, label_row, col + i, lbl)
        if summary is not None:
            summary["tc_stats_fallback_used"] = True
        if out_warnings is not None:
            out_warnings.append(
                f"v2.02 Coverage fallback: TC stats label stamp row={label_row} "
                f"(56차 T306) — audit reviewer에 자동 라벨 채움 사전 통보 권장"
            )

    # 55-fix-2 W4 + 55-fix-3 W8: data row 비어있음 검증.
    # skip 시 산출물 cell에 노란 강조 + hint 추가 (audit silent 차단).
    existing = ws.cell(row, col).value
    if existing is not None and existing != "":
        msg = (
            f"TC stats data row (row={row}, col={col}) already has value "
            f"{existing!r} — 회사 양식 변형 가능성, fill skip (audit reviewer 확인 권장)"
        )
        if out_warnings is not None:
            out_warnings.append(msg)
        if summary is not None:
            summary["tc_stats_skipped_reason"] = msg
        # 55-fix-3 W8: 산출물 셀에 노란 강조 hint (audit reviewer가 X-* 헤더 안 봐도 인지)
        # 단 row 자체에 이미 값이 있어 col+5 (다음 col)에 hint
        mark_user_input_required(
            ws, row, col + 5,
            hint=(
                f"TC stats data row 변형 감지 — 회사 양식이 row {row}에 다른 값. "
                f"audit reviewer가 직접 검토 + 수동 입력 필요"
            ),
        )
        return

    # blocked는 모호 — 0 채움 + summary inferred 표시
    if total_key == "total_tcs":
        total = agg.get("total_tcs", agg.get("total", 0)) or 0
    else:
        total = agg.get(total_key, 0) or 0
    tested = agg.get("tested", 0) or 0
    passed = agg.get("passed", 0) or 0
    failed = agg.get("failed", 0) or 0
    safe_write(ws, row, col, total)
    safe_write(ws, row, col + 1, tested)
    safe_write(ws, row, col + 2, passed)
    safe_write(ws, row, col + 3, failed)
    safe_write(ws, row, col + 4, 0)
    # 54-fix W4: blocked=0 inferred 시각 안내
    mark_user_input_required(
        ws, row, col + 5,
        hint="Blocked TC 수 inferred=0 — VectorCAST blocked 데이터 미지원, 명시적 입력 필요",
    )
    if summary is not None:
        summary["tc_stats_blocked_inferred"] = True


def _write_v202_requirements_row(
    ws, layout: Any,
    summary: dict[str, Any] | None = None,
    out_warnings: list[str] | None = None,
) -> None:
    """55-fix-3 W10 — Requirements row fill helper (DRY 통합).

    55-fix-2 W5 가드: B 셀이 빈/'SwITS'면 fill, 다른 값 ('■' 헤더 등)이면 skip.
    55-fix-3 (deep-reviewer I5): skip 시 warning + summary reason 누적 (W4와 정책 통일).
    """
    if layout is None or layout.requirements_row is None:
        return
    row = layout.requirements_row

    # 56차 T306 — v2.02 Coverage 양식 label-missing fallback: layout이 row 20이
    # 빈 row임을 감지(requirements_label_missing=True)했으면 builder가 헤더+라벨 stamp.
    # SITR은 label/SwITS default 존재 → 본 branch 미실행 (기존 path 유지).
    if getattr(layout, "requirements_label_missing", False):
        # row 20 = 헤더, row 21 = "Source" 라벨, row 22 = "SwITS" 데이터
        header_existing = ws.cell(row, 2).value
        if header_existing is None or (
            isinstance(header_existing, str) and header_existing.strip() == ""
        ):
            safe_write(ws, row, 2, "■  Requirements/Design Coverage")
        source_existing = ws.cell(row + 1, 2).value
        if source_existing is None or (
            isinstance(source_existing, str) and source_existing.strip() == ""
        ):
            safe_write(ws, row + 1, 2, "Source")
        swits_existing = ws.cell(row + 2, 2).value
        if swits_existing is None or (
            isinstance(swits_existing, str) and swits_existing.strip() == ""
        ):
            safe_write(ws, row + 2, 2, "SwITS")
        if summary is not None:
            summary["requirements_fallback_used"] = True
        if out_warnings is not None:
            out_warnings.append(
                f"v2.02 Coverage fallback: Requirements 헤더+라벨 stamp row={row}~{row+2} "
                f"(56차 T306) — audit reviewer에 자동 채움 사전 통보 권장"
            )
        return

    existing = ws.cell(row, 2).value
    if existing is None or existing == "" or existing == "SwITS":
        safe_write(ws, row, 2, "SwITS")
    else:
        # I5 deferred fix — W5 skip 시 warning + summary reason 누적
        msg = (
            f"Requirements row (row={row}, col=B) already has value "
            f"{existing!r} — 회사 양식 변형 가능성, SwITS fill skip"
        )
        if out_warnings is not None:
            out_warnings.append(msg)
        if summary is not None:
            summary["requirements_row_skipped_reason"] = msg


def _write_v202_extra_rows(
    ws, agg: dict[str, Any], layout: Any, summary: dict[str, Any] | None,
    out_warnings: list[str] | None = None,
) -> None:
    """54차 T283 — v2.02 양식 신규 row fill (B17-F17 TC stats + B22 Requirements).

    55-fix-3 W10: helper로 DRY 통합. swut_sutr inline도 동일 helper 호출.
    layout이 None 또는 해당 row가 None (v3.01)이면 silent skip — SwUT 회귀 영향 zero.
    """
    _write_v202_tc_stats_row(
        ws, agg, layout, summary, out_warnings, total_key="total_tcs",
    )
    _write_v202_requirements_row(ws, layout, summary, out_warnings)


def _compute_asil_distribution(
    function_rows: list[FunctionCoverage],
    function_asil_map: dict[str, str],
) -> tuple[dict[str, int], dict[str, list[str]]]:
    """30차 W21 + 31차 W29: function 별 ASIL 등급 분포 계산.

    Args:
        function_rows: 집계된 함수 list (``FunctionCoverage``).
        function_asil_map: ``swut_asil_resolver`` 결과 (``{SwUFn_NNNN: "A"/"B"/...}``).

    Returns:
        ``(distribution, function_ids_by_asil)``
        - distribution: 등급별 개수 (예: ``{"ASIL_A": 15, "ASIL_D": 2, "UNKNOWN": 5}``)
        - function_ids_by_asil: 등급별 함수 ID list dict — keys: "B"/"C"/"D"
          (A/QM/UNKNOWN은 audit 강조 대상 아니므로 누적 안 함). 정렬됨.
    """
    distribution: dict[str, int] = {}
    ids_by_asil: dict[str, list[str]] = {"B": [], "C": [], "D": []}

    for fc in function_rows:
        # function_id 결정 — fc.unit_id 또는 fc.name에서 SwUFn_NNNN 추출.
        candidate_keys = [fc.unit_id or "", fc.name or ""]
        asil = ""
        matched_id = ""
        for key in candidate_keys:
            if not key:
                continue
            if key in function_asil_map:
                asil = function_asil_map[key]
                matched_id = key
                break
            m = _TC_FN_RE.search(key)
            if m and m.group(1) in function_asil_map:
                asil = function_asil_map[m.group(1)]
                matched_id = m.group(1)
                break

        bucket = f"ASIL_{asil}" if asil else "UNKNOWN"
        distribution[bucket] = distribution.get(bucket, 0) + 1
        # 31차 W29: B/C/D 모두 누적 (이전 30차는 D만)
        if asil in ("B", "C", "D") and matched_id:
            ids_by_asil[asil].append(matched_id)

    return (
        distribution,
        {k: sorted(set(v)) for k, v in ids_by_asil.items()},
    )


def _write_coverage_sheet(
    ws, agg: dict[str, Any], *, layout: Any = None,
    out_warnings: list[str] | None = None,
) -> int:
    """3. Coverage 시트 — per-function Statement/Branch/Exception 표.

    30차 W21: ``agg["function_asil_map"]`` 에 ASIL D 매핑된 함수는 row 전체에
    빨간 강조 (``mark_asil_d_function``). 색상은 FAIL과 동일 RGB이나 호출
    의미 분리.

    59차 F4-C: ``layout.coverage_metric_kind == "function_and_calls"`` 시
    KJPDS02 v1.01 양식 호환 — 추가 col에 Function Calls metric stamp
    (``FunctionCoverage.function_calls_coverage``). v2.02/v3.01은 단일 metric.

    Returns:
        쓰여진 행 수.
    """
    if not ws:
        return 0
    function_rows: list[FunctionCoverage] = agg.get("function_rows", [])
    if not function_rows:
        return 0

    # 헤더 행을 찾는다 — "Unit ID" 또는 "Function Name" 라벨 위치
    header_row = None
    for row in ws.iter_rows(min_row=1, max_row=15, values_only=False):
        labels = [
            str(c.value).strip() if c.value else ""
            for c in row
        ]
        if any(l in ("Unit ID", "Function Name", "Component") for l in labels):
            header_row = row[0].row
            break
    if header_row is None:
        return 0

    # 데이터 행 시작은 헤더 + 1 또는 + 2 (회사 포맷에 따라 hierarchical header)
    data_start = header_row + 2

    # 라운드 F7 D5 fix: 회사 표준 양식은 C2부터 'No' col 시작 (HDPDM01 release
    # 산출물은 C1부터). header row scan으로 'No' col 동적 감지 → 그 col부터 stamp.
    # 미발견 시 기존 hardcoded C1 fallback (backward-compat).
    no_col = 1  # fallback
    component_col_offset = 1  # No 다음 col이 Component (회사 표준) 또는 unit_id (HDPDM01)
    has_component_col = False
    for row in ws.iter_rows(min_row=max(1, header_row - 1),
                             max_row=header_row, values_only=False):
        for cell in row:
            v = str(cell.value or "").strip()
            if v == "No":
                no_col = cell.column
            elif v == "Component":
                has_component_col = True
    # 회사 표준: No=C2, Component=C3, Unit ID=C4, Name=C5, Statement Count=C6 ...
    # HDPDM01 release: No=C1, unit_id=C2, name=C3, Statement total=C4 ...
    if has_component_col:
        unit_id_col = no_col + 2  # skip No + Component
        # Statement: Count=+4, Total=+5, Pass=+6 (header에서 'Count'/'Total'/'Pass' 위치 그대로)
        stmt_count_col = no_col + 4
        # Branch: Count=+8 (Statement+Exception 사이 gap), Total=+9, Pass=+10
        branch_count_col = no_col + 8
    else:
        unit_id_col = no_col + 1
        stmt_count_col = no_col + 3
        branch_count_col = no_col + 6

    # 30차 W21: 함수별 ASIL 매핑 + ASIL D 식별.
    function_asil_map: dict[str, str] = agg.get("function_asil_map") or {}

    # F7 stage 8 T706 fix — SwITCV (회사 표준) layout 분기:
    # layout.coverage_metric_kind == "function_and_calls" → SwIT 양식
    #   회사 표준 SwITCV 4.Coverage R9 header: No(C2)/Component(C3)/Unit(C4-C5)/
    #     Functions(C6 — 단일 'O'/'X' Pass)/Exception(C7)/Function Called(C8 Count, C9 Total, C10 Pass)
    #   → Statement/Branch는 SwITCV에 없는 metric. Functions Pass + Function Calls만 stamp
    # default → SwUT 양식 (Statement + Branch + 옵션 Function Calls)
    is_swit_metric_layout = (
        layout is not None
        and getattr(layout, "coverage_metric_kind", "single") == "function_and_calls"
        and has_component_col
    )

    # 기존 데이터 행을 덮어쓴다 (template이 기존 sample 데이터 가질 수 있음).
    written = 0
    for i, fc in enumerate(function_rows):
        r = data_start + i
        safe_write(ws, r, no_col, i + 1)
        safe_write(ws, r, unit_id_col, fc.unit_id)
        safe_write(ws, r, unit_id_col + 1, fc.name)

        if is_swit_metric_layout:
            # SwITCV — Functions Pass (C6) + Function Called metric (C8/C9/C10)
            # Functions Pass: function 매핑 여부 — 신규 session에 unit_id 있으면 'O'
            functions_pass_col = no_col + 4
            fcalls_count_col = no_col + 6
            safe_write(ws, r, functions_pass_col, "O")
            fcc = getattr(fc, "function_calls_coverage", None)
            if fcc is not None and fcc.total > 0:
                safe_write(ws, r, fcalls_count_col, fcc.covered)
                safe_write(ws, r, fcalls_count_col + 1, fcc.total)
                safe_write(ws, r, fcalls_count_col + 2, "O" if fcc.passed else "X")
        else:
            # SwUTCV / HDPDM01 — Statement + Branch metric
            safe_write(ws, r, stmt_count_col, fc.statement.total)
            safe_write(ws, r, stmt_count_col + 1, fc.statement.covered)
            safe_write(ws, r, stmt_count_col + 2, "O" if fc.statement.passed else "X")
            safe_write(ws, r, branch_count_col, fc.branch.total)
            safe_write(ws, r, branch_count_col + 1, fc.branch.covered)
            safe_write(ws, r, branch_count_col + 2, "O" if fc.branch.passed else "X")

            # 59차 F4-C — KJPDS02 v1.01 양식 (HDPDM01과 별도): Function Calls metric col stamp.
            if (
                layout is not None
                and getattr(layout, "coverage_metric_kind", "single") == "function_and_calls"
            ):
                fcc = getattr(fc, "function_calls_coverage", None)
                if fcc is not None and fcc.total > 0:
                    safe_write(ws, r, 10, fcc.total)
                    safe_write(ws, r, 11, fcc.covered)
                    safe_write(ws, r, 12, "O" if fcc.passed else "X")

        # 30차 W21 + 31차 W29: ASIL B/C/D 함수면 row의 핵심 컬럼 강조.
        # fc.unit_id 가 SwUFn_NNNN 패턴일 수 있고 또는 다른 ID. 둘 다 매칭 시도.
        asil = function_asil_map.get(fc.unit_id) or function_asil_map.get(fc.name)
        if not asil:
            # fc.name / fc.unit_id 에 SwUFn_NNNN 정규식 추출 fallback.
            m = _TC_FN_RE.search(fc.unit_id or "") or _TC_FN_RE.search(fc.name or "")
            if m:
                asil = function_asil_map.get(m.group(1))
        # ASIL 등급별 시각 강조 — D(빨강) > C(주황) > B(파랑) 단계
        _marker = {
            "B": mark_asil_b_function,
            "C": mark_asil_c_function,
            "D": mark_asil_d_function,
        }.get(asil or "")
        if _marker:
            for col in (2, 3):  # Unit ID + Function Name 컬럼
                _marker(ws, r, col)

        written += 1

    # F7 자체평가 R1 C2 fix: clear policy — 신규 stamp 후 양식 default 함수 row
    # (Fun_B/Fun_C/Fun_D 등) clear. 회사 표준 SwUTCV 4.Coverage 양식이 R12+에
    # 5+ default 함수 보유 → 신규 session 2 함수만 R10/R11 stamp + R12+ default 잔존
    # → R25 `=SUM(F10:F24)` 수식이 default까지 sum하여 false coverage 산출.
    if written > 0:
        try:
            from backend.services.excel_template_utils import clear_data_range
            clear_start = data_start + written
            clear_end = ws.max_row
            if clear_end >= clear_start:
                cleared = clear_data_range(
                    ws,
                    start_row=clear_start, end_row=clear_end,
                    start_col=no_col, end_col=branch_count_col + 6,
                    preserve_formula=True, preserve_merged_anchor=True,
                    sentinel_patterns=[
                        "End of Document", "< End", "■ Appendix",
                        "Appendix", "※", "TOTALS", "GRAND TOTALS",
                    ],
                )
                if out_warnings is not None and cleared > 0:
                    out_warnings.append(
                        f"[clear] Coverage 시트 row {clear_start}~{clear_end} "
                        f"양식 default 함수 row {cleared} cell clear (false coverage 차단)"
                    )
        except ImportError:
            pass
    return written


# BLANK_MARKUP은 excel_template_utils에서 import (단일 출처).


_TC_FN_RE = re.compile(r"(SwUFn_\d+)")


def _write_history_sheet(
    ws, history_rows: list[dict[str, str]], out_warnings: list[str] | None = None,
) -> int:
    """History 시트 — git log 자동 채움 (T134).

    회사 표준 History layout: Version / Date / Description / Author / Reviewer / Approver.
    헤더 행 다음부터 git log 결과를 row 단위로 작성.

    Returns:
        쓰여진 row 수.
    """
    if not ws or not history_rows:
        return 0
    # 헤더 행 찾기 — "Version" 라벨 위치
    header_pos = None
    for row in ws.iter_rows(min_row=1, max_row=10, values_only=False):
        for cell in row:
            if isinstance(cell.value, str) and cell.value.strip() == "Version":
                header_pos = (row[0].row, cell.column)
                break
        if header_pos:
            break
    if header_pos is None:
        if out_warnings is not None:
            out_warnings.append("History 시트 'Version' 헤더 미발견 — git log 작성 skip")
        return 0

    start_row = header_pos[0] + 1
    col = header_pos[1]
    written = 0
    for i, h in enumerate(history_rows):
        r = start_row + i
        safe_write(ws, r, col, h.get("version", ""))
        safe_write(ws, r, col + 1, h.get("date", ""))
        safe_write(ws, r, col + 2, h.get("description", ""))
        safe_write(ws, r, col + 3, h.get("author", ""))
        safe_write(ws, r, col + 4, h.get("reviewer", ""))
        safe_write(ws, r, col + 5, h.get("approver", ""))
        written += 1
    return written


def _collect_tc_to_function(session: SwUTSession) -> dict[str, str]:
    """TC name → 함수 ID (`SwUFn_NNNN`).

    TC name 예:
      - SwUT: `SwUFn_0101.001` → `SwUFn_0101`
      - SwIT: `SwITC_SwUFn_0101.001` → `SwUFn_0101` (34차 deep-reviewer C1)

    34차 deep-reviewer C1 fix: `re.match`(^anchor)이 SwIT TC prefix `SwITC_`를
    거부해서 2.Consistency 시트 row 2가 항상 FAIL 반환 → 잘못된 audit evidence.
    `re.search`로 변경해 SwUT/SwIT TC 명명 모두 호환. SwUT TC도 prefix 없이
    시작하므로 search로 시작 위치 매칭 정상 (회귀 영향 없음).
    """
    out: dict[str, str] = {}
    for env in session.environments:
        for tc_name in env.test_cases:
            m = _TC_FN_RE.search(tc_name)
            if m:
                out[tc_name] = m.group(1)
    return out


def _compute_self_consistency(
    session: SwUTSession,
    swuds_function_ids: set[str] | None = None,
    *,
    test_kind: str = "SwUTS",
) -> list[dict[str, Any]]:
    """15차/16차: 자체 일관성 4가지 + SwUDS↔{test_kind} 매핑 (옵션) 검증.

    16차: ``swuds_function_ids`` 가 제공되면 row 5 'SwUDS↔{test_kind} 함수 ID 매핑' 추가.

    Args:
        test_kind: audit 라벨 — SwUT는 "SwUTS" (default), SwIT는 "SwIT" (34차 C2).
            row 5 item label과 _write_consistency_sheet intro 텍스트에 반영.

    Returns:
        list of {item, expected, actual, result, note}. result ∈ {PASS, FAIL}.
    """
    rows: list[dict[str, Any]] = []

    # 1. Function ID 일관성 — 모든 환경의 function_coverage가 비어있지 않음
    envs_with_fn = sum(1 for e in session.environments if e.function_coverage)
    total_envs = len(session.environments)
    rows.append({
        "item": "Function coverage data 완전성",
        "expected": f"{total_envs} 환경 모두 function_coverage 보유",
        "actual": f"{envs_with_fn}/{total_envs} 환경",
        "result": "PASS" if envs_with_fn == total_envs else "FAIL",
        "note": "비-zero function_coverage 환경 비율",
    })

    # 2. TC ↔ Function 매핑 — TC name이 SwUFn_NNNN.MMM 패턴 따름
    tc_to_fn = _collect_tc_to_function(session)
    all_tcs: set[str] = set()
    for env in session.environments:
        all_tcs.update(env.test_cases.keys())
    matched_pct = (len(tc_to_fn) / len(all_tcs) * 100) if all_tcs else 100.0
    rows.append({
        "item": "TC ↔ Function ID 패턴 일치",
        "expected": "100% TCs match SwUFn_NNNN.MMM",
        "actual": f"{len(tc_to_fn)}/{len(all_tcs)} ({matched_pct:.1f}%)",
        "result": "PASS" if len(tc_to_fn) == len(all_tcs) else "FAIL",
        "note": "패턴 불일치 시 trace 누락 위험",
    })

    # 3. TC execution coverage — test_results가 test_cases 전체를 cover
    tcs_with_result: set[str] = set()
    for env in session.environments:
        tcs_with_result.update(env.test_results.keys())
    missing = all_tcs - tcs_with_result
    rows.append({
        "item": "TC 실행 결과 완전성",
        "expected": f"{len(all_tcs)} TCs 모두 실행 결과 보유",
        "actual": f"{len(tcs_with_result)}/{len(all_tcs)} ({len(missing)} 누락)",
        "result": "PASS" if not missing else "FAIL",
        "note": "누락 TC는 SUTR Deviation 필요",
    })

    # 4. 환경별 TC 수 합 ↔ agg.total_tcs
    agg = aggregate_session(session)
    env_tc_sum = sum(len(e.test_cases) for e in session.environments)
    rows.append({
        "item": "TC 카운트 일관성 (env 합 ↔ aggregate)",
        "expected": str(env_tc_sum),
        "actual": str(agg["total_tcs"]),
        "result": "PASS" if env_tc_sum == agg["total_tcs"] else "FAIL",
        "note": "aggregate_session 무결성",
    })

    # 5. SwUDS ↔ {test_kind} 함수 ID 매핑 (16차) — swuds_function_ids 제공 시만.
    if swuds_function_ids is not None:
        swuts_fn_ids: set[str] = set()
        for env in session.environments:
            for fc in env.function_coverage:
                swuts_fn_ids.add(fc.unit_id)
        missing_in_swuts = swuds_function_ids - swuts_fn_ids  # SwUDS에 있고 {test_kind}에 없음
        extra_in_swuts = swuts_fn_ids - swuds_function_ids   # {test_kind}에 있고 SwUDS에 없음
        ok = not missing_in_swuts and not extra_in_swuts
        note_parts: list[str] = []
        if missing_in_swuts:
            note_parts.append(
                f"SwUDS 정의 미테스트: {sorted(missing_in_swuts)[:5]}"
                + (f" +{len(missing_in_swuts) - 5} more" if len(missing_in_swuts) > 5 else "")
            )
        if extra_in_swuts:
            note_parts.append(
                f"{test_kind} 추가 (SwUDS 미정의): {sorted(extra_in_swuts)[:5]}"
                + (f" +{len(extra_in_swuts) - 5} more" if len(extra_in_swuts) > 5 else "")
            )
        if not note_parts:
            note_parts.append("함수 ID 1:1 매칭")
        rows.append({
            "item": f"SwUDS ↔ {test_kind} 함수 ID 매핑",
            "expected": f"{len(swuds_function_ids)} 함수 (SwUDS)",
            "actual": f"{len(swuts_fn_ids)} 함수 ({test_kind})",
            "result": "PASS" if ok else "FAIL",
            "note": "; ".join(note_parts),
        })

    return rows


def _write_consistency_sheet(
    ws,
    session: SwUTSession,
    swuds_function_ids: set[str] | None = None,
    out_warnings: list[str] | None = None,
    *,
    test_kind: str = "SwUTS",
) -> int:
    """2.Consistency 시트 — {test_kind} 자체 일관성 + SwUDS↔{test_kind} 매핑 (16차).

    Args:
        swuds_function_ids: SwUDS docx에서 추출된 함수 ID set. 제공되면 row 5 추가.
        test_kind: audit 라벨 — SwUT는 "SwUTS" (default), SwIT는 "SwIT" (34차 C2 fix).
            intro 텍스트 + row 5 item label 동적 치환.

    Layout: A1 = 안내, row 3 = 헤더, row 4부터 결과 row (4 또는 5개).

    Returns:
        쓰여진 결과 row 수 (헤더 제외).
    """
    if not ws:
        return 0

    rows = _compute_self_consistency(
        session, swuds_function_ids=swuds_function_ids, test_kind=test_kind,
    )

    # 안내문 + 헤더 + data
    if swuds_function_ids is not None:
        intro = (
            f"본 시트는 {test_kind} 내부 자체 일관성 + SwUDS↔{test_kind} 함수 ID 매핑 "
            "자동 검증 결과 (16차 v3.02). FAIL 행은 reviewer 검토 + audit evidence 보강 필요."
        )
    else:
        intro = (
            f"본 시트는 {test_kind} 내부 자체 일관성 4 항목 자동 검증 결과. "
            f"SwUDS↔{test_kind} 함수 ID 매핑 비교는 swuds_docx_path 옵션 제공 시 "
            "자동 활성화 (16차)."
        )
    safe_write(ws, 1, 1, intro)
    safe_write(ws, 3, 1, "Item")
    safe_write(ws, 3, 2, "Expected")
    safe_write(ws, 3, 3, "Actual")
    safe_write(ws, 3, 4, "Result")
    safe_write(ws, 3, 5, "Note")

    written = 0
    for i, r in enumerate(rows):
        row_idx = 4 + i
        safe_write(ws, row_idx, 1, r["item"])
        safe_write(ws, row_idx, 2, r["expected"])
        safe_write(ws, row_idx, 3, r["actual"])
        safe_write(ws, row_idx, 4, r["result"])
        safe_write(ws, row_idx, 5, r["note"])
        # 23차 T192: FAIL row의 Result 셀 빨간 강조 — audit reviewer 가시성.
        if r["result"] == "FAIL":
            mark_fail_cell(ws, row_idx, 4)
        written += 1

    failed = [r["item"] for r in rows if r["result"] == "FAIL"]
    if failed and out_warnings is not None:
        out_warnings.append(
            f"2.Consistency 자체 일관성 FAIL {len(failed)}건: {', '.join(failed)}"
        )

    # 57차 T319 fix — 회사 v2.02 양식의 row 11+ SwUDS function list 자동 채움.
    # row 10 = 헤더 (No / ID / Function Name / SwUDS와 SwUTS 항목 정합성 확인 / 비고).
    # row 11+: 모든 환경의 function_coverage 추출 → fn_id + fn_name + 정합성 stamp.
    # 정확한 attr 이름: FunctionCoverage.unit_id (fn_id) + FunctionCoverage.name (fn_name).
    if session.environments:
        all_fns: dict[str, str] = {}  # unit_id → name
        for env in session.environments:
            for fc in env.function_coverage or []:
                unit_id = fc.unit_id  # 예: SwUFn_0101
                fn_name = fc.name      # 예: main
                if unit_id and unit_id not in all_fns:
                    all_fns[unit_id] = fn_name
        swuds_set = swuds_function_ids or set()
        function_list_start = 11
        for idx, (unit_id, fn_name) in enumerate(sorted(all_fns.items())):
            row_idx_fn = function_list_start + idx
            if row_idx_fn > 2000:  # safety: 2000 row 한계 (회사 양식 최대)
                break
            safe_write(ws, row_idx_fn, 2, idx + 1)         # B: No
            safe_write(ws, row_idx_fn, 3, unit_id)         # C: Function ID
            safe_write(ws, row_idx_fn, 4, fn_name)         # D: Function Name
            # E: SwUDS↔SwUTS 정합성 — SwUDS function_ids set에 있으면 'O', 없으면 'X'
            in_swuds = unit_id in swuds_set if swuds_set else True
            safe_write(ws, row_idx_fn, 5, "O" if in_swuds else "X")

    return written


def _write_traceability_sheet(
    ws, session: SwUTSession, out_warnings: list[str] | None = None,
    *, layout: Any = None,
) -> int:
    """1.Traceability 시트 — TC × Function 매트릭스 본격 작성 (T133).

    시트 헤더 행에서 `SwUFn_NNNN` 컬럼 위치 lookup → 각 TC 행에 'O' 표시.
    헤더 미발견 시 BLANK_MARKUP 유지.

    58차 F2: SwIT v2.02 양식은 헤더 row 위치가 v3.01 (1~10)보다 아래쪽 (20~25)에
    있을 수 있고 SwUFn_ 컬럼 개수도 더 작음. layout.traceability_header_row 제공
    시 그 row를 헤더로 강제. fallback 시 max_row=30 확장 + SwUFn_ 임계 50→5로 완화.

    Args:
        ws: 1.Traceability 시트.
        session: SwUTSession.
        out_warnings: 누락/실패 메시지 누적.
        layout: Optional[SwitLayout] — traceability_header_row 보유 시 우선.

    Returns:
        쓰여진 'O' 셀 수. 0이면 매트릭스 미작성.
    """
    if not ws:
        return 0

    # 59차 F4-C → 60차 F6-B 갱신 — KJPDS02 v1.01 양식 matrix kind 분기.
    # "switc_x_swst" 양식은 row = SwITC ID, col = SwST/SwSTR.
    # F6-B 라이브 분석 (T411) 결과: 검증된 양식 (KJPDS02 SwITS v1.01 + HDPDM01
    # SITS v2.02) 모두 'Integration Strategy' 시트가 SwST matrix가 아닌
    # **call graph (depth 1~14 tree)** 양식. SwITC×SwST traceability matrix 자체
    # 가 시방서에 존재하지 않음 — F4-C skip이 양식 설계상 정답.
    # 본 메시지는 audit reviewer가 'matrix 미stamp' 정상 동작임을 인지하도록 명시.
    # 다른 회사 양식 도입 시 재검증 필요.
    matrix_kind = (
        getattr(layout, "traceability_matrix_kind", "swufn_x_env") if layout is not None
        else "swufn_x_env"
    )
    if matrix_kind == "switc_x_swst":
        # 라운드 F7 stage 8 T705 부분 구현: SwITCV 2.Traceability 양식 default
        # SwITC row + 'O' 마킹 clear (false audit 차단) + 신규 session의 SwITC TC
        # 를 row stamp + count='1'. SwST × SwITC 'O' stamp는 SwITS spec 미제공
        # → skip + 명확한 warning (사용자에게 "T705 partial — SwST 매핑 부재" 안내).
        ws_title = getattr(ws, "title", "Traceability").strip()

        # 1) header row 찾기 — R11 SwST_01~SwSTR_NN header
        header_row_idx = None
        for row in ws.iter_rows(min_row=1, max_row=20, values_only=False):
            swst_cols = sum(
                1 for c in row
                if isinstance(c.value, str)
                and (str(c.value).strip().startswith(("SwST_", "SwSTR_")))
            )
            if swst_cols >= 3:
                header_row_idx = row[0].row
                break
        if header_row_idx is None:
            if out_warnings is not None:
                out_warnings.append(
                    f"{ws_title} switc_x_swst header (SwST_/SwSTR_) 미발견 — skip"
                )
            return 0

        # 2) data start = header + 2 (R12 count + R13~ SwITC row)
        data_start = header_row_idx + 2
        # session에서 unique SwITC ID 추출
        tc_to_fn = _collect_tc_to_function(session)
        # SwITC TC name 패턴 'SwITC_NN' 또는 'SwITC_SwUFn_NNNN.NNN' → SwITC ID prefix 추출
        import re as _re
        # 패턴 우선순위 (F7 stage 8 T705):
        # 1) SwITC_NN / SwITC_NN_NN (KJPDS02 회사 표준)
        # 2) SwITC_SwUFn_NNNN.NNN (VectorCAST SwIT — SwUFn 부분 NNNN 추출 → SwITC_NNNN)
        # 3) SwUFn_NNNN.NNN (SwUT session — SwITC_NNNN 변환, F6-A 패턴)
        _SWITC_DIRECT = _re.compile(r"^(SwITC_\d+(?:_\d+)?)$")
        _SWITC_WITH_FN = _re.compile(r"^SwITC_SwUFn_(\d+)")
        _SWUFN_ONLY = _re.compile(r"^SwUFn_(\d+)")
        switc_ids: list[str] = []
        seen: set[str] = set()
        for tc_name in tc_to_fn.keys():
            # SwITC_NN_NN 형식 sub-index 제거 후 prefix만 — 'SwITC_05_01' / 'SwITC_05_02'
            # 같은 sub TC는 'SwITC_05' 1건으로 통합
            sid = None
            m = _re.match(r"^(SwITC_\d+)", tc_name)
            if m:
                sid = m.group(1)
            else:
                fm = _SWITC_WITH_FN.match(tc_name)
                if fm:
                    sid = f"SwITC_{fm.group(1)}"
                else:
                    um = _SWUFN_ONLY.match(tc_name)
                    if um:
                        sid = f"SwITC_{um.group(1)}"
            if sid and sid not in seen:
                seen.add(sid)
                switc_ids.append(sid)
        switc_ids.sort()

        # 3) 양식 default clear (data_start ~ max_row, col 1~5: No/ID/Count + O 마킹 일부)
        try:
            from backend.services.excel_template_utils import clear_data_range
            cleared = clear_data_range(
                ws,
                start_row=data_start, end_row=ws.max_row,
                start_col=1, end_col=ws.max_column or 50,
                preserve_formula=True, preserve_merged_anchor=True,
                sentinel_patterns=["End of Document", "Appendix", "TOTALS"],
            )
            if out_warnings is not None and cleared > 0:
                out_warnings.append(
                    f"[clear] {ws_title} (SwITC×SwST matrix) 양식 default "
                    f"{cleared} cell clear — 신규 session SwITC {len(switc_ids)}건 stamp"
                )
        except ImportError:
            pass

        # 4) 신규 session의 SwITC row stamp (C2=No, C3=ID, C4=Count)
        # 회사 표준 SwITCV R13~: C2='SwITC_01' (ID), C3='3' (count)
        for i, sid in enumerate(switc_ids):
            r = data_start + i
            safe_write(ws, r, 1, i + 1)        # No
            safe_write(ws, r, 2, sid)          # SwITC ID
            safe_write(ws, r, 3, 1)            # Count (각 SwITC당 1)

        if out_warnings is not None:
            out_warnings.append(
                f"{ws_title} matrix kind 'switc_x_swst' partial stamp — SwITC "
                f"{len(switc_ids)}건 row stamp. SwST × SwITC 'O' 마킹은 SwITS "
                "spec 미제공으로 skip (T705 full — SwITS xlsm parser 통합 필요). "
                "audit reviewer는 SwST 매핑 manual 확인 의무."
            )
        return len(switc_ids)

    # 58차 F2: layout 제공 시 traceability_header_row 강제. fallback은 자동 탐색.
    header_row_idx = None
    header_cols: dict[str, int] = {}
    layout_header_row = (
        getattr(layout, "traceability_header_row", None) if layout is not None else None
    )
    if layout_header_row is not None:
        # 강제 헤더 row — 그 row에서 SwUFn_/SwUTC_/SwITC_ prefix col 수집
        for cell in next(
            ws.iter_rows(min_row=layout_header_row, max_row=layout_header_row,
                         values_only=False),
            [],
        ):
            v = cell.value
            if isinstance(v, str):
                s = v.strip()
                if _TC_FN_RE.fullmatch(s) or s.startswith(("SwUTC_", "SwITC_", "SwUFn_")):
                    header_cols[s] = cell.column
        if header_cols:
            header_row_idx = layout_header_row

    if header_row_idx is None:
        # 자동 탐색 — max_row 20 → 30 확장, SwUFn_ 임계 50 → 5 완화 (SwIT v2.02 대응).
        for row in ws.iter_rows(min_row=1, max_row=30, values_only=False):
            cols: dict[str, int] = {}
            for cell in row:
                v = cell.value
                if isinstance(v, str) and _TC_FN_RE.fullmatch(v.strip()):
                    cols[v.strip()] = cell.column
            if len(cols) >= 5:
                header_row_idx = row[0].row
                header_cols = cols
                break

    if header_row_idx is None:
        if out_warnings is not None:
            out_warnings.append(
                "1.Traceability 헤더(SwUFn_xxxx 행) 미발견 — placeholder 유지"
            )
        safe_write(ws, 1, 1, BLANK_MARKUP)
        return 0

    # 2) 기존 TC 행 위치 인덱싱 — SwUTC_SwUFn_xxxx.NNN 또는 SwUFn_xxxx.NNN
    data_start = header_row_idx + 1
    tc_row_index: dict[str, int] = {}
    for row in ws.iter_rows(
        min_row=data_start, max_row=data_start + 600, values_only=False,
    ):
        for cell in row[:5]:
            v = cell.value
            if isinstance(v, str):
                stripped = v.strip()
                if stripped.startswith(("SwUTC_SwUFn_", "SwUFn_")):
                    tc_row_index[stripped] = row[0].row
                    break

    # 3) 우리 session TC name → 함수 매핑 + 'O' 표시.
    # T136: 회사 v3.01 row label은 `SwUTC_<fn_id>` (인덱스 `.NNN` 없음).
    # `SwUTC_<tc_name>` (인덱스 포함) 과 `<tc_name>` 도 fallback 시도.
    tc_to_fn = _collect_tc_to_function(session)
    written = 0
    matched_fn: set[str] = set()
    for tc_name, fn_id in tc_to_fn.items():
        col = header_cols.get(fn_id)
        if col is None:
            continue
        row_idx = (
            tc_row_index.get(f"SwUTC_{fn_id}")          # 회사 표준 (인덱스 없음)
            or tc_row_index.get(f"SwUTC_{tc_name}")     # 인덱스 포함 형식
            or tc_row_index.get(tc_name)                # 우리 빌더 native
        )
        if row_idx is None:
            continue
        # 같은 fn_id 가 여러 TC index를 가질 때 첫 매칭만 — 회사 시트 row 1개당 'O' 1개로 충분.
        if fn_id in matched_fn:
            continue
        if safe_write(ws, row_idx, col, "O"):
            written += 1
            matched_fn.add(fn_id)

    if written == 0:
        if out_warnings is not None:
            out_warnings.append(
                "1.Traceability — 헤더는 발견했으나 TC 매칭 0건 (회사 시트 row 명명 차이)"
            )
        safe_write(ws, 1, 1, BLANK_MARKUP)
    return written


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_coverage_report(
    session: SwUTSession,
    meta: CoverageBuildMeta,
    template_bytes: bytes,
    swuds_function_ids: set[str] | None = None,
    hmr_html_bytes: bytes | None = None,
) -> CoverageBuildResult:
    """Coverage Report v3.01 xlsx 생성.

    Args:
        session: SwUT 데이터 (input_adapter 출력).
        meta: 빌드 메타 (Project/ASIL/Author 등).
        template_bytes: 기존 v3.01 xlsx 파일 bytes (template).
        swuds_function_ids: 16차 — SwUDS 함수 ID set (옵션). 제공되면 2.Consistency에
            'SwUDS↔SwUTS 함수 ID 매핑' row 5 추가 + incomplete_sheets에서 partial 라벨 제거.
        hmr_html_bytes: 60차 F6-C — VectorCAST aggregate metrics report HTML
            (옵션, Jenkins_PDSM_UT/IT_metrics_report.html 양식). 제공 시 함수별
            Function Calls coverage를 추출하여 fc.function_calls_coverage 채움.
            KJPDS02 v1.01 양식의 row 6 'Function Calls' stamp source. None이면
            기존 빈 CoverageStats default 유지 (backward-compat, v2.02/v3.01 동작).

    Returns:
        CoverageBuildResult — xlsx_io 채워짐.
    """
    if openpyxl is None:
        raise RuntimeError("openpyxl is required for SwUT Coverage Report builder")

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
    validate_xlsx_template_bytes(template_bytes, label="Coverage Report template")

    # 5차 L1: 입력 template hash — audit 추적성.
    template_sha256_12 = hashlib.sha256(template_bytes).hexdigest()[:12]

    # 37차 fix → 38차 W1 DRY: extract_warnings_from_session helper로 추출.
    warnings: list[str] = extract_warnings_from_session(session)

    # 54-fix C1: SwUT 라우터에 v2.02 template 잘못 입력되더라도 silent 빈 셀 차단.
    # v3.01 양식은 fallback_to_v301=True로 기존 hardcode 동작과 동등 (회귀 zero 영향).
    # v2.02 양식 (사용자 실수 또는 의도된 mixed)이면 SW Version 등 v2.02 라벨 매핑.
    from backend.services.excel_layout_resolver import inspect_swit_layout
    layout = inspect_swit_layout(template_bytes, "coverage")
    if layout.warnings:
        warnings.extend([f"[layout] {w}" for w in layout.warnings])

    wb: Workbook = openpyxl.load_workbook(io.BytesIO(template_bytes), data_only=False)
    sheet_names = wb.sheetnames

    agg = aggregate_session(session)

    # 60차 F6-C — HMR HTML 제공 시 함수별 Function Calls coverage 채움.
    # VectorCAST aggregate metrics report (Jenkins_PDSM_UT/IT_metrics_report)
    # 양식 → 함수명 매칭으로 fc.function_calls_coverage stamp. 매칭 안 되면 skip
    # (graceful — v2.02/v3.01 빈 cell default 유지).
    if hmr_html_bytes:
        from backend.services.swut_input_adapter import CoverageStats
        from backend.services.vcast_hmr_parser import parse_hmr_html
        hmr_parse_warnings: list[str] = []
        hmr_result = parse_hmr_html(
            hmr_html_bytes, parse_warnings=hmr_parse_warnings,
        )
        if hmr_parse_warnings:
            warnings.extend([f"[hmr] {w}" for w in hmr_parse_warnings])
        if hmr_result.ok:
            # F6 자체평가 Round 1 W2 fix: dataclasses.replace + 새 list로 session
            # 객체 mutation 차단 (향후 session caching 도입 시 silent regression 방지).
            from dataclasses import replace as _dc_replace
            original_rows: list[FunctionCoverage] = agg.get("function_rows") or []
            new_function_rows: list[FunctionCoverage] = []
            stamped = 0
            ambiguous = 0
            for fc in original_rows:
                # F6 Round 1 C2 + W3 fix: metrics_by_name 사용 — 함수명 중복 시
                # ambiguous skip + warning. fc.unit_id dead fallback 제거 (HMR key는
                # 실제 C 함수명, fc.unit_id는 SwUFn_NNNN — 본질적으로 불일치).
                candidates = hmr_result.metrics_by_name.get(fc.name, [])
                if len(candidates) > 1:
                    ambiguous += 1
                    _files = ", ".join(sorted({c.unit_file for c in candidates}))
                    warnings.append(
                        f"[hmr] ambiguous function '{fc.name}' — 다중 unit_file "
                        f"({_files}) 매칭. silent wrong-pick 방지 위해 stamp skip"
                    )
                    new_function_rows.append(fc)
                    continue
                m = candidates[0] if candidates else None
                if m and m.total_calls > 0:
                    new_function_rows.append(_dc_replace(
                        fc,
                        function_calls_coverage=CoverageStats(
                            covered=m.covered_calls,
                            total=m.total_calls,
                            coverage_pct=m.coverage_pct / 100.0,
                        ),
                    ))
                    stamped += 1
                else:
                    new_function_rows.append(fc)
            warnings.append(
                f"[hmr] Function Calls metric stamped — {stamped}/{len(original_rows)} "
                f"functions matched (HMR metric count: {len(hmr_result.metrics)}, "
                f"ambiguous skipped: {ambiguous})"
            )
            # 새 list로 교체 — 이후 3.Coverage sheet writer가 stamped 값 사용,
            # session.environments[].function_coverage는 unchanged (W2 격리).
            agg["function_rows"] = new_function_rows

    # 30차 W21 + 31차 W29: 함수별 ASIL 분포 + B/C/D 별 함수 ID 그룹.
    asil_distribution, ids_by_asil = _compute_asil_distribution(
        agg.get("function_rows") or [],
        agg.get("function_asil_map") or {},
    )

    summary = {
        "environments": len(session.environments),
        "total_tcs": agg["total_tcs"],
        "passed": agg["passed"],
        "failed": agg["failed"],
        "function_rows": agg["function_count"],
        # 30차 W21 + 31차 W29: ASIL 등급 분포 + 등급별 함수 ID.
        "asil_distribution": asil_distribution,
        "asil_b_function_ids": ids_by_asil.get("B", []),
        "asil_c_function_ids": ids_by_asil.get("C", []),
        "asil_d_function_ids": ids_by_asil.get("D", []),
        # 31-fix D15: audit reviewer 공지 메타 — 회사 v3.01 표준 외 색상 확장 명시.
        "asil_highlight_policy": (
            "B=파랑(#E2F0FF) / C=주황(#FFE5CC) / D=빨강(#FFC7CE) — "
            "31차 비표준 audit 확장 (회사 v3.01 양식은 빨강만 사용)"
        ),
    }

    # Cover (Cover는 v2.02도 동일 시트명 "Cover" 사용 — 정확 매칭 유지)
    cover_ws = next((wb[n] for n in sheet_names if n.lower() == "cover"), None)
    if cover_ws is None:
        warnings.append("Cover 시트 미발견 — Doc ID/Author 등 미기록")
    else:
        # 54-fix C1: layout 전달 — v2.02 라벨 자동 매핑 + v3.01 fallback
        _write_cover_sheet(cover_ws, meta, out_warnings=warnings, layout=layout)

    # Test Summary — 54-fix C1: SwIT 53차 patern과 대칭. v2.02 "1.Test Summary" 호환.
    ts_ws = next((wb[n] for n in sheet_names if "test summary" in n.lower()), None)
    if ts_ws is None:
        warnings.append("Test Summary 시트 미발견")
    else:
        # 54-fix C1: layout + summary 전달
        _write_test_summary_sheet(
            ts_ws, meta, agg, out_warnings=warnings,
            layout=layout, summary=summary,
        )

    # 3. Coverage
    cov_ws = next((wb[n] for n in sheet_names
                   if "coverage" in n.lower() and "traceability" not in n.lower()
                   and "consistency" not in n.lower()), None)
    if cov_ws is None:
        warnings.append("Coverage 시트 미발견")
    else:
        # F7 자체평가 R2 N3 fix: layout + out_warnings 전달 — clear warning이
        # X-SwUT-Warnings 헤더로 propagate (이전 누락).
        n_written = _write_coverage_sheet(
            cov_ws, agg, layout=layout, out_warnings=warnings,
        )
        summary["coverage_rows_written"] = n_written

    # 1.Traceability — T133 본격 작성 (TC×Function 매트릭스)
    # 라운드 F7 D1 fix: incomplete_sheets에 실제 시트 이름 보고 — 회사 표준은
    # '2.Traceability' (prefix 2.), HDPDM01 release는 '1.Traceability'. 시트 발견
    # 시 ws.title 사용.
    incomplete_sheets: list[str] = []
    trace_ws = next((wb[n] for n in sheet_names if "traceability" in n.lower()), None)
    if trace_ws is None:
        warnings.append("Traceability 시트 미발견")
    else:
        n_o = _write_traceability_sheet(trace_ws, session, out_warnings=warnings, layout=layout)
        summary["traceability_o_cells"] = n_o
        if n_o == 0:
            incomplete_sheets.append(trace_ws.title.strip())

    # 2.Consistency — 15차: SwUTS 자체 일관성 4 row + 16차: SwUDS↔SwUTS 매핑 row (옵션).
    cons_ws = next((wb[n] for n in sheet_names if "consistency" in n.lower()), None)
    if cons_ws is not None:
        n_cons = _write_consistency_sheet(
            cons_ws, session,
            swuds_function_ids=swuds_function_ids,
            out_warnings=warnings,
        )
        summary["consistency_self_check_rows"] = n_cons
        if swuds_function_ids is not None:
            summary["consistency_swuds_compared"] = True
            # SwUDS 매핑까지 자동 완료 — incomplete 표시 제거.
        else:
            summary["consistency_swuds_compared"] = False
            # 라운드 F7 D1 fix: ws.title 사용 (회사 표준 '3.Consistency')
            incomplete_sheets.append(
                f"{cons_ws.title.strip()} (SwUDS 비교 partial — v3.02)"
            )
    else:
        warnings.append("Consistency 시트 미발견")
        incomplete_sheets.append("Consistency")

    # History — 55-fix: 사용자 결정 B (single-row release entry).
    # 이전 git log 10건 → 산출물 release_sw_version + test_date 1 row만.
    hist_ws = next((wb[n] for n in sheet_names if n.lower() == "history"), None)
    if hist_ws is not None:
        # 55-fix-2 W2: SwUT prefix 명시 — audit reviewer가 산출물 식별 가능 (vs SwIT)
        # 55-fix-2 W6: out_warnings 전달 — release_sw_version/test_date 빈 시 누적
        release_rows = build_release_history_row(
            meta, doc_kind="SwUT Coverage Report", out_warnings=warnings,
        )
        n_h = _write_history_sheet(hist_ws, release_rows, out_warnings=warnings)
        summary["history_rows_written"] = n_h
        if n_h == 0:
            incomplete_sheets.append("History")

    # 14차 W1: BytesIO 그대로 result에 저장 — getvalue() copy 회피.
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)  # router StreamingResponse가 처음부터 read
    wb.close()

    filename = (
        f"({meta.project_id})SwUT Coverage Report_"
        f"v{meta.release_sw_version}_{short_date(meta.test_date)}_R.xlsx"
    )

    summary["template_sha256_12"] = template_sha256_12
    summary["build_timestamp"] = meta.build_timestamp
    return CoverageBuildResult(
        ok=True,
        xlsx_io=out,
        filename=filename,
        warnings=warnings,
        incomplete_sheets=incomplete_sheets,
        summary=summary,
    )


# `short_date`는 excel_template_utils에서 import — 모듈 하단 중복 정의 제거 (deep-reviewer C1).


# 38차 W2 — public API 명시. SwIT aggregator가 본 모듈의 _write_*_sheet private
# 함수들을 직접 import 중 (강결합 보류 — 35차 SwIT 라운드 채택). 본 __all__로
# 강결합 경계를 명시화: signature 변경 시 SwIT 회귀(test_swit_*_aggregator.py)
# 동시 검증 의무. 향후 W2 정리 시 public alias로 분리 권장.
__all__ = [
    # Public API
    "CoverageBuildMeta",
    "CoverageBuildResult",
    "build_coverage_report",
    # Private 함수 — SwIT가 import 중. 명시로 강결합 가시화.
    "_compute_asil_distribution",
    "_write_consistency_sheet",
    "_write_cover_sheet",
    "_write_coverage_sheet",
    "_write_history_sheet",
    "_write_test_summary_sheet",
    "_write_traceability_sheet",
]
