from __future__ import annotations

from pathlib import Path


def test_artifact_payload_path_survives_permission_error(monkeypatch):
    """cloudium U:\\(SMB) payload가 접근 거부(WinError 5)여도 예외 대신 None 반환."""
    from workflow import impact_changes

    def _raise(self, *a, **k):
        raise PermissionError("[WinError 5] 액세스가 거부되었습니다")

    monkeypatch.setattr(Path, "exists", _raise)
    # 예외 전파 없이 None (best-effort)
    assert impact_changes._artifact_payload_path("U:/연구소/SwUDS.docx") is None
    assert impact_changes._load_json(Path("U:/연구소/x.payload.json")) == {}


def test_build_change_log_survives_uds_payload_permission_error(monkeypatch):
    """build_change_log가 previous_linked_docs.uds(U:\\) 접근 거부여도 죽지 않고 change_log 반환."""
    from workflow import impact_changes

    def _raise(self, *a, **k):
        raise PermissionError("[WinError 5] 액세스가 거부되었습니다")

    monkeypatch.setattr(Path, "exists", _raise)
    cl = impact_changes.build_change_log(
        run_id="impact_test",
        trigger={"scm_id": "kjpds02_pv", "trigger_type": "jenkins"},
        result={
            "actions": {"uds": {"status": "review_required", "function_count": 2}},
            "changed_function_types": {"door_ctrl": "SIGNATURE"},
            "impact": {"direct": ["door_ctrl"]},
        },
        previous_linked_docs={"uds": "U:/연구소/SwUDS_v2.08.docx"},
    )
    assert isinstance(cl, dict)
    assert cl.get("run_id") == "impact_test"


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


def test_load_payload_with_status_distinguishes_absent_unreadable(monkeypatch, tmp_path):
    """M6 핵심 — absent(부재)와 unreadable(존재하나 권한거부)을 구분한다."""
    from workflow import impact_changes
    # 미지정
    assert impact_changes._load_payload_with_status("") == ({}, "absent")
    # 부재(존재 안 함)
    assert impact_changes._load_payload_with_status(str(tmp_path / "nope.docx")) == ({}, "absent")
    # 정상 로드
    p = tmp_path / "doc.docx"
    (tmp_path / "doc.payload.json").write_text('{"test_case_count": 5}', encoding="utf-8")
    payload, status = impact_changes._load_payload_with_status(str(p))
    assert status == "loaded" and payload.get("test_case_count") == 5
    # unreadable — 경로가 둘이고 **둘 다** 고정해야 결과가 머신에 안 좌우된다.
    # ⚠ 구현은 resolver(`get_resolver().read_bytes`)를 **먼저** 부른다. resolver 를 스텁하지
    #   않으면 그것이 던지는 예외 종류가 머신 상태(file_mode.json·cloudium 가용성)에 좌우돼
    #   판정이 갈린다 — 실측: CI 에서 FileNotFoundError 가 나 'absent' 로 떨어지면서
    #   아래 `Path.exists` 몽키패치에 닿지도 못했다(로컬 통과 / CI 실패).
    import backend.services.file_resolver as _fr

    # ① resolver 가 권한거부를 던지는 경로 — cloudium U:\ SMB 의 실제 케이스
    class _Denied:
        def read_bytes(self, *a, **k):
            raise PermissionError("[WinError 5]")

    monkeypatch.setattr(_fr, "get_resolver", lambda *a, **k: _Denied())
    assert impact_changes._load_payload_with_status("U:/x.docx") == ({}, "unreadable")

    # ② resolver 미가용 → 로컬 직접 읽기 폴백에서 권한거부
    def _unavailable(*a, **k):
        raise RuntimeError("resolver 미가용")

    def _raise(self, *a, **k):
        raise PermissionError("[WinError 5]")

    monkeypatch.setattr(_fr, "get_resolver", _unavailable)
    monkeypatch.setattr(Path, "exists", _raise)
    assert impact_changes._load_payload_with_status("U:/x.docx") == ({}, "unreadable")


def test_build_change_log_uds_before_unreadable_avoids_created_overreport(monkeypatch):
    """M6: 이전 UDS payload가 unreadable이면 전 함수를 'created'로 과대보고하지 않고 정직 표기."""
    from workflow import impact_changes
    after_payload = {"function_details": {"1": {"name": "door_run"}, "2": {"name": "door_init"}}}

    def _fake(path_text):
        if path_text == "AFTER_UDS":
            return after_payload, "loaded"
        if path_text == "BEFORE_UDS_UNREADABLE":
            return {}, "unreadable"
        return {}, "absent"

    monkeypatch.setattr(impact_changes, "_load_payload_with_status", _fake)
    cl = impact_changes.build_change_log(
        run_id="t", trigger={"scm_id": "kj", "trigger_type": "jenkins"},
        result={
            "actions": {"uds": {"status": "completed", "output_path": "AFTER_UDS",
                                "functions": ["door_run", "door_init"], "function_count": 2}},
            "changed_function_types": {"door_run": "SIGNATURE"}, "impact": {"direct": ["door_run"]},
        },
        previous_linked_docs={"uds": "BEFORE_UDS_UNREADABLE"},
    )
    uds = cl["documents"]["uds"]
    assert uds.get("before_unavailable") is True
    kinds = {fc for row in uds.get("changed_functions", []) for fc in row.get("fields_changed", [])}
    assert "created" not in kinds  # 과대보고 없음
    assert cl["summary"]["before_payload_unavailable"] is True


def test_build_change_log_uds_before_absent_marks_first_generation(monkeypatch):
    """이전 UDS가 진짜 부재(absent)면 diff 수행(초판) + first_generation 플래그."""
    from workflow import impact_changes
    after_payload = {"function_details": {"1": {"name": "door_run"}}}

    def _fake(path_text):
        if path_text == "AFTER_UDS":
            return after_payload, "loaded"
        return {}, "absent"

    monkeypatch.setattr(impact_changes, "_load_payload_with_status", _fake)
    cl = impact_changes.build_change_log(
        run_id="t", trigger={"scm_id": "kj"},
        result={"actions": {"uds": {"status": "completed", "output_path": "AFTER_UDS", "functions": ["door_run"]}},
                "changed_function_types": {"door_run": "NEW"}, "impact": {}},
        previous_linked_docs={"uds": ""},
    )
    assert cl["documents"]["uds"].get("first_generation") is True


def test_build_change_log_sits_before_unreadable_null_delta_no_crash(monkeypatch):
    """M6: SITS before unreadable → delta=after-0 과대보고 대신 None + summary int(None) 크래시 없음."""
    from workflow import impact_changes

    def _fake(path_text):
        if path_text == "BEFORE_SITS_UNREADABLE":
            return {}, "unreadable"
        return {}, "absent"

    monkeypatch.setattr(impact_changes, "_load_payload_with_status", _fake)
    cl = impact_changes.build_change_log(
        run_id="t", trigger={"scm_id": "kj"},
        result={"actions": {"sits": {"status": "completed",
                                     "result": {"test_case_count": 10, "total_sub_cases": 30},
                                     "function_count": 3}},
                "changed_function_types": {}, "impact": {}},
        previous_linked_docs={"sits": "BEFORE_SITS_UNREADABLE"},
    )
    s = cl["documents"]["sits"]["summary"]
    assert s["before_test_case_count"] is None
    assert s["delta_cases"] is None
    assert cl["documents"]["sits"].get("before_unavailable") is True
    assert cl["summary"]["sits_delta_cases"] == 0  # int(None or 0) 크래시 방지
