"""요약탭 AI 인사이트 — workflow/summary_ai_insight + POST /api/summary/ai-insight.

정직성/비용 규약 검증 중심: LLM 미설정도 결정론 코어 완결, 섹션 실패 격리,
환각 규칙/파일 사후 필터, 발췌 캡 강제, probe는 LLM 0회, 캐시 키 가변성.
"""
from __future__ import annotations

import json
from pathlib import Path

from workflow.summary_ai_insight import (
    PROMPT_VERSION,
    SummaryInsightInput,
    _extract_json_payload,
    collect_code_excerpts,
    compute_cache_key,
    generate_summary_insight,
    top_rules_with_files,
)


def _inp(**over):
    base = dict(
        job_slug="kjpds02_pv",
        latest_build=125,
        baseline_build=124,
        headline={"violations": 562, "compliance": 91, "coverage_line": 0.82},
        top_rules=[{"rule": "Rule-8.6", "count": 120, "files_affected": 14}],
        delta={
            "totals": {"cur": 562, "base": 552, "delta": 10},
            "rules": {"new": [{"rule": "Rule-9.9", "count": 4}], "resolved": [], "increased": [], "decreased": [], "residual_delta": 0},
            "files": [{"file": "foo.c", "path": "APP/src/foo.c", "delta": 5, "rules": []}],
        },
        signals=[{"type": "changed_file_violation_increase", "file": "APP/src/foo.c", "delta": 5, "rules": ["Rule-8.6"]}],
        complexity_offenders=[{"function": "big_fn", "vg": 42, "file": "foo.c"}],
        vcast_failures=[{"testcase": "TC1", "result": "FAIL"}],
        trace_summary={"has_data": True, "uncovered": 8, "asil_gap_count": 2, "asil_unknown_count": 12},
        code_excerpts=[{"path": "APP/src/foo.c", "bytes": 10, "text": "int x = 1;", "truncated": False}],
    )
    base.update(over)
    return SummaryInsightInput(**base)


# ── 결정론 코어 ──────────────────────────────────────────────────────────────

def test_deterministic_core_without_llm_all_sections_fallback():
    res = generate_summary_insight(_inp(), use_llm=False)
    assert res["ok"] is True
    assert res["ai_enriched"] is False
    for name in ("rules", "mistakes", "roles"):
        assert res["sections"][name]["ai_enriched"] is False
        assert res["sections"][name]["reason"] == "llm_unavailable"
    # roles 결정론 폴백은 basis에 실제 수치 인용
    dev = res["sections"]["roles"]["developer"]
    tester = res["sections"]["roles"]["tester"]
    assert dev and tester
    assert any("신규 규칙 1종" in d["basis"] for d in dev)
    assert any("실패 TC 1건" in t["basis"] for t in tester)
    # 결정론 코어 구조
    det = res["deterministic"]
    assert det["headline"]["violations"] == 562
    assert det["delta_summary"]["available"] is True
    assert det["delta_summary"]["changed_files_with_increase"] == 1
    assert {g["kind"] for g in det["gaps"]} >= {"trace_uncovered", "asil_test_gap", "test_failures"}


def test_deterministic_delta_none_not_zero():
    """delta 계산 불가는 available:false — 0으로 위장하지 않는다."""
    res = generate_summary_insight(_inp(delta=None, signals=[]), use_llm=False)
    ds = res["deterministic"]["delta_summary"]
    assert ds["available"] is False
    assert ds["residual_delta"] is None


def test_coverage_unmeasured_gap():
    res = generate_summary_insight(_inp(headline={"violations": 1, "coverage_line": None}), use_llm=False)
    assert {"kind": "coverage_unmeasured", "count": None} in res["deterministic"]["gaps"]


# ── enrichment 격리/환각 필터 ────────────────────────────────────────────────

def _fake_agent(responses):
    """stage별 응답을 돌려주는 agent_call_text 대역."""
    def call(cfg, messages, *, role=None, stage=None, **k):
        v = responses.get(stage)
        if isinstance(v, Exception):
            raise v
        return v
    return call


CFG = {"model": "gemini-test"}


def test_enrichment_failure_isolated_per_section():
    """rules 섹션 예외가 mistakes/roles를 죽이지 않는다(격리)."""
    agent = _fake_agent({
        "summary_rules": RuntimeError("boom"),
        "summary_mistakes": json.dumps({"items": [{"pattern": "p", "rules": ["Rule-8.6"], "files": [], "diagnosis": "d", "improvement": "i", "evidence_quote": "", "confidence": "low"}]}),
        "summary_roles": json.dumps({"developer": [{"priority": 1, "action": "a", "basis": "b"}], "tester": [{"priority": 1, "action": "a", "basis": "b"}]}),
    })
    res = generate_summary_insight(_inp(), llm_cfg=CFG, agent_call=agent)
    assert res["sections"]["rules"]["ai_enriched"] is False
    assert res["sections"]["rules"]["reason"] == "llm_error"
    assert res["sections"]["mistakes"]["ai_enriched"] is True
    assert res["sections"]["roles"]["ai_enriched"] is True
    assert res["ai_enriched"] is True


def test_rule_hallucination_filtered():
    """입력에 없는 규칙 번호는 버린다 — 전부 환각이면 폴백."""
    agent = _fake_agent({
        "summary_rules": json.dumps({"items": [
            {"rule": "Rule-8.6", "title": "t", "why_risky": "w", "typical_cause": "c", "fix_guide": "f"},
            {"rule": "Rule-77.7", "title": "환각", "why_risky": "", "typical_cause": "", "fix_guide": ""},
        ]}),
    })
    res = generate_summary_insight(_inp(), sections=("rules",), llm_cfg=CFG, agent_call=agent)
    items = res["sections"]["rules"]["items"]
    assert [i["rule"] for i in items] == ["Rule-8.6"]  # 환각 규칙 제거

    all_fake = _fake_agent({"summary_rules": json.dumps({"items": [{"rule": "Rule-77.7"}]})})
    res2 = generate_summary_insight(_inp(), sections=("rules",), llm_cfg=CFG, agent_call=all_fake)
    assert res2["sections"]["rules"]["ai_enriched"] is False


def test_mistake_pattern_requires_known_basis():
    """규칙·파일 근거가 전부 미지인 패턴은 드랍, confidence 미지값은 low로 정규화."""
    agent = _fake_agent({
        "summary_mistakes": json.dumps({"items": [
            {"pattern": "ok", "rules": ["Rule-8.6"], "files": ["없는파일.c"], "confidence": "HIGH!"},
            {"pattern": "환각", "rules": ["Rule-0.0"], "files": ["ghost.c"]},
        ]}),
    })
    res = generate_summary_insight(_inp(), sections=("mistakes",), llm_cfg=CFG, agent_call=agent)
    items = res["sections"]["mistakes"]["items"]
    assert len(items) == 1
    assert items[0]["pattern"] == "ok"
    assert items[0]["files"] == []          # 미지 파일 제거(규칙 근거는 유지)
    assert items[0]["confidence"] == "low"  # 비표준 값 정규화


def test_roles_partial_response_falls_back_whole():
    """developer만 오고 tester가 없으면 반쪽 권고 대신 전체 결정론 폴백."""
    agent = _fake_agent({"summary_roles": json.dumps({"developer": [{"priority": 1, "action": "a"}]})})
    res = generate_summary_insight(_inp(), sections=("roles",), llm_cfg=CFG, agent_call=agent)
    sec = res["sections"]["roles"]
    assert sec["ai_enriched"] is False
    assert sec["developer"] and sec["tester"]  # 결정론 폴백 존재


# ── JSON 파서/발췌 캡/캐시 키 ────────────────────────────────────────────────

def test_extract_json_payload_codefence_and_noise():
    assert _extract_json_payload('설명입니다\n```json\n{"a": 1}\n```\n끝') == {"a": 1}
    assert _extract_json_payload('노이즈 [ {"b": 2} ] 꼬리') == [{"b": 2}]
    assert _extract_json_payload("json 없음") is None
    assert _extract_json_payload("") is None


def test_excerpt_caps_enforced():
    files = {f"f{i}.c": "x" * 10000 for i in range(6)}
    out = collect_code_excerpts(lambda p: files[p], list(files.keys()))
    assert len(out) == 4  # 파일 수 캡
    assert all(e["bytes"] <= 4096 for e in out)
    assert sum(e["bytes"] for e in out) <= 16384
    assert all(e["truncated"] for e in out)


def test_excerpt_reader_failure_skipped():
    def reader(p):
        if p == "bad.c":
            raise FileNotFoundError(p)
        return "ok"
    out = collect_code_excerpts(reader, ["bad.c", "good.c"])
    assert [e["path"] for e in out] == ["good.c"]


def test_cache_key_changes_on_model_build_and_prompt(monkeypatch):
    import workflow.summary_ai_insight as mod

    k1 = compute_cache_key(_inp(), "gemini-a")
    assert compute_cache_key(_inp(), "gemini-b") != k1                      # 모델
    assert compute_cache_key(_inp(latest_build=126), "gemini-a") != k1      # 빌드
    assert compute_cache_key(_inp(top_rules=[{"rule": "R", "count": 1}]), "gemini-a") != k1  # 입력 지문
    monkeypatch.setattr(mod, "PROMPT_VERSION", PROMPT_VERSION + 1)
    assert mod.compute_cache_key(_inp(), "gemini-a") != k1                  # 프롬프트 버전


def test_top_rules_with_files_skips_residual_and_counts_files():
    details = {"violations_by_file": [
        {"file": "a.c", "path": "src/a.c", "total": 7, "rules": [
            {"rule": "Rule-1.1", "count": 4}, {"rule": "기타 규칙 (비상위)", "count": 3, "residual": True}]},
        {"file": "b.c", "path": "src/b.c", "total": 2, "rules": [{"rule": "Rule-1.1", "count": 2}]},
    ]}
    out = top_rules_with_files(details)
    assert out == [{"rule": "Rule-1.1", "count": 6, "files_affected": 2}]


def test_deterministic_no_issue_projects_get_keepup_guidance():
    """이상 신호가 없는 프로젝트도 빈 권고가 아니라 '유지' 권고를 받는다."""
    res = generate_summary_insight(
        _inp(delta=None, signals=[], top_rules=[], complexity_offenders=[], vcast_failures=[],
             trace_summary={"has_data": True, "uncovered": 0, "asil_gap_count": 0, "asil_unknown_count": 0}),
        use_llm=False,
    )
    roles = res["sections"]["roles"]
    assert roles["developer"][0]["action"]
    assert roles["tester"][0]["action"]


# ── 엔드포인트 (probe/캐시/LLM 0회) ─────────────────────────────────────────

def _prep_build(tmp_path, n=125):
    br = tmp_path / f"build_{n}"
    rd = br / "report"
    rd.mkdir(parents=True)
    (rd / "analysis_summary.json").write_text(json.dumps({
        "prqa": {"rcr": {"ok": True, "summary": {"Rule Violation Count": 562, "Project Compliance Index": 91}}},
        "coverage": {"line_rate": 0.82},
    }), encoding="utf-8")
    return {"build_root": str(br), "build_number": n, "reports_dir": str(rd), "mtime": 0}


def test_endpoint_probe_cache_miss_no_llm_call(tmp_path, monkeypatch):
    from backend.routers import summary_insight as si

    meta = _prep_build(tmp_path)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    called = {"n": 0}

    def no_llm(*a, **k):
        called["n"] += 1
        raise AssertionError("probe must not reach LLM")

    monkeypatch.setattr("workflow.summary_ai_insight.generate_summary_insight", no_llm, raising=True)
    resp = si.summary_ai_insight_endpoint({"job_url": "http://j/", "probe": True})
    assert resp["cached"] is False and resp["available"] is True
    assert called["n"] == 0


def test_endpoint_generate_then_cache_hit(tmp_path, monkeypatch):
    from backend.routers import summary_insight as si

    meta = _prep_build(tmp_path)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    # LLM 미설정 환경처럼 use_llm 경로에서 cfg None → 결정론 폴백(실 Gemini 미호출).
    monkeypatch.setattr("workflow.impact_ai_guide._load_impact_oai_config", lambda: None, raising=True)
    r1 = si.summary_ai_insight_endpoint({"job_url": "http://j/"})
    assert r1["cached"] is False and r1["available"] is True
    assert r1["ai_enriched"] is False  # cfg 없음 → 전 섹션 결정론
    assert r1["deterministic"]["headline"]["violations"] == 562
    assert (Path(meta["reports_dir"]) / si.AI_INSIGHT_CACHE_NAME).exists()

    r2 = si.summary_ai_insight_endpoint({"job_url": "http://j/"})
    assert r2["cached"] is True
    r3 = si.summary_ai_insight_endpoint({"job_url": "http://j/", "probe": True})
    assert r3["cached"] is True


def test_endpoint_prompt_version_mismatch_invalidates_cache(tmp_path, monkeypatch):
    from backend.routers import summary_insight as si

    meta = _prep_build(tmp_path)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    stale = {"ok": True, "prompt_version": -1, "sections": {}, "deterministic": {}}
    (Path(meta["reports_dir"]) / si.AI_INSIGHT_CACHE_NAME).write_text(json.dumps(stale), encoding="utf-8")
    resp = si.summary_ai_insight_endpoint({"job_url": "http://j/", "probe": True})
    assert resp["cached"] is False  # 구 프롬프트 산출물을 현행으로 위장하지 않는다


def test_endpoint_cache_invalidated_when_rcr_replaced_in_place(tmp_path, monkeypatch):
    """W1: 같은 빌드 디렉토리의 RCR이 교체되면(재-sync) 캐시를 stale로 서빙하지 않는다."""
    from backend.routers import summary_insight as si

    meta = _prep_build(tmp_path)
    rcr = Path(meta["build_root"]) / "PROJ_RCR_01012026.html"
    rcr.write_text("<html><head><title>Helix QAC Rule Compliance Report</title></head><body></body></html>", encoding="utf-8")
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    monkeypatch.setattr("workflow.impact_ai_guide._load_impact_oai_config", lambda: None, raising=True)
    r1 = si.summary_ai_insight_endpoint({"job_url": "http://j/"})
    assert r1["cached"] is False
    assert si.summary_ai_insight_endpoint({"job_url": "http://j/", "probe": True})["cached"] is True
    # RCR in-place 교체(mtime/size 변화) → probe/생성 모두 캐시 미스
    rcr.write_text("<html><head><title>Helix QAC Rule Compliance Report</title></head><body><p>v2</p></body></html>", encoding="utf-8")
    assert si.summary_ai_insight_endpoint({"job_url": "http://j/", "probe": True})["cached"] is False
    r2 = si.summary_ai_insight_endpoint({"job_url": "http://j/"})
    assert r2["cached"] is False  # 재생성됨


def test_endpoint_job_slug_is_job_dir_not_build_dir(tmp_path, monkeypatch):
    """W2: job_slug는 build_N이 아니라 잡 디렉토리명."""
    from backend.routers import summary_insight as si

    job_dir = tmp_path / "http_ci_job_KJPDS02_DV"
    meta = {
        "build_root": str(job_dir / "build_125"), "build_number": 125,
        "reports_dir": str(job_dir / "build_125" / "report"), "mtime": 0,
    }
    Path(meta["reports_dir"]).mkdir(parents=True)
    (Path(meta["reports_dir"]) / "analysis_summary.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    monkeypatch.setattr("workflow.impact_ai_guide._load_impact_oai_config", lambda: None, raising=True)
    resp = si.summary_ai_insight_endpoint({"job_url": "http://j/"})
    assert resp["input"]["job_slug"] == "http_ci_job_KJPDS02_DV"


def test_source_reader_blocks_mid_path_traversal(tmp_path):
    """W3: 중간 '..' 세그먼트는 거부 — root 밖 read 차단(defense-in-depth)."""
    import pytest

    from backend.routers.summary_insight import _make_source_reader

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ok.c").write_text("int a;", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    read = _make_source_reader(str(tmp_path / "src"))
    assert read("ok.c") == "int a;"
    assert read("../ok.c") == "int a;"  # 선행 ../는 스트립(정상 RCR 상대경로 수용)
    with pytest.raises(FileNotFoundError):
        read("foo/../../secret.txt")  # 중간 traversal 거부
    with pytest.raises(FileNotFoundError):
        read("..")


# ── trace 큐레이션(v3) — raw 관측치의 조치 항목 오변환 차단 ─────────────────

RAW_TRACE = {
    "has_data": True,
    "total_requirements": 68, "covered": 68, "uncovered": 0, "coverage_pct": 100.0,
    "asil_gap_count": 0, "asil_unknown_count": 0,
    "integrity_clean": False, "integrity_collision_count": 0,
    "integrity_dangling_count": 111, "integrity_placeholder_count": 0,
    "summary_raw": {
        "vcast_input_rows": 1032, "vcast_traced_rows": 405, "vcast_untraced_rows": 627,
        "unmapped_vcast_count": 627, "unmapped_suts_tested": 619, "unmapped_vcast_only": 6,
        "unmapped_isr": 2, "unmapped_safety": 44, "unmapped_uds_linked": 624,
        "unmapped_design_gap": 3, "unmapped_app_design_gap": 0,
        "total_tests": 7543,  # 기타 raw 필드 — 큐레이션에서 드랍돼야 함
    },
}


def test_curate_trace_drops_raw_and_classifies_kjpds02_shape():
    """실측(KJPDS02_PV) shape: 미추적 627은 관측치로, 조치 축은 design_gap 3만 남는다."""
    from workflow.summary_ai_insight import TRACE_UNTRACED_NOTE, curate_trace_summary

    cur = curate_trace_summary(RAW_TRACE)
    assert cur["has_data"] is True
    assert "summary_raw" not in cur                      # raw 총계 LLM 유입 차단
    vb = cur["vcast_bridge"]
    assert vb["untraced_rows_observed"] == 627           # 관측치 라벨
    assert vb["classification"]["design_gap"] == 3       # 유일한 조치 대상
    assert vb["classification"]["uds_linked_granularity"] == 624
    assert vb["classification"]["safety_token_flagged"] == 44
    assert vb["note"] == TRACE_UNTRACED_NOTE             # 기확립 진단 문구 동봉
    assert cur["integrity"]["dangling_count"] == 111     # 실 finding 축은 유지
    assert curate_trace_summary(None) is None
    assert curate_trace_summary({"has_data": False}) is None


def test_gaps_use_design_gap_not_untraced_total():
    """gaps에 미추적 총계(627)는 없고 design_gap(3)·dangling(111)만 조치 축으로 등장."""
    from workflow.summary_ai_insight import curate_trace_summary, generate_summary_insight

    res = generate_summary_insight(
        _inp(trace_summary=curate_trace_summary(RAW_TRACE), vcast_failures=[], delta=None, signals=[]),
        use_llm=False,
    )
    kinds = {g["kind"]: g["count"] for g in res["deterministic"]["gaps"]}
    assert kinds.get("vcast_design_gap") == 3
    assert kinds.get("integrity_dangling") == 111
    assert not any(v == 627 for v in kinds.values())     # 총계가 gap으로 둔갑 금지
    # 결정론 tester 권고가 입도차 문맥을 동봉
    tester = res["sections"]["roles"]["tester"]
    design_item = next(t for t in tester if "설계 갭" in t["basis"])
    assert "진짜 설계 갭 3건" in design_item["basis"]
    assert "입도차 624건" in design_item["basis"]        # 총계≠조치 문맥 명시
    dangling_item = next(t for t in tester if "dangling" in t["basis"])
    assert "111" in dangling_item["basis"]


def test_gaps_raw_trace_fallback_dual_source():
    """큐레이션 안 거친 raw trace(테스트/구 경로)에서도 design_gap·dangling을 읽는다."""
    from workflow.summary_ai_insight import generate_summary_insight

    res = generate_summary_insight(_inp(trace_summary=RAW_TRACE), use_llm=False)
    kinds = {g["kind"] for g in res["deterministic"]["gaps"]}
    assert "vcast_design_gap" in kinds and "integrity_dangling" in kinds


def test_resolve_effective_model_override_priority(monkeypatch):
    """실호출 모델 해석 — cfg.model_override > env LLM_MODEL_OVERRIDE > cfg.model (llm_call 동일)."""
    from workflow.summary_ai_insight import resolve_effective_model

    monkeypatch.delenv("LLM_MODEL_OVERRIDE", raising=False)
    assert resolve_effective_model({"model": "gemini-2.5-flash"}) == "gemini-2.5-flash"
    monkeypatch.setenv("LLM_MODEL_OVERRIDE", "gemini-3.5-flash-lite")
    assert resolve_effective_model({"model": "gemini-2.5-flash"}) == "gemini-3.5-flash-lite"
    assert resolve_effective_model({"model": "x", "model_override": "cfg-wins"}) == "cfg-wins"
    assert resolve_effective_model(None) is None


def test_endpoint_cache_miss_on_model_change(tmp_path, monkeypatch):
    """Phase 0: 캐시 산출물의 model ≠ 현재 해석 모델 → cached:false(구 모델 위장 금지)."""
    from backend.routers import summary_insight as si

    meta = _prep_build(tmp_path)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    monkeypatch.delenv("LLM_MODEL_OVERRIDE", raising=False)
    monkeypatch.setattr("workflow.impact_ai_guide._load_impact_oai_config", lambda: None, raising=True)
    r1 = si.summary_ai_insight_endpoint({"job_url": "http://j/"})
    assert r1["cached"] is False and r1["model"] is None
    assert si.summary_ai_insight_endpoint({"job_url": "http://j/", "probe": True})["cached"] is True
    # 모델 배선 변경(None → gemini-3.5) → 동일 RCR/프롬프트여도 캐시 미스
    monkeypatch.setattr(
        "workflow.impact_ai_guide._load_impact_oai_config",
        lambda: {"model": "gemini-3.5-flash-lite"},
        raising=True,
    )
    assert si.summary_ai_insight_endpoint({"job_url": "http://j/", "probe": True})["cached"] is False


def _load_real_config():
    """실 config 모듈을 sys.modules와 무관하게 파일에서 로드(격리-내성).

    ⚠ test_workflow_pipeline이 config 미로드 시점이면 sys.modules['config']에 MagicMock을
    심고 복원하지 않는다(레거시 stub 누설) — `import config`는 전체 스위트 순서에 따라
    MagicMock을 받을 수 있어(단독 green ↔ 전체 fail), 별도 이름으로 실 파일을 직접 로드한다.
    """
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "config.py"
    spec = importlib.util.spec_from_file_location("_config_real_p0_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_config_policy_gemini35_exact_and_defaults():
    """Phase 0: 표준 모델 정책 존재(스펙 정확값) + 기본 모델 전환 + 2.5 정책 비포획."""
    config = _load_real_config()

    pol = config.LLM_MODEL_POLICIES["gemini-3.5-flash-lite"]
    assert pol["max_input_tokens"] == 1048576
    assert pol["max_output_tokens"] == 65536
    assert config.DEFAULT_LLM_MODEL == "gemini-3.5-flash-lite"
    # substring first-match(정책 lookup 폴백)에서도 3.5 키가 먼저 매칭 — 2.5(8192캡) 비포획.
    name = "gemini-3.5-flash-lite"
    first = next(k for k in config.LLM_MODEL_POLICIES if str(k).lower() in name)
    assert first == "gemini-3.5-flash-lite"
    assert "gemini-2.5" not in name


def test_endpoint_no_cached_build(monkeypatch):
    from backend.routers import summary_insight as si

    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [])
    resp = si.summary_ai_insight_endpoint({"job_url": "http://j/"})
    assert resp["available"] is False and resp["reason"] == "no_cached_build"


# ── v4: testing 섹션·규칙 공식 설명 주입·아키 사이클 payload ─────────────────

def _td_fixture():
    return {
        "technique_recommendations": {
            "available": True,
            "coverage_join": {"entries": 3, "with_asil": 1, "asil_unknown": 2},
            "items": [{"function": "Safe_Fn", "unit": "a.c", "asil": "C", "ccn": 22,
                       "gap_kind": "below_target", "techniques": ["boundary_values"],
                       "basis": "ASIL C · 분기 50%"}],
            "summary": {"below_target": 1, "unmeasured_metric": 0, "uncovered": 0},
        },
        "design_test_gap": {
            "available": True,
            "totals": {"targets_with_uds": 2},
            "band_missing": {"suts": False, "vcast": False},
            "targets_with_uds_no_suts": [{"target_id": "REQ-9", "uds_count": 1}],
        },
        "mcdc_note": "MC/DC 미측정 — 미측정≠미달",
    }


def test_prompt_version_and_sections():
    """⚠ 이름에 버전을 박지 않는다 — 올릴 때마다 이름이 낡아 거짓말이 된다.

    v5 bump: N5 아키텍처 payload 확장.
    v6 bump: role_guidance 프롬프트에 안전 커버리지 읽는 법 추가 + trace 입력에 safety 블록.
             둘 다 **LLM 이 받는 것**이 바뀐 것이라 전 AI 캐시가 자연 미스여야 한다
             (probe 가 생성 버튼을 노출). 버전을 안 올리면 옛 결과가 새 안내로 만든 것인 척 산다.
    """
    from workflow.summary_ai_insight import SECTIONS

    assert PROMPT_VERSION == 6
    assert SECTIONS == ("rules", "mistakes", "roles", "architecture", "testing")


def test_deterministic_testing_block_and_absence():
    res = generate_summary_insight(_inp(test_design=_td_fixture()), use_llm=False)
    dt = res["deterministic"]["testing"]
    assert dt["available"] is True
    assert dt["technique"]["coverage_join"]["entries"] == 3
    assert dt["design_test_gap"]["band_missing"] == {"suts": False, "vcast": False}
    assert "미측정≠미달" in dt["mcdc_note"]
    assert res["sections"]["testing"]["ai_enriched"] is False  # LLM 0회 — 결정론 폴백
    # 입력 부재 — available:false 명시(침묵 생략 금지)
    res2 = generate_summary_insight(_inp(), use_llm=False)
    assert res2["deterministic"]["testing"] == {"available": False, "reason": "no_test_design_input"}


def test_enrich_testing_symbol_filter():
    agent = _fake_agent({
        "summary_testing": json.dumps({"items": [
            {"topic": "coverage_gap", "finding": "f", "suggestion": "s",
             "symbols": ["Safe_Fn"], "basis": "분기 50%", "confidence": "medium"},
            {"topic": "design_gap", "finding": "g", "suggestion": "",
             "symbols": ["REQ-9"], "basis": ""},
            {"topic": "technique", "finding": "환각", "suggestion": "",
             "symbols": ["ghost_fn"], "basis": ""},
        ]}),
    })
    res = generate_summary_insight(_inp(test_design=_td_fixture()), sections=("testing",),
                                   llm_cfg=CFG, agent_call=agent)
    sec = res["sections"]["testing"]
    assert sec["ai_enriched"] is True
    # 입력 심볼(함수/유닛/타깃 ID) 밖만 언급한 항목은 드랍
    assert [i["symbols"] for i in sec["items"]] == [["Safe_Fn"], ["REQ-9"]]
    assert sec["items"][0]["topic"] == "coverage_gap"


def test_rules_payload_includes_official_descriptions_for_known_only():
    captured = {}

    def agent(cfg, messages, *, role=None, stage=None, **k):
        captured["payload"] = messages[1]["content"]
        return json.dumps({"items": [{"rule": "Rule-8.6", "title": "t", "why_risky": "w",
                                      "typical_cause": "c", "fix_guide": "g"}]})

    res = generate_summary_insight(
        _inp(rule_descriptions={
            "Rule-8.6": {"title": "exactly one external definition", "enabled": True, "group": "M3CM"},
            "Rule-미지": {"title": "x-desc"},
        }),
        sections=("rules",), llm_cfg=CFG, agent_call=agent,
    )
    assert res["sections"]["rules"]["ai_enriched"] is True
    assert "official_descriptions" in captured["payload"]
    assert "exactly one external definition" in captured["payload"]
    assert "x-desc" not in captured["payload"]  # 입력 규칙 집합 밖 설명은 미동봉(payload 경량)


def test_architecture_payload_cycles_and_module_symbol_vocab():
    from tests.unit.test_summary_arch_metrics import _arch_fixture

    arch = _arch_fixture()
    arch["module_graph"] = {"nodes": [{"module": "APP", "files": 2, "functions": 4}],
                            "edges": [{"from": "APP", "to": "LIB", "calls": 3}], "truncated": False}
    arch["cycles"] = {"file_sccs": [{"files": ["APP/a.c", "APP/b.c"], "size": 2}],
                      "module_sccs": [], "mutual_file_pairs": []}
    arch["refactor_candidates"] = []
    captured = {}

    def agent(cfg, messages, *, role=None, stage=None, **k):
        captured["payload"] = messages[1]["content"]
        return json.dumps({"items": [
            {"topic": "cycle", "finding": "파일 순환", "suggestion": "s",
             "functions": [], "files": ["APP/a.c"], "basis": "size 2"},
            {"topic": "coupling", "finding": "모듈 결합", "suggestion": "",
             "functions": ["APP"], "files": [], "basis": "3회"},
        ]})

    res = generate_summary_insight(_inp(arch_metrics=arch), sections=("architecture",),
                                   llm_cfg=CFG, agent_call=agent)
    sec = res["sections"]["architecture"]
    assert '"cycles"' in captured["payload"] and '"module_graph"' in captured["payload"]
    assert sec["ai_enriched"] is True and len(sec["items"]) == 2
    assert sec["items"][0]["topic"] == "cycle"          # v4: topic 화이트리스트 확장
    assert sec["items"][1]["functions"] == ["APP"]      # 모듈명이 어휘를 통과
    # 결정론 블록에도 cycles 병합
    assert res["deterministic"]["architecture"]["cycles"]["file_sccs"][0]["size"] == 2


# ── 안전 요구(ASIL A~D) 커버리지가 AI 입력까지 닿는가 ────────────────────────
#
# R24 가 화면 3곳에 배선했고 AI 입력만 남아 있었다. 필드만 넣고 안내를 안 넣으면
# LLM 이 `pct: null` 을 "커버리지 0%" 로 읽는다 — 화면에서 막은 오독 그대로다.
# 실측 shape 는 KJPDS02_PV(A 62/62 = 100%, QM 2, 미상 4).

_KJPDS02_DIST = {"A": {"total": 62, "covered": 62},
                 "QM": {"total": 2, "covered": 2},
                 "UNKNOWN": {"total": 4, "covered": 4}}


def _trace(dist, **over):
    t = {"has_data": True, "total_requirements": 68, "covered": 68, "uncovered": 0,
         "asil_gap_count": 0, "asil_unknown_count": 0}
    if dist is not None:
        t["asil_distribution"] = dist
    t.update(over)
    return t


def test_curate_carries_safety_coverage():
    """실측 shape: 안전 62/62 = 100% 인데 **미상 4건이 분모 밖**이라는 사실이 같이 간다."""
    from workflow.summary_ai_insight import TRACE_SAFETY_NOTE, curate_trace_summary

    s = curate_trace_summary(_trace(_KJPDS02_DIST))["safety"]
    assert (s["total"], s["covered"], s["pct"]) == (62, 62, 100.0)
    assert s["unknown"] == 4, "미상 건수가 빠지면 100% 가 '안전 요구 전부 검증됨' 으로 읽힌다"
    assert s["note"] == TRACE_SAFETY_NOTE


def test_zero_denominator_reaches_the_llm_as_null_not_zero():
    """등급 붙은 요구가 0건이면 `pct` 는 **null** — LLM 에 직렬화된 문자열까지 확인한다.

    dict 에서만 None 이고 어딘가에서 0 으로 접히면 프롬프트 안내가 무의미해진다.
    """
    from workflow.summary_ai_insight import curate_trace_summary

    s = curate_trace_summary(_trace({"QM": {"total": 5, "covered": 5}}))["safety"]
    assert s["total"] == 0 and s["pct"] is None
    blob = json.dumps({"trace": curate_trace_summary(_trace({"QM": {"total": 5, "covered": 5}}))},
                      ensure_ascii=False, default=str)
    assert '"pct": null' in blob, "직렬화에서 0 으로 접히면 '커버리지 0%' 로 읽힌다"
    assert '"pct": 0' not in blob


def test_old_cache_without_distribution_says_nothing_rather_than_zero():
    """등급 분포가 없는 옛 캐시(실측: 저장소 캐시 6건 중 2건)는 **침묵**한다.

    0 으로 접으면 "안전 요구 0건" 이라는 없는 사실이 생긴다.
    """
    from workflow.summary_ai_insight import curate_trace_summary, derive_safety_coverage

    assert derive_safety_coverage(_trace(None)) is None
    assert derive_safety_coverage(_trace({})) is None
    assert "safety" not in curate_trace_summary(_trace(None))


def test_unknown_axis_is_the_distribution_not_asil_unknown_count():
    """`safety.unknown` 은 **등급분포** 축이다 — `asil_unknown_count`(링크테이블 축)가 아니다.

    후자는 등급 데이터가 전무하면 0 으로 강제된다(report_gen/trace_link_table.py) — 즉
    "등급이 하나도 없다" 는 최악의 경우에 침묵한다. 그걸 '분모에서 뺀 건수'로 쓰면
    분모 밖 건수가 0 으로 보고돼 100% 가 '전부 검증됨' 이 된다.
    """
    from workflow.summary_ai_insight import derive_safety_coverage

    s = derive_safety_coverage(_trace(
        {"A": {"total": 1, "covered": 1}, "UNKNOWN": {"total": 3, "covered": 0}},
        asil_unknown_count=0,          # 링크테이블 축은 0 이라고 말한다
    ))
    assert s["unknown"] == 3, "링크테이블 축(0)을 따라가면 미상 3건이 침묵한다"


def test_both_unknown_spellings_are_counted():
    """백엔드는 'UNKNOWN', 상세탭 파생은 '미상' — 하나만 알면 그 표면에서 경고가 사라진다."""
    from workflow.summary_ai_insight import derive_safety_coverage

    s = derive_safety_coverage(_trace({"A": {"total": 1, "covered": 1},
                                       "미상": {"total": 2, "covered": 0}}))
    assert s["unknown"] == 2


def test_qm_never_enters_the_denominator():
    """QM 은 비안전이다 — 분모에 섞이면 안전 커버리지가 희석된다."""
    from workflow.summary_ai_insight import derive_safety_coverage

    s = derive_safety_coverage(_trace({"C": {"total": 2, "covered": 1},
                                       "QM": {"total": 98, "covered": 98}}))
    assert (s["total"], s["covered"], s["pct"]) == (2, 1, 50.0)


def test_safety_shortfall_is_a_gap_and_leads_the_list():
    """안전 요구 미확보는 gap 이고 **맨 앞**이다(프롬프트 심각도: 안전 > 회귀 > 부채)."""
    from workflow.summary_ai_insight import build_deterministic_insight, curate_trace_summary

    ts = curate_trace_summary(_trace({"D": {"total": 10, "covered": 6}}, uncovered=7))
    gaps = build_deterministic_insight(_inp(trace_summary=ts, vcast_failures=[], signals=[]))["gaps"]
    assert gaps[0] == {"kind": "safety_uncovered", "count": 4, "safety_total": 10}
    assert [g["kind"] for g in gaps].count("safety_uncovered") == 1


def test_full_safety_coverage_is_not_a_gap():
    """62/62 는 gap 이 아니다 — 없는 조치 항목을 만들지 않는다."""
    from workflow.summary_ai_insight import build_deterministic_insight, curate_trace_summary

    ts = curate_trace_summary(_trace(_KJPDS02_DIST))
    gaps = build_deterministic_insight(_inp(trace_summary=ts, vcast_failures=[], signals=[]))["gaps"]
    assert not any(g["kind"] == "safety_uncovered" for g in gaps)


def test_zero_denominator_is_not_a_gap():
    """잴 대상이 없는 것과 미달은 다르다 — QM 전용 프로젝트에 없는 결함을 만들지 않는다."""
    from workflow.summary_ai_insight import build_deterministic_insight, curate_trace_summary

    ts = curate_trace_summary(_trace({"QM": {"total": 5, "covered": 0}}))
    gaps = build_deterministic_insight(_inp(trace_summary=ts, vcast_failures=[], signals=[]))["gaps"]
    assert not any(g["kind"] == "safety_uncovered" for g in gaps)


def test_raw_cache_path_gets_the_gap_too():
    """큐레이션을 안 거친 raw 캐시로 들어와도 같은 gap 이 난다 — 호출 경로가 둘이다."""
    from workflow.summary_ai_insight import build_deterministic_insight

    gaps = build_deterministic_insight(
        _inp(trace_summary=_trace({"B": {"total": 4, "covered": 1}}), vcast_failures=[], signals=[]))["gaps"]
    assert {"kind": "safety_uncovered", "count": 3, "safety_total": 4} in gaps


def test_deterministic_tester_guidance_cites_the_safety_numbers():
    """LLM 없이도 근거에 실수치가 인용된다(프롬프트 규칙: 수치 없는 일반론 금지)."""
    from workflow.summary_ai_insight import curate_trace_summary, generate_summary_insight

    res = generate_summary_insight(
        _inp(trace_summary=curate_trace_summary(_trace({"D": {"total": 10, "covered": 6}})),
             vcast_failures=[], delta=None, signals=[]),
        use_llm=False,
    )
    tester = res["sections"]["roles"]["tester"]
    hit = next((t for t in tester if "안전 요구" in t["action"]), None)
    assert hit is not None, "안전 미확보 4건이 권고에 안 나온다"
    assert "10건" in hit["basis"] and "4건" in hit["basis"]


def test_prompt_tells_the_llm_how_to_read_safety():
    """필드만 주고 읽는 법을 안 주면 `pct: null` 이 '커버리지 0%' 가 된다.

    프롬프트는 LLM 에 실제로 실려 나가는 텍스트다 — 세 가지 오독을 전부 명시해야 한다.
    """
    from prompts import load_prompt

    p = load_prompt("summary_role_guidance")
    assert "safety" in p
    assert "잴 대상이 없음" in p, "(a) null 을 0% 로 읽지 말라는 안내가 없다"
    assert "감사 finding" in p, "(b) 미상 분모 밖 + 등급 미할당이 finding 이라는 안내가 없다"
    assert "두 번 세지" in p, "(c) uncovered 와 이중계상 금지 안내가 없다"


def test_safety_block_actually_reaches_the_llm_payload():
    """`enrich_role_guidance` 가 실제로 직렬화해 보내는 payload 에 safety 가 들어 있는가."""
    from workflow.summary_ai_insight import (
        build_deterministic_insight,
        curate_trace_summary,
        enrich_role_guidance,
    )

    seen = {}

    def _fake(cfg, messages, role=None, stage=None):
        seen["user"] = messages[-1]["content"]
        seen["system"] = messages[0]["content"]
        return json.dumps({"developer": [{"priority": 1, "action": "a", "basis": "b"}],
                           "tester": [{"priority": 1, "action": "a", "basis": "b"}]})

    inp = _inp(trace_summary=curate_trace_summary(_trace({"D": {"total": 10, "covered": 6}})),
               vcast_failures=[], signals=[])
    enrich_role_guidance({"model": "x"}, inp, build_deterministic_insight(inp), agent_call=_fake)
    assert '"safety"' in seen["user"], "안전 블록이 LLM 에 안 간다"
    assert '"pct": 60.0' in seen["user"]
    assert "잴 대상이 없음" in seen["system"], "읽는 법(system 프롬프트)이 같이 안 간다"


# ── 프롬프트 변경 ↔ 캐시 무효화 lockstep ─────────────────────────────────────
#
# `compute_cache_key` 지문에 PROMPT_VERSION 이 들어 있다("모델/프롬프트/입력이 바뀌면
# 키가 바뀐다"). 그런데 버전은 **손으로 올리는 상수**라, 프롬프트 파일만 고치고 잊으면
# 옛 캐시가 새 안내로 만든 결과인 척 그대로 돌아온다 — 화면엔 아무 표시도 없다.
#
# 프롬프트를 의도적으로 고쳤다면: PROMPT_VERSION 을 올리고 아래 digest 를 함께 갱신할 것.
# (실패 메시지가 새 digest 를 알려준다.)

_PROMPT_FILES = [
    "summary_rule_insight",
    "summary_mistake_patterns",
    "summary_architecture",
    "summary_testing",
    "summary_role_guidance",
]
_PROMPT_DIGEST_AT_VERSION = (6, "899e72d36c83f253")


def _prompts_digest() -> str:
    import hashlib

    from prompts import load_prompt

    h = hashlib.sha256()
    for name in _PROMPT_FILES:
        h.update(name.encode("utf-8"))
        h.update(b"\x00")
        h.update(load_prompt(name).replace("\r\n", "\n").encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def test_prompt_change_requires_a_version_bump():
    """프롬프트 본문이 바뀌었는데 PROMPT_VERSION 이 그대로면 옛 캐시가 stale 로 산다."""
    from workflow.summary_ai_insight import PROMPT_VERSION

    pinned_version, pinned_digest = _PROMPT_DIGEST_AT_VERSION
    actual = _prompts_digest()
    if actual == pinned_digest:
        assert PROMPT_VERSION == pinned_version, (
            f"프롬프트는 그대로인데 PROMPT_VERSION 이 {PROMPT_VERSION} 로 바뀌었다 — "
            f"핀({pinned_version})도 함께 갱신할 것"
        )
        return
    assert PROMPT_VERSION > pinned_version, (
        f"프롬프트 본문이 바뀌었다(digest {pinned_digest} → {actual}). "
        f"PROMPT_VERSION 을 {pinned_version} 에서 올리고 이 파일의 "
        f"_PROMPT_DIGEST_AT_VERSION 을 ({PROMPT_VERSION}, \"{actual}\") 로 갱신할 것 — "
        "안 올리면 옛 캐시가 새 프롬프트로 만든 결과인 척 돌아온다."
    )


def test_prompt_version_is_in_the_cache_key(monkeypatch):
    """버전을 올려도 키에 안 들어가면 무의미하다 — 지문에 실제로 반영되는지 본다.

    ⚠ 전역 상수를 손으로 되돌리지 않는다(`monkeypatch`). 저장소 격리 규약: teardown 에서
    "특정 값으로 고정" 하지 말고 원래 값을 복원할 것 — 누설되면 단독 실행이 깨진다.
    """
    import workflow.summary_ai_insight as mod

    inp = _inp()
    before = mod.compute_cache_key(inp, "gemini-x")
    monkeypatch.setattr(mod, "PROMPT_VERSION", mod.PROMPT_VERSION + 1)
    after = mod.compute_cache_key(inp, "gemini-x")
    assert before != after, "PROMPT_VERSION 이 캐시 키에 안 들어간다 — 프롬프트 갱신이 무효화를 못 낸다"
