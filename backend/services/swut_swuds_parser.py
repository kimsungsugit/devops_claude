"""SwUDS (Software Unit Description Specification) docx parser (16차 라운드).

SwUDS는 함수별 설계 문서. 각 함수는 ``SwUFn_NNNN`` 형식 heading + 다음 table에
description / interface / requirements 정보가 들어있다 (Hyundai/Mobis 양식).

본 파서는 SwUDS docx에서 **함수 ID 목록**을 추출해서 SwUT의 2.Consistency 시트의
SwUDS↔SwUTS 매핑 검증에 사용한다. ISO 26262 ASIL A 이상 단위테스트 산출물 심사 시
"SwUDS에 정의된 함수가 SwUTS에서 모두 테스트되었는가" 가 핵심 질문이다.

## 가정 (Hyundai/Mobis 양식)

- Heading 단락 텍스트가 정확히 ``SwUFn_NNNN`` 형식으로 시작 (대소문자 구분).
- 같은 함수의 description은 그 다음에 오는 table에 들어있다.
- 함수 정의 외 다른 paragraph는 무시.

## 한계 / Fail-safe

- 다른 회사 양식 (LG / Bosch 등) 에서 heading 패턴이 다르면 ``parse_warnings`` 에
  사유 추가 후 빈 list 반환.
- python-docx ImportError 시 ``ParserResult.ok=False`` + ``parse_warnings`` 안내.
- docx zip bomb 방지는 ``excel_template_utils.validate_xlsx_template_bytes`` 와 별도
  ``DOCX_MAX_BYTES = 64MB`` 한도 자체 적용.

## ISO 26262 Tool Qualification

- ASIL A: 본 파서 결과를 reviewer 검토 후 evidence 사용 가능.
- ASIL B/C/D: 본 파서 결과는 manual 검증 후 evidence 확정 의무.
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
except ImportError:  # pragma: no cover - hook fail-safe
    Document = None  # type: ignore[assignment]
    _HAS_DOCX = False


_SWUFN_RE = re.compile(r"^SwUFn_(\d+)\b")
DOCX_MAX_BYTES = 64 * 1024 * 1024  # 64MB — DoS 방지


@dataclass
class SwUDSEntry:
    """SwUDS의 함수 항목."""
    function_id: str       # 'SwUFn_0101'
    heading_text: str      # 원본 heading (예: 'SwUFn_0101 — DrvIn_Main')
    description: str = ""  # 첫 table의 description 셀 (있으면)
    # 32차 W28: 함수별 ASIL 등급 — heading 다음 표의 'ASIL' 라벨 옆 셀에서 추출.
    # 단일 문자 ("A"/"B"/"C"/"D"/"QM") 또는 빈 string (라벨 없음/잘못된 값).
    asil: str = ""


@dataclass
class SwUDSParseResult:
    """SwUDS docx 파싱 결과."""
    ok: bool
    entries: list[SwUDSEntry] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)

    @property
    def function_ids(self) -> set[str]:
        """function_id 만 set으로 — SwUTS 비교용."""
        return {e.function_id for e in self.entries}

    @property
    def function_asil_map(self) -> dict[str, str]:
        """32차 W28: function_id → ASIL 등급 dict — c_source 부재 시 fallback.

        ASIL 비어있는 entry는 제외. 매핑 0건이면 빈 dict.
        """
        return {e.function_id: e.asil for e in self.entries if e.asil}

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "entries": [
                {"function_id": e.function_id, "heading_text": e.heading_text,
                 "description": e.description[:200], "asil": e.asil}
                for e in self.entries
            ],
            "parse_warnings": self.parse_warnings,
            "tool_qualification": {
                "evidence_class": "auto-generated draft",
                "asil_a_usage": "reviewer 검토 후 evidence 사용 가능",
                "asil_b_c_d_usage": "단독 evidence 사용 금지 — manual review 의무",
                "format_assumption": "Hyundai/Mobis 양식 (SwUFn_NNNN heading)",
            },
        }


def _iter_blocks(doc: Any):
    """문서를 paragraph + table 순서대로 yield (Hyundai 양식 핵심)."""
    body = doc._body._element  # type: ignore[attr-defined]
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield ("p", Paragraph(child, doc))
        elif isinstance(child, CT_Tbl):
            yield ("tbl", Table(child, doc))


def _extract_description_from_table(tbl: Any) -> str:
    """함수 table의 첫 row에서 description 추출 — fail-safe로 빈 string 반환.

    Hyundai 양식 table은 보통 첫 row에 label/value 페어 — 'Description' 라벨 옆 셀.
    """
    try:
        rows = tbl.rows
        for row in rows[:5]:  # 처음 5 row만 스캔
            cells = [c.text.strip() for c in row.cells]
            for i, c in enumerate(cells):
                if c.lower() in ("description", "기능 설명", "설명"):
                    if i + 1 < len(cells):
                        return cells[i + 1][:500]
    except Exception:  # pragma: no cover — 양식 다양성 fail-safe
        pass
    return ""


# 32차 W28: SwUDS table에서 ASIL 라벨 후보 — 영문 / 한글 / 변종 커버.
_ASIL_LABEL_CANDIDATES = (
    "asil", "safety level", "safety", "안전등급", "안전 등급",
    "안전성 등급", "안전성", "asil level",
)


def _extract_asil_from_table(tbl: Any) -> str:
    """32차 W28: 함수 table에서 ASIL 라벨 옆 셀 추출 → 단일 문자 정규화.

    Description 패턴과 동일한 첫 5행 스캔 + 라벨 매칭. 라벨 옆 셀 텍스트를
    ``swut_asil_resolver._normalize_asil`` 호출하여 "A"/"B"/"C"/"D"/"QM"
    또는 빈 string 반환. 라벨 미발견 / 잘못된 값 → 빈 string (fail-safe).

    32차 reviewer W1: silent except → logger.debug로 파싱 에러 진단 가능.
    """
    try:
        from backend.services.swut_asil_resolver import _normalize_asil
        rows = tbl.rows
        for row in rows[:5]:
            cells = [c.text.strip() for c in row.cells]
            for i, c in enumerate(cells):
                if c.lower() in _ASIL_LABEL_CANDIDATES:
                    if i + 1 < len(cells):
                        return _normalize_asil(cells[i + 1])
    except Exception as e:  # pragma: no cover — 양식 다양성 fail-safe
        import logging
        logging.getLogger(__name__).debug(
            "_extract_asil_from_table 파싱 예외 (양식 변종 추정): %s: %s",
            type(e).__name__, e,
        )
    return ""


def parse_swuds_docx(
    docx_bytes: bytes, parse_warnings: list[str] | None = None,
) -> SwUDSParseResult:
    """SwUDS docx bytes에서 함수 ID 목록 추출.

    Args:
        docx_bytes: docx 파일 raw bytes.
        parse_warnings: 외부 누적 list (router warnings 와 통합).

    Returns:
        SwUDSParseResult — ok / entries / parse_warnings.
    """
    warnings = parse_warnings if parse_warnings is not None else []

    if not _HAS_DOCX:
        warnings.append("python-docx 미설치 — SwUDS 파싱 skip")
        return SwUDSParseResult(ok=False, parse_warnings=warnings)

    if not docx_bytes:
        warnings.append("SwUDS docx bytes 비어있음")
        return SwUDSParseResult(ok=False, parse_warnings=warnings)

    if len(docx_bytes) > DOCX_MAX_BYTES:
        warnings.append(
            f"SwUDS docx {len(docx_bytes):,} bytes — {DOCX_MAX_BYTES:,} 한도 초과"
        )
        return SwUDSParseResult(ok=False, parse_warnings=warnings)

    try:
        doc = Document(io.BytesIO(docx_bytes))
    except Exception as e:
        warnings.append(f"SwUDS docx 로드 실패: {type(e).__name__}: {e}")
        return SwUDSParseResult(ok=False, parse_warnings=warnings)

    entries: list[SwUDSEntry] = []
    last_heading: str | None = None
    last_fn_id: str | None = None
    pending_table: Any = None

    for kind, node in _iter_blocks(doc):
        if kind == "p":
            text = (node.text or "").strip()
            m = _SWUFN_RE.match(text)
            if m:
                # 이전 heading의 entry를 (table 없이도) 저장
                if last_fn_id and last_heading and not any(
                    e.function_id == last_fn_id for e in entries
                ):
                    entries.append(SwUDSEntry(
                        function_id=last_fn_id,
                        heading_text=last_heading,
                        description="",
                    ))
                last_heading = text
                last_fn_id = f"SwUFn_{m.group(1)}"
                pending_table = None
        elif kind == "tbl" and last_fn_id and not pending_table:
            # heading 직후 첫 table만 description / ASIL 출처로 활용
            pending_table = node
            description = _extract_description_from_table(node)
            # 32차 W28: 동일 table에서 ASIL 추출 — Description 패턴 차용.
            asil = _extract_asil_from_table(node)
            entries.append(SwUDSEntry(
                function_id=last_fn_id,
                heading_text=last_heading or "",
                description=description,
                asil=asil,
            ))
            # 같은 heading 아래 다른 entry 추가 안 함 (중복 방지)
            last_fn_id = None
            last_heading = None

    # 마지막 heading이 table 없이 끝났을 때
    if last_fn_id and last_heading and not any(
        e.function_id == last_fn_id for e in entries
    ):
        entries.append(SwUDSEntry(
            function_id=last_fn_id, heading_text=last_heading, description="",
        ))

    if not entries:
        warnings.append(
            "SwUDS 함수 heading ('SwUFn_NNNN') 미발견 — 양식 다를 가능성"
        )
        return SwUDSParseResult(ok=False, parse_warnings=warnings)

    # 라운드 80 T1405-1: heading+table 가정으로 ASIL 추출 0건이면 regex fallback.
    # SUDS v1.07 양식은 표 ASIL header 없고 본문 "SwUFn_NNNN ... ASIL X" 형식으로
    # 함수 옆에 ASIL 등급 명시 — regex로 직접 추출 가능 (실 환경 203건 검증).
    asil_count = sum(1 for e in entries if e.asil)
    if asil_count == 0 and entries:
        _apply_regex_asil_fallback(doc, entries, warnings)

    return SwUDSParseResult(ok=True, entries=entries, parse_warnings=warnings)


# 라운드 80 T1405-1: regex fallback corpus 길이 — 100자 보수적 (false positive 방지).
_ASIL_REGEX_PROXIMITY = 100
_REGEX_PAIR_SWUFN = re.compile(
    r"(SwUFn_\d+)[\s\S]{{0,{n}}}?ASIL[\s_-]*([ABCD]|QM)\b".format(n=_ASIL_REGEX_PROXIMITY),
    re.IGNORECASE,
)


def _apply_regex_asil_fallback(
    doc: Any, entries: list[SwUDSEntry], warnings: list[str],
) -> None:
    """라운드 80 T1405-1: heading+table 양식 변종 시 regex로 ASIL fallback.

    문서 전체 paragraph + table cell text를 통합 corpus로 만들어 ``SwUFn_NNNN``
    ↔ ``ASIL [A-D|QM]`` pair 추출. 같은 fn_id에 여러 pair 발견 시 첫 매칭 채택
    (보수적). 32차 W28의 ``_normalize_asil`` 호출해 단일 문자 정규화.
    """
    try:
        from backend.services.swut_asil_resolver import _normalize_asil
        # 전체 corpus 구축
        parts: list[str] = []
        for kind, node in _iter_blocks(doc):
            if kind == "p":
                parts.append(node.text or "")
            elif kind == "tbl":
                for row in node.rows:
                    for cell in row.cells:
                        parts.append(cell.text or "")
        corpus = "\n".join(parts)
        # SwUFn → ASIL 매핑 (첫 발견 우선)
        fn_to_asil: dict[str, str] = {}
        for m in _REGEX_PAIR_SWUFN.finditer(corpus):
            fn_id = f"SwUFn_{m.group(1).split('_')[-1]}" if "_" in m.group(1) else m.group(1)
            normalized = _normalize_asil(m.group(2))
            if not normalized or fn_id in fn_to_asil:
                continue
            fn_to_asil[fn_id] = normalized
        # entries에 적용
        applied = 0
        for e in entries:
            if e.asil:
                continue
            asil = fn_to_asil.get(e.function_id)
            if asil:
                e.asil = asil
                applied += 1
        if applied > 0:
            warnings.append(
                f"SwUDS regex fallback 적용: {applied}/{len(entries)} 함수 ASIL 매핑 "
                f"(heading+table 양식 변종 추정)"
            )
    except Exception as e:  # pragma: no cover — fail-safe
        import logging
        logging.getLogger(__name__).debug(
            "SwUDS regex fallback 실패 (silent): %s: %s", type(e).__name__, e,
        )
