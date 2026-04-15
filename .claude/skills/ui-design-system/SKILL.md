---
name: ui-design-system
description: React 프론트엔드의 디자인 시스템을 구축합니다. 디자인 토큰, CSS 변수화, 토스트/다이얼로그 컴포넌트, 상태 표준화.
trigger: 디자인 토큰, CSS 변수, 하드코딩 컬러, 토스트, 확인 다이얼로그, UI 컴포넌트 표준화 요청 시
---

# /ui-design-system 스킬

프론트엔드 디자인 시스템을 체계적으로 구축합니다.

## 현재 문제
- 100+ 하드코딩된 컬러가 코드 전체에 산재
- 일관된 spacing/typography 스케일 없음
- 토스트 알림 없음 (alert() 사용)
- 5개 삭제 작업에 확인 다이얼로그 없음
- 15+ 인터랙티브 요소에 hover/focus 상태 없음

## 대상 파일
- `frontend-v2/src/App.css` (4,500+ 줄)
- `frontend-v2/src/App.jsx` (5,015 줄)
- `frontend-v2/src/views/` 내 리포트 뷰들
- `frontend-v2/src/components/` 공통 컴포넌트

## P0 작업 (Critical)

### A: 디자인 토큰 시스템
```css
:root {
  /* Spacing */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;
  
  /* Typography */
  --font-size-sm: 0.875rem;
  --font-size-md: 1rem;
  --font-size-lg: 1.25rem;
  
  /* Colors - semantic */
  --color-primary: ...;
  --color-success: ...;
  --color-warning: ...;
  --color-error: ...;
  --color-bg: ...;
  --color-surface: ...;
  --color-text: ...;
  --color-text-secondary: ...;
  --color-border: ...;
}
```

### B: 하드코딩 컬러 → CSS 변수 교체
```bash
# 하드코딩 컬러 탐색
grep -rn "#[0-9a-fA-F]\{3,6\}" frontend-v2/src/ --include="*.css" --include="*.jsx"
grep -rn "rgb(" frontend-v2/src/ --include="*.css" --include="*.jsx"
```

### C: 토스트 알림 컴포넌트
- 유형: success / error / warning / info
- 자동 닫힘 (3초)
- 스택 가능
- alert() 호출을 모두 교체

### D: 확인 다이얼로그
- 삭제 작업 5개에 적용
- "정말 삭제하시겠습니까?" 패턴

## P1 작업 (High)
- E: hover/focus 상태 추가
- F: 로딩 스피너 표준화
- G: 빈 상태 UI 패턴

## 검증
```bash
# 하드코딩 컬러 잔존 확인
grep -rn "#[0-9a-fA-F]\{6\}" frontend-v2/src/App.css | wc -l  # 목표: 0

# 빌드 확인
cd frontend-v2 && npm run build

# 회귀 테스트
cd frontend-v2 && npm test
```
