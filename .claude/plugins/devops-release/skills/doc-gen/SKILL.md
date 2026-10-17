---
description: "규격서 **1종을 골라** 생성합니다(uds|sts|suts|sits|all) — 플러그인 `user_config.backend_url` 경유. 4종 순차 + 추적성 체인 검증 + documenter 연동 + delta 재생성까지 필요하면 프로젝트 스킬 `/doc-pipeline` 이 더 완전합니다(같은 백엔드 엔드포인트를 쓴다)."
when_to_use: 특정 규격서 1종만 생성, uds만/sts만/suts만/sits만 생성, 플러그인 경유 문서 생성 요청 시
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
