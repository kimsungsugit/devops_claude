# /app/tests/unit/test_uds_ai.py
"""Unit tests for workflow/uds_ai.py - UDS AI section helpers (no LLM calls)."""

from __future__ import annotations

import json
from unittest.mock import patch

from workflow.uds_ai import (
    _trim_text,
    _normalize_evidence_item,
    _normalize_evidence_list,
    _normalize_section,
    _extract_json_payload,
    _parse_decision,
    _quality_warnings,
    _validate_sections,
    _repair_missing_sections,
    _build_section_prompt,
    _dynamic_max_retries,
    _collect_function_set,
)


class TestTrimText:
    def test_short_text(self):
        assert _trim_text("hello", 1000) == "hello"

    def test_long_text(self):
        text = "x" * 5000
        result = _trim_text(text, 500)
        assert len(result) < 5000
        assert "truncated" in result

    def test_none(self):
        assert _trim_text(None, 100) == ""


class TestNormalizeEvidenceItem:
    def test_dict_with_fields(self):
        item = {"source_type": "rag", "source_file": "a.c", "excerpt": "line 1"}
        result = _normalize_evidence_item(item)
        assert result is not None
        assert result["source_type"] == "rag"

    def test_string_item(self):
        result = _normalize_evidence_item("some note")
        assert result is not None
        assert result["source_type"] == "note"
        assert result["excerpt"] == "some note"

    def test_empty_dict(self):
        result = _normalize_evidence_item({})
        assert result is None

    def test_none(self):
        assert _normalize_evidence_item(None) is None


class TestNormalizeEvidenceList:
    def test_normal_list(self):
        items = [{"source_type": "rag", "excerpt": "test"}]
        result = _normalize_evidence_list(items)
        assert len(result) == 1

    def test_non_list(self):
        assert _normalize_evidence_list("not a list") == []

    def test_filters_invalid(self):
        items = [{}, {"source_type": "x", "excerpt": "ok"}, None]
        result = _normalize_evidence_list(items)
        assert len(result) == 1


class TestNormalizeSection:
    def test_dict_section(self):
        section = {"text": "Overview text", "evidence": []}
        result = _normalize_section(section)
        assert result["text"] == "Overview text"

    def test_string_section(self):
        result = _normalize_section("Some text")
        assert result["text"] == "Some text"
        assert len(result["evidence"]) == 1

    def test_na_section(self):
        result = _normalize_section("N/A")
        assert result["text"] == "N/A"
        assert result["evidence"] == []

    def test_none(self):
        result = _normalize_section(None)
        assert result["text"] == ""


class TestExtractJsonPayload:
    def test_valid_json(self):
        result = _extract_json_payload('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_with_extra_text(self):
        result = _extract_json_payload('Some text {"key": "value"} more text')
        assert result == {"key": "value"}

    def test_invalid_json(self):
        result = _extract_json_payload("not json at all")
        assert result is None

    def test_empty(self):
        assert _extract_json_payload("") is None
        assert _extract_json_payload(None) is None


class TestParseDecision:
    def test_accept(self):
        decision, reason = _parse_decision('{"decision": "accept", "reason": "good"}')
        assert decision == "accept"

    def test_retry(self):
        decision, reason = _parse_decision('{"decision": "retry", "reason": "bad format"}')
        assert decision == "retry"

    def test_keyword_fallback(self):
        decision, _ = _parse_decision("The output is acceptable, accept it.")
        assert decision == "accept"

    def test_empty(self):
        decision, _ = _parse_decision("")
        assert decision == "retry"


class TestQualityWarnings:
    def test_no_evidence_warning(self):
        sections = {
            "overview": {"text": "Some overview", "evidence": []},
            "requirements": {"text": "N/A", "evidence": []},
            "interfaces": {"text": "", "evidence": []},
            "uds_frames": {"text": "Frames text", "evidence": [{"source_type": "rag"}]},
            "notes": {"text": "Note", "evidence": []},
        }
        warnings = _quality_warnings(sections)
        assert any("overview" in w for w in warnings)
        assert any("notes" in w for w in warnings)
        assert not any("requirements" in w for w in warnings)

    def test_no_warnings_when_complete(self):
        sections = {
            "overview": {"text": "N/A", "evidence": []},
            "requirements": {"text": "N/A", "evidence": []},
            "interfaces": {"text": "N/A", "evidence": []},
            "uds_frames": {"text": "N/A", "evidence": []},
            "notes": {"text": "N/A", "evidence": []},
        }
        assert _quality_warnings(sections) == []


class TestValidateSections:
    def test_valid_payload(self):
        payload = {
            "overview": {"text": "t", "evidence": []},
            "requirements": {"text": "t", "evidence": []},
            "interfaces": {"text": "t", "evidence": []},
            "uds_frames": {"text": "t", "evidence": []},
            "notes": {"text": "t", "evidence": []},
            "document": "full doc",
        }
        assert _validate_sections(payload, detailed=True) is not None

    def test_missing_key(self):
        # Only 1 key present (< 2 required) → returns None
        payload = {
            "overview": {},
        }
        assert _validate_sections(payload, detailed=False) is None


class TestBuildSectionPrompt:
    def test_normal_prompt_no_repair_marker(self):
        prompt = _build_section_prompt("interfaces")
        assert "interfaces" in prompt
        assert "UDS Writer" in prompt
        assert "REPAIR" not in prompt

    def test_repair_prompt_has_marker(self):
        prompt = _build_section_prompt("interfaces", repair=True)
        assert "REPAIR" in prompt
        assert "interfaces" in prompt
        assert "UDS Writer" in prompt

    def test_repair_prompt_contains_all_normal_content(self):
        normal = _build_section_prompt("uds_frames")
        repair = _build_section_prompt("uds_frames", repair=True)
        # repair prompt는 normal보다 길어야 함
        assert len(repair) > len(normal)
        # ASIL/Related 규칙은 repair에도 포함
        assert "ASIL" in repair
        assert "Related ID" in repair


class TestRepairMissingSections:
    def _make_raw(self, **overrides):
        base = {
            "overview": {"text": "real overview", "evidence": []},
            "requirements": {"text": "real reqs", "evidence": []},
            "interfaces": {"text": "N/A", "evidence": []},
            "uds_frames": {"text": "N/A", "evidence": []},
            "notes": {"text": "N/A", "evidence": []},
        }
        base.update(overrides)
        return base

    def test_no_repair_when_all_present(self):
        raw = {k: {"text": "real content", "evidence": []} for k in
               ["overview", "requirements", "interfaces", "uds_frames", "notes"]}
        result = _repair_missing_sections(raw, cfg={}, user_payload={}, analysis_payload={})
        assert result is raw

    def test_repairs_na_sections(self):
        raw = self._make_raw()
        repaired_section = {"text": "Interfaces description", "evidence": []}

        def mock_call_role(cfg, *, role, stage, messages, temperature=0.2):
            return {"output": json.dumps(repaired_section)}

        with patch("workflow.uds_ai._call_role", side_effect=mock_call_role):
            result = _repair_missing_sections(
                raw, cfg={}, user_payload={}, analysis_payload={}
            )

        assert result["interfaces"]["text"] == "Interfaces description"
        assert result["uds_frames"]["text"] == "Interfaces description"
        assert result["notes"]["text"] == "Interfaces description"
        assert result["overview"]["text"] == "real overview"
        assert result["requirements"]["text"] == "real reqs"

    def test_keeps_na_when_repair_fails(self):
        raw = self._make_raw()

        def mock_call_role(cfg, *, role, stage, messages, temperature=0.2):
            return {"output": json.dumps({"text": "N/A", "evidence": []})}

        with patch("workflow.uds_ai._call_role", side_effect=mock_call_role):
            result = _repair_missing_sections(
                raw, cfg={}, user_payload={}, analysis_payload={}
            )

        assert result["interfaces"]["text"] == "N/A"

    def test_already_generated_included_in_prompt(self):
        raw = self._make_raw()
        captured_messages = []

        def mock_call_role(cfg, *, role, stage, messages, temperature=0.2):
            captured_messages.extend(messages)
            return {"output": json.dumps({"text": "repaired", "evidence": []})}

        with patch("workflow.uds_ai._call_role", side_effect=mock_call_role):
            _repair_missing_sections(raw, cfg={}, user_payload={}, analysis_payload={})

        user_content = json.loads(captured_messages[1]["content"])
        assert "already_generated" in user_content
        assert "overview" in user_content["already_generated"]


class TestDynamicRetry:
    """라운드 C T512: _dynamic_max_retries 회귀."""

    def test_very_low_confidence_3_retries(self):
        assert _dynamic_max_retries(0.0) == 3
        assert _dynamic_max_retries(0.2) == 3
        assert _dynamic_max_retries(0.29) == 3

    def test_mid_confidence_2_retries(self):
        assert _dynamic_max_retries(0.3) == 2
        assert _dynamic_max_retries(0.5) == 2
        assert _dynamic_max_retries(0.59) == 2

    def test_high_confidence_1_retry(self):
        assert _dynamic_max_retries(0.6) == 1
        assert _dynamic_max_retries(0.79) == 1

    def test_very_high_confidence_0_retries(self):
        assert _dynamic_max_retries(0.8) == 0
        assert _dynamic_max_retries(0.95) == 0
        assert _dynamic_max_retries(1.0) == 0

    def test_invalid_confidence_fallback_to_legacy_default(self):
        """nonsense confidence → fallback 2 (legacy max_retries)."""
        assert _dynamic_max_retries(None) == 2  # type: ignore[arg-type]
        assert _dynamic_max_retries("abc") == 2  # type: ignore[arg-type]


class TestCollectFunctionSet:
    """라운드 C T502: _collect_function_set source_sections 추출."""

    def test_empty_source_sections_returns_empty_frozenset(self):
        result = _collect_function_set({})
        assert result == frozenset()
        assert isinstance(result, frozenset)

    def test_extracts_function_call_patterns(self):
        source_sections = {
            "interfaces": "void main(void) { s_Init(); g_DataUpdate(arg); }",
        }
        result = _collect_function_set(source_sections)
        # 3자리 이상 함수만 (정규식 \w{2,})
        assert "main" in result
        assert "s_Init" in result
        assert "g_DataUpdate" in result

    def test_ignores_non_string_values(self):
        """source_sections에 None 또는 dict 값 있으면 graceful skip."""
        source_sections = {
            "interfaces": None,
            "uds_frames": {"nested": "dict"},
            "overview": "g_GoodFunc()",
        }
        result = _collect_function_set(source_sections)
        # str 값만 처리 — g_GoodFunc 추출
        assert "g_GoodFunc" in result


class TestJudgeEscalation:
    """라운드 C T512: call_judge JSON parse + verdict 회귀."""

    def test_call_judge_valid_response(self):
        """call_judge mock — agent_call이 valid JSON 반환 시 정확 parse."""
        from workflow.ai import call_judge

        with patch("workflow.ai.agent_call") as mock_agent:
            mock_agent.return_value = {
                "ok": True,
                "output": '{"confidence": 0.85, "verdict": "trust", "rationale": "all checks passed"}',
            }
            result = call_judge(
                cfg={},
                payload={"overview": {}},
                semantic_findings=[],
                reviewer_decision={"decision": "accept", "reason": ""},
                judge_prompt="judge prompt text",
            )
            assert result["verdict"] == "trust"
            assert result["confidence"] == 0.85
            assert "passed" in result["rationale"]

    def test_call_judge_invalid_json_fallback(self):
        """call_judge — invalid JSON 응답 시 fallback {retry, 0.5, parse_failed}."""
        from workflow.ai import call_judge

        with patch("workflow.ai.agent_call") as mock_agent:
            mock_agent.return_value = {
                "ok": True,
                "output": "not a json at all",
            }
            result = call_judge(
                cfg={}, payload={}, semantic_findings=[],
                reviewer_decision={"decision": "reject", "reason": "x"},
                judge_prompt="p",
            )
            assert result["verdict"] == "retry"
            assert result["confidence"] == 0.5
            assert "parse_failed" in result["rationale"]

    def test_call_judge_invalid_verdict_fallback(self):
        """verdict가 trust/retry/abort 아니면 fallback."""
        from workflow.ai import call_judge

        with patch("workflow.ai.agent_call") as mock_agent:
            mock_agent.return_value = {
                "ok": True,
                "output": '{"confidence": 0.7, "verdict": "MAYBE", "rationale": "wat"}',
            }
            result = call_judge(
                cfg={}, payload={}, semantic_findings=[],
                reviewer_decision={"decision": "accept", "reason": ""},
                judge_prompt="p",
            )
            assert result["verdict"] == "retry"
            assert "parse_failed" in result["rationale"]

    def test_call_judge_clamps_confidence_to_unit_interval(self):
        """confidence > 1.0 또는 < 0.0 → clamp."""
        from workflow.ai import call_judge

        with patch("workflow.ai.agent_call") as mock_agent:
            mock_agent.return_value = {
                "ok": True,
                "output": '{"confidence": 1.5, "verdict": "trust", "rationale": "x"}',
            }
            result = call_judge(
                cfg={}, payload={}, semantic_findings=[],
                reviewer_decision={"decision": "accept", "reason": ""},
                judge_prompt="p",
            )
            assert result["confidence"] == 1.0

    def test_call_judge_no_output_fallback(self):
        """agent_call이 output 없을 시 fallback."""
        from workflow.ai import call_judge

        with patch("workflow.ai.agent_call") as mock_agent:
            mock_agent.return_value = {"ok": False, "output": None, "reason": "run_mode_off"}
            result = call_judge(
                cfg={}, payload={}, semantic_findings=[],
                reviewer_decision={"decision": "accept", "reason": ""},
                judge_prompt="p",
            )
            assert result["verdict"] == "retry"
            assert result["confidence"] == 0.5


class TestQualityWarningsSemanticJudge:
    """라운드 C T513: warning_categories에 [semantic]/[judge] prefix 통합 검증."""

    def test_semantic_prefix_warning_categorized(self):
        from backend.services.warning_categories import categorize_warnings
        warnings = [
            "[semantic] source_file: missing.c 미존재",
            "[semantic] score=0.5 (passed=False)",
            "[hmr] stamp",
        ]
        result = categorize_warnings(warnings)
        assert result["semantic"] == 2
        assert result["hmr"] == 1
        assert result["other"] == 0

    def test_judge_prefix_warning_categorized(self):
        from backend.services.warning_categories import categorize_warnings
        warnings = [
            "[judge] verdict=retry, confidence=0.45",
        ]
        result = categorize_warnings(warnings)
        assert result["judge"] == 1


class TestFunctionDescriptionPass2Body:
    """2차 refinement의 body는 function_details가 아니라 body_snippets 인자에서 온다.

    회귀 대상: uds_ai가 `function_details[fid]["body_text"]`를 읽었으나 어느 detail 생성
    지점도 그 키를 넣지 않아 Pass 2가 **한 번도 실행된 적 없는 dead path**였다.
    """

    _FD = {
        "F1": {
            "name": "foo_func",
            "description_source": "inference",
            "prototype": "void foo_func(void)",
        },
    }
    _BODY = "if (u16t_Data > 0) { s_DoSomething(); } else { s_HandleError(); }"

    def _run(self, body_snippets):
        stages: list = []

        def _fake_call_role(cfg, *, role, stage, messages, **kw):
            stages.append(stage)
            return {"ok": True, "output": json.dumps(
                {"foo_func": "주기적으로 호출되어 입력을 검사하고 오류를 처리한다."},
                ensure_ascii=False,
            )}

        with patch("workflow.uds_ai.load_oai_configs", return_value=[{"model": "gemini-flash"}]), \
                patch("workflow.uds_ai._call_role", side_effect=_fake_call_role):
            from workflow.uds_ai import generate_ai_function_descriptions
            res = generate_ai_function_descriptions(
                dict(self._FD), {}, body_snippets=body_snippets,
            )
        return stages, res

    def test_pass1_always_runs(self):
        stages, res = self._run(None)
        assert any(s.startswith("func_desc_batch_") for s in stages)
        assert res.get("foo_func")

    def test_without_snippets_pass2_does_not_run(self):
        """인자가 없으면 2차 패스는 돌지 않는다(기존 동작 — 단, 이제 사유가 로그에 남는다)."""
        stages, _ = self._run(None)
        assert [s for s in stages if "p2" in s] == []

    def test_with_snippets_pass2_runs(self):
        """snippet을 넘기면 2차 패스가 실제로 실행된다(과거엔 넘길 방법 자체가 없었다)."""
        stages, _ = self._run({"F1": self._BODY})
        assert [s for s in stages if "p2" in s], f"pass2 미실행: {stages}"

    def test_legacy_body_key_in_detail_still_works(self):
        """외부 호출자가 detail에 body를 직접 채운 경우도 폴백으로 인정한다."""
        fd = {"F1": {**self._FD["F1"], "body": self._BODY}}
        stages: list = []

        def _fake_call_role(cfg, *, role, stage, messages, **kw):
            stages.append(stage)
            return {"ok": True, "output": json.dumps(
                {"foo_func": "주기적으로 호출되어 입력을 검사하고 오류를 처리한다."},
                ensure_ascii=False,
            )}

        with patch("workflow.uds_ai.load_oai_configs", return_value=[{"model": "gemini-flash"}]), \
                patch("workflow.uds_ai._call_role", side_effect=_fake_call_role):
            from workflow.uds_ai import generate_ai_function_descriptions
            generate_ai_function_descriptions(fd, {}, body_snippets=None)
        assert [s for s in stages if "p2" in s], f"legacy body 폴백 실패: {stages}"

    def test_short_body_is_not_a_pass2_candidate(self):
        """20자 미만 body는 정제 근거가 못 되므로 후보에서 빠진다(기존 규칙 유지)."""
        stages, _ = self._run({"F1": "x = 1;"})
        assert [s for s in stages if "p2" in s] == []


class TestAiReviewDecisionSurfaced:
    """retry 소진 후에도 reject인 초안을 승인본과 구분할 수 있어야 한다.

    회귀 대상: while 루프가 max_retries를 소진하면 decision이 여전히 reject여도
    best_raw를 그대로 최종본으로 반환했고, 그 사실이 반환값 어디에도 없었다.
    """

    @staticmethod
    def _payload_json():
        base = {"text": "이 단위는 입력을 검사하고 결과를 반환한다.", "evidence": []}
        return json.dumps({
            "overview": dict(base), "requirements": dict(base),
            "interfaces": dict(base), "uds_frames": dict(base), "notes": dict(base),
            "logic_diagrams": [],
        }, ensure_ascii=False)

    def _run(self, *, review_verdict: str):
        import config as _config
        payload_json = self._payload_json()

        def _fake_call_role(cfg, *, role, stage, messages, **kw):
            if stage == "uds_review":
                return {"ok": True, "output": json.dumps(
                    {"decision": review_verdict, "reason": "근거 불충분"}, ensure_ascii=False)}
            if stage == "uds_audit":
                return {"ok": True, "output": json.dumps({"decision": "accept", "reason": ""})}
            return {"ok": True, "output": payload_json}

        with patch("workflow.uds_ai.load_oai_config", return_value={"model": "m"}), \
                patch("workflow.uds_ai._call_role", side_effect=_fake_call_role), \
                patch("workflow.uds_ai._load_prompt", return_value="prompt"), \
                patch.object(_config, "UDS_JUDGE_ENABLED", False):
            from workflow.uds_ai import generate_uds_ai_sections
            return generate_uds_ai_sections(
                requirements_text="요구사항", source_sections={},
                notes_text="", logic_items=[], detailed=False,
            )

    def test_reject_is_reported_in_result(self):
        sections = self._run(review_verdict="reject")
        assert sections is not None
        assert sections["ai_review_decision"] == "reject"
        assert sections["ai_review_retry_count"] >= 1
        assert any("[ai-review]" in w for w in sections["quality_warnings"]), \
            sections["quality_warnings"]

    def test_accept_has_no_review_warning(self):
        sections = self._run(review_verdict="accept")
        assert sections is not None
        assert sections["ai_review_decision"] == "accept"
        assert sections["ai_review_retry_count"] == 0
        assert not [w for w in sections["quality_warnings"] if "[ai-review]" in w]


class TestParallelSectionsPathDeclaresUnreviewed:
    """UDS_PARALLEL_SECTIONS=True 경로는 검증 루프를 타지 않는다 — 그 사실이 드러나야 한다.

    회귀 대상: 이 분기는 reviewer/auditor/semantic/judge를 전혀 거치지 않고 조기 return
    하는데, 순차 경로가 채우는 confidence/semantic_validated/semantic_report/
    ai_review_decision/ai_review_retry_count 를 하나도 안 채웠다. 소비자가 `.get()`으로
    읽으면 None(=falsy)이라 '문제 없음'과 구분되지 않았다.
    """

    @staticmethod
    def _section_json():
        base = {"text": "이 단위는 입력을 검사하고 결과를 반환한다.", "evidence": []}
        return json.dumps({
            "overview": dict(base), "requirements": dict(base),
            "interfaces": dict(base), "uds_frames": dict(base), "notes": dict(base),
            "logic_diagrams": [],
        }, ensure_ascii=False)

    def _run(self, *, parallel: bool):
        import config as _config
        payload_json = self._section_json()

        def _fake_call_role(cfg, *, role, stage, messages, **kw):
            if stage == "uds_review":
                return {"ok": True, "output": json.dumps({"decision": "accept", "reason": ""})}
            if stage == "uds_audit":
                return {"ok": True, "output": json.dumps({"decision": "accept", "reason": ""})}
            return {"ok": True, "output": payload_json}

        def _fake_parallel(cfg, user_payload, analysis_payload):
            return json.loads(payload_json)

        with patch("workflow.uds_ai.load_oai_config", return_value={"model": "m"}), \
                patch("workflow.uds_ai._call_role", side_effect=_fake_call_role), \
                patch("workflow.uds_ai._parallel_sections", side_effect=_fake_parallel), \
                patch("workflow.uds_ai._load_prompt", return_value="prompt"), \
                patch.object(_config, "UDS_JUDGE_ENABLED", False), \
                patch.object(_config, "UDS_PARALLEL_SECTIONS", parallel):
            from workflow.uds_ai import generate_uds_ai_sections
            return generate_uds_ai_sections(
                requirements_text="요구사항", source_sections={},
                notes_text="", logic_items=[], detailed=False,
            )

    def test_parallel_path_marks_result_unreviewed(self):
        sections = self._run(parallel=True)
        assert sections is not None
        assert sections["ai_review_decision"] == "not_reviewed"
        assert sections["ai_review_retry_count"] == 0
        assert sections["semantic_validated"] is False
        assert sections["confidence"] == 0.0
        assert isinstance(sections["semantic_report"], dict)
        assert any("[ai-review]" in w and "UDS_PARALLEL_SECTIONS" in w
                   for w in sections["quality_warnings"]), sections["quality_warnings"]

    def test_parallel_and_sequential_return_the_same_keys(self):
        """계약 불일치 자체가 결함이었다 — 두 경로의 키 집합이 같아야 한다."""
        par = self._run(parallel=True)
        seq = self._run(parallel=False)
        assert par is not None and seq is not None
        assert set(par) == set(seq), set(par) ^ set(seq)

    def test_sequential_path_is_still_reviewed(self):
        """대조군: 순차 경로는 not_reviewed가 아니어야 한다(무조건 미검토 표시 방지)."""
        sections = self._run(parallel=False)
        assert sections is not None
        assert sections["ai_review_decision"] == "accept"
        assert not [w for w in sections["quality_warnings"] if "UDS_PARALLEL_SECTIONS" in w]
