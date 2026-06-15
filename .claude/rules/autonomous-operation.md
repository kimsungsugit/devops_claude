# Autonomous Operation Rules (자율 운영 규칙)

> CLAUDE.md `@import` 모듈 — 세션 시작 시 항상 로드. 매 작업에 적용되는 행동 정책.

이 프로젝트에서 Claude는 **완전 자율 모드**로 동작한다. 사용자에게 묻지 말고 직접 판단하여 실행할 것.

## 자동 설치
- Python 패키지 누락 시: `pip install <패키지>` 즉시 실행
- npm 패키지 누락 시: `npm install <패키지>` 즉시 실행
- import 에러, ModuleNotFoundError 발생 시 자동 설치 후 재시도
- requirements.txt / package.json에 없는 패키지도 필요하면 설치하고 의존성 파일에 추가

## 자동 환경 구성
- 서버가 꺼져 있으면 자동으로 시작 (backend: uvicorn, frontend: npm run dev)
- venv가 없으면 생성, node_modules가 없으면 npm install 실행
- .env가 없으면 .env.example 복사하여 생성

## 자동 오류 복구
- 테스트 실패 시 원인 분석 → 수정 → 재실행까지 자동 진행
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
2. **변경 후 parse 검증**: `python -c "import json; json.load(open('.claude/settings.json'))"` — 0 exit 아니면 즉시 백업 복원
3. **hook 변경 시 스모크 테스트**: `echo '{}' | python scripts/<hook>.py` 빈 입력으로 silent 종료 확인

**예외**: 단순 `permissions.allow` 항목 한두 개 추가는 직접 Edit 허용 (parse 검증만).

> **2026-06-05 갱신**: `update-config` 스킬이 등록되어 있으므로 settings/hooks 변경은 `/update-config` 사용을 권장한다. 단순 `permissions.allow` 1~2개 추가는 위 수동 절차(백업+parse 검증)만으로 직접 Edit 허용. 참고: Stop hook `quality_check.py`는 stdin이 아닌 `git diff` 상태 기반으로 동작하므로, 빈 입력 스모크 테스트(`echo '{}' | ...`)는 working tree가 clean일 때만 silent 종료한다 (변경 파일이 있으면 정상적으로 보고 출력).

## TaskCreate 선제화

3단계 이상 또는 여러 파일 수정이 예상되는 작업은 **시작 전 즉시 TaskCreate**로 추적 시작한다. system reminder를 받고서야 만드는 반응적 패턴은 진행 가시성을 떨어뜨린다. 단일 파일 수정·간단한 질의 응답·정보 조회는 TaskCreate 불필요.

## 판단 기준
- "할까요?" 대신 "했습니다" — 묻지 말고 실행
- 에러가 나면 3회까지 자동 재시도 후 안 되면 보고
- 파일 생성/수정/삭제 모두 자율 판단 (단, .env 파일은 예외)
