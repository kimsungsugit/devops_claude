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
from dataclasses import dataclass, field
from typing import Any

try:
    import openpyxl
    from openpyxl.workbook.workbook import Workbook
except ImportError:  # pragma: no cover
    openpyxl = None  # type: ignore[assignment]

from backend.services.excel_template_utils import (
    collect_git_history,
    find_kv_row,
    has_vba_macros,
    inspect_vba_refs,
    safe_write,
    short_date,
    truncate_cell_text,
    validate_build_meta,
    validate_xlsx_template_bytes,
    write_value_after_label,
)
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


def _write_cover(ws, meta: SutrBuildMeta, out_warnings: list[str] | None = None) -> None:
    _write_label(ws, "Project", meta.project_full_name, out_warnings)
    _write_label(ws, "ASIL Level", meta.asil_level, out_warnings)
    _write_label(ws, "Status", "DRAFT — PENDING REVIEW", out_warnings)
    _write_label(ws, "Validation Date", meta.validation_date, out_warnings)
    _write_label(ws, "Author", meta.author, out_warnings)
    _write_label(ws, "Approver", meta.approver, out_warnings)
    if meta.doc_id_sequence:
        _write_label(ws, "Doc. ID", f"{meta.doc_id_base}-{meta.doc_id_sequence}", out_warnings)
    _write_label(ws, "Version", f"v{meta.release_sw_version}", out_warnings)
    # optional — 회사 v3.01 template에 라벨이 없을 수 있어 silent skip 허용.
    _write_label(ws, "Build Timestamp", meta.build_timestamp, out_warnings)


def _write_test_summary(
    ws, meta: SutrBuildMeta, agg: dict[str, Any],
    out_warnings: list[str] | None = None,
) -> None:
    _write_label(ws, "Project Name", meta.project_full_name, out_warnings)
    _write_label(ws, "Release Name(SW)", meta.release_sw_version, out_warnings)
    _write_label(ws, "Test Target Version(HW)", meta.hw_version, out_warnings)
    _write_label(ws, "Test Date", meta.test_date, out_warnings)
    _write_label(ws, "Test Engineer", meta.test_engineer, out_warnings)
    _write_label(ws, "Target Coverage", meta.target_coverage, out_warnings)
    # deep-reviewer X7: 0/N의 silent wrong-pick 회피 — N=0이면 "N/A" 명시.
    actual_cov = agg["tested"] / agg["total"] if agg["total"] > 0 else "N/A"
    _write_label(ws, "Actual Coverage", actual_cov, out_warnings)
    _write_label(ws, "Target Pass ratio", meta.target_pass_ratio, out_warnings)
    actual_pass = agg["passed"] / agg["tested"] if agg["tested"] > 0 else "N/A"
    _write_label(ws, "Actual Pass ratio", actual_pass, out_warnings)
    _write_label(ws, "Final Test Result", meta.final_test_result, out_warnings)


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


def _write_test_log(ws, session: SwUTSession) -> int:
    """Test Log 시트 — TC별 input/expected/actual/pass.

    회사 표준 layout (TC ID / Title / Method / Unit / Total + pass/fail) 단순화:
    각 환경 / 각 TC 단위 한 행씩.
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

    written = 0
    for env in session.environments:
        for tc_name, _tc_list in sorted(env.test_cases.items()):
            r = start_row + written
            safe_write(ws, r, col, tc_name)
            safe_write(ws, r, col + 1, env.component_name)
            safe_write(ws, r, col + 2, "AEC, ABV")
            exec_r = env.test_results.get(tc_name)
            safe_write(
                ws, r, col + 3,
                "Pass" if exec_r and exec_r.passed else "Fail" if exec_r else "N/A",
            )
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

    warnings: list[str] = []
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
    summary = {
        "environments": len(session.environments),
        "total": agg["total"],
        "tested": agg["tested"],
        "passed": agg["passed"],
        "failed": agg["failed"],
        "deviation_cases_written": 0,
        "test_log_rows_written": 0,
    }

    cover_ws = next((wb[n] for n in sheet_names if n.lower() == "cover"), None)
    if cover_ws is None:
        warnings.append("Cover 시트 미발견")
    else:
        _write_cover(cover_ws, meta, out_warnings=warnings)

    ts_ws = next((wb[n] for n in sheet_names if n.lower() == "test summary"), None)
    if ts_ws is None:
        warnings.append("Test Summary 시트 미발견")
    else:
        _write_test_summary(ts_ws, meta, agg, out_warnings=warnings)

    dev_ws = next((wb[n] for n in sheet_names if n.lower() == "deviation"), None)
    if dev_ws is None:
        warnings.append("Deviation 시트 미발견")
    elif deviation_cases:
        n = _write_deviation(dev_ws, deviation_cases, out_warnings=warnings)
        summary["deviation_cases_written"] = n

    log_ws = next((wb[n] for n in sheet_names if n.lower() == "test log"), None)
    if log_ws is None:
        warnings.append("Test Log 시트 미발견")
    else:
        n = _write_test_log(log_ws, session)
        summary["test_log_rows_written"] = n

    incomplete_sheets: list[str] = []
    # T134: History 시트 git log 자동
    hist_ws = next((wb[n] for n in sheet_names if n.lower() == "history"), None)
    if hist_ws is not None:
        from backend.services.swut_coverage_aggregator import _write_history_sheet
        git_rows = collect_git_history(limit=10)
        if git_rows:
            n_h = _write_history_sheet(hist_ws, git_rows, out_warnings=warnings)
            summary["history_rows_written"] = n_h
            if n_h == 0:
                incomplete_sheets.append("History")
        else:
            warnings.append("git log 가져오기 실패 — History 시트 placeholder")
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
