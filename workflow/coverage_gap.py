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
from typing import Any, Dict, List, Optional

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


def load_function_coverage(vectorcast_paths: List[str]) -> Dict[str, Dict[str, Optional[float]]]:
    """vectorcast RAG 경로들 → {normalized_fn: {statement, branch, mcdc}} (rate 0..1, 없으면 None).

    같은 함수가 여러 경로/UT·IT에서 나오면 메트릭별 최대 rate(최선 증거)를 취한다.
    """
    out: Dict[str, Dict[str, Optional[float]]] = {}
    try:
        from backend.routers.jenkins import _load_vectorcast_rag_from_cloudium
    except Exception:  # noqa: BLE001 — jenkins 미import 환경이면 커버리지 연동 불가, 분석은 계속
        return out

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
                rec = out.setdefault(fn, {"statement": None, "branch": None, "mcdc": None})
                for metric, key in (("statement", "statements"), ("branch", "branches"), ("mcdc", "pairs")):
                    r = _rate(e.get(key))
                    prev_r = rec[metric]
                    if r is not None and (prev_r is None or r > prev_r):
                        rec[metric] = r
    return out


def _baseline_path(cache_root: str, scm_id: str) -> Path:
    # scm_id 해시로 파일명 충돌 방지('proj/A'와 'proj-A'가 같은 sanitized 이름이 되던 문제, W2).
    h = hashlib.sha1(str(scm_id or "default").encode("utf-8")).hexdigest()[:16]
    return Path(cache_root or ".devops_pro_cache") / _BASELINE_SUBDIR / f"coverage_baseline_{h}.json"


def _read_baseline(cache_root: str, scm_id: str) -> Dict[str, Dict[str, float]]:
    try:
        p = _baseline_path(cache_root, scm_id)
        if p.is_file():
            obj = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                return obj
    except Exception:  # noqa: BLE001
        pass
    return {}


def _write_baseline(cache_root: str, scm_id: str, cov: Dict[str, Dict[str, Optional[float]]]) -> None:
    try:
        p = _baseline_path(cache_root, scm_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        # tmp 작성 후 원자적 교체 — 동시 쓰기 시 한쪽 기록 소실/부분 파일 방지(W5).
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(cov, ensure_ascii=False), encoding="utf-8")
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
) -> Dict[str, Any]:
    """영향 함수 × ASIL 타깃 대비 커버리지 gap + 직전 스냅샷 대비 delta.

    반환: ``{available, functions:[{function, asil, target_metric, statement, branch, mcdc,
    target_rate, current_rate, meets_target, delta}], summary:{evaluated, below_target,
    regressed, had_baseline}}``. VectorCAST 커버리지 데이터가 없으면 available=False.
    """
    cov = load_function_coverage(vectorcast_paths)
    if not cov:
        return {"available": False, "reason": "VectorCAST 커버리지 데이터 없음(RAG metrics 미생성)",
                "functions": [], "summary": {}}

    baseline = _read_baseline(cache_root, scm_id)
    rows: List[Dict[str, Any]] = []
    below_target = 0
    regressed = 0
    unmatched = 0          # 커버리지 데이터에 매칭 안 된 영향 함수
    unmatched_safety = 0   # 그 중 ASIL C/D — '미검증'을 안전 통과로 위장하면 안 됨
    unknown_asil = 0       # ASIL 미상 — statement 위장 평가 금지
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
        metric = _ASIL_METRIC.get(asil)   # 기본값 없음 — 미상을 statement(최저 기준)로 위장 금지(W1)
        if metric is None:
            unknown_asil += 1
            rows.append({
                "function": fn, "asil": asil or "UNKNOWN", "target_metric": "unknown",
                "statement": rec.get("statement"), "branch": rec.get("branch"), "mcdc": rec.get("mcdc"),
                "target_rate": 1.0, "current_rate": None, "meets_target": False, "delta": None,
                "asil_unknown": True,
            })
            continue
        cur = rec.get(metric)
        target = 1.0   # ISO 26262: 해당 ASIL 구조 커버리지 100% 목표(미달 시 정당화 필요)
        meets = cur is not None and cur >= target - 1e-9
        prev = (baseline.get(key) or {}).get(metric)
        delta = (cur - prev) if (isinstance(cur, (int, float)) and isinstance(prev, (int, float))) else None
        if cur is not None and not meets:
            below_target += 1
        if isinstance(delta, (int, float)) and delta < -1e-9:
            regressed += 1
        rows.append({
            "function": fn, "asil": asil, "target_metric": metric,
            "statement": rec.get("statement"), "branch": rec.get("branch"), "mcdc": rec.get("mcdc"),
            "target_rate": target, "current_rate": cur, "meets_target": meets, "delta": delta,
        })

    if update_baseline:
        # 다음 실행의 비교 기준 — 이번 커버리지 전체(영향 함수 한정 아님)를 스냅샷.
        # 주의: 삭제된 함수의 이전 rate가 stale entry로 누적될 수 있음(delta 산출엔 무해).
        _write_baseline(cache_root, scm_id, cov)

    return {
        "available": True,
        "functions": rows,
        "summary": {
            "evaluated": len(rows),
            "below_target": below_target,
            "regressed": regressed,
            "unmatched": unmatched,
            "unmatched_safety": unmatched_safety,
            "unknown_asil": unknown_asil,
            "had_baseline": bool(baseline),
        },
    }
