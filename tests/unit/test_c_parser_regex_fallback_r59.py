"""(R59 N60) 정규식 폴백의 정의-머리 탐색은 **선형**이어야 한다 — 한 파일이 백엔드 전체를 멈추던 것.

옛 `_REGEX_DEF_PAT` 는 접두(lazy, 괄호·쉼표·개행 허용)와 파라미터(lazy `[^;]*?`)가 둘 다 무한정 늘어나
세미콜론 없이 이어지는 초기화 표(인터럽트 벡터 테이블 `Generated_Code/Vectors.c`, 17.6KB, `_VECTOR(x),` 123줄)에서
O(n³) 으로 백트래킹했다: 그 한 파일에 **31초**, `re` 는 매칭 중 GIL 을 놓지 않으므로 그동안 백엔드 프로세스의
다른 스레드(진행 조회·`/api/health`·이벤트 루프)가 전부 멈췄다(라이브 40초 정지 — keep-alive 타이머가 늦게
발화해 대기 중이던 폴링을 응답 없이 끊음).

계약:
- `_iter_regex_def_heads` 가 옛 finditer 와 같은 `(start, prefix, name, params, end)` 를 낸다 — 보통 코드에선 **동일**
  (실 루트 178 파일 중 폴백이 실제로 도는 110 파일 전부 동일).
- 벡터 테이블 모양의 입력은 줄 수에 비례하는 시간에 끝난다(옛 정규식은 123줄에 31초, 3,000줄이면 시간 단위).
- 갈리는 곳은 옛 규칙이 지어내던 자리뿐: `if( f() == ON ) {` 를 함수로 읽던 것, `const FUNC(void, CODE) foo(void) {`
  에서 FUNC 를 이름으로 내던 것 — 괄호 깊이로 재면 함수 이름은 `{` 바로 앞 괄호의 주인이다.
"""
from __future__ import annotations

import re
import time

import pytest

from workflow.code_parser import c_parser as cp

# 옛 정규식 — 대조군(오라클). 보통 코드에선 새 스캐너와 같은 답을 내야 한다.
_OLD_PAT = re.compile(
    r"^[\t ]*((?:static\s+)?[A-Za-z_][\w\s\*\(\),]*?)\s+([A-Za-z_]\w*)\s*\(([^;]*?)\)\s*\{",
    flags=re.M,
)


def _old(text):
    return [(m.start(), m.group(1).strip(), m.group(2), " ".join(m.group(3).split()), m.end()) for m in _OLD_PAT.finditer(text)]


def _new(text):
    return [(s, p.strip(), n, " ".join(pr.split()), e) for s, p, n, pr, e in cp._iter_regex_def_heads(text)]


class _ScanMeter:
    """스캐너가 정규식으로 **실제로 훑은 글자 수** — 시간 대신 이걸로 선형성을 단언한다."""

    def __init__(self, prefix_pat, param_pat):
        self._prefix, self._param = prefix_pat, param_pat
        self.prefix_span = 0
        self.param_span = 0

    class _Prefix:
        def __init__(self, meter):
            self.m = meter

        def finditer(self, text, lo, hi):
            self.m.prefix_span += max(0, hi - lo)
            return self.m._prefix.finditer(text, lo, hi)

    class _Param:
        def __init__(self, meter):
            self.m = meter

        def search(self, text, pos, endpos):
            mt = self.m._param.search(text, pos, endpos)
            self.m.param_span += (mt.end() if mt else min(endpos, len(text))) - pos
            return mt


@pytest.fixture
def scan_meter(monkeypatch):
    meter = _ScanMeter(cp._DEF_PREFIX_OUT_PAT, cp._DEF_PARAM_SCAN_PAT)
    monkeypatch.setattr(cp, "_DEF_PREFIX_OUT_PAT", _ScanMeter._Prefix(meter))
    monkeypatch.setattr(cp, "_DEF_PARAM_SCAN_PAT", _ScanMeter._Param(meter))
    return meter


def _vector_table(n_lines: int) -> str:
    rows = "\n".join(f"  _VECTOR(Cpu_Interrupt_{i}),      /* 0x{0xFF9E10 + 4 * i:07X} vector {i} */" for i in range(n_lines))
    return (
        "typedef void (*near tIsrFunc)(void);\n"
        "typedef struct { byte padding; tIsrFunc address; } InterruptTableEntry;\n"
        "#define _VECTOR(v) {0xFFU, &v}\n"
        f"const InterruptTableEntry _InterruptVectorTable[{n_lines}] @0x00FF9E10U = {{ /* Interrupt vector table */\n"
        f"{rows}\n"
        "};\n"
    )


class TestLinearInPathologicalTable:
    def test_vector_table_finishes_in_bounded_time_and_finds_nothing(self):
        text = cp.blank_c_comments(_vector_table(3000))   # 실물(123줄)의 24배 — 옛 정규식으론 시간 단위
        st = time.perf_counter()
        fns = cp._extract_function_defs_regex_fallback(text, "Vectors.c", set())
        assert time.perf_counter() - st < 2.0
        assert fns == []

    def test_table_candidates_never_reach_the_prefix_walk(self, scan_meter):
        # 시간 비율이 아니라 **훑은 글자 수**로 단언한다(리뷰 I5: 바닥값 0.5초짜리 비율 가드는 O(n²) 회귀를 통과시켰다).
        text = cp.blank_c_comments(_vector_table(6000))
        assert _new(text) == []
        # 표의 후보 6,000개는 파라미터 단계(`,` 뒤)에서 떨어진다 — 접두를 훑는 건 `#define _VECTOR(v) {…}` 줄의 후보 하나뿐.
        assert scan_meter.prefix_span <= 64
        assert scan_meter.param_span <= 4 * len(text)

    def test_macro_only_header_is_cheap(self, scan_meter):
        text = "\n".join(f"#define REG_{i}(x)  ((x) + {i}U)" for i in range(20000))
        st = time.perf_counter()
        assert _new(text) == []
        assert time.perf_counter() - st < 1.0
        assert scan_meter.prefix_span == 0 and scan_meter.param_span <= 4 * len(text)

    def test_long_line_above_each_function_stays_linear(self, scan_meter):
        # 리뷰 W1: 창 안에 `\n` 이 없으면 rfind 가 -1 → 0 이 되어 머리마다 파일 맨 앞부터 훑었다(400개·1.2MB 에 3초, 배증마다 4배).
        #   트리거는 창(`_DEF_PREFIX_WINDOW`)보다 긴 줄 — 그래서 위 줄을 창보다 길게 둔다.
        row = "1," * (cp._DEF_PREFIX_WINDOW // 2 + 512)
        blocks = "".join(f"static const U8 tbl_{i}[] = {{{row}}};\nvoid f_{i}(void)\n{{\n}}\n" for i in range(400))
        heads = _new(blocks)
        assert [h[2] for h in heads] == [f"f_{i}" for i in range(400)]
        assert scan_meter.prefix_span <= 2 * len(blocks), "머리마다 자기 줄과 바로 위 긴 줄만 훑어야 한다"

    def test_unclosed_parens_are_capped_per_candidate(self, scan_meter):
        # 리뷰 W2: 닫히지 않는 `(` 가 이어지고 `;{}` 가 멀면 후보마다 그 구간 끝까지 훑었다(63KB 에 3초).
        text = "".join(f"FOO_{i}(a, b\n" for i in range(4000)) + "void real(void) {\n}\n"
        assert [h[2] for h in _new(text)] == ["real"]
        assert scan_meter.param_span <= 4000 * (cp._DEF_PARAMS_MAX + 64)

    def test_parameter_list_longer_than_the_cap_is_not_a_head(self):
        text = "void f(" + "int a," * 800 + " int z) {\n}\n"   # 파라미터 5.6KB — 실측 최장은 364자
        assert _old(text) and _new(text) == []


_AGREE_CASES = [
    "void foo(int x) {\n  return;\n}\n",
    "static int bar(void) {\n  return 0;\n}\n",
    "static\nvoid\nmulti_line(const U8 *p,\n            U16 n)\n{\n}\n",
    "static foo(void) {\n}\n",                                   # 반환형 생략(K&R 풍)
    "void cb_param(int (*cb)(int), void *ctx) {\n}\n",          # 함수 포인터 파라미터
    "FUNC(void, CODE) autosar(void) {\n}\n",                     # 매크로 반환형
    "static FUNC(void, CODE) autosar_static(void) {\n}\n",
    "void proto(int a);\nvoid real(int b) {\n}\n",               # 프로토타입은 머리가 아니다
    "void a(void) {\n}\nvoid b(void) {\n}\n",                    # 겹치지 않는 연속 매치
    "  if (x) {\n  }\n",                                         # 접두 없는 키워드 — 매치 없음
    "void f(void) {\n  else if (y) {\n  }\n}\n",                 # 키워드 머리도 옛 규칙대로 소비(호출자가 거른다)
    "#define X(a) ((a) + 1)\nvoid g(void) {\n}\n",               # `#` 줄은 접두가 될 수 없다
    "int x;\nvoid h(void)\n{\n}\n",                              # `;` 뒤 다음 줄 시작부터
    "void\n\n\nblank_lines(void) {\n}\n",                        # 빈 줄은 접두 시작이 아니다
    "unsigned char *ptr_ret(void) {\n}\n",
    "void trailing_ws(void)   \n   {\n}\n",
    "extern void ext(void) {\n}\n",
    "(void)\n foo(void) {\n}\n",                                 # `(` 로 시작하는 줄은 접두 시작이 아니다 → 매치 없음
    "static\n* foo(void) {\n}\n",                                # 접두는 `*` 를 품을 수 있다(첫 줄만 글자로 시작하면 된다)
    "",
]


class TestHeadScannerAgreesWithOldRegex:
    @pytest.mark.parametrize("text", _AGREE_CASES, ids=[c.split("\n", 1)[0][:28] or "empty" for c in _AGREE_CASES])
    def test_same_heads_as_old_regex(self, text):
        assert _new(text) == _old(text)

    def test_match_start_is_the_prefix_line_start(self):
        # 선행 주석은 match_start 에서 거슬러 읽으므로 옛 값(줄 시작, 들여쓰기 포함)과 같아야 한다.
        text = "  /* doc */\n  static void indented(void) {\n  }\n"
        heads = _new(cp.blank_c_comments(text))
        assert heads and heads[0][0] == text.index("  static")

    def test_fallback_output_identical_on_generated_code_shape(self):
        src = (
            "/*\n** bool PS3_MOTOR_NSCS_GetVal(void)\n**  This method is implemented as a macro. See PS3_MOTOR_NSCS.h file.\n*/\n"
            "/* 실제 함수의 설명 */\nvoid PS3_MOTOR_NSCS_Init(void)\n{\n  x = 1;\n}\n"
        )
        fns = cp._extract_function_defs_regex_fallback(src, "x.c", set())
        assert [f.name for f in fns] == ["PS3_MOTOR_NSCS_Init"]
        assert fns[0].signature == "void PS3_MOTOR_NSCS_Init(void)"
        assert "실제 함수의 설명" in (fns[0].comment_desc or "")


class TestWhereTheOldRegexInvented:
    """옛 규칙과 갈리는 자리 — 전부 옛 쪽이 지어낸 것이다(실 파일 6개에서 phantom 14건, 실 함수 손실 0)."""

    def test_call_inside_if_is_not_a_function(self):
        text = "void real(void) {\n  if( s_IsDoorClosed( u8t_Door1 ) == u8g_ON ) {\n    x = 1;\n  }\n}\n"
        assert [h[2] for h in _old(text)] == ["real", "s_IsDoorClosed"], "옛 규칙은 if 안 호출을 함수로 읽었다"
        assert [h[2] for h in _new(text)] == ["real"]

    def test_macro_return_type_after_qualifier_names_the_function_not_the_macro(self):
        text = "const FUNC(void, CODE) foo(void) {\n}\n"
        assert [h[2] for h in _old(text)] == ["FUNC"]
        assert _new(text)[0][1:4] == ("const FUNC(void, CODE)", "foo", "void")

    def test_unbalanced_parameters_are_rejected(self):
        # 옛 `[^;]*?` 는 `)` 하나만 보고 `{` 를 찾았다 — 괄호 깊이가 안 맞으면 파라미터가 아니다.
        assert _new("void f(int a {\n}\n") == []
        assert _new("void f(int a)) {\n}\n") == []
        # 파라미터 안의 `{`·`}` — 옛 `[^;]*?` 는 통과시켰다.
        assert _old("void f(int a { int b) {\n}\n") and _new("void f(int a { int b) {\n}\n") == []


class TestScannerRulesIndividually:
    def test_name_needs_whitespace_before_it(self):
        assert _new("void*foo(void) {\n}\n") == []
        # ⚠ 옛 규칙의 한계 그대로: `*` 가 이름에 붙은 포인터 반환 함수는 폴백이 못 찾는다(tree-sitter 경로가 찾는다). 넓히지 않았다.
        assert _new("void *foo(void) {\n}\n") == _old("void *foo(void) {\n}\n") == []
        assert [h[2] for h in _new("void * foo(void) {\n}\n")] == ["foo"]

    def test_prefix_cannot_cross_a_non_type_character(self):
        assert _new("x = y\n  foo(void) {\n}\n") == []          # `=` 뒤 줄에는 접두가 없다
        assert [h[1:3] for h in _new("x = y;\nint foo(void) {\n}\n")] == [("int", "foo")]

    def test_prefix_starts_at_the_earliest_qualifying_line(self):
        heads = _new("static\nconst\nU8 *\nfoo(void) {\n}\n")
        assert heads[0][1] == "static\nconst\nU8 *" and heads[0][0] == 0

    def test_semicolon_between_parens_rejects(self):
        assert _new("void f(int a; int b) {\n}\n") == []

    def test_matches_do_not_overlap(self):
        text = "void a(void) {\n  b(1) {\n}\n"
        heads = _new(text)
        assert [h[2] for h in heads] == ["a"], "a 의 `{` 뒤에서 이어져야 하고 b 는 접두가 없다"


@pytest.mark.skipif(cp._make_parser() is None, reason="tree-sitter C 파서 미가용")
def test_parse_c_project_still_uses_the_fallback_when_tree_sitter_finds_nothing(tmp_path):
    # 폴백 자체를 끄면 안 된다 — CRC32.c 는 tree-sitter 가 오류 없이 0개로 읽지만 폴백이 실제 함수 2개를 낸다(실측).
    (tmp_path / "gen.c").write_text("__EXTERN_C void _Startup(void) {\n  DoZeroOut();\n}\n", encoding="utf-8")
    res = cp.parse_c_project(str(tmp_path))
    names = [f["name"] for f in res["functions"]]
    assert "_Startup" in names
