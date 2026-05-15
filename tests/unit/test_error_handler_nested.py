"""42차 C3 — error_handler nested dict 처리 회귀.

40차 require_admin이 HTTPException(detail={code, message}) 형태로 raise →
41차 비판 평가에서 발견한 이중 wrapping 문제 (`{'code': 'HTTP_403', 'message':
"{'code': 'ADMIN_REQUIRED', ...}"}`).

42차 W6 fix: http_exception_handler가 dict detail을 직접 unpack —
code/message는 raw extraction + extra 키는 detail 필드로.

본 회귀가 향후 regression 방지 (backend 회귀 0건의 갭 해결).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.error_handler import http_exception_handler  # noqa: E402


class _FakeRequest:
    """http_exception_handler가 request 인자 받지만 본문 사용 안 함."""
    pass


def _call(exc: HTTPException) -> tuple[int, dict]:
    """async handler 호출 + JSONResponse → dict 추출."""
    response = asyncio.run(http_exception_handler(_FakeRequest(), exc))
    body = json.loads(response.body.decode("utf-8"))
    return (response.status_code, body)


class TestStrDetail:
    """기존 동작 — detail이 str일 때 `code=HTTP_<status>`."""

    def test_404_str_detail(self):
        status, body = _call(HTTPException(status_code=404, detail="Not Found"))
        assert status == 404
        assert body["ok"] is False
        assert body["error"]["code"] == "HTTP_404"
        assert body["error"]["message"] == "Not Found"

    def test_500_str_detail(self):
        status, body = _call(HTTPException(status_code=500, detail="server err"))
        assert status == 500
        assert body["error"]["code"] == "HTTP_500"


class TestDictDetail:
    """42차 W6 fix — detail이 dict면 unpack."""

    def test_admin_required_dict(self):
        """require_admin이 raise하는 형태 — code + message 추출."""
        exc = HTTPException(
            status_code=403,
            detail={
                "code": "ADMIN_REQUIRED",
                "message": "admin 권한 필요 (현재 사용자: guest)",
            },
        )
        status, body = _call(exc)
        assert status == 403
        # 이전(이중 wrapping): "{'code': 'ADMIN_REQUIRED', 'message': ...}"
        # 42차 fix: code/message 직접 사용
        assert body["error"]["code"] == "ADMIN_REQUIRED"
        assert body["error"]["message"] == "admin 권한 필요 (현재 사용자: guest)"
        # extra 키 없으면 detail 필드 없음
        assert "detail" not in body["error"]

    def test_auth_required_dict(self):
        exc = HTTPException(
            status_code=401,
            detail={"code": "AUTH_REQUIRED", "message": "X-User 헤더 필요"},
        )
        status, body = _call(exc)
        assert status == 401
        assert body["error"]["code"] == "AUTH_REQUIRED"
        assert body["error"]["message"] == "X-User 헤더 필요"

    def test_dict_with_extra_fields(self):
        """dict에 code/message 외 추가 키 → detail 필드로 보존."""
        exc = HTTPException(
            status_code=400,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "Invalid input",
                "field": "release_sw_version",
                "value": "bad",
            },
        )
        status, body = _call(exc)
        assert status == 400
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["error"]["detail"]["field"] == "release_sw_version"
        assert body["error"]["detail"]["value"] == "bad"

    def test_dict_missing_code_fallback(self):
        """code 없는 dict — HTTP_<status> fallback."""
        exc = HTTPException(
            status_code=403,
            detail={"message": "only message"},
        )
        status, body = _call(exc)
        assert body["error"]["code"] == "HTTP_403"
        assert body["error"]["message"] == "only message"

    def test_empty_dict_detail(self):
        """빈 dict — fallback code + message."""
        exc = HTTPException(status_code=500, detail={})
        status, body = _call(exc)
        assert status == 500
        assert body["error"]["code"] == "HTTP_500"
        # str({}) 또는 empty — 빈 string 또는 "{}"
        assert isinstance(body["error"]["message"], str)
