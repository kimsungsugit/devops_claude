"""Tests for cloudium_worker_launcher — auto-spawn 동작 단위 검증."""
from __future__ import annotations

import subprocess
import threading
from unittest.mock import patch

import pytest

from backend.services import cloudium_worker_launcher as launcher


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    """각 test가 깨끗한 env 상태에서 시작."""
    monkeypatch.delenv("CLOUDIUM_AUTO_START_WORKER", raising=False)
    yield


# ── _is_disabled — env 토글 robust truthy check (W5) ──────────────────────


@pytest.mark.parametrize("val", ["0", "false", "FALSE", "no", "off", " 0 ", "False"])
def test_is_disabled_truthy_falsy(monkeypatch, val):
    monkeypatch.setenv("CLOUDIUM_AUTO_START_WORKER", val)
    assert launcher._is_disabled() is True


@pytest.mark.parametrize("val", ["1", "true", "yes", "on", "anything-else"])
def test_is_disabled_keeps_enabled(monkeypatch, val):
    monkeypatch.setenv("CLOUDIUM_AUTO_START_WORKER", val)
    assert launcher._is_disabled() is False


def test_is_disabled_default_enabled():
    # 환경변수 미설정 → 디폴트 켜짐
    assert launcher._is_disabled() is False


# ── ensure_cloudium_worker_running — action 분기 ──────────────────────────


def test_ensure_returns_disabled_when_env_off(monkeypatch):
    monkeypatch.setenv("CLOUDIUM_AUTO_START_WORKER", "0")
    result = launcher.ensure_cloudium_worker_running()
    assert result == {"action": "disabled"}


def test_ensure_returns_already_running_when_gate_alive():
    with patch.object(launcher, "_REPO_ROOT") as _, \
         patch("backend.services.file_resolver.is_gate_running", return_value=True):
        result = launcher.ensure_cloudium_worker_running()
    assert result == {"action": "already_running"}


def test_ensure_returns_exe_missing_when_no_file(tmp_path):
    fake_root = tmp_path  # dist/excel_rename_gui_v2.exe 부재
    with patch.object(launcher, "_REPO_ROOT", fake_root), \
         patch("backend.services.file_resolver.is_gate_running", return_value=False):
        result = launcher.ensure_cloudium_worker_running()
    assert result["action"] == "exe_missing"
    assert "excel_rename_gui_v2.exe" in result["path"]


def test_ensure_spawns_when_gate_down_and_exe_present(tmp_path):
    # exe 가짜 생성
    dist = tmp_path / "dist"
    dist.mkdir()
    fake_exe = dist / "excel_rename_gui_v2.exe"
    fake_exe.write_bytes(b"fake")

    with patch.object(launcher, "_REPO_ROOT", tmp_path), \
         patch("backend.services.file_resolver.is_gate_running", return_value=False), \
         patch("subprocess.Popen") as mock_popen:
        result = launcher.ensure_cloudium_worker_running()

    assert result["action"] == "spawned"
    assert "excel_rename_gui_v2.exe" in result["path"]
    # W3 — stdio가 명시 분리됐는지
    _, kwargs = mock_popen.call_args
    assert kwargs.get("stdin") == subprocess.DEVNULL
    assert kwargs.get("stdout") == subprocess.DEVNULL
    assert kwargs.get("stderr") == subprocess.DEVNULL
    assert kwargs.get("close_fds") is True


def test_ensure_returns_failed_on_oserror(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "excel_rename_gui_v2.exe").write_bytes(b"fake")

    with patch.object(launcher, "_REPO_ROOT", tmp_path), \
         patch("backend.services.file_resolver.is_gate_running", return_value=False), \
         patch("subprocess.Popen", side_effect=OSError("PermissionError")):
        result = launcher.ensure_cloudium_worker_running()

    assert result["action"] == "failed"
    assert "PermissionError" in result["error"]


# ── W2 — is_gate_running 호출이 force=True인지 ────────────────────────────


def test_ensure_uses_force_ping_to_avoid_stale_cache(tmp_path):
    """W2 fix: TTL 캐시 우회 위해 force=True로 호출해야."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "excel_rename_gui_v2.exe").write_bytes(b"fake")

    with patch.object(launcher, "_REPO_ROOT", tmp_path), \
         patch("backend.services.file_resolver.is_gate_running", return_value=False) as mock_ping, \
         patch("subprocess.Popen"):
        launcher.ensure_cloudium_worker_running()

    # force=True 인자가 전달됐는지
    _, kwargs = mock_ping.call_args
    assert kwargs.get("force") is True


# ── W1 — Lock으로 동시 호출 race 방지 ─────────────────────────────────────


def test_ensure_lock_prevents_concurrent_spawn(tmp_path):
    """W1 fix: 두 thread가 동시에 호출해도 Popen은 1회만."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "excel_rename_gui_v2.exe").write_bytes(b"fake")

    # is_gate_running: 첫 호출 false (Lock 안에서 → spawn), 두 번째 호출은 Lock에 의해
    # 첫 spawn 끝난 후 호출되지만 실제 worker 떠 있다는 보장 없음 — 본 테스트는
    # Lock이 호출 직렬화하는지만 검증. 실제 ping은 monkeypatch
    ping_calls = []
    spawn_calls = []

    def fake_ping(*args, **kwargs):
        ping_calls.append(1)
        # 첫 호출 false (spawn 트리거), 두 번째는 true (이미 떠 있음 가정)
        return len(ping_calls) > 1

    def fake_popen(*args, **kwargs):
        spawn_calls.append(1)

    with patch.object(launcher, "_REPO_ROOT", tmp_path), \
         patch("backend.services.file_resolver.is_gate_running", side_effect=fake_ping), \
         patch("subprocess.Popen", side_effect=fake_popen):
        results = []
        threads = [
            threading.Thread(target=lambda: results.append(launcher.ensure_cloudium_worker_running()))
            for _ in range(5)
        ]
        for t in threads: t.start()
        for t in threads: t.join()

    # spawn 1회만 (나머지는 already_running)
    assert spawn_calls == [1]
    assert sum(1 for r in results if r["action"] == "spawned") == 1
    assert sum(1 for r in results if r["action"] == "already_running") == 4
