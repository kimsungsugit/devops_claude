"""Hybrid search engine for RAG Knowledge Base.

Combines keyword (FTS) and semantic (vector) search using
Reciprocal Rank Fusion (RRF).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("workflow.rag.searcher")


def _get_config_float(name: str, default: float) -> float:
    try:
        import config
        return float(getattr(config, name, default))
    except Exception:
        return default


def _get_config_int(name: str, default: int) -> int:
    try:
        import config
        return int(getattr(config, name, default))
    except Exception:
        return default


# ==============================================================
# Keyword Search
# ==============================================================

def keyword_search(
    data: List[Dict[str, Any]],
    query: str,
    top_k: int = 20,
    *,
    categories: Optional[List[str]] = None,
    role: Optional[str] = None,
    stage: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """키워드 기반 검색 (in-memory).

    각 엔트리의 error_raw, error_clean, fix, context 필드에서
    쿼리 토큰 매칭 (BM25-like 단순 스코어링).

    Returns:
        score가 추가된 dict 리스트 (내림차순)
    """
    if not query or not data:
        return []

    # 쿼리 토큰화
    tokens = _tokenize(query)
    if not tokens:
        return []

    results: List[Dict[str, Any]] = []

    for idx, ent in enumerate(data):
        # 카테고리/역할/스테이지 필터
        if categories:
            ent_cat = str(ent.get("category") or "")
            if ent_cat not in categories:
                continue
        if role and ent.get("role") != role:
            continue
        if stage and ent.get("stage") != stage:
            continue

        # 검색 대상 텍스트 결합
        haystack = " ".join([
            str(ent.get("error_raw") or ""),
            str(ent.get("error_clean") or ""),
            str(ent.get("fix") or ""),
            str(ent.get("context") or ""),
        ]).lower()

        # 토큰 매칭 스코어
        score = 0.0
        matched_tokens = 0
        for token in tokens:
            count = haystack.count(token)
            if count > 0:
                matched_tokens += 1
                # BM25-inspired: diminishing returns for repeated matches
                score += min(count, 5) * (1.0 / (1.0 + 0.5 * count))

        if matched_tokens == 0:
            continue

        # 토큰 커버리지 보너스
        coverage = matched_tokens / len(tokens)
        score *= (0.5 + 0.5 * coverage)

        item = dict(ent)
        item["index"] = idx
        item["score"] = score
        item["_search_type"] = "keyword"
        results.append(item)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def _tokenize(text: str) -> List[str]:
    """쿼리 텍스트를 검색 토큰으로 분리."""
    text = text.lower().strip()
    # 특수문자 기준 분리, 2글자 이상만
    tokens = re.findall(r"[a-z0-9가-힣_]{2,}", text)
    # 중복 제거하되 순서 유지
    seen: set = set()
    unique: List[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


# ==============================================================
# Semantic Search
# ==============================================================

def semantic_search(
    data: List[Dict[str, Any]],
    query: str,
    top_k: int = 20,
    *,
    categories: Optional[List[str]] = None,
    role: Optional[str] = None,
    stage: Optional[str] = None,
    tags: Optional[List[str]] = None,
    stats_out: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """벡터 유사도 기반 시맨틱 검색.

    기존 KnowledgeBase.search() 로직을 분리한 것.

    ⚠ **열화된 질의 벡터로는 랭킹하지 않는다.** 임베딩 폴백 체인이 전부 실패하면
    `embedder` 는 무작위 벡터를 내는데(호출자를 죽이지 않기 위한 자리 채움), 그걸로 만든
    유사도 정렬은 랭킹이 아니라 난수 정렬이다. 실측: Gemini 키가 없는 이 저장소 상태에서
    실 KB 102건 중 **52건이 "관련 근거"로 통과**했고 점수(0.20~0.25)는 그럴듯했으며 경고는
    0건이었다. 그 근거가 흘러가는 곳은 assistant 답변과 **생성 문서 본문**
    (`report_gen/docx_builder.py`)이다.

    이제 열화 시 `[]` 를 낸다 → `hybrid_search` 는 keyword 단독으로 강등된다(=실제 신호).
    "왜 비었는지"는 `stats_out` 에 남으므로 KB 가 빈 것과 구분된다.

    Args:
        stats_out: 주면 이유·집계를 기록한다(additive — 기존 호출 무영향).
    """
    def _stat(**kv: Any) -> None:
        if stats_out is not None:
            stats_out.update(kv)

    if not query or not data:
        _stat(semantic_disabled_reason="empty_query_or_data", semantic_ranked=0)
        return []

    from workflow.rag.embedder import cosine_similarity, get_embedding

    q_meta: Dict[str, Any] = {}
    q_vec = get_embedding(query, meta_out=q_meta)
    _stat(
        query_embed_source=q_meta.get("embed_source"),
        query_embed_model=q_meta.get("embed_model"),
        query_embed_dim=q_meta.get("embed_dim"),
    )
    if not q_vec:
        _stat(semantic_disabled_reason="empty_query_vector", semantic_ranked=0)
        return []

    if q_meta.get("degraded"):
        # 무작위 폴백 벡터 = 의미 신호 0. 정렬해도 근거가 아니므로 순위를 만들지 않는다.
        _logger.warning(
            "semantic_search 비활성: 질의 임베딩이 열화 상태(source=%s) — 무작위 벡터로는 "
            "유사도 랭킹을 만들 수 없다. 임베딩 백엔드(GEMINI_API_KEY / KB_EMBED_URL / "
            "sentence-transformers)를 설정하면 복구된다. keyword 검색만 사용한다.",
            q_meta.get("embed_source"),
        )
        _stat(
            semantic_disabled_reason=f"degraded_query_embedding:{q_meta.get('embed_source')}",
            semantic_ranked=0,
        )
        return []

    norm_tags = [str(t) for t in (tags or []) if str(t).strip()]

    results: List[Dict[str, Any]] = []
    skipped_no_vector = 0
    skipped_dim_mismatch = 0

    for idx, ent in enumerate(data):
        # 필터
        if categories:
            ent_cat = str(ent.get("category") or "")
            if ent_cat not in categories:
                continue
        if role and ent.get("role") != role:
            continue
        if stage and ent.get("stage") != stage:
            continue

        v = ent.get("vector") or []
        if not v:
            skipped_no_vector += 1
            continue

        # 저장 벡터가 질의와 다른 차원이면 비교 자체가 성립하지 않는다(다른 모델로 만든
        # 벡터). cosine 이 예전처럼 zero-pad 해 그럴듯한 수를 내는 걸 막고, 몇 건이
        # 빠졌는지 보고한다 — 침묵 드롭이 아니어야 한다.
        if len(v) != len(q_vec):
            skipped_dim_mismatch += 1
            continue

        score = cosine_similarity(q_vec, v) * float(ent.get("weight", 1.0))

        # 태그 매칭 부스트
        if norm_tags:
            ent_tags = set(ent.get("tags") or [])
            hit = len(ent_tags.intersection(norm_tags))
            if hit:
                score += 0.05 * hit

        if score <= 0.0:
            continue

        item = dict(ent)
        item["index"] = idx
        item["score"] = score
        item["_search_type"] = "semantic"
        results.append(item)

    if skipped_dim_mismatch:
        _logger.warning(
            "semantic_search: 저장 벡터 %d건이 질의(dim=%d)와 차원이 달라 비교 불가로 제외됐다 "
            "— 다른 임베딩 모델로 만든 KB 다. 재인덱싱이 필요하다.",
            skipped_dim_mismatch,
            len(q_vec),
        )
    _stat(
        semantic_disabled_reason=None,
        semantic_ranked=len(results),
        semantic_skipped_no_vector=skipped_no_vector,
        semantic_skipped_dim_mismatch=skipped_dim_mismatch,
    )

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


# ==============================================================
# RRF (Reciprocal Rank Fusion)
# ==============================================================

def _rrf_merge(
    ranked_lists: List[List[Dict[str, Any]]],
    *,
    k: int = 60,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """Reciprocal Rank Fusion으로 여러 랭킹 리스트 병합.

    score = sum( 1/(k + rank_i) ) for each list
    """
    scores: Dict[str, float] = {}
    items: Dict[str, Dict[str, Any]] = {}

    for ranked_list in ranked_lists:
        for rank, item in enumerate(ranked_list):
            item_id = str(item.get("id") or item.get("index", rank))
            rrf_score = 1.0 / (k + rank + 1)  # rank is 0-based, +1 for 1-based
            scores[item_id] = scores.get(item_id, 0.0) + rrf_score
            if item_id not in items:
                items[item_id] = item

    # 최종 스코어 할당
    merged = []
    for item_id, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        item = dict(items[item_id])
        item["score"] = score
        item["_search_type"] = "hybrid"
        merged.append(item)

    return merged[:top_k]


# ==============================================================
# Boost (기존 부스팅 로직 통합)
# ==============================================================

def _apply_boosts(
    results: List[Dict[str, Any]],
    query: str,
    *,
    role: Optional[str] = None,
    stage: Optional[str] = None,
    req_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """기존 부스팅 로직 적용 (role, stage, recency, project, exact match)."""
    project_boost = _get_config_float("RAG_PROJECT_BOOST", 0.0)
    recency_days = _get_config_float("RAG_RECENCY_DAYS", 0)
    recency_boost = _get_config_float("RAG_RECENCY_BOOST", 0.0)
    apply_boost = _get_config_float("RAG_APPLY_COUNT_BOOST", 0.0)
    error_boost = _get_config_float("RAG_ERROR_COUNT_BOOST", 0.0)
    exact_boost = _get_config_float("RAG_EXACT_MATCH_BOOST", 0.4)

    for item in results:
        score = float(item.get("score", 0.0))

        # Role/Stage boost
        if role and item.get("role") == role:
            score += 0.15
        if stage and item.get("stage") == stage:
            score += 0.1

        # Recency boost
        if recency_days > 0 and item.get("timestamp"):
            try:
                ts = datetime.fromisoformat(str(item["timestamp"]))
                delta_days = (datetime.utcnow() - ts).total_seconds() / 86400.0
                if delta_days < recency_days:
                    score += recency_boost * (1.0 - (delta_days / recency_days))
            except Exception:
                pass

        # Project boost
        if project_boost > 0 and item.get("project_root"):
            if str(item["project_root"]) in query:
                score += project_boost

        # Apply count boost
        if apply_boost > 0:
            score += apply_boost * float(item.get("apply_count", 0))

        # Error count boost
        if error_boost > 0:
            score += error_boost * float(item.get("error_count", 0))

        # Exact match (req_id)
        if req_ids:
            hay = " ".join([
                str(item.get("error_raw") or ""),
                str(item.get("error_clean") or ""),
                str(item.get("context") or ""),
                str(item.get("source_file") or ""),
                json.dumps(item.get("metadata") or {}, ensure_ascii=False),
            ])
            if any(rid in hay for rid in req_ids):
                score += exact_boost

        item["score"] = score

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ==============================================================
# Hybrid Search (Public API)
# ==============================================================

def hybrid_search(
    data: List[Dict[str, Any]],
    query: str,
    top_k: int = 3,
    *,
    tags: Optional[List[str]] = None,
    role: Optional[str] = None,
    stage: Optional[str] = None,
    categories: Optional[List[str]] = None,
    alpha: Optional[float] = None,
    stats_out: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Hybrid 검색: keyword + semantic + RRF 병합.

    Args:
        data: KB 엔트리 리스트
        query: 검색 쿼리
        top_k: 반환할 결과 수
        tags: 태그 필터
        role: 역할 필터
        stage: 스테이지 필터
        categories: 카테고리 필터
        alpha: keyword/semantic 가중치 (0.0=keyword only, 1.0=semantic only, None=RRF)
        stats_out: 주면 semantic 축의 열화 사유·집계를 그대로 전파한다(additive).

    ⚠ **점수 척도 주의**: RRF 병합 점수는 `sum(1/(k+rank+1))` 이라 k=60 기본값에서
    **상한이 0.0328** 이다(두 리스트 모두 1위). semantic/keyword 단독 경로의 점수와 척도가
    **10배 이상 다르다**. 이 반환값에 절대 문턱(예: `score < 0.3` 컷)을 적용하면 융합
    경로에서는 전량 탈락한다 — 소비처는 `_search_type` 을 보고 척도를 구분할 것.

    Returns:
        score 포함된 결과 리스트
    """
    if not query or not data:
        if stats_out is not None:
            stats_out["semantic_disabled_reason"] = "empty_query_or_data"
        return []

    # alpha 결정
    if alpha is None:
        alpha = _get_config_float("RAG_HYBRID_ALPHA", 0.5)
    alpha = max(0.0, min(1.0, alpha))

    rrf_k = _get_config_int("RAG_RRF_K", 60)

    # 내부 검색에서 더 많은 후보 확보
    internal_top_k = max(top_k * 5, 20)

    from workflow.rag.chunker import _extract_req_ids_from_text
    req_ids = _extract_req_ids_from_text(query)

    if alpha == 0.0:
        # Keyword only
        results = keyword_search(data, query, internal_top_k,
                                 categories=categories, role=role, stage=stage)
        if stats_out is not None:
            stats_out["semantic_disabled_reason"] = "alpha=0 (keyword only)"
    elif alpha == 1.0:
        # Semantic only
        results = semantic_search(data, query, internal_top_k,
                                  categories=categories, role=role, stage=stage, tags=tags,
                                  stats_out=stats_out)
    else:
        # Hybrid: RRF merge
        kw_results = keyword_search(data, query, internal_top_k,
                                    categories=categories, role=role, stage=stage)
        sem_results = semantic_search(data, query, internal_top_k,
                                     categories=categories, role=role, stage=stage, tags=tags,
                                     stats_out=stats_out)
        # semantic 축이 열화로 비었으면 RRF 는 keyword 단독 랭킹을 그대로 재배열할 뿐인데
        # 점수 척도만 RRF(≤0.0328)로 바뀐다. 그러면 소비처가 척도를 오독하기 쉬우므로
        # 융합을 건너뛰고 keyword 점수 척도를 유지한다(=강등 사실을 척도로도 드러낸다).
        if not sem_results:
            results = kw_results
            if stats_out is not None:
                stats_out["fusion"] = "keyword_only_fallback"
        else:
            results = _rrf_merge([kw_results, sem_results], k=rrf_k, top_k=internal_top_k)
            if stats_out is not None:
                stats_out["fusion"] = "rrf"
                stats_out["rrf_k"] = rrf_k

    # 부스팅 적용
    results = _apply_boosts(results, query, role=role, stage=stage, req_ids=req_ids)

    if stats_out is not None:
        stats_out["keyword_ranked"] = len(
            [r for r in results if r.get("_search_type") == "keyword"]
        )
        stats_out["returned"] = len(results[:top_k])

    return results[:top_k]
