---
name: deploy
description: "CI/CD 파이프라인을 실행하고 배포 상태를 확인합니다."
---

# 배포 스킬

$ARGUMENTS 에 배포 대상(환경, 브랜치 등)이 들어옵니다.

## 환경 매핑
- `dev` / `development` --> 개발 서버 배포
- `staging` / `stage` --> 스테이징 환경 배포
- `prod` / `production` --> 운영 환경 배포 (추가 확인 필요)
- 인자 없으면 현재 브랜치 기준으로 판단 (main=staging, feature/*=dev)

## 자율 운영 원칙
- 테스트 미통과 시 자동 수정 후 재실행
- 미커밋 변경 있으면 사용자에게 경고 후 계속 진행 (자동 커밋하지 않음)
- 파이프라인 실패 시 로그 분석 --> 원인 보고

---

### STEP 1: 사전 검증
- `git status`로 미커밋 변경 확인
  - 미커밋 변경이 있으면: "경고: 커밋되지 않은 변경 N개 파일 있음. 배포는 마지막 커밋 기준으로 진행합니다." 출력 후 계속
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
- GitHub: `gh run list --limit 1` --> `gh run watch`
- Jenkins: 진행률 API 폴링
- 실패 시 로그 확인 및 원인 분석

### STEP 4: 결과 보고
```
## 배포 완료
환경: [dev/staging/prod]
파이프라인: [URL]
상태: SUCCESS / FAILED
소요 시간: N분
```
실패 시 로그 핵심 내용 포함

## 롤백 전략
- 배포 실패 시:
  1. 실패 원인 로그 분석 및 보고
  2. 이전 성공 배포 커밋 식별: `git log --oneline --merges -5`
  3. 롤백 명령 안내 (자동 실행하지 않음): `git revert <commit>` 또는 이전 태그 재배포
  4. 운영 환경(prod) 롤백은 반드시 사용자 승인 후 실행
