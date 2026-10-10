# tests/unit/test_struct_member_types.py
"""멤버 경로 행이 **베이스 심볼의 레코드**를 이지 않게 하는 계약 (R8).

## 왜 이 파일이 있나

`resolve_param_grid_entries` 는 `REG_ADC0STS.Bits.READY` 를 `REG_ADC0STS` 로 잘라
`globals_info_map` 을 조회했다. 그러면 Type/Range/Reset/Description 네 칸이 전부
**레지스터 전체**의 값이 된다 — 이름은 비트 하나를 가리키는데:

    이름                     우리(수정 전)   정본
    REG_ADC0STS.Bits.READY   ADC0STSSTR      U8   (0x00 ~ 0x01)
    REG_ADC0STS.Byte         ADC0STSSTR      U8   (0x00 ~ 0xFF)

실측(2026-08-26): 산출물의 멤버 경로 행 **335개**가 그랬고, 그 행들의 정본 대비
재현율은 4개 열 **전부 0.0%**(n=273)였다. 같은 문서의 단일 심볼 행은 type 93.7% 다.
**값 부재가 아니라 다른 대상의 값**이라, 빈 칸이면 하지 않았을 주장을 틀리게 한다 —
Phase 3 이 고친 "이웃 선언의 설명"(809개 중 411개)과 같은 부류다.

## 이 파일이 지키는 것

1. 멤버 표(`extract_struct_member_types`)가 타입·비트폭·**자기** 주석을 낸다
2. 못 풀면 **N/A** 로 둔다 — 베이스의 레코드를 대신 주지 않는다
3. 첨자만 있는 이름(`arr[3]`)은 **베이스가 맞다** — 같은 배열의 원소다
4. 단일 심볼 행은 손대지 않는다(음성 대조군)
"""
from __future__ import annotations

import pytest

from report_gen.function_analyzer import (
    PARAM_GRID_COLS,
    _build_function_info_layout,
    _member_path_of,
    resolve_param_grid_entries,
)
from report_gen.source_parser import (
    extract_struct_member_arrays,
    extract_struct_member_types,
    resolve_struct_member,
)

# 실물 MCU 헤더 구조 그대로 — 익명 비트필드 · 꼬리 주석 · 중첩 union 3단.
REAL_HEADER = """
/*** ADC0STS - ADC0 Status Register; 0x00000602 ***/
typedef union {
  U8 Byte;
  struct {
    U8             :1;
    U8 READY       :1;                     /* Ready For Restart Event Flag */
    U8             :1;
    U8 DBECC_ERR   :1;                     /* Double Bit ECC Error Flag */
  } Bits;
} ADC0STSSTR;

/*** PARTID - Part ID Register; 0x00000000 ***/
typedef union {
  U32 Dword;
  struct {
    union {
      U8 Byte;
      struct {
        U8 ID0     :8;                     /* Part ID 0 */
      } Bits;
    } PARTID0STR;
  } Overlap_STR;
} PARTIDSTR;

typedef struct {
    l_u16            queue_header;         /**< the first element of queue */
    lin_tl_pdu_data  *tl_pdu;              /**< PDU data */
    U8               buf[8];
} lin_transport_layer_queue;
"""


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


# --------------------------------------------------------------------------- §1 추출


class TestExtractMemberTypes:
    def test_basic_member_and_bitfield(self):
        t = extract_struct_member_types(REAL_HEADER)["ADC0STSSTR"]
        assert t["Byte"]["type"] == "U8"
        assert t["Byte"]["bits"] == ""
        assert t["Bits.READY"]["type"] == "U8"
        assert t["Bits.READY"]["bits"] == "1", "비트폭을 잃으면 범위를 못 만든다"

    def test_nested_three_levels(self):
        """실물에 3단이 있다 — 1단만 펴면 그런 행이 통째로 안 풀린다(실측 55칸)."""
        t = extract_struct_member_types(REAL_HEADER)["PARTIDSTR"]
        assert "Overlap_STR.PARTID0STR.Bits.ID0" in t, f"3단이 안 펴졌다: {sorted(t)}"
        assert t["Overlap_STR.PARTID0STR.Byte"]["type"] == "U8"

    def test_pointer_member(self):
        """별표가 이름에 붙는 형태(`T   *p`)를 놓치면 그 타입이 통째로 안 잡힌다."""
        t = extract_struct_member_types(REAL_HEADER)["lin_transport_layer_queue"]
        assert t["tl_pdu"]["type"] == "lin_tl_pdu_data *"

    def test_array_member_keeps_dimension(self):
        t = extract_struct_member_types(REAL_HEADER)["lin_transport_layer_queue"]
        assert t["buf"]["array"] == "[8]"

    def test_trailing_comment_belongs_to_its_own_member(self):
        t = extract_struct_member_types(REAL_HEADER)["ADC0STSSTR"]
        assert t["Bits.READY"]["desc"] == "Ready For Restart Event Flag"
        assert t["Bits.DBECC_ERR"]["desc"] == "Double Bit ECC Error Flag"

    def test_member_without_comment_does_not_inherit_the_previous_one(self):
        """⚠ 음성 대조군 — `;` 로 끊으면 앞 멤버의 꼬리 주석이 다음 조각 **머리**에 붙는다.

        그대로 쓰면 설명이 한 칸씩 밀린다. 전역에서 같은 밀림이 809개 중 411개였다.
        """
        src = "typedef struct { U8 a;  /* 설명 A */\n U8 b;\n U8 c; } T;"
        t = extract_struct_member_types(src)["T"]
        assert t["a"]["desc"] == "설명 A"
        assert t["b"]["desc"] == "", f"앞 멤버 주석을 물려받았다: {t['b']}"
        assert t["c"]["desc"] == ""

    def test_doxygen_marker_is_stripped(self):
        t = extract_struct_member_types(REAL_HEADER)["lin_transport_layer_queue"]
        assert t["queue_header"]["desc"] == "the first element of queue"
        assert t["tl_pdu"]["desc"] == "PDU data"

    def test_anonymous_bitfield_is_not_a_member(self):
        """`U8 :1;` 은 패딩이다 — 이름이 없으니 멤버로 세면 없는 필드를 만든다."""
        t = extract_struct_member_types(REAL_HEADER)["ADC0STSSTR"]
        assert not any(k.endswith(".") or k == "" for k in t)
        assert sorted(t) == ["Bits.DBECC_ERR", "Bits.READY", "Byte"]

    def test_nested_members_do_not_leak_to_top_level(self):
        """중첩 블록 안 멤버가 최상위 이름으로도 잡히면 같은 필드가 두 대상이 된다."""
        t = extract_struct_member_types(REAL_HEADER)["ADC0STSSTR"]
        assert "READY" not in t, f"중첩 멤버가 최상위로 샜다: {sorted(t)}"

    def test_brace_inside_comment_does_not_break_block_matching(self):
        """주석 안 `}` 로 블록이 일찍 닫히면 그 타입의 멤버가 통째로 사라진다."""
        src = "typedef struct { /* 닫는 괄호 } 주의 */ U8 a; U8 b; } T;"
        t = extract_struct_member_types(src)
        assert sorted(t.get("T") or {}) == ["a", "b"], f"주석 중괄호에 걸렸다: {t}"

    @pytest.mark.parametrize("src", ["", "   ", "typedef struct { U8 a;", "int x;"])
    def test_malformed_input_yields_empty_not_crash(self, src):
        assert extract_struct_member_types(src) == {}

    def test_existing_array_extractor_contract_is_unchanged(self):
        """SUTS/SITS 가 쓰는 반환형(`{타입: {멤버: "[8]"}}`)을 넓히지 않았다."""
        got = extract_struct_member_arrays(REAL_HEADER)
        assert got["lin_transport_layer_queue"]["buf"] == "[8]"
        assert isinstance(got["lin_transport_layer_queue"]["buf"], str)


# --------------------------------------------------------------------------- §2 해석


class TestResolveStructMember:
    @pytest.fixture()
    def table(self):
        return extract_struct_member_types(REAL_HEADER)

    def test_direct_path(self, table):
        assert resolve_struct_member(table, "ADC0STSSTR", "Bits.READY")["type"] == "U8"

    def test_walks_through_an_intermediate_typedef(self, table):
        """중간 마디가 또 다른 typedef 여도 이어져야 한다."""
        table = dict(table)
        table["OUTER"] = {"inner": {"type": "ADC0STSSTR", "array": "", "bits": "", "desc": ""}}
        got = resolve_struct_member(table, "OUTER", "inner.Bits.READY")
        assert got and got["type"] == "U8"

    def test_unknown_member_returns_none_not_the_base(self, table):
        """⚠ 핵심 계약 — 못 찾으면 **베이스를 대신 주지 않는다**."""
        assert resolve_struct_member(table, "ADC0STSSTR", "Bits.NOPE") is None
        assert resolve_struct_member(table, "NOSUCHTYPE", "Byte") is None

    def test_subscript_in_path_is_stripped(self, table):
        table = dict(table)
        table["T"] = {"arr": {"type": "U8", "array": "[4]", "bits": "", "desc": ""}}
        assert resolve_struct_member(table, "T", "arr[3]")["type"] == "U8"

    @pytest.mark.parametrize("bad", [None, "", [], 0])
    def test_bad_table_returns_none(self, bad):
        assert resolve_struct_member(bad, "ADC0STSSTR", "Byte") is None

    def test_empty_base_or_path_returns_none(self, table):
        assert resolve_struct_member(table, "", "Byte") is None
        assert resolve_struct_member(table, "ADC0STSSTR", "") is None


class TestMemberPathOf:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("REG_ADC0STS.Bits.READY", "Bits.READY"),
            ("q->tl_pdu", "tl_pdu"),
            ("arr[3]", ""),                 # ⚠ 첨자는 멤버가 아니다
            ("u8s_Flag", ""),
            ("arr[3].m", "m"),
        ],
    )
    def test_split(self, name, expected):
        assert _member_path_of(name) == expected


# --------------------------------------------------------------------------- §3 그리드


_GIM = {
    "REG_ADC0STS": {"type": "ADC0STSSTR", "range": "", "init": "", "desc": "ADC Status Register"},
    "u8s_Flag": {"type": "U8", "range": "0 ~ 255", "init": "0x00", "desc": "System Reset Flag"},
    "u16s_Buf": {"type": "U16", "array": "[8]", "range": "0 ~ 65535", "init": "", "desc": "buffer"},
    "q": {"type": "lin_transport_layer_queue", "range": "", "init": "", "desc": "queue"},
}


@pytest.fixture()
def smt():
    return extract_struct_member_types(REAL_HEADER)


class TestGridWiring:
    def test_member_row_carries_the_member_value(self, smt):
        grid_in, _ = resolve_param_grid_entries(
            _info(globals_global=["[IN] REG_ADC0STS.Bits.READY"]), _GIM, smt)
        row = _row(grid_in, "REG_ADC0STS.Bits.READY")
        assert row[2] == "U8", f"베이스 타입이 남아 있다: {row}"
        assert row[3] == "0 ~ 1 (비트 폭)", f"비트폭 범위/출처 표시가 없다: {row}"
        assert row[5] == "Ready For Restart Event Flag"

    def test_member_row_is_na_when_the_table_is_absent(self):
        """⚠ 핵심 계약 — 표가 없으면 **베이스 값을 물려주지 않고** 비운다."""
        grid_in, _ = resolve_param_grid_entries(
            _info(globals_global=["[IN] REG_ADC0STS.Bits.READY"]), _GIM, None)
        row = _row(grid_in, "REG_ADC0STS.Bits.READY")
        assert row[2] == "N/A", f"베이스 타입을 물려받았다: {row}"
        assert row[5] == "N/A", f"베이스 설명을 물려받았다: {row}"

    def test_unresolvable_member_is_na(self, smt):
        grid_in, _ = resolve_param_grid_entries(
            _info(globals_global=["[IN] REG_ADC0STS.Bits.NOPE"]), _GIM, smt)
        assert _row(grid_in, "REG_ADC0STS.Bits.NOPE")[2] == "N/A"

    def test_single_symbol_rows_are_untouched(self, smt):
        """음성 대조군 — 멤버 축 수정이 단일 심볼 행을 건드리면 안 된다."""
        info = _info(globals_global=["[IN] u8s_Flag"])
        with_table, _ = resolve_param_grid_entries(info, _GIM, smt)
        without, _ = resolve_param_grid_entries(info, _GIM, None)
        assert with_table == without
        assert _row(with_table, "u8s_Flag")[2] == "U8"
        assert _row(with_table, "u8s_Flag")[4] == "0x00", "Reset 이 사라졌다"

    def test_subscript_only_name_keeps_the_base_record(self, smt):
        """`arr[3]` 은 같은 배열의 **원소**라 베이스의 타입·범위·설명이 맞다."""
        grid_in, _ = resolve_param_grid_entries(
            _info(globals_global=["[IN] u16s_Buf[3]"]), _GIM, smt)
        row = _row(grid_in, "u16s_Buf[3]")
        assert row[2] == "U16 Array"
        assert row[5] == "buffer", f"원소 행에서 베이스 설명이 사라졌다: {row}"

    def test_non_bitfield_member_gets_type_width_provenance(self, smt):
        """비트가 아니면 타입 폭이고, 그 **출처를 함께** 적는다(기존 판정 재사용)."""
        grid_in, _ = resolve_param_grid_entries(
            _info(globals_global=["[IN] REG_ADC0STS.Byte"]), _GIM, smt)
        assert _row(grid_in, "REG_ADC0STS.Byte")[3] == "0 ~ 255 (타입 폭)"

    def test_member_reset_is_not_invented(self, smt):
        """멤버의 리셋 값은 MCU 데이터시트에 있고 소스엔 없다 — 비운다.

        ⚠ 베이스에 **초기값이 실제로 있는** 경우로 잰다. 빈 베이스로 재면
          "우리가 비운 것" 과 "베이스가 원래 비어 있던 것" 이 구분되지 않아,
          베이스 초기값을 물려주도록 되돌려도 시험이 통과한다(뮤테이션 M18 생존).
        """
        gim = dict(_GIM)
        gim["REG_ADC0STS"] = dict(_GIM["REG_ADC0STS"], init="0x55")
        grid_in, _ = resolve_param_grid_entries(
            _info(globals_global=["[IN] REG_ADC0STS.Bits.READY"]), gim, smt)
        assert _row(grid_in, "REG_ADC0STS.Bits.READY")[4] == "N/A", "베이스 초기값을 물려받았다"
        # 음성 대조군 — 단일 심볼 행은 그 초기값을 그대로 실어야 한다.
        single, _ = resolve_param_grid_entries(
            _info(globals_global=["[IN] REG_ADC0STS"]), gim, smt)
        assert _row(single, "REG_ADC0STS")[4] == "0x55"

    def test_union_full_width_alias_keeps_the_base_description(self, smt):
        """`REG_X.Byte` 는 레지스터 **전체와 같은 저장소**라 그 설명이 맞다.

        정본도 그 칸에 레지스터 설명을 적는다(`ADC0STS / ADC Status Register`).
        비우면 맞는 정보를 버리게 된다 — 실측 259칸이 이 모양이었다.
        """
        grid_in, _ = resolve_param_grid_entries(
            _info(globals_global=["[IN] REG_ADC0STS.Byte"]), _GIM, smt)
        assert _row(grid_in, "REG_ADC0STS.Byte")[5] == "ADC Status Register"

    def test_bitfield_does_not_inherit_the_base_description(self, smt):
        """⚠ 음성 대조군 — 전폭 별칭 규칙이 비트 하나에까지 번지면 원래 결함이다."""
        gim = dict(_GIM)
        gim["REG_ADC0STS"] = dict(_GIM["REG_ADC0STS"])
        smt2 = {k: {m: dict(r) for m, r in v.items()} for k, v in smt.items()}
        smt2["ADC0STSSTR"]["Bits.READY"]["desc"] = ""      # 자기 주석이 없는 경우
        grid_in, _ = resolve_param_grid_entries(
            _info(globals_global=["[IN] REG_ADC0STS.Bits.READY"]), gim, smt2)
        assert _row(grid_in, "REG_ADC0STS.Bits.READY")[5] == "N/A", "비트 필드가 베이스 설명을 물려받았다"

    def test_struct_top_level_member_does_not_inherit(self, smt):
        """struct 최상위 멤버는 별칭이 아니다 — 물려주면 안 된다."""
        grid_in, _ = resolve_param_grid_entries(
            _info(globals_global=["[IN] q.buf"]), _GIM, smt)
        assert _row(grid_in, "q.buf")[5] == "N/A", "struct 멤버가 베이스 설명을 물려받았다"

    def test_parent_kind_is_recorded(self):
        t = extract_struct_member_types(REAL_HEADER)
        assert t["ADC0STSSTR"]["Byte"]["parent"] == "union"
        assert t["ADC0STSSTR"]["Bits.READY"]["parent"] == "struct"
        assert t["lin_transport_layer_queue"]["buf"]["parent"] == "struct"

    def test_array_member_is_marked_as_array(self, smt):
        grid_in, _ = resolve_param_grid_entries(
            _info(globals_global=["[IN] q.buf"]), _GIM, smt)
        assert _row(grid_in, "q.buf")[2] == "U8 Array"

    def test_row_count_is_unchanged_by_the_member_axis(self, smt):
        """행을 더하거나 잃지 않는다 — 값만 바뀐다."""
        info = _info(globals_global=[
            "[IN] REG_ADC0STS.Bits.READY", "[IN] REG_ADC0STS.Byte", "[IN] u8s_Flag"])
        a, _ = resolve_param_grid_entries(info, _GIM, smt)
        b, _ = resolve_param_grid_entries(info, _GIM, None)
        assert len(a) == len(b) == 3

    def test_third_argument_is_optional(self):
        """기존 호출부(2인자)가 그대로 돌아야 한다 — 계약 확장은 additive."""
        grid_in, _ = resolve_param_grid_entries(_info(globals_global=["[IN] u8s_Flag"]), _GIM)
        assert _row(grid_in, "u8s_Flag")[2] == "U8"

    def test_layout_fallback_uses_the_table_from_info(self, smt):
        """표를 미리 안 넣어준 폴백 경로도 멤버 표를 봐야 한다."""
        info = _info(globals_global=["[IN] REG_ADC0STS.Bits.READY"])
        info["_globals_info_map"] = _GIM
        info["_struct_member_types"] = smt
        rows = _build_function_info_layout(info, PARAM_GRID_COLS)
        cells = [c for _kind, cs in rows for c in cs]
        assert "U8" in cells, f"폴백 경로가 멤버 표를 안 봤다: {cells[:24]}"
        assert "ADC0STSSTR" not in cells, "폴백 경로가 베이스 타입을 적었다"


# --------------------------------------------------------------------------- §4 배선


class TestPayloadAndCache:
    """payload 키가 없으면 멤버 행이 전부 N/A 로 나간다 — 배선이 곧 계약이다."""

    def test_source_sections_emit_the_member_table(self, tmp_path):
        """⚠ 함수 스코프 fixture 를 쓴다 — 이 파서를 module 스코프로 잡았다가 고부하
        `-n auto` 에서 간헐 ERROR 를 낸 전례가 있다.
        """
        from backend.services import file_resolver as fr
        from report_gen.uds_generator import generate_uds_source_sections

        (tmp_path / "regs.h").write_text(REAL_HEADER, encoding="utf-8")
        (tmp_path / "m.c").write_text(
            '#include "regs.h"\nvoid Adc_Init(void) { REG_ADC0STS.Bits.READY = 1U; }\n',
            encoding="utf-8")
        saved = fr._resolver
        fr._resolver = fr.LocalFileResolver()
        try:
            payload = generate_uds_source_sections(str(tmp_path), preprocess=False)
        finally:
            # ⚠ 원래 값 **복원** — 특정 값으로 고정하면 다음 테스트가 물려받는다.
            fr._resolver = saved

        table = payload.get("struct_member_types")
        assert isinstance(table, dict) and table, "payload 에 멤버 표가 없다"
        assert table["ADC0STSSTR"]["Bits.READY"]["type"] == "U8"
        # 기존 키도 그대로 나가야 한다(SUTS/SITS 계약).
        assert isinstance(payload.get("struct_member_arrays"), dict)

    def test_cache_version_was_bumped(self):
        """키를 새로 넣고 버전을 안 올리면 구 캐시가 히트해 fix 가 죽는다(v12 전례)."""
        from backend.helpers.uds import _SOURCE_SECTIONS_SCHEMA_VERSION as ver

        assert int(str(ver).lstrip("v")) >= 14, f"캐시 버전이 v14 미만이다: {ver}"

    def test_docx_builder_passes_the_table_to_the_grid(self):
        """⚠ 구조 검사다 — 관측량이 아니다.

        문서 생성은 수백 초라 단위 시험에서 돌릴 수 없어, 두 호출부가 인자를
        **세 개로** 넘기는지만 본다. 대신 판정 자체는 위 §3 이 관측량으로 고정한다.
        """
        import ast
        from pathlib import Path as _Path

        src = _Path("report_gen/docx_builder.py").read_text(encoding="utf-8")
        calls = [n for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "resolve_param_grid_entries"]
        assert len(calls) == 2, f"호출부 개수가 바뀌었다: {len(calls)}"
        for c in calls:
            assert len(c.args) == 3, f"멤버 표를 안 넘기는 호출부가 있다 (line {c.lineno})"
