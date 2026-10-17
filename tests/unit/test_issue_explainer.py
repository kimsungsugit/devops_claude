"""(R48-b) `backend/services/issue_explainer.py` — Gemini 설명의 안전장치.

1. 프롬프트 밖 숫자 → 응답 폐기 + 룰 폴백(`generated_by: rule`, 사유 명시)
2. 입력에 없는 문제 코드 → 폐기
3. 형식 위반(JSON 아님/키 없음) → 폐기, 코드 펜스는 벗겨서 받는다
4. LLM 이 일부만 설명하면 나머지는 룰 문장으로 채운다 — 목록이 줄지 않는다
5. 캐시: 같은 사실이면 LLM 을 다시 부르지 않는다
"""
from __future__ import annotations

import json

import pytest

from backend.services import issue_explainer as ex


def _payload(n=2):
    issues = [
        {"code": "gate_fail:traceability_rate", "severity": "error", "kind": "actual", "source": "gate_report",
         "message": "게이트 미달: traceability_rate — 30.8% < 20.0%", "facts": {"gate": "traceability_rate"}},
        {"code": "tbd_residual:ASIL TBD", "severity": "warning", "kind": "potential", "source": "gate_report",
         "message": "ASIL TBD 29 / 169", "facts": {"count": 29, "total": 169}},
    ][:n]
    return {"run_id": 2075, "doc_type": "uds",
            "counts": {"total": len(issues), "actual": 1 if n else 0, "potential": 1 if n > 1 else 0,
                       "by_severity": {"error": 1 if n else 0, "warning": 1 if n > 1 else 0, "risk": 0}},
            "issues": issues}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    ex.clear_cache()
    # 설정 로더를 고정 — 실 .env/OAI_CONFIG 에 기대지 않는다
    import workflow.ai as ai
    monkeypatch.setattr(ai, "load_oai_config", lambda _p: {"model": "gemini-test", "api_key": "x"})
    monkeypatch.delenv("LLM_MODEL_OVERRIDE", raising=False)
    yield
    ex.clear_cache()


def _ok_llm(text):
    return lambda cfg, messages: text


class TestRuleFallback:
    def test_use_llm_false(self):
        out = ex.explain_issues(_payload(), use_llm=False, llm_call_fn=lambda *_: (_ for _ in ()).throw(AssertionError("호출되면 안 된다")))
        assert out["generated_by"] == "rule" and out["model"] is None
        assert out["llm_reason"] == "LLM 사용 안 함"
        assert [i["code"] for i in out["items"]] == ["gate_fail:traceability_rate", "tbd_residual:ASIL TBD"]
        assert "30.8%" in out["items"][0]["explanation"]
        assert out["items"][0]["action"] == ex.rule_action("gate_fail:x")
        assert "2건" in out["summary"] and "actual) 1건" in out["summary"]

    def test_empty_issue_list_says_nothing_measured_caveat(self):
        out = ex.explain_issues(_payload(0), use_llm=True, llm_call_fn=_ok_llm("{}"))
        assert out["generated_by"] == "rule" and "잰 것이 없음" in out["summary"]
        assert out["llm_reason"] == "설명할 문제가 없다"

    def test_llm_exception_falls_back_with_reason(self):
        def boom(cfg, messages):
            raise TimeoutError("slow")
        out = ex.explain_issues(_payload(), llm_call_fn=boom)
        assert out["generated_by"] == "rule" and "TimeoutError" in out["llm_reason"]
        assert out["model"] == "gemini-test"

    def test_rule_action_prefix_and_default(self):
        assert ex.rule_action("report_timeout:accuracy") == ex.rule_action("report_timeout")
        assert ex.rule_action("never_heard_of") == ex._DEFAULT_ACTION


class TestDuplicateCodes:
    """(R49 리뷰 I6) 같은 code 가 여러 건이면 설명은 **순번 `i`** 로 되붙는다 — code 만으로는 마지막 설명이 전부를 덮는다."""

    def _dup_payload(self):
        issues = [
            {"code": "requirement_doc_skipped", "severity": "warning", "kind": "actual", "source": "generation",
             "message": "요구 문서 탈락: SwRS.docx: 접근 거부 — 워커 미응답", "facts": {"path": "SwRS.docx"}},
            {"code": "requirement_doc_skipped", "severity": "warning", "kind": "actual", "source": "generation",
             "message": "요구 문서 탈락: SwDS.docx: 파일 없음", "facts": {"path": "SwDS.docx"}},
        ]
        return {"run_id": 1, "doc_type": "uds", "counts": {"total": 2, "actual": 2, "potential": 0,
                "by_severity": {"error": 0, "warning": 2, "risk": 0}}, "issues": issues}

    def test_facts_and_rule_items_carry_index(self):
        facts = ex._facts_of(self._dup_payload())
        assert [i["i"] for i in facts["issues"]] == [0, 1]
        rule = ex.rule_explanation(self._dup_payload())
        assert [(i["i"], i["code"]) for i in rule["items"]] == [(0, "requirement_doc_skipped"), (1, "requirement_doc_skipped")]
        assert rule["items"][0]["action"] == ex._RULE_ACTION["requirement_doc_skipped"], "전용 조치문(리뷰 W2)"

    def test_llm_items_matched_by_index_not_code(self):
        resp = json.dumps({"summary": "문서 두 건을 읽지 못했다.", "items": [
            {"i": 0, "code": "requirement_doc_skipped", "explanation": "SwRS 는 워커가 응답하지 않았다", "action": "워커를 띄운다"},
            {"i": 1, "code": "requirement_doc_skipped", "explanation": "SwDS 는 경로에 없다", "action": "경로를 고친다"},
        ]})
        out = ex.explain_issues(self._dup_payload(), llm_call_fn=_ok_llm(resp))
        assert out["generated_by"] == "llm"
        assert [(i["i"], i["explanation"]) for i in out["items"]] == [(0, "SwRS 는 워커가 응답하지 않았다"), (1, "SwDS 는 경로에 없다")]

    def test_bad_index_falls_back_to_code_and_never_invents_items(self):
        # i 가 범위 밖/불리언/코드 불일치면 무시하고 code 로 맞춘다 — 항목 수는 입력과 같다
        resp = json.dumps({"summary": "요약.", "items": [
            {"i": 7, "code": "requirement_doc_skipped", "explanation": "설명 A", "action": "조치 A"},
            {"i": True, "code": "requirement_doc_skipped", "explanation": "설명 B", "action": "조치 B"},
        ]})
        out = ex.explain_issues(self._dup_payload(), llm_call_fn=_ok_llm(resp))
        assert out["generated_by"] == "llm" and len(out["items"]) == 2
        assert [i["i"] for i in out["items"]] == [0, 1]
        assert {i["explanation"] for i in out["items"]} <= {"설명 A", "설명 B"}

    def test_index_that_points_at_another_code_is_ignored(self):
        """순번과 code 가 어긋나면 순번을 버린다 — 다른 문제의 설명이 이 문제에 붙으면 검토자가 오독한다."""
        out = ex.explain_issues(_payload(), llm_call_fn=_ok_llm(json.dumps({"summary": "요약.", "items": [
            # i=1 은 tbd_residual 자리인데 code 는 gate_fail — code 가 맞는 0번에 붙어야 한다
            {"i": 1, "code": "gate_fail:traceability_rate", "explanation": "게이트 설명", "action": "게이트 조치"},
            # i=False(=0 으로 읽힘) 는 불리언 — 무시하고 code 로 1번에 붙는다
            {"i": False, "code": "tbd_residual:ASIL TBD", "explanation": "TBD 설명", "action": "TBD 조치"},
        ]})))
        assert out["generated_by"] == "llm"
        assert [(i["i"], i["code"], i["explanation"]) for i in out["items"]] == [
            (0, "gate_fail:traceability_rate", "게이트 설명"),
            (1, "tbd_residual:ASIL TBD", "TBD 설명"),
        ]


class TestLlmValidation:
    def test_good_response_is_used_and_missing_codes_are_filled_by_rule(self):
        resp = json.dumps({"summary": "traceability 가 30.8% 로 임계 20.0% 를 밑돈다. ASIL TBD 29건은 잠재 문제다.",
                           "items": [{"code": "gate_fail:traceability_rate", "explanation": "요구와 연결된 함수가 적다", "action": "Related ID 를 SRS 와 연결한다"}]})
        out = ex.explain_issues(_payload(), llm_call_fn=_ok_llm(resp))
        assert out["generated_by"] == "llm" and out["model"] == "gemini-test"
        assert out["summary"].startswith("traceability")
        codes = [i["code"] for i in out["items"]]
        assert codes == ["gate_fail:traceability_rate", "tbd_residual:ASIL TBD"], "LLM 이 빠뜨린 항목이 사라지면 안 된다"
        assert out["items"][0]["explanation"] == "요구와 연결된 함수가 적다"
        assert out["items"][1]["action"] == ex.rule_action("tbd_residual")   # 룰로 채움

    def test_invented_number_discards_whole_response(self):
        resp = json.dumps({"summary": "435개 중 82개가 문제다", "items": []})
        out = ex.explain_issues(_payload(), llm_call_fn=_ok_llm(resp))
        assert out["generated_by"] == "rule"
        assert "프롬프트 밖 숫자" in out["llm_reason"] and "435" in out["llm_reason"]

    def test_unknown_code_discards(self):
        resp = json.dumps({"summary": "ok", "items": [{"code": "made_up", "explanation": "x", "action": "y"}]})
        out = ex.explain_issues(_payload(), llm_call_fn=_ok_llm(resp))
        assert out["generated_by"] == "rule" and "입력에 없는 문제 코드" in out["llm_reason"]

    @pytest.mark.parametrize("bad", ["not json at all", "[1,2]", json.dumps({"summary": 1, "items": []}), json.dumps({"items": []}), ""])
    def test_malformed_discards(self, bad):
        out = ex.explain_issues(_payload(), llm_call_fn=_ok_llm(bad))
        assert out["generated_by"] == "rule" and out["llm_reason"].startswith("LLM")

    def test_code_fence_and_surrounding_prose_are_tolerated(self):
        body = json.dumps({"summary": "요약", "items": []})
        for wrapped in (f"```json\n{body}\n```", f"결과입니다:\n{body}\n감사합니다."):
            ex.clear_cache()
            out = ex.explain_issues(_payload(), llm_call_fn=_ok_llm(wrapped))
            assert out["generated_by"] == "llm", wrapped

    def test_model_override_env_is_reported(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL_OVERRIDE", "gemini-3.5-flash-lite")
        out = ex.explain_issues(_payload(), llm_call_fn=_ok_llm(json.dumps({"summary": "s", "items": []})))
        assert out["model"] == "gemini-3.5-flash-lite"


class TestCache:
    def test_same_facts_do_not_call_llm_twice(self):
        calls = []

        def fn(cfg, messages):
            calls.append(1)
            return json.dumps({"summary": "s", "items": []})
        a = ex.explain_issues(_payload(), llm_call_fn=fn)
        b = ex.explain_issues(_payload(), llm_call_fn=fn)
        assert len(calls) == 1 and a["facts_sha1"] == b["facts_sha1"] and b.get("cached") is True

    def test_prompt_item_cap_is_disclosed(self):
        p = _payload()
        p["issues"] = [dict(p["issues"][0], code="validation_issue", message=f"issue {i}") for i in range(ex.PROMPT_ITEMS_MAX + 3)]
        p["counts"]["total"] = len(p["issues"])
        out = ex.explain_issues(p, use_llm=False)
        assert out["items_shown"] == ex.PROMPT_ITEMS_MAX and out["items_total"] == ex.PROMPT_ITEMS_MAX + 3
        assert len(out["items"]) == ex.PROMPT_ITEMS_MAX + 3   # 룰 목록은 전부
