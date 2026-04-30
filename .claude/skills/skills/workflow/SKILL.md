---
name: workflow
description: "기획부터 배포까지 전체 개발 워크플로우를 자동으로 실행합니다. 기능 추가, 개선, 리팩토링 작업에 사용하세요."
---

# 전체 개발 워크플로우

$ARGUMENTS 에 구현할 기능이나 작업 설명이 들어옵니다.

## 자율 운영 원칙
- **묻지 않고 실행한다** -- "할까요?" 금지, "했습니다"로 보고
- 환경 문제(패키지 누락, 서버 미실행 등)는 자동 해결 후 진행
- 테스트 실패 시 3회까지 자동 수정/재시도, 그래도 실패하면 보고
- 각 단계 완료 후 한 줄 보고하고 즉시 다음 단계로

## 사전 환경 확인 (매 실행 시)
- Python 패키지 누락 --> `pip install` 자동 실행
- node_modules 없음 --> `cd frontend-v2 && npm install` 자동 실행
- 백엔드 서버 필요 시 --> 자동 시작

---

## Gate 간 데이터 전달 프로토콜

각 Gate에서 다음 Gate로 넘길 때 TaskCreate의 description에 아래 구조를 포함한다:

### planner → architect/designer
```
affected_files: [변경 대상 파일 경로 목록]
safety_impact: {asil: "QM|A|B|C|D", traceability_update: true|false}
priority: P1|P2|P3
```

### architect → coder
```
interface_spec: {함수 시그니처 또는 API 엔드포인트}
data_flow: {입력 → 처리 → 출력 설명}
design_decisions: [{decision: "...", rationale: "..."}]
```

### coder → tester
```
changed_files: [실제 수정된 파일 경로 목록]
test_hints: [테스트 포인트 - 경계값, 에러 케이스 등]
safety_level: "QM|ASIL-A|ASIL-B|ASIL-C|ASIL-D"
```

### tester → reviewer
```
test_results: {passed: N, failed: N, skipped: N}
coverage_delta: {before: X%, after: Y%}
safety_tests: {asil_tests_passed: true|false}
```

---

### STEP 1: 분석 및 기획 (planner 에이전트)
- 관련 코드를 Glob/Grep/Read로 탐색
- 영향받는 파일 목록 파악
- 구현 계획 작성 후 **바로 보여주고 즉시 STEP 2로 진행** (승인 대기 없음)
  - 변경할 파일 + 변경 내용 요약
  - 신규 파일 (필요시)
  - 예상 리스크

---

### STEP 2: 코드 작성 (coder 에이전트)
- STEP 1 계획에 따라 코드 작성
- 작성 순서: 모델/스키마 --> 서비스 --> 라우터/API --> 프론트엔드 컴포넌트
- 각 파일 수정 시 기존 코드 스타일 준수
- TaskCreate/TaskUpdate로 진행 상황 추적

---

### STEP 3: 테스트 (tester 에이전트)
- `git diff --name-only`로 변경 파일 확인
- 관련 테스트 실행:
  ```bash
  python -m pytest tests/unit/ -q --tb=short
  ```
- 프론트엔드 변경 시:
  ```bash
  cd frontend-v2 && npm test
  ```
- **실패 시 자동 복구**: 원인 분석 --> 코드 수정 --> 재실행 (최대 3회)

---

### STEP 3.5: 추적성 검증 (ISO 26262)
- 변경된 코드가 요구사항과 매핑되는지 확인
- 요구사항 ID가 커밋/변경 내역에 포함되는지 검증
- 안전 관련 변경(ASIL C/D)이 있으면 STEP 4에서 reviewer 결과 필수 확인

---

### STEP 4: 셀프 리뷰 + 적응형 검증 루프 (reviewer 에이전트)

#### STEP 4 진입 전: review_depth 결정

review_depth 정의(meta/light/standard/deep), 키워드 트리거, ASIL 자동 판정, 변경 통계 측정 시점은 모두 **`.claude/agents/reviewer/reviewer.md` `## 검토 깊이 자동 판정`** 단일 출처를 따른다.

STEP 4에서의 동작:
- **meta** → STEP 4 생략, 메인이 정책 일관성(X4/X5/X6)만 점검
- **light** → STEP 4 생략 가능, CLAUDE.md 미니 체크리스트(10개) 의무 점검
- **standard** → reviewer 단일 호출 (S/P/Q/R/F + X1~X8 전체) → Critical 0이면 통과
- **deep** → 아래 적응형 3~5회 루프

#### deep depth: 적응형 검증 루프 (deep에서만 발동)

**아래 루프는 deep depth에서만 작동한다.** standard/light/meta는 위 절차로 종료. 기본 3회 루프, 진행 있으면 +1회씩 연장 (최대 5회 하드 제한).

```
prev_critical = None
round = 1
MIN_ROUNDS = 3
MAX_ROUNDS = 5

while round <= MAX_ROUNDS:
  (a) **deep-reviewer** 에이전트로 git diff 리뷰 (deep 전용 opus)
      - 보안 (S1~S5), 성능 (P1~P4), 품질 (Q1~Q4)
      - 프론트엔드 (R1~R7), ISO 26262 (F1~F8)
      - X1~X8 시나리오/timeline/트리 의무 (deep-reviewer.md)
      - 호출 실패 시 sonnet reviewer → 메인 미니 체크리스트 폴백

  (b) python scripts/quality_check.py --round {round} --json
      → counts.critical 읽기

  (c) Critical 있으면 coder에게 수정 위임

  (d) 진행/정체 판정:
      if current == 0 and round >= MIN_ROUNDS: break  # 정상
      if round >= MIN_ROUNDS and prev is not None:
          if current < prev: 계속  # 감소 = 진행
          else: break  # 정체/증가 = 중단 보고
      prev = current
      round += 1
```

**종료 조건**:
- **정상**: Critical 0 + 최소 3회 완료 → STEP 5
- **연장**: Critical 감소 중 → 다음 라운드 (최대 5회)
- **중단**: Critical 정체/증가 (3회 이상 시) → 사용자 보고
- **하드 캡**: 5회 도달 → 즉시 보고
- ASIL C/D 변경은 루프 중 reviewer LGTM 필수

---

### STEP 5: 커밋
- ASIL C/D 변경이 있으면 STEP 4 리뷰 결과가 LGTM인지 확인 후 커밋
- safety-critical 변경 시 커밋 전 reviewer 에이전트 결과를 반드시 확인
- 변경사항 전체 요약 출력
- `feat:` / `fix:` / `refactor:` 등 적절한 커밋 메시지로 **자동 커밋**
- 커밋 후 결과 보고:
  ```
  ## 워크플로우 완료
  기능: [기능명]
  변경 파일: N개
  테스트: X passed
  커밋: abc1234 "feat: ..."
  ```
