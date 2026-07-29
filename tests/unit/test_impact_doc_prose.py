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


def test_type_token_exemption_covers_only_real_types():
    r"""I8: 타입 토큰 면제 어휘가 `\d{1,2}`로 열려 있으면 **없는 타입이 면제된다**.

    `U48`·`S99`·`u7`·`uint99`는 숫자 검사(비트폭이라며 제거)와 식별자 검사(타입 어휘라며
    면제)를 **둘 다** 통과해, 안전 문서 초안에 "U48 폭 입력" 같은 환각 타입이 그대로 실렸다.
    """
    from workflow.c_type_bounds import C_TYPE_ALIAS, FLOAT_TYPES
    from workflow.impact_doc_prose import _TYPE_TOKEN_RE

    for real in ("U16", "u8", "int32_t", "uint16_t", "float64", "unsigned char", "boolean"):
        assert _TYPE_TOKEN_RE.search(real), f"실제 타입 {real}이 면제되지 않으면 정상 문장이 폐기된다"
    for fake in ("U48", "S99", "u7", "uint99", "int99_t", "float128"):
        assert not _TYPE_TOKEN_RE.search(fake), f"{fake}는 이 프로젝트에 없는 타입이다"
    # 어휘는 c_type_bounds 단일 출처에서 온다 — 타입이 늘면 거기만 고친다
    for word in list(C_TYPE_ALIAS)[:5] + sorted(FLOAT_TYPES)[:3]:
        assert _TYPE_TOKEN_RE.search(word), word


def test_fake_type_width_is_dropped_but_real_type_survives():
    """게이트 통과 여부로 확인 — 정규식 단위가 아니라 실제 판정."""
    from workflow.impact_doc_prose import filter_prose

    fake = filter_prose({"uds_description": "입력은 U48 폭이므로 상한을 확인한다"}, {"0", "65535"}, {"s_foo"})
    assert fake["fields"] == {}
    assert fake["dropped_fields"][0]["reason"] == "unknown_number"
    assert fake["dropped_fields"][0]["token"] == "48"

    real = filter_prose({"uds_description": "입력은 U16 폭이므로 상한을 확인한다"}, {"0", "65535"}, {"s_foo"})
    assert real["fields"]["uds_description"].startswith("입력은 U16")
    assert real["dropped_fields"] == []


def test_type_vocabulary_includes_widths_without_boundary_values():
    """반대 방향 함정: 어휘를 경계값 테이블로만 좁히면 **U64/S64가 빠진다**.

    경계값 정의가 없어 `C_TYPE_BOUNDS` 에 없을 뿐, `generators/sits.py:186` 의 타입 정규식이
    프로젝트 타입으로 인정하는 토큰이다 → "U64 폭" 같은 정상 문장이 `unknown_number: 64` 로
    폐기된다. ⚠ `C_TYPE_ALIAS` 에 넣는 것으로 고치면 `c_type_boundaries()` 가 KeyError 로 죽는다.
    """
    from workflow.c_type_bounds import C_TYPE_BOUNDS, c_type_boundaries
    from workflow.impact_doc_prose import _TYPE_TOKEN_RE, filter_prose

    for wide in ("U64", "s64", "uint64_t", "int64_t"):
        assert _TYPE_TOKEN_RE.fullmatch(wide.lower()), f"{wide}는 프로젝트가 인정하는 타입 토큰"
    assert "u64" not in C_TYPE_BOUNDS, "경계값은 정의돼 있지 않다(있는 척하면 환각)"
    assert c_type_boundaries("U64") == [], "경계값 없는 타입은 빈 리스트 — 크래시도 창작도 없다"

    kept = filter_prose({"uds_description": "U64 폭 누적값의 상한 처리를 확인한다"}, {"0"}, {"s_foo"})
    assert kept["fields"], "정상 타입 문장이 폐기되면 안 된다"


def test_trim_for_prompt_keeps_every_document_node():
    """⚠ 통짜 JSON `[:12000]` 절단은 **뒤쪽 문서 노드를 통째로 날린다**.

    실측: SUTS 표만 21KB라 uds/sds/sts/sits 가 전부 잘려나갔고, 그 상태로 sts_purpose·
    sits_description 을 요구하니 근거 없는 산문이 나왔다.
    """
    import json

    from workflow.impact_doc_prose import trim_for_prompt

    big_row = {"cells": {f"in:g_v[{i}]": {"current": "0x8000", "proposed": "0xFFFF"} for i in range(12)}}
    det = {
        "suts": [dict(big_row) for _ in range(40)],          # 지배항 — 예산을 다 먹던 노드
        "uds": {"prototype": "U16 s_foo(U16 x)", "calls": ["Hal_Read"]},
        "sds": {"component": "SwCom_11"},
        "sts": [[{"action": "call s_foo", "expected": "ok"}]],
        "sits": {"call_chain": "a -> b -> c", "sub_cases": [{"case_label": "max"}]},
    }
    raw = json.dumps(det, ensure_ascii=False)
    assert len(raw) > 12000, "케이스 전제: 예산 초과 페이로드"
    assert raw.find('"sits"') > 12000, "케이스 전제: 구 방식이면 sits 가 잘려나간다"

    sent = trim_for_prompt(det, budget=12000)
    assert set(sent) == set(det), "문서 노드가 하나라도 빠지면 그 필드는 근거 없이 작성된다"
    body = json.dumps(sent, ensure_ascii=False)
    assert len(body) <= 12000
    assert json.loads(body) == sent, "문자열 절단이 아니라 구조 축소 — 항상 파싱 가능해야"
    assert len(sent["suts"]) < len(det["suts"]), "지배항이 줄어야 나머지가 들어간다"
    assert sent["sds"] == det["sds"], "작은 노드는 손대지 않는다"


def test_trim_for_prompt_is_noop_under_budget():
    """예산 안이면 그대로 — 없는 축소를 하지 않는다."""
    from workflow.impact_doc_prose import trim_for_prompt

    det = {"uds": {"prototype": "U16 s_foo(void)"}, "sds": {"component": "C1"}}
    assert trim_for_prompt(det) == det
    assert trim_for_prompt({}) == {}
    assert trim_for_prompt(None) == {}


def test_allowed_set_comes_from_what_the_model_actually_saw(monkeypatch):
    """허용 집합은 **전송본** 기준이어야 한다.

    원본(상한 256KB)에서 만들면 프롬프트에서 잘려 모델이 본 적 없는 값까지 "결정론에 있는
    값"으로 통과시킨다 = 게이트가 스스로 느슨해진다(환각 차단이 목적인데 반대로 간다).
    """
    from workflow import impact_doc_prose as mod

    seen: dict = {}

    def _fake_agent(cfg, messages, **kw):  # noqa: ARG001
        seen["payload"] = messages[-1]["content"]
        # 잘려나간 영역에만 있던 값을 산문에 넣는다
        return '{"uds_description": "누적 상한을 424242 로 본다"}'

    monkeypatch.setattr(mod, "resolve_effective_model", lambda cfg: "m")
    # 값을 **큰 노드의 뒤쪽 행**에 둔다 — 노드별 예산이라 작은 노드는 항상 살아남으므로,
    # 잘려나가는 건 지배항 안에서 상한을 넘긴 부분이다(화면엔 보이지만 모델은 못 본 값).
    rows = [{"cells": {f"in:g_v[{i}]": {"current": "0x8000"} for i in range(12)}} for _ in range(40)]
    rows[-1] = {"cells": {"in:g_tail": {"current": "424242"}}}
    det = {"suts": rows, "uds": {"prototype": "U16 s_foo(U16 x)"}}
    res = mod.generate_doc_prose(function="s_foo", deterministic=det, cfg={"x": 1}, agent_call=_fake_agent)

    assert "424242" not in seen["payload"], "케이스 전제: 그 값은 프롬프트에 없다"
    assert res["fields"] == {}, "모델이 본 적 없는 값이 통과하면 게이트가 무의미하다"
    assert res["dropped_fields"][0]["token"] == "424242"


def test_trimming_is_surfaced_not_silenced():
    """근거 축소를 침묵시키지 않는다 — 화면이 "일부 근거만 사용"을 말할 수 있어야 한다."""
    from workflow.impact_doc_prose import generate_doc_prose

    rows = [{"cells": {f"in:g_v[{i}]": {"current": "0x0"} for i in range(12)}} for _ in range(40)]
    out = generate_doc_prose(
        function="s_foo",
        deterministic={"suts": rows, "uds": {"prototype": "void s_foo(void)"}},
        cfg={"model": "stub"},
        agent_call=_agent({"uds_description": "이력 전역을 초기 상태로 되돌린다."}),
    )
    assert out["ok"] is True
    assert out["trimmed_nodes"] == ["suts"], "줄어든 노드를 밝혀야 한다"


def test_no_trim_note_when_everything_fits():
    """없는 축소를 경고하지 않는다(cry wolf 방지)."""
    out = _run({"uds_description": "오류 이력 전역 g_sys_error_his 를 갱신한다.",
                "sds_behavior": "", "suts_description": "", "sts_purpose": "", "sits_description": ""})
    assert out["ok"] is True
    assert out["trimmed_nodes"] == []


def test_empty_after_trim_skips_llm_call():
    """노드가 전부 비면 허용 집합도 비어 어떤 문장도 통과 못 한다 — 호출 자체를 생략."""
    from workflow.impact_doc_prose import generate_doc_prose

    called = {"n": 0}

    def _call(_cfg, _messages, **_kw):
        called["n"] += 1
        return "{}"

    out = generate_doc_prose(function="s_foo", deterministic={"suts": [], "uds": {}},
                             cfg={"model": "s"}, agent_call=_call)
    assert out["reason"] == "no_deterministic_payload"
    assert called["n"] == 0, "근거 0으로 LLM을 부르면 환각만 유발한다"


def test_shrink_does_not_blow_up_on_many_small_elements():
    """미세 증가 루프가 무제한이면 접두 재직렬화로 O(n²) — 요청 경로에서 CPU를 먹는다."""
    import time

    from workflow.impact_doc_prose import trim_for_prompt

    det = {"suts": [{"v": i} for i in range(20000)]}
    t0 = time.perf_counter()
    sent = trim_for_prompt(det, budget=12000)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"트리밍에 {elapsed:.1f}s — 원소 수에 제곱으로 붙는다"
    assert 0 < len(sent["suts"]) < 20000


def test_trim_respects_budget_on_adversarial_shapes():
    """예산은 **보장**이어야 한다 — 노드 수·키 길이를 클라이언트가 정하므로 상한이 열려 있으면
    프롬프트 비용이 통제되지 않는다.

    실측으로 세 번 샜다: ①노드별 몫의 하한(400)×노드수 ②dict 래퍼(`"key": `, `, `)의
    구분자 4자 미계상 ③스칼라의 따옴표 2자. 셋 다 "조금씩" 새는 종류라 정상 규모에선 안 보인다.
    """
    import json

    from workflow.impact_doc_prose import trim_for_prompt

    shapes = {
        "many_keys": {f"node_{i}": {"text": "x" * 2000} for i in range(60)},
        "many_lists": {f"n{i}": [f"v{j}" for j in range(500)] for i in range(30)},
        "long_keys": {"k" * 80 + str(i): {"t": "y" * 300} for i in range(200)},
        "one_huge_string": {"suts": "z" * 100_000},
        "deep_nesting": {"uds": {"a": {"b": {"c": {"d": ["x" * 500] * 50}}}}},
    }
    for name, det in shapes.items():
        sent = trim_for_prompt(det, budget=12000)
        body = json.dumps(sent, ensure_ascii=False)
        assert len(body) <= 12000, f"{name}: {len(body)}자 — 예산 초과"
        assert json.loads(body) == sent, f"{name}: 파싱 불가 JSON"
        assert sent, f"{name}: 근거가 통째로 사라졌다(잘라서 일부라도 싣는 것이 목적)"


def test_document_nodes_outrank_incidental_nodes():
    """예산이 모자랄 때 밀려나야 하는 건 표 렌더용 부수 노드지 문서 노드가 아니다."""
    from workflow.impact_doc_prose import trim_for_prompt

    det = {
        "columns": [{"name": f"g_col_{i}", "side": "input"} for i in range(400)],   # 지배항
        "suts_meta": {"component": "SwCom_11"},
        "uds": {"prototype": "U16 s_foo(U16 x)"},
        "sits": {"call_chain": "a -> b -> c"},
        "sds": {"component": "SwCom_11"},
    }
    sent = trim_for_prompt(det, budget=1200)
    for node in ("uds", "sits", "sds"):
        assert node in sent, f"{node} 가 부수 노드에 밀려 빠졌다"


def test_dropped_node_is_reported_not_only_shrunken_one():
    """통째로 빠진 노드는 축소보다 **큰 손실**인데, `sent` 만 훑으면 그게 침묵한다."""
    from workflow.impact_doc_prose import generate_doc_prose

    out = generate_doc_prose(
        function="s_foo",
        deterministic={
            "uds": {"prototype": "void s_foo(void)"},
            "columns": [{"name": f"g_col_{i}"} for i in range(4000)],   # 예산 밖으로 밀릴 부수 노드
        },
        cfg={"model": "stub"},
        agent_call=_agent({"uds_description": "이력 전역을 초기 상태로 되돌린다."}),
    )
    assert out["ok"] is True
    assert "columns" in out["trimmed_nodes"], "빠진 노드를 밝히지 않으면 사용자가 근거 범위를 오판한다"


def test_empty_nodes_are_not_reported_as_trimmed():
    """프론트는 없는 문서에도 자리를 채워 보낸다(`|| {}`) — 그걸 손실로 세면 매번 오경보."""
    from workflow.impact_doc_prose import generate_doc_prose

    out = generate_doc_prose(
        function="s_foo",
        deterministic={"uds": {"prototype": "void s_foo(void)"}, "sits": {}, "sts": []},
        cfg={"model": "stub"},
        agent_call=_agent({"uds_description": "이력 전역을 초기 상태로 되돌린다."}),
    )
    assert out["ok"] is True
    assert out["trimmed_nodes"] == []
