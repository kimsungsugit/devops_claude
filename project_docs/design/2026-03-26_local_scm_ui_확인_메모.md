# Local SCM UI 확인 메모

## 확인 목적

- `Local SCM` 화면에서 최근 impact run 이력과 change history가 실제 데이터 기준으로 어떻게 보여야 하는지 정리한다.
- 이번 확인은 API 응답과 [LocalScmPanel.jsx](/D:/Project/devops/260105/frontend/src/components/local/LocalScmPanel.jsx) 바인딩 기준으로 수행했다.

## 확인 제약

- 백엔드와 프론트엔드 서버는 로컬에서 정상 응답을 확인했다.
- 다만 Playwright daemon 세션 파일 권한 문제로 브라우저 스냅샷 캡처는 확보하지 못했다.
- 따라서 본 메모는 "현재 화면이 받아야 하는 실제 데이터" 기준의 UI 확인 결과다.

## 1. Registry 영역에서 보여야 하는 값

- SCM 목록에는 `hdpdm01` 1개 항목이 보여야 한다.
- linked docs는 최신 생성 결과 기준으로 아래 경로가 연결되어야 한다.
  - UDS: `D:\Project\devops\260105\backend\reports\uds_local\uds_spec_generated_expanded_20260326_133526.docx`
  - SUTS: `D:\Project\devops\260105\reports\suts\suts_impact_20260326_132933.xlsm`
  - SITS: `D:\Project\devops\260105\reports\sits\sits_impact_20260326_132911.xlsm`
  - STS: 기존 `sts_eval_20260319_123007.xlsx`
  - SRS/SDS/HSIS: 기존 연결 문서 유지

## 2. Audit 이력에서 상단에 보여야 하는 run

최신 5개 기준으로 아래 순서가 보여야 한다.

1. `impact_20260326_140848.json`
   - changed function: `g_Ap_DoorCtrl_Reset`
   - type: `HEADER`
   - 모든 대상 문서 `review_required`

2. `impact_20260326_140410.json`
   - 과거 header mapping 실패 케이스
   - changed function: `ap_doorctrl_it_pds`

3. `impact_20260326_135056.json`
   - Motor auto-generate 성공 케이스
   - `AUTO` 대상 3개, `FLAG` 대상 1개

4. `impact_20260326_131319.json`
   - Buzzer auto-generate 성공 케이스
   - `AUTO` 대상 3개, `FLAG` 대상 1개

5. `impact_20260326_122042.json`
   - header mapping 보완 전 초기 케이스

## 3. Change History 드롭다운에서 보여야 하는 run

최신 5개 기준으로 아래 run ID가 보여야 한다.

- `impact_20260326_140848`
- `impact_20260326_140410`
- `impact_20260326_135056`
- `impact_20260326_131319`
- `impact_20260326_122042`

## 4. `impact_20260326_135056` 선택 시 화면에서 기대되는 내용

이 run은 `Ap_MotorCtrl_PDS.c` auto-generate 성공 케이스이므로 `Local SCM` 상세 영역에서 다음이 보여야 한다.

- changed_files:
  - `Sources/APP/Ap_MotorCtrl_PDS.c`

- changed_functions:
  - 총 24개 BODY 함수
  - 예시:
    - `g_ap_motorctrl_func`
    - `s_motorctrl`
    - `s32s_motorspdctrl_openastoffsetcalc`
    - `s_motorstatectrl`

- summary:
  - `uds_changed_functions = 0`
  - `suts_changed_functions = 24`
  - `sits_test_cases = 102`
  - `sits_sub_cases = 714`
  - `sits_delta_cases = 102`
  - `sts_flagged = 24`

- action 상태:
  - UDS: `AUTO / completed`
  - SUTS: `AUTO / completed`
  - SITS: `AUTO / completed`
  - STS: `FLAG / review_required`
  - SDS: `- / skipped`

- 열기 버튼으로 접근 가능한 결과:
  - UDS DOCX
  - SUTS XLSM
  - SITS XLSM
  - STS review markdown
  - change log json

## 5. `impact_20260326_140848` 선택 시 화면에서 기대되는 내용

이 run은 header mapping 보완 후 검증 케이스이므로 다음이 보여야 한다.

- changed_files:
  - `Sources/APP/Ap_DoorCtrl_it_PDS.h`

- changed_functions:
  - `g_Ap_DoorCtrl_Reset: HEADER`

- summary:
  - `uds_changed_functions = 1`
  - `suts_changed_functions = 1`
  - `sits_flagged = 1`
  - `sts_flagged = 1`
  - `sds_flagged = 1`

- action 상태:
  - SDS: `FLAG / review_required`
  - SITS: `FLAG / review_required`
  - STS: `FLAG / review_required`
  - SUTS: `FLAG / review_required`
  - UDS: `FLAG / review_required`

즉, 이전처럼 `ap_doorctrl_it_pds`가 아니라 실제 함수명 `g_Ap_DoorCtrl_Reset`이 화면에 보여야 한다.

## 6. Local SCM UI 기준 결론

- 화면에 연결되는 데이터는 정상 갱신되어 있다.
- 최신 linked docs는 auto-generate 결과로 교체되어 있다.
- audit/change history에는 최신 run 들이 정렬되어 노출되어야 한다.
- HEADER 케이스는 이제 파일 stem이 아니라 실제 함수명으로 노출되어야 한다.

## 7. 후속 권장

- 브라우저 스냅샷은 Playwright daemon 권한 문제 해소 후 한 번 더 확보하는 것이 좋다.
- 현재는 API 응답과 프론트 컴포넌트 구조 기준으로 UI 표시 기대값을 검증 완료한 상태다.
