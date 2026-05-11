"""Tests for backend.services.excel_template_utils."""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.excel_template_utils import (  # noqa: E402
    TemplateValidationError,
    find_kv_row,
    resolve_merge_anchor,
    safe_write,
    short_date,
    validate_xlsx_template_bytes,
    write_value_after_label,
)


def _minimal_xlsx_bytes() -> bytes:
    wb = openpyxl.Workbook()
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# validate_xlsx_template_bytes — Critical S (reviewer)
# ---------------------------------------------------------------------------

class TestValidateXlsxBytes:
    def test_valid_xlsx_passes(self):
        validate_xlsx_template_bytes(_minimal_xlsx_bytes())

    def test_empty_bytes_rejected(self):
        with pytest.raises(TemplateValidationError, match="empty"):
            validate_xlsx_template_bytes(b"")

    def test_bad_magic_rejected(self):
        with pytest.raises(TemplateValidationError, match="magic bytes"):
            validate_xlsx_template_bytes(b"NOT_AN_XLSX_FILE_AT_ALL_!!!")

    def test_truncated_zip_rejected(self):
        # PK 헤더만 있고 잘림
        with pytest.raises(TemplateValidationError, match="valid ZIP"):
            validate_xlsx_template_bytes(b"PK\x03\x04\x00\x00\x00\x00")

    def test_zip_without_office_structure_rejected(self):
        # 평범한 ZIP (Office XML 구조 없음)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "hello")
        with pytest.raises(TemplateValidationError, match="Open Office XML"):
            validate_xlsx_template_bytes(buf.getvalue())


# ---------------------------------------------------------------------------
# Helpers (parity with previous tests)
# ---------------------------------------------------------------------------

class TestShortDate:
    @pytest.mark.parametrize("inp,expected", [
        ("2024-02-19", "240219"),
        ("2024/02/19", "240219"),
        ("24-02-19", "240219"),
        ("", ""),
    ])
    def test_parse(self, inp, expected):
        assert short_date(inp) == expected


class TestFindKvRow:
    def test_finds_label(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["B3"] = "Project"
        ws["C3"] = "HDPDM01"
        pos = find_kv_row(ws, "Project")
        assert pos == (3, 2)

    def test_not_found_returns_none(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        assert find_kv_row(ws, "NonExistent") is None


class TestMergedCellHandling:
    def test_anchor_resolves_for_merged_cell(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["B2"] = "Project"
        ws.merge_cells("B2:C2")
        assert resolve_merge_anchor(ws, 2, 3) == (2, 2)  # C2 → anchor B2

    def test_anchor_passthrough_for_unmerged(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        assert resolve_merge_anchor(ws, 5, 5) == (5, 5)

    def test_write_value_after_merged_label(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["B2"] = "Project"
        ws.merge_cells("B2:C2")  # 라벨이 2 컬럼 머지
        assert write_value_after_label(ws, "Project", "HDPDM01")
        # 라벨 머지 영역 다음(D2)에 값 들어가야 함
        assert ws["D2"].value == "HDPDM01"

    def test_safe_write_silent_on_merged_non_anchor(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"] = "anchor"
        ws.merge_cells("A1:B1")
        # B1(머지된 non-anchor)에 쓰기 시도 → anchor로 보정되어 성공
        assert safe_write(ws, 1, 2, "X") is True
        assert ws["A1"].value == "X"  # anchor가 덮어쓰여짐
