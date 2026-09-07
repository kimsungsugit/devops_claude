"""검토 기록 API — `/api/review/*` (R34, 계획 C-2).

규칙은 `workflow/quality/review.py` 에 있고 여기는 HTTP 번역뿐이다(`decision` 어휘·comment 검증도 거기 것을 쓴다).

| 엔드포인트 | 권한 | 계약 |
|---|---|---|
| `GET /runs/{run_id}` | `require_user`(로그인) | 기록 목록 + `stale`/`hash_unavailable`/`superseded_by`/`can_review`. run 없음 = **404** |
| `POST /runs/{run_id}` | `require_jwt_user` **+ `require_admin`**(§8 #8) | body `extra='forbid'`. 409 `STALE`/`HASH_UNAVAILABLE`/`VERSION_CONFLICT`, 503 `DB_BUSY` |
| `GET /history` | `require_user` | 감사 이력, `scm_id`/`doc_type`/`run_id`/`reviewer`/`limit`/`offset` |

- 200 + `{"error": …}` 를 **절대** 돌려주지 않는다 — `api.js` 는 `res.ok` 만 본다(quality.py `get_run` 과 같은 이유).
- 경로·파일명·신원은 클라이언트가 보내지 않는다(run_id 만 — `evidence` 와 같은 구조).
- 쓰기 실패는 fail-loud(`record_run` 의 `return -1` 관용을 따르지 않는다).
- 핸들러는 전부 `def`(스레드풀) — GET 이 산출물 파일을 다시 읽어 해시할 수 있다(세션 밖, 크기 상한·캐시는 서비스).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.dependencies.admin import require_admin
from backend.dependencies.auth import require_jwt_user, require_user
from backend.services.admin_users import is_admin, mask_user
from workflow.quality.review import (
    AUTH_METHOD_JWT,
    COMMENT_MAX_LEN,
    DECISIONS,
    ReviewError,
    comment_violation,
    history,
    review_state,
    upsert_review,
)

_logger = logging.getLogger("devops_api.review")

router = APIRouter(prefix="/api/review", tags=["review"])

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ReviewBody(BaseModel):
    """`extra='forbid'` — 미지 키는 422(S12). 경로·파일명·신원 필드는 없다."""

    model_config = ConfigDict(extra="forbid")

    # 어휘의 단일 출처는 서비스 `DECISIONS` — `Literal[튜플]` 은 그 값들의 Literal 이다(리뷰 W4).
    decision: Literal[DECISIONS]  # type: ignore[valid-type]
    comment: Optional[str] = Field(default=None, max_length=COMMENT_MAX_LEN)
    expected_sha256: str = Field(..., min_length=64, max_length=64)
    # strict — "1" 같은 문자열을 정수로 접지 않는다(낙관적 잠금 값은 화면이 받은 그대로여야 한다).
    version: Optional[int] = Field(default=None, ge=1, strict=True)

    @field_validator("expected_sha256")
    @classmethod
    def _sha_hex(cls, v: str) -> str:
        if not _SHA256_RE.match(v or ""):
            raise ValueError("expected_sha256 must be 64 hex chars")
        return v.lower()

    @field_validator("comment")
    @classmethod
    def _comment_ok(cls, v: Optional[str]) -> Optional[str]:
        bad = comment_violation(v)
        if bad:
            raise ValueError(bad)
        return v


def _http(exc: ReviewError) -> HTTPException:
    """서비스 예외 → HTTPException(dict detail → `error.{code,message,detail}`, error_handler 규약).

    `code`/`message` 를 **뒤에** 두어 extra 가 덮어쓰지 못하게 한다(리뷰 I1).
    """
    return HTTPException(
        status_code=exc.status,
        detail={**exc.extra, "code": exc.code, "message": exc.message},
    )


def _open_session():
    from workflow.quality.db import get_session, init_db

    init_db()
    return get_session()


@router.get("/runs/{run_id}")
def get_review(run_id: int, user: str = Depends(require_user)) -> Dict[str, Any]:
    try:
        return review_state(_open_session, run_id, can_review=bool(is_admin(user)))
    except ReviewError as exc:
        raise _http(exc) from None


@router.post("/runs/{run_id}")
def post_review(
    run_id: int,
    body: ReviewBody,
    jwt_user: str = Depends(require_jwt_user),
    _admin: str = Depends(require_admin),
) -> Dict[str, Any]:
    """검토 기록 생성/갱신. 본문 `created` 로 구분한다(프론트 헬퍼가 상태코드를 안 본다).

    두 의존성은 같은 요청 contextvar 를 읽으므로 신원은 하나다 — `require_jwt_user` 가 Bearer 를, `require_admin`
    이 admin 등록을 각각 강제한다.
    """
    try:
        result = upsert_review(
            _open_session,
            run_id=run_id, reviewer=jwt_user, decision=body.decision, comment=body.comment,
            expected_sha256=body.expected_sha256, version=body.version, auth_method=AUTH_METHOD_JWT,
        )
    except ReviewError as exc:
        raise _http(exc) from None
    _logger.info(
        "review %s: run=%s decision=%s by=%s",
        "create" if result["created"] else "update", run_id, body.decision, mask_user(jwt_user),
    )
    return result


@router.get("/history")
def get_history(
    scm_id: Optional[str] = Query(None, max_length=64),
    doc_type: Optional[str] = Query(None, max_length=16),
    run_id: Optional[int] = Query(None, ge=1),
    reviewer: Optional[str] = Query(None, max_length=120),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user: str = Depends(require_user),
) -> Dict[str, Any]:
    with _open_session() as session:
        return history(
            session, scm_id=scm_id, doc_type=doc_type, run_id=run_id, reviewer=reviewer,
            limit=limit, offset=offset,
        )
