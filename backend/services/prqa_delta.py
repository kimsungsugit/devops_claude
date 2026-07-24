"""빌드간 PRQA/Helix QAC 위반 delta — RCR 상세 디스크 캐시 + 쌍 비교(순수 계산).

프로젝트 요약탭 '빌드 드릴다운'의 데이터 레이어. analysis_summary.json의 prqa.rcr는
집계 kv뿐이라(파일×규칙 없음) 규칙 단위 delta는 빌드별 RCR HTML을
parse_prqa_rcr_details로 파싱해야 한다. BeautifulSoup 파싱은 빌드당 수 초라
(prqa-trend가 analysis_summary 직독으로 회피한 바로 그 비용) 파싱 결과를 빌드
report/ 하위 JSON으로 캐시한다. 캐시 키 = RCR 원본 {path, mtime_ns, size} +
PARSER_VERSION — 원본 교체·파서 개정 시 자동 무효화(결과 해시가 아니라 원본
시그니처 키: stale PASS 전례 참조 scripts/quality_check.py).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.services.report_parsers import _job_slug_from_dir, parse_prqa_rcr_details

logger = logging.getLogger(__name__)

RCR_DETAILS_CACHE_NAME = "prqa_rcr_details_cache.json"
# parse_prqa_rcr_details 출력 규약(키/규칙 분해 방식)이 바뀌면 +1 — 기존 캐시 전면 무효화.
PARSER_VERSION = 1
# report_parsers.parse_prqa_rcr_details가 WorstRules 미포함 잔여 위반에 붙이는 라벨.
RESIDUAL_RULE_LABEL = "기타 규칙 (비상위)"
# delta 계산 시 위반 상세를 절단하지 않기 위한 사실상 무제한 캡(기본 60은 표시용 절단).
_DELTA_MAX_FILES = 100000


def find_latest_rcr_html(build_root: Optional[Path], reports_dir: Optional[Path]) -> Optional[Path]:
    """RCR HTML 후보를 reports_dir(rglob) + 빌드 루트(직하 glob)에서 모아 mtime 최신 선택.

    report_parsers.build_report_summary와 동일 규약 — 일부 잡(KJPDS02_*)은 RCR을
    report/ 하위가 아니라 빌드 루트에 둔다. mtime 선택은 파일명 날짜 토큰(DDMMYYYY,
    사전순≠시간순)이나 stale 사본에 오도되지 않는다.
    """
    cands: List[Path] = []
    try:
        if reports_dir and reports_dir.is_dir():
            cands.extend(p for p in reports_dir.rglob("*_RCR_*.html") if p.is_file())
    except OSError:
        pass
    try:
        if build_root and build_root != reports_dir and build_root.is_dir():
            cands.extend(p for p in build_root.glob("*_RCR_*.html") if p.is_file())
    except OSError:
        pass
    if not cands:
        return None
    try:
        return max(cands, key=lambda c: c.stat().st_mtime_ns)
    except OSError:
        return None


def load_rcr_details_cached(
    build_root: Optional[Path], reports_dir: Optional[Path]
) -> Optional[Dict[str, Any]]:
    """빌드의 RCR 위반 상세를 디스크 캐시 경유로 로드.

    반환 {"details": …, "src": …, "cache_hit": bool} 또는 None(RCR 부재/파싱 실패).
    실패를 빈 details로 위장하지 않는다 — 호출측이 available:false + reason으로
    정직하게 응답해야 한다(침묵 0 금지). 캐시 쓰기 실패는 fail-soft(결과는 반환).
    """
    rcr = find_latest_rcr_html(build_root, reports_dir)
    if rcr is None or reports_dir is None:
        return None
    try:
        st = rcr.stat()
    except OSError:
        return None
    src = {
        "path": str(rcr),
        "mtime_ns": st.st_mtime_ns,
        "size": st.st_size,
        "parser_version": PARSER_VERSION,
    }
    cache_path = Path(reports_dir) / RCR_DETAILS_CACHE_NAME
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            isinstance(cached, dict)
            and cached.get("src") == src
            and isinstance(cached.get("details"), dict)
        ):
            return {"details": cached["details"], "src": src, "cache_hit": True}
    except (OSError, ValueError):
        pass  # 캐시 부재/손상 → 재파싱

    details = parse_prqa_rcr_details(
        rcr, top_n=20, job_slug=_job_slug_from_dir(Path(reports_dir)), max_files=_DELTA_MAX_FILES
    )
    if not isinstance(details, dict) or details.get("error"):
        return None
    try:
        # tmp+replace 원자 쓰기 — writer별 유니크 tmp(고정 tmp는 동시 writer 인터리브로
        # garbage가 rename될 수 있음 — 통합 deep-review W1과 동일 패턴 정리).
        import uuid as _uuid

        tmp = cache_path.with_name(f"{cache_path.name}.{_uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(
            json.dumps({"src": src, "details": details}, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(cache_path)
    except OSError as exc:
        logger.debug("prqa delta cache write skipped (%s): %s", cache_path, exc)
    return {"details": details, "src": src, "cache_hit": False}


def rule_totals_from_details(details: Dict[str, Any]) -> Tuple[Dict[str, int], int]:
    """violations_by_file 전체에서 규칙별 위반 총계 + residual 총계를 분리 합산.

    top_rules(top_n 절단본)가 아니라 violations_by_file에서 합산해야 delta가 절단에
    오염되지 않는다. residual('기타 규칙 (비상위)')은 규칙 귀속 불가분이라 별도 반환 —
    규칙 delta에 섞으면 '특정 규칙이 늘/줄었다'는 허위 신호가 된다.
    """
    totals: Dict[str, int] = {}
    residual_total = 0
    for f in details.get("violations_by_file") or []:
        for r in (f or {}).get("rules") or []:
            try:
                cnt = int(r.get("count") or 0)
            except (TypeError, ValueError):
                continue
            if cnt <= 0:
                continue
            if r.get("residual"):
                residual_total += cnt
                continue
            rule = str(r.get("rule") or "").strip()
            if not rule:
                continue
            totals[rule] = totals.get(rule, 0) + cnt
    return totals, residual_total


def attributed_total(details: Dict[str, Any]) -> Optional[int]:
    """빌드의 파일 귀속 위반 총계 — FileStatus 합(권위) 우선, 부재 시 파일 total 합."""
    at = details.get("violations_attributed_total")
    if isinstance(at, int):
        return at
    vbf = details.get("violations_by_file") or []
    if not vbf:
        return None
    total = 0
    for f in vbf:
        try:
            total += int((f or {}).get("total") or 0)
        except (TypeError, ValueError):
            continue
    return total


def _file_map(details: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """violations_by_file → 조인 키(path 우선, 없으면 표시명) 맵.

    동일 basename이 다른 디렉토리에 존재할 수 있어(APP/config.c vs BOOT/config.c)
    path를 키로 잡는다 — parse_prqa_rcr_details의 오병합 방지 규약과 동일.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for f in details.get("violations_by_file") or []:
        if not isinstance(f, dict):
            continue
        key = str(f.get("path") or "").strip() or str(f.get("file") or "").strip()
        if not key:
            continue
        rules: Dict[str, int] = {}
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
        try:
            total = int(f.get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        out[key] = {
            "file": str(f.get("file") or "").strip() or key,
            "path": str(f.get("path") or "").strip(),
            "total": total,
            "rules": rules,
        }
    return out


def compute_prqa_pair_delta(
    cur: Dict[str, Any], base: Dict[str, Any], *, max_files: int = 200
) -> Dict[str, Any]:
    """두 빌드의 RCR 상세를 조인해 규칙/파일 delta를 낸다(순수 계산 — IO 없음).

    규칙 4분류(new/resolved/increased/decreased) + residual_delta(귀속 불가분 몫),
    파일별 delta(총계·규칙 구성 변화가 있는 파일만, |delta| 내림차순, max_files 상한).
    """
    cur_rules, cur_res = rule_totals_from_details(cur)
    base_rules, base_res = rule_totals_from_details(base)

    new = [
        {"rule": r, "count": c} for r, c in cur_rules.items() if r not in base_rules
    ]
    resolved = [
        {"rule": r, "count_was": c} for r, c in base_rules.items() if r not in cur_rules
    ]
    increased: List[Dict[str, Any]] = []
    decreased: List[Dict[str, Any]] = []
    for rule in cur_rules.keys() & base_rules.keys():
        d = cur_rules[rule] - base_rules[rule]
        if d > 0:
            increased.append({"rule": rule, "base": base_rules[rule], "cur": cur_rules[rule], "delta": d})
        elif d < 0:
            decreased.append({"rule": rule, "base": base_rules[rule], "cur": cur_rules[rule], "delta": d})
    new.sort(key=lambda x: (-x["count"], x["rule"]))
    resolved.sort(key=lambda x: (-x["count_was"], x["rule"]))
    increased.sort(key=lambda x: (-x["delta"], x["rule"]))
    decreased.sort(key=lambda x: (x["delta"], x["rule"]))

    cur_files = _file_map(cur)
    base_files = _file_map(base)
    files: List[Dict[str, Any]] = []
    for key in cur_files.keys() | base_files.keys():
        c = cur_files.get(key)
        b = base_files.get(key)
        c_total = c["total"] if c else 0
        b_total = b["total"] if b else 0
        c_rules = c["rules"] if c else {}
        b_rules = b["rules"] if b else {}
        rule_deltas: List[Dict[str, Any]] = []
        for rule in c_rules.keys() | b_rules.keys():
            d = c_rules.get(rule, 0) - b_rules.get(rule, 0)
            if d != 0:
                rule_deltas.append(
                    {"rule": rule, "base": b_rules.get(rule, 0), "cur": c_rules.get(rule, 0), "delta": d}
                )
        # 총계 무변화 + 규칙 구성 무변화 파일은 노이즈 — 제외. 규칙 스왑(+A/−B, 총계 0)은 유지.
        if c_total == b_total and not rule_deltas:
            continue
        rule_deltas.sort(key=lambda x: (-abs(x["delta"]), x["rule"]))
        src = c or b or {}
        files.append(
            {
                "file": src.get("file") or key,
                "path": src.get("path") or "",
                "base": b_total,
                "cur": c_total,
                "delta": c_total - b_total,
                "rules": rule_deltas,
            }
        )
    files.sort(key=lambda f: (-abs(f["delta"]), f["file"]))
    files_omitted = max(0, len(files) - max_files)
    files = files[:max_files]

    cur_total = attributed_total(cur)
    base_total = attributed_total(base)
    return {
        "basis": "worstrules_matrix",  # 규칙 분해는 WorstRules(최다 위반 규칙) 부분집합 기반
        "totals": {
            "cur": cur_total,
            "base": base_total,
            "delta": (cur_total - base_total) if (cur_total is not None and base_total is not None) else None,
        },
        "rules": {
            "new": new,
            "resolved": resolved,
            "increased": increased,
            "decreased": decreased,
            "residual_delta": cur_res - base_res,
        },
        "files": files,
        "files_omitted": files_omitted,
    }


def _norm_path(p: str) -> str:
    s = str(p or "").replace("\\", "/").strip().lower()
    # RCR 경로는 리포트 기준 상대(../src/foo.c)가 흔하다 — 선행 ./ ../ 를 벗겨야
    # 저장소 기준 changed_files와 suffix 관계가 성립한다.
    while s.startswith("./") or s.startswith("../"):
        s = s[2:] if s.startswith("./") else s[3:]
    return s.strip("/")


def _suffix_match(a: str, b: str) -> bool:
    """경로 두 개가 세그먼트 경계 기준 suffix 관계인지 — basename 단독 오매칭 방지.

    RCR 경로(툴 기준 상대)와 SCM changed_files(저장소 기준)는 루트가 달라 완전 일치가
    불가능하다. 'x_foo.c'.endswith('foo.c') 같은 오매칭은 '/' 경계 확인으로 차단.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    longer, shorter = (a, b) if len(a) > len(b) else (b, a)
    return longer.endswith(shorter) and longer[-len(shorter) - 1] == "/"


def apply_changed_file_signals(
    delta_files: List[Dict[str, Any]], changed_files: List[str]
) -> List[Dict[str, Any]]:
    """delta 파일에 in_changed_set 플래그를 부여하고 '변경 파일 위반 증가' 신호를 만든다.

    changed_files가 확보된 경우에만 호출할 것 — 부재 시 플래그 자체를 붙이지 않아
    '변경 안 됨(false)'으로 위장하지 않는다(증거부재≠부정). delta_files는 제자리 갱신.
    """
    normalized_changed = [_norm_path(c) for c in changed_files if str(c or "").strip()]
    signals: List[Dict[str, Any]] = []
    for f in delta_files:
        target = _norm_path(f.get("path") or f.get("file") or "")
        matched = any(_suffix_match(target, ch) for ch in normalized_changed)
        f["in_changed_set"] = matched
        if matched and (f.get("delta") or 0) > 0:
            top_rules = [r["rule"] for r in (f.get("rules") or []) if (r.get("delta") or 0) > 0][:3]
            signals.append(
                {
                    "type": "changed_file_violation_increase",
                    "file": f.get("path") or f.get("file"),
                    "delta": f["delta"],
                    "rules": top_rules,
                }
            )
    signals.sort(key=lambda s: -s["delta"])
    return signals
