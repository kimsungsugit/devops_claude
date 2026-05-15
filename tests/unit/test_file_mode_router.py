"""39차 — /api/file-mode/add-allowed-prefix + remove + extra-prefixes 회귀.

3 endpoint × ~3 시나리오 = ~8건.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.services import cloudium_extra_prefixes as cep  # noqa: E402


client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    """endpoint 회귀 사이 영구 저장소 격리."""
    import threading
    p = tmp_path / "extra.json"
    monkeypatch.setattr(cep, "PREFIXES_PATH", p)
    monkeypatch.setattr(cep, "_LOCK", threading.Lock())
    return p


@pytest.fixture
def _cloudium_resolver(monkeypatch):
    """resolver를 cloudium mock으로 강제 — switch_mode 부작용 회피."""
    from backend.services import file_resolver as fr

    class _MockCloudium(fr.CloudiumFileResolver):
        def __init__(self):
            self.allowed_prefixes = []
            self.gate_process = "excel_rename_gui_v2.exe"
            self.worker_host = "127.0.0.1"
            self.worker_port = 8765

    mock = _MockCloudium()
    monkeypatch.setattr(fr, "_resolver", mock)
    # switch_mode가 호출되어도 _MockCloudium에 prefixes만 누적
    original_switch = fr.switch_mode

    def _switch_stub(mode: str, **kwargs):
        if mode == "cloudium":
            prefixes_str = kwargs.get("allowed_prefixes", "")
            mock.allowed_prefixes = [p.strip() for p in prefixes_str.split(",") if p.strip()]
            return mock
        return original_switch(mode, **kwargs)

    monkeypatch.setattr(fr, "switch_mode", _switch_stub)
    return mock


class TestExtraPrefixesGet:
    """GET /api/file-mode/extra-prefixes — read-only."""

    def test_empty_initially(self):
        r = client.get("/api/file-mode/extra-prefixes", headers={"X-User": "tester"})
        assert r.status_code == 200
        assert r.json() == {"prefixes": []}

    def test_returns_added_prefixes(self):
        cep.save_extra_prefixes(["U:/a", "U:/b"])
        r = client.get("/api/file-mode/extra-prefixes", headers={"X-User": "tester"})
        assert r.status_code == 200
        assert r.json()["prefixes"] == ["U:/a", "U:/b"]


class TestAddAllowedPrefix:
    """POST /api/file-mode/add-allowed-prefix — cloudium 모드 전용."""

    def test_local_mode_rejected(self):
        """local 모드면 400 — 사용자에게 모드 전환 안내."""
        r = client.post(
            "/api/file-mode/add-allowed-prefix",
            json={"prefix": "U:/test"},
            headers={"X-User": "tester"},
        )
        # local 모드 backend → 400 (cloudium 전환 안 했음)
        assert r.status_code == 400
        # error_handler가 wrapping — {"ok": False, "error": {"code": "HTTP_400", "message": "..."}}
        body = r.json()
        msg = body.get("error", {}).get("message") or body.get("detail", "")
        assert "cloudium" in msg.lower()

    def test_cloudium_mode_normal_add(self, _cloudium_resolver):
        r = client.post(
            "/api/file-mode/add-allowed-prefix",
            json={"prefix": "U:/swit/test_result"},
            headers={"X-User": "tester"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["added"] is True
        assert "U:/swit/test_result" in body["extra_prefixes"]
        # resolver에도 즉시 반영
        assert "U:/swit/test_result" in _cloudium_resolver.allowed_prefixes

    def test_cloudium_mode_duplicate_added_false(self, _cloudium_resolver):
        client.post(
            "/api/file-mode/add-allowed-prefix",
            json={"prefix": "U:/dup"},
            headers={"X-User": "tester"},
        )
        r = client.post(
            "/api/file-mode/add-allowed-prefix",
            json={"prefix": "U:/dup"},
            headers={"X-User": "tester"},
        )
        assert r.status_code == 200
        assert r.json()["added"] is False

    def test_pydantic_422_on_newline(self, _cloudium_resolver):
        r = client.post(
            "/api/file-mode/add-allowed-prefix",
            json={"prefix": "U:/path\r\nX-Injected: evil"},
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422

    def test_pydantic_422_on_empty(self, _cloudium_resolver):
        r = client.post(
            "/api/file-mode/add-allowed-prefix",
            json={"prefix": "   "},
            headers={"X-User": "tester"},
        )
        assert r.status_code == 422


class TestRemoveAllowedPrefix:
    """POST /api/file-mode/remove-allowed-prefix — 영구 저장소 갱신."""

    def test_remove_existing(self):
        cep.save_extra_prefixes(["U:/a", "U:/b"])
        r = client.post(
            "/api/file-mode/remove-allowed-prefix",
            json={"prefix": "U:/a"},
            headers={"X-User": "tester"},
        )
        assert r.status_code == 200
        assert r.json()["removed"] is True
        assert "U:/a" not in r.json()["extra_prefixes"]

    def test_remove_missing_graceful(self):
        cep.save_extra_prefixes(["U:/exists"])
        r = client.post(
            "/api/file-mode/remove-allowed-prefix",
            json={"prefix": "U:/never"},
            headers={"X-User": "tester"},
        )
        assert r.status_code == 200
        assert r.json()["removed"] is False
