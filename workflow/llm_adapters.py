# workflow/llm_adapters.py
"""LLM Adapter pattern - provider-agnostic interface for LLM calls.

Usage:
    adapter = get_adapter(config_dict)
    result = adapter.generate(messages, temperature=0.3, max_tokens=65536)

Supported providers (via LLM_PROVIDER env or api_type in config):
    - google/gemini (default)
    - openai (GPT-4, etc.)
    - anthropic (Claude)
"""

from __future__ import annotations

import os
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LLMAdapter(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model = config.get("model", "")
        self.api_key = config.get("api_key", "")

    @abstractmethod
    def generate(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 65536,
        timeout: float = 300.0,
    ) -> Dict[str, Any]:
        """Generate a response from the LLM.

        Returns dict with at least {"output": str, "usage": dict}.
        """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name."""


class GeminiAdapter(LLMAdapter):
    """Adapter for Google Gemini models (default)."""

    @property
    def provider_name(self) -> str:
        return "gemini"

    def generate(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 65536,
        timeout: float = 300.0,
    ) -> Dict[str, Any]:
        try:
            from google import genai as genai_new
        except ImportError:
            genai_new = None

        api_key = self.api_key or os.environ.get("GOOGLE_API_KEY", "")
        if not api_key:
            raise ValueError("Google API key not configured")

        contents = []
        system_instruction = None
        for msg in messages:
            role = msg.get("role", "user")
            text = msg.get("content", "")
            if role == "system":
                system_instruction = text
            else:
                contents.append({"role": role, "parts": [{"text": text}]})

        if genai_new:
            client = genai_new.Client(api_key=api_key)
            gen_config = {"temperature": temperature, "max_output_tokens": max_tokens}
            kwargs: Dict[str, Any] = {
                "model": self.model,
                "contents": contents,
                "config": gen_config,
            }
            if system_instruction:
                kwargs["config"]["system_instruction"] = system_instruction
            resp = client.models.generate_content(**kwargs)
            text_out = resp.text if hasattr(resp, "text") else str(resp)
            usage = {}
            if hasattr(resp, "usage_metadata"):
                um = resp.usage_metadata
                usage = {
                    "prompt_tokens": getattr(um, "prompt_token_count", 0),
                    "completion_tokens": getattr(um, "candidates_token_count", 0),
                }
            return {"output": text_out, "usage": usage}

        raise ImportError("google-genai SDK not installed")


class OpenAIAdapter(LLMAdapter):
    """Adapter for OpenAI-compatible APIs (GPT-4, etc.)."""

    @property
    def provider_name(self) -> str:
        return "openai"

    def generate(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 65536,
        timeout: float = 300.0,
    ) -> Dict[str, Any]:
        try:
            import openai
        except ImportError:
            raise ImportError("openai package not installed: pip install openai")

        api_key = self.api_key or os.environ.get("OPENAI_API_KEY", "")
        base_url = self.config.get("base_url")
        client_kwargs: Dict[str, Any] = {"api_key": api_key, "timeout": timeout}
        if base_url:
            client_kwargs["base_url"] = base_url

        client = openai.OpenAI(**client_kwargs)
        resp = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text_out = resp.choices[0].message.content if resp.choices else ""
        usage = {}
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
            }
        return {"output": text_out, "usage": usage}


class AnthropicAdapter(LLMAdapter):
    """Adapter for Anthropic Claude models."""

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def generate(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 65536,
        timeout: float = 300.0,
    ) -> Dict[str, Any]:
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package not installed: pip install anthropic")

        api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        client = anthropic.Anthropic(api_key=api_key, timeout=timeout)

        system_text = ""
        chat_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_text = msg.get("content", "")
            else:
                chat_messages.append(msg)

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": chat_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system_text:
            kwargs["system"] = system_text

        resp = client.messages.create(**kwargs)
        text_out = ""
        if resp.content:
            text_out = resp.content[0].text if hasattr(resp.content[0], "text") else str(resp.content[0])
        usage = {
            "prompt_tokens": getattr(resp.usage, "input_tokens", 0),
            "completion_tokens": getattr(resp.usage, "output_tokens", 0),
        }
        return {"output": text_out, "usage": usage}


_ADAPTER_MAP = {
    "google": GeminiAdapter,
    "gemini": GeminiAdapter,
    "openai": OpenAIAdapter,
    "gpt": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "claude": AnthropicAdapter,
}


def get_adapter(config: Dict[str, Any]) -> LLMAdapter:
    """Create an LLM adapter based on config or environment."""
    provider = (
        os.environ.get("LLM_PROVIDER", "")
        or config.get("api_type", "")
        or config.get("provider", "")
    ).lower().strip()

    model = config.get("model", "").lower()
    if not provider:
        if "gemini" in model:
            provider = "google"
        elif "gpt" in model or "o1" in model:
            provider = "openai"
        elif "claude" in model:
            provider = "anthropic"
        else:
            provider = "google"

    adapter_cls = _ADAPTER_MAP.get(provider, GeminiAdapter)
    logger.debug("Using LLM adapter: %s (provider=%s, model=%s)",
                 adapter_cls.__name__, provider, config.get("model"))
    return adapter_cls(config)
