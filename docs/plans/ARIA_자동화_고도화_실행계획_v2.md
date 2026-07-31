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
> 최종 갱신: 2026-07-30 / 대조 기준 커밋: `03eedf1`

---

## 0. 한 줄 요약

외부 계획서는 **그대로 따르면 안 된다.** 이미 구현된 것을 문제로 적어둔 항목이 여럿이고,
가장 큰 덩어리(CORE-000)는 이 저장소 규모에서 수개월짜리인데 그것을 P0 로 두었다.
실측으로 재현된 것만 골라 9개 라운드에 걸쳐 고쳤고, **계획서에 없던 결함을 더 많이 찾았다.**

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

## 5-3. RAG 근거의 정직성 — ✅ 완료 (2026-07-30)

`rag/embedder.py` 를 "예산·재시도 공유" 관점으로 보러 갔다가 **훨씬 심한 것**을 실측했다.
남은 항목(§6 #5)이 예상한 결함이 아니었으므로 판정을 여기로 옮긴다.

### 실측 (고치기 전)

| 측정 | 값 |
|---|---|
| 저장소 실 KB 엔트리의 벡터 | **102/102 건이 64차원 무작위 난수** (Gemini 키 부재 → 최후 폴백) |
| `semantic_search` 가 "관련 근거" 로 통과시킨 수 | **52/102 건**, 점수 0.20~0.25, 경고 **0건** |
| 반환 항목에 열화 표시 | **없음** (`embed_degraded`·`embed_model`·`warning` 전부 부재) |
| `_embed_random` 프로세스간 결정성 | **없음** — 같은 문자열이 3개 프로세스에서 전부 다른 벡터 (docstring 은 "seed 고정" 이라고 주장) |
| `cosine_similarity` 64 vs 768 | **zero-pad 후 계산** → 앞 64차원만 쓴 무의미한 수를 그럴듯한 유사도로 위장 |
| 이 근거의 소비처 | **9곳** — assistant 답변, `report_gen/docx_builder.py:2102`(**생성 문서 본문**), `backend/helpers/uds.py:1493`, `pipeline.py:3222` 등 |

즉 "근거 없음" 이 아니라 **난수를 근거로 제시**하고 있었고, 그게 생성 문서에까지 흘렀다.

### 수정 (커밋 대기)

1. **출처 관측** — `get_embedding(text, meta_out={})` 가
   `embed_source`/`embed_model`/`embed_dim`/`degraded` 를 기록한다(additive kwarg — 기존 호출
   9곳 무영향). `degraded` 판정은 `_note_embed` **단일 출처**.
2. **열화 벡터로 랭킹하지 않는다** — `semantic_search` 는 질의 임베딩이 `degraded` 면 `[]` +
   경고 + `stats_out["semantic_disabled_reason"]`. `hybrid_search` 는 keyword 단독으로 강등되고
   **RRF 로 감싸지 않는다**(감싸면 점수 척도가 ≤0.0328 로 바뀌어 소비처가 오독).
3. **차원 불일치는 위장하지 않는다** — `cosine_similarity` mismatch → `0.0`("관계 미확인").
   `semantic_search` 는 몇 건이 그래서 빠졌는지 세어 보고한다(침묵 드롭 아님).
4. **무작위 벡터는 캐시하지 않는다** — 설정 dim 이 64 면 캐시에 들어가고, 캐시 히트는
   `source="cache"` 로 되읽혀 **열화 표시가 소멸**했다.
5. **`_embed_random` seed 를 `hashlib.blake2b`** 로 — 프로세스 경계에서도 결정적.
6. **저장 엔트리에 출처를 심는다** — `metadata["embed"]`(이미 JSON 컬럼이라 스키마 변경 0).
   실 KB 102건은 사후 판별이 불가능했다.
7. **합성 요약이 실제 근거보다 위에 오던 것** — `retrieval/hybrid.py::_report_hits` 의
   합성 항목 점수가 `0.35` 하드코딩이라 RRF 근거(상한 0.0328)를 **항상 눌렀다**.
   실제 근거 최솟값 아래로 내리고 `chunk_text` 에도 "[합성 요약]" 을 명시(LLM 은 metadata
   플래그를 안 읽는다).

### 부수 발견 — 고치지 않고 사실만 남긴 것

`assistant_service._kb_hints` 의 `score < 0.3` 컷은 RRF 상한 0.0328 대비
**구조적으로 통과 불가**다(`< 0.3` = Initial commit, RRF = a9cd852 — 리팩터가 척도를 10배
바꿨는데 소비처 문턱이 그대로 남았다). 다만 이 함수는 **호출자 0건(dead code)** 이라 라이브
영향이 없다. 되살릴 때 먼저 고치도록 docstring 에 사유를 박아 뒀고, 척도 계약은
`test_rrf_score_upper_bound_is_documented` 가 앵커로 고정한다.

### 검증

- 새 테스트 27건 (`tests/unit/test_rag_embed_provenance.py`) — **뮤테이션 6/6 확인**
  (M1 pad 복원 / M2 `hash()` 복원 / M3 degraded 가드 제거 / M4 dim 집계 제거 /
  M5 keyword 폴백 제거 / M6 합성점수 0.35 복원 → 각각 해당 테스트가 실패)
- **음성 대조군** 포함 — 정상 임베딩에서는 semantic 이 살아 있고 RRF 융합이 유지된다
  (없으면 `return []` 무조건 실행으로도 통과하는 공허한 테스트가 된다)
- 화석 테스트 1건 교정 — `test_dimension_mismatch_pads` 는 결함을 단언하고 있었다
- `test_rag_kb_cache.py` 의 `get_embedding` 스텁이 시그니처를 미러링하지 않아 깨졌다 → 수정
- 회귀 **4,823 passed / 1 skipped** (병렬 245s), ruff ratchet 신규 위반 0

---

## 5-4. 품질 게이트의 vacuous truth — ✅ 완료 (2026-07-30)

게이트가 **"검사 0건"을 통과로 기록**하고 있었다. 원인은 한 줄이다:

```python
gate_pass = all(m.get("gate_pass", True) for m in metrics if m.get("gate_pass") is not None)
```

필터를 거친 제너레이터가 비면 `all([])` 은 **True** 다.

### 실측 (고치기 전)

| 상황 | 옛 결과 |
|---|---|
| 알 수 없는 `doc_type` → `metrics=[]` (`recorder.py:139` 의 실제 분기) | **`gate_pass=True`**, score=0.0 — 점수 0인데 통과로 DB 기록 |
| `config.UDS_QUALITY_GATE_THRESHOLDS` 부재/import 실패 | 11개 지표 전부 `threshold=None` → 검사 0건인데 **`gate_pass=True`** |
| 같은 상황의 점수 | 다른 규칙(페널티 없는 `_pct` 평균)으로 계산 → 게이트 점수와 **비교 불가**. 참고지표가 높으면 오히려 **오른다**(실측 64.71 → 68.0) |

두 번째가 특히 나쁘다: `try/except Exception: thresholds = {}` 가 어떤 config 실패든 삼키고
`getattr(config, ..., {})` 가 키 rename/삭제까지 삼킨다 — **config 리팩터 한 번으로 UDS
게이트가 경고 한 줄 없이 꺼지고**, 그 상태가 "통과"로 남는다.

### 수정

1. **판정을 `evaluator.compute_gate_verdict` 단일 출처로** 뽑았다(예전엔 recorder 인라인).
   게이트 대상이 0개면 `gate_pass=False` + `reason="no_gated_metric"` — **fail-closed**.
2. **`gated_metric_count` 를 DB 에 기록** — 나중에 DB 만 보고도 "게이트 항목이 0개였다"를
   되짚을 수 있다. `threshold=None` 이라 판정에는 끼어들지 않는다.
3. **UDS threshold 소실을 경고 + 지표로** — `quality_thresholds_missing` (사유도 로깅).
4. **advisor 문구 2건 교정** — ① `gated_count==0` 이면 "통과/미통과"가 아니라 "판정 불가"로
   말한다 ② 게이트 미통과인데 제안 0건일 때 "모든 항목이 임계값을 통과했습니다"라고
   말하던 것을 막았다(게이트 결과와 정면 모순이었다).

### 측정으로 **막은** 잘못된 변경

- UDS 의 `quick_gate.gate_pass` 지표에 threshold 를 걸어 게이트화하려 했으나, 코드 주석
  (`T5 진실원 통일`)대로 backend 의 quick_gate 가 **같은 7필드·같은 임계**를 쓰는 것이
  확인돼 중복이었다 → 하지 않았다.
- advisor 의 `not suggestions → "모든 항목 통과"` 가 게이트 FAIL 과 모순되는 케이스를
  실측했더니 sits·swreport 에서는 **제안이 정상 생성**돼 재현되지 않았다. 재현되는 조건
  (실패 지표에 advice 규칙 없음)만 좁혀 고쳤다.
- 같은 vacuous-truth 패턴을 저장소 전체에서 훑었다 → `recorder.py:142` **한 곳뿐**
  (복제본 없음). 이 저장소가 반복해 겪은 "한쪽만 고쳐짐" 은 이번엔 해당 없다.

### 검증

- 새 테스트 22건 (`tests/unit/test_quality_gate_vacuous_pass.py`) — **뮤테이션 5/5 확인**
  (verdict 가드 제거 / recorder 인라인 복원 / missing 지표 제거 / advisor 2분기 제거)
- **evaluator 7종 전수 계약 테스트** — 어떤 doc_type 이든 게이트 대상 ≥1 이어야 하고,
  빈 입력은 fail-closed 여야 한다. threshold 를 떼는 회귀를 이 테스트가 잡는다
- 음성 대조군 4건 — 정상 통과 실행·정상 config·진짜 전부통과 문구가 오염되지 않음
- ⚠ **내 주장 1건이 테스트에서 틀린 게 드러나 정정**했다: "게이트를 잃으면 점수가 오른다"는
  **데이터 의존**이었다(참고지표 global/static 값에 좌우 — 64.71→68.0 상승 / →59.11 하락).
  핵심은 "항상 오른다"가 아니라 **척도가 달라 비교 불가**라는 것이라 그렇게 고정했다
- 기존 quality 테스트 138건 통과

---

## 5-5. RAG 근본 원인 + 재인덱싱 + 진단 배선 — ✅ 완료 (2026-07-30)

§5-3 에서 "실 KB 102건이 전부 무작위 벡터" 를 고쳤지만 **왜 그렇게 됐는지**는 틀리게 적었다.

### ⚠ 앞선 판정 정정 — "Gemini 키 부재" 가 아니었다

키는 **실재한다**. `OAI_CONFIG_LIST` 에 2건(len 39) 있고 **env 는 전부 비어 있다**:

| 경로 | 키를 어디서 읽나 | 결과 |
|---|---|---|
| `workflow/ai.py::llm_call` | `cfg["api_key"]` (`load_oai_configs`) | **정상 동작** |
| `workflow/rag/embedder.py` | `os.environ` **만** | 클라이언트 생성 실패 → HTTP → local → **무작위 벡터** |

**같은 자격증명 · 두 개의 해석기 · 한쪽만 조용히 실패.** 이게 KB 가 난수였던 근본 원인이고,
"키가 없다" 는 내 판정은 사실이 아니었다. 앞선 라운드 커밋 메시지·§5-3 의 "(Gemini 키 부재)"
표기는 이 절로 정정한다.

### 그 밖에 실측된 격차

| 항목 | 옛 상태 |
|---|---|
| `_embed_gemini` 재시도 | **0회**(`_embed_http` 는 2회) — 일시적 429 하나가 `learn()` 엔트리를 **영구** 오염 |
| 입력 길이 가드 | **전무**(`max_input`·`[:N]`·`truncat`·`2048` 패턴 전부 0건) — 상한 초과 → API 거부 → 무작위 벡터 |
| 폴백 사유 | 미기록 — `degraded=True` 만 있어 "키 미해석"·"429"·"입력 초과" 구분 불가 |
| 재인덱싱 경로 | **없음** — 백엔드를 붙여도 기존 64차원 벡터가 남아 dim mismatch 로 전량 제외 |

### 수정 (3건 한 묶음)

**#1 진단을 사용자까지 배선** — `KnowledgeBase.search(stats_out=)` → `_report_hits(notes_out=)`
→ `retrieve_contexts` → `_retrieval_hints` → 응답 `retrieval_notes` + LLM 컨텍스트
(`RET#note` 를 근거 **앞**에 둔다 — 뒤쪽은 절단될 수 있고 신뢰 범위를 먼저 알아야 한다) →
프론트 `AiAssistSection` 경고 배너. **경고는 근거가 아니므로 `evidence`/`citations` 에 섞지
않았고**, 근거 목록이 `<details>` 로 접혀 있어 **접지 않고 항상 노출**한다.
`_report_hits` 의 `stats_out` 미지원 TypeError 폴백은 **일부러 두지 않았다** — 두면 stub
불일치가 조용히 "진단 없음" 으로 삼켜진다(실제로 이 결정이 테스트 19건을 요란하게 깨뜨려
stub 3종을 고치게 만들었다 = 의도한 동작).

**#2 재인덱싱** — `KnowledgeBase.reindex_embeddings(force/dry_run/limit)` +
`scripts/reindex_kb.py` CLI. 백엔드가 **열화 상태면 거부**(무작위 벡터를 다시 쓰는 무의미한
쓰기 방지, `force` 로 우회 가능). 멱등(두 번째는 전량 skip). `metadata.embed.text_field` 를
신설해 어느 필드로 임베딩했는지 기록 — 구 엔트리는 휴리스틱을 쓰고 **그 건수를 보고**한다.

**#3 egress 격차** — `resolve_google_api_key()`(env → `load_oai_configs` 동일 출처),
Gemini 재시도 3회, `_clip_input`(상한 초과 시 **자르고 보고**, 단건·배치 **같은 상한**),
`embed_fallback_reasons`(어느 백엔드가 왜 실패했는지).

### 실측 (수정 후)

| 검증 | 결과 |
|---|---|
키 해석 | `('설정됨 len=39', 'oai_config')` — env 없이도 찾는다 |
재시도 | API 호출 1회 → **3회**, 사유 기록됨 |
입력 상한 | 20,000자 → 6,000자 + `input_truncated` 사유 |
폴백 사유 | gemini/http/local **3건 전부** 기록 |
재인덱싱 | 실 KB 20건: 64차원 → 8차원 전량 교체, 출처 각인, 2회차 전량 skip |
**재인덱싱 효과** | 시맨틱 검색 **0건 → 5건**, `dim_mismatch 20 → 0` |

### 검증

- 새 테스트 27건 (`test_rag_egress_and_reindex.py`) — **뮤테이션 6/6**
  (키 폴백 / 재시도 루프 / 배치 상한 / 열화 거부 가드 / 벡터 교체 / note 생성)
- 음성 대조군 5건 — 정상 키·1회 성공·상한 미만·정상 백엔드·정상 검색에서 부작용 없음
- **스텁 시그니처 회귀 19건**을 내 변경이 드러냈고 3종(`_embed_*` lambda, `_FakeKB.search`,
  `get_embedding`) 전부 실제 시그니처로 미러링

---

## 5-6. UDS DOCX 생성 충실도 — ✅ 완료 (2026-07-30)

P2 백로그의 `report_gen/` DOCX 라이터 대조. XLSM 3종은 `6da9e96` 로 붙였지만 DOCX 는 미점검이었다.

### 실측 (고치기 전)

| 항목 | 값 |
|---|---|
| 프로덕션 성공 판정 | **`returncode == 0 and out_path.exists() and size > 0`** 뿐 |
| payload 함수 (실 HDPDM01) | 432 |
| 템플릿 SwUFn heading | 430 |
| 문서에 반영 | 336 |
| **템플릿에 heading 이 없어 미반영** | **96 = 22.2%** |
| 내용 없이 남은 heading | 75 (그중 템플릿이 "삭제" 로 표기 **10**) |
| 생성 시점 보고 표면 | **없음** |

즉 **함수 22%가 빠진 문서가 `status: "success"`** 로 기록됐다.

### 측정으로 확인한 설계 제약

프로덕션은 `backend/helpers/uds.py` 의 exec 문자열을 **서브프로세스**로 돌리고 반환값을
버린다. 그래서 in-process `stats_out` 은 호출자에 닿지 않고 **파일 sidecar 가 필수**다.

### 수정

- `generate_uds_docx(..., stats_out=)` + **항상** `<out>.gen_stats.json` 기록. 3개 save
  경로(template / placeholder_substitution / no_template) 전부 `mode` 를 남긴다 —
  통계 부재를 "정상" 으로 오독하지 않게.
- 매칭은 **resolver 호출 결과를 실제로 분류**한다. 선언적 집합 차집합은 퍼지 매칭(`endswith`
  tolerance·시그니처 폴백)을 과소 계상해 거짓 경고를 낸다.
- **3축 분리** — 섞으면 수치가 부풀거나 경고가 오탐이 된다:
  `unmatched_payload`(문서에 없음) / `boilerplate_only`(이름만 맞고 내용은 합성) /
  `deleted_heading`(템플릿이 "삭제" 표기 = 갭 아님) / `empty_heading`(나머지 갭)
- `template_source`: `argument` / `config_fallback` / `none` — `template_path=None` 은
  "템플릿 없음" 이 아니라 `resolve_uds_template_path()` 가 저장소 기본 템플릿을 해결한다
  (의도된 admin 동작). 누가 골랐는지 안 남으면 반영률 저하 원인을 못 가른다.
- 총량은 **캡 전**에 센다. 분모 0 → `match_pct=None`(0% 아님).
- `backend/helpers/uds.py`: sidecar 를 읽어 checkpoint 에 `gen_stats` + `warnings` 기록.
  부재는 `gen_stats_missing: true` 로 명시. **성공/실패 판정은 뒤집지 않았다** —
  템플릿이 의도된 부분집합일 수 있어 뒤집으면 대량 오탐(§5-2 와 같은 판단).

### 측정 중 드러난 **별건 결함 2건** (이 라운드에서 고치지 않음)

| # | 결함 | 근거 |
|---|---|---|
| D1 | **사람이 쓴 description 이 `description_source="inference"` 로 강등된다.** `_resolve_related_asil_desc`(`docx_builder.py:1948`)가 **출처 미기록을 전부 `"inference"` 로 확정**한다(asil·related 도 동일). "미기록"과 "추론"은 다른 사실이다. 정직한 값은 `unknown` 이지만 provenance 점수(0.60→0.30)가 전 프로젝트에서 내려가므로 **정책 결정**이다 | 실측: 사람이 쓴 설명을 넣고 생성 → 생성 후 payload 엔트리가 `description_source='inference'` |
| D2 | **생성마다 저장소 고정 참조 SUDS(40.7MB, HDPDM01)를 읽어 함수 정보를 채운다.** `config.UDS_REF_SUDS_PATH` 고정값 + 매칭은 **함수명만**. 빈/TBD 필드만 채우고 `*_source="reference"` 를 남기는 가드는 있으나 **어느 문서인지 안 남는다** — 다른 프로젝트 생성 시 HDPDM01 의 ASIL·Related ID 가 들어갈 수 있다(§3 의 "SUTS ASIL 이 HDPDM01 로 채워짐" 과 같은 패턴, 다른 사이트) | 생성 31.9초 중 **24.3초**가 이 읽기. 함수 2개 payload 인데 `table.text` 64,312회 |

D1 은 이 라운드 지표에서 **회피**했다(설명 축을 근거로 안 쓴다 — 고장난 판정을 지표에서
흉내내면 결함이 복제된다). D2 는 성능·정확성 양쪽이라 별 라운드가 필요하다.

### 검증

- 새 테스트 24건 (`tests/unit/test_uds_docx_gen_stats.py`) — **뮤테이션 6/6**
  (sidecar 기록 / 계측 호출 / 삭제 분기 / description 축 / 캡 전 총량 / shape 검사)
- ⚠ **테스트가 내 전제 2건을 반증했다**: ①`template_path=None` 이 `no_template` 이 아니라
  config 폴백으로 template 경로를 탄다 ②`_finalize_function_fields` 가 빈 함수에 설명·ASIL·
  related 를 합성해 "내용 없음" 단정이 성립하지 않는다. 둘 다 테스트를 실제 동작에 맞췄다.
- ⚠ **테스트 실행시간 711초 → 96초**: `template_path=None` 인 테스트가 실 저장소 템플릿
  (430 heading)을 끌어와 **하나가 313.88초**였다. fixture 로 `UDS_REF_SUDS_PATH`·
  `resolve_uds_template_path` 를 차단(테스트가 40MB 저장소 산출물에 의존할 이유가 없다).

---

## 5-7. 임베딩 백엔드가 죽어 있었다 — 겹친 결함 3층 — ✅ 완료 (2026-07-31)

§5-5 에서 "KB 가 난수인 진짜 원인은 키 미해석" 이라 적고 고쳤다. 그런데 실 KB 에
재인덱싱을 돌리자 **§5-5 에서 만든 fail-closed 가드가 거부**했다 — 백엔드가 여전히
`random` 이었다. 가드가 없었으면 63건을 난수로 다시 덮어쓰고 "완료" 로 끝났을 것이다.

### 실측 — 결함이 층으로 겹쳐 있었다

| # | 결함 | 실측 |
|---|---|---|
| E1 | 모델명 `text-embedding-004` 가 **v1beta 에서 삭제**됨 | `404 NOT_FOUND`. 살아 있는 embedContent 모델은 `gemini-embedding-001` / `gemini-embedding-2(-preview)` **3개뿐** |
| E2 | 신 SDK 응답 언팩이 틀림 | `response.embeddings[0]` 는 pydantic `ContentEmbedding`. `__iter__` 가 값이 아니라 **`('values', [...])` 튜플**을 낸다 → 옛 코드 `[float(v) for v in emb]` = `TypeError`. **단건·배치 두 곳에 복제** |
| E3 | 차원 불일치 | `gemini-embedding-001` native = **3072**, 설정 = 768. `config` 에는 `RAG_EMBED_MODEL`·`RAG_EMBED_DIM` 이 **아예 없었다**(모듈 내부 하드코딩만) |

**E1 만 고치면 소용없다.** API 가 200 을 줘도 E2 의 TypeError 가 `except Exception` 에
잡혀 재시도 3회를 태우고 폴백 체인 → **무작위 벡터**로 귀결된다. E2 까지 고쳐도 E3
때문에 `_cache_put` 이 모든 벡터를 캐시 거부하고(매 호출이 API 왕복) pgvector
`VECTOR(768)` 삽입이 실패한다 — 전부 조용히.

부수 실측 — MRL 절단은 정규화를 깬다: `output_dimensionality` 미지정 3072 는
L2 = 1.000000 이지만 768 절단은 **0.585940**, 1536 은 **0.689938**.

### 수정

1. **E1** — 기본 모델 `gemini-embedding-001`. `RAG_EMBED_MODEL`/`RAG_EMBED_DIM` 을
   `config.py` 로 올려 env 로 덮을 수 있게 했다. 모델이 또 죽어도 설정 표면에서 보인다
2. **E2** — `_coerce_embedding_values()` 단일 함수. `.values` 속성 / 순수 list / dict 를
   전부 받고, 언팩 불가는 예외가 아니라 `None`(재시도 3배 낭비 방지). **단건·배치가
   같은 함수를 쓴다** — 복제가 되살아나면 AST 계약 테스트가 잡는다
3. **E3** — 요청에 `output_dimensionality` 를 **명시**하고 `_normalize_vec()` 로 재정규화.
   그래도 어긋나면 `_check_dim()` 이 **저장하지 않고 오류 로그**(fail-closed) — 기대값과
   실제값을 둘 다 적어 조치 가능하게. 혼합 차원 KB 는 cosine 이 0.0 을 내 해당 엔트리가
   영구히 검색에서 빠지는데, 예전엔 `_cache_put` 이 조용히 캐시만 거부해 **아무 표면에도
   안 나왔다**

### 실측 (수정 후)

- 단건: `embed_source=gemini`, `dim=768`, `L2=1.000000`, `degraded=False`
- 의미 판별력: 관련쌍 cos **0.9469** vs 무관쌍 **0.6949**
- 실 KB 63건 재인덱싱 **63/63 성공 · 실패 0**. 2회차는 `skipped_current=63`(멱등)
- 시맨틱 검색 `semantic_ranked` **0 → 63**, `skipped_dim_mismatch=0`,
  `semantic_disabled_reason=None`

### 검증

- 새 테스트 28건(`tests/unit/test_rag_embed_model_contract.py`) — **뮤테이션 6/6**
  (모델명 / 언팩 / `output_dimensionality` / 차원검사 / 정규화 / 배치 복제 재발)
- ⚠ **테스트가 내 fix 의 버그를 잡았다**: `_coerce_embedding_values` 가 dict 를
  `getattr(obj,"values")` 로 먼저 보는 바람에 **내장 메서드**를 벡터로 취급했다
  (dict 분기가 도달 불가). isinstance 순서를 뒤집어 수정
- 기존 테스트 2건을 차원 인지하도록 갱신 — 스텁이 2·4차원을 반환하며 통과하고 있었다.
  차원 검사가 생기며 드러난 것이므로 **의도된 파장**이다

---

## 5-8. 참조 SUDS 격리 (D2) — ✅ 완료 (2026-07-31)

### 실측 (고치기 전)

`config.UDS_REF_SUDS_PATH` 기본값 = 저장소 `docs/` 의 **HDPDM01 SUDS**(40.7MB).
`generate_uds_docx` 는 프로젝트가 무엇이든 이걸 읽어 **함수명만으로** 매칭해 대상 함수의
`asil`·`related`·`description`·`precondition`·`logic`·`inputs`·`outputs`·`called`·`calling`
을 덧씌웠다. 신원 확인은 **없었다**.

| 항목 | 실측 |
|---|---|
| 참조 함수 블록 | **416개** (고유 함수명 408) |
| `asil` 보유 | 416개 **전부** — A 280 / QM 135 / 파싱오류 1 |
| `related` 보유 | 416개 **전부** |
| 파싱 오류 실물 | `asil = 'void s_Init_SystemManagementFunc( void )'` |

### ⚠ 측정이 내 전제를 절반 뒤집었다

"참조의 ASIL 이 다른 프로젝트로 샌다" 고 봤는데, **실제로 새던 축은 `related` 뿐**이었다.
`asil` 은 병합 지점 **이전**에 `QM`(`asil_source="default"`)으로 채워져 있어 병합의
"빈 칸만 채운다" 조건에 걸리지 않는다. `related` 는 그런 선행 기본값이 없어 참조 값이
그대로 들어왔다 — 통합 테스트로 `SwFn_12` 유입을 직접 관측했다.

그래서 계수기도 고쳤다: 신원 게이트를 맨 앞에 두면 **어차피 적용되지 않았을 시도까지
"차단" 으로 세어** 막은 양이 부풀려진다(2건으로 보고되나 실제는 1건).
판정 순서를 `적용 자격 → 값 유효성 → 신원` 으로 바꿔 계수를 사실과 맞췄다.

### 수정

1. `_reference_identity_verdict()` — 참조 파일명과 payload(`project_name`/`module_name`/
   `source_docs`/`summary.project`)의 프로젝트 토큰을 대조. `True`/`False`/**`None`(판정 불가)**
   3값이며 **`None` 은 확인됨이 아니다**(fail-closed)
2. **안전·추적성 축**(`asil`·`related`·`ref_related_by_name`)은 신원 확인 시에만 적용.
   **서술 축**은 유지 — 틀려도 안전 판정이 아니라 문서 품질 문제다(과잉 차단 방지)
3. ASIL 어휘 검사(`_VALID_ASIL`) — 파싱 오류가 등급으로 굳는 것을 막는다
4. 무엇을 왜 막았는지 `stats_out["reference_suds"]` 로 sidecar 기록(로그만이면 안 보인다)
5. `backend/helpers/uds.py` — 지정 참조 경로가 없을 때 저장소 HDPDM01 로 **조용히 대체**하던
   하드코딩 폴백 제거. `local.py::_pick_doc_path` 와 같은 원칙(지정 실패 = 건너뛰기)

### 검증

- 새 테스트 37건(`tests/unit/test_uds_reference_suds_isolation.py`) — **뮤테이션 7/7**
- ⚠ **처음엔 뮤테이션 2건이 살아남았다.** 판정 규칙을 테스트에 **복제**해 검증했기 때문에
  실제 루프를 고쳐도 통과했다 — 이 저장소가 반복해 겪은 "판정 복제" 실패 모드 그대로다.
  파서만 대체하고 **실제 `generate_uds_docx` 루프를 태우는** 하네스로 다시 썼다
- ⚠ 남은 1건(N7)이 계속 살아남아 조사했더니 **description 분기가 죽어 있었다**(아래 D3)

### D3 (신규 기록, 이 라운드에서 고치지 않음) — 약한 출처가 강한 근거를 선점한다

병합 이전 단계가 칸을 먼저 채워, 프로젝트 **자기 자신의** 설계서조차 닿지 못한다:

| 축 | 선점 값 | 결과 |
|---|---|---|
| `asil` | `QM`, `asil_source="default"` | 참조의 ASIL 이 **영영 적용 안 됨** |
| `description` | 합성문, `description_source="inference"` | 병합의 description 분기가 **사실상 죽은 코드**(실측 `descriptive_fields_applied=0`) |
| `related` | 없음(`TBD` 유지) | 유일하게 적용됨 — 그래서 오염도 여기서 났다 |

저장소엔 이미 이 개념의 어휘가 있다 — `_weak_sources = {"", "inference", "default",
"module_inherit"}`. 병합 자격을 "문자열이 TBD 인가" 가 아니라 **"현재 출처가 약한가"** 로
바꾸면 자기 프로젝트 SUDS 의 ASIL 416건이 살아난다(그중 280건이 `A` 라 **등급 상향** 방향).
다만 HDPDM01 산출물 수치가 이동하는 변경이라 **정책 결정**으로 분리한다.
D2 의 신원 게이트가 먼저 들어갔으므로, 이 변경을 해도 타 프로젝트로는 새지 않는다.

---

## 5-9. 출처 어휘 정직화 + 판정 단일화 (D1) — ✅ 완료 (2026-07-31)

### 실측 (고치기 전)

`_resolve_related_asil_desc` 가 출처 미기록을 **세 축 모두 무조건 `"inference"`** 로
확정했다. 사람이 쓴 설명·실제 등급 `C`·실제 `SwFn_07` 을 넣고 **실제로 생성**한 결과:

| 필드 | 값 | 옛 출처 | 실제 |
|---|---|---|---|
| description | `CAN 수신 버퍼를 검증한다` | `inference` (0.60, 표기 **"추론"**) | 사람이 씀 |
| asil | `C` | `inference` | 주어진 값 |
| related | `SwFn_07` | `inference` | 주어진 값 |

아무것도 추론하지 않았는데 리뷰어가 보는 표에 "추론" 으로 찍힌다. 반대로 값을 **비우면서**
`related_source="inference"` 를 적는 자리도 있어 빈 칸이 같은 0.60 을 받았다 —
**두 방향으로 동시에** 틀렸다.

`validation.py` 의 `src_labels`/`src_score` 엔 `unknown`(미상, 0.30)과 `default`
(기본값·근거 없음, 0.30)가 **이미 1급 어휘**였다. 쓰지 않았을 뿐이다. 생산자
(`function_analyzer.py`)는 이미 **자기가 한 행위에 묶어** 라벨한다(합성했을 때만
`inference`, QM 을 채웠을 때만 `default`) — 규약은 있었고 이 지점만 어겼다.

### ⚠ 라벨 하나가 판정 7곳을 건드렸다

`unknown` 을 도입하려 하니 **"이 출처는 약한가?"** 판정이 서로 다른 리터럴로 복제돼
있었다: `{"", "inference"}` / `{"inference","rule",""}` /
`{"inference","module_inherit","default","rule",""}` / `!= "inference"` / `== "inference"` …

그대로 뒀으면 5곳이 `unknown` 을 **강한 출처로 오인**해 *"출처를 모른다"* 가
*"확정됐다"* 처럼 굳고, 뒤따르는 주석·SDS·SRS 근거가 덮어쓰지 못했을 것이다.
라벨 하나 고치려다 다섯 곳에 구멍을 내는 whack-a-mole 이다.

### 수정

1. `report_gen/provenance.py` 신설 — `WEAK_SOURCES` / `is_weak_source()` /
   `unrecorded_source()` **판정 단일 출처**
2. `unrecorded_source()` 는 **값을 보고** 라벨한다:
   자리표시자 → `default` · 생성기 문구 → `inference` · 실제 값인데 출처 미기록 → `unknown`
3. 값을 비우면서 `inference` 를 적던 2곳 → `default`
4. 판정 복제 6곳을 `is_weak_source()` 로 전환
   (`docx_builder` 4곳 + `function_analyzer` + `routers/local.py`)
5. RAG 보강 게이트가 `!= "inference"` 라 `unknown`·`default` 함수를 통째로 빼던 것도 함께 교정

### 검증

- 새 테스트 47건(`tests/unit/test_provenance_vocabulary.py`) — **뮤테이션 6/6**
- 회귀 **5,051 passed / 1 skipped**
- 회귀 방지 핵심: 주석 근거 업그레이드(`comment_asil` → `asil_source="comment"`)가
  `unknown` 상태에서도 동작하는지 **실제 생성으로** 확인
- AST 계약 테스트로 **판정 리터럴 재등장을 금지**

### 남은 사이트 (의도적 미전환)

`report_gen/requirements.py::enrich_function_details_with_docs` 의 `{"", "inference"}`
1곳. 작업 시점에 그 파일이 **다른 세션의 미커밋 작업**을 담고 있어 손대지 않았다
(내가 넣었던 편집은 외과적으로 되돌렸고, 남의 변경은 그대로 보존).
남은 집합은 `WEAK_SOURCES` 의 **진부분집합**이라 *덜* 덮어쓸 뿐 *잘못* 덮어쓰지는
않는다 — 안전한 방향의 격차다. 잊지 않도록 테스트가 이 상태를 감시한다.

---

## 5-10. SITS 의 SDS 보강이 한 건도 산출한 적 없었다 — ✅ 완료 (2026-07-31)

§5-8(D2) 을 고친 뒤 **같은 결함군의 남은 인스턴스**를 쓸다가 찾았다.
`_load_default_sds_map`(저장소 `docs/` 글롭)이 `sts`·`suts`·`sits` **세 곳에 복제**돼
있는데, 앞의 둘은 `sds_map` 파라미터로 프로젝트 SDS 를 받을 수 있고 docstring 에 경고까지
달려 있었다. **`sits` 만 파라미터가 없어 저장소 문서 고정**이었다.

### 실측 — 두 겹으로 깨져 있었고 둘 다 침묵했다

| # | 결함 | 실측 |
|---|---|---|
| S1 | 프로젝트 SDS 를 쓸 방법이 **없었다** | `collect_integration_flows` 에 `sds_map` 파라미터 부재. 그런데 `generate_sits` 는 `sds_docx_path` 를 **이미 받고 있었다** — 배선만 없었다 |
| S2 | 읽는 필드가 스키마에 **없었다** | 맵 값 스키마 = `{kind, description, related, asil, component_description, canonical}`. 코드는 `entry.get("swcom") or entry.get("component")` → 항상 `None`. 실측 **763항목 중 보유 0개** |
| — | 안 보였다 | 전체가 `except Exception: pass` 안 |

즉 이 보강은 **한 번도 산출한 적이 없다.** 5.1MB 남의 프로젝트 문서를 파싱하고 결과는 0,
표면에는 아무것도 안 나온다. 같은 맵을 쓰는 `sts.py::_lookup_sds_related_ids` 는 **실재
필드 `related`** 를 읽는다 — 세 생성기가 같은 맵을 서로 다르게 읽고 있었다.

### 수정

1. `collect_integration_flows(..., sds_map=None)` 추가 — `sts`/`suts` 와 파라미터 동등
2. `generate_sits` 가 받은 `sds_docx_path` 를 흐름 수집까지 **배선**.
   맵 확보는 **SUTS 가 이미 고쳐 둔 `_resolve_sds_map` 을 재사용**한다
   (복제하면 한쪽만 고쳐진다 — 이 저장소의 반복 실패 모드)
3. `except Exception: pass` 제거 — 조회 실패는 함수명과 함께 경고
4. `stats_out` 에 `sds_source`/`sds_map_entries`/`sds_lookups`/`sds_key_hits`/
   `sds_swcom_hits` 보고. 조회했는데 산출 0 이면 **경고**한다

### 이 라운드에서 **하지 않은** 것

**대체 필드를 추측하지 않았다.** 틀린 SwCom 을 추적성 열에 넣는 건 0건보다 나쁘다.
스키마에 필드가 생기면 테스트가 실패해 알려 준다(`TestMeasuredSchemaGap`).

### 검증

- 새 테스트 11건(`tests/unit/test_sits_sds_related_source.py`) — **뮤테이션 6/6**
- 실측 확인: 폴백은 `lookups=1, key_hits=0, swcom_hits=0` + 경고,
  호출자 SDS 를 주면 `swcom_hits=1` 이며 `SwCom_07` 이 `related_ids` 에 실제로 들어간다

---

## 5-11. 자체 감사 — "보고를 추가한 것" vs "보고가 도달한 것" — ✅ 완료 (2026-07-31)

앞선 라운드들이 침묵을 없앤다며 `stats_out`/sidecar 를 여러 개 늘렸다.
**그 수치가 사람이 보는 표면까지 실제로 도달하는지** 를 사후 감사했더니 두 곳이 끊겨
있었다 — 고치려던 결함군과 같은 모양이다.

| # | 격차 | 실측 |
|---|---|---|
| R1 | SITS `sds_*` 키가 품질 리포트에 안 실림 | `generate_sits_quality_report` 가 `flow_stats` 에서 **이름 지정한 8개 키만** 골라 담는다. 새 키는 전부 버려져 **로그에만** 남았다(품질 리포트는 API 로 나가지만 로그는 안 나간다) |
| R2 | UDS 충실도가 API 응답에 없음 | sidecar 와 `<out>.docx.stage.json` 에 기록되는데 **checkpoint 를 읽는 코드가 저장소 전체에 0개**(write-only). 다른 `*_path` 리포트들과 달리 결과 dict 에 없었다 |

**수정**: SITS 품질 리포트에 `sds_related_enrichment`(조건 없이 — 0 이야말로 실어야 할 값),
UDS 결과 dict 에 `gen_stats_path` + `gen_stats_summary`(sidecar 부재는 `None`=미측정).

### 곁가지 — 테스트 스위트의 vacuous truth 사냥 (유효한 **음성** 결과)

프로덕션의 `all([])` 를 고쳤으니 **검증 계층**도 같은지 봤다. 정적 탐지는 오탐이 많아
**테스트 자체에 뮤테이션**을 걸었다(`assert all(X for…)` → `all(False for…)`,
`assert not any(X…)` → `not any(True…)`, 루프 첫 줄에 `assert False`).

- 대상 136건 중 **118건이 뮤테이션에 걸려 실패** = 단언이 실제로 하중을 받고 있다
- 생존 18건은 전부 **"빈 것이 곧 단언 대상"** 인 정당한 케이스(개별 확인)
- **for 루프 46건 전부 실제로 순회** — vacuous 0건

→ 결함이 아니므로 만들지 않았다. 스위트의 vacuous 노출은 사실상 없다.

---

## 5-12. Gemini SDK 를 즉시 로드하던 것 — 기동·테스트가 46초를 헛되이 지불 — ✅ 완료 (2026-07-31)

위 감사 중 테스트 하나가 유난히 느려 파고들다 발견했다.

### 실측

| 대상 | 비용(3회 재현, warm cache) |
|---|---|
| `google.genai` | **≈ 36초** |
| `google.generativeai` (**수명 종료 패키지**) | **≈ 10초** |
| `backend.helpers.uds` import 전체 | **52.7초** → **15.5초** |

`workflow/ai.py` 가 두 SDK 를 **모듈 레벨**에서 즉시 import 했다. 그래서
**백엔드 기동**·**모든 pytest 워커**·`workflow.ai` 를 스치는 모든 스크립트가 LLM 을
한 번도 호출하지 않아도 46초를 냈다. `google.generativeai` 는 *"All support … has
ended"* 를 매 실행 찍는 EOL 패키지이고 실사용처는 legacy fallback 한 곳뿐이다.

같은 저장소의 `workflow/llm_adapters.py:111` 은 **이미 함수 안에서 지연 import** 한다 —
여기만 즉시 로드였다(패턴 불일치).

### 수정

- `_load_gemini_sdks()` + `_sdk(name)` 지연 로더(스레드 락, 1회 로드).
  로드 실패는 `_sdk_errors` 에 **사유를 남긴다**(조용한 `None` 금지)
- 외부 계약 유지: `workflow/pipeline.py:2246` 이 `getattr(ai, "genai_new", None)` 로
  가용성을 묻는다 → **PEP 562 모듈 `__getattr__`** 로 이름 4개를 그대로 유지
- ⚠ 모듈 `__getattr__` 은 **모듈 밖** 접근에만 불린다. 내부 전역 조회에는 안 걸리므로
  내부 참조 9블록을 전부 `_sdk("…")` 로 바꿨다(안 바꾸면 `NameError`)

### 검증

- 실제 LLM 호출로 확인: 응답 `서울`, `sdk=google-genai`, `finish_reason=STOP`, `truncated=False`
- `import backend.helpers.uds` 후 `google.genai`/`google.generativeai` 가
  `sys.modules` 에 **없음**(별도 프로세스)
- 새 테스트 14건(`test_ai_lazy_sdk.py`) + 14건(`test_report_reachability.py`) — **뮤테이션 8/8**
- ⚠ 테스트가 스스로 40.77초를 쓰고 있었다(계약 검증이 실제 로드를 유발). 캐시 스텁으로
  교체 — **이 라운드가 없애려는 비용을 테스트가 도로 지불하면 안 된다**
- ⚠ `test_report_reachability` 초안이 253초였다: `Path("backend").rglob("*")` 가
  **`backend/.venv` 까지 훑었다**(실측 70,189 엔트리/21.5초). `os.walk` 가지치기로 교정

---

## 5-13. 신뢰도 리포트가 자기 산출물을 되읽어 출처를 만들어냈다 — ✅ 완료 (2026-07-31)

`generate_asil_related_confidence_report` 는 `generated_docx_path` — **이 파이프라인이
방금 쓴 UDS DOCX** — 를 되읽어 payload 의 빈 필드를 채운다. 값을 채우는 것 자체는 유용하다.
문제는 **출처 라벨**이었다. 값이 어디서 왔는지가 아니라 **문자열 모양**만 보고 배정했다:

    asil 이 placeholder 가 아니다     → `sds`        (0.95)
    related 가 `SwFn_\d+` 모양이다     → `srs`        (0.95)
    related 가 `SwCom_\d+` 모양이다    → `rule`       (0.75)
    그 외                             → `reference`  (0.90)

`SwFn_07` 이라는 **문자열 모양**은 "SRS 를 참조했다" 는 증거가 아니다.

### 실측 — 대조군을 나란히 놓으면 결정적이다

같은 payload(진짜 유래 `default`/`inference`)에 **생성 DOCX 만 물렸을 때**:

| 항목 | DOCX 미지정(대조군) | DOCX 되읽음 | 수정 후 |
|---|---|---|---|
| ASIL 출처 | 기본값(근거 없음) | **SDS** | 생성 문서 회수 |
| Related 출처 | 추론 | **SRS** | 생성 문서 회수 |
| 점수 / 등급 | 0.500 / D | **0.933 / B** | 0.300 / D |
| 저신뢰 목록 | 1건 노출 | **none** | 1건 노출 |
| "정본 문서 근거" | 0/1 (0%) | **1/1 (100%)** | 0/1 (0%) |
| 증거 문장 | (없음) | **"SDS 매핑 규칙에 의해 보강됨"** | "원 유래 미확인" |

마지막 세 줄이 특히 나쁘다. 이 리포트의 **용도 자체가** "어느 필드가 근거가 약한가" 인데,
세탁된 행은 **조치 대상 목록에서 사라지고** 없는 증거 문장까지 붙는다.

### 수정

- 생성 문서에서 회수한 값은 전부 새 어휘 **`generated_doc`**(0.30, "생성 문서 회수(원 유래 불명)").
  `unknown` 과 점수는 같지만 원인이 달라 라벨을 분리했다 — 이건 어휘 드리프트가 아니라
  **payload 결손의 신호**라 조치 방향이 다르다
- 모양 기반 분류(`re.search` → `srs`/`rule`/`reference`) 제거. AST 계약 테스트로 재발 차단
- **값을 실제로 가져오지 않았으면 출처도 안 바꾼다** — 예전엔 서술을 그대로 두고
  `description_source` 만 `reference` 로 올렸다(값 변경 없는 순수 등급 상승)
- `generated_doc` 은 `op_counts` 의 정본 집합(`{sds, srs, reference}`)에 없어 자동 제외된다

### 검증

- 새 테스트 21건(`test_confidence_provenance_laundering.py`) — **뮤테이션 9/9 잡힘**
- 음성 대조군: payload 의 정당한 `sds` 출처는 보존(기존 `test_report_gen_cross` 단언 무손상)
- 관련 6개 파일 233 passed

### 확정하지 못한 것 (과대 주장 금지)

디스크의 실 산출물 5건 중 4건은 **함수 0건**(공허), 1건(432함수)은 `ASIL Source SDS 100%` +
`Related SRS/레퍼런스/룰`(= 세탁 코드가 배정하던 3라벨)로 **정황이 일치**한다. 다만
`related_source="rule"` 은 `docx_builder.py:3042`·`helpers/uds.py:418` 도 생산하므로
**그 리포트가 세탁 경로를 탔다고 단정할 수 없다**. 코드 결함은 프로브로 증명됐고,
과거 산출물 귀속은 미확정으로 남긴다.

### 곁가지 — 복제 여부 확인 (결함 아님)

같은 파일의 다른 DOCX 되읽기 4곳(`:389`, `:685`, `:921`, `:1100`)은 출처를 배정하지 않는다.
`docx_builder.py:3039-3047` 은 모양이 비슷하나 **외부 레퍼런스 SUDS** 유래라 `reference` 가
정확하고 `main` 의 `rule` 도 실제 룰이다 — 복제 아님. 세탁은 이 함수 두 분기에 국한됐다.

### 후속 — 내가 같은 함정에 빠졌다 (X3 자기검출)

`generated_doc` 을 `validation.py` 의 라벨·점수표에만 넣고 **`provenance.py::WEAK_SOURCES`
에는 빠뜨렸다.** 그래서 0.30 짜리 최약체가 `is_weak_source()` 에서는 **강한 출처**로
분류됐다 — 더 나은 근거가 와도 덮이지 않는다. 이 함수는 payload 를 **제자리 변경**하므로
그 값이 하류로 샌다.

`provenance.py` 의 docstring 이 바로 이 경우를 경고하고 있었다("새 라벨을 추가하면 양쪽을
같이 갱신할 것"). 문자열을 하나 더 넣는 대신 **두 표를 구조로 묶었다**:

- `WEAK_SCORE_MAX = 0.75` (경계: `rule` 까지 약함 / `call_graph` 부터 강함)
- 계약 테스트 3건 — 점수 ≤ 경계인데 강하다고 판정되면 실패, 점수 > 경계인데 약하다고
  판정돼도 실패, `WEAK_SOURCES` 에만 있고 점수가 없어도 실패(`.get(…, 0.6)` 로 조용히
  접히는 걸 막는다). **뮤테이션 3/3**

### 남긴 후보

- `_score_for` 는 **값이 비어 있어도** 출처 점수를 매긴다(빈 ASIL + `asil_source="sds"` → 0.95).
  대조군이 0.500 을 받은 것도 이 때문이다. 빈 값의 출처를 점수에 넣는 게 옳은지는 별건.
- `_run_report_with_timeout`(`backend/helpers/common.py:389`)은 `max_workers=1` 이라 리포트가
  순차 실행되지만, **timeout 시 `cancel_futures=True` 는 이미 실행 중인 future 를 안 죽인다**.
  그 스레드가 `uds_payload` 를 계속 제자리 변경하는 동안 다음 리포트가 같은 payload 를
  쓴다. 이 라운드에서 만든 결함은 아니고(제자리 변경은 원래부터), 고치려면 리포트 계층의
  변경 규약을 바꿔야 해 별건으로 남긴다.

---

## 6. 다음 라운드 후보

| # | 대상 | 이유 |
|---|---|---|
| ~~1~~ | ~~pre-commit 900s 예산 (P1)~~ | ✅ 완료 — 위 P1 참조 |
| ~~2~~ | ~~`report_gen/` DOCX 라이터 대조 (P2)~~ | ✅ 완료 — 아래 별도 절 |
| ~~3~~ | ~~`impact_orchestrator.py:135` (P0 잔여)~~ | ✅ 완료 — 위 P0 참조 |
| ~~4~~ | ~~LLM redaction + 모델 echo 대조~~ | ✅ 완료 — §5-1 L4/L6 |
| ~~5~~ | ~~3개 egress 경로 통합~~ | ✅ 완료 — §5-5. 키 해석 단일화(근본 원인)·재시도·입력 상한·폴백 사유. **잔여: 토큰 예산·stage cap 공유**(임베딩은 단발 호출이라 예산 개념이 llm_call 과 다름 — 별건) |
| ~~6~~ | ~~`stats_out` 을 UI 까지 배선~~ | ✅ 완료 — §5-5 #1 (`retrieval_notes` 신규 응답 키 + 프론트 경고 배너) |
| ~~7~~ | ~~실 KB 재인덱싱~~ | ✅ 완료 — §5-5 #2 + **§5-7 에서 실제 실행**(63/63, 시맨틱 0→63). 돌려 보니 백엔드가 죽어 있었고(모델 404) 가드가 그걸 잡았다 |
| ~~D1~~ | ~~provenance 가 "미기록" 을 `inference` 로 확정~~ | ✅ 완료 — §5-9. 값을 보고 `default`/`inference`/`unknown` 을 가르고, 판정 복제 6곳을 `report_gen/provenance.py` 단일 출처로 전환. **점수 이동은 의도한 것**(0.60 은 부풀린 값이었다) |
| ~~D2~~ | ~~저장소 고정 HDPDM01 SUDS 로 함수 정보 채움~~ | ✅ 완료 — §5-8. 신원 게이트 + 안전축/서술축 분리 + ASIL 어휘 검사 + 하드코딩 폴백 제거. **성능(생성 31.9초 중 24.3초)은 미해결** — 신원 불일치여도 문서는 여전히 읽는다(서술축 때문). 신원 판정을 읽기 **전에** 하고 불일치면 아예 안 읽는 최적화는 별건 |
| 🔴 D3 | 약한 출처(`default`/`inference`)가 강한 근거(참조 SUDS)를 선점 | §5-8 참조. `asil` 은 병합 전 `QM` 으로, `description` 은 합성문으로 칸이 차 자기 프로젝트 SUDS 의 ASIL 416건이 영영 안 들어간다. `_weak_sources` 어휘가 이미 있으므로 자격 조건을 바꾸면 되나 **HDPDM01 수치가 이동** → 정책 결정 |
| 8 | UTCV-001 잔여 | `applicable` 정책축·커버리지 예외 disposition. 이 저장소에 해당 축이 **존재하지 않아** 신규 기능 개발이다(결함 수정 아님) — 사용자 판단 필요 |
| 9 | 템플릿↔소스 프로젝트 불일치 | 소스 900함수 중 271개만 HDPDM01 템플릿에 존재(629건=69.9% 부재). 의도된 부분집합인지 오배치인지는 프로젝트 설정 판단이 필요해 `ok` verdict 는 뒤집지 않고 수치만 노출해 둔 상태 |
| 10 | `workflow/ai_validator.py` | dead code(호출자 0). 살릴지 지울지는 정책 결정 — 사용자 몫으로 남김 |
| 11 | 빈 값에도 출처 점수가 매겨진다 | §5-13 참조. `_score_for` 는 값 유무를 안 본다 — 빈 ASIL + `asil_source="sds"` 가 0.95 를 받는다. "출처는 있는데 값이 없다" 는 상태를 점수에 어떻게 반영할지는 정책 판단 |

---

## 7. 작업 규약 (이 저장소 고유)

- 고치기 **전에 실측**한다. 계획서·docstring·주석의 수치를 사실로 받지 않는다
  (실제로 `parse_hsis_signals` docstring 의 "SwVar=20/Related=21" 은 재현되지 않았다 — 19/20 이 맞다).
- 새 테스트는 **뮤테이션으로 검증**한다. 옛 동작을 되살렸을 때 실패하지 않는 테스트는 무의미하다.
- 같은 판정을 두 곳에 복제하지 않는다. 이 저장소는 그래서 "한쪽만 고쳐지고 다른 쪽 잠복" 을
  반복해 겪었다(`_is_hsis_data_row`, `_ratchet_core`, `_artifact_check` 단일화).
- 미측정을 통과로 바꾸지 않는다. 키가 없으면 **"대조 불가"** 이지 PASS 가 아니다.
- 정책 결정(임계값·기본값·게이트화)은 **노출까지만** 하고 값 결정은 사용자에게 남긴다.
