"""Tests for cloudium_worker_launcher — auto-spawn 동작 단위 검증."""
from __future__ import annotations

import subprocess
import threading
from unittest.mock import patch

import pytest

from backend.services import cloudium_worker_launcher as launcher


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    """각 test가 깨끗한 env 상태에서 시작.

    ⚠ 준비 대기(`CLOUDIUM_WORKER_READY_TIMEOUT`)는 **0 으로 명시**한다. 기본값(8초)이면
    gate 를 '영원히 down' 으로 mock 한 테스트가 매번 상한까지 기다려 스위트가 느려진다
    (실측: 두 테스트가 각 8.02초 — 도입 직후 이 파일이 0.4초에서 16.8초가 됐다).
    대기 자체의 계약은 아래 전용 테스트가 예산을 직접 주고 검증한다.
    """
    monkeypatch.delenv("CLOUDIUM_AUTO_START_WORKER", raising=False)
    monkeypatch.setenv("CLOUDIUM_WORKER_READY_TIMEOUT", "0")
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
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    # spawn 1회만 (나머지는 already_running)
    assert spawn_calls == [1]
    assert sum(1 for r in results if r["action"] == "spawned") == 1
    assert sum(1 for r in results if r["action"] == "already_running") == 4


# ── spawn 후 준비 대기 (2026-08-07) ────────────────────────────────────────
#
# spawn 직후 바로 반환하면 worker TCP 서버가 뜨기 전에 도착한 요청이 전부 **403
# "접근 거부"** 가 된다. 실체는 '아직 준비 중'인데 사용자에겐 권한 문제로 보인다.
# (실측: 백엔드 기동 직후 매트릭스 체인 8단계가 전부 403. 게이트 캐시 TTL 이 1초라
#  나중엔 자가 회복되지만, 그 창에 걸린 요청은 그냥 실패한다.)


def _spawn_env(tmp_path, monkeypatch, budget: str):
    exe = tmp_path / "dist" / "excel_rename_gui_v2.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("stub")
    monkeypatch.setenv("CLOUDIUM_WORKER_READY_TIMEOUT", budget)
    return exe


def test_spawn_waits_until_worker_ready(tmp_path, monkeypatch):
    """down → down → up 으로 바뀌면 ready=True 로 돌아온다."""
    _spawn_env(tmp_path, monkeypatch, "5")
    seq = [False, False, False, True]   # 첫 호출은 spawn 판정용

    with patch.object(launcher, "_REPO_ROOT", tmp_path), \
         patch("backend.services.file_resolver.is_gate_running",
               side_effect=lambda *a, **k: seq.pop(0) if seq else True), \
         patch("subprocess.Popen"), \
         patch.object(launcher.time, "sleep"):     # 실제로 자지 않는다(스위트 지연 방지)
        out = launcher.ensure_cloudium_worker_running()

    assert out["action"] == "spawned"
    assert out["ready"] is True, "worker 가 떴는데 준비 안 됨으로 보고했다"


def test_spawn_not_ready_is_reported_not_hidden(tmp_path, monkeypatch):
    """상한 내에 안 뜨면 **ready=False 를 명시**한다 — 성공으로 위장 금지.

    ⚠ 예산을 작게 준다. `sleep` 을 mock 해도 루프는 deadline 까지 spin 하므로 예산이
    곧 실제 소요다(1초로 뒀더니 이 테스트만 1.00초였다).
    """
    _spawn_env(tmp_path, monkeypatch, "0.2")

    with patch.object(launcher, "_REPO_ROOT", tmp_path), \
         patch("backend.services.file_resolver.is_gate_running", return_value=False), \
         patch("subprocess.Popen"), \
         patch.object(launcher.time, "sleep"):
        out = launcher.ensure_cloudium_worker_running()

    assert out["action"] == "spawned"
    assert out["ready"] is False, "안 떴는데 준비됨으로 보고했다"
    assert "waited_s" in out, "얼마나 기다렸는지 안 알려준다"


def test_ready_budget_0_means_no_wait(tmp_path, monkeypatch):
    """예산 0 은 옛 동작(대기 없음) — 테스트/CI 가 상한만큼 멎지 않게."""
    _spawn_env(tmp_path, monkeypatch, "0")
    slept = []

    with patch.object(launcher, "_REPO_ROOT", tmp_path), \
         patch("backend.services.file_resolver.is_gate_running", return_value=False), \
         patch("subprocess.Popen"), \
         patch.object(launcher.time, "sleep", side_effect=lambda s: slept.append(s)):
        out = launcher.ensure_cloudium_worker_running()

    assert out["ready"] is False and slept == [], "예산 0 인데 잤다"


def test_already_running_never_waits(tmp_path, monkeypatch):
    """가장 흔한 경로(이미 떠 있음)에 지연을 얹지 않는다.

    ⚠ `sleep` 호출 여부로 단언하면 안 된다 — gate 가 떠 있으면 `_wait_ready` 도 첫 검사에서
    바로 돌아와 **자지 않는다**. 그래서 대기를 얹는 변형이 그대로 통과한다(뮤테이션 M3 생존).
    대기 함수가 **불렸는지**를 본다.
    """
    _spawn_env(tmp_path, monkeypatch, "30")
    waits = []

    with patch.object(launcher, "_REPO_ROOT", tmp_path), \
         patch("backend.services.file_resolver.is_gate_running", return_value=True), \
         patch.object(launcher, "_wait_ready",
                      side_effect=lambda *a, **k: waits.append(a) or (True, 0.0)):
        out = launcher.ensure_cloudium_worker_running()

    assert out["action"] == "already_running"
    assert waits == [], "이미 떠 있는데 준비 대기를 탔다"


def test_wait_ready_는_예산이_0이면_한번도_자지_않는다(monkeypatch):
    """`sleep` 이 deadline 검사보다 먼저 오면 예산 0 에도 최소 1회 지연이 생긴다."""
    slept = []
    with patch("backend.services.file_resolver.is_gate_running", return_value=False), \
         patch.object(launcher.time, "sleep", side_effect=lambda s: slept.append(s)):
        ready, waited = launcher._wait_ready(0.0)
    assert ready is False and waited == 0.0
    assert slept == [], "예산 0 인데 잤다"


def test_wait_ready_는_기한이_지났으면_자기_전에_끝낸다():
    """deadline 검사가 `sleep` **뒤로** 가면 이미 지난 기한에도 한 번 잔다.

    시계를 통제해 순서만 가른다 — 예산 0 은 shortcut 을 타 루프에 안 들어가므로
    이 결함을 못 가른다(뮤테이션 M4 가 그래서 처음에 생존했다).
    """
    slept = []
    clock = iter([0.0] + [100.0] * 20)   # 첫 호출=deadline 계산, 이후는 기한 경과
    with patch("backend.services.file_resolver.is_gate_running", return_value=False), \
         patch.object(launcher.time, "monotonic", side_effect=lambda: next(clock)), \
         patch.object(launcher.time, "sleep", side_effect=lambda s: slept.append(s)):
        ready, _waited = launcher._wait_ready(1.0)
    assert ready is False
    assert slept == [], "기한이 이미 지났는데 잤다 — deadline 검사가 sleep 뒤에 있다"


def test_wait_ready_는_이미_준비면_자지_않는다(monkeypatch):
    slept = []
    with patch("backend.services.file_resolver.is_gate_running", return_value=True), \
         patch.object(launcher.time, "sleep", side_effect=lambda s: slept.append(s)):
        ready, waited = launcher._wait_ready(30.0)
    assert ready is True and waited == 0.0
    assert slept == [], "이미 준비됐는데 잤다"


@pytest.mark.parametrize(("val", "expect"), [("8", 8.0), ("0", 0.0), ("2.5", 2.5),
                                             ("헛소리", 8.0), ("-3", 0.0)])
def test_ready_budget_parsing(monkeypatch, val, expect):
    """잘못된 값이 예외로 기동을 죽이지 않고 기본값으로 떨어진다."""
    monkeypatch.setenv("CLOUDIUM_WORKER_READY_TIMEOUT", val)
    assert launcher._ready_budget_s() == expect
