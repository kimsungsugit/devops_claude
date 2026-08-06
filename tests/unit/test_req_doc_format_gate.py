# -*- coding: utf-8 -*-
"""요구문서 형식 게이트 — 파서 능력을 단일 출처로.

## 무엇이 어긋나 있었나

읽기 지점이 7곳인데 **4곳은 `allow` 를 안 넘겼다**(`jenkins.py:3180`,
`local.py:2217/2406/2593`). 같은 코드를 복제하며 게이트만 3곳에 붙은 드리프트다.
그리고 게이트(`_is_allowed_req_doc`)는 4종(`.txt .md .pdf .docx`)만 허용하는데
파서(`_read_text_uncached`)는 **12종**을 읽는다 — 즉 두 방향으로 다 어긋나 있었다:

  - 파서는 읽는데 게이트가 막는 형식 (`.csv .log .json .xml .yaml .yml .html .htm`)
  - 게이트가 없어서 **못 읽는 형식이 통과**하는 4곳 (`.xlsm .xlsx` 등)

후자는 요구문서 읽기가 실체화(worker IPC)로 바뀌면서 **비용이 생겼다**: 못 읽을 형식도
바이트를 통째로 끌어온 뒤 파서가 ``""`` 를 돌려주고, 사용자는 "본문 0자 — 양식/권한
확인 필요"라는 **원인과 무관한** 사유를 본다. 실측 대상 문서는 `.xlsm` 수 MB 급이다.

## 고정하는 계약

  A. 파서 능력은 ``chunker.SUPPORTED_TEXT_EXTS`` **단일 출처**이며 실제 분기와 일치한다
  B. 못 읽는 형식은 **바이트를 받기 전에** 걸리고, 사유가 '본문 0자'와 다르다
  C. 호출자 ``allow`` 는 그 위에 얹는 **추가** 제약이다(넓힐 수 없다)
  D. 읽기 지점 **7곳 전부** 같은 게이트를 쓴다 (비대칭 재발 금지)
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.services import resolver_helpers as RH
from workflow.rag.chunker import (
    SUPPORTED_TEXT_EXTS,
    _read_text_uncached,
)

# ─────────────────────────────────────────────────────────────────────────────
# A — 단일 출처가 실제 파서 동작과 일치하는가
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ext", sorted(SUPPORTED_TEXT_EXTS - {".pdf", ".docx"}))
def test_지원목록의_텍스트계열은_실제로_본문이_나온다(tmp_path, ext):
    """목록에만 있고 파서가 못 읽으면 게이트가 헛되이 통과시킨다."""
    f = tmp_path / f"doc{ext}"
    f.write_text("SwTR_0101 요구사항 본문", encoding="utf-8")
    assert _read_text_uncached(f).strip(), f"{ext} 가 목록에 있는데 본문이 안 나온다"


def test_지원목록의_docx도_실제로_읽힌다(tmp_path):
    import io

    from docx import Document

    d = Document()
    d.add_paragraph("SwTR_0101")
    buf = io.BytesIO()
    d.save(buf)
    f = tmp_path / "doc.docx"
    f.write_bytes(buf.getvalue())
    assert "SwTR_0101" in _read_text_uncached(f)


@pytest.mark.parametrize("ext", [".xlsm", ".xlsx", ".exe", ".zip", ".c", ""])
def test_목록_밖은_파서가_빈문자열을_돌려준다(tmp_path, ext):
    """목록 밖인데 읽히면 '못 읽는다'는 게이트 판정이 거짓이 된다."""
    f = tmp_path / f"doc{ext}"
    f.write_bytes(b"anything")
    assert _read_text_uncached(f) == ""


def test_목록이_파서_분기와_동기다():
    """⚠ 목록과 분기가 갈리면 게이트가 조용히 틀린다 — 소스에서 직접 대조한다."""
    src = Path(_read_text_uncached.__code__.co_filename).read_text(encoding="utf-8")
    fn = next(n for n in ast.parse(src).body
              if isinstance(n, ast.FunctionDef) and n.name == "_read_text_uncached")
    in_branches: set[str] = set()
    for node in ast.walk(fn):
        # `if ext in (".txt", ...)` 형태의 리터럴 튜플만 모은다.
        if isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.In):
            cmp = node.comparators[0]
            if isinstance(cmp, ast.Tuple):
                for e in cmp.elts:
                    if isinstance(e, ast.Constant) and isinstance(e.value, str):
                        in_branches.add(e.value)
    assert in_branches, "분기에서 확장자를 하나도 못 읽었다 — 파서가 재작성됐다면 이 검사부터 갱신"
    missing = in_branches - set(SUPPORTED_TEXT_EXTS)
    assert not missing, f"분기에는 있는데 SUPPORTED_TEXT_EXTS 에 없다: {sorted(missing)}"


# ─────────────────────────────────────────────────────────────────────────────
# B·C — 게이트 동작과 우선순위
# ─────────────────────────────────────────────────────────────────────────────

def test_못읽는_형식은_사유가_본문0자와_다르다():
    why = RH.parser_unreadable_reason("U:/x/(KJPDS02_SwTS) Test Spec.xlsm")
    assert why and ".xlsm" in why
    assert "본문 0자" not in why, "원인과 무관한 사유로 뭉갰다"
    assert "Test Spec.xlsm" in why, "어느 파일인지 안 알려준다"


def test_읽을수_있는_형식은_사유가_없다():
    for p in ("U:/x/SRS.docx", "a.md", "b.TXT", "c.Pdf", "d.html"):
        assert RH.parser_unreadable_reason(p) == "", p


def test_확장자_없음도_사유를_준다():
    why = RH.parser_unreadable_reason("U:/x/README")
    assert "확장자 없음" in why


class _Cloud:
    def __init__(self, files):
        self.files = files
        self.read_calls: list[str] = []

    def exists(self, path):
        return str(path) in self.files

    def read_bytes(self, path):
        self.read_calls.append(str(path))
        return self.files[str(path)]

    def check_access(self, path):
        return None


@pytest.fixture()
def cloud(monkeypatch):
    def _install(files):
        fake = _Cloud(files)
        from backend.services import file_resolver as fr
        monkeypatch.setattr(fr, "get_resolver", lambda: fake)
        monkeypatch.setattr(RH, "_needs_resolver_read", lambda: True)
        return fake
    return _install


def test_못읽는_형식은_IPC_read_를_아예_하지_않는다(cloud):
    """실측 대상은 수 MB `.xlsm` 이다 — 받아 놓고 버리면 그대로 낭비다."""
    xlsm = "U:/x/Test Spec.xlsm"
    fake = cloud({xlsm: b"PK" + b"0" * 4096})
    _p, text, reason = RH.read_requirement_doc(xlsm)
    assert text == "" and ".xlsm" in reason
    assert fake.read_calls == [], "못 읽을 형식을 IPC 로 끌어왔다"


def test_via_resolver_도_같은_게이트를_탄다(cloud):
    xlsm = "U:/x/Test Spec.xlsm"
    fake = cloud({xlsm: b"PK"})
    text, reason = RH.read_requirement_doc_via_resolver(xlsm)
    assert text == "" and ".xlsm" in reason
    assert fake.read_calls == []


def test_allow_는_파서게이트_위에_얹는_추가제약이다(cloud):
    """`.md` 는 파서가 읽지만 호출자가 좁히면 거부돼야 한다(넓히기는 불가)."""
    md = "U:/x/note.md"
    cloud({md: b"# SwTR_0101"})
    _p, text, reason = RH.read_requirement_doc(md, allow=lambda _p: False)
    assert text == "" and "허용된" in reason

    # 반대로 allow 가 넓혀도 파서 게이트를 못 뚫는다.
    xlsm = "U:/x/a.xlsm"
    cloud({xlsm: b"PK"})
    _p2, text2, reason2 = RH.read_requirement_doc(xlsm, allow=lambda _p: True)
    assert text2 == "" and ".xlsm" in reason2


def test_local_모드도_같은_사유를_준다(tmp_path, monkeypatch):
    """⚠ `".xlsm" in reason` 으로 단언하면 안 된다 — 파일명이 `spec.xlsm` 이라 **어느 사유든**
    통과한다(그렇게 짰다가 뮤테이션 M1 이 생존했다). 갈래를 가르는 문구로 단언한다.
    """
    monkeypatch.setattr(RH, "_needs_resolver_read", lambda: False)
    f = tmp_path / "spec.xlsm"
    f.write_bytes(b"PK")
    _p, text, reason = RH.read_requirement_doc(str(f))
    assert text == ""
    assert "읽을 수 없는 형식" in reason, f"local 과 cloudium 이 다른 말을 한다: {reason}"
    assert "본문 0자" not in reason, "형식 문제를 '본문 0자'로 뭉갰다"


def test_디렉터리는_형식_사유로_뭉개지지_않는다(tmp_path, monkeypatch):
    """⚠ 게이트를 존재/디렉터리 판정 **앞**에 두면 '파일이 아님' 갈래가 사라진다.

    디렉터리는 확장자가 없어 형식 게이트에 먼저 걸린다 — 갈래를 가르려다 갈래를 없앤 꼴.
    (실제로 그렇게 짰다가 `test_requirement_doc_read_reasons.py` 가 잡았다.)
    """
    monkeypatch.setattr(RH, "_needs_resolver_read", lambda: False)
    d = tmp_path / "some_dir"
    d.mkdir()
    _p, text, reason = RH.read_requirement_doc(str(d))
    assert text == ""
    assert "디렉터리" in reason, f"디렉터리 갈래가 형식 사유로 뭉개졌다: {reason}"


def test_없는_파일도_형식_사유로_뭉개지지_않는다(tmp_path, monkeypatch):
    monkeypatch.setattr(RH, "_needs_resolver_read", lambda: False)
    _p, text, reason = RH.read_requirement_doc(str(tmp_path / "no_such.xlsm"))
    assert text == "" and "파일 없음" in reason


def test_읽을수_있는_형식은_그대로_읽힌다(cloud):
    md = "U:/x/req.md"
    fake = cloud({md: "# SwTR_0101 요구".encode("utf-8")})
    p, text, reason = RH.read_requirement_doc(md)
    assert reason == "" and "SwTR_0101" in text and p is not None
    assert len(fake.read_calls) == 1


# ─────────────────────────────────────────────────────────────────────────────
# D — 읽기 지점 7곳이 같은 게이트를 쓰는가 (비대칭 재발 금지)
# ─────────────────────────────────────────────────────────────────────────────

def test_모든_읽기지점이_allow를_넘긴다():
    """3곳만 게이트가 붙어 있던 게 이번 결함이다. 새 호출부가 또 빠뜨리면 여기서 걸린다."""
    root = Path(RH.__file__).resolve().parents[2]
    offenders: list[str] = []
    seen = 0
    for rel in ("backend/routers/jenkins.py", "backend/routers/local.py"):
        for i, line in enumerate((root / rel).read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if not s.startswith("p, text, reason = read_requirement_doc("):
                continue
            seen += 1
            if "allow=" not in s:
                offenders.append(f"{rel}:{i}")
    assert seen >= 7, f"읽기 지점을 {seen}개만 찾았다 — 선택자가 낡았을 수 있다"
    assert offenders == [], f"allow 없이 요구문서를 읽는 지점: {offenders}"
