# tests/unit/test_build.py
"""Unit tests for workflow.build pure helper functions."""
from __future__ import annotations

from pathlib import Path

import pytest

from workflow.build import (
    _guess_targets_from_testname,
    triage_ctest_output,
)


class TestGuessTargetsFromTestname:
    def test_e2e(self):
        result = _guess_targets_from_testname("test_e2e_crc")
        assert "libs/e2e.c" in result

    def test_lin_master(self):
        result = _guess_targets_from_testname("test_lin_master_send")
        assert "libs/lin_master.c" in result
        assert "libs/lin_protocol.c" in result

    def test_lin_slave(self):
        result = _guess_targets_from_testname("test_lin_slave_rx")
        assert "libs/lin_slave.c" in result

    def test_rotary_switch(self):
        result = _guess_targets_from_testname("test_rotary_switch")
        assert "libs/rotary_switch.c" in result
        assert "libs/shared_data.c" in result

    def test_gateway_logic(self):
        result = _guess_targets_from_testname("test_gateway_logic")
        assert "libs/gateway_logic.c" in result

    def test_unknown_name(self):
        assert _guess_targets_from_testname("test_unknown") == []

    def test_empty(self):
        assert _guess_targets_from_testname("") == []

    def test_deduplication(self):
        result = _guess_targets_from_testname("test_shared_data")
        assert result.count("libs/shared_data.c") == 1


class TestTriageCTestOutput:
    def test_timeout(self):
        # The regex expects Start and ***Timeout on the same line
        text = "Start 1: test_lin_master ***Timeout"
        r = triage_ctest_output(text)
        assert len(r["failures"]) >= 1
        assert r["failures"][0]["type"] == "timeout"
        assert "test_lin_master" in r["timeout_tests"]

    def test_timeout_no_start(self):
        text = "***Timeout"
        r = triage_ctest_output(text)
        assert len(r["failures"]) >= 1
        assert r["failures"][0]["type"] == "timeout"

    def test_asan(self):
        text = "ERROR: AddressSanitizer: heap-buffer-overflow\nin do_stuff /reports/auto_generated/test.c:42\nStart 1: test_lin_master"
        r = triage_ctest_output(text)
        types = [f["type"] for f in r["failures"]]
        assert "asan" in types

    def test_tsan(self):
        text = "ERROR: ThreadSanitizer: data race"
        r = triage_ctest_output(text)
        types = [f["type"] for f in r["failures"]]
        assert "tsan" in types
        assert "libs/shared_data.c" in r["targets"]

    def test_assertion_failed(self):
        text = "Assertion `x == 1' failed\nStart 1: test_shared_data"
        r = triage_ctest_output(text)
        types = [f["type"] for f in r["failures"]]
        assert "assert" in types

    def test_crc_fail(self):
        text = "CRC8 Unit Tests\n[FAIL] test_poly"
        r = triage_ctest_output(text)
        types = [f["type"] for f in r["failures"]]
        assert "crc" in types
        assert "libs/e2e.c" in r["targets"]

    def test_clean_output(self):
        r = triage_ctest_output("All tests passed")
        assert r["failures"] == []
        assert r["targets"] == []
        assert r["timeout_tests"] == []

    def test_empty_string(self):
        r = triage_ctest_output("")
        assert r["failures"] == []

    def test_target_deduplication(self):
        text = "ERROR: ThreadSanitizer\nStart 1: test_shared_data"
        r = triage_ctest_output(text)
        assert len(set(r["targets"])) == len(r["targets"])
