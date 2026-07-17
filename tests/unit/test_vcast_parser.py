"""VectorCAST Parser 단위 테스트"""
from pathlib import Path
import pytest

from backend.services.vcast_parser import (
    VectorCASTParser,
    VCASTVersion,
    ReportType,
    CoverageItem,
    MatricsType,
    VIMLib,
    parse_vcast_report,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestCoverageItem:
    def test_parse_full_format(self):
        ci = CoverageItem("5 / 5 (100%)")
        assert ci.count == 5
        assert ci.total == 5
        assert ci.passed is True

    def test_parse_partial(self):
        ci = CoverageItem("30 / 45 (67%)")
        assert ci.count == 30
        assert ci.total == 45
        assert ci.passed is False

    def test_parse_compact(self):
        ci = CoverageItem("3/4(75%)")
        assert ci.count == 3
        assert ci.total == 4

    def test_empty(self):
        ci = CoverageItem("")
        assert ci.count == 0
        assert ci.total == 0
        assert ci.percentage == "-"

    def test_percentage(self):
        ci = CoverageItem("8 / 10 (80%)")
        assert ci.percentage == "80 %"

    def test_coverage_string(self):
        ci = CoverageItem("")
        ci.count = 3
        ci.total = 4
        assert "75" in ci.coverage


class TestVIMLib:
    def test_check_string_exists(self):
        assert VIMLib.check_string_exists("hello world", "world")
        assert not VIMLib.check_string_exists("hello", "xyz")
        assert not VIMLib.check_string_exists("", "test")
        assert not VIMLib.check_string_exists(None, "test")

    def test_get_table_contents(self):
        html = "<tr><td>A</td><td>B</td><td>C</td></tr>"
        result = VIMLib.get_table_contents(html, "td")
        assert result is not None
        assert len(result) == 3
        assert result[0] == "A"

    def test_get_table_contents_no_match(self):
        assert VIMLib.get_table_contents("no tags here", "td") is None

    def test_get_one_td_value(self):
        assert VIMLib.get_one_td_value("<td>Hello</td>") == "Hello"
        assert VIMLib.get_one_td_value("no td") == ""

    def test_substring(self):
        assert VIMLib.substring("File: test.c", ":", False) == " test.c"
        assert VIMLib.substring("File: test.c", ":", True) == "File"
        assert VIMLib.substring("no delimiter", ":", True) == ""

    def test_environment_name(self):
        html = '<td class="env">TEST_ENV</td>'
        assert VIMLib.environment_name(html) == "TEST_ENV"


class TestVectorCASTParser:
    def test_parse_metrics(self):
        path = FIXTURES / "vcast_metrics.html"
        if not path.exists():
            pytest.skip("fixture missing")
        result = parse_vcast_report(path, ReportType.Metrics)
        assert result.environment == "TEST_ENV"
        assert len(result.statement_data) > 0
        # Check specific function data
        buzzer = result.statement_data.get("Ap_BuzzerCtrl")
        assert buzzer is not None
        init = buzzer.dic_data.get("Ap_BuzzerCtrl_Init")
        assert init is not None
        assert init.complexity == 2
        assert init.statements.passed is True

    def test_parse_nonexistent_file(self):
        result = parse_vcast_report(Path("/nonexistent.html"), ReportType.Metrics)
        assert hasattr(result, "parse_error") and result.parse_error

    def test_parse_metrics_coverage_values(self):
        path = FIXTURES / "vcast_metrics.html"
        if not path.exists():
            pytest.skip("fixture missing")
        result = parse_vcast_report(path, ReportType.Metrics)
        buzzer = result.statement_data.get("Ap_BuzzerCtrl")
        process = buzzer.dic_data.get("Ap_BuzzerCtrl_Process")
        assert process is not None
        assert process.statements.count == 30
        assert process.statements.total == 45
        assert process.branches.count == 8


class TestTCBankPassedCount:
    """passed_count 는 **모든 실행 결과가 통과**한 케이스만 센다.

    회귀 배경: 예전 구현이 `any(item.passed ...)` 라 실행 10건 중 1건만 통과해도
    그 테스트 케이스를 '통과'로 셌다. 이 값은 vcast 라우터의 API 응답
    (`passed_count`)과 `failed_count = test_count - passed_count`, `pass_rate`
    로 흘러가므로 ISO 26262 시험 증거가 부풀려졌다. 이 속성엔 테스트가 **0건**
    이어서 오래 살아남았다 → 아래로 고정한다.
    """

    @staticmethod
    def _bank(spec):
        """spec: {tc_name: [passed_bool, ...]} → TCBank"""
        from backend.services.vcast_parser import TCBank, TestResultItem

        class _H:
            test_case_name = "x"

        bank = TCBank()
        bank.test_results = {
            name: [TestResultItem(header=_H(), passed=p) for p in flags]
            for name, flags in spec.items()
        }
        return bank

    def test_all_pass_counts(self):
        assert self._bank({"TC": [True, True, True]}).passed_count == 1

    def test_any_fail_does_not_count(self):
        assert self._bank({"TC": [True, False, True]}).passed_count == 0

    def test_mixed_case_is_not_a_pass(self):
        """실행 10건 중 1건만 통과 → 통과 아님 (구 any() 구현이 1로 셌다)."""
        flags = [True] + [False] * 9
        assert self._bank({"TC_MIXED": flags}).passed_count == 0

    def test_counts_only_all_pass_cases(self):
        bank = self._bank({
            "TC_MIXED": [True] + [False] * 9,
            "TC_ALLFAIL": [False, False],
            "TC_ALLPASS": [True, True],
        })
        assert bank.passed_count == 1  # TC_ALLPASS 만

    def test_empty_results(self):
        from backend.services.vcast_parser import TCBank
        assert TCBank().passed_count == 0

    def test_empty_item_list_is_not_a_pass(self):
        """실행 결과가 0건인 케이스는 통과로 세지 않는다 (all([]) is True 함정)."""
        assert self._bank({"TC_EMPTY": []}).passed_count == 0
