"""API 미들웨어 — Rate limiting, request logging, security headers, Cloudium gate."""
from __future__ import annotations

import json
import time
import logging
from collections import defaultdict
from typing import Dict

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# **W-N2 fix**: 동적 inline import → top-level fail-fast. helpers는 미들웨어를
# import하지 않으므로 순환 의존 없음. ImportError 시 cloudium 미들웨어 startup
# 단계에서 즉시 실패하여 silent 우회 위험 제거.
from backend.helpers.common import _parse_path_list

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


# ---------------------------------------------------------------------------
# Cloudium gate middleware — D1/D3 단일 정책 강제 layer
# ---------------------------------------------------------------------------
# 사용자 입력 path를 받는 모든 endpoint에서 게이트/화이트리스트를 자동 검사.
# 196곳 라우터 코드 변경 없이 단일 책임 지점에서 정책을 강제한다.
#
# PATH_KEYS는 backend 라우터에서 사용자 입력 path로 사용되는 키 이름 화이트리스트.
# 새 endpoint에 다른 키 이름이 추가되면 여기 갱신 필요 (회귀 테스트로 보호).

_CLOUDIUM_PATH_KEYS = frozenset({
    "path", "file_path", "doc_path", "document_path", "target",
    "uds_path", "sts_path", "suts_path", "sits_path",
    "srs_path", "sds_path",
    "template_path", "ai_example_path", "ai_examples_path",
    "source_root", "source_dir", "report_dir", "cache_root",
    "folder", "root", "status_path",
    "validation_report_path", "residual_report_path",
    "stp_path", "hsis_path", "output_dir",
})

# **D2 fix**: 콤마/세미콜론/뉴라인 구분 multi-path 키. value를 split 후 각 element를
# 화이트리스트 검사. PATH_KEYS와 별도로 두어 single-string check와 구별.
#
# **분류 룰 (W-N5)**:
#   - 단일 path string으로 받는 키 (예: `srs_path`, `template_path`) → `_CLOUDIUM_PATH_KEYS`
#   - 콤마/세미콜론 구분 multi-path string으로 받는 키 (예: `req_paths`) → `_CLOUDIUM_MULTI_PATH_KEYS`
#   - JSON list of strings (`{"paths": ["a", "b"]}`)는 부모 key가 위 두 set 어디에든 있으면
#     `_scan_dict_for_paths`가 element 별로 검사 (C-N1 처리).
#   - 새 endpoint 추가 시 라우터 회귀 테스트(`test_all_router_user_input_path_keys_*`)가
#     `_paths` 접미사·exact 매칭으로 자동 검출 → 누락 시 즉시 실패.
_CLOUDIUM_MULTI_PATH_KEYS = frozenset({
    "req_paths",
})

# Cloudium 모드 자체를 관리하는 endpoint는 검사 제외 (chicken-and-egg 방지).
# **D1 fix**: 과거 startswith 매칭은 `/api/file-mode/*` 신규 endpoint를 자동 우회시켰음
# (deny-by-default 위반). frozenset + 정확 매치로 강화하고 명시 endpoint만 화이트리스트.
_CLOUDIUM_EXEMPT_PATHS = frozenset({
    "/api/file-mode",            # 모드 조회/전환 자체
    "/api/file-mode/browse-file",
    "/api/file-mode/check-access",
    "/api/health",
    "/api/metrics",
    "/api/cache/clear",
    "/api/scm/register",
    "/api/scm/list",
})

# **N14 fix**: SCM 관리 endpoint 명시 prefix 화이트리스트 (정확 prefix만).
# `/api/scm/` 전체 exempt는 미래 신규 endpoint(/api/scm/sync 등)를 자동 우회시켜
# D1 fix(deny-by-default)를 약화시키므로 명시 patterns로 좁힘.
# 동적 path parameter용 — `path == prefix` 또는 `path.startswith(prefix + "/")` 매칭.
_CLOUDIUM_EXEMPT_SCM_PREFIXES = (
    "/api/scm/update/",
    "/api/scm/delete/",
    "/api/scm/test/",
    "/api/scm/audit/",
    "/api/scm/status/",
    "/api/scm/impact-jobs/",
    "/api/scm/change-history/",
)


def _is_exempt(path: str) -> bool:
    """D1: trailing slash 차이까지 정확 매치. 미지의 /api/file-mode/* 는 미들웨어 통과.

    **N9 fix (A)**: SCM 관리 endpoint(register/update/delete/test/audit/status/
    impact-jobs/change-history/link-docs)는 메타데이터 관리만 수행하고 사용자 path를
    실제 read하지 않으므로 PATH_KEYS scan 면제. 후속 sync/impact/doc-gen endpoint는
    그대로 PATH_KEYS scan + endpoint enforce_resolver_access + resolver
    _gate_then_allow 3중 검증 유지.

    **N14 fix**: 과거 `/api/scm/` 전체 startswith는 신규 endpoint 자동 우회 위험.
    명시 prefix 화이트리스트(_CLOUDIUM_EXEMPT_SCM_PREFIXES)로 좁힘.
    """
    if path in _CLOUDIUM_EXEMPT_PATHS or path.rstrip("/") in _CLOUDIUM_EXEMPT_PATHS:
        return True
    # 동적 path parameter exempt (/api/scm/update/{id} 등)
    for prefix in _CLOUDIUM_EXEMPT_SCM_PREFIXES:
        if path == prefix.rstrip("/") or path.startswith(prefix):
            return True
    # /api/scm/{id}/link-docs — id가 가운데에 있는 동적 path
    if path.startswith("/api/scm/") and path.endswith("/link-docs"):
        return True
    return False


def _cloudium_blocked_response(message: str) -> JSONResponse:
    """미들웨어 차단 응답 — frontend api.js의 detail 매칭과 일관성 유지."""
    return JSONResponse(
        {
            "ok": False,
            "code": "CLOUDIUM_BLOCKED",
            "detail": message,  # api.js가 j.detail을 우선 추출 → 사용자 친화 메시지
        },
        status_code=403,
    )


class CloudiumBlockedException(Exception):
    """**W-N1 fix**: endpoint에서 cloudium 정책 위반 시 raise.

    fastapi exception handler(`main.py` 등록)가 받아 미들웨어와 동일한 JSON shape
    (`{ok, code: "CLOUDIUM_BLOCKED", detail}`) 응답으로 변환. HTTPException(detail=str)을
    그대로 쓰면 응답이 `{detail}`만 되어 미들웨어 차단 응답과 shape 불일치 — 그러면
    frontend가 정책 위반을 단일 분기로 처리하기 어려움.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _check_path_value(key: str, value, resolver, validated: list) -> bool:
    """단일 키-값에 대해 PATH_KEYS / MULTI_PATH_KEYS 매칭 검사.

    매칭되면 resolver.check_access를 호출하고 validated에 추가. 반환값은 처리됐는지 여부
    (True면 호출자가 재귀 진입 안 함).

    **D2 fix**: multi-path 키는 _parse_path_list로 split 후 각 element 검사.
    """
    if not isinstance(value, str) or not value:
        return False
    if key in _CLOUDIUM_PATH_KEYS:
        resolver.check_access(value)
        validated.append(value)
        return True
    if key in _CLOUDIUM_MULTI_PATH_KEYS:
        for element in _parse_path_list(value):
            resolver.check_access(element)
            validated.append(element)
        return True
    return False


def _scan_dict_for_paths(data, resolver, validated: list, parent_key: str = ""):
    """dict/list 재귀 순회하며 PATH_KEYS / MULTI_PATH_KEYS 매칭 키의 string 값을 검사.

    검사 통과한 path는 validated 리스트에 추가 — 미들웨어가 이후 read 메서드
    호출 시 ContextVar로 마킹해 W1 이중 검사를 회피한다.

    **C-N1 fix**: list 값을 가진 PATH_KEYS/MULTI_PATH_KEYS 키는 element가
    string일 때도 검사. 예: `{"paths": ["//corp/a", "//corp/b"]}` — 부모 key를
    `parent_key`로 전달해 list element string을 동일 화이트리스트로 검사.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, list):
                # list 값: 단순 element들에 부모 key를 전달해 검사 (C-N1)
                _scan_dict_for_paths(value, resolver, validated, parent_key=key)
            elif isinstance(value, dict):
                _scan_dict_for_paths(value, resolver, validated)
            else:
                _check_path_value(key, value, resolver, validated)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                _scan_dict_for_paths(item, resolver, validated)
            elif isinstance(item, list):
                # 중첩 list — parent_key 유지 (예: nested list of paths)
                _scan_dict_for_paths(item, resolver, validated, parent_key=parent_key)
            elif parent_key and isinstance(item, str):
                # **C-N1 fix**: 부모 key가 PATH_KEYS / MULTI_PATH_KEYS면 string element도 검사
                _check_path_value(parent_key, item, resolver, validated)


class CloudiumGateMiddleware(BaseHTTPMiddleware):
    """Cloudium 모드일 때 요청 body/query의 path 키를 자동 게이트 검사.

    - LOCAL 모드면 통과
    - cloudium 모드면 PATH_KEYS 매칭 키 값에 resolver.check_access() 호출
    - 게이트 미실행 또는 화이트리스트 미통과 시 403 (detail 키로 사용자 메시지)
    - JSON, multipart/form-data, urlencoded 모두 검사 (multipart 우회 방지)
    - body는 receive 재구성으로 endpoint가 재읽기 가능하게 유지
    """

    async def dispatch(self, request: Request, call_next):
        # exempt: file-mode 관리 endpoint는 본 미들웨어가 막으면 안 됨 (D1 fix: 정확 매칭)
        path = request.url.path
        if _is_exempt(path):
            return await call_next(request)

        from backend.services.file_resolver import (
            CloudiumFileResolver,
            get_resolver,
            mark_path_validated,
            reset_path_validated,
        )
        resolver = get_resolver()
        if not isinstance(resolver, CloudiumFileResolver):
            return await call_next(request)

        validated: list = []

        # Query params 검사 (multi-path 키 포함)
        try:
            for key, value in request.query_params.multi_items():
                _check_path_value(key, value, resolver, validated)
        except PermissionError as e:
            return _cloudium_blocked_response(str(e))

        # Body 검사 — JSON / multipart / urlencoded 모두 처리
        if request.method in ("POST", "PUT", "PATCH"):
            ct = (request.headers.get("content-type") or "").lower()
            body = await request.body()

            try:
                if "application/json" in ct and body:
                    try:
                        data = json.loads(body)
                    except (json.JSONDecodeError, ValueError):
                        data = None
                    if data is not None:
                        _scan_dict_for_paths(data, resolver, validated)
                elif ("multipart/form-data" in ct or
                      "application/x-www-form-urlencoded" in ct):
                    # Form 필드의 PATH_KEYS / MULTI_PATH_KEYS 검사 — multipart 우회 방지.
                    # request.form()은 body를 소비하지만, 우리가 이미 await했으니
                    # starlette가 _body 캐시 사용하도록 유도.
                    request._body = body  # type: ignore[attr-defined]
                    form = await request.form()
                    for key, value in form.multi_items():
                        _check_path_value(key, value, resolver, validated)
            except PermissionError as e:
                return _cloudium_blocked_response(str(e))

            # body 재구성 — endpoint가 다시 읽을 수 있도록
            async def _receive():
                return {"type": "http.request", "body": body, "more_body": False}
            request._receive = _receive  # type: ignore[attr-defined]

        # W1: 검증된 path 집합 마킹 — read 메서드의 중복 검사 회피.
        # **W4 fix**: 과거 첫 번째 path만 마킹 → 모든 검증 path를 frozenset으로 마킹.
        # multi-path endpoint에서도 ContextVar W1 perf 효과 누적.
        token = mark_path_validated(validated)
        try:
            return await call_next(request)
        finally:
            reset_path_validated(token)
