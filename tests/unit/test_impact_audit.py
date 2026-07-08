from __future__ import annotations


def _isolate_locks(impact_audit, tmp_path, monkeypatch):
    """테스트별로 락 상태를 격리 — 실제 프로세스 락/소유자 전역을 건드리지 않는다.

    filelock 설치 여부와 무관하게 동작하도록 모듈의 FileLock 속성을 그대로 사용(미설치면 None →
    threading.Lock 폴백, 프로덕션과 동일 경로)."""
    import threading

    audit = tmp_path / "audit"
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", audit)
    monkeypatch.setattr(impact_audit, "LOCK_PATH", audit / ".run_lock")
    if impact_audit.FileLock:
        audit.mkdir(parents=True, exist_ok=True)
        fresh_file_lock = impact_audit.FileLock(str(audit / ".run_lock.flock"), timeout=5)
    else:
        fresh_file_lock = threading.Lock()
    monkeypatch.setattr(impact_audit, "_RUN_FILE_LOCK", fresh_file_lock)
    monkeypatch.setattr(impact_audit, "_RUN_INTRA_LOCK", threading.Lock())
    monkeypatch.setattr(impact_audit, "_RUN_LOCK_OWNER", {"tid": None})


def test_run_lock_acquire_release(tmp_path, monkeypatch):
    from workflow import impact_audit
    import threading

    _isolate_locks(impact_audit, tmp_path, monkeypatch)

    acquired = impact_audit.acquire_run_lock("hdpdm01")
    assert acquired["ok"] is True
    assert impact_audit.LOCK_PATH.exists()
    assert acquired["lock"]["thread_id"] == threading.get_ident()

    released = impact_audit.release_run_lock()
    assert released is True
    assert not impact_audit.LOCK_PATH.exists()


def test_run_lock_second_acquire_blocked_until_release(tmp_path, monkeypatch):
    """실행 수명 동안 락을 보유 — 해제 전 재획득은 active_lock, 해제 후 재획득 성공."""
    from workflow import impact_audit

    _isolate_locks(impact_audit, tmp_path, monkeypatch)

    first = impact_audit.acquire_run_lock("a")
    assert first["ok"] is True

    second = impact_audit.acquire_run_lock("b")  # 아직 해제 안 함
    assert second["ok"] is False
    assert second["reason"] == "active_lock"

    assert impact_audit.release_run_lock() is True

    third = impact_audit.acquire_run_lock("c")  # 이제 가능
    assert third["ok"] is True
    assert third["lock"]["scm_id"] == "c"
    impact_audit.release_run_lock()


def test_run_lock_stale_file_without_held_lock_is_reclaimed(tmp_path, monkeypatch):
    """crash한 홀더가 남긴 .run_lock 파일이 있어도, 락(flock)이 비어 있으면 재획득 성공(overwrite).

    새 설계에서 뮤텍스는 FileLock/OS가 담당하므로, 잔존 메타데이터 파일은 회수를 막지 않는다.
    """
    from workflow import impact_audit

    _isolate_locks(impact_audit, tmp_path, monkeypatch)
    impact_audit.ensure_audit_dir()
    impact_audit.LOCK_PATH.write_text(
        '{"scm_id":"old","pid":999999,"thread_id":1,"started_at":"2026-03-20T00:00:00"}',
        encoding="utf-8",
    )

    acquired = impact_audit.acquire_run_lock("new")

    assert acquired["ok"] is True
    assert acquired["lock"]["scm_id"] == "new"
    impact_audit.release_run_lock()


def test_run_lock_release_by_non_owner_is_noop(tmp_path, monkeypatch):
    """소유 스레드가 아닌 곳(실패한 acquire의 finally 등)에서의 release는 남의 락을 풀지 않는다."""
    from workflow import impact_audit

    _isolate_locks(impact_audit, tmp_path, monkeypatch)

    acquired = impact_audit.acquire_run_lock("owner")
    assert acquired["ok"] is True

    # 다른 소유자가 쥐고 있는 것처럼 위장 → release는 no-op이어야 함
    impact_audit._RUN_LOCK_OWNER["tid"] = -999
    assert impact_audit.release_run_lock() is False
    assert impact_audit.LOCK_PATH.exists()  # 락 유지됨

    # 실제 소유자로 복구 후 정상 해제
    import threading
    impact_audit._RUN_LOCK_OWNER["tid"] = threading.get_ident()
    assert impact_audit.release_run_lock() is True


def test_write_impact_audit_creates_per_run_file(tmp_path, monkeypatch):
    from workflow import impact_audit

    monkeypatch.setattr(impact_audit, "AUDIT_DIR", tmp_path / "audit")

    out = impact_audit.write_impact_audit({"scm_id": "hdpdm01", "trigger": "local"})

    assert out.exists()
    assert out.name.startswith("impact_")
