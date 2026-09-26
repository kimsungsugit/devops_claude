"""RAG egress 정직성 + 재인덱싱 경로 + 진단 배선.

## 왜 이 테스트가 있나 (실측)

### 근본 원인 — 키 해석이 갈라져 있었다

이 저장소의 Gemini 키는 `OAI_CONFIG_LIST` 에 있고(2건, len 39) **env 는 전부 비어 있다.**
`workflow/ai.py::llm_call` 은 `cfg["api_key"]` 로 읽어 정상 동작했지만, `embedder` 는
**env 만** 읽었으므로 클라이언트 생성이 항상 실패해 HTTP→local→**무작위 벡터**로 떨어졌다.
그래서 실 KB 102건의 벡터가 전부 난수였다.

⚠ 앞선 라운드에서 이 상태를 "Gemini 키 부재" 로 기록했는데 **사실이 아니었다.** 키는 있고,
embedder 가 있는 곳을 안 봤다. 같은 자격증명 · 두 개의 해석기 · 한쪽만 조용히 실패.

### 그 밖에 실측된 격차

| 항목 | 옛 상태 |
|---|---|
| `_embed_gemini` 재시도 | **0회** (`_embed_http` 는 2회) — 일시적 429 하나가 `learn()` 엔트리를 **영구** 오염 |
| 입력 길이 가드 | **전무**(패턴 검색 0건) — 상한 초과 시 API 거부 → 무작위 벡터 |
| 폴백 사유 | 미기록 — `degraded=True` 만 있어 "키 미해석"·"429"·"입력 초과"를 구분 못 함 |
| 재인덱싱 경로 | **없음** — 백엔드를 붙여도 기존 64차원 벡터가 남아 dim mismatch 로 전량 제외 |
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest


@pytest.fixture
def kb_dir():
    d = pathlib.Path(tempfile.mkdtemp()) / "kb_store"
    d.mkdir(parents=True)
    return d


@pytest.fixture(autouse=True)
def _isolate_embedder(monkeypatch):
    """모듈 전역(클라이언트/캐시/로컬모델 플래그)을 테스트마다 원복.

    ⚠ 전역 싱글톤을 teardown 에서 "특정 값으로 고정" 하지 말 것 — 반드시 원래 값 복원
    (`file_resolver._resolver` 누설로 단독 16건이 깨졌던 전례).
    """
    from workflow.rag import embedder
    saved = (embedder._gemini_client, embedder._st_model, embedder._st_model_tried)
    embedder._embed_cache.clear()
    yield
    embedder._gemini_client, embedder._st_model, embedder._st_model_tried = saved
    embedder._embed_cache.clear()


# ==============================================================
# 1. 키 해석 — llm_call 과 같은 출처를 봐야 한다
# ==============================================================

class TestKeyResolution:
    def test_env_key_wins_and_reports_source(self, monkeypatch):
        from workflow.rag import embedder
        monkeypatch.setenv("GEMINI_API_KEY", "env-key-1234567890")
        key, src = embedder.resolve_google_api_key()
        assert key == "env-key-1234567890"
        assert src == "env:GEMINI_API_KEY"

    def test_falls_back_to_oai_config_when_env_empty(self, monkeypatch):
        """**근본 원인 회귀 방지** — env 가 비어도 OAI_CONFIG_LIST 의 키를 찾아야 한다.

        뮤테이션: `load_oai_configs` 폴백을 지우면 키를 못 찾아 실패
        (= 실 KB 102건이 난수였던 그 상태로 되돌아간다).
        """
        from workflow.rag import embedder
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setattr(
            "workflow.ai.load_oai_configs",
            lambda _p: [{"model": "gemini-3-pro", "api_key": "cfg-key-abcdefghij"}],
        )
        key, src = embedder.resolve_google_api_key()
        assert key == "cfg-key-abcdefghij"
        assert src == "oai_config"

    def test_non_gemini_config_entries_are_ignored(self, monkeypatch):
        """OpenAI 키를 Gemini 클라이언트에 넣으면 401 로 죽는다 — 모델/타입으로 걸러야 한다."""
        from workflow.rag import embedder
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setattr(
            "workflow.ai.load_oai_configs",
            lambda _p: [{"model": "gpt-4o", "api_key": "sk-openai-key"}],
        )
        key, src = embedder.resolve_google_api_key()
        assert key == ""
        assert src == ""

    def test_missing_everywhere_returns_empty(self, monkeypatch):
        from workflow.rag import embedder
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setattr("workflow.ai.load_oai_configs", lambda _p: [])
        assert embedder.resolve_google_api_key() == ("", "")


# ==============================================================
# 2. 재시도 — 일시적 실패가 영구 오염이 되지 않게
# ==============================================================

class TestRetry:
    def test_gemini_retries_before_giving_up(self, monkeypatch):
        """옛 코드는 1회 시도 후 바로 무작위 폴백이었다.

        뮤테이션: `for attempt in range(_EMBED_ATTEMPTS)` 를 단일 시도로 되돌리면 호출이
        1회가 되어 실패.
        """
        from workflow.rag import embedder
        calls = {"n": 0}

        class _Boom:
            class models:
                @staticmethod
                def embed_content(**_kw):
                    calls["n"] += 1
                    raise RuntimeError("429 RESOURCE_EXHAUSTED")

        monkeypatch.setattr(embedder, "_init_gemini_client", lambda: _Boom())
        monkeypatch.setattr(embedder, "_EMBED_RETRY_SLEEP", 0.001)
        reasons = []
        assert embedder._embed_gemini("텍스트", reasons=reasons) is None
        assert calls["n"] == embedder._EMBED_ATTEMPTS
        assert any("429" in r for r in reasons)

    def test_success_on_first_attempt_does_not_retry(self, monkeypatch):
        """음성 대조군 — 성공하면 재시도하지 않는다(불필요한 API 호출 방지).

        스텁 차원을 `get_embed_dim` 에 맞춘다: 반환 벡터는 차원 검사(`_check_dim`)를
        통과해야 하고, 이미 정규화된 값이라 `_normalize_vec` 이 그대로 통과시킨다.
        """
        from workflow.rag import embedder
        calls = {"n": 0}
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 2)

        class _Ok:
            class models:
                @staticmethod
                def embed_content(**_kw):
                    calls["n"] += 1
                    return type("R", (), {"embeddings": [[1.0, 0.0]]})()

        monkeypatch.setattr(embedder, "_init_gemini_client", lambda: _Ok())
        assert embedder._embed_gemini("텍스트") == [1.0, 0.0]
        assert calls["n"] == 1

    def test_malformed_response_is_not_retried(self, monkeypatch):
        """응답 형식 문제는 재시도해도 같다 — 무의미한 API 호출을 3배로 늘리지 않는다."""
        from workflow.rag import embedder
        calls = {"n": 0}

        class _Empty:
            class models:
                @staticmethod
                def embed_content(**_kw):
                    calls["n"] += 1
                    return type("R", (), {"embeddings": []})()

        monkeypatch.setattr(embedder, "_init_gemini_client", lambda: _Empty())
        assert embedder._embed_gemini("텍스트") is None
        assert calls["n"] == 1


# ==============================================================
# 3. 입력 길이 상한 — 자르되 침묵하지 않는다
# ==============================================================

class TestInputClip:
    def test_oversize_input_is_clipped_and_reported(self, monkeypatch):
        """상한 초과를 방치하면 API 거부 → 무작위 벡터가 된다. 자르고 **보고**한다.

        뮤테이션: `_clip_input` 호출을 없애면 사유가 안 남아 실패.
        """
        from workflow.rag import embedder
        monkeypatch.setattr(embedder, "_get_max_input_chars", lambda: 100)
        reasons = []
        out = embedder._clip_input("가" * 500, reasons=reasons)
        assert len(out) == 100
        assert any("input_truncated" in r for r in reasons)

    def test_within_limit_is_untouched(self, monkeypatch):
        from workflow.rag import embedder
        monkeypatch.setattr(embedder, "_get_max_input_chars", lambda: 100)
        reasons = []
        assert embedder._clip_input("짧은 글", reasons=reasons) == "짧은 글"
        assert reasons == []

    def test_zero_limit_disables_clipping(self, monkeypatch):
        """상한 0/음수는 "제한 없음" — 설정 실수로 전부 잘려나가는 사고를 막는다."""
        from workflow.rag import embedder
        monkeypatch.setattr(embedder, "_get_max_input_chars", lambda: 0)
        assert embedder._clip_input("가" * 500) == "가" * 500

    def test_batch_path_uses_the_same_limit(self, monkeypatch):
        """단건과 배치가 다른 상한을 쓰면 같은 텍스트가 경로에 따라 다른 결과를 낸다.

        뮤테이션: 배치의 `_clip_input` 를 없애면 배치가 원문 길이를 넘겨 실패.
        """
        from workflow.rag import embedder
        monkeypatch.setattr(embedder, "_get_max_input_chars", lambda: 10)
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 4)
        seen = {}

        class _Cap:
            class models:
                @staticmethod
                def embed_content(**kw):
                    seen["lens"] = [len(t) for t in kw["contents"]]
                    return type("R", (), {"embeddings": [[0.1] * 4 for _ in kw["contents"]]})()

        monkeypatch.setattr(embedder, "_init_gemini_client", lambda: _Cap())
        embedder._embed_gemini_batch(["가" * 50, "나" * 3])
        assert seen["lens"] == [10, 3]


# ==============================================================
# 4. 폴백 사유가 meta_out 까지
# ==============================================================

class TestFallbackReasons:
    def test_random_fallback_records_every_reason(self, monkeypatch):
        """`degraded=True` 만으로는 운영자가 고칠 수 없다 — 어느 백엔드가 왜 실패했는지.

        뮤테이션: `_note_embed(..., reasons=reasons)` 의 reasons 전달을 없애면 키가 사라져 실패.
        """
        from workflow.rag import embedder
        monkeypatch.setattr(embedder, "_init_gemini_client", lambda: None)
        monkeypatch.delenv("KB_EMBED_URL", raising=False)
        monkeypatch.setattr(embedder, "_st_model_tried", True)
        monkeypatch.setattr(embedder, "_st_model", None)
        meta = {}
        embedder.get_embedding("진단", meta_out=meta)
        assert meta["embed_source"] == "random"
        reasons = meta.get("embed_fallback_reasons") or []
        assert any("gemini" in r for r in reasons)
        assert any("http" in r for r in reasons)
        assert any("local" in r for r in reasons)

    def test_success_path_has_no_reasons_key(self, monkeypatch):
        """음성 대조군 — 정상 경로에 진단 잡음을 붙이지 않는다."""
        from workflow.rag import embedder
        monkeypatch.setattr(embedder, "_embed_gemini",
                            lambda t, reasons=None: [0.5, 0.5])
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 2)
        meta = {}
        embedder.get_embedding("정상", meta_out=meta)
        assert meta["embed_source"] == "gemini"
        assert "embed_fallback_reasons" not in meta


# ==============================================================
# 5. 재인덱싱 — 백엔드가 생겼을 때 기존 벡터를 되살리는 경로
# ==============================================================

def _stub_backend(monkeypatch, dim=4, model="stub"):
    from workflow.rag import embedder
    monkeypatch.setattr(embedder, "_embed_gemini", lambda t, reasons=None: [0.25] * dim)
    monkeypatch.setattr(embedder, "get_embed_dim", lambda: dim)
    monkeypatch.setattr(embedder, "get_embed_model", lambda: model)
    embedder._embed_cache.clear()


def _degrade_backend(monkeypatch):
    from workflow.rag import embedder
    monkeypatch.setattr(embedder, "_embed_gemini", lambda t, reasons=None: None)
    monkeypatch.setattr(embedder, "_embed_http", lambda t, reasons=None: None)
    monkeypatch.setattr(embedder, "_embed_local", lambda t, reasons=None: None)
    embedder._embed_cache.clear()


class TestReindex:
    def test_refuses_when_backend_is_degraded(self, kb_dir, monkeypatch):
        """열화 상태에서 재인덱싱하면 무작위 벡터를 다시 쓸 뿐이다 — 거부하고 사유를 낸다.

        뮤테이션: `if probe.get("degraded") and not force` 가드를 없애면 진행돼 실패.
        """
        from workflow.rag import KnowledgeBase
        _degrade_backend(monkeypatch)
        kb = KnowledgeBase(kb_dir)
        kb.learn("에러 하나", "고쳤다", success=True)
        out = kb.reindex_embeddings()
        assert out["reindexed"] == 0
        assert "열화" in (out["aborted_reason"] or "")

    def test_force_overrides_the_refusal(self, kb_dir, monkeypatch):
        from workflow.rag import KnowledgeBase
        _degrade_backend(monkeypatch)
        kb = KnowledgeBase(kb_dir)
        kb.learn("에러 하나", "고쳤다", success=True)
        out = kb.reindex_embeddings(force=True)
        assert out["aborted_reason"] is None

    def test_reindex_replaces_vectors_and_stamps_provenance(self, kb_dir, monkeypatch):
        """열화 벡터(64차원) → 새 백엔드 차원으로 교체 + 출처 각인.

        뮤테이션: `entry["vector"] = vec` 를 없애면 차원이 그대로라 실패.
        """
        from workflow.rag import KnowledgeBase
        _degrade_backend(monkeypatch)
        kb = KnowledgeBase(kb_dir)
        kb.learn("빌드 실패 abc", "이렇게 고쳤다", success=True)
        assert len(kb.data[-1]["vector"]) == 64
        assert (kb.data[-1]["metadata"]["embed"]).get("degraded") is True

        _stub_backend(monkeypatch, dim=4, model="stub-4")
        out = kb.reindex_embeddings()
        assert out["reindexed"] == 1
        assert len(kb.data[-1]["vector"]) == 4
        prov = kb.data[-1]["metadata"]["embed"]
        assert prov["degraded"] is False
        assert prov["model"] == "stub-4"
        assert prov["text_field"]

    def test_reindex_is_idempotent(self, kb_dir, monkeypatch):
        """두 번째 실행은 전부 skip — 매번 전량 재계산하면 대용량 KB 에서 비용이 폭발한다."""
        from workflow.rag import KnowledgeBase
        _degrade_backend(monkeypatch)
        kb = KnowledgeBase(kb_dir)
        kb.learn("에러 x", "fix x", success=True)
        _stub_backend(monkeypatch, dim=4, model="stub-4")
        assert kb.reindex_embeddings()["reindexed"] == 1
        second = kb.reindex_embeddings()
        assert second["reindexed"] == 0
        assert second["skipped_current"] == 1

    def test_force_reindexes_even_current_entries(self, kb_dir, monkeypatch):
        from workflow.rag import KnowledgeBase
        _stub_backend(monkeypatch, dim=4, model="stub-4")
        kb = KnowledgeBase(kb_dir)
        kb.learn("에러 y", "fix y", success=True)
        assert kb.reindex_embeddings()["reindexed"] == 0        # 이미 최신
        assert kb.reindex_embeddings(force=True)["reindexed"] == 1

    def test_dry_run_writes_nothing(self, kb_dir, monkeypatch):
        from workflow.rag import KnowledgeBase
        _degrade_backend(monkeypatch)
        kb = KnowledgeBase(kb_dir)
        kb.learn("에러 z", "fix z", success=True)
        before = list(kb.data[-1]["vector"])
        _stub_backend(monkeypatch, dim=4, model="stub-4")
        out = kb.reindex_embeddings(dry_run=True)
        assert out["reindexed"] == 1 and out["dry_run"] is True
        assert kb.data[-1]["vector"] == before, "dry-run 이 벡터를 바꿨다"

    def test_legacy_entries_without_text_field_are_counted_not_hidden(self, kb_dir, monkeypatch):
        """구 엔트리는 임베딩 원본 필드 기록이 없어 휴리스틱을 쓴다 — 그 건수를 보고해야 한다.

        뮤테이션: `text_field_guessed` 집계를 없애면 0 이 되어 실패.
        """
        from workflow.rag import KnowledgeBase
        _stub_backend(monkeypatch, dim=4, model="stub-4")
        kb = KnowledgeBase(kb_dir)
        kb.learn("에러 w", "fix w", success=True)
        # 구 엔트리 흉내: text_field 기록 제거
        kb.data[-1]["metadata"]["embed"].pop("text_field", None)
        kb.data[-1]["metadata"]["embed"]["model"] = "old-model"
        out = kb.reindex_embeddings()
        assert out["reindexed"] == 1
        assert out["text_field_guessed"] == 1

    def test_reindex_revives_semantic_search(self, kb_dir, monkeypatch):
        """재인덱싱의 **목적** — 차원 불일치로 전량 제외되던 것이 다시 랭킹된다."""
        from workflow.rag import KnowledgeBase
        from workflow.rag.searcher import semantic_search
        _degrade_backend(monkeypatch)
        kb = KnowledgeBase(kb_dir)
        kb.learn("coverage 미달 원인", "커버리지를 올렸다", success=True)

        _stub_backend(monkeypatch, dim=4, model="stub-4")
        before = {}
        semantic_search([dict(e) for e in kb.data], "coverage", 5, stats_out=before)
        assert before["semantic_skipped_dim_mismatch"] == 1, "재인덱싱 전에는 차원 불일치로 제외"

        kb.reindex_embeddings()
        after = {}
        res = semantic_search([dict(e) for e in kb.data], "coverage", 5, stats_out=after)
        assert after["semantic_skipped_dim_mismatch"] == 0
        assert len(res) == 1, "재인덱싱 후 랭킹에 들어와야 한다"

    def test_limit_caps_the_work(self, kb_dir, monkeypatch):
        from workflow.rag import KnowledgeBase
        _degrade_backend(monkeypatch)
        kb = KnowledgeBase(kb_dir)
        for i in range(4):
            kb.learn(f"에러 {i}", f"fix {i}", success=True)
        _stub_backend(monkeypatch, dim=4, model="stub-4")
        assert kb.reindex_embeddings(limit=2)["reindexed"] == 2


# ==============================================================
# 6. 진단이 사용자에게 도달하는 배선
# ==============================================================

class TestDiagnosticWiring:
    def test_kb_search_exposes_stats_out(self, kb_dir, monkeypatch):
        """`KnowledgeBase.search(stats_out=...)` — 진단이 소비처까지 가는 첫 관문.

        뮤테이션: `hybrid_search(..., stats_out=stats_out)` 전달을 없애면 키가 없어 실패.
        """
        from workflow.rag import KnowledgeBase
        _degrade_backend(monkeypatch)
        kb = KnowledgeBase(kb_dir)
        kb.learn("coverage 미달", "고쳤다", success=True)
        stats = {}
        kb.search("coverage 미달", top_k=3, stats_out=stats)
        assert str(stats.get("semantic_disabled_reason") or "").startswith(
            "degraded_query_embedding")

    def test_report_hits_turns_reason_into_human_note(self, kb_dir, monkeypatch):
        """사유 문자열이 사용자에게 보일 문장으로 변환돼야 한다.

        뮤테이션: `notes_out.append(_semantic_note(...))` 를 없애면 notes 가 비어 실패.
        """
        from workflow.rag import KnowledgeBase
        from workflow.retrieval import hybrid
        _degrade_backend(monkeypatch)
        kb = KnowledgeBase(kb_dir)
        kb.learn("coverage 미달", "고쳤다", success=True)
        monkeypatch.setattr(hybrid, "get_kb", lambda _d: kb)
        notes = []
        hybrid._report_hits("coverage 미달", kb_dir, top_k=3, notes_out=notes)
        assert notes and "시맨틱" in notes[0]
        assert "키워드 검색만" in notes[0]

    def test_healthy_search_produces_no_note(self, kb_dir, monkeypatch):
        """음성 대조군 — 정상 동작 시 경고를 띄우면 경고가 무의미해진다."""
        from workflow.rag import KnowledgeBase
        from workflow.retrieval import hybrid
        _stub_backend(monkeypatch, dim=4, model="stub-4")
        kb = KnowledgeBase(kb_dir)
        kb.learn("coverage 미달", "고쳤다", success=True)
        monkeypatch.setattr(hybrid, "get_kb", lambda _d: kb)
        notes = []
        hybrid._report_hits("coverage 미달", kb_dir, top_k=3, notes_out=notes)
        assert notes == []

    def test_kb_search_failure_is_logged_not_swallowed(self, kb_dir, monkeypatch, caplog):
        """검색이 죽어도 `[]` 만 돌려주면 "근거 없음" 과 구분되지 않는다.

        뮤테이션: `_logger.warning(...)` 를 없애면 로그가 없어 실패.
        """
        import logging

        from workflow.retrieval import hybrid

        class _Boom:
            def search(self, *_a, **_k):
                raise RuntimeError("kb broke")

        monkeypatch.setattr(hybrid, "get_kb", lambda _d: _Boom())
        with caplog.at_level(logging.WARNING, logger="workflow.retrieval.hybrid"):
            assert hybrid._report_hits("q", kb_dir, top_k=3) == []
        assert any("KB 검색 실패" in r.message for r in caplog.records)

    def test_semantic_note_covers_known_reasons(self):
        """사유 종류마다 다른 안내를 낸다 — 하나로 뭉치면 조치 방법을 알 수 없다."""
        from workflow.retrieval.hybrid import _semantic_note
        degraded = _semantic_note("degraded_query_embedding:random")
        alpha = _semantic_note("alpha=0 (keyword only)")
        other = _semantic_note("something_else")
        assert "GEMINI_API_KEY" in degraded
        assert "키워드 전용 설정" in alpha
        assert "something_else" in other
        assert len({degraded, alpha, other}) == 3
