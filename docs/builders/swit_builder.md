# SwIT Builder (Software Integration Test, 33~35차 라운드~)

> CLAUDE.md on-demand 레퍼런스 — SwIT Coverage/SITR/Consistency 빌더 작업 시 참조.
> 관련: [`swut_builder.md`](swut_builder.md), [`visual-marking-and-design-tokens.md`](visual-marking-and-design-tokens.md)

ISO 26262 ASIL B+ 통합 테스트 산출물 자동 생성. SwUT 30~32차 인프라 **81% 재활용**.

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
