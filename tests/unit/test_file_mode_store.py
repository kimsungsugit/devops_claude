"""Tests for file-mode persistence (config/file_mode.json).

`/api/file-mode`로 전환한 local/cloudium 모드는 in-memory resolver 싱글톤에만
반영돼 backend 재시작 시 소실됐다. file_mode_store가 선택을 디스크에 영속하고
`file_resolver._build_initial_resolver()`가 startup 시 env보다 우선 적용한다.
저장/로드 정확성 + 손상 graceful + 복원 precedence(영속 > env > local)를 고정한다.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

import backend.services.file_mode_store as store


@pytest.fixture
def tmp_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """MODE_PATH를 임시 경로로, 락을 단순 threading.Lock으로 격리."""
    p = tmp_path / "file_mode.json"
    monkeypatch.setattr(store, "MODE_PATH", p)
    monkeypatch.setattr(store, "_LOCK", threading.Lock())
    return p


def test_load_none_when_absent(tmp_store: Path) -> None:
    assert store.load_file_mode() is None


def test_save_load_cloudium_roundtrip(tmp_store: Path) -> None:
    store.save_file_mode("cloudium", allowed_prefixes="U:/proj,U:/lib", gate_process="x.exe")
    assert tmp_store.exists()
    loaded = store.load_file_mode()
    assert loaded == {
        "mode": "cloudium",
        "allowed_prefixes": "U:/proj,U:/lib",
        "gate_process": "x.exe",
    }


def test_save_load_local(tmp_store: Path) -> None:
    store.save_file_mode("local")
    loaded = store.load_file_mode()
    assert loaded is not None and loaded["mode"] == "local"


def test_save_invalid_mode_is_noop(tmp_store: Path) -> None:
    store.save_file_mode("bogus")
    assert not tmp_store.exists()
    assert store.load_file_mode() is None


def test_load_invalid_mode_returns_none(tmp_store: Path) -> None:
    tmp_store.write_text('{"mode": "weird", "schema_version": 1}', encoding="utf-8")
    assert store.load_file_mode() is None


def test_load_corrupt_file_graceful(tmp_store: Path) -> None:
    tmp_store.write_text("{ not json", encoding="utf-8")
    assert store.load_file_mode() is None
    # 손상 파일은 .invalid.json으로 backup, 원본은 사라짐
    assert not tmp_store.exists()
    assert tmp_store.with_suffix(".invalid.json").exists()


def test_clear_file_mode(tmp_store: Path) -> None:
    store.save_file_mode("cloudium", allowed_prefixes="U:/x")
    assert tmp_store.exists()
    store.clear_file_mode()
    assert not tmp_store.exists()
    # 미존재 상태에서 재호출해도 에러 없음
    store.clear_file_mode()


# ── 복원 precedence: 영속 > env > local ─────────────────────────────

def test_build_initial_resolver_restores_persisted_cloudium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.services.file_resolver as fr
    monkeypatch.setattr(store, "load_file_mode", lambda: {
        "mode": "cloudium", "allowed_prefixes": "U:/proj", "gate_process": "",
    })
    r = fr._build_initial_resolver()
    assert r.mode == "cloudium"
    assert "U:/proj" in r.allowed_prefixes


def test_build_initial_resolver_persisted_local_beats_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.services.file_resolver as fr
    monkeypatch.setattr(store, "load_file_mode", lambda: {
        "mode": "local", "allowed_prefixes": "", "gate_process": "",
    })
    monkeypatch.setenv("DEVOPS_FILE_MODE", "cloudium")  # 영속이 우선해야 함
    r = fr._build_initial_resolver()
    assert r.mode == "local"


def test_build_initial_resolver_env_fallback_when_no_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.services.file_resolver as fr
    monkeypatch.setattr(store, "load_file_mode", lambda: None)
    monkeypatch.setenv("DEVOPS_FILE_MODE", "cloudium")
    r = fr._build_initial_resolver()
    assert r.mode == "cloudium"


def test_build_initial_resolver_defaults_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.services.file_resolver as fr
    monkeypatch.setattr(store, "load_file_mode", lambda: None)
    monkeypatch.delenv("DEVOPS_FILE_MODE", raising=False)
    r = fr._build_initial_resolver()
    assert r.mode == "local"
