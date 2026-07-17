---
name: deploy
description: "**push → 파이프라인 트리거 + 상태 확인**. 환경(dev/staging/prod)을 인자로 받아 현재 커밋 기준으로 진행합니다. 버전 태깅이나 릴리스 전 체크리스트까지 필요하면 `/deploy-release`를 쓰세요."
---

# 배포 스킬

$ARGUMENTS 에 배포 대상(환경, 브랜치 등)이 들어옵니다.

## ⚠ 먼저 알 것 — 자동 배포 파이프라인은 **없다** (2026-07-17 확인)

`git push` 가 트리거하는 건 **검증 CI 뿐**이다:
- `.github/workflows/ci.yml` → syntax-check / unit-tests / frontend-tests
- `.gitlab-ci.yml` → stages: lint / test / frontend

**어느 쪽에도 deploy stage 가 없고**, 실제 기동은 각자 PC 의 `start.bat`(+`backend\.venv`)다.
(Docker/nginx 설정은 저장소에 있으나 미사용 — `/deploy-release` 의 Docker 절 참조)

따라서 아래 환경 매핑은 **현재 실재하지 않는다.** 배포 대상이 새로 생기면 그때
이 절을 실제 배선으로 갱신할 것. 지금 이 스킬이 하는 일 = push → CI 상태 확인.

## 환경 매핑 (⚠ 미배선 — 위 참조)
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
- `.venv/Scripts/python.exe -m pytest tests/unit/ -q --tb=short`로 테스트 실행
  (맨 `pytest`/`python` 금지 — mingw 라 bcrypt 부재로 **수집 에러 15건 / 0개 실행**된다.
   `.claude/rules/autonomous-operation.md` 인터프리터 규칙 참조)
- 테스트 실패 시 자동 수정 후 재실행 (최대 3회)
  - ⚠ **고치기 전에 환경부터 의심할 것.** `errors during collection` 이나
    `ModuleNotFoundError: bcrypt` 는 **코드 결함이 아니라 인터프리터 문제**다.
    이걸 코드 문제로 오인하면 멀쩡한 코드를 3회 고치려 든다

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
