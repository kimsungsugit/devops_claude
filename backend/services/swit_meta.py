"""SwIT (Software Integration Test) 빌더 메타 (33~34차 라운드).

SwUT `BuildMetaBase` 17 공통 필드 그대로 상속 + SwIT 도구별 필드만 추가.
deep-reviewer W3 정책 — 3x duplication 회피.

ISO 26262 Integration test 관점:
    SwIT는 ASIL B+ 이상에서 의무 (분기 커버리지 + 인터페이스 테스트). 단일
    함수 단위 SwUT와 달리 모듈/컴포넌트 단위 통합 테스트라 asil_level 평균이
    ASIL B인 경우가 많음. 단 본 모듈은 default 변경하지 않고 SwUTBuildRequest
    와 동일하게 사용자 입력 (req.asil_level) 우선 — `BuildMetaBase` default
    "ASIL A" fallback.

Hyundai v2.02 양식 호환:
    `doc_id_base="HDPDM01-SwIT"` (Coverage) / `"HDPDM01-SITR"` (SITR).
    Cover 시트 Doc. ID 필드에 `{doc_id_base}-{doc_id_sequence}` 형식으로 채움.

34차 라운드 — SwitSitrBuildMeta 추가 (xlsm, keep_vba=True):
    SwUT `SutrBuildMeta` 패턴 그대로 — target_coverage / target_pass_ratio /
    final_test_result default override.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.services.swut_meta import BuildMetaBase
from backend.services.swut_sutr_aggregator import SutrBuildMeta


@dataclass
class SwitCoverageBuildMeta(BuildMetaBase):
    """SwIT Coverage Report 빌드 메타 — base 17 필드 그대로 사용.

    SwUT의 `CoverageBuildMeta` 와 동일 패턴 (base만 상속, 추가 필드 없음).
    `doc_id_base` 만 SwIT 식별자로 차이.
    """
    pass


@dataclass
class SwitSitrBuildMeta(SutrBuildMeta):
    """SwIT SITR (Software Integration Test Result) 빌드 메타 (34차).

    SwUT `SutrBuildMeta`를 직접 상속 — `_write_cover` / `_write_test_summary`
    함수가 `SutrBuildMeta` 타입을 요구하므로 nominal subtype 호환. 추가 필드
    없이 `doc_id_base` default만 override.
    """
    doc_id_base: str = "HDPDM01-SITR"


__all__ = [
    "SwitCoverageBuildMeta",
    "SwitSitrBuildMeta",
]
