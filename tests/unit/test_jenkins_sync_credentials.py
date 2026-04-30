"""ensure_source_checkout credential propagation tests.

These tests verify that SCM credentials resolved via the registry + env fallback
actually reach the `run_svn` / `run_git` call. `svn`/`git` binaries are never
invoked — we monkeypatch both and the Jenkins client.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


class _StubClient:
    def __init__(self, meta: Dict[str, Any]):
        self._meta = meta

    def get_scm_meta(self, *, build_selector: str) -> Dict[str, Any]:  # noqa: D401
        return self._meta


def _seed_registry(tmp_path, monkeypatch, **entry) -> None:
    from backend.schemas import ScmLinkedDocs, ScmRegisterRequest
    from backend.services import scm_registry

    monkeypatch.setattr(
        scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json"
    )
    scm_registry.register_entry(
        ScmRegisterRequest(
            id=entry["id"],
            name=entry.get("name", entry["id"]),
            scm_type=entry.get("scm_type", "svn"),
            scm_url=entry.get("scm_url", ""),
            scm_username=entry.get("scm_username", ""),
            scm_password_env=entry.get("scm_password_env", ""),
            linked_docs=ScmLinkedDocs(),
        )
    )


def test_ensure_source_checkout_svn_passes_registry_credentials(tmp_path, monkeypatch):
    from backend.services import jenkins_service

    _seed_registry(
        tmp_path,
        monkeypatch,
        id="t1",
        scm_type="svn",
        scm_url="svn://host/repo",
        scm_username="reg_user",
        scm_password_env="MY_PW",
    )
    monkeypatch.setenv("MY_PW", "secret")
    monkeypatch.delenv("DEVOPS_SCM_PASSWORD", raising=False)

    captured: Dict[str, Any] = {}

    def fake_run_svn(**kwargs):
        captured.update(kwargs)
        # Simulate checkout creating files under `source/`
        dest = Path(kwargs["project_root"]) / kwargs["workdir_rel"]
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "dummy.c").write_text("int main(){}", encoding="utf-8")
        return {"rc": 0, "output": "", "dest": str(dest)}

    def fail_run_git(**_kwargs):
        raise AssertionError("run_git should not be called for SVN")

    monkeypatch.setattr(jenkins_service, "run_svn", fake_run_svn)
    monkeypatch.setattr(jenkins_service, "run_git", fail_run_git)

    client = _StubClient(
        meta={
            "repo_urls": ["svn://host/repo"],
            "scm": "svn",
            "scm_revision": "527",
        }
    )

    result = jenkins_service.ensure_source_checkout(
        build_root=tmp_path / "build_1",
        client=client,
        build_selector="lastSuccessfulBuild",
    )

    assert result["ok"] is True
    assert result["scm"] == "svn"
    assert captured["username"] == "reg_user"
    assert captured["password"] == "secret"
    assert captured["repo_url"] == "svn://host/repo"
    assert captured["revision"] == "527"


def test_ensure_source_checkout_override_username_wins(tmp_path, monkeypatch):
    from backend.services import jenkins_service

    _seed_registry(
        tmp_path,
        monkeypatch,
        id="t1",
        scm_type="svn",
        scm_url="svn://host/repo",
        scm_username="reg_user",
    )
    monkeypatch.setenv("DEVOPS_SCM_PASSWORD", "global_pw")

    captured: Dict[str, Any] = {}

    def fake_run_svn(**kwargs):
        captured.update(kwargs)
        dest = Path(kwargs["project_root"]) / kwargs["workdir_rel"]
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "x.c").write_text("", encoding="utf-8")
        return {"rc": 0, "output": "", "dest": str(dest)}

    monkeypatch.setattr(jenkins_service, "run_svn", fake_run_svn)

    result = jenkins_service.ensure_source_checkout(
        build_root=tmp_path / "build_2",
        client=_StubClient(meta={"repo_urls": ["svn://host/repo"], "scm": "svn"}),
        build_selector="lastSuccessfulBuild",
        scm_username="override_user",
    )

    assert result["ok"] is True
    assert captured["username"] == "override_user"
    assert captured["password"] == "global_pw"


def test_ensure_source_checkout_no_registry_uses_default_env(tmp_path, monkeypatch):
    from backend.services import jenkins_service, scm_registry

    # Empty registry — redirect path so no stale entries leak in
    monkeypatch.setattr(
        scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json"
    )
    monkeypatch.setenv("DEVOPS_SCM_PASSWORD", "default_pw")

    captured: Dict[str, Any] = {}

    def fake_run_svn(**kwargs):
        captured.update(kwargs)
        dest = Path(kwargs["project_root"]) / kwargs["workdir_rel"]
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "x.c").write_text("", encoding="utf-8")
        return {"rc": 0, "output": ""}

    monkeypatch.setattr(jenkins_service, "run_svn", fake_run_svn)

    result = jenkins_service.ensure_source_checkout(
        build_root=tmp_path / "build_3",
        client=_StubClient(meta={"repo_urls": ["svn://unknown/repo"], "scm": "svn"}),
        build_selector="lastSuccessfulBuild",
    )

    assert result["ok"] is True
    assert captured["username"] == ""
    assert captured["password"] == "default_pw"


def test_ensure_source_checkout_cached_skips_run_svn(tmp_path, monkeypatch):
    from backend.services import jenkins_service

    build_root = tmp_path / "build_4"
    source_dir = build_root / "source"
    source_dir.mkdir(parents=True)
    (source_dir / "already.c").write_text("", encoding="utf-8")
    # Sentinel required for cache hit — mimic a prior successful checkout.
    (source_dir / ".source_complete").write_text("scm=svn\nrevision=1\n", encoding="utf-8")

    def should_not_run(**_kwargs):
        raise AssertionError("run_svn should not be called when source is cached")

    monkeypatch.setattr(jenkins_service, "run_svn", should_not_run)
    monkeypatch.setattr(jenkins_service, "run_git", should_not_run)

    result = jenkins_service.ensure_source_checkout(
        build_root=build_root,
        client=_StubClient(meta={}),
        build_selector="lastSuccessfulBuild",
    )

    assert result["ok"] is True
    assert result["scm"] == "cached"


def test_ensure_source_checkout_partial_without_sentinel_re_runs(tmp_path, monkeypatch):
    """A non-empty source/ dir without the .source_complete marker must NOT
    be treated as cached — it may be the debris of a failed prior run."""
    from backend.services import jenkins_service

    build_root = tmp_path / "build_partial"
    source_dir = build_root / "source"
    source_dir.mkdir(parents=True)
    (source_dir / "garbage.txt").write_text("", encoding="utf-8")
    # No .source_complete sentinel → must re-checkout.

    captured = {}

    def fake_run_svn(**kwargs):
        captured.update(kwargs)
        dest = Path(kwargs["project_root"]) / kwargs["workdir_rel"]
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "main.c").write_text("", encoding="utf-8")
        return {"rc": 0, "output": ""}

    monkeypatch.setattr(jenkins_service, "run_svn", fake_run_svn)

    result = jenkins_service.ensure_source_checkout(
        build_root=build_root,
        client=_StubClient(meta={"repo_urls": ["svn://host/repo"], "scm": "svn"}),
        build_selector="lastSuccessfulBuild",
    )

    assert result["ok"] is True
    assert result["scm"] == "svn"  # not "cached"
    assert captured, "run_svn should have been invoked"
    assert (source_dir / ".source_complete").exists()


def test_ensure_source_checkout_releases_build_root_lock_on_success(tmp_path, monkeypatch):
    """After a successful checkout the build_root lock must be released so a
    subsequent sync on the same build_root doesn't block."""
    from backend.services import jenkins_service

    def fake_run_svn(**kwargs):
        dest = Path(kwargs["project_root"]) / kwargs["workdir_rel"]
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "x.c").write_text("", encoding="utf-8")
        return {"rc": 0, "output": ""}

    monkeypatch.setattr(jenkins_service, "run_svn", fake_run_svn)

    build_root = tmp_path / "build_lock"
    client = _StubClient(meta={"repo_urls": ["svn://host/repo"], "scm": "svn"})

    r1 = jenkins_service.ensure_source_checkout(
        build_root=build_root, client=client, build_selector="lastSuccessfulBuild"
    )
    # Second call should hit the cache path and also acquire/release the lock
    # without hanging.
    r2 = jenkins_service.ensure_source_checkout(
        build_root=build_root, client=client, build_selector="lastSuccessfulBuild"
    )
    assert r1["ok"] is True
    assert r2["ok"] is True and r2["scm"] == "cached"


def test_ensure_source_checkout_force_rechecks_even_when_cached(tmp_path, monkeypatch):
    """force=True must invalidate an existing sentinel and re-checkout."""
    from backend.services import jenkins_service

    build_root = tmp_path / "build_force"
    source_dir = build_root / "source"
    source_dir.mkdir(parents=True)
    (source_dir / "existing.c").write_text("", encoding="utf-8")
    (source_dir / ".source_complete").write_text("scm=svn\n", encoding="utf-8")

    call_count = {"n": 0}

    def fake_run_svn(**kwargs):
        call_count["n"] += 1
        dest = Path(kwargs["project_root"]) / kwargs["workdir_rel"]
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "fresh.c").write_text("", encoding="utf-8")
        return {"rc": 0, "output": ""}

    monkeypatch.setattr(jenkins_service, "run_svn", fake_run_svn)

    result = jenkins_service.ensure_source_checkout(
        build_root=build_root,
        client=_StubClient(meta={"repo_urls": ["svn://host/repo"], "scm": "svn"}),
        build_selector="lastSuccessfulBuild",
        force=True,
    )

    assert result["ok"] is True
    assert result["scm"] == "svn"
    assert call_count["n"] == 1, "run_svn must be called even with cached source when force=True"
    # Old file must be gone (rmtree), new file must exist.
    assert not (source_dir / "existing.c").exists()
    assert (source_dir / "fresh.c").exists()


def test_ensure_source_checkout_git_path_does_not_pass_password(tmp_path, monkeypatch):
    """Git clone currently does not accept username/password via run_git
    (credentials are expected to be handled out-of-band e.g. via SSH agent or
    .netrc). Ensure the SVN-only credentials don't accidentally leak into
    run_git kwargs, which would break signature compatibility."""
    from backend.services import jenkins_service

    monkeypatch.setenv("DEVOPS_SCM_PASSWORD", "should_not_be_used")

    captured: Dict[str, Any] = {}

    def fake_run_git(**kwargs):
        captured.update(kwargs)
        dest = Path(kwargs["project_root"]) / kwargs["workdir_rel"]
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "README.md").write_text("", encoding="utf-8")
        return {"rc": 0, "output": ""}

    def fail_run_svn(**_kwargs):
        raise AssertionError("run_svn should not be called for git")

    monkeypatch.setattr(jenkins_service, "run_git", fake_run_git)
    monkeypatch.setattr(jenkins_service, "run_svn", fail_run_svn)

    result = jenkins_service.ensure_source_checkout(
        build_root=tmp_path / "build_5",
        client=_StubClient(
            meta={
                "repo_urls": ["https://example/repo.git"],
                "scm": "git",
                "git_branch": "main",
            }
        ),
        build_selector="lastSuccessfulBuild",
    )

    assert result["ok"] is True
    assert result["scm"] == "git"
    assert "username" not in captured
    assert "password" not in captured
    assert captured["branch"] == "main"
