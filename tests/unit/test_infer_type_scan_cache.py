"""`_infer_type_from_file` — 후보 줄 스캔 + 실행 단위 원문 캐시 (R52 N41).

## 왜

kjpds02_pv 소스 분석 491초 중 이 폴백이 347초(71%)였다. 전역 25,007건이 전부 폴백을 탔고 **호출마다 파일을 다시
읽었다**(cloudium 모드에선 워커 IPC 소켓 연결 — 25,160회 · 777MB · 251초. 실제 파일은 113개 · 3.4MB). 정규식도
줄마다 `^\\s*(.+?)` 를 늘려 파일 전체를 훑는데, 호출의 90%(22,627)는 그 파일에 이름이 **아예 없는** 호출이었다
(tree-sitter 가 '그 파일이 쓰는 전역' 을 파일에 귀속시키므로 선언은 다른 파일에 있다).

## 무엇을 재나

1. **참조 구현(변경 전 코드 그대로)과 결과 동일** — 손으로 만든 경계 케이스 + 고정 시드 무작위 대조. 매치 단위로도
   같아야 한다(group(1) 범위 · 끝 위치 · 종결 기호).
2. 캐시는 **읽기 횟수**를 바꾼다 — 등가성만 재면 캐시를 빼도 통과한다(관측량은 횟수, R47-j 교훈).
3. `generate_uds_source_sections` 가 두 호출부에 **같은** 실행 단위 캐시를 넘긴다(한쪽만 넘기면 쌍둥이 한쪽 결함).
"""
from __future__ import annotations

import ast
import random
import re
from pathlib import Path
from typing import List, Tuple

import pytest

from report_gen import utils as RU
from report_gen.source_parser import _read_text_limited
from report_gen.utils import _infer_type_from_file, _is_type_head, _iter_decl_matches


# ── 참조 구현: 변경 전 `_infer_type_from_file` 의 스캔 본문 그대로(원문을 인자로 받는 점만 다르다) ──
def _ref_infer(text: str, name: str) -> Tuple[str, str]:
    if not name:
        return "", ""
    name_re = re.escape(name)
    try:
        pattern = re.compile(rf"^\s*(.+?)\b{name_re}\b\s*(=|\[|;)", re.M)
    except re.error:
        return "", ""
    for match in pattern.finditer(text):
        decl = match.group(0)
        if "(" in decl:
            continue
        head = match.group(1)
        head = re.sub(r"\b(static|extern|const|volatile)\b", "", head).strip()
        gtype = " ".join(head.split()).strip()
        init = ""
        init_match = re.search(rf"\b{name_re}\b\s*=\s*([^;]+)", decl)
        if init_match:
            init = init_match.group(1).strip()
        if gtype and _is_type_head(gtype):
            return gtype, init
    return "", ""


def _write(tmp_path: Path, text: str, name: str = "x.c") -> str:
    p = tmp_path / name
    p.write_bytes(text.encode("utf-8"))      # `\r\n`·`\r` 을 그대로 남긴다
    return str(p)


def _new_on_text(text: str, name: str) -> Tuple[str, str]:
    """파일 없이 새 구현을 원문에 직접 태운다 — 캐시에 원문을 미리 넣으면 읽기를 건너뛴다."""
    return _infer_type_from_file("<mem>.c", name, cache={"<mem>.c": text})


CASES: List[Tuple[str, str, List[str]]] = [
    ("basic", "extern volatile ADC0STSSTR _ADC0STS;\n", ["_ADC0STS", "ADC0STSSTR", "nope"]),
    ("blank_prefix", "\n\n\n   static U8 s_Cnt = 3;\n", ["s_Cnt"]),
    ("crlf", "static U8 a;\r\nstatic U16 b = 2;\r\nU8 s_Cnt[4];\r\n", ["a", "b", "s_Cnt"]),
    ("cross_line_terminator", "static U8 s_X\n= 4;\nU8 s_Y\n;\nU8 s_Z\n\n  [3];\nU8 s_W\n", ["s_X", "s_Y", "s_Z", "s_W"]),
    ("paren_then_decl", "void f(U8 s_Cnt);\nstatic U8 s_Cnt;\n", ["s_Cnt"]),
    ("twice_on_line", "U8 s_A = s_A_INIT; s_A[0] = 1;\nU16 s_B = 1, s_B2 = s_B;\n", ["s_A", "s_B", "s_B2"]),
    ("inside_longer_ident", "U8 s_Cnt2;\nU8 xs_Cnt;\n", ["s_Cnt"]),
    ("at_offset_zero", "s_Cnt = 3;\nU8 s_Cnt;\n", ["s_Cnt"]),
    ("only_in_comment", "/* s_Cnt is here */\nvoid g(void) { s_Cnt = 1; }\n", ["s_Cnt"]),
    ("bad_shape_then_real", "static U8 u8s_Copy = s_Cnt;\n\nstatic U8 s_Cnt;\n", ["s_Cnt"]),
    ("anonymous_enum_close", "static enum\n{\n    en_s_Stop = 0x01U\n}   s_State;\n\nstatic U8 s_State2;\n",
     ["s_State", "s_State2", "en_s_Stop"]),
    ("unicode_neighbor", "U8 és_Cnt;\nU8 s_Cnté;\nU8 s_Cnt;\n", ["s_Cnt", "és_Cnt"]),
    ("cr_only_newlines", "U8 a;\rstatic U16 s_Cnt;\r", ["s_Cnt", "a"]),
    ("tabs", "\t\tconst\tU32\ts_Tab\t=\t7\t;\n", ["s_Tab"]),
    ("name_absent", "U8 other;\n" * 50, ["s_Cnt"]),
    ("regex_special_name_falls_back", "U8 a.b;\nU8 axb;\n", ["a.b", "axb"]),
    ("struct_enum_types", "struct Foo s_F = {0};\nenum Color s_C;\nunion U s_U[2];\n", ["s_F", "s_C", "s_U"]),
    ("name_used_as_type_elsewhere", "U8 s_Cnt;\ns_Cnt other;\n", ["s_Cnt", "other"]),
    ("match_ends_on_next_line_swallows_it", "U8 s_A\n= s_B;\nU8 s_B;\n", ["s_A", "s_B"]),
    ("empty_file", "", ["s_Cnt"]),
    # (리뷰 I1) 이름에 개행이 들어 자기겹침하는 이상값 — 후보를 `len(name)` 씩 건너뛰면 둘째 후보(다른 줄)를 놓친다.
    ("newline_in_name_self_overlap", "a\nU8 a\nU8 a;", ["a\nU8 a", "a"]),
]


@pytest.mark.parametrize("label,text,names", CASES, ids=[c[0] for c in CASES])
def test_matches_reference_implementation_from_file(tmp_path, label, text, names):
    p = _write(tmp_path, text)
    loaded = _read_text_limited(Path(p))
    for name in names:
        assert _infer_type_from_file(p, name) == _ref_infer(loaded, name), (label, name)
        assert _new_on_text(loaded, name) == _ref_infer(loaded, name), (label, name, "cache 경로")


def test_explicit_expectations(tmp_path):
    """참조 구현이 틀렸다면 위 대조는 같이 틀린다 — 몇 개는 값을 못박는다."""
    p = _write(tmp_path, "\n\n   static U8 s_Cnt = 3;\r\nvoid f(U8 s_X);\r\nstatic U16 s_X[4];\r\nU8 xs_Y;\r\n")
    assert _infer_type_from_file(p, "s_Cnt") == ("U8", "")
    assert _infer_type_from_file(p, "s_X") == ("U16", ""), "`(` 줄은 건너뛰고 뒤의 진짜 선언을 찾아야 한다"
    assert _infer_type_from_file(p, "s_Y") == ("", ""), "긴 식별자 안의 부분 문자열은 통단어가 아니다"
    assert _infer_type_from_file(p, "absent") == ("", "")
    assert _infer_type_from_file("", "s_Cnt") == ("", "") and _infer_type_from_file(p, "") == ("", "")


_TOKENS = ["s_Cnt", "s_Cnt2", "xs_Cnt", "és_Cnt", "U8", "U16", "static", "extern", "const", "volatile", "struct",
           "=", "[", "]", ";", "(", ")", "{", "}", ",", "\n", "\n", "\r\n", "\r", " ", " ", "  ", "\t",
           "/*", "*/", "x", "3", "s", "_"]
_NAMES = ["s_Cnt", "U8", "x", "s", "_", "és_Cnt", "s\nU8"]


def _signature(text: str, name: str):
    pattern = re.compile(rf"^\s*(.+?)\b{re.escape(name)}\b\s*(=|\[|;)", re.M)
    ref = [(m.start(1), m.end(1), m.end(), m.group(2)) for m in pattern.finditer(text)]
    new = [(m.start(1), m.end(1), m.end(), m.group(2)) for m in _iter_decl_matches(text, name, pattern)]
    return ref, new


def test_random_texts_match_finditer_match_for_match():
    """고정 시드 무작위 대조 — 매치의 group(1) 범위·끝 위치·종결 기호가 finditer 와 같고, 최종 결과도 같다."""
    rng = random.Random(20260916)
    checked = 0
    for _ in range(1500):
        text = "".join(rng.choice(_TOKENS) for _ in range(rng.randint(1, 40)))
        for name in _NAMES:
            ref, new = _signature(text, name)
            assert ref == new, (repr(text), name, ref, new)
            assert _new_on_text(text, name) == _ref_infer(text, name), (repr(text), name)
            checked += 1
    assert checked == 1500 * len(_NAMES)


_CRAFTED = [
    ("blank_lines_before_decl", "\n\n  U8 s_A;\n", "s_A"),
    ("consumed_next_line_is_not_retried", "f( s_A\n= s_A;\nU8 s_A;\n", "s_A"),
    ("same_line_twice_yields_once", "U8 s_A = s_A_INIT; s_A[0] = 1;\n", "s_A"),
    ("terminator_on_next_line", "U8 s_A\n= s_A;\n", "s_A"),
    ("rejected_then_later_line", "void f(U8 s_A);\nstatic U8 s_A;\n", "s_A"),
    ("cr_only", "U8 a;\rstatic U16 s_A;\r", "s_A"),
    ("tail_without_newline", "U8 s_A", "s_A"),
]


@pytest.mark.parametrize("label,text,name", _CRAFTED, ids=[c[0] for c in _CRAFTED])
def test_crafted_texts_match_finditer_match_for_match(label, text, name):
    ref, new = _signature(text, name)
    assert ref == new, (label, ref, new)
    assert _new_on_text(text, name) == _ref_infer(text, name)


def test_non_word_name_with_inverted_boundary_still_matches_finditer():
    """`*p` 처럼 비단어 문자로 시작하는 이름은 `\\b` 의 뜻이 뒤집힌다(앞 글자가 **단어 문자**여야 경계). 통단어 판정을
    원 정규식에 맡기므로 후보 줄 탐색은 이 경우에도 같다."""
    text = "x*p;\nU8 *p;\n"
    assert _new_on_text(text, "*p") == _ref_infer(text, "*p") == ("x", "")


def test_regex_special_name_matches_finditer_verbatim():
    """정규식 토큰이 섞인 이름은 `re.escape` 로 리터럴 — 후보 줄 탐색도 리터럴 부분 문자열이라 같다."""
    text = "U8 a.b;\nU8 axb;\n"
    pattern = re.compile(rf"^\s*(.+?)\b{re.escape('a.b')}\b\s*(=|\[|;)", re.M)
    assert [m.span() for m in _iter_decl_matches(text, "a.b", pattern)] == [m.span() for m in pattern.finditer(text)]
    assert _new_on_text(text, "a.b") == ("U8", "") == _ref_infer(text, "a.b")


class TestCacheChangesTheReadCount:
    def _count_reads(self, monkeypatch, fail_first: Exception | None = None):
        """읽기(`_read_bytes_resolver_aware`) 호출을 센다. `fail_first` 를 주면 **첫 호출만** 그 예외로 실패시킨다."""
        calls: List[str] = []
        real = RU._read_bytes_resolver_aware

        def counting(path, *a, **k):
            calls.append(str(path))
            if fail_first is not None and len(calls) == 1:
                raise fail_first
            return real(path, *a, **k)

        monkeypatch.setattr(RU, "_read_bytes_resolver_aware", counting)
        return calls

    def test_one_read_per_file_with_cache_and_one_per_call_without(self, tmp_path, monkeypatch):
        p = _write(tmp_path, "U8 a;\nU16 b;\nU32 c;\n")
        calls = self._count_reads(monkeypatch)
        cache: dict = {}
        out = [_infer_type_from_file(p, n, cache=cache) for n in ("a", "b", "c", "zzz")]
        assert out == [("U8", ""), ("U16", ""), ("U32", ""), ("", "")]
        assert len(calls) == 1 and set(cache) == {p}, "캐시가 있으면 파일당 1회"
        calls.clear()
        assert [_infer_type_from_file(p, n) for n in ("a", "b")] == [("U8", ""), ("U16", "")]
        assert len(calls) == 2, "기본값(None)은 옛 동작 — 호출마다 읽는다"

    def test_cache_is_per_file(self, tmp_path, monkeypatch):
        p1 = _write(tmp_path, "U8 s_Cnt;\n", "a.c")
        p2 = _write(tmp_path, "U16 s_Cnt;\n", "b.c")
        calls = self._count_reads(monkeypatch)
        cache: dict = {}
        assert _infer_type_from_file(p1, "s_Cnt", cache=cache) == ("U8", "")
        assert _infer_type_from_file(p2, "s_Cnt", cache=cache) == ("U16", "")
        assert _infer_type_from_file(p1, "s_Cnt", cache=cache) == ("U8", "")
        assert len(calls) == 2 and set(cache) == {p1, p2}

    def test_missing_file_is_cached_as_empty(self, tmp_path, monkeypatch):
        """없는 파일은 다시 읽어도 없다 — 빈 원문으로 캐시(옛 판과 같은 `("", "")`, 읽기 시도는 1회)."""
        p = str(tmp_path / "missing.c")
        calls = self._count_reads(monkeypatch)
        cache: dict = {}
        assert _infer_type_from_file(p, "s_Cnt", cache=cache) == ("", "")
        assert _infer_type_from_file(p, "s_Cnt2", cache=cache) == ("", "")
        assert len(calls) == 1 and cache == {p: ""}

    @pytest.mark.parametrize("exc", [PermissionError("worker timeout"), OSError("ipc"), RuntimeError("boom")],
                             ids=["PermissionError", "OSError", "RuntimeError"])
    def test_transient_read_failure_is_not_cached(self, tmp_path, monkeypatch, exc):
        """(리뷰 W1) 워커 타임아웃 같은 일시 실패를 빈 원문으로 굳히면 그 파일의 **나머지 전역 전부**가 조용히 타입 없음이 된다.
        실패한 호출은 옛 판처럼 `("", "")` 이지만 캐시엔 남지 않고, 다음 심볼이 다시 읽어 회복한다."""
        p = _write(tmp_path, "U8 a;\nU16 b;\nU32 c;\n")
        calls = self._count_reads(monkeypatch, fail_first=exc)
        cache: dict = {}
        out = [_infer_type_from_file(p, n, cache=cache) for n in ("a", "b", "c")]
        assert out == [("", ""), ("U16", ""), ("U32", "")], "첫 호출만 실패하고 다음 심볼은 회복해야 한다"
        assert len(calls) == 2, "실패 1회 + 성공 1회 — 성공한 원문만 캐시된다"
        assert set(cache) == {p} and cache[p].startswith("U8 a;")


def test_generator_passes_one_shared_run_scoped_cache_to_both_call_sites():
    """소스 가드 — 두 호출부가 같은 이름의 캐시를 넘기고, 그 캐시는 함수 안에서 만들어진다(모듈 전역이면 파일이 바뀐 뒤에도 남는다)."""
    src_path = Path(RU.__file__).resolve().parent / "uds_generator.py"
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "generate_uds_source_sections")
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_infer_type_from_file"]
    assert len(calls) == 2, "호출부 수가 바뀌었다 — 새 호출부도 캐시를 넘기는지 확인할 것"
    cache_names = set()
    for call in calls:
        kw = {k.arg: k.value for k in call.keywords}
        assert "cache" in kw, f"{call.lineno}: 캐시를 넘기지 않는 호출부 — 그쪽은 전역마다 파일을 다시 읽는다"
        assert isinstance(kw["cache"], ast.Name)
        cache_names.add(kw["cache"].id)
    assert len(cache_names) == 1, f"두 호출부가 다른 캐시를 쓴다: {cache_names}"
    (cache_name,) = cache_names

    def _targets(nodes):
        out = set()
        for n in nodes:
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                out.add(n.target.id)
            elif isinstance(n, ast.Assign):
                out.update(t.id for t in n.targets if isinstance(t, ast.Name))
        return out

    assert cache_name in _targets(ast.walk(fn)), "캐시가 함수 안에서 만들어지지 않는다"
    assert cache_name not in _targets(tree.body), "모듈 전역 캐시 — SVN 갱신 뒤에도 옛 원문이 남는다"
