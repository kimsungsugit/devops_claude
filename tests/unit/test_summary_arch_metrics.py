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


# ── N5(v4): 간섭 자유 후보 · 전역 결합 · 커버리지×복잡도 · 간접 호출/캡슐화 ──

_V4_SRC = {
    # used_globals는 파일에 전역 '선언'이 있어야 잡힌다(파서 실동작).
    "APP/hi.c": (
        "unsigned int g_shared;\n"
        "/** @asil D */\n"
        "void hi_fn(void) { g_shared = 1; lo_fn(); }\n"
        "static void helper(void) { g_shared = 2; }\n"
    ),
    "BSW/lo.c": (
        "extern unsigned int g_shared;\n"
        "void lo_fn(void) { g_shared = 3; }\n"
        "void ptr_user(void) { void (*p)(void) = &hi_fn; p(); }\n"
    ),
}
_V4_NO_ASIL = {k: v.replace("/** @asil D */\n", "") for k, v in _V4_SRC.items()}


def _v4(tmp_path, files=None, **kw):
    src = tmp_path / "source"
    for rel, text in (files or _V4_SRC).items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return compute_architecture_metrics(src, **kw)


def test_arch_version_bumped():
    from workflow.summary_arch_metrics import ARCH_METRICS_VERSION

    assert ARCH_METRICS_VERSION >= 4  # v3 캐시(신규 블록 없음) 재사용 금지


def test_asil_interference_edges_and_mixed_modules(tmp_path):
    r = _v4(tmp_path, asil_by_function={"hi_fn": "D", "lo_fn": "QM"})
    intf = r["asil_interference"]
    assert intf["available"] is True and intf["graded_functions"] == 2
    edge = next(e for e in intf["edges"] if e["caller"] == "hi_fn" and e["callee"] == "lo_fn")
    assert edge["caller_asil"] == "D" and edge["callee_asil"] == "QM"
    assert edge["higher"] == "hi_fn" and edge["cross_module"] is True
    assert "판정이 아니" in intf["note"]


def test_asil_interference_honest_without_index(tmp_path):
    """등급이 어디에도 없으면 available:false — 전부 QM으로 위장하지 않는다."""
    intf = _v4(tmp_path, files=_V4_NO_ASIL)["asil_interference"]
    assert intf["available"] is False and intf["reason"] == "no_asil_index"


def test_asil_interference_falls_back_to_comment_asil(tmp_path):
    """주입 인덱스가 없어도 소스 주석이 있으면 축이 산다(폴백 경로)."""
    intf = _v4(tmp_path)["asil_interference"]
    assert intf["available"] is True and intf["graded_functions"] == 1


def test_global_coupling_counts_usage_not_writers(tmp_path):
    r = _v4(tmp_path)
    gc = r["global_coupling"]
    assert gc["available"] is True
    top = {g["global"]: g for g in gc["top"]}
    assert top["g_shared"]["functions"] >= 3      # hi_fn/helper/lo_fn
    assert top["g_shared"]["modules"] >= 2        # APP · BSW
    assert gc["cross_module_globals"] >= 1
    # read/write를 구분하지 않는다는 사실을 note가 명시(허위 'writer' 표현 금지)
    assert "읽기/쓰기를 구분하지 않는다" in gc["note"]


def test_indirect_calls_surface_graph_incompleteness(tmp_path):
    r = _v4(tmp_path)
    ic = r["indirect_calls"]
    assert ic["functions_with_indirect"] >= 1     # ptr_user의 &hi_fn 참조
    assert ic["reference_edges"] >= 1
    assert "포함되지 않는다" in ic["note"]


def test_encapsulation_marks_static_detection_unreliable(tmp_path):
    """파서의 static 판정은 과소 탐지된다 — 비율을 제공하지 않고 한계를 명시한다."""
    enc = _v4(tmp_path)["encapsulation"]
    assert enc["static_detection_reliable"] is False
    assert "static_ratio" not in enc            # 허위 '캡슐화 없음' 결론 유발 금지
    assert enc["functions"] == 4
    assert enc["header_defined_functions"] == 0
    assert enc["documented_ratio"] is not None
    assert "비율 해석 금지" in enc["note"]


def test_coverage_complexity_quadrants_and_unjoined(tmp_path):
    cov = {
        "hi_fn": {"statement": 0.4, "branch": 0.2},
        "lo_fn": {"statement": 1.0, "branch": 1.0},
        # helper/ptr_user는 인덱스에 없음 → unjoined로 계수(침묵 제외 금지)
    }
    r = _v4(tmp_path, ccn_by_function={"hi_fn": 20, "lo_fn": 2},
            coverage_by_function=cov)
    cc = r["coverage_complexity"]
    assert cc["available"] is True
    assert cc["joined"] == 2 and cc["unjoined"] == 2
    assert cc["complexity_basis"] == "vcast_ccn"
    assert [p["function"] for p in cc["priority"]] == ["hi_fn"]   # 고복잡·저커버
    assert cc["counts"]["high_complex_low_cov"] == 1


def test_coverage_complexity_absent_is_honest(tmp_path):
    cc = _v4(tmp_path)["coverage_complexity"]
    assert cc["available"] is False and cc["reason"] == "no_coverage_index"


def test_asil_functions_keeps_comment_only_contract(tmp_path):
    """by_function은 주석 기반 계약 유지 — 주입 인덱스를 섞으면 라우터 병합이 이중 계산된다."""
    r = _v4(tmp_path, asil_by_function={"lo_fn": "B"})
    assert set(r["asil_functions"]["by_function"]) == {"hi_fn"}   # 주석 보유 함수만
    assert r["asil_functions"]["index_used"] == 1                 # 실제 사용 인덱스는 별도 표기


# ── O3(v5): file_graph — 모듈 → 파일 드릴다운 재료 ──────────────────────────

def test_file_graph_nodes_carry_module_attribution(tmp_path):
    r = _v4(tmp_path)
    fg = r["file_graph"]
    by_file = {n["file"]: n for n in fg["nodes"]}
    assert set(by_file) == {"APP/hi.c", "BSW/lo.c"}
    # 모듈 귀속이 module_graph와 같은 프록시 규칙(_module_of)을 따라야 드릴다운 조인이 성립
    assert by_file["APP/hi.c"]["module"] == "APP"
    assert by_file["APP/hi.c"]["functions"] == 2      # hi_fn, helper
    assert by_file["BSW/lo.c"]["functions"] == 2      # lo_fn, ptr_user
    assert by_file["APP/hi.c"]["lines"] > 0
    assert fg["total_files"] == 2 and fg["truncated"] is False


def test_file_graph_edges_match_cross_file_calls(tmp_path):
    r = _v4(tmp_path)
    fg = r["file_graph"]
    edges = {(e["from"], e["to"]): e["calls"] for e in fg["edges"]}
    assert edges.get(("APP/hi.c", "BSW/lo.c")) == 1   # hi_fn → lo_fn
    # 모듈 그래프의 cross-module 엣지와 같은 소스(pair_counts)에서 나온다
    assert fg["total_edges"] == len(edges)


def test_file_graph_caps_are_honest(tmp_path):
    """캡 초과는 truncated:true. 잘린 노드를 가리키는 엣지는 남기지 않는다(유령 노드 방지)."""
    from workflow.summary_arch_metrics import _build_file_graph

    file_of = {f"fn{i}": f"m/f{i}.c" for i in range(10)}
    body_lines = {f"fn{i}": 10 for i in range(10)}
    pairs = {("m/f0.c", "m/f9.c"): 5, ("m/f0.c", "m/f1.c"): 3}
    fg = _build_file_graph(file_of, body_lines, pairs, max_nodes=2, max_edges=10)
    assert fg["truncated"] is True and fg["total_files"] == 10
    kept = {n["file"] for n in fg["nodes"]}
    assert len(kept) == 2
    for e in fg["edges"]:
        assert e["from"] in kept and e["to"] in kept


def test_arch_version_bumped_to_5():
    from workflow.summary_arch_metrics import ARCH_METRICS_VERSION

    assert ARCH_METRICS_VERSION >= 5  # v4 캐시(file_graph 없음) 재사용 금지


# ── Q2(v6): 계층 그래프 · DSM 위상정렬 · 전역 함수 샘플 ─────────────────────

# 함수명 휴리스틱(_classify_unmapped_layer)의 실제 분류에 맞춘 픽스처 —
# PE_* → BSW_DRIVER, Ap_* → APP_LEAF, *Lib* → LIB_UTIL (분류기가 정본이므로 그에 맞춘다).
_LAYER_SRC = {
    "APP/app.c": "void Ap_MainTask(void) { PE_Initialize_Core(); u16g_Lib_Filter(); }\n",
    # BSW가 APP을 부른다 = 하위→상위 역방향(검토 후보)
    "BSW/drv.c": "void PE_Initialize_Core(void) { Ap_MainTask(); }\n",
    "LIB/util.c": "void u16g_Lib_Filter(void) { int x = 1; }\n",
}


def test_layer_graph_ranks_and_detects_reverse_calls(tmp_path):
    r = _v4(tmp_path, files=_LAYER_SRC)
    lg = r["layer_graph"]
    assert lg["available"] is True
    ranks = {n["layer"]: n["rank"] for n in lg["nodes"]}
    assert ranks["APP_LEAF"] > ranks["BSW_DRIVER"] > ranks["LIB_UTIL"]   # 상위일수록 rank 큼
    rev = [e for e in lg["edges"] if e["reverse"]]
    assert rev and rev[0]["from"] == "BSW_DRIVER" and rev[0]["to"] == "APP_LEAF"
    pair = lg["reverse_pairs"][0]
    assert pair["caller"] == "PE_Initialize_Core" and pair["callee"] == "Ap_MainTask"
    assert pair["caller_file"] and pair["callee_file"]                   # 드릴다운용 파일 동반
    assert lg["reverse_total"] == 1


def test_layer_graph_labels_heuristic_limit(tmp_path):
    """계층은 함수명 추정이라 '위반'으로 단정하면 안 된다 — note로 한계를 고지한다."""
    lg = _v4(tmp_path, files=_LAYER_SRC)["layer_graph"]
    assert "휴리스틱" in lg["note"] and "위반" in lg["note"]
    # 그림에서 빠진 함수는 침묵시키지 않는다
    assert "excluded_test_artifact" in lg and "unclassifiable" in lg


def test_layer_graph_reverse_pairs_capped_with_omitted(tmp_path):
    from workflow.summary_arch_metrics import _build_layer_graph

    call_map = {f"Eeprom_W{i}": ["Ap_MainTask"] for i in range(40)}
    call_map["Ap_MainTask"] = []
    lg = _build_layer_graph(call_map, {}, max_pairs=10)
    assert lg["reverse_total"] == 40
    assert len(lg["reverse_pairs"]) == 10 and lg["reverse_pairs_omitted"] == 30


def test_topo_order_puts_callers_before_callees(tmp_path):
    """DSM 정렬: 비순환 그래프면 호출자가 피호출자보다 앞 — 상삼각이 비어야 한다."""
    from workflow.summary_arch_metrics import _topo_order

    files = ["a.c", "b.c", "c.c"]
    pairs = {("a.c", "b.c"): 3, ("b.c", "c.c"): 2}
    order = _topo_order(files, pairs)
    pos = {f: i for i, f in enumerate(order)}
    assert pos["a.c"] < pos["b.c"] < pos["c.c"]
    assert len(order) == 3


def test_topo_order_keeps_cycles_and_isolated_nodes():
    """순환은 응축돼 한 덩어리로 인접, 고립 노드도 빠지지 않는다(DSM에서 파일이 사라지면 안 됨)."""
    from workflow.summary_arch_metrics import _topo_order

    files = ["a.c", "b.c", "lonely.c"]
    pairs = {("a.c", "b.c"): 1, ("b.c", "a.c"): 1}     # 2-사이클
    order = _topo_order(files, pairs)
    assert set(order) == set(files) and len(order) == 3
    assert abs(order.index("a.c") - order.index("b.c")) == 1   # 응축돼 붙어 있다
    # 결정론 — 같은 입력이면 같은 순서
    assert _topo_order(files, pairs) == order


def test_global_coupling_carries_function_samples(tmp_path):
    r = _v4(tmp_path)
    top = {g["global"]: g for g in r["global_coupling"]["top"]}
    rec = top["g_shared"]
    assert rec["functions_sample"] and len(rec["functions_sample"]) <= 8
    assert set(rec["functions_sample"]) <= {"hi_fn", "helper", "lo_fn"}
    assert rec["functions_omitted"] == max(0, rec["functions"] - 8)


def test_arch_version_bumped_to_6():
    from workflow.summary_arch_metrics import ARCH_METRICS_VERSION

    assert ARCH_METRICS_VERSION >= 6  # v5 캐시(layer_graph·topo_order 없음) 재사용 금지


def test_topo_order_handles_graph_without_any_scc():
    """SCC가 하나도 없어도(전부 단일 노드) id 부여가 깨지지 않는다."""
    from workflow.summary_arch_metrics import _topo_order

    order = _topo_order(["only.c"], {})
    assert order == ["only.c"]
    assert _topo_order([], {}) == []


# ── v7: 분할 축 · 순환 간선 함수 쌍 · 간접 호출 정직화 ─────────────────────────
# 실측이 단일 알고리즘을 기각했다(god_file 8개 중 연결성분으로 갈린 건 1개, 이름으로 1개,
# 나머지 6개는 최대 덩어리 91~97%로 분할선 없음). 그 세 갈래를 여기서 고정한다.

def test_split_axis_uses_call_components_when_file_falls_apart():
    from workflow.summary_arch_metrics import split_axis_for_file

    members = ["a1", "a2", "a3", "b1", "b2"]
    calls = {"a1": ["a2"], "a2": ["a3"], "a3": [], "b1": ["b2"], "b2": []}
    r = split_axis_for_file(members, calls)
    assert r["available"] is True
    assert r["axis"] == "call_component"
    assert r["cut_calls"] == 0          # 성분 간 호출은 정의상 0 — 그냥 잘라도 의존이 안 생긴다
    assert [g["size"] for g in r["groups"]] == [3, 2]


def test_split_axis_falls_back_to_name_prefix_when_components_shatter():
    """UDS 실측: 성분은 22개로 부서지지만 이름은 WDBI/RDBI 두 축이 선명했다."""
    from workflow.summary_arch_metrics import split_axis_for_file

    members = [f"s_UDS_WDBI_{i}" for i in range(4)] + [f"s_UDS_RDBI_{i}" for i in range(3)]
    r = split_axis_for_file(members, {m: [] for m in members})   # 서로 안 부른다 = 성분 7개
    assert r["available"] is True and r["axis"] == "name_prefix"
    assert [g["label"] for g in r["groups"]] == ["s_UDS_WDBI", "s_UDS_RDBI"]


def test_split_axis_refuses_when_one_blob_dominates():
    """실측 6/8 파일이 이 경로 — 억지 군집 대신 '없다'를 반환해야 한다."""
    from workflow.summary_arch_metrics import split_axis_for_file

    members = [f"f{i}" for i in range(10)]
    calls = {f"f{i}": [f"f{i + 1}"] for i in range(9)}       # 한 줄로 전부 연결
    calls["f9"] = []
    r = split_axis_for_file(members, calls)
    assert r["available"] is False and r["reason"] == "no_natural_split"
    assert r["largest_component_share"] == 1.0


def test_split_axis_cut_edges_counted_for_prefix_axis():
    from workflow.summary_arch_metrics import split_axis_for_file

    # 그룹 안에서는 사슬로 이어져 성분이 1덩어리가 되고(=성분 축 무효), 이름 축만 남는 배치.
    # 접두사는 앞 3토큰이라 이름이 4토큰 이상이어야 군집이 생긴다(s_Mod_A_x1 → s_Mod_A).
    members = ["s_Mod_A_x1", "s_Mod_A_x2", "s_Mod_A_x3", "s_Mod_B_y1", "s_Mod_B_y2", "s_Mod_B_y3"]
    calls = {
        "s_Mod_A_x1": ["s_Mod_A_x2", "s_Mod_B_y1"],   # 마지막 하나가 군집을 가로지른다
        "s_Mod_A_x2": ["s_Mod_A_x3"], "s_Mod_A_x3": [],
        "s_Mod_B_y1": ["s_Mod_B_y2"], "s_Mod_B_y2": ["s_Mod_B_y3"], "s_Mod_B_y3": [],
    }
    r = split_axis_for_file(members, calls)
    assert r["axis"] == "name_prefix" and r["cut_calls"] == 1


def test_indirect_calls_separates_real_pointers_from_register_reads(tmp_path):
    """func_refs 는 MCU 레지스터·변수를 대량 포함한다(실측 2,708건 중 실제 함수 2건).

    그 수치를 '함수포인터 보유'로 쓰면 시임 후보가 통째로 오탐이 된다.
    """
    src = tmp_path / "source"
    (src / "BSW").mkdir(parents=True)
    (src / "BSW" / "p.c").write_text(
        "void real_target(void) { int z = 0; }\n"
        "void reg_init(void) { DDRADL = 1U; DDRJ = 2U; }\n"
        "void registrar(void) { Register(&real_target); }\n",
        encoding="utf-8",
    )
    (src / ".source_complete").write_text("scm=svn\nrevision=1\n", encoding="utf-8")
    ind = compute_architecture_metrics(src)["indirect_calls"]
    assert ind["resolved_ref_functions"] <= ind["func_ref_functions"]
    # 걸러낸 뒤 남는 참조는 프로젝트 안에 실제로 정의된 함수뿐이다
    for t in ind["top"]:
        assert t["ref_functions"] or t["pointer_symbols"]
        for r in t["ref_functions"]:
            assert r == "real_target"


def test_playbook_inputs_carry_cycle_edge_function_pairs(tmp_path):
    """'a.c 가 b.c 를 부른다'로는 못 고친다 — 어느 함수인지가 나와야 한다."""
    src = tmp_path / "source"
    (src / "SYS").mkdir(parents=True)
    (src / "SYS" / "a.c").write_text("void A_Tick(void) { B_Notify(); }\n", encoding="utf-8")
    (src / "SYS" / "b.c").write_text("void B_Notify(void) { A_Reset(); }\n"
                                     "void A_Reset(void) { int q = 0; }\n", encoding="utf-8")
    (src / ".source_complete").write_text("scm=svn\nrevision=1\n", encoding="utf-8")
    m = compute_architecture_metrics(src)
    pb = m["playbook_inputs"]
    assert "split_axis" in pb and "cycle_edge_functions" in pb
    if m["cycles"]["file_sccs"]:      # 순환이 잡혔다면 그 간선의 함수 쌍이 있어야 한다
        pairs = [p for v in pb["cycle_edge_functions"].values() for p in v]
        assert {"caller": "A_Tick", "callee": "B_Notify"} in pairs
