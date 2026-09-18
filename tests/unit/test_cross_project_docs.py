# -*- coding: utf-8 -*-
"""cross-project 증거 결합 탐지 — 남의 프로젝트 문서가 등록돼 있는가 (인계 P5).

## 왜 필요한가

존재 확인만으로는 이걸 못 본다. 실측(2026-08-07): `hdpdm01` 항목의 `uds` 가
`(KJPDS02_SwUDS)…` 였는데, 파일이 없어서 감사에 **"파일 없음"으로만** 보고됐다 —
진짜 문제가 가려진 것이다. 파일이 있었다면 다른 프로젝트의 설계서가 이 프로젝트의
추적성 증거로 조용히 들어가고, ISO 26262 산출물에서 그건 되돌리기 어렵다.

같은 사고를 저장소가 이미 두 번 고쳤다 — `_pick_doc_path` 의 저장소 `docs/` 바꿔치기,
SUTS ASIL 이 HDPDM01 로 채워지던 건. 여기는 **등록 단계**라 그보다 앞이다.

## 고정하는 계약

  A. 판정은 `report_gen/doc_kind` **단일 구현** — `docx_builder` 는 별칭만 갖는다
  B. **판정 불가(None)를 '확인됨'으로 접지 않는다** (fail-closed)
  C. 문서 종류·범용 명사는 프로젝트 식별자가 아니다 (`reference.docx` → 확인 불가)
  D. 라이브 레지스트리 실측: 문서 41건 중 **탐지 1 · 오탐 0**
"""
from __future__ import annotations

import pytest

from report_gen.doc_kind import (
    PROJECT_TOKEN_STOPWORDS,
    cross_project_verdict,
    project_tokens,
)

# ── A — 단일 구현 ──────────────────────────────────────────────────────────

def test_docx_builder_는_사본이_아니라_별칭이다():
    """사본을 두면 이 저장소 단골인 '한쪽만 수정'이 된다."""
    from report_gen import docx_builder as db

    assert db._project_tokens is project_tokens
    assert db._REF_TOKEN_STOPWORDS is PROJECT_TOKEN_STOPWORDS


def test_참조_SUDS_판정도_같은_구현을_탄다():
    """`_reference_identity_verdict` 가 별도 토큰 규칙을 갖지 않는다."""
    from pathlib import Path

    from report_gen.docx_builder import _reference_identity_verdict

    v = _reference_identity_verdict(
        {"project_name": "KJPDS02_PV"}, Path("(HDPDM01_SUDS) Unit Design.docx"))
    assert v["same_project"] is False


# ── 토큰 추출 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("text", "expect"), [
    ("(KJPDS02_SwUDS) Software Unit Design Specification_v2.08", {"KJPDS02"}),
    ("(HDPDM01_SUDS) Unit Design", {"HDPDM01"}),
    ("NE_GN7 SRS", set()),                    # 5자 미만 토큰은 식별자로 안 본다
    ("", set()),
])
def test_토큰_추출(text, expect):
    assert project_tokens(text) == expect


def test_문서종류_어휘는_식별자가_아니다():
    """`SPECIFICATION`·`SOFTWARE` 가 프로젝트 ID 가 되면 전 문서가 서로 '같은 프로젝트'가 된다."""
    assert project_tokens("Software Unit Design Specification Document Report") == set()


# ── B·C — 판정 불가를 확인됨으로 접지 않는다 ──────────────────────────────

def test_같은_프로젝트면_True():
    v = cross_project_verdict(["kjpds02_pv", "KJPDS02_PV"],
                              "(KJPDS02_SwUDS) Unit Design_v3.02.docx")
    assert v["same_project"] is True and v["reason"] == "token_match"


def test_다른_프로젝트면_False():
    v = cross_project_verdict(["hdpdm01", "HDPDM01 PDS_64_RD"],
                              "(KJPDS02_SwUDS) Unit Design_v2.08.docx")
    assert v["same_project"] is False and v["reason"] == "token_mismatch"
    assert v["doc_tokens"] == ["KJPDS02"]


def test_문서에_토큰이_없으면_판정불가(tmp_path):
    """⚠ `reference.docx` 를 '다른 프로젝트'로 **확정**하면 멀쩡한 문서가 차단된다."""
    v = cross_project_verdict(["hdpdm01"], "reference.docx")
    assert v["same_project"] is None and v["reason"] == "doc_no_token"


def test_항목에_토큰이_없으면_판정불가():
    """신원을 모르는데 '다르다'고 단정하지 않는다."""
    v = cross_project_verdict(["", "  "], "(KJPDS02_SwUDS) Unit Design.docx")
    assert v["same_project"] is None and v["reason"] == "owner_no_token"


def test_판정불가는_False와_구분된다():
    """`None` 을 falsy 로 뭉개면 '확인 못 함'이 '다른 프로젝트'가 된다(반대도 마찬가지)."""
    unknown = cross_project_verdict(["hdpdm01"], "reference.docx")["same_project"]
    foreign = cross_project_verdict(["hdpdm01"], "(KJPDS02_X) a.docx")["same_project"]
    assert unknown is None and foreign is False
    assert unknown is not foreign


def test_경로여도_파일명으로_판정한다():
    """상위 폴더에 프로젝트명이 섞여 있어도 문서 자체의 신원을 본다."""
    v = cross_project_verdict(["hdpdm01"], "U:/x/04 KJPDS02/y/(KJPDS02_SwUDS) a.docx")
    assert v["same_project"] is False


# ── 엔드포인트 배선 ────────────────────────────────────────────────────────

def _entry(**kw):
    base = {"id": "hdpdm01", "name": "HDPDM01 PDS_64_RD", "source_root": "", "scm_url": ""}
    base.update(kw)
    return base


class _AlwaysExists:
    def exists(self, _p):
        return True          # 존재는 정상 — 그래도 타 프로젝트는 잡혀야 한다


@pytest.fixture()
def audit_script():
    """`scripts/check_linked_docs.py` 를 로드해 `audit` 을 준다.

    ⚠ 이 스크립트는 **import 시점에 `sys.stdout` 을 재바인딩**한다(Windows 한글 출력용,
    `:47-48`). 그대로 두면 pytest 의 capsys 가 출력을 못 보고, 더 나쁘게는 **다음 테스트까지
    stdout 이 바뀐 채로 남는다**. 원래 값을 저장했다 복원한다 — 특정 값으로 고정하지 않는다.
    """
    import importlib.util
    import io
    import sys
    from pathlib import Path

    saved = sys.stdout
    # ⚠ 스크립트를 **그냥 import 하면 안 된다**. `hasattr(sys.stdout, "buffer")` 가 참이면
    #   pytest 가 물려 준 스트림의 buffer 를 TextIOWrapper 로 감싸는데, 그 wrapper 가
    #   GC 될 때 **버퍼까지 닫아** 이후 테스트가 전부
    #   `ValueError: I/O operation on closed file` 로 죽는다(실제로 6건이 깨졌다).
    #   `buffer` 가 없는 StringIO 를 미리 끼워 두면 스크립트가 재바인딩을 건너뛴다.
    sys.stdout = io.StringIO()
    try:
        spec = importlib.util.spec_from_file_location(
            "_chk_linked_docs",
            Path(__file__).resolve().parents[2] / "scripts" / "check_linked_docs.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        yield mod
    finally:
        sys.stdout = saved


def _run_audit(mod, entries) -> tuple[int, str]:
    """`audit` 을 돌리고 (문제수, 출력) 을 준다. print 는 호출 시점 sys.stdout 을 본다."""
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        problems = mod.audit(_AlwaysExists(), entries)
    return problems, buf.getvalue()


def test_감사_스크립트가_타프로젝트를_별도로_센다(audit_script):
    """'파일 없음'과 '남의 프로젝트'는 **다른 문제**다 — 하나로 뭉개면 후자가 가려진다."""
    entries = [{**_entry(), "linked_docs": {"uds": "(KJPDS02_SwUDS) Unit Design.docx"}}]
    problems, out = _run_audit(audit_script, entries)
    assert problems == 1, "존재하는데 타 프로젝트인 건을 문제로 안 셌다"
    assert "타 프로젝트 1건" in out
    assert "KJPDS02" in out, "어느 토큰 때문인지 안 알려준다"


def test_감사_스크립트가_같은_프로젝트는_통과시킨다(audit_script):
    entries = [{**_entry(id="kjpds02_pv", name="KJPDS02_PV"),
                "linked_docs": {"uds": "(KJPDS02_SwUDS) Unit Design.docx"}}]
    problems, out = _run_audit(audit_script, entries)
    assert problems == 0
    assert "전부 확인됨" in out


class _FakeLinked:
    def __init__(self, mapping):
        self._m = mapping

    def model_dump(self, mode="json"):   # noqa: ARG002 — 시그니처만 맞춘다
        return dict(self._m)


class _FakeEntry:
    def __init__(self, eid, name, mapping):
        self.id = eid
        self.name = name
        self.source_root = ""
        self.scm_url = ""
        self.linked_docs = _FakeLinked(mapping)


@pytest.fixture()
def endpoint(monkeypatch):
    """`scm_linked_docs_status` 를 HTTP 없이 직접 부른다(인증 우회 — 판정 로직만 본다)."""
    from backend.routers import scm as scm_mod
    from backend.services import file_resolver as fr

    class _R:
        def exists(self, _p):
            return True

    monkeypatch.setattr(fr, "get_resolver", lambda: _R())

    def _call(eid, name, mapping):
        monkeypatch.setattr(scm_mod, "get_registry_entry",
                            lambda _i: _FakeEntry(eid, name, mapping))
        return scm_mod.scm_linked_docs_status(eid)

    return _call


def test_endpoint_가_문서별_신원을_실제로_싣는다(endpoint):
    """⚠ 소스 문자열 검사로는 부족하다 — 배선을 지워도 문자열이 남아 통과한다
    (뮤테이션 M7 이 그래서 생존했다). 응답 값을 단언한다.
    """
    out = endpoint("hdpdm01", "HDPDM01 PDS_64_RD",
                   {"uds": "(KJPDS02_SwUDS) Unit Design.docx",
                    "srs": "(HDPDM01_SwRS) Requirements.docx"})
    assert out["items"]["uds"]["same_project"] is False, "타 프로젝트 문서를 안 잡았다"
    assert out["items"]["srs"]["same_project"] is True
    assert out["foreign_project_keys"] == ["uds"]
    # 존재 확인 결과가 사라지지 않았는지(둘을 합쳐 싣는다)
    assert out["items"]["uds"]["exists"] is True


def test_endpoint_같은_프로젝트면_foreign_이_비어있다(endpoint):
    out = endpoint("kjpds02_pv", "KJPDS02_PV",
                   {"uds": "(KJPDS02_SwUDS) Unit Design.docx"})
    assert out["foreign_project_keys"] == []
    assert out["items"]["uds"]["same_project"] is True


def test_endpoint_목록형_문서도_센다(endpoint):
    """`vectorcast` 처럼 경로 배열인 키도 타 프로젝트를 집계해야 한다."""
    out = endpoint("hdpdm01", "HDPDM01",
                   {"vectorcast": ["U:/a/(KJPDS02_X) log", "U:/b/(HDPDM01_Y) log"]})
    assert out["items"]["vectorcast"]["foreign_project"] == 1
    assert out["foreign_project_keys"] == ["vectorcast"]
