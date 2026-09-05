# -*- coding: utf-8 -*-
"""void 반환 판정 단일 출처 가드 (R7, 2026-08-26).

## 무엇을 막는가

1. **근본** — `source_parser._extract_c_prototypes` 가 `__interrupt` 를 반환 타입에
   보존하면서 구분 공백을 잃어 `__interruptvoid` 라는 **존재하지 않는 타입**을 만들었다.
   실측: PDS64_RD 헤더 14건 → 산출물 `uds_local_20260825_153411.docx` 에 34칸
   (`Prototype` 12 · Output Parameters 그리드 12 · `Calling Function` 10).

2. **판정 분열** — 같은 질문에 프로덕션 6곳이 3가지 규칙을 썼다. 정확일치 3곳은
   `__interrupt void` 를 "반환값 있음" 으로 읽어 **void 인터럽트 핸들러가 설계서에서
   반환값을 가진 함수가 됐다**. 부분문자열 3곳은 우연히 맞았지만 `void *` 를 막는다.

3. **캐시** — 파서 로직이 바뀌면 `_SOURCE_SECTIONS_SCHEMA_VERSION` 을 올려야 한다.
   안 올리면 소스가 안 바뀐 프로젝트에서 구 캐시가 히트해 **fix 가 프로덕션에서
   발화하지 않는다**(저장소가 v3·v4·v12 에서 세 번 겪은 실패).

⚠ 이 파일은 **관측량**을 단언한다 — "함수가 존재한다"가 아니라 "그 함수가 내는 답이
   무엇인가". 구조 검사만 하면 분기를 죽여도 통과한다([[feedback_guard_must_change_observable]]).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

from backend.helpers.common import _parse_signature_outputs_simple  # noqa: E402
from backend.services.docgen_test_materials import _returns_value  # noqa: E402
from generators.suts import (  # noqa: E402
    _infer_return_type,
    _lw_parse_outputs,
    collect_unit_functions,
    generate_sequences,
)
from report_gen.c_return import normalize_return_type, returns_value  # noqa: E402
from report_gen.function_analyzer import _parse_signature_outputs  # noqa: E402
from report_gen.source_parser import _extract_c_prototypes  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# 1. 근본 — 파서가 공백을 잃지 않는다
# ─────────────────────────────────────────────────────────────────────
class TestPrototypeKeepsQualifierSeparator:
    HEADER = (
        "__interrupt void Cpu_Interrupt(void);\n"
        "__interrupt void SCI0_INT(void);\n"
        "extern U8 u8g_Read(void);\n"
        "void TIM0_Stop(void);\n"
    )

    def test_interrupt_qualifier_keeps_space(self):
        rows = {name: ret for name, _p, ret, _e in _extract_c_prototypes(self.HEADER)}
        assert rows["Cpu_Interrupt"] == "__interrupt void"
        assert rows["SCI0_INT"] == "__interrupt void"

    def test_glued_form_is_never_produced(self):
        """`__interruptvoid` 는 C 에 없는 토큰이다 — 우리가 만들어 냈던 것."""
        rets = [ret for _n, _p, ret, _e in _extract_c_prototypes(self.HEADER)]
        assert not any("__interruptvoid" in r for r in rets), rets

    def test_qualifier_is_still_preserved(self):
        """공백을 되살리자고 한정자를 **버리면** 안 된다(커밋 43a2f99 의 의도)."""
        rows = {name: ret for name, _p, ret, _e in _extract_c_prototypes(self.HEADER)}
        assert "__interrupt" in rows["Cpu_Interrupt"]

    def test_non_interrupt_prototypes_unchanged(self):
        rows = {name: ret for name, _p, ret, _e in _extract_c_prototypes(self.HEADER)}
        assert rows["u8g_Read"] == "U8"
        assert rows["TIM0_Stop"] == "void"

    def test_signature_assembled_by_uds_generator_is_valid_c(self):
        """`uds_generator` 는 `f"{ret_type} {name}( {params} )"` 로 조립한다 —
        그 조립 결과가 산출물 `Prototype` 칸에 그대로 실린다(실측 12칸이 붙어 있었다)."""
        rows = {n: (p, r) for n, p, r, _e in _extract_c_prototypes(self.HEADER)}
        params, ret = rows["Cpu_Interrupt"]
        sig = f"{ret} Cpu_Interrupt( {params} )"
        assert sig == "__interrupt void Cpu_Interrupt( void )"


# ─────────────────────────────────────────────────────────────────────
# 2. 판정 — 단일 출처가 내는 답
# ─────────────────────────────────────────────────────────────────────
class TestReturnsValueJudgment:
    @pytest.mark.parametrize(
        "raw",
        [
            "void",
            "__interrupt void",
            "__interruptvoid",      # 구 캐시·구 문서가 되돌려 보내는 형태
            "__EXTERN_C void",
            "static void",
            "const volatile void",
            "",
            "   ",
            None,
            "static",               # 한정자만 남으면 판정 불가 → 없음
            "__interrupt",          # ⚠ tree-sitter 가 `__interrupt void` 에서 내는 head
                                    #   (`void` 를 먹는다 — c_parser 의 기존 결함).
                                    #   옛 부분문자열 규칙은 여기서 `[OUT] return __interrupt`
                                    #   를 만들었다. 이 소스에선 산출물에 안 닿았지만 경로는 산다.
        ],
    )
    def test_no_return_value(self, raw):
        assert returns_value(raw) is False

    @pytest.mark.parametrize(
        "raw",
        [
            "U8",
            "S16",
            "l_u16",
            "static S16",
            "void *",               # ⚠ 부분문자열 판정이 여기서 틀렸다
            "void*",
            "const void *",
            "void **",
            "const char *",
            "struct Foo",
        ],
    )
    def test_has_return_value(self, raw):
        assert returns_value(raw) is True

    def test_void_pointer_is_a_real_return_value(self):
        """이 한 줄이 부분문자열 규칙과 갈리는 지점이다."""
        assert "void" in "void *"
        assert returns_value("void *") is True

    def test_win32_uppercase_void_is_void(self):
        assert returns_value("VOID") is False

    def test_type_named_like_void_is_not_void(self):
        """`avoid_t` 는 void 가 아니다 — 부분문자열 규칙이 막던 부류."""
        assert returns_value("avoid_t") is True
        assert returns_value("voidptr_t") is True

    def test_glue_repair_does_not_eat_real_identifiers(self):
        """붙음 복구를 넓히면 진짜 식별자를 잘라 먹는다 — 좁혀 뒀는지 확인."""
        assert normalize_return_type("__interruptible_t") == "__interruptible_t"
        assert returns_value("__interruptible_t") is True


class TestNormalizeReturnType:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("__interruptvoid", "void"),
            ("__interrupt void", "void"),
            ("__EXTERN_C void", "void"),
            ("static const U8", "U8"),
            ("__interrupt", ""),
            ("  U16  ", "U16"),
            ("const char *", "char *"),
            ("void *", "void *"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_return_type(raw) == expected

    def test_case_sensitive_qualifier_strip(self):
        """C 는 대소문자를 구분한다 — `Static` 은 타입명일 수 있다."""
        assert normalize_return_type("Static") == "Static"
        assert normalize_return_type("static") == ""


# ─────────────────────────────────────────────────────────────────────
# 3. 6곳이 같은 답을 내는가 — 관측량 기반
# ─────────────────────────────────────────────────────────────────────
def _fn_of(sig: str) -> str:
    return sig.split("(")[0].strip().split()[-1]


def _verdicts(sig: str) -> dict:
    fn = _fn_of(sig)
    return {
        "common": any(
            str(x).startswith("[OUT] return") for x in _parse_signature_outputs_simple(sig)
        ),
        "suts_lw": bool(_lw_parse_outputs(sig, fn)),
        "function_analyzer": any(
            str(x).startswith("[OUT] return") for x in _parse_signature_outputs(sig, fn)
        ),
        "docgen_test_materials": _returns_value({"prototype": sig}),
        "suts_output_vars": returns_value(_infer_return_type(sig)),
    }


VOID_SIGS = [
    "__interrupt void Cpu_Interrupt( void )",
    "__interruptvoid Cpu_Interrupt( void )",
    "__EXTERN_C void main( void )",
    "void TIM0_Stop( void )",
]
VALUE_SIGS = [
    "U8 u8g_Read( void )",
    "static S16 s_Calc( U8 a )",
    "void * mem_alloc( U16 n )",
    "const char * name_of( U8 id )",
]


class TestAllProducersAgree:
    @pytest.mark.parametrize("sig", VOID_SIGS)
    def test_void_signatures_claim_no_return(self, sig):
        v = _verdicts(sig)
        assert set(v.values()) == {False}, v

    @pytest.mark.parametrize("sig", VALUE_SIGS)
    def test_value_signatures_claim_a_return(self, sig):
        v = _verdicts(sig)
        assert set(v.values()) == {True}, v

    @pytest.mark.parametrize("sig", VOID_SIGS + VALUE_SIGS)
    def test_no_producer_disagrees(self, sig):
        v = _verdicts(sig)
        assert len(set(v.values())) == 1, f"판정 분열: {sig} -> {v}"

    def test_interrupt_handler_gets_no_output_row(self):
        """산출물 Output Parameters 그리드에 `return __interruptvoid` 가 실렸었다."""
        sig = "__interrupt void Cpu_Interrupt( void )"
        rows = _parse_signature_outputs_simple(sig)
        assert not [r for r in rows if "return" in str(r)], rows

    def test_real_return_survives(self):
        """음성 대조군 — 고치면서 진짜 반환값까지 지우지 않았는가."""
        assert _parse_signature_outputs_simple("U8 u8g_Read( void )") == ["[OUT] return U8"]


# ─────────────────────────────────────────────────────────────────────
# 4. 판정 복제 재발 방지 — 새 사이트가 자기 규칙을 들고 오는 것을 막는다
# ─────────────────────────────────────────────────────────────────────
PRODUCTION_DIRS = ("backend", "report_gen", "generators", "workflow")
_SKIP_PARTS = {".venv", "venv", "node_modules", "__pycache__", "_archive", "site-packages"}
# 단일 출처 자신은 당연히 `void` 문자열을 갖는다.
_ALLOWED = {Path("report_gen") / "c_return.py"}

# ⚠ **축을 가른다.** `params.lower() == "void"` 는 `f(void)` = "파라미터 없음" 이고
#   `gtype.lower() == "void"` 는 전역 변수 타입이다 — 둘 다 반환 축이 아니다.
#   첫 판은 이 셋을 싸잡아 19건을 offender 로 냈다(전부 오탐).
_RETURN_ISH = re.compile(r"(?i)(ret|return|head|proto|signature|\bsig\b|\brt\b|rtype)")


def _return_axis_void_comparisons(source: str, label: str = "<mem>") -> list:
    """`"void"` 와 비교하는 **반환 축** 표현식을 찾는다.

    휴리스틱이다(피연산자 이름으로 축을 가른다). 권위 있는 가드는 위 §3 의
    관측량 시험이고, 여기는 **새 복제를 늦게라도 알아채는 ratchet** 이다.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        # strict=True: ast.Compare 는 ops 와 comparators 길이가 늘 같다 —
        #   아니면 파서가 이상한 것이니 조용히 자르지 말고 터지게 둔다.
        for op, comp in zip(node.ops, node.comparators, strict=True):
            if isinstance(op, (ast.Eq, ast.NotEq)):
                lit, other = comp, node.left
            elif isinstance(op, (ast.In, ast.NotIn)):
                lit, other = node.left, comp
            else:
                continue
            if not (isinstance(lit, ast.Constant) and isinstance(lit.value, str)):
                continue
            if lit.value.strip().lower() != "void":
                continue
            seg = ast.get_source_segment(source, other) or ""
            if _RETURN_ISH.search(seg):
                hits.append(f"{label}:{node.lineno}: {seg.strip()[:70]}")
    return hits


def _production_files():
    out = []
    for d in PRODUCTION_DIRS:
        base = REPO / d
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            rel = p.relative_to(REPO)
            if _SKIP_PARTS & set(rel.parts):
                continue
            out.append(p)
    return out


class TestNoDuplicateVoidJudgment:
    def test_scanner_reaches_real_source(self):
        """탐지기가 아무것도 안 보고 통과하는 fake-green 방지."""
        files = _production_files()
        assert len(files) > 100, f"후보 {len(files)}개 — 스캔 경로가 틀렸다"
        assert any(f.name == "c_return.py" for f in files)

    def test_detector_flags_a_planted_duplicate(self):
        """양성 대조군 — 탐지기가 실제로 잡는가."""
        planted = "def f(sig):\n    ret = sig\n    if ret.lower() != 'void':\n        return 1\n"
        assert _return_axis_void_comparisons(planted, "planted")

    def test_detector_flags_substring_form(self):
        planted = "def f(head):\n    if 'void' not in head:\n        return 1\n"
        assert _return_axis_void_comparisons(planted, "planted")

    def test_detector_ignores_parameter_axis(self):
        """음성 대조군 — `f(void)` 는 파라미터 없음이지 반환 축이 아니다."""
        other = "def f(params):\n    if params.lower() == 'void':\n        return []\n"
        assert _return_axis_void_comparisons(other, "other") == []

    def test_detector_ignores_global_type_axis(self):
        other = "def f(gtype):\n    if gtype.lower() == 'void':\n        return []\n"
        assert _return_axis_void_comparisons(other, "other") == []

    def test_no_new_inline_return_void_comparison(self):
        offenders = []
        for p in _production_files():
            rel = p.relative_to(REPO)
            if rel in _ALLOWED:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            offenders.extend(_return_axis_void_comparisons(text, str(rel)))
        assert not offenders, (
            "반환 축 void 판정을 인라인으로 복제했다. "
            "`report_gen.c_return.returns_value` 를 쓸 것:\n  " + "\n  ".join(offenders)
        )

    def test_every_wired_site_imports_the_single_source(self):
        wired = [
            Path("backend") / "helpers" / "common.py",
            Path("backend") / "services" / "docgen_test_materials.py",
            Path("report_gen") / "function_analyzer.py",
            Path("report_gen") / "uds_generator.py",
            Path("generators") / "suts.py",
        ]
        for rel in wired:
            tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
            names = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module == "report_gen.c_return"
                for alias in node.names
            }
            assert "returns_value" in names, f"{rel} 이 단일 출처를 안 쓴다"


# ─────────────────────────────────────────────────────────────────────
# 5. 캐시 무효화 — 파서가 바뀌면 버전이 올라야 한다
# ─────────────────────────────────────────────────────────────────────
class TestSourceSectionsCacheInvalidated:
    def test_schema_version_advanced_past_v12(self):
        """v12 캐시에는 `__interruptvoid` 가 박혀 있다 — 안 올리면 fix 가 안 뜬다."""
        from backend.helpers.uds import _SOURCE_SECTIONS_SCHEMA_VERSION as ver

        assert ver.startswith("v")
        assert int(ver[1:]) >= 13, f"파서 로직이 바뀌었는데 캐시 버전이 {ver} 이다"

    def test_signature_carries_schema_version(self):
        """버전이 시그니처에 실제로 들어가야 무효화가 일어난다."""
        from backend.helpers import uds as uds_mod

        sig = uds_mod._source_root_signature(str(REPO / "report_gen"))
        assert sig is not None
        assert sig.startswith(uds_mod._SOURCE_SECTIONS_SCHEMA_VERSION + ":")


# ─────────────────────────────────────────────────────────────────────
# 6. SUTS 시험 케이스 — void 함수에 "반환값 검증" 을 만들지 않는다
# ─────────────────────────────────────────────────────────────────────
class TestSutsReturnCheckSequence:
    """`generate_sequences` 는 입력·출력 변수가 없는 unit 에 기본 시퀀스를 만든다.

    반환값이 있으면 `RETURN_CHECK` 를 하나 더 붙인다. 예전 판정은
    `"void" in prototype.split("(")[0].lower()` 라 **함수 이름까지** 봤다.
    """

    @staticmethod
    def _strategies(prototype: str) -> set:
        unit = {"name": "Fn", "prototype": prototype, "input_vars": [], "output_vars": []}
        return {s.get("strategy") for s in generate_sequences(unit, max_seq=9)}

    def test_void_interrupt_handler_gets_no_return_check(self):
        assert "RETURN_CHECK" not in self._strategies("__interrupt void Cpu_Interrupt(void)")

    def test_glued_form_also_gets_no_return_check(self):
        assert "RETURN_CHECK" not in self._strategies("__interruptvoid Cpu_Interrupt(void)")

    def test_plain_void_gets_no_return_check(self):
        assert "RETURN_CHECK" not in self._strategies("void TIM0_Stop(void)")

    def test_value_returning_function_gets_return_check(self):
        """음성 대조군 — 전부 막아 버리면 시험이 사라진다."""
        assert "RETURN_CHECK" in self._strategies("U8 u8g_Read(void)")

    def test_function_named_like_void_still_gets_return_check(self):
        """⚠ 이름에 `void` 가 든 함수를 void 로 읽던 결함."""
        assert "RETURN_CHECK" in self._strategies("U8 avoid_Overflow(U8 a)")

    def test_void_pointer_return_gets_return_check(self):
        assert "RETURN_CHECK" in self._strategies("void * mem_alloc(U16 n)")

    def test_missing_prototype_is_treated_as_void(self):
        """근거가 없으면 반환값을 **주장하지 않는다**(기존 동작 보존)."""
        assert "RETURN_CHECK" not in self._strategies("")


# ─────────────────────────────────────────────────────────────────────
# 7. 배선된 두 사이트의 **관측량** — 함수가 아니라 호출부를 부른다
# ─────────────────────────────────────────────────────────────────────
# ⚠ §3 의 `_verdicts` 는 이 둘을 **재구현**해서 재고 있었다(`returns_value(
#   _infer_return_type(sig))`). 그래서 호출부를 옛 규칙으로 되돌려도 통과했다
#   — 뮤테이션 M12·M14 가 살아남아 드러난 내 공백이다.
#   [[feedback_guard_must_change_observable]]: 가드는 **관측량**을 단언할 것.
class TestSutsOutputVarsSite:
    """`collect_unit_functions` 는 반환값이 있으면 출력 변수에 `return` 을 넣는다."""

    @staticmethod
    def _output_vars(prototype: str) -> list:
        name = prototype.split("(")[0].strip().split()[-1] if "(" in prototype else "Fn"
        units = collect_unit_functions(
            {
                "a": {
                    "id": "SwUFn_0101", "name": name, "prototype": prototype,
                    "inputs": [], "outputs": [],
                    "globals_global": [], "globals_static": [], "logic_flow": [],
                }
            },
            sds_map={},
        )
        return list(units[0].get("output_vars") or [])

    def test_interrupt_handler_has_no_return_output_var(self):
        assert self._output_vars("__interrupt void Cpu_Interrupt(void)") == []

    def test_glued_form_too(self):
        assert self._output_vars("__interruptvoid Cpu_Interrupt(void)") == []

    def test_plain_void_has_none(self):
        assert self._output_vars("void TIM0_Stop(void)") == []

    def test_value_returning_function_has_one(self):
        assert "return" in self._output_vars("U8 u8g_Read(void)")

    def test_void_pointer_return_has_one(self):
        assert "return" in self._output_vars("void * mem_alloc(U16 n)")


_SRC_H = """\
__interrupt void Cpu_Interrupt(void);
U8 u8g_Read(void);
void TIM0_Stop(void);
"""
_SRC_C = """\
#include "m.h"
__interrupt void Cpu_Interrupt(void) { u8g_State = 1U; }
U8 u8g_Read(void) { return u8g_State; }
void TIM0_Stop(void) { u8g_State = 0U; }
U8 u8g_State;
"""


@pytest.fixture()
def _uds_sections(tmp_path):
    """⚠ 함수 스코프다. 이 파서를 module 스코프로 잡았다가 고부하 `-n auto` 에서
    간헐 ERROR 를 낸 전례가 있다([[project_flaky_parser_fixture]])."""
    from backend.services import file_resolver as fr
    from report_gen.uds_generator import generate_uds_source_sections

    (tmp_path / "m.h").write_text(_SRC_H, encoding="utf-8")
    (tmp_path / "m.c").write_text(_SRC_C, encoding="utf-8")
    saved = fr._resolver
    fr._resolver = fr.LocalFileResolver()
    try:
        return generate_uds_source_sections(str(tmp_path), preprocess=False)
    finally:
        # ⚠ 원래 값 **복원** — 특정 값으로 고정하면 다음 테스트가 물려받는다(커밋 584833e).
        fr._resolver = saved


def _by_prototype(sections: dict) -> dict:
    out = {}
    for info in (sections.get("function_details") or {}).values():
        out[str(info.get("prototype") or "").strip()] = info
    return out


class TestUdsGeneratorOutputsSite:
    """생산 경로 끝단 — 산출물 Output Parameters 그리드에 실리는 그 값."""

    def test_prototype_keeps_the_separator_end_to_end(self, _uds_sections):
        protos = set(_by_prototype(_uds_sections))
        assert "__interrupt void Cpu_Interrupt( void )" in protos, protos
        assert not any("__interruptvoid" in p for p in protos), protos

    def test_interrupt_handler_has_no_return_output(self, _uds_sections):
        info = _by_prototype(_uds_sections)["__interrupt void Cpu_Interrupt( void )"]
        rows = [r for r in (info.get("outputs") or []) if "return" in str(r)]
        assert rows == [], rows

    def test_plain_void_has_no_return_output(self, _uds_sections):
        info = _by_prototype(_uds_sections)["void TIM0_Stop( void )"]
        rows = [r for r in (info.get("outputs") or []) if "return" in str(r)]
        assert rows == [], rows

    def test_value_returning_function_keeps_its_return_output(self, _uds_sections):
        """음성 대조군 — 전부 지워 버리면 진짜 반환값이 사라진다."""
        info = _by_prototype(_uds_sections)["U8 u8g_Read( void )"]
        rows = [r for r in (info.get("outputs") or []) if "return" in str(r)]
        assert rows and rows[0].startswith("[OUT] return U8"), rows
