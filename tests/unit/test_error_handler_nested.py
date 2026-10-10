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
        """빈 dict — fallback code + message.

        43차 W24 fix: 이전 `str({})` = "{}" 출력 → 사용자 혼란.
        status-aware fallback (`HTTP <status> error`) 사용.
        """
        exc = HTTPException(status_code=500, detail={})
        status, body = _call(exc)
        assert status == 500
        assert body["error"]["code"] == "HTTP_500"
        # 43차 W24: "{}" repr 차단 — status-aware message
        assert body["error"]["message"] == "HTTP 500 error"
        # extra detail 없음
        assert "detail" not in body["error"]

    def test_dict_with_only_code_no_message(self):
        """43차 W24: code만 있고 message 없는 dict — fallback message.

        '{'code': 'SOMETHING'}' raw repr이 frontend에 노출되지 않도록.
        """
        exc = HTTPException(status_code=422, detail={"code": "BAD_INPUT"})
        status, body = _call(exc)
        assert status == 422
        assert body["error"]["code"] == "BAD_INPUT"
        # message가 "{'code': 'BAD_INPUT'}"가 아니라 fallback
        assert body["error"]["message"] == "HTTP 422 error"

    def test_dict_with_empty_string_message(self):
        """44차 W28: message 키는 있지만 빈 string — fallback 사용.

        의도적 빈 message는 사용자 혼란 방지 정책. 호출 측은 명시적 message 제공 필요.
        """
        exc = HTTPException(
            status_code=403,
            detail={"code": "FORBIDDEN", "message": ""},
        )
        status, body = _call(exc)
        assert status == 403
        assert body["error"]["code"] == "FORBIDDEN"
        # 빈 string이 그대로 노출되지 않고 status-aware fallback 사용
        assert body["error"]["message"] == "HTTP 403 error"

    def test_dict_with_none_message(self):
        """44차 W28: message 키 None — fallback 사용 (raise 측 누락 간주)."""
        exc = HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR", "message": None},
        )
        status, body = _call(exc)
        assert status == 500
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert body["error"]["message"] == "HTTP 500 error"
