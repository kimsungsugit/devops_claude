# -*- coding: utf-8 -*-
"""요구문서 cloudium 실체화 — 인계 P3(`read_requirement_doc` Path 직독 7곳).

cloudium 모드에서 백엔드 프로세스는 registry 의 ``U:/…`` 를 직접 못 연다. 그래서 등록된
SRS/SDS/UDS 가 전부 탈락하고 핸들러는 "SRS document is required" 라는 **원인과 무관한**
400 을 냈다. 사용자는 준 문서를 안 줬다는 말을 듣는다.

## 왜 '읽기만 resolver 로' 가 아니라 **실체화**인가

호출부 7곳은 본문만 쓰는 게 아니라 **경로를 하류로 넘긴다**(``req_doc_paths``). 그 하류가
전부 ``Path`` 직독이다 — ``_build_req_map_from_doc_paths``(ASIL/Related),
``_extract_sds_partition_map``, ``_build_uds_asil_map``. 읽기만 바꾸면 U: 경로가 하류로
흘러 거기서 **조용히 스킵**된다(오늘은 최소한 사유와 함께 실패한다) — 반쪽 수정이 지금보다
나쁜 경우다. ``_build_uds_asil_map`` docstring 이 정답을 이미 적어 뒀다:
*"호출부가 cloudium U: 경로를 로컬 tmp로 변환해 넘긴 뒤에만 유효"*.

## 이 파일이 고정하는 계약

  A. **local 모드는 불변** — 직독 그대로, 실체화 안 함
  B. cloudium 이면 worker IPC 로 읽어 로컬로 떨구고 그 경로를 준다
  C. **파일명을 보존한다** ← 호출부가 ``p.name`` 으로 문서 종류를 판정한다.
     ``tmpXXXX.docx`` 로 바꾸면 SRS/SDS 가 통째로 오분류되고, 그건 조용하다
  D. ``allow`` 는 **바이트를 받기 전에** 판정 — 안 쓸 문서를 IPC 로 끌어오지 않는다
  E. 실패는 갈래별 사유 (접근 거부 / 파일 없음 / 읽기 실패 / 0바이트)
  F. 반환 shape ``(경로, 본문, 사유)`` 불변 — 호출부 7곳이 안 바뀐다는 근거
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.services import resolver_helpers as RH


class _FakeCloud:
    """CloudiumFileResolver 대역 — isinstance 판정을 위해 실제 클래스를 상속한다."""

    def __init__(self, files: dict, *, fail_read: Exception | None = None):
        self.files = files
        self.fail_read = fail_read
        self.read_calls: list[str] = []

    def exists(self, path: str) -> bool:
        return str(path) in self.files

    def read_bytes(self, path: str) -> bytes:
        self.read_calls.append(str(path))
        if self.fail_read:
            raise self.fail_read
        return self.files[str(path)]

    def check_access(self, path: str) -> None:
        return None


@pytest.fixture()
def cloud(monkeypatch):
    """resolver 를 cloudium 대역으로 교체. ⚠ 전역을 '특정 값으로 고정'하지 않고 monkeypatch 로 복원."""
    def _install(files, **kw):
        fake = _FakeCloud(files, **kw)
        from backend.services import file_resolver as fr
        monkeypatch.setattr(fr, "get_resolver", lambda: fake)
        # _needs_resolver_read / materialize 는 isinstance 대신 이 함수를 본다.
        monkeypatch.setattr(RH, "_needs_resolver_read", lambda: True)
        return fake
    return _install


def _docx_bytes(text: str = "SwTR_0101 요구") -> bytes:
    """python-docx 로 만든 최소 docx — `_read_text_from_file` 이 실제로 파싱한다."""
    import io

    from docx import Document

    d = Document()
    d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


U_SRS = "U:/proj/01.SwRS/(KJPDS02_SwRS) Software Requirements Specification_v3.01.docx"


# ─────────────────────────────────────────────────────────────────────────────
# A — local 모드 불변 (회귀 방지)
# ─────────────────────────────────────────────────────────────────────────────

def test_local_모드는_직독_그대로_실체화하지_않는다(tmp_path, monkeypatch):
    monkeypatch.setattr(RH, "_needs_resolver_read", lambda: False)
    f = tmp_path / "SRS.docx"
    f.write_bytes(_docx_bytes("SwTR_0101"))

    p, text, reason = RH.read_requirement_doc(str(f))
    assert reason == ""
    assert text
    assert p == f.resolve(), "local 모드인데 경로가 임시본으로 바뀌었다 — 직독이 깨졌다"


def test_local_모드_파일없음은_기존_사유_그대로(tmp_path, monkeypatch):
    monkeypatch.setattr(RH, "_needs_resolver_read", lambda: False)
    p, text, reason = RH.read_requirement_doc(str(tmp_path / "없음.docx"))
    assert text == "" and "파일 없음" in reason


def test_판정함수가_local_resolver를_실제로_False로_읽는다(monkeypatch):
    """⚠ 위 두 테스트는 `_needs_resolver_read` 를 **stub** 한다 — 그 함수 자체가 망가져도
    통과한다(뮤테이션 M7 생존으로 실증). 여기서는 진짜 함수를 진짜 resolver 로 태운다.
    """
    from backend.services import file_resolver as fr

    monkeypatch.setattr(fr, "get_resolver", lambda: fr.LocalFileResolver())
    assert RH._needs_resolver_read() is False, "local 모드인데 실체화 경로로 내려간다"


def test_판정함수가_cloudium_resolver를_실제로_True로_읽는다(monkeypatch, tmp_path):
    from backend.services import file_resolver as fr

    monkeypatch.setattr(
        fr, "get_resolver", lambda: fr.CloudiumFileResolver(allowed_prefixes=str(tmp_path)))
    assert RH._needs_resolver_read() is True, "cloudium 인데 직독만 하고 끝난다"


def test_local_모드는_권한오류에도_실체화로_안_내려간다(tmp_path, monkeypatch):
    """local 은 사용자 권한이 곧 OS 권한이라 폴백이 의미 없다 — 사유를 그대로 준다."""
    from backend.services import file_resolver as fr

    monkeypatch.setattr(fr, "get_resolver", lambda: fr.LocalFileResolver())
    monkeypatch.setattr(
        Path, "exists", lambda self: (_ for _ in ()).throw(PermissionError("denied")))
    _p, text, reason = RH.read_requirement_doc(str(tmp_path / "x.docx"))
    assert text == "" and "직접 열 수 없다" in reason


# ─────────────────────────────────────────────────────────────────────────────
# B·C — cloudium 실체화 + **파일명 보존**
# ─────────────────────────────────────────────────────────────────────────────

def test_cloudium_문서를_실제로_읽는다(cloud):
    cloud({U_SRS: _docx_bytes("SwTR_0101 요구")})
    p, text, reason = RH.read_requirement_doc(U_SRS)
    assert reason == "", f"cloudium 문서를 못 읽었다: {reason}"
    assert "SwTR_0101" in text
    assert p is not None and p.exists(), "실체화된 로컬 파일이 없다"


@pytest.mark.parametrize(("label", "boom"), [
    ("파일없음(False 반환)", None),
    ("PermissionError", PermissionError("U: denied")),
    ("OSError", OSError("device not ready")),
])
def test_직독_실패_세_갈래_모두_실체화로_내려간다(cloud, monkeypatch, label, boom):
    """직독이 못 하는 방식이 셋이다 — 한 갈래만 폴백을 달면 나머지에서 다시 침묵한다.

    (뮤테이션 M1 이 처음에 생존한 이유가 이거였다: 테스트가 한 갈래만 태웠다.)
    """
    cloud({U_SRS: _docx_bytes("SwTR_0101")})
    real_exists = Path.exists
    target = Path(U_SRS).name

    def _patched(self, *a, **kw):
        # ⚠ 대상 경로에만 건다. 전역으로 걸면 **실체화 자신의 임시파일 생성까지** 막혀
        #   "실체화로 안 내려갔다"는 엉뚱한 실패가 난다(처음에 그렇게 틀렸다).
        if self.name != target:
            return real_exists(self, *a, **kw)
        if boom is not None:
            raise boom
        return False

    monkeypatch.setattr(Path, "exists", _patched)
    p, text, reason = RH.read_requirement_doc(U_SRS)
    assert reason == "", f"[{label}] 실체화로 안 내려갔다: {reason}"
    assert "SwTR_0101" in text and p is not None


def test_실체화_경로가_원본_파일명을_보존한다(cloud):
    """⚠ 최고 위험 지점 — 호출부가 p.name 으로 문서 종류를 판정한다.

    tmpXXXX.docx 로 바꾸면 SRS/SDS 판정이 통째로 뒤집히고, **아무 에러도 안 난다**.
    """
    from report_gen.doc_kind import is_sds_filename, is_srs_filename

    cloud({U_SRS: _docx_bytes()})
    p, _text, _r = RH.read_requirement_doc(U_SRS)
    assert p.name == Path(U_SRS).name, f"파일명이 바뀌었다: {p.name}"
    assert is_srs_filename(p.name) is True
    assert is_sds_filename(p.name) is False


def test_다른_폴더의_동명_파일이_서로_덮어쓰지_않는다(cloud):
    a = "U:/proj/A/SRS.docx"
    b = "U:/proj/B/SRS.docx"
    cloud({a: _docx_bytes("문서 A SwTR_0101"), b: _docx_bytes("문서 B SwTR_0202")})
    pa, ta, _ = RH.read_requirement_doc(a)
    pb, tb, _ = RH.read_requirement_doc(b)
    assert pa != pb, "같은 파일명이 한 칸을 공유했다 — 뒤에 읽은 문서가 앞을 덮어쓴다"
    assert "SwTR_0101" in ta and "SwTR_0202" in tb
    assert pa.read_bytes() != pb.read_bytes()


def test_하류가_쓰는_경로가_실제로_열린다(cloud):
    """실체화의 **목적** — req_doc_paths 를 받는 하류는 전부 Path 직독이다."""
    cloud({U_SRS: _docx_bytes("SwTR_0101")})
    p, _t, _r = RH.read_requirement_doc(U_SRS)
    # 하류가 하는 짓 그대로: Path.exists() + docx open
    assert Path(str(p)).exists()
    from report_gen.requirements import _safe_docx_open
    assert _safe_docx_open(str(p)) is not None


# ─────────────────────────────────────────────────────────────────────────────
# D — allow 는 바이트를 받기 전에
# ─────────────────────────────────────────────────────────────────────────────

def test_allow_거부는_IPC_read_를_아예_하지_않는다(cloud):
    fake = cloud({"U:/proj/x.exe": b"MZ"})
    p, text, reason = RH.read_requirement_doc(
        "U:/proj/x.exe", allow=lambda _p: False)
    assert text == "" and "허용된" in reason
    assert fake.read_calls == [], "허용 밖 문서를 IPC 로 끌어왔다 — 순서가 뒤바뀌었다"


def test_allow_통과는_읽는다(cloud):
    fake = cloud({U_SRS: _docx_bytes()})
    _p, text, reason = RH.read_requirement_doc(U_SRS, allow=lambda _p: True)
    assert reason == "" and text
    assert len(fake.read_calls) == 1


# ─────────────────────────────────────────────────────────────────────────────
# E — 실패 갈래별 사유
# ─────────────────────────────────────────────────────────────────────────────

def test_없는_파일은_사유가_다르다(cloud):
    cloud({})
    _p, text, reason = RH.read_requirement_doc(U_SRS)
    assert text == "" and "파일 없음" in reason


def test_읽기_실패는_사유가_다르다(cloud):
    cloud({U_SRS: b""}, fail_read=PermissionError("worker timeout"))
    _p, text, reason = RH.read_requirement_doc(U_SRS)
    assert text == ""
    assert "읽기 실패" in reason and "PermissionError" in reason


def test_0바이트는_성공으로_위장하지_않는다(cloud):
    cloud({U_SRS: b""})
    _p, text, reason = RH.read_requirement_doc(U_SRS)
    assert text == "" and "0바이트" in reason


def test_접근_거부는_사유가_다르다(cloud, monkeypatch):
    from fastapi import HTTPException
    cloud({U_SRS: _docx_bytes()})

    def _deny(_path):
        raise HTTPException(status_code=403, detail="allowed_prefixes 밖")

    monkeypatch.setattr(RH, "enforce_resolver_access", _deny)
    _p, text, reason = RH.read_requirement_doc(U_SRS)
    assert text == "" and "접근 거부" in reason


def test_사유_갈래가_서로_다른_문장이다(cloud, monkeypatch):
    """뭉뚱그리면 사용자가 엉뚱한 곳을 의심한다."""
    msgs = []
    cloud({})
    msgs.append(RH.read_requirement_doc(U_SRS)[2])
    cloud({U_SRS: b""})
    msgs.append(RH.read_requirement_doc(U_SRS)[2])
    cloud({U_SRS: b"x"}, fail_read=OSError("io"))
    msgs.append(RH.read_requirement_doc(U_SRS)[2])
    assert len(set(msgs)) == 3, f"사유가 겹친다: {msgs}"


# ─────────────────────────────────────────────────────────────────────────────
# F — 계약(호출부 7곳 무변경의 근거) + 단일 구현 공유
# ─────────────────────────────────────────────────────────────────────────────

def test_반환_shape_은_3튜플_그대로다(cloud):
    cloud({U_SRS: _docx_bytes()})
    out = RH.read_requirement_doc(U_SRS)
    assert isinstance(out, tuple) and len(out) == 3
    assert isinstance(out[0], Path) and isinstance(out[1], str) and isinstance(out[2], str)


def test_via_resolver_는_같은_실체화를_공유한다(cloud, monkeypatch):
    """사본을 두면 이 저장소 단골인 '한쪽만 수정'이 재발한다."""
    cloud({U_SRS: _docx_bytes("SwTR_0101")})
    calls = []
    orig = RH.materialize_via_resolver

    def _spy(*a, **kw):
        calls.append(a[0] if a else kw.get("path_str"))
        return orig(*a, **kw)

    monkeypatch.setattr(RH, "materialize_via_resolver", _spy)
    text, reason = RH.read_requirement_doc_via_resolver(U_SRS)
    assert reason == "" and "SwTR_0101" in text
    assert calls == [U_SRS], "via_resolver 가 실체화를 안 거친다 — 사본이 생겼다"


def test_빈_경로는_사유_없이_조용히_통과(cloud):
    cloud({})
    assert RH.read_requirement_doc("   ") == (None, "", "")
    assert RH.read_requirement_doc_via_resolver("") == ("", "")
