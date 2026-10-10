"""PDF Converter 단위 테스트"""
from pathlib import Path

import pytest


class TestPdfConverter:
    def test_import(self):
        from backend.services.pdf_converter import generate_report_pdf, xlsx_to_pdf
        assert callable(generate_report_pdf)
        assert callable(xlsx_to_pdf)

    def test_generate_report_pdf(self, tmp_path):
        from backend.services.pdf_converter import generate_report_pdf

        pdf_path = tmp_path / "test_report.pdf"
        sections = [
            {"heading": "Overview", "content": "This is a test report for PDF generation."},
            {"heading": "Metrics", "content": [
                ["Metric", "Value", "Status"],
                ["Coverage", "85%", "PASS"],
                ["Complexity", "12", "WARN"],
            ]},
        ]
        result = generate_report_pdf("Test Report", sections, pdf_path, subtitle="Unit Test")
        assert result.exists()
        assert result.stat().st_size > 500

    def test_generate_empty_sections(self, tmp_path):
        from backend.services.pdf_converter import generate_report_pdf

        pdf_path = tmp_path / "empty.pdf"
        result = generate_report_pdf("Empty", [], pdf_path)
        assert result.exists()

    def test_xlsx_to_pdf(self, tmp_path):
        try:
            import openpyxl
        except ImportError:
            pytest.skip("openpyxl not installed")

        from backend.services.pdf_converter import xlsx_to_pdf

        xlsx_path = tmp_path / "test.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Name", "Score", "Grade"])
        ws.append(["Alice", 95, "A"])
        ws.append(["Bob", 80, "B"])
        wb.save(str(xlsx_path))

        pdf_path = tmp_path / "test.pdf"
        result = xlsx_to_pdf(xlsx_path, pdf_path)
        assert result.exists()
        assert result.stat().st_size > 500

    def test_docx_to_pdf_missing_file(self):
        from backend.services.pdf_converter import docx_to_pdf

        with pytest.raises(FileNotFoundError):
            docx_to_pdf(Path("/nonexistent/file.docx"))
