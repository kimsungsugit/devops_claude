"""배열을 **원소 단위로** 펼쳐 정본과 같은 입도로 맞추는 경로.

## 왜 (KJPDS02_PV 정본 실측, 2026-08-12)

정본 SUTS 는 배열을 원소마다 한 칸씩 적는다.

    입력 Inpt: 엔트리 6,014 중 `name[N]` **3,023 (50.3%)**
    기대 ExpR: 엔트리 5,389 중 `name[N]` **2,716 (50.4%)**
    base 134 중 **모든 unit 에서 같은 개수** 120 · 최대 원소 60
    입력 unit당 최대 **96 = 열 상한 정확히**(초과 0) · 기대 최대 **84 = 상한**

우리는 그 자리에 base 이름 한 칸만 냈다 — 결손이 아니라 **입도 차이**다:

    s_sha256_accumulate_state::au32_State   정본 8원소  ← 우리 ['au32_State']
    g_DrvIn_Main_Reset::u16s_AdcBuffer      정본 9원소  ← 우리 ['u16s_AdcBuffer']

(unit, base) 쌍 282 중 **181(64.2%)** 은 이미 이름을 잡고 있었다. 크기만 있으면 맞는다.

## 예산 정책

정본은 입력 96 · 기대 84 둘 다 **최대가 상한과 정확히 일치**한다(초과 0) — 즉 정본
자신이 열 수에 묶여 있다. 우리도 넘길 수 없으므로, 넘칠 배열은 **펼치지 않고 base
이름을 그대로 둔다**. 원소를 잘라 넣으면 두 가지가 동시에 망가진다:

  1. "이 배열은 앞 k칸만 시험한다"는 **없는 사실**을 문서에 적게 된다
  2. 뒤에 오는 **다른 변수**가 통째로 밀려나 사라진다

변수는 하나도 잃지 않고 입도만 낮추는 쪽이 정직하다. 건너뛴 것은
`array_expansion.skipped` 로 보고하고 로그는 WARNING 으로 올린다.
"""
from __future__ import annotations

import pytest

from generators.suts import (
    _array_sizes,
    _decl_dims_from_array_field,
    _clean_global_name,
    _expand_array_entries,
    collect_unit_functions,
)


def _unit(name="Fn", *, inputs=None, outputs=None, gg=None, gs=None, proto="void Fn(void)"):
    return {
        "a": {
            "id": "SwUFn_0101",
            "name": name,
            "prototype": proto,
            "inputs": list(inputs or []),
            "outputs": list(outputs or []),
            "globals_global": list(gg or []),
            "globals_static": list(gs or []),
            "logic_flow": [],
        }
    }


class TestArraySizes:
    def test_size_tail_is_read(self):
        assert _array_sizes(["[IN] u16s_AdcBuffer (size: 9)"]) == {"u16s_AdcBuffer": (9,)}

    def test_param_declaration_dim_is_read(self):
        """파라미터 표시엔 차원이 `buf[8]` 로 이미 들어 있다 — 이 필드에선 늘 선언 크기다."""
        assert _array_sizes(["[IN] U8 buf[8]"]) == {"buf": (8,)}

    def test_size_survives_other_tails(self):
        got = _array_sizes(["[IN] u8s_Buf (size: 4) (idx: i) (range: 0x0 ~ 0xFF)"])
        assert got == {"u8s_Buf": (4,)}

    @pytest.mark.parametrize("raw", ["[IN] g_Plain", "[IN] u8s_Buf (size: 1)", "[IN] u8s_Buf (size: 0)"])
    def test_non_arrays_and_single_element_are_ignored(self, raw):
        """크기 1 을 펼치면 `x[0]` 이 되어 정본의 평범한 이름과 어긋난다."""
        assert _array_sizes([raw]) == {}

    def test_indirect_tags_are_stripped(self):
        assert _array_sizes(["[INDIRECT2] u8s_Buf (size: 3)"]) == {"u8s_Buf": (3,)}


class TestExpansion:
    def test_elements_are_zero_based_and_contiguous(self):
        out, info = _expand_array_entries(["a"], {"a": (3,)}, 96)
        assert out == ["a[0]", "a[1]", "a[2]"]
        assert info["expanded"] == ["a"] and info["skipped"] == []

    def test_non_array_names_pass_through(self):
        out, _ = _expand_array_entries(["x", "y"], {}, 96)
        assert out == ["x", "y"]

    def test_order_is_preserved(self):
        out, _ = _expand_array_entries(["x", "a", "y"], {"a": (2,)}, 96)
        assert out == ["x", "a[0]", "a[1]", "y"]

    def test_budget_overflow_keeps_the_base_name(self):
        """⚠ 예산이 모자라면 **자르지 않고 안 펼친다** — 변수를 잃지 않는다."""
        out, info = _expand_array_entries(["big"], {"big": (60,)}, 10)
        assert out == ["big"]
        assert info["skipped"] == [{"name": "big", "elements": 60, "remaining": 10}]

    def test_later_variables_are_not_crowded_out(self):
        """확장이 뒤 변수를 밀어내면 그 변수가 캡에서 잘려 **통째로 사라진다**."""
        out, info = _expand_array_entries(["big", "keep_me"], {"big": (8,)}, 8)
        assert "keep_me" in out, f"뒤 변수가 밀려났다: {out}"
        assert info["skipped"] and info["skipped"][0]["name"] == "big"

    def test_expansion_uses_the_budget_when_it_fits_exactly(self):
        out, info = _expand_array_entries(["a"], {"a": (4,)}, 4)
        assert out == ["a[0]", "a[1]", "a[2]", "a[3]"] and not info["skipped"]


class TestEndToEnd:
    def test_global_array_becomes_elements(self):
        u = collect_unit_functions(_unit(gg=["[IN] u16s_AdcBuffer (size: 9)"]), sds_map={})[0]
        assert u["input_vars"] == [f"u16s_AdcBuffer[{i}]" for i in range(9)]

    def test_param_array_becomes_elements(self):
        u = collect_unit_functions(
            _unit(inputs=["[IN] U8 buf[8]"], proto="void Fn(U8 buf[8])"), sds_map={}
        )[0]
        assert u["input_vars"] == [f"buf[{i}]" for i in range(8)]

    def test_expected_column_expands_too(self):
        """⚠ 한쪽만 펼치면 같은 행에서 같은 변수가 다른 이름으로 두 번 나온다.

        실측: 같은 unit 의 입력·기대 **양쪽에** 펼쳐진 배열이 120건이다.
        """
        u = collect_unit_functions(_unit(gg=["[OUT] u8s_Log (size: 3)"]), sds_map={})[0]
        assert u["output_vars"][:3] == ["u8s_Log[0]", "u8s_Log[1]", "u8s_Log[2]"]

    def test_plain_globals_are_untouched(self):
        """확장이 평범한 전역을 건드리면 회귀다."""
        u = collect_unit_functions(_unit(gg=["[IN] g_MotorState"]), sds_map={})[0]
        assert "g_MotorState" in u["input_vars"]

    def test_skip_is_reported_not_silent(self):
        """예산 부족으로 못 펼친 것은 산출물이 **말해야** 한다.

        조용하면 "정본과 입도가 다르다"의 원인을 짚을 수 없다.
        """
        u = collect_unit_functions(_unit(gg=["[IN] huge (size: 200)"]), sds_map={})[0]
        assert u["input_vars"] == ["huge"]
        skipped = u["array_expansion"]["input"]["skipped"]
        assert skipped and skipped[0]["name"] == "huge" and skipped[0]["elements"] == 200

    def test_never_exceeds_the_column_budget(self):
        """96열을 넘기면 뒤가 캡에서 잘려 변수가 사라진다."""
        gg = [f"[IN] arr{i} (size: 30)" for i in range(5)]
        u = collect_unit_functions(_unit(gg=gg), sds_map={})[0]
        assert len(u["input_vars"]) <= 96
        # 다섯 배열의 base 이름이 하나도 사라지지 않아야 한다
        roots = {v.split("[")[0] for v in u["input_vars"]}
        assert {f"arr{i}" for i in range(5)} <= roots


_SRC_C = """
typedef struct { U8 f; } S_T;
static U8 u8s_DataBuffer[8];
static S_T s_Buf[4];
static U8 u8s_Unk[UNKNOWN_MAX];
static U8 u8s_Sized[MAX_LEN];
static U8 u8s_Plain;
static const U8 u8s_ConstLut[4] = { 0U, 1U, 2U, 3U };
static U16 u16s_Grid[3][MAX_ROW];
static U8 u8s_Cube[2][2][2];
void g_ArrayUser( void )
{
    U8 u8t_i;
    u8t_i = u8s_DataBuffer[2];
    s_Buf->f = u8t_i;
    u8t_i = u8s_Unk[0];
    u8t_i = u8s_Sized[1];
    u8t_i = u8s_ConstLut[1];
    u8s_Plain = u8t_i;
    return;
}
void g_MultiDimUser( U8 au8_Pair[2][3] )
{
    U16 u16t_v;
    u16t_v = u16s_Grid[1][2];
    u8t_i = u8s_Cube[0][0][0];
    au8_Pair[0][0] = ( U8 )u16t_v;
    return;
}
typedef struct { U8 CCIF; U8 ACCERR; } S_BITS_T;
typedef struct { S_BITS_T Bits; U8 Byte; } S_REG_T;
typedef struct { U16 u16_Addr; U8 u8_Data; } S_MSG_T;
static S_REG_T s_Reg;
void g_PtrUser( S_MSG_T* pst_Msg, U8 u8t_Scalar )
{
    U8 u8t_i;
    u8t_i = s_Reg.Bits.CCIF;
    u8t_i = pst_Msg->u8_Data;
    pst_Msg->u16_Addr = ( U16 )u8t_Scalar;
    return;
}
"""
_SRC_H = "#define MAX_LEN 6\n#define MAX_ROW 4\n"


@pytest.fixture(scope="module")
def array_project(tmp_path_factory):
    """**생산자 경로**(실제 파싱)를 지나는 종단 픽스처.

    ⚠ 소비처(`collect_unit_functions`)만 문자열로 테스트하면 생산자
      (`uds_generator` → `_format_param_entry`)의 결함이 통째로 생존한다 —
      실제로 뮤테이션 3건이 그렇게 살아남았다.

    ⚠ **resolver 를 직접 local 로 고정한다.** conftest 의 `_default_local_resolver`
      는 함수 스코프 autouse 라, **모듈 스코프 픽스처는 그보다 먼저 만들어진다**
      (pytest 는 session→module→function 순으로 셋업한다). 그래서 이 픽스처는
      머신의 영속 설정(`config/file_mode.json` = cloudium)을 그대로 타고,
      Cloudium worker 로 파일을 읽으러 간다 — xdist 로 18개 워커가 동시에
      두드리면 그 IPC 가 간헐적으로 실패해 픽스처가 ERROR 로 죽는다
      (전량 실행에서만, 단독으론 통과 = 재현이 어렵다).
    """
    from backend.services import file_resolver as fr
    from report_gen.uds_generator import generate_uds_source_sections

    d = tmp_path_factory.mktemp("array_src")
    (d / "cfg.h").write_text(_SRC_H, encoding="utf-8")
    (d / "m.c").write_text(_SRC_C, encoding="utf-8")
    _saved = fr._resolver
    fr._resolver = fr.LocalFileResolver()
    try:
        return generate_uds_source_sections(str(d), preprocess=False)
    finally:
        # ⚠ 원래 값 **복원**. 특정 값으로 고정하고 가면 다음 테스트가 그 값을 물려받는다
        #   (`file_resolver._resolver` 누설로 단독 16건이 깨졌던 전례 — 커밋 584833e).
        fr._resolver = _saved


def _globals_of(project, fn_name="g_ArrayUser"):
    for info in (project.get("function_details") or {}).values():
        if isinstance(info, dict) and info.get("name") == fn_name:
            return list(info.get("globals_global") or []) + list(info.get("globals_static") or [])
    pytest.fail(f"{fn_name} 를 파싱하지 못했다 — 이 테스트의 전제가 깨졌다")


class TestProducerEmitsSize:
    def test_declared_array_carries_its_size(self, array_project):
        """전역 표시에 `(size: N)` 이 실려야 소비처가 펼칠 수 있다."""
        entry = next(g for g in _globals_of(array_project) if "u8s_DataBuffer" in g)
        assert "(size: 8)" in entry, entry

    def test_member_path_does_not_carry_a_size(self, array_project):
        """⚠ `s_Buf->f` 는 배열이 아니라 그 배열 한 칸의 **필드**다.

        여기 크기를 붙이면 소비처가 `s_Buf->f[0..3]` 이라는 없는 이름을 만든다.
        """
        members = [g for g in _globals_of(array_project) if "->" in g or "." in g.split("] ")[-1]]
        for g in members:
            assert "(size:" not in g, f"멤버 경로에 크기가 붙었다: {g}"

    def test_unresolved_macro_size_is_not_emitted(self, array_project):
        """`[UNKNOWN_MAX]` 는 개수를 **모르는** 것이다 — 실으면 크기처럼 보이는 문자열만 남는다."""
        entry = next((g for g in _globals_of(array_project) if "u8s_Unk" in g), "")
        assert entry and "(size:" not in entry, entry

    def test_macro_size_is_resolved_to_a_number(self, array_project):
        """`[MAX_LEN]` 은 매크로가 접히므로 숫자로 실려야 한다."""
        entry = next((g for g in _globals_of(array_project) if "u8s_Sized" in g), "")
        assert "(size: 6)" in entry, entry

    def test_non_array_global_has_no_size(self, array_project):
        entry = next((g for g in _globals_of(array_project) if "u8s_Plain" in g), "")
        assert entry and "(size:" not in entry, entry


# ---------------------------------------------------------------------------
# 다차원 배열 — 크기가 없는 게 아니라 **변수 자체가 사라졌다**
#
# 정본 실측(KJPDS02_PV): 입력 엔트리의 첨자 깊이 분포 {0: 2748, 1: 3138, 2: 128}.
# 깊이 2 인 128 칸이 통째로 빠져 있었고(입력 71 · 기대 71 원소), 그 원인은 소비처가
# 아니라 **선언자 정규식**이었다 — `(?:\[[^\]]*\])?` 가 첨자를 하나만 허용해
# `static U16 u16s_MovgAvgFltBuff[R][C];` 가 파서 산출 어디에도 없었다.
# ---------------------------------------------------------------------------
class TestMultiDimDeclarationSurvives:
    """⚠ 가장 날카로운 앵커: 고치기 전엔 이 선언이 **빈 리스트**를 냈다."""

    @pytest.mark.parametrize(
        "stmt, name, dim",
        [
            ("static U16 u16s_Grid[3][4];", "u16s_Grid", "[3][4]"),
            ("S16 s16g_Tbl[5][7][7];", "s16g_Tbl", "[5][7][7]"),
            ("static U16 b[R][C];", "b", "[R][C]"),
            ("static U8 u8s_Flat[60];", "u8s_Flat", "[60]"),
            ("U8 u8s_Open[];", "u8s_Open", "[]"),
            ("U8 u8s_Plain;", "u8s_Plain", ""),
        ],
    )
    def test_declarator_keeps_name_and_every_dimension(self, stmt, name, dim):
        from report_gen.source_parser import _parse_c_declaration_statement

        got = _parse_c_declaration_statement(stmt)
        assert got, f"선언이 통째로 사라졌다: {stmt}"
        assert got[0]["name"] == name and got[0]["array"] == dim, got


class TestMultiDimParams:
    """파라미터도 같은 결함이었다 — 이름이 **타입 쪽으로 넘어가** 식별 불가였다."""

    @pytest.mark.parametrize(
        "param, name",
        [
            ("S16 t[3][4]", "t"),
            ("const U8 data[]", "data"),          # 빈 첨자도 이름을 삼켰다
            ("U8 buf[8]", "buf"),                 # 회귀 가드(1차원)
            ("const U8 *p", "p"),
        ],
    )
    def test_name_is_recovered(self, param, name):
        from report_gen.function_analyzer import _split_param

        assert _split_param(param)[1] == name, _split_param(param)

    def test_display_keeps_every_dimension(self):
        """`t[3] [4]` 처럼 갈라지면 그건 이름이 아니라 문자열 쓰레기다."""
        from report_gen.function_analyzer import _format_param_entry, _split_param

        t, n, a = _split_param("S16 t[3][4]")
        assert _format_param_entry(n, t, a, [], {}, False) == "S16 t[3][4]"

    def test_macro_dimensions_are_folded_one_by_one(self):
        from report_gen.function_analyzer import _format_param_entry, _split_param

        mm = {"ROWS": "5", "COLS": "7"}
        t, n, a = _split_param("S16 t[ROWS][COLS]")
        assert _format_param_entry(n, t, a, [], mm, False) == "S16 t[5][7]"


class TestMultiDimSizeTail:
    def test_dimensions_are_carried_separately_not_multiplied(self):
        """`9x8` 로 실어야 소비처가 `[i][j]` 를 만든다. 72 로 접으면 복원 불가다."""
        from report_gen.function_analyzer import _format_param_entry

        mm = {"R": "9", "C": "8"}
        assert _format_param_entry("g", "", "", [], mm, False, size_hint="[R][C]") == "g (size: 9x8)"

    def test_three_dimensions(self):
        from report_gen.function_analyzer import _format_param_entry

        assert _format_param_entry("g", "", "", [], {}, False, size_hint="[5][7][7]") == "g (size: 5x7x7)"

    def test_one_unresolved_dimension_suppresses_the_whole_size(self):
        """한 축이라도 모르면 원소 개수를 모르는 것이다 — 반쪽 크기는 거짓이다."""
        from report_gen.function_analyzer import _format_param_entry

        got = _format_param_entry("g", "", "", [], {"R": "9"}, False, size_hint="[R][UNKNOWN]")
        assert "(size:" not in got, got

    @pytest.mark.parametrize(
        "raw, want",
        [
            ("[IN] g (size: 9x8)", {"g": (9, 8)}),
            ("[IN] g (size: 5x7x7)", {"g": (5, 7, 7)}),
            ("[IN] U8 t[3][4]", {"t": (3, 4)}),
            ("[IN] g (size: 1x1)", {}),           # 원소 1개는 펼치지 않는다
        ],
    )
    def test_sizes_are_parsed_as_dimension_tuples(self, raw, want):
        assert _array_sizes([raw]) == want


class TestMultiDimExpansion:
    def test_row_major_order_matches_the_reference(self):
        out, info = _expand_array_entries(["a"], {"a": (2, 3)}, 96)
        assert out == ["a[0][0]", "a[0][1]", "a[0][2]", "a[1][0]", "a[1][1]", "a[1][2]"]
        assert info["expanded"] == ["a"]

    def test_budget_counts_the_product_not_the_first_dimension(self):
        """`[5][7][7]` 은 5칸이 아니라 **245칸**이다 — 5로 세면 캡을 넘겨 뒤가 사라진다."""
        out, info = _expand_array_entries(["tbl", "keep_me"], {"tbl": (5, 7, 7)}, 96)
        assert out == ["tbl", "keep_me"]
        assert info["skipped"] and info["skipped"][0]["elements"] == 245

    def test_reserve_uses_the_actual_position_not_the_first_match(self):
        """같은 **배열 이름**이 두 번 오면 `list.index` 가 첫 위치를 돌려줘 예약분을 과다 계산한다.

        ⚠ 중복이 배열 **자신**이어야 결함이 드러난다 — 다른 이름이 중복이면
          `list.index(nm)` 와 실제 위치가 같아 가드가 헛돈다(뮤테이션 생존).
          자리가 남는데도 안 펼치는 **조용한 과소 산출**이다.
        """
        out, info = _expand_array_entries(["a", "b", "a"], {"a": (3,)}, 8)
        assert out == ["a[0]", "a[1]", "a[2]", "b", "a[0]", "a[1]", "a[2]"], out
        assert not info["skipped"], info["skipped"]

    def test_end_to_end_two_dimensions(self):
        u = collect_unit_functions(_unit(gg=["[IN] u16s_Grid (size: 3x2)"]), sds_map={})[0]
        assert u["input_vars"] == [f"u16s_Grid[{i}][{j}]" for i in range(3) for j in range(2)]


# ---------------------------------------------------------------------------
# MISRA 캐스트 상수 — 다차원 fix 를 **무효화하던** 진짜 차단 지점
#
# KJPDS02 실측: 배열 차원에 쓰인 매크로 13종이 **전부** 캐스트+접미사 형태였다.
#   ( ( U8 )( 9U ) ) · ( U8 )32U · (5U) · 2U · (REQ_DOWNLOAD_BLOCK_SIZE + 10u)
# `_safe_eval_int` 의 문자 화이트리스트가 `U`·`L` 을 불허해 전부 안 접혔다 →
# 배열 크기가 없는 것과 같아 확장이 조용히 건너뛰어졌다.
# ---------------------------------------------------------------------------
class TestMisraConstantFolding:
    @pytest.mark.parametrize(
        "value, want",
        [
            ("( ( U8 )( 9U ) )", 9),      # u8s_FIT_MAX_BUFFER
            ("( ( U8 )( 16U ) )", 16),    # MAXHISNO
            ("( U8 )32U", 32),            # SHA256_DIGEST_SIZE
            ("(5U)", 5),                  # TEMP_LUT_SIZE
            ("2U", 2),                    # PWM_CHANNEL_COUNT
            ("( ( U8 )( 7 ) )", 7),       # SCAN_COUNT (접미사 없음)
            ("0x1FU", 31),
            ("10u + 6", 16),
        ],
    )
    def test_cast_and_suffix_constants_fold(self, value, want):
        from report_gen.function_analyzer import _safe_eval_int

        assert _safe_eval_int(value) == want

    @pytest.mark.parametrize("value", ["(UNKNOWN) + 3", "(A)", "UNKNOWN", "(SIZE) * 2", "SZ"])
    def test_unknown_symbols_are_never_invented(self, value):
        """⚠ `(UNKNOWN) + 3` 의 괄호까지 벗기면 `+ 3` 이 **3** 으로 평가된다.

        모르는 크기를 숫자로 바꾸면 문서에 없는 사실이 박힌다 — None 이어야 한다.
        """
        from report_gen.function_analyzer import _safe_eval_int

        assert _safe_eval_int(value) is None

    def test_nested_macro_values_are_resolved(self):
        """`#define A (B + 10u)` — 값 안에 또 매크로가 있으면 한 번만 돌아선 못 접는다."""
        from report_gen.function_analyzer import _format_param_entry

        mm = {"LINTP_DATA_LEN_MAX": "(REQ_BLK + 10u)", "REQ_BLK": "( ( U16 )( 512U ) )"}
        got = _format_param_entry("g", "", "", [], mm, False, size_hint="[LINTP_DATA_LEN_MAX]")
        assert got == "g (size: 522)", got

    def test_self_referential_macro_terminates(self):
        """`#define A A` 로 무한 치환에 빠지면 안 된다(상한이 있어야 한다)."""
        from report_gen.function_analyzer import _subst_macros

        assert _subst_macros("A", {"A": "A"}) == "A"

    def test_only_identifiers_present_in_the_expression_are_substituted(self):
        """맵 전체를 도는 대신 식에 **나타난** 이름만 본다(KJPDS02 는 매크로 5,622개)."""
        from report_gen.function_analyzer import _subst_macros

        assert _subst_macros("ROWS", {"ROWS": "3", "UNRELATED": "9"}) == "3"

    def test_real_two_dim_macro_pair_folds(self):
        """정본이 72원소로 적는 `u16s_MovgAvgFltBuff[9][8]` 의 실제 매크로 쌍."""
        from report_gen.function_analyzer import _format_param_entry

        mm = {"u8s_FIT_MAX_BUFFER": "( ( U8 )( 9U ) )", "u8g_LIB_FLT_MAX_CNT": "( ( U8 )( 8U ) )"}
        got = _format_param_entry(
            "u16s_MovgAvgFltBuff", "", "", [], mm, False,
            size_hint="[u8s_FIT_MAX_BUFFER][u8g_LIB_FLT_MAX_CNT]",
        )
        assert got == "u16s_MovgAvgFltBuff (size: 9x8)", got


# ---------------------------------------------------------------------------
# 반환값 슬롯 — 우리는 그 자리에 **타입 이름**을 냈다
#
# 정본(KJPDS02_PV) 기대열 5,389 엔트리 중 `return` 290 · `return[0]` 7.
# 우리는 287칸에 `U8`(144) `U16`(62) `S16`(32) `l_u8`(19) … 을 냈다 — 변수가 아니다.
# 생산자 5곳의 `[OUT] return <타입>` 계약은 다른 소비처(impact_doc_draft·sits·backend
# helpers)가 타입을 읽으므로 **그대로 두고**, SUTS 소비처에서만 이름을 교정한다.
# ---------------------------------------------------------------------------
class TestReturnSlot:
    @pytest.mark.parametrize(
        "raw",
        [
            "[OUT] return U8",
            "[OUT] return U16 (range: 0 ~ 65535)",
            "[OUT] return l_u8",
            "[OUT] return const U8 *",
            "return S16",
        ],
    )
    def test_return_slot_becomes_the_word_return(self, raw):
        from generators.suts import _extract_var_names

        assert _extract_var_names([raw]) == ["return"], _extract_var_names([raw])

    def test_type_name_is_never_emitted_as_a_variable(self):
        from generators.suts import _extract_var_names

        got = _extract_var_names(["[OUT] return U8", "[OUT] return U16"])
        assert got == ["return"], got

    def test_ordinary_params_are_untouched(self):
        """회귀 가드 — `return` 으로 시작하지 않는 것은 예전 그대로 이름을 뽑는다."""
        from generators.suts import _extract_var_names

        assert _extract_var_names(["[IN] U8 u8g_Speed", "[OUT] S16 *ps16_Out"]) == [
            "u8g_Speed", "ps16_Out",
        ]

    @pytest.mark.parametrize("raw", ["[OUT] returnValue", "[OUT] return_code", "[IN] returnCnt"])
    def test_a_name_starting_with_return_is_not_swallowed(self, raw):
        """⚠ `^return\\b` 의 **단어 경계**가 본체다.

        경계가 없으면 `returnValue` 가 통째로 `return` 이 된다. 타입 토큰이 앞에
        붙은 형태(`U8 returnValue`)는 애초에 `^return` 에 안 걸려 가드가 헛돈다 —
        **맨 이름**으로 시험해야 결함이 드러난다(뮤테이션 생존).
        """
        from generators.suts import _extract_var_names

        want = raw.split("] ", 1)[1]
        assert _extract_var_names([raw]) == [want], _extract_var_names([raw])

    def test_end_to_end_non_void_unit_reports_return(self):
        u = collect_unit_functions(
            _unit(outputs=["[OUT] return U16"], proto="U16 Fn(void)"), sds_map={}
        )[0]
        assert u["output_vars"] == ["return"], u["output_vars"]

    def test_fallback_uses_the_same_name(self):
        """출력이 하나도 없을 때의 폴백도 `return_<함수명>` 이 아니라 `return` 이다."""
        u = collect_unit_functions(_unit(proto="U16 Fn(void)"), sds_map={})[0]
        assert u["output_vars"] == ["return"], u["output_vars"]

    def test_void_unit_gets_no_return(self):
        u = collect_unit_functions(_unit(proto="void Fn(void)"), sds_map={})[0]
        assert "return" not in u["output_vars"]


# ---------------------------------------------------------------------------
# const 전역 — 시험 입력으로 **설정할 수 없고** 기대결과로 **변하지도 않는다**
#
# 실측(KJPDS02_PV 정본 1,005 unit): 정본은 const 전역을 입력 0칸 · 기대 0칸 —
# 어느 입도로도 한 번도 적지 않는다. 우리는 419칸(입력 160 · 기대 259)을 냈고
# 일치는 0 이었다. 배열이면 원소 확장이 그 노이즈를 배로 불린다
# (`au32_Sha256RoundConstants[0..63]` = 64칸).
# ---------------------------------------------------------------------------
class TestConstGlobalSuppression:
    @pytest.mark.parametrize(
        "gim, want",
        [
            ({"g": {"type": "const U32"}}, True),
            ({"g": {"type": "const S16"}}, True),
            ({"g": {"type": "CONST U8"}}, True),
            ({"g": {"type": "U32"}}, False),
            ({"g": {"type": "constant_t"}}, False),   # 단어 경계 — 타입 이름의 일부
            ({"g": {}}, False),
            ({}, False),
            (None, False),
        ],
    )
    def test_const_detection(self, gim, want):
        from generators.suts import _is_const_global

        assert _is_const_global("g", gim) is want

    def test_const_global_is_not_listed_at_all(self):
        """base 한 칸도 내지 않는다 — 정본이 어느 입도로도 안 적기 때문이다."""
        u = collect_unit_functions(
            _unit(gg=["[IN] au32_Rounds (size: 4)", "[IN] u8g_Speed"]),
            {"au32_Rounds": {"type": "const U32", "array": "[4]"}},
            sds_map={},
        )[0]
        assert "u8g_Speed" in u["input_vars"]
        assert not any("au32_Rounds" in v for v in u["input_vars"]), u["input_vars"]
        assert not any("au32_Rounds" in v for v in u["output_vars"]), u["output_vars"]

    def test_const_suppression_also_covers_the_expected_column(self):
        u = collect_unit_functions(
            _unit(gg=["[OUT] s16s_Lut (size: 3)"]),
            {"s16s_Lut": {"type": "const S16", "array": "[3]"}},
            sds_map={},
        )[0]
        assert not any("s16s_Lut" in v for v in u["output_vars"]), u["output_vars"]

    def test_non_const_global_is_untouched(self):
        """회귀 가드 — 억제가 넓으면 지금 맞고 있는 4,832칸을 함께 지운다."""
        u = collect_unit_functions(
            _unit(gg=["[IN] u16s_AdcBuffer (size: 3)"]),
            {"u16s_AdcBuffer": {"type": "U16", "array": "[3]"}},
            sds_map={},
        )[0]
        assert u["input_vars"] == ["u16s_AdcBuffer[0]", "u16s_AdcBuffer[1]", "u16s_AdcBuffer[2]"]

    def test_const_parameter_is_still_an_input(self):
        """⚠ 파라미터의 `const` 는 **가리키는 곳**이 읽기 전용일 뿐이다.

        그 버퍼는 시험이 채워 넣어야 하는 입력이라 억제 대상이 아니다.
        """
        u = collect_unit_functions(
            _unit(inputs=["[IN] const U8 *pu8t_Src"], proto="void Fn(const U8 *pu8t_Src)"),
            {"pu8t_Src": {"type": "const U8 *"}},
            sds_map={},
        )[0]
        assert "pu8t_Src" in u["input_vars"], u["input_vars"]

    def test_without_globals_info_map_nothing_is_suppressed(self):
        """근거가 없으면 억제하지 않는다 — 요약 로그가 그 사실을 명시한다."""
        u = collect_unit_functions(_unit(gg=["[IN] au32_Rounds (size: 4)"]), sds_map={})[0]
        assert any("au32_Rounds" in v for v in u["input_vars"]), u["input_vars"]

    def test_const_qualifier_survives_the_type_merge(self, array_project):
        """⚠ 생산자 경로 앵커 — tree-sitter 산출 타입엔 `const` 가 **없다**.

        그게 텍스트 스캔 값을 덮어써서 `static const UDSFuncEntry_t s_UdsFuncTbl[…]`
        이 그냥 `UDSFuncEntry_t` 로 남았다. const 가 사라지면 위 억제가 통째로
        헛돈다 — 소비처만 테스트하면 이 결함이 생존한다.
        """
        from report_gen.source_parser import is_const_type

        gim = array_project.get("globals_info_map") or {}
        entry = gim.get("u8s_ConstLut") or {}
        assert entry, f"const 전역이 globals_info_map 에 없다: {sorted(gim)[:12]}"
        assert is_const_type(entry.get("type")), entry

    def test_const_global_is_absent_from_the_generated_unit(self, array_project):
        """종단 — 실제 파싱을 지나 소비처까지 갔을 때 그 이름이 없어야 한다."""
        units = collect_unit_functions(
            array_project.get("function_details") or {},
            array_project.get("globals_info_map") or {},
            sds_map={},
        )
        u = next(x for x in units if x["name"] == "g_ArrayUser")
        assert not any("u8s_ConstLut" in v for v in u["input_vars"] + u["output_vars"]), u


class TestMultiDimProducer:
    def test_multi_dim_global_is_not_lost(self, array_project):
        """⚠ 회귀 앵커 — 고치기 전엔 이 전역이 산출물 **어디에도** 없었다."""
        entries = _globals_of(array_project, "g_MultiDimUser")
        assert any("u16s_Grid" in g for g in entries), entries

    def test_multi_dim_global_carries_both_dimensions(self, array_project):
        entry = next(g for g in _globals_of(array_project, "g_MultiDimUser") if "u16s_Grid" in g)
        assert "(size: 3x4)" in entry, entry

    def test_three_dim_global_carries_all_three(self, array_project):
        entry = next(g for g in _globals_of(array_project, "g_MultiDimUser") if "u8s_Cube" in g)
        assert "(size: 2x2x2)" in entry, entry


# ---------------------------------------------------------------------------
# 포인터 표기 — 정본(VectorCAST)은 `p[0]` · `p[0].m`, 우리는 `p` · `p->m` 이었다
#
# 실측(KJPDS02_PV, 2026-08-13): 화살표 표기만 맞춰도 입력 163칸 · 기대 124칸이
# 과다 → 일치로 옮겨간다. hit+over 합이 before/after 동일 = **순수 이름 바꾸기**이고
# 잃은 일치는 0 이다.
#
# ⚠ **맨이름 규칙(`p` → `p[0]`)은 일부러 넣지 않았다.** 정본 자신이 일관되지 않다 —
#   `Values`·`Data`·`Addr` 는 `[0]` 으로 적지만 `pst_Queue`·`pst_Params`·`pt_Raw` 는
#   맨이름으로 적는다. 규칙을 걸면 이미 맞던 이름 **78건**이 깨지고(입력 -14 순손실)
#   기대는 +62 라 이득이 손실을 못 덮는다. 근거 없는 규칙은 넣지 않는다.
# ---------------------------------------------------------------------------
class TestPointerNotation:
    @pytest.mark.parametrize(
        "raw, want",
        [
            ("p->m", "p[0].m"),
            ("pst_Params->u16_Addr1", "pst_Params[0].u16_Addr1"),
            ("p -> m", "p[0].m"),
            ("a->b->c", "a[0].b[0].c"),
            ("plain", "plain"),
            ("s.f", "s.f"),
            ("arr[3]", "arr[3]"),
            ("", ""),
        ],
    )
    def test_arrow_becomes_index_zero_dot(self, raw, want):
        from generators.suts import _vc_pointer_notation

        assert _vc_pointer_notation(raw) == want

    def test_param_member_reaches_the_unit_in_vectorcast_notation(self, array_project):
        """종단 — 파싱부터 소비처까지 지나 `pst_Msg[0].u8_Data` 로 나와야 한다."""
        units = collect_unit_functions(
            array_project.get("function_details") or {},
            array_project.get("globals_info_map") or {},
            sds_map={},
        )
        u = next(x for x in units if x["name"] == "g_PtrUser")
        assert "pst_Msg[0].u8_Data" in u["input_vars"], u["input_vars"]
        assert "pst_Msg[0].u16_Addr" in u["output_vars"], u["output_vars"]

    def test_no_arrow_survives_into_the_document(self, array_project):
        """구조 가드 — 산출물 어디에도 C 화살표가 남으면 안 된다."""
        units = collect_unit_functions(
            array_project.get("function_details") or {},
            array_project.get("globals_info_map") or {},
            sds_map={},
        )
        leaked = [(u["name"], v) for u in units
                  for v in u["input_vars"] + u["output_vars"] if "->" in v]
        assert not leaked, leaked

    def test_scalar_param_is_not_turned_into_an_element(self, array_project):
        """⚠ 음성 대조군 — 포인터가 아닌 파라미터에 `[0]` 을 붙이면 없는 배열을 지어낸다."""
        units = collect_unit_functions(
            array_project.get("function_details") or {},
            array_project.get("globals_info_map") or {},
            sds_map={},
        )
        u = next(x for x in units if x["name"] == "g_PtrUser")
        allv = u["input_vars"] + u["output_vars"]
        assert "u8t_Scalar" in allv, allv
        assert "u8t_Scalar[0]" not in allv, allv


# ---------------------------------------------------------------------------
# 멤버 접근 체인 — 한 단계만 물어 **존재하지 않는 잎**을 냈다
#
# `_FSTAT.Bits.CCIF` 가 `_FSTAT.Bits` 로 남았다. `Bits` 는 공용체 필드일 뿐 시험이
# 값을 넣는 대상이 아니라, 정본과 영영 안 맞고 진짜 이름도 그 자리에 못 온다.
# ---------------------------------------------------------------------------
class TestMemberChain:
    def test_direct_two_level_member_reaches_the_leaf(self, array_project):
        """⚠ 회귀 앵커 — 고치기 전엔 `s_Reg.Bits` 에서 멈췄다."""
        entries = _globals_of(array_project, "g_PtrUser")
        assert any("s_Reg.Bits.CCIF" in g for g in entries), entries

    def test_truncated_intermediate_is_not_emitted(self, array_project):
        """중간 마디(`s_Reg.Bits`)는 잎이 아니다 — 이름으로 내면 안 된다."""
        names = [_clean_global_name(g) for g in _globals_of(array_project, "g_PtrUser")]
        assert "s_Reg.Bits" not in names, names

    @pytest.mark.parametrize(
        "body, name, want",
        [
            ("x = _FSTAT.Bits.CCIF;", "_FSTAT", "_FSTAT.Bits.CCIF"),
            ("_PTAD.Overlap_STR.PTADLSTR.Byte = 1U;", "_PTAD", "_PTAD.Overlap_STR.PTADLSTR.Byte"),
            ("y = p -> a -> b;", "p", "p->a->b"),
            ("z = s.one;", "s", "s.one"),
        ],
    )
    def test_scan_captures_the_whole_chain(self, body, name, want):
        from report_gen.function_analyzer import _collect_var_usage

        got = _collect_var_usage(body, [name])
        assert want in got[name]["members"], got[name]["members"]

    def test_variable_subscript_does_not_become_a_name(self):
        """⚠ `arr[u8t_Idx].f` 를 이름으로 삼으면 **지역 인덱스 변수**가 문서에 실린다."""
        from report_gen.function_analyzer import _collect_var_usage

        got = _collect_var_usage("v = arr[u8t_Idx].f;", ["arr"])
        assert not any("u8t_Idx" in m for m in got["arr"]["members"]), got["arr"]["members"]


class TestGlobalSizeFallback:
    """선언 크기를 `globals_info_map` 에서도 찾는다.

    ## 왜 (KJPDS02_PV 실측, 2026-08-18)

    7차 라운드에서 입출력 **이름**을 SwUDS 문서로 대체하면서 사각이 생겼다. 문서에서
    온 이름은 대응하는 소스 엔트리가 없으니 `(size: N)` 꼬리도 없다 — 그런데 선언
    크기는 `globals_info_map` 에 이미 `array: '[60]'` 로 들어 있었고 `_array_sizes`
    는 그걸 한 번도 보지 않았다.

        s_UDS_RDBI_RealTimeMonitor::u8s_DataBuffer
            정본 60원소  ←  우리 ['u8s_DataBuffer'] 한 칸
            그 unit 의 globals_global 18개 중 DataBuffer 엔트리 **0개**
            globals_info_map['u8s_DataBuffer'] = {'array': '[60]', 'type': 'U8'}

    오프라인 시뮬 실측: 입력 일치 5,110 → **5,170**(+60) · 과다 1,056 → **1,055**(-1)
    · **사라진 맞춤 0**. 기대 축은 ±0(그 unit 이 기대 열을 쓰지 않는다).

    ## ⚠ 관찰 첨자(`(idx: ...)`)로 바꾸자는 유혹은 **재고 기각**했다

    파서는 `(idx: 4, 2, 3, 1, 0)` 로 실제 접근 첨자도 낸다. 그걸 쓰면 지어낸 칸이
    0 이지만 맞추는 칸이 폭락한다 — 정본 168쌍 기준:

        size 전량확장(현행) : 정확일치 146 · 맞춘칸 4,308 · 지어낸칸 841
        idx 관찰확장        : 정확일치  10 · 맞춘칸   454 · 지어낸칸   0

    정본은 관찰 첨자가 아니라 **선언 크기**로 적는다(base 134 중 120이 모든 unit 에서
    같은 개수). idx 는 하한일 뿐이다.
    """

    def test_array_field_is_parsed(self):
        assert _decl_dims_from_array_field("[60]") == (60,)
        assert _decl_dims_from_array_field("[5][7][7]") == (5, 7, 7)

    def test_macro_sized_array_is_rejected_not_guessed(self):
        r"""⚠ `[SIGNATURE_SIZE]` 에서 숫자만 긁으면 **없는 크기를 지어낸다**.

        `[DATA_LEN2]` 는 `re.findall(r"\d+")` 로 뽑으면 `2` 가 나온다 — 2원소
        배열이라는 거짓말이다. 대괄호 수와 숫자 차원 수가 어긋나면 전부 버린다.
        """
        assert _decl_dims_from_array_field("[SIGNATURE_SIZE]") == ()
        assert _decl_dims_from_array_field("[DATA_LEN2]") == ()
        assert _decl_dims_from_array_field("[4][MAX_LEN]") == ()
        assert _decl_dims_from_array_field("") == ()
        assert _decl_dims_from_array_field("[]") == ()

    def test_fallback_supplies_size_when_entry_has_none(self):
        got = _array_sizes(
            ["[IN] u8s_DataBuffer"],
            globals_info={"u8s_DataBuffer": {"array": "[60]", "type": "U8"}},
        )
        assert got == {"u8s_DataBuffer": (60,)}

    def test_local_entry_wins_over_global_info(self):
        """unit 지역 엔트리가 **우선**이다 — 폴백은 빈자리만 채운다."""
        got = _array_sizes(
            ["[IN] buf (size: 9x8)"],
            globals_info={"buf": {"array": "[3]", "type": "U8"}},
        )
        assert got == {"buf": (9, 8)}

    def test_non_array_global_is_not_expanded(self):
        """음성 대조군 — 스칼라 전역을 폴백이 배열로 만들면 회귀다."""
        assert _array_sizes([], globals_info={"g_State": {"array": "", "type": "U8"}}) == {}
        assert _array_sizes([], globals_info={"g_P": {"array": "[1]", "type": "U8"}}) == {}

    def test_wired_through_collect_unit_functions(self):
        """⚠ 헬퍼만 테스트하면 **호출부가 값을 버리는 것**을 못 본다.

        이 저장소가 직전 라운드에서 정확히 그렇게 뮤테이션을 놓쳤다(M10 생존).
        실제 결함 모양 그대로 — 이름은 SwUDS 에서 오고 크기는 전역맵에만 있다.
        """
        units = collect_unit_functions(
            _unit("RealTime", gg=["[IN] g_Other"]),
            {"u8s_DataBuffer": {"array": "[4]", "type": "U8"}},
            sds_map={},
            uds_io_map={"by_name": {"RealTime": {"inputs": ["u8s_DataBuffer"], "outputs": []}}},
        )
        assert units[0]["input_vars"] == [f"u8s_DataBuffer[{i}]" for i in range(4)]

    def test_wiring_negative_control(self):
        """폴백이 없어야 할 때 안 걸리는지 — 같은 경로, 크기 없는 전역."""
        units = collect_unit_functions(
            _unit("RealTime", gg=["[IN] g_Other"]),
            {"u8s_DataBuffer": {"array": "[SIGNATURE_SIZE]", "type": "U8"}},
            sds_map={},
            uds_io_map={"by_name": {"RealTime": {"inputs": ["u8s_DataBuffer"], "outputs": []}}},
        )
        assert units[0]["input_vars"] == ["u8s_DataBuffer"]
