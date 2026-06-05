# SwSA Builder 설계서 (Software Static Analysis Report 자동화)

> 회사 v0.10 SwSA 템플릿(.xlsm)에 정적분석 로그(QAC/PMD/CodeSonar/CodeEye)를
> 파싱·집계해 셀병합·폰트·매크로를 보존한 채 자동 작성. SwUT/SwIT template-copy
> 인프라 70~98% 재활용 + 기존 QAC 파서 재활용. 웹에서 INPUT 경로만 제공.

## 1. 입력 자산 (실측, KJPDS02 PV 기준)

| 자산 | 경로 패턴 | 비고 |
|------|-----------|------|
| 템플릿 v0.10 | `…/2220 개발표준 Template/…/08.SW 정적분석/02.Result Report/(XXXX_SwSA)…v0.10_2XXXXX.xlsm` | 17시트(IT801/BTB 有, **ST1101 無**) |
| 레퍼런스 PV v0.11 | `…/04 KJPDS02/…/02.Result Report/(KJPDS02_PV_SwSA)…v0.11_260424.xlsm` | 16시트(ST101~**ST1101**, IT801/BTB 無) |
| 로그 루트 | `…/04 KJPDS02/…/01.Log/PV/<TOOL>/<MODULE_날짜_버전>/…` | TOOL∈{QAC,CodeSonar,CodeEye,PMD} |

로그 종류:
- **QAC** (Helix QAC 2025.1): `results_data.xml`(+`.pb2`), `*_RCR_*`/`*_SCR_*`/`*_HMR_*.html`. 구 PRQA(`NE1AW_…`) + 신 Helix(`NE1aW_…`) 혼재.
- **PMD**: `*_PMD_Report_*.txt`(CPD) + `*.png`
- **CodeSonar**: `CodeSonar_*.pdf`, **CodeEye**: `종합보고서_*.pdf`/`검사완료보고서_*.pdf`

> 실 경로는 Cloudium read-only. 런타임은 `file_resolver` worker(8765) 경유. 개발 샘플은
> `.codex_tmp/swsa_samples/`(gitignore)에 worker로 추출.

## 2. 문서 구조 (16시트, 실측)

| 시트 | fill_mode | 소스 | 비고 |
|------|-----------|------|------|
| Cover | META | web form | Doc ID/Version/Status/Date/Author (G26~G30, 라벨 col C) |
| History | META | web form | 최신행에 Version/Date/Desc/Author |
| Guideline / 검증 항목 | MANUAL | 정적 boilerplate | ASIL ●◎ / 진행 O/X 수동 |
| Summary | META + **FORMULA** | web form 헤더 + ST 시트 수식집계 | 헤더 E3~E10 입력; 매트릭스 16~37행은 `='1.ST101'!C4`/`INDIRECT` 자동 |
| **1.ST101** | **AUTO** | QAC `results_data.xml` (M3CM) | 코딩 가이드라인 위반(MISRA C:2012) |
| **2.ST201** | **AUTO** | QAC HMR + PMD | 코드 메트릭(ST201~204) + 중복(ST206) |
| 3.ST301 / 4.ST401 | PDF | CodeSonar pdf | Run-Time Error / Global Var Init (Phase 3) |
| 5.ST501·6.ST601·7.ST701·8.ST801·9.ST901 | MANUAL | HKSAT(로그 부재) | Error Pattern/Timing/Race/Recursion/Change Impact |
| 10.ST1001 | PDF | CodeEye pdf | Open Source (Phase 3) |
| **11.ST1101** | **AUTO** | QAC `results_data.xml` (HKCCM) | 시큐어 코딩 (PV 한정, v0.10 템플릿엔 없음) |

**핵심**: 빌더는 **템플릿에 존재하는 시트만 감지해 채움**. v0.10(generic)엔 ST1101 없음 → graceful skip.

## 3. 버전 간 구조 분기 (라벨 앵커 필수)

- **컬럼 레이아웃 2종**: ST101~1001(데이터 col C, Result H/I) vs **ST1101(+1 shift: col D, Result I/J)**.
- **ST101 결과표 분기**: v0.10 = 단일행(위반룰수=B/총위반=D/예외=F/수정=H/결과=J, row77), v0.11 = Mandatory/Required/Total 3행(컬럼 +2 shift). → **하드코딩 좌표 금지, `find_kv_row`/라벨 스캔 기반 `swsa_layout_resolver` 의무**.
- ST601은 P/F가 I8(불규칙), 미수행 시트는 헤더 공란.

## 4. 셀 ↔ 소스 매핑 (AUTO 시트, 정책: active 위반 기준)

### ST101 (QAC results_data.xml → M3CM)
- 총 위반 = `misra.active` (제외 후). Mandatory = `category("MISRA Mandatory").active`, Required = `MISRA Required`.
- 위반 룰 개수 = `distinct_rules(active)`. 상세표 5.1 = `rules_sorted()` per-rule(rule_id/description/active).
- 도구명/Version = xml `helix_qac_version`. LOC = SCR/RCR Summary (medium).
- **예외처리/수정대상/P-F** = 리뷰어 Deviation 판정 → 로그 부재 → **노란 표시 + 폼 입력** (`mark_user_input_required`).

### ST201 (QAC HMR → ST201~204, PMD → ST206)
- ST201 STCYC / ST202 STMIF / ST203 STM29 / ST204 STCALL: `parse_st201_from_hmr` 밴드 집계(함수개수/밴드별/Fail). verdict=Fail if fail_count>0.
- ST205 Recursion(STNRA): **HMR 부재** → 노란 표시.
- ST206 Duplicated: `parse_pmd_cpd` 밴드(0-9/10-49/>=50) + 블록별 예외표.

### ST1101 (QAC results_data.xml → HKCCM, LAYOUT-B col D/J)
- 총 위반 = `secure.active`. 카테고리맵 = `by_prefix()` (INT/DCI/POS/EXP…), severity = High/Middle/Low(상/중/하).
- 코딩룰 버전 = 'HKMC 4.1' (config).

## 5. 컴포넌트 (재활용률)

| 컴포넌트 | 재활용 | 상태 |
|----------|--------|------|
| excel toolkit (safe_write/mark_*/keep_vba) | 100% `excel_template_utils` | 기존 |
| cloudium 파일접근 | 98% `file_resolver` | 기존 |
| QAC HMR 파서 | 90% `qac_parser` | 기존 |
| **swsa_qac_xml_parser** (ST101/ST1101) | 신규 | ✅ **Phase 1a 완료** |
| **swsa_st201_binner** (ST201~204) | qac_parser 재사용 | ✅ **Phase 1a 완료** |
| **swsa_pmd_parser** (ST206) | 신규 | ✅ **Phase 1a 완료** |
| **swsa_layout_resolver** (라벨/레이아웃 감지) | `find_kv_row` 기반 | ✅ **Phase 1b 기반(b84c664)** — 병합라벨 흡수 |
| **swsa_meta** (`SwsaBuildMeta`) | `BuildMetaBase` 상속 | ✅ **Phase 1b 기반(b84c664)** |
| swsa_input_adapter (로그 수집) | `swit_input_adapter` thin | ⬜ Phase 1b (남음) |
| swsa_aggregator (orchestrator + 시트 writer) | 70% swut/swit aggregator | ⬜ Phase 1b (남음) — 다음 단계 |
| routers/swsa.py + SwSABuildRequest | 88~90% swit | ⬜ Phase 1c |
| SwSABuildSection.jsx | 92% SwITBuildSection | ⬜ Phase 1c |

## 6. Phase 1a 산출물 (완료, 26 tests)

- `backend/services/swsa_qac_xml_parser.py` — `parse_qac_results_xml()` → `QacXmlResult{misra,secure,groups}`. dataroot[project] 단일 사용(per-file 2× 차단), 카테고리(Mandatory/Required)·leaf 룰·by_prefix 노출. (10 tests)
- `backend/services/swsa_st201_binner.py` — `parse_st201_from_hmr()` / `bin_metric_functions()`. ST201~204 밴드. 신/구 자동감지. (8 tests)
- `backend/services/swsa_pmd_parser.py` — `parse_pmd_cpd()` → 블록/밴드/verdict. (8 tests)
- 실 KJPDS02 로그 회귀(skipif): M3CM active=286(Man 233/Req 52), HKCCM active=210; HMR 878함수; PMD 21블록/812줄.

## 7. 리스크

1. 구 PRQA HMR(2631 빌드) 파싱 실패 — `qac_parser` old_version 미지원. 신 Helix는 정상. 레퍼런스 빌드가 구 포맷이면 ST201 수동.
2. 예외처리/수정대상은 로그 부재 → 항상 노란 표시 + 폼.
3. ST1101 max_row≈100만(전열 서식) — bounded iteration 의무.
4. total vs active 모호(제외 룰) — 기본 active, total 별도 노출.
5. 가용 로그(NE1aW 5월/FBL)는 레퍼런스(2631 3월)와 다른 빌드 → **포맷 검증용**. 실 라이브 검증은 레퍼런스 동일 빌드 로그로 build→cell 대조.

## 7b. 심층 리뷰 (deep-reviewer ×2 라운드) 수정 내역

opus deep-reviewer 2회 + workflow 2회로 실데이터 검증 후 수정 (모두 commit):

**보안/무결성**:
- admin gate: `/api/swsa` 라우터 `require_admin` (SwUT/SwIT 대칭). local 모드 임의 read 차단.
- 수식 보존: `is_formula_cell` 가드 — v0.11 양식 summary 셀(`=COUNTIF`/`=I127`/`=$E$79`)을
  literal 로 덮지 않음. 예외처리 셀은 `mark_user_input_fill_only`(텍스트 없는 노란)로 `#VALUE!` 방지.
- CRLF: project_id/doc_version 등 헤더 유입 필드 `_no_newline` + ascii_name strip.

**audit 정확성**:
- 더블카운팅: HMR/PMD 모듈별 여러 분석 날짜 합산(2088) → `_select_latest_per_module`(1053).
- ST201 밴드-0: 첫 밴드 하한 개방 — HIS metric 0값(nesting/param) 드롭 방지 (878 흡수).
- deviation 노출: 제외율 ≥70% 경고 (active 만 표시함을 환기).
- parser parse_warnings → result 전파 ([QAC]/[HMR]/[PMD]).

**기능 갭**:
- History 시트 `_write_history` 신규 (첫 빈/placeholder 행 탐색 + append, 기존 이력 보존).
- Cover 사인오프 Reviewer/Approver(J3/K3).

**검증된 의미론**: active = QAC deviation-adjusted (정답). active 210=RCR, excluded-sum 1864=SCR.

## 7c. v0.11 full-support 스펙 (다음 증분 — rank 2/3/4)

v0.10(빌드 타깃)은 완전 동작. v0.11 양식은 summary 셀이 **detail 표 참조 수식**이라
detail 을 채워야 완성 (현재는 수식 보존 + 경고). 필요 작업:

1. **per-module 데이터** (prereq): `merge_qac_results` 가 APP+BOOT 를 rule_id 별 합산해
   per-module 손실. `QacLeafRule.per_module: dict[prefix,(total,active)]` 추가 또는
   `SwsaInputData` 에 pre-merge per-module 결과 보존.
2. **ST101 5.1 detail** (rows 86~110): 템플릿이 룰 목록(C=Rule ID/D=카테고리/E=설명) 보유.
   각 행 Rule ID 매칭 → **J=APP active, K=BOOT active, M/N=excluded** 기입 (B=ROW()/L=비율
   수식 보존). 그러면 D77(`=COUNTIF(L86:L102,">0")`)/F77(`=I127`)/H77 자동 재계산.
3. **ST1101 detail** (rows 92~102 + 예외표 126~191): HKCCM 코드(C-INT/DCI/POS…) 매칭.

> 빌드 타깃이 v0.10 generic 인 한 불필요. KJPDS02 v0.11 flavor blank 템플릿 빌드 시 착수.

## 8. 사용자 결정 (확정)

1. Phase 1 = QAC 3시트(ST101/ST201/ST1101) 먼저, 나머지 양식/메타 + 노란 표시.
2. 판정 셀 = 노란 표시 + 선택 폼입력.
3. 검증 = 빌드→레퍼런스 셀 대조 PoC.
