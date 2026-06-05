---
description: "설계/시험 규격서를 자동 생성합니다. UDS, STS, SUTS, SITS 중 선택하여 생성합니다."
---

# 문서 자동 생성 (doc-gen)

$ARGUMENTS 에 생성할 문서 유형이 들어옵니다: uds, sts, suts, sits, all

## 수행 절차

1. **문서 유형 확인**
   - uds: Unit Design Specification (단위 설계 규격서)
   - sts: Software Test Specification (소프트웨어 시험 규격서)
   - suts: Software Unit Test Specification (단위 시험 규격서)
   - sits: Software Integration Test Specification (통합 시험 규격서)
   - all: 위 4종 전체 순차 생성

2. **필수 입력 확인**
   - source_root: C 소스코드 경로
   - 요구사항 문서(SRS, SDS) 경로
   - Jenkins job URL 및 빌드 번호

3. **생성 API 호출**
   - UDS: `POST ${user_config.backend_url}/api/jenkins/uds/generate-async`
   - STS: `POST ${user_config.backend_url}/api/jenkins/sts/generate-async`
   - SUTS: `POST ${user_config.backend_url}/api/jenkins/suts/generate-async`
   - SITS: `POST ${user_config.backend_url}/api/local/sits/generate-async`

4. **진행률 모니터링**
   - progress API를 폴링하여 완료까지 추적
   - 각 단계별 진행 상황 표시

5. **결과 확인**
   - 생성된 문서 경로 출력
   - `.devops_pro_cache/exports/` 에서 파일 확인
   - 품질 검증 결과 요약
