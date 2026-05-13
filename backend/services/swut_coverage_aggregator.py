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
    collect_git_history,
    mark_asil_b_function,
    mark_asil_c_function,
    mark_asil_d_function,
    mark_fail_cell,
    safe_write,
    short_date,
    validate_build_meta,
    validate_xlsx_template_bytes,
    write_label_or_mark,
    write_value_after_label,
)
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


_OPTIONAL_LABELS = {"Build Timestamp", "Reviewer", "Doc. ID"}


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
) -> None:
    """Cover 시트 — Doc ID/Project/ASIL/Author/Approver 등."""
    if not ws:
        return
    _write_label(ws, "Project", meta.project_full_name, out_warnings)
    _write_label(ws, "ASIL Level", meta.asil_level, out_warnings)
    _write_label(ws, "Status", "DRAFT — PENDING REVIEW", out_warnings)
    # 23차 T192: validation_date / reviewer / approver 비어있으면 노란 강조
    _write_label_or_mark(ws, "Validation Date", meta.validation_date,
                         "yyyy-mm-dd 형식 검증 완료일", out_warnings)
    _write_label_or_mark(ws, "Author", meta.author,
                         "test_engineer 또는 default_author", out_warnings)
    _write_label_or_mark(ws, "Reviewer", meta.reviewer,
                         "검토자 이름", out_warnings)
    _write_label_or_mark(ws, "Approver", meta.approver,
                         "승인자 이름 (필수)", out_warnings)
    if meta.doc_id_sequence:
        _write_label(ws, "Doc. ID",
                     f"{meta.doc_id_base}-{meta.doc_id_sequence}", out_warnings)
    _write_label(ws, "Build Timestamp", meta.build_timestamp, out_warnings)


def _write_test_summary_sheet(
    ws, meta: CoverageBuildMeta, agg: dict[str, Any],
    out_warnings: list[str] | None = None,
) -> None:
    """Test Summary 시트 — 핵심 메트릭 표."""
    if not ws:
        return
    _write_label(ws, "Project Name", meta.project_full_name, out_warnings)
    _write_label(ws, "Release Name(SW)", meta.release_sw_version, out_warnings)
    _write_label(ws, "Test Target Version(HW)", meta.hw_version, out_warnings)
    _write_label(ws, "Test Date", meta.test_date, out_warnings)
    # 24차: Test Engineer 빈 시 노란 강조 (사용자 입력 필요)
    _write_label_or_mark(ws, "Test Engineer", meta.test_engineer,
                         "테스트 엔지니어 이름", out_warnings)
    _write_label(ws, "Final Test Result", meta.final_test_result, out_warnings)


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


def _write_coverage_sheet(ws, agg: dict[str, Any]) -> int:
    """3. Coverage 시트 — per-function Statement/Branch/Exception 표.

    30차 W21: ``agg["function_asil_map"]`` 에 ASIL D 매핑된 함수는 row 전체에
    빨간 강조 (``mark_asil_d_function``). 색상은 FAIL과 동일 RGB이나 호출
    의미 분리.

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

    # 30차 W21: 함수별 ASIL 매핑 + ASIL D 식별.
    function_asil_map: dict[str, str] = agg.get("function_asil_map") or {}

    # 기존 데이터 행을 덮어쓴다 (template이 기존 sample 데이터 가질 수 있음).
    # 머지셀 head-only 쓰기 — _safe_write 사용 (실패 시 silent skip).
    written = 0
    for i, fc in enumerate(function_rows):
        r = data_start + i
        safe_write(ws, r, 1, i + 1)
        safe_write(ws, r, 2, fc.unit_id)
        safe_write(ws, r, 3, fc.name)
        safe_write(ws, r, 4, fc.statement.total)
        safe_write(ws, r, 5, fc.statement.covered)
        safe_write(ws, r, 6, "O" if fc.statement.passed else "X")
        safe_write(ws, r, 7, fc.branch.total)
        safe_write(ws, r, 8, fc.branch.covered)
        safe_write(ws, r, 9, "O" if fc.branch.passed else "X")

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

    TC name 예: `SwUFn_0101.001` → function `SwUFn_0101`.
    """
    out: dict[str, str] = {}
    for env in session.environments:
        for tc_name in env.test_cases:
            m = _TC_FN_RE.match(tc_name)
            if m:
                out[tc_name] = m.group(1)
    return out


def _compute_self_consistency(
    session: SwUTSession,
    swuds_function_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """15차/16차: SwUTS 자체 일관성 4가지 + SwUDS↔SwUTS 매핑 (옵션) 검증.

    16차: ``swuds_function_ids`` 가 제공되면 row 5 'SwUDS↔SwUTS 함수 ID 매핑' 추가.

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

    # 5. SwUDS ↔ SwUTS 함수 ID 매핑 (16차) — swuds_function_ids 제공 시만.
    if swuds_function_ids is not None:
        swuts_fn_ids: set[str] = set()
        for env in session.environments:
            for fc in env.function_coverage:
                swuts_fn_ids.add(fc.unit_id)
        missing_in_swuts = swuds_function_ids - swuts_fn_ids  # SwUDS에 있고 SwUTS에 없음
        extra_in_swuts = swuts_fn_ids - swuds_function_ids   # SwUTS에 있고 SwUDS에 없음
        ok = not missing_in_swuts and not extra_in_swuts
        note_parts: list[str] = []
        if missing_in_swuts:
            note_parts.append(
                f"SwUDS 정의 미테스트: {sorted(missing_in_swuts)[:5]}"
                + (f" +{len(missing_in_swuts) - 5} more" if len(missing_in_swuts) > 5 else "")
            )
        if extra_in_swuts:
            note_parts.append(
                f"SwUTS 추가 (SwUDS 미정의): {sorted(extra_in_swuts)[:5]}"
                + (f" +{len(extra_in_swuts) - 5} more" if len(extra_in_swuts) > 5 else "")
            )
        if not note_parts:
            note_parts.append("함수 ID 1:1 매칭")
        rows.append({
            "item": "SwUDS ↔ SwUTS 함수 ID 매핑",
            "expected": f"{len(swuds_function_ids)} 함수 (SwUDS)",
            "actual": f"{len(swuts_fn_ids)} 함수 (SwUTS)",
            "result": "PASS" if ok else "FAIL",
            "note": "; ".join(note_parts),
        })

    return rows


def _write_consistency_sheet(
    ws,
    session: SwUTSession,
    swuds_function_ids: set[str] | None = None,
    out_warnings: list[str] | None = None,
) -> int:
    """2.Consistency 시트 — SwUTS 자체 일관성 + SwUDS↔SwUTS 매핑 (16차).

    Args:
        swuds_function_ids: SwUDS docx에서 추출된 함수 ID set. 제공되면 row 5 추가.

    Layout: A1 = 안내, row 3 = 헤더, row 4부터 결과 row (4 또는 5개).

    Returns:
        쓰여진 결과 row 수 (헤더 제외).
    """
    if not ws:
        return 0

    rows = _compute_self_consistency(session, swuds_function_ids=swuds_function_ids)

    # 안내문 + 헤더 + data
    if swuds_function_ids is not None:
        intro = (
            "본 시트는 SwUTS 내부 자체 일관성 + SwUDS↔SwUTS 함수 ID 매핑 자동 검증 결과 (16차 v3.02). "
            "FAIL 행은 reviewer 검토 + audit evidence 보강 필요."
        )
    else:
        intro = (
            "본 시트는 SwUTS 내부 자체 일관성 4 항목 자동 검증 결과. "
            "SwUDS↔SwUTS 함수 ID 매핑 비교는 swuds_docx_path 옵션 제공 시 자동 활성화 (16차)."
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

    return written


def _write_traceability_sheet(
    ws, session: SwUTSession, out_warnings: list[str] | None = None,
) -> int:
    """1.Traceability 시트 — TC × Function 매트릭스 본격 작성 (T133).

    시트 헤더 행에서 `SwUFn_NNNN` 컬럼 위치 lookup → 각 TC 행에 'O' 표시.
    헤더 미발견 시 BLANK_MARKUP 유지.

    Returns:
        쓰여진 'O' 셀 수. 0이면 매트릭스 미작성.
    """
    if not ws:
        return 0

    # 1) 헤더 행 찾기 — SwUFn_xxxx 컬럼이 50개+ 등장하는 행
    header_row_idx = None
    header_cols: dict[str, int] = {}
    for row in ws.iter_rows(min_row=1, max_row=20, values_only=False):
        cols: dict[str, int] = {}
        for cell in row:
            v = cell.value
            if isinstance(v, str) and _TC_FN_RE.fullmatch(v.strip()):
                cols[v.strip()] = cell.column
        if len(cols) >= 50:
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
) -> CoverageBuildResult:
    """Coverage Report v3.01 xlsx 생성.

    Args:
        session: SwUT 데이터 (input_adapter 출력).
        meta: 빌드 메타 (Project/ASIL/Author 등).
        template_bytes: 기존 v3.01 xlsx 파일 bytes (template).
        swuds_function_ids: 16차 — SwUDS 함수 ID set (옵션). 제공되면 2.Consistency에
            'SwUDS↔SwUTS 함수 ID 매핑' row 5 추가 + incomplete_sheets에서 partial 라벨 제거.

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

    warnings: list[str] = []
    wb: Workbook = openpyxl.load_workbook(io.BytesIO(template_bytes), data_only=False)
    sheet_names = wb.sheetnames

    agg = aggregate_session(session)

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
    }

    # Cover
    cover_ws = next((wb[n] for n in sheet_names if n.lower() == "cover"), None)
    if cover_ws is None:
        warnings.append("Cover 시트 미발견 — Doc ID/Author 등 미기록")
    else:
        _write_cover_sheet(cover_ws, meta, out_warnings=warnings)

    # Test Summary
    ts_ws = next((wb[n] for n in sheet_names if n.lower() == "test summary"), None)
    if ts_ws is None:
        warnings.append("Test Summary 시트 미발견")
    else:
        _write_test_summary_sheet(ts_ws, meta, agg, out_warnings=warnings)

    # 3. Coverage
    cov_ws = next((wb[n] for n in sheet_names
                   if "coverage" in n.lower() and "traceability" not in n.lower()
                   and "consistency" not in n.lower()), None)
    if cov_ws is None:
        warnings.append("3.Coverage 시트 미발견")
    else:
        n_written = _write_coverage_sheet(cov_ws, agg)
        summary["coverage_rows_written"] = n_written

    # 1.Traceability — T133 본격 작성 (TC×Function 매트릭스)
    incomplete_sheets: list[str] = []
    trace_ws = next((wb[n] for n in sheet_names if "traceability" in n.lower()), None)
    if trace_ws is None:
        warnings.append("1.Traceability 시트 미발견")
    else:
        n_o = _write_traceability_sheet(trace_ws, session, out_warnings=warnings)
        summary["traceability_o_cells"] = n_o
        if n_o == 0:
            incomplete_sheets.append("1.Traceability")

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
            incomplete_sheets.append("2.Consistency (SwUDS 비교 partial — v3.02)")
    else:
        warnings.append("2.Consistency 시트 미발견")
        incomplete_sheets.append("2.Consistency")

    # History — T134 git log 자동 채움
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
