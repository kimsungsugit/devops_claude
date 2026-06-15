# SwUT Builder (Software Unit Test, 8~20차 라운드)

> CLAUDE.md on-demand 레퍼런스 — SwUT Coverage/SUTR/Consistency 빌더 작업 시 참조.
> 관련: [`swit_builder.md`](swit_builder.md), [`visual-marking-and-design-tokens.md`](visual-marking-and-design-tokens.md)

ISO 26262 ASIL A 단위테스트 산출물 자동 생성 + cross-validation 플랫폼.

## audit 자동화 현황 (Coverage Report v3.01 6시트, SUTR v3.01 5시트)
| 시트 | Coverage | SUTR |
|------|---------|------|
| Cover / Test Summary | ✓ meta 자동 | ✓ meta 자동 |
| 1.Traceability (TC×Function 매트릭스) | ✓ (7차) | N/A |
| **2.Consistency** (자체 일관성 + SwUDS 매핑) | **✓ 4 row + 옵션 5번째 (15~16차)** | **✓ 17차 대칭** |
| 3.Coverage | ✓ | N/A |
| Deviation / Test Log | N/A | ✓ |
| History (git log) | ✓ (6차) | ✓ |

## 입력 데이터 흐름
1. **Jenkins build cache 우선** — `collect_from_jenkins_cache(scan_jenkins_build_root)`
2. **log_folder fallback** — VectorCAST 결과 디렉토리 직접 파싱
3. **template** — 회사 v3.01 xlsx/xlsm template-copy 전략 (스타일/머지셀/매크로 보존)
4. **swuds_docx_path (옵션, 16차)** — python-docx로 SwUFn_NNNN heading 추출

## Cross-validation (18차, `swut_consistency_checker.py`)
- **uncovered_mismatch**: 미커버 Function ↔ 미실행 TC 일치성
- **exception_deviation**: Coverage Exception 합 ≥ SUTR Deviation TC 수
- **total_tc**: Coverage Traceability TC 수 == SUTR Total
- **final_result**: 'PASS' / 'OK' 표기 통일

## 메모리 / 동시성 (14차/17차/20차/31차)
- 14차 W1: `xlsx_io: BytesIO` lazy + StreamingResponse 64KB chunk → 메모리 1배 절감
- 17차: Semaphore(2) → (3) 상향 (worst 1.8MB×3=5.4MB)
- 20차: psutil 기반 메모리 모니터링 로그 (`mem_mb=...,delta=...`)
- **31차 W31**: 30차 c_source_root 도입 후 worst-case 갱신 — `parse_c_project` 동시 3건 추가 2.4MB×3=7.2MB. 총 worst-case ≈ **12.6MB** (5.4MB 빌드 + 7.2MB c_parser). 운영 안전 한도 내

## ISO 26262 Tool Qualification
모든 builder result에 `tool_qualification` 메타 포함:
- `evidence_class: "auto-generated draft"`
- `asil_a_usage: "reviewer 검토 후 evidence 사용 가능"`
- `asil_b_c_d_usage: "단독 evidence 사용 금지 — manual review 의무"`

## Frontend UI
- `SwUTBuildSection.jsx` (Detail.jsx 탭 `🧪 SwUT 빌드`)
- Form 입력 (project/release/date/log_folder/template/swuds) → Coverage/SUTR 빌드 → blob 다운로드
- 동일 페이지 하단 Consistency Check 섹션 (19차) — issues 카드 severity별 색상
- **헤더 계약 (X3, 30차 W21 — frontend 편집 시 필수 인지)**: 빌드 응답 헤더 `X-SwUT-Summary`/`X-SwIT-Summary`는 1024B 초과 시 `asil_d_function_ids`가 sentinel string으로 축약될 수 있다(backend가 JSON-valid 보장). frontend(`SwUTBuildSection.jsx`/`SwITBuildSection.jsx`)는 헤더를 반드시 `try/catch` + `JSON.parse` fallback으로 파싱할 것 — `.json()` 기대/truncation 미고려 시 1024B 초과 케이스에서 summary 패널 silent 미표시. backend 로직: `backend/routers/{swut,swit}.py`.

## 입력 표면 매트릭스 (Pydantic, 13차+26차)
| 필드 | 검증 | Frontend Form (26차) |
|------|------|---------------------|
| release_sw_version | regex `^\d+\.\d+(\.\d+)?$` | ✓ 필수 |
| test_date / validation_date | regex `^\d{2,4}[-/]\d{1,2}[-/]\d{1,2}$` | ✓ (validation_date 26차 추가) |
| test_engineer | maxlen 100 + 줄바꿈 금지 | ✓ |
| reviewer_override / approver_override | maxlen 100 + 줄바꿈 금지 | **✓ 26차 W16 추가** |
| doc_id_sequence | digit only | ✓ |
| jenkins_build_number | ge=1 le=99999 | (옵션) |
| cache_root / log_folder / **coverage_template_path / sutr_template_path (51차 분리)** / swuds_docx_path | maxlen 500 + 줄바꿈 금지 | ✓ (PathPickerDialog 21차, **swuds_docx_path는 32차 W28 ASIL 2차 source 추가, 51차에 양식 path는 Coverage/SUTR 별도 Browse**) |
| **c_source_root** | maxlen 500 + 줄바꿈 금지 | **✓ 30차 W21 추가 (PathPickerDialog + Doxygen @asil 추출 — 1차 ASIL source)** |
| deviation_cases | max_length=200 + 합산 256KB + item key ≤20 | (programmatic) |

## 함수별 ASIL 등급 (W21+W29+W28, 30~32차 완료)

**구현 완료 (30/31/32차 commit)**:
- `backend/services/swut_asil_resolver.py` (30차) — C 소스 → `function_id → ASIL` 매핑 (1차 source)
- `backend/services/swut_swuds_parser.py` (32차) — SwUDS docx 'ASIL' 라벨 → `function_asil_map` property (2차 source)
- 기존 자산: `workflow/code_parser/c_parser.py::parse_c_project` (Doxygen `@asil`) + `_extract_description_from_table` 패턴 재활용
- `SwUTBuildRequest.c_source_root` (30차) + `swuds_docx_path` (16차+32차) — PathPickerDialog 연동
- Coverage / SUTR builder `summary.asil_distribution` + `asil_b/c/d_function_ids` + `asil_highlight_policy` (대칭)
- 3.Coverage / SUTR Test Log 시트 ASIL B(파랑)/C(주황)/D(빨강) row 시각 강조 (31차 W29)
- Frontend `.swut-asil-distribution-panel` + B/C/D 강조 클래스 + audit 정책 공지 카드

**ASIL Source 우선순위 (32차 W28)**: `c_source_root` > `swuds_docx_path` > 없음. 충돌 시 c_source 우선 + parse_warnings에 사유 누적. 구현 truth (C 소스 @asil)가 설계 문서(SwUDS)보다 정확하다는 가정.

**사용자 결정 (A2, 30차)**: 1.Traceability 시트 자체 변경 없음 (회사 v3.01 양식 호환 100%). ASIL 정보는 summary + UI + 3.Coverage / SUTR Test Log 시트 강조로 표현.

**ISO 26262 적용**:
- ASIL D 함수 식별 → audit reviewer 즉시 인지 (MC/DC 커버리지 필수 안내)
- c_source_root 미제공 시 graceful skip + parse_warnings 명시 (이전 운영 호환)
- evidence_class "auto-generated draft" 정책 유지 — manual review 의무 동일

**비-목표 (31차+)**:
- 1.Traceability 시트 자체에 ASIL 컬럼 (양식 영향)
- SUTR Test Log에 함수 ID/ASIL 컬럼
- SwUDS docx에서 ASIL 추출 (현재 C 소스 단일 출처)
- ASIL B/C 함수 시각 강조 (본 라운드는 D만)

## 시각 강조 / Design Token
→ [`visual-marking-and-design-tokens.md`](visual-marking-and-design-tokens.md) 참조 (SwUT/SwIT 공통).

## AuditLog 시트 정책 (라운드 83~87)

산출물 6번째 시트 'AuditLog' (회사 양식 영향 0 — 시트 추가만, 기존 시트 보존).
audit reviewer가 산출물 자체에서 빌드 환경 / ASIL source / 분포 / warnings / 분류 즉시 인지 (self-contained).

**6 섹션**:
1. **빌드 환경** (project_id/version/date/engineer/author/timestamp/sha256)
2. **ISO 26262 ASIL Source 활용도** (c_source/SUDS/SDS/SRS/SwUDS docx)
3. **ASIL 등급 분포** (D/C/B/A/QM/UNKNOWN/Total, 라운드 81 5단계)
4. **빌드 결과 통계** (envs/TCs/passed/failed/not_executed/function_count)
5. **Parse Warnings** (top 20, silent skip 차단)
6. **Tool Qualification** (evidence_class / ASIL usage / Round 추적)

**section 3-1 UNKNOWN 함수 분류** (라운드 86~87 추가):
- `c_only` — c source 존재 + SUDS 미등재 → SUDS docx 보강 필요
- `stub` — `_` / `stub_` prefix → 자동 생성 (정상 skip)
- `orphan` — c source 부재 → 수동 검토

> **라운드 87 통합 효과 (HDPDM01 v23)**: UNKNOWN 12건 자동 분류 → c_only 11
> (`g_ApiIn_LinRx_ReadData` 등) + orphan 1 (`ADC0_stop_current_workaround`). audit
> reviewer가 SUDS 등재 누락 함수 즉시 식별.

## Workflow & Tests (33차 갱신 — 실측)
- Backend SwUT 전체 회귀: **~301개** (31-fix +5 / 32차 W28 +8)
- Backend SwIT 회귀: **65개** (33차 25 + 34차 28 + 35차 5 + 36-fix 7 — `_extract_env_from_filename` SwIT prefix)
- Backend 37차 신규: **+7** (`TestResolveLatestReleaseFolder`: Case A/B/C + non-release skip + missing-subfolder skip + W1 mixed suffix + W2 silent fallback)
- Backend 38차 신규: **+21** (helpers 3 + safety 9 + preview 4 + edge case 3 (1 skip) + C2 cloudium 2)
- Backend 39차 신규: **+20** (cloudium_extra_prefixes 11 + file_mode_router 9 — add/remove/list × cloudium-only/normal/duplicate/422)
- Backend 40차 신규: **+57** (admin_users 12 + auth_router 6 + admin_gate 39 parametrize 13 endpoint × 3)
- Backend 41차 신규: **+4** (bootstrap_from_env env handling 4 시나리오)
- Backend 42차 신규: **+9** (bootstrap +1 _mask_user + error_handler_nested 7 + admin_gate +0)
- Backend 전체: **1965~1968개** (.venv Python 3.12.6 — 1956 → ~1968 +9~12, 회귀 진행 중)
- Frontend AdminContext: **7개** (40차 4 + 41차 1 + 42차 +2 debounce/retry)
- Frontend 전체: **242개** (240 → 242 +2)
- Frontend SwUTBuildSection: **26개**
- Frontend 전체: **220개** (23 test files)

## 30차 W21 deep-reviewer Critical/Warning fix (commit 진행 의무)
- **Critical (X5/S3 path traversal)**: `swut_asil_resolver` 에 시스템 디렉토리 blacklist (Windows: `C:/Windows`, `Program Files`, POSIX: `/etc`, `/root`, `/sys`, `/proc` 등) 추가 — `allowed_roots` 미지정해도 backstop으로 거부. ISO 26262 audit 도구 보안 경계.
- **Warning (X3 헤더 truncate)**: `_build_result_to_response`에서 `X-SwUT-Summary` 1024B 초과 시 `asil_d_function_ids` list를 길이 sentinel string으로 축약 + JSON valid 보장 fallback. frontend silent 미표시 회피.
- **Info (색상 충돌)**: `mark_asil_d_function` ↔ `mark_fail_cell` 동일 RGB이나 시트 분리 (3.Coverage = ASIL D 전용, 2.Consistency = FAIL 전용) — docstring + [visual-marking-and-design-tokens.md](visual-marking-and-design-tokens.md) 정책에 명시. 동일 시트 두 강조 동시 시 fix.
- Cloudium worker는 read-only — 절대 cloudium 파일 생성/수정 금지 (사용자 의사결정)
- 라이브 검증 PoC: `.codex_tmp/poc_live_full_verification.py` (maintained, 사용자 환경에서 직접 호출)

> **회귀 카운트 측정 명령** (정확치 재확인 시):
> ```bash
> # .venv Python 3.12 권장 (운영 환경 동일). msys64 mingw Python은 os.sep='/' quirk 주의.
> .venv/Scripts/python.exe -m pytest tests/unit/test_swut_*.py tests/unit/test_excel_template_utils.py --collect-only -q | tail -3
> cd frontend-v2 && npx vitest run src/__tests__/SwUTBuildSection.test.jsx --reporter=basic
> ```

## Backend Reload 절차 (26차 C6 명시)

backend 코드 변경 (`backend/services/`, `backend/routers/`, `backend/schemas.py` 등)
후에는 **반드시 backend 재시작 필요** — uvicorn에 `--reload` 옵션이 없으면 stale
코드가 호출되어 PoC / endpoint 결과가 신규 변경 반영 안 됨.

### 절차
1. **재시작 방식 (권장)**: 기존 backend 종료 (Ctrl+C 또는 작업 관리자) →
   `cd backend && uvicorn main:app --reload --port 9000` (개발 모드 `--reload` 권장)
2. **포트 충돌 시**: `netstat -ano | findstr 9000` → PID 확인 → 종료
3. **Cloudium 모드 stuck 방지**: PoC 종료 시 항상 `_restore_local_mode()` finally
   (22차 T188 패턴). cloudium 모드 + worker 미실행 시 모든 read 403

### 변경 영향 매트릭스
| 변경 영역 | reload 필요? |
|----------|-------------|
| `backend/services/*.py` | ✅ 필수 |
| `backend/routers/*.py` | ✅ 필수 |
| `backend/schemas.py` | ✅ 필수 (Pydantic schema cache) |
| `backend/main.py` | ✅ 필수 |
| `config/swut_meta.json` | 12차 lru_cache + mtime invalidate — **자동** |
| `frontend-v2/src/*` | ❌ Vite HMR (자동) |
| `.codex_tmp/poc_*.py` | ❌ 매 실행 새 process |

## SwUT 관련 path (사용자 환경 의존 — W23, 28차 추가)
- VectorCAST log 디렉토리 (`log_folder`): 예) `U:/연구소/.../HDPDM01/.../vectorcast/results/` — Cloudium worker(read-only)로 접근
- 회사 v3.01 template (`template_path`): 예) `U:/연구소/.../양식/(HDPDM01)Coverage_Report_v3.01.xlsx`, `(HDPDM01)SUTR_v3.01.xlsm`
- SwUDS docx (`swuds_docx_path`, 옵션): 예) `U:/연구소/.../(HDPDM01)SwUDS_v3.docx`
- SwUT meta config: `config/swut_meta.json` (lru_cache + mtime invalidate, 12차)
- 산출물 임시 디렉토리 (PoC 산출물 검수용): `.codex_tmp/live_full_2026_05_12/` (gitignore)
- localStorage form 보존 key: `devops_v2_swut_form` (frontend)
- localStorage 사용자 식별: `devops_v2_user` (USER_KEY)

> 실 경로는 라이센스/보안상 사용자 환경에서만 유효 — 위 예시는 표기 패턴이며 git에 commit 금지.
