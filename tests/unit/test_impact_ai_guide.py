"""Tests for workflow.impact_ai_guide (deterministic parts + LLM enrichment wiring)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import workflow.ai as _wai  # monkeypatch 타깃 (lazy import가 이 모듈 속성을 읽음)
from workflow.impact_ai_guide import (
    assess_risk,
    analyze_cross_document_impact,
    generate_impact_guide,
    ImpactGuideContext,
)


@pytest.fixture(autouse=True)
def _force_deterministic(monkeypatch):
    """기본적으로 LLM 미설정으로 강제 — 결정론 경로.

    dev 머신에 Gemini config가 있어도 단위테스트가 실제 LLM 네트워크 호출을 하지 않도록
    load_oai_config를 None으로 패치. enrichment 테스트는 이 위에 자체 setattr로 덮어쓴다.
    """
    monkeypatch.setattr(_wai, "load_oai_config", lambda *_a, **_k: None, raising=True)


class TestAssessRisk:
    def test_empty_changes(self):
        risk = assess_risk({}, {}, {})
        assert risk.grade == "LOW"
        assert risk.score == 0

    def test_qm_body_change(self):
        changed = {"func_a": "BODY"}
        by_name = {"func_a": {"asil": "QM"}}
        risk = assess_risk(changed, by_name, {"direct": ["func_a"]})
        assert risk.grade in ("LOW", "MEDIUM")
        assert not risk.asil_escalation

    def test_asil_d_signature_critical(self):
        changed = {"safety_func": "SIGNATURE"}
        by_name = {"safety_func": {"asil": "D"}}
        impact = {"direct": ["safety_func"], "indirect_1hop": ["dep1", "dep2", "dep3"]}
        risk = assess_risk(changed, by_name, impact)
        assert risk.grade in ("HIGH", "CRITICAL")
        assert risk.asil_escalation
        assert risk.max_asil == "D"
        assert any("safety_func" in sf for sf in risk.affected_safety_functions)

    def test_asil_b_escalation(self):
        changed = {"brake_ctrl": "BODY"}
        by_name = {"brake_ctrl": {"asil": "B"}}
        risk = assess_risk(changed, by_name, {"direct": ["brake_ctrl"]})
        assert risk.asil_escalation

    def test_large_scope_high(self):
        changed = {f"func_{i}": "BODY" for i in range(10)}
        by_name = {f"func_{i}": {"asil": "A"} for i in range(10)}
        impact = {"direct": [f"func_{i}" for i in range(10)],
                  "indirect_1hop": [f"dep_{i}" for i in range(15)]}
        risk = assess_risk(changed, by_name, impact)
        assert risk.score >= 25  # at least MEDIUM
        assert risk.grade in ("MEDIUM", "HIGH", "CRITICAL")

    def test_mixed_asil(self):
        changed = {"qm_func": "BODY", "asil_c_func": "HEADER"}
        by_name = {"qm_func": {"asil": "QM"}, "asil_c_func": {"asil": "C"}}
        risk = assess_risk(changed, by_name, {"direct": list(changed.keys())})
        assert risk.max_asil == "C"


class TestAnalyzeCrossDocumentImpact:
    def test_signature_affects_all(self):
        changed = {"func_a": "SIGNATURE"}
        result = analyze_cross_document_impact(changed)
        assert "uds" in result
        assert "suts" in result
        assert "sits" in result
        assert "sts" in result

    def test_body_change(self):
        changed = {"func_a": "BODY"}
        result = analyze_cross_document_impact(changed)
        assert "uds" in result
        assert "suts" in result
        assert "sds" in result  # BODY now affects SDS (design description update)

    def test_filtered_targets(self):
        changed = {"func_a": "SIGNATURE"}
        result = analyze_cross_document_impact(changed, targets=["uds", "suts"])
        assert "uds" in result
        assert "suts" in result
        assert "sits" not in result

    def test_empty_changes(self):
        result = analyze_cross_document_impact({})
        assert result == {}


class TestGenerateImpactGuide:
    def test_basic_guide(self):
        ctx = ImpactGuideContext(
            changed_types={"brake_ctrl": "BODY"},
            impact_groups={"direct": ["brake_ctrl"]},
            by_name={"brake_ctrl": {"asil": "QM", "description": "Brake control"}},
        )
        guide = generate_impact_guide(ctx)
        assert guide.risk.grade in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert guide.executive_summary
        assert guide.generated_at
        assert isinstance(guide.cross_doc_impacts, dict)
        assert isinstance(guide.review_checklist, list)

    def test_high_risk_has_checklist(self):
        ctx = ImpactGuideContext(
            changed_types={"safety_func": "SIGNATURE"},
            impact_groups={"direct": ["safety_func"], "indirect_1hop": ["dep1", "dep2"]},
            by_name={"safety_func": {"asil": "D"}},
        )
        guide = generate_impact_guide(ctx)
        assert guide.risk.asil_escalation
        # Should have CRITICAL priority item in checklist
        critical_items = [c for c in guide.review_checklist if c.get("priority") == "CRITICAL"]
        assert len(critical_items) >= 1

    def test_to_dict(self):
        ctx = ImpactGuideContext(
            changed_types={"func_a": "BODY"},
            impact_groups={},
            by_name={},
        )
        guide = generate_impact_guide(ctx)
        d = guide.to_dict()
        assert "executive_summary" in d
        assert "risk" in d
        assert "review_checklist" in d
        assert "cross_doc_impacts" in d
        assert "ai_enriched" in d

    def test_empty_context(self):
        ctx = ImpactGuideContext(
            changed_types={},
            impact_groups={},
            by_name={},
        )
        guide = generate_impact_guide(ctx)
        assert guide.risk.grade == "LOW"

    def test_test_recommendations_for_new(self):
        ctx = ImpactGuideContext(
            changed_types={"new_func": "NEW"},
            impact_groups={"direct": ["new_func"]},
            by_name={"new_func": {"asil": "A"}},
            suts_tcs={},  # no existing TCs
        )
        guide = generate_impact_guide(ctx)
        assert len(guide.test_recommendations) >= 1
        assert any("신규" in r.get("test_type", "") or "NEW" in r.get("test_type", "")
                    for r in guide.test_recommendations)


def test_unknown_asil_not_silently_defaulted_to_qm():
    """ASIL 정보가 없으면 QM(비안전)으로 단정하지 않고 UNKNOWN으로 표시 + 수동확인 체크리스트(안전측, CLAUDE.md #4)."""
    from workflow.impact_ai_guide import generate_impact_guide, ImpactGuideContext

    g = generate_impact_guide(ImpactGuideContext(
        changed_types={"foo": "BODY"},
        impact_groups={"direct": ["foo"], "indirect_1hop": [], "indirect_2hop": []},
        by_name={},  # ASIL 정보 없음
    )).to_dict()
    assert g["risk"]["unknown_asil_count"] >= 1
    assert g["risk"]["max_asil"] == "UNKNOWN"
    assert g["risk"]["grade"] != "LOW"   # 미상이면 LOW 단정 금지
    assert any("ASIL 미상" in c.get("item", "") for c in g["review_checklist"])


def test_known_asil_still_classified():
    """명시적 ASIL D는 정상 분류(회귀 보호)."""
    from workflow.impact_ai_guide import generate_impact_guide, ImpactGuideContext

    g = generate_impact_guide(ImpactGuideContext(
        changed_types={"safety_fn": "SIGNATURE"},
        impact_groups={"direct": ["safety_fn"], "indirect_1hop": [], "indirect_2hop": []},
        by_name={"safety_fn": {"asil": "D"}},
    )).to_dict()
    assert g["risk"]["max_asil"] == "D"
    assert g["risk"]["unknown_asil_count"] == 0
    assert g["risk"]["asil_escalation"] is True


class TestLLMEnrichmentWiring:
    """H1 회귀 그물 — LLM 강화 경로가 실제 배선돼 동작하는지 검증.

    과거 generate_change_summary/suggest_test_additions가 agent_call를 존재하지 않는
    시그니처(system_prompt=/user_prompt=)로 호출해 매번 TypeError→결정론 폴백 고정,
    ai_enriched가 영구 False였다. 이 테스트들은 그 배선 버그가 재발하면 즉시 실패한다.
    """

    def test_summary_enriched_when_llm_configured(self, monkeypatch):
        """cfg가 있고 agent_call_text가 텍스트를 주면 executive_summary가 LLM 값 + ai_enriched=True."""
        monkeypatch.setattr(_wai, "load_oai_config", lambda *_a, **_k: {"model": "gemini"}, raising=True)
        monkeypatch.setattr(
            _wai, "agent_call_text",
            lambda cfg, messages, **k: "## LLM 요약\n실제 AI가 작성한 영향도 요약본",
            raising=True,
        )
        g = generate_impact_guide(ImpactGuideContext(
            changed_types={"foo": "BODY"},
            impact_groups={"direct": ["foo"], "indirect_1hop": [], "indirect_2hop": []},
            by_name={"foo": {"asil": "B"}},
        )).to_dict()
        assert g["ai_enriched"] is True
        assert "실제 AI가 작성한" in g["executive_summary"]

    def test_test_recommendations_parsed_from_llm(self, monkeypatch):
        """```json 펜스로 감싼 배열도 견고하게 파싱되어 test_recommendations에 반영."""
        canned = (
            "여기 제안입니다:\n```json\n"
            '[{"function": "foo", "test_type": "경계값 재검증", '
            '"description": "인터페이스 변경", "rationale": "타입 변경"}]\n```'
        )
        monkeypatch.setattr(_wai, "load_oai_config", lambda *_a, **_k: {"model": "gemini"}, raising=True)
        monkeypatch.setattr(_wai, "agent_call_text", lambda cfg, messages, **k: canned, raising=True)
        g = generate_impact_guide(ImpactGuideContext(
            changed_types={"foo": "SIGNATURE"},
            impact_groups={"direct": ["foo"], "indirect_1hop": [], "indirect_2hop": []},
            by_name={"foo": {"asil": "C"}},
        )).to_dict()
        assert g["ai_enriched"] is True
        assert any(r.get("function") == "foo" and r.get("test_type") == "경계값 재검증"
                   for r in g["test_recommendations"])

    def test_malformed_llm_tests_fall_back_deterministic(self, monkeypatch):
        """LLM 응답이 malformed JSON이면 test_recommendations는 결정론 폴백(크래시/오염 없음)."""
        monkeypatch.setattr(_wai, "load_oai_config", lambda *_a, **_k: {"model": "gemini"}, raising=True)
        # 배열이 아닌 잡음 → _parse_test_suggestions_json이 []를 반환 → 결정론 폴백
        monkeypatch.setattr(_wai, "agent_call_text",
                            lambda cfg, messages, **k: "죄송합니다 JSON을 만들 수 없습니다",
                            raising=True)
        g = generate_impact_guide(ImpactGuideContext(
            changed_types={"new_func": "NEW"},
            impact_groups={"direct": ["new_func"], "indirect_1hop": [], "indirect_2hop": []},
            by_name={"new_func": {"asil": "A"}},
            suts_tcs={},
        )).to_dict()
        # NEW 함수 → 결정론 폴백이 '신규 TC 생성' 제안을 냄
        assert len(g["test_recommendations"]) >= 1
        assert any("신규" in r.get("test_type", "") for r in g["test_recommendations"])

    def test_no_config_stays_deterministic(self, monkeypatch):
        """cfg가 없으면(LLM 미설정) 예외 없이 결정론 유지 + ai_enriched=False."""
        # autouse가 이미 load_oai_config→None. agent_call_text가 호출되면 실패하도록 감시.
        def _boom(*_a, **_k):
            raise AssertionError("cfg 없음에도 agent_call_text가 호출됨")
        monkeypatch.setattr(_wai, "agent_call_text", _boom, raising=True)
        g = generate_impact_guide(ImpactGuideContext(
            changed_types={"foo": "BODY"},
            impact_groups={"direct": ["foo"], "indirect_1hop": [], "indirect_2hop": []},
            by_name={"foo": {"asil": "QM"}},
        )).to_dict()
        assert g["ai_enriched"] is False
        assert g["executive_summary"]  # 결정론 요약 존재


def test_explain_function_change_no_llm_returns_none(monkeypatch):
    """LLM 미설정이면 None(결정론 폴백) — 프론트가 매개변수 diff로 대체."""
    from workflow import impact_ai_guide
    from workflow import ai as _ai
    monkeypatch.setattr(_ai, "load_oai_config", lambda _p: None)
    out = impact_ai_guide.explain_function_change(
        function="foo", change_type="SIGNATURE",
        before="int foo(int a)", after="int foo(int a, int b)",
    )
    assert out is None


def test_explain_function_change_with_llm(monkeypatch):
    """LLM 설정 시 선언 원문을 프롬프트에 넣어 설명 문자열 반환."""
    from workflow import impact_ai_guide
    from workflow import ai as _ai
    captured = {}

    def _fake_call(cfg, messages, **k):
        captured["messages"] = messages
        return "매개변수 b(bool)가 추가되었습니다."

    monkeypatch.setattr(_ai, "load_oai_config", lambda _p: {"provider": "gemini"})
    monkeypatch.setattr(_ai, "agent_call_text", _fake_call)
    out = impact_ai_guide.explain_function_change(
        function="foo", change_type="SIGNATURE", asil="B",
        before="int foo(int a)", after="int foo(int a, int b)",
    )
    assert out and "매개변수" in out
    # 선언 원문이 프롬프트에 포함됐는지
    joined = " ".join(m["content"] for m in captured["messages"])
    assert "int foo(int a, int b)" in joined


def test_explain_function_change_injects_doc_content(monkeypatch):
    """doc_content(현재 문서 내용)가 프롬프트에 원문으로 주입돼 '원문→제안' 근거가 된다."""
    from workflow import impact_ai_guide
    from workflow import ai as _ai
    captured = {}

    def _fake_call(cfg, messages, **k):
        captured["messages"] = messages
        return "원문→제안 설명"

    monkeypatch.setattr(_ai, "load_oai_config", lambda _p: {"provider": "gemini"})
    monkeypatch.setattr(_ai, "agent_call_text", _fake_call)
    out = impact_ai_guide.explain_function_change(
        function="s_tunningparamread_16bitdata", change_type="BODY", asil="A",
        function_diff="@@ -1 +1 @@\n-old\n+new",
        doc_content={
            "uds": {"description": "튜닝 파라미터를 16bit로 읽어 반환한다",
                    "prototype": "void s_TunningParamRead_16bitData(void)",
                    "globals": ["s16g_FrM30OpGain"]},
            "sds": "16비트 튜닝값 읽기 컴포넌트",
            "suts": [{"tc_id": "SwUTC_1150", "expected": {"out": "0x4E"}}],
        },
    )
    assert out
    joined = " ".join(m["content"] for m in captured["messages"])
    # 각 문서 현재 내용이 프롬프트에 원문으로 실렸는지
    assert "튜닝 파라미터를 16bit로 읽어 반환한다" in joined
    assert "16비트 튜닝값 읽기 컴포넌트" in joined
    assert "SwUTC_1150" in joined
    # '원문→제안' 지시가 프롬프트에 존재
    assert "원문" in joined and "제안" in joined


def test_explain_function_change_without_doc_content_unchanged(monkeypatch):
    """doc_content 미제공(None) 시 기존 동작 유지 — 문서 원문 블록 없이 정상 설명."""
    from workflow import impact_ai_guide
    from workflow import ai as _ai
    captured = {}

    def _cap(cfg, messages, **k):
        captured["m"] = messages
        return "설명"

    monkeypatch.setattr(_ai, "load_oai_config", lambda _p: {"provider": "gemini"})
    monkeypatch.setattr(_ai, "agent_call_text", _cap)
    out = impact_ai_guide.explain_function_change(
        function="foo", change_type="SIGNATURE",
        before="int foo(int a)", after="int foo(int a, int b)",
    )
    assert out
    joined = " ".join(m["content"] for m in captured["m"])
    # doc_content 주입 블록 고유 마커(system 프롬프트의 지시문과 구분되는 context 삽입부)
    assert "[현재 문서 내용(원문) —" not in joined  # 원문 블록 미주입


def test_format_doc_content_for_prompt_serializes_all_docs():
    """직렬화 헬퍼가 uds/sds/suts/sts/sits를 라벨링해 캡한다(방어적·부분 결과)."""
    from workflow.impact_ai_guide import _format_doc_content_for_prompt
    s = _format_doc_content_for_prompt({
        "uds": {"description": "설명", "prototype": "void f(void)", "globals": ["g1", "g2"]},
        "sds": "SDS 내용",
        "sts": [{"tc_id": "T1", "description": "STS 시험", "inputs": {"a": "1"}}],
    })
    assert "UDS Description: 설명" in s
    assert "UDS Prototype: void f(void)" in s
    assert "UDS Used Globals: g1, g2" in s
    assert "SDS 내용" in s
    assert "STS TC: T1" in s
    assert len(s) <= 2000


def test_format_doc_content_for_prompt_empty_or_bad():
    """빈/비-dict 입력은 빈 문자열(방어적)."""
    from workflow.impact_ai_guide import _format_doc_content_for_prompt
    assert _format_doc_content_for_prompt(None) == ""
    assert _format_doc_content_for_prompt({}) == ""
    assert _format_doc_content_for_prompt("not a dict") == ""  # type: ignore[arg-type]
