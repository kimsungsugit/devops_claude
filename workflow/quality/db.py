"""Database engine and session factory for Quality DB (quality.sqlite)."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from workflow.quality.models import QualityBase

_logger = logging.getLogger("workflow.quality.db")

# 경로별 엔진/세션팩토리 캐시 (db_path 별 1개씩 — 동일 경로면 재사용).
# 과거: 단일 _engine 싱글톤이라 첫 init 후 db_path 인자가 무시돼 테스트 격리가
# 깨졌다(record_run(db_path=tmp)이 실제론 기본 DB에 기록). 경로별 dict 로 해소.
# RLock: get_session_factory → get_engine 재귀 호출이 같은 스레드에서 안전하도록.
_engines: dict = {}
_session_factories: dict = {}
_lock = threading.RLock()
_QUALITY_DB_FILENAME = "quality.sqlite"


def _resolve_key(db_path: "Optional[Path]") -> str:
    """db_path → 캐시 키 (None이면 기본 경로)."""
    return str(Path(db_path) if db_path is not None else _default_db_path())


def _default_db_path() -> Path:
    """기본 Quality DB 경로 반환.

    상대 경로인 DEFAULT_REPORT_DIR은 **CWD가 아니라 프로젝트 루트(config.py 위치)**
    기준으로 anchor한다. 과거에는 CWD 의존이라 backend 기동(CWD=backend) 시
    backend/reports/quality.sqlite 를, 루트 실행(generators record_run) 시
    reports/quality.sqlite 를 써서 read/write DB가 갈라져 대시보드가 빈 DB를
    읽는 문제가 있었다.
    """
    try:
        import config
        report_dir = Path(getattr(config, "DEFAULT_REPORT_DIR", "reports"))
        if not report_dir.is_absolute():
            repo_root = Path(config.__file__).resolve().parent
            report_dir = repo_root / report_dir
        return report_dir / _QUALITY_DB_FILENAME
    except Exception:
        return Path("reports") / _QUALITY_DB_FILENAME


def get_engine(db_path: Optional[Path] = None, *, force_new: bool = False):
    """SQLAlchemy 엔진 반환 (db_path 별 캐시, thread-safe)."""
    key = _resolve_key(db_path)
    with _lock:
        if not force_new and key in _engines:
            return _engines[key]

        path = Path(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        url = f"sqlite:///{path}"
        engine = create_engine(url, echo=False)

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        _engines[key] = engine
        # force_new 로 엔진을 갈면 기존 세션팩토리도 무효화.
        _session_factories.pop(key, None)
        _logger.info("Quality DB engine: %s", path)
        return engine


def get_session_factory(db_path: Optional[Path] = None):
    """SessionLocal 팩토리 반환 (db_path 별 캐시)."""
    key = _resolve_key(db_path)
    with _lock:
        if key not in _session_factories:
            engine = get_engine(db_path)  # RLock 재귀 안전
            _session_factories[key] = sessionmaker(bind=engine, expire_on_commit=False)
        return _session_factories[key]


def init_db(db_path: Optional[Path] = None) -> None:
    """테이블 생성 (없으면 CREATE)."""
    engine = get_engine(db_path)
    QualityBase.metadata.create_all(engine, checkfirst=True)
    _logger.info("Quality DB tables initialized")


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
    """테스트용: 전 경로 엔진/세션 초기화."""
    with _lock:
        for engine in _engines.values():
            try:
                engine.dispose()
            except Exception:
                pass
        _engines.clear()
        _session_factories.clear()
