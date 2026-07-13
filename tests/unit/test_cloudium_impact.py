from __future__ import annotations

import pytest

from workflow.change_trigger import ChangeTrigger


def test_is_cloudium_mode_reflects_resolver(monkeypatch):
    from workflow import impact_orchestrator as io
    import backend.services.file_resolver as fr

    class _Fake:
        mode = "cloudium"
    monkeypatch.setattr(fr, "get_resolver", lambda: _Fake())
    assert io._is_cloudium_mode() is True

    class _Local:
        mode = "local"
    monkeypatch.setattr(fr, "get_resolver", lambda: _Local())
    assert io._is_cloudium_mode() is False


def test_generate_uds_source_sections_via_cloudium_resolver(monkeypatch):
    """cloudium 모드면 os.walk/open 없이 resolver(list_dir+read_bytes)로 소스를 읽는다."""
    import report_gen.uds_generator as ug
    import backend.services.file_resolver as fr

    calls = {"list": 0, "read": 0, "walk_blocked": True}
    fake_c = b"void Ap_Door_Run(void){ Ap_Helper(); }\nvoid Ap_Helper(void){}\n"

    class _FakeCloud:
        mode = "cloudium"
        def is_dir(self, p):
            return str(p) == "//remote/src"
        def list_dir(self, p, pattern="*", recursive=False, include_dirs=False):
            calls["list"] += 1
            return ["//remote/src/Ap_Door.c"]
        def read_bytes(self, p):
            calls["read"] += 1
            return fake_c

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeCloud())
    # os.walk가 불려선 안 됨(원격경로라 로컬에서 아무것도 못 찾음 → 호출 자체가 버그)
    monkeypatch.setattr(ug.os, "walk", lambda *a, **k: (_ for _ in ()).throw(AssertionError("os.walk must not run in cloudium")))

    sections = ug.generate_uds_source_sections("//remote/src")
    assert isinstance(sections, dict)
    assert calls["list"] >= 1   # 소스 enumerate가 resolver 경유
    assert calls["read"] >= 1   # 소스 read가 resolver 경유


def test_run_impact_update_cloudium_downgrades_auto_and_skips_diff(tmp_path, monkeypatch):
    """cloudium: classify subprocess 생략 + AUTO→FLAG 강등 + 경고."""
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import impact_audit, impact_orchestrator

    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json")
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setattr(impact_audit, "LOCK_PATH", tmp_path / "audit" / ".run_lock")
    scm_registry.register_entry(
        ScmRegisterRequest(id="x", name="X", scm_type="svn", source_root="//remote/src")
    )

    monkeypatch.setattr(impact_orchestrator, "_is_cloudium_mode", lambda: True)

    classify_calls = {"n": 0}
    def _spy_classify(*a, **k):
        classify_calls["n"] += 1
        return {"unexpected": "BODY"}
    monkeypatch.setattr(impact_orchestrator, "classify_changed_functions", _spy_classify)

    monkeypatch.setattr(
        impact_orchestrator, "_load_source_sections",
        lambda _r: {
            "call_map": {"door_run": ["door_helper"]},
            "function_details_by_name": {
                "door_run": {"module_name": "door", "file": "Sources/APP/Ap_Door.c"},
                "door_helper": {"module_name": "door", "file": "Sources/APP/Ap_Door.c"},
            },
        },
    )

    result = impact_orchestrator.run_impact_update(
        ChangeTrigger(
            trigger_type="jenkins", scm_id="x", source_root="//remote/src",
            scm_type="svn", base_ref="", changed_files=["Ap_Door.c"],
            dry_run=True, auto_generate=True, targets=["uds", "sits"], metadata={},
        )
    )

    assert result["ok"] is True
    assert classify_calls["n"] == 0   # cloudium: git/svn diff subprocess 생략
    assert result["actions"]["uds"]["mode"] == "FLAG"   # AUTO 강등
    assert any("cloudium" in w for w in result["warnings"])
    # 파일 기반 분류 → by_name 매핑으로 실제 함수 도출
    assert "door_run" in result["changed_function_types"]


def test_impact_analyze_runs_in_process(tmp_path, monkeypatch):
    """impact.py가 subprocess 대신 in-process analyze()를 호출한다(local 모드)."""
    from backend.routers import impact as imod
    from backend.schemas import ImpactAnalyzeRequest
    import backend.services.file_resolver as fr
    import tools.impact_analysis as tia

    (tmp_path / "x.c").write_text("void f(void){}", encoding="utf-8")

    class _Local:
        mode = "local"
    monkeypatch.setattr(fr, "get_resolver", lambda: _Local())
    monkeypatch.setattr(
        tia, "analyze",
        lambda sr, ch: {
            "changed_files": ch, "seed_function_count": 1, "impacted_function_count": 1,
            "impacted_functions": ["f"], "impacted_swcom": ["SwCom_01"],
        },
    )

    res = imod.impact_analyze(ImpactAnalyzeRequest(source_root=str(tmp_path), changed_files=["x.c"]))
    assert res["ok"] is True
    assert res["result"]["impacted_function_count"] == 1
    assert res["report_path"].endswith(".md") and res["json_path"].endswith(".json")


def test_impact_analyze_ai_guide_not_fake_low(tmp_path, monkeypatch):
    """include_ai_guide=True면 빈 컨텍스트 LOW 위장이 아니라 scope/ASIL미상 기반 평가가 나온다."""
    from backend.routers import impact as imod
    from backend.schemas import ImpactAnalyzeRequest
    import backend.services.file_resolver as fr
    import tools.impact_analysis as tia

    (tmp_path / "x.c").write_text("void f(void){}", encoding="utf-8")

    class _Local:
        mode = "local"
    monkeypatch.setattr(fr, "get_resolver", lambda: _Local())
    monkeypatch.setattr(
        tia, "analyze",
        lambda sr, ch: {"impacted_functions": ["f", "g", "h"], "impacted_function_count": 3,
                        "seed_function_count": 1, "impacted_swcom": []},
    )
    res = imod.impact_analyze(ImpactAnalyzeRequest(source_root=str(tmp_path), changed_files=["x.c"], include_ai_guide=True))
    assert res["ai_guide"] is not None
    assert res["ai_guide"]["risk"]["unknown_asil_count"] >= 1   # by_name 없음 → ASIL 미상 명시(QM 위장 아님)


def test_impact_analyze_cloudium_worker_down_returns_400(monkeypatch):
    """cloudium worker 다운 시 is_dir 예외가 500이 아닌 깨끗한 400으로 처리된다."""
    from backend.routers import impact as imod
    from backend.schemas import ImpactAnalyzeRequest
    import backend.services.file_resolver as fr
    from fastapi import HTTPException

    class _DownCloud:
        mode = "cloudium"
        def is_dir(self, p):
            raise ConnectionError("worker unavailable")

    monkeypatch.setattr(fr, "get_resolver", lambda: _DownCloud())
    with pytest.raises(HTTPException) as ei:
        imod.impact_analyze(ImpactAnalyzeRequest(source_root="//remote/src", changed_files=["x.c"]))
    assert ei.value.status_code == 400


def test_run_impact_update_cloudium_empty_index_warns_underreport(tmp_path, monkeypatch):
    """cloudium에서 source index(by_name)가 비면 과소보고 경고를 낸다."""
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    from workflow import impact_audit, impact_orchestrator

    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json")
    monkeypatch.setattr(impact_audit, "AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setattr(impact_audit, "LOCK_PATH", tmp_path / "audit" / ".run_lock")
    scm_registry.register_entry(
        ScmRegisterRequest(id="x", name="X", scm_type="svn", source_root="//remote/src")
    )
    monkeypatch.setattr(impact_orchestrator, "_is_cloudium_mode", lambda: True)
    monkeypatch.setattr(impact_orchestrator, "classify_changed_functions", lambda *a, **k: {})
    monkeypatch.setattr(
        impact_orchestrator, "_load_source_sections",
        lambda _r: {"call_map": {}, "function_details_by_name": {}},
    )
    result = impact_orchestrator.run_impact_update(
        ChangeTrigger(
            trigger_type="jenkins", scm_id="x", source_root="//remote/src",
            scm_type="svn", base_ref="", changed_files=["Ap_Door.c"],
            dry_run=True, targets=["uds"], metadata={},
        )
    )
    assert result["ok"] is True
    # by_name(소스 인덱스)이 비면 함수 해석 불가 → "소스 인덱스 0건" 과소보고 경고를 낸다.
    # (R2 71f0b51에서 영문 'under-reported' → 한국어로 재작성됨. 경고 존재를 검증하되 문구 변화에
    #  견고하도록 안정 접두사로 매칭.)
    assert any("소스 인덱스 0건" in w for w in result["warnings"])
