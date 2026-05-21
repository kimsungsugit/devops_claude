"""54차 T280 — excel_layout_resolver.py 회귀 테스트.

8 시나리오: v2.02 inspect / v3.01 fallback / sha256 caching / graceful missing /
LRU 회전 / kind 분기 (coverage vs sitr).
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import openpyxl  # noqa: E402

from backend.services import excel_layout_resolver as elr  # noqa: E402


def _make_xlsx(sheets: dict[str, list[list[str]]]) -> bytes:
    """sheets dict로 xlsx bytes 생성. {sheet_name: [[cell, cell, ...], ...]}."""
    wb = openpyxl.Workbook()
    # default sheet 제거
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r_idx, row in enumerate(rows, start=1):
            for c_idx, val in enumerate(row, start=1):
                if val is not None:
                    ws.cell(row=r_idx, column=c_idx, value=val)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _reset_cache():
    elr.clear_layout_cache()
    yield
    elr.clear_layout_cache()


def _v202_coverage_template() -> bytes:
    """SwIT v2.02 Coverage 양식 mimicry — 'SW Version', 'HW Version' 라벨."""
    return _make_xlsx({
        "Cover": [
            ["", ""],
            ["Project", ""],
            ["ASIL Level", ""],
            ["Author", ""],
            ["Approver", ""],
        ],
        "1.Test Summary": [
            ["", ""],
            ["Project Name", ""],
            ["SW Version", ""],
            ["HW Version", ""],
            ["Test Date", ""],
            ["Test Engineer", ""],
            ["Final Test Result", ""],
            # B17-F17 row 16~17번째 즈음
            [""], [""], [""], [""], [""], [""], [""], [""], [""],
            ["Total TC", ""],  # v2.02 신규 — row 17 (1-based)
            [""], [""], [""], [""],
            ["Requirements/Design Coverage", ""],  # row 22
        ],
        "1.Traceability": [["Function ID"]],
        "2.Consistency": [["Item", "Expected", "Actual", "Result"]],
        "3.Coverage": [["Unit ID"]],
        "History": [["Version", "Date"]],
    })


def _v202_sitr_template() -> bytes:
    """SwIT v2.02 SITR — xlsm은 만들 수 없으나 sheet 구조는 mimicry. 본 fixture는
    xlsx 확장자로 만들지만 kind='sitr'로 호출하여 path 분기만 검증."""
    return _make_xlsx({
        "Cover": [["Project", ""]],
        "1.Test Summary": [
            ["", ""],
            ["SW Version", ""],
            ["HW Version", ""],
            ["Test Engineer", ""],
        ],
        "Deviation": [["Test Case ID", "Issue", "Rationale"]],
        "Test Log": [
            # header row에 marker col 추가
            ["Test Case ID", "Component", "Method", "Result", "Function ID", "ASIL", "", "", "Marker"],
        ],
        "History": [["Version"]],
    })


def _v301_coverage_template() -> bytes:
    """SwUT v3.01 양식 — Release Name(SW) / Test Target Version(HW) 라벨."""
    return _make_xlsx({
        "Cover": [
            ["Project", ""],
            ["ASIL Level", ""],
            ["Author", ""],
            ["Approver", ""],
        ],
        "Test Summary": [
            ["Project Name", ""],
            ["Release Name(SW)", ""],
            ["Test Target Version(HW)", ""],
            ["Test Date", ""],
            ["Test Engineer", ""],
            ["Final Test Result", ""],
        ],
        "1.Traceability": [["Function ID"]],
        "2.Consistency": [["Item"]],
        "3.Coverage": [["Unit ID"]],
        "History": [["Version"]],
    })


def _empty_xlsx() -> bytes:
    """label 없는 빈 xlsx — graceful warnings 확인."""
    return _make_xlsx({"Sheet1": [["dummy"]]})


class TestInspectCoverageV202:
    def test_inspect_coverage_template_v202(self):
        layout = elr.inspect_swit_layout(_v202_coverage_template(), "coverage")
        assert layout.detected_version == "v2.02"
        assert layout.test_summary_labels.get("release_sw_version") == "SW Version"
        assert layout.test_summary_labels.get("hw_version") == "HW Version"
        assert layout.tc_stats_row is not None
        assert layout.tc_stats_col_start is not None
        assert layout.requirements_row is not None
        assert layout.fallback_to_v301 is False

    def test_inspect_kind_coverage_skips_test_log(self):
        """kind='coverage'는 Test Log/Deviation inspect skip."""
        layout = elr.inspect_swit_layout(_v202_coverage_template(), "coverage")
        assert layout.test_log_header_cell is None
        assert layout.deviation_header_cell is None
        assert layout.test_log_extra_marker_col is None


class TestInspectSitrV202:
    def test_inspect_sitr_template_v202_marker_col(self):
        layout = elr.inspect_swit_layout(_v202_sitr_template(), "sitr")
        assert layout.detected_version == "v2.02"
        # Test Log header에 "Marker" 가 col 9에 있음
        assert layout.test_log_extra_marker_col == 9
        # Test Log header cell + Deviation header cell도 잡혀야 함
        assert layout.test_log_header_cell is not None
        assert layout.deviation_header_cell is not None

    def test_inspect_kind_sitr_finds_deviation(self):
        layout = elr.inspect_swit_layout(_v202_sitr_template(), "sitr")
        assert layout.deviation_header_cell is not None
        assert layout.deviation_header_cell.row == 1
        assert layout.deviation_header_cell.col == 1


class TestV301Fallback:
    def test_inspect_v301_fallback(self):
        """v3.01 양식 → fallback_to_v301=True + tc_stats_row=None."""
        layout = elr.inspect_swit_layout(_v301_coverage_template(), "coverage")
        assert layout.detected_version == "v3.01"
        assert layout.fallback_to_v301 is True
        assert layout.tc_stats_row is None
        assert layout.requirements_row is None
        # v3.01 라벨이 검출돼야 함
        assert layout.test_summary_labels.get("release_sw_version") == "Release Name(SW)"


class TestCaching:
    def test_lru_cache_sha256_keying(self, monkeypatch):
        """같은 bytes 두 번 inspect → _inspect_internal 1회만 호출."""
        template = _v202_coverage_template()
        call_count = {"n": 0}
        original = elr._inspect_internal

        def counting(bytes_, kind):
            call_count["n"] += 1
            return original(bytes_, kind)

        monkeypatch.setattr(elr, "_inspect_internal", counting)
        elr.clear_layout_cache()

        layout1 = elr.inspect_swit_layout(template, "coverage")
        layout2 = elr.inspect_swit_layout(template, "coverage")
        assert call_count["n"] == 1
        assert layout1 is layout2  # 동일 객체 반환

    def test_layout_cache_invalidation_on_bytes_change(self):
        """1 byte라도 다르면 sha256 다름 → 새 inspect."""
        t1 = _v202_coverage_template()
        # 1바이트 변경된 새 template
        t2 = _v202_sitr_template()
        assert t1 != t2
        layout1 = elr.inspect_swit_layout(t1, "coverage")
        layout2 = elr.inspect_swit_layout(t2, "coverage")
        # detected_version은 같을 수 있으나 다른 cache entry
        assert elr.cache_size() == 2
        assert layout1 is not layout2

    def test_lru_evict_when_max_exceeded(self):
        """maxsize 초과 시 oldest entry 제거 (54-fix W3: 4 → 8)."""
        elr.clear_layout_cache()
        # 9개 서로 다른 template
        for i in range(9):
            t = _make_xlsx({"Sheet": [[f"v{i}"]]})
            elr.inspect_swit_layout(t, "coverage")
        # _MAX_CACHE_SIZE = 8 이므로 9번째에 oldest evict됨
        assert elr.cache_size() == 8


class TestGraceful:
    def test_missing_labels_graceful(self):
        """label 없는 xlsx → warnings 누적 + fallback=True."""
        layout = elr.inspect_swit_layout(_empty_xlsx(), "coverage")
        assert layout.fallback_to_v301 is True
        # test_summary_labels 비어 있음 (Test Summary 시트 없음)
        assert layout.test_summary_labels == {}
        assert any("Test Summary" in w for w in layout.warnings)

    def test_inspect_rejects_zip_bomb_magic_bytes(self):
        """54-fix C2 — ZIP bomb / magic byte 위조 거부."""
        # ZIP magic bytes (PK\x03\x04)이지만 후속 ZIP 구조 부재
        fake_zip = b"PK\x03\x04" + b"\x00" * 100
        layout = elr.inspect_swit_layout(fake_zip, "coverage")
        assert layout.fallback_to_v301 is True
        # validate_xlsx_template_bytes가 거부 (Open Office XML 구조 미발견 등)
        assert any(
            "template 입력 검증 실패" in w or "Open Office XML" in w or "not a valid ZIP" in w
            for w in layout.warnings
        )

    def test_corrupted_bytes_graceful(self):
        """invalid bytes → fallback=True + warnings (54-fix C2: ZIP bomb 사전 검증)."""
        layout = elr.inspect_swit_layout(b"not a real xlsx", "coverage")
        assert layout.fallback_to_v301 is True
        # C2 fix 후: validate_xlsx_template_bytes가 거부 → "template 입력 검증 실패" 메시지
        assert any(
            "template 입력 검증 실패" in w or "template load 실패" in w or "load 실패" in w
            for w in layout.warnings
        )
