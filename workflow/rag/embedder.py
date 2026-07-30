"""Embedding layer for RAG Knowledge Base.

Fallback chain:
1. Google Gemini text-embedding-004 (768dim)
2. External HTTP API (KB_EMBED_URL env)
3. sentence-transformers all-MiniLM-L6-v2 (384dim)
4. Seeded random vectors (64dim) - last resort

⚠ **4번은 의미 신호가 0인 벡터다.** 이걸로 만든 유사도 랭킹은 랭킹이 아니라 난수 정렬이다.
반환 타입이 `List[float]` 하나뿐이라 소비처가 1~3번과 4번을 **구분할 방법이 없었고**, 실측
결과 저장소의 실 KB 엔트리 102건이 **전부 64차원 무작위 벡터**였다(Gemini 키 부재). 그 상태로
`semantic_search` 는 102건 중 52건을 "관련 근거"로 통과시켰다 — 경고 0건.

그래서 출처를 관측 가능하게 만들었다: `get_embedding(text, meta_out={})` 가
`embed_source`/`embed_model`/`embed_dim`/`degraded` 를 기록한다(additive kwarg — 기존
소비처 9곳 무영향). `degraded=True` 면 소비처는 **랭킹에 쓰지 말아야** 한다
(`workflow/rag/searcher.py::semantic_search` 가 그렇게 한다).
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

_logger = logging.getLogger("workflow.rag.embedder")

# 의미 신호가 없는 출처 — 이 벡터로 만든 랭킹은 랭킹이 아니다(판정 단일 출처).
_DEGRADED_SOURCES = frozenset({"random"})

# 재시도: 실패하면 체인이 무작위 벡터로 내려가고 `learn()` 은 그걸 **영구 저장**한다.
# 즉 일시적 429/503 하나가 KB 엔트리를 영구 오염시킨다(`_embed_http` 는 원래 2회였다).
_EMBED_ATTEMPTS = 3
_EMBED_RETRY_SLEEP = 1.0


def _get_max_input_chars() -> int:
    """임베딩 입력 상한(문자). text-embedding-004 는 2048 토큰이 상한이다.

    상한을 넘기면 API 가 거부하고, 체인은 그걸 **무작위 벡터**로 갈음한다 — 즉 "너무 길다"가
    "의미 없는 벡터"로 조용히 바뀐다. 예전엔 길이 가드가 **전무**했다(패턴 검색 0건).
    실측: 저장소 실 KB 의 임베딩 입력은 최대 4,000자였으나 `add_document` 는 임의 길이를
    받는다.
    """
    try:
        import config
        return int(getattr(config, "RAG_EMBED_MAX_INPUT_CHARS", 6000))
    except Exception:  # silent-ok: config 부재/파싱 실패 시 문서화된 기본값으로 진행.
        # 이 모듈의 다른 config 리더(`get_embed_dim`·`_get_cache_max`)와 같은 규약이며,
        # 상한을 못 읽는 것 자체가 판정을 바꾸지 않는다(절단이 발생하면 별도로 경고한다).
        return 6000


def _clip_input(text: str, *, reasons: Optional[List[str]] = None) -> str:
    """상한 초과 시 **자르고 보고**한다. 침묵 절단이 아니라 기록되는 절단이다."""
    limit = _get_max_input_chars()
    if limit <= 0 or len(text) <= limit:
        return text
    _logger.warning(
        "임베딩 입력이 상한을 넘어 잘랐다: %d자 → %d자. 뒷부분은 벡터에 반영되지 않는다 "
        "(자르지 않으면 API 가 거부하고 무작위 벡터로 떨어진다).",
        len(text), limit,
    )
    if reasons is not None:
        reasons.append(f"input_truncated: {len(text)}자 → {limit}자")
    return text[:limit]

# ---- 모듈 레벨 캐시 ----
_embed_cache: OrderedDict[str, List[float]] = OrderedDict()
_cache_max: int = 2000
_cache_lock = threading.Lock()   # C3 — get/put 의 in→pop TOCTOU(동시 eviction 시 KeyError) 차단

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


def _cache_key(text: str) -> str:
    """C3 — 캐시키에 model+dim 을 포함한다. 예전엔 raw text 만이라, Gemini(768)↔local(384)↔
    random(64) 폴백이 오가면 같은 text 가 **혼합차원 벡터로 pin** 돼 cosine 유사도가
    수치적으로 깨지거나 차원 불일치로 예외가 났다. model/dim 이 바뀌면 키가 바뀌어 stale
    다른-차원 벡터를 안 되쓴다.
    """
    return f"{get_embed_model()}\x00{get_embed_dim()}\x00{text}"


def _cache_put(text: str, vec: List[float], *, degraded: bool = False) -> None:
    # 설정 차원과 다른 폴백 벡터(local 384·random 64 등)는 캐시하지 않는다 — 그 키(현재 dim)
    # 아래 잘못된 차원을 pin 하면 혼합차원 오염이 재발한다. 재계산은 폴백 한정이라 저비용.
    if len(vec) != get_embed_dim():
        return
    # 의미 신호가 없는 무작위 벡터는 차원이 우연히 맞아도 캐시하지 않는다. 캐시에 들어가면
    # 캐시 히트를 "정상 임베딩"으로 되읽어(`_cache_get` 은 출처를 안 나름) degraded 표시가
    # 소멸한다 — 설정 dim 이 64 인 구성에서 실제로 그렇게 새어나간다.
    if degraded:
        return
    key = _cache_key(text)
    _max = _get_cache_max()
    with _cache_lock:
        _embed_cache[key] = vec
        _embed_cache.move_to_end(key)
        while len(_embed_cache) > _max:
            _embed_cache.popitem(last=False)


def _cache_get(text: str) -> Optional[List[float]]:
    key = _cache_key(text)
    with _cache_lock:
        vec = _embed_cache.get(key)   # pop 아닌 get — TOCTOU KeyError 제거
        if vec is not None:
            _embed_cache.move_to_end(key)
        return vec


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

def resolve_google_api_key() -> Tuple[str, str]:
    """Gemini/Google 키를 **`llm_call` 과 같은 출처들**에서 해석한다.

    ⚠ 이 함수가 생긴 이유 — 실측된 라이브 결함:
    이 저장소의 Gemini 키는 `OAI_CONFIG_LIST` 에 있고(2건, len 39) **env 는 전부 비어
    있다**. 그런데 embedder 는 env 만 읽었으므로 클라이언트 생성이 항상 실패해
    HTTP→local→**무작위 벡터**로 떨어졌다. 그 결과 저장소 실 KB 102건의 벡터가 전부
    난수였다. `workflow/ai.py::llm_call` 은 같은 키를 `cfg["api_key"]` 로 읽어 정상
    동작했다 — **같은 자격증명, 두 개의 해석기, 한쪽만 조용히 실패**한 경우다.

    (앞선 라운드에서 이 상태를 "Gemini 키 부재" 로 적었는데 사실이 아니었다. 키는 있고,
    embedder 가 있는 곳을 안 봤다.)

    Returns:
        `(api_key, source)` — source 는 `"env:NAME"` / `"oai_config"` / `""`(못 찾음).
    """
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        v = str(os.environ.get(name) or "").strip()
        if v:
            return v, f"env:{name}"
    # env 에 없으면 llm_call 이 쓰는 정본 로더를 그대로 쓴다(경로·캐시·파싱 규칙 공유).
    try:
        from workflow.ai import load_oai_configs
        for cfg in load_oai_configs(None) or []:
            if not isinstance(cfg, dict):
                continue
            model = str(cfg.get("model") or "").lower()
            api_type = str(cfg.get("api_type") or cfg.get("provider") or "").lower()
            if "gemini" not in model and "goog" not in api_type:
                continue
            v = str(cfg.get("api_key") or "").strip()
            if v:
                return v, "oai_config"
    except Exception as e:   # noqa: BLE001 - 키 해석 실패는 폴백 사유로 보고만 한다
        _logger.debug("oai_config 에서 Gemini 키 해석 실패: %s", e)
    return "", ""


def _init_gemini_client():
    """Gemini 클라이언트 초기화 (lazy)."""
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client

    api_key, key_source = resolve_google_api_key()
    if not api_key:
        _logger.warning(
            "Gemini 임베딩 키를 못 찾았다 (env GEMINI_API_KEY/GOOGLE_API_KEY 및 "
            "OAI_CONFIG_LIST 모두) — 폴백 체인으로 내려간다. 최후 폴백은 무작위 벡터라 "
            "시맨틱 검색이 무효가 된다."
        )
        return None
    _logger.info("Gemini 임베딩 키 출처: %s", key_source)

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


def _embed_gemini(text: str, *, reasons: Optional[List[str]] = None) -> Optional[List[float]]:
    """Gemini text-embedding-004로 단일 텍스트 임베딩.

    ⚠ **재시도가 필수인 이유**: 실패하면 체인이 HTTP→local→**무작위 벡터**로 내려가고,
    `learn()` 경로에서는 그 무작위 벡터가 **영구 저장**된다. 즉 일시적인 429/503 하나가
    KB 엔트리를 영구히 오염시킨다. 예전엔 재시도가 0회였다(`_embed_http` 는 2회였는데
    정작 1순위 백엔드만 없었다).

    Args:
        reasons: 주면 실패 사유를 누적한다 — "왜 무작위로 떨어졌는지" 를 추적 가능하게.
    """
    client = _init_gemini_client()
    if client is None:
        if reasons is not None:
            reasons.append("gemini: 클라이언트 없음(키 미해석 또는 SDK 미설치)")
        return None

    model = get_embed_model()
    text = _clip_input(text, reasons=reasons)
    last_err = ""
    for attempt in range(_EMBED_ATTEMPTS):
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
            last_err = "응답에 embedding 이 없음"
            break   # 형식 문제는 재시도해도 같다
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < _EMBED_ATTEMPTS - 1:
                _logger.warning("Gemini embedding 실패(%d/%d), 재시도: %s",
                                attempt + 1, _EMBED_ATTEMPTS, last_err)
                time.sleep(_EMBED_RETRY_SLEEP * (attempt + 1))
    _logger.warning("Gemini embedding 최종 실패: %s", last_err)
    if reasons is not None:
        reasons.append(f"gemini: {last_err}")
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
        # 단건 경로(`_embed_gemini`)와 **같은 상한**을 적용한다. 한쪽만 자르면 같은 텍스트가
        # 배치에서는 API 거부(→무작위), 단건에서는 절단으로 갈려 결과가 경로에 따라 달라진다.
        batch = [_clip_input(t) for t in texts[i:i + batch_size]]
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

def _embed_http(text: str, *, reasons: Optional[List[str]] = None) -> Optional[List[float]]:
    """외부 HTTP API로 임베딩 (기존 호환)."""
    embed_url = os.environ.get("KB_EMBED_URL", "").strip()
    if not embed_url:
        if reasons is not None:
            reasons.append("http: KB_EMBED_URL 미설정")
        return None

    try:
        import requests  # type: ignore
    except ImportError:
        if reasons is not None:
            reasons.append("http: requests 미설치")
        return None

    text = _clip_input(text, reasons=reasons)
    last_err = ""
    for attempt in range(2):
        try:
            resp = requests.post(embed_url, json={"text": text}, timeout=5)
            resp.raise_for_status()
            vec = resp.json().get("vector") or []
            if vec:
                return [float(v) for v in vec]
            last_err = "응답에 vector 가 없음"
            break
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt == 0:
                _logger.warning("HTTP embedding failed (attempt 1), retrying: %s", e)
                time.sleep(1.5)

    _logger.warning("HTTP embedding failed after retries: %s", last_err)
    if reasons is not None:
        reasons.append(f"http: {last_err}")
    return None


# ==============================================================
# 3. Local sentence-transformers
# ==============================================================

def _embed_local(text: str, *, reasons: Optional[List[str]] = None) -> Optional[List[float]]:
    """sentence-transformers 로컬 모델."""
    global _st_model, _st_model_tried

    if _st_model_tried and _st_model is None:
        if reasons is not None:
            reasons.append("local: 앞선 시도에서 로드 실패(재시도 안 함)")
        return None

    if _st_model is None:
        _st_model_tried = True
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            _st_model = SentenceTransformer("all-MiniLM-L6-v2")
            _logger.info("Loaded local embedding model: all-MiniLM-L6-v2 (384dim)")
        except ImportError:
            _logger.debug("sentence-transformers not installed")
            if reasons is not None:
                reasons.append("local: sentence-transformers 미설치")
            return None
        except Exception as e:
            _logger.warning("Failed to load local model: %s", e)
            if reasons is not None:
                reasons.append(f"local: 모델 로드 실패 {type(e).__name__}: {e}")
            return None

    try:
        vec = _st_model.encode(text).tolist()
        return [float(v) for v in vec]
    except Exception as e:
        _logger.warning("Local embedding failed: %s", e)
        if reasons is not None:
            reasons.append(f"local: {type(e).__name__}: {e}")
        return None


# ==============================================================
# 4. Seeded random (최후 폴백)
# ==============================================================

def _embed_random(text: str, dim: int = 64) -> List[float]:
    """동일 입력 -> 동일 벡터 (seed 고정).

    ⚠ 이 벡터에는 **의미 신호가 없다**. 폴백 체인이 전부 실패했을 때 호출자를 죽이지 않기
    위한 자리 채움일 뿐이므로, 이걸로 만든 유사도는 랭킹 근거가 될 수 없다
    (`get_embedding` 이 `meta_out["degraded"]=True` 로 표시한다).

    seed 는 `hashlib` 로 만든다. 예전엔 내장 `hash(text)` 였는데 파이썬의 str 해시는
    **프로세스마다 무작위화**된다(`sys.flags.hash_randomization=1`, `PYTHONHASHSEED` 미설정).
    실측: 같은 문자열이 세 프로세스에서 전부 다른 벡터였다. 그래서 docstring 의 "seed 고정"
    이 거짓이었고, 더 나쁘게는 **어제 저장한 KB 벡터와 오늘 만든 질의 벡터가 통계적으로
    무관**해져 폴백 검색이 자기 자신과도 일관되지 않았다.
    """
    digest = hashlib.blake2b(text.encode("utf-8", "surrogatepass"), digest_size=8).digest()
    seed = int.from_bytes(digest, "big") % (2**32)
    rng = np.random.default_rng(seed)
    return rng.normal(size=dim).astype(float).tolist()


# ==============================================================
# Public API
# ==============================================================

def _note_embed(meta_out: Optional[Dict[str, Any]], source: str, vec: List[float],
                *, reasons: Optional[List[str]] = None) -> None:
    """임베딩 출처를 표준 키로 기록한다 — **degraded 판정의 단일 출처**.

    `degraded=True` 는 "이 벡터에 의미 신호가 없다"는 뜻이다. 판정을 소비처마다 복제하면
    한쪽만 고쳐지는 게 이 저장소가 반복해 겪은 실패 모드라(`_is_hsis_data_row`·`_ratchet_core`)
    여기 한 곳에서만 정한다.
    """
    if meta_out is None:
        return
    meta_out["embed_source"] = source
    meta_out["embed_dim"] = len(vec or [])
    # cache 히트는 설정 dim 과 일치하고 degraded 가 아닌 벡터만 담기므로(위 `_cache_put`)
    # 설정 모델명이 곧 그 벡터의 모델이다.
    meta_out["embed_model"] = get_embed_model() if source in ("gemini", "cache") else source
    meta_out["degraded"] = source in _DEGRADED_SOURCES
    # 왜 이 출처로 떨어졌는지 — `degraded=True` 만으로는 "키 미해석"·"429"·"입력 초과"를
    # 구분할 수 없어 운영자가 고칠 수 없다.
    if reasons:
        meta_out["embed_fallback_reasons"] = list(reasons)


def get_embedding(text: str, *, meta_out: Optional[Dict[str, Any]] = None) -> List[float]:
    """텍스트 임베딩 반환 (폴백 체인 적용).

    Args:
        meta_out: 주면 임베딩 **출처**를 기록한다(additive — 기존 호출 9곳 무영향).
                  `{"embed_source","embed_model","embed_dim","degraded"}` +
                  폴백이 일어났으면 `embed_fallback_reasons`(왜 내려갔는지).
                  `degraded=True` 는 무작위 폴백 = 의미 신호 없음 → 랭킹에 쓰면 안 된다.

    Returns:
        float 리스트 (차원은 사용된 모델에 따라 다름)
    """
    text = (text or "").strip()
    if not text:
        _note_embed(meta_out, "empty", [])
        return []

    cached = _cache_get(text)
    if cached is not None:
        _note_embed(meta_out, "cache", cached)
        return cached

    reasons: List[str] = []

    # 1) Gemini
    vec = _embed_gemini(text, reasons=reasons)
    if vec:
        _cache_put(text, vec)
        _note_embed(meta_out, "gemini", vec, reasons=reasons)
        return vec

    # 2) External HTTP
    vec = _embed_http(text, reasons=reasons)
    if vec:
        _cache_put(text, vec)
        _note_embed(meta_out, "http", vec, reasons=reasons)
        return vec

    # 3) Local model
    vec = _embed_local(text, reasons=reasons)
    if vec:
        _cache_put(text, vec)
        _note_embed(meta_out, "local", vec, reasons=reasons)
        return vec

    # 4) Random fallback — 의미 신호 없음. 캐시하지 않는다(`degraded=True` 표시가 캐시
    #    히트에서 소멸하는 것을 막는다). 재계산은 blake2b seed 라 저렴하고 결정적이다.
    vec = _embed_random(text, dim=64)
    _cache_put(text, vec, degraded=True)
    _note_embed(meta_out, "random", vec, reasons=reasons)
    return vec


def get_embeddings_batch(
    texts: List[str], *, meta_out: Optional[Dict[str, Any]] = None
) -> List[List[float]]:
    """배치 임베딩 (Gemini 배치 -> 개별 폴백).

    Args:
        meta_out: 주면 **배치 전체의** 출처 분포를 기록한다 —
                  `{"embed_sources": {source: count}, "degraded_count": int, "degraded": bool}`.
                  개별 폴백은 텍스트마다 출처가 다를 수 있어 단일 값으로 접지 않는다.

    Returns:
        각 텍스트에 대한 embedding 리스트
    """
    sources: Dict[str, int] = {}

    def _tally(src: str) -> None:
        sources[src] = sources.get(src, 0) + 1

    def _finish() -> None:
        if meta_out is None:
            return
        degraded_n = sum(n for s, n in sources.items() if s in _DEGRADED_SOURCES)
        meta_out["embed_sources"] = dict(sources)
        meta_out["degraded_count"] = degraded_n
        meta_out["degraded"] = degraded_n > 0

    if not texts:
        _finish()
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
            _tally("cache")
        else:
            uncached_indices.append(i)
            uncached_texts.append(t)

    if not uncached_texts:
        _finish()
        return [r for r in results if r is not None]

    # Gemini 배치 시도
    batch_vecs = _embed_gemini_batch(uncached_texts)
    if batch_vecs and len(batch_vecs) == len(uncached_texts):
        for idx, text, vec in zip(uncached_indices, uncached_texts, batch_vecs):
            results[idx] = vec
            _cache_put(text, vec)
            _tally("gemini")
    else:
        # 배치 실패 -> 개별 폴백. 텍스트마다 출처가 갈릴 수 있어 개별로 집계한다.
        for i, idx in enumerate(uncached_indices):
            one: Dict[str, Any] = {}
            results[idx] = get_embedding(uncached_texts[i], meta_out=one)
            _tally(str(one.get("embed_source") or "unknown"))

    _finish()
    return [r if r is not None else [] for r in results]


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """코사인 유사도 계산.

    ⚠ **차원이 다르면 0.0** 을 낸다("관계 미확인"). 예전엔 짧은 쪽을 zero-pad 했는데,
    임베딩에서 그건 "없는 차원의 값이 전부 0" 이라고 **가정**하는 것이고 그런 가정을
    보장하는 임베딩 모델은 없다. 실제로 이 저장소의 KB 는 64차원 폴백 벡터로 채워져 있고
    Gemini 키가 생기면 질의는 768차원이 된다 — pad 는 앞 64차원만으로 계산한 무의미한 수를
    **그럴듯한 유사도로 위장**해서 내놓았다. 0.0 이면 `semantic_search` 의 `score <= 0.0`
    필터가 걸러내고, 몇 건이 걸러졌는지는 `stats_out` 으로 보고된다(침묵 드롭 아님).
    """
    a_arr = np.array(a, dtype=float)
    b_arr = np.array(b, dtype=float)
    if a_arr.size == 0 or b_arr.size == 0:
        return 0.0
    if a_arr.size != b_arr.size:
        return 0.0
    na = np.linalg.norm(a_arr)
    nb = np.linalg.norm(b_arr)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (na * nb))
