# ARIA 자동화 고도화 — 실행계획 v2 (우리 판정본)

> **이 문서의 위치**
> 외부 작성 문서 `outputs/ARIA_문서별_자동화_고도화_구현계획.md`(1,718줄, 2026-07-28)를
> 코드와 전수 대조한 뒤 **우리 판단으로 재구성한 실행계획**이다.
>
> ⚠ 원본은 `outputs/` 에 있는데 **한 번도 커밋된 적이 없다**(ignore 규칙이 아니라 그냥
> 안 올렸다 — `outputs/*.md` 는 untracked). 원본이 사라져도 이 문서만으로 판정·현황·
> 다음 할 일이 자립하도록 썼다.
>
> ⚠ 이 문서를 `plans/` 나 `docs/` 루트에 두면 안 된다 — 둘 다 `.gitignore` 에 막혀 있다
> (`plans/`, `docs/*`). `docs/` 는 allow-list 방식이라 `!docs/plans/` 를 추가해 열었다.
>
> 최종 갱신: 2026-07-29 / 대조 기준 커밋: `6da9e96`

---

## 0. 한 줄 요약

외부 계획서는 **그대로 따르면 안 된다.** 이미 구현된 것을 문제로 적어둔 항목이 여럿이고,
가장 큰 덩어리(CORE-000)는 이 저장소 규모에서 수개월짜리인데 그것을 P0 로 두었다.
실측으로 재현된 것만 골라 5개 라운드에 걸쳐 고쳤고, **계획서에 없던 결함을 더 많이 찾았다.**

---

## 1. 계획서가 틀렸거나 이미 구현돼 있던 것 — 재작업 금지

| 계획서 주장 | 실제 (코드 대조) |
|---|---|
| SwUTR/SwUTCV 가 total=0 을 100% 로 처리 | **이미 fail-closed.** `swut_sutr_aggregator` 가 N/A+경고, `swut_input_adapter` 가 `passed>total` 차단, `compute_coverage_rollup` 이 degenerate MC/DC 중화 |
| 생성기들이 제각각 LLM 에 전체 파일 전달 | 호출 11곳이 거의 전부 `workflow/ai.py` 의 `llm_call`/`agent_call` **단일 진입점** 경유 → gateway 신설이 아니라 **기존 진입점에 정책 계층**을 얹는 게 맞다. 단 redaction 코드는 실제로 0건 |
| `SwCom_XX` placeholder 미감지 | `report_gen/trace_integrity.py` 가 placeholder·정규화충돌·dangling 감사 **이미 구현** |
| UDS provenance 부족 | `description_source`/`asil_source`/`related_source`/`calls_source`/`range_source` **이미 존재** |

> `A3-S`/`A3-E`/`A4` 는 ISO 26262 표준 용어가 아니라 **계획서 저자의 내부 어휘**다
> (계획서 본문이 스스로 명시). 도입하면 기존 `QualitySummary.gate_pass` 경로를 전부 건드려야 한다.

---

## 2. 항목별 현황 (계획서 번호 31개 전수)

범례: ✅ 완료 · 🟡 부분 · ⬜ 미착수 · ⛔ 보류 결정

### 2.1 공통 기반 (CORE)

| ID | 항목 | 상태 | 근거 |
|---|---|---|---|
| CORE-000A~F | ArtifactEnvelope·EvidenceRef·FieldState·ApprovalRecord·QualityState | ⛔ | 코드 **0건**. contracts 8모듈 + DB 마이그레이션 + 수용시험 43개 = 수개월. §5 참조 |
| CORE-001 | Baseline·산출물 컨텍스트 SSOT | ⬜ | `BaselineManifest` 코드 0건 |
| CORE-002 | 로컬·워커 공통 FileResolver | 🟡 | `_resolved_doc_input`(suts) · `_doc_or_discovered`(local.py 17곳) 도입. 전 생성기 통합은 미완 |
| CORE-003 | 근거·추정·검증 결과 공통 계약 | 🟡 | provenance 필드는 이미 존재. `not_measured` 계약은 **0건** |
| CORE-004 | 품질 DB ↔ 승인 피드백 | ⬜ | |
| CORE-005 | Baseline Manifest 기반 fail-closed gate | 🟡 | validator 예외 fail-closed 는 됨(STS B7). **baseline mismatch 축은 미착수** |
| CORE-006 | 공통 LLM Context Gateway | ⬜ | `ContextGateway` 0건, redaction 0건. **단 §1 대로 gateway 신설은 불필요** — `agent_call` 에 정책 계층만 |

### 2.2 문서별

| ID | 항목 | 상태 | 커밋 / 근거 |
|---|---|---|---|
| UDS-001 | 함수 inventory·근거 등급 고정 | 🟡 | provenance 이미 존재, 등급 고정은 미완 |
| UDS-002 | LLM fail-closed gate | 🟡 | reject 표면화 `88a3a63`, 병렬경로 **미검토 선언** `1bfdee9`. ⚠ **실제 검증 수행은 여전히 안 함** |
| UDS-003 | 상위 추적성 roll-up | ⬜ | (별건으로 `design_bridge` 등 일부 존재) |
| **STS-001** | Excel schema SSOT·validator 교정 | ✅ | `88a3a63` — `_detect_sts_columns` |
| **STS-002** | 커버리지 지표 분리 (review-only vs executable) | ✅ | `983eaae` — `_REVIEW_ONLY_METHODS`. 실측 100.0% → 실행시험 87.3% |
| STS-003 | Evidence-bound Expected Result | ⬜ | |
| STS-004 | 변경분 재생성 | ⬜ | |
| **SUTS-001** | SDS 입력 실사용 및 resolver 적용 | ✅ | `1bfdee9` — `_resolve_sds_map`/`load_sds_map_from` |
| SUTS-002 | 관찰점·oracle 계약 | ⬜ | |
| SUTS-003 | MC/DC 독립효과 증명 | ⬜ | |
| SUTS-004 | VectorCAST round-trip | ⬜ | |
| **SITS-001A** | Synthetic SwCom trace 제외 | ✅ | `88a3a63` — `synthetic_related_ids` |
| SITS-001B | SDS 기반 component graph | ⬜ | |
| SITS-002 | SDS·HSIS·UDS 실사용 | 🟡 | HSIS 경로는 `1bfdee9` 로 정리, 나머지 미완 |
| SITS-003 | 호출·순서·시간·오류전파 모델 | ⬜ | |
| SITS-004 | VectorCAST integration round-trip | ⬜ | |

### 2.3 VectorCAST 결과 문서 · 추적성/RAG

| ID | 항목 | 상태 | 비고 |
|---|---|---|---|
| UTR-001 | 결과 상태 fail-closed | 🟡 | **Final Result 도출 완료**(`compute_final_result`) — 실측: 실패 5/5 인 SUTR 이 `OK` 로 찍히고 있었다(경고 0건). 잔여: raw verdict 문자열 보존, deviation 별도 집계 |
| UTCV-001 | 구조 커버리지 원시값 보존 | 🟡 | **실측/합성 구분 완료**(`CoverageStats.measured`) — 실측: HMR 미제공 시 rollup 이 **100.0%**(측정 0건인데 ASIL 게이트 통과), 실측 30%+합성이 41.18% 로 부풀림. 잔여: `applicable` 정책축, exception disposition |
| ITR-001 | 통합시험 결과 ↔ call edge 정합 | ⛔ | **현재 데이터로 구현 불가.** VectorCAST 가 edge 식별자를 안 준다 — HMR 은 함수당 스칼라(`covered_calls`/`total_calls`)뿐이고 `call_tree.py` ↔ 커버리지 코드 참조 0건. 계획서 자신도 SITS-004 에서 인정한다. edge 계측 로그가 생기면 재검토 |
| ITCV-001 | Function Call coverage ↔ graph reconciliation | ⬜ | 같은 제약. `Functions`/`Function Calls` 분리는 `FunctionCallsMetric` 에 이미 있음 |
| TRACE-001 | 추적 링크 graph SSOT | ⬜ | |
| RAG-001~003 | revision-aware ingestion / 승인 피드백 / 6-domain KB | ⬜ | |

**집계: 완료 5 · 부분 5 · 미착수 20 · 보류 1 (총 31)**

---

## 3. 계획서에 **없던** 결함 — 우리가 찾아 고친 것

전부 같은 결함군이다: **틀렸거나 불완전한 데이터가 경고 없이 정상 산출물로 나온다.**
계획서가 제시한 항목보다 이쪽이 실측 피해가 컸다.

| 결함 | 실측 | 커밋 |
|---|---|---|
| HSIS signal 캐시가 **전역** — 빈 문서로 재호출해도 첫 파일 20건이 동일 객체로 반환(`is` → True) | 장기 기동 서버라 프로젝트 A→B 오염 실제 가능 | `1bfdee9` |
| HSIS 행 판정이 **복제**돼 한쪽만 고쳐진 상태 | 21건 중 1건 누락 | `1bfdee9` |
| SUTS ASIL 이 사용자 SDS 를 무시하고 저장소 `docs/` 사용 | KJPDS02 SUTS 가 **HDPDM01 ASIL** 로 채워짐 | `1bfdee9` |
| UDS 병렬 경로가 미검토본을 검토본으로 위장 | 검증 키를 **한 개도** 안 채워 소비자 `.get()` 이 falsy=문제없음 | `1bfdee9` |
| TC 생성 캡이 요구당 함수 루프를 **기록 없이** 절단 | 매핑 함수 **747개 중 48개만** TC 보유(93.6% 무시험), 보고 커버리지는 100.0% | `983eaae` |
| 지정 문서를 못 읽으면 저장소 `docs/` **다른 프로젝트 문서로 조용히 대체** | **17곳**. cloudium worker-only 경로(`U:\…`)는 상시 이 경로 | `983eaae` |
| SITS 통합 흐름 캡이 안전등급 무관하게 알파벳 절단 | 145개 중 25개 폐기, 그 중 **ASIL A 7건** | `0c4d49a` |
| 생성 N ↔ 파일 기록 K 를 **아무도 대조 안 함** (3개 생성기 전부) | SUTS 는 대조 인자가 있는데도 호출부 4곳 전부 `None` | `6da9e96` |
| SITS 검증기가 sub-case 를 **34.8% 과소** 계수 | 파일 1288행 중 840만 셈, `avg` 7.0(실제 10.7), 그래도 `valid=True` | `6da9e96` |

---

## 4. 우리 우선순위 (재정렬)

계획서의 P0 는 CORE-000 을 맨 앞에 두지만, **그건 수개월짜리라 그 사이 산출물은 계속
거짓 PASS 를 낸다.** 우리는 "지금 나가는 문서가 거짓말하지 않게" 를 먼저 둔다.

### P0 — 산출물 정직성 (진행 중, 5라운드 완료)

- ✅ STS-001 / STS-002 / SITS-001A / SUTS-001
- ✅ §3 의 9건
- ⬜ **남은 것**: `workflow/impact_orchestrator.py:135` 이 부풀린 `requirement_coverage_pct` 를 영향도 리포트에 노출

### P1 — 게이트 자체의 신뢰성

- ✅ **pre-commit 타임아웃이 커밋을 통과시키던 것** — `tests/unit/` 이 2026-07-17 3,486개/281초 →
  2026-07-29 4,638개/**590초**로 자라 900s 예산까지 여유가 310초뿐이었다. 넘으면 훅이 `exit 124` 를
  받아 `"Skipping — commit allowed"` 로 **커밋을 통과시켰다**(무게이트 강등). 두 갈래로 고침:
  ① xdist `-n auto` 로 590→**179초**(18코어, 결과는 직렬과 완전 일치 — 3회 확인),
  ② 그래도 예산에 닿으면 **fail-closed(중단)**. 이 저장소에서 "오래 걸림" 의 실체는 느림이 아니라
  **hang** 이었으므로(재진입 데드락·tkinter 모달) 통과시킬 대상이 아니다.
  부수 효과: 게이트가 ~3.5분이라 이제 포그라운드 커밋이 가능해져 **동시 세션 흡수 창이 9분 → 3.5분**으로 줄었다.
- ⬜ **CI 는 xdist 미적용** — `ci.yml` 은 timeout 이 없어 하드 게이트라 급하지 않지만,
  windows 러너에서 직렬로 도는 만큼 느리다(coverage 병행 시 xdist 설정 주의). 별건.
- ⬜ **CI 가 `test_impact_jobs.py` 를 `--ignore` 로 제외한다** — 로컬은 돌고 CI 는 안 도는 파일이 하나 있다.
- ⬜ CORE-003 `not_measured` **경량** 계약 (전면 스키마 아님) — 미측정을 0/PASS 와 구분
- ⬜ CORE-006 대체안: `agent_call` 에 경로·시크릿 redaction + 응답 ID 대조 (gateway 신설 아님)

### P2 — 결과 왕복

- ⬜ UTCV-001 / ITCV-001 원시 분자·분모 보존
- ⬜ SUTS-004 / SITS-004 VectorCAST TC ID round-trip
- ⬜ UTR-001 / ITR-001 final result fail-closed
- ⬜ `report_gen/` DOCX 라이터 계층 — XLSM 3종은 `6da9e96` 로 생성↔기록 대조를 붙였지만 DOCX 경로(`docx_builder`·`uds_generator`)는 미점검

### P3 — 지속 개선

- ⬜ TRACE-001, RAG-001~003, STS-004 delta regeneration

---

## 5. 보류 결정과 근거

| 항목 | 판단 |
|---|---|
| **CORE-000 전체** | ⛔ 보류. ArtifactEnvelope·EvidenceRef·FieldState·ApprovalRecord·QualityState + contracts 8모듈 + DB 마이그레이션 + 수용시험 43개. 이 저장소 규모에서 수개월이고, 그 기간 동안 얻는 게 없다. 같은 목적(거짓 PASS 차단)은 §3 처럼 지점별로 훨씬 싸게 달성된다 |
| **ApprovalRecord 승인축** | ⛔ 보류. 승인 워크플로 자체가 아직 없다 |
| **6-domain 조직 KB** | ⛔ 보류. 단일 프로젝트 KB 도 아직 안정화 전 |
| **함수 기준 커버리지 게이트화** | ⛔ 보류. 실측 6.4% 라 게이트에 넣으면 기존 프로젝트가 즉시 FAIL — **정책 결정 사항**이므로 지표 노출만 하고 임계는 안 걸었다 |
| **SITS `max_flows` 기본값 상향** | ⛔ 보류. 실측 프로젝트는 여전히 25개(전부 QM) 부족하나, 전 프로젝트 산출물 크기가 바뀌므로 값 결정은 사용자 몫. 인자로 노출해 코드 수정 없이 조정 가능하게만 함 |

---

## 6. 다음 라운드 후보

| # | 대상 | 이유 |
|---|---|---|
| ~~1~~ | ~~pre-commit 900s 예산 (P1)~~ | ✅ 완료 — 위 P1 참조 |
| 2 | `report_gen/` DOCX 라이터 대조 (P2) | XLSM 만 덮었다 — 같은 결함군이 DOCX 경로에 그대로 남아 있을 수 있다 |
| 3 | `impact_orchestrator.py:135` (P0 잔여) | 부풀린 커버리지가 영향도 리포트로 새어나간다 |
| 4 | UTCV-001 원시 분자·분모 (P2) | 계획서 항목 중 실측 피해가 가장 클 후보 |

---

## 7. 작업 규약 (이 저장소 고유)

- 고치기 **전에 실측**한다. 계획서·docstring·주석의 수치를 사실로 받지 않는다
  (실제로 `parse_hsis_signals` docstring 의 "SwVar=20/Related=21" 은 재현되지 않았다 — 19/20 이 맞다).
- 새 테스트는 **뮤테이션으로 검증**한다. 옛 동작을 되살렸을 때 실패하지 않는 테스트는 무의미하다.
- 같은 판정을 두 곳에 복제하지 않는다. 이 저장소는 그래서 "한쪽만 고쳐지고 다른 쪽 잠복" 을
  반복해 겪었다(`_is_hsis_data_row`, `_ratchet_core`, `_artifact_check` 단일화).
- 미측정을 통과로 바꾸지 않는다. 키가 없으면 **"대조 불가"** 이지 PASS 가 아니다.
- 정책 결정(임계값·기본값·게이트화)은 **노출까지만** 하고 값 결정은 사용자에게 남긴다.
