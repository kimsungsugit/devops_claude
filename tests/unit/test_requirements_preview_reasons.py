"""requirements-preview 가 "왜 못 읽었는지"를 보고하는가 (2026-08-06).

## 사용자 보고

"왜 SRS 문서가 있는데 없어서 매트릭스를 생성할 수 없다고 나오지?"

## 실체

``/api/jenkins/uds/requirements-preview`` 의 요구문서 읽기 루프가 **다섯 갈래 실패를
전부 ``text = ""`` 로 삼켰다** — ①접근 거부 ②파일 없음 ③형식 불허 ④read 실패
⑤본문 추출 실패. 응답은 언제나 ``ok: True`` 라 호출자가 구분할 수 없고, 프론트는
끝에서 "SRS 경로를 확인하세요" 한 문장으로 뭉갠다.

바로 아래 ``compare``/``function_mapping`` 두 블록은 **같은 결함을 이미 고쳐**
사유를 ``errors`` 에 싣는다(그 주석이 "네 상태가 전부 같은 null 이 돼 약 4개월간
묻혔다"고 적고 있다). 정작 그 위 루프는 안 고쳐져 있었다 — 늘 나오는 한쪽만 고침.

실측(KJPDS02, 2026-08-06): ``kjpds02`` 항목은 등록된 문서 11개 중 **8개가 실물
없음**이었고 SRS 는 ``_v2.03_….docx`` 로 등록됐는데 폴더엔 ``_v3.01_…_R.docx``
하나뿐이었다. 즉 "없다"는 판정 자체는 맞았고, **왜인지를 말하지 않은 것**이 결함이다.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

from backend.services.resolver_helpers import (  # noqa: E402
    read_requirement_doc_via_resolver,
    read_uploaded_requirement_doc,
)


# ---------------------------------------------------------------------------
# 업로드 분기 — 경로 분기와 **같은 어휘**로 사유를 낸다
# ---------------------------------------------------------------------------
def test_upload_parse_failure_reports_reason(monkeypatch):
    import workflow.rag.chunker as ck
    monkeypatch.setattr(ck, "_read_text_from_file",
                        lambda p: (_ for _ in ()).throw(ValueError("bad zip")))
    text, reason = read_uploaded_requirement_doc("SRS.docx", b"garbage")
    assert text == ""
    assert "본문 추출 실패" in reason and "SRS.docx" in reason


def test_upload_empty_body_reports_reason(monkeypatch):
    import workflow.rag.chunker as ck
    monkeypatch.setattr(ck, "_read_text_from_file", lambda p: "   ")
    text, reason = read_uploaded_requirement_doc("SRS.docx", b"x")
    assert (text, "본문 0자" in reason) == ("", True)


def test_upload_success_has_no_reason(monkeypatch):
    import workflow.rag.chunker as ck
    monkeypatch.setattr(ck, "_read_text_from_file", lambda p: " 본문 ")
    assert read_uploaded_requirement_doc("SRS.docx", b"x") == ("본문", "")


def test_upload_removes_its_temp_file(monkeypatch):
    """`delete=False` 로 만든 임시 파일을 지운다 — 예전엔 업로드마다 쌓였다."""
    seen: list[Path] = []

    import workflow.rag.chunker as ck

    def _capture(p):
        seen.append(Path(p))
        return "본문"

    monkeypatch.setattr(ck, "_read_text_from_file", _capture)
    read_uploaded_requirement_doc("SRS.docx", b"x")
    assert seen, "파서가 호출되지 않았다"
    assert not seen[0].exists(), f"임시 파일이 남았다: {seen[0]}"


def test_upload_temp_file_removed_even_on_failure(monkeypatch):
    seen: list[Path] = []

    import workflow.rag.chunker as ck

    def _boom(p):
        seen.append(Path(p))
        raise ValueError("bad")

    monkeypatch.setattr(ck, "_read_text_from_file", _boom)
    read_uploaded_requirement_doc("SRS.docx", b"x")
    assert seen and not seen[0].exists(), "실패 경로에서 임시 파일이 남았다"


# ---------------------------------------------------------------------------
# 사유 보고 — 각 갈래가 **다른** 문구를 낸다
# ---------------------------------------------------------------------------
class _FakeResolver:
    def __init__(self, *, exists=True, data=b"x", exc=None):
        self._exists, self._data, self._exc = exists, data, exc

    def exists(self, path):
        if isinstance(self._exists, Exception):
            raise self._exists
        return self._exists

    def read_bytes(self, path):
        if self._exc:
            raise self._exc
        return self._data


@pytest.fixture
def patched(monkeypatch):
    def _apply(resolver, *, access_exc=None, text=""):
        import backend.services.resolver_helpers as rh
        monkeypatch.setattr("backend.services.file_resolver.get_resolver", lambda: resolver)
        if access_exc is not None:
            monkeypatch.setattr(rh, "enforce_resolver_access",
                                lambda p: (_ for _ in ()).throw(access_exc))
        else:
            monkeypatch.setattr(rh, "enforce_resolver_access", lambda p: None)
        import workflow.rag.chunker as ck
        monkeypatch.setattr(ck, "_read_text_from_file", lambda p: text)
    return _apply


def test_empty_path_is_not_an_error(patched):
    patched(_FakeResolver())
    text, reason = read_requirement_doc_via_resolver("")
    assert (text, reason) == ("", "")


def test_missing_file_says_missing(patched):
    patched(_FakeResolver(exists=False))
    text, reason = read_requirement_doc_via_resolver("U:/x/SRS.docx")
    assert text == ""
    assert "파일 없음" in reason
    assert "SRS.docx" in reason, "어느 파일인지 이름이 없으면 사용자가 못 고친다"


def test_access_denied_says_denied(patched):
    from fastapi import HTTPException
    patched(_FakeResolver(), access_exc=HTTPException(status_code=403, detail="차단됨"))
    text, reason = read_requirement_doc_via_resolver("Z:/nope/SRS.docx")
    assert text == ""
    assert "접근 거부" in reason and "차단됨" in reason


def test_disallowed_format_says_format(patched):
    patched(_FakeResolver())
    text, reason = read_requirement_doc_via_resolver(
        "U:/x/SUTS.xlsm", allow=lambda p: p.suffix.lower() == ".docx",
    )
    assert text == ""
    assert "형식" in reason


def test_read_failure_says_read(patched):
    patched(_FakeResolver(exc=OSError("boom")))
    text, reason = read_requirement_doc_via_resolver("U:/x/SRS.docx")
    assert text == ""
    assert "읽기 실패" in reason and "OSError" in reason


def test_empty_body_says_zero_chars(patched):
    patched(_FakeResolver(), text="   ")
    text, reason = read_requirement_doc_via_resolver("U:/x/SRS.docx")
    assert text == ""
    assert "본문 0자" in reason


def test_success_has_no_reason(patched):
    patched(_FakeResolver(), text="  SwRS_01 요구사항  ")
    text, reason = read_requirement_doc_via_resolver("U:/x/SRS.docx")
    assert text == "SwRS_01 요구사항"
    assert reason == ""


def test_every_branch_produces_a_distinct_reason(patched):
    """사유가 서로 달라야 화면에서 갈린다 — 같은 문구면 뭉갠 것과 다를 게 없다."""
    from fastapi import HTTPException
    seen = []

    patched(_FakeResolver(exists=False))
    seen.append(read_requirement_doc_via_resolver("U:/a/S.docx")[1])

    patched(_FakeResolver(), access_exc=HTTPException(status_code=403, detail="d"))
    seen.append(read_requirement_doc_via_resolver("U:/a/S.docx")[1])

    patched(_FakeResolver(exc=OSError("b")))
    seen.append(read_requirement_doc_via_resolver("U:/a/S.docx")[1])

    patched(_FakeResolver(), text="")
    seen.append(read_requirement_doc_via_resolver("U:/a/S.docx")[1])

    patched(_FakeResolver())
    seen.append(read_requirement_doc_via_resolver("U:/a/S.xlsm", allow=lambda _p: False)[1])

    assert all(seen), "빈 사유가 있으면 그 갈래는 여전히 침묵이다"
    assert len(set(seen)) == len(seen), f"사유가 겹친다: {seen}"


# ---------------------------------------------------------------------------
# endpoint 배선 — 손으로 짠 침묵 루프로 되돌아가지 않게
# ---------------------------------------------------------------------------
def _preview_fn() -> ast.AsyncFunctionDef:
    tree = ast.parse((REPO / "backend" / "routers" / "jenkins.py").read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "jenkins_uds_requirements_preview")


def test_endpoint_uses_the_reporting_reader():
    fn = _preview_fn()
    names = {getattr(n.func, "id", "") for n in ast.walk(fn) if isinstance(n, ast.Call)}
    assert "read_requirement_doc_via_resolver" in names, (
        "요구문서 읽기가 사유를 보고하지 않는 손수 짠 루프로 되돌아갔다"
    )


def test_endpoint_returns_req_doc_errors():
    src = ast.unparse(_preview_fn())
    assert "req_doc_errors" in src, "사유를 응답에 싣지 않으면 프론트가 여전히 뭉갠다"


def test_no_silent_swallow_left_in_the_read_loop():
    """`except …: text = ''` 류가 이 함수에 남아 있지 않은지."""
    fn = _preview_fn()
    offenders = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body = node.body
        # 사유를 남기지 않고 값만 비우고 넘어가는 형태
        if len(body) == 1 and isinstance(body[0], ast.Assign):
            tgt = body[0].targets[0]
            if getattr(tgt, "id", "") == "text":
                offenders.append(node.lineno)
    assert not offenders, f"침묵 삼킴이 남아 있다: jenkins.py 라인 {offenders}"


@pytest.mark.parametrize("path_kwargs,expect", [
    ({"req_paths": ""}, "요구사항 문서 경로가 지정되지 않았습니다"),
])
def test_no_path_is_its_own_reason(monkeypatch, path_kwargs, expect):
    """경로 미지정은 "읽었는데 0건"과 전혀 다른 사유다 — 구분해 알린다."""
    from backend.routers import jenkins as J
    monkeypatch.setattr(J, "generate_uds_requirements_preview", lambda t: {"items": []})
    monkeypatch.setattr(J, "generate_uds_requirements_mapping", lambda i: [])
    out = asyncio.run(J.jenkins_uds_requirements_preview(
        req_files=[], source_root="", **path_kwargs,
    ))
    assert expect in " ".join(out.get("req_doc_errors") or [])


def test_path_branch_actually_reports_its_reason(monkeypatch, patched):
    """**경로** 분기가 사유를 응답에 싣는지 — 구조 검사만으로는 부족하다.

    ⚠ 이 테스트가 없을 때, 경로 루프의 사유 수집만 지운 뮤테이션이 **생존**했다:
      `read_requirement_doc_via_resolver` 호출은 그대로 남고 `req_doc_errors` 문자열도
      업로드 분기 덕에 파일에 남아, 두 구조 검사가 모두 통과했다.
    """
    from backend.routers import jenkins as J
    patched(_FakeResolver(exists=False))
    monkeypatch.setattr(J, "generate_uds_requirements_preview", lambda t: {"items": []})
    monkeypatch.setattr(J, "generate_uds_requirements_mapping", lambda i: [])
    out = asyncio.run(J.jenkins_uds_requirements_preview(
        req_files=[], req_paths="U:/proj/01.SwRS/SRS_v2.03.docx", source_root="",
    ))
    errs = out.get("req_doc_errors") or []
    assert errs, "경로를 읽지 못했는데 사유가 응답에 없다 — 프론트가 다시 뭉갠다"
    assert "SRS_v2.03.docx" in " ".join(errs)
    assert "파일 없음" in " ".join(errs)


class _FakeUpload:
    """UploadFile 최소 대역 — endpoint 가 쓰는 `.filename` / `await .read()` 만."""

    def __init__(self, filename: str, data: bytes = b"x"):
        self.filename = filename
        self._data = data

    async def read(self):
        return self._data


def test_upload_branch_reports_its_reason_through_the_endpoint(monkeypatch):
    """**업로드** 분기가 사유를 응답에 싣는지 — 헬퍼 단독 테스트만으론 부족하다.

    ⚠ 이 테스트가 없을 때, endpoint 에서 업로드 사유 수집만 지운 뮤테이션이 **생존**했다.
      헬퍼는 여전히 사유를 돌려주지만 호출부가 버리면 화면엔 아무것도 안 온다.
    """
    import workflow.rag.chunker as ck
    from backend.routers import jenkins as J
    monkeypatch.setattr(ck, "_read_text_from_file",
                        lambda p: (_ for _ in ()).throw(ValueError("bad zip")))
    monkeypatch.setattr(J, "generate_uds_requirements_preview", lambda t: {"items": []})
    monkeypatch.setattr(J, "generate_uds_requirements_mapping", lambda i: [])
    out = asyncio.run(J.jenkins_uds_requirements_preview(
        req_files=[_FakeUpload("SRS_upload.docx")], req_paths="", source_root="",
    ))
    errs = out.get("req_doc_errors") or []
    assert errs, "업로드 파싱이 실패했는데 사유가 응답에 없다"
    assert "SRS_upload.docx" in " ".join(errs)


def test_upload_branch_success_carries_no_error(monkeypatch):
    import workflow.rag.chunker as ck
    from backend.routers import jenkins as J
    monkeypatch.setattr(ck, "_read_text_from_file", lambda p: "SwRS_01 본문")
    monkeypatch.setattr(J, "generate_uds_requirements_preview",
                        lambda t: {"items": [{"id": "SwRS_01"}] if t else []})
    monkeypatch.setattr(J, "generate_uds_requirements_mapping", lambda i: [])
    out = asyncio.run(J.jenkins_uds_requirements_preview(
        req_files=[_FakeUpload("SRS_upload.docx")], req_paths="", source_root="",
    ))
    assert "req_doc_errors" not in out
    assert len((out.get("preview") or {}).get("items") or []) == 1


def test_path_branch_success_carries_no_error(patched, monkeypatch):
    """정상일 땐 사유가 없어야 한다 — 거짓 경보는 진짜 경보를 죽인다."""
    from backend.routers import jenkins as J
    patched(_FakeResolver(), text="SwRS_01 본문")
    monkeypatch.setattr(J, "generate_uds_requirements_preview",
                        lambda t: {"items": [{"id": "SwRS_01"}]})
    monkeypatch.setattr(J, "generate_uds_requirements_mapping", lambda i: [])
    out = asyncio.run(J.jenkins_uds_requirements_preview(
        req_files=[], req_paths="U:/proj/SRS.docx", source_root="",
    ))
    assert "req_doc_errors" not in out


# ---------------------------------------------------------------------------
# /api/scm/linked-docs-status — '없다'와 '못 봤다'는 다른 말이다
# ---------------------------------------------------------------------------
def _entry_with(linked: dict):
    from backend.schemas import ScmLinkedDocs, ScmRegistryEntry
    return ScmRegistryEntry(id="e1", name="E1", linked_docs=ScmLinkedDocs(**linked))


def _status(monkeypatch, resolver, linked):
    from backend.routers import scm as S
    monkeypatch.setattr(S, "get_registry_entry", lambda eid: _entry_with(linked))
    monkeypatch.setattr("backend.services.file_resolver.get_resolver", lambda: resolver)
    return S.scm_linked_docs_status("e1")["items"]


def test_status_reports_missing_as_false(monkeypatch):
    items = _status(monkeypatch, _FakeResolver(exists=False), {"srs": "U:/a/SRS.docx"})
    assert items["srs"]["exists"] is False


def test_status_reports_present_as_true(monkeypatch):
    items = _status(monkeypatch, _FakeResolver(exists=True), {"srs": "U:/a/SRS.docx"})
    assert items["srs"]["exists"] is True


def test_status_does_not_fold_check_failure_into_missing(monkeypatch):
    """확인이 실패하면 `None`(모름) — `False`(없음)로 접으면 멀쩡한 문서를 없다고 보고한다."""
    items = _status(monkeypatch, _FakeResolver(exists=RuntimeError("ipc timeout")),
                    {"srs": "U:/a/SRS.docx"})
    assert items["srs"]["exists"] is None, "IPC 실패를 '파일 없음'으로 단정했다"
    assert "확인 실패" in items["srs"]["reason"]


def test_status_skips_empty_paths(monkeypatch):
    items = _status(monkeypatch, _FakeResolver(exists=True), {"srs": "U:/a/SRS.docx", "sds": ""})
    assert "srs" in items and "sds" not in items
