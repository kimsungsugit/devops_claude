"""SwIT Coverage Report ↔ SITR 일관성 검증 (35차).

SwUT consistency_checker (18차)의 `check_swut_consistency` 함수에 `tc_prefix`
kwarg 추가됨 — SwIT는 thin wrapper로 prefix="SwITC" 전달해 재활용.

SwIT 컨텍스트:
    Coverage Report xlsx (33차) + SITR xlsm (34차) 간 다음 4가지 cross-validation:
    1. **미커버 Function ↔ 미실행 TC**: Coverage의 미커버 SwUFn_X와 SITR
       `SwITC_SwUFn_X` 미실행 TC 일대일 매칭
    2. **Exception 카운트 ↔ Deviation 카운트**: Coverage Exception 합 ≥
       SITR Deviation TC 수
    3. **Total TC 일관성**: Coverage Traceability TC == SITR Total
    4. **Final Result 용어 통일**: PASS / OK 정규화 후 비교

ISO 26262 ASIL B+ Integration test:
    - ASIL B/C/D: 본 도구 결과는 audit reviewer가 놓친 불일치 후보 발견용
    - manual review 의무 — 단독 evidence 사용 금지
"""
from __future__ import annotations

from typing import Any

from backend.services.swut_consistency_checker import (
    ConsistencyIssue,
    ConsistencyReport,
    check_swut_consistency,
)


def check_swit_consistency(
    coverage_source: Any,
    sitr_source: Any,
) -> ConsistencyReport:
    """SwIT Coverage Report ↔ SITR 일관성 검증.

    `swut_consistency_checker.check_swut_consistency` thin wrapper —
    SwIT TC name prefix "SwITC"로 재호출.

    Args:
        coverage_source: SwIT Coverage Report xlsx (path / bytes / Workbook).
        sitr_source: SwIT SITR xlsm (path / bytes / Workbook).

    Returns:
        ConsistencyReport — SwUT와 동일 dataclass 재사용.
    """
    return check_swut_consistency(coverage_source, sitr_source, tc_prefix="SwITC")


__all__ = [
    "ConsistencyIssue",
    "ConsistencyReport",
    "check_swit_consistency",
]
