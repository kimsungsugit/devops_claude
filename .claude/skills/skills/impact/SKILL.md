---
name: impact
description: "소스코드 변경에 대한 영향도 분석을 실행합니다. SVN/Git 변경분을 분석하여 영향받는 문서를 식별합니다."
---

# 변경 영향도 분석 스킬

$ARGUMENTS 에 분석 대상(SCM ID, 빌드번호, 리비전 등)이 들어옵니다.

## 수행 절차

1. **변경 정보 수집**
   - Git: `git diff --name-only` 또는 지정된 리비전 비교
   - SVN: `svn diff` 또는 지정된 리비전 비교
   - 변경된 `.c`, `.h` 파일 목록 추출

2. **Impact 분석 트리거**
   ```bash
   curl -s -X POST http://127.0.0.1:8000/api/jenkins/impact/trigger-async \
     -H "Content-Type: application/json" \
     -d '{"scm_id":"<id>","build_number":<n>,"targets":["uds","suts","sits","sts","sds"]}'
   ```

3. **진행률 모니터링**
   ```bash
   curl -s "http://127.0.0.1:8000/api/scm/impact-job/<job_id>"
   ```

4. **결과 분석**
   - 영향받는 함수 목록
   - 영향받는 문서 (UDS/STS/SUTS/SITS)
   - 변경 유형별 분류 (추가/수정/삭제)

5. **결과 보고**
   - 영향도 요약 테이블
   - 재생성 필요한 문서 목록
   - 추천 액션 (문서 재생성, 테스트 재실행 등)
