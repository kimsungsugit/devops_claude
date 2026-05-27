"""warning_categories 모듈 단위 회귀 (60차 F6 Round 5 NF3).

SwUT/SwIT routers의 breakdown 라벨 단일 출처 — NW7/NW8 검증을 모듈 단위로 격리.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.warning_categories import (  # noqa: E402
    KNOWN_WARNING_PREFIXES,
    categorize_warnings,
    format_breakdown_label,
)


class TestCategorizeWarnings:
    def test_empty_list_zero_counts(self):
        result = categorize_warnings([])
        assert result == {
            "ambiguous": 0, "hmr": 0, "swuts": 0, "layout": 0, "other": 0,
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
        assert result["other"] == 4


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
        """NF3 단일 출처 — KNOWN_WARNING_PREFIXES tuple."""
        assert KNOWN_WARNING_PREFIXES == ("[hmr]", "[swuts]", "[layout]")
