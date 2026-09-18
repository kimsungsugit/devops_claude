"""Database engine and session factory for Chat History DB (chat_history.sqlite)."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.services.chat_history_models import ChatHistoryBase

_logger = logging.getLogger("backend.chat_history.db")

# 경로별 엔진/세션팩토리 캐시 (db_path 별 1개씩 — 동일 경로면 재사용).
# ⚠ (R41 N11) 과거엔 `_engine` **전역 하나**였다. 첫 `get_engine()` 이 경로를 고정하면
#   이후 `db_path` 인자가 **무시**돼, 테스트가 임시 DB 를 주어도 실제로는 그때 잡힌 경로에
#   쓴다 — 한 번이라도 라이브 경로로 열리면 그 워커의 이후 전 테스트가 **사용자 채팅 DB**
#   에 기록하고, 경로별 캐시가 없으니 회복 지점도 없다.
#   `workflow/quality/db.py` 가 **같은 결함을 이미 고쳤다**(그 주석: "단일 _engine 싱글톤이라
#   첫 init 후 db_path 인자가 무시돼 테스트 격리가 깨졌다") — 여기만 옛 형태로 남아 있었다.
_engines: dict = {}
_session_factories: dict = {}
# RLock 필수: get_session_factory 가 _lock 을 쥔 채 get_engine 을 부르고(재귀 acquire),
# get_engine 의 fast-path 는 _engine 이 아직 None 인 **첫 호출**에선 안 타므로
# 일반 Lock 이면 같은 스레드가 자기 락에 막혀 **영구 데드락**이 된다.
# (workflow/quality/db.py 가 같은 이유로 이미 RLock 을 쓴다 — 그 주석 참조)
_lock = threading.RLock()
_CHAT_HISTORY_DB_FILENAME = "chat_history.sqlite"


def _default_db_path() -> Path:
    """레포 루트 기준 절대경로로 anchor.

    DEFAULT_REPORT_DIR 가 상대경로면 CWD(backend vs 루트)에 따라 다른 파일을
    읽고 쓰는 split-brain 이 발생하므로 config.py 위치(레포 루트)에 고정한다.
    """
    try:
        import config
        report_dir = getattr(config, "DEFAULT_REPORT_DIR", "reports")
        base = Path(report_dir)
        if not base.is_absolute():
            repo_root = Path(config.__file__).resolve().parent
            base = repo_root / base
        return base / _CHAT_HISTORY_DB_FILENAME
    except Exception:
        return (Path("reports").resolve()) / _CHAT_HISTORY_DB_FILENAME


def _resolve_key(db_path: "Optional[Path]") -> str:
    """db_path → 캐시 키 (None 이면 기본 경로). 정본 `workflow/quality/db.py::_resolve_key` 와 같은 형태."""
    return str(Path(db_path) if db_path is not None else _default_db_path())


def get_engine(db_path: Optional[Path] = None, *, force_new: bool = False):
    """SQLAlchemy 엔진 반환 (db_path 별 캐시, thread-safe)."""
    key = _resolve_key(db_path)
    with _lock:
        if not force_new and key in _engines:
            return _engines[key]

        db_path = Path(key)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        url = f"sqlite:///{db_path}"
        # D10: sync endpoint + 백그라운드 저장 스레드 동시 접근 허용
        engine = create_engine(url, echo=False, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA wal_autocheckpoint=200")  # D10: WAL 무제한 증가 방지
            cursor.execute("PRAGMA busy_timeout=5000")  # R2: 멀티워커 동시 write lock 경합 시 대기
            cursor.close()

        _logger.info("Chat History DB engine: %s", db_path)
        _engines[key] = engine
        # force_new 로 엔진을 갈면 기존 세션팩토리도 무효화(정본과 같은 규약).
        _session_factories.pop(key, None)
        return engine


def get_session_factory(db_path: Optional[Path] = None):
    """SessionLocal 팩토리 반환 (db_path 별 캐시).

    RLock 재귀 안전 — `get_engine` 을 락 안에서 부른다(모듈 상단 `_lock` 주석 참조).
    """
    key = _resolve_key(db_path)
    with _lock:
        if key not in _session_factories:
            engine = get_engine(db_path)
            _session_factories[key] = sessionmaker(bind=engine, expire_on_commit=False)
        return _session_factories[key]


def _migrate_schema(engine) -> None:
    """기존 chat_conversations 테이블에 owner 컬럼/인덱스 보강 (idempotent).

    create_all 은 기존 테이블에 컬럼을 추가하지 않으므로, 구버전 DB(owner 없음)에
    대해 ALTER TABLE 로 마이그레이션한다. 신규 DB는 create_all 이 이미 생성하므로 no-op.
    """
    try:
        with engine.begin() as conn:
            cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(chat_conversations)")}
            if cols and "owner" not in cols:
                conn.exec_driver_sql("ALTER TABLE chat_conversations ADD COLUMN owner VARCHAR(120)")
                conn.exec_driver_sql(
                    "CREATE INDEX IF NOT EXISTS ix_chat_conversations_owner ON chat_conversations(owner)"
                )
                _logger.info("Chat History DB migrated: added owner column")
    except Exception:
        _logger.warning("Chat History DB owner migration failed", exc_info=True)


def init_db(db_path: Optional[Path] = None) -> None:
    engine = get_engine(db_path)
    ChatHistoryBase.metadata.create_all(engine, checkfirst=True)
    _migrate_schema(engine)
    _logger.info("Chat History DB tables initialized")


@contextmanager
def get_session(db_path: Optional[Path] = None) -> Generator[Session, None, None]:
    factory = get_session_factory(db_path)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """캐시된 엔진을 **전부** 정리한다(테스트 teardown·경로 전환).

    ⚠ 경로별 캐시가 되면서 지울 대상이 여러 개다 — 하나만 지우면 다른 경로의 엔진이
      살아남아 다음 테스트가 그 경로를 계속 쓴다.
    """
    with _lock:
        for engine in list(_engines.values()):
            try:
                engine.dispose()
            except Exception:  # noqa: BLE001 — dispose 실패가 정리를 막지 않는다
                _logger.warning("Chat History DB engine dispose 실패", exc_info=True)
        _engines.clear()
        _session_factories.clear()
