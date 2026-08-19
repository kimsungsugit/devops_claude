"""warning_categories 모듈 단위 회귀 (60차 F6 Round 5 NF3).

SwUT/SwIT routers의 breakdown 라벨 단일 출처 — NW7/NW8 검증을 모듈 단위로 격리.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.warning_categories import (  # noqa: E402
    KNOWN_WARNING_PREFIXES,
    categorize_warnings,
    format_breakdown_label,
)


class TestCategorizeWarnings:
    def test_empty_list_zero_counts(self):
        result = categorize_warnings([])
        # 라운드 C: semantic/judge prefix 추가 (LLM hallucination 검증)
        assert result == {
            "ambiguous": 0, "hmr": 0, "swuts": 0, "layout": 0,
            "semantic": 0, "judge": 0, "extraction": 0, "other": 0,
        }

    def test_nw7_ambiguous_precise_not_substring(self):
        """NW7: stamp summary 메시지 'ambiguous skipped: N' substring을 false
        +1로 카운트하지 않음 (startswith 정밀 매칭)."""
        warnings = [
            "[hmr] ambiguous function 'Init' — 다중 unit_file",
            "[hmr] Function Calls metric stamped — 5/10 (HMR metric count: 10, "
            "ambiguous skipped: 1)",
        ]
        result = categorize_warnings(warnings)
        assert result["ambiguous"] == 1, (
            f"NW7 회귀 — stamp summary substring 오분류: {result}"
        )
        assert result["hmr"] == 2  # ambiguous 1 + stamped 1

    def test_nw8_uncategorized_caught_as_other(self):
        """NW8: 비-prefix warning은 other 카테고리에 포함."""
        warnings = ["일반 warning", "[c_source] ASIL resolve 실패"]
        result = categorize_warnings(warnings)
        assert result["other"] == 2

    def test_mixed_categories(self):
        warnings = (
            ["[hmr] ambiguous"] * 5
            + ["[hmr] stamped — ambiguous skipped: 5"]
            + ["[swuts] read 실패"] * 3
            + ["[layout] precondition col missing"] * 2
            + ["기타"] * 4
        )
        result = categorize_warnings(warnings)
        assert result["ambiguous"] == 5
        assert result["hmr"] == 6
        assert result["swuts"] == 3
        assert result["layout"] == 2
        assert result["extraction"] == 0
        assert result["other"] == 4

    def test_extraction_prefix_counted(self):
        warnings = [
            "[extraction] value-row summary",
            "[extraction] actual empty env top5",
            "plain warning",
        ]
        result = categorize_warnings(warnings)
        assert result["extraction"] == 2
        assert result["other"] == 1


class TestFormatBreakdownLabel:
    def test_empty_returns_uncategorized(self):
        assert format_breakdown_label([]) == "uncategorized"

    def test_zero_categories_filtered(self):
        """카운트 0 카테고리는 라벨에서 제거."""
        label = format_breakdown_label(["[hmr] x"])
        assert "hmr=1" in label
        assert "swuts" not in label
        assert "layout" not in label
        assert "ambiguous" not in label
        assert "other" not in label

    def test_known_prefixes_constant(self):
        """NF3 단일 출처 — KNOWN_WARNING_PREFIXES tuple.
        라운드 C: [semantic]/[judge] 추가 (LLM hallucination 검증)."""
        assert KNOWN_WARNING_PREFIXES == (
            "[hmr]", "[swuts]", "[layout]", "[semantic]", "[judge]", "[extraction]",
        )

    def test_hierarchical_hint_when_ambiguous_and_hmr_both_present_round7_nw11(self):
        """Round 7 NW11 fix: ambiguous + hmr 둘 다 > 0 시 hint prefix 부착.

        audit reviewer가 'ambiguous=5, hmr=6'을 단순 합산 (11)으로 오해하지 않도록
        ambiguous가 hmr의 subset임을 라벨에 명시 (`[ambiguous⊂hmr]`).
        """
        warnings = ["[hmr] ambiguous func"] * 5 + ["[hmr] stamped"] * 1
        label = format_breakdown_label(warnings)
        assert label.startswith("[ambiguous⊂hmr]"), f"NW11 hint 누락: {label}"
        assert "ambiguous=5" in label
        assert "hmr=6" in label

    def test_no_hint_when_only_hmr_no_ambiguous_round7_nw11(self):
        """ambiguous=0이면 hint 부착 안 함 (라벨 noise 회피)."""
        warnings = ["[hmr] Function Calls metric stamped — 5/10"]
        label = format_breakdown_label(warnings)
        assert not label.startswith("[ambiguous⊂hmr]"), (
            f"ambiguous 0 시 hint 부착 안 됨: {label}"
        )
        assert "hmr=1" in label

    def test_semantic_judge_prefix_counted_round_c(self):
        """라운드 C: [semantic]/[judge] prefix 정확 카운트."""
        warnings = [
            "[semantic] source_file: missing.c 미존재",
            "[semantic] function: g_Unknown 매칭 실패",
            "[judge] verdict=retry, confidence=0.5",
            "[hmr] stamp summary",
            "기타 일반",
        ]
        from backend.services.warning_categories import categorize_warnings
        result = categorize_warnings(warnings)
        assert result["semantic"] == 2
        assert result["judge"] == 1
        assert result["hmr"] == 1
        assert result["other"] == 1  # 기타 — known prefix 아님
