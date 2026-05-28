# F7 — 회사 표준 양식 호환 + 4 빌더 재설계

> **목적**: backend가 HDPDM01 release 산출물을 잘못된 base template로 사용했던 결함 fix. 회사 표준 양식 (`★개발템플릿 Version3`)을 정확한 base로 사용.

## Context

라운드 D 라이브 진단 결과 4 산출물 모두 partial overwrite + 양식 default 데이터 혼재 결함 발견. 사용자가 회사 표준 양식 경로 제공 — backend가 사용하던 양식과 **완전히 다름**.

### 회사 표준 vs 기존 backend 비교

| 항목 | 회사 표준 (★개발템플릿 V3) | 기존 backend (HDPDM01 release 산출물) |
|------|--------------------------|-----------------------------------|
| SwUTCV 시트 | `Cover/History/1.Test Summary/2.Traceability/3.Consistency/4. Coverage` | `Cover/History/Test Summary/1.Traceability/2.Consistency/3. Coverage` |
| SwUTR 시트 | `Cover/History/1.Test Summary/2.Deviation/3.Test Result` | `Cover/History/Test Summary/Deviation/Test Log` |
| SwITR 시트 | `Cover/History/1.Test Summary/2.Test Log` (4 시트) | path 미존재 |
| SwITCV (핵심) | `Cover/History/1.Test Summary/2.Traceability/3.Consistency/4.Coverage` + **2.Traceability에 SwITC×SwST/SwSTR matrix 실재** | F4-C에서 "양식 부재" 잘못 판단 |
| SwITCV 4.Coverage | **R5=Functions, R6=Function Calls 별도** | F6-C 작업 의도와 정확히 일치 |
| SwITR 2.Test Log | R6 header: TC ID/Description/Generation Method/Precondition/Param. C3=sub-index, C4=description text | NW15 자동 감지 fallback과 동일 |

### 4가지 핵심 결함 (라운드 D 진단)

1. **잘못된 base template** — HDPDM01 release 산출물 사용 → 419 함수 default 포함
2. **F4-C "SwITC×SwST matrix 부재" 오판** — 회사 표준에 명확히 존재
3. **시트명 prefix 번호 미인식** — `1.Test Summary` vs `Test Summary`
4. **partial overwrite** — clear policy 부재 (라운드 D T601에서 helper 완성)

## 사용자 의사 결정 (확정)

- 라운드 D 전면 재설계 → F7 신규 라운드
- 회사 표준 양식 path를 backend의 base로 변경
- F4-C SwST matrix 재구현
- 시트명 prefix 매핑 정책
- 권한 위임 — 자율 진행

## 작업 흐름 (T701~T715, 순차 실행)

```
T701 config/swut_meta.json — 회사 표준 template path 추가 + project XXXX placeholder
T702 excel_layout_resolver — 시트명 prefix 매칭 (1.Test Summary ↔ Test Summary 호환)
T703 swut_sutr_aggregator — sheet name lookup 'Test Log' → '3.Test Result' 매핑
T704 swit_sitr_aggregator — SwITR layout (NW15 자동 감지 fallback 회사 표준 검증)
T705 SwITCV SwST matrix builder 신규 — F4-C 재작업 (matrix_kind="switc_x_swst" 정정)
T706 SwITCV 4.Coverage — F6-C HMR Functions+Function Calls 정확 위치 적용
T707 clear policy 4 builder 적용 — T601 clear_data_range helper 사용
T708 Cover 시트 label 확장 — Author/Reviewer/Approver/Project Name fallback
T709 회귀 +30:
  - test_excel_layout_resolver 시트명 prefix +5
  - test_swut_aggregators / test_swit_* clear policy +10
  - test_swit_coverage_aggregator SwST matrix +5
  - test_company_standard_template 라이브 fixture +10
T710 라이브 재빌드 4 양식 (live_build_4_artifacts.py 회사 표준 path로) + diff 비교
T711~T715 자체평가 deep-reviewer 적응형 다회 + fix
F7 종료 commit
```

## 변경 파일

### 신규 (2 파일)
- 없음 — 모두 기존 파일 수정 + 회귀 추가

### 수정 (10+ 파일)
| 파일 | 변경 |
|------|------|
| `config/swut_meta.json` | 회사 표준 template path + project XXXX placeholder 치환 |
| `backend/services/excel_layout_resolver.py` | 시트명 prefix 매칭 (1.Test Summary ↔ Test Summary) |
| `backend/services/swut_coverage_aggregator.py` | 시트명 lookup `Test Summary` → `1.Test Summary` fallback + clear policy 적용 |
| `backend/services/swut_sutr_aggregator.py` | 시트명 `Test Log` → `3.Test Result` 매핑 + clear policy |
| `backend/services/swit_coverage_aggregator.py` | 회사 표준 SwITCV 6 시트 호환 + SwST matrix builder + F6-C Function Calls |
| `backend/services/swit_sitr_aggregator.py` | SwITR 4 시트 + Description col layout + clear policy |
| `backend/services/excel_template_utils.py` | (T601 완료) clear_data_range helper |
| `tests/unit/test_*.py` | 회귀 +30 |

## 재사용 자산 (T601 helper + F6 layout)

- `clear_data_range` (T601 완료 — 라운드 D 흡수)
- `SwitLayout` (F6 NW15) — description col auto-detect fallback이 회사 표준에도 적용
- `format_breakdown_label` (F6 NF3) — warning prefix 단일 출처
- `validate_evidence_grounding` (라운드 C T507) — 추후 SwUT/SwIT 영역 적용 후보

## 위험 / 완화

| Risk | 완화 |
|------|------|
| R1: 회사 표준 양식 변경 시 backend 영향 | template path config 외부화 + 양식 자체 inspect 회귀 |
| R2: HDPDM01 기존 산출물 backward-compat | sheet name lookup이 양쪽 다 매칭 — fallback chain |
| R3: SwST matrix 실 데이터 부재 (synthetic session) | session에 SwST mapping field 추가 또는 SwITS spec에서 추출 |
| R4: clear policy가 양식 default 함수 list 삭제 | preserve 옵션 — Coverage 시트의 함수 list는 보존, Test Log/Deviation만 clear |

## 비-목표 (별도 라운드)

- SwITS spec에서 SwST/SwSTR ID 추출 (F4-C에서 시작했던 작업) — 별도 라운드
- 회사 표준 양식 자체 수정 (audit reviewer 협의)
- LLM hallucination 검증 (라운드 C 완료)

---

이 plan은 라운드 D를 전면 재설계 + F6 carry-over (NW15 등) 흡수. 사용자 명시 "끝까지 자율 진행".
