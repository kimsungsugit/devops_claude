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

import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

try:
    import openpyxl
    from openpyxl.workbook.workbook import Workbook
except ImportError:  # pragma: no cover
    openpyxl = None  # type: ignore[assignment]

from backend.services.excel_template_utils import (
    find_kv_row,
    resolve_merge_anchor,
    safe_write,
    short_date,
    validate_xlsx_template_bytes,
    write_value_after_label,
)
from backend.services.swut_input_adapter import SwUTSession


@dataclass
class SutrBuildMeta:
    """SUTR 빌드 메타."""
    project_id: str = "HDPDM01"
    project_full_name: str = "HDPDM01"
    asil_level: str = "ASIL A"
    doc_id_base: str = "HDPDM01-SUTR"
    doc_id_sequence: str = ""
    default_author: str = ""
    default_reviewer: str = ""
    default_approver: str = ""

    release_sw_version: str = ""
    hw_version: str = "1.00"
    test_date: str = ""
    test_engineer: str = ""
    validation_date: str = ""
    reviewer_override: str = ""
    approver_override: str = ""

    target_coverage: float = 1.0
    target_pass_ratio: float = 1.0
    final_test_result: str = "OK"

    build_timestamp: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    @property
    def author(self) -> str:
        return self.test_engineer or self.default_author

    @property
    def approver(self) -> str:
        return self.approver_override or self.default_approver


@dataclass
class SutrBuildResult:
    ok: bool
    xlsm_bytes: bytes = b""
    filename: str = ""
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    tool_qualification: dict[str, Any] = field(
        default_factory=lambda: {
            "evidence_class": "auto-generated draft",
            "asil_a_usage": "reviewer 승인 후 evidence로 사용 가능",
            "asil_b_c_d_usage": "단독 evidence 사용 금지 — manual review 의무",
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "filename": self.filename,
            "xlsm_size_bytes": len(self.xlsm_bytes),
            "warnings": self.warnings,
            "summary": self.summary,
            "tool_qualification": self.tool_qualification,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# helper 함수는 backend/services/excel_template_utils.py 로 통합 (reviewer 권고 X5).


def _aggregate(session: SwUTSession) -> dict[str, Any]:
    total = 0
    tested = 0
    passed = 0
    failed = 0
    failed_tcs: list[tuple[str, str]] = []  # (env, tc_name)

    for env in session.environments:
        for tc_name, tc_list in env.test_cases.items():
            total += len(tc_list) if tc_list else 1
        for tc_name, r in env.test_results.items():
            tested += 1
            if r.passed:
                passed += 1
            else:
                failed += 1
                failed_tcs.append((env.env_name, tc_name))

    return {
        "total": total,
        "tested": tested,
        "passed": passed,
        "failed": failed,
        "failed_tcs": failed_tcs,
        "deviated": 0,  # 본 라운드 미연결 (deviation_generator)
        "not_executed": max(total - tested, 0),
    }


# ---------------------------------------------------------------------------
# Sheet writers
# ---------------------------------------------------------------------------

def _write_cover(ws, meta: SutrBuildMeta) -> None:
    write_value_after_label(ws, "Project", meta.project_full_name)
    write_value_after_label(ws, "ASIL Level", meta.asil_level)
    write_value_after_label(ws, "Status", "DRAFT — PENDING REVIEW")
    write_value_after_label(ws, "Validation Date", meta.validation_date)
    write_value_after_label(ws, "Author", meta.author)
    write_value_after_label(ws, "Approver", meta.approver)
    if meta.doc_id_sequence:
        write_value_after_label(ws, "Doc. ID", f"{meta.doc_id_base}-{meta.doc_id_sequence}")
    write_value_after_label(ws, "Version", f"v{meta.release_sw_version}")


def _write_test_summary(ws, meta: SutrBuildMeta, agg: dict[str, Any]) -> None:
    write_value_after_label(ws, "Project Name", meta.project_full_name)
    write_value_after_label(ws, "Release Name(SW)", meta.release_sw_version)
    write_value_after_label(ws, "Test Target Version(HW)", meta.hw_version)
    write_value_after_label(ws, "Test Date", meta.test_date)
    write_value_after_label(ws, "Test Engineer", meta.test_engineer)
    write_value_after_label(ws, "Target Coverage", meta.target_coverage)
    write_value_after_label(ws, "Actual Coverage", agg["tested"] / max(agg["total"], 1))
    write_value_after_label(ws, "Target Pass ratio", meta.target_pass_ratio)
    write_value_after_label(ws, "Actual Pass ratio", agg["passed"] / max(agg["tested"], 1))
    write_value_after_label(ws, "Final Test Result", meta.final_test_result)


def _write_deviation(ws, deviation_cases: list[Any]) -> int:
    """Deviation 시트 — swut_deviation_generator 결과 기록.

    Returns: 쓰여진 행 수.
    """
    if not deviation_cases:
        return 0
    # 헤더 위치
    pos = find_kv_row(ws, "Test Case ID", max_row=10)
    if pos is None:
        return 0
    start_row = pos[0] + 1
    written = 0
    for i, case in enumerate(deviation_cases):
        r = start_row + i
        # case는 DeviationCase dataclass (또는 dict)
        if isinstance(case, dict):
            tc_id_v = case.get("tc_id", "")
            tc_no_v = case.get("tc_no", "")
            tc_label = f"{tc_id_v} ({tc_no_v})" if tc_no_v else tc_id_v
            issue = case.get("issue_text", "")
            rationale = case.get("auto_rationale", "")
        else:
            tc_label = f"{case.tc_id} ({case.tc_no})" if case.tc_no else case.tc_id
            issue = case.issue_text
            rationale = case.auto_rationale or ""
        status = "Auto-Generated"
        safe_write(ws, r, pos[1], tc_label)
        safe_write(ws, r, pos[1] + 1, issue)
        safe_write(ws, r, pos[1] + 2, rationale)
        safe_write(ws, r, pos[1] + 3, status)
        written += 1
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
) -> SutrBuildResult:
    """SUTR v3.01 xlsm 생성.

    Args:
        session: input_adapter 출력.
        meta: 빌드 메타.
        template_bytes: 기존 v3.01 xlsm 파일 bytes.
        deviation_cases: swut_deviation_generator 결과 (None이면 빈 Deviation 시트).
    """
    if openpyxl is None:
        raise RuntimeError("openpyxl is required for SwUT SUTR builder")

    # Critical (reviewer S): ZIP bomb / magic byte 검증.
    validate_xlsx_template_bytes(template_bytes, label="SUTR template")

    warnings: list[str] = []
    # keep_vba=True — .xlsm 매크로 보존
    wb: Workbook = openpyxl.load_workbook(
        io.BytesIO(template_bytes), keep_vba=True, data_only=False,
    )
    sheet_names = wb.sheetnames

    agg = _aggregate(session)
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
        _write_cover(cover_ws, meta)

    ts_ws = next((wb[n] for n in sheet_names if n.lower() == "test summary"), None)
    if ts_ws is None:
        warnings.append("Test Summary 시트 미발견")
    else:
        _write_test_summary(ts_ws, meta, agg)

    dev_ws = next((wb[n] for n in sheet_names if n.lower() == "deviation"), None)
    if dev_ws is None:
        warnings.append("Deviation 시트 미발견")
    elif deviation_cases:
        n = _write_deviation(dev_ws, deviation_cases)
        summary["deviation_cases_written"] = n

    log_ws = next((wb[n] for n in sheet_names if n.lower() == "test log"), None)
    if log_ws is None:
        warnings.append("Test Log 시트 미발견")
    else:
        n = _write_test_log(log_ws, session)
        summary["test_log_rows_written"] = n

    warnings.append("History 시트는 본 라운드 placeholder — git log 자동 연동 다음 라운드")

    out = io.BytesIO()
    wb.save(out)
    xlsm_bytes = out.getvalue()
    wb.close()

    filename = (
        f"({meta.project_id}_SUTR) Software Unit Test Result_"
        f"v{meta.release_sw_version}_{short_date(meta.test_date)}_R.xlsm"
    )

    return SutrBuildResult(
        ok=True,
        xlsm_bytes=xlsm_bytes,
        filename=filename,
        warnings=warnings,
        summary=summary,
    )


def short_date(s: str) -> str:
    if not s:
        return ""
    m = re.match(r"(\d{2,4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if not m:
        return s.replace("-", "").replace("/", "")[:6]
    yy = m.group(1)[-2:]
    return f"{yy}{int(m.group(2)):02d}{int(m.group(3)):02d}"
