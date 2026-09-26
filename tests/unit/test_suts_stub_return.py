"""stub return — 피호출 함수의 반환값이 정본의 시험 **입력**이다.

## 왜 (KJPDS02_PV 실측, 2026-08-19)

정본 SUTS 의 Inpt 열은 이 unit 이 호출하는 함수의 반환값을 적는다. VectorCAST 가
피호출 함수를 stub 하고 그 반환값을 주입하기 때문이다.

    정본:  u16g_Conv_AngleToPulse() return      우리: (없음 — 0칸)
    규모:  입력 198칸 · 136 unit · 피호출 함수 **100% 가 비-void**

12라운드 동안 이 축을 한 번도 안 냈다. 남은 결손의 성격이 입도차(578칸)에서
**이름 부재(655칸)** 로 넘어간 뒤에야 보였다.

## ⚠ 정본이 **어느** callee 를 stub 하는지 가르는 정적 신호는 없다

네 가지를 재고 전부 실패했다. 다음 라운드가 같은 데를 다시 파지 않도록 숫자를 남긴다:

    후보                일치   채운행 과다   정밀도
      calls_list        189       253        42.8%   ← 채택
      called             81       156        34.2%
      calling(역방향)      0       230         0.0%
      logic 등장분만     178       250        41.6%   ← 필터가 오히려 나쁘다
      파일 경계         채택 79.9% vs 미채택 69.9% — 방향이 **반대**라 신호 아님

그럼에도 채택한 이유는 4차(맨이름 규칙)·12차(통짜 표기) 기각과 성격이 다르기
때문이다 — 저 둘은 **순손실**(이미 맞던 78건이 깨짐)과 **근거 부족**(6칸)이었고,
여기는 **사라진 맞춤 0** 에 순증 +189(입력 재현율 87.2% → 90.3%)다. 과다 253 도
지어낸 이름이 아니라 **실제로 호출하는 비-void 함수**라 stub 가능한 실재 대상이다.

## ⚠ 두 가지 계약이 이 파일의 본체다

1. **입력 열 전용** — 정본 ExpR 의 stub return 은 **0칸**이다.
2. **SwUDS 이름 대체보다 뒤** — 대체는 `input_vars` 를 통째로 교체하므로, 앞에 넣으면
   조용히 사라진다. `test_survives_uds_replacement` 가 그 순서를 고정한다.
"""
from __future__ import annotations

import logging

from generators.suts import (
    _nonvoid_function_names,
    _stub_return_names,
    collect_unit_functions,
)


class TestNonvoidFunctionNames:
    def test_return_slot_marks_nonvoid(self):
        got = _nonvoid_function_names({"a": {"name": "F", "outputs": ["[OUT] return U8"]}})
        assert got == {"F"}

    def test_void_function_is_absent(self):
        got = _nonvoid_function_names({"a": {"name": "V", "outputs": ["[OUT] g_Flag"]}})
        assert got == set()

    def test_direction_tag_is_optional(self):
        """태그 제거는 기존 `_DIR_TAG_PAT` 을 쓴다 — 태그 유무로 판정이 갈리면 안 된다."""
        assert _nonvoid_function_names(
            {"a": {"name": "F", "outputs": ["return U8"]}}) == {"F"}

    def test_return_prefixed_identifier_is_not_a_return_slot(self):
        """⚠ `returnValue` 는 반환 슬롯이 아니다.

        `_RETURN_SLOT_RE` 의 단어 경계가 이걸 막는다. 앵커만 있고 경계가 없으면
        이런 이름을 가진 출력 전역이 함수를 통째로 비-void 로 만든다.
        """
        assert _nonvoid_function_names(
            {"a": {"name": "F", "outputs": ["[OUT] returnValue"]}}) == set()

    def test_nameless_entry_never_pollutes_the_set(self):
        """빈 이름이 들어가면 하류의 `nm in nonvoid` 가 빈 문자열을 통과시킨다."""
        got = _nonvoid_function_names({"a": {"name": "", "outputs": ["[OUT] return U8"]}})
        assert got == set()
        assert "" not in got

    def test_empty_input_is_not_a_crash(self):
        assert _nonvoid_function_names({}) == set()
        assert _nonvoid_function_names(None) == set()


class TestStubReturnNames:
    def test_only_nonvoid_callees_survive(self):
        assert _stub_return_names(["F", "V"], {"F"}) == ["F() return"]

    def test_duplicates_collapse_and_order_is_stable(self):
        assert _stub_return_names(["B", "A", "B"], {"A", "B"}) == ["B() return", "A() return"]

    def test_blank_entries_are_ignored(self):
        assert _stub_return_names(["", "  ", None], {"F"}) == []

    def test_missing_calls_list_is_empty_not_a_crash(self):
        assert _stub_return_names(None, {"F"}) == []

    def test_empty_nonvoid_set_yields_nothing(self):
        """비-void 집합이 비면 아무것도 안 낸다 — 이 축이 통째로 죽는 상태다."""
        assert _stub_return_names(["F"], set()) == []


def _fd(**funcs):
    """`{이름: (calls_list, outputs)}` → function_details."""
    out = {}
    for i, (nm, (calls, outs)) in enumerate(funcs.items(), start=1):
        out[f"SwUFn_{i:04d}"] = {
            "id": f"SwUFn_{i:04d}", "name": nm, "prototype": f"void {nm}(void)",
            "file": "q.c", "inputs": [], "outputs": list(outs),
            "globals_global": [], "globals_static": [], "logic_flow": [],
            "calls_list": list(calls),
        }
    return out


def _uds(**by_name):
    return {"by_name": dict(by_name)}


def _by(units, name):
    return next(u for u in units if u["name"] == name)


class TestCollectWiring:
    def test_stub_lands_in_the_input_column(self):
        units = collect_unit_functions(
            _fd(Caller=(["Callee"], []), Callee=([], ["[OUT] return U8"])),
            sds_map={},
        )
        assert "Callee() return" in _by(units, "Caller")["input_vars"]

    def test_stub_never_lands_in_the_expected_column(self):
        """⚠ 이 파일의 핵심 계약 — 정본 ExpR 의 stub return 은 0칸이다."""
        units = collect_unit_functions(
            _fd(Caller=(["Callee"], []), Callee=([], ["[OUT] return U8"])),
            sds_map={},
        )
        assert not [v for v in _by(units, "Caller")["output_vars"] if "() return" in v]

    def test_void_callee_is_not_stubbed(self):
        units = collect_unit_functions(
            _fd(Caller=(["Quiet"], []), Quiet=([], ["[OUT] g_Flag"])),
            sds_map={},
        )
        assert not [v for v in _by(units, "Caller")["input_vars"] if "() return" in v]

    def test_survives_uds_replacement(self):
        """⚠ SwUDS 대체는 `input_vars` 를 **통째로 교체**한다.

        stub 추가를 그 **앞**에 두면 조용히 사라진다. 이 테스트가 순서를 고정한다 —
        산출물만 봐서는 안 보이는 종류의 결함이다.
        """
        units = collect_unit_functions(
            _fd(Caller=(["Callee"], []), Callee=([], ["[OUT] return U8"])),
            sds_map={},
            uds_io_map=_uds(Caller={"inputs": ["u8_DocSaysThis"], "outputs": []}),
        )
        got = _by(units, "Caller")["input_vars"]
        assert "u8_DocSaysThis" in got, got
        assert "Callee() return" in got, got

    def test_unknown_callee_is_not_stubbed(self):
        """`function_details` 에 없는 함수는 비-void 인지 알 수 없다 — 지어내지 않는다."""
        units = collect_unit_functions(_fd(Caller=(["NeverHeardOf"], [])), sds_map={})
        assert not [v for v in _by(units, "Caller")["input_vars"] if "() return" in v]


class TestScopeReport:
    def test_note_reports_added_count(self, caplog):
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            collect_unit_functions(
                _fd(Caller=(["Callee"], []), Callee=([], ["[OUT] return U8"])),
                sds_map={},
            )
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "stub return 1칸" in msgs, msgs

    def test_no_nonvoid_says_undetermined_not_zero(self, caplog):
        """⚠ 비-void 0개는 "stub 0칸" 이 아니라 **판정 못 함**이다.

        파서가 `[OUT] return` 을 안 냈다는 뜻이라 축이 통째로 죽는다. 0 으로 적으면
        "호출이 없다"와 "판정을 못 했다"가 같은 말이 된다.
        """
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            collect_unit_functions(_fd(Caller=(["Callee"], [])), sds_map={})
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "stub return 판정 안 함" in msgs, msgs
        assert "stub return 0칸" not in msgs, msgs


class TestBudgetTruncation:
    def test_truncation_is_reported_not_silent(self, caplog):
        """⚠ `input_vars[:max_inp]` 는 경고 없이 자른다 — 그 침묵을 걷는다.

        ⚠ **안 잘리는 unit 을 반드시 섞는다.** 잘리는 unit 만 두면 음수 클램프가
          있으나 없으나 같은 수가 나와 뮤테이션이 산다(1회차에 그렇게 생존했다).
          `Small` 은 90칸이라 클램프가 없으면 −6 을 보태 104 → 98 로 어긋난다.
        ⚠ **문구가 아니라 숫자를 단언한다** — 문구만 보면 집계가 틀려도 초록이다.
        """
        fd = _fd(Big=([], []), Small=([], []))
        fd["SwUFn_0001"]["globals_global"] = [f"[IN] U8 g_V{i}" for i in range(200)]
        fd["SwUFn_0002"]["globals_global"] = [f"[IN] U8 g_S{i}" for i in range(90)]
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            collect_unit_functions(fd, sds_map={})
        msgs = " ".join(r.getMessage() for r in caplog.records)
        # 200 − 96(열 상한) = 104. `Small` 은 한 칸도 안 보탠다.
        assert "예산 절단 1unit(입력 104칸" in msgs, msgs

    def test_no_truncation_stays_quiet(self, caplog):
        """음성 대조군 — 안 잘렸는데 절단을 외치면 경고가 무의미해진다."""
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            collect_unit_functions(_fd(Small=([], [])), sds_map={})
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "예산 절단" not in msgs, msgs
