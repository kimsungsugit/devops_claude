"""SwUT audit 시각 강조 디자인 토큰 (29차 W17, 단일 출처).

회사 v3.01 xlsx/xlsm 산출물의 cell fill 색상 및 안내 문구 표준.
audit reviewer가 한눈에 "사용자 입력 필요" vs "자동 채움" vs "FAIL"을
구분 가능하도록 23/24차에 도입된 정책의 단일 출처 모듈.

배경:
    이전 (23~28차) excel_template_utils.py module-level 상수에 RGB hex가
    hardcoded됐고, frontend tokens.css는 별도 Tailwind palette를 사용.
    두 컨텍스트는 의도적으로 다른 색상을 쓰지만 (Excel 셀 배경 vs UI 텍스트
    시인성), audit 정책의 RGB 단일 출처는 backend에만 존재해야 안전.

design vs runtime:
    이 모듈은 정적 상수만 export — Pydantic schema도 아님, lazy import도
    아님. 모든 backend 코드는 import 시점에 즉시 값 확정.

ISO 26262 ASIL A audit 영향:
    cell fill 색상이 변경되면 audit reviewer에게 통보 (산출물 시인성 영향).
    본 모듈 변경 = 정책 변경 = CLAUDE.md `## 시각 강조 정책` 섹션 동기 갱신
    의무.
"""
from __future__ import annotations

from typing import Final


# ---- Excel cell fill 색상 (openpyxl PatternFill start_color/end_color) ----

# 연한 노란 (warm pastel yellow, #FFEB9C). 사용자 입력 필요 셀 배경.
USER_INPUT_FILL_RGB: Final[str] = "FFFFEB9C"

# 연한 빨강 (warm pastel red, #FFC7CE). FAIL row Result 셀 배경.
FAIL_FILL_RGB: Final[str] = "FFFFC7CE"

# 30차 W21: ASIL D 함수 row 강조 — FAIL과 RGB 동일하나 의미 분리.
# "FAIL"은 TC 실행 결과 실패, "ASIL D"는 audit 검토 우선순위 표시.
# 동일 셀 두 의미 겹치면 ASIL D 우선 (호출 순서 보장).
ASIL_D_FILL_RGB: Final[str] = "FFFFC7CE"

# 31차 W29: ASIL B (분기 커버리지 필수) / ASIL C (MC/DC 권장) 함수 row 강조.
# 노란 (FFFFEB9C 사용자 입력) / 빨간 (FFFFC7CE FAIL/ASIL D) 과 명확히 구분되는
# pastel color 사용. audit reviewer가 한눈에 ASIL 등급 차이 인지.
ASIL_B_FILL_RGB: Final[str] = "FFE2F0FF"   # 연한 파랑 (분기 커버리지 필수)
ASIL_C_FILL_RGB: Final[str] = "FFFFE5CC"   # 연한 주황 (MC/DC 커버리지 권장)

# 라운드 81 T1501: ASIL A / QM 함수 row 강조 — 5단계 그라데이션 완성.
# HDPDM01 NE_GN7 환경처럼 A/QM 함수가 압도적인 경우에도 audit reviewer가
# 시각적으로 함수 분포를 한눈에 인지 가능. B/C/D 와 명확히 구분되는 pastel.
ASIL_A_FILL_RGB: Final[str] = "FFE4F3D5"   # 연한 녹색 (구문 커버리지로 충분, 가장 약한 안전 등급)
ASIL_QM_FILL_RGB: Final[str] = "FFE8E8E8"  # 연한 회색 (Quality Management — 비안전, 정보성)

# 라운드 98 — 회사 양식 재현용 음영. audit 마킹(위 ASIL/FAIL)과 성격 구분:
# 이 값은 회사 SwUTCV/SwITCV 3.Consistency 순번(B)열 표준 음영을 그대로 재현하는
# 고정값이며 우리가 정의한 의미 색이 아님. REF(회사 감사본) 일치 목적.
INDEX_COL_SHADE_RGB: Final[str] = "FFEEEEEE"  # 연회색 (Consistency No 열 음영, 회사 양식)


# ---- 함수 호출 트리(콜트리) xlsx 내보내기 색상 (call_tree_xlsx.py 전용) ----
#
# 회사 SwITS "2.SW Integration Strategy" 시트 재현용. 함수 호출 계층(depth)을
# 컬럼 들여쓰기 + depth별 파스텔 배경으로 시각화(통합 순서). 회사 양식 색을 그대로
# 재현한 고정값이며 우리가 정의한 의미 색이 아님(REF 일치 목적). audit 마킹(위
# ASIL/FAIL)과 성격이 다르므로 별도 상수군으로 분리.
#
# depth 인덱스 → 배경. depth가 목록 길이를 넘으면 마지막 색을 유지(회사 양식은
# 10 depth 이상을 단일 베이지로 통일 — 그 규칙을 재현).
CALL_TREE_DEPTH_FILLS: Final[tuple] = (
    "FFDDEBF7",  # depth 0: 연파랑
    "FFDDEBF7",  # depth 1: 연파랑
    "FFFFE6EE",  # depth 2: 연분홍
    "FFE5F5E0",  # depth 3: 연초록
    "FFFFF9DB",  # depth 4: 연노랑
    "FFF5E6D0",  # depth 5+: 베이지 (이후 모든 depth 동일)
)

# 진입 함수 블록 헤더 셀 — 노란 배경 + 남색 굵은 글씨(회사 양식 B열 통합테스트 ID 셀).
CALL_TREE_ROOT_FILL_RGB: Final[str] = "FFFFFF00"    # 노랑 (진입 함수 블록 헤더 배경)
CALL_TREE_ROOT_FONT_RGB: Final[str] = "FF002060"    # 남색 (진입 함수명 글자색)
CALL_TREE_SOURCE_FILL_RGB: Final[str] = "FFFFFFCC"  # 연노랑 (관련 소스 파일 셀)
CALL_TREE_HEADER_FILL_RGB: Final[str] = "FFFFFF00"  # 노랑 (depth 헤더 행)
CALL_TREE_EXTERNAL_FILL_RGB: Final[str] = "FFF2F2F2"  # 연회색 (외부/라이브러리 함수 셀)

# 보조 텍스트(메타 라인·유형/비고·외부 함수명·정의 파일) 글자색 — muted gray.
# Excel 산출물 공통 보조 정보용. 강조 색(ASIL/ROOT)과 구분되는 저채도 회색.
MUTED_TEXT_FONT_RGB: Final[str] = "FF6B7280"  # 회색 (보조 정보 글자)


# ---- 사용자 입력 placeholder 문자열 (셀에 쓰이는 안내) ----

# 24차 silent "N/A" 제거 정책에 따라 명시적 안내. 뒤에 hint를 " — "로 이어 붙임.
USER_INPUT_PLACEHOLDER: Final[str] = "▶ 사용자 입력 필요"


__all__ = [
    "USER_INPUT_FILL_RGB",
    "FAIL_FILL_RGB",
    "ASIL_A_FILL_RGB",
    "ASIL_B_FILL_RGB",
    "ASIL_C_FILL_RGB",
    "ASIL_D_FILL_RGB",
    "ASIL_QM_FILL_RGB",
    "INDEX_COL_SHADE_RGB",
    "CALL_TREE_DEPTH_FILLS",
    "CALL_TREE_ROOT_FILL_RGB",
    "CALL_TREE_ROOT_FONT_RGB",
    "CALL_TREE_SOURCE_FILL_RGB",
    "CALL_TREE_HEADER_FILL_RGB",
    "CALL_TREE_EXTERNAL_FILL_RGB",
    "MUTED_TEXT_FONT_RGB",
    "USER_INPUT_PLACEHOLDER",
]
