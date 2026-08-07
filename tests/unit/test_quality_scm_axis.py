"""품질 이력의 **프로젝트 축**(`scm_id`) — 스키마 마이그레이션과 delta 스코프.

## 왜 이 테스트가 있나 (실측 2026-08-07)

### 1. Alembic 이 없다 — 컬럼 추가가 곧 장애다

이 저장소엔 `alembic.ini` 도 `ALTER TABLE` 도 0건이고, `init_db()` 는
`create_all(checkfirst=True)` 뿐이다. 그건 **없는 테이블을 만들 뿐 기존 테이블에
컬럼을 더하지 않는다**. 즉 모델에 필드를 추가하면 그 순간부터 기존
`reports/quality.sqlite`(실측 964행)를 읽는 모든 쿼리가

    sqlite3.OperationalError: no such column: generation_runs.scm_id

로 죽는다 — `/api/quality/*` 전체가 500 이 된다. `_apply_column_additions()` 가
그 다리이고, 아래 테스트는 **구 스키마 DB 를 실제로 만들어** 다리가 놓이는지 본다.
모델만 보고 통과하는 테스트는 이 결함을 못 잡는다(모델엔 이미 컬럼이 있으니까).

### 2. delta 가 다른 프로젝트와의 차이였다

`score_delta` 의 prev_run 조회가 `doc_type` 만 봤다. 실측 964행은
HDPDM01(swut 625) 과 KJPDS02(swreport 317, swit 12, swut 4) 가 시간순으로 섞여
있어서, HDPDM01 run 의 `↑ +12.4` 가 **바로 앞에 기록된 KJPDS02 run 대비**일 수
있었다. 화면은 그걸 "이 프로젝트가 좋아졌다" 로 읽는다.

### 3. FAIL 은 남는데 사유가 안 남았다

`compute_gate_verdict` 의 `reason` 이 로그 한 줄에 쓰이고 버려졌다. DB 에는
`gated_metric_count=0` 이라는 간접 흔적만 있어서, 화면이 "왜 판정 불가인지" 를
말할 근거가 없었다.
"""
from __future__ import annotations

import pathlib
import sqlite3
import tempfile

import pytest

# 실제 운영 DB 의 **마이그레이션 이전** 스키마(2026-08-07 `PRAGMA table_info` 실측).
# 새 모델로 CREATE 하면 컬럼이 이미 있어 마이그레이션을 통과시켜도 통과하므로,
# 여기서는 raw DDL 로 옛 모양을 정확히 재현한다.
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
def qdb():
    return pathlib.Path(tempfile.mkdtemp()) / "q.db"


@pytest.fixture
def legacy_db(qdb):
    """마이그레이션 이전 스키마 + 기존 행 1개를 담은 DB."""
    conn = sqlite3.connect(qdb)
    conn.executescript(_LEGACY_DDL)
    conn.execute(
        "INSERT INTO generation_runs (run_uuid, doc_type, project_root, status)"
        " VALUES ('legacy-uuid-1', 'swut', 'HDPDM01', 'success')"
    )
    conn.commit()
    conn.close()
    return qdb


def _columns(db_path) -> set:
    conn = sqlite3.connect(db_path)
    try:
        return {str(r[1]) for r in conn.execute("PRAGMA table_info(generation_runs)")}
    finally:
        conn.close()


def _sits(pct: float) -> dict:
    """SITS quality_report — 점수만 다르게 만드는 최소 payload.

    `total_test_cases>0` 이어야 `record_run` 의 빈 산출물 skip 을 통과한다.
    """
    return {
        "requirement_traceability_pct": pct,
        "io_coverage_pct": pct,
        "total_test_cases": 5,
    }


# ==============================================================
# 1. 스키마 마이그레이션
# ==============================================================

class TestColumnMigration:

    def test_legacy_db_gains_the_column(self, legacy_db):
        """구 스키마 DB 에 컬럼이 실제로 생긴다."""
        from workflow.quality.db import init_db

        assert "scm_id" not in _columns(legacy_db), "픽스처가 구 스키마가 아니다"
        init_db(legacy_db)
        assert "scm_id" in _columns(legacy_db)

    def test_existing_rows_survive_and_read_as_null(self, legacy_db):
        """행이 유실되지 않고, 기존 행의 scm_id 는 NULL(=미상)이다.

        NULL 을 빈 문자열이나 임의 기본값으로 채우면 "미상" 과 "무소속" 이 섞인다.
        """
        from workflow.quality.db import get_session, init_db
        from workflow.quality.models import GenerationRun

        init_db(legacy_db)
        with get_session(legacy_db) as s:
            rows = s.query(GenerationRun).all()
            assert len(rows) == 1
            assert rows[0].run_uuid == "legacy-uuid-1"
            assert rows[0].project_root == "HDPDM01"  # 원본 증거 보존
            assert rows[0].scm_id is None

    def test_index_is_created(self, legacy_db):
        from workflow.quality.db import init_db

        init_db(legacy_db)
        conn = sqlite3.connect(legacy_db)
        try:
            names = {
                r[0] for r in conn.execute(
                    "select name from sqlite_master where type='index'"
                    " and tbl_name='generation_runs'"
                )
            }
        finally:
            conn.close()
        assert "ix_gen_run_scm" in names

    def test_running_twice_is_safe(self, legacy_db):
        """idempotent — 두 번째 호출이 'duplicate column' 로 터지지 않는다.

        `init_db()` 는 API 요청마다 불리므로 재진입 안전성이 곧 가용성이다.
        """
        from workflow.quality.db import init_db

        init_db(legacy_db)
        init_db(legacy_db)  # 여기서 OperationalError 가 나면 실패
        assert "scm_id" in _columns(legacy_db)

    def test_query_after_migration_does_not_raise(self, legacy_db):
        """마이그레이션의 존재 이유 자체 — 조회가 살아 있는가.

        컬럼이 없으면 `no such column` 으로 죽는 그 경로를 그대로 태운다.
        """
        from workflow.quality.db import get_session, init_db
        from workflow.quality.models import GenerationRun

        init_db(legacy_db)
        with get_session(legacy_db) as s:
            got = s.query(GenerationRun).filter(GenerationRun.scm_id == "hdpdm01").all()
        assert got == []


# ==============================================================
# 2. scm_id 기록
# ==============================================================

class TestScmIdRecording:

    def test_scm_id_is_persisted(self, qdb):
        from workflow.quality.db import get_session
        from workflow.quality.models import GenerationRun
        from workflow.quality.recorder import record_run

        rid = record_run("sits", _sits(80.0), scm_id="kjpds02_pv", db_path=qdb)
        assert rid > 0
        with get_session(qdb) as s:
            run = s.query(GenerationRun).filter_by(id=rid).one()
            assert run.scm_id == "kjpds02_pv"

    def test_omitting_scm_id_stays_null(self, qdb):
        """미전달은 기존 동작 그대로 — 임의 값으로 채우지 않는다."""
        from workflow.quality.db import get_session
        from workflow.quality.models import GenerationRun
        from workflow.quality.recorder import record_run

        rid = record_run("sits", _sits(80.0), db_path=qdb)
        with get_session(qdb) as s:
            assert s.query(GenerationRun).filter_by(id=rid).one().scm_id is None


# ==============================================================
# 3. score_delta 프로젝트 스코프
# ==============================================================

class TestDeltaScope:

    def test_same_project_gets_a_delta(self, qdb):
        """대조군 — 같은 프로젝트끼리는 delta 가 계산되어야 한다.

        이 테스트가 없으면 "delta 를 아예 끄는" 뮤테이션이 살아남는다.
        """
        from workflow.quality.db import get_session
        from workflow.quality.models import QualitySummary
        from workflow.quality.recorder import record_run

        first = record_run("sits", _sits(70.0), scm_id="kjpds02", db_path=qdb)
        second = record_run("sits", _sits(90.0), scm_id="kjpds02", db_path=qdb)

        with get_session(qdb) as s:
            summ = s.query(QualitySummary).filter_by(run_id=second).one()
            assert summ.prev_run_id == first
            assert summ.score_delta is not None
            assert summ.score_delta > 0  # 70 → 90 이므로 상승

    def test_different_project_is_not_compared(self, qdb):
        """다른 프로젝트의 run 을 prev 로 집지 않는다 (핵심 회귀)."""
        from workflow.quality.db import get_session
        from workflow.quality.models import QualitySummary
        from workflow.quality.recorder import record_run

        record_run("sits", _sits(70.0), scm_id="hdpdm01", db_path=qdb)
        second = record_run("sits", _sits(90.0), scm_id="kjpds02", db_path=qdb)

        with get_session(qdb) as s:
            summ = s.query(QualitySummary).filter_by(run_id=second).one()
            assert summ.prev_run_id is None
            assert summ.score_delta is None

    def test_null_scm_id_keeps_legacy_behaviour(self, qdb):
        """scm_id 미상인 run 은 예전대로 doc_type 만 보고 잇는다.

        과거 964행이 전부 NULL 이라, 여기서 끊으면 기존 추세가 통째로 사라진다.
        """
        from workflow.quality.db import get_session
        from workflow.quality.models import QualitySummary
        from workflow.quality.recorder import record_run

        first = record_run("sits", _sits(70.0), db_path=qdb)
        second = record_run("sits", _sits(90.0), db_path=qdb)

        with get_session(qdb) as s:
            summ = s.query(QualitySummary).filter_by(run_id=second).one()
            assert summ.prev_run_id == first


# ==============================================================
# 4. 게이트 사유 영속
# ==============================================================

class TestGateReasonPersisted:

    def test_no_gated_metric_reason_is_recorded(self, qdb):
        """검사 0건 → 사유가 DB 에 남아 화면이 '왜' 를 말할 수 있다."""
        from workflow.quality.db import get_session
        from workflow.quality.models import QualityScore
        from workflow.quality.recorder import record_run

        # 알 수 없는 doc_type → metrics=[] → verdict.reason='no_gated_metric'
        rid = record_run("bogus_type", {"x": 1}, db_path=qdb)
        with get_session(qdb) as s:
            names = {
                r.metric_name for r in s.query(QualityScore).filter_by(run_id=rid).all()
            }
        assert "gate_reason:no_gated_metric" in names

    def test_reason_row_is_ungated_so_it_cannot_change_the_verdict(self, qdb):
        """사유 행은 **비게이트**여야 한다 — 판정에 끼면 그 자체가 결함."""
        from workflow.quality.db import get_session
        from workflow.quality.models import QualityScore
        from workflow.quality.recorder import record_run

        rid = record_run("bogus_type", {"x": 1}, db_path=qdb)
        with get_session(qdb) as s:
            row = (
                s.query(QualityScore)
                .filter_by(run_id=rid, metric_name="gate_reason:no_gated_metric")
                .one()
            )
        assert row.gate_pass is None
        assert row.threshold is None

    def test_normal_run_has_no_reason_row(self, qdb):
        """음성 대조군 — 사유가 없을 땐 행을 만들지 않는다.

        빈 사유 행을 남기면 소비처가 '사유 있음/없음' 을 구분하지 못한다.
        """
        from workflow.quality.db import get_session
        from workflow.quality.models import QualityScore
        from workflow.quality.recorder import record_run

        rid = record_run("sits", _sits(90.0), db_path=qdb)
        with get_session(qdb) as s:
            names = [
                r.metric_name for r in s.query(QualityScore).filter_by(run_id=rid).all()
            ]
        assert not [n for n in names if n.startswith("gate_reason:")]
