"""Unit tests for backend/helpers/jenkins.py domain helpers."""
from __future__ import annotations

import sys
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from backend.helpers.jenkins import (
    _jenkins_exports_dir,
    _jenkins_logic_dir,
    _jenkins_sts_dir,
    _jenkins_suts_dir,
    _jenkins_templates_dir,
    _load_uds_meta,
    _normalize_filter_tokens,
    _normalize_jenkins_cache_root,
    _matches_filters,
    _resolve_cached_build_root,
    _save_uds_meta,
    _uds_meta_path,
)


class TestNormalizeJenkinsCacheRoot:
    def test_custom_path(self, tmp_path):
        result = _normalize_jenkins_cache_root(str(tmp_path))
        assert result == tmp_path.resolve()

    def test_empty_fallback(self):
        result = _normalize_jenkins_cache_root("")
        assert result == (Path.home() / ".devops_pro_cache").resolve()


class TestJenkinsDirHelpers:
    def test_exports_dir(self, tmp_path):
        d = _jenkins_exports_dir(str(tmp_path))
        assert d == tmp_path.resolve() / "exports"

    def test_templates_dir(self, tmp_path):
        d = _jenkins_templates_dir(str(tmp_path))
        assert d == tmp_path.resolve() / "templates"

    def test_logic_dir(self, tmp_path):
        d = _jenkins_logic_dir(str(tmp_path))
        assert d == tmp_path.resolve() / "exports" / "logic"

    def test_sts_dir(self, tmp_path):
        d = _jenkins_sts_dir(str(tmp_path))
        assert d == tmp_path.resolve() / "exports" / "sts"

    def test_suts_dir(self, tmp_path):
        d = _jenkins_suts_dir(str(tmp_path))
        assert d == tmp_path.resolve() / "exports" / "suts"


class TestUdsMetaPath:
    def test_path_format(self, tmp_path):
        p = _uds_meta_path(tmp_path, "my_job")
        assert p == tmp_path / "uds_meta_my_job.json"


class TestLoadSaveUdsMeta:
    def test_load_missing(self, tmp_path):
        meta = _load_uds_meta(tmp_path, "nope")
        assert meta == {"labels": {}}

    def test_save_and_load(self, tmp_path):
        _save_uds_meta(tmp_path, "test", {"labels": {"a": "1"}, "extra": "val"})
        meta = _load_uds_meta(tmp_path, "test")
        assert meta["labels"] == {"a": "1"}
        assert meta["extra"] == "val"
        assert "updated_at" in meta


class TestNormalizeFilterTokens:
    def test_basic(self):
        assert _normalize_filter_tokens(["src\\main", "lib/"]) == ["src/main", "lib"]

    def test_empty(self):
        assert _normalize_filter_tokens(None) == []
        assert _normalize_filter_tokens([]) == []


class TestMatchesFilters:
    def test_no_filters(self):
        assert _matches_filters("any/path.c", [], []) is True

    def test_include_match(self):
        assert _matches_filters("src/main.c", ["src"], []) is True
        assert _matches_filters("lib/util.c", ["src"], []) is False

    def test_exclude_match(self):
        assert _matches_filters("build/out.o", [], ["build"]) is False
        assert _matches_filters("src/main.c", [], ["build"]) is True

    def test_exclude_overrides_include(self):
        assert _matches_filters("src/test/a.c", ["src"], ["src/test"]) is False

    def test_exact_match(self):
        assert _matches_filters("src", ["src"], []) is True


class TestResolveCachedBuildRoot:
    def test_nonexistent_job(self, tmp_path):
        result = _resolve_cached_build_root(
            "http://jenkins/job/foo", str(tmp_path), "latest"
        )
        assert result is None

    def test_specific_build(self, tmp_path):
        job_dir = tmp_path / "jenkins" / "foo" / "build_42"
        job_dir.mkdir(parents=True)
        with patch("backend.helpers.jenkins._job_slug", return_value="foo"):
            result = _resolve_cached_build_root(
                "http://jenkins/job/foo", str(tmp_path), "42"
            )
        assert result is not None
        assert result.name == "build_42"

    def test_latest_build(self, tmp_path):
        for n in [1, 2, 3]:
            (tmp_path / "jenkins" / "myjob" / f"build_{n}").mkdir(parents=True)
        with patch("backend.helpers.jenkins._job_slug", return_value="myjob"):
            result = _resolve_cached_build_root(
                "http://jenkins/job/myjob", str(tmp_path), "latest"
            )
        assert result is not None
        assert "build_3" in result.name
