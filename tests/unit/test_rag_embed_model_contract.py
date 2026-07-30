# tests/unit/test_rag_embed_model_contract.py
"""임베딩 백엔드 계약 — 모델명 / 응답 언팩 / 차원.

## 이 파일이 생긴 이유 (2026-07-30 실측)

앞선 라운드에서 "KB 벡터가 전부 난수" 의 원인을 **키 미해석**으로 잡고 고쳤다
(`resolve_google_api_key`). 그 fix 로 클라이언트는 뜨는데 KB 는 **여전히 난수**였다.
`reindex_embeddings` 의 fail-closed 가드가 재인덱싱을 거부하면서 진짜 이유가 드러났다:

| # | 결함 | 실측 |
|---|------|------|
| E1 | 모델명 `text-embedding-004` 가 v1beta 에서 **삭제**됨 | 404 NOT_FOUND. 살아 있는 건 `gemini-embedding-001` / `gemini-embedding-2(-preview)` 뿐 |
| E2 | 신 SDK 응답 언팩이 틀림 | `response.embeddings[0]` 는 pydantic `ContentEmbedding`. `__iter__` 가 `('values', [...])` **튜플**을 낸다 → `[float(v) for v in emb]` = TypeError |
| E3 | 차원 불일치 | `gemini-embedding-001` native = **3072**, 설정 = 768 |

**세 결함은 층으로 겹쳐 있었다.** E1 만 고치면 E2 가 조용히 이어받아 결과는 그대로 난수다
(TypeError → `except Exception` → 재시도 3회 → 폴백 → random). E2 까지 고쳐도 E3 때문에
`_cache_put` 이 모든 벡터의 캐시를 거부하고 pgvector `VECTOR(768)` 삽입이 실패한다.

E2 는 **단건·배치 두 곳에 복제**돼 있었다(이 저장소가 반복해 겪은 실패 모드 —
한쪽만 고치면 나머지가 잠복). 그래서 언팩·정규화·차원검사를 단일 함수로 두고,
그 단일성 자체를 계약 테스트로 고정한다.

부수 실측: MRL 절단 벡터는 정규화가 깨져서 온다 — 3072 는 L2=1.000000 이지만
768 절단은 0.585940, 1536 은 0.689938.
"""
from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest

from workflow.rag import embedder

_EMBEDDER_SRC = Path(embedder.__file__)


# --------------------------------------------------------------
# E1 — 모델명이 죽은 값이 아니어야 하고, 설정 표면에 있어야 한다
# --------------------------------------------------------------

class TestModelName:
    def test_default_model_is_not_the_removed_one(self):
        """뮤테이션: 기본값을 `text-embedding-004` 로 되돌리면 실패.

        이 모델은 v1beta 에서 제거됐다(404). 하드코딩된 채로 죽어 있어도 어떤 표면에도
        안 나타났고, 404 는 폴백 체인이 흡수해 KB 전체가 난수가 됐다.
        """
        assert embedder._DEFAULT_EMBED_MODEL != "text-embedding-004"
        assert embedder.get_embed_model() != "text-embedding-004"

    def test_model_and_dim_are_config_surfaced(self):
        """모델·차원은 config 에 있어야 한다 — 모듈 내부 하드코딩만이면 아무도 못 본다."""
        import config
        assert isinstance(getattr(config, "RAG_EMBED_MODEL", None), str)
        assert str(getattr(config, "RAG_EMBED_MODEL")).strip()
        assert int(getattr(config, "RAG_EMBED_DIM")) > 0

    def test_config_overrides_module_default(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "RAG_EMBED_MODEL", "some-other-model", raising=False)
        monkeypatch.setattr(config, "RAG_EMBED_DIM", 1536, raising=False)
        assert embedder.get_embed_model() == "some-other-model"
        assert embedder.get_embed_dim() == 1536

    def test_request_config_pins_output_dimensionality(self):
        """차원을 명시하지 않으면 native(3072) 가 와서 설정(768)과 어긋난다.

        뮤테이션: `output_dimensionality` 키를 빼면 실패.
        """
        cfg = embedder._embed_request_config()
        assert cfg["output_dimensionality"] == embedder.get_embed_dim()
        assert cfg["task_type"] == "RETRIEVAL_DOCUMENT"


# --------------------------------------------------------------
# E2 — pydantic 응답 언팩
# --------------------------------------------------------------

class _ContentEmbeddingLike:
    """실제 `google.genai.types.ContentEmbedding` 의 결정적 성질만 재현한다.

    핵심: **`__iter__` 가 값이 아니라 `(필드명, 값)` 튜플을 낸다**(pydantic BaseModel).
    이 성질이 없으면 옛 코드의 결함을 재현할 수 없어 테스트가 무의미해진다.
    """

    def __init__(self, values):
        self.values = list(values)
        self.statistics = None

    def __iter__(self):
        yield ("values", self.values)
        yield ("statistics", self.statistics)


class TestResponseUnpack:
    def test_stub_reproduces_the_old_failure(self):
        """대조군 — 스텁이 진짜 결함을 재현하는지 먼저 확인한다.

        이게 통과하지 않으면 아래 테스트들은 존재하지 않는 버그를 막는 셈이 된다.
        """
        obj = _ContentEmbeddingLike([0.1, 0.2])
        with pytest.raises(TypeError):
            [float(v) for v in obj]  # type: ignore[arg-type]  # ← 옛 코드 그대로(고의)

    def test_coerce_reads_values_attribute(self):
        """뮤테이션: `_coerce_embedding_values` 를 `[float(v) for v in obj]` 로 되돌리면 실패."""
        out = embedder._coerce_embedding_values(_ContentEmbeddingLike([0.1, 0.2, 0.3]))
        assert out == [0.1, 0.2, 0.3]

    def test_coerce_accepts_plain_list(self):
        """구 SDK/HTTP 백엔드는 순수 list 를 준다 — 둘 다 받아야 한다."""
        assert embedder._coerce_embedding_values([1.0, 2.0]) == [1.0, 2.0]

    def test_coerce_accepts_dict_shape(self):
        assert embedder._coerce_embedding_values({"values": [1.0, 2.0]}) == [1.0, 2.0]

    @pytest.mark.parametrize("bad", [None, [], {"values": []}, "문자열", 42])
    def test_coerce_returns_none_on_unusable(self, bad):
        """언팩 불가는 **None** — 예외로 터뜨려 재시도를 3배 태우지 않는다."""
        assert embedder._coerce_embedding_values(bad) is None

    def test_coerce_does_not_swallow_a_real_vector_of_zeros(self):
        """음성 대조군 — 값이 0.0 뿐이어도 유효한 벡터다(빈 것과 구분)."""
        assert embedder._coerce_embedding_values([0.0, 0.0]) == [0.0, 0.0]

    def test_single_path_unpacks_pydantic_response(self, monkeypatch):
        """단건 경로 통합 — 스텁이 ContentEmbedding 을 줘도 벡터가 나와야 한다."""
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 2)

        class _Client:
            class models:
                @staticmethod
                def embed_content(**_kw):
                    return type("R", (), {"embeddings": [_ContentEmbeddingLike([1.0, 0.0])]})()

        monkeypatch.setattr(embedder, "_init_gemini_client", lambda: _Client())
        assert embedder._embed_gemini("텍스트") == [1.0, 0.0]

    def test_batch_path_unpacks_pydantic_response(self, monkeypatch):
        """배치 경로 — 같은 결함이 복제돼 있었다. 여기서도 나와야 한다."""
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 2)

        class _Client:
            class models:
                @staticmethod
                def embed_content(**kw):
                    n = len(kw["contents"])
                    return type("R", (), {
                        "embeddings": [_ContentEmbeddingLike([1.0, 0.0]) for _ in range(n)]
                    })()

        monkeypatch.setattr(embedder, "_init_gemini_client", lambda: _Client())
        assert embedder._embed_gemini_batch(["a", "b"]) == [[1.0, 0.0], [1.0, 0.0]]

    def test_batch_falls_back_wholesale_when_one_entry_is_unusable(self, monkeypatch):
        """부분 성공을 반쪽 배치로 돌려주면 호출자가 인덱스 정렬을 잃는다 — 전체 폴백."""
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 2)

        class _Client:
            class models:
                @staticmethod
                def embed_content(**_kw):
                    return type("R", (), {
                        "embeddings": [_ContentEmbeddingLike([1.0, 0.0]), None]
                    })()

        monkeypatch.setattr(embedder, "_init_gemini_client", lambda: _Client())
        assert embedder._embed_gemini_batch(["a", "b"]) is None


class TestUnpackIsSingleSourced:
    """언팩이 다시 복제되는 것을 막는다.

    E2 가 단건·배치 두 곳에 복제돼 있어 **양쪽 다 같은 방식으로 깨져** 있었다.
    한쪽만 고치면 나머지가 잠복하므로 복제 자체를 금지한다.
    """

    def test_both_gemini_paths_call_the_shared_coercer(self):
        tree = ast.parse(_EMBEDDER_SRC.read_text(encoding="utf-8"))
        for fn_name in ("_embed_gemini", "_embed_gemini_batch"):
            fn = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef) and n.name == fn_name)
            called = {n.func.id for n in ast.walk(fn)
                      if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            assert "_coerce_embedding_values" in called, f"{fn_name} 가 공용 언팩을 안 쓴다"
            assert "_check_dim" in called, f"{fn_name} 가 차원 검사를 안 한다"

    def test_no_raw_float_comprehension_over_embedding_objects(self):
        """`[float(v) for v in <emb-ish>]` 패턴이 gemini 경로에 재등장하지 않아야 한다."""
        tree = ast.parse(_EMBEDDER_SRC.read_text(encoding="utf-8"))
        offenders = []
        for fn_name in ("_embed_gemini", "_embed_gemini_batch"):
            fn = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef) and n.name == fn_name)
            for node in ast.walk(fn):
                if not isinstance(node, ast.ListComp):
                    continue
                f = node.elt
                if (isinstance(f, ast.Call) and isinstance(f.func, ast.Name)
                        and f.func.id == "float"):
                    offenders.append(f"{fn_name}:{node.lineno}")
        assert not offenders, f"직접 언팩이 되살아났다: {offenders}"


# --------------------------------------------------------------
# E3 — 차원 계약 + 정규화
# --------------------------------------------------------------

class TestDimContract:
    def test_mismatch_is_rejected_not_stored(self, monkeypatch):
        """뮤테이션: `_check_dim` 을 항등함수로 만들면 실패.

        혼합 차원 벡터가 KB 에 들어가면 `cosine_similarity` 가 0.0 을 내고 그 엔트리는
        영구히 검색에서 빠진다 — 그런데 어떤 표면에도 안 나온다. fail-closed 로 막는다.
        """
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 768)
        reasons = []
        assert embedder._check_dim([0.1] * 3072, source="gemini", reasons=reasons) is None
        assert any("dim 3072" in r and "768" in r for r in reasons)

    def test_matching_dim_passes_through_unchanged(self):
        """음성 대조군 — 맞으면 그대로 통과한다(과잉 차단 아님)."""
        vec = [0.0] * embedder.get_embed_dim()
        assert embedder._check_dim(vec, source="gemini") is vec

    def test_mismatch_message_names_both_numbers(self, monkeypatch, caplog):
        """설정 오류는 읽을 수 있어야 한다 — 기대값과 실제값이 둘 다 로그에 있어야 한다."""
        import logging
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 768)
        with caplog.at_level(logging.ERROR, logger="workflow.rag.embedder"):
            embedder._check_dim([0.1] * 384, source="local")
        msg = " ".join(r.message for r in caplog.records)
        assert "768" in msg and "384" in msg and "RAG_EMBED_DIM" in msg


class TestNormalization:
    def test_truncated_vector_is_renormalized(self):
        """MRL 절단 벡터는 L2 가 1 이 아니다(실측 768 절단 = 0.585940).

        뮤테이션: `_normalize_vec` 을 항등함수로 만들면 실패.
        """
        out = embedder._normalize_vec([3.0, 4.0])
        assert math.isclose(math.sqrt(sum(x * x for x in out)), 1.0, rel_tol=1e-9)

    def test_direction_is_preserved(self):
        """정규화는 크기만 바꾼다 — 방향(=의미)이 바뀌면 랭킹이 달라진다."""
        src = [3.0, 4.0]
        out = embedder._normalize_vec(src)
        assert math.isclose(embedder.cosine_similarity(src, out), 1.0, rel_tol=1e-9)

    def test_zero_vector_is_returned_as_is(self):
        """0 벡터는 정규화 불가 — 0 나눗셈으로 NaN 을 만들지 않는다."""
        assert embedder._normalize_vec([0.0, 0.0]) == [0.0, 0.0]

    def test_already_normalized_is_stable(self):
        """음성 대조군 — 두 번 정규화해도 값이 표류하지 않는다."""
        once = embedder._normalize_vec([1.0, 2.0, 3.0])
        twice = embedder._normalize_vec(once)
        assert all(math.isclose(a, b, rel_tol=1e-12) for a, b in zip(once, twice))

    def test_gemini_path_normalizes_before_returning(self, monkeypatch):
        """통합 — 저장 경로에 들어가는 벡터는 이미 정규화돼 있어야 한다."""
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 2)

        class _Client:
            class models:
                @staticmethod
                def embed_content(**_kw):
                    return type("R", (), {"embeddings": [_ContentEmbeddingLike([3.0, 4.0])]})()

        monkeypatch.setattr(embedder, "_init_gemini_client", lambda: _Client())
        out = embedder._embed_gemini("텍스트")
        assert out is not None
        assert math.isclose(math.sqrt(sum(x * x for x in out)), 1.0, rel_tol=1e-9)


class TestSinglePathParity:
    """단건과 배치가 같은 텍스트에 같은 벡터를 내야 한다.

    요청 config 가 갈리면(예: 한쪽만 `output_dimensionality`) 같은 텍스트가 경로에 따라
    다른 차원·다른 정규화로 저장돼 KB 가 조용히 혼합된다.
    """

    def test_both_paths_send_the_same_request_config(self, monkeypatch):
        monkeypatch.setattr(embedder, "get_embed_dim", lambda: 2)
        seen = []

        class _Client:
            class models:
                @staticmethod
                def embed_content(**kw):
                    seen.append(kw.get("config"))
                    n = kw["contents"] if isinstance(kw["contents"], list) else [kw["contents"]]
                    return type("R", (), {
                        "embeddings": [_ContentEmbeddingLike([1.0, 0.0]) for _ in n]
                    })()

        monkeypatch.setattr(embedder, "_init_gemini_client", lambda: _Client())
        embedder._embed_gemini("같은 텍스트")
        embedder._embed_gemini_batch(["같은 텍스트"])
        assert len(seen) == 2
        assert seen[0] == seen[1], f"단건·배치 요청 config 가 다르다: {seen}"
