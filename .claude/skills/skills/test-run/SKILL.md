---
name: test-run
description: "테스트를 실행하고 결과를 분석합니다. 실패 시 자동 수정합니다."
---

# 테스트 실행 스킬

$ARGUMENTS 에 특정 테스트 파일이나 범위가 들어올 수 있습니다.

## 자율 운영 원칙
- 테스트 실패 → 원인 분석 → 코드 수정 → 재실행 (최대 3회)
- 패키지 누락 → 자동 설치 후 재실행
- 묻지 않고 수정, 결과만 보고

---

### STEP 1: 테스트 범위 결정
- 인자가 있으면 해당 테스트만 실행
- 없으면 `git diff --name-only`로 변경 파일 관련 테스트 탐색

### STEP 2: 테스트 실행
- 백엔드:
  ```bash
  python -m pytest tests/unit/ -q --tb=short
  ```
- 프론트엔드 (변경 있을 때):
  ```bash
  cd frontend-v2 && npm test
  ```

### STEP 3: 실패 시 자동 복구
- 스택 트레이스에서 원인 추출
- 코드 버그 → 직접 수정 후 재실행
- 테스트 로직 문제 → 테스트 수정 후 재실행
- import 에러 → `pip install` 후 재실행

### STEP 4: 결과 보고
```
테스트: X passed, Y failed, Z skipped
커버리지: N% (실행했으면)
```
실패 잔존 시 상세 내역 포함
