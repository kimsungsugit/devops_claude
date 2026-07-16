---
name: impact
description: "백엔드 API(:9000)로 영향도 분석 **잡을 트리거**하고 진행률을 폴링합니다. SCM ID/빌드번호/리비전을 받아 서버에서 비동기 실행 — 백엔드 기동이 필요합니다. 로컬에서 서버 없이 재생성 여부만 판정하려면 `/impact-analysis`를 쓰세요."
---

# 변경 영향도 분석 스킬

$ARGUMENTS 에 분석 대상(SCM ID, 빌드번호, 리비전 등)이 들어옵니다.

## 수행 절차

1. **변경 정보 수집**
   - Git: `git diff --name-only` 또는 지정된 리비전 비교
   - SVN: `svn diff` 또는 지정된 리비전 비교
   - 변경된 `.c`, `.h` 파일 목록 추출
   - Python/JavaScript 변경 시 문서 생성 로직(workflow/, report_gen/, generators/) 영향도도 분석

2. **Impact 분석 트리거**
   ```bash
   curl -s -X POST ${BACKEND_URL:-http://127.0.0.1:9000}/api/jenkins/impact/trigger-async \
     -H "Content-Type: application/json" \
     -d '{"scm_id":"<id>","build_number":<n>,"targets":["uds","suts","sits","sts","sds"]}'
   ```

3. **진행률 모니터링**
   ```bash
   curl -s "${BACKEND_URL:-http://127.0.0.1:9000}/api/scm/impact-job/<job_id>"
   ```

4. **결과 분석**
   - 영향받는 함수 목록
   - 영향받는 문서 (UDS/STS/SUTS/SITS)
   - 변경 유형별 분류 (추가/수정/삭제)

5. **ISO 26262 안전 영향도 분류**
   - 변경된 함수의 ASIL 등급에 따라 영향도 심각도 분류
   - ASIL D: Critical -- 전체 문서 재생성 + 리뷰 필수
   - ASIL C: High -- 관련 문서 재생성 + 리뷰 권장
   - ASIL B: Medium -- 관련 문서 재생성
   - ASIL A/QM: Low -- 변경분만 반영
   - ASIL 등급은 SRS/SDS 문서의 안전 요구사항 매핑 또는 함수 주석의 ASIL 태그로 판별

6. **결과 보고**
   - 영향도 요약 테이블 (안전 심각도 컬럼 포함)
   - 재생성 필요한 문서 목록
   - 추천 액션 (문서 재생성, 테스트 재실행 등)
   - Python/JS 변경 시: 문서 생성 로직 자체의 변경 영향 별도 보고
