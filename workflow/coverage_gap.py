"""영향 함수의 VectorCAST per-function 커버리지(statement/branch/MC/DC) → ASIL 타깃 대비 gap
+ 직전 스냅샷 대비 delta. 영향도 분석의 ISO 26262 증거(MC/DC delta) 보강.

데이터 소스: ``entry.linked_docs.vectorcast`` (= ``vectorcast_rag.json`` 경로 목록). RAG 번들의
``vcast_summary.ut_metrics/it_metrics.entries`` 에 함수(subprogram)별 statements/branches/pairs
가 ``{covered,total,rate}`` 로 들어 있다(``pairs`` = VectorCAST MC/DC). test_rows에는 pass/fail만
있어 커버리지 % 산출 불가. RAG에 metrics가 없으면(cloudium 원본 폴더 fallback 등) 커버리지
데이터 없음으로 처리하고 분석은 계속한다.

"delta"는 두 가지:
  1. 목표 대비 gap — ASIL 등급별 요구 커버리지(D=MC/DC, C/B=branch, A/QM=statement) 100% 대비.
  2. 이력 대비 delta — scm_id별 직전 스냅샷과 비교(커버리지 하락 = 회귀 신호). 두 번째 빌드 없이
     직전 실행 스냅샷만으로 산출.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ASIL → 요구 구조 커버리지 메트릭(ISO 26262 Part 6 Table 9/12). D=MC/DC(pairs), C/B=branch, A/QM=statement.
_ASIL_METRIC = {"D": "mcdc", "C": "branch", "B": "branch", "A": "statement", "QM": "statement"}
_BASELINE_SUBDIR = "impact"


def _norm_fn(name: Any) -> str:
    """함수명 정규화 — 서명/파라미터/스코프 제거 + 소문자. by_name 키와 RAG subprogram 매칭용."""
    s = str(name or "").strip()
    s = re.sub(r"\(.*$", "", s)        # 'foo(int)' → 'foo'
    s = s.rsplit("::", 1)[-1]          # 'Cls::foo' → 'foo'
    return s.strip().lower()


def _rate(d: Any) -> Optional[float]:
    """{covered,total,rate} → 0..1 rate. rate 우선, 없으면 covered/total."""
    if isinstance(d, dict):
        r = d.get("rate")
        if isinstance(r, (int, float)):
            return float(r)
        cov, tot = d.get("covered"), d.get("total")
        if isinstance(cov, (int, float)) and isinstance(tot, (int, float)) and tot:
            return float(cov) / float(tot)
    return None


def load_function_coverage(
    vectorcast_paths: List[str],
    collision_names: Optional[Set[str]] = None,
) -> Tuple[Dict[str, Dict[str, Optional[float]]], Set[str]]:
    """vectorcast RAG 경로들 → ({normalized_fn: {statement, branch, mcdc}}, worst_copy_fns).

    같은 함수가 같은 unit의 UT·IT에서 여러 번 나오면 메트릭별 **최대** rate(같은 함수의 두 측정 =
    최선 증거)를 취한다.

    ⚠ 이름충돌(collision_names, 소문자 정규화 집합): 서로 다른 unit/파일에 정의된 **동명의 다른 함수**는
    하나로 병합하면 안 된다. 전역 max로 병합하면 최선 copy의 rate가 최악 copy의 gap을 은폐해
    (예: APP copy MC/DC 60% + BOOT copy 100% → merged 100%, ASIL D 함수가 '목표 충족'으로 위장)
    ISO 26262 구조 커버리지 gap을 **under-report**한다. 변경된 copy를 이름만으로 특정할 수 없으므로,
    충돌 함수는 여러 unit 중 **최악(min) rate**를 노출해 어느 copy에 gap이 있어도 재검증 대상에
    남긴다(증거 부재≠충족, 안전측 과대보고). 두 번째 반환값은 이렇게 worst-copy로 접힌 함수 집합
    (감사/표면화용).
    """
    collision_names = collision_names or set()
    # (fn, unit) → {statement, branch, mcdc}. 같은 unit의 UT/IT는 max(동일 함수의 최선 증거)로 합친다.
    per_unit: Dict[Tuple[str, str], Dict[str, Optional[float]]] = {}
    try:
        from backend.routers.jenkins import _load_vectorcast_rag_from_cloudium
    except Exception:  # noqa: BLE001 — jenkins 미import 환경이면 커버리지 연동 불가, 분석은 계속
        return {}, set()

    for raw in vectorcast_paths or []:
        path = str(raw or "").strip()
        if not path:
            continue
        try:
            rag = _load_vectorcast_rag_from_cloudium(path) or {}
        except Exception:  # noqa: BLE001
            continue
        summary = rag.get("vcast_summary") or rag.get("vcast") or {}
        if not isinstance(summary, dict):
            continue
        # ut_metrics/it_metrics 우선, 키 변형 대비 'entries' 보유 하위 dict도 수용.
        blocks: List[Dict[str, Any]] = []
        for mkey in ("ut_metrics", "it_metrics"):
            blk = summary.get(mkey)
            if isinstance(blk, dict) and isinstance(blk.get("entries"), list):
                blocks.append(blk)
        if not blocks:
            for v in summary.values():
                if isinstance(v, dict) and isinstance(v.get("entries"), list):
                    blocks.append(v)
        for blk in blocks:
            for e in (blk.get("entries") or []):
                if not isinstance(e, dict):
                    continue
                fn = _norm_fn(e.get("subprogram"))
                if not fn:
                    continue
                # unit(=component_name/source file)로 copy를 구분한다 — 충돌 함수의 서로 다른 copy를
                # 하나로 접지 않기 위한 핵심 신호. 없으면 "" (구 RAG 호환 — 그땐 전역 병합과 동일).
                unit = str(e.get("unit") or e.get("component_name") or "").strip().lower()
                rec = per_unit.setdefault((fn, unit), {"statement": None, "branch": None, "mcdc": None})
                for metric, key in (("statement", "statements"), ("branch", "branches"), ("mcdc", "pairs")):
                    r = _rate(e.get(key))
                    prev_r = rec[metric]
                    if r is not None and (prev_r is None or r > prev_r):
                        rec[metric] = r

    # (fn, unit) → fn 으로 접기. 비충돌: 전역 max(기존 동작). 충돌+다중 unit: 메트릭별 최악(min) copy.
    units_of: Dict[str, List[str]] = {}
    for (fn, unit) in per_unit:
        units_of.setdefault(fn, []).append(unit)
    out: Dict[str, Dict[str, Optional[float]]] = {}
    worst_copy_fns: Set[str] = set()
    for fn, units in units_of.items():
        recs = [per_unit[(fn, u)] for u in units]
        multi_unit = len(set(units)) > 1
        use_min = multi_unit and fn in collision_names
        merged: Dict[str, Optional[float]] = {"statement": None, "branch": None, "mcdc": None}
        for metric in ("statement", "branch", "mcdc"):
            vals = [r[metric] for r in recs if isinstance(r.get(metric), (int, float))]
            if vals:
                merged[metric] = min(vals) if use_min else max(vals)
        out[fn] = merged
        if use_min:
            worst_copy_fns.add(fn)
    return out, worst_copy_fns


def _baseline_path(cache_root: str, scm_id: str) -> Path:
    # scm_id 해시로 파일명 충돌 방지('proj/A'와 'proj-A'가 같은 sanitized 이름이 되던 문제, W2).
    h = hashlib.sha1(str(scm_id or "default").encode("utf-8")).hexdigest()[:16]
    return Path(cache_root or ".devops_pro_cache") / _BASELINE_SUBDIR / f"coverage_baseline_{h}.json"


def _read_baseline(cache_root: str, scm_id: str) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Any]]:
    """(함수별 커버리지, 메타). 메타는 스냅샷을 만든 빌드 revision 등.

    구 포맷(플랫 dict)도 읽는다 — 그때는 meta={}(revision 미상)이라 Δ 신뢰도 판정에서 legacy로 처리.
    """
    try:
        p = _baseline_path(cache_root, scm_id)
        if p.is_file():
            obj = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                if isinstance(obj.get("functions"), dict) and isinstance(obj.get("_meta"), dict):
                    return obj["functions"], obj["_meta"]  # 신 포맷
                return obj, {}  # 구 포맷(플랫) — revision 미상
    except Exception:  # noqa: BLE001
        pass
    return {}, {}


def _write_baseline(
    cache_root: str,
    scm_id: str,
    cov: Dict[str, Dict[str, Optional[float]]],
    revision: str = "",
) -> None:
    try:
        p = _baseline_path(cache_root, scm_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        # tmp 작성 후 원자적 교체 — 동시 쓰기 시 한쪽 기록 소실/부분 파일 방지(W5).
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        payload = {"_meta": {"revision": str(revision or "")}, "functions": cov}
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:  # noqa: BLE001 — 스냅샷 실패는 분석에 영향 없음
        pass


def compute_coverage_gap(
    impacted_functions: List[str],
    asil_by_fn: Dict[str, str],
    vectorcast_paths: List[str],
    *,
    cache_root: str = ".devops_pro_cache",
    scm_id: str = "",
    update_baseline: bool = True,
    build_revision: str = "",
    collision_names: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """영향 함수 × ASIL 타깃 대비 커버리지 gap + 직전 스냅샷 대비 delta.

    반환: ``{available, functions:[{function, asil, target_metric, statement, branch, mcdc,
    target_rate, current_rate, meets_target, delta}], summary:{evaluated, below_target,
    regressed, had_baseline}}``. VectorCAST 커버리지 데이터가 없으면 available=False.

    ⚠ Δ(회귀) 신뢰도: baseline은 매 실행마다 현재 커버리지로 갱신되므로, **같은 빌드를 재분석하면
    baseline이 자기 자신**이 되어 delta=0 → "회귀 0"이 "회귀 없음"으로 위장된다. build_revision을
    받아 스냅샷 revision과 비교하고, 같으면 summary.baseline_same_revision=True로 표면화한다.
    또한 더 오래된 빌드의 커버리지로 baseline을 덮어쓰지 않는다(Δ 기준 훼손 방지).
    """
    cov, _worst_copy_fns = load_function_coverage(vectorcast_paths, collision_names=collision_names)
    if not cov:
        return {"available": False, "reason": "VectorCAST 커버리지 데이터 없음(RAG metrics 미생성)",
                "functions": [], "summary": {}}

    baseline, _base_meta = _read_baseline(cache_root, scm_id)
    _base_rev = str(_base_meta.get("revision") or "")
    _cur_rev = str(build_revision or "")
    _same_rev = bool(_base_rev) and bool(_cur_rev) and _base_rev == _cur_rev
    rows: List[Dict[str, Any]] = []
    below_target = 0
    regressed = 0
    unmatched = 0          # 커버리지 데이터에 매칭 안 된 영향 함수
    unmatched_safety = 0   # 그 중 ASIL C/D — '미검증'을 안전 통과로 위장하면 안 됨
    unknown_asil = 0       # ASIL 미상 — statement 위장 평가 금지
    unmeasured = 0         # 매칭됐으나 ASIL 타깃 메트릭이 미측정(rate=None) — 증거 부재≠목표 미달
    unmeasured_safety = 0  # 그 중 ASIL C/D (예: MC/DC 리포트 없는 ASIL D 함수)
    collision_masked = 0   # 이름충돌로 worst-copy(최악) rate를 노출한 함수 수(감사/표면화)
    for fn in impacted_functions:
        key = _norm_fn(fn)
        asil = str(asil_by_fn.get(fn) or "").strip().upper()
        rec = cov.get(key)
        if rec is None:
            # 커버리지 매칭 실패 — 증거 부재를 '충족'으로 위장하지 않는다(X7/안전측). 미검증으로 노출.
            unmatched += 1
            if asil in ("C", "D"):
                unmatched_safety += 1
            continue
        # 이름충돌로 worst-copy(최악 copy)를 노출한 함수인지 — gap이 어느 copy에 있든 재검증 대상.
        _wc = key in _worst_copy_fns
        if _wc:
            collision_masked += 1
        metric = _ASIL_METRIC.get(asil)   # 기본값 없음 — 미상을 statement(최저 기준)로 위장 금지(W1)
        if metric is None:
            unknown_asil += 1
            rows.append({
                "function": fn, "asil": asil or "UNKNOWN", "target_metric": "unknown",
                "statement": rec.get("statement"), "branch": rec.get("branch"), "mcdc": rec.get("mcdc"),
                "target_rate": 1.0, "current_rate": None, "meets_target": False, "delta": None,
                "asil_unknown": True, "collision_worst_copy": _wc,
            })
            continue
        cur = rec.get(metric)
        target = 1.0   # ISO 26262: 해당 ASIL 구조 커버리지 100% 목표(미달 시 정당화 필요)
        meets = cur is not None and cur >= target - 1e-9
        # 매칭은 됐으나 타깃 메트릭이 미측정(rate=None) — 예: ASIL D 함수인데 리포트에 MC/DC 컬럼
        # 없음. '목표 미달(실패)'이 아니라 '증거 부재(미측정)'로 별도 분류해야 false 미달 경보를 막는다.
        is_unmeasured = cur is None
        prev = (baseline.get(key) or {}).get(metric)
        delta = (cur - prev) if (isinstance(cur, (int, float)) and isinstance(prev, (int, float))) else None
        if cur is not None and not meets:
            below_target += 1
        if is_unmeasured:
            unmeasured += 1
            if asil in ("C", "D"):
                unmeasured_safety += 1
        if isinstance(delta, (int, float)) and delta < -1e-9:
            regressed += 1
        rows.append({
            "function": fn, "asil": asil, "target_metric": metric,
            "statement": rec.get("statement"), "branch": rec.get("branch"), "mcdc": rec.get("mcdc"),
            "target_rate": target, "current_rate": cur, "meets_target": meets, "delta": delta,
            "unmeasured_target": is_unmeasured, "collision_worst_copy": _wc,
        })

    if update_baseline:
        # 다음 실행의 비교 기준 — 이번 커버리지 전체(영향 함수 한정 아님)를 스냅샷.
        # 주의: 삭제된 함수의 이전 rate가 stale entry로 누적될 수 있음(delta 산출엔 무해).
        # ⚠ 더 오래된 빌드로 baseline을 되돌리지 않는다 — 과거 빌드를 나중에 분석하면 Δ 기준이
        #   과거로 훼손돼 이후 실행의 회귀 탐지가 무력화된다(둘 다 숫자 revision일 때만 비교).
        _older = (
            _base_rev.isdigit() and _cur_rev.isdigit() and int(_cur_rev) < int(_base_rev)
        )
        if not _older:
            _write_baseline(cache_root, scm_id, cov, revision=_cur_rev)

    return {
        "available": True,
        "functions": rows,
        "summary": {
            "evaluated": len(rows),
            "below_target": below_target,
            "regressed": regressed,
            "unmatched": unmatched,
            "unmatched_safety": unmatched_safety,
            "unmeasured": unmeasured,
            "unmeasured_safety": unmeasured_safety,
            "unknown_asil": unknown_asil,
            # 이름충돌로 worst-copy(최악 copy) rate를 노출한 함수 수 — 전역 max 병합의 gap 은폐를
            # 안전측으로 대체했음을 표면화(0이면 충돌 영향 함수 없음 또는 단일 copy만 측정됨).
            "collision_worst_copy": collision_masked,
            "had_baseline": bool(baseline),
            # Δ(회귀) 신뢰도 3종. 하나라도 참이면 regressed 수치를 '회귀 없음/있음'으로 읽으면 안 된다.
            #  - same_revision : baseline이 이번과 같은 빌드 → Δ≡0 (비교 불가)
            #  - revision_unknown : 한쪽이라도 revision 미상(로컬 diff 등) → 같은 빌드인지 알 수 없음
            #  - newer_than_build : baseline이 더 최신 빌드(과거 빌드를 나중에 분석) → 개선분이
            #                        음수 Δ로 뒤집혀 **유령 회귀**가 보고됨
            "baseline_revision": _base_rev,
            "build_revision": _cur_rev,
            "baseline_same_revision": _same_rev,
            "baseline_revision_unknown": bool(baseline) and (not _base_rev or not _cur_rev),
            "baseline_newer_than_build": _base_rev.isdigit() and _cur_rev.isdigit() and int(_cur_rev) < int(_base_rev),
        },
    }
