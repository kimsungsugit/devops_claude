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
    # auto_generate defaults to False, so AUTO is downgraded to FLAG
    assert result["actions"]["uds"]["mode"] == "FLAG"
    assert result["actions"]["sts"]["mode"] == "FLAG"
    assert result["impact"]["indirect_1hop"] == ["door_helper"]
    assert result["impact"]["indirect_2hop"] == ["door_leaf"]
    assert any(p.name.startswith("impact_") for p in audit_dir.iterdir())


def test_run_impact_update_upgrades_body_to_signature_from_change_details(tmp_path, monkeypatch):
    """svn A:B editType가 .c를 BODY로 분류해도, unified diff에서 시그니처 이전≠이후 원문이
    나오면 SIGNATURE로 격상(SDS 자동 FLAG) + change_details에 원문(소문자 키) + display_name."""
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
            id="hdpdm01", name="HDPDM01", scm_type="svn",
            scm_url="https://svn.example/repo/trunk", source_root=str(tmp_path / "src"),
        )
    )
    # editType 경로처럼 .c edit → BODY로 분류됐다고 가정
    monkeypatch.setattr(
        impact_orchestrator, "classify_changed_functions",
        lambda *args, **kwargs: {"door_ctrl": "BODY"},
    )
    monkeypatch.setattr(
        impact_orchestrator, "_load_source_sections",
        lambda _sr: {"call_map": {}, "function_details_by_name": {
            "door_ctrl": {"name": "Door_Ctrl", "module_name": "door", "file": "Sources/APP/Ap_Door.c"}}},
    )
    # unified diff에서 실제 시그니처 변경 원문이 추출됐다고 가정(before≠after)
    monkeypatch.setattr(
        impact_orchestrator, "_collect_signature_changes",
        lambda *a, **k: {"Door_Ctrl": {"before": "int Door_Ctrl(int a)", "after": "int Door_Ctrl(int a, bool b)"}},
    )

    result = impact_orchestrator.run_impact_update(
        ChangeTrigger(
            trigger_type="jenkins", scm_id="hdpdm01", source_root=str(tmp_path / "src"),
            scm_type="svn", base_ref="",
            changed_files=["Ap_Door.c"], dry_run=True, targets=["uds", "sds", "sts"],
            metadata={
                "changed_files_source": "svn_revision_range",
                "baseline_revision": "100", "build_revision": "150",
                "changed_file_edit_types": {"Ap_Door.c": "edit"},
            },
        )
    )

    # BODY → SIGNATURE 격상 (editType 원본 케이스와 무관하게 조인)
    assert result["changed_function_types"]["door_ctrl"] == "SIGNATURE"
    # change_details: 이전→이후 원문(소문자 키, 프론트 조인 규약)
    assert result["change_details"]["door_ctrl"]["before"] == "int Door_Ctrl(int a)"
    assert result["change_details"]["door_ctrl"]["after"] == "int Door_Ctrl(int a, bool b)"
    # SIGNATURE.sds=FLAG → SDS 자동 검토(BODY였다면 sds='-')
    assert result["actions"]["sds"]["mode"] == "FLAG"
    # 표시용 원본 케이스명
    assert result["function_meta"]["door_ctrl"]["display_name"] == "Door_Ctrl"


def _setup_classification_env(tmp_path, monkeypatch, *, scm_type, classify_result):
    """granularity 테스트 공통 셋업 — registry/audit redirect + non-cloudium + stub."""
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import impact_audit, impact_orchestrator

    audit_dir = tmp_path / "audit"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json")
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", audit_dir)
    monkeypatch.setattr(impact_audit, "LOCK_PATH", audit_dir / ".run_lock")
    # 분기를 결정적으로 — file_mode 전역 싱글톤(라이브 cloudium)에 의존하지 않게 non-cloudium 고정.
    monkeypatch.setattr(impact_orchestrator, "_is_cloudium_mode", lambda: False)
    # 실 svn/git subprocess 회피(코드베이스 관례) — 시그니처 원문 수집은 빈 dict.
    monkeypatch.setattr(impact_orchestrator, "_collect_signature_changes", lambda *a, **k: {})
    scm_registry.register_entry(ScmRegisterRequest(
        id="kj", name="KJ", scm_type=scm_type,
        scm_url="https://svn.example/repo/trunk", source_root=str(tmp_path / "src")))
    monkeypatch.setattr(impact_orchestrator, "classify_changed_functions",
                        lambda *a, **k: dict(classify_result))
    monkeypatch.setattr(impact_orchestrator, "_load_source_sections",
                        lambda _sr: {"call_map": {}, "function_details_by_name": {
                            "foo": {"name": "Foo", "module_name": "m", "file": "a.c"}}})
    return impact_orchestrator


def test_run_impact_update_classification_granularity_file_for_edit_types(tmp_path, monkeypatch):
    """svn revision-range editType 경로 → classification.granularity='file'(파일단위 보수 분류)."""
    orch = _setup_classification_env(tmp_path, monkeypatch, scm_type="svn", classify_result={"foo": "BODY"})
    result = orch.run_impact_update(ChangeTrigger(
        trigger_type="jenkins", scm_id="kj", source_root=str(tmp_path / "src"),
        scm_type="svn", base_ref="", changed_files=["a.c"], dry_run=True, targets=["uds"],
        metadata={"changed_files_source": "svn_revision_range",
                  "baseline_revision": "100", "build_revision": "150",
                  "changed_file_edit_types": {"a.c": "edit"}}))
    assert result["classification"]["granularity"] == "file"
    assert result["classification"]["source"] == "svn_revision_range"
    assert result["classification"]["signature_distinguished"] is False


def test_run_impact_update_classification_granularity_line_for_local_diff(tmp_path, monkeypatch):
    """로컬 working-copy diff 경로(edit_types 없음, non-cloudium) → granularity='line'."""
    orch = _setup_classification_env(tmp_path, monkeypatch, scm_type="git", classify_result={"foo": "SIGNATURE"})
    result = orch.run_impact_update(ChangeTrigger(
        trigger_type="local", scm_id="kj", source_root=str(tmp_path / "src"),
        scm_type="git", base_ref="HEAD~1", changed_files=["a.c"], dry_run=True, targets=["uds"],
        metadata={}))
    assert result["classification"]["granularity"] == "line"
    assert result["classification"]["signature_distinguished"] is True


def _setup_precise_env(tmp_path, monkeypatch, *, blob, by_name=None):
    """A 정밀분류 테스트 공통 셋업 — 실 editType classify 사용(subprocess 없음), svn diff는 canned."""
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry, local_service
    from workflow import impact_audit, impact_orchestrator

    audit_dir = tmp_path / "audit"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json")
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", audit_dir)
    monkeypatch.setattr(impact_audit, "LOCK_PATH", audit_dir / ".run_lock")
    monkeypatch.setattr(impact_orchestrator, "_is_cloudium_mode", lambda: False)
    scm_registry.register_entry(ScmRegisterRequest(
        id="kj", name="KJ", scm_type="svn",
        scm_url="https://svn.example/repo/trunk", source_root=str(tmp_path / "src")))
    _default_by_name = {
        "foo_run": {"name": "Foo_Run", "module_name": "m", "file": "sources/pure.c"},
        "foo_extra": {"name": "Foo_Extra", "module_name": "m", "file": "sources/pure.c"},
        "bar_init": {"name": "Bar_Init", "module_name": "n", "file": "sources/modvar.c"},
        "bar_other": {"name": "Bar_Other", "module_name": "n", "file": "sources/modvar.c"},
    }
    monkeypatch.setattr(impact_orchestrator, "_load_source_sections", lambda _sr: {
        "call_map": {},
        "function_details_by_name": by_name if by_name is not None else _default_by_name,
    })
    calls = {"n": 0}

    def _fake_svn(**_k):
        calls["n"] += 1
        return {"rc": 0, "output": blob}

    monkeypatch.setattr(local_service, "svn_diff_unified", _fake_svn)
    monkeypatch.setattr(scm_registry, "resolve_scm_credentials", lambda **_k: ("u", "p", None))
    return impact_orchestrator, calls


def _precise_trigger(tmp_path, changed_files):
    return ChangeTrigger(
        trigger_type="jenkins", scm_id="kj", source_root=str(tmp_path / "src"),
        scm_type="svn", base_ref="", changed_files=changed_files, dry_run=True, targets=["uds"],
        metadata={"changed_files_source": "svn_revision_range",
                  "baseline_revision": "100", "build_revision": "150",
                  "changed_file_edit_types": {f: "edit" for f in changed_files}})


def test_run_impact_update_precise_narrowing_line_classified(tmp_path, monkeypatch):
    """A: 순수 본문 편집 .c(pure.c)는 라인변경 함수(foo_run)만 유지·foo_extra 제거,
    모듈스코프 var 파일(modvar.c)은 fattened 유지. granularity='line', svn diff는 1회(fetch-once)."""
    blob = "\n".join([
        "Index: sources/pure.c",
        "@@ -10,3 +10,4 @@ Foo_Run(void)",
        "-    return 0;",
        "+    x++;",
        "+    return x;",
        "Index: sources/modvar.c",
        "@@ -5,3 +5,3 @@ Bar_Init(void)",
        "-static uint8 s_Mode;",
        "+static uint8 s_Mode = 1;",
        "",
    ])
    orch, calls = _setup_precise_env(tmp_path, monkeypatch, blob=blob)
    result = orch.run_impact_update(_precise_trigger(tmp_path, ["sources/pure.c", "sources/modvar.c"]))
    ct = result["changed_function_types"]
    # pure.c=line_classified → 라인변경된 foo_run만 유지, foo_extra 제거
    assert "foo_run" in ct
    assert "foo_extra" not in ct
    # modvar.c=모듈스코프 var → fattened 유지(둘 다)
    assert "bar_init" in ct
    assert "bar_other" in ct
    # granularity 정직화: 라인증거(foo_run)와 파일단위 보수(bar_*)가 혼재 → "mixed".
    # (과거엔 일괄 "line"이라 단정해 프론트의 '보수 추정' 경고가 꺼졌다 — 과대보고 은폐.)
    assert result["classification"]["granularity"] == "mixed"
    # foo_run(pure.c 본문변경) + bar_init(modvar.c 라인변경 hunk 귀속) = 라인증거 2.
    # bar_other는 라인변경이 없는데 modvar.c가 narrow 불가(top-level var 변경)라 보수 포함된 passenger.
    assert result["classification"]["evidenced_function_count"] == 2
    assert result["classification"]["fattened_function_count"] == 1
    # 함수별 증거 출처(단일 출처) — 프론트는 function_diffs 유무 추론 대신 이 값을 쓴다.
    assert result["function_meta"]["foo_run"]["evidence"] == "line"
    assert result["function_meta"]["bar_init"]["evidence"] == "line"
    assert result["function_meta"]["bar_other"]["evidence"] == "file_fatten"
    # 투명성 필드: pure.c 1개 함수단위 축소, foo_extra 1개 제외(감사/프론트 노출)
    assert result["classification"]["line_classified_file_count"] == 1
    assert result["classification"]["narrow_removed_count"] == 1
    # fetch-once: svn_diff_unified 정확히 1회(분류+시그니처 공유)
    assert calls["n"] == 1


def test_run_impact_update_format_only_downgraded_to_file_fatten(tmp_path, monkeypatch):
    """포맷/이동만(의미 변경 없음) 함수는 직접변경(line)→파일영향(file_fatten)으로 강등되고 자체
    diff가 드롭된다. changed_types(impact 집합)는 불변 = under-report 0(안전)."""
    blob = "\n".join([
        "Index: sources/fmt.c",
        "@@ -10,3 +50,3 @@ Fmt_Fn(void)",   # 블록 이동: -/+ 동일 = 포맷/이동만
        "-    do_a();",
        "-    do_b();",
        "+    do_a();",
        "+    do_b();",
        "Index: sources/real.c",
        "@@ -5,2 +5,2 @@ Real_Fn(void)",     # 실 로직 변경(대조군)
        "-    x = 1;",
        "+    x = 2;",
        "",
    ])
    by_name = {
        "fmt_fn": {"name": "Fmt_Fn", "module_name": "m", "file": "sources/fmt.c"},
        "real_fn": {"name": "Real_Fn", "module_name": "n", "file": "sources/real.c"},
    }
    orch, _ = _setup_precise_env(tmp_path, monkeypatch, blob=blob, by_name=by_name)
    result = orch.run_impact_update(_precise_trigger(tmp_path, ["sources/fmt.c", "sources/real.c"]))
    ct = result["changed_function_types"]
    fm = result["function_meta"]
    fd = result["function_diffs"]
    # 포맷/이동만 → file_fatten 강등 + function_diffs drop, 단 changed_types엔 유지(impact 불변)
    assert fm["fmt_fn"]["evidence"] == "file_fatten"
    assert "fmt_fn" not in fd
    assert "fmt_fn" in ct
    # 실 변경(대조군) → line 유지 + diff 보유
    assert fm["real_fn"]["evidence"] == "line"
    assert "real_fn" in fd
    assert "x = 2" in fd["real_fn"]
    # deep-review W1: 강등 후 line+fatten 혼재 → granularity 'mixed'(honesty 불변식), signature_distinguished False
    assert result["classification"]["granularity"] == "mixed"
    assert result["classification"]["signature_distinguished"] is False


def test_run_impact_update_precise_fallback_on_bare_hunk(tmp_path, monkeypatch):
    """A: svn diff에 -x -p 컨텍스트 없음(bare @@) → positive-context 가드가 정밀분류 우회 →
    파일단위 보수 경로 유지(granularity='file', 파일 전체 함수 fattened)."""
    blob_bare = "\n".join([
        "Index: sources/pure.c",
        "@@ -10,3 +10,4 @@",  # bare — 함수 컨텍스트 없음(구버전 svn이 -p 무시한 경우)
        "-    return 0;",
        "+    return 1;",
        "",
    ])
    orch, _calls = _setup_precise_env(tmp_path, monkeypatch, blob=blob_bare)
    result = orch.run_impact_update(_precise_trigger(tmp_path, ["sources/pure.c"]))
    ct = result["changed_function_types"]
    # 폴백 → pure.c 전체 함수 fattened(foo_run, foo_extra 둘 다)
    assert "foo_run" in ct
    assert "foo_extra" in ct
    assert result["classification"]["granularity"] == "file"


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
        lambda target, trigger, changed_types, impact_groups, by_name=None, linked_doc="", ai_guide=None, **_kw: str(tmp_path / f"{target}_review.md"),
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
    # auto_generate defaults to False, so all AUTO actions are downgraded to FLAG
    assert result["actions"]["uds"]["status"] == "review_required"
    assert result["actions"]["uds"]["artifact_path"].endswith("uds_review.md")
    assert result["actions"]["sts"]["artifact_path"].endswith("sts_review.md")
    assert result["change_log"]["path"].endswith(".json")
    assert updated is not None
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
    # auto_generate defaults to False, so AUTO is downgraded to FLAG
    assert result["actions"]["uds"]["mode"] == "FLAG"
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


def test_run_impact_update_sits_uses_cross_module_impact(tmp_path, monkeypatch):
    """SITS 대상이면 module 경계를 넘는 영향을 별도(cross-module)로 계산한다.
    uds(module-scoped)는 cross-module callee를 제외하지만 SITS는 포함해야 한다."""
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import impact_audit, impact_orchestrator

    reg_path = tmp_path / "config" / "scm_registry.json"
    audit_dir = tmp_path / "audit"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", reg_path)
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", audit_dir)
    monkeypatch.setattr(impact_audit, "LOCK_PATH", audit_dir / ".run_lock")
    scm_registry.register_entry(
        ScmRegisterRequest(id="x", name="X", scm_type="git", source_root=str(tmp_path / "src"))
    )

    monkeypatch.setattr(
        impact_orchestrator, "classify_changed_functions",
        lambda *a, **k: {"seed": "SIGNATURE"},
    )
    monkeypatch.setattr(
        impact_orchestrator, "_load_source_sections",
        lambda _r: {
            "call_map": {"seed": ["cross_fn"]},
            "function_details_by_name": {
                "seed": {"module_name": "a", "file": "Sources/APP/a/Ap_A.c"},
                "cross_fn": {"module_name": "b", "file": "Sources/APP/b/Ap_B.c"},
            },
        },
    )

    result = impact_orchestrator.run_impact_update(
        ChangeTrigger(
            trigger_type="local", scm_id="x", source_root=str(tmp_path / "src"),
            scm_type="git", base_ref="HEAD~1", changed_files=["Ap_A.c"],
            dry_run=True, targets=["uds", "sits"], metadata={},
        )
    )

    assert result["ok"] is True
    # 기본값이 cross-module(same_module_only=False)로 바뀌었다 — 다른 모듈에서 변경 함수를 호출하는
    # 함수(cross_fn)가 **주 영향 집합(impact)** 에 포함된다. 과거(module=파일 스코핑)엔 fatten이 이미
    # 같은 파일 함수를 전부 seed로 넣어 indirect가 구조적으로 0이 됐고, 그 결과 cross_fn이 가이드
    # 표·간접영향 스탯·hop 필터에서 통째로 사라졌다(under-report = ISO 위험 방향).
    assert result["impact"]["indirect_1hop"] == ["cross_fn"]
    # SITS cross 뷰는 계약 일관성 위해 항상 노출(가지치기 꺼져 있으면 impact와 동일)
    assert result["impact_sits_cross"]["indirect_1hop"] == ["cross_fn"]
    # actions.sits는 영향 전체(impacted_all)를 담는다
    assert "cross_fn" in result["actions"]["sits"]["functions"]
    # uds/suts/sts/sds actions는 설계상 '직접 변경 함수'만 담는다(간접은 sits 몫) — 계약 불변
    assert result["actions"]["uds"]["functions"] == ["seed"]

    # 옵션으로 module 가지치기를 켜면 기존(module-scoped) 동작 — uds 제외, SITS는 cross 포함.
    scoped = impact_orchestrator.run_impact_update(
        ChangeTrigger(
            trigger_type="local", scm_id="x", source_root=str(tmp_path / "src"),
            scm_type="git", base_ref="HEAD~1", changed_files=["Ap_A.c"],
            dry_run=True, targets=["uds", "sits"], metadata={},
        ),
        options=impact_orchestrator.ImpactOptions(same_module_only=True),
    )
    assert scoped["impact"]["indirect_1hop"] == []
    assert scoped["impact_sits_cross"]["indirect_1hop"] == ["cross_fn"]
    assert any("SITS cross-module" in w for w in scoped["warnings"])
    assert "cross_fn" in scoped["actions"]["sits"]["functions"]
    assert "cross_fn" not in scoped["actions"]["uds"]["functions"]


def test_run_impact_update_no_sits_has_no_cross_field(tmp_path, monkeypatch):
    """SITS 미대상이면 cross-module 계산을 하지 않는다(불필요 연산 회피)."""
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import impact_audit, impact_orchestrator

    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json")
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setattr(impact_audit, "LOCK_PATH", tmp_path / "audit" / ".run_lock")
    scm_registry.register_entry(
        ScmRegisterRequest(id="x", name="X", scm_type="git", source_root=str(tmp_path / "src"))
    )
    monkeypatch.setattr(impact_orchestrator, "classify_changed_functions", lambda *a, **k: {"seed": "BODY"})
    monkeypatch.setattr(
        impact_orchestrator, "_load_source_sections",
        lambda _r: {"call_map": {"seed": ["cross_fn"]},
                    "function_details_by_name": {
                        "seed": {"module_name": "a", "file": "Sources/APP/a/Ap_A.c"},
                        "cross_fn": {"module_name": "b", "file": "Sources/APP/b/Ap_B.c"}}},
    )
    result = impact_orchestrator.run_impact_update(
        ChangeTrigger(trigger_type="local", scm_id="x", source_root=str(tmp_path / "src"),
                      scm_type="git", base_ref="HEAD~1", changed_files=["Ap_A.c"],
                      dry_run=True, targets=["uds", "suts"], metadata={})
    )
    assert result["ok"] is True
    assert "impact_sits_cross" not in result


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


def test_resolve_changed_types_preserves_classify_kind():
    """classify가 함수별로 분류한 정밀 kind(SIGNATURE/NEW)를 _resolve가 보존한다
    (확장자 BODY로 평탄화하지 않음 — 시그니처 변경 가이드/ SDS FLAG 라우팅 정확성)."""
    from workflow import impact_orchestrator

    resolved = impact_orchestrator._resolve_changed_types_to_functions(
        {"Ap_Door_Init": "SIGNATURE", "Ap_Door_Reset": "NEW", "Ap_Door_Run": "SIGNATURE"},
        ["Ap_Door.c"],
        {
            "ap_door_init": {"file": "D:/p/Sources/APP/Ap_Door.c"},
            "ap_door_run": {"file": "D:/p/Sources/APP/Ap_Door.c"},
            "ap_door_reset": {"file": "D:/p/Sources/APP/Ap_Door.c"},
        },
    )
    assert resolved == {
        "ap_door_init": "SIGNATURE",
        "ap_door_run": "SIGNATURE",
        "ap_door_reset": "NEW",
    }


def test_run_impact_update_asil_differentiation_and_evidence(tmp_path, monkeypatch):
    """ASIL D 직접 변경 → sds 강제 FLAG(BODY는 본래 '-') + MC/DC 플래그 + function_meta +
    regression_test_set + asil 요약(ISO 증거 보강)."""
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import impact_audit, impact_orchestrator

    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json")
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setattr(impact_audit, "LOCK_PATH", tmp_path / "audit" / ".run_lock")
    scm_registry.register_entry(
        ScmRegisterRequest(id="x", name="X", scm_type="git", source_root=str(tmp_path / "src"))
    )
    monkeypatch.setattr(impact_orchestrator, "classify_changed_functions", lambda *a, **k: {"safety_fn": "BODY"})
    monkeypatch.setattr(
        impact_orchestrator, "_load_source_sections",
        lambda _r: {
            "call_map": {},
            "function_details_by_name": {
                "safety_fn": {"module_name": "door", "file": "Sources/APP/Ap_X.c", "asil": "D"},
            },
        },
    )
    result = impact_orchestrator.run_impact_update(
        ChangeTrigger(
            trigger_type="local", scm_id="x", source_root=str(tmp_path / "src"),
            scm_type="git", base_ref="HEAD", changed_files=["Ap_X.c"],
            dry_run=True, targets=["uds", "sts", "sds"], metadata={},
        )
    )
    assert result["ok"] is True
    # ASIL 요약
    assert result["asil"]["max_changed"] == "D"
    assert result["asil"]["escalation"] is True
    assert result["asil"]["mcdc_required"] is True
    assert result["asil"]["coverage_target"] == "MC/DC"
    # function_meta에 ASIL D
    assert result["function_meta"]["safety_fn"]["asil"] == "D"
    # ASIL 차등 게이트: BODY는 본래 sds='-'(skip)이나 ASIL D 에스컬레이션으로 FLAG 강제
    assert result["actions"]["sds"]["mode"] == "FLAG"
    # 시험 산출물에 MC/DC 재검증 플래그
    assert result["actions"]["sts"].get("mcdc_required") is True
    # 회귀시험 선정 요약
    assert result["regression_test_set"]["summary"]["coverage_target"] == "MC/DC"
    assert result["regression_test_set"]["summary"]["impacted_function_count"] >= 1
    # 경고에 ASIL escalation
    assert any("ASIL escalation" in w for w in result["warnings"])


def _reg_demo(tmp_path, monkeypatch, classify, by_name):
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import impact_audit, impact_orchestrator
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json")
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setattr(impact_audit, "LOCK_PATH", tmp_path / "audit" / ".run_lock")
    scm_registry.register_entry(ScmRegisterRequest(id="x", name="X", scm_type="git", source_root=str(tmp_path / "src")))
    monkeypatch.setattr(impact_orchestrator, "classify_changed_functions", lambda *a, **k: dict(classify))
    monkeypatch.setattr(impact_orchestrator, "_load_source_sections",
                        lambda _r: {"call_map": {}, "function_details_by_name": by_name})
    monkeypatch.setattr(impact_orchestrator, "_is_cloudium_mode", lambda: False)  # 이 테스트들은 local 가정
    return impact_orchestrator


def test_info_warning_does_not_downgrade_auto(tmp_path, monkeypatch):
    """정보성 경고(jenkins changeSet)만 있으면 auto_generate AUTO를 강등하지 않는다(C1 회귀)."""
    io = _reg_demo(tmp_path, monkeypatch, {"foo": "BODY"},
                   {"foo": {"module_name": "m", "file": "Sources/APP/Ap_X.c", "asil": ""}})
    result = io.run_impact_update(ChangeTrigger(
        trigger_type="jenkins", scm_id="x", source_root=str(tmp_path / "src"), scm_type="git",
        base_ref="HEAD", changed_files=["Ap_X.c"], dry_run=True, auto_generate=True,
        targets=["uds"], metadata={"changed_files_source": "jenkins_changeset"}))
    assert result["actions"]["uds"]["mode"] == "AUTO"   # 정보성 경고는 AUTO 봉쇄 안 함
    assert any("changeSet" in w or "changeset" in w for w in result["warnings"])


def test_asil_escalation_downgrades_auto_and_normalizes_prefix(tmp_path, monkeypatch):
    """ASIL B+ 직접변경이면 auto_generate AUTO를 검토(FLAG)로 강등 + 'ASIL D' 접두어 정규화(W1)."""
    io = _reg_demo(tmp_path, monkeypatch, {"safety": "BODY"},
                   {"safety": {"module_name": "m", "file": "Sources/APP/Ap_X.c", "asil": "ASIL D"}})
    result = io.run_impact_update(ChangeTrigger(
        trigger_type="local", scm_id="x", source_root=str(tmp_path / "src"), scm_type="git",
        base_ref="HEAD", changed_files=["Ap_X.c"], dry_run=True, auto_generate=True,
        targets=["uds"], metadata={}))
    assert result["asil"]["max_changed"] == "D"          # 'ASIL D' → 'D' 정규화
    assert result["asil"]["escalation"] is True
    assert result["actions"]["uds"]["mode"] == "FLAG"    # 안전: AUTO 봉쇄


def test_run_impact_update_includes_coverage_gap(tmp_path, monkeypatch):
    """linked vectorcast가 있으면 coverage_gap을 result에 싣고, ASIL C/D 미달 시 검토 강등 + 경고."""
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import coverage_gap as cg, impact_audit, impact_orchestrator

    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json")
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setattr(impact_audit, "LOCK_PATH", tmp_path / "audit" / ".run_lock")
    scm_registry.register_entry(ScmRegisterRequest(
        id="x", name="X", scm_type="git", source_root=str(tmp_path / "src"),
        linked_docs={"vectorcast": ["rag.json"]},
    ))
    monkeypatch.setattr(impact_orchestrator, "_is_cloudium_mode", lambda: False)
    monkeypatch.setattr(impact_orchestrator, "classify_changed_functions", lambda *a, **k: {"safety": "BODY"})
    monkeypatch.setattr(
        impact_orchestrator, "_load_source_sections",
        lambda _r: {"call_map": {}, "function_details_by_name": {
            "safety": {"module_name": "m", "file": "Sources/APP/Ap_X.c", "asil": "D"}}},
    )
    monkeypatch.setattr(cg, "compute_coverage_gap", lambda *a, **k: {
        "available": True,
        "functions": [{"function": "safety", "asil": "D", "target_metric": "mcdc",
                       "current_rate": 0.8, "meets_target": False, "delta": -0.1}],
        "summary": {"evaluated": 1, "below_target": 1, "regressed": 1, "had_baseline": True},
    })
    result = impact_orchestrator.run_impact_update(ChangeTrigger(
        trigger_type="local", scm_id="x", source_root=str(tmp_path / "src"), scm_type="git",
        base_ref="HEAD", changed_files=["Ap_X.c"], dry_run=True, auto_generate=True,
        targets=["uds"], metadata={}))
    assert result["coverage_gap"]["available"] is True
    assert result["coverage_gap"]["summary"]["below_target"] == 1
    assert result["actions"]["uds"]["mode"] == "FLAG"   # ASIL C/D 커버리지 미달 → 검토 강등
    assert any("목표 미달" in w for w in result["warnings"])
    assert any("커버리지 회귀" in w for w in result["warnings"])


def test_run_impact_update_no_coverage_data_with_safety_promotes(tmp_path, monkeypatch):
    """vectorcast 연결됐으나 커버리지 데이터 없음 + ASIL C/D 영향 → 미검증을 안전 통과로 보지 않고 경고+검토 강등."""
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import coverage_gap as cg, impact_audit, impact_orchestrator

    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json")
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setattr(impact_audit, "LOCK_PATH", tmp_path / "audit" / ".run_lock")
    scm_registry.register_entry(ScmRegisterRequest(
        id="x", name="X", scm_type="git", source_root=str(tmp_path / "src"),
        linked_docs={"vectorcast": ["rag.json"]},
    ))
    monkeypatch.setattr(impact_orchestrator, "_is_cloudium_mode", lambda: False)
    monkeypatch.setattr(impact_orchestrator, "classify_changed_functions", lambda *a, **k: {"safety": "BODY"})
    monkeypatch.setattr(
        impact_orchestrator, "_load_source_sections",
        lambda _r: {"call_map": {}, "function_details_by_name": {
            "safety": {"module_name": "m", "file": "Sources/APP/Ap_X.c", "asil": "D"}}},
    )
    # 커버리지 데이터 없음(RAG metrics 미생성) 시나리오
    monkeypatch.setattr(cg, "compute_coverage_gap", lambda *a, **k: {"available": False, "functions": [], "summary": {}})
    result = impact_orchestrator.run_impact_update(ChangeTrigger(
        trigger_type="local", scm_id="x", source_root=str(tmp_path / "src"), scm_type="git",
        base_ref="HEAD", changed_files=["Ap_X.c"], dry_run=True, auto_generate=True,
        targets=["uds"], metadata={}))
    assert any("커버리지 데이터 없음" in w for w in result["warnings"])
    assert result["actions"]["uds"]["mode"] == "FLAG"   # 증거 없음 → 안전측 검토


def test_resolve_preserves_deleted_functions():
    """삭제된 함수는 현재 소스(by_name)에 없어도 DELETE로 보존 — SUTS/SITS TC 제거 가이드 트리거."""
    from workflow import impact_orchestrator

    resolved = impact_orchestrator._resolve_changed_types_to_functions(
        {"ap_keep": "BODY", "ap_old_fn": "DELETE"},
        ["Ap_Mod.c"],
        {"ap_keep": {"file": "D:/p/Sources/APP/Ap_Mod.c"}},  # ap_old_fn 부재(삭제됨)
    )
    assert resolved["ap_keep"] == "BODY"
    assert resolved["ap_old_fn"] == "DELETE"


def test_resolve_applies_edit_type_new_to_file_functions():
    """editType=add 파일의 함수는 확장자 기본값(BODY) 대신 NEW로 격상(Phase 3 cloudium 정밀)."""
    from workflow import impact_orchestrator

    resolved = impact_orchestrator._resolve_changed_types_to_functions(
        {"ap_new": "NEW"},                       # classify(edit_types)의 stem 키
        ["Sources/APP/Ap_New.c"],
        {"ap_new_fn": {"file": "D:/p/Sources/APP/Ap_New.c"}},
        edit_types={"Sources/APP/Ap_New.c": "add"},
    )
    assert resolved["ap_new_fn"] == "NEW"        # 함수 단위로 NEW 전파


def test_resolve_local_diff_func_kind_overrides_edit_type():
    """로컬 diff가 함수별 정밀 kind(SIGNATURE 등)를 준 경우, 파일 editType 기본값보다 우선한다."""
    from workflow import impact_orchestrator

    resolved = impact_orchestrator._resolve_changed_types_to_functions(
        {"ap_sig": "SIGNATURE"},                 # func 단위 정밀 kind
        ["Sources/APP/Ap_New.c"],
        {"ap_sig": {"file": "D:/p/Sources/APP/Ap_New.c"}},
        edit_types={"Sources/APP/Ap_New.c": "add"},
    )
    assert resolved["ap_sig"] == "SIGNATURE"     # func 정밀 kind 우선(editType 기본값 무시)


def test_run_impact_update_uses_edit_types_and_skips_local_diff(tmp_path, monkeypatch):
    """jenkins_changeset + edit_types → 로컬 diff 생략 + add→NEW/delete→DELETE 전파 + 경고 정확화."""
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import delta_update, impact_audit, impact_orchestrator

    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json")
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setattr(impact_audit, "LOCK_PATH", tmp_path / "audit" / ".run_lock")
    scm_registry.register_entry(ScmRegisterRequest(
        id="x", name="X", scm_type="svn", source_root=str(tmp_path / "src")))
    monkeypatch.setattr(impact_orchestrator, "_is_cloudium_mode", lambda: False)  # local 모드 + changeset
    # classify는 진짜 함수를 써야 editType 경로를 검증 — 대신 로컬 diff는 호출되면 안 됨.
    monkeypatch.setattr(delta_update, "_run_unified_diff",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("editType 경로에서 diff 금지")))
    monkeypatch.setattr(impact_orchestrator, "_load_source_sections",
                        lambda _r: {"call_map": {}, "function_details_by_name": {
                            "ap_new_fn": {"module_name": "m", "file": "Sources/APP/Ap_New.c", "asil": ""}}})

    result = impact_orchestrator.run_impact_update(ChangeTrigger(
        trigger_type="jenkins", scm_id="x", source_root=str(tmp_path / "src"), scm_type="svn",
        base_ref="", changed_files=["Sources/APP/Ap_New.c", "Sources/APP/Ap_Old.c"], dry_run=True,
        auto_generate=False, targets=["uds", "suts"],
        metadata={"changed_files_source": "jenkins_changeset",
                  "changed_file_edit_types": {"Sources/APP/Ap_New.c": "add",
                                              "Sources/APP/Ap_Old.c": "delete"}}))
    cft = result["changed_function_types"]
    assert cft.get("ap_new_fn") == "NEW"        # add 파일 함수 → NEW 전파
    assert cft.get("ap_old") == "DELETE"        # delete 파일(by_name 부재) → stem DELETE 보존
    assert any("editType" in w for w in result["warnings"])  # 경고가 editType 기반으로 정확화


def test_resolve_prefers_full_path_over_basename_collision():
    """동명 파일이 여러 모듈에 있을 때, 변경 경로와 full-path 일치하는 함수만 — basename 과대매칭 방지."""
    from workflow import impact_orchestrator

    resolved = impact_orchestrator._resolve_changed_types_to_functions(
        {"comm_foo": "BODY"},
        ["comm/Foo.c"],
        {
            "comm_foo": {"file": "D:/p/Sources/comm/Foo.c"},
            "app_foo": {"file": "D:/p/Sources/app/Foo.c"},  # 동명·타모듈
        },
    )
    assert "comm_foo" in resolved
    assert "app_foo" not in resolved


# --- 회귀 TC 로더(cloudium worker 경유) — B1 fix 검증 ---------------------------

def _fake_resolver(read_bytes_impl):
    class _R:
        def read_bytes(self, path):
            return read_bytes_impl(path)
    return _R()


def test_load_suts_fn_tcs_reads_via_worker_not_direct_open(monkeypatch):
    """cloudium: SUTS를 직접 load_workbook이 아니라 worker read_bytes로 읽고 파싱한다."""
    from workflow import impact_orchestrator as orch
    import backend.services.file_resolver as fr
    import tools.export_suts_vectorcast as ev

    monkeypatch.setattr(fr, "get_resolver", lambda: _fake_resolver(lambda p: b"XLSM-BYTES"))
    captured = {}

    def fake_build(path, *, project_id="HDPDM01", target_functions=None, source_bytes=None):
        captured["source_bytes"] = source_bytes
        return {"units": [
            {"unit_name": "door_run", "test_cases": [{"base_tc_id": "TC01"}, {"base_tc_id": "TC02"}, {"base_tc_id": "TC01"}]},
            {"unit_name": "", "test_cases": [{"base_tc_id": "TCX"}]},  # 이름 없는 유닛 스킵
        ]}

    monkeypatch.setattr(ev, "build_vectorcast_model", fake_build)
    warns = []
    out = orch._load_suts_fn_tcs("U:/x/SUTS.xlsm", ["door_run"], warn_sink=warns)
    assert out == {"door_run": ["TC01", "TC02"]}  # dedup 유지
    assert captured["source_bytes"] == b"XLSM-BYTES"  # 직접 open 아님 — worker bytes 경유
    assert warns == []


def test_load_suts_fn_tcs_permission_error_warns_and_empty(monkeypatch):
    """cloudium worker 접근 실패는 silent 0이 아니라 warn_sink에 사유를 남긴다."""
    from workflow import impact_orchestrator as orch
    import backend.services.file_resolver as fr

    def _raise(_p):
        raise PermissionError("cloudium worker down")

    monkeypatch.setattr(fr, "get_resolver", lambda: _fake_resolver(_raise))
    warns = []
    out = orch._load_suts_fn_tcs("U:/x/SUTS.xlsm", ["door_run"], warn_sink=warns)
    assert out == {}
    assert any("접근 실패" in w for w in warns)


def test_load_suts_fn_tcs_no_unit_match_warns(monkeypatch):
    """유닛명 매칭 0(이름 규칙 불일치)도 사유를 남긴다(silent 0 방지)."""
    from workflow import impact_orchestrator as orch
    import backend.services.file_resolver as fr
    import tools.export_suts_vectorcast as ev

    monkeypatch.setattr(fr, "get_resolver", lambda: _fake_resolver(lambda p: b"BYTES"))
    monkeypatch.setattr(ev, "build_vectorcast_model", lambda *a, **k: {"units": []})
    warns = []
    out = orch._load_suts_fn_tcs("U:/x/SUTS.xlsm", ["door_run"], warn_sink=warns)
    assert out == {}
    assert any("매칭" in w for w in warns)


def test_load_sits_fn_chains_reads_via_worker(monkeypatch):
    """SITS 중간 JSON을 worker read_bytes로 읽고 flagged 함수의 체인만 집계한다."""
    from workflow import impact_orchestrator as orch
    import backend.services.file_resolver as fr
    import json as _json

    payload = _json.dumps({"integrations": [
        {"entry_fn": "door_run", "call_chain": "a->b", "tc_id": "IT01"},
        {"entry_fn": "other", "call_chain": "x", "tc_id": "IT99"},
    ]}).encode("utf-8")
    monkeypatch.setattr(fr, "get_resolver", lambda: _fake_resolver(lambda p: payload))
    warns = []
    out = orch._load_sits_fn_chains("U:/x/SITS.xlsm", ["door_run"], warn_sink=warns)
    assert out == {"door_run": ["IT01: a->b"]}
    assert warns == []


def test_load_sits_fn_chains_missing_intermediate_warns(monkeypatch):
    """중간파일 부재(FileNotFoundError)는 정당한 0이되 사유를 남긴다."""
    from workflow import impact_orchestrator as orch
    import backend.services.file_resolver as fr

    def _raise(p):
        raise FileNotFoundError(p)

    monkeypatch.setattr(fr, "get_resolver", lambda: _fake_resolver(_raise))
    warns = []
    out = orch._load_sits_fn_chains("U:/x/SITS.xlsm", ["door_run"], warn_sink=warns)
    assert out == {}
    assert any("중간파일 미생성" in w for w in warns)


def test_multi_file_same_name_function_not_dropped(tmp_path, monkeypatch):
    """동일 이름 함수가 두 파일에 정의될 때, 어느 파일이 바뀌어도 그 함수를 놓치지 않는다.

    회귀(2라운드 연속 놓친 버그): AST dedup이 두 번째 정의를 **파일 경로째** 버려서 by_name에는
    한 사본의 file만 남는다. 그 상태에서 다른 파일이 바뀌면
      - full_hits(정확 경로 매칭)에 그 함수가 안 잡히고
      - `resolved.update(full_hits or base_hits)` 규칙상 basename 폴백도 무시돼
    **실제로 변경된 안전 함수(EEPROM 무결성 등)가 영향 집합에서 통째로 사라진다**(under-report).
    → sections["function_collisions"]로 정의 파일 전체를 넘겨 해결.
    """
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import impact_audit, impact_orchestrator

    audit_dir = tmp_path / "audit"
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json")
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", audit_dir)
    monkeypatch.setattr(impact_audit, "_RUN_FILE_LOCKS", {})
    monkeypatch.setattr(impact_audit, "_RUN_INTRA_LOCKS", {})
    monkeypatch.setattr(impact_audit, "_RUN_LOCK_OWNERS", {})
    scm_registry.register_entry(
        ScmRegisterRequest(
            id="coll", name="COLL", scm_type="git",
            scm_url="https://example/repo.git", source_root=str(tmp_path / "src"),
        )
    )
    monkeypatch.setattr(impact_orchestrator, "_is_cloudium_mode", lambda: False)
    monkeypatch.setattr(impact_orchestrator, "_collect_signature_changes", lambda *a, **k: {})
    # classify는 변경 파일의 함수 하나만 지목(실제 hunk 기반과 동일)
    monkeypatch.setattr(
        impact_orchestrator, "classify_changed_functions",
        lambda *a, **k: {"eeprom_src_only": "BODY"},
    )
    # by_name은 last-wins라 eeprom_setbyte의 file이 Generated_Code만 가리킨다(현실 재현).
    # function_collisions가 두 정의 파일을 모두 알려준다.
    monkeypatch.setattr(
        impact_orchestrator, "_load_source_sections",
        lambda *a, **k: {
            "function_details_by_name": {
                "eeprom_setbyte": {"name": "eeprom_setbyte", "asil": "D",
                                   "file": "src/Generated_Code/EEPROM.c", "module_name": "EEPROM"},
                "eeprom_src_only": {"name": "eeprom_src_only", "asil": "QM",
                                    "file": "src/Sources/Eeprom/EEPROM.c", "module_name": "EEPROM"},
            },
            "function_collisions": {
                "eeprom_setbyte": {
                    "files": ["src/Generated_Code/EEPROM.c", "src/Sources/Eeprom/EEPROM.c"],
                    "asil": "D",
                },
            },
            "call_map": {},
        },
    )

    result = impact_orchestrator.run_impact_update(
        ChangeTrigger(
            trigger_type="local", scm_id="coll", source_root=str(tmp_path / "src"),
            scm_type="git", base_ref="HEAD~1",
            changed_files=["Sources/Eeprom/EEPROM.c"],  # 두 번째 정의가 있는 파일만 변경
            dry_run=True, targets=["uds"], metadata={},
        )
    )
    assert result["ok"] is True
    ct = result["changed_function_types"]
    # 변경 파일의 고유 함수 + **충돌 사본이 있는 eeprom_setbyte(ASIL D)** 둘 다 잡혀야 한다.
    assert "eeprom_src_only" in ct
    assert "eeprom_setbyte" in ct, "다중정의 안전 함수가 영향 집합에서 누락됨(under-report)"
    # ASIL도 두 사본 중 높은 등급(D)이 유지돼 escalation/MC-DC 게이트가 발동한다
    assert result["function_meta"]["eeprom_setbyte"]["asil"] == "D"
    assert result["asil"]["escalation"] is True
    assert result["asil"]["mcdc_required"] is True


def test_bfs_cap_scales_with_seed_count_so_2hop_computes(tmp_path, monkeypatch):
    """seeds가 승격 임계(50)를 넘어도 BFS 탐색은 seeds에 맞춰 넉넉히 → 2-hop이 실제로 계산된다.

    회귀: max_impacted_functions=50이 (1)탐색상한 (2)승격임계를 겸해서, cross-module 기본화로 seeds가
    수백이 되면 seeds만으로 이미 초과 → depth1 직후 중단 → indirect_2hop이 **항상 미계산**이었다.
    """
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import impact_audit, impact_orchestrator

    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json")
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setattr(impact_audit, "_RUN_FILE_LOCKS", {})
    monkeypatch.setattr(impact_audit, "_RUN_INTRA_LOCKS", {})
    monkeypatch.setattr(impact_audit, "_RUN_LOCK_OWNERS", {})
    scm_registry.register_entry(ScmRegisterRequest(
        id="big", name="BIG", scm_type="git",
        scm_url="https://example/repo.git", source_root=str(tmp_path / "src")))
    monkeypatch.setattr(impact_orchestrator, "_is_cloudium_mode", lambda: False)
    monkeypatch.setattr(impact_orchestrator, "_collect_signature_changes", lambda *a, **k: {})

    # 60개 변경 함수(seeds) — 승격 임계 50 초과. 각 seed가 고유 1-hop, 그 이웃이 고유 2-hop.
    N = 60
    changed = {f"seed{i}": "BODY" for i in range(N)}
    bn = {}
    call_map = {}
    for i in range(N):
        bn[f"seed{i}"] = {"name": f"seed{i}", "file": f"Sources/APP/f{i}.c", "module_name": "app"}
        bn[f"n{i}"] = {"name": f"n{i}", "file": f"Sources/APP/n{i}.c", "module_name": "app"}
        bn[f"m{i}"] = {"name": f"m{i}", "file": f"Sources/APP/m{i}.c", "module_name": "app"}
        call_map[f"seed{i}"] = [f"n{i}"]
        call_map[f"n{i}"] = [f"m{i}"]
    monkeypatch.setattr(impact_orchestrator, "classify_changed_functions", lambda *a, **k: dict(changed))
    monkeypatch.setattr(impact_orchestrator, "_load_source_sections",
                        lambda *a, **k: {"call_map": call_map, "function_details_by_name": bn})

    # 변경 파일 = 모든 seed 파일(각 seed가 자기 파일). classify가 seed 전부를 지목하도록.
    result = impact_orchestrator.run_impact_update(ChangeTrigger(
        trigger_type="local", scm_id="big", source_root=str(tmp_path / "src"),
        scm_type="git", base_ref="HEAD~1", changed_files=[f"f{i}.c" for i in range(N)],
        dry_run=True, targets=["uds"], metadata={}))
    assert result["ok"] is True
    imp = result["impact"]
    assert len(imp["direct"]) == N               # seed 60개
    assert len(imp["indirect_1hop"]) == N        # 1-hop 완전(cap이 이걸 자르지 않음)
    assert len(imp["indirect_2hop"]) == N        # 2-hop이 실제로 계산됨(과거엔 0)
    assert result["impact_traversal"]["truncated"] is False
    # 승격은 여전히 정상(seeds 60 > 임계 50)
    assert any("exceeded limit" in w for w in result["warnings"])
