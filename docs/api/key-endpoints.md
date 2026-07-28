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
- **`POST /api/summary/architecture-metrics`** — 소스 아키텍처 결정론 메트릭 **v6**. fan/핫스팟/결합/SCC + `asil_interference`(간섭 자유 검토 후보) · `global_coupling`(전역 공유 + 사용 함수 샘플, read/write 미구분 고지) · `coverage_complexity`(사분면, 미조인 수 표면화) · `indirect_calls`/`encapsulation`(콜그래프 완전성) · **`file_graph`**(파일 드릴다운 + `topo_order` = DSM 정렬) · **`layer_graph`**(APP/BSW/LIB/BOOT + 역방향 호출). ⚠ 계층은 함수명 휴리스틱이라 역방향은 '위반'이 아니라 **검토 후보**
- **`POST /api/summary/arch-improvement`** — 아키텍처 개선(To-Be) 제안. 결정론 후보 6종(순환 끊기·계층 정돈·집중 파일 분할 + 테스트 용이성 3종: 순수 함수 추출·전역 주입·시임 명시)은 LLM 없이 항상 산출, AI 목표 구조는 **후보가 있을 때만** 호출(근거 없는 그림 금지). 절단 시 종류별 최소 1건 보장 + `summary.omitted` 표기
- **`POST /api/summary/coding-rulebook`** — 정적분석 위반 → 팀 코딩 룰북 초안. 상위 규칙(기본 8·상한 15)을 배치 처리해 카테고리(필수/요구/권고/프로젝트 관례)로 묶고 `markdown` 필드를 **서버에서 조립**. ⚠ 코드 증거 0건 규칙은 수록하지 않고 `excluded`에 사유를 남긴다(일반론 룰 차단). `probe`는 대상 규칙·증거 수만 반환(LLM 0회)
- **`POST /api/summary/ai-insight`** — AI 인사이트(Gemini, 5섹션: rules/mistakes/roles/architecture/testing). `probe`=캐시만 조회, `force`=재생성. 캐시 히트 판정 = prompt_version + RCR stat 지문 + 모델
- **`POST /api/jenkins/prqa-delta`** · **`prqa-rule-trend`** · **`POST /api/summary/rule-fix-example`** · **`rule-unresolved-evidence`** · **`rule-definition`** — 규칙 워크벤치(빌드간 위반 delta·트렌드 분류·fix 증거·팀 룰 초안). 파일 증거는 관측 구간 전체가 아니라 **변화가 실제 일어난 인접 구간**(`decrease_window`/`increase_window`, 파일 단위 변화량 최대)에서 뽑고, 규칙이 RCFInfo에 없거나 비활성인 빌드의 카운트는 **null**(규칙셋 확장을 '신규 발생'으로 오분류 금지 — `applied_from_build`/`ruleset_sizes`로 가시화). RCMA류 pseudo 엔트리는 `scope='cross_module'`이라 스냅샷 조회 대상이 아니다(`reason: cross_module_scope` / 룰 초안은 `cross_module_only`)
- **`POST /api/jenkins/cached-builds-meta`** · **`sync-backfill`** · **`GET /api/jenkins/sync-backfill-status/{job_id}`** — 캐시 빌드 표면 확대(오프라인 메타 + 과거 빌드 백필)
