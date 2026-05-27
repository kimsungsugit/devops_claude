"""SwUTS / SwITS xlsm parser 단위 테스트 (60차 F6-A).

합성 xlsm으로 양식 시뮬레이션 + parse_swuts_xlsm 검증. 라이브 검증은
``.codex_tmp/round_60_local_build/sanity_parse_swuts.py``에서 별도 수행.
"""
from __future__ import annotations

import io
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.swuts_excel_parser import (  # noqa: E402
    XLSM_MAX_BYTES,
    parse_swuts_xlsm,
)


def _build_swuts_xlsm(
    sheet_name: str = "2.SW Unit Test Spec",
    *,
    headers: list[str] | None = None,
    data_rows: list[list[str | None]] | None = None,
    header_row: int = 4,
) -> bytes:
    """합성 xlsm — Hyundai SwUTS 양식 시뮬레이션.

    Args:
        sheet_name: TC 시트명 (정규식 매칭 대상). default = KJPDS02 형식.
        headers: header_row에 stamp할 라벨 list (1-based col 순서).
        data_rows: header 다음 row부터 stamp할 data row list.
        header_row: header가 위치할 row (1-based).
    """
    from openpyxl import Workbook  # type: ignore

    wb = Workbook()
    # 기본 'Sheet' 삭제 + TC 시트 추가 (시트명 정확 매칭 위해)
    default_sheet = wb.active
    if default_sheet is not None:
        wb.remove(default_sheet)
    ws = wb.create_sheet(sheet_name)

    if headers:
        for col_idx, label in enumerate(headers, 1):
            ws.cell(header_row, col_idx).value = label

    if data_rows:
        for r_idx, row in enumerate(data_rows, header_row + 1):
            for col_idx, val in enumerate(row, 1):
                if val is not None:
                    ws.cell(r_idx, col_idx).value = val

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestSwUTSExcelParser:
    def test_empty_bytes_returns_ok_false(self):
        result = parse_swuts_xlsm(b"")
        assert not result.ok
        assert any("비어있음" in w for w in result.parse_warnings)

    def test_oversize_rejected(self):
        oversized = b"x" * (XLSM_MAX_BYTES + 1)
        result = parse_swuts_xlsm(oversized)
        assert not result.ok
        assert any("DoS 방지" in w for w in result.parse_warnings)

    def test_kjpds02_swuts_format_basic(self):
        """KJPDS02 SwUTS v1.01 양식 — TC_ID 4자리 (SwUTC_0121) + 헤더 row 4."""
        xlsm = _build_swuts_xlsm(
            sheet_name="2.SW Unit Test Spec",
            headers=[
                "Index", "TC_ID", "Unit", "Test Method",
                "Test Case Generation Method",
            ],
            data_rows=[
                # TC 메타 row (sub-TC index col 비움)
                ["1", "SwUTC_0121", "s_safe_rotr", None, None],
                # sub-TC row (TC_ID 비우고 method 채움)
                ["1", None, "s_safe_rotr", "REQ", "ABV"],
                ["1", None, "s_safe_rotr", "REQ", "ABV"],
                ["2", "SwUTC_0122", "s_sha256_transform", None, None],
                ["2", None, "s_sha256_transform", "REQ", "ABV"],
            ],
        )
        result = parse_swuts_xlsm(xlsm)
        assert result.ok, result.parse_warnings
        assert len(result.entries) == 2  # sub-TC는 별도 entry 아님 (merge)
        e = result.by_tc_id["SwUTC_0121"]
        assert e.unit_name == "s_safe_rotr"
        assert e.test_method == "REQ"  # sub-TC row에서 merge
        assert e.generation_method == "ABV"
        # function_id KJPDS02 패턴 fallback (SwUTC_0121 → SwUFn_0121)
        assert e.function_id == "SwUFn_0121"

    def test_hdpdm01_suts_format_long_tcid(self):
        """HDPDM01 SUTS v3.01 양식 — TC_ID = SwUTC_SwUFn_0101 (long form).

        header에 'Test Case Generation Method' 라벨이 2 col (multiple col) 등장.
        실제 spec 데이터는 두 번째 col에만 있는 양식 (col 9 empty, col 12 채움).
        """
        xlsm = _build_swuts_xlsm(
            sheet_name="2.SW Unit Test Spec",
            header_row=6,
            headers=[
                "Component", "TC ID", "Name", "Description", "Safety Related",
                "Test Environment", "Test Method",
                "Test Case Generation Method",  # col 8 (첫 매칭)
                "Precondition",  # col 9
                "Sequence",      # col 10
                "Test Case Generation Method",  # col 11 (두 번째 매칭)
            ],
            data_rows=[
                # 메타 row + first sub-TC 데이터 일부
                [
                    "SwCom_01", "SwUTC_SwUFn_0101", "void main( void )",
                    "Main entry", None, None, None, None, None, "1",
                    "AEC, ABV",  # col 11 (실제 값) — col 8 (첫 매칭)은 비움
                ],
            ],
        )
        result = parse_swuts_xlsm(xlsm)
        assert result.ok, result.parse_warnings
        e = result.by_tc_id["SwUTC_SwUFn_0101"]
        # function_id 추출 — TC_ID에 SwUFn_ substring 있음
        assert e.function_id == "SwUFn_0101"
        # multiple col 매칭 — col 11이 nonempty라 채택
        assert e.generation_method == "AEC, ABV"

    def test_no_tc_sheets_returns_ok_false(self):
        """시트명에 'Unit Test Spec' / 'Integration Test Spec' 패턴 없으면 skip."""
        xlsm = _build_swuts_xlsm(
            sheet_name="Cover",  # 매칭 안 되는 시트명
            headers=["TC_ID", "Description"],
            data_rows=[["SwUTC_0101", "test"]],
        )
        result = parse_swuts_xlsm(xlsm)
        assert not result.ok
        assert any("TC 시트 미발견" in w for w in result.parse_warnings)

    def test_header_label_variants_normalized(self):
        """'TC ID' / 'TC_ID' / 'tc id' 모두 동일 라벨로 매칭."""
        xlsm = _build_swuts_xlsm(
            sheet_name="2.SW Unit Test Spec",
            headers=["tc id", "DESCRIPTION", "Pre-Condition"],
            data_rows=[["SwUTC_0001", "test description", "test pre"]],
        )
        result = parse_swuts_xlsm(xlsm)
        assert result.ok, result.parse_warnings
        e = result.by_tc_id["SwUTC_0001"]
        assert e.description == "test description"
        assert e.precondition == "test pre"
