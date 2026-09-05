---
name: ci-validate
description: CI/CD 파이프라인(GitLab CI, GitHub Actions) 정의를 검증하고 pytest 스위트를 실행합니다.
when_to_use: CI 파이프라인, 테스트 실행, pytest, 빌드 검증, GitLab CI, GitHub Actions 요청 시
---

# /ci-validate 스킬

CI/CD 파이프라인과 전체 테스트 스위트를 실행/검증합니다.

## 파이프라인 구성

### GitLab CI (`.gitlab-ci.yml`)
- PowerShell executor
- Syntax check → Unit tests
- 현재 스위트 전량, 15분 타임아웃 (개수를 고정 기재하지 말 것 — 실제 개수는 `.venv/Scripts/python.exe -m pytest tests/unit/ --collect-only -q` 로 확인. 과거 "253개" 표기가 실제와 14배 어긋난 채 방치됐다)
- ⚠ **양쪽 다 test_impact_jobs 를 건너뛰지 않는다.** `.gitlab-ci.yml` 은 원래 0건이었고,
  GitHub 쪽 `--ignore=tests/unit/test_impact_jobs.py` 도 커밋 `b107c4b`(2026-07-29)에서
  **제거됐다**(`ci.yml:83-86` 주석이 그 경위를 남긴다 — 19건이 계속 미검증이었다).
  *(2026-08-03 정정: 이 절은 이미 사라진 `--ignore` 를 계속 있다고 적고 있었다.)*

### GitHub Actions (`.github/workflows/ci.yml`)
- 잡 **4개**: `syntax-check`(:10) / `unit-tests`(:37) / `frontend-tests`(:99) / **`lint`(:117)**
- `lint` = ruff_ratchet + eslint_ratchet(변경 라인) + SKILL.md frontmatter.
  로컬 pre-commit 과 달리 **DISABLED(rc=2)도 빌드 실패**로 다룬다(의도적 비대칭 —
  통제된 환경에서 도구 부재는 인프라 이상이다)
- ⚠ **deploy stage 없음** — 이 CI 는 검증 전용이다
- ⚠ `unit-tests` 잡에 **`timeout-minutes` 가 없다**(GitLab 은 15m 명시). hang 시 하드캡이
  GitHub 기본값에만 의존한다 — 로컬 훅이 900s+30s KILL 로 fail-closed 인 것과 비대칭

## 실행 순서

### 1. 로컬 테스트
```bash
# 전체 단위 테스트
.venv/Scripts/python.exe -m pytest tests/unit/ -v --tb=short --timeout=60 2>&1 | tail -30

# 특정 모듈
.venv/Scripts/python.exe -m pytest tests/unit/test_impact_orchestrator.py -v
.venv/Scripts/python.exe -m pytest tests/unit/test_generators_sts.py -v
.venv/Scripts/python.exe -m pytest tests/unit/test_generators_suts.py -v
```

### 2. 문법 검사
```bash
# Python 구문 오류 확인
.venv/Scripts/python.exe -m py_compile backend/main.py
.venv/Scripts/python.exe -m py_compile workflow/impact_orchestrator.py
.venv/Scripts/python.exe -m py_compile report_gen/source_parser.py
```

### 3. CI 설정 검증
- `.gitlab-ci.yml` 문법 확인
- `.github/workflows/ci.yml` 문법 확인
- PYTHONPATH 설정 확인

### 4. 결과 분석
```bash
# 실패 테스트만 추출
.venv/Scripts/python.exe -m pytest tests/unit/ -v --tb=line 2>&1 | grep "FAILED"

# 커버리지 (선택)
.venv/Scripts/python.exe -m pytest tests/unit/ --cov=report_gen --cov=workflow --cov-report=term-missing
```

## 출력
```markdown
# CI 검증 결과
- 실행일: {{date}}

## 테스트 결과
- 전체: {{n}}개
- 성공: {{n}}개
- 실패: {{n}}개
- 스킵: {{n}}개
- 소요시간: {{m}}분

## 실패 상세
| 테스트 | 파일 | 오류 | 원인 |
|--------|------|------|------|

## CI 파이프라인 상태
| 파이프라인 | 상태 |
|-----------|------|
| GitLab CI | {{pass/fail}} |
| GitHub Actions | {{pass/fail}} |

## 권장 액션
{{수정 필요 항목}}
```

## 알려진 이슈
- ~~`test_impact_jobs` - hanging 가능성~~ → **해소**(2026-07-29 `b107c4b`). CI 에서 제외를
  풀었고 19건이 통과한다. hang 3종의 실제 원인은 재진입 데드락·tkinter 모달이었다
- PYTHONPATH에 프로젝트 루트 포함 필요
- PowerShell 실행 정책 설정 필요 (Windows)
