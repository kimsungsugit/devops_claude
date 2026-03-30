# E2E 시나리오 D - Review-Only 정상 동작 검증

## 목적

- 자동 생성이 아니라 review-required로 떨어지는 것이 정상인 상황을 분리해서 검증한다.

## 대상 기준

- SCM ID: `hdpdm01`
- Source Root: `D:\Project\Ados\PDS64_RD`

## 실제 대상 케이스

- 다중 파일 변경으로 영향 함수 수가 임계값을 초과하는 상황
- 기준선 예시:
  - `reports/impact_audit/impact_20260326_100606.json`
  - warning: `impacted function count exceeded limit (71>50); promote to review`

## 실제 대상 파일/함수

- 대상 파일:
  - `Sources/APP/Ap_BuzzerCtrl_PDS.c`
  - `Sources/APP/Ap_DoorCtrl_PDS.c`
  - `Sources/APP/Ap_MotorCtrl_PDS.c`
- 대표 함수군:
  - `g_Ap_BuzzerCtrl_Func`
  - `g_Ap_DoorCtrl_Func`
  - `g_Ap_MotorCtrl_Func`
  - `s_MotorCtrl`
  - `s_DoorStateCtrl`
  - `s_BuzzerCtrl_On`

## 변경 방식

- 대량 영향이 재현되도록 2~3개 파일에서 BODY 변경 수행
- 자동 생성보다 review fallback이 우선되는 상황을 의도적으로 만든다

## 기대 결과

- audit/change log는 정상 생성
- UDS/SUTS/SITS가 `review_required` 중심으로 기록될 수 있음
- review markdown이 생성되면 변경 함수와 리뷰 포인트가 들어 있어야 함
- 운영자가 "실패"가 아니라 "정책상 review-only"라고 설명 가능해야 함

## 주요 확인 포인트

- review-required와 오류 실패를 구분할 수 있는가
- warning 메시지가 결과와 연결되는가
- review 문서 품질이 충분한가

## PASS 기준

- review-only 결과가 정책적으로 설명 가능
- audit/change log 정상 생성
- review 문서 또는 로그에 근거가 남음

