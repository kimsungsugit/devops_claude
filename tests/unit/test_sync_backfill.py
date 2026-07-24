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
