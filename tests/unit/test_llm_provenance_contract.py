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

    def test_missing_asil_is_labelled_default_not_rule(self):
        out = self._run({"name": "f", "asil": "", "asil_source": "inference"})
        assert out["asil"] == "QM"
        assert out["asil_source"] == "default", "근거가 없어 쓴 기본값을 '룰' 로 적었다"

    def test_no_source_at_all_is_default(self):
        out = self._run({"name": "f", "asil": ""})
        assert out["asil_source"] == "default"

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
