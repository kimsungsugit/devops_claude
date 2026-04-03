"""Embedding layer for RAG Knowledge Base.

Fallback chain:
1. Google Gemini text-embedding-004 (768dim)
2. External HTTP API (KB_EMBED_URL env)
3. sentence-transformers all-MiniLM-L6-v2 (384dim)
4. Seeded random vectors (64dim) - last resort
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from collections import OrderedDict
from typing import List, Optional

import numpy as np

_logger = logging.getLogger("workflow.rag.embedder")

# ---- 모듈 레벨 캐시 ----
_embed_cache: OrderedDict[str, List[float]] = OrderedDict()
_cache_max: int = 2000

# ---- Lazy-loaded models ----
_gemini_client = None
_st_model = None
_st_model_tried = False


def _get_cache_max() -> int:
    try:
        import config
        return int(getattr(config, "KB_EMBED_CACHE_MAX", 2000))
    except Exception:
        return 2000


def _cache_put(key: str, vec: List[float]) -> None:
    global _cache_max
    _cache_max = _get_cache_max()
    _embed_cache[key] = vec
    while len(_embed_cache) > _cache_max:
        _embed_cache.popitem(last=False)


def _cache_get(key: str) -> Optional[List[float]]:
    if key in _embed_cache:
        vec = _embed_cache.pop(key)
        _embed_cache[key] = vec  # move to end (LRU)
        return vec
    return None


def get_embed_dim() -> int:
    """현재 설정된 embedding 차원 반환."""
    try:
        import config
        return int(getattr(config, "RAG_EMBED_DIM", 768))
    except Exception:
        return 768


def get_embed_model() -> str:
    """현재 설정된 embedding 모델명 반환."""
    try:
        import config
        return str(getattr(config, "RAG_EMBED_MODEL", "text-embedding-004"))
    except Exception:
        return "text-embedding-004"


# ==============================================================
# 1. Gemini Embedding
# ==============================================================

def _init_gemini_client():
    """Gemini 클라이언트 초기화 (lazy)."""
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return None

    try:
        from google import genai  # 신 SDK (google-genai)
        _gemini_client = genai.Client(api_key=api_key)
        _logger.info("Gemini embedding client initialized (new SDK, model: %s)", get_embed_model())
        return _gemini_client
    except ImportError:
        _logger.debug("google-genai not installed, Gemini embedding unavailable")
        return None
    except Exception as e:
        _logger.warning("Failed to init Gemini client: %s", e)
        return None


def _embed_gemini(text: str) -> Optional[List[float]]:
    """Gemini text-embedding-004로 단일 텍스트 임베딩."""
    client = _init_gemini_client()
    if client is None:
        return None

    model = get_embed_model()
    try:
        # 신 SDK: client.models.embed_content()
        response = client.models.embed_content(
            model=model,
            contents=text,
            config={"task_type": "RETRIEVAL_DOCUMENT"},
        )
        emb = getattr(response, "embedding", None)
        if emb is None and hasattr(response, "embeddings") and response.embeddings:
            emb = response.embeddings[0]
        if emb:
            return [float(v) for v in emb]
        return None
    except Exception as e:
        _logger.warning("Gemini embedding failed: %s", e)
        return None


def _embed_gemini_batch(texts: List[str]) -> Optional[List[List[float]]]:
    """Gemini 배치 임베딩."""
    client = _init_gemini_client()
    if client is None:
        return None

    model = get_embed_model()
    try:
        import config
        batch_size = int(getattr(config, "RAG_EMBED_BATCH_SIZE", 100))
    except Exception:
        batch_size = 100

    all_vecs: List[List[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        try:
            # 신 SDK 배치 임베딩
            response = client.models.embed_content(
                model=model,
                contents=batch,
                config={"task_type": "RETRIEVAL_DOCUMENT"},
            )
            embeddings = getattr(response, "embeddings", None)
            if embeddings and len(embeddings) > 0:
                for emb in embeddings:
                    vec = emb if isinstance(emb, list) else list(emb)
                    all_vecs.append([float(v) for v in vec])
            elif hasattr(response, "embedding") and response.embedding:
                all_vecs.append([float(v) for v in response.embedding])
            else:
                return None
        except Exception as e:
            _logger.warning("Gemini batch embedding failed at batch %d: %s", i // batch_size, e)
            return None

        # Rate limit 방어
        if i + batch_size < len(texts):
            time.sleep(0.1)

    return all_vecs if len(all_vecs) == len(texts) else None


# ==============================================================
# 2. External HTTP API (기존 KB_EMBED_URL)
# ==============================================================

def _embed_http(text: str) -> Optional[List[float]]:
    """외부 HTTP API로 임베딩 (기존 호환)."""
    embed_url = os.environ.get("KB_EMBED_URL", "").strip()
    if not embed_url:
        return None

    try:
        import requests  # type: ignore
    except ImportError:
        return None

    for attempt in range(2):
        try:
            resp = requests.post(embed_url, json={"text": text}, timeout=5)
            resp.raise_for_status()
            vec = resp.json().get("vector") or []
            return [float(v) for v in vec] if vec else None
        except Exception as e:
            if attempt == 0:
                _logger.warning("HTTP embedding failed (attempt 1), retrying: %s", e)
                time.sleep(1.5)

    _logger.warning("HTTP embedding failed after retries")
    return None


# ==============================================================
# 3. Local sentence-transformers
# ==============================================================

def _embed_local(text: str) -> Optional[List[float]]:
    """sentence-transformers 로컬 모델."""
    global _st_model, _st_model_tried

    if _st_model_tried and _st_model is None:
        return None

    if _st_model is None:
        _st_model_tried = True
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            _st_model = SentenceTransformer("all-MiniLM-L6-v2")
            _logger.info("Loaded local embedding model: all-MiniLM-L6-v2 (384dim)")
        except ImportError:
            _logger.debug("sentence-transformers not installed")
            return None
        except Exception as e:
            _logger.warning("Failed to load local model: %s", e)
            return None

    try:
        vec = _st_model.encode(text).tolist()
        return [float(v) for v in vec]
    except Exception as e:
        _logger.warning("Local embedding failed: %s", e)
        return None


# ==============================================================
# 4. Seeded random (최후 폴백)
# ==============================================================

def _embed_random(text: str, dim: int = 64) -> List[float]:
    """동일 입력 -> 동일 벡터 (seed 고정)."""
    seed = abs(hash(text)) % (2**32)
    rng = np.random.default_rng(seed)
    return rng.normal(size=dim).astype(float).tolist()


# ==============================================================
# Public API
# ==============================================================

def get_embedding(text: str) -> List[float]:
    """텍스트 임베딩 반환 (폴백 체인 적용).

    Returns:
        float 리스트 (차원은 사용된 모델에 따라 다름)
    """
    text = (text or "").strip()
    if not text:
        return []

    cached = _cache_get(text)
    if cached is not None:
        return cached

    # 1) Gemini
    vec = _embed_gemini(text)
    if vec:
        _cache_put(text, vec)
        return vec

    # 2) External HTTP
    vec = _embed_http(text)
    if vec:
        _cache_put(text, vec)
        return vec

    # 3) Local model
    vec = _embed_local(text)
    if vec:
        _cache_put(text, vec)
        return vec

    # 4) Random fallback
    vec = _embed_random(text, dim=64)
    _cache_put(text, vec)
    return vec


def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """배치 임베딩 (Gemini 배치 -> 개별 폴백).

    Returns:
        각 텍스트에 대한 embedding 리스트
    """
    if not texts:
        return []

    # 캐시에서 먼저 찾기
    results: List[Optional[List[float]]] = [None] * len(texts)
    uncached_indices: List[int] = []
    uncached_texts: List[str] = []

    for i, t in enumerate(texts):
        t = (t or "").strip()
        if not t:
            results[i] = []
            continue
        cached = _cache_get(t)
        if cached is not None:
            results[i] = cached
        else:
            uncached_indices.append(i)
            uncached_texts.append(t)

    if not uncached_texts:
        return [r for r in results if r is not None]

    # Gemini 배치 시도
    batch_vecs = _embed_gemini_batch(uncached_texts)
    if batch_vecs and len(batch_vecs) == len(uncached_texts):
        for idx, text, vec in zip(uncached_indices, uncached_texts, batch_vecs):
            results[idx] = vec
            _cache_put(text, vec)
    else:
        # 배치 실패 -> 개별 폴백
        for i, idx in enumerate(uncached_indices):
            results[idx] = get_embedding(uncached_texts[i])

    return [r if r is not None else [] for r in results]


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """코사인 유사도 계산."""
    a_arr = np.array(a, dtype=float)
    b_arr = np.array(b, dtype=float)
    if a_arr.size == 0 or b_arr.size == 0:
        return 0.0
    # 차원 불일치 시 짧은 쪽 zero-pad
    if a_arr.size != b_arr.size:
        max_dim = max(a_arr.size, b_arr.size)
        a_arr = np.pad(a_arr, (0, max_dim - a_arr.size))
        b_arr = np.pad(b_arr, (0, max_dim - b_arr.size))
    na = np.linalg.norm(a_arr)
    nb = np.linalg.norm(b_arr)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (na * nb))
