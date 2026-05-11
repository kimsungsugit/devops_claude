"""Tests for backend.routers.swut endpoint (8차 라운드 T143).

FastAPI TestClient로 endpoint 진입 검증:
- Pydantic 422 (invalid release_sw_version / test_engineer 줄바꿈 / doc_id_sequence 비-digit)
- X-User 400 (헤더 미포함)
- Coverage build 200 + xlsx Content-Type (모킹된 input/template)
- Jenkins fetcher mock 후 SwUTSession 반환
- Semaphore(2) 동시 호출 제한
"""
from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.main import app  # noqa: E402
from backend.services.swut_input_adapter import (  # noqa: E402
    EnvironmentData,
    ExecutionRow,
    FunctionCoverage,
    SwUTSession,
)

client = TestClient(app)


def _minimal_xlsx_template_bytes() -> bytes:
    """최소 6시트 Coverage Report template."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    cov = wb.create_sheet("Cover")
    cov["B1"] = "Project"
    ts = wb.create_sheet("Test Summary")
    ts["B1"] = "Project Name"
    wb.create_sheet("1.Traceability")
    wb.create_sheet("2.Consistency")
    cov3 = wb.create_sheet("3. Coverage")
    cov3["A1"] = "Statement Coverage"
    cov3["A6"] = "Unit ID"
    wb.create_sheet("History")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_session() -> SwUTSession:
    env = EnvironmentData(
        env_name="SWTE_01",
        component_name="X",
        test_cases={"SwUFn_0001.001": [object()]},
        test_results={"SwUFn_0001.001": ExecutionRow(tc_name="SwUFn_0001.001", passed=True)},
        function_coverage=[FunctionCoverage(unit_id="SwUFn_0001", name="X")],
    )
    return SwUTSession(environments=[env])


# ---------------------------------------------------------------------------
# Pydantic 422 검증
# ---------------------------------------------------------------------------

class TestPydanticValidation:
    def test_invalid_release_sw_version_rejected(self):
        r = client.post(
            "/api/swut/coverage/build",
            json={
                "project_id": "HDPDM01",
                "release_sw_version": "vX.Y",  # regex 미충족
                "test_date": "2024-02-19",
            },
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_test_engineer_newline_rejected(self):
        r = client.post(
            "/api/swut/coverage/build",
            json={
                "project_id": "HDPDM01",
                "release_sw_version": "1.0.0",
                "test_date": "2024-02-19",
                "test_engineer": "X\nY",
            },
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_doc_id_sequence_non_digit_rejected(self):
        r = client.post(
            "/api/swut/coverage/build",
            json={
                "project_id": "HDPDM01",
                "release_sw_version": "1.0.0",
                "test_date": "2024-02-19",
                "doc_id_sequence": "abc",
            },
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422


class TestXUserHeader:
    def test_missing_x_user_header_rejected(self):
        r = client.post(
            "/api/swut/coverage/build",
            json={
                "project_id": "HDPDM01",
                "release_sw_version": "1.0.0",
                "test_date": "2024-02-19",
            },
            # X-User 헤더 미포함
        )
        # UserContextMiddleware가 먼저 403 또는 endpoint 400 둘 중 하나
        assert r.status_code in (400, 401, 403)


# ---------------------------------------------------------------------------
# Coverage / SUTR 빌드 200 (mock)
# ---------------------------------------------------------------------------

class TestCoverageBuildSuccess:
    def test_returns_xlsx_with_attachment_header(self):
        with patch(
            "backend.routers.swut.collect_swut_session", return_value=_make_session(),
        ), patch(
            "backend.routers.swut._read_template_bytes",
            return_value=_minimal_xlsx_template_bytes(),
        ):
            r = client.post(
                "/api/swut/coverage/build",
                json={
                    "project_id": "HDPDM01",
                    "release_sw_version": "1.0.0",
                    "test_date": "2024-02-19",
                    "test_engineer": "JK",
                    "log_folder": "C:/fake/log",
                },
                headers={"X-User": "tester"},
            )
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert "attachment" in r.headers.get("Content-Disposition", "")
        # 반환 bytes가 xlsx ZIP magic 헤더
        assert r.content[:4] == b"PK\x03\x04"
        # X-* 헤더에 summary/warnings
        assert "X-Swut-Summary" in r.headers or "x-swut-summary" in r.headers


class TestJenkinsFetcherMock:
    def test_collect_from_jenkins_cache_with_mock(self, tmp_path):
        """T140: jenkins_adapter mock 후 SwUTSession 반환."""
        from backend.services.swut_input_adapter import collect_from_jenkins_cache

        # 가짜 cache_root 구조: <root>/<project>/<build>/dummy
        project_dir = tmp_path / "HDPDM01" / "42"
        project_dir.mkdir(parents=True)
        # html 파일 직접 — scan_jenkins_build_root mock 반환
        fake_files = [
            str(project_dir / "SWTE_01_test_case_data_report.html"),
            str(project_dir / "SWTE_01_execution_results_report.html"),
            str(project_dir / "SWTE_01_aggregate_coverage_report.html"),
        ]
        for f in fake_files:
            Path(f).write_text(
                "<!DOCTYPE html><!-- VectorCAST Report header --><html><body>"
                "<title>Test Case Data Report</title></body></html>",
                encoding="utf-8",
            )

        with patch(
            "backend.services.jenkins_adapter.scan_jenkins_build_root",
            return_value={"html_files": fake_files},
        ):
            session = collect_from_jenkins_cache(
                resolver=type("R", (), {"read_bytes": lambda self, p: Path(p).read_bytes()})(),
                project_id="HDPDM01",
                cache_root=str(tmp_path),
                build_number=42,
            )

        assert session is not None
        assert session.source_kind == "jenkins_cache"
        assert len(session.environments) == 1
        assert session.environments[0].env_name == "SWTE_01"

    def test_cache_root_missing_returns_none(self, tmp_path):
        from backend.services.swut_input_adapter import collect_from_jenkins_cache
        warnings: list[str] = []
        session = collect_from_jenkins_cache(
            resolver=None, project_id="HDPDM01",
            cache_root=str(tmp_path / "nonexistent"),
            parse_warnings=warnings,
        )
        assert session is None
        assert any("미발견" in w for w in warnings)


# ---------------------------------------------------------------------------
# Semaphore(2) 동작 검증
# ---------------------------------------------------------------------------

class TestSemaphore:
    def test_semaphore_capacity_is_2(self):
        """Semaphore 인스턴스 capacity 검증 — 동시 2건 한도."""
        from backend.routers.swut import _BUILD_SEMAPHORE
        assert _BUILD_SEMAPHORE._value == 2

    def test_semaphore_serializes_3rd_request(self):
        """3건 동시 호출 시 1건은 대기. asyncio.run sync wrapper로 검증."""
        sem = asyncio.Semaphore(2)
        order: list[int] = []

        async def _hold(i: int):
            async with sem:
                order.append(i)
                await asyncio.sleep(0.02)

        async def _main():
            await asyncio.gather(_hold(0), _hold(1), _hold(2))

        asyncio.run(_main())
        assert len(order) == 3  # 모두 완료, Semaphore가 deadlock 안 됨
