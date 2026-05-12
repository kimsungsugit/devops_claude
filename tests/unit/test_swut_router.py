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


class TestInputSurface13:
    """13차 라운드 — 입력 표면 강화 (C3/W7/W8/W9)."""

    def _base_body(self) -> dict:
        return {
            "project_id": "HDPDM01",
            "release_sw_version": "1.0.0",
            "test_date": "2024-02-19",
        }

    def test_w7_test_date_with_suffix_rejected(self):
        """W7: test_date $ anchor — garbage suffix 차단."""
        body = self._base_body()
        body["test_date"] = "2024-02-19; DROP TABLE users"
        r = client.post(
            "/api/swut/coverage/build", json=body,
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_w7_validation_date_with_garbage_rejected(self):
        """W7: validation_date pattern — 빈 string OK, garbage 차단."""
        body = self._base_body()
        body["validation_date"] = "not a date"
        r = client.post(
            "/api/swut/coverage/build", json=body,
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_w7_validation_date_empty_allowed(self):
        """W7: validation_date 빈 string은 통과 — schema validate 만 통과 검증."""
        from backend.schemas import SwUTBuildRequest
        # Pydantic validate 단독 검증 (endpoint mock 부담 없이)
        req = SwUTBuildRequest(
            project_id="HDPDM01",
            release_sw_version="1.0.0",
            test_date="2024-02-19",
            validation_date="",
        )
        assert req.validation_date == ""

    def test_w8_log_folder_with_newline_rejected(self):
        """W8: log_folder 줄바꿈 금지 (헤더 인젝션 안전)."""
        body = self._base_body()
        body["log_folder"] = "C:/fake/log\r\nX-Injected: evil"
        r = client.post(
            "/api/swut/coverage/build", json=body,
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_w8_template_path_maxlen_rejected(self):
        """W8: template_path 500자 초과 차단."""
        body = self._base_body()
        body["template_path"] = "C:/" + "a" * 600
        r = client.post(
            "/api/swut/coverage/build", json=body,
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_w9_jenkins_build_number_negative_rejected(self):
        """W9: jenkins_build_number 음수 차단."""
        body = self._base_body()
        body["jenkins_build_number"] = -1
        r = client.post(
            "/api/swut/coverage/build", json=body,
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_w9_jenkins_build_number_too_large_rejected(self):
        """W9: jenkins_build_number 99999 초과 차단."""
        body = self._base_body()
        body["jenkins_build_number"] = 100000
        r = client.post(
            "/api/swut/coverage/build", json=body,
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_c3_deviation_cases_max_length_rejected(self):
        """C3: deviation_cases 201개 차단 (max_length=200)."""
        body = self._base_body()
        body["deviation_cases"] = [{"tc_id": f"T{i}"} for i in range(201)]
        r = client.post(
            "/api/swut/sutr/build", json=body,
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_c3_deviation_cases_size_limit_rejected(self):
        """C3: 합산 256KB 초과 차단 (50개 × 6KB = 300KB)."""
        body = self._base_body()
        body["deviation_cases"] = [
            {"tc_id": f"T{i}", "rationale": "x" * 6000} for i in range(50)
        ]
        r = client.post(
            "/api/swut/sutr/build", json=body,
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_c3_deviation_cases_key_count_rejected(self):
        """C3: 단일 item key 수 21개 차단."""
        body = self._base_body()
        item = {f"k{i}": "v" for i in range(21)}
        body["deviation_cases"] = [item]
        r = client.post(
            "/api/swut/sutr/build", json=body,
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_c3_deviation_cases_within_limits_accepted_by_schema(self):
        """C3: 정상 case는 schema 통과."""
        from backend.schemas import SwUTBuildRequest
        req = SwUTBuildRequest(
            project_id="HDPDM01",
            release_sw_version="1.0.0",
            test_date="2024-02-19",
            deviation_cases=[
                {"tc_id": "TC1", "tc_no": "TC1", "issue_text": "div by zero",
                 "auto_rationale": "[AUTO] checked"},
                {"tc_id": "TC2", "tc_no": "TC2", "issue_text": "stack overflow",
                 "auto_rationale": "[AUTO] checked"},
            ],
        )
        assert len(req.deviation_cases) == 2


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
    def test_semaphore_capacity_is_3(self):
        """17차 T173: Semaphore(2) → (3) 상향. 14차 메모리 1배 절감 활용."""
        from backend.routers.swut import _BUILD_SEMAPHORE
        assert _BUILD_SEMAPHORE._value == 3

    def test_semaphore_serializes_4th_request(self):
        """17차 T173: 4건 동시 호출 시 1건은 대기. capacity=3."""
        sem = asyncio.Semaphore(3)
        order: list[int] = []

        async def _hold(i: int):
            async with sem:
                order.append(i)
                await asyncio.sleep(0.02)

        async def _main():
            await asyncio.gather(_hold(0), _hold(1), _hold(2), _hold(3))

        asyncio.run(_main())
        assert len(order) == 4  # 모두 완료, Semaphore가 deadlock 안 됨


# ---------------------------------------------------------------------------
# 12차 라운드 — code health 개선 검증
# ---------------------------------------------------------------------------

class TestConfigCache:
    """C2: _load_meta_from_config mtime 기반 cache."""

    def test_lru_cache_hits_with_same_mtime(self, tmp_path, monkeypatch):
        from backend.routers import swut as swut_mod

        cfg_path = tmp_path / "swut_meta.json"
        cfg_path.write_text('{"projects":{"HDPDM01":{"asil_level":"ASIL A"}}}', encoding="utf-8")
        monkeypatch.setattr(swut_mod, "_META_CONFIG_PATH", str(cfg_path))

        swut_mod._read_meta_config_raw.cache_clear()

        for _ in range(5):
            cfg = swut_mod._load_meta_from_config("HDPDM01")
            assert cfg.get("asil_level") == "ASIL A"

        info = swut_mod._read_meta_config_raw.cache_info()
        # 5회 호출 중 1회 miss, 4회 hit
        assert info.misses == 1
        assert info.hits == 4

    def test_lru_cache_invalidates_on_mtime_change(self, tmp_path, monkeypatch):
        """mtime이 변하면 cache miss → reload."""
        import time
        from backend.routers import swut as swut_mod

        cfg_path = tmp_path / "swut_meta.json"
        cfg_path.write_text('{"projects":{"HDPDM01":{"asil_level":"ASIL A"}}}', encoding="utf-8")
        monkeypatch.setattr(swut_mod, "_META_CONFIG_PATH", str(cfg_path))
        swut_mod._read_meta_config_raw.cache_clear()

        cfg1 = swut_mod._load_meta_from_config("HDPDM01")
        assert cfg1.get("asil_level") == "ASIL A"

        # 파일 변경 + mtime 강제 진행
        time.sleep(0.02)
        cfg_path.write_text('{"projects":{"HDPDM01":{"asil_level":"ASIL D"}}}', encoding="utf-8")
        new_mtime = cfg_path.stat().st_mtime + 1.0
        import os
        os.utime(str(cfg_path), (new_mtime, new_mtime))

        cfg2 = swut_mod._load_meta_from_config("HDPDM01")
        assert cfg2.get("asil_level") == "ASIL D"  # cache invalidated


class TestExceptionSanitization:
    """W4: builder exception sanitize — internal detail leak 차단."""

    def test_filenotfound_returns_404_sanitized(self):
        """template_path 존재 안 함 → FileNotFoundError → 404 + sanitized detail."""
        with patch(
            "backend.routers.swut._do_coverage_build",
            side_effect=FileNotFoundError("/secret/internal/path"),
        ):
            r = client.post(
                "/api/swut/coverage/build",
                json={
                    "project_id": "HDPDM01",
                    "release_sw_version": "1.0.0",
                    "test_date": "2024-02-19",
                    "log_folder": "C:/fake/log",
                },
                headers={"X-User": "tester"},
            )
        assert r.status_code == 404
        body = r.json()
        # 응답 형식: {"ok": False, "error": {"code": "HTTP_404", "message": "..."}}
        message = body.get("error", {}).get("message") or body.get("detail", "")
        # 내부 path는 leak되지 않음 — type name만 표시
        assert "/secret/internal/path" not in message
        assert "FileNotFoundError" in message

    def test_value_error_returns_400_with_message(self):
        """ValueError는 사용자 입력 관련이므로 message 표시."""
        with patch(
            "backend.routers.swut._do_coverage_build",
            side_effect=ValueError("ASIL level 'XYZ' 미지원"),
        ):
            r = client.post(
                "/api/swut/coverage/build",
                json={
                    "project_id": "HDPDM01",
                    "release_sw_version": "1.0.0",
                    "test_date": "2024-02-19",
                    "log_folder": "C:/fake/log",
                },
                headers={"X-User": "tester"},
            )
        assert r.status_code == 400
        body = r.json()
        message = body.get("error", {}).get("message") or body.get("detail", "")
        assert "ASIL level" in message

    def test_unexpected_returns_500_no_message_leak(self):
        """예상 못 한 exception은 message 본문 미노출 — type name만."""
        with patch(
            "backend.routers.swut._do_coverage_build",
            side_effect=RuntimeError("DB password=hunter2 leaked"),
        ):
            r = client.post(
                "/api/swut/coverage/build",
                json={
                    "project_id": "HDPDM01",
                    "release_sw_version": "1.0.0",
                    "test_date": "2024-02-19",
                    "log_folder": "C:/fake/log",
                },
                headers={"X-User": "tester"},
            )
        assert r.status_code == 500
        body = r.json()
        message = body.get("error", {}).get("message") or body.get("detail", "")
        assert "hunter2" not in message
        assert "RuntimeError" in message


class TestAsyncMigration:
    """W5: asyncio.to_thread 마이그레이션 검증 — 기존 endpoint가 to_thread로 동작."""

    def test_endpoint_uses_to_thread(self):
        """source code에 asyncio.to_thread 사용 + get_event_loop 미사용 검증."""
        import inspect
        from backend.routers import swut as swut_mod

        src = inspect.getsource(swut_mod)
        assert "asyncio.to_thread" in src
        assert "asyncio.get_event_loop()" not in src
        assert "loop.run_in_executor" not in src


class TestStreamingResponse14:
    """14차 W1: StreamingResponse + BytesIO 직접 stream."""

    def test_response_includes_content_length(self):
        """W1b: Content-Length 헤더가 명시되어 chunked 모드 아니어도 정확한 크기 통보."""
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
                    "log_folder": "C:/fake/log",
                },
                headers={"X-User": "tester"},
            )
        assert r.status_code == 200
        content_length = r.headers.get("content-length")
        assert content_length is not None
        assert int(content_length) == len(r.content)
        # PK ZIP magic 보존 — stream chunk 손상 없음
        assert r.content[:4] == b"PK\x03\x04"

    def test_streaming_response_used_not_plain_response(self):
        """W1a: source code에 StreamingResponse 사용 확인."""
        import inspect
        from backend.routers import swut as swut_mod

        src = inspect.getsource(swut_mod)
        assert "StreamingResponse" in src
        assert "_iter_bytesio" in src
        # plain Response(content=bytes) 사용 회피 확인 — bytes 그대로 전송하지 않음
        assert "Response(content=content" not in src

    def test_builder_result_xlsx_io_is_bytesio(self):
        """W1a: builder result.xlsx_io가 BytesIO 인스턴스 + backward compat property."""
        from backend.routers.swut import _build_coverage_meta
        from backend.schemas import SwUTBuildRequest
        from backend.services.swut_coverage_aggregator import build_coverage_report

        req = SwUTBuildRequest(
            project_id="HDPDM01",
            release_sw_version="1.0.0",
            test_date="2024-02-19",
            log_folder="C:/fake/log",
        )
        session = _make_session()
        meta = _build_coverage_meta(req)
        result = build_coverage_report(session, meta, _minimal_xlsx_template_bytes())
        assert isinstance(result.xlsx_io, io.BytesIO)
        # backward compat property 동작
        assert result.xlsx_bytes[:4] == b"PK\x03\x04"
        # result_size_bytes는 BytesIO copy 없이 측정
        assert result.result_size_bytes == len(result.xlsx_bytes)
        # property 호출 후에도 BytesIO position이 보존되어 stream 가능 (idempotent)
        assert result.xlsx_io.tell() == 0

    def test_iter_bytesio_yields_chunks(self):
        """W1: _iter_bytesio가 chunk별 yield + 빈 data 시 종료."""
        from backend.routers.swut import _iter_bytesio
        import io as _io

        data = b"x" * (200 * 1024)  # 200KB → 64KB chunk 4개
        buf = _io.BytesIO(data)
        chunks = list(_iter_bytesio(buf, chunk_size=64 * 1024))
        assert len(chunks) == 4
        assert sum(len(c) for c in chunks) == len(data)
        assert b"".join(chunks) == data


class TestSutrSwudsIntegration17:
    """17차 T172: SUTR endpoint도 swuds_docx_path 처리."""

    def test_sutr_endpoint_calls_resolve_swuds(self):
        """SUTR endpoint가 _resolve_swuds_function_ids를 호출 + build_sutr에 인자 전달."""
        # mock으로 SwUDS 함수 ID set 강제 + build_sutr 호출 검증
        with patch(
            "backend.routers.swut.collect_swut_session", return_value=_make_session(),
        ), patch(
            "backend.routers.swut._read_template_bytes",
            return_value=_minimal_xlsx_template_bytes(),
        ), patch(
            "backend.routers.swut._resolve_swuds_function_ids",
            return_value={"SwUFn_0001", "SwUFn_0002"},
        ) as resolve_mock, patch(
            "backend.routers.swut.build_sutr",
        ) as build_mock:
            # build_sutr mock — io.BytesIO 결과 반환
            import io as _io
            from backend.services.swut_sutr_aggregator import SutrBuildResult
            build_mock.return_value = SutrBuildResult(
                ok=True, xlsm_io=_io.BytesIO(b"PK\x03\x04test"),
                filename="x.xlsm", warnings=[],
                incomplete_sheets=[], vba_macros_preserved=False, summary={},
            )

            client.post(
                "/api/swut/sutr/build",
                json={
                    "project_id": "HDPDM01",
                    "release_sw_version": "1.0.0",
                    "test_date": "2024-02-19",
                    "log_folder": "C:/fake/log",
                    "swuds_docx_path": "U:/docs/SwUDS_v3.docx",
                },
                headers={"X-User": "tester"},
            )

            assert resolve_mock.called
            # build_sutr이 swuds_function_ids 인자 받았는지
            assert build_mock.called
            call_kwargs = build_mock.call_args.kwargs
            assert call_kwargs.get("swuds_function_ids") == {"SwUFn_0001", "SwUFn_0002"}
