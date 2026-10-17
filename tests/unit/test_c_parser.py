"""C 파서 — **주석 안에서 함수를 만들어내지 않는지**가 이 파일의 본체다.

## 무엇이 문제였나 (실측 2026-08-12, KJPDS02)

Processor Expert 가 만든 `Generated_Code/*.c` 는 매크로로 구현된 접근자의 프로토타입을
**주석 안에** 남긴다:

    /*
    bool PS3_MOTOR_NSCS_GetVal(void)

    **  This method is implemented as a macro. See PS3_MOTOR_NSCS.h file.  **
    */

tree-sitter 는 이 파일을 "함수 0개" 로 **정확히** 읽는다. 그런데 호출부의 `if not funcs:`
가 그걸 "파싱 실패" 로 보고 정규식 폴백을 돌렸고, 그 정규식이 주석을 훑어 **없는 함수를
만들어냈다**. 파라미터 `[^;]*?` 가 주석 경계를 넘어 다음 함수의 `{` 까지 먹어 시그니처가
통째로 오염되기까지 했다:

    '[IN] void) ** This method is implemented as a macro. … // if (Val == (U8) TRUE'

**정본 SUTS 에는 이 접근자들이 하나도 없다**(`_GetVal/_PutVal/_SetVal/_ClrVal` 계열 6건뿐이고
그중 이 이름들은 없다). 즉 존재하지 않는 함수의 시험 케이스를 생성하고 있었다 — 빠뜨린
것보다 나쁘다. 없는 것을 시험하라고 문서에 적기 때문이다.

⚠ 가리기는 **길이를 유지해야** 한다. 통째로 지우면 바이트 오프셋이 밀려
  `_extract_leading_comment(text_bytes, start_byte)` 가 엉뚱한 자리를 읽는다.
"""
from __future__ import annotations

import pytest

from report_gen.source_parser import _extract_c_definitions
from workflow.code_parser.c_parser import (
    _extract_function_defs_regex_fallback,
    blank_c_comments,
    c_identifiers,
)

# 실제 `Generated_Code/PS3_MOTOR_NSCS.c` 의 구조를 줄인 것
_PE_ACCESSOR_SRC = """\
/*
** ===================================================================
**     Method      :  PS3_MOTOR_NSCS_GetVal (component BitIO)
**     Returns     :  Input value
** ===================================================================
*/
/*
bool PS3_MOTOR_NSCS_GetVal(void)

**  This method is implemented as a macro. See PS3_MOTOR_NSCS.h file.  **
*/

// void PS3_MOTOR_NSCS_PutVal(bool Val)
// {
//   if (Val == (byte)TRUE) { setReg8Bits(PTS, (byte)0x08U); }
// }

/** 실제 함수의 설명이다. */
void PS3_MOTOR_NSCS_Init(void)
{
    u8s_Ready = 1U;
}
"""


class TestBlankCComments:
    def test_length_and_line_count_are_preserved(self):
        """⚠ 길이가 바뀌면 오프셋 기반 추출이 다른 자리를 읽는다."""
        src = "int a;\n/* 주석\n여러 줄 */\nint b;  // 끝\n"
        out = blank_c_comments(src)
        assert len(out) == len(src)
        assert out.count("\n") == src.count("\n")

    def test_comment_bodies_become_blanks_but_code_survives(self):
        out = blank_c_comments("int a; /* void f(void) */ int b;")
        assert "void f" not in out
        assert "int a;" in out and "int b;" in out

    def test_line_comments_are_blanked_too(self):
        """⚠ 이 이름의 함수는 `//` 도 지워야 한다.

        지금의 두 정의 추출 정규식은 `^[\\t ]*` 로 줄머리에 고정돼 있어 `//` 주석만으로는
        유령이 안 생긴다 — 즉 이 축은 **추출기 수준에서는 관측되지 않는다**. 그래도
        `blank_c_comments` 는 이름대로 동작해야 다음 호출자가 함정에 안 빠지므로,
        유틸리티 수준에서 직접 고정한다.
        """
        out = blank_c_comments("int a;  // void f(void) {\nint b;\n")
        assert "void f" not in out
        assert "int a;" in out and "int b;" in out

    def test_empty_input(self):
        assert blank_c_comments("") == ""


class TestCIdentifiers:
    """정수 리터럴의 접미사를 식별자로 내놓지 않는지.

    ⚠ 이 한 글자가 실제로 **324개 함수**를 오염시켰다 — `#define X 123U` 의 `U` 가
      전역 이름으로 잡혀 그 매크로를 쓰는 모든 함수에 붙었다. 상세는
      `tests/unit/test_phantom_inputs.py` 모듈 docstring.
    """

    @pytest.mark.parametrize(
        "src,expected",
        [
            ("123U", []),
            ("0x1FUL", []),
            ("0x00FF9DF0U", []),
            ("42", []),
            ("( ( U8 )( 2U ) )", ["U8"]),
            ("#define VectorNumber_VReserved123 123U", ["define", "VectorNumber_VReserved123"]),
            ("_PTT.Bits.PTT3", ["_PTT", "Bits", "PTT3"]),
            ("u8s_Buf[10U] = 0U;", ["u8s_Buf"]),
            ("", []),
        ],
    )
    def test_suffix_is_not_an_identifier(self, src, expected):
        assert c_identifiers(src) == expected


class TestPhantomFunctionsFromComments:
    @pytest.mark.parametrize(
        "extract",
        [
            pytest.param(
                lambda s: [f.name for f in _extract_function_defs_regex_fallback(s, "x.c", set())],
                id="c_parser-regex-fallback",
            ),
            pytest.param(
                lambda s: [n for n, *_ in _extract_c_definitions(s)],
                id="source_parser-definitions",
            ),
        ],
    )
    def test_commented_out_prototype_is_not_a_function(self, extract):
        """두 파서 **모두** 지켜야 한다 — 한쪽만 고치면 다른 경로로 유령이 들어온다."""
        names = extract(_PE_ACCESSOR_SRC)
        assert "PS3_MOTOR_NSCS_GetVal" not in names, "블록 주석 안의 프로토타입"
        assert "PS3_MOTOR_NSCS_PutVal" not in names, "`//` 로 주석 처리된 정의"

    @pytest.mark.parametrize(
        "extract",
        [
            pytest.param(
                lambda s: [f.name for f in _extract_function_defs_regex_fallback(s, "x.c", set())],
                id="c_parser-regex-fallback",
            ),
            pytest.param(
                lambda s: [n for n, *_ in _extract_c_definitions(s)],
                id="source_parser-definitions",
            ),
        ],
    )
    def test_real_function_is_still_found(self, extract):
        """주석을 가리느라 진짜 함수를 잃으면 그게 더 큰 회귀다."""
        assert "PS3_MOTOR_NSCS_Init" in extract(_PE_ACCESSOR_SRC)

    def test_signature_is_not_contaminated_across_comment_boundary(self):
        """파라미터 `[^;]*?` 가 주석 경계를 넘어 다음 `{` 까지 먹던 것."""
        fns = _extract_function_defs_regex_fallback(_PE_ACCESSOR_SRC, "x.c", set())
        init = next(f for f in fns if f.name == "PS3_MOTOR_NSCS_Init")
        assert "macro" not in init.signature and "**" not in init.signature

    def test_leading_comment_is_still_read_from_the_original_text(self):
        """⚠ 오프셋 보존 확인 — 가린 텍스트로 주석을 읽으면 설명이 공백이 된다."""
        fns = _extract_function_defs_regex_fallback(_PE_ACCESSOR_SRC, "x.c", set())
        init = next(f for f in fns if f.name == "PS3_MOTOR_NSCS_Init")
        assert "실제 함수의 설명" in (init.comment_desc or ""), \
            "주석을 가린 텍스트에서 설명을 뽑으면 안 된다(원문에서 뽑아야 한다)"
