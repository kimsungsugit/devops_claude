"""베이스라인 고정 → 각 빌드의 누적 변화 매트릭스.

change-log(영향분석 실행 이력) **완전 비의존**. 행 = 캐시된 빌드, 값 = (고정 베이스라인 →
그 빌드)의 소스 스냅샷 차이. 구 타임라인은 "잡을 실행한 이력"을 읽어 잡을 돌린 적 없는
빌드가 전부 `—`였고(실측 104행 중 빌드번호 있는 행이 2개), 그 이력 자체가 이 표에 필요 없다.

## 비용을 감당하는 두 레버 (실측 KJPDS02_PV 13빌드)

1. **동일 트리는 셀 하나를 공유한다.** 13빌드의 고유 content_sha가 4개뿐이라 12쌍이 3쌍으로
   접힌다(83초 → 12~26초). `parse_c_project`에는 메모이제이션이 전혀 없어서(lru_cache·디스크·
   프로세스 캐시 모두 부재) 이 dedup이 유일한 현실적 수단이다.
2. **베이스라인과 바이트 동일한 빌드는 함수 차이가 0임이 증명된다.** 가정이 아니다 — 두 트리가
   동일하면 파서 산출도 동일하고 (파일,함수명) 조인의 차집합은 공집합이다. 13행 중 9행이
   파싱 0회로 즉시 확정된다.

## 정직성 규약
- 함수 축 미계산은 `None` + `function_state.reason` — **0으로 위장하지 않는다**.
- ASIL은 함수 축이 있어야만 산출된다(함수명 조인). 파일 단위로는 원리적으로 불가.
- 동일 트리 그룹을 표면화한다 — "10개 빌드의 변화가 0"은 코드가 안 바뀐 게 아니라 백필이 같은
  SVN HEAD를 받아왔다는 뜻일 수 있고, 그걸 감추면 ASIL 함수 변경이 과소보고된다.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CHANGE_MATRIX_ALGO_VERSION = 1
# ⚠ `summary_baseline_diff_*` 와 **반드시 달라야 한다** — summary_insight._changed_functions_from_cache
#   가 그 글롭의 mtime 최신 3개를 test-design·ai-insight의 '변경 축'으로 쓴다. 같은 이름으로
#   매트릭스 셀을 대량 생성하면 그 축이 조용히 바뀐다.
CELL_CACHE_PREFIX = "summary_change_cell_"
MAX_MATRIX_TARGETS = 30
# 스냅샷당 파싱 결과 수 MB — 고유 트리 수(실측 4)만큼만 들고 있으면 된다.
_PARSE_LRU_MAX = 4
_PARSE_LRU: "OrderedDict[str, Dict[Tuple[str, str], Dict[str, Any]]]" = OrderedDict()
_PARSE_LOCK = threading.Lock()


def cell_cache_name(baseline_sha: str) -> str:
    return f"{CELL_CACHE_PREFIX}{str(baseline_sha or '')[:12]}.json"


def cell_id(baseline_sha: str, target_sha: str) -> str:
    return f"{str(baseline_sha or '')[:8]}__{str(target_sha or '')[:8]}"


def group_by_content_sha(
    metas: List[Dict[str, Any]], sha_of: Callable[[Dict[str, Any]], Optional[str]],
) -> Dict[str, List[Any]]:
    """{content_sha: [build_number...]} — **전 그룹**(멤버 1개짜리 포함).

    `summary_insight._snapshot_groups`는 count>1만 반환한다(경고용). 여기서는 그룹 대표를
    정해 셀을 공유해야 하므로 단독 그룹도 필요하다.
    """
    out: Dict[str, List[Any]] = {}
    for meta in metas:
        sha = sha_of(meta)
        if sha:
            out.setdefault(sha, []).append(meta.get("build_number"))
    return out


def canonical_build(numbers: List[Any]) -> Any:
    """그룹 대표 = 가장 작은 빌드 번호.

    max를 쓰면 같은 트리로 새 빌드가 들어올 때마다 대표가 바뀌어 캐시가 매번 미스난다.
    과거 빌드가 백필로 추가되는 경우가 더 드물어 min이 안정적이다.
    """
    nums = [n for n in numbers if n is not None]
    return min(nums) if nums else None


def parse_functions_memo(source: Path, *, content_sha: Optional[str]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """내용 지문을 키로 하는 파싱 메모 — **경로가 아니라 내용**이 키다.

    동일 트리 10빌드가 파싱 1회를 공유한다(실측 파싱 횟수 = 고유 sha 수 = 4).
    지문이 없으면 메모하지 않고 직통한다(잘못된 키로 오염시키지 않는다).
    """
    from backend.services.baseline_diff import _parse_functions

    if not content_sha:
        return _parse_functions(source)
    with _PARSE_LOCK:
        hit = _PARSE_LRU.get(content_sha)
        if hit is not None:
            _PARSE_LRU.move_to_end(content_sha)
            return hit
    parsed = _parse_functions(source)
    with _PARSE_LOCK:
        _PARSE_LRU[content_sha] = parsed
        _PARSE_LRU.move_to_end(content_sha)
        while len(_PARSE_LRU) > _PARSE_LRU_MAX:
            _PARSE_LRU.popitem(last=False)
    return parsed


def clear_parse_memo() -> None:
    """테스트/캐시 초기화 훅."""
    with _PARSE_LOCK:
        _PARSE_LRU.clear()


def function_counts(diff: Dict[str, Any]) -> Dict[str, int]:
    """셀 결과에서 함수 축 요약만 추출."""
    counts = dict((diff.get("functions") or {}).get("counts") or {})
    counts["changed"] = sum(int(v or 0) for k, v in counts.items() if k != "changed")
    return counts


def asil_column(diff: Dict[str, Any]) -> Dict[str, Any]:
    """표의 'ASIL 함수 변경' 열 — {touched, by_grade, max}."""
    touched = [t for t in (diff.get("asil_touched") or []) if isinstance(t, dict)]
    by_grade: Dict[str, int] = {}
    for t in touched:
        grade = str(t.get("asil") or "").strip()
        if grade:
            by_grade[grade] = by_grade.get(grade, 0) + 1
    order = ["D", "C", "B", "A", "QM"]
    present = [g for g in order if g in by_grade]
    return {"touched": len(touched), "by_grade": by_grade, "max": present[0] if present else None}


def annotate_asil_coverage(
    diff: Dict[str, Any], *, asil_by_fn: Optional[Dict[str, Any]],
    function_coverage: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """조인 무관 캐시(파싱 결과)에 ASIL·커버리지를 **읽을 때** 부착한다.

    셀 캐시 키에 조인 규모를 넣으면 새 빌드가 하나 들어올 때마다 4~9초짜리 계산이 전부
    무효화된다(매트릭스에선 그게 곧 83초). 파싱 결과는 조인과 무관하므로 분리해 두고,
    등급·커버리지는 순수 dict 조회로 나중에 붙인다.
    """
    from backend.services.baseline_diff import _resolve_asil, build_changed_detail

    fns = diff.get("functions") or {}
    fn_rows: List[Dict[str, Any]] = []
    for kind, key in (("NEW", "new"), ("DELETE", "deleted"),
                      ("SIGNATURE", "signature_changed"), ("BODY", "body_changed")):
        for row in fns.get(key) or []:
            if not isinstance(row, dict):
                continue
            asil, src = _resolve_asil(row.get("name"), row.get("asil"), asil_by_fn)
            row = {**row, "asil": asil, "asil_source": src}
            fns.setdefault(key, [])
            fn_rows.append({**row, "kind": kind})
    # 원본 리스트를 등급이 반영된 값으로 교체(참조가 아니라 새 리스트).
    for kind, key in (("NEW", "new"), ("DELETE", "deleted"),
                      ("SIGNATURE", "signature_changed"), ("BODY", "body_changed")):
        fns[key] = [{k: v for k, v in r.items() if k != "kind"} for r in fn_rows if r["kind"] == kind]
    diff["functions"] = fns
    diff["asil_touched"] = [
        {"name": r.get("name"), "file": r.get("file"), "asil": r.get("asil"),
         "change_kind": r["kind"], "asil_source": r.get("asil_source")}
        for r in fn_rows if r.get("asil")
    ]
    file_rows = {
        row.get("path"): {"change_kind": row.get("change_kind"),
                          "lines_added": row.get("lines_added"), "lines_removed": row.get("lines_removed")}
        for row in (diff.get("files") or {}).get("changed_detail") or []
        if isinstance(row, dict) and row.get("path")
    }
    if file_rows:
        detail, omitted, gap = build_changed_detail(file_rows, fn_rows, function_coverage)
        diff.setdefault("files", {})["changed_detail"] = detail
        diff["files"]["changed_detail_omitted"] = omitted
        diff["functions"]["gap_summary"] = gap
    return diff
