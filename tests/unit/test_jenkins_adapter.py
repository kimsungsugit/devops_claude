"""jenkins_adapter 단위 테스트 — 현재는 _to_int 숫자 파싱 방어에 집중."""
from backend.services.jenkins_adapter import _to_int


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
