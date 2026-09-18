# -*- coding: utf-8 -*-
"""문서 종류 파일명 판정 — SDS/SRS **단일 출처**.

여기 두는 이유: `generators/` 는 `backend/` 를 import 할 수 없다(라우터가 generators 를
쓰므로 순환). `generators/` 가 이미 의존하는 `report_gen/` 이 양쪽이 닿는 유일한 층이다.
의존성 0(표준 라이브러리만) — 어디서 import 해도 안전하다.

## 왜 substring 이 아닌가 (실측, 커밋 `384743a`)

    (HDPDM01_SDS)  Software Architecture Design Spec …   "sds" in name  ✓
    (KJPDS02_SwDS) Software Architecture Design Spec …   "sds" in name  ✗
    (KJPDS02_SwRS) Software Requirements Spec …          "srs" in name  ✗

**"swds" 안에 "sds" 라는 부분문자열이 없다.** `Sw*` 표기를 쓰는 프로젝트는 SDS/SRS 가
인식되지 않았고, 저장소 `docs/` 폴백(HDPDM01)이 대신 잡혀 다른 프로젝트 설계서가 쓰였다.

## ⚠ 음성 케이스가 핵심

단위설계(`SUDS`/`SwUDS`)를 아키텍처설계(SDS)로 삼키면 추적 계층이 통째로 뒤집힌다.
`swuds` 에 `swds` 가, `suds` 에 `sds` 가 부분문자열로 없어 아래 토큰 경계 매칭으로 자연히
갈린다 — **`ds` 같은 느슨한 토큰으로 넓히면 즉시 깨진다.** 시스템 요구(`SyRS`)도 음성이다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, Set

# 앞뒤가 알파벳이 아닌 자리의 `sds`/`swds` 만 — `suds`·`swuds` 는 걸리지 않는다.
_SDS_NAME_RE = re.compile(r"(?<![a-z])s(?:w)?ds(?![a-z])", re.I)
_SRS_NAME_RE = re.compile(r"(?<![a-z])s(?:w)?rs(?![a-z])", re.I)


def is_sds_filename(name: Any) -> bool:
    """SW 아키텍처 설계서(SDS/SwDS) 파일명인가. 단위설계(SUDS/SwUDS)는 False."""
    return bool(_SDS_NAME_RE.search(Path(str(name or "")).name))


def is_srs_filename(name: Any) -> bool:
    """SW 요구사항 명세서(SRS/SwRS) 파일명인가. 시스템 요구(SyRS)는 False."""
    return bool(_SRS_NAME_RE.search(Path(str(name or "")).name))


# ── 프로젝트 신원 판정 ──────────────────────────────────────────────────────
#
# 위 SDS/SRS 판정과 같은 사고(다른 프로젝트 문서가 증거로 들어감)의 **다른 축**이다.
# 저 위는 "문서 종류를 잘못 봤다", 여기는 "종류는 맞는데 **남의 프로젝트 것**이다".

# 문서 종류·일반 명사는 프로젝트 식별자가 아니다. `reference.docx` 같은 범용 파일명이
# `REFERENCE` 를 프로젝트 ID 로 만들면 신원이 "확인 불가"가 아니라 **"다른 프로젝트"로
# 잘못 확정**된다(테스트가 잡았다).
PROJECT_TOKEN_STOPWORDS = frozenset({
    "SUDS", "SWUDS", "SRS", "SWRS", "SDS", "SWSA", "UDS", "STS", "SUTS", "SITS",
    "SYRS", "SYTS", "HSIS", "SPEC", "SPECIFICATION", "SOFTWARE", "UNIT", "DESIGN",
    "DOCUMENT", "REPORT", "FINAL", "DRAFT", "TEMPLATE", "TOKENIZED", "LOCAL",
    "REFERENCE", "REVISION", "VERSION", "COMMON", "SAMPLE", "OUTPUT",
})


def project_tokens(text: Any) -> Set[str]:
    """문자열에서 프로젝트 식별자 후보 토큰을 뽑는다(대문자 영숫자 5자 이상)."""
    out: Set[str] = set()
    for tok in re.split(r"[^A-Za-z0-9]+", str(text or "")):
        t = tok.strip().upper()
        if len(t) >= 5 and t not in PROJECT_TOKEN_STOPWORDS and not t.isdigit():
            out.add(t)
    return out


def cross_project_verdict(owner_texts: Iterable[Any], doc_text: Any) -> Dict[str, Any]:
    """문서가 **이 프로젝트의 것**인가. 신원 비교의 단일 구현.

    Args:
        owner_texts: 프로젝트 신원을 담은 문자열들(항목 id/이름/source_root/job url 등).
        doc_text: 문서 경로나 파일명.

    Returns:
        ``same_project`` — ``True``(확인됨) / ``False``(다름) / ``None``(판정 불가).

    ⚠ **판정 불가는 '확인됨'이 아니다.** 토큰이 한쪽에도 없으면 조용히 통과시키지 말고
    ``None`` 으로 남겨 호출부가 fail-closed 로 다루게 한다. 여기를 `False or True` 로
    접으면 판정 못 한 문서가 '검증된 증거'로 둔갑한다.
    """
    owner: Set[str] = set()
    for t in owner_texts or []:
        owner |= project_tokens(t)
    doc = project_tokens(Path(str(doc_text or "")).stem or str(doc_text or ""))

    if not doc:
        return {"same_project": None, "reason": "doc_no_token",
                "owner_tokens": sorted(owner), "doc_tokens": []}
    if not owner:
        return {"same_project": None, "reason": "owner_no_token",
                "owner_tokens": [], "doc_tokens": sorted(doc)}
    shared = owner & doc
    return {
        "same_project": bool(shared),
        "reason": "token_match" if shared else "token_mismatch",
        "owner_tokens": sorted(owner),
        "doc_tokens": sorted(doc),
        "shared_tokens": sorted(shared),
    }
