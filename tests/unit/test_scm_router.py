from __future__ import annotations


def test_scm_router_crud_and_link_docs(tmp_path, monkeypatch):
    from backend.routers import scm as scm_router
    from backend.schemas import ScmLinkedDocs, ScmRegisterRequest, ScmUpdateRequest
    from backend.services import scm_registry

    reg_path = tmp_path / "config" / "scm_registry.json"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)

    created = scm_router.scm_register(
        ScmRegisterRequest(
            id="hdpdm01",
            name="HDPDM01",
            scm_type="git",
            scm_url="https://example/repo.git",
            source_root=str(tmp_path),
        )
    )
    assert created["ok"] is True
    assert created["item"]["id"] == "hdpdm01"

    listed = scm_router.scm_list()
    assert listed["count"] == 1

    updated = scm_router.scm_update("hdpdm01", ScmUpdateRequest(branch="main"))
    assert updated["item"]["branch"] == "main"

    linked = scm_router.scm_link_docs(
        "hdpdm01",
        ScmLinkedDocs(uds="backend/reports/uds_local/latest.docx"),
    )
    assert linked["item"]["linked_docs"]["uds"].endswith("latest.docx")

    deleted = scm_router.scm_delete("hdpdm01")
    assert deleted["deleted"] == "hdpdm01"


def test_scm_status_for_missing_registry(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from backend.routers import scm as scm_router
    from backend.services import scm_registry

    reg_path = tmp_path / "config" / "scm_registry.json"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)
    scm_registry.ensure_registry_file()

    try:
        scm_router.scm_status("missing")
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("expected 404")


def test_scm_change_history_routes(tmp_path, monkeypatch):
    from backend.routers import scm as scm_router
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import impact_changes

    reg_path = tmp_path / "config" / "scm_registry.json"
    change_dir = tmp_path / "impact_changes"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)
    monkeypatch.setattr(impact_changes, "CHANGE_DIR", change_dir)

    scm_router.scm_register(
        ScmRegisterRequest(
            id="hdpdm01",
            name="HDPDM01",
            scm_type="svn",
            scm_url="svn://example/repo",
            source_root=str(tmp_path),
        )
    )
    impact_changes.write_change_log(
        {
            "run_id": "impact_20260324_112921",
            "timestamp": "2026-03-24T11:29:21",
            "scm_id": "hdpdm01",
            "dry_run": False,
            "changed_files": ["Sources/APP/Ap_Door.c"],
            "changed_functions": {"door_run": "BODY"},
            "summary": {
                "uds_changed_functions": 1,
                "suts_changed_functions": 2,
                "suts_changed_cases": 2,
                "suts_changed_sequences": 6,
                "sts_flagged": 1,
                "sds_flagged": 0,
            },
            "documents": {
                "uds": {
                    "changed_functions": [
                        {"name": "door_run", "fields_changed": ["description"]},
                    ]
                },
                "suts": {"summary": {"changed_cases": 2}},
            },
        }
    )

    listed = scm_router.scm_change_history("hdpdm01", limit=10)
    detail = scm_router.scm_change_history_detail("impact_20260324_112921")
    function_items = scm_router.scm_change_history_function("hdpdm01", "door_run", limit=10)

    assert listed["count"] == 1
    assert detail["item"]["run_id"] == "impact_20260324_112921"
    assert function_items["count"] == 1
