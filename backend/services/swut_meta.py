"""Coverage Report / SUTR 빌더 공통 메타 base (T137 / W3 fix).

`CoverageBuildMeta` / `SutrBuildMeta` 가 17 공통 필드 + 일부 도구별 필드를
가짐. 본 base를 상속해 도구별 필드만 subclass에 추가한다.

미래 SDUR / SITS 빌더 추가 시 3x duplication 방지 (deep-reviewer W3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BuildMetaBase:
    """17 공통 필드 + 3 property (author/reviewer/approver).

    fixed 항목은 ``config/swut_meta.json`` 에서 로드되고, dialog 항목은 매 빌드
    frontend dialog에서 받는다. auto 항목 ``build_timestamp`` 는 인스턴스 생성 시
    자동 채움.
    """
    # fixed (config에서 로드)
    project_id: str = "HDPDM01"
    project_full_name: str = "HDPDM01"
    asil_level: str = "ASIL A"
    doc_id_base: str = ""
    doc_id_sequence: str = ""
    default_author: str = ""
    default_reviewer: str = ""
    default_approver: str = ""

    # dialog (매 빌드 변경)
    release_sw_version: str = ""   # 예: 1.01.05
    hw_version: str = "1.00"
    test_date: str = ""            # ISO 8601 또는 yyyy-mm-dd
    test_engineer: str = ""
    validation_date: str = ""
    reviewer_override: str = ""
    approver_override: str = ""

    # auto
    final_test_result: str = "PASS"  # Coverage 기본 "PASS", SUTR은 "OK"로 override
    build_timestamp: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    @property
    def author(self) -> str:
        return self.test_engineer or self.default_author

    @property
    def reviewer(self) -> str:
        return self.reviewer_override or self.default_reviewer

    @property
    def approver(self) -> str:
        return self.approver_override or self.default_approver
