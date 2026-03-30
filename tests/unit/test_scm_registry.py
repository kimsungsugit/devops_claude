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
