"""SITS 입력 도메인 골든 — 합성 다중 모듈 프로젝트와 그 흐름 · ITC 스냅숏(`tests/fixtures/sits_input_domain_golden.json`).

입력 값 도메인 해상(`_declared_input_domain` ∩ `_apply_documented_range` · `_uds_documented_ranges`)을
`generators.sits._input_domain_resolver` 로 뽑아낸 리팩터(S2)가 **문서의 열 · 값을 한 바이트도 바꾸지 않았다**는 근거다.
픽스처는 뽑아내기 **전** 코드(커밋 194c8eeb)로 만들었다 — 리팩터 뒤 코드로 다시 만들면 골든이 아니라 거울이 된다.

다시 만들어야 하면(입력 프로젝트를 늘릴 때) 뽑아내기 전 코드의 작업 트리에서:
    .venv/Scripts/python.exe -m tests.unit._sits_golden_project --write

프로젝트가 밟는 해상 경로: 전역 표 타입 · enum(열거자) · 맨 `enum` · 비트필드 멤버 · 구조체 통째(모름) · 포인터 객체(주소 범위
사유) · 원문 매개변수 선언 · typedef 를 푼 enum 매개변수 · 배열 원소 펼침 · 설계서 범위로 좁힘 · 전폭 문서 · 못 읽은 범위 ·
표끼리 어긋남 · 타입 밖 문서 · 열거자 좁힘 · 타입 모르는 입력의 문서 범위 · 간접 전역(GLOBAL 행)의 문서 범위 · 입력 없는
진입(callee 매개변수 모음) · 매개변수 20 · 전역 15 · 출력 10 을 넘는 진입 · (리뷰 I9) 멤버 타입 미상 · 못 푼 typedef · 실수에 대한
설계서 범위 · 간접 전역 포인터 · 구조체 통째의 설계서 범위.

뽑아내기 전 코드로 다시 만들 때는 작업 트리를 되돌리지 말고(git stash 금지) 그 판의 `sits.py` 를 `generators.sits` 로 올려 부른다 —
`scratchpad/regen_golden_from_head.py` 가 한 방법이다(`git show 194c8eeb:generators/sits.py` 를 importlib 로 실행).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sits_input_domain_golden.json"

# 흐름 dict 중 리팩터 전부터 있던 키 — 새 키(S0 · S2 가 더한 것)는 비교하지 않는다
FLOW_KEYS = ("entry_fn", "call_chain", "functions", "input_vars", "input_raws", "input_types", "input_domain_sources",
             "expected_vars", "expected_raws", "indirect_vars", "indirect_types", "cross_calls", "module_name")
ITC_KEYS = ("tc_id", "gen_method", "test_method", "input_vars", "expected_vars", "entry_fn")
SUB_KEYS = ("case_num", "case_label", "precondition", "inputs", "expected", "type_bounded", "type_bounded_gap")


def _f(name: str, file: str, calls=(), inputs=(), outputs=(), gg=(), gs=(), **kw: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {"name": name, "file": file, "calls_list": list(calls), "inputs": list(inputs),
                         "outputs": list(outputs), "globals_global": list(gg), "globals_static": list(gs), "asil": "B",
                         "logic_flow": [{"type": "if"}]}
    d.update(kw)
    return d


def function_details() -> Dict[str, Dict[str, Any]]:
    return {
        "F1": _f("Ap_Run", "Ap.c", ["Drv_Write", "Ap_Help"],
                 inputs=["[IN] UINT8 ReProg_Opt", "[IN] e_CODE e_Err",
                         "[INOUT] UINT8 * pData (idx: 1) (range: 0x00000000 ~ 0xFFFFFFFF)"],
                 outputs=["[OUT] return U8"],
                 gg=["[IN] u8g_Speed", "[IN] g_DoorState", "[IN] REG_FSTAT.Bits.CCIF",
                     "[INOUT] BackupArray (size: 2) (idx: ( ( ( U32 )AddrIn ) %0x04U ) / 2U)", "[IN] s_State",
                     "[IN] g_ptr", "[IN] REG_FSTAT", "[IN] g_Unk", "[IN] u8g_Help"],
                 param_base_types={"ReProg_Opt": "uint8_t"},
                 param_value_domains={"e_Err": {"kind": "enum", "values": [0, 1, 2, 15]}},
                 prototype="U8 Ap_Run(UINT8 ReProg_Opt, e_CODE e_Err, UINT8 *pData)"),
        "F2": _f("Drv_Write", "Drv.c", ["Io_Set"], inputs=["[IN] U16 u16_val"], outputs=["[OUT] u16g_Out"],
                 gg=["[INDIRECT] g_Mode", "[INDIRECT] g_DoorState", "[IN] u16g_Out"]),
        "F3": _f("Ap_Help", "Ap.c", [], gg=["[IN] u8g_Help"]),
        "F4": _f("Io_Set", "Io.c", [], inputs=["[IN] S16 s16_x"], gg=["[IN] s16g_Pos", "[INDIRECT] s16g_Pos"]),
        # 입력 없는 진입 — 다른 모듈 callee 의 매개변수를 통합 입력으로 모은다
        "F5": _f("Io_Main", "IoMain.c", ["Drv_Write"]),
        # 상한(매개변수 20 · 전역 15 · 출력 10)을 넘는 진입
        "F6": _f("Big_Entry", "Big.c", ["Drv_Write"],
                 inputs=[f"[IN] U8 p{i:02d}" for i in range(24)],
                 outputs=[f"[OUT] u8g_O{i:02d}" for i in range(12)],
                 gg=[f"[IN] u8g_B{i:02d}" for i in range(18)]),
        # (리뷰 I9) 멤버 타입 미상 · 못 푼 typedef · 실수(설계서 범위 → `float_not_ranged`), 간접 전역 포인터 · 구조체 통째에 설계서 범위
        "F7": _f("Odd_Entry", "Odd.c", ["Odd_Drv"], inputs=["[IN] U8 u8_odd"],
                 gg=["[IN] REG_FSTAT.Bits.NOPE", "[IN] tl_status", "[IN] f32g_Gain"]),
        "F8": _f("Odd_Drv", "OddDrv.c", gg=["[INDIRECT] g_ptr2", "[INDIRECT] REG_ODD", "[INDIRECT] f32g_Gain2"]),
    }


GLOBALS_INFO = {
    "u8g_Speed": {"type": "U8", "base_type": "uint8_t", "array": ""},
    "BackupArray": {"type": "U16", "base_type": "uint16_t", "array": "[0x02]"},
    "REG_FSTAT": {"type": "FSTATSTR", "array": ""},
    "g_DoorState": {"type": "enum en_g_DoorState", "array": "",
                    "value_domain": {"kind": "enum", "type": "enum en_g_DoorState", "values": list(range(12))}},
    "g_Mode": {"type": "enum en_Mode", "array": "",
               "value_domain": {"kind": "enum", "type": "enum en_Mode", "values": [17, 34, 65]}},
    "s_State": {"type": "enum", "array": ""},
    "g_ptr": {"type": "U8 *", "array": ""},
    "u8g_Help": {"type": "U8", "base_type": "uint8_t", "array": ""},
    "u16g_Out": {"type": "U16", "base_type": "uint16_t", "array": ""},
    "s16g_Pos": {"type": "S16", "base_type": "int16_t", "array": ""},
    **{f"u8g_B{i:02d}": {"type": "U8", "base_type": "uint8_t", "array": ""} for i in range(18)},
    "tl_status": {"type": "lin_message_status", "array": ""},
    "f32g_Gain": {"type": "float", "base_type": "float", "array": ""},
    "f32g_Gain2": {"type": "float", "base_type": "float", "array": ""},
    "g_ptr2": {"type": "U16 *", "array": ""},
    "REG_ODD": {"type": "FSTATSTR", "array": ""},
}
STRUCT_MEMBER_TYPES = {"FSTATSTR": {"Byte": {"type": "U8", "bits": ""}, "Bits.CCIF": {"type": "U8", "bits": "1"},
                                    "Bits.FPVIOL": {"type": "U8", "bits": "3"}}}


def uds_unit_io() -> Dict[str, Any]:
    tables = {
        "Ap_Run": {"u8g_Speed": {"type": "U8", "range": [0, 255]},                       # 전폭 → 선언 타입
                   "g_DoorState": {"type": "enum", "values": [0, 2, 4]},                   # 열거자 좁힘
                   "e_Err": {"type": "e_CODE", "range_unread": "digit_count_differs"},     # 못 읽음
                   "ReProg_Opt": {"type": "UINT8", "range": [0, 300]},                     # 타입 밖
                   "pData": {"type": "UINT8 *", "range": [0, 0xFFFFFFFF]},                 # 주소 범위
                   "g_Unk": {"type": "U8", "range": [0, 3]},                               # 타입 모름 + 문서
                   "u8g_Help": {"type": "U8", "range": [0, 1]}},
        "Drv_Write": {"u8g_Speed": {"type": "U8", "range": [10, 20]},                     # 좁힘(교집합)
                      "g_Mode": {"type": "enum", "range": [34, 65]},                       # 간접 전역 열거자 좁힘
                      "u8g_Help": {"type": "U8", "range": [5, 9]},                         # Ap_Run 과 어긋남
                      "u16_val": {"type": "U16", "range": [100, 200]}},
        "Io_Set": {"s16g_Pos": {"type": "S16", "range": [2253, 2672]}},
        "Odd_Entry": {"f32g_Gain": {"type": "float", "range": [0, 1]}},                # 실수 → 범위 안 씀
        "Odd_Drv": {"g_ptr2": {"type": "U16 *", "range": [0, 0xFFFF]},              # 간접 전역 포인터 — 주소 범위
                    "REG_ODD": {"type": "FSTATSTR", "range": [0, 7]},                # 간접 전역 구조체 통째
                    "f32g_Gain2": {"type": "float", "range": [0, 1]}},
    }
    return {"by_name": {fn: {"inputs": [], "outputs": [], "param_info": pi} for fn, pi in tables.items()}}


def run() -> Dict[str, Any]:
    """흐름 수집 → ITC 생성(서브케이스 15). 입력은 매번 새 사본이다."""
    from generators.sits import collect_integration_flows, generate_itc_list
    stats: Dict[str, Any] = {}
    flows = collect_integration_flows(function_details(), max_flows=None, stats_out=stats,
                                      globals_info_map=copy.deepcopy(GLOBALS_INFO),
                                      struct_member_types=copy.deepcopy(STRUCT_MEMBER_TYPES),
                                      uds_unit_io=uds_unit_io())
    itcs = generate_itc_list(copy.deepcopy(flows), max_subcases=15, stats_out=stats)
    return {"flows": flows, "itcs": itcs, "stats": stats}


def snapshot(got: Dict[str, Any]) -> Dict[str, Any]:
    """비교 대상만 — 리팩터 전부터 있던 키. JSON 왕복으로 튜플 · 리스트를 같은 모양으로 둔다."""
    def _sub(sc: Dict[str, Any]) -> Dict[str, Any]:
        return {k: sc[k] for k in SUB_KEYS if k in sc}
    out = {
        "flows": [{k: f.get(k) for k in FLOW_KEYS} for f in got["flows"]],
        "itcs": [dict({k: t.get(k) for k in ITC_KEYS}, sub_cases=[_sub(sc) for sc in t.get("sub_cases") or []])
                 for t in got["itcs"]],
        "stats": got["stats"],
    }
    return json.loads(json.dumps(out, ensure_ascii=False, sort_keys=True, default=str))


def dumps(snap: Dict[str, Any]) -> str:
    return json.dumps(snap, ensure_ascii=False, sort_keys=True, indent=1)


def main(argv: List[str]) -> int:
    if "--write" not in argv:
        print(dumps(snapshot(run()))[:2000])
        return 0
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(dumps(snapshot(run())) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
