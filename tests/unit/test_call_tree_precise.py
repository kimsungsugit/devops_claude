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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
