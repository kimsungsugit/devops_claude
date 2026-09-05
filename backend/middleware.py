"""API 미들웨어 — Rate limiting, request logging, security headers, Cloudium gate."""
from __future__ import annotations

import json
import logging
import time
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
    "srs_path", "sds_path", "syrs_path",
    "template_path", "ai_example_path", "ai_examples_path",
    "source_root", "source_dir", "report_dir", "cache_root",
    "folder", "root", "status_path",
    "validation_report_path", "residual_report_path",
    "stp_path", "hsis_path", "output_dir",
    # 같은 종류의 납품 정본 — 템플릿 후보로 쓰인다(`docgen_template_source`).
    # cloudium(`U:`)에 등록되므로 다른 문서 경로와 같은 게이트를 타야 한다.
    "reference_doc_path",
    # SwReport 통합 Summary — source_paths(JSON list)의 element(단일 path)는 C-N1
    # list 처리가 parent_key="source_paths"로 _check_path_value를 호출하므로 여기 등록 시
    # 각 element가 cloudium gate 검사됨 (리뷰 S3/X4 — 방어심층 1단 복원).
    "source_paths",
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


def _cloudium_blocked_response(message: str, request_path: str = "") -> JSONResponse:
    """미들웨어 차단 응답 — frontend api.js의 detail 매칭과 일관성 유지.

    차단 메시지를 backend log에도 warning 출력하여 어떤 path가 어느 endpoint에서
    막혔는지 즉시 진단 가능 (사용자 보고 시점에 backend log만 봐도 원인 파악).
    """
    import logging
    _log = logging.getLogger("devops_api")
    _log.warning("[cloudium-blocked] endpoint=%s detail=%s", request_path or "?", message)
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


class CloudiumGateMiddleware:
    """Cloudium 모드일 때 요청 body/query의 path 키를 자동 게이트 검사.

    - LOCAL 모드면 통과
    - cloudium 모드면 PATH_KEYS 매칭 키 값에 resolver.check_access() 호출
    - 게이트 미실행 또는 화이트리스트 미통과 시 403 (detail 키로 사용자 메시지)
    - JSON, multipart/form-data, urlencoded 검사 (multipart 우회 방지)
    - body는 message replay 패턴으로 endpoint가 재읽기 가능

    56차 T307 — BaseHTTPMiddleware → 순수 ASGI middleware 리팩토링.
    `request._receive = ...` 재정의 제거 → starlette receive chain 충돌 (known
    issue #1438 "RuntimeError: Unexpected message received: http.request") 차단.
    다중 미들웨어 스택 + StreamingResponse 응답과 호환.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # ASGI lifespan / websocket 등 비-HTTP는 그대로 통과
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path: str = scope.get("path", "")
        if _is_exempt(path):
            return await self.app(scope, receive, send)

        from backend.services.file_resolver import (
            CloudiumFileResolver,
            get_resolver,
            mark_path_validated,
            reset_path_validated,
        )
        resolver = get_resolver()
        if not isinstance(resolver, CloudiumFileResolver):
            return await self.app(scope, receive, send)

        validated: list = []

        # Query params 검사 — scope["query_string"] 파싱
        from urllib.parse import parse_qsl
        qs = scope.get("query_string", b"").decode("latin-1")
        try:
            for key, value in parse_qsl(qs, keep_blank_values=True):
                _check_path_value(key, value, resolver, validated)
        except PermissionError as e:
            await _send_cloudium_blocked(send, str(e), path)
            return

        method: str = scope.get("method", "GET")

        # Body 검사 — POST/PUT/PATCH만
        if method in ("POST", "PUT", "PATCH"):
            # receive를 한 번에 모두 소비 (body 재현용 캐싱)
            body = b""
            messages: list = []
            more_body = True
            while more_body:
                msg = await receive()
                messages.append(msg)
                if msg.get("type") == "http.request":
                    body += msg.get("body", b"")
                    more_body = msg.get("more_body", False)
                else:
                    # http.disconnect 등 비정상 종료
                    more_body = False

            ct = _header_value(scope, b"content-type").lower()

            try:
                if "application/json" in ct and body:
                    try:
                        data = json.loads(body)
                    except (json.JSONDecodeError, ValueError):
                        data = None
                    if data is not None:
                        _scan_dict_for_paths(data, resolver, validated)
                elif "application/x-www-form-urlencoded" in ct and body:
                    # urlencoded — parse_qsl로 직접 처리 (starlette 의존 X)
                    try:
                        for key, value in parse_qsl(
                            body.decode("utf-8"), keep_blank_values=True,
                        ):
                            _check_path_value(key, value, resolver, validated)
                    except UnicodeDecodeError:
                        pass
                elif "multipart/form-data" in ct and body:
                    # multipart — Starlette Request wrapping (cached receive로
                    # body 재읽기 가능). `python-multipart`는 FastAPI 의존성이라
                    # 이미 설치됨.
                    from starlette.requests import Request as _StarletteRequest

                    async def _cached_receive():
                        return {
                            "type": "http.request",
                            "body": body,
                            "more_body": False,
                        }

                    form_req = _StarletteRequest(scope, _cached_receive)
                    try:
                        form_data = await form_req.form()
                        for key, value in form_data.multi_items():
                            _check_path_value(key, value, resolver, validated)
                    except PermissionError:
                        # cloudium 정책 위반은 외부 handler로 위임 (raise)
                        raise
                    except Exception:
                        # multipart parse 실패만 silent — endpoint 단계
                        # deny-by-default (resolver 검증)로 안전망 유지
                        pass
            except PermissionError as e:
                await _send_cloudium_blocked(send, str(e), path)
                return

            # message replay — 다운스트림 endpoint가 다시 body 읽기 가능
            sent_count = 0

            async def replay_receive():
                nonlocal sent_count
                if sent_count < len(messages):
                    msg = messages[sent_count]
                    sent_count += 1
                    return msg
                # 모든 캐싱된 message 소비 후 → 원본 receive (disconnect 등)
                return await receive()

            token = mark_path_validated(validated)
            try:
                await self.app(scope, replay_receive, send)
                return
            finally:
                reset_path_validated(token)

        # GET/HEAD/OPTIONS 등 body 없음 — 원본 receive 그대로 전달
        token = mark_path_validated(validated)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_path_validated(token)


def _header_value(scope, name: bytes) -> str:
    """ASGI scope의 headers list에서 특정 헤더 값 추출 (소문자 비교).

    headers는 [(b"name", b"value"), ...] 형식. 없으면 빈 string.
    """
    name_lower = name.lower()
    for k, v in scope.get("headers", []):
        if k.lower() == name_lower:
            try:
                return v.decode("latin-1")
            except UnicodeDecodeError:
                return ""
    return ""


async def _send_cloudium_blocked(send, message: str, request_path: str) -> None:
    """ASGI send callable로 403 차단 응답 직접 송신.

    BaseHTTPMiddleware 시절 _cloudium_blocked_response가 반환한 JSONResponse를
    그대로 사용. JSONResponse는 ASGI response callable이라 await 호출 가능.
    """
    response = _cloudium_blocked_response(message, request_path)
    # 빈 receive — JSONResponse는 disconnect 감지 안 함 (단순 응답)
    async def _noop_receive():
        return {"type": "http.disconnect"}
    await response({"type": "http", "method": "POST", "path": request_path}, _noop_receive, send)
