"""R34 (C-2) — 검토 기록 `review_records`/`review_audit` + `/api/review/*`.

## 계약(계획 §4.3·§4.5)

- 판정은 run 이 아니라 **산출물 바이트**에 고정된다: `expected_sha256 == run.output_sha256` 일 때만 쓰고,
  해시 없는 run 은 `hash_unavailable` 로 잠근다(S5·S6).
- 쓰기는 JWT + admin(S4, §8 #8). X-User 만으로는 401 `JWT_REQUIRED`.
- 한 검토자는 run 당 기록 하나(UNIQUE) + `version` 낙관적 잠금(S9).
- 기록과 감사행은 한 트랜잭션(S11) — 감사 INSERT 가 실패하면 기록도 남지 않는다.
- run 없음은 **404**. 200 + `{"error": …}` 는 절대 없다(`api.js` 가 `res.ok` 만 본다).
- 입력은 `extra='forbid'`·`max_length`·제어문자 거부(S12).
- `stale` 은 표시만(지우지 않는다), `superseded_by` 는 TTL 대신(§8 #9·#10).
- (리뷰 C1) 갱신은 `UPDATE … WHERE id AND version` 한 문장 — 두 세션이 같은 version 을 읽고 차례로 쓰면 두 번째는 409.
- (리뷰 C2) 파일 기준이 아니면 레코드 `stale` 도 `null` — 기록 해시끼리 비교해 '같다' 라고 말하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Optional

import pytest

pytest.importorskip("fastapi")


# ==============================================================
# 픽스처
# ==============================================================


@pytest.fixture
def qdb(monkeypatch, tmp_path):
    from workflow.quality import db as qdb_mod

    db_file = tmp_path / "q.sqlite"
    monkeypatch.setattr(qdb_mod, "_default_db_path", lambda: db_file)
    qdb_mod.reset_engine()
    qdb_mod.init_db(db_file)
    yield db_file
    qdb_mod.reset_engine()


def _make_run(db, *, doc_type="sits", scm_id="kjpds02", sha: Optional[str] = "auto",
              output_path: Optional[str] = None, meta: Optional[dict] = None,
              status="success", gated: Optional[int] = 5) -> int:
    from workflow.quality.db import get_session
    from workflow.quality.models import GenerationRun, QualityScore

    if sha == "auto":
        sha = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    with get_session(db) as s:
        run = GenerationRun(
            run_uuid=str(uuid.uuid4()), doc_type=doc_type, scm_id=scm_id, status=status,
            output_sha256=sha, output_path=output_path,
            meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
        )
        s.add(run)
        s.flush()
        if gated is not None:
            s.add(QualityScore(run_id=run.id, metric_name="gated_metric_count", value=float(gated)))
        rid = run.id
    return rid


def _run_sha(db, rid) -> Optional[str]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT output_sha256 FROM generation_runs WHERE id=?", (rid,)).fetchone()[0]
    finally:
        conn.close()


_TABLE_SQL = {
    "review_records": "SELECT * FROM review_records ORDER BY id",
    "review_audit": "SELECT * FROM review_audit ORDER BY id",
}


def _rows(db, table):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(_TABLE_SQL[table])]
    finally:
        conn.close()


def _app(*, user="tester", admin: Optional[str] = "tester"):
    """라우터 단독 앱. `require_user`/`require_jwt_user`/`require_admin` 을 각각 덮는다."""
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from backend.dependencies.admin import require_admin
    from backend.dependencies.auth import require_jwt_user, require_user
    from backend.error_handler import http_exception_handler
    from backend.routers import review

    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.include_router(review.router)
    app.dependency_overrides[require_user] = lambda: user
    app.dependency_overrides[require_jwt_user] = lambda: user
    if admin is not None:
        app.dependency_overrides[require_admin] = lambda: admin
    return TestClient(app)


@pytest.fixture
def client(qdb):
    return _app()


def _body(sha, decision="approved", comment="ok", version=None, **extra):
    b = {"decision": decision, "comment": comment, "expected_sha256": sha}
    if version is not None:
        b["version"] = version
    b.update(extra)
    return b


# ==============================================================
# 1. 스키마 — 새 테이블이 생기고, 기존 DB(R33 형상)에도 생긴다
# ==============================================================


class TestSchema:

    def test_tables_exist_after_init(self, qdb):
        conn = sqlite3.connect(qdb)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        assert {"review_records", "review_audit"} <= names

    def test_unique_run_reviewer(self, qdb):
        """UNIQUE(run_id, reviewer) 가 DB 층에 실재한다 — 서비스 층만 믿지 않는다."""
        from datetime import datetime, timezone

        from sqlalchemy.exc import IntegrityError

        from workflow.quality.db import get_session
        from workflow.quality.models import ReviewRecord

        rid = _make_run(qdb)
        now = datetime.now(timezone.utc)
        with get_session(qdb) as s:
            s.add(ReviewRecord(run_id=rid, output_sha256="a" * 64, reviewer="r1", decision="approved",
                               version=1, created_at=now, updated_at=now))
        with pytest.raises(IntegrityError):
            with get_session(qdb) as s:
                s.add(ReviewRecord(run_id=rid, output_sha256="a" * 64, reviewer="r1", decision="rejected",
                                   version=1, created_at=now, updated_at=now))


# ==============================================================
# 2. 조회 — 404 · hash_unavailable · stale · superseded_by
# ==============================================================


class TestGet:

    def test_unknown_run_is_404_not_200_error(self, client):
        res = client.get("/api/review/runs/999999")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "RUN_NOT_FOUND"

    def test_no_hash_is_locked_with_reason(self, client, qdb):
        rid = _make_run(qdb, sha=None, meta={"output_sha256_reason": "no_path"})
        d = client.get(f"/api/review/runs/{rid}").json()
        assert d["hash_unavailable"] is True
        assert d["hash_reason"] == "no_path"
        assert d["stale"] is None  # 판단 불가는 False 가 아니다
        assert d["reviews"] == []

    def test_legacy_run_without_reason_is_locked_with_none_reason(self, client, qdb):
        rid = _make_run(qdb, sha=None)
        d = client.get(f"/api/review/runs/{rid}").json()
        assert d["hash_unavailable"] is True
        assert d["hash_reason"] is None

    def test_stale_when_file_changed(self, client, qdb, tmp_path):
        """파일이 살아 있으면 **지금 파일**을 다시 읽어 비교한다."""
        out = tmp_path / "SITS_gate.xlsm"
        out.write_bytes(b"v1")
        sha1 = hashlib.sha256(b"v1").hexdigest()
        rid = _make_run(qdb, sha=sha1, output_path=str(out))
        d = client.get(f"/api/review/runs/{rid}").json()
        assert (d["stale"], d["current_basis"], d["current_sha256"]) == (False, "file", sha1)
        out.write_bytes(b"v2 -- overwritten by a later run")
        d = client.get(f"/api/review/runs/{rid}").json()
        assert d["stale"] is True
        assert d["current_sha256"] == hashlib.sha256(b"v2 -- overwritten by a later run").hexdigest()

    def test_file_gone_falls_back_to_record(self, client, qdb, tmp_path):
        sha1 = hashlib.sha256(b"v1").hexdigest()
        rid = _make_run(qdb, sha=sha1, output_path=str(tmp_path / "gone.xlsm"))
        client.post(f"/api/review/runs/{rid}", json=_body(sha1))
        d = client.get(f"/api/review/runs/{rid}").json()
        assert d["current_basis"] == "record"
        assert d["current_basis_reason"] == "file_missing"
        assert d["current_sha256"] == sha1
        assert d["stale"] is None  # 파일이 없으니 "지금 산출물" 을 모른다
        # (리뷰 C2) 레코드 층도 같은 판정기 — 기록 해시끼리 비교해 False 를 만들면 안 된다
        assert [r["stale"] for r in d["reviews"]] == [None]

    def test_unreadable_file_reports_reason_not_silent_record(self, client, qdb, tmp_path, monkeypatch):
        """읽기 실패(권한·UNC 등)는 '파일 없음' 과 다른 사유로 — 200 으로 위장하지 않는다."""
        from workflow.quality import review as review_mod

        out = tmp_path / "o.xlsm"
        out.write_bytes(b"v1")
        rid = _make_run(qdb, sha=hashlib.sha256(b"v1").hexdigest(), output_path=str(out))

        def _boom(_p):
            raise PermissionError("synthetic read failure")

        monkeypatch.setattr(review_mod, "sha256_of_file", _boom)
        review_mod._HASH_CACHE.clear()
        d = client.get(f"/api/review/runs/{rid}").json()
        assert (d["current_basis"], d["current_basis_reason"], d["stale"]) == ("record", "unreadable", None)

    def test_no_path_reason_and_can_review(self, qdb):
        rid = _make_run(qdb, output_path=None)
        d = _app().get(f"/api/review/runs/{rid}").json()
        assert d["current_basis_reason"] == "no_path"
        assert d["can_review"] is True  # conftest: tester 는 admin
        d2 = _app(user="reader", admin=None).get(f"/api/review/runs/{rid}").json()
        assert d2["can_review"] is False

    def test_rehash_cache_hits_on_same_signature(self, client, qdb, tmp_path, monkeypatch):
        """같은 (mtime, size) 면 파일을 다시 읽지 않고, 바뀌면 다시 읽는다."""
        import os

        from workflow.quality import review as review_mod

        out = tmp_path / "o.xlsm"
        out.write_bytes(b"v1")
        rid = _make_run(qdb, sha=hashlib.sha256(b"v1").hexdigest(), output_path=str(out))
        review_mod._HASH_CACHE.clear()
        calls = []
        real = review_mod.sha256_of_file

        def _counting(p):
            calls.append(str(p))
            return real(p)

        monkeypatch.setattr(review_mod, "sha256_of_file", _counting)
        client.get(f"/api/review/runs/{rid}")
        client.get(f"/api/review/runs/{rid}")
        assert len(calls) == 1
        out.write_bytes(b"v2-longer")
        os.utime(out, None)
        client.get(f"/api/review/runs/{rid}")
        assert len(calls) == 2

    def test_superseded_by_newer_success_run_same_project_and_doc(self, client, qdb):
        old = _make_run(qdb, scm_id="kjpds02", doc_type="sits")
        _make_run(qdb, scm_id="kjpds02", doc_type="suts")           # 다른 문서 — 아님
        _make_run(qdb, scm_id="hdpdm01", doc_type="sits")           # 다른 프로젝트 — 아님
        _make_run(qdb, scm_id="kjpds02", doc_type="sits", status="failed")  # 실패 — 아님
        newer = _make_run(qdb, scm_id="kjpds02", doc_type="sits")
        # 같은 프로젝트의 **가장 새로운** run 이 다른 문서(suts)여도 답은 같은 문서의 newer 여야 한다 —
        # doc_type 필터를 지운 뮤턴트가 이 행 없이는 살아남았다(M10).
        _make_run(qdb, scm_id="kjpds02", doc_type="suts")
        d = client.get(f"/api/review/runs/{old}").json()
        assert d["superseded_by"]["run_id"] == newer
        assert d["superseded_by"]["created_at"]
        assert client.get(f"/api/review/runs/{newer}").json()["superseded_by"] is None

    def test_null_scm_id_is_never_superseded(self, client, qdb):
        a = _make_run(qdb, scm_id=None)
        _make_run(qdb, scm_id=None)
        assert client.get(f"/api/review/runs/{a}").json()["superseded_by"] is None

    def test_gated_metric_count_missing_is_none_not_zero(self, client, qdb):
        rid = _make_run(qdb, gated=None)
        assert client.get(f"/api/review/runs/{rid}").json()["gated_metric_count"] is None


# ==============================================================
# 3. 쓰기 — 생성 · 갱신 · 409 3종 · 트랜잭션
# ==============================================================


class TestPost:

    def test_create_then_read_back_with_audit(self, client, qdb):
        rid = _make_run(qdb)
        sha = _run_sha(qdb, rid)
        res = client.post(f"/api/review/runs/{rid}", json=_body(sha, comment="looks fine\nline2\ttab"))
        assert res.status_code == 200, res.text
        d = res.json()
        assert d["created"] is True
        rec = d["record"]
        assert (rec["decision"], rec["reviewer"], rec["version"], rec["auth_method"]) == ("approved", "tester", 1, "jwt")
        assert rec["output_sha256"] == sha
        assert rec["stale"] is None  # 이 run 은 파일이 없다 — POST 응답도 GET 과 같은 판정기(리뷰 W2)
        got = client.get(f"/api/review/runs/{rid}").json()
        assert [r["id"] for r in got["reviews"]] == [rec["id"]]
        audits = _rows(qdb, "review_audit")
        assert len(audits) == 1
        assert (audits[0]["action"], audits[0]["decision"], audits[0]["review_id"]) == ("create", "approved", rec["id"])

    def test_unknown_run_is_404(self, client, qdb):
        res = client.post("/api/review/runs/424242", json=_body("a" * 64))
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "RUN_NOT_FOUND"
        assert _rows(qdb, "review_records") == []

    def test_hash_unavailable_is_409_and_locks(self, client, qdb):
        rid = _make_run(qdb, sha=None, meta={"output_sha256_reason": "file_missing"})
        res = client.post(f"/api/review/runs/{rid}", json=_body("a" * 64))
        assert res.status_code == 409
        err = res.json()["error"]
        assert err["code"] == "HASH_UNAVAILABLE"
        assert err["detail"]["hash_reason"] == "file_missing"
        assert _rows(qdb, "review_records") == []

    def test_stale_expected_hash_is_409(self, client, qdb):
        rid = _make_run(qdb)
        res = client.post(f"/api/review/runs/{rid}", json=_body("b" * 64))
        assert res.status_code == 409
        err = res.json()["error"]
        assert err["code"] == "STALE"
        assert err["detail"]["output_sha256"] == _run_sha(qdb, rid)
        assert _rows(qdb, "review_records") == []
        assert _rows(qdb, "review_audit") == []

    def test_uppercase_expected_hash_matches(self, client, qdb):
        rid = _make_run(qdb)
        sha = _run_sha(qdb, rid)
        assert client.post(f"/api/review/runs/{rid}", json=_body(sha.upper())).status_code == 200

    def test_update_requires_current_version(self, client, qdb):
        rid = _make_run(qdb)
        sha = _run_sha(qdb, rid)
        first = client.post(f"/api/review/runs/{rid}", json=_body(sha)).json()["record"]
        # version 없이 갱신 → 409
        res = client.post(f"/api/review/runs/{rid}", json=_body(sha, decision="rejected"))
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "VERSION_CONFLICT"
        # 낡은 version → 409
        res = client.post(f"/api/review/runs/{rid}", json=_body(sha, decision="rejected", version=99))
        assert res.status_code == 409
        assert res.json()["error"]["detail"]["current_version"] == 1
        # 맞는 version → 200, version 2, 감사 update
        res = client.post(f"/api/review/runs/{rid}", json=_body(sha, decision="rejected", version=first["version"]))
        assert res.status_code == 200, res.text
        d = res.json()
        assert d["created"] is False
        assert (d["record"]["decision"], d["record"]["version"], d["record"]["id"]) == ("rejected", 2, first["id"])
        assert [a["action"] for a in _rows(qdb, "review_audit")] == ["create", "update"]
        assert len(_rows(qdb, "review_records")) == 1

    def test_version_on_create_is_a_conflict(self, client, qdb):
        """기존 기록이 없는데 version 이 오면 화면이 낡았거나 남의 기록을 노린 것 — 만들지 않는다."""
        rid = _make_run(qdb)
        res = client.post(f"/api/review/runs/{rid}", json=_body(_run_sha(qdb, rid), version=1))
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "VERSION_CONFLICT"
        assert _rows(qdb, "review_records") == []

    def test_two_reviewers_two_records(self, qdb):
        rid = _make_run(qdb)
        sha = _run_sha(qdb, rid)
        assert _app(user="alice", admin="alice").post(f"/api/review/runs/{rid}", json=_body(sha)).status_code == 200
        assert _app(user="bob", admin="bob").post(
            f"/api/review/runs/{rid}", json=_body(sha, decision="needs_work"),
        ).status_code == 200
        got = _app().get(f"/api/review/runs/{rid}").json()
        assert sorted((r["reviewer"], r["decision"]) for r in got["reviews"]) == [
            ("alice", "approved"), ("bob", "needs_work"),
        ]

    def test_audit_failure_rolls_back_the_record(self, client, qdb, monkeypatch):
        """(S11) 감사 INSERT 가 실패하면 기록도 남지 않는다 — 한 트랜잭션."""
        from sqlalchemy.exc import IntegrityError

        from workflow.quality import review as review_mod

        real = review_mod.ReviewAudit

        def _null_decision(*a, **k):
            k["decision"] = None  # NOT NULL 위반 — SQL 이 실제로 나간 뒤 DB 가 거부한다
            return real(*a, **k)

        monkeypatch.setattr(review_mod, "ReviewAudit", _null_decision)
        rid = _make_run(qdb)
        with pytest.raises(IntegrityError):
            client.post(f"/api/review/runs/{rid}", json=_body(_run_sha(qdb, rid)))
        assert _rows(qdb, "review_records") == [], "감사 없이 기록만 남았다"
        assert _rows(qdb, "review_audit") == []

    def test_never_200_with_error_key(self, client, qdb):
        rid = _make_run(qdb, sha=None)
        for res in (
            client.get("/api/review/runs/999999"),
            client.post(f"/api/review/runs/{rid}", json=_body("a" * 64)),
            client.post("/api/review/runs/999999", json=_body("a" * 64)),
        ):
            assert not (res.status_code == 200 and "error" in res.json())


# ==============================================================
# 4. 입력 표면 — extra forbid · 길이 · 제어문자 · 형식
# ==============================================================


class TestInputSurface:

    @pytest.mark.parametrize("bad", [
        {"path": "C:/x.docx"},            # 경로 필드는 받지 않는다
        {"reviewer": "someone-else"},     # 신원은 토큰에서만
        {"run_id": 1},
        {"auth_method": "x-user"},
    ])
    def test_unknown_field_is_422(self, client, qdb, bad):
        rid = _make_run(qdb)
        res = client.post(f"/api/review/runs/{rid}", json=_body(_run_sha(qdb, rid), **bad))
        assert res.status_code == 422
        assert _rows(qdb, "review_records") == []

    @pytest.mark.parametrize("decision", ["approve", "APPROVED", "", None, 1, ["approved"]])
    def test_bad_decision_is_422(self, client, qdb, decision):
        rid = _make_run(qdb)
        b = _body(_run_sha(qdb, rid))
        b["decision"] = decision
        assert client.post(f"/api/review/runs/{rid}", json=b).status_code == 422

    @pytest.mark.parametrize("sha", ["", "abc", "z" * 64, "a" * 63, "a" * 65, None, 1234, ["a" * 64]])
    def test_bad_sha_is_422(self, client, qdb, sha):
        rid = _make_run(qdb)
        b = _body("a" * 64)
        b["expected_sha256"] = sha
        assert client.post(f"/api/review/runs/{rid}", json=b).status_code == 422

    def test_comment_too_long_is_422(self, client, qdb):
        rid = _make_run(qdb)
        assert client.post(f"/api/review/runs/{rid}", json=_body(_run_sha(qdb, rid), comment="x" * 2001)).status_code == 422
        assert client.post(f"/api/review/runs/{rid}", json=_body(_run_sha(qdb, rid), comment="x" * 2000)).status_code == 200

    @pytest.mark.parametrize("comment", [
        "a\x00b", "a\x1bb", "a\rb", "a\x7fb",
        "a\u2028b",   # 줄 구분자(Zl) — JSON-in-HTML 을 깬다
        "a\u202eb",   # RLO(Cf) — 화면 문구 역전
        "a\ufeffb",   # BOM(Cf)
        "a\x85b",     # NEL(Cc)
    ])
    def test_control_chars_in_comment_are_422(self, client, qdb, comment):
        rid = _make_run(qdb)
        assert client.post(f"/api/review/runs/{rid}", json=_body(_run_sha(qdb, rid), comment=comment)).status_code == 422

    @pytest.mark.parametrize("version", [0, -1, "1", 1.5])
    def test_bad_version_is_422(self, client, qdb, version):
        rid = _make_run(qdb)
        b = _body(_run_sha(qdb, rid))
        b["version"] = version
        assert client.post(f"/api/review/runs/{rid}", json=b).status_code == 422

    def test_decision_vocabulary_has_one_source(self):
        """(리뷰 W4) 라우터 `Literal` 과 서비스 `DECISIONS` 는 같은 집합이어야 한다."""
        from typing import get_args

        from backend.routers.review import ReviewBody
        from workflow.quality.review import DECISIONS

        assert set(get_args(ReviewBody.model_fields["decision"].annotation)) == set(DECISIONS)

    def test_non_json_body_is_422(self, client, qdb):
        rid = _make_run(qdb)
        res = client.post(f"/api/review/runs/{rid}", data="decision=approved",
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert res.status_code == 422

    @pytest.mark.parametrize("run_id", ["abc", "1.5", "-1"])
    def test_bad_run_id_path(self, client, run_id):
        res = client.get(f"/api/review/runs/{run_id}")
        assert res.status_code in (404, 422)
        assert res.status_code != 200

    def test_history_query_bounds(self, client):
        assert client.get("/api/review/history?limit=0").status_code == 422
        assert client.get("/api/review/history?limit=201").status_code == 422
        assert client.get("/api/review/history?offset=-1").status_code == 422
        assert client.get("/api/review/history?scm_id=" + "x" * 65).status_code == 422


# ==============================================================
# 5. 권한 — JWT 강제 · admin · 신원 일치
# ==============================================================


class TestAuth:

    def test_read_requires_login_only(self, qdb):
        """조회는 `require_user` 만 — admin 아니어도 된다."""
        rid = _make_run(qdb)
        assert _app(user="reader", admin=None).get(f"/api/review/runs/{rid}").status_code == 200

    def test_write_without_bearer_is_401_jwt_required(self, qdb):
        """`require_jwt_user` 를 덮지 않은 진짜 의존성 — Authorization 없으면 JWT_REQUIRED (X-User 로는 안 된다)."""
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient

        from backend.dependencies.auth import require_user
        from backend.error_handler import http_exception_handler
        from backend.routers import review

        app = FastAPI()
        app.add_exception_handler(HTTPException, http_exception_handler)
        app.include_router(review.router)
        app.dependency_overrides[require_user] = lambda: "tester"
        c = TestClient(app)
        rid = _make_run(qdb)
        res = c.post(f"/api/review/runs/{rid}", json=_body(_run_sha(qdb, rid)), headers={"X-User": "tester"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "JWT_REQUIRED"
        assert _rows(qdb, "review_records") == []

    def test_bearer_but_no_identity_is_401_auth_required(self, qdb):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient

        from backend.error_handler import http_exception_handler
        from backend.routers import review

        app = FastAPI()
        app.add_exception_handler(HTTPException, http_exception_handler)
        app.include_router(review.router)
        c = TestClient(app)
        rid = _make_run(qdb)
        res = c.post(f"/api/review/runs/{rid}", json=_body(_run_sha(qdb, rid)),
                     headers={"Authorization": "Bearer not-a-real-token"})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "AUTH_REQUIRED"

    def test_non_admin_jwt_user_is_403(self, qdb, monkeypatch):
        """JWT 는 통과했지만 admin 목록에 없다 — 403 ADMIN_REQUIRED (진짜 `require_admin`)."""
        from backend.dependencies import admin as admin_mod

        monkeypatch.setattr(admin_mod, "get_current_user", lambda: "nobody")
        c = _app(user="nobody", admin=None)
        rid = _make_run(qdb)
        res = c.post(f"/api/review/runs/{rid}", json=_body(_run_sha(qdb, rid)))
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "ADMIN_REQUIRED"
        assert _rows(qdb, "review_records") == []

    def test_default_user_is_rejected_by_service(self, qdb):
        """의존성이 뚫려도 서비스는 'default' 를 검토자로 받지 않는다."""
        from workflow.quality.db import get_session
        from workflow.quality.review import IdentityRequired, upsert_review

        rid = _make_run(qdb)
        with pytest.raises(IdentityRequired) as ei:
            upsert_review(lambda: get_session(qdb), run_id=rid, reviewer="default", decision="approved",
                          comment=None, expected_sha256=_run_sha(qdb, rid), version=None)
        assert ei.value.status == 401  # 인증 문제를 409 로 위장하지 않는다(리뷰 I3)


# ==============================================================
# 6. 이력
# ==============================================================


class TestHistory:

    def test_history_filters_and_includes_audit_rows(self, qdb):
        a = _make_run(qdb, scm_id="kjpds02", doc_type="sits")
        b = _make_run(qdb, scm_id="hdpdm01", doc_type="swut")
        sa, sb = _run_sha(qdb, a), _run_sha(qdb, b)
        c = _app()
        first = c.post(f"/api/review/runs/{a}", json=_body(sa)).json()["record"]
        c.post(f"/api/review/runs/{a}", json=_body(sa, decision="rejected", version=first["version"]))
        c.post(f"/api/review/runs/{b}", json=_body(sb, decision="needs_work"))

        all_ = c.get("/api/review/history").json()
        assert all_["total"] == 3
        assert [i["action"] for i in all_["items"]] == ["create", "update", "create"]  # 최신순
        assert all_["items"][0]["run_id"] == b

        only_a = c.get("/api/review/history?scm_id=kjpds02").json()
        assert only_a["total"] == 2 and {i["run_id"] for i in only_a["items"]} == {a}
        only_swut = c.get("/api/review/history?doc_type=SWUT").json()
        assert only_swut["total"] == 1 and only_swut["items"][0]["decision"] == "needs_work"
        assert c.get("/api/review/history?scm_id=kjpds02 ").json()["total"] == 2  # 끝 공백 — quality.py 와 같은 strip(리뷰 I2)
        assert c.get(f"/api/review/history?run_id={b}").json()["total"] == 1
        assert c.get("/api/review/history?reviewer=tester").json()["total"] == 3
        assert c.get("/api/review/history?reviewer=nobody").json()["total"] == 0
        paged = c.get("/api/review/history?limit=1&offset=1").json()
        assert paged["total"] == 3 and len(paged["items"]) == 1 and paged["items"][0]["action"] == "update"

    def test_history_is_not_the_chat_approval_table(self):
        """S14/§4.3 — 챗 승인 감사와 분리. 검토 이력은 quality DB 의 review_audit 만 읽는다."""
        from tests.unit._source_probe import source_of
        from workflow.quality import review

        src = source_of(review.history)
        assert "ReviewAudit" in src
        assert "chat" not in src.lower()


# ==============================================================
# 7. 사이드카 불가침(S1) — 검토는 DB 에만
# ==============================================================


def test_review_module_never_touches_sidecars():
    from pathlib import Path

    from workflow.quality import review

    src = Path(review.__file__).read_text(encoding="utf-8")
    for token in (".quality_gate.md", ".validation.md", ".field_confidence.md", "write_text", "atomic_write_text"):
        assert token not in src, f"검토 모듈이 사이드카를 만진다: {token}"


# ==============================================================
# 8. 동시성 — lost update · 생성 경합 · 잠금 (리뷰 C1 · W1)
# ==============================================================


class TestConcurrency:

    def test_two_sessions_same_version_second_writer_conflicts(self, qdb):
        """두 세션이 같은 version 을 읽고 차례로 쓴다 — 두 번째는 409 이고 첫 번째 판정이 살아남는다.

        `SELECT 후 비교 → 무조건 UPDATE` 였던 초판은 둘 다 200 을 주고 첫 판정을 조용히 잃었다(리뷰 C1 실측).
        배리어로 두 세션의 SELECT 가 모두 끝난 뒤에 UPDATE 가 나가게 한다.
        """
        import threading

        from workflow.quality import review as review_mod
        from workflow.quality.db import get_session

        rid = _make_run(qdb)
        sha = _run_sha(qdb, rid)
        first = _app().post(f"/api/review/runs/{rid}", json=_body(sha)).json()["record"]
        assert first["version"] == 1

        barrier = threading.Barrier(2, timeout=10)
        orig_first = review_mod.ReviewRecord  # 참조 유지
        real_query_cls = type(get_session)  # noqa: F841

        # SELECT(기존 기록 읽기) 직후에 배리어를 거는 훅: `session.query(ReviewRecord)...first()` 가 돌아온 뒤 대기.
        orig_upsert = review_mod._upsert_in_session

        def _paced(session, **kw):
            q = session.query

            def _query(*a, **k):
                res = q(*a, **k)
                if a and a[0] is orig_first:
                    first_ = res.first

                    def _first():
                        row = first_()
                        try:
                            barrier.wait()
                        except threading.BrokenBarrierError:
                            pass
                        return row
                    res.first = _first
                return res
            session.query = _query
            return orig_upsert(session, **kw)

        review_mod._upsert_in_session = _paced
        results = {}
        try:
            def _writer(tag, decision):
                try:
                    out = review_mod.upsert_review(
                        lambda: get_session(qdb), run_id=rid, reviewer="tester", decision=decision,
                        comment=tag, expected_sha256=sha, version=1,
                    )
                    results[tag] = ("ok", out["record"]["version"])
                except review_mod.ReviewError as exc:
                    results[tag] = (exc.code, None)
                except Exception as exc:  # 어떤 예외든 500 형태로 새면 실패
                    results[tag] = ("EXC:" + type(exc).__name__, str(exc)[:80])

            t1 = threading.Thread(target=_writer, args=("A", "needs_work"))
            t2 = threading.Thread(target=_writer, args=("B", "rejected"))
            t1.start()
            t2.start()
            t1.join(20)
            t2.join(20)
        finally:
            review_mod._upsert_in_session = orig_upsert
        codes = sorted(v[0] for v in results.values())
        assert codes == ["VERSION_CONFLICT", "ok"], results
        rows = _rows(qdb, "review_records")
        assert len(rows) == 1 and rows[0]["version"] == 2
        winner = [k for k, v in results.items() if v[0] == "ok"][0]
        assert rows[0]["comment"] == winner  # 이긴 쪽의 판정이 남았다
        assert [a["action"] for a in _rows(qdb, "review_audit")] == ["create", "update"]  # 진 쪽은 감사행도 없다

    def test_create_race_unique_violation_is_409_not_500(self, qdb, monkeypatch):
        """두 요청이 서로의 커밋 전에 '기존 없음' 을 보면 UNIQUE 가 데이터를 지키고 응답은 409 로 번역된다(리뷰 W1)."""
        from workflow.quality import review as review_mod
        from workflow.quality.db import get_session

        rid = _make_run(qdb)
        sha = _run_sha(qdb, rid)
        _app().post(f"/api/review/runs/{rid}", json=_body(sha))  # 첫 요청이 이미 기록을 만들었다
        orig = review_mod._upsert_in_session

        class _NoRow:
            def filter_by(self, **_kw):
                return self

            def first(self):
                return None

        def _patched(session, **kw):
            q = session.query

            def _query(*a, **k):
                # 두 번째 요청의 SELECT 는 첫 요청의 커밋 전 스냅샷을 본 것처럼 — 기존 없음
                if a and a[0] is review_mod.ReviewRecord:
                    return _NoRow()
                return q(*a, **k)
            session.query = _query
            return orig(session, **kw)

        monkeypatch.setattr(review_mod, "_upsert_in_session", _patched)
        with pytest.raises(review_mod.VersionConflict) as ei:
            review_mod.upsert_review(lambda: get_session(qdb), run_id=rid, reviewer="tester", decision="rejected",
                                     comment=None, expected_sha256=sha, version=None)
        assert ei.value.extra.get("cause") == "unique_violation"
        assert len(_rows(qdb, "review_records")) == 1
        assert [a["action"] for a in _rows(qdb, "review_audit")] == ["create"]

    def test_locked_db_is_503_db_busy(self, qdb, monkeypatch):
        """잠금 대기 초과는 데이터 손실이 아니라 재시도 대상 — 500 이 아니라 503 DB_BUSY."""
        from sqlalchemy.exc import OperationalError

        from workflow.quality import review as review_mod

        rid = _make_run(qdb)
        sha = _run_sha(qdb, rid)

        def _locked(session, **kw):
            raise OperationalError("INSERT", {}, Exception("database is locked"))

        monkeypatch.setattr(review_mod, "_upsert_in_session", _locked)
        res = _app().post(f"/api/review/runs/{rid}", json=_body(sha))
        assert res.status_code == 503 and res.json()["error"]["code"] == "DB_BUSY"
        assert _rows(qdb, "review_records") == []


# ==============================================================
# 9. 레거시 DB(R33 형상)에 두 테이블이 생기고 FK 가 집행된다 (리뷰 W5 · W9)
# ==============================================================


def test_legacy_r33_db_gains_review_tables_and_fk_is_enforced(monkeypatch, tmp_path):
    from datetime import datetime, timezone

    from sqlalchemy.exc import IntegrityError

    from tests.unit.test_quality_output_sha256 import _LEGACY_DDL
    from workflow.quality import db as qdb_mod
    from workflow.quality.models import ReviewRecord

    db_file = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db_file)
    ddl = _LEGACY_DDL.split("-- (R34 형상")[0]  # R33 형상 = 검토 테이블 없음
    conn.executescript(ddl)
    conn.execute("INSERT INTO generation_runs (run_uuid, doc_type, status) VALUES ('u1','sits','success')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(qdb_mod, "_default_db_path", lambda: db_file)
    qdb_mod.reset_engine()
    try:
        qdb_mod.init_db(db_file)
        conn = sqlite3.connect(db_file)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        assert {"review_records", "review_audit"} <= names
        now = datetime.now(timezone.utc)
        with pytest.raises(IntegrityError):  # 없는 run 으로는 기록이 들어가지 않는다(FK 집행)
            with qdb_mod.get_session(db_file) as s:
                s.add(ReviewRecord(run_id=999999, output_sha256="a" * 64, reviewer="r", decision="approved",
                                   version=1, created_at=now, updated_at=now))
    finally:
        qdb_mod.reset_engine()
