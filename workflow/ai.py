# /app/workflow/ai.py
# -*- coding: utf-8 -*-
"""
AI helpers
- LLM config & call wrapper (Google Gemini Support Added)
- SEARCH/REPLACE 패치 적용 (fuzzy 매칭 포함)
- LLM 기반 단위 테스트 자동 생성
  * C 소스(.c) -> C 테스트(.c)
  * C++ 소스(.cpp/.cxx/.cc 등) -> C++ 테스트(.cpp)
  * 마크다운/설명 텍스트/Unity 의존성 방어적으로 제거
  * 추가로 "테스트 계획 JSON(plan)"도 함께 생성
"""

from __future__ import annotations

import json
import os
import re
import time
import traceback
import difflib
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Tuple

# [Google Gemini SDK Import]
try:
    # New SDK (recommended): pip install google-genai
    from google import genai as genai_new  # type: ignore
except Exception:  # pragma: no cover
    genai_new = None  # type: ignore

try:
    # Legacy SDK (deprecated): pip install google-generativeai
    import google.generativeai as genai_legacy  # type: ignore
    from google.generativeai.types import HarmCategory, HarmBlockThreshold  # type: ignore
except Exception:  # pragma: no cover
    genai_legacy = None  # type: ignore
    HarmCategory = None  # type: ignore
    HarmBlockThreshold = None  # type: ignore

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore

import analysis_tools as tools
import config
from utils.log import get_logger
from . import common, static
from .common import read_excerpt, create_backup, standardize_result

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Gemini Context Caching
# ---------------------------------------------------------------------------
_gemini_cached_content: Dict[str, Any] = {}
_oai_config_cache_lock = threading.Lock()
_oai_config_cache: Dict[str, Tuple[int, Optional[Dict[str, Any]]]] = {}

def create_gemini_cached_context(
    cfg: Dict[str, Any],
    context_text: str,
    cache_key: str = "default",
    *,
    ttl_minutes: int = 30,
) -> Optional[str]:
    """Pre-cache large context (source code, SDS text) for Gemini batched calls.
    Returns a cached_content name/id if successful, None otherwise.
    """
    if not context_text or len(context_text) < 1000:
        return None
    model = str(cfg.get("model") or "").strip()
    if "gemini" not in model.lower():
        return None

    existing = _gemini_cached_content.get(cache_key)
    if existing and existing.get("text_hash") == hash(context_text):
        return existing.get("name")

    api_key = str(cfg.get("api_key") or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return None

    if genai_new is not None:
        try:
            client = genai_new.Client(api_key=api_key)
            from google.genai import types as genai_types
            cached = client.caches.create(
                model=model,
                config=genai_types.CreateCachedContentConfig(
                    contents=[genai_types.Content(parts=[genai_types.Part(text=context_text[:100000])],
                              role="user")],
                    display_name=f"uds_ctx_{cache_key}",
                    ttl=f"{ttl_minutes * 60}s",
                ),
            )
            name = getattr(cached, "name", None)
            if name:
                _gemini_cached_content[cache_key] = {
                    "name": name,
                    "text_hash": hash(context_text),
                    "model": model,
                }
                logger.info("Gemini context cached: key=%s name=%s len=%d", cache_key, name, len(context_text))
                return name
        except Exception as e:
            logger.warning("Gemini context caching failed: %s", e)
    return None


def get_gemini_cached_content_name(cache_key: str = "default") -> Optional[str]:
    entry = _gemini_cached_content.get(cache_key)
    return entry.get("name") if entry else None


# ---------------------------------------------------------------------------
# LLM 설정 로딩
# ---------------------------------------------------------------------------

def _env_provider_candidates() -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    openai_api_key = str(os.environ.get("OPENAI_API_KEY") or "").strip()
    openai_base_url = str(
        os.environ.get("OPENAI_API_BASE")
        or os.environ.get("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    ).strip()
    if openai_api_key:
        candidates.append(
            {
                "model": str(os.environ.get("OPENAI_MODEL") or os.environ.get("LLM_OPENAI_MODEL") or "gpt-4.1-mini"),
                "api_key": openai_api_key,
                "base_url": openai_base_url,
                "api_type": "openai",
                "retries": 2,
            }
        )

    ollama_base_url = str(os.environ.get("OLLAMA_BASE_URL") or "").strip()
    if ollama_base_url:
        candidates.append(
            {
                "model": str(os.environ.get("OLLAMA_MODEL") or os.environ.get("LLM_OLLAMA_MODEL") or "llama3.1:8b"),
                "api_key": "",
                "base_url": ollama_base_url,
                "api_type": "openai_compat",
                "retries": 1,
            }
        )

    litellm_base_url = str(os.environ.get("LITELLM_BASE_URL") or "").strip()
    if litellm_base_url:
        candidates.append(
            {
                "model": str(os.environ.get("LITELLM_MODEL") or os.environ.get("LLM_LITELLM_MODEL") or "gpt-4.1-mini"),
                "api_key": str(os.environ.get("LITELLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip(),
                "base_url": litellm_base_url,
                "api_type": "openai_compat",
                "retries": 2,
            }
        )

    return candidates


def _merge_env_provider_candidates(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = [dict(item) for item in items if isinstance(item, dict)]
    seen = {
        (
            str(item.get("model") or ""),
            str(item.get("api_type") or ""),
            str(item.get("base_url") or ""),
        )
        for item in merged
    }
    for item in _env_provider_candidates():
        key = (
            str(item.get("model") or ""),
            str(item.get("api_type") or ""),
            str(item.get("base_url") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def load_oai_configs(path: Optional[str]) -> List[Dict[str, Any]]:
    """
    LLM 설정을 파일에서 리스트로 로드
    - 파일이 없거나 파싱 실패 시 빈 리스트 반환
    - JSON 내용이 단일 객체이면, 원소 1개인 리스트로 반환
    """
    if not path:
        path = getattr(config, "DEFAULT_OAI_CONFIG_PATH", None)

    if not path:
        logger.error("Config path not set")
        return _merge_env_provider_candidates([])

    p = Path(path)
    if not p.exists():
        logger.error("Config file not found: %s", p)
        return _merge_env_provider_candidates([])

    try:
        data = json.loads(p.read_text(encoding="utf-8"))

        if isinstance(data, list):
            items = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict):
            items = [data]
        else:
            return []

        resolve = getattr(config, "resolve_oai_api_keys", None)
        if resolve:
            items = resolve(items)
        return _merge_env_provider_candidates(items)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load OAI configs: %s", e)
        return []


def load_oai_config(path: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    LLM 설정을 파일에서 로드
    - 리스트 형식([{}, {}])이면 첫 원소 사용
    """
    if not path:
        path = getattr(config, "DEFAULT_OAI_CONFIG_PATH", None)

    if not path:
        logger.error("Config path not set")
        env_items = _merge_env_provider_candidates([])
        return dict(env_items[0]) if env_items else None

    p = Path(path)
    if not p.exists():
        logger.error("Config file not found: %s", p)
        env_items = _merge_env_provider_candidates([])
        return dict(env_items[0]) if env_items else None
    try:
        cache_mtime_ns = int(p.stat().st_mtime_ns)
    except OSError:
        cache_mtime_ns = -1
    cache_key = str(p.resolve())
    with _oai_config_cache_lock:
        cached = _oai_config_cache.get(cache_key)
        if cached and cached[0] == cache_mtime_ns:
            cached_cfg = cached[1]
            return dict(cached_cfg) if isinstance(cached_cfg, dict) else None

    try:
        data = json.loads(p.read_text(encoding="utf-8"))

        # 단일 dict 형태
        if isinstance(data, dict):
            with _oai_config_cache_lock:
                _oai_config_cache[cache_key] = (cache_mtime_ns, dict(data))
            return data

        # 리스트 형태([{}, {}])
        if isinstance(data, list):
            if not data:
                logger.error("Config list is empty")
                return None

            # --- Gemini-only 강제(요청: gemini3만 사용) ---
            # 우선순위: ENV(LLM_GEMINI_ONLY) > config.LLM_GEMINI_ONLY
            gemini_only = os.environ.get("LLM_GEMINI_ONLY")
            if gemini_only is None:
                gemini_only = "1" if getattr(config, "LLM_GEMINI_ONLY", False) else "0"
            gemini_only_on = str(gemini_only).strip() in ("1", "true", "True", "yes", "YES")

            # 선호 모델 힌트(기본: config.DEFAULT_LLM_MODEL)
            preferred = str(getattr(config, "DEFAULT_LLM_MODEL", "") or "").lower()
            preferred_sub = str(getattr(config, "LLM_GEMINI_PREFERRED_SUBSTRING", "gemini-3") or "gemini-3").lower()

            def _is_gemini_cfg(item: Any) -> bool:
                try:
                    m = str(item.get("model") or "").lower()
                    api_type = str(item.get("api_type") or "").lower()
                    return ("gemini" in m) or (api_type == "google")
                except Exception:
                    return False

            # 1) Gemini-only ON이면 Gemini config만 선택
            if gemini_only_on:
                for it in data:
                    if isinstance(it, dict) and _is_gemini_cfg(it) and (preferred_sub in str(it.get("model") or "").lower() or preferred_sub == ""):
                        logger.info("Selected Gemini-only LLM config: model=%s, api_type=%s", it.get('model'), it.get('api_type', 'google'))
                        with _oai_config_cache_lock:
                            _oai_config_cache[cache_key] = (cache_mtime_ns, dict(it))
                        return it
                for it in data:
                    if isinstance(it, dict) and _is_gemini_cfg(it):
                        logger.info("Selected Gemini-only LLM config: model=%s, api_type=%s", it.get('model'), it.get('api_type', 'google'))
                        with _oai_config_cache_lock:
                            _oai_config_cache[cache_key] = (cache_mtime_ns, dict(it))
                        return it
                logger.error("Gemini-only enabled but no Gemini config found in OAI_CONFIG_LIST")
                return None

            # 2) Gemini-only OFF여도 DEFAULT_LLM_MODEL이 gemini면 Gemini 우선
            if "gemini" in preferred:
                for it in data:
                    if isinstance(it, dict) and _is_gemini_cfg(it):
                        logger.info("Selected preferred Gemini LLM config: model=%s, api_type=%s", it.get('model'), it.get('api_type', 'google'))
                        with _oai_config_cache_lock:
                            _oai_config_cache[cache_key] = (cache_mtime_ns, dict(it))
                        return it

            # 3) 기본: 첫 항목
            if isinstance(data[0], dict):
                with _oai_config_cache_lock:
                    _oai_config_cache[cache_key] = (cache_mtime_ns, dict(data[0]))
                return data[0]
            return None

        # 알 수 없는 타입
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load OAI config: %s", e)
        return None


# ---------------------------------------------------------------------------
# 에이전트 로그
# ---------------------------------------------------------------------------

def _agent_log(log_dir: Path, role: str, content: str) -> None:
    tools.ensure_dir(log_dir)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_human = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fname = log_dir / f"agent_{ts}.md"

    if role in ("error", "retry", "warning"):
        logger.warning("[AI %s] %s", role.upper(), content[:500])

    try:
        with fname.open("a", encoding="utf-8") as f:
            f.write(f"\n\n## {role.upper()} @ {ts_human}\n\n")
            f.write(content)
    except OSError as e:
        logger.error("Failed to write agent log: %s", e)


# ---------------------------------------------------------------------------
# LLM 호출 (Gemini 통합 + 예외 처리 강화)
# ---------------------------------------------------------------------------


def _extract_gemini_text(resp: Any) -> Optional[str]:
    """Gemini SDK 응답 객체에서 텍스트만 안전 추출, repr 전체 덤프 방지용"""
    try:
        t = getattr(resp, "text", None)
        if isinstance(t, str) and t.strip():
            return t.strip()
    except Exception:
        pass

    # candidates -> content -> parts -> text 경로 시도
    try:
        candidates = getattr(resp, "candidates", None)
    except Exception:
        candidates = None

    pieces: List[str] = []
    if candidates:
        try:
            for c in candidates:
                # candidate.text 우선
                try:
                    ct = getattr(c, "text", None)
                    if isinstance(ct, str) and ct.strip():
                        pieces.append(ct.strip())
                        continue
                except Exception:
                    pass

                content = None
                try:
                    content = getattr(c, "content", None)
                except Exception:
                    content = None

                # dict 스타일 방어
                if content is None and isinstance(c, dict):
                    content = c.get("content") or c.get("message")

                # content 자체가 문자열인 경우
                if isinstance(content, str) and content.strip():
                    pieces.append(content.strip())
                    continue

                parts = None
                try:
                    parts = getattr(content, "parts", None) if content is not None else None
                except Exception:
                    parts = None

                if parts is None and isinstance(content, dict):
                    parts = content.get("parts")

                if parts:
                    for p in parts:
                        if isinstance(p, dict):
                            tx = p.get("text")
                        else:
                            tx = getattr(p, "text", None)
                        if isinstance(tx, str) and tx.strip():
                            pieces.append(tx.strip())
        except Exception:
            pieces = pieces  # keep whatever collected

    if pieces:
        return "\n".join(pieces).strip()

    # 마지막 방어, model_dump/dict/to_dict 기반으로 text 키 탐색
    for fn in ("model_dump", "dict", "to_dict"):
        if hasattr(resp, fn):
            try:
                d = getattr(resp, fn)()
                if isinstance(d, dict):
                    # 흔한 경로들
                    for k in ("text", "output_text", "content"):
                        v = d.get(k)
                        if isinstance(v, str) and v.strip():
                            return v.strip()
                    # candidates 재탐색
                    cands = d.get("candidates")
                    if isinstance(cands, list):
                        for c in cands:
                            if isinstance(c, dict):
                                v = c.get("text")
                                if isinstance(v, str) and v.strip():
                                    return v.strip()
            except Exception:
                pass

    return None

def llm_call(
    cfg: Dict[str, Any],
    messages: List[Dict[str, str]],
    log_dir: Optional[Path] = None,
    logs: Optional[Path] = None,
    meta_out: Optional[Dict[str, Any]] = None,
    stage: Optional[str] = None,
) -> Optional[str]:
    """
    OpenAI / Ollama / Google Gemini 호환 LLM 호출 래퍼
    - Gemini: google-genai(신 SDK) 우선, 없으면 google-generativeai(레거시) fallback
    - OpenAI/Ollama: /chat/completions(OpenAI 호환) 호출
    """
    if log_dir is None and logs is not None:
        log_dir = logs

    if not cfg:
        if log_dir:
            _agent_log(log_dir, "error", "Config is empty/None. Check oai_config.json path.")
        if meta_out is not None:
            meta_out["error"] = "empty_config"
        return None

    model = cfg.get("model") or getattr(config, "DEFAULT_LLM_MODEL", "gpt-4.1-mini")
    model_override = (cfg.get("model_override") or os.environ.get("LLM_MODEL_OVERRIDE") or "").strip()
    if model_override:
        model = model_override
    api_key = (
        cfg.get("api_key")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    )

    def _pick_model_policy(model_name: str) -> Dict[str, Any]:
        policies = getattr(config, "LLM_MODEL_POLICIES", {}) or {}
        if not isinstance(policies, dict):
            return {}
        name = str(model_name or "").lower()
        if name in policies and isinstance(policies[name], dict):
            return dict(policies[name])
        for key, val in policies.items():
            if str(key).lower() in name and isinstance(val, dict):
                return dict(val)
        return {}

    policy = _pick_model_policy(model)
    default_tokens = int(getattr(config, "DEFAULT_LLM_NUM_PREDICT", 8192))
    explicit_num = ("num_predict" in cfg) or ("max_tokens" in cfg)
    num_predict = int(cfg.get("num_predict") or cfg.get("max_tokens") or default_tokens)
    if not explicit_num:
        policy_out = int(policy.get("max_output_tokens") or 0)
        if policy_out > 0:
            num_predict = policy_out
    explicit_temperature = "temperature" in cfg
    default_temperature = float(getattr(config, "DEFAULT_LLM_TEMPERATURE", 0.3))
    temperature = float(cfg.get("temperature", default_temperature))
    if not explicit_temperature:
        if "temperature_default" in policy:
            temperature = float(policy.get("temperature_default"))
        elif "gemini" in str(model).lower():
            temperature = float(getattr(config, "DEFAULT_LLM_TEMPERATURE_GEMINI", 1.0))
    if meta_out is not None:
        meta_out["model"] = model
        if model_override:
            meta_out["model_override"] = model_override
        meta_out["temperature"] = temperature
        meta_out["max_tokens"] = num_predict

    token_margin = float(policy.get("token_estimate_margin") or 0.0)
    if token_margin <= 0:
        if "gemini" in str(model).lower():
            token_margin = float(getattr(config, "LLM_TOKEN_ESTIMATE_MARGIN_GEMINI", 1.25))
        else:
            token_margin = float(getattr(config, "LLM_TOKEN_ESTIMATE_MARGIN_DEFAULT", 1.1))

    def _estimate_tokens(text: str) -> int:
        if not text:
            return 0
        try:
            import tiktoken  # type: ignore
            enc = tiktoken.get_encoding("cl100k_base")
            base = int(len(enc.encode(text)))
        except Exception:
            base = max(1, int(len(text) / 4))
        return max(1, int(base * token_margin))

    def _truncate_middle(text: str, keep_head: int, keep_tail: int) -> str:
        if len(text) <= (keep_head + keep_tail + 20):
            return text
        return text[:keep_head] + "\n...[truncated]...\n" + text[-keep_tail:]

    def _summarize_text(text: str, *, keep_head: int = 1200, keep_tail: int = 800) -> str:
        if not text:
            return text
        lines = text.splitlines()
        if len(text) <= (keep_head + keep_tail + 200):
            return text
        keywords = ("error", "fail", "failed", "exception", "traceback", "warning", "assert", "timeout")
        key_lines = [ln for ln in lines if any(k in ln.lower() for k in keywords)]
        key_block = "\n".join(key_lines[:80])
        head = text[:keep_head]
        tail = text[-keep_tail:]
        summary = "\n".join(
            [
                head,
                "\n...[summary]...\n",
                key_block,
                "\n...[tail]...\n",
                tail,
            ]
        )
        return summary

    def _trim_messages_to_token_budget(msgs: List[Dict[str, str]], max_tokens: int) -> List[Dict[str, str]]:
        if max_tokens <= 0:
            return msgs
        msgs = list(msgs or [])

        def _total_tokens() -> int:
            return sum(_estimate_tokens(m.get("content", "")) for m in msgs)

        total = _total_tokens()
        if total <= max_tokens:
            return msgs

        warn_threshold = int(policy.get("warn_input_tokens") or getattr(config, "LLM_WARN_INPUT_TOKENS", 200000))
        if total >= warn_threshold and log_dir:
            _agent_log(
                log_dir,
                "warning",
                f"Input tokens estimate {total} exceeds {warn_threshold}. Applying auto-summarization.",
            )

        if total >= warn_threshold:
            for i, m in enumerate(msgs):
                if m.get("role") == "system":
                    continue
                content = m.get("content", "")
                if len(content) > 4000:
                    msgs[i]["content"] = _summarize_text(content)
            total = _total_tokens()

        for _ in range(20):
            if total <= max_tokens:
                break
            idx = None
            longest = 0
            for i, m in enumerate(msgs):
                if m.get("role") == "system":
                    continue
                ln = len(m.get("content", ""))
                if ln > longest:
                    longest = ln
                    idx = i
            if idx is None:
                break
            content = msgs[idx].get("content", "")
            msgs[idx]["content"] = _truncate_middle(content, keep_head=2000, keep_tail=1200)
            total = _total_tokens()
        return msgs

    env_max = os.environ.get("LLM_MAX_INPUT_TOKENS", "").strip()
    explicit_input = ("max_input_tokens" in cfg) or bool(env_max)
    max_input_tokens = int(
        cfg.get("max_input_tokens")
        or env_max
        or getattr(config, "DEFAULT_LLM_MAX_INPUT_TOKENS", 0)
        or 0
    )
    if not explicit_input:
        policy_in = int(policy.get("max_input_tokens") or 0)
        if policy_in > 0:
            max_input_tokens = policy_in

    stage_caps = (
        cfg.get("max_input_tokens_by_stage")
        or policy.get("max_input_tokens_by_stage")
        or getattr(config, "LLM_MAX_INPUT_TOKENS_BY_STAGE", {})
        or {}
    )
    if stage and isinstance(stage_caps, dict):
        try:
            stage_key = str(stage).strip().lower()
            stage_cap = stage_caps.get(stage_key)
            if stage_cap:
                stage_cap_int = int(stage_cap)
                if stage_cap_int > 0:
                    if max_input_tokens > 0:
                        max_input_tokens = min(max_input_tokens, stage_cap_int)
                    else:
                        max_input_tokens = stage_cap_int
        except Exception:
            pass
    if max_input_tokens > 0:
        messages = _trim_messages_to_token_budget(messages, max_input_tokens)
        if meta_out is not None:
            meta_out["input_tokens_est"] = sum(_estimate_tokens(m.get("content", "")) for m in messages)

    # -----------------------------------------------------------------------
    # 1) Google Gemini
    # -----------------------------------------------------------------------
    if "gemini" in str(model).lower():
        retries = int(cfg.get("retries") or getattr(config, "DEFAULT_LLM_RETRIES", 2))
        gemini_read_timeout = int(
            cfg.get("read_timeout")
            or os.environ.get("LLM_READ_TIMEOUT")
            or getattr(config, "DEFAULT_LLM_READ_TIMEOUT", 60)
            or 60
        )

        def _retry_sleep(attempt: int) -> None:
            import random as _rnd
            time.sleep(min(120.0, (4 ** attempt) + _rnd.random() * 2))

        if meta_out is not None:
            meta_out["provider"] = "gemini"
        if num_predict < 4096 and "max_output_tokens" not in policy:
            if log_dir:
                _agent_log(log_dir, "debug", f"Auto-adjusting num_predict {num_predict} -> 65536 for Gemini")
            num_predict = 65536
            if meta_out is not None:
                meta_out["max_tokens"] = num_predict

        if not api_key or api_key.strip() == "":
            err = "Google API Key missing. Check oai_config.json or GOOGLE_API_KEY env."
            if log_dir:
                _agent_log(log_dir, "error", err)
            if meta_out is not None:
                meta_out["error"] = "missing_api_key"
            return None

        def _build_gemini_contents(msgs: List[Dict[str, str]]) -> List[Any]:
            contents: List[Any] = []
            for m in msgs:
                if "gemini_content" in m:
                    contents.append(m["gemini_content"])
                    continue
                role = (m.get("role") or "user").strip().lower()
                if role == "system":
                    continue
                content = m.get("content") or ""
                parts = [{"text": content}]
                contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
            return contents

        def _extract_system_instruction(msgs: List[Dict[str, str]]) -> Optional[str]:
            sys_lines: List[str] = []
            for m in msgs:
                if (m.get("role") or "").strip().lower() == "system":
                    content = m.get("content") or ""
                    if content:
                        sys_lines.append(content)
            return "\n".join(sys_lines).strip() if sys_lines else None

        system_instruction = _extract_system_instruction(messages)
        contents = _build_gemini_contents(messages)
        prompt_lines: List[str] = []
        for m in messages:
            role = (m.get("role") or "user").strip()
            content = m.get("content") or ""
            if role == "system":
                continue
            tag = "ASSISTANT" if role == "assistant" else "USER"
            prompt_lines.append(f"[{tag}]\n{content}")
        prompt = "\n\n".join(prompt_lines).strip()
        if system_instruction:
            prompt = f"[SYSTEM]\n{system_instruction}\n\n{prompt}"

        # 1-a) New SDK (google-genai)
        if genai_new is not None:
            last_err = ""
            allow_legacy_after_network_denied = str(
                cfg.get("legacy_fallback_on_network_denied")
                or os.environ.get("GEMINI_LEGACY_FALLBACK_ON_NETWORK_DENIED")
                or "0"
            ).strip().lower() in ("1", "true", "yes")
            fallback_model = (
                cfg.get("fallback_model")
                or os.environ.get("LLM_FALLBACK_MODEL")
                or ("gemini-2.5-flash" if "gemini-3" in str(model).lower() else "")
            )

            def _try_gemini(model_name: str, max_tokens: int) -> Tuple[Optional[str], Optional[Any]]:
                client_kwargs: Dict[str, Any] = {"api_key": api_key}
                gen_cfg: Any = None
                try:
                    from google.genai import types as genai_types  # type: ignore
                    client_kwargs["http_options"] = genai_types.HttpOptions(
                        timeout=int(gemini_read_timeout * 1000)
                    )
                    client = genai_new.Client(**client_kwargs)  # type: ignore[attr-defined]
                    gen_cfg = genai_types.GenerateContentConfig(
                        temperature=temperature,
                        max_output_tokens=int(max_tokens),
                        automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    )
                    if system_instruction:
                        gen_cfg.system_instruction = system_instruction  # type: ignore[attr-defined]
                except Exception:  # pragma: no cover
                    client = genai_new.Client(**client_kwargs)  # type: ignore[attr-defined]
                    gen_cfg = {
                        "temperature": temperature,
                        "max_output_tokens": int(max_tokens),
                        "automatic_function_calling": {"disable": True},
                    }
                    if system_instruction:
                        gen_cfg["system_instruction"] = system_instruction

                resp = client.models.generate_content(  # type: ignore[attr-defined]
                    model=str(model_name),
                    contents=contents if contents else prompt,
                    config=gen_cfg,
                )
                text = _extract_gemini_text(resp)
                return (text or "").strip() or None, resp

            for attempt in range(max(1, retries)):
                try:
                    text, resp = _try_gemini(str(model), int(num_predict))
                    if log_dir:
                        _agent_log(log_dir, "assistant", text or "")
                    if meta_out is not None:
                        meta_out["sdk"] = "google-genai"
                        meta_out["ok"] = True
                        try:
                            cand = getattr(resp, "candidates", None)
                            if cand and hasattr(cand[0], "content"):
                                meta_out["gemini_content"] = cand[0].content
                        except Exception:
                            pass
                    return text
                except Exception as e:
                    last_err = str(e)
                    lower_err = last_err.lower()
                    if "winerror 10013" in lower_err or "access is denied" in lower_err or "access denied" in lower_err:
                        if log_dir:
                            _agent_log(log_dir, "error", f"Network access denied (WinError 10013): {last_err}")
                        if meta_out is not None:
                            meta_out["sdk"] = "google-genai"
                            meta_out["error"] = "network_denied"
                            meta_out["new_sdk_error"] = last_err
                        if not allow_legacy_after_network_denied:
                            return None
                        break
                    lower_err = last_err.lower()
                    is_bad_request = ("400" in lower_err) or ("invalid_argument" in lower_err)
                    if is_bad_request and fallback_model:
                        try:
                            reduced_tokens = min(int(num_predict), 8192)
                            text, resp = _try_gemini(str(fallback_model), int(reduced_tokens))
                            if log_dir:
                                _agent_log(log_dir, "assistant", text or "")
                            if meta_out is not None:
                                meta_out["sdk"] = "google-genai"
                                meta_out["ok"] = True
                                meta_out["model_fallback"] = str(fallback_model)
                                try:
                                    cand = getattr(resp, "candidates", None)
                                    if cand and hasattr(cand[0], "content"):
                                        meta_out["gemini_content"] = cand[0].content
                                except Exception:
                                    pass
                            return text
                        except Exception as e2:
                            last_err = str(e2)
                    if log_dir:
                        _agent_log(log_dir, "retry", f"Attempt {attempt+1} failed: {last_err}")
                    _retry_sleep(attempt)
            if log_dir:
                _agent_log(log_dir, "error", f"Gemini(New SDK) failed after retries: {last_err}")
            if meta_out is not None:
                meta_out["sdk"] = "google-genai"
                meta_out["error"] = meta_out.get("error") or last_err

        # 1-b) Legacy SDK (google-generativeai, deprecated fallback)
        if genai_legacy is not None:
            last_err = ""
            for attempt in range(max(1, retries)):
                try:
                    genai_legacy.configure(api_key=api_key)  # type: ignore[union-attr]

                    # legacy는 구조화된 role보다 prompt 문자열 전달이 안전
                    if system_instruction:
                        gemini_model = genai_legacy.GenerativeModel(  # type: ignore[union-attr]
                            model_name=str(model),
                            system_instruction=system_instruction,
                        )
                    else:
                        gemini_model = genai_legacy.GenerativeModel(  # type: ignore[union-attr]
                            model_name=str(model),
                        )

                    safety_settings = None
                    if HarmCategory is not None and HarmBlockThreshold is not None:
                        safety_settings = {
                            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                        }

                    generation_config: Dict[str, Any] = {
                        "max_output_tokens": int(num_predict),
                        "temperature": temperature,
                    }

                    read_timeout = int(os.environ.get("LLM_READ_TIMEOUT", "600"))
                    kwargs: Dict[str, Any] = {
                        "generation_config": generation_config,
                        "request_options": {"timeout": read_timeout},
                    }
                    if safety_settings is not None:
                        kwargs["safety_settings"] = safety_settings

                    response = gemini_model.generate_content(prompt, **kwargs)
                    text = _extract_gemini_text(response)
                    if log_dir:
                        _agent_log(log_dir, "assistant", text or "")
                    if meta_out is not None:
                        meta_out["sdk"] = "google-generativeai"
                        meta_out["ok"] = True
                    return (text or "").strip() or None
                except Exception as e:
                    last_err = str(e)
                    lower_err = last_err.lower()
                    if "winerror 10013" in lower_err or "access is denied" in lower_err or "access denied" in lower_err:
                        if log_dir:
                            _agent_log(log_dir, "error", f"Network access denied (WinError 10013): {last_err}")
                        if meta_out is not None:
                            meta_out["sdk"] = "google-generativeai"
                            meta_out["error"] = "network_denied"
                        return None
                    if log_dir:
                        _agent_log(log_dir, "retry", f"Attempt {attempt+1} failed: {last_err}")
                    _retry_sleep(attempt)
            if log_dir:
                _agent_log(log_dir, "error", f"Gemini(Legacy SDK) failed after retries: {last_err}")
            if meta_out is not None:
                meta_out["sdk"] = "google-generativeai"
                meta_out["error"] = last_err
            return None

        if log_dir:
            _agent_log(log_dir, "error", "Gemini SDK not available. Install google-genai.")
        if meta_out is not None:
            meta_out["error"] = "gemini_sdk_missing"
        return None

    # -----------------------------------------------------------------------
    # 2) OpenAI / Ollama (OpenAI-compatible endpoint)
    # -----------------------------------------------------------------------
    base_url = os.environ.get("OLLAMA_BASE_URL") or cfg.get("base_url") or getattr(
        config, "DEFAULT_OAI_BASE_URL", ""
    )
    retries = int(cfg.get("retries") or getattr(config, "DEFAULT_LLM_RETRIES", 2))
    read_timeout = int(os.environ.get("LLM_READ_TIMEOUT", "600"))

    if not base_url or requests is None:
        if log_dir:
            _agent_log(log_dir, "error", "No base_url or requests lib missing (and not Gemini model)")
        if meta_out is not None:
            meta_out["error"] = "missing_base_url_or_requests"
        return None

    url = base_url.rstrip("/") + "/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": num_predict,
        "temperature": temperature,
        # Ollama 호환 옵션(무시되면 서버가 무시)
        "options": {"num_ctx": int(cfg.get("num_ctx") or 65536)},
    }
    if meta_out is not None:
        meta_out["provider"] = "openai_compat"
        meta_out["base_url"] = base_url

    def _llm_debug_enabled(cfg_dict: Dict[str, Any]) -> bool:
        try:
            if os.environ.get("LLM_DEBUG", "").strip().lower() in ("1", "true", "yes"):
                return True
            if os.environ.get("AI_DEBUG", "").strip().lower() in ("1", "true", "yes"):
                return True
        except Exception:
            pass
        try:
            if cfg_dict.get("llm_debug") or cfg_dict.get("debug"):
                return True
        except Exception:
            pass
        return False

    last_err = ""
    for attempt in range(retries):
        try:
            if _llm_debug_enabled(cfg):
                msg = f"Sending request to {url} (attempt {attempt+1}/{retries})"
                if log_dir:
                    _agent_log(log_dir, "debug", msg)

            resp = requests.post(url, json=payload, timeout=read_timeout)  # type: ignore[arg-type]

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 0) or 0)
                wait = max(retry_after, min(30.0, 2 ** attempt))
                if log_dir:
                    _agent_log(log_dir, "retry", f"Rate limited (429), waiting {wait}s")
                time.sleep(wait)
                continue

            if resp.status_code != 200:
                body = resp.text
                raise ValueError(f"HTTP {resp.status_code}: {body}")

            data = resp.json()
            if "choices" not in data or not data["choices"]:
                raise ValueError(f"Invalid API response: {data}")

            content = data["choices"][0]["message"]["content"]
            if log_dir:
                _agent_log(log_dir, "assistant", content)
            if meta_out is not None:
                meta_out["ok"] = True
            return content
        except Exception as e:
            last_err = str(e)
            if log_dir:
                _agent_log(log_dir, "retry", f"Attempt {attempt+1} failed: {last_err}")
            import random as _rnd
            time.sleep(min(30.0, (2 ** attempt) + _rnd.random()))

    if log_dir:
        _agent_log(log_dir, "error", f"LLM call failed after retries: {last_err}")
    if meta_out is not None:
        meta_out["error"] = last_err or "llm_call_failed"
    return None

# ---------------------------------------------------------------------------
# Agent loop wrapper (roles + review + RAG)
# ---------------------------------------------------------------------------

def _default_agent_settings(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    settings = {
        "roles": list(getattr(config, "AGENT_ROLES_DEFAULT", ["planner", "generator", "fixer", "reviewer"])),
        "max_steps": int(getattr(config, "AGENT_MAX_STEPS_DEFAULT", 3)),
        "review_enabled": bool(getattr(config, "AGENT_REVIEW_ENABLED_DEFAULT", True)),
        "rag_enabled": bool(getattr(config, "AGENT_RAG_ENABLED_DEFAULT", True)),
        "rag_top_k": int(getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3)),
        "run_mode": str(getattr(config, "AGENT_RUN_MODE_DEFAULT", "auto")),
    }
    if isinstance(overrides, dict):
        settings.update({k: v for k, v in overrides.items() if v is not None})
    valid_modes = getattr(config, "AGENT_RUN_MODES", ["auto", "review", "off"])
    if settings["run_mode"] not in valid_modes:
        settings["run_mode"] = str(getattr(config, "AGENT_RUN_MODE_DEFAULT", "auto"))
    try:
        settings["max_steps"] = max(1, int(settings.get("max_steps", 1)))
    except Exception:
        settings["max_steps"] = 1
    try:
        settings["rag_top_k"] = max(1, int(settings.get("rag_top_k", 1)))
    except Exception:
        settings["rag_top_k"] = 1
    if not isinstance(settings.get("roles"), list):
        settings["roles"] = [str(settings.get("roles"))]
    settings["roles"] = [str(r) for r in settings["roles"] if str(r).strip()]
    return settings


def _role_system_prompt(role: str) -> str:
    role = (role or "assistant").strip().lower()
    prompts = {
        "analysis": (
            "You are an Analyst agent. Extract key facts, constraints, and gaps. "
            "Be concise and return structured notes only."
        ),
        "writer": (
            "You are a Writer agent. Produce the final content exactly in the required format. "
            "Do not add extra commentary."
        ),
        "auditor": (
            "You are an Auditor agent. Verify evidence coverage and compliance. "
            "Return JSON only: {\"decision\":\"accept|retry|reject\",\"reason\":\"...\"}."
        ),
        "planner": (
            "You are a Planner agent. Produce a short, structured plan and constraints. "
            "No code. Be concise."
        ),
        "generator": (
            "You are a Generator agent. Produce concrete outputs that match the requested format. "
            "Do not add extra commentary."
        ),
        "fixer": (
            "You are a Fixer agent. Propose precise edits or patches to resolve issues. "
            "Follow the required patch format strictly and output only the patch blocks. "
            "No explanations."
        ),
        "reviewer": (
            "You are a Reviewer agent. Check outputs for correctness and format compliance. "
            "Return a JSON object only: {\"decision\":\"accept|retry|reject\",\"reason\":\"...\"}. "
            "Do not include any other text."
        ),
        "assistant": "You are a helpful assistant. Follow instructions strictly and keep outputs concise.",
    }
    return prompts.get(role, prompts["assistant"])


def _parse_review_decision(text: Optional[str]) -> Tuple[str, str]:
    if not text:
        return "retry", "empty_review"
    t = text.strip()
    try:
        data = json.loads(_extract_json_from_reply(t))
        if isinstance(data, dict):
            decision = str(data.get("decision", "")).lower()
            reason = str(data.get("reason", "")).strip()
            if decision in ("accept", "retry", "reject"):
                return decision, reason or decision
    except Exception:
        pass
    t_low = t.lower()
    for key in ("accept", "retry", "reject"):
        if key in t_low:
            return key, t[:200]
    return "retry", t[:200]


def _format_rag_context(entries: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    lines.append("Knowledge base hints (prior successful fixes):")
    for idx, ent in enumerate(entries, start=1):
        err = str(ent.get("error_clean") or ent.get("error_raw") or "")[:200]
        fix = str(ent.get("fix") or "")[:500]
        role = str(ent.get("role") or "")
        stage = str(ent.get("stage") or "")
        meta = ", ".join([x for x in [role, stage] if x])
        if meta:
            meta = f" ({meta})"
        lines.append(f"- Example {idx}{meta}: {err}")
        if fix:
            lines.append(f"  Fix: {fix}")
    return "\n".join(lines).strip()


def _parse_list_str(val: Any) -> List[str]:
    if val is None:
        return []
    if isinstance(val, (list, tuple, set)):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        parts = re.split(r"[,\n;]+", val)
        return [p.strip() for p in parts if p.strip()]
    return []


def _write_agent_run_log(log_dir: Optional[Path], payload: Dict[str, Any]) -> None:
    if not log_dir:
        return
    try:
        run_dir = log_dir / "agent_runs"
        tools.ensure_dir(run_dir)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        role = str(payload.get("role") or "agent")
        stage = str(payload.get("stage") or "run")
        name = f"{role}_{stage}_{ts}.json"
        (run_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def agent_call(
    cfg: Dict[str, Any],
    messages: List[Dict[str, str]],
    log_dir: Optional[Path] = None,
    *,
    role: str = "assistant",
    stage: Optional[str] = None,
    task_id: Optional[str] = None,
    rag_kb: Any = None,
    rag_query: Optional[str] = None,
    settings: Optional[Dict[str, Any]] = None,
    validator: Optional[Callable[[str], Any]] = None,
    llm_call_fn: Optional[Callable[[List[Dict[str, str]]], Tuple[Optional[str], Optional[Dict[str, Any]]]]] = None,
) -> Dict[str, Any]:
    cfg = cfg or {}
    role = (role or "assistant").strip().lower()
    settings = _default_agent_settings(settings)
    if settings.get("run_mode") == "off":
        return {"ok": False, "role": role, "stage": stage, "reason": "run_mode_off", "output": None}

    task_id = task_id or f"{role}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    base_messages = [{"role": "system", "content": _role_system_prompt(role)}] + list(messages or [])

    def _extract_gemini_content(meta: Optional[Dict[str, Any]]) -> Optional[Any]:
        if not isinstance(meta, dict):
            return None
        if "gemini_content" in meta:
            return meta.get("gemini_content")
        attempts = meta.get("attempts")
        if isinstance(attempts, list) and attempts:
            last = attempts[-1]
            if isinstance(last, dict) and "gemini_content" in last:
                return last.get("gemini_content")
        return None

    def _strip_gemini_content(meta: Optional[Dict[str, Any]]) -> None:
        if not isinstance(meta, dict):
            return
        if "gemini_content" in meta:
            meta["gemini_content"] = True
        attempts = meta.get("attempts")
        if isinstance(attempts, list):
            for a in attempts:
                if isinstance(a, dict) and "gemini_content" in a:
                    a["gemini_content"] = True

    rag_used = False
    if settings.get("rag_enabled") and rag_kb is not None and rag_query:
        rag_categories = []
        try:
            if isinstance(settings.get("rag_categories"), list):
                rag_categories = [str(x) for x in settings.get("rag_categories") if str(x).strip()]
            elif settings.get("rag_category"):
                rag_categories = [str(settings.get("rag_category"))]
        except Exception:
            rag_categories = []
        try:
            if stage:
                cat_map = getattr(config, "RAG_CATEGORY_BY_STAGE", {})
                if isinstance(cat_map, dict):
                    mapped = cat_map.get(str(stage))
                    if isinstance(mapped, (list, tuple)):
                        rag_categories.extend([str(x) for x in mapped if str(x).strip()])
                    elif mapped:
                        rag_categories.append(str(mapped))
        except Exception:
            pass
        try:
            entries = rag_kb.search(
                rag_query,
                top_k=int(settings.get("rag_top_k") or 3),
                role=role,
                stage=stage,
                tags=[role, stage] if stage else [role],
                categories=rag_categories or None,
            )
        except Exception:
            entries = []
        if entries:
            base_messages.append({"role": "user", "content": _format_rag_context(entries)})
            rag_used = True

    attempts: List[Dict[str, Any]] = []
    feedback_msgs: List[Dict[str, str]] = []
    final_output: Optional[str] = None
    ok = False
    last_reason = ""
    last_gemini_content: Optional[Any] = None

    for attempt in range(1, int(settings.get("max_steps") or 1) + 1):
        llm_meta: Optional[Dict[str, Any]] = None
        call_messages = list(base_messages)
        if last_gemini_content is not None:
            call_messages.append({"role": "assistant", "content": "", "gemini_content": last_gemini_content})
        call_messages.extend(feedback_msgs)
        if llm_call_fn is not None:
            reply, llm_meta = llm_call_fn(call_messages)
        else:
            meta_tmp: Dict[str, Any] = {}
            reply = llm_call(cfg, call_messages, log_dir, stage=stage, meta_out=meta_tmp)
            llm_meta = meta_tmp
        attempt_meta: Dict[str, Any] = {"attempt": attempt, "role": role}
        attempt_meta["output"] = (reply or "")[:2000]
        gemini_content = _extract_gemini_content(llm_meta)
        if gemini_content is not None:
            last_gemini_content = gemini_content
            if log_dir:
                _agent_log(log_dir, "debug", "Gemini content retained for next turn.")
        _strip_gemini_content(llm_meta)
        if llm_meta:
            attempt_meta["llm_meta"] = llm_meta

        valid = bool(reply)
        reason = "" if valid else "no_reply"
        if not valid and isinstance(llm_meta, dict) and llm_meta.get("error"):
            reason = f"llm_error:{llm_meta.get('error')}"
        if valid and validator:
            try:
                vres = validator(reply)
                if isinstance(vres, tuple):
                    valid = bool(vres[0])
                    if len(vres) > 1:
                        reason = str(vres[1])
                else:
                    valid = bool(vres)
            except Exception as e:
                valid = False
                reason = f"validator_error: {e}"

        review = None
        if valid and settings.get("review_enabled") and role != "reviewer":
            expected_format = ""
            if stage in ("test_plan", "plan_repair"):
                expected_format = "Expected format: a single JSON object only (no markdown)."
            elif stage == "test_code":
                expected_format = "Expected format: pure C/C++ code only (single file), no JSON, no markdown."
            review_prompt = (
                "Review the output for correctness and format compliance. "
                "Return JSON only: {\"decision\":\"accept|retry|reject\",\"reason\":\"...\"}.\n"
                f"{expected_format}\n\n"
                f"OUTPUT:\n{reply}"
            )
            review_messages = [
                {"role": "system", "content": _role_system_prompt("reviewer")},
                {"role": "user", "content": review_prompt},
            ]
            review_reply = llm_call(cfg, review_messages, log_dir, stage=stage)
            decision, review_reason = _parse_review_decision(review_reply)
            review = {"decision": decision, "reason": review_reason, "raw": (review_reply or "")[:1000]}
            if decision in ("retry", "reject"):
                valid = False
                reason = f"review_{decision}: {review_reason}"

        attempt_meta["ok"] = valid
        attempt_meta["reason"] = reason
        if review:
            attempt_meta["review"] = review
        attempts.append(attempt_meta)

        if valid:
            final_output = reply
            ok = True
            break

        last_reason = reason or "retry"
        guidance = ""
        lr = (last_reason or "").lower()
        if "too_long" in lr:
            guidance = "Shorten the output and reduce the number of tests."
        elif "missing_main" in lr:
            guidance = "Add a single main() that runs all tests."
        elif "truncated" in lr or "unbalanced" in lr:
            guidance = "Ensure the code is complete and all blocks are closed."
        elif "not_c_family_code" in lr or "empty_body" in lr:
            guidance = "Output only valid C/C++ code."
        feedback_msgs.append(
            {
                "role": "user",
                "content": f"Previous attempt failed ({last_reason}). {guidance} Revise your answer.",
            }
        )

    result = {
        "ok": ok,
        "role": role,
        "stage": stage,
        "task_id": task_id,
        "rag_used": rag_used,
        "attempts": attempts,
        "output": final_output,
        "reason": "" if ok else (last_reason or "failed"),
    }
    _write_agent_run_log(log_dir, result)
    return result


def agent_call_text(
    cfg: Dict[str, Any],
    messages: List[Dict[str, str]],
    log_dir: Optional[Path] = None,
    *,
    role: str = "assistant",
    stage: Optional[str] = None,
    task_id: Optional[str] = None,
    rag_kb: Any = None,
    rag_query: Optional[str] = None,
    settings: Optional[Dict[str, Any]] = None,
    validator: Optional[Callable[[str], Any]] = None,
    llm_call_fn: Optional[Callable[[List[Dict[str, str]]], Tuple[Optional[str], Optional[Dict[str, Any]]]]] = None,
) -> Optional[str]:
    res = agent_call(
        cfg,
        messages,
        log_dir,
        role=role,
        stage=stage,
        task_id=task_id,
        rag_kb=rag_kb,
        rag_query=rag_query,
        settings=settings,
        validator=validator,
        llm_call_fn=llm_call_fn,
    )
    return res.get("output")

# ---------------------------------------------------------------------------
# SEARCH / REPLACE 블록 처리 (기존 동일)
# ---------------------------------------------------------------------------

def _parse_search_replace_blocks(reply: str) -> List[Dict[str, str]]:
    pattern = re.compile(
        r"<<<<SEARCH_BLOCK\[(?P<file>[^\]]+)\]\s*(?P<search>.*?)<<<<REPLACE_BLOCK\[(?P=file)\]\s*(?P<replace>.*?)(?=(<<<<SEARCH_BLOCK|\Z))",
        re.DOTALL,
    )
    blocks: List[Dict[str, str]] = []
    for m in pattern.finditer(reply):
        blocks.append(
            {
                "file": m.group("file").strip(),
                "search": m.group("search"),
                "replace": m.group("replace"),
            }
        )
    return blocks


def _make_unified_diff(path: Path, before: str, after: str) -> str:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=str(path),
            tofile=str(path),
        )
    )


def apply_search_replace(
    root: Path,
    reply: str,
    logs: Optional[Path],
    patch_mode: str = "auto",
    patch_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    raw_mode = (patch_mode or getattr(config, "AGENT_PATCH_MODE_DEFAULT", "auto") or "auto").lower()
    allowed = tuple(getattr(config, "AGENT_PATCH_MODES", ("auto", "review", "off")))
    if raw_mode not in allowed:
        raw_mode = allowed[0] if allowed else "auto"
    patch_mode = raw_mode

    # Auto 모드에서 안전장치: 특정 경로는 패치 금지 (벤더/캐시/리포트 등)
    deny_prefixes = tuple(getattr(config, "AGENT_PATCH_DENY_PREFIXES", (
        "libs/pico-sdk",
        ".devops_pro_cache",
        "reports",
        "build",
        "cmake-build",
        "third_party",
    )))
    max_change_lines = int(getattr(config, "AGENT_PATCH_MAX_CHANGE_LINES", 400))
    max_replace_chars = int(getattr(config, "AGENT_PATCH_MAX_REPLACE_CHARS", 80000))

    def _is_denied(rel_posix: str) -> bool:
        rel_posix = rel_posix.lstrip("./")
        for p in deny_prefixes:
            p2 = p.replace("\\", "/").rstrip("/")
            if rel_posix == p2 or rel_posix.startswith(p2 + "/"):
                return True
        return False


    def _fuzzy_find_block(original: str, search: str) -> Optional[str]:
        orig = original.replace("\r\n", "\n")
        pat = search.replace("\r\n", "\n")

        orig_lines = orig.split("\n")
        pat_lines = pat.split("\n")

        while pat_lines and not pat_lines[0].strip():
            pat_lines.pop(0)
        while pat_lines and not pat_lines[-1].strip():
            pat_lines.pop()
        if not pat_lines:
            return None

        n = len(orig_lines)
        m = len(pat_lines)
        if m == 0 or m > n:
            return None

        matches = []
        for i in range(n - m + 1):
            ok = True
            for j in range(m):
                if orig_lines[i + j].strip() != pat_lines[j].strip():
                    ok = False
                    break
            if ok:
                matches.append((i, "\n".join(orig_lines[i : i + m])))
        if len(matches) == 1:
            return matches[0][1]
        # ambiguous: 여러 위치에서 매칭되는 경우 안전을 위해 실패 처리
        return None

    changes: List[Dict[str, Any]] = []
    blocks = _parse_search_replace_blocks(reply)
    if not blocks:
        return changes

    if patch_dir is None:
        base = logs.parent if logs is not None else root
        patch_dir = base / "agent_patches"
    tools.ensure_dir(patch_dir)
    root_abs = root.resolve()

    for blk in blocks:
        rel_path = blk["file"]
        search_block = blk["search"]
        replace_block = blk["replace"]

        tf = (root / rel_path).resolve()

        # Safety: refuse to patch outside repo or into vendor/cache/build dirs

        root_resolved = root.resolve()

        try:

            _rel = tf.relative_to(root_resolved)

        except Exception:

            log: Dict[str, Any] = {

                "file": str(tf),

                "rel_file": rel_path,

                "status": "skipped",

                "patch_mode": patch_mode,

                "patch_file": None,

                "error_msg": "path_outside_root",

            }

            changes.append(log)

            continue

        

        deny_roots = [

            root_resolved / ".git",

            root_resolved / ".devops_pro_cache",

            root_resolved / "libs" / "pico-sdk",

            root_resolved / "reports" / "build",

            root_resolved / "reports" / "coverage",

        ]

        def _is_under(p: Path, parent: Path) -> bool:

            try:

                p.relative_to(parent)

                return True

            except Exception:

                return False

        

        blocked = any(_is_under(tf, dr) for dr in deny_roots)

        # Allow patching generated tests only under reports/auto_generated/

        allow_autogen = _is_under(tf, root_resolved / "reports" / "auto_generated") and tf.name.startswith("test_")

        if blocked and not allow_autogen:

            log: Dict[str, Any] = {

                "file": str(tf),

                "rel_file": rel_path,

                "status": "skipped",

                "patch_mode": patch_mode,

                "patch_file": None,

                "error_msg": "path_blocked_by_policy",

            }

            changes.append(log)

            continue

        

        # Only patch existing files (avoid creating arbitrary files)

        if not tf.exists():

            log: Dict[str, Any] = {

                "file": str(tf),

                "rel_file": rel_path,

                "status": "skipped",

                "patch_mode": patch_mode,

                "patch_file": None,

                "error_msg": "file_not_found",

            }

            changes.append(log)

            continue
        log: Dict[str, Any] = {
            "file": str(tf),
            "rel_file": rel_path,
            "status": "error",
            "patch_mode": patch_mode,
            "patch_file": None,
            "backup": None,
            "error_msg": "",
            "match_mode": None,
        }

        try:
            if not tf.exists():
                log["status"] = "file_not_found"
                log["error_msg"] = "target file not found"
                changes.append(log)
                continue

            # 안전장치: auto 모드에서는 패치 금지 경로/파일 차단
            try:
                file_rel = tf.relative_to(root_abs)
                rel_posix = file_rel.as_posix()
            except Exception:
                rel_posix = str(rel_path).replace("\\", "/").lstrip("./")
                if patch_mode == "auto":
                    log["status"] = "blocked"
                    log["error_msg"] = f"path_outside_root:{rel_posix}"
                    changes.append(log)
                    continue

            if patch_mode == "auto" and _is_denied(rel_posix):
                log["status"] = "blocked"
                log["error_msg"] = f"denied_path:{rel_posix}"
                changes.append(log)
                continue


            original = tf.read_text(encoding="utf-8").replace("\r\n", "\n")
            search_text = search_block.replace("\r\n", "\n")
            replace_text = replace_block.replace("\r\n", "\n")

            matched_segment: Optional[str] = None
            if search_text and search_text in original:
                matched_segment = search_text
                log["match_mode"] = "exact"
            else:
                fuzzy = _fuzzy_find_block(original, search_text)
                if fuzzy is not None:
                    matched_segment = fuzzy
                    log["match_mode"] = "fuzzy"

            if not matched_segment:
                log["status"] = "no_match"
                log["error_msg"] = "SEARCH_BLOCK not found (exact/fuzzy failed)"
                changes.append(log)
                continue

            # 변경 규모 제한 (auto 모드)

            if patch_mode == "auto":

                if len(replace_text) > max_replace_chars:

                    log["status"] = "blocked"

                    log["error_msg"] = f"replace_too_large:{len(replace_text)}"

                    changes.append(log)

                    continue

                old_lines = matched_segment.split("\n") if matched_segment else []

                new_lines = replace_text.split("\n")

                delta_lines = abs(len(new_lines) - len(old_lines)) + min(len(old_lines), len(new_lines))

                if delta_lines > max_change_lines:

                    log["status"] = "blocked"

                    log["error_msg"] = f"change_too_large:{delta_lines}"

                    changes.append(log)

                    continue


            before_excerpt = read_excerpt(tf)
            new_text = original.replace(matched_segment, replace_text, 1)

            diff_text = _make_unified_diff(tf, original, new_text)
            patch_path: Optional[Path] = None
            if diff_text:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                patch_path = patch_dir / f"{tf.name}.{ts}.patch"
                tmp = patch_path.with_suffix(patch_path.suffix + ".tmp")
                tmp.write_text(diff_text, encoding="utf-8")
                tmp.replace(patch_path)
                log["patch_file"] = str(patch_path)

            if patch_mode == "review":
                log["status"] = "preview"
                log["before_excerpt"] = before_excerpt
                changes.append(log)
                continue

            if patch_mode == "off":
                log["status"] = "skipped"
                log["error_msg"] = "patch_mode_off_noop"
                log["before_excerpt"] = before_excerpt
                changes.append(log)
                continue

            backup_path = create_backup(tf)
            if backup_path is None and patch_mode == "auto":
                log["status"] = "error"
                log["error_msg"] = "backup_failed_cannot_proceed"
                changes.append(log)
                continue
            tf.write_text(new_text, encoding="utf-8")
            after_excerpt = read_excerpt(tf)

            log["status"] = "ok"
            log["backup"] = str(backup_path) if backup_path else None
            log["before_excerpt"] = before_excerpt
            log["after_excerpt"] = after_excerpt
            changes.append(log)
        except Exception as e:
            log["status"] = "error"
            log["error_msg"] = str(e)
            changes.append(log)

    return changes


# ---------------------------------------------------------------------------
# 테스트 계획(JSON) / 코드 추출 유틸
# ---------------------------------------------------------------------------

def _has_test_main(body: str) -> bool:
    """Return True if a generated test contains a main() entry point."""
    t = body or ""
    return bool(re.search(r"\bmain\s*\(", t))

def _extract_test_body(reply: str, is_cpp: bool) -> str:
    """
    LLM 응답에서 C/C++ 코드 본문만 최대한 안전하게 추출하는 함수
    - ```c / ```cpp 코드펜스 우선 추출
    - #include 라인부터 시작하도록 정규화
    - #include 또는 main 같은 명확한 코드 시그널이 없으면 빈 문자열 반환(격리 유도)
    """
    code = reply.strip()

    # 1) fenced code 우선
    m = re.search(r"```(?:c\+\+|cpp|c|cc|cxx)?\s*(.*?)```", code, re.S | re.I)
    if m:
        code = m.group(1)

    code = code.replace("```", "").strip()

    # 2) include 기준으로 잘라내기
    idx = code.find("#include")
    if idx != -1:
        code = code[idx:]
    else:
        # include가 없는 경우라도 main/ASSERT 등 명확한 코드가 있으면 허용
        if not re.search(r"\bint\s+main\b", code) and not re.search(r"\bTEST\b", code) and not re.search(r"\bassert\b", code, re.I):
            return ""

    # 3) Unity 제거
    if is_cpp:
        code = re.sub(r'#include\s+"unity\.h"\s*', '#include <cassert>\n', code)
    else:
        code = re.sub(r'#include\s+"unity\.h"\s*', '#include <assert.h>\n', code)

    return code.strip() + "\n"
def _looks_like_c_family_code(code: str) -> bool:
    """
    C/C++ 코드인지 최소한의 휴리스틱으로 판별
    - SDK 응답 repr, JSON, Markdown 설명문, Python dict dump 등은 강하게 차단
    - #include 또는 main/ASSERT 같은 시그널이 없으면 거부
    """
    t = (code or "").strip()

    bad_markers = [
        "sdk_http_response",
        "HttpResponse(",
        "candidates=[Candidate(",
        "usage_metadata=",
        "model_version=",
        "prompt_feedback=",
        "content=[Content(",
        "parts=[Part(",
        "<dict len=",
        "```json",
        "{'candidates'",
        '"candidates"',
    ]
    if any(b in t for b in bad_markers):
        return False

    has_signal = ("#include" in t) or bool(re.search(r"\bint\s+main\b", t)) or bool(re.search(r"\bassert\b", t, re.I))
    if not has_signal:
        return False

    kw = ["#include", "typedef", "struct", "static", "extern", "uint8_t", "uint16_t", "uint32_t", "size_t", "assert", "main("]
    return any(k in t for k in kw)


def _strip_c_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*?$", "", text, flags=re.M)
    return text


def _param_placeholder(param: str) -> Tuple[Optional[str], Optional[str]]:
    p = (param or "").strip()
    if not p or p == "void":
        return None, None
    if "..." in p:
        return "0", None
    p = p.split("=", 1)[0].strip()
    if "*" in p or "[" in p:
        if re.search(r"\b(uint8_t|char)\b", p):
            return "buf_u8a", "u8"
        if re.search(r"\b(uint16_t)\b", p):
            return "buf_u16a", "u16"
        if re.search(r"\b(uint32_t)\b", p):
            return "buf_u32a", "u32"
        if re.search(r"\b(uint64_t)\b", p):
            return "buf_u64a", "u64"
        if re.search(r"\b(int8_t|int16_t|int32_t|int|long)\b", p):
            return "buf_i32a", "i32"
        return "buf_u8a", "u8"
    if re.search(r"\b(bool)\b", p):
        return "false", None
    if re.search(r"\b(float|double)\b", p):
        return "0.0", None
    return "0", None


def _parse_param_name(raw: str) -> str:
    ids = re.findall(r"[A-Za-z_]\w*", raw or "")
    if not ids:
        return ""
    return ids[-1]


def _alt_buffer(expr: str) -> str:
    return expr.replace("buf_u8a", "buf_u8b").replace("buf_u16a", "buf_u16b").replace("buf_u32a", "buf_u32b").replace("buf_u64a", "buf_u64b").replace("buf_i32a", "buf_i32b")


def _build_call_variants(func_name: str, params: List[str]) -> List[List[str]]:
    variants: List[List[str]] = []
    base_args: List[str] = []
    param_names: List[str] = []
    has_ptr = False
    first_scalar_idx: Optional[int] = None
    pid_idx: Optional[int] = None
    len_idx: Optional[int] = None

    for i, raw in enumerate(params):
        name = _parse_param_name(raw)
        param_names.append(name)
        expr, buf_kind = _param_placeholder(raw)
        if expr is None:
            expr = "0"
        base_args.append(expr)
        if buf_kind:
            has_ptr = True
        if first_scalar_idx is None and buf_kind is None:
            first_scalar_idx = i
        if name and "pid" in name.lower():
            pid_idx = i
        if name and any(k in name.lower() for k in ("len", "size", "count")):
            len_idx = i

    variants.append(list(base_args))

    if has_ptr:
        alt = [_alt_buffer(a) for a in base_args]
        if alt != base_args:
            variants.append(alt)

    if pid_idx is not None:
        for v in ("0x00", "0x01", "0x02", "0xFF"):
            args = list(base_args)
            args[pid_idx] = v
            variants.append(args)

    if len_idx is not None:
        for v in ("1", "4", "8", "16"):
            args = list(base_args)
            args[len_idx] = v
            variants.append(args)

    if first_scalar_idx is not None and pid_idx is None:
        for v in ("0", "1", "2", "3", "4", "7", "8", "9", "10", "11", "12", "13", "14", "15", "255"):
            args = list(base_args)
            args[first_scalar_idx] = v
            variants.append(args)

    uniq: List[List[str]] = []
    seen = set()
    for v in variants:
        key = "|".join(v)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(v)
        if len(uniq) >= 12:
            break
    return uniq


def _is_simple_signature(ret: str, params: str, *, header_found: bool) -> bool:
    if not ret:
        return False
    if "typedef" in ret or "struct" in ret or "enum" in ret:
        return False
    allowed = {
        "void",
        "int",
        "unsigned",
        "signed",
        "short",
        "long",
        "char",
        "float",
        "double",
        "bool",
        "size_t",
        "uint8_t",
        "uint16_t",
        "uint32_t",
        "uint64_t",
        "int8_t",
        "int16_t",
        "int32_t",
        "int64_t",
        "uint",
        "uintptr_t",
        "intptr_t",
        "const",
        "volatile",
        "static",
        "inline",
    }

    def _check_tokens(tokens: List[str]) -> bool:
        for t in tokens:
            if t in allowed:
                continue
            if header_found and t.endswith("_t"):
                continue
            return False
        return True

    ret_tokens = re.findall(r"[A-Za-z_]\w*", ret)
    if not _check_tokens(ret_tokens):
        return False

    if params and params != "void":
        for raw in params.split(","):
            ids = re.findall(r"[A-Za-z_]\w*", raw)
            if not ids:
                continue
            type_ids = ids[:-1] if len(ids) > 1 else ids
            if not _check_tokens(type_ids):
                return False
    return True


def _extract_stub_functions(src_text: str) -> List[Dict[str, str]]:
    funcs: List[Dict[str, str]] = []
    if not src_text:
        return funcs
    text = _strip_c_comments(src_text)
    func_re = re.compile(
        r"^\s*(?P<ret>[\w\s\*\(\),]+?)\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^;{}]*)\)\s*\{",
        re.M,
    )
    skip_names = {
        "main",
        "core1_entry",
        "if",
        "for",
        "while",
        "switch",
        "case",
        "do",
    }
    skip_fragments = ("loop", "isr", "irq", "handler")
    for m in func_re.finditer(text):
        ret = (m.group("ret") or "").strip()
        name = (m.group("name") or "").strip()
        params = (m.group("params") or "").strip()
        if not ret:
            continue
        if not name or name in skip_names:
            continue
        if any(f in name.lower() for f in skip_fragments):
            continue
        if "typedef" in ret:
            continue
        funcs.append({"ret": ret, "name": name, "params": params})
    return funcs


def _build_stub_test_body(project_root: Path, rel_src: str, src_text: str) -> str:
    libs_dir = project_root / "libs"
    lib_sources = []
    if libs_dir.exists():
        lib_sources = sorted([p for p in libs_dir.glob("*.c") if p.is_file()])

    funcs = _extract_stub_functions(src_text)
    func_names = {f.get("name") for f in funcs}
    calls: List[str] = []
    buffers: Dict[str, str] = {}
    header_found = False
    for f in funcs:
        if not _is_simple_signature(f["ret"], f["params"], header_found=header_found):
            continue
        params = [p.strip() for p in f["params"].split(",")] if f["params"] and f["params"] != "void" else []
        for raw in params:
            _, buf = _param_placeholder(raw)
            if buf:
                buffers[buf] = buf
        for args in _build_call_variants(f["name"], params):
            calls.append(f"(void){f['name']}({', '.join(args)});")
            if len(calls) >= 12:
                break
        if len(calls) >= 12:
            break

    include_block = []
    for p in lib_sources:
        rel = p.relative_to(project_root).as_posix()
        include_block.append(f"#include \"{rel}\"")
    includes = "\n".join(include_block) + ("\n" if include_block else "")
    buf_decls = []
    if "u8" in buffers:
        buf_decls.append("uint8_t buf_u8a[16] = {0};")
        buf_decls.append("uint8_t buf_u8b[16] = {0};")
    if "u16" in buffers:
        buf_decls.append("uint16_t buf_u16a[8] = {0};")
        buf_decls.append("uint16_t buf_u16b[8] = {0};")
    if "u32" in buffers:
        buf_decls.append("uint32_t buf_u32a[4] = {0};")
        buf_decls.append("uint32_t buf_u32b[4] = {0};")
    if "u64" in buffers:
        buf_decls.append("uint64_t buf_u64a[2] = {0};")
        buf_decls.append("uint64_t buf_u64b[2] = {0};")
    if "i32" in buffers:
        buf_decls.append("int32_t buf_i32a[4] = {0};")
        buf_decls.append("int32_t buf_i32b[4] = {0};")
    buf_block = "\n    ".join(buf_decls) + ("\n" if buf_decls else "")
    init_lines: List[str] = []
    if "u8" in buffers:
        init_lines.append("for (int i = 0; i < 16; i++) { buf_u8a[i] = (uint8_t)i; buf_u8b[i] = (uint8_t)(0xFF - i); }")
    if "u16" in buffers:
        init_lines.append("for (int i = 0; i < 8; i++) { buf_u16a[i] = (uint16_t)(i * 3); buf_u16b[i] = (uint16_t)(0xFF - i); }")
    if "u32" in buffers:
        init_lines.append("for (int i = 0; i < 4; i++) { buf_u32a[i] = (uint32_t)(i * 7); buf_u32b[i] = (uint32_t)(0xFFFF - i); }")
    if "i32" in buffers:
        init_lines.append("for (int i = 0; i < 4; i++) { buf_i32a[i] = (int32_t)(i - 2); buf_i32b[i] = (int32_t)(2 - i); }")
    buf_init = "\n    ".join(init_lines) + ("\n" if init_lines else "")
    special: List[str] = []
    if "handle_lin1_slave_processing" in func_names:
        special.extend(
            [
                "uart_stub_reset();",
                "init_lin1_slave();",
                "uart_stub_set_readable_after(1);",
                "lin1_gpio_isr(LIN1_UART_RX_PIN, GPIO_IRQ_EDGE_FALL);",
                "uint8_t sbcm0[7] = {0x11,0x22,0x33,0x44,0x55,0x66,0x77};",
                "uint8_t cks0 = calculate_enhanced_lin_checksum(0x00, sbcm0, 7);",
                "uint8_t frame0[10] = {0x55, 0x00, sbcm0[0], sbcm0[1], sbcm0[2], sbcm0[3], sbcm0[4], sbcm0[5], sbcm0[6], cks0};",
                "uart_stub_push_bytes(frame0, 10);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t sbcm1[7] = {0x01,0x00,0x02,0x10,0x20,0x30,0x40};",
                "uint8_t cks1 = calculate_enhanced_lin_checksum(0x01, sbcm1, 7);",
                "uint8_t frame1[10] = {0x55, 0x01, sbcm1[0], sbcm1[1], sbcm1[2], sbcm1[3], sbcm1[4], sbcm1[5], sbcm1[6], cks1};",
                "uart_stub_push_bytes(frame1, 10);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t frame2[2] = {0x55, 0x02};",
                "uart_stub_push_bytes(frame2, 2);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t diag3c[8] = {0x10,0x01,0x02,0x03,0x04,0x05,0x06,0x07};",
                "uint8_t cks3c = calculate_classic_lin_checksum(diag3c, 8);",
                "uint8_t frame3c[11] = {0x55, 0x3C, diag3c[0], diag3c[1], diag3c[2], diag3c[3], diag3c[4], diag3c[5], diag3c[6], diag3c[7], cks3c};",
                "uart_stub_push_bytes(frame3c, 11);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t diag3c_short[4] = {0x10,0x01,0x02,0x03};",
                "uint8_t frame3c_short[6] = {0x55, 0x3C, diag3c_short[0], diag3c_short[1], diag3c_short[2], diag3c_short[3]};",
                "uart_stub_push_bytes(frame3c_short, 6);",
                "handle_lin1_slave_processing();",
                "LinDiagResponseTransaction* dr = get_diag_response_transaction();",
                "diag_response_lock();",
                "for (int i = 0; i < 8; i++) { dr->response_data[i] = (uint8_t)(i + 1); dr->last_valid_response_data[i] = (uint8_t)(0xA0 + i); }",
                "dr->response_ready = true; dr->has_ever_responded = true;",
                "diag_response_unlock();",
                "uint8_t frame3d[2] = {0x55, 0x3D};",
                "uart_stub_set_readable_after(1);",
                "uart_stub_push_bytes(frame3d, 2);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t no_sync[3] = {0x00,0x01,0x02};",
                "uart_stub_push_bytes(no_sync, 3);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t only_sync[1] = {0x55};",
                "uart_stub_push_bytes(only_sync, 1);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t sbc_bad[7] = {0xFF,0xEE,0xDD,0xCC,0xBB,0xAA,0x99};",
                "uint8_t frame_bad[10] = {0x55, 0x00, sbc_bad[0], sbc_bad[1], sbc_bad[2], sbc_bad[3], sbc_bad[4], sbc_bad[5], sbc_bad[6], (uint8_t)0x00};",
                "uart_stub_push_bytes(frame_bad, 10);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t short_data[4] = {0x55, 0x00, 0x01, 0x02};",
                "uart_stub_push_bytes(short_data, 4);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t diag_bad[8] = {0x21,0x22,0x23,0x24,0x25,0x26,0x27,0x28};",
                "uint8_t frame3c_bad[11] = {0x55, 0x3C, diag_bad[0], diag_bad[1], diag_bad[2], diag_bad[3], diag_bad[4], diag_bad[5], diag_bad[6], diag_bad[7], (uint8_t)0x00};",
                "uart_stub_push_bytes(frame3c_bad, 11);",
                "handle_lin1_slave_processing();",
                "LinDiagResponseTransaction* dr2 = get_diag_response_transaction();",
                "diag_response_lock();",
                "dr2->response_ready = false; dr2->has_ever_responded = false;",
                "diag_response_unlock();",
                "uart_stub_set_readable_after(1);",
                "uart_stub_push_bytes(frame3d, 2);",
                "handle_lin1_slave_processing();",
                "diag_response_lock();",
                "for (int i = 0; i < 8; i++) { dr2->last_valid_response_data[i] = (uint8_t)(0xB0 + i); }",
                "dr2->response_ready = false; dr2->has_ever_responded = true;",
                "diag_response_unlock();",
                "uart_stub_set_readable_after(1);",
                "uart_stub_push_bytes(frame3d, 2);",
                "handle_lin1_slave_processing();",
            ]
        )

    if "lin_master_run_init_sequence" in func_names:
        special.extend(
            [
                "uart_stub_reset();",
                "init_lin2_master();",
                "uint8_t resp_init[4] = {0x12,0x34,0x56,0x78};",
                "uint8_t cks_init = calculate_enhanced_lin_checksum(generate_lin_ident(0x02), resp_init, 4);",
                "uint8_t frame_init[5] = {resp_init[0], resp_init[1], resp_init[2], resp_init[3], cks_init};",
                "uart_stub_push_bytes(frame_init, 5);",
                "(void)lin_master_run_init_sequence();",
                "uart_stub_reset();",
                "uint8_t frame_init_bad[5] = {0xAA,0xBB,0xCC,0xDD,0x00};",
                "uart_stub_push_bytes(frame_init_bad, 5);",
                "(void)lin_master_run_init_sequence();",
                "uart_stub_reset();",
                "(void)lin_master_run_init_sequence();",
                "uint8_t ru_buf[3] = {0};",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t ru_src[3] = {0x10,0x20,0x30};",
                "uart_stub_push_bytes(ru_src, 3);",
                "(void)read_uart_bytes(LIN2_UART_ID, ru_buf, 3, 1);",
                "print_byte_array(\"  L2M TEST: \", ru_buf, 3);",
            ]
        )

    if "handle_lin2_master_schedule" in func_names:
        special.extend(
            [
                "uart_stub_reset();",
                "uint8_t resp_req[4] = {0x9A,0xBC,0xDE,0xF0};",
                "uint8_t cks_req = calculate_enhanced_lin_checksum(generate_lin_ident(0x02), resp_req, 4);",
                "uint8_t frame_req[5] = {resp_req[0], resp_req[1], resp_req[2], resp_req[3], cks_req};",
                "uart_stub_push_bytes(frame_req, 5);",
                "handle_lin2_master_schedule();",
                "handle_lin2_master_schedule();",
                "handle_lin2_master_schedule();",
                "uart_stub_reset();",
                "handle_lin2_master_schedule();",
                "handle_lin2_master_schedule();",
                "handle_lin2_master_schedule();",
                "uart_stub_reset();",
                "handle_lin2_master_schedule();",
                "handle_lin2_master_schedule();",
                "uint8_t bad_resp[5] = {0x01,0x02,0x03,0x04,0x00};",
                "uart_stub_push_bytes(bad_resp, 5);",
                "handle_lin2_master_schedule();",
            ]
        )

    if "process_diag_request_and_get_response" in func_names:
        special.extend(
            [
                "uart_stub_reset();",
                "(void)process_diag_request_and_get_response();",
                "uart_stub_reset();",
                "uint8_t diag_req[8] = {0x01,0x10,0x22,0x33,0x44,0x55,0x66,0x77};",
                "(void)diag_enqueue(diag_req);",
                "uint8_t resp3d[8] = {0x10,0x02,0x03,0x04,0x05,0x06,0x07,0x08};",
                "uint8_t cks3d = calculate_classic_lin_checksum(resp3d, 8);",
                "uint8_t frame3d_resp[9] = {resp3d[0],resp3d[1],resp3d[2],resp3d[3],resp3d[4],resp3d[5],resp3d[6],resp3d[7],cks3d};",
                "uart_stub_set_readable_after(5);",
                "uart_stub_push_bytes(frame3d_resp, 9);",
                "(void)process_diag_request_and_get_response();",
                "uart_stub_reset();",
                "uint8_t diag_cf_unexp[8] = {0x01,0x20,0x02,0x03,0x04,0x05,0x06,0x07};",
                "(void)diag_enqueue(diag_cf_unexp);",
                "uint8_t resp_unexp[8] = {0x41,0x42,0x43,0x44,0x45,0x46,0x47,0x48};",
                "uint8_t cks_unexp = calculate_classic_lin_checksum(resp_unexp, 8);",
                "uint8_t frame_unexp[9] = {resp_unexp[0],resp_unexp[1],resp_unexp[2],resp_unexp[3],resp_unexp[4],resp_unexp[5],resp_unexp[6],resp_unexp[7],cks_unexp};",
                "uart_stub_set_readable_after(1);",
                "uart_stub_push_bytes(frame_unexp, 9);",
                "(void)process_diag_request_and_get_response();",
                "uart_stub_reset();",
                "uint8_t diag_sf[8] = {0x01,0x00,0x02,0x03,0x04,0x05,0x06,0x07};",
                "(void)diag_enqueue(diag_sf);",
                "uint8_t resp_sf[8] = {0x20,0x21,0x22,0x23,0x24,0x25,0x26,0x27};",
                "uint8_t cks_sf = calculate_classic_lin_checksum(resp_sf, 8);",
                "uint8_t frame_sf[9] = {resp_sf[0],resp_sf[1],resp_sf[2],resp_sf[3],resp_sf[4],resp_sf[5],resp_sf[6],resp_sf[7],cks_sf};",
                "uart_stub_set_readable_after(1);",
                "uart_stub_push_bytes(frame_sf, 9);",
                "(void)process_diag_request_and_get_response();",
                "uart_stub_reset();",
                "uint8_t diag_ff[8] = {0x01,0x10,0x20,0x30,0x40,0x50,0x60,0x70};",
                "(void)diag_enqueue(diag_ff);",
                "(void)process_diag_request_and_get_response();",
                "uart_stub_reset();",
                "uint8_t diag_ff_small[8] = {0x01,0x10,0x08,0x11,0x22,0x33,0x44,0x55};",
                "(void)diag_enqueue(diag_ff_small);",
                "(void)process_diag_request_and_get_response();",
                "uint8_t diag_cf_last[8] = {0x01,0x20,0xAA,0xBB,0xCC,0xDD,0xEE,0xFF};",
                "(void)diag_enqueue(diag_cf_last);",
                "uint8_t resp_last[8] = {0x50,0x51,0x52,0x53,0x54,0x55,0x56,0x57};",
                "uint8_t cks_last = calculate_classic_lin_checksum(resp_last, 8);",
                "uint8_t frame_last[9] = {resp_last[0],resp_last[1],resp_last[2],resp_last[3],resp_last[4],resp_last[5],resp_last[6],resp_last[7],cks_last};",
                "uart_stub_set_readable_after(1);",
                "uart_stub_push_bytes(frame_last, 9);",
                "(void)process_diag_request_and_get_response();",
                "uart_stub_reset();",
                "uint8_t diag_cf[8] = {0x01,0x20,0x02,0x03,0x04,0x05,0x06,0x07};",
                "(void)diag_enqueue(diag_cf);",
                "uint8_t resp_cf[8] = {0x30,0x31,0x32,0x33,0x34,0x35,0x36,0x37};",
                "uint8_t cks_cf = calculate_classic_lin_checksum(resp_cf, 8);",
                "uint8_t frame_cf[9] = {resp_cf[0],resp_cf[1],resp_cf[2],resp_cf[3],resp_cf[4],resp_cf[5],resp_cf[6],resp_cf[7],cks_cf};",
                "uart_stub_push_bytes(frame_cf, 9);",
                "(void)process_diag_request_and_get_response();",
                "uart_stub_reset();",
                "uint8_t diag_unk[8] = {0x01,0xF0,0x11,0x22,0x33,0x44,0x55,0x66};",
                "(void)diag_enqueue(diag_unk);",
                "uint8_t resp_bad[8] = {0x40,0x41,0x42,0x43,0x44,0x45,0x46,0x47};",
                "uint8_t frame_bad_resp[9] = {resp_bad[0],resp_bad[1],resp_bad[2],resp_bad[3],resp_bad[4],resp_bad[5],resp_bad[6],resp_bad[7],(uint8_t)0x00};",
                "uart_stub_set_readable_after(1);",
                "uart_stub_push_bytes(frame_bad_resp, 9);",
                "(void)process_diag_request_and_get_response();",
            ]
        )

    if "diag_enqueue" in func_names or "diag_dequeue" in func_names:
        special.extend(
            [
                "uint8_t diag_fill[8] = {0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08};",
                "(void)diag_enqueue(diag_fill);",
                "(void)diag_enqueue(diag_fill);",
                "(void)diag_enqueue(diag_fill);",
                "(void)diag_enqueue(diag_fill);",
                "(void)diag_enqueue(diag_fill);",
                "uint8_t diag_out[8] = {0};",
                "(void)diag_dequeue(diag_out);",
                "diag_queue_init();",
                "(void)diag_dequeue(diag_out);",
            ]
        )

    if "gateway_update_from_sbc_v1_1" in func_names or "gateway_get_publish_for_pdsm_v1_5" in func_names:
        special.extend(
            [
                "uint8_t sbc0_data[7] = {0xFF,0xAA,0x55,0x10,0x34,0x01,0xE0};",
                "gateway_update_from_sbc_v1_1(0x00, sbc0_data);",
                "uint8_t sbc1_data[7] = {0x11,0x22,0x33,0x44,0x55,0x66,0x77};",
                "gateway_update_from_sbc_v1_1(0x01, sbc1_data);",
                "uint8_t pdsm_data[4] = {0x80,0xAA,0x5F,0x9C};",
                "gateway_update_from_pdsm_v1_5(0x02, pdsm_data);",
                "gateway_update_from_pdsm_v1_5(0x03, pdsm_data);",
                "uint8_t pdsm_case6[4] = {0x00,0x00,0x60,0x00};",
                "gateway_update_from_pdsm_v1_5(0x02, pdsm_case6);",
                "uint8_t pdsm_case14[4] = {0x00,0x00,0xE0,0x00};",
                "gateway_update_from_pdsm_v1_5(0x02, pdsm_case14);",
                "uint8_t resp_buf[8] = {0};",
                "gateway_get_response_for_sbc_v1_1(0x02, resp_buf);",
                "gateway_get_response_for_sbc_v1_1(0x03, resp_buf);",
                "uint8_t pub_buf[8] = {0};",
                "gateway_get_publish_for_pdsm_v1_5(0x00, pub_buf);",
                "gateway_get_publish_for_pdsm_v1_5(0x01, pub_buf);",
                "gateway_get_publish_for_pdsm_v1_5(0x05, pub_buf);",
            ]
        )

    if "rotary_switch_update" in func_names or "rotary_switch_init" in func_names:
        special.extend(
            [
                "adc_stub_reset();",
                "rotary_switch_init();",
                "uint16_t slope_vals[5] = {3108, 3401, 3639, 3798, 3873};",
                "uint16_t temp_vals[4] = {3108, 3550, 3758, 3873};",
                "for (int i = 0; i < 5; i++) {",
                "  adc_stub_set_value(1, slope_vals[i]);",
                "  adc_stub_set_value(0, temp_vals[i < 4 ? i : 3]);",
                "  for (int j = 0; j < 3; j++) rotary_switch_update();",
                "}",
                "(void)get_adc_channel_from_gpio(25);",
                "(void)get_adc_channel_from_gpio(26);",
                "(void)get_closest_position(3108);",
                "(void)get_closest_position(3940);",
                "(void)get_slope_index_from_position(0);",
                "(void)get_slope_index_from_position(3);",
                "(void)get_slope_index_from_position(6);",
                "(void)get_slope_index_from_position(8);",
                "(void)get_slope_index_from_position(11);",
                "(void)get_temp_index_from_position(0);",
                "(void)get_temp_index_from_position(4);",
                "(void)get_temp_index_from_position(7);",
                "(void)get_temp_index_from_position(11);",
                "(void)read_adc_averaged(0);",
                "(void)read_adc_averaged(1);",
            ]
        )

    call_block = "\n    ".join(special + calls) if (special or calls) else "/* no callable functions found */"
    return (
        "#include <assert.h>\n"
        "#include <stdbool.h>\n"
        "#include <stddef.h>\n"
        "#include <stdint.h>\n"
        "#include \"pico/types.h\"\n"
        "#include \"hardware/uart.h\"\n"
        "#include \"hardware/gpio.h\"\n"
        "#include \"hardware/adc.h\"\n"
        "\n"
        "#define AI_UT_INCLUDE_SOURCES_ALL 1\n"
        f"{includes}"
        "int main(void) {\n"
        f"    {buf_block}"
        f"    {buf_init}"
        "    shared_data_init();\n"
        f"    {call_block}\n"
        "    return 0;\n"
        "}\n"
    )


def _extract_json_from_reply(reply: str) -> str:
    start = reply.find("{")
    end = reply.rfind("}")
    if start != -1 and end != -1 and end > start:
        return reply[start : end + 1]
    return reply


def _plan_has_requirement_id(raw_json: str) -> bool:
    try:
        obj = json.loads(raw_json or "")
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False
    funcs = obj.get("functions") or []
    if not isinstance(funcs, list):
        return False
    field = str(getattr(config, "REQUIRE_REQUIREMENT_ID_FIELD", "requirement_id") or "requirement_id")
    for fn in funcs:
        cases = (fn or {}).get("cases") if isinstance(fn, dict) else None
        if not isinstance(cases, list):
            return False
        for c in cases:
            if not isinstance(c, dict):
                return False
            rid = str(c.get(field) or "").strip()
            if not rid:
                return False
    return True


def _validate_plan_obj(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    if not obj.get("file") or not obj.get("language"):
        return False
    funcs = obj.get("functions")
    if not isinstance(funcs, list) or not funcs:
        return False
    for fn in funcs:
        if not isinstance(fn, dict):
            return False
        if not str(fn.get("name") or "").strip():
            return False
        cases = fn.get("cases")
        if not isinstance(cases, list) or not cases:
            return False
        for c in cases:
            if not isinstance(c, dict):
                return False
            if not str(c.get("id") or "").strip():
                return False
            if not isinstance(c.get("inputs"), dict):
                return False
            if not isinstance(c.get("expected"), dict):
                return False
    return True


def _summarize_plan_for_prompt(plan_obj: Dict[str, Any]) -> str:
    max_funcs = int(getattr(config, "PLAN_MAX_FUNCTIONS", 8))
    max_cases = int(getattr(config, "PLAN_MAX_CASES_PER_FUNC", 6))
    max_total_cases = int(getattr(config, "TEST_PROMPT_MAX_CASES", 12))
    funcs = plan_obj.get("functions") if isinstance(plan_obj, dict) else None
    if not isinstance(funcs, list):
        return ""
    lines: List[str] = []
    total_cases = 0
    for fn in funcs[:max_funcs]:
        if not isinstance(fn, dict):
            continue
        fname = str(fn.get("name") or "").strip() or "(unknown)"
        purpose = str(fn.get("purpose") or "").strip()
        lines.append(f"- {fname}: {purpose}")
        cases = fn.get("cases") if isinstance(fn.get("cases"), list) else []
        for c in cases[:max_cases]:
            if not isinstance(c, dict):
                continue
            if total_cases >= max_total_cases:
                return "\n".join(lines).strip()
            rid = str(c.get("requirement_id") or "").strip()
            desc = str(c.get("description") or "").strip()
            inputs = c.get("inputs") if isinstance(c.get("inputs"), dict) else {}
            expected = c.get("expected") if isinstance(c.get("expected"), dict) else {}
            lines.append(
                f"  * {c.get('id')}: {desc} | req={rid} | inputs={inputs} | expected={expected}"
            )
            total_cases += 1
    return "\n".join(lines).strip()


def _make_skeleton_plan(rel: Any, lang: str, code_excerpt: str) -> str:
    """LLM 실패/JSON 깨짐 시 사용되는 최소 안전 Plan(JSON) 생성"""
    fn_names: List[str] = []
    try:
        sig_re = re.compile(
            r"^\s*(?:static\s+)?(?:inline\s+)?(?:const\s+)?[A-Za-z_][\w\s\*]*\s+([A-Za-z_]\w*)\s*\([^;]*\)\s*\{",
            re.M,
        )
        for m in sig_re.finditer(code_excerpt or ""):
            name = m.group(1)
            if name in {"if", "for", "while", "switch"}:
                continue
            if name not in fn_names:
                fn_names.append(name)
            if len(fn_names) >= 8:
                break
    except Exception:
        fn_names = []

    if not fn_names:
        fn_names = ["(unknown)"]

    plan = {
        "file": str(rel),
        "language": lang,
        "functions": [],
        "meta": {
            "generated_by": "fallback_skeleton",
            "note": "LLM plan JSON parse/repair failed; using minimal placeholder plan",
        },
    }
    for i, name in enumerate(fn_names, start=1):
        plan["functions"].append(
            {
                "name": name,
                "purpose": "Auto-generated placeholder plan",
                "cases": [
                    {
                        "id": f"SMOKE_{i:02d}",
                        "requirement_id": "REQ-UNKNOWN",
                        "description": "Basic smoke test placeholder",
                        "inputs": {},
                        "expected": {"return": "(unspecified)", "side_effects": "(unspecified)"},
                    }
                ],
            }
        )
    return json.dumps(plan, ensure_ascii=False, indent=2)

def _validate_or_repair_plan_json(
    raw_json: str,
    cfg: Dict[str, Any],
    lang: str,
    rel: Any,
    log_dir: Path,
    max_repair_attempts: int = 2,
    agent_settings: Optional[Dict[str, Any]] = None,
    rag_kb: Any = None,
    rag_query: Optional[str] = None,
) -> Tuple[str, bool]:
    """Plan JSON을 최대한 깨지지 않게 보정
    - 1) json.loads
    - 2) 로컬 휴리스틱(괄호/대괄호 균형, trailing comma 제거 등)
    - 3) LLM repair 최대 N회
    - 4) 실패 시: False 반환(호출부에서 fallback skeleton로 대체)
    """
    def _try_load(s: str) -> bool:
        try:
            obj = json.loads(s)
            return _validate_plan_obj(obj)
        except Exception:
            return False

    def _local_repair(s: str) -> str:
        cand = _extract_json_from_reply(s or "")
        cand = cand.replace("\ufeff", "")
        cand = re.sub(r",\s*([}\]])", r"\1", cand)
        open_curly = cand.count("{")
        close_curly = cand.count("}")
        if close_curly < open_curly:
            cand = cand + ("}" * (open_curly - close_curly))
        open_br = cand.count("[")
        close_br = cand.count("]")
        if close_br < open_br:
            cand = cand + ("]" * (open_br - close_br))
        if cand.count('"') % 2 == 1:
            cand = cand + '"'
        return cand

    if _try_load(raw_json):
        return raw_json, True

    _agent_log(
        log_dir,
        "error",
        f"[PLAN JSON] Initial parse failed for {rel}. Attempting self-heal...\n\nRAW:\n{(raw_json or '')[:2000]}",
    )

    local = _local_repair(raw_json)
    if _try_load(local):
        _agent_log(log_dir, "warn", f"[PLAN JSON] Local repair succeeded for {rel}.")
        return local, True

    repair_system = (
        "You fix invalid JSON. Return ONLY a single valid JSON object. "
        "Do NOT add markdown fences, comments, or explanations."
    )
    repair_user_tpl = (
        "Fix the following JSON so that it parses. Preserve the same schema and as much content as possible.\n\n"
        "JSON (may be truncated/invalid):\n{bad}\n"
    )

    last = local
    for attempt in range(max(1, int(max_repair_attempts))):
        repair_user = repair_user_tpl.format(bad=last[:3500])
        messages = [
            {"role": "system", "content": repair_system},
            {"role": "user", "content": repair_user},
        ]
        repair_settings = dict(agent_settings or {})
        repair_settings["max_steps"] = 1
        repair_settings["review_enabled"] = False
        repair_reply = agent_call_text(
            cfg,
            messages,
            log_dir,
            role="fixer",
            stage="plan_repair",
            rag_kb=rag_kb,
            rag_query=rag_query or repair_user,
            settings=repair_settings,
        )
        if not repair_reply:
            _agent_log(log_dir, "error", f"[PLAN JSON] Repair LLM call failed for {rel} (attempt {attempt+1}).")
            continue

        candidate = _local_repair(repair_reply)
        if _try_load(candidate):
            _agent_log(log_dir, "warn", f"[PLAN JSON] Repair succeeded for {rel} (attempt {attempt+1}).")
            return candidate, True

        _agent_log(
            log_dir,
            "error",
            f"[PLAN JSON] Repair parse failed for {rel} (attempt {attempt+1}).\n\nCANDIDATE:\n{candidate[:2000]}",
        )
        last = candidate

    return raw_json, False

    candidate = _extract_json_from_reply(repair_reply)
    try:
        json.loads(candidate)
        _agent_log(
            log_dir,
            "assistant",
            f"[PLAN JSON] Repair succeeded for {rel}.",
        )
        return candidate, True
    except Exception as e2:
        _agent_log(
            log_dir,
            "error",
            f"[PLAN JSON] Repair parse failed for {rel}: {e2}\n\nCANDIDATE:\n{candidate[:2000]}",
        )
        return raw_json, False


# ---------------------------------------------------------------------------
# 유닛 테스트 자동 생성 (계획 + 코드)
# ---------------------------------------------------------------------------

def run_test_gen(
    project_root: Path,
    reports: Path,
    targets: List[Path],
    cfg: Dict[str, Any],
    include_paths: List[str],
    defines: List[str],
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    agent_settings: Optional[Dict[str, Any]] = None,
    rag_kb: Any = None,
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    agent_runs: List[Dict[str, Any]] = []

    settings = _default_agent_settings(agent_settings)
    run_mode = settings.get("run_mode")
    if run_mode == "off":
        return {"results": results, "agent_runs": agent_runs, "enabled": False, "reason": "run_mode_off"}

    tests_dir = reports / "auto_generated"
    if run_mode == "review":
        tests_dir = reports / "agent_review" / "auto_generated"
    tools.ensure_dir(tests_dir)

    if bool(cfg.get("test_gen_stub_only")):
        for src in targets:
            try:
                rel = src.relative_to(project_root)
            except ValueError:
                rel = src.name
            stem = Path(str(rel)).stem
            test_file = tests_dir / f"test_{stem}.c"
            try:
                src_text = src.read_text(encoding="utf-8", errors="ignore")
                test_body = _build_stub_test_body(project_root, str(rel), src_text)
                test_file.write_text(
                    test_body,
                    encoding="utf-8",
                )
                results.append(
                    {
                        "file": str(rel),
                        "ok": True,
                        "reason": "stub_only",
                        "test_file": str(test_file),
                        "plan_ok": False,
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "file": str(rel),
                        "ok": False,
                        "reason": f"stub_write_failed:{e}",
                        "plan_ok": False,
                    }
                )
        return {"results": results, "agent_runs": agent_runs, "enabled": True, "mode": "stub"}

    # 이전 실행에서 남은 auto_generated 테스트가 빌드를 깨는 경우 방지, 기본 정리 수행
    try:
        for p in list(tests_dir.glob("test_*.c")) + list(tests_dir.glob("test_*.cpp")):
            try:
                p.unlink(missing_ok=True)  # type: ignore[arg-type]
            except Exception:
                pass
    except Exception:
        pass

    exclude_raw = cfg.get("test_gen_excludes") or cfg.get("test_gen_exclude_files") or ""
    exclude_list = _parse_list_str(exclude_raw) if isinstance(exclude_raw, str) else list(exclude_raw or [])
    exclude_list = [str(x).strip().lower() for x in exclude_list if str(x).strip()]

    def _is_excluded_target(p: Path) -> bool:
        rel = p.as_posix().lower()
        name = p.name.lower()
        for ex in exclude_list:
            ex_norm = ex.replace("\\", "/")
            if "/" in ex_norm:
                if ex_norm in rel:
                    return True
            elif ex_norm == name:
                return True
        return False

    if exclude_list:
        filtered: List[Path] = []
        for t in targets:
            if _is_excluded_target(t):
                try:
                    rel = t.relative_to(project_root)
                except Exception:
                    rel = t
                _agent_log(log_dir, "warn", f"[TEST GEN] Skipped by exclude: {rel}")
                results.append(
                    {
                        "file": str(rel),
                        "ok": False,
                        "reason": "excluded",
                        "plan_ok": False,
                    }
                )
            else:
                filtered.append(t)
        targets = filtered

    total = len(targets)
    log_dir = reports / "agent_logs"
    timeout_sec = int(cfg.get("test_gen_timeout_sec") or os.environ.get("TEST_GEN_TIMEOUT_SEC", "300"))

    def _call_agent_with_timeout(
        messages: List[Dict[str, str]],
        *,
        role: str,
        stage: str,
        task_id: str,
        rag_query: Optional[str],
        cfg_override: Optional[Dict[str, Any]] = None,
        validator: Optional[Callable[[str], Any]] = None,
    ) -> Tuple[Dict[str, Any], bool]:
        call_cfg = cfg_override or cfg
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            agent_call,
            call_cfg,
            messages,
            log_dir,
            role=role,
            stage=stage,
            task_id=task_id,
            rag_kb=rag_kb,
            rag_query=rag_query,
            settings=agent_settings,
            validator=validator,
        )
        try:
            return future.result(timeout=timeout_sec), False
        except FuturesTimeoutError:
            future.cancel()
            _agent_log(
                log_dir,
                "error",
                f"[{stage}] LLM timeout for {task_id} ({timeout_sec}s). Skipping.",
            )
            return {"ok": False, "output": None, "reason": "timeout"}, True
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    for idx, src in enumerate(targets):
        if progress_callback:
            progress_callback(idx, total, f"Generating tests for {src.name}")

        try:
            rel = src.relative_to(project_root)
        except ValueError:
            rel = src.name

        ext = src.suffix.lower()
        is_cpp = ext in {".cpp", ".cxx", ".cc", ".hpp", ".hh", ".hxx"}
        lang = "C++" if is_cpp else "C"

        code_excerpt = read_excerpt(src, max_lines=200)
        stem = Path(str(rel)).stem

        # -----------------------------
        # 1) 테스트 계획(JSON) 생성
        # -----------------------------
        plan_file: Optional[Path] = tests_dir / f"test_{stem}.plan.json"
        plan_ok = False

        plan_prompt = (
            f"You are an embedded {lang} test planner.\n"
            f"Analyze the following source file ({rel}) and design a set of unit tests.\n"
            f"Return ONLY a single JSON object with this structure:\n\n"
            "{\n"
            '  "file": "relative/path/to/source.c or .cpp",\n'
            f'  "language": "{lang}",\n'
            "  \"functions\": [\n"
            "    {\n"
            '      "name": "function_name",\n'
            '      "purpose": "short description of what this function does",\n'
            "      \"cases\": [\n"
            "        {\n"
            '          "id": "CASE1",\n'
            '          "requirement_id": "REQ-1234 or UDS-0x10-01",\n'
            '          "description": "what scenario is being tested",\n'
            '          "inputs": { "param1": "value or range", "param2": "..." },\n'
            '          "expected": { "return": "value or condition", "side_effects": "description (if any)" }\n'
            "        }\n"
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "STRICT RULES:\n"
            "- Output ONLY ONE JSON object.\n"
            "- No markdown fences, no comments, no explanations.\n"
            "- No trailing commas.\n"
            "- All keys and string values must use double quotes.\n"
            "- Each case MUST include a non-empty requirement_id.\n\n"
            f"Source excerpt:\n```{ 'cpp' if is_cpp else 'c' }\n{code_excerpt}\n```"
        )

        plan_messages = [
            {"role": "system", "content": "You are an embedded C/C++ test planner that outputs STRICT JSON."},
            {"role": "user", "content": plan_prompt},
        ]

        
        plan_reply: Optional[str] = None
        raw_json = ""

        plan_gen_attempts = int(os.environ.get("DEVOPS_PLAN_GEN_RETRY", str(getattr(config, "PLAN_GEN_RETRY", 2))))
        plan_repair_attempts = int(os.environ.get("DEVOPS_PLAN_REPAIR_RETRY", str(getattr(config, "PLAN_REPAIR_RETRY", 2))))

        for attempt in range(max(1, plan_gen_attempts)):
            try:
                plan_agent, _timed_out = _call_agent_with_timeout(
                    plan_messages,
                    role="planner",
                    stage="test_plan",
                    task_id=f"plan_{stem}",
                    rag_query=code_excerpt,
                )
                agent_runs.append(plan_agent)
                plan_reply = plan_agent.get("output")
                if not plan_reply:
                    continue
            except Exception as e:
                _agent_log(
                    log_dir,
                    "error",
                    f"[TEST PLAN] LLM call failed for {rel} (attempt {attempt + 1}): {e}\n{traceback.format_exc()}",
                )
                plan_reply = None
                continue

            raw_json = _extract_json_from_reply(plan_reply)
            raw_json, plan_ok = _validate_or_repair_plan_json(
                raw_json=raw_json,
                cfg=cfg,
                lang=lang,
                rel=rel,
                log_dir=log_dir,
                max_repair_attempts=plan_repair_attempts,
                agent_settings=agent_settings,
                rag_kb=rag_kb,
                rag_query=code_excerpt,
            )
            if plan_ok:
                if getattr(config, "REQUIRE_REQUIREMENT_ID", True):
                    if not _plan_has_requirement_id(raw_json):
                        plan_ok = False
                if plan_ok:
                    break

            # Retry with a minimal prompt after parse failures
            plan_messages = [
                {"role": "system", "content": "You are an embedded test planner. Output only JSON."},
                {"role": "user", "content": (
                    f"Return ONLY ONE VALID JSON object with keys: file, language, functions.\n"
                    f"Keep it MINIMAL: up to 3 functions, each with 1 short case.\n"
                    f"Each case MUST include requirement_id (non-empty).\n"
                    f"No long strings. No markdown.\n\n"
                    f"Target: {rel}\nLanguage: {lang}\n\n"
                    f"Source excerpt:\n{code_excerpt[:2500]}"
                )},
            ]

        if not plan_ok:
            raw_json = _make_skeleton_plan(rel=rel, lang=lang, code_excerpt=code_excerpt)
            plan_ok = True
            _agent_log(log_dir, "warn", f"[PLAN JSON] Fallback skeleton plan used for {rel}.")

        try:
            if plan_file is not None:
                plan_file.write_text(raw_json, encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to write plan file %s: %s", plan_file, e)
            plan_file = None

        plan_hint = ""
        if plan_ok:
            try:
                plan_obj = json.loads(raw_json)
                if _validate_plan_obj(plan_obj):
                    plan_hint = _summarize_plan_for_prompt(plan_obj)
            except Exception:
                plan_hint = ""

        # -----------------------------
        # 2) 테스트 코드 생성
        # -----------------------------
        if progress_callback:
            progress_callback(idx, total, f"Generating {lang} test code for {src.name}")

        max_funcs = int(getattr(config, "PLAN_MAX_FUNCTIONS", 8))
        max_total_cases = int(getattr(config, "TEST_PROMPT_MAX_CASES", 12))
        max_lines = int(getattr(config, "TEST_CODE_MAX_LINES", 300))
        plan_block = f"Test plan summary:\n{plan_hint}\n\n" if plan_hint else ""
        if is_cpp:
            user_prompt = (
                f"You are an embedded {lang} unit test generator.\n"
                f"Generate a single self-contained {lang} test file for the following source file ({rel}).\n"
                "Requirements:\n"
                "- DO NOT use Unity or any external test framework.\n"
                "- Use only the standard library (e.g., <cassert>) and simple helper functions.\n"
                "- Provide a single 'int main()' that runs all tests and returns 0 on success.\n"
                "- Output ONLY pure C++ code. No explanations, no comments, no markdown fences, no backticks.\n"
                "- Focus on edge cases and error handling.\n\n"
                f"- Limit scope: cover at most {max_funcs} functions and {max_total_cases} total test cases.\n"
                f"- Keep the output under ~{max_lines} lines. Prefer concise stubs and helpers.\n"
                "- If external dependencies are referenced, include minimal stub implementations in the same file.\n\n"
                f"{plan_block}"
                f"Source excerpt:\n```cpp\n{code_excerpt}\n```"
            )
        else:
            user_prompt = (
                f"You are an embedded {lang} unit test generator.\n"
                f"Generate a single self-contained {lang} test file for the following source file ({rel}).\n"
                "Requirements:\n"
                "- DO NOT use Unity or any external test framework.\n"
                "- Use only the standard C library (e.g., <assert.h>) and simple helper functions.\n"
                "- Provide a single 'int main(void)' that runs all tests and returns 0 on success.\n"
                "- Output ONLY pure C code. No explanations, no comments, no markdown fences, no backticks.\n"
                "- Focus on edge cases and error handling.\n\n"
                f"- Limit scope: cover at most {max_funcs} functions and {max_total_cases} total test cases.\n"
                f"- Keep the output under ~{max_lines} lines. Prefer concise stubs and helpers.\n"
                "- If external dependencies are referenced, include minimal stub implementations in the same file.\n\n"
                f"{plan_block}"
                f"Source excerpt:\n```c\n{code_excerpt}\n```"
            )

        code_messages = [
            {"role": "system", "content": "You are an embedded C/C++ unit test generator."},
            {"role": "user", "content": user_prompt},
        ]

        cfg_code = dict(cfg or {})
        if "num_predict" not in cfg_code and "max_tokens" not in cfg_code:
            cfg_code["num_predict"] = int(getattr(config, "TEST_CODE_MAX_TOKENS", 16384))
        def _validate_test_code(reply_text: str) -> Tuple[bool, str]:
            body_text = _extract_test_body(reply_text or "", is_cpp=is_cpp)
            if not body_text:
                return False, "empty_body"
            if not _looks_like_c_family_code(body_text):
                return False, "not_c_family_code"
            if not _has_test_main(body_text):
                return False, "missing_main"
            if max_lines and body_text.count("\n") > max_lines:
                return False, "too_long"
            if body_text.count("/*") > body_text.count("*/"):
                return False, "truncated_block_comment"
            if body_text.count("{") < body_text.count("}"):
                return False, "unbalanced_braces"
            return True, ""

        try:
            code_agent, timed_out = _call_agent_with_timeout(
                code_messages,
                role="generator",
                stage="test_code",
                task_id=f"code_{stem}",
                rag_query=code_excerpt,
                cfg_override=cfg_code,
                validator=_validate_test_code,
            )
            agent_runs.append(code_agent)
            reply = code_agent.get("output")
        except Exception as e:
            _agent_log(
                log_dir,
                "error",
                f"[TEST CODE] LLM call failed for {rel}: {e}\n{traceback.format_exc()}",
            )
            results.append(
                {
                    "file": str(rel),
                    "ok": False,
                    "reason": "llm_exception",
                    "plan_file": str(plan_file) if plan_file else None,
                    "plan_ok": plan_ok,
                }
            )
            continue
        if timed_out:
            results.append(
                {
                    "file": str(rel),
                    "ok": False,
                    "reason": "timeout",
                    "plan_file": str(plan_file) if plan_file else None,
                    "plan_ok": plan_ok,
                }
            )
            continue
        if not reply:
            reason = str(code_agent.get("reason") or "")
            if reason.startswith("review_") or reason.startswith("validator_") or reason:
                fail_reason = reason or "invalid_llm_output"
            else:
                fail_reason = "no_llm_response"
            results.append(
                {
                    "file": str(rel),
                    "ok": False,
                    "reason": fail_reason,
                    "plan_file": str(plan_file) if plan_file else None,
                    "plan_ok": plan_ok,
                }
            )
            continue

        body = _extract_test_body(reply, is_cpp=is_cpp)

        test_ext = ".cpp" if is_cpp else ".c"
        test_file = tests_dir / f"test_{stem}{test_ext}"

        if not _has_test_main(body):
            invalid_dir = tests_dir / "_invalid"
            tools.ensure_dir(invalid_dir)
            try:
                (invalid_dir / f"test_{stem}{test_ext}.raw.txt").write_text(reply, encoding="utf-8")
                (invalid_dir / f"test_{stem}{test_ext}").write_text(body, encoding="utf-8")
            except Exception:
                pass
            results.append(
                {
                    "file": str(rel),
                    "ok": False,
                    "reason": "missing_main",
                    "test_file": str(invalid_dir / f"test_{stem}{test_ext}"),
                    "plan_file": str(plan_file) if plan_file else None,
                    "plan_ok": plan_ok,
                }
            )
            continue

        # LLM 응답 오염(예: SDK 객체 repr)이면 파일 생성 자체를 중단, 격리 로그만 남김
        if not _looks_like_c_family_code(body):
            invalid_dir = tests_dir / "_invalid"
            tools.ensure_dir(invalid_dir)
            try:
                (invalid_dir / f"test_{stem}{test_ext}.raw.txt").write_text(reply, encoding="utf-8")
                (invalid_dir / f"test_{stem}{test_ext}.extracted.txt").write_text(body, encoding="utf-8")
            except Exception:
                pass
            results.append(
                {
                    "file": str(rel),
                    "ok": False,
                    "reason": "invalid_llm_output_quarantined",
                    "test_file": str(invalid_dir / f"test_{stem}{test_ext}.extracted.txt"),
                    "plan_file": str(plan_file) if plan_file else None,
                    "plan_ok": plan_ok,
                }
            )
            continue

        try:
            test_file.write_text(body, encoding="utf-8")
        except Exception as e:
            results.append(
                {
                    "file": str(rel),
                    "ok": False,
                    "reason": f"write_error: {e}",
                    "test_file": str(test_file),
                    "plan_file": str(plan_file) if plan_file else None,
                    "plan_ok": plan_ok,
                }
            )
            continue

        compile_ok = True
        compile_res: Dict[str, Any] = {"ok": True}
        try:
            cc = "g++" if is_cpp else "gcc"
            if not tools.which(cc):
                compile_ok = False
                compile_res = {"ok": False, "reason": "compiler_not_found"}
            else:
                inc_args = [f"-I{ip}" for ip in (include_paths or []) if ip]
                def_args = [
                    d if d.startswith("-D") else f"-D{d}"
                    for d in (["UNIT_TEST", "HOST_BUILD"] + list(defines or []))
                    if str(d).strip()
                ]
                tmp_dir = tests_dir / "_tmp"
                tools.ensure_dir(tmp_dir)
                obj_path = tmp_dir / f"{test_file.stem}.o"
                cmd = [cc, "-c"] + def_args + inc_args + [str(test_file.relative_to(project_root)), "-o", str(obj_path)]
                c, o, e = tools.run_command(cmd, cwd=project_root, timeout=120)
                compile_ok = c == 0
                compile_res = {
                    "ok": compile_ok,
                    "exit_code": c,
                    "stdout": (o or "").strip()[:4000],
                    "stderr": (e or "").strip()[:4000],
                    "cmd": " ".join(cmd),
                }
                try:
                    if obj_path.exists():
                        obj_path.unlink()
                except Exception:
                    pass
        except Exception as e:
            compile_ok = False
            compile_res = {"ok": False, "reason": f"compile_exception: {e}"}

        if not compile_ok:
            invalid_dir = tests_dir / "_invalid"
            tools.ensure_dir(invalid_dir)
            try:
                (invalid_dir / f"{test_file.name}.compile.stdout.log").write_text(
                    compile_res.get("stdout", ""), encoding="utf-8"
                )
                (invalid_dir / f"{test_file.name}.compile.stderr.log").write_text(
                    compile_res.get("stderr", ""), encoding="utf-8"
                )
                (invalid_dir / f"{test_file.name}.compile.cmd.txt").write_text(
                    compile_res.get("cmd", ""), encoding="utf-8"
                )
            except Exception:
                pass
            try:
                bad_path = invalid_dir / (test_file.name + ".bad")
                test_file.replace(bad_path)
                test_file = bad_path
            except Exception:
                try:
                    test_file.unlink(missing_ok=True)  # type: ignore[arg-type]
                except Exception:
                    pass
            results.append(
                {
                    "file": str(rel),
                    "ok": False,
                    "reason": "compile_failed",
                    "compile": compile_res,
                    "test_file": str(test_file),
                    "plan_file": str(plan_file) if plan_file else None,
                    "plan_ok": plan_ok,
                }
            )
            continue

        try:
            syntax_res = static.run_gcc_syntax(
                project_root,
                reports,
                [test_file],
                include_paths,
                defines,
                progress_callback,
                "native",
            )
        except Exception as e:
            results.append(
                {
                    "file": str(rel),
                    "ok": False,
                    "reason": f"syntax_exception: {e}",
                    "test_file": str(test_file),
                    "plan_file": str(plan_file) if plan_file else None,
                    "plan_ok": plan_ok,
                }
            )
            continue


        syntax_ok = bool(syntax_res.get("ok"))
        if not syntax_ok:
            # 컴파일 불가 테스트는 빌드 실패 유발, 자동 생성 폴더 밖으로 격리
            invalid_dir = tests_dir / "_invalid"
            tools.ensure_dir(invalid_dir)
            try:
                raw_path = invalid_dir / (test_file.name + ".raw.txt")
                raw_path.write_text(reply, encoding="utf-8")
            except Exception:
                pass
            try:
                bad_path = invalid_dir / (test_file.name + ".bad")
                test_file.replace(bad_path)
                test_file = bad_path
            except Exception:
                # 이동 실패 시 삭제 시도
                try:
                    test_file.unlink(missing_ok=True)  # type: ignore[arg-type]
                except Exception:
                    pass

        results.append(
            {
                "file": str(rel),
                "ok": syntax_ok,
                "reason": "generated" if syntax_ok else "syntax_failed",
                "compile": compile_res,
                "syntax": syntax_res,
                "test_file": str(test_file),
                "plan_file": str(plan_file) if plan_file else None,
                "plan_ok": plan_ok,
            }
        )

    return {
        "results": results,
        "agent_runs": agent_runs,
        "enabled": True,
        "mode": run_mode,
        "tests_dir": str(tests_dir),
    }
