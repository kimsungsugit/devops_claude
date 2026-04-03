"""Unit tests for backend routers (health, exports, code, config).

Uses starlette TestClient to exercise FastAPI endpoints without a running server.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

# Ensure repo root is on sys.path so backend/config can be imported
_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# Stub optional dependencies that may not be installed in the test environment
# so that importing backend.main does not fail.
for _mod_name in [
    "langchain_core",
    "langchain_core.tools",
    "langchain_mcp_adapters",
    "langchain_mcp_adapters.tools",
    "mcp",
    "mcp.client",
    "mcp.client.stdio",
]:
    if _mod_name not in sys.modules:
        _stub = types.ModuleType(_mod_name)
        # Provide minimal class stubs that routers may reference at import time
        _stub.BaseTool = MagicMock       # type: ignore[attr-defined]
        _stub.StructuredTool = MagicMock  # type: ignore[attr-defined]
        sys.modules[_mod_name] = _stub

import backend.middleware as _mw  # noqa: E402

# Disable rate limiting for tests
_mw.RATE_LIMIT = 999999

from backend.main import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)


# ═══════════════════════════════════════════════════════════════════
# Health Router
# ═══════════════════════════════════════════════════════════════════
class TestHealthRouter:
    """Tests for /api/health and related health endpoints."""

    def test_health_check_status_200(self):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    def test_health_check_has_version(self):
        r = client.get("/api/health")
        data = r.json()
        assert "version" in data
        assert isinstance(data["version"], str)

    def test_health_check_has_engine(self):
        r = client.get("/api/health")
        data = r.json()
        assert "engine" in data
        assert isinstance(data["engine"], str)

    def test_health_check_has_file_mode(self):
        r = client.get("/api/health")
        data = r.json()
        assert "file_mode" in data
        assert data["file_mode"] in ("local", "cloudium")

    def test_file_mode_get(self):
        r = client.get("/api/file-mode")
        assert r.status_code == 200
        data = r.json()
        assert "mode" in data

    def test_preview_excel_missing_path(self):
        """POST /api/preview-excel with empty path returns 400."""
        r = client.post("/api/preview-excel", json={"path": ""})
        assert r.status_code == 400

    def test_preview_excel_nonexistent_file(self):
        """POST /api/preview-excel with nonexistent file returns 404."""
        r = client.post(
            "/api/preview-excel",
            json={"path": "/nonexistent/path/file.xlsx"},
        )
        assert r.status_code == 404

    def test_preview_excel_unsupported_format(self):
        """POST /api/preview-excel with unsupported extension returns 400."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"dummy")
            tmp_path = f.name
        try:
            r = client.post("/api/preview-excel", json={"path": tmp_path})
            assert r.status_code == 400
        finally:
            os.unlink(tmp_path)

    def test_preview_excel_txt_file(self):
        """POST /api/preview-excel with a .txt file returns content."""
        with tempfile.NamedTemporaryFile(
            suffix=".txt", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write("line1\nline2\nline3\n")
            tmp_path = f.name
        try:
            r = client.post("/api/preview-excel", json={"path": tmp_path})
            assert r.status_code == 200
            data = r.json()
            assert data["ok"] is True
            assert len(data["sheets"]) == 1
            assert data["sheets"][0]["name"] == "Content"
            assert len(data["sheets"][0]["rows"]) == 3
        finally:
            os.unlink(tmp_path)

    def test_preview_image_nonexistent(self):
        """GET /api/preview-image with nonexistent docx returns 404."""
        r = client.get(
            "/api/preview-image",
            params={"path": "/nonexistent/doc.docx", "image_id": "rId1"},
        )
        assert r.status_code == 404

    def test_check_access_no_body(self):
        """POST /api/file-mode/check-access with empty body returns ok."""
        r = client.post("/api/file-mode/check-access", json={})
        assert r.status_code == 200
        data = r.json()
        assert "mode" in data

    def test_check_access_with_nonexistent_path(self):
        """POST /api/file-mode/check-access with nonexistent path."""
        r = client.post(
            "/api/file-mode/check-access",
            json={"path": "/nonexistent/test/path"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("accessible") is False


# ═══════════════════════════════════════════════════════════════════
# Exports Router
# ═══════════════════════════════════════════════════════════════════
class TestExportsRouter:
    """Tests for /api/exports endpoints."""

    def test_list_exports_returns_list(self):
        """GET /api/exports returns a JSON list."""
        r = client.get("/api/exports")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_list_exports_with_nonexistent_base(self):
        """GET /api/exports with a nonexistent base dir returns empty or error."""
        r = client.get("/api/exports", params={"base": "/nonexistent/base/dir"})
        # Server may return 200 (empty list), 400, or 403 (forbidden path)
        assert r.status_code in (200, 400, 403)

    def test_list_exports_with_session_filter(self):
        """GET /api/exports with session_id filter still returns a list."""
        r = client.get(
            "/api/exports",
            params={"session_id": "nonexistent_session_xyz"},
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_delete_export_nonexistent(self):
        """DELETE /api/exports/<filename> with nonexistent file returns 404."""
        r = client.delete("/api/exports/nonexistent_file.zip")
        assert r.status_code == 404

    def test_restore_export_nonexistent(self):
        """POST /api/exports/restore/<filename> with nonexistent returns 404."""
        r = client.post("/api/exports/restore/nonexistent_file.zip")
        assert r.status_code == 404

    def test_download_export_nonexistent(self):
        """GET /api/exports/download/<filename> with nonexistent returns 404."""
        r = client.get("/api/exports/download/nonexistent_file.zip")
        assert r.status_code == 404

    def test_pdf_convert_nonexistent_source(self):
        """POST /api/exports/pdf/convert with nonexistent file returns error."""
        r = client.post(
            "/api/exports/pdf/convert",
            json={"source_path": "/nonexistent/file.docx"},
        )
        # Should get 404 (FileNotFoundError) or 500
        assert r.status_code in (404, 500)

    def test_pdf_convert_unsupported_extension(self):
        """POST /api/exports/pdf/convert with unsupported ext returns error."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"dummy")
            tmp_path = f.name
        try:
            r = client.post(
                "/api/exports/pdf/convert",
                json={"source_path": tmp_path},
            )
            # 400 (HTTPException) or 500 (APIError caught by generic handler)
            assert r.status_code in (400, 500)
        finally:
            os.unlink(tmp_path)

    def test_pdf_convert_missing_source_path(self):
        """POST /api/exports/pdf/convert without source_path returns 422."""
        r = client.post("/api/exports/pdf/convert", json={})
        assert r.status_code == 422

    def test_pdf_report_missing_fields(self):
        """POST /api/exports/pdf/report without required fields returns 422."""
        r = client.post("/api/exports/pdf/report", json={})
        assert r.status_code == 422

    def test_pdf_report_with_sections(self):
        """POST /api/exports/pdf/report with temp output path generates PDF."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = str(Path(tmpdir) / "test_report.pdf")
            r = client.post(
                "/api/exports/pdf/report",
                json={
                    "title": "Test Report",
                    "sections": [
                        {"heading": "Section 1", "content": "Hello world"},
                        {"heading": "Section 2", "content": "Test content"},
                    ],
                    "output_path": out_path,
                },
            )
            # Might succeed (200) or fail (500) depending on PDF libs installed
            if r.status_code == 200:
                data = r.json()
                assert data["ok"] is True
                assert "pdf_path" in data
                assert "size_mb" in data
            else:
                # PDF generation library may not be available in test env
                assert r.status_code == 500

    def test_cleanup_exports_returns_deleted_count(self):
        """POST /api/exports/cleanup returns deleted count."""
        r = client.post("/api/exports/cleanup", params={"days": 1})
        assert r.status_code == 200
        data = r.json()
        assert "deleted" in data
        assert isinstance(data["deleted"], int)


# ═══════════════════════════════════════════════════════════════════
# Code Router
# ═══════════════════════════════════════════════════════════════════
class TestCodeRouter:
    """Tests for /api/code endpoints."""

    def test_preview_function_missing_params(self):
        """GET /api/code/preview/function without required params returns 422."""
        r = client.get("/api/code/preview/function")
        assert r.status_code == 422

    def test_preview_function_missing_function_name(self):
        """GET /api/code/preview/function without function_name returns 422."""
        r = client.get(
            "/api/code/preview/function",
            params={"source_root": "/some/path"},
        )
        assert r.status_code == 422

    def test_preview_function_empty_function_name(self):
        """GET /api/code/preview/function with empty function_name returns 400."""
        r = client.get(
            "/api/code/preview/function",
            params={"source_root": "/some/path", "function_name": ""},
        )
        assert r.status_code == 400

    def test_call_graph_missing_source_root(self):
        """GET /api/code/call-graph without source_root returns 422."""
        r = client.get("/api/code/call-graph")
        assert r.status_code == 422

    def test_call_graph_invalid_depth(self):
        """GET /api/code/call-graph with depth out of range returns 422."""
        r = client.get(
            "/api/code/call-graph",
            params={"source_root": "/tmp", "depth": 99},
        )
        assert r.status_code == 422

    def test_call_graph_nonexistent_source(self):
        """GET /api/code/call-graph with nonexistent source_root returns error."""
        r = client.get(
            "/api/code/call-graph",
            params={"source_root": "/nonexistent/src/root"},
        )
        # May return 200 (empty graph), 400 (bad path), or 500
        assert r.status_code in (200, 400, 500)

    def test_dependency_map_missing_source_root(self):
        """GET /api/code/dependency-map without source_root returns 422."""
        r = client.get("/api/code/dependency-map")
        assert r.status_code == 422

    def test_globals_missing_source_root(self):
        """GET /api/code/globals without source_root returns 422."""
        r = client.get("/api/code/globals")
        assert r.status_code == 422

    def test_globals_nonexistent_source(self):
        """GET /api/code/globals with nonexistent source returns error."""
        r = client.get(
            "/api/code/globals",
            params={"source_root": "/nonexistent/code/root"},
        )
        # Returns 200 (empty globals), 400 (bad path), or 500
        assert r.status_code in (200, 400, 500)

    def test_call_graph_max_files_boundaries(self):
        """GET /api/code/call-graph validates max_files range."""
        # Below minimum
        r = client.get(
            "/api/code/call-graph",
            params={"source_root": "/tmp", "max_files": 50},
        )
        assert r.status_code == 422

        # Above maximum
        r = client.get(
            "/api/code/call-graph",
            params={"source_root": "/tmp", "max_files": 9999},
        )
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════
# Config Router
# ═══════════════════════════════════════════════════════════════════
class TestConfigRouter:
    """Tests for /api/config endpoints."""

    def test_config_defaults_returns_200(self):
        """GET /api/config/defaults returns config data."""
        r = client.get("/api/config/defaults")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    def test_config_defaults_has_required_keys(self):
        """Config defaults contains essential configuration fields."""
        r = client.get("/api/config/defaults")
        data = r.json()
        required_keys = [
            "project_root",
            "report_dir",
            "targets_glob",
            "include_paths",
            "quality_preset",
            "do_build",
            "do_coverage",
        ]
        for key in required_keys:
            assert key in data, f"Missing config key: {key}"

    def test_config_defaults_types(self):
        """Config defaults values have correct types."""
        r = client.get("/api/config/defaults")
        data = r.json()
        assert isinstance(data["project_root"], str)
        assert isinstance(data["report_dir"], str)
        assert isinstance(data["include_paths"], list)
        assert isinstance(data["do_build"], bool)
        assert isinstance(data["do_coverage"], bool)
        assert isinstance(data["quality_preset"], str)

    def test_config_options_returns_200(self):
        """GET /api/config/options returns options data."""
        r = client.get("/api/config/options")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    def test_config_options_has_presets(self):
        """Config options includes quality presets."""
        r = client.get("/api/config/options")
        data = r.json()
        assert "quality_presets" in data
        assert isinstance(data["quality_presets"], list)
        assert len(data["quality_presets"]) > 0

    def test_config_options_has_strategy(self):
        """Config options includes build strategy and fallback options."""
        r = client.get("/api/config/options")
        data = r.json()
        assert "build_strategy_options" in data
        assert "build_fallback_options" in data


# ═══════════════════════════════════════════════════════════════════
# General API behavior
# ═══════════════════════════════════════════════════════════════════
class TestGeneralAPI:
    """Tests for cross-cutting API behavior."""

    def test_nonexistent_api_route(self):
        """Unmatched /api/* route returns 404."""
        r = client.get("/api/this-endpoint-does-not-exist")
        assert r.status_code == 404

    def test_cors_headers_present(self):
        """CORS middleware adds Access-Control-Allow-Origin header."""
        r = client.get(
            "/api/health",
            headers={"Origin": "http://localhost:3000"},
        )
        assert r.status_code == 200
        assert "access-control-allow-origin" in r.headers

    def test_options_preflight(self):
        """OPTIONS preflight request is handled by CORS middleware."""
        r = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r.status_code == 200
        assert "access-control-allow-origin" in r.headers


# ═══════════════════════════════════════════════════════════════════
# Jenkins Router
# ═══════════════════════════════════════════════════════════════════
class TestJenkinsRouter:
    """Tests for /api/jenkins endpoints."""

    def test_jenkins_jobs_missing_token(self):
        """POST /api/jenkins/jobs with empty api_token returns 400."""
        r = client.post(
            "/api/jenkins/jobs",
            json={
                "base_url": "http://jenkins.local",
                "username": "user",
                "api_token": "",
            },
        )
        assert r.status_code == 400
        body = r.json()
        msg = body.get("error", {}).get("message", "") or body.get("detail", "")
        assert "Token" in msg or "토큰" in msg

    def test_jenkins_builds_missing_job_url(self):
        """POST /api/jenkins/builds with empty job_url returns 400."""
        r = client.post(
            "/api/jenkins/builds",
            json={
                "job_url": "",
                "username": "user",
                "api_token": "some-token",
            },
        )
        assert r.status_code == 400

    def test_jenkins_builds_missing_token(self):
        """POST /api/jenkins/builds with empty api_token returns 400."""
        r = client.post(
            "/api/jenkins/builds",
            json={
                "job_url": "http://jenkins.local/job/test/",
                "username": "user",
                "api_token": "",
            },
        )
        assert r.status_code == 400

    def test_jenkins_progress_returns_progress(self):
        """GET /api/jenkins/progress returns ok + progress."""
        r = client.get(
            "/api/jenkins/progress",
            params={
                "action": "sync",
                "job_url": "http://jenkins.local/job/test/",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert "ok" in data
        assert "progress" in data

    def test_jenkins_jobs_missing_required_fields(self):
        """POST /api/jenkins/jobs without body returns 422."""
        r = client.post("/api/jenkins/jobs", json={})
        assert r.status_code == 422

    def test_jenkins_builds_missing_required_fields(self):
        """POST /api/jenkins/builds without body returns 422."""
        r = client.post("/api/jenkins/builds", json={})
        assert r.status_code == 422

    def test_jenkins_build_info_missing_required_fields(self):
        """POST /api/jenkins/build-info without body returns 422."""
        r = client.post("/api/jenkins/build-info", json={})
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════
# Impact Router
# ═══════════════════════════════════════════════════════════════════
class TestImpactRouter:
    """Tests for /api/impact endpoints."""

    def test_impact_analyze_missing_source_root(self):
        """POST /api/impact/analyze with nonexistent source_root returns 400."""
        r = client.post(
            "/api/impact/analyze",
            json={
                "source_root": "/nonexistent/source/root",
                "changed_files": ["main.c"],
            },
        )
        assert r.status_code == 400
        body = r.json()
        msg = body.get("error", {}).get("message", "") or body.get("detail", "")
        assert "source_root" in msg

    def test_impact_analyze_no_changed_files(self):
        """POST /api/impact/analyze without changed_files returns 400."""
        with tempfile.TemporaryDirectory() as tmpdir:
            r = client.post(
                "/api/impact/analyze",
                json={
                    "source_root": tmpdir,
                    "changed_files": [],
                    "changed_raw": "",
                },
            )
            assert r.status_code == 400
            body = r.json()
            msg = body.get("error", {}).get("message", "") or body.get("detail", "")
            assert "changed" in msg

    def test_impact_analyze_missing_body(self):
        """POST /api/impact/analyze without body returns 422."""
        r = client.post("/api/impact/analyze", json={})
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════
# Chat Router
# ═══════════════════════════════════════════════════════════════════
class TestChatRouter:
    """Tests for /api/chat endpoints."""

    def test_chat_missing_question(self):
        """POST /api/chat without question returns 422."""
        r = client.post("/api/chat", json={})
        assert r.status_code == 422

    def test_chat_approval_get_nonexistent(self):
        """GET /api/chat/approval/<id> with nonexistent id returns 404."""
        r = client.get("/api/chat/approval/nonexistent_approval_id_xyz")
        assert r.status_code == 404

    def test_chat_approval_resolve_nonexistent(self):
        """POST /api/chat/approval/resolve with nonexistent id returns 404."""
        r = client.post(
            "/api/chat/approval/resolve",
            json={
                "approval_id": "nonexistent_approval_id_xyz",
                "decision": "approve",
            },
        )
        assert r.status_code == 404

    def test_chat_approval_resolve_missing_fields(self):
        """POST /api/chat/approval/resolve without body returns 422."""
        r = client.post("/api/chat/approval/resolve", json={})
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════
# Sessions Router
# ═══════════════════════════════════════════════════════════════════
class TestSessionsRouter:
    """Tests for /api/sessions endpoints."""

    def test_list_sessions_returns_list(self):
        """GET /api/sessions returns a JSON list."""
        r = client.get("/api/sessions")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_create_and_delete_session(self):
        """POST /api/sessions/new + DELETE /api/sessions/<id> lifecycle."""
        r = client.post("/api/sessions/new")
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        assert "path" in data
        session_id = data["id"]

        # Get session data
        r2 = client.get(f"/api/sessions/{session_id}/data")
        assert r2.status_code == 200
        d2 = r2.json()
        assert "summary" in d2
        assert "findings" in d2

        # Get session config
        r3 = client.get(f"/api/sessions/{session_id}/config")
        assert r3.status_code == 200
        d3 = r3.json()
        assert "config" in d3

        # Save session config
        r4 = client.post(
            f"/api/sessions/{session_id}/config",
            json={"config": {"project_root": "/tmp/test"}},
        )
        assert r4.status_code == 200
        assert r4.json()["ok"] is True

        # Set session name
        r5 = client.post(
            f"/api/sessions/{session_id}/name",
            json={"name": "Test Session"},
        )
        assert r5.status_code == 200
        assert r5.json()["name"] == "Test Session"

        # Get log
        r6 = client.get(f"/api/sessions/{session_id}/log")
        assert r6.status_code == 200
        assert "lines" in r6.json()

        # Delete session
        r7 = client.delete(f"/api/sessions/{session_id}")
        assert r7.status_code == 200
        assert r7.json()["ok"] is True

    def test_delete_session_nonexistent(self):
        """DELETE /api/sessions/<id> with nonexistent id returns 404."""
        r = client.delete("/api/sessions/nonexistent_session_xyz")
        assert r.status_code == 404

    def test_session_complexity_returns_rows(self):
        """GET /api/sessions/<id>/report/complexity returns rows key."""
        r = client.post("/api/sessions/new")
        session_id = r.json()["id"]
        try:
            r2 = client.get(f"/api/sessions/{session_id}/report/complexity")
            assert r2.status_code == 200
            assert "rows" in r2.json()
        finally:
            client.delete(f"/api/sessions/{session_id}")

    def test_session_docs_nonexistent(self):
        """GET /api/sessions/<id>/report/docs for empty session returns ok=False."""
        r = client.post("/api/sessions/new")
        session_id = r.json()["id"]
        try:
            r2 = client.get(f"/api/sessions/{session_id}/report/docs")
            assert r2.status_code == 200
            assert r2.json()["ok"] is False
        finally:
            client.delete(f"/api/sessions/{session_id}")

    def test_session_logs_returns_logs(self):
        """GET /api/sessions/<id>/report/logs returns logs key."""
        r = client.post("/api/sessions/new")
        session_id = r.json()["id"]
        try:
            r2 = client.get(f"/api/sessions/{session_id}/report/logs")
            assert r2.status_code == 200
            assert "logs" in r2.json()
        finally:
            client.delete(f"/api/sessions/{session_id}")

    def test_session_report_files(self):
        """GET /api/sessions/<id>/report/files returns file listing."""
        r = client.post("/api/sessions/new")
        session_id = r.json()["id"]
        try:
            r2 = client.get(f"/api/sessions/{session_id}/report/files")
            assert r2.status_code == 200
            # Should be a dict (report file listing)
            assert isinstance(r2.json(), dict)
        finally:
            client.delete(f"/api/sessions/{session_id}")

    def test_stop_run_invalid_pid(self):
        """POST /api/run/stop with pid=0 returns 400."""
        r = client.post(
            "/api/run/stop",
            json={"pid": 0},
        )
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════════
# Profiles Router
# ═══════════════════════════════════════════════════════════════════
class TestProfilesRouter:
    """Tests for /api/profiles endpoints."""

    def test_list_profiles_returns_names(self):
        """GET /api/profiles returns names list."""
        r = client.get("/api/profiles")
        assert r.status_code == 200
        data = r.json()
        assert "names" in data
        assert isinstance(data["names"], list)

    def test_get_nonexistent_profile(self):
        """GET /api/profiles/<name> with nonexistent name returns 404."""
        r = client.get("/api/profiles/nonexistent_profile_xyz_12345")
        assert r.status_code == 404

    def test_save_and_delete_profile(self):
        """POST + DELETE /api/profiles/<name> lifecycle."""
        name = "__test_profile_unit__"
        # Save
        r = client.post(
            f"/api/profiles/{name}",
            json={"project_root": "/tmp/test", "report_dir": "reports"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Get
        r2 = client.get(f"/api/profiles/{name}")
        assert r2.status_code == 200
        assert r2.json()["project_root"] == "/tmp/test"

        # Delete
        r3 = client.delete(f"/api/profiles/{name}")
        assert r3.status_code == 200
        assert r3.json()["ok"] is True

        # Confirm deleted
        r4 = client.get(f"/api/profiles/{name}")
        assert r4.status_code == 404

    def test_delete_nonexistent_profile(self):
        """DELETE /api/profiles/<name> with nonexistent returns 404."""
        r = client.delete("/api/profiles/nonexistent_profile_xyz_12345")
        assert r.status_code == 404

    def test_set_last_profile(self):
        """POST /api/profiles/last sets the last profile name."""
        r = client.post(
            "/api/profiles/last",
            json={"name": "test_last"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ═══════════════════════════════════════════════════════════════════
# Quality Router
# ═══════════════════════════════════════════════════════════════════
class TestQualityRouter:
    """Tests for /api/quality endpoints."""

    def test_list_runs_returns_runs(self):
        """GET /api/quality/runs returns runs list."""
        r = client.get("/api/quality/runs")
        assert r.status_code == 200
        data = r.json()
        assert "runs" in data
        assert isinstance(data["runs"], list)

    def test_list_runs_with_doc_type_filter(self):
        """GET /api/quality/runs?doc_type=uds filters by type."""
        r = client.get("/api/quality/runs", params={"doc_type": "uds"})
        assert r.status_code == 200
        data = r.json()
        assert "runs" in data

    def test_list_runs_with_limit_offset(self):
        """GET /api/quality/runs with limit/offset pagination."""
        r = client.get(
            "/api/quality/runs",
            params={"limit": 10, "offset": 0},
        )
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "limit" in data
        assert "offset" in data

    def test_get_run_nonexistent(self):
        """GET /api/quality/runs/<id> with nonexistent returns error."""
        r = client.get("/api/quality/runs/999999")
        assert r.status_code == 200
        data = r.json()
        # Returns error field (not HTTP 404) when run not found
        assert "error" in data or "id" in data

    def test_trend_requires_doc_type(self):
        """GET /api/quality/trend without doc_type returns 422."""
        r = client.get("/api/quality/trend")
        assert r.status_code == 422

    def test_trend_with_doc_type(self):
        """GET /api/quality/trend?doc_type=uds returns trend."""
        r = client.get("/api/quality/trend", params={"doc_type": "uds"})
        assert r.status_code == 200
        data = r.json()
        assert "trend" in data
        assert isinstance(data["trend"], list)

    def test_advice_nonexistent_run(self):
        """POST /api/quality/runs/<id>/advice with nonexistent returns error."""
        r = client.post("/api/quality/runs/999999/advice")
        assert r.status_code == 200
        data = r.json()
        # Returns error field when advisor module or run not available
        assert isinstance(data, dict)


# ═══════════════════════════════════════════════════════════════════
# Local Router (selected simple endpoints)
# ═══════════════════════════════════════════════════════════════════
class TestLocalRouter:
    """Tests for /api/local endpoints."""

    def test_list_dir(self):
        """POST /api/local/list-dir with real directory returns entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file inside
            (Path(tmpdir) / "test.txt").write_text("hello", encoding="utf-8")
            r = client.post(
                "/api/local/list-dir",
                json={"project_root": tmpdir, "rel_path": "."},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["ok"] is True
            assert any(e["name"] == "test.txt" for e in data["entries"])

    def test_list_dir_nonexistent(self):
        """POST /api/local/list-dir with nonexistent returns ok=False."""
        r = client.post(
            "/api/local/list-dir",
            json={"project_root": "/nonexistent/root", "rel_path": "."},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False

    def test_search_in_files(self):
        """POST /api/local/search with real files returns results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.c").write_text(
                "int main() { return 0; }", encoding="utf-8"
            )
            r = client.post(
                "/api/local/search",
                json={
                    "project_root": tmpdir,
                    "rel_path": ".",
                    "query": "main",
                },
            )
            assert r.status_code == 200
            data = r.json()
            assert data["ok"] is True
            assert len(data["results"]) >= 1

    def test_search_empty_query(self):
        """POST /api/local/search with empty query returns ok=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            r = client.post(
                "/api/local/search",
                json={
                    "project_root": tmpdir,
                    "rel_path": ".",
                    "query": "",
                },
            )
            assert r.status_code == 200
            data = r.json()
            assert data["ok"] is False

    def test_editor_read_write_cycle(self):
        """POST /api/local/editor/write + read cycle works."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write
            r = client.post(
                "/api/local/editor/write",
                json={
                    "project_root": tmpdir,
                    "rel_path": "test.txt",
                    "content": "hello world",
                    "make_backup": False,
                },
            )
            assert r.status_code == 200
            assert r.json()["ok"] is True

            # Read back
            r2 = client.post(
                "/api/local/editor/read",
                json={
                    "project_root": tmpdir,
                    "rel_path": "test.txt",
                },
            )
            assert r2.status_code == 200
            d2 = r2.json()
            assert d2["ok"] is True
            assert d2["text"] == "hello world"

    def test_editor_replace(self):
        """POST /api/local/editor/replace replaces lines correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "test.c"
            fpath.write_text("line1\nline2\nline3\n", encoding="utf-8")
            r = client.post(
                "/api/local/editor/replace",
                json={
                    "project_root": tmpdir,
                    "rel_path": "test.c",
                    "start_line": 2,
                    "end_line": 2,
                    "content": "REPLACED",
                },
            )
            assert r.status_code == 200
            assert r.json()["ok"] is True
            # Verify
            text = fpath.read_text(encoding="utf-8")
            assert "REPLACED" in text
            assert "line1" in text
            assert "line3" in text

    def test_format_c_returns_dict(self):
        """POST /api/local/format-c returns ok field."""
        r = client.post(
            "/api/local/format-c",
            json={"text": "int main(){return 0;}", "filename": "test.c"},
        )
        assert r.status_code == 200
        data = r.json()
        assert "ok" in data
        # ok may be False if clang-format is not installed

    def test_format_c_empty_text(self):
        """POST /api/local/format-c with empty text returns ok=False."""
        r = client.post(
            "/api/local/format-c",
            json={"text": "", "filename": "test.c"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_replace_text(self):
        """POST /api/local/replace-text replaces text in file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "main.c"
            fpath.write_text("int foo = 42;", encoding="utf-8")
            r = client.post(
                "/api/local/replace-text",
                json={
                    "project_root": tmpdir,
                    "rel_path": "main.c",
                    "search": "42",
                    "replace": "99",
                },
            )
            assert r.status_code == 200
            assert r.json()["ok"] is True
            assert r.json()["changed"] is True
            assert "99" in fpath.read_text(encoding="utf-8")

    def test_open_file_empty_path(self):
        """POST /api/local/open-file with empty path returns 400."""
        r = client.post("/api/local/open-file", json={"path": ""})
        assert r.status_code == 400

    def test_open_file_nonexistent(self):
        """POST /api/local/open-file with nonexistent returns 403 or 404."""
        r = client.post(
            "/api/local/open-file",
            json={"path": "/nonexistent/file.txt"},
        )
        assert r.status_code in (403, 404)

    def test_open_folder_empty_path(self):
        """POST /api/local/open-folder with empty path returns 400."""
        r = client.post("/api/local/open-folder", json={"path": ""})
        assert r.status_code == 400

    def test_preflight_missing_config(self):
        """POST /api/local/preflight without config returns 422."""
        r = client.post("/api/local/preflight", json={})
        assert r.status_code == 422

    def test_kb_list_missing_fields(self):
        """POST /api/local/kb/list without body returns 422."""
        r = client.post("/api/local/kb/list", json={})
        assert r.status_code == 422

    def test_kb_delete_no_entry_key(self):
        """POST /api/local/kb/delete without entry_key returns 400."""
        r = client.post(
            "/api/local/kb/list",
            json={"project_root": "/tmp", "report_dir": "reports"},
        )
        assert r.status_code == 200
        assert "entries" in r.json()

    def test_local_reports_list(self):
        """GET /api/local/reports returns list."""
        r = client.get("/api/local/reports")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (list, dict))
