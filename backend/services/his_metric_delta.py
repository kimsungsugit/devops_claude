"""빌드간 **함수 단위** HIS 메트릭 delta — QAC HMR 파싱 디스크 캐시 + 쌍 비교(순수 계산).

## 왜 필요한가

RCR(Rule Compliance Report)은 **파일 × 규칙 카운트가 최상세**라 "이 파일 위반이 0→4"까지만
말할 수 있고 어느 함수·어느 줄인지 모른다. 그런데 같은 빌드 산출물에 있는 **HMR(HIS Metrics
Report)** 은 함수 단위다::

    <h3>File: .../Sys_UDS_LinComp_PDS.c</h3>
    <h4>Function: s_UDS_WDBI_ProcessTempOffsetTable()</h4>
      Metric | CALLS | v(G) | GOTO | RETURN | CALLING | LEVEL | PARAM | PATH | STMT
      Values |   4   |  7   |  0   |   1    |    0    |   4   |   0   |  11  |  26

그래서 두 축을 분리해 정직하게 답한다:

- **함수 단위 메트릭 변화** — 정확하다(추정 아님). 신규/삭제 함수, 메트릭 변경 함수,
  회사 ST201 밴드(Pass/Conditional/Fail) **교차**를 그대로 보고한다.
- **MISRA 규칙 위반의 함수 귀속** — RCR에 없다. 위 목록은 "이 구간에 실제로 바뀐 함수"일 뿐
  "이 함수가 그 규칙을 위반했다"가 아니다. 호출측이 note로 이 경계를 반드시 노출할 것.

## 재사용

파싱은 ``qac_parser.parse_qac_report``(기존 SwSA ST201 경로와 동일 파서), 밴드/판정은
``swsa_st201_binner.ST201_METRICS``(회사 양식 SSOT)를 그대로 쓴다 — 임계값을 여기서 새로
정의하지 않는다(이중 출처 금지). 밴드가 정의된 4종(V_G/LEVEL/CALLING/CALLS) 외 메트릭은
**판정 없이 값 변화만** 보고한다(없는 기준을 지어내지 않는다).

캐시 키 = HMR 원본 {path, mtime_ns, size} + PARSER_VERSION — prqa_delta와 동일 규약
(결과 해시가 아니라 원본 시그니처: stale PASS 전례 scripts/quality_check.py 참조).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.services.prqa_delta import _norm_path, _suffix_match
from backend.services.qac_parser import MatrixItem, parse_qac_report
from backend.services.swsa_st201_binner import ST201_METRICS

logger = logging.getLogger(__name__)

HIS_METRICS_CACHE_NAME = "his_metrics_cache.json"
# 캐시 payload 규약(키 형식/메트릭 집합)이 바뀌면 +1 — 기존 캐시 전면 무효화.
PARSER_VERSION = 1

# 보고 대상 메트릭 순서 — 표시 순서이자 delta 스캔 순서.
REPORT_ITEMS: Tuple[MatrixItem, ...] = (
    MatrixItem.V_G, MatrixItem.LEVEL, MatrixItem.CALLING, MatrixItem.CALLS,
    MatrixItem.PATH, MatrixItem.STMT, MatrixItem.PARAM, MatrixItem.RETURN, MatrixItem.GOTO,
)

# MatrixItem.name -> (st_id, 표시명, bands) — 회사 양식에 밴드가 정의된 4종만.
_BANDED: Dict[str, Tuple[str, str, List[Tuple[Optional[int], str, str]]]] = {
    item.name: (st_id, disp, bands)
    for st_id, (_code, item, disp, bands) in ST201_METRICS.items()
}

# 사용자 대면 메트릭 라벨 — HMR 헤더 표기(v(G)/LEVEL/…)를 그대로 쓴다.
METRIC_LABEL: Dict[str, str] = {
    "V_G": "v(G)", "LEVEL": "LEVEL", "CALLING": "CALLING", "CALLS": "CALLS",
    "PATH": "PATH", "STMT": "STMT", "PARAM": "PARAM", "RETURN": "RETURN", "GOTO": "GOTO",
}

ATTRIBUTION_NOTE = (
    "함수 목록은 이 구간에 실제로 바뀐 함수이며, 규칙 위반이 그 함수에서 났다는 판정이 "
    "아닙니다 — QAC RCR은 파일 단위라 규칙의 함수·줄 귀속 정보가 없습니다. "
    "메트릭 값과 밴드 판정만 함수 단위 실측입니다."
)


def find_latest_hmr_html(build_root: Optional[Path], reports_dir: Optional[Path]) -> Optional[Path]:
    """HMR HTML 후보를 reports_dir(rglob) + 빌드 루트(직하 glob)에서 모아 mtime 최신 선택.

    prqa_delta.find_latest_rcr_html과 동일 규약 — KJPDS02_* 는 리포트를 report/ 하위가
    아니라 빌드 루트에 둔다. 파일명 날짜 토큰(DDMMYYYY)은 사전순≠시간순이라 mtime 선택.
    """
    cands: List[Path] = []
    try:
        if reports_dir and reports_dir.is_dir():
            cands.extend(p for p in reports_dir.rglob("*_HMR_*.html") if p.is_file())
    except OSError:
        pass
    try:
        if build_root and build_root != reports_dir and build_root.is_dir():
            cands.extend(p for p in build_root.glob("*_HMR_*.html") if p.is_file())
    except OSError:
        pass
    if not cands:
        return None
    try:
        return max(cands, key=lambda c: c.stat().st_mtime_ns)
    except OSError:
        return None


def _functions_from_manager(mgr: Any) -> Dict[str, Dict[str, str]]:
    """QACDataManager.list_result → {"<파일경로>\\x1f<함수명>": {metric: value}}.

    JSON 캐시 가능하도록 키를 단일 문자열로 접는다(구분자는 경로·함수명에 나올 수 없는 US).
    """
    out: Dict[str, Dict[str, str]] = {}
    for item in getattr(mgr, "list_result", None) or []:
        fn = str(getattr(item, "function_name", "") or "").strip()
        fp = str(getattr(item, "file_name", "") or "").strip()
        if not fn or not fp:
            continue
        vals: Dict[str, str] = {}
        for mi in REPORT_ITEMS:
            v = (getattr(item, "dic_values", None) or {}).get(mi)
            if v is None or str(v).strip() == "":
                continue
            vals[mi.name] = str(v).strip()
        if vals:
            out[f"{fp}\x1f{fn}"] = vals
    return out


def load_his_metrics_cached(
    build_root: Optional[Path], reports_dir: Optional[Path]
) -> Optional[Dict[str, Any]]:
    """빌드의 함수별 HIS 메트릭을 디스크 캐시 경유로 로드.

    반환 {"functions": {...}, "src": {...}, "cache_hit": bool} 또는 None(HMR 부재/파싱 실패).
    실패를 빈 dict로 위장하지 않는다 — 호출측이 available:false + reason으로 정직 응답할 것.
    캐시 쓰기 실패는 fail-soft(결과는 반환).
    """
    hmr = find_latest_hmr_html(build_root, reports_dir)
    if hmr is None or reports_dir is None:
        return None
    try:
        st = hmr.stat()
    except OSError:
        return None
    src = {
        "path": str(hmr),
        "mtime_ns": st.st_mtime_ns,
        "size": st.st_size,
        "parser_version": PARSER_VERSION,
    }
    cache_path = Path(reports_dir) / HIS_METRICS_CACHE_NAME
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            isinstance(cached, dict)
            and cached.get("src") == src
            and isinstance(cached.get("functions"), dict)
        ):
            return {"functions": cached["functions"], "src": src, "cache_hit": True}
    except (OSError, ValueError):
        pass  # 캐시 부재/손상 → 재파싱

    mgr = parse_qac_report(hmr)
    if getattr(mgr, "parse_error", ""):
        return None
    functions = _functions_from_manager(mgr)
    if not functions:
        return None
    try:
        import uuid as _uuid

        tmp = cache_path.with_name(f"{cache_path.name}.{_uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(
            json.dumps({"src": src, "functions": functions}, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(cache_path)
    except OSError as exc:
        logger.debug("his metrics cache write skipped (%s): %s", cache_path, exc)
    return {"functions": functions, "src": src, "cache_hit": False}


def band_verdict(metric_name: str, value: Any) -> Optional[Dict[str, str]]:
    """메트릭 값 → 회사 ST201 밴드 판정. 밴드 미정의 메트릭/비숫자 값은 None.

    None을 'Pass'로 접지 않는다 — 기준 없음과 통과는 다르다(미평가를 통과로 오기재 금지).
    """
    banded = _BANDED.get(str(metric_name))
    if banded is None:
        return None
    try:
        v = int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return None
    st_id, disp, bands = banded
    for upper, label, verdict in bands:
        if upper is None or v <= upper:
            return {"st_id": st_id, "name": disp, "band": label, "verdict": verdict}
    return None


def band_headroom(metric_name: str, value: Any) -> Optional[Dict[str, Any]]:
    """현재 값에서 **판정이 나빠지기까지 남은 여유**(정수 거리). 밴드 미정의/비숫자면 None.

    왜 `band_verdict(v)` vs `band_verdict(v+1)` 비교로 부족한가: 그건 값이 밴드 상한에
    **정확히** 붙은 함수만 잡는다. 실제 리팩터링은 1단이 아니라 2~5단을 올린다 — 단일 exit
    변환은 중첩을, 재귀 제거는 복잡도를 그만큼 밀어올린다. 실측에서도 그 차이가 컸다:
    HDPDM01의 V_G==10(상한 정확히)은 5개뿐이지만 8~10(여유 ≤3)은 29개다.
    거리를 돌려주고 **임계는 호출측이 정하게** 한다.

    이미 최악 밴드에 있어 더 나빠질 곳이 없으면 None(여유 0이 아니다 — 개념이 다르다).
    """
    banded = _BANDED.get(str(metric_name))
    if banded is None:
        return None
    try:
        v = int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return None
    st_id, disp, bands = banded
    # 각 밴드의 시작값 — 상한만 정의돼 있으므로 앞 밴드의 상한 + 1이 다음 밴드의 시작.
    entries: List[Tuple[int, Optional[int], str, str]] = []
    prev_upper: Optional[int] = None
    for upper, label, verdict in bands:
        entries.append((0 if prev_upper is None else prev_upper + 1, upper, label, verdict))
        prev_upper = upper
    idx = next(
        (i for i, (_s, upper, _l, _v) in enumerate(entries) if upper is None or v <= upper), None
    )
    if idx is None:
        return None
    cur_start, _cur_upper, cur_label, cur_verdict = entries[idx]
    for start, _upper, label, verdict in entries[idx + 1:]:
        # 같은 판정이 이어지는 밴드는 건너뛴다 — V_G 는 11~20 과 21~30 이 둘 다
        # Conditional 이라, 20→21 을 '나빠짐'으로 세면 없던 위험을 만든다.
        if verdict != cur_verdict:
            return {
                "headroom": start - v, "st_id": st_id, "name": disp,
                "band": cur_label, "verdict": cur_verdict,
                "next_band": label, "next_verdict": verdict,
            }
    return None


def _resolve_file_key(functions: Dict[str, Dict[str, str]], file: str) -> Tuple[List[str], str]:
    """대상 파일에 속한 함수 키들을 경로 suffix 매칭으로 고른다.

    RCR 경로(리포트 기준 상대)·HMR 경로(빌드 머신 절대)는 루트가 달라 완전 일치가 불가능하다.
    prqa_delta와 같은 세그먼트 경계 suffix 규칙을 쓴다. 동일 basename이 여러 디렉토리에
    있으면(APP/config.c vs BOOT/config.c) 찍지 않고 ambiguous를 돌려준다.
    """
    want = _norm_path(file)
    if not want:
        return [], "params_required"
    matched: Dict[str, List[str]] = {}
    for key in functions:
        fp = key.split("\x1f", 1)[0]
        if _suffix_match(_norm_path(fp), want):
            matched.setdefault(fp, []).append(key)
    if not matched:
        return [], "file_not_in_hmr"
    if len(matched) > 1:
        return [], "file_ambiguous_in_hmr"
    return next(iter(matched.values())), ""


def _fn_name(key: str) -> str:
    return key.split("\x1f", 1)[1] if "\x1f" in key else key


def compute_function_metric_delta(
    cur: Dict[str, Dict[str, str]],
    base: Dict[str, Dict[str, str]],
    *,
    file: Optional[str] = None,
    max_functions: int = 40,
) -> Dict[str, Any]:
    """두 빌드의 함수별 메트릭을 조인해 added/removed/modified를 낸다(순수 계산 — IO 없음).

    ``file`` 지정 시 그 파일 소속 함수로 한정. 지정하지 않으면 전 함수를 대상으로 한다.
    변화가 있는 함수만 반환하며, 밴드가 정의된 메트릭이 **밴드를 넘은 경우**(예: v(G)
    10→11 = Pass→Conditional)를 band_crossings로 별도 표기한다 — 값 증가와 등급 변화는
    의미가 달라 섞으면 안 된다.
    """
    partial: Optional[str] = None
    if file:
        cur_keys, cur_reason = _resolve_file_key(cur, file)
        base_keys, base_reason = _resolve_file_key(base, file)
        # 한쪽에만 있으면(신규 파일 등) 있는 쪽만으로 진행 — 양쪽 다 없을 때만 실패.
        if not cur_keys and not base_keys:
            return {"available": False, "reason": cur_reason or base_reason or "file_not_in_hmr"}
        if cur_reason == "file_ambiguous_in_hmr" or base_reason == "file_ambiguous_in_hmr":
            return {"available": False, "reason": "file_ambiguous_in_hmr"}
        # ⚠ 한쪽 HMR에만 파일이 있으면 그쪽 함수가 **전부** added/removed로 나온다. 파일이
        #   실제로 신설/삭제된 경우와 '그 빌드 분석 대상에서 빠진' 경우를 HMR만으로는 구분할
        #   수 없다 → 목록을 그대로 주되 partial 플래그로 고지한다(전부 신규를 사실로 위장 금지).
        if not base_keys:
            partial = "base_missing"
        elif not cur_keys:
            partial = "cur_missing"
        cur = {k: cur[k] for k in cur_keys}
        base = {k: base[k] for k in base_keys}

    added: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []
    modified: List[Dict[str, Any]] = []

    for key in cur.keys() - base.keys():
        added.append({
            "function": _fn_name(key),
            "change": "added",
            "metrics": [
                {"metric": m, "label": METRIC_LABEL.get(m, m), "base": None, "cur": cur[key][m],
                 "verdict": (band_verdict(m, cur[key][m]) or {}).get("verdict")}
                for m in (mi.name for mi in REPORT_ITEMS) if m in cur[key]
            ],
        })
    for key in base.keys() - cur.keys():
        removed.append({"function": _fn_name(key), "change": "removed"})
    for key in cur.keys() & base.keys():
        c, b = cur[key], base[key]
        changes: List[Dict[str, Any]] = []
        crossings: List[Dict[str, Any]] = []
        for mi in REPORT_ITEMS:
            m = mi.name
            cv, bv = c.get(m), b.get(m)
            if cv == bv:
                continue
            cvd, bvd = band_verdict(m, cv), band_verdict(m, bv)
            changes.append({
                "metric": m, "label": METRIC_LABEL.get(m, m), "base": bv, "cur": cv,
                "verdict": (cvd or {}).get("verdict"),
            })
            if cvd and bvd and cvd.get("verdict") != bvd.get("verdict"):
                crossings.append({
                    "metric": m, "label": METRIC_LABEL.get(m, m),
                    "name": cvd.get("name"), "st_id": cvd.get("st_id"),
                    "base": bv, "cur": cv,
                    "from_verdict": bvd.get("verdict"), "to_verdict": cvd.get("verdict"),
                    "from_band": bvd.get("band"), "to_band": cvd.get("band"),
                })
        if changes:
            modified.append({
                "function": _fn_name(key), "change": "modified",
                "metrics": changes, "band_crossings": crossings,
            })

    # 등급이 나빠진 함수를 먼저 — 값만 흔들린 함수보다 판단 가치가 높다.
    _rank = {"Fail": 0, "Conditional": 1, "Pass": 2}

    def _worst(fn: Dict[str, Any]) -> int:
        return min(
            [_rank.get(str(c.get("to_verdict")), 3) for c in fn.get("band_crossings") or []] or [3]
        )

    added.sort(key=lambda f: f["function"])
    removed.sort(key=lambda f: f["function"])
    modified.sort(key=lambda f: (_worst(f), -len(f.get("metrics") or []), f["function"]))

    functions = added + modified + removed
    omitted = max(0, len(functions) - max_functions)
    out: Dict[str, Any] = {
        "available": True,
        "reason": None,
        "functions": functions[:max_functions],
        "omitted": omitted,
        "totals": {"added": len(added), "removed": len(removed), "modified": len(modified)},
        "note": ATTRIBUTION_NOTE,
    }
    if partial:
        out["partial"] = partial
    return out


def load_pair_function_delta(
    *,
    from_build_root: Optional[Path],
    from_reports_dir: Optional[Path],
    to_build_root: Optional[Path],
    to_reports_dir: Optional[Path],
    file: Optional[str] = None,
    max_functions: int = 40,
) -> Dict[str, Any]:
    """빌드 쌍의 HMR을 캐시 경유 로드해 함수 delta를 낸다(IO + 계산 조립).

    어느 한쪽이라도 HMR이 없으면 available:false + reason='no_hmr' — 0/빈 목록으로
    위장하지 않는다(증거부재≠변화없음).
    """
    cur = load_his_metrics_cached(to_build_root, to_reports_dir)
    base = load_his_metrics_cached(from_build_root, from_reports_dir)
    if cur is None or base is None:
        return {"available": False, "reason": "no_hmr"}
    out = compute_function_metric_delta(
        cur["functions"], base["functions"], file=file, max_functions=max_functions
    )
    out["cache_hit"] = bool(cur.get("cache_hit") and base.get("cache_hit"))
    return out
