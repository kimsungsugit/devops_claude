"""R33 (C-1) — 산출물 바이트 해시 `generation_runs.output_sha256` + `busy_timeout`.

## 왜 (실측 2026-09-07, `reports/quality.sqlite` 2,034 run)

`output_path` 가 있는 run 43개 중 저장소 안 경로 40개는 **전부 파일이 있다**. 그런데
그중 **18개는 기록된 `output_size_bytes` 와 지금 그 경로의 파일 크기가 다르다** —
`reports/_gen_check/SITS_gate.xlsm` 한 경로를 21 run 이 돌려썼다. 경로는 run 을
식별하지 못한다. 검토 기록(R34~)이 "어느 바이트에 대한 판정인가" 를 고정하려면
**기록 시점의 해시**가 있어야 하고, 그게 이 컬럼이다.

## 가드가 막는 것

1. **모델 필드 추가 ≠ DB 컬럼 추가** — Alembic 이 없어 `_COLUMN_ADDITIONS` 한 줄이
   빠지면 기존 DB 를 읽는 `/api/quality/*` 전체가 `no such column` 500. 구 스키마
   DB 를 raw DDL 로 만들어 다리가 놓이는지 본다(`test_quality_scm_axis.py` 와 같은 형태).
   `TestModelDbDrift` 는 **앞으로 어떤 컬럼을 더해도** 같은 누락을 잡는다(모델 컬럼
   전체 ↔ 마이그레이션 후 DB 컬럼 전체 대조).
2. **해시가 기록되지 않는 것** — 경로 파일에서 계산 / 명시 인자 우선 / 파일 부재 → NULL
   (예외로 기록 통째 유실 금지) / hex 아닌 인자 → NULL.
3. **`busy_timeout` 선언** — ⚠ 계획서의 "busy_timeout 없음" 은 오진이었다(R33 뮤테이션 M2 ALIVE 로
   드러남): Python `sqlite3.connect()` 기본 `timeout=5.0` 이 이미 5초 busy handler 라 실효값은 원래
   5000 이었다. PRAGMA 가 지키는 것은 **드라이버 기본값이 꺼진 커넥션**(`timeout=0`)에서도 5초로
   되돌리는 것이고, 가드는 바로 그 커넥션으로 잰다(엔진 기본 경로에서 재면 vacuous — 리뷰 W1).
4. **NULL 의 사유**(W5) — 경로 없음·파일 부재·파일 아님·읽기 실패·인자 불량이 한 값으로 접히지 않는다.
5. **기록 유실**(C1) — `_measure_output` 의 어떤 실패도 `record_run` 을 -1 로 만들지 않는다.
"""
from __future__ import annotations

import hashlib
import sqlite3
import uuid

import pytest

# `test_quality_scm_axis.py` 의 구 스키마(2026-08-07 실측) 그대로 — `scm_id` 도 `output_sha256` 도 없는
# 모양(두 컬럼을 한 번에 태운다 — `_apply_column_additions` 는 항목별 독립 판정이라 순서 의존은 없다).
# 새 모델로 CREATE 하면 컬럼이 이미 있어 가드가 안 된다.
_LEGACY_DDL = """
CREATE TABLE generation_runs (
    id INTEGER NOT NULL,
    run_uuid VARCHAR(36) NOT NULL,
    doc_type VARCHAR(10) NOT NULL,
    project_root TEXT,
    target_function VARCHAR(200),
    status VARCHAR(20),
    created_at DATETIME,
    elapsed_sec FLOAT,
    output_path TEXT,
    output_size_bytes INTEGER,
    ai_model VARCHAR(80),
    error_msg TEXT,
    meta_json TEXT,
    PRIMARY KEY (id),
    UNIQUE (run_uuid)
);
CREATE TABLE quality_scores (
    id INTEGER NOT NULL,
    run_id INTEGER NOT NULL,
    metric_name VARCHAR(50) NOT NULL,
    value FLOAT,
    gate_pass BOOLEAN,
    threshold FLOAT,
    PRIMARY KEY (id),
    FOREIGN KEY(run_id) REFERENCES generation_runs (id)
);
CREATE TABLE quality_summaries (
    run_id INTEGER NOT NULL,
    overall_score FLOAT,
    gate_pass BOOLEAN,
    score_delta FLOAT,
    prev_run_id INTEGER,
    fn_count INTEGER,
    PRIMARY KEY (run_id),
    FOREIGN KEY(run_id) REFERENCES generation_runs (id)
);
"""


@pytest.fixture
def qdb(monkeypatch, tmp_path):
    from workflow.quality import db as qdb_mod

    db_file = tmp_path / "q.sqlite"
    monkeypatch.setattr(qdb_mod, "_default_db_path", lambda: db_file)
    qdb_mod.reset_engine()
    yield db_file
    qdb_mod.reset_engine()


@pytest.fixture
def legacy_db(qdb):
    conn = sqlite3.connect(qdb)
    conn.executescript(_LEGACY_DDL)
    conn.execute(
        "INSERT INTO generation_runs (run_uuid, doc_type, project_root, status, output_path)"
        " VALUES ('legacy-uuid-1', 'sits', 'D:/x', 'success', 'D:/x/SITS_gate.xlsm')"
    )
    conn.commit()
    conn.close()
    return qdb


def _columns(db_path, table="generation_runs") -> set:
    conn = sqlite3.connect(db_path)
    try:
        return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def _sits(pct: float = 80.0) -> dict:
    return {
        "requirement_traceability_pct": pct,
        "io_coverage_pct": pct,
        "total_test_cases": 5,
    }


def _meta(row: dict) -> dict:
    import json

    return json.loads(row["meta_json"]) if row.get("meta_json") else {}


def _run_row(db_path, run_id: int) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return dict(conn.execute(
            "SELECT * FROM generation_runs WHERE id=?", (run_id,)
        ).fetchone())
    finally:
        conn.close()


# ==============================================================
# 1. 마이그레이션 — 구 DB 가 컬럼을 얻고, 모델↔DB 가 어긋나지 않는다
# ==============================================================


class TestColumnMigration:

    def test_legacy_db_gains_output_sha256(self, legacy_db):
        from workflow.quality.db import init_db

        assert "output_sha256" not in _columns(legacy_db)
        init_db(legacy_db)
        assert "output_sha256" in _columns(legacy_db)

    def test_existing_rows_read_as_null_not_error(self, legacy_db):
        """구 행은 해시가 NULL 이어야 한다 — '' 나 예외가 아니라."""
        from workflow.quality.db import get_session, init_db
        from workflow.quality.models import GenerationRun

        init_db(legacy_db)
        with get_session(legacy_db) as s:
            row = s.query(GenerationRun).filter_by(run_uuid="legacy-uuid-1").one()
            assert row.output_sha256 is None
            assert row.output_path == "D:/x/SITS_gate.xlsm"

    def test_running_twice_is_safe(self, legacy_db):
        from workflow.quality.db import init_db

        init_db(legacy_db)
        init_db(legacy_db)
        assert "output_sha256" in _columns(legacy_db)

    def test_runs_endpoint_is_200_on_migrated_legacy_db(self, legacy_db):
        """`_COLUMN_ADDITIONS` 가 빠지면 이 요청이 500 이다 — 기존 DB 를 읽는 모든 조회가 그렇다."""
        pytest.importorskip("fastapi")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from backend.dependencies.auth import require_user
        from backend.routers import quality

        app = FastAPI()
        app.include_router(quality.router)
        app.dependency_overrides[require_user] = lambda: "tester"
        client = TestClient(app)
        res = client.get("/api/quality/runs")
        assert res.status_code == 200, res.text
        runs = res.json()["runs"]
        assert len(runs) == 1
        # 응답에 필드가 **있고** None 이다(없는 것과 다르다 — 리더가 `hash_unavailable` 로 가른다).
        assert "output_sha256" in runs[0]
        assert runs[0]["output_sha256"] is None


class TestModelDbDrift:
    """앞으로 어떤 컬럼을 더하든 `_COLUMN_ADDITIONS` 누락을 여기서 잡는다."""

    def test_every_model_column_exists_after_migrating_legacy_db(self, legacy_db):
        from workflow.quality.db import init_db
        from workflow.quality.models import GenerationRun

        init_db(legacy_db)
        model_cols = {c.name for c in GenerationRun.__table__.columns}
        db_cols = _columns(legacy_db)
        assert model_cols - db_cols == set(), (
            f"모델에만 있는 컬럼 {sorted(model_cols - db_cols)} — "
            "db.py `_COLUMN_ADDITIONS` 에 한 줄이 빠졌다(기존 DB 조회 전부 500)"
        )

    def test_column_additions_declare_the_new_column(self):
        from workflow.quality.db import _COLUMN_ADDITIONS

        assert ("generation_runs", "output_sha256") in {
            (t, c) for t, c, _ddl, _ix in _COLUMN_ADDITIONS
        }


# ==============================================================
# 2. 기록 — 해시가 실제로 들어간다
# ==============================================================


class TestRecordRunHashesOutput:

    def test_hash_is_computed_from_output_path(self, qdb, tmp_path):
        from workflow.quality.recorder import record_run

        out = tmp_path / "SITS_gate.xlsm"
        out.write_bytes(b"PK\x03\x04 sits bytes v1")
        rid = record_run("sits", _sits(), output_path=str(out), db_path=qdb)
        assert rid > 0
        row = _run_row(qdb, rid)
        assert row["output_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
        assert row["output_size_bytes"] == out.stat().st_size

    def test_same_path_different_bytes_get_different_hashes(self, qdb, tmp_path):
        """실측 18/40 의 형태 — 한 경로를 여러 run 이 돌려쓴다. 경로가 아니라 바이트를 고정해야 한다."""
        from workflow.quality.recorder import record_run

        out = tmp_path / "SITS_gate.xlsm"
        out.write_bytes(b"v1")
        r1 = record_run("sits", _sits(), output_path=str(out), db_path=qdb)
        out.write_bytes(b"v2 overwritten")
        r2 = record_run("sits", _sits(), output_path=str(out), db_path=qdb)
        h1, h2 = _run_row(qdb, r1)["output_sha256"], _run_row(qdb, r2)["output_sha256"]
        assert h1 and h2 and h1 != h2
        assert _run_row(qdb, r1)["output_path"] == _run_row(qdb, r2)["output_path"]

    def test_explicit_sha_wins_over_file(self, qdb, tmp_path):
        """BytesIO 응답 빌더(C-4)는 경로 없이 해시만 넘긴다 — 파일이 있어도 명시 값이 정본."""
        from workflow.quality.recorder import record_run

        out = tmp_path / "o.xlsx"
        out.write_bytes(b"file bytes")
        explicit = hashlib.sha256(b"the bytes that were actually streamed").hexdigest()
        rid = record_run("sits", _sits(), output_path=str(out), output_sha256=explicit, db_path=qdb)
        row = _run_row(qdb, rid)
        assert row["output_sha256"] == explicit
        # (리뷰 W2) 크기를 **파일**에서 재면 한 행의 크기와 해시가 다른 바이트를 가리킨다 — 명시 해시가
        # 있으면 크기는 명시 값뿐(없으면 NULL). 파일 크기 10 이 들어오면 안 된다.
        assert row["output_size_bytes"] is None
        assert _meta(row).get("output_sha256_reason") is None

    def test_explicit_sha_with_explicit_size(self, qdb):
        from workflow.quality.recorder import record_run, sha256_hex

        buf = b"streamed xlsx bytes"
        rid = record_run(
            "sits", _sits(), output_sha256=sha256_hex(buf), output_size_bytes=len(buf), db_path=qdb,
        )
        row = _run_row(qdb, rid)
        assert (row["output_sha256"], row["output_size_bytes"]) == (sha256_hex(buf), len(buf))

    def test_explicit_sha_without_path(self, qdb):
        from workflow.quality.recorder import record_run, sha256_hex

        explicit = sha256_hex(b"streamed xlsx")
        rid = record_run("sits", _sits(), output_sha256=explicit, db_path=qdb)
        row = _run_row(qdb, rid)
        assert row["output_sha256"] == explicit
        assert row["output_path"] is None

    def test_no_path_reason(self, qdb):
        """BytesIO 응답 빌더(C-4 전) — 경로 자체가 없다. '아직 배선 안 됨' 과 '산출물이 사라짐' 은 다르다."""
        from workflow.quality.recorder import record_run

        rid = record_run("sits", _sits(), db_path=qdb)
        row = _run_row(qdb, rid)
        assert row["output_sha256"] is None
        assert _meta(row)["output_sha256_reason"] == "no_path"

    def test_reason_absent_when_hash_recorded(self, qdb, tmp_path):
        from workflow.quality.recorder import record_run

        out = tmp_path / "o.xlsm"
        out.write_bytes(b"ok")
        rid = record_run("sits", _sits(), output_path=str(out), meta={"kind": "x"}, db_path=qdb)
        row = _run_row(qdb, rid)
        assert row["output_sha256"]
        assert "output_sha256_reason" not in _meta(row)
        assert _meta(row)["kind"] == "x"  # 호출자의 meta 는 그대로 보존

    def test_directory_path_records_null_size_and_hash(self, qdb, tmp_path):
        """(리뷰 I1) 디렉터리를 `stat` 하면 크기 0 이 나온다 — 0 은 '빈 산출물' 로 읽힌다. NULL 이어야 한다."""
        from workflow.quality.recorder import record_run

        rid = record_run("sits", _sits(), output_path=str(tmp_path), db_path=qdb)
        row = _run_row(qdb, rid)
        assert rid > 0
        assert row["output_size_bytes"] is None
        assert row["output_sha256"] is None
        assert _meta(row)["output_sha256_reason"] == "not_a_file"

    def test_nul_byte_path_does_not_lose_the_record(self, qdb, caplog):
        """(리뷰 C1) `Path.stat()` 은 NUL 경로에 `ValueError` 를 낸다 — `except OSError` 로 좁히면 그 예외가
        `record_run` 의 `return -1` 까지 새어 **품질 기록이 통째로 사라진다**. 어떤 실패든 사유로 접는다."""
        import logging

        from workflow.quality.recorder import record_run

        with caplog.at_level(logging.WARNING, logger="workflow.quality.recorder"):
            rid = record_run("sits", _sits(), output_path="a\x00b.xlsm", db_path=qdb)
        assert rid > 0, "해시 실패가 기록 유실로 번졌다"
        row = _run_row(qdb, rid)
        assert row["output_sha256"] is None
        # Python 3.12 의 `Path.exists()` 는 NUL 경로를 False 로 접으므로 `file_missing` 이 정상. 어느 쪽이든
        # 기록이 살아 있고 NULL 에 사유가 붙는 것이 계약이다.
        assert _meta(row)["output_sha256_reason"] in ("file_missing", "unreadable")

    def test_unexpected_reader_failure_is_a_reason_not_a_lost_record(self, qdb, tmp_path, monkeypatch):
        """(리뷰 C1) 읽기 단계의 **OSError 아닌** 예외(인코딩·드라이버 오류 등)도 기록을 버리지 않는다."""
        from workflow.quality import recorder

        out = tmp_path / "o.xlsm"
        out.write_bytes(b"x")

        def _boom(_p):
            raise ValueError("synthetic non-OSError while reading")

        monkeypatch.setattr(recorder, "_hash_and_size_of_file", _boom)
        rid = recorder.record_run("sits", _sits(), output_path=str(out), db_path=qdb)
        assert rid > 0, "해시 실패가 기록 유실로 번졌다"
        row = _run_row(qdb, rid)
        assert row["output_sha256"] is None
        assert row["output_size_bytes"] is None
        assert _meta(row)["output_sha256_reason"] == "unreadable"

    def test_relative_output_path_is_anchored_to_repo_root(self, qdb, tmp_path, monkeypatch):
        """(리뷰 W4) 라이브 DB 에 상대 경로 행이 실재한다. CWD 가 아니라 저장소 루트 기준이어야
        백엔드(기동 CWD)와 스크립트가 같은 파일을 해시한다."""
        import config
        from workflow.quality.recorder import record_run

        repo = tmp_path / "repo"
        (repo / "reports").mkdir(parents=True)
        (repo / "reports" / "x.xlsm").write_bytes(b"repo-root bytes")
        (repo / "config.py").write_text("", encoding="utf-8")
        elsewhere = tmp_path / "elsewhere"
        (elsewhere / "reports").mkdir(parents=True)
        (elsewhere / "reports" / "x.xlsm").write_bytes(b"cwd bytes -- wrong file")
        monkeypatch.setattr(config, "__file__", str(repo / "config.py"))
        monkeypatch.chdir(elsewhere)

        rid = record_run("sits", _sits(), output_path="reports/x.xlsm", db_path=qdb)
        row = _run_row(qdb, rid)
        assert row["output_sha256"] == hashlib.sha256(b"repo-root bytes").hexdigest()
        assert row["output_path"] == "reports/x.xlsm"  # 저장 문자열은 원본 그대로

    def test_missing_file_records_null_hash_but_still_records(self, qdb, tmp_path, caplog):
        """파일 부재는 기록을 버릴 이유가 아니다 — 해시만 NULL, 그리고 침묵하지 않는다."""
        import logging

        from workflow.quality.recorder import record_run

        ghost = tmp_path / "gone.xlsm"
        with caplog.at_level(logging.WARNING, logger="workflow.quality.recorder"):
            rid = record_run("sits", _sits(), output_path=str(ghost), db_path=qdb)
        assert rid > 0
        row = _run_row(qdb, rid)
        assert row["output_sha256"] is None
        assert row["output_size_bytes"] is None
        assert row["output_path"] == str(ghost)
        assert _meta(row)["output_sha256_reason"] == "file_missing"
        assert any("해시" in r.getMessage() for r in caplog.records)

    @pytest.mark.parametrize("bad", ["", "abc", "z" * 64, "  ", 12345])
    def test_non_hex_explicit_sha_is_null_not_stored(self, qdb, bad):
        """잘못된 해시를 저장하면 검토의 `expected_sha256` 비교가 영원히 STALE 이다."""
        from workflow.quality.recorder import record_run

        rid = record_run("sits", _sits(), output_sha256=bad, db_path=qdb)
        assert rid > 0
        row = _run_row(qdb, rid)
        assert row["output_sha256"] is None
        assert _meta(row)["output_sha256_reason"] == "invalid_arg"

    def test_uppercase_hex_is_normalized(self, qdb):
        from workflow.quality.recorder import record_run

        h = "A" * 64
        rid = record_run("sits", _sits(), output_sha256=h, db_path=qdb)
        assert _run_row(qdb, rid)["output_sha256"] == "a" * 64

    def test_uds_and_test_result_paths_forward_the_kwarg(self, qdb, tmp_path):
        """`record_uds_run` / `record_test_result_run` 은 **kwargs 경유 — 해시 인자가 새지 않는다."""
        from workflow.quality.recorder import record_test_result_run, record_uds_run, sha256_hex

        out = tmp_path / "uds.docx"
        out.write_bytes(b"docx")
        uds_eval = {"quick_gate": {"counts": {"total_functions": 3}, "rates": {}}, "gate_pass": True}
        r_uds = record_uds_run(uds_eval, output_path=str(out), db_path=qdb)
        assert r_uds > 0
        assert _run_row(qdb, r_uds)["output_sha256"] == hashlib.sha256(b"docx").hexdigest()

        r_tr = record_test_result_run(
            "sutr", {"total": 4, "passed": 4}, project_id="HDPDM01",
            output_sha256=sha256_hex(b"sutr"), db_path=qdb,
        )
        assert r_tr > 0
        assert _run_row(qdb, r_tr)["output_sha256"] == sha256_hex(b"sutr")

    def test_sha256_of_file_streams_large_file(self, tmp_path):
        """46MB docx 도 통째로 읽지 않는다 — 청크 합이 표준 해시와 같아야 한다."""
        from workflow.quality.recorder import sha256_of_file

        big = tmp_path / "big.bin"
        data = bytes(range(256)) * (5 * 1024 * 4 + 7)  # ≈5.2MB, 1MiB 경계에 안 맞는 크기
        big.write_bytes(data)
        assert sha256_of_file(big) == hashlib.sha256(data).hexdigest()

    def test_api_exposes_recorded_hash(self, qdb, tmp_path):
        pytest.importorskip("fastapi")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from backend.dependencies.auth import require_user
        from backend.routers import quality
        from workflow.quality.recorder import record_run

        out = tmp_path / "o.xlsm"
        out.write_bytes(b"api bytes")
        rid = record_run("sits", _sits(), output_path=str(out), db_path=qdb)

        app = FastAPI()
        app.include_router(quality.router)
        app.dependency_overrides[require_user] = lambda: "tester"
        client = TestClient(app)
        listed = client.get("/api/quality/runs").json()["runs"]
        detail = client.get(f"/api/quality/runs/{rid}").json()
        expect = hashlib.sha256(b"api bytes").hexdigest()
        assert [r["output_sha256"] for r in listed if r["id"] == rid] == [expect]
        assert detail["output_sha256"] == expect


# ==============================================================
# 3. busy_timeout — 잠금 경합에서 즉시 죽지 않는다
# ==============================================================


class TestBusyTimeout:
    """⚠ 엔진 기본 커넥션으로 재면 vacuous 다 — Python 드라이버 기본 timeout 이 이미 5초라 PRAGMA 를 지워도
    통과한다(뮤턴트 M2 ALIVE). 그래서 **드라이버 기본값을 끈 커넥션**(`timeout=0`)에 적용해 잰다."""

    def test_pragma_is_set_on_engine_connections(self, qdb):
        from sqlalchemy import text

        from workflow.quality.db import BUSY_TIMEOUT_MS, get_engine, init_db

        init_db(qdb)
        with get_engine(qdb).connect() as conn:
            val = conn.execute(text("PRAGMA busy_timeout")).scalar()
        assert int(val or 0) >= BUSY_TIMEOUT_MS

    def test_pragma_restores_timeout_on_a_zero_timeout_connection(self, qdb):
        """`connect_args={"timeout": 0}` 같은 뒷날의 변경이 잠금 대기를 0 으로 되돌리지 못하게 한다."""
        from workflow.quality.db import BUSY_TIMEOUT_MS, _apply_sqlite_pragmas, init_db

        init_db(qdb)
        conn = sqlite3.connect(qdb, timeout=0)
        try:
            assert int(conn.execute("PRAGMA busy_timeout").fetchone()[0]) == 0, "전제: 드라이버 대기 꺼짐"
            _apply_sqlite_pragmas(conn)
            assert int(conn.execute("PRAGMA busy_timeout").fetchone()[0]) >= BUSY_TIMEOUT_MS
        finally:
            conn.close()

    def test_write_waits_for_a_short_external_lock(self, qdb):
        """드라이버 대기가 꺼진 커넥션이라도 PRAGMA 뒤에는 다른 write lock 을 기다린다.

        `busy_timeout=0` 이면 `database is locked` 로 즉시 죽는다(뮤테이션으로 확인).
        """
        import threading
        import time

        from workflow.quality.db import _apply_sqlite_pragmas, init_db

        init_db(qdb)
        holder = sqlite3.connect(qdb, isolation_level=None, timeout=0)
        holder.execute("BEGIN IMMEDIATE")  # write lock
        result: dict = {}

        def _writer():
            w = sqlite3.connect(qdb, isolation_level=None, timeout=0)
            try:
                _apply_sqlite_pragmas(w)
                w.execute(
                    "INSERT INTO generation_runs (run_uuid, doc_type, status, created_at)"
                    " VALUES (?, 'sits', 'success', CURRENT_TIMESTAMP)",
                    (str(uuid.uuid4()),),
                )
                result["ok"] = True
            except sqlite3.OperationalError as exc:
                result["error"] = str(exc)
            finally:
                w.close()

        t = threading.Thread(target=_writer)
        t.start()
        time.sleep(0.5)
        holder.execute("COMMIT")
        holder.close()
        t.join(timeout=10)
        assert not t.is_alive()
        assert result.get("ok"), f"lock 경합에서 즉시 죽었다: {result.get('error')}"


# ==============================================================
# 4. 모델 ↔ 라우터 직렬화 필드 세트 — 응답에서 빠지면 리더가 영영 못 본다
# ==============================================================


def test_run_to_dict_includes_output_sha256():
    from backend.routers.quality import _run_to_dict

    class _Run:
        id = 1
        run_uuid = str(uuid.uuid4())
        doc_type = "sits"
        scm_id = None
        project_root = None
        target_function = None
        status = "success"
        meta_json = None
        error_msg = None
        scores = []
        created_at = None
        elapsed_sec = None
        output_path = "x"
        output_size_bytes = 1
        output_sha256 = "f" * 64
        ai_model = None
        summary = None

    assert _run_to_dict(_Run())["output_sha256"] == "f" * 64
