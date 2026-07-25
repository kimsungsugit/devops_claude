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
- **`POST /api/summary/baseline-diff`** — 베이스라인↔대상 소스 스냅샷 직접 비교(change-log 비의존). `files.changed_detail[]`이 **파일→변경 함수 트리**이며 각 함수에 커버리지·ASIL 조인(N3). `functions.gap_summary`가 '변경 함수 중 미커버' 최상위 신호. 캐시 키 = 양쪽 스냅샷 지문 + 커버리지/ASIL 조인 규모
- **`POST /api/summary/test-design`** — 테스트 설계 어드바이저(결정론, LLM 0회). UT/IT 행(`metric_set`), ASIL은 주석+요구 역전파 병합, 변경 축(`changed_axis` — 캐시된 baseline-diff 기반), ccn 기반 최소 TC 추정(`suggested_min_cases_estimate:true`), 기법 카탈로그 15종(ISO 26262-6 Table 8/9/11/12 참조). ⚠ IT 갭은 별도 축(`it_*`) — 통합 미실행 ≠ 단위 시험 부재
- **`POST /api/summary/test-case-draft`** — 함수 1개 시험 케이스 초안(Gemini on-demand + 디스크 캐시, N4). 결정론 골격(권고 기법·최소 TC·경계값 후보)은 LLM 없이도 항상 산출. 환각 필터는 **케이스 단위**(본문·파라미터·전역·호출 밖 식별자 과반이면 그 케이스만 폐기). `probe`/`force` 지원
- **`POST /api/summary/architecture-metrics`** — 소스 아키텍처 결정론 메트릭 v4. fan/핫스팟/결합/SCC + **asil_interference**(간섭 자유 검토 후보) · **global_coupling**(전역 공유, read/write 미구분 고지) · **coverage_complexity**(사분면, 미조인 수 표면화) · **indirect_calls/encapsulation**(콜그래프 완전성 — 간접 호출은 엣지 미반영)
- **`POST /api/summary/ai-insight`** — AI 인사이트(Gemini, 5섹션: rules/mistakes/roles/architecture/testing). `probe`=캐시만 조회, `force`=재생성. 캐시 히트 판정 = prompt_version + RCR stat 지문 + 모델
- **`POST /api/jenkins/prqa-delta`** · **`prqa-rule-trend`** · **`POST /api/summary/rule-fix-example`** · **`rule-unresolved-evidence`** · **`rule-definition`** — 규칙 워크벤치(빌드간 위반 delta·트렌드 분류·fix 증거·팀 룰 초안)
- **`POST /api/jenkins/cached-builds-meta`** · **`sync-backfill`** · **`GET /api/jenkins/sync-backfill-status/{job_id}`** — 캐시 빌드 표면 확대(오프라인 메타 + 과거 빌드 백필)
