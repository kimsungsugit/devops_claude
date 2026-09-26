"""함수 단위 시험 케이스 초안(N4) — 결정론 골격·환각 필터·정직 폴백.

핵심 계약: LLM이 없거나 실패해도 결정론 골격(권고 기법·최소 TC 추정·경계값 후보)은 항상
나오고, 소스 본문에 없는 식별자를 인용한 케이스는 그 케이스만 폐기된다.
"""
from __future__ import annotations

import json

from workflow.test_case_draft import (
    TEST_CASE_DRAFT_NOTE,
    build_deterministic_draft,
    filter_cases,
    generate_test_case_draft,
)

SOURCE = """
void Ap_MotorCtrl_SetSpeed(uint8_t speed, boolean enable)
{
    if (enable == TRUE) {
        if (speed > MAX_SPEED) {
            g_motor_state = MOTOR_ERROR;
            return;
        }
        g_motor_speed = speed;
    } else {
        g_motor_speed = 0;
    }
    Ap_MotorCtrl_Apply();
}
"""

CTX = {
    "function": "Ap_MotorCtrl_SetSpeed",
    "unit": "Ap_MotorCtrl_PDS",
    "signature": "void Ap_MotorCtrl_SetSpeed(uint8_t speed, boolean enable)",
    "params": [{"name": "speed", "type": "uint8_t"}, {"name": "enable", "type": "boolean"}],
    "globals": ["g_motor_speed", "g_motor_state"],
    "calls": ["Ap_MotorCtrl_Apply"],
    "statement": 0.6, "branch": 0.25, "ccn": 4,
    "asil": "C", "asil_source": "uds_link",
    "gap_kind": "below_target",
    "techniques": ["boundary_values", "decision_condition", "robustness"],
}


def test_deterministic_core_always_present():
    det = build_deterministic_draft(CTX)
    assert [t["id"] for t in det["techniques"]] == ["boundary_values", "decision_condition", "robustness"]
    assert all(t["iso_ref"].startswith("ISO 26262-6") for t in det["techniques"])
    assert det["suggested_min_cases"] == 4 and det["suggested_min_cases_estimate"] is True
    # MC/DC는 값이 아니라 상태로 — '0%' 미달 위장 금지
    assert det["coverage"]["mcdc"] is None and det["coverage"]["mcdc_state"] == "unmeasured"
    assert det["asil"] == "C" and det["asil_source"] == "uds_link"


def test_boundary_candidates_from_param_types():
    det = build_deterministic_draft(CTX)
    by_param = {b["param"]: b for b in det["boundary_candidates"]}
    assert by_param["speed"]["candidates"] == ["0", "1", "254", "255"]   # uint8_t 경계
    assert by_param["enable"]["candidates"] == ["FALSE", "TRUE"]
    # 타입 미상 파라미터는 후보를 만들지 않는다(추측 금지)
    det2 = build_deterministic_draft({**CTX, "params": [{"name": "opaque"}]})
    assert det2["boundary_candidates"] == []


def test_min_cases_none_without_ccn():
    det = build_deterministic_draft({**CTX, "ccn": None})
    # ccn을 모르면 '1건이면 충분'으로 위장하지 않고 None
    assert det["suggested_min_cases"] is None


def test_filter_drops_hallucinated_and_empty_expected():
    allowed = {"speed", "enable", "g_motor_speed", "max_speed", "true", "false", "motor_error"}
    out = filter_cases([
        {"id": "TC1", "purpose": "p", "inputs": "speed=255, enable=TRUE",
         "expected": "g_motor_speed == 255", "covers": "speed > MAX_SPEED"},
        # 입력에 없는 식별자만 잔뜩 — 폐기
        {"id": "TC2", "purpose": "p", "inputs": "torque_limit=99, brake_pedal=ACTIVE",
         "expected": "vehicle_state == LIMP_HOME", "covers": "unknown_branch_guard"},
        # 기대 결과 없음 — 시험이 아니다
        {"id": "TC3", "purpose": "p", "inputs": "speed=0", "expected": "", "covers": ""},
    ], allowed)
    assert [c["id"] for c in out["cases"]] == ["TC1"]
    assert out["dropped"] == 2


def test_generate_without_llm_returns_deterministic_only():
    gen = generate_test_case_draft(context=CTX, source_excerpt=SOURCE, cfg={})
    assert gen["ai_enriched"] is False and gen["enrich_reason"] == "llm_unavailable"
    assert gen["cases"] == [] and gen["deterministic"]["suggested_min_cases"] == 4


def test_generate_skips_llm_without_source():
    """본문이 없으면 인용 검증이 불가능 — 호출 자체를 생략(근거 없는 케이스 방지)."""
    calls = []

    def _agent(*a, **k):
        calls.append(a)
        return "{}"

    gen = generate_test_case_draft(context=CTX, source_excerpt="", cfg={"model": "m"}, agent_call=_agent)
    assert gen["enrich_reason"] == "no_source_excerpt" and calls == []


def test_generate_with_llm_filters_and_keeps_valid_cases():
    payload = {
        "cases": [
            {"id": "TC1", "purpose": "상한 초과 시 에러 상태", "technique": "boundary_values",
             "preconditions": "g_motor_state = 0", "inputs": "speed=255, enable=TRUE",
             "expected": "g_motor_state == MOTOR_ERROR, Ap_MotorCtrl_Apply 미호출",
             "covers": "if (speed > MAX_SPEED)"},
            {"id": "TC2", "purpose": "환각", "technique": "boundary_values",
             "preconditions": "cluster_gateway_init()", "inputs": "can_frame_id=0x7DF",
             "expected": "diag_session_state == EXTENDED", "covers": "unrelated_guard"},
        ],
        "notes": ["MAX_SPEED 정의 확인 필요"],
    }

    def _agent(cfg, messages, **k):
        assert "함수 소스 본문" in messages[1]["content"]
        return json.dumps(payload, ensure_ascii=False)

    gen = generate_test_case_draft(context=CTX, source_excerpt=SOURCE,
                                   cfg={"model": "gemini"}, agent_call=_agent)
    assert gen["ai_enriched"] is True
    assert [c["id"] for c in gen["cases"]] == ["TC1"]
    assert gen["dropped_cases"] == 1
    assert gen["notes"] == ["MAX_SPEED 정의 확인 필요"]
    assert gen["deterministic"]["suggested_min_cases"] == 4  # 골격은 그대로 동반


def test_generate_all_filtered_is_honest():
    def _agent(*a, **k):
        return json.dumps({"cases": [{"id": "TC1", "inputs": "foo_bar_baz=1",
                                      "expected": "qux_quux_corge == 2", "covers": "grault_garply"}]})

    gen = generate_test_case_draft(context=CTX, source_excerpt=SOURCE,
                                   cfg={"model": "m"}, agent_call=_agent)
    assert gen["cases"] == [] and gen["enrich_reason"] == "all_cases_filtered"
    assert gen["dropped_cases"] == 1


def test_llm_error_falls_back_without_raising():
    def _agent(*a, **k):
        raise RuntimeError("network down")

    gen = generate_test_case_draft(context=CTX, source_excerpt=SOURCE,
                                   cfg={"model": "m"}, agent_call=_agent)
    assert gen["ai_enriched"] is False and gen["enrich_reason"] == "llm_error"
    assert gen["deterministic"]["techniques"]


def test_note_is_server_fixed():
    assert "심사 판정이 아닙니다" in TEST_CASE_DRAFT_NOTE
    assert "요구사항 기반 시험" in TEST_CASE_DRAFT_NOTE
