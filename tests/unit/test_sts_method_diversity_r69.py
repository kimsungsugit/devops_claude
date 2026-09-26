"""R69 (N80) — STS `method_diversity_pct` 는 도달 가능한 정의여야 한다.

실측(품질 DB `reports/quality.sqlite`, 2026-09-19): STS run 1087(08-11) 100.0 → run 2059·2076·2112·2113 전부 **40.0**.
정의가 `test_method 종류 / 5` 였는데 2026-08-11 어휘 정규화 뒤 STS 의 test_method 는 RBT/FIT 둘뿐이라 상한이 40 이고
advisory 임계 60 은 구조적으로 미달이었다. 분모 5 는 옛 5어휘 시절 것이다.

바뀐 정의: **생성 방법(gen_method) 종류 수 / 어휘 크기 3**(SITS 와 같은 형태). 분자가 실제로 갈리는 축(R67 부터 스텝이 증명하는
AOR/ECA/BAA)이라 조언이 행동으로 이어진다. test_method 종류 수는 참고지표(`test_method_kinds`)로 남긴다.
"""
from __future__ import annotations

import re
from pathlib import Path

from workflow.quality.evaluator import _STS_GEN_METHOD_VOCAB_SIZE, evaluate_sts

REPO = Path(__file__).resolve().parents[2]


def _by_name(report):
    return {m["metric_name"]: m for m in evaluate_sts(report)}


def _report(test_methods, gen_methods):
    return {"total_test_cases": 10, "completeness_pct": 100.0, "safety_test_cases": 1,
            "requirement_coverage": {"covered_pct": 100.0, "total_reqs": 5},
            "test_method_distribution": test_methods, "gen_method_distribution": gen_methods}


class TestDefinition:
    def test_all_three_gen_methods_reach_100(self):
        """R67 라이브 분포(AOR 159 · ECA 102 · BAA 33)면 100 — 옛 정의는 같은 산출물을 40 으로 적었다."""
        m = _by_name(_report({"RBT": 279, "FIT": 15}, {"AOR": 159, "ECA": 102, "BAA": 33}))
        assert m["method_diversity_pct"]["value"] == 100.0
        assert m["test_method_kinds"]["value"] == 2.0
        assert m["gen_method_kinds"]["value"] == 3.0

    def test_full_test_method_vocab_alone_cannot_reach_the_advisory_threshold_under_old_definition(self):
        """옛 정의의 결함 재현: test_method 를 어휘 전부(2종) 써도 2/5 = 40 < 60. 새 정의는 test_method 를 보지 않는다."""
        m = _by_name(_report({"RBT": 1, "FIT": 1}, {"AOR": 1}))
        assert m["method_diversity_pct"]["value"] == round(1 / 3 * 100, 2)
        m2 = _by_name(_report({"RBT": 1}, {"AOR": 1, "ECA": 1}))
        assert m2["method_diversity_pct"]["value"] == round(2 / 3 * 100, 2), "test_method 가 하나여도 gen_method 로만 잰다"

    def test_single_gen_method_is_low(self):
        m = _by_name(_report({"RBT": 5}, {"AOR": 5}))
        assert m["method_diversity_pct"]["value"] == 33.33

    def test_unknown_and_blank_keys_do_not_count(self):
        m = _by_name(_report({"RBT": 5, "?": 1, "": 2}, {"AOR": 5, "?": 2, "": 1}))
        assert m["gen_method_kinds"]["value"] == 1.0
        assert m["test_method_kinds"]["value"] == 1.0, "참고지표도 '?'·빈 키를 종류로 세지 않는다"
        assert m["method_diversity_pct"]["value"] == 33.33

    def test_missing_distribution_is_zero_not_crash(self):
        m = _by_name(_report({}, {}))
        assert m["method_diversity_pct"]["value"] == 0.0
        m2 = _by_name({"total_test_cases": 0})
        assert m2["method_diversity_pct"]["value"] == 0.0

    def test_capped_at_100(self):
        m = _by_name(_report({}, {"AOR": 1, "ECA": 1, "BAA": 1, "XYZ": 1}))
        assert m["method_diversity_pct"]["value"] == 100.0

    def test_metric_is_advisory_not_gate(self):
        """비게이트(threshold None) 는 유지 — 정의를 바꾸면서 게이트로 승격하지 않는다."""
        m = _by_name(_report({"RBT": 1}, {"AOR": 1}))
        assert m["method_diversity_pct"]["threshold"] is None and m["method_diversity_pct"]["gate_pass"] is None


class TestVocabularyBinding:
    def test_denominator_equals_sts_gen_method_vocabulary(self):
        """분모 3 = `generators.sts._GEN_METHODS` 크기. 어휘가 늘면 상한 100 이 거짓이 된다 — 여기서 묶는다."""
        from generators.sts import _GEN_METHODS

        assert _STS_GEN_METHOD_VOCAB_SIZE == float(len(_GEN_METHODS)) == 3.0

    def test_advisory_threshold_is_reachable(self):
        """임계(60)는 어휘 전부를 쓰지 않고도 넘을 수 있고, 한 종류로는 못 넘어야 조언이 의미를 갖는다."""
        from workflow.quality.thresholds import ADVISORY_THRESHOLDS

        th = ADVISORY_THRESHOLDS["sts"]["method_diversity_pct"]
        assert 100.0 >= th
        assert (2 / _STS_GEN_METHOD_VOCAB_SIZE) * 100 >= th > (1 / _STS_GEN_METHOD_VOCAB_SIZE) * 100

    def test_old_denominator_is_gone(self):
        """`/ 5.0` 회귀 방지 — STS 평가기 본문에 5 어휘 분모가 다시 오면 상한 40 이 되살아난다."""
        src = (REPO / "workflow" / "quality" / "evaluator.py").read_text(encoding="utf-8")
        body = src[src.index("def evaluate_sts("):src.index("def evaluate_suts(")]
        assert not re.search(r"/\s*5\.0", body)

    def test_advice_speaks_the_current_vocabulary(self):
        """조언 문구가 옛 어휘(Boundary/Normal/Stress/State Transition)를 말하면 사용자가 존재하지 않는 방법을 찾는다."""
        from workflow.quality.advisor import _STS_ADVICE

        text = _STS_ADVICE["method_diversity_pct"]["low_advice"]
        for word in ("AOR", "ECA", "BAA"):
            assert word in text
        for stale in ("Stress", "State Transition", "Error Guessing", "Boundary/Normal"):
            assert stale not in text
        assert _STS_ADVICE["test_method_kinds"]["threshold"] is None
        assert _STS_ADVICE["gen_method_kinds"]["threshold"] is None
