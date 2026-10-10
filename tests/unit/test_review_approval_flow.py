"""(R48-a) 승인 절차 — 승인자 역할 · 자기 승인 차단(4-eyes) · `created_by` 기록 · 게시 게이트.

R34 의 검토 기록은 **admin 1명 단독 검토**였다(§8 #8 (a)). 이 라운드가 더한 것:

1. 쓰기 주체 = admin **또는 승인자**(`config/approvers.json`). 둘 다 아니면 403 `REVIEWER_REQUIRED`.
2. `generation_runs.created_by` — `record_run` 이 요청 contextvar 에서 채운다. 검토자와 같으면 403 `SELF_REVIEW`.
   NULL(구 run)은 판정 불가 → 막지 않고 `created_by_known:false` 로 공시.
3. 조회의 `can_review`/`review_block_reason` 은 **run 단위**(`self_review`) — 폼이 보이면 POST 가 통과한다(R37 D-1 약속 유지).
4. `approval_for_sha256`/`require_approved_bytes` — 게시(`/api/jenkins/uds/publish`)는 그 바이트에 `approved` 가 있어야 한다.
"""
from __future__ import annotations

import hashlib
import sqlite3
import uuid
from typing import Optional

import pytest

pytest.importorskip("fastapi")

from tests.unit.test_review_records import _app, _body, _make_run, _rows, _run_sha  # noqa: E402


@pytest.fixture
def qdb(monkeypatch, tmp_path):
    """`test_review_records.qdb` 와 같은 격리 — 프로세스 임시 DB 대신 테스트마다 새 파일."""
    from workflow.quality import db as qdb_mod

    db_file = tmp_path / "q.sqlite"
    monkeypatch.setattr(qdb_mod, "_default_db_path", lambda: db_file)
    qdb_mod.reset_engine()
    qdb_mod.init_db(db_file)
    yield db_file
    qdb_mod.reset_engine()


def _make_run_by(db, creator: Optional[str], **kw) -> int:
    from workflow.quality.db import get_session
    from workflow.quality.models import GenerationRun

    rid = _make_run(db, **kw)
    with get_session(db) as s:
        s.query(GenerationRun).filter_by(id=rid).update({GenerationRun.created_by: creator})
    return rid


# ==============================================================
# 1. 역할 — 승인자는 admin 이 아니어도 쓴다, 둘 다 아니면 403
# ==============================================================


class TestReviewerRole:

    def test_approver_who_is_not_admin_can_write(self, qdb):
        from backend.services.admin_users import is_admin

        assert is_admin("reviewer01") is False
        c = _app(user="reviewer01", admin="reviewer01")   # _app 은 admin 인자를 승인자 목록에 넣는다
        rid = _make_run(qdb)
        st = c.get(f"/api/review/runs/{rid}").json()
        assert st["can_review"] is True and st["review_block_reason"] is None
        res = c.post(f"/api/review/runs/{rid}", json=_body(_run_sha(qdb, rid)))
        assert res.status_code == 200, res.text
        assert _rows(qdb, "review_records")[0]["reviewer"] == "reviewer01"

    def test_neither_role_is_403_reviewer_required_and_state_agrees(self, qdb):
        c = _app(user="someone", admin=None)
        rid = _make_run(qdb)
        st = c.get(f"/api/review/runs/{rid}").json()
        assert (st["can_review"], st["review_block_reason"]) == (False, "not_reviewer")
        res = c.post(f"/api/review/runs/{rid}", json=_body(_run_sha(qdb, rid)))
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "REVIEWER_REQUIRED"

    def test_viewer_is_reviewer_is_admin_or_approver(self):
        from workflow.quality.review import Viewer

        assert Viewer(name="a", is_admin=True, has_bearer=True).can_review is True
        assert Viewer(name="a", is_approver=True, has_bearer=True).can_review is True
        assert Viewer(name="a", is_approver=True, has_bearer=False).block_reason == "jwt_required"
        assert Viewer(name="a", has_bearer=True).block_reason == "not_reviewer"


# ==============================================================
# 2. 4-eyes — 만든 사람은 판정하지 못한다
# ==============================================================


class TestSelfReview:

    def test_creator_gets_self_review_block_and_403(self, qdb):
        rid = _make_run_by(qdb, "tester")
        c = _app()                                     # tester = admin + Bearer
        st = c.get(f"/api/review/runs/{rid}").json()
        assert st["created_by"] == "tester" and st["created_by_known"] is True
        assert (st["can_review"], st["review_block_reason"]) == (False, "self_review")
        res = c.post(f"/api/review/runs/{rid}", json=_body(_run_sha(qdb, rid)))
        assert res.status_code == 403, res.text
        assert res.json()["error"]["code"] == "SELF_REVIEW"
        assert _rows(qdb, "review_records") == []
        assert _rows(qdb, "review_audit") == []

    def test_other_approver_can_review_the_same_run(self, qdb):
        rid = _make_run_by(qdb, "tester")
        c = _app(user="reviewer01", admin="reviewer01")
        st = c.get(f"/api/review/runs/{rid}").json()
        assert st["can_review"] is True
        assert c.post(f"/api/review/runs/{rid}", json=_body(_run_sha(qdb, rid))).status_code == 200

    def test_identity_match_ignores_case_and_whitespace(self, qdb):
        """`HBRND2` 가 만든 run 을 `hbrnd2` 가 승인하는 길이 있으면 4-eyes 는 이름 표기 하나로 뚫린다."""
        from workflow.quality.review import is_same_identity

        assert is_same_identity(" HBRND2 ", "hbrnd2") is True
        assert is_same_identity(None, "x") is False and is_same_identity("", "") is False
        rid = _make_run_by(qdb, "TESTER ")
        res = _app().post(f"/api/review/runs/{rid}", json=_body(_run_sha(qdb, rid)))
        assert res.status_code == 403 and res.json()["error"]["code"] == "SELF_REVIEW"

    def test_unknown_creator_is_not_blocked_but_is_disclosed(self, qdb):
        """구 run(NULL)을 막으면 R48 이전 run 전부가 영구 미승인 — 대신 판정 불가를 **말한다**."""
        rid = _make_run(qdb)   # created_by NULL
        c = _app()
        st = c.get(f"/api/review/runs/{rid}").json()
        assert st["created_by"] is None and st["created_by_known"] is False
        assert st["can_review"] is True
        assert c.post(f"/api/review/runs/{rid}", json=_body(_run_sha(qdb, rid))).status_code == 200

    def test_batch_states_agree_with_single(self, qdb):
        rid = _make_run_by(qdb, "tester")
        c = _app()
        single = c.get(f"/api/review/runs/{rid}").json()
        batch = c.get(f"/api/review/states?run_ids={rid}").json()["states"][str(rid)]
        assert batch["can_review"] is single["can_review"] is False
        assert batch["review_block_reason"] == single["review_block_reason"] == "self_review"
        assert "created_by" in batch and "_created_by_raw" not in batch and "_created_by_raw" not in single

    def test_creator_name_is_masked_for_non_admin_non_self(self, qdb):
        rid = _make_run_by(qdb, "hbrnd2")
        d = _app(user="reviewer01", admin="reviewer01").get(f"/api/review/runs/{rid}").json()
        assert d["created_by_known"] is True
        assert d["created_by"] != "hbrnd2", "검토자 이름과 같은 노출 규칙 — 승인자(비admin)에겐 마스킹"


# ==============================================================
# 3. `created_by` 기록 — record_run 이 채운다
# ==============================================================


class TestCreatedByRecording:

    def _uds_data(self):
        return {"quick_gate": {"rates": {"description_fill_rate": 1.0}, "counts": {"total_functions": 3}}}

    def test_record_run_takes_identity_from_request_context(self, qdb):
        from backend.user_context import current_user
        from workflow.quality.db import get_session
        from workflow.quality.models import GenerationRun
        from workflow.quality.recorder import record_run

        tok = current_user.set("maker01")
        try:
            rid = record_run("uds", self._uds_data(), scm_id="p", db_path=qdb)
        finally:
            current_user.reset(tok)
        assert rid > 0
        with get_session(qdb) as s:
            assert s.query(GenerationRun).filter_by(id=rid).one().created_by == "maker01"

    def test_explicit_argument_wins_and_default_identity_is_null(self, qdb):
        from backend.user_context import current_user
        from workflow.quality.db import get_session
        from workflow.quality.models import GenerationRun
        from workflow.quality.recorder import record_run

        tok = current_user.set("ctxuser")
        try:
            rid1 = record_run("uds", self._uds_data(), scm_id="p", db_path=qdb, created_by="explicit")
        finally:
            current_user.reset(tok)
        tok = current_user.set("default")
        try:
            rid2 = record_run("uds", self._uds_data(), scm_id="p", db_path=qdb)
        finally:
            current_user.reset(tok)
        with get_session(qdb) as s:
            assert s.query(GenerationRun).filter_by(id=rid1).one().created_by == "explicit"
            assert s.query(GenerationRun).filter_by(id=rid2).one().created_by is None

    def test_empty_output_run_also_records_creator(self, qdb):
        """빈 산출물 분기(`_record_empty_output_run`)도 같은 값을 남긴다 — 분기 하나가 빠지면 그 run 만 4-eyes 밖이다."""
        from backend.user_context import current_user
        from workflow.quality.db import get_session
        from workflow.quality.models import GenerationRun
        from workflow.quality.recorder import record_run

        tok = current_user.set("maker02")
        try:
            rid = record_run("uds", {"quick_gate": {"rates": {}, "counts": {"total_functions": 0}}}, scm_id="p", db_path=qdb)
        finally:
            current_user.reset(tok)
        with get_session(qdb) as s:
            run = s.query(GenerationRun).filter_by(id=rid).one()
            assert run.status == "empty_output"
            assert run.created_by == "maker02"

    def test_legacy_db_gains_created_by_column(self, tmp_path, monkeypatch):
        """Alembic 이 없다 — `_COLUMN_ADDITIONS` 한 줄이 빠지면 기존 DB 에서 모든 조회가 500 이다(R33 과 같은 축)."""
        from workflow.quality import db as qdb_mod

        db_file = tmp_path / "legacy.sqlite"
        conn = sqlite3.connect(db_file)
        conn.execute(
            "CREATE TABLE generation_runs (id INTEGER PRIMARY KEY, run_uuid VARCHAR(36) NOT NULL UNIQUE, "
            "doc_type VARCHAR(10) NOT NULL, project_root TEXT, scm_id VARCHAR(64), target_function VARCHAR(200), "
            "status VARCHAR(20), created_at DATETIME, elapsed_sec FLOAT, output_path TEXT, output_size_bytes INTEGER, "
            "output_sha256 VARCHAR(64), ai_model VARCHAR(80), error_msg TEXT, meta_json TEXT)"
        )
        conn.execute(
            "INSERT INTO generation_runs (run_uuid, doc_type, status) VALUES (?, 'uds', 'success')", (str(uuid.uuid4()),)
        )
        conn.commit()
        conn.close()
        monkeypatch.setattr(qdb_mod, "_default_db_path", lambda: db_file)
        qdb_mod.reset_engine()
        try:
            qdb_mod.init_db(db_file)
            conn = sqlite3.connect(db_file)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(generation_runs)")}
            idx = {r[1] for r in conn.execute("PRAGMA index_list(generation_runs)")}
            conn.close()
            assert "created_by" in cols
            assert "ix_gen_run_created_by" in idx
            # 기존 행은 NULL — 조회가 죽지 않고 '판정 불가' 로 나온다.
            d = _app().get("/api/review/runs/1").json()
            assert d["created_by_known"] is False and d["can_review"] is True
        finally:
            qdb_mod.reset_engine()


# ==============================================================
# 4. 승인 상태와 게시 게이트 — 바이트 해시가 열쇠
# ==============================================================


def _approve(db, rid, reviewer="reviewer01", decision="approved"):
    c = _app(user=reviewer, admin=reviewer)
    res = c.post(f"/api/review/runs/{rid}", json=_body(_run_sha(db, rid), decision=decision))
    assert res.status_code == 200, res.text


class TestApprovalState:

    def test_state_approved_flag_counts_only_matching_bytes(self, qdb):
        rid = _make_run(qdb)
        c = _app()
        assert c.get(f"/api/review/runs/{rid}").json()["approved"] is False
        _approve(qdb, rid, decision="needs_work")
        assert c.get(f"/api/review/runs/{rid}").json()["approved"] is False
        _approve(qdb, rid, reviewer="reviewer02")
        st = c.get(f"/api/review/runs/{rid}").json()
        assert st["approved"] is True and st["approved_runs"] == [rid]
        # run 의 해시가 바뀌면(재기록) 옛 승인은 세지 않는다.
        conn = sqlite3.connect(qdb)
        conn.execute("UPDATE generation_runs SET output_sha256=? WHERE id=?", ("f" * 64, rid))
        conn.commit()
        conn.close()
        assert c.get(f"/api/review/runs/{rid}").json()["approved"] is False

    def test_approved_is_byte_scoped_like_the_publish_gate(self, qdb):
        """(리뷰 W2) 같은 바이트를 낸 다른 run 의 승인은 이 run 의 승인이다 — 화면 '미승인' 인데 게시는 통과하는 갈림을 없앤다."""
        sha = hashlib.sha256(b"same-bytes").hexdigest()
        r1 = _make_run(qdb, sha=sha)
        r2 = _make_run(qdb, sha=sha)
        _approve(qdb, r1)
        c = _app()
        st2 = c.get(f"/api/review/runs/{r2}").json()
        assert st2["approved"] is True and st2["approved_runs"] == [r1]
        assert st2["reviews"] == []          # 기록은 r1 에만 — 승인 상태와 기록 목록은 다른 사실
        batch = c.get(f"/api/review/states?run_ids={r2}").json()["states"][str(r2)]
        assert batch["approved"] is True and "_approval" not in batch and "_approval" not in st2

    def test_admin_who_is_not_approver_can_write(self, qdb):
        """(리뷰 W6) `is_admin or is_approver` 의 admin 분기 — tester 는 conftest 기본 admin, 승인자 목록엔 없다."""
        from backend.services.approvers import is_approver

        assert is_approver("tester") is False
        rid = _make_run(qdb)
        c = _app(admin=None)   # 승인자 등록 없이
        assert c.get(f"/api/review/runs/{rid}").json()["can_review"] is True
        assert c.post(f"/api/review/runs/{rid}", json=_body(_run_sha(qdb, rid))).status_code == 200

    def test_approval_for_sha256_and_require(self, qdb):
        from workflow.quality.db import get_session
        from workflow.quality.review import NotApproved, approval_for_sha256, require_approved_bytes

        rid = _make_run(qdb)
        sha = _run_sha(qdb, rid)
        with get_session(qdb) as s:
            st = approval_for_sha256(s, sha)
            assert st == {"approved": False, "sha256": sha, "records": [], "runs": []}
            assert approval_for_sha256(s, "")["approved"] is False
            with pytest.raises(NotApproved) as ei:
                require_approved_bytes(s, sha)
            assert ei.value.code == "NOT_APPROVED" and ei.value.status == 409
        _approve(qdb, rid, decision="rejected")
        with get_session(qdb) as s:
            with pytest.raises(NotApproved) as ei:
                require_approved_bytes(s, sha.upper())     # 대소문자 무관
            assert [r["decision"] for r in ei.value.extra["records"]] == ["rejected"]
            assert ei.value.extra["runs"] == [rid]
        _approve(qdb, rid, reviewer="reviewer02")
        with get_session(qdb) as s:
            st = require_approved_bytes(s, sha)
            assert st["approved"] is True and st["runs"] == [rid]
            assert all("reviewer_masked" in r and "reviewer" not in r for r in st["records"])


class TestPublishGate:
    """`/api/jenkins/uds/publish` — 승인 없는 바이트는 409, 승인된 바이트만 docs/ 로 간다."""

    @pytest.fixture
    def pub(self, tmp_path, monkeypatch, qdb):
        from fastapi.testclient import TestClient

        from backend.main import app
        from backend.routers import jenkins as J

        fake_repo = tmp_path / "repo"
        (fake_repo / "docs").mkdir(parents=True)
        monkeypatch.setattr(J, "repo_root", fake_repo)
        cache_root = tmp_path / "cache"
        (cache_root / "exports").mkdir(parents=True)
        src = cache_root / "exports" / "UDS_r48.docx"
        src.write_bytes(b"approved-bytes")
        client = TestClient(app)

        def post():
            return client.post("/api/jenkins/uds/publish", headers={"X-User": "tester"},
                               json={"job_url": "http://j/job/x/", "cache_root": str(cache_root),
                                     "filename": "UDS_r48.docx", "target_dir": "docs/r48"})
        return {"post": post, "src": src, "out": fake_repo / "docs" / "r48" / "UDS_r48.docx", "db": qdb}

    def _run_for_file(self, db, path):
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        return _make_run(db, doc_type="uds", sha=sha, output_path=str(path))

    def test_unreviewed_bytes_are_409_and_nothing_is_written(self, pub):
        r = pub["post"]()
        assert r.status_code == 409, r.text
        assert r.json()["error"]["code"] == "NOT_APPROVED"
        assert not pub["out"].exists()

    def test_rejected_bytes_are_409_with_the_record_listed(self, pub):
        rid = self._run_for_file(pub["db"], pub["src"])
        _approve(pub["db"], rid, decision="rejected")
        r = pub["post"]()
        assert r.status_code == 409
        err = r.json()["error"]
        assert err["code"] == "NOT_APPROVED"
        # error_handler 규약: code/message 밖의 키는 `error.detail` 아래로 간다.
        assert [x["decision"] for x in err["detail"]["records"]] == ["rejected"] and err["detail"]["runs"] == [rid]

    def test_approved_bytes_publish(self, pub):
        rid = self._run_for_file(pub["db"], pub["src"])
        _approve(pub["db"], rid)
        r = pub["post"]()
        assert r.status_code == 200, r.text
        assert pub["out"].read_bytes() == b"approved-bytes"
        assert r.json()["approval"]["approved"] is True and r.json()["approval"]["runs"] == [rid]

    def test_approval_is_bound_to_bytes_not_to_the_file_name(self, pub):
        """같은 이름으로 파일이 바뀌면(재생성) 옛 승인은 그 파일에 대한 것이 아니다."""
        rid = self._run_for_file(pub["db"], pub["src"])
        _approve(pub["db"], rid)
        pub["src"].write_bytes(b"regenerated-bytes")
        r = pub["post"]()
        assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_APPROVED"
        assert not pub["out"].exists()


# ==============================================================
# 5. 프론트 lockstep — 새 오류 코드에 문장이 있다
# ==============================================================


def test_frontend_has_text_for_new_codes():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "frontend-v2" / "src" / "gateVerdict.js").read_text(encoding="utf-8")
    for code in ("REVIEWER_REQUIRED", "SELF_REVIEW", "NOT_APPROVED"):
        assert f"{code}:" in js, f"REVIEW_ERROR_TEXT 에 {code} 문장이 없다"
    for token in ("not_reviewer", "self_review", "jwt_required"):
        assert f"{token}:" in js
    assert "not_admin:" not in js, "옛 사유 토큰이 남아 있으면 서버가 내지 않는 사유에 문장이 붙어 있는 것"
    py = (Path(__file__).resolve().parents[2] / "workflow" / "quality" / "review.py").read_text(encoding="utf-8")
    for token in ("not_reviewer", "self_review", "jwt_required"):
        assert f'= "{token}"' in py, f"서버 BLOCK_* 에 {token} 이 없다"
    assert '= "not_admin"' not in py
