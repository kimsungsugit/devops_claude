"""SwSA(Software Static Analysis Report) 빌더 메타.

SwUT ``BuildMetaBase`` 17 공통 필드 상속 + SwSA Cover/Summary/ST 헤더 필드 추가.
deep-reviewer W3 — 3x duplication 회피 (swit_meta 와 동일 패턴).

ISO 26262: SwSA 는 코딩 가이드라인(MISRA)/시큐어코딩이 ASIL A evidence
'auto-generated draft'. asil_level default "ASIL A" (사용자 입력 우선).
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.services.swut_meta import BuildMetaBase

__all__ = ["SwsaBuildMeta"]


@dataclass
class SwsaBuildMeta(BuildMetaBase):
    """SwSA 빌드 메타 — base 17 필드 + SwSA 양식 헤더.

    Cover/Summary/History 의 META 셀과 모든 실행 ST 시트의 Test-Information
    헤더(분석차수/SW Ver./Tester/Debugger)에 stamp 된다. 로그에서 도출 불가한
    값(예외처리/수정대상 등)은 빈 문자열로 두면 aggregator 가 노란 표시한다.
    """
    # 식별자
    doc_id_base: str = "HKY-SwSA"          # Cover Doc ID = f"{doc_id_base}-{doc_id_sequence}"
    asil_level: str = "ASIL A"
    final_test_result: str = "Fail"         # SwSA 결과 기본(위반 존재 가정), 빌더가 산정

    # Cover (G26~G30)
    doc_version: str = "v0.10"              # Cover Version
    doc_status: str = "Unspecified"         # Cover Status (In Review 등)

    # Summary 상단 정보블록 (E3~E10)
    phase: str = ""                         # PV / DV
    platform_version: str = ""              # Software Platform Ver. (예: (APP) 2631.00 / (BOOT) 1.13)
    product: str = "PDS"                    # Product
    verification_target: str = "MCU"        # 검증 대상 (MCU/AP/MBD)
    compiler: str = ""                      # Complier
    mcu: str = ""                           # MCU part number

    # History 최신행
    history_description: str = ""

    # ST 시트 공통 Test-Information (모든 실행 시트 동일 stamp)
    analysis_round: str = "1"               # 분석차수
    tester: str = ""                        # Tester (미지정 시 author 사용)
    debugger: str = ""                      # Debugger
    misra_rule_version: str = "MISRA C 2012"   # ST101 코딩룰 버전
    secure_rule_version: str = "HKMC 4.1"      # ST1101 코딩룰 버전

    @property
    def doc_id(self) -> str:
        seq = self.doc_id_sequence.strip()
        return f"{self.doc_id_base}-{seq}" if seq else self.doc_id_base

    @property
    def tester_name(self) -> str:
        return self.tester or self.author
