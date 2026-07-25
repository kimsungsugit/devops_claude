"""rule_definition — 팀 코딩 룰 초안: 환각 필터·정규화·no_code_evidence 게이트·캐시/probe."""
from __future__ import annotations

import json
from pathlib import Path

DIFF = "--- a/APP/foo.c\n+++ b/APP/foo.c\n@@ -1 +1 @@\n-int x = 42;\n+int x = X_INIT;\n"


# ── workflow 순수 계산 ──────────────────────────────────────────────────────

def _gen(agent_out, **kw):
    from workflow.rule_definition import generate_rule_definition

    return generate_rule_definition(
        rule="Rule-1.1",
        description={"title": "desc", "enabled": True, "group": "M3CM"},
        trend_row={"classification": "persistent", "first": 6, "latest": 6, "net": 0},
        evidence_diffs=[{"file": "APP/foo.c", "text": DIFF, "diff_sha": "s1"}],
        unresolved_excerpts=[],
        cfg=kw.pop("cfg", {"model": "m"}),
        agent_call=(lambda *a, **k: agent_out) if not callable(agent_out) else agent_out,
        **kw,
    )


def test_generate_definition_normalizes_output():
    out = _gen(json.dumps({
        "rule": "Rule-1.1", "intent": "의도", "rationale": "근거",
        "avoid_pattern": "int x = 42;", "comply_pattern": "int x = X_INIT;",
        "exceptions": ["e1", "", "e2", "e3", "e4", "e5"],  # 빈 항목 제거 + 4개 캡
        "evidence_basis": "위반 6건", "confidence": "HIGH?!",
    }))
    assert out["ai_enriched"] is True
    d = out["definition"]
    assert d["intent"] == "의도" and d["comply_pattern"] == "int x = X_INIT;"
    assert d["exceptions"] == ["e1", "e2", "e3", "e4"]
    assert d["confidence"] == "low"  # 비표준 값 정규화


def test_generate_definition_hallucination_and_echo_rejected():
    # 증거 밖 식별자 과반 → 폐기
    bad = _gen(json.dumps({
        "rule": "Rule-1.1", "intent": "i",
        "comply_pattern": "SomeMadeUpFn(another_fake, totally_new, ghost_var);",
    }))
    assert bad["definition"] is None and bad["enrich_reason"] == "hallucinated_identifiers"
    # 다른 규칙을 에코 → 폐기
    echo = _gen(json.dumps({"rule": "Rule-9.9", "intent": "i", "comply_pattern": "int x = X_INIT;"}))
    assert echo["definition"] is None and echo["enrich_reason"] == "rule_echo_mismatch"


def test_generate_definition_llm_fallbacks():
    # cfg 없음 → llm_unavailable (결정론 폴백 — 증거는 라우터가 이미 반환)
    off = _gen("ignored", cfg={})
    assert off["definition"] is None and off["enrich_reason"] == "llm_unavailable"

    # 호출 예외 → llm_error
    def boom(*a, **k):
        raise RuntimeError("x")
    err = _gen(boom)
    assert err["definition"] is None and err["enrich_reason"] == "llm_error"
    # 빈/무효 출력 → llm_empty_or_invalid
    empty = _gen("not json at all")
    assert empty["definition"] is None and empty["enrich_reason"] == "llm_empty_or_invalid"


# ── 라우터 (증거 조립·no_code_evidence·probe/캐시/force) ────────────────────

def _snap(tmp_path: Path, n: int, files: dict) -> Path:
    root = tmp_path / f"build_{n}"
    (root / "report").mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        p = root / "source" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def _wire(tmp_path, monkeypatch, rule_row):
    from backend.routers import summary_insight as si

    a = _snap(tmp_path, 122, {"APP/foo.c": "int x = 42;\n"})
    b = _snap(tmp_path, 125, {"APP/foo.c": "int x = X_INIT;\n"})
    metas = [
        {"build_number": 125, "build_root": str(b), "reports_dir": str(b / "report")},
        {"build_number": 122, "build_root": str(a), "reports_dir": str(a / "report")},
    ]
    monkeypatch.setattr("backend.services.build_inventory.list_cached_builds_meta", lambda **k: metas)
    monkeypatch.setattr(
        "backend.services.prqa_rule_trend.compute_rule_trend",
        lambda **k: {"ok": True, "available": True, "rules": [rule_row],
                     "observed_range": {"from_build": 122, "to_build": 125}},
    )
    return si


_ROW = {
    "rule": "Rule-1.1", "classification": "decreasing", "first": 6, "latest": 2, "net": -4,
    "description": {"title": "desc", "enabled": True, "group": "M3CM"},
    "files_latest": [{"path": "APP/foo.c", "count": 2}],
    "decreased_files": [{"path": "APP/foo.c", "from_build": 122, "to_build": 125, "delta": -4}],
}
_BODY = {"job_url": "http://j/", "rule": "Rule-1.1"}


def test_endpoint_definition_cache_probe_force(tmp_path, monkeypatch):
    si = _wire(tmp_path, monkeypatch, dict(_ROW))
    calls = {"n": 0}

    def fake_gen(**kw):
        calls["n"] += 1
        assert kw["evidence_diffs"] and kw["evidence_diffs"][0]["diff_sha"]  # 증거 조립 확인
        return {"definition": {"intent": "i", "rationale": "r", "avoid_pattern": "",
                               "comply_pattern": "int x = X_INIT;", "exceptions": [],
                               "evidence_basis": "b", "confidence": "medium"},
                "ai_enriched": True, "enrich_reason": None, "model": "gemini-3.5-flash-lite"}

    monkeypatch.setattr("workflow.rule_definition.generate_rule_definition", fake_gen)
    p = si.summary_rule_definition({**_BODY, "probe": True})
    assert p["available"] is True and p["cached"] is False and calls["n"] == 0  # probe는 LLM 0회
    assert p["evidence_used"]["fix_diffs"] == 1 and p["evidence_used"]["unresolved_excerpts"] == 1
    r1 = si.summary_rule_definition(dict(_BODY))
    assert r1["available"] is True and r1["cached"] is False and calls["n"] == 1
    assert "코딩 룰이 아닙니다" in r1["note"]  # 서버 고정 note
    assert r1["description"]["title"] == "desc"
    r2 = si.summary_rule_definition(dict(_BODY))
    assert r2["cached"] is True and calls["n"] == 1  # 캐시 히트
    r3 = si.summary_rule_definition({**_BODY, "force": True})
    assert r3["cached"] is False and calls["n"] == 2


def test_endpoint_definition_no_code_evidence(tmp_path, monkeypatch):
    row = {**_ROW, "decreased_files": [], "files_latest": [{"path": "ghost.c", "count": 1}]}
    si = _wire(tmp_path, monkeypatch, row)

    def no_llm(**kw):
        raise AssertionError("증거 0건이면 LLM에 도달하면 안 된다")

    monkeypatch.setattr("workflow.rule_definition.generate_rule_definition", no_llm)
    r = si.summary_rule_definition(dict(_BODY))
    assert r["available"] is False and r["reason"] == "no_code_evidence"


def test_endpoint_definition_rule_not_in_trend_and_params(tmp_path, monkeypatch):
    si = _wire(tmp_path, monkeypatch, dict(_ROW))
    r = si.summary_rule_definition({"job_url": "http://j/", "rule": "Rule-없음"})
    assert r["available"] is False and r["reason"] == "rule_not_in_trend"
    r2 = si.summary_rule_definition({"job_url": "http://j/"})
    assert r2["available"] is False and r2["reason"] == "params_required"
