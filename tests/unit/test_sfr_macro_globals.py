"""SFR(하드웨어 레지스터)이 매크로 뒤에 숨어 통째로 사라지던 경로.

## 무엇이 문제였나 (KJPDS02 실측, 2026-08-12)

정본 SUTS 는 `g_SysOs_WdiCtrl` 의 입력을
`['u8s_InitiComplet_F', '_PTT.Bits.PTT3', '_PTT.Bits.PTT4', 'u8g_SystemReset_F']` 로 적는데
생성물은 **0개**였다. 결손 762건 중 이 계열(선언 미발견 SFR/헤더)이 **340건(44.6%)** 으로 최대다.

원인이 두 겹이었다:

1. **주소 배치 접미사가 변수명을 먹었다.** `extern volatile PTTSTR _PTT @0x000002C0;` 를
   `_parse_c_declaration_statement` 가 선언자 마지막 토큰으로 이름을 잡아 **`x000002C0`** 으로
   등록했다. `Generated_Code/IO_Map.h` 한 파일에만 372건 — 레지스터 전체가 쓰레기 이름이 되고
   진짜 이름은 어디에도 없었다.
2. **본문은 매크로 이름만 쓴다.** `#define PTT_PTT3 _PTT.Bits.PTT3` 이라 `_PTT` 는 어느 `.c`
   에도 문자열로 안 나온다. 그래서 헤더 extern 스캔의 "본문에서 쓰였나" 검사를 통과하지 못하고
   버려졌고, `macro_globals_map`(globals_info_map 에 있는 이름만 참조)도 못 만들어졌다.

⚠ 이름은 **확장형**으로 나와야 한다. base(`_PTT`)로만 접으면 정본과 다른 이름이라
  추적이 끊긴다.
"""
from __future__ import annotations

import pytest

from generators.suts import collect_unit_functions
from report_gen.source_parser import _extract_c_global_candidates
from report_gen.uds_generator import generate_uds_source_sections

_IO_MAP_H = (
    "extern volatile PTTSTR _PTT @0x000002C0;\n"
    "#define PTT_PTT3   _PTT.Bits.PTT3\n"
    "#define PTT_PTT4   _PTT.Bits.PTT4\n"
    "#define MAX_COUNT  255\n"
    "#define HALF(x)    ((x) / 2)\n"
)
_SYS_H = "extern U8 u8g_SystemReset_F;\n"
_MAIN_C = (
    '#include "IO_Map.h"\n'
    '#include "Sys.h"\n'
    "static U8 u8s_InitiComplet_F;\n"
    "void g_SysOs_WdiCtrl( void )\n"
    "{\n"
    "    U8 u8t_V;\n"
    "    if( u8g_SystemReset_F == 0 ) { PTT_PTT4 = (U8)(~(U8)PTT_PTT4); }\n"
    "    u8t_V = (U8)PTT_PTT3;\n"
    "    if( ( u8t_V == 1 ) && ( u8s_InitiComplet_F == 1 ) ) { PTT_PTT3 = 0; }\n"
    "    return;\n"
    "}\n"
)


class TestAddressPlacementSuffix:
    """`@0x...` 배치 지정자가 이름을 삼키지 않는지."""

    def test_sfr_name_is_the_variable_not_the_address(self):
        got = _extract_c_global_candidates("extern volatile PTTSTR _PTT @0x000002C0;")
        assert [g["name"] for g in got] == ["_PTT"], "주소 리터럴이 변수명이 되면 안 된다"
        assert got[0]["type"] == "volatile PTTSTR"

    def test_symbolic_address_is_also_stripped(self):
        got = _extract_c_global_candidates("extern U16 _TIM0 @TIM0_BASE;")
        assert [g["name"] for g in got] == ["_TIM0"]

    @pytest.mark.parametrize(
        "decl,name",
        [
            ("extern U8 u8g_SystemReset_F;", "u8g_SystemReset_F"),
            ("static U8 u8s_Buf[10] = {0};", "u8s_Buf"),
            ("U8 g_Plain;", "g_Plain"),
        ],
    )
    def test_ordinary_declarations_are_unchanged(self, decl, name):
        """@ 를 지우는 처리가 평범한 선언을 건드리면 회귀다."""
        assert [g["name"] for g in _extract_c_global_candidates(decl)] == [name]


@pytest.fixture(scope="module")
def sfr_project(tmp_path_factory):
    d = tmp_path_factory.mktemp("sfr_src")
    (d / "IO_Map.h").write_text(_IO_MAP_H, encoding="utf-8")
    (d / "Sys.h").write_text(_SYS_H, encoding="utf-8")
    (d / "SysOs_Main.c").write_text(_MAIN_C, encoding="utf-8")
    return generate_uds_source_sections(str(d), preprocess=False)


@pytest.fixture(scope="module")
def wdi_globals(sfr_project):
    for info in (sfr_project.get("function_details") or {}).values():
        if isinstance(info, dict) and info.get("name") == "g_SysOs_WdiCtrl":
            return list(info.get("globals_global") or []) + list(info.get("globals_static") or [])
    pytest.fail("g_SysOs_WdiCtrl 를 파싱하지 못했다 — 이 테스트의 전제가 깨졌다")


class TestMacroHiddenRegisters:
    def test_bitfield_path_is_emitted_not_just_the_base(self, wdi_globals):
        names = {g.split("] ", 1)[-1] for g in wdi_globals}
        assert "_PTT.Bits.PTT3" in names, "매크로 확장형이 없으면 정본과 다른 이름이 된다"
        assert "_PTT.Bits.PTT4" in names

    def test_cross_file_extern_still_resolved(self, wdi_globals):
        """헤더 extern 해결은 원래 되던 것 — 매크로 처리가 이걸 깨면 회귀다."""
        assert any(g.endswith("u8g_SystemReset_F") for g in wdi_globals)

    def test_macro_write_makes_it_inout(self, wdi_globals):
        """`PTT_PTT3 = 0;` 은 쓰기다. 본문에 전역명이 없어 라인 스캔은 못 본다."""
        entry = next(g for g in wdi_globals if g.endswith("_PTT.Bits.PTT3"))
        assert entry.startswith("[INOUT]"), f"읽기 전용으로 보면 기대결과 열에서 빠진다: {entry}"

    def test_constant_and_function_like_macros_do_not_become_globals(self, sfr_project):
        """`#define MAX_COUNT 255` 가 전역이 되면 없는 변수를 시험하게 된다."""
        names = {
            g.split("] ", 1)[-1]
            for info in (sfr_project.get("function_details") or {}).values()
            if isinstance(info, dict)
            for g in (list(info.get("globals_global") or []) + list(info.get("globals_static") or []))
        }
        assert "MAX_COUNT" not in names and "255" not in names
        assert "HALF" not in names

    def test_suts_row_input_is_not_empty(self, sfr_project):
        """최종 소비처 확인 — 여기서 비면 시퀀스에 넣을 값이 없다(사용자 보고의 실체)."""
        units = collect_unit_functions(sfr_project["function_details"], sds_map={})
        unit = next(u for u in units if u["name"] == "g_SysOs_WdiCtrl")
        assert unit["input_vars"], "입력 0개면 시험이 성립하지 않는다"
        for expected in ("_PTT.Bits.PTT3", "_PTT.Bits.PTT4", "u8g_SystemReset_F", "u8s_InitiComplet_F"):
            assert expected in unit["input_vars"], f"정본이 입력으로 적는 {expected} 가 없다"
