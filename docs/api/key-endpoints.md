# Key API Endpoints

> CLAUDE.md on-demand 레퍼런스 — endpoint 작업 시 참조.

- `POST /api/jenkins/uds/generate-async` — UDS 생성
- `POST /api/jenkins/sts/generate-async` — STS 생성
- `POST /api/jenkins/suts/generate-async` — SUTS 생성
- `POST /api/local/sits/generate-async` — SITS 생성
- `POST /api/jenkins/impact/trigger-async` — Impact 분석
- `GET /api/jenkins/progress` — 진행률 조회
- **`POST /api/jenkins/uds/traceability-matrix`** — 추적성 매트릭스(V-model 6단계: SRS→SDS→UDS→STS→SUTS→SITS/VectorCAST) 생성. 프론트가 5개 추출 엔드포인트로 모은 7배열을 echo back → P&F 함수명 bridge. '추적성 분석' 섹션(구 'SRS/SDS 매핑', 2026-06 rename)
- **`POST /api/jenkins/call-tree`** — 함수 호출 트리. body `{job_url, cache_root, build_selector, source_root?, entry(콤마 구분), max_depth, include_external, engine}`. `engine='precise'`(tree-sitter `parse_c_project`, 기본)는 호출엣지+콜백+ASIL 메타 추출, 미가용 시 `regex` 자동 폴백. 응답 `{trees[], missing[], stats{engine,functions,edges,files_scanned}}`. cached build root 필수
- **`POST /api/jenkins/call-tree/save`** — 콜트리를 html/csv/json으로 저장 (`output_format`)
- **`POST /api/jenkins/call-tree/preview-html`** — 보유 call_tree dict → HTML 렌더 (`CallTreePreviewRequest`)
- **`GET /api/jenkins/call-tree/download`** — 저장 콜트리 파일 다운로드 (`safe_resolve_under` 경로검증)
- **`POST /api/swut/coverage/build`** — SwUT Coverage Report v3.01 xlsx 빌드 (16~17차)
- **`POST /api/swut/sutr/build`** — SUTR v3.01 xlsm 빌드 (keep_vba=True, 17차 대칭)
- **`POST /api/swut/consistency/check`** — Coverage↔SUTR cross-validation (18차)
- **`POST /api/swit/coverage/build`** — SwIT Coverage Report v2.02 xlsx 빌드 (33차)
- **`POST /api/swit/sitr/build`** — SwIT SITR v2.02 xlsm 빌드 (keep_vba=True, 34차 대칭)
- **`POST /api/swit/consistency/check`** — SwIT Coverage↔SITR cross-validation (35차)
- **`POST /api/swut/doc/summary`** — 단일 산출물(SwUTCV Coverage .xlsx / SUTR .xlsm) 직접 파싱. body `{path, kind:'coverage'|'report'}`, 응답 `{coverage_summary|sutr_summary, parse_warnings}`(ok/issues 키 없음 — 정합성 비교 아님). admin only, read-only(Semaphore 미적용)
- **`POST /api/swit/doc/summary`** — 단일 산출물(SwITCV Coverage / SITR) 직접 파싱 (위 SwUT 대칭, kind='report'→SITR 결과)
- **`POST /api/swut/log-folder/preview`** — SwUT log_folder dry-run preview (38차)
- **`POST /api/swit/log-folder/preview`** — SwIT log_folder dry-run preview (38차)
- **`POST /api/file-mode/add-allowed-prefix`** — Cloudium allowed_prefixes 동적 추가 (39차, admin only 40차)
- **`POST /api/file-mode/remove-allowed-prefix`** — 동적 제거 (39차, admin only 40차)
- **`GET /api/file-mode/extra-prefixes`** — 영구 저장 prefixes 조회 (39차, admin only 40차)
- **`POST /api/auth/login`** — JWT 로그인 (45차, 공개) → access(60분)/refresh(7일) 발급
- **`POST /api/auth/refresh`** — access 재발급 (45차, 공개)
- **`POST /api/auth/change-password`** — PW 변경 (45차, 인증) → 새 access/refresh + tv 증가 (47차)
- **`POST /api/auth/logout`** — 로그아웃 (45차, 인증) → `increment_token_version` 즉시 무효화 (47차)
- **`GET /api/auth/me`** — 현재 사용자 + is_admin + must_change_password (40/45차, 공개·best-effort)
- **`GET /api/auth/admins`** — admin list 조회 (40차 신규, admin only)

## 프로젝트 요약 탭 (`backend/routers/summary_insight.py`)

응답 규약 공통: 계산 불가는 `available:false` + `reason`(부분 결과·침묵 0 금지), 수치에는 항상 출처 라벨.

- **`POST /api/summary/quality-detail`** — 함수(subprogram)단위 커버리지 + 실패 TC. 소스 우선순위 `vectorcast_detail` → `vectorcast.ut/it_metrics` → **`scm_vcast_job`**(SCM 연결문서 로드 이력, N1). 응답 `coverage_source`/`coverage_source_detail`로 출처·로드 시각 표기. IT 축은 소스마다 달라(빌드=진입/호출, SCM=구문/분기/호출) `metrics_present`로 보유 축만 집계
- **`POST /api/summary/baseline-diff`** — 베이스라인↔대상 소스 스냅샷 직접 비교(change-log 비의존). `files.changed_detail[]`이 **파일→변경 함수 트리**이며 각 함수에 커버리지·ASIL 조인(N3). `functions.gap_summary`가 '변경 함수 중 미커버' 최상위 신호. 캐시 키 = 양쪽 스냅샷 지문 + 커버리지/ASIL 조인 규모. **지문에 `content_sha` 포함**(stat 2개만으로는 서로 다른 스냅샷이 충돌 — 실측 4개 빌드가 같은 `{370, 9305884}`였다). `files.identical_snapshot`은 '변경 없음'이 아니라 **비교 불성립**(백필이 여러 빌드에 같은 SVN HEAD를 넣으면 발생 — 그대로 두면 ASIL 함수 변경이 22건→1건으로 과소보고된다). 기본 baseline은 target과 내용이 다른 가장 오래된 스냅샷(`baseline_auto_reason`), 한계는 `checkout_lag_days`·`snapshot_groups`로 노출
- **`POST /api/summary/change-matrix`** · **`/change-matrix/cell`** — 빌드별 변경 영향(베이스라인 고정 → 각 빌드 누적, **change-log 비의존**). 구 타임라인은 영향분석 잡 실행 이력을 읽어 잡을 돌린 적 없는 빌드가 전부 `—`였다(실측 89행 중 88행이 빌드번호 없는 "#—"). 행 축은 `has_source` 캐시 빌드. **content_sha가 같은 빌드는 셀 하나를 공유**하고(실측 13빌드 → 고유 트리 4개, 12쌍 → 3쌍), 베이스라인과 바이트 동일한 빌드는 **파싱 없이** 함수 0을 확정한다. `level:"files"`는 manifest dict 비교로 즉시 응답하고 `level:"functions"`는 캐시된 셀만 채운 뒤 `pending_cells`를 남긴다 — 실제 계산은 `/cell`(probe/force, 경로별 락) 전용. 함수 미계산은 `null`+`function_state.reason`(0 위장 금지), ASIL은 함수 축이 있을 때만. ⚠ 셀 캐시는 `summary_change_cell_*`(≠`summary_baseline_diff_*` — 후자 글롭은 `_changed_functions_from_cache`가 test-design 변경 축으로 읽는다)
- **`POST /api/summary/rule-window-changes`** — 구간 변경 파일 목록(결정론, LLM 0회). 파일 귀속이 없는 규칙(RCMA류 cross-module)은 파일 diff를 만들 수 없지만 **위반이 변한 구간에 바뀐 소스 파일은 실재**한다. `decl_touched`(비-static 최상위 선언 변경 라인 수)는 **정렬 키 전용 휴리스틱** — 0이어도 후보에서 빼지 않는다. `attribution:"observational"` + 고정 note로 관측≠인과 명시
- **`POST /api/summary/test-design`** — 테스트 설계 어드바이저(결정론, LLM 0회). UT/IT 행(`metric_set`), ASIL은 주석+요구 역전파 병합, 변경 축(`changed_axis` — 캐시된 baseline-diff 기반), ccn 기반 최소 TC 추정(`suggested_min_cases_estimate:true`), 기법 카탈로그 15종(ISO 26262-6 Table 8/9/11/12 참조). ⚠ IT 갭은 별도 축(`it_*`) — 통합 미실행 ≠ 단위 시험 부재
- **`POST /api/summary/test-case-draft`** — 함수 1개 시험 케이스 초안(Gemini on-demand + 디스크 캐시, N4). 결정론 골격(권고 기법·최소 TC·경계값 후보)은 LLM 없이도 항상 산출. 환각 필터는 **케이스 단위**(본문·파라미터·전역·호출 밖 식별자 과반이면 그 케이스만 폐기). `probe`/`force` 지원
- **`POST /api/summary/architecture-metrics`** — 소스 아키텍처 결정론 메트릭 **v7**(v7 = `playbook_inputs` 신설 + `indirect_calls` resolved 분리, 아래 arch-improvement 항 참조). fan/핫스팟/결합/SCC + `asil_interference`(간섭 자유 검토 후보) · `global_coupling`(전역 공유 + 사용 함수 샘플, read/write 미구분 고지) · `coverage_complexity`(사분면, 미조인 수 표면화) · `indirect_calls`/`encapsulation`(콜그래프 완전성) · **`file_graph`**(파일 드릴다운 + `topo_order` = DSM 정렬) · **`layer_graph`**(APP/BSW/LIB/BOOT + 역방향 호출). ⚠ 계층은 함수명 휴리스틱이라 역방향은 '위반'이 아니라 **검토 후보**
- **`POST /api/summary/arch-improvement`** — 아키텍처 개선(To-Be) 제안. 결정론 후보 6종(순환 끊기·계층 정돈·집중 파일 분할 + 테스트 용이성 3종: 순수 함수 추출·전역 주입·시임 명시)은 LLM 없이 항상 산출, AI 목표 구조는 **후보가 있을 때만** 호출(근거 없는 그림 금지). 절단 시 종류별 최소 1건 보장 + `summary.omitted` 표기
  - **상세 플레이북** (후보의 `detail` · 집계 `playbook`, `workflow/arch_playbook.py`): 후보가 "무엇을"까지만 말하면 실행이 안 된다("파일을 분할한다" — 134개 함수를 어느 선으로?). `arch.playbook_inputs`(v7 신설)의 실측 재료로 **단계·Before/After C 스케치·시험 스텁 계획·영향 범위**를 붙인다. ①순환은 그 간선을 만드는 **실제 함수 호출 쌍**, ②분할은 **파일 내부 콜 연결성분 / 이름 접두사 중 실용적인 축**과 군집별 함수 목록, ③시임은 **실제 함수포인터 심볼**. ⚠ 코드는 스케치다 — 파서가 시그니처를 안 주므로 타입 자리는 주석이고 `sketch.note`로 상시 고지(지어내면 컴파일 안 되는 코드를 배포하게 된다). ⚠ **분할 축이 없으면 군집을 만들지 않는다** — 실측 god_file 8개 중 6개가 최대 덩어리 91~97%로 분할선이 없었고, 그때는 "없음 + 왜"를 반환한다. ⚠ Generated_Code 경로는 리팩터링이 아니라 **래핑 대상**으로 안내(생성기가 덮어쓴다). 재료가 없으면 `detail` 키 자체를 생략하고 `playbook.without_detail`로 센다. 캐시 hit 시에도 결정론 코어는 **매번 재계산**해 덮는다(캐시 키는 kind/target/basis뿐이라 플레이북 개정이 반영 안 됨)
  - ⚠ **`indirect_calls` 정직화(v7)**: 파서의 `func_refs`는 MCU 레지스터·변수 참조를 대량 포함한다 — 실측 KJPDS02_PV 2,708건 중 **실제 함수는 2건(0.1%)**. 이 원시 수치로 시임 후보를 뽑던 탓에 `PE_Initialize_GPIO_Part1`(참조 27 = `DDRADL`·`DDRJ`…)이 1순위 스텁 후보였다. v7부터 `resolved_ref_*`(known 함수 교집합) / `seam_functions`를 따로 싣고 `top`은 **실제 심볼 보유 함수만**(692 → 7). 디스패치 테이블(`s_uds_wdbi_did_tbl[i].pf_Handler`)이 단일 포인터보다 시험 이득이 커 먼저 온다. 원시 필드는 하위호환으로 남지만 '함수포인터 보유'로 읽으면 안 된다
- **`POST /api/summary/coding-rulebook`** — 정적분석 위반 → 팀 코딩 룰북 초안. 상위 규칙(기본 8·상한 15)을 배치 처리해 카테고리(필수/요구/권고/프로젝트 관례)로 묶고 `markdown` 필드를 **서버에서 조립**. ⚠ 코드 증거 0건 규칙은 수록하지 않고 `excluded`에 사유를 남긴다(일반론 룰 차단). `probe`는 대상 규칙·증거 수만 반환(LLM 0회)
- **`POST /api/summary/ai-insight`** — AI 인사이트(Gemini, 5섹션: rules/mistakes/roles/architecture/testing). `probe`=캐시만 조회, `force`=재생성. 캐시 히트 판정 = prompt_version + RCR stat 지문 + 모델
- **`POST /api/jenkins/prqa-delta`** · **`prqa-rule-trend`** · **`POST /api/summary/rule-fix-example`** · **`rule-unresolved-evidence`** · **`rule-definition`** — 규칙 워크벤치(빌드간 위반 delta·트렌드 분류·fix 증거·팀 룰 초안). 파일 증거는 관측 구간 전체가 아니라 **변화가 실제 일어난 인접 구간**(`decrease_window`/`increase_window`, 파일 단위 변화량 최대)에서 뽑고, 규칙이 RCFInfo에 없거나 비활성인 빌드의 카운트는 **null**(규칙셋 확장을 '신규 발생'으로 오분류 금지 — `applied_from_build`/`ruleset_sizes`로 가시화). RCMA류 pseudo 엔트리는 `scope='cross_module'`이라 스냅샷 조회 대상이 아니다(`reason: cross_module_scope` / 룰 초안은 `cross_module_only`).
  - **함수 단위 귀속** (`rule-unresolved-evidence` 응답의 `attribution` · `file_rule_deltas`): RCR은 **파일×규칙 카운트가 최상세**라 규칙의 함수·줄 귀속이 원리적으로 없다. 그러나 같은 빌드 산출물의 **HMR(HIS Metrics Report)** 은 함수 단위라, 구간에 **새로 생긴 함수 / 메트릭이 변한 함수**는 실측으로 답할 수 있다(`backend/services/his_metric_delta.py`, 캐시 `his_metrics_cache.json`). 밴드 판정은 `swsa_st201_binner.ST201_METRICS`(회사 양식 SSOT) 재사용 — **밴드가 정의된 4종**(v(G)·LEVEL·CALLING·CALLS)만 Pass/Conditional/Fail을 붙이고 나머지(PATH·STMT·PARAM·RETURN·GOTO)는 **verdict null**(기준 없음을 통과로 접지 않는다). 값 변화와 **밴드 교차**(`band_crossings`)는 별도 필드다. ⚠ 함수 목록은 '이 함수가 그 규칙을 위반했다'가 아니라 '이 구간에 바뀐 함수'이며, 서버가 `attribution.note`로 그 경계를 상시 반환한다. HMR 부재·동명 파일 다중 경로는 빈 목록이 아니라 `available:false` + `no_hmr`/`file_ambiguous_in_hmr`
- **`POST /api/jenkins/cached-builds-meta`** · **`sync-backfill`** · **`GET /api/jenkins/sync-backfill-status/{job_id}`** — 캐시 빌드 표면 확대(오프라인 메타 + 과거 빌드 백필). `cached-builds-meta`는 `source_pinned`/`source_revision_source`로 **스냅샷 신뢰도**를 노출한다. `sync-backfill`은 `pin_source`(revision 고정 체크아웃) · `warm_matrix`(sync 후 change-matrix 셀 선계산, `phase="matrix"`) · `baseline_build`를 받고, 한 번에 못 고치고 남는 수를 `remaining_unpinned`로 알린다. **revision 해석은 ① `jenkins_console.log`의 `At revision N` 직독**(`build_revision.py` — 빌드가 실제로 받은 값이고 네트워크 0, 로그 선두만 읽음) **→ ② `svn info -r {빌드시각}`** 순이다. 실측 KJPDS02_PV 14빌드에서 두 경로 **완전 일치**(불일치 0), 콘솔이 상한 2MB에 걸려 선두가 잘린 빌드만 ②로 넘어간다. ⚠ `pin_source=true`면 **이미 캐시된 빌드도 미고정이면 재수집**한다 — 아니면 HEAD로 받아둔 잘못된 트리가 영원히 남아 토글이 무력화된다. ⚠ 재수집은 **비파괴**(`source.repin` 스테이징 → 성공 시에만 교체) — 선삭제하면 체크아웃 실패한 빌드가 소스를 잃고 표에서 행째 사라진다. 고정 실패는 HEAD 폴백 + `per_build[].status="pin_failed"`로 정직 보고
- **`POST /api/summary/change-matrix`** · **`/change-matrix/cell`** — 베이스라인 대비 각 빌드의 누적 소스 변화(행 = 캐시 빌드, 영향분석 실행 이력 비의존). `level="files"`는 manifest 비교만으로 즉시 응답, `level="functions"`는 캐시된 셀만 probe하고 나머지를 `pending_cells`(content_sha dedup)로 남긴다 — 실제 계산은 `/cell` 전용. 응답의 `snapshot_trust`는 미고정 스냅샷 수를 노출한다(**'변화 0'이 코드 미변경이 아니라 HEAD 체크아웃 결과일 수 있음**을 감추지 않기 위해). 행마다 `comparison_basis`(`trusted`/`mixed`/`both_unpinned`) — 베이스라인과 고정 상태가 다르면 diff는 산술적으로 맞아도 **의미가 틀리므로**(실제로는 "과거 rev → 오늘"인데 "그 빌드의 변화"로 붙는다) 프론트가 ⚠로 라벨한다. 재수집을 나눠 실행하면 반드시 겪는 상태다. `row_limit`은 표시/전체/누락 빌드를 명시하고 **베이스라인 행은 상한과 무관하게 항상 포함**한다(구 상한 30 + 캐시 33빌드에서 자동 선택된 베이스라인 #77이 침묵 절단된 전례)
