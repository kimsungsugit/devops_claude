# E2E 시나리오 B - SIGNATURE 또는 HEADER 변경 검증

## 목적

- 인터페이스 변경 시 BODY 변경보다 넓은 영향 반응이 나오는지 확인한다.

## 대상 기준

- SCM ID: `hdpdm01`
- Source Root: `D:\Project\Ados\PDS64_RD`

## 실제 대상 파일/함수

- 후보 파일:
  - `D:\Project\Ados\PDS64_RD\Sources\APP\Ap_DoorCtrl_PDS.c`
  - 관련 헤더 파일이 있다면 동일 모듈 헤더 파일
- 대표 함수:
  - `g_Ap_DoorCtrl_Func`
  - `s_DoorStateCtrl`
  - `s_DoorStateCtrl_UserCtrl`

## 변경 방식

- 아래 중 하나만 선택해서 최소 단위로 적용
  - `g_Ap_DoorCtrl_Func` 선언/정의부 공백이 아닌 실제 파라미터 변경
  - `s_DoorStateCtrl` 반환형 또는 파라미터 타입 변경
  - 관련 헤더 선언부 변경

## 기대 결과

- changed function type: `SIGNATURE` 또는 `HEADER`
- UDS 우선 영향 표시
- STS/SDS review 대상 확대 가능
- BODY-only 시나리오보다 영향 함수 수 또는 review 범위가 더 넓게 나타날 가능성 높음
- 프론트엔드에서 인터페이스 변경 가이드 노출

## 주요 확인 포인트

- 인터페이스 변경이 BODY로 축소 판정되지 않는가
- UDS 관련 review guidance가 강화되어 보이는가
- STS/SDS flag가 정책과 일관되게 나오는가

## 실행 절차

1. `Ap_DoorCtrl_PDS.c` 및 관련 헤더 기준 상태 기록
2. 함수 선언/정의부 변경
3. 영향도 분석 실행
4. changed_functions 타입과 문서별 summary 수치 확인
5. review 문서 생성 여부 확인

## PASS 기준

- `SIGNATURE` 또는 `HEADER` 판정
- BODY 시나리오와 다른 가이드/영향 범위 확인
- audit/change log 정상 생성

## 금지 사항

- 원격 SVN 반영 금지
- 테스트 목적 외 구조 개편 금지

