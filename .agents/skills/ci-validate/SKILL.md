---
name: ci-validate
description: CI/CD 파이프라인(GitLab CI, GitHub Actions)을 검증하고 253개 pytest 테스트를 실행합니다.
trigger: CI 파이프라인, 테스트 실행, pytest, 빌드 검증, GitLab CI, GitHub Actions 요청 시
---

# /ci-validate 스킬

CI/CD 파이프라인과 전체 테스트 스위트를 실행/검증합니다.

## 파이프라인 구성

### GitLab CI (`.gitlab-ci.yml`)
- PowerShell executor
- Syntax check → Unit tests
- 253개 테스트 케이스, 15분 타임아웃
- test_impact_jobs 스킵 (hanging 방지)

### GitHub Actions (`.github/workflows/ci.yml`)
- Python setup → pip install → pytest

## 실행 순서

### 1. 로컬 테스트
```bash
# 전체 단위 테스트
pytest tests/unit/ -v --tb=short --timeout=60 2>&1 | tail -30

# 특정 모듈
pytest tests/unit/test_impact_orchestrator.py -v
pytest tests/unit/test_generators_sts.py -v
pytest tests/unit/test_generators_suts.py -v
```

### 2. 문법 검사
```bash
# Python 구문 오류 확인
python -m py_compile backend/main.py
python -m py_compile workflow/impact_orchestrator.py
python -m py_compile report_gen/source_parser.py
```

### 3. CI 설정 검증
- `.gitlab-ci.yml` 문법 확인
- `.github/workflows/ci.yml` 문법 확인
- PYTHONPATH 설정 확인

### 4. 결과 분석
```bash
# 실패 테스트만 추출
pytest tests/unit/ -v --tb=line 2>&1 | grep "FAILED"

# 커버리지 (선택)
pytest tests/unit/ --cov=report_gen --cov=workflow --cov-report=term-missing
```

## 출력
```markdown
# CI 검증 결과
- 실행일: {{date}}

## 테스트 결과
- 전체: 253개
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
- `test_impact_jobs` - hanging 가능성, 타임아웃 필요
- PYTHONPATH에 프로젝트 루트 포함 필요
- PowerShell 실행 정책 설정 필요 (Windows)
