---
name: start-work
description: 모든 개발 작업의 진입점. 계획→설계→구현→테스트→리뷰→문서화를 강제하며, 변경 영역에 따라 적절한 에이전트를 자동 라우팅합니다.
trigger: 기능 추가, 버그 수정, 리팩토링, 개선, 구현, 개발, 만들어줘, 수정해줘, 고쳐줘, 변경해줘 등 코드 변경을 수반하는 모든 요청
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
   python -m pytest tests/unit/ -q --tb=short
   cd frontend-v2 && npm test  # 프론트엔드 변경 시
   ```
8. ISO 26262: 안전 관련 테스트(ASIL C/D) 실패 시 자동 수정하지 않고 보고

### Gate 4.5: 품질 평가 + Auto-retry (문서 생성 작업 시)

UDS/STS/SUTS 생성 작업인 경우, 생성 완료 후 자동으로 품질을 평가하고 필요 시 재시도합니다.

**평가 단계:**
```bash
python -c "
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

### Gate 5: 리뷰
9. **reviewer** 에이전트에 위임
   - 보안/성능/예외처리 점검
   - ISO 26262: MISRA-C 준수, ASIL 일관성, 추적성 검증

### Gate 6: 문서화
10. 변경내역 기록, 필요시 **documenter** 에이전트에 위임

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
