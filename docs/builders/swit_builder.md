# SwIT Builder (Software Integration Test, 33~35차 라운드~)

> CLAUDE.md on-demand 레퍼런스 — SwIT Coverage(SwITCV)/SITR/**SwITCR**/Consistency 빌더 작업 시 참조.
> 관련: [`swut_builder.md`](swut_builder.md), [`visual-marking-and-design-tokens.md`](visual-marking-and-design-tokens.md)

ISO 26262 ASIL B+ 통합 테스트 산출물 자동 생성. SwUT 30~32차 인프라 **81% 재활용**.

## 산출물 3종 (생성 현황 보드 게이트 대상)

`/api/swit/*` 도 SwUT 과 대칭으로 산출물 **셋**을 낸다. 세 endpoint 모두 동기 blob 응답이고
`require_admin` + Semaphore(capacity 2)를 공유한다.

| 산출물 | endpoint | 확장자 | 양식 config 키 | Quality doc_type | 총 TC 키 |
|--------|----------|--------|----------------|------------------|----------|
| **SwITCV** (커버리지) | `POST /api/swit/coverage/build` | xlsx | `swit_coverage_template` | `swit` | `total_tcs` |
| **SITR** (시험 결과) | `POST /api/swit/sitr/build` | xlsm | `swit_sitr_template` | `sitr` | `total` |
| **SwITCR** (종합 결과) | `POST /api/swit/switcr/build` | xlsm | `switcr_template` | `switcr` | `total_tcs` |

⚠ **SwUT 과 같은 분모 함정이 여기도 있다** — SITR 만 `total`, 나머지 둘은 `total_tcs` 다.
자세한 근거는 [`swut_builder.md`](swut_builder.md) `## 산출물 3종` 참조. 커버리지의
doc_type 이 `switcv` 가 아니라 **`swit`** 인 것도 같은 이유(기존 이력 보존)다.

**SwITCR 시트** — `cover` / `summary` / `it101` / `it201` / `it301` / `it401` / `it701` /
`2.Test Log` / `4.Coverage` / `FI_Test Case` / `history` / `AuditLog`.

⚠ **SwITCR 만 다른 산출물을 되읽는다.** SwITCV·SITR·Fault Injection 규격서를 입력으로 받아
증적 시트를 채우는데, 셋 다 config fallback 이 있어 **없어도 빌드가 죽지 않고 그 시트가 빈
채로 나간다**. 즉 결핍이 조용하다 — 생성 현황 보드의 준비 점검이 이 셋을 선택 입력으로
표시하는 이유다(`backend/services/docgen_requirements.py` `IN_LEVEL_ARTIFACTS`).

## SwITCV `4.Coverage` 레이아웃 — DV(11열) / PV(10열) (2026-08-26 실측)

**Component 열 하나 차이로 그 오른쪽 전부가 한 칸씩 밀린다.** 열을 상수로 박으면 조용히
틀린 값을 읽는다. 판정은 `excel_layout_resolver.coverage_column_base()` **단일 출처**를 쓸 것.

| | No | Component | Unit ID | Name | Functions | Exception | Called Count | Total | Pass | Exception | File |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **DV(11열)** | B | C | D | E | F | G | H | I | J | K | L |
| **PV(10열)** | B | — | C | D | E | F | G | H | I | J | K |

요약 블록(r4 헤더 / r5 Functions / r6 Function Calls)도 같은 한 칸만큼 밀린다 —
`Total | Fail Count | Exception | Coverage` 연속 4칸. DV 는 E~H, PV 는 D~G.

KJPDS02 PV 정본(`… SwITCV … v2.01_260629_R.xlsx`) 실측:

    D5=1014(Total)  E5=4(Fail)   F5=4(Exc)   G5=1(Coverage)
    D6=1014(Total)  E6=21(Fail)  F6=21(Exc)  G6=1(Coverage)
    데이터 1014행(r11~r1024) + 마감 TOTAL 행 r1025 + `< End of Document >` r1027

⚠ **`4.Coverage` 를 정확 매칭으로 찾지 말 것** — 회사 SwUTCV 정본의 시트명은
`4. Coverage`(점 뒤 공백)다. `find_coverage_sheet()` 를 쓸 것.

⚠ **헤더 라벨에 오타가 실재한다** (`Excpetion`). 그래서 `Fail Count`/`Exception` 은 라벨로
찾지 않고 `Total` 만 라벨로 찾은 뒤 `+1 / +2` 로 잡는다.

### 이 결함이 오래 산 이유 (2026-08-26 수정 전)

`swit_comprehensive_aggregator._load_workbook_summary` 가 DV 에 고정돼 PV 정본을 한 칸씩
밀려 읽었다. 라운드 102 가 같은 파일의 `_extract_template_coverage_rows` 만 DV/PV 적응을
시키고 이 함수를 빠뜨린, **복제본이 갈라진** 형태다. 증상이 조용했던 건 밀린 자리의 값이
우연히 같았기 때문이다 — `Fail Count`(4)와 `Exception`(4)이 같은 수라 "fail 은 맞네" 로
보였고, 정작 `Total`(1014)이 `Fail Count`(4)로 읽혀 **253배 과소** 보고됐다.

결과(KJPDS02 PV SwITCR 실측 대조):

| | 수정 전 | 수정 후 | 정본 |
|---|---|---|---|
| IT101 `E75` Functions Total | 4 | **1014** | 1014 |
| IT101 `E76` Function Calls Total | 21 | **1014** | 1014 |
| IT101 `K75/K76` Exception | 1 / 1 | **4 / 21** | 4 / 21 |
| IT101 4.1 판정 `=IF(E=F+I+K,…)` | **Fail / Fail** | Pass / Pass | Pass |
| IT101 4.2 미달성 표 | "해당사항 없음" | **10건 + 외 15건** | 25건 |
| quality `qualified_function_count` | 4.0 | **1014.0** | — |

⚠ 판정이 **Fail 로 뒤집혀 있었고**, 실재하는 미달성 25건(함수 4 + 호출 21)이
"해당사항 없음" 으로 나갔다 — ISO 26262 감사 산출물에서 거짓 부정이다.
회귀 가드는 `tests/unit/test_swit_comprehensive_aggregator.py`
`TestSwitcvPvLayoutIsNotReadOneColumnOff` (뮤테이션 8/8).

⚠ 가드는 **Total / Fail Count / Exception 을 전부 다른 값**으로 둔다. 세 값이 같으면 한 칸
밀려도 통과해서 결함을 못 잡는다 — 예전 픽스처가 헤더 없이 DV 열에만 기입해 **코드의
거울**이던 것이 이 결함을 통과시킨 원인이다.

## SwITR 증거 읽기 — 시트명·열 (2026-08-26 실측)

SwITCR 은 SwITR 을 되읽어 TC 집계를 증거로 삼는다. 정본 배치는 **코드가 가정하던 것과 달랐고**,
그 결과 `sitr_test_log_tcs` / `sitr_pass_count` / `sitr_fail_count` 세 키가 늘 부재였다.

| | 코드가 보던 곳 | 정본 실측 |
|---|---|---|
| 시트 | `2.Test Log` (정확 매칭) | **`3.Test Log`** |
| TC ID 열 | `row[5]` = F | **B** (세로 병합) |
| Pass/Fail 열 | `row[-12:]` (뒤에서 12칸) | **AL** (max_col=319) |

⚠ **행을 세면 틀린다.** TC ID 가 세로 병합이라 병합 그룹 54개 / 결과 셀 630개가 나오는데
문서가 말하는 Total 은 **611** 이다. 그래서 이제 `1.Test Summary` 의 Total 행을 **먼저** 쓴다:

    r17  Type | Number of TCs Tested | Number of TCs Passed | Number of TCs Failed | not executed
    r18  Requirements Based TC   581  581  0  0
    r19  Interface TC            (빈 칸 — 미수행)
    r20  Fault Injection TC       30   30  0  0
    r21  Total                   611  611  0  0        <- 이 행을 쓴다

부분합을 우리가 더하지 않는다 — 합산 규칙이 양식마다 다르다. Total 한 칸이라도 수가 아니면
**통째로 포기**한다(절반짜리 근거 금지). 라벨을 못 찾으면 `1.Test Summary` 가 없는 판(v1.01)
으로 보고 `N.Test Log` 행 세기로 접는데, 그때도 시트명·열은 **탐지**한다.

⚠ SwITCV 에도 `1.Test Summary` 가 있지만 `Number of TCs Tested` 블록이 없다 — 라벨 기반이라
자동으로 걸러진다(같은 함수가 두 워크북에 쓰인다).

### 곁가지 — 읽어도 쓰지 않던 두 번째 배선

`_write_it101` 이 `sitr_*` 를 **`switcv_summary`**(커버리지 쪽 dict)에서 찾고 있었다. 그 키는
SwITR 워크북에서만 나오고, 게다가 이 함수는 `switr_summary` 를 인자로 받지도 않았다. 즉 읽기를
고쳐도 IT101 에는 안 닿았다. 인자를 넘기고 조회 대상을 바꿨다.

### 대조 — 이 읽기를 쓸모 있게 만드는 부분

읽기만 고치면 값은 `or` 폴백 자리에 조용히 앉을 뿐이다(KJPDS02 는 세션이 이미 611 을 주므로
산출물 숫자는 그대로다). 그래서 **세션 실측 ↔ 승인 문서가 다르면 경고**한다
(`_switr_divergence_warnings`, prefix `[evidence]`).

- 일치는 **조용하다** — 정상을 경고로 채우면 진짜 경고가 묻힌다
- 한쪽이 없으면 건너뛴다 — **부재는 불일치가 아니다**
- 산출물에는 세션 값을 싣고, 그 사실을 경고문에 적는다

실측(KJPDS02 PV): 세션 611/611/0 · 문서 611/611/0 → 경고 없음. 대조군으로 세션을 600 으로
바꾸면 `[evidence] 총 TC: VectorCAST 세션 600 와 SwITR 문서 611 가 다릅니다` 가 뜬다.

⚠ **`sitr_*` 를 단언하는 테스트가 0건이었다** — 그래서 죽은 읽기가 안 잡혔다. 회귀 가드는
`tests/unit/test_swit_comprehensive_aggregator.py` `TestSwitrEvidenceIsActuallyRead` /
`TestSessionVsSwitrDivergenceIsReported` / `TestIt101ReadsSitrKeysFromTheSwitrDict`
(뮤테이션 12/12).

### 아직 못 잰 것

`_load_fault_injection_summary` 도 시트명 정확 매칭(`FI_Test Case`, 실패 시 **첫 시트**로 폴백)
+ 열 하드코딩(3/2/15~19/4/5/6)이다. **FI 정본 파일이 실물로 없어 대조 불가**라 손대지 않았다
(그 부재는 빌드 경고로 나간다). 파일이 확보되면 위와 같은 방식으로 잴 것.

## 33차 — Coverage Report v2.02 (xlsx)
- 회사 v2.02 양식 (HDPDM01 NE_GN7). 시트 구조: Cover / Test Summary / 1.Traceability / 2.Consistency / 3.Coverage / History (SwUT v3.01과 동일)
- 입력: VectorCAST log (`U:\...\08.SW 통합테스트\03.Test Result\01.Log\v<VER>_<DATE>\`)
- ASIL source: c_source_root + swuds_docx_path (SwUT 32차 W28 정책 동일 — c_source 우선)
- 파일명: `(HDPDM01)SwIT Coverage Report_v<VER>_<DATE>_R.xlsx`

## 34차 — SITR v2.02 (xlsm, keep_vba=True)
- 회사 v2.02 양식 (HDPDM01_SITR NE_GN7). 시트 구조: Cover / Test Summary / Deviation / Test Log / (옵션) 2.Consistency / History (SwUT SUTR v3.01과 동일)
- 입력: Coverage와 동일 (log_folder / c_source_root / swuds_docx_path)
- 31차 W27 ASIL col+4/5 시각 강조 정책 SUTR과 대칭 — Test Log row ASIL B(파랑)/C(주황)/D(빨강)
- 파일명: `(HDPDM01_SITR) Software Integration Test Result_v<VER>_<DATE>_R.xlsm`
- VBA 매크로 보존 (keep_vba=True) — 실 실행 검증은 사용자 의무 (deep-reviewer W2)
- `deviation_cases` body 필드 (SwUT 13차 C3 정책 동일 — 256KB / item key ≤ 20)
- Semaphore 공유 (Coverage와 동일 instance, capacity 2)

## 재활용 자산 (33/34차 합산 ≥85%)

| 자산 | 33차 활용 (Coverage) | 34차 활용 (SITR) |
|------|---------------------|------------------|
| `swut_input_adapter` SwUTSession / aggregate_session | `swit_input_adapter.collect_swit_session` thin wrapper | 동일 |
| `swut_coverage_aggregator._compute_asil_distribution` / `_compute_self_consistency` / `_write_history_sheet` / `_write_consistency_sheet` | 시트 writer 6개 import | History + Consistency import |
| `swut_sutr_aggregator._write_cover` / `_write_test_summary` / `_write_deviation` / `_write_test_log` | (Coverage는 별도 writer) | **시트 writer 4개 import** |
| `excel_template_utils` (safe_write / mark_asil_* / has_vba_macros / inspect_vba_refs) | 일반 목적 | 일반 목적 + VBA 검사 |
| `swut_asil_resolver` + `swut_swuds_parser` | ASIL 매핑 동일 | 동일 |
| `swut.py` Semaphore / StreamingResponse / X-* 헤더 패턴 | `routers/swit.py` Coverage endpoint | SITR endpoint도 Semaphore 공유 |

## SwIT 도구별 차이 (SwUT 대비)
- 신규 `swit_meta.SwitCoverageBuildMeta` (`doc_id_base="HDPDM01-SwIT"`, default `asil_level="ASIL B"`)
- 신규 `swit_meta.SwitSitrBuildMeta` (`SutrBuildMeta` 상속, `doc_id_base="HDPDM01-SITR"`, `final_test_result="OK"`)
- 신규 `SwITBuildRequest` + `SwITSitrBuildRequest` Pydantic (SwUT 17 필드 동일 + ASIL B default, SITR은 `deviation_cases` 추가)
- 신규 endpoint:
  - `/api/swit/coverage/build` (xlsx)
  - `/api/swit/sitr/build` (xlsm, keep_vba)
  - Semaphore(**2**) 공유 (SwUT 3 — SwIT 신규라 보수적)
- X-SwIT-Summary / X-SwIT-Warnings 헤더 (SwUT와 분리)

## 35차 — Consistency Checker + Frontend SwITBuildSection
- **Backend** `backend/services/swit_consistency_checker.py` — SwUT `check_swut_consistency` thin wrapper. `tc_prefix="SwITC"` 전달로 SwUT 18차 인프라 재활용
- **Backend** `swut_consistency_checker.py`에 `tc_prefix` kwarg 도입 (default "SwUTC", SwIT는 "SwITC"). `_extract_coverage_summary` / `_extract_sutr_summary` / `_collect_tc_to_function` 3 곳 동적 regex로 변경. SwUT 회귀 영향 없음
- **Backend** `/api/swit/consistency/check` endpoint — SwUT `_run_consistency_safely` 패턴 차용, Semaphore 미적용 (read-only)
- **Frontend** `frontend-v2/src/components/sections/SwITBuildSection.jsx` (신규, ~430 lines) — SwUTBuildSection 패턴 차용. 3 섹션: Coverage 빌드 / SITR 빌드 / Coverage↔SITR consistency 검증. localStorage 키 `devops_v2_swit_form` (SwUT와 분리). X-SwIT-Summary/Warnings 헤더
- **헤더 계약 (X3)**: `X-SwIT-Summary`는 1024B 초과 시 `asil_d_function_ids`가 sentinel string으로 축약될 수 있다(backend JSON-valid 보장). frontend는 반드시 `try/catch` + `JSON.parse` fallback으로 파싱 — 상세 [swut_builder.md](swut_builder.md) `## Frontend UI` 참조
- **Frontend** Detail.jsx에 SwIT 빌드 탭 추가 (icon 🧩, id 'swit')
- 회귀: backend +5 / frontend +8

## 라운드 archive (36-fix ~ 58차)

> **44차 W21 (이후 누적 정비)**: 36-fix ~ 58차 상세 라운드 노트는 [`docs/rounds/sw_test_round_history.md`](../rounds/sw_test_round_history.md)로 분리 (본문 비대화 해소). 본문에는 아래 summary table 1행 + 33~35차 핵심 정책만 유지하고, 신규 라운드 detail은 commit 직후 같은 파일에 누적한다.

| 라운드 | 주제 | 회귀 (backend) |
|--------|------|---------------|
| 36-fix | SwIT log filename `SwITC_` prefix 지원 (Critical) | 1842 → 1849 (+11) |
| 37차 | log_folder 자동 latest release 선택 | 1849 → 1854 (+7) |
| 38차 | DRY/`__all__`/dry-run preview/`_safety` 통합 | 1854 → 1875 (+21) |
| 39차 | Cloudium 동적 allowed_prefixes + PathPickerDialog UX | 1875 → 1895 (+20) |
| 40차 | Backend Admin Role 시스템 (A안: 전체 admin only) — 보안 강화 | 1895 → 1952 (+57) |
| 41차 | Bootstrap admin + APIRouter deps + visibility refresh | 1952 → 1956 (+4) |
| 42차 | error_handler nested + mask_user + retry + debounce | 1956 → 1968 (+12) |
| 43차 | 42차 자체 평가 W19/W20/W23/W24 — mask_user public + StrictMode safe + error_handler 빈 dict fallback | 1968 → 1970 (+2) |
| 44차 | 43차 자체 평가 W21/W25/W28/I3 — CLAUDE.md archive 분리 + act() 정리 + error_handler falsy + deprecation | 1970 → 1972 (+3) |
| 45차 | **C1 JWT/세션 인증 도입** (X-User spoofing 차단) — auth_service/users/AuthContext/Login/AuthGate | +51 backend / +7 frontend |
| 46차 | 45차 자체 평가 W32/W33 — timing attack 차단 + PW UX 72-byte 안내 | 2013 → 2016 (+3) / frontend +5 |
| 47차 | 46차 자체 평가 W34/W35/W36/I5/I7 — refresh token revocation + 자동 refresh queue + JWT 운영 매뉴얼 | 2016 → 2028 (+12) / frontend +5 |
| 48차 | 47차 자체 평가 C5/C6/C7 + W43/W44/W45 — logout DEV_MODE bypass 차단 + postSse refresh queue | +2 backend / +1 frontend |
| 49차 | swut_meta.json fallback (c_source_root/swuds_docx_path/swit template) | 2030 → 2030 (변경 0, 50차 fallback 회귀로 +9) |
| 50차 | 403 raw fetch fix (X9) + C1/C2 fallback 회귀 + W4/W5 source origin 시각화 + SwIT meta config approvers | 2030 → 2042 (+12) |
| 51차 | Template 2-field 분리 (Coverage/SUTR/SITR) + schema + router + frontend UI | 2042 → 2042 (회귀 갱신, +sutr maxlen 1) |
| 52차 | 51차 자체 평가 fix — localStorage legacy 마이그레이션 + endpoint별 정확한 field 사용 검증 (+4) + cloudium Test Result prefix 추가 | 2042 → 2046 (+4) |
| 53차 | deep-reviewer 발견 Critical 2 + Warning 회귀 3 — Pydantic extra=forbid + cloudium add_prefix blacklist + SwIT req priority/localStorage migration/source origin parse_warnings 회귀 | 2046 → 2048 (+2 backend, frontend +2 SwUT/SwIT migration) |
| 53-fix | 53차 자체 평가 fix — 시트명 substring/extra=forbid 회귀 + blacklist 확장 (/var, /boot, /lib, /lib64) + `_is_blacklisted` 단위 회귀 | 2048 → ~2060 (+12: cloudium parametrize 24 + extra=forbid 3 + sheetname 2) |
| 54차 | SwIT v2.02 양식 본격 호환 — `excel_layout_resolver` 신규 (template inspect + lru_cache) + `swut_meta_resolver` DRY 통합 + writer `layout` kwarg + B17 TC stats + B22 SwITS + Test Log AL marker | ~2060 → ~2078 (+18: layout_resolver 10 + meta_resolver 9 + v202 writer 9) |
| 54-fix | deep-reviewer 발견 C1 SwUT layout inspect (silent 빈 셀 차단) + C2 ZIP bomb 방어 + W1 Lock + W2 swit alias 통일 + W3 maxsize 8 + W4 blocked_inferred 시각 안내 + AL marker None | ~2078 → ~2082 (+4: C1 v202 fill 2 + C2 zip_bomb 1 + corrupted_bytes 갱신) |
| 55차 | frontend blocked_inferred UI 경고 panel (54-fix W4 cross-stack 완성) + swut_meta_resolver 5 함수 docstring 보강 (I2 plan vs 구현 divergence 명시) | backend 무변경 / frontend 263 → 267 (+4: SwIT 2 + SwUT 2 panel 렌더/미렌더) |
| 55-fix | 사용자 라이브 산출물 검증 보고 fix — History 시트 single-row (사용자 결정 B, release_sw_version + test_date 1 row) + TC stats 'Total Number of TCs' candidate 추가 + label_row + 1 (data row) 보정 | 회귀 row 보정만 (439 SwUT/SwIT batch 통과) |
| 55-fix-2 | deep-reviewer 발견 Warning 6건 통합 — W1 SwitLayout docstring + W2 doc_kind 표준화 (SwUT/SwIT prefix) + W3 stale 회귀 갱신 + W4 data row 검증 (silent overwrite 방어) + W5 Requirements row 가드 + W6 빈 입력 warning 누적 | 439 → 444 (+5: W4 1 + W6 4 + W3 갱신) |
| 55-fix-3 | deep-reviewer 발견 Warning 4건 통합 — W10 v2.02 helper 추출 (DRY 위반 해소) + W8 W4 skip 시 산출물 노란 강조 (audit silent fix) + W9 author 빈 warning + doc_kind context (I6 동시) + W7 SwUT SUTR W4 회귀 추가 | 444 → 446 (+2: W7 SUTR 가드 회귀) |
| 56차 | 사용자 라이브 환경 backend 에러 2건 + Coverage 시트 fill 누락 통합 fix — T306 Coverage v2.02 label-missing fallback (B17:F18 + B20~B22 stamp) + T307 CloudiumGateMiddleware ASGI 리팩토링 (starlette known issue #1438 차단) + T308 log_folder Pre-flight UNC check (400 + PATH_MODE_MISMATCH) | ~2082 → 2139 (+57: T306 +5 + T307 +2 + T308 +13 + 기존 회귀 갱신) |
| 56-fix | T312 StreamingResponse → Response (h11 LocalProtocolError 차단) + T313 Coverage Cover Version fill (SUTR과 비대칭 해소) | 2139 → 2139 (회귀 영향 0) |
| 57차 | SUTR/SITR Test Log 1941 TC 매칭 — T314 `_write_test_log` 재작성 (Coverage TC source 공유 + 회사 v2.02 양식 1 TC당 6 row step 자동 감지) + T315 SITR 자동 효과 (sutr_aggregator import 재사용) | 2139 → ~2145 (+6: layout step +3, SUTR test_log step +3) |
| **58차** | **F1/F2/F3 통합 fix** — F3 SwIT SITR column layout-aware (`SwitLayout` 6 신규 col field + `_scan_test_log_columns`, v3.01 hardcode fallback) + F2 SwIT Coverage Traceability dynamic header (`traceability_header_row` + `_scan_traceability_header`, max_row 20→30 / SwUFn_ 임계 50→5 완화) + F1 SUTR Actual via BeautifulSoup (`ExecutionRow.actual_result` 신규 + `extract_execution_results_with_actual` — vcast_parser 결함 우회). 라이브 검증: Actual stamp **0% → 98.8%** (1918/1941), SwIT Coverage O stamp **0 → 335**, SwIT SITR column B/H/R/AB/AL/AN 정확 | ~2145 → ~2160 (+15: layout column 4 + traceability 4 + inspect_sitr 2 + actual 4 + traceability stamp 1) |
