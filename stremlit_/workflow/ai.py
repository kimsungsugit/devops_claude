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
import difflib
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
from . import common, static
from .common import read_excerpt, create_backup, standardize_result


# ---------------------------------------------------------------------------
# LLM 설정 로딩
# ---------------------------------------------------------------------------

def load_oai_configs(path: Optional[str]) -> List[Dict[str, Any]]:
    """
    LLM 설정을 파일에서 리스트로 로드
    - 파일이 없거나 파싱 실패 시 빈 리스트 반환
    - JSON 내용이 단일 객체이면, 원소 1개인 리스트로 반환
    """
    if not path:
        path = getattr(config, "DEFAULT_OAI_CONFIG_PATH", None)

    if not path:
        print("[AI ERROR] Config path not set")
        return []

    p = Path(path)
    if not p.exists():
        print(f"[AI ERROR] Config file not found: {p}")
        return []

    try:
        data = json.loads(p.read_text(encoding="utf-8"))

        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]

        if isinstance(data, dict):
            return [data]

        return []
    except Exception as e:
        print(f"[AI ERROR] Failed to load OAI configs: {e}")
        return []


def load_oai_config(path: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    LLM 설정을 파일에서 로드
    - 리스트 형식([{}, {}])이면 첫 원소 사용
    """
    if not path:
        path = getattr(config, "DEFAULT_OAI_CONFIG_PATH", None)

    if not path:
        print("[AI ERROR] Config path not set")
        return None

    p = Path(path)
    if not p.exists():
        print(f"[AI ERROR] Config file not found: {p}")
        return None

    try:
        data = json.loads(p.read_text(encoding="utf-8"))

        # 단일 dict 형태
        if isinstance(data, dict):
            return data

        # 리스트 형태([{}, {}])
        if isinstance(data, list):
            if not data:
                print("[AI ERROR] Config list is empty")
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
                        print(f"[AI INFO] Selected Gemini-only LLM config: model={it.get('model')}, api_type={it.get('api_type','google')}")
                        return it
                # preferred_sub 미매칭이어도 Gemini면 OK
                for it in data:
                    if isinstance(it, dict) and _is_gemini_cfg(it):
                        print(f"[AI INFO] Selected Gemini-only LLM config: model={it.get('model')}, api_type={it.get('api_type','google')}")
                        return it
                print("[AI ERROR] Gemini-only enabled but no Gemini config found in OAI_CONFIG_LIST")
                return None

            # 2) Gemini-only OFF여도 DEFAULT_LLM_MODEL이 gemini면 Gemini 우선
            if "gemini" in preferred:
                for it in data:
                    if isinstance(it, dict) and _is_gemini_cfg(it):
                        print(f"[AI INFO] Selected preferred Gemini LLM config: model={it.get('model')}, api_type={it.get('api_type','google')}")
                        return it

            # 3) 기본: 첫 항목
            return data[0] if isinstance(data[0], dict) else None

        # 알 수 없는 타입
        return None
    except Exception as e:
        print(f"[AI ERROR] Failed to load OAI config: {e}")
        return None


# ---------------------------------------------------------------------------
# 에이전트 로그
# ---------------------------------------------------------------------------

def _agent_log(log_dir: Path, role: str, content: str) -> None:
    tools.ensure_dir(log_dir)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_human = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fname = log_dir / f"agent_{ts}.md"

    # 중요한 에러는 콘솔에도 찍기
    if role in ("error", "retry", "warning"):
        print(f"[{ts_human}] [AI {role.upper()}] {content[:500]}")

    try:
        with fname.open("a", encoding="utf-8") as f:
            f.write(f"\n\n## {role.upper()} @ {ts_human}\n\n")
            f.write(content)
    except Exception as e:
        print(f"[AI LOG FAIL] {e}")


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
            try:
                client = genai_new.Client(api_key=api_key)  # type: ignore[attr-defined]
                gen_cfg: Any = None
                try:
                    from google.genai import types as genai_types  # type: ignore
                    gen_cfg = genai_types.GenerateContentConfig(
                        temperature=temperature,
                        max_output_tokens=int(num_predict),
                    )
                    if system_instruction:
                        gen_cfg.system_instruction = system_instruction  # type: ignore[attr-defined]
                except Exception:  # pragma: no cover
                    gen_cfg = {"temperature": temperature, "max_output_tokens": int(num_predict)}
                    if system_instruction:
                        gen_cfg["system_instruction"] = system_instruction

                resp = client.models.generate_content(  # type: ignore[attr-defined]
                    model=str(model),
                    contents=contents if contents else prompt,
                    config=gen_cfg,
                )
                text = _extract_gemini_text(resp)
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
                return (text or "").strip() or None
            except Exception as e:
                err_msg = f"Gemini(New SDK) Error: {e}"
                if log_dir:
                    _agent_log(log_dir, "error", err_msg)
                if meta_out is not None:
                    meta_out["sdk"] = "google-genai"
                    meta_out["error"] = str(e)
                return None

        # 1-b) Legacy SDK (google-generativeai, deprecated fallback)
        if genai_legacy is not None:
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

                kwargs: Dict[str, Any] = {
                    "generation_config": generation_config,
                    "request_options": {"timeout": 1200},
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
                err_msg = f"Gemini(Legacy SDK) Error: {e}"
                if log_dir:
                    _agent_log(log_dir, "error", err_msg)
                if meta_out is not None:
                    meta_out["sdk"] = "google-generativeai"
                    meta_out["error"] = str(e)
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
            time.sleep(1.0)

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
        "planner": "You are a Planner agent. Produce structured plans and constraints. Be concise.",
        "generator": "You are a Generator agent. Produce concrete outputs that match the requested format.",
        "fixer": "You are a Fixer agent. Propose precise edits or patches to resolve issues.",
        "reviewer": (
            "You are a Reviewer agent. Check outputs for correctness and format compliance. "
            "Return a JSON object: {\"decision\":\"accept|retry|reject\",\"reason\":\"...\"}."
        ),
        "assistant": "You are a helpful assistant. Follow instructions strictly.",
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
        try:
            entries = rag_kb.search(
                rag_query,
                top_k=int(settings.get("rag_top_k") or 3),
                role=role,
                stage=stage,
                tags=[role, stage] if stage else [role],
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
            review_prompt = (
                "Review the output for correctness and format compliance. "
                "Return JSON only: {\"decision\":\"accept|retry|reject\",\"reason\":\"...\"}.\n\n"
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
        feedback_msgs.append(
            {
                "role": "user",
                "content": f"Previous attempt failed ({last_reason}). Revise your answer.",
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

                old_lines = matched_segment.split("\\n") if matched_segment else []

                new_lines = replace_text.split("\\n")

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


def _extract_json_from_reply(reply: str) -> str:
    start = reply.find("{")
    end = reply.rfind("}")
    if start != -1 and end != -1 and end > start:
        return reply[start : end + 1]
    return reply


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
            json.loads(s)
            return True
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

    # 이전 실행에서 남은 auto_generated 테스트가 빌드를 깨는 경우 방지, 기본 정리 수행
    try:
        for p in list(tests_dir.glob("test_*.c")) + list(tests_dir.glob("test_*.cpp")):
            try:
                p.unlink(missing_ok=True)  # type: ignore[arg-type]
            except Exception:
                pass
    except Exception:
        pass

    total = len(targets)
    log_dir = reports / "agent_logs"

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
            "- All keys and string values must use double quotes.\n\n"
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
            plan_agent = agent_call(
                cfg,
                plan_messages,
                log_dir,
                role="planner",
                stage="test_plan",
                task_id=f"plan_{stem}",
                rag_kb=rag_kb,
                rag_query=code_excerpt,
                settings=agent_settings,
            )
            agent_runs.append(plan_agent)
            plan_reply = plan_agent.get("output")
            if not plan_reply:
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
                break

            # Retry with a minimal prompt after parse failures
            plan_messages = [
                {"role": "system", "content": "You are an embedded test planner. Output only JSON."},
                {"role": "user", "content": (
                    f"Return ONLY ONE VALID JSON object with keys: file, language, functions.\n"
                    f"Keep it MINIMAL: up to 3 functions, each with 1 short case.\n"
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
        except Exception as e:
            print(f"[AI WARN] Failed to write plan file {plan_file}: {e}")
            plan_file = None

        # -----------------------------
        # 2) 테스트 코드 생성
        # -----------------------------
        if progress_callback:
            progress_callback(idx, total, f"Generating {lang} test code for {src.name}")

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
                f"Source excerpt:\n```c\n{code_excerpt}\n```"
            )

        code_messages = [
            {"role": "system", "content": "You are an embedded C/C++ unit test generator."},
            {"role": "user", "content": user_prompt},
        ]

        code_agent = agent_call(
            cfg,
            code_messages,
            log_dir,
            role="generator",
            stage="test_code",
            task_id=f"code_{stem}",
            rag_kb=rag_kb,
            rag_query=code_excerpt,
            settings=agent_settings,
        )
        agent_runs.append(code_agent)
        reply = code_agent.get("output")
        if not reply:
            results.append(
                {
                    "file": str(rel),
                    "ok": False,
                    "reason": "no_llm_response",
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
