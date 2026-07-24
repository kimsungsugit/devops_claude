"""PRQA 룰 다빌드 트렌드 — 규칙×빌드 위반 매트릭스 + 분류(감소/지속/증가/해소/신규).

요약탭 "룰 인텔리전스"의 결정론 코어. 빌드별 규칙 카운트는 prqa_delta의 RCR 디스크
캐시(load_rcr_details_cached — 빌드당 파싱 1회화)를 재사용하므로 2회차 호출부터는
JSON 로드 N번 + 산술뿐이다(응답 cache에 히트/미스 가시화).

정직성 규약:
- RCR 없는 빌드의 카운트 자리는 **null**(0 금지 — '위반 0'과 '측정 없음'은 다르다).
- analyzed(RCR 보유) 빌드가 2개 미만이면 분류하지 않는다(insufficient_data) —
  단일 관측으로 추세를 단정하지 않는다.
- residual('기타 규칙 (비상위)')은 규칙 귀속 불가분 — 분류에서 제외하고 별도 시리즈로.
- 분류는 관측 범위(캐시된 빌드) 한정 — '전체 이력'을 주장하지 않는다.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.services.build_inventory import list_cached_builds_meta
from backend.services.prqa_delta import load_rcr_details_cached, rule_totals_from_details

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 10
MAX_RULES = 40


def _classify(counts: List[Optional[int]]) -> Optional[str]:
    """규칙의 analyzed 구간 카운트(오름차순, null 제외)로 분류.

    우선순위: resolved > new_recent > increasing/decreasing > persistent.
    관측 2개 미만이면 None(분류 불가).
    """
    observed = [c for c in counts if c is not None]
    if len(observed) < 2:
        return None
    first, latest = observed[0], observed[-1]
    if latest == 0 and any(c > 0 for c in observed):
        return "resolved"
    if first == 0 and latest > 0:
        return "new_recent"
    if latest > first > 0:
        return "increasing"
    if 0 < latest < first:
        return "decreasing"
    if latest == first and all(c > 0 for c in observed):
        return "persistent"
    return None  # 예: 전 구간 0 — 표시 가치 없음(호출측에서 드랍)


def _file_rule_counts(details: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """violations_by_file → {path(또는 표시명): {rule: count}} (residual 제외)."""
    out: Dict[str, Dict[str, int]] = {}
    for f in details.get("violations_by_file") or []:
        if not isinstance(f, dict):
            continue
        key = str(f.get("path") or "").strip() or str(f.get("file") or "").strip()
        if not key:
            continue
        rules = out.setdefault(key, {})
        for r in f.get("rules") or []:
            if r.get("residual"):
                continue
            rule = str(r.get("rule") or "").strip()
            try:
                cnt = int(r.get("count") or 0)
            except (TypeError, ValueError):
                continue
            if rule and cnt > 0:
                rules[rule] = rules.get(rule, 0) + cnt
    return out


def compute_rule_trend(
    *, job_url: str, cache_root: Path, limit: int = DEFAULT_LIMIT, max_rules: int = MAX_RULES,
) -> Dict[str, Any]:
    metas = list_cached_builds_meta(job_url=job_url, cache_root=cache_root)
    if not metas:
        return {"ok": True, "available": False, "reason": "no_cached_build"}
    metas = metas[: max(1, int(limit))]
    metas.reverse()  # 오름차순(오래된→최신) — 트렌드 X축 방향

    builds: List[Dict[str, Any]] = []
    builds_skipped: List[Dict[str, Any]] = []
    per_build_totals: List[Optional[Dict[str, int]]] = []   # 빌드별 {rule: count} 또는 None
    per_build_residual: List[Optional[int]] = []
    per_build_files: List[Optional[Dict[str, Dict[str, int]]]] = []
    rcr_hits = 0
    rcr_misses = 0

    for m in metas:
        num = m.get("build_number")
        loaded = load_rcr_details_cached(
            Path(str(m.get("build_root") or "")), Path(str(m.get("reports_dir") or ""))
        )
        if loaded is None:
            builds_skipped.append({"build_number": num, "reason": "no_rcr"})
            builds.append({
                "build_number": num, "timestamp_iso": m.get("timestamp_iso"),
                "revision": m.get("revision"), "analyzed": False,
            })
            per_build_totals.append(None)
            per_build_residual.append(None)
            per_build_files.append(None)
            continue
        if loaded["cache_hit"]:
            rcr_hits += 1
        else:
            rcr_misses += 1
        totals, residual = rule_totals_from_details(loaded["details"])
        builds.append({
            "build_number": num, "timestamp_iso": m.get("timestamp_iso"),
            "revision": m.get("revision"), "analyzed": True,
        })
        per_build_totals.append(totals)
        per_build_residual.append(residual)
        per_build_files.append(_file_rule_counts(loaded["details"]))

    analyzed_count = sum(1 for t in per_build_totals if t is not None)
    if analyzed_count == 0:
        return {"ok": True, "available": False, "reason": "no_rcr_in_cached_builds",
                "builds_skipped": builds_skipped}
    insufficient = analyzed_count < 2

    # 전 빌드 규칙 합집합 → 규칙별 시리즈(RCR 없는 빌드 자리는 null).
    all_rules: set = set()
    for t in per_build_totals:
        if t:
            all_rules.update(t.keys())
    rules_out: List[Dict[str, Any]] = []
    for rule in all_rules:
        counts = [
            (t.get(rule, 0) if t is not None else None) for t in per_build_totals
        ]
        observed = [c for c in counts if c is not None]
        latest = observed[-1] if observed else None
        first = observed[0] if observed else None
        classification = None if insufficient else _classify(counts)
        if not insufficient and classification is None:
            continue  # 전 구간 0 등 — 노이즈 드랍
        latest_files: List[Dict[str, Any]] = []
        decreased_files: List[Dict[str, Any]] = []
        # 최신 analyzed 빌드의 파일 귀속 상위 + (감소 규칙) 최초→최신 파일별 감소.
        last_idx = max((i for i, t in enumerate(per_build_totals) if t is not None), default=None)
        first_idx = min((i for i, t in enumerate(per_build_totals) if t is not None), default=None)
        if last_idx is not None and per_build_files[last_idx]:
            pairs = [
                (path, rc.get(rule, 0)) for path, rc in per_build_files[last_idx].items() if rc.get(rule, 0) > 0
            ]
            pairs.sort(key=lambda kv: (-kv[1], kv[0]))
            latest_files = [{"path": p, "count": c} for p, c in pairs[:5]]
        if (
            classification in ("decreasing", "resolved")
            and first_idx is not None and last_idx is not None and first_idx != last_idx
            and per_build_files[first_idx] is not None and per_build_files[last_idx] is not None
        ):
            from_b = builds[first_idx]["build_number"]
            to_b = builds[last_idx]["build_number"]
            for path, rc in per_build_files[first_idx].items():
                before = rc.get(rule, 0)
                after = (per_build_files[last_idx].get(path) or {}).get(rule, 0)
                if before > after:
                    decreased_files.append({
                        "path": path, "from_build": from_b, "to_build": to_b,
                        "delta": after - before,
                    })
            decreased_files.sort(key=lambda f: (f["delta"], f["path"]))
            decreased_files = decreased_files[:5]
        rules_out.append({
            "rule": rule,
            "counts": counts,
            "latest": latest,
            "first": first,
            "net": (latest - first) if (latest is not None and first is not None) else None,
            "classification": classification,
            "files_latest": latest_files,
            "decreased_files": decreased_files,
        })

    # 정렬: 심각도 우선(increasing/new_recent → persistent 큰 순 → decreasing → resolved).
    order = {"increasing": 0, "new_recent": 1, "persistent": 2, "decreasing": 3, "resolved": 4, None: 5}
    rules_out.sort(key=lambda r: (order.get(r["classification"], 5), -(r["latest"] or 0), r["rule"]))
    rules_omitted = max(0, len(rules_out) - max_rules)
    rules_out = rules_out[:max_rules]

    summary: Dict[str, int] = {"resolved": 0, "decreasing": 0, "persistent": 0, "increasing": 0, "new_recent": 0}
    for r in rules_out:
        if r["classification"] in summary:
            summary[r["classification"]] += 1

    return {
        "ok": True,
        "available": True,
        "reason": None,
        "builds": builds,
        "builds_skipped": builds_skipped,
        "insufficient_data": insufficient,
        "rules": rules_out,
        "rules_omitted": rules_omitted,
        "residual": {"counts": per_build_residual, "note": "규칙 귀속 불가분(WorstRules 비상위) — 분류 제외"},
        "summary": summary,
        "cache": {"rcr_hits": rcr_hits, "rcr_misses": rcr_misses},
        "scope_note": "분류는 캐시된 빌드 구간 한정 관측",
    }
