"""문서 초안 원재료(타입 해상도·컬럼 골격) — 순수 함수 검증.

이 파일의 존재 이유 1순위는 **`uint8_t` 기본값 환각 차단**이다.
`generators.suts.infer_variable_type`은 미상 타입을 조용히 `uint8_t`로 떨어뜨리는데,
영향도 초안이 그걸 그대로 쓰면 실측 U16 변수(`g_sys_error_his`)에 `MAX=0xFF`라는
없는 경계값을 제안하게 된다. `resolve_var_type`은 미상이면 반드시 `None`이어야 한다.
"""
from __future__ import annotations

import pytest

# ─── base_var — 배열 첨자 분리(표시는 보존, 조회만 base) ────────────────────────

@pytest.mark.parametrize(("raw", "expect"), [
    ("g_sys_error_his[0]", ("g_sys_error_his", "[0]")),
    ("g_sys_error_his[4]", ("g_sys_error_his", "[4]")),
    ("matrix[1][2]", ("matrix", "[1][2]")),
    ("u16t_Data", ("u16t_Data", "")),
    ("  spaced[3]  ", ("spaced", "[3]")),
    ("", ("", "")),
    (None, ("", "")),
])
def test_base_var_splits_subscript(raw, expect):
    from workflow.impact_doc_draft import base_var

    assert base_var(raw) == expect


# ─── resolve_var_type — 미상은 None(환각 차단) ──────────────────────────────────

def test_resolve_var_type_unknown_returns_none_not_uint8():
    """이름 규칙에도 globals 맵에도 없으면 **None**.

    ⚠ 회귀 가드: `generators.suts.infer_variable_type`은 같은 입력에 'uint8_t'를 준다.
    그 기본값이 초안 경로로 새면 U16 변수에 MAX=0xFF를 제안하는 환각이 된다."""
    from generators.suts import infer_variable_type
    from workflow.impact_doc_draft import resolve_var_type

    name = "g_sys_error_his"
    assert infer_variable_type(name, {}) == "uint8_t"   # 생성기 경로는 기본값(문서생성용, 정상)
    assert resolve_var_type(name, {}) is None           # 초안 경로는 미상 = None


def test_resolve_var_type_globals_map_wins_over_name_pattern():
    """globals_info_map 실측이 이름 규칙보다 우선 — source 라벨로 근거를 밝힌다."""
    from workflow.impact_doc_draft import resolve_var_type

    # 이름은 u8 패턴('u8g_')인데 실측은 U32 → 실측 채택
    got = resolve_var_type("u8g_Counter", {"u8g_Counter": "U32"})
    assert got == {"type": "uint32_t", "source": "globals_map"}

    got2 = resolve_var_type("u16t_Data", {})
    assert got2 == {"type": "uint16_t", "source": "name_pattern"}


def test_resolve_var_type_uses_base_for_array_elements():
    """`g_arr[3]`의 타입은 base(`g_arr`)로 조회한다 — 원소마다 맵에 있을 리 없다."""
    from workflow.impact_doc_draft import resolve_var_type

    assert resolve_var_type("g_arr[3]", {"g_arr": "U16"}) == {"type": "uint16_t", "source": "globals_map"}
    # 첨자 포함 원문 키가 맵에 있으면 그것도 인정
    assert resolve_var_type("g_arr[3]", {"g_arr[3]": "U8"}) == {"type": "uint8_t", "source": "globals_map"}


def test_resolve_var_type_ignores_process_global_cache(monkeypatch):
    """전역 `_globals_type_cache`를 읽지 않는다(동시 문서생성 오염 차단)."""
    import generators.suts as gsuts
    from workflow.impact_doc_draft import resolve_var_type

    monkeypatch.setitem(gsuts._globals_type_cache, "g_sys_error_his", "U16")
    assert resolve_var_type("g_sys_error_his", {}) is None      # 전역은 무시
    assert resolve_var_type("g_sys_error_his", None) is None    # None 주입도 전역 폴백 아님


@pytest.mark.parametrize("bad", ["", None, "   "])
def test_resolve_var_type_blank_is_none(bad):
    from workflow.impact_doc_draft import resolve_var_type

    assert resolve_var_type(bad, {"x": "U8"}) is None


# ─── build_var_types — base로 접고, 미상은 키 부재 ─────────────────────────────

def test_build_var_types_folds_array_elements_and_omits_unknown():
    from workflow.impact_doc_draft import build_var_types

    names = [f"g_sys_error_his[{i}]" for i in range(5)] + ["u16t_Data", "SomeEnum_Mode"]
    got = build_var_types(names, {"g_sys_error_his": "U16"})

    assert got["g_sys_error_his"] == {"type": "uint16_t", "source": "globals_map"}  # 5원소 → 1키
    assert got["u16t_Data"]["type"] == "uint16_t"
    assert "SomeEnum_Mode" not in got, "미상은 키 자체를 넣지 않는다(숫자 제안 금지)"
    assert len(got) == 2


def test_build_var_types_respects_cap():
    from workflow.impact_doc_draft import build_var_types

    names = [f"u16_v{i}" for i in range(500)]
    assert len(build_var_types(names, {}, cap=10)) <= 10


def test_build_var_types_empty_input():
    from workflow.impact_doc_draft import build_var_types

    assert build_var_types(None) == {}
    assert build_var_types([]) == {}


# ─── collect_var_names — 문서 컬럼이 권위, 열 순서 보존 ────────────────────────

def test_collect_var_names_prefers_document_columns_and_keeps_order():
    """시트 헤더 원문이 먼저, 순서 보존. 행 키는 보완용으로 뒤에 붙는다."""
    from workflow.impact_doc_draft import collect_var_names

    cols = {"inputs": ["g_a[0]", "g_a[1]"], "expected": ["ret"]}
    rows = [{"inputs": {"g_a[0]": "0x0", "extra_only_in_row": "1"}, "expected": {"ret": "0x0"}}]

    assert collect_var_names(rows, cols) == ["g_a[0]", "g_a[1]", "ret", "extra_only_in_row"]


def test_collect_var_names_dedups_and_survives_malformed_rows():
    from workflow.impact_doc_draft import collect_var_names

    rows = ["not-a-dict", None, {"inputs": {"x": "1"}}, {"inputs": {"x": "2"}}]
    assert collect_var_names(rows, None) == ["x"]
    assert collect_var_names(None, None) == []


# ─── canonical_* — 라벨은 생성기 상수에서, TSV용으로 개행 제거 ─────────────────

def test_canonical_suts_columns_come_from_generator_constant():
    from generators.suts import _FIXED_HEADERS
    from workflow.impact_doc_draft import canonical_suts_columns

    got = canonical_suts_columns()
    assert got["fixed"][0] == "Component"       # 열 순서(2번 컬럼부터)
    assert got["fixed"][1] == "TC ID"
    assert got["related"] == "SUDS"
    assert len(got["fixed"]) == len(_FIXED_HEADERS)
    assert all("\n" not in h for h in got["fixed"]), "TSV 셀에 개행이 들어가면 행이 깨진다"
    assert "Safety Related" in got["fixed"]      # 개행 → 공백으로 편 것


def test_canonical_sits_columns_come_from_generator_constant():
    from workflow.impact_doc_draft import canonical_sits_columns

    got = canonical_sits_columns()
    assert got["fixed"] == ["TC ID", "Description", "Call Chain",
                            "Test Case Generation Method", "Precondition"]
    assert got["related"] == "SwDS"


def test_canonical_columns_do_not_hardcode_sheet_name():
    """시트명은 템플릿별로 다르다 — 문서 메타(loc.sheet)에서만 온다(하드코딩 금지)."""
    from workflow.impact_doc_draft import canonical_sits_columns, canonical_suts_columns

    assert canonical_suts_columns()["sheet"] == ""
    assert canonical_sits_columns()["sheet"] == ""


# ─── parse_annotated_types — UDS `[IN] U16 var` 어노테이션 (cloudium 주 근거) ──

def test_parse_annotated_types_extracts_type_and_name():
    from workflow.impact_doc_draft import parse_annotated_types

    got = parse_annotated_types([
        "[IN] U16 g_sys_error_his",
        "[OUT] U8 u8_Result",
        "[INDIRECT] S32 s32_Offset",
        "BOOL g_Flag",              # 태그 없이도 인정
    ])
    assert got == {
        "g_sys_error_his": "uint16_t",
        "u8_Result": "uint8_t",
        "s32_Offset": "int32_t",
        "g_Flag": "bool",
    }


def test_parse_annotated_types_drops_unattributable_entries():
    """타입은 있는데 변수명이 없으면 버린다 — 오귀속이 환각보다 낫지 않다."""
    from workflow.impact_doc_draft import parse_annotated_types

    assert parse_annotated_types(["[OUT] return U8 (range: 0 ~ 255)"]) == {}
    assert parse_annotated_types(["g_no_type_token"]) == {}      # 타입 없음
    assert parse_annotated_types([None, "", "   "]) == {}


def test_annotation_beats_name_pattern_but_loses_to_globals_map():
    """근거 강도 순서: globals_map > doc_annotation > name_pattern."""
    from workflow.impact_doc_draft import resolve_var_type

    annots = {"u8_Legacy": "uint32_t"}   # 이름은 u8인데 문서는 U32라고 말한다
    assert resolve_var_type("u8_Legacy", {}, annot_types=annots) == {
        "type": "uint32_t", "source": "doc_annotation"}
    # 소스 실측이 있으면 그게 이긴다
    assert resolve_var_type("u8_Legacy", {"u8_Legacy": "U16"}, annot_types=annots) == {
        "type": "uint16_t", "source": "globals_map"}
    # 어노테이션 없으면 이름 규칙
    assert resolve_var_type("u8_Legacy", {})["source"] == "name_pattern"


def test_build_var_types_joins_array_columns_to_annotation():
    """문서 컬럼은 첨자 포함(`g_x[0]`), 어노테이션은 base(`g_x`) — base로 조인된다."""
    from workflow.impact_doc_draft import build_var_types

    cols = ["g_sys_error_his[%d]" % i for i in range(5)]
    got = build_var_types(cols, {}, annotated=["[IN] U16 g_sys_error_his"])
    assert got == {"g_sys_error_his": {"type": "uint16_t", "source": "doc_annotation"}}
