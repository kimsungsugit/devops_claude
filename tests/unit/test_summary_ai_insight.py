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
