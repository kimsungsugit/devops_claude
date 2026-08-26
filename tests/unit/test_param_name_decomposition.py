"""이름 칸에 타입·범위·주석이 섞여 있던 것 — 제 열로 돌려보내는 가드.

## 무엇이 문제였나 (실측 2026-08-26, 정본 SUDS 대조)

정본 Name 칸 2,751개는 **단일 심볼(80.5%) · 멤버 경로(14.9%) · 첨자(3.3%)** 뿐이고
타입이나 범위를 이름 칸에 적는 일이 **한 번도 없다**. 우리 2,406칸 중 **236칸**이 그랬다
(단일 심볼 2,170 + 아래 236 = 2,406):

| 모양 | 우리 | 정본 |
|---|---:|---:|
| `u16s_AdcBuffer (size: 8)` | 100 | 0 (정본은 `u16s_AdcBuffer[8]`) |
| `return S16 (range: -32768 ~ 32767)` | 81 | 0 |
| `U8 u8t_Data` | 36 | 0 |
| `(divisor: no 0)` 꼬리 | 16 | 0 |
| `enum en_g_DoorState u8s_Data` 류 | 3 | 0 |

행에 이미 **Type · Value Range · Description 열이 있는데** 그 값을 이름 칸에 욱여넣고
있었다. 게다가 꼬리가 붙은 이름으로는 전역 정보(`globals_info_map`) 조회가 실패해
같은 행의 Type/Range/Desc 가 통째로 `N/A` 였다.

⚠ **단순 strip 금지.** `return S16 (range: …)` 에서 마지막 토큰을 취하면 `S16` 이 되어
반환값 표시가 **타입 이름으로 둔갑**한다 — 지표는 오르고 이름은 더 틀리는 모양이다.

실측 효과(payload 447함수 · 조인 346): 입력 재현율 90.2 → **96.3%** · 정밀도 85.2 → 91.0,
기대 재현율 86.5 → **90.5%** · 정밀도 88.9 → 92.9. `return` 이 타입으로 둔갑한 사례 **0건**.

⚠ 이 수치는 그리드 함수를 직접 돌린 **오프라인 측정**이라, 문서까지 쓴 뒤 재는 정본 대조
(P3 기록 83.1%/76.2%)와 **분모가 다르다**. 두 숫자를 이어 붙여 인용하지 말 것.
"""

from __future__ import annotations

import pytest

from report_gen.function_analyzer import (
    _param_grid_row,
    resolve_param_grid_entries,
    split_param_annotations,
    split_param_display,
)

_NA = "N/A"


class TestSplitAnnotations:
    def test_a_plain_name_is_untouched(self):
        assert split_param_annotations("u8g_Simple") == ("u8g_Simple", [])

    def test_a_single_tail_is_separated_not_dropped(self):
        base, tails = split_param_annotations("u16s_Buf (size: 8)")
        assert base == "u16s_Buf"
        assert ("size", "8") in tails

    def test_several_tails_are_all_separated(self):
        base, tails = split_param_annotations("u16s_Buf (size: 2) (idx: 0, 1)")
        assert base == "u16s_Buf"
        assert dict(tails) == {"size": "2", "idx": "0, 1"}

    def test_nested_parentheses_inside_a_tail(self):
        """⚠ `[^)]*\\)` 는 첫 `)` 에서 멈춘다 — 괄호를 세지 않으면 꼬리가 안 떨어지고
        마지막 토큰이 `))` 가 되어 **진짜 전역이 사라진다**(실측 2건)."""
        raw = "u8g_PartNoInfo (idx: ( ( U8 )( 2U ) ), ( ( U8 )( 8U ) ))"
        base, tails = split_param_annotations(raw)
        assert base == "u8g_PartNoInfo"
        assert dict(tails)["idx"].startswith("( ( U8 )( 2U ) )")

    def test_a_tail_in_the_middle_is_not_a_tail(self):
        """꼬리는 이름 **뒤에만** 붙는다 — 중간을 지우면 다른 이름이 된다."""
        raw = "a (size: 2) b"
        assert split_param_annotations(raw)[0] == raw

    def test_member_paths_survive(self):
        assert split_param_annotations("REG_PTT.Bits.PTT3") == ("REG_PTT.Bits.PTT3", [])


class TestSplitDisplay:
    @pytest.mark.parametrize(
        "raw,name",
        [
            ("u8g_Simple", "u8g_Simple"),
            ("DiagData.OpenFailure", "DiagData.OpenFailure"),
            ("DiagData.OpenFailure[3]", "DiagData.OpenFailure[3]"),
            # ⚠ 정본에 실재하는 모양 — 멤버 경로에 공백이 섞여 있다. 타입+이름으로
            #   오인하면 `OpenFailure` 만 남아 다른 심볼이 된다.
            ("DiagData. OpenFailure", "DiagData. OpenFailure"),
            ("REG_PTT.Bits.PTT3", "REG_PTT.Bits.PTT3"),
            ("u16s_AdcBuffer[8]", "u16s_AdcBuffer[8]"),
            ("U8", "U8"),
        ],
    )
    def test_shapes_the_reference_also_uses_are_untouched(self, raw, name):
        """⚠ 음성 대조군 — 정본이 쓰는 모양을 건드리면 2,170칸이 어긋난다."""
        assert split_param_display(raw) == (name, {})

    def test_size_tail_becomes_the_reference_notation(self):
        """정본은 `u16s_AdcBuffer[8]` 로 적는다(92칸). 같은 정보, 다른 표기."""
        assert split_param_display("u16s_AdcBuffer (size: 8)")[0] == "u16s_AdcBuffer[8]"

    def test_multi_dimensional_size(self):
        assert split_param_display("buf (size: 9x8)")[0] == "buf[9][8]"

    def test_size_is_not_appended_twice(self):
        """이미 첨자가 있으면 덧붙이지 않는다."""
        assert split_param_display("buf[8] (size: 8)")[0] == "buf[8]"

    def test_return_row_keeps_its_identity(self):
        """⚠ 이 시리즈의 덫 — 마지막 토큰을 취하면 `S16` 이 되어 타입으로 둔갑한다."""
        name, extra = split_param_display("return S16 (range: -32768 ~ 32767)")
        assert name == "return"
        assert extra["type"] == "S16"
        assert extra["range"] == "-32768 ~ 32767"

    def test_bare_return_has_no_type(self):
        assert split_param_display("return") == ("return", {})

    def test_type_prefix_moves_to_the_type_column(self):
        assert split_param_display("U8 u8t_Data") == ("u8t_Data", {"type": "U8"})

    def test_multiword_type_prefix(self):
        name, extra = split_param_display("enum en_g_DoorState u8s_DoorStsData")
        assert (name, extra["type"]) == ("u8s_DoorStsData", "enum en_g_DoorState")

    @pytest.mark.parametrize(
        "raw,name,type_text",
        [
            ("const U8 * pu8t_Data", "pu8t_Data", "const U8 *"),
            ("U8 * p", "p", "U8 *"),
            ("U8* p", "p", "U8*"),
            ("unsigned char c", "c", "unsigned char"),
            ("struct Foo * f", "f", "struct Foo *"),
            ("l_u8 pid", "pid", "l_u8"),
            ("U8 u8t_Buf[LEN]", "u8t_Buf[LEN]", "U8"),
        ],
    )
    def test_pointer_and_qualified_parameters(self, raw, name, type_text):
        """시그니처 파라미터의 흔한 모양 — 포인터/한정자가 이름에 남으면 조회가 어긋난다."""
        got_name, extra = split_param_display(raw)
        assert (got_name, extra.get("type")) == (name, type_text)

    def test_type_prefix_with_array_keeps_the_dimension_on_the_name(self):
        name, extra = split_param_display("U16 u16t_AdcBuffer[8]")
        assert (name, extra["type"]) == ("u16t_AdcBuffer[8]", "U16")

    def test_idx_and_divisor_become_a_note_not_part_of_the_name(self):
        name, extra = split_param_display("s16g_ApiIn_OverPos (divisor: no 0)")
        assert name == "s16g_ApiIn_OverPos"
        assert "divisor: no 0" in extra["note"]

    def test_notes_are_kept_when_the_size_is_also_present(self):
        """⚠ 관찰 첨자를 조용히 버리면 정보가 사라진다 — 이름에서 빼되 남긴다."""
        name, extra = split_param_display("u8s_DataBuffer (size: 60) (idx: 4, 0, 2)")
        assert name == "u8s_DataBuffer[60]"
        assert "idx: 4, 0, 2" in extra["note"]


class TestGridRow:
    def test_global_info_wins_over_the_recovered_type(self):
        """전역 정보가 권위다 — 되찾은 값은 그 칸이 **비었을 때만** 채운다."""
        row = _param_grid_row(1, "u8t_Data", {"type": "U16"}, None, {"type": "U8"})
        assert row[2] == "U16"

    def test_recovered_type_fills_an_empty_column(self):
        row = _param_grid_row(1, "return", {}, None, {"type": "S16"})
        assert row[2] == "S16"

    def test_recovered_range_fills_an_empty_column(self):
        row = _param_grid_row(1, "return", {}, None, {"range": "0 ~ 255"})
        assert row[3] == "0 ~ 255"

    def test_note_is_appended_to_the_description(self):
        row = _param_grid_row(1, "buf", {"desc": "ADC 버퍼"}, None, {"note": "idx: 0, 1"})
        assert row[5] == "ADC 버퍼 (idx: 0, 1)"

    def test_note_alone_becomes_the_description(self):
        row = _param_grid_row(1, "buf", {}, None, {"note": "divisor: no 0"})
        assert row[5] == "divisor: no 0"

    def test_no_extras_leaves_every_column_as_before(self):
        """⚠ 음성 대조군."""
        row = _param_grid_row(1, "u8g_A", {"type": "U8", "desc": "플래그"})
        assert row[1:] == ["u8g_A", "U8", _NA, _NA, "플래그"]


class TestResolveParamGridEntries:
    def test_the_global_lookup_succeeds_after_decomposition(self):
        """⚠ 꼬리가 붙은 채로 찾으면 gmap 에 없어 Type/Range/Desc 가 통째로 N/A 였다."""
        info = {"globals_static": ["[IN] u16s_AdcBuffer (size: 8)"]}
        gmap = {"u16s_AdcBuffer": {"type": "U16", "array": "[8]", "desc": "ADC 버퍼"}}
        grid_in, _grid_out = resolve_param_grid_entries(info, gmap)
        assert grid_in[0][1] == "u16s_AdcBuffer[8]"
        assert grid_in[0][2] == "U16 Array"
        assert "ADC 버퍼" in grid_in[0][5]

    def test_the_same_variable_with_and_without_an_index_note_is_one_row(self):
        """중복 판정을 꼬리째로 하면 같은 변수가 두 행이 된다."""
        info = {"globals_static": [
            "[IN] u16s_Buf (size: 2)",
            "[IN] u16s_Buf (size: 2) (idx: 0, 1)",
        ]}
        grid_in, _ = resolve_param_grid_entries(info, {})
        assert len(grid_in) == 1
        assert grid_in[0][1] == "u16s_Buf[2]"

    def test_a_return_output_lands_in_the_out_grid_with_its_columns(self):
        info = {"outputs": ["[OUT] return U8 (range: 0 ~ 255)"]}
        _grid_in, grid_out = resolve_param_grid_entries(info, {})
        assert grid_out[0][1] == "return"
        assert grid_out[0][2] == "U8"
        assert grid_out[0][3] == "0 ~ 255"

    def test_plain_globals_are_unchanged(self):
        """⚠ 음성 대조군 — 90.2% 를 차지하는 평범한 이름이 흔들리면 안 된다."""
        info = {"globals_global": ["[INOUT] u8g_State"]}
        grid_in, grid_out = resolve_param_grid_entries(info, {"u8g_State": {"type": "U8"}})
        assert grid_in[0][1] == "u8g_State"
        assert grid_out[0][1] == "u8g_State"
        assert grid_in[0][2] == "U8"


class TestSingleSourceOfAnnotationKeys:
    def test_suts_delegates_instead_of_copying(self):
        """꼬리 어휘가 두 곳이면 새 꼬리 추가 때 한쪽만 고쳐지고 **꼬리가 이름이 된다**."""
        from generators import suts
        from tests.unit._source_probe import source_of

        body = source_of(suts._strip_param_annotations)
        assert "split_param_annotations(s)[0]" in body
        assert "_PARAM_ANNOT_KEYS" not in body

    def test_the_delegation_still_strips(self):
        from generators import suts

        assert suts._strip_param_annotations("u8g_Hash (idx: u8t_Index)") == "u8g_Hash"
