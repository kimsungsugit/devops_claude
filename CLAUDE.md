# DevOps Release Claude - Automated Document Generation Platform

C 소스코드 + 요구사항 문서(SRS/SDS)로부터 설계/시험 규격서(UDS, STS, SUTS, SITS)를 자동 생성하는 DevOps 플랫폼.

## ISO 26262 Safety Context

이 프로젝트는 **ISO 26262:2018** 자동차 기능안전 표준을 따르는 문서 자동 생성 플랫폼이다.

### 추적성 체인
```
SRS (요구사항) → SDS (설계) → UDS (단위설계) → STS (단위시험) → SUTS (소프트웨어 통합시험) → SITS (시스템 통합시험)
```

### ASIL 등급 인식
- **ASIL D**: 최고 안전 등급. MC/DC 커버리지, 완전한 추적성, 코드 리뷰 필수
- **ASIL C**: MC/DC 커버리지 권장, 분기 커버리지 필수
- **ASIL B**: 분기 커버리지 필수, 구문 커버리지
- **ASIL A/QM**: 구문 커버리지

### 안전 규칙
- C 소스: MISRA-C 2012 준수, 방어적 프로그래밍
- 안전 관련 함수(ASIL C/D) 변경 시: reviewer 리뷰 필수, 테스트 자동 수정 금지
- 문서 생성 시: 추적성 매트릭스(SRS→UDS→STS) 자동 검증

### ASIL 탐지 기준 (통일)
ASIL 등급은 다음 순서로 판별한다:
1. 함수 주석의 ASIL 태그: `@asil A|B|C|D|QM` (Doxygen 주석 내)
2. SRS/SDS 문서의 안전 요구사항 매핑 (SCM registry 참조)
3. 파일/디렉토리명 패턴: `*_asil_*`, `*_safety_*`
4. 판별 불가 시: QM(비안전)으로 간주하되 reviewer에게 확인 요청

## Autonomous Operation Rules (자율 운영 규칙)

이 프로젝트에서 Claude는 **완전 자율 모드**로 동작한다. 사용자에게 묻지 말고 직접 판단하여 실행할 것.

### 자동 설치
- Python 패키지 누락 시: `pip install <패키지>` 즉시 실행
- npm 패키지 누락 시: `npm install <패키지>` 즉시 실행
- import 에러, ModuleNotFoundError 발생 시 자동 설치 후 재시도
- requirements.txt / package.json에 없는 패키지도 필요하면 설치하고 의존성 파일에 추가

### 자동 환경 구성
- 서버가 꺼져 있으면 자동으로 시작 (backend: uvicorn, frontend: npm run dev)
- venv가 없으면 생성, node_modules가 없으면 npm install 실행
- .env가 없으면 .env.example 복사하여 생성

### 자동 오류 복구
- 테스트 실패 시 원인 분석 → 수정 → 재실행까지 자동 진행
- 빌드 에러 시 의존성 확인 → 설치 → 재빌드
- 포트 충돌 시 프로세스 확인 후 대체 포트 사용
- **예외**: 안전 관련 테스트(ASIL C/D) 실패 시 자동 수정하지 않고 보고

### MCP / RAG 활용 (구체화 — 직접 Bash 사용 지양)

다음 작업은 **mcp__devops-release__*** 도구를 우선 사용한다. 직접 Bash로 처리하면 캐싱/권한 검증/일관성 손실:

| 작업 | 우선 사용할 MCP | 직접 Bash 폴백 허용 시점 |
|------|----------------|------------------------|
| 빌드/테스트 리포트 분석 | `report_summary`, `report_findings`, `report_coverage`, `report_log` | MCP에 없는 항목만 |
| Git 상태 조회 | `git_status`, `git_diff`, `git_log`, `git_changed_files` | 복잡한 형식 변환 필요 시 |
| 코드 검색 | `search_code` (file_glob/exclude_glob 필터 내장) | regex 매우 복잡할 때 |
| 문서 검색/열기 | `list_docs`, `search_docs`, `read_doc` | — |
| Jenkins 빌드 캐시 분석 | `jenkins_build_summary`, `jenkins_build_status` | — |
| Git 스테이징 | `git_stage_files` (경로 검증 내장) | — |
| 파일 쓰기 (project_root 하위) | `write_file`, `replace_in_file` | Edit/Write 도구로 충분한 일반 케이스 |

**Playwright MCP**: UI 검증이 필요하면 자동으로 브라우저 열어서 확인.
**RAG/Knowledge Base**: 문서 생성 시 기존 지식베이스 자동 참조.

### Settings/Hooks 변경 시 절차 (update-config 스킬 부재 정정)

`.claude/settings.json` / `.claude/settings.local.json` / hooks / permissions / env 변경 시 다음 절차 의무:

1. **백업**: `cp .claude/settings.json .claude/settings.json.bak.YYYYMMDD` (롤백 안전망)
2. **변경 후 parse 검증**: `python -c "import json; json.load(open('.claude/settings.json'))"` — 0 exit 아니면 즉시 백업 복원
3. **hook 변경 시 스모크 테스트**: `echo '{}' | python scripts/<hook>.py` 빈 입력으로 silent 종료 확인

**예외**: 단순 `permissions.allow` 항목 한두 개 추가는 직접 Edit 허용 (parse 검증만).

> 이전 버전은 `update-config` 스킬 호출을 의무화했으나 해당 스킬이 `.claude/skills/`에 부재 (2026-05-08 정비 시 정정). 스킬 신규 작성은 별도 작업으로 예정.

### TaskCreate 선제화

3단계 이상 또는 여러 파일 수정이 예상되는 작업은 **시작 전 즉시 TaskCreate**로 추적 시작한다. system reminder를 받고서야 만드는 반응적 패턴은 진행 가시성을 떨어뜨린다. 단일 파일 수정·간단한 질의 응답·정보 조회는 TaskCreate 불필요.

### 판단 기준
- "할까요?" 대신 "했습니다" — 묻지 말고 실행
- 에러가 나면 3회까지 자동 재시도 후 안 되면 보고
- 파일 생성/수정/삭제 모두 자율 판단 (단, .env 파일은 예외)

### 작업 종료 직전 비판적 자체 검토 (필수)

코드 변경 작업을 마치고 사용자에게 완료 보고하기 직전, **변경 규모에 맞는 깊이로 reviewer 에이전트를 호출**하여 비판적 자체 검토를 수행한다. PostToolUse hook의 syntax/lint는 기계적 검사일 뿐 설계·논리·동시성 같은 비판적 검토를 대체하지 않는다.

**review_depth 정의 단일 출처**: `.claude/agents/reviewer/reviewer.md` `## 검토 깊이 자동 판정` 섹션을 참조. meta / light / standard / deep 4단계, 키워드 강제 승격, ASIL 자동 판정, 변경 통계 측정 시점 모두 거기에 정의돼 있다. 본 문서와 SKILL.md들은 그 정의를 그대로 따른다.

**호출 정책 (review_depth 별)**:
- **meta** (정책/문서만 변경) → reviewer 생략, 메인 에이전트가 X4/X5/X6만 직접 점검
- **light** → reviewer 생략 가능, 단 미니 체크리스트(아래) 11개 항목은 메인이 직접 점검
- **standard** → reviewer **1회 호출** (S/P/Q/R/F + X1~X8 전체)
- **deep** → reviewer 적응형 3~5회 루프 (start-work Gate 5와 동일)
- **혼합형** (코드 + 문서 동시 변경) → reviewer.md `## 검토 깊이 자동 판정` `#### 혼합형` 규칙 적용 — 코드/문서 그룹 분리 후 max(depth) 채택, 출력에 정책 일관성 섹션 별도 보고

**생략 조건** (light로 강등):
- 사용자가 "검토 생략" / "리뷰 없이" / "빠르게" 명시
- 단순 lint/포맷 자동 수정만 발생

**보고 방식**:
- 발견된 Critical / Warning / Info를 표로 즉시 보고
- X1~X8 점검 결과는 매 reviewer 호출의 출력에 표 형태로 **반드시** 포함
- Critical은 사용자 확인 후 자동 수정 시도, Warning/Info는 보고만
- **능동 보고 (필수)**: 사용자가 "문제점은 없니?"를 묻기 전에 **매 commit 직전** 응답에 (1) 변경 요약 표, (2) X1~X8 mini-checklist 표, (3) 잠재 문제점 표(있으면), (4) 결론 1줄을 자동 포함한다. 이 패턴은 `feedback_critical_review_style.md`의 사용자 합의 사항.
- **입력 표면 매트릭스 (보안 경계 변경 시 필수)**: 권한 layer / 미들웨어 / handler / resolver 변경 또는 사용자 입력 endpoint 5개+ 추가 시 능동 보고에 (5) **입력 표면 매트릭스**를 추가한다. 행=입력 채널(JSON 단일/JSON list/JSON nested/Query/Form string/multi-path string/UploadFile/SSE/WebSocket/Cookie/Header), 열=검사 layer(미들웨어/endpoint/resolver), 셀=검사됨/우회/N/A. 빈 셀 또는 "우회"는 즉시 결함. fix 후 매 라운드 메타-점검: "이 fix가 같은 패턴의 다른 입구를 노출시키는가?" → whack-a-mole 방지. 상세는 `feedback_input_surface_matrix.md`.
- 검토 결과 "이상 없음"이면 한 줄로 표시 후 마무리

**reviewer 호출 실패 (403 등) 시 또는 light depth 시 메인 에이전트 미니 체크리스트**:

매 항목을 직접 점검하고 결과 표를 보고. "확인 안 함"은 금지, 결정 못 하면 Issue로 표시.

| # | 카테고리 | 점검 |
|---|----------|------|
| 1 | S1 (injection) | f-string SQL/command, `subprocess.*shell=True` 스캔 |
| 2 | S3 (path traversal) | `open(request.*)`, `Path(request.*)` 스캔 |
| 3 | Q1 (broad except) | `except:`, `except Exception:` 위치 |
| 4 | R2 (null guard) | 변경 파일의 `.map(` 호출이 `?.`/`Array.isArray`/`\|\| []`로 보호되는지 |
| 5 | X1 (race) | 변경 함수가 공유 상태(global/class attr/file/in-memory cache)를 lock 없이 수정하는지 |
| 6 | X2 (hook deps) | useEffect/useCallback/useMemo의 deps가 본문 참조 변수 모두 포함하는지 |
| 7 | X3 (계약) | API 응답 shape 변경 시 frontend 호출처가 새 필드명/타입 기대하는지 |
| 8 | X4 (회귀) | 변경 함수의 호출자 1-hop 호환성 (`grep -rn 함수명`) |
| 9 | X6 (데이터 일관성) | 캐시 키/sentinel/메모이즈 무효화가 변경된 데이터 흐름과 동기인지 |
| 10 | X7 (fallback) | 빈 배열/null/undefined 분기에서 `items[0]` 같은 silent wrong-pick 없는지 |
| 11 | X9 (raw fetch silent failure) | frontend 변경 시 `await fetch(` 호출이 (a) `api.js`의 `api/post/postSse` 헬퍼 안 쓰고 raw 호출 + (b) `X-User` 헤더 누락 + (c) `res.ok` 검사 누락 — 3 조건 충족 시 401/403/500을 silent로 삼키고 success 토스트로 위장. **점검 명령**: `grep -rnE "await fetch\(\|= fetch\(" frontend-v2/src --include="*.jsx" --include="*.js" \| grep -v "api.js:"` 후 각 호출의 헤더/검사 패턴 검증. JSON body는 `api()` 헬퍼로 변환, FormData(multipart) 사용 시 raw fetch 정당하지만 X-User + res.ok는 명시 필수. 상세: `feedback_raw_fetch_silent_failure.md` |

## Team Agents (에이전트 협업 구조)

핵심 에이전트(coder, architect)는 `model: opus`, 나머지는 `model: sonnet`. 스킬은 에이전트에 위임하여 실행.

| 에이전트 | 모델 | 역할 | 호출 시점 |
|---------|------|------|----------|
| **planner** | sonnet | 요구사항 분석, 작업 분해, 안전 영향도 평가 | Gate 1 (계획) |
| **architect** | **opus** | 모듈 설계, 인터페이스 정의, 아키텍처 결정 | Gate 2 (backend/workflow/report_gen) |
| **designer** | sonnet | UI/UX 설계, CSS 변수화, 접근성 | Gate 2 (frontend-v2) |
| **prompt-engineer** | sonnet | Gemini 프롬프트 체인 설계/튜닝 | Gate 2 (prompts/uds_ai.py) |
| **coder** | **opus** | Python/React/C 코드 구현 | Gate 3 (구현) |
| **tester** | sonnet | 테스트 작성/실행, ISO 26262 커버리지 + MCP 리포트 접근 | Gate 4 (검증) |
| **reviewer** | sonnet | 보안/성능/MISRA-C/ASIL 리뷰 + MCP 코드검색/리포트 접근 | Gate 5 (light/standard depth) |
| **deep-reviewer** | **opus** | deep depth 전용 비판 리뷰 (X1~X8 시나리오/timeline/트리 의무) | Gate 5 (deep depth — 100줄+/5파일+/키워드/ASIL) |
| **documenter** | sonnet | 계획서, 변경내역, 결과보고서 작성 + Bash 실행 | Gate 6 (문서화) |

### 에이전트 ↔ 스킬 관계
- `/plan` → planner 에이전트에 위임
- `/dev` → coder 에이전트에 위임
- `/test-run` → tester 에이전트에 위임
- `/workflow` → planner→coder→tester→reviewer 순차 호출
- `/start-work` → 전체 Gate 1~6 순차 실행 (자동 라우팅)

## Architecture
- **Backend**: FastAPI (Python 3.12) — `backend/`
- **Frontend**: React + Vite — `frontend-v2/` (port 5174)
- **LLM**: Google Gemini 3 Pro / 2.5 Flash — `workflow/ai.py`
- **CI/CD**: GitHub Actions + GitLab CI + Jenkins
- **Report Engine**: `report_gen/`, `generators/`

## Build & Test Commands
```bash
# Backend 테스트
python -m pytest tests/unit/ -q --tb=short

# Frontend 테스트
cd frontend-v2 && npm test

# Frontend 빌드
cd frontend-v2 && npm run build

# Backend 서버 실행
cd backend && uvicorn main:app --reload --port 9000

# Frontend 개발 서버
cd frontend-v2 && npm run dev

# 전체 테스트 (커버리지)
python -m pytest tests/ -v --cov=backend --cov=workflow --cov=report_gen --cov-report=html
```

## Code Style
- Python: 4-space indent, type hints, f-strings, isort import 순서
- JavaScript/JSX: 2-space indent, PascalCase components, camelCase functions
- 커밋 메시지: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`

## Key API Endpoints
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
- **`POST /api/swut/log-folder/preview`** — SwUT log_folder dry-run preview (38차)
- **`POST /api/swit/log-folder/preview`** — SwIT log_folder dry-run preview (38차)
- **`POST /api/file-mode/add-allowed-prefix`** — Cloudium allowed_prefixes 동적 추가 (39차, admin only 40차)
- **`POST /api/file-mode/remove-allowed-prefix`** — 동적 제거 (39차, admin only 40차)
- **`GET /api/file-mode/extra-prefixes`** — 영구 저장 prefixes 조회 (39차, admin only 40차)
- **`GET /api/auth/me`** — 현재 사용자 + is_admin (40차 신규, 공개)
- **`GET /api/auth/admins`** — admin list 조회 (40차 신규, admin only)

## SwUT Builder (Software Unit Test, 8~20차 라운드)

ISO 26262 ASIL A 단위테스트 산출물 자동 생성 + cross-validation 플랫폼.

### audit 자동화 현황 (Coverage Report v3.01 6시트, SUTR v3.01 5시트)
| 시트 | Coverage | SUTR |
|------|---------|------|
| Cover / Test Summary | ✓ meta 자동 | ✓ meta 자동 |
| 1.Traceability (TC×Function 매트릭스) | ✓ (7차) | N/A |
| **2.Consistency** (자체 일관성 + SwUDS 매핑) | **✓ 4 row + 옵션 5번째 (15~16차)** | **✓ 17차 대칭** |
| 3.Coverage | ✓ | N/A |
| Deviation / Test Log | N/A | ✓ |
| History (git log) | ✓ (6차) | ✓ |

### 입력 데이터 흐름
1. **Jenkins build cache 우선** — `collect_from_jenkins_cache(scan_jenkins_build_root)`
2. **log_folder fallback** — VectorCAST 결과 디렉토리 직접 파싱
3. **template** — 회사 v3.01 xlsx/xlsm template-copy 전략 (스타일/머지셀/매크로 보존)
4. **swuds_docx_path (옵션, 16차)** — python-docx로 SwUFn_NNNN heading 추출

### Cross-validation (18차, `swut_consistency_checker.py`)
- **uncovered_mismatch**: 미커버 Function ↔ 미실행 TC 일치성
- **exception_deviation**: Coverage Exception 합 ≥ SUTR Deviation TC 수
- **total_tc**: Coverage Traceability TC 수 == SUTR Total
- **final_result**: 'PASS' / 'OK' 표기 통일

### 메모리 / 동시성 (14차/17차/20차/31차)
- 14차 W1: `xlsx_io: BytesIO` lazy + StreamingResponse 64KB chunk → 메모리 1배 절감
- 17차: Semaphore(2) → (3) 상향 (worst 1.8MB×3=5.4MB)
- 20차: psutil 기반 메모리 모니터링 로그 (`mem_mb=...,delta=...`)
- **31차 W31**: 30차 c_source_root 도입 후 worst-case 갱신 — `parse_c_project` 동시 3건 추가 2.4MB×3=7.2MB. 총 worst-case ≈ **12.6MB** (5.4MB 빌드 + 7.2MB c_parser). 운영 안전 한도 내

### ISO 26262 Tool Qualification
모든 builder result에 `tool_qualification` 메타 포함:
- `evidence_class: "auto-generated draft"`
- `asil_a_usage: "reviewer 검토 후 evidence 사용 가능"`
- `asil_b_c_d_usage: "단독 evidence 사용 금지 — manual review 의무"`

### Frontend UI
- `SwUTBuildSection.jsx` (Detail.jsx 탭 `🧪 SwUT 빌드`)
- Form 입력 (project/release/date/log_folder/template/swuds) → Coverage/SUTR 빌드 → blob 다운로드
- 동일 페이지 하단 Consistency Check 섹션 (19차) — issues 카드 severity별 색상

### 입력 표면 매트릭스 (Pydantic, 13차+26차)
| 필드 | 검증 | Frontend Form (26차) |
|------|------|---------------------|
| release_sw_version | regex `^\d+\.\d+(\.\d+)?$` | ✓ 필수 |
| test_date / validation_date | regex `^\d{2,4}[-/]\d{1,2}[-/]\d{1,2}$` | ✓ (validation_date 26차 추가) |
| test_engineer | maxlen 100 + 줄바꿈 금지 | ✓ |
| reviewer_override / approver_override | maxlen 100 + 줄바꿈 금지 | **✓ 26차 W16 추가** |
| doc_id_sequence | digit only | ✓ |
| jenkins_build_number | ge=1 le=99999 | (옵션) |
| cache_root / log_folder / template_path / swuds_docx_path | maxlen 500 + 줄바꿈 금지 | ✓ (PathPickerDialog 21차, **swuds_docx_path는 32차 W28 ASIL 2차 source 추가**) |
| **c_source_root** | maxlen 500 + 줄바꿈 금지 | **✓ 30차 W21 추가 (PathPickerDialog + Doxygen @asil 추출 — 1차 ASIL source)** |
| deviation_cases | max_length=200 + 합산 256KB + item key ≤20 | (programmatic) |

### 함수별 ASIL 등급 (W21+W29+W28, 30~32차 완료)

**구현 완료 (30/31/32차 commit)**:
- `backend/services/swut_asil_resolver.py` (30차) — C 소스 → `function_id → ASIL` 매핑 (1차 source)
- `backend/services/swut_swuds_parser.py` (32차) — SwUDS docx 'ASIL' 라벨 → `function_asil_map` property (2차 source)
- 기존 자산: `workflow/code_parser/c_parser.py::parse_c_project` (Doxygen `@asil`) + `_extract_description_from_table` 패턴 재활용
- `SwUTBuildRequest.c_source_root` (30차) + `swuds_docx_path` (16차+32차) — PathPickerDialog 연동
- Coverage / SUTR builder `summary.asil_distribution` + `asil_b/c/d_function_ids` + `asil_highlight_policy` (대칭)
- 3.Coverage / SUTR Test Log 시트 ASIL B(파랑)/C(주황)/D(빨강) row 시각 강조 (31차 W29)
- Frontend `.swut-asil-distribution-panel` + B/C/D 강조 클래스 + audit 정책 공지 카드

**ASIL Source 우선순위 (32차 W28)**: `c_source_root` > `swuds_docx_path` > 없음. 충돌 시 c_source 우선 + parse_warnings에 사유 누적. 구현 truth (C 소스 @asil)가 설계 문서(SwUDS)보다 정확하다는 가정.

**사용자 결정 (A2, 30차)**: 1.Traceability 시트 자체 변경 없음 (회사 v3.01 양식 호환 100%). ASIL 정보는 summary + UI + 3.Coverage / SUTR Test Log 시트 강조로 표현.

**ISO 26262 적용**:
- ASIL D 함수 식별 → audit reviewer 즉시 인지 (MC/DC 커버리지 필수 안내)
- c_source_root 미제공 시 graceful skip + parse_warnings 명시 (이전 운영 호환)
- evidence_class "auto-generated draft" 정책 유지 — manual review 의무 동일

**비-목표 (31차+)**:
- 1.Traceability 시트 자체에 ASIL 컬럼 (양식 영향)
- SUTR Test Log에 함수 ID/ASIL 컬럼
- SwUDS docx에서 ASIL 추출 (현재 C 소스 단일 출처)
- ASIL B/C 함수 시각 강조 (본 라운드는 D만)

### 시각 강조 정책 (23/24/29/30/31차)

산출물 cell에 audit reviewer 친화 표시:

| 색상 RGB | 용도 | 헬퍼 |
|----------|------|------|
| 🟡 노란 `FFFFEB9C` | 사용자 입력 필요 | `mark_user_input_required` / `write_value_or_mark` |
| 🟦 파랑 `FFE2F0FF` (**31차 W29**) | 3.Coverage / SUTR Test Log — ASIL B 함수 row (분기 커버리지 필수) | `mark_asil_b_function` |
| 🟧 주황 `FFFFE5CC` (**31차 W29**) | 3.Coverage / SUTR Test Log — ASIL C 함수 row (MC/DC 권장) | `mark_asil_c_function` |
| 🔴 빨간 `FFFFC7CE` | 2.Consistency FAIL row Result 셀 | `mark_fail_cell` |
| 🔴 빨간 `FFFFC7CE` (동일 RGB, **30차 W21 의미 분리**) | 3.Coverage / SUTR Test Log — ASIL D 함수 row (MC/DC 필수) | `mark_asil_d_function` |
| 기본 (없음) | 자동 채움 (config/meta 정상) | `safe_write` / `_write_label` |

> **31차 W29 의미**: ASIL D > C > B 단계 색상으로 audit reviewer가 한눈에 검토 깊이 차이 인지. ASIL A/QM은 강조 없음 (구문 커버리지로 충분).

> **30차 W21 의미 분리**: `mark_fail_cell` ↔ `mark_asil_d_function` 색상 RGB 동일 (`FFFFC7CE`)이나 호출 의미 다름. FAIL = TC 실행 실패, ASIL D = audit 검토 우선순위. 동일 셀 겹치면 ASIL D 우선 (호출 순서 보장). audit reviewer에게 정책 사전 통보 권장.

24차 silent "N/A" 제거 — Actual Coverage/Pass ratio가 data 부재 시 `▶ 사용자 입력 필요 — VectorCAST 데이터 부재 — log_folder 재확인` 명시 (deep-reviewer X7 강화).

### Design Token 단일 출처 (29차 W17)

**Backend RGB / placeholder 단일 출처**: `backend/services/design_tokens.py`
- `USER_INPUT_FILL_RGB = "FFFFEB9C"` — Excel 셀 노란 배경
- `FAIL_FILL_RGB = "FFFFC7CE"` — Excel 셀 빨간 배경 (TC 실행 실패)
- `ASIL_D_FILL_RGB = "FFFFC7CE"` — **30차 W21 동일 값 / 의미 분리 (audit MC/DC 우선순위)**
- `ASIL_C_FILL_RGB = "FFFFE5CC"` — **31차 W29 연한 주황 (MC/DC 권장)**
- `ASIL_B_FILL_RGB = "FFE2F0FF"` — **31차 W29 연한 파랑 (분기 커버리지 필수)**
- `USER_INPUT_PLACEHOLDER = "▶ 사용자 입력 필요"` — 24차 silent "N/A" 대체 안내

`excel_template_utils.py`가 위 모듈에서 import — 이전 (23~28차) module-level hardcoded 제거. 신규 backend Excel builder는 반드시 `design_tokens`에서 import.

**Backend ↔ Frontend 색상 컨텍스트 매트릭스 (의도된 분리)**:

| 컨텍스트 | 출처 | 용도 |
|----------|------|------|
| Backend Excel 셀 배경 | `design_tokens.py` `USER_INPUT_FILL_RGB`/`FAIL_FILL_RGB`/`ASIL_D_FILL_RGB` (warm pastel — `#FFEB9C`/`#FFC7CE`) | audit reviewer 친화 부드러운 hint |
| Frontend UI 텍스트/badge | `frontend-v2/src/index.css` `--color-warning`/`--color-danger` (Tailwind amber-500/red-500) | UI 시인성 — 명도/대비 강함 |
| **Frontend ASIL D audit (30차 W21)** | `--audit-asil-d-soft` (`#ffe3e8`) / `--audit-asil-d-text` (`#b3261e`) | ASIL 분포 패널에서 ASIL D 항목 강조 — Excel 빨강과 의미 매칭하되 UI 시인성 조정 |

**중요**: 두 컨텍스트는 **단일 RGB로 통합하지 말 것**. Excel 셀 배경(부드러운 톤)과 React UI 텍스트(시인성)는 다른 색상 요구. design tokens는 같은 audit 의미를 가지지만 시각적 구현은 컨텍스트마다 적합한 톤 사용.

**변경 시 동기 정책**: backend `design_tokens.py` RGB 변경 시 본 CLAUDE.md 섹션 + audit reviewer 통보 의무 (산출물 시인성 정책 영향).

> **Backward 호환 (W22, 28차 명시)**: 24차 이전 빌드 결과물은 동일 셀에 string `"N/A"` 보유. 회사 audit reviewer가 두 형식 모두 인지하도록 산출물에 라운드(24차+) 표기를 Cover 시트 doc_id_sequence에 포함 권장. 자동 변환/마이그레이션 스크립트는 제공 안 함 — 이전 산출물은 그대로 둘 것. 신규 빌드부터 노란 마킹 적용.

### Workflow & Tests (33차 갱신 — 실측)
- Backend SwUT 전체 회귀: **~301개** (31-fix +5 / 32차 W28 +8)
- Backend SwIT 회귀: **65개** (33차 25 + 34차 28 + 35차 5 + 36-fix 7 — `_extract_env_from_filename` SwIT prefix)
- Backend 37차 신규: **+7** (`TestResolveLatestReleaseFolder`: Case A/B/C + non-release skip + missing-subfolder skip + W1 mixed suffix + W2 silent fallback)
- Backend 38차 신규: **+21** (helpers 3 + safety 9 + preview 4 + edge case 3 (1 skip) + C2 cloudium 2)
- Backend 39차 신규: **+20** (cloudium_extra_prefixes 11 + file_mode_router 9 — add/remove/list × cloudium-only/normal/duplicate/422)
- Backend 40차 신규: **+57** (admin_users 12 + auth_router 6 + admin_gate 39 parametrize 13 endpoint × 3)
- Backend 41차 신규: **+4** (bootstrap_from_env env handling 4 시나리오)
- Backend 42차 신규: **+9** (bootstrap +1 _mask_user + error_handler_nested 7 + admin_gate +0)
- Backend 전체: **1965~1968개** (.venv Python 3.12.6 — 1956 → ~1968 +9~12, 회귀 진행 중)
- Frontend AdminContext: **7개** (40차 4 + 41차 1 + 42차 +2 debounce/retry)
- Frontend 전체: **242개** (240 → 242 +2)
- Frontend SwUTBuildSection: **26개**
- Frontend 전체: **220개** (23 test files)

### 30차 W21 deep-reviewer Critical/Warning fix (commit 진행 의무)
- **Critical (X5/S3 path traversal)**: `swut_asil_resolver` 에 시스템 디렉토리 blacklist (Windows: `C:/Windows`, `Program Files`, POSIX: `/etc`, `/root`, `/sys`, `/proc` 등) 추가 — `allowed_roots` 미지정해도 backstop으로 거부. ISO 26262 audit 도구 보안 경계.
- **Warning (X3 헤더 truncate)**: `_build_result_to_response`에서 `X-SwUT-Summary` 1024B 초과 시 `asil_d_function_ids` list를 길이 sentinel string으로 축약 + JSON valid 보장 fallback. frontend silent 미표시 회피.
- **Info (색상 충돌)**: `mark_asil_d_function` ↔ `mark_fail_cell` 동일 RGB이나 시트 분리 (3.Coverage = ASIL D 전용, 2.Consistency = FAIL 전용) — docstring + 본 CLAUDE.md 정책에 명시. 동일 시트 두 강조 동시 시 fix.
- Cloudium worker는 read-only — 절대 cloudium 파일 생성/수정 금지 (사용자 의사결정)
- 라이브 검증 PoC: `.codex_tmp/poc_live_full_verification.py` (maintained, 사용자 환경에서 직접 호출)

> **회귀 카운트 측정 명령** (정확치 재확인 시):
> ```bash
> # .venv Python 3.12 권장 (운영 환경 동일). msys64 mingw Python은 os.sep='/' quirk 주의.
> .venv/Scripts/python.exe -m pytest tests/unit/test_swut_*.py tests/unit/test_excel_template_utils.py --collect-only -q | tail -3
> cd frontend-v2 && npx vitest run src/__tests__/SwUTBuildSection.test.jsx --reporter=basic
> ```
> 27차까지 "~260개" 표기는 부정확 — 28차 실측 220개, 29차 design_tokens 회귀 +1, 30차 prep W25 fix로 환경 무관 221개.

### Backend Reload 절차 (26차 C6 명시)

backend 코드 변경 (`backend/services/`, `backend/routers/`, `backend/schemas.py` 등)
후에는 **반드시 backend 재시작 필요** — uvicorn에 `--reload` 옵션이 없으면 stale
코드가 호출되어 PoC / endpoint 결과가 신규 변경 반영 안 됨.

#### 절차
1. **재시작 방식 (권장)**: 기존 backend 종료 (Ctrl+C 또는 작업 관리자) →
   `cd backend && uvicorn main:app --reload --port 9000` (개발 모드 `--reload` 권장)
2. **포트 충돌 시**: `netstat -ano | findstr 9000` → PID 확인 → 종료
3. **Cloudium 모드 stuck 방지**: PoC 종료 시 항상 `_restore_local_mode()` finally
   (22차 T188 패턴). cloudium 모드 + worker 미실행 시 모든 read 403

#### 변경 영향 매트릭스
| 변경 영역 | reload 필요? |
|----------|-------------|
| `backend/services/*.py` | ✅ 필수 |
| `backend/routers/*.py` | ✅ 필수 |
| `backend/schemas.py` | ✅ 필수 (Pydantic schema cache) |
| `backend/main.py` | ✅ 필수 |
| `config/swut_meta.json` | 12차 lru_cache + mtime invalidate — **자동** |
| `frontend-v2/src/*` | ❌ Vite HMR (자동) |
| `.codex_tmp/poc_*.py` | ❌ 매 실행 새 process |

## SwIT Builder (Software Integration Test, 33~35차 라운드~)

ISO 26262 ASIL B+ 통합 테스트 산출물 자동 생성. SwUT 30~32차 인프라 **81% 재활용**.

### 33차 — Coverage Report v2.02 (xlsx)
- 회사 v2.02 양식 (HDPDM01 NE_GN7). 시트 구조: Cover / Test Summary / 1.Traceability / 2.Consistency / 3.Coverage / History (SwUT v3.01과 동일)
- 입력: VectorCAST log (`U:\...\08.SW 통합테스트\03.Test Result\01.Log\v<VER>_<DATE>\`)
- ASIL source: c_source_root + swuds_docx_path (SwUT 32차 W28 정책 동일 — c_source 우선)
- 파일명: `(HDPDM01)SwIT Coverage Report_v<VER>_<DATE>_R.xlsx`

### 34차 — SITR v2.02 (xlsm, keep_vba=True)
- 회사 v2.02 양식 (HDPDM01_SITR NE_GN7). 시트 구조: Cover / Test Summary / Deviation / Test Log / (옵션) 2.Consistency / History (SwUT SUTR v3.01과 동일)
- 입력: Coverage와 동일 (log_folder / c_source_root / swuds_docx_path)
- 31차 W27 ASIL col+4/5 시각 강조 정책 SUTR과 대칭 — Test Log row ASIL B(파랑)/C(주황)/D(빨강)
- 파일명: `(HDPDM01_SITR) Software Integration Test Result_v<VER>_<DATE>_R.xlsm`
- VBA 매크로 보존 (keep_vba=True) — 실 실행 검증은 사용자 의무 (deep-reviewer W2)
- `deviation_cases` body 필드 (SwUT 13차 C3 정책 동일 — 256KB / item key ≤ 20)
- Semaphore 공유 (Coverage와 동일 instance, capacity 2)

### 재활용 자산 (33/34차 합산 ≥85%)

| 자산 | 33차 활용 (Coverage) | 34차 활용 (SITR) |
|------|---------------------|------------------|
| `swut_input_adapter` SwUTSession / aggregate_session | `swit_input_adapter.collect_swit_session` thin wrapper | 동일 |
| `swut_coverage_aggregator._compute_asil_distribution` / `_compute_self_consistency` / `_write_history_sheet` / `_write_consistency_sheet` | 시트 writer 6개 import | History + Consistency import |
| `swut_sutr_aggregator._write_cover` / `_write_test_summary` / `_write_deviation` / `_write_test_log` | (Coverage는 별도 writer) | **시트 writer 4개 import** |
| `excel_template_utils` (safe_write / mark_asil_* / has_vba_macros / inspect_vba_refs) | 일반 목적 | 일반 목적 + VBA 검사 |
| `swut_asil_resolver` + `swut_swuds_parser` | ASIL 매핑 동일 | 동일 |
| `swut.py` Semaphore / StreamingResponse / X-* 헤더 패턴 | `routers/swit.py` Coverage endpoint | SITR endpoint도 Semaphore 공유 |

### SwIT 도구별 차이 (SwUT 대비)
- 신규 `swit_meta.SwitCoverageBuildMeta` (`doc_id_base="HDPDM01-SwIT"`, default `asil_level="ASIL B"`)
- 신규 `swit_meta.SwitSitrBuildMeta` (`SutrBuildMeta` 상속, `doc_id_base="HDPDM01-SITR"`, `final_test_result="OK"`)
- 신규 `SwITBuildRequest` + `SwITSitrBuildRequest` Pydantic (SwUT 17 필드 동일 + ASIL B default, SITR은 `deviation_cases` 추가)
- 신규 endpoint:
  - `/api/swit/coverage/build` (xlsx)
  - `/api/swit/sitr/build` (xlsm, keep_vba)
  - Semaphore(**2**) 공유 (SwUT 3 — SwIT 신규라 보수적)
- X-SwIT-Summary / X-SwIT-Warnings 헤더 (SwUT와 분리)

### 35차 — Consistency Checker + Frontend SwITBuildSection
- **Backend** `backend/services/swit_consistency_checker.py` — SwUT `check_swut_consistency` thin wrapper. `tc_prefix="SwITC"` 전달로 SwUT 18차 인프라 재활용
- **Backend** `swut_consistency_checker.py`에 `tc_prefix` kwarg 도입 (default "SwUTC", SwIT는 "SwITC"). `_extract_coverage_summary` / `_extract_sutr_summary` / `_collect_tc_to_function` 3 곳 동적 regex로 변경. SwUT 회귀 영향 없음
- **Backend** `/api/swit/consistency/check` endpoint — SwUT `_run_consistency_safely` 패턴 차용, Semaphore 미적용 (read-only)
- **Frontend** `frontend-v2/src/components/sections/SwITBuildSection.jsx` (신규, ~430 lines) — SwUTBuildSection 패턴 차용. 3 섹션: Coverage 빌드 / SITR 빌드 / Coverage↔SITR consistency 검증. localStorage 키 `devops_v2_swit_form` (SwUT와 분리). X-SwIT-Summary/Warnings 헤더
- **Frontend** Detail.jsx에 SwIT 빌드 탭 추가 (icon 🧩, id 'swit')
- 회귀: backend +5 / frontend +8

### 34차 deep-reviewer C1/C2/C3 fix (commit 포함)
- **C1 (Critical X3)**: `_collect_tc_to_function` `.match` → `.search`로 변경 (SwIT TC prefix `SwITC_` 호환 — 이전 항상 FAIL → 정상 매칭). `swut_coverage_aggregator.py:378`
- **C2 (Critical X3)**: `_compute_self_consistency` + `_write_consistency_sheet`에 `test_kind: str = "SwUTS"` kwarg 추가. SwIT 호출 시 `test_kind="SwIT"` 전달 — intro 텍스트 + row 5 item label 동적 치환 (이전: SwUTS 하드코딩이 SwIT 산출물에 그대로 기록되어 audit reviewer 혼동)
- **C3 (Critical X6)**: SwIT v2.02 양식 ASIL 시각 강조 사전 통보 — 31차 W29 색상 정책 (B 파랑 #E2F0FF / C 주황 #FFE5CC / D 빨강 #FFC7CE)이 SwIT 산출물에도 적용됨. **회사 v2.02 SITR 양식이 빨강만 표준이라 추가 색상은 비표준 audit 확장**. 라이브 PoC 검증 시 회사 audit reviewer에 사전 통보 의무
- **W2 (Warning X4)**: SwIT SITR이 `_write_cover` / `_write_test_summary` / `_write_deviation` / `_write_test_log` private 함수 강결합. 향후 SwUT SUTR signature 변경 시 SwIT 회귀에서 자동 감지 위해 `__all__` 명시 또는 public alias 추가는 35차+ 정비 후보

### 라운드 archive (36-fix ~ 42차)

> **44차 W21**: 36-fix ~ 42차 상세 노트는 [`docs/rounds/sw_test_round_history.md`](docs/rounds/sw_test_round_history.md) 분리 (본문 비대화 해소).

| 라운드 | 주제 | 회귀 (backend) |
|--------|------|---------------|
| 36-fix | SwIT log filename `SwITC_` prefix 지원 (Critical) | 1842 → 1849 (+11) |
| 37차 | log_folder 자동 latest release 선택 | 1849 → 1854 (+7) |
| 38차 | DRY/`__all__`/dry-run preview/`_safety` 통합 | 1854 → 1875 (+21) |
| 39차 | Cloudium 동적 allowed_prefixes + PathPickerDialog UX | 1875 → 1895 (+20) |
| 40차 | Backend Admin Role 시스템 (A안: 전체 admin only) — 보안 강화 | 1895 → 1952 (+57) |
| 41차 | Bootstrap admin + APIRouter deps + visibility refresh | 1952 → 1956 (+4) |
| 42차 | error_handler nested + mask_user + retry + debounce | 1956 → 1968 (+12) |

### 44차 — 43차 자체 평가 발견 결함 4건 통합 fix (W21/W25/W28/I3)
- 43차 commit `c577aa0` 자체 비판 평가에서 발견한 자체 해결 가능 4건. C1 JWT는 45차+ 별도 큰 라운드.
- **W21 CLAUDE.md archive 분리**: 본문 1500+ → ~550 lines 압축. 36-fix~42차 상세 노트를 [`docs/rounds/sw_test_round_history.md`](docs/rounds/sw_test_round_history.md)로 분리. 본문에는 라운드 summary table + archive 링크. 33-35차 핵심 정책 + 43차/44차 (최신) 본문 유지.
- **W25 act() warning 정리**: AdminContext.test.jsx의 W4 retry / W20 unmount 회귀에서 `render()` + `vi.waitFor` 호출을 `await act(...)` wrap — vitest stderr act warning 0건 (이전: 2건 출력).
- **W28 error_handler falsy message 분리**: `detail.get("message")`가 `None` / `""` / falsy 모두 status-aware fallback (`HTTP <status> error`) 사용. 의도된 빈 message 노출 차단. 회귀 +2 (`test_dict_with_empty_string_message` + `test_dict_with_none_message`).
- **I3 _mask_user deprecation warning**: `_mask_user` alias를 단순 변수 alias → `DeprecationWarning` 발화 wrapper 함수로 전환. `stacklevel=2`로 호출 지점 정확 표시. 45차+ 완전 제거 검토.
- 회귀: backend 1970 → 1972 (+2 W28 empty_string + none_message) + bootstrap +1 (I3 deprecation) = +3 / frontend 243 → 243 (W25 동작 변경 없이 stderr 정리만)

### 43차 — 42차 자체 평가 발견 결함 4건 통합 fix (W19/W20/W23/W24)
- 42차 commit `1fa4692` 자체 비판 평가에서 발견한 자체 해결 가능 4건. C1 JWT는 44차+ 별도 큰 라운드.
- **W19 mask_user public 승격**: `_mask_user` (private, 42차) → `mask_user` (public, `__all__` 등록). `dependencies/admin.py`가 underscore private 함수 import하는 convention 위반 해결. `_mask_user = mask_user` alias로 backward-compat 유지.
- **W20 StrictMode safe**: AdminContext.jsx에 `isMountedRef` 도입 — fetch 응답/retry timer fire가 unmount 후 setState 호출 시 React warning. 모든 setState 직전 `isMountedRef.current` 확인 + 매 mount마다 `true` 복원 (StrictMode 두 번째 mount 대응). 회귀에서 unmount 후 timer fire 시 "unmounted" warning 발생 안 함 검증.
- **W23 frontend 회귀 실행 검증**: 42차에 미실행한 vitest 전체 회귀 실 실행 (242 → 243 +1 W20). backend admin/auth 57건 통과 (W19 mask_user 영향 회귀).
- **W24 error_handler 빈 dict fallback**: `HTTPException(detail={})` 또는 code만 있고 message 누락 시 `str(detail)` (= "{}") 노출되어 사용자 혼란 → status-aware fallback `HTTP <status> error` 사용. 회귀 +1 (`test_dict_with_only_code_no_message`).
- 회귀: backend 1968 → 1970 (+1 W24 dict_with_only_code + empty_dict 갱신 +1 mask_user alias 검증 보강) / frontend 242 → 243 (+1 W20 StrictMode race) / backend admin gate 57건 무회귀

## Admin 운영 가이드 (40~41차)

| 시나리오 | 방법 |
|---------|------|
| 첫 admin 등록 | `.env`에 `BOOTSTRAP_ADMIN_USERS=user1,user2` 추가 → backend 가동 시 자동 |
| admin 추가 | admin이 `config/admin_users.json` 직접 편집 (mtime invalidate로 자동 반영) |
| admin 제거 | 동일 — json 편집 |
| Lockout 회복 | `config/admin_users.json` 수동 편집 + `.env` `BOOTSTRAP_ADMIN_USERS` 설정 + backend 재기동 |
| Frontend admin 모드 표시 | `Ctrl+Shift+A` 키보드 토글 또는 Settings 페이지 AdminSection |
| 권한 동기화 | AdminContext가 `/api/auth/me` 호출 — 탭 visible 시 자동 refresh (41차) |
| 13 endpoint 보호 | SwIT 4 + SwUT 5 + file-mode 4 — 라우터 또는 endpoint dependency로 admin only |

## Workflows (워크플로우 — 자동 연결)
- `/workflow [기능설명]` — **전체 개발 흐름**: 기획→코드→테스트→리뷰→커밋 자동 실행
- `/hotfix [버그설명]` — **긴급 수정**: 분석→수정→테스트→커밋 빠른 처리
- `/doc-pipeline [all|uds|sts|suts|sits|delta]` — **문서 생성**: UDS→STS→SUTS→SITS 순차 자동 생성

## Individual Skills (개별 도구)
- `/plan` — 기획만
- `/dev` — 코드 작성만
- `/test-run` — 테스트만
- `/deploy` — 배포만
- `/health-check` — 상태 점검
- `/impact` — 영향도 분석
- `/devops-release:doc-gen` — 단일 문서 생성 (플러그인)
- `/devops-release:review` — 코드 리뷰 (플러그인)

## MCP Tools (devops-release 서버)

### 읽기 도구
- `report_summary`, `report_findings`, `report_coverage`, `report_log` — 빌드/테스트 리포트 분석 (TTL 캐싱 내장)
- `git_status`, `git_diff`, `git_log`, `git_changed_files` — Git 상태 조회
- `search_code` (ripgrep 통합, `file_glob`/`exclude_glob` 필터 지원), `read_source_file` — 코드 검색/읽기
- `list_docs`, `search_docs`, `read_doc` — 문서 검색/열기
- `jenkins_build_summary`, `jenkins_build_status` — Jenkins 빌드 캐시 분석
- `health_check` — MCP 서버 5개 상태 확인

### 쓰기 도구
- `git_stage_files` — 파일 스테이징 (경로 검증 내장)
- `write_file` — 파일 쓰기 (.env 금지, project_root 하위만)
- `replace_in_file` — 파일 내 텍스트 교체
- `clear_report_cache` — 리포트 캐시 초기화

### MCP Resources / Prompts
- Resources: `git://repo/status`, `git://repo/diff`, `git://repo/log`, `git://repo/changed-files`, `docs://index`
- Prompts: `triage_build_failure`, `summarize_change_risk`, `review_coverage_gap`

## Hooks (자동 품질 게이트)
- **SessionStart**: `.env` 자동 생성 (.env.example → .env) + settings 변경 정책 reminder
- **PreToolUse**: C/H 파일 수정 시 ASIL C/D 태그 감지 → 경고
- **PostToolUse**: 단일 dispatcher (`scripts/posttool_dispatch.py`) — Python syntax+ruff, JSX/TS ESLint, .md broken-link/heading-jump, workflow/report_gen 변경 시 관련 pytest
- **PostToolBatch** (신규, 2026-05-11): 병렬 Write/Edit 일괄 종료 시 `scripts/posttoolbatch_report.py` — 변경 파일 집계 + CLAUDE.md L106 능동 보고 X1~X8 trigger 메시지를 메인 응답에 push. **단일 파일 turn은 silent** (PostToolUse가 이미 파일별 보고), 단 ASIL C/H는 단독이어도 hint 출력. ASIL 파일은 list 앞으로 정렬되어 truncation 시에도 누락되지 않음. 출력은 `ensure_ascii=False`로 한글 가독성 유지. **메인 에이전트의 능동 보고 의무는 그대로 유지** (hook은 보조 알림이며 대체 아님)
- **Stop**: `scripts/quality_check.py` 단일 호출 (이전 `stop_check.py` fallback 사슬 제거됨)
- **PreCompact**: git status + diff stat을 `.codex_tmp/precompact_context.json`에 저장 (출력은 schema 정합 `systemMessage` 형식)

## Gate 간 데이터 전달 프로토콜
`/workflow` 실행 시 각 Gate에서 TaskCreate description에 구조화된 데이터를 포함:
- **planner→architect**: affected_files, safety_impact(ASIL), priority
- **architect→coder**: interface_spec, data_flow, design_decisions
- **coder→tester**: changed_files, test_hints, safety_level
- **tester→reviewer**: test_results, coverage_delta, safety_tests

## Important Paths
- 요구사항 문서: `D:/Project/devops/260105/docs/`
- 소스코드: `D:/Project/Ados/PDS64_RD/`
- 캐시: `.devops_pro_cache/`
- 환경설정: `.env` (절대 커밋 금지)

### SwUT 관련 path (사용자 환경 의존 — W23, 28차 추가)
- VectorCAST log 디렉토리 (`log_folder`): 예) `U:/연구소/.../HDPDM01/.../vectorcast/results/` — Cloudium worker(read-only)로 접근
- 회사 v3.01 template (`template_path`): 예) `U:/연구소/.../양식/(HDPDM01)Coverage_Report_v3.01.xlsx`, `(HDPDM01)SUTR_v3.01.xlsm`
- SwUDS docx (`swuds_docx_path`, 옵션): 예) `U:/연구소/.../(HDPDM01)SwUDS_v3.docx`
- SwUT meta config: `config/swut_meta.json` (lru_cache + mtime invalidate, 12차)
- 산출물 임시 디렉토리 (PoC 산출물 검수용): `.codex_tmp/live_full_2026_05_12/` (gitignore)
- localStorage form 보존 key: `devops_v2_swut_form` (frontend)
- localStorage 사용자 식별: `devops_v2_user` (USER_KEY)

> 실 경로는 라이센스/보안상 사용자 환경에서만 유효 — 위 예시는 표기 패턴이며 git에 commit 금지.

## SCM Credential Resolution (Jenkins sync)
- **절대 HTTP body로 password를 받지 않음** — env 또는 registry에서만 해결
- 우선순위: `scm_id` → `repo_url` 매칭 → entry의 `scm_password_env` → 전역 `DEVOPS_SCM_PASSWORD`
- `scm_password_env`는 shell identifier 패턴만 허용하고 `PATH`/`HOME` 등 시스템 변수 블랙리스트
- Docker 이미지는 `subversion` 포함(Dockerfile), 호스트 SVN auth 캐시 없음 → env 주입 필수
- 체크아웃 완료 시 `source/.source_complete` 센티널 기록, 이 파일 기준으로만 캐시 재사용
- 강제 재 sync: `/api/jenkins/sync` 요청에 `force: true`
