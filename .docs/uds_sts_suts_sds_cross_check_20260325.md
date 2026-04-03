# UDS / SDS / STS / SUTS 교차 검증 리포트
기준일: 2026-03-25

## 목적
현재 연결된 산출물이 실제 소스코드와 SDS 설계 정보를 얼마나 정확히 반영하고 있는지 대표 함수 기준으로 교차 검증한다.

검증 대상:
- 소스코드: `D:\Project\Ados\PDS64_RD\Sources\APP\Ap_BuzzerCtrl_PDS.c`
- SDS: [D:\Project\devops\260105\docs\(HDPDM01_SDS) Software Architecture Design Specification_v1.04_20230512.docx](D:/Project/devops/260105/docs/(HDPDM01_SDS)%20Software%20Architecture%20Design%20Specification_v1.04_20230512.docx)
- UDS: [D:\Project\devops\260105\backend\reports\uds_local\uds_spec_generated_expanded_20260324_170030.payload.json](D:/Project/devops/260105/backend/reports/uds_local/uds_spec_generated_expanded_20260324_170030.payload.json)
- STS: [D:\Project\devops\260105\reports\sts\sts_eval_20260319_123007.xlsx](D:/Project/devops/260105/reports/sts/sts_eval_20260319_123007.xlsx)
- SUTS: [D:\Project\devops\260105\reports\suts\suts_impact_20260324_111833.xlsm](D:/Project/devops/260105/reports/suts/suts_impact_20260324_111833.xlsm)

대표 함수:
- `g_Ap_BuzzerCtrl_Func`
- `g_Ap_BuzzerCtrl_Reset`
- `u8g_BuzzerStateReturn`

## 전체 판단
결론은 명확하다.

- `SDS`: 설계 설명, ASIL, Related ID, 인터페이스/데이터 설명이 충분히 존재한다.
- `STS`: 테스트 의도와 requirement 연결은 살아 있다.
- `SUTS`: 함수 시그니처, 변수, sequence 수준 정보가 잘 살아 있다.
- `UDS`: 생성은 정상 완료되었지만, 일부 함수에서 `description`과 `signature`가 SDS/소스 수준만큼 정확히 반영되지 않았다.

즉 현재 품질은:
- `SDS / STS / SUTS`: 비교적 양호
- `UDS`: 생성 성공, 하지만 설명/시그니처 품질은 추가 보정 필요

## 1. 소스코드 기준

### `g_Ap_BuzzerCtrl_Func`
- source signature: `void g_Ap_BuzzerCtrl_Func( void )`

### `g_Ap_BuzzerCtrl_Reset`
- source signature: `void g_Ap_BuzzerCtrl_Reset( void )`

### `u8g_BuzzerStateReturn`
- source signature: `U8 u8g_BuzzerStateReturn( void )`

## 2. SDS 기준

### `SwCom_16: Buzzer Control`
SDS에는 아래가 명확히 존재한다.
- `SC Name`: `Buzzer Control`
- `SC Description`: `g_Ap_Main() 함수에 의해 5ms 마다 Buzzer 출력을 판단하여 수행한다...`
- `ASIL`: `QM`
- `Related ID`: `SwEI_03, SwTR_0104, SwTR_0105, SwTR_0202, SwTR_0203, SwTR_0401, SwTR_0402`
- `SW Component Interface`
  - `g_Ap_BuzzerCtrl_Func()`
  - `g_Ap_BuzzerCtrl_Reset()`
  - `u8g_BuzzerStateReturn`
- `Software Component Data`
  - 관련 전역/입출력 데이터 다수
- `Software Component Unit Function`
  - `s_BuzzerStateCtrl()`, `s_BuzzerCtrl_On()`, `s_BuzzerCtrl_Off()` 등 상세 설명 존재

판단:
- SDS는 해당 컴포넌트의 설계 설명과 traceability 정보를 충분히 가지고 있다.
- UDS/STS/SUTS 생성 시 참조하기에 충분한 품질이다.

## 3. UDS 기준

UDS payload 집계:
- `function_details`: `431`
- `inputs` 존재 함수: `84`
- `outputs` 존재 함수: `127`
- `globals_global` 존재 함수: `360`
- `globals_static` 존재 함수: `266`
- `related` 존재 함수: `431`
- `description` 존재 함수: `431`

### `g_Ap_BuzzerCtrl_Func`
- `description_source = sds`
- `related_source = sds`
- `description = "void"`
- `signature = null`
- `inputs = []`
- `outputs = []`
- `globals_global = 17개`
- `globals_static = 7개`
- `related = SwEI_03, SwTR_0104, ...`

평가:
- `related`는 SDS와 일치한다.
- global/static 영향 변수도 반영됐다.
- 그러나 `description`이 `void`로만 들어가 있어 SDS 설명을 제대로 반영했다고 보기 어렵다.
- `signature = null`이라 input/output 품질도 낮다.

### `g_Ap_BuzzerCtrl_Reset`
- `description_source = sds`
- `related_source = sds`
- `description = "void"`
- `signature = null`
- `outputs = []`
- `globals_global = 4개`
- `globals_static = 7개`

평가:
- reset 함수의 출력성 전역/정적 변수는 잡혔다.
- 하지만 설명은 여전히 `void` 수준이라 SDS 설계 설명 반영 품질이 낮다.

### `u8g_BuzzerStateReturn`
- `description_source = sds`
- `related_source = sds`
- `description = "U8"`
- `signature = null`
- `outputs = ['[OUT] return U8 (range: 0 ~ 255)']`
- `globals_static = ['[IN] s_BuzzerState']`

평가:
- return/output과 static input은 비교적 잘 잡혔다.
- 그러나 설명이 `U8`만 들어간 것은 부정확하다.

### UDS 총평
- 강점:
  - 생성 자체는 정상
  - related/global/static 계열은 꽤 잘 반영
- 약점:
  - SDS의 설명 텍스트가 UDS description에 제대로 들어가지 않음
  - 일부 함수에서 signature 추출 실패
  - 그 결과 inputs/outputs 품질이 떨어짐

## 4. STS 기준

### `g_Ap_BuzzerCtrl_Func`
확인된 행:
- row `24`
- test case: `SwTC_SwEI_03_01`
- title: `Buzzer Control Output Signal - g_Ap_BuzzerCtrl_Func`
- related requirement: `SwEI_03`
- 설명: `PDSM 은 Buzzer 울림/경보 상황에 따라 PWM/Cycle 출력한다...`

평가:
- STS는 테스트 의도와 requirement trace가 살아 있다.
- 함수 수준 테스트 목적은 비교적 잘 표현된다.

### `u8g_BuzzerStateReturn`
확인된 행:
- row `644`
- `u8g_BuzzerStateReturn() 호출 | u8g_BuzzerStateReturn 정상 실행 확인`

평가:
- coverage는 있으나, 표현 깊이는 함수에 따라 편차가 있다.

### STS 총평
- requirement 연결과 테스트 의도는 양호
- 세부 표현 깊이는 함수별 편차 존재
- 현재 linked STS는 최신 impact 기준 문서는 아니므로, 최신 UDS/SUTS와 1:1 동기 상태는 아님

## 5. SUTS 기준

### `g_Ap_BuzzerCtrl_Func`
확인된 행:
- row `7`
- testcase: `SwUTC_SwUFn_0101`
- 설명: `Executes the buzzer control main function.`
- signature: `void g_Ap_BuzzerCtrl_Func( void )`
- SRS requirement 다수 연결
- input/output/indirect vars 다수 연결

평가:
- SUTS는 함수 시그니처와 변수 단위 정보가 잘 살아 있다.
- UDS보다 함수 단위 정밀도가 높다.

### `g_Ap_BuzzerCtrl_Reset`
확인된 행:
- row `77`
- 설명: `Executes the buzzer control function reset.`
- 관련 전역/정적 변수들 연결

### `u8g_BuzzerStateReturn`
확인된 행:
- row `70`
- signature: `U8 u8g_BuzzerStateReturn( void )`
- 이후 sequence row에서 boundary input/expected 확인 가능

평가:
- SUTS는 testcase/sequence 수준 품질이 양호하다.
- 특히 return 값과 input boundary가 UDS보다 잘 표현된다.

## 6. 최종 결론

현재 구현 품질을 한 줄로 정리하면:

- `SDS`: 좋음
- `STS`: 좋음
- `SUTS`: 좋음
- `UDS`: 생성 성공, 그러나 설명/시그니처 정밀도는 미흡

즉 지금 상태는
- 문서 생성 파이프라인은 동작한다.
- 하지만 `UDS 품질 = SDS 수준으로 완전히 반영됐다`고 보긴 어렵다.

가장 중요한 발견:
- `g_Ap_BuzzerCtrl_Func`, `g_Ap_BuzzerCtrl_Reset`, `u8g_BuzzerStateReturn` 모두
  - `description_source = sds`
  - 그런데 결과 description이 `void`, `U8` 같은 축약값으로 남아 있다.

이건 단순 뷰어 문제가 아니라 **UDS description enrichment 품질 문제**다.

## 7. 다음 권장 작업

1. `UDS description enrichment` 점검
- SDS에서 `SC Description`, `Function Description`을 어떻게 뽑는지 재검토
- 현재 `void`, `U8`로 들어가는 원인 추적

2. `signature` 추출 보강
- source parser에서 `void (...)`, `U8 (...)` 시그니처를 놓치는 이유 확인

3. `UDS vs SDS` 자동 검증 추가
- 함수별로
  - source signature
  - sds description
  - uds description
  - related
  를 비교하는 quality check 추가

4. `linked STS` 최신화 여부 검토
- 현재 STS linked 문서는 최신 impact와 완전 동기 상태는 아님

