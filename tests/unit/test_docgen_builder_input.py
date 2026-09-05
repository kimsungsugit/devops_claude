"""생성기 선택 입력의 **worker 경유 이관** 회귀.

## 무엇이 문제였나

라우터 5곳에 **글자 그대로 같은** 로컬 전용 판정이 복제돼 있었다::

    p2 = Path(val).expanduser().resolve()
    return str(p2) if p2.exists() and p2.is_file() else None

등록 문서 41개가 전부 cloudium `U:` 인데 `Path.exists()` 는 백엔드 권한으로
`PermissionError` 를 낸다 → 전량 `None` → 생성기가 그 문서 **없이** 만들고 화면엔
"생성 완료" 가 뜬다. 근거가 빠진 ISO 26262 산출물이고, 사유도 남지 않는다.

## ⚠ 텍스트 추출 게이트를 타면 안 된다

`materialize_via_resolver` 는 본문 추출용이라 `SUPPORTED_TEXT_EXTS` 게이트가 있어
`.xlsm`/`.xlsx` 를 **차단**한다. 그런데 생성기가 여는 파일이 정확히 그 형식이다
(HSIS·시험 규격서·템플릿). 그래서 별도 경로가 필요했다 — 이 구분이 무너지면
HSIS 가 조용히 빠진다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.services.resolver_helpers import resolve_builder_input

REPO = Path(__file__).resolve().parents[2]


# ── local 모드 (conftest 가 격리한다) ───────────────────────────────────────

def test_empty_path_is_not_a_failure() -> None:
    """지정하지 않은 선택 입력은 실패가 아니다 — 사유를 남기면 노이즈가 된다."""
    reasons: list[str] = []
    assert resolve_builder_input("", reasons=reasons) is None
    assert reasons == []


def test_existing_local_file_returns_path(tmp_path: Path) -> None:
    """local 모드는 **직독이 정답**이다 — 대용량 xlsm 을 복사할 이유가 없다."""
    f = tmp_path / "spec.docx"
    f.write_text("x", encoding="utf-8")
    reasons: list[str] = []
    got = resolve_builder_input(str(f), reasons=reasons)
    assert got == str(f.resolve())
    assert reasons == []


def test_missing_local_file_collects_reason(tmp_path: Path) -> None:
    """없는 파일은 `None` **+ 사유**. 사유 없이 None 만 주면 조용히 빠진다."""
    reasons: list[str] = []
    assert resolve_builder_input(str(tmp_path / "nope.docx"), reasons=reasons) is None
    assert len(reasons) == 1
    assert "파일 없음" in reasons[0]


def test_label_is_used_in_reason(tmp_path: Path) -> None:
    """사유에 무슨 문서인지 적힌다 — 파일명만으로는 어느 슬롯인지 모른다."""
    reasons: list[str] = []
    resolve_builder_input(str(tmp_path / "x.docx"), label="HSIS", reasons=reasons)
    assert reasons and reasons[0].startswith("HSIS:")


def test_reasons_accumulate_across_calls(tmp_path: Path) -> None:
    """여러 선택 입력의 사유가 한 리스트에 모여야 한 번에 보고할 수 있다."""
    reasons: list[str] = []
    for name in ("a.docx", "b.docx", "c.docx"):
        resolve_builder_input(str(tmp_path / name), reasons=reasons)
    assert len(reasons) == 3


def test_works_without_reasons_collector(tmp_path: Path) -> None:
    """수집기를 안 넘겨도 죽지 않는다(호출부가 사유를 안 쓸 수 있다)."""
    assert resolve_builder_input(str(tmp_path / "x.docx")) is None


@pytest.mark.parametrize("ext", [".xlsm", ".xlsx", ".docx"])
def test_binary_office_formats_are_not_gated(tmp_path: Path, ext: str) -> None:
    """**`.xlsm`/`.xlsx` 가 형식 게이트에 막히면 안 된다.**

    `materialize_via_resolver`(본문 추출용)는 이 형식을 차단한다. 생성기는 openpyxl 로
    직접 열므로 그 게이트를 타면 HSIS·규격서·템플릿이 통째로 빠진다.
    """
    f = tmp_path / f"doc{ext}"
    f.write_bytes(b"binary-ish")
    reasons: list[str] = []
    assert resolve_builder_input(str(f), reasons=reasons) == str(f.resolve())
    assert reasons == []


def test_text_extraction_gate_still_blocks_them() -> None:
    """대조군 — 본문 추출 경로는 여전히 xlsm 을 막는다(두 경로가 다르다는 증거)."""
    from backend.services.resolver_helpers import parser_unreadable_reason
    assert parser_unreadable_reason("x.xlsm")
    assert parser_unreadable_reason("x.xlsx")
    assert not parser_unreadable_reason("x.docx")


# ── 구조 가드: 복제가 되살아나지 않게 ───────────────────────────────────────

_LOCAL_ONLY_PATTERN = re.compile(
    r"p2\s*=\s*Path\(val\)\.expanduser\(\)\.resolve\(\)\s*\n\s*return\s+str\(p2\)"
)


@pytest.mark.parametrize("rel", ["backend/routers/jenkins.py", "backend/routers/local.py"])
def test_local_only_resolution_is_gone(rel: str) -> None:
    """직독 판정이 다시 복제되면 실패한다.

    5벌이 **글자 그대로 같았다**. 하나만 고치면 나머지 넷이 남아 같은 결함이 계속
    산다 — 이 저장소가 반복해서 겪은 형태다.
    """
    text = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
    found = _LOCAL_ONLY_PATTERN.findall(text)
    assert not found, f"{rel}: 로컬 전용 직독 판정이 {len(found)}곳 남아 있다"


_DIRECT_DOC_READ = re.compile(
    r"Path\((srs|sds|uds|hsis|stp|template)_path\)\.expanduser\(\)\.resolve\(\)\s*\n"
    r"\s*if p\.exists\(\)"
)


@pytest.mark.parametrize("rel", ["backend/routers/jenkins.py", "backend/routers/local.py"])
def test_document_paths_are_not_probed_directly(rel: str) -> None:
    """문서 경로에 `Path(...).exists()` 를 직접 쓰면 안 된다.

    cloudium `U:` 에서 **`PermissionError` 가 그대로 전파**돼
    `[WinError 5] 액세스가 거부되었습니다` 로 500 이 난다(실제 사용자 보고 — 화면에서
    STS 를 만들다 이 오류를 봤다).

    선택 입력은 이미 worker 경유였는데 `srs_path`(5곳)와 `template_path`(7곳)만 **별도
    블록**이라 빠져 있었다 — 같은 판정이 여러 벌이면 한쪽만 고쳐진다는 이 저장소의
    반복 결함 그대로다.
    """
    text = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
    found = _DIRECT_DOC_READ.findall(text)
    assert not found, f"{rel}: 문서 경로 직독이 {len(found)}곳 남아 있다 {sorted(set(found))}"


@pytest.mark.parametrize("rel", ["backend/routers/jenkins.py", "backend/routers/local.py"])
def test_routers_use_shared_resolver(rel: str) -> None:
    text = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
    assert "resolve_builder_input" in text, f"{rel}: 공용 해석기를 쓰지 않는다"
