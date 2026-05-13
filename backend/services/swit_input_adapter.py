"""SwIT (Software Integration Test) input adapter — SwUT 인프라 재활용 (33차).

Phase 1 분석 결과 SwUT의 `SwUTSession` / `EnvironmentData` / `aggregate_session`
이 100% 재활용 가능 (VectorCAST `MatricsType.Functions` Integration test도 동일
환경/TC/실행결과 구조). 본 모듈은 thin wrapper — 직접 import만 노출하고 SwIT
도구별 차이는 향후 33-fix 라운드에서 분기.

VectorCAST log 디렉토리 구조 가정:
    SwUT와 동일 `01.TestCaseDataReport / 02.ExecutionResultReport /
    03.AggregateCoverageReport`. 실 SwIT 환경 다르면 33-fix 라운드에서
    `collect_swit_session` override.

ISO 26262:
    Integration test도 unit test와 동일 evidence_class "auto-generated draft".
"""
from __future__ import annotations

from typing import Any

from backend.services.swut_input_adapter import (
    CoverageStats,
    EnvironmentData,
    ExecutionRow,
    FunctionCoverage,
    SwUTSession,
    aggregate_session,
    collect_swut_session,
)


def collect_swit_session(
    resolver: Any,
    project_id: str,
    *,
    jenkins_build_number: int | None = None,
    cache_root: str = "",
    log_folder: str | None = None,
    allowed_roots: list[str] | None = None,
) -> SwUTSession:
    """SwIT 빌더용 session collect — 33차에서는 SwUT collect를 그대로 재활용.

    Jenkins cache 우선, log_folder fallback. 입력 path traversal 방어는
    SwUT collect_swut_session이 처리 (allowed_roots 검증 내장).

    Args:
        resolver: file_resolver.
        project_id: 예) "HDPDM01".
        jenkins_build_number: Jenkins build 번호. None이면 latest.
        cache_root: Jenkins cache root prefix.
        log_folder: fallback path (`U:\\...\\08.SW 통합테스트\\03.Test Result\\01.Log\\v<VER>_<DATE>`).
        allowed_roots: 신뢰 가능한 root prefix 화이트리스트.

    Returns:
        SwUTSession — environments 채워짐. session.parse_warnings 확인 의무.

    Raises:
        ValueError: 두 입력 모두 미제공 또는 Jenkins/log 둘 다 실패 시.
    """
    return collect_swut_session(
        resolver, project_id,
        jenkins_build_number=jenkins_build_number,
        cache_root=cache_root,
        log_folder=log_folder,
        allowed_roots=allowed_roots,
    )


__all__ = [
    "CoverageStats",
    "EnvironmentData",
    "ExecutionRow",
    "FunctionCoverage",
    "SwUTSession",
    "aggregate_session",
    "collect_swit_session",
]
