"""입력 예산·절단이 **egress 간 공유**되는지 잠근다 (계획서 §6 후보 13).

배경 — 이 저장소엔 LLM 나가는 길이 셋이다:

  1. `workflow/ai.py::llm_call`            — uds/agent 파이프라인
  2. `workflow/llm_adapters.py::*Adapter`  — 챗(anthropic) · 주기보고서
  3. `workflow/rag/embedder.py`            — 임베딩 (`_clip_input` 로 이미 상한·보고 있음)

절단 구현이 **`llm_call` 안쪽 중첩 함수**라 2번은 구조적으로 같은 절단을 쓸 수 없었다.
설정에 `max_input_tokens` 가 있어도 어댑터 스택은 통째로 무시하고 원문을 그대로 보냈다
→ **같은 챗 질문이 공급자에 따라 한쪽은 잘려서 답이 나오고 한쪽은 상한 초과로 실패**한다.
`TestAnthropicChatPathIsConsistent`(test_llm_provenance_contract.py) 가 **응답** 절단에
대해 막아둔 것과 같은 비대칭이 **입력** 쪽에 남아 있었다.

상한 **값**을 정하는 건 정책이라 여기서 만들지 않는다 — 이 파일이 잠그는 건
(a) 구현이 하나일 것, (b) 예산이 설정되면 어댑터도 지킬 것, (c) 잘랐으면 보고할 것.
"""
import ast
import inspect

import pytest

# ---------------------------------------------------------------------------
# 1) 모듈 레벨 단일 출처 — 구현이 llm_call 안에 갇혀 있으면 안 된다
# ---------------------------------------------------------------------------

class TestTrimmerIsModuleLevel:
    def test_public_trimmer_is_importable(self):
        """어댑터가 import 할 수 있어야 공유가 성립한다."""
        from workflow.ai import (  # noqa: F401
            estimate_tokens,
            resolve_token_margin,
            trim_messages_to_token_budget,
        )

    def test_llm_call_does_not_redefine_the_implementation(self):
        """`llm_call` 안에 구현이 다시 생기면 두 egress 가 조용히 갈라진다."""
        from workflow import ai

        src = inspect.getsource(ai.llm_call)
        for name in ("def _truncate_middle", "def _summarize_text"):
            assert name not in src, (
                f"{name} 이 llm_call 안에 다시 정의됐다 — 어댑터 egress 는 그걸 못 쓴다")

    def test_llm_call_delegates_to_the_shared_trimmer(self):
        """위임을 끊고 자체 구현으로 되돌리면 여기서 걸린다."""
        from workflow import ai

        src = inspect.getsource(ai.llm_call)
        assert "trim_messages_to_token_budget(" in src


# ---------------------------------------------------------------------------
# 2) 트리머 동작 — 잘랐다는 사실이 반환값에 남는가
# ---------------------------------------------------------------------------

class TestTrimReportsWhatItDid:
    def test_under_budget_is_a_noop(self):
        from workflow.ai import trim_messages_to_token_budget

        msgs = [{"role": "user", "content": "짧은 질문"}]
        out, info = trim_messages_to_token_budget(msgs, 10_000)

        assert info == {"applied": False}
        assert out[0]["content"] == "짧은 질문"

    def test_no_budget_is_a_noop(self):
        """예산 미설정(0)은 '무제한'이지 '0토큰'이 아니다."""
        from workflow.ai import trim_messages_to_token_budget

        msgs = [{"role": "user", "content": "x" * 50_000}]
        out, info = trim_messages_to_token_budget(msgs, 0)

        assert info == {"applied": False}
        assert len(out[0]["content"]) == 50_000

    def test_over_budget_records_before_and_after(self):
        """`after` 만 보고하면 '원래 그 크기였다' 와 구분되지 않는다."""
        from workflow.ai import trim_messages_to_token_budget

        # ⚠ `warn_input_tokens` 를 명시한다. 생략하면 `config.LLM_WARN_INPUT_TOKENS` 를
        #    읽는데, 다른 테스트 파일이 `config` 를 MagicMock 으로 갈아끼우면 `int()` 가
        #    **1** 이 되어(MagicMock.__int__) 늘 요약 경로를 탄다 — 단독 통과·합본 실패.
        msgs = [{"role": "user", "content": "x" * 20_000}]
        out, info = trim_messages_to_token_budget(msgs, 2_000, warn_input_tokens=10**9)

        assert info["applied"] is True
        assert info["limit_tokens"] == 2_000
        assert info["before_tokens_est"] > info["after_tokens_est"]
        assert info["truncated_messages"] >= 1
        assert info["gave_up_over_limit"] is False
        assert "[truncated]" in out[0]["content"]

    def test_giving_up_over_limit_is_recorded(self):
        """20회 안에 예산 아래로 못 내리면 **초과분을 그대로 보낸다** — 침묵하면 안 된다."""
        from workflow.ai import trim_messages_to_token_budget

        # keep_head+keep_tail(3200자) 아래로는 더 못 줄어서 예산(10토큰)에 영영 못 닿는다.
        msgs = [{"role": "user", "content": "x" * 20_000}]
        _out, info = trim_messages_to_token_budget(msgs, 10, warn_input_tokens=10**9)

        assert info["applied"] is True
        assert info["gave_up_over_limit"] is True

    def test_system_message_is_never_trimmed(self):
        from workflow.ai import trim_messages_to_token_budget

        system = "S" * 9_000
        msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": "u" * 40_000},
        ]
        out, info = trim_messages_to_token_budget(msgs, 3_000)

        assert info["applied"] is True
        assert out[0]["content"] == system, "system 프롬프트를 자르면 지시가 사라진다"


# ---------------------------------------------------------------------------
# 3) 어댑터 egress — 예산을 지키고, 지킨 사실을 보고하는가
# ---------------------------------------------------------------------------

class TestAdapterHonorsInputBudget:
    def test_absent_budget_is_byte_identical(self):
        """예산 미설정 시 완전 no-op — 기존 동작을 바꾸지 않는다."""
        from workflow.llm_adapters import _trim_outgoing

        msgs = [{"role": "user", "content": "x" * 50_000}]
        out, meta = _trim_outgoing(msgs, {}, "claude-x")

        assert meta == {}
        assert out[0]["content"] == "x" * 50_000

    def test_configured_budget_is_applied_and_reported(self):
        from workflow.llm_adapters import _trim_outgoing

        msgs = [{"role": "user", "content": "x" * 20_000}]
        out, meta = _trim_outgoing(msgs, {"max_input_tokens": 2_000}, "claude-x")

        # 요약·중간절단 어느 경로를 타는지는 `config.LLM_WARN_INPUT_TOKENS` 에 달렸다
        # (다른 테스트가 config 를 stub 하면 갈린다). 경로와 무관하게 **줄었다는 사실**과
        # 흔적이 남는 것만 잠근다.
        assert len(out[0]["content"]) < 20_000
        assert any(mark in out[0]["content"] for mark in ("[truncated]", "[summary]"))
        assert meta["input_trim"]["applied"] is True
        assert any("input_truncated" in w for w in meta["warnings"]), (
            "잘랐는데 경고가 없으면 호출자는 답이 왜 짧은지 알 수 없다")

    def test_garbage_budget_does_not_crash(self):
        from workflow.llm_adapters import _trim_outgoing

        msgs = [{"role": "user", "content": "hi"}]
        for bad in ("몰라", None, [], {}):
            out, meta = _trim_outgoing(msgs, {"max_input_tokens": bad}, "m")
            assert meta == {}
            assert out == msgs

    def test_give_up_is_surfaced_in_the_warning(self):
        """예산을 못 맞춘 채 보냈다는 사실이 경고 문구에 남아야 한다."""
        from workflow.llm_adapters import _trim_outgoing

        msgs = [{"role": "user", "content": "x" * 20_000}]
        _out, meta = _trim_outgoing(msgs, {"max_input_tokens": 10}, "m")

        assert meta["input_trim"]["gave_up_over_limit"] is True
        assert "초과분 그대로 전송" in meta["warnings"][0]


# ---------------------------------------------------------------------------
# 4) 배선 — 규칙만 있고 아무도 안 부르면 결함은 그대로다
#
# ⚠ 이 저장소는 같은 실수를 이미 겪었다: 규칙은 테스트했는데 **호출**을 안 잠가서
#    뮤테이션이 살아남았다(`rejoin_function_maps` 배선). 세 어댑터 전부 확인한다.
# ---------------------------------------------------------------------------

class TestEveryAdapterIsWired:
    @pytest.mark.parametrize("adapter_name", ["GeminiAdapter", "OpenAIAdapter", "AnthropicAdapter"])
    def test_generate_calls_trim_outgoing(self, adapter_name):
        from workflow import llm_adapters as mod

        src = inspect.getsource(getattr(mod, adapter_name).generate)
        tree = ast.parse(inspect.cleandoc(src))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "_trim_outgoing" in called, (
            f"{adapter_name}.generate 가 입력 예산을 적용하지 않는다 "
            "— 그 공급자에서만 예산이 무시된다")

    @pytest.mark.parametrize("adapter_name", ["GeminiAdapter", "OpenAIAdapter", "AnthropicAdapter"])
    def test_trim_meta_reaches_the_caller(self, adapter_name):
        """`_trim` 을 만들고 반환 dict 에 안 넣으면 절단이 다시 침묵한다."""
        from workflow import llm_adapters as mod

        src = inspect.getsource(getattr(mod, adapter_name).generate)
        assert "**_trim" in src, f"{adapter_name} 가 절단 정보를 호출자에게 안 돌려준다"
