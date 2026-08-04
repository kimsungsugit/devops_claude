# tests/unit/test_llm_provenance_contract.py
r"""LLM 응답 완결성 + 근거(provenance) 등급의 정직성 계약.

세 결함 모두 "확인하지 못한 것을 확인한 것처럼 다룬다" 는 같은 부류다.

## L1 — 잘린 응답이 완결된 응답과 구분되지 않았다

`finish_reason` 이 저장소 전체에 **0건**이었다(2026-07-29 실측). 재현:

    시나리오          finish_reason   추출 결과              절단 신호
    완전한 응답        STOP           함수는 ... 계산한다.     없음
    토큰 상한에 잘림    MAX_TOKENS     함수는 ... CRC 를       없음
    안전필터 차단      SAFETY         함수는                 없음

호출자는 넷을 구분할 수 없었고 **잘린 초안이 완결된 산출물로 문서에 들어갔다.**

## L2 — 근거 없이 provenance 를 승격했다

    케이스                asil          asil_source
    값 있음(정규화만)      asil d → D    inference → rule   ← 대소문자 정규화가 근거?
    ASIL 아예 없음        → QM          inference → rule   ← 기본값인데 규칙 유래로
    출처도 없음           → QM          None → rule        ← 아무 근거 없이 0.75

## L3 — 모르는 출처를 조용히 '추론' 으로 접었다

코드가 실제로 넣는 `uds`·`swcom`·`rag`·`module_inherit`·`default`·`srs_default_qm` 이
전부 미지값이라 `inference`(0.60)로 접혔다. 문서 유래는 과소, 근거 없는 기본값은 과대.
게다가 표에 "추론" 이라고 **찍혀서** 리뷰어가 그 분류를 사실로 읽는다.
"""
from __future__ import annotations

import pytest

from workflow.ai import _extract_finish_reason, _norm_finish_reason, _note_finish_reason

# ---------------------------------------------------------------------------
# L1 — 응답 완결성
# ---------------------------------------------------------------------------

class _Part:
    def __init__(self, text):
        self.text = text


class _Content:
    def __init__(self, text):
        self.parts = [_Part(text)]


class _Cand:
    def __init__(self, text, finish_reason):
        self.content = _Content(text)
        self.finish_reason = finish_reason
        self.text = text


class _Resp:
    def __init__(self, text, finish_reason):
        self.candidates = [_Cand(text, finish_reason)]
        self.text = text


class TestFinishReasonNormalization:
    @pytest.mark.parametrize(("raw", "want"), [
        ("STOP", "STOP"),
        ("stop", "STOP"),
        ("FinishReason.MAX_TOKENS", "MAX_TOKENS"),   # enum repr
        ("MAX_TOKENS", "MAX_TOKENS"),
        (2, "2"),
        (None, ""),
    ])
    def test_shapes_are_normalized(self, raw, want):
        assert _norm_finish_reason(raw) == want

    def test_extract_from_candidates(self):
        assert _extract_finish_reason(_Resp("t", "SAFETY")) == "SAFETY"

    def test_missing_shape_returns_empty_not_crash(self):
        assert _extract_finish_reason(object()) == ""


class TestTruncationIsSurfaced:
    @pytest.mark.parametrize("fr", ["MAX_TOKENS", "SAFETY", "RECITATION",
                                    "FinishReason.MAX_TOKENS"])
    def test_abnormal_finish_marks_truncated(self, fr):
        meta: dict = {}
        _note_finish_reason(meta, _Resp("부분", fr), None)
        assert meta["truncated"] is True
        assert meta["finish_reason_available"] is True

    def test_normal_finish_is_not_truncated(self):
        """대조군 — 정상 응답을 절단으로 오판하면 멀쩡한 생성이 계속 재시도된다."""
        meta: dict = {}
        _note_finish_reason(meta, _Resp("완전", "STOP"), None)
        assert meta["truncated"] is False

    def test_unknown_shape_is_not_treated_as_truncated(self):
        """SDK shape 를 모른다고 정상 응답을 버리면 그게 더 나쁘다.

        단 '확인 못 함' 과 '확인했고 정상' 은 구분해야 한다.
        """
        meta: dict = {}
        _note_finish_reason(meta, object(), None)
        assert meta["truncated"] is False
        assert meta["finish_reason_available"] is False

    def test_meta_out_none_does_not_crash(self):
        _note_finish_reason(None, _Resp("부분", "MAX_TOKENS"), None)


class TestAgentCallRetriesOnTruncation:
    """잘린 응답은 validator 실패와 같은 등급의 재시도 사유여야 한다."""

    def test_truncated_branch_exists_in_agent_call(self):
        import ast
        import inspect

        from workflow import ai as ai_mod

        src = inspect.getsource(ai_mod.agent_call)
        tree = ast.parse(src)
        found = any(
            isinstance(n, ast.Constant) and n.value == "truncated"
            for n in ast.walk(tree)
        )
        assert found, "agent_call 이 llm_meta['truncated'] 를 보지 않는다 — 잘린 초안이 통과한다"


# ---------------------------------------------------------------------------
# L2 — 근거 없는 승격
# ---------------------------------------------------------------------------

class TestNoEvidenceFreePromotion:
    @staticmethod
    def _run(info):
        from backend.helpers.uds import _enrich_function_quality_fields
        payload = {"function_details": {"F": dict(info)}, "function_details_by_name": {}}
        _enrich_function_quality_fields(payload)
        return payload["function_details"]["F"]

    def test_normalization_alone_does_not_upgrade_source(self):
        out = self._run({"name": "f", "asil": "asil d", "asil_source": "inference"})
        assert out["asil"] == "D"                      # 값은 정규화된다
        assert out["asil_source"] == "inference"       # 출처는 그대로 — 정규화는 근거가 아니다

    def test_missing_asil_is_not_fabricated(self):
        """⚠ 2026-07-31 로 불변식이 **강해졌다**.

        예전 계약은 "근거 없이 채운 QM 은 `rule`(0.75) 이 아니라 `default`(0.30) 로
        적어라" 였다 — 라벨만 정직해지고 **값은 여전히 지어냈다**. 이제는 아예 채우지
        않는다: `QM` 은 ISO 26262 에서 "안전 요구 면제" 라는 실질 주장이라, 근거의
        부재를 그걸로 바꾸면 under-classification 이다.

        옛 승격 회귀(`rule` 로 적기)도 계속 막는다 — 아래 두 번째 단언.
        """
        out = self._run({"name": "f", "asil": "", "asil_source": "inference"})
        assert out["asil"] == "", "근거가 없는데 등급을 지어냈다"
        assert out["asil_source"] == "inference", (
            "아무 일도 안 했는데 출처를 바꿨다 — 정규화도 승격도 근거가 아니다")

    def test_no_source_at_all_stays_unset(self):
        out = self._run({"name": "f", "asil": ""})
        assert out["asil"] == ""
        assert not str(out.get("asil_source") or "").strip(), (
            "채운 값이 없는데 출처를 발명했다")

    def test_tbd_is_preserved_not_blanked(self):
        """"없음" 과 "미정" 은 다른 상태다 — 접으면 구분이 사라진다."""
        out = self._run({"name": "f", "asil": "TBD"})
        assert out["asil"] == "TBD"

    def test_strong_source_is_preserved(self):
        """대조군 — 실제 문서 유래 출처를 깎아내리면 안 된다."""
        out = self._run({"name": "f", "asil": "C", "asil_source": "sds"})
        assert out["asil_source"] == "sds"


# ---------------------------------------------------------------------------
# L3 — 출처 어휘 드리프트
# ---------------------------------------------------------------------------

def _confidence_report(tmp_path, infos):
    from report_gen.validation import generate_asil_related_confidence_report

    out = tmp_path / "conf.md"
    generate_asil_related_confidence_report(
        {"function_details": {f"F{i}": v for i, v in enumerate(infos)}}, str(out))
    return out.read_text(encoding="utf-8")


class TestSourceVocabularyMatchesProducers:
    """생산 코드가 실제로 넣는 값이 어휘에 있어야 한다."""

    PRODUCED = ["uds", "swcom", "rag", "module_inherit", "default",
                "srs_default_qm", "call_graph", "hsis", "sds_match"]

    @pytest.mark.parametrize("value", PRODUCED)
    def test_produced_value_is_not_classified_unknown(self, value, tmp_path):
        txt = _confidence_report(tmp_path, [
            {"name": "f", "asil": "D", "asil_source": value,
             "description": "d", "description_source": "comment",
             "related": "SwRS_1", "related_source": "sds"},
        ])
        assert "분류 불가 출처값" not in txt, f"생산 어휘 '{value}' 가 미지값으로 접힌다"

    def test_document_sourced_outscores_inference(self, tmp_path):
        """`uds`/`swcom` 은 문서 유래 — 추론(0.60)과 같은 점수면 안 된다."""
        from report_gen.validation import generate_asil_related_confidence_report

        def _avg(src):
            out = tmp_path / f"{src}.md"
            generate_asil_related_confidence_report({"function_details": {"F": {
                "name": "f", "asil": "D", "asil_source": src,
                "description": "d", "description_source": src,
                "related": "SwRS_1", "related_source": src}}}, str(out))
            for line in out.read_text(encoding="utf-8").splitlines():
                if "Overall confidence score" in line:
                    return float(line.split("`")[1])
            raise AssertionError("점수 줄을 못 찾음")

        assert _avg("uds") > _avg("inference")
        assert _avg("default") < _avg("inference"), "근거 없는 기본값이 추론보다 높다"

    def test_truly_unknown_value_is_surfaced_not_folded(self, tmp_path):
        """어휘에 없는 값은 조용히 '추론' 이 되면 안 된다 — 보고서에 드러나야 한다."""
        txt = _confidence_report(tmp_path, [
            {"name": "f", "asil": "D", "asil_source": "완전히_새로운_출처",
             "description": "d", "description_source": "comment",
             "related": "SwRS_1", "related_source": "sds"},
        ])
        assert "분류 불가 출처값" in txt
        assert "완전히_새로운_출처" in txt

    def test_known_vocabulary_produces_no_warning(self, tmp_path):
        """대조군 — 아는 값만 있으면 경고가 없어야 한다(경고 남발 방지)."""
        txt = _confidence_report(tmp_path, [
            {"name": "f", "asil": "D", "asil_source": "sds",
             "description": "d", "description_source": "comment",
             "related": "SwRS_1", "related_source": "srs"},
        ])
        assert "분류 불가 출처값" not in txt


# ---------------------------------------------------------------------------
# L4 — 어느 모델이 답했는지 meta 가 거짓을 말하던 것
# ---------------------------------------------------------------------------

class _RespModel:
    def __init__(self, model_version=None):
        if model_version is not None:
            self.model_version = model_version


class TestEffectiveModelIsRecorded:
    r"""`meta_out["model"]` 은 호출 **전** cfg 값으로 한 번만 찍혔다.

    400 폴백이 성공하면 답한 모델은 `model_fallback` 이라는 **다른 키**에만 갔고,
    그 키는 저장소 어디서도 읽히지 않았다. `meta.get("model")` 을 읽는 소비처
    (`workflow/gui_utils.py` 의 `ai_model` 2곳)는 **실패한 모델**을 산출물의 모델
    근거로 기록했다. `.env` 가 특정 모델을 하드락하는 운영 방식이라 이 값은 근거의 일부다.
    """

    def test_model_key_holds_the_answering_model(self):
        from workflow.ai import _note_effective_model

        meta = {"model_requested": "gemini-3.5-flash-lite", "model": "gemini-3.5-flash-lite"}
        _note_effective_model(meta, "gemini-2.5-flash", _RespModel("gemini-2.5-flash"), None)
        assert meta["model"] == "gemini-2.5-flash", "폴백 후에도 실패한 모델이 남았다"
        assert meta["model_requested"] == "gemini-3.5-flash-lite"

    def test_provider_echo_is_captured(self):
        from workflow.ai import _note_effective_model

        meta: dict = {}
        _note_effective_model(meta, "gemini-2.5-flash", _RespModel("gemini-2.5-flash-001"), None)
        assert meta["model_reported"] == "gemini-2.5-flash-001"

    def test_version_suffix_is_not_a_mismatch(self):
        """대조군 — 정확일치를 요구하면 정상 응답이 전부 불일치로 잡힌다."""
        from workflow.ai import _note_effective_model

        meta: dict = {}
        _note_effective_model(meta, "gemini-2.5-flash", _RespModel("gemini-2.5-flash-001"), None)
        assert meta["model_mismatch"] is False

    def test_different_model_is_flagged(self):
        from workflow.ai import _note_effective_model

        meta: dict = {}
        _note_effective_model(meta, "gemini-3.5-flash-lite", _RespModel("gemini-1.5-pro"), None)
        assert meta["model_mismatch"] is True

    def test_absent_echo_does_not_claim_mismatch(self):
        """모르는 것을 불일치로 단정하면 거짓 경고가 난다."""
        from workflow.ai import _note_effective_model

        meta: dict = {}
        _note_effective_model(meta, "gemini-2.5-flash", _RespModel(), None)
        assert meta["model_reported"] == ""
        assert meta["model_mismatch"] is False

    def test_openai_dict_shape_is_supported(self):
        from workflow.ai import _note_effective_model

        meta: dict = {}
        _note_effective_model(meta, "gpt-4o-mini", {"model": "gpt-4o-mini-2024"}, None)
        assert meta["model_reported"] == "gpt-4o-mini-2024"
        assert meta["model_mismatch"] is False

    def test_meta_out_none_does_not_crash(self):
        from workflow.ai import _note_effective_model

        _note_effective_model(None, "m", _RespModel("m"), None)


class TestFallbackBranchIsNotAWeakerCopy:
    """폴백 분기는 정상 경로의 복사본이라 검사가 빠지기 쉽다 — 실제로 둘이 빠져 있었다."""

    @staticmethod
    def _fallback_src() -> str:
        import inspect

        from workflow import ai as ai_mod

        src = inspect.getsource(ai_mod.llm_call)
        i = src.find("is_bad_request and fallback_model")
        assert i > 0, "폴백 분기를 못 찾았다 — 구조가 바뀌었으면 이 테스트도 갱신할 것"
        return src[i:i + 1800]

    def test_fallback_checks_finish_reason(self):
        assert "_note_finish_reason" in self._fallback_src(), (
            "폴백 응답이 잘려도 완결본으로 통과한다")

    def test_fallback_records_effective_model(self):
        assert "_note_effective_model" in self._fallback_src(), (
            "폴백 후에도 model 키가 실패한 모델을 가리킨다")

    def test_fallback_keeps_legacy_key(self):
        """기존 `model_fallback` 키를 없애면 (읽는 곳은 없지만) 로그 계약이 깨진다."""
        assert "model_fallback" in self._fallback_src()


# ---------------------------------------------------------------------------
# L5 — 독립 egress(어댑터 스택)가 같은 검사를 우회하던 것
# ---------------------------------------------------------------------------

class TestAdapterStackSharesTheJudgment:
    r"""`workflow/llm_adapters.py` 는 `ai.llm_call` 을 **안 거치는 독립 egress** 다.

    `backend/services/assistant_service.py::_call_anthropic` 과
    `scripts/generate_periodic_reports.py` 가 의도적으로 여기를 쓴다. llm_call 에 넣은
    검사가 어댑터에 없으면 같은 결함(잘린 응답을 완결본으로 취급, 모델 근거 부재)이
    **그 경로에만** 남는다.

    판정은 `ai.py` 단일 출처(`note_finish_reason_value` / `note_effective_model`)를 쓰고
    어댑터는 공급자별 shape 추출만 한다.
    """

    def test_completion_meta_marks_truncation(self):
        from workflow.llm_adapters import _completion_meta

        m = _completion_meta("claude-x", object(), finish_raw="max_tokens")
        assert m["truncated"] is True
        assert m["finish_reason"] == "MAX_TOKENS"

    def test_anthropic_end_turn_is_normal(self):
        """대조군 — Anthropic 정상 종료(`end_turn`)를 절단으로 오판하면 안 된다."""
        from workflow.llm_adapters import _completion_meta

        assert _completion_meta("claude-x", object(), finish_raw="end_turn")["truncated"] is False

    def test_openai_length_is_truncation(self):
        from workflow.llm_adapters import _completion_meta

        assert _completion_meta("gpt-x", object(), finish_raw="length")["truncated"] is True

    def test_model_echo_is_compared(self):
        from workflow.llm_adapters import _completion_meta

        m = _completion_meta("claude-3-5-sonnet", {"model": "claude-3-opus"}, finish_raw="end_turn")
        assert m["model_mismatch"] is True

    def test_unknown_finish_is_not_truncation(self):
        from workflow.llm_adapters import _completion_meta

        m = _completion_meta("m", object(), finish_raw=None)
        assert m["truncated"] is False
        assert m["finish_reason_available"] is False

    @pytest.mark.parametrize("adapter_name", ["GeminiAdapter", "OpenAIAdapter", "AnthropicAdapter"])
    def test_every_adapter_returns_completion_meta(self, adapter_name):
        """세 어댑터 중 하나라도 빠지면 그 공급자에서만 결함이 남는다."""
        import inspect

        from workflow import llm_adapters as mod

        src = inspect.getsource(getattr(mod, adapter_name).generate)
        assert "_completion_meta" in src, f"{adapter_name} 가 완결성/모델 정보를 안 낸다"

    def test_judgment_is_not_duplicated_in_adapters(self):
        """어댑터가 자체 판정 목록을 만들면 ai.py 와 갈라진다."""
        import inspect

        from workflow import llm_adapters as mod

        src = inspect.getsource(mod)
        assert "note_finish_reason_value" in src, "판정을 ai.py 단일 출처에서 안 가져온다"
        assert "_OK_FINISH_REASONS" not in src, "어댑터가 정상종료 목록을 복제했다"


class TestAnthropicChatPathIsConsistent:
    """같은 챗이 공급자에 따라 다르게 정직하면 안 된다."""

    def test_truncated_response_is_not_returned_as_answer(self):
        import inspect

        from backend.services import assistant_service as svc

        src = inspect.getsource(svc._call_anthropic)
        assert 'result.get("truncated")' in src, (
            "Anthropic 경로만 잘린 답변을 완결 답변으로 돌려준다 "
            "(agent_call 경로는 절단을 재시도 사유로 다룬다)")


# ---------------------------------------------------------------------------
# L6 — 나가는 프롬프트의 시크릿
# ---------------------------------------------------------------------------

class TestOutgoingSecretRedaction:
    r"""프롬프트에 실제 시크릿이 들어가면 가린다 — **정규식 추측이 아니라 값 대조**.

    `workflow/ai_validator.py` 에 시크릿 탐지가 있지만 모듈 전체가 dead code 이고
    (프로덕션 호출자 0건), 그 검사는 프롬프트가 아니라 **응답**을 보며 경고만 낸다.
    게다가 정규식(`password\s*[=:]`·IP)이 이 저장소에선 오탐이 심하다 — 프롬프트에
    Jenkins URL 과 C 소스가 늘 들어가 거의 매 호출 경고가 뜬다(= 소음이 되어 무의미).

    그래서 env 의 **실제 값**과 문자열 대조만 한다. 오탐이 원리적으로 없다.
    """

    SECRET = "AIzaSyFAKE_TEST_KEY_1234567890abcdef"

    @pytest.fixture()
    def with_secret(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", self.SECRET)

    def test_real_secret_is_redacted(self, with_secret):
        from workflow.ai import redact_known_secrets

        out, names = redact_known_secrets(f"키는 {self.SECRET} 이다")
        assert self.SECRET not in out
        assert names == ["GOOGLE_API_KEY"]

    def test_lookalike_text_is_untouched(self, with_secret):
        """대조군 — IP·`password` 같은 단어가 든 정상 프롬프트를 훼손하면 안 된다."""
        from workflow.ai import redact_known_secrets

        text = "Jenkins 192.168.110.40:7000. password = check_pw(x); 를 분석하라"
        out, names = redact_known_secrets(text)
        assert out == text and names == []

    def test_no_secret_configured_is_noop(self, monkeypatch):
        from workflow.ai import sanitize_messages

        for n in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
                  "ANTHROPIC_API_KEY", "OAI_API_KEY", "DEVOPS_SCM_PASSWORD",
                  "DEVOPS_JENKINS_API_TOKEN", "JENKINS_TOKEN", "JENKINS_API_TOKEN"):
            monkeypatch.delenv(n, raising=False)
        msgs = [{"role": "user", "content": "x"}]
        assert sanitize_messages(msgs) is msgs      # 사본조차 안 만든다

    def test_short_value_is_not_used_as_a_needle(self, monkeypatch):
        """짧은 값은 본문에 우연히 등장한다 — 멀쩡한 프롬프트를 훼손하면 안 된다."""
        monkeypatch.setenv("JENKINS_TOKEN", "abc")
        from workflow.ai import redact_known_secrets

        out, names = redact_known_secrets("abcdef 를 계산한다")
        assert out == "abcdef 를 계산한다" and names == []

    def test_original_messages_are_not_mutated(self, with_secret):
        from workflow.ai import sanitize_messages

        msgs = [{"role": "user", "content": f"키 {self.SECRET}"}]
        out = sanitize_messages(msgs)
        assert self.SECRET in msgs[0]["content"], "원본을 훼손했다"
        assert self.SECRET not in out[0]["content"]

    def test_non_dict_entries_survive(self, with_secret):
        from workflow.ai import sanitize_messages

        assert sanitize_messages(["문자열", None])[0] == "문자열"

    def test_llm_call_sanitizes_before_sending(self):
        import inspect

        from workflow import ai as ai_mod

        src = inspect.getsource(ai_mod.llm_call)
        assert "sanitize_messages(messages)" in src
        # 절단 **뒤**여야 한다 — 앞이면 `[REDACTED:...]` 가 잘려 시크릿 일부가 남는다
        assert src.index("_trim_messages_to_token_budget(messages") < src.index("sanitize_messages(messages)")

    @pytest.mark.parametrize("adapter_name", ["GeminiAdapter", "OpenAIAdapter", "AnthropicAdapter"])
    def test_every_adapter_sanitizes(self, adapter_name):
        import inspect

        from workflow import llm_adapters as mod

        src = inspect.getsource(getattr(mod, adapter_name).generate)
        assert "_sanitize_outgoing(messages)" in src, f"{adapter_name} 는 프롬프트를 안 가린다"

