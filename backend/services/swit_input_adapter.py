"""SwIT (Software Integration Test) input adapter — SwUT 인프라 재활용 (33차).

Phase 1 분석 결과 SwUT의 `SwUTSession` / `EnvironmentData` / `aggregate_session`
이 100% 재활용 가능 (VectorCAST `MatricsType.Functions` Integration test도 동일
환경/TC/실행결과 구조). 본 모듈은 thin wrapper — 직접 import만 노출하고 SwIT
도구별 차이는 향후 33-fix 라운드에서 분기.

VectorCAST log 디렉토리 구조 (사용자 환경 검증 — 36-fix):
    `01.TestCaseDataReport / 02.ExecutionResultReport / 03.AggregateCoverageReport`
    동일 (Coverage 빌드 흐름은 이 3 디렉토리만 사용). `04.MetricsReport`는
    별도 흐름 (report_parsers / vcast 라우터)에서 처리.

환경 명명 차이 (36-fix Critical):
    SwUT html: `SWTE_NN_*.html` (VectorCAST 환경 명명)
    SwIT html: `SwITC_NN_*.html` (Software Integration Test Case ID)
    `collect_swut_session`에 `env_prefix` kwarg 도입 — SwIT는 "SwITC" 전달.

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
    # 36-fix: SwIT html 파일명 prefix는 SwITC_NN — SwUT의 SWTE_NN과 다름.
    # collect_swut_session에 env_prefix="SwITC" 전달해 regex 매칭 정상화.
    return collect_swut_session(
        resolver, project_id,
        jenkins_build_number=jenkins_build_number,
        cache_root=cache_root,
        log_folder=log_folder,
        allowed_roots=allowed_roots,
        env_prefix="SwITC",
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
