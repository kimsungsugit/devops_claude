"""UDS 문서 RAG Description 보강 게이트 회귀 (R3).

과거 docx_builder 의 RAG 보강이 존재하지 않는 _kb.load() 호출로 AttributeError 가
나며 영구 dead 였다. 이를 제거하고, ASIL 문서 출력 변경을 막기 위해 기본 off 게이트
(UDS_RAG_DESC_ENRICH)로 opt-in 화했다.
"""
from __future__ import annotations

import inspect


def test_uds_rag_enrich_default_off(monkeypatch):
    import importlib

    import config
    # env 가 켜져 있어도 '기본값이 off' 임을 결정적으로 검증(env 격리 후 reload)
    monkeypatch.delenv("UDS_RAG_DESC_ENRICH", raising=False)
    importlib.reload(config)
    assert getattr(config, "UDS_RAG_DESC_ENRICH", None) is False


def test_knowledgebase_has_no_load_method():
    """KnowledgeBase 는 public load() 가 없다(__init__ 의 _load_all 이 로드).

    과거 docx_builder 가 호출하던 _kb.load() 는 처음부터 존재하지 않는 메서드였다.
    """
    from workflow.rag import KnowledgeBase
    assert not hasattr(KnowledgeBase, "load")


def test_docx_builder_rag_block_fixed_and_gated():
    """generate_uds_docx 의 RAG 보강 블록이 dead 호출 제거 + 게이트 적용 상태인지."""
    import report_gen.docx_builder as db
    src = inspect.getsource(db.generate_uds_docx)
    # 1) 존재하지 않는 메서드 호출 제거(회귀 방지)
    assert "_kb.load()" not in src
    # 2) 보강 경로 자체는 유지(KnowledgeBase 사용)
    assert "KnowledgeBase" in src
    # 3) 기본 off 게이트가 적용됨
    assert "UDS_RAG_DESC_ENRICH" in src
    # 4) KB 결과를 올바른 스키마 키(context/fix)로 읽음 — 과거 text/content 는 항상 빈값
    assert 'r.get("text")' not in src
    assert ('r.get("context")' in src) or ('r.get("fix")' in src)


def test_docx_builder_imports_clean():
    """모듈이 깨끗이 import 되는지(구문/이름 회귀 방지)."""
    import importlib

    import report_gen.docx_builder as db
    importlib.reload(db)
    assert callable(db.generate_uds_docx)
