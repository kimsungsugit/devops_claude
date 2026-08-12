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

import sys

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

    @pytest.mark.parametrize("addr", ["0x00FF9DF0U", "0x1FUL", "0x20u", "4096U"])
    def test_integer_suffix_on_the_address_is_also_eaten(self, addr):
        """⚠ `0[xX][0-9A-Fa-f]+` 는 `U` 앞에서 멈춘다 — 남은 `U` 가 **이름이 된다**.

        실측(SysOs_Main.c): 그렇게 등록된 전역 `U` 가 매크로 토큰화 결함과 맞물려
        324개 함수에 붙었다. 상세는 `tests/unit/test_phantom_inputs.py`.
        """
        got = _extract_c_global_candidates(
            f"static const volatile FirmwareVersionInfo_t g_Ver @{addr} = {{ 1 }};"
        )
        assert [g["name"] for g in got] == ["g_Ver"], got

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


class TestGlobalsScanLoss:
    """전역 인식에서 **잃은 것**을 산출물이 말하는지.

    스캔 캡(.c 200 · .h 300) · 미사용 판정 · 접두사 필터 · 타입없음 드롭 — 네 지점이
    전부 조용히 자른다. 기록이 없으면 "이 프로젝트엔 원래 전역이 없다" 로 오독한다.
    """

    def test_payload_carries_the_loss_counters(self, sfr_project):
        g = sfr_project.get("globals_scan")
        assert isinstance(g, dict) and g.get("measured") is True
        for k in ("c_total", "c_cap", "h_total", "h_cap", "extern_added",
                  "extern_dropped_unused", "extern_dropped_prefix",
                  "typeless_dropped", "globals_kept"):
            assert k in g, f"{k} 가 없으면 그 축의 손실을 볼 수 없다"

    def test_totals_are_reported_not_just_scanned(self, sfr_project):
        """캡에 닿았는지는 **스캔 수만으로는 알 수 없다** — 총량이 함께 있어야 한다."""
        g = sfr_project["globals_scan"]
        assert g["c_scanned"] <= g["c_total"] and g["h_scanned"] <= g["h_total"]
        assert g["c_cap"] and g["h_cap"]

    def test_header_only_extern_is_recognized(self, tmp_path):
        """**cross-file 전역이 실제로 해결되는지** — 이게 B 단계가 지키려는 행동이다.

        정의는 다른 .c 에 있고 선언만 헤더에 있는 전역(`u8g_SystemReset_F` 같은)이
        인식돼야 시험 입력이 선다.

        ⚠ 인식 주체는 헤더 extern 스캔이 **아니라** `globals_detailed`(tree-sitter 전
          파일 스캔)다. 실측으로 확인했다 — 헤더 extern 스캔을 타는 건수는 실제
          프로젝트에서 0 이다(`extern_added: 0`). include 가드를 씌워도 마찬가지다.
          그래서 그 스캔의 필터(미사용·접두사)는 **현행 파서에선 도달하지 않는 경로**이며,
          카운터는 tree-sitter 가 실패했을 때를 위한 계측으로만 남아 있다.
        """
        (tmp_path / "ext.h").write_text(
            "#ifndef EXT_H\n#define EXT_H\nextern U8 u8g_SystemReset_F;\n#endif\n",
            encoding="utf-8")
        (tmp_path / "m.c").write_text(
            '#include "ext.h"\n'
            "void f(void){ if( u8g_SystemReset_F == 0 ) { return; } }\n",
            encoding="utf-8")
        res = generate_uds_source_sections(str(tmp_path), preprocess=False)
        globs = [
            g
            for info in (res.get("function_details") or {}).values()
            if isinstance(info, dict) and info.get("name") == "f"
            for g in (list(info.get("globals_global") or []) + list(info.get("globals_static") or []))
        ]
        assert any(g.endswith("u8g_SystemReset_F") for g in globs), \
            "다른 파일에 정의된 전역을 못 잡으면 시험 입력이 서지 않는다"

    def test_unmeasured_is_not_reported_as_zero_loss(self, monkeypatch, tmp_path):
        """⚠ AST 파서가 없으면 이 값들은 **재지 못한 것**이다.

        기본값을 0 으로 두면 화면이 "전역을 하나도 안 잃었다" 고 말한다. 그리고 애초에
        바인딩이 없으면 페이로드 조립에서 `NameError` 로 생성이 통째로 죽는다
        (이 커밋에서 실제로 그럴 뻔했다).
        """
        monkeypatch.setitem(sys.modules, "workflow.code_parser", None)
        (tmp_path / "a.c").write_text("void f(void){ return; }\n", encoding="utf-8")
        res = generate_uds_source_sections(str(tmp_path), preprocess=False)
        g = res.get("globals_scan")
        assert isinstance(g, dict), "폴백 경로에서 키가 아예 없으면 소비처가 터진다"
        assert g.get("measured") is False
        assert g.get("reason")
        assert "globals_kept" not in g, "재지 못한 것을 0 으로 그리면 안 된다"


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
