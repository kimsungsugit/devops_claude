"""문서 종류 파일명 판정 — `SwDS`/`SwRS` 표기를 놓치던 것.

오래도록 `"sds" in name.lower()` 로만 봤다. 그런데 **"swds" 안에 "sds" 가 없다**:

    (HDPDM01_SDS)  Software Architecture Design Specification …   "sds" ✓
    (KJPDS02_SwDS) Software Architecture Design Specification …   "sds" ✗   ← 못 잡음
    (KJPDS02_SwRS) Software Requirements Specification …          "srs" ✗   ← 못 잡음

그래서 KJPDS02 처럼 `Sw*` 표기를 쓰는 프로젝트는 SDS/SRS 가 **어느 경로에서도 인식되지
않았고**, 저장소 `docs/` 폴백(HDPDM01)이 대신 잡혔다. `local.py` `_resolve_req_doc_sets`
가 폴백을 무조건 이어붙이기까지 해서, 산출물이 통째로 남의 프로젝트 설계 기준이 됐다.

⚠ 가장 중요한 건 **음성 케이스**다. 단위설계(`SUDS`/`SwUDS`)를 아키텍처설계(SDS)로
삼키면 추적 계층이 통째로 뒤집힌다. `ds` 같은 느슨한 토큰으로 넓히면 즉시 깨진다.
"""
from __future__ import annotations

import pytest

from backend.helpers.sds import is_sds_filename, is_srs_filename

# (파일명, SDS 인가, SRS 인가) — 앞 넷은 저장소/사용자 프로젝트 실파일명
CASES = [
    ("(HDPDM01_SDS) Software Architecture Design Specification_v1.04_20230512.docx", True, False),
    ("(KJPDS02_SwDS) Software Architecture Design Specification_v3.01_20260410_R.docx", True, False),
    ("(HDPDM01_SRS) Software Requirements Specification_v1.05_20230510.docx", False, True),
    ("(KJPDS02_SwRS) Software Requirements Specification_v2.03_20260405.docx", False, True),
    # ── 음성: 단위설계는 SDS 가 아니다 ──
    ("(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx", False, False),
    ("(KJPDS02_SwUDS) Software Unit Design Specification_v3.02_260XXX.docx", False, False),
    # ── 음성: 시스템 레벨은 SW 요구가 아니다 ──
    ("(KJPDS02_SyRS) System Requirements Specification_v1.00.docx", False, False),
    ("(KJPDS02_SyTS) System Test Specification.docx", False, False),
    # ── 음성: 무관 문서 ──
    ("(KJPDS02_HSIS) Hardware Software Interface Specification.xlsx", False, False),
    ("readme.docx", False, False),
]


@pytest.mark.parametrize("name,want_sds,want_srs", CASES)
def test_filename_classification(name, want_sds, want_srs):
    assert is_sds_filename(name) is want_sds, f"SDS 판정 어긋남: {name}"
    assert is_srs_filename(name) is want_srs, f"SRS 판정 어긋남: {name}"


def test_full_path_is_accepted():
    """전체 경로를 넘겨도 파일명만 본다 — 디렉터리에 'sds' 가 있어도 오탐 없어야."""
    assert is_sds_filename(r"U:\01.SwDS\(KJPDS02_SwDS) arch.docx") is True
    # 디렉터리에만 SwDS 가 있고 파일은 단위설계 → False 여야 한다
    assert is_sds_filename(r"U:\01.SwDS\(KJPDS02_SwUDS) unit.docx") is False


@pytest.mark.parametrize("junk", [None, "", "   ", 123])
def test_junk_inputs_are_false(junk):
    assert is_sds_filename(junk) is False
    assert is_srs_filename(junk) is False


def test_routers_use_the_shared_classifier_not_substrings():
    """구조 가드 — 파일명 판정이 substring 으로 되돌아가면 잡는다.

    남는 `"srs" in hn` 하나는 **표 컬럼 헤더** 판정이라 파일명과 무관하다(허용).
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    offenders = []
    for rel in ("backend/routers/jenkins.py", "backend/routers/local.py"):
        for i, ln in enumerate(
                (root / rel).read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if not re.search(r'"(?:sds|srs)" in ', ln):
                continue
            if "hn" in ln:      # 표 헤더 판정(이미 swrs 를 함께 본다)
                continue
            offenders.append(f"{rel}:{i}: {ln.strip()[:70]}")
    assert not offenders, "파일명 판정이 substring 으로 남아 있다:\n" + "\n".join(offenders)
