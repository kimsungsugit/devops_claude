"""`_resolve_req_doc_sets` — 저장소 `docs/` 문서가 남의 프로젝트에 섞이지 않는지.

`_discover_default_req_docs()` 는 저장소 `docs/*.docx` 를 글롭한다(현재 HDPDM01 SDS).
예전 구현은 사용자가 준 경로에 그 결과를 **무조건 이어붙였다**:

    req_paths = user_req + defaults["req"]
    sds_paths = user_sds + defaults["sds"]

`enrich_function_details_with_docs` 의 SDS 병합은 first-wins 라, 사용자 문서가 빈칸인
항목을 뒤에 붙은 HDPDM01 의 `asil`·`related` 가 채우고, 사용자 문서에 없는 함수는
HDPDM01 엔트리가 통째로 들어온다.

실측(KJPDS02 SwDS ↔ 저장소 HDPDM01 SwDS): 함수 엔트리 **473개(80.9%)가 이름 충돌**,
그 **전부**가 HDPDM01 쪽에 asil·related 보유. ISO 26262 산출물에 다른 프로젝트의
안전등급·요구ID 가 섞이는 경로였다.

같은 규율이 `_doc_or_discovered`(SRS)와 `generators/suts.py` `load_sds_map_from`
(커밋 `1bfdee9`)에 이미 있었다 — 여기만 빠져 있었다.

(R66) 아무것도 주지 않았을 때 쓰던 저장소 글롭(`_discover_default_req_docs`)도 지웠다 — 대상 프로젝트가 무엇이든 HDPDM01
문서의 ASIL · 요구 ID 가 함수 상세에 들어갔다. 아래 fixture 는 그 함수가 되살아나도 결과에 안 섞이는지 보려고 같은 이름을
심는다(`raising=False`).
"""
from __future__ import annotations

import pytest

from backend.routers import local as local_mod

REPO_SDS = r"D:\repo\docs\(HDPDM01_SDS) Software Architecture Design Specification.docx"
REPO_SRS = r"D:\repo\docs\(HDPDM01_SRS) Software Requirements Specification.docx"


@pytest.fixture
def repo_defaults(monkeypatch):
    """저장소 docs/ 글롭이 항상 HDPDM01 을 내놓는 상태를 고정."""
    monkeypatch.setattr(local_mod, "_discover_default_req_docs",
                        lambda: {"req": [REPO_SRS, REPO_SDS], "sds": [REPO_SDS]}, raising=False)


def test_user_sds_is_not_polluted_by_repo_docs(repo_defaults):
    """핵심 — 사용자가 SDS 를 주면 저장소 문서는 붙지 않는다."""
    req, sds = local_mod._resolve_req_doc_sets(
        req_doc_paths=[r"U:\proj\KJPDS02_SwRS.docx"],
        sds_doc_paths=[r"U:\proj\KJPDS02_SwDS.docx"])
    assert sds == [r"U:\proj\KJPDS02_SwDS.docx"]
    assert REPO_SDS not in sds and REPO_SDS not in req
    assert REPO_SRS not in req


def test_sds_derived_from_req_paths_like_jenkins(repo_defaults):
    """요구 문서 목록에 'sds' 이름 파일이 있으면 그걸 SDS 로 쓴다(Jenkins 경로와 동일 규칙)."""
    req, sds = local_mod._resolve_req_doc_sets(
        req_doc_paths=[r"U:\proj\KJPDS02_SwRS.docx", r"U:\proj\KJPDS02_SwDS.docx"])
    assert sds == [r"U:\proj\KJPDS02_SwDS.docx"]
    assert REPO_SDS not in sds


def test_no_repo_sds_when_user_gave_req_only(repo_defaults, caplog):
    """SDS 를 못 찾으면 **비운다** — 저장소 문서로 채우지 않는다. 다만 침묵하지 않는다."""
    import logging
    with caplog.at_level(logging.WARNING):
        req, sds = local_mod._resolve_req_doc_sets(req_doc_paths=[r"U:\proj\KJPDS02_SwRS.docx"])
    assert sds == []
    assert REPO_SDS not in req
    assert any("오염" in r.message or "대체하지 않는다" in r.message for r in caplog.records), \
        "SDS 가 비었는데 아무 기록도 남기지 않았다"


def test_nothing_supplied_means_no_documents(repo_defaults, caplog):
    """(R66) 아무것도 안 주면 **아무 문서도 없다** — 예전엔 저장소 docs/ 의 HDPDM01 SRS · SDS 였다. 침묵하지는 않는다."""
    import logging
    with caplog.at_level(logging.WARNING):
        req, sds = local_mod._resolve_req_doc_sets()
    assert (req, sds) == ([], [])
    assert any("대체하지 않는다" in r.message for r in caplog.records)


@pytest.mark.parametrize("req_arg,sds_arg", [
    ([""], None), (None, [""]), ([" "], [""]), ([], []),
])
def test_blank_entries_do_not_count_as_user_supplied(repo_defaults, req_arg, sds_arg):
    """공백 문자열은 '사용자가 줬다'로 세지 않는다 — 그리고 (R66) 아무것도 안 준 것은 아무 문서도 없는 것이다."""
    req, sds = local_mod._resolve_req_doc_sets(req_doc_paths=req_arg, sds_doc_paths=sds_arg)
    assert (req, sds) == ([], [])


def test_structure_guard_no_unconditional_append():
    """구조 가드 — `user + defaults` 무조건 이어붙이기가 되살아나면 잡는다."""
    from tests.unit._source_probe import source_of
    src = source_of(local_mod._resolve_req_doc_sets)
    for bad in ('list(req_doc_paths or []) + list(defaults',
                'list(sds_doc_paths or []) + list(defaults'):
        assert bad not in src, f"저장소 docs/ 무조건 병합이 되살아났다: {bad!r}"
