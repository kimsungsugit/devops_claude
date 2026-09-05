"""PRQA 룰 다빌드 트렌드 — 규칙×빌드 위반 매트릭스 + 분류(감소/지속/증가/해소/신규).

요약탭 "룰 인텔리전스"의 결정론 코어. 빌드별 규칙 카운트는 prqa_delta의 RCR 디스크
캐시(load_rcr_details_cached — 빌드당 파싱 1회화)를 재사용하므로 2회차 호출부터는
JSON 로드 N번 + 산술뿐이다(응답 cache에 히트/미스 가시화).

정직성 규약:
- RCR 없는 빌드의 카운트 자리는 **null**(0 금지 — '위반 0'과 '측정 없음'은 다르다).
- **규칙셋에 없던/비활성이던 빌드도 null**(0 금지) — 실측 KJPDS02_PV #120에서 규칙이
  111→253개로 확장되며 Secure C(C-POS/C-INT/C-DCI) 6종이 '신규 발생'으로 오분류됐다.
  '검사하지 않음'을 '위반 0'으로 적으면 규칙셋 확장이 코드 악화로 보고된다. 단 카운트가
  0보다 크면 RCFInfo 기재 여부와 무관하게 적용된 것(위반이 곧 증거)이므로 그대로 둔다.
- analyzed(RCR 보유) 빌드가 2개 미만이면 분류하지 않는다(insufficient_data) —
  단일 관측으로 추세를 단정하지 않는다.
- residual('기타 규칙 (비상위)')은 규칙 귀속 불가분 — 분류에서 제외하고 별도 시리즈로.
- 분류는 관측 범위(캐시된 빌드) 한정 — '전체 이력'을 주장하지 않는다.
- 파일별 증거는 **변화가 실제 일어난 인접 구간**(decrease_window / increase_window)에서
  뽑는다. 관측 구간 전체(first→latest)만 보면 중간에 해소된 규칙(실측 C-MSC-009:
  #122→#123에 2→0)이 first=0이라 후보에서 사라지고, 증가 규칙 안의 감소 파일(Rule-2.2:
  ApiIn_LinRxComp 14→12)도 통째로 누락된다.
- RCMA류 pseudo 엔트리(FileStatus에 없는 모듈 간 분석 집계)는 파일이 아니다 —
  scope='cross_module'로 표시해 스냅샷 조회 대상에서 제외한다(과거엔 '스냅샷에서 파일을
  찾지 못했습니다'라는 오해 유발 메시지가 나왔다).
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
MAX_EVIDENCE_FILES = 10
# 소스 파일 확장자 — RCMA류 pseudo 엔트리(모듈 간 분석 집계) 판별용.
_SOURCE_EXTS = (".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".inc", ".ipp", ".cp")
CROSS_MODULE_NOTE = (
    "모듈 간 분석(RCMA) 집계는 특정 파일에 귀속되지 않아 파일 단위 스냅샷 증거를 만들 수 없습니다"
)


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


def rule_file_index(files: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
    """path→{rule:count} 를 rule→{path:count} 로 역전.

    구간 탐색이 규칙별로 파일을 훑으므로 역인덱스가 없으면 O(규칙수 × 구간수 × 전체파일수)
    가 된다. 역전은 빌드당 1회 O(위반항목수)라 저렴하고, 이후 순회는 '그 규칙에 위반이 있는
    파일'로 한정된다.
    """
    out: Dict[str, Dict[str, int]] = {}
    for path, rc in files.items():
        for rule, cnt in rc.items():
            if cnt > 0:
                out.setdefault(rule, {})[path] = cnt
    return out


def _file_deltas(
    idx_from: Optional[Dict[str, int]], idx_to: Optional[Dict[str, int]],
    window: Dict[str, Any], *, direction: str, pseudo: set,
) -> List[Dict[str, Any]]:
    """구간 양끝의 (그 규칙) 파일별 카운트를 비교해 감소('down')/증가('up') 목록을 만든다.

    합집합 키를 순회한다 — from에만/to에만 있는 파일(위반이 사라진 파일, 새로 생긴 파일)이
    한쪽 dict 순회로는 누락된다. scope='cross_module'은 스냅샷 조회 대상이 아님을 프론트에
    알리는 표시(RCMA류).
    """
    a = idx_from or {}
    b = idx_to or {}
    out: List[Dict[str, Any]] = []
    for path in set(a) | set(b):
        before = a.get(path, 0)
        after = b.get(path, 0)
        if direction == "down" and before <= after:
            continue
        if direction == "up" and after <= before:
            continue
        entry: Dict[str, Any] = {
            "path": path, "from_build": window["from_build"], "to_build": window["to_build"],
            "delta": after - before, "count_from": before, "count_to": after,
        }
        if path in pseudo or (not path.strip()):
            entry["scope"] = "cross_module"
        out.append(entry)
    # 변화량이 큰 것 먼저(감소는 음수라 오름차순, 증가는 내림차순).
    out.sort(key=lambda f: (f["delta"], f["path"]) if direction == "down" else (-f["delta"], f["path"]))
    return out[:MAX_EVIDENCE_FILES]


def _best_change_window(
    counts: List[Optional[int]], builds: List[Dict[str, Any]],
    per_build_rule_idx: List[Optional[Dict[str, Dict[str, int]]]], rule: str,
    *, direction: str, pseudo: set, prefer_onset: bool = False,
) -> tuple:
    """**파일 단위 변화량이 가장 큰** 인접 관측 구간과 그 파일 목록을 반환.

    규칙 총계 delta로 구간을 고르면 안 된다 — 총계가 늘거나 그대로인 구간에도 줄어든 파일이
    있고(파일 A −2, 파일 B +5 → 총계 +3), 그 감소가 곧 "위반하지 않는 작성" 예시의 근거다.
    null(미분석·규칙 미적용) 자리는 건너뛰어 관측끼리 잇는다. tie는 최신 구간 우선(>=).
    prefer_onset이면 0→>0 최초 구간만 후보로 둔다(신규 발생의 관심사는 '언제 처음 나타났나').
    """
    obs = [i for i, c in enumerate(counts) if c is not None]
    pairs = list(zip(obs, obs[1:]))
    if prefer_onset and direction == "up":
        onset = next((p for p in pairs if counts[p[0]] == 0 and (counts[p[1]] or 0) > 0), None)
        if onset is not None:
            pairs = [onset]
    best_win: Optional[Dict[str, Any]] = None
    best_files: List[Dict[str, Any]] = []
    best_mag = 0
    for a, b in pairs:
        idx_a = (per_build_rule_idx[a] or {}).get(rule)
        idx_b = (per_build_rule_idx[b] or {}).get(rule)
        win = {
            "from_build": builds[a]["build_number"], "to_build": builds[b]["build_number"],
            "from_index": a, "to_index": b,
            "delta": (counts[b] or 0) - (counts[a] or 0),
        }
        files = _file_deltas(idx_a, idx_b, win, direction=direction, pseudo=pseudo)
        mag = sum(abs(f["delta"]) for f in files)
        if mag > 0 and mag >= best_mag:
            # file_delta = 이 목록의 합(규칙 총계 delta와 다를 수 있다 — 양방향 혼재 구간).
            win["file_delta"] = sum(f["delta"] for f in files)
            best_win, best_files, best_mag = win, files, mag
    return best_win, best_files


def is_cross_module_key(key: str) -> bool:
    """파일 귀속 불가 pseudo 엔트리(RCMA 등)의 표시 키인가 — 소스 확장자가 없으면 그렇다.

    엔드포인트는 프론트가 되돌려 보낸 표시 키만 받으므로(원본 details 없이) 이 문자열
    판정으로 스냅샷 조회를 건너뛴다. details가 있으면 `cross_module_keys()`가 더 정확하다.
    """
    k = str(key or "").strip().lower()
    return bool(k) and not k.endswith(_SOURCE_EXTS)


def cross_module_keys(details: Dict[str, Any]) -> set:
    """violations_by_file 중 파일 귀속 불가 엔트리의 표시 키 집합.

    report_parsers는 FileStatus에 없는 WorstRules 전용 행(RCMA류)을 path='' + file=표시명
    으로 담는다 — path가 비어 있고 표시명에 소스 확장자도 없으면 pseudo로 판정한다
    (경로 정규화 실패로 path가 빈 실제 파일은 표시명에 확장자가 남아 제외된다).
    """
    out: set = set()
    for f in details.get("violations_by_file") or []:
        if not isinstance(f, dict):
            continue
        if str(f.get("path") or "").strip():
            continue
        name = str(f.get("file") or "").strip()
        if name and is_cross_module_key(name):
            out.add(name)
    return out


def rules_applied_in_build(details: Dict[str, Any]) -> Optional[set]:
    """그 빌드에서 **검사가 적용된** 규칙 집합(RCFInfo enabled). 판정 불가면 None.

    RCFInfo 부재(구형 리포트)는 None — 호출측은 이때 카운트 0을 그대로 0으로 둔다
    (판정 근거가 없을 때 null을 남발하면 멀쩡한 '위반 0'이 '미측정'으로 위장된다).
    enabled 키가 없는 항목은 적용으로 간주(보수적).
    """
    descs = details.get("rule_descriptions")
    if not isinstance(descs, dict) or not descs:
        return None
    return {
        str(k) for k, v in descs.items()
        if not isinstance(v, dict) or v.get("enabled") is not False
    }


def file_rule_counts(details: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """violations_by_file → {path(또는 표시명): {rule: count}} (residual 제외).

    public: rule-unresolved-evidence 엔드포인트가 (rule, file) 구간 카운트 산출에 재사용.
    """
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
    # 파일 귀속은 rule→{path:count} 역인덱스로만 보관한다 — path→{rule:count} 원본까지 같이
    # 들고 있으면 대형 리포트(파일 수천 × 규칙)에서 같은 데이터를 두 벌 쥐게 된다.
    per_build_rule_idx: List[Optional[Dict[str, Dict[str, int]]]] = []
    per_build_applied: List[Optional[set]] = []             # 빌드별 검사 적용 규칙(RCFInfo) 또는 None
    pseudo_keys: set = set()                                 # RCMA류 — 파일 귀속 불가 표시 키
    rcr_hits = 0
    rcr_misses = 0
    # 규칙 설명(RCFInfo) — 규칙 설정은 빌드마다 변할 수 있어 "설명을 가진 최신 analyzed 빌드"
    # 기준으로 채택하고 출처 빌드를 응답에 명시한다(구형 리포트는 RCFInfo 자체가 없을 수 있음).
    rule_descriptions: Dict[str, Dict[str, Any]] = {}
    descriptions_build: Optional[int] = None

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
            per_build_rule_idx.append(None)
            per_build_applied.append(None)
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
        per_build_rule_idx.append(rule_file_index(file_rule_counts(loaded["details"])))
        per_build_applied.append(rules_applied_in_build(loaded["details"]))
        pseudo_keys |= cross_module_keys(loaded["details"])
        descs = loaded["details"].get("rule_descriptions")
        if isinstance(descs, dict) and descs:
            rule_descriptions = descs  # 오름차순 순회 — 마지막 대입이 곧 최신 analyzed
            descriptions_build = num

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
    # 최초/최신 analyzed 인덱스는 규칙과 무관 — 루프 밖에서 1회 계산(J2 구간 증거의 from/to 쌍).
    g_last_idx = max((i for i, t in enumerate(per_build_totals) if t is not None), default=None)
    g_first_idx = min((i for i, t in enumerate(per_build_totals) if t is not None), default=None)
    rules_out: List[Dict[str, Any]] = []
    for rule in all_rules:
        # 카운트 0은 두 가지다: '검사했고 위반 없음'(0) vs '그 빌드에서 검사 안 함'(null).
        # RCFInfo로 판정하고, 카운트가 0보다 크면 위반 자체가 적용 증거이므로 그대로 둔다.
        counts: List[Optional[int]] = []
        for totals_b, applied in zip(per_build_totals, per_build_applied):
            if totals_b is None:
                counts.append(None)
                continue
            cnt = totals_b.get(rule, 0)
            if cnt == 0 and applied is not None and rule not in applied:
                counts.append(None)
                continue
            counts.append(cnt)
        observed = [c for c in counts if c is not None]
        latest = observed[-1] if observed else None
        first = observed[0] if observed else None
        if not observed or all(c == 0 for c in observed):
            continue  # 관측이 전부 0(또는 관측 자체가 없음) — 표시 가치 없음
        classification = None if insufficient else _classify(counts)
        # 관측 1개(규칙이 이 구간 중간에 적용 시작)는 분류하지 않되 **드랍하지도 않는다** —
        # 위반이 있는데 표에서 사라지면 침묵 손실이다. 사유를 명시해 '분류 없음'을 설명한다.
        classification_reason = (
            "insufficient_observations" if classification is None and len(observed) < 2 else None
        )
        obs_idx = [i for i, c in enumerate(counts) if c is not None]
        rule_first_idx = obs_idx[0] if obs_idx else None
        latest_files: List[Dict[str, Any]] = []
        last_idx = g_last_idx
        if last_idx is not None and per_build_rule_idx[last_idx]:
            # 역인덱스는 count>0만 담으므로 필터가 따로 필요 없다.
            pairs = sorted(
                ((per_build_rule_idx[last_idx] or {}).get(rule) or {}).items(),
                key=lambda kv: (-kv[1], kv[0]),
            )
            latest_files = [
                {"path": p, "count": c, **({"scope": "cross_module"} if p in pseudo_keys else {})}
                for p, c in pairs[:8]  # J2: 5→8
            ]
        # 감소/증가 파일은 **분류와 무관하게** 실제 변화 구간에서 뽑는다 — 총량이 늘거나 그대로인
        # 규칙 안에도 줄어든 파일이 있고(실측 Rule-2.2 ApiIn_LinRxComp 14→12), 그것이 곧
        # "위반하지 않는 작성" 예시의 근거다.
        dec_win, decreased_files = _best_change_window(
            counts, builds, per_build_rule_idx, rule, direction="down", pseudo=pseudo_keys,
        )
        inc_win, increased_files = _best_change_window(
            counts, builds, per_build_rule_idx, rule, direction="up", pseudo=pseudo_keys,
            prefer_onset=classification == "new_recent",
        )
        rules_out.append({
            "rule": rule,
            "counts": counts,
            "latest": latest,
            "first": first,
            "net": (latest - first) if (latest is not None and first is not None) else None,
            "classification": classification,
            "classification_reason": classification_reason,
            "description": rule_descriptions.get(rule),  # {title, enabled, group} 또는 None
            "files_latest": latest_files,
            "decreased_files": decreased_files,
            "increased_files": increased_files,
            "decrease_window": dec_win,
            "increase_window": inc_win,
            # 규칙이 관측 구간 도중 적용 시작됐으면(규칙셋 확장) 그 빌드를 명시 — '신규 발생'과
            # '규칙 신규 적용'을 사용자가 구분할 수 있어야 한다.
            "applied_from_build": (
                builds[rule_first_idx]["build_number"] if rule_first_idx is not None else None
            ),
            "scope_narrowed": bool(
                rule_first_idx is not None and g_first_idx is not None and rule_first_idx != g_first_idx
            ),
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
        "descriptions_available": bool(rule_descriptions),
        "descriptions_source_build": descriptions_build,
        # 관측 구간(최초↔최신 analyzed 빌드) — 미해소 규칙의 구간 증거(from/to) 호출용.
        "observed_range": (
            {
                "from_build": builds[g_first_idx]["build_number"],
                "to_build": builds[g_last_idx]["build_number"],
            }
            if g_first_idx is not None and g_last_idx is not None
            else None
        ),
        "residual": {"counts": per_build_residual, "note": "규칙 귀속 불가분(WorstRules 비상위) — 분류 제외"},
        "summary": summary,
        "cache": {"rcr_hits": rcr_hits, "rcr_misses": rcr_misses},
        "scope_note": "분류는 캐시된 빌드 구간 한정 관측",
        # 파일 귀속 불가 pseudo 엔트리(RCMA류) — 프론트가 스냅샷 증거 버튼을 감추는 근거.
        "cross_module_keys": sorted(pseudo_keys),
        "cross_module_note": CROSS_MODULE_NOTE,
        # 규칙 미적용 빌드를 null로 둔 근거(0 위장 금지) — 규칙셋 변동 가시화.
        "ruleset_sizes": [
            (len(a) if a is not None else None) for a in per_build_applied
        ],
    }
