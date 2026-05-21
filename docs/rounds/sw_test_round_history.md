# SwUT/SwIT 라운드 히스토리 (36-fix ~ 42차)

> CLAUDE.md 본문 비대화 해결 (44차 W21) — 36-fix ~ 42차 상세 라운드 노트를 본 파일로 분리.
> 33-35차 핵심 정책 + 43차 (최신) + 44차+ 신규 라운드는 CLAUDE.md 본문 유지.

## 36-fix — SwIT log filename SwITC_ prefix 지원 (Critical)
- 35차 PoC 자체 평가 중 발견: `_extract_env_from_filename` regex가 `SWTE_\d+` 하드코딩
  → 사용자 실 환경 `SwITC_21_*.html` 거부 → environments 0건
- Fix: `env_prefix` kwarg 도입 (`_extract_env_from_filename`, `collect_from_log_folder`,
  `collect_from_jenkins_cache`, `collect_swut_session`). SwIT는 "SwITC" 명시 전달
- 회귀: SwUT 4 + SwIT 7 = 11건 통과 (1842 → 1849)

## 37차 — log_folder 자동 latest release 선택
- `01.Log/` 상위 폴더만 줘도 `v<버전>_<YYMMDD>` 패턴 중 날짜 suffix 최대값 자동 선택
- `_resolve_latest_release_folder` helper: Case A (release 폴더 직접 지정 → 그대로) /
  Case B (`01.Log/` 상위 → 자동 latest) / cloudium 모드 graceful warning
- 빌더 4개 (`swut_coverage`/`swut_sutr`/`swit_coverage`/`swit_sitr`) — `session.parse_warnings`를
  응답 warnings에 통합 (X-SwUT-Warnings / X-SwIT-Warnings 헤더 노출) — input_adapter 단계
  메시지가 frontend Warnings 패널에 표시
- reviewer W1/W2 fix: 날짜 자리수 혼재 감지 warning + resolver.exists() 예외 silent 차단
- 회귀: 5 (basic) + 1 (W1) + 1 (W2) = 7건 통과 (1849 → 1854)

### 비-목표 (38차+)
- 라이브 검증 결과 fix (실 양식 시트 위치 / VBA 보존 / 사용자 환경 path 인코딩)
- SwIT 시리즈 SwUDS↔SwIT 매핑 audit 정책 사전 통보 (회사 양식 빨강만 표준)
- `swit_meta.json` config 파일 도입 (현재는 req 명시 입력만, SwUT는 config 있음)
- Cloudium 모드 자동 latest 선택 지원 (현재는 local 전용 — list_dir이 파일만 반환 한계)
- reviewer W3: 라우터 `allowed_roots` 명시 주입 (현재 None — Pydantic + path traversal blacklist로 2차 방어)

## 38차 — 35차 비판 평가 발견 결함 해결 (DRY/__all__/dry-run preview/_safety)
- **W1 DRY**: `backend/services/swut_builder_helpers.py` 신규 — `extract_warnings_from_session(session)` helper. 빌더 4개 (swut_coverage/swut_sutr/swit_coverage/swit_sitr)에서 `warnings: list[str] = list(session.parse_warnings or [])` → helper 호출로 통합
- **W2 강결합**: SwUT `swut_coverage_aggregator.py` + `swut_sutr_aggregator.py`에 `__all__` 명시. SwIT가 import 중인 private 함수도 포함하여 signature 변경 시 SwIT 회귀 동시 검증 의무 가시화
- **I2 _safety decorator**: `backend/routers/_safety.py` 신규 — `run_build_safely` + `run_consistency_safely` + `get_process_memory_mb`. SwUT/SwIT 라우터의 `_run_*_safely` 4개 함수 통합. 100+ lines 중복 제거
- **W4 dry-run preview**: `POST /api/swut/log-folder/preview` + `POST /api/swit/log-folder/preview` endpoint 신규. 사용자가 빌드 전 자동 선택될 release를 미리 확인. `LogFolderPreviewRequest` Pydantic + `preview_release_candidates(resolver, log_folder)` helper. frontend SwITBuildSection에 "🔎 미리보기" 버튼 + inline panel (`is_latest=true` row 강조)
- **W6 edge case 회귀**: 100 후보 성능 (1초 미만) / 심볼릭 링크 (POSIX 한정 skip) / W2 silent failure (mock resolver)
- **C2 cloudium fallback (부분)**: cloudium 모드에서 `resolver.list_dir`이 디렉토리 반환할 경우 자동 latest 시도. worker 빌드/배포 시점에 활성화 가능. 미지원 worker는 기존 graceful warning 유지
- **C3 PoC headers fix**: `.codex_tmp/poc_swit_round38_live.py`에서 `dict(r.headers).get("X-SwIT-Summary")` → `{k.lower(): v}` lowercase dict 변환. urllib HTTPMessage case-insensitive 보장
- 회귀: backend +21 / frontend +2 (1854 → 1875 / 228 → 230)

### 비-목표 (39차+ — 사용자 의무)
- **C1 실 환경 라이브 검증**: Cloudium worker(`dist/excel_rename_gui_v2.exe`) 실행 후 실 `U:\연구소\...` path + 회사 xlsx/xlsm + 실 VectorCAST html → vcast_parser 데이터 추출 검증
- **W3 VBA 실 보존**: 회사 v2.02 xlsm template (vbaProject.bin 포함)으로 SITR 빌드 후 Excel에서 macro 실행 확인
- **W5 Backend 인스턴스 정리**: 9000~9004 다수 — Windows task manager 또는 `Stop-Process -Id <PID>`
- **Cloudium worker IPC 확장**: 본 repo에 worker 소스 없음. 별도 빌드 라운드 필요

## 39차 — Cloudium 동적 allowed_prefixes + PathPickerDialog UX (A+B+C 통합)
- 38차 commit 후 사용자 SwIT/SwUT Browse cloudium 동작 안 됨 보고 → 두 차단 식별:
  - 차단1: `allowed_prefixes`에 SwIT/SwUT Test Result 경로 미포함 → 403 CLOUDIUM_BLOCKED
  - 차단2: Cloudium worker IPC `list_dir`이 파일만 반환 — backend 디렉토리 navigate 불가
- **A (동적 add-allowed-prefix endpoint)**:
  - `backend/services/cloudium_extra_prefixes.py` 신규 — CRUD (load/save/add/remove) + atomic write
  - `config/cloudium_extra_prefixes.json` 영구 저장소 (scm_registry와 분리 — SCM은 추적성, extra는 빌드 input)
  - `POST /api/file-mode/add-allowed-prefix` + `remove-allowed-prefix` + `GET extra-prefixes` 3 endpoint
  - Pydantic AddAllowedPrefixRequest / RemoveAllowedPrefixRequest (maxlen 500 + `_no_newline`)
  - cloudium 모드 전용 — local 모드 시 400 거부
- **B (startup auto-merge hook)**:
  - `backend/main.py` lifespan + `health.set_file_mode`에서 `load_extra_prefixes()` 자동 호출
  - backend 재기동 후에도 사용자 추가 path 유지
- **C (PathPickerDialog UX 강화)**:
  - cloudium 모드 시 prominent 경고 카드 (`picker-cloudium-warning`) — "worker가 디렉토리 navigate 미지원, path 직접 입력 권장"
  - bookmark dropdown (localStorage `devops_v2_cloudium_path_bookmarks`, LRU 20건) — 자주 쓰는 경로 빠른 접근
  - 403 자동 add 제안 — CLOUDIUM_BLOCKED 응답 시 "이 경로를 추가하시겠습니까?" prompt → 확인 시 add-allowed-prefix 호출 + 자동 재시도
- **D (worker exe `list_dirs` op 신규)** — 본 라운드 비-목표 (별도 빌드 라운드, worker 소스 외부 repo)
- 회귀: backend 1875 → 1895 (+20) / frontend 230 → 234 (+4)
- 라이브 PoC 검증 (port 9005): SwIT Test Result path 동적 추가 → 차단1 해제 ✓ (status 200) → 파일 4건 list 반환, 디렉토리는 cloudium_hint로 안내 (차단2 UX 우회 ✓)

## 40차 — Backend Admin Role 시스템 (A안: 전체 admin only) — 보안 강화
- 39-fix-2 자체 평가에서 발견한 C1+C2+C3+W7 4건을 통합 fix
- 사용자 결정 (AskUserQuestion): A안 — 진짜 admin 보안 + 전체 SwIT/SwUT endpoint admin only + GET /api/auth/me + React Context
- **신규**:
  - `config/admin_users.json` — admin 사용자 list 영구 저장 (X-User 헤더값 매칭)
  - `backend/services/admin_users.py` — CRUD (load/add/remove/is_admin) + FileLock + atomic write + lru_cache + mtime invalidate
  - `backend/dependencies/admin.py::require_admin()` — FastAPI Depends, 401 AUTH_REQUIRED / 403 ADMIN_REQUIRED
  - `backend/routers/auth.py` — `GET /api/auth/me` (공개) + `GET /api/auth/admins` (admin only)
  - `frontend-v2/src/contexts/AdminContext.jsx` — AdminProvider + useAdminMode hook, `/api/auth/me` 호출 + custom event listener
- **13 endpoint admin only 가드** (`Depends(require_admin)` 추가):
  - SwIT 4 (coverage/sitr build + consistency + preview)
  - SwUT 5 (coverage/sutr build + consistency + preview + browse)
  - file-mode 4 (add/remove/list extra-prefixes + browse-file)
  - 예외: `GET /api/file-mode` (mode 조회), `GET /api/auth/me` 공개 유지
- **C1 fix**: localStorage 신뢰 제거 → backend `config/admin_users.json` 정식 권한 검증
- **C2 fix**: 빌드 endpoint도 admin only (frontend 빌드 버튼도 disabled)
- **C3 fix**: same-tab admin 토글 — App.jsx Ctrl+Shift+A에 custom event 'admin-mode-changed' dispatch → AdminProvider 즉시 refresh
- **W2 fix**: PathPickerDialog 자체 admin 가드 — non-admin이면 모달 자체에 "🔒 관리자 권한 필요" 표시
- **W7 fix**: backend admin role 회귀 +57건 (admin_users 12 + auth 6 + admin_gate 39)
- 회귀: backend 1895 → 1952 (+57) / frontend 235 → 239 (+4 AdminContext)

## 41차 — Bootstrap admin + APIRouter deps + AdminContext visibility refresh
- 40차 자체 평가 발견 문제 (C2/W2/W3/W4/W8/W9) 개선. C1 (JWT)은 42차+ 별도.
- **W2 Bootstrap admin**: `BOOTSTRAP_ADMIN_USERS` env → backend startup 시 빈 admin_users.json에 자동 등록 (lockout 회복용). `bootstrap_from_env()` 4 action: bootstrapped / skipped_has_admins / skipped_no_env / error
- **W3 APIRouter dependency**: SwIT/SwUT 라우터 전체에 `dependencies=[Depends(require_admin)]` — 9 endpoint signature에서 `_admin` 파라미터 제거 (코드 정리)
- **W4 AdminContext visibility refresh**: `document.visibilitychange` listener 추가 — 탭 visible 시 `/api/auth/me` 자동 refresh (backend 회복 / 다른 클라이언트 admin 변경 자동 반영)
- **W8 Admin 운영 가이드** (CLAUDE.md 본문 별도 섹션 참고)
- **W9 Cloudium admin role**: 라이브 PoC port 9008에서 cloudium 모드 전환 후 admin/non-admin 분기 정상 (mode 무관 admin gate 동작)
- **C2 PoC 강화**: admin 빌드 정상 경로 (status=200) 명시 검증 — 이전 40차 PoC는 400만 확인
- 회귀: backend 1952 → 1956 (+4 bootstrap) / frontend 239 → 240 (+1 visibility)

## 42차 — 41차 자체 평가 발견 문제 통합 fix (W2/W4/W5/W6/W7/W10/W11/W17/W18/C2/C3)
- 41차 자체 평가에서 발견한 9건 fix + 추가 4건 (C3/W11/W17/W18) 즉시 처리. C1 JWT는 43차+ 별도.
- **W2 health admin sub-router**: `admin_router = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])` — 4 file-mode endpoint 분리 (DRY)
- **W4 AdminContext retry**: fetch 실패 시 30초 후 1회 자동 재시도 (timer cleanup on unmount)
- **W5 debounce**: 외부 manual `refresh({force: false})` 호출 시 5초 내 중복 차단. visibility/storage/custom event는 force=true (즉시 반영)
- **W6 error_handler nested dict**: `HTTPException(detail=dict)`을 standard wrapper에 unpack — code/message 직접 추출 + extra 필드 detail에 보존 (이전 이중 wrapping `"{'code': ...}"` 문자열 노출 차단)
- **W7+W11 admin user 마스킹**: backend log에 user 평문 누출 차단 — `_mask_user(user)` helper (예: `hb***2`). startup bootstrap + runtime require_admin 거부 시 모두 적용
- **W18 bootstrap 응답 평문 제거**: `bootstrap_from_env()`가 `added` (평문 list) 대신 `added_count` + `added_masked`만 반환
- **W10 frontend dist rebuild**: 41차+42차 변경 모두 반영
- **C2 PoC 강화**: local 모드 fixture로 admin 빌드 status=200 + 실 산출물 8,515 bytes + environments=1 검증 (41차 cloudium 권한 영향 0 bytes 해결)
- **C3 error_handler 회귀 신규**: 7건 (str detail / dict detail / extra fields / missing code / empty dict)
- 회귀: backend 1956 → ~1968 (+12 — bootstrap +1 _mask_user / error_handler +7 / file_mode_router 영향 +0) / frontend 240 → 242 (+2 debounce + retry)

## 49차 — swut_meta.json fallback (SwUT/SwIT path 매번 입력 불필요)
- 사용자 지적: SwUDS Docx Path / C Source Root는 프로젝트 config에 등록된 값을 자동 사용해야 함
- **config 확장**: `config/swut_meta.json` HDPDM01 프로젝트에 `swuds_docx_path` + `template_paths.swit_coverage_template` + `template_paths.swit_sitr_template` 슬롯 추가 (빈 값으로 — 사용자가 환경별 path 채우기)
- **SwUT router fallback**: `_resolve_swuds_path` + `_resolve_c_source_root` helper 신규. `_resolve_swuds_function_ids` + `_resolve_swuds_function_asil_map` + `_apply_function_asil_map`에서 req 비면 config 값 사용
- **SwIT router fallback**: SwUT의 `_load_meta_from_config` import. `_read_template_bytes` 시그니처 `(template_path, project_id, kind)` — kind="coverage"/"sitr"로 swit_coverage_template / swit_sitr_template 키 사용. `_resolve_swit_swuds_path` + `_resolve_swit_c_source_root` 신규. 동일 ASIL fallback. 임시 DEBUG sitr/coverage log 제거
- **Frontend hint**: SwUT/SwIT BuildSection의 hint에 "비우면 config/swut_meta.json 사용" 안내 추가 (사용자 명시)
- 회귀: backend 79건 통과 (SwUT/SwIT router 회귀 무영향) — 빈 fallback 시나리오 회귀는 50차 추가
- **운영**: 사용자가 `config/swut_meta.json` 편집 → mtime invalidate 자동 → backend 재시작 불필요 (lru_cache + mtime key)

## 50차 — 49차 자체 평가 결함 일괄 fix + 403 raw fetch 노출
- 49차 commit 직전 평가에서 발견한 C1/C2/W1/W3/W4/W5/I1 일괄 처리 + 사용자 403 console 에러 진단
- **403 fix (mini-checklist X9)**: SwITBuildSection / SwUTBuildSection / PathPickerDialog가 raw fetch + X-User 단일 헤더만 부착 → JWT Authorization 미부착 → backend가 X-User 식별 사용자가 admin 아니면 403. `api.js`에 `authHeaders()` public export 추가 → 5곳 (SwIT 3 + SwUT 2 + PathPickerDialog 4 호출처) `'X-User': user` → `...authHeaders()` 변경. 3 테스트의 `vi.mock('../api.js')`에 `authHeaders` mock 추가 (49건 통과)
- **C1/C2 회귀**: `TestSwutConfigFallback50` (5건) + `TestSwitConfigFallback50` (4건) — req priority / config fallback / 둘 다 빈 / whitespace strip / SwIT template 빈 → 400 (coverage + sitr 키 분기 검증)
- **W1 type hint**: `_resolve_swit_swuds_path` + `_resolve_swit_c_source_root`에 `req: SwITBuildRequest | SwITSitrBuildRequest` annotation 추가
- **W3 hint 정리**: Frontend hint에서 "(49차)" 라운드 표기 제거 — 동작 설명만 유지
- **W4/W5 fallback 시각화**: `_apply_function_asil_map`이 `session.parse_warnings`에 source origin 명시 — `c_source 12건 (req)` 또는 `SwUDS 8건 (config fallback)` 형태. silent path 사용 차단 + audit reviewer가 X-SwUT-Warnings / X-SwIT-Warnings 헤더에서 확인 가능
- **W6 SwIT meta builder config fallback**: 49차에 누락 — `_build_swit_coverage_meta` + `_build_swit_sitr_meta`가 config를 전혀 읽지 않아 `default_author/reviewer/approver` 빈 string, `project_full_name`도 project_id 그대로. SwUT 패턴 (`_build_coverage_meta`)과 동일하게 `_load_meta_from_config` 호출 + `approvers.get(...)` + `project_full_name` fallback 적용. doc_id_base는 SwIT 고유 (`{project_id}-SwIT/SITR`) 유지. asil_level은 SwUT용 (ASIL A)이라 req의 ASIL B 사용 정책 유지
- 회귀: backend ~2030 → +12 fallback (~2042) / frontend 261 통과 (test mock 갱신만)

## 51차 — Template 2-field 분리 (Coverage / SUTR / SITR 양식별)
- 사용자 요청: SwUT은 Coverage Report (xlsx) + SUTR (xlsm) 양식이 다르고, SwIT도 Coverage (xlsx) + SITR (xlsm) 양식이 다른데 단일 `template_path` form 필드 → 매 빌드마다 변경 부담
- **Backend schema** (`backend/schemas.py`):
  - `SwUTBuildRequest`: `template_path` 제거 + `coverage_template_path` + `sutr_template_path` 신규 (각 maxlen 500 + `_no_newline` validator)
  - `SwITBuildRequest`: `template_path` 제거 + `coverage_template_path` + `sitr_template_path` 신규
  - `SwITSitrBuildRequest`: SwITBuildRequest 상속 (자동 반영)
- **Backend router**: `_do_coverage_build`/`_do_sutr_build`/`_do_swit_coverage_build`/`_do_swit_sitr_build` 각 endpoint가 kind별 적절한 필드 사용 + `_read_template_bytes(req.<kind>_template_path, req.project_id, kind)`로 호출. 빈 시 config의 `coverage_report_template`/`sutr_template`/`swit_coverage_template`/`swit_sitr_template` fallback (49차 인프라 그대로)
- **Frontend** (`SwUTBuildSection.jsx`/`SwITBuildSection.jsx`):
  - DEFAULT_FORM에서 `template_path` 제거 + 양 필드 추가
  - UI row 1개 → 2개 분리 (각각 별도 Browse 버튼 + label "Coverage Template Path (xlsx)" / "SUTR Template Path (xlsm)" 또는 "SITR Template Path (xlsm)")
  - `buildXlsx` client validation: kind별 적절한 필드 검증 (`kind === 'coverage' ? coverage_template_path : sutr_template_path`)
- **Browse 다이얼로그 파일 필터**: Coverage = `*.xlsx`, SUTR/SITR = `*.xlsm` (이전 통합 `*.xlsx,*.xlsm`)
- **회귀 갱신**:
  - backend: `test_w8_template_path_maxlen_rejected` → `test_w8_coverage_template_path_maxlen_rejected` + 신규 `test_w8_sutr_template_path_maxlen_rejected` (+1)
  - frontend: `getByText(/SUTR 빌드/)` matcher가 신규 "SUTR Template Path" 라벨과 multiple match → `/📝 SUTR 빌드/` 정확 매칭으로 변경. Browse 버튼 수 6 → 7. hint matcher "회사 v3.01 양식 template" → "Coverage 빌드 전용" + "SUTR 빌드 전용" 분리
- 회귀: backend 2042 → 2042 (회귀 갱신, +sutr maxlen 1 추가 후 정리) / frontend 261 통과
- **운영**: 사용자가 `config/swut_meta.json` 4 키 (`coverage_report_template`/`sutr_template`/`swit_coverage_template`/`swit_sitr_template`)에 한 번 박아두면, 빌드 form은 release_sw_version / test_date / log_folder만 매번 입력 + nothing else. mtime invalidate로 backend 재시작 불필요

## 52차 — 51차 자체 평가 발견 결함 통합 fix (C1/W2/W3 + cloudium prefix)
- 51차 commit 직전 자체 비판 평가에서 발견한 결함:
  - **C1 localStorage 마이그레이션 누락** — 51차 `template_path` 제거 후 이전 사용자가 form에 `template_path` 키 저장되어 있으면 backend로 그대로 보내져 무시 (Pydantic ignore) → 사용자 재입력 부담. `loadSavedForm`에서 legacy key 감지 → `coverage_template_path`로 자동 이동 + `delete saved.template_path`. SwUT/SwIT 양쪽 적용
  - **W2 endpoint별 정확한 field 사용 검증 누락** — Coverage endpoint이 `coverage_template_path` 사용, SUTR endpoint이 `sutr_template_path` 사용, SwIT 동일 — 회귀 부재. `_read_template_bytes` monkeypatch + capture 패턴으로 4건 추가 (SwUT 2 + SwIT 2). `kind` 인자도 함께 검증
  - **W3 docstring 갱신** — `SwUTBuildRequest` docstring에 `template_path` 언급 → `coverage_template_path / sutr_template_path` 갱신 (51차 분리 명시)
- **운영 환경 fix (사용자 환경 의존, 별도 라운드 영향 없음)**: cloudium 모드에서 SwIT 빌드 시 log_folder가 allowed_prefixes 미등록으로 403 → admin endpoint `POST /api/file-mode/add-allowed-prefix`로 3 prefix 추가 (`08.SW 통합테스트/03.Test Result/01.Log` + `08.SW 통합테스트/03.Test Result` 상위 + `10.SW 단위테스트/03.Test Result`). `config/cloudium_extra_prefixes.json`에 영구 저장
- 회귀: backend 2042 → 2046 (+4 endpoint field 사용 검증 / Coverage / SUTR / SwIT Coverage / SwIT SITR)

## 53차 — deep-reviewer 발견 Critical 2 + Warning 회귀 3 통합 fix
- 49~52차 누적 변경 (~480 lines / 8 파일 / audit evidence 도구) deep-reviewer (opus) 호출 결과: Critical 2 / Warning 7 / Info 5 발견. 사용자 결정: Critical + 회귀 누락 3건 우선 처리.
- **C1 (Critical X3+X7) Pydantic `extra='forbid'`**: `SwUTBuildRequest` + `SwITBuildRequest` 둘 다 `model_config = ConfigDict(extra="forbid")` 추가. `SwITSitrBuildRequest`는 상속으로 자동 적용. 외부 호출자 (Jenkins curl, 외부 script)가 51차 이전 `template_path` 키 보내면 silent ignore 대신 **422 raise + 명시적 마이그레이션 강제**. ISO 26262 audit evidence 도구의 silent wrong-pick (config fallback 양식 사용) 차단. `from pydantic import ConfigDict` 추가
- **C2 (Critical X5) cloudium `add_prefix` system blacklist**: `backend/services/cloudium_extra_prefixes.py`에 `_SYSTEM_BLACKLIST` tuple (Windows: `C:/Windows`, `C:/Program Files`, `C:/ProgramData`, `C:/Program Files (x86)` / POSIX: `/etc`, `/root`, `/sys`, `/proc`, `/bin`, `/sbin`, `/usr/bin`, `/usr/sbin`) + 단일 drive root (`C:/`, `D:/`, `/`) + `_is_blacklisted(prefix)` helper 추가. `add_prefix(prefix)`이 ValueError raise → endpoint 400. admin이 실수로 `C:/` 등 등록하여 cloudium worker가 시스템 전체 read하는 보안 약화 차단. 30차 W21 `swut_asil_resolver` 백스탑 패턴 차용
- **W1 (Warning X8) SwIT c_source_root req priority 회귀**: 50차에 SwUT은 `test_resolve_c_source_root_req_priority` 회귀 있으나 SwIT은 config fallback만 있음. 향후 SwIT helper의 분기 순서 silent 뒤집기 위험. `test_resolve_swit_c_source_root_req_priority` 추가 — req 값 우선 + config 무시 검증
- **W2 (Warning X8) localStorage 마이그레이션 frontend 회귀**: 52차 C1 `loadSavedForm` 마이그레이션 (`saved.template_path` → `coverage_template_path` 자동 이동 + delete)이 SwUT/SwIT 양쪽에 있는데 회귀 부재. `SwUTBuildSection.test.jsx` + `SwITBuildSection.test.jsx`에 1건씩 추가 — localStorage setItem legacy form → render → coverage_template_path input value 검증
- **W3 (Warning X8) source origin parse_warnings 회귀**: 50차 W4/W5의 `function_asil_map source — c_source N건 (req)` 또는 `(config fallback)` 시각화가 audit reviewer가 ASIL 출처 인지하는 핵심인데 회귀 부재. `test_apply_function_asil_map_records_source_origin` 추가 — c_source req + swuds config fallback mixed case로 양 origin string 모두 검증. `swut_asil_resolver.resolve_function_asil_map`은 monkeypatch로 mock
- **잔여 Warning** (W4/W5/W6/W7/W8 + I*): DRY 위반 (`_apply_function_asil_map` ~70줄 복제) + endpoint별 schema 분리 등은 별도 라운드 (54차+) 후보. ISO 26262 ASIL 정책 silent divergence 위험은 인지하나 본 라운드는 안전성 핵심 결함 우선 처리
- **운영 fix (부수)**: backend uvicorn `--reload`가 swit.py 변경 detect 못 한 케이스 발견 → backend 강제 kill + 재시작. 51차+52차 schema 메모리 로드 보장. 사용자가 SwIT 빌드 시도 시 422 또는 400 정확한 에러 응답
- 회귀: backend 2046 → 2048 (+2: SwIT c_source req priority + source origin) / frontend 261 → 263 (+2: SwUT/SwIT localStorage 마이그레이션)
- **운영**: cloudium `add_prefix` 호출 시 system 디렉토리 prefix는 400 응답 + ValueError detail. admin이 등록 가능한 prefix는 사용자 작업 path (`U:/연구소/...`, `D:/Project/...`)만

## 53-fix — 53차 자체 평가 발견 결함 통합 fix
- 53차 commit `9ab7e7f` 직전 자체 비판 평가에서 발견한 결함:
  - **C1 시트명 substring 매칭 회귀 부재** — 53차에 swit_coverage_aggregator + swit_sitr_aggregator의 `n.lower() == "test summary"` → `"test summary" in n.lower()`로 변경. 향후 누군가 exact 매칭으로 되돌리면 silent regression. `TestSheetNameSubstring53fix` 신규 클래스 2건: swit_coverage / swit_sitr aggregator 모듈 source에 substring pattern 명시 검증 (inspect.getsource로 코드 검사)
  - **C2 extra='forbid' 422 응답 회귀 부재** — 53차 ConfigDict 적용 검증 누락. `TestExtraForbid53fix` 신규 클래스 3건: legacy `template_path` 키 → 422 + extra_forbidden detail / SwIT SITR endpoint 동일 / 임의 random key 거부
  - **W1 `_SYSTEM_BLACKLIST` 누락** — POSIX 시스템 디렉토리 `/var`, `/boot`, `/lib`, `/lib64` 미포함. 추가하여 cloudium add_prefix 차단 범위 확장
  - **W2 `_is_blacklisted` unit 회귀 부재** — sanity check만 했고 직접 unit test 부재. `TestSystemBlacklist53` 신규 클래스: blacklist 19건 parametrize (drive root + Windows 시스템 + POSIX 8건) + valid path 5건 parametrize + `_is_blacklisted` 직접 helper 검증
- 회귀: backend 2048 → ~2060 (+12: cloudium +24건 parametrize + extra=forbid 3 + sheetname substring 2 = ~29 신규 unique). 142 passed (cloudium + SwIT + SwUT 회귀 한꺼번에 실행)
- 53차 자체 평가에서 발견한 W3 (시트명 substring 비표준 양식 오매칭 가능성) 및 I1 (SwIT v2.02 양식 layout 본격 호환)은 54차+ 별도 라운드 후보

## 54차 — SwIT v2.02 양식 본격 호환 + DRY 통합

53차/53-fix 누적 후 사용자가 SwIT v2.02 빌드 산출물에 빈 셀 다수 보고. 원인: backend writer가 SwUT v3.01 hardcode label (`Release Name(SW)`, `Test Target Version(HW)`)을 검색했는데 SwIT v2.02 양식은 `SW Version`, `HW Version` 사용 → label 미발견 → fill 미실행. 추가로 v2.02 B17-F17 TC 통계 row + B22 Requirements/Design Coverage SwITS + Test Log AL column marker가 v3.01에 없는 신규 row/col.

### T280 — Layout resolver 모듈 (excel_layout_resolver.py 신규)
- 회사 양식 (v2.02 / v3.01) template bytes를 openpyxl로 inspect하여 label↔cell 매핑 + 신규 row 위치를 자동 추출. `SwitLayout` dataclass: `detected_version` / `cover_labels` / `test_summary_labels` / `tc_stats_row` / `tc_stats_col_start` / `requirements_row` / `test_log_header_cell` / `test_log_extra_marker_col` / `warnings`
- candidate label 매칭 우선순위 (v2.02 → v3.01 fallback): `release_sw_version`은 `("SW Version", "SW 버전", "Release Name(SW)")` 순. v2.02 라벨 우선 매칭, 못 찾으면 v3.01 fallback
- v2.02 신규 row 후보: `Total TC` / `Test Case Count` / `TC Count` 등 (`tc_stats_row`) + `Requirements/Design Coverage` 등 (`requirements_row`). v3.01 template에는 부재 → None 반환
- SITR-only inspect: Test Log 시트 header row에서 `Marker` / `Pass/Fail Marker` 라벨로 AL column index 추출
- sha256 keying + 자체 구현 LRU cache(maxsize=4). 동일 template 반복 빌드 시 `load_workbook` 1회만
- openpyxl 미설치 / 손상 bytes / 시트 미발견 graceful — `fallback_to_v301=True` + warnings 누적, raise 안 함
- 회귀 10건 (`test_excel_layout_resolver.py`): v2.02 coverage / v2.02 sitr / v3.01 fallback / sha256 cache hit / LRU evict / graceful missing / kind coverage skip test_log / kind sitr include AL col

### T281 — DRY 통합 (swut_meta_resolver.py 신규)
- 50차 W4/W5에서 도입된 `_resolve_swuds_path`, `_resolve_c_source_root`, `_apply_function_asil_map` (~70줄)이 SwUT/SwIT 라우터에 중복 → audit 추적성 약화. 본 라운드에서 `backend/services/swut_meta_resolver.py`로 통합
- public API: `load_meta_from_config(project_id)` / `resolve_swuds_path(req, project_id)` / `resolve_c_source_root(req, project_id)` / `resolve_swuds_function_ids(req, project_id)` / `resolve_swuds_function_asil_map(req, project_id)` / `apply_function_asil_map(req, session, project_id)`. 32차 W28 c_source 우선 정책 + 50차 W4/W5 source origin 시각화 유지
- 라우터 layer (`swut.py` / `swit.py`)는 thin wrapper만 유지: `def _apply_function_asil_map(req, session): _resolver_apply_function_asil_map(req, session, req.project_id)`. monkeypatch 의존 회귀 import 경로 무영향
- backward compat: `swut._META_CONFIG_PATH` + `swut._read_meta_config_raw` alias 유지. `_load_meta_from_config` thin wrapper에서 monkeypatch한 path를 resolver 모듈로 동기화
- 회귀 9건 (`test_swut_meta_resolver.py`): swuds path req 우선 / config fallback / 둘 다 비면 빈 / c_source 동일 / apply source origin req / apply source origin config fallback / ASIL 충돌 warning + c_source 우선 / 둘 다 비면 skip
- 기존 회귀 호환 (307건 무영향): `test_swut_router.py` + `test_swit_router.py`의 `_setup_cfg` 헬퍼만 monkeypatch 대상 `resolver_mod._META_CONFIG_PATH`로 redirect

### T282 — SwIT v2.02 writer 분기 (layout kwarg)
- `_write_cover_sheet` / `_write_test_summary_sheet` (swut_coverage_aggregator.py) + `_write_cover` / `_write_test_summary` / `_write_test_log` (swut_sutr_aggregator.py) 모두 `layout: SwitLayout | None = None` keyword-only kwarg 추가
- 내부: `labels = layout.cover_labels if layout else {}` 후 `labels.get("project_full_name", "Project")` 패턴. v2.02 layout 제공 시 동적 label 매핑, layout=None이면 v3.01 hardcode label (SwUT 회귀 zero 영향)
- SwIT aggregator (swit_coverage_aggregator.py / swit_sitr_aggregator.py): build 함수 진입 직후 `layout = inspect_swit_layout(template_bytes, "coverage"|"sitr")` 호출 → 6 writer 호출에 layout 전달

### T283 — TC stats / B22 / AL marker fill
- `_write_test_summary_sheet` (Coverage) 추가: layout.tc_stats_row != None이면 B17 col부터 Total/Tested/Passed/Failed/Blocked(0) 채움. `summary["tc_stats_blocked_inferred"]=True` 표기 (audit reviewer가 명시적으로 채움 안내)
- layout.requirements_row != None이면 B22(col 2)에 `"SwITS"` 표기 (SwIT artifact 식별)
- `_write_test_log` (SUTR): layout.test_log_extra_marker_col != None이면 각 row의 AL col에 `✓`(Pass) / `✗`(Fail) marker fill
- 9 신규 회귀 (`TestSwitV202LayoutCompat` 5건 + `TestSwitSitrV202LayoutCompat` 4건): v2.02 fixture template으로 빌드 후 산출물 셀 값 검증 + v3.01 backward compat 검증

### 회귀 통계
- backend ~2060 → ~2078 (+18: layout_resolver 10 + meta_resolver 9 + writer v2.02 9 - 기존 monkeypatch 회귀 무영향 0)
- frontend 263 → 263 (response shape 무변경)
- pre-commit hook 180s 한도 내

### 리스크 완화
- writer signature 변경은 모두 `layout=None` default kwarg → SwUT 기존 호출 사이트 무영향 (회귀 batch 검증)
- v2.02 template label이 실 양식과 다를 수 있어 candidate-tuple에 한글/영문 변형 모두 등록. 미발견 시 `fallback_to_v301=True` + warnings에 누락 label 누적 (audit reviewer 인지 가능)
- TC stats "blocked" 필드 모호 → 0 채움 + `tc_stats_blocked_inferred` summary 표시. 사용자가 명시적으로 fill 책임

### 비-목표 (55차+)
- SwIT 시트명 substring → regex 패턴 (`r"^\d*\.?\s*test summary"`) — 53차 substring으로 호환 100%
- ~~SwUT v3.01 양식의 layout_resolver 통합~~ — **54-fix C1으로 완료** (silent 빈 셀 차단)
- 사용자 실 환경 v2.02 라이브 검증 (사용자 의무)
- swit_meta.py SwIT 전용 default (현재 hbrnd2 환경은 SwUT/SwIT 공통)

## 54-fix — 54차 자체 평가 발견 결함 통합 (deep-reviewer C1/C2 + W1~W4)

54차 commit `132a97c` 후 deep-reviewer (opus) 시나리오 기반 비판 검토에서 Critical 2 + Warning 4 + Info 2 발견. Info 2건은 별도 라운드 (SwitLayout rename + docstring 명시), Critical + Warning 6건 본 fix.

### C1 — SwUT 라우터가 v2.02 template 잘못 입력 시 silent 빈 셀 차단 (Critical X3)
- **시나리오**: 사용자가 SwIT v2.02 path를 SwUT 라우터 `coverage_template_path`에 실수로 입력 → SwUT aggregator는 layout 미호출 → "Release Name(SW)" find_kv_row 미발견 → 빈 셀 산출물 → ISO 26262 audit evidence가 빈 채로 reviewer 제출
- **Fix**:
  - `swut_coverage_aggregator.py` + `swut_sutr_aggregator.py` build 함수 진입 직후 `inspect_swit_layout(template_bytes, "coverage"|"sitr")` 호출 (SwIT aggregator와 대칭)
  - 모든 writer 호출에 `layout=layout, summary=summary` 전달
  - 시트명 매칭을 53차 SwIT 패턴 대칭으로 substring 변경 (`"test summary" in n.lower()` 등) — v2.02 "1.Test Summary" 호환 + v3.01 backward compat 유지
- **회귀**: `TestSwutBuilderV202InspectFix54` 2건 (v2.02 SW Version 자동 fill + v3.01 backward compat)

### C2 — excel_layout_resolver ZIP bomb 방어 부재 (Critical X5)
- **시나리오**: `inspect_swit_layout`이 `__all__`에 public export → 향후 직접 호출 시 `validate_xlsx_template_bytes` 우회 가능 → 압축비 1000:1 또는 4GB decompressed ZIP에 메모리 폭증
- **Fix**: `_inspect_internal` 진입에 `validate_xlsx_template_bytes(template_bytes, label=f"layout inspect ({kind})")` 추가. `TemplateValidationError` catch하여 fallback_to_v301=True + warnings 누적 (graceful, raise 안 함)
- **회귀**: `test_inspect_rejects_zip_bomb_magic_bytes` (PK\x03\x04 magic + 빈 ZIP 구조 → 거부)
- **회귀 갱신**: `test_corrupted_bytes_graceful` 메시지 매칭에 "template 입력 검증 실패" 추가

### W1 — `_LAYOUT_CACHE` race / StopIteration 방어 (Warning X1)
- **시나리오**: Semaphore(3) SwUT + Semaphore(2) SwIT + 54-fix C1로 SwUT도 layout 호출 → 최대 5건 동시 thread. dict iter + del 복합 연산 비-atomic → cache stampede + LRU thrashing + 빈 dict에서 StopIteration 가능
- **Fix**: `threading.Lock` 추가. `inspect_swit_layout`이 fast path/miss path/insertion 모두 lock 내. stampede 검사 (다른 thread가 먼저 set 했으면 그 값 반환) + `try/except StopIteration` race-safe guard

### W2 — swit.py _META_CONFIG_PATH alias 통일 (Warning X4)
- **시나리오**: swut.py는 backward compat alias + 단방향 sync wrapper 있는데 swit.py는 없음. 회귀 setup_cfg가 swut만 patch하고 swit를 호출하면 stale path 사용 위험. 비대칭 패턴이 향후 cross-test contamination 또는 회귀 작성자 혼란
- **Fix**:
  - swit.py에도 swut.py 동일 패턴 — `_META_CONFIG_PATH = _resolver_mod._META_CONFIG_PATH` alias + `_read_meta_config_raw` alias + `_load_meta_from_config` thin wrapper에 단방향 sync 로직
  - `tests/unit/test_swit_router.py` `_setup_cfg`에 `monkeypatch.setattr(swit_mod, "_META_CONFIG_PATH", str(cfg_path))` 추가 (3개 모듈 모두 patch)

### W3 — cache maxsize 4 → 8 thrashing 방지 (Warning X6)
- **시나리오**: 회사 양식 정확히 4개라 한계. 시험용/추가 template 진입 시 thrashing. 현재 SwUT는 layout 호출 안 했으나 C1 fix로 호출 추가됨 — 양식 4개 모두 사용 시점에 새 template 진입하면 evict
- **Fix**: `_MAX_CACHE_SIZE = 8` (4 → 8). 회귀 `test_lru_evict_when_max_exceeded` 9개 진입 시 8개 유지로 갱신

### W4 — blocked_inferred 산출물 표기 + AL marker None 처리 (Warning X7)
- **시나리오 1 (blocked inferred)**: `summary["tc_stats_blocked_inferred"] = True`만 set하고 산출물 셀에는 "0"만 fill → audit reviewer가 "VectorCAST가 blocked TC 0건 실제 보고"로 오해 → 잘못된 evidence
- **시나리오 2 (AL marker None)**: `marker = "✓" if exec_r.passed else "✗"` → exec_r.passed=None (결과 unset)도 ✗로 표기 (silent wrong-pick)
- **Fix**:
  - `_write_v202_extra_rows` (Coverage) + SUTR `_write_test_summary` 둘 다 B17 col+5 cell에 `mark_user_input_required` 노란 강조 + hint "Blocked TC 수 inferred=0 — VectorCAST blocked 미지원, 명시적 입력 필요"
  - AL marker: `exec_r.passed is True` → ✓ / `is False` → ✗ / `is None` → "—" (silent wrong-pick 방지)

### 회귀 통계
- backend ~2078 → ~2082 (+4: C2 zip_bomb_magic_bytes + C1 v202_fills + C1 v301_backward + corrupted_bytes 메시지 갱신 / lru_evict 9 entry 갱신은 net 0)
- backend SwUT/SwIT batch 439 통과 (54차 436 → +3)
- frontend 263 무변경

### 비-목표 (55차+ Info)
- I1 SwitLayout → ExcelTemplateLayout rename (회귀 다수 import — 별도 정비 라운드)
- ~~I2 docstring kind 인자 명시~~ — **55차에서 완료**
- ~~frontend SwITBuildSection summary panel에 tc_stats_blocked_inferred 표시~~ — **55차에서 완료**

## 55차 — frontend blocked_inferred UI 경고 + swut_meta_resolver docstring 명확화

54-fix W4에서 backend는 산출물 B17 col+5 노란 강조 + `summary["tc_stats_blocked_inferred"] = True` set 했으나 frontend가 raw JSON `<pre>` dump로만 노출 → audit reviewer가 download 전 inferred 데이터 인지 불가. cross-stack 표시 누락 fix.

### T298+T299 — frontend 경고 panel (SwIT + SwUT 대칭)
- `SwITBuildSection.jsx` + `SwUTBuildSection.jsx` `lastSummary` 영역에 conditional render
- `lastSummary?.tc_stats_blocked_inferred === true` 시 `role="alert"` panel — "TC Stats Blocked = 0 (inferred). VectorCAST blocked 미지원, B17 row F열 0 채움, G열 노란 강조로 audit reviewer 명시 입력 안내"
- CSS `.swut-blocked-inferred-warning` 추가 — 좌측 4px amber border + `--color-warning-soft` 배경 (Excel 노란 강조 시각 매칭). design tokens 무영향

### T300 — frontend 회귀 +4건
- SwITBuildSection.test.jsx +2: mock fetch `tc_stats_blocked_inferred: true` 응답 → 경고 panel 렌더 / key 부재 → 미렌더
- SwUTBuildSection.test.jsx +2: SwUT v2.02 잘못 입력 시나리오 (54-fix C1 cross-stack) — 동일 패턴

### T301 — swut_meta_resolver 5 함수 docstring 보강 (I2)
- `resolve_swuds_path` / `resolve_c_source_root` / `resolve_swuds_function_ids` / `resolve_swuds_function_asil_map` / `apply_function_asil_map` 모두 docstring에 "plan vs 구현 divergence (54-fix I2 / 55차)" 섹션 추가
- 명시: plan의 `kind: Literal["swut", "swit"]` 인자는 req 객체의 동일 속성명(swuds_docx_path / c_source_root)으로 덕 타이핑 흡수. SwUT/SwIT 동일 함수 호환. 향후 분기 필요 시 kind 도입 검토 안내
- `load_meta_from_config(project_id)`는 req 인자 없음 → 무영향

### 회귀
- frontend 263 → 267 (+4: SwIT 2 + SwUT 2)
- backend swut_meta_resolver 9건 무변경 (docstring만)
- frontend 변경 영역 41/41 통과 (SwIT 13 + SwUT 28)

### ISO 26262 영향
- audit reviewer가 download 전 inferred 데이터 명시 인지 → 추적성 강화 (W4 cross-stack 완료)
- evidence_class 정책 무변경 — UI 경고는 reviewer 행동 유도, evidence 자체 변경 없음
- Backend RGB / Frontend CSS 색상 컨텍스트 분리 정책 유지 (`--color-warning-soft` 기존 토큰 재사용)

### 비-목표 (56차+)
- I1 SwitLayout → ExcelTemplateLayout rename (회귀 import 7 파일 / 17 문자열 — 별도 정비 라운드)
- excel_layout_resolver candidate-tuple config-driven (`swut_meta.json`에 label override — 사용자 라이브 검증 결과 따라)
- 라우터 `_META_CONFIG_PATH` 단방향 sync 패턴 정리 (alias 제거 + 회귀 setup_cfg 통일)
- 사용자 실 환경 v2.02 라이브 검증 (사용자 의무 / 별도 PoC)

## 55-fix — 라이브 산출물 검증 발견 결함 통합 (사용자 보고)

사용자가 55차 commit `3a16b68` 후 실 환경에서 v2.02 양식으로 빌드한 산출물 2개를 검사하여 보고:
- `(HDPDM01)SwIT Coverage Report_v2.02_260514_R (1).xlsx`
- `(HDPDM01_SITR) Software Integration Test Result_v2.02_260514_R (1).xlsm`

산출물 inspect 결과 두 가지 핵심 문제 발견.

### T303 — History 시트 single-row 정책 (사용자 결정 B)
- **문제**: `collect_git_history(limit=10)`이 git log 10건 (`vf129dc0`, `v132a97c` 등 commit hash 버전)으로 History 시트 row 5~14 채움 → audit reviewer가 산출물 history로 혼동 + 매일 snapshot/auto-commit이 표기되어 구조적 의미 약화
- **사용자 결정**: (B) 오늘 날짜로 한 row만 — 산출물별 release 1건
- **Fix**:
  - `backend/services/excel_template_utils.py` 신규 helper `build_release_history_row(meta, doc_kind)` — `release_sw_version` + `test_date` (yy.mm.dd) + `description="Initial release v{version} ({doc_kind})"` + `author=meta.author` 1 row
  - 4 aggregator (`swut_coverage` / `swut_sutr` / `swit_coverage` / `swit_sitr`) 모두 `collect_git_history(limit=10)` → `build_release_history_row(meta, doc_kind=...)` 교체
  - `collect_git_history`는 backward compat로 유지 (별도 호출처 / 회귀)

### T304 — TC stats candidate 확장 + fill row 보정 (Critical)
- **문제 1**: 회사 v2.02 SITR 양식의 TC stats 라벨은 **`'Total Number of TCs'`** (B17~F17 가로 5컬럼) — 우리 candidate (`'Total TC', 'Test Case Count', 'TC Count'`)에 미등록 → label 검출 실패 → TC stats fill skip
- **문제 2**: 회사 양식은 row 17이 헤더, row 18이 data row — 우리 `_scan_tc_stats_row`가 label_row를 그대로 반환 → writer가 라벨 row를 덮어쓰기 시도 → 머지셀 anchor 실패로 silent skip
- **Fix**:
  - `_TC_STATS_LABELS`에 `'Total Number of TCs'` 추가 (55-fix 사용자 보고)
  - `_scan_tc_stats_row` 반환을 `(label_row + 1, label_col)` 로 변경 — data row 반환. col_start도 label_col (가로 배치라 첫 라벨 col부터 데이터)
- **Requirements row 정책**:
  - 회사 v2.02 SITR 양식은 row 22에 이미 `'SwITS'` default 채워져 있음 + F22 formula `=IFERROR(D22/C22,"")`
  - candidate에 `'■  Requirements/Design Coverage'` (prefix 양식) 추가하면 우리 코드가 row 20 (라벨 row)에 SwITS 덮어쓰기 위험 → **추가 금지** 주석 명시
  - 즉 Requirements row는 회사 default 그대로 유지 (audit reviewer 수동 입력)

### Cover 시트 fill 분석 (변경 없음)
- 회사 v2.02 Cover 시트는 horizontal 배치 (`I2='Author' J2='JK Kim' K2='Approver' L2='김진경'`) + row 10 title만 — Project / ASIL Level / Doc. ID / Validation Date 등 label 부재
- 우리 코드 `find_kv_row`는 Author/Approver 정확히 매칭하여 fill 성공 ✅
- 회사 양식이 그 정보를 받지 않는 단순 title sheet — fix 불필요

### 회귀 갱신
- `test_swit_coverage_aggregator.py::test_tc_stats_row_filled`: 검증 row 17 → 18, col B~E → A~E (label A17 → data A18)
- `test_swit_sitr_aggregator.py::test_tc_stats_row_filled`: 검증 row 17 → 18, col B~E → A~E
- 회귀: backend ~2082 → ~2082 (회귀 row 보정만, 신규 회귀 추가 없음)
- backend SwUT/SwIT batch **439 통과**

### 비-목표 (56차+)
- Consistency 시트 회사 v2.02 양식 3컬럼 구조 (`Item / Actual / Note`) 대응 (현재 우리 코드 5컬럼 가정 — 일부 row만 fill)
- 4.Coverage 시트 회사 formula `=IF(H11=I11, "O", "X")`와 우리 데이터 fill 충돌 정리
- 사용자 추가 라이브 검증 결과 따른 candidate 확장
