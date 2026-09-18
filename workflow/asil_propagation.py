"""요구 ASIL → 함수 역전파 — 추적성 링크 테이블 기반(N2).

**왜 필요한가(실측)**: 테스트 설계 어드바이저·아키텍처 메트릭의 ASIL 축은 지금까지 C 소스
주석 `@asil` 하나에만 의존했는데, 실제 프로젝트 소스에는 그 주석이 **0건**이다(KJPDS02_PV
build_124 전수 파싱: 914함수 중 comment_asil 보유 0). 그래서 ASIL 축이 사실상 죽어 있었다.

반면 `report/trace_link_table.json` 에는 등급이 **요구 단위로** 완비돼 있고(`asil_coverage.
by_target` — 실측 요구 68건 전부 보유), 같은 파일의 `links` 에 요구→UDS 함수 링크가
3,212건 있다(`related_type="UDS_FUNCTION"`, `related_id` 가 **실제 C 함수명**). 두 축을
조인하면 함수별 ASIL을 얻는다.

정직성 규약:
- 한 함수가 여러 요구에 걸리면 **최고 등급(max)** 을 취한다 — 안전측(under-report 금지).
- 표준 등급(D/C/B/A/QM) 밖의 표기는 채택하지 않는다(오분류보다 미상이 낫다).
- 출처를 항상 라벨링한다: `comment_asil`(소스 주석) / `uds_link`(요구 역전파) / `both`.
  주석과 링크가 어긋나면 max를 쓰되 `conflict:true` 로 표면화한다(침묵 승자 선택 금지).
- 역전파는 **문자열 링크 관측**이라 함수명 동명이인을 구분하지 못한다 — 호출측이 이 한계를
  사용자에게 표기해야 한다(`note` 제공).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from workflow.coverage_gap import _ASIL_METRIC, _norm_fn

# 등급 서열 — 정렬/max 병합 단일 출처(test_design_advisor가 import해 lockstep 유지).
ASIL_RANK: Dict[str, int] = {"D": 4, "C": 3, "B": 2, "A": 1, "QM": 0}

ASIL_PROPAGATION_NOTE = (
    "함수 ASIL은 요구 ASIL을 UDS 설계 링크(요구→함수)로 역전파한 값이다 — 함수명 문자열 "
    "매칭 기반이라 동명 함수는 구분하지 못하며, 여러 요구에 걸리면 최고 등급을 취한다."
)


def normalize_asil(value: Any) -> Optional[str]:
    """표준 등급만 통과 — 'C(D)' 같은 비표준 표기는 None(미상)."""
    s = str(value or "").strip().upper()
    return s if s in _ASIL_METRIC else None


def _max_asil(a: Optional[str], b: Optional[str]) -> Optional[str]:
    if a is None:
        return b
    if b is None:
        return a
    return a if ASIL_RANK.get(a, -1) >= ASIL_RANK.get(b, -1) else b


def build_function_asil_map(link_table: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """trace_link_table → {available, by_function:{norm_fn:{asil,targets,display_name}}, stats}.

    by_function 키는 `_norm_fn` 정규화본이라 VectorCAST subprogram·파서 함수명과 같은 규약으로
    조인된다. display_name은 링크에 적힌 원문(표기용).
    """
    links = (link_table or {}).get("links")
    by_target_raw = ((link_table or {}).get("asil_coverage") or {}).get("by_target")
    if not isinstance(links, list) or not links:
        return {"available": False, "reason": "no_trace_link_table", "by_function": {}}
    if not isinstance(by_target_raw, dict) or not by_target_raw:
        return {"available": False, "reason": "no_target_asil", "by_function": {}}

    target_asil: Dict[str, str] = {}
    nonstandard_targets = 0
    for tid, raw in by_target_raw.items():
        norm = normalize_asil(raw)
        if norm is None:
            nonstandard_targets += 1
            continue
        target_asil[str(tid).strip()] = norm

    by_function: Dict[str, Dict[str, Any]] = {}
    uds_links = 0
    links_without_asil = 0
    for link in links:
        if not isinstance(link, dict) or str(link.get("related_type") or "") != "UDS_FUNCTION":
            continue
        uds_links += 1
        fn_raw = str(link.get("related_id") or "").strip()
        tid = str(link.get("target_id") or "").strip()
        key = _norm_fn(fn_raw)
        if not key or not tid:
            continue
        asil = target_asil.get(tid)
        if asil is None:
            links_without_asil += 1
            continue
        rec = by_function.setdefault(key, {"asil": None, "targets": [], "display_name": fn_raw})
        rec["asil"] = _max_asil(rec["asil"], asil)
        if tid not in rec["targets"]:
            rec["targets"].append(tid)
    for rec in by_function.values():
        rec["targets"].sort()

    return {
        "available": bool(by_function),
        "reason": None if by_function else "no_uds_function_links",
        "by_function": by_function,
        "note": ASIL_PROPAGATION_NOTE,
        "stats": {
            "targets_with_asil": len(target_asil),
            "targets_nonstandard_asil": nonstandard_targets,
            "uds_function_links": uds_links,
            "links_target_without_asil": links_without_asil,
            "functions_resolved": len(by_function),
        },
    }


def merge_asil_sources(
    comment_asil: Optional[Dict[str, str]],
    uds_asil: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, int]]:
    """소스 주석 ASIL + 역전파 ASIL → {norm_fn: {asil, source, conflict}} + 집계.

    comment_asil은 `{원본 함수명: 등급}`(summary_arch_metrics.asil_functions.by_function),
    uds_asil은 build_function_asil_map 결과. 두 축이 다르면 max를 채택하되 conflict를 남긴다.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for raw_name, raw_asil in (comment_asil or {}).items():
        asil = normalize_asil(raw_asil)
        if asil is None:
            continue
        merged[_norm_fn(raw_name)] = {"asil": asil, "source": "comment_asil", "conflict": False,
                                      "display_name": str(raw_name)}
    for key, rec in ((uds_asil or {}).get("by_function") or {}).items():
        asil = normalize_asil(rec.get("asil"))
        if asil is None:
            continue
        prev = merged.get(key)
        if prev is None:
            merged[key] = {"asil": asil, "source": "uds_link", "conflict": False,
                           "display_name": rec.get("display_name") or key,
                           "targets": rec.get("targets") or []}
            continue
        merged[key] = {
            "asil": _max_asil(prev["asil"], asil),
            "source": "both",
            # 두 축이 다른 등급을 말하면 max를 쓰되 사실을 남긴다(조용한 승자 선택 금지).
            "conflict": prev["asil"] != asil,
            "display_name": prev.get("display_name") or rec.get("display_name") or key,
            "targets": rec.get("targets") or [],
        }
    counts: Dict[str, int] = {"comment_asil": 0, "uds_link": 0, "both": 0, "conflict": 0}
    for rec in merged.values():
        counts[rec["source"]] = counts.get(rec["source"], 0) + 1
        if rec.get("conflict"):
            counts["conflict"] += 1
    counts["total"] = len(merged)
    return merged, counts


def asil_lookup(merged: Dict[str, Dict[str, Any]], function_name: Any) -> Optional[str]:
    """정규화 조인 단축 — 등급만 필요할 때."""
    rec = merged.get(_norm_fn(function_name))
    return rec.get("asil") if rec else None


def distribution(merged: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    """등급별 함수 수(표기용) — 값이 0인 등급도 키는 유지(부재≠미표시)."""
    out: Dict[str, int] = {k: 0 for k in ASIL_RANK}
    for rec in merged.values():
        asil = rec.get("asil")
        if asil in out:
            out[asil] += 1
    return out


def rank_sort_key(asil: Optional[str]) -> int:
    """정렬용 — 미상은 최하위(단, QM보다도 아래: 미상≠QM이므로 별도 축으로 다뤄야 함)."""
    return ASIL_RANK.get(asil or "", -1)


def top_functions(merged: Dict[str, Dict[str, Any]], *, limit: int = 20) -> List[Dict[str, Any]]:
    """등급 높은 순 함수 목록(표기용)."""
    rows = [
        {"function": rec.get("display_name") or key, "asil": rec.get("asil"),
         "source": rec.get("source"), "targets": rec.get("targets") or [],
         "conflict": bool(rec.get("conflict"))}
        for key, rec in merged.items()
    ]
    rows.sort(key=lambda r: (-rank_sort_key(r["asil"]), str(r["function"])))
    return rows[:limit]
