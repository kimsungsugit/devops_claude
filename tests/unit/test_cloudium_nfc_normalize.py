"""Regression: Cloudium 게이트가 NFC/NFD(한글 조합/분해형) 경로를 동등 취급.

SVN/네트워크 드라이브에서 분해형(NFD)으로 들어온 동일 경로가 NFC 화이트리스트와
불일치해 오차단되던 버그(_normalize_for_compare에 NFC 정규화 추가)의 회귀 가드.
"""
from __future__ import annotations

import unicodedata

import pytest

from backend.services.file_resolver import CloudiumFileResolver

# 조합형/분해형이 실제로 갈리는 한글 경로
_KO = "U:/연구소/소프트웨어/01.SW 요구사항/(KJPDS02_SwRS) Spec.docx"
_KO_DIR = "U:/연구소/소프트웨어/01.SW 요구사항"


def test_normalize_for_compare_nfc_nfd_equal() -> None:
    nfc = unicodedata.normalize("NFC", _KO)
    nfd = unicodedata.normalize("NFD", _KO)
    assert nfc != nfd  # 입력 바이트열은 서로 다름
    assert (CloudiumFileResolver._normalize_for_compare(nfc)
            == CloudiumFileResolver._normalize_for_compare(nfd))  # 정규화 후 동일


# check_access()는 _ensure_gate(worker 실행 검사) → _check_allowed 순이라 worker가
# 떠 있어야 한다(CI/worker-down 환경 의존). NFC 정규화는 prefix 매칭 로직인
# _check_allowed에만 있으므로 그쪽을 직접 단위 테스트한다 (worker 비의존).
def test_check_allowed_allows_nfd_path_against_nfc_prefix() -> None:
    """NFC 화이트리스트에 NFD 경로로 접근해도 차단되면 안 됨 (raises 시 실패)."""
    r = CloudiumFileResolver(allowed_prefixes=unicodedata.normalize("NFC", _KO_DIR))
    r._check_allowed(unicodedata.normalize("NFD", _KO))


def test_check_allowed_allows_nfc_path_against_nfd_prefix() -> None:
    """반대 방향(NFD 화이트리스트 ↔ NFC 경로)도 동등 허용."""
    r = CloudiumFileResolver(allowed_prefixes=unicodedata.normalize("NFD", _KO_DIR))
    r._check_allowed(unicodedata.normalize("NFC", _KO))


def test_check_allowed_still_blocks_outside_prefix() -> None:
    """경계 약화 없음 — 화이트리스트 밖 경로는 여전히 차단."""
    r = CloudiumFileResolver(allowed_prefixes=_KO_DIR)
    with pytest.raises(PermissionError):
        r._check_allowed("U:/다른경로/01.기타/secret.docx")
