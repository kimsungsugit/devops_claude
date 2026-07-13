from __future__ import annotations


def _isolate_locks(impact_audit, tmp_path, monkeypatch):
    """테스트별 락 격리. 락은 이제 **AUDIT_DIR 기준으로 scm별 지연 생성**되므로 AUDIT_DIR만
    tmp로 바꾸면 실제로 격리된다(과거엔 FileLock이 import 시점 repo 경로에 바인딩돼 monkeypatch가
    무시됐고, 그래서 테스트가 _RUN_FILE_LOCK을 직접 주입해야 했다 — 동시 실행 시 유령 실패의 원인).
    """
    import threading

    audit = tmp_path / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", audit)
    monkeypatch.setattr(impact_audit, "LOCK_PATH", audit / ".run_lock")  # legacy 참조 호환
    monkeypatch.setattr(impact_audit, "_RUN_FILE_LOCKS", {})
    monkeypatch.setattr(impact_audit, "_RUN_INTRA_LOCKS", {})
    monkeypatch.setattr(impact_audit, "_RUN_LOCKS_GUARD", threading.Lock())
    monkeypatch.setattr(impact_audit, "_RUN_LOCK_OWNERS", {})


def _lock_json(impact_audit, scm_id="hdpdm01"):
    """현재 AUDIT_DIR 기준 scm별 진단 JSON 경로."""
    return impact_audit.AUDIT_DIR / f".run_lock_{impact_audit._lock_key(scm_id)}.json"


def test_run_lock_acquire_release(tmp_path, monkeypatch):
    from workflow import impact_audit
    import threading

    _isolate_locks(impact_audit, tmp_path, monkeypatch)

    acquired = impact_audit.acquire_run_lock("hdpdm01")
    assert acquired["ok"] is True
    assert _lock_json(impact_audit).exists()
    assert acquired["lock"]["thread_id"] == threading.get_ident()

    released = impact_audit.release_run_lock()
    assert released is True
    assert not _lock_json(impact_audit).exists()


def test_run_lock_second_acquire_blocked_until_release(tmp_path, monkeypatch):
    """실행 수명 동안 락을 보유 — 해제 전 재획득은 active_lock, 해제 후 재획득 성공."""
    from workflow import impact_audit

    _isolate_locks(impact_audit, tmp_path, monkeypatch)

    first = impact_audit.acquire_run_lock("a")
    assert first["ok"] is True

    # 같은 scm은 차단(중복 실행 방지)
    second = impact_audit.acquire_run_lock("a")
    assert second["ok"] is False
    assert second["reason"] == "active_lock"

    # 다른 scm은 차단하지 않는다 — 락은 scm별. (과거엔 전역 단일 락이라 프로젝트 A 분석이
    # 프로젝트 B를 문서 자동생성 timeout(최대 1시간)까지 막았다.)
    other = impact_audit.acquire_run_lock("b")
    assert other["ok"] is True
    assert other["lock"]["scm_id"] == "b"

    assert impact_audit.release_run_lock() is True  # 이 스레드가 소유한 키 해제

    third = impact_audit.acquire_run_lock("c")
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
    _lock_json(impact_audit).write_text(
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
    _k = impact_audit._lock_key("owner")
    impact_audit._RUN_LOCK_OWNERS[_k] = -999
    assert impact_audit.release_run_lock() is False
    assert _lock_json(impact_audit, "owner").exists()  # 락 유지됨

    # 실제 소유자로 복구 후 정상 해제
    import threading
    impact_audit._RUN_LOCK_OWNERS[_k] = threading.get_ident()
    assert impact_audit.release_run_lock() is True


def test_write_impact_audit_creates_per_run_file(tmp_path, monkeypatch):
    from workflow import impact_audit

    monkeypatch.setattr(impact_audit, "AUDIT_DIR", tmp_path / "audit")

    out = impact_audit.write_impact_audit({"scm_id": "hdpdm01", "trigger": "local"})

    assert out.exists()
    assert out.name.startswith("impact_")
