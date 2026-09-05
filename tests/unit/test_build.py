# tests/unit/test_build.py
"""Unit tests for workflow.build pure helper functions."""
from __future__ import annotations

from workflow.build import (
    _guess_targets_from_testname,
    _overall_tests_ok,
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


class TestOverallTestsOk:
    """전체 테스트 통과 판정 (deep-review B8).

    named 테스트가 없어 __all__ 센티널(name=None)만 있을 때, 예전 인라인은 all([])=무조건
    True 라 stability_gate 에서 exit≠0 도 통과로 위장했다. 이제 센티널 exit_code 로 판정.
    """

    def test_named_tests_all_pass(self):
        assert _overall_tests_ok(
            [{"name": "t1", "exit_code": 0}, {"name": "t2", "exit_code": 0}], []) is True

    def test_named_test_fails(self):
        assert _overall_tests_ok(
            [{"name": "t1", "exit_code": 0}, {"name": "t2", "exit_code": 1}], []) is False

    def test_all_sentinel_nonzero_is_not_vacuous_pass(self):
        """핵심 B8 — __all__ 센티널만(name=None) 있고 exit≠0 이면 통과 아님.

        stability_gate 는 2회 실행이라 __all__ 이 2개(name=None) — 예전 all([])=True 로
        exit≠0 을 무시했다. 뮤테이션: 이 판정을 `all(... if name is not None)` 로 되돌리면
        all([])=True 가 돼 실패.
        """
        results = [{"name": None, "exit_code": 8}, {"name": None, "exit_code": 8}]
        assert _overall_tests_ok(results, []) is False

    def test_all_sentinel_zero_no_tests_tolerated(self):
        """대조: __all__ exit0(=테스트 없음)은 파이프라인 의도상 통과(tolerance 유지)."""
        assert _overall_tests_ok([{"name": None, "exit_code": 0}], []) is True

    def test_unstable_forces_fail(self):
        assert _overall_tests_ok([{"name": "t1", "exit_code": 0}], ["t1"]) is False

    def test_empty_results_is_not_pass(self):
        assert _overall_tests_ok([], []) is False
