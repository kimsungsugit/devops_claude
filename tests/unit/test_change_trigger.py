from __future__ import annotations


def test_build_registry_trigger_uses_manual_changed_files(tmp_path, monkeypatch):
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow.change_trigger import build_registry_trigger

    reg_path = tmp_path / "config" / "scm_registry.json"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)
    scm_registry.register_entry(
        ScmRegisterRequest(
            id="hdpdm01",
            name="HDPDM01",
            scm_type="git",
            scm_url="https://example/repo.git",
            source_root=str(tmp_path / "src"),
        )
    )

    trig = build_registry_trigger(
        trigger_type="local",
        scm_id="hdpdm01",
        manual_changed_files=["a.c", "b.h"],
        dry_run=True,
        targets=["uds"],
    )

    assert trig.changed_files == ["a.c", "b.h"]
    assert trig.dry_run is True
    assert trig.targets == ["uds"]


def test_build_registry_trigger_uses_hash_fallback_for_unknown_mode(tmp_path, monkeypatch):
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import change_trigger

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.c").write_text("int a(void){return 0;}\n", encoding="utf-8")

    reg_path = tmp_path / "config" / "scm_registry.json"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)
    monkeypatch.setattr(change_trigger, "diff_source_snapshot", lambda *args, **kwargs: {"changed_files": ["a.c"]})
    scm_registry.register_entry(
        ScmRegisterRequest(
            id="hdpdm01",
            name="HDPDM01",
            scm_type="hash",
            source_root=str(src),
        )
    )

    trig = change_trigger.build_registry_trigger(
        trigger_type="local",
        scm_id="hdpdm01",
    )

    assert trig.changed_files == ["a.c"]
    assert trig.scm_type == "hash"


def test_build_registry_trigger_uses_empty_base_ref_for_svn(tmp_path, monkeypatch):
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import change_trigger

    reg_path = tmp_path / "config" / "scm_registry.json"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)
    monkeypatch.setattr(change_trigger, "get_changed_files", lambda source_root, base_ref, scm_type: ["a.c"])
    scm_registry.register_entry(
        ScmRegisterRequest(
            id="hdpdm01",
            name="HDPDM01",
            scm_type="svn",
            source_root=str(tmp_path / "wc"),
            base_ref="",
        )
    )

    trig = change_trigger.build_registry_trigger(
        trigger_type="local",
        scm_id="hdpdm01",
    )

    assert trig.scm_type == "svn"
    assert trig.base_ref == ""
    assert trig.changed_files == ["a.c"]
