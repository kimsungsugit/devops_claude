---
name: report-quality
description: 보고서 품질을 검증하고 개선합니다. analysis_summary 확장, 커버리지 정규화, 정적분석 결과 통합, Domain Tests 수정.
trigger: 보고서 품질, 리포트 개선, analysis_summary, 커버리지 정규화, Clang-Tidy 요청 시
---

# /report-quality 스킬

파이프라인 보고서의 품질을 검증하고 개선 작업을 수행합니다.

## 현재 문제점 (계획서 기준)
1. `analysis_summary.md` 38줄 → 상세 메트릭 부족
2. Clang-Tidy 결과 파일 미저장 (메모리만)
3. Fuzzing 통합 요약 누락
4. Domain Tests "no scenarios produced" 오류
5. QEMU 리포트 깊이 부족
6. 커버리지 수치 불일치 (72.8% vs 94%)

## Phase 1 작업 (Backend - High Priority)

### 1-1: analysis_summary.md 확장
- 단계별 상세 메트릭 추가
- 커버리지 테이블 포함
- Fuzzing 상세 정보
- 정적 분석 요약

### 1-2: Clang-Tidy JSON 출력
- 결과를 파일로 저장하도록 수정
- JSON 포맷 표준화

### 1-4: 커버리지 정규화
- libs-only vs total 커버리지 분리
- 실제 gcovr 출력과 일치시키기

### 1-5: Domain Tests 수정
- AI 모델 호출 오류 해결
- "no scenarios produced" 원인 분석

### 1-6: QEMU 리포트 강화
- soft-fail 설명 추가
- meta.json 외 상세 정보

## 검증 방법
```bash
# 테스트 실행
pytest tests/unit/ -v --tb=short -k "report"

# analysis_summary 확인
cat reports/analysis_summary.md | wc -l  # 목표: 100줄+

# 커버리지 비교
python -c "import json; print(json.load(open('reports/coverage.json'))['line_rate'])"
```

## 출력
```markdown
# 보고서 품질 검증 결과

## 체크리스트
| 항목 | 상태 | 상세 |
|------|------|------|
| analysis_summary 줄 수 | {{pass/fail}} | {{줄 수}} |
| Clang-Tidy 파일 존재 | {{pass/fail}} | {{경로}} |
| 커버리지 수치 일치 | {{pass/fail}} | libs: {{%}} / total: {{%}} |
| Domain Tests 실행 | {{pass/fail}} | {{시나리오 수}} |
| QEMU 상세 리포트 | {{pass/fail}} | {{항목 수}} |

## 수정 필요 항목
{{상세 내용}}
```
