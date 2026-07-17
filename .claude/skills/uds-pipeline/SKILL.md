---
name: uds-pipeline
description: UDS(Unit Design Specification) 문서 생성 파이프라인을 실행합니다. C 소스 파싱 → AI 분석 → 품질 검증 → DOCX 빌드 전 과정.
trigger: UDS 생성, 문서 생성 파이프라인, 단위설계서 작성 요청 시
---

# /uds-pipeline 스킬

C 소스 코드로부터 UDS 문서를 자동 생성하는 전체 파이프라인을 실행합니다.

## 파이프라인 단계

### Stage 1: 소스 파싱
- `report_gen/source_parser.py` → C 함수 추출
- 입력: `libs/*.c`, include paths: libs/, include/, tests/
- 출력: 함수 시그니처, 입출력, 전역변수, 호출관계

### Stage 2: AI 분석 강화
- `workflow/uds_ai.py` → Gemini API 호출
- 프롬프트 체인:
  1. `uds_analysis.txt` - 입력 완전성 분석, 갭 식별
  2. `uds_writer.txt` - UDS 본문 생성 (증거 기반)
  3. `uds_logic.txt` - 로직 다이어그램 생성
  4. `uds_reviewer.txt` - 품질 검증 (accept/retry/reject)
  5. `uds_auditor.txt` - ISO 26262 준수 감사

### Stage 3: 품질 검증
- `report_gen/validation.py`
- 체크: JSON 포맷, 증거 근거, 추적성, ASIL 등급, 일관성
- **핵심 원칙**: 사실 없이 작성 금지, 증거 없으면 "N/A"

### Stage 4: 문서 빌드
- `report_gen/docx_builder.py` → DOCX 조립
- 템플릿: `templates/` 디렉토리
- 출력: `reports/` 디렉토리

## 실행 모드

⚠ `from workflow.impact_orchestrator import run` 은 **존재하지 않는 심볼**이었다(ImportError).
유일한 엔트리포인트는 `run_impact_update(trigger, *, options=None, on_progress=None)` 이고,
`dry_run`/`auto_generate` 는 **함수 인자가 아니라 `ChangeTrigger` 속성**이다.

```bash
# 드라이런 (검증만) — 맨 python 금지, .venv 필수 (rules/autonomous-operation.md)
.venv/Scripts/python.exe -c "
from workflow.change_trigger import ChangeTrigger
from workflow.impact_orchestrator import run_impact_update
t = ChangeTrigger(
    trigger_type='manual', scm_id='<scm_id>', source_root='<source_root>',
    scm_type='svn', base_ref='<rev>', changed_files=['a.c'],
    dry_run=True,
)
print(run_impact_update(t))
"

# 실제 생성 (AUTO 대상 실행 — auto_generate=False 면 AUTO→FLAG 로 강등된다)
.venv/Scripts/python.exe -c "
from workflow.change_trigger import ChangeTrigger
from workflow.impact_orchestrator import run_impact_update
t = ChangeTrigger(
    trigger_type='manual', scm_id='<scm_id>', source_root='<source_root>',
    scm_type='svn', base_ref='<rev>', changed_files=['a.c'],
    dry_run=False, auto_generate=True,
)
print(run_impact_update(t))
"
```
`scm_id`/`source_root`/`base_ref` 는 `config/scm_registry.json` 의 등록값을 쓸 것
(현재 hdpdm01 / kjpds02 / kjpds02_pv 3개 — 아래 §참고 파일).
탐색 범위 조정은 `ImpactOptions(max_hop=…, same_module_only=…)` 를 `options=` 로 전달.

## 품질 게이트
- [ ] 모든 함수에 증거 근거 있음
- [ ] reviewer가 accept 판정
- [ ] auditor가 ISO 26262 적합 판정
- [ ] 요구사항 추적성 100%

## 현재 이슈 (실사용 완성도 계획서 기준)
- dry_run=false 실행 검증 필요
- 5개 대표 시나리오 테스트 필요:
  - A: BODY 변경 (단일 함수)
  - B: HEADER/SIGNATURE 변경 (인터페이스)
  - C: 다중 파일 동시 변경
  - D: 재생성 불필요 케이스
  - E: SITS 통합 플로우
