---
name: impact-analysis
description: C 소스 변경 감지 → 영향도 분석 → 문서 재생성 판정까지의 임팩트 분석 워크플로우를 실행합니다.
trigger: 소스 변경 영향도, 임팩트 분석, 변경 감지, 문서 재생성 판정 요청 시
---

# /impact-analysis 스킬

C 소스 코드 변경에 대한 영향도 분석을 수행하고 문서 재생성 여부를 판정합니다.

## 배경
- impact_orchestrator.py의 ACTION_MATRIX 기반
- 변경 유형: SIGNATURE, BODY, NEW, DELETE, HEADER
- 대상 문서: UDS, STS, SUTS, SITS, SDS

## 실행 순서

### 1. 변경 감지
```bash
# SCM 변경 파일 확인 (SVN 기반)
svn status | grep "\.c$\|\.h$"
```
- 변경된 C/H 파일 목록 수집
- 함수 단위 변경 분류 (HEADER/BODY/SIGNATURE/NEW/DELETE)

### 2. 영향도 분석
- `workflow/impact_orchestrator.py` 의 ACTION_MATRIX 참조
- call graph 탐색 (max_hop=2)
- 직접 영향 + 간접 영향 함수 식별

### 3. 문서 판정
| 변경 유형 | UDS | SUTS | SITS | STS | SDS |
|-----------|-----|------|------|-----|-----|
| BODY | AUTO | AUTO | AUTO | review | review |
| SIGNATURE | AUTO | AUTO | AUTO | review | review |
| HEADER | review | review | review | review | review |
| NEW | AUTO | AUTO | AUTO | AUTO | review |
| DELETE | AUTO | AUTO | AUTO | review | review |

### 4. 실행/보고
- `dry_run=false` 시 실제 문서 재생성
- audit log → `reports/impact_audit/`
- change log → `reports/impact_changes/`

## 출력
```markdown
# 영향도 분석 결과
- 분석일: {{date}}
- 변경 파일: {{count}}개

## 변경 함수
| 파일 | 함수 | 변경유형 | 직접영향 | 간접영향 |
|------|------|----------|----------|----------|

## 문서 판정
| 문서 | 판정 | 사유 |
|------|------|------|

## 다음 액션
- [ ] 자동 재생성 대상
- [ ] 수동 리뷰 대상
```

## 핵심 파일
- `workflow/impact_orchestrator.py` - 오케스트레이션 로직
- `report_gen/source_parser.py` - C 소스 파싱
- `report_gen/function_analyzer.py` - 함수 분석
- `config/scm_registry.json` - SCM 설정 (SVN, base rev 527)
