"""Database engine and session factory for RAG KB."""
from __future__ import annotations

import logging
import os
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from workflow.rag.models import Base

_logger = logging.getLogger("workflow.rag.db")

# 모듈 레벨 싱글톤
_engine = None
_SessionLocal = None
_lock = threading.Lock()


def _get_storage_mode() -> str:
    """현재 storage 모드 반환."""
    import config
    force_pg = bool(getattr(config, "FORCE_PGVECTOR", False))
    storage = str(getattr(config, "KB_STORAGE", "sqlite") or "sqlite").strip().lower()
    if force_pg:
        storage = "pgvector"
    return storage


def _get_pg_dsn() -> str:
    """PostgreSQL DSN 반환."""
    import config
    return (
        str(getattr(config, "PGVECTOR_DSN", "") or "").strip()
        or str(getattr(config, "PGVECTOR_URL", "") or "").strip()
        or os.environ.get("PGVECTOR_DSN", "").strip()
        or os.environ.get("PGVECTOR_URL", "").strip()
    )


def _mask_dsn(dsn: str) -> str:
    """DSN에서 비밀번호를 마스킹."""
    return re.sub(r":([^:@]+)@", ":***@", dsn)


def get_engine(db_path: Optional[Path] = None, *, force_new: bool = False):
    """SQLAlchemy 엔진 반환 (싱글톤, thread-safe)."""
    global _engine
    if _engine is not None and not force_new:
        return _engine

    with _lock:
        if _engine is not None and not force_new:
            return _engine

        storage = _get_storage_mode()

        if storage == "pgvector":
            dsn = _get_pg_dsn()
            if dsn:
                _engine = create_engine(
                    dsn,
                    pool_size=5,
                    max_overflow=10,
                    pool_pre_ping=True,
                    echo=False,
                )
                _logger.info("Using PostgreSQL engine: %s", _mask_dsn(dsn))
            else:
                _logger.warning("pgvector selected but no DSN configured, falling back to SQLite")
                storage = "sqlite"

        if storage == "sqlite":
            if db_path is None:
                db_path = Path("kb_index.sqlite")
            url = f"sqlite:///{db_path}"
            _engine = create_engine(url, echo=False)

            # WAL 모드 활성화
            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragma(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()

            _logger.info("Using SQLite engine: %s", db_path)

        return _engine


def get_session_factory(db_path: Optional[Path] = None):
    """SessionLocal 팩토리 반환."""
    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine(db_path)
        _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return _SessionLocal


def init_db(db_path: Optional[Path] = None) -> None:
    """테이블 생성 (없으면 CREATE)."""
    engine = get_engine(db_path)
    storage = _get_storage_mode()
    if storage == "pgvector":
        from sqlalchemy import text
        with engine.connect() as conn:
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
            except Exception:
                pass
    Base.metadata.create_all(engine, checkfirst=True)
    _logger.info("Database tables initialized")


@contextmanager
def get_session(db_path: Optional[Path] = None) -> Generator[Session, None, None]:
    """세션 컨텍스트 매니저."""
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
    """테스트용: 엔진/세션 초기화."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
