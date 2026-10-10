# -*- coding: utf-8 -*-
"""캐시 single-flight — TTL 캐시만으로는 pile-up 을 못 막는다.

배경(2026-08-06 실측, KJPDS02_PV): `_VCAST_CLOUDIUM_PARSE_CACHE` 와 `_UDS_MAPPING_CACHE`
둘 다 락을 캐시 *조회*에만 걸고 비싼 작업은 락 밖에서 했다. 주석엔 각각

  - "동시 miss는 redundant parse 허용, 락 점유 최소화"
  - "재로드/연타 시 같은 파싱이 쌓여 worker/CPU 경합 → 타임아웃을 유발하므로 TTL 캐시로 막는다"

라고 적혀 있었는데, 후자가 말한 pile-up 을 **전자의 설계가 정확히 허용**하고 있었다.
cold key 에 동시 도착한 N개 요청은 전부 계산한다 — 캐시는 누가 먼저 끝낸 다음부터만 듣는다.
실측: cloudium VectorCAST 파싱 단독 233초 → 요청 둘이 겹치자 **460초**(워커가 하나라 경합).

이 파일이 고정하는 계약:
  A. 같은 키 동시 요청 → 실제 계산은 **1회**, 나머지는 그 결과를 쓴다
  B. **다른 키는 직렬화되지 않는다** ← 전역 단일 락으로 "고치면" A는 통과하고 B가 깨진다
  C. 예외가 나도 락이 풀린다(다음 요청이 hang 하지 않는다)

⚠ 스레드 테스트는 전부 timeout 을 준다. 이 저장소는 게이트가 hang 으로 죽은 전례가 있어
   실패는 반드시 **FAIL 로** 끝나야지 멈춰선 안 된다.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

import pytest

from backend.cache import KeyedBuildLocks

# 스레드 동기화 상한 — 넘으면 통과가 아니라 실패로 끝낸다.
T = 10.0


# ─────────────────────────────────────────────────────────────────────────────
# A. KeyedBuildLocks 단위 계약
# ─────────────────────────────────────────────────────────────────────────────

def _run_concurrently(fns, timeout: float = T) -> List[Any]:
    """fns 를 각각 스레드로 동시에 돌리고 결과를 순서대로 반환. 예외는 그대로 올린다."""
    results: List[Any] = [None] * len(fns)
    errors: List[BaseException] = []

    def _wrap(i, fn):
        try:
            results[i] = fn()
        except BaseException as e:  # noqa: BLE001 - 스레드 예외를 삼키면 테스트가 거짓 통과
            errors.append(e)

    threads = [threading.Thread(target=_wrap, args=(i, f)) for i, f in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout)
    alive = [t for t in threads if t.is_alive()]
    assert not alive, f"{len(alive)}개 스레드가 {timeout}s 안에 안 끝났다 (deadlock 의심)"
    if errors:
        raise errors[0]
    return results


def test_같은_키_동시요청은_계산을_한_번만_한다():
    locks = KeyedBuildLocks()
    cache: Dict[str, Any] = {}
    calls: List[int] = []
    entered = threading.Event()
    release = threading.Event()

    def build():
        calls.append(1)
        entered.set()
        # 두 번째 스레드가 확실히 락 앞에 줄 서도록 잡아 둔다.
        release.wait(T)
        cache["k"] = "value"
        return "value"

    def caller():
        return locks.run("k", lambda: cache.get("k"), build)

    def second():
        # 첫 스레드가 build 에 들어간 뒤 출발 — 그래야 "동시 miss" 가 재현된다.
        assert entered.wait(T), "leader 가 build 에 진입하지 않았다"
        release.set()
        return locker_result()

    def locker_result():
        return locks.run("k", lambda: cache.get("k"), build)

    out = _run_concurrently([caller, second])
    assert out == ["value", "value"]
    assert len(calls) == 1, f"build 가 {len(calls)}번 실행됐다 — single-flight 가 안 걸렸다"


def test_대기자는_리더의_결과를_그대로_쓴다():
    """재확인(double-check)이 없으면 직렬화만 하고 중복은 그대로 남는다 — 더 나빠진다."""
    locks = KeyedBuildLocks()
    cache: Dict[str, Any] = {}
    order: List[str] = []
    entered = threading.Event()
    release = threading.Event()

    def build_leader():
        order.append("leader")
        entered.set()
        release.wait(T)
        cache["k"] = {"n": 1}
        return cache["k"]

    def build_follower():
        order.append("follower")   # 여기 들어오면 재확인이 없다는 뜻
        cache["k"] = {"n": 2}
        return cache["k"]

    def leader():
        return locks.run("k", lambda: cache.get("k"), build_leader)

    def follower():
        assert entered.wait(T)
        release.set()
        return locks.run("k", lambda: cache.get("k"), build_follower)

    out = _run_concurrently([leader, follower])
    assert order == ["leader"], f"follower 가 계산했다: {order}"
    assert out[0] == out[1] == {"n": 1}


def test_다른_키는_서로를_막지_않는다():
    """전역 단일 락으로 '고치면' 여기서 깨진다 — 서로 다른 문서/폴더가 줄을 선다."""
    locks = KeyedBuildLocks()
    both_in = threading.Barrier(2)

    def build_for(_key):
        def _b():
            # 둘 다 동시에 build 안에 있어야 통과 — 직렬화면 timeout(BrokenBarrier).
            both_in.wait(timeout=T)
            return _key
        return _b

    def caller(key):
        return lambda: locks.run(key, lambda: None, build_for(key))

    out = _run_concurrently([caller("a"), caller("b")])
    assert sorted(out) == ["a", "b"]


def test_캐시_히트면_계산을_아예_안_한다():
    locks = KeyedBuildLocks()
    cache = {"k": "cached"}

    def build():
        raise AssertionError("캐시 히트인데 build 가 호출됐다")

    assert locks.run("k", lambda: cache.get("k"), build) == "cached"


def test_build_예외는_전파되고_락은_풀린다():
    """예외를 삼키면 실패가 숨고, 락을 안 풀면 이후 모든 요청이 영구 hang 한다."""
    locks = KeyedBuildLocks()

    def boom():
        raise RuntimeError("parse failed")

    with pytest.raises(RuntimeError, match="parse failed"):
        locks.run("k", lambda: None, boom)

    # 같은 키로 다시 — 락이 안 풀렸으면 여기서 멈춘다.
    done = threading.Event()

    def again():
        r = locks.run("k", lambda: None, lambda: "ok")
        done.set()
        return r

    assert _run_concurrently([again]) == ["ok"]
    assert done.is_set()


def test_키_상한_초과해도_동작한다():
    """상한 도달 시 락 dict 를 비운다 — 락은 최적화지 정확성 장치가 아니라 안전하다."""
    locks = KeyedBuildLocks(max_keys=2)
    for i in range(6):
        assert locks.run(f"k{i}", lambda: None, lambda i=i: i) == i


def test_falsy_결과도_캐시_히트로_인정한다():
    """빈 dict/0/'' 를 miss 로 오인하면 매번 재계산한다(계약: None 만 miss)."""
    locks = KeyedBuildLocks()
    calls: List[int] = []

    def build():
        calls.append(1)
        return {}

    cache: Dict[str, Any] = {}

    def cache_get():
        return cache.get("k")

    assert locks.run("k", cache_get, build) == {}
    cache["k"] = {}                      # 빈 결과를 캐시한 상태
    assert locks.run("k", cache_get, build) == {}
    assert len(calls) == 1, "빈 dict 캐시가 miss 로 취급돼 재계산됐다"


# ─────────────────────────────────────────────────────────────────────────────
# B. 실제 적용부 — jenkins.py 의 두 비싼 캐시
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def jenkins_mod():
    """캐시/락 전역을 저장·복원. ⚠ 특정 값으로 '고정'하지 말고 원래 값으로 되돌린다."""
    from backend.routers import jenkins as J

    saved_vcast = dict(J._VCAST_CLOUDIUM_PARSE_CACHE)
    saved_uds = dict(J._UDS_MAPPING_CACHE)
    saved_vlocks = J._VCAST_PARSE_BUILD_LOCKS
    saved_ulocks = J._UDS_MAPPING_BUILD_LOCKS
    J._VCAST_CLOUDIUM_PARSE_CACHE.clear()
    J._UDS_MAPPING_CACHE.clear()
    J._VCAST_PARSE_BUILD_LOCKS = KeyedBuildLocks(max_keys=32)
    J._UDS_MAPPING_BUILD_LOCKS = KeyedBuildLocks(max_keys=16)
    try:
        yield J
    finally:
        J._VCAST_CLOUDIUM_PARSE_CACHE.clear()
        J._VCAST_CLOUDIUM_PARSE_CACHE.update(saved_vcast)
        J._UDS_MAPPING_CACHE.clear()
        J._UDS_MAPPING_CACHE.update(saved_uds)
        J._VCAST_PARSE_BUILD_LOCKS = saved_vlocks
        J._UDS_MAPPING_BUILD_LOCKS = saved_ulocks


def test_vcast_폴더_파싱은_동시요청에도_한_번만_돈다(jenkins_mod, monkeypatch):
    J = jenkins_mod
    calls: List[str] = []
    entered = threading.Event()
    release = threading.Event()

    def fake_impl(p, key):
        calls.append(p)
        entered.set()
        release.wait(T)
        payload = {"test_rows": [{"subprogram": "f"}], "source_folder": p}
        # 실제 impl 과 동일하게 성공 결과를 캐시에 넣는다(대기자가 이걸 받아야 한다).
        with J._VCAST_CLOUDIUM_PARSE_LOCK:
            J._VCAST_CLOUDIUM_PARSE_CACHE[key] = (time.time(), payload)
        return dict(payload)

    monkeypatch.setattr(J, "_parse_vcast_logs_from_cloudium_folder_impl", fake_impl)
    path = "U:/x/VC_REPORT"

    def first():
        return J._parse_vcast_logs_from_cloudium_folder(path)

    def second():
        assert entered.wait(T)
        release.set()
        return J._parse_vcast_logs_from_cloudium_folder(path)

    out = _run_concurrently([first, second])
    assert len(calls) == 1, f"같은 폴더를 {len(calls)}번 파싱했다"
    assert out[0]["test_rows"] == out[1]["test_rows"] == [{"subprogram": "f"}]


def test_vcast_대소문자_슬래시_다른_같은_폴더도_한_번만_돈다(jenkins_mod, monkeypatch):
    """키 정규화가 깨지면 single-flight 도 캐시도 동시에 죽는다."""
    J = jenkins_mod
    calls: List[str] = []

    def fake_impl(p, key):
        calls.append(key)
        payload = {"test_rows": [1]}
        with J._VCAST_CLOUDIUM_PARSE_LOCK:
            J._VCAST_CLOUDIUM_PARSE_CACHE[key] = (time.time(), payload)
        return dict(payload)

    monkeypatch.setattr(J, "_parse_vcast_logs_from_cloudium_folder_impl", fake_impl)
    J._parse_vcast_logs_from_cloudium_folder("U:/x/VC_REPORT")
    J._parse_vcast_logs_from_cloudium_folder("U:\\x\\vc_report\\")
    assert len(calls) == 1, f"같은 폴더가 다른 키로 갈렸다: {calls}"


def test_uds_매핑은_동시요청에도_한_번만_파싱한다(jenkins_mod, monkeypatch):
    J = jenkins_mod
    calls: List[str] = []
    entered = threading.Event()
    release = threading.Event()

    monkeypatch.setattr(
        "backend.services.resolver_helpers.enforce_resolver_access", lambda _p: None
    )

    def fake_impl(uds_path, ck):
        calls.append(uds_path)
        entered.set()
        release.wait(T)
        result = {"mapping_pairs": [{"requirement_id": "SwTR_0101"}], "all_function_ids": ["SwUFn_1"]}
        with J._UDS_MAPPING_LOCK:
            J._UDS_MAPPING_CACHE[ck] = (time.time(), result)
        return dict(result)

    monkeypatch.setattr(J, "_jenkins_uds_extract_mapping_impl", fake_impl)
    body = {"uds_path": "U:/x/UDS.docx"}

    def first():
        return J.jenkins_uds_extract_mapping(dict(body))

    def second():
        assert entered.wait(T)
        release.set()
        return J.jenkins_uds_extract_mapping(dict(body))

    out = _run_concurrently([first, second])
    assert len(calls) == 1, f"같은 UDS 를 {len(calls)}번 파싱했다"
    assert out[0]["mapping_pairs"] == out[1]["mapping_pairs"]


def test_uds_서로_다른_문서는_병렬로_진행된다(jenkins_mod, monkeypatch):
    """전역 락으로 만들면 여기서 깨진다 — 프로젝트가 다른 두 문서가 줄을 선다."""
    J = jenkins_mod
    both_in = threading.Barrier(2)
    monkeypatch.setattr(
        "backend.services.resolver_helpers.enforce_resolver_access", lambda _p: None
    )

    def fake_impl(uds_path, ck):
        both_in.wait(timeout=T)
        return {"mapping_pairs": [], "uds_path": uds_path}

    monkeypatch.setattr(J, "_jenkins_uds_extract_mapping_impl", fake_impl)
    out = _run_concurrently([
        lambda: J.jenkins_uds_extract_mapping({"uds_path": "U:/a/A.docx"}),
        lambda: J.jenkins_uds_extract_mapping({"uds_path": "U:/b/B.docx"}),
    ])
    assert sorted(r["uds_path"] for r in out) == ["U:/a/A.docx", "U:/b/B.docx"]


def test_uds_경로_누락은_여전히_400(jenkins_mod):
    """single-flight 를 앞에 끼우면서 검증이 뒤로 밀리지 않았는지."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        jenkins_mod.jenkins_uds_extract_mapping({"uds_path": "  "})
    assert ei.value.status_code == 400


def test_uds_캐시_히트는_impl을_부르지_않는다(jenkins_mod, monkeypatch):
    J = jenkins_mod
    monkeypatch.setattr(
        "backend.services.resolver_helpers.enforce_resolver_access", lambda _p: None
    )

    def boom(*_a, **_k):
        raise AssertionError("캐시 히트인데 impl 이 호출됐다")

    monkeypatch.setattr(J, "_jenkins_uds_extract_mapping_impl", boom)
    ck = J._UDS_MAPPING_SCHEMA_VERSION + ":" + "u:/x/uds.docx"
    with J._UDS_MAPPING_LOCK:
        J._UDS_MAPPING_CACHE[ck] = (time.time(), {"mapping_pairs": ["cached"]})
    assert J.jenkins_uds_extract_mapping({"uds_path": "U:/X/UDS.docx"})["mapping_pairs"] == ["cached"]


def test_uds_TTL_만료분은_다시_계산한다(jenkins_mod, monkeypatch):
    """single-flight 를 넣으면서 TTL 을 무력화하면 stale 을 영구히 반환한다."""
    J = jenkins_mod
    monkeypatch.setattr(
        "backend.services.resolver_helpers.enforce_resolver_access", lambda _p: None
    )
    monkeypatch.setattr(
        J, "_jenkins_uds_extract_mapping_impl", lambda p, ck: {"mapping_pairs": ["fresh"]}
    )
    ck = J._UDS_MAPPING_SCHEMA_VERSION + ":" + "u:/x/uds.docx"
    with J._UDS_MAPPING_LOCK:
        J._UDS_MAPPING_CACHE[ck] = (time.time() - J._UDS_MAPPING_TTL - 1, {"mapping_pairs": ["stale"]})
    assert J.jenkins_uds_extract_mapping({"uds_path": "U:/X/UDS.docx"})["mapping_pairs"] == ["fresh"]
