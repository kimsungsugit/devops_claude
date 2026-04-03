---
name: doc-pipeline
description: "문서 생성 파이프라인. UDS→STS→SUTS→SITS 문서를 순서대로 자동 생성합니다."
---

# 문서 생성 파이프라인 워크플로우

$ARGUMENTS 에 생성 옵션이 들어옵니다:
- `all` — UDS → STS → SUTS → SITS 전체 (기본값)
- `uds` / `sts` / `suts` / `sits` — 특정 문서만
- `delta` — 변경분만 재생성

## 자율 운영 원칙
- 백엔드 서버 미실행 시 → 자동 시작 후 진행
- API 호출 실패 시 → 3회 재시도
- 사용자 확인 없이 전 과정 자동 실행

---

### STEP 1: 환경 확인 및 자동 구성
- 백엔드 상태 확인:
  ```bash
  curl -s http://127.0.0.1:8000/api/health
  ```
- 서버 미실행 시 **자동 시작**:
  ```bash
  cd backend && uvicorn main:app --port 8000 &
  ```
  5초 대기 후 재확인
- 필수 경로 확인 (source_root, SRS, SDS)

---

### STEP 2: 변경 분석 (delta 모드 시)
- `git diff --name-only` 또는 `svn diff --summarize`로 변경 파일 확인
- 변경된 `.c`, `.h` 파일 목록 추출
- 영향받는 함수/모듈 식별

---

### STEP 3: 문서 생성 (순차 실행)

순서대로 자동 실행 (이전 문서 결과를 다음에서 참조):

1. **UDS** → `POST /api/jenkins/uds/generate-async` → 진행률 폴링
2. **STS** → `POST /api/jenkins/sts/generate-async` → 진행률 폴링
3. **SUTS** → `POST /api/jenkins/suts/generate-async` → 진행률 폴링
4. **SITS** → `POST /api/local/sits/generate-async` → 진행률 폴링

각 단계 보고: `[1/4] UDS 생성 완료 — path/to/file.docx`

API 실패 시: 3초 대기 → 재시도 (최대 3회)

---

### STEP 4: 품질 검증
- 생성된 파일 존재 및 크기 확인 (0바이트 아닌지)
- 생성 로그에서 경고/에러 확인
- doc-quality 에이전트 활용 가능 시 자동 품질 검증

---

### STEP 5: 결과 보고
```
## 문서 생성 완료

| 문서 | 상태 | 파일 경로 |
|------|------|----------|
| UDS  | OK   | exports/uds_xxx.docx |
| STS  | OK   | exports/sts_xxx.xlsx |
| SUTS | OK   | exports/suts_xxx.xlsm |
| SITS | OK   | exports/sits_xxx.xlsm |

소요 시간: ~N분
```
