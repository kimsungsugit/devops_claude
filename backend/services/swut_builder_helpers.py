"""SwUT/SwIT 빌더 공통 helper (38차 W1 — DRY 해결).

37차에서 도입된 `warnings: list[str] = list(session.parse_warnings or [])`
패턴이 빌더 4개 (swut_coverage / swut_sutr / swit_coverage / swit_sitr)에서
동일하게 반복되어 DRY 위반. 본 모듈로 추출해 단일 출처 보장.

향후 input_adapter ↔ 빌더 warning 통합 정책 변경 시 한 곳에서만 수정.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.services.swut_input_adapter import SwUTSession


def extract_warnings_from_session(session: "SwUTSession") -> list[str]:
    """input_adapter 단계 parse_warnings를 빌더 응답 warnings의 초기값으로 반환.

    37차 fix로 도입된 통합 정책 — env_prefix mismatch / auto-resolved release
    / sub-folder missing 등 input adapter 단계 메시지가 X-SwUT-Warnings /
    X-SwIT-Warnings 헤더에 노출되도록.

    Args:
        session: SwUT/SwIT 입력 어댑터 결과

    Returns:
        session.parse_warnings의 shallow copy. None이면 빈 list.
    """
    return list(session.parse_warnings or [])


__all__ = ["extract_warnings_from_session"]
