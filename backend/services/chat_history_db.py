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

_engine = None
_SessionLocal = None
_lock = threading.Lock()
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


def get_engine(db_path: Optional[Path] = None, *, force_new: bool = False):
    global _engine
    if _engine is not None and not force_new:
        return _engine

    with _lock:
        if _engine is not None and not force_new:
            return _engine

        if db_path is None:
            db_path = _default_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        url = f"sqlite:///{db_path}"
        # D10: sync endpoint + 백그라운드 저장 스레드 동시 접근 허용
        _engine = create_engine(url, echo=False, connect_args={"check_same_thread": False})

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA wal_autocheckpoint=200")  # D10: WAL 무제한 증가 방지
            cursor.execute("PRAGMA busy_timeout=5000")  # R2: 멀티워커 동시 write lock 경합 시 대기
            cursor.close()

        _logger.info("Chat History DB engine: %s", db_path)
        return _engine


def get_session_factory(db_path: Optional[Path] = None):
    global _SessionLocal
    if _SessionLocal is not None:
        return _SessionLocal
    with _lock:  # W3: double-checked locking (reset_engine 직후 동시호출 시 stale factory 방지)
        if _SessionLocal is None:
            engine = get_engine(db_path)
            _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return _SessionLocal


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
    global _engine, _SessionLocal
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _SessionLocal = None
