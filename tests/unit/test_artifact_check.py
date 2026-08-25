# tests/unit/test_artifact_check.py
"""생성 수 ↔ 파일 기록 수 대조 — 세 생성기 공용 판정의 단일 출처 테스트.

회귀 대상: STS/SUTS/SITS 파이프라인이 `validate_*_xlsm(out)` 을 부르고 그 결과를
그대로 돌려주면서 **생성한 개수와 대조하지 않았다**. `validate_*` 는 "0건인가" 만 보므로
라이터가 절반을 흘려도 `valid: True` 가 나오고, 호출자에게 가는 `test_case_count` 는
파일이 아니라 생성기가 세어준 값이라 아무도 눈치채지 못한다.

SUTS 는 `expected_tc_range`/`expected_seq_range` 인자를 **가지고 있었는데도** 호출부
4곳이 전부 기본값 None 이라 그 대조가 한 번도 실행된 적이 없었다.
"""
from __future__ import annotations

import ast

import pytest

from generators._artifact_check import apply_write_back_check, compare_generated_vs_written
from tests.unit._source_probe import source_of


class TestCompareGeneratedVsWritten:
    def test_match_reports_nothing(self):
        assert compare_generated_vs_written(
            {"tc_count": 120, "sub_case_count": 1288},
            {"tc_count": 120, "sub_case_count": 1288, "sheets": ["a"]},
        ) == []

    def test_shortfall_is_reported_with_delta(self):
        [msg] = compare_generated_vs_written({"tc_count": 120}, {"tc_count": 90})
        assert "120" in msg and "90" in msg and "-30" in msg

    def test_surplus_is_reported_too(self):
        """파일에 더 많은 것도 이상 신호다 — 한 방향만 보면 중복 기록을 놓친다."""
        [msg] = compare_generated_vs_written({"tc_count": 10}, {"tc_count": 12})
        assert "+2" in msg

    @pytest.mark.parametrize("stats", [{}, {"tc_count": None}])
    def test_missing_key_is_not_a_pass(self, stats):
        """되읽지 못한 것을 통과로 바꾸면 fail-open 이다(미측정 ≠ 유효)."""
        [msg] = compare_generated_vs_written({"tc_count": 10}, stats)
        assert "대조 불가" in msg

    def test_non_numeric_is_not_a_pass(self):
        [msg] = compare_generated_vs_written({"tc_count": 10}, {"tc_count": "많음"})
        assert "대조 불가" in msg

    def test_every_key_is_checked_not_just_the_first(self):
        msgs = compare_generated_vs_written(
            {"tc_count": 10, "sub_case_count": 20}, {"tc_count": 1, "sub_case_count": 2})
        assert len(msgs) == 2

    def test_empty_expectation_is_vacuously_clean(self):
        assert compare_generated_vs_written({}, {"tc_count": 5}) == []


class TestApplyWriteBackCheck:
    def test_mismatch_downgrades_valid(self):
        v = apply_write_back_check(
            {"valid": True, "issues": [], "stats": {"tc_count": 7}}, {"tc_count": 10})
        assert v["valid"] is False
        assert len(v["issues"]) == 1

    def test_match_keeps_existing_verdict(self):
        v = apply_write_back_check(
            {"valid": True, "issues": [], "stats": {"tc_count": 10}}, {"tc_count": 10})
        assert v["valid"] is True
        assert v["issues"] == []

    def test_existing_issues_are_preserved(self):
        """다른 검사의 결과를 덮어쓰면 안 된다."""
        v = apply_write_back_check(
            {"valid": False, "issues": ["기존 문제"], "stats": {"tc_count": 7}},
            {"tc_count": 10})
        assert "기존 문제" in v["issues"]
        assert len(v["issues"]) == 2

    def test_records_that_the_check_ran(self):
        """'대조하고 통과' 와 '대조를 아예 안 함' 이 둘 다 issues 빈 리스트면 구분이 안 된다."""
        v = apply_write_back_check(
            {"valid": True, "issues": [], "stats": {"tc_count": 10}}, {"tc_count": 10})
        wb = v["stats"]["write_back_check"]
        assert wb["passed"] is True
        assert wb["expected"] == {"tc_count": 10}
        assert wb["mismatches"] == []

    def test_missing_stats_dict_is_created_not_crashed(self):
        v = apply_write_back_check({"valid": True, "issues": []}, {"tc_count": 10})
        assert v["valid"] is False          # 되읽은 값이 없으니 대조 불가 = 통과 아님
        assert "write_back_check" in v["stats"]

    def test_non_dict_validation_does_not_crash(self):
        v = apply_write_back_check(None, {"tc_count": 10})   # type: ignore[arg-type]
        assert v["valid"] is False

    def test_non_list_issues_is_replaced_not_crashed(self):
        v = apply_write_back_check(
            {"valid": True, "issues": "문자열", "stats": {"tc_count": 1}}, {"tc_count": 2})
        assert isinstance(v["issues"], list) and len(v["issues"]) == 1


class TestAllThreePipelinesAreWired:
    """한 곳만 배선하면 나머지가 잠복한다 — 이 저장소가 반복해 겪은 실패 모드."""

    @pytest.mark.parametrize(
        ("module_name", "func_name"),
        [("generators.sts", "generate_sts"),
         ("generators.suts", "generate_suts"),
         ("generators.sits", "generate_sits")],
    )
    def test_pipeline_calls_the_shared_check(self, module_name, func_name):
        import importlib

        mod = importlib.import_module(module_name)
        tree = ast.parse(source_of(getattr(mod, func_name)))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "apply_write_back_check" in called, (
            f"{module_name}.{func_name} 가 생성↔기록 대조를 안 한다")
