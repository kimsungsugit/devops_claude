"""summary_arch_metrics — fan 계산·ccn/proxy 라벨·결합도·발췌 캡 + AI architecture 섹션."""
from __future__ import annotations

import json
from pathlib import Path

from workflow.summary_arch_metrics import compute_architecture_metrics


def _write_src(tmp_path: Path) -> Path:
    src = tmp_path / "source"
    (src / "APP").mkdir(parents=True)
    (src / "APP" / "a.c").write_text(
        "/** @asil C */\n"
        "void hub(void) { helper(); helper(); other_file_fn(); }\n"
        "void helper(void) { int x = 1; }\n",
        encoding="utf-8",
    )
    (src / "APP" / "b.c").write_text(
        "void other_file_fn(void) { helper(); }\n"
        "void big_fn(void) {\n" + ("    int y;\n" * 120) + "}\n",
        encoding="utf-8",
    )
    (src / ".source_complete").write_text("scm=svn\nrevision=1\n", encoding="utf-8")
    return src


def test_fan_in_out_and_coupling(tmp_path):
    src = _write_src(tmp_path)
    m = compute_architecture_metrics(src)
    assert m["available"] is True
    assert m["snapshot"]["functions"] == 4
    fan = {r["function"]: r for r in m["fan"]}
    # helper: hub와 other_file_fn이 호출 → fan_in 2 (중복 호출은 1로 dedup)
    assert fan["helper"]["fan_in"] == 2 and fan["helper"]["fan_out"] == 0
    assert fan["hub"]["fan_out"] == 2  # helper + other_file_fn (dedup)
    # 결합: hub(a.c)→other_file_fn(b.c), other_file_fn(b.c)→helper(a.c) = cross 2
    assert m["coupling"]["cross_edges"] == 2
    assert m["coupling"]["top_pairs"]
    # 대형 함수 아웃라이어
    assert m["size_outliers"][0]["function"] == "big_fn"
    # ASIL 주석 함수 계수
    assert m["asil_functions"]["count"] >= 1


def test_complexity_source_labeling(tmp_path):
    """ccn 조인 함수는 vcast_ccn, 미매칭은 loc_proxy 라벨(측정≠추정 정직성)."""
    src = _write_src(tmp_path)
    m = compute_architecture_metrics(src, ccn_by_function={"helper": 7})
    hot = {h["function"]: h for h in m["hotspots"]}
    assert hot["helper"]["complexity"] == 7 and hot["helper"]["complexity_source"] == "vcast_ccn"
    # helper 외(fan_in>0인 other_file_fn)는 프록시
    if "other_file_fn" in hot:
        assert hot["other_file_fn"]["complexity_source"] == "loc_proxy"


def test_excerpt_cap(tmp_path):
    src = _write_src(tmp_path)
    m = compute_architecture_metrics(src, ccn_by_function={"helper": 50}, excerpt_max_lines=10)
    assert m["excerpts"]
    for e in m["excerpts"]:
        assert len(e["text"].splitlines()) <= 10


def test_unavailable_on_empty_dir(tmp_path):
    empty = tmp_path / "source"
    empty.mkdir()
    m = compute_architecture_metrics(empty)
    assert m["available"] is False and m["reason"] == "no_functions_parsed"


# ── AI architecture 섹션(환각 필터·폴백) ────────────────────────────────────

def _arch_fixture():
    return {
        "available": True,
        "snapshot": {"files": 2, "functions": 4, "parse_ms": 10},
        "fan": [{"function": "hub", "file": "APP/a.c", "fan_in": 0, "fan_out": 2}],
        "hotspots": [{"function": "helper", "file": "APP/a.c", "fan_in": 2, "complexity": 7, "complexity_source": "vcast_ccn", "score": 14}],
        "coupling": {"edges": 4, "cross_edges": 2, "cross_file_call_ratio": 0.5,
                     "top_pairs": [{"from_file": "APP/a.c", "to_file": "APP/b.c", "calls": 1}]},
        "size_outliers": [{"function": "big_fn", "file": "APP/b.c", "lines": 122}],
        "asil_functions": {"count": 1},
        "excerpts": [{"function": "helper", "file": "APP/a.c", "text": "void helper(void) {}", "truncated": False}],
    }


def test_architecture_section_enriched_and_symbol_filter():
    from tests.unit.test_summary_ai_insight import CFG, _fake_agent, _inp
    from workflow.summary_ai_insight import generate_summary_insight

    agent = _fake_agent({
        "summary_architecture": json.dumps({"items": [
            {"topic": "hotspot", "finding": "f", "suggestion": "s", "functions": ["helper"], "files": [], "basis": "fan_in 2 × ccn 7", "confidence": "medium"},
            {"topic": "coupling", "finding": "환각", "suggestion": "", "functions": ["ghost_fn"], "files": ["ghost.c"], "basis": ""},
        ]}),
    })
    res = generate_summary_insight(_inp(arch_metrics=_arch_fixture()), sections=("architecture",),
                                   llm_cfg=CFG, agent_call=agent)
    sec = res["sections"]["architecture"]
    assert sec["ai_enriched"] is True
    assert len(sec["items"]) == 1 and sec["items"][0]["functions"] == ["helper"]  # 환각 심볼 드랍
    # 결정론 코어에도 아키텍처 요약 병합
    assert res["deterministic"]["architecture"]["available"] is True


def test_architecture_section_unavailable_without_metrics():
    from tests.unit.test_summary_ai_insight import _inp
    from workflow.summary_ai_insight import generate_summary_insight

    res = generate_summary_insight(_inp(), use_llm=False)
    assert res["sections"]["architecture"]["ai_enriched"] is False
    assert res["deterministic"]["architecture"] == {"available": False, "reason": "no_source_snapshot"}
