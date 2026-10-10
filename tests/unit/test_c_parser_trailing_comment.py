"""전역 선언의 설명이 **직전 선언의 것**이었다 — 꼬리 주석 귀속 가드.

## 무엇이 문제였나 (실측 2026-08-25, PDS64_RD + 정본 SUDS 대조로 발각)

`_extract_leading_comment` 는 선언 앞의 마지막 블록 주석을 가져온다. 그런데 MCU 헤더는
설명을 **선언 뒤 같은 줄**에 적는다:

    volatile PPSESTR REG_PPSE;   /* Port E Polarity Select Register; 0x268 */
    volatile PTTSTR  REG_PTT;    /* Port T Data Register; 0x2C0 */

`REG_PTT` 앞을 뒤로 훑으면 마지막 `*/` 는 **PPSE 의 것**이고, 그 뒤엔 공백뿐이라
"앞 주석" 으로 통과했다. 파일 전체가 한 칸씩 밀린다.

**실측**: 전역 선언 809개 중 **411개(50.8%)** 가 남의 설명을 달고 있었다. 정본 대조에서
`REG_PTT` → "Port E Polarity Select Register" 로 나와 발각됐다. 우리 desc 첫 토큰이
변수명과 맞는 비율 **36%**, 정본은 **82%** 였다.

⚠ 이건 값 부재보다 나쁘다. ISO 26262 설계서에 "이 레지스터는 X 다" 를 **틀리게**
적는 것이라, 빈 칸이면 하지 않았을 주장을 한다.

동시에 **자기** 꼬리 주석 425개는 통째로 버려지고 있었다 — 남의 것을 차단만 하면
분모가 비므로 자기 것을 되살린다. 수정 후 원문 대조 **408건 정합 100%**.

함수 쪽은 같은 함수를 쓰지만 영향이 작다(368개 중 정상 leading 353 유지 · 오배치 9만
차단 — `} /* end of l_ifc_init() */` 이 다음 함수 설명이 되던 것).
"""

from __future__ import annotations

import pytest

from tests.unit._source_probe import source_of
from workflow.code_parser import c_parser
from workflow.code_parser.c_parser import (
    _extract_global_decls,
    _extract_leading_comment,
    _extract_trailing_comment,
    _is_trailing_comment,
    _make_parser,
)

# 실제 헤더(MC9S12ZVL64MLF_PDS.c:124-125)의 모양을 그대로 옮긴 것.
_MCU_HEADER = """volatile PERESTR REG_PERE;                /* Port E Pull Device Enable Register; 0x00000266 */
volatile PPSESTR REG_PPSE;                /* Port E Polarity Select Register; 0x00000268 */
volatile PTTSTR REG_PTT;                  /* Port T Data Register; 0x000002C0 */
volatile PTITSTR REG_PTIT;                /* Port T Input Register; 0x000002C1 */
"""

# 앞 주석이 정상인 형태 — 이쪽은 **바뀌면 안 된다**.
_LEADING_STYLE = """/* Motor control state machine */
U8 u8g_MotorState;

/* Accumulated pulse count */
U16 u16g_PulseCount;
"""


def _globals(src: str):
    raw = src.encode("utf-8")
    parser = _make_parser()
    if parser is None:                             # tree_sitter 부재는 skip 이지 통과가 아니다
        pytest.skip("tree_sitter 파서를 만들 수 없다")
    tree = parser.parse(raw)
    return {g["name"]: (g.get("desc") or "").strip()
            for g in _extract_global_decls(tree.root_node, raw)}


class TestIsTrailingComment:
    """`/*` 앞에 같은 줄의 코드가 있는가 — 이 한 줄이 귀속을 가른다."""

    def test_code_before_the_comment_on_its_line_is_trailing(self):
        text = "volatile PPSESTR REG_PPSE;   /* Port E */\n"
        assert _is_trailing_comment(text, text.index("/*")) is True

    def test_comment_alone_on_its_line_is_leading(self):
        text = "U8 a;\n/* Motor state */\n"
        assert _is_trailing_comment(text, text.index("/*")) is False

    def test_indented_comment_alone_is_still_leading(self):
        text = "U8 a;\n    \t /* Motor state */\n"
        assert _is_trailing_comment(text, text.index("/*")) is False

    def test_comment_at_offset_zero_is_leading(self):
        """파일 첫 글자가 `/*` 면 앞 줄이 없다 — rfind 가 -1 을 내는 자리."""
        text = "/* File header */\nU8 a;\n"
        assert _is_trailing_comment(text, 0) is False


class TestExtractTrailingComment:
    def test_block_comment_on_the_same_line(self):
        src = b"U8 a;  /* Motor state */\nU8 b;\n"
        assert _extract_trailing_comment(src, src.index(b";") + 1) == "Motor state"

    def test_line_comment_on_the_same_line(self):
        src = b"U8 a;  // Motor state\nU8 b;\n"
        assert _extract_trailing_comment(src, src.index(b";") + 1) == "Motor state"

    def test_comment_on_the_next_line_is_not_taken(self):
        """다음 줄 주석은 그 다음 선언의 앞 주석이지 이 선언의 꼬리가 아니다."""
        src = b"U8 a;\n/* belongs to b */\nU8 b;\n"
        assert _extract_trailing_comment(src, src.index(b";") + 1) == ""

    def test_no_comment_returns_empty(self):
        src = b"U8 a;\nU8 b;\n"
        assert _extract_trailing_comment(src, src.index(b";") + 1) == ""

    def test_two_declarations_on_one_line_each_take_their_own(self):
        src = b"U8 a; /* first */ U8 b; /* second */\n"
        first_end = src.index(b";") + 1
        second_end = src.index(b";", first_end + 1) + 1
        assert _extract_trailing_comment(src, first_end) == "first"
        assert _extract_trailing_comment(src, second_end) == "second"

    def test_last_line_without_newline(self):
        src = b"U8 a;  /* Motor state */"
        assert _extract_trailing_comment(src, src.index(b";") + 1) == "Motor state"


class TestLeadingCommentRejectsSomeoneElsesTail:
    def test_previous_declarations_tail_is_not_a_leading_comment(self):
        """이 저장소가 411건을 잘못 붙이던 바로 그 모양."""
        src = _MCU_HEADER.encode("utf-8")
        start = src.index(b"volatile PTTSTR")
        assert _extract_leading_comment(src, start) == ""

    def test_a_real_leading_comment_is_still_returned(self):
        """⚠ 음성 대조군 — 차단이 정상 주석까지 먹으면 desc 가 통째로 사라진다."""
        src = _LEADING_STYLE.encode("utf-8")
        start = src.index(b"U8 u8g_MotorState")
        assert "Motor control state machine" in _extract_leading_comment(src, start)


class TestGlobalDescIsItsOwn:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("REG_PERE", "Port E Pull Device Enable Register; 0x00000266"),
            ("REG_PPSE", "Port E Polarity Select Register; 0x00000268"),
            ("REG_PTT", "Port T Data Register; 0x000002C0"),
            ("REG_PTIT", "Port T Input Register; 0x000002C1"),
        ],
    )
    def test_each_register_gets_its_own_description(self, name, expected):
        assert _globals(_MCU_HEADER).get(name) == expected

    def test_no_register_carries_a_neighbours_description(self):
        """관측량으로 단언한다 — 한 칸 밀림은 '이웃의 설명을 갖고 있음' 으로 나타난다."""
        got = _globals(_MCU_HEADER)
        order = ["REG_PERE", "REG_PPSE", "REG_PTT", "REG_PTIT"]
        for i in range(1, len(order)):
            assert got[order[i]] != got[order[i - 1]], f"{order[i]} 가 앞 선언 설명을 받았다"
        # 밀림이면 PTT 가 PPSE 의 문구를 갖는다 — 그 구체 사례를 직접 막는다.
        assert "Polarity Select" not in got["REG_PTT"]

    def test_leading_style_still_populates_desc(self):
        """앞 주석 스타일은 그대로 동작해야 한다(꼬리 우선이 앞을 죽이면 안 된다)."""
        got = _globals(_LEADING_STYLE)
        assert "Motor control state machine" in got.get("u8g_MotorState", "")
        assert "Accumulated pulse count" in got.get("u16g_PulseCount", "")

    def test_own_tail_wins_over_a_leading_comment(self):
        """둘 다 있으면 자기 줄의 것이 권위다."""
        src = "/* stale banner */\nU8 u8g_State;  /* Motor state */\n"
        assert _globals(src).get("u8g_State") == "Motor state"


class TestFunctionCommentsUnaffected:
    def test_end_of_previous_function_is_not_the_next_functions_description(self):
        src = (
            "void foo(void)\n{\n    return;\n} /* end of foo() */\n"
            "void bar(void)\n{\n    return;\n}\n"
        )
        raw = src.encode("utf-8")
        assert _extract_leading_comment(raw, src.index("void bar")) == ""

    def test_doxygen_block_above_a_function_still_attaches(self):
        src = "/**\n * @brief Initialise the motor\n */\nvoid foo(void)\n{\n}\n"
        raw = src.encode("utf-8")
        got = _extract_leading_comment(raw, src.index("void foo"))
        assert "Initialise the motor" in got


class TestCallSitesStayInSync:
    def test_global_decls_prefer_the_trailing_comment(self):
        """호출부가 꼬리 우선을 잃으면 411건이 사라지기만 하고 되살아나지 않는다."""
        body = source_of(_extract_global_decls)
        assert "_extract_trailing_comment(src, node.end_byte)" in body, \
            "전역 선언이 자기 꼬리 주석을 먼저 보지 않는다"
        assert body.index("_extract_trailing_comment") < body.index("_extract_leading_comment"), \
            "꼬리보다 앞 주석을 먼저 보면 남의 설명이 다시 이긴다"

    def test_module_exposes_both_helpers(self):
        assert callable(getattr(c_parser, "_is_trailing_comment", None))
        assert callable(getattr(c_parser, "_extract_trailing_comment", None))
