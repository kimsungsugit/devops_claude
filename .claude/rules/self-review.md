# 작업 종료 직전 비판적 자체 검토 (필수)

> CLAUDE.md `@import` 모듈 — 세션 시작 시 항상 로드. 매 commit 직전 적용되는 검토/보고 정책.

코드 변경 작업을 마치고 사용자에게 완료 보고하기 직전, **변경 규모에 맞는 깊이로 reviewer 에이전트를 호출**하여 비판적 자체 검토를 수행한다. PostToolUse hook의 syntax/lint는 기계적 검사일 뿐 설계·논리·동시성 같은 비판적 검토를 대체하지 않는다.

**review_depth 정의 단일 출처**: `.claude/agents/reviewer/reviewer.md` `### 검토 깊이 자동 판정` 섹션을 참조. meta / light / standard / deep 4단계, 키워드 강제 승격, ASIL 자동 판정, 변경 통계 측정 시점 모두 거기에 정의돼 있다. 본 문서와 SKILL.md들은 그 정의를 그대로 따른다.

## 호출 정책 (review_depth 별)
- **meta** (정책/문서만 변경) → reviewer 생략, 메인 에이전트가 X4/X5/X6만 직접 점검
- **light** → reviewer 생략 가능, 단 미니 체크리스트(아래) 11개 항목은 메인이 직접 점검
- **standard** → reviewer **1회 호출** (S/P/Q/R/F + X1~X9 전체)
- **deep** → reviewer 적응형 3~5회 루프 (start-work Gate 5와 동일)
- **혼합형** (코드 + 문서 동시 변경) → reviewer.md `### 검토 깊이 자동 판정` `#### 혼합형` 규칙 적용 — 코드/문서 그룹 분리 후 max(depth) 채택, 출력에 정책 일관성 섹션 별도 보고

## 생략 조건 (light로 강등)
- 사용자가 "검토 생략" / "리뷰 없이" / "빠르게" 명시
- 단순 lint/포맷 자동 수정만 발생

## 보고 방식
- 발견된 Critical / Warning / Info를 표로 즉시 보고
- X1~X9 점검 결과는 매 reviewer 호출의 출력에 표 형태로 **반드시** 포함
- Critical은 사용자 확인 후 자동 수정 시도, Warning/Info는 보고만
- **능동 보고 (필수)**: 사용자가 "문제점은 없니?"를 묻기 전에 **매 commit 직전** 응답에 (1) 변경 요약 표, (2) X1~X9 mini-checklist 표, (3) 잠재 문제점 표(있으면), (4) 결론 1줄을 자동 포함한다. 이 패턴은 세션 메모리 `[[feedback_critical_review_style]]`(사용자 합의 사항)에 근거한다. *(본 문서의 `[[name]]` 표기는 세션 메모리 참조 — 없어도 각 항목의 요지는 인라인되어 자기완결적이다.)*
- **입력 표면 매트릭스 (보안 경계 변경 시 필수)**: 권한 layer / 미들웨어 / handler / resolver 변경 또는 사용자 입력 endpoint 5개+ 추가 시 능동 보고에 (5) **입력 표면 매트릭스**를 추가한다. 행=입력 채널(JSON 단일/JSON list/JSON nested/Query/Form string/multi-path string/UploadFile/SSE/WebSocket/Cookie/Header), 열=검사 layer(미들웨어/endpoint/resolver), 셀=검사됨/우회/N/A. 빈 셀 또는 "우회"는 즉시 결함. fix 후 매 라운드 메타-점검: "이 fix가 같은 패턴의 다른 입구를 노출시키는가?" → whack-a-mole 방지. 상세는 세션 메모리 `[[feedback_input_surface_matrix]]`.
- 검토 결과 "이상 없음"이면 한 줄로 표시 후 마무리

## reviewer 호출 실패 (403 등) 시 또는 light depth 시 메인 에이전트 미니 체크리스트

매 항목을 직접 점검하고 결과 표를 보고. "확인 안 함"은 금지, 결정 못 하면 Issue로 표시.

| # | 카테고리 | 점검 |
|---|----------|------|
| 1 | S1 (injection) | f-string SQL/command, `subprocess.*shell=True` 스캔 |
| 2 | S3 (path traversal) | `open(request.*)`, `Path(request.*)` 스캔 |
| 3 | Q1 (broad except) | `except:`, `except Exception:` 위치 |
| 4 | R2 (null guard) | 변경 파일의 `.map(` 호출이 `?.`/`Array.isArray`/`\|\| []`로 보호되는지 |
| 5 | X1 (race) | 변경 함수가 공유 상태(global/class attr/file/in-memory cache)를 lock 없이 수정하는지 |
| 6 | X2 (hook deps) | useEffect/useCallback/useMemo의 deps가 본문 참조 변수 모두 포함하는지 |
| 7 | X3 (계약) | API 응답 shape 변경 시 frontend 호출처가 새 필드명/타입 기대하는지 |
| 8 | X4 (회귀) | 변경 함수의 호출자 1-hop 호환성 (`grep -rn 함수명`) |
| 9 | X6 (데이터 일관성) | 캐시 키/sentinel/메모이즈 무효화가 변경된 데이터 흐름과 동기인지 |
| 10 | X7 (fallback) | 빈 배열/null/undefined 분기에서 `items[0]` 같은 silent wrong-pick 없는지 |
| 11 | X9 (raw fetch silent failure) | frontend 변경 시 `await fetch(` 호출이 (a) `api.js`의 `api/post/postSse` 헬퍼 안 쓰고 raw 호출 + (b) `X-User` 헤더 누락 + (c) `res.ok` 검사 누락 — 3 조건 충족 시 401/403/500을 silent로 삼키고 success 토스트로 위장. **점검 명령**: `grep -rn "fetch(" frontend-v2/src --include="*.jsx" --include="*.js"` (결과에서 `api.js:` 정의 라인은 제외) 후 각 호출의 헤더/검사 패턴 검증. `"fetch("`는 BRE 리터럴이라 `await fetch(`·`= fetch(` 모두 매치(과거 `-rnE "…\|…"` 는 ERE에서 `\|`가 리터럴 파이프라 영구 미매치였음 — 표 셀 파이프 회피 위해 alternation 제거). JSON body는 `api()` 헬퍼로 변환, FormData(multipart) 사용 시 raw fetch 정당하지만 X-User + res.ok는 명시 필수. 상세: 세션 메모리 `[[feedback_raw_fetch_silent_failure]]` |
