"""배열 **선언 크기**를 파서가 통째로 버리던 경로.

## 왜 필요한가 (KJPDS02_PV 정본 실측, 2026-08-12)

정본 SUTS 는 배열을 **원소 단위로 펼쳐** 입력 열에 적는다:

    Inpt[0]=u8s_DataBuffer[0]  Inpt[1]=u8s_DataBuffer[1]  …  Inpt[59]=u8s_DataBuffer[59]

    정본 입력 엔트리 6,014 중 `name[N]` 형태  **3,023 (50.3%)**
    그 3,023 을 만드는 base 이름                134 개 / 인스턴스 289
    base 134 중 **모든 unit 에서 같은 개수**    120 개
    인덱스 289 중 연속 283 · 그중 0부터 시작    246
    최대 원소 수                                60

즉 정본이 펼치는 근거는 **관찰된 접근 첨자가 아니라 선언 크기**다
(`u8s_DataBuffer[u8t_Idx]` 처럼 첨자가 변수여도 0..59 를 다 적는다).

## 무엇이 문제였나

`_extract_decl_name_and_type` 의 이름 정규식이 배열 부분을 **매치만 하고 캡처하지
않는다**:

    re.search(r"([A-Za-z_]\\w*)\\s*(?:\\[[^\\]]*\\])?\\s*$", text)
                                    ^^^^^^^^^^^^^^^^ 버려진다

그래서 `static U8 u8s_DataBuffer[60];` 이
`{'name': 'u8s_DataBuffer', 'type': 'U8'}` 로만 남는다. 디스크 캐시
(`.devops_pro_cache/source_sections/*.json` 의 `static_vars`)에서도 확인된다:

    ['u8s_DataBuffer', 'U8', '/* Entry validity flag */', '', '']   ← `[60]` 없음

크기가 없으면 원소 확장의 근거 자체가 없다.

⚠ 이 커밋은 **크기를 붙잡는 데까지**다. 원소 확장(열 예산 96 과의 조정 포함)은
  라이브 대조 후 별건으로 간다 — 없는 회수를 미리 적지 않는다.
"""
from __future__ import annotations

import pytest

from report_gen.source_parser import _decl_array_dim, _extract_c_global_candidates


class TestDeclArrayDim:
    @pytest.mark.parametrize(
        "decl,dim",
        [
            ("u8s_DataBuffer[60]", "[60]"),
            ("RVL[9]", "[9]"),
            ("buf[MAX_LEN]", "[MAX_LEN]"),
            ("m[MAX][2]", "[MAX][2]"),
            ("*p[3]", "[3]"),
            ("x[ 10 ]", "[10]"),
        ],
    )
    def test_dimension_is_captured(self, decl, dim):
        assert _decl_array_dim(decl) == dim

    @pytest.mark.parametrize("decl", ["plain", "*ptr", "", "   "])
    def test_non_array_yields_empty(self, decl):
        assert _decl_array_dim(decl) == ""

    def test_incomplete_size_is_kept_as_empty_brackets(self):
        """`extern U8 x[];` 는 크기를 **모르는** 것이다.

        `""`(배열 아님)과 구분돼야 한다 — 확장 소비처가 "0개로 펼쳐라" 로 읽으면
        변수가 통째로 사라진다.
        """
        assert _decl_array_dim("x[]") == "[]"

    @pytest.mark.parametrize("decl", ["(*cb)(void)", "(*pfn)(int, char)"])
    def test_function_pointer_is_not_an_array(self, decl):
        """`(*cb)(void)` 의 `(void)` 를 차원으로 읽으면 없는 배열이 생긴다."""
        assert _decl_array_dim(decl) == ""

    @pytest.mark.parametrize("decl", ["(*p)[10]", "(*rows)[COLS]"])
    def test_pointer_to_array_is_not_the_variable_size(self, decl):
        """⚠ `(*p)[10]` 은 **10개짜리 배열을 가리키는 포인터**다 — `p` 자체가 10개가 아니다.

        괄호 가드가 없으면 정규식이 뒤쪽 `[10]` 을 그대로 집어와, 원소 확장이
        존재하지 않는 10개 원소를 만들어낸다.
        """
        assert _decl_array_dim(decl) == ""

    def test_initializer_does_not_leak(self):
        """`= {0}` 쪽 괄호/대괄호를 차원으로 읽으면 안 된다."""
        assert _decl_array_dim("u8s_Buf[8] = {0}") == "[8]"
        assert _decl_array_dim("g_x = arr[3]") == ""


class TestGlobalCandidatesCarryTheDimension:
    @pytest.mark.parametrize(
        "stmt,expect",
        [
            ("static U8 u8s_DataBuffer[60];", [("u8s_DataBuffer", "[60]")]),
            ("static volatile word RVL[9];", [("RVL", "[9]")]),
            ("extern U8 u8g_PartNo[10];", [("u8g_PartNo", "[10]")]),
            ("static U8 plain;", [("plain", "")]),
        ],
    )
    def test_dimension_reaches_the_candidate(self, stmt, expect):
        got = [(g["name"], g["array"]) for g in _extract_c_global_candidates(stmt)]
        assert got == expect

    def test_each_declarator_keeps_its_own_dimension(self):
        """⚠ 한 문장에 여러 선언자가 오면 **각자의** 크기를 가져야 한다.

        선언문 전체에서 마지막 `[...]` 를 쓰면 `a` 와 `c` 가 같은 크기가 된다.
        """
        got = [(g["name"], g["array"]) for g in _extract_c_global_candidates("U8 a[3], b, c[7];")]
        assert got == [("a", "[3]"), ("b", ""), ("c", "[7]")]

    def test_existing_fields_are_unchanged(self):
        """추가 필드가 기존 계약을 흔들면 회귀다(소비처가 name/type/static/extern 을 읽는다)."""
        g = _extract_c_global_candidates("static U8 u8s_DataBuffer[60];")[0]
        assert g["name"] == "u8s_DataBuffer"
        assert g["type"] == "U8"
        assert g["static"] == "true" and g["extern"] == "false"
