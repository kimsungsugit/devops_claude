"""stub 출력 파라미터 — 피호출이 **써 넣는 값**도 정본의 시험 **입력**이다.

## 왜 (KJPDS02_PV 실측, 2026-08-19 · R23)

`test_suts_stub_return.py` 가 연 축의 나머지 절반이다. VectorCAST 가 피호출을
stub 하면 반환값만 주입되는 게 아니다 — 포인터 출력 파라미터에 써 넣을 값도
시험자가 정해야 한다. 그래서 정본 Inpt 열에 이렇게 실린다:

    EEPROM_GetByte() Data[0]        sf_TryAddU32() sum[0]
    sf_LinDataPolling() e_Err[0]    EepSetupFCCOB() pIndex[0]

    정본 표적: 입력 22칸 · 기대 10칸

## ⚠ 이 축은 **과다 축을 처음 재다가** 나왔다

22라운드 동안 미달만 팠다. 과다 2,134칸을 전량 귀속하는 과정에서 "정본에만 있는
표기" 로 걸렸다 — 우리가 못 내는 게 아니라 **낼 생각을 안 한** 칸이었다.

## ⚠ 비-void 조인이 이 축의 전부다

    후보 규칙                     생산   적중   과다   정밀도
      조건 없음([OUT] 전부)        154     12    142     7.8%
      **비-void 피호출만**          35     12     23    34.3%   ← 채택
      out-param 1개뿐               43      9     34    20.9%
      비-void ∧ 1개뿐               28      9     19    32.1%

같은 적중 12 를 과다 142→23 으로 낸다. 우연이 아니다 — 비-void 집합은 우리가 이미
`X() return` 을 내는 대상과 정확히 같고, **stub 되는 함수만** 그 출력 파라미터를
주입받는다. 근거가 같으므로 두 경로는 같은 조인을 쓴다.

라이브 재생성: 입력 5,459(90.8%) → **5,471(91.0%)** · **사라진 맞춤 0** · 사라진 칸 0.

## ⚠ 접미 `[0]` 은 R22 를 뒤집는 게 아니다

R22 가 기각한 건 *배열 변수*에 `[0]` 을 붙이는 것이다(정본의 지배 표기가 base 라
4,895칸 손실). 여기 피호출 출력 파라미터는 정본이 **일관되게 `[0]`** 으로 적는다.
두 표기를 다 쟀다 — `[0]` 적중 12 · 접미 없음 적중 **0**. 이름족이 다르면 표기도 다르다.

## ⚠ 측정이 한 번 틀렸다 — 그 실패를 가드로 고정한다

첫 판은 피호출의 `inputs` 키만 훑어 표적 22 중 15 를 "파서가 태깅을 안 한다" 로
오판했다. 실제로는 `outputs: [OUT] UINT32 * sum` 에 이미 실려 있었다. 한 분류로
몰리면 데이터가 아니라 조회 경로부터 의심할 것 — `test_out_param_in_outputs_key_is_found`
가 그 실패를 되풀이 못 하게 막는다.
"""
from __future__ import annotations

import logging

from generators.suts import (
    _out_param_names_by_function,
    _stub_out_param_names,
    collect_unit_functions,
)


class TestOutParamNamesByFunction:
    def test_out_param_in_outputs_key_is_found(self):
        """⚠ 이 파일에서 가장 중요한 한 줄 — 측정 첫 판이 여기서 틀렸다.

        `sf_TryAddU32(UINT32 base, UINT32 offset, UINT32 *sum)` 의 `sum` 은
        `inputs` 이 아니라 **`outputs`** 에 `[OUT] UINT32 * sum` 으로 실린다.
        """
        got = _out_param_names_by_function(
            {"a": {"name": "F", "outputs": ["[OUT] return U8", "[OUT] UINT32 * sum"]}})
        assert got == {"F": ["sum"]}

    def test_out_param_in_inputs_key_is_found(self):
        got = _out_param_names_by_function(
            {"a": {"name": "F", "inputs": ["[OUT] U8 * p"], "outputs": []}})
        assert got == {"F": ["p"]}

    def test_return_slot_is_never_a_parameter(self):
        """반환값은 `_stub_return_names` 의 몫이다. 여기서 내면 같은 칸을 두 번 적는다."""
        got = _out_param_names_by_function(
            {"a": {"name": "F", "outputs": ["[OUT] return U8"]}})
        assert got == {}

    def test_in_and_inout_params_are_excluded(self):
        """`[INOUT]` 까지 넣으면 생산 35→477 에 적중은 12 그대로다(정밀도 34.3%→3.4%)."""
        got = _out_param_names_by_function({"a": {"name": "F", "inputs": [
            "[IN] U8 plain", "[INOUT] U8 * shared"], "outputs": []}})
        assert got == {}

    def test_untagged_slot_is_not_an_out_param(self):
        """음성 대조군 — 태그가 없으면 방향을 모른다. 모르는 걸 [OUT] 로 치지 않는다."""
        got = _out_param_names_by_function(
            {"a": {"name": "F", "outputs": ["e_ERROR_CODE * e_Err"]}})
        assert got == {}

    def test_same_name_in_both_keys_collapses(self):
        got = _out_param_names_by_function({"a": {
            "name": "F", "inputs": ["[OUT] U8 * p"], "outputs": ["[OUT] U8 * p"]}})
        assert got == {"F": ["p"]}

    def test_multiple_params_keep_declaration_order(self):
        got = _out_param_names_by_function({"a": {"name": "F", "outputs": [
            "[OUT] UINT32 * addressCheck", "[OUT] UINT32 * downloadAddress"]}})
        assert got == {"F": ["addressCheck", "downloadAddress"]}

    def test_nameless_entry_never_pollutes_the_map(self):
        """빈 이름이 키가 되면 하류의 `out_params.get(nm)` 이 빈 문자열에 걸린다."""
        got = _out_param_names_by_function(
            {"a": {"name": "", "outputs": ["[OUT] U8 * p"]}})
        assert got == {}
        assert "" not in got

    def test_non_dict_entry_is_not_a_crash(self):
        got = _out_param_names_by_function({"a": "not_a_dict", "b": None})
        assert got == {}

    def test_empty_input_is_not_a_crash(self):
        assert _out_param_names_by_function({}) == {}
        assert _out_param_names_by_function(None) == {}


class TestStubOutParamNames:
    def test_notation_carries_the_zero_index(self):
        """접미 `[0]` 이 이 축의 표기다 — 접미 없이 내면 적중이 12 에서 **0** 이 된다."""
        assert _stub_out_param_names(["F"], {"F"}, {"F": ["sum"]}) == ["F() sum[0]"]

    def test_void_callee_is_not_stubbed(self):
        """비-void 조인이 정밀도의 전부다(과다 142 → 23). 이걸 풀면 축이 무너진다."""
        assert _stub_out_param_names(["V"], set(), {"V": ["p"]}) == []

    def test_callee_without_out_params_yields_nothing(self):
        assert _stub_out_param_names(["F"], {"F"}, {}) == []

    def test_duplicates_collapse_and_order_is_stable(self):
        got = _stub_out_param_names(["B", "A", "B"], {"A", "B"},
                                    {"A": ["x"], "B": ["y"]})
        assert got == ["B() y[0]", "A() x[0]"]

    def test_two_params_of_one_callee_both_land(self):
        got = _stub_out_param_names(["F"], {"F"}, {"F": ["addressCheck", "downloadAddress"]})
        assert got == ["F() addressCheck[0]", "F() downloadAddress[0]"]

    def test_blank_entries_are_ignored(self):
        assert _stub_out_param_names(["", "  ", None], {"F"}, {"F": ["p"]}) == []

    def test_missing_calls_list_is_empty_not_a_crash(self):
        assert _stub_out_param_names(None, {"F"}, {"F": ["p"]}) == []


def _fd(**funcs):
    """`{이름: (calls_list, inputs, outputs)}` → function_details."""
    out = {}
    for i, (nm, spec) in enumerate(funcs.items(), start=1):
        calls, ins, outs = spec
        out[f"SwUFn_{i:04d}"] = {
            "id": f"SwUFn_{i:04d}", "name": nm, "prototype": f"void {nm}(void)",
            "file": "q.c", "inputs": list(ins), "outputs": list(outs),
            "globals_global": [], "globals_static": [], "logic_flow": [],
            "calls_list": list(calls),
        }
    return out


_CALLEE = ([], [], ["[OUT] return U8", "[OUT] U8 * Data"])


def _by(units, name):
    return next(u for u in units if u["name"] == name)


class TestCollectWiring:
    def test_out_param_lands_in_the_input_column(self):
        units = collect_unit_functions(
            _fd(Caller=(["Callee"], [], []), Callee=_CALLEE), sds_map={})
        assert "Callee() Data[0]" in _by(units, "Caller")["input_vars"]

    def test_out_param_never_lands_in_the_expected_column(self):
        """⚠ 핵심 계약 — 정본 기대 열 표적 10칸의 적중은 **0** 이었다.

        8칸이 2단 중첩 표기(`X() pt_WorkState[0]() u32t_A`)고 2칸은 피호출이 아니라
        레지스터 매크로(`_PTT() Byte`)다. 낼 수 없는 걸 내는 척하지 않는다.
        """
        units = collect_unit_functions(
            _fd(Caller=(["Callee"], [], []), Callee=_CALLEE), sds_map={})
        assert not [v for v in _by(units, "Caller")["output_vars"] if "() Data" in v]

    def test_return_comes_before_its_out_params(self):
        """⚠ 정본은 같은 피호출의 `() return` 을 먼저 적는다.

        순서는 예산이 빠듯한 unit 에서 **어느 칸이 살아남는지**를 정한다 —
        산출물 총계만 봐서는 안 보이는 종류의 계약이다.
        """
        got = _by(collect_unit_functions(
            _fd(Caller=(["Callee"], [], []), Callee=_CALLEE), sds_map={}), "Caller")
        assert got["input_vars"].index("Callee() return") < \
            got["input_vars"].index("Callee() Data[0]"), got["input_vars"]

    def test_survives_uds_replacement(self):
        """⚠ SwUDS 대체는 `input_vars` 를 **통째로 교체**한다 — 앞에 두면 조용히 사라진다."""
        units = collect_unit_functions(
            _fd(Caller=(["Callee"], [], []), Callee=_CALLEE), sds_map={},
            uds_io_map={"by_name": {"Caller": {"inputs": ["u8_DocSaysThis"], "outputs": []}}})
        got = _by(units, "Caller")["input_vars"]
        assert "u8_DocSaysThis" in got, got
        assert "Callee() Data[0]" in got, got

    def test_void_callee_contributes_nothing(self):
        units = collect_unit_functions(
            _fd(Caller=(["Quiet"], [], []), Quiet=([], [], ["[OUT] U8 * Data"])), sds_map={})
        assert not [v for v in _by(units, "Caller")["input_vars"] if "() Data" in v]

    def test_unknown_callee_is_not_stubbed(self):
        """`function_details` 에 없는 함수의 파라미터는 알 수 없다 — 지어내지 않는다."""
        units = collect_unit_functions(_fd(Caller=(["NeverHeardOf"], [], [])), sds_map={})
        assert not [v for v in _by(units, "Caller")["input_vars"] if "() " in v]


class TestReport:
    def test_note_reports_the_count_separately_from_return(self, caplog):
        """⚠ 두 경로를 합쳐 세면 어느 쪽이 회귀했는지 로그로 못 가른다.

        문구가 아니라 **숫자**를 단언한다 — 문구만 보면 집계가 틀려도 초록이다.
        """
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            collect_unit_functions(
                _fd(Caller=(["Callee"], [], []), Callee=_CALLEE), sds_map={})
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "stub return 1칸" in msgs, msgs
        assert "stub 출력파라미터 1칸(대상 함수 1개)" in msgs, msgs

    def test_no_target_says_undetermined_not_zero(self, caplog):
        """⚠ 대상 0개는 "0칸" 이 아니라 **판정 못 함**이다.

        파서가 `[OUT]` 파라미터를 안 냈다는 뜻이라 축이 통째로 죽는다. 0 으로 적으면
        "출력 파라미터가 없다"와 "판정을 못 했다"가 같은 말이 된다.
        """
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            collect_unit_functions(
                _fd(Caller=(["Callee"], [], []), Callee=([], [], ["[OUT] return U8"])),
                sds_map={})
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "stub 출력파라미터 판정 안 함" in msgs, msgs
        assert "stub 출력파라미터 0칸" not in msgs, msgs
