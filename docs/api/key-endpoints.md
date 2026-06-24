# Key API Endpoints

> CLAUDE.md on-demand 레퍼런스 — endpoint 작업 시 참조.

- `POST /api/jenkins/uds/generate-async` — UDS 생성
- `POST /api/jenkins/sts/generate-async` — STS 생성
- `POST /api/jenkins/suts/generate-async` — SUTS 생성
- `POST /api/local/sits/generate-async` — SITS 생성
- `POST /api/jenkins/impact/trigger-async` — Impact 분석
- `GET /api/jenkins/progress` — 진행률 조회
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
