"""ISO 26262 추적성 체인 문서 ASIL extractor (라운드 80 T1405-2).

CLAUDE.md ASIL 탐지 기준 #2 "SRS/SDS 문서의 안전 요구사항 매핑" 구현.
SUDS는 ``swut_swuds_parser`` 가 함수 단위 매핑 담당. 본 모듈은:

- **SDS** (Software Design Specification) docx에서 **컴포넌트 단위** ASIL 추출
  (`SwCom_01: A`, `SwCom_02: A` 형식 표). 라운드 77 ``FunctionCoverage.component_name``
  필드와 매칭.
- **SRS** (Software Requirements Specification) docx에서 **함수명 보조** 추출
  (`g_*` / `s_*` / `u_*` 함수명 ↔ ASIL regex).

## ISO 26262 Tool Qualification

- 본 extractor 결과는 SUDS 미발견 함수에 한해 fallback. SUDS / c_source 우선.
- ASIL A: reviewer 검토 후 evidence 사용 가능.
- ASIL B/C/D: manual 검증 후 evidence 확정 의무.

## 양식 가정

- SDS: 컴포넌트 정의 표에 'ASIL' header col 존재. 같은 row의 다른 col에 컴포넌트명.
- SRS: 본문 또는 표 cell에 함수명 + ASIL 등급 인접 (200자 내).
"""
from __future__ import annotations

import io
import re

try:
    from docx import Document  # type: ignore
    _HAS_DOCX = True
except ImportError:  # pragma: no cover
    Document = None  # type: ignore[assignment]
    _HAS_DOCX = False

# 라운드 80 T1405-2: regex pair 근접 거리 (100자 ~ 1500자).
# - SRS/표 단위: 100자 (보수적, false positive 방지)
# - SUDS section 단위: 1500자 (실 양식 SwUFn~ASIL 거리 500자~1000자 측정 결과)
_ASIL_PROXIMITY_TIGHT = 100
_ASIL_PROXIMITY_SECTION = 1500
_REGEX_FN_ASIL = re.compile(
    r"\b(g_\w+|s_\w+|u_\w+|SwUFn_\d+)[\s\S]{{0,{n}}}?ASIL[\s_-]*([ABCD]|QM)\b".format(
        n=_ASIL_PROXIMITY_TIGHT,
    ),
    re.IGNORECASE,
)
_REGEX_COMPONENT_PREFIX = re.compile(r"SwCom_\d+|Sw\s*Com\s*\d+", re.IGNORECASE)
_REGEX_SWUFN_ONLY = re.compile(r"SwUFn_\d+")
_REGEX_ASIL_ONLY = re.compile(r"ASIL[\s_-]*([ABCD]|QM)\b", re.IGNORECASE)

DOCX_MAX_BYTES = 64 * 1024 * 1024  # 64MB DoS 방지 (swut_swuds_parser와 동일)


def _load_doc(docx_bytes: bytes, warnings: list[str]):
    """docx bytes 로드 — fail-safe."""
    if not _HAS_DOCX:
        warnings.append("python-docx 미설치 — ISO 26262 doc ASIL extractor skip")
        return None
    if not docx_bytes:
        warnings.append("docx bytes 비어있음 — extractor skip")
        return None
    if len(docx_bytes) > DOCX_MAX_BYTES:
        warnings.append(
            f"docx {len(docx_bytes):,} bytes > {DOCX_MAX_BYTES:,} 한도 초과 — skip"
        )
        return None
    try:
        return Document(io.BytesIO(docx_bytes))
    except Exception as e:
        warnings.append(f"docx 로드 실패: {type(e).__name__}: {e}")
        return None


def extract_component_asil_from_sds(
    docx_bytes: bytes, warnings: list[str] | None = None,
) -> dict[str, str]:
    """SDS docx에서 컴포넌트별 ASIL 추출.

    회사 양식 (HDPDM01 SDS v1.04 검증): 표에 'ASIL' header col + 컴포넌트명 col.
    같은 row에서 두 값 매칭 → dict[component_name, asil_letter] 반환.

    Args:
        docx_bytes: SDS docx raw bytes.
        warnings: 외부 누적 list (router warnings 와 통합).

    Returns:
        ``{"SwCom_01": "A", "System OS": "A", ...}`` — 컴포넌트명 다양한 키로 저장
        (SwCom_NN prefix + 별칭 텍스트 모두). 매칭 0건 시 빈 dict.
    """
    warns = warnings if warnings is not None else []
    doc = _load_doc(docx_bytes, warns)
    if doc is None:
        return {}

    try:
        from backend.services.swut_asil_resolver import _normalize_asil
    except ImportError:  # pragma: no cover
        warns.append("swut_asil_resolver import 실패 — SDS extractor skip")
        return {}

    result: dict[str, str] = {}
    table_count = 0
    asil_table_count = 0

    for tbl in doc.tables:
        table_count += 1
        if not tbl.rows:
            continue
        header = [cell.text.strip().upper() for cell in tbl.rows[0].cells]
        asil_col = next((i for i, h in enumerate(header) if "ASIL" in h), None)
        if asil_col is None:
            continue
        asil_table_count += 1
        for row in tbl.rows[1:]:
            cells = [c.text.strip() for c in row.cells]
            if len(cells) <= asil_col:
                continue
            asil_letter = _normalize_asil(cells[asil_col])
            if not asil_letter:
                continue
            # 컴포넌트 이름 후보 — SwCom_NN prefix + 다른 col text
            for idx, val in enumerate(cells):
                if idx == asil_col or not val:
                    continue
                # SwCom_NN 매칭
                m_comp = _REGEX_COMPONENT_PREFIX.search(val)
                if m_comp:
                    key = m_comp.group(0).replace(" ", "")
                    if key not in result:
                        result[key] = asil_letter
                # 별칭 (System OS / DRV IN 등) — 짧은 컴포넌트명만 등록
                v = val.strip()
                if v and len(v) <= 50 and "\n" not in v and v not in result:
                    result[v] = asil_letter

    if not result:
        warns.append(
            f"SDS docx ASIL 컴포넌트 매핑 0건 "
            f"(표 {table_count}개 중 ASIL header {asil_table_count}건)"
        )
    return result


def extract_supplementary_asil_from_srs(
    docx_bytes: bytes, warnings: list[str] | None = None,
) -> dict[str, str]:
    """SRS docx에서 함수명 보조 ASIL 추출.

    SRS는 함수 단위 ASIL 매핑이 표준이 아님 — 본문/표 텍스트에 함수명 ↔ ASIL
    인접 패턴이 산발적. 보수적으로 100자 근접 regex 추출.

    Args:
        docx_bytes: SRS docx raw bytes.
        warnings: 외부 누적 list.

    Returns:
        ``{"g_DrvIn_Main": "A", "s_SystemOperation": "A", ...}`` — 함수명 키.
        매칭 0건 시 빈 dict.
    """
    warns = warnings if warnings is not None else []
    doc = _load_doc(docx_bytes, warns)
    if doc is None:
        return {}

    try:
        from backend.services.swut_asil_resolver import _normalize_asil
    except ImportError:  # pragma: no cover
        warns.append("swut_asil_resolver import 실패 — SRS extractor skip")
        return {}

    # 전체 corpus — paragraph + table cell
    parts: list[str] = []
    for p in doc.paragraphs:
        parts.append(p.text or "")
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                parts.append(cell.text or "")
    corpus = "\n".join(parts)

    result: dict[str, str] = {}
    for m in _REGEX_FN_ASIL.finditer(corpus):
        fn_name = m.group(1)
        # 한글 조사 자동 strip (예: g_ApiIn_MotorPosition과 → g_ApiIn_MotorPosition)
        fn_name = re.sub(r"[가-힣]+$", "", fn_name).strip("._")
        if not fn_name:
            continue
        asil_letter = _normalize_asil(m.group(2))
        if not asil_letter or fn_name in result:
            continue
        result[fn_name] = asil_letter

    if not result:
        warns.append("SRS docx 함수 보조 ASIL 매핑 0건")
    return result


def extract_function_asil_from_suds(
    docx_bytes: bytes, warnings: list[str] | None = None,
) -> dict[str, str]:
    """SUDS docx에서 함수 단위 ASIL 직접 추출 (heading 의존 X).

    ``swut_swuds_parser.parse_swuds_docx`` 는 'SwUFn_NNNN heading + 다음 table'
    Hyundai 양식 가정. v1.07 양식은 heading 부재 → entries 빈 → ASIL 매핑 0.
    본 함수는 본문 전체 corpus에서 **역방향 매칭** — 각 ASIL 라벨의 직전 SwUFn
    채택 (1500자 이내). SUDS section 양식 SwUFn~ASIL 거리 500~1000자 측정 결과
    반영. 라이브 검증 SUDS v1.07 = 415건 ASIL 라벨 → 약 380건 매핑.

    Args:
        docx_bytes: SUDS docx raw bytes.
        warnings: 외부 누적 list.

    Returns:
        ``{"SwUFn_0101": "A", "SwUFn_0102": "QM", ...}`` 매핑. 매칭 0건 시 빈 dict.
    """
    warns = warnings if warnings is not None else []
    doc = _load_doc(docx_bytes, warns)
    if doc is None:
        return {}

    try:
        from backend.services.swut_asil_resolver import _normalize_asil
    except ImportError:  # pragma: no cover
        warns.append("swut_asil_resolver import 실패 — SUDS extractor skip")
        return {}

    # 전체 corpus — paragraph + table cell
    parts: list[str] = []
    for p in doc.paragraphs:
        parts.append(p.text or "")
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                parts.append(cell.text or "")
    corpus = "\n".join(parts)

    # 역방향 매칭: ASIL 라벨 각각의 직전 SwUFn 찾기 (1500자 내).
    # 1) SwUFn 위치 모두 수집 (정렬 — finditer는 본래 순서 보장)
    swufn_positions: list[tuple[int, str]] = [
        (m.start(), m.group(0)) for m in _REGEX_SWUFN_ONLY.finditer(corpus)
    ]
    # 2) ASIL 라벨 각각의 직전 SwUFn 찾기 — pointer 1-pass (O(N+M))
    result: dict[str, str] = {}
    swufn_idx = 0
    last_swufn: tuple[int, str] | None = None
    for am in _REGEX_ASIL_ONLY.finditer(corpus):
        asil_pos = am.start()
        asil_letter = _normalize_asil(am.group(1))
        if not asil_letter:
            continue
        # 직전 SwUFn 갱신 — asil_pos 이하의 마지막 swufn으로 진행
        while swufn_idx < len(swufn_positions) and swufn_positions[swufn_idx][0] <= asil_pos:
            last_swufn = swufn_positions[swufn_idx]
            swufn_idx += 1
        if last_swufn is None:
            continue
        # 거리 체크
        dist = asil_pos - last_swufn[0]
        if dist > _ASIL_PROXIMITY_SECTION:
            continue
        fn_id = last_swufn[1]
        if fn_id in result:
            continue
        result[fn_id] = asil_letter

    if not result:
        warns.append("SUDS docx 함수 ASIL 매핑 0건 (역방향)")
    return result


_REGEX_SWUFN_TO_NAME = re.compile(r"(SwUFn_\d+)[:\s]+([a-zA-Z_]\w+)")


def extract_function_name_to_swufn_from_suds(
    docx_bytes: bytes, warnings: list[str] | None = None,
) -> dict[str, str]:
    """라운드 85 T1901: SUDS docx에서 함수명 ↔ SwUFn_NNNN reverse map 추출.

    SUDS 본문 'SwUFn_0101: main', 'SwUFn_0201: g_DrvIn_Main' 형식 (Hyundai/Mobis
    양식). 라이브 진단 v1.07 = 1706건 pair (unique 440).

    Args:
        docx_bytes: SUDS docx raw bytes.
        warnings: 외부 누적 list.

    Returns:
        ``{"main": "SwUFn_0101", "g_DrvIn_Main": "SwUFn_0201", ...}``
        함수명 keyed reverse map. 첫 매칭 우선 (중복 시 후속 entry는 parse_warnings).
        매칭 0건 시 빈 dict.

    카드: vcast 추출 fc.unit_id/fc.name (함수명) → 본 map → SwUFn_NNNN →
    function_asil_from_suds (ASIL 등급) chain 완성.
    """
    warns = warnings if warnings is not None else []
    doc = _load_doc(docx_bytes, warns)
    if doc is None:
        return {}

    parts: list[str] = []
    for p in doc.paragraphs:
        parts.append(p.text or "")
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                parts.append(cell.text or "")
    corpus = "\n".join(parts)

    result: dict[str, str] = {}
    duplicates: list[str] = []
    for m in _REGEX_SWUFN_TO_NAME.finditer(corpus):
        sw_fn_id = m.group(1)
        fn_name = m.group(2)
        if fn_name in result:
            if result[fn_name] != sw_fn_id and len(duplicates) < 10:
                duplicates.append(f"{fn_name}: {result[fn_name]} vs {sw_fn_id}")
            continue
        result[fn_name] = sw_fn_id

    if duplicates:
        warns.append(
            f"SUDS 함수명↔SwUFn 중복 매핑 {len(duplicates)}건 (첫 매칭 우선): "
            f"{', '.join(duplicates[:5])}"
        )
    if not result:
        warns.append("SUDS docx 함수명↔SwUFn reverse map 0건")
    return result


__all__ = [
    "extract_function_asil_from_suds",
    "extract_function_name_to_swufn_from_suds",
    "extract_component_asil_from_sds",
    "extract_supplementary_asil_from_srs",
    "DOCX_MAX_BYTES",
]
