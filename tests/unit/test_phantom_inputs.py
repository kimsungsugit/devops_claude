"""시험 입력이 **없는 것으로 채워지거나 있는 것이 사라지던** 두 경로.

## 1. 유령 전역 `U` — 이 프로젝트 전역 부착 1위가 존재하지 않는 변수였다

실측(2026-08-12, KJPDS02 1,157함수): `U` 가 **324개 함수**에 `[IN]` 전역으로 붙어 있었다.
2위(`s16g_ApiIn_MotorPosition`, 123건)의 2.6배다. 결함이 두 겹으로 맞물렸다:

1. **선언 파싱** — `static const volatile FirmwareVersionInfo_t g_FirmwareVersionInfo
   @0x00FF9DF0U = {…};` 에서 주소 배치 접미사를 지우는 정규식이 정수 접미사 `U` 를 안
   먹었다. `0[xX][0-9A-Fa-f]+` 는 `U` 앞에서 멈춘다(16진수가 아니므로). 남은 `U` 가
   선언자의 마지막 토큰이라 **변수 이름이 `U`** 가 됐다.
2. **토큰화** — `#define VectorNumber_VReserved123 123U` 의 확장형에서 식별자를 뽑을 때
   `re.findall(r"[A-Za-z_]\\w*", "123U")` 가 `['U']` 를 내놓는다. 그 `U` 가 ①에서 등록된
   전역 이름과 **정확히 일치**해서, 그 매크로를 쓰는 모든 함수에 전역 `U` 가 붙었다.

피해는 "이름이 이상하다" 가 아니다. `U` 는 1글자라 `collect_unit_functions` 의 이름
필터(`len(gn) <= 2`)에서 탈락하고, 그 함수의 **입력 열이 통째로 빈다**. 게이트는 그걸
`dropped_by_name_filter` 로 세고 있었는데(22건) 실제 원인이 유령이었다.

## 2. 파라미터 앞 설명 주석 — 멀쩡한 선언을 통째로 버렸다

LIN 스택은 파라미터마다 앞에 주석을 단다:

    void lin_lld_sci_rx_response(
        /* [IN] Length of response data expect to wait */
        l_u8 msg_length )

주석을 남기면 세 곳이 동시에 망가진다 — 타입 문자열 오염(이름 추출 실패) · 주석의 `/*`
를 포인터로 읽어 `(range: …)` 를 지어냄 · 주석 안 콤마에서 파라미터가 둘로 찢어짐.
실측 23개 unit 이 이 경로로 입력 0개였다.
"""
from __future__ import annotations

import pytest

from generators.suts import _extract_var_names, collect_unit_functions
from report_gen.function_analyzer import _parse_signature_params
from report_gen.uds_generator import generate_uds_source_sections

# ── 1. 유령 전역 ─────────────────────────────────────────────────────────────
_VER_C = (
    '#include "Vectors.h"\n'
    "static const volatile FirmwareVersionInfo_t g_FirmwareVersionInfo @0x00FF9DF0U = {\n"
    "    1, 2\n"
    "};\n"
    "U8 g_ReadsVersion( void )\n"
    "{\n"
    "    return g_FirmwareVersionInfo.major;\n"
    "}\n"
    "void g_UsesMacroOnly( void )\n"
    "{\n"
    "    u8s_Slot = VectorNumber_VReserved123;\n"
    "    return;\n"
    "}\n"
)
_VECTORS_H = "#define VectorNumber_VReserved123 123U\n#define MAX_SLOT 8U\n"


@pytest.fixture(scope="module")
def ver_project(tmp_path_factory):
    d = tmp_path_factory.mktemp("phantom_u")
    (d / "Vectors.h").write_text(_VECTORS_H, encoding="utf-8")
    (d / "SysOs_Main.c").write_text(_VER_C, encoding="utf-8")
    return generate_uds_source_sections(str(d), preprocess=False)


def _globals_of(project, fname):
    for info in (project.get("function_details") or {}).values():
        if isinstance(info, dict) and info.get("name") == fname:
            return list(info.get("globals_global") or []) + list(info.get("globals_static") or [])
    pytest.fail(f"{fname} 를 파싱하지 못했다 — 이 테스트의 전제가 깨졌다")


class TestPhantomGlobalU:
    def test_address_suffix_does_not_become_the_variable_name(self, ver_project):
        """`@0x00FF9DF0U` 의 `U` 가 이름이 되면 안 된다 — 진짜 이름이 나와야 한다."""
        gim = ver_project.get("globals_info_map") or {}
        assert "g_FirmwareVersionInfo" in gim, "주소 접미사가 진짜 이름을 먹었다"
        assert "U" not in gim, "정수 접미사 `U` 가 전역으로 등록됐다"

    def test_macro_with_integer_suffix_does_not_attach_a_one_letter_global(self, ver_project):
        """`123U` 의 `U` 를 식별자로 읽으면 그 매크로를 쓰는 함수 전부가 오염된다."""
        names = [str(g).split()[-1] for g in _globals_of(ver_project, "g_UsesMacroOnly")]
        assert "U" not in names, "매크로 확장형의 정수 접미사가 전역으로 붙었다"

    def test_the_real_global_is_still_attached(self, ver_project):
        """유령을 지우느라 진짜 전역을 잃으면 그게 더 큰 회귀다."""
        names = [str(g).split()[-1] for g in _globals_of(ver_project, "g_ReadsVersion")]
        assert any(n.startswith("g_FirmwareVersionInfo") for n in names), names


# ── 2. 파라미터 앞 주석 ──────────────────────────────────────────────────────
class TestParamLeadingComment:
    """생산자(`_parse_signature_params`) 수준 — 여기서 새면 모든 소비처가 오염된다."""

    def test_comment_does_not_reach_the_parameter_string(self):
        got = _parse_signature_params(
            "void lin_lld_sci_rx_response ( /* [IN] Length of response data */ l_u8 msg_length )"
        )
        assert got == ["l_u8 msg_length"], got

    def test_comma_inside_a_comment_does_not_split_the_parameter(self):
        """⚠ 주석 안 콤마에서 쪼개지면 파라미터 **하나가 둘**이 된다(실측)."""
        got = _parse_signature_params(
            "void f ( /* [IN] Error code, if positive = 0 */ l_u8 error_code )"
        )
        assert got == ["l_u8 error_code"], got

    def test_multiline_comment_between_parameters(self):
        got = _parse_signature_params(
            "void f (\n"
            "    /* [IN] first */\n"
            "    l_u8 a,\n"
            "    /* [OUT] second */\n"
            "    l_u8* b\n"
            ")"
        )
        assert got == ["l_u8 a", "l_u8* b"], got

    def test_line_comment_form(self):
        assert _parse_signature_params("void f ( // note\n l_u8 a )") == ["l_u8 a"]

    def test_plain_signature_is_unchanged(self):
        """주석 처리가 평범한 시그니처를 건드리면 회귀다."""
        assert _parse_signature_params("void f(U8 mode, const U8 * src)") == [
            "U8 mode",
            "const U8 * src",
        ]


class TestCommentedParamReachesInputColumn:
    """소비처 확인 — 여기서 빠지면 시퀀스에 넣을 값이 없다."""

    def test_input_column_gets_the_parameter(self):
        details = {
            "SwUFn_0101": {
                "id": "SwUFn_0101",
                "name": "lin_lld_sci_rx_response",
                "prototype": "void lin_lld_sci_rx_response(l_u8 msg_length)",
                "inputs": ["[IN] /* [IN] Length of response data */ l_u8 msg_length"],
                "outputs": [],
                "globals_global": [],
                "globals_static": [],
            }
        }
        units = collect_unit_functions(details, sds_map={})
        assert units[0]["input_vars"] == ["msg_length"], units[0]["input_vars"]

    def test_pointer_range_is_not_invented_from_the_comment_slashes(self):
        """`/*` 의 `*` 를 포인터로 읽으면 포인터가 아닌 값에 범위 근거가 생긴다."""
        got = _parse_signature_params("void f ( /* [IN] len */ l_u8 msg_length )")
        assert "*" not in got[0], got

    def test_names_survive_both_comment_and_nested_index_tail(self):
        raw = "[IN] /* [IN] part no */ U8 u8g_PartNo (idx: ( ( U8 )( 2U ) ), ( ( U8 )( 8U ) ))"
        assert _extract_var_names([raw]) == ["u8g_PartNo"]
