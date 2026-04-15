---
name: doc-pipeline
description: "문서 생성 파이프라인. UDS->STS->SUTS->SITS 문서를 순서대로 자동 생성합니다."
---

# 문서 생성 파이프라인 워크플로우

$ARGUMENTS 에 생성 옵션이 들어옵니다:
- `all` -- UDS -> STS -> SUTS -> SITS 전체 (기본값)
- `uds` / `sts` / `suts` / `sits` -- 특정 문서만
- `delta` -- 변경분만 재생성

## 자율 운영 원칙
- 백엔드 서버 미실행 시 --> 자동 시작 후 진행
- API 호출 실패 시 --> 3회 재시도
- API 실패 기준: HTTP 상태 코드 >= 500, 응답 timeout (30초), 또는 응답 JSON 파싱 실패
- 사용자 확인 없이 전 과정 자동 실행

## ISO 26262 문서 추적성
- UDS->STS->SUTS->SITS 간 요구사항 연결(traceability)을 유지해야 한다
- 각 문서 생성 시 상위 문서의 요구사항 ID가 하위 문서에 정확히 반영되는지 검증
- 추적성 체인이 끊어진 항목은 경고로 보고

---

### STEP 1: 환경 확인 및 자동 구성
- 백엔드 상태 확인:
  ```bash
  curl -s ${BACKEND_URL:-http://127.0.0.1:8000}/api/health
  ```
- 서버 미실행 시 **자동 시작**:
  ```bash
  cd backend && uvicorn main:app --port ${BACKEND_PORT:-8000} &
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

1. **UDS** --> `POST ${BACKEND_URL:-http://127.0.0.1:8000}/api/jenkins/uds/generate-async` --> 진행률 폴링
2. **STS** --> `POST ${BACKEND_URL:-http://127.0.0.1:8000}/api/jenkins/sts/generate-async` --> 진행률 폴링
3. **SUTS** --> `POST ${BACKEND_URL:-http://127.0.0.1:8000}/api/jenkins/suts/generate-async` --> 진행률 폴링
4. **SITS** --> `POST ${BACKEND_URL:-http://127.0.0.1:8000}/api/local/sits/generate-async` --> 진행률 폴링
   (SITS는 Jenkins 없이 로컬 직접 생성하므로 /api/local/ 엔드포인트 사용)

각 단계 보고: `[1/4] UDS 생성 완료 -- path/to/file.docx`

**의존성 체인**: UDS 생성 실패 시 STS/SUTS/SITS를 건너뛰고 실패 보고. STS 실패 시 SUTS/SITS만 건너뜀. 각 단계는 이전 단계 성공을 확인한 후 진행.

### 부분 실패 처리
- 일부 문서만 실패 시 성공한 문서는 유지하고 실패 문서만 재시도 (최대 3회)
- 재시도 후에도 실패한 문서는 건너뛰고 다음 문서로 진행
- 최종 보고에서 실패 문서와 원인을 명시

---

### STEP 4: 품질 검증
- 생성된 파일 존재 및 크기 확인 (0바이트 아닌지)
- 생성 로그에서 경고/에러 확인
- reviewer 에이전트로 생성 품질 검증
- 추적성 체인 검증: 상위 문서 요구사항 ID가 하위 문서에 누락 없이 반영되었는지 확인

---

### STEP 4.5: documenter 에이전트 연동
문서 생성 완료 후 documenter 에이전트를 호출하여 산출물을 정리한다:

1. **CHANGELOG 업데이트**: `project_docs/change_history/` 에 생성/변경된 문서 목록과 변경 사유 기록
2. **결과 보고서 작성**: `reports/daily_brief/` 에 문서 생성 결과 요약 (성공/실패, 생성된 문서 수, 품질 점수)
3. **추적성 검증 보고**: SRS→UDS→STS 요구사항 ID 매핑 결과를 보고서에 포함

```python
# documenter 에이전트 호출 예시
Agent("documenter", prompt=f"""
문서 생성 파이프라인 결과를 정리해줘:
- 생성된 문서: {generated_docs}
- 품질 검증 결과: {quality_results}
- CHANGELOG에 변경 내역 추가
- 일일 보고서에 결과 요약 작성
""")
```

**조건**: doc-pipeline이 최소 1개 이상 문서를 성공적으로 생성한 경우에만 실행.
실패 시 STEP 4.5는 건너뛰고 결과 보고로 직행.

---

### STEP 5: 결과 보고
```
## 문서 생성 완료

| 문서 | 상태 | 파일 경로 | 추적성 |
|------|------|----------|--------|
| UDS  | OK   | exports/uds_xxx.docx | - |
| STS  | OK   | exports/sts_xxx.xlsx | UDS 연결 OK |
| SUTS | OK   | exports/suts_xxx.xlsm | STS 연결 OK |
| SITS | OK   | exports/sits_xxx.xlsm | SUTS 연결 OK |

소요 시간: ~N분
추적성 경고: [있으면 상세 내역]
```
