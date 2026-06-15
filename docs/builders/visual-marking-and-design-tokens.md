# 시각 강조 정책 & Design Token 단일 출처

> CLAUDE.md on-demand 레퍼런스 — SwUT/SwIT 산출물 시각 강조, Excel 셀 배경, design token 작업 시 참조.
> 관련: [`swut_builder.md`](swut_builder.md), [`swit_builder.md`](swit_builder.md)

## 시각 강조 정책 (23/24/29/30/31차 + 라운드 81 5단계 확장)

산출물 cell에 audit reviewer 친화 표시. **라운드 81 ASIL 5단계 그라데이션 완성** —
HDPDM01 NE_GN7 같은 A/QM-only 환경에서도 시각 분포 인지 가능.

| 색상 RGB | 용도 | 헬퍼 |
|----------|------|------|
| 🟡 노란 `FFFFEB9C` | 사용자 입력 필요 | `mark_user_input_required` / `write_value_or_mark` |
| ⚪ 회색 `FFE8E8E8` (**라운드 81 T1501**) | 3.Coverage / Test Log — QM 함수 row (비안전, 정보성) | `mark_asil_qm_function` |
| 🟢 녹색 `FFE4F3D5` (**라운드 81 T1501**) | 3.Coverage / Test Log — ASIL A 함수 row (구문 커버리지 충분) | `mark_asil_a_function` |
| 🟦 파랑 `FFE2F0FF` (**31차 W29**) | 3.Coverage / Test Log — ASIL B 함수 row (분기 커버리지 필수) | `mark_asil_b_function` |
| 🟧 주황 `FFFFE5CC` (**31차 W29**) | 3.Coverage / Test Log — ASIL C 함수 row (MC/DC 권장) | `mark_asil_c_function` |
| 🔴 빨간 `FFFFC7CE` | 2.Consistency FAIL row Result 셀 | `mark_fail_cell` |
| 🔴 빨간 `FFFFC7CE` (동일 RGB, **30차 W21 의미 분리**) | 3.Coverage / Test Log — ASIL D 함수 row (MC/DC 필수) | `mark_asil_d_function` |
| 기본 (없음) | 자동 채움 (config/meta 정상) | `safe_write` / `_write_label` |

> **라운드 81 5단계 그라데이션**: QM(회색) → A(녹색) → B(파랑) → C(주황) → D(빨강).
> 위험도 단계별 시각 인지. 회사 v3.01/v2.02 양식은 빨강만 표준이라 audit reviewer
> 사전 통보 의무 (라운드 81 commit `f609ba5`).

> **30차 W21 의미 분리**: `mark_fail_cell` ↔ `mark_asil_d_function` 색상 RGB 동일 (`FFFFC7CE`)이나 호출 의미 다름. FAIL = TC 실행 실패, ASIL D = audit 검토 우선순위. 동일 셀 겹치면 ASIL D 우선 (호출 순서 보장). audit reviewer에게 정책 사전 통보 권장.

24차 silent "N/A" 제거 — Actual Coverage/Pass ratio가 data 부재 시 `▶ 사용자 입력 필요 — VectorCAST 데이터 부재 — log_folder 재확인` 명시 (deep-reviewer X7 강화).

## Design Token 단일 출처 (29차 W17)

**Backend RGB / placeholder 단일 출처**: `backend/services/design_tokens.py`
- `USER_INPUT_FILL_RGB = "FFFFEB9C"` — Excel 셀 노란 배경
- `FAIL_FILL_RGB = "FFFFC7CE"` — Excel 셀 빨간 배경 (TC 실행 실패)
- `ASIL_D_FILL_RGB = "FFFFC7CE"` — **30차 W21 동일 값 / 의미 분리 (audit MC/DC 우선순위)**
- `ASIL_C_FILL_RGB = "FFFFE5CC"` — **31차 W29 연한 주황 (MC/DC 권장)**
- `ASIL_B_FILL_RGB = "FFE2F0FF"` — **31차 W29 연한 파랑 (분기 커버리지 필수)**
- `ASIL_A_FILL_RGB = "FFE4F3D5"` — **라운드 81 T1501 연한 녹색 (구문 충분, 가장 약한 안전 등급)**
- `ASIL_QM_FILL_RGB = "FFE8E8E8"` — **라운드 81 T1501 연한 회색 (비안전, 정보성)**
- `USER_INPUT_PLACEHOLDER = "▶ 사용자 입력 필요"` — 24차 silent "N/A" 대체 안내

`excel_template_utils.py`가 위 모듈에서 import — 이전 (23~28차) module-level hardcoded 제거. 신규 backend Excel builder는 반드시 `design_tokens`에서 import.

**Backend ↔ Frontend 색상 컨텍스트 매트릭스 (의도된 분리)**:

| 컨텍스트 | 출처 | 용도 |
|----------|------|------|
| Backend Excel 셀 배경 | `design_tokens.py` `USER_INPUT_FILL_RGB`/`FAIL_FILL_RGB`/`ASIL_D_FILL_RGB` (warm pastel — `#FFEB9C`/`#FFC7CE`) | audit reviewer 친화 부드러운 hint |
| Frontend UI 텍스트/badge | `frontend-v2/src/index.css` `--color-warning`/`--color-danger` (Tailwind amber-500/red-500) | UI 시인성 — 명도/대비 강함 |
| **Frontend ASIL D audit (30차 W21)** | `--audit-asil-d-soft` (`#ffe3e8`) / `--audit-asil-d-text` (`#b3261e`) | ASIL 분포 패널에서 ASIL D 항목 강조 — Excel 빨강과 의미 매칭하되 UI 시인성 조정 |

**중요**: 두 컨텍스트는 **단일 RGB로 통합하지 말 것**. Excel 셀 배경(부드러운 톤)과 React UI 텍스트(시인성)는 다른 색상 요구. design tokens는 같은 audit 의미를 가지지만 시각적 구현은 컨텍스트마다 적합한 톤 사용.

**변경 시 동기 정책**: backend `design_tokens.py` RGB 변경 시 본 문서 + audit reviewer 통보 의무 (산출물 시인성 정책 영향).

> **Backward 호환 (W22, 28차 명시)**: 24차 이전 빌드 결과물은 동일 셀에 string `"N/A"` 보유. 회사 audit reviewer가 두 형식 모두 인지하도록 산출물에 라운드(24차+) 표기를 Cover 시트 doc_id_sequence에 포함 권장. 자동 변환/마이그레이션 스크립트는 제공 안 함 — 이전 산출물은 그대로 둘 것. 신규 빌드부터 노란 마킹 적용.
