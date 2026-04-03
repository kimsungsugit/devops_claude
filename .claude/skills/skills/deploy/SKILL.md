---
name: deploy
description: "CI/CD 파이프라인을 실행하고 배포 상태를 확인합니다."
---

# 배포 스킬

$ARGUMENTS 에 배포 대상(환경, 브랜치 등)이 들어옵니다.

## 자율 운영 원칙
- 테스트 미통과 시 자동 수정 후 재실행
- 미커밋 변경 있으면 자동 커밋 후 배포
- 파이프라인 실패 시 로그 분석 → 원인 보고

---

### STEP 1: 사전 검증
- `git status`로 미커밋 변경 확인 → 있으면 자동 커밋
- `python -m pytest tests/unit/ -q --tb=short`로 테스트 실행
- 테스트 실패 시 자동 수정 후 재실행 (최대 3회)

### STEP 2: 배포 실행
- GitHub:
  ```bash
  git push origin $(git branch --show-current)
  ```
- Jenkins (필요 시):
  ```bash
  curl -s -X POST "${JENKINS_URL}/job/${JOB_NAME}/build"
  ```

### STEP 3: 상태 모니터링
- GitHub: `gh run list --limit 1` → `gh run watch`
- Jenkins: 진행률 API 폴링
- 실패 시 로그 확인 및 원인 분석

### STEP 4: 결과 보고
```
## 배포 완료
파이프라인: [URL]
상태: SUCCESS / FAILED
소요 시간: N분
```
실패 시 로그 핵심 내용 포함
