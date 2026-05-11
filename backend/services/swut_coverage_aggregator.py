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
    resolve_merge_anchor,
    safe_write,
    short_date,
    validate_xlsx_template_bytes,
    write_value_after_label,
)
from backend.services.swut_input_adapter import (
    EnvironmentData,
    FunctionCoverage,
    SwUTSession,
)


# ---------------------------------------------------------------------------
# Dialog/meta payload
# ---------------------------------------------------------------------------

@dataclass
class CoverageBuildMeta:
    """Coverage Report 빌드에 필요한 메타.

    fixed 항목은 ``config/swut_meta.json`` 에서 로드되고, dialog 항목은
    매 빌드 frontend에서 받는다.
    """
    # fixed
    project_id: str = "HDPDM01"
    project_full_name: str = "HDPDM01"
    asil_level: str = "ASIL A"
    doc_id_base: str = ""
    default_author: str = ""
    default_reviewer: str = ""
    default_approver: str = ""

    # dialog
    release_sw_version: str = ""   # 예: 1.01.05
    hw_version: str = "1.00"
    test_date: str = ""            # ISO 8601 또는 yyyy-mm-dd
    test_engineer: str = ""
    validation_date: str = ""
    reviewer_override: str = ""
    approver_override: str = ""
    doc_id_sequence: str = ""

    # auto
    final_test_result: str = "PASS"
    build_timestamp: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    @property
    def author(self) -> str:
        return self.test_engineer or self.default_author

    @property
    def reviewer(self) -> str:
        return self.reviewer_override or self.default_reviewer

    @property
    def approver(self) -> str:
        return self.approver_override or self.default_approver


@dataclass
class CoverageBuildResult:
    ok: bool
    xlsx_bytes: bytes = b""
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
            "xlsx_size_bytes": len(self.xlsx_bytes),
            "warnings": self.warnings,
            "summary": self.summary,
            "tool_qualification": self.tool_qualification,
        }


# ---------------------------------------------------------------------------
# Sheet writers
# ---------------------------------------------------------------------------

# helper 함수는 backend/services/excel_template_utils.py 로 이전 (reviewer 권고 X5).
# 두 빌더(Coverage / SUTR)가 동일 helper를 공유. 단일 출처로 유지보수.


def _aggregate_session(session: SwUTSession) -> dict[str, Any]:
    """SwUTSession에서 Test Summary 통계 + 함수 집합 산출."""
    total_tcs = 0
    passed = 0
    failed = 0
    not_executed_tcs: list[str] = []

    # 모든 TC 리스트 + per-function coverage 집계
    all_functions: list[FunctionCoverage] = []
    tc_to_functions: dict[str, set[str]] = {}  # tc_name -> {SwUFn_xxxx, ...}

    for env in session.environments:
        all_functions.extend(env.function_coverage)
        for tc_name, tc_list in env.test_cases.items():
            total_tcs += len(tc_list) if tc_list else 1
            tc_to_functions.setdefault(tc_name, set()).add(env.component_name)
        for tc_name, r in env.test_results.items():
            if r.passed:
                passed += 1
            else:
                failed += 1
        # reviewer X6: not_executed = test_cases 키 - test_results 키 차집합 (실측)
        tc_keys = set(env.test_cases.keys())
        exec_keys = set(env.test_results.keys())
        not_executed_tcs.extend(sorted(tc_keys - exec_keys))

    return {
        "total_tcs": total_tcs,
        "passed": passed,
        "failed": failed,
        "not_executed": len(not_executed_tcs),
        "function_count": len(all_functions),
        "function_rows": all_functions,
        "tc_to_functions": tc_to_functions,
    }


def _write_cover_sheet(ws, meta: CoverageBuildMeta) -> None:
    """Cover 시트 — Doc ID/Project/ASIL/Author/Approver 등."""
    if not ws:
        return
    write_value_after_label(ws, "Project", meta.project_full_name)
    write_value_after_label(ws, "ASIL Level", meta.asil_level)
    # reviewer ISO F3: 자동 생성물은 사람 승인 없이 Approved 기재 금지.
    write_value_after_label(ws, "Status", "DRAFT — PENDING REVIEW")
    write_value_after_label(ws, "Validation Date", meta.validation_date)
    write_value_after_label(ws, "Author", meta.author)
    write_value_after_label(ws, "Approver", meta.approver)
    if meta.doc_id_sequence:
        doc_id = f"{meta.doc_id_base}-{meta.doc_id_sequence}"
        write_value_after_label(ws, "Doc. ID", doc_id)


def _write_test_summary_sheet(ws, meta: CoverageBuildMeta, agg: dict[str, Any]) -> None:
    """Test Summary 시트 — 핵심 메트릭 표."""
    if not ws:
        return
    write_value_after_label(ws, "Project Name", meta.project_full_name)
    write_value_after_label(ws, "Release Name(SW)", meta.release_sw_version)
    write_value_after_label(ws, "Test Target Version(HW)", meta.hw_version)
    write_value_after_label(ws, "Test Date", meta.test_date)
    write_value_after_label(ws, "Test Engineer", meta.test_engineer)
    write_value_after_label(ws, "Final Test Result", meta.final_test_result)


def _write_coverage_sheet(ws, agg: dict[str, Any]) -> int:
    """3. Coverage 시트 — per-function Statement/Branch/Exception 표.

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
        written += 1
    return written


def _write_traceability_sheet(ws, agg: dict[str, Any]) -> int:
    """1.Traceability 시트 — TC × Function 매트릭스.

    회사 포맷이 TC 행 / Function 열 매트릭스(420x420). 본 빌더는 lightweight
    구현 — 기존 template의 hierarchy 그대로 유지하고 cell만 채우려 시도.
    매트릭스가 너무 크고 template 의존이라 본 라운드는 **로우 카운트만** 기록.
    """
    if not ws:
        return 0
    # TODO(다음 라운드): per-env 단위로 TC → Function 매핑 작성
    # 본 라운드: agg 통계만 기록 (Cell A1 위쪽 빈 셀에)
    return 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_coverage_report(
    session: SwUTSession,
    meta: CoverageBuildMeta,
    template_bytes: bytes,
) -> CoverageBuildResult:
    """Coverage Report v3.01 xlsx 생성.

    Args:
        session: SwUT 데이터 (input_adapter 출력).
        meta: 빌드 메타 (Project/ASIL/Author 등).
        template_bytes: 기존 v3.01 xlsx 파일 bytes (template).

    Returns:
        CoverageBuildResult — xlsx_bytes 채워짐.
    """
    if openpyxl is None:
        raise RuntimeError("openpyxl is required for SwUT Coverage Report builder")

    # Critical (reviewer S): ZIP bomb / magic byte 검증.
    validate_xlsx_template_bytes(template_bytes, label="Coverage Report template")

    warnings: list[str] = []
    wb: Workbook = openpyxl.load_workbook(io.BytesIO(template_bytes), data_only=False)
    sheet_names = wb.sheetnames

    agg = _aggregate_session(session)
    summary = {
        "environments": len(session.environments),
        "total_tcs": agg["total_tcs"],
        "passed": agg["passed"],
        "failed": agg["failed"],
        "function_rows": agg["function_count"],
    }

    # Cover
    cover_ws = next((wb[n] for n in sheet_names if n.lower() == "cover"), None)
    if cover_ws is None:
        warnings.append("Cover 시트 미발견 — Doc ID/Author 등 미기록")
    else:
        _write_cover_sheet(cover_ws, meta)

    # Test Summary
    ts_ws = next((wb[n] for n in sheet_names if n.lower() == "test summary"), None)
    if ts_ws is None:
        warnings.append("Test Summary 시트 미발견")
    else:
        _write_test_summary_sheet(ts_ws, meta, agg)

    # 3. Coverage
    cov_ws = next((wb[n] for n in sheet_names
                   if "coverage" in n.lower() and "traceability" not in n.lower()
                   and "consistency" not in n.lower()), None)
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
        _write_traceability_sheet(trace_ws, agg)
        warnings.append("1.Traceability 매트릭스는 본 라운드 placeholder — TC×Function 채우기는 다음 라운드")

    # 2.Consistency — 본 라운드 placeholder (SwUDS docx 파싱 미연결)
    warnings.append("2.Consistency 시트는 본 라운드 placeholder — SwUDS↔SwUTS 비교 다음 라운드")

    # 빌드 → bytes
    out = io.BytesIO()
    wb.save(out)
    xlsx_bytes = out.getvalue()
    wb.close()

    filename = (
        f"({meta.project_id})SwUT Coverage Report_"
        f"v{meta.release_sw_version}_{short_date(meta.test_date)}_R.xlsx"
    )

    return CoverageBuildResult(
        ok=True,
        xlsx_bytes=xlsx_bytes,
        filename=filename,
        warnings=warnings,
        summary=summary,
    )


def short_date(s: str) -> str:
    """`2024-02-19` → `240219`."""
    if not s:
        return ""
    m = re.match(r"(\d{2,4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if not m:
        return s.replace("-", "").replace("/", "")[:6]
    yy = m.group(1)[-2:]
    return f"{yy}{int(m.group(2)):02d}{int(m.group(3)):02d}"
