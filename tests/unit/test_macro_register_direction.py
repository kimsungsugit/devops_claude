"""매크로 뒤에 숨은 레지스터의 **방향**이 뒤집혀 쓰기 전용이 시험 입력이 되던 경로.

## 무엇이 문제였나 (KJPDS02_PV 실측, 2026-08-12)

`_collect_var_usage` 의 매크로 접기 경로는 방향 판정을 전역 경로와 **복제하지 않고**
자체 규칙을 썼는데, 그 규칙이 `rhs = True` 를 **무조건** 세웠다:

    usage[g]["rhs"] = True          # ← 조건 없음
    if _written:
        usage[g]["lhs"] = True
        usage[g]["inout"] = True

그래서 `PTAD_PTADL4 = big_RESET;` 처럼 **쓰기만 하는** 레지스터가 "읽고 쓴다(INOUT)"
가 되어 시험 **입력** 열에 올라갔다. 실측 소스(SysSleepCtrl_PDS.c):

    PTT_PTT3    = big_SET;      /* 쓰기만 */
    PTP_PTP4    = big_RESET;    /* 쓰기만 */
    PTAD_PTADL4 = big_RESET;    /* 쓰기만 */

정본 SUTS 는 이 함수들(`s_Sleep_DisablePower` 등)의 입력을 **0개**로 적는다.

읽기 캡을 풀어 매크로 맵이 3.2배로 늘자 이 결함이 그대로 확대됐다 —
"정본은 입력 0개인데 우리는 값을 낸" unit 이 34 → **44** 로 늘었다. 방향 판정을
`_scan_name_usage` 단일 출처로 합치자 **33** 으로 내려갔다.

⚠ 교훈은 숫자가 아니라 구조다: **판정을 복제하면 한쪽만 고쳐진다.** 이 저장소가
  반복해서 겪은 실패다(`_is_hsis_data_row`, ruff/eslint ratchet, SyTS/SyITS 파서).
"""
from __future__ import annotations

import pytest

from generators.suts import collect_unit_functions
from report_gen.function_analyzer import _collect_var_usage
from report_gen.uds_generator import generate_uds_source_sections

_MG = {"PTAD_PTADL4": ["_PTAD"], "ADC0STS": ["_ADC0STS"]}
_ME = {"PTAD_PTADL4": "_PTAD.Bits.PTADL4", "ADC0STS": "_ADC0STS.Byte"}


class TestMacroDirection:
    """매크로 이름으로 접근한 전역의 방향이 전역 직접 접근과 **같은 규칙**인지."""

    def test_write_only_macro_is_not_an_input(self):
        u = _collect_var_usage("{ PTAD_PTADL4 = big_RESET; }", ["_PTAD"], _MG, _ME)["_PTAD"]
        assert u["lhs"] is True
        assert u["rhs"] is False, "쓰기만 하는 레지스터를 읽기로 세면 시험 입력이 지어진다"
        assert u["inout"] is False

    def test_read_only_macro_is_an_input(self):
        u = _collect_var_usage("{ if( ADC0STS == 0 ) {} }", ["_ADC0STS"], _MG, _ME)["_ADC0STS"]
        assert (u["rhs"], u["lhs"]) == (True, False)

    def test_read_then_write_macro_is_inout(self):
        body = "{ U8 t = ADC0STS;\n  ADC0STS = (U8)0x00; }"
        u = _collect_var_usage(body, ["_ADC0STS"], _MG, _ME)["_ADC0STS"]
        assert u["inout"] is True

    def test_compound_assign_through_macro_is_inout(self):
        u = _collect_var_usage("{ ADC0STS |= 0x01U; }", ["_ADC0STS"], _MG, _ME)["_ADC0STS"]
        assert (u["lhs"], u["rhs"], u["inout"]) == (True, True, True)

    def test_expansion_is_still_the_display_name(self):
        """방향을 고치면서 **이름**이 base 로 되돌아가면 정본과 안 맞는다."""
        u = _collect_var_usage("{ PTAD_PTADL4 = 0; }", ["_PTAD"], _MG, _ME)["_PTAD"]
        assert "_PTAD.Bits.PTADL4" in u["members"]

    @pytest.mark.parametrize(
        "body,lhs,rhs",
        [
            ("{ _PTAD = 1; }", True, False),
            ("{ x = _PTAD; }", False, True),
            ("{ _PTAD |= 1; }", True, True),
        ],
    )
    def test_direct_global_access_is_unchanged(self, body, lhs, rhs):
        """전역 직접 접근의 판정이 흔들리면 회귀다(단일 출처로 합친 쪽의 대조군)."""
        u = _collect_var_usage(body, ["_PTAD"])["_PTAD"]
        assert (u["lhs"], u["rhs"]) == (lhs, rhs)

    def test_macro_absent_from_body_contributes_nothing(self):
        """본문에 없는 매크로가 전역을 세우면 없는 입력이 생긴다."""
        u = _collect_var_usage("{ return; }", ["_PTAD"], _MG, _ME)["_PTAD"]
        assert (u["lhs"], u["rhs"], u["inout"]) == (False, False, False)
        assert not u["members"]


_TAIL_H_HEAD = "\n".join(f"#define PAD_{i:06d} {i}" for i in range(12_000))
_TAIL_H = (
    _TAIL_H_HEAD
    + "\nextern volatile PTADSTR _PTAD @0x00000271;\n"
    + "extern volatile ADC0STSSTR _ADC0STS @0x00000602;\n"
    + "#define PTAD_PTADL4  _PTAD.Bits.PTADL4\n"
    + "#define ADC0STS      _ADC0STS.Byte\n"
)
_TAIL_C = (
    '#include "IO_Map.h"\n'
    "void s_Sleep_DisablePower( void )\n"
    "{\n"
    "    PTAD_PTADL4 = big_RESET;\n"
    "    return;\n"
    "}\n"
    "U8 s_ReadAdcStatus( void )\n"
    "{\n"
    "    return (U8)ADC0STS;\n"
    "}\n"
)


@pytest.fixture(scope="module")
def tail_project(tmp_path_factory):
    """레지스터 정의가 **옛 캡(200KB) 뒤쪽**에 있는 프로젝트.

    실물 IO_Map.h 의 구조를 그대로 재현한다 — 앞쪽 수천 개의 `#define` 다음에
    레지스터가 온다. 옛 캡에서는 여기 정의가 통째로 안 보였다.
    """
    d = tmp_path_factory.mktemp("tail_src")
    (d / "IO_Map.h").write_text(_TAIL_H, encoding="utf-8")
    (d / "m.c").write_text(_TAIL_C, encoding="utf-8")
    assert (d / "IO_Map.h").stat().st_size > 200_000, "테스트 전제(옛 캡 초과)가 깨졌다"
    return generate_uds_source_sections(str(d), preprocess=False)


def _globals_of(project, fn_name):
    for info in (project.get("function_details") or {}).values():
        if isinstance(info, dict) and info.get("name") == fn_name:
            return list(info.get("globals_global") or []) + list(info.get("globals_static") or [])
    pytest.fail(f"{fn_name} 를 파싱하지 못했다 — 이 테스트의 전제가 깨졌다")


class TestRegistersPastTheOldCap:
    def test_register_defined_after_200kb_is_found(self, tail_project):
        names = {g.split("] ", 1)[-1] for g in _globals_of(tail_project, "s_ReadAdcStatus")}
        assert "_ADC0STS.Byte" in names, "캡 뒤쪽 레지스터가 안 잡히면 SFR 결손이 그대로다"

    def test_write_only_register_does_not_become_a_test_input(self, tail_project):
        units = collect_unit_functions(tail_project["function_details"], sds_map={})
        unit = next(u for u in units if u["name"] == "s_Sleep_DisablePower")
        assert unit["input_vars"] == [], (
            f"쓰기 전용 레지스터가 입력이 됐다: {unit['input_vars']} "
            "— 정본은 이 함수의 입력을 0개로 적는다"
        )

    def test_read_only_register_is_a_test_input(self, tail_project):
        """대조군 — 방향 fix 가 읽기까지 지우면 결손이 늘어난다."""
        units = collect_unit_functions(tail_project["function_details"], sds_map={})
        unit = next(u for u in units if u["name"] == "s_ReadAdcStatus")
        assert "_ADC0STS.Byte" in unit["input_vars"]

    def test_truncation_counter_is_zero_when_nothing_is_cut(self, tail_project):
        """절단 계수가 **있어야** 하고, 안 잘렸으면 0 이어야 한다.

        키가 없으면 소비처는 손실을 볼 방법이 없다(옛 판이 정확히 그랬다).
        """
        g = tail_project.get("globals_scan") or {}
        assert g.get("read_truncated_files") == 0
        assert g.get("read_truncated_detail") == []
