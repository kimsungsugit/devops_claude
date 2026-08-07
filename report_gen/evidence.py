"""품질 **근거** 사이드카 읽기 — "왜 이 점수인가" 의 실체.

## 왜 이 모듈이 생겼나

품질 게이트가 내는 건 점수와 PASS/FAIL 뿐이고, **그렇게 된 이유**는 DOCX 옆에
Markdown 사이드카 세 개로만 남아 있었다 — writer 는 4곳인데 reader 는 0곳이라
화면이 한 번도 본 적이 없다.

| 사이드카 | 담긴 것 | 생산자 |
|---|---|---|
| `.quality_gate.md` | 지표 15종, TBD 잔여, Description 3등급, 실패 게이트 + 개선 가이드 | `validation.py::generate_uds_field_quality_gate_report` |
| `.field_confidence.md` | 출처 신뢰도 점수/등급(A~D), 출처 분포 | `validation.py::generate_asil_related_confidence_report` |
| `.validation.md` | DOCX 구조 검증(표/이미지/heading 수, issues) | `validation.py::generate_uds_validation_report` |

## 계약 — 부재를 0 이나 통과로 접지 않는다

각 섹션은 `{"present": bool, ...}` 이고, `present=False` 면 **반드시 `reason`** 이
붙는다. 파일이 없는 것과 값이 0 인 것은 화면에서 전혀 다른 뜻이라, 빈 dict 를
돌려주면 "근거상 문제 없음" 으로 오독된다.

`gate_pass` 판정은 **직접 하지 않는다** — `gate_report.py::parse_gate_report` 에
위임한다. 그쪽이 "`Gate pass:` 가 정확히 1회일 때만 값을 낸다(2회 이상은 ambiguous,
`None` 은 판정 불가이지 통과가 아님)" 는 계약을 이미 들고 있고, 그 계약이 생긴 이유가
바로 같은 파일을 두 파서가 반대로 읽던 사건이다. 세 번째 파서를 만들지 않는다.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from report_gen.gate_report import parse_gate_report

_logger = logging.getLogger("report_gen.evidence")

__all__ = [
    "read_gate_report",
    "read_confidence_report",
    "read_docx_validation",
    "read_evidence",
    "SIDECAR_SUFFIXES",
]

# DOCX 경로 → 사이드카 경로 (`x.docx` → `x.quality_gate.md`)
SIDECAR_SUFFIXES = {
    "gate_report": ".quality_gate.md",
    "confidence": ".field_confidence.md",
    "docx_validate": ".validation.md",
}

# `- <라벨>: \`<값>\`` — 세 사이드카가 공유하는 유일한 줄 문법.
_KV_RE = re.compile(r"^-\s*([^:]+):\s*`([^`]*)`")
# `- Gates: \`3\` / \`13\` passed`
_RATIO_RE = re.compile(r"`(\d+)`\s*/\s*`(\d+)`")
# `(grade: \`D\`)`
_GRADE_RE = re.compile(r"grade:\s*`([^`]+)`", re.I)
# `- High (comment/SDS/reference): \`120\` (65.9%)`
_COUNT_PCT_RE = re.compile(r"^-\s*([^:]+):\s*`(\d+)`\s*\(([\d.]+)%\)")


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _logger.warning("사이드카 읽기 실패 %s: %s", path, exc)
        return None


def _absent(reason: str) -> Dict[str, Any]:
    """부재/실패를 **명시**한다 — 빈 dict 를 돌려주면 '문제 없음' 으로 읽힌다."""
    return {"present": False, "reason": reason}


def _sections(text: str) -> Dict[str, List[str]]:
    """`## 제목` 기준으로 본문을 나눈다. 제목 앞 서두는 `""` 키."""
    out: Dict[str, List[str]] = {"": []}
    cur = ""
    for line in text.splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out.setdefault(cur, [])
            continue
        out[cur].append(line)
    return out


def _kv(lines: List[str]) -> Dict[str, str]:
    got: Dict[str, str] = {}
    for line in lines:
        m = _KV_RE.match(line.strip())
        if m:
            got[m.group(1).strip()] = m.group(2).strip()
    return got


def _as_int(text: Optional[str]) -> Optional[int]:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def _as_float(text: Optional[str]) -> Optional[float]:
    try:
        return float(str(text).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def _bullet_list(lines: List[str]) -> List[str]:
    """`- x` 목록. 생산자가 비었을 때 쓰는 `- none` 은 빈 목록으로 본다."""
    out = []
    for line in lines:
        s = line.strip()
        if not s.startswith("- "):
            continue
        val = s[2:].strip()
        if val.lower() == "none":
            continue
        out.append(val)
    return out


def read_gate_report(path: Path) -> Dict[str, Any]:
    """`.quality_gate.md` → 게이트 지표 + TBD 잔여 + Description 등급 + 실패 사유."""
    if not path.exists():
        return _absent("사이드카 없음 (.quality_gate.md)")
    text = _read_text(path)
    if text is None:
        return _absent("사이드카 읽기 실패 (.quality_gate.md)")

    parsed = parse_gate_report(text)  # gate_pass 판정은 단일 출처에 위임
    sec = _sections(text)
    head = _kv(sec.get("", []))

    gates_passed = gates_total = None
    for line in sec.get("", []):
        if line.strip().lower().startswith("- gates:"):
            m = _RATIO_RE.search(line)
            if m:
                gates_passed, gates_total = int(m.group(1)), int(m.group(2))
            break

    # TBD 잔여 — `- ASIL TBD: \`3\` / \`169\`` (괄호 없음: Metrics 정규식이 못 잡는다)
    tbd: Dict[str, Any] = {}
    for line in sec.get("TBD Residual", []):
        s = line.strip()
        if not s.startswith("- "):
            continue
        m = _RATIO_RE.search(s)
        label = s[2:].split(":", 1)[0].strip().lower().replace(" ", "_")
        if m and label:
            tbd[label] = {"count": int(m.group(1)), "total": int(m.group(2))}

    # Description 3등급 — `- High (comment/SDS/reference): \`120\` (65.9%)`
    desc_quality: Dict[str, Any] = {}
    for line in sec.get("Description Quality Grade", []):
        m = _COUNT_PCT_RE.match(line.strip())
        if not m:
            continue
        key = m.group(1).split("(")[0].strip().lower()
        desc_quality[key] = {"count": int(m.group(2)), "pct": float(m.group(3))}

    # 실패 게이트 — `- **name**: 0.0% < 70.0%` (개선 가이드는 하위 들여쓰기 줄)
    failed: List[Dict[str, Any]] = []
    guide_by_gate: Dict[str, str] = {}
    last_gate = ""
    for line in sec.get("Failed Gates", []):
        s = line.strip()
        if s.startswith("- **"):
            name = s[4:].split("**", 1)[0].strip()
            detail = s.split(":", 1)[1].strip() if ":" in s else ""
            failed.append({"gate": name, "detail": detail})
            last_gate = name
        elif s.startswith("- 개선 가이드:") and last_gate:
            guide_by_gate[last_gate] = s.split(":", 1)[1].strip()
        elif s.startswith("- ") and s[2:].strip().lower() != "none" and "**" not in s:
            # 구 판은 게이트 이름만 나열한다(`- description_fill_rate`).
            failed.append({"gate": s[2:].strip(), "detail": ""})
            last_gate = s[2:].strip()
    for f in failed:
        f["guide"] = guide_by_gate.get(f["gate"], "")

    return {
        "present": True,
        "gate_pass": parsed.get("gate_pass"),
        "gate_pass_status": parsed.get("gate_pass_status"),
        "total_functions": _as_int(head.get("Total functions")),
        "gates_passed": gates_passed,
        "gates_total": gates_total,
        "metrics": parsed.get("metrics") or {},
        "tbd_residual": tbd,
        "description_quality": desc_quality,
        "failed_gates": failed,
    }


def read_confidence_report(path: Path) -> Dict[str, Any]:
    """`.field_confidence.md` → 출처 신뢰도 점수/등급."""
    if not path.exists():
        return _absent("사이드카 없음 (.field_confidence.md)")
    text = _read_text(path)
    if text is None:
        return _absent("사이드카 읽기 실패 (.field_confidence.md)")

    sec = _sections(text)
    head_lines = sec.get("", [])
    head = _kv(head_lines)

    grade = None
    for line in head_lines:
        if "overall confidence score" in line.lower():
            m = _GRADE_RE.search(line)
            if m:
                grade = m.group(1).strip()
            break

    return {
        "present": True,
        "total_functions": _as_int(head.get("Total functions")),
        "overall_score": _as_float(head.get("Overall confidence score")),
        "grade": grade,
        # 출처 분포는 등급 판단의 근거라 목록째로 낸다(비면 `- none` → 빈 배열).
        "description_sources": _bullet_list(sec.get("Description Source", [])),
        "asil_sources": _bullet_list(sec.get("ASIL Source", [])),
        "related_sources": _bullet_list(sec.get("Related ID Source", [])),
    }


def read_docx_validation(path: Path) -> Dict[str, Any]:
    """`.validation.md` → DOCX 구조 검증 요약."""
    if not path.exists():
        return _absent("사이드카 없음 (.validation.md)")
    text = _read_text(path)
    if text is None:
        return _absent("사이드카 읽기 실패 (.validation.md)")

    sec = _sections(text)
    head = _kv(sec.get("", []))
    ok_raw = str(head.get("OK", "")).strip().lower()

    return {
        "present": True,
        # "OK: True|False" 가 아니면 판정 불가 — 문자열을 truthy 로 읽지 않는다
        # (JS 에서 문자열 'False' 는 truthy 라 FAIL 이 PASS 로 그려진다).
        "ok": True if ok_raw == "true" else (False if ok_raw == "false" else None),
        "tables": _as_int(head.get("Tables")),
        "images": _as_int(head.get("Images")),
        "swufn_headings": _as_int(head.get("SwUFn headings")),
        "function_info_tables": _as_int(head.get("FunctionInfo tables")),
        "logic_rows": _as_int(head.get("Logic rows")),
        # 아래 셋은 신판 산출물에만 있다 — 없으면 None(미측정)이지 0 이 아니다.
        "expected_functions": _as_int(head.get("Expected functions")),
        "matched_functions": _as_int(head.get("Matched functions")),
        "missing_from_docx": _as_int(head.get("Missing from docx")),
        "issues": _bullet_list(sec.get("Issues", [])),
    }


def read_evidence(docx_path: str) -> Dict[str, Any]:
    """산출물 DOCX 경로 → 근거 3종 묶음.

    경로는 **호출자(서버)가 DB 에서 꺼낸 값**이어야 한다. 클라이언트가 보낸 경로를
    그대로 넣으면 임의 파일 읽기가 된다 — endpoint 는 run_id 만 받는다.
    """
    raw = str(docx_path or "").strip()
    if not raw:
        return {
            "output_path_present": False,
            **{k: _absent("산출물 경로가 기록되지 않은 run") for k in SIDECAR_SUFFIXES},
        }

    base = Path(raw)
    # `x.docx` → `x.quality_gate.md` (with_suffix 는 마지막 확장자만 바꾼다)
    def _side(suffix: str) -> Path:
        return base.with_suffix(suffix) if base.suffix else Path(raw + suffix)

    return {
        "output_path_present": base.exists(),
        "gate_report": read_gate_report(_side(SIDECAR_SUFFIXES["gate_report"])),
        "confidence": read_confidence_report(_side(SIDECAR_SUFFIXES["confidence"])),
        "docx_validate": read_docx_validation(_side(SIDECAR_SUFFIXES["docx_validate"])),
    }
