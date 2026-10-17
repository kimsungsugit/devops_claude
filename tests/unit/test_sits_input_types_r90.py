"""(R90) SITS 서브케이스 입력 값은 그 입력의 **선언 타입이 담는 값**이어야 한다.

HDPDM01 실측(r89c 문서): 통합 oracle 이 `input_outside_declared_type` 으로 거부한 기대 칸 1,996 · 서브케이스 266
(`ReProg_Opt`(UINT8) = -1, `BackupArray[0]`(U16) = 2147483647 …) — 문서가 프로그램에 존재할 수 없는 입력을 적고 있었다.
카탈로그는 행 수 · 순서 · 역할을 그대로 두고 값만 선언 타입에 맞춘다(`generators/sits.py` R90 블록).

(R90 후속) 선언 타입 전폭만 쓰면 정상 행이 코드가 다루지 않는 값으로 간다 — `SwITC_SwUFn_0401/0403` 의 S16 가운데 값 0 이 나눗셈
분모가 되어 모든 행이 미정의 동작이었다. 설계서(SwUDS `Value Range`)가 범위를 적었으면 도메인 = 설계서 범위 ∩ 선언 타입: 정상 행은
그 안, 강건성 행은 그 바로 밖(타입이 담을 때).
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from generators import sits as S
from generators.sits import (
    _BOUNDARY_SETS,
    _TYPE_BOUNDED_MARK,
    _apply_documented_range,
    _declared_input_domain,
    _documented_interval,
    _infer_boundary_values,
    _param_decl_index,
    _role_values,
    _typed_boundary_values,
    _uds_documented_ranges,
    collect_integration_flows,
    generate_itc_list,
)

_INT_KEYS = ("uint8", "uint16", "uint32", "int8", "int16", "int32", "bool")


def _bounds(dom):
    """도메인이 담는 범위 — 시험 쪽 독립 계산(표의 유효 양끝 · enum/비트필드의 lo/hi)."""
    if dom["kind"] == "table":
        return _BOUNDARY_SETS[dom["key"]][1], _BOUNDARY_SETS[dom["key"]][5]
    return dom["lo"], dom["hi"]


# ── 값 카탈로그 ────────────────────────────────────────────────────────────────
class TestTypedCatalogue:
    @pytest.mark.parametrize("key", _INT_KEYS)
    def test_every_role_value_is_held_by_the_type(self, key):
        vals, bounded = _typed_boundary_values({"kind": "table", "key": key})
        lo, hi = _BOUNDARY_SETS[key][1], _BOUNDARY_SETS[key][5]
        assert len(vals) == 7
        assert all(lo <= v <= hi for v in vals), (key, vals)
        assert bounded == ("inside", "inside")

    @pytest.mark.parametrize("key", ("uint8", "uint16", "uint32", "int8", "int16", "int32"))
    def test_valid_roles_keep_the_table_and_robustness_moves_just_inside(self, key):
        """유효 값(인덱스 1~5)은 표 그대로(표는 불가침 — `c_type_bounds` 거울), 무효 두 칸만 경계 바로 안쪽."""
        row = _BOUNDARY_SETS[key]
        vals, _ = _typed_boundary_values({"kind": "table", "key": key})
        assert vals[1:6] == row[1:6]
        assert vals[0] == row[1] + 1 and vals[6] == row[5] - 1
        assert len(set(vals)) == 7, "역할 값이 서로 겹치면 행이 시험을 하나 잃는다"

    def test_the_examples_from_the_document(self):
        assert _typed_boundary_values({"kind": "table", "key": "uint8"})[0] == [1, 0, 63, 127, 191, 255, 254]
        u16 = _typed_boundary_values({"kind": "table", "key": "uint16"})[0]
        assert 2147483647 not in u16 and 65536 not in u16 and -1 not in u16

    def test_bool_stays_in_zero_one(self):
        assert _typed_boundary_values({"kind": "table", "key": "bool"}) == ([1, 0, 0, 0, 1, 1, 0], ("inside", "inside"))

    def test_float_is_unchanged(self):
        assert _typed_boundary_values({"kind": "table", "key": "float"}) == (list(_BOUNDARY_SETS["float"]), ("", ""))

    def test_enum_uses_enumerators_and_keeps_an_outside_value_the_object_holds(self):
        """enum 은 열거자가 유효 값, 열거자 밖 ±1 은 enum 객체가 담으면 그대로(원본 모델 `ENUM_INPUT_RANGE`)."""
        from generators.c_source_oracle import ENUM_INPUT_RANGE
        dom = {"kind": "enum", "values": list(range(12)), "lo": ENUM_INPUT_RANGE[0], "hi": ENUM_INPUT_RANGE[1]}
        vals, bounded = _typed_boundary_values(dom)
        assert vals == [1, 0, 3, 6, 9, 11, 12]
        assert bounded == ("inside", "")
        acks = [17, 34, 65, 66, 67, 68, 69, 70, 71]
        vals, bounded = _typed_boundary_values({"kind": "enum", "values": acks, "lo": 0, "hi": 127})
        assert vals[0] == 16 and vals[6] == 72 and bounded == ("", "")
        assert set(vals[1:6]) <= set(acks)

    def test_the_value_just_outside_is_kept_when_it_is_exactly_the_type_bound(self):
        """`vlo-1 == lo` · `vhi+1 == hi` — 타입이 담는 마지막 값이면 범위 밖 강건성 값 그대로(옮기지 않는다)."""
        assert _role_values(0, 255, 1, 254) == ([0, 1, 64, 127, 190, 254, 255], ("", ""))
        assert _role_values(0, 255, 0, 254)[1] == ("inside", "")
        assert _role_values(0, 255, 1, 255)[1] == ("", "inside")

    def test_negative_enumerators_stay_in_what_the_model_accepts(self):
        """열거자 -2 · -1 · 0 · 3 — 원본 모델이 받는 값은 0~127 ∪ 열거자다. -3 은 그 밖이라 하한 쪽은 틈(1, 열거자 밖 · 타입 안),
        상한 쪽은 4(0~127 안 · 열거자 밖 = 범위 밖 강건성 값 그대로)."""
        from generators.c_source_oracle import ENUM_INPUT_RANGE
        vals = [-2, -1, 0, 3]
        dom = {"kind": "enum", "values": vals, "lo": min(ENUM_INPUT_RANGE[0], vals[0]),
               "hi": max(ENUM_INPUT_RANGE[1], vals[-1])}
        got, states = _typed_boundary_values(dom)
        assert got == [1, -2, -1, 0, 3, 3, 4] and states == ("gap", "")
        accepted = set(vals) | set(range(ENUM_INPUT_RANGE[0], ENUM_INPUT_RANGE[1] + 1))
        assert set(got) <= accepted

    def test_all_negative_enumerators_never_step_outside_the_accepted_set(self):
        """열거자 -3 · -2 — -4 · -1 은 0~127 ∪ 열거자 밖이라 내지 않는다(연속이라 틈도 없다 → 다음 · 앞 열거자)."""
        dom = {"kind": "enum", "values": [-3, -2], "lo": -3, "hi": 127}
        assert _typed_boundary_values(dom) == ([-2, -3, -3, -2, -2, -2, -3], ("inside", "inside"))
        # 열거자 -5 · -1 — 사이 -4 ~ -2 는 받지 않는 값이라 틈이 아니다 → 하한+1(-4)이 아니라 다음 열거자(-1)
        sparse = {"kind": "enum", "values": [-5, -1], "lo": -5, "hi": 127}
        got, states = _typed_boundary_values(sparse)
        assert got[0] == -1 and got[6] == 0 and states == ("inside", "")

    def test_enum_with_gaps_keeps_an_invalid_value_inside_the_type(self):
        """열거자 0 · 2 · 4 — -1 은 담기지 않으니 틈 1(하한 쪽) · 3(상한 쪽, 5 는 담기므로 범위 밖 그대로)."""
        dom = {"kind": "enum", "values": [0, 2, 4], "lo": 0, "hi": 127}
        assert _typed_boundary_values(dom) == ([1, 0, 0, 2, 4, 4, 5], ("gap", ""))
        dense = {"kind": "enum", "values": [0, 1, 2], "lo": 0, "hi": 127}
        assert _typed_boundary_values(dense)[1] == ("inside", "")

    def test_documented_value_list_gap(self):
        """U8 설계 값 목록 0 · 5 · 15 — -1 은 U8 밖, 1 은 목록 밖 · 타입 안(틈)."""
        got, states = _typed_boundary_values({"kind": "documented", "lo": 0, "hi": 255, "vlo": 0, "vhi": 15,
                                              "values": [0, 5, 15]})
        assert got[0] == 1 and got[6] == 16 and states == ("gap", "")

    def test_one_bit_field(self):
        assert _typed_boundary_values({"kind": "range", "lo": 0, "hi": 1}) == ([1, 0, 0, 0, 0, 1, 0], ("inside", "inside"))


# ── 선언 타입 해상 ─────────────────────────────────────────────────────────────
_GIM = {
    "u8g_Speed": {"type": "U8", "base_type": "uint8_t", "array": ""},
    "BackupArray": {"type": "U16", "base_type": "uint16_t", "array": "[0x02]"},
    "REG_FSTAT": {"type": "FSTATSTR", "array": ""},
    "g_DoorState": {"type": "enum en_g_DoorState", "array": "",
                    "value_domain": {"kind": "enum", "type": "enum en_g_DoorState", "values": list(range(12))}},
    "lin_configured_NAD": {"type": "l_u8", "array": ""},
    "tl_status": {"type": "lin_message_status", "array": ""},
    "u16g_Shadow": {"type": "U8", "base_type": "uint8_t", "array": ""},
    "g_Mode": {"type": "enum en_Mode", "array": "",
               "value_domain": {"kind": "enum", "type": "enum en_Mode", "values": [17, 34, 65]}},
    "s_State": {"type": "enum", "array": ""},
}
_SMT = {"FSTATSTR": {"Byte": {"type": "U8", "bits": ""}, "Bits.CCIF": {"type": "U8", "bits": "1"},
                     "Bits.FPVIOL": {"type": "U8", "bits": "3"}}}


class TestDeclaredDomain:
    def _dom(self, name, raw="", pdx=None):
        return _declared_input_domain(name, raw, _GIM, _SMT, pdx or {})

    def test_global_scalar(self):
        assert self._dom("u8g_Speed", "[IN] u8g_Speed")[0]["key"] == "uint8"

    def test_lin_alias(self):
        assert self._dom("lin_configured_NAD", "[IN] lin_configured_NAD")[0]["key"] == "uint8"

    def test_array_element_takes_the_element_type_not_the_index_annotation(self):
        """`(idx: ((U32)AddrIn) …)` 꼬리의 `U32` 를 이름 패턴 판정이 타입으로 읽어 2147483647 을 냈다."""
        raw = "[INOUT] BackupArray (size: 2) (idx: ( ( ( U32 )AddrIn ) %0x04U ) / 2U)"
        assert _infer_boundary_values(raw) is _BOUNDARY_SETS["uint32"]   # 이전 판정(근거)
        assert self._dom("BackupArray[0]", raw)[0]["key"] == "uint16"

    def test_bit_field_member_is_its_width(self):
        assert self._dom("REG_FSTAT.Bits.CCIF")[0] == {"kind": "range", "lo": 0, "hi": 1, "bits": 1,
                                                        "source": "member_declaration"}
        assert self._dom("REG_FSTAT.Bits.FPVIOL")[0]["hi"] == 7
        assert self._dom("REG_FSTAT.Byte")[0]["key"] == "uint8"

    def test_enum_global(self):
        d = self._dom("g_DoorState")[0]
        assert d["kind"] == "enum" and d["values"] == list(range(12))

    def test_parameter_declared_in_the_raw(self):
        assert self._dom("ReProg_Opt", "[IN] UINT8 ReProg_Opt")[0]["key"] == "uint8"

    _PDATA = "[INOUT] UINT8 * pData (idx: 1) (range: 0x00000000 ~ 0xFFFFFFFF)"

    def test_pointer_object_is_not_given_the_pointee_domain(self):
        """`pData` 칸은 포인터 객체(주소)를 부른다 — 원본 모델도 그 값을 쓰지 않는다(`pointer_parameter:`). U8 도메인은 엉뚱한 객체의
        것이라 모르는 타입(이전 값)으로 둔다."""
        assert self._dom("pData", self._PDATA) == (None, "pointer_object")

    def test_dereferenced_pointer_cells_read_the_pointee(self):
        """`pData[1]` · `p[0].m` 은 가리키는 대상 — 원본 모델이 하네스 대상으로 세우는 표기다. SUTS 규약대로 가리키는 타입."""
        assert self._dom("pData[1]", self._PDATA)[0]["key"] == "uint8"
        smt = {"MSG": {"len": {"type": "U16"}}}
        d, _ = _declared_input_domain("msg[0].len", "[IN] MSG * msg", {}, smt, {})
        assert d["key"] == "uint16"

    @pytest.mark.parametrize("name, gim, smt, want", [
        ("g_ptr", {"g_ptr": {"type": "U8 *", "array": ""}}, {}, "pointer_object"),
        ("g_ptr[0]", {"g_ptr": {"type": "U8 *", "array": ""}}, {}, ""),
        ("tbl[2]", {"tbl": {"type": "U16 *", "array": "[4]"}}, {}, "pointer_object"),   # 포인터 배열의 원소 = 포인터
        ("tbl[2][0]", {"tbl": {"type": "U16 *", "array": "[4]"}}, {}, ""),
        ("q.data", {"q": {"type": "QUEUE", "array": ""}}, {"QUEUE": {"data": {"type": "U8 *"}}}, "pointer_object"),
        ("q.data[3]", {"q": {"type": "QUEUE", "array": ""}}, {"QUEUE": {"data": {"type": "U8 *"}}}, ""),
    ])
    def test_pointer_globals_and_members(self, name, gim, smt, want):
        d, why = _declared_input_domain(name, "", gim, smt, {})
        assert why == want and (d is None) == bool(want)

    def test_pointer_object_gets_no_documented_address_range(self):
        """포인터 행의 `Value Range`(`0x00000000 ~ 0xFFFFFFFF`)는 주소 범위다 — 값 도메인으로 쓰지 않고 사유를 센다."""
        fd = {"F1": {"name": "Ap", "file": "Ap.c", "calls_list": ["Drv"], "inputs": [self._PDATA], "outputs": [],
                     "globals_global": [], "globals_static": [], "asil": "B"},
              "F2": {"name": "Drv", "file": "Drv.c", "calls_list": [], "inputs": [], "outputs": [],
                     "globals_global": [], "globals_static": [], "asil": "B"}}
        io = {"by_name": {"Ap": {"inputs": [], "outputs": [],
                                 "param_info": {"pData": {"type": "UINT8 *", "range": [0, 0xFFFFFFFF]}}}}}
        stats: dict = {}
        f = collect_integration_flows(fd, max_flows=None, stats_out=stats, uds_unit_io=io)[0]
        src = dict(zip(f["input_vars"], f["input_domain_sources"], strict=True))
        assert src["pData"] == "unknown"
        assert stats["input_documented_range_unused"] == {"pointer_address_range": 1}
        assert stats["input_type_resolution"]["unresolved"] == {"pointer_object": 1}

    def test_global_declaration_wins_over_the_entry_prefix(self):
        assert self._dom("u16g_Shadow", "[IN] U16 u16g_Shadow")[0]["key"] == "uint8"

    def test_enum_parameter_through_the_source_stage_typedef_resolution(self):
        fd = {"F": {"name": "f", "inputs": ["[IN] e_ERROR_CODE e_ReprogErr"],
                    "param_value_domains": {"e_ReprogErr": {"kind": "enum", "values": [0, 1, 2, 15]}}}}
        pdx = _param_decl_index(fd)
        d, _ = self._dom("e_ReprogErr", "[IN] e_ERROR_CODE e_ReprogErr", pdx)
        assert d["kind"] == "enum" and d["values"] == [0, 1, 2, 15]
        assert self._dom("e_ReprogErr", "[IN] e_ERROR_CODE e_ReprogErr")[0] is None   # 맵 없으면 모른다

    def test_conflicting_resolutions_of_one_raw_are_dropped(self):
        fd = {"A": {"inputs": ["[IN] T x"], "param_base_types": {"x": "uint8_t"}},
              "B": {"inputs": ["[IN] T x"], "param_base_types": {"x": "uint16_t"}}}
        assert _param_decl_index(fd) == {}

    @pytest.mark.parametrize("name, raw, why", [
        ("REG_FSTAT", "[IN] REG_FSTAT", "struct_object"),
        ("tl_status", "[OUT] tl_status", "type_unresolved"),
        ("p", "p", "no_declaration"),
        ("REG_FSTAT.Bits.NOPE", "", "member_type_unresolved"),
    ])
    def test_unknown_types_are_not_guessed(self, name, raw, why):
        assert self._dom(name, raw) == (None, why)


# ── 서브케이스 생성 ────────────────────────────────────────────────────────────
def _fd_typed():
    def _f(name, file, calls, inputs=(), glob=()):
        return {"name": name, "file": file, "calls_list": list(calls), "inputs": list(inputs), "outputs": [],
                "globals_global": list(glob), "globals_static": [], "asil": "B",
                "logic_flow": [{"type": "if"}]}          # 조건 분기 → `ABV, AEC`(등가류 라벨 EC1~EC7)
    return {
        "F1": _f("Ap_Run", "Ap.c", ["Drv_Write"], inputs=["[IN] UINT8 ReProg_Opt"],
                 glob=["[IN] u8g_Speed", "[IN] g_DoorState", "[IN] REG_FSTAT.Bits.CCIF",
                       "[INOUT] BackupArray (size: 2) (idx: ( ( ( U32 )AddrIn ) %0x04U ) / 2U)"]),
        # 호출 대상의 [INDIRECT] 전역 → 전역 상태 행(GLOBAL_1 · GLOBAL_2)
        "F2": _f("Drv_Write", "Drv.c", [], glob=["[INDIRECT] g_Mode", "[INDIRECT] g_DoorState"]),
    }


def _itcs(typed=True, max_subcases=15):
    flows = collect_integration_flows(_fd_typed(), max_flows=None, globals_info_map=copy.deepcopy(_GIM),
                                      struct_member_types=_SMT if typed else None)
    if not typed:
        for f in flows:
            f.pop("input_types", None)
            f.pop("indirect_types", None)
    return flows, generate_itc_list(flows, max_subcases=max_subcases)


class TestSubCases:
    def test_no_emitted_value_is_outside_its_declared_type(self):
        flows, itcs = _itcs()
        f = flows[0]
        doms = {n: d for n, d in zip(f["input_vars"], f["input_types"], strict=True) if d}
        doms.update({n: d for n, d in zip(f["indirect_vars"], f["indirect_types"], strict=True) if d})
        assert {"ReProg_Opt", "u8g_Speed", "g_DoorState", "REG_FSTAT.Bits.CCIF", "BackupArray[0]"} <= set(doms)
        seen = 0
        for sc in itcs[0]["sub_cases"]:
            for n, v in sc["inputs"].items():
                if n in doms:
                    lo, hi = _bounds(doms[n])
                    assert lo <= v <= hi, (sc["case_label"], n, v)
                    seen += 1
        assert seen > 50

    def test_the_untyped_path_did_emit_such_values(self):
        """대조군 — 같은 흐름에서 타입을 빼면(이전 동작) 타입 밖 값이 나온다. 위 시험이 공허하지 않다는 근거."""
        flows, itcs = _itcs()
        doms = dict(zip(flows[0]["input_vars"], flows[0]["input_types"], strict=True))
        _, old = _itcs(typed=False)
        bad = [(n, v) for sc in old[0]["sub_cases"] for n, v in sc["inputs"].items()
               if doms.get(n) and not _bounds(doms[n])[0] <= v <= _bounds(doms[n])[1]]
        assert ("ReProg_Opt", -1) in bad and ("BackupArray[0]", 2147483647) in bad
        assert ("REG_FSTAT.Bits.CCIF", 127) in bad and ("u8g_Speed", 256) in bad

    def test_count_order_and_roles_are_unchanged(self):
        _, new = _itcs()
        _, old = _itcs(typed=False)
        a, b = new[0]["sub_cases"], old[0]["sub_cases"]
        assert len(a) == len(b) == 15
        assert [sc["case_num"] for sc in a] == [sc["case_num"] for sc in b]
        assert [sc["case_label"].split(" ※")[0] for sc in a] == [sc["case_label"] for sc in b]
        assert [list(sc["inputs"]) for sc in a] == [list(sc["inputs"]) for sc in b]

    def test_deterministic(self):
        assert _itcs()[1] == _itcs()[1]

    def test_robustness_rows_say_what_moved(self):
        fd = _fd_typed()
        fd["F2"]["globals_global"] = []      # g_Mode(열거자 17~65 → 16 이 담긴다)를 빼면 하한 쪽은 전부 옮겨진다
        flows = collect_integration_flows(fd, max_flows=None, globals_info_map=copy.deepcopy(_GIM),
                                          struct_member_types=_SMT)
        subs = generate_itc_list(flows, max_subcases=15)[0]["sub_cases"]
        first, last = subs[0], subs[6]
        # g_DoorState 는 열거자 밖 12 가 담기므로 상한 쪽은 무효 값이 남는다 → 상한 행엔 꼬리가 없다
        assert last["inputs"]["g_DoorState"] == 12 and "g_DoorState" not in last["type_bounded"]
        assert "EC7:무효-상한" in last["case_label"] and _TYPE_BOUNDED_MARK[1] not in last["case_label"]
        # 하한 쪽은 모든 입력이 타입 안으로 옮겨졌다 → 무효를 주장하는 라벨에 꼬리
        assert set(first["type_bounded"]) == set(first["inputs"])
        assert "EC1:무효-하한" in first["case_label"] and first["case_label"].endswith(_TYPE_BOUNDED_MARK[0])
        err1 = next(sc for sc in subs if str(sc["case_label"]).startswith("ERR_PROP_1"))
        assert err1["case_label"].endswith(_TYPE_BOUNDED_MARK[0]) and err1["precondition"].endswith(_TYPE_BOUNDED_MARK[0])

    def test_an_enum_outside_value_keeps_the_row_invalid(self):
        """g_Mode(열거자 17 · 34 · 65)의 16 은 enum 객체가 담는 무효 값 — 그 행은 여전히 무효라 꼬리가 없다."""
        _, itcs = _itcs()
        first = itcs[0]["sub_cases"][0]
        assert first["inputs"]["g_Mode"] == 16 and "g_Mode" not in first["type_bounded"]
        assert _TYPE_BOUNDED_MARK[0] not in first["case_label"]

    def test_an_enum_gap_row_says_invalid_for_a_different_reason(self):
        """열거자 0 · 2 · 4 의 하한 강건성 값 1 은 타입 안이지만 열거자 밖 — '무효 값 없음' 꼬리가 아니라 '열거자 밖 · 타입 안'."""
        from generators.sits import _TYPE_GAP_MARK
        gim = copy.deepcopy(_GIM)
        gim["g_DoorState"]["value_domain"]["values"] = [0, 2, 4]
        fd = _fd_typed()
        fd["F2"]["globals_global"] = []
        flows = collect_integration_flows(fd, max_flows=None, globals_info_map=gim, struct_member_types=_SMT)
        subs = generate_itc_list(flows, max_subcases=15)[0]["sub_cases"]
        first = subs[0]
        assert first["inputs"]["g_DoorState"] == 1
        assert first["type_bounded_gap"] == ["g_DoorState"]
        assert set(first["type_bounded"]) == set(first["inputs"])        # 전부 타입 안으로 옮겨졌다
        assert first["case_label"].endswith(_TYPE_GAP_MARK[0]) and _TYPE_BOUNDED_MARK[0] not in first["case_label"]
        err1 = next(sc for sc in subs if str(sc["case_label"]).startswith("ERR_PROP_1"))
        assert err1["precondition"].endswith(_TYPE_GAP_MARK[0]) and err1["type_bounded_gap"] == ["g_DoorState"]

    def test_a_row_with_an_unknown_input_keeps_its_label(self):
        """모르는 타입의 입력은 이전 값(-1)이 남는다 — 그 행은 여전히 무효 값을 가지므로 꼬리를 붙이지 않는다."""
        fd = _fd_typed()
        fd["F1"]["globals_global"].append("[IN] tl_status")
        flows = collect_integration_flows(fd, max_flows=None, globals_info_map=copy.deepcopy(_GIM),
                                          struct_member_types=_SMT)
        sub0 = generate_itc_list(flows, max_subcases=15)[0]["sub_cases"][0]
        assert sub0["inputs"]["tl_status"] == -1
        assert "tl_status" not in sub0["type_bounded"]
        assert _TYPE_BOUNDED_MARK[0] not in sub0["case_label"]

    def test_global_state_row_uses_the_declared_minimum(self):
        """전역 상태 행의 변수도 입력이다 — enum 이면 첫 열거자(이름 패턴 표의 0 은 열거자가 아니다)."""
        _, itcs = _itcs()
        g = {sc["case_label"]: sc["inputs"] for sc in itcs[0]["sub_cases"] if str(sc["case_label"]).startswith("GLOBAL_")}
        assert g == {"GLOBAL_1 [g_Mode=min]": g["GLOBAL_1 [g_Mode=min]"],
                     "GLOBAL_2 [g_DoorState=min]": g["GLOBAL_2 [g_DoorState=min]"]}
        assert g["GLOBAL_1 [g_Mode=min]"]["g_Mode"] == 17
        assert g["GLOBAL_2 [g_DoorState=min]"]["g_DoorState"] == 0
        _, old = _itcs(typed=False)
        assert next(sc for sc in old[0]["sub_cases"] if sc["case_label"].startswith("GLOBAL_1"))["inputs"]["g_Mode"] == 0

    def test_enum_without_known_enumerators_is_held_to_the_enum_range(self):
        """`static enum { … } s_State;` — 열거자 값을 못 읽어도 enum 객체가 담는 범위(`ENUM_INPUT_RANGE`)는 안다."""
        from generators.c_source_oracle import ENUM_INPUT_RANGE
        d, _ = _declared_input_domain("s_State", "[IN] s_State", _GIM, _SMT, {})
        assert (d["kind"], d["lo"], d["hi"]) == ("range", ENUM_INPUT_RANGE[0], ENUM_INPUT_RANGE[1])
        vals, _ = _typed_boundary_values(d)
        assert all(ENUM_INPUT_RANGE[0] <= v <= ENUM_INPUT_RANGE[1] for v in vals)

    def test_flow_without_types_keeps_the_previous_values(self):
        """다른 호출자(영향도 초안)가 만든 흐름 — 타입 필드가 없으면 이전 값 그대로."""
        flow = {"entry_fn": "f", "call_chain": "f", "module_name": "m", "input_vars": ["x"], "input_raws": ["[IN] U8 x"],
                "expected_vars": [], "expected_raws": [], "related_ids": [], "asil": "QM", "logic_flow": [],
                "cross_calls": []}
        subs = S._generate_sub_case_candidates(flow, max_cases=7)
        assert [sc["inputs"]["x"] for sc in subs] == _BOUNDARY_SETS["uint8"]

    def test_stats_report_typed_and_unresolved(self):
        stats: dict = {}
        fd = _fd_typed()
        fd["F1"]["globals_global"].append("[IN] tl_status")
        flows = collect_integration_flows(fd, max_flows=None, stats_out=stats, globals_info_map=copy.deepcopy(_GIM),
                                          struct_member_types=_SMT)
        generate_itc_list(flows, max_subcases=15, stats_out=stats)
        assert stats["input_type_resolution"]["unresolved"] == {"type_unresolved": 1}
        assert stats["input_type_resolution"]["typed"] >= 5
        assert stats["input_type_bounded_values"] > 0
        assert {"input_type_resolution", "input_type_bounded_values"} <= set(S._FLOW_COV_KEYS)


# ── 실 프로젝트(HDPDM01) ───────────────────────────────────────────────────────
_HD_ROOTS = (r"D:\Project\Ados\PDS64_RD", r"D:\Project\Ados\PDS64_FBL")


@pytest.fixture(scope="module")
def hd_sections():
    if not all(Path(r).is_dir() for r in _HD_ROOTS):
        pytest.skip("HDPDM01 소스 트리가 없다(로컬 전용 확인)")
    from report_generator import generate_uds_source_sections
    rd = generate_uds_source_sections(",".join(_HD_ROOTS))
    if not rd.get("function_details"):
        pytest.skip("HDPDM01 파싱 결과가 비었다")
    return rd


def test_hdpdm01_no_emitted_input_is_outside_its_declared_type(hd_sections):
    """파싱한 HDPDM01 — 선언 타입을 아는 입력의 값은 전부 그 타입 안. SUTS 의 같은 판정(`_holds_declared_types`)으로도 본다.

    r89c 문서와 같은 입력(RD+FBL, 흐름 캡 없음, 서브케이스 15): 수정 전 같은 해상으로 17,900 값 · 866 서브케이스가 밖이었다.
    """
    from generators.suts import _holds_declared_types
    rd = hd_sections
    gim, smt = rd.get("globals_info_map") or {}, rd.get("struct_member_types") or {}
    flows = collect_integration_flows(rd["function_details"], max_flows=None, globals_info_map=gim,
                                      struct_members=rd.get("struct_member_arrays") or {}, struct_member_types=smt)
    itcs = generate_itc_list(copy.deepcopy(flows), max_subcases=15)
    by_entry = {f["entry_fn"]: f for f in flows}
    checked = 0
    for t in itcs:
        f = by_entry[t["entry_fn"]]
        doms = {n: d for n, d in zip(f["input_vars"], f["input_types"], strict=True) if d}
        doms.update({n: d for n, d in zip(f["indirect_vars"], f["indirect_types"], strict=True) if d})
        for sc in t["sub_cases"]:
            view, vtypes = {}, {}
            for n, v in sc["inputs"].items():
                d = doms.get(n)
                if not d or isinstance(v, str) or (d["kind"] == "table" and d["key"] == "float"):
                    continue
                lo, hi = _bounds(d)
                assert lo <= v <= hi, (t["tc_id"], sc["case_label"], n, v, d)
                checked += 1
                if d["kind"] == "table":
                    view[n], vtypes[n] = v, d["key"] + "_t"
            assert _holds_declared_types(view, vtypes, set(view)), (t["tc_id"], sc["case_label"])
    assert checked > 10_000

    # 대조군 — 타입 필드를 지운 같은 흐름(이전 동작)은 타입 밖 값을 낸다(검사가 공허하지 않다)
    old_flows = copy.deepcopy(flows)
    for f in old_flows:
        f.pop("input_types", None)
        f.pop("indirect_types", None)
    old = generate_itc_list(old_flows, max_subcases=15)
    assert [len(t["sub_cases"]) for t in old] == [len(t["sub_cases"]) for t in itcs]
    outside = 0
    for t in old:
        f = by_entry[t["entry_fn"]]
        doms = {n: d for n, d in zip(f["input_vars"], f["input_types"], strict=True) if d}
        for sc in t["sub_cases"]:
            for n, v in sc["inputs"].items():
                d = doms.get(n)
                if d and not isinstance(v, str) and not (d["kind"] == "table" and d["key"] == "float"):
                    lo, hi = _bounds(d)
                    outside += not lo <= v <= hi
    assert outside > 1_000


# ── 생성 경로 배선 ─────────────────────────────────────────────────────────────
_A_C = b"""typedef unsigned char U8;
typedef struct { U8 Byte; struct { U8 F : 1; U8 G : 3; } Bits; } REGSTR;
REGSTR g_Reg;
U8 u8g_Speed;
void B(U8 x);
void A(void)
{
    if (g_Reg.Bits.F) { B(u8g_Speed); }
}
"""
_B_C = b"typedef unsigned char U8;\nvoid B(U8 x)\n{\n    (void)x;\n}\n"


def test_generate_sits_hands_member_types_to_the_flows(tmp_path, monkeypatch):
    """`generate_sits` 가 소스 단계의 `struct_member_types` 를 흐름 수집에 넘긴다 — 안 넘기면 비트필드 멤버가 타입 미상이 되어
    이전 값(-1 · 127 · 256)으로 돌아간다. 품질 리포트에도 이 축이 실린다."""
    (tmp_path / "a.c").write_bytes(_A_C)
    (tmp_path / "b.c").write_bytes(_B_C)
    seen: dict = {}
    real = S.generate_itc_list

    def spy(*a, **k):
        seen["itcs"] = real(*a, **k)
        return seen["itcs"]

    monkeypatch.setattr(S, "generate_itc_list", spy)
    out = S.generate_sits(source_root=str(tmp_path), output_path=str(tmp_path / "o.xlsm"), max_subcases=15)
    vals = [sc["inputs"]["g_Reg.Bits.F"] for t in seen.get("itcs") or [] for sc in t["sub_cases"]
            if "g_Reg.Bits.F" in (sc.get("inputs") or {})]
    assert len(vals) >= 7, out.get("error")
    assert set(vals) <= {0, 1}, vals
    cov = (out.get("quality_report") or {}).get("integration_flow_coverage") or {}
    assert cov["input_type_resolution"]["typed"] >= 2
    assert cov["input_type_bounded_values"] > 0


# ── (R90 후속) 설계서 범위 ──────────────────────────────────────────────────────

_U8 = {"kind": "table", "key": "uint8", "source": "global_declaration"}
_S16 = {"kind": "table", "key": "int16", "source": "global_declaration"}


def _doc(ranges=(), values=(), unread=()):
    return {"ranges": list(ranges), "values": [sorted(v) for v in values], "unread": list(unread), "texts": []}


class TestDocumentedInterval:
    def test_tables_are_intersected(self):
        """한 변수를 여러 함수 표가 적는다 — 전폭 행은 양식 기본값이라 좁은 표가 그 변수에 대해 더 말한 것."""
        assert _documented_interval(_doc(ranges=[(0, 255), (0, 1)])) == ({"vlo": 0, "vhi": 1, "values": None}, "")

    def test_value_list_meets_a_full_width_row(self):
        iv, _ = _documented_interval(_doc(ranges=[(-32768, 32767)], values=[[0, 2470, 2268]]))
        assert iv == {"vlo": 0, "vhi": 2470, "values": [0, 2268, 2470]}

    @pytest.mark.parametrize("doc, why", [
        (_doc(ranges=[(0, 1), (5, 9)]), "documented_ranges_disagree"),
        (_doc(ranges=[(0, 10)], values=[[20, 30]]), "documented_ranges_disagree"),
        (_doc(unread=["digit_count_differs"]), "documented_range_unread:digit_count_differs"),
        (None, "not_documented"),
    ])
    def test_unusable_documents_say_why(self, doc, why):
        assert _documented_interval(doc) == (None, why)


class TestApplyDocumentedRange:
    def test_a_narrower_range_inside_the_type(self):
        dom, src, why = _apply_documented_range(_U8, _doc(ranges=[(0, 1)]))
        assert (src, why) == ("documented_range", "")
        vals, bounded = _typed_boundary_values(dom)
        # 정상 값은 범위 안, 강건성 상한은 범위 바로 밖(U8 이 2 를 담는다), 하한은 타입 밖이라 안쪽
        assert vals == [1, 0, 0, 0, 0, 1, 2] and bounded == ("inside", "")

    def test_signed_range_away_from_zero_has_no_zero_nominal(self):
        """S16 전폭의 가운데 값 0 은 나눗셈 분모가 됐다 — 설계서가 0 을 뺀 범위를 적었으면 정상 값에 0 이 없다."""
        dom, src, _ = _apply_documented_range(_S16, _doc(ranges=[(2253, 2672)]))
        vals, bounded = _typed_boundary_values(dom)
        assert src == "documented_range"
        assert vals == [2252, 2253, 2357, 2462, 2567, 2672, 2673] and bounded == ("", "")
        assert 0 not in vals[1:6]

    def test_value_list_nominal_is_a_listed_value(self):
        dom, _, _ = _apply_documented_range(_S16, _doc(ranges=[(-32768, 32767)], values=[[0, 2268, 2470]]))
        vals, _ = _typed_boundary_values(dom)
        assert vals[0] == -1 and vals[6] == 2471 and vals[3] == 2268
        assert set(vals[1:6]) <= {0, 2268, 2470}

    def test_full_width_document_is_the_declared_type(self):
        """`0x7FFF ~ 0x8000`(S16 전폭)은 타입 밖의 정보를 주지 않는다 — 선언 타입 표 그대로(SUTS R65 와 같은 판정)."""
        assert _apply_documented_range(_S16, _doc(ranges=[(-32768, 32767)])) == (_S16, "declared_type", "")

    def test_a_document_the_type_cannot_hold_falls_back_and_says_why(self):
        assert _apply_documented_range(_S16, _doc(ranges=[(0, 65535)])) == (_S16, "declared_type", "documented_outside_type")

    def test_unknown_type_with_a_document_stays_inside_it(self):
        """선언 타입을 모르면 범위 밖 값을 객체가 담는지 모른다 — 강건성 값도 문서 범위 안."""
        dom, src, _ = _apply_documented_range(None, _doc(ranges=[(0, 3)]))
        vals, _ = _typed_boundary_values(dom)
        assert src == "documented_range" and dom["type_known"] is False
        assert all(0 <= v <= 3 for v in vals)
        assert _apply_documented_range(None, None) == (None, "unknown", "not_documented")

    def test_enum_is_narrowed_to_documented_enumerators(self):
        enum = {"kind": "enum", "values": list(range(12)), "lo": 0, "hi": 127}
        dom, src, _ = _apply_documented_range(enum, _doc(ranges=[(0, 3)]))
        assert src == "documented_range" and dom["values"] == [0, 1, 2, 3]
        assert _apply_documented_range(enum, _doc(ranges=[(0, 11)])) == (enum, "declared_type", "")
        assert _apply_documented_range(enum, _doc(ranges=[(40, 50)]))[2] == "documented_excludes_enumerators"

    def test_float_is_not_ranged(self):
        f = {"kind": "table", "key": "float"}
        assert _apply_documented_range(f, _doc(ranges=[(0, 1)])) == (f, "declared_type", "float_not_ranged")


def _uds_io(tables):
    return {"by_name": {fn: {"inputs": [], "outputs": [], "param_info": pi} for fn, pi in tables.items()}}


_UDS_TABLES = {
    "Ap_Run": {"u8g_Speed": {"type": "U8", "range": [0, 255]}, "g_DoorState": {"type": "enum", "range": [0, 11]}},
    "Drv_Write": {"u8g_Speed": {"type": "U8", "range": [10, 20]},
                  "BackupArray": {"type": "U16", "range": [0, 0xFFFF]},
                  "ReProg_Opt": {"type": "UINT8", "range_unread": "digit_count_differs"}},
}


class TestDocumentedRangeInSubCases:
    def _flows(self, tables=_UDS_TABLES, stats=None):
        return collect_integration_flows(_fd_typed(), max_flows=None, stats_out=stats,
                                         globals_info_map=copy.deepcopy(_GIM), struct_member_types=_SMT,
                                         uds_unit_io=_uds_io(tables))

    def test_chain_tables_narrow_the_domain_and_the_source_is_recorded(self):
        f = self._flows()[0]
        src = dict(zip(f["input_vars"], f["input_domain_sources"], strict=True))
        dom = dict(zip(f["input_vars"], f["input_types"], strict=True))
        assert src["u8g_Speed"] == "documented_range" and (dom["u8g_Speed"]["vlo"], dom["u8g_Speed"]["vhi"]) == (10, 20)
        assert src["BackupArray[0]"] == "declared_type"        # 전폭 문서 → 타입
        assert src["ReProg_Opt"] == "declared_type"            # 못 읽은 칸 → 타입(사유는 통계)
        assert src["REG_FSTAT.Bits.CCIF"] == "declared_type"   # 표에 없다

    def test_nominal_rows_stay_inside_and_robustness_rows_go_just_outside(self):
        flows = self._flows()
        subs = generate_itc_list(flows, max_subcases=15)[0]["sub_cases"]
        speed = [sc["inputs"]["u8g_Speed"] for sc in subs]
        assert speed[0] == 9 and speed[6] == 21                # 강건성 — 문서 범위 바로 밖(U8 이 담는다)
        assert all(10 <= v <= 20 for v in speed[1:6])          # 경계 · 정상
        rest = [sc for sc in subs if not str(sc["case_label"])[:1].isdigit()]
        for sc in rest:
            v = sc["inputs"]["u8g_Speed"]
            if str(sc["case_label"]).startswith("ERR_PROP"):
                assert v in (9, 21)
            else:
                assert 10 <= v <= 20, (sc["case_label"], v)    # 조건 조합 · 전역 상태 = 정상
        assert all(0 <= sc["inputs"]["u8g_Speed"] <= 255 for sc in subs)
        # 무효 값이 남았으므로(문서 범위 밖) 그 입력은 타입 안으로 옮긴 목록에 없다
        assert "u8g_Speed" not in subs[0]["type_bounded"] and "u8g_Speed" not in subs[6].get("type_bounded", [])

    def test_count_and_order_do_not_change(self):
        with_doc = generate_itc_list(self._flows(), max_subcases=15)[0]["sub_cases"]
        without = generate_itc_list(_itcs()[0], max_subcases=15)[0]["sub_cases"]
        assert [sc["case_num"] for sc in with_doc] == [sc["case_num"] for sc in without]
        assert [list(sc["inputs"]) for sc in with_doc] == [list(sc["inputs"]) for sc in without]

    def test_stats_count_sources_and_unused_documents(self):
        stats: dict = {}
        self._flows(stats=stats)
        src = stats["input_domain_source"]
        assert src["documented_range"] == 1 and src["unknown"] == 0
        assert src["declared_type"] == sum(src.values()) - 1
        assert stats["input_documented_range_unused"] == {"documented_range_unread:digit_count_differs": 1}
        assert {"input_domain_source", "input_documented_range_unused",
                "input_documented_range_type_unknown"} <= set(S._FLOW_COV_KEYS)

    def test_tables_off_the_chain_are_not_read(self):
        docs = _uds_documented_ranges(["u8g_Speed"], ["Ap_Run"], _uds_io(_UDS_TABLES))
        assert docs["u8g_Speed"]["ranges"] == [(0, 255)]

    def test_global_state_row_uses_the_documented_minimum(self):
        tables = {**_UDS_TABLES, "Drv_Write": {**_UDS_TABLES["Drv_Write"], "g_Mode": {"type": "enum", "range": [34, 65]}}}
        subs = generate_itc_list(self._flows(tables), max_subcases=15)[0]["sub_cases"]
        g1 = next(sc for sc in subs if str(sc["case_label"]).startswith("GLOBAL_1"))
        assert g1["inputs"]["g_Mode"] == 34


def test_generate_sits_reads_the_swuds_value_ranges(tmp_path, monkeypatch):
    """`generate_sits` 가 SwUDS 함수 표를 읽어 흐름 수집에 넘긴다(로더는 SUTS 와 같은 `load_uds_unit_io`)."""
    (tmp_path / "a.c").write_bytes(_A_C)
    (tmp_path / "b.c").write_bytes(_B_C)
    import generators.uds_unit_io as uio
    monkeypatch.setattr(uio, "load_uds_unit_io",
                        lambda *a, **k: _uds_io({"A": {"u8g_Speed": {"type": "U8", "range": [3, 9]}}}))
    seen: dict = {}
    real = S.generate_itc_list

    def spy(*a, **k):
        seen["itcs"] = real(*a, **k)
        return seen["itcs"]

    monkeypatch.setattr(S, "generate_itc_list", spy)
    out = S.generate_sits(source_root=str(tmp_path), output_path=str(tmp_path / "o.xlsm"), max_subcases=15,
                          uds_path=str(tmp_path / "missing_SwUDS.docx"))
    vals = [sc["inputs"]["u8g_Speed"] for t in seen.get("itcs") or [] for sc in t["sub_cases"]
            if "u8g_Speed" in (sc.get("inputs") or {})]
    assert vals and vals[0] == 2 and vals[6] == 10 and all(3 <= v <= 9 for v in vals[1:6]), (vals, out.get("error"))
    cov = (out.get("quality_report") or {}).get("integration_flow_coverage") or {}
    assert cov["input_domain_source"]["documented_range"] >= 1


_HD_UDS = Path(r"D:\Project\devops\260105\docs\(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx")


def test_hdpdm01_with_swuds_ranges_nominal_rows_stay_inside_the_document(hd_sections):
    """HDPDM01 + SwUDS — 값은 전부 선언 타입 안, 정상 행(2~6 · 조건 조합 · 전역 상태)은 설계서 범위 안, 강건성 행은 설계서 범위
    바로 밖이거나(타입이 담을 때) 경계 바로 안쪽."""
    if not _HD_UDS.is_file():
        pytest.skip("HDPDM01 SwUDS 가 없다(로컬 전용 확인)")
    from generators.uds_unit_io import load_uds_unit_io
    rd = hd_sections
    io = load_uds_unit_io(str(_HD_UDS), source_functions=[
        str((v or {}).get("name") or "") for v in rd["function_details"].values() if isinstance(v, dict)])
    stats: dict = {}
    flows = collect_integration_flows(rd["function_details"], max_flows=None, stats_out=stats,
                                      globals_info_map=rd.get("globals_info_map") or {},
                                      struct_members=rd.get("struct_member_arrays") or {},
                                      struct_member_types=rd.get("struct_member_types") or {}, uds_unit_io=io)
    assert stats["input_domain_source"]["documented_range"] > 500
    itcs = generate_itc_list(copy.deepcopy(flows), max_subcases=15)
    by_entry = {f["entry_fn"]: f for f in flows}
    nominal_checked = 0
    for t in itcs:
        f = by_entry[t["entry_fn"]]
        doms = {n: d for n, d in zip(f["input_vars"], f["input_types"], strict=True) if d}
        for i, sc in enumerate(t["sub_cases"]):
            label = str(sc["case_label"])
            robust = i in (0, 6) or label.startswith("ERR_PROP")
            for n, v in sc["inputs"].items():
                d = doms.get(n)
                if not d or isinstance(v, str) or (d["kind"] == "table" and d["key"] == "float"):
                    continue
                lo, hi = _bounds(d)
                assert lo <= v <= hi, (t["tc_id"], label, n, v)
                if d["kind"] == "documented" and not robust:
                    assert d["vlo"] <= v <= d["vhi"], (t["tc_id"], label, n, v, d)
                    nominal_checked += 1
    assert nominal_checked > 3_000
