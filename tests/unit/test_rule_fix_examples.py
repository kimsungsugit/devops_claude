"""rule_fix_examples + workflow/rule_fix_example — diff 증거·정직 실패·환각 필터·캐시."""
from __future__ import annotations

import json
from pathlib import Path


def _snap(tmp_path: Path, n: int, files: dict) -> Path:
    root = tmp_path / f"build_{n}"
    (root / "report").mkdir(parents=True, exist_ok=True)
    src = root / "source"
    for rel, text in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


# ── 증거 수집 ────────────────────────────────────────────────────────────────

def test_evidence_diff_between_snapshots(tmp_path):
    from backend.services.rule_fix_examples import collect_fix_evidence

    a = _snap(tmp_path, 122, {"APP/src/foo.c": "int x = 42;\nint y = 0;\n"})
    b = _snap(tmp_path, 125, {"APP/src/foo.c": "#define X_INIT (42)\nint x = X_INIT;\nint y = 0;\n"})
    ev = collect_fix_evidence(from_build_root=a, to_build_root=b, file="src/foo.c")
    assert ev["ok"] is True
    assert "-int x = 42;" in ev["diff"]["text"] and "+int x = X_INIT;" in ev["diff"]["text"]
    assert ev["diff"]["truncated"] is False and ev["diff"]["hunks_total"] == 1
    assert ev["diff_sha"]


def test_evidence_unchanged_file_honest_reason(tmp_path):
    from backend.services.rule_fix_examples import collect_fix_evidence

    a = _snap(tmp_path, 122, {"APP/foo.c": "int x;\n"})
    b = _snap(tmp_path, 125, {"APP/foo.c": "int x;\n"})
    ev = collect_fix_evidence(from_build_root=a, to_build_root=b, file="foo.c")
    assert ev["ok"] is False and ev["reason"] == "file_unchanged_between_builds"


def test_evidence_ambiguous_and_missing(tmp_path):
    from backend.services.rule_fix_examples import collect_fix_evidence

    a = _snap(tmp_path, 122, {"APP/config.c": "int a;\n", "BOOT/config.c": "int b;\n"})
    b = _snap(tmp_path, 125, {"APP/config.c": "int a2;\n", "BOOT/config.c": "int b;\n"})
    # basename만으로는 2개 매치 — ambiguous 정직 실패(오귀속 금지)
    ev = collect_fix_evidence(from_build_root=a, to_build_root=b, file="config.c")
    assert ev["ok"] is False and ev["reason"] == "file_ambiguous_in_snapshot"
    # 경로 suffix가 있으면 확정
    ev2 = collect_fix_evidence(from_build_root=a, to_build_root=b, file="APP/config.c")
    assert ev2["ok"] is True
    # 부재
    ev3 = collect_fix_evidence(from_build_root=a, to_build_root=b, file="ghost.c")
    assert ev3["ok"] is False and ev3["reason"] == "file_not_in_snapshot"
    # 스냅샷 자체 없음
    c = tmp_path / "build_999"
    (c / "report").mkdir(parents=True)
    ev4 = collect_fix_evidence(from_build_root=c, to_build_root=b, file="APP/config.c")
    assert ev4["ok"] is False and ev4["reason"] == "snapshot_missing"


def test_diff_cap_and_truncated_flag(tmp_path):
    from backend.services.rule_fix_examples import capped_unified_diff

    a = "\n".join(f"line{i}" for i in range(300))
    b = "\n".join((f"line{i}X" if i % 20 == 0 else f"line{i}") for i in range(300))
    d = capped_unified_diff(a, b, "x.c", max_hunks=2, max_chars=500)
    assert d["truncated"] is True
    assert d["hunks_used"] <= 2 and d["hunks_total"] > d["hunks_used"]
    assert len(d["text"]) <= 600  # 캡 + 마지막 라인 여유


# ── 환각 필터 ────────────────────────────────────────────────────────────────

def test_hallucination_identifier_filter():
    from workflow.rule_fix_example import hallucination_check

    diff = "-int x = 42;\n+int x = X_INIT;\n+#define X_INIT (42)"
    ok_example = {"rule": "Rule-1.1", "compliant_pattern": "#define X_INIT (42)\nint x = X_INIT;", "avoid_pattern": "int x = 42;"}
    assert hallucination_check(ok_example, diff, "Rule-1.1") is None
    fake = {"rule": "Rule-1.1", "compliant_pattern": "MotorCtrl_SetSpeed(speed_rpm, GEAR_TABLE[idx]);", "avoid_pattern": ""}
    assert hallucination_check(fake, diff, "Rule-1.1") == "hallucinated_identifiers"
    echo = {"rule": "Rule-9.9", "compliant_pattern": "int x = X_INIT;"}
    assert hallucination_check(echo, diff, "Rule-1.1") == "rule_echo_mismatch"


def test_generate_fix_example_llm_paths(monkeypatch):
    from workflow.rule_fix_example import generate_fix_example

    diff = "-int x = 42;\n+int x = X_INIT;"
    # LLM 미설정 → 정상 폴백
    out = generate_fix_example(rule="Rule-1.1", diff_excerpt=diff, cfg=None,
                               agent_call=lambda *a, **k: None)
    # cfg=None 명시라 내부 해석 시도 — 해석 결과가 있어도 agent_call이 None을 주면 invalid.
    assert out["example"] is None
    # 정상 응답
    ok = generate_fix_example(
        rule="Rule-1.1", diff_excerpt=diff, cfg={"model": "gemini-test"},
        agent_call=lambda *a, **k: json.dumps({
            "rule": "Rule-1.1", "explanation": "e", "avoid_pattern": "int x = 42;",
            "compliant_pattern": "int x = X_INIT;", "confidence": "HIGH?!",
        }),
    )
    assert ok["ai_enriched"] is True
    assert ok["example"]["confidence"] == "low"  # 비표준 값 정규화
    # 예외 → llm_error
    def boom(*a, **k):
        raise RuntimeError("x")
    err = generate_fix_example(rule="R", diff_excerpt=diff, cfg={"model": "m"}, agent_call=boom)
    assert err["ai_enriched"] is False and err["enrich_reason"] == "llm_error"


# ── 엔드포인트 (캐시/probe/정직 실패) ──────────────────────────────────────

def _wire(tmp_path, monkeypatch, a_root, b_root):
    from backend.routers import summary_insight as si

    metas = [
        {"build_number": 125, "build_root": str(b_root), "reports_dir": str(b_root / "report")},
        {"build_number": 122, "build_root": str(a_root), "reports_dir": str(a_root / "report")},
    ]
    monkeypatch.setattr("backend.services.build_inventory.list_cached_builds_meta", lambda **k: metas)
    return si


def test_endpoint_fix_example_cache_and_force(tmp_path, monkeypatch):
    a = _snap(tmp_path, 122, {"APP/foo.c": "int x = 42;\n"})
    b = _snap(tmp_path, 125, {"APP/foo.c": "int x = X_INIT;\n"})
    si = _wire(tmp_path, monkeypatch, a, b)
    calls = {"n": 0}

    def fake_gen(**kw):
        calls["n"] += 1
        return {"example": {"explanation": "e", "avoid_pattern": "", "compliant_pattern": "int x = X_INIT;", "confidence": "medium"},
                "ai_enriched": True, "enrich_reason": None, "model": "gemini-3.5-flash-lite"}

    monkeypatch.setattr("workflow.rule_fix_example.generate_fix_example", fake_gen)
    body = {"job_url": "http://j/", "rule": "Rule-1.1", "file": "APP/foo.c", "from_build": 122, "to_build": 125}
    r1 = si.summary_rule_fix_example(body)
    assert r1["available"] is True and r1["cached"] is False and calls["n"] == 1
    assert r1["correlation_note"] and "인과" in r1["correlation_note"]  # 서버 고정 주입
    assert "-int x = 42;" in r1["evidence"]["text"]
    r2 = si.summary_rule_fix_example(body)
    assert r2["cached"] is True and calls["n"] == 1  # 캐시 히트 — LLM 재호출 없음
    r3 = si.summary_rule_fix_example({**body, "force": True})
    assert r3["cached"] is False and calls["n"] == 2


def test_endpoint_fix_example_probe_no_llm(tmp_path, monkeypatch):
    a = _snap(tmp_path, 122, {"APP/foo.c": "a\n"})
    b = _snap(tmp_path, 125, {"APP/foo.c": "b\n"})
    si = _wire(tmp_path, monkeypatch, a, b)

    def no_llm(**kw):
        raise AssertionError("probe must not reach LLM")

    monkeypatch.setattr("workflow.rule_fix_example.generate_fix_example", no_llm)
    r = si.summary_rule_fix_example({"job_url": "http://j/", "rule": "R", "file": "APP/foo.c",
                                     "from_build": 122, "to_build": 125, "probe": True})
    assert r["available"] is True and r["cached"] is False


def test_endpoint_fix_example_honest_reasons(tmp_path, monkeypatch):
    a = _snap(tmp_path, 122, {"APP/foo.c": "same\n"})
    b = _snap(tmp_path, 125, {"APP/foo.c": "same\n"})
    si = _wire(tmp_path, monkeypatch, a, b)
    r = si.summary_rule_fix_example({"job_url": "http://j/", "rule": "R", "file": "APP/foo.c",
                                     "from_build": 122, "to_build": 125})
    assert r["available"] is False and r["reason"] == "file_unchanged_between_builds"
    r2 = si.summary_rule_fix_example({"job_url": "http://j/", "rule": "R", "file": "APP/foo.c",
                                      "from_build": 122, "to_build": 999})
    assert r2["available"] is False and r2["reason"] == "build_not_cached"
    r3 = si.summary_rule_fix_example({"job_url": "http://j/"})
    assert r3["available"] is False and r3["reason"] == "params_required"
