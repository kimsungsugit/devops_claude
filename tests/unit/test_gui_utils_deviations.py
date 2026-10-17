# tests/unit/test_gui_utils_deviations.py
"""deviation 저장소의 원자성·복사반환 (deep-review C2).

upsert/delete_deviation 은 load-modify-write 인데 lock 이 없어 동시 두 요청이 같은
목록을 읽고 각자 write → 하나가 소실(lost-update)됐다. 또 load_deviations 가 캐시된
리스트를 by-ref 로 반환해 호출자 변형이 캐시를 오염시켰다. ISO 26262 deviation(정적
분석 위반 수용 사유)의 감사기록이 사라지는 클래스다.
"""
from __future__ import annotations

import threading

from workflow.gui_utils import (
    delete_deviation,
    load_deviations,
    upsert_deviation,
)


def _rec(i: int) -> dict:
    return {"id": f"d{i}", "rule": "R", "file": "f.c", "line": i, "message": "m"}


def test_load_returns_copy_not_cached_reference(tmp_path):
    """load_deviations 반환값을 제자리 변형해도 캐시/후속 load 가 오염되지 않는다.

    뮤테이션: `return list(...)` 를 `return _DEVIATIONS_CACHE[key]`(by-ref)로 되돌리면
    주입이 캐시에 남아 실패한다.
    """
    upsert_deviation(tmp_path, _rec(1))
    got = load_deviations(tmp_path)            # 캐시 hit → 복사본이어야
    got.append({"id": "INJECTED"})             # 반환 리스트를 제자리 변형
    again = load_deviations(tmp_path)
    assert [d["id"] for d in again] == ["d1"], "by-ref 반환이라 캐시가 오염됐다"


def test_concurrent_upserts_no_lost_update(tmp_path):
    """동시 upsert 25건 — lock 없으면 last-writer-wins 로 일부 소실. 전부 살아야 한다.

    뮤테이션: upsert 의 `with _DEVIATIONS_LOCK:` 를 제거하면 lost-update 로 실패(확률적).
    """
    n = 25
    threads = [threading.Thread(target=upsert_deviation, args=(tmp_path, _rec(i))) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ids = {d["id"] for d in load_deviations(tmp_path, force=True)}
    assert ids == {f"d{i}" for i in range(n)}, f"lost-update: {n - len(ids)}건 소실"


def test_upsert_delete_roundtrip(tmp_path):
    upsert_deviation(tmp_path, _rec(1))
    upsert_deviation(tmp_path, _rec(2))
    assert delete_deviation(tmp_path, "d1") is True
    assert delete_deviation(tmp_path, "d1") is False   # 이미 없음
    ids = {d["id"] for d in load_deviations(tmp_path, force=True)}
    assert ids == {"d2"}
