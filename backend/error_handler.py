"""표준 에러 응답 및 핸들링

모든 API 엔드포인트에서 일관된 에러 형식을 제공합니다.
"""
from __future__ import annotations

import logging
import traceback
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("devops_api")


class APIError(HTTPException):
    """Structured API error with consistent format."""
    def __init__(
        self,
        status_code: int = 500,
        message: str = "Internal server error",
        code: str = "INTERNAL_ERROR",
        detail: Optional[Dict[str, Any]] = None,
    ):
        self.code = code
        self.message = message
        self.error_detail = detail or {}
        super().__init__(status_code=status_code, detail=message)


def error_response(
    status_code: int,
    message: str,
    code: str = "ERROR",
    detail: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    """Create standardized error response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                **({"detail": detail} if detail else {}),
            },
        },
    )


def success_response(data: Any = None, message: str = "ok") -> Dict[str, Any]:
    """Create standardized success response."""
    response = {"ok": True}
    if data is not None:
        response["data"] = data
    return response


def handle_exception(exc: Exception, context: str = "") -> JSONResponse:
    """Handle unexpected exceptions with logging."""
    tb = traceback.format_exc()
    logger.error("[%s] Unhandled exception: %s\n%s", context, exc, tb)
    return error_response(
        500,
        f"서버 내부 오류: {str(exc)[:200]}",
        code="INTERNAL_ERROR",
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI global exception handler."""
    return handle_exception(exc, context=f"{request.method} {request.url.path}")


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """FastAPI HTTP exception handler with consistent format.

    42차 W6 fix: detail이 dict({code, message, ...})면 그 구조를 유지 — 이중 wrapping 회피.
    require_admin 등 dependency가 `HTTPException(detail={"code": ..., "message": ...})`
    형태로 raise할 때 사용자가 raw dict 문자열을 보게 되는 문제 해결.
    """
    detail = exc.detail
    if isinstance(detail, dict):
        # 구조화된 detail — code/message를 직접 사용.
        # 43차 W24 fix: 빈 dict({}) 시 `str({})` = "{}"가 frontend에 노출되어 사용자
        # 혼란 발생. 빈 dict이거나 message 키가 없으면 status-aware fallback 사용.
        # 44차 W28 정밀화: `message` 값 falsy일 때 모두 status-aware fallback 사용.
        # 분류:
        #   - key 없음 → fallback ("HTTP <N> error")
        #   - key 있고 None → fallback (raise 측 누락 간주)
        #   - key 있고 빈 string ("") → fallback (의도적 빈 message는 사용자 혼란 야기)
        #   - 그 외 truthy → 그대로 사용
        # `dict.get("message")`는 미존재 시 None — falsy 한 줄 처리로 통합.
        code = detail.get("code") or f"HTTP_{exc.status_code}"
        raw_msg = detail.get("message")
        message = raw_msg if raw_msg else f"HTTP {exc.status_code} error"
        extra = {k: v for k, v in detail.items() if k not in ("code", "message")}
        return error_response(
            exc.status_code, message, code=code,
            detail=extra if extra else None,
        )
    return error_response(
        exc.status_code,
        str(detail),
        code=f"HTTP_{exc.status_code}",
    )
