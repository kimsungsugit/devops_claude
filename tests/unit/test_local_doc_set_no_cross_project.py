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
                        lambda: {"req": [REPO_SRS, REPO_SDS], "sds": [REPO_SDS]})


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


def test_defaults_still_used_when_nothing_supplied(repo_defaults):
    """폴백은 유지 — 아무것도 안 주면 저장소 docs/ 를 쓴다(동봉 샘플 데모 경로)."""
    req, sds = local_mod._resolve_req_doc_sets()
    assert sds == [REPO_SDS]
    assert req == [REPO_SRS, REPO_SDS]


@pytest.mark.parametrize("req_arg,sds_arg", [
    ([""], None), (None, [""]), ([" "], [""]), ([], []),
])
def test_blank_entries_do_not_count_as_user_supplied(repo_defaults, req_arg, sds_arg):
    """공백 문자열은 '사용자가 줬다'로 세지 않는다 — 안 그러면 폴백이 죽는다."""
    req, sds = local_mod._resolve_req_doc_sets(req_doc_paths=req_arg, sds_doc_paths=sds_arg)
    assert sds == [REPO_SDS]


def test_structure_guard_no_unconditional_append():
    """구조 가드 — `user + defaults` 무조건 이어붙이기가 되살아나면 잡는다."""
    import inspect
    src = inspect.getsource(local_mod._resolve_req_doc_sets)
    for bad in ('list(req_doc_paths or []) + list(defaults',
                'list(sds_doc_paths or []) + list(defaults'):
        assert bad not in src, f"저장소 docs/ 무조건 병합이 되살아났다: {bad!r}"
