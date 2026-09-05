"""콜트리 엔진 테스트 — C1/C2 결함 회귀 + 정밀(tree-sitter) 엔진.

- C1: jenkins 라우터가 call_tree 심볼을 import하는지(과거 NameError 500).
- C2: build_call_tree(regex)에 custom external_map을 넘기면 분류에 반영되는지
      (과거 지역변수 shadow로 무력화되던 결함).
- build_call_tree_precise: tree-sitter 호출엣지 + ASIL 메타 + external 분리 + missing.
"""
from __future__ import annotations

import pytest

from backend.services.call_tree import (
    build_call_tree,
    build_call_tree_precise,
    call_tree_to_csv,
    call_tree_to_html,
)

C_SAMPLE = """
#include <stdio.h>

int helper(int x) { return x * 2; }
int leaf(void) { return 42; }

int compute(int a) {
    int r = helper(a);
    r += leaf();
    return r;
}

/**
 * @asil D
 */
void main_entry(void) {
    int v = compute(10);
    printf("%d", v);
}
"""


# ── C1: jenkins 라우터 import 회귀 ──────────────────────────────────────────
def test_jenkins_imports_call_tree_symbols():
    """C1 회귀: jenkins 라우터에서 call_tree 심볼이 import되어 NameError 500이 없어야 한다."""
    from backend.routers import jenkins

    assert callable(jenkins.build_call_tree)
    assert callable(jenkins.build_call_tree_precise)
    assert callable(jenkins.call_tree_to_csv)
    assert callable(jenkins.call_tree_to_html)


# ── C2: regex 엔진 custom external_map 반영 ─────────────────────────────────
def test_regex_external_map_custom_applied(tmp_path):
    """C2 회귀: custom external_map의 header/library가 external 분류에 반영되어야 한다.

    과거에는 build_call_tree 내부 지역변수 external_map={}이 파라미터를 shadow해
    custom 분류가 무시되고 header='unknown'으로 떨어졌다.
    """
    (tmp_path / "m.c").write_text(
        "int entry(void) { my_custom_extern(); return 0; }\n", encoding="utf-8"
    )
    payload = build_call_tree(
        tmp_path,
        ["entry"],
        include_external=True,
        external_map=[{"names": ["my_custom_extern"], "header": "custom.h", "library": "mylib"}],
    )
    tree = payload["trees"][0]
    exts = {e["name"]: e for e in tree.get("externals", [])}
    assert "my_custom_extern" in exts, "external 호출이 누락됨"
    assert exts["my_custom_extern"]["header"] == "custom.h"  # C2 fix
    assert exts["my_custom_extern"]["library"] == "mylib"


# ── 정밀 엔진 ───────────────────────────────────────────────────────────────
def test_precise_basic_tree_and_asil(tmp_path):
    (tmp_path / "sample.c").write_text(C_SAMPLE, encoding="utf-8")
    payload = build_call_tree_precise(tmp_path, ["main_entry"], max_depth=6, include_external=True)

    assert payload["stats"]["engine"] == "tree-sitter"
    assert payload["missing"] == []
    assert payload["stats"]["functions"] == 4

    root = payload["trees"][0]
    assert root["name"] == "main_entry"
    assert root.get("asil") == "D"  # Doxygen @asil 추출 → 노드 보강
    assert root.get("file")        # 소스 점프용 메타
    assert root.get("signature")

    child_names = [c["name"] for c in root["calls"]]
    assert "compute" in child_names
    compute = next(c for c in root["calls"] if c["name"] == "compute")
    grand = {c["name"] for c in compute["calls"]}
    assert {"helper", "leaf"} <= grand


def test_precise_external_split(tmp_path):
    """known(프로젝트 정의)에 없는 호출은 자식 노드가 아니라 external로 분리되어야 한다."""
    (tmp_path / "s.c").write_text(
        "int leaf(void){ return 1; }\n"
        "int entry(void){ leaf(); some_undefined_api(); return 0; }\n",
        encoding="utf-8",
    )
    payload = build_call_tree_precise(tmp_path, ["entry"], include_external=True)
    root = payload["trees"][0]
    internal = {c["name"] for c in root["calls"]}
    assert "leaf" in internal
    assert "some_undefined_api" not in internal
    exts = {e["name"] for e in root.get("externals", [])}
    assert "some_undefined_api" in exts


def test_precise_missing_entry(tmp_path):
    (tmp_path / "x.c").write_text("int foo(void){ return 0; }\n", encoding="utf-8")
    payload = build_call_tree_precise(tmp_path, ["nonexistent"])
    assert "nonexistent" in payload["missing"]
    assert payload["trees"] == []


def test_precise_empty_dir_graceful(tmp_path):
    """빈 디렉토리: 함수 0개, entry는 missing — 크래시 없이 graceful."""
    payload = build_call_tree_precise(tmp_path, ["main"])
    assert payload["stats"]["functions"] == 0
    assert "main" in payload["missing"]
    assert payload["trees"] == []


def test_precise_serialize_csv_html(tmp_path):
    (tmp_path / "sample.c").write_text(C_SAMPLE, encoding="utf-8")
    payload = build_call_tree_precise(tmp_path, ["main_entry"], max_depth=6)
    csv_out = call_tree_to_csv(payload)
    assert "main_entry" in csv_out and "compute" in csv_out
    html_out = call_tree_to_html(payload)
    assert "<li>" in html_out and "main_entry" in html_out


def test_precise_include_exclude_filter(tmp_path):
    """include/exclude가 함수의 소스 파일 경로 기준으로 적용되어야 한다."""
    (tmp_path / "keep.c").write_text(
        "int kept(void){ return 0; }\nint entry(void){ kept(); return 0; }\n", encoding="utf-8"
    )
    sub = tmp_path / "vendor"
    sub.mkdir()
    (sub / "skip.c").write_text("int vendor_fn(void){ return 0; }\n", encoding="utf-8")
    payload = build_call_tree_precise(tmp_path, ["entry"], exclude_paths=["vendor"])
    # vendor_fn은 제외됐어야 함(트리에 무관하지만 functions 카운트에 미포함)
    assert payload["stats"]["functions"] == 2  # kept, entry (vendor_fn 제외)


def test_precise_excluded_func_not_misclassified_external(tmp_path):
    """리뷰 finding[1] 회귀: include/exclude로 제외된 프로젝트 함수가 external(unknown
    라이브러리)로 오분류되지 않고 internal leaf로 표시되어야 한다."""
    (tmp_path / "main.c").write_text(
        "int entry(void){ vendor_fn(); return 0; }\n", encoding="utf-8"
    )
    sub = tmp_path / "vendor"
    sub.mkdir()
    (sub / "v.c").write_text("int vendor_fn(void){ return 0; }\n", encoding="utf-8")
    payload = build_call_tree_precise(
        tmp_path, ["entry"], exclude_paths=["vendor"], include_external=True
    )
    root = payload["trees"][0]
    internal = {c["name"] for c in root["calls"]}
    exts = {e["name"] for e in root.get("externals", [])}
    assert "vendor_fn" in internal, "제외된 프로젝트 함수가 internal leaf로 남아야 함"
    assert "vendor_fn" not in exts, "제외된 프로젝트 함수가 external로 오분류되면 안 됨"


def test_precise_engine_label_present(tmp_path):
    """리뷰 finding[2]: engine 라벨이 tree-sitter|regex-fallback 중 하나로 정직하게 표기."""
    (tmp_path / "s.c").write_text("int f(void){ return 0; }\n", encoding="utf-8")
    payload = build_call_tree_precise(tmp_path, ["f"])
    assert payload["stats"]["engine"] in ("tree-sitter", "regex-fallback")


# ── 전체 콜트리(auto_roots) ────────────────────────────────────────────────
def test_auto_root_entries_indegree_zero():
    """in-degree 0 함수만 루트. 호출되는 함수는 루트에서 제외되고 결정적 정렬."""
    from backend.services.call_tree import _auto_root_entries

    call_map = {"main": ["a", "b"], "a": ["c"], "b": ["c"], "c": []}
    known = set(call_map)
    assert _auto_root_entries(call_map, known) == ["main"]


def test_auto_root_entries_covers_cycle_only_component():
    """순환만으로 묶여 in-degree 0 진입점이 없는 컴포넌트도 대표 루트로 흡수(100% 커버)."""
    from backend.services.call_tree import _auto_root_entries

    # main→a(→b→a 순환). x↔y는 서로만 호출(진입점 없음) → 대표 1개 추가 루트.
    call_map = {"main": ["a"], "a": ["b"], "b": ["a"], "x": ["y"], "y": ["x"]}
    known = set(call_map)
    roots = _auto_root_entries(call_map, known)
    # 결정성 계약: main(in-degree 0) + 순환 {x,y} 대표는 정렬 최소값 'x' — 정확값으로 잠근다
    # (멤버십만 단언하면 sorted() 제거 같은 결정성 회귀를 못 잡음).
    assert roots == ["main", "x"]
    # 루트 forest가 known 전체를 도달해야 함
    reached = set()
    stack = list(roots)
    while stack:
        n = stack.pop()
        if n in reached:
            continue
        reached.add(n)
        stack.extend(c for c in call_map.get(n, []) if c in known)
    assert reached == known


def test_auto_root_entries_self_loop_and_empty():
    """self-loop(f→f)는 in-degree 0이 아니나 순환 흡수로 루트가 되어야 하고, 빈 입력은 [](크래시 없음)."""
    from backend.services.call_tree import _auto_root_entries

    assert _auto_root_entries({"x": ["x"]}, {"x"}) == ["x"]
    assert _auto_root_entries({}, set()) == []


def test_auto_root_entries_multi_cycle_determinism():
    """복수 순환 전용 컴포넌트 → 각 대표는 정렬 최소값, 전체 정렬 순(dict 삽입 순서 무관)."""
    from backend.services.call_tree import _auto_root_entries

    cm = {"b": ["a"], "a": ["b"], "d": ["c"], "c": ["d"]}
    assert _auto_root_entries(cm, set(cm)) == ["a", "c"]


def test_auto_root_entries_boot_priority_ordering():
    """루트 정렬은 (진입점 우선순위, 이름) — boot(main·_Startup) → ISR → 일반 순.

    truncation([:_MAX_AUTO_ROOTS])이 이 순서로 선택하므로 boot 루트가 알파벳에 밀려 절단되지
    않아야 한다. 모두 in-degree 0 루트인 함수들만 두고 순서를 정확값으로 잠근다.
    """
    from backend.services.call_tree import _auto_root_entries

    # 알파벳 순이면 [Cpu_Interrupt, _Startup, main, zzz_helper], boot 우선이면 아래 순서.
    cm = {"_Startup": [], "main": [], "Cpu_Interrupt": [], "zzz_helper": []}
    roots = _auto_root_entries(cm, set(cm))
    # boot(_startup, main) 먼저(그 안에서 이름순 '_' < 'm'), 그 다음 ISR(Cpu_Interrupt), 마지막 일반.
    assert roots == ["_Startup", "main", "Cpu_Interrupt", "zzz_helper"]


def test_root_priority_classification():
    """_root_priority: boot=0 / ISR·인터럽트=1 / 일반=2 (대소문자·접미/접두 규칙)."""
    from backend.services.call_tree import _root_priority

    assert _root_priority("main") == 0
    assert _root_priority("_Startup") == 0
    assert _root_priority("_EntryPoint") == 0
    assert _root_priority("Cpu_Interrupt") == 1
    assert _root_priority("lin_lld_sci_isr") == 1
    assert _root_priority("ISR_Handler") == 1
    assert _root_priority("g_Ap_DoorCtrl_GetDrMovgTmMon") == 2


def test_auto_roots_root_cap_and_truncation_flag(tmp_path, monkeypatch):
    """루트 수가 _MAX_AUTO_ROOTS를 넘으면 [:cap]으로 bound하고 roots_truncated=True로 정직 노출."""
    import backend.services.call_tree as ct

    monkeypatch.setattr(ct, "_MAX_AUTO_ROOTS", 2)
    # 서로 호출하지 않는 leaf 4개 → 전부 in-degree 0 루트
    (tmp_path / "s.c").write_text(
        "int f1(void){return 1;}\nint f2(void){return 2;}\nint f3(void){return 3;}\nint f4(void){return 4;}\n",
        encoding="utf-8",
    )
    payload = ct.build_call_tree_precise(tmp_path, [], auto_roots=True)
    st = payload["stats"]
    assert st["roots"] == 2
    assert st["roots_total"] == 4
    assert st["roots_truncated"] is True


def test_auto_roots_node_budget_truncation(tmp_path, monkeypatch):
    """포레스트 노드가 _MAX_FOREST_NODES를 넘으면 nodes_truncated=True(경로 열거 팽창 방어)."""
    import backend.services.call_tree as ct

    monkeypatch.setattr(ct, "_MAX_FOREST_NODES", 2)  # main_entry→compute→helper/leaf: 2노드 초과
    (tmp_path / "sample.c").write_text(C_SAMPLE, encoding="utf-8")
    payload = ct.build_call_tree_precise(tmp_path, [], max_depth=8, auto_roots=True)
    assert payload["stats"]["nodes_truncated"] is True


def test_precise_auto_roots_full_forest(tmp_path):
    """auto_roots=True면 entry 없이 전체 forest 구성 — 모든 함수 도달, stats.roots 노출, missing 없음."""
    (tmp_path / "sample.c").write_text(C_SAMPLE, encoding="utf-8")
    payload = build_call_tree_precise(tmp_path, [], max_depth=8, auto_roots=True)
    st = payload["stats"]
    assert st["roots"] >= 1
    assert st["functions"] == 4  # helper, leaf, compute, main_entry
    assert payload["missing"] == []
    root_names = {t["name"] for t in payload["trees"]}
    # main_entry는 아무도 호출하지 않으므로 루트여야 함(helper/leaf/compute는 호출됨)
    assert "main_entry" in root_names
    assert "helper" not in root_names


def test_regex_auto_roots_parity(tmp_path):
    """regex 엔진도 auto_roots 지원(엔진 간 parity) — 루트 산출 + missing 없음."""
    (tmp_path / "sample.c").write_text(C_SAMPLE, encoding="utf-8")
    payload = build_call_tree(tmp_path, [], max_depth=8, auto_roots=True)
    assert payload["stats"]["roots"] >= 1
    assert payload["missing"] == []
    assert any(t["name"] == "main_entry" for t in payload["trees"])


# ── #if 중첩 함수 파싱 회귀(tree-sitter가 preproc_if 안 함수를 놓쳐 전 파일 regex 폴백되던 결함) ──
_C_PREPROC = """
typedef unsigned char (*cb_t)(void);
static unsigned char s_safety_check(void) { return 1; }

#if defined(FEATURE_A)
void reg_site(void) {
    cb_t pfn = &s_safety_check;   /* 주소취득 → func_ref 승격 대상 */
    dispatch(pfn);                /* 인자 전달 → func_ref */
}
#endif
"""


def test_preproc_if_nested_functions_parsed(tmp_path):
    """#if/#endif 안에 감싼 함수도 tree-sitter로 추출돼야 한다(엔진=tree-sitter 유지, 폴백 아님)."""
    (tmp_path / "p.c").write_text(_C_PREPROC, encoding="utf-8")
    payload = build_call_tree_precise(tmp_path, [], max_depth=5, auto_roots=True)
    names = {f for t in payload["trees"] for f in _all_names(t)}
    # preproc_if 안의 reg_site와 밖의 s_safety_check 둘 다 known으로 잡혀야 함
    assert payload["stats"]["functions"] >= 2
    assert payload["stats"]["engine"] == "tree-sitter"
    assert "reg_site" in names or "s_safety_check" in names


def _all_names(node):
    yield node.get("name")
    for c in node.get("calls", []) or []:
        yield from _all_names(c)


# ── feature 2: 함수포인터 참조(&foo/f(foo)) → known 엣지 승격 + via_ref 태그 ──
def test_func_ref_promotion_and_via_ref(tmp_path):
    (tmp_path / "r.c").write_text(_C_PREPROC, encoding="utf-8")
    # reg_site를 진입점으로 — &s_safety_check 참조가 엣지로 승격되고 via_ref=True여야 함
    payload = build_call_tree_precise(tmp_path, ["reg_site"], max_depth=3)
    assert payload["trees"], "reg_site 트리 필요"
    kids = {c["name"]: c for c in payload["trees"][0]["calls"]}
    assert "s_safety_check" in kids, "함수포인터 참조가 엣지로 승격돼야 함"
    assert kids["s_safety_check"].get("via_ref") is True, "추론 엣지는 via_ref로 표시"


# ── feature 3: 미해결 간접호출(디스패치/함수포인터) → node.indirect 배지 ──
_C_INDIRECT = """
typedef struct { unsigned char (*pf_Handler)(void); } entry_t;
static entry_t s_tbl[4];
unsigned char u8_i;

void dispatch_via_table(void) {
    s_tbl[u8_i].pf_Handler();   /* 미해결 간접호출 — 대상 못 이음 */
    real_leaf();
}
unsigned char real_leaf(void) { return 0; }
"""


def test_indirect_pointer_call_badge(tmp_path):
    (tmp_path / "i.c").write_text(_C_INDIRECT, encoding="utf-8")
    payload = build_call_tree_precise(tmp_path, ["dispatch_via_table"], max_depth=2)
    node = payload["trees"][0]
    assert node.get("indirect"), "간접호출 사이트가 node.indirect로 노출돼야 함"
    assert any("pf_Handler" in x for x in node["indirect"])
    # 직접 호출은 정상 엣지로 남아야 함
    assert any(c["name"] == "real_leaf" for c in node["calls"])


def test_indirect_macro_uppercase_not_flagged(tmp_path):
    """함수형 매크로(전대문자, 예: CALLBACK_HANDLER)는 이름이 handler 패턴이라도 간접호출 배지 아님.

    preprocess=False라 매크로가 미해결 call로 보이나, 전대문자 관례로 제외(_extract_calls와 동일 정책).
    반면 실 함수포인터(pfn_… 혼합 케이스)는 배지 유지.
    """
    src = """
void caller(void) {
    EVENT_HANDLER(1, 2);      /* 함수형 매크로 — 간접호출 아님 */
    pfn_SafetyCheck();        /* 진짜 함수포인터 파라미터 */
    real_leaf();
}
unsigned char real_leaf(void) { return 0; }
"""
    (tmp_path / "m.c").write_text(src, encoding="utf-8")
    payload = build_call_tree_precise(tmp_path, ["caller"], max_depth=2)
    ind = payload["trees"][0].get("indirect") or []
    assert not any("EVENT_HANDLER" in x for x in ind), "전대문자 매크로는 간접호출 배지 아님"
    assert any("pfn_SafetyCheck" in x for x in ind), "진짜 함수포인터는 배지 유지"


def test_indirect_resolved_identifier_excluded(tmp_path):
    """pfn 관례 이름이라도 known으로 해결되면(실제 정의 존재) indirect 배지에서 제외."""
    src = """
unsigned char pfn_ok(void) { return 1; }
void caller(void) { pfn_ok(); }
"""
    (tmp_path / "k.c").write_text(src, encoding="utf-8")
    payload = build_call_tree_precise(tmp_path, ["caller"], max_depth=2)
    node = payload["trees"][0]
    assert not node.get("indirect"), "known으로 해결되는 호출은 간접 배지 아님"
    assert any(c["name"] == "pfn_ok" for c in node["calls"])


# ── feature 1: 역방향(called-by) 트리 ──
def test_reverse_called_by(tmp_path):
    (tmp_path / "s.c").write_text(C_SAMPLE, encoding="utf-8")
    # compute를 호출하는 것은 main_entry — 역방향에서 compute의 자식으로 main_entry가 와야 함
    fwd = build_call_tree_precise(tmp_path, ["compute"], max_depth=2)
    assert fwd["stats"]["reverse"] is False
    assert any(c["name"] in ("helper", "leaf") for c in fwd["trees"][0]["calls"])
    rev = build_call_tree_precise(tmp_path, ["compute"], max_depth=2, reverse=True)
    assert rev["stats"]["reverse"] is True
    callers = {c["name"] for c in rev["trees"][0]["calls"]}
    assert "main_entry" in callers, "compute의 호출자는 main_entry"
    assert "helper" not in callers, "역방향엔 callee가 아니라 caller가 와야 함"


def test_reverse_regex_parity(tmp_path):
    """regex 엔진도 reverse 지원(엔진 간 parity)."""
    (tmp_path / "s.c").write_text(C_SAMPLE, encoding="utf-8")
    rev = build_call_tree(tmp_path, ["compute"], max_depth=2, reverse=True)
    assert rev["stats"]["reverse"] is True
    assert any(c["name"] == "main_entry" for c in rev["trees"][0]["calls"])


def test_invert_call_map_unit():
    from backend.services.call_tree import _invert_call_map
    cm = {"a": ["b", "c"], "b": ["c"], "c": []}
    inv = _invert_call_map(cm, {"a", "b", "c"})
    assert inv["c"] == ["a", "b"]
    assert inv["b"] == ["a"]
    assert inv["a"] == []


# ── C1 회귀(리뷰 Critical): #if 0 죽은 코드가 동명 활성 함수의 ASIL/엣지를 last-wins로 덮던 결함 ──
_C_DEADCODE = """
/** @asil D */
unsigned char active_fn(void){ return live_leaf(); }
#if 0
/** @asil B */
unsigned char active_fn(void){ return stale_leaf(); }
unsigned char stale_leaf(void){ return 0; }
#endif
unsigned char live_leaf(void){ return 1; }
"""


def test_dead_code_if0_excluded_asil_and_edges(tmp_path):
    """#if 0 안의 동명 정의(@asil B)가 제외돼 활성 정의의 ASIL(D)·엣지(live_leaf)가 보존돼야 한다."""
    (tmp_path / "d.c").write_text(_C_DEADCODE, encoding="utf-8")
    payload = build_call_tree_precise(tmp_path, ["active_fn"], max_depth=2)
    node = payload["trees"][0]
    assert node.get("asil") == "D", "ASIL이 #if 0의 B로 다운그레이드되면 안 됨"
    kids = {c["name"] for c in node["calls"]}
    assert "live_leaf" in kids and "stale_leaf" not in kids, "죽은 코드 호출이 활성 엣지를 덮으면 안 됨"
    # stale_leaf는 #if 0 전용이므로 트리 어디에도 나타나면 안 됨
    all_fns = {f for t in payload["trees"] for f in _all_names(t)}
    assert "stale_leaf" not in all_fns


def test_if0_else_keeps_active_else_branch(tmp_path):
    """#if 0 … #else … #endif → then(죽음) 제외, else(활성) 유지."""
    src = """
#if 0
unsigned char f(void){ return dead(); }
#else
unsigned char f(void){ return alive(); }
#endif
unsigned char alive(void){ return 0; }
"""
    (tmp_path / "e.c").write_text(src, encoding="utf-8")
    payload = build_call_tree_precise(tmp_path, ["f"], max_depth=2)
    kids = {c["name"] for c in payload["trees"][0]["calls"]}
    assert "alive" in kids, "#else 활성 분기가 유지돼야 함"


def test_if1_else_branch_dead(tmp_path):
    """#if 1 … #else … #endif → else(죽음) 제외."""
    src = """
#if 1
unsigned char f(void){ return alive(); }
#else
unsigned char f(void){ return dead(); }
#endif
unsigned char alive(void){ return 0; }
"""
    (tmp_path / "t.c").write_text(src, encoding="utf-8")
    payload = build_call_tree_precise(tmp_path, ["f"], max_depth=2)
    kids = {c["name"] for c in payload["trees"][0]["calls"]}
    assert "alive" in kids and "dead" not in kids


def test_reverse_preserves_via_ref(tmp_path):
    """reverse 모드에서도 참조 추론 엣지가 via_ref로 표시돼야 한다(W1) — 영향분석 왜곡 방지."""
    src = """
unsigned char s_cb(void){ return 0; }
void reg(void){ register_it(s_cb); }
unsigned char register_it(unsigned char (*p)(void)){ return 0; }
"""
    (tmp_path / "v.c").write_text(src, encoding="utf-8")
    fwd = build_call_tree_precise(tmp_path, ["reg"], max_depth=2)
    fkids = {c["name"]: c for c in fwd["trees"][0]["calls"]}
    assert fkids.get("s_cb", {}).get("via_ref") is True, "정방향: 참조 엣지 via_ref"
    # 역방향: s_cb의 호출자(caller)로 reg가 오고, 그 엣지도 추론이므로 via_ref 유지
    rev = build_call_tree_precise(tmp_path, ["s_cb"], max_depth=2, reverse=True)
    rkids = {c["name"]: c for c in rev["trees"][0]["calls"]}
    assert "reg" in rkids, "역방향: s_cb의 caller는 reg"
    assert rkids["reg"].get("via_ref") is True, "역방향에서도 추론 엣지는 via_ref로 표시(W1)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
