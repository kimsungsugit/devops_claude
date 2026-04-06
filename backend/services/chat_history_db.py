"""Database engine and session factory for Chat History DB (chat_history.sqlite)."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.services.chat_history_models import ChatHistoryBase

_logger = logging.getLogger("backend.chat_history.db")

_engine = None
_SessionLocal = None
_lock = threading.Lock()
_CHAT_HISTORY_DB_FILENAME = "chat_history.sqlite"


def _default_db_path() -> Path:
    try:
        import config
        report_dir = getattr(config, "DEFAULT_REPORT_DIR", "reports")
        return Path(report_dir) / _CHAT_HISTORY_DB_FILENAME
    except Exception:
        return Path("reports") / _CHAT_HISTORY_DB_FILENAME


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
        _engine = create_engine(url, echo=False)

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        _logger.info("Chat History DB engine: %s", db_path)
        return _engine


def get_session_factory(db_path: Optional[Path] = None):
    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine(db_path)
        _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return _SessionLocal


def init_db(db_path: Optional[Path] = None) -> None:
    engine = get_engine(db_path)
    ChatHistoryBase.metadata.create_all(engine, checkfirst=True)
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
