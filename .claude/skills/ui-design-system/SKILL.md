---
name: ui-design-system
description: React 프론트엔드의 디자인 시스템을 구축합니다. 디자인 토큰, CSS 변수화, 토스트/다이얼로그 컴포넌트, 상태 표준화.
when_to_use: 디자인 토큰, CSS 변수, 하드코딩 컬러, 토스트, 확인 다이얼로그, UI 컴포넌트 표준화 요청 시
---

# /ui-design-system 스킬

프론트엔드 디자인 시스템을 체계적으로 구축합니다.

> ⚠ 아래 수치는 **작성 시점의 스냅샷**이다. 착수 전 재측정할 것:
> `grep -rn "style=" frontend-v2/src --include="*.jsx" | grep -cE "#[0-9a-fA-F]{3,6}|rgb\("`
> (2026-07-17 재측정 = 117건 — "100+" 표기는 아직 유효)

## 현재 문제
- 100+ 하드코딩된 컬러가 코드 전체에 산재
- 일관된 spacing/typography 스케일 없음
- 토스트 알림 없음 (alert() 사용)
- 5개 삭제 작업에 확인 다이얼로그 없음
- 15+ 인터랙티브 요소에 hover/focus 상태 없음

## 대상 파일
- `frontend-v2/src/index.css` — **유일한 최상위 CSS** (2026-07-17 실측 1,817줄)
- `frontend-v2/src/App.jsx` (2026-07-17 실측 382줄)
- `frontend-v2/src/views/` 내 리포트 뷰들
- `frontend-v2/src/components/` 공통 컴포넌트

> ⚠ 과거 이 절은 `App.css`(4,500+줄)·`App.jsx`(5,015줄)를 지목했는데 **App.css 는
> 존재하지 않고** App.jsx 는 실제 382줄(13배 차이)이었다. 착수 전 `ls`/`wc -l` 로
> 재측정할 것 — 없는 파일을 대상으로 잡으면 아래 검증이 **fake-green** 이 된다.

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

> ⚠ **대상 파일 존재를 먼저 확인**하고 grep 할 것. 없는 파일을 grep 하면 출력이
> 비어 `wc -l` 이 **0** 을 내고, 그게 "목표: 0 충족"으로 읽힌다 — 실제로 이 절이
> 존재하지 않는 `App.css` 를 grep 해 **영원히 통과**하고 있었다(fake-green).
> 이 저장소가 훅에서 온종일 싸운 바로 그 패턴이다.

```bash
# 0) 대상 존재 확인 — 이게 없으면 아래 결과는 무의미
ls -l frontend-v2/src/index.css

# 하드코딩 컬러 잔존 확인 (inline style + CSS 양쪽)
grep -rnE "#[0-9a-fA-F]{3,6}|rgb\(" frontend-v2/src --include="*.css" --include="*.jsx" | wc -l
#   → 목표: 감소 추세. 2026-07-17 실측 baseline = 117 (inline style 기준)
#     "0" 을 목표로 적지 말 것 — 위 fake-green 을 다시 만든다

# 빌드 확인
cd frontend-v2 && npm run build

# 회귀 테스트
cd frontend-v2 && npm test
```
