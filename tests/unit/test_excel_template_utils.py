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
    BLANK_MARKUP,
    BuildMetaValidationError,
    TemplateValidationError,
    find_kv_row,
    resolve_merge_anchor,
    safe_write,
    sheet_is_blank_placeholder,
    short_date,
    validate_build_meta,
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


class TestValidateBuildMeta:
    """deep-reviewer X3: 빌더 입력 메타 검증."""

    def test_valid_meta_passes(self):
        validate_build_meta("1.01.05", "2024-02-19")
        validate_build_meta("2.02", "2024/02/19")

    def test_empty_release_rejected(self):
        with pytest.raises(BuildMetaValidationError, match="release_sw_version is empty"):
            validate_build_meta("", "2024-02-19")
        with pytest.raises(BuildMetaValidationError, match="release_sw_version is empty"):
            validate_build_meta("   ", "2024-02-19")

    def test_invalid_release_format_rejected(self):
        with pytest.raises(BuildMetaValidationError, match="형식 미충족"):
            validate_build_meta("v1.01.05", "2024-02-19")
        with pytest.raises(BuildMetaValidationError, match="형식 미충족"):
            validate_build_meta("1.x.05", "2024-02-19")

    def test_empty_date_rejected(self):
        with pytest.raises(BuildMetaValidationError, match="test_date is empty"):
            validate_build_meta("1.01.05", "")

    def test_invalid_date_format_rejected(self):
        with pytest.raises(BuildMetaValidationError, match="형식 미충족"):
            validate_build_meta("1.01.05", "Feb 19 2024")

    def test_test_engineer_with_newline_rejected(self):
        """5차 H1 Critical: 줄바꿈 포함 이름 거부 (xlsx 셀 깨짐 방지)."""
        with pytest.raises(BuildMetaValidationError, match="줄바꿈"):
            validate_build_meta("1.0.0", "2024-02-19", test_engineer="X\nY")

    def test_test_engineer_too_long_rejected(self):
        with pytest.raises(BuildMetaValidationError, match="길이"):
            validate_build_meta("1.0.0", "2024-02-19", test_engineer="A" * 101)

    def test_doc_id_sequence_non_digit_rejected(self):
        """5차 H2 Warning: doc_id_sequence digit만 허용."""
        with pytest.raises(BuildMetaValidationError, match="doc_id_sequence"):
            validate_build_meta("1.0.0", "2024-02-19", doc_id_sequence="abc")

    def test_doc_id_sequence_empty_ok(self):
        validate_build_meta("1.0.0", "2024-02-19", doc_id_sequence="")
        validate_build_meta("1.0.0", "2024-02-19", doc_id_sequence="851")


class TestTruncateCellText:
    """5차 H3 Critical: xlsx 셀 한도 방어 truncate."""

    def test_short_text_unchanged(self):
        from backend.services.excel_template_utils import truncate_cell_text
        s, truncated = truncate_cell_text("hello")
        assert s == "hello"
        assert truncated is False

    def test_long_text_truncated(self):
        from backend.services.excel_template_utils import truncate_cell_text
        long = "A" * 5000
        s, truncated = truncate_cell_text(long)
        assert truncated is True
        assert len(s) <= 2050  # 2000 + " …(truncated)" 마진
        assert s.endswith("…(truncated)")

    def test_none_returns_empty(self):
        from backend.services.excel_template_utils import truncate_cell_text
        s, truncated = truncate_cell_text(None)
        assert s == ""
        assert truncated is False


class TestSheetIsBlankPlaceholder:
    """deep-reviewer 시나리오 A: placeholder 시트 감지."""

    def test_detects_blank_markup_in_a1(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"] = BLANK_MARKUP
        assert sheet_is_blank_placeholder(ws) is True

    def test_no_blank_markup_returns_false(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"] = "Normal data here"
        assert sheet_is_blank_placeholder(ws) is False

    def test_none_sheet_returns_false(self):
        assert sheet_is_blank_placeholder(None) is False


# ---------------------------------------------------------------------------
# 23차 T192/T194: 시각 강조 헬퍼 회귀
# ---------------------------------------------------------------------------

class TestVisualMarkers23:
    """사용자 입력 필요 (노란) / FAIL (빨강) 시각 강조 회귀."""

    def test_mark_user_input_required_writes_placeholder_and_fill(self):
        from backend.services.excel_template_utils import (
            mark_user_input_required, USER_INPUT_PLACEHOLDER,
        )
        wb = openpyxl.Workbook()
        ws = wb.active
        result = mark_user_input_required(ws, 2, 3, hint="Approver 이름")
        assert result is True
        cell = ws.cell(2, 3)
        assert cell.value.startswith(USER_INPUT_PLACEHOLDER)
        assert "Approver 이름" in cell.value
        assert cell.fill.fill_type == "solid"
        assert "FFEB9C" in str(cell.fill.fgColor.rgb).upper()

    def test_mark_user_input_required_no_hint(self):
        from backend.services.excel_template_utils import mark_user_input_required
        wb = openpyxl.Workbook()
        ws = wb.active
        mark_user_input_required(ws, 1, 1)
        assert "▶ 사용자 입력 필요" in ws.cell(1, 1).value
        assert "—" not in ws.cell(1, 1).value  # hint 없을 때 separator 없음

    def test_write_value_or_mark_writes_when_value_present(self):
        from backend.services.excel_template_utils import write_value_or_mark
        wb = openpyxl.Workbook()
        ws = wb.active
        result = write_value_or_mark(ws, 1, 1, "JK Kim", hint="ignored")
        assert result is True
        assert ws.cell(1, 1).value == "JK Kim"

    def test_write_value_or_mark_marks_when_value_empty(self):
        from backend.services.excel_template_utils import write_value_or_mark
        wb = openpyxl.Workbook()
        ws = wb.active
        result = write_value_or_mark(ws, 1, 1, "", hint="hint here")
        assert result is False  # marked, not written
        assert "▶ 사용자 입력 필요" in ws.cell(1, 1).value
        assert "FFEB9C" in str(ws.cell(1, 1).fill.fgColor.rgb).upper()

    def test_mark_fail_cell_applies_red_fill_and_preserves_value(self):
        from backend.services.excel_template_utils import mark_fail_cell
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(1, 1).value = "FAIL"
        result = mark_fail_cell(ws, 1, 1)
        assert result is True
        assert "FFC7CE" in str(ws.cell(1, 1).fill.fgColor.rgb).upper()
        # value 보존 — 색칠이 텍스트 reset 하지 않음
        assert ws.cell(1, 1).value == "FAIL"

    def test_write_label_or_mark_finds_label_and_marks_empty(self):
        from backend.services.excel_template_utils import write_label_or_mark
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A4"] = "Validation Date"
        ws["B4"] = "(placeholder)"
        out_warnings: list[str] = []
        result = write_label_or_mark(
            ws, "Validation Date", value="", hint="yyyy-mm-dd",
            optional_labels={"Reviewer"}, out_warnings=out_warnings,
        )
        assert result is False  # 빈 value → 노란 mark
        assert "▶ 사용자 입력 필요" in ws.cell(4, 2).value
        assert "yyyy-mm-dd" in ws.cell(4, 2).value
        assert "FFEB9C" in str(ws.cell(4, 2).fill.fgColor.rgb).upper()

    def test_write_label_or_mark_writes_when_value_present(self):
        from backend.services.excel_template_utils import write_label_or_mark
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"] = "Author"
        out_warnings: list[str] = []
        result = write_label_or_mark(
            ws, "Author", value="JK Kim", hint="이름",
            optional_labels=None, out_warnings=out_warnings,
        )
        assert result is True  # value 있음
        assert ws.cell(1, 2).value == "JK Kim"
        assert out_warnings == []

    def test_write_label_or_mark_skips_optional_label_warning(self):
        from backend.services.excel_template_utils import write_label_or_mark
        wb = openpyxl.Workbook()
        ws = wb.active
        out_warnings: list[str] = []
        write_label_or_mark(
            ws, "Reviewer", value="someone", hint="",
            optional_labels={"Reviewer"}, out_warnings=out_warnings,
        )
        assert out_warnings == []  # optional 라벨이라 미발견 silent

    def test_write_label_or_mark_warns_non_optional_label_missing(self):
        from backend.services.excel_template_utils import write_label_or_mark
        wb = openpyxl.Workbook()
        ws = wb.active
        out_warnings: list[str] = []
        write_label_or_mark(
            ws, "Validation Date", value="2024-02-19", hint="",
            optional_labels={"Reviewer"}, out_warnings=out_warnings,
        )
        assert any("Validation Date" in w for w in out_warnings)

    def test_mark_handles_merged_cell_anchor(self):
        """머지셀 비-anchor 위치 호출 → anchor 셀에 mark."""
        from backend.services.excel_template_utils import mark_user_input_required
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.merge_cells("B2:D2")
        mark_user_input_required(ws, 2, 4, hint="merged")  # D2 → anchor B2
        assert ws.cell(2, 2).value is not None
        assert "▶ 사용자 입력 필요" in ws.cell(2, 2).value

    def test_design_tokens_single_source_29w17(self):
        """29차 W17: excel_template_utils가 design_tokens에서 RGB를 import."""
        from backend.services import design_tokens
        from backend.services.excel_template_utils import (
            _FAIL_FILL_RGB,
            _USER_INPUT_FILL_RGB,
            USER_INPUT_PLACEHOLDER,
        )

        # 동일 객체(=Final 상수)를 가리키는지 확인 — 단일 출처 보장
        assert _USER_INPUT_FILL_RGB == design_tokens.USER_INPUT_FILL_RGB
        assert _FAIL_FILL_RGB == design_tokens.FAIL_FILL_RGB
        assert USER_INPUT_PLACEHOLDER == design_tokens.USER_INPUT_PLACEHOLDER

        # 값 자체도 회귀 — audit 정책 RGB 변경 시 본 테스트가 실패해야 함
        assert _USER_INPUT_FILL_RGB == "FFFFEB9C"
        assert _FAIL_FILL_RGB == "FFFFC7CE"
        assert USER_INPUT_PLACEHOLDER == "▶ 사용자 입력 필요"


class TestAsilDMarker21:
    """30차 W21: mark_asil_d_function — ASIL D 함수 row 빨간 강조."""

    def test_mark_asil_d_applies_red_fill(self):
        from backend.services.excel_template_utils import mark_asil_d_function
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(1, 1).value = "SwUFn_0103"
        result = mark_asil_d_function(ws, 1, 1)
        assert result is True
        # RGB는 ASIL_D_FILL_RGB (= FAIL_FILL_RGB와 동일 값)
        assert "FFC7CE" in str(ws.cell(1, 1).fill.fgColor.rgb).upper()
        # value 보존 — 색칠이 함수 ID reset 하지 않음
        assert ws.cell(1, 1).value == "SwUFn_0103"

    def test_asil_d_and_fail_share_same_rgb(self):
        """30차 W21: ASIL D / FAIL은 동일 RGB이나 의미 분리.

        design_tokens에서 두 상수가 같은 값을 가리키는지 검증 — 변경 시
        본 테스트가 실패해야 정책 동기 의무 인지.
        """
        from backend.services import design_tokens
        assert design_tokens.ASIL_D_FILL_RGB == design_tokens.FAIL_FILL_RGB

    def test_mark_asil_d_handles_merged_cell_anchor(self):
        """머지셀 비-anchor 위치 호출 → anchor 셀에 fill."""
        from backend.services.excel_template_utils import mark_asil_d_function
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.merge_cells("C3:E3")
        result = mark_asil_d_function(ws, 3, 5)  # E3 → anchor C3
        assert result is True
        assert "FFC7CE" in str(ws.cell(3, 3).fill.fgColor.rgb).upper()


class TestAsilBCMarker31:
    """31차 W29: mark_asil_b_function / mark_asil_c_function — ASIL B/C 강조."""

    def test_mark_asil_b_applies_blue_fill(self):
        from backend.services.excel_template_utils import mark_asil_b_function
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(1, 1).value = "SwUFn_0201"
        result = mark_asil_b_function(ws, 1, 1)
        assert result is True
        # ASIL_B_FILL_RGB = "FFE2F0FF" 연한 파랑
        assert "E2F0FF" in str(ws.cell(1, 1).fill.fgColor.rgb).upper()
        assert ws.cell(1, 1).value == "SwUFn_0201"

    def test_mark_asil_c_applies_orange_fill(self):
        from backend.services.excel_template_utils import mark_asil_c_function
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(2, 1).value = "SwUFn_0301"
        result = mark_asil_c_function(ws, 2, 1)
        assert result is True
        # ASIL_C_FILL_RGB = "FFFFE5CC" 연한 주황
        assert "FFE5CC" in str(ws.cell(2, 1).fill.fgColor.rgb).upper()
        assert ws.cell(2, 1).value == "SwUFn_0301"

    def test_asil_b_c_d_rgbs_are_all_distinct(self):
        """ASIL B/C/D RGB가 모두 다른 색 — audit reviewer 등급 구분 가능."""
        from backend.services import design_tokens
        rgbs = {
            design_tokens.ASIL_B_FILL_RGB,
            design_tokens.ASIL_C_FILL_RGB,
            design_tokens.ASIL_D_FILL_RGB,
        }
        assert len(rgbs) == 3, f"중복된 RGB 발견: {rgbs}"

    def test_asil_b_c_distinct_from_user_input_and_fail(self):
        """ASIL B/C가 USER_INPUT(노랑)/FAIL(빨강)와도 다른 색."""
        from backend.services import design_tokens
        assert design_tokens.ASIL_B_FILL_RGB not in (
            design_tokens.USER_INPUT_FILL_RGB,
            design_tokens.FAIL_FILL_RGB,
        )
        assert design_tokens.ASIL_C_FILL_RGB not in (
            design_tokens.USER_INPUT_FILL_RGB,
            design_tokens.FAIL_FILL_RGB,
        )

    def test_mark_asil_b_handles_merged_cell_anchor(self):
        from backend.services.excel_template_utils import mark_asil_b_function
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.merge_cells("B2:D2")
        result = mark_asil_b_function(ws, 2, 4)  # D2 → anchor B2
        assert result is True
        assert "E2F0FF" in str(ws.cell(2, 2).fill.fgColor.rgb).upper()

    def test_mark_asil_c_handles_merged_cell_anchor(self):
        from backend.services.excel_template_utils import mark_asil_c_function
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.merge_cells("E5:G5")
        result = mark_asil_c_function(ws, 5, 7)  # G5 → anchor E5
        assert result is True
        assert "FFE5CC" in str(ws.cell(5, 5).fill.fgColor.rgb).upper()
