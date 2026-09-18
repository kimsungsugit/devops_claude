"""56차 T308 — log_folder UNC + local 모드 pre-flight check.

사용자가 Settings에서 mode 전환을 잊고 log_folder=U:/... 입력으로 빌드 시도하면
`LocalFileResolver.exists()`가 `PermissionError [WinError 5]` 발생 → 403 응답. 모드
진단 부재로 UX 손실. 본 모듈은 endpoint 진입 즉시 pre-flight check로 400 + 안내.

## 정책

- UNC 패턴(`\\\\server\\share`) 감지
- 회사 환경 mapped network drive letters (U/V/W/X/Y/Z) 감지
  - A-T는 보통 local HDD/SSD/USB라 자동 회피
  - 사용자 환경 mapped letter 추가 필요 시 본 frozenset 갱신
- Local 모드일 때만 차단 — Cloudium 모드면 worker가 처리하므로 통과

## ISO 26262

본 check는 사용자 입력 진단만 — evidence/audit 자체에 영향 없음. ASIL B+ 산출물
입력 검증으로 분류.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

# UNC 패턴: \\server\share 형식
_UNC_PREFIX = re.compile(r"^\\\\")

# 회사 환경 mapped network drive letters
# - A-T: 보통 local HDD/SSD/USB
# - U-Z: 보통 network share (회사 환경 컨벤션)
_NETWORK_DRIVE_LETTERS = frozenset("UVWXYZ")


def is_network_path(path: str) -> bool:
    """UNC (`\\\\server\\share`) 또는 회사 mapped network drive 감지.

    Args:
        path: 검사할 path string. None/빈 string은 False 반환.

    Returns:
        True: UNC 또는 U:/V:/W:/X:/Y:/Z: 시작 path. False: local path 또는 빈 string.
    """
    if not path:
        return False
    p = str(path).strip()
    if not p:
        return False
    if _UNC_PREFIX.match(p):
        return True
    if len(p) >= 2 and p[1] == ":" and p[0].upper() in _NETWORK_DRIVE_LETTERS:
        return True
    return False


def check_log_folder_mode_compat(log_folder: str | None, resolver: Any) -> None:
    """log_folder가 UNC + Local 모드면 HTTPException 400 raise.

    Cloudium 모드면 통과 (worker가 처리). Local 모드 + UNC면 사용자 친화 메시지 +
    suggested_mode='cloudium' 안내.

    Args:
        log_folder: 사용자가 입력한 log_folder path. None/빈 string OK (검사 skip).
        resolver: `get_resolver()` 반환값 (LocalFileResolver or CloudiumFileResolver).

    Raises:
        HTTPException 400: code=PATH_MODE_MISMATCH + message + suggested_mode=cloudium
    """
    if not log_folder:
        return

    # CloudiumFileResolver import는 함수 내부 — circular import 방어
    from backend.services.file_resolver import CloudiumFileResolver

    if isinstance(resolver, CloudiumFileResolver):
        return  # cloudium 모드는 worker가 검증

    if is_network_path(log_folder):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "PATH_MODE_MISMATCH",
                "message": (
                    f"log_folder='{log_folder}' 는 네트워크 경로입니다. "
                    f"현재 Local 모드에서는 접근 불가 — Settings에서 Cloudium 모드로 "
                    f"전환 후 재시도해주세요."
                ),
                "suggested_mode": "cloudium",
            },
        )


__all__ = ["is_network_path", "check_log_folder_mode_compat"]
