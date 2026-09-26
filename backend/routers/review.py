"""검토 기록 API — `/api/review/*` (R34, 계획 C-2).

규칙은 `workflow/quality/review.py` 에 있고 여기는 HTTP 번역뿐이다(`decision` 어휘·comment 검증도 거기 것을 쓴다).

| 엔드포인트 | 권한 | 계약 |
|---|---|---|
| `GET /runs/{run_id}` | `require_user`(로그인) | 기록 목록 + `stale`/`hash_unavailable`/`superseded_by`/`can_review`+`review_block_reason`/`created_by`/`approved`. run 없음 = **404** |
| `POST /runs/{run_id}` | `require_reviewer` = JWT **+ admin 또는 승인자**(R48-a, §8 #8 (b)) | body `extra='forbid'`. 403 `REVIEWER_REQUIRED`/`SELF_REVIEW`(자기 run), 409 `STALE`/`HASH_UNAVAILABLE`/`VERSION_CONFLICT`, 503 `DB_BUSY` |
| `GET /history` | `require_user` | 감사 이력, `scm_id`/`doc_type`/`run_id`/`reviewer`/`limit`/`offset`. 남의 이름 필터는 **403** |
| `GET /states?run_ids=1,2` | `require_user` | (R35) 목록 '검토' 열용 배치 — id 마다 `GET /runs/{id}` 와 같은 본문. ≤50개, 없는 id 는 `missing` |
| `GET /runs/{run_id}/issues` | `require_user` | (R48-b) 문제 목록(생성 중 기록 + 사이드카 파생 + 점수 미달). run 없음 = **404** |
| `POST /runs/{run_id}/issues/explain` | `require_user` | (R48-b) Gemini 설명 — body `{use_llm?}` `extra='forbid'`. 실패는 룰 문장 + `generated_by:"rule"` |

- 200 + `{"error": …}` 를 **절대** 돌려주지 않는다 — `api.js` 는 `res.ok` 만 본다(quality.py `get_run` 과 같은 이유).
- 경로·파일명·신원은 클라이언트가 보내지 않는다(run_id 만 — `evidence` 와 같은 구조).
- (R37 D-1) 조회 3종은 `Viewer` 를 만들어 넘길 뿐 **권한을 판정하지 않는다** — `can_review` 는 POST 의 의존성과
  같은 조건(admin **그리고** Bearer)이라야 하고, 검토자 이름은 admin·본인 밖에서 마스킹된다.
- 쓰기 실패는 fail-loud(`record_run` 의 `return -1` 관용을 따르지 않는다).
- 핸들러는 전부 `def`(스레드풀) — GET 이 산출물 파일을 다시 읽어 해시할 수 있다(세션 밖, 크기 상한·캐시는 서비스).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.dependencies.auth import has_bearer, require_jwt_user, require_user
from backend.services.admin_users import is_admin, mask_user
from backend.services.approvers import is_approver
from workflow.quality.review import (
    AUTH_METHOD_JWT,
    COMMENT_MAX_LEN,
    DECISIONS,
    ReviewError,
    Viewer,
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


def _viewer(request: Request, user: str) -> Viewer:
    """요청에서 **사실 넷**만 읽는다 — 판정은 `Viewer` 가 한다(권한 규칙을 라우터에 복제하지 않는다)."""
    return Viewer(
        name=user, is_admin=bool(is_admin(user)), has_bearer=has_bearer(request),
        is_approver=bool(is_approver(user)),
    )


def require_reviewer(jwt_user: str = Depends(require_jwt_user)) -> str:
    """(R48-a) 검토 쓰기 주체 — JWT 로 로그인한 **admin 또는 승인자**(`config/approvers.json`).

    `Viewer.is_reviewer` 와 같은 두 목록을 본다(조회의 `can_review` 약속 = 쓰기의 통과 조건, R37 D-1).
    아니면 403 `REVIEWER_REQUIRED` — 401 이 아니다(신원은 있고 역할이 없다).
    """
    if is_admin(jwt_user) or is_approver(jwt_user):
        return jwt_user
    _logger.warning("review gate: user=%s is neither admin nor approver", mask_user(jwt_user))
    raise HTTPException(
        status_code=403,
        detail={
            "code": "REVIEWER_REQUIRED",
            "message": "검토 기록은 admin 또는 승인자만 남길 수 있습니다 — 관리자에게 승인자 등록을 요청하세요",
        },
    )


def _open_session():
    from workflow.quality.db import get_session, init_db

    init_db()
    return get_session()


@router.get("/runs/{run_id}")
def get_review(run_id: int, request: Request, user: str = Depends(require_user)) -> Dict[str, Any]:
    try:
        return review_state(_open_session, run_id, viewer=_viewer(request, user))
    except ReviewError as exc:
        raise _http(exc) from None


@router.post("/runs/{run_id}")
def post_review(
    run_id: int,
    body: ReviewBody,
    jwt_user: str = Depends(require_reviewer),
) -> Dict[str, Any]:
    """검토 기록 생성/갱신. 본문 `created` 로 구분한다(프론트 헬퍼가 상태코드를 안 본다).

    (R48-a) `require_reviewer` = Bearer(`require_jwt_user`) + admin **또는** 승인자. 자기 승인(`created_by ==
    reviewer`)은 서비스가 403 `SELF_REVIEW` 로 막는다 — 역할 검사는 사람 단위, 4-eyes 는 run 단위라 층이 다르다.
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
    request: Request,
    run_ids: str = Query(..., min_length=1, max_length=800),
    user: str = Depends(require_user),
) -> Dict[str, Any]:
    """(R35) 목록 '검토' 열 — 단건과 **같은 판정기**(복제 없음). 없는 id 는 404 가 아니라 `missing`.

    세션 하나 + 누적 재해시 예산(`BATCH_REHASH_BUDGET_BYTES`) — 넘는 run 은 `current_basis_reason='batch_budget'`.
    응답에 `output_path` 는 없다(리뷰 W4).
    """
    ids = _parse_run_ids(run_ids)
    try:
        return review_states(_open_session, ids, viewer=_viewer(request, user))
    except ReviewError as exc:
        raise _http(exc) from None


class ExplainBody(BaseModel):
    """`extra='forbid'`. `use_llm=false` 는 룰 문장만(테스트·LLM 없는 환경)."""

    model_config = ConfigDict(extra="forbid")

    use_llm: bool = True


def _issues_payload(run_id: int) -> Dict[str, Any]:
    from workflow.quality.issues import RunNotFound, collect_run_issues

    try:
        with _open_session() as session:
            return collect_run_issues(session, run_id)
    except RunNotFound:
        raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": f"run_id {run_id} not found"}) from None


@router.get("/runs/{run_id}/issues")
def get_run_issues(run_id: int, _user: str = Depends(require_user)) -> Dict[str, Any]:
    """(R48-b) run 의 **문제 목록** — 생성 중 기록(meta) + 사이드카 근거 + DB 점수를 한 어휘로(`workflow/quality/issues.py`).

    로그인 사용자 누구나(승인자는 admin 이 아니다 — 승인 전에 봐야 한다). 서버 절대경로는 싣지 않는다.
    """
    return _issues_payload(run_id)


@router.post("/runs/{run_id}/issues/explain")
def explain_run_issues(run_id: int, body: Optional[ExplainBody] = None, _user: str = Depends(require_user)) -> Dict[str, Any]:
    """(R48-b) 문제 목록을 Gemini 로 풀어 설명한다 — **버튼으로만** 부를 것(페이지 로드마다 부르지 않는다).

    숫자는 만들지 않는다(프롬프트 밖 숫자 → 폐기), 없는 문제도 만들지 않는다(코드 부분집합). 실패·비활성은 룰 문장으로
    내려가고 `generated_by`/`model`/`llm_reason` 이 출처를 말한다(`backend/services/issue_explainer.py`).
    """
    from backend.services.issue_explainer import explain_issues

    payload = _issues_payload(run_id)
    return explain_issues(payload, use_llm=(body.use_llm if body is not None else True))


@router.get("/history")
def get_history(
    request: Request,
    scm_id: Optional[str] = Query(None, max_length=64),
    doc_type: Optional[str] = Query(None, max_length=16),
    run_id: Optional[int] = Query(None, ge=1),
    reviewer: Optional[str] = Query(None, max_length=120),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: str = Depends(require_user),
) -> Dict[str, Any]:
    try:
        with _open_session() as session:
            return history(
                session, scm_id=scm_id, doc_type=doc_type, run_id=run_id, reviewer=reviewer,
                limit=limit, offset=offset, viewer=_viewer(request, user),
            )
    except ReviewError as exc:
        raise _http(exc) from None
