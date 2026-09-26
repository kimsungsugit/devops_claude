"""(R61 N63) 문서 주석 → 함수 짝짓기와 함수 본문 추출은 **선형**이고, 남의 것을 붙이지 않는다.

R60 라이브에서 소스 분석 단계마다 4.2~4.5초 백엔드 정지가 남아 있었다(2초 keep-alive 폴러가 ConnectionError).
주인은 `report_gen.source_parser` 의 정규식 둘이었다 — `re` 는 매칭 중 GIL 을 놓지 않는다.

1. `_extract_doxygen_asil_tags` — `/**(.*?)*/ <머리>` 를 `re.S` 로 걸어, 주석 뒤에 함수가 없으면 `.*?` 가 **다음 주석들을
   넘어** 머리가 나올 때까지 늘어났다. 함수가 없는 레지스터 헤더(670KB) 두 개에서 3.59초·2.57초.
   같은 기전이 오귀속도 만들었다: 파일 머리말의 `@brief`/`@asil` 이 첫 함수의 것이 된다(실측 KJPDS02 31건).
   ⚠ 단순히 "바로 앞 주석만" 으로 좁히면 Freescale LIN 양식(`/** … *//*END*---*/` 뒤에 함수)의 맞는 귀속 82건을 잃는다 —
     옛 정규식은 경계를 넘는 부작용으로 그걸 **우연히** 맞히고 있었다. 그래서 규칙은 "문서 주석 뒤 공백과 **주인 아닌 주석**
     (일반 주석·`/**<`·태그 없는 `/**`)만 건너뛴다" — 태그 없는 `/**` 구분선이 짝을 끊으면 `@asil` 이 말없이 사라진다(리뷰 W2).
2. `_extract_c_function_bodies` — R59 가 `c_parser` 에서 걷어낸 O(n³) 정규식의 **사본**. 주석 제거본 `Vectors.c`(17.9KB)에
   1.60초. 사본이 넷 더 있었다(`report/c_parsing.py` 의 프로토타입·정의·본문, `ast_parser.py`) — 그중 정의·본문은
   SUTS/SITS 경량 폴백으로 프로덕션에서 닿아 함께 고쳤고, 나머지 둘은 호출자 0 이라 목록으로 묶어 뒀다(맨 아래 가드).
   옛 규칙은 `if( f(x) == ON ) {` 의 호출을 정의로 읽었고, 같은 이름은 뒤엣것이 남으므로 **진짜 본문이 if 블록으로
   덮였다**(실측 KJPDS02 12개 함수).

⚠ 두 결함 모두 라이브 문서에는 닿지 않았다(tree-sitter 경로가 값을 덮는다 — 두 프로젝트의 최종 섹션 diff 0).
  닿는 것은 정지(4초)와, tree-sitter 가 없는 폴백 경로의 산출이다.
"""
from __future__ import annotations

import ast
import functools
import re
import time
from pathlib import Path

import pytest

from report import c_parsing as twin
from report_gen import source_parser as sp

REPO = Path(__file__).resolve().parents[2]

# 옛 정규식 — 대조군(오라클). 주석 경계를 넘지 않는 입력에선 새 스캐너와 같은 답을 내야 한다.
_OLD_DOX = re.compile(
    r"/\*\*(.*?)\*/\s*"
    r"(?:static\s+)?[A-Za-z_][\w\s\*]*?\s+([A-Za-z_]\w*)\s*\(",
    flags=re.S,
)


def _old_pairs(text):
    return [(m.group(2), m.group(1)) for m in _OLD_DOX.finditer(text)]


def _new_pairs(text):
    return list(sp._iter_doc_comment_heads(text))


class TestDocCommentBelongsToTheNextFunction:
    def test_adjacent_comment_gives_its_tags(self):
        text = "/**\n * @brief Init motor\n * @asil B\n */\nstatic void Motor_Init(void) {\n}\n"
        assert sp._extract_doxygen_asil_tags(text) == {"Motor_Init": {"asil": "B", "brief": "Init motor"}}

    def test_file_header_does_not_overwrite_the_functions_own_comment(self):
        text = (
            "/** @file lin.c\n * @brief LIN low level functions\n * @asil D\n */\n"
            "#include \"lin.h\"\n"
            "/** @brief Initialize the interface\n * @asil A\n */\n"
            "void lin_lld_init(void) {\n}\n"
        )
        # 옛 결과: {'asil': 'D', 'brief': 'LIN low level functions'} — 머리말이 함수의 자기 주석을 덮었다.
        assert sp._extract_doxygen_asil_tags(text) == {
            "lin_lld_init": {"asil": "A", "brief": "Initialize the interface"}
        }

    def test_file_header_is_not_lent_to_an_uncommented_function(self):
        text = (
            "/** @file cfg.c\n * @brief Common LIN configuration\n * @asil D\n */\n"
            "#include \"cfg.h\"\n"
            "int counter;\n"
            "/* callout */\n"
            "void ld_read_by_id_callout(void) {\n}\n"
        )
        # 옛 규칙은 뒤따르는 주석의 `*/` 까지 늘어나 머리말을 이 함수에 붙였다(`@asil D` 가 첫 함수 하나의 것이 된다).
        assert [n for n, _b in _old_pairs(text)] == ["ld_read_by_id_callout"]
        assert "@asil D" in _old_pairs(text)[0][1]
        assert sp._extract_doxygen_asil_tags(text) == {}
        # 파일 수준 ASIL 은 제 통로로 간다 — 첫 함수 하나가 아니라 파일의 모든 함수에.
        assert sp._extract_file_header_asil(text) == "D"

    def test_plain_comment_between_doc_comment_and_function_is_skipped(self):
        # Freescale LIN 양식 — 실측 lin_lld_sci.h. "바로 앞 주석만" 으로 좁히면 이 귀속을 잃는다.
        text = (
            "/*FUNCTION*----------------------------------*//**\n"
            "* @fn void lin_goto_idle_state()\n"
            "* @brief Enter IDLE state\n"
            "*//*END*--------------------------------------*/\n"
            "void lin_goto_idle_state(void);\n"
        )
        assert sp._extract_doxygen_asil_tags(text) == {"lin_goto_idle_state": {"brief": "Enter IDLE state"}}

    def test_line_comment_between_is_skipped(self):
        text = "/** @asil C */\n// legacy name kept\n   // second line\nU8 f(void) {\n}\n"
        assert sp._extract_doxygen_asil_tags(text) == {"f": {"asil": "C"}}

    def test_nearer_tagged_doc_comment_owns_the_function(self):
        text = "/** @asil D\n * @brief far */\n/** @brief near */\nvoid g(void) {\n}\n"
        assert sp._extract_doxygen_asil_tags(text) == {"g": {"brief": "near"}}

    @pytest.mark.parametrize(
        "between",
        ["/*** Local functions ***/", "/**@{*/", "/******************/", "/** plain words, no tags */", "/**/"],
    )
    def test_tagless_doc_comment_between_does_not_silently_drop_the_asil(self, between):
        # 리뷰 W2 — 구분선·그룹 마커도 `/**` 로 시작한다. 그게 짝을 끊으면 `@asil D` 가 말없이 사라진다(과소보고).
        text = f"/** @asil D */\n{between}\nvoid g(void) {{\n}}\n"
        assert sp._extract_doxygen_asil_tags(text) == {"g": {"asil": "D"}}

    def test_trailing_member_doc_is_never_an_owner(self):
        # `/**< …` 는 **앞** 멤버의 문서다 — 다음 함수의 것이 아니고, 사이에 끼어도 짝을 끊지 않는다.
        assert sp._extract_doxygen_asil_tags("int x; /**< @asil D counter */\nvoid f(void) {\n}\n") == {}
        text = "/** @asil B */\nint dummy_never_here; /**< @asil D */\nvoid f(void) {\n}\n"
        assert sp._extract_doxygen_asil_tags(text) == {}          # 코드가 끼면 끊긴다
        text = "/** @asil B */ /**< @asil D stray */\nvoid f(void) {\n}\n"
        assert sp._extract_doxygen_asil_tags(text) == {"f": {"asil": "B"}}

    def test_preprocessor_line_between_breaks_the_pair(self):
        # 재 보니 전처리 줄을 건너뛰면 더해지는 7건 중 5건이 오귀속(머리말 → `#include` → 첫 프로토타입)이었다.
        text = "/** @brief Erase flash */\n#pragma CODE_SEG SHADOW_ROM\nvoid PFLASH_Send_Command(void);\n"
        assert sp._extract_doxygen_asil_tags(text) == {}

    def test_code_between_breaks_the_pair(self):
        text = "/** @asil D */\nint x;\nvoid h(void) {\n}\n"
        assert sp._extract_doxygen_asil_tags(text) == {}

    def test_empty_comment_is_closed_by_its_own_slash(self):
        # `/**/` 는 빈 주석이다. 닫는 `*/` 를 `/**` 뒤에서만 찾으면 다음 주석의 끝까지 삼킨다.
        assert _new_pairs("/**/ void g(void) {}") == [("g", "")]

    def test_unterminated_comment_ends_the_scan(self):
        assert sp._extract_doxygen_asil_tags("/** @asil D \n void f(void) {") == {}

    def test_unterminated_plain_comment_in_the_gap_ends_the_scan(self):
        assert sp._extract_doxygen_asil_tags("/** @asil D */ /* never closed \n void f(void) {") == {}

    def test_same_name_later_comment_wins_and_tagless_comment_does_not_erase(self):
        text = (
            "/** @asil A */\nvoid f(void);\n"
            "/** @asil B */\nvoid f(void) {\n}\n"
            "/** nothing here */\nvoid f(void);\n"
        )
        assert sp._extract_doxygen_asil_tags(text) == {"f": {"asil": "B"}}

    def test_scan_resumes_after_the_matched_head(self):
        text = "/** @asil A */ void a(void); /** @asil B */ void b(void);"
        assert sp._extract_doxygen_asil_tags(text) == {"a": {"asil": "A"}, "b": {"asil": "B"}}

    def test_all_tag_kinds_survive(self):
        text = (
            "/**\n * @brief Door close\n * @safety ASIL-D rated path\n"
            " * @requirement SwTR_012\n * @req SwFn_7\n */\nvoid Door_Close(void) {\n}\n"
        )
        assert sp._extract_doxygen_asil_tags(text) == {
            "Door_Close": {
                "asil": "D",
                "safety": "ASIL-D rated path",
                "requirement": "SwTR_012, SwFn_7",
                "brief": "Door close",
            }
        }


_AGREE_SAMPLES = [
    "/** @asil B */\nvoid a(void) {\n}\n",
    "/** @brief x */ static U8 b(U8 v) { return v; }\n/** @brief y */\nextern  void   c ( void );\n",
    "/** one */\n\n\n   unsigned long * d(void);\nint z;\n/** two */ const char * e(int a,\n int b) {\n}\n",
    "int only_code(void) { return 0; }\n",
    "/** @asil QM */\r\nvoid crlf(void)\r\n{\r\n}\r\n",
]


class TestAgreesWithOldRegexWhereItDidNotCrossComments:
    @pytest.mark.parametrize("text", _AGREE_SAMPLES)
    def test_same_pairs(self, text):
        old = _old_pairs(text)
        assert all("*/" not in body for _n, body in old)     # 시료 자체가 경계를 넘지 않는다는 전제
        assert _new_pairs(text) == old

    def test_samples_are_not_vacuous(self):
        assert sum(len(_old_pairs(t)) for t in _AGREE_SAMPLES) >= 6


class _HeadMeter:
    """`_DOX_HEAD_PAT.match` 호출 수 — 문서 주석 하나에 한 번이어야 한다(시간 비율이 아니라 횟수로 단언)."""

    def __init__(self, pat):
        self._pat = pat
        self.calls = 0

    def match(self, text, pos=0):
        self.calls += 1
        return self._pat.match(text, pos)


class TestLinearOnRegisterHeaders:
    @staticmethod
    def _register_header(n: int) -> str:
        return "".join(
            f"/*** REG{i} - Register {i}; 0x{i:08X} ***/\n#define REG{i}_MASK {i}U\ntypedef union {{ byte B; }} REG{i}STR;\n"
            for i in range(n)
        )

    def test_head_is_tried_once_per_doc_comment(self, monkeypatch):
        meter = _HeadMeter(sp._DOX_HEAD_PAT)
        monkeypatch.setattr(sp, "_DOX_HEAD_PAT", meter)
        text = self._register_header(4000)
        assert sp._extract_doxygen_asil_tags(text) == {}
        assert meter.calls == 4000

    def test_register_header_finishes_in_bounded_time(self):
        text = self._register_header(20000)      # ≈1.6MB — 실물(670KB, 옛 정규식 3.6초)의 2.4배
        st = time.perf_counter()
        assert sp._extract_doxygen_asil_tags(text) == {}
        assert time.perf_counter() - st < 2.0

    def test_long_blank_run_after_a_type_word_is_capped(self):
        # 접두 상한이 없으면 lazy 확장 × `\s+` 되물림으로 공백 길이의 제곱.
        text = "/** c */ x" + " " * 50000 + ";\n"
        st = time.perf_counter()
        assert sp._extract_doxygen_asil_tags(text) == {}
        assert time.perf_counter() - st < 2.0

    def test_blank_runs_are_capped_at_every_position(self):
        # 리뷰 I3 — 접두만 묶으면 `\s+`·`\s*` 가 lazy 위치마다 공백 런 전체를 먹었다 되물린다(1MB 에 2.25초).
        after_type = "".join("/** c */ x" + " " * 5000 + ";\n" for _ in range(400))      # 2MB
        # 이름 뒤 공백은 런마다 한 번만 되물린다(상한 없이도 선형) — 그래도 시간 상한 안인지는 본다.
        after_name = "".join("/** c */ " + "a " * 100 + " " * 5000 + ";\n" for _ in range(400))
        for text in (after_type, after_name):
            st = time.perf_counter()
            assert sp._extract_doxygen_asil_tags(text) == {}
            assert time.perf_counter() - st < 2.0

    def test_contiguous_tagless_comments_are_walked_once(self, monkeypatch):
        # 머리가 안 맞았을 때 주석 하나씩 다시 시작하면, 건너뛰기가 매번 끝까지 가므로 잇닿은 주석 N 개에 N².
        meter = _HeadMeter(sp._DOX_HEAD_PAT)
        monkeypatch.setattr(sp, "_DOX_HEAD_PAT", meter)
        calls = []
        real = sp._doxygen_tags_of
        monkeypatch.setattr(sp, "_doxygen_tags_of", lambda body: (calls.append(1), real(body))[1])
        text = "/** words */\n" * 5000 + "int x;\n"
        assert sp._extract_doxygen_asil_tags(text) == {}
        assert meter.calls == 1
        assert len(calls) == 4999          # 첫 주석 뒤의 주석마다 한 번 — 5,000² 이 아니다

    def test_return_type_longer_than_the_cap_is_not_a_head(self):
        long_type = " ".join(["unsigned"] * 40)          # 359자 > 256
        assert len(long_type) > sp._DOX_HEAD_PREFIX_MAX
        assert sp._extract_doxygen_asil_tags(f"/** @asil B */ {long_type} f(void);") == {}
        ok_type = " ".join(["unsigned"] * 20)
        assert sp._extract_doxygen_asil_tags(f"/** @asil B */ {ok_type} f(void);") == {"f": {"asil": "B"}}


def _vector_table(n_lines: int) -> str:
    rows = "\n".join(f"  _VECTOR(Cpu_Interrupt_{i}),      " for i in range(n_lines))
    return (
        "typedef void (*near tIsrFunc)(void);\n"
        "#define _VECTOR(v) {0xFFU, &v}\n"
        f"const InterruptTableEntry _InterruptVectorTable[{n_lines}] @0x00FF9E10U = {{\n"
        f"{rows}\n"
        "};\n"
    )


_CALL_IN_IF = (
    "static U8 s_IsDoorClosed(U8 u8t_DoorState)\n{\n    return u8t_DoorState;\n}\n"
    "void g_Task(void)\n{\n"
    "    if( ( s_IsDoorClosed( u8t_Door1 ) == u8g_ON ) && ( s_IsDoorClosed( u8t_Door2 ) == u8g_ON ) )\n"
    "    {\n        u8g_Flag = 1;\n    }\n}\n"
)

_BODY_MODULES = [pytest.param(sp, id="source_parser"), pytest.param(twin, id="report.c_parsing")]


class TestFunctionBodies:
    @pytest.mark.parametrize("mod", _BODY_MODULES)
    def test_vector_table_finishes_in_bounded_time(self, mod):
        text = _vector_table(1500)       # 실물(123줄, 옛 정규식 1.6초)의 12배 — 옛 규칙으론 시간 단위
        st = time.perf_counter()
        assert mod._extract_c_function_bodies(text) == {}
        assert time.perf_counter() - st < 2.0

    @pytest.mark.parametrize("mod", _BODY_MODULES)
    def test_call_inside_if_does_not_replace_the_real_body(self, mod):
        bodies = mod._extract_c_function_bodies(_CALL_IN_IF)
        assert bodies["s_IsDoorClosed"] == "return u8t_DoorState;"
        assert set(bodies) == {"s_IsDoorClosed", "g_Task"}

    @pytest.mark.parametrize("mod", _BODY_MODULES)
    def test_nested_braces_and_empty_bodies(self, mod):
        text = "void a(void) { if (x) { y = 1; } }\nvoid b(void) {}\nvoid c(void) {\n  z = 2;\n}\n"
        assert mod._extract_c_function_bodies(text) == {"a": "if (x) { y = 1; }", "c": "z = 2;"}

    def test_both_modules_give_the_same_bodies(self):
        text = _CALL_IN_IF + "static  const U16 tbl_get ( U8 i )\n{\n  return tbl[i];\n}\n"
        assert sp._extract_c_function_bodies(text) == twin._extract_c_function_bodies(text)
        assert "tbl_get" in sp._extract_c_function_bodies(text)


class TestTwinDefinitions:
    def test_vector_table_finishes_in_bounded_time(self):
        st = time.perf_counter()
        assert twin._extract_c_definitions(_vector_table(1500)) == []
        assert time.perf_counter() - st < 2.0

    def test_three_tuple_shape_static_flag_and_flattened_params(self):
        text = "static U8 f(U8 a,\n      U8 b)\n{\n}\nvoid g ( void ) {\n}\nstaticky_t h(void) {\n}\n"
        assert twin._extract_c_definitions(text) == [
            ("f", "U8 a, U8 b", True),
            ("g", "void", False),
            ("h", "void", False),
        ]

    def test_call_inside_if_is_not_a_definition(self):
        assert [d[0] for d in twin._extract_c_definitions(_CALL_IN_IF)] == ["s_IsDoorClosed", "g_Task"]

    def test_control_keywords_are_not_functions(self):
        text = "void f(void)\n{\n}\n  else if (x)\n  {\n  }\n"
        assert [d[0] for d in twin._extract_c_definitions(text)] == ["f"]


# 백트래킹하는 두 모양. 문자열 상수에 이 조각이 있으면 그 정규식은 사본이다.
_CUBIC_PREFIX = r"[\w\s\*\(\),]*?"
_CROSSING_DOC = r"/\*\*(.*?)\*/\s*"

#: 남아 있는 사본과 그 사유. 여기에 파일을 **더하는** 변경은 같은 결함을 다시 들이는 것이다.
_KNOWN_COPIES = {
    # 호출자 0 (R60 가드 `TestTheOtherPreprocessingPathStaysUnused`) — N68 에서 제거.
    "workflow/code_parser/ast_parser.py": {_CUBIC_PREFIX: 1},
    # `_extract_c_prototypes`·`_extract_doxygen_asil_tags` — 프로덕션 호출자 0(아래 가드). N68 과 함께 제거.
    "report/c_parsing.py": {_CUBIC_PREFIX: 1, _CROSSING_DOC: 1},
    # diff 한 줄짜리(`^[+-]`), 파라미터가 `[^;{}]*` — 벡터 테이블 diff 로 재서 0.05초 미만.
    "workflow/delta_update.py": {_CUBIC_PREFIX: 1},
}
_PRODUCTION_DIRS = ("report", "report_gen", "workflow", "generators", "backend/services", "backend/helpers", "backend/routers")


_RE_FUNCS = {"compile", "finditer", "findall", "search", "match", "fullmatch", "sub", "subn", "split"}


def _regex_constants(path: Path):
    """`re.<함수>(…)` 호출의 **인자 안** 문자열 상수들.

    리뷰 I8 — 문자열 모양으로 거르면(여러 줄이면 제외·`(` 로 시작하면 제외) 진짜 정규식을 그렇게 쓴 사본을 놓친다.
    "정규식으로 쓰이는가" 는 호출 자리로 판정한다. `r"…" + _RET_TYPE + r"…"` 같은 이음도 인자 안을 걸어 들어가 본다.
    인접 문자열 리터럴은 파서가 한 상수로 합친다.
    """
    tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _RE_FUNCS):
            continue
        if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "re"):
            continue
        for arg in list(node.args) + [k.value for k in node.keywords]:
            out.extend(n.value for n in ast.walk(arg) if isinstance(n, ast.Constant) and isinstance(n.value, str))
    return out


@functools.lru_cache(maxsize=1)
def _copies_in_production():
    found = {}
    for d in _PRODUCTION_DIRS:
        for path in (REPO / d).rglob("*.py"):
            consts = _regex_constants(path)
            hits = {frag: sum(1 for c in consts if frag in c)
                    for frag in (_CUBIC_PREFIX, _CROSSING_DOC)}
            hits = {k: v for k, v in hits.items() if v}
            if hits:
                found[path.relative_to(REPO).as_posix()] = hits
    return found


class TestNoNewCopiesOfTheBacktrackingPatterns:
    def test_probe_sees_the_known_copies(self):
        # 자기 검증 — 탐지기가 아무것도 못 보면 아래 단언은 공허하게 통과한다.
        found = _copies_in_production()
        assert found.get("report/c_parsing.py") == _KNOWN_COPIES["report/c_parsing.py"]
        assert found.get("workflow/code_parser/ast_parser.py") == _KNOWN_COPIES["workflow/code_parser/ast_parser.py"]

    def test_production_has_only_the_known_copies(self):
        assert _copies_in_production() == _KNOWN_COPIES

    def test_fixed_modules_are_clean(self):
        found = _copies_in_production()
        assert "report_gen/source_parser.py" not in found
        assert "workflow/code_parser/c_parser.py" not in found

    def test_twin_leftovers_have_no_production_caller(self):
        leftovers = {"_extract_c_prototypes", "_extract_doxygen_asil_tags"}
        users = []
        for d in _PRODUCTION_DIRS + ("backend/mcp", "scripts"):
            for path in (REPO / d).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("c_parsing"):
                        if node.level and path.parent.name == "report":
                            continue     # `report/__init__.py` 의 재수출
                        names = {a.name for a in node.names}
                        if names & leftovers:
                            users.append((path.relative_to(REPO).as_posix(), sorted(names & leftovers)))
        assert users == []


class TestLightweightFallbackUsesTheFixedTwin:
    """`generators.suts._lightweight_parse` — 전체 소스 분석이 실패했을 때 SUTS/SITS 가 도는 경로. R61 전엔 이 경로를
    지나는 테스트가 하나도 없었다(그래서 쌍둥이 모듈 머리말의 "프로덕션 호출부 0건" 이 틀린 채 남아 있었다)."""

    def test_table_file_does_not_stall_and_call_in_if_is_not_a_function(self, tmp_path):
        from generators.suts import _lightweight_parse

        (tmp_path / "Vectors.c").write_text(_vector_table(1500), encoding="utf-8")
        (tmp_path / "door.c").write_text(_CALL_IN_IF, encoding="utf-8")
        st = time.perf_counter()
        details = _lightweight_parse(str(tmp_path))
        assert time.perf_counter() - st < 5.0
        # 옛 규칙은 `if( s_IsDoorClosed(…) … ) {` 를 세 번째 함수로 냈다.
        assert sorted(v["name"] for v in details.values()) == ["g_Task", "s_IsDoorClosed"]
        by_name = {v["name"]: v for v in details.values()}
        assert by_name["g_Task"]["calls_list"] == ["s_IsDoorClosed"]
        assert by_name["s_IsDoorClosed"]["calls_list"] == []
