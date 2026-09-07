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


class IdentityRequired(ReviewError):
    status = 401
    code = "AUTH_REQUIRED"


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

_HASH_CACHE: Dict[str, "tuple[tuple[int, int], str]"] = {}
_HASH_CACHE_MAX = 64
_HASH_CACHE_LOCK = threading.Lock()


def _cached_file_hash(p) -> str:
    """(mtime_ns, size) 가 같으면 재해시하지 않는다(선례 `reference_preview_cache`). 한도 넘으면 통째로 비운다."""
    st = p.stat()
    key = str(p)
    sig = (int(st.st_mtime_ns), int(st.st_size))
    with _HASH_CACHE_LOCK:
        hit = _HASH_CACHE.get(key)
        if hit and hit[0] == sig:
            return hit[1]
    digest = sha256_of_file(p)
    with _HASH_CACHE_LOCK:
        if len(_HASH_CACHE) >= _HASH_CACHE_MAX:
            _HASH_CACHE.clear()
        _HASH_CACHE[key] = (sig, digest)
    return digest


def current_output_hash(output_path: Optional[str], recorded_sha256: Optional[str]) -> Dict[str, Any]:
    """지금 산출물의 해시. `{"sha256", "basis": "file"|"record"|None, "basis_reason"}`.

    - `file`: `output_path` 가 살아 있어 **지금 파일**을 읽었다(캐시 적중이면 안 읽는다).
    - `record`: 파일 기준 판단을 못 해 run 의 기록 해시만 있다. `basis_reason` 이 왜인지 말한다 —
      `no_path` / `file_missing` / `not_a_file` / `too_large` / `unreadable`.
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
                return {"sha256": _cached_file_hash(p), "basis": "file", "basis_reason": None}
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


def _hash_reason_from_meta(raw: Optional[str]) -> Optional[str]:
    """R33 이 `meta_json.output_sha256_reason` 에 남긴 NULL 사유. 없으면 None(구 run — 사유 미기록)."""
    if not raw:
        return None
    try:
        import json

        meta = json.loads(raw)
    except (ValueError, TypeError):
        return None
    v = meta.get("output_sha256_reason") if isinstance(meta, dict) else None
    return str(v) if v else None


def _gated_metric_count(run: GenerationRun) -> Optional[int]:
    for s in (getattr(run, "scores", None) or []):
        if str(getattr(s, "metric_name", "") or "") == "gated_metric_count":
            try:
                return int(s.value) if s.value is not None else None
            except (TypeError, ValueError):
                return None
    return None


def _record_plain(rec: ReviewRecord) -> Dict[str, Any]:
    return {
        "id": rec.id,
        "run_id": rec.run_id,
        "reviewer": rec.reviewer,
        "auth_method": rec.auth_method,
        "decision": rec.decision,
        "comment": rec.comment,
        "output_sha256": rec.output_sha256,
        "version": rec.version,
        "created_at": _iso(rec.created_at),
        "updated_at": _iso(rec.updated_at),
    }


def _load_state(session: Session, run_id: int) -> Dict[str, Any]:
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
        "output_path": run.output_path,
        "output_sha256": run.output_sha256,
        "hash_reason": _hash_reason_from_meta(run.meta_json) if run.output_sha256 is None else None,
        "superseded_by": superseded_by(session, run),
        "gated_metric_count": _gated_metric_count(run),
        "reviews": [_record_plain(r) for r in records],
    }


def review_state(
    open_session: Callable[[], ContextManager[Session]], run_id: int, *, can_review: Optional[bool] = None,
) -> Dict[str, Any]:
    """`GET /api/review/runs/{id}` 본문. DB 읽기는 세션 안, 파일 재해시는 세션 **밖**(리뷰 W3).

    run 이 없으면 `RunNotFound`(200+error 금지). `can_review` 는 라우터가 현재 사용자의 admin 여부를 넣는다(I7).
    """
    with open_session() as session:
        st = _load_state(session, run_id)
    cur = current_output_hash(st["output_path"], st["output_sha256"])
    hash_unavailable = st["output_sha256"] is None
    for r in st["reviews"]:
        r["stale"] = _stale(r["output_sha256"], cur)
    st.update({
        # 검토 잠금(S6). 사유는 R33 의 meta — 구 run 은 사유 미기록(None).
        "hash_unavailable": hash_unavailable,
        "current_sha256": cur["sha256"],
        "current_basis": cur["basis"],
        "current_basis_reason": cur["basis_reason"],
        # run 의 기록 해시 ↔ 지금 파일. 파일 기준이 아니면 None(판단 불가) — False 로 접지 않는다.
        "stale": _stale(st["output_sha256"], cur),
        "can_review": can_review,
    })
    return st


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
) -> Dict[str, Any]:
    """감사 이력(G7) — 최신순. run 의 doc_type/scm_id 를 조인해 필터한다. 챗 승인 감사와 **분리**.

    정규화는 형제 `backend/routers/quality.py::list_runs` 와 **같게** — `doc_type` 은 `lower().strip()`, `scm_id` 는
    `strip()`(리뷰 I2/후속: 두 엔드포인트가 같은 질의에 다른 수를 내면 빈 목록이 '이력 없음' 으로 읽힌다).
    """
    q = session.query(ReviewAudit, GenerationRun).join(GenerationRun, ReviewAudit.run_id == GenerationRun.id)
    if scm_id:
        q = q.filter(GenerationRun.scm_id == scm_id.strip())  # 형제 quality.py 와 같은 정규화(strip 만)
    if doc_type:
        q = q.filter(GenerationRun.doc_type == doc_type.lower().strip())
    if run_id is not None:
        q = q.filter(ReviewAudit.run_id == int(run_id))
    if reviewer:
        q = q.filter(ReviewAudit.reviewer == reviewer.strip())
    total = q.count()
    rows = q.order_by(ReviewAudit.id.desc()).offset(offset).limit(limit).all()
    items = [
        {
            "id": audit.id,
            "review_id": audit.review_id,
            "run_id": audit.run_id,
            "doc_type": run.doc_type,
            "scm_id": run.scm_id,
            "reviewer": audit.reviewer,
            "action": audit.action,
            "decision": audit.decision,
            "output_sha256": audit.output_sha256,
            "created_at": _iso(audit.created_at),
        }
        for audit, run in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}
