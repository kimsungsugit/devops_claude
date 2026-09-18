"""전략 카탈로그 최대치를 **손으로 세지 않고 실행으로** 고정한다.

## 왜 이 파일이 있나

준비 게이트는 "전부 담으려면 얼마" 를 말할 때 생성기의 카탈로그 상수를 쓴다
(`docgen_requirements._suts_catalog_max` · `_sits_subcase_catalog_max`). 그 상수가
실제 산출 개수와 갈리면 게이트는 **조용히** 틀린다 — 손실을 부풀리거나(사용자가 이미
최대인 값을 더 올리려 한다), 더 나쁘게는 **손실을 0 으로 접는다**.

같은 결함이 이 저장소에서 **두 번** 났고 둘 다 주석의 산수였다:

  - SUTS: 주석이 `6 MC/DC` 라 합이 29 였는데 `MCDC_BASE` 를 빠뜨린 것이고 실제는 30.
  - SITS: 주석은 `7+4+2+2`(=15)인데 상수는 14 였다. 게이트가 값(14)을 전량으로 읽어
    `max_subcases=14` 를 **손실 없음**으로 판정했고, 정답인 15 를 고른 사용자에게는
    "14 이상은 더 담을 것이 없습니다" 라고 말했다.

주석은 검사되지 않는다. 그래서 여기서는 **최대 입력을 만들어 실제로 돌리고** 개수를
센다. 상수를 고치면 이 테스트가 따라 움직여야 하고, 생성기에 전략을 추가하면 상수를
안 고친 순간 여기서 깨진다.

## 이 테스트가 잡지 못하는 것

"이 프로젝트에서 실제로 몇 종이 나오는가" 는 소스에 달렸다(그래서 게이트는 이 축의
손실을 `suggested_basis: "catalog"` 로 내려 "최대 N종까지" 라고 말한다). 여기서 재는
것은 **이론적 최대**뿐이다.
"""
from __future__ import annotations

import pytest

from generators.sits import _DEFAULT_SUBCASES, _SUBCASE_CATALOG_MAX, _generate_sub_cases
from generators.suts import _DEFAULT_SEQ_COUNT, _STRATEGY_CATALOG_MAX, generate_sequences


def _max_sits_flow() -> dict:
    """카탈로그를 전부 발화시키는 통합 흐름.

    조건 조합(GAP A)은 `min(4, len(input_vars))` 라 입력 **4개 이상**, 전역(GAP D)은
    `indirect_vars[:2]` 라 전역 **2개 이상**이어야 최대가 나온다. 입력이 3개뿐이면
    조건 조합이 3종밖에 안 나와 총합이 14 가 되는데, 그 수를 카탈로그로 착각한 것이
    원래 결함이다.
    """
    return {
        "call_chain": "caller -> callee",
        "input_vars": [f"u8V{i}" for i in range(4)],
        "input_raws": [f"[IN] U8 u8V{i}" for i in range(4)],
        "expected_vars": ["u8Out"],
        "expected_raws": ["[OUT] U8 u8Out"],
        "indirect_vars": [f"u8gS{i}" for i in range(2)],
    }


def _max_suts_unit() -> dict:
    """카탈로그를 전부 발화시키는 단위 함수.

    ⚠ `VOID_SIDE_EFFECT` 는 `input_vars and not output_vars and indirect_vars` 라
      **출력 변수가 없어야** 붙는다. 출력을 두면 29 에서 멈춘다 — 30 이라는 수가
      도달 가능한지 자체가 여기서 판별된다.
    """
    cond = " && ".join(f"u8V{i} > {i}" for i in range(8))   # MC/DC 토글 6종(상한)
    return {
        "name": "fn_max",
        "prototype": "void fn_max(U8 a)",
        "input_vars": [f"u8V{i}" for i in range(8)],
        "output_vars": [],
        "indirect_vars": [f"u8gS{i}" for i in range(4)],
        "logic_flow": [
            {"type": "switch", "variable": "u8V0", "condition": "sw",
             "children": [{"type": "case", "value": str(j)} for j in range(8)]},
            {"type": "loop", "condition": "i < 3"},
            {"type": "if", "condition": cond},
        ],
    }


class TestSitsSubcaseCatalog:
    def test_catalog_max_matches_actual_output(self):
        """상수 = 실제로 만들어지는 최대 개수."""
        got = _generate_sub_cases(_max_sits_flow(), max_cases=10_000)
        assert len(got) == _SUBCASE_CATALOG_MAX, (
            f"카탈로그 상수 {_SUBCASE_CATALOG_MAX} 와 실제 산출 {len(got)} 가 다르다 — "
            f"전략을 추가/삭제했으면 `_SUBCASE_CATALOG_MAX` 도 고칠 것. "
            f"산출: {[c['case_label'] for c in got]}"
        )

    def test_generator_default_is_a_cap_not_the_catalog(self):
        """기본값 14 는 **캡**이다 — 카탈로그보다 작아야 이 사실이 참이다.

        이 단언이 깨지는 방향은 둘이고 **둘 다 결함**이다:
          - 같아지면 게이트의 "기본값에서도 한 종이 빠집니다" 문구가 거짓말이 된다.
          - 커지면 캡이 카탈로그를 넘어 아무 것도 안 자르는데 자르는 척한다.
        """
        assert _DEFAULT_SUBCASES < _SUBCASE_CATALOG_MAX

    def test_default_cap_actually_drops_one_candidate(self):
        """기본값으로 만들면 후보 하나가 **실제로** 빠진다(수치가 아니라 산출로 확인)."""
        full = _generate_sub_cases(_max_sits_flow(), max_cases=_SUBCASE_CATALOG_MAX)
        capped = _generate_sub_cases(_max_sits_flow(), max_cases=_DEFAULT_SUBCASES)
        assert len(full) - len(capped) == _SUBCASE_CATALOG_MAX - _DEFAULT_SUBCASES
        dropped = {c["case_label"] for c in full} - {c["case_label"] for c in capped}
        assert dropped, "캡을 낮췄는데 빠진 후보가 없다면 캡이 동작하지 않는 것이다"


class TestSutsStrategyCatalog:
    def test_catalog_max_matches_actual_output(self):
        got = generate_sequences(_max_suts_unit(), max_seq=10_000)
        assert len(got) == _STRATEGY_CATALOG_MAX, (
            f"카탈로그 상수 {_STRATEGY_CATALOG_MAX} 와 실제 산출 {len(got)} 가 다르다. "
            f"산출: {[s.get('strategy') for s in got]}"
        )

    def test_mcdc_is_last_and_falls_first(self):
        """MC/DC 가 목록 **맨 끝**이라 상한에 가장 먼저 잘린다.

        게이트가 "ASIL D 는 MC/DC 필수" 를 근거로 상한을 경고하는 전제다. 순서가 바뀌면
        그 경고가 근거를 잃는다(경고문은 그대로 남으므로 조용히 거짓이 된다).
        """
        full = generate_sequences(_max_suts_unit(), max_seq=_STRATEGY_CATALOG_MAX)
        names = [str(s.get("strategy") or "") for s in full]
        mcdc_idx = [i for i, n in enumerate(names) if n.startswith("MCDC")]
        assert mcdc_idx, "MC/DC 전략이 아예 안 나왔다"
        assert max(mcdc_idx) == len(names) - 1, f"MC/DC 가 맨 끝이 아니다: {names}"

        capped = generate_sequences(_max_suts_unit(), max_seq=_DEFAULT_SEQ_COUNT)
        cut = set(names) - {str(s.get("strategy") or "") for s in capped}
        assert cut and all(n.startswith("MCDC") for n in cut), (
            f"기본 상한에서 잘린 것이 MC/DC 만이어야 한다 — 실제: {sorted(cut)}")

    def test_generator_default_is_a_cap_not_the_catalog(self):
        assert _DEFAULT_SEQ_COUNT < _STRATEGY_CATALOG_MAX


class TestGateDisclosureUsesCatalog:
    """공시표가 **생성기 상수를 그대로** 들고 있는가 (손으로 적은 수의 드리프트 차단).

    `docgen_requirements` 는 의도적으로 손으로 쓴 표다(모듈 docstring 참조 — 요청 경로에서
    FastAPI 앱을 import 하지 않으려는 선택). 그 대가로 드리프트는 **여기서** 막는다.
    """

    @pytest.mark.parametrize(("doc", "cap", "module", "const"), [
        ("sits", "max_subcases", "generators.sits", "_DEFAULT_SUBCASES"),
        ("suts", "max_sequences", "generators.suts", "_DEFAULT_SEQ_COUNT"),
        ("sts", "max_tc_per_req", "generators.sts", "_MAX_TC_PER_REQ"),
        ("sts", "max_steps_per_tc", "generators.sts", "_MAX_STEPS_PER_TC"),
        ("sits", "max_flows", "generators.sits", "_DEFAULT_MAX_FLOWS"),
    ])
    def test_generator_default_matches_generator_module(self, doc, cap, module, const):
        import importlib

        from backend.services.docgen_requirements import DOC_REQUIREMENTS
        declared = DOC_REQUIREMENTS[doc]["caps"][cap]["generator"]
        actual = getattr(importlib.import_module(module), const)
        assert declared == actual, (
            f"{doc}.{cap} 공시 generator={declared} 인데 {module}.{const}={actual} 다 — "
            f"둘 중 하나가 낡았고, 화면은 낡은 쪽을 보여 준다")

    @pytest.mark.parametrize(("doc", "cap", "module", "const"), [
        ("sits", "max_subcases", "generators.sits", "_SUBCASE_CATALOG_MAX"),
        ("suts", "max_sequences", "generators.suts", "_STRATEGY_CATALOG_MAX"),
    ])
    def test_catalog_max_matches_generator_module(self, doc, cap, module, const):
        import importlib

        from backend.services.docgen_requirements import DOC_REQUIREMENTS
        declared = DOC_REQUIREMENTS[doc]["caps"][cap].get("catalog_max")
        actual = getattr(importlib.import_module(module), const)
        assert declared == actual, (
            f"{doc}.{cap} 의 catalog_max={declared} 가 {module}.{const}={actual} 와 다르다 — "
            f"게이트의 '전부 담으려면 N' 이 그만큼 틀린다")

    def test_catalog_max_is_declared_wherever_generator_default_is_a_cap(self):
        """생성기 기본값이 캡이면 `catalog_max` 가 **반드시** 있어야 한다.

        없으면 `_cap_full_total` 이 `generator` 로 폴백해 캡을 전량으로 읽는다 = 손실 0 판정.
        이게 SITS 에서 실제로 일어난 일이라, 새 캡이 생겨도 같은 구멍이 안 나게 못박는다.
        """
        from backend.services.docgen_requirements import DOC_REQUIREMENTS
        known_catalogs = {
            ("sits", "max_subcases"): _SUBCASE_CATALOG_MAX,
            ("suts", "max_sequences"): _STRATEGY_CATALOG_MAX,
        }
        for (doc, cap), catalog in known_catalogs.items():
            entry = DOC_REQUIREMENTS[doc]["caps"][cap]
            assert entry.get("catalog_max") == catalog, (
                f"{doc}.{cap} 은 생성기 기본값({entry.get('generator')})이 카탈로그"
                f"({catalog})보다 작은 **캡**이라 catalog_max 공시가 필수다")
