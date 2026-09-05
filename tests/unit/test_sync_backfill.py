"""sync_backfill — 과거 빌드 일괄 캐시. 빌드별 실패 격리·중복 거부·Jenkins 미도달 정직."""
from __future__ import annotations

import time


def _wait_done(job_id: str, timeout: float = 5.0) -> dict:
    from backend.services.sync_backfill import backfill_status

    deadline = time.time() + timeout
    while time.time() < deadline:
        st = backfill_status(job_id)
        if st and st["state"] != "running":
            return st
        time.sleep(0.02)
    raise AssertionError("backfill did not finish in time")


def test_per_build_error_isolated(tmp_path, monkeypatch):
    """한 빌드의 sync 실패가 나머지를 죽이지 않고 per_build에 정직 기록된다."""
    from backend.services import sync_backfill

    calls = []

    def fake_sync(**kw):
        num = int(kw["build_selector"])
        calls.append(num)
        if num == 124:
            raise RuntimeError("artifact download failed")
        rd = tmp_path / f"b{num}" / "report"
        rd.mkdir(parents=True, exist_ok=True)
        return {}, tmp_path / f"b{num}", rd, [], []

    monkeypatch.setattr("backend.services.jenkins_service.sync_jenkins_artifacts", fake_sync)
    started = sync_backfill.start_backfill(
        job_url="http://j/job/X/", username="u", api_token="t", cache_root=tmp_path,
        verify_tls=True, patterns=[], build_numbers=[125, 124, 122],
    )
    assert started["accepted"] is True
    st = _wait_done(started["job_id"])
    assert st["state"] == "done_with_errors"
    assert calls == [125, 124, 122]  # 실패 후에도 계속
    by = {e["build_number"]: e for e in st["per_build"]}
    assert by[125]["status"] == "ok" and by[125]["reports_dir"]
    assert by[124]["status"] == "error" and "artifact download failed" in by[124]["error"]
    assert by[122]["status"] == "ok"
    assert st["completed"] == 3 and st["finished_at"]


def test_duplicate_job_rejected_and_released_after_done(tmp_path, monkeypatch):
    import threading

    from backend.services import sync_backfill

    gate = threading.Event()

    def slow_sync(**kw):
        gate.wait(timeout=3)
        rd = tmp_path / "b" / "report"
        rd.mkdir(parents=True, exist_ok=True)
        return {}, tmp_path / "b", rd, [], []

    monkeypatch.setattr("backend.services.jenkins_service.sync_jenkins_artifacts", slow_sync)
    first = sync_backfill.start_backfill(
        job_url="http://j/job/Y/", username="u", api_token="t", cache_root=tmp_path,
        verify_tls=True, patterns=[], build_numbers=[1],
    )
    assert first["accepted"] is True
    dup = sync_backfill.start_backfill(
        job_url="http://j/job/Y/", username="u", api_token="t", cache_root=tmp_path,
        verify_tls=True, patterns=[], build_numbers=[2],
    )
    assert dup["accepted"] is False and dup["reason"] == "backfill_already_running"
    assert dup["job_id"] == first["job_id"]
    gate.set()
    _wait_done(first["job_id"])
    assert sync_backfill.active_job_for("http://j/job/Y/") is None  # 완료 후 락 해제


def test_endpoint_jenkins_unreachable_honest(tmp_path, monkeypatch):
    """빌드 번호 자동 해석이 Jenkins 미도달이면 available:false + 사유(캐시 위장 금지)."""
    from backend.routers import summary_insight as si

    def boom(**kw):
        raise ConnectionError("no route to host")

    monkeypatch.setattr("backend.services.sync_backfill.resolve_recent_build_numbers", boom)
    resp = si.jenkins_sync_backfill({"job_url": "http://j/job/X/", "cache_root": str(tmp_path)})
    assert resp["available"] is False and resp["reason"] == "jenkins_unreachable"
    assert "ConnectionError" in resp["detail"]


def test_endpoint_skip_cached_and_nothing_to_backfill(tmp_path, monkeypatch):
    from backend.routers import summary_insight as si

    monkeypatch.setattr(
        "backend.services.build_inventory.list_cached_builds_meta",
        lambda **k: [{"build_number": 125}, {"build_number": 124}],
    )
    resp = si.jenkins_sync_backfill(
        {"job_url": "http://j/job/X/", "cache_root": str(tmp_path), "build_numbers": [125, 124]}
    )
    assert resp["available"] is False and resp["reason"] == "nothing_to_backfill"
    assert resp["skipped_cached"] == [124, 125]

    captured = {}

    def fake_start(**kw):
        captured.update(kw)
        return {"accepted": True, "job_id": "jid"}

    monkeypatch.setattr("backend.services.sync_backfill.start_backfill", fake_start)
    resp2 = si.jenkins_sync_backfill(
        {"job_url": "http://j/job/X/", "cache_root": str(tmp_path), "build_numbers": [125, 123, 122]}
    )
    assert resp2["available"] is True
    assert resp2["accepted"] == [123, 122]      # 캐시된 125 스킵
    assert resp2["skipped_cached"] == [125]
    assert captured["build_numbers"] == [123, 122]


def test_status_endpoint_unknown_job():
    from backend.routers import summary_insight as si

    resp = si.jenkins_sync_backfill_status("nope")
    assert resp["available"] is False and resp["reason"] == "unknown_job_id"


# ── 스냅샷 고정(pin_source) + 함수 축 warm(warm_matrix) ─────────────────────────


def test_pin_source_forwarded_to_sync_and_recorded(tmp_path, monkeypatch):
    """pin_source가 sync_jenkins_artifacts까지 전달되고 빌드별 revision 출처가 기록된다."""
    from backend.services import sync_backfill

    seen = []

    def fake_sync(**kw):
        seen.append(kw.get("pin_source_revision"))
        rd = tmp_path / "report"
        rd.mkdir(parents=True, exist_ok=True)
        return (
            {"checkout": {"revision": "1042", "revision_source": "svn_date", "pin_error": ""}},
            tmp_path, rd, [], [],
        )

    monkeypatch.setattr("backend.services.jenkins_service.sync_jenkins_artifacts", fake_sync)
    started = sync_backfill.start_backfill(
        job_url="http://j/job/P/", username="u", api_token="t", cache_root=tmp_path,
        verify_tls=True, patterns=[], build_numbers=[125, 124], pin_source=True,
    )
    st = _wait_done(started["job_id"])
    assert seen == [True, True]
    assert st["pin_source"] is True
    by = {e["build_number"]: e for e in st["per_build"]}
    assert by[125]["revision"] == "1042" and by[125]["revision_source"] == "svn_date"


def test_pin_failure_reported_not_swallowed(tmp_path, monkeypatch):
    """revision 고정 실패는 HEAD로 진행하되 status=pin_failed로 정직 보고(성공 위장 금지)."""
    from backend.services import sync_backfill

    def fake_sync(**kw):
        rd = tmp_path / "report"
        rd.mkdir(parents=True, exist_ok=True)
        return (
            {"checkout": {"revision": "", "revision_source": "head",
                          "pin_error": "svn info -r failed"}},
            tmp_path, rd, [], [],
        )

    monkeypatch.setattr("backend.services.jenkins_service.sync_jenkins_artifacts", fake_sync)
    started = sync_backfill.start_backfill(
        job_url="http://j/job/Q/", username="u", api_token="t", cache_root=tmp_path,
        verify_tls=True, patterns=[], build_numbers=[110], pin_source=True,
    )
    st = _wait_done(started["job_id"])
    entry = st["per_build"][0]
    assert entry["status"] == "pin_failed"
    assert "svn info -r failed" in entry["error"]
    # pin 실패는 sync 자체의 실패가 아니므로 잡 전체는 done (아티팩트는 정상 캐시됨)
    assert st["state"] == "done"


def test_warm_matrix_computes_pending_cells_only(tmp_path, monkeypatch):
    """warm_matrix는 pending_cells만 계산한다 — 동일 트리 dedup 뒤 남은 쌍만."""
    from backend.routers import summary_insight as si
    from backend.services import sync_backfill

    def fake_sync(**kw):
        rd = tmp_path / "report"
        rd.mkdir(parents=True, exist_ok=True)
        return {"checkout": {}}, tmp_path, rd, [], []

    monkeypatch.setattr("backend.services.jenkins_service.sync_jenkins_artifacts", fake_sync)
    monkeypatch.setattr(si, "summary_change_matrix", lambda body: {
        "available": True, "baseline": {"build_number": 77},
        "pending_cells": [{"cell_id": "c1", "target_build": 122},
                          {"cell_id": "c2", "target_build": 124}],
    })
    targets = []
    monkeypatch.setattr(si, "summary_change_matrix_cell", lambda body: (
        targets.append(body.get("target_build")) or {"available": True}
    ))
    started = sync_backfill.start_backfill(
        job_url="http://j/job/R/", username="u", api_token="t", cache_root=tmp_path,
        verify_tls=True, patterns=[], build_numbers=[125], warm_matrix=True, baseline_build=77,
    )
    st = _wait_done(started["job_id"])
    assert targets == [122, 124]
    assert st["matrix"]["state"] == "done"
    assert st["matrix"]["total"] == 2 and st["matrix"]["completed"] == 2
    assert st["matrix"]["baseline_build"] == 77
    assert st["phase"] == "finished"


def test_warm_matrix_cell_failure_isolated(tmp_path, monkeypatch):
    """셀 1개 실패가 나머지를 죽이지 않고 matrix.errors에 기록된다."""
    from backend.routers import summary_insight as si
    from backend.services import sync_backfill

    def fake_sync(**kw):
        rd = tmp_path / "report"
        rd.mkdir(parents=True, exist_ok=True)
        return {"checkout": {}}, tmp_path, rd, [], []

    def flaky(body):
        if body.get("target_build") == 124:
            raise RuntimeError("parse blew up")
        return {"available": True}

    monkeypatch.setattr("backend.services.jenkins_service.sync_jenkins_artifacts", fake_sync)
    monkeypatch.setattr(si, "summary_change_matrix", lambda body: {
        "available": True, "baseline": {"build_number": 77},
        "pending_cells": [{"target_build": 122}, {"target_build": 124}, {"target_build": 125}],
    })
    monkeypatch.setattr(si, "summary_change_matrix_cell", flaky)
    started = sync_backfill.start_backfill(
        job_url="http://j/job/S/", username="u", api_token="t", cache_root=tmp_path,
        verify_tls=True, patterns=[], build_numbers=[125], warm_matrix=True,
    )
    st = _wait_done(started["job_id"])
    assert st["matrix"]["completed"] == 3          # 실패 후에도 계속
    assert st["matrix"]["state"] == "done_with_errors"
    assert [e["target_build"] for e in st["matrix"]["errors"]] == [124]


def test_warm_matrix_unavailable_is_skipped_not_error(tmp_path, monkeypatch):
    """스냅샷이 없어 매트릭스를 만들 수 없으면 skipped + 사유 — 실패로 위장하지 않는다."""
    from backend.routers import summary_insight as si
    from backend.services import sync_backfill

    def fake_sync(**kw):
        rd = tmp_path / "report"
        rd.mkdir(parents=True, exist_ok=True)
        return {"checkout": {}}, tmp_path, rd, [], []

    monkeypatch.setattr("backend.services.jenkins_service.sync_jenkins_artifacts", fake_sync)
    monkeypatch.setattr(si, "summary_change_matrix",
                        lambda body: {"available": False, "reason": "no_source_snapshot"})
    started = sync_backfill.start_backfill(
        job_url="http://j/job/T/", username="u", api_token="t", cache_root=tmp_path,
        verify_tls=True, patterns=[], build_numbers=[125], warm_matrix=True,
    )
    st = _wait_done(started["job_id"])
    assert st["matrix"] == {"state": "skipped", "reason": "no_source_snapshot"}
    assert st["state"] == "done"


def test_endpoint_pin_source_reprocesses_unpinned_cached_builds(tmp_path, monkeypatch):
    """pin_source면 '캐시됨'만으로 skip하지 않는다 — 미고정 스냅샷은 재수집 대상.

    이 가드가 없으면 HEAD로 받아둔 잘못된 트리가 영원히 남아 고정 토글이 무력화된다.
    """
    from backend.routers import summary_insight as si

    monkeypatch.setattr(
        "backend.services.build_inventory.list_cached_builds_meta",
        lambda **k: [
            {"build_number": 125, "source_pinned": True},    # 이미 고정 → skip
            {"build_number": 124, "source_pinned": False},   # HEAD 트리 → 재수집
            {"build_number": 122, "source_pinned": False},
        ],
    )
    captured = {}
    monkeypatch.setattr("backend.services.sync_backfill.start_backfill",
                        lambda **kw: (captured.update(kw), {"accepted": True, "job_id": "jid"})[1])

    resp = si.jenkins_sync_backfill({
        "job_url": "http://j/job/X/", "cache_root": str(tmp_path),
        "build_numbers": [125, 124, 122], "pin_source": True,
        "warm_matrix": True, "baseline_build": 122,
    })
    assert resp["available"] is True
    assert resp["accepted"] == [124, 122] and resp["skipped_cached"] == [125]
    assert captured["pin_source"] is True and captured["warm_matrix"] is True
    assert captured["baseline_build"] == 122

    # 대조군: pin_source 없이는 종전대로 캐시된 빌드를 전부 skip한다(회귀 방지)
    resp2 = si.jenkins_sync_backfill({
        "job_url": "http://j/job/X/", "cache_root": str(tmp_path),
        "build_numbers": [125, 124, 122],
    })
    assert resp2["available"] is False and resp2["reason"] == "nothing_to_backfill"
