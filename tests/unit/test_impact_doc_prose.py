"""AI 서술문 보강 — 값 환각 게이트.

역할 분담이 이 기능의 전부다: **값은 결정론이 소유하고 AI는 산문만 쓴다.**
프롬프트로 "값을 쓰지 마라"라고 지시하는 것만으론 부족해서, 응답에 등장한 숫자·식별자를
결정론 페이로드와 대조해 **필드 단위로** 폐기한다(한 필드가 틀렸다고 나머지를 버리지 않는다).
"""
from __future__ import annotations

import json

import pytest

DETERMINISTIC = {
    "suts": [{"strategy": "BV_MIN", "inputs": {"g_sys_error_his": "0x0"},
              "expected": {"g_sys_error_his": "0x0"}}],
    "suts_meta": {"component": "SwCom_07", "test_method": "FNCT"},
    "uds": {"prototype": "void s_updateerrorcode(U16 u16t_Data)",
            "globals": ["g_sys_error_his"], "calls": ["s_helper"]},
}


def _agent(payload: dict):
    """LLM 스텁 — 주어진 dict를 JSON으로 돌려준다."""
    def _call(_cfg, _messages, **_kw):
        return json.dumps(payload, ensure_ascii=False)
    return _call


def _run(payload: dict, **kw):
    from workflow.impact_doc_prose import generate_doc_prose

    return generate_doc_prose(
        function="s_updateerrorcode",
        deterministic=DETERMINISTIC,
        signature="void s_updateerrorcode(U16 u16t_Data)",
        cfg={"model": "stub"},
        agent_call=_agent(payload),
        **kw,
    )


def test_valid_prose_passes_through():
    out = _run({
        "uds_description": "오류 이력 전역 g_sys_error_his 를 갱신하고 s_helper 로 위임한다.",
        "sds_behavior": "진단 컴포넌트의 오류 이력 인터페이스를 담당한다.",
        "suts_description": "입력 경계에서 이력 갱신 동작을 확인한다.",
        "sts_purpose": "", "sits_description": "",
    })
    assert out["ok"] is True
    assert "g_sys_error_his" in out["fields"]["uds_description"]
    assert out["dropped_fields"] == []
    assert out["fields"].keys() <= {"uds_description", "sds_behavior", "suts_description"}
    assert "심사 판정이 아닙니다" in out["note"] or "설계자 검토" in out["note"]


def test_unknown_number_drops_only_that_field():
    """결정론 페이로드에 없는 숫자가 있으면 **그 필드만** 폐기한다."""
    out = _run({
        "uds_description": "임계값 0xDEAD 를 초과하면 이력을 갱신한다.",   # 없는 값
        "sds_behavior": "진단 컴포넌트의 오류 이력 인터페이스를 담당한다.",  # 정상
        "suts_description": "", "sts_purpose": "", "sits_description": "",
    })
    assert out["ok"] is True
    assert "uds_description" not in out["fields"]
    assert "sds_behavior" in out["fields"], "한 필드 오류로 나머지를 버리지 않는다"
    assert out["dropped_fields"] == [
        {"field": "uds_description", "reason": "unknown_number", "token": "0xDEAD"},
    ]


def test_known_number_in_other_base_is_accepted():
    """진법이 달라도 결정론에 있는 값이면 통과(0x0 ≡ 0)."""
    out = _run({
        "uds_description": "초기 상태 0 에서 이력을 갱신한다.",
        "sds_behavior": "", "suts_description": "", "sts_purpose": "", "sits_description": "",
    })
    assert out["ok"] is True
    assert "uds_description" in out["fields"]


def test_unknown_identifier_drops_field():
    """결정론에 없는 식별자(존재하지 않는 함수/전역)를 쓰면 그 필드를 폐기한다."""
    out = _run({
        "uds_description": "g_phantom_flag 를 확인해 분기한다.",   # 없는 전역
        "sds_behavior": "", "suts_description": "", "sts_purpose": "", "sits_description": "",
    })
    assert out["ok"] is False          # 통과 필드가 하나도 없음
    assert out["reason"] == "all_fields_filtered"
    assert out["dropped_fields"][0]["reason"] == "unknown_identifier"
    assert out["dropped_fields"][0]["token"] == "g_phantom_flag"


def test_llm_unavailable_returns_not_ok_without_raising():
    from workflow.impact_doc_prose import generate_doc_prose

    out = generate_doc_prose(function="s_foo", deterministic=DETERMINISTIC, cfg={})
    assert out["ok"] is False
    assert out["reason"] == "llm_unavailable"
    assert out["fields"] == {}


def test_no_deterministic_payload_skips_llm_call():
    """결정론 근거가 없으면 호출 자체를 생략한다(환각 유인 제거)."""
    from workflow.impact_doc_prose import generate_doc_prose

    called = {"n": 0}

    def _call(_cfg, _messages, **_kw):
        called["n"] += 1
        return "{}"

    out = generate_doc_prose(function="s_foo", deterministic={}, cfg={"model": "s"}, agent_call=_call)
    assert out["ok"] is False
    assert out["reason"] == "no_deterministic_payload"
    assert called["n"] == 0


def test_llm_error_is_contained():
    from workflow.impact_doc_prose import generate_doc_prose

    def _boom(_cfg, _messages, **_kw):
        raise RuntimeError("upstream 500")

    out = generate_doc_prose(function="s_foo", deterministic=DETERMINISTIC,
                             cfg={"model": "s"}, agent_call=_boom)
    assert out["ok"] is False
    assert out["reason"] == "llm_error"


@pytest.mark.parametrize("bad", ["", "not json", "{}", '{"uds_description": ""}'])
def test_invalid_llm_output(bad):
    from workflow.impact_doc_prose import generate_doc_prose

    out = generate_doc_prose(
        function="s_foo", deterministic=DETERMINISTIC, cfg={"model": "s"},
        agent_call=lambda _c, _m, **_k: bad,
    )
    assert out["ok"] is False
    assert out["reason"] == "llm_empty_or_invalid"


def test_small_ordinals_and_iso_number_are_allowed():
    """'2가지', 'ISO 26262' 같은 문장 수식 숫자는 값 대조에서 면제한다(과탐 방지)."""
    out = _run({
        "uds_description": "ISO 26262 관점에서 2 가지 상태를 갱신한다.",
        "sds_behavior": "", "suts_description": "", "sts_purpose": "", "sits_description": "",
    })
    assert out["ok"] is True
    assert "uds_description" in out["fields"]


def test_endpoint_returns_not_ok_when_llm_missing(monkeypatch):
    """라우터는 예외를 던지지 않고 ok=False로 정직 반환 — 프론트는 표를 그대로 유지한다."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.routers import impact as impact_router

    app = FastAPI()
    app.include_router(impact_router.router)
    client = TestClient(app)

    import workflow.impact_ai_guide as guide
    monkeypatch.setattr(guide, "_load_impact_oai_config", lambda: None)

    r = client.post("/api/impact/doc-prose",
                    json={"function": "s_foo", "deterministic": DETERMINISTIC})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["fields"] == {}


@pytest.mark.parametrize("text", [
    "U16 폭 입력의 경계 취급을 확인한다.",
    "int32_t 범위에서 포화 처리를 본다.",
    "float64 정밀도 손실을 확인한다.",
    "S8 입력의 음수 경계를 다룬다.",
])
def test_c_type_width_is_not_treated_as_a_value(text):
    """C 타입 토큰의 숫자는 **값이 아니라 비트폭**이다 — 값 대조에서 폐기하면 안 된다.

    ⚠ 회귀 가드(실측): 결정론 페이로드에 'U16' 문자열이 없는 조합(타입 미상 케이스에서 흔함)에서
    "U16 폭 입력의 경계를 확인한다"가 `unknown_number:16`으로 폐기됐다. 숫자 검사와 식별자 검사
    **양쪽**을 면제해야 한다 — 한쪽만 풀면 다른 쪽에서 걸린다."""
    from workflow.impact_doc_prose import generate_doc_prose

    out = generate_doc_prose(
        function="s_setmode",
        deterministic={"suts": [{"variable": "SomeEnum_Mode", "verdict": "검증필요"}]},
        signature="void s_setmode(SomeEnum_Mode m)",
        cfg={"model": "stub"},
        agent_call=_agent({"uds_description": text}),
    )
    assert out["ok"] is True, f"정상 서술문이 폐기됨: {out['dropped_fields']}"


def test_real_hallucinated_value_is_still_dropped_after_type_exemption():
    """타입 토큰 면제가 **진짜 환각까지** 풀어주지 않는지 — 면제 범위 회귀 가드."""
    from workflow.impact_doc_prose import generate_doc_prose

    out = generate_doc_prose(
        function="s_setmode",
        deterministic={"suts": [{"variable": "SomeEnum_Mode"}]},
        cfg={"model": "stub"},
        agent_call=_agent({"uds_description": "U16 임계값 0xDEAD 를 초과하면 갱신한다."}),
    )
    assert out["ok"] is False
    assert out["dropped_fields"][0]["token"] == "0xDEAD"
