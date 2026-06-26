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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
