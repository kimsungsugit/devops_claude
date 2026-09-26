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
    _clean_global_name,
    _decl_dims_from_array_field,
    _expand_array_entries,
    _observed_idx_map,
    _struct_member_dims,
    collect_unit_functions,
)
from report_gen.source_parser import extract_struct_member_arrays


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


class TestParallelListStaysInStep:
    """부속 리스트를 함께 펼치는 축 — 안 쓰면 **짝이 조용히 어긋난다**.

    SITS 는 이름과 원문을 인덱스로 짝짓는다(`expected_raws[ev_idx]`). 이름만 늘어나면
    원소마다 **다른 변수의** 타입·경계값이 붙는데, 값이 틀리는 게 아니라 짝이 밀리는
    것이라 산출물만 봐서는 안 보인다.
    """

    def test_parallel_is_duplicated_per_element(self):
        out, info = _expand_array_entries(
            ["a", "b"], {"a": (3,)}, 96, parallel=["RAW_A", "RAW_B"])
        assert out == ["a[0]", "a[1]", "a[2]", "b"]
        assert info["parallel"] == ["RAW_A", "RAW_A", "RAW_A", "RAW_B"]

    def test_parallel_follows_the_budget_skip(self):
        """안 펼친 이름은 부속도 한 칸이다 — 여기가 어긋나면 뒤가 전부 밀린다."""
        out, info = _expand_array_entries(
            ["big", "keep"], {"big": (60,)}, 10, parallel=["R1", "R2"])
        assert out == ["big", "keep"]
        assert info["parallel"] == ["R1", "R2"]

    def test_parallel_length_always_matches_out(self):
        out, info = _expand_array_entries(
            ["x", "a", "y"], {"a": (2,)}, 96, parallel=["RX", "RA", "RY"])
        assert len(info["parallel"]) == len(out)
        assert info["parallel"] == ["RX", "RA", "RA", "RY"]

    def test_mismatched_length_is_refused_not_trimmed(self):
        """길이가 다르면 짝이 이미 깨진 것이다 — 잘라 맞추면 그 사실이 사라진다."""
        import pytest

        with pytest.raises(ValueError, match="parallel"):
            _expand_array_entries(["a", "b"], {}, 96, parallel=["only_one"])

    def test_without_parallel_nothing_changes(self):
        """기존 호출부(SUTS)는 영향이 없어야 한다."""
        out, info = _expand_array_entries(["a"], {"a": (2,)}, 96)
        assert out == ["a[0]", "a[1]"]
        assert info["parallel"] is None


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


class TestStructMemberArrays:
    r"""구조체 멤버 배열 — 정본은 `DiagData.CloseFailure[0..2]` 로 적는다.

    ## 왜 (KJPDS02_PV 실측, 2026-08-18)

    이 저장소는 struct **본문을 한 번도 읽지 않았다**(`type_defs` 는 주석 표 섹션이라
    멤버 차원이 없다). 그래서 멤버 배열이 base 한 칸으로 나갔다:

        s_LinFrame.LIN_data   정본 8원소  ←  우리 ['s_LinFrame.LIN_data']
        DiagData.CloseFailure 정본 3원소  ←  우리 ['DiagData.CloseFailure']

    첨자가 붙는 자리가 **둘**이라는 게 이 축의 핵심이다:

        멤버가 배열      PS.Data              → PS.Data[0..7]        (꼬리)
        root 가 배열     g_Ph.u8_MaxCount     → g_Ph[0..3].u8_MaxCount (root 뒤)

    꼬리/​root 를 바꿔 붙이면 `g_Ph.u8_MaxCount[0]` 이라는 **없는 대상**이 된다.

    실측(오프라인 시뮬): 일치 +136 · 과다 **-12** · 사라진 맞춤 0.

    ## ⚠ 파라미터 타입까지 열지 않는다

    포인터 파라미터(`SHA256_CTX *ctx`)의 타입을 프로토타입에서 끌어오면 닿는 칸이
    늘지만 실측 **일치 +34 에 과다 +176** 이었다 — `SHA256_CTX.buffer[64]` 를 통째로
    펼치는 게 원인이고 정본이 지지하지 않는다.
    """

    _SM = {"st_s_DTC": {"CloseFailure": "[3]"}, "ProgramStruct": {"Add.ByteArray": "[4]"}}
    _GI = {"DiagData": {"array": "", "type": "st_s_DTC"},
           "PS": {"array": "", "type": "ProgramStruct"}}

    def test_member_dims_via_root_type(self):
        got = _array_sizes(["[IN] DiagData.CloseFailure"],
                           globals_info=self._GI, struct_members=self._SM)
        assert got == {"DiagData.CloseFailure": (3,)}

    def test_nested_union_member_path(self):
        """중첩 union 은 `Add.ByteArray` 경로로 잡힌다."""
        got = _array_sizes(["[OUT] PS.Add.ByteArray"],
                           globals_info=self._GI, struct_members=self._SM)
        assert got == {"PS.Add.ByteArray": (4,)}

    def test_const_qualifier_on_root_type_is_stripped(self):
        got = _array_sizes(["[IN] DiagData.CloseFailure"],
                           globals_info={"DiagData": {"array": "", "type": "const st_s_DTC"}},
                           struct_members=self._SM)
        assert got == {"DiagData.CloseFailure": (3,)}

    def test_unknown_type_or_member_is_not_guessed(self):
        """음성 대조군 — 타입도 멤버도 모르면 **아무것도 만들지 않는다**."""
        assert _array_sizes(["[IN] Foo.bar"], globals_info={}, struct_members=self._SM) == {}
        assert _array_sizes(["[IN] DiagData.NoSuch"],
                            globals_info=self._GI, struct_members=self._SM) == {}

    def test_pointer_param_root_is_not_resolved(self):
        """⚠ root 에 이미 첨자가 있으면(포인터 표기) 이 경로를 타지 않는다."""
        assert _struct_member_dims("ctx[0].state", self._GI, self._SM) == ()

    def test_root_array_puts_index_after_root_not_tail(self):
        out, info = _expand_array_entries(
            ["g_Ph.u8_Max"], {}, 96, root_sizes={"g_Ph": (4,)}
        )
        assert out == [f"g_Ph[{i}].u8_Max" for i in range(4)]
        assert info["expanded"] == ["g_Ph.u8_Max"]

    def test_member_size_wins_over_root_size(self):
        """멤버 자신이 배열이면 꼬리에 붙는다 — root 배열보다 우선."""
        out, _ = _expand_array_entries(
            ["PS.Data"], {"PS.Data": (2,)}, 96, root_sizes={"PS": (3,)}
        )
        assert out == ["PS.Data[0]", "PS.Data[1]"]

    def test_root_expansion_respects_budget(self):
        """예산이 모자라면 root 확장도 **자르지 않고 안 펼친다**."""
        out, info = _expand_array_entries(
            ["a.m", "keep"], {}, 4, root_sizes={"a": (8,)}
        )
        assert out == ["a.m", "keep"] and info["skipped"][0]["name"] == "a.m"

    def test_wired_end_to_end(self):
        """⚠ 배선 테스트 — 헬퍼만 보면 호출부가 값을 버리는 걸 못 본다."""
        units = collect_unit_functions(
            _unit("Fn", gg=["[IN] DiagData.CloseFailure"]),
            self._GI, sds_map={}, struct_members=self._SM,
        )
        assert units[0]["input_vars"] == [f"DiagData.CloseFailure[{i}]" for i in range(3)]

    def test_wired_root_array_end_to_end(self):
        units = collect_unit_functions(
            _unit("Fn", gg=["[IN] g_Ph.u8_Max"]),
            {"g_Ph": {"array": "[4]", "type": "SlipDetectPhase_t"}}, sds_map={},
        )
        assert units[0]["input_vars"] == [f"g_Ph[{i}].u8_Max" for i in range(4)]

    def test_no_struct_map_changes_nothing(self):
        """음성 대조군 — 맵이 없으면 이전과 동일하게 base 한 칸."""
        units = collect_unit_functions(
            _unit("Fn", gg=["[IN] DiagData.CloseFailure"]), self._GI, sds_map={},
        )
        assert units[0]["input_vars"] == ["DiagData.CloseFailure"]


class TestStructExpansionGuards:
    r"""위 클래스의 뮤테이션 생존 3건을 메운다 — 전부 **테스트 공백**이었다.

    ⚠ `test_pointer_param_root_is_not_resolved` 는 **공허했다**: `ctx` 의 타입이
      애초에 맵에 없어 가드를 지워도 `()` 가 나왔다. 가드가 실제로 막는지 보려면
      **타입이 풀리는데도 첨자 때문에 막히는** 경우를 써야 한다.
    """

    _SM = {"SHA256_CTX": {"state": "[8]"}, "T": {"Data": "[2]"}}

    def test_subscripted_root_does_not_resolve_but_bare_root_does(self):
        """`ctx[0].state`(포인터 표기)는 안 걸리고 `ctx.state` 는 걸린다.

        ⚠ 이 동작을 **따로 가드로 막지 않는다** — `globals_info` 키가 맨 이름이라
          `ctx[0]` 조회가 이미 실패한다. 겹쳐 막으면 뮤테이션이 통째로 살아남는다
          (5차 라운드에서 같은 판단으로 죽은 게이트를 뺐다). 여기서는 가드가 아니라
          **관측되는 결과**를 고정한다.
        """
        gi = {"ctx": {"array": "", "type": "SHA256_CTX"}}
        assert _struct_member_dims("ctx[0].state", gi, self._SM) == ()
        assert _struct_member_dims("ctx.state", gi, self._SM) == (8,)

    def test_root_expansion_leaves_already_subscripted_root_alone(self):
        out, info = _expand_array_entries(
            ["ctx[0].state"], {}, 96, root_sizes={"ctx": (4,)}
        )
        assert out == ["ctx[0].state"] and not info["expanded"]

    def test_nested_block_members_do_not_leak_to_top_level(self):
        """N8 — 중첩 블록 멤버가 최상위 이름으로 새면 없는 경로가 생긴다.

        `ByteArray` 는 `Add.ByteArray` 로만 닿아야 한다. 최상위로 새면
        `PS.ByteArray` 라는 존재하지 않는 이름이 문서에 실린다.

        ⚠ 중첩 블록의 **두 번째** 배열 멤버라야 샌다. `;` 로 끊으면 첫 멤버가 든
          조각엔 여는 중괄호가 같이 붙어 정규식이 어차피 실패하기 때문이다 —
          한 개짜리로 쓴 초판은 제거 로직을 지워도 통과해 **공허**했다.
        """
        src = """
        typedef struct
        {
            UINT8 Data[8];
            union
            {
                UINT8   ByteArray[4];
                UINT8   Spare[2];
                UINT32  DWord;
            } Add;
        } ProgramStruct;
        """
        got = extract_struct_member_arrays(src)["ProgramStruct"]
        assert got.get("Data") == "[8]"
        assert got.get("Add.ByteArray") == "[4]"
        assert got.get("Add.Spare") == "[2]"
        assert "ByteArray" not in got and "Spare" not in got, f"중첩 멤버가 샜다: {got}"

    def test_balanced_block_finds_outer_close_not_inner(self):
        """N9 — 중괄호 균형이 깨지면 중첩 union 을 가진 타입이 통째로 사라진다."""
        src = "typedef struct { union { int a[2]; } U; int b[3]; } Outer;"
        got = extract_struct_member_arrays(src)
        assert "Outer" in got, f"중첩 union 때문에 타입을 놓쳤다: {got}"
        assert got["Outer"].get("b") == "[3]"
        assert got["Outer"].get("U.a") == "[2]"

    def test_trailing_comments_do_not_hide_members(self):
        """⚠ 라이브에서만 8칸이 조용히 사라졌던 자리다.

        멤버를 `;` 로 끊으므로 앞 멤버의 **꼬리 주석**이 다음 조각 머리에 붙는다:

            UINT8 dataIndex;    /* Current data byte index */
            UINT8 dataBuffer[8];

        조각이 `/* … */ UINT8 dataBuffer[8]` 로 시작해 앵커에 안 걸린다.
        `LIN_FRAME` 은 멤버에 주석이 없어 **우연히** 통과했고, 주석이 달린
        `LIN_INT_CTRL` 만 통째로 빠졌다 — 오프라인 시뮬(주석 제거본 사용)에서는
        안 보이고 라이브에서만 났다.
        """
        src = """
        typedef struct {
            UINT8 dataIndex;            /* Current data byte index */
            UINT8 dataBuffer[8];        /* Data buffer */
            UINT8 checksum;             // line comment
            UINT8 tail[2];
        } LIN_INT_CTRL;
        """
        got = extract_struct_member_arrays(src)["LIN_INT_CTRL"]
        assert got.get("dataBuffer") == "[8]", f"주석이 멤버를 가렸다: {got}"
        assert got.get("tail") == "[2]", f"줄 주석이 멤버를 가렸다: {got}"

    def test_comment_inside_dimension_is_not_mistaken_for_size(self):
        """음성 대조군 — 주석 안 숫자를 크기로 줍지 않는다."""
        got = extract_struct_member_arrays(
            "typedef struct { /* 99 */ UINT8 b[3]; } C;"
        )
        assert got["C"].get("b") == "[3]"

    def test_pointer_member_is_not_treated_as_array(self):
        """음성 대조군 — `UINT8 *p[4]` 는 원소 수가 아니라 포인터 개수다."""
        got = extract_struct_member_arrays("typedef struct { UINT8 *p[4]; UINT8 q[5]; } P;")
        assert got["P"].get("q") == "[5]"
        assert "p" not in got["P"], f"포인터 멤버가 배열로 잡혔다: {got['P']}"


class TestObservedIndexExpansion:
    """선언 크기가 없는 **포인터 버퍼**를 본문 관찰 첨자로 펼치는 경로 (R21).

    ## 왜 (KJPDS02_PV 정본 실측, 2026-08-19)

    정본은 포인터 버퍼도 원소 단위로 적는데(`pu8t_ResponseBuffer[0..39]` 40칸),
    포인터는 원소 수가 **선언에 없다** — 호출자만 안다. 본문이 실제로 만진 첨자만이
    근거이고, 파서는 그걸 이미 `(idx: …)` 로 싣고 있었다(소비처가 안 썼을 뿐).

    ## 방향 태그로 **열이 갈린다** — 손실 0 조합 탐색 실측

        [IN]  → 입력 열   적중 28 · 과다  1
        [OUT] → 기대 열   적중 53 · 과다  0
        둘 다             적중 81 · 과다  1 · **사라진 맞춤 0**
        [OUT] 를 양쪽에   적중 63 · 과다 43 · 사라진 맞춤 1   ← 대조군

    라이브 적용 결과: 입력 5,432 → **5,459** · 기대 4,927 → **4,980** · 과다 +1 ·
    사라진 맞춤 **0**(집합 비교).

    ⚠ `[INOUT]` 은 넣지 않는다 — 적중이 **한 칸도 안 늘고**(81 그대로) 과다만 는다.
    ⚠ 선언 크기가 잡히면 그쪽이 이긴다. R10 이 관찰 첨자를 기각한 게 바로 그 경우라
      (일치 146 → 10 폭락) 순서가 곧 정책이다.
    """

    # ── 맵 생산 ────────────────────────────────────────────────────────────
    def test_literal_indexes_are_collected_for_matching_tag(self):
        got = _observed_idx_map([["[IN] const UINT8 * version (idx: 0, 1, 3, 2)"]], {"IN"})
        assert got == {"version": (0, 1, 2, 3)}

    def test_other_direction_tag_is_not_collected(self):
        """방향이 곧 열이다 — `[OUT]` 을 입력 맵에 넣으면 대조군(과다 43)이 된다."""
        raw = [["[OUT] U8 * pu8t_Resp (idx: 0, 1)"]]
        assert _observed_idx_map(raw, {"IN"}) == {}
        assert _observed_idx_map(raw, {"OUT"}) == {"pu8t_Resp": (0, 1)}

    @pytest.mark.parametrize("tag", ["INOUT", "INDIRECT", "INDIRECT2"])
    def test_inout_and_indirect_are_excluded(self, tag):
        """⚠ `"[IN]" in "[INOUT] x"` 류의 substring 실패를 이 저장소가 4번 겪었다."""
        raw = [[f"[{tag}] U8 * buf (idx: 0, 1, 2)"]]
        assert _observed_idx_map(raw, {"IN"}) == {}
        assert _observed_idx_map(raw, {"OUT"}) == {}

    def test_variable_index_drops_the_whole_slot(self):
        """리터럴만 골라 쓰면 폭이 임의로 좁아져 **없는 사실**을 적게 된다."""
        assert _observed_idx_map(
            [["[IN] U8 * buf (idx: 0, 1, u8t_Idx)"]], {"IN"}
        ) == {}

    @pytest.mark.parametrize("expr", ["7*8", "3 * 8", "0x10", "3abc"])
    def test_arithmetic_index_is_not_a_literal(self, expr):
        """⚠ 정규식 앵커(`$`)가 없으면 `7*8` 이 리터럴로 통과하고 `int()` 가 **터진다**.

        `7*8` 은 가정이 아니다 — 정본 SUTS 가 `lin_tl_rx_queue.tl_pdu[7*8]` 로 41칸
        적고 있고, 같은 표기가 본문 첨자로도 온다. 크래시는 조용하지 않지만
        파이프라인 전체를 세운다.
        """
        assert _observed_idx_map([[f"[IN] U8 * buf (idx: 0, {expr})"]], {"IN"}) == {}

    def test_declared_size_wins_over_observation(self):
        """`(size:)` 가 같이 붙으면 관찰은 버린다 — R10 이 기각한 경우다."""
        assert _observed_idx_map(
            [["[IN] u8s_Buf (size: 8) (idx: 0, 1)"]], {"IN"}
        ) == {}

    def test_single_index_is_not_an_expansion(self):
        assert _observed_idx_map([["[IN] U8 * buf (idx: 3)"]], {"IN"}) == {}

    def test_widest_slot_wins_when_name_repeats(self):
        """좁은 쪽을 채택하면 정본이 적는 원소를 빠뜨린다(under-testing)."""
        got = _observed_idx_map(
            [["[IN] U8 * buf (idx: 0, 1)"], ["[IN] U8 * buf (idx: 0, 1, 2, 3)"]], {"IN"}
        )
        assert got == {"buf": (0, 1, 2, 3)}

    # ── 확장 ───────────────────────────────────────────────────────────────
    def test_expand_uses_observed_indexes_verbatim(self):
        """정본 첨자는 **불연속일 수 있다**(`pu8t_ResponseBuffer` 는 0..39 중 관찰분).

        `_elem_suffixes` 처럼 `0..n-1` 을 만들면 관찰하지 않은 칸을 지어내게 된다.
        """
        out, stats = _expand_array_entries(
            ["buf"], {}, 96, observed_idx={"buf": (2, 5, 9)}
        )
        assert out == ["buf[2]", "buf[5]", "buf[9]"]
        assert stats["observed"] == ["buf"]

    def test_declared_dims_take_priority_over_observed(self):
        out, stats = _expand_array_entries(
            ["buf"], {"buf": (3,)}, 96, observed_idx={"buf": (7, 8)}
        )
        assert out == ["buf[0]", "buf[1]", "buf[2]"]
        assert stats["observed"] == [], "선언이 있는데 관찰로 펼쳤다 — R10 재발"

    def test_observed_expansion_respects_the_budget(self):
        """예산을 넘기면 펼치지 않는다 — 잘라 넣으면 뒤 변수가 사라진다."""
        out, stats = _expand_array_entries(
            ["buf"], {}, 4, observed_idx={"buf": tuple(range(10))}
        )
        assert out == ["buf"]
        assert stats["skipped"] and stats["skipped"][0]["elements"] == 10
        assert stats["observed"] == []

    def test_observed_is_reported_separately_from_declared(self):
        """합쳐 세면 "선언 크기로 펼쳤다" 로 읽혀 근거가 부풀려진다."""
        _, stats = _expand_array_entries(
            ["a", "b"], {"a": (2,)}, 96, observed_idx={"b": (0, 1)}
        )
        assert stats["expanded"] == ["a", "b"]
        assert stats["observed"] == ["b"]

    # ── 호출부 배선 (헬퍼 단독 테스트는 값 폐기를 못 본다) ────────────────
    def test_wired_in_input_column_for_in_tag(self):
        u = collect_unit_functions(
            _unit(inputs=["[IN] const UINT8 * version (idx: 0, 1, 3, 2)"],
                  proto="void Fn(const UINT8 *version)"),
            sds_map={},
        )[0]
        assert u["input_vars"] == ["version[0]", "version[1]", "version[2]", "version[3]"]

    def test_wired_in_expected_column_for_out_tag(self):
        u = collect_unit_functions(
            _unit(outputs=["[OUT] U16 * Values (idx: 1, 0, 2)"],
                  proto="void Fn(U16 *Values)"),
            sds_map={},
        )[0]
        assert u["output_vars"] == ["Values[0]", "Values[1]", "Values[2]"]

    def test_out_tag_does_not_expand_the_input_column(self):
        """정본은 `[OUT]` 버퍼를 **입력 열엔 base 한 칸**으로 적는다.

        양쪽에 적용하면 `sf_ReadAppVersion::versionOut` 의 맞춤이 사라진다
        (대조군 실측: 적중 63 · 과다 43 · **사라진 맞춤 1**).

        ⚠ 이름이 **입력 열에도 실려 있어야** 이 축이 재어진다. 기대 열에만 두면
          입력 열은 애초에 그 이름을 안 내므로 잘못된 구현도 그냥 통과한다 —
          첫 판이 그랬고 뮤테이션(M12)이 살아남아 드러났다.
        """
        u = collect_unit_functions(
            _unit(inputs=["[IN] U8 * versionOut"],
                  outputs=["[OUT] U8 * versionOut (idx: 0, 1, 2, 3)"],
                  proto="void Fn(U8 *versionOut)"),
            sds_map={},
        )[0]
        assert u["input_vars"] == ["versionOut"], \
            f"입력 열이 관찰 첨자로 펼쳐졌다: {u['input_vars']}"
        assert u["output_vars"] == [f"versionOut[{i}]" for i in range(4)]

    def test_inout_tag_is_not_wired_to_either_column(self):
        """`[INOUT]` 은 적중을 **한 칸도 안 늘리고**(81 그대로) 과다만 늘린다.

        ⚠ 헬퍼 단독 테스트는 호출부가 어떤 태그 집합을 넘기는지 못 본다 —
          `{"OUT"}` 을 `{"OUT", "INOUT"}` 으로 바꾸는 뮤테이션(M15)이 살아남았다.
        """
        u = collect_unit_functions(
            _unit(inputs=["[INOUT] U8 * shared (idx: 0, 1, 2)"],
                  outputs=["[INOUT] U8 * shared (idx: 0, 1, 2)"],
                  proto="void Fn(U8 *shared)"),
            sds_map={},
        )[0]
        assert u["input_vars"] == ["shared"], f"입력: {u['input_vars']}"
        assert u["output_vars"] == ["shared"], f"기대: {u['output_vars']}"

    def test_plain_pointer_without_observation_is_untouched(self):
        """음성 대조군 — 관찰 첨자가 없으면 base 한 칸 그대로다(크기를 지어내지 않는다)."""
        u = collect_unit_functions(
            _unit(inputs=["[IN] U8 * raw"], proto="void Fn(U8 *raw)"), sds_map={}
        )[0]
        assert u["input_vars"] == ["raw"]
