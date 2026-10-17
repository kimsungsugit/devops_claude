"""`report_gen.atomic_io.replace_with_retry` — a Windows sharing violation on the rename is retried, nothing else.

The gate saw `users.add_user` fail with `PermissionError: [WinError 5]` on `users.json.tmp → users.json` in 2 of 3 runs:
a scanner opens the file written a moment before. The three auth stores (users, admins, approvers) share this rename.
"""
from __future__ import annotations

import pytest

from report_gen import atomic_io


@pytest.fixture
def fake_replace(monkeypatch):
    calls = {"n": 0, "fail": 0, "error": PermissionError}

    def replace(src, dst):
        calls["n"] += 1
        if calls["n"] <= calls["fail"]:
            raise calls["error"]("[WinError 5] denied")
    monkeypatch.setattr(atomic_io.os, "replace", replace)
    monkeypatch.setattr(atomic_io, "_REPLACE_DELAY_S", 0)
    return calls


def test_a_transient_sharing_violation_is_retried_on_windows(fake_replace, monkeypatch):
    monkeypatch.setattr(atomic_io, "_IS_WINDOWS", True)
    fake_replace["fail"] = 3
    atomic_io.replace_with_retry("a.tmp", "a")
    assert fake_replace["n"] == 4


def test_a_lasting_violation_is_raised_after_the_budget(fake_replace, monkeypatch):
    monkeypatch.setattr(atomic_io, "_IS_WINDOWS", True)
    fake_replace["fail"] = 10**6
    with pytest.raises(PermissionError):
        atomic_io.replace_with_retry("a.tmp", "a")
    assert fake_replace["n"] == atomic_io._REPLACE_ATTEMPTS


def test_elsewhere_a_permission_error_is_real_and_raised_at_once(fake_replace, monkeypatch):
    monkeypatch.setattr(atomic_io, "_IS_WINDOWS", False)
    fake_replace["fail"] = 1
    with pytest.raises(PermissionError):
        atomic_io.replace_with_retry("a.tmp", "a")
    assert fake_replace["n"] == 1


def test_other_errors_are_never_retried(fake_replace, monkeypatch):
    monkeypatch.setattr(atomic_io, "_IS_WINDOWS", True)
    fake_replace.update(fail=1, error=FileNotFoundError)
    with pytest.raises(FileNotFoundError):
        atomic_io.replace_with_retry("a.tmp", "a")
    assert fake_replace["n"] == 1


def test_the_auth_stores_rename_through_it(tmp_path, monkeypatch):
    from backend.services import admin_users, approvers, users
    seen = []
    monkeypatch.setattr(users, "replace_with_retry", lambda s, d: seen.append(("users", d)))
    monkeypatch.setattr(admin_users, "replace_with_retry", lambda s, d: seen.append(("admins", d)))
    monkeypatch.setattr(approvers, "replace_with_retry", lambda s, d: seen.append(("approvers", d)))
    for module in (users, admin_users, approvers):
        module._atomic_write(tmp_path / "x.json", {"schema_version": 1})
    assert [k for k, _d in seen] == ["users", "admins", "approvers"]
