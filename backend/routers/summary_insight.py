"""프로젝트 요약탭 심층 데이터 라우터 — 빌드간 PRQA 위반 delta(+향후 AI 인사이트).

jenkins.py(6천 줄, 동시 세션 편집 잦음)를 더 키우지 않기 위해 요약탭 신규 API를 이
파일로 분리한다. 경로는 기존 관례(/api/jenkins/*)를 따른다. 응답 정직성 규약:
계산 불가는 항상 available:false + reason — 부분 delta나 침묵 0으로 위장하지 않는다.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

# 공용 헬퍼(backend/helpers) — 라우터 간 private import 아님.
from backend.helpers.jenkins import _normalize_jenkins_cache_root
from backend.services.jenkins_service import list_cached_builds
from backend.services.prqa_delta import (
    apply_changed_file_signals,
    compute_prqa_pair_delta,
    load_rcr_details_cached,
)

router = APIRouter()
_logger = logging.getLogger("uvicorn.error")


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _find_build(builds: List[Dict[str, Any]], number: int) -> Optional[Dict[str, Any]]:
    for b in builds:
        if _to_int(b.get("build_number")) == number:
            return b
    return None


def _previous_cached_build(builds: List[Dict[str, Any]], number: int) -> Optional[Dict[str, Any]]:
    """number보다 작은 빌드 중 최대(=직전 캐시 빌드). builds는 최신순이지만 번호
    비연속·정렬 예외에 흔들리지 않도록 명시 max로 고른다."""
    older = [b for b in builds if (_to_int(b.get("build_number")) or -1) < number and _to_int(b.get("build_number")) is not None]
    if not older:
        return None
    return max(older, key=lambda b: _to_int(b.get("build_number")) or -1)


def _changed_files_for_build(scm_id: str, build_number: int) -> Dict[str, Any]:
    """change-log(durable 영향도 이력)에서 해당 빌드의 변경 파일 목록을 찾는다.

    build_timeline rows(run_id↔build_number 매핑)로 run_id를 찾고 레코드를 로드한다.
    부재는 available:false — '변경 파일 0개'와 구분(증거부재≠공집합).
    """
    if not scm_id:
        return {"available": False, "reason": "scm_id_not_provided"}
    try:
        from workflow.impact_changes import build_timeline, load_change_log

        rows = (build_timeline(scm_id, limit=200) or {}).get("rows") or []
        run_id = next(
            (r.get("run_id") for r in rows if _to_int(r.get("build_number")) == build_number),
            None,
        )
        if not run_id:
            return {"available": False, "reason": "no_change_log_for_build"}
        record = load_change_log(str(run_id))
        files = [str(f) for f in (record.get("changed_files") or []) if str(f or "").strip()]
        return {"available": True, "source": "change_log", "count": len(files), "files": files}
    except Exception as exc:  # change-log 손상 등 — delta 본체를 죽이지 않는다(fail-soft).
        _logger.debug("prqa-delta changed_files lookup failed (scm=%s #%s): %s", scm_id, build_number, exc)
        return {"available": False, "reason": "change_log_error"}


@router.post("/api/jenkins/prqa-delta")
def jenkins_prqa_delta(req: dict) -> Dict[str, Any]:
    """빌드 쌍(현재 vs 기준)의 PRQA 규칙×파일 위반 delta — 요약탭 드릴다운 on-demand.

    전 빌드 일괄이 아니라 쌍 단위인 이유: RCR HTML 파싱이 빌드당 수 초(캐시 미스 시).
    파싱 결과는 prqa_rcr_details_cache.json(RCR mtime_ns/size/파서버전 키)으로 1회화되어
    2회차부터는 JSON 로드 2번 + 산술뿐이다.
    """
    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    if not job_url:
        return {"ok": True, "available": False, "reason": "job_url_required"}
    build_number = _to_int(body.get("build_number"))
    if build_number is None:
        return {"ok": True, "available": False, "reason": "build_number_required"}

    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    builds = list_cached_builds(job_url=job_url, cache_root=cache_root)  # 최신순
    cur_meta = _find_build(builds, build_number)
    base_out: Dict[str, Any] = {
        "ok": True,
        "build_number": build_number,
        "baseline_build_number": None,
        "baseline_auto": False,
    }
    if cur_meta is None:
        return {**base_out, "available": False, "reason": "build_not_cached"}

    # 현재 빌드 RCR을 baseline 해석보다 먼저 확인 — 最古 빌드처럼 baseline이 없더라도
    # '이 빌드에 RCR 없음'이 사용자에게 더 직접적인 사유다.
    cur = load_rcr_details_cached(
        Path(str(cur_meta.get("build_root") or "")) if cur_meta.get("build_root") else None,
        Path(str(cur_meta.get("reports_dir") or "")) if cur_meta.get("reports_dir") else None,
    )
    if cur is None:
        return {**base_out, "available": False, "reason": "no_rcr_current"}

    baseline_req = body.get("baseline_build_number")
    if baseline_req in (None, ""):
        base_meta = _previous_cached_build(builds, build_number)
        base_out["baseline_auto"] = True
        if base_meta is None:
            return {**base_out, "available": False, "reason": "no_baseline_build"}
    else:
        baseline_number = _to_int(baseline_req)
        if baseline_number is None:
            return {**base_out, "available": False, "reason": "baseline_build_number_invalid"}
        base_meta = _find_build(builds, baseline_number)
        if base_meta is None:
            return {**base_out, "available": False, "reason": "baseline_not_cached"}
    base_out["baseline_build_number"] = _to_int(base_meta.get("build_number"))
    base = load_rcr_details_cached(
        Path(str(base_meta.get("build_root") or "")) if base_meta.get("build_root") else None,
        Path(str(base_meta.get("reports_dir") or "")) if base_meta.get("reports_dir") else None,
    )
    if base is None:
        return {**base_out, "available": False, "reason": "no_rcr_baseline"}

    delta = compute_prqa_pair_delta(cur["details"], base["details"])

    changed = _changed_files_for_build(str(body.get("scm_id") or "").strip(), build_number)
    signals: List[Dict[str, Any]] = []
    if changed.get("available"):
        # in_changed_set 플래그는 changed_files 확보 시에만 부여(부재를 false로 위장 금지).
        signals = apply_changed_file_signals(delta["files"], changed.get("files") or [])
    changed_out = {k: v for k, v in changed.items() if k != "files"}

    return {
        **base_out,
        "available": True,
        "reason": None,
        "basis": delta["basis"],
        "totals": delta["totals"],
        "rules": delta["rules"],
        "files": delta["files"],
        "files_omitted": delta["files_omitted"],
        "changed_files": changed_out,
        "signals": signals,
        "truncation": {
            "cur_files_truncated_to": cur["details"].get("files_truncated_to"),
            "base_files_truncated_to": base["details"].get("files_truncated_to"),
        },
        "cache": {"cur_hit": cur["cache_hit"], "base_hit": base["cache_hit"]},
    }
