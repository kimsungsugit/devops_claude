"""챗 LLM 경로의 Anthropic(Claude) 어댑터 라우팅 회귀 (D4).

ai.llm_call(agent_call) 은 gemini/openai_compat 만 분기 → Claude 미지원이었다.
_run_llm_candidates 가 anthropic 후보를 llm_adapters.AnthropicAdapter 경유로 호출하고,
실패 시 다음 후보(gemini/openai)로 폴백하는지 검증.
"""
from __future__ import annotations

import backend.services.assistant_service as svc
import workflow.llm_adapters as la


class _FakeAdapter:
    def __init__(self, cfg, output="클로드 답변"):
        self.cfg = cfg
        self._output = output
        self.calls = []

    def generate(self, messages, **kw):
        self.calls.append((messages, kw))
        return {"output": self._output, "usage": {}}


# ---------------- 감지 ----------------

def test_is_anthropic_cfg_detection():
    assert svc._is_anthropic_cfg({"api_type": "anthropic", "model": "x"}) is True
    assert svc._is_anthropic_cfg({"api_type": "claude"}) is True
    assert svc._is_anthropic_cfg({"provider": "anthropic"}) is True
    assert svc._is_anthropic_cfg({"model": "claude-opus-4"}) is True  # api_type 없으면 모델명으로
    assert svc._is_anthropic_cfg({"api_type": "google", "model": "gemini-2.5"}) is False
    assert svc._is_anthropic_cfg({"api_type": "openai", "model": "gpt-4"}) is False
    # api_type 이 명시되면 claude 모델명이어도 그 api_type 을 따른다(오탐 방지)
    assert svc._is_anthropic_cfg({"api_type": "openai", "model": "claude-proxy"}) is False
    assert svc._is_anthropic_cfg({}) is False


# ---------------- _call_anthropic ----------------

def test_call_anthropic_routes_through_adapter(monkeypatch):
    fake = _FakeAdapter(None, output="  클로드 답변  ")
    monkeypatch.setattr(la, "AnthropicAdapter", lambda cfg: fake)
    out, err = svc._call_anthropic(
        {"api_type": "anthropic", "model": "claude-opus-4", "temperature": 0.5, "max_tokens": 2048},
        [{"role": "user", "content": "hi"}],
    )
    assert out == "클로드 답변"  # strip 적용
    assert err == ""
    # cfg 의 temperature/max_tokens 가 generate 로 전달됐는지
    assert fake.calls and fake.calls[0][1]["temperature"] == 0.5
    assert fake.calls[0][1]["max_tokens"] == 2048


def test_call_anthropic_auth_error_normalized(monkeypatch):
    def _boom(cfg):
        raise Exception("authentication_error: invalid x-api-key")
    monkeypatch.setattr(la, "AnthropicAdapter", _boom)
    out, err = svc._call_anthropic({"api_type": "anthropic"}, [{"role": "user", "content": "hi"}])
    assert out == ""
    assert err == "missing_api_key"


def test_call_anthropic_generic_error_normalized(monkeypatch):
    class _BoomAdapter:
        def generate(self, *a, **k):
            raise RuntimeError("model overloaded")
    monkeypatch.setattr(la, "AnthropicAdapter", lambda cfg: _BoomAdapter())
    out, err = svc._call_anthropic({"api_type": "anthropic"}, [{"role": "user", "content": "hi"}])
    assert out == ""
    assert err == "anthropic_error"


# ---------------- _run_llm_candidates 통합 ----------------

def test_run_uses_adapter_for_anthropic_not_agent_call(monkeypatch):
    fake = _FakeAdapter(None, output="클로드")
    monkeypatch.setattr(la, "AnthropicAdapter", lambda cfg: fake)
    called = {"agent_call": 0}

    def _agent(*a, **k):
        called["agent_call"] += 1
        return {"output": "GEMINI", "attempts": []}
    monkeypatch.setattr(svc, "agent_call", _agent)

    ans, sel, lerr, _ms = svc._run_llm_candidates(
        cfg={"api_type": "anthropic", "model": "claude-opus-4"},
        cfg_candidates=[],
        messages=[{"role": "user", "content": "hi"}],
    )
    assert ans == "클로드"
    assert called["agent_call"] == 0  # anthropic 은 agent_call 미경유
    assert lerr == ""


def test_run_falls_back_to_gemini_on_anthropic_failure(monkeypatch):
    def _boom(cfg):
        raise Exception("authentication error: invalid x-api-key")
    monkeypatch.setattr(la, "AnthropicAdapter", _boom)
    monkeypatch.setattr(
        svc, "agent_call",
        lambda *a, **k: {"output": "GEMINI", "attempts": []},
    )
    ans, sel, lerr, _ms = svc._run_llm_candidates(
        cfg={"api_type": "anthropic", "model": "claude-opus-4"},
        cfg_candidates=[{"api_type": "google", "model": "gemini-2.5"}],
        messages=[{"role": "user", "content": "hi"}],
    )
    assert ans == "GEMINI"
    assert sel.get("api_type") == "google"  # gemini 후보로 폴백


def test_run_gemini_only_unaffected(monkeypatch):
    """비-anthropic 후보는 기존 agent_call 경로 그대로(회귀 가드)."""
    monkeypatch.setattr(la, "AnthropicAdapter", lambda cfg: (_ for _ in ()).throw(AssertionError("must not call adapter")))
    monkeypatch.setattr(
        svc, "agent_call",
        lambda *a, **k: {"output": "GEMINI", "attempts": [{"llm_meta": {"error": ""}}]},
    )
    ans, sel, lerr, _ms = svc._run_llm_candidates(
        cfg={"api_type": "google", "model": "gemini-2.5"},
        cfg_candidates=[],
        messages=[{"role": "user", "content": "hi"}],
    )
    assert ans == "GEMINI"
    assert lerr == ""


def test_anthropic_ignores_llm_provider_env(monkeypatch):
    """전역 LLM_PROVIDER 오설정이 anthropic 라우팅을 뒤집지 않는다(footgun 차단).

    get_adapter 는 LLM_PROVIDER env 를 api_type 보다 우선하지만, _call_anthropic 은
    AnthropicAdapter 를 직접 생성하므로 env 와 무관하게 Claude 어댑터를 쓴다.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openai")  # 전역 오설정
    fake = _FakeAdapter(None, output="클로드")
    monkeypatch.setattr(la, "AnthropicAdapter", lambda cfg: fake)
    out, err = svc._call_anthropic(
        {"api_type": "anthropic", "model": "claude-opus-4"},
        [{"role": "user", "content": "hi"}],
    )
    assert out == "클로드"
    assert err == ""
