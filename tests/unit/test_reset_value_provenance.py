# tests/unit/test_reset_value_provenance.py
"""`Reset Value` 열 — 값과 **출처**를 함께 내는 계약 (R9).

## 왜 이 파일이 있나

정본 SUDS 의 `Reset Value` 열은 뜻이 **하나가 아니다**. 같은 심볼에 두 값을 적는 곳이
465개 중 16개(칸으로는 2,191 중 **100 = 4.6%**)다:

    u8g_ApiIn_LinRx_LatchState   0x00 × 8칸 · 0x03 × 11칸
    u8g_ApiIn_LinRx_MovementReq  0x00 × 13칸 · 0x04 × 1칸

① **C 정적 저장기간**(main 진입 전 0) 과 ② **리셋 함수가 넣는 값** 이 섞여 있다.
`g_ApiIn_LinRx_ReadData_Reset()` 이 `= u8g_LATCH_UNKNOWNED`(=`0x03`) 를 대입하므로
둘 다 사실이다.

표시 없이 값만 적으면 우리도 그 모호함을 물려받는다. 특히 `0x00` 은 "주변온도 0 에서
시작한다" 처럼 **우리가 세운 적 없는 운용 주장**이 될 수 있다(실제 초기값은 `0xFF`
= 무효 표식). 그래서 근거를 함께 적는다 — `Value Range` 의 `(타입 폭)` 과 같은 결정.

## 이 파일이 지키는 것

1. 판정 순서 — 선언 → 리셋 함수 상수 → (배치 주소면 비움) → 정적 저장기간 0
2. **모르면 비운다** — 리셋 함수가 런타임 값을 넣거나 값이 갈리면 N/A
3. 출처 표시가 셀에 실린다
4. 정본 대조는 **숫자로** 한다 — `0x00`·`0`·`0x0000` 은 같은 값이고 우리 칸엔
   출처가 붙는다. 문자열로만 비교하면 지표가 거짓으로 나빠진다(SUTS R26 교훈)
"""
from __future__ import annotations

import pytest

from report_gen.c_reset import (
    RESET_SRC_DECL,
    RESET_SRC_FUNC,
    RESET_SRC_ZERO,
    SKIP_CONFLICT,
    SKIP_DECL_NONNUMERIC,
    SKIP_PLACED,
    SKIP_RUNTIME,
    as_constant,
    collect_reset_assignments,
    format_reset,
    is_reset_function,
    placed_global_names,
    resolve_reset,
)
from report_gen.function_analyzer import resolve_param_grid_entries
from report_gen.uds_reference_parity import value_verdict


def _info(**over):
    base = {
        "id": "SwUFn_0101", "name": "Adc_Init", "prototype": "void Adc_Init(void)",
        "description": "init", "asil": "B", "related": "SwTR_001",
        "inputs": [], "outputs": [], "globals_global": [], "globals_static": [],
    }
    base.update(over)
    return base


def _row(grid, name):
    for r in grid:
        if r[1] == name:
            return r
    raise AssertionError(f"{name!r} 행이 없다: {[r[1] for r in grid]}")


# --------------------------------------------------------------------------- §1 상수


class TestAsConstant:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("0x03", 3), ("3", 3), ("0x0FU", 15), ("12UL", 12),
            ("( ( U8 )( 0xFFU ) )", 255),      # 실물 매크로 본문 모양
            ("(U16)(0x1234)", 0x1234),
            ("-1", -1),
        ],
    )
    def test_numeric_forms(self, text, expected):
        assert as_constant(text) == expected

    def test_macro_is_resolved(self):
        macros = {"u8g_LATCH_UNKNOWNED": "( ( U8 )( 0x03U ) )"}
        assert as_constant("u8g_LATCH_UNKNOWNED", macros) == 3

    def test_macro_of_macro_one_hop(self):
        macros = {"A": "B", "B": "0x07"}
        assert as_constant("A", macros) == 7

    def test_parenthesised_macro_is_not_mistaken_for_a_cast(self):
        """⚠ `(A)` 는 캐스트가 아니라 **괄호 친 매크로**다.

        정규식만으로는 `(U8)x` 와 못 가른다 — 캐스트로 보고 지우면 남는 게 없어
        값이 통째로 사라진다(그러면 `Reset Value` 가 조용히 N/A 로 떨어진다).
        """
        assert as_constant("(A)", {"A": "0x07"}) == 7
        assert as_constant("( u8g_BASE )", {"u8g_BASE": "0x12"}) == 0x12
        # 음성 대조군 — 진짜 캐스트는 여전히 걷어낸다
        assert as_constant("(U8)(0x09)", {}) == 9

    @pytest.mark.parametrize("text", ["", "   ", "read_sensor()", "a + b", "SOME_UNKNOWN"])
    def test_non_constant_is_none(self, text):
        assert as_constant(text, {}) is None

    def test_macro_cycle_does_not_hang(self):
        """⚠ 순환 매크로에 빠지면 문서 생성이 통째로 멈춘다."""
        assert as_constant("A", {"A": "B", "B": "A"}) is None


class TestFormatReset:
    @pytest.mark.parametrize(
        ("value", "ctype", "expected"),
        [
            (0, "U8", "0x00"), (3, "U8", "0x03"),
            (0, "U16", "0x0000"), (0x8DC, "S16", "0x08DC"),
            (0, "U32", "0x00000000"),
            (0, "volatile U16", "0x0000"),
            (0, "en_g_DoorState", "0x00"),        # 모르는 타입은 2자리
        ],
    )
    def test_width_follows_type(self, value, ctype, expected):
        assert format_reset(value, ctype) == expected


# --------------------------------------------------------------------------- §2 함수


class TestIsResetFunction:
    @pytest.mark.parametrize("name", [
        "g_ApiIn_LinRx_ReadData_Reset", "PE_low_level_init_1", "ld_init",
        "Monitor_ADC_Init", "Reset", "init",
    ])
    def test_reset_like(self, name):
        assert is_reset_function(name)

    @pytest.mark.parametrize("name", [
        "initiate_transfer", "s_MotorSpeed", "reinitialize", "g_DoorCtrl_Main",
    ])
    def test_not_reset_like(self, name):
        """⚠ 부분 문자열로 보면 `initiate_transfer` 가 걸려 런타임 대입을 리셋으로 센다."""
        assert not is_reset_function(name)


class TestCollectResetAssignments:
    def test_only_reset_functions_are_read(self):
        bodies = {
            "g_Foo_Reset": "u8g_A = 0x01; u8g_B = 0x02;",
            "g_Foo_Main": "u8g_A = 0x99;",
        }
        got = collect_reset_assignments(bodies)
        assert [v for _f, v in got["u8g_A"]] == ["0x01"]
        assert "u8g_B" in got

    @pytest.mark.parametrize("body", [
        "u8g_A[0] = 0x01;",        # 원소 대입은 변수 전체의 리셋 값이 아니다
        "s.u8g_A = 0x01;",         # 멤버 대입
        "p->u8g_A = 0x01;",
        "*u8g_A = 0x01;",          # 포인터 역참조 — 대상이 그 변수가 아니다
        "if (u8g_A == 0x01) { ; }",
    ])
    def test_excluded_shapes(self, body):
        assert collect_reset_assignments({"g_Foo_Reset": body}).get("u8g_A") is None

    def test_compound_assignment_is_not_a_reset(self):
        assert collect_reset_assignments({"g_Foo_Reset": "u8g_A += 1;"}).get("u8g_A") is None


# --------------------------------------------------------------------------- §3 판정


class TestResolveReset:
    def test_declaration_initializer_wins(self):
        cell, src = resolve_reset({"type": "U8", "init": "0x05"},
                                  [("g_Foo_Reset", "0x09")], {})
        assert (cell, src) == (f"0x05 ({RESET_SRC_DECL})", RESET_SRC_DECL)

    def test_array_initializer_uses_first_element(self):
        cell, _src = resolve_reset({"type": "U8", "init": "{0x1D, 0x3A}"}, [], {})
        assert cell.startswith("0x1D")

    def test_reset_function_constant(self):
        cell, src = resolve_reset(
            {"type": "U8"}, [("g_X_Reset", "u8g_LATCH_UNKNOWNED")],
            {"u8g_LATCH_UNKNOWNED": "( ( U8 )( 0x03U ) )"})
        # ⚠ 상수가 아니라 **글자 그대로** 단언한다. 라벨 상수로 비교하면 라벨을
        #   지우는 변경이 시험과 함께 움직여 통과한다(뮤테이션 M12 생존).
        assert cell == "0x03 (Reset 함수)"
        assert (cell, src) == (f"0x03 ({RESET_SRC_FUNC})", RESET_SRC_FUNC)

    def test_zero_default_label_is_literal(self):
        cell, _src = resolve_reset({"type": "U8"}, [], {})
        assert cell == "0x00 (정적 저장기간)"

    def test_declaration_label_is_literal(self):
        cell, _src = resolve_reset({"type": "U8", "init": "0x05"}, [], {})
        assert cell == "0x05 (선언)"

    def test_conflicting_constants_are_left_empty(self):
        cell, src = resolve_reset({"type": "U8"},
                                  [("g_A_Reset", "0x01"), ("g_B_Reset", "0x02")], {})
        assert (cell, src) == ("", SKIP_CONFLICT)

    def test_runtime_assignment_is_left_empty(self):
        """⚠ 리셋 함수가 값을 넣는데 우리가 그 값을 모르면 `0` 은 **거짓**이다."""
        cell, src = resolve_reset({"type": "U8"}, [("g_X_Reset", "read_sensor()")], {})
        assert (cell, src) == ("", SKIP_RUNTIME)

    def test_placed_global_is_left_empty(self):
        cell, src = resolve_reset({"type": "U8"}, [], {}, placed=True)
        assert (cell, src) == ("", SKIP_PLACED)

    def test_plain_static_defaults_to_zero(self):
        cell, src = resolve_reset({"type": "U16"}, [], {})
        assert (cell, src) == (f"0x0000 ({RESET_SRC_ZERO})", RESET_SRC_ZERO)

    def test_reset_function_beats_placed(self):
        """레지스터라도 초기화 함수가 상수를 넣으면 그건 소스에 있는 근거다."""
        cell, src = resolve_reset({"type": "U8"}, [("g_X_Init", "0x02")], {}, placed=True)
        assert (cell, src) == (f"0x02 ({RESET_SRC_FUNC})", RESET_SRC_FUNC)

    def test_non_numeric_initializer_is_left_empty(self):
        cell, src = resolve_reset({"type": "U8", "init": "SOME_STRUCT_LITERAL"}, [], {})
        assert (cell, src) == ("", SKIP_DECL_NONNUMERIC)

    def test_empty_ginfo_does_not_crash(self):
        cell, src = resolve_reset(None, None, None)
        assert src == RESET_SRC_ZERO and cell.startswith("0x00")


class TestPlacedGlobalNames:
    def test_placement_syntax(self):
        text = "extern volatile ADC0STSSTR REG_ADC0STS @0x00000602;\nU8 plain;\n"
        assert list(placed_global_names(text)) == ["REG_ADC0STS"]

    def test_no_placement(self):
        assert list(placed_global_names("U8 u8g_A = 0;")) == []


# --------------------------------------------------------------------------- §4 그리드


_GIM_NEW = {
    "u8g_Flag": {"type": "U8", "range": "0 ~ 255", "init": "",
                 "reset": f"0x03 ({RESET_SRC_FUNC})", "reset_source": RESET_SRC_FUNC,
                 "desc": "flag"},
    "u8g_Unknown": {"type": "U8", "range": "", "init": "0x77",
                    "reset": "", "reset_source": SKIP_RUNTIME, "desc": ""},
    "REG_PTT": {"type": "PTTSTR", "range": "", "init": "", "reset": "",
                "reset_source": SKIP_PLACED, "desc": "Port T"},
}
_GIM_OLD = {  # `reset` 키가 아예 없던 구 payload
    "u8g_Flag": {"type": "U8", "range": "0 ~ 255", "init": "0x11", "desc": "flag"},
}


class TestGridWiring:
    def test_reset_cell_carries_provenance(self):
        grid_in, _ = resolve_param_grid_entries(
            _info(globals_global=["[IN] u8g_Flag"]), _GIM_NEW)
        assert _row(grid_in, "u8g_Flag")[4] == f"0x03 ({RESET_SRC_FUNC})"

    def test_empty_reset_does_not_fall_back_to_init(self):
        """⚠ 핵심 계약 — 판정이 "모른다" 로 끝났으면 선언 초기값으로 되돌아가면 안 된다."""
        grid_in, _ = resolve_param_grid_entries(
            _info(globals_global=["[IN] u8g_Unknown"]), _GIM_NEW)
        assert _row(grid_in, "u8g_Unknown")[4] == "N/A", "init 폴백이 살아 있다"

    def test_old_payload_without_reset_key_falls_back(self):
        """구 캐시 호환 — 키가 **아예 없을 때만** 옛 동작."""
        grid_in, _ = resolve_param_grid_entries(
            _info(globals_global=["[IN] u8g_Flag"]), _GIM_OLD)
        assert _row(grid_in, "u8g_Flag")[4] == "0x11"

    def test_member_row_reset_is_na(self):
        """멤버의 리셋 값은 소스에 없다 — 베이스 것을 물려받으면 안 된다."""
        from report_gen.source_parser import extract_struct_member_types

        smt = extract_struct_member_types(
            "typedef union { U8 Byte; struct { U8 A :1; } Bits; } PTTSTR;")
        gim = dict(_GIM_NEW)
        gim["REG_PTT"] = dict(_GIM_NEW["REG_PTT"], reset=f"0x00 ({RESET_SRC_ZERO})")
        grid_in, _ = resolve_param_grid_entries(
            _info(globals_global=["[IN] REG_PTT.Bits.A"]), gim, smt)
        assert _row(grid_in, "REG_PTT.Bits.A")[4] == "N/A"


# --------------------------------------------------------------------------- §5 대조


class TestParityComparison:
    @pytest.mark.parametrize(
        ("ref", "ours", "same"),
        [
            ("0x03", f"0x03 ({RESET_SRC_FUNC})", True),
            ("0", "0x00 (정적 저장기간)", True),          # 16진↔10진 표기차
            ("0x0000", "0x00 (정적 저장기간)", True),
            ("0x00", f"0x01 ({RESET_SRC_FUNC})", False),  # ⚠ 값이 다르면 여전히 불일치
            ("0x03", "N/A", False),
        ],
    )
    def test_reset_is_compared_numerically(self, ref, ours, same):
        assert value_verdict("reset", ref, ours)[0] is same

    def test_annotation_alone_does_not_make_it_match(self):
        """⚠ 지표를 평평하게 만들지 않는다 — 괄호만 떼고 통과시키면 안 된다."""
        assert value_verdict("reset", "0x05", "(Reset 함수)")[0] is False


# --------------------------------------------------------------------------- §6 배선


class TestPayloadAndCache:
    def test_source_sections_emit_reset_and_source(self, tmp_path):
        """⚠ 함수 스코프 fixture — 이 파서를 module 스코프로 잡았다가 고부하 `-n auto`
        에서 간헐 ERROR 를 낸 전례가 있다.
        """
        from backend.services import file_resolver as fr
        from report_gen.uds_generator import generate_uds_source_sections

        (tmp_path / "m.h").write_text(
            "typedef unsigned char U8;\n"
            "#define u8g_INVALID  ( ( U8 )( 0xFFU ) )\n"
            "extern U8 u8g_Sig;\nextern U8 u8g_Plain;\n"
            "extern volatile U8 REG_PTT @0x00000258;\n", encoding="utf-8")
        (tmp_path / "m.c").write_text(
            '#include "m.h"\n'
            "U8 u8g_Sig;\nU8 u8g_Plain;\n"
            "void g_Sig_Reset(void) { u8g_Sig = u8g_INVALID; }\n"
            "void g_Sig_Main(void) { u8g_Plain = u8g_Sig; REG_PTT = u8g_Sig; }\n",
            encoding="utf-8")
        saved = fr._resolver
        fr._resolver = fr.LocalFileResolver()
        try:
            payload = generate_uds_source_sections(str(tmp_path), preprocess=False)
        finally:
            # ⚠ 원래 값 **복원** — 특정 값으로 고정하면 다음 테스트가 물려받는다.
            fr._resolver = saved

        gmap = payload.get("globals_info_map") or {}
        assert gmap["u8g_Sig"]["reset"] == f"0xFF ({RESET_SRC_FUNC})", gmap["u8g_Sig"]
        assert gmap["u8g_Sig"]["reset_source"] == RESET_SRC_FUNC
        # 리셋 함수가 안 건드리는 전역은 C 보장으로 0
        assert gmap["u8g_Plain"]["reset"] == f"0x00 ({RESET_SRC_ZERO})"
        # ⚠ 배치 주소(`@0x…`)로 선언된 레지스터는 **비운다** — 리셋 값이
        #   MCU 데이터시트에 있고 소스엔 없다. `0x00` 을 적으면 거짓이다.
        assert gmap["REG_PTT"]["reset"] == "", gmap["REG_PTT"]
        assert gmap["REG_PTT"]["reset_source"] == SKIP_PLACED

    def test_cache_version_was_bumped(self):
        """키를 새로 넣고 버전을 안 올리면 구 캐시가 히트해 판정이 안 돈다(v12 전례)."""
        from backend.helpers.uds import _SOURCE_SECTIONS_SCHEMA_VERSION as ver

        assert int(str(ver).lstrip("v")) >= 15, f"캐시 버전이 v15 미만이다: {ver}"
