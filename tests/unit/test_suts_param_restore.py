"""SwUDS 대체가 지운 **파라미터**를 되돌린다 — 파라미터 누락은 under-testing 이다.

## 왜 (KJPDS02_PV 실측, 2026-08-19 · R24)

SUTS 는 SwUDS 를 근거로 만든다. 그래서 `collect_unit_functions` 는 SwUDS 의
`[ Input/Output Parameters ]` 표가 있으면 `input_vars` 를 **통째로 교체**한다.
그 교체가 소스에서 뽑은 이름을 전부 버리는데, 그 안에 **함수 자신의 파라미터**가
섞여 있었다. 파라미터는 정의상 시험 입력이므로 그건 문서 누락이지 "입력이 아니다"
라는 진술이 아니다.

## 무엇을 되돌리나 — 실측으로 골랐다

대체가 지운 입력 527칸을 후보로 두고 잰 것:

    되살릴 대상                 생산   적중   과다   정밀도
      전부(합집합)               527     37    490     7.0%   ← 기각
      전역만                     409     16    393     3.9%   ← 기각
      파라미터(멤버 경로 포함)   118     21     97    17.8%
      **파라미터 루트만**         22     11     11    50.0%   ← 채택
      ㄴ SwUDS 가 root 자체를 안 적은 것    5      5      0   **100%**

읽으면 당연하다 — SwUDS 가 root 를 적고 **멤버를 골랐다면 그건 선별**이고, 거기
우리가 멤버를 더 얹는 건 추측이다. 통째로 빠뜨렸다면 그건 누락이다.

실제 사례가 규칙을 설명한다 (전부 SwUDS 쪽 오타·누락):

    prv_ComputeQ15Ratio               파라미터 `val`       ↔ SwUDS `Val`
    s_ApplyTemperatureCompensation    `s16_Ratio`          ↔ SwUDS `s16t_Ratio`
    g_Lib_SafeWriteQueue_EnqueueWrite 콜백 파라미터 2개를 SwUDS 가 누락
    s_UDS_ParseTempOffsetWrite        `u8t_PCI` 누락

## 라이브 재생성

    입력 5,471(91.0%) → **5,482(91.2%)** · 과다 1,474 → 1,490
    기대 4,980(92.4%) → 4,980 (변화 0 — 규칙이 입력 열 전용이다)
    **사라진 맞춤 0 · 사라진 칸 0**

⚠ 오프라인 예측은 생산 22였는데 실제는 27이다. 복원된 배열 파라미터가 그 뒤의
  **원소 확장**을 타기 때문이다. 오프라인 예산 시뮬을 믿지 않는 이유가 이것이다.

## ⚠ 기대 열에는 걸지 않는다

같은 규칙을 기대 열에 걸면 생산 86 · 적중 1 = **1.2%** 다. 정본 ExpR 은 파라미터를
그렇게 안 적는다. 방향을 가정하지 않고 **양쪽을 다 재서** 한쪽만 채택했다.
"""
from __future__ import annotations

import logging

from generators.suts import collect_unit_functions


def _fd(**funcs):
    """`{이름: (prototype, inputs, outputs, globals_global)}` → function_details."""
    out = {}
    for i, (nm, spec) in enumerate(funcs.items(), start=1):
        proto, ins, outs, gg = spec
        out[f"SwUFn_{i:04d}"] = {
            "id": f"SwUFn_{i:04d}", "name": nm, "prototype": proto,
            "file": "q.c", "inputs": list(ins), "outputs": list(outs),
            "globals_global": list(gg), "globals_static": [], "logic_flow": [],
            "calls_list": [],
        }
    return out


def _uds(name, inputs, outputs=()):
    return {"by_name": {name: {"inputs": list(inputs), "outputs": list(outputs)}}}


def _by(units, name):
    return next(u for u in units if u["name"] == name)


def _run(fd, uds, **kw):
    return collect_unit_functions(fd, sds_map={}, uds_io_map=uds, **kw)


_F = dict(F=("void F(U8 a, U8 b)", ["[IN] U8 a", "[IN] U8 b"], [], []))


class TestRestoresMissingParams:
    def test_param_absent_from_swuds_is_restored(self):
        """SwUDS 가 `b` 를 안 적었다 — 파라미터는 시험 입력이므로 되돌린다."""
        units = _run(_fd(**_F), _uds("F", ["a"]))
        got = _by(units, "F")["input_vars"]
        assert "a" in got and "b" in got, got

    def test_case_mismatch_counts_as_absent(self):
        """실측 사례 `val` ↔ SwUDS `Val`. 대소문자만 다르면 SwUDS 이름은 안 맞는다.

        둘 다 남는다 — 문서 이름을 지우는 건 우리 판단 범위가 아니고, 소스 이름을
        빼면 그 파라미터가 시험에서 사라진다(under-testing).
        """
        units = _run(_fd(F=("void F(S16 val)", ["[IN] const S16 val"], [], [])),
                     _uds("F", ["Val"]))
        got = _by(units, "F")["input_vars"]
        assert "val" in got, got
        assert "Val" in got, got

    def test_already_listed_param_is_not_duplicated(self):
        units = _run(_fd(**_F), _uds("F", ["a", "b"]))
        got = _by(units, "F")["input_vars"]
        assert got.count("a") == 1 and got.count("b") == 1, got

    def test_swuds_names_come_first(self):
        """순서 계약 — SwUDS 가 1차 근거다. 복원분은 **뒤에** 붙는다.

        예산이 빠듯한 unit 에서 순서만으로 절단 대상이 뒤바뀐다.
        """
        units = _run(_fd(**_F), _uds("F", ["a"]))
        got = _by(units, "F")["input_vars"]
        assert got.index("a") < got.index("b"), got


class TestDoesNotOverreach:
    def test_member_path_is_not_restored(self):
        """⚠ 정밀도가 50% → 14.2% 로 떨어지는 지점이다. 멤버는 SwUDS 의 **선별**이다."""
        units = _run(
            _fd(F=("void F(ST *p)",
                   ["[IN] ST * p", "[IN] ST * p->m1", "[IN] ST * p->m2"], [], [])),
            _uds("F", ["p[0].m1"]))
        got = _by(units, "F")["input_vars"]
        assert "p[0].m2" not in got, got
        assert "p" in got, got          # 루트는 되돌린다

    def test_global_is_not_restored(self):
        """전역 되살리기는 정밀도 3.9% 로 기각됐다 — 파라미터만 되돌린다."""
        units = _run(
            _fd(F=("void F(void)", [], [], ["[IN] u8g_SomeGlobal"])),
            _uds("F", ["u8_DocSaysThis"]))
        got = _by(units, "F")["input_vars"]
        assert "u8g_SomeGlobal" not in got, got

    def test_return_slot_is_not_restored_into_inputs(self):
        units = _run(
            _fd(F=("U8 F(U8 a)", ["[IN] U8 a", "[OUT] return U8"], [], [])),
            _uds("F", ["a"]))
        got = _by(units, "F")["input_vars"]
        assert "return" not in got, got

    def test_expected_column_is_untouched(self):
        """⚠ 기대 열은 정밀도 1.2% — 같은 규칙을 걸지 않는다."""
        units = _run(
            _fd(F=("void F(U8 * pOut)", ["[INOUT] U8 * pOut"],
                   ["[INOUT] U8 * pOut"], [])),
            _uds("F", ["u8_In"], ["u8_DocOut"]))
        assert _by(units, "F")["output_vars"] == ["u8_DocOut"], _by(units, "F")

    def test_expected_column_untouched_even_when_swuds_gave_no_outputs(self):
        """⚠ 위 케이스만으로는 못 잡는다 — SwUDS 가 기대 열도 주면 그 대체가
        잘못 넣은 값을 **덮어 지워** 결함이 안 보인다. 기대 축을 안 준 판으로 잰다.
        """
        units = _run(
            _fd(F=("void F(U8 a, U8 b)", ["[IN] U8 a", "[IN] U8 b"],
                   ["[OUT] U8 u8g_Out"], [])),
            _uds("F", ["a"]))
        got = _by(units, "F")
        assert "b" in got["input_vars"], got["input_vars"]
        assert "b" not in got["output_vars"], got["output_vars"]

    def test_no_restore_when_swuds_did_not_replace(self, caplog):
        """SwUDS 가 입력을 안 적었으면 대체가 없고, 복원할 것도 없다(이중 적재 금지).

        ⚠ 값만 보면 못 잡는다 — 대체를 안 걸어도 결과 리스트는 같다. **진단 수치**가
        갈린다: 대체가 0 unit 인데 "1/1 대체함" 으로 적히면 다음 라운드가 오독한다.
        """
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            units = _run(_fd(**_F), _uds("F", []))
        got = _by(units, "F")["input_vars"]
        assert got.count("a") == 1 and got.count("b") == 1, got
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "SwUDS 이름 대체 입력 0/1" in msgs, msgs
        assert "파라미터 복원 판정 안 함" in msgs, msgs

    def test_restored_param_is_not_reported_as_indirect(self):
        """복원 뒤 `inp_set` 을 안 갱신하면 **간접 변수** 판정이 stale 집합을 본다.

        같은 이름이 `[INDIRECT]` 전역으로도 잡혀 있으면, 이미 입력 열에 있는데도
        GLOBAL/VOID 전략의 간접 변수로 또 실린다.
        """
        units = _run(
            _fd(F=("void F(U8 shared_name)", ["[IN] U8 shared_name"], [],
                   ["[INDIRECT] U8 shared_name"])),
            _uds("F", ["u8_DocSaysThis"]))
        got = _by(units, "F")
        assert "shared_name" in got["input_vars"], got["input_vars"]
        assert "shared_name" not in (got.get("indirect_vars") or []), got.get("indirect_vars")

    def test_unit_without_swuds_entry_is_unchanged(self):
        units = _run(_fd(**_F), _uds("Other", ["x"]))
        assert _by(units, "F")["input_vars"] == ["a", "b"]


class TestReport:
    def test_note_counts_restored_cells_separately(self, caplog):
        """세 복원 경로(stub return · stub out-param · 파라미터)를 한 숫자로 뭉치지 않는다."""
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            _run(_fd(**_F), _uds("F", ["a"]))
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "대체가 지운 파라미터 복원 1칸(1 unit)" in msgs, msgs

    def test_no_replacement_says_undetermined_not_zero(self, caplog):
        """0 을 '고칠 게 없었다'로 읽히게 두지 않는다 — 배선이 끊긴 것과 구분한다."""
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            _run(_fd(**_F), {"by_name": {}})
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "파라미터 복원 판정 안 함" in msgs, msgs
        assert "대체가 지운 파라미터 복원" not in msgs, msgs

    def test_restored_count_is_cells_not_units(self, caplog):
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            _run(_fd(F=("void F(U8 a, U8 b, U8 c)",
                        ["[IN] U8 a", "[IN] U8 b", "[IN] U8 c"], [], [])),
                 _uds("F", ["a"]))
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "대체가 지운 파라미터 복원 2칸(1 unit)" in msgs, msgs


class TestInteropWithOtherRestorePaths:
    def test_stub_return_still_lands_after_restore(self):
        """R14/R23 이 연 두 경로가 이 변경으로 안 밀린다."""
        fd = _fd(F=("void F(U8 a, U8 b)", ["[IN] U8 a", "[IN] U8 b"], [], []),
                 G=("U8 G(void)", [], ["[OUT] return U8", "[OUT] U8 * Data"], []))
        fd["SwUFn_0001"]["calls_list"] = ["G"]
        units = _run(fd, _uds("F", ["a"]))
        got = _by(units, "F")["input_vars"]
        assert "b" in got, got
        assert "G() return" in got, got
        assert "G() Data[0]" in got, got

    def test_restored_param_precedes_stub_cells(self):
        """파라미터는 SwUDS 계열이라 stub 표기보다 앞이다 — 정본 Inpt 열 순서와 같다."""
        fd = _fd(F=("void F(U8 a, U8 b)", ["[IN] U8 a", "[IN] U8 b"], [], []),
                 G=("U8 G(void)", [], ["[OUT] return U8"], []))
        fd["SwUFn_0001"]["calls_list"] = ["G"]
        got = _run(fd, _uds("F", ["a"]))
        vs = _by(got, "F")["input_vars"]
        assert vs.index("b") < vs.index("G() return"), vs
