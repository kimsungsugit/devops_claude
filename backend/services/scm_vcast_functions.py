"""SCM 입력 문서(cloudium VectorCAST 폴더) 로드 이력 → 함수(subprogram)단위 커버리지 회수.

빌드 산출물(`report/analysis_summary.json`)에 함수단위 커버리지가 아예 없는 프로젝트가 실측
다수다(KJPDS02_PV: `vectorcast_detail`이 빈 {} 이고 `vectorcast.ut/it_metrics`도 부재) — 그런
프로젝트도 **설정 > 연결 문서 경로 > VectorCAST**(`linked_docs.vectorcast`)를 한 번 로드했으면
그 결과가 `reports/impact_jobs/job_impact_*_{jobslug}_*.json` 에 남아 있고, 거기에는 함수별
`statements/branches/pairs` + `ccn` 이 그대로 들어 있다(실측: UT 1014행 · IT 712행 · 복잡도 1008행).

이 모듈은 그 잡 파일에서 **함수단위 블록만** 회수한다. 잡 선택 규약은
`jenkins._scm_vcast_metrics_for_slug` 와 동일하다 — 파일명으로 후보를 고르고(본문 파싱 최소화)
`status=completed ∧ trigger_type=vectorcast ∧ result.ok` 인 최신 잡을 쓰되, 최신이 실패/미완료면
직전 성공 잡으로 폴백한다(가용성 우선).

⚠ 잡 파일은 실측 3.3MB다. 파싱 결과 전체를 캐시하면 프로세스 메모리를 잡아먹으므로 **필요한
키만 슬라이스**해 보존하고 원본 dict은 즉시 버린다(`test_rows` 7502행은 통과/실패 집계만 남긴다).
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("uvicorn.error")

# key=(잡파일경로, mtime_ns) — 완료된 잡 파일은 불변이라 무-stale(새 로드 = 새 파일 = 새 키).
# 값은 _slice_payload의 슬라이스본(또는 None=이 파일은 대상 아님)만 보존한다.
_CACHE: Dict[Tuple[str, int], Optional[Dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX_ENTRIES = 8

# 방어적 상한 — 손상/비정상 잡이 프로세스 메모리를 잡지 못하게. 실측 최대는 UT 1014 · IT 712.
MAX_ENTRIES_PER_BLOCK = 5000
MAX_COMPLEXITY_ROWS = 5000
MAX_FAILURES = 50
MAX_PARSE_WARNINGS = 10


def _dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _entries_of(block: Any) -> List[Dict[str, Any]]:
    rows = _dict(block).get("entries")
    if not isinstance(rows, list):
        return []
    return [e for e in rows[:MAX_ENTRIES_PER_BLOCK] if isinstance(e, dict)]


def _test_row_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    """test_rows(실측 7502행)는 통째로 보존하지 않는다 — 집계 dict만 승계."""
    summary = _dict(data.get("summary"))
    return {
        "total": summary.get("total"),
        "passed": summary.get("passed"),
        "failed": summary.get("failed"),
        "pass_rate": summary.get("pass_rate"),
        "ut_rows": data.get("test_rows_count_ut"),
        "it_rows": data.get("test_rows_count_it"),
    }


def _slice_payload(raw: Dict[str, Any], path: Path) -> Optional[Dict[str, Any]]:
    """잡 본문 → 함수단위 블록 슬라이스. 대상이 아니거나 함수 행이 0이면 None.

    None은 '이 잡 파일은 함수 커버리지 소스가 아님'이라는 뜻이며, 호출측은 더 오래된 후보로
    넘어간다(캐시에도 None을 저장해 같은 파일을 다시 열지 않는다).
    """
    if raw.get("status") != "completed" or raw.get("trigger_type") != "vectorcast":
        return None
    result = _dict(raw.get("result"))
    if not result.get("ok"):
        return None
    data = _dict(result.get("data"))
    vcast = _dict(data.get("vcast_summary"))
    ut = _entries_of(vcast.get("ut_metrics"))
    it = _entries_of(vcast.get("it_metrics"))
    if not ut and not it:
        return None  # 커버리지 없는 로드(테스트 행만) — 폴백 소스로 쓸 수 없다
    complexity = [
        r for r in (data.get("complexity_rows") or [])[:MAX_COMPLEXITY_ROWS] if isinstance(r, dict)
    ]
    failures = [f for f in (data.get("failures") or [])[:MAX_FAILURES] if isinstance(f, dict)]
    warnings = [str(w) for w in (data.get("parse_warnings") or [])[:MAX_PARSE_WARNINGS]]
    return {
        "available": True,
        "reason": None,
        "job_file": path.name,
        "job_id": raw.get("job_id"),
        "scm_id": raw.get("scm_id"),
        # 로드 시각 — 프론트가 '언제 읽은 SCM 문서인지' 표기한다(빌드 산출물과 시점이 다르므로 필수).
        "generated_at": raw.get("finished_at") or raw.get("updated_at") or raw.get("created_at"),
        "ut_entries": ut,
        "it_entries": it,
        "complexity_rows": complexity,
        "coverage": _dict(data.get("coverage")) or None,
        "coverage_ut": _dict(data.get("coverage_ut")) or None,
        "coverage_it": _dict(data.get("coverage_it")) or None,
        "failures": failures,
        "test_summary": _test_row_summary(data),
        "parse_warnings": warnings,
        "merged_sources": data.get("merged_sources"),
    }


def _load_from_file(path: Path) -> Optional[Dict[str, Any]]:
    """단일 잡 파일 → 슬라이스본(캐시 경유). 파일 소멸/손상은 None(다음 후보로)."""
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return None
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key]
    sliced: Optional[Dict[str, Any]] = None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            sliced = _slice_payload(raw, path)
    except (OSError, ValueError) as exc:  # 소멸(OSError)·부분쓰기/손상 JSON(JSONDecodeError ⊂ ValueError)
        logger.debug("scm vcast job read failed (%s): %s", path.name, exc)
        sliced = None
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX_ENTRIES:
            _CACHE.clear()  # 슬라이스본도 수백 KB — 단순 전량 비움(자매 캐시와 동일 전략)
        _CACHE[key] = sliced
    return sliced


def load_scm_function_metrics(job_url: str) -> Dict[str, Any]:
    """job_url → SCM 로드 이력의 함수단위 커버리지. 부재는 available:false + reason.

    Jenkins·cloudium 재접근 없음(기존 잡 파일 직독) — 요약탭의 임계경로에 넣어도 안전하다.
    """
    from backend.services.jenkins_helpers import _job_slug
    from workflow.impact_jobs import find_job_files_by_scm

    url = str(job_url or "").strip()
    if not url:
        return {"available": False, "reason": "job_url_required"}
    slug = _job_slug(url)
    if not slug:
        return {"available": False, "reason": "invalid_job_url"}
    try:
        candidates = find_job_files_by_scm(slug, limit=5)
    except OSError as exc:  # glob/mkdir I/O 장애 → '이력 없음'으로 graceful
        logger.debug("scm vcast job lookup failed (%s): %s", slug, exc)
        return {"available": False, "reason": "job_dir_unreadable"}
    if not candidates:
        return {"available": False, "reason": "no_scm_vcast_job"}
    for path in candidates:
        sliced = _load_from_file(path)
        if sliced is not None:
            return dict(sliced)
    # 후보는 있었으나 전부 미완료/실패/커버리지 부재 — '이력 없음'과 구분해 보고한다.
    return {"available": False, "reason": "no_completed_vcast_job_with_metrics"}


def clear_cache() -> None:
    """테스트/운영 진단용 캐시 초기화."""
    with _CACHE_LOCK:
        _CACHE.clear()
