"""ISO 26262 안전 판정이 **한 벌**인가(R9-3).

STS·SUTS·SITS 가 각자 한 벌씩 들고 있었다. 세 구현은 실측상 동작이 같았지만(2026-08-19
대조 — 그래서 이 통합의 판정 변화는 **0건**), 안전 판정을 고친 커밋 3건
(`fe9481e`·`e69b9dd`·`fb385d8`)이 그중 `generators/sts.py` 에는 **한 번도 안 닿았다**.
갈라지는 건 시간 문제였다.

더해 `sts.py` 안에만 ASIL 술어가 네 벌 있었고 하나만 표기가 달랐다
(`not in ("TBD", "")` vs `!= "TBD"`) — 앞의 truthy 검사 때문에 `""` 가지는 도달 불가라
동작은 같았지만, 읽는 사람에겐 "여기만 다른 규칙" 이다.
"""
from __future__ import annotations

import pytest

from generators.safety_marks import is_safety_asil, resolve_safety_related


class TestTheMarkItself:
    @pytest.mark.parametrize("val", ["A", "B", "C", "D", "a", " b ", "ASIL B", "asil d"])
    def test_graded_is_safety(self, val):
        assert resolve_safety_related(val) == "O", val

    def test_qm_is_the_only_non_safety_claim(self):
        assert resolve_safety_related("QM") == "X"
        assert resolve_safety_related("qm") == "X"

    @pytest.mark.parametrize("val", ["", None, "TBD", "tbd", "   ", "Z", "unknown"])
    def test_absent_evidence_stays_blank(self, val):
        """⚠ 근거 부재를 `X` 로 단정하지 않는다 — under-classification 이다."""
        assert resolve_safety_related(val) == "", repr(val)


class TestThePredicate:
    @pytest.mark.parametrize("val", ["A", "B", "C", "D", "ASIL C"])
    def test_graded_is_true(self, val):
        assert is_safety_asil(val) is True, val

    @pytest.mark.parametrize("val", ["", None, "TBD", "tbd", "QM", "qm", "  "])
    def test_no_evidence_or_qm_is_false(self, val):
        assert is_safety_asil(val) is False, repr(val)

    def test_unknown_grade_is_treated_conservatively(self):
        """미상 등급은 **보수적으로 안전 취급**한다.

        `resolve_safety_related` 는 같은 입력에 빈칸(근거 없음)을 낸다 — 둘은 일부러
        다르다. 여기를 저기에 맞추면 미상 등급이 비안전으로 내려가 under-classification
        이 된다. 이 테스트가 그 '고침'을 막는다.
        """
        assert is_safety_asil("Z") is True
        assert resolve_safety_related("Z") == ""


class TestTheTwoNeverClaimNonSafetyWithoutEvidence:
    """계약: 둘 다 근거 없이 '비안전' 을 주장하지 않는다."""

    @pytest.mark.parametrize("val", ["", None, "TBD", "Z", "unknown", "  "])
    def test_no_x_without_evidence(self, val):
        assert resolve_safety_related(val) != "X", repr(val)

    @pytest.mark.parametrize("val", ["A", "B", "C", "D", "ASIL A"])
    def test_o_implies_true(self, val):
        """`O` 를 내는 입력은 술어에서도 True — 두 축이 반대로 가면 안 된다."""
        assert resolve_safety_related(val) == "O"
        assert is_safety_asil(val) is True


class TestAllThreeGeneratorsShareOneImplementation:
    """세 생성기가 **같은 객체**를 쓰는가 — 값이 같은 게 아니라 출처가 같아야 한다.

    ⚠ 값 비교(`f("A") == g("A")`)로는 복제를 못 잡는다. 복제본도 값은 같다.
    """

    def test_same_function_object(self):
        from generators.sits import _safety_mark as sits_mark
        from generators.sts import _safety_mark as sts_mark
        from generators.suts import resolve_safety_related as suts_mark

        assert sits_mark is resolve_safety_related, "SITS 가 자기 구현을 들고 있다"
        assert sts_mark is resolve_safety_related, "STS 가 자기 구현을 들고 있다"
        assert suts_mark is resolve_safety_related, "SUTS 가 자기 구현을 들고 있다"

    def test_no_generator_redefines_the_logic(self):
        """소스에 판정 리터럴이 다시 나타나면 실패 — 복제가 되살아난 것이다."""
        import pathlib

        marker = 'if val == "QM":'
        for name in ("sits", "sts", "suts"):
            src = pathlib.Path(f"generators/{name}.py").read_text(encoding="utf-8")
            assert marker not in src, f"generators/{name}.py 에 판정이 다시 쓰였다"

    def test_sts_has_no_hand_written_asil_predicate_left(self):
        """`sts.py` 의 ASIL 술어 4벌이 남아 있지 않은가."""
        import pathlib

        src = pathlib.Path("generators/sts.py").read_text(encoding="utf-8")
        assert '"QM" not in' not in src, "sts.py 에 손으로 쓴 ASIL 술어가 남아 있다"
        assert src.count("is_safety_asil(") >= 4, "술어 호출이 4곳 미만 — 일부만 옮겼다"
