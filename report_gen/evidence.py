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
| `.validation.md` (같은 접미사, **다른 형식**) | XLSM 구조 검증(`**결과**` PASS/FAIL, Quality Gate 표, 이슈·경고) | `generators/{sts,suts,sits}.py::*_validation_report` — 첫 줄로 판별(R47 N22) |
| `.docx.gen_stats.json` `reference_suds`·`enrichment`(+ 구 run 은 `.payload.json` `enrichment` 폴백) | **참조 SwUDS 보강** — 어느 문서를 열었나, 같은 프로젝트인가, ASIL·Related 를 몇 건 적용/차단했나, 게이트가 그 값을 되쓴 값으로 쟀나 | `docx_builder.py`(서브프로세스) + `backend.helpers.uds.merge_enriched_function_details`/`record_enrichment_in_gen_stats`(부모) — R47 N26 · R47-g N28-b |

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

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import report_gen.validation_labels as VL
from report_gen.enrichment_record import int_field as _int_field
from report_gen.enrichment_record import normalize_enrichment as _normalize_enrichment
from report_gen.gate_report import parse_gate_report, parse_scoring_scope

_logger = logging.getLogger("report_gen.evidence")

__all__ = [
    "read_gate_report",
    "read_confidence_report",
    "read_docx_validation",
    "read_reference_enrichment",
    "read_evidence",
    "EVIDENCE_SECTIONS",
    "SIDECAR_SUFFIXES",
    "GEN_STATS_SUFFIX",
    "PAYLOAD_SUFFIX",
    "VALIDATION_SIDECAR_WRITERS",
]

# DOCX 경로 → 사이드카 경로 (`x.docx` → `x.quality_gate.md`)
SIDECAR_SUFFIXES = {
    "gate_report": ".quality_gate.md",
    "confidence": ".field_confidence.md",
    "docx_validate": ".validation.md",
}

# (R47 N26) 참조 보강 근거는 Markdown 이 아니라 JSON 두 개에서 온다.
#   `<out>.docx.gen_stats.json` — 접미사 **덧붙임**(`docx_builder.gen_stats_path` 와 같은 규칙, 가드가 대조한다).
#   `<out>.payload.json`        — `with_suffix` 치환(`_write_uds_payload_sidecar` 와 같은 규칙).
GEN_STATS_SUFFIX = ".gen_stats.json"
PAYLOAD_SUFFIX = ".payload.json"

# `read_evidence` 가 내는 섹션 — 이 순서로 응답에 실린다. `sections=` 는 이 이름들만 받는다.
EVIDENCE_SECTIONS = ("gate_report", "confidence", "docx_validate", "reference")
# (리뷰 W3) 섹션 이름의 출처가 둘(사이드카 접미사 표 + 이 튜플)이라 — 새 사이드카를 표에만 적으면 어느 분기에서도
#   읽히지 않고 `sections=("새키",)` 는 ValueError 가 된다. import 시점에 포함을 강제한다.
assert set(SIDECAR_SUFFIXES) <= set(EVIDENCE_SECTIONS), "SIDECAR_SUFFIXES 의 키는 전부 EVIDENCE_SECTIONS 에 있어야 한다"

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
            got[_norm_label(m.group(1))] = m.group(2).strip()
    return got


def _as_int(text: Optional[str]) -> Optional[int]:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def _payload_present(text: Optional[str]) -> Optional[bool]:
    """head `- Payload:` 의 backtick 값 — `none` 이면 False, 파일명이면 True, 줄이 없으면(구판) None."""
    raw = str(text or "").strip()
    if not raw:
        return None
    return raw.lower() != "none"


def _payload_read_error(lines: List[str]) -> Optional[str]:
    for line in lines:
        s = line.strip()
        if s.lower().startswith("- payload:") and "읽기 실패" in s:
            m = re.search(r"읽기 실패 `([^`]*)`", s)
            return m.group(1) if m else "읽기 실패"
    return None


def _payload_file(text: Optional[str]) -> Optional[str]:
    raw = str(text or "").strip()
    return raw if raw and raw.lower() != "none" else None


def _head_ratio(lines: List[str], label: str) -> Optional[Dict[str, int]]:
    """head 의 ``- Label: `N` / `M` `` 줄 → `{count, total}`. 없으면 `None`(0 이 아니다).

    ⚠ `_kv` 는 **첫 backtick 값만** 잡는다 — 비율 줄을 `_kv` 로 읽으면 분모가 사라진다.
      그래서 줄을 직접 찾아 `_RATIO_RE` 로 판다.
    """
    want = f"- {label}:".lower()
    for line in lines:
        if line.strip().lower().startswith(want):
            m = _RATIO_RE.search(line)
            return {"count": int(m.group(1)), "total": int(m.group(2))} if m else None
    return None


def _as_count(text: Optional[str]) -> Optional[int]:
    """건수 값 — **구판 산출물이 backtick 안에 단위를 넣었다**(`` `120건` ``).

    `_as_int` 는 그걸 `None` 으로 떨어뜨린다. 라벨을 고쳐도 값이 안 들어오는 두 번째
    겹이라 따로 둔다. `_as_int` 를 관대하게 만들지 않는 것은 의도다 — `Tables` 같은
    필드는 단위가 붙을 일이 없고, 거기까지 느슨해지면 쓰레기를 숫자로 읽는다.
    """
    raw = str(text or "").strip()
    m = re.match(r"^(-?\d+)", raw)
    return int(m.group(1)) if m else None


def _norm_label(key: str) -> str:
    """라벨 키 정규화 — 사람이 읽는 `⚠` 접두를 떼어 낸다.

    라이터는 눈에 띄라고 `- ⚠ 데이터 없는 …` 로 쓴다. 그 장식을 상수에 넣으면
    라벨 상수가 표현 형식에 묶이므로, 대조 직전에 여기서 벗긴다.
    """
    return str(key or "").lstrip("⚠ \t").strip()


def _as_float(text: Optional[str]) -> Optional[float]:
    try:
        return float(str(text).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def _bullet_list(lines: List[str]) -> List[str]:
    """`- x` 목록. 생산자가 비었을 때 쓰는 `- none` 은 빈 목록으로 본다.

    ⚠ **들여쓴 하위 불릿은 앞 항목의 설명이지 항목이 아니다.** 예전엔 `strip()` 후에
      판정해 들여쓰기를 지웠고, `## Unmeasured Gates` 에 붙인 주석 한 줄이 게이트 하나로
      세어졌다 — 머리글은 `2` 인데 목록은 **3개**(2026-09-02 실측, 라운드 15가 만든 결함).
      지금은 그 목록 길이를 개수로 쓰는 소비처가 없지만, 생기는 순간 그대로 틀린다.
      이 저장소가 반복해 겪은 "절단·부속 줄을 개수로 되짚기" 함정이라 여기서 막는다.
    """
    out = []
    for line in lines:
        if line[:1].isspace():          # 들여쓴 부속 줄 — 항목이 아니다
            continue
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
    scope = parse_scoring_scope(text)  # 채점 범위 3키도 같은 모듈
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
        # ── 미측정 게이트 ── 실패와 **같은 수로 세면 안 된다**. 분모가 0인 축(예: 문서의
        # SwUFn 항목이 전역 변수라 Prototype 이 비어 입력/출력 슬롯을 셀 수 없다)을 예전엔
        # 0.0% 로 적어 실패로 계상했다 — 실 산출물 429함수에서 실패 8건 중 2건이 그랬다.
        # 없으면 `None`(구판 산출물) 이지 0 이 아니다.
        "unmeasured_gates": _bullet_list(sec.get("Unmeasured Gates", [])),
        "unmeasured_count": _as_count(head.get("Unmeasured gates")),
        # ── 해당 없음(R29 Q-4) ── "못 잰 것" 과 다르다: 대상이 0 이라 **판정에서 뺀** 축
        # (예: 모든 함수의 Prototype 을 읽었는데 입력 슬롯이 있는 함수가 0). 미측정은
        # `Gate pass` 를 False 로 붙들지만 해당 없음은 붙들지 않는다. 구판은 `None`.
        "not_applicable_gates": _bullet_list(sec.get("Not Applicable Gates", [])),
        "not_applicable_count": _as_count(head.get("Not applicable gates")),
        # ── 무엇을 채점했는가 (R30 Q-2) ── payload 유무와 문서와의 차집합. 구판은 전부 `None`.
        #   `payload_present` 가 False 면 설명 출처는 문서 자기 대조(generated_doc)라 High 가 0 인 게 정상이다.
        "payload_present": _payload_present(head.get("Payload")),
        "payload_file": _payload_file(head.get("Payload")),
        # 리뷰 W1: "없음" 과 "있는데 못 읽음" 은 다르다 — 못 읽은 사유가 있으면 그 문장(구판·정상 None)
        "payload_read_error": _payload_read_error(sec.get("", [])),
        # 리뷰 W3: 행 수 ≠ 함수 수 — 같은 이름 SwUFn 이 여럿이면 한 payload 행이 복제 채점된다.
        # (R31) 세 키는 `gate_report.parse_scoring_scope` 단일 출처 — `backend/helpers/uds.py` 의
        # `report_gate` 와 같은 함수로 읽어 API 와 증거 패널이 다른 수를 낼 수 없게 한다.
        "distinct_scored_functions": scope["distinct_scored_functions"],
        "document_entries": scope["document_entries"],
        # 채점 집합 / 문서 항목 — 판정 밖이지만 "무엇에 대한 통과인가" 의 분모. 구판 None.
        "scored_entries": scope["scored_entries"],
        "entries_not_in_payload": _head_ratio(sec.get("", []), "Document entries not in payload"),
        "payload_not_in_document": _head_ratio(sec.get("", []), "Payload functions not in document"),
        # 잰 값은 있는데 임계 표에 키가 없는 축(리뷰 W4) — FAIL 에 사유가 붙으려면 리더가 세야 한다
        "ungated_gates": _bullet_list(sec.get("Ungated Metrics", [])),
        "ungated_count": _as_count(head.get("Ungated metrics")),
        # 부분 측정(리뷰 W2): Prototype 을 못 읽은 함수는 입출력 분모에서 빠진 채 나머지로 채점된다
        "prototype_unreadable": _head_ratio(sec.get("", []), "Prototype unreadable"),
        # 어느 임계 벌로 채점했는지(R29 Q-3) — 구판은 `None`(공시된 적 없음)
        "threshold_source": (str(head.get("Threshold source") or "").strip("` ") or None),
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
    """`.validation.md` → 구조 검증 요약. **형식은 첫 줄로 판별한다** (R47 N22).

    같은 접미사를 두 계열이 쓴다:
    - UDS(DOCX): `# UDS Validation Report` + `- 라벨: \\`값\\`` 줄 문법 → `format="docx"`
    - STS/SUTS/SITS(XLSM): `# STS 생성 문서 자동 검증 리포트` + `**결과**: PASS|FAIL` + 표 →
      `format="xlsm"` (라이터: `generators/{sts,suts,sits}.py`)

    2026-09-09 라이브 실측: STS·SUTS·SITS 산출물 셋 다 이 사이드카를 **쓰고 있었는데** 리더가 UDS
    라벨로만 읽어 `present:True, ok:None` + 필드 14개 null 로 답했고, 화면은 "DOCX 구조 검증 판정
    불가" 를 그렸다 — SUTS 는 라이터가 **FAIL** 을 적어 둔 문서였다. 실패가 '판정 불가' 로 접힌 것.
    doc_type 이 아니라 **내용**으로 가른다(DB 의 doc_type 이 틀려도 파일이 진실이다).
    """
    if not path.exists():
        return _absent("사이드카 없음 (.validation.md)")
    text = _read_text(path)
    if text is None:
        return _absent("사이드카 읽기 실패 (.validation.md)")

    if _XLSM_TITLE_RE.search(text):
        return _parse_xlsm_validation(text)
    if _DOCX_TITLE_RE.search(text):
        return _parse_docx_validation(text)
    # 제목이 없어도 `- 라벨: \`값\`` 줄 문법이 있으면 UDS 계열이다(제목 없는 구판·최소 산출물).
    if any(_KV_RE.match(ln.strip()) for ln in text.splitlines()):
        return _parse_docx_validation(text)
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    # 파일은 있는데 아는 형식이 아니다 — 판정 불가를 **사유와 함께** 낸다(null 더미 아님).
    return {
        "present": True,
        "format": "unknown",
        "ok": None,
        "reason": f"검증 리포트 형식을 알 수 없다 (첫 줄: {first[:80]!r})",
        "issues": [],
        "warnings": None,
    }


# ── .validation.md 형식 판별 ────────────────────────────────────────────────
_DOCX_TITLE_RE = re.compile(r"^#\s*UDS Validation Report\b", re.M)
_XLSM_TITLE_RE = re.compile(r"^#\s*(STS|SUTS|SITS)\s+생성 문서 자동 검증 리포트\s*$", re.M)
_XLSM_RESULT_RE = re.compile(r"^\*\*결과\*\*:\s*(PASS|FAIL)\b", re.M)
_XLSM_FILE_RE = re.compile(r"^\*\*파일\*\*:\s*`([^`]*)`", re.M)
_XLSM_CHECKED_RE = re.compile(r"^\*\*검증 시각\*\*:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", re.M)
_XLSM_GATE_HDR_RE = re.compile(r"Quality Gate\s*\((\d+)\s*/\s*(\d+)\)")

#: `.validation.md` 를 실제로 쓰는 doc_type — 엔드포인트가 "이 문서 종류는 만들지 않는다" 를
#: 섹션별로 말할 때 쓴다. gate_report/confidence 는 UDS 만 쓴다.
VALIDATION_SIDECAR_WRITERS = frozenset({"uds", "sts", "suts", "sits"})


def _table_rows(lines: List[str]) -> List[List[str]]:
    """`| a | b |` 표 → 셀 목록(머리글·구분선 제외)."""
    rows: List[List[str]] = []
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if set(cells[0]) <= set("-: "):          # `|------|-----|`
            continue
        if cells[0] == "항목":                     # 머리글
            continue
        rows.append(cells)
    return rows


def _xlsm_bullets(lines: List[str]) -> List[str]:
    """`- ❌ x` / `- ⚠ x` → `x`. 라이터의 빈 표식(`이슈 없음`)은 빈 목록."""
    out: List[str] = []
    for raw in _bullet_list(lines):
        item = raw.strip()
        for mark in ("❌", "⚠"):
            if item.startswith(mark):
                item = item[len(mark):].strip()
        if not item or item in ("이슈 없음", "none"):
            continue
        out.append(item)
    return out


def _parse_xlsm_validation(text: str) -> Dict[str, Any]:
    """STS/SUTS/SITS 검증 리포트 → 판정·게이트 표·이슈·경고·구조 표.

    ⚠ `ok` 는 **`**결과**` 줄**(라이터의 `valid`)이고 `gates_passed/total` 은 **Quality Gate 표**다.
      둘은 독립이다 — SUTS 는 게이트 5/5 인데 `issues` 때문에 FAIL 인 문서가 실재한다(2026-09-09).
      게이트 표로 `ok` 를 되짚지 않는다(형제 검증기 계약이 셋 다 다르다).
    """
    tm = _XLSM_TITLE_RE.search(text)
    kind = tm.group(1) if tm else "XLSM"
    m = _XLSM_RESULT_RE.search(text)
    ok: Optional[bool] = None if m is None else (m.group(1) == "PASS")
    fm = _XLSM_FILE_RE.search(text)
    cm = _XLSM_CHECKED_RE.search(text)

    sec = _sections(text)
    gates_passed = gates_total = None
    gate_items: List[Dict[str, str]] = []
    issues: List[str] = []
    # 라이터 셋은 경고가 없으면 절을 **생략**한다 — 그래서 절 부재는 미상이 아니라 0건이다(docx 계열의
    # `None`=구판/미상 과 뜻이 다르다, 리뷰 I3).
    warnings: List[str] = []
    structure: Dict[str, str] = {}
    for title, lines in sec.items():
        if "Quality Gate" in title:
            g = _XLSM_GATE_HDR_RE.search(title)
            if g:
                gates_passed, gates_total = int(g.group(1)), int(g.group(2))
            for cells in _table_rows(lines):
                res = cells[1].upper()
                verdict = ("PASS" if res.startswith("PASS")
                           else "FAIL" if res.startswith("FAIL") else "N/A")
                gate_items.append({"name": cells[0], "result": verdict})
        elif title.endswith("Issues") or title.endswith("이슈"):
            issues = _xlsm_bullets(lines)
        elif title.endswith("Warnings") or title.endswith("경고"):
            warnings = _xlsm_bullets(lines)
        elif title.endswith("구조 검증"):
            for cells in _table_rows(lines):
                structure[cells[0]] = cells[1]

    return {
        "present": True,
        "format": "xlsm",
        "doc_kind": kind,
        "file": fm.group(1) if fm else None,
        "checked_at": cm.group(1) if cm else None,
        # `**결과**` 줄이 없으면 None(판정 불가) — PASS 로 접지 않는다.
        "ok": ok,
        "gates_passed": gates_passed,
        "gates_total": gates_total,
        "gate_items": gate_items,
        "failed_gates": [g["name"] for g in gate_items if g["result"] == "FAIL"],
        "issues": issues,
        "warnings": warnings,          # [] = 경고 0건(절 생략). docx 계열의 None(미상)과 다르다
        "structure": structure,
    }


def _parse_docx_validation(text: str) -> Dict[str, Any]:
    """UDS DOCX 검증 리포트(`- 라벨: \\`값\\`` 문법)."""
    sec = _sections(text)
    head = _kv(sec.get("", []))
    ok_raw = str(head.get("OK", "")).strip().lower()

    return {
        "present": True,
        "format": "docx",
        # "OK: True|False" 가 아니면 판정 불가 — 문자열을 truthy 로 읽지 않는다
        # (JS 에서 문자열 'False' 는 truthy 라 FAIL 이 PASS 로 그려진다).
        "ok": True if ok_raw == "true" else (False if ok_raw == "false" else None),
        "tables": _as_int(head.get("Tables")),
        "images": _as_int(head.get("Images")),
        "swufn_headings": _as_int(head.get("SwUFn headings")),
        "function_info_tables": _as_int(head.get("FunctionInfo tables")),
        "logic_rows": _as_int(head.get("Logic rows")),
        # ── 입력 대비 대조 ──────────────────────────────────────────────────
        # ⚠ 라벨은 `validation_labels` 단일 출처다. 예전엔 여기가 영문
        #   ("Expected functions" 등)을 찾는데 라이터는 한국어를 써서, 세 필드가
        #   **한 번도** 채워진 적이 없었다(2026-09-01 실측). 예외도 안 나고 값만
        #   사라지므로 눈으로는 안 보인다 — 왕복 가드
        #   `tests/unit/test_validation_report_roundtrip.py` 가 이걸 막는다.
        # ⚠ 없으면 None(미측정)이지 0 이 아니다. 0 은 "누락 없음" 으로 읽힌다.
        "expected_functions": _as_count(head.get(VL.LABEL_EXPECTED_FUNCTIONS)),
        "matched_functions": _as_count(head.get(VL.LABEL_MATCHED_FUNCTIONS)),
        "missing_from_docx": _as_count(head.get(VL.LABEL_MISSING_FROM_DOCX)),
        # 빈 명세로 나간 heading 수 — "이 문서가 껍데기인가" 의 직접 지표인데
        # 리더에 대응 키가 아예 없어 화면에 닿은 적이 없다.
        "headings_without_payload": _as_count(
            head.get(VL.LABEL_HEADINGS_WITHOUT_PAYLOAD)),
        # `drop` 으로 문서에서 통째로 뺀 절. 이게 없으면 위 수치가 **남은 것만**
        # 센다는 사실이 사라져, 얇아진 문서가 완결된 것처럼 보인다.
        "dropped_headings": _as_count(head.get(VL.LABEL_DROPPED_HEADINGS)),
        "unmatched_headings_mode": (head.get(VL.LABEL_UNMATCHED_MODE) or None),
        "issues": _bullet_list(sec.get("Issues", [])),
        # ── (R31 Q-8) 라이터↔리더 누수 ──
        # ① 경고 절(제목은 `VL.SECTION_WARNINGS` — 여기 리터럴로 적지 않는다) — "payload 없음 — 대조 불가",
        #    "소스 함수 629개가 문서에 없다" 를 라이터는 쓰는데 리더가 안 읽어 화면에 닿은 적이 없었다.
        #    `ok` 를 바꾸지 않는 공시라 목록째 낸다.
        #    절이 없는 구판은 `None`(미상) — `[]`(경고 0건) 로 접으면 아랫줄 `uncomparable` 과 규약이 갈린다(리뷰 I6).
        "warnings": (_bullet_list(sec[VL.SECTION_WARNINGS]) if VL.SECTION_WARNINGS in sec else None),
        # ② `대조 불가` 는 위 `_as_count` 에서 `None` 으로 떨어져 **줄이 없는 구판과 같아 보였다**.
        #    True = 대조 자체를 못 함(사이드카 없음/읽기 실패) · False = 대조함(수치 있음) · None = 줄 없음(구판)
        "uncomparable": _uncomparable(head.get(VL.LABEL_EXPECTED_FUNCTIONS)),
    }


def _uncomparable(text: Optional[str]) -> Optional[bool]:
    raw = str(text or "").strip()
    if not raw:
        return None
    if raw == VL.VALUE_UNCOMPARABLE:
        return True
    return False if _as_count(raw) is not None else None


_MATCHING_KEYS = ("by_name", "by_name_and_id", "id_collision_blocks", "unmatched_blocks", "unnamed_blocks",
                  "ambiguous_names")


def _matching_summary(m: Any) -> Optional[Dict[str, Optional[int]]]:
    """(R51 N40) `reference_suds.matching` → 정수 축만. dict 가 아니면 None(구판 — 미기록)."""
    if not isinstance(m, dict):
        return None
    out: Dict[str, Optional[int]] = {k: _int_field(m, k) for k in _MATCHING_KEYS}
    # 갈린 축 계수(축별 dict)의 합 — 빈 dict 는 "막은 축 없음" 이라 0(`_int_sum` 은 빈 dict 를 미측정으로 접는다).
    _bx = m.get("blocked_axes")
    out["blocked_axes"] = 0 if isinstance(_bx, dict) and not _bx else _int_sum(_bx)
    return out


def _int_sum(d: Any) -> Optional[int]:
    """`{"inputs": 3, "outputs": 0, ...}` 의 합 — dict 가 아니거나 **정수가 아닌 축이 하나라도 있으면** 미측정(None).

    (리뷰 W5) 첫 판은 int 만 골라 더해 `{"inputs": "?", "outputs": 3}` 을 3 으로 냈다 — 누락 축이 침묵하고,
    빈 dict 는 0(= "차단 없음") 이 됐다. 이 모듈의 계약은 부재를 0 으로 접지 않는 것이다.
    """
    if not isinstance(d, dict) or not d:
        return None
    if any(not isinstance(v, int) or isinstance(v, bool) for v in d.values()):
        return None
    return sum(d.values())


def _mismatch_field(v: Any) -> Optional[Dict[str, str]]:
    """`registry_mismatch` — dict 이고 `form`·`registry` 가 비지 않은 문자열일 때만 그대로(문자열화), 아니면 None."""
    if not isinstance(v, dict):
        return None
    form, reg = str(v.get("form") or "").strip(), str(v.get("registry") or "").strip()
    if not form or not reg:
        return None
    return {"scm_id": str(v.get("scm_id") or ""), "form": form, "registry": reg}


def _read_json_dict(path: Path, label: str) -> "tuple[Optional[Dict[str, Any]], Optional[str]]":
    """`(dict, None)` 또는 `(None, 사유)`. 부재와 읽기 실패를 다른 사유로 낸다."""
    if not path.is_file():
        return None, f"{label} 없음 ({path.name})"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:   # noqa: BLE001 - 사유를 화면까지 나른다
        return None, f"{label} 읽기 실패 {type(exc).__name__}: {str(exc)[:120]}"
    if not isinstance(data, dict):
        return None, f"{label} 형식이 dict 가 아님"
    return data, None


def read_reference_enrichment(gen_stats_path: Path, payload_path: Path) -> Dict[str, Any]:
    """참조 SwUDS 보강 근거 — 빌더 통계(`reference_suds`) + 부모 병합 기록(`enrichment`). (R47 N26)

    ## 왜 이 섹션이 생겼나

    R47 실측: 게이트가 23.8% 라던 ASIL 은 문서도 파서도 아니라 **배선**이었다 — 지정한 정본은 템플릿에만
    흐르고 참조는 config 기본값(다른 프로젝트 HDPDM01)이라 신원 게이트가 305건을 차단했다. 그 사실은
    `gen_stats.reference_suds` 에 **처음부터 적혀 있었는데** 읽는 화면이 없었다. 이 섹션은 그 기록을
    보드까지 나른다: 어느 문서를 열었나 · 같은 프로젝트인가 · ASIL·Related 를 몇 건 적용/차단했나 ·
    게이트가 문서를 만든 값(보강본)을 쟀나(N27).

    ## 계약

    - `present:false` 는 반드시 `reason` — 통계 사이드카 부재·읽기 실패·`reference_suds` 키 없음(구판 빌더).
    - `document`(연 파일명) / `configured`(부모가 경로를 넘겼나) 는 **구판 통계엔 없다** → `None`(모름).
      `configured:False` 는 "미지정/접근 실패", `configured:True` + `document:None` 은 "경로는 왔는데 파일이
      아니라 열지 못함"(리뷰 W2) — 화면은 `None` 을 어느 쪽으로도 접지 않는다.
    - `same_project` 는 빌더 판정 그대로(`True/False/None`) — `None` 은 확인됨이 아니다.
    - `enrichment` 는 별도 `present` 를 갖는다: payload 사이드카 부재 / `enrichment` 키 없음(병합 이전 라이터) /
      `applied:false`+사유 / `applied:true`+`functions`.
    - (R47-g N28-b) `enrichment` 의 **출처는 둘**이고 순서가 계약이다: 통계 사이드카에 `enrichment` 가 있으면
      그것을 쓰고 **payload 는 열지 않는다**(부모가 payload 기록 직후 병기 — `record_enrichment_in_gen_stats`).
      없을 때만 `<out>.payload.json` 을 연다(구 run — 2.7MB 전량 파싱, 느릴 뿐 값은 같다). 두 출처는 같은
      dict 를 같은 규칙으로 읽는다(`_normalize_enrichment`) — "0건 병합·미지 키 n" 은 어느 쪽에서 와도 실패다.
      `record_source` 가 어느 파일이었는지 말한다(`"gen_stats"` / `"payload"` / 기록 없음 `None`) — 병기 경로가
      끊기는 회귀는 값이 아니라 이 키와 소요로만 보인다.
    """
    stats, why = _read_json_dict(gen_stats_path, "생성 통계 사이드카")
    if stats is None:
        return _absent(why or "생성 통계 사이드카 없음")
    ref = stats.get("reference_suds")
    if not isinstance(ref, dict):
        return _absent("생성 통계에 reference_suds 기록 없음(참조 통계를 남기기 전 빌더)")
    identity = ref.get("identity") if isinstance(ref.get("identity"), dict) else {}
    same = identity.get("same_project")
    doc = ref.get("document")
    configured = ref.get("configured")

    enrichment: Dict[str, Any]
    if isinstance(stats.get("enrichment"), dict):
        # 병기된 요약 — payload 를 열지 않는다(리더 소요의 95% 가 그 파일이었다).
        enrichment = _normalize_enrichment(stats["enrichment"], "gen_stats")
    else:
        payload, pwhy = _read_json_dict(payload_path, "payload 사이드카")
        if payload is None:
            enrichment = {"present": False, "applied": None, "functions": None, "unknown_keys": None, "reason": pwhy,
                          "record_source": None}
        elif not isinstance(payload.get("enrichment"), dict):
            enrichment = {"present": False, "applied": None, "functions": None, "unknown_keys": None,
                          "reason": "payload 에 enrichment 기록 없음(보강본을 병합하지 않는 라이터) — 게이트 ASIL·Related 는 파서 값",
                          "record_source": None}
        else:
            enrichment = _normalize_enrichment(payload["enrichment"], "payload")

    return {
        "present": True,
        "document": str(doc) if isinstance(doc, str) and doc else None,
        "configured": configured if isinstance(configured, bool) else None,
        "same_project": same if isinstance(same, bool) else None,
        "identity_reason": str(identity.get("reason") or "") or None,
        "shared_tokens": [str(t) for t in (identity.get("shared_tokens") or []) if t],
        # (R47-d 리뷰 I3) 누가 골랐나 — "form" / "registry:<id>" / None(기록 없음: 구 빌더·jenkins 경로).
        "origin": (str(ref.get("origin")).strip() or None) if isinstance(ref.get("origin"), str) else None,
        # (R47-e N30) 폼 지정 경로 ≠ 레지스트리 정본 — 있으면 `{"scm_id","form","registry"}`, 없으면 None(불일치 없음 또는 미기록).
        "registry_compare": (str(ref.get("registry_compare")).strip() or None) if isinstance(ref.get("registry_compare"), str) else None,
        "registry_mismatch": _mismatch_field(ref.get("registry_mismatch")),
        "safety_fields_applied": _int_field(ref, "safety_fields_applied"),
        "safety_fields_blocked": _int_field(ref, "safety_fields_blocked"),
        # (R50 N38) 정본이 **이미 있던** 값을 덮은 건수(이전 출처별 dict 의 합) — 구판 gen_stats 엔 키가 없어 None(미기록),
        #   빈 dict 는 "덮은 것 없음" 이라 0 이다(`_int_sum` 은 빈 dict 를 미측정으로 접으므로 따로 가른다).
        "safety_fields_agreed": _int_field(ref, "safety_fields_agreed"),
        "safety_fields_overridden": (
            0 if isinstance(ref.get("safety_fields_overridden"), dict) and not ref.get("safety_fields_overridden")
            else _int_sum(ref.get("safety_fields_overridden"))
        ),
        "descriptive_fields_applied": _int_field(ref, "descriptive_fields_applied"),
        "invalid_asil_rejected": _int_field(ref, "invalid_asil_rejected"),
        # (R51 N40) 정본 블록→함수 매칭 계수(이름 매칭). 구판 gen_stats(키 없음)는 None — "ID 충돌 0" 으로 읽히면 안 된다.
        "matching": _matching_summary(ref.get("matching")),
        "structural_fields_applied": _int_sum(ref.get("structural_fields_applied")),
        "structural_fields_blocked": _int_sum(ref.get("structural_fields_blocked")),
        "enrichment": enrichment,
    }


def read_evidence(docx_path: str, sections: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """산출물 DOCX 경로 → 근거 4종 묶음(사이드카 3종 + 참조 보강).

    경로는 **호출자(서버)가 DB 에서 꺼낸 값**이어야 한다. 클라이언트가 보낸 경로를
    그대로 넣으면 임의 파일 읽기가 된다 — endpoint 는 run_id 만 받는다.

    `sections` — 읽을 섹션만 고른다(기본 = `EVIDENCE_SECTIONS` 전부). (R47-f N28) 보드의 근거 1회
    열람은 두 요청(evidence + attribution)이고 attribution 은 `confidence` 만 쓰는데 이 함수가
    전량이라 2.7MB payload 사이드카를 요청마다 파싱했다(실측 run 2070: 전량 78ms·13.7MB peak,
    confidence 만 2ms·0.2MB). 모르는 이름은 ValueError — 오타가 "섹션 없음" 으로 조용히 접히지 않게.
    응답엔 고른 섹션 키만 실린다(없는 키 ≠ `present:false`).
    """
    want = tuple(EVIDENCE_SECTIONS) if sections is None else tuple(sections)
    unknown = [s for s in want if s not in EVIDENCE_SECTIONS]
    if unknown:
        raise ValueError(f"read_evidence: 모르는 섹션 {unknown} — 가능한 값 {list(EVIDENCE_SECTIONS)}")
    if not want:
        # (리뷰 W1) 0개 선택은 의미 있는 요청이 아니다 — 통과시키면 소비자의 `ev.get(k) or {}` 가 "요청 안 함" 을
        #   "사이드카 없음" 으로 번역해 화면이 파일 부재를 단언한다.
        raise ValueError("read_evidence: sections 가 비었다 — 전부 읽으려면 None")

    raw = str(docx_path or "").strip()
    if not raw:
        return {
            "output_path_present": False,
            **{k: _absent("산출물 경로가 기록되지 않은 run") for k in EVIDENCE_SECTIONS if k in want},
        }

    base = Path(raw)
    # `x.docx` → `x.quality_gate.md` (with_suffix 는 마지막 확장자만 바꾼다)
    def _side(suffix: str) -> Path:
        return base.with_suffix(suffix) if base.suffix else Path(raw + suffix)

    readers = {
        "gate_report": lambda: read_gate_report(_side(SIDECAR_SUFFIXES["gate_report"])),
        "confidence": lambda: read_confidence_report(_side(SIDECAR_SUFFIXES["confidence"])),
        "docx_validate": lambda: read_docx_validation(_side(SIDECAR_SUFFIXES["docx_validate"])),
        # (R47 N26) 통계는 접미사 덧붙임, payload 는 치환 — 라이터 둘의 규칙이 다르다.
        "reference": lambda: read_reference_enrichment(Path(raw + GEN_STATS_SUFFIX), _side(PAYLOAD_SUFFIX)),
    }
    out: Dict[str, Any] = {"output_path_present": base.exists()}
    for k in EVIDENCE_SECTIONS:
        if k in want:
            out[k] = readers[k]()
    return out
