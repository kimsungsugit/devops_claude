"""SwUDS docx parser 단위 테스트 (16차 라운드).

합성 docx로 SwUDS 양식 시뮬레이션 + 함수 ID 추출 검증.
"""
from __future__ import annotations

import io
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.swut_swuds_parser import (  # noqa: E402
    DOCX_MAX_BYTES,
    parse_swuds_docx,
)


def _build_swuds_docx(function_ids: list[str], with_descriptions: bool = False) -> bytes:
    """합성 SwUDS docx 생성 — Hyundai 양식 (heading 'SwUFn_XXXX' + table)."""
    from docx import Document  # type: ignore

    doc = Document()
    for fn_id in function_ids:
        doc.add_paragraph(f"{fn_id} — Sample Description Heading")
        tbl = doc.add_table(rows=2, cols=2)
        tbl.cell(0, 0).text = "Description"
        if with_descriptions:
            tbl.cell(0, 1).text = f"Function {fn_id} does X, Y, Z."
        else:
            tbl.cell(0, 1).text = ""
        tbl.cell(1, 0).text = "Interface"
        tbl.cell(1, 1).text = "void"

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class TestSwUDSParser:
    def test_empty_bytes_returns_ok_false(self):
        warnings: list[str] = []
        result = parse_swuds_docx(b"", parse_warnings=warnings)
        assert not result.ok
        assert any("비어있음" in w for w in warnings)

    def test_oversize_rejected(self):
        warnings: list[str] = []
        oversize = b"x" * (DOCX_MAX_BYTES + 1)
        result = parse_swuds_docx(oversize, parse_warnings=warnings)
        assert not result.ok
        assert any("한도 초과" in w for w in warnings)

    def test_invalid_docx_returns_ok_false(self):
        warnings: list[str] = []
        result = parse_swuds_docx(b"not a docx file", parse_warnings=warnings)
        assert not result.ok
        assert any("로드 실패" in w for w in warnings)

    def test_no_swufn_heading_returns_ok_false(self):
        from docx import Document  # type: ignore
        doc = Document()
        doc.add_paragraph("Just a regular paragraph")
        doc.add_paragraph("Another one")
        buf = io.BytesIO()
        doc.save(buf)

        warnings: list[str] = []
        result = parse_swuds_docx(buf.getvalue(), parse_warnings=warnings)
        assert not result.ok
        assert any("미발견" in w for w in warnings)

    def test_extracts_3_function_ids(self):
        docx_bytes = _build_swuds_docx(["SwUFn_0001", "SwUFn_0002", "SwUFn_0101"])
        result = parse_swuds_docx(docx_bytes)
        assert result.ok
        assert result.function_ids == {"SwUFn_0001", "SwUFn_0002", "SwUFn_0101"}
        assert len(result.entries) == 3

    def test_description_extracted_from_table(self):
        docx_bytes = _build_swuds_docx(["SwUFn_0101"], with_descriptions=True)
        result = parse_swuds_docx(docx_bytes)
        assert result.ok
        entry = result.entries[0]
        assert entry.function_id == "SwUFn_0101"
        assert "Function SwUFn_0101 does X" in entry.description

    def test_heading_text_preserved(self):
        docx_bytes = _build_swuds_docx(["SwUFn_0501"])
        result = parse_swuds_docx(docx_bytes)
        assert result.ok
        assert "Sample Description Heading" in result.entries[0].heading_text

    def test_to_dict_contains_qualification_meta(self):
        docx_bytes = _build_swuds_docx(["SwUFn_0001"])
        result = parse_swuds_docx(docx_bytes)
        d = result.to_dict()
        assert d["ok"] is True
        assert "tool_qualification" in d
        assert d["tool_qualification"]["evidence_class"] == "auto-generated draft"

    def test_heading_without_following_table_still_captured(self):
        """heading 직후 paragraph만 있어도 (table 없이) entry 보존."""
        from docx import Document  # type: ignore
        doc = Document()
        doc.add_paragraph("SwUFn_9999")
        doc.add_paragraph("Just a paragraph, no table.")
        buf = io.BytesIO()
        doc.save(buf)

        result = parse_swuds_docx(buf.getvalue())
        assert result.ok
        assert "SwUFn_9999" in result.function_ids


class TestSwUDSConsistencyIntegration:
    """16차: SwUDS↔SwUTS 비교가 build_coverage_report로 전달되는지."""

    def test_swuds_function_ids_added_to_consistency_when_all_match(self, tmp_path):
        """SwUTS 모든 함수가 SwUDS에 있으면 PASS."""
        import openpyxl
        from backend.services.swut_coverage_aggregator import build_coverage_report, CoverageBuildMeta
        from backend.services.swut_input_adapter import (
            EnvironmentData, ExecutionRow, FunctionCoverage, SwUTSession,
        )
        # session: SwUFn_0001 만 보유
        env = EnvironmentData(
            env_name="SWTE_01", component_name="X",
            test_cases={"SwUFn_0001.001": [object()]},
            test_results={"SwUFn_0001.001": ExecutionRow(tc_name="SwUFn_0001.001", passed=True)},
            function_coverage=[FunctionCoverage(unit_id="SwUFn_0001", name="X")],
        )
        session = SwUTSession(environments=[env])
        meta = CoverageBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")

        # 최소 template
        wb_tmpl = openpyxl.Workbook()
        wb_tmpl.remove(wb_tmpl.active)
        wb_tmpl.create_sheet("Cover")
        wb_tmpl.create_sheet("Test Summary")
        wb_tmpl.create_sheet("1.Traceability")
        wb_tmpl.create_sheet("2.Consistency")
        cov3 = wb_tmpl.create_sheet("3. Coverage")
        cov3["A1"] = "Statement Coverage"
        cov3["A6"] = "Unit ID"
        wb_tmpl.create_sheet("History")
        tmpl_buf = io.BytesIO()
        wb_tmpl.save(tmpl_buf)

        # SwUDS function_ids: 동일한 SwUFn_0001
        result = build_coverage_report(
            session, meta, tmpl_buf.getvalue(),
            swuds_function_ids={"SwUFn_0001"},
        )

        wb = openpyxl.load_workbook(io.BytesIO(result.xlsx_bytes))
        cons = wb["2.Consistency"]
        # row 8 = SwUDS↔SwUTS 매핑
        items = [str(cons.cell(r, 1).value or "") for r in range(4, 10)]
        result_col = [str(cons.cell(r, 4).value or "") for r in range(4, 10)]
        # 5번째 row가 SwUDS 매핑
        swuds_rows = [(i, item) for i, item in enumerate(items) if "SwUDS" in item]
        assert swuds_rows, f"SwUDS 매핑 row 없음: {items}"
        idx = swuds_rows[0][0]
        assert result_col[idx] == "PASS"
        # summary 갱신
        assert result.summary.get("consistency_self_check_rows") == 5
        assert result.summary.get("consistency_swuds_compared") is True

    def test_swuds_missing_function_marked_fail(self, tmp_path):
        """SwUDS에는 있는데 SwUTS에 없는 함수가 있으면 FAIL."""
        import openpyxl
        from backend.services.swut_coverage_aggregator import build_coverage_report, CoverageBuildMeta
        from backend.services.swut_input_adapter import (
            EnvironmentData, ExecutionRow, FunctionCoverage, SwUTSession,
        )
        env = EnvironmentData(
            env_name="SWTE_01", component_name="X",
            test_cases={"SwUFn_0001.001": [object()]},
            test_results={"SwUFn_0001.001": ExecutionRow(tc_name="SwUFn_0001.001", passed=True)},
            function_coverage=[FunctionCoverage(unit_id="SwUFn_0001", name="X")],
        )
        session = SwUTSession(environments=[env])
        meta = CoverageBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")

        wb_tmpl = openpyxl.Workbook()
        wb_tmpl.remove(wb_tmpl.active)
        wb_tmpl.create_sheet("Cover")
        wb_tmpl.create_sheet("Test Summary")
        wb_tmpl.create_sheet("1.Traceability")
        wb_tmpl.create_sheet("2.Consistency")
        cov3 = wb_tmpl.create_sheet("3. Coverage")
        cov3["A1"] = "Statement Coverage"
        cov3["A6"] = "Unit ID"
        wb_tmpl.create_sheet("History")
        tmpl_buf = io.BytesIO()
        wb_tmpl.save(tmpl_buf)

        # SwUDS: SwUFn_0001 + SwUFn_0002 (SwUTS에 0002 없음)
        result = build_coverage_report(
            session, meta, tmpl_buf.getvalue(),
            swuds_function_ids={"SwUFn_0001", "SwUFn_0002"},
        )

        wb = openpyxl.load_workbook(io.BytesIO(result.xlsx_bytes))
        cons = wb["2.Consistency"]
        items = [str(cons.cell(r, 1).value or "") for r in range(4, 10)]
        result_col = [str(cons.cell(r, 4).value or "") for r in range(4, 10)]
        notes = [str(cons.cell(r, 5).value or "") for r in range(4, 10)]
        swuds_rows = [(i, item) for i, item in enumerate(items) if "SwUDS" in item]
        assert swuds_rows
        idx = swuds_rows[0][0]
        assert result_col[idx] == "FAIL"
        assert "SwUFn_0002" in notes[idx], f"누락 함수 표시 누락: {notes[idx]}"

    def test_swuds_not_provided_partial_label_kept(self, tmp_path):
        """swuds_function_ids=None이면 incomplete_sheets에 partial 라벨 유지."""
        import openpyxl
        from backend.services.swut_coverage_aggregator import build_coverage_report, CoverageBuildMeta
        from backend.services.swut_input_adapter import (
            EnvironmentData, ExecutionRow, FunctionCoverage, SwUTSession,
        )
        env = EnvironmentData(
            env_name="SWTE_01", component_name="X",
            test_cases={"SwUFn_0001.001": [object()]},
            test_results={"SwUFn_0001.001": ExecutionRow(tc_name="SwUFn_0001.001", passed=True)},
            function_coverage=[FunctionCoverage(unit_id="SwUFn_0001", name="X")],
        )
        session = SwUTSession(environments=[env])
        meta = CoverageBuildMeta(release_sw_version="1.0.0", test_date="2024-02-19")

        wb_tmpl = openpyxl.Workbook()
        wb_tmpl.remove(wb_tmpl.active)
        wb_tmpl.create_sheet("Cover")
        wb_tmpl.create_sheet("Test Summary")
        wb_tmpl.create_sheet("1.Traceability")
        wb_tmpl.create_sheet("2.Consistency")
        cov3 = wb_tmpl.create_sheet("3. Coverage")
        cov3["A1"] = "Statement Coverage"
        cov3["A6"] = "Unit ID"
        wb_tmpl.create_sheet("History")
        tmpl_buf = io.BytesIO()
        wb_tmpl.save(tmpl_buf)

        result = build_coverage_report(session, meta, tmpl_buf.getvalue())
        assert any("partial" in s for s in result.incomplete_sheets)
        assert result.summary.get("consistency_swuds_compared") is False


class TestSwUDSSchemaIntegration:
    """16차: SwUTBuildRequest에 swuds_docx_path 필드 추가."""

    def test_schema_accepts_empty_swuds_path(self):
        from backend.schemas import SwUTBuildRequest
        req = SwUTBuildRequest(
            project_id="HDPDM01",
            release_sw_version="1.0.0",
            test_date="2024-02-19",
        )
        assert req.swuds_docx_path == ""

    def test_schema_accepts_explicit_swuds_path(self):
        from backend.schemas import SwUTBuildRequest
        req = SwUTBuildRequest(
            project_id="HDPDM01",
            release_sw_version="1.0.0",
            test_date="2024-02-19",
            swuds_docx_path="U:/docs/SwUDS_v3.docx",
        )
        assert req.swuds_docx_path == "U:/docs/SwUDS_v3.docx"

    def test_schema_rejects_swuds_path_with_newline(self):
        """W8 패턴: 줄바꿈 차단 (헤더 인젝션 안전)."""
        from backend.schemas import SwUTBuildRequest
        with pytest.raises(Exception):  # noqa: B017
            SwUTBuildRequest(
                project_id="HDPDM01",
                release_sw_version="1.0.0",
                test_date="2024-02-19",
                swuds_docx_path="U:/docs\r\nX-Injected: evil",
            )

    def test_schema_rejects_swuds_path_too_long(self):
        from backend.schemas import SwUTBuildRequest
        with pytest.raises(Exception):  # noqa: B017
            SwUTBuildRequest(
                project_id="HDPDM01",
                release_sw_version="1.0.0",
                test_date="2024-02-19",
                swuds_docx_path="U:/" + "a" * 600,
            )
