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
from typing import Any

# 앞뒤가 알파벳이 아닌 자리의 `sds`/`swds` 만 — `suds`·`swuds` 는 걸리지 않는다.
_SDS_NAME_RE = re.compile(r"(?<![a-z])s(?:w)?ds(?![a-z])", re.I)
_SRS_NAME_RE = re.compile(r"(?<![a-z])s(?:w)?rs(?![a-z])", re.I)


def is_sds_filename(name: Any) -> bool:
    """SW 아키텍처 설계서(SDS/SwDS) 파일명인가. 단위설계(SUDS/SwUDS)는 False."""
    return bool(_SDS_NAME_RE.search(Path(str(name or "")).name))


def is_srs_filename(name: Any) -> bool:
    """SW 요구사항 명세서(SRS/SwRS) 파일명인가. 시스템 요구(SyRS)는 False."""
    return bool(_SRS_NAME_RE.search(Path(str(name or "")).name))
