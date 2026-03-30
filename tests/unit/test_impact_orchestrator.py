from __future__ import annotations

from workflow.change_trigger import ChangeTrigger
from pathlib import Path


def test_run_impact_update_dry_run_builds_auto_and_flag_actions(tmp_path, monkeypatch):
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import impact_audit, impact_orchestrator

    reg_path = tmp_path / "config" / "scm_registry.json"
    audit_dir = tmp_path / "audit"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", audit_dir)
    monkeypatch.setattr(impact_audit, "LOCK_PATH", audit_dir / ".run_lock")
    scm_registry.register_entry(
        ScmRegisterRequest(
            id="hdpdm01",
            name="HDPDM01",
            scm_type="git",
            scm_url="https://example/repo.git",
            source_root=str(tmp_path / "src"),
        )
    )

    monkeypatch.setattr(
        impact_orchestrator,
        "classify_changed_functions",
        lambda *args, **kwargs: {"door_run": "BODY", "door_init": "SIGNATURE"},
    )

    monkeypatch.setattr(
        impact_orchestrator,
        "_load_source_sections",
        lambda _source_root: {
            "call_map": {"door_run": ["door_helper"], "door_helper": ["door_leaf"]},
            "function_details_by_name": {
                "door_run": {"module_name": "door", "file": "Sources/APP/Ap_Door.c"},
                "door_init": {"module_name": "door", "file": "Sources/APP/Ap_Door.c"},
                "door_helper": {"module_name": "door", "file": "Sources/APP/Ap_Door_Helper.c"},
                "door_leaf": {"module_name": "door", "file": "Sources/APP/Ap_Door_Leaf.c"},
            },
        },
    )

    result = impact_orchestrator.run_impact_update(
        ChangeTrigger(
            trigger_type="local",
            scm_id="hdpdm01",
            source_root=str(tmp_path / "src"),
            scm_type="git",
            base_ref="HEAD~1",
            changed_files=["Ap_Door.c"],
            dry_run=True,
            targets=["uds", "sts"],
            metadata={},
        )
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["actions"]["uds"]["mode"] == "AUTO"
    assert result["actions"]["sts"]["mode"] == "FLAG"
    assert result["impact"]["indirect_1hop"] == ["door_helper"]
    assert result["impact"]["indirect_2hop"] == ["door_leaf"]
    assert any(p.name.startswith("impact_") for p in audit_dir.iterdir())


def test_run_impact_update_promotes_auto_to_flag_when_limit_exceeded(tmp_path, monkeypatch):
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import impact_audit, impact_orchestrator

    reg_path = tmp_path / "config" / "scm_registry.json"
    audit_dir = tmp_path / "audit"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", audit_dir)
    monkeypatch.setattr(impact_audit, "LOCK_PATH", audit_dir / ".run_lock")
    scm_registry.register_entry(
        ScmRegisterRequest(
            id="hdpdm01",
            name="HDPDM01",
            scm_type="git",
            source_root=str(tmp_path / "src"),
        )
    )

    monkeypatch.setattr(
        impact_orchestrator,
        "classify_changed_functions",
        lambda *args, **kwargs: {"seed": "BODY"},
    )

    monkeypatch.setattr(
        impact_orchestrator,
        "_load_source_sections",
        lambda _source_root: {
            "call_map": {
                "seed": ["f1", "f2"],
                "f1": ["f3"],
                "f2": ["f4"],
            },
            "function_details_by_name": {
                name: {"module_name": "door", "file": "Sources/APP/Ap_Door.c"}
                for name in ["seed", "f1", "f2", "f3", "f4"]
            },
        },
    )

    result = impact_orchestrator.run_impact_update(
        ChangeTrigger(
            trigger_type="local",
            scm_id="hdpdm01",
            source_root=str(tmp_path / "src"),
            scm_type="git",
            base_ref="HEAD~1",
            changed_files=["Ap_Door.c"],
            dry_run=False,
            targets=["uds", "suts"],
            metadata={},
        ),
        options=impact_orchestrator.ImpactOptions(max_hop=2, same_module_only=True, max_impacted_functions=2),
    )

    assert result["ok"] is True
    assert result["warnings"]
    assert result["actions"]["uds"]["mode"] == "FLAG"
    assert result["actions"]["suts"]["mode"] == "FLAG"


def test_run_impact_update_executes_auto_and_flag_actions(tmp_path, monkeypatch):
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import impact_audit, impact_changes, impact_orchestrator

    reg_path = tmp_path / "config" / "scm_registry.json"
    audit_dir = tmp_path / "audit"
    change_dir = tmp_path / "changes"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", audit_dir)
    monkeypatch.setattr(impact_audit, "LOCK_PATH", audit_dir / ".run_lock")
    monkeypatch.setattr(impact_changes, "CHANGE_DIR", change_dir)
    scm_registry.register_entry(
        ScmRegisterRequest(
            id="hdpdm01",
            name="HDPDM01",
            scm_type="git",
            source_root=str(tmp_path / "src"),
        )
    )

    monkeypatch.setattr(
        impact_orchestrator,
        "classify_changed_functions",
        lambda *args, **kwargs: {"door_run": "BODY", "door_header": "HEADER"},
    )

    monkeypatch.setattr(
        impact_orchestrator,
        "_load_source_sections",
        lambda _source_root: {
            "call_map": {"door_run": ["door_helper"]},
            "function_details_by_name": {
                "door_run": {"module_name": "door", "file": "Sources/APP/Ap_Door.c"},
                "door_header": {"module_name": "door", "file": "Sources/APP/Ap_Door.h"},
                "door_helper": {"module_name": "door", "file": "Sources/APP/Ap_Door.c"},
            },
        },
    )
    monkeypatch.setattr(
        impact_orchestrator,
        "_execute_auto_action",
        lambda target, trigger, entry, target_functions=None: {"output_path": str(tmp_path / f"{target}.out")},
    )
    monkeypatch.setattr(
        impact_orchestrator,
        "_write_review_artifact",
        lambda target, trigger, changed_types, impact_groups, by_name=None, linked_doc="": str(tmp_path / f"{target}_review.md"),
    )

    result = impact_orchestrator.run_impact_update(
        ChangeTrigger(
            trigger_type="local",
            scm_id="hdpdm01",
            source_root=str(tmp_path / "src"),
            scm_type="git",
            base_ref="HEAD~1",
            changed_files=["Ap_Door.c", "Ap_Door.h"],
            dry_run=False,
            targets=["uds", "sts"],
            metadata={},
        )
    )

    updated = scm_registry.get_registry_entry("hdpdm01")
    assert result["ok"] is True
    assert result["actions"]["uds"]["status"] == "completed"
    assert result["actions"]["uds"]["output_path"].endswith("uds.out")
    assert result["actions"]["sts"]["artifact_path"].endswith("sts_review.md")
    assert result["change_log"]["path"].endswith(".json")
    assert updated is not None
    assert updated.linked_docs.uds.endswith("uds.out")
    assert any(p.name.startswith("change_") for p in change_dir.iterdir())


def test_run_uds_generation_passes_source_root_to_script(tmp_path, monkeypatch):
    from workflow import impact_orchestrator

    captured = {}
    out_dir = tmp_path / "backend" / "reports" / "uds_local"
    out_dir.mkdir(parents=True, exist_ok=True)
    generated = out_dir / "uds_spec_generated_expanded_20260324_120000.docx"
    generated.write_text("ok", encoding="utf-8")

    class DummyRun:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(impact_orchestrator, "REPO_ROOT", tmp_path)

    def fake_run(cmd, cwd=None, env=None, capture_output=None, text=None, timeout=None, check=None):
        captured["env"] = dict(env or {})
        return DummyRun()

    monkeypatch.setattr(impact_orchestrator.subprocess, "run", fake_run)

    result = impact_orchestrator._run_uds_generation(
        ChangeTrigger(
            trigger_type="local",
            scm_id="hdpdm01",
            source_root=str(tmp_path / "src_root"),
            scm_type="svn",
            base_ref="",
            changed_files=["Sources/APP/Ap_BuzzerCtrl_PDS.c"],
            dry_run=False,
            metadata={},
        )
    )

    assert result["output_path"].endswith(".docx")
    assert captured["env"]["UDS_SOURCE_ROOT"] == str(tmp_path / "src_root")


def test_run_impact_update_falls_back_to_file_based_change_types(tmp_path, monkeypatch):
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import impact_audit, impact_orchestrator

    reg_path = tmp_path / "config" / "scm_registry.json"
    audit_dir = tmp_path / "audit"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", audit_dir)
    monkeypatch.setattr(impact_audit, "LOCK_PATH", audit_dir / ".run_lock")
    scm_registry.register_entry(
        ScmRegisterRequest(
            id="hdpdm01",
            name="HDPDM01",
            scm_type="hash",
            source_root=str(tmp_path / "src"),
        )
    )
    monkeypatch.setattr(impact_orchestrator, "classify_changed_functions", lambda *args, **kwargs: {})

    monkeypatch.setattr(
        impact_orchestrator,
        "_load_source_sections",
        lambda _source_root: {"call_map": {}, "function_details_by_name": {}},
    )

    result = impact_orchestrator.run_impact_update(
        ChangeTrigger(
            trigger_type="local",
            scm_id="hdpdm01",
            source_root=str(tmp_path / "src"),
            scm_type="hash",
            base_ref="",
            changed_files=["Sources/APP/Ap_DoorCtrl_PDS.c", "Sources/APP/Ap_DoorCtrl_PDS.h"],
            dry_run=True,
            targets=["uds", "sts"],
            metadata={},
        )
    )

    assert result["ok"] is True
    assert result["changed_function_types"]["ap_doorctrl_pds"] == "HEADER"
    assert result["actions"]["uds"]["mode"] == "AUTO"
    assert result["actions"]["sts"]["mode"] == "FLAG"


def test_update_linked_doc_preserves_other_paths(tmp_path, monkeypatch):
    from backend.schemas import ScmLinkedDocs, ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import impact_orchestrator

    reg_path = tmp_path / "config" / "scm_registry.json"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)
    scm_registry.register_entry(
        ScmRegisterRequest(
            id="hdpdm01",
            name="HDPDM01",
            scm_type="hash",
            source_root=str(tmp_path / "src"),
            linked_docs=ScmLinkedDocs(
                uds="old_uds.docx",
                sts="old_sts.xlsx",
                suts="old_suts.xlsx",
                srs="srs.docx",
                sds="sds.docx",
                hsis="hsis.xlsx",
            ),
        )
    )

    impact_orchestrator._update_linked_doc("hdpdm01", "uds", "new_uds.docx")

    entry = scm_registry.get_registry_entry("hdpdm01")
    assert entry is not None
    assert entry.linked_docs.uds == "new_uds.docx"
    assert entry.linked_docs.sts == "old_sts.xlsx"
    assert entry.linked_docs.suts == "old_suts.xlsx"


def test_write_review_artifact_includes_context_and_linked_summary(tmp_path, monkeypatch):
    from workflow import impact_orchestrator
    from workflow.change_trigger import ChangeTrigger

    monkeypatch.setattr(impact_orchestrator, "REPO_ROOT", tmp_path)
    linked_doc = tmp_path / "reports" / "sts" / "sts_eval.xlsx"
    linked_doc.parent.mkdir(parents=True, exist_ok=True)
    linked_doc.write_text("", encoding="utf-8")
    linked_doc.with_suffix(".payload.json").write_text(
        """
        {
          "test_case_count": 241,
          "quality_report": {"requirement_coverage": {"pct": 100.0}},
          "trace_coverage": {"pct": 84.6}
        }
        """.strip(),
        encoding="utf-8",
    )

    out = impact_orchestrator._write_review_artifact(
        "sts",
        ChangeTrigger(
            trigger_type="local",
            scm_id="hdpdm01",
            source_root=str(tmp_path / "src"),
            scm_type="hash",
            base_ref="",
            changed_files=["Sources/APP/Ap_BuzzerCtrl_PDS.c"],
            dry_run=False,
            targets=["sts"],
            metadata={},
        ),
        {"ap_buzzerctrl_pds": "BODY"},
        {"direct": ["ap_buzzerctrl_pds"], "indirect_1hop": [], "indirect_2hop": []},
        {
            "ap_buzzerctrl_pds": {
                "module_name": "Ap_BuzzerCtrl",
                "file": "Sources/APP/Ap_BuzzerCtrl_PDS.c",
                "related": "SwTR_0202, SwEI_0301",
            }
        },
        str(linked_doc),
    )

    text = Path(out).read_text(encoding="utf-8")
    assert "Linked test cases" in text
    assert "Ap_BuzzerCtrl" in text
    assert "SwTR_0202" in text


def test_resolve_changed_types_to_functions_uses_matching_source_file():
    from workflow import impact_orchestrator

    resolved = impact_orchestrator._resolve_changed_types_to_functions(
        {"ap_buzzerctrl_pds": "BODY"},
        ["Sources/APP/Ap_BuzzerCtrl_PDS.c"],
        {
            "buzzer_run": {"file": "D:/Project/Ados/PDS_64_RD/Sources/APP/Ap_BuzzerCtrl_PDS.c"},
            "buzzer_init": {"file": "D:/Project/Ados/PDS_64_RD/Sources/APP/Ap_BuzzerCtrl_PDS.c"},
            "door_run": {"file": "D:/Project/Ados/PDS_64_RD/Sources/APP/Ap_DoorCtrl_PDS.c"},
        },
    )

    assert resolved == {"buzzer_run": "BODY", "buzzer_init": "BODY"}
