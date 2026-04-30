from __future__ import annotations

from pathlib import Path


def test_registry_create_update_delete(tmp_path, monkeypatch):
    from backend.schemas import ScmLinkedDocs, ScmRegisterRequest, ScmUpdateRequest
    from backend.services import scm_registry

    reg_path = tmp_path / "config" / "scm_registry.json"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)

    created = scm_registry.register_entry(
        ScmRegisterRequest(
            id="hdpdm01",
            name="HDPDM01",
            scm_type="git",
            scm_url="https://example/repo.git",
            source_root="D:/Project/Ados/PDS_64_RD",
        )
    )
    assert created.id == "hdpdm01"
    assert reg_path.exists()

    loaded = scm_registry.get_registry_entry("hdpdm01")
    assert loaded is not None
    assert loaded.scm_url == "https://example/repo.git"

    updated = scm_registry.update_entry(
        "hdpdm01",
        ScmUpdateRequest(
            branch="main",
            linked_docs=ScmLinkedDocs(uds="backend/reports/uds_local/latest.docx"),
        ),
    )
    assert updated.branch == "main"
    assert updated.linked_docs.uds.endswith("latest.docx")

    assert scm_registry.delete_entry("hdpdm01") is True
    assert scm_registry.get_registry_entry("hdpdm01") is None


def test_registry_invalid_json_recovers(tmp_path, monkeypatch):
    from backend.services import scm_registry

    reg_path = tmp_path / "config" / "scm_registry.json"
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text("{invalid", encoding="utf-8")
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)

    store = scm_registry.load_registry_store()

    assert store.registries == []
    assert reg_path.with_suffix(".invalid.json").exists()


def _seed_registry(tmp_path, monkeypatch, entry: dict) -> None:
    """Write a minimal registry file and redirect the module path to it."""
    from backend.schemas import ScmLinkedDocs, ScmRegisterRequest
    from backend.services import scm_registry

    reg_path = tmp_path / "config" / "scm_registry.json"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)
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


def test_resolve_credentials_url_match_uses_entry_env(tmp_path, monkeypatch):
    from backend.services import scm_registry

    _seed_registry(
        tmp_path,
        monkeypatch,
        {
            "id": "t1",
            "scm_type": "svn",
            "scm_url": "svn://192.168.110.33/ADOS/PDS64_RD",
            "scm_username": "kss1119",
            "scm_password_env": "MY_PW_ENV",
        },
    )
    monkeypatch.setenv("MY_PW_ENV", "from_entry_env")
    monkeypatch.delenv("DEVOPS_SCM_PASSWORD", raising=False)

    user, pw, entry = scm_registry.resolve_scm_credentials(
        repo_url="svn://192.168.110.33/ADOS/PDS64_RD"
    )
    assert user == "kss1119"
    assert pw == "from_entry_env"
    assert entry is not None and entry.id == "t1"


def test_resolve_credentials_override_username_wins(tmp_path, monkeypatch):
    from backend.services import scm_registry

    _seed_registry(
        tmp_path,
        monkeypatch,
        {
            "id": "t1",
            "scm_type": "svn",
            "scm_url": "svn://host/repo",
            "scm_username": "registry_user",
            "scm_password_env": "MY_PW_ENV",
        },
    )
    monkeypatch.setenv("MY_PW_ENV", "pw")

    user, _pw, _ = scm_registry.resolve_scm_credentials(
        repo_url="svn://host/repo", override_username="override_user"
    )
    assert user == "override_user"


def test_resolve_credentials_falls_back_to_default_env(tmp_path, monkeypatch):
    from backend.services import scm_registry

    # No registry entry matches
    _seed_registry(
        tmp_path,
        monkeypatch,
        {"id": "other", "scm_type": "svn", "scm_url": "svn://other/repo"},
    )
    monkeypatch.delenv("MY_PW_ENV", raising=False)
    monkeypatch.setenv("DEVOPS_SCM_PASSWORD", "default_pw")

    user, pw, entry = scm_registry.resolve_scm_credentials(repo_url="svn://nowhere/none")
    assert user == ""
    assert pw == "default_pw"
    assert entry is None


def test_resolve_credentials_by_scm_id(tmp_path, monkeypatch):
    from backend.services import scm_registry

    _seed_registry(
        tmp_path,
        monkeypatch,
        {
            "id": "t1",
            "scm_type": "svn",
            "scm_url": "svn://host/repo",
            "scm_username": "kss1119",
        },
    )
    monkeypatch.setenv("DEVOPS_SCM_PASSWORD", "global_pw")

    user, pw, entry = scm_registry.resolve_scm_credentials(scm_id="t1")
    assert user == "kss1119"
    assert pw == "global_pw"
    assert entry is not None and entry.id == "t1"


def test_resolve_credentials_url_prefix_match(tmp_path, monkeypatch):
    from backend.services import scm_registry

    _seed_registry(
        tmp_path,
        monkeypatch,
        {
            "id": "t1",
            "scm_type": "svn",
            "scm_url": "svn://192.168.110.33/ADOS/PDS64_RD",
            "scm_username": "kss1119",
        },
    )

    # Sub-path of the registered URL should still match the entry.
    _user, _pw, entry = scm_registry.resolve_scm_credentials(
        repo_url="svn://192.168.110.33/ADOS/PDS64_RD/trunk/src"
    )
    assert entry is not None and entry.id == "t1"


def test_resolve_credentials_does_not_match_reverse_direction(tmp_path, monkeypatch):
    """If the registry entry is a deeper sub-path than the requested URL,
    we must NOT match — otherwise a sibling project under the same host could
    cross-leak credentials."""
    from backend.schemas import ScmLinkedDocs, ScmRegisterRequest
    from backend.services import scm_registry

    reg_path = tmp_path / "config" / "scm_registry.json"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)
    scm_registry.register_entry(
        ScmRegisterRequest(
            id="deep",
            name="deep",
            scm_type="svn",
            scm_url="svn://host/proj/trunk/src",  # deeper than request
            scm_username="deep_user",
            linked_docs=ScmLinkedDocs(),
        )
    )

    _u, _p, entry = scm_registry.resolve_scm_credentials(repo_url="svn://host/proj")
    assert entry is None, "Reverse direction (registry deeper than request) must not match"


def test_register_rejects_blacklisted_env_name(tmp_path, monkeypatch):
    """`scm_password_env=PATH` must be rejected (not silently accepted)."""
    import pytest
    from backend.schemas import ScmLinkedDocs, ScmRegisterRequest
    from backend.services import scm_registry

    reg_path = tmp_path / "config" / "scm_registry.json"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)

    with pytest.raises(scm_registry.ScmValidationError):
        scm_registry.register_entry(
            ScmRegisterRequest(
                id="bad",
                name="bad",
                scm_type="svn",
                scm_url="svn://host/x",
                scm_password_env="PATH",  # reserved
                linked_docs=ScmLinkedDocs(),
            )
        )


def test_register_rejects_invalid_env_identifier(tmp_path, monkeypatch):
    import pytest
    from backend.schemas import ScmLinkedDocs, ScmRegisterRequest
    from backend.services import scm_registry

    reg_path = tmp_path / "config" / "scm_registry.json"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)

    with pytest.raises(scm_registry.ScmValidationError):
        scm_registry.register_entry(
            ScmRegisterRequest(
                id="bad",
                name="bad",
                scm_type="svn",
                scm_url="svn://host/x",
                scm_password_env="has space",  # not an identifier
                linked_docs=ScmLinkedDocs(),
            )
        )


def test_register_accepts_valid_env_name(tmp_path, monkeypatch):
    from backend.schemas import ScmLinkedDocs, ScmRegisterRequest
    from backend.services import scm_registry

    reg_path = tmp_path / "config" / "scm_registry.json"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)

    entry = scm_registry.register_entry(
        ScmRegisterRequest(
            id="ok",
            name="ok",
            scm_type="svn",
            scm_url="svn://host/x",
            scm_password_env="SVN_PWD_PROJECT_A",
            linked_docs=ScmLinkedDocs(),
        )
    )
    assert entry.scm_password_env == "SVN_PWD_PROJECT_A"


def test_resolve_credentials_prefers_longest_match(tmp_path, monkeypatch):
    """When multiple entries could match, the most specific (longest URL) wins."""
    from backend.schemas import ScmLinkedDocs, ScmRegisterRequest
    from backend.services import scm_registry

    reg_path = tmp_path / "config" / "scm_registry.json"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)

    # Broad entry first, specific entry second — without longest-match logic
    # the first would always win.
    scm_registry.register_entry(
        ScmRegisterRequest(
            id="broad",
            name="broad",
            scm_type="svn",
            scm_url="svn://host/proj",
            scm_username="broad_user",
            linked_docs=ScmLinkedDocs(),
        )
    )
    scm_registry.register_entry(
        ScmRegisterRequest(
            id="specific",
            name="specific",
            scm_type="svn",
            scm_url="svn://host/proj/trunk",
            scm_username="specific_user",
            linked_docs=ScmLinkedDocs(),
        )
    )

    user, _pw, entry = scm_registry.resolve_scm_credentials(
        repo_url="svn://host/proj/trunk/src/foo.c"
    )
    assert entry is not None and entry.id == "specific"
    assert user == "specific_user"
