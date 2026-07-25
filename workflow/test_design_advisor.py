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

from workflow.asil_propagation import ASIL_RANK as _ASIL_RANK
from workflow.coverage_gap import _ASIL_METRIC, _norm_fn

# v2(N4): IT 행 생성 · 변경 함수 축(changed_*) · ccn 기반 최소 케이스 수 추정 · 카탈로그 확장.
TEST_DESIGN_VERSION = 2

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
    # ── v2(N4) 확장: Table 8/9/11/12 전반 ──
    "state_transition": {
        "label": "상태 전이 시험", "iso_ref": "ISO 26262-6 Table 8 1e 연계",
        "when": "상태 변수/모드를 가진 함수 — 전이 경로와 불법 전이 케이스",
    },
    "control_flow": {
        "label": "제어 흐름 분석 기반 시험", "iso_ref": "ISO 26262-6 Table 9 연계",
        "when": "ccn 높고 분기 미달 — 미실행 경로를 직접 겨냥한 케이스",
    },
    "data_flow": {
        "label": "데이터 흐름 기반 시험", "iso_ref": "ISO 26262-6 Table 11 1c 연계",
        "when": "전역/공유 데이터를 쓰는 함수 — 정의-사용 쌍 커버",
    },
    "resource_usage": {
        "label": "자원 사용 시험", "iso_ref": "ISO 26262-6 Table 12 1d 연계",
        "when": "통합 레벨 — 스택/실행시간/메모리 한계 검증",
    },
    "back_to_back": {
        "label": "백투백 비교 시험", "iso_ref": "ISO 26262-6 Table 11 1d 연계",
        "when": "모델·이전 버전과 동일 입력 비교 — 변경 함수 회귀 확인",
    },
    "fault_injection": {
        "label": "오류 주입 시험", "iso_ref": "ISO 26262-6 Table 11 1e 연계",
        "when": "ASIL C/D 안전 메커니즘 — 결함 상황에서의 동작 확인",
    },
    "regression_suite": {
        "label": "회귀 시험 재실행", "iso_ref": "ISO 26262-6 §9 연계",
        "when": "변경된 함수 — 기존 케이스 재실행으로 회귀 여부 확인",
    },
}

_GAP_SEVERITY = {
    # 변경분(N4)이 최우선 — '이번 빌드에서 건드렸는데 커버가 없다'가 가장 먼저 볼 항목.
    "changed_uncovered": -2, "changed_below_target": -1,
    "uncovered": 0, "unmeasured_metric": 1, "below_target": 2, "branch_gap": 3, "statement_gap": 4,
    # 통합(IT) 축은 단위 구조 커버리지 목표와 기준이 달라 **항상 뒤로** 둔다 — 통합 시나리오에서
    # 특정 함수가 실행되지 않은 것은 '단위 시험이 없다'가 아니다(허위 경보 차단, 실측 616건).
    "it_entry_gap": 5, "it_not_exercised": 6, "it_partial": 7,
}

# IT 갭은 별도 축 — UT 갭 집계(uncovered/below_target)에 섞지 않는다.
_IT_GAP_KINDS = {"it_entry_gap", "it_not_exercised", "it_partial"}


def _norm_unit(u: Any) -> str:
    """env 인스턴스 접미사 제거 — "sysctrl_main.c'1" → "sysctrl_main.c"(중복 행 병합 키)."""
    s = str(u or "").strip()
    return (s.split("'", 1)[0] if "'" in s else s).lower()


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


def _asil_of(raw: Any) -> Optional[str]:
    """주입 ASIL 값 정규화 — dict({asil,source})·평면 문자열 양쪽 수용, 비표준은 미상."""
    val = raw.get("asil") if isinstance(raw, dict) else raw
    s = str(val or "").strip().upper()
    return s if s in _ASIL_METRIC else None


def suggested_min_cases(ccn: Optional[float], gap_kind: Optional[str] = None) -> Optional[int]:
    """분기 커버에 필요한 최소 TC 수 **추정**(McCabe: 독립 경로 수 = ccn).

    측정값이 아니라 상한 근사이므로 호출측은 estimate 라벨을 반드시 붙인다. ccn 부재는 None
    (1로 가정하면 '케이스 1개면 충분'이라는 허위 신호가 된다).
    """
    if not isinstance(ccn, (int, float)) or ccn <= 0:
        return None
    base = int(ccn)
    # 미커버 함수는 정상 경로 1건이 추가로 필요(진입 케이스) — 경험 규칙, 상한 아님.
    return base + 1 if gap_kind == "uncovered" else base


def build_coverage_rows(
    ut_entries: List[Dict[str, Any]],
    it_entries: List[Dict[str, Any]],
    asil_by_fn: Dict[str, Any],
    *,
    changed_functions: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """UT/IT entries × ASIL 조인 → 함수 행(metric_set으로 레벨 구분).

    v2(N4):
    - it_entries도 행을 만든다(구 버전은 통째로 버렸다). IT는 단위 시험과 목표가 달라
      metric_set='it'로 구분하고 ASIL 타깃 판정(meets_target)은 UT 행에만 적용한다.
    - changed_functions(베이스라인 diff의 변경 함수 정규화 집합)를 받아 changed 플래그를 단다.
    - asil_by_fn은 주석 맵(평면 문자열)과 병합 맵({asil,source}) 양쪽을 받는다(N2 연동).

    mcdc는 데이터 부재로 항상 None(정직) — ASIL C/D의 target_metric='mcdc'는
    unmeasured_target으로 표기한다.
    """
    asil_norm = {_norm_fn(k): v for k, v in (asil_by_fn or {}).items()}
    changed = changed_functions or set()
    rows: List[Dict[str, Any]] = []
    # (레벨, 함수, 유닛) 중복 병합 — 같은 함수가 env 인스턴스마다 행을 만들면(실측 IT에서
    # 동일 함수 5중복) 목록이 노이즈로 덮인다. 같은 대상의 여러 측정은 **최악값**을 남긴다.
    seen: Dict[tuple, int] = {}
    for metric_set, entries in (("ut", ut_entries or []), ("it", it_entries or [])):
        for e in entries:
            if not isinstance(e, dict):
                continue
            name = str(e.get("subprogram") or "").strip()
            if not name:
                continue
            key = _norm_fn(name)
            raw_asil = asil_norm.get(key)
            asil = _asil_of(raw_asil)
            asil_source = raw_asil.get("source") if isinstance(raw_asil, dict) else ("comment_asil" if asil else None)
            st = _rate01(e.get("statements"))
            br = _rate01(e.get("branches"))
            target = _ASIL_METRIC.get(asil) if asil else None
            current = {"statement": st, "branch": br, "mcdc": None}.get(target) if target else None
            ccn = e.get("ccn") if isinstance(e.get("ccn"), (int, float)) else None
            row = {
                "function": name,
                "unit": e.get("unit"),
                "metric_set": metric_set,
                "asil": asil,
                "asil_source": asil_source,
                "ccn": ccn,
                "statement": st,
                "branch": br,
                "mcdc": None,
                # IT 진입/호출 축(빌드 소스 스키마) — 있으면 그대로 싣는다(표시·기법 판단용).
                "functions_entered": _rate01(e.get("functions")),
                "function_calls": _rate01(e.get("function_calls")),
                "target_metric": target if metric_set == "ut" else None,
                "meets_target": (
                    None if metric_set != "ut" or target is None or target == "mcdc" or current is None
                    else bool(current >= 1.0)
                ),
                "unmeasured_target": bool(metric_set == "ut" and target == "mcdc"),
                "changed": key in changed,
                "measurements": 1,
            }
            dedup_key = (metric_set, key, _norm_unit(e.get("unit")))
            prev_idx = seen.get(dedup_key)
            if prev_idx is None:
                seen[dedup_key] = len(rows)
                rows.append(row)
                continue
            prev = rows[prev_idx]
            prev["measurements"] += 1
            # 같은 대상의 반복 측정은 최악값 채택 — 최선값으로 접으면 갭이 은폐된다(coverage_gap 규약).
            for metric in ("statement", "branch", "functions_entered", "function_calls"):
                a, b = prev.get(metric), row.get(metric)
                if isinstance(b, (int, float)) and (not isinstance(a, (int, float)) or b < a):
                    prev[metric] = b
            if isinstance(row.get("ccn"), (int, float)) and (
                not isinstance(prev.get("ccn"), (int, float)) or row["ccn"] > prev["ccn"]
            ):
                prev["ccn"] = row["ccn"]      # 복잡도는 최대(보수적)
            prev["changed"] = prev["changed"] or row["changed"]
            if row["asil"] and (not prev["asil"] or _ASIL_RANK.get(row["asil"], -1) > _ASIL_RANK.get(prev["asil"], -1)):
                prev["asil"], prev["asil_source"] = row["asil"], row["asil_source"]
    # 병합 후 타깃 판정 재계산(최악값 반영) — UT 행만 해당.
    for r in rows:
        if r["metric_set"] != "ut" or not r["target_metric"] or r["target_metric"] == "mcdc":
            continue
        cur = r.get(r["target_metric"])
        r["meets_target"] = None if cur is None else bool(cur >= 1.0)
    return rows


def derive_technique_recommendations(rows: List[Dict[str, Any]], *, top_n: int = 30) -> Dict[str, Any]:
    """함수 행 → 갭 분류 + 기법 권고(결정론 매핑, basis는 항상 수치 인용).

    우선순위: 미커버 > MC/DC 미측정(ASIL C/D) > 분기 미달 > 구문 미달. 갭 없는 함수는 제외.
    """
    items: List[Dict[str, Any]] = []
    summary = {"below_target": 0, "unmeasured_metric": 0, "uncovered": 0,
               "asil_unknown_with_gap": 0, "mcdc_unmeasured_safety": 0,
               "changed_with_gap": 0, "it_gap": 0}
    for r in rows:
        st, br, ccn, asil = r["statement"], r["branch"], r.get("ccn"), r.get("asil")
        is_it = r.get("metric_set") == "it"
        gap_kind: Optional[str] = None
        techniques: List[str] = []
        if is_it:
            # 통합(IT) 축은 단위 구조 커버리지와 목표가 다르다 — 통합 시나리오에서 함수가
            # 실행되지 않은 것을 '미커버(시험 없음)'로 부르면 허위 경보다(실측 616건).
            entered = r.get("functions_entered")
            if entered is not None and entered < 1.0:
                gap_kind, techniques = "it_entry_gap", ["integration_interface", "data_flow"]
            elif st is not None and st == 0.0:
                gap_kind, techniques = "it_not_exercised", ["integration_interface"]
            elif (st is not None and st < 1.0) or (br is not None and br < 1.0):
                gap_kind, techniques = "it_partial", ["integration_interface", "data_flow"]
            if gap_kind is None:
                continue
            if asil in ("C", "D"):
                techniques = techniques + ["fault_injection"]
            if r.get("changed"):
                techniques = techniques + ["regression_suite"]
            summary["it_gap"] += 1
            if asil is None:
                summary["asil_unknown_with_gap"] += 1
            if r.get("changed"):
                summary["changed_with_gap"] += 1
            items.append({
                "function": r["function"], "unit": r.get("unit"), "metric_set": "it",
                "asil": asil, "asil_source": r.get("asil_source"), "ccn": ccn,
                "changed": bool(r.get("changed")), "gap_kind": gap_kind,
                "techniques": list(dict.fromkeys(techniques)),
                "suggested_min_cases": None, "suggested_min_cases_estimate": True,
                "basis": (
                    f"{'변경됨 · ' if r.get('changed') else ''}통합(IT) 측정 · "
                    f"진입 {_pct(r.get('functions_entered'))} · 구문 {_pct(st)} · 분기 {_pct(br)}"
                    f" · ccn {int(ccn) if ccn is not None else '—'}"
                    + (f" · 반복 측정 {r['measurements']}회 중 최악값" if (r.get("measurements") or 1) > 1 else "")
                ),
            })
            continue
        if st is not None and st == 0.0:
            gap_kind = "uncovered"
            techniques = ["requirements_based", "equivalence_partitioning"]
        elif r["unmeasured_target"]:
            gap_kind = "unmeasured_metric"
            techniques = ["mcdc_measurement", "decision_condition", "boundary_values"]
        elif br is not None and br < 1.0:
            gap_kind = "below_target" if r["target_metric"] == "branch" else "branch_gap"
            techniques = ["boundary_values"] + (
                ["decision_condition", "control_flow"] if (ccn or 0) >= 10 else ["equivalence_partitioning"]
            )
        elif st is not None and st < 1.0:
            gap_kind = "below_target" if r["target_metric"] == "statement" else "statement_gap"
            techniques = ["requirements_based", "equivalence_partitioning"]
        if gap_kind is None:
            continue
        # 변경분 승격(N4) — 이번 빌드에서 손댄 함수의 갭을 최상단으로.
        if r.get("changed") and gap_kind in ("uncovered", "below_target", "branch_gap", "statement_gap"):
            gap_kind = "changed_uncovered" if gap_kind == "uncovered" else "changed_below_target"
            techniques = techniques + ["regression_suite", "back_to_back"]
        if asil in ("B", "C", "D"):
            techniques = techniques + ["robustness"]
        if asil in ("C", "D"):
            techniques = techniques + ["fault_injection"]
        base_kind = gap_kind.replace("changed_", "") if gap_kind.startswith("changed_") else gap_kind
        if base_kind == "uncovered":
            summary["uncovered"] += 1
        elif base_kind == "unmeasured_metric":
            summary["unmeasured_metric"] += 1
            summary["mcdc_unmeasured_safety"] += 1
        elif base_kind == "below_target":
            summary["below_target"] += 1
        if r.get("changed"):
            summary["changed_with_gap"] += 1
        if asil is None:
            summary["asil_unknown_with_gap"] += 1
        min_cases = suggested_min_cases(ccn, base_kind)
        items.append({
            "function": r["function"],
            "unit": r.get("unit"),
            "metric_set": r.get("metric_set"),
            "asil": asil,
            "asil_source": r.get("asil_source"),
            "ccn": ccn,
            "changed": bool(r.get("changed")),
            "gap_kind": gap_kind,
            "techniques": list(dict.fromkeys(techniques)),  # 순서 유지 dedup
            "suggested_min_cases": min_cases,
            "suggested_min_cases_estimate": True,  # McCabe 근사 — 측정값 아님
            "basis": (
                f"{'변경됨 · ' if r.get('changed') else ''}"
                f"{'통합(IT) · ' if is_it else ''}"
                f"ASIL {asil or '미상'} · 구문 {_pct(st)} · 분기 {_pct(br)}"
                f" · MC/DC 미측정 · ccn {int(ccn) if ccn is not None else '—'}"
                + (f" · 분기 커버 최소 TC 추정 {min_cases}" if min_cases else "")
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
