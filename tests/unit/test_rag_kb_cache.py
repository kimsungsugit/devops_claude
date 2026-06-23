"""get_kb 프로세스 캐시(D8) + KnowledgeBase 동시성 가드 회귀.

- 캐시 동일성/경로 정규화/구분/disable/TTL/LRU
- _enforce_max_entries 의 DB row 삭제(파일 unlink 와 정합)
- 공유 인스턴스에 대한 동시 search↔learn no-crash (cache B race 종결)
- _new_id 원자 카운터(동시 learn id 충돌→유실 방지)
"""
from __future__ import annotations

import itertools
import sqlite3
import threading
import traceback
from pathlib import Path

import pytest

import config
import workflow.rag as rag
import workflow.rag.embedder as emb
from workflow.rag import KnowledgeBase, _clear_kb_cache, get_kb


@pytest.fixture
def kb_env(monkeypatch, tmp_path):
    """sqlite 저장소 + 임베딩 네트워크 차단 + 캐시 ON 기본."""
    monkeypatch.setattr(emb, "get_embedding", lambda text: [float(len(str(text)) % 5)] * 8)
    monkeypatch.setattr(config, "KB_GLOBAL_DIR", "")
    monkeypatch.setattr(config, "KB_SOURCES_DIR", "")
    monkeypatch.setattr(config, "KB_STORAGE", "sqlite")
    monkeypatch.setattr(config, "FORCE_PGVECTOR", False)
    monkeypatch.setattr(config, "KB_CACHE_ENABLED", True)
    monkeypatch.setattr(config, "KB_CACHE_TTL_SECONDS", 120)
    monkeypatch.setattr(config, "KB_CACHE_MAX_ENTRIES", 32)
    monkeypatch.setattr(config, "KB_MAX_ENTRIES", 5000, raising=False)
    _clear_kb_cache()
    yield tmp_path
    _clear_kb_cache()


# ---------------- 캐시 동일성/키 ----------------

def test_get_kb_caches_same_dir(kb_env):
    d = kb_env / "rep"
    a = get_kb(d)
    b = get_kb(d)
    assert a is b  # 같은 base_dir → 동일 인스턴스 재사용


def test_get_kb_normalizes_path_forms(kb_env):
    """상대/절대/드라이브 대소문자 혼재가 같은 key 로 collapse 되어야 분열 안 함."""
    d = kb_env / "rep"
    a = get_kb(d)
    # 같은 물리 디렉터리를 가리키는 다른 Path 표현
    b = get_kb(Path(str(d)))
    c = get_kb(d / "." / "..")  # → kb_env, 다른 디렉터리이므로 분리되어야
    assert a is b
    assert a is not c


def test_get_kb_distinct_dirs(kb_env):
    a = get_kb(kb_env / "rep1")
    b = get_kb(kb_env / "rep2")
    assert a is not b
    assert a.base_dir != b.base_dir


def test_get_kb_disabled_returns_fresh(kb_env, monkeypatch):
    monkeypatch.setattr(config, "KB_CACHE_ENABLED", False)
    d = kb_env / "rep"
    a = get_kb(d)
    b = get_kb(d)
    assert a is not b  # 캐시 비활성 → 매번 새 인스턴스


# ---------------- TTL / LRU ----------------

class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def time(self):
        return self.t

    def perf_counter(self):
        return self.t


def test_get_kb_ttl_expiry(kb_env, monkeypatch):
    clk = _Clock()
    monkeypatch.setattr(rag, "_time", clk)
    monkeypatch.setattr(config, "KB_CACHE_TTL_SECONDS", 10)
    d = kb_env / "rep"
    a = get_kb(d)
    assert get_kb(d) is a  # 만료 전
    clk.t += 11  # TTL 경과
    b = get_kb(d)
    assert b is not a  # 만료 → 재빌드


def test_get_kb_lru_eviction(kb_env, monkeypatch):
    monkeypatch.setattr(config, "KB_CACHE_MAX_ENTRIES", 2)
    a = get_kb(kb_env / "r1")
    get_kb(kb_env / "r2")
    get_kb(kb_env / "r3")  # r1 evict (가장 오래됨)
    a2 = get_kb(kb_env / "r1")
    assert a2 is not a  # evict 되어 재빌드


# ---------------- enforce_max_entries DB 삭제 ----------------

def test_enforce_max_entries_deletes_db_rows(kb_env, monkeypatch):
    """trim 후 파일 unlink 뿐 아니라 DB row 도 삭제되어야(재빌드 resurrect 방지)."""
    monkeypatch.setattr(config, "KB_MAX_ENTRIES", 5, raising=False)
    kb = get_kb(kb_env / "rep")
    for i in range(12):
        kb.learn(f"err {i}", f"fix {i}", success=True)
    assert len(kb.data) == 5
    dbp = kb.base_dir / "kb_index.sqlite"
    conn = sqlite3.connect(str(dbp))
    try:
        n = conn.execute("SELECT COUNT(*) FROM kb_entries").fetchone()[0]
    finally:
        conn.close()
    assert n == 5, f"DB row 가 trim 과 불일치(resurrect 위험): {n}"


# ---------------- 동시성 ----------------

def test_concurrent_search_learn_no_crash(kb_env):
    """공유 캐시 인스턴스에 동시 search/stats ↔ learn/feedback → 크래시 없음."""
    kb = get_kb(kb_env / "rep")
    for i in range(20):
        kb.learn(f"seed {i}", f"sfix {i}", success=True)

    errors: list[str] = []
    ctr = itertools.count()
    n_threads = 10
    barrier = threading.Barrier(n_threads)

    def searcher():
        barrier.wait()
        try:
            for _ in range(60):
                kb.search("seed 5", top_k=3)
                kb.stats()
        except Exception:
            errors.append(traceback.format_exc())

    def learner():
        barrier.wait()
        try:
            for _ in range(60):
                n = next(ctr)
                kb.learn(f"new {n}", f"nfix {n}", success=True)
                kb.feedback(0, True)
        except Exception:
            errors.append(traceback.format_exc())

    threads = [threading.Thread(target=searcher) for _ in range(6)]
    threads += [threading.Thread(target=learner) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, "동시성 크래시:\n" + "\n".join(errors[:2])


def test_new_id_unique_under_rapid_calls(kb_env):
    """같은 us 타임스탬프라도 카운터 접미로 id 가 유일해야(동시 learn 유실 방지)."""
    kb = get_kb(kb_env / "rep")
    ids = [kb._new_id() for _ in range(2000)]
    assert len(set(ids)) == len(ids)


def test_direct_construct_resolves_base_dir(kb_env):
    """직접 생성자도 base_dir 을 resolve — 캐시 key 와 정합."""
    d = kb_env / "rep"
    kb = KnowledgeBase(d)
    assert kb.base_dir == d.expanduser().resolve()


def test_clear_kb_cache_forces_rebuild(kb_env):
    """_clear_kb_cache 후 get_kb 는 새 인스턴스를 빌드 — storage 전환 반영의 토대.

    (local.py use-pgvector 가 config 변이 후 이 호출로 stale sqlite 인스턴스를
    버리고 pgvector 로 재빌드되게 하는 계약.)
    """
    d = kb_env / "rep"
    a = get_kb(d)
    assert get_kb(d) is a
    _clear_kb_cache()
    b = get_kb(d)
    assert b is not a


def test_delete_db_rows_chunks_over_var_limit(kb_env):
    """_delete_db_rows 가 900 초과 id 도 배치로 전부 삭제(IN절 변수상한 회피)."""
    kb = get_kb(kb_env / "rep")
    ids = []
    for i in range(1500):
        ent = kb._ensure_shape(
            {"error_raw": f"e{i}", "fix": f"f{i}", "id": f"kb_x_{i}"}, f"kb_x_{i}.json",
        )
        kb._db_upsert(ent)
        ids.append(ent["id"])
    kb._delete_db_rows(ids)
    conn = sqlite3.connect(str(kb.base_dir / "kb_index.sqlite"))
    try:
        n = conn.execute("SELECT COUNT(*) FROM kb_entries").fetchone()[0]
    finally:
        conn.close()
    assert n == 0, f"chunk 삭제 후 잔존 row: {n}"
