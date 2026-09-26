"""warning_categories 모듈 단위 회귀 (60차 F6 Round 5 NF3).

SwUT/SwIT routers의 breakdown 라벨 단일 출처 — NW7/NW8 검증을 모듈 단위로 격리.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.warning_categories import (  # noqa: E402
    KNOWN_WARNING_PREFIXES,
    categorize_warnings,
    format_breakdown_label,
    warnings_header_json,
)


class TestCategorizeWarnings:
    def test_empty_list_zero_counts(self):
        result = categorize_warnings([])
        # 라운드 C: semantic/judge prefix 추가 (LLM hallucination 검증)
        # 2026-08-25: evidence 추가 — 등록됐는데 파일이 없는 선택 증빙
        assert result == {
            "ambiguous": 0, "hmr": 0, "swuts": 0, "layout": 0,
            "semantic": 0, "judge": 0, "extraction": 0, "evidence": 0, "other": 0,
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
        라운드 C: [semantic]/[judge] 추가 (LLM hallucination 검증).
        2026-08-25: [evidence] 추가 — 선택 증빙 부재."""
        assert KNOWN_WARNING_PREFIXES == (
            "[hmr]", "[swuts]", "[layout]", "[semantic]", "[judge]", "[extraction]",
            "[evidence]",
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


class TestEvidenceCategory:
    """선택 증빙 부재가 `other` 로 묻히면, 헤더 한도 초과 시 **증빙이 빠졌다는 사실
    자체**가 화면에서 사라진다.

    2026-08-25 실측: KJPDS02 SwITCR 빌드가 경고 17건을 냈는데 전부 `other=17` 이라
    `(17 warnings — 헤더 한도 초과로 생략, breakdown: other=17)` 만 보였다.
    """

    def test_evidence_prefix_is_counted(self):
        warnings = [
            "[evidence] fault_injection_result: config 에 등록된 파일이 없어 …",
            "[evidence] switcr_reference: config 에 등록된 파일이 없어 …",
            "[hmr] stamped",
        ]
        result = categorize_warnings(warnings)
        assert result["evidence"] == 2, result
        assert result["other"] == 0, "알려진 prefix 인데 other 로도 셌다"

    def test_evidence_shows_up_in_the_label(self):
        label = format_breakdown_label(["[evidence] x", "[evidence] y", "무분류"])
        assert "evidence=2" in label, label
        assert "other=1" in label, label

    def test_router_message_actually_carries_the_prefix(self):
        """⚠ 카테고리를 만들어도 라우터가 그 prefix 로 안 쓰면 아무 효과가 없다."""
        from backend.routers import swit as mod
        from tests.unit._source_probe import source_of
        src = source_of(mod._read_optional_config_file)
        assert '"[evidence] {config_key}' in src, (
            "선택 증빙 경고가 등록된 prefix 로 안 나간다 — other 로 묻힌다")


class TestWarningsHeaderJson:
    """예산 초과 시 **본문을 통째로 버리지 않는다.**

    2026-08-25 실측: SwITCR 빌드가 경고 17건을 냈는데 헤더엔
    `(17 warnings — 헤더 한도 초과로 생략, breakdown: other=17)` 뿐이었다. 바로 그
    빌드에서 새로 낸 "선택 증빙이 빠졌다" 경고가 사용자에게 닿지 않았다 — 이 저장소의
    정직성은 경고를 사람이 **읽는 것**에 걸려 있으므로, 개수만 남기는 건 침묵에 가깝다.
    """

    BUDGET = 1024

    def _big(self, n=60):
        return [f"[hmr] 함수 '{i:03}' 에서 다중 unit_file 로 모호합니다" for i in range(n)]

    def test_within_budget_is_unchanged(self):
        small = ["[hmr] a", "기타"]
        assert json.loads(warnings_header_json(small)) == small

    def test_over_budget_keeps_some_text(self):
        parsed = json.loads(warnings_header_json(self._big()))
        assert len(parsed) > 1, "개수만 남았다 — 본문이 하나도 안 실렸다"

    def test_sentinel_is_first(self):
        """뒤에 두면 스크롤 안 하는 화면에서 '더 있다' 가 안 보인다."""
        parsed = json.loads(warnings_header_json(self._big()))
        assert parsed[0].startswith("(+") and "생략" in parsed[0], parsed[0]

    def test_counts_add_up(self):
        warnings = self._big()
        parsed = json.loads(warnings_header_json(warnings))
        dropped = int(re.search(r"\+(\d+) warnings", parsed[0]).group(1))
        assert dropped + len(parsed) - 1 == len(warnings), (
            f"실린 {len(parsed) - 1} + 생략 {dropped} != 전체 {len(warnings)}")

    def test_result_fits_the_budget(self):
        assert len(warnings_header_json(self._big(400))) <= self.BUDGET

    def test_breakdown_counts_all_not_just_kept(self):
        """남긴 것만 세면 화면 숫자와 산출물이 어긋난다."""
        warnings = self._big(50) + ["[evidence] x"] * 7
        parsed = json.loads(warnings_header_json(warnings))
        assert "hmr=50" in parsed[0] and "evidence=7" in parsed[0], parsed[0]

    def test_single_oversized_warning_still_valid_json(self):
        """경고 하나가 예산보다 크면 본문은 못 싣는다 — 그래도 JSON 은 유효해야 한다.

        ⚠ 예전 코드가 고친 결함이 이것이다(30차 W21): 문자열을 중간에서 자르면
          프론트 `JSON.parse` 가 깨진다.
        """
        out = warnings_header_json(["가" * 4000])
        parsed = json.loads(out)                      # 깨지면 여기서 실패
        assert len(parsed) == 1 and "1 warnings" in parsed[0], parsed
        assert len(out) <= self.BUDGET

    def test_tiny_budget_degrades_but_stays_valid_json(self):
        """예산이 sentinel 보다도 작으면 본문을 포기한다 — **그래도 유효 JSON** 이어야 한다.

        ⚠ 이 분기는 기본 예산(1024B)에서는 거의 안 밟힌다. 안 밟히는 분기는 뮤테이션이
          통째로 생존한다(실측: `return out[:budget]` 를 심어도 아무 테스트가 안 죽었다).
          그래서 예산을 인자로 낮춰 **명시적으로** 밟는다.
        ⚠ 문자열을 중간에서 자르면 프론트 `JSON.parse` 가 깨진다 — 30차 W21 회귀.
        """
        out = warnings_header_json(self._big(30), budget=60)
        parsed = json.loads(out)                  # 깨지면 여기서 실패
        assert len(parsed) == 1, parsed
        assert "30 warnings" in parsed[0], parsed[0]

    def test_empty_is_empty(self):
        assert json.loads(warnings_header_json([])) == []


class TestAllThreeRoutersUseTheSharedTruncation:
    """한 곳만 고치면 나머지가 잠복한다 — swreport 는 실제로 breakdown 이 없었다."""

    @pytest.mark.parametrize("mod_name", ["swut", "swit", "swreport"])
    def test_router_delegates_to_the_helper(self, mod_name):
        import importlib

        from tests.unit._source_probe import source_of
        mod = importlib.import_module(f"backend.routers.{mod_name}")
        src = source_of(mod._build_result_to_response)
        assert "warnings_header_json(warnings)" in src, (
            f"{mod_name} 가 자체 절단 로직을 들고 있다 — 판정이 갈라진다")
        # ⚠ `헤더 한도 초과로 생략` 자체로는 못 잡는다 — **summary(ASIL ids) 절단**이
        #   같은 문구를 정당하게 쓴다. 경고 축만 겨냥한다.
        assert "warnings)} warnings" not in src, (
            f"{mod_name} 가 경고 sentinel 을 직접 만든다 — 복제본이다")
        assert "format_breakdown_label" not in src, (
            f"{mod_name} 가 breakdown 라벨을 직접 만든다 — 판정이 갈라진다")
