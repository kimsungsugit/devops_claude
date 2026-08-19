"""uint32 의 중앙 경계값 — SUTS 가 홀로 어긋나 있던 것을 고정한다.

`generators/suts.py:_TYPE_BOUNDARIES["uint32_t"]["mid"]` 가 **`2**15`(32768)** 이었다.
uint8 은 `2**7-1`(127) · uint16 은 `2**15-1`(32767) 인데 uint32 만 `2**15` 라,
uint32 의 중앙도 uint16 의 중앙도 아닌 값이었다.

세 갈래 근거로 `2**31-1`(0x7FFFFFFF) 이 맞다:

  1. **내부 정합** — 부호 없는 타입의 mid 는 `max // 2` 다(255//2=127 · 65535//2=32767).
     uint32 면 `(2**32-1)//2 = 2**31-1`.
  2. **형제 생성기** — `generators/sits.py:_BOUNDARY_SETS["uint32"]` 의 중앙(4번째)이
     이미 `0x7FFFFFFF` 다. uint8·uint16·int16 은 두 생성기가 일치했고 uint32 만 갈렸다.
  3. **정본 실측**(KJPDS02_PV SUTS, R25) — 정본은 uint32 칸에 `0x7FFFFFFF` 를 쓰고,
     우리가 그 값을 못 내던 칸이 **52개**였다. 반대로 우리가 쓰던 **32768 은 정본
     uint32 칸에 0회** 등장한다 — 아무도 시험하지 않는 값을 시험하고 있었다.

⚠ 이 값은 **실 문서 산출값**이다(생성되는 xlsm 셀이 바뀐다).
  `tests/unit/test_c_type_bounds_mirror.py` 가 "고치면 산출물이 바뀌니 별도 판단
  필요" 로 남겨 둔 항목이고, 위 3근거가 그 판단이다. 되돌리려면 여기부터 읽을 것.

⚠ 상수만 단언하면 가드가 아니다([[feedback_guard_must_change_observable]]) —
  `generate_sequences` 가 실제로 내는 **값**까지 본다.
"""

from __future__ import annotations

import pytest

from generators.suts import (
    _TYPE_BOUNDARIES,
    generate_sequences,
    get_boundary_values,
)

U32_MID = 2**31 - 1          # 0x7FFFFFFF
OLD_WRONG_MID = 2**15        # 32768 — 정본 uint32 칸 등장 0회


class TestBoundaryTable:
    def test_uint32_mid_is_half_of_max(self):
        b = _TYPE_BOUNDARIES["uint32_t"]
        assert b["mid"] == U32_MID
        # 규칙으로도 성립해야 한다 — 상수를 손으로 바꿔 끼우면 여기서 걸린다.
        assert b["mid"] == b["max"] // 2

    def test_old_value_is_gone(self):
        assert _TYPE_BOUNDARIES["uint32_t"]["mid"] != OLD_WRONG_MID

    @pytest.mark.parametrize("tname", ["uint8_t", "uint16_t", "uint32_t"])
    def test_unsigned_mid_rule_holds_for_every_width(self, tname):
        """한 타입만 고치고 규칙을 안 맞추면 같은 결함이 다른 폭에서 되살아난다."""
        b = _TYPE_BOUNDARIES[tname]
        assert b["mid"] == b["max"] // 2, f"{tname}: mid 는 max//2 여야 한다"

    def test_public_accessor_agrees(self):
        """`get_boundary_values` 를 거쳐도 같은 값이어야 한다(소비처가 이걸 쓴다)."""
        assert get_boundary_values("uint32_t")["mid"] == U32_MID


class TestCrossGeneratorParity:
    """SITS 와 어긋나 있던 것이 이 결함의 정체다. 다시 갈라지면 여기서 잡는다."""

    @pytest.mark.parametrize(
        "suts_key,sits_key",
        [("uint8_t", "uint8"), ("uint16_t", "uint16"), ("uint32_t", "uint32"),
         ("int16_t", "int16")],
    )
    def test_mid_matches_sits_boundary_set(self, suts_key, sits_key):
        from generators.sits import _BOUNDARY_SETS

        # SITS 는 7점 리스트이고 **4번째(index 3)** 가 중앙이다.
        assert _TYPE_BOUNDARIES[suts_key]["mid"] == _BOUNDARY_SETS[sits_key][3], (
            f"{suts_key} 의 mid 가 SITS {sits_key} 중앙과 다르다 — "
            "둘 중 한쪽만 고쳐졌다는 뜻이다"
        )


class TestObservableInGeneratedSequences:
    """상수가 아니라 **산출물**을 단언한다. 소비처가 mid 를 안 쓰면 상수만 맞고 끝난다."""

    @staticmethod
    def _unit():
        # 이름 패턴 `u32g_` → uint32_t (`_TYPE_NAME_PATTERNS`)
        return {
            "name": "r25_uint32_probe",
            "input_vars": ["u32g_Counter"],
            "output_vars": ["u32g_Counter"],
            "prototype": "U32 r25_uint32_probe(U32 u32g_Counter)",
        }

    def _values(self, key):
        vals = set()
        for s in generate_sequences(self._unit()):
            for raw in (s.get(key) or {}).values():
                v = str(raw).strip()
                try:
                    vals.add(int(v, 16) if v.lower().startswith("0x") else int(v))
                except ValueError:
                    continue
        return vals

    def test_generated_inputs_contain_new_mid(self):
        assert U32_MID in self._values("inputs")

    def test_generated_inputs_no_longer_contain_old_mid(self):
        """32768 은 정본이 한 번도 안 쓰는 값이다 — 다시 새어 나오면 회귀다."""
        assert OLD_WRONG_MID not in self._values("inputs")

    def test_expected_column_also_moved(self):
        """입력만 바뀌고 기대 열이 옛 값에 남으면 한 행 안에서 값이 어긋난다."""
        assert OLD_WRONG_MID not in self._values("expected")
