"""API 미들웨어 — Rate limiting, request logging, security headers"""
from __future__ import annotations

import time
import logging
from collections import defaultdict
from typing import Dict, Tuple

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("devops_api")

# Simple in-memory rate limiter (single-worker safe)
_rate_store: Dict[str, list] = defaultdict(list)
RATE_LIMIT = 300  # requests per minute (이미지 프리뷰 등 대량 요청 대응)
RATE_WINDOW = 60  # seconds

# Rate limit 제외 경로 (대량 리소스 요청)
_RATE_EXEMPT_PATHS = frozenset({
    "/api/preview-image",
    "/api/preview-excel",
    "/static",
    "/assets",
})


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 정적 리소스 + 이미지 프리뷰는 rate limit 제외
        path = request.url.path
        if any(path.startswith(p) for p in _RATE_EXEMPT_PATHS):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        # Clean old entries
        _rate_store[client_ip] = [t for t in _rate_store[client_ip] if now - t < RATE_WINDOW]

        if len(_rate_store[client_ip]) >= RATE_LIMIT:
            return Response(
                content='{"ok":false,"error":{"code":"RATE_LIMITED","message":"요청 한도 초과"}}',
                status_code=429,
                media_type="application/json",
            )

        _rate_store[client_ip].append(now)
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = (time.time() - start) * 1000

        # Only log slow requests or errors
        if duration > 1000 or response.status_code >= 400:
            logger.info(
                "[%s] %s %s → %d (%.0fms)",
                request.client.host if request.client else "-",
                request.method,
                request.url.path,
                response.status_code,
                duration,
            )

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
