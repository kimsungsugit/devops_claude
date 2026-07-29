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
| ~~생성기들이 제각각 LLM 에 전체 파일 전달~~ | ⚠ **이 판정은 2026-07-29 에 정정됐다.** "거의 전부 단일 진입점" 은 사실이 아니다 — 독립 egress 가 **3개**다: ①`workflow/ai.py::llm_call`(예산·재시도·stage cap 있음) ②`workflow/llm_adapters.py::*Adapter.generate`(`ai.py` 와 코드 공유 0 — `assistant_service._call_anthropic`·`scripts/generate_periodic_reports.py` 가 **의도적으로 우회**) ③`workflow/rag/embedder.py`(자체 `genai.Client`+자체 키). 즉 CORE-006 은 "정책 계층만" 이 아니라 **경로가 갈라져 있다는 사실 자체**가 문제다. redaction 은 여전히 0건 |
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
| CORE-006 | 공통 LLM Context Gateway | 🟡 | **응답 완결성 검증 완료**(아래 L1). redaction 은 여전히 0건. ⚠ §1 의 "이미 단일 진입점" 판정은 **틀렸다** — 아래 정정 참조 |

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
- ✅ **영향도 리포트가 부풀린 커버리지 하나만 싣던 것** — `_load_linked_doc_summary` 가
  `requirement_coverage["pct"]`(검증방법 무관, RVW 포함)만 뽑아 실었다. 같은 품질 리포트
  안에 있던 정직한 축이 전부 유실됐다. 실측: 리포트엔 `100.0` 만 / 실행시험 `87.3` ·
  함수 기준 `6.4`(무시험 함수 699) · **생성기 경고 2건**은 미노출.
  → 축 전부 + 경고를 전달하고 라벨에 축을 명시(`검증방법 무관`). SITS 흐름 캡 축도 함께.
  키는 additive 라 구 payload·타 문서종은 렌더러가 줄을 생략한다.
  곁가지로 `coverage_warnings` 가 외부 JSON 이라 int 면 크래시·str 이면 **글자 단위 순회**
  하던 것을 `_as_str_list` 로 차단(테스트가 잡았다).

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
- ✅ **LLM 응답 완결성 + 근거 등급 정직성 3건**(L1/L2/L3) — 아래 별도 절
- ⬜ CORE-006 잔여: `agent_call` 에 경로·시크릿 redaction(저장소 전체 0건), 모델 echo 대조
  (`meta_out["model"]` 은 호출 **전** config 값이라 응답 출처를 대조하지 않는다),
  그리고 위 3개 egress 경로 통합

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

## 5-1. LLM·근거 축 3건 — ✅ 완료 (2026-07-29)

전부 "확인하지 못한 것을 확인한 것처럼 다룬다" 는 같은 부류다.

| # | 결함 | 실측 재현 | 조치 |
|---|---|---|---|
| L1 | **잘린 응답과 완결된 응답을 구분하지 못했다** — `finish_reason` 이 저장소 전체 **0건** | `STOP`/`MAX_TOKENS`/`SAFETY`/`RECITATION` 네 경우 전부 "절단 신호 없음". 잘린 초안이 완결 산출물로 문서에 들어감 | `_note_finish_reason` 신설(Gemini 신·구 SDK + OpenAI 호환 **3경로**). `agent_call` 이 절단을 **재시도 사유**로 처리 — 소진 시 `ok=False` 라 호출자가 "생성 실패" 를 본다. ⚠ shape 를 못 읽으면 절단으로 **치지 않는다**(`finish_reason_available` 로 "확인 못 함"과 "확인했고 정상" 구분) |
| L2 | **근거 없이 provenance 를 승격했다** | `asil d`→`D` **정규화만** 했는데 `inference`→`rule` / ASIL 이 **아예 없어** QM 기본값을 쓴 경우도 `rule`(0.75) / 출처가 `None` 이어도 `rule` | 정규화는 근거가 아니므로 출처 **불변**. 근거 없는 기본값은 `"default"` 로 명시 |
| L3 | **모르는 출처를 조용히 `inference` 로 접었다** | 생산 어휘 `uds`·`swcom`·`rag`·`module_inherit`·`default`·`srs_default_qm` 이 전부 미지값 → 문서 유래는 0.95→0.60 **과소**, 근거 없는 기본값은 실제 추론과 **동급**. 게다가 표에 "추론" 이라 **찍혀서** 리뷰어가 그 분류를 사실로 읽는다 | 어휘를 생산값에 맞춰 확장(+등급). 미지값은 `inference` 가 아니라 `unknown`(0.30) 이고 **보고서에 목록으로 노출** |

### L4 — 어느 모델이 답했는지 meta 가 거짓을 말했다 (2026-07-30 추가)

`meta_out["model"]` 은 호출 **전** cfg 값으로 한 번만 찍혔다. 400 폴백이 성공하면 답한
모델은 `model_fallback` 이라는 **다른 키**에만 갔고, 그 키는 저장소 어디서도 읽히지
않았다. `meta.get("model")` 을 읽는 소비처(`gui_utils` 의 `ai_model` 2곳)는 **실패한
모델**을 산출물의 모델 근거로 기록했다. `.env` 가 특정 모델을 하드락하는 운영 방식이라
이 값은 근거의 일부다.

→ `_note_effective_model` 로 `model` 키가 **답한 모델**을 가리키게 하고(요청 모델은
`model_requested` 로 보존), provider echo(`model_version`/`model`)를 `model_reported` 로
잡아 어긋나면 경고. 버전 접미사(`gemini-2.5-flash` → `-001`)는 불일치로 안 본다.
echo 가 없으면 **불일치로 단정하지 않는다**(모르는 것은 모른다고 남긴다).

⚠ **L1 수정에 구멍이 있었다** — 400 폴백 분기는 정상 경로의 복사본인데
`_note_finish_reason` 이 빠져 있어 **폴백 응답이 잘려도 완결본으로 통과**했다. 같이 메움.
복사본 분기에 검사가 빠지는 건 이 저장소가 반복해 겪은 패턴이라 AST 테스트로 고정했다.

### L5 — 독립 egress 가 같은 검사를 우회했다 (2026-07-30)

`workflow/llm_adapters.py` 의 어댑터 3종은 `{"output","usage"}` 만 돌려줬다 —
`finish_reason` 미확인, 모델 echo 미확인, 재시도·예산 없음. 이 스택은
`assistant_service._call_anthropic` 과 `scripts/generate_periodic_reports.py` 가
**의도적으로 쓰는 독립 경로**라, L1/L4 수정이 이 경로엔 닿지 않았다.

→ `_completion_meta` 로 세 어댑터가 **`ai.py` 단일 출처 판정**을 쓰게 했다
(`note_finish_reason_value` / `note_effective_model`). 공급자별 shape 추출만 어댑터가 한다:
Gemini `candidates[].finish_reason` / OpenAI `choices[0].finish_reason` /
Anthropic `stop_reason`(`end_turn` 정상, `max_tokens` 절단).

소비처도 맞췄다: `_call_anthropic` 이 잘린 응답을 완결 답변으로 돌려주지 않고 후보
폴백 코드를 낸다 — 다른 챗 경로(`agent_call`)는 절단을 재시도 사유로 다루므로, 이쪽만
통과시키면 **같은 챗이 공급자에 따라 다르게 정직해진다**.

테스트가 어댑터의 판정 복제(`_OK_FINISH_REASONS` 자체 보유)를 금지한다.

### L6 — 나가는 프롬프트의 시크릿 (2026-07-30)

`workflow/ai_validator.py` 에 시크릿 탐지가 있지만 **모듈 전체가 dead code** 다
(importer 는 테스트뿐). 게다가 그 검사는 ①프롬프트가 아니라 **응답**을 보고
②경고만 낼 뿐 가리지 않으며 ③정규식(`password\s*[=:]`·IP)이 이 저장소에선 오탐이
심하다 — 프롬프트에 Jenkins URL 과 C 소스가 늘 들어가 거의 매 호출 경고 = 소음.

→ **정규식 추측을 안 쓴다.** env 에 실제 설정된 값(`GOOGLE_API_KEY`,
`DEVOPS_JENKINS_API_TOKEN` 등 9종, 12자 이상)과 **문자열 대조**만 한다. 오탐이 원리적으로
없다. `llm_call` 은 절단 **뒤**(프롬프트가 나가기 직전)에서, 어댑터 3종은 `generate` 첫
줄에서 가린다. 걸리면 경고 — 시크릿이 프롬프트에 들어갔다는 것 자체가 사고 신호다.

실측: 실제 키만 가려지고 `Jenkins 192.168.110.40:7000 … password = check_pw(x);` 는
**그대로** 통과. 시크릿 미설정 시 완전 no-op(사본조차 안 만듦).

`ai_validator.py` 의 docstring 도 고쳤다 — "민감정보 노출 방지" 를 **하고 있다고 주장**해
리뷰어가 보호받고 있다고 읽었다. 미배선 사실과 실제로 도는 곳을 명시.

### 조사 보고 정정 — redaction 노출은 훨씬 좁다

"응답 전문이 `agent_*.md` 에 무삭제로 남는다" 는 **2개 호출부 한정**이다(AST 전수 조사:
`log_dir` 에 실제 경로를 주는 곳은 `workflow/gui_utils.py` 2곳뿐, 나머지 16곳은 None).
redaction 레이어를 크게 짓는 건 과잉이라 이번 라운드에서 제외했다.

⚠ 이 프로젝트 캐시(900함수)에는 L3 드리프트 값이 **없다**(`asil_source` 900/900 `inference`).
드리프트 값은 이후 enrichment 단계에서 붙으므로 **데이터로는 재현하지 못했다** — 코드 대조로만
확인했다. 별건으로, 이 프로젝트는 전 함수 ASIL·Related 출처가 `inference` 라 신뢰도 **전원 D등급**이다.

---

## 5-2. UDS DOCX 입력 대비 대조 — ✅ 완료 (2026-07-29)

`validate_uds_docx_structure` 가 문서 **내부 정합성**만 봤다(heading 수 ↔ 표 수, logic 행 ↔
이미지 수). "몇 개가 들어와야 했는가" 를 모르므로 양방향 불일치가 통째로 침묵했다.

| 실측 | 값 |
|---|---|
| payload 함수 1 / 5 / 20 / 100 → 문서 SwUFn 섹션 | **항상 429**, `ok=True`, issues 0건 |
| 실 데이터(소스 900 / 템플릿 함수명 421, 빌더 정규화 기준) | 교집합 **271** |
| 문서에 못 실리는 소스 함수 | **629개 (69.9%)** — 조용히 누락 |
| 데이터 없는 템플릿 heading | **150개** — 빈 함수 명세로 출력 |

429 는 admin 설정 템플릿(`docs/(HDPDM01_SUDS)_template_tokenized.docx`)의 heading 수다
(`template_path=None` → `config.resolve_uds_template_path()` 폴백 = **프로덕션 동작**).
DOCX 는 XLSM 라이터와 달리 **템플릿 주도**라(SwUFn heading 을 함수명으로 매칭해 채움)
누락과 빈 채움이 둘 다 가능하다.

**수정**: payload 가 `.payload.json` 사이드카로 DOCX 옆에 이미 기록되므로 검증기가 스스로
찾아 대조한다 — **호출부 4곳 무변경**. 함수명 키는 **빌더 자신의 `_normalize_symbol_name`
을 재사용**한다(검증기가 자체 정규화를 만들면 판정이 갈라진다 — 실측 정확일치 211 vs
빌더 정규화 271, 60건 차이). 사이드카 부재는 `expected_functions=None` + "대조 불가(미검증)"
로 **통과가 아니다**.

⚠ `ok` 판정은 **바꾸지 않았다**. 템플릿이 부분집합을 담는 게 의도일 수 있어 실패로 만들면
정상 산출물이 대량 오탐된다. 대신 `warnings` 로 수치를 드러내 "ok=True 니까 다 들어갔다"
는 오독을 막는다(대조군 테스트로 고정).

곁가지: 리포트가 **절단된 예시 리스트 길이를 개수로** 써서 629건이 "50건 이상" 으로
찍혔다(이 저장소가 반복해 겪은 함정). `*_count` 를 절단 전에 따로 담아 교정.

---

## 6. 다음 라운드 후보

| # | 대상 | 이유 |
|---|---|---|
| ~~1~~ | ~~pre-commit 900s 예산 (P1)~~ | ✅ 완료 — 위 P1 참조 |
| ~~2~~ | ~~`report_gen/` DOCX 라이터 대조 (P2)~~ | ✅ 완료 — 아래 별도 절 |
| ~~3~~ | ~~`impact_orchestrator.py:135` (P0 잔여)~~ | ✅ 완료 — 위 P0 참조 |
| 4 | LLM redaction + 모델 echo 대조 (CORE-006 잔여) | 프롬프트 redaction 저장소 전체 0건. 응답 전문이 `agent_*.md` 에 무삭제로 디스크에 남는다(HTTP 에러 본문 포함). `workflow/ai_validator.py` 의 시크릿 검사는 **모듈 전체가 dead code**(프로덕션 호출자 0) |
| 🟡 5 | 3개 egress 경로 통합 | **부분 완료(L5, 2026-07-30)** — 어댑터 3종이 절단·모델 검사를 공유하게 됐다(`_completion_meta` → `ai.py` 단일 출처). 잔여: 예산·재시도·stage cap 공유, `rag/embedder.py`(자체 client·자체 키) |

---

## 7. 작업 규약 (이 저장소 고유)

- 고치기 **전에 실측**한다. 계획서·docstring·주석의 수치를 사실로 받지 않는다
  (실제로 `parse_hsis_signals` docstring 의 "SwVar=20/Related=21" 은 재현되지 않았다 — 19/20 이 맞다).
- 새 테스트는 **뮤테이션으로 검증**한다. 옛 동작을 되살렸을 때 실패하지 않는 테스트는 무의미하다.
- 같은 판정을 두 곳에 복제하지 않는다. 이 저장소는 그래서 "한쪽만 고쳐지고 다른 쪽 잠복" 을
  반복해 겪었다(`_is_hsis_data_row`, `_ratchet_core`, `_artifact_check` 단일화).
- 미측정을 통과로 바꾸지 않는다. 키가 없으면 **"대조 불가"** 이지 PASS 가 아니다.
- 정책 결정(임계값·기본값·게이트화)은 **노출까지만** 하고 값 결정은 사용자에게 남긴다.
