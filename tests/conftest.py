from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest


_TMP_ROOT = Path(__file__).resolve().parents[1] / ".codex_tmp"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)


@pytest.fixture()
def tmp_path() -> Path:
    path = _TMP_ROOT / f"pytest-{uuid.uuid4().hex[:12]}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture()
def sample_report_dir(tmp_path: Path) -> Path:
    """Create a sample report directory with minimal JSON files for MCP tests."""
    import json as _json

    report_dir = tmp_path / "reports"
    report_dir.mkdir()

    (report_dir / "analysis_summary.json").write_text(
        _json.dumps({
            "project": "test_project",
            "coverage": {"line_rate": 0.85, "branch_rate": 0.72, "threshold": 0.8, "ok": True},
        }),
        encoding="utf-8",
    )
    (report_dir / "findings_flat.json").write_text(
        _json.dumps([
            {"severity": "warning", "rule": "W001", "message": "unused variable", "file": "main.c", "line": 10},
        ]),
        encoding="utf-8",
    )
    (report_dir / "run_status.json").write_text(
        _json.dumps({"ok": True, "total": 50, "passed": 48, "failed": 2}),
        encoding="utf-8",
    )
    (report_dir / "history.json").write_text(_json.dumps([]), encoding="utf-8")
    (report_dir / "jenkins_scan.json").write_text(_json.dumps({}), encoding="utf-8")
    return report_dir


@pytest.fixture()
def mock_llm_response(monkeypatch):
    """Mock workflow.ai LLM calls to return a canned response without hitting real APIs."""

    def _mock_call(*args, **kwargs):
        return {"text": "Mocked LLM response", "usage": {"input_tokens": 10, "output_tokens": 20}}

    try:
        import workflow.ai as _ai_mod
        monkeypatch.setattr(_ai_mod, "call_llm", _mock_call, raising=False)
        monkeypatch.setattr(_ai_mod, "call_gemini", _mock_call, raising=False)
    except (ImportError, AttributeError):
        pass
    return _mock_call


@pytest.fixture()
def mock_api_client():
    """Provide a mock httpx-style async client for API integration tests."""
    from unittest.mock import AsyncMock, MagicMock

    client = MagicMock()
    client.get = AsyncMock(return_value=MagicMock(status_code=200, json=lambda: {"ok": True}))
    client.post = AsyncMock(return_value=MagicMock(status_code=200, json=lambda: {"ok": True}))
    client.delete = AsyncMock(return_value=MagicMock(status_code=200, json=lambda: {"ok": True}))
    return client
