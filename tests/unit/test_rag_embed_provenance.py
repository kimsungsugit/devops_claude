"""RAG 근거의 정직성 — 임베딩 출처 관측 + 열화 벡터로 랭킹 금지.

## 왜 이 테스트가 있나 (실측)

저장소의 실 KB 엔트리 **102건이 전부 64차원 무작위 폴백 벡터**였다(Gemini 키 부재).
그 상태로 `semantic_search` 는 102건 중 **52건을 "관련 근거"로 통과**시켰고, 점수는
0.20~0.25 로 그럴듯했으며 경고는 **0건**이었다. 그 근거가 흘러가는 곳은 assistant 답변과
**생성 문서 본문**(`report_gen/docx_builder.py:2102`)이다.

부수적으로 `_embed_random` 의 docstring 은 "동일 입력 -> 동일 벡터 (seed 고정)" 라고 적혀
있었지만 내장 `hash()` 가 프로세스마다 무작위화되므로 **거짓**이었다 — 어제 저장한 벡터와
오늘 만든 질의 벡터가 통계적으로 무관했다.

## 뮤테이션 대조 (각 테스트 docstring 에 명시)

옛 동작에서 실패하지 않는 테스트는 무의미하므로, 되돌릴 지점을 각 테스트에 적어 둔다.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

# ==============================================================
# 1. 임베딩 출처 관측 (embedder.get_embedding meta_out)
# ==============================================================

class TestEmbedProvenance:
    def _isolate(self, monkeypatch, *, gemini=None, http=None, local=None):
        from workflow.rag import embedder
        monkeypatch.setattr(embedder, "_embed_gemini", lambda t, reasons=None: gemini)
        monkeypatch.setattr(embedder, "_embed_http", lambda t, reasons=None: http)
        monkeypatch.setattr(embedder, "_embed_local", lambda t, reasons=None: local)
        embedder._embed_cache.clear()
        return embedder

    def test_random_fallback_is_marked_degraded(self, monkeypatch):
        """모든 백엔드 실패 → source=random, degraded=True.

        뮤테이션: `_note_embed` 호출을 없애면 meta_out 이 비어 실패.
        """
        embedder = self._isolate(monkeypatch)
        meta = {}
        vec = embedder.get_embedding("아무 텍스트", meta_out=meta)
        assert len(vec) == 64
        assert meta["embed_source"] == "random"
        assert meta["degraded"] is True
        assert meta["embed_dim"] == 64

    @pytest.mark.parametrize("backend,expected", [
        ("gemini", "gemini"),
        ("http", "http"),
        ("local", "local"),
    ])
    def test_working_backend_is_not_degraded(self, monkeypatch, backend, expected):
        """실제 임베딩이 나온 경로는 degraded=False — 가드가 공허하지 않음을 보장."""
        embedder = self._isolate(monkeypatch, **{backend: [0.1, 0.2, 0.3]})
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 3)
        monkeypatch.setattr(embedder, "get_embed_model", lambda: "m-test")
        meta = {}
        vec = embedder.get_embedding("텍스트", meta_out=meta)
        assert vec == [0.1, 0.2, 0.3]
        assert meta["embed_source"] == expected
        assert meta["degraded"] is False

    def test_empty_text_is_reported_not_silently_empty(self, monkeypatch):
        embedder = self._isolate(monkeypatch)
        meta = {}
        assert embedder.get_embedding("   ", meta_out=meta) == []
        assert meta["embed_source"] == "empty"
        assert meta["embed_dim"] == 0

    def test_meta_out_is_optional(self, monkeypatch):
        """기존 호출 9곳은 meta_out 을 안 넘긴다 — additive 계약."""
        embedder = self._isolate(monkeypatch)
        assert len(embedder.get_embedding("텍스트")) == 64

    def test_degraded_vector_is_never_cached(self, monkeypatch):
        """설정 dim 이 우연히 64 여도 무작위 벡터는 캐시하지 않는다.

        캐시에 들어가면 다음 조회가 source='cache'(degraded 없음)로 되읽혀 **열화 표시가
        소멸**한다.

        뮤테이션: `_cache_put` 의 `if degraded: return` 을 없애면 두 번째 조회가
        source='cache' 가 되어 실패.
        """
        embedder = self._isolate(monkeypatch)
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 64)   # 무작위와 같은 차원
        m1, m2 = {}, {}
        embedder.get_embedding("동일텍스트", meta_out=m1)
        embedder.get_embedding("동일텍스트", meta_out=m2)
        assert m1["embed_source"] == "random"
        assert m2["embed_source"] == "random", "캐시 히트로 되읽히면 열화 표시가 사라진다"
        assert m2["degraded"] is True
        assert len(embedder._embed_cache) == 0

    def test_cache_hit_reports_cache_source(self, monkeypatch):
        embedder = self._isolate(monkeypatch, gemini=[0.5, 0.5])
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 2)
        monkeypatch.setattr(embedder, "get_embed_model", lambda: "m-cached")
        m1, m2 = {}, {}
        embedder.get_embedding("t", meta_out=m1)
        embedder.get_embedding("t", meta_out=m2)
        assert m1["embed_source"] == "gemini"
        assert m2["embed_source"] == "cache"
        assert m2["embed_model"] == "m-cached"
        assert m2["degraded"] is False
        embedder._embed_cache.clear()


class TestBatchProvenance:
    def test_batch_reports_source_distribution(self, monkeypatch):
        """개별 폴백은 텍스트마다 출처가 갈릴 수 있어 단일 값으로 접지 않는다.

        뮤테이션: `_finish()` 호출을 없애면 meta_out 이 비어 실패.
        """
        from workflow.rag import embedder
        monkeypatch.setattr(embedder, "_embed_gemini_batch", lambda ts: None)
        monkeypatch.setattr(embedder, "_embed_gemini", lambda t, reasons=None: None)
        monkeypatch.setattr(embedder, "_embed_http", lambda t, reasons=None: None)
        monkeypatch.setattr(embedder, "_embed_local", lambda t, reasons=None: None)
        embedder._embed_cache.clear()
        meta = {}
        out = embedder.get_embeddings_batch(["a", "b"], meta_out=meta)
        assert len(out) == 2
        assert meta["embed_sources"] == {"random": 2}
        assert meta["degraded_count"] == 2
        assert meta["degraded"] is True

    def test_batch_success_is_not_degraded(self, monkeypatch):
        from workflow.rag import embedder
        monkeypatch.setattr(embedder, "_embed_gemini_batch",
                            lambda ts: [[0.1, 0.2] for _ in ts])
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 2)
        embedder._embed_cache.clear()
        meta = {}
        embedder.get_embeddings_batch(["a", "b"], meta_out=meta)
        assert meta["embed_sources"] == {"gemini": 2}
        assert meta["degraded"] is False
        embedder._embed_cache.clear()

    def test_empty_batch_still_reports(self, monkeypatch):
        from workflow.rag import embedder
        meta = {}
        assert embedder.get_embeddings_batch([], meta_out=meta) == []
        assert meta["degraded"] is False
        assert meta["embed_sources"] == {}


# ==============================================================
# 2. _embed_random 프로세스간 결정성
# ==============================================================

_DETERMINISM_SNIPPET = (
    "import sys; sys.path.insert(0, r'{root}');"
    "from workflow.rag.embedder import _embed_random;"
    "print(repr(_embed_random('ASIL D coverage', dim=4)))"
)


def test_embed_random_is_stable_across_processes():
    """docstring 의 'seed 고정' 이 프로세스 경계에서도 성립해야 한다.

    내장 `hash()` 는 str 에 대해 프로세스마다 무작위화된다(`PYTHONHASHSEED` 미설정 시).
    그래서 옛 구현은 **같은 문자열이 실행마다 다른 벡터**였고, 저장된 KB 벡터와 새 질의
    벡터가 통계적으로 무관해져 폴백 검색이 자기 자신과도 일관되지 않았다.

    뮤테이션: `hashlib.blake2b(...)` 를 `abs(hash(text))` 로 되돌리면 실패.
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    code = _DETERMINISM_SNIPPET.format(root=str(root))
    outs = []
    for _ in range(3):
        # 각 실행이 독립 프로세스 = 서로 다른 hash seed
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, timeout=120, cwd=str(root))
        assert proc.returncode == 0, proc.stderr[-2000:]
        outs.append(proc.stdout.strip())
    assert len(set(outs)) == 1, f"프로세스마다 다른 벡터: {outs}"


def test_embed_random_still_differs_by_input():
    """결정성을 얻으려고 상수 seed 로 만들면 모든 텍스트가 같은 벡터가 된다 — 그건 아님."""
    from workflow.rag.embedder import _embed_random
    assert _embed_random("alpha", dim=8) != _embed_random("beta", dim=8)


def test_embed_random_handles_surrogates():
    """`.encode('utf-8')` 만 쓰면 서로게이트 문자에서 UnicodeEncodeError 로 죽는다.

    KB 텍스트는 파일/로그에서 오므로 깨진 인코딩이 섞일 수 있다.
    뮤테이션: `'surrogatepass'` 를 없애면 예외로 실패.
    """
    from workflow.rag.embedder import _embed_random
    assert len(_embed_random("깨짐\ud800문자", dim=4)) == 4


# ==============================================================
# 3. cosine_similarity — 차원 불일치는 위장하지 않는다
# ==============================================================

class TestCosineDimMismatch:
    def test_mismatch_returns_zero_not_padded_similarity(self):
        """짧은 쪽 zero-pad 는 "없는 차원의 값이 전부 0" 이라는 근거 없는 가정이다.

        실제 피해: KB 는 64차원 폴백 벡터인데 Gemini 키가 생기면 질의는 768차원이 된다 —
        pad 는 앞 64차원만으로 계산한 무의미한 수를 **그럴듯한 유사도로 위장**했다.

        뮤테이션: `np.pad` 분기를 되살리면 1.0 이 나와 실패.
        """
        from workflow.rag.embedder import cosine_similarity
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0, 0.0]) == 0.0

    def test_same_dim_still_computed(self):
        from workflow.rag.embedder import cosine_similarity
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


# ==============================================================
# 4. semantic_search — 열화 벡터로 랭킹하지 않는다
# ==============================================================

def _entry(eid, vec, ctx="coverage 미달", weight=1.0):
    return {"id": eid, "vector": list(vec), "category": "c", "weight": weight,
            "error_raw": eid, "error_clean": eid, "fix": "fix", "context": ctx}


class TestSemanticSearchDegraded:
    def _degraded(self, monkeypatch):
        from workflow.rag import embedder
        monkeypatch.setattr(embedder, "_embed_gemini", lambda t, reasons=None: None)
        monkeypatch.setattr(embedder, "_embed_http", lambda t, reasons=None: None)
        monkeypatch.setattr(embedder, "_embed_local", lambda t, reasons=None: None)
        embedder._embed_cache.clear()

    def _working(self, monkeypatch, vec):
        from workflow.rag import embedder
        monkeypatch.setattr(embedder, "_embed_gemini", lambda t, reasons=None: list(vec))
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: len(vec))
        monkeypatch.setattr(embedder, "get_embed_model", lambda: "m-ok")
        embedder._embed_cache.clear()

    def test_degraded_query_yields_no_ranking(self, monkeypatch):
        """무작위 질의 벡터로는 순위를 만들지 않는다.

        뮤테이션: `if q_meta.get("degraded")` 분기를 없애면 무작위 랭킹이 돌아와 실패.
        """
        from workflow.rag.searcher import semantic_search
        self._degraded(monkeypatch)
        data = [_entry(f"e{i}", [0.1 * i] * 64) for i in range(1, 11)]
        stats = {}
        assert semantic_search(data, "coverage", 10, stats_out=stats) == []
        assert stats["semantic_disabled_reason"] == "degraded_query_embedding:random"
        assert stats["semantic_ranked"] == 0
        assert stats["query_embed_source"] == "random"

    def test_non_degraded_query_still_ranks(self, monkeypatch):
        """음성 대조군 — 가드가 semantic 을 통째로 죽이지 않았음을 보장.

        이 테스트가 없으면 `return []` 를 무조건 실행하도록 바꿔도 위 테스트는 통과한다.
        """
        from workflow.rag.searcher import semantic_search
        self._working(monkeypatch, [1.0, 0.0, 0.0])
        data = [_entry("a", [1.0, 0.0, 0.0]), _entry("b", [0.0, 1.0, 0.0])]
        stats = {}
        res = semantic_search(data, "coverage", 10, stats_out=stats)
        assert [r["id"] for r in res] == ["a"], "완전일치가 1위여야 한다"
        assert stats["semantic_disabled_reason"] is None
        assert stats["semantic_ranked"] == 1

    def test_dim_mismatch_is_counted_not_silently_dropped(self, monkeypatch):
        """다른 모델로 만든 KB 벡터는 비교 불가 — 몇 건 빠졌는지 보고해야 한다.

        뮤테이션: `skipped_dim_mismatch` 집계를 없애면 키가 사라져 실패.
        """
        from workflow.rag.searcher import semantic_search
        self._working(monkeypatch, [1.0, 0.0, 0.0])
        data = [
            _entry("ok", [1.0, 0.0, 0.0]),
            _entry("wrongdim", [1.0, 0.0]),          # 2차원 — 비교 불가
            _entry("wrongdim2", [1.0] * 64),         # 64차원 — 비교 불가
            _entry("novec", []),
        ]
        stats = {}
        res = semantic_search(data, "coverage", 10, stats_out=stats)
        assert [r["id"] for r in res] == ["ok"]
        assert stats["semantic_skipped_dim_mismatch"] == 2
        assert stats["semantic_skipped_no_vector"] == 1

    def test_stats_out_is_optional(self, monkeypatch):
        from workflow.rag.searcher import semantic_search
        self._degraded(monkeypatch)
        assert semantic_search([_entry("a", [1.0] * 64)], "q", 5) == []


class TestHybridSearchDegraded:
    def test_degraded_falls_back_to_keyword_and_keeps_scale(self, monkeypatch):
        """semantic 이 열화로 비면 RRF 융합을 건너뛰고 keyword 척도를 유지한다.

        RRF 로 감싸면 점수 상한이 0.0328 로 바뀌어, 절대 문턱을 가진 소비처가
        "근거 없음" 으로 오독한다. 강등 사실을 척도로도 드러낸다.

        뮤테이션: `if not sem_results:` 분기를 없애면 fusion='rrf' + 점수 0.03 대가 되어 실패.
        """
        from workflow.rag import embedder
        from workflow.rag.searcher import hybrid_search
        monkeypatch.setattr(embedder, "_embed_gemini", lambda t, reasons=None: None)
        monkeypatch.setattr(embedder, "_embed_http", lambda t, reasons=None: None)
        monkeypatch.setattr(embedder, "_embed_local", lambda t, reasons=None: None)
        embedder._embed_cache.clear()
        data = [_entry("a", [0.5] * 64, ctx="coverage 미달 원인")]
        stats = {}
        res = hybrid_search(data, "coverage 미달", top_k=5, stats_out=stats)
        assert stats["fusion"] == "keyword_only_fallback"
        assert res, "keyword 신호는 살아 있어야 한다"
        assert res[0]["score"] > 0.05, f"RRF 척도로 눌리면 안 된다: {res[0]['score']}"

    def test_working_embedding_uses_rrf(self, monkeypatch):
        """음성 대조군 — 정상 임베딩에서는 융합이 유지된다."""
        from workflow.rag import embedder
        from workflow.rag.searcher import hybrid_search
        monkeypatch.setattr(embedder, "_embed_gemini", lambda t, reasons=None: [1.0, 0.0])
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 2)
        embedder._embed_cache.clear()
        data = [_entry("a", [1.0, 0.0], ctx="coverage 미달 원인")]
        stats = {}
        hybrid_search(data, "coverage 미달", top_k=5, stats_out=stats)
        assert stats["fusion"] == "rrf"
        embedder._embed_cache.clear()


def test_rrf_score_upper_bound_is_documented():
    """RRF 점수 척도 계약 — 절대 문턱을 붙이려는 미래의 소비처를 막는 앵커.

    `_kb_hints`(현재 dead code)가 `score < 0.3` 컷을 갖고 있는데, RRF 상한은
    `2/(k+1)` = 0.0328(k=60)이라 **구조적으로 통과 불가**였다. 척도가 바뀌면 이 테스트가
    깨지면서 소비처 문턱을 함께 보게 된다.
    """
    from workflow.rag.searcher import _rrf_merge
    k = 60
    both_first = [[{"id": "x"}], [{"id": "x"}]]
    merged = _rrf_merge(both_first, k=k, top_k=5)
    assert merged[0]["score"] == pytest.approx(2.0 / (k + 1))
    assert merged[0]["score"] < 0.05, "RRF 점수에 0.3 같은 절대 문턱은 성립하지 않는다"


# ==============================================================
# 5. 저장 엔트리에 임베딩 출처가 남는다
# ==============================================================

class TestStoredProvenance:
    def test_learn_stamps_embed_provenance(self, tmp_path, monkeypatch):
        """엔트리의 vector 가 실측인지 무작위인지 **사후에** 판별 가능해야 한다.

        실측: 실 KB 102건에 이 정보가 없어 벡터 길이로 추정할 수밖에 없었고, 설정 dim 이
        바뀌면 추정도 깨진다. `metadata` 는 이미 JSON 컬럼이라 스키마 변경이 없다.

        뮤테이션: `"metadata": {"embed": ...}` 를 지우면 KeyError 로 실패.
        """
        from workflow.rag import KnowledgeBase, embedder
        monkeypatch.setattr(embedder, "_embed_gemini", lambda t, reasons=None: None)
        monkeypatch.setattr(embedder, "_embed_http", lambda t, reasons=None: None)
        monkeypatch.setattr(embedder, "_embed_local", lambda t, reasons=None: None)
        embedder._embed_cache.clear()

        kb = KnowledgeBase(tmp_path)
        kb.learn("빌드 실패 xyz", "이렇게 고쳤다", success=True)
        assert kb.data, "엔트리가 만들어져야 한다"
        embed = (kb.data[-1].get("metadata") or {}).get("embed") or {}
        assert embed.get("source") == "random"
        assert embed.get("degraded") is True
        assert embed.get("dim") == 64

    def test_add_document_stamps_embed_provenance(self, tmp_path, monkeypatch):
        from workflow.rag import KnowledgeBase, embedder
        monkeypatch.setattr(embedder, "_embed_gemini", lambda t, reasons=None: [0.1, 0.2])
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 2)
        monkeypatch.setattr(embedder, "get_embed_model", lambda: "m-doc")
        embedder._embed_cache.clear()

        kb = KnowledgeBase(tmp_path)
        kb.add_document("제목", "본문 내용", category="general")
        embed = (kb.data[-1].get("metadata") or {}).get("embed") or {}
        assert embed.get("source") == "gemini"
        assert embed.get("degraded") is False
        assert embed.get("model") == "m-doc"
        # 기존 metadata 키를 덮어쓰지 않는다
        assert "req_ids" in (kb.data[-1].get("metadata") or {})
        embedder._embed_cache.clear()


# ==============================================================
# 6. 합성 요약이 실제 근거보다 위에 오지 않는다
# ==============================================================

class TestSyntheticReportHitRanking:
    def test_synthetic_hit_ranks_below_real_evidence(self, tmp_path, monkeypatch):
        """합성 요약은 검색된 근거가 아니다 — 점수를 0.35 로 하드코딩하면 RRF 근거
        (상한 0.0328)보다 **항상 위**에 정렬되고 top_k 슬롯을 먼저 차지한다.

        뮤테이션: `synth_score` 를 0.35 로 되돌리면 실패.
        """
        from workflow.retrieval import hybrid

        class _FakeKB:
            # 스텁은 실제 시그니처를 미러링해야 한다 — `_report_hits` 는 진단을 받기 위해
            # `stats_out` 을 넘긴다(TypeError 폴백을 일부러 두지 않았으므로 불일치는 즉시 드러난다).
            def search(self, q, top_k=5, stats_out=None, **_kw):
                return [{"id": "real1", "error_clean": "실제 근거", "fix": "f",
                         "score": 0.03, "source_file": "real1.json"}]

        monkeypatch.setattr(hybrid, "get_kb", lambda d: _FakeKB())
        hits = hybrid._report_hits("질문", tmp_path, top_k=5)
        real = [h for h in hits if not (h.get("metadata") or {}).get("synthetic")]
        synth = [h for h in hits if (h.get("metadata") or {}).get("synthetic")]
        assert real and synth, f"실제/합성 둘 다 있어야 한다: {[h['hit_id'] for h in hits]}"
        assert synth[0]["score"] < min(h["score"] for h in real)

    def test_synthetic_hit_is_labelled_in_context_text(self, tmp_path, monkeypatch):
        """LLM 은 chunk_text 만 읽는다 — metadata 플래그만으론 합성임을 알 수 없다."""
        from workflow.retrieval import hybrid

        class _EmptyKB:
            def search(self, q, top_k=5, stats_out=None, **_kw):
                return []

        monkeypatch.setattr(hybrid, "get_kb", lambda d: _EmptyKB())
        hits = hybrid._report_hits("질문", tmp_path, top_k=5)
        synth = [h for h in hits if (h.get("metadata") or {}).get("synthetic")]
        assert synth
        assert "합성" in synth[0]["chunk_text"]
        assert synth[0]["score"] > 0.0, "근거가 아예 없을 때는 유일한 컨텍스트라 살아 있어야 한다"
