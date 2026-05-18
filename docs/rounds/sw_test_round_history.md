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
