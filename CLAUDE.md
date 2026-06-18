# DevOps Release Claude - Automated Document Generation Platform

C 소스코드 + 요구사항 문서(SRS/SDS)로부터 설계/시험 규격서(UDS, STS, SUTS, SITS)를 자동 생성하는 DevOps 플랫폼.

> **문서 구성 (분기 맵)** — 이 CLAUDE.md는 코어 정책만 담고, 나머지는 분기되어 있다:
> - **항상 로드** (`@import` — 실제 로드 트리거는 §운영·검토 정책의 `@` 라인, 아래 링크는 가독용): [자율 운영 규칙](.claude/rules/autonomous-operation.md) · [작업 종료 비판적 검토](.claude/rules/self-review.md)
> - **코드 편집 시 자동 로드** (nested): [`backend/services/CLAUDE.md`](backend/services/CLAUDE.md) — 빌더 하드 제약
> - **필요 시 직접 열람** (on-demand 링크, 아래 "참조 문서 (on-demand)" 섹션):
>   빌더 상세 / 엔드포인트 / 시각강조·토큰 / admin 운영 / 라운드 history
>
> 정책 갱신 시: always-on 규칙은 `.claude/rules/*.md`, 기능 상세는 `docs/builders/*.md`에 기재할 것.

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

## 운영·검토 정책 (always-on import)

아래 두 모듈은 세션 시작 시 항상 로드되며 매 작업에 적용된다. 상세는 링크된 파일 본문 참조.

@.claude/rules/autonomous-operation.md

@.claude/rules/self-review.md

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
- `/start-work` → 전체 Gate 1~6 순차 실행 (planner→coder→tester→reviewer 자동 라우팅)

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

## Workflows (워크플로우 — 자동 연결)
- `/start-work [작업설명]` — **전체 개발 흐름**: 계획→설계→구현→테스트→리뷰→문서화 (Gate 1~6 자동 라우팅)
- `/hotfix [버그설명]` — **긴급 수정**: 분석→수정→테스트→커밋 빠른 처리
- `/doc-pipeline [all|uds|sts|suts|sits|delta]` — **문서 생성**: UDS→STS→SUTS→SITS 순차 자동 생성

## Individual Skills (개별 도구)
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
- **SessionStart**: `.env` 자동 생성 (.env.example → .env) + git hooks 자동 활성화 (`scripts/install_git_hooks.sh`) + settings 변경 정책 reminder
- **PreToolUse**: C/H 파일 수정 시 ASIL C/D 태그 감지 → 경고
- **PostToolUse**: 단일 dispatcher (`scripts/posttool_dispatch.py`) — Python syntax+ruff, JSX/TS ESLint, .md broken-link/heading-jump, workflow/report_gen 변경 시 관련 pytest
- **PostToolBatch** (신규, 2026-05-11): 병렬 Write/Edit 일괄 종료 시 `scripts/posttoolbatch_report.py` — 변경 파일 집계 + 능동 보고 X1~X8 trigger 메시지를 메인 응답에 push. **단일 파일 turn은 silent** (PostToolUse가 이미 파일별 보고), 단 ASIL C/H는 단독이어도 hint 출력. ASIL 파일은 list 앞으로 정렬되어 truncation 시에도 누락되지 않음. 출력은 `ensure_ascii=False`로 한글 가독성 유지. **메인 에이전트의 능동 보고 의무는 그대로 유지** (hook은 보조 알림이며 대체 아님)
- **Stop**: `scripts/quality_check.py` 단일 호출 (이전 `stop_check.py` fallback 사슬 제거됨)
- **PreCompact**: git status + diff stat을 `.codex_tmp/precompact_context.json`에 저장 (출력은 schema 정합 `systemMessage` 형식)

## Gate 간 데이터 전달 프로토콜
`/start-work` 실행 시 각 Gate에서 TaskCreate description에 구조화된 데이터를 포함:
- **planner→architect**: affected_files, safety_impact(ASIL), priority
- **architect→coder**: interface_spec, data_flow, design_decisions
- **coder→tester**: changed_files, test_hints, safety_level
- **tester→reviewer**: test_results, coverage_delta, safety_tests

## Important Paths
- 요구사항 문서: `D:/Project/devops/260105/docs/`
- 소스코드: `D:/Project/Ados/PDS64_RD/`
- 캐시: `.devops_pro_cache/`
- 환경설정: `.env` (절대 커밋 금지)
- SwUT/SwIT 빌더 관련 사용자 환경 의존 path: [`docs/builders/swut_builder.md`](docs/builders/swut_builder.md) `## SwUT 관련 path` 참조

## SCM Credential Resolution (Jenkins sync)
- **절대 HTTP body로 password를 받지 않음** — env 또는 registry에서만 해결
- 우선순위: `scm_id` → `repo_url` 매칭 → entry의 `scm_password_env` → 전역 `DEVOPS_SCM_PASSWORD`
- `scm_password_env`는 shell identifier 패턴만 허용하고 `PATH`/`HOME` 등 시스템 변수 블랙리스트
- Docker 이미지는 `subversion` 포함(Dockerfile), 호스트 SVN auth 캐시 없음 → env 주입 필수
- 체크아웃 완료 시 `source/.source_complete` 센티널 기록, 이 파일 기준으로만 캐시 재사용
- 강제 재 sync: `/api/jenkins/sync` 요청에 `force: true`

## 참조 문서 (on-demand)

아래 문서는 자동 로드되지 않는다. 해당 영역 작업 시 직접 열람할 것.

| 문서 | 언제 읽나 |
|------|----------|
| [`docs/api/key-endpoints.md`](docs/api/key-endpoints.md) | API endpoint 추가/변경 시 — 전체 endpoint 목록 |
| [`docs/builders/swut_builder.md`](docs/builders/swut_builder.md) | SwUT 빌더 작업 시 — `backend/routers/swut.py`·`backend/services/*`, frontend-v2 SwUT 탭(`SwUTBuildSection.jsx`) 편집 포함 (X-SwUT-Summary truncation 계약은 §Frontend UI) |
| [`docs/builders/swit_builder.md`](docs/builders/swit_builder.md) | SwIT 빌더 작업 시 — `backend/routers/swit.py`, frontend-v2 SwIT 탭(`SwITBuildSection.jsx`) 편집 포함 + 36-fix~58차 라운드 archive |
| [`docs/builders/swreport_summary.md`](docs/builders/swreport_summary.md) | 전 레벨 통합 Summary(ES95411) 빌더 작업 시 — `backend/routers/swreport.py`·`swreport_summary_aggregator.py`, frontend-v2 통합 정리 탭(`SwReportSummarySection.jsx`). 레벨별 산출물 → 마스터 Summary roll-up |
| [`docs/builders/visual-marking-and-design-tokens.md`](docs/builders/visual-marking-and-design-tokens.md) | 산출물 셀 시각 강조 / Excel RGB / design_tokens 변경 시 |
| [`docs/admin-operations.md`](docs/admin-operations.md) | admin 등록/회복/권한 endpoint 작업 시 |
| [`docs/rounds/sw_test_round_history.md`](docs/rounds/sw_test_round_history.md) | 36-fix~ 라운드 상세 노트 |
| [`docs/rounds/auth_operations.md`](docs/rounds/auth_operations.md) | JWT 생성/회복/검증 상세 운영 |
