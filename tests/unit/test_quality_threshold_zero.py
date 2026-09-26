"""품질 사유 코드 — **임계 0 은 "축을 끈다" 이지 "가장 엄격" 이 아니다**.

## 왜 이 파일이 필요했나

`_derive_quality_reason_codes` 가 호출부마다 이렇게 읽고 있었다:

    if called < float((thresholds or {}).get("called_min") or 95.0):

`0.0` 은 falsy 다. 운영자가 축을 끄려고 `UDS_CALLED_MIN=0` 을 넣으면 `or` 가 그걸
**95.0 으로 뒤집는다**. 같은 임계를 `gate_pass` 는 `rate >= thresholds["called_min"]` 로
**직접** 읽으므로 정상 동작한다 — 즉 두 계산이 같은 설정을 반대로 해석했다.

실측(2026-09-02): 12개 임계를 전부 0 으로 두면
  · `gate_pass` = **True** (모든 축이 꺼진다)
  · 사유 코드 = **12건 전부 `*_LOW`**
→ **통과 판정인데 사유는 전부 미달.** 화면의 조치 제안(`_build_quality_action_hints`)도
  운영자가 일부러 끈 축을 고치라고 말한다.

부수 결함: 폴백 숫자 12개가 호출부에 **복제**돼 있었다. 오늘은 config 와 일치하지만
config 가 바뀌면 조용히 갈리고, 그 숫자가 사실 행세를 한다(이 저장소가 겪은 형태).
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

THRESHOLD_KEYS = (
    "called_min", "calling_min", "input_min", "output_min", "global_min", "static_min",
    "description_min", "asil_min", "related_min",
    "description_trusted_min", "asil_trusted_min", "related_trusted_min",
)
RATE_KEYS = (
    "called_fill", "calling_fill", "input_fill", "output_fill", "global_fill", "static_fill",
    "description_fill", "asil_fill", "related_fill",
    "description_trusted_fill", "asil_trusted_fill", "related_trusted_fill",
)

# `gate_pass`(`_compute_quick_quality_gate`)가 실제로 보는 7축 — 사유와 lockstep 이어야 한다.
GATED_PAIRS = (
    ("called_fill", "called_min", "CALLED_LOW"),
    ("calling_fill", "calling_min", "CALLING_LOW"),
    ("input_fill", "input_min", "INPUT_PARSE_LOW"),
    ("output_fill", "output_min", "OUTPUT_PARSE_LOW"),
    ("description_fill", "description_min", "DESCRIPTION_LOW"),
    ("asil_fill", "asil_min", "ASIL_LOW"),
    ("related_fill", "related_min", "RELATED_ID_LOW"),
)


def _codes(rates: Dict[str, float], thresholds: Any, total: int = 100) -> List[str]:
    from backend.helpers.uds import _derive_quality_reason_codes

    return _derive_quality_reason_codes(
        {"rates": rates, "thresholds": thresholds, "counts": {"total_functions": total}})


def _zero_rates() -> Dict[str, float]:
    return {k: 0.0 for k in RATE_KEYS}


# ==============================================================
# 1. 0 은 유효한 임계다
# ==============================================================

class TestZeroIsARealThreshold:

    def test_all_thresholds_zero_silences_the_threshold_codes(self):
        """축을 전부 끄면 임계 기반 사유는 남지 않는다(예전엔 12건 전부 나왔다)."""
        got = _codes(_zero_rates(), {k: 0.0 for k in THRESHOLD_KEYS})
        for _, _, code in GATED_PAIRS:
            assert code not in got, f"{code} 가 임계 0 에서도 나온다: {got}"

    def test_calling_zero_survives_because_it_is_not_a_threshold(self):
        """대조군 — `CALLING_ZERO` 는 "데이터가 아예 없다" 는 **진단**이지 임계 판정이
        아니다. 임계를 껐다고 사라지면 파서가 안 돈 사실까지 숨긴다.

        (R31 Q-7) 단, 축을 껐으면 판정은 **통과**이므로 그 진단은 사유 목록이 아니라
        정보 목록(`_derive_quality_info_codes`)에 남는다 — 통과 판정에 사유가 붙으면 모순.
        """
        from backend.helpers.uds import _derive_quality_info_codes

        thr = {k: 0.0 for k in THRESHOLD_KEYS}
        assert _codes(_zero_rates(), thr) == [], "축이 전부 꺼졌으면 사유는 0개"
        info = _derive_quality_info_codes(
            {"rates": _zero_rates(), "thresholds": thr, "counts": {"total_functions": 100}})
        assert "CALLING_ZERO" in info, "진단은 사라지면 안 된다 — 정보 등급으로 남는다"

    @pytest.mark.parametrize("rate_key,thr_key,code", GATED_PAIRS)
    def test_each_axis_can_be_switched_off_individually(self, rate_key, thr_key, code):
        """한 축만 꺼도 그 축의 사유만 사라진다 — 전체를 끄는 것과 구분된다.

        ⚠ 미달값을 `0.0` 으로 두면 안 된다: `calling` 축은 `0.0` 에서 `CALLING_ZERO`
          분기로 빠져 `CALLING_LOW` 가 **원리적으로** 안 나온다(임계와 무관).
          0 이 아니면서 임계 미만인 값을 써야 이 테스트가 임계를 재게 된다.
        """
        base = {k: 100.0 for k in RATE_KEYS}
        base[rate_key] = 10.0          # 0 아님 · 임계(50) 미만
        default_thr = {k: 50.0 for k in THRESHOLD_KEYS}
        assert code in _codes(base, default_thr), "임계 50 이면 미달이어야 한다"
        off = dict(default_thr, **{thr_key: 0.0})
        assert code not in _codes(base, off), f"{thr_key}=0 인데 {code} 가 남는다"

    def test_the_verdict_and_the_reason_use_the_same_threshold(self):
        """`gate_pass`(`>=`)와 사유(`<`)는 **여집합**이어야 한다.

        예전엔 같은 설정을 반대로 읽어, 통과 판정에 미달 사유가 붙었다.
        """
        rates = {k: 60.0 for k in RATE_KEYS}
        thr = {k: 60.0 for k in THRESHOLD_KEYS}      # 정확히 경계값
        got = _codes(rates, thr)
        for rate_key, thr_key, code in GATED_PAIRS:
            passes = rates[rate_key] >= thr[thr_key]   # gate_pass 의 판정식
            assert (code not in got) == passes, f"{code}: 판정과 사유가 어긋난다 ({got})"


# ==============================================================
# 2. 기본값은 config 단일 출처
# ==============================================================

class TestDefaultsComeFromConfig:

    @pytest.mark.parametrize("key", THRESHOLD_KEYS)
    def test_missing_key_falls_back_to_config_not_a_copied_literal(self, key):
        import config
        from backend.helpers.uds import _quality_threshold

        assert _quality_threshold({}, key) == float(config.UDS_QUALITY_GATE_THRESHOLDS[key])

    def test_changing_config_changes_the_fallback(self, monkeypatch):
        """⚠ 복제된 리터럴이면 config 를 바꿔도 안 따라온다 — 그게 옛 결함이었다."""
        import config
        from backend.helpers.uds import _quality_threshold

        patched = dict(config.UDS_QUALITY_GATE_THRESHOLDS)
        patched["called_min"] = 12.5
        monkeypatch.setattr(config, "UDS_QUALITY_GATE_THRESHOLDS", patched)
        assert _quality_threshold({}, "called_min") == 12.5

    def test_no_literal_thresholds_remain_in_the_derivation(self):
        """호출부에 숫자가 다시 박히면 같은 결함이 되살아난다 — 소스로 확인.

        ⚠ `inspect.getsource` 가 아니라 `source_of` 를 쓴다: 전자는 **import 시점의**
          줄 번호를 지금 디스크 파일에 적용해, 게이트가 도는 동안 다른 세션이 그 파일을
          저장하면 **다른 함수**를 보고 거짓 실패한다(`tests/unit/_source_probe.py` 참조).
        """
        from backend.helpers.uds import _derive_quality_reason_codes
        from tests.unit._source_probe import source_of

        src = source_of(_derive_quality_reason_codes)
        assert '_min") or ' not in src, src
        assert "_min') or " not in src, src


# ==============================================================
# 3. 임계가 아예 없으면 사유를 지어내지 않는다
# ==============================================================

class TestNoThresholdMeansNoJudgement:

    def test_absent_everywhere_is_none_not_a_number(self):
        from backend.helpers.uds import _quality_threshold

        assert _quality_threshold({}, "no_such_min") is None

    def test_an_axis_with_no_threshold_anywhere_emits_no_reason(self, monkeypatch):
        """⚠ 이 경로는 **config 에 12키가 다 있어서** 평소엔 안 탄다 — 그래서
        "임계가 없으면 항상 미달" 로 바꾸는 뮤턴트가 처음엔 살아남았다.

        config 에서 키가 사라지는 일은 실제로 가능하다(설정 정리·오타·부분 override).
        그때 판정 불가를 **미달로 몰면** 고칠 수 없는 사유가 영구히 붙는다.
        """
        import config
        from backend.helpers.uds import _quality_threshold

        patched = {k: v for k, v in config.UDS_QUALITY_GATE_THRESHOLDS.items()
                   if k != "called_min"}
        monkeypatch.setattr(config, "UDS_QUALITY_GATE_THRESHOLDS", patched)

        assert _quality_threshold({}, "called_min") is None
        # 임계가 어디에도 없다 → 그 축의 사유를 만들지 않는다(다른 축은 그대로).
        got = _codes(_zero_rates(), {})
        assert "CALLED_LOW" not in got, got
        assert "INPUT_PARSE_LOW" in got, "다른 축까지 조용해지면 안 된다"

    def test_a_non_numeric_threshold_falls_back_instead_of_crashing(self):
        import config
        from backend.helpers.uds import _quality_threshold

        assert _quality_threshold({"called_min": "높게"}, "called_min") == float(
            config.UDS_QUALITY_GATE_THRESHOLDS["called_min"])

    def test_thresholds_not_a_dict_is_tolerated(self):
        """`quick_gate` 가 없거나 모양이 다른 호출 경로가 있다 — 죽지 않아야 한다."""
        got = _codes(_zero_rates(), None)
        assert "CALLED_LOW" in got      # config 기본값으로 판정한다


# ==============================================================
# 4. 회귀 대조군 — 기본 설정에서는 예전과 같이 동작한다
# ==============================================================

class TestDefaultBehaviourUnchanged:

    def test_default_thresholds_still_flag_a_bad_document(self):
        got = _codes(_zero_rates(), dict.fromkeys(THRESHOLD_KEYS))  # 값 None → config 폴백
        for _, _, code in GATED_PAIRS:
            assert code in got or code == "CALLING_LOW", got

    def test_a_perfect_document_gets_no_threshold_codes(self):
        got = _codes({k: 100.0 for k in RATE_KEYS}, {})
        assert got == [], got

    def test_no_functions_is_still_reported(self):
        got = _codes({k: 100.0 for k in RATE_KEYS}, {}, total=0)
        assert "NO_FUNCTIONS" in got
