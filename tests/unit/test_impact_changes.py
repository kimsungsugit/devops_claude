from __future__ import annotations


def test_diff_uds_payload_detects_changed_fields():
    from workflow.impact_changes import diff_uds_payload

    before = {
        "function_details": {
            "1": {
                "name": "door_run",
                "description": "before",
                "inputs": ["a"],
                "outputs": ["ret"],
                "calls_list": ["door_off"],
                "globals_global": [],
                "globals_static": ["timer"],
                "related": "SwTR_0001",
                "asil": "QM",
            }
        }
    }
    after = {
        "function_details": {
            "1": {
                "name": "door_run",
                "description": "after",
                "inputs": ["a"],
                "outputs": ["ret"],
                "calls_list": ["door_off", "door_on"],
                "globals_global": ["g_state"],
                "globals_static": ["timer"],
                "related": "SwTR_0001",
                "asil": "QM",
            }
        }
    }

    diff = diff_uds_payload(before, after, ["door_run"])

    assert diff["summary"]["changed_functions"] == 1
    assert diff["changed_functions"][0]["name"] == "door_run"
    assert set(diff["changed_functions"][0]["fields_changed"]) == {"description", "calls_list", "globals_global"}


def test_write_and_list_change_logs(tmp_path, monkeypatch):
    from workflow import impact_changes

    monkeypatch.setattr(impact_changes, "CHANGE_DIR", tmp_path / "impact_changes")
    change_log = {
        "run_id": "impact_20260324_112921",
        "timestamp": "2026-03-24T11:29:21",
        "scm_id": "hdpdm01",
        "dry_run": False,
        "changed_files": ["Sources/APP/Ap_Door.c"],
        "summary": {
            "uds_changed_functions": 1,
            "suts_changed_functions": 2,
            "suts_changed_cases": 2,
            "suts_changed_sequences": 6,
            "sts_flagged": 1,
            "sds_flagged": 0,
        },
        "changed_functions": {"door_run": "BODY"},
        "documents": {
            "uds": {
                "changed_functions": [
                    {"name": "door_run", "fields_changed": ["description", "calls_list"]},
                ]
            },
            "suts": {"summary": {"changed_cases": 2}},
        },
    }

    out = impact_changes.write_change_log(change_log)
    items = impact_changes.list_change_logs("hdpdm01", limit=10)
    detail = impact_changes.load_change_log("impact_20260324_112921")
    fn_items = impact_changes.list_function_history("hdpdm01", "door_run", limit=10)
    module_items = impact_changes.list_module_history("hdpdm01", "Door", limit=10)

    assert out.exists()
    assert len(items) == 1
    assert items[0]["run_id"] == "impact_20260324_112921"
    assert detail["summary"]["uds_changed_functions"] == 1
    assert len(fn_items) == 1
    assert fn_items[0]["uds_fields_changed"] == ["description", "calls_list"]
    assert len(module_items) == 1
    assert module_items[0]["matched_functions"] == ["door_run"]
