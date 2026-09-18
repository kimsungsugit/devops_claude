"""익명 집합체 변수가 **존재하지 않는 이름**으로 설계서에 실리던 것 — 귀속 가드.

## 무엇이 문제였나 (실측 2026-08-26, PDS64_RD + 정본 SUDS 대조)

    static enum
    {
        en_s_Buzzer_Stop            = 0x01U,
        en_s_Buzzer_2_Flashing      = 0x02U
    }   s_BuzzerState;

`_find_ident` 는 깊이우선이라 **타입 자리까지** 판다. 그래서 첫 열거자
`en_s_Buzzer_Stop` 을 변수명으로 집어냈고, 진짜 변수 `s_BuzzerState` 는 파서 목록에서
통째로 사라졌다. 결과는 두 겹이다:

1. 설계서에 **존재하지 않는 정적 변수** `en_s_Buzzer_Stop` 이 실린다.
2. 사라진 `s_BuzzerState` 는 폴백 `_infer_type_from_file` 로 타입을 구하는데, 그 정규식은
   '선언' 개념이 없어 닫는 줄 `}   s_BuzzerState;` 에서 타입을 `}` 로 만들어 냈다.

**실측**: 전역/정적 선언 809개 중 2개(`s_BuzzerState`·`s_MotorState`)가 이 모양이고,
산출물 Type 칸 2,406개 중 **24개**가 `enum }` 또는 열거자 본문이었다. 정본 2,751칸 중
중괄호 포함은 **0개**다.

⚠ 값 부재보다 나쁘다 — 빈 칸이면 하지 않았을 주장("이런 변수가 있다")을 틀리게 한다.
"""

from __future__ import annotations

import pytest

from report_gen.utils import _infer_type_from_decl, _infer_type_from_file, _is_type_head
from workflow.code_parser.c_parser import (
    _decl_ident,
    _extract_global_decls,
    _extract_globals,
    _make_parser,
    _normalize_type_text,
)

_ANON_ENUM = """static enum
{
    en_s_Buzzer_Stop            = 0x01U,
    en_s_Buzzer_2_Flashing      = 0x02U,
    en_s_Buzzer_3_Flashing      = 0x03U

}   s_BuzzerState;

static U8 u8s_BuzzerActCnt;
"""


def _parse(src: str):
    parser = _make_parser()
    if parser is None:  # tree_sitter 부재는 skip 이지 통과가 아니다
        pytest.skip("tree_sitter 파서를 만들 수 없다")
    raw = src.encode("utf-8")
    return parser.parse(raw).root_node, raw


def _first_declaration(src: str):
    root, raw = _parse(src)
    for node in root.children:
        if node.type == "declaration":
            return node, raw
    pytest.fail(f"declaration 노드를 못 찾았다: {src!r}")


class TestDeclIdentSkipsTheTypeSlot:
    def test_anonymous_enum_yields_the_variable_not_the_first_enumerator(self):
        """이 저장소가 2건을 잘못 붙이던 바로 그 모양."""
        node, _raw = _first_declaration(_ANON_ENUM)
        assert _decl_ident(node) == "s_BuzzerState"

    @pytest.mark.parametrize(
        "code,expected",
        [
            ("U8 u8g_A;", "u8g_A"),
            ("static U8 u8s_B;", "u8s_B"),
            ("extern U16 u16g_C;", "u16g_C"),
            ("U8 *pu8g_D;", "pu8g_D"),
            ("U8 u8g_E[10];", "u8g_E"),
            ("volatile PTTSTR REG_PTT;", "REG_PTT"),
            ("enum en_g_State g_DoorState;", "g_DoorState"),
            ("struct _tagStartup _startupData;", "_startupData"),
            ("static U8 u8s_F = 3;", "u8s_F"),
            ("static const U8 u8s_I[2] = {1, 2};", "u8s_I"),
            ("static struct { U8 a; U8 b; } s_Rec;", "s_Rec"),
        ],
    )
    def test_ordinary_shapes_are_unchanged(self, code, expected):
        """⚠ 음성 대조군 — 타입 자리를 건너뛰다 정상 선언까지 먹으면 전역이 통째로 사라진다."""
        node, _raw = _first_declaration(code)
        assert _decl_ident(node) == expected

    @pytest.mark.parametrize(
        "code",
        [
            # ⚠ `static`/`extern` 이 붙으면 tree-sitter 는 이것을 **declaration 으로** 만든다
            #   (선언자는 없다). 접두사 없는 `enum { … };` 은 enum_specifier 라 여기 안 온다.
            "static enum { en_X = 1, en_Y = 2 };",
            "extern enum { en_X = 1, en_Y = 2 };",
        ],
    )
    def test_a_declaration_without_a_declarator_names_nothing(self, code):
        """변수를 선언하지 않은 선언은 이름이 없다 — 열거자로 메우면 유령이 생긴다."""
        node, _raw = _first_declaration(code)
        assert _decl_ident(node) == ""

    def test_a_type_definition_without_a_variable_declares_nothing(self):
        root, raw = _parse("static enum { en_X = 1, en_Y = 2 };")
        names = [g["name"] for g in _extract_global_decls(root, raw)]
        assert "en_X" not in names and "en_Y" not in names


class TestNormalizeTypeText:
    @pytest.mark.parametrize(
        "raw_type,expected",
        [
            ("enum\n{\n  en_s_Stop = 0x01U\n}", "enum"),
            ("enum en_g_State { A = 1 }", "enum en_g_State"),
            ("struct { U8 a; }", "struct"),
            ("union { U8 a; U16 b; }", "union"),
        ],
    )
    def test_bodies_collapse_to_the_tag_form(self, raw_type, expected):
        assert _normalize_type_text(raw_type) == expected

    @pytest.mark.parametrize(
        "raw_type",
        ["U8", "U16", "PTTSTR", "enum en_g_DoorState", "struct _tagStartup", "unsigned char"],
    )
    def test_real_type_names_are_left_alone(self, raw_type):
        """⚠ 음성 대조군 — 정상 타입을 줄이면 805칸이 뭉개진다."""
        assert _normalize_type_text(raw_type) == raw_type

    def test_whitespace_is_folded_but_content_kept(self):
        assert _normalize_type_text("  struct   _tagStartup  ") == "struct _tagStartup"


class TestGlobalDeclsCarryTheirOwnIdentity:
    def test_the_real_variable_is_present_and_the_enumerator_is_not(self):
        root, raw = _parse(_ANON_ENUM)
        by_name = {g["name"]: g for g in _extract_global_decls(root, raw)}
        assert "s_BuzzerState" in by_name, "진짜 변수가 목록에서 빠졌다"
        assert "en_s_Buzzer_Stop" not in by_name, "열거자가 변수로 실렸다"

    def test_the_type_cell_is_a_type_name_not_a_definition(self):
        root, raw = _parse(_ANON_ENUM)
        by_name = {g["name"]: g for g in _extract_global_decls(root, raw)}
        gtype = by_name["s_BuzzerState"]["type"]
        assert gtype == "enum"
        assert "{" not in gtype and "}" not in gtype

    def test_neighbouring_declarations_are_unaffected(self):
        """⚠ 음성 대조군 — 같은 파일의 평범한 정적 변수는 그대로여야 한다."""
        root, raw = _parse(_ANON_ENUM)
        by_name = {g["name"]: g for g in _extract_global_decls(root, raw)}
        assert by_name["u8s_BuzzerActCnt"]["type"] == "U8"
        assert by_name["u8s_BuzzerActCnt"]["is_static"] == "true"

    def test_name_only_extractor_stays_in_sync(self):
        """`_extract_globals` 도 같은 판정을 써야 한다 — 한쪽만 고치면 두 목록이 갈린다."""
        root, raw = _parse(_ANON_ENUM)
        names = _extract_globals(root, raw)
        assert "s_BuzzerState" in names
        assert "en_s_Buzzer_Stop" not in names


class TestDeclarationRangeRegexIsAlive:
    """`r"...\\\\d..."` 는 정규식에서 **리터럴 백슬래시**라 영구 미매치였다.

    ⚠ PDS64_RD 에서는 고쳐도 **0건**이다 — 이 소스는 선언문 안에 범위를 적지 않는다
      (`~` 를 품은 전역 선언 0개 · 꼬리 주석 425개 중 `a ~ b` 포함 0개).
      회수가 아니라 **침묵하던 경로의 복구**다. 없는 회수를 있다고 적지 않기 위해 명시한다.
    """

    @pytest.mark.parametrize(
        "code",
        [
            "U8 /* 0x00 ~ 0x0F */ u8g_Level;",
            "U8 u8g_Level /* 0x00 ~ 0x0F */;",
        ],
    )
    def test_a_range_inside_the_declaration_is_recovered(self, code):
        root, raw = _parse(code)
        got = _extract_global_decls(root, raw)[0]
        assert got["range"] == "0x00 ~ 0x0F"
        assert got["range_source"] == "decl"

    def test_decimal_ranges_too(self):
        root, raw = _parse("U8 u8g_Level = 0 /* 0 ~ 15 */;")
        got = _extract_global_decls(root, raw)[0]
        assert (got["range"], got["range_source"]) == ("0 ~ 15", "decl")

    def test_a_declaration_without_a_range_stays_empty(self):
        """⚠ 음성 대조군 — 항상 범위를 만들어 내면 지표가 거짓으로 오른다."""
        root, raw = _parse("U8 u8g_Level;")
        got = _extract_global_decls(root, raw)[0]
        assert got["range"] == "" and got["range_source"] == ""

    def test_a_comment_range_still_wins_over_the_declaration(self):
        root, raw = _parse("U8 u8g_Level;  /* Range: 0x00 ~ 0x0F */")
        got = _extract_global_decls(root, raw)[0]
        assert got["range_source"] == "comment"

    def test_the_comment_wins_even_when_the_declaration_also_carries_a_range(self):
        """둘 다 있을 때가 우선순위의 **유일한 관측 지점**이다.

        한쪽만 있는 사례로는 순서를 뒤집어도 결과가 같아 시험이 아무것도 안 막는다.
        주석은 사람이 적은 설계 의도라 선언문에서 긁은 숫자보다 권위가 높다.
        """
        root, raw = _parse("U8 /* 0 ~ 3 */ u8g_Level;  /* Range: 0x00 ~ 0x0F */")
        got = _extract_global_decls(root, raw)[0]
        assert (got["range"], got["range_source"]) == ("0x00 ~ 0x0F", "comment")


class TestTypeHeadFallback:
    @pytest.mark.parametrize(
        "text",
        ["U8", "U16", "PTTSTR", "unsigned char", "struct _tagStartup", "enum en_g_State", "U8 *"],
    )
    def test_real_type_heads_are_accepted(self, text):
        """⚠ 음성 대조군 — 여기가 좁아지면 807개 전역이 타입 없이 버려진다."""
        assert _is_type_head(text) is True

    @pytest.mark.parametrize(
        "text",
        ["}", "{", "s_BuzzerState =", "enum { en_s_Stop = 0x01U }", "if (a == b)", ""],
    )
    def test_non_declaration_heads_are_rejected(self, text):
        assert _is_type_head(text) is False

    def test_closing_brace_line_is_not_a_type(self):
        assert _infer_type_from_decl("}   s_BuzzerState;", "s_BuzzerState") == ""

    def test_an_ordinary_declaration_still_resolves(self):
        """⚠ 음성 대조군."""
        assert _infer_type_from_decl("static U8 u8s_Cnt;", "u8s_Cnt") == "U8"

    def test_file_fallback_skips_the_closing_brace_and_keeps_scanning(self, tmp_path):
        """앞줄이 모양 아니어도 **뒤에 진짜 선언이 있으면** 찾아야 한다."""
        src = tmp_path / "x.c"
        src.write_text(
            "static enum\n{\n    en_s_Stop = 0x01U\n}   s_State;\n"
            "\nstatic U8 s_State2;\n",
            encoding="utf-8",
        )
        assert _infer_type_from_file(str(src), "s_State") == ("", "")
        assert _infer_type_from_file(str(src), "s_State2") == ("U8", "")

    def test_a_bad_shaped_first_match_does_not_abort_the_scan(self, tmp_path):
        """⚠ 모양 불량에서 **중단**하면 뒤에 있는 진짜 선언을 못 본다.

        앞 후보가 유효할 때만 시험하면 '건너뛴다' 와 '멈춘다' 가 구분되지 않는다.
        """
        src = tmp_path / "z.c"
        src.write_text(
            "static U8 u8s_Copy = s_Cnt;\n\nstatic U8 s_Cnt;\n", encoding="utf-8"
        )
        assert _infer_type_from_file(str(src), "s_Cnt") == ("U8", "")

    def test_file_fallback_does_not_read_an_assignment_as_a_declaration(self):
        """`s_State = en_s_Stop;` 은 선언이 아니다 — 타입을 만들어 내면 안 된다."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "y.c"
            src.write_text("void f(void)\n{\n    s_State = en_s_Stop;\n}\n", encoding="utf-8")
            assert _infer_type_from_file(str(src), "en_s_Stop") == ("", "")
