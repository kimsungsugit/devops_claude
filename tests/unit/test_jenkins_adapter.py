"""jenkins_adapter 단위 테스트 — _to_int 파싱 방어 + VectorCAST 결과 정규화(fail-safe)."""
from backend.services.jenkins_adapter import (
    _normalize_vcast_result,
    _summarize_vcast_tests,
    _to_int,
)


class TestToInt:
    def test_thousands_comma_not_truncated(self):
        # 회귀: re.search(r"-?\d+")가 콤마에서 멈춰 "67,464"→67로 1000배 손상하던 것 차단.
        # PRQA RCR의 LOC/파일수/진단수가 콤마 포맷일 때 발동했다.
        assert _to_int("67,464") == 67464
        assert _to_int("1,234,567") == 1234567

    def test_plain_int_and_negative(self):
        assert _to_int("881") == 881
        assert _to_int("-5") == -5
        assert _to_int(349) == 349

    def test_embedded_number_and_percent(self):
        assert _to_int("558 violations") == 558
        assert _to_int("92%") == 92

    def test_none_empty_and_nonnumeric_use_default(self):
        assert _to_int(None) == 0
        assert _to_int("") == 0
        assert _to_int("n/a") == 0
        assert _to_int("n/a", default=-1) == -1


class TestNormalizeVcastResult:
    """결과 문자열 → pass/fail/skip/unknown. fail-safe: 실패/오류를 최우선 판정."""

    def test_plain_pass_fail_skip_unknown(self):
        assert _normalize_vcast_result("PASS") == "pass"
        assert _normalize_vcast_result("FAIL") == "fail"
        assert _normalize_vcast_result("SKIPPED") == "skip"
        assert _normalize_vcast_result("") == "unknown"
        assert _normalize_vcast_result("??weird??") == "unknown"

    def test_error_folds_to_fail_despite_ok_substring(self):
        # 회귀: "TOKEN ERROR"는 'OK' 부분문자열이 있어 과거 PASS로 오분류됐다(실패 위장 = 안전 위험).
        # fail-safe 재정렬로 ERROR/FAIL이 최우선 → fail.
        assert _normalize_vcast_result("TOKEN ERROR") == "fail"
        assert _normalize_vcast_result("ENVIRONMENT ERROR") == "fail"
        assert _normalize_vcast_result("FATAL") == "fail"

    def test_not_run_is_skip(self):
        assert _normalize_vcast_result("NOT RUN") == "skip"
        assert _normalize_vcast_result("N/A") == "skip"


class TestSummarizeVcastTests:
    def test_pass_rate_over_total_includes_skip_unknown(self):
        # 통과율=통과/전체(스킵·미분류 포함) — 미실행/미분류가 있어도 100% 위장 안 됨.
        rows = [{"result": "PASS"}, {"result": "PASS"}, {"result": "FAIL"},
                {"result": "SKIPPED"}, {"result": "??weird??"}]
        s = _summarize_vcast_tests(rows)
        assert s["total"] == 5
        assert (s["passed"], s["failed"], s["skipped"], s["unknown"]) == (2, 1, 1, 1)
        assert s["pass_rate"] == 0.4

    def test_error_row_counted_as_failed_not_skip(self):
        # Finding C/D 계약: 실행오류(ERROR)는 실패로 집계된다(스킵/미분류 아님).
        s = _summarize_vcast_tests([{"result": "PASS"}, {"result": "RUNTIME ERROR"}])
        assert s["passed"] == 1 and s["failed"] == 1
        assert s["skipped"] == 0 and s["unknown"] == 0
