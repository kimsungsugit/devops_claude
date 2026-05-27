# F6 라운드 — Spec 문서 통합 추출 (즉시 실행 가능 plan)

> **다음 세션 시작 시 이 문서만 보고 바로 코드 작성 시작 가능하도록 작성.**
>
> 59차 후속. F4 (33fbe02/e672453/49a7287) + F5 W4 (0d04f29) 완료 상태에서 시작.

---

## 0. 다음 세션 즉시 시작 절차

```powershell
# 0-1. 작업 디렉토리 + venv
cd D:\Project\devops\Release_claude
& .\.venv\Scripts\Activate.ps1

# 0-2. 최신 commit 확인 (F4-C, F5 W4 commit 포함)
git log --oneline -5
# 기대: 0d04f29(snapshot 5/27) / 49a7287(F4-C) / e672453(F4-B) / 33fbe02(F4-A) / 174056c(58차)

# 0-3. 본 plan 다시 읽기
cat docs/rounds/F6_plan_spec_sources_integration.md

# 0-4. backend / frontend 서버 가동 (선택)
backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 9000 --reload
# 별도 창: cd frontend-v2 && npm run dev

# 0-5. Cloudium worker (라이브 PoC 시)
# dist/excel_rename_gui_v2.exe (10MB, worker.py 빌드) — 1개만 실행
# netstat -ano | findstr ":8765" 로 listen 확인
```

### 첫 행동

T401 SwUTS docx 구조 라이브 분석 — `.codex_tmp/round_60_local_build/inspect_swuts_docx_structure.py` 작성 후 사용자 환경 SwUTS docx로 실행.

---

## 1. Context (왜 F6인가)

### 1-1. 59차 F5 라이브 진단 결과 (HDPDM01 v2.02, 30 env × 1941 TC)

| 누락 카테고리 | 카운트 | root cause | 코드 결함? |
|--------------|-------|-----------|----------|
| expected_result | 142건 (7.3%) | VectorCAST가 expected 정의 안 함 (write-only operations 38개 함수) | ❌ data 부재 |
| actual_result | 23건 (1.2%) | VectorCAST report에 variable row 부재 (stub-only TC) | ❌ data 부재 |
| input_data | 30건 (1.5%) | 같은 패턴 | ❌ data 부재 |

**핵심 증거**: 같은 함수 root (SwUFn_NNNN)에서 일부 TC만 expected 누락 + 일부 보유하는 mixed 케이스 **0건**. 모두 all-missing (38개 함수). **vcast_parser 추출 layer 결함 0건 확정**.

### 1-2. 진정한 audit 누락 원인 = spec source 미활용

회사 양식 (KJPDS02 v1.01 / HDPDM01 v2.02/v3.01) 의 Test Log 시트는 다음 column을 요구하는데, 현재 우리 산출물에는:

| Test Log column | 회사 표준 | 우리 산출물 현재 |
|----------------|----------|--------------|
| TC_ID (`SwUTC_0101_01` / `SwITC_0101_01` 형식) | SwUTS / SwITS docx 정의 | VectorCAST 함수 ID (`SwUFn_0101.001`) — 형식 불일치 |
| Description ("Interface : main -> s_System_I") | SwUTS / SwITS docx | 하드코딩 "AEC, ABV" |
| Precondition | SwUTS / SwITS docx | 빈 cell |
| Test Method (REQ, IFT) | SwUTS / SwITS docx | 하드코딩 |
| Generation Method (AOR, ABV) | SwUTS / SwITS docx | 하드코딩 "AEC, ABV" |
| Coverage v1.01 Traceability col header (SwST_01, SwSTR_01) | SwITS docx | skip + warning (F4-C C4 미구현) |
| Function Calls metric (v1.01 row 6) | HMR or CRR | 빈 cell (F4-C field만 있고 source 없음) |

### 1-3. 의도된 outcome

3개 양식 (KJPDS02 v1.01 + HDPDM01 v2.02 + HDPDM01 v3.01) 모두 audit-grade 산출물 완성:
- Test Log column에 spec docx 데이터 정확 stamp
- F4-C SwITC×SwST matrix skip 해소
- Function Calls metric 정상 stamp
- ISO 26262 evidence_class "auto-generated draft" 정책 동일 유지 (manual review 의무)

---

## 2. 현재 추출 source 매트릭스 (정리)

| Source | 현재 활용 | 활용 안 한 정보 |
|--------|----------|---------------|
| **VectorCAST HTML** | | |
| ⤷ TestCaseDataReport.html (env별) | ✅ TestCaseItem.input_data / expected_result | — |
| ⤷ ExecutionResultReport.html (env별) | ✅ ExecutionRow.actual_result (58차 F1 BeautifulSoup) | — |
| ⤷ AggregateCoverageReport.html (env별) | ✅ FunctionCoverage statement/branch/mcdc | — |
| ⤷ **CRR** (단일 통합 Coverage Report) | ❌ | metricstable 401~630 table — Statement/Branch/MC/DC 함수별 통계 |
| ⤷ **HMR** (Metrics Report) | ❌ | **Function Calls metric** — KJPDS02 v1.01 row 6 직결 |
| ⤷ **RCR** (Requirements Coverage) | ❌ | 요구사항 추적성 |
| ⤷ **SUR** (Summary Report) | ❌ | 통합 요약 |
| **Spec docx** | | |
| ⤷ SwUDS docx (`swuds_docx_path`) | ✅ swut_swuds_parser — function_ids + function_asil_map | description/parameters 미활용 |
| ⤷ **SwUTS docx** (path 미정) | ❌ | **TC_ID + Description + Precondition + Test Method + Generation Method + Requirements 추적** |
| ⤷ **SwITS docx** (path 미정) | ❌ | **SwITC TC_ID + SwST/SwSTR col header + matrix entries** |
| ⤷ **SRS / SDS / UDS / STS** | ❌ | 추적성 chain |
| ⤷ **SUTS / SITS** | ❌ | 시험 결과 spec |
| **C 소스** | | |
| ⤷ c_source_root (Doxygen @asil) | ✅ swut_asil_resolver | — |

---

## 3. F6 작업 분해 (sub-라운드 권장)

| sub-라운드 | 작업 | 예상 시간 | 회귀 |
|----------|------|----------|------|
| **F6-A** | SwUTS docx parser + SUTR Test Log 통합 | ~5~8h | +10 |
| **F6-B** | SwITS docx parser + SITR Test Log + Coverage v1.01 Traceability matrix 해소 (F4-C C4) | ~5~8h | +10 |
| **F6-C** | HMR HTML parser + Function Calls metric (v1.01 row 6) stamp | ~3~5h | +5 |
| **F6-D** | CRR HTML parser + Statement/Branch/MC/DC 분리 metric | ~3~5h | +5 |
| **F6-E** (별도 라운드) | SRS/SDS/UDS/STS 추적성 chain | ~10h+ | +20 |

**권장 순서**: F6-A → F6-B → F6-C → F6-D. F6-A/B가 audit 정확도 직결 + 사용자 우선순위 최고.

---

## 4. F6-A — SwUTS docx parser + SUTR Test Log 통합 (~5~8h)

### 4-1. 사전 사용자 제공 fixture

다음 세션 시작 시 사용자에게 요청해야 할 항목:

1. **SwUTS docx sample 파일 경로** (1~2개):
   - HDPDM01 SwUTS docx (예: `U:/연구소/.../HDPDM01/.../SwUTS_v?.docx`)
   - KJPDS02 SwUTS docx (예: `U:/연구소/.../KJPDS02/.../SwUTS_v?.docx`)
   - Cloudium worker IPC 통해 read 가능
2. **SwUTS docx 양식 가정 검증**:
   - heading 패턴 (SwUTC_0101_01 형식?)
   - table 컬럼 (TC ID / Description / Precondition / Test Method / Generation Method / Requirements 등)

### 4-2. T401 SwUTS docx 구조 라이브 분석 (~30분)

`.codex_tmp/round_60_local_build/inspect_swuts_docx_structure.py` 신규:

```python
"""F6-A T401 — SwUTS docx 구조 라이브 분석.

Cloudium worker로 사용자 환경 SwUTS docx read → python-docx 로 paragraph + table
순회 → heading 패턴 + table 컬럼 구조 파악.
"""
from backend.services.file_resolver import CloudiumFileResolver, set_resolver
from docx import Document
import io

SWUTS_PATHS = [
    # 사용자 제공 필요
    # "U:/연구소/.../HDPDM01/.../SwUTS_v?.docx",
]

# heading: SwUTC_NNNN_NN | SwUFn_NNNN | TC ID 인지
# table: 각 column header 텍스트
# 첫 5개 TC 샘플 출력
```

라이브 실행 후 결과를 plan에 반영 (heading regex / table column 이름 / TC index 매핑).

### 4-3. 신규 모듈 `backend/services/swuts_docx_parser.py`

기존 `swut_swuds_parser.py` (242 lines) 와 같은 패턴으로 작성:

```python
"""SwUTS (Software Unit Test Specification) docx parser (F6-A 라운드).

SwUTS는 단위 시험 spec 문서. 각 TC는 ``SwUTC_NNNN_NN`` 형식 heading + 다음 table에
description / precondition / test_method / generation_method / requirements 정보가
들어있다 (Hyundai/Mobis 양식).

본 파서는 SwUTS docx에서 **TC별 시험 spec 정보**를 추출해서 SUTR Test Log 시트의
TC_ID + Description + Precondition + Test Method + Generation Method 컬럼에 stamp.

## 가정 (Hyundai/Mobis 양식 — KJPDS02 v1.01 양식 기준)

- Heading 단락: ``SwUTC_NNNN_NN`` 형식 (예: ``SwUTC_0101_01``)
- 같은 TC의 spec table은 그 다음에 오는 table에 들어있다 (label/value 페어)
- table label: 'Description' / 'Precondition' / 'Test Method' / 'Generation Method' /
  'Requirements' / 'Function ID' (또는 한글 변종)

## 한계 / Fail-safe

- python-docx ImportError → ParserResult.ok=False
- DOCX_MAX_BYTES = 64MB (zip bomb 방지)
- 양식 다양성: 라벨 미발견 → parse_warnings 누적, 해당 field 빈 string
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

try:
    from docx import Document  # type: ignore
    from docx.oxml.table import CT_Tbl  # type: ignore
    from docx.oxml.text.paragraph import CT_P  # type: ignore
    from docx.table import Table  # type: ignore
    from docx.text.paragraph import Paragraph  # type: ignore
    _HAS_DOCX = True
except ImportError:
    Document = None  # type: ignore[assignment]
    _HAS_DOCX = False


# SwUTC_NNNN_NN — KJPDS02 v1.01 양식 / SwUTC_NNNN — HDPDM01 변형 가능
_SWUTC_RE = re.compile(r"^SwUTC_(\d+)(?:_(\d+))?\b")
DOCX_MAX_BYTES = 64 * 1024 * 1024  # 64MB


@dataclass
class SwUTSEntry:
    """SwUTS의 단위 TC 항목."""
    tc_id: str                  # 'SwUTC_0101_01'
    heading_text: str           # 원본 heading (예: 'SwUTC_0101_01 — main 호출')
    description: str = ""       # 'Interface : main -> s_System_I'
    precondition: str = ""
    test_method: str = ""       # 'REQ, IFT' (Requirements + Interface Test)
    generation_method: str = ""  # 'AOR, ABV' (Boundary Value + ...)
    function_id: str = ""       # 'SwUFn_0101' — VectorCAST 매핑용
    requirements: list[str] = field(default_factory=list)  # 추적성 ID
    raw_spec: dict[str, str] = field(default_factory=dict)  # 향후 확장용 raw label/value


@dataclass
class SwUTSParseResult:
    """SwUTS docx 파싱 결과."""
    ok: bool
    entries: list[SwUTSEntry] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)

    @property
    def tc_ids(self) -> set[str]:
        return {e.tc_id for e in self.entries}

    @property
    def by_tc_id(self) -> dict[str, SwUTSEntry]:
        return {e.tc_id: e for e in self.entries}

    @property
    def by_function_id(self) -> dict[str, list[SwUTSEntry]]:
        """function_id (SwUFn_NNNN) → SwUTC_* list. 1:N 매핑."""
        result: dict[str, list[SwUTSEntry]] = {}
        for e in self.entries:
            if e.function_id:
                result.setdefault(e.function_id, []).append(e)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tc_count": len(self.entries),
            "entries": [
                {"tc_id": e.tc_id, "function_id": e.function_id,
                 "description": e.description[:200]}
                for e in self.entries[:50]  # 상위 50개만 (logs용)
            ],
            "parse_warnings": self.parse_warnings,
            "tool_qualification": {
                "evidence_class": "auto-generated draft",
                "asil_a_usage": "reviewer 검토 후 evidence 사용 가능",
                "asil_b_c_d_usage": "단독 evidence 사용 금지 — manual review 의무",
                "format_assumption": "Hyundai/Mobis 양식 (SwUTC_NNNN_NN heading)",
            },
        }


# label 후보 (대소문자 무시 매칭) — 양식 변종 커버
_LABEL_CANDIDATES = {
    "description": ("description", "기능 설명", "설명", "test case description"),
    "precondition": ("precondition", "전제 조건", "전제조건", "pre-condition"),
    "test_method": ("test method", "test type", "테스트 방법", "시험 방법"),
    "generation_method": ("generation method", "testcase generation method",
                          "tc generation method", "테스트케이스 생성 방법"),
    "function_id": ("function id", "function", "함수 id", "함수"),
    "requirements": ("requirements", "requirement id", "요구사항", "추적성"),
}


def _iter_blocks(doc):
    """문서를 paragraph + table 순서대로 yield (SwUDS와 동일 패턴)."""
    body = doc._body._element  # type: ignore[attr-defined]
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield ("p", Paragraph(child, doc))
        elif isinstance(child, CT_Tbl):
            yield ("tbl", Table(child, doc))


def _extract_label_value_from_table(tbl, label_keys) -> str:
    """table에서 label 매칭 (대소문자 무시) → 옆 셀 텍스트 반환. 미발견 시 ''."""
    try:
        for row in tbl.rows[:15]:  # 첫 15 row 스캔
            cells = [c.text.strip() for c in row.cells]
            for i, c in enumerate(cells):
                c_lower = c.lower()
                for label in label_keys:
                    if c_lower == label.lower():
                        if i + 1 < len(cells):
                            return cells[i + 1][:500]
    except Exception:
        pass
    return ""


def parse_swuts_docx(
    docx_bytes: bytes, *, parse_warnings: list[str] | None = None,
) -> SwUTSParseResult:
    """SwUTS docx → SwUTSParseResult.

    파싱 흐름:
        1. heading paragraph 검색 — SwUTC_NNNN_NN 패턴
        2. 다음 table 추출 — label/value 셀에서 description/precondition/.../function_id
        3. 다음 heading 만날 때까지 entry 채움

    Args:
        docx_bytes: SwUTS docx file 내용 (resolver.read_bytes)
        parse_warnings: 누락 사유 누적 (caller가 전달)

    Returns:
        SwUTSParseResult — ok=True면 entries 채움. False면 parse_warnings에 사유.
    """
    warnings = parse_warnings if parse_warnings is not None else []

    if not _HAS_DOCX:
        return SwUTSParseResult(
            ok=False, parse_warnings=warnings + [
                "python-docx 미설치 — SwUTS docx 파싱 불가",
            ],
        )
    if len(docx_bytes) > DOCX_MAX_BYTES:
        return SwUTSParseResult(
            ok=False, parse_warnings=warnings + [
                f"SwUTS docx 크기 {len(docx_bytes):,} > 한도 {DOCX_MAX_BYTES:,}",
            ],
        )

    try:
        doc = Document(io.BytesIO(docx_bytes))
    except Exception as e:
        return SwUTSParseResult(
            ok=False, parse_warnings=warnings + [
                f"docx open 실패 — {type(e).__name__}: {e}",
            ],
        )

    entries: list[SwUTSEntry] = []
    current_entry: SwUTSEntry | None = None
    pending_tables_for_current: list = []

    for kind, item in _iter_blocks(doc):
        if kind == "p":
            txt = item.text.strip()
            m = _SWUTC_RE.match(txt)
            if m:
                # 이전 entry의 pending tables 처리 — 라벨/값 추출
                if current_entry is not None and pending_tables_for_current:
                    for tbl in pending_tables_for_current:
                        _populate_entry_from_table(current_entry, tbl)
                    entries.append(current_entry)
                    pending_tables_for_current = []
                # 신규 entry 시작
                tc_id = m.group(0)
                current_entry = SwUTSEntry(tc_id=tc_id, heading_text=txt)
        elif kind == "tbl":
            if current_entry is not None:
                pending_tables_for_current.append(item)
    # 마지막 entry flush
    if current_entry is not None:
        for tbl in pending_tables_for_current:
            _populate_entry_from_table(current_entry, tbl)
        entries.append(current_entry)

    if not entries:
        warnings.append(
            "SwUTS docx에서 SwUTC_NNNN_NN heading 0건 — Hyundai/Mobis 양식 "
            "아니거나 다른 prefix 사용 추정"
        )
        return SwUTSParseResult(ok=False, parse_warnings=warnings)

    return SwUTSParseResult(ok=True, entries=entries, parse_warnings=warnings)


def _populate_entry_from_table(entry: SwUTSEntry, tbl) -> None:
    """table 첫 5~15 row label/value 페어로 entry field 채움."""
    for field_name, labels in _LABEL_CANDIDATES.items():
        val = _extract_label_value_from_table(tbl, labels)
        if val and not getattr(entry, field_name, None):
            if field_name == "requirements":
                # 콤마 split, strip
                entry.requirements = [
                    r.strip() for r in val.split(",") if r.strip()
                ]
            else:
                setattr(entry, field_name, val)
            entry.raw_spec[field_name] = val
```

### 4-4. swut_meta_resolver.py 확장 (~50 lines)

`backend/services/swut_meta_resolver.py` 에 신규 함수 추가:

```python
def resolve_swuts_test_specs(req: Any, project_id: str) -> dict[str, Any] | None:
    """F6-A 신규 — req.swuts_docx_path 있으면 SwUTS docx → SwUTSParseResult.by_tc_id

    Returns: by_tc_id dict ({tc_id: SwUTSEntry}) 또는 None (path 미제공/실패).

    호출 패턴 (swut_sutr_aggregator):
        swuts_map = resolve_swuts_test_specs(req, project_id) or {}
        # _write_test_log에서 swuts_map[tc_id]로 description/precondition 등 lookup
    """
    swuts_path = resolve_swuts_path(req, project_id)
    if not swuts_path:
        return None
    from backend.services.file_resolver import get_resolver
    from backend.services.swuts_docx_parser import parse_swuts_docx
    try:
        resolver = get_resolver()
        docx_bytes = resolver.read_bytes(swuts_path)
        parse_warnings: list[str] = []
        result = parse_swuts_docx(docx_bytes, parse_warnings=parse_warnings)
        if not result.ok:
            _logger.warning("SwUTS parse failed: %s", parse_warnings)
            return None
        return result.by_tc_id
    except (FileNotFoundError, PermissionError) as e:
        _logger.warning("SwUTS docx read failed: %s", e)
        return None


def resolve_swuts_path(req: Any, project_id: str) -> str:
    """F6-A — req.swuts_docx_path 우선 → swut_meta.json fallback.
    
    swut_meta.json 신규 field: 'swuts_docx_path' (project_id 별 매핑)
    """
    explicit = getattr(req, "swuts_docx_path", "") or ""
    if explicit:
        return explicit
    cfg = _load_swut_meta_cached()
    by_project = cfg.get("by_project", {}).get(project_id, {})
    return (by_project.get("swuts_docx_path") or
            cfg.get("swuts_docx_path") or "").strip()
```

### 4-5. backend/schemas.py 변경 (정확 위치)

**SwUTBuildRequest** (line 662 부근): swuds_docx_path 다음에 추가

```python
# 16차: SwUDS docx (옵션) — 제공 시 2.Consistency에 SwUDS↔SwUTS 매핑 row 추가
swuds_docx_path: str = Field("", max_length=500)
# F6-A 신규: SwUTS docx (옵션) — 제공 시 SUTR Test Log의 TC_ID/Description/
# Precondition/Test Method/Generation Method spec 데이터 stamp.
swuts_docx_path: str = Field("", max_length=500)
```

**`_no_newline` validator (line 677~679)** field 목록에 `"swuts_docx_path"` 추가.

**SwITBuildRequest (line ~750)** 도 동일하게 `swits_docx_path` 추가 (F6-B에서 사용).

### 4-6. backend/services/swut_sutr_aggregator.py `_write_test_log` 변경

**변경 위치**: line 425 (helper 호출) 직후 + line 437~440 (B/C/D fill) 변경.

기존 (line 437~440):
```python
safe_write(ws, r, col, tc_name)             # B: TC ID (= SwUFn_0101.001)
safe_write(ws, r, col + 1, component_name)  # C: Title (component_name)
safe_write(ws, r, col + 2, "AEC, ABV")      # D: Method (하드코딩)
```

F6-A 변경:
```python
# F6-A — SwUTS docx 매핑 lookup. function_id 또는 tc_index 기준.
# swuts_map은 build_sutr → _write_test_log 호출 시 agg["swuts_map"]에서 가져옴.
swuts_map = function_asil_map  # 임시 — 실제는 별도 dict
# 위 인자는 _write_test_log signature 확장 필요 — swuts_map 추가
swuts_entry = (swuts_map or {}).get(tc_name) if swuts_map else None
if swuts_entry is None:
    # fallback: function_id 기준 매칭 (SwUFn_0101.001 → SwUFn_0101 → SwUTC_*)
    fn_id_match = re.match(r"(SwUFn_\d+)", tc_name)
    if fn_id_match and swuts_map:
        candidates = swuts_map.get(fn_id_match.group(1), [])
        # 동일 function의 TC index 매칭 (.001 → _01 등)
        tc_index_match = re.search(r"\.(\d+)$", tc_name)
        if tc_index_match and candidates:
            idx = int(tc_index_match.group(1))
            # SwUTC_NNNN_idx 매칭 시도
            for c in candidates:
                if c.tc_id.endswith(f"_{idx:02d}"):
                    swuts_entry = c
                    break
            else:
                swuts_entry = candidates[0] if candidates else None

# B/C/D fill — SwUTS spec 있으면 spec 데이터 우선, 없으면 VectorCAST fallback
display_tc_id = swuts_entry.tc_id if swuts_entry else tc_name
display_method = swuts_entry.test_method if swuts_entry else "AEC, ABV"
display_method2 = swuts_entry.generation_method if swuts_entry else "AEC, ABV"
display_description = swuts_entry.description if swuts_entry else component_name
display_precondition = swuts_entry.precondition if swuts_entry else ""

safe_write(ws, r, col, display_tc_id)
safe_write(ws, r, col + 1, display_description or component_name)
safe_write(ws, r, col + 2, display_method)
# Precondition은 col + 3 (E)에 stamp (회사 v1.01 양식 col I=9 = Precondition)
# v2.02 양식은 Precondition col이 다를 수 있음 — layout-aware
precondition_col = getattr(layout, "test_log_precondition_col", None) if layout else None
if precondition_col and display_precondition:
    safe_write(ws, r, precondition_col, display_precondition)
```

또한 `_write_test_log` signature 확장:

```python
def _write_test_log(
    ws,
    session: SwUTSession,
    function_asil_map: dict[str, str] | None = None,
    out_warnings: list[str] | None = None,
    *,
    layout: Any = None,
    swuts_map: dict[str, SwUTSEntry] | None = None,  # F6-A 신규
) -> int:
```

`build_sutr` 호출처 (line ~925)에서 `swuts_map=resolve_swuts_test_specs(...)` 전달.

### 4-7. SwitLayout.test_log_precondition_col 추가 (`backend/services/excel_layout_resolver.py`)

line 124 (test_log_input_col) 부근에 추가:

```python
# F6-A — Precondition column 위치 (v1.01 양식 col I=9, v2.02/v3.01 없음)
test_log_precondition_col: Optional[int] = None
```

`_inspect_internal` (line ~516) 에서 `_scan_test_log_columns` 결과에 `precondition_col` 추가:

```python
# F6-A — Precondition col 자동 감지
elif result["precondition_col"] is None and s in (
    "precondition", "pre-condition", "전제 조건",
):
    result["precondition_col"] = c
```

### 4-8. Frontend `frontend-v2/src/components/sections/SwUTBuildSection.jsx`

**line 29** form initialState 에 추가:
```js
swuds_docx_path: '',
swuts_docx_path: '',  // F6-A 신규
```

**line 389** swuds_docx_path FormField 다음에 SwUTS docx FormField 추가 (동일 패턴):

```jsx
<FormField
  name="swuts_docx_path"
  label="SwUTS docx (옵션, F6-A)"
  value={form.swuts_docx_path}
  onChange={v => setField('swuts_docx_path', v)}
  placeholder="비우면 config/swut_meta.json의 swuts_docx_path 자동 사용"
  hint="제공 시 SUTR Test Log의 TC_ID/Description/Precondition/Test Method spec 데이터 stamp"
  onBrowse={() => openPicker('swuts_docx_path', '*.docx', 'SwUTS docx 선택')}
/>
```

(line 402 `openPicker` 호출 패턴 그대로 차용)

### 4-9. config/swut_meta.json 확장

```json
{
  "by_project": {
    "HDPDM01": {
      "swuds_docx_path": "U:/...SwUDS_v?.docx",
      "swuts_docx_path": "U:/...SwUTS_v?.docx",
      "c_source_root": "..."
    },
    "KJPDS02": {
      "swuts_docx_path": "U:/...KJPDS02 SwUTS_v?.docx"
    }
  },
  "swuts_docx_path": ""  # 전역 fallback (선택)
}
```

기존 lru_cache + mtime invalidate 그대로 작동.

### 4-10. F6-A 회귀 (+10)

**`tests/unit/test_swuts_docx_parser.py` 신규 (+5)**:

```python
class TestSwutsDocxParser:
    def test_parses_swutc_heading_basic(self):
        """heading 'SwUTC_0101_01' + 다음 table description → entry 생성."""
    def test_handles_multiple_tcs_with_different_function_ids(self):
        """3 TC heading + 3 table → 3 entries, function_id 각각 보유."""
    def test_label_value_pairs_extracted_from_table(self):
        """description/precondition/test_method 라벨 옆 셀 추출."""
    def test_empty_docx_returns_ok_false_with_warning(self):
        """heading 0건 → ok=False + parse_warnings."""
    def test_docx_max_bytes_rejected(self):
        """64MB+ docx → ok=False + 'docx 크기' warning."""
```

**`tests/unit/test_swut_aggregators.py` (+3)**:
```python
class TestSutrTestLogSwutsIntegrationF6A:
    def test_swuts_entry_overrides_tc_id_to_swutc_format(self):
        """swuts_map 제공 시 col B에 SwUTC_0101_01 stamp (SwUFn_ 대체)."""
    def test_swuts_description_stamped_at_col_c(self):
        """SwUTS.description → col C stamp (component_name 대체)."""
    def test_layout_precondition_col_writes_swuts_precondition(self):
        """layout.test_log_precondition_col + swuts.precondition → 정확 col stamp."""
```

**`tests/unit/test_excel_layout_resolver.py` (+2)**:
```python
class TestScanPreconditionColF6A:
    def test_scan_precondition_col_v101_kjpds02(self):
        """'Precondition' 헤더 col 자동 감지."""
    def test_precondition_col_none_when_label_missing(self):
        """라벨 미존재 → None."""
```

### 4-11. F6-A backward-compat 정책

- `swuts_docx_path` 미제공 (현재 모든 호출) → `swuts_map = None` → 기존 동작 (B/C/D 하드코딩 유지)
- `swuts_docx_path` 제공이라도 docx 파싱 실패 → graceful skip + parse_warnings emit
- `test_log_precondition_col` None (v2.02/v3.01 양식 default) → precondition stamp skip
- 모든 기존 v2.02/v3.01 회귀 무영향

---

## 5. F6-B — SwITS docx parser + Coverage v1.01 Traceability matrix 해소 (~5~8h)

### 5-1. 신규 모듈 `backend/services/swits_docx_parser.py`

F6-A SwUTS 패턴과 동일. 차이:

- heading: `SwITC_NNNN_NN` 형식 (Integration TC)
- 추가 field: `swst_traceability` — `[(SwST_NN, "O" or "X"), ...]` 추적성 entry
- `swst_col_headers` set — 모든 SwITS에 등장한 SwST/SwSTR ID

```python
@dataclass
class SwITSEntry:
    tc_id: str            # 'SwITC_0101_01'
    heading_text: str
    description: str = ""
    precondition: str = ""
    test_method: str = ""
    generation_method: str = ""
    function_id: str = ""
    requirements: list[str] = field(default_factory=list)
    # F6-B 신규 — SwITC × SwST 추적성 entry
    swst_traceability: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class SwITSParseResult:
    ok: bool
    entries: list[SwITSEntry] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)
    swst_col_headers: list[str] = field(default_factory=list)  # F6-B 신규

    @property
    def matrix_entries(self) -> list[tuple[str, str, str]]:
        """모든 entries의 swst_traceability flatten."""
        result = []
        for e in self.entries:
            for (swst_id, marker) in e.swst_traceability:
                result.append((e.tc_id, swst_id, marker))
        return result
```

### 5-2. F4-C SwITC×SwST matrix 활성화 (정확한 변경 위치)

**파일**: `backend/services/swut_coverage_aggregator.py`
**위치**: line 828~847 (F4-C에서 skip path 작성)

기존 (F4-C):
```python
if matrix_kind == "switc_x_swst":
    if out_warnings is not None:
        out_warnings.append(
            "1.Traceability matrix kind 'switc_x_swst' (KJPDS02 v1.01 양식) — "
            "SwITS docx parser 미구현으로 매트릭스 stamp skip. ..."
        )
    return 0
```

F6-B 변경:
```python
if matrix_kind == "switc_x_swst":
    # F6-B — SwITS docx 제공 시 SwITC × SwST matrix stamp.
    swits_result = agg.get("swits_result")  # SwITSParseResult 또는 None
    if swits_result is None or not swits_result.ok:
        if out_warnings is not None:
            out_warnings.append(
                "1.Traceability matrix 'switc_x_swst' — SwITS docx 미제공 또는 "
                "파싱 실패. SwITBuildRequest.swits_docx_path 제공 필요."
            )
        return 0
    return _write_switc_x_swst_matrix(ws, swits_result, out_warnings=out_warnings)
```

신규 함수 `_write_switc_x_swst_matrix`:
```python
def _write_switc_x_swst_matrix(ws, swits_result, *, out_warnings=None) -> int:
    """F6-B — KJPDS02 v1.01 양식 Traceability matrix stamp.
    
    Layout (KJPDS02 reference):
        row 11: col1='[N by M] Matrix' col3+ swst_col_headers (SwST_01, ...)
        row 12: col1='SwITC' col3+ COUNTIF formulas (= COUNTIF range)
        row 13+: col1=switc_id col3+ 'O' marker
    """
    # 1. col 3+ 에 swst_col_headers stamp
    for i, swst in enumerate(swits_result.swst_col_headers):
        safe_write(ws, 11, 3 + i, swst)
    # 2. row 13+ 에 SwITC ID + matrix entries stamp
    swst_to_col = {swst: 3 + i for i, swst in enumerate(swits_result.swst_col_headers)}
    written = 0
    for i, entry in enumerate(swits_result.entries):
        r = 13 + i
        safe_write(ws, r, 1, entry.tc_id)
        for (swst_id, marker) in entry.swst_traceability:
            c = swst_to_col.get(swst_id)
            if c:
                safe_write(ws, r, c, marker)
                written += 1
    return written
```

### 5-3. F6-B 회귀 (+10)

- `test_swits_docx_parser.py` 신규 (+5): heading / swst_col_headers / matrix_entries / ok=False graceful
- `test_swit_coverage_aggregator.py` (+3): switc_x_swst stamp 정상 / col header row 11 / matrix entries row 13+
- `test_swit_sitr_aggregator.py` (+2): SwITS docx 제공 시 SITR Test Log description stamp

---

## 6. F6-C — HMR HTML parser + Function Calls metric (~3~5h)

### 6-1. HMR 구조 (Jenkins_PDSM_IT_metrics_report 패턴 분석 필요)

`.codex_tmp/round_60_local_build/inspect_hmr_format.py` 신규 — HMR HTML의 metrics table 구조 + Function Calls 추출 패턴 식별.

### 6-2. 신규 모듈 `backend/services/vcast_hmr_parser.py`

```python
def parse_hmr_html(html_bytes: bytes) -> dict[str, FunctionCallMetric]:
    """HMR → {function_id: FunctionCallMetric}.
    
    FunctionCallMetric: total_calls, covered_calls, exception_calls, coverage_pct
    """
```

### 6-3. swut_coverage_aggregator.py 통합

`_write_coverage_sheet` (F4-C에서 layout.coverage_metric_kind="function_and_calls" + fc.function_calls_coverage 있으면 col 10/11/12 stamp 추가했음). F6-C는 fc.function_calls_coverage를 채우는 source 추가:

```python
# build_coverage_report에서:
if req.hmr_path:
    hmr_metrics = parse_hmr_html(read_bytes(req.hmr_path))
    for fc in function_rows:
        m = hmr_metrics.get(fc.unit_id) or hmr_metrics.get(fc.name)
        if m:
            fc.function_calls_coverage = CoverageStats(
                covered=m.covered_calls, total=m.total_calls,
                coverage_pct=m.coverage_pct,
            )
```

### 6-4. 회귀 (+5)

- `test_vcast_hmr_parser.py` 신규 (+3): metric extraction / graceful / format 다양성
- `test_swut_aggregators.py` (+2): hmr 통합 시 col 10/11/12 stamp 검증

---

## 7. F6-D — CRR HTML parser + Statement/Branch/MC/DC 분리 metric (~3~5h)

CRR `metricstable` 401~630 table parsing. AggregateCoverage와 중복 가능성 — 우선 F6-A/B/C 후 필요 시 진행.

### 7-1. CRR 구조 (.codex_tmp/round_59_local_build/inspect_crr_format.py 참고)

- HDPDM01 CRR: 2.25MB, 401 metricstable, 754 TC mention
- KJPDS02 CRR: 4.18MB, 630 metricstable, 1348 TC mention
- `<h3>` 0건 — 우리 h3/h4 anchor 패턴 안 맞음
- metricstable parsing logic 신규 작성 필요

### 7-2. 회귀 (+5)

- `test_vcast_crr_parser.py` 신규 (+5)

---

## 8. F6-E (별도 라운드) — SRS/SDS/UDS/STS 추적성 chain

audit-grade 산출물의 최종 단계. 산출물 단독으로 추적성 매트릭스 검토 가능.

별도 라운드로 분리 — F6-A/B/C/D 완료 후 진행.

---

## 9. F4-C SwITC×SwST matrix 활성화 정확 위치 (F6-B 의존)

`backend/services/swut_coverage_aggregator.py` line 828~847에 F4-C가 작성한 skip path:

```python
matrix_kind = (
    getattr(layout, "traceability_matrix_kind", "swufn_x_env") if layout is not None
    else "swufn_x_env"
)
if matrix_kind == "switc_x_swst":
    if out_warnings is not None:
        out_warnings.append(
            "1.Traceability matrix kind 'switc_x_swst' (KJPDS02 v1.01 양식) — "
            "SwITS docx parser 미구현으로 매트릭스 stamp skip. ..."
        )
    return 0
```

F6-B에서 이 skip path를 `_write_switc_x_swst_matrix` 호출로 교체. SwITSParseResult가 agg dict에 들어가야 함 — `build_coverage_report` (line 904 부근)에서 `agg["swits_result"] = resolve_swits_test_specs(req, project_id)`.

---

## 10. ISO 26262 audit evidence 영향

| 항목 | F5 이전 | F6 완료 |
|------|---------|---------|
| evidence_class | "auto-generated draft" | 동일 (정책 변경 없음) |
| asil_a_usage | "reviewer 검토 후 evidence 사용 가능" | 동일 |
| asil_b_c_d_usage | "단독 evidence 사용 금지 — manual review 의무" | 동일 |
| audit reviewer 부담 | 산출물 + spec docx 별도 cross-check 의무 | spec 정보 산출물에 통합 → 단독 검토 가능 |
| 진정한 추적성 (SRS→SDS→SwUDS→SwUTS→SwUTR) | partial (SwUDS만) | full (SwUTS/SwITS까지) |

---

## 11. Cloudium worker 사전 조건 (모든 F6 라이브 PoC)

- `dist/excel_rename_gui_v2.exe` (10MB, worker.py PyInstaller 빌드) — **1개만 실행**
- `dist_real/excel_rename_gui_v2.exe` (75MB)는 dummy.py 빌드 — listen 안 됨
- port 8765 LISTENING 확인: `netstat -ano | findstr ":8765"`
- 사용자가 직접 더블클릭 또는 `! D:\Project\devops\Release_claude\dist\excel_rename_gui_v2.exe`

---

## 12. 회귀 실행 + 라이브 PoC 명령어

### 회귀
```powershell
& D:\Project\devops\Release_claude\.venv\Scripts\Activate.ps1

# F6-A
python -m pytest tests/unit/test_swuts_docx_parser.py tests/unit/test_swut_aggregators.py tests/unit/test_excel_layout_resolver.py -v

# F6-B
python -m pytest tests/unit/test_swits_docx_parser.py tests/unit/test_swit_coverage_aggregator.py tests/unit/test_swit_sitr_aggregator.py -v

# F6-C
python -m pytest tests/unit/test_vcast_hmr_parser.py "tests/unit/test_swut_aggregators.py::TestCoverageMetricKindF4C" -v

# 전체 통합 (target: 220~225 passed, 2 skipped)
python -m pytest tests/unit/test_swut_aggregators.py tests/unit/test_swit_sitr_aggregator.py tests/unit/test_swit_coverage_aggregator.py tests/unit/test_swut_input_adapter.py tests/unit/test_excel_layout_resolver.py tests/unit/test_vcast_parser.py tests/unit/test_swuts_docx_parser.py tests/unit/test_swits_docx_parser.py --tb=line -q
```

### 라이브 PoC
```powershell
# F6-A 완료 후
python .codex_tmp/round_60_local_build/direct_build_kjpds02_with_swuts.py

# F6-B 완료 후
python .codex_tmp/round_60_local_build/direct_build_kjpds02_with_swits.py
```

기대 결과:

| 항목 | F5 후 | F6-A 후 | F6-B 후 |
|------|-------|---------|---------|
| Test Log col B (TC ID) | SwUFn_0101.001 | **SwUTC_0101_01** | 동일 + SITR |
| Test Log col C (Description) | "AEC, ABV" (하드코딩) | **"Interface : main -> s_System_I"** | 동일 + SITR |
| Test Log Precondition | 빈 cell | **SwUTS.precondition** | 동일 + SITR |
| Coverage v1.01 Traceability | skip + warning | 동일 (변경 없음) | **SwITC × SwST matrix 정상 stamp** |
| Function Calls metric (v1.01 row 6) | 빈 cell | 동일 | 동일 (F6-C 영향) |

---

## 13. 비-목표 (F6 외 라운드)

- **F6-E (SRS/SDS/UDS/STS docx parser)** — 별도 라운드 (~10h+, 추적성 chain 완성)
- **SUTS/SITS docx** — 시험 결과 spec, 우선순위 낮음
- **W5 vcast_parser parse_execution_result root cause fix** — uds_pipeline / vcast_excel_generator caller 영향 분석 필요. 별도 라운드 (~5h)
- **Frontend UI에서 양식 자동 detect 안내 표시** — F4-C 양식 detect 결과를 frontend에 표시
- **KJPDS02 v1.01 Coverage 1.Test Summary 4 breakdown** (추적성/정합성/Function/FunctionCalls coverage 분리) — 표시 형식 변경

---

## 14. 59차 commit chain (참고)

```
0d04f29  chore(auto): F5 W4 parse_warnings emit (snapshot 2026-05-27)
49a7287  feat(swut/swit): 59차 F4-C — KJPDS02 v1.01 양식 시트 구성 분기 (3/3)
e672453  feat(swut/swit): 59차 F4-B — vcast HTML step iteration 추출 인프라 (2/3)
33fbe02  feat(swut/swit): 59차 F4-A — Test Log stamp generic화 (1/3)
174056c  feat(swut/swit): 58차 — F1/F2/F3 통합 fix
```

origin/main 보다 3 commits ahead (33fbe02 / e672453 / 49a7287). push는 사용자 의사 결정.

---

## 15. 사용자 제공 필요 항목 (F6 시작 전)

1. **SwUTS docx sample path** (라이브 검증 + fixture 작성용):
   - HDPDM01 SwUTS docx 1~2개
   - KJPDS02 SwUTS docx 1개 (가능 시)
2. **SwITS docx sample path** (F6-B):
   - HDPDM01 SwITS docx
   - KJPDS02 SwITS docx (Coverage v1.01 SwITC×SwST matrix 검증)
3. **HMR HTML sample path** (F6-C):
   - 이미 `report/Jenkins_PDSM_IT_metrics_report.html`, `Jenkins_PDSM_UT_metrics_report.html` 보유
4. **양식 매핑 확인** (F6-A T401 결과 기반):
   - heading 패턴 (SwUTC_NNNN_NN vs SwUTC_NNNN 변형)
   - table column 정확한 라벨 (영문/한글)
   - Test Method 값 매핑 (REQ/IFT vs AOR/ABV vs AEC/ABV)

---

## 16. 작업 추적 (task ID)

| Sub | task ID | 내용 |
|-----|---------|------|
| F6-A | T401 | SwUTS docx 구조 라이브 분석 (사용자 환경) |
| F6-A | T402 | swuts_docx_parser.py 신규 + dataclass 정의 |
| F6-A | T403 | parse_swuts_docx 함수 + label/value 추출 |
| F6-A | T404 | swut_meta_resolver.resolve_swuts_test_specs 신규 |
| F6-A | T405 | schemas.py SwUTBuildRequest.swuts_docx_path field 추가 |
| F6-A | T406 | swut_sutr_aggregator._write_test_log signature + swuts_map 통합 |
| F6-A | T407 | excel_layout_resolver SwitLayout.test_log_precondition_col + scan |
| F6-A | T408 | SwUTBuildSection.jsx swuts_docx_path FormField |
| F6-A | T409 | F6-A 회귀 +10 |
| F6-A | T410 | F6-A 통합 회귀 + 라이브 PoC + commit |
| F6-B | T411 | SwITS docx 구조 라이브 분석 |
| F6-B | T412 | swits_docx_parser.py 신규 + swst_traceability dataclass |
| F6-B | T413 | parse_swits_docx 함수 + matrix entry 추출 |
| F6-B | T414 | swut_coverage_aggregator._write_switc_x_swst_matrix 신규 (F4-C skip 해소) |
| F6-B | T415 | schemas.py SwITBuildRequest.swits_docx_path field |
| F6-B | T416 | SwITBuildSection.jsx swits_docx_path FormField |
| F6-B | T417 | F6-B 회귀 +10 |
| F6-B | T418 | F6-B 통합 회귀 + 라이브 PoC + commit |
| F6-C | T419 | HMR HTML 구조 라이브 분석 |
| F6-C | T420 | vcast_hmr_parser.py 신규 |
| F6-C | T421 | swut_coverage_aggregator HMR 통합 — fc.function_calls_coverage 채움 |
| F6-C | T422 | F6-C 회귀 +5 |
| F6-C | T423 | F6-C 통합 + commit |
| F6-D | T424 | CRR 구조 라이브 분석 |
| F6-D | T425 | vcast_crr_parser.py 신규 |
| F6-D | T426 | F6-D 회귀 +5 |
| F6-D | T427 | F6-D 통합 + commit |

---

## 17. 위험 / 완화

| Risk | 완화 |
|------|------|
| R1. SwUTS docx 양식 회사별 차이 (KJPDS02 vs HDPDM01) | T401에서 라이브 fixture 분석 후 plan 보강. 양식별 fixture 회귀로 검증 |
| R2. TC_ID 매핑 실패 (SwUTC_0101_01 vs SwUFn_0101.001) | function_id 또는 TC index regex 매칭 + fallback chain (직접 매칭 → function_id → 미매칭 시 VectorCAST ID 그대로 + warning) |
| R3. python-docx 큰 docx (50MB+) 처리 | DOCX_MAX_BYTES=64MB + lazy block iteration (이미 swut_swuds_parser 패턴) |
| R4. F4-A 변수명 헤더 row stamp와 충돌 | layout.test_log_variable_header_row가 우선 — Description stamp는 별도 col |
| R5. SwITC×SwST matrix 큰 규모 (KJPDS02 47×108) | 메모리 영향 없음 (단순 cell stamp ~5000건) |
| R6. SwUTS path 미제공 backward-compat | swuts_map=None → 기존 동작 100% 유지. 모든 회귀 무영향 |
| R7. ISO 26262 audit reviewer가 신규 source 인지 못 함 | parse_warnings에 SwUTS 사용 명시 emit + tool_qualification.format_assumption 명시 |
| R8. raw_spec field 큰 dict (메모리) | 첫 500 char truncate + 상위 50 entries만 to_dict 출력 (audit reviewer 시인성 균형) |

---

## 18. 본 plan을 따라야 하는 이유 (다음 세션 첫 행동 안내)

1. **`docs/rounds/F6_plan_spec_sources_integration.md` 읽기** (본 문서)
2. F6-A 진행 결정 시:
   - 사용자에게 **SwUTS docx sample path 1~2개 요청**
   - T401 inspect_swuts_docx_structure.py 작성 + 실행
   - 라이브 결과로 heading 패턴 / table column 확정
   - swuts_docx_parser.py 작성 시작 (T402~T409)
3. F6-A commit 후 F6-B 진행 결정 (사용자 의사 확인)
4. 모든 라운드 backward-compat 보장 — 기존 swuds_docx_path / 양식 v2.02/v3.01 무영향

---

## 19. 참고 fixture 위치

- `.codex_tmp/round_59_local_build/inspect_extraction_accuracy.py` — 추출 정확도 라이브 측정
- `.codex_tmp/round_59_local_build/inspect_expected_missing_pattern.py` — mixed 함수 검증
- `.codex_tmp/round_59_local_build/inspect_missing_actual_root_cause.py` — variable row 부재 확인
- `.codex_tmp/round_59_local_build/inspect_report_folder.py` — report/ 다른 프로젝트 검증
- `.codex_tmp/round_59_local_build/inspect_crr_format.py` — CRR metricstable 구조 (F6-D 참고)
- `.codex_tmp/round_60_local_build/inspect_swuts_docx_structure.py` — **F6-A T401 신규 (다음 세션에서 작성)**

---

## 20. 끝맺음 + 즉시 시작 명령

다음 세션 첫 명령어:

```powershell
cd D:\Project\devops\Release_claude
& .\.venv\Scripts\Activate.ps1
cat docs/rounds/F6_plan_spec_sources_integration.md

# 사용자에게 SwUTS docx path 요청 → 받으면:
mkdir .codex_tmp/round_60_local_build
# inspect_swuts_docx_structure.py 작성 + 실행 (T401)
```

본 plan에 작업 흐름이 모두 들어있어, **새 세션에서 별도 컨텍스트 재구축 없이 즉시 F6-A T401부터 시작 가능**.
