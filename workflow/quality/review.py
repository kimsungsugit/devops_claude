"""검토 기록(review) 서비스 — 판정을 산출물 **바이트**에 고정한다 (R34, 계획 C-2).

라우터(`backend/routers/review.py`)는 HTTP 번역만 하고 규칙은 전부 여기 있다. 규칙이 라우터에 복제되면
한쪽만 고쳐진다(이 저장소가 반복해 겪은 패턴). `decision` 어휘도 여기 `DECISIONS` 하나뿐이다.

## 계약

- 검토 단위는 **run 하나**(S7). 대상은 `GenerationRun.output_sha256`(R33) — 없으면 `HashUnavailable`(S6).
- 쓰기는 `expected_sha256 == run.output_sha256` 일 때만(S5). 다르면 `Stale` — 클라이언트가 본 산출물과 서버가
  기록한 산출물이 다르다는 뜻이고, 조용히 최신 값으로 갈아끼우지 않는다.
- 한 검토자는 run 당 기록 하나(UNIQUE). 갱신은 현재 `version` 을 같이 보내야 한다(S9 lost update).
  ⚠ (R34 리뷰 C1) "SELECT 해서 version 을 비교한 뒤 UPDATE" 는 lost update 를 **막지 못한다** — 두 세션이 같은
  version 을 읽고 차례로 UPDATE 하면 둘 다 200 이 된다(실측). 그래서 갱신은 `UPDATE … WHERE id=? AND version=?`
  한 문장으로 하고 rowcount 0 이면 `VersionConflict` 다. 생성 경합은 UNIQUE 가 잡고(IntegrityError) 같은 409 로 번역.
- 기록 + 감사행은 **한 세션**에서 flush 된다(S11) — 감사 INSERT 가 실패하면 기록도 남지 않는다.
- `stale` 은 컬럼이 아니라 **조회 시 계산**: 파일이 살아 있으면 지금 파일 해시와 스냅샷 비교, 아니면 **판단 불가
  (None)** — 파일이 없는데 기록 해시끼리 비교해 "같다(False)" 라고 말하지 않는다(리뷰 C2). 지우지 않는다(§8 #9).
- 같은 `(scm_id, doc_type)` 에 더 새로운 성공 run 이 있으면 `superseded_by`(TTL 대신, §8 #10).
- 파일 재해시는 DB 세션 **밖**에서 한다(리뷰 W3) — 46MB docx·UNC 경로가 커넥션 풀을 붙들지 않게. 크기 상한과
  (path, mtime_ns, size) 캐시를 둔다.
"""
from __future__ import annotations

import logging
import threading
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, ContextManager, Dict, List, Optional

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from workflow.quality.models import GenerationRun, ReviewAudit, ReviewRecord
from workflow.quality.recorder import resolve_output_path, sha256_of_file

_logger = logging.getLogger("workflow.quality.review")

DECISIONS = ("approved", "rejected", "needs_work")
AUTH_METHOD_JWT = "jwt"
# 재해시 상한 — UDS docx 실측 46MB. 이보다 크면 파일 기준 판단을 포기하고 사유를 낸다(무제한 읽기 금지, 리뷰 W3).
REHASH_MAX_BYTES = 512 * 1024 * 1024
COMMENT_MAX_LEN = 2000

# 검토 쓰기가 막힌 사유 — 화면이 "누구에게 무엇이 모자란가" 를 말할 수 있게 갈라 둔다.
# 하나로 접으면 "권한이 없습니다" 가 토큰 만료까지 삼켜, 재로그인하면 되는 사람이 관리자를 찾는다.
# (R48-a) `not_admin` → `not_reviewer`: 쓰기 주체가 admin **또는 승인자**(`config/approvers.json`)로 넓어졌다.
# `self_review` 는 run 단위 사유다 — 사람은 검토자인데 **이 run 은** 자기가 만든 것이라 못 쓴다(4-eyes).
BLOCK_NOT_REVIEWER = "not_reviewer"
BLOCK_JWT_REQUIRED = "jwt_required"
BLOCK_SELF_REVIEW = "self_review"


def is_same_identity(a: Optional[str], b: Optional[str]) -> bool:
    """사용자 이름 동일성 — `admin_users.is_admin`/`approvers.is_approver` 와 같은 규약(trim + lowercase).

    자기 승인 판정과 이름 노출 판정이 **같은 함수**를 쓴다. 한쪽만 대소문자를 접으면 `HBRND2` 가 만든 run 을
    `hbrnd2` 가 승인하는 길이 생긴다.
    """
    x = str(a or "").strip().lower()
    y = str(b or "").strip().lower()
    return bool(x) and bool(y) and x == y


@dataclass(frozen=True)
class Viewer:
    """이 응답을 받는 사람 — **쓰기 통과 여부와 이름 노출 범위를 여기서만** 판정한다 (R37 D-1).

    ⚠ 두 결함이 같은 뿌리였다:

    1. `can_review` 가 admin 여부만 봤다. 쓰기는 `require_jwt_user` **+** `require_admin` 인데
       조회는 `require_user`(Bearer 불요)라, `DEV_MODE_X_USER_FALLBACK=1` 에서 X-User 로 들어온 admin 이
       입력 폼을 받고 저장에서 401 을 맞았다 — **화면이 약속한 것을 서버가 거부**한다.
    2. 검토자 실명이 로그인한 누구에게나 나갔다. 같은 이름을 서버 로그는 `mask_user` 로 가리면서
       API 응답은 원문으로 냈다 — 한 값에 두 기준이면 느슨한 쪽이 사실상의 정책이 된다.

    그래서 "쓸 수 있는 사람" 과 "이름을 볼 수 있는 사람" 을 같은 객체가 답한다. 라우터는 요청에서
    네 사실(이름·admin 여부·승인자 여부·Bearer 여부)만 읽어 넘기고, 판정은 하지 않는다.

    (R48-a) 쓰기 주체는 **admin 또는 승인자**(`is_reviewer`). 사람 단위 판정(`can_review`)과 run 단위 판정
    (`can_review_run` — 자기가 만든 run 은 불가)을 나눈다. 목록 열·패널·POST 가 전부 후자를 써야 한다.
    """

    name: str = ""
    is_admin: bool = False
    has_bearer: bool = False
    is_approver: bool = False

    @property
    def is_reviewer(self) -> bool:
        """검토 기록을 남길 수 있는 **역할**인가 — admin 또는 승인자."""
        return bool(self.is_admin or self.is_approver)

    @property
    def can_review(self) -> bool:
        """`POST /api/review/runs/{id}` 의 **사람 단위** 조건 — 그 endpoint 의 의존성(역할 + Bearer)과 같다.

        run 단위(자기 승인)는 `can_review_run` 이 더한다 — 이 값만 보고 폼을 그리면 자기 run 에서 403 을 맞는다.
        """
        return bool(self.is_reviewer and self.has_bearer)

    @property
    def block_reason(self) -> Optional[str]:
        """`can_review` 가 False 인 이유. 통과하면 None."""
        if self.can_review:
            return None
        return BLOCK_NOT_REVIEWER if not self.is_reviewer else BLOCK_JWT_REQUIRED

    def can_review_run(self, created_by: Optional[str]) -> bool:
        """이 run 에 기록을 남길 수 있는가 — 사람 조건 **그리고** 자기가 만든 run 이 아님(4-eyes).

        `created_by` 가 None(구 run·신원 없이 만든 run)이면 자기 승인을 **판정할 수 없고**, 막지 않는다 —
        막으면 R48 이전 run 750건이 영구 미승인이다. 대신 응답 `created_by:null` 이 그 사실을 공시한다.
        """
        return self.can_review and not is_same_identity(self.name, created_by)

    def block_reason_for_run(self, created_by: Optional[str]) -> Optional[str]:
        if self.can_review_run(created_by):
            return None
        if self.can_review:
            return BLOCK_SELF_REVIEW
        return self.block_reason

    def _is_self(self, reviewer: str) -> bool:
        return is_same_identity(self.name, reviewer)

    def may_see_names(self, reviewer: str) -> bool:
        """이 사람에게 `reviewer` 의 실명을 보여도 되는가 — 마스킹과 이력 필터가 **같은 조건**을 쓴다.

        ⚠ **Bearer 를 함께 요구한다**(R37 리뷰 W3). `DEV_MODE_X_USER_FALLBACK=1`(D-1 이 근거로 든 바로 그
          환경)에서는 `X-User: <admin>` 헤더 한 줄로 `is_admin` 이 True 가 된다. 쓰기는 `require_jwt_user`
          가 막지만 **읽기 통제는 그대로 뚫려** 전 검토자 실명이 나가고, `X-User: <피해자>` 로는 자기일치를
          만들어 이력 필터의 403 까지 우회된다. 신원을 위조할 수 있는 채널로는 이름을 풀지 않는다.
        """
        return bool(self.has_bearer) and (self.is_admin or self._is_self(reviewer))

    def visible(self, reviewer: Optional[str]) -> Optional[str]:
        """검토자 이름 — admin 과 **본인**에게는 원문(둘 다 Bearer 필요), 나머지에게는 마스킹.

        본인을 가리지 않는 이유: 자기가 남긴 판정을 못 알아보면 갱신 대상을 고를 수 없다.
        마스킹 방식은 기존 단일 출처(`admin_users.mask_user`)를 그대로 쓴다 — 여기서 다시 만들면
        로그와 API 가 또 갈린다. import 는 지연(계층: workflow → backend 는 recorder 의 선례).
        """
        if reviewer is None:
            return None
        if self.may_see_names(reviewer):
            return reviewer
        from backend.services.admin_users import mask_user

        return mask_user(reviewer)


class ReviewError(Exception):
    """라우터가 HTTP 로 번역하는 규칙 위반. `code` 는 응답 `error.code` 로 그대로 나간다."""

    status = 409
    code = "REVIEW_ERROR"

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra


class RunNotFound(ReviewError):
    status = 404
    code = "RUN_NOT_FOUND"


class ReviewerFilterForbidden(ReviewError):
    """(R37 D-1) 남의 이름으로 감사 이력을 거르려는 조회 — 마스킹을 질의로 우회하는 경로."""

    status = 403
    code = "REVIEWER_FILTER_FORBIDDEN"


class IdentityRequired(ReviewError):
    status = 401
    code = "AUTH_REQUIRED"


class SelfReview(ReviewError):
    """(R48-a) 자기가 만든 run 에 판정을 남기려 했다 — 검토는 만든 사람과 다른 사람이 한다(4-eyes)."""

    status = 403
    code = "SELF_REVIEW"


class NotApproved(ReviewError):
    """(R48-a) 승인 기록 없는 바이트를 게시하려 했다 — `approved` 판정이 **그 해시**에 있어야 한다."""

    status = 409
    code = "NOT_APPROVED"


class HashUnavailable(ReviewError):
    code = "HASH_UNAVAILABLE"


class Stale(ReviewError):
    code = "STALE"


class VersionConflict(ReviewError):
    code = "VERSION_CONFLICT"


class DbBusy(ReviewError):
    """SQLite 단일 라이터 잠금을 `busy_timeout` 안에 못 얻었다 — 데이터는 그대로, 다시 시도하면 된다."""

    status = 503
    code = "DB_BUSY"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    # 저장은 tz-naive UTC → 응답에 offset 명시(quality.py `_run_to_dict` 와 같은 이유).
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt else None


# ── 입력 검증(라우터와 서비스가 같은 함수를 쓴다) ────────────────────────────────


def comment_violation(text: Optional[str]) -> Optional[str]:
    """comment 가 허용되지 않으면 사유 문자열, 괜찮으면 None.

    (리뷰 W6) C0 만 막으면 U+2028(줄 구분자)·U+202E(RLO, 문구 역전)·U+FEFF·U+0085 가 통과한다. 유니코드 범주로
    막는다: Cc(제어)·Cf(서식)·Zl·Zp — `\\n`·`\\t` 만 예외.
    """
    if text is None:
        return None
    if len(text) > COMMENT_MAX_LEN:
        return f"comment 는 {COMMENT_MAX_LEN}자 이하"
    for ch in text:
        if ch in ("\n", "\t"):
            continue
        if unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp"):
            return f"comment 에 제어·서식·구분 문자(U+{ord(ch):04X})는 허용하지 않는다(줄바꿈·탭 제외)"
    return None


# ── 산출물 현재 해시(세션 밖) ───────────────────────────────────────────────────

_HASH_CACHE: "OrderedDict[str, tuple[tuple[int, int], str]]" = OrderedDict()
_HASH_CACHE_MAX = 64
_HASH_CACHE_LOCK = threading.Lock()

# (R35 리뷰 C2) 배치 조회 한 번이 읽을 수 있는 **누적** 바이트. 파일 하나 상한(`REHASH_MAX_BYTES`)만으로는
# 50개 × 512MB 가 한 요청이라 스레드풀이 멎는다. 넘는 run 은 `basis='record'`·`batch_budget` 으로 정직하게 낸다.
BATCH_REHASH_BUDGET_BYTES = 64 * 1024 * 1024


def _cache_lookup(key: str, sig: "tuple[int, int]") -> Optional[str]:
    with _HASH_CACHE_LOCK:
        hit = _HASH_CACHE.get(key)
        if hit and hit[0] == sig:
            _HASH_CACHE.move_to_end(key)
            return hit[1]
    return None


def _cache_store(key: str, sig: "tuple[int, int]", digest: str) -> None:
    # LRU — 예전엔 가득 차면 `clear()` 통째라 경로 65개를 오가면 매번 전량 재해시였다(리뷰 C2).
    with _HASH_CACHE_LOCK:
        _HASH_CACHE[key] = (sig, digest)
        _HASH_CACHE.move_to_end(key)
        while len(_HASH_CACHE) > _HASH_CACHE_MAX:
            _HASH_CACHE.popitem(last=False)


def _cached_file_hash(p, budget: Optional[Dict[str, int]] = None) -> Optional[str]:
    """(mtime_ns, size) 가 같으면 재해시하지 않는다(선례 `reference_preview_cache`).

    `budget` 이 있으면(배치) 캐시 미스일 때 남은 바이트에서 파일 크기를 뺀다 — 모자라면 **읽지 않고 None**.
    캐시 적중은 예산을 쓰지 않는다.
    """
    st = p.stat()
    key = str(p)
    sig = (int(st.st_mtime_ns), int(st.st_size))
    hit = _cache_lookup(key, sig)
    if hit is not None:
        return hit
    if budget is not None:
        if sig[1] > budget.get("remaining", 0):
            return None
        budget["remaining"] = budget.get("remaining", 0) - sig[1]
    digest = sha256_of_file(p)
    _cache_store(key, sig, digest)
    return digest


def current_output_hash(
    output_path: Optional[str], recorded_sha256: Optional[str], *, budget: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """지금 산출물의 해시. `{"sha256", "basis": "file"|"record"|None, "basis_reason"}`.

    - `file`: `output_path` 가 살아 있어 **지금 파일**을 읽었다(캐시 적중이면 안 읽는다).
    - `record`: 파일 기준 판단을 못 해 run 의 기록 해시만 있다. `basis_reason` 이 왜인지 말한다 —
      `no_path` / `file_missing` / `not_a_file` / `too_large` / `unreadable` / `batch_budget`(배치 누적 예산 초과 —
      단건 조회는 예산이 없어 파일 기준으로 다시 잰다).
    - `None`: 둘 다 없다 → `hash_unavailable`.
    읽기 실패는 기록 해시로 물러나되 사유를 남긴다 — 조용히 "같다" 로 접지 않는다(리뷰 W3 ③).
    ⚠ DB 세션 밖에서 부를 것.
    """
    reason: Optional[str] = None
    if output_path:
        try:
            p = resolve_output_path(output_path)
            if not p.exists():
                reason = "file_missing"
            elif not p.is_file():
                reason = "not_a_file"
            elif p.stat().st_size > REHASH_MAX_BYTES:
                reason = "too_large"
            else:
                digest = _cached_file_hash(p, budget)
                if digest is not None:
                    return {"sha256": digest, "basis": "file", "basis_reason": None}
                reason = "batch_budget"
        except Exception as exc:
            _logger.warning("검토 대상 파일을 다시 읽지 못했다(%r) — 기록 해시로 물러난다: %s", output_path, exc)
            reason = "unreadable"
    else:
        reason = "no_path"
    if recorded_sha256:
        return {"sha256": recorded_sha256, "basis": "record", "basis_reason": reason}
    return {"sha256": None, "basis": None, "basis_reason": reason}


def _stale(snapshot: Optional[str], cur: Dict[str, Any]) -> Optional[bool]:
    """스냅샷 ↔ 지금 파일. 파일 기준이 아니면 **판단 불가(None)** — False 로 접지 않는다(리뷰 C2). 두 표면이 공유."""
    if not snapshot or cur.get("basis") != "file" or not cur.get("sha256"):
        return None
    return snapshot != cur["sha256"]


# ── 조회 ────────────────────────────────────────────────────────────────────────


def superseded_by(session: Session, run: GenerationRun) -> Optional[Dict[str, Any]]:
    """같은 (scm_id, doc_type) 의 더 새로운 성공 run. `scm_id` 가 NULL(미상)이면 비교하지 않는다."""
    if not run.scm_id:
        return None
    newer = (
        session.query(GenerationRun.id, GenerationRun.created_at)
        .filter(
            GenerationRun.scm_id == run.scm_id,
            GenerationRun.doc_type == run.doc_type,
            GenerationRun.status == "success",
            GenerationRun.id > run.id,
        )
        .order_by(GenerationRun.id.desc())
        .first()
    )
    return {"run_id": int(newer[0]), "created_at": _iso(newer[1])} if newer else None


def _meta_field(raw: Optional[str], key: str) -> Optional[str]:
    """`meta_json` 의 문자열 필드 하나. 없거나 못 읽으면 None(구 run — 미기록)."""
    if not raw:
        return None
    try:
        import json

        meta = json.loads(raw)
    except (ValueError, TypeError):
        return None
    v = meta.get(key) if isinstance(meta, dict) else None
    return str(v) if v else None


def _hash_reason_from_meta(raw: Optional[str]) -> Optional[str]:
    """R33 이 `meta_json.output_sha256_reason` 에 남긴 NULL 사유. 없으면 None(구 run — 사유 미기록)."""
    return _meta_field(raw, "output_sha256_reason")


def _gated_metric_count(run: GenerationRun) -> Optional[int]:
    for s in (getattr(run, "scores", None) or []):
        if str(getattr(s, "metric_name", "") or "") == "gated_metric_count":
            try:
                return int(s.value) if s.value is not None else None
            except (TypeError, ValueError):
                return None
    return None


def _record_plain(rec: ReviewRecord, *, viewer: Optional[Viewer] = None) -> Dict[str, Any]:
    """`viewer` 가 없으면 원문 — 내부 호출(테스트·스크립트)용이다. HTTP 응답 경로는 **반드시** 넘긴다
    (가드: `test_review_records.py::TestReviewerNameExposure`)."""
    return {
        "id": rec.id,
        "run_id": rec.run_id,
        "reviewer": viewer.visible(rec.reviewer) if viewer else rec.reviewer,
        "auth_method": rec.auth_method,
        "decision": rec.decision,
        "comment": rec.comment,
        "output_sha256": rec.output_sha256,
        "version": rec.version,
        "created_at": _iso(rec.created_at),
        "updated_at": _iso(rec.updated_at),
    }


def _load_state(session: Session, run_id: int, *, viewer: Optional[Viewer] = None) -> Dict[str, Any]:
    """세션 안에서 DB 만 읽는다(파일 I/O 없음)."""
    run = session.query(GenerationRun).filter_by(id=run_id).first()
    if not run:
        raise RunNotFound(f"run_id {run_id} not found", run_id=run_id)
    records: List[ReviewRecord] = (
        session.query(ReviewRecord).filter_by(run_id=run_id).order_by(ReviewRecord.id.asc()).all()
    )
    return {
        "run_id": run.id,
        "doc_type": run.doc_type,
        "scm_id": run.scm_id,
        # (R37 리뷰 C1) 빈 산출물 run 은 해시가 있어 검토가 **열린다** — 그러면 화면이 "무엇을 승인하는가" 를
        # 말할 수 있어야 한다. 이걸 안 실으면 패널이 아는 유일한 단서가 `gated_metric_count == null` 인데,
        # 그 문구는 *구 run(기록 이전)* 을 뜻해서 "잴 대상이 0건"(해당 없음)을 "기록이 안 됐다"(미측정)로
        # **틀리게 귀속**한다. 두 사실은 다르고, 감사 증거에서 그 차이는 결정적이다.
        "status": run.status,
        "empty_output_reason": _meta_field(run.meta_json, "empty_output_reason"),
        # (R48-a) 생성자 — 자기 승인 판정의 근거. 이름 노출은 검토자 이름과 **같은 규칙**(admin·본인만 원문).
        #   `created_by_known` 을 따로 두는 이유: 마스킹된 이름과 "기록 없음" 이 화면에서 같아 보이면 안 된다.
        "created_by": (viewer.visible(run.created_by) if viewer else run.created_by),
        "created_by_known": run.created_by is not None,
        "_created_by_raw": run.created_by,
        "output_path": run.output_path,
        "output_sha256": run.output_sha256,
        "hash_reason": _hash_reason_from_meta(run.meta_json) if run.output_sha256 is None else None,
        "superseded_by": superseded_by(session, run),
        "gated_metric_count": _gated_metric_count(run),
        "reviews": [_record_plain(r, viewer=viewer) for r in records],
        # (R48-a 리뷰 W1/W2) 승인 상태는 **바이트 범위** — 게시 게이트(`require_approved_bytes`)와 같은 질문·같은 함수.
        #   같은 바이트를 낸 다른 run(R47-k 이후 결정적 생성)의 승인도 이 run 의 승인이다. run 범위로 세면 화면은 "미승인",
        #   게시는 통과(또는 그 반대)로 갈린다.
        "_approval": approval_for_sha256(session, run.output_sha256 or ""),
    }


def review_state(
    open_session: Callable[[], ContextManager[Session]], run_id: int, *, viewer: Optional[Viewer] = None,
) -> Dict[str, Any]:
    """`GET /api/review/runs/{id}` 본문. DB 읽기는 세션 안, 파일 재해시는 세션 **밖**(리뷰 W3).

    run 이 없으면 `RunNotFound`(200+error 금지). `viewer` 가 쓰기 가능 여부와 이름 노출을 정한다(R37 D-1)
    — 라우터는 요청에서 사실만 읽어 넘기고 판정하지 않는다. `None` 이면 판정 없음(`can_review: null`).
    """
    with open_session() as session:
        st = _load_state(session, run_id, viewer=viewer)
    return _finish_state(st, viewer=viewer)


def _finish_state(st: Dict[str, Any], *, viewer: Optional[Viewer], budget: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """세션 밖 마무리 — 파일 재해시 + stale. 단건·배치가 **같은 판정기**를 쓴다(복제 금지)."""
    cur = current_output_hash(st["output_path"], st["output_sha256"], budget=budget)
    hash_unavailable = st["output_sha256"] is None
    for r in st["reviews"]:
        r["stale"] = _stale(r["output_sha256"], cur)
    created_by_raw = st.pop("_created_by_raw", None)
    approval = st.pop("_approval", None) or {"approved": False, "runs": []}
    st.update({
        # 검토 잠금(S6). 사유는 R33 의 meta — 구 run 은 사유 미기록(None).
        "hash_unavailable": hash_unavailable,
        "current_sha256": cur["sha256"],
        "current_basis": cur["basis"],
        "current_basis_reason": cur["basis_reason"],
        # run 의 기록 해시 ↔ 지금 파일. 파일 기준이 아니면 None(판단 불가) — False 로 접지 않는다.
        "stale": _stale(st["output_sha256"], cur),
        # (R48-a) **run 단위** 판정 — 역할·Bearer 에 자기 승인 차단까지. POST 의 검사와 같은 함수다.
        "can_review": viewer.can_review_run(created_by_raw) if viewer else None,
        # 왜 못 쓰는가 — 없으면 화면이 "admin 만" 한 문장으로 접어 토큰 만료를 권한 문제로 오독한다.
        "review_block_reason": viewer.block_reason_for_run(created_by_raw) if viewer else None,
        # 승인 상태 — "이 run 의 기록 바이트에 approved 가 있는가"(게시 게이트와 **같은 함수**). 지금 파일이 그 바이트와
        # 다르면 `stale` 이 따로 말한다 — 두 사실을 한 값으로 접지 않는다.
        "approved": bool(approval.get("approved")),
        "approved_runs": list(approval.get("runs") or []),
    })
    return st


def review_states(
    open_session: Callable[[], ContextManager[Session]], run_ids: List[int], *,
    viewer: Optional[Viewer] = None, budget_bytes: Optional[int] = None,
) -> Dict[str, Any]:
    """(R35) `GET /api/review/states` 본문 — 목록 '검토' 열. `{"states": {str(id): state}, "missing": [id]}`.

    - DB 읽기는 세션 **하나**(리뷰 W3: run 마다 세션+init_db 50회였다), 재해시는 세션 밖에서 **누적 예산**(리뷰 C2).
    - 없는 id 는 404 가 아니라 `missing` — 배치의 일부만 없다고 전부를 거절하지 않는다.
    - `output_path`(서버 절대경로)는 싣지 않는다 — 열이 쓰지 않는 값이고 배치는 열거 비용을 50배 낮춘다(리뷰 W4).
    """
    loaded: Dict[str, Dict[str, Any]] = {}
    missing: List[int] = []
    with open_session() as session:
        for rid in run_ids:
            try:
                loaded[str(rid)] = _load_state(session, rid, viewer=viewer)
            except RunNotFound:
                missing.append(rid)
    # 기본값은 호출 시점에 읽는다(정의 시점 바인딩이면 env/monkeypatch 로 바꾼 값이 안 먹는다).
    budget = {"remaining": int(BATCH_REHASH_BUDGET_BYTES if budget_bytes is None else budget_bytes)}
    states: Dict[str, Dict[str, Any]] = {}
    for key, st in loaded.items():
        out = _finish_state(st, viewer=viewer, budget=budget)
        out.pop("output_path", None)
        states[key] = out
    return {"states": states, "missing": missing}


# ── 쓰기 ────────────────────────────────────────────────────────────────────────


def _translate_db_error(exc: Exception, *, run_id: int, reviewer: str) -> ReviewError:
    """생성 경합·잠금 대기 초과를 계약 안의 코드로(리뷰 W1). 데이터는 UNIQUE/롤백이 이미 지켰다."""
    # UNIQUE 위반만 경합이다 — NOT NULL·FK 위반은 코드 결함이라 그대로 올려 500 으로 드러낸다(fail-loud).
    if isinstance(exc, IntegrityError) and "unique" in str(exc).lower():
        return VersionConflict(
            "같은 검토자의 기록이 그 사이 생겼다(동시 생성) — 최신 기록을 다시 읽고 갱신할 것",
            run_id=run_id, reviewer=reviewer, cause="unique_violation",
        )
    if isinstance(exc, OperationalError) and "locked" in str(exc).lower():
        return DbBusy("품질 DB 가 다른 기록으로 잠겨 있다 — 잠시 후 다시 시도할 것", run_id=run_id)
    raise exc


def _upsert_in_session(
    session: Session, *, run_id: int, reviewer: str, decision: str, comment: Optional[str],
    expected_sha256: str, version: Optional[int], auth_method: str,
) -> Dict[str, Any]:
    run = session.query(GenerationRun).filter_by(id=run_id).first()
    if not run:
        raise RunNotFound(f"run_id {run_id} not found", run_id=run_id)
    if not run.output_sha256:
        raise HashUnavailable(
            "이 run 은 산출물 해시가 없어 검토를 잠근다(hash_unavailable)",
            run_id=run_id, hash_reason=_hash_reason_from_meta(run.meta_json),
        )
    expected = (expected_sha256 or "").strip().lower()
    if expected != run.output_sha256:
        raise Stale(
            "산출물이 검토 시점과 다르다 — 화면을 새로고침해 지금 산출물을 다시 확인할 것",
            run_id=run_id, expected_sha256=expected, output_sha256=run.output_sha256,
        )
    # (R48-a) 4-eyes — 만든 사람은 판정하지 못한다. `created_by` 가 NULL 이면 판정 불가라 통과(위 docstring).
    if is_same_identity(run.created_by, reviewer):
        raise SelfReview(
            "자기가 만든 run 은 검토할 수 없다 — 다른 승인자가 판정해야 한다(4-eyes)",
            run_id=run_id, created_by=run.created_by,
        )

    now = _utcnow()
    existing = session.query(ReviewRecord).filter_by(run_id=run_id, reviewer=reviewer).first()
    if existing is None:
        if version is not None:
            raise VersionConflict(
                "기존 기록이 없는데 version 이 왔다 — 다른 검토자의 기록을 갱신하려는 것이거나 화면이 낡았다",
                run_id=run_id, version=version,
            )
        rec = ReviewRecord(
            run_id=run_id, output_sha256=run.output_sha256, reviewer=reviewer,
            auth_method=auth_method, decision=decision, comment=comment,
            version=1, created_at=now, updated_at=now,
        )
        session.add(rec)
        session.flush()  # rec.id — 감사행이 참조. UNIQUE 경합이면 여기서 IntegrityError.
        action = "create"
    else:
        if version is None:
            raise VersionConflict(
                "기존 기록이 있다 — 갱신하려면 현재 version 을 같이 보낼 것",
                run_id=run_id, version=None, current_version=existing.version,
            )
        # (리뷰 C1) 조건부 UPDATE 한 문장 — 읽은 version 이 아직 그 값일 때만 바뀐다. 0행이면 그 사이 누가 바꿨다.
        changed = (
            session.query(ReviewRecord)
            .filter(ReviewRecord.id == existing.id, ReviewRecord.version == int(version))
            .update(
                {
                    ReviewRecord.decision: decision,
                    ReviewRecord.comment: comment,
                    ReviewRecord.output_sha256: run.output_sha256,
                    ReviewRecord.auth_method: auth_method,
                    ReviewRecord.version: int(version) + 1,
                    ReviewRecord.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        if changed != 1:
            session.rollback()
            raise VersionConflict(
                "기록이 그 사이 바뀌었다(version 불일치) — 최신 기록을 다시 읽고 갱신할 것",
                run_id=run_id, version=version, current_version=_current_version(session, existing.id),
            )
        session.expire(existing)
        rec = existing
        action = "update"

    # 감사행 — 같은 세션. 여기서 예외가 나면 위 기록도 커밋되지 않는다(S11).
    session.add(ReviewAudit(
        review_id=rec.id, run_id=run_id, reviewer=reviewer, action=action,
        decision=decision, output_sha256=run.output_sha256, created_at=now,
    ))
    session.flush()
    return {"created": action == "create", "record": _record_plain(rec), "_output_path": run.output_path}


def approval_for_sha256(session: Session, sha256: str) -> Dict[str, Any]:
    """(R48-a) 이 **바이트**(sha256)에 승인 기록이 있는가 — 게시 게이트의 단일 판정기.

    반환 `{"approved": bool, "sha256", "records": [...], "runs": [id…]}`. `records` 는 그 해시를 스냅샷으로 가진
    기록 전부(판정별) — 승인이 없을 때 "반려 1건" 과 "기록 0건" 을 화면이 가를 수 있어야 한다.
    해시로 찾는 이유: 경로는 run 을 식별하지 못한다(R33 실측 — 한 경로를 21 run 이 돌려썼다). 게시하려는 파일의
    지금 바이트와 승인 시점 바이트가 같아야 승인이 그 파일에 대한 것이다.
    """
    sha = str(sha256 or "").strip().lower()
    if not sha:
        return {"approved": False, "sha256": None, "records": [], "runs": []}
    rows: List[ReviewRecord] = (
        session.query(ReviewRecord).filter(ReviewRecord.output_sha256 == sha).order_by(ReviewRecord.id.asc()).all()
    )
    return {
        "approved": any(r.decision == "approved" for r in rows),
        "sha256": sha,
        "records": [
            {"run_id": r.run_id, "decision": r.decision, "reviewer_masked": _mask(r.reviewer), "updated_at": _iso(r.updated_at)}
            for r in rows
        ],
        "runs": sorted({r.run_id for r in rows}),
    }


def _mask(name: str) -> str:
    from backend.services.admin_users import mask_user

    return mask_user(name)


def require_approved_bytes(session: Session, sha256: str) -> Dict[str, Any]:
    """승인 없는 바이트면 `NotApproved`(409). 통과하면 `approval_for_sha256` 결과."""
    st = approval_for_sha256(session, sha256)
    if not st["approved"]:
        raise NotApproved(
            "이 산출물 바이트에 승인(approved) 기록이 없다 — 검토 기록에서 승인을 받은 뒤 게시할 것",
            sha256=st["sha256"], records=st["records"], runs=st["runs"],
        )
    return st


def _current_version(session: Session, rec_id: int) -> Optional[int]:
    row = session.query(ReviewRecord.version).filter_by(id=rec_id).first()
    return int(row[0]) if row else None


def upsert_review(
    open_session: Callable[[], ContextManager[Session]],
    *,
    run_id: int,
    reviewer: str,
    decision: str,
    comment: Optional[str],
    expected_sha256: str,
    version: Optional[int],
    auth_method: str = AUTH_METHOD_JWT,
) -> Dict[str, Any]:
    """기록 생성/갱신 + 감사행 — 한 세션. 반환 `{"created": bool, "record": {...}}`(record.stale 은 파일 기준).

    검사 순서: 어휘/신원 → run 존재(404) → 해시 존재(409 HASH_UNAVAILABLE) → 해시 일치(409 STALE) → version(409).
    DB 경합(UNIQUE·잠금)은 `_translate_db_error` 로 계약 안의 코드가 된다.
    """
    if decision not in DECISIONS:
        raise ReviewError(f"decision must be one of {DECISIONS}", decision=decision)
    if not reviewer or reviewer == "default":
        raise IdentityRequired("검토자 신원이 없다(default) — JWT 로그인 필요")
    bad = comment_violation(comment)
    if bad:
        raise ReviewError(bad)
    try:
        with open_session() as session:
            out = _upsert_in_session(
                session, run_id=run_id, reviewer=reviewer, decision=decision, comment=comment,
                expected_sha256=expected_sha256, version=version, auth_method=auth_method,
            )
    except (IntegrityError, OperationalError) as exc:
        raise _translate_db_error(exc, run_id=run_id, reviewer=reviewer) from exc
    # (리뷰 W2) POST 응답의 stale 도 GET 과 같은 판정기 — 세션 밖에서 파일 기준으로.
    output_path = out.pop("_output_path")
    cur = current_output_hash(output_path, out["record"]["output_sha256"])
    out["record"]["stale"] = _stale(out["record"]["output_sha256"], cur)
    return out


def history(
    session: Session,
    *,
    scm_id: Optional[str] = None,
    doc_type: Optional[str] = None,
    run_id: Optional[int] = None,
    reviewer: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    viewer: Optional[Viewer] = None,
) -> Dict[str, Any]:
    """감사 이력(G7) — 최신순. run 의 doc_type/scm_id 를 조인해 필터한다. 챗 승인 감사와 **분리**.

    정규화는 형제 `backend/routers/quality.py::list_runs` 와 **같게** — `doc_type` 은 `lower().strip()`, `scm_id` 는
    `strip()`(리뷰 I2/후속: 두 엔드포인트가 같은 질의에 다른 수를 내면 빈 목록이 '이력 없음' 으로 읽힌다).

    (R37 D-1) 이름은 `viewer` 가 정한다. **필터도 같이 막는다** — 응답만 마스킹하면 `?reviewer=<이름>` 의
    결과 수가 그 이름의 존재를 그대로 알려줘, 가린 값을 되맞힐 수 있다(마스킹이 표시 계층에만 있으면
    질의 계층이 그 옆으로 샌다).
    """
    q = session.query(ReviewAudit, GenerationRun).join(GenerationRun, ReviewAudit.run_id == GenerationRun.id)
    if scm_id:
        q = q.filter(GenerationRun.scm_id == scm_id.strip())  # 형제 quality.py 와 같은 정규화(strip 만)
    if doc_type:
        q = q.filter(GenerationRun.doc_type == doc_type.lower().strip())
    if run_id is not None:
        q = q.filter(ReviewAudit.run_id == int(run_id))
    if reviewer:
        want = reviewer.strip()
        # 마스킹과 **같은 조건**(`may_see_names`)을 쓴다 — 표시 계층만 가리면 결과 수가 가린 이름을 되맞힌다.
        if viewer is not None and not viewer.may_see_names(want):
            raise ReviewerFilterForbidden(
                "다른 검토자로 이력을 거르려면 JWT 로그인한 admin 이어야 합니다 — 본인 이력은 자기 이름으로 조회됩니다",
                reviewer=want[:64],
            )
        q = q.filter(ReviewAudit.reviewer == want)
    total = q.count()
    rows = q.order_by(ReviewAudit.id.desc()).offset(offset).limit(limit).all()
    items = [
        {
            "id": audit.id,
            "review_id": audit.review_id,
            "run_id": audit.run_id,
            "doc_type": run.doc_type,
            "scm_id": run.scm_id,
            "reviewer": viewer.visible(audit.reviewer) if viewer else audit.reviewer,
            "action": audit.action,
            "decision": audit.decision,
            "output_sha256": audit.output_sha256,
            "created_at": _iso(audit.created_at),
        }
        for audit, run in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}
