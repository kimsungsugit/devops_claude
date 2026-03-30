# 전체 웹 UI 종합 개선 계획

## 현황 진단 요약

| 영역 | 현재 상태 | 심각도 |
|------|-----------|--------|
| 디자인 시스템 | 하드코딩 색상 100+ 곳, spacing/typography 스케일 없음 | 높음 |
| UX 패턴 | 토스트 시스템 없음, 삭제 확인 누락 5곳, alert() 사용 | 높음 |
| 접근성 | hover/focus 누락 15+ 곳, aria-label 부재, outline:none | 중간 |
| 로딩/빈 상태 | 전역 스피너 없음, 빈 상태 아이콘 없음 | 중간 |
| 코드 품질 | App.jsx 5,015줄, useState 161개, prop drilling | 높음 (별도 계획) |

### 핵심 파일

- `frontend/src/App.css` - 전체 스타일 (4,500+ 줄)
- `frontend/src/App.jsx` - 메인 앱 (5,015줄)
- `frontend/src/views/ExcelCompare.jsx` - 인라인 스타일 다수
- `frontend/src/views/VCastReportGenerator.jsx` - 인라인 스타일 다수
- `frontend/src/views/QACReportGenerator.jsx` - 인라인 스타일 다수
- `frontend/src/views/JenkinsDashboard.jsx` - 인라인 색상
- `frontend/src/views/JenkinsWorkflow.jsx` - 인라인 색상
- `frontend/src/views/LocalWorkflow.jsx` - 인라인 색상

---

## [P0] A. 디자인 토큰 시스템 구축

**대상:** `App.css` `:root` 섹션 (라인 1-50)

**현황:** CSS 변수는 기본 색상/배경에 존재하나, spacing/typography/상태색/radius/shadow/transition 변수가 체계적으로 정의되지 않음. `:root`와 `body[data-theme='light']`에서 동일 변수 중복 정의.

**개선:**

1. spacing 스케일 변수 추가: `--sp-1: 4px`, `--sp-2: 8px`, `--sp-3: 12px`, `--sp-4: 16px`, `--sp-6: 24px`
2. typography 스케일: `--text-xs: 10px`, `--text-sm: 11px`, `--text-base: 12px`, `--text-md: 13px`, `--text-lg: 14px`
3. 상태 색상 변수: `--color-success: #22c55e`, `--color-warning: #f59e0b`, `--color-danger: #ef4444`, `--color-info: #3b82f6` + 각각의 `soft` 변형
4. border-radius: `--radius-sm: 4px`, `--radius-md: 6px`, `--radius-lg: 8px`, `--radius-xl: 12px`
5. transition: `--transition-fast: 0.15s ease`, `--transition-normal: 0.2s ease`
6. shadow: `--shadow-sm`, `--shadow-md`, `--shadow-lg`
7. `:root`와 `body[data-theme='light']` 중복 정의 정리

---

## [P0] B. 하드코딩 색상/인라인 스타일 제거

**대상:** 다수 파일

**현황:**
- App.css에 `#ef4444`, `#22c55e`, `#f59e0b`, `#3b82f6`, `#fff` 등 60+ 곳
- ExcelCompare.jsx에 `#666`, `#f8d7da`, `#d4edda` 등 인라인 스타일 20+ 곳
- VCastReportGenerator.jsx에 `#007bff`, `#28a745`, `#dc3545` 등 15+ 곳
- QACReportGenerator.jsx에 유사 패턴 20+ 곳
- JenkinsDashboard/Workflow에 `#666`, `#f00` 등

**개선:**

1. App.css의 하드코딩 색상을 A에서 정의한 변수로 교체
2. ExcelCompare, VCastReportGenerator, QACReportGenerator의 인라인 스타일을 CSS 클래스로 전환
3. JenkinsDashboard/Workflow의 인라인 `#666` 등을 `var(--muted)` 등으로 교체
4. Prism 토큰 색상 (라인 3158-3202)을 CSS 변수화

---

## [P0] C. 토스트 알림 시스템 도입

**대상:** `App.jsx`, 새 컴포넌트 `Toast.jsx`

**현황:** 사용자 피드백이 `setMessage()` 텍스트로만 처리. 메시지 사라지는 타이밍 불명확. 성공/에러/경고 시각적 구분 없음. `alert()` 사용 1곳 (`App.jsx:4294`).

**개선:**

1. 경량 토스트 컴포넌트 `frontend/src/components/Toast.jsx` 생성
   - 성공(녹색), 에러(빨간색), 경고(노란색), 정보(파란색) 4가지 타입
   - 자동 사라짐 (3초) + 수동 닫기 버튼
   - 화면 우상단 스택 형태
   - 슬라이드 인/아웃 애니메이션
2. `showToast(type, text)` 함수를 App.jsx에 추가
3. 주요 `setMessage()` 호출을 `showToast`로 점진적 전환
4. `alert()` 제거하고 토스트로 교체

---

## [P0] D. 삭제 확인 다이얼로그

**대상:** `App.jsx`

**현황:** 프로파일 삭제만 확인 다이얼로그 존재 (라인 4989-5009). 나머지 5개 삭제 작업에 확인 없음:
- `deleteKb()` (라인 ~1201) - 지식베이스 삭제
- `deleteSession()` (라인 ~3149) - 세션 삭제
- `deleteExport()` (라인 ~3262) - 백업 삭제
- `deleteUdsVersion()` (라인 ~2260) - UDS 버전 삭제
- `handleChatDeleteMsg()` - 채팅 메시지 삭제

**개선:**

1. 범용 확인 모달 컴포넌트 `frontend/src/components/ConfirmDialog.jsx` 생성
   - 제목, 메시지, 확인/취소 버튼
   - 위험 액션은 빨간색 확인 버튼
   - 키보드 지원 (Enter=확인, Escape=취소)
2. 모든 삭제 작업에 확인 다이얼로그 적용
3. 기존 프로파일 삭제 모달도 공통 컴포넌트로 통합

---

## [P1] E. 인터랙티브 요소 hover/focus 상태 보완

**대상:** `App.css`

**현황:** 15개 이상의 인터랙티브 요소에 hover/focus 상태 미적용:
- `.segmented-btn`, `.theme-toggle`, `.tabs button`
- `.metric-filter-btn`, `.metric-chip`, `.status-chip`
- `.tool-card`, `.summary-card`, `.card`
- `.export-row`, `.detail-row`, `.report-tree-folder`
- `outline: none` 사용 (라인 732, 3596)

**개선:**

1. 모든 클릭 가능 요소에 hover 상태 추가 (배경색 변경 또는 border 강조)
2. `outline: none` 제거 → `:focus-visible` 상태로 교체 (키보드 사용자만 보이도록)
3. 공통 포커스 링 스타일: `box-shadow: 0 0 0 2px var(--accent)`
4. 카드 hover 시 미세한 `translateY(-1px)` + `box-shadow` 추가

---

## [P1] F. 로딩 상태 표준화

**대상:** `App.css`, 각 뷰 파일

**현황:** 전역 로딩 인디케이터 없음. 버튼 텍스트만 "로딩 중..."으로 변경. 로딩 스피너 CSS 클래스 부재.

**개선:**

1. CSS 스피너 애니메이션 클래스 `.spinner` 추가 (8px/16px/24px 3가지 크기)
2. 버튼 로딩 상태: 텍스트 + 미니 스피너 조합 `.btn-loading` 클래스
3. 패널/카드 로딩: 내부에 스피너 중앙 배치 `.panel-loading`
4. 전체 화면 로딩: 상단에 얇은 프로그레스 바 `.top-progress-bar`

---

## [P1] G. 빈 상태(Empty State) 표준화

**대상:** `App.css`, 각 뷰 파일

**현황:** `.empty` 클래스에 단순 텍스트만 표시. 아이콘/일러스트레이션 없음.

**개선:**

1. 빈 상태 패턴 표준화: 아이콘 + 설명 텍스트 + 액션 버튼(선택)
2. 상황별 빈 상태 메시지: 데이터 없음, 검색 결과 없음, 에러 발생
3. `.empty-state` CSS 클래스: 중앙 정렬 + 약간 큰 아이콘 + 회색 텍스트

---

## [P2] H. 스크롤바/테이블 UX 개선

**대상:** `App.css`

**현황:** 커스텀 스크롤바 없음. 테이블 정렬 기능 없음.

**개선:**

1. 커스텀 스크롤바 스타일: 얇은 트랙 + 둥근 썸 + 다크모드 대응
   - `::-webkit-scrollbar`, `scrollbar-width: thin`, `scrollbar-color`
2. 긴 셀 텍스트에 `text-overflow: ellipsis` 적용 표준화

---

## [P2] I. 접근성(a11y) 기본 보강

**대상:** `App.jsx`, `PrimaryNav.jsx`, `AppHeader.jsx`

**현황:** ARIA 레이블 거의 없음. 시맨틱 랜드마크 일부만 사용.

**개선:**

1. PrimaryNav 버튼에 `aria-label` 추가
2. AppHeader 버튼에 `aria-label` 추가
3. 주요 영역에 `role` 속성 추가 (navigation, main, complementary)
4. 모달/드로어에 `aria-modal`, `aria-labelledby` 추가
5. `console.log/error` 정리: 개발 환경에서만 출력되도록 조건부 처리

---

## [P3] J. 전역 키보드 단축키

**대상:** `App.jsx`

**현황:** 에디터에만 단축키 존재. 전역 단축키 없음.

**개선:**

1. `Ctrl+1~5`: 탭 전환 (대시보드/워크플로우/에디터/분석기/설정)
2. `Ctrl+/`: 챗봇 토글
3. `?` 또는 `F1`: 단축키 도움말 표시
4. 풋터 또는 사이드바에 "단축키" 링크 추가

---

## 우선순위 요약

| 우선순위 | 항목 | 예상 작업량 |
|----------|------|-------------|
| **P0 (필수)** | A. 디자인 토큰 | 중 |
| **P0 (필수)** | B. 하드코딩 색상 제거 | 대 |
| **P0 (필수)** | C. 토스트 시스템 | 중 |
| **P0 (필수)** | D. 삭제 확인 다이얼로그 | 중 |
| **P1 (높음)** | E. hover/focus 보완 | 중 |
| **P1 (높음)** | F. 로딩 표준화 | 중 |
| **P1 (높음)** | G. 빈 상태 표준화 | 소 |
| **P2 (중간)** | H. 스크롤바/테이블 | 소 |
| **P2 (중간)** | I. 접근성 보강 | 중 |
| **P3 (낮음)** | J. 전역 단축키 | 소 |

---

## [검증] K. 종합 검증 및 회귀 테스트

**목적:** A~J의 모든 변경사항이 기존 기능을 손상시키지 않았는지 체계적으로 검증

### K-1. 빌드 검증

1. `npm run build` 성공 확인 (에러/경고 0)
2. 빌드 결과물 크기 확인 (이전 대비 비정상적 증가 없는지)
3. `ReadLints` 로 모든 수정 파일의 린터 에러 0 확인

### K-2. CSS 변수 무결성 검증

1. `:root`에 정의된 모든 디자인 토큰 변수가 실제 사용되는지 확인
2. CSS에서 `var(--` 참조하는 변수가 모두 `:root` 또는 테마에 정의되어 있는지 확인
3. 다크 모드 테마(`body[data-theme='dark']`)에서 모든 토큰 변수에 대응 값이 존재하는지 확인
4. 하드코딩 색상 잔존 여부: App.css에서 `#fff`, `#000`, `#666`, `#ef4444`, `#22c55e`, `#f59e0b`, `#3b82f6` 직접 사용 검색 → 0건 목표

### K-3. 인라인 스타일 잔존 검증

1. ExcelCompare.jsx에서 `style={{` 검색 → 동적 크기 외에는 0건 목표
2. VCastReportGenerator.jsx에서 `style={{` 검색 → 동적 크기 외에는 0건 목표
3. QACReportGenerator.jsx에서 `style={{` 검색 → 동적 크기 외에는 0건 목표
4. JenkinsDashboard.jsx, JenkinsWorkflow.jsx에서 하드코딩 색상 `style` 0건 목표

### K-4. 기능 동작 검증 (브라우저)

1. **라이트/다크 모드 전환**: 토글 후 모든 요소가 올바른 색상으로 표시되는지
2. **토스트 알림**: 성공/에러/경고/정보 각 타입이 올바른 색상으로 표시되고, 3초 후 자동 사라지는지
3. **삭제 확인 다이얼로그**:
   - 지식베이스 삭제 → 확인 모달 표시 확인
   - 세션 삭제 → 확인 모달 표시 확인
   - 백업 삭제 → 확인 모달 표시 확인
   - UDS 버전 삭제 → 확인 모달 표시 확인
   - 프로파일 삭제 → 기존 동작 유지 확인
   - 취소 시 삭제되지 않음 확인
   - Escape 키로 모달 닫힘 확인
4. **hover/focus 상태**: 주요 버튼, 카드, 탭에 마우스 올리면 시각적 피드백 있는지
5. **로딩 스피너**: API 호출 시 버튼에 스피너 표시되는지
6. **빈 상태**: 데이터 없는 화면에서 아이콘+메시지가 올바르게 표시되는지
7. **스크롤바**: 긴 목록에서 커스텀 스크롤바가 표시되는지
8. **키보드 단축키**: `Ctrl+1~5` 탭 전환, `Ctrl+/` 챗봇 토글 동작 확인

### K-5. 탭별 화면 이상 유무

1. **대시보드 탭 (로컬)**: 메트릭 카드, KPI, 리포트 목록 정상 표시
2. **대시보드 탭 (젠킨스)**: 빌드 히스토리, 타임라인, 상태 표시 정상
3. **워크플로우 탭 (로컬)**: 테스트 요약, 커버리지 테이블, 품질 그룹 정상
4. **워크플로우 탭 (젠킨스)**: 실행 설정, 미리보기, 결과 정상
5. **에디터 탭**: 파일 탐색기, 코드 편집, AI 가이드, 정적분석 결과 정상
6. **분석기 탭 (UDS)**: UDS 업로드, 상세정보 탭들, 그래프 정상
7. **설정 탭**: 프로파일, 프로젝트 설정, Jenkins 설정 정상
8. **챗봇 사이드바**: 대화, 프리셋, 소스 배지, 마크다운 렌더링 정상

### K-6. 반응형/모바일 검증

1. 1100px 이하: 챗봇 FAB + 드로어 정상 동작
2. 1200px 이하: 레이아웃 축소 정상
3. 2000px 이상: 넓은 화면에서 레이아웃 깨지지 않음

### K-7. 접근성 검증

1. Tab 키로 주요 요소 순회 가능
2. 포커스 시 시각적 표시(포커스 링) 존재
3. aria-label이 적용된 요소들이 올바른 설명을 가지는지

---

## 우선순위 요약 (최종)

| 우선순위 | 항목 | 예상 작업량 |
|----------|------|-------------|
| **P0 (필수)** | A. 디자인 토큰 | 중 |
| **P0 (필수)** | B. 하드코딩 색상 제거 | 대 |
| **P0 (필수)** | C. 토스트 시스템 | 중 |
| **P0 (필수)** | D. 삭제 확인 다이얼로그 | 중 |
| **P1 (높음)** | E. hover/focus 보완 | 중 |
| **P1 (높음)** | F. 로딩 표준화 | 중 |
| **P1 (높음)** | G. 빈 상태 표준화 | 소 |
| **P2 (중간)** | H. 스크롤바/테이블 | 소 |
| **P2 (중간)** | I. 접근성 보강 | 중 |
| **P3 (낮음)** | J. 전역 단축키 | 소 |
| **최종** | K. 종합 검증 | 중 |

> 참고: App.jsx 5,015줄 리팩토링(커스텀 훅 분리, Context API 도입, 코드 스플리팅)은 별도 대규모 계획으로 분리 권장합니다.
