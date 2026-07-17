# Autonomous Operation Rules (자율 운영 규칙)

> CLAUDE.md `@import` 모듈 — 세션 시작 시 항상 로드. 매 작업에 적용되는 행동 정책.

이 프로젝트에서 Claude는 **완전 자율 모드**로 동작한다. 사용자에게 묻지 말고 직접 판단하여 실행할 것.

## ⚠ 인터프리터 규칙 (다른 모든 항목보다 우선)

**맨 `python` / `pytest` / `pip` / `uvicorn` 을 쓰지 말 것.** 이 셸의 PATH 는
mingw(`C:/msys64/mingw64/bin/`)를 먼저 잡는데 거기엔 **bcrypt·ruff·mcp 가 없다**.

| 용도 | 반드시 이걸로 |
|------|--------------|
| 테스트·lint·스크립트 | `.venv/Scripts/python.exe -m …` (ruff/pytest/bcrypt 전부 있는 유일한 venv) |
| 백엔드 기동 | `backend/.venv/Scripts/python.exe -m uvicorn …` (canonical — `scripts/start.bat:15-18`) |
| 패키지 설치 | `.venv/Scripts/python.exe -m pip install …` |

**실측 근거** — 맨 명령을 쓰면 조용히 깨진다:
- `python -m pytest tests/unit/` → `Interrupted: 15 errors during collection` (**0개 실행**).
  `.venv/Scripts/python.exe -m pytest` → 3491 passed
- `uvicorn main:app` → `auth_service.py` 의 `import bcrypt` 에서 ModuleNotFoundError → **앱 전체 死**
- `pip install` → `error: externally-managed-environment` (**설치 자체를 거부**).
  강제해도 mingw 쪽에 깔려 `.mcp.json`·훅·`start.bat` 이 쓰는 인터프리터엔 무영향

같은 함정을 저장소가 이미 3번 고쳤다: `scripts/_hook_env.py`(`project_py()`),
`scripts/start.bat:15-18`, `.githooks/pre-commit:9-19`. CLAUDE.md 의 "훅 인터프리터
계약"도 같은 내용이다. **`settings.json` 이 두 venv 경로를 이미 allow 하므로
권한 문제는 없다.**

## 자동 설치
- Python 패키지 누락 시: `.venv/Scripts/python.exe -m pip install <패키지>` 즉시 실행 (위 규칙)
- npm 패키지 누락 시: `npm install <패키지>` 즉시 실행
- import 에러, ModuleNotFoundError 발생 시 자동 설치 후 재시도
  - ⚠ 단, **맨 `python` 으로 났다면 패키지 문제가 아니라 인터프리터 문제**다. 설치하지 말고 venv 로 다시 실행할 것
- requirements.txt / package.json에 없는 패키지도 필요하면 설치하고 의존성 파일에 추가

## 자동 환경 구성
- 서버가 꺼져 있으면 자동으로 시작 (backend: **`backend/.venv/Scripts/python.exe -m uvicorn`**, frontend: npm run dev)
- venv가 없으면 생성, node_modules가 없으면 npm install 실행
- .env가 없으면 .env.example 복사하여 생성

## 자동 오류 복구
- 테스트 실패 시 원인 분석 → 수정 → 재실행까지 자동 진행
  - ⚠ **먼저 인터프리터부터 의심할 것.** 수집 에러(`errors during collection`)·
    `ModuleNotFoundError: bcrypt` 는 코드 결함이 아니라 맨 `python` 을 쓴 증상이다.
    이걸 코드 문제로 오인해 고치려 들면 멀쩡한 코드를 망친다
- 빌드 에러 시 의존성 확인 → 설치 → 재빌드
- 포트 충돌 시 프로세스 확인 후 대체 포트 사용
- **예외**: 안전 관련 테스트(ASIL C/D) 실패 시 자동 수정하지 않고 보고

## MCP / RAG 활용 (구체화 — 직접 Bash 사용 지양)

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

## Settings/Hooks 변경 시 절차

`.claude/settings.json` / `.claude/settings.local.json` / hooks / permissions / env 변경 시 다음 절차 의무:

1. **백업**: `cp .claude/settings.json .claude/settings.json.bak.YYYYMMDD` (롤백 안전망)
2. **변경 후 parse 검증**: `.venv/Scripts/python.exe -c "import json; json.load(open('.claude/settings.json'))"` — 0 exit 아니면 즉시 백업 복원
3. **hook 변경 시 스모크 테스트**: `echo '{}' | python scripts/<hook>.py` 빈 입력으로 silent 종료 확인

**예외**: 단순 `permissions.allow` 항목 한두 개 추가는 직접 Edit 허용 (parse 검증만).

> **2026-06-05 갱신**: `update-config` 스킬이 등록되어 있으므로 settings/hooks 변경은 `/update-config` 사용을 권장한다. 단순 `permissions.allow` 1~2개 추가는 위 수동 절차(백업+parse 검증)만으로 직접 Edit 허용. 참고: Stop hook `quality_check.py`는 stdin이 아닌 `git diff` 상태 기반으로 동작하므로, 빈 입력 스모크 테스트(`echo '{}' | ...`)는 working tree가 clean일 때만 silent 종료한다 (변경 파일이 있으면 정상적으로 보고 출력).

## TaskCreate 선제화

3단계 이상 또는 여러 파일 수정이 예상되는 작업은 **시작 전 즉시 TaskCreate**로 추적 시작한다. system reminder를 받고서야 만드는 반응적 패턴은 진행 가시성을 떨어뜨린다. 단일 파일 수정·간단한 질의 응답·정보 조회는 TaskCreate 불필요.

## 판단 기준
- "할까요?" 대신 "했습니다" — 묻지 말고 실행
- 에러가 나면 3회까지 자동 재시도 후 안 되면 보고
- 파일 생성/수정/삭제 모두 자율 판단 (단, .env 파일은 예외)
