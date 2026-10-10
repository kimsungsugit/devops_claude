"""중간 마디 배열 — **불성립 이름** 교정.

## 왜 (KJPDS02_PV 실측, 2026-08-18)

    우리:  pst_Queue[0].ast_Queue.u16_Addr1
    선언:  ST_SAFE_WRITE_QUEUE_ENTRY ast_Queue[SAFE_WRITE_QUEUE_SIZE];   /* = 16 */

**배열에 `.멤버` 는 못 붙인다.** 이건 입도(granularity) 문제가 아니라 C 로 성립하지
않는 이름이다. 첨자를 잃는 자리는 SwUDS 이름 대체다 — 문서는 `ast_Queue[x]`
(자리표시자) · `ast_Queue[16]`(선언 크기)로 적는데 `uds_unit_io.clean_param_name` 이
첨자를 **의도적으로** 전부 뗀다. 그 규칙은 옳다(문서 `CSL[9]` vs 소스 `U8 CSL[8]` —
문서 숫자를 믿으면 없는 원소를 만든다). 다만 되붙일 자리가 **꼬리와 root 뿐**이라
중간 마디가 갈 곳이 없었다.

정본도 이 배열을 펼쳐 적는다:

    s_Lib_SafeWriteQueue_Enqueue  기대 열   ast_Queue[0..15] × 멤버 5 = 80칸
    s_Lib_SafeWriteQueue_Dequeue  입력 열   ast_Queue[0]·[7]·[15] × 멤버 5 = 15칸

## ⚠ 폭은 **선언 크기 전량**이다 — 정본의 {0,7,15} 를 규칙화하지 않는다

정본 전수에서 첨자 2개 이상인 배열 그룹의 **87~94% 가 0..k 연속**이고 불연속은
입력 3.6% · 기대 1.3% 뿐인데, 그 불연속 11건 중 **5건이 바로 이 배열**이다. 즉
{첫·중간·끝} 은 정본의 관행이 아니라 이 한 배열의 개별 선택이라 규칙화하면
과적합이다(12차에서 `name[SIZE]` 통짜 표기를 6칸 근거로 기각한 것과 같은 판정).
게다가 Enqueue 기대 열은 같은 배열을 **16개 전량**으로 적는다 — 좁히면 그 77칸이
under-specification 이 된다.

## ⚠ 파라미터 타입은 **중간 마디에만** 쓴다

11차가 파라미터 타입으로 **꼬리**를 펼치는 정책(S1p)을 실측으로 기각했다
(일치 +34 · 과다 +176 — `SHA256_CTX.buffer[64]` 통째 확장). 꼬리는 안 펼쳐도
`ctx[0].buffer` 가 **성립하는** 이름이라 그건 취향 문제지만, 중간 마디는 안 붙이면
틀린 이름이라 성격이 다르다. 이 파일의 `test_param_tail_is_still_not_expanded` 가
그 경계를 고정한다.
"""
from __future__ import annotations

import pytest

from generators.suts import (
    _declared_type_map,
    _expand_array_entries,
    _mid_member_sizes,
    _root_type_hints,
    collect_unit_functions,
)

# `ST_SAFE_WRITE_QUEUE` 의 실제 모양(NE1AW_PORTING/Lib/Lib_SafeWriteQueue_it.h:47)
_SM = {
    "ST_SAFE_WRITE_QUEUE": {"ast_Queue": "[16]"},
    "SHA256_CTX": {"buffer": "[64]", "state": "[8]"},
    "Outer": {"mid": "[3]", "mid.leaf": "[2]"},
    # ⚠ 매크로 이름 **안에 숫자**가 있어야 이 축을 잰다. `[SIGNATURE_SIZE]` 처럼
    #   숫자가 없으면 `\d+` 를 긁는 잘못된 구현도 빈 결과를 내 테스트가 공허해진다.
    "NoDim": {"sig": "[DATA_LEN2]"},
    # 꼬리만 배열인 파라미터 타입 — 여기가 11차가 기각한 S1p 자리다.
    "TailOnly": {"a.b": "[4]"},
}


class TestRootTypeHints:
    def test_param_type_prefix_is_read(self):
        """파라미터는 `globals_info` 에 없다 — 엔트리 접두가 **유일한** 타입 출처다."""
        got = _root_type_hints(["[INOUT] ST_SAFE_WRITE_QUEUE* pst_Queue->ast_Queue"])
        assert got["pst_Queue"] == "ST_SAFE_WRITE_QUEUE"

    def test_cv_qualifier_and_star_are_stripped(self):
        got = _root_type_hints(["[IN] const ST_SAFE_WRITE_PARAMS* pst_Params->u8_Data"])
        assert got["pst_Params"] == "ST_SAFE_WRITE_PARAMS"

    def test_dot_and_subscript_forms_reduce_to_root(self):
        got = _root_type_hints([
            "[IN] SHA256_CTX* ctx[0].state",
            "[IN] Outer g_Out.mid.leaf",
        ])
        assert got["ctx"] == "SHA256_CTX"
        assert got["g_Out"] == "Outer"

    def test_declaration_wins_over_entry_prefix(self):
        """⚠ 전역은 **선언**이 옳다. 엔트리 접두는 호출 지점 표기라 어긋날 수 있다."""
        got = _root_type_hints(
            ["[IN] WrongType g_Out.mid.leaf"],
            declared_types=_declared_type_map({"g_Out": {"type": "const Outer"}}),
        )
        assert got["g_Out"] == "Outer"

    def test_declared_type_map_strips_qualifiers_once(self):
        """선언 맵은 루프 **밖에서 한 번** 만든다 — 안에서 만들면 176만 회 헛돈다."""
        got = _declared_type_map({"a": {"type": "volatile T"}, "b": {"type": ""}, "c": None})
        assert got == {"a": "T"}

    def test_bare_name_without_type_is_skipped(self):
        """음성 대조군 — 토큰이 하나뿐이면 타입이 없는 것이다."""
        assert _root_type_hints(["[IN] lonely"]) == {}

    def test_return_slot_does_not_become_a_root(self):
        got = _root_type_hints(["[OUT] return U8 (range: 0 ~ 255)"])
        assert "return" not in got and "U8" not in got


class TestMidMemberSizes:
    def test_mid_array_is_found(self):
        got = _mid_member_sizes(
            ["pst_Queue[0].ast_Queue.u16_Addr1"],
            {"pst_Queue": "ST_SAFE_WRITE_QUEUE"}, _SM,
        )
        assert got == {"pst_Queue[0].ast_Queue.u16_Addr1": (1, (16,))}

    def test_two_node_name_is_not_mid(self):
        """음성 대조군 — `A.B` 의 `B` 는 **꼬리**다. `sizes` 가 맡는다."""
        assert _mid_member_sizes(
            ["ctx[0].state"], {"ctx": "SHA256_CTX"}, _SM) == {}

    def test_already_subscripted_mid_is_left_alone(self):
        assert _mid_member_sizes(
            ["pst_Queue[0].ast_Queue[3].u16_Addr1"],
            {"pst_Queue": "ST_SAFE_WRITE_QUEUE"}, _SM,
        ) == {}

    def test_unknown_type_yields_nothing(self):
        assert _mid_member_sizes(
            ["p[0].ast_Queue.u16_Addr1"], {"p": "NoSuchType"}, _SM) == {}

    def test_non_numeric_dimension_is_rejected(self):
        """⚠ `[DATA_LEN2]` 에서 `\\d+` 를 긁으면 크기 2 를 **지어낸다**.

        매크로 이름에 숫자가 든 형태라야 이 축이 실제로 재진다 —
        `[SIGNATURE_SIZE]` 로 쓰면 잘못된 구현도 빈 결과라 테스트가 공허하다.
        """
        assert _mid_member_sizes(["g[0].sig.x"], {"g": "NoDim"}, _SM) == {}

    def test_array_at_the_tail_is_not_a_mid_node(self):
        """⚠ 꼬리 배열은 여기 소관이 아니다 — 11차가 기각한 S1p 자리다.

        `p[0].a.b` 에서 배열인 건 `a.b`(꼬리)다. 파라미터 타입으로 여길 펼치면
        `SHA256_CTX.buffer[64]` 통째 확장이 되살아난다(일치 +34 · 과다 +176).
        """
        assert _mid_member_sizes(["p[0].a.b"], {"p": "TailOnly"}, _SM) == {}

    def test_deeper_path_is_supported(self):
        """`a.b.c.d` 에서 `b.c` 가 배열이면 마디 2 뒤에 붙는다."""
        got = _mid_member_sizes(
            ["g_Out.mid.leaf.x"], {"g_Out": "Outer"}, _SM)
        # `mid` 가 먼저 걸린다(첫 배열 마디) — 결정적 규칙이다.
        assert got == {"g_Out.mid.leaf.x": (1, (3,))}


class TestMidExpansion:
    def test_subscript_lands_on_the_mid_node(self):
        out, info = _expand_array_entries(
            ["pst_Queue[0].ast_Queue.u16_Addr1"], {}, 96,
            mid_sizes={"pst_Queue[0].ast_Queue.u16_Addr1": (1, (3,))},
        )
        assert out == [
            "pst_Queue[0].ast_Queue[0].u16_Addr1",
            "pst_Queue[0].ast_Queue[1].u16_Addr1",
            "pst_Queue[0].ast_Queue[2].u16_Addr1",
        ]
        assert info["expanded"] == ["pst_Queue[0].ast_Queue.u16_Addr1"]

    def test_mid_wins_over_tail(self):
        """⚠ 둘 다 배열이면 **중간**이 이긴다.

        꼬리만 펼친 `A.B.C[0]` 은 `A.B` 가 배열이라 **여전히 불성립**이고,
        중간만 펼친 `A.B[0].C` 는 C 를 통째 배열로 읽는 성립하는 이름이다.
        """
        out, _ = _expand_array_entries(
            ["a.b.c"], {"a.b.c": (2,)}, 96, mid_sizes={"a.b.c": (1, (2,))},
        )
        assert out == ["a.b[0].c", "a.b[1].c"]

    def test_tail_still_expands_when_no_mid(self):
        """음성 대조군 — 11차 동작이 그대로여야 한다."""
        out, _ = _expand_array_entries(["PS.Data"], {"PS.Data": (3,)}, 96, mid_sizes={})
        assert out == ["PS.Data[0]", "PS.Data[1]", "PS.Data[2]"]

    def test_root_still_expands_when_no_mid(self):
        """음성 대조군 — root 삽입(`at_node == 0`)을 일반 경로로 옮긴 뒤에도 같다."""
        out, _ = _expand_array_entries(
            ["g_Ph.u8_Max"], {}, 96, root_sizes={"g_Ph": (2,)}, mid_sizes={})
        assert out == ["g_Ph[0].u8_Max", "g_Ph[1].u8_Max"]

    def test_budget_shortfall_leaves_the_name_untouched(self):
        """⚠ 자르지 않고 **안 펼친다**. 자르면 없는 사실을 문서에 적는다."""
        out, info = _expand_array_entries(
            ["x.arr.m", "keep"], {}, 4, mid_sizes={"x.arr.m": (1, (16,))})
        assert out == ["x.arr.m", "keep"]
        assert info["skipped"][0]["name"] == "x.arr.m"

    def test_mid_sizes_omitted_is_previous_behaviour(self):
        out, _ = _expand_array_entries(["x.arr.m"], {}, 96)
        assert out == ["x.arr.m"]


def _fd(name, inputs, outputs):
    return {"a": {"id": "SwUFn_0101", "name": name, "prototype": f"void {name}(void)",
                  "file": "q.c", "inputs": list(inputs), "outputs": list(outputs),
                  "globals_global": [], "globals_static": [], "logic_flow": []}}


def _uds(**by_name):
    return {"by_name": dict(by_name)}


class TestCollectWiring:
    def test_source_parsed_whole_array_stays_a_tail(self):
        """소스 파싱만으로는 `p[0].arr` 두 마디라 중간 경로가 아니다.

        그리고 그건 **성립하는** 이름이라 파라미터 타입으로 펼치지 않는다(S1p 기각).
        """
        units = collect_unit_functions(
            _fd("s_Deq",
                ["[INOUT] ST_SAFE_WRITE_QUEUE* pst_Queue->ast_Queue"],
                ["[OUT] return U8"]),
            sds_map={},
            struct_members={"ST_SAFE_WRITE_QUEUE": {"ast_Queue": "[3]"}},
        )
        assert units[0]["input_vars"] == ["pst_Queue[0].ast_Queue"]

    def test_uds_derived_member_path_expands_at_mid(self):
        """SwUDS 가 준 `p->arr.m` 형태(첨자 제거본)가 중간에서 펼쳐진다.

        이게 실제 결함 경로다 — 문서는 `ast_Queue[x].u16_Addr1` 로 적고,
        `clean_param_name` 이 `[x]` 를 떼면 `p->arr.m` 만 남는다.
        """
        units = collect_unit_functions(
            _fd("s_Deq",
                ["[INOUT] ST_SAFE_WRITE_QUEUE* pst_Queue->ast_Queue"],
                ["[OUT] return U8"]),
            sds_map={},
            struct_members={"ST_SAFE_WRITE_QUEUE": {"ast_Queue": "[3]"}},
            uds_io_map=_uds(s_Deq={
                "inputs": ["pst_Queue->ast_Queue.u16_Addr1"], "outputs": []}),
        )
        got = units[0]["input_vars"]
        assert got == [
            "pst_Queue[0].ast_Queue[0].u16_Addr1",
            "pst_Queue[0].ast_Queue[1].u16_Addr1",
            "pst_Queue[0].ast_Queue[2].u16_Addr1",
        ], got

    def test_malformed_name_never_survives(self):
        """⚠ 이 경로의 계약 — 배열 마디에 `.멤버` 가 붙은 이름은 산출물에 없어야 한다."""
        units = collect_unit_functions(
            _fd("s_Deq",
                ["[INOUT] ST_SAFE_WRITE_QUEUE* pst_Queue->ast_Queue"],
                ["[OUT] return U8"]),
            sds_map={},
            struct_members={"ST_SAFE_WRITE_QUEUE": {"ast_Queue": "[3]"}},
            uds_io_map=_uds(s_Deq={
                "inputs": ["pst_Queue->ast_Queue.u16_Addr1"], "outputs": []}),
        )
        assert "pst_Queue[0].ast_Queue.u16_Addr1" not in units[0]["input_vars"]

    def test_param_tail_is_still_not_expanded(self):
        """⚠ 11차가 실측으로 기각한 S1p 를 되살리지 않는다(일치 +34 · 과다 +176).

        `ctx[0].buffer` 는 첨자가 없어도 **성립하는** 이름이라 정본이 안 펼친다.
        """
        units = collect_unit_functions(
            _fd("sha", ["[IN] SHA256_CTX* ctx->buffer"], ["[OUT] return U8"]),
            sds_map={},
            struct_members={"SHA256_CTX": {"buffer": "[64]"}},
        )
        got = units[0]["input_vars"]
        assert "ctx[0].buffer" in got, got
        assert "ctx[0].buffer[0]" not in got, f"파라미터 꼬리가 펼쳐졌다: {got}"


class TestScopeReport:
    def test_note_reports_fixed_count(self, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            collect_unit_functions(
                _fd("s_Deq", ["[INOUT] ST_SAFE_WRITE_QUEUE* pst_Queue->ast_Queue"],
                    ["[OUT] return U8"]),
                sds_map={},
                struct_members={"ST_SAFE_WRITE_QUEUE": {"ast_Queue": "[3]"}},
                uds_io_map=_uds(s_Deq={
                    "inputs": ["pst_Queue->ast_Queue.u16_Addr1"], "outputs": []}),
            )
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "중간마디 배열 복원 1칸" in msgs, msgs

    def test_missing_struct_map_says_so(self, caplog):
        """⚠ 맵이 없으면 '0칸'이 아니라 **안 함**이라고 말한다."""
        import logging
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            collect_unit_functions(
                _fd("s_Deq", ["[IN] U8 a"], ["[OUT] return U8"]), sds_map={})
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "구조체 멤버 맵 없음" in msgs, msgs


@pytest.mark.parametrize("name,expected", [
    ("pst_Queue[0].ast_Queue.u8_Data", (1, (16,))),
    ("pst_Queue.ast_Queue.u8_Data", (1, (16,))),
])
def test_root_subscript_presence_does_not_change_lookup(name, expected):
    """`->` 변환으로 붙은 `[0]` 이 있든 없든 root 키는 같다."""
    assert _mid_member_sizes([name], {"pst_Queue": "ST_SAFE_WRITE_QUEUE"}, _SM)[name] == expected
