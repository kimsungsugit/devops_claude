# SW Test Result Report — 전 레벨 통합 Summary 빌더 (ES95411)

> 완성된 레벨별 결과 산출물(SwUTCR/SwITCR/SwSA 등 ES95411-style detail 시트 보유 xlsm)을
> 파싱하여 마스터 리포트(ES95411)의 `Summary` 시트(ST 정적·UT 단위·IT 통합·ET 시스템
> 전 레벨)를 채운 `.xlsm`을 생성한다. 현재 수기로 유지되는 cross-level 통합표를 자동화.

## 배경 / 데이터 흐름

```
01.Test Specification (SwTS)
        ↓ 시험 수행
02.Test Result/01.Log (SwTL)
        ↓ 레벨별 집계 (기존 SwUTCR / SwITCR / SwSA 빌더)
   레벨별 산출물 (ES95411-style 'NN.<TestID>' detail 시트 + Result 블록 보유)
        ↓ ★ 본 빌더 (cross-level roll-up) ★
   ES95411 'Summary' 마스터 표 (.xlsm)
```

- 기존 `SwUTCR`/`SwITCR`의 "Comprehensive(CR)"는 **레벨 내** 통합이다. 본 빌더는 그
  산출물들을 가로질러 **UT+IT+ST+ET**를 한 Summary 표로 합치는 **cross-level** 통합으로,
  기존에 없던 신규 기능이다 (grep 0건 확인 후 신설).

## 핵심 모델 — Summary = detail 시트 Result 블록의 roll-up

v1.02 실 ES95411을 ground-truth로 검증(24/24행·Total 일치):

| 규칙 | 동작 |
|------|------|
| 매칭 키 | test ID (UT101/IT101/ST101…). Summary 행의 `SheetName`(P열) 또는 `ID`(E열)에서 선행 `NN.` 접두 제거 후 source 시트와 매칭 |
| 수행(O) primary 행 | detail Result 블록에서 분석차수·SW Ver.·Tester·Debugger·총분석시간·P/F 추출 → Summary 행(H/I/J/L/M/N) stamp |
| 미수행(X) 행 | 결과 컬럼 공란화 (hidden detail의 stale 값 무시) |
| sub 행 (ST202–211, IT802) | parent 시트 공유. meta(H/I/J/M 세로병합 + Debugger 행별)는 **template에 위임**(건드리지 않음), P/F만 parent 승계 |
| Total 행 | 점검대상(G)=수행 개수, 총분석시간(M)=합, P/F(N)=Fail 개수 |
| 헤더 블록 | Fail 개수(E11)·종합 Result(E12) 계산값 + meta override(Project/Phase/ASIL 등) |

## 컬럼 자동 감지 / 타 프로젝트 일반화

컬럼 위치를 **하드코딩하지 않는다**. `_locate_table`이 'ID' 라벨이 있는 행을 헤더로
잡고, 그 행 + 위 1행(2단 헤더)에서 알려진 라벨(`_HEADER_LABEL_MAP`: No/ID/Test
Name/점검 대상/분석 차수/SW Ver./Tester/Tool/Debugger/총 분석시간/P/F/Note/Sheet
Name)을 스캔해 **실제 컬럼 위치를 매핑**한다(`SummaryCols`). 못 찾은 라벨만 v1.02
default. 헤더 블록 값 열도 라벨 우측 첫 비어있지 않은 셀로 자동 감지.

결과: **공식 템플릿이나 타 프로젝트가 컬럼을 옮겨도**(예: 열 삽입) 데이터가 올바른
셀에 들어간다. 어떤 컬럼이 감지됐는지는 `summary.detected_columns`로 보고(매핑 누락
조기 발견용). 검증: 표준 v1.02(24/24 + 컬럼 14개 자동매핑) + 우측 이동 레이아웃
테스트(`test_column_autodetect_shifted_layout`) 양쪽 통과.

## ⚠ ES95411 양식이 어디에도 없다 (2026-08-26 실측)

KJPDS02 `template_paths.es95411_template` 이 가리키는
`(KJPDS02_ES95411) ES95411 Test Result Report_v1.02_260324.xlsm` 은 **실재하지 않는다.**
등록 경로 폴더는 물론 그 아래 `PV_2631` · `backup` · `backup/1.DV` 까지 전수 확인했고,
**회사 공용 양식 트리**(`★개발템플릿 Version3`)도 깊이 4까지 훑었다 — `ES95411` 이라는
이름은 **0건**이다.

같은 자리에서 대신 나온 것:

| 위치 | 파일 | 시트 |
|---|---|---|
| 프로젝트 `11.SW 테스트/02.Test Result/02.Result Report` | `(KJPDS02_SwTR) Software Test Result_v2.01_260629_R.xlsx` | Cover · History · 1.Test Summary · 2.Test Log |
| 공용 양식 `11.SW 테스트/03.최종 보고서` | `(XXXX_SwTCR) Software Test Comprehesive Result_v0.10_XXXXXX.xlsm` | **27시트** |

**후신 후보는 `SwTR` 이 아니라 `SwTCR` 이다.** SwTR 은 Cover/Test Summary/Test Log 4시트짜리
**SwT 레벨 산출물**이라 roll-up 이 아니다. 반면 SwTCR 27시트는 이렇게 생겼다:

    Cover · History · Guideline · 검증 항목 · Summary
    1.ST101 … 10.ST1001      (SW 테스트 10)
    11.UT101 … 13.UT301      (단위시험 3)
    14.IT101 … 21.IT801      (통합시험 8)
    통합검증_BTB

전 레벨(ST+UT+IT)을 한 파일에 담는 **마스터 roll-up** — ES95411 이 하던 역할 그대로다.
대조군인 SwITCR 공용 양식은 12시트(IT101~IT801)뿐이라 레벨 하나만 담는다.

계층도 맞아떨어진다: `09.SW 단위 테스트`→SwUTCR / `10.SW 통합 테스트`→SwITCR /
`11.SW 테스트`→**SwTCR**.

⚠ **아직 config 를 바꾸지 않았다.** 근거는 강하지만 "ES95411(사내 문서번호)이 표준 템플릿
Version3 에서 SwTCR 로 개명됐다" 는 **문서 체계에 대한 판단**이고, 틀리면 통합 Summary 가
엉뚱한 양식으로 나간다. 확인되면 `es95411_template` 을 SwTCR 경로로 바꾸고 파서의 시트
탐지(`NN.<TestID>`)가 27시트 배치에서도 도는지 재검증할 것.

**일반화 경계** — 회사 ES95411 표준 폼(동일 한글 라벨, 'Summary' 시트, 'NN.<ID>'
detail 시트 명명)을 쓰는 프로젝트면 동작. 라벨/구조가 근본적으로 다른 폼은
`_HEADER_LABEL_MAP`(표 헤더)·detail Result 블록 라벨(분석차수/Tester/P/F/준비/수행/
검토/Total) 확장이 필요하다.

## 데이터 변경 반영 (재빌드)

매 빌드는 template을 fresh 로드 + source로 stamp하므로 **소스 데이터가 바뀌면 그에 맞게
갱신**된다: 값/Tester/hours/P-F overwrite, 수행→미수행(O→X) 시 결과 컬럼 공란화, Total
재계산. **stale 빨강 처리**(`_apply_pf_fill`): Fail이면 빨강, Pass이면 셀에 **우리 FAIL
색이 남아 있을 때만** 제거 — populated 템플릿(등록된 v1.02처럼)이나 직전 출력에서
Fail→Pass로 바뀌어도 빨강이 잔존하지 않으며, 양식의 정당한 배경(다른 색)은 보존한다.
검증: `test_data_change_reflected_and_stale_fail_fill_cleared`,
`test_data_change_performed_to_not_performed_clears_row`.

## 시각 서식 보존 (검증 완료)

template-copy + `safe_write`(값만 기록, 스타일 객체 보존)이므로 출력은 템플릿의 서식을
그대로 유지한다. v1.02 ground-truth 대조 결과: **셀 스타일(보더 4면·fill·폰트·숫자
형식·정렬) 차이 0건**, 병합셀 42=42, 열너비·행높이 무변, 시트 29개 보존, 표준 데이터
유효성(드롭다운) 13=13 보존, VBA 보존. FAIL 셀은 빨간 fill 적용 후에도 보더 유지.
(한계: openpyxl이 x14 확장형 데이터 유효성은 드롭 — 플랫폼 전 빌더 공통.)

## openpyxl 계약 (중요)

- **source는 `data_only=True`** (Excel 캐시 계산값), **template은 `data_only=False, keep_vba`**
  (수식/VBA/스타일 보존) — 분리 로드(동일 파일이어도 2회).
- **수식 캐시 미스 대응 (리뷰 F1/F2)**: openpyxl이 생성한 산출물은 수식 캐시가 없을 수
  있다. hours(`F7=SUM`)/P-F(`I7=IF`)가 None이면:
  - hours: Total 라벨 **바로 우측 1칸만** 읽고, 비숫자면 **준비+수행+검토 합산** fallback
    (`_extract_hours`). `_value_right`는 인접 라벨/블록 헤더(`■`)에서 정지해 빈 hours 셀
    우측의 'P/F' 라벨을 긁던 wrong-pick을 차단.
  - P/F: 미캐시면 빈값으로 두고 **`incomplete`에 경고** 누적("Excel로 1회 열어 저장 권장")
    — silent 미수행 오분류 방지.

## API

신규 라우터 `backend/routers/swreport.py` (prefix `/api/swreport`, **admin-only**):

| endpoint | 입력 | 출력 |
|----------|------|------|
| `POST /api/swreport/summary/build` | `SwReportBuildRequest` (JSON) | `.xlsm` attachment + `X-SwReport-Summary`/`Warnings`/`Incomplete` 헤더 |
| `POST /api/swreport/summary/preview` | 동일 | 통합 표 행 + 집계 JSON (Excel 미빌드) |

`SwReportBuildRequest` (`schemas.py`, `extra='forbid'`):
- 필수: `project_id`, `release_sw_version`(regex), `test_date`(regex)
- `template_path` (ES95411 양식 xlsm; 비면 config `template_paths.es95411_template` fallback)
- `source_paths` (레벨별 산출물 ≤16; 비면 template 자체를 source로 단일파일 refresh)
- 헤더 메타(선택): `asil_level/phase/product/test_target/compiler/mcu/software_platform_ver/test_engineer/...`

입력 표면: **JSON body 단일** — path 문자열을 `file_resolver`로 read (cloudium worker/local 공통).
`template_path`·`source_paths` 모두 cloudium gate(`middleware._CLOUDIUM_PATH_KEYS`) + Pydantic
(`_no_newline`, maxlen, ≤16) + resolver 화이트리스트 3중 검사.

## Frontend

`frontend-v2/src/components/sections/SwReportSummarySection.jsx` (Detail.jsx `SECTIONS`에 `swreport` 등록).
- preview = `api.post()` (JSON), build = raw `fetch` blob + `authHeaders()` + `res.ok` (X9 준수).
- `source_paths_text`(UI 전용)는 payload에서 strip → 줄단위 배열 변환(extra=forbid 422 회피).

## 제약 (backend/services/CLAUDE.md)

- Cloudium worker **read-only** — 본 빌더는 bytes in → bytes out, 파일 직접 쓰기 없음.
- 시각 강조 RGB는 `design_tokens` 단일출처 (`mark_fail_cell` 등 래퍼 경유).
- ISO 26262: 산출물은 **auto-generated draft** (tool_qualification 승계) — ASIL B/C/D 단독
  evidence 금지, reviewer 검토 필수.
- `backend/services`·`routers`·`schemas`·`main.py` 변경 후 **uvicorn 재시작** 의무.

## 알려진 동작

- v1.02 ES95411의 Summary는 수기로 Tester를 전 행 '주희영'으로 채웠으나, detail 시트
  실제값은 IT401/IT701/ET101='이재원, 유영규'다. 본 빌더는 detail 시트를 충실히
  roll-up하므로 이 **수기 불일치를 드러낸다**(버그 아님 — 의도된 정확성).

## 테스트

- `tests/unit/test_swreport_summary.py` — roll-up·sub병합보존·미수행공란·Fail강조·Total
  계산·**수식 캐시미스 fallback**·preview.
- `tests/unit/test_swreport_router.py` — 422 검증·200 배선·X-User·헤더.
