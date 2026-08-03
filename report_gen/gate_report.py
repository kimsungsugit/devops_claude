"""품질 게이트 사이드카(`.quality_gate.md`) 파싱 — **판정 단일 출처**.

## 왜 이 모듈이 생겼나

같은 파일을 읽는 파서가 **둘**이었고 서로 **정반대 판정**을 냈다:

    backend/helpers/uds.py::_parse_quality_gate_report
        `re.search` → **첫 매치**, `gate_pass` 는 `bool`
    report_gen/validation.py::_parse_quality_gate_summary
        줄 루프에서 매번 덮어씀 → **마지막 매치**, `gate_pass` 는 `'true'`/`'false'` **문자열**

`- Gate pass:` 가 본문에 두 번 나오면 두 파서가 다른 값을 낸다. 재현(2026-08-03):

    대조군(게이트 본문만)            uds.py=False(bool)   validation.py='false'(str)
    + 검토 의견 1줄("이전엔 Gate     uds.py=False(bool)   validation.py='true'(str)  ← 뒤집힘
      pass: True 였다" 같은 문장)

타입까지 갈렸다. **JS 에서 문자열 `'false'` 는 truthy** 라 이 값이 화면에 닿는 순간
FAIL 이 PASS 로 그려진다. 이 저장소가 네 번째로 겪는 "같은 판정을 두 곳에 복제 →
한쪽만 고쳐짐" 이다(`_is_hsis_data_row` · `_ratchet_core` · `_artifact_check` 에 이어).

## 계약

- `gate_pass` 는 `Optional[bool]`. **`None` 은 "판정 불가" 이지 통과가 아니다.**
- `- Gate pass:` 가 **정확히 1회**일 때만 값을 낸다.
  0회 → `not_found`, **2회 이상 → `ambiguous`**, 둘 다 `gate_pass=None`.
  둘 중 하나를 골라 주지 않는다 — 첫 매치를 고르든 마지막을 고르든 그게 바로
  "본문에 문장 하나 넣으면 게이트가 뒤집히는" 경로다.
- 실측 근거: 실물 사이드카 **93/93 개가 정확히 1회**다(2026-08-03, `grep -c`).
  즉 이 엄격화로 정상 산출물이 `None` 이 되는 일은 없다.

## 생산자

`report_gen/validation.py::generate_uds_quality_gate_report` 하나뿐이다(전수 확인:
`prompts/` 에 "Gate pass" 0건 — AI 가 이 문자열을 낼 경로는 없다).
지표 줄 포맷은 같은 파일 `- <Label>: \\`N\\` / \\`M\\` (X%)`.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

__all__ = [
    "parse_gate_report",
    "to_rate_map",
    "to_percent_text_map",
    "UDS_RATE_KEY_SOURCES",
]

# 앞의 `- ` 를 요구하지 않는다. 요구하면 "검토 의견" 문장 속 `Gate pass: True` 를
# 못 세어 **모호성을 감지하지 못한 채** 첫/마지막 매치 문제가 되살아난다.
_GATE_PASS_RE = re.compile(r"gate\s*pass:\s*`?(true|false)`?", re.I)

# validation.py 가 쓰던 것과 같은 모양을 유지한다(줄 단위 `search`).
# 괄호 안은 `([^)]+)` 로 넉넉히 받아 `metrics` 의 원문 문자열을 보존한다.
_METRIC_RE = re.compile(r"-\s*([^:]+):\s*`?(\d+)`?\s*/\s*`?(\d+)`?\s*\(([^)]+)\)")

_PERCENT_RE = re.compile(r"([\d.]+)\s*%")

# uds.py 쪽 `rates` 키 → 사이드카 라벨의 정규화 키(우선순위 순).
# ⚠ `called_fill`: 생산자는 `- Called fill (supported):` 로 쓰는데(validation.py:856)
#    옛 uds.py 정규식은 `- Called fill:` 만 찾아 **이 지표를 한 번도 파싱한 적이 없다**.
#    옛 표기(`- Called fill:`)를 쓰는 테스트 픽스처·구 산출물도 있으므로 둘 다 받는다.
UDS_RATE_KEY_SOURCES: Dict[str, Tuple[str, ...]] = {
    "description_fill": ("description_fill",),
    "input_fill": ("input_fill",),
    "output_fill": ("output_fill",),
    "globals_global_fill": ("globals_global_fill",),
    "globals_static_fill": ("globals_static_fill",),
    "called_fill": ("called_fill_supported", "called_fill"),
    "calling_fill": ("calling_fill",),
}


def _norm_key(label: str) -> str:
    """`Globals(Global) fill` → `globals_global_fill`, `Called fill (supported)` → `called_fill_supported`."""
    return re.sub(r"[^a-z0-9]+", "_", str(label or "").strip().lower()).strip("_")


def parse_gate_report(text: str) -> Dict[str, Any]:
    """사이드카 본문을 정본 구조로 판다.

    반환:
        gate_pass         Optional[bool] — None 이면 판정 불가(통과 아님)
        gate_pass_status  "ok" | "not_found" | "ambiguous"
        gate_pass_matches 발견된 `Gate pass:` 개수
        metrics           {정규화키: {numerator, denominator, percent, raw}}
    """
    body = str(text or "")
    found = _GATE_PASS_RE.findall(body)

    gate_pass: Optional[bool] = None
    if len(found) == 1:
        gate_pass = str(found[0]).strip().lower() == "true"
        status = "ok"
    elif not found:
        status = "not_found"
    else:
        # 여러 개면 어느 것도 고르지 않는다 — 고르는 순간 본문 텍스트가 판정을 조종한다.
        status = "ambiguous"

    metrics: Dict[str, Dict[str, Any]] = {}
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = _METRIC_RE.search(line)
        if not m:
            continue
        key = _norm_key(m.group(1))
        if not key:
            continue
        paren = str(m.group(4)).strip()
        pm = _PERCENT_RE.search(paren)
        metrics[key] = {
            "numerator": int(m.group(2)),
            "denominator": int(m.group(3)),
            "percent": float(pm.group(1)) if pm else None,
            "raw": paren,
        }

    return {
        "gate_pass": gate_pass,
        "gate_pass_status": status,
        "gate_pass_matches": len(found),
        "metrics": metrics,
    }


def to_rate_map(parsed: Dict[str, Any]) -> Dict[str, float]:
    """`backend/helpers/uds.py` 가 쓰던 `rates`(백분율 float) 모양으로 변환."""
    metrics = parsed.get("metrics") or {}
    out: Dict[str, float] = {}
    for out_key, sources in UDS_RATE_KEY_SOURCES.items():
        for src in sources:
            entry = metrics.get(src)
            if isinstance(entry, dict) and entry.get("percent") is not None:
                out[out_key] = float(entry["percent"])
                break
    return out


def to_percent_text_map(parsed: Dict[str, Any]) -> Dict[str, str]:
    """`report_gen/validation.py` 가 쓰던 `metrics`(`"71.4%"` 원문 문자열) 모양으로 변환."""
    metrics = parsed.get("metrics") or {}
    return {k: str((v or {}).get("raw") or "") for k, v in metrics.items()}
