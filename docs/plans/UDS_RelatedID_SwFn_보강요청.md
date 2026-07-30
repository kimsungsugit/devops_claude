# UDS `Related ID` 보강 요청 — SwCom 유지 + SwFn 병기

> **이 문서의 위치** — ARIA(추적성 자동화 도구) 측이 **문서 작성 파트에 보내는 요청**이다.
> 도구가 스스로 고칠 수 없는 것, 즉 **설계 의도**를 문서에 적어 달라는 요청만 담는다.
> 대상 프로젝트: **KJPDS02** / 기준 문서: `SwUDS v3.02_260XXX`, `SwDS v3.01_20260410_R`
> 작성일: 2026-07-30 / 대조 기준 커밋: `10d9aa5`(설계-ID 브리지), `52e4b08`(함수 fan-out 차단)
> 모든 수치는 원문 직접 파싱 실측이며, 재현 스크립트 경로를 §6에 남긴다.

---

## 0. 한 줄 요약

UDS `Related ID` 열에 **기존 `SwCom_NN` 을 그대로 두고 `SwFn_NN` 을 함께 적어** 주시기 바랍니다.
대상은 현재 SwCom 만 적힌 **900행**입니다.

**SwCom 을 SwFn 으로 교체하는 것은 안 됩니다** — SwFn 에는 ASIL 표기가 없어 안전등급 근거가 사라집니다(§4).

---

## 1. 현황 실측

`SwUDS v3.02` 의 함수별 표 **1,035개**를 전수 파싱한 결과입니다.

| 항목 | 실측 |
|---|---|
| `Related ID` 열 존재 | ✅ 있음 (전 1,035행) |
| 값이 채워진 행 | **1,035 / 1,035 (100%)** — 빈 칸 0 |
| SRS 요구ID(`SwTR_`/`SwEI_`/`SwTSR_`…)를 담은 행 | **0** |
| **`SwCom_NN` 만 적힌 행** | **900 (87.0%)** ← 이번 요청 대상 |
| `SwFn_`/`SwSTR_`/`SwST_`/`SwTK_` 를 포함한 행 | 135 (13.0%) |

즉 열도 있고 값도 다 차 있습니다. **입도(粒度)만 컴포넌트 수준**입니다.

---

## 2. 왜 필요한가 — SwCom 은 추적 연결에 쓸 수 없습니다

추적성 도구는 `UDS 함수 → 설계ID → SDS → SRS 요구` 경로로 역추적합니다. 그런데 **SwCom 은 이
경로에서 구조적으로 제외**되어 있습니다. 임의 결정이 아니라 실측 근거가 있습니다(커밋 `10d9aa5`):

> SwCom 을 브리지에 포함하면 도달하는 요구 수는 **그대로(64)** 인데
> 요구당 연결 함수 수(fan-out) 중앙값이 **22 → 56 으로 악화**된다.

SwCom 은 컴포넌트 하나가 요구 수십 개를 한꺼번에 참조하는 **느슨한(loose) 노드**라, 넣으면
"이 요구에 이 함수 500개가 관련됨" 같은 무의미한 연결만 늘어납니다.

**결과**: SwCom 만 적힌 900행은 역추적 경로에서 통째로 빠집니다. 문서에 값이 있는데도
도구가 쓰지 못하는 상태입니다.

---

## 3. 기대 효과 — SDS 원문 실측

`SwDS v3.01` 의 SwFn / SwCom 엔트리를 각각 파싱해 비교했습니다.

| 축 | **SwFn 경유** | SwCom 경유(현행) |
|---|---|---|
| 엔트리 수 / 요구를 가진 수 | 41 / **41** | 33 / 33 |
| 엔트리당 연결 요구 (중앙 · 최대) | **1 · 6** | 5 · 17 |
| 도달하는 고유 요구 수 | **51** | 46 |
| 요구당 함수 수 (1,035 배정 시, 중앙 · 최대) | **25 · 126** | 94 · 502 |

- 요구당 함수 수 **94 → 25** (약 3.8배 정밀화)
- 도달 요구 **46 → 51** (SwFn 이 더 넓게 닿습니다)

---

## 4. ⚠ 제약 — SwCom 을 지우면 안 됩니다

| 축 | SwFn | SwCom |
|---|---|---|
| **ASIL 표기 보유** | **0 / 41** ❌ | **33 / 33** ✅ |

SDS 원문에서 SwFn 엔트리에는 ASIL 이 **하나도 기재되어 있지 않습니다.** 도구는 요구사항별
ASIL 을 SDS 컴포넌트에서 끌어올려(roll-up) 계산하므로, SwCom 을 SwFn 으로 **교체**하면
안전등급 근거가 사라집니다.

따라서 기재 형식은 **병기**입니다:

```
현재 :  SwCom_14
요청 :  SwCom_14, SwFn_10
```

---

## 5. 한계 — 이 조치로 해결되지 **않는** 것 (정직 고지)

| 질문 | 답 |
|---|---|
| 미추적 함수의 역추적 링크가 생기나 | **예** — 900행이 브리지 대상이 됩니다 |
| 연결 입도가 좋아지나 | **예** — 요구당 94 → 25 |
| 요구사항 커버리지가 올라가나 | **아니오** — 이미 **68 / 68 = 100%** 입니다 |
| **함수 단위** 정밀 추적이 되나 | **아니오** — SwFn 이 41개뿐이라 요구당 약 25함수의 그룹 단위 roll-up 입니다 |
| ASIL 정합이 좋아지나 | **아니오** — SwFn 에 ASIL 이 없어 SwCom 병기로 현상 유지입니다 |

**함수 단위 추적**을 하려면 소스 주석(`@related SwTR_0101` 형태)이 필요한데 현재 **0건**입니다.
다만 이 프로젝트의 실측 ASIL 분포는 **A 62 / QM 2 / 미상 4** 이므로, ASIL A 수준에서는
SwFn 병기로 실무상 충분하다고 판단합니다. ASIL C/D 항목이 생기면 그때 소스 주석이 필요합니다.

> **어느 함수가 어느 SwFn 인지는 도구가 판단할 수 없습니다.** 그것은 설계 의도이므로
> 부록 A 의 SwFn 열은 **빈 칸으로 드립니다.** 도구가 추정해 채우면 근거 없는 매핑이
> 그대로 문서에 박히게 됩니다.

---

## 6. 부록

첨부는 같은 디렉터리의 [`UDS_RelatedID_SwFn_부록/`](UDS_RelatedID_SwFn_부록/) 에 있습니다.
TSV(탭 구분, UTF-8 BOM)라 Excel 에서 바로 열립니다.

| 부록 | 파일 | 내용 | 행 수 |
|---|---|---|---|
| **A** | `appendix_A_swcom_only.tsv` | SwCom 만 적힌 대상 목록 — `SwUFn ID / 함수명 / Prototype / 현재 Related ID / **추가할 SwFn(빈 칸)**` | **900** |
| **B** | `appendix_B_swfn_catalog.tsv` | SwFn 카탈로그 — `SwFn ID / ASIL / 연결 요구ID / 설명`. 부록 A 를 채울 때 참조 | **41** |
| **C** | `appendix_C_doc_code_drift.tsv` | 문서–코드 드리프트 확인 요청 (§7) | 241 |

재현 스크립트도 같은 디렉터리에 함께 둡니다 — `uds_appendix.py`(A·B), `drift_appendix.py`(C).
둘 다 Cloudium 워커 경유 **읽기 전용**이며 원본 문서를 수정하지 않습니다. 저장소 루트에서
`.venv/Scripts/python.exe docs/plans/UDS_RelatedID_SwFn_부록/uds_appendix.py <출력경로>` 로 재생성합니다.

---

## 7. 부록 C — 별건 확인 요청 (문서–코드 드리프트)

SwDS 에 설계로 기재돼 있으나 SwUDS 에는 없는 함수가 **241건**입니다. 소스(`NE1AW_PORTING`,
`PDS128_FBL`) 원문과 대조해 분류했습니다.

### 7-1. 코드에서 비활성화됐는데 설계에는 남아 있음 — **12건** (근거 명확)

정의·선언이 **주석 처리**되어 빌드에 들어가지 않는데 SwDS 에는 설계로 남아 있습니다.
코드 쪽에 사유까지 적혀 있습니다 — 예: `/* Unused wrapper: keep implementation disabled to
avoid dead-code violation`.

| 함수 | 근거 |
|---|---|
| `g_SysEepromCtrl_WriteRdbiData` | 선언 주석 `SysEepromCtrl_it_PDS.h:252`, 정의도 주석 블록 안(`SysEepromCtrl_PDS.c:1040`) |
| `u8g_SysEepromCtrl_ReadRdbiData` | 선언 주석 `SysEepromCtrl_it_PDS.h:259`, 정의도 주석 블록 안(`SysEepromCtrl_PDS.c:1123`) |
| `g_SysEepromCtrl_WriteData` | 선언 주석 `SysEepromCtrl_PDS.c:1012` |
| `g_Lib_SafeWriteQueue_Init` | 선언 주석 `Lib_SafeWriteQueue.c:212` |
| `g_Lib_Sha256_Calculate` | 선언 주석 `Lib_sha256.c:313` |
| `g_Lib_Sha256_FwHashCalculate` | 선언 주석 `Lib_sha256_it.h:31` |
| `g_Lib_Sha256_GetProgressCallback` | 선언 주석 `Lib_sha256_it.h:107` |
| `g_Lib_Sha256_SetProgressCallback` | 선언 주석 `SysOs_Main.c:190` |
| `Cpu_GetResetSource` | 선언 주석 `Cpu.c:19` |
| `PT5_MOTOR_NFAULT_GetVal` | 선언 주석 `PT5_MOTOR_NFAULT.c:38` |
| `s_AntipinchFlagCheck` | 선언 주석 `Ap_DoorPreCtrl_PDS.c:374` |
| `u16s_MotorShortBattA2_Check` | 선언 주석 `SysDiagCtrl_PDS.c:158` |

**확인 요청**: 이 12건을 SwDS 에서 제거할지, 아니면 코드를 되살릴지 결정 부탁드립니다.

### 7-2. 코드에 살아 있는데 SwUDS 에 없음 — **6건** (UDS 누락 후보)

| 함수 | 근거 |
|---|---|
| `g_Ap_Diagnostic` | 정의·선언 `Ap_DoorPreCtrl_PDS.c` |
| `s_DoorState_Iintialization` | 정의·선언 `Ap_DoorCtrl_PDS.c` |
| `l_ifc_init` / `l_sys_init` | 정의 `lin_common_api.c` (LIN 스택 외부 API) |
| `ld_send_message` | 정의 `lin_commontl_api.c` |
| `lin_lld_get_state` | 정의 `lin.c` |

뒤 4건은 **LIN 스택 외부 라이브러리** API 라 단위설계 대상이 아닐 수 있습니다. 앞 2건은
자체 구현이라 SwUDS 누락 여부 확인이 필요합니다.

### 7-3. 나머지 223건 — 미분류 (원자료만 제공)

소스에 정의가 없는 항목입니다. 다만 `g_DoorState_His[]`, `ccr_reg`, `EntryPoint` 처럼
**SwDS 인터페이스 표에서 함수가 아닌 것(전역변수·레지스터·표 헤더)이 함께 파싱된 잡음**이
섞여 있습니다. 도구가 잡음과 실제 갭을 구분할 수 없어 **판정하지 않고 목록만** 드립니다.
부록 C TSV 의 `NO_IMPL` 행이 여기 해당합니다.

---

## 8. 요약

| 요청 | 대상 | 성격 |
|---|---|---|
| **주** UDS `Related ID` 에 SwFn 병기 (SwCom 유지) | 900행 | 추적성 정밀도 3.8배 개선 |
| **부** 코드 비활성화 함수의 SwDS 잔존 정리 | 12건 | 문서–코드 정합 |
| **부** UDS 누락 후보 확인 | 6건 (그중 4건은 외부 라이브러리 가능) | 문서 완전성 |

요구 커버리지는 이미 100%이므로 **긴급하지 않습니다.** 감사(audit) 대비 시점에 맞춰
진행하시면 됩니다.
