"""Unit tests for backend/helpers/session.py session/profile management."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from backend.helpers.session import (
    _augment_path,
    _default_base_report_dir,
    _exports_dir,
    _invalidate_session_cache,
    _load_raw_profiles,
    _local_reports_dir,
    _local_sts_dir,
    _local_suts_dir,
    _local_sits_dir,
    _normalize_profile,
    _resolve_base_dir,
    _save_raw_profiles,
    _session_dir,
    _session_meta_path,
    _load_session_meta,
    _save_session_meta,
    _track_process,
)
from backend.state import session_list_cache, running_processes


class TestSessionDir:
    def test_path(self, tmp_path):
        d = _session_dir(str(tmp_path), "sess_123")
        assert d == Path(tmp_path).resolve() / "sessions" / "sess_123"


class TestSessionMeta:
    def test_meta_path(self, tmp_path):
        p = _session_meta_path(tmp_path)
        assert p == tmp_path / "session_meta.json"

    def test_load_missing(self, tmp_path):
        assert _load_session_meta(tmp_path) == {}

    def test_save_and_load(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        _save_session_meta(tmp_path, {"name": "test_session"})
        meta = _load_session_meta(tmp_path)
        assert meta["name"] == "test_session"
        assert "updated_at" in meta


class TestExportsDir:
    def test_path(self, tmp_path):
        d = _exports_dir(str(tmp_path))
        assert d == Path(tmp_path).resolve() / "exports"


class TestLocalDirs:
    def test_reports_dir(self, tmp_path):
        assert _local_reports_dir(tmp_path) == tmp_path / "local_reports"

    def test_sts_dir(self, tmp_path):
        assert _local_sts_dir(tmp_path) == tmp_path / "sts"

    def test_suts_dir(self, tmp_path):
        assert _local_suts_dir(tmp_path) == tmp_path / "suts"

    def test_sits_dir(self, tmp_path):
        assert _local_sits_dir(tmp_path) == tmp_path / "sits"


class TestAugmentPath:
    def test_add_new(self):
        result = _augment_path("/usr/bin", ["/extra/bin"])
        parts = result.split(os.pathsep)
        assert "/extra/bin" in parts
        assert "/usr/bin" in parts

    def test_no_duplicates(self):
        result = _augment_path("/a" + os.pathsep + "/b", ["/a"])
        parts = result.split(os.pathsep)
        assert parts.count("/a") == 1

    def test_empty(self):
        result = _augment_path("", [])
        assert result == ""


class TestNormalizeProfile:
    def test_defaults(self):
        profile = _normalize_profile({})
        assert profile["git_incremental"] is False
        assert profile["do_build"] is False
        assert isinstance(profile["exclude_dirs"], list)

    def test_preserves_values(self):
        profile = _normalize_profile({
            "project_root": "/my/project",
            "git_incremental": True,
            "exclude_dirs": "build,tmp",
        })
        assert profile["project_root"] == "/my/project"
        assert profile["git_incremental"] is True
        assert profile["exclude_dirs"] == ["build", "tmp"]

    def test_jenkins_fields(self):
        profile = _normalize_profile({
            "jenkins_base_url": "http://ci.local",
            "jenkins_verify_tls": False,
        })
        assert profile["jenkins_base_url"] == "http://ci.local"
        assert profile["jenkins_verify_tls"] is False


class TestLoadSaveRawProfiles:
    def test_missing_file(self, monkeypatch, tmp_path):
        fake = tmp_path / "nonexistent.json"
        monkeypatch.setattr("backend.helpers.session.SETTINGS_FILE", fake)
        raw = _load_raw_profiles()
        assert raw == {"profiles": {}, "last_profile": None}

    def test_roundtrip(self, monkeypatch, tmp_path):
        fake = tmp_path / "profiles.json"
        monkeypatch.setattr("backend.helpers.session.SETTINGS_FILE", fake)
        data = {"profiles": {"p1": {"project_root": "/x"}}, "last_profile": "p1"}
        _save_raw_profiles(data)
        loaded = _load_raw_profiles()
        assert loaded["last_profile"] == "p1"
        assert "p1" in loaded["profiles"]


class TestResolveBaseDir:
    def test_default(self):
        result = _resolve_base_dir(None)
        assert isinstance(result, Path)

    def test_override_not_allowed(self):
        # ALLOW_BASE_OVERRIDE defaults to False/missing, so arbitrary paths are rejected
        with pytest.raises(Exception):
            _resolve_base_dir("/some/random/path/that/does/not/exist")


class TestInvalidateSessionCache:
    def test_clear_all(self):
        session_list_cache["test"] = ([], 0.0)
        _invalidate_session_cache()
        assert len(session_list_cache) == 0

    def test_clear_specific(self, tmp_path):
        key = str(tmp_path.resolve())
        session_list_cache[key] = ([], 0.0)
        session_list_cache["other"] = ([], 0.0)
        _invalidate_session_cache(tmp_path)
        assert key not in session_list_cache
        assert "other" in session_list_cache
        session_list_cache.clear()


class TestTrackProcess:
    def test_track(self):
        running_processes.clear()
        _track_process("sess_1", 12345, "/tmp/status.json")
        assert "sess_1" in running_processes
        info = running_processes["sess_1"]
        assert info["pid"] == 12345
        assert "started_at" in info
        running_processes.clear()
