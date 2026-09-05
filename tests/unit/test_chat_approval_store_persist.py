"""승인 store SQLite 영속화 회귀 (R2 — 멀티워커/재시작 생존, 원자 pop)."""
from __future__ import annotations

import threading

import pytest

import backend.services.chat_history_db as db
from backend.services import chat_approval_store as store


@pytest.fixture
def store_db(tmp_path):
    path = tmp_path / "chat_history.sqlite"
    db.reset_engine()
    db.init_db(path)
    yield path
    db.reset_engine()


def test_save_get_pop_roundtrip(store_db):
    store.save_pending_approval("a1", {"owner": "alice", "question": "배포해줘"})
    got = store.get_pending_approval("a1")
    assert got is not None
    assert got["owner"] == "alice"
    assert got["question"] == "배포해줘"
    assert "saved_at" in got
    # pop 1회 성공
    popped = store.pop_pending_approval("a1")
    assert popped is not None and popped["owner"] == "alice"
    # pop 후 사라짐
    assert store.get_pending_approval("a1") is None


def test_persists_across_engine_reset(store_db):
    """재시작(엔진 재생성) 후에도 동일 파일에서 승인이 보존된다(멀티워커/restart)."""
    store.save_pending_approval("persist1", {"owner": "bob"})
    # 엔진/세션 팩토리를 버리고 같은 파일로 재초기화 = 워커 재시작 시뮬레이션
    db.reset_engine()
    db.init_db(store_db)
    got = store.get_pending_approval("persist1")
    assert got is not None
    assert got["owner"] == "bob"


def test_atomic_pop_double_fire(store_db):
    """순차 double-fire: 첫 pop 만 payload, 둘째는 None(이미 소비)."""
    store.save_pending_approval("dbl", {"owner": "x"})
    first = store.pop_pending_approval("dbl")
    second = store.pop_pending_approval("dbl")
    assert first is not None
    assert second is None


def test_concurrent_pop_single_winner(store_db):
    """동시 pop 8스레드 → 정확히 1개만 payload 획득(원자 DELETE RETURNING)."""
    store.save_pending_approval("race", {"owner": "y"})
    results = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def _pop():
        barrier.wait()
        r = store.pop_pending_approval("race")
        with lock:
            results.append(r)

    threads = [threading.Thread(target=_pop) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"원자성 위반 — 승자 {len(winners)}명"
    assert winners[0]["owner"] == "y"
