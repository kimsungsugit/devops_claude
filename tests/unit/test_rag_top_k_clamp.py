"""RAG `top_k` 상한 — §6 후보 17 잔여의 실제 결론.

## 왜 stage cap 이 아니라 이것인가

후보 17 의 잔여는 *"`uds_analysis`·`uds_audit`·`uds_logic`·`uds_review`·`uds_sections`
5종에 stage cap 이 없어 전역 상한(1,048,576)만 적용된다 — 상한 값은 정책"* 이었다.
값을 정하기 전에 먼저 쟀더니 **넣을 이유가 없었다**:

| 측정 | 값 |
|---|---|
| 실데이터 프롬프트 / 전역 상한 | **2.05%** |
| 최악 포화 시나리오 | **16.32%** |

`user_payload` 가 이미 `_trim_text` 로 78,000자에 묶여 있어서다. 없는 문제에 stage 키
13개 + 동적 prefix 매칭을 더하는 건 과잉이라 **stage cap 은 도입하지 않기로 확정**했다.

실제로 열려 있던 축은 **`rag_top_k` 하나**다 — 사용자 Form 입력이 그대로 검색 결과
개수가 되고 그게 프롬프트 크기가 되는데 상한이 없었다(`rag_top_k=1000` → 전역 상한의
45.9%). 소비처는 셋이고, 셋 다 상한이 없거나 하한만 있었다:

    workflow/ai.py            `max(1, ...)`  ← 하한만
    backend/routers/local.py  Form 값 그대로
    backend/helpers/uds.py    Form 값 그대로

⚠ 조사 초안은 소비처를 **2곳**으로 셌다(`local.py` + `helpers/uds.py`). `workflow/ai.py`
가 빠져 있었고, 두 곳만 조였다면 같은 결함이 한쪽에 남는 판정 복제가 됐을 것이다.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from workflow.ai import _default_agent_settings, clamp_rag_top_k

REPO_ROOT = Path(__file__).resolve().parents[2]
CONSUMERS = [
    "workflow/ai.py",
    "backend/routers/local.py",
    "backend/helpers/uds.py",
]


class TestClamp:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [(1, 1), (3, 3), (50, 50), (51, 50), (1000, 50), (10**9, 50)],
    )
    def test_upper_bound(self, given, expected):
        assert clamp_rag_top_k(given) == expected

    @pytest.mark.parametrize("given", [0, -1, -1000])
    def test_lower_bound(self, given):
        assert clamp_rag_top_k(given) == 1

    def test_non_numeric_falls_back_to_default_not_exception(self):
        """검색 폭이라 실패시킬 이유가 없다 — 접되 상한은 지킨다."""
        assert clamp_rag_top_k(None, default=8) == 8
        assert clamp_rag_top_k("abc", default=8) == 8
        assert clamp_rag_top_k("12") == 12
        assert clamp_rag_top_k(None, default=10**6) == 50

    def test_max_comes_from_config_not_a_literal(self, monkeypatch):
        import config

        monkeypatch.setattr(config, "AGENT_RAG_TOP_K_MAX", 7, raising=False)
        assert clamp_rag_top_k(1000) == 7, "상한이 config 가 아니라 리터럴에 박혀 있다"

    def test_broken_config_value_does_not_disable_the_clamp(self, monkeypatch):
        """상한이 0/음수로 잘못 설정돼도 clamp 가 꺼지지 않는다(fail-closed)."""
        import config

        monkeypatch.setattr(config, "AGENT_RAG_TOP_K_MAX", 0, raising=False)
        assert clamp_rag_top_k(1000) == 1


class TestAgentSettingsUseTheClamp:
    def test_override_is_bounded(self):
        assert _default_agent_settings({"rag_top_k": 5000})["rag_top_k"] == 50

    def test_normal_value_passes_through(self):
        assert _default_agent_settings({"rag_top_k": 7})["rag_top_k"] == 7

    def test_default_is_unchanged(self):
        import config

        assert _default_agent_settings()["rag_top_k"] == config.AGENT_RAG_TOP_K_DEFAULT


class TestEveryConsumerIsWired:
    """소비처 3곳이 **전부** clamp 를 부르는지 소스에서 확인한다.

    한 곳만 빠뜨리면 그 입구로 무제한 값이 그대로 들어간다 — 이 저장소가 반복해서
    겪은 "판정 복제, 한쪽만 고침" 이다.
    """

    @pytest.mark.parametrize("rel_path", CONSUMERS)
    def test_consumer_calls_clamp(self, rel_path):
        tree = ast.parse((REPO_ROOT / rel_path).read_text(encoding="utf-8"))
        called = {
            (n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", ""))
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
        }
        assert "clamp_rag_top_k" in called, (
            f"{rel_path} 가 clamp 를 안 부른다 — 이 입구로 무제한 top_k 가 들어간다"
        )

    def test_no_consumer_reimplements_the_bound(self):
        """`min(..., 50)` 같은 리터럴 상한이 소비처에 다시 나타나지 않아야 한다."""
        import config

        literal = str(config.AGENT_RAG_TOP_K_MAX)
        for rel_path in CONSUMERS:
            src = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
            for line in src.splitlines():
                if "rag_top_k" not in line or line.lstrip().startswith("#"):
                    continue
                assert f"min({literal}" not in line and f", {literal})" not in line, (
                    f"{rel_path} 가 상한을 리터럴로 다시 적었다: {line.strip()}"
                )
