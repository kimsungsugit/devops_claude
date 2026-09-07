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
import json
import pathlib
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
-- (R34 형상, 2026-09-07) 검토 기록 두 테이블 — 여기 얼려 두어야 뒷날 컬럼 추가가 드리프트로 드러난다.
CREATE TABLE review_records (
    id INTEGER NOT NULL,
    run_id INTEGER NOT NULL,
    output_sha256 VARCHAR(64) NOT NULL,
    reviewer VARCHAR(120) NOT NULL,
    auth_method VARCHAR(16) NOT NULL,
    decision VARCHAR(16) NOT NULL,
    comment TEXT,
    version INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_review_run_reviewer UNIQUE (run_id, reviewer),
    FOREIGN KEY(run_id) REFERENCES generation_runs (id)
);
CREATE TABLE review_audit (
    id INTEGER NOT NULL,
    review_id INTEGER NOT NULL,
    run_id INTEGER NOT NULL,
    reviewer VARCHAR(120) NOT NULL,
    action VARCHAR(16) NOT NULL,
    decision VARCHAR(16) NOT NULL,
    output_sha256 VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(review_id) REFERENCES review_records (id),
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
        """(R34 리뷰 W5) `GenerationRun` 만이 아니라 **메타데이터의 모든 테이블**을 대조한다 —
        `review_records`/`review_audit` 에 컬럼을 더하고 `_COLUMN_ADDITIONS` 를 빠뜨려도 여기서 잡힌다."""
        from workflow.quality.db import init_db
        from workflow.quality.models import QualityBase

        init_db(legacy_db)
        missing = {}
        for table in QualityBase.metadata.sorted_tables:
            model_cols = {c.name for c in table.columns}
            gap = model_cols - _columns(legacy_db, table.name)
            if gap:
                missing[table.name] = sorted(gap)
        assert missing == {}, (
            f"모델에만 있는 컬럼 {missing} — db.py `_COLUMN_ADDITIONS` 에 한 줄이 빠졌다(기존 DB 조회 전부 500)"
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



# ==============================================================
# (R36 C-4) BytesIO 응답 빌더 — 바이트 해시가 기록되고, 라우터 6곳이 전부 넘긴다
# ==============================================================


class TestOutputHashKwargs:
    def test_bytesio_and_bytes_hash_same_and_keep_position(self):
        import io

        from workflow.quality.recorder import output_hash_kwargs, sha256_hex

        data = b"PK\x03\x04hello"
        buf = io.BytesIO(data)
        buf.seek(3)
        kw = output_hash_kwargs(buf)
        assert kw == {"output_sha256": sha256_hex(data), "output_size_bytes": len(data)}
        assert buf.tell() == 3, "getvalue 가 위치를 옮기면 뒤의 StreamingResponse 가 잘린다"
        assert output_hash_kwargs(data) == kw
        assert output_hash_kwargs(bytearray(data)) == kw
        assert output_hash_kwargs(memoryview(data)) == kw

    @pytest.mark.parametrize("bad", [None, "not-bytes", 42, object()])
    def test_non_bytes_says_no_bytes_not_no_path(self, bad, caplog):
        """(리뷰 W2) 실패를 `no_path` 로 접으면 '경로 없는 문서'(정상)와 '배선 끊김'(버그)이 한 토큰이 된다."""
        import logging

        from workflow.quality.recorder import output_hash_kwargs

        with caplog.at_level(logging.WARNING, logger="workflow.quality.recorder"):
            assert output_hash_kwargs(bad) == {"output_hash_reason": "no_bytes"}
        assert any("해시 미기록" in r.getMessage() for r in caplog.records), "침묵으로 빠졌다"

    def test_getvalue_failures_each_get_their_own_reason(self):
        from workflow.quality.recorder import output_hash_kwargs

        class _Boom:
            def getvalue(self):
                raise OSError("closed")

        class _Text:
            def getvalue(self):
                return "text"

        assert output_hash_kwargs(_Boom()) == {"output_hash_reason": "bytes_unreadable"}
        assert output_hash_kwargs(_Text()) == {"output_hash_reason": "bytes_not_bytes"}

    def test_empty_buffer_is_not_a_hash(self, caplog):
        """(리뷰 W3) 빈 입력의 sha256(`e3b0c442…`)은 유효해 보여서 **0바이트 산출물이 승인까지** 받을 수 있다."""
        import io
        import logging

        from workflow.quality.recorder import output_hash_kwargs

        with caplog.at_level(logging.WARNING, logger="workflow.quality.recorder"):
            assert output_hash_kwargs(io.BytesIO()) == {"output_hash_reason": "empty_bytes"}
            assert output_hash_kwargs(b"") == {"output_hash_reason": "empty_bytes"}
        assert any("0개" in r.getMessage() for r in caplog.records)

    def test_failure_reason_reaches_the_db_and_is_not_no_path(self, qdb):
        """사유가 DB(`meta.output_sha256_reason`)까지 가야 화면이 '배선 실패' 를 말할 수 있다."""
        from workflow.quality.recorder import output_hash_kwargs, record_run

        rid = record_run("swut", {"total_tcs": 3, "statement_pct": 1.0}, project_root="PRJ", db_path=qdb,
                         **output_hash_kwargs(None))
        conn = sqlite3.connect(qdb)
        try:
            sha, meta = conn.execute(
                "SELECT output_sha256, meta_json FROM generation_runs WHERE id=?", (rid,)).fetchone()
        finally:
            conn.close()
        assert sha is None
        assert json.loads(meta)["output_sha256_reason"] == "no_bytes"

    def test_path_based_runs_still_say_no_path(self, qdb):
        """경로도 바이트도 없는 진짜 `no_path` 는 그대로 — 사유를 뭉개서 고친 게 아니다."""
        from workflow.quality.recorder import record_run

        rid = record_run("swut", {"total_tcs": 3}, project_root="PRJ", db_path=qdb)
        conn = sqlite3.connect(qdb)
        try:
            meta = conn.execute("SELECT meta_json FROM generation_runs WHERE id=?", (rid,)).fetchone()[0]
        finally:
            conn.close()
        assert json.loads(meta)["output_sha256_reason"] == "no_path"

    def test_record_run_with_bytes_kwargs_stores_hash_and_size(self, qdb):
        import io

        from workflow.quality.recorder import output_hash_kwargs, record_run, sha256_hex

        data = b"x" * 1234
        rid = record_run("swut", {"total_tcs": 3, "statement_pct": 1.0}, project_root="PRJ", db_path=qdb, **output_hash_kwargs(io.BytesIO(data)))
        assert rid > 0
        conn = sqlite3.connect(qdb)
        try:
            sha, size, meta = conn.execute(
                "SELECT output_sha256, output_size_bytes, meta_json FROM generation_runs WHERE id=?", (rid,)
            ).fetchone()
        finally:
            conn.close()
        assert sha == sha256_hex(data) and size == 1234
        assert meta is None or json.loads(meta).get("output_sha256_reason") is None  # 사유 없음 = 해시 있음

    def test_rebuild_bytes_differ_is_recorded_as_different_runs(self, qdb):
        """같은 입력을 다시 만들면 바이트가 다르다(openpyxl 저장 시각) — 두 run 은 각자 해시를 갖는다."""
        import io
        import time

        from openpyxl import Workbook

        from workflow.quality.recorder import output_hash_kwargs, record_run

        def build():
            wb = Workbook()
            wb.active["A1"] = "x"
            b = io.BytesIO()
            wb.save(b)
            return b

        k1 = output_hash_kwargs(build())
        time.sleep(1.1)
        k2 = output_hash_kwargs(build())
        assert k1["output_sha256"] != k2["output_sha256"], "결정론이 생겼다 — 화면 문구(생성마다 다름)를 다시 볼 것"
        r1 = record_run("swut", {"total_tcs": 3, "statement_pct": 1.0}, project_root="PRJ", db_path=qdb, **k1)
        r2 = record_run("swut", {"total_tcs": 3, "statement_pct": 1.0}, project_root="PRJ", db_path=qdb, **k2)
        conn = sqlite3.connect(qdb)
        try:
            rows = conn.execute("SELECT id, output_sha256 FROM generation_runs WHERE id IN (?, ?)", (r1, r2)).fetchall()
        finally:
            conn.close()
        assert len({sha for _, sha in rows}) == 2


class TestBytesRoutersPassHash:
    """라우터의 기록 호출 **전부**가 바이트 해시를 넘긴다 — 하나가 빠지면 그 문서만 영구 검토 잠금이다."""

    ROUTERS = (
        "backend/routers/swut.py", "backend/routers/swit.py", "backend/routers/swsa.py", "backend/routers/swreport.py",
    )

    @staticmethod
    def _calls(tree, names):
        import ast

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
                if name in names:
                    yield node

    def test_every_record_call_passes_output_hash_kwargs(self):
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        missing = []
        total = 0
        for rel in self.ROUTERS:
            tree = ast.parse((root / rel).read_text(encoding="utf-8"))
            for call in self._calls(tree, {"record_run", "record_test_result_run"}):
                total += 1
                starred = [
                    kw for kw in call.keywords
                    if kw.arg is None and isinstance(kw.value, ast.Call)
                    and getattr(kw.value.func, "id", getattr(kw.value.func, "attr", "")) == "output_hash_kwargs"
                ]
                # (리뷰 W5b) `**output_hash_kwargs(None)` 은 항상 빈 인자다 — 배선된 척하는 죽은 호출.
                live = [
                    kw for kw in starred
                    if kw.value.args and not (
                        isinstance(kw.value.args[0], ast.Constant) and kw.value.args[0].value is None
                    )
                ]
                if not live:
                    missing.append(f"{rel}:{call.lineno}")
        assert total >= 6, f"기록 호출이 {total}개뿐 — 라우터 구조가 바뀌었으면 이 가드도 갱신"
        assert missing == [], f"바이트 해시를 안 넘기는 기록 호출: {missing}"

    def test_every_test_quality_caller_passes_output_io(self):
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        missing = []
        total = 0
        for rel in ("backend/routers/swut.py", "backend/routers/swit.py"):
            tree = ast.parse((root / rel).read_text(encoding="utf-8"))
            for call in self._calls(tree, {"_record_test_quality"}):
                total += 1
                if not any(kw.arg == "output_io" for kw in call.keywords):
                    missing.append(f"{rel}:{call.lineno}")
        assert total == 6, f"헬퍼 호출이 {total}개 — 셋씩 두 라우터여야 한다"
        assert missing == [], f"output_io 를 안 넘기는 호출: {missing}"

    @pytest.mark.parametrize("modname", ["swut", "swit"])
    def test_helper_forwards_hash_of_output_io(self, monkeypatch, modname):
        import importlib
        import io

        import workflow.quality.recorder as rec

        mod = importlib.import_module(f"backend.routers.{modname}")
        seen = {}

        def _fake(doc_type, summary, **kw):
            seen.update(kw)
            return 1

        monkeypatch.setattr(rec, "record_test_result_run", _fake)

        class _Req:
            project_id = "HDPDM01"
            release_sw_version = "1.02"
            scm_id = ""

        class _Meta:
            asil_level = "ASIL B"

        data = b"xlsm-bytes"
        mod._record_test_quality(_Req(), _Meta(), {"total": 1}, doc_type="sutr", output_io=io.BytesIO(data))
        assert seen["output_sha256"] == rec.sha256_hex(data) and seen["output_size_bytes"] == len(data)
        seen.clear()
        mod._record_test_quality(_Req(), _Meta(), {"total": 1}, doc_type="sutr")
        assert "output_sha256" not in seen, "버퍼 없이도 해시가 생겼다 — 무엇의 해시인가"


def test_swreport_route_records_response_bytes_hash(qdb, monkeypatch):
    """라우터 → recorder → DB 왕복: 응답으로 나가는 바로 그 바이트의 해시가 행에 남는다(swreport, 가장 단순한 BytesIO 라우터)."""
    import io

    from backend.routers import swreport as rt
    from backend.schemas import SwReportBuildRequest
    from workflow.quality.recorder import sha256_hex

    data = b"PK\x03\x04 summary bytes"

    class _Res:
        ok = True
        summary = {"performed_count": 3, "fail_count": 0, "overall_result": "Pass"}
        xlsm_io = io.BytesIO(data)
        filename = "sum.xlsm"
        warnings: list = []
        incomplete_rows: list = []

    monkeypatch.setattr(rt, "_resolve_template_bytes", lambda req: b"tpl")
    monkeypatch.setattr(rt, "_resolve_source_workbooks", lambda req, tpl: [])
    monkeypatch.setattr(rt, "build_summary_report", lambda tpl, sources, meta: _Res())
    req = SwReportBuildRequest(project_id="ES95411", scm_id="kjpds02", release_sw_version="1.0", test_date="2026-09-07")
    resp = rt._do_summary_build(req)
    assert resp.status_code == 200
    conn = sqlite3.connect(qdb)
    try:
        row = conn.execute(
            "SELECT doc_type, output_sha256, output_size_bytes FROM generation_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("swreport", sha256_hex(data), len(data))
    # (리뷰 W1) **응답으로 나가는 바이트**를 직접 잰다 — 주입한 fixture 와만 비교하면 응답 조립이
    # 한 바이트를 더해도 이 가드는 통과한다. 이 변경의 유일한 주장이 "응답 바이트의 해시" 다.
    assert hashlib.sha256(resp.body).hexdigest() == row[1], "기록 해시가 응답 본문의 해시가 아니다"
    assert len(resp.body) == row[2], "기록 크기가 응답 본문 길이와 다르다"



class TestSuiteNeverWritesUserQualityDb:
    """기록 경로 테스트가 **사용자 DB** 에 쓰면 화면의 추세·KPI·`superseded_by`·검토 대상이 오염된다.

    실측으로 이미 벌어진 일이다(2026-09-07: swut 1,338행 중 1,327행이 픽스처 서명). 격리는
    `tests/conftest.py::_isolate_quality_db`(세션 autouse)가 하고, 이 가드가 그 사실을 단언한다.
    """

    def test_default_db_path_is_not_the_repo_reports_db(self):
        from pathlib import Path

        import config
        from workflow.quality.db import _default_db_path

        live = (Path(config.__file__).resolve().parent / getattr(config, "DEFAULT_REPORT_DIR", "reports")
                / "quality.sqlite").resolve()
        assert _default_db_path().resolve() != live, (
            "테스트가 사용자 Quality DB 를 기본 경로로 쓴다 — conftest 의 세션 격리가 꺼졌다"
        )

    def test_a_router_build_lands_in_the_isolated_db(self, monkeypatch):
        """실 라우터 경로(swreport)가 기록을 남기되 그 행이 **격리 DB** 에만 생긴다."""
        import io
        import sqlite3
        from pathlib import Path

        import config
        from backend.routers import swreport as rt
        from backend.schemas import SwReportBuildRequest
        from workflow.quality.db import _default_db_path

        live = (Path(config.__file__).resolve().parent / getattr(config, "DEFAULT_REPORT_DIR", "reports")
                / "quality.sqlite")
        before = _row_count(live)

        class _Res:
            ok = True
            summary = {"performed_count": 2, "fail_count": 0, "overall_result": "Pass"}
            xlsm_io = io.BytesIO(b"PK\x03\x04 isolated")
            filename = "s.xlsm"
            warnings: list = []
            incomplete_rows: list = []

        monkeypatch.setattr(rt, "_resolve_template_bytes", lambda req: b"tpl")
        monkeypatch.setattr(rt, "_resolve_source_workbooks", lambda req, tpl: [])
        monkeypatch.setattr(rt, "build_summary_report", lambda tpl, sources, meta: _Res())
        rt._do_summary_build(SwReportBuildRequest(
            project_id="ES95411", release_sw_version="1.0", test_date="2026-09-07",
        ))
        assert _row_count(live) == before, "테스트가 사용자 DB 에 행을 남겼다"
        conn = sqlite3.connect(_default_db_path())
        try:
            assert conn.execute(
                "SELECT COUNT(*) FROM generation_runs WHERE doc_type='swreport'"
            ).fetchone()[0] >= 1, "격리 DB 에도 안 남았다 — 기록이 통째로 사라졌다"
        finally:
            conn.close()


def _row_count(db_path) -> int:
    """사용자 DB 행 수(없으면 -1). 읽기 전용으로만 연다."""
    import sqlite3
    from pathlib import Path

    if not Path(db_path).exists():
        return -1
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM generation_runs").fetchone()[0])
    except sqlite3.Error:
        return -1
    finally:
        conn.close()



# ==============================================================
# (R36 C-5) 저장소 전수 — 품질 기록은 **경로 아니면 바이트**로 산출물을 고정한다
# ==============================================================


class TestEveryRecordSiteFixesTheArtifact:
    """새 빌더가 생겨도 "무엇을 검토했는가" 를 못 고정하는 기록이 늘지 않게 한다.

    파일 목록을 손으로 들고 있으면 **새 라우터가 목록 밖에서 태어난다** — 이 저장소가 게이트 범위로
    반복해 당한 형태(`test_gate_reach.py` 의 `_EXEMPT = {}` 와 같은 이유). 그래서 트리 전체를 걷는다.

    통과 조건은 셋 중 하나다:
      - `output_path=` (파일을 쓰는 빌더 — R33)
      - `output_sha256=` 또는 `**output_hash_kwargs(...)` (BytesIO 빌더 — R36)
      - `**kwargs` 를 **자기 시그니처의 `**kwargs`** 로 넘기는 위임(=책임이 호출자에게 있다)
      - `**helper(...)` 로 인자를 만드는 경우, 그 helper 가 같은 모듈에서 `output_path`/`output_sha256` 를
        채우는 것이 보이면 통과(UDS 관문의 `_uds_record_kwargs`)
    """

    TREES = ("backend", "workflow", "generators", "report_gen", "tools", "prompts")
    SKIP = {".venv", "venv", "node_modules", "site-packages", "tests", "__pycache__"}
    NAMES = {"record_run", "record_test_result_run", "record_uds_run"}
    BYTES_ROUTERS = ("backend/routers/swut.py", "backend/routers/swit.py",
                     "backend/routers/swsa.py", "backend/routers/swreport.py")

    @staticmethod
    def _callee(node):
        import ast

        fn = node.func
        if isinstance(fn, ast.Name):
            return fn.id
        return fn.attr if isinstance(fn, ast.Attribute) else ""

    @classmethod
    def _calls_with_owner(cls, node, owner=None):
        """(Call, 감싸는 FunctionDef) — 중첩 함수도 가장 가까운 것으로."""
        import ast

        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Call) and cls._callee(child) in cls.NAMES:
                yield child, owner
            nxt = child if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else owner
            yield from cls._calls_with_owner(child, nxt)

    @staticmethod
    def _helper_fixes_artifact(tree, name: str) -> bool:
        """같은 모듈의 `name` 함수가 `output_path`/`output_sha256` 를 채우는가(문자열 키·kwarg 둘 다)."""
        import ast

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and sub.value in ("output_path", "output_sha256"):
                        return True
                    if isinstance(sub, ast.keyword) and sub.arg in ("output_path", "output_sha256"):
                        return True
        return False

    def _scan(self):
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        rows = []
        for tree_name in self.TREES:
            base = root / tree_name
            if not base.exists():
                continue
            for path in base.rglob("*.py"):
                if any(part in self.SKIP for part in path.parts):
                    continue
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"))
                except SyntaxError:                       # 문법 오류는 syntax 게이트가 잡는다
                    continue
                rel = str(path.relative_to(root)).replace("\\", "/")
                for call, owner in self._calls_with_owner(tree):
                    kws = {kw.arg for kw in call.keywords if kw.arg}
                    stars = [kw.value for kw in call.keywords if kw.arg is None]
                    how = None
                    if "output_path" in kws:
                        how = "path"
                    elif "output_sha256" in kws:
                        how = "bytes"
                    for star in stars:
                        if how:
                            break
                        if isinstance(star, ast.Call):
                            name = self._callee(star)
                            if name == "output_hash_kwargs":
                                how = "bytes"
                            elif self._helper_fixes_artifact(tree, name):
                                how = "helper"
                        elif isinstance(star, ast.Name) and owner is not None:
                            kwarg = owner.args.kwarg
                            if kwarg is not None and kwarg.arg == star.id:
                                how = "passthru"
                    rows.append((rel, call.lineno, self._callee(call), how))
        return rows

    def test_no_record_site_leaves_the_artifact_unfixed(self):
        rows = self._scan()
        assert len(rows) >= 10, f"기록 호출을 {len(rows)}개밖에 못 찾았다 — 스캔이 헛돌고 있다(가드 무효)"
        unfixed = [f"{r}:{ln} {fn}()" for r, ln, fn, how in rows if how is None]
        assert unfixed == [], (
            "산출물을 고정하지 않는 품질 기록이 있다 — 그 run 은 영원히 '검토 잠금' 이다. "
            f"`output_path=` 또는 `**output_hash_kwargs(버퍼)` 를 넘길 것: {unfixed}"
        )

    def test_bytes_routers_are_actually_covered_by_the_scan(self):
        """스캔이 파일을 못 찾아도 위 테스트는 통과한다 — 네 라우터가 실제로 걸리는지 따로 못 박는다."""
        rows = self._scan()
        for rel in self.BYTES_ROUTERS:
            hits = [r for r in rows if r[0] == rel and r[3] == "bytes"]
            assert hits, f"{rel} 에서 바이트 해시로 고정한 기록 호출을 못 찾았다"

    def test_uds_gateway_is_fixed_through_its_kwargs_helper(self):
        """UDS 는 관문이 dict 를 만들어 넘긴다 — 그 형태도 '고정됨' 으로 읽혀야 한다(아니면 가드가 거짓 실패)."""
        rows = self._scan()
        uds = [r for r in rows if r[0] == "backend/helpers/uds.py"]
        assert uds and all(r[3] in ("helper", "path", "bytes") for r in uds), uds


    def test_recorder_names_are_never_alias_imported(self):
        """(리뷰 W5a) `import record_run as _rec` 로 부르면 이름 기반 가드가 통째로 눈을 감는다."""
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        offenders = []
        for tree_name in TestEveryRecordSiteFixesTheArtifact.TREES:
            base = root / tree_name
            if not base.exists():
                continue
            for path in base.rglob("*.py"):
                if any(part in TestEveryRecordSiteFixesTheArtifact.SKIP for part in path.parts):
                    continue
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"))
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.Import, ast.ImportFrom)):
                        continue
                    for alias in node.names:
                        if alias.name in TestEveryRecordSiteFixesTheArtifact.NAMES and alias.asname:
                            offenders.append(
                                f"{str(path.relative_to(root))}:{node.lineno} {alias.name} as {alias.asname}")
        assert offenders == [], f"기록 함수를 별칭으로 부르면 전수 가드가 놓친다: {offenders}"

    def test_star_argument_is_not_a_dead_none(self):
        """(리뷰 W5b) 전수 가드도 `output_hash_kwargs(None)` 을 '고정됨' 으로 세지 않는다."""
        import ast

        rows = self._scan()
        dead = []
        for rel, lineno, _fn, how in rows:
            if how != "bytes":
                continue
            src = (pathlib.Path(__file__).resolve().parents[2] / rel).read_text(encoding="utf-8")
            tree = ast.parse(src)
            for call, _owner in self._calls_with_owner(tree):
                if call.lineno != lineno:
                    continue
                for kw in call.keywords:
                    if kw.arg is not None or not isinstance(kw.value, ast.Call):
                        continue
                    if self._callee(kw.value) != "output_hash_kwargs":
                        continue
                    args = kw.value.args
                    if not args or (isinstance(args[0], ast.Constant) and args[0].value is None):
                        dead.append(f"{rel}:{lineno}")
        assert dead == [], f"항상 빈 dict 를 만드는 죽은 배선: {dead}"
