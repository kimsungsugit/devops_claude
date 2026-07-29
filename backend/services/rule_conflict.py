"""룰 상충 후보 — "이 규칙을 고치면 저 규칙에 걸린다"의 결정론 산출(LLM 0회).

요약탭 소스코드 서브탭 "룰 상충·판단 지점"의 코어. 새 파싱·새 IO를 만들지 않고
기존 산출물만 결합한다: RCR 디스크캐시(prqa_delta) · 룰 트렌드(prqa_rule_trend) ·
HMR 함수 메트릭(his_metric_delta) · 큐레이션 지식 테이블(config/misra_rule_conflicts.json).

**왜 지식 테이블이 필요한가 — 실측 근거.** 빌드 구간에서 '규칙 A 감소 · 규칙 B 증가'가
같은 파일에 동시에 난 사례는 캐시된 17개 빌드에서 **0건**이었다(변화가 난 6구간 중
대부분이 코드 변경이 아니라 규칙셋 on/off였다). 구간 delta만으로는 상충을 찾을 수 없다.
그래서 근거를 4단계로 나누고, 구간 실측(T1)은 최상위 등급에 자리만 두어 빌드가 쌓이면
자동으로 채워지게 한다.

증거 등급(tier) — 강→약:
  window          같은 파일 × 같은 구간에서 A↓·B↑ (실측)
  cooccurrence    같은 파일에 A·B가 함께 위반 중 (실측)
  metric_headroom 그 수정이 밀어올릴 HIS 메트릭이 밴드 경계에 붙은 함수 존재 (실측)
  ruleset_active  상대 규칙이 활성이나 현재 위반 0 — 예고

정직성 규약:
- **상대 규칙이 규칙셋에 없거나 비활성이면 후보에서 제외한다.** 그 규칙으로는 걸릴 수
  없으므로 경고 자체가 헛것이다. 제외 사유는 버리지 않고 risk_filtered로 돌려준다.
- **RCFInfo가 없는 빌드는 활성 판정 자체가 불가**하다 → 제외가 아니라 ruleset_unknown
  으로 표시하고 tier를 강등한다. 증거 부재를 '위험 없음'으로 읽히게 하지 않는다.
- 상충은 가능성이지 인과·확정 판정이 아니다 — CONFLICT_NOTE를 서버가 고정 주입한다.
- 지식 테이블은 도구 산출물이 아니라 사람이 정리한 지식이다. 파일의 source_note를
  그대로 실어 보내 그 경계를 화면에서도 유지한다.
- 테이블 부재·손상은 available:false + reason (빈 목록을 '상충 없음'으로 위장 금지).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.services.build_inventory import find_build_meta, list_cached_builds_meta
from backend.services.his_metric_delta import METRIC_LABEL, _resolve_file_key, band_verdict, load_his_metrics_cached
from backend.services.prqa_delta import load_rcr_details_cached
from backend.services.prqa_rule_trend import (
    compute_rule_trend,
    cross_module_keys,
    file_rule_counts,
    is_cross_module_key,
    rules_applied_in_build,
)

logger = logging.getLogger(__name__)

CONFLICT_TABLE_NAME = "misra_rule_conflicts.json"
DEFAULT_MAX_CONFLICTS = 40
MAX_EVIDENCE_PER_KIND = 6
# 자동 생성 마커 확인은 파일을 열어야 한다 — 경로로 이미 판정된 건 건너뛰고 나머지만, 상한 내에서.
MAX_MARKER_PROBES = 20
MARKER_HEAD_BYTES = 800

CONFLICT_NOTE = (
    "상충 후보는 큐레이션된 규칙 지식과 이 빌드의 관측(동시 위반·메트릭 여유)을 결합한 "
    "가능성이며, 그 위반이 실제로 발생한다는 판정이 아닙니다. 상대 규칙이 규칙셋에 없거나 "
    "비활성이면 후보에서 제외됩니다 — 규칙 설정(RCFInfo)을 읽을 수 없는 빌드는 그 판정 "
    "자체가 불가하므로 별도 표시합니다."
)

TIER_ORDER: Dict[str, int] = {
    "window": 0, "cooccurrence": 1, "metric_headroom": 2, "ruleset_active": 3, "ruleset_unknown": 4,
}
TIER_NOTE: Dict[str, str] = {
    "window": "이 구간에서 한 규칙이 줄고 다른 규칙이 같은 파일에서 늘었습니다 — 관측이지 인과가 아닙니다",
    "cooccurrence": "두 규칙이 같은 파일에서 함께 위반 중입니다 — 한쪽 수정이 다른 쪽 코드를 건드릴 위치입니다",
    "metric_headroom": "이 수정이 밀어올리는 메트릭이 밴드 경계에 붙은 함수가 있습니다",
    "ruleset_active": "상대 규칙이 활성이나 현재 위반은 없습니다 — 수정 시 새로 발생할 수 있습니다",
    # 실측 증거도 없고 규칙 설정도 못 읽은 상태 — '활성'이라 부르면 거짓이 된다.
    "ruleset_unknown": "이 빌드의 규칙 설정(RCFInfo)이 없어 상대 규칙이 검사되는지 확인하지 못했습니다",
}

# 규칙 ID 표기 흡수 — 'Rule 10.4' / 'Rule-10.4' / 'MISRA 10.4' / 'M3CM Rule-10.4' / '10.4'.
_RULE_NUM_RE = re.compile(r"(?:^|[\s\-_])(?:rule[\s\-_]*)?(\d{1,2})\.(\d{1,2})\s*$", re.I)

# 자동 생성 코드 판별 — ① 경로 세그먼트 ② 파일명 ③ 파일 머리의 생성 마커.
_GENERATED_SEGMENTS = {"generated_code", "generated", "autogen", "auto_generated", "gen"}
_GENERATED_NAME_RE = re.compile(r"(_cfg|_gen|_generated)\.[ch]$", re.I)
_GENERATED_MARKER_RE = re.compile(
    r"auto[-\s]?generat|generated\s+by|do\s+not\s+(edit|modify|change)|자동\s*생성", re.I
)


def normalize_rule_id(raw: Any) -> str:
    """규칙 ID 표기 정규화 — 'Rule 10.4'·'MISRA 10.4'·'10.4' → 'Rule-10.4'.

    숫자.숫자 패턴이 아닌 ID(Secure C 'C-INT-002' 등)는 공백만 정리해 그대로 둔다 —
    억지로 Rule-* 로 접으면 다른 규칙 체계가 같은 키로 뭉개진다.
    """
    s = str(raw or "").strip()
    if not s:
        return ""
    m = _RULE_NUM_RE.search(s)
    if m:
        return f"Rule-{int(m.group(1))}.{int(m.group(2))}"
    return re.sub(r"\s+", " ", s)


def _table_path(base: Optional[Path] = None) -> Path:
    """지식 테이블 경로 — 저장소 루트의 config/ 하위."""
    if base is not None:
        return Path(base)
    return Path(__file__).resolve().parents[2] / "config" / CONFLICT_TABLE_NAME


# 프로세스 캐시: {경로: (mtime_ns, size, payload)} — 편집 즉시 반영(재기동 불필요).
_TABLE_CACHE: Dict[str, Tuple[int, int, Dict[str, Any]]] = {}


def load_conflict_table(path: Optional[Path] = None) -> Dict[str, Any]:
    """상충 지식 테이블 로드. 부재·손상은 available:false + reason(빈 목록 위장 금지).

    mtime+size 시그니처 캐시 — config/swut_meta.json 과 같은 규약(파일을 고치면 다음
    호출에 바로 반영되고, 안 고치면 JSON 파싱이 반복되지 않는다).
    """
    p = _table_path(path)
    key = str(p)
    try:
        st = p.stat()
    except OSError:
        return {"available": False, "reason": "table_missing", "conflicts": [], "rule_categories": {}}
    hit = _TABLE_CACHE.get(key)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("rule conflict table 읽기 실패 (%s): %s", p, exc)
        return {"available": False, "reason": "table_unreadable", "conflicts": [], "rule_categories": {}}
    if not isinstance(data, dict) or not isinstance(data.get("conflicts"), list):
        return {"available": False, "reason": "table_invalid", "conflicts": [], "rule_categories": {}}

    categories = {
        normalize_rule_id(k): str(v)
        for k, v in (data.get("rule_categories") or {}).items()
        if normalize_rule_id(k)
    }
    entries: List[Dict[str, Any]] = []
    for raw in data["conflicts"]:
        if not isinstance(raw, dict) or not str(raw.get("id") or "").strip():
            continue
        fixing = [r for r in (normalize_rule_id(x) for x in raw.get("when_fixing") or []) if r]
        risky = [r for r in (normalize_rule_id(x) for x in raw.get("may_violate") or []) if r]
        if not fixing:
            continue  # 고칠 대상이 없는 항목은 후보를 만들 수 없다
        entries.append({
            "id": str(raw["id"]).strip(),
            "when_fixing": fixing,
            "may_violate": risky,
            "kind": str(raw.get("kind") or "fix_induces"),
            "mechanism": str(raw.get("mechanism") or ""),
            "resolutions": [str(x) for x in (raw.get("resolutions") or []) if str(x).strip()],
            "deviation_hint": str(raw.get("deviation_hint") or ""),
            "metric_risk": [str(x).strip() for x in (raw.get("metric_risk") or []) if str(x).strip()],
            "confidence": str(raw.get("confidence") or "low"),
            "refs": [str(x) for x in (raw.get("refs") or []) if str(x).strip()],
        })
    payload = {
        "available": True,
        "reason": None,
        "version": data.get("version"),
        "source_note": str(data.get("source_note") or ""),
        "category_note": str(data.get("category_note") or ""),
        "rule_categories": categories,
        "conflicts": entries,
    }
    _TABLE_CACHE[key] = (st.st_mtime_ns, st.st_size, payload)
    return payload


def clear_conflict_table_cache() -> None:
    """테이블 캐시 비우기 — 테스트에서 임시 파일을 갈아끼울 때 쓴다."""
    _TABLE_CACHE.clear()


def is_generated_path(path: str) -> bool:
    """경로만으로 자동 생성 코드인지 — 세그먼트·파일명 규칙(파일 IO 없음)."""
    s = str(path or "").replace("\\", "/").strip().lower()
    if not s:
        return False
    if any(seg in _GENERATED_SEGMENTS for seg in s.split("/") if seg):
        return True
    return bool(_GENERATED_NAME_RE.search(s.rsplit("/", 1)[-1]))


def _marker_in_snapshot(build_root: Optional[Path], path: str) -> bool:
    """스냅샷 파일 머리에 생성 마커가 있는지 — 경로로 판정 못 한 파일의 2차 확인."""
    if build_root is None:
        return False
    from backend.services.rule_fix_examples import resolve_snapshot_file

    resolved = resolve_snapshot_file(Path(build_root), path)
    if resolved is None:
        return False
    try:
        head = resolved.read_text(encoding="utf-8", errors="ignore")[:MARKER_HEAD_BYTES]
    except OSError:
        return False
    return bool(_GENERATED_MARKER_RE.search(head))


def _rule_meta(
    rule: str, descriptions: Dict[str, Any], categories: Dict[str, str], counts: Dict[str, int]
) -> Dict[str, Any]:
    desc = descriptions.get(rule) if isinstance(descriptions, dict) else None
    return {
        "rule": rule,
        "title": (desc or {}).get("title") if isinstance(desc, dict) else None,
        "group": (desc or {}).get("group") if isinstance(desc, dict) else None,
        "count": counts.get(rule, 0),
        "category": categories.get(rule),
    }


def _window_evidence(
    trend_rules: Dict[str, Dict[str, Any]], fixing: List[str], risky: List[str],
) -> List[Dict[str, Any]]:
    """T1 — 같은 파일 · 같은 구간에서 fixing 규칙이 줄고 risk 규칙이 늘어난 관측.

    트렌드가 규칙별로 이미 계산해 둔 decreased_files/increased_files 를 조인한다(추가 IO 0).
    구간(from_build,to_build)과 파일이 **둘 다** 같아야 한 사건으로 본다 — 파일만 같고
    구간이 다르면 서로 무관한 두 변화를 인과처럼 붙이는 셈이다.
    """
    out: List[Dict[str, Any]] = []
    for fr in fixing:
        down = (trend_rules.get(fr) or {}).get("decreased_files") or []
        if not down:
            continue
        down_idx = {(d.get("path"), d.get("from_build"), d.get("to_build")): d for d in down}
        for rr in risky:
            for up in (trend_rules.get(rr) or {}).get("increased_files") or []:
                hit = down_idx.get((up.get("path"), up.get("from_build"), up.get("to_build")))
                if hit is None:
                    continue
                out.append({
                    "file": up.get("path"),
                    "from_build": up.get("from_build"),
                    "to_build": up.get("to_build"),
                    "rule_down": fr, "delta_down": hit.get("delta"),
                    "rule_up": rr, "delta_up": up.get("delta"),
                    **({"scope": "cross_module"} if up.get("scope") == "cross_module" else {}),
                })
    out.sort(key=lambda e: (-(abs(e.get("delta_up") or 0) + abs(e.get("delta_down") or 0)), str(e.get("file"))))
    return out[:MAX_EVIDENCE_PER_KIND]


def _cooccurrence_evidence(
    per_file: Dict[str, Dict[str, int]], fixing: List[str], risky: List[str], pseudo: Set[str],
) -> List[Dict[str, Any]]:
    """T2 — 최신 빌드에서 fixing 규칙과 risk 규칙이 같은 파일에 함께 위반 중."""
    out: List[Dict[str, Any]] = []
    for path, rc in per_file.items():
        hit_fix = {r: rc[r] for r in fixing if rc.get(r, 0) > 0}
        hit_risk = {r: rc[r] for r in risky if rc.get(r, 0) > 0}
        if not hit_fix or not hit_risk:
            continue
        entry: Dict[str, Any] = {
            "file": path, "fixing_counts": hit_fix, "risk_counts": hit_risk,
            "total": sum(hit_fix.values()) + sum(hit_risk.values()),
        }
        if path in pseudo or is_cross_module_key(path):
            entry["scope"] = "cross_module"
        out.append(entry)
    out.sort(key=lambda e: (-int(e["total"]), str(e["file"])))
    return out[:MAX_EVIDENCE_PER_KIND]


def _headroom_evidence(
    functions: Dict[str, Dict[str, str]], files: List[str], metrics: List[str],
) -> List[Dict[str, Any]]:
    """T3 — metric_risk 메트릭이 **한 단계만 올라도 밴드가 나빠지는** 함수.

    "복잡도가 높다"가 아니라 "여유가 없다"를 본다. 이미 Fail인 함수는 더 나빠질 밴드가
    없어 여기 안 걸리지만, 그건 별도로 위험하므로 verdict를 실어 보낸다.
    """
    out: List[Dict[str, Any]] = []
    if not functions or not metrics:
        return out
    for f in files:
        keys, reason = _resolve_file_key(functions, f)
        if reason or not keys:
            continue
        for key in keys:
            vals = functions.get(key) or {}
            for metric in metrics:
                raw = vals.get(metric)
                if raw is None:
                    continue
                try:
                    value = int(str(raw).strip())
                except (TypeError, ValueError):
                    continue
                cur = band_verdict(metric, value)
                nxt = band_verdict(metric, value + 1)
                if cur is None or nxt is None or cur.get("verdict") == nxt.get("verdict"):
                    continue
                out.append({
                    "file": f,
                    "function": key.split("\x1f", 1)[1] if "\x1f" in key else key,
                    "metric": metric,
                    "label": METRIC_LABEL.get(metric, metric),
                    "value": value,
                    "st_id": cur.get("st_id"),
                    "band": cur.get("band"), "verdict": cur.get("verdict"),
                    "next_band": nxt.get("band"), "next_verdict": nxt.get("verdict"),
                })
    out.sort(key=lambda e: (str(e["file"]), str(e["function"]), str(e["metric"])))
    return out[:MAX_EVIDENCE_PER_KIND]


def _measurement_ambiguities(
    trend: Dict[str, Any], details: Dict[str, Any], per_file: Dict[str, Dict[str, int]],
    pseudo: Set[str], applied: Optional[Set[str]],
) -> List[Dict[str, Any]]:
    """측정 근거가 불확실한 지점 — 숫자를 그대로 믿으면 안 되는 곳들.

    실측에서 확인된 것들이다: 규칙셋 on/off가 만든 가짜 증감, 파일에 귀속되지 않는 위반,
    RCFInfo 부재로 인한 활성 판정 불가, 관측 1개 규칙, 규칙 귀속이 없는 residual.
    """
    out: List[Dict[str, Any]] = []
    builds = trend.get("builds") or []
    sizes = trend.get("ruleset_sizes") or []
    rules = trend.get("rules") or []

    # ① 규칙셋 크기가 변한 구간 — 그 구간의 증감은 코드 변화가 아닐 수 있다.
    # ⚠ **관측(non-None)끼리** 이어야 한다. 배열 인덱스로 바로 이웃을 비교하면 사이에 낀
    #    미분석 빌드(RCR 없음 → None)가 변화를 삼킨다 — 실측 KJPDS02_PV는 #116(104) →
    #    #117(미분석) → #120(242) 이라 단순 이웃 비교로는 규칙셋 2.3배 확장을 못 봤다.
    observed = [i for i, s in enumerate(sizes) if s is not None and i < len(builds)]
    for a_idx, b_idx in zip(observed, observed[1:]):
        a, b = sizes[a_idx], sizes[b_idx]
        if a == b:
            continue
        affected = [
            r["rule"] for r in rules
            if isinstance(r.get("counts"), list) and b_idx < len(r["counts"])
            and (r["counts"][a_idx] is None) != (r["counts"][b_idx] is None)
        ]
        out.append({
            "kind": "ruleset_change",
            "from_build": builds[a_idx].get("build_number"),
            "to_build": builds[b_idx].get("build_number"),
            "from_size": a, "to_size": b,
            "affected_rules": sorted(affected)[:12],
            "affected_total": len(affected),
            "detail": "규칙셋이 바뀐 구간입니다 — 이 구간의 위반 증감은 코드 변화가 아니라 검사 범위 변화일 수 있습니다.",
        })

    # ② 파일에 귀속되지 않는 위반(RCMA류) — 규칙별 비중이 큰 순.
    unattributed: Dict[str, int] = {}
    for path, rc in per_file.items():
        if not (path in pseudo or is_cross_module_key(path)):
            continue
        for rule, cnt in rc.items():
            unattributed[rule] = unattributed.get(rule, 0) + int(cnt)
    if unattributed:
        totals: Dict[str, int] = {}
        for rc in per_file.values():
            for rule, cnt in rc.items():
                totals[rule] = totals.get(rule, 0) + int(cnt)
        rows = sorted(unattributed.items(), key=lambda kv: (-kv[1], kv[0]))[:6]
        out.append({
            "kind": "unattributed",
            "rules": [
                {"rule": r, "unattributed": c, "total": totals.get(r, c)} for r, c in rows
            ],
            "detail": "이 위반들은 특정 파일에 귀속되지 않는 모듈 간 분석(RCMA) 집계입니다 — 파일 단위 조치 대상을 특정할 수 없습니다.",
        })

    # ③ RCFInfo 부재 — 활성/비활성 판정 자체가 불가(증거 부재 ≠ 위험 없음).
    if applied is None:
        out.append({
            "kind": "ruleset_unknown",
            "detail": "이 빌드의 RCR에 규칙 설정(RCFInfo)이 없어 어떤 규칙이 활성인지 판정할 수 없습니다 — 상충 후보의 '상대 규칙이 활성인가'를 확인하지 못한 상태입니다.",
        })

    # ④ 관측 1개 규칙 — 추세를 단정할 수 없다.
    single = [r["rule"] for r in rules if r.get("classification_reason") == "insufficient_observations"]
    if single:
        out.append({
            "kind": "single_observation",
            "rules": sorted(single)[:12], "total": len(single),
            "detail": "이 규칙들은 관측이 1개뿐이라 증가/감소를 판정하지 않았습니다.",
        })

    # ⑤ residual — 규칙 귀속이 없는 잔여 위반.
    residual_counts = (trend.get("residual") or {}).get("counts") or []
    latest_residual = next((c for c in reversed(residual_counts) if c is not None), None)
    if latest_residual:
        out.append({
            "kind": "residual", "count": latest_residual,
            "detail": "원본 리포트가 '상위 규칙'으로 분해하지 않은 잔여 위반입니다 — 어느 규칙인지 알 수 없어 상충 판정 대상에서 제외됩니다.",
        })

    # ⑥ 파일 총계와 규칙 분해 합의 차이 — 리포트 자체의 미귀속분.
    fs_total = details.get("filestatus_total_vc")
    attributed = details.get("violations_attributed_total")
    if isinstance(fs_total, int) and isinstance(attributed, int) and fs_total > attributed:
        out.append({
            "kind": "file_unattributed", "total": fs_total, "attributed": attributed,
            "gap": fs_total - attributed,
            "detail": "원본 QAC 리포트의 총 위반과 파일별 합계가 다릅니다 — 차이만큼은 파일에 귀속되지 않은 위반입니다.",
        })
    return out


def _generated_ambiguities(
    per_file: Dict[str, Dict[str, int]], pseudo: Set[str], build_root: Optional[Path],
) -> Tuple[List[Dict[str, Any]], int]:
    """자동 생성 코드의 위반 — 손댈 수 없는 파일과 조치 대상을 구분한다.

    반환 (목록, 마커 검사를 못 한 파일 수). 두 번째 값이 0이 아니면 목록이 완전하지
    않다 — 호출측이 그 사실을 응답에 실어야 한다(절단을 침묵시키지 않는다).
    """
    out: List[Dict[str, Any]] = []
    probes = 0
    unprobed = 0
    for path, rc in sorted(per_file.items()):
        if not rc or path in pseudo or is_cross_module_key(path):
            continue
        basis: Optional[str] = None
        if is_generated_path(path):
            basis = "path"
        elif probes < MAX_MARKER_PROBES:
            probes += 1
            if _marker_in_snapshot(build_root, path):
                basis = "marker"
        else:
            unprobed += 1  # 상한 초과 — 자동 생성일 수도 있으나 확인하지 못했다
        if basis is None:
            continue
        out.append({
            "file": path, "basis": basis,
            "violations": int(sum(rc.values())),
            "rules": sorted(rc.keys()),
        })
    out.sort(key=lambda e: (-int(e["violations"]), str(e["file"])))
    return out, unprobed


def compute_rule_conflicts(
    *, job_url: str, cache_root: Path, limit: int = 15,
    max_conflicts: int = DEFAULT_MAX_CONFLICTS, table_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """상충 후보 + 애매한 지점 산출(결정론). 실패는 available:false + reason."""
    table = load_conflict_table(table_path)
    trend = compute_rule_trend(job_url=job_url, cache_root=cache_root, limit=limit, max_rules=200)
    if not trend.get("available"):
        return {
            "ok": True, "available": False,
            "reason": trend.get("reason") or "no_cached_build",
            "table": {k: table.get(k) for k in ("available", "reason", "version", "source_note")},
        }
    if not table.get("available"):
        return {
            "ok": True, "available": False, "reason": table.get("reason") or "table_missing",
            "table": {k: table.get(k) for k in ("available", "reason", "version", "source_note")},
        }

    rng = trend.get("observed_range") or {}
    metas = list_cached_builds_meta(job_url=job_url, cache_root=cache_root)
    to_meta = find_build_meta(metas, rng.get("to_build"))
    build_root = Path(str(to_meta.get("build_root"))) if to_meta else None

    details: Dict[str, Any] = {}
    per_file: Dict[str, Dict[str, int]] = {}
    pseudo: Set[str] = set()
    applied: Optional[Set[str]] = None
    functions: Dict[str, Dict[str, str]] = {}
    # 최신 빌드의 RCR을 못 읽으면 위반 표가 통째로 비어 '상충 없음'처럼 보인다 — 그건
    # 좋은 소식이 아니라 측정 실패다. 사유를 따로 들고 나가 화면이 구분할 수 있게 한다.
    latest_rcr_reason: Optional[str] = None
    if to_meta is None:
        latest_rcr_reason = "latest_build_not_cached"
    else:
        loaded = load_rcr_details_cached(
            build_root, Path(str(to_meta.get("reports_dir") or ""))
        )
        if loaded is None:
            latest_rcr_reason = "latest_rcr_unreadable"
        else:
            details = loaded["details"]
            per_file = file_rule_counts(details)
            pseudo = cross_module_keys(details)
            applied = rules_applied_in_build(details)
        hmr = load_his_metrics_cached(build_root, Path(str(to_meta.get("reports_dir") or "")))
        if hmr is not None:
            functions = hmr.get("functions") or {}

    descriptions: Dict[str, Any] = details.get("rule_descriptions") or {}
    categories: Dict[str, str] = table.get("rule_categories") or {}
    trend_rules: Dict[str, Dict[str, Any]] = {r["rule"]: r for r in (trend.get("rules") or []) if r.get("rule")}
    # 규칙별 최신 위반 합(파일 분해 기준) — 트렌드 latest 와 달리 파일 귀속분만 센다.
    rule_totals: Dict[str, int] = {}
    for rc in per_file.values():
        for rule, cnt in rc.items():
            rule_totals[rule] = rule_totals.get(rule, 0) + int(cnt)

    def _violating(rule: str) -> int:
        """이 규칙의 현재 위반 수 — 파일 분해 우선, 없으면 트렌드 최신값."""
        if rule in rule_totals:
            return rule_totals[rule]
        latest = (trend_rules.get(rule) or {}).get("latest")
        return int(latest) if isinstance(latest, int) else 0

    def _active(rule: str) -> Optional[bool]:
        """규칙이 이 빌드에서 검사되는가 — 판정 불가면 None(RCFInfo 부재).

        ⚠ **위반이 1건이라도 있으면 적용된 것**이다(위반이 곧 검사의 증거). RCFInfo는
        빌드마다 있기도 없기도 하고 규칙셋 표기도 갈리는데, 카운트만으로 확실한 이 근거를
        무시하면 실제로 걸리고 있는 규칙을 '검사 안 함'으로 접어버린다 —
        prqa_rule_trend 가 카운트>0을 null 로 접지 않는 것과 같은 규약이다.
        """
        if _violating(rule) > 0:
            return True
        if applied is None:
            return None
        return rule in applied

    conflicts: List[Dict[str, Any]] = []
    # 후보가 통째로 빠진 사유 — 제외를 침묵시키면 "왜 이 상충은 안 보이나"에 답할 수 없다.
    # 위반이 없어 건너뛴 항목(대다수)은 개수만, 상대 규칙이 꺼져 성립하지 않는 항목은 목록으로.
    skipped_no_violation = 0
    excluded: List[Dict[str, Any]] = []
    for entry in table.get("conflicts") or []:
        # ① 고칠 대상: 실제로 위반이 있는 규칙만. 위반 0인 규칙을 '고칠 때'를 경고할 이유가 없다.
        fixing = [r for r in entry["when_fixing"] if _violating(r) > 0 and _active(r) is not False]
        if not fixing:
            skipped_no_violation += 1
            continue
        # ② 상대 규칙: 활성인 것만. 규칙셋에 없거나 비활성이면 그 규칙으로는 걸릴 수 없다.
        risky: List[str] = []
        filtered: List[Dict[str, str]] = []
        for r in entry["may_violate"]:
            state = _active(r)
            if state is False:
                filtered.append({"rule": r, "reason": "not_in_ruleset"})
            else:
                risky.append(r)
        if not risky and entry["kind"] != "process_tension":
            # 상대 규칙이 전부 걸러졌다 — 이 프로젝트에선 상충이 성립하지 않는다(좋은 소식이지만
            # 근거를 남긴다: 규칙 설정이 바뀌면 되살아나는 후보다).
            excluded.append({
                "id": entry["id"], "reason": "counterpart_inactive",
                "fixing": fixing, "inactive": [f["rule"] for f in filtered],
            })
            continue

        windows = _window_evidence(trend_rules, fixing, risky)
        cooc = _cooccurrence_evidence(per_file, fixing, risky, pseudo)
        fixing_files = [
            p for p, rc in per_file.items()
            if any(rc.get(r, 0) > 0 for r in fixing) and not (p in pseudo or is_cross_module_key(p))
        ]
        headroom = _headroom_evidence(functions, fixing_files, entry["metric_risk"])

        # 실측 증거(관측)는 RCFInfo 유무와 무관하게 유효하다 — 같은 파일에 두 규칙 위반이
        # 함께 있다는 건 그 자체로 사실이다. 반면 증거가 하나도 없을 때의 근거는 '상대 규칙이
        # 활성'뿐인데, RCFInfo가 없으면 그것조차 확인 못 한 것이므로 '활성'이라 부르면 거짓이다.
        if windows:
            tier = "window"
        elif cooc:
            tier = "cooccurrence"
        elif headroom:
            tier = "metric_headroom"
        elif applied is None:
            tier = "ruleset_unknown"
        else:
            tier = "ruleset_active"
        ruleset_unknown = applied is None

        conflicts.append({
            "id": entry["id"],
            "kind": entry["kind"],
            "tier": tier,
            "tier_note": TIER_NOTE.get(tier, ""),
            "ruleset_unknown": ruleset_unknown,
            "fixing": [_rule_meta(r, descriptions, categories, rule_totals) for r in fixing],
            "risk": [_rule_meta(r, descriptions, categories, rule_totals) for r in risky],
            "risk_filtered": filtered,
            "evidence": {"windows": windows, "cooccurrence": cooc, "metric_headroom": headroom},
            "mechanism": entry["mechanism"],
            "resolutions": entry["resolutions"],
            "deviation_hint": entry["deviation_hint"],
            "metric_risk": entry["metric_risk"],
            "confidence": entry["confidence"],
            "refs": entry["refs"],
            # 정렬·표시용 — 이 상충이 지금 얼마나 큰 덩어리인가.
            "fixing_violations": sum(_violating(r) for r in fixing),
        })

    conflicts.sort(key=lambda c: (
        TIER_ORDER.get(c["tier"], 9), -int(c["fixing_violations"]), c["id"],
    ))
    omitted = max(0, len(conflicts) - max_conflicts)
    conflicts = conflicts[:max_conflicts]

    by_rule: Dict[str, List[str]] = {}
    for c in conflicts:
        for meta in c["fixing"]:
            by_rule.setdefault(meta["rule"], []).append(c["id"])

    generated, generated_unprobed = _generated_ambiguities(per_file, pseudo, build_root)

    # 판단이 필요한 지점 = 실측 근거가 있는 후보(지금 당장 마주치는 것) 우선.
    judgement = [
        {
            "id": c["id"], "tier": c["tier"],
            "fixing": [m["rule"] for m in c["fixing"]],
            "risk": [m["rule"] for m in c["risk"]],
            "categories": sorted({m["category"] for m in c["fixing"] + c["risk"] if m.get("category")}),
            "kind": c["kind"],
            "confidence": c["confidence"],
        }
        for c in conflicts if c["tier"] in ("window", "cooccurrence")
    ]

    return {
        "ok": True,
        "available": True,
        "reason": None,
        "build_number": rng.get("to_build"),
        "note": CONFLICT_NOTE,
        "table": {
            "available": True, "reason": None,
            "version": table.get("version"),
            "source_note": table.get("source_note"),
            "category_note": table.get("category_note"),
            "total": len(table.get("conflicts") or []),
            # 대조 결과의 나머지 — 합이 total 이 되어야 표가 자립한다.
            "skipped_no_violation": skipped_no_violation,
            "excluded": excluded,
        },
        "ruleset": {
            "available": applied is not None,
            "enabled_count": len(applied) if applied is not None else None,
            "source_build": trend.get("descriptions_source_build"),
            # RCR 자체를 못 읽은 것과 RCR은 읽었으나 RCFInfo가 없는 것은 사유가 다르다 —
            # 전자를 'no_rcfinfo'로 적으면 리포트 부재가 규칙 설정 부재로 위장된다.
            "reason": None if applied is not None else (latest_rcr_reason or "no_rcfinfo"),
        },
        # 최신 빌드의 위반 표가 비어 있는 사유(측정 실패 vs 진짜 0) — null이면 정상 측정.
        "latest_rcr_reason": latest_rcr_reason,
        "conflicts": conflicts,
        "conflicts_omitted": omitted,
        "by_rule": by_rule,
        "ambiguities": {
            "conflict": judgement,
            "measurement": _measurement_ambiguities(trend, details, per_file, pseudo, applied),
            "generated": generated,
            # 마커 검사 상한에 걸려 확인하지 못한 파일 수 — 0이 아니면 목록이 완전하지 않다.
            "generated_unprobed": generated_unprobed,
        },
    }
