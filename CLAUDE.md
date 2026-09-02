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

### 추적성 체인 (ISO 26262 V-model — 좌 설계 ↔ 우 검증, 수평쌍)
```
SyRS (시스템 요구)        ─────►  SyTS  (시스템 시험)
HSIS (HW-SW 인터페이스)   ─────►  SyITS (시스템 통합시험)
SDS  (SW 아키텍처 설계)   ─────►  SITS  (SW 통합시험)
UDS  (단위 상세 설계)     ─────►  SUTS  (SW 단위시험)
Source (소스코드)         ─────►  VectorCAST (실행 결과)
```
- SW 요구(SRS/SwRS)는 추적 허브(요구사항 행) — STS(SW 요구 기반 시험)로 검증되고, 위로 SyRS·HSIS, 아래로 SDS→UDS→Source, 가로로 각 시험 밴드에 연결된다.
- 밴드 SSOT(10, backend `BANDS` = frontend `_TRACE_BANDS` lockstep): SyRS·SDS·HSIS·UDS·STS·SUTS·SITS·SyTS·SyITS·VectorCAST. 모든 링크는 `target=요구ID`의 방사형(star) — 밴드↔밴드 직접 엣지 아님.
- ⚠ 라벨 주의: **SUTS=SW 단위시험, SITS=SW 통합시험, SyITS=시스템 통합시험, SyTS=시스템 시험** (과거 'SUTS=SW통합 / SITS=시스템통합' 표기는 오류였음).

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

**에이전트 14종 전부 `model: opus`** (프로젝트 9 + 플러그인 5). 스킬은 에이전트에 위임하여 실행.

> planner가 2026-07-27에 sonnet → **opus로 승격**됐다(사용자 결정). 계획 단계는 잘못 세우면 그 아래 Gate 전부가 헛돌기 때문에 비용 대비 효과가 가장 크다 — 실측 사례: 사용자가 지적한 UI 결함 4건을 조사시켰더니 **지적보다 심각한 데이터 결함 2건**(IT 커버리지 분모 2.61배 부풀림, ASIL 함수 변경 22→1 과소보고)을 수치로 특정해냈다.
>
> 2026-08-19에 **남은 9종(prompt-engineer·tester·reviewer·documenter + 플러그인 5)도 opus로 승격**됐다(사용자 결정). 이제 모델 열은 전부 같으므로 **에이전트를 고르는 기준은 비용이 아니라 역할**이다 — 아래 표의 '호출 시점'만 보면 된다.
>
> ⚠ 승격 전 판단 근거는 아래 두 문단에 남긴다. 되돌릴 일이 생기면 **이 근거부터 다시 잴 것** (sonnet 으로 내리면 어느 규약이 먼저 새는지가 여기 적혀 있다).
>
> designer도 2026-07-28에 **opus로 승격**됐다(사용자 결정). 이 저장소의 프론트 작업은 CSS 배치가 아니라 **"측정치를 어떤 형태로 보여야 오독하지 않는가"** 판단이 본체다 — 밴드 교차와 값 변화를 한 열에 섞지 않기, 미계산을 `0`이 아니라 `—`로 두기, 절단을 침묵시키지 않기 같은 결정이 전부 designer 몫이라 sonnet 급 판단으로는 정직성 규약이 새어나간다.

| 에이전트 | 모델 | 역할 | 호출 시점 |
|---------|------|------|----------|
| **planner** | **opus** | 요구사항 분석, 작업 분해, 안전 영향도 평가 | Gate 1 (계획) |
| **architect** | **opus** | 모듈 설계, 인터페이스 정의, 아키텍처 결정 | Gate 2 (backend/workflow/report_gen) |
| **designer** | **opus** | UI/UX 설계, CSS 변수화, 접근성 | Gate 2 (frontend-v2) |
| **prompt-engineer** | **opus** | Gemini 프롬프트 체인 설계/튜닝 | Gate 2 (prompts/uds_ai.py) |
| **coder** | **opus** | Python/React/C 코드 구현 | Gate 3 (구현) |
| **tester** | **opus** | 테스트 작성/실행, ISO 26262 커버리지 + MCP 리포트 접근 | Gate 4 (검증) |
| **reviewer** | **opus** | 보안/성능/MISRA-C/ASIL 리뷰 + MCP 코드검색/리포트 접근 | Gate 5 (light/standard depth) |
| **deep-reviewer** | **opus** | deep depth 전용 비판 리뷰 (X1~X9 시나리오/timeline/트리 의무) | Gate 5 (deep depth — 100줄+/5파일+/키워드/ASIL) |
| **documenter** | **opus** | 계획서, 변경내역, 결과보고서 작성 + Bash 실행 | Gate 6 (문서화) |

### 에이전트 ↔ 스킬 관계
- `/start-work` → 전체 Gate 1~6 순차 실행 (planner→coder→tester→reviewer 자동 라우팅)

## Architecture
- **Backend**: FastAPI (Python 3.12) — `backend/`
- **Frontend**: React + Vite — `frontend-v2/` (port 5174)
- **LLM**: Google Gemini 3 Pro / 2.5 Flash — `workflow/ai.py`
- **CI**: GitHub Actions(`ci.yml` = syntax-check + unit-tests + frontend-tests + **lint**[ruff_ratchet + **eslint_ratchet** 변경라인 + SKILL.md frontmatter]) + GitLab CI(stages: lint[syntax + ruff-eslint-frontmatter]/test/frontend). **검증 전용 — 배포 스텝 없음**
- **기동/배포**: `start.bat` + `backend\.venv` (사용자 PC). **Docker/nginx 설정은 저장소에 있으나 미사용**(과거 검토) — 되살리려면 tkinter 부재로 파일 선택 불가 + cloudium worker가 컨테이너 localhost라 사용자 PC에 안 닿는 문제부터 해결 필요
- **Jenkins**: 이 앱의 CD가 아니라 **분석 대상 데이터 소스**(빌드 산출물을 읽어옴 — `/api/jenkins/*`)
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

전체 목록은 `.claude/skills/*/SKILL.md` (한 단계만 스캔 — 중첩 디렉터리는 discovery 안 됨).

> **frontmatter 규약**: 자동 호출 판정에 쓰이는 건 **`description` + `when_to_use`** 다(합산 1,536자 제한, 초과분은 잘림). 트리거 문구는 반드시 **`when_to_use:`** 에 쓸 것.
>
> 2026-07-17에 **트리거가 0인 스킬이 16개 중 16개**였다(프로젝트 14 + 플러그인 2) — 두 가지 경로로:
> 1. **잘못된 필드명** (9개) — `trigger:` 는 **공식 필드가 아니라 조용히 무시된다**(경고도 없음). `/start-work` 의 "다 고쳐/이어서/1번부터" 가 여기 있었다. 알 수 없는 필드는 전부 같은 식으로 사라지므로 새 필드를 쓸 땐 공식 목록을 확인할 것
> 2. **필드 자체 부재** (7개: `deploy`·`doc-pipeline`·`health-check`·`hotfix`·`impact` + 플러그인 `doc-gen`·`review`) — 위 §Workflows 가 "자동 연결"이라 부르는 `/hotfix`·`/doc-pipeline` 이 여기 있었다. 결과는 ①과 같다: **직접 타이핑해야만 걸린다**
>
> 공식 필드는 **16개**뿐이다(`name` `description` `when_to_use` `argument-hint` `arguments` `disable-model-invocation` `user-invocable` `allowed-tools` `disallowed-tools` `model` `effort` `context` `agent` `hooks` `paths` `shell` — [공식 문서](https://code.claude.com/docs/en/skills.md) "Frontmatter reference"). **필수 필드는 없다** — `name` 은 디렉터리명 폴백(표시 라벨일 뿐, 커맨드 이름은 디렉터리에서 온다), `description` 은 본문 첫 문단 폴백. 다만 첫 문단 폴백으론 자동 호출 매칭이 안 되므로 이 저장소는 description 을 요구한다(**프로젝트 정책**이지 스펙 위반 아님).
>
> 위 두 결함은 **조용히 실패**하므로 눈으로 못 본다. SKILL.md 편집 시 PostToolUse 훅이 자동 검사하고, 수동으로는:
> `.venv/Scripts/python.exe scripts/check_skill_frontmatter.py` (`.claude/` 전체 rglob — **플러그인 스킬 포함**. 과거 `.claude/skills/*` 만 보다가 플러그인 2개를 놓쳤다)

| 스킬 | 용도 |
|------|------|
| `/deploy` | push → **검증 CI** 트리거 + 상태 확인 (배포 stage 는 실재하지 않음 — 위 §Architecture) |
| `/deploy-release` | 릴리스 준비 — 사전 체크리스트 + 버전 태깅(`git tag v1.x.x`) + CI 상태 확인 |
| `/health-check` | 백엔드(:9000)/프론트(:5174) 상태 점검 |
| `/impact` | 백엔드 API 경유 영향도 분석 (SVN/Git 변경분 → 영향 문서) |
| `/impact-analysis` | 로컬 오케스트레이터 dry-run — 문서 재생성 **판정**까지 |
| `/uds-pipeline` | UDS 단일 파이프라인 (C 파싱→AI→검증→DOCX) |
| `/ci-validate` | CI/CD 파이프라인 정의 검증 + 테스트 스위트 실행 |
| `/debug-diagnose` | 버그·성능 이슈 체계적 진단 |
| `/report-quality` | 보고서 품질 검증·개선 |
| `/ui-design-system` | 프론트 디자인 토큰/CSS 변수화 |
| `/autodoc-generate` | AutoDoc — PPT/HTML/포털/API 문서 생성 |

**플러그인 제공** (devops-release):
- 스킬: `/devops-release:doc-gen` (단일 문서 생성), `/devops-release:review` (코드 리뷰)
- 에이전트 5종: `ci-monitor`, `doc-quality`, `db-manager`, `performance-monitor`, `security-audit`
  — 위 **Team Agents 표(프로젝트 에이전트 9종)와 별개**이며, 플러그인 활성화 시에만 존재

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
- **PreToolUse**: `scripts/pretool_asil_check.py` — C/H 파일 수정 **직전** 기존 내용에서 `@asil C|D` 감지 → 경고(차단 아님)
- **PostToolUse**: 단일 dispatcher (`scripts/posttool_dispatch.py`) — Python syntax+ruff, **JSX/TS 는 `eslint_ratchet.py`(변경라인 한정, `--fix` 없음)**, .md broken-link/heading-jump, workflow/report_gen 변경 시 **대응 모듈 테스트**(`tests/unit/test_<모듈>.py`). **SKILL.md 는 frontmatter 도 검사**(`scripts/check_skill_frontmatter.py` — 미지 필드/`when_to_use` 부재/1,536자 초과. 심각도 순 정렬 — 훅이 상위 3건만 보여주므로 순서가 곧 가시성이다). **Python 은 신규 침묵-except 도 advisory**(`scripts/_silence_check.py` — `except Exception: pass` 류; ruff/E722 사각지대. net-new 만, 좁은예외/로깅/`# silent-ok` 면제)
- **PostToolBatch** (신규, 2026-05-11): 병렬 Write/Edit 일괄 종료 시 `scripts/posttoolbatch_report.py` — 변경 파일 집계 + 능동 보고 X1~X9 trigger 메시지를 메인 응답에 push. **단일 파일 turn은 silent** (PostToolUse가 이미 파일별 보고), 단 ASIL C/H는 단독이어도 hint 출력. ASIL 파일은 list 앞으로 정렬되어 truncation 시에도 누락되지 않음. 출력은 `ensure_ascii=False`로 한글 가독성 유지. **메인 에이전트의 능동 보고 의무는 그대로 유지** (hook은 보조 알림이며 대체 아님)
- **Stop**: `scripts/quality_check.py` 단일 호출 (이전 `stop_check.py` fallback 사슬 제거됨). **advisory 게이트** — pytest는 변경 모듈 스코프(`tests/unit/test_<모듈>.py`), 전역 예산(`QUALITY_CHECK_BUDGET`, 기본 240s) 내 자체 종료. 전체 회귀(`tests/unit/` = **8,147개** · 게이트 실범위 `tests/`(**예외 없음**) = **8,436개 / 572초**(`-n auto`, 2026-09-02 실측 — pre-commit 게이트 실행값) — 2026-08-21 엔 7,288개/310~433초, 2026-08-19 엔 6,676개였다. 소요는 **직렬 590초 · 병렬(`-n auto`, 18코어) 179초** 로 4,638개 시점(2026-07-29) 측정값이라 지금은 더 걸린다. 2026-08-03 5,241개 · 2026-07-17 3,486개/281초였다 — **한 달에 1.9배로 자라는 중이라 이 줄의 수치는 인용 전에 다시 셀 것**)는 예산에 못 들어가므로 `--round 3` 또는 pre-commit 담당. **결과 캐시 없음**(tracked diff 해시가 untracked 변경을 못 봐 stale PASS를 냈던 전례 — `scripts/quality_check.py` 주석 참조). **변경 파일 목록은 `git diff`(±cached)에 `git ls-files --others`(untracked) 를 더한다** — 캐시만 고치고 파일 목록은 tracked-only 로 두던 같은 결함이 남아 있어, `except Exception: pass` 든 신규 파일이 `verified:true`로 통과하던 것을 2026-07-21 차단(untracked 는 전 라인 신규로 §7d 판정). §7d 는 **AST 침묵-except ratchet**(`git diff -M` 추가라인의 신규 `except Exception: pass` 만 Warning — 레거시 **793건 / 125파일**[2026-09-02 실측 — `scripts/_silence_check.py:silent_excepts` 정의로 `backend`·`generators`·`report_gen`·`workflow`·`scripts`·`tests`·`prompts`+루트 스캔, **`venv`/`.venv`/`node_modules`/`site-packages` 제외**. 내역: no-raise/no-log 544 · pass-only 249. ⚠ 여기 적혀 있던 **2,306건 / 711파일(2026-08-19)** 은 **틀린 수치였다** — `backend/venv`(점 없음, git 미추적 site-packages **12,562파일**)가 필터를 빠져나가 **남의 코드를 센 값**이다. 그때 '스코프가 명시되지 않아 재현 불가'라며 폐기한 옛 수치 **831** 이 오히려 이 값에 가깝다 — **재현이 안 되면 옛 수치가 아니라 내 스코프부터 의심할 것**] backlog 제외, `# silent-ok` 면제)
  - **격리 규약**: Stop 훅은 변경 모듈을 **단독 실행**하므로 모든 테스트 파일이 단독으로 통과해야 한다(그래야 FAIL=진짜 회귀). `tests/conftest.py`의 `_default_local_resolver`/`_default_admin_users`가(2026-08-21 `tests/unit/` 에서 **이동** — `tests/integration/` 이 격리 0이라 56건이 401로 죽어 있었다) 머신 상태(`config/file_mode.json`, `admin_users.json`)로부터 격리하며, 파일별 fixture가 이를 override할 수 있다. **전역 싱글톤을 teardown에서 "특정 값으로 고정"하지 말 것 — 반드시 원래 값 복원** (`file_resolver._resolver` 누설로 단독 16건이 깨졌던 전례: 커밋 584833e)
- **PreCompact**: `scripts/precompact_context.py` — git status + diff stat을 `.codex_tmp/precompact_context.json`에 저장 (출력은 schema 정합 `systemMessage` 형식, timeout 15s)
- **훅은 전부 `scripts/*.py` 파일로 유지할 것** — settings.json 안의 한 줄짜리 `python -c "…"` 는 읽기·수정·테스트가 불가능하고 JSON 이스케이프가 조금만 틀어져도 조용히 죽는다 (2026-07-17에 ASIL/PreCompact 2건을 파일로 분리)
- **플러그인 훅** (devops-release — 프로젝트 훅과 **병합**되어 함께 발화): PreToolUse `Bash` → `.claude/plugins/devops-release/scripts/validate_api_call.py` (백엔드 :9000 미기동 시 경고), PostToolUse `Edit|Write` → `.claude/plugins/devops-release/scripts/check_secrets.py`.
  ⚠ 2026-08-03 에 `.sh` → `.py` 로 옮겼다. 옛 판은 stdin JSON 을 **`jq` 로 팠는데 이 환경엔 jq 가 없어** 변수가 빈 문자열이 되고 곧바로 `exit 0` — **활성화된 채 한 번도 검사한 적이 없었다**(비밀값 2건이 든 파일을 넣어도 무출력). 도구 부재를 clean 으로 읽던 fake-green 패턴이라 stdlib 만 쓰는 Python 으로 재작성하고, **입력/도구 이상은 `DISABLED` 로 명시 보고**하게 했다. 비밀값은 **키 이름과 줄 번호만** 출력한다(경고문이 값을 대화 기록에 복사하면 검사기가 유출 경로가 된다)
- **훅 인터프리터 계약**: 훅은 정리된 PATH에서 떠서 맨 `python`이 mingw python(ruff/bcrypt 없음)으로 잡힌다. 그래서 훅 스크립트는 `scripts/_hook_env.py`의 `project_py()`로 프로젝트 venv를 명시 해석하고, 도구가 없으면 **DISABLED로 명시 보고**한다(빈 출력을 "clean/PASS"로 읽던 fake-green 차단). bash 쪽 동일 우회는 `.githooks/pre-commit`
- **`.githooks/pre-commit` (3단계 게이트, 2026-07-18 ruff·frontmatter 승격 / 2026-07-20 eslint 추가)**: syntax(py_compile) → **`ruff_ratchet.py --cached` + `eslint_ratchet.py --cached`(둘 다 변경라인 신규위반) + `check_skill_frontmatter.py`** → pytest(**xdist 있으면 `-n auto`**, 900s). ⚠ **2026-08-21: 테스트 범위가 `tests/unit/` → `tests/unit/ tests/integration/ tests/e2e/` 로 넓어졌다.** 게이트 4곳(pre-commit·Stop·GitHub Actions·GitLab)이 전부 `tests/unit/` 만 돌아서 **integration 56건이 커밋 `1b6bb99`(2026-08-04) 이후 17일간 전부 401 로 죽어 있었는데 스위트는 초록**이었다 — 거기엔 `STS-EXPORTS-001` 같은 ISO 26262 추적성 ID 가 달려 "시험이 있다"는 근거로 쓰인다. ⚠ 죽은 스위트는 회귀만 못 잡는 게 아니라 **낡은 계약을 보존한다**: 되살려 보니 `/api/run/stop` 이 임의 PID 에 200 을 주던(=백엔드를 통째로 죽일 수 있던) 시절의 기대가 그대로였다. `tests/` 루트 직속 3파일(196건·561초·ASIL QM 기본값 요구)은 **아직 제외**이고 사유는 `tests/unit/test_gate_reach.py` 의 `_EXEMPT` 에 있다 — 그 가드가 새 사각지대를 막는다(뮤테이션 3/3). **2026-07-29: 타임아웃이 `"Skipping — commit allowed"` 로 커밋을 통과시키던 것을 fail-closed(중단)로 바꿨다** — 스위트가 3,486개/281초(07-17) → 4,638개/590초(07-29)로 자라 예산 여유가 310초뿐이었고, 넘는 순간 게이트가 조용히 무게이트로 강등된다. 이 저장소에서 "오래 걸림"의 실체는 느림이 아니라 **hang** 이었다(재진입 데드락·tkinter 모달). 병렬은 실측 590→**179·174초**(3회 실행, 격리 실패 0건 — 결과가 직렬과 완전 일치. 3회차만 4,650인데 그 사이 추가한 신규 테스트 12건 때문이고, 다른 작업과 동시 실행이라 261초). 부하 중에도 예산 대비 여유 639초. xdist 부재는 조용히 직렬로 도는 게 아니라 **명시 보고**. ruff·frontmatter 는 이전엔 PostToolUse 훅에서만 발화해 `--no-verify`·외부 에디터·auto_commit_push 가 우회했다 → 커밋 시점·CI(`lint` job)로 승격. 저장소 ruff backlog(**82건** — 2026-09-02 실측 `ruff check .`. E702 30·F841 27·E701 12·E731 4·F401 4·E741 3·E722 1·I001 1. ⚠ 직전 판(141건)의 내역은 **합이 82밖에 안 됐다** — 최대 항목 **E402 52건(전체의 39%)이 통째로 빠진 채** '남은 건 전부 판단 축'이라고 적혀 있었다. E402 는 판단 축이 아니라 이 문서가 아래에서 `# noqa` 로 **해소하라고 지시한** 항목이고, 실제로 **절반만 해소돼 있었다** — 같은 import 블록 안에서 일부 줄에만 `# noqa: E402` 가 붙어 있었다(`backend/routers/swut.py` 85·89 는 있고 92~107 은 없음). 2026-09-02 에 52건 전부 붙여 **E402 0건**으로 마무리했고, 다른 규칙 증가 0건·핵심 모듈 import 확인)라 **파일 전체가 아닌 변경 라인 ratchet**(`scripts/ruff_ratchet.py`). ruff·eslint 두 ratchet 의 **판정 로직은 `scripts/_ratchet_core.py` 단일 출처**다(2026-07-21) — 예전엔 eslint 판이 ruff 판의 복제라 미러링 중 고친 fail-open 이 한쪽에만 반영돼, 같은 untracked 파일을 ruff 판은 통과·eslint 판은 차단했다. ⚠rename 은 `-M`+**pathspec 없이**라야 감지(pathspec 이 old 배제→파일 전체 폭주). ⚠**import 정렬(I001)이 레거시 위반을 '신규'로 만든다** — 재배치된 줄이 `git diff` 상 추가 라인이라 원래 거기 있던 F401/E402 가 신규로 계상된다(R10 실측 120건 차단). 되돌려 '안 바뀐 줄'로 만드는 건 게이트를 속이는 것 → `__init__.py` F401 은 `per-file-ignores`, `sys.path` 뒤 E402 는 `# noqa` 로 **실제로 해소**할 것. ⚠훅은 `ruff_ratchet.py --cached $STAGED_PY` 로 **파일 목록을 인자로** 넘긴다 — 인자 없이 돌리면 결과가 달라지므로 재현은 같은 인자로. ruff 자체 실패(rc≠0+빈 stdout)는 `[]`→clean 이 아니라 **DISABLED(fail-closed)**. untracked 신규 파일은 전 라인 신규(레거시 빚 없음), 경로 정규화 실패·added 공백+위반존재도 통과 아닌 **보류(rc=2)**. 로컬은 DISABLED 경고후허용/CI 는 실패(의도적 비대칭)
- **ESLint (2026-07-20 신설)**: `frontend-v2` 에 flat config·의존성이 **아예 없어** 훅이 매 편집마다 `npx eslint` ERROR 만 냈다 = JSX lint 게이트가 한 번도 동작한 적 없음. `eslint.config.js`(테스트 전역 블록 필수 — 없으면 `no-undef` 2,000건+) + `scripts/eslint_ratchet.py` 신설. **실측 backlog = error 29 / warning 16**(2026-09-02 실측, `frontend-v2/src` 16파일 — 신설 시점 101/36 → 73/18 → 2026-08-19 정리 35/18 → 35/16 → **현재 29/16**). ⚠ 직전 판은 남은 51건이 **"전부 판단 축"**이라고 적었는데 **틀렸다** — 6건은 판단이 필요 없는 실 결함이었고 2026-09-02 에 전수 판정하며 해소했다: `react-hooks/refs` 3 + `purity` 1(**`Dashboard.jsx:62,494`** — 렌더 중 `Math.random()` 과 **렌더 중 ref 쓰기**. React 는 커밋하지 않고 렌더할 수 있어 버려진 렌더의 함수가 ref 에 남는다 → `useState` 지연 초기화 + effect 로 이동) + `no-unused-vars` 2(구조 검사가 2026-08-31 에 행동 검사로 교체되며 남은 죽은 import). **남은 45건은 판단 축이 맞다**: react-hooks 계열 38(exhaustive-deps 16·set-state-in-effect 15·immutability 5·purity 1[`Date.now()` — 렌더 시점의 '지금'이 의도된 의미]·preserve-manual-memoization 1 — deps 를 기계적으로 채우면 무한 루프·stale closure, 후방참조 5건은 런타임 결함이 아니라 컴파일러 최적화 포기이며 `AuthContext`/`AdminContext` 는 인증 흐름이라 이득보다 회귀 위험이 크다) + react-refresh/only-export-components 7(파일 분리 필요) → ratchet. **변경 라인은 error·warning 둘 다 차단**(severity 1도 — 레거시만 면제): warning 이 대부분 `react-hooks/exhaustive-deps`(X2 stale closure)라, 비차단이면 유일한 자동 X2 검사가 아무것도 안 막는다. npx 대신 `_hook_env.project_eslint()` 로 **로컬 바이너리 직접 해석**(npx 는 미설치 시 레지스트리에서 받아와 훅이 조용히 네트워크에 의존했다)

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
- ⚠ **`D:/Project/devops/Release_claude - 복사본/` — 되병합 금지**. 별도 git 저장소(`main`)이고 HEAD가 **`d943d89` 2026-04-01 스냅샷**에 멈춰 있는 **구 하네스**다: X9 없음(X1~X8), health-check 포트 8000(현 9000), 죽은 `/dev` 스킬 존재, 품질 게이트 fake-green 수정분 없음. **canonical 은 이 트리(`Release_claude/`)** 다. 거기서 Claude Code 를 돌리거나 스킬/설정을 이쪽으로 가져오면 2026-07-17에 고친 결함들이 되살아난다 (참조용 보관본으로만 취급할 것)
- SwUT/SwIT 빌더 관련 사용자 환경 의존 path: [`docs/builders/swut_builder.md`](docs/builders/swut_builder.md) `## SwUT 관련 path` 참조

## SCM Credential Resolution (Jenkins sync)
- **절대 HTTP body로 password를 받지 않음** — env 또는 registry에서만 해결
- 우선순위: `scm_id` → `repo_url` 매칭 → entry의 `scm_password_env` → 전역 `DEVOPS_SCM_PASSWORD`
- `scm_password_env`는 shell identifier 패턴만 허용하고 `PATH`/`HOME` 등 시스템 변수 블랙리스트
- SVN auth 캐시에 의존하지 말고 env 주입할 것 (Dockerfile은 `subversion`을 포함하나 **Docker는 현재 미사용** — 아래 Architecture 참조)
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
