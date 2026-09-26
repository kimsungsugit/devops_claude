"""(R58 N59) 괄호 대상 `(ident)(args)` 는 파일 단위에서 호출로 단정하지 않는다.

tree-sitter 는 `(U8)(x + 1)` 캐스트를 call_expression(function=parenthesized_expression) 으로 읽는다. 옛 파서는
그 첫 identifier 를 그대로 `calls` 에 넣어 `U8`·`U16`·`byte`·`l_u8` 같은 타입 이름이 호출 목록에 섞였고
(KJPDS02_PV 파싱 1,958 항목 중 480 이 미정의 이름, 그중 177 이 타입 이름), 콜트리 precise 엔진은 known 에 없는
그 이름을 **external(unknown 라이브러리)** 로 화면·xlsx 에 실었다(라이브 externals 278쌍 중 97쌍).

계약:
- 파서는 괄호 대상을 `paren_calls` 로 따로 모으고(같은 순회) `_extract_calls` 는 넣지 않는다.
- `promote_paren_call_targets(functions)` 가 그 함수 집합에 있는 이름만 `calls` 로 승격한다(`(foo)(x)` 매크로 회피 관용구 보존).
  `parse_c_project` 가 루트 하나에 대해 부르고, 루트 여럿을 합치는 소비자(UDS·주석 커버리지)는 병합 뒤 다시 부른다 — 멱등.
- 버린 개수는 `call_filter` 로 공시하고 콜트리 stats(`paren_targets_dropped`)·xlsx 메타줄이 전달한다.
- regex 폴백(`_extract_calls_from_body_text`)은 원래 `(U8)(x)` 를 호출로 읽지 않았다 — 두 엔진이 같은 답을 낸다.
"""
from __future__ import annotations

import pytest

from backend.services import docgen_comment_coverage as dcc
from backend.services.call_tree import build_call_tree_precise
from backend.services.call_tree_xlsx import _meta_line
from workflow.code_parser import c_parser as cp

pytestmark = pytest.mark.skipif(cp._make_parser() is None, reason="tree-sitter C 파서 미가용")

_SRC = """
typedef unsigned char U8;
typedef unsigned short word;
typedef unsigned char (*pfn_t)(unsigned char);
static pfn_t g_pfn;

static U8 s_Helper(U8 a) { return a; }

U8 f(int x) {
    U8 a = (U8)(x + 1);          /* 캐스트 — 호출이 아니다 */
    word w = (word)x;            /* 괄호 없는 캐스트 — 원래도 호출이 아니었다 */
    a = (l_u8)(x);               /* 헤더에만 있는 typedef — 이 파일만 봐선 모른다 */
    a = (U8)s_Helper(a);         /* 캐스트 뒤 직접 호출 */
    a = ((U8)(x)) + (byte)(x);
    a = (s_Helper)(a);           /* 매크로 회피 관용구 — 진짜 호출 */
    a = (*s_Helper)(a);          /* 함수 지시자 역참조 — 진짜 호출 */
    a = (*g_pfn)(a);             /* 함수포인터 변수 — 대상 미해결(pointer_calls 몫) */
    a = Ext_Api(a);              /* 프로젝트 밖 함수 — external 경로는 살아 있어야 한다 */
    return a + (U8)w;
}
"""


@pytest.fixture(scope="module")
def parsed(tmp_path_factory):
    root = tmp_path_factory.mktemp("r58")
    (root / "a.c").write_text(_SRC, encoding="utf-8")
    # `g` 는 직접 호출(Direct_Fn)과 괄호 호출(Other_Fn)을 함께 가진다 — 승격이 직접 호출을 **덮어쓰지 않고 합쳐야** 한다.
    (root / "b.c").write_text(
        "unsigned char Other_Fn(unsigned char v) { return v; }\n"
        "unsigned char Direct_Fn(unsigned char v) { return v; }\n"
        "unsigned char g(unsigned char v) { return Direct_Fn(v) + (Other_Fn)(v) + (U16)(v); }\n",
        encoding="utf-8",
    )
    return root, cp.parse_c_project(str(root))


def _fn(parsed, name):
    return {f["name"]: f for f in parsed[1]["functions"]}[name]


class TestCastIsNotACall:
    def test_type_names_do_not_enter_calls(self, parsed):
        assert _fn(parsed, "f")["calls"] == ["Ext_Api", "s_Helper"]

    def test_cast_wrapped_direct_call_kept(self, parsed):
        # `(U8)s_Helper(a)` — 캐스트 뒤 직접 호출은 종전대로 호출이다(위 단언과 합쳐 '캐스트만 빠진다'를 고정).
        f = _fn(parsed, "f")
        assert "s_Helper" in f["calls"] and "U8" not in f["calls"]

    def test_pointer_variable_not_promoted(self, parsed):
        f = _fn(parsed, "f")
        assert "g_pfn" not in f["calls"]
        assert "g_pfn" in f["pointer_calls"], "간접 호출 사이트는 배지 경로에 남아야 한다"

    def test_paren_targets_stay_on_the_record(self, parsed):
        # 승격이 소비해 버리면 루트를 합친 소비자가 다시 승격할 수 없다(리뷰 W1).
        assert _fn(parsed, "f")["paren_calls"] == ["U8", "byte", "g_pfn", "l_u8", "s_Helper"]
        assert _fn(parsed, "s_Helper")["paren_calls"] == []


class TestParenthesizedRealCallsArePromoted:
    def test_same_file_function_kept(self, tmp_path):
        # `(h)(a)` 와 `(*h)(a)` — 직접 호출 없이 괄호 호출만 있어도 함수면 남는다(승격 경로 단독 고정).
        (tmp_path / "p.c").write_text(
            "static unsigned char h(unsigned char a) { return a; }\n"
            "unsigned char k(unsigned char a) { return (h)(a); }\n"
            "unsigned char m(unsigned char a) { return (*h)(a); }\n",
            encoding="utf-8",
        )
        res = cp.parse_c_project(str(tmp_path))
        fns = {f["name"]: f for f in res["functions"]}
        assert fns["k"]["calls"] == ["h"]
        assert fns["m"]["calls"] == ["h"]
        assert res["call_filter"] == {"paren_targets": 2, "paren_kept": 2, "paren_dropped": 0}

    def test_cross_file_function_kept_and_type_dropped(self, parsed):
        # 직접 호출 + 승격된 괄호 호출의 합집합 — 덮어쓰기면 Direct_Fn 이 사라진다.
        assert _fn(parsed, "g")["calls"] == ["Direct_Fn", "Other_Fn"]


def _two_roots(tmp_path):
    a = tmp_path / "APP"
    b = tmp_path / "FBL"
    a.mkdir()
    b.mkdir()
    (a / "app.c").write_text("unsigned char App_Fn(unsigned char v) { return v; }\n", encoding="utf-8")
    (b / "fbl.c").write_text(
        "unsigned char Fbl_Fn(unsigned char v) { return (App_Fn)(v) + (U8)(v); }\n", encoding="utf-8",
    )
    return a, b


class TestMultiRootRePromotion:
    """리뷰 W1 — 루트 A 의 함수를 루트 B 가 `(App_Fn)(v)` 로 부르면 루트 단위 known 으론 버려진다."""

    def test_single_root_scope_drops_cross_root_call(self, tmp_path):
        _, b = _two_roots(tmp_path)
        res = cp.parse_c_project(str(b))
        assert res["functions"][0]["calls"] == []
        assert res["call_filter"] == {"paren_targets": 2, "paren_kept": 0, "paren_dropped": 2}

    def test_merged_promotion_recovers_it_and_is_idempotent(self, tmp_path):
        a, b = _two_roots(tmp_path)
        merged = cp.parse_c_project(str(a))["functions"] + cp.parse_c_project(str(b))["functions"]
        first = cp.promote_paren_call_targets(merged)
        fns = {f["name"]: f for f in merged}
        assert fns["Fbl_Fn"]["calls"] == ["App_Fn"]
        assert first == {"paren_targets": 2, "paren_kept": 1, "paren_dropped": 1}
        assert cp.promote_paren_call_targets(merged) == first
        assert fns["Fbl_Fn"]["calls"] == ["App_Fn"]

    def test_comment_coverage_merges_roots_then_promotes(self, tmp_path):
        a, b = _two_roots(tmp_path)
        dcc.clear_cache()
        res, _meta = dcc._parse_cached(f"{a},{b}", 50)
        fns = {f["name"]: f for f in res["functions"]}
        assert fns["Fbl_Fn"]["calls"] == ["App_Fn"]
        assert res["call_filter"] == {"paren_targets": 2, "paren_kept": 1, "paren_dropped": 1}

    def test_uds_generator_merges_roots_then_promotes(self, tmp_path):
        # 생성기는 콤마 구분 복수 루트를 루트마다 파싱해 합친다 — 합친 뒤 재승격해야 FBL→APP 괄호 호출이 남는다.
        # `Fbl_Leaf()` 직접 호출을 함께 둬 "호출 0건" 폴백(파일 본문 재스캔)이 끼어들지 않게 한다.
        a, b = _two_roots(tmp_path)
        (b / "fbl.c").write_text(
            "void Fbl_Leaf(void) {}\n"
            "unsigned char Fbl_Fn(unsigned char v) { Fbl_Leaf(); return (App_Fn)(v) + (U8)(v); }\n",
            encoding="utf-8",
        )
        from report_gen.uds_generator import generate_uds_source_sections

        sections = generate_uds_source_sections(f"{a},{b}", preprocess=False, max_files=20, max_items=100)
        fbl = next(v for v in sections["function_details"].values() if v.get("name") == "Fbl_Fn")
        assert sorted(fbl["calls_list"]) == ["App_Fn", "Fbl_Leaf"]


class TestCallFilterIsDisclosed:
    def test_counts(self, parsed):
        cf = parsed[1]["call_filter"]
        # a.c f: U8, l_u8, byte, s_Helper, g_pfn (5, kept 1) · b.c g: Other_Fn, U16 (2, kept 1)
        assert cf == {"paren_targets": 7, "paren_kept": 2, "paren_dropped": 5}

    def test_missing_root_has_key(self, tmp_path):
        res = cp.parse_c_project(str(tmp_path / "nope"))
        assert res["call_filter"] == {"paren_targets": 0, "paren_kept": 0, "paren_dropped": 0}

    def test_extractor_collects_only_parenthesized_targets(self):
        parser = cp._make_parser()
        src = _SRC.encode("utf-8")
        tree = parser.parse(src)
        node = next(n for n in cp._walk(tree.root_node)
                    if n.type == "function_definition" and cp._find_ident(n.child_by_field_name("declarator")) == "f")
        assert cp._extract_paren_call_targets(node, src) == ["U8", "byte", "g_pfn", "l_u8", "s_Helper"]
        assert cp._extract_calls(node, src) == ["Ext_Api", "s_Helper"], "_extract_calls 는 괄호 대상을 더 이상 넣지 않는다"

    def test_xlsx_meta_line_shows_dropped_count(self):
        line = _meta_line({"engine": "tree-sitter", "functions": 1, "edges": 0, "paren_targets_dropped": 130}, {}, False)
        assert "괄호 대상 제외(캐스트·포인터, 전체 기준): 130" in line
        assert "괄호 대상" not in _meta_line({"engine": "tree-sitter", "functions": 1, "edges": 0}, {}, False)


class TestCallTreeExternalsNoLongerListTypes:
    def test_precise_externals_and_stats(self, parsed):
        payload = build_call_tree_precise(parsed[0], ["f"], include_external=True, max_depth=3)
        root = payload["trees"][0]
        # 캐스트는 빠지고 진짜 미지 호출은 남는다 — 빈 집합 대조가 아니라 정확한 집합(리뷰 W3).
        assert {e["name"] for e in root["externals"]} == {"Ext_Api"}
        assert {c["name"] for c in root["calls"]} == {"s_Helper"}
        assert payload["stats"]["paren_targets_dropped"] == 5

    def test_regex_fallback_never_read_casts_as_calls(self):
        assert cp._extract_calls_from_body_text("a = (U8)(x + 1); b = (byte)(x); c = real_fn(x);") == ["real_fn"]
