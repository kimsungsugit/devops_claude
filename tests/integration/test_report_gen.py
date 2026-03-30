# /app/tests/integration/test_report_gen.py
"""Integration tests for report generation pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from report.c_parsing import (
    _extract_c_prototypes,
    _extract_c_definitions,
    _extract_c_function_bodies,
    _extract_c_macros,
    _extract_c_global_candidates,
    _strip_c_comments,
)


class TestCParsingWithSampleFile:
    """Test C parsing functions against the sample.c fixture."""

    @pytest.fixture(autouse=True)
    def _load_sample(self, fixtures_dir: Path):
        p = fixtures_dir / "sample.c"
        if p.exists():
            self.raw_text = p.read_text(encoding="utf-8")
            self.clean_text = _strip_c_comments(self.raw_text)
        else:
            pytest.skip("sample.c fixture not found")

    def test_extract_definitions(self):
        defs = _extract_c_definitions(self.clean_text)
        names = [d[0] for d in defs]
        assert "g_comm_init" in names
        assert "g_process_frame" in names
        assert "s_get_counter" in names

    def test_extract_static_function(self):
        defs = _extract_c_definitions(self.clean_text)
        for name, params, is_static in defs:
            if name == "s_get_counter":
                assert is_static is True
                break
        else:
            pytest.fail("s_get_counter not found in definitions")

    def test_extract_function_bodies(self):
        bodies = _extract_c_function_bodies(self.clean_text)
        assert "g_comm_init" in bodies
        assert "g_counter = 0" in bodies["g_comm_init"]

    def test_extract_macros(self):
        macros = _extract_c_macros(self.raw_text)
        assert "MAX_BUFFER_SIZE" in macros
        assert "VERSION_MAJOR" in macros

    def test_extract_globals(self):
        globals_list = _extract_c_global_candidates(self.clean_text)
        names = [g["name"] for g in globals_list]
        assert "g_counter" in names


class TestHeaderParsing:
    """Test parsing of the sample.h fixture."""

    @pytest.fixture(autouse=True)
    def _load_header(self, fixtures_dir: Path):
        p = fixtures_dir / "sample.h"
        if p.exists():
            self.text = p.read_text(encoding="utf-8")
        else:
            pytest.skip("sample.h fixture not found")

    def test_extract_prototypes(self):
        protos = _extract_c_prototypes(self.text)
        names = [p[0] for p in protos]
        assert "g_comm_init" in names
        assert "g_process_frame" in names
        assert "g_comm_reset" in names

    def test_extern_flag(self):
        protos = _extract_c_prototypes(self.text)
        for name, params, is_extern in protos:
            if name == "g_comm_init":
                assert is_extern is True
                break
