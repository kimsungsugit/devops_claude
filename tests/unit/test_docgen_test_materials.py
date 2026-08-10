"""시험 문서 재료 측정 — **캡 여유**와 **타입 근거**가 이 파일의 본체다.

0단계 실측이 지목한 두 함정을 회귀로 고정한다:

1. **"절단 0" 은 안전하다는 뜻이 아니다.** KJPDS02 는 후보 120 / 캡 120 으로 경계에
   정확히 닿아 있어, 함수가 하나만 늘어도 조용히 잘리기 시작한다. 그래서 절단 건수가
   아니라 **여유**를 본다.
2. **타입 폴백은 반환값으로 판정할 수 없다.** `infer_variable_type` 의 폴백이
   `"uint8_t"` 인데 진짜 u8 도 같은 값이다 — 0단계 측정도 처음엔 반환값으로 세어
   "100% 확정" 이라는 거짓 수치를 냈다.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from backend.services import docgen_test_materials as tm


def _fn(name: str, file: str, calls: list[str], *, asil: str = "QM",
        inputs: list[str] | None = None) -> Dict[str, Any]:
    return {
        "name": name, "file": file, "calls_list": list(calls),
        "asil": asil, "inputs": list(inputs or []), "outputs": [],
    }


def _cross_module_details(n_flows: int) -> Dict[str, Any]:
    """진입점 n개가 각각 **다른 모듈**의 함수를 호출하는 최소 구조."""
    fd: Dict[str, Any] = {}
    for i in range(n_flows):
        entry, callee = f"Mod{i}_Entry", f"Other{i}_Callee"
        fd[entry] = _fn(entry, f"src/Mod{i}.c", [callee])
        fd[callee] = _fn(callee, f"src/Other{i}.c", [])
    return fd


# ── SITS 흐름 / 캡 ──────────────────────────────────────────────────────────

def test_flows_total_is_measured_before_cap() -> None:
    """총량은 **캡 전** 값이어야 한다 — 결과 길이로 되짚으면 절단을 못 본다."""
    from generators.sits import _DEFAULT_MAX_FLOWS

    fd = _cross_module_details(_DEFAULT_MAX_FLOWS + 5)
    res = tm._measure_sits(fd, {}, "")
    assert res["flows_total"] == _DEFAULT_MAX_FLOWS + 5
    assert res["cap"] == _DEFAULT_MAX_FLOWS


def test_headroom_not_dropped_count() -> None:
    """캡을 안 넘겨도 **여유**를 낸다. '절단 0' 만 보면 경계 상태를 못 본다."""
    fd = _cross_module_details(10)
    res = tm._measure_sits(fd, {}, "")
    assert res["headroom"] == res["cap"] - 10
    assert res["at_cap_boundary"] is False


def test_at_cap_boundary_flags_zero_headroom() -> None:
    """후보 수 == 캡이면 지금은 절단 0 이지만 **경계**다 — 함수 하나만 늘면 잘린다."""
    from generators.sits import _DEFAULT_MAX_FLOWS

    fd = _cross_module_details(_DEFAULT_MAX_FLOWS)
    res = tm._measure_sits(fd, {}, "")
    assert res["flows_total"] == _DEFAULT_MAX_FLOWS
    assert res["headroom"] == 0
    assert res["at_cap_boundary"] is True


def test_collect_flows_accepts_none_for_uncapped() -> None:
    """`max_flows=None` 이 캡 없음 계약이다(시그니처가 이걸 막고 있었다)."""
    from generators.sits import collect_integration_flows

    fd = _cross_module_details(6)
    stats: Dict[str, Any] = {}
    flows = collect_integration_flows(fd, max_flows=None, stats_out=stats, sds_map={})
    assert len(flows) == 6
    assert stats["total_flows_found"] == 6
    assert stats["flows_dropped"] == 0


def test_sds_swcom_zero_is_surfaced_not_hidden() -> None:
    """SwDS 보강이 0건이면 **그 0을 올린다**.

    실측: 실 SwDS 763항목을 줘도 키 매칭 38건 / SwCom **0건** 이다(맵 필드가 `kind`
    뿐이라 코드가 읽는 `swcom`/`component` 가 없다). 숨기면 추적성 열이 합성 ID 만
    남는데도 화면은 정상으로 보인다.
    """
    fd = _cross_module_details(3)
    res = tm._measure_sits(fd, {}, "SwDS 경로가 지정되지 않았습니다")
    assert res["sds_swcom_hits"] in (0, None)
    assert res["sds_reason"]


def test_sample_flow_carries_call_chain() -> None:
    """콜체인이 문서 D열에 그대로 박히므로 화면도 그걸 보여야 한다."""
    fd = _cross_module_details(2)
    res = tm._measure_sits(fd, {}, "")
    assert res["sample_flow"] is not None
    assert res["sample_flow"]["entry_fn"]
    assert "->" in res["sample_flow"]["call_chain"] or res["sample_flow"]["call_chain"]


# ── SUTS 변수 타입 ──────────────────────────────────────────────────────────

def test_type_grounding_uses_evidence_not_return_value() -> None:
    """폴백과 진짜 u8 은 **반환값이 같다** — 근거 유무로 갈라야 한다."""
    from generators.suts import infer_variable_type

    fd = {
        "a": _fn("a", "src/A.c", [], inputs=["[IN] u8_Speed"]),          # 이름 패턴 O
        "b": _fn("b", "src/B.c", [], inputs=["[IN] EEPROM_TAddress Addr"]),  # 근거 X
    }
    res = tm._measure_suts_types(fd)
    assert res["variables"] == 2
    assert res["grounded"] == 1
    assert res["fallback"] == 1
    # 반환값만 보면 구분이 안 된다는 사실 자체를 고정한다.
    assert infer_variable_type("[IN] EEPROM_TAddress Addr") == "uint8_t"


def test_fallback_samples_are_reported() -> None:
    """조치하려면 **어떤 변수인지** 알아야 한다 — 건수만으로는 못 고친다."""
    fd = {
        "a": _fn("a", "src/A.c", [],
                 inputs=["[INOUT] S_SHA256_WorkState_t* pt (range: 0x0 ~ 0xFFFFFFFF)"]),
    }
    res = tm._measure_suts_types(fd)
    assert res["fallback"] == 1
    assert res["fallback_samples"], "폴백 변수 목록이 비어 있으면 조치가 불가능하다"
    assert "SHA256" in res["fallback_samples"][0]


def test_zero_variables_is_not_full_grounding() -> None:
    """변수가 0개면 100% 가 아니다 — 분모 0 을 성공으로 접지 않는다."""
    res = tm._measure_suts_types({"a": _fn("a", "src/A.c", [])})
    assert res["variables"] == 0
    assert res["grounded"] == 0


# ── measure() 실패 경로 ─────────────────────────────────────────────────────

def test_measure_reports_reason_when_no_source() -> None:
    res = tm.measure("")
    assert res["ok"] is False
    assert res["reason"]


def test_cache_miss_is_explicit(tmp_path) -> None:
    """캐시가 없으면 `has_cached` 는 False 이고 `cached` 는 None 이다.

    preflight 가 이걸로 `unmeasured` 를 결정한다 — 값이 0 인 것과 다르다.
    """
    tm.clear_cache()
    assert tm.has_cached(str(tmp_path)) is False
    assert tm.cached(str(tmp_path)) is None


@pytest.mark.parametrize("doc_type", ["sutr", "sitr", "swreport"])
def test_test_report_form_fields_are_shared(doc_type: str) -> None:
    """시험 결과 3종의 폼 필수값은 서버 단일 출처를 쓴다(프론트 복제 제거)."""
    from backend.services.docgen_requirements import (
        TEST_REPORT_DOC_TYPES,
        TEST_REPORT_FORM_FIELDS,
    )
    assert doc_type in TEST_REPORT_DOC_TYPES
    assert "release_sw_version" in TEST_REPORT_FORM_FIELDS
