---
name: start-work
description: 코드 변경 작업의 **기본 진입점**. 계획→설계→구현→테스트→리뷰→문서화 Gate를 강제하고 변경 영역에 따라 에이전트를 자동 라우팅합니다. 긴급 명시 시엔 Gate를 생략하는 `/hotfix`, 고치지 않고 원인만 규명할 땐 `/debug-diagnose`가 대신 맡습니다.
when_to_use: |
  코드 변경을 수반하는 모든 요청 (아래 두 예외를 뺀 기본값). 신규 작업과 후속 지시 모두 포함:
  - 신규: 기능 추가, 버그 수정, 리팩토링, 개선, 구현, 개발, 만들어줘, 수정해줘, 고쳐줘, 변경해줘
  - 후속/연속: 다 고쳐, 다 수정, 이어서, 이어서 진행, 추가로, 다음 진행, 후속 처리, 계속 진행, 마저 해줘, 나머지도, 다른것도
  - 리뷰 후속: "1번부터 진행", "❶부터 고쳐", "Critical 수정해줘" 같이 직전 검토 결과를 기반으로 한 수정 지시
  제외 ①: 단순 정보 조회·설명·계획 논의 (예: "어떻게 동작해?", "계획만 보여줘")
  제외 ②: 긴급 명시("긴급/지금 당장/프로덕션 장애")→`/hotfix`, 원인 규명만("왜 안되지?", "왜 이렇게 됐어?")→`/debug-diagnose`
---

# /start-work (필수 진입점)

코드 변경이 필요한 모든 작업은 이 스킬을 거칩니다.
각 Gate에서 해당 에이전트에 위임하여 실행합니다.

## 자율 운영 원칙
- **묻지 않고 실행한다** — "할까요?" 금지, "했습니다"로 보고
- 환경 문제(패키지 누락, 서버 미실행 등)는 자동 해결 후 진행
- 단, **안전 관련 변경(ASIL C/D)** 시에는 reviewer 결과를 반드시 확인

## 자동 라우팅 규칙

변경 대상에 따라 적절한 에이전트를 선택합니다:

| 변경 영역 | 설계 에이전트 | 판별 기준 |
|-----------|-------------|-----------|
| `frontend-v2/` | **designer** | CSS, JSX, 컴포넌트, 레이아웃 |
| `backend/`, `workflow/`, `report_gen/` | **architect** | API, 모듈, 데이터 흐름 |
| `prompts/`, `workflow/uds_ai.py` | **prompt-engineer** | LLM 프롬프트, AI 파이프라인 |
| `generators/` | **architect** | STS/SUTS 생성 로직 |
| `tests/` | **tester** (설계 생략) | 테스트 추가/수정 |
| 복합 영역 | **architect** + **designer** 병렬 | 백엔드+프론트 동시 변경 |

## Gate 순서

### Gate 1: 계획 (건너뛸 수 없음)
1. **planner** 에이전트에 위임
   - 요구사항 분석, 관련 코드 탐색
   - 영향 범위 파악, 작업 분해, 리스크 식별
   - ISO 26262: 안전 영향도 평가, ASIL 분류
2. 계획서를 보여주고 **즉시 다음 Gate로 진행**

### Gate 2: 설계 (자동 라우팅)
3. 위 라우팅 규칙에 따라 에이전트 선택 → 위임
4. 설계안 작성 → 즉시 Gate 3로 진행

### Gate 3: 구현
5. **coder** 에이전트에 위임
6. 기존 패턴 분석 후 일관되게 구현

### Gate 4: 검증
7. **tester** 에이전트에 위임
   ```bash
   .venv/Scripts/python.exe -m pytest tests/unit/ -q --tb=short
   cd frontend-v2 && npm test  # 프론트엔드 변경 시
   ```
8. ISO 26262: 안전 관련 테스트(ASIL C/D) 실패 시 자동 수정하지 않고 보고

### Gate 4.5: 품질 평가 + Auto-retry (문서 생성 작업 시)

UDS/STS/SUTS 생성 작업인 경우, 생성 완료 후 자동으로 품질을 평가하고 필요 시 재시도합니다.

**평가 단계:**
```bash
.venv/Scripts/python.exe -c "
from workflow.quality.db import init_db, get_session
from workflow.quality.models import GenerationRun, QualitySummary
init_db()
with get_session() as s:
    run = s.query(GenerationRun).join(QualitySummary).order_by(GenerationRun.created_at.desc()).first()
    if run and run.summary:
        print(f'score={run.summary.overall_score:.1f} gate={run.summary.gate_pass} delta={run.summary.score_delta}')
        if not run.summary.gate_pass:
            from workflow.quality.advisor import suggest_improvements
            advice = suggest_improvements(run.id)
            for sg in advice.get('suggestions', []):
                print(f'  [{sg[\"priority\"]}] {sg[\"metric\"]}: {sg[\"value\"]:.1f}/{sg[\"threshold\"]} -> {sg[\"advice\"][:80]}')
" 2>/dev/null || echo "Quality DB not available (skip)"
```

**Auto-retry 판단:**
- `gate_pass=True` → Gate 5로 진행
- `gate_pass=False` + high priority 제안 있음 → **자동 재시도** (최대 1회):
  1. advisor 제안을 분석하여 **조정 가능한 파라미터** 식별
     - 프롬프트 변경 → prompt-engineer 에이전트에 위임
     - 파라미터 조정 → coder 에이전트가 config 수정 후 재실행
  2. 재생성 실행
  3. 품질 재평가 → 개선되었으면 Gate 5로, 아니면 결과 보고
- `gate_pass=False` + 조정 불가능 → 결과 보고

**Auto-retry 제한:**
- 최대 재시도 횟수: 1회 (무한 루프 방지)
- 재시도 후에도 gate_pass=False면 결과와 함께 보고

### Gate 5: 리뷰 + 문제점 검토 (적응형 검증 루프)

#### Gate 5 진입 전: review_depth 결정

review_depth (meta / light / standard / deep) 정의·키워드 트리거·ASIL 자동 판정·변경 통계 측정 시점은 모두 **`.claude/agents/reviewer/reviewer.md` `### 검토 깊이 자동 판정`** 단일 출처를 따른다.

Gate 5에서의 동작:
- **meta** → Gate 5 생략, 메인 에이전트가 X4/X5/X6 정책 일관성만 직접 점검
- **light** → Gate 5 생략 가능, 단 CLAUDE.md @import `self-review.md`의 미니 체크리스트(11개, X9 포함) 점검 의무
- **standard** → reviewer **단일 호출** (S/P/Q/R/F + X1~X9 전체). Critical 0이면 Gate 6, 있으면 1회 fix 후 재검토 1회만
- **deep** → 아래 **적응형 3~5회 루프** 발동

#### deep depth: 적응형 검증 루프 (deep에서만 발동)

**아래 루프는 deep depth에서만 작동한다.** standard/light/meta는 위 절차로 종료. 기본 3회 루프, 진행 있으면 +1회씩 연장 (최대 5회 하드 제한).
각 라운드마다 Critical 수를 비교해 **감소 → 연장**, **정체 → 중단 보고**.

#### 루프 진행 방식
```
prev_critical = None
round = 1
MIN_ROUNDS = 3
MAX_ROUNDS = 5  # hard cap to prevent infinite loop

while round <= MAX_ROUNDS:
    1. **deep-reviewer** 에이전트에 변경사항 리뷰 위임 (deep depth 전용 opus 모델)
       - 보안/성능/예외처리 (S1~S5, P1~P4, Q1~Q4)
       - 프론트엔드 코드 패턴 (R1~R7)
       - ISO 26262 (F1~F8): MISRA-C, ASIL, 추적성
       - X1~X9 비정형 비판 — **시나리오 / timeline / 트리** 의무 (deep-reviewer.md 참조)
       - deep-reviewer 호출 실패(403 등) 시 reviewer 로 폴백(모델은 같고 **의무가 얕다** — X1~X9 전수·timeline·트리가 빠진다), 그래도 실패하면 메인 에이전트 미니 체크리스트 11개
    
    2. 종합 품질 검사 실행:
       .venv/Scripts/python.exe scripts/quality_check.py --round {round} --json
       → JSON에서 counts.critical **과 verified/not_run** 읽기
    
    3. 이슈 분류 및 수정:
       - Critical: coder에게 수정 위임 → 다음 라운드 진입
       - Warning/Info (이번 작업 범위): 수정
    
    4. 진행/정체 판정:
       current_critical = result["counts"]["critical"]
       
       # ⚠ critical==0 은 "검증했고 깨끗함"이 아니라 "Critical로 분류된 게 없음"일 뿐이다.
       #    도구 부재(DISABLED)·타임아웃(TIMEOUT)·대응 테스트 없음(no_module_tests)·
       #    예산 초과(budget_exceeded)는 전부 Critical이 아니어서, 아무것도 안 돌렸는데도
       #    critical==0 이 나온다. verified=False 면 그 사실을 사용자에게 **명시 보고**하고
       #    "테스트 통과"라고 쓰지 말 것.
       if not result.get("verified", True):
           report(f"⚠ 미검증 항목: {result.get('not_run')} — 이 라운드는 회귀를 확인하지 못했다")
       
       if current_critical == 0:
           if round >= MIN_ROUNDS:
               break  # 정상 종료 → Gate 6 진행 (단, verified=False면 위 경고를 보고에 포함)
           # MIN_ROUNDS 미만이면 계속 (플레이키 탐지)
       
       elif prev_critical is not None:
           if current_critical < prev_critical:
               # 진행 있음: round < MAX_ROUNDS면 계속
               pass
           elif round >= MIN_ROUNDS:
               # 정체 또는 증가: 중단
               break
           # MIN_ROUNDS 미만이면 계속 시도
       
       prev_critical = current_critical
       round += 1
```

#### 라운드별 집중 영역 (권장)
- **Round 1**: 기능 정확성 (테스트 실패, 빌드 오류, 문법)
- **Round 2**: 코드 품질 (null guard, 예외 처리, 명명)
- **Round 3**: 엣지 케이스, 리그레션
- **Round 4~5 (연장)**: Critical 잔존 항목 집중 수정

#### 종료 조건
- **정상**: Critical 0건 + 최소 3회 완료 → Gate 6
- **연장**: Critical > 0 & 감소 중 → 다음 라운드 (최대 5회)
- **중단**: Critical 정체/증가 (3회 이상 시) → 사용자에게 보고
- **하드 캡**: 5회 도달 → 즉시 보고 (무한 루프 방지)
- **ASIL C/D**: 루프 안에서도 reviewer LGTM 필수

#### 판정 예시
```
Round 1: Critical 5 → 수정
Round 2: Critical 3 (감소) → 계속
Round 3: Critical 1 (감소) → 계속 (MIN_ROUNDS 도달)
Round 4: Critical 0 → 종료 ✓

vs.

Round 1: Critical 5 → 수정
Round 2: Critical 5 (정체) → 아직 MIN_ROUNDS 미만, 계속
Round 3: Critical 5 (정체) → 중단, 사용자 보고 ✗
```

### Gate 6: 문서화
9. 변경내역 기록, 필요시 **documenter** 에이전트에 위임

## 게이트 생략 조건

### 설계(Gate 2) 생략 가능
- 단일 파일 내 10줄 미만 수정
- 오타/주석/설정값 변경

### 긴급 핫픽스 (사용자가 "긴급" 명시)
- Gate 2(설계) 생략 가능
- Gate 1(계획)은 여전히 필수 (간소화된 형태)
- 단, ASIL C/D 함수 변경 시 Gate 5(리뷰) 필수

### 탐색/조사 전용
- 코드 변경 없이 읽기만 → 이 스킬 불필요
