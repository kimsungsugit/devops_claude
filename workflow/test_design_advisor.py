"""테스트 설계 어드바이저(결정론, LLM 0회) — 커버리지×ASIL×ccn 기법 매핑 + 설계-시험 갭.

사용자 요구 "테스트를 더 잘 설계하는 방법"과 "함수 단위를 넘는 디테일"의 결정론 코어.
ISO 26262-6:2018 참조 규약(ASIL→구조 커버리지 단일 출처는 coverage_gap._ASIL_METRIC과 lockstep):
- 파생 기법: Table 8(단위 TC 도출 — 1a 요구기반/1b 동등분할/1c 경계값/1d 오류추정),
  Table 11(통합 TC 도출). 구조 커버리지: Table 9(단위 — 1a stmt/1b branch/1c MC/DC),
  Table 12(아키텍처 레벨 — 함수/호출 커버리지).
- 권고는 표 참조 기반 **가이드**이며 심사(assessment) 판정이 아니다.

정직성:
- MC/DC 데이터 부재(캐시 실측: VCAST 원본 HTML에도 컬럼 자체가 없음 — 미측정 모드) →
  ASIL C/D의 mcdc 타깃은 'unmeasured_metric'이지 '미달'이 아니다(미측정≠미달).
- ASIL 미상은 QM으로 단정하지 않는다(asil 미상 카운터 별도 축).
- SUTS 링크 밴드가 통째로 0인 잡(HDPDM01 실측)은 band_missing으로 표시하고 타깃별 갭
  열거를 억제한다(증거부재≠갭 — 전 요구가 갭으로 보이는 허위 경보 차단).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from workflow.coverage_gap import _ASIL_METRIC, _norm_fn

TEST_DESIGN_VERSION = 1

MCDC_NOTE = (
    "MC/DC는 현 빌드 산출물에 미측정(VectorCAST 리포트에 컬럼 부재) — "
    "ASIL C/D 함수의 MC/DC 항목은 '측정 활성화'가 선행 조치다(미측정≠미달)."
)

# 기법 카탈로그 — id → {label, iso_ref, when}. iso_ref는 참조 표기이지 심사 판정 아님.
TECHNIQUE_CATALOG: Dict[str, Dict[str, str]] = {
    "requirements_based": {
        "label": "요구사항 기반 시험", "iso_ref": "ISO 26262-6 Table 8 1a",
        "when": "모든 단위의 기본 — 요구 명세로부터 TC 도출",
    },
    "equivalence_partitioning": {
        "label": "동등 분할", "iso_ref": "ISO 26262-6 Table 8 1b",
        "when": "입력 도메인을 대표값 클래스로 분할 — 구문 미달 함수의 케이스 확장",
    },
    "boundary_values": {
        "label": "경계값 분석", "iso_ref": "ISO 26262-6 Table 8 1c",
        "when": "분기 조건의 경계(min/max/±1) — 분기 미달 함수",
    },
    "error_guessing": {
        "label": "오류 추정", "iso_ref": "ISO 26262-6 Table 8 1d",
        "when": "결함 이력·경험 기반 보완 케이스",
    },
    "decision_condition": {
        "label": "결정/조건 조합 시험", "iso_ref": "ISO 26262-6 Table 9 1b 연계",
        "when": "복합 조건(ccn 높음) 함수의 분기 커버 확장",
    },
    "mcdc_measurement": {
        "label": "MC/DC 측정 활성화", "iso_ref": "ISO 26262-6 Table 9 1c",
        "when": "ASIL C/D — 현 데이터엔 MC/DC 미측정(측정 활성화 선행)",
    },
    "robustness": {
        "label": "강건성(비정상 입력) 시험", "iso_ref": "ISO 26262-6 §9.4.2 연계",
        "when": "ASIL B 이상 — 범위 밖/NULL/오버플로 입력",
    },
    "integration_interface": {
        "label": "인터페이스 통합 시험", "iso_ref": "ISO 26262-6 Table 11",
        "when": "IT 함수 진입/호출 미커버 — 호출 경로 설계",
    },
}

_GAP_SEVERITY = {"uncovered": 0, "unmeasured_metric": 1, "below_target": 2, "branch_gap": 3, "statement_gap": 4}
_ASIL_RANK = {"D": 4, "C": 3, "B": 2, "A": 1, "QM": 0}


def normalize_related_id(rid: Any) -> str:
    """추적 링크 related_id 정규화 — VCAST 접미사 '" (N TC)"' 제거."""
    return re.sub(r"\s*\(\d+\s*TC\)\s*$", "", str(rid or "").strip())


def _rate01(d: Any) -> Optional[float]:
    """{covered,total,rate} → 0..1. covered/total 우선(스케일 무결) — rate만 있으면 >1을 %로 간주."""
    if not isinstance(d, dict):
        return None
    cov, tot = d.get("covered"), d.get("total")
    if isinstance(cov, (int, float)) and isinstance(tot, (int, float)) and tot:
        return float(cov) / float(tot)
    r = d.get("rate")
    if isinstance(r, (int, float)):
        return float(r) / 100.0 if float(r) > 1.0 else float(r)
    return None


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{round(x * 100)}%"


def build_coverage_rows(
    ut_entries: List[Dict[str, Any]],
    it_entries: List[Dict[str, Any]],
    asil_by_fn: Dict[str, str],
) -> List[Dict[str, Any]]:
    """UT entries × ASIL(comment_asil, _norm_fn 정규화 조인) → 함수 행.

    mcdc는 데이터 부재로 항상 None(정직) — ASIL C/D의 target_metric='mcdc'는
    unmeasured_target으로 표기한다. it_entries는 현재 집계 참고용으로만 받는다(행 미생성).
    """
    del it_entries  # 시그니처 안정용 — IT 상세 행은 후속 확장 여지(현재 UT 행만)
    asil_norm = {_norm_fn(k): str(v or "").strip().upper() for k, v in (asil_by_fn or {}).items()}
    rows: List[Dict[str, Any]] = []
    for e in ut_entries or []:
        if not isinstance(e, dict):
            continue
        name = str(e.get("subprogram") or "").strip()
        if not name:
            continue
        asil = asil_norm.get(_norm_fn(name)) or None
        if asil is not None and asil not in _ASIL_METRIC:
            asil = None  # 비표준 표기(예: 'C(D)')는 미상으로 — 오분류 방지
        st = _rate01(e.get("statements"))
        br = _rate01(e.get("branches"))
        target = _ASIL_METRIC.get(asil) if asil else None
        current = {"statement": st, "branch": br, "mcdc": None}.get(target) if target else None
        rows.append({
            "function": name,
            "unit": e.get("unit"),
            "asil": asil,
            "ccn": e.get("ccn") if isinstance(e.get("ccn"), (int, float)) else None,
            "statement": st,
            "branch": br,
            "mcdc": None,
            "target_metric": target,
            "meets_target": (None if target is None or target == "mcdc" or current is None
                             else bool(current >= 1.0)),
            "unmeasured_target": bool(target == "mcdc"),
        })
    return rows


def derive_technique_recommendations(rows: List[Dict[str, Any]], *, top_n: int = 30) -> Dict[str, Any]:
    """함수 행 → 갭 분류 + 기법 권고(결정론 매핑, basis는 항상 수치 인용).

    우선순위: 미커버 > MC/DC 미측정(ASIL C/D) > 분기 미달 > 구문 미달. 갭 없는 함수는 제외.
    """
    items: List[Dict[str, Any]] = []
    summary = {"below_target": 0, "unmeasured_metric": 0, "uncovered": 0,
               "asil_unknown_with_gap": 0, "mcdc_unmeasured_safety": 0}
    for r in rows:
        st, br, ccn, asil = r["statement"], r["branch"], r.get("ccn"), r.get("asil")
        gap_kind: Optional[str] = None
        techniques: List[str] = []
        if st is not None and st == 0.0:
            gap_kind = "uncovered"
            techniques = ["requirements_based", "equivalence_partitioning"]
        elif r["unmeasured_target"]:
            gap_kind = "unmeasured_metric"
            techniques = ["mcdc_measurement", "decision_condition", "boundary_values"]
        elif br is not None and br < 1.0:
            gap_kind = "below_target" if r["target_metric"] == "branch" else "branch_gap"
            techniques = ["boundary_values"] + (
                ["decision_condition"] if (ccn or 0) >= 10 else ["equivalence_partitioning"]
            )
        elif st is not None and st < 1.0:
            gap_kind = "below_target" if r["target_metric"] == "statement" else "statement_gap"
            techniques = ["requirements_based", "equivalence_partitioning"]
        if gap_kind is None:
            continue
        if asil in ("B", "C", "D"):
            techniques = techniques + ["robustness"]
        if gap_kind == "uncovered":
            summary["uncovered"] += 1
        elif gap_kind == "unmeasured_metric":
            summary["unmeasured_metric"] += 1
            summary["mcdc_unmeasured_safety"] += 1
        elif gap_kind == "below_target":
            summary["below_target"] += 1
        if asil is None:
            summary["asil_unknown_with_gap"] += 1
        items.append({
            "function": r["function"],
            "unit": r.get("unit"),
            "asil": asil,
            "ccn": ccn,
            "gap_kind": gap_kind,
            "techniques": techniques,
            "basis": (
                f"ASIL {asil or '미상'} · 구문 {_pct(st)} · 분기 {_pct(br)}"
                f" · MC/DC 미측정 · ccn {int(ccn) if ccn is not None else '—'}"
            ),
        })
    items.sort(key=lambda i: (
        _GAP_SEVERITY.get(i["gap_kind"], 9),
        -_ASIL_RANK.get(i["asil"] or "", -1),
        -(i["ccn"] or 0),
        i["function"],
    ))
    omitted = max(0, len(items) - top_n)
    return {"items": items[:top_n], "items_omitted": omitted, "summary": summary}


def compute_design_test_gap(link_table: Optional[Dict[str, Any]], *, cap: int = 50) -> Dict[str, Any]:
    """trace_link_table.json → 요구(target)별 'UDS 설계는 있는데 시험 링크 없음' 갭.

    band_missing 정직 규칙: 시험 밴드(SUTS/VCAST) 링크가 잡 전체에서 0이면 그 밴드 기준
    타깃별 갭 열거를 억제한다 — 증거부재≠갭(전 요구가 갭으로 보이는 허위 경보 차단).
    """
    links = (link_table or {}).get("links")
    if not isinstance(links, list) or not links:
        return {"available": False, "reason": "no_trace_link_table"}
    uds_by_target: Dict[str, set] = {}
    suts_targets: Dict[str, int] = {}
    vcast_targets: Dict[str, int] = {}
    uds_fns: set = set()
    suts_ids: set = set()
    vcast_fns: set = set()
    for link in links:
        if not isinstance(link, dict):
            continue
        rtype = str(link.get("related_type") or "")
        rid = normalize_related_id(link.get("related_id"))
        tid = str(link.get("target_id") or "").strip()
        if not tid or not rid:
            continue
        if rtype == "UDS_FUNCTION":
            uds_fns.add(rid)
            uds_by_target.setdefault(tid, set()).add(rid)
        elif rtype == "SUTS_TEST":
            suts_ids.add(rid)
            suts_targets[tid] = suts_targets.get(tid, 0) + 1
        elif rtype == "VCAST_FUNCTION":
            vcast_fns.add(rid)
            vcast_targets[tid] = vcast_targets.get(tid, 0) + 1
    band_missing = {"suts": len(suts_ids) == 0, "vcast": len(vcast_fns) == 0}
    out: Dict[str, Any] = {
        "available": True,
        "totals": {
            "targets_with_uds": len(uds_by_target),
            "uds_functions_distinct": len(uds_fns),
            "suts_tests_distinct": len(suts_ids),
            "vcast_functions_distinct": len(vcast_fns),
        },
        "band_missing": band_missing,
        "note": "갭은 요구ID 단위 링크 관측 기준 — 함수명 문자열 매칭 한계를 가진다",
    }
    if band_missing["suts"]:
        out["targets_with_uds_no_suts"] = []
        out["no_suts_suppressed"] = True  # 밴드 자체 부재 — 열거 억제(증거부재≠갭)
    else:
        no_suts = sorted(t for t in uds_by_target if t not in suts_targets)
        out["targets_with_uds_no_suts"] = [
            {"target_id": t, "uds_count": len(uds_by_target[t])} for t in no_suts[:cap]
        ]
        out["no_suts_omitted"] = max(0, len(no_suts) - cap)
    if band_missing["suts"] and band_missing["vcast"]:
        out["targets_with_uds_no_any_test"] = []
        out["no_any_suppressed"] = True
    else:
        no_any = sorted(
            t for t in uds_by_target
            if (band_missing["suts"] or t not in suts_targets)
            and (band_missing["vcast"] or t not in vcast_targets)
        )
        out["targets_with_uds_no_any_test"] = [
            {"target_id": t, "uds_count": len(uds_by_target[t])} for t in no_any[:cap]
        ]
        out["no_any_omitted"] = max(0, len(no_any) - cap)
    return out
