"""svn --password-from-stdin 분기 검증.

핵심 계약:
  1. subversion이 --password-from-stdin을 지원하면 password는 argv에서
     사라지고 stdin으로 전달된다.
  2. 미지원 환경에서는 종전처럼 argv fallback을 쓰되, password는 그대로
     전달되어야 한다 (기능은 유지).
  3. svn_info_url도 동일 규칙을 따른다.
"""
from __future__ import annotations

from typing import Any, Dict, List


class _FakeCompleted:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _patch_local_service(monkeypatch, *, help_supports_stdin: bool):
    """Reset the feature-detection cache and stub subprocess.run.

    The stub captures every call so tests can assert on argv and stdin_input.
    """
    from backend.services import local_service

    monkeypatch.setattr(local_service, "_SVN_STDIN_SUPPORT_CACHE", None)

    calls: List[Dict[str, Any]] = []
    help_output = (
        "Valid options:\n"
        "  --username ARG\n"
        "  --password ARG\n"
        "  --password-from-stdin\n"
        "  --non-interactive\n"
        if help_supports_stdin
        else (
            "Valid options:\n"
            "  --username ARG\n"
            "  --password ARG\n"
            "  --non-interactive\n"
        )
    )

    def fake_run(args, **kwargs):
        calls.append({"args": list(args), "kwargs": dict(kwargs)})
        if args and args[0] == "svn" and len(args) > 1 and args[1] == "help":
            return _FakeCompleted(stdout=help_output)
        # checkout/info return ok with no output
        return _FakeCompleted(stdout="", returncode=0)

    monkeypatch.setattr(local_service.subprocess, "run", fake_run)
    return calls


def test_run_svn_uses_stdin_when_supported(tmp_path, monkeypatch):
    from backend.services import local_service

    calls = _patch_local_service(monkeypatch, help_supports_stdin=True)

    result = local_service.run_svn(
        project_root=str(tmp_path),
        workdir_rel="source",
        action="checkout",
        repo_url="svn://host/repo",
        revision="123",
        username="u",
        password="SECRET_PW",
    )

    assert result["rc"] == 0
    checkout_calls = [c for c in calls if c["args"][:2] == ["svn", "checkout"]]
    assert len(checkout_calls) == 1
    argv = checkout_calls[0]["args"]
    # Password must NOT appear anywhere in argv.
    assert "SECRET_PW" not in argv, f"password leaked into argv: {argv}"
    assert "--password-from-stdin" in argv
    assert "--password" not in argv
    # And it must have been piped on stdin.
    assert checkout_calls[0]["kwargs"].get("input") == "SECRET_PW"


def test_run_svn_falls_back_to_argv_when_unsupported(tmp_path, monkeypatch):
    from backend.services import local_service

    calls = _patch_local_service(monkeypatch, help_supports_stdin=False)

    result = local_service.run_svn(
        project_root=str(tmp_path),
        workdir_rel="source",
        action="checkout",
        repo_url="svn://host/repo",
        username="u",
        password="SECRET_PW",
    )

    assert result["rc"] == 0
    checkout_calls = [c for c in calls if c["args"][:2] == ["svn", "checkout"]]
    assert len(checkout_calls) == 1
    argv = checkout_calls[0]["args"]
    # Legacy mode — password is on argv (documented limitation).
    assert "--password" in argv
    assert "SECRET_PW" in argv
    assert "--password-from-stdin" not in argv
    assert checkout_calls[0]["kwargs"].get("input") is None


def test_run_svn_without_password_adds_no_flags(tmp_path, monkeypatch):
    """When no password is provided (cached auth / anon repo) we must not
    invent flags."""
    from backend.services import local_service

    calls = _patch_local_service(monkeypatch, help_supports_stdin=True)

    local_service.run_svn(
        project_root=str(tmp_path),
        workdir_rel="source",
        action="checkout",
        repo_url="svn://host/repo",
    )

    checkout = next(c for c in calls if c["args"][:2] == ["svn", "checkout"])
    argv = checkout["args"]
    assert "--password" not in argv
    assert "--password-from-stdin" not in argv
    assert checkout["kwargs"].get("input") is None


def test_svn_info_url_uses_stdin_when_supported(monkeypatch):
    from backend.services import local_service

    calls = _patch_local_service(monkeypatch, help_supports_stdin=True)

    result = local_service.svn_info_url(
        repo_url="svn://host/repo",
        username="u",
        password="PW_INFO",
    )

    assert result["rc"] == 0
    info_calls = [c for c in calls if c["args"][:2] == ["svn", "info"]]
    assert len(info_calls) == 1
    argv = info_calls[0]["args"]
    assert "PW_INFO" not in argv
    assert "--password-from-stdin" in argv
    assert info_calls[0]["kwargs"].get("input") == "PW_INFO"


def test_feature_detection_is_cached(monkeypatch):
    """The feature probe must run at most once per process to avoid the
    cost of spawning `svn help checkout` on every checkout."""
    from backend.services import local_service

    calls = _patch_local_service(monkeypatch, help_supports_stdin=True)

    for _ in range(5):
        local_service._svn_supports_password_stdin()

    help_calls = [c for c in calls if c["args"][:2] == ["svn", "help"]]
    assert len(help_calls) == 1


# ── P2/P4: password sanitization ───────────────────────────────────────

def test_run_svn_strips_whitespace_in_stdin_path(tmp_path, monkeypatch):
    """A password with trailing \\n (common env-var pitfall) must be trimmed
    identically on the argv and stdin branches — otherwise svn sees two
    different values depending on the client version."""
    from backend.services import local_service

    calls = _patch_local_service(monkeypatch, help_supports_stdin=True)
    local_service.run_svn(
        project_root=str(tmp_path),
        workdir_rel="source",
        action="checkout",
        repo_url="svn://host/repo",
        username="u",
        password="  SECRET_PW  \n",
    )
    checkout = next(c for c in calls if c["args"][:2] == ["svn", "checkout"])
    assert checkout["kwargs"].get("input") == "SECRET_PW"


def test_run_svn_strips_whitespace_in_argv_path(tmp_path, monkeypatch):
    from backend.services import local_service

    calls = _patch_local_service(monkeypatch, help_supports_stdin=False)
    local_service.run_svn(
        project_root=str(tmp_path),
        workdir_rel="source",
        action="checkout",
        repo_url="svn://host/repo",
        username="u",
        password="  SECRET_PW  \n",
    )
    checkout = next(c for c in calls if c["args"][:2] == ["svn", "checkout"])
    argv = checkout["args"]
    # The trimmed value lands in argv, never the padded/newline version.
    assert "SECRET_PW" in argv
    assert "  SECRET_PW  \n" not in argv


def test_run_svn_rejects_password_with_embedded_newline(tmp_path, monkeypatch):
    """An internal \\n inside the password is ambiguous for --password-from-stdin
    and a classic injection shape for argv; refuse rather than guess."""
    from backend.services import local_service

    calls = _patch_local_service(monkeypatch, help_supports_stdin=True)
    result = local_service.run_svn(
        project_root=str(tmp_path),
        workdir_rel="source",
        action="checkout",
        repo_url="svn://host/repo",
        username="u",
        password="line1\nline2",
    )
    assert result["rc"] == 1
    assert "newline" in result["output"].lower()
    # svn checkout must NOT have been invoked at all.
    assert not any(c["args"][:2] == ["svn", "checkout"] for c in calls)


def test_svn_info_url_rejects_password_with_embedded_newline(monkeypatch):
    from backend.services import local_service

    calls = _patch_local_service(monkeypatch, help_supports_stdin=True)
    result = local_service.svn_info_url(
        repo_url="svn://host/repo",
        username="u",
        password="a\r\nb",
    )
    assert result["rc"] == 1
    assert "newline" in result["output"].lower()
    assert not any(c["args"][:2] == ["svn", "info"] for c in calls)


# ── P1: encoding safety ────────────────────────────────────────────────

def test_run_cmd_uses_utf8_with_replace(monkeypatch):
    """subprocess.run must be called with encoding='utf-8', errors='replace'
    so localized svn output on non-UTF-8 locales never raises
    UnicodeDecodeError."""
    from backend.services import local_service

    captured = {}

    class _R:
        stdout = ""
        stderr = ""
        returncode = 0

    def fake_run(args, **kwargs):
        captured.update(kwargs)
        return _R()

    monkeypatch.setattr(local_service.subprocess, "run", fake_run)
    local_service._run_cmd(["echo", "hi"], cwd=local_service.Path("."))

    assert captured.get("encoding") == "utf-8"
    assert captured.get("errors") == "replace"
    assert captured.get("text") is True
