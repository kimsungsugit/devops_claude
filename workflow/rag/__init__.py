# workflow/rag/__init__.py
# -*- coding: utf-8 -*-
# RAG Knowledge Base (v30.4: directory-backed, atomic writes)
# Package entry point - maintains backward compatibility with workflow.rag imports

from __future__ import annotations

import itertools
import json
import logging
import os
import re
import sqlite3
import threading
import time as _time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

# -- re-export chunker functions (backward compat) --
from workflow.rag.chunker import (
    REQ_ID_PATTERN,
    _chunk_by_req_ids,
    _chunk_c_by_function,
    _chunk_docx_by_heading,
    _chunk_source_file,
    _chunk_text,
    _chunk_xlsx_rows,
    _extract_req_ids_from_text,
    _read_and_chunk_file,
    _read_text_from_file,
)

# -- re-export ingestor functions (backward compat) --
from workflow.rag.ingestor import (
    _collect_files_from_paths,
    _infer_vectorcast_tags,
    _split_paths,
    ingest_external_sources,
    ingest_runtime_summary,
    ingest_uds_reference,
)

# 위 두 블록은 **하위 호환 재수출**이다(chunker/ingestor 로 분리하기 전 경로를 쓰는 코드용).
# `__all__` 로 그 의도를 명시하지 않으면 F401 "imported but unused" 로 잡힌다 — 실제로는
# 지우면 안 되는 공개 표면이라 '미사용'이 아니라 '여기서만 안 쓰는 것'이다.
# ⚠ 이 모듈을 `import *` 하는 곳은 없고(속성 접근만), 따라서 `__all__` 추가는 런타임 무영향.
__all__ = [
    "REQ_ID_PATTERN",
    "_chunk_by_req_ids",
    "_chunk_c_by_function",
    "_chunk_docx_by_heading",
    "_chunk_source_file",
    "_chunk_text",
    "_chunk_xlsx_rows",
    "_collect_files_from_paths",
    "_extract_req_ids_from_text",
    "_infer_vectorcast_tags",
    "_read_and_chunk_file",
    "_read_text_from_file",
    "_split_paths",
    "ingest_external_sources",
    "ingest_runtime_summary",
    "ingest_uds_reference",
]

_rag_logger = logging.getLogger("workflow.rag")
_RAG_PERF_LOG = str(os.environ.get("DEVOPS_RAG_PERF_LOG", "0")).strip().lower() in ("1", "true", "yes")

try:  # optional HTTP embedder
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore

try:
    import psycopg2  # type: ignore
except Exception:  # pragma: no cover
    psycopg2 = None  # type: ignore

import config


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _normalize_message(msg: str) -> str:
    msg = msg or ""
    # 컴파일 로그 등의 노이즈 제거
    msg = re.sub(r"/app/[^\s]+", "<PATH>", msg)
    msg = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z", "<TIME>", msg)
    msg = re.sub(r"\s+", " ", msg)
    return msg.strip()


# 프로세스 전역 원자 id 카운터: 동시 learn 이 같은 us 타임스탬프로 id 충돌하면
# source_file({id}.json)·DB row 가 덮어써져 엔트리가 유실된다. next() 는 GIL atomic.
_ID_COUNTER = itertools.count()


class KnowledgeBase:
    """
    디렉터리 기반 RAG 저장소

    - base_dir/ 아래에 여러 개의 JSON 엔트리 파일 생성
      예) kb_store/kb_20251203T075959123456Z.json
    - 각 파일에는 단일 dict 엔트리 저장
    - 저장 시 항상 tmp 파일에 먼저 쓰고 rename 으로 교체
    """

    def __init__(self, base_dir: Path):
        # 캐시 key(get_kb 의 normcase(resolve)) 와 self.base_dir 가 동일 디렉터리를
        # 가리키도록 방어적으로 정규화 — 상대/절대/드라이브 대소문자 혼재 분열 방지.
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.data: List[Dict[str, Any]] = []
        # 동시성 가드(get_kb 프로세스 캐시로 인스턴스가 스레드 간 공유되는 케이스):
        # self.data 의 구조변경(append/재바인드)과 엔트리 다중키 in-place 변이만 보호한다.
        # 임베딩/네트워크/DB I/O 는 이 락 밖에서 수행해 임계구역을 짧게 유지.
        # CPython GIL 전제(단일 키 read/write 는 atomic). 다중키 일관성은 reader 측
        # search/stats 가 deep-1 스냅샷([dict(e) ...])을 떠서 보장(free-threaded 빌드는 미보장).
        self._lock = threading.RLock()
        force_pg = bool(getattr(config, "FORCE_PGVECTOR", False))
        force_pg_strict = bool(getattr(config, "FORCE_PGVECTOR_STRICT", False))
        self.storage = str(getattr(config, "KB_STORAGE", "sqlite") or "sqlite").strip().lower()
        if force_pg:
            self.storage = "pgvector"
        self.db_path = self.base_dir / "kb_index.sqlite"
        self._db_ok = False
        self._db_has_source_file = False
        self.pg_dsn = (
            str(getattr(config, "PGVECTOR_DSN", "") or "").strip()
            or str(getattr(config, "PGVECTOR_URL", "") or "").strip()
            or str(os.environ.get("PGVECTOR_DSN", "") or "").strip()
            or str(os.environ.get("PGVECTOR_URL", "") or "").strip()
        )
        self._pg_ok = False
        self._embed_cache: "OrderedDict[str, List[float]]" = OrderedDict()
        self._embed_cache_max = int(getattr(config, "KB_EMBED_CACHE_MAX", 1000))
        self._max_entries = int(getattr(config, "KB_MAX_ENTRIES", 5000))
        self._db_has_error_count = False
        self._db_has_project_root = False
        self._db_has_metadata = False

        if self.storage == "pgvector":
            if psycopg2 is None or not self.pg_dsn:
                self._pg_ok = False
                if not force_pg:
                    self.storage = "sqlite"
                elif force_pg_strict:
                    raise RuntimeError("pgvector required but psycopg2/dsn not configured")
            else:
                self._pg_ok = self._init_pgvector()
                if force_pg and force_pg_strict and not self._pg_ok:
                    raise RuntimeError("pgvector required but initialization failed")

        if self.storage == "sqlite":
            self._db_ok = self._init_db()
        self._load_all()
        self._ingest_sources_once()

    # ---------------- 내부 유틸 ----------------

    def _iter_entry_files(self):
        for p in self.base_dir.glob("*.json"):
            if p.name.endswith(".tmp") or p.name.endswith(".bak"):
                continue
            yield p

    def _write_atomic(self, path: Path, payload: Any) -> None:
        # tmp 이름에 pid+tid 를 붙여, 같은 source_file 에 대한 동시 write 가
        # 동일 tmp 경로를 두고 replace 충돌(Windows EACCES/부분기록)하는 것을 차단.
        # (이름은 여전히 ".tmp" 로 끝나 _iter_entry_files 가 스킵)
        tmp = path.with_suffix(path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _ensure_shape(self, raw: Dict[str, Any], source_file: str) -> Dict[str, Any]:
        d = dict(raw)
        error_raw = str(d.get("error_raw", ""))
        error_clean = _normalize_message(d.get("error_clean") or error_raw)
        d["error_raw"] = error_raw
        d["error_clean"] = error_clean
        d["fix"] = str(d.get("fix", ""))
        tags = d.get("tags") or []
        if not isinstance(tags, list):
            tags = [str(tags)]
        d["tags"] = [str(t) for t in tags]
        role = d.get("role")
        d["role"] = str(role) if role is not None else None
        stage = d.get("stage")
        d["stage"] = str(stage) if stage is not None else None
        context = d.get("context")
        d["context"] = str(context) if context is not None else ""
        category = d.get("category") or d.get("kb_category") or ""
        d["category"] = str(category).strip() if category else "general"
        vec = d.get("vector") or []
        if isinstance(vec, list):
            d["vector"] = [float(x) for x in vec]
        else:
            d["vector"] = []
        d["weight"] = float(d.get("weight", 1.0))
        d["apply_count"] = int(d.get("apply_count", 0))
        d["timestamp"] = d.get("timestamp") or datetime.utcnow().isoformat()
        d["source_file"] = source_file
        if "id" not in d:
            d["id"] = os.path.splitext(os.path.basename(source_file))[0]
        metadata = d.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        d["metadata"] = metadata
        return d

    def _external_index_path(self) -> Path:
        return self.base_dir / "kb_external_index.json"

    def _load_external_index(self) -> Dict[str, str]:
        try:
            p = self._external_index_path()
            if p.exists():
                obj = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(obj, dict):
                    return {str(k): str(v) for k, v in obj.items()}
        except Exception:
            return {}
        return {}

    def _save_external_index(self, idx: Dict[str, str]) -> None:
        try:
            self._write_atomic(self._external_index_path(), idx)
        except Exception:
            pass

    def add_document(
        self,
        title: str,
        content: str,
        *,
        category: str,
        tags: Optional[List[str]] = None,
        source_file: Optional[str] = None,
    ) -> None:
        text = (content or "").strip()
        if not text:
            return
        vec = self._get_embedding(text)
        req_ids = _extract_req_ids_from_text(text)
        entry: Dict[str, Any] = {
            "id": self._new_id(),
            "error_raw": str(title or "")[:200],
            "error_clean": str(title or "")[:200],
            "fix": text,
            "tags": tags or [],
            "role": "rag",
            "stage": "rag",
            "context": text,
            "category": str(category or "general"),
            "vector": vec,
            "weight": 1.0,
            "apply_count": 0,
            "timestamp": datetime.utcnow().isoformat(),
            "source_file": source_file or "",
            "metadata": {
                "req_ids": req_ids,
                "source_type": str(category or "general"),
            },
        }
        self._append_new_entry(entry, write_to_disk=True)

    def _init_db(self) -> bool:
        try:
            conn = sqlite3.connect(str(self.db_path))
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS kb_entries (
                    id TEXT PRIMARY KEY,
                    error_raw TEXT,
                    error_clean TEXT,
                    fix TEXT,
                    tags TEXT,
                    role TEXT,
                    stage TEXT,
                    category TEXT,
                    context TEXT,
                    vector TEXT,
                    weight REAL,
                    apply_count INTEGER,
                    timestamp TEXT,
                    source_file TEXT,
                    error_count INTEGER,
                    project_root TEXT,
                    metadata TEXT
                )
                """
            )
            try:
                cur.execute("PRAGMA table_info(kb_entries)")
                cols = [row[1] for row in cur.fetchall()]
                if "source_file" not in cols:
                    cur.execute("ALTER TABLE kb_entries ADD COLUMN source_file TEXT")
                if "error_count" not in cols:
                    cur.execute("ALTER TABLE kb_entries ADD COLUMN error_count INTEGER")
                if "project_root" not in cols:
                    cur.execute("ALTER TABLE kb_entries ADD COLUMN project_root TEXT")
                if "metadata" not in cols:
                    cur.execute("ALTER TABLE kb_entries ADD COLUMN metadata TEXT")
                self._db_has_source_file = True
                self._db_has_error_count = True
                self._db_has_project_root = True
                self._db_has_metadata = True
            except Exception:
                self._db_has_source_file = False
                self._db_has_error_count = False
                self._db_has_project_root = False
                self._db_has_metadata = False
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def _pg_connect(self):
        if psycopg2 is None or not self.pg_dsn:
            return None
        try:
            return psycopg2.connect(self.pg_dsn)
        except Exception:
            return None

    def _vector_to_str(self, vec: List[float]) -> Optional[str]:
        if not vec:
            return None
        try:
            return "[" + ",".join(f"{float(v):.6f}" for v in vec) + "]"
        except Exception:
            return None

    def _init_pgvector(self) -> bool:
        conn = self._pg_connect()
        if conn is None:
            return False
        try:
            cur = conn.cursor()
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            _embed_dim = int(getattr(config, "RAG_EMBED_DIM", 768))
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS kb_entries (
                    id TEXT PRIMARY KEY,
                    error_raw TEXT,
                    error_clean TEXT,
                    fix TEXT,
                    tags JSONB,
                    role TEXT,
                    stage TEXT,
                    category TEXT,
                    context TEXT,
                    vector VECTOR({_embed_dim}),
                    weight REAL,
                    apply_count INTEGER,
                    timestamp TEXT,
                    source_file TEXT,
                    error_count INTEGER,
                    project_root TEXT,
                    metadata JSONB
                )
                """
            )
            try:
                cur.execute("ALTER TABLE kb_entries ADD COLUMN IF NOT EXISTS source_file TEXT")
                cur.execute("ALTER TABLE kb_entries ADD COLUMN IF NOT EXISTS error_count INTEGER")
                cur.execute("ALTER TABLE kb_entries ADD COLUMN IF NOT EXISTS project_root TEXT")
                cur.execute("ALTER TABLE kb_entries ADD COLUMN IF NOT EXISTS metadata JSONB")
                self._db_has_metadata = True
            except Exception:
                self._db_has_metadata = False
            conn.commit()
            conn.close()
            return True
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            return False

    def _pg_upsert(self, entry: Dict[str, Any]) -> None:
        if not self._pg_ok:
            return
        conn = self._pg_connect()
        if conn is None:
            return
        try:
            cur = conn.cursor()
            vec_str = self._vector_to_str(entry.get("vector") or [])
            cur.execute(
                """
                INSERT INTO kb_entries
                (id, error_raw, error_clean, fix, tags, role, stage, category, context, vector, weight, apply_count, timestamp, source_file, error_count, project_root, metadata)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s::vector, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    error_raw = EXCLUDED.error_raw,
                    error_clean = EXCLUDED.error_clean,
                    fix = EXCLUDED.fix,
                    tags = EXCLUDED.tags,
                    role = EXCLUDED.role,
                    stage = EXCLUDED.stage,
                    category = EXCLUDED.category,
                    context = EXCLUDED.context,
                    vector = EXCLUDED.vector,
                    weight = EXCLUDED.weight,
                    apply_count = EXCLUDED.apply_count,
                    timestamp = EXCLUDED.timestamp,
                    source_file = EXCLUDED.source_file,
                    error_count = EXCLUDED.error_count,
                    project_root = EXCLUDED.project_root,
                    metadata = EXCLUDED.metadata
                """,
                (
                    entry.get("id"),
                    entry.get("error_raw"),
                    entry.get("error_clean"),
                    entry.get("fix"),
                    json.dumps(entry.get("tags") or [], ensure_ascii=False),
                    entry.get("role"),
                    entry.get("stage"),
                    entry.get("category"),
                    entry.get("context"),
                    vec_str,
                    float(entry.get("weight", 1.0)),
                    int(entry.get("apply_count", 0)),
                    entry.get("timestamp"),
                    entry.get("source_file") or "",
                    int(entry.get("error_count", 0)),
                    entry.get("project_root") or "",
                    json.dumps(entry.get("metadata") or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    def _pg_search(
        self,
        q_vec: List[float],
        query: str,
        top_k: int,
        *,
        tags: Optional[List[str]] = None,
        role: Optional[str] = None,
        stage: Optional[str] = None,
        categories: Optional[List[str]] = None,
        req_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not self._pg_ok:
            return []
        conn = self._pg_connect()
        if conn is None:
            return []
        if not q_vec:
            return []
        q_vec_str = self._vector_to_str(q_vec)
        if not q_vec_str:
            return []

        clauses: List[str] = []
        params: List[Any] = []
        if role:
            clauses.append("role = %s")
            params.append(role)
        if stage:
            clauses.append("stage = %s")
            params.append(stage)
        if categories:
            clauses.append("category = ANY(%s)")
            params.append(categories)

        where_sql = ""
        if clauses:
            where_sql = " WHERE " + " AND ".join(clauses)

        sql = (
            "SELECT id, error_raw, error_clean, fix, tags, role, stage, category, context, "
            "weight, apply_count, timestamp, source_file, error_count, project_root, metadata, "
            "(1 - (vector <=> %s::vector)) AS score "
            f"FROM kb_entries{where_sql} "
            "ORDER BY vector <=> %s::vector NULLS LAST "
            "LIMIT %s"
        )
        params_with_vec = list(params) + [q_vec_str, q_vec_str, int(max(1, top_k * 5))]

        results: List[Dict[str, Any]] = []
        project_boost = float(getattr(config, "RAG_PROJECT_BOOST", 0.0))
        recency_days = float(getattr(config, "RAG_RECENCY_DAYS", 0))
        recency_boost = float(getattr(config, "RAG_RECENCY_BOOST", 0.0))
        apply_boost = float(getattr(config, "RAG_APPLY_COUNT_BOOST", 0.0))
        error_boost = float(getattr(config, "RAG_ERROR_COUNT_BOOST", 0.0))
        try:
            cur = conn.cursor()
            cur.execute(sql, params_with_vec)
            rows = cur.fetchall()
            conn.close()
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            return []

        norm_tags = [str(t) for t in (tags or []) if str(t).strip()]
        req_ids = [str(x).strip() for x in (req_ids or []) if str(x).strip()]
        exact_boost = float(getattr(config, "RAG_EXACT_MATCH_BOOST", 0.4))
        for row in rows:
            ent_tags = []
            try:
                ent_tags = json.loads(row[4] or "[]")
                if not isinstance(ent_tags, list):
                    ent_tags = []
            except Exception:
                ent_tags = []

            if norm_tags:
                hit = len(set(ent_tags).intersection(norm_tags))
                if hit == 0:
                    continue

            metadata = {}
            try:
                metadata = row[15] or {}
            except Exception:
                metadata = {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}
            item = {
                "id": row[0],
                "error_raw": row[1],
                "error_clean": row[2],
                "fix": row[3],
                "tags": ent_tags,
                "role": row[5],
                "stage": row[6],
                "category": row[7] or "general",
                "context": row[8] or "",
                "weight": float(row[9] or 1.0),
                "apply_count": int(row[10] or 0),
                "timestamp": row[11] or "",
                "source_file": row[12] or "",
                "error_count": int(row[13] or 0),
                "project_root": row[14] or "",
                "metadata": metadata if isinstance(metadata, dict) else {},
                "score": float(row[16] or 0.0),
            }
            score = float(item.get("score") or 0.0)
            if recency_days > 0 and item.get("timestamp"):
                try:
                    ts = datetime.fromisoformat(str(item.get("timestamp")))
                    delta_days = (datetime.utcnow() - ts).total_seconds() / 86400.0
                    if delta_days < recency_days:
                        score += recency_boost * (1.0 - (delta_days / recency_days))
                except Exception:
                    pass
            if project_boost > 0:
                project_root = str(item.get("project_root") or "")
                if project_root and project_root in query:
                    score += project_boost
            if apply_boost > 0:
                score += apply_boost * float(item.get("apply_count") or 0)
            if error_boost > 0:
                score += error_boost * float(item.get("error_count") or 0)
            if req_ids:
                hay = " ".join(
                    [
                        str(item.get("error_raw") or ""),
                        str(item.get("error_clean") or ""),
                        str(item.get("context") or ""),
                        str(item.get("source_file") or ""),
                        json.dumps(item.get("metadata") or {}, ensure_ascii=False),
                    ]
                )
                if any(rid in hay for rid in req_ids):
                    score += exact_boost
            item["score"] = float(score)
            results.append(item)

        results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return results[:top_k]

    def _db_upsert(self, entry: Dict[str, Any]) -> None:
        if not self._db_ok or self.storage != "sqlite":
            return
        try:
            conn = sqlite3.connect(str(self.db_path))
            cur = conn.cursor()
            if self._db_has_source_file:
                if self._db_has_metadata:
                    cur.execute(
                        """
                        INSERT OR REPLACE INTO kb_entries
                        (id, error_raw, error_clean, fix, tags, role, stage, category, context, vector, weight, apply_count, timestamp, source_file, error_count, project_root, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            entry.get("id"),
                            entry.get("error_raw"),
                            entry.get("error_clean"),
                            entry.get("fix"),
                            json.dumps(entry.get("tags") or [], ensure_ascii=False),
                            entry.get("role"),
                            entry.get("stage"),
                            entry.get("category"),
                            entry.get("context"),
                            json.dumps(entry.get("vector") or [], ensure_ascii=False),
                            float(entry.get("weight", 1.0)),
                            int(entry.get("apply_count", 0)),
                            entry.get("timestamp"),
                            entry.get("source_file") or "",
                            int(entry.get("error_count", 0)),
                            entry.get("project_root") or "",
                            json.dumps(entry.get("metadata") or {}, ensure_ascii=False),
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT OR REPLACE INTO kb_entries
                        (id, error_raw, error_clean, fix, tags, role, stage, category, context, vector, weight, apply_count, timestamp, source_file, error_count, project_root)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            entry.get("id"),
                            entry.get("error_raw"),
                            entry.get("error_clean"),
                            entry.get("fix"),
                            json.dumps(entry.get("tags") or [], ensure_ascii=False),
                            entry.get("role"),
                            entry.get("stage"),
                            entry.get("category"),
                            entry.get("context"),
                            json.dumps(entry.get("vector") or [], ensure_ascii=False),
                            float(entry.get("weight", 1.0)),
                            int(entry.get("apply_count", 0)),
                            entry.get("timestamp"),
                            entry.get("source_file") or "",
                            int(entry.get("error_count", 0)),
                            entry.get("project_root") or "",
                        ),
                    )
            else:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO kb_entries
                    (id, error_raw, error_clean, fix, tags, role, stage, category, context, vector, weight, apply_count, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.get("id"),
                        entry.get("error_raw"),
                        entry.get("error_clean"),
                        entry.get("fix"),
                        json.dumps(entry.get("tags") or [], ensure_ascii=False),
                        entry.get("role"),
                        entry.get("stage"),
                        entry.get("category"),
                        entry.get("context"),
                        json.dumps(entry.get("vector") or [], ensure_ascii=False),
                        float(entry.get("weight", 1.0)),
                        int(entry.get("apply_count", 0)),
                        entry.get("timestamp"),
                    ),
                )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _db_load_all(self) -> List[Dict[str, Any]]:
        if not self._db_ok or self.storage != "sqlite":
            return []
        out: List[Dict[str, Any]] = []
        try:
            conn = sqlite3.connect(str(self.db_path))
            cur = conn.cursor()
            if self._db_has_source_file:
                if self._db_has_metadata:
                    cur.execute(
                        """
                        SELECT id, error_raw, error_clean, fix, tags, role, stage, category, context, vector, weight, apply_count, timestamp, source_file, error_count, project_root, metadata
                        FROM kb_entries
                        """
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, error_raw, error_clean, fix, tags, role, stage, category, context, vector, weight, apply_count, timestamp, source_file, error_count, project_root
                        FROM kb_entries
                        """
                    )
            else:
                cur.execute(
                    """
                    SELECT id, error_raw, error_clean, fix, tags, role, stage, category, context, vector, weight, apply_count, timestamp
                    FROM kb_entries
                    """
                )
            rows = cur.fetchall()
            conn.close()
            for row in rows:
                tags = []
                vector = []
                try:
                    tags = json.loads(row[4] or "[]")
                except Exception:
                    tags = []
                try:
                    vector = json.loads(row[9] or "[]")
                except Exception:
                    vector = []
                source_file = ""
                error_count = 0
                project_root = ""
                metadata = {}
                if self._db_has_source_file and len(row) > 13:
                    source_file = row[13] or ""
                if self._db_has_error_count and len(row) > 14:
                    try:
                        error_count = int(row[14] or 0)
                    except Exception:
                        error_count = 0
                if self._db_has_project_root and len(row) > 15:
                    project_root = row[15] or ""
                if self._db_has_metadata and len(row) > 16:
                    try:
                        metadata = json.loads(row[16] or "{}")
                    except Exception:
                        metadata = {}
                out.append(
                    {
                        "id": row[0],
                        "error_raw": row[1],
                        "error_clean": row[2],
                        "fix": row[3],
                        "tags": tags if isinstance(tags, list) else [],
                        "role": row[5],
                        "stage": row[6],
                        "category": row[7] or "general",
                        "context": row[8] or "",
                        "vector": vector if isinstance(vector, list) else [],
                        "weight": float(row[10] or 1.0),
                        "apply_count": int(row[11] or 0),
                        "timestamp": row[12] or "",
                        "source_file": source_file,
                        "error_count": error_count,
                        "project_root": project_root,
                        "metadata": metadata if isinstance(metadata, dict) else {},
                    }
                )
        except Exception:
            return []
        return out

    def _ingest_sources_once(self) -> None:
        src_dir = str(getattr(config, "KB_SOURCES_DIR", "") or os.environ.get("KB_SOURCES_DIR", "") or "").strip()
        if not src_dir:
            return
        base = Path(src_dir).expanduser().resolve()
        if not base.exists() or not base.is_dir():
            return
        index_path = self.base_dir / "kb_ingest_index.json"
        seen: Dict[str, Any] = {}
        try:
            if index_path.exists():
                seen = json.loads(index_path.read_text(encoding="utf-8"))
                if not isinstance(seen, dict):
                    seen = {}
        except Exception:
            seen = {}

        updated = False
        for fp in base.rglob("*.json"):
            try:
                rel = fp.relative_to(base).as_posix()
                stat = fp.stat()
                sig = f"{stat.st_mtime_ns}:{stat.st_size}"
                if seen.get(rel) == sig:
                    continue
                payload = json.loads(fp.read_text(encoding="utf-8"))
                entries = payload if isinstance(payload, list) else [payload]
                cat = fp.parent.name if fp.parent != base else "general"
                for ent in entries:
                    if not isinstance(ent, dict):
                        continue
                    ent.setdefault("category", cat)
                    shaped = self._ensure_shape(ent, fp.name)
                    self._append_new_entry(shaped, write_to_disk=True)
                seen[rel] = sig
                updated = True
            except Exception:
                continue

        if updated:
            try:
                index_path.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

    def _load_all(self) -> None:
        """전체 엔트리를 self.data 로 로드.

        불변식: __init__ 에서만 호출되며(인스턴스가 _KB_CACHE 에 공개되기 전,
        다른 스레드가 참조를 얻기 전), self._lock 으로 가드하지 않는다. self.data
        를 변이하는 다른 모든 메서드(_append_new_entry/learn/feedback/
        _enforce_max_entries)와 reader(search/stats)는 _lock 보호된다. 향후
        공개 reload()/refresh() 로 노출하려면 반드시 self._lock 으로 감쌀 것.
        """
        started = _time.perf_counter()
        if self.storage == "pgvector" and self._pg_ok:
            self.data.clear()
            return
        # 1) 레거시 단일 JSON 파일 -> 디렉터리로 마이그레이션 (최초 1회)
        legacy = self.base_dir.parent / "knowledge_base.json"
        has_entries = any(True for _ in self._iter_entry_files())
        if legacy.exists() and not has_entries:
            try:
                raw = json.loads(legacy.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    raw = raw.get("data") or raw.get("entries") or []
                if isinstance(raw, list):
                    for idx, ent in enumerate(raw):
                        if not isinstance(ent, dict):
                            continue
                        tmp = self._ensure_shape(ent, f"legacy_{idx}.json")
                        self._append_new_entry(tmp, write_to_disk=True)
                # 백업 후 원본 rename
                legacy.rename(legacy.with_suffix(legacy.suffix + ".bak"))
            except Exception:
                # 실패해도 그냥 무시, 이후 현재 디렉터리만 사용
                pass

        # 2) 디렉터리 내 엔트리 로드
        self.data.clear()
        if self.storage == "sqlite" and self._db_ok:
            self.data = self._db_load_all()
            if self.data:
                return

        for fp in sorted(self._iter_entry_files(), key=lambda p: p.name):
            try:
                txt = fp.read_text(encoding="utf-8")
                if not txt.strip():
                    continue
                obj = json.loads(txt)
                if isinstance(obj, list):
                    objs = obj
                else:
                    objs = [obj]
                for ent in objs:
                    if not isinstance(ent, dict):
                        continue
                    shaped = self._ensure_shape(ent, fp.name)
                    self._db_upsert(shaped)
                    self.data.append(shaped)
            except Exception:
                # 손상된 파일은 건너뛰기
                continue

    def _new_id(self) -> str:
        return (
            "kb_"
            + datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")
            + f"_{next(_ID_COUNTER):x}"
        )

    def _append_new_entry(self, entry: Dict[str, Any], write_to_disk: bool = True) -> None:
        if "id" not in entry:
            entry["id"] = self._new_id()
        file_name = f"{entry['id']}.json"
        if write_to_disk:
            path = self.base_dir / file_name
            self._write_atomic(path, entry)
        if self.storage == "pgvector":
            self._pg_upsert(entry)
        else:
            self._db_upsert(entry)
        # 디스크/DB write(위)는 id 기준 멱등이라 락 밖에서 수행 가능.
        # 공유 상태인 self.data 구조변경만 락으로 직렬화.
        with self._lock:
            self.data.append(entry)

    def _get_embedding(self, text: str) -> List[float]:
        from workflow.rag.embedder import get_embedding
        return get_embedding(text)

    # ---------------- 퍼블릭 API ----------------

    def search(
        self,
        error_msg: str,
        top_k: int = 3,
        *,
        tags: Optional[List[str]] = None,
        role: Optional[str] = None,
        stage: Optional[str] = None,
        categories: Optional[List[str]] = None,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        에러 메시지를 기반으로 과거 성공 패턴 검색
        """
        started = _time.perf_counter()

        norm_cats = [str(c) for c in (categories or []) if str(c).strip()]
        if category:
            norm_cats.append(str(category))

        if self.storage == "pgvector" and self._pg_ok:
            # pgvector: 기존 DB 레벨 검색 유지 (self.data 미사용)
            query = _normalize_message(error_msg)
            req_ids = _extract_req_ids_from_text(query)
            q_vec = self._get_embedding(query)
            rows = self._pg_search(
                q_vec,
                query=query,
                top_k=top_k,
                tags=tags,
                role=role,
                stage=stage,
                categories=norm_cats or None,
                req_ids=req_ids,
            )
            entries_n = 0
        else:
            # SQLite: hybrid search 사용.
            # 동시 learn/feedback 의 엔트리 다중키 in-place 변이로부터 reader 를 격리하기 위해
            # 락 안에서 deep-1 스냅샷(엔트리 dict 사본)을 떠서 검색한다. 얕은 list 복사로는
            # 동일 dict 객체를 공유해 torn read(weight 새값 + apply_count 옛값)가 발생한다.
            from workflow.rag.searcher import hybrid_search
            query = _normalize_message(error_msg)
            with self._lock:
                snap = [dict(e) for e in self.data]
            entries_n = len(snap)
            rows = hybrid_search(
                snap, query, top_k,
                tags=tags, role=role, stage=stage,
                categories=norm_cats or None,
            )

        if _RAG_PERF_LOG:
            _rag_logger.info(
                "rag_search storage=%s entries=%d query_chars=%d top_k=%d hits=%d elapsed_ms=%.1f",
                self.storage,
                entries_n,
                len(query),
                top_k,
                len(rows),
                (_time.perf_counter() - started) * 1000.0,
            )
        return rows

    def learn(
        self,
        error_msg: str,
        fix_pattern: str,
        tags: Optional[List[str]] = None,
        success: bool = True,
        *,
        role: Optional[str] = None,
        stage: Optional[str] = None,
        context: Optional[str] = None,
        category: Optional[str] = None,
        project_root: Optional[str] = None,
    ) -> None:
        """
        성공한 수정 패턴을 지식 베이스에 저장
        """
        if not success:
            # 실패한 패턴은 기본적으로 저장하지 않음
            return

        ctx = _normalize_message(error_msg)
        if not ctx:
            return

        # 중복 패턴 간단 필터링 (동일 error_clean + 유사 fix).
        # 탐색 + 다중키 in-place 변이는 락 안에서(reader torn read 방지),
        # 디스크/DB write 는 그 스냅샷으로 락 밖에서 수행.
        dup_payload = None
        with self._lock:
            for ent in self.data:
                if ent.get("error_clean") == ctx and ent.get("fix") == fix_pattern:
                    if role and ent.get("role") not in (None, role):
                        continue
                    if stage and ent.get("stage") not in (None, stage):
                        continue
                    # 이미 동일 패턴 존재 -> weight만 조금 올리고 종료
                    ent["weight"] = float(ent.get("weight", 1.0)) + 0.1
                    ent["apply_count"] = int(ent.get("apply_count", 0)) + 1
                    ent["error_count"] = int(ent.get("error_count", 0)) + 1
                    if project_root:
                        ent["project_root"] = project_root
                    sf = ent.get("source_file") or ""
                    if not sf:
                        sf = f"{ent['id']}.json"
                        ent["source_file"] = sf
                    dup_payload = (sf, dict(ent))
                    break
        if dup_payload is not None:
            sf, snapshot = dup_payload
            self._write_atomic(self.base_dir / sf, snapshot)
            if self.storage == "pgvector":
                self._pg_upsert(snapshot)
            else:
                self._db_upsert(snapshot)
            return

        # 신규 엔트리: 임베딩(네트워크 round-trip)은 절대 락 밖에서 계산한다.
        # (락 해제 ~ _append_new_entry 사이 동일 패턴 동시 삽입은 드문 중복으로,
        #  dedup 이 best-effort 이므로 허용 — 크래시/유실 없음.)
        vec = self._get_embedding(ctx)
        entry: Dict[str, Any] = {
            "id": self._new_id(),
            "error_raw": error_msg,
            "error_clean": ctx,
            "fix": fix_pattern,
            "tags": tags or [],
            "role": str(role) if role else None,
            "stage": str(stage) if stage else None,
            "context": str(context) if context else "",
            "category": str(category).strip() if category else "general",
            "vector": vec,
            "weight": 1.0,
            "apply_count": 1,
            "error_count": 1,
            "timestamp": datetime.utcnow().isoformat(),
            "source_file": "",  # _append_new_entry 에서 채움
            "project_root": project_root or "",
        }
        self._append_new_entry(entry, write_to_disk=True)
        self._enforce_max_entries()

    def _delete_db_rows(self, ids: Iterable[Optional[str]]) -> None:
        """trim 된 엔트리를 영속 저장소에서도 삭제 (파일 unlink 와 정합).

        기존엔 파일만 unlink 하고 DB row 는 남아, TTL 캐시 재빌드(_db_load_all)가
        trimming 을 되돌렸다(선재 버그). 캐시 도입과 함께 DB/PG 삭제를 동봉.
        """
        id_list = [str(i) for i in ids if i]
        if not id_list:
            return
        try:
            if self.storage == "pgvector" and self._pg_ok:
                conn = self._pg_connect()
                if conn is None:
                    return
                try:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM kb_entries WHERE id = ANY(%s)", (id_list,))
                    conn.commit()
                finally:
                    conn.close()
            elif self._db_ok and self.storage == "sqlite":
                conn = sqlite3.connect(str(self.db_path))
                try:
                    # sqlite 변수 상한(구버전 999) 초과 시 OperationalError 가
                    # except 로 삼켜져 row 가 남으면 resurrect 재발 → 배치로 분할.
                    for i in range(0, len(id_list), 900):
                        batch = id_list[i:i + 900]
                        placeholders = ",".join("?" for _ in batch)
                        conn.execute(
                            f"DELETE FROM kb_entries WHERE id IN ({placeholders})", batch,
                        )
                    conn.commit()
                finally:
                    conn.close()
        except Exception:
            pass

    def _enforce_max_entries(self) -> None:
        # 후보 산정 + self.data 재바인드는 락 안에서, 파일 unlink/DB 삭제(I/O)는 락 밖.
        with self._lock:
            if self._max_entries <= 0 or len(self.data) <= self._max_entries:
                return
            sorted_entries = sorted(
                self.data,
                key=lambda e: (float(e.get("weight", 1.0)), e.get("timestamp", "")),
            )
            to_remove = sorted_entries[: len(self.data) - self._max_entries]
            remove_ids = {e.get("id") for e in to_remove}
            removed_sfs = [e.get("source_file") for e in to_remove]
            self.data = [e for e in self.data if e.get("id") not in remove_ids]
        for sf in removed_sfs:
            if sf:
                p = self.base_dir / sf
                try:
                    if p.exists():
                        p.unlink()
                except OSError:
                    pass
        self._delete_db_rows(remove_ids)

    def stats(self) -> Dict[str, Any]:
        by_category: Dict[str, int] = {}
        by_source: Dict[str, int] = {}
        source_latest: Dict[str, str] = {}
        with self._lock:
            snap = list(self.data)
        for ent in snap:
            cat = str(ent.get("category") or "general")
            by_category[cat] = by_category.get(cat, 0) + 1
            src = str(ent.get("source_file") or "unknown")
            by_source[src] = by_source.get(src, 0) + 1
            ts = str(ent.get("timestamp") or "")
            if ts:
                prev = source_latest.get(src, "")
                if not prev or ts > prev:
                    source_latest[src] = ts
        source_list = [
            {"source": k, "count": v, "last_ts": source_latest.get(k, "")}
            for k, v in by_source.items()
        ]
        source_list.sort(key=lambda x: x.get("count", 0), reverse=True)
        category_list = [{"category": k, "count": v} for k, v in by_category.items()]
        category_list.sort(key=lambda x: x.get("count", 0), reverse=True)
        return {
            "total": len(snap),
            "by_category": by_category,
            "by_source": by_source,
            "source_list": source_list,
            "category_list": category_list,
        }

    def feedback(self, index: int, positive: bool = True) -> None:
        """
        나중에 UI에서 thumbs-up/down 같은 피드백 연결용 훅

        주의: positional index 는 _enforce_max_entries 재바인드/동시 learn 으로
        가리키는 엔트리가 바뀔 수 있다(stale-index TOCTOU). 락은 크래시만 막고
        의미적 정확성은 보장 못 함 — id 기반 조회 전환은 후속 백로그.
        """
        payload = None
        with self._lock:
            if index < 0 or index >= len(self.data):
                return
            ent = self.data[index]
            delta = 0.2 if positive else -0.2
            ent["weight"] = max(0.1, float(ent.get("weight", 1.0)) + delta)
            ent["apply_count"] = int(ent.get("apply_count", 0)) + (1 if positive else 0)
            sf = ent.get("source_file") or ""
            payload = (sf, dict(ent))
        sf, snapshot = payload
        if not sf:
            # source_file 미설정 엔트리는 디스크 기록 스킵(기존 KeyError 위험 방어)
            return
        self._write_atomic(self.base_dir / sf, snapshot)
        if self.storage == "pgvector":
            self._pg_upsert(snapshot)
        else:
            self._db_upsert(snapshot)


# ---------------- get_kb 프로세스 캐시 (D8) ----------------
# 매 호출마다 KnowledgeBase 를 새로 구성(_init_db + _load_all + _ingest)하던 비용을
# 제거한다. 인스턴스가 스레드 간 공유되므로 KnowledgeBase 내부 RLock 이 race 를 막는다.
#   - key: normcase(resolve(base_dir)) — 상대/절대/드라이브 대소문자 collapse
#   - TTL(KB_CACHE_TTL_SECONDS): 멀티프로세스(pipeline 별도 프로세스) staleness 상한.
#     in-process 쓰기는 즉시 _db_upsert/_write_atomic 로 영속되므로 재빌드는 무손실.
#   - LRU(KB_CACHE_MAX_ENTRIES): session/build 별 고cardinality 경로의 메모리 누수 차단.
#   - per-key 빌드락: 무관 key 의 콜드빌드를 직렬화하지 않음(캐시락은 dict 조작만 짧게).
_KB_CACHE: "OrderedDict[str, Tuple[KnowledgeBase, float]]" = OrderedDict()
_KB_BUILD_LOCKS: Dict[str, "threading.Lock"] = {}
_KB_CACHE_LOCK = threading.Lock()


def _clear_kb_cache() -> None:
    """프로세스 캐시 초기화 (테스트 격리 / 운영 강제 무효화)."""
    with _KB_CACHE_LOCK:
        _KB_CACHE.clear()
        _KB_BUILD_LOCKS.clear()


def _kb_cache_ttl() -> float:
    try:
        return float(getattr(config, "KB_CACHE_TTL_SECONDS", 120) or 0)
    except (TypeError, ValueError):
        return 120.0


def _kb_cache_max() -> int:
    try:
        return max(1, int(getattr(config, "KB_CACHE_MAX_ENTRIES", 32) or 32))
    except (TypeError, ValueError):
        return 32


def _kb_resolve_base_dir(report_dir: Path) -> Path:
    global_dir = str(getattr(config, "KB_GLOBAL_DIR", "") or "").strip()
    if global_dir:
        return Path(global_dir).expanduser().resolve()
    kb_dir_name = getattr(config, "KB_DIR_NAME", "kb_store")
    return (Path(report_dir) / kb_dir_name).expanduser().resolve()


def _purge_expired_locked(now: float, ttl: float) -> None:
    if ttl <= 0:
        return
    stale = [k for k, (_, ts) in _KB_CACHE.items() if (now - ts) >= ttl]
    for k in stale:
        _KB_CACHE.pop(k, None)
        _KB_BUILD_LOCKS.pop(k, None)


def get_kb(report_dir: Path) -> KnowledgeBase:
    """report_dir 기준 RAG 저장소 인스턴스 반환 (프로세스 캐시 + TTL + LRU).

    base_dir = report_dir / config.KB_DIR_NAME (또는 config.KB_GLOBAL_DIR).
    멀티프로세스에서 같은 base_dir 에 쓰는 워크플로(pipeline)와 즉시 일관성이
    필요하면 KB_CACHE_ENABLED=0 또는 짧은 KB_CACHE_TTL_SECONDS 를 쓰거나,
    고cardinality 경로(session/build 별)는 KB_GLOBAL_DIR 로 collapse 하는 것을 권장.
    """
    base_dir = _kb_resolve_base_dir(report_dir)
    if not bool(getattr(config, "KB_CACHE_ENABLED", True)):
        return KnowledgeBase(base_dir)

    key = os.path.normcase(str(base_dir))
    ttl = _kb_cache_ttl()
    now = _time.time()

    with _KB_CACHE_LOCK:
        _purge_expired_locked(now, ttl)
        hit = _KB_CACHE.get(key)
        if hit is not None:
            _KB_CACHE.move_to_end(key)
            return hit[0]
        build_lock = _KB_BUILD_LOCKS.get(key)
        if build_lock is None:
            build_lock = threading.Lock()
            _KB_BUILD_LOCKS[key] = build_lock

    # 빌드(디스크/DB I/O)는 캐시락 밖에서. 동일 key 중복빌드만 per-key 락으로 차단.
    with build_lock:
        with _KB_CACHE_LOCK:
            hit = _KB_CACHE.get(key)
            if hit is not None:
                _KB_CACHE.move_to_end(key)
                return hit[0]
        inst = KnowledgeBase(base_dir)
        with _KB_CACHE_LOCK:
            _KB_CACHE[key] = (inst, _time.time())
            _KB_CACHE.move_to_end(key)
            while len(_KB_CACHE) > _kb_cache_max():
                old_key, _ = _KB_CACHE.popitem(last=False)
                _KB_BUILD_LOCKS.pop(old_key, None)
        return inst
