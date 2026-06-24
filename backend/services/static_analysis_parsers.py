"""SCM 정적분석 보조 산출물 파서 — CPD(중복) / QAC HIS Metrics / CodeEye(OSS 라이선스).

CodeSonar(codesonar_pdf_parser.py)와 함께 SCM `…/09.정적분석/01.Static Analysis/` 하위의
나머지 정적분석 도구 산출물에서 요약 지표를 추출한다. 회사 정적분석 4종 = QAC·CodeSonar·CPD·CodeEye.

- CPD  : PMD CPD 표준 XML(`<pmd-cpd><duplication lines tokens><file path/>`) → 중복 블록/라인/파일
- QAC  : PRQA HIS Metrics Report PDF → 함수별 순환복잡도 v(G)=STCYC 분포(빌드 prqa.hmr와 동일 도구,
         SCM 원본 PDF 기준 함수 카운트/최대 v(G))
- CodeEye: OSS 라이선스 검사 종합보고서 PDF(한글) → 검사 파일/성공/실패/검사명

PDF는 pdfplumber, XML은 표준 라이브러리. 모든 read는 호출측(jenkins 라우터)이 cloudium worker로 수행.
"""
from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Union

__all__ = [
    "parse_cpd_xml",
    "parse_qac_his_pdf",
    "parse_qac_his_text",
    "parse_codeeye_pdf",
    "parse_codeeye_text",
]


def _basename(p: str) -> str:
    return re.split(r"[\\/]", (p or "").rstrip("\\/"))[-1]


def _pdf_text(src: Union[bytes, str]) -> str:
    import pdfplumber

    stream: Union[io.BytesIO, str] = io.BytesIO(src) if isinstance(src, bytes) else src
    pages: List[str] = []
    with pdfplumber.open(stream) as pdf:
        for pg in pdf.pages:
            pages.append(pg.extract_text() or "")
    return "\n".join(pages)


# ──────────────────────────────────────────────────────────────────────────
# CPD (Copy-Paste Detection · PMD CPD XML)
# ──────────────────────────────────────────────────────────────────────────
def parse_cpd_xml(src: Union[bytes, str]) -> Dict[str, Any]:
    """PMD CPD XML → 중복 요약. src는 XML bytes 또는 경로."""
    try:
        if isinstance(src, bytes):
            root = ET.fromstring(src)
        else:
            root = ET.parse(src).getroot()
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:150]}"}

    blocks: List[Dict[str, Any]] = []
    total_lines = 0
    total_tokens = 0
    files: set = set()
    for d in root.findall("duplication"):
        lines = int(d.get("lines") or 0)
        tokens = int(d.get("tokens") or 0)
        total_lines += lines
        total_tokens += tokens
        fs = [f.get("path") or "" for f in d.findall("file")]
        for f in fs:
            files.add(f)
        # 한 블록이 같은 파일 내 여러 fragment를 가질 수 있어 파일명 dedup(표시 노이즈 제거).
        blocks.append({
            "lines": lines,
            "tokens": tokens,
            "fragments": len(fs),
            "files": sorted({_basename(f) for f in fs}),
        })
    blocks.sort(key=lambda b: -b["lines"])
    return {
        "ok": True,
        "duplication_blocks": len(blocks),
        "total_dup_lines": total_lines,
        "total_tokens": total_tokens,
        "files_involved": len(files),
        "top_blocks": blocks[:20],
    }


# ──────────────────────────────────────────────────────────────────────────
# QAC HIS Metrics (PRQA) PDF — 함수별 순환복잡도 v(G)=STCYC
# ──────────────────────────────────────────────────────────────────────────
def parse_qac_his_pdf(src: Union[bytes, str]) -> Dict[str, Any]:
    """PRQA HIS Metrics Report PDF → 함수별 v(G) 분포 요약.

    레이아웃: 'Function: <name>' 다음에
        'Metric (STCAL) (STM19) (STCYC) ...' / 'Values <STCAL> <STM19> <STCYC> ...'
    STCYC(3번째 값)이 순환복잡도 v(G).
    """
    try:
        full = _pdf_text(src)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:150]}"}
    return parse_qac_his_text(full)


def parse_qac_his_text(full: str) -> Dict[str, Any]:
    """추출된 HIS Metrics 텍스트 → 함수별 v(G) 요약. (PDF 분리 — 단위테스트 용이)"""
    funcs: List[Dict[str, Any]] = []
    # 'Function: name' ... 'Values <int> <int> <int>' (앞 3개 = STCAL STM19 STCYC)
    for m in re.finditer(r"Function:\s*(\S+)[\s\S]{0,200}?Values\s+(\d+)\s+(\d+)\s+(\d+)", full):
        funcs.append({"function": m.group(1), "vg": int(m.group(4))})

    vgs = [f["vg"] for f in funcs]
    summary: Dict[str, Any] = {"function_count": len(funcs)}
    if vgs:
        vgs_sorted = sorted(vgs)
        summary["vg_max"] = max(vgs)
        summary["vg_mean"] = round(sum(vgs) / len(vgs), 2)
        summary["vg_p95"] = vgs_sorted[min(len(vgs) - 1, int(len(vgs) * 0.95))]
        summary["vg_over_10"] = sum(1 for v in vgs if v > 10)
    # 프로젝트/일시
    m_proj = re.search(r"Project\s*:\s*(\S+)", full)
    if m_proj:
        summary["project"] = m_proj.group(1)
    m_stat = re.search(r"Status at:\s*(.+)", full)
    if m_stat:
        summary["status_at"] = m_stat.group(1).strip()[:60]
    top = sorted(funcs, key=lambda f: -f["vg"])[:15]
    return {"ok": bool(funcs), "summary": summary, "top_functions": top}


# ──────────────────────────────────────────────────────────────────────────
# CodeEye 종합보고서 PDF — OSS 라이선스 검사
# ──────────────────────────────────────────────────────────────────────────
def parse_codeeye_pdf(src: Union[bytes, str]) -> Dict[str, Any]:
    """CodeEye OSS 라이선스 검사 종합보고서(한글) → 검사 파일/성공/실패/검사명."""
    try:
        full = _pdf_text(src)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:150]}"}
    return parse_codeeye_text(full)


def parse_codeeye_text(full: str) -> Dict[str, Any]:
    """추출된 CodeEye 종합보고서 텍스트 → 검사 파일/성공/실패 요약. (PDF 분리)"""
    s: Dict[str, Any] = {}

    def _int(pat: str) -> Any:
        m = re.search(pat, full)
        return int(m.group(1)) if m else None

    # '검사파일개수 : 110건', '검사 성공 파일 : 110건', '검사 실패 파일 : 0건'
    s["files_checked"] = _int(r"검사파일개수\s*:\s*([\d,]+)\s*건")
    s["files_success"] = _int(r"검사\s*성공\s*파일\s*:\s*([\d,]+)\s*건")
    s["files_fail"] = _int(r"검사\s*실패\s*파일\s*:\s*([\d,]+)\s*건")
    m_name = re.search(r"검사명칭\s*:\s*(\S+)", full)
    if m_name:
        s["inspection_name"] = m_name.group(1)
    m_purpose = re.search(r"검사목적\s*:\s*(.+)", full)
    if m_purpose:
        s["purpose"] = m_purpose.group(1).strip()[:40]
    m_start = re.search(r"검사시작시간\s*:\s*([\d\-:\s]+)", full)
    if m_start:
        s["started"] = m_start.group(1).strip()[:20]
    return {"ok": s.get("files_checked") is not None, "summary": s}
