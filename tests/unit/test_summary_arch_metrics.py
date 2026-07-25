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


# ── v3: 모듈 그래프·SCC 사이클·상호 의존·개선 후보 ──────────────────────────

def _write_multi_module_src(tmp_path: Path, *, back_edge: bool = False) -> Path:
    src = tmp_path / "source"
    (src / "APP").mkdir(parents=True)
    (src / "LIB").mkdir(parents=True)
    (src / "APP" / "a.c").write_text("void app_main(void) { lib_util(); }\n", encoding="utf-8")
    lib_body = "void lib_util(void) { app_main(); }\n" if back_edge else "void lib_util(void) { int x = 1; }\n"
    (src / "LIB" / "u.c").write_text(lib_body, encoding="utf-8")
    (src / ".source_complete").write_text("scm=svn\n", encoding="utf-8")
    return src


def test_module_graph_rollup(tmp_path):
    m = compute_architecture_metrics(_write_multi_module_src(tmp_path))
    g = m["module_graph"]
    mods = {n["module"]: n for n in g["nodes"]}
    assert set(mods) == {"APP", "LIB"}
    assert mods["APP"]["functions"] == 1 and mods["APP"]["files"] == 1
    assert g["edges"] == [{"from": "APP", "to": "LIB", "calls": 1}]
    assert g["truncated"] is False


def test_file_scc_cycle_and_mutual_pairs(tmp_path):
    # 기본 픽스처는 a.c(hub)→b.c(other_file_fn)→a.c(helper)의 파일 2-사이클을 이미 담는다.
    m = compute_architecture_metrics(_write_src(tmp_path))
    sccs = m["cycles"]["file_sccs"]
    assert len(sccs) == 1 and sccs[0]["size"] == 2
    assert sccs[0]["files"] == ["APP/a.c", "APP/b.c"]
    mp = m["cycles"]["mutual_file_pairs"]
    assert mp and mp[0]["a"] == "APP/a.c" and mp[0]["b"] == "APP/b.c"
    assert mp[0]["a_to_b"] == 1 and mp[0]["b_to_a"] == 1
    # 같은 모듈(APP) 내 사이클 — 모듈 SCC는 아님
    assert m["cycles"]["module_sccs"] == []


def test_module_scc_on_cross_module_cycle(tmp_path):
    m = compute_architecture_metrics(_write_multi_module_src(tmp_path, back_edge=True))
    msccs = m["cycles"]["module_sccs"]
    assert len(msccs) == 1 and msccs[0]["modules"] == ["APP", "LIB"]


def test_no_cycles_empty_arrays_not_omitted(tmp_path):
    # 비순환 — cycles 키는 항상 존재하고 빈 배열(침묵 생략 금지, 프론트가 '관측 없음' 명시 렌더).
    m = compute_architecture_metrics(_write_multi_module_src(tmp_path))
    assert m["cycles"]["file_sccs"] == []
    assert m["cycles"]["module_sccs"] == []
    assert m["cycles"]["mutual_file_pairs"] == []


def test_refactor_candidates_god_file_with_basis(tmp_path):
    src = tmp_path / "source"
    for d in ("G", "A", "B", "C"):
        (src / d).mkdir(parents=True)
    body = "".join(f"void g{i}(void) {{ int x = {i}; }}\n" for i in range(15))
    (src / "G" / "god.c").write_text(body + "void g_hub(void) { a_fn(); }\n", encoding="utf-8")
    (src / "A" / "a.c").write_text("void a_fn(void) { int y = 0; }\n", encoding="utf-8")
    (src / "B" / "b.c").write_text("void b_fn(void) { g1(); }\n", encoding="utf-8")
    (src / "C" / "c.c").write_text("void c_fn(void) { g2(); }\n", encoding="utf-8")
    (src / ".source_complete").write_text("x", encoding="utf-8")
    m = compute_architecture_metrics(src)
    gods = [c for c in m["refactor_candidates"] if c["kind"] == "god_file"]
    assert gods and gods[0]["file"] == "G/god.c"
    assert gods[0]["functions"] == 16 and gods[0]["in_files"] == 2 and gods[0]["out_files"] == 1
    assert "함수 16개" in gods[0]["basis"]  # basis는 실측 수치 문자열


def test_refactor_candidates_empty_below_threshold(tmp_path):
    # 임계 미달(소형 파일들) — 후보 없음이 정직한 출력(모든 파일을 후보로 라벨링 금지).
    m = compute_architecture_metrics(_write_multi_module_src(tmp_path))
    assert [c for c in m["refactor_candidates"] if c["kind"] == "god_file"] == []


def test_asil_by_function_map(tmp_path):
    m = compute_architecture_metrics(_write_src(tmp_path))
    byf = m["asil_functions"]["by_function"]
    assert m["asil_functions"]["count"] == len(byf) >= 1
    assert "C" in set(byf.values())  # 픽스처의 @asil C 주석


def test_iterative_tarjan_deep_chain_no_recursion_limit():
    from workflow.summary_arch_metrics import _tarjan_scc

    n = 1500
    adj = {f"f{i}": [f"f{i + 1}"] for i in range(n - 1)}
    adj[f"f{n - 1}"] = ["f0"]  # 체인 말단→시작 — 전체가 하나의 SCC
    sccs = _tarjan_scc(adj)  # 재귀 구현이면 RecursionError(기본 한도 1000)
    assert len(sccs) == 1 and len(sccs[0]) == n


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
