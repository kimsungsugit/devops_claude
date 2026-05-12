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

### 메모리 / 동시성 (14차/17차/20차)
- 14차 W1: `xlsx_io: BytesIO` lazy + StreamingResponse 64KB chunk → 메모리 1배 절감
- 17차: Semaphore(2) → (3) 상향 (worst 1.8MB×3=5.4MB)
- 20차: psutil 기반 메모리 모니터링 로그 (`mem_mb=...,delta=...`)

### ISO 26262 Tool Qualification
모든 builder result에 `tool_qualification` 메타 포함:
- `evidence_class: "auto-generated draft"`
- `asil_a_usage: "reviewer 검토 후 evidence 사용 가능"`
- `asil_b_c_d_usage: "단독 evidence 사용 금지 — manual review 의무"`

### Frontend UI
- `SwUTBuildSection.jsx` (Detail.jsx 탭 `🧪 SwUT 빌드`)
- Form 입력 (project/release/date/log_folder/template/swuds) → Coverage/SUTR 빌드 → blob 다운로드
- 동일 페이지 하단 Consistency Check 섹션 (19차) — issues 카드 severity별 색상

### 입력 표면 매트릭스 (Pydantic, 13차)
| 필드 | 검증 |
|------|------|
| release_sw_version | regex `^\d+\.\d+(\.\d+)?$` |
| test_date / validation_date | regex `^\d{2,4}[-/]\d{1,2}[-/]\d{1,2}$` |
| test_engineer / reviewer / approver | maxlen 100 + 줄바꿈 금지 |
| doc_id_sequence | digit only |
| jenkins_build_number | ge=1 le=99999 |
| cache_root / log_folder / template_path / swuds_docx_path | maxlen 500 + 줄바꿈 금지 |
| deviation_cases | max_length=200 + 합산 256KB + item key ≤20 |

### Workflow & Tests
- Backend SwUT 전체 회귀: ~240개 (test_swut_*.py + test_excel_template_utils.py)
- Frontend SwUTBuildSection: 16개 (vitest)
- Cloudium worker는 read-only — 절대 cloudium 파일 생성/수정 금지 (사용자 의사결정)

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

## SCM Credential Resolution (Jenkins sync)
- **절대 HTTP body로 password를 받지 않음** — env 또는 registry에서만 해결
- 우선순위: `scm_id` → `repo_url` 매칭 → entry의 `scm_password_env` → 전역 `DEVOPS_SCM_PASSWORD`
- `scm_password_env`는 shell identifier 패턴만 허용하고 `PATH`/`HOME` 등 시스템 변수 블랙리스트
- Docker 이미지는 `subversion` 포함(Dockerfile), 호스트 SVN auth 캐시 없음 → env 주입 필수
- 체크아웃 완료 시 `source/.source_complete` 센티널 기록, 이 파일 기준으로만 캐시 재사용
- 강제 재 sync: `/api/jenkins/sync` 요청에 `force: true`
