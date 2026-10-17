"""(R48-a) 승인자 목록 `backend/services/approvers.py` — `config/approvers.json` CRUD + 판정.

admin_users 와 같은 패턴이라 같은 축을 잰다: 대소문자 무시 비교 · 원자 쓰기(LF) · mtime 캐시 무효화 ·
손상 파일은 비켜 두고 **빈 목록**(권한이 넓어지는 쪽으로 접히지 않는다) · `default` 는 절대 승인자가 아니다.
"""
from __future__ import annotations

import json
import threading

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    from backend.services import approvers as ap

    p = tmp_path / "approvers.json"
    monkeypatch.setattr(ap, "APPROVERS_PATH", p)
    try:
        from filelock import FileLock
        monkeypatch.setattr(ap, "_LOCK", FileLock(str(p) + ".lock", timeout=5))
    except ImportError:
        monkeypatch.setattr(ap, "_LOCK", threading.Lock())
    ap._cache["mtime"] = 0.0
    ap._cache["approvers"] = set()
    return p


class TestCrud:
    def test_empty_by_default_and_file_is_created(self, store):
        from backend.services import approvers as ap

        assert ap.load_approvers() == set()
        assert store.exists()
        assert json.loads(store.read_text(encoding="utf-8")) == {"approvers": [], "schema_version": 1}

    def test_add_is_case_insensitive_and_keeps_original_case(self, store):
        from backend.services import approvers as ap

        assert ap.add_approver("Reviewer01")["added"] is True
        assert ap.add_approver("reviewer01")["added"] is False
        assert ap.load_approvers() == {"Reviewer01"}
        assert ap.is_approver("REVIEWER01") is True
        assert ap.is_approver(" reviewer01 ") is True

    def test_remove(self, store):
        from backend.services import approvers as ap

        ap.add_approver("a")
        ap.add_approver("b")
        assert ap.remove_approver("A")["removed"] is True
        assert ap.remove_approver("zzz")["removed"] is False
        assert ap.load_approvers() == {"b"}
        assert ap.is_approver("a") is False

    def test_blank_and_default_are_never_approvers(self, store):
        from backend.services import approvers as ap

        ap.save_approvers(["default", "", "  "])
        assert ap.load_approvers() == {"default"}   # 저장은 되지만
        assert ap.is_approver("default") is False   # 판정은 항상 False (미들웨어의 '신원 없음' 토큰)
        assert ap.is_approver("") is False
        with pytest.raises(ValueError):
            ap.add_approver("  ")

    def test_file_is_written_with_lf_only(self, store):
        from backend.services import approvers as ap

        ap.add_approver("x")
        assert b"\r\n" not in store.read_bytes()


class TestCacheAndCorruption:
    def test_external_edit_is_picked_up_by_mtime(self, store):
        """운영 가이드가 허용하는 '파일 직접 편집' 이 재기동 없이 반영돼야 한다."""
        import os
        import time

        from backend.services import approvers as ap

        assert ap.is_approver("ext") is False
        store.write_text('{"approvers": ["ext"], "schema_version": 1}', encoding="utf-8")
        # mtime 해상도가 거친 파일시스템 대비 — 미래 시각으로 밀어 둔다.
        t = time.time() + 5
        os.utime(store, (t, t))
        assert ap.is_approver("ext") is True

    def test_corrupt_file_becomes_empty_list_and_is_backed_up(self, store, caplog):
        from backend.services import approvers as ap

        ap.add_approver("keep")
        store.write_text("{not json", encoding="utf-8")
        ap._cache["mtime"] = 0.0
        with caplog.at_level("WARNING"):
            assert ap.load_approvers() == set()
        assert store.with_suffix(".invalid.json").exists()
        assert json.loads(store.read_text(encoding="utf-8")) == {"approvers": [], "schema_version": 1}
        assert any("approvers.json" in r.getMessage() for r in caplog.records), "손상 사실이 로그에 남아야 한다"

    def test_non_dict_payload_is_empty(self, store):
        from backend.services import approvers as ap

        store.write_text('["a", "b"]', encoding="utf-8")
        ap._cache["mtime"] = 0.0
        assert ap.load_approvers() == set()
