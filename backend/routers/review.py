"""검토 기록 API — `/api/review/*` (R34, 계획 C-2).

규칙은 `workflow/quality/review.py` 에 있고 여기는 HTTP 번역뿐이다(`decision` 어휘·comment 검증도 거기 것을 쓴다).

| 엔드포인트 | 권한 | 계약 |
|---|---|---|
| `GET /runs/{run_id}` | `require_user`(로그인) | 기록 목록 + `stale`/`hash_unavailable`/`superseded_by`/`can_review`. run 없음 = **404** |
| `POST /runs/{run_id}` | `require_jwt_user` **+ `require_admin`**(§8 #8) | body `extra='forbid'`. 409 `STALE`/`HASH_UNAVAILABLE`/`VERSION_CONFLICT`, 503 `DB_BUSY` |
| `GET /history` | `require_user` | 감사 이력, `scm_id`/`doc_type`/`run_id`/`reviewer`/`limit`/`offset` |
| `GET /states?run_ids=1,2` | `require_user` | (R35) 목록 '검토' 열용 배치 — id 마다 `GET /runs/{id}` 와 같은 본문. ≤50개, 없는 id 는 `missing` |

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
    review_states,
    upsert_review,
)

_logger = logging.getLogger("devops_api.review")

router = APIRouter(prefix="/api/review", tags=["review"])

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_RUN_ID_RE = re.compile(r"^[0-9]{1,12}$")
# 배치 상한 — 목록 한 페이지(`/api/quality/runs` limit 50)와 같다. 넘으면 422(조용히 자르지 않는다).
STATES_MAX_IDS = 50


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


def _parse_run_ids(raw: str) -> list[int]:
    """`1,2,3` → [1,2,3]. 비정수·0·상한 초과는 422 — 일부만 받아 '없음' 으로 접지 않는다."""
    ids: list[int] = []
    for tok in str(raw or "").split(","):
        t = tok.strip()
        if not t:
            continue
        if not _RUN_ID_RE.match(t) or int(t) < 1:
            raise HTTPException(status_code=422, detail={"code": "BAD_RUN_IDS", "message": f"run_ids 항목이 정수가 아닙니다: {t[:20]!r}"})
        n = int(t)
        if n not in ids:
            ids.append(n)
    if not ids:
        raise HTTPException(status_code=422, detail={"code": "BAD_RUN_IDS", "message": "run_ids 가 비었습니다"})
    if len(ids) > STATES_MAX_IDS:
        raise HTTPException(
            status_code=422,
            detail={"code": "BAD_RUN_IDS", "message": f"run_ids 는 최대 {STATES_MAX_IDS}개입니다 ({len(ids)}개)"},
        )
    return ids


@router.get("/states")
def get_states(
    run_ids: str = Query(..., min_length=1, max_length=800),
    user: str = Depends(require_user),
) -> Dict[str, Any]:
    """(R35) 목록 '검토' 열 — 단건과 **같은 판정기**(복제 없음). 없는 id 는 404 가 아니라 `missing`.

    세션 하나 + 누적 재해시 예산(`BATCH_REHASH_BUDGET_BYTES`) — 넘는 run 은 `current_basis_reason='batch_budget'`.
    응답에 `output_path` 는 없다(리뷰 W4).
    """
    ids = _parse_run_ids(run_ids)
    try:
        return review_states(_open_session, ids, can_review=bool(is_admin(user)))
    except ReviewError as exc:
        raise _http(exc) from None


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
