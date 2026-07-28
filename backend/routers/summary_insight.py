"""프로젝트 요약탭 심층 데이터 라우터 — 빌드간 PRQA 위반 delta + AI 인사이트.

jenkins.py(6천 줄, 동시 세션 편집 잦음)를 더 키우지 않기 위해 요약탭 신규 API를 이
파일로 분리한다. 경로는 기존 관례(/api/jenkins/*, /api/summary/*)를 따른다.
응답 정직성 규약: 계산 불가는 항상 available:false + reason — 부분 delta나 침묵 0으로
위장하지 않는다. AI 인사이트는 on-demand + 빌드 디렉토리 디스크 캐시(비용 통제).
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

# 공용 헬퍼(backend/helpers) — 라우터 간 private import 아님.
from backend.helpers.jenkins import _normalize_jenkins_cache_root
from backend.services.jenkins_service import list_cached_builds
from backend.services.prqa_delta import (
    apply_changed_file_signals,
    compute_prqa_pair_delta,
    find_latest_rcr_html,
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


# ---------------------------------------------------------------------------
# 빌드 표면 확대 (Phase E) — 오프라인 메타 + 백필
# ---------------------------------------------------------------------------


@router.post("/api/jenkins/cached-builds-meta")
def jenkins_cached_builds_meta(req: dict) -> Dict[str, Any]:
    """캐시된 빌드 전량 + 오프라인 메타(result/timestamp/revision/보유 플래그).

    Jenkins 연결 불필요 — status.json·소스 센티널 직독. "최신 N개만 보인다"의 근본
    원인(캐시가 곧 상한)을 표면에서라도 정직하게: 캐시에 있는 만큼은 전부 보여준다.
    """
    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    if not job_url:
        return {"ok": True, "available": False, "reason": "job_url_required", "builds": []}
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    from backend.services.build_inventory import list_cached_builds_meta

    builds = list_cached_builds_meta(job_url=job_url, cache_root=cache_root)
    if not builds:
        return {"ok": True, "available": False, "reason": "no_cached_build", "builds": [], "count": 0}
    return {"ok": True, "available": True, "reason": None, "builds": builds, "count": len(builds)}


@router.post("/api/jenkins/sync-backfill")
def jenkins_sync_backfill(req: dict) -> Dict[str, Any]:
    """과거 빌드 일괄 캐시(백그라운드) — Jenkins 연결 시에만. 미도달은 정직 실패."""
    from backend.services.build_inventory import list_cached_builds_meta
    from backend.services.sync_backfill import (
        MAX_BACKFILL_COUNT,
        resolve_recent_build_numbers,
        start_backfill,
    )

    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    if not job_url:
        return {"ok": True, "available": False, "reason": "job_url_required"}
    username = str(body.get("username") or "")
    api_token = str(body.get("api_token") or "")
    verify_tls = bool(body.get("verify_tls", True))
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    patterns = body.get("patterns") if isinstance(body.get("patterns"), list) else []
    skip_cached = bool(body.get("skip_cached", True))
    pin_source = bool(body.get("pin_source", False))
    warm_matrix = bool(body.get("warm_matrix", False))
    baseline_build = _to_int(body.get("baseline_build"))

    cached_meta = list_cached_builds_meta(job_url=job_url, cache_root=cache_root)
    cached_numbers = {
        n for n in (_to_int(b.get("build_number")) for b in cached_meta) if n is not None
    }
    if pin_source:
        # 고정 요청일 때 '캐시됨'만으로 건너뛰면 **HEAD로 받아둔 잘못된 트리가 영원히 남는다**.
        # 이미 고정된 빌드만 skip 대상으로 남기고, 미고정 캐시는 재수집시킨다.
        cached_numbers = {
            n for n in (
                _to_int(b.get("build_number")) for b in cached_meta if b.get("source_pinned")
            ) if n is not None
        }

    raw_numbers = body.get("build_numbers")
    if isinstance(raw_numbers, list) and raw_numbers:
        numbers = [n for n in (_to_int(x) for x in raw_numbers) if n is not None]
    else:
        count = _to_int(body.get("count")) or 10
        count = max(1, min(count, MAX_BACKFILL_COUNT))
        try:
            numbers = resolve_recent_build_numbers(
                job_url=job_url, username=username, api_token=api_token,
                verify_tls=verify_tls, count=count,
                exclude=cached_numbers if skip_cached else set(),
            )
        except Exception as exc:
            # Jenkins 미도달 — 캐시 상태로 위장하지 않는다(요약탭은 캐시 기반으로 계속 동작).
            return {
                "ok": True, "available": False, "reason": "jenkins_unreachable",
                "detail": f"{type(exc).__name__}: {exc}",
            }

    skipped = sorted(n for n in numbers if n in cached_numbers) if skip_cached else []
    accepted = [n for n in numbers if not (skip_cached and n in cached_numbers)]
    if not accepted:
        return {
            "ok": True, "available": False, "reason": "nothing_to_backfill",
            "skipped_cached": skipped,
        }
    # 한 번에 처리 못 하고 남는 미고정 빌드 수 — 상한(MAX_BACKFILL_COUNT)이 캐시 빌드 수보다
    # 작으면 여러 번 눌러야 한다. 그 사실을 알리지 않으면 "고정했는데 왜 아직 경고가 뜨나"가 된다.
    remaining_unpinned = 0
    if pin_source:
        remaining_unpinned = sum(
            1 for b in cached_meta
            if not b.get("source_pinned") and _to_int(b.get("build_number")) not in set(accepted)
        )
    started = start_backfill(
        job_url=job_url, username=username, api_token=api_token, cache_root=cache_root,
        verify_tls=verify_tls, patterns=[str(p) for p in patterns],
        build_numbers=accepted,
        scm_username=str(body.get("scm_username") or ""), scm_id=str(body.get("scm_id") or ""),
        pin_source=pin_source, warm_matrix=warm_matrix, baseline_build=baseline_build,
    )
    if not started.get("accepted"):
        return {"ok": True, "available": False, "reason": started.get("reason"), "job_id": started.get("job_id")}
    return {
        "ok": True, "available": True, "reason": None,
        "job_id": started["job_id"], "accepted": accepted, "skipped_cached": skipped,
        "total": len(accepted),
        "pin_source": pin_source, "warm_matrix": warm_matrix,
        "remaining_unpinned": remaining_unpinned,
    }


@router.get("/api/jenkins/sync-backfill-status/{job_id}")
def jenkins_sync_backfill_status(job_id: str) -> Dict[str, Any]:
    from backend.services.sync_backfill import backfill_status

    status = backfill_status(job_id)
    if status is None:
        return {"ok": True, "available": False, "reason": "unknown_job_id"}
    return {"ok": True, "available": True, **status}


# ---------------------------------------------------------------------------
# 룰 인텔리전스 (Phase F) — 다빌드 룰 트렌드 + fix 근거 작성 예시
# ---------------------------------------------------------------------------

FIX_EXAMPLE_CACHE_NAME = "summary_rule_fix_cache.json"
FIX_EXAMPLE_CACHE_MAX_ENTRIES = 30
# fix 캐시는 read-modify-write라 동시 생성 시 형제 엔트리가 유실된다(통합 deep-review W1
# lost-update) — 프로세스 내 직렬화 락(uvicorn 단일 워커 전제, main.py 주석 참조).
_FIX_CACHE_LOCK = threading.Lock()


@router.post("/api/jenkins/prqa-rule-trend")
def jenkins_prqa_rule_trend(req: dict) -> Dict[str, Any]:
    """규칙×빌드 위반 트렌드 + 분류(resolved/decreasing/persistent/increasing/new_recent).

    빌드별 규칙 카운트는 prqa_delta RCR 디스크캐시 재사용 — 첫 호출만 미캐시 빌드 수 ×
    파싱 비용, 2회차부터 JSON 로드 + 산술(응답 cache.rcr_misses로 가시화).
    """
    from backend.services.prqa_rule_trend import DEFAULT_LIMIT, MAX_RULES, compute_rule_trend

    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    if not job_url:
        return {"ok": True, "available": False, "reason": "job_url_required"}
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    limit = _to_int(body.get("limit")) or DEFAULT_LIMIT
    max_rules = _to_int(body.get("max_rules")) or MAX_RULES
    return compute_rule_trend(
        job_url=job_url, cache_root=cache_root,
        limit=max(2, min(limit, 50)), max_rules=max(5, min(max_rules, 100)),
    )


def _fix_cache_load(path: Path) -> Dict[str, Any]:
    data = _read_json(path)
    entries = data.get("entries") if isinstance(data, dict) else None
    return entries if isinstance(entries, dict) else {}


def _fix_cache_store(path: Path, entries: Dict[str, Any]) -> None:
    # LRU-ish 상한: generated_at 오래된 것부터 제거.
    if len(entries) > FIX_EXAMPLE_CACHE_MAX_ENTRIES:
        ordered = sorted(entries.items(), key=lambda kv: str(kv[1].get("generated_at") or ""))
        entries = dict(ordered[len(ordered) - FIX_EXAMPLE_CACHE_MAX_ENTRIES:])
    _write_cache_atomic(path, {"entries": entries})


@router.post("/api/summary/rule-fix-example")
def summary_rule_fix_example(req: dict) -> Dict[str, Any]:
    """감소 규칙의 실제 fix diff 발췌 + '위반하지 않는 작성 예시'(Gemini, on-demand).

    correlation_note는 서버 고정 주입(상관≠인과 — LLM 재량 배제). LLM 실패/필터 시에도
    diff 증거는 항상 반환(결정론 폴백). 캐시 키에 diff_sha+model+prompt_version 포함.
    """
    import hashlib as _hashlib

    from backend.services.build_inventory import find_build_meta, list_cached_builds_meta
    from backend.services.prqa_rule_trend import CROSS_MODULE_NOTE, is_cross_module_key
    from backend.services.rule_fix_examples import collect_fix_evidence
    from workflow.rule_fix_example import (
        CORRELATION_NOTE,
        FIX_EXAMPLE_PROMPT_VERSION,
        generate_fix_example,
    )

    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    rule = str(body.get("rule") or "").strip()
    file = str(body.get("file") or "").strip()
    from_build = _to_int(body.get("from_build"))
    to_build = _to_int(body.get("to_build"))
    if not job_url or not rule or not file or from_build is None or to_build is None:
        return {"ok": True, "available": False, "reason": "params_required"}
    if is_cross_module_key(file):
        # RCMA류 집계는 파일이 아니다 — 스냅샷을 뒤져 'file_not_in_snapshot'을 내면
        # "파일이 사라졌다"는 오해를 부른다(실제로는 애초에 파일 귀속이 없는 항목).
        return {"ok": True, "available": False, "reason": "cross_module_scope",
                "cross_module_note": CROSS_MODULE_NOTE,
                "rule": rule, "file": file, "from_build": from_build, "to_build": to_build}
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    metas = list_cached_builds_meta(job_url=job_url, cache_root=cache_root)
    from_meta = find_build_meta(metas, from_build)
    to_meta = find_build_meta(metas, to_build)
    if from_meta is None or to_meta is None:
        return {"ok": True, "available": False, "reason": "build_not_cached"}

    evidence = collect_fix_evidence(
        from_build_root=Path(str(from_meta.get("build_root"))),
        to_build_root=Path(str(to_meta.get("build_root"))),
        file=file,
    )
    if not evidence.get("ok"):
        return {"ok": True, "available": False, "reason": evidence.get("reason"),
                "rule": rule, "file": file, "from_build": from_build, "to_build": to_build}

    model = _expected_insight_model()
    key = _hashlib.sha256(
        f"{rule}|{file}|{from_build}|{to_build}|{evidence['diff_sha']}|{model}|{FIX_EXAMPLE_PROMPT_VERSION}".encode()
    ).hexdigest()
    cache_path = Path(str(to_meta.get("reports_dir"))) / FIX_EXAMPLE_CACHE_NAME
    with _FIX_CACHE_LOCK:
        entries = _fix_cache_load(cache_path)
        hit = entries.get(key)
    probe = bool(body.get("probe"))
    force = bool(body.get("force"))
    if hit and not force:
        return {**hit, "cached": True}
    if probe:
        return {"ok": True, "available": True, "cached": False, "rule": rule, "file": file,
                "from_build": from_build, "to_build": to_build}

    gen = generate_fix_example(rule=rule, diff_excerpt=evidence["diff"]["text"],
                               rule_context={"file": file, "from_build": from_build, "to_build": to_build})
    payload: Dict[str, Any] = {
        "ok": True, "available": True, "reason": None,
        "rule": rule, "file": file, "from_build": from_build, "to_build": to_build,
        "evidence": evidence["diff"],
        "correlation_note": CORRELATION_NOTE,
        "example": gen["example"],
        "ai_enriched": gen["ai_enriched"],
        "enrich_reason": gen["enrich_reason"],
        "model": gen["model"],
        "prompt_version": FIX_EXAMPLE_PROMPT_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    # RMW 원자화(락) — LLM 호출(수 초) 밖에서 재로드해 형제 엔트리 유실을 막는다(lost-update).
    with _FIX_CACHE_LOCK:
        entries = _fix_cache_load(cache_path)
        entries[key] = payload
        _fix_cache_store(cache_path, entries)
    return {**payload, "cached": False}


# 서버 고정 주입(LLM 무관) — 구간 관측을 인과로 격상하지 않는다(ISO 정직성).
UNRESOLVED_NOTE = "파일 변경/무변경과 위반 잔존은 같은 빌드 구간의 관측이며 인과 판정이 아닙니다."


def _cross_module_counts_only(
    *, job_url: str, cache_root: Path, rule: str, file: str, from_build: int, to_build: int,
) -> Dict[str, Any]:
    """파일 귀속 불가 항목(RCMA류)의 구간 카운트만 반환 — 스냅샷 diff는 원리적으로 없다.

    카운트는 실재하는 관측이므로 버리지 않는다(0 위장·침묵 금지). diff 부재를 파일 부재
    (file_not_in_snapshot)로 표기하면 사용자가 '파일이 사라졌다'로 오독한다.
    """
    from backend.services.build_inventory import find_build_meta, list_cached_builds_meta
    from backend.services.prqa_delta import load_rcr_details_cached
    from backend.services.prqa_rule_trend import CROSS_MODULE_NOTE, file_rule_counts

    metas = list_cached_builds_meta(job_url=job_url, cache_root=cache_root)
    counts: Dict[str, Any] = {"from": None, "to": None}
    counts_reason: Optional[str] = None
    for label, bn in (("from", from_build), ("to", to_build)):
        meta = find_build_meta(metas, bn)
        if meta is None:
            counts_reason = "build_not_cached"
            continue
        loaded = load_rcr_details_cached(
            Path(str(meta.get("build_root") or "")), Path(str(meta.get("reports_dir") or ""))
        )
        if loaded is None:
            counts_reason = "no_rcr"
            continue
        counts[label] = int((file_rule_counts(loaded["details"]).get(file) or {}).get(rule, 0))
    out: Dict[str, Any] = {
        "ok": True, "available": False, "reason": "cross_module_scope",
        "cross_module_note": CROSS_MODULE_NOTE,
        "rule": rule, "file": file, "from_build": from_build, "to_build": to_build,
        "counts": counts, "file_changed": None, "diff": None, "note": UNRESOLVED_NOTE,
    }
    if counts_reason:
        out["counts_reason"] = counts_reason
    return out


def _file_rule_deltas(
    cur_details: Optional[Dict[str, Any]], base_details: Optional[Dict[str, Any]], file: str
) -> List[Dict[str, Any]]:
    """이 파일에서 구간 중 변한 규칙들 — 카드가 조회한 단일 규칙 옆에 붙일 전체 맥락.

    RCR을 이미 로드한 자리에서 계산하므로 추가 IO 0. 한쪽이라도 없으면 빈 목록(0 위장 금지 —
    호출측이 counts_reason으로 결측을 이미 고지한다).
    """
    from backend.services.prqa_rule_trend import file_rule_counts

    if not cur_details or not base_details:
        return []
    cur = (file_rule_counts(cur_details).get(file) or {})
    base = (file_rule_counts(base_details).get(file) or {})
    out: List[Dict[str, Any]] = []
    for rule in cur.keys() | base.keys():
        c, b = int(cur.get(rule, 0)), int(base.get(rule, 0))
        if c != b:
            out.append({"rule": rule, "base": b, "cur": c, "delta": c - b})
    out.sort(key=lambda r: (-r["delta"], r["rule"]))
    return out


def _function_attribution(
    *, from_meta: Dict[str, Any], to_meta: Dict[str, Any], file: str
) -> Dict[str, Any]:
    """구간 내 이 파일의 **함수 단위** 변화(HMR = HIS Metrics Report 기반).

    RCR이 파일 단위라 규칙의 함수 귀속은 원리적으로 불가하지만, 같은 빌드 산출물의 HMR은
    함수 단위다 — 어떤 함수가 새로 생겼고 어떤 함수의 복잡도가 어떻게 변했는지는 **실측**
    으로 답할 수 있다. 서비스가 note로 이 경계(관측≠규칙 귀속)를 함께 반환한다.
    실패는 전부 available:false + reason (빈 목록을 '변화 없음'으로 위장하지 않는다).
    """
    from backend.services.his_metric_delta import load_pair_function_delta

    try:
        return load_pair_function_delta(
            from_build_root=Path(str(from_meta.get("build_root") or "")),
            from_reports_dir=Path(str(from_meta.get("reports_dir") or "")),
            to_build_root=Path(str(to_meta.get("build_root") or "")),
            to_reports_dir=Path(str(to_meta.get("reports_dir") or "")),
            file=file,
        )
    except Exception as exc:  # noqa: BLE001 — 부가 정보라 본 응답을 깨뜨리면 안 된다
        _logger.debug("function attribution failed (%s): %s", file, exc)
        return {"available": False, "reason": "attribution_failed"}


@router.post("/api/summary/rule-unresolved-evidence")
def summary_rule_unresolved_evidence(req: dict) -> Dict[str, Any]:
    """미해소 규칙 × 파일의 구간 증거(결정론, LLM 0회) — '변경에도 위반 유지' vs '무변경 잔존'.

    규칙 위반의 **줄** 정보는 RCR에 없다(파일×규칙 카운트가 최상세). 그래서 코드 수준 근거는
    두 축으로 낸다: ① 빌드 스냅샷 diff, ② **HMR 함수 단위 메트릭 delta**(attribution) —
    ②는 어느 함수가 새로 생겼는지·복잡도가 어떻게 변했는지까지 실측으로 좁혀준다.
    '파일 무변경'은 실패가 아니라 그 자체로 유효 증거(위반이 잔존하는 파일이 구간 내
    수정된 적 없음)라 available:true + file_changed:false로 반환한다.
    """
    from backend.services.build_inventory import find_build_meta, list_cached_builds_meta
    from backend.services.prqa_delta import load_rcr_details_cached
    from backend.services.prqa_rule_trend import file_rule_counts, is_cross_module_key
    from backend.services.rule_fix_examples import collect_fix_evidence

    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    rule = str(body.get("rule") or "").strip()
    file = str(body.get("file") or "").strip()
    from_build = _to_int(body.get("from_build"))
    to_build = _to_int(body.get("to_build"))
    if not job_url or not rule or not file or from_build is None or to_build is None:
        return {"ok": True, "available": False, "reason": "params_required"}
    if is_cross_module_key(file):
        # 파일 귀속이 없는 집계 항목(RCMA류) — 구간 카운트는 의미가 있으나 스냅샷 diff는 없다.
        # 카운트만 채워 정직 반환한다(available:false + 전용 reason).
        return _cross_module_counts_only(
            job_url=job_url, cache_root=_normalize_jenkins_cache_root(str(body.get("cache_root") or "")),
            rule=rule, file=file, from_build=from_build, to_build=to_build,
        )
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    metas = list_cached_builds_meta(job_url=job_url, cache_root=cache_root)
    from_meta = find_build_meta(metas, from_build)
    to_meta = find_build_meta(metas, to_build)
    if from_meta is None or to_meta is None:
        return {"ok": True, "available": False, "reason": "build_not_cached"}

    # (rule, file) 구간 카운트 — diff 증거와 독립(RCR 캐시 실패 시 counts만 결측 표기, 0 위장 금지).
    counts: Dict[str, Any] = {"from": None, "to": None}
    counts_reason: Optional[str] = None
    details: Dict[str, Optional[Dict[str, Any]]] = {"from": None, "to": None}
    for label, meta in (("from", from_meta), ("to", to_meta)):
        loaded = load_rcr_details_cached(
            Path(str(meta.get("build_root") or "")), Path(str(meta.get("reports_dir") or ""))
        )
        if loaded is None:
            counts_reason = "no_rcr"
            continue
        details[label] = loaded["details"]
        counts[label] = int((file_rule_counts(loaded["details"]).get(file) or {}).get(rule, 0))

    evidence = collect_fix_evidence(
        from_build_root=Path(str(from_meta.get("build_root"))),
        to_build_root=Path(str(to_meta.get("build_root"))),
        file=file,
    )
    base: Dict[str, Any] = {
        "ok": True, "rule": rule, "file": file,
        "from_build": from_build, "to_build": to_build,
        "counts": counts, "note": UNRESOLVED_NOTE,
        # 규칙의 줄 귀속은 RCR에 없다 → 함수 단위 실측(HMR)으로 좁혀 준다. 부가 정보라
        # 실패해도 본 응답(diff·counts)은 그대로 나간다.
        "attribution": _function_attribution(from_meta=from_meta, to_meta=to_meta, file=file),
        "file_rule_deltas": _file_rule_deltas(details["to"], details["from"], file),
    }
    if counts_reason:
        base["counts_reason"] = counts_reason
    if evidence.get("ok"):
        return {**base, "available": True, "reason": None, "file_changed": True,
                "diff": evidence["diff"]}
    if evidence.get("reason") == "file_unchanged_between_builds":
        # 무변경은 실패가 아니라 유효 증거 — '위반 잔존 + 구간 내 파일 미수정' 관측.
        return {**base, "available": True, "reason": None, "file_changed": False, "diff": None}
    return {**base, "available": False, "reason": evidence.get("reason"),
            "file_changed": None, "diff": None}


@router.post("/api/summary/rule-window-changes")
def summary_rule_window_changes(req: dict) -> Dict[str, Any]:
    """구간 변경 파일 목록(결정론, LLM 0회) — 파일 귀속이 없는 규칙의 유일한 코드 증거.

    RCMA류 위반은 파일 diff를 만들 수 없지만, 위반이 변한 구간에 **실제로 바뀐 소스 파일**은
    스냅샷에 있다. 그것을 보여주되 인과로 격상하지 않는다(서버 고정 note).
    """
    from backend.services.build_inventory import list_cached_builds_meta
    from backend.services.window_change_candidates import collect_window_changes, resolve_window_metas

    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    rule = str(body.get("rule") or "").strip()
    from_build = _to_int(body.get("from_build"))
    to_build = _to_int(body.get("to_build"))
    if not job_url or from_build is None or to_build is None:
        return {"ok": True, "available": False, "reason": "params_required"}
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    metas = list_cached_builds_meta(job_url=job_url, cache_root=cache_root)
    pair = resolve_window_metas(metas, from_build, to_build)
    if pair is None:
        return {"ok": True, "available": False, "reason": "build_not_cached",
                "rule": rule, "from_build": from_build, "to_build": to_build}
    from_meta, to_meta = pair
    out = collect_window_changes(
        from_build_root=Path(str(from_meta.get("build_root"))),
        to_build_root=Path(str(to_meta.get("build_root"))),
    )
    return {**out, "rule": rule, "from_build": from_build, "to_build": to_build}


RULE_DEF_CACHE_NAME = "summary_rule_definition_cache.json"
_RULE_DEF_CACHE_LOCK = threading.Lock()


def _collect_rule_evidence(
    row: Dict[str, Any], metas: List[Dict[str, Any]], to_meta: Optional[Dict[str, Any]],
    *, max_diffs: int = 2, max_excerpts: int = 2, excerpt_bytes: int = 2000,
) -> tuple:
    """규칙 1개의 코드 증거(결정론) — ①해소 구간 diff ②미해소 파일 발췌.

    rule-definition과 coding-rulebook이 **같은 증거**를 써야 두 산출물이 어긋나지 않으므로
    단일 출처로 둔다(복제하면 한쪽만 고쳐지는 표류가 생긴다). 반환 (diffs, excerpts).
    """
    from backend.services.build_inventory import find_build_meta
    from backend.services.prqa_rule_trend import is_cross_module_key
    from backend.services.rule_fix_examples import collect_fix_evidence, resolve_snapshot_file

    # 파일 귀속 불가 항목(RCMA류)은 스냅샷에 실체가 없다 — 후보에서 미리 걸러 rglob 헛돌이를
    # 막고, 남은 실제 파일 후보가 max_diffs/max_excerpts 슬롯을 pseudo에 빼앗기지 않게 한다
    # (실측 C-POS-012: RCMA가 감소 1위라 잘라내면 실제 파일 2건이 증거에서 탈락했다).
    def _real(entries: Any) -> List[Dict[str, Any]]:
        return [
            f for f in (entries or [])
            if isinstance(f, dict) and f.get("scope") != "cross_module"
            and not is_cross_module_key(str(f.get("path") or ""))
        ]

    diffs: List[Dict[str, Any]] = []
    for f in _real(row.get("decreased_files"))[:max_diffs]:
        fm = find_build_meta(metas, f.get("from_build"))
        tm = find_build_meta(metas, f.get("to_build"))
        if fm is None or tm is None:
            continue
        ev = collect_fix_evidence(
            from_build_root=Path(str(fm.get("build_root"))),
            to_build_root=Path(str(tm.get("build_root"))),
            file=str(f.get("path") or ""),
        )
        if ev.get("ok"):
            diffs.append({"file": f.get("path"), "text": ev["diff"]["text"], "diff_sha": ev["diff_sha"]})
    excerpts: List[Dict[str, Any]] = []
    if to_meta is not None:
        for f in _real(row.get("files_latest"))[:max_excerpts]:
            p = resolve_snapshot_file(Path(str(to_meta.get("build_root"))), str(f.get("path") or ""))
            if p is None:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")[:excerpt_bytes]
            except OSError:
                continue
            if text.strip():
                excerpts.append({"file": f.get("path"), "text": text})
    return diffs, excerpts


@router.post("/api/summary/rule-definition")
def summary_rule_definition(req: dict) -> Dict[str, Any]:
    """팀 코딩 룰 초안(LLM on-demand) — 규칙 공식 설명+트렌드+실코드 증거를 조립해 생성.

    코드 증거(해소 diff·미해소 발췌) 0건이면 no_code_evidence 거부 — 환각 필터의 허용
    어휘가 비어 일반론 초안이 그대로 통과하는 구멍을 막는다. note(초안≠확정 룰,
    관측≠인과)는 서버 고정 주입. probe/force/캐시 규약은 rule-fix-example과 동일.
    """
    import hashlib as _hashlib

    from backend.services.build_inventory import find_build_meta, list_cached_builds_meta
    from backend.services.prqa_rule_trend import compute_rule_trend
    from workflow.rule_definition import (
        RULE_DEFINITION_NOTE,
        RULE_DEFINITION_PROMPT_VERSION,
        generate_rule_definition,
    )

    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    rule = str(body.get("rule") or "").strip()
    if not job_url or not rule:
        return {"ok": True, "available": False, "reason": "params_required"}
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))

    trend = compute_rule_trend(job_url=job_url, cache_root=cache_root, limit=10, max_rules=100)
    if not trend.get("available"):
        return {"ok": True, "available": False, "reason": trend.get("reason") or "no_cached_build"}
    row = next((r for r in trend.get("rules") or [] if r.get("rule") == rule), None)
    if row is None:
        return {"ok": True, "available": False, "reason": "rule_not_in_trend", "rule": rule}

    metas = list_cached_builds_meta(job_url=job_url, cache_root=cache_root)
    rng = trend.get("observed_range") or {}
    to_meta = find_build_meta(metas, rng.get("to_build"))

    evidence_diffs, unresolved_excerpts = _collect_rule_evidence(row, metas, to_meta)
    if not evidence_diffs and not unresolved_excerpts:
        # 증거 0건의 사유를 구분한다 — 파일 귀속이 원리적으로 없는 규칙(RCMA류 집계만 존재)과
        # '스냅샷을 못 찾음'은 사용자가 취할 조치가 전혀 다르다.
        only_pseudo = bool(
            (row.get("files_latest") or row.get("decreased_files"))
            and all(
                f.get("scope") == "cross_module"
                for f in (row.get("files_latest") or []) + (row.get("decreased_files") or [])
            )
        )
        return {"ok": True, "available": False, "rule": rule,
                "reason": "cross_module_only" if only_pseudo else "no_code_evidence"}

    # LLM 미설정이면 model=None — join이 TypeError로 죽지 않게 빈 문자열로(키 일관성 유지).
    model = _expected_insight_model() or ""
    ex_sha = _hashlib.sha256(
        "\n".join(e["text"] for e in unresolved_excerpts).encode("utf-8", "ignore")
    ).hexdigest()[:16]
    key = _hashlib.sha256("|".join([
        rule, model, str(RULE_DEFINITION_PROMPT_VERSION),
        ",".join(sorted(e["diff_sha"] for e in evidence_diffs)), ex_sha,
    ]).encode()).hexdigest()
    cache_path = (
        Path(str(to_meta.get("reports_dir"))) / RULE_DEF_CACHE_NAME if to_meta is not None else None
    )
    hit = None
    if cache_path is not None:
        with _RULE_DEF_CACHE_LOCK:
            entries = _fix_cache_load(cache_path)
            hit = entries.get(key)
    probe = bool(body.get("probe"))
    force = bool(body.get("force"))
    if hit and not force:
        return {**hit, "cached": True}
    if probe:
        return {
            "ok": True, "available": True, "cached": False, "rule": rule,
            "evidence_used": {"fix_diffs": len(evidence_diffs),
                              "unresolved_excerpts": len(unresolved_excerpts)},
        }

    gen = generate_rule_definition(
        rule=rule, description=row.get("description"), trend_row=row,
        evidence_diffs=evidence_diffs, unresolved_excerpts=unresolved_excerpts,
    )
    payload: Dict[str, Any] = {
        "ok": True, "available": True, "reason": None, "rule": rule,
        "description": row.get("description"),
        "trend": {k: row.get(k) for k in ("classification", "first", "latest", "net")},
        "evidence_used": {"fix_diffs": len(evidence_diffs),
                          "unresolved_excerpts": len(unresolved_excerpts)},
        "note": RULE_DEFINITION_NOTE,
        "definition": gen["definition"],
        "ai_enriched": gen["ai_enriched"],
        "enrich_reason": gen["enrich_reason"],
        "model": gen["model"],
        "prompt_version": RULE_DEFINITION_PROMPT_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if cache_path is not None:
        # RMW 원자화(락) — LLM 호출 밖에서 재로드(형제 엔트리 lost-update 방지, fix-example과 동일).
        with _RULE_DEF_CACHE_LOCK:
            entries = _fix_cache_load(cache_path)
            entries[key] = payload
            _fix_cache_store(cache_path, entries)
    return {**payload, "cached": False}


RULEBOOK_CACHE_NAME = "summary_coding_rulebook_cache.json"
_RULEBOOK_LOCK = threading.Lock()


@router.post("/api/summary/coding-rulebook")
def summary_coding_rulebook(req: dict) -> Dict[str, Any]:
    """정적분석 위반 → 팀 코딩 룰북 초안(Q4) — 규칙 배치 처리 + 카테고리 묶음 + Markdown.

    기존 rule-definition은 규칙 1개씩만 냈다. 여기서는 위반 상위 규칙을 한 번에 처리해
    카테고리(필수/요구/권고/프로젝트 관례)로 묶고 문서로 내보낼 수 있게 한다.
    ⚠ 증거 0건 규칙은 룰북에 넣지 않고 제외 사유를 남긴다 — 일반론 룰이 섞이면 문서 신뢰가 깨진다.
    비용: 규칙당 LLM 1회(상한 15) → on-demand + 캐시. probe는 LLM 0회로 캐시만 조회한다.
    """
    import hashlib as _hashlib

    from backend.services.build_inventory import find_build_meta, list_cached_builds_meta
    from backend.services.prqa_rule_trend import compute_rule_trend
    from workflow.coding_rulebook import CODING_RULEBOOK_VERSION, build_rulebook, render_markdown

    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    if not job_url:
        return {"ok": True, "available": False, "reason": "job_url_required"}
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    max_rules = max(1, min(_to_int(body.get("max_rules")) or 8, 15))

    trend = compute_rule_trend(job_url=job_url, cache_root=cache_root, limit=10, max_rules=100)
    if not trend.get("available"):
        return {"ok": True, "available": False, "reason": trend.get("reason") or "no_cached_build"}
    rows = [r for r in (trend.get("rules") or []) if r.get("rule")]
    # 최신 위반이 많은 규칙부터 — 룰북은 '지금 아픈 곳'을 먼저 다뤄야 한다.
    rows.sort(key=lambda r: (-(r.get("latest") or 0), str(r.get("rule"))))
    rows = rows[:max_rules]
    if not rows:
        return {"ok": True, "available": False, "reason": "no_rules_in_trend"}

    metas = list_cached_builds_meta(job_url=job_url, cache_root=cache_root)
    rng = trend.get("observed_range") or {}
    to_meta = find_build_meta(metas, rng.get("to_build"))

    rule_inputs: List[Dict[str, Any]] = []
    for row in rows:
        diffs, excerpts = _collect_rule_evidence(row, metas, to_meta)
        # 트렌드는 규칙 행마다 description={title,enabled,group}(RCFInfo)를 직접 싣는다.
        desc = row.get("description") if isinstance(row.get("description"), dict) else None
        rule_inputs.append({
            "rule": row.get("rule"),
            "description": desc,
            "trend_row": row,
            "evidence_diffs": diffs,
            "unresolved_excerpts": excerpts,
            "counts": {"latest": row.get("latest"), "first": row.get("first")},
        })

    # 캐시 키는 증거의 **내용**을 지문화한다 — 개수만 쓰면 파일이 바뀌어도 diff가 여전히 2건이면
    # 같은 키가 되어 낡은 룰북을 서빙한다(rule-definition이 diff_sha+ex_sha를 쓰는 이유와 동일).
    model = _expected_insight_model() or ""
    ev_fingerprint = json.dumps([
        [
            i["rule"],
            sorted(str(d.get("diff_sha") or "") for d in i["evidence_diffs"]),
            _hashlib.sha256(
                "\n".join(str(x.get("text") or "") for x in i["unresolved_excerpts"]).encode("utf-8", "ignore")
            ).hexdigest()[:16],
        ]
        for i in rule_inputs
    ], ensure_ascii=False)
    key = _hashlib.sha256("|".join([
        model, str(CODING_RULEBOOK_VERSION), str(max_rules), ev_fingerprint,
    ]).encode()).hexdigest()
    cache_path = Path(str(to_meta.get("reports_dir"))) / RULEBOOK_CACHE_NAME if to_meta else None
    hit = None
    if cache_path is not None:
        with _RULEBOOK_LOCK:
            hit = _fix_cache_load(cache_path).get(key)
    if hit and not bool(body.get("force")):
        return {**hit, "cached": True}
    if bool(body.get("probe")):
        # 아직 생성 전 — 어떤 규칙이 대상이고 증거가 몇 건인지만 알린다(LLM 0회).
        return {
            "ok": True, "available": True, "cached": False, "generated": False,
            "candidates": [
                {"rule": i["rule"], "latest": (i["counts"] or {}).get("latest"),
                 "evidence": len(i["evidence_diffs"]) + len(i["unresolved_excerpts"])}
                for i in rule_inputs
            ],
        }

    book = build_rulebook(rule_inputs, max_rules=max_rules)
    payload = {
        "ok": True, "available": True, "reason": None, "generated": True,
        "build_number": (to_meta or {}).get("build_number"),
        **book,
        "markdown": render_markdown(book, project=_job_slug_label(job_url)),
        "model": model or None,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if cache_path is not None:
        with _RULEBOOK_LOCK:
            entries = _fix_cache_load(cache_path)
            entries[key] = payload
            _fix_cache_store(cache_path, entries)
    return {**payload, "cached": False}


def _job_slug_label(job_url: str) -> str:
    """문서 제목용 프로젝트 라벨 — job URL 마지막 세그먼트."""
    parts = [p for p in str(job_url or "").replace("\\", "/").split("/") if p and p != "job"]
    return parts[-1] if parts else ""


# ---------------------------------------------------------------------------
# 품질 상세 (Phase I) — 함수단위 커버리지(기존 갭) + 실패 테스트케이스
# ---------------------------------------------------------------------------


def _load_scm_function_entries(job_url: str) -> Optional[Dict[str, Any]]:
    """SCM 입력 문서(연결 문서 경로 > VectorCAST) 로드 이력의 함수 entries — 부재는 None.

    빌드 산출물에 함수단위 커버리지가 없는 프로젝트(실측 KJPDS02_PV)의 유일한 소스다.
    Jenkins/cloudium 재접근 없이 기존 잡 파일만 직독한다(backend/services/scm_vcast_functions).
    """
    if not str(job_url or "").strip():
        return None
    try:
        from backend.services.scm_vcast_functions import load_scm_function_metrics

        scm = load_scm_function_metrics(job_url)
    except Exception as exc:  # 이력 손상 등 — 빌드 경로 결과를 죽이지 않는다(fail-soft)
        _logger.debug("scm vcast function metrics load failed (%s): %s", job_url, exc)
        return None
    return scm if scm.get("available") else None


def _load_vcast_function_entries(reports_dir: Path, *, job_url: str = "") -> Dict[str, Any]:
    """함수단위 커버리지 entries 로드 — 빌드 산출물 우선, 없으면 SCM 입력 문서 폴백.

    우선순위(사용자 결정 — 빌드 우선):
      ①vectorcast_detail(구 규약) ②vectorcast.ut/it_metrics ③SCM 로드 이력(scm_vcast_job).
    실측: 캐시 전 빌드에서 vectorcast_detail은 빈 {} 이고, KJPDS02_PV류는 ②도 부재라 ③만이
    함수 커버리지를 준다(UT 1014 · IT 712). 반환 {"ut_entries", "it_entries", "source",
    "source_detail"} — source_detail은 ③일 때 잡 파일/로드 시각(출처 표기 의무).
    """
    data = _read_json(reports_dir / "analysis_summary.json") or {}
    detail = data.get("vectorcast_detail") if isinstance(data.get("vectorcast_detail"), dict) else {}
    agg = detail.get("aggregate_coverage") if isinstance(detail.get("aggregate_coverage"), dict) else {}
    det_entries = [e for e in (agg.get("entries") or []) if isinstance(e, dict)]
    if det_entries:
        return {"ut_entries": det_entries, "it_entries": [], "source": "vectorcast_detail",
                "source_detail": None}
    vc = data.get("vectorcast") if isinstance(data.get("vectorcast"), dict) else {}
    ut_sec = vc.get("ut_metrics") if isinstance(vc.get("ut_metrics"), dict) else {}
    it_sec = vc.get("it_metrics") if isinstance(vc.get("it_metrics"), dict) else {}
    ut = [e for e in (ut_sec.get("entries") or []) if isinstance(e, dict)]
    it = [e for e in (it_sec.get("entries") or []) if isinstance(e, dict)]
    if ut or it:
        return {"ut_entries": ut, "it_entries": it, "source": "vectorcast_metrics",
                "source_detail": None}
    scm = _load_scm_function_entries(job_url)
    if scm:
        return {
            "ut_entries": scm.get("ut_entries") or [],
            "it_entries": scm.get("it_entries") or [],
            "source": "scm_vcast_job",
            "source_detail": {
                "job_file": scm.get("job_file"),
                "generated_at": scm.get("generated_at"),
                "merged_sources": scm.get("merged_sources"),
                "complexity_rows": len(scm.get("complexity_rows") or []),
            },
        }
    return {"ut_entries": [], "it_entries": [], "source": None, "source_detail": None}


def _norm_unit(u: Any) -> str:
    """IT unit의 env 인스턴스 접미사 제거 — "sysctrl_main_pds.c'1" → "sysctrl_main_pds.c"."""
    s = str(u or "")
    return s.split("'", 1)[0] if "'" in s else s


def _cell_pair(cell: Any) -> Optional[tuple]:
    """{covered,total} → (covered,total). 축 자체가 없거나 비수치면 None(0으로 위장 금지)."""
    if not isinstance(cell, dict):
        return None
    try:
        return int(cell.get("covered")), int(cell.get("total"))
    except (TypeError, ValueError):
        return None


def _fold_coverage_entries(entries: List[Dict[str, Any]], axes: tuple) -> tuple:
    """(unit, subprogram) **반복 측정**을 접는다 — 합산하면 분모가 배수로 부푼다.

    VectorCAST 리포트는 같은 함수를 환경/폴더마다 다시 측정하고, 파서·병합 단계가 그 축
    식별자를 버려(`jenkins_adapter.parse_vcast_metrics_report` / `jenkins._merge_vectorcast_payloads`)
    entries에 동일 키가 여러 벌 남는다. 이를 독립 관측으로 보고 더하면 실측 IT 분모가
    2854 → 7438(2.61배)로 부풀어 커버리지가 허위로 낮아진다.

    축별 **max(covered)/max(total)** 로 접는다 — "어느 환경에서든 커버됐으면 커버"가 커버리지
    롤업의 표준 의미다(실측 `s_System_MainLoop` covered=[0,4,4,0,0]/total=[4,4,4,4,4] →
    합산 8/20=40%는 오답, 접으면 4/4). 최악값은 버리지 않고 `worst_covered`로 함께 남겨
    "재검증할 함수" 판단에 쓴다.

    ⚠ 폴딩 키는 **정규화 전 unit** — `_norm_unit`의 `'N` 절단은 서로 다른 env를 같은 unit으로
      만들 수 있어 표시에만 쓴다(실측 데이터엔 접미사가 없어 현재는 동일 결과).
    반환 (folded_rows, stats).
    """
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    order: List[tuple] = []
    for e in entries:
        key = (str(e.get("unit") or ""), str(e.get("subprogram") or ""))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(e)
    folded: List[Dict[str, Any]] = []
    duplicated = divergent = 0
    for key in order:
        grp = groups[key]
        if len(grp) > 1:
            duplicated += 1
        row = dict(grp[0])
        row_divergent = False
        for axis in axes:
            pairs = [p for p in (_cell_pair(e.get(axis)) for e in grp) if p is not None]
            if not pairs:
                continue
            if len(set(pairs)) > 1:
                row_divergent = True
            cov = max(p[0] for p in pairs)
            tot = max(p[1] for p in pairs)
            cell: Dict[str, Any] = {
                "covered": cov, "total": tot,
                "rate": round(cov / tot * 100, 1) if tot else None,
            }
            if len(pairs) > 1:
                cell["worst_covered"] = min(p[0] for p in pairs)
            row[axis] = cell
        ccns = [e.get("ccn") for e in grp if isinstance(e.get("ccn"), (int, float))]
        if ccns:
            row["ccn"] = max(ccns)
        if len(grp) > 1:
            row["measurements"] = len(grp)
        if row_divergent:
            row["divergent"] = True
            divergent += 1
        folded.append(row)
    stats = {
        "raw_entries": len(entries), "folded_entries": len(folded),
        "duplicated_keys": duplicated, "divergent_keys": divergent,
        "method": "max_covered_max_total",
        "note": "같은 (unit, subprogram)의 환경별 반복 측정을 접었습니다 — 축별 최대 커버/최대 총계",
    }
    return folded, stats


_UT_AXES = ("statements", "branches")


def _aggregate_ut_coverage(entries: List[Dict[str, Any]], worst_limit: int) -> Dict[str, Any]:
    """UT(구문/분기) 함수단위 집계 — 구 quality-detail 로직 이관 + 분기 totals 합산(L1).

    반복 측정은 `_fold_coverage_entries`로 먼저 접는다(합산 금지 — 그 docstring 참조).
    """
    entries, fold_stats = _fold_coverage_entries(entries, _UT_AXES)
    cov_st = st_total = 0
    cov_br = br_total = 0
    fully = 0
    uncovered_rows: List[Dict[str, Any]] = []
    rated: List[Dict[str, Any]] = []
    for e in entries:
        st = e.get("statements") if isinstance(e.get("statements"), dict) else {}
        try:
            c_i, t_i = int(st.get("covered")), int(st.get("total"))
        except (TypeError, ValueError):
            continue
        cov_st += c_i
        st_total += t_i
        br = e.get("branches") if isinstance(e.get("branches"), dict) else {}
        try:
            cov_br += int(br.get("covered"))
            br_total += int(br.get("total"))
        except (TypeError, ValueError):
            pass  # 분기 결측 행 — 구문 집계는 계속(분기 totals만 미포함)
        if t_i > 0 and c_i == t_i:
            fully += 1
        if t_i > 0 and c_i == 0:
            uncovered_rows.append({"unit": e.get("unit"), "subprogram": e.get("subprogram")})
        r = st.get("rate")
        try:
            r_f = float(r) if r is not None else None
        except (TypeError, ValueError):
            r_f = None
        if r_f is not None and t_i > 0:
            rated.append({
                "unit": e.get("unit"), "subprogram": e.get("subprogram"), "ccn": e.get("ccn"),
                "statements": st, "branches": e.get("branches"),
                **({"measurements": e["measurements"]} if e.get("measurements") else {}),
                **({"divergent": True} if e.get("divergent") else {}),
            })
    rated.sort(key=lambda e: (float((e.get("statements") or {}).get("rate") or 0), str(e.get("subprogram"))))
    return {
        "available": True,
        "totals": {
            "functions": len(entries),
            "fully_covered": fully,
            "uncovered": len(uncovered_rows),
            "statements": {
                "covered": cov_st, "total": st_total,
                "rate": round(cov_st / st_total * 100, 1) if st_total else None,
            },
            "branches": {
                "covered": cov_br, "total": br_total,
                "rate": round(cov_br / br_total * 100, 1) if br_total else None,
            },
        },
        "worst": rated[:worst_limit],
        "uncovered": uncovered_rows[:50],
        "fold": fold_stats,  # 접힌 반복 측정 수 — 침묵 금지(수치가 왜 달라졌는지의 근거)
    }


_IT_AXES = ("functions", "function_calls", "statements", "branches")


def _aggregate_it_coverage(entries: List[Dict[str, Any]], worst_limit: int) -> Dict[str, Any]:
    """IT 집계 — 소스마다 축이 다르므로 **존재하는 축만** 집계한다.

    실측 스키마 편차:
      - 빌드 산출물 IT: functions(진입) · function_calls (구문/분기 없음)
      - SCM 로드 이력 IT: statements · branches · function_calls (**functions 없음**)
    구 코드는 functions 결측 행을 통째로 skip해 SCM 소스에선 IT가 전부 사라졌다. 축별로
    독립 합산하고 metrics_present로 보유 축을 표기한다(결측 축은 None — 0% 위장 금지).
    unit엔 env 인스턴스 접미사('N)가 붙을 수 있어 표기용으로 정규화한다.

    ⚠ 합산 **전에** `_fold_coverage_entries`로 환경별 반복 측정을 접는다 — IT는 UT와 달리
    반복이 지배적이라(실측 712행 = 259함수 × 최대 5환경) 접지 않으면 분모가 2.61배가 된다.
    """
    entries, fold_stats = _fold_coverage_entries(entries, _IT_AXES)
    sums: Dict[str, List[int]] = {axis: [0, 0] for axis in _IT_AXES}
    present: Dict[str, bool] = {axis: False for axis in _IT_AXES}
    rated: List[Dict[str, Any]] = []
    for e in entries:
        row_axes: Dict[str, Any] = {}
        gap_rate: Optional[float] = None
        for axis in _IT_AXES:
            pair = _cell_pair(e.get(axis))
            if pair is None:
                continue
            cov, tot = pair
            present[axis] = True
            sums[axis][0] += cov
            sums[axis][1] += tot
            row_axes[axis] = e.get(axis)
            # 미달 판정 기준: 진입(functions) 우선, 없으면 구문(statements) — 소스별 주 메트릭.
            if tot > 0 and cov < tot and axis in ("functions", "statements") and gap_rate is None:
                gap_rate = cov / tot
        if gap_rate is not None:
            rated.append({
                **({"measurements": e["measurements"]} if e.get("measurements") else {}),
                **({"divergent": True} if e.get("divergent") else {}),
                "unit": _norm_unit(e.get("unit")), "subprogram": e.get("subprogram"),
                "ccn": e.get("ccn"), "gap_rate": round(gap_rate, 4), **row_axes,
            })
    rated.sort(key=lambda r: (float(r.get("gap_rate") or 0), str(r.get("subprogram"))))
    totals: Dict[str, Any] = {"entries": len(entries)}
    for axis in _IT_AXES:
        if not present[axis]:
            totals[axis] = None  # 이 소스엔 없는 축 — 0/0이 아니라 부재
            continue
        cov, tot = sums[axis]
        totals[axis] = {"covered": cov, "total": tot,
                        "rate": round(cov / tot * 100, 1) if tot else None}
    return {
        "available": True,
        "totals": totals,
        "metrics_present": present,
        "worst": rated[:worst_limit],
        "fold": fold_stats,
    }


def _find_vcast_rag(reports_dir: Path) -> Optional[Path]:
    """vectorcast_rag.json 실경로 — ①루트(구 가정) ②vectorcast_rag/ 하위(실물 정규) ③rglob 최신.

    실측: 전 빌드에서 파일은 reports/vectorcast_rag/vectorcast_rag.json 하위폴더에만 있다 —
    루트만 보던 구 코드는 항상 available:false(L1 경로 버그 교정, 같은 버그가 2곳이었음).
    """
    direct = reports_dir / "vectorcast_rag.json"
    if direct.exists():
        return direct
    nested = reports_dir / "vectorcast_rag" / "vectorcast_rag.json"
    if nested.exists():
        return nested
    try:
        found = [p for p in reports_dir.rglob("vectorcast_rag.json") if p.is_file()]
        if found:
            return max(found, key=lambda p: p.stat().st_mtime)
    except OSError:
        pass
    return None


@router.post("/api/summary/quality-detail")
def summary_quality_detail(req: dict) -> Dict[str, Any]:
    """함수(subprogram)단위 커버리지(UT 구문/분기 + IT 축) + 실패 TC.

    소스 우선순위: vectorcast_detail(구 규약) → vectorcast.ut/it_metrics → SCM 로드 이력
    (N1 — 빌드 산출물에 함수 커버리지가 없는 프로젝트의 유일 경로). source/source_detail로
    출처를 항상 표기한다. 섹션별 available:false 분리 — 한쪽 부재가 다른 쪽을 죽이지 않는다.
    """
    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    if not job_url:
        return {"ok": True, "available": False, "reason": "job_url_required"}
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    builds = list_cached_builds(job_url=job_url, cache_root=cache_root)
    build_req = _to_int(body.get("build_number"))
    target = _find_build(builds, build_req) if build_req is not None else (builds[0] if builds else None)
    if target is None:
        return {"ok": True, "available": False, "reason": "no_cached_build"}
    reports_dir = Path(str(target.get("reports_dir") or ""))
    worst_limit = max(1, min(_to_int(body.get("worst_limit")) or 15, 50))

    loaded = _load_vcast_function_entries(reports_dir, job_url=job_url)
    if loaded["ut_entries"]:
        function_coverage: Dict[str, Any] = _aggregate_ut_coverage(loaded["ut_entries"], worst_limit)
        function_coverage["source"] = loaded["source"]
        function_coverage["source_detail"] = loaded.get("source_detail")
    else:
        function_coverage = {"available": False, "reason": "no_function_coverage_source"}
    if loaded["it_entries"]:
        it_coverage: Dict[str, Any] = _aggregate_it_coverage(loaded["it_entries"], worst_limit)
        it_coverage["source"] = loaded["source"]
        it_coverage["source_detail"] = loaded.get("source_detail")
    else:
        it_coverage = {"available": False, "reason": "no_it_metrics"}

    rag_path = _find_vcast_rag(reports_dir)
    failures = _vcast_failures(rag_path)
    if rag_path is not None:
        failed_testcases: Dict[str, Any] = {
            "available": True, "count": len(failures), "items": failures,
            "source": "build_artifact", "source_path": str(rag_path),
        }
    else:
        # 빌드에 실행 로그가 없으면 SCM 로드 이력의 failures/집계로 폴백(같은 정직성 규약).
        scm = _load_scm_function_entries(job_url)
        if scm:
            scm_failures = [f for f in (scm.get("failures") or []) if isinstance(f, dict)]
            failed_testcases = {
                "available": True, "count": len(scm_failures), "items": scm_failures,
                "source": "scm_vcast_job", "source_path": None,
                "test_summary": scm.get("test_summary"),
                "generated_at": scm.get("generated_at"),
            }
        else:
            failed_testcases = {"available": False, "reason": "no_vectorcast_rag"}
    return {
        "ok": True,
        "available": True,
        "reason": None,
        "build_number": target.get("build_number"),
        "coverage_source": loaded["source"],
        "coverage_source_detail": loaded.get("source_detail"),
        "function_coverage": function_coverage,
        "it_coverage": it_coverage,
        "failed_testcases": failed_testcases,
    }


# ---------------------------------------------------------------------------
# 테스트 설계 어드바이저 (Phase L2) — 커버리지×ASIL×ccn 기법 매핑 + 설계-시험 갭
# ---------------------------------------------------------------------------


# 추적 링크 테이블은 빌드 산출물(실측 2.2MB · 링크 11,747건)이라 파싱이 40ms 든다. 한 요청이
# 이걸 3번 읽는 경로가 있어(arch 지문 · ASIL 인덱스 · 설계-시험 갭) (경로, mtime_ns, size) 키로
# 1회화한다. 완료된 빌드 산출물은 불변이므로 stat이 같으면 내용도 같다(scm_vcast_functions와 동일 규약).
_LINK_TABLE_CACHE: Dict[tuple, Optional[Dict[str, Any]]] = {}
_ASIL_MAP_CACHE: Dict[tuple, Dict[str, Any]] = {}
_LINK_TABLE_LOCK = threading.Lock()
_LINK_TABLE_CACHE_MAX = 4


def _stat_key(path: Path) -> Optional[tuple]:
    try:
        st = path.stat()
    except OSError:
        return None
    return (str(path), st.st_mtime_ns, st.st_size)


def _load_trace_link_table(build_root: Path, reports_dir: Path) -> Optional[Dict[str, Any]]:
    """trace_link_table.json — 빌드 report/ 우선, reports_dir 폴백(경로 규약 이원 대응). stat 키 캐시."""
    for cand in (Path(str(build_root)) / "report" / "trace_link_table.json",
                 reports_dir / "trace_link_table.json"):
        key = _stat_key(cand)
        if key is None:
            continue
        with _LINK_TABLE_LOCK:
            if key in _LINK_TABLE_CACHE:
                cached = _LINK_TABLE_CACHE[key]
                if cached:
                    return cached
                continue  # 캐시된 '이 파일은 비어있음' — 다음 후보로
        table = _read_json(cand)
        table = table if isinstance(table, dict) and table else None
        with _LINK_TABLE_LOCK:
            if len(_LINK_TABLE_CACHE) >= _LINK_TABLE_CACHE_MAX:
                _LINK_TABLE_CACHE.clear()
            _LINK_TABLE_CACHE[key] = table
        if table:
            return table
    return None


def _propagated_asil(build_root: Path, reports_dir: Path) -> Dict[str, Any]:
    """요구 ASIL 역전파 결과(N2) — 링크 테이블 stat 키로 1회화(11,747건 조인 재실행 회피)."""
    from workflow.asil_propagation import build_function_asil_map

    keys = tuple(
        k for k in (
            _stat_key(Path(str(build_root)) / "report" / "trace_link_table.json"),
            _stat_key(reports_dir / "trace_link_table.json"),
        ) if k is not None
    )
    with _LINK_TABLE_LOCK:
        hit = _ASIL_MAP_CACHE.get(keys) if keys else None
    if hit is not None:
        return hit
    result = build_function_asil_map(_load_trace_link_table(build_root, reports_dir))
    if keys:
        with _LINK_TABLE_LOCK:
            if len(_ASIL_MAP_CACHE) >= _LINK_TABLE_CACHE_MAX:
                _ASIL_MAP_CACHE.clear()
            _ASIL_MAP_CACHE[keys] = result
    return result


def clear_summary_caches() -> None:
    """테스트/운영 진단용 — 링크 테이블·ASIL 맵 프로세스 캐시 초기화."""
    with _LINK_TABLE_LOCK:
        _LINK_TABLE_CACHE.clear()
        _ASIL_MAP_CACHE.clear()


def _coverage_index(reports_dir: Path, *, job_url: str = "") -> Dict[str, Dict[str, Any]]:
    """{정규화 함수명: {statement, branch, ccn, metric_source, measurements}} — 0..1 스케일 통일.

    두 축을 지킨다:
    1) **레벨 우선** — UT가 1순위(단위 구조 커버리지), UT에 없는 함수만 IT로 보완하고
       metric_source로 출처를 남긴다. UT와 IT는 목표가 달라 절대 합치지 않는다(N4에서 IT
       미실행을 단위 미커버로 세다 허위 332건을 낸 전례).
    2) **같은 레벨 안의 반복 측정은 최악값** — 같은 함수가 여러 unit/env에 걸쳐 측정되면
       최선값으로 접히는 순간 갭이 은폐된다(coverage_gap.load_function_coverage·
       test_design_advisor와 동일 규약). 구 구현은 first-wins라 **입력 순서에 따라** 값이
       달라졌다(실측 writeblock: 같은 UT 안에 0.7647과 0.9가 공존 — 오늘은 우연히 나쁜 쪽이
       뽑히지만 보장이 없는 잠복 결함). ccn만 최대값(보수적).
    """
    from workflow.coverage_gap import _norm_fn
    from workflow.test_design_advisor import _rate01

    loaded = _load_vcast_function_entries(reports_dir, job_url=job_url)
    out: Dict[str, Dict[str, Any]] = {}
    for level, entries in (("ut", loaded.get("ut_entries") or []), ("it", loaded.get("it_entries") or [])):
        for e in entries:
            if not isinstance(e, dict):
                continue
            key = _norm_fn(e.get("subprogram"))
            if not key:
                continue
            prev = out.get(key)
            if prev is not None and prev["metric_source"] != level:
                continue  # 레벨 우선 — UT로 채운 함수를 IT로 덮지 않는다
            ccn = e.get("ccn") if isinstance(e.get("ccn"), (int, float)) else None
            rec = {
                "statement": _rate01(e.get("statements")),
                "branch": _rate01(e.get("branches")),
                "ccn": ccn,
                "metric_source": level,
                "unit": e.get("unit"),
                "measurements": 1,
            }
            if prev is None:
                out[key] = rec
                continue
            prev["measurements"] += 1
            for metric in ("statement", "branch"):
                a, b = prev.get(metric), rec.get(metric)
                if isinstance(b, (int, float)) and (not isinstance(a, (int, float)) or b < a):
                    prev[metric] = b          # 최악값 — 은폐 금지
            if isinstance(ccn, (int, float)) and (not isinstance(prev.get("ccn"), (int, float)) or ccn > prev["ccn"]):
                prev["ccn"] = ccn             # 복잡도는 최대(보수적)
    return out


def _asil_index(build_root: Path, reports_dir: Path, *, job_url: str = "") -> Dict[str, Any]:
    """함수 ASIL 인덱스 — 소스 주석(arch 캐시) + 요구 역전파(추적 링크) 병합(N2).

    반환 {"by_function", "counts", "propagation"} — 주석이 0건인 프로젝트에서도 등급 축이
    살아야 하므로 역전파가 주 경로다(실측 KJPDS02_PV: 주석 0 → 역전파 385함수).
    """
    from workflow.asil_propagation import merge_asil_sources

    arch = _arch_metrics_cached(build_root, reports_dir, job_url=job_url)
    comment_map = ((arch or {}).get("asil_functions") or {}).get("by_function") or {}
    propagated = _propagated_asil(build_root, reports_dir)
    merged, counts = merge_asil_sources(comment_map, propagated)
    return {
        "by_function": merged,
        "counts": counts,
        "propagation": {k: propagated.get(k) for k in ("available", "reason", "stats", "note")},
    }


def _changed_functions_from_cache(reports_dir: Path) -> Dict[str, Any]:
    """캐시된 baseline-diff 결과에서 변경 함수 집합을 회수(N4의 '변경 축' 재료).

    여기서 diff를 새로 계산하지 않는다 — 스냅샷 2벌 파싱은 수 초라 test-design 임계경로에
    맞지 않는다. 사용자가 베이스라인 비교를 한 번이라도 열었으면 캐시가 있고, 없으면
    available:false로 정직하게 축을 비활성화한다(증거부재≠변경 없음).
    """
    from workflow.coverage_gap import _norm_fn

    try:
        cands = sorted(reports_dir.glob("summary_baseline_diff_*.json"),
                       key=lambda p: p.stat().st_mtime_ns, reverse=True)
    except OSError:
        return {"available": False, "reason": "reports_dir_unreadable", "functions": set()}
    for path in cands[:3]:
        data = _read_json(path)
        result = (data or {}).get("result")
        if not isinstance(result, dict) or not result.get("available"):
            continue
        fns = result.get("functions") or {}
        names: set = set()
        for key in ("new", "deleted", "signature_changed", "body_changed"):
            for f in fns.get(key) or []:
                n = _norm_fn((f or {}).get("name"))
                if n:
                    names.add(n)
        if not names:
            continue
        return {
            "available": True, "functions": names,
            "baseline_build": (result.get("baseline") or {}).get("build_number"),
            "target_build": (result.get("target") or {}).get("build_number"),
            "count": len(names),
        }
    return {"available": False, "reason": "no_baseline_diff_cache", "functions": set()}


def _compute_test_design_payload(build_root: Path, reports_dir: Path, *, job_url: str = "") -> Dict[str, Any]:
    """test-design 조립(결정론) — 엔드포인트와 ai-insight(Phase M)가 공유.

    무캐시: 이미 로드된 JSON에 대한 순수 산술(수십 ms) — 디스크 캐시는 무효화 버그 표면만
    늘린다(계획 판정). ASIL은 주석(arch 캐시) + 요구 역전파(N2) 병합 인덱스를 쓴다 —
    주석이 0건인 프로젝트에서 축이 통째로 죽던 것을 되살린다.
    """
    from workflow.test_design_advisor import (
        MCDC_NOTE,
        TECHNIQUE_CATALOG,
        TEST_DESIGN_VERSION,
        build_coverage_rows,
        compute_design_test_gap,
        derive_technique_recommendations,
    )

    loaded = _load_vcast_function_entries(reports_dir, job_url=job_url)
    asil_idx = _asil_index(build_root, reports_dir, job_url=job_url)
    asil_by_fn = asil_idx["by_function"]
    counts = asil_idx["counts"]
    if not asil_by_fn:
        asil_source = "no_asil_source"
    elif counts.get("comment_asil") and counts.get("uds_link"):
        asil_source = "comment_asil+uds_link"
    else:
        asil_source = "comment_asil" if counts.get("comment_asil") else "uds_link"
    changed = _changed_functions_from_cache(reports_dir)

    if loaded["ut_entries"] or loaded["it_entries"]:
        rows = build_coverage_rows(
            loaded["ut_entries"], loaded["it_entries"], asil_by_fn,
            changed_functions=changed["functions"] if changed.get("available") else None,
        )
        recs = derive_technique_recommendations(rows)
        with_asil = sum(1 for r in rows if r["asil"])
        ut_rows = sum(1 for r in rows if r.get("metric_set") == "ut")
        technique: Dict[str, Any] = {
            "available": True,
            "source_coverage": loaded["source"],
            "source_detail": loaded.get("source_detail"),
            "asil_source": asil_source,
            "asil_counts": counts,
            "asil_propagation": asil_idx["propagation"],
            # 조인 성립 수를 항상 표면화(침묵 미조인 금지 — 함수명 규약이 프로젝트마다 다르다).
            "coverage_join": {"entries": len(rows), "ut_rows": ut_rows,
                              "it_rows": len(rows) - ut_rows,
                              "with_asil": with_asil, "asil_unknown": len(rows) - with_asil},
            "changed_axis": {k: v for k, v in changed.items() if k != "functions"},
            **recs,
        }
    else:
        technique = {"available": False, "reason": "no_coverage_entries"}

    gap = compute_design_test_gap(_load_trace_link_table(build_root, reports_dir))
    return {
        "version": TEST_DESIGN_VERSION,
        "catalog": TECHNIQUE_CATALOG,
        "technique_recommendations": technique,
        "design_test_gap": gap,
        "mcdc_note": MCDC_NOTE,
    }


TEST_CASE_DRAFT_CACHE_NAME = "summary_test_case_draft_cache.json"
_TEST_CASE_CACHE_LOCK = threading.Lock()


@router.post("/api/summary/test-case-draft")
def summary_test_case_draft(req: dict) -> Dict[str, Any]:
    """함수 1개의 시험 케이스 초안 — 결정론 골격 + Gemini(on-demand, 디스크 캐시).

    소스 본문·파라미터·전역·호출 + 커버리지/ASIL/ccn을 근거로 케이스 표를 만든다. 본문에
    없는 식별자를 인용한 케이스는 폐기되고(환각 필터), LLM 미설정/실패여도 결정론 골격
    (권고 기법·최소 TC 추정·경계값 후보)은 항상 반환한다. probe/force/캐시 규약은
    rule-fix-example과 동일.
    """
    import hashlib as _hashlib

    from backend.services.source_function_lookup import lookup_function
    from workflow.coverage_gap import _norm_fn
    from workflow.test_case_draft import (
        TEST_CASE_DRAFT_NOTE,
        TEST_CASE_DRAFT_PROMPT_VERSION,
        generate_test_case_draft,
    )

    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    function = str(body.get("function") or "").strip()
    if not job_url or not function:
        return {"ok": True, "available": False, "reason": "params_required"}
    unit = str(body.get("unit") or "").strip() or None
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    builds = list_cached_builds(job_url=job_url, cache_root=cache_root)
    build_req = _to_int(body.get("build_number"))
    target = _find_build(builds, build_req) if build_req is not None else (builds[0] if builds else None)
    if target is None:
        return {"ok": True, "available": False, "reason": "no_cached_build"}
    build_root = Path(str(target.get("build_root") or ""))
    reports_dir = Path(str(target.get("reports_dir") or ""))

    # 소스 스냅샷은 최신 빌드에 없을 수 있다 — has_source 빌드 중 최신을 별도로 고른다.
    src_meta = next(
        (b for b in builds if (Path(str(b.get("build_root") or "")) / "source" / ".source_complete").exists()),
        None,
    )
    if src_meta is None:
        return {"ok": True, "available": False, "reason": "no_source_snapshot"}
    src_root = Path(str(src_meta.get("build_root")))

    found = lookup_function(src_root, function, unit)
    if not found.get("ok"):
        return {"ok": True, "available": False, "reason": found.get("reason"),
                "function": function, "candidates": found.get("candidates")}

    key_fn = _norm_fn(function)
    cov = (_coverage_index(reports_dir, job_url=job_url) or {}).get(key_fn) or {}
    asil_rec = (_asil_index(build_root, reports_dir, job_url=job_url)["by_function"] or {}).get(key_fn) or {}
    design = _compute_test_design_payload(build_root, reports_dir, job_url=job_url)
    rec = next(
        (i for i in ((design.get("technique_recommendations") or {}).get("items") or [])
         if _norm_fn(i.get("function")) == key_fn),
        {},
    )
    context = {
        "function": function, "unit": unit or cov.get("unit"),
        "signature": found.get("signature"), "params": found.get("params"),
        "globals": found.get("globals"), "calls": found.get("calls"),
        "statement": cov.get("statement"), "branch": cov.get("branch"), "ccn": cov.get("ccn"),
        "asil": asil_rec.get("asil") or found.get("asil"),
        "asil_source": asil_rec.get("source") or ("comment_asil" if found.get("asil") else None),
        "gap_kind": rec.get("gap_kind"),
        "techniques": rec.get("techniques") or ["requirements_based", "boundary_values"],
    }

    model = _expected_insight_model() or ""
    body_sha = _hashlib.sha256(str(found.get("body") or "").encode("utf-8", "ignore")).hexdigest()[:16]
    cov_sig = f"{cov.get('statement')}|{cov.get('branch')}|{cov.get('ccn')}|{context['asil']}|{context['gap_kind']}"
    cache_key = _hashlib.sha256("|".join([
        key_fn, body_sha, cov_sig, model, str(TEST_CASE_DRAFT_PROMPT_VERSION),
    ]).encode()).hexdigest()
    cache_path = reports_dir / TEST_CASE_DRAFT_CACHE_NAME
    with _TEST_CASE_CACHE_LOCK:
        hit = _fix_cache_load(cache_path).get(cache_key)
    if hit and not bool(body.get("force")):
        return {**hit, "cached": True}
    if bool(body.get("probe")):
        return {"ok": True, "available": True, "cached": False, "function": function,
                "file": found.get("file")}

    gen = generate_test_case_draft(context=context, source_excerpt=str(found.get("body") or ""))
    payload: Dict[str, Any] = {
        "ok": True, "available": True, "reason": None,
        "function": function, "unit": context["unit"], "file": found.get("file"),
        "signature": found.get("signature"),
        "body_truncated": bool(found.get("body_truncated")),
        "context": {k: context[k] for k in ("statement", "branch", "ccn", "asil", "asil_source", "gap_kind")},
        "deterministic": gen["deterministic"],
        "cases": gen["cases"],
        "notes": gen["notes"],
        "dropped_cases": gen["dropped_cases"],
        "ai_enriched": gen["ai_enriched"],
        "enrich_reason": gen["enrich_reason"],
        "model": gen["model"],
        "prompt_version": TEST_CASE_DRAFT_PROMPT_VERSION,
        "note": TEST_CASE_DRAFT_NOTE,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    # RMW 원자화 — LLM 호출 밖에서 재로드(형제 엔트리 lost-update 방지, fix-example과 동일).
    with _TEST_CASE_CACHE_LOCK:
        entries = _fix_cache_load(cache_path)
        entries[cache_key] = payload
        _fix_cache_store(cache_path, entries)
    return {**payload, "cached": False}


@router.post("/api/summary/test-design")
def summary_test_design(req: dict) -> Dict[str, Any]:
    """테스트 설계 어드바이저(결정론, LLM 0회) — 기법 권고 + 설계-시험 갭. 섹션별 available 분리."""
    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    if not job_url:
        return {"ok": True, "available": False, "reason": "job_url_required"}
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    builds = list_cached_builds(job_url=job_url, cache_root=cache_root)
    build_req = _to_int(body.get("build_number"))
    target = _find_build(builds, build_req) if build_req is not None else (builds[0] if builds else None)
    if target is None:
        return {"ok": True, "available": False, "reason": "no_cached_build"}
    payload = _compute_test_design_payload(
        Path(str(target.get("build_root") or "")), Path(str(target.get("reports_dir") or "")),
        job_url=job_url,
    )
    return {
        "ok": True, "available": True, "reason": None,
        "build_number": target.get("build_number"),
        **payload,
    }


# ---------------------------------------------------------------------------
# 베이스라인→최신 변화 (Phase H) — change-log 비의존 스냅샷 직접 비교
# ---------------------------------------------------------------------------


def _snapshot_stat_key(src: Path) -> Optional[Dict[str, Any]]:
    """스냅샷 트리의 stat 요약 — 캐시 키. 재sync로 트리가 바뀌면 값이 달라진다.

    ⚠ 이 키를 만드는 것 자체가 rglob 전수 stat이다(실측 13빌드 4,810파일 ≈ 1.9초). 한 요청에서
    빌드마다 여러 번 부르지 말 것 — 호출측이 결과를 재사용해야 한다.
    """
    files = 0
    total = 0
    mtime_max = 0.0
    try:
        for p in src.rglob("*"):
            if p.is_file():
                st = p.stat()
                files += 1
                total += st.st_size
                mtime_max = max(mtime_max, st.st_mtime)
    except OSError:
        return None
    return {"file_count": files, "total_bytes": total, "mtime_max": round(mtime_max, 3)}


def _snapshot_manifest_cached(meta: Dict[str, Any]) -> tuple:
    """(content_sha, manifest) — reports_dir에 함께 캐시.

    manifest({상대경로: sha1})가 있으면 **두 스냅샷의 파일 축 비교가 dict 연산으로 끝난다**.
    빌드 N개를 한 베이스라인에 비교할 때 rglob+sha1을 N번 반복하지 않는 통로다.
    구 캐시(`{key, sha}`만 있는 파일)는 sha 조회엔 그대로 쓰이고, manifest가 필요할 때만
    재계산해 additive로 채운다 — 배포된 캐시를 무효화하지 않는다.
    """
    from backend.services.baseline_diff import content_sha_from_manifest, source_file_manifest

    src = Path(str(meta.get("build_root") or "")) / "source"
    if not src.is_dir():
        return None, None
    key = _snapshot_stat_key(src)
    if key is None:
        return None, None
    cache_path = Path(str(meta.get("reports_dir") or "")) / "source_content_sha.json"
    cached = _read_json(cache_path)
    if isinstance(cached, dict) and cached.get("key") == key:
        manifest = cached.get("manifest")
        if isinstance(manifest, dict) and manifest:
            return str(cached.get("sha") or content_sha_from_manifest(manifest)), manifest
    manifest = source_file_manifest(src)
    sha = content_sha_from_manifest(manifest)
    if sha:
        _write_cache_atomic(cache_path, {"key": key, "sha": sha, "manifest": manifest})
    return sha, manifest


def _snapshot_content_sha_cached(meta: Dict[str, Any]) -> Optional[str]:
    """빌드 소스 스냅샷의 내용 지문 — reports_dir에 캐시(147파일 sha1 ≈ 0.18초).

    sha만 필요한 호출처(동일 트리 그룹·기본 baseline 선택)는 manifest 없는 구 캐시로도
    히트한다 — manifest를 얻자고 재계산을 유발하지 않는다.
    """
    from backend.services.baseline_diff import source_content_sha

    src = Path(str(meta.get("build_root") or "")) / "source"
    if not src.is_dir():
        return None
    key = _snapshot_stat_key(src)
    if key is None:
        return None
    cache_path = Path(str(meta.get("reports_dir") or "")) / "source_content_sha.json"
    cached = _read_json(cache_path)
    if isinstance(cached, dict) and cached.get("key") == key and cached.get("sha"):
        return str(cached["sha"])
    sha = source_content_sha(src)
    if sha:
        _write_cache_atomic(cache_path, {"key": key, "sha": sha})
    return sha


def _source_checkout_iso(meta: Dict[str, Any]) -> Optional[str]:
    """소스 스냅샷을 **언제 받아왔는지**(빌드 시각이 아니라 체크아웃 시각).

    둘이 크게 어긋나면(빌드 5월 / 체크아웃 오늘) 그 스냅샷은 빌드 당시 코드가 아니라
    나중에 받은 HEAD다 — 사용자가 수치를 믿기 전에 알아야 할 사실이다.
    """
    sentinel = Path(str(meta.get("build_root") or "")) / "source" / ".source_complete"
    try:
        return datetime.fromtimestamp(sentinel.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return None


def _checkout_lag_days(meta: Dict[str, Any]) -> Optional[float]:
    """빌드 시각 → 소스 체크아웃 시각의 지연(일).

    크면 그 스냅샷은 **빌드 당시 코드가 아니라 나중에 받은 트리**다(실측 #111: 빌드 05-19,
    체크아웃 07-27 = 69일). 임계값으로 판정하지 않고 값만 노출한다 — 백필은 원래 나중에
    하는 것이라 자의적 컷오프는 정상 데이터를 오염으로 몰 수 있다. 판단은 사용자 몫.
    """
    built = str(meta.get("timestamp_iso") or "")
    checked = _source_checkout_iso(meta)
    if not built or not checked:
        return None
    try:
        return round((datetime.fromisoformat(checked) - datetime.fromisoformat(built)).total_seconds() / 86400, 1)
    except (TypeError, ValueError):
        return None


def _snapshot_groups(with_src: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """내용이 동일한 스냅샷끼리 묶는다 — 2개 이상이면 그 구간은 **비교가 성립하지 않는다**.

    실측 KJPDS02_PV: #111~#121·#123 열 개 빌드가 바이트 동일(백필이 전부 같은 SVN HEAD를
    받았다). 열 빌드 동안 코드가 한 글자도 안 바뀔 리 없으므로 이는 스냅샷 재사용 신호다.
    그룹을 표면화해야 사용자가 "왜 변경이 0인가"를 알고 다른 쌍을 고를 수 있다.
    """
    by_sha: Dict[str, List[Any]] = {}
    for meta in with_src:
        sha = _snapshot_content_sha_cached(meta)
        if sha:
            by_sha.setdefault(sha, []).append(meta.get("build_number"))
    return [
        {"builds": sorted(nums, reverse=True), "count": len(nums)}
        for nums in by_sha.values() if len(nums) > 1
    ]


def _pick_default_baseline(with_src: List[Dict[str, Any]], target: Dict[str, Any]) -> tuple:
    """기본 베이스라인 = target과 **내용이 실제로 다른** 가장 오래된 스냅샷.

    무조건 최고령을 잡으면 target과 바이트 동일한 스냅샷이 걸려 "변경 0"인 빈 화면이 된다.
    ⚠ differing이라고 신뢰할 수 있는 건 아니다 — 실측 #111은 #125와 1파일만 다르지만 그
    트리는 빌드 69일 뒤에 받은 HEAD라, 그 diff는 '#111→#125의 변화'가 아니다. 그래서 선택은
    바꾸지 않고 `checkout_lag_days`·`snapshot_groups`로 **한계를 노출**한다(수치를 좋아
    보이게 조작하지 않는다 — ISO 정직성).

    전부 동일하면 최고령을 그대로 쓰고(reason=all_identical) identical_snapshot이 사실을
    알린다 — 조용히 빈 화면을 내지 않는다.
    """
    tgt_sha = _snapshot_content_sha_cached(target)
    if not tgt_sha:
        return with_src[-1], "content_sha_unavailable"
    tgt_num = _to_int(target.get("build_number"))
    for meta in reversed(with_src):  # 오래된 것부터
        if _to_int(meta.get("build_number")) == tgt_num:
            continue
        sha = _snapshot_content_sha_cached(meta)
        if sha and sha != tgt_sha:
            return meta, "oldest_differing_snapshot"
    return with_src[-1], "all_identical"


@router.post("/api/summary/baseline-diff")
def summary_baseline_diff(req: dict) -> Dict[str, Any]:
    """베이스라인 빌드 vs 대상 빌드의 소스 스냅샷 직접 비교(영향분석 이력 무관).

    기본 쌍 = 최고령 has_source 캐시 빌드 → 최신 has_source 캐시 빌드. 결과는 target
    reports_dir에 baseline별 파일로 캐시(키 = 양쪽 스냅샷 지문 + ALGO_VERSION, force 우회).
    """
    from backend.services.baseline_diff import compute_baseline_diff, snapshot_fingerprint
    from backend.services.build_inventory import find_build_meta, list_cached_builds_meta

    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    if not job_url:
        return {"ok": True, "available": False, "reason": "job_url_required"}
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    metas = list_cached_builds_meta(job_url=job_url, cache_root=cache_root)
    with_src = [m for m in metas if m.get("has_source")]
    if not with_src:
        return {"ok": True, "available": False, "reason": "no_source_snapshot"}
    if len(with_src) < 2 and _to_int(body.get("baseline_build")) is None:
        return {"ok": True, "available": False, "reason": "single_build_cached"}

    target_req = _to_int(body.get("target_build"))
    baseline_req = _to_int(body.get("baseline_build"))
    target = find_build_meta(with_src, target_req) if target_req is not None else with_src[0]        # 최신
    baseline_auto_reason: Optional[str] = None
    if baseline_req is not None:
        baseline = find_build_meta(with_src, baseline_req)
    elif target is None:
        baseline = None
    else:
        baseline, baseline_auto_reason = _pick_default_baseline(with_src, target)
    if target is None:
        return {"ok": True, "available": False, "reason": "snapshot_missing_target"}
    if baseline is None:
        return {"ok": True, "available": False, "reason": "snapshot_missing_baseline"}
    if _to_int(target.get("build_number")) == _to_int(baseline.get("build_number")):
        return {"ok": True, "available": False, "reason": "same_build_pair"}

    base_src = Path(str(baseline.get("build_root"))) / "source"
    tgt_src = Path(str(target.get("build_root"))) / "source"
    base_fp = snapshot_fingerprint(base_src)
    tgt_fp = snapshot_fingerprint(tgt_src)
    if base_fp is None:
        return {"ok": True, "available": False, "reason": "snapshot_missing_baseline"}
    if tgt_fp is None:
        return {"ok": True, "available": False, "reason": "snapshot_missing_target"}

    # 조인 재료(N3) — 대상 빌드 기준 함수 커버리지·ASIL. 부재해도 diff 자체는 산출된다.
    tgt_reports = Path(str(target.get("reports_dir")))
    tgt_root = Path(str(target.get("build_root")))
    coverage_idx = _coverage_index(tgt_reports, job_url=job_url)
    asil_idx = _asil_index(tgt_root, tgt_reports, job_url=job_url)

    cache_path = tgt_reports / f"summary_baseline_diff_{baseline.get('build_number')}.json"
    # 소스 지문만으로는 커버리지/ASIL 갱신(SCM 재로드·추적성 재생성)을 못 본다 — 조인 지문 포함.
    src_key = {
        "baseline_fp": base_fp, "target_fp": tgt_fp,
        "coverage_fn_count": len(coverage_idx),
        "asil_fn_count": len(asil_idx["by_function"]),
    }
    cached = _read_json(cache_path)
    if cached and cached.get("src") == src_key and isinstance(cached.get("result"), dict) and not body.get("force"):
        return {**cached["result"], "cached": True}

    try:
        result = compute_baseline_diff(
            baseline_source=base_src, target_source=tgt_src,
            function_coverage=coverage_idx, asil_by_fn=asil_idx["by_function"],
        )
    except Exception as exc:
        _logger.warning("baseline-diff compute failed: %s", exc, exc_info=True)
        return {"ok": True, "available": False, "reason": f"compute_failed: {type(exc).__name__}"}

    payload = {
        "ok": True,
        "available": True,
        "reason": None,
        "independent_of_change_log": True,
        "baseline": {"build_number": baseline.get("build_number"), "revision": baseline.get("revision"),
                     "timestamp_iso": baseline.get("timestamp_iso"),
                     "source_checked_out_at": _source_checkout_iso(baseline),
                     "checkout_lag_days": _checkout_lag_days(baseline)},
        "target": {"build_number": target.get("build_number"), "revision": target.get("revision"),
                   "timestamp_iso": target.get("timestamp_iso"),
                   "source_checked_out_at": _source_checkout_iso(target),
                   "checkout_lag_days": _checkout_lag_days(target)},
        # 기본 쌍을 어떻게 골랐는지 — 사용자가 고르지 않은 쌍이 왜 나왔는지 답할 수 있어야 한다.
        "baseline_auto_reason": baseline_auto_reason,
        # 내용이 같은 스냅샷 묶음 — 이 구간끼리는 비교가 성립하지 않는다(스냅샷 재사용).
        "snapshot_groups": _snapshot_groups(with_src),
        **result,
        # 조인 출처 표기(N3) — 커버리지가 어느 소스에서 왔고 ASIL이 어떻게 확보됐는지.
        "join_sources": {
            "coverage": _load_vcast_function_entries(tgt_reports, job_url=job_url).get("source"),
            "asil_counts": asil_idx["counts"],
            "asil_propagation": asil_idx["propagation"],
        },
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_cache_atomic(cache_path, {"src": src_key, "result": payload})
    return {**payload, "cached": False}


# ---------------------------------------------------------------------------
# 빌드별 변경 매트릭스 — 베이스라인 고정 → 각 빌드의 누적 소스 변화 (change-log 비의존)
# ---------------------------------------------------------------------------

#: 매트릭스 표시 행 상한.
#: 이전 값 30은 캐시 33빌드에서 #77·78·79를 **침묵 절단**했고, 하필 자동 선택된 베이스라인
#: (#77)이 잘려 헤더는 "기준 #77"인데 표에 그 행이 없었다. 행 1개의 추가 비용은 manifest
#: dict 비교뿐이고(스냅샷 지문은 `_matrix_context`가 이미 전 빌드분을 계산한다) 실질 0에
#: 가까우므로, 캐시 조회 상한(`list_cached_builds` 계열)과 같은 100으로 맞춘다.
MATRIX_ROW_LIMIT = 100

_MATRIX_CELL_LOCKS: Dict[str, threading.Lock] = {}
_MATRIX_LOCKS_GUARD = threading.Lock()


def _matrix_cell_lock(cache_path: Path) -> threading.Lock:
    """셀 캐시 경로별 락 — 두 클라이언트가 같은 쌍을 동시에 파싱하지 않게(arch 캐시와 동일 패턴)."""
    key = str(cache_path)
    with _MATRIX_LOCKS_GUARD:
        lock = _MATRIX_CELL_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _MATRIX_CELL_LOCKS[key] = lock
        return lock


def _matrix_context(body: dict) -> Dict[str, Any]:
    """매트릭스 두 엔드포인트의 공통 준비 — 빌드 목록·지문·그룹·베이스라인 결정.

    지문 조회는 빌드당 **1회만** 한다(캐시 키 생성이 rglob 전수 stat이라 실측 13빌드 1.9초 —
    `_snapshot_groups`와 `_pick_default_baseline`이 각각 훑던 것을 여기서 합친다).
    """
    from backend.services.build_inventory import find_build_meta, list_cached_builds_meta
    from backend.services.change_matrix import canonical_build, group_by_content_sha

    job_url = str(body.get("job_url") or "").strip()
    if not job_url:
        return {"error": {"ok": True, "available": False, "reason": "job_url_required"}}
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    metas = list_cached_builds_meta(job_url=job_url, cache_root=cache_root)
    with_src = [m for m in metas if m.get("has_source")]
    if not with_src:
        return {"error": {"ok": True, "available": False, "reason": "no_source_snapshot"}}

    sha_cache: Dict[Any, Optional[str]] = {}
    manifest_cache: Dict[Any, Optional[Dict[str, str]]] = {}

    def sha_of(meta: Dict[str, Any]) -> Optional[str]:
        num = meta.get("build_number")
        if num not in sha_cache:
            sha, manifest = _snapshot_manifest_cached(meta)
            sha_cache[num] = sha
            manifest_cache[num] = manifest
        return sha_cache[num]

    baseline_req = _to_int(body.get("baseline_build"))
    baseline_auto_reason: Optional[str] = None
    if baseline_req is not None:
        baseline = find_build_meta(with_src, baseline_req)
    else:
        baseline, baseline_auto_reason = _pick_default_baseline(with_src, with_src[0])
    if baseline is None:
        return {"error": {"ok": True, "available": False, "reason": "snapshot_missing_baseline"}}

    groups = group_by_content_sha(with_src, sha_of)
    return {
        "job_url": job_url, "cache_root": cache_root, "metas": metas, "with_src": with_src,
        "baseline": baseline, "baseline_auto_reason": baseline_auto_reason,
        "sha_of": sha_of, "sha_cache": sha_cache, "manifest_cache": manifest_cache,
        "groups": groups,
        "canonical": {sha: canonical_build(nums) for sha, nums in groups.items()},
    }


def _comparison_basis(baseline: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    """두 스냅샷을 같은 기준으로 비교할 수 있는지 — 'trusted' / 'mixed' / 'both_unpinned'.

    고정 상태가 다르면 diff는 산술적으로는 맞지만 **의미가 틀린다**. 미고정 스냅샷은
    '체크아웃한 날'의 트리이므로, 미고정 베이스라인 ↔ 고정 대상의 diff는 실제로
    "과거 rev → 오늘"의 변화인데 화면엔 "그 빌드가 만든 변화"로 붙는다. 재수집을
    나눠 실행하면 반드시 겪는 상태라 숨기지 않는다.
    """
    b = bool(baseline.get("source_pinned"))
    t = bool(target.get("source_pinned"))
    if b and t:
        return {"state": "trusted"}
    if b != t:
        return {
            "state": "mixed",
            "reason": (
                "베이스라인과 이 빌드의 소스 기준이 다릅니다"
                f"(기준 #{baseline.get('build_number')}={'고정' if b else '미고정'} · "
                f"이 빌드={'고정' if t else '미고정'}) — 아래 수치는 두 빌드 사이의 변화가 아닙니다."
            ),
        }
    return {
        "state": "both_unpinned",
        "reason": "두 스냅샷 모두 빌드 시점으로 고정되지 않았습니다 — 같은 날 받아온 트리라 변화가 0으로 보입니다.",
    }


def _build_meta_row(meta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "build_number": meta.get("build_number"),
        "build_result": meta.get("result"),
        "timestamp_iso": meta.get("timestamp_iso"),
        "revision": meta.get("revision"),
        "source_checked_out_at": _source_checkout_iso(meta),
        "checkout_lag_days": _checkout_lag_days(meta),
        # 스냅샷이 빌드 시점 revision으로 고정됐는지 — False면 '변화 0'을 코드 미변경으로
        # 읽으면 안 된다(받아온 날의 HEAD 트리라 여러 빌드가 같아진다).
        "source_pinned": bool(meta.get("source_pinned")),
        "source_revision_source": meta.get("source_revision_source"),
    }


@router.post("/api/summary/change-matrix")
def summary_change_matrix(req: dict) -> Dict[str, Any]:
    """베이스라인 → 각 빌드의 누적 변화(행 = 캐시된 빌드). **함수 축을 계산하지 않는다.**

    `level="files"`는 manifest dict 비교만으로 즉시 응답하고, `level="functions"`는 캐시된 셀만
    읽어(probe) 채운 뒤 나머지를 `pending_cells`로 남긴다 — 실제 계산은 `/cell` 전용이다.
    베이스라인과 바이트 동일한 빌드는 파싱 없이 함수 0을 확정한다(증명이지 가정이 아님).
    """
    from backend.services.change_matrix import cell_id

    body = req or {}
    ctx = _matrix_context(body)
    if "error" in ctx:
        return ctx["error"]
    level = "functions" if str(body.get("level") or "files") == "functions" else "files"
    limit = max(1, min(_to_int(body.get("limit")) or MATRIX_ROW_LIMIT, MATRIX_ROW_LIMIT))
    baseline = ctx["baseline"]
    base_num = baseline.get("build_number")
    base_sha = ctx["sha_of"](baseline)
    base_manifest = ctx["manifest_cache"].get(base_num)

    # 표시 대상 선정 — 최신순 limit개. **베이스라인은 무조건 포함**한다: 헤더가 "기준 #77"이라
    # 쓰는데 그 행이 상한에 잘려 사라지면(실측 33빌드/상한 30 → #77·78·79 누락) 사용자는
    # 기준을 표에서 찾을 수 없다. 잘린 사실도 응답에 명시한다(침묵 절단 금지).
    ordered = ctx["with_src"]
    selected = ordered[:limit]
    if not any(m.get("build_number") == base_num for m in selected):
        selected = selected[: max(0, limit - 1)] + [baseline]
    omitted = [
        m.get("build_number") for m in ordered
        if m.get("build_number") not in {s.get("build_number") for s in selected}
    ]

    rows: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    pending_seen: set = set()
    cached_cells = 0
    for meta in selected:
        num = meta.get("build_number")
        row = _build_meta_row(meta)
        sha = ctx["sha_of"](meta)
        members = sorted(ctx["groups"].get(sha or "", []), reverse=True)
        row.update({
            "row_key": f"b{num}",
            "content_sha": sha,
            "snapshot_group": {"count": len(members), "members": members,
                               "canonical_build": ctx["canonical"].get(sha or "")},
            "is_baseline": num == base_num,
            "identical_to_baseline": bool(sha and base_sha and sha == base_sha),
            "files": None, "functions": None, "asil": None,
            # 비교 기준 신뢰도 — 두 스냅샷의 고정 상태가 다르면 숫자가 **방향까지 뒤집힌다**.
            # 예: 베이스라인이 미고정(오늘 HEAD)이고 대상이 고정(6월 rev)이면, 실제로는
            # "6월→오늘의 변화"인데 화면엔 "이 빌드가 베이스라인 대비 바꾼 것"으로 붙는다.
            # 부분 재수집 중에는 반드시 생기는 상태라 행 단위로 표시해야 한다.
            "comparison_basis": _comparison_basis(baseline, meta),
        })
        if row["is_baseline"]:
            row["function_state"] = {"state": "baseline", "reason": "베이스라인 자신"}
            rows.append(row)
            continue
        manifest = ctx["manifest_cache"].get(num)
        if base_manifest is not None and manifest is not None:
            from backend.services.baseline_diff import compute_file_axis_from_manifests

            axis = compute_file_axis_from_manifests(baseline=base_manifest, target=manifest)
            row["files"] = {
                "added": len(axis["added"]), "deleted": len(axis["deleted"]),
                "modified": len(axis["modified"]), "changed": axis["changed"],
                "unchanged": axis["unchanged"], "total_baseline": axis["total_baseline"],
                "total_target": axis["total_target"],
                "changed_paths": (
                    [{"path": p, "change_kind": "added"} for p in axis["added"]]
                    + [{"path": p, "change_kind": "deleted"} for p in axis["deleted"]]
                    + [{"path": m["path"], "change_kind": "modified"} for m in axis["modified"]]
                ),
            }
        if row["identical_to_baseline"]:
            # 두 트리가 바이트 동일 → 파서 산출도 동일 → 함수 차집합은 공집합. 계산 불필요.
            row["functions"] = {"new": 0, "deleted": 0, "signature": 0, "body": 0, "changed": 0}
            row["asil"] = {"touched": 0, "by_grade": {}, "max": None}
            row["function_state"] = {
                "state": "identical",
                "reason": "베이스라인과 소스 트리가 바이트 동일 — 함수 차이는 계산 없이 0으로 확정",
            }
            rows.append(row)
            continue
        cid = cell_id(base_sha or "", sha or "")
        row["cell_id"] = cid
        if level == "functions":
            hit = _read_matrix_cell(ctx, base_sha, sha)
            if hit is not None:
                from backend.services.change_matrix import asil_column, function_counts

                enriched = _annotate_cell(ctx, hit)
                row["functions"] = function_counts(enriched)
                row["asil"] = asil_column(enriched)
                row["function_state"] = {"state": "computed"}
                cached_cells += 1
                rows.append(row)
                continue
        row["function_state"] = {
            "state": "not_computed",
            "reason": "level_files" if level == "files" else "cell_not_cached",
        }
        if cid not in pending_seen:
            pending_seen.add(cid)
            pending.append({"cell_id": cid, "target_build": ctx["canonical"].get(sha or "") or num})
        rows.append(row)

    join = _matrix_join_scope(ctx)
    return {
        "ok": True, "available": True, "reason": None, "level": level,
        "baseline": {**_build_meta_row(baseline), "content_sha": base_sha},
        "baseline_auto_reason": ctx["baseline_auto_reason"],
        "join_scope": join,
        "snapshot_groups": [
            {"content_sha": sha, "builds": sorted(nums, reverse=True), "count": len(nums)}
            for sha, nums in ctx["groups"].items() if len(nums) > 1
        ],
        "rows": rows,
        # 절단 고지 — 잘렸다는 사실을 숨기면 사용자는 "내 빌드가 왜 없나"를 알 수 없다.
        "row_limit": {
            "limit": limit, "shown": len(rows), "available": len(ordered),
            "omitted_builds": sorted([b for b in omitted if b is not None], reverse=True),
            "baseline_forced_in": bool(omitted) and base_num in {r.get("build_number") for r in rows},
        },
        "pending_cells": pending,
        # 스냅샷 신뢰도 — unpinned가 많으면 '동일 트리'는 코드 미변경이 아니라 백필이 HEAD를
        # 받아온 결과다. 이걸 숨기면 ASIL 함수 변경이 침묵으로 과소보고된다.
        "snapshot_trust": {
            "pinned": sum(1 for r in rows if r.get("source_pinned")),
            "unpinned": sum(1 for r in rows if not r.get("source_pinned")),
            "unpinned_builds": [r["build_number"] for r in rows if not r.get("source_pinned")],
            "note": (
                "고정되지 않은 스냅샷은 체크아웃한 날의 트리입니다 — 여러 빌드가 같은 트리가 되어 "
                "변화가 0으로 보입니다. '과거 빌드 가져오기'의 스냅샷 고정으로 재수집하세요."
            ),
        },
        "stats": {
            "rows": len(rows), "pairs_total": max(0, len(rows) - 1),
            "pairs_distinct": len({r.get("cell_id") for r in rows if r.get("cell_id")}),
            "function_cells_cached": cached_cells,
        },
        "note": (
            "영향분석 실행 이력과 무관한 소스 스냅샷 비교입니다 — 실행 이력 누적은 상단 문제점 "
            "배너에 반영됩니다."
        ),
    }


def _matrix_join_scope(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """ASIL·커버리지 인덱스는 **최신 빌드 1벌**로 고정한다.

    행마다 다른 인덱스를 쓰면 ASIL 열이 행 간 비교 불가가 된다(같은 함수가 빌드마다 다른 등급으로
    보임). 기준 빌드를 응답에 명시해 사용자가 무엇과 조인됐는지 알 수 있게 한다.
    """
    latest = ctx["with_src"][0]
    reports = Path(str(latest.get("reports_dir")))
    root = Path(str(latest.get("build_root")))
    cov = _coverage_index(reports, job_url=ctx["job_url"])
    asil = _asil_index(root, reports, job_url=ctx["job_url"])
    ctx["_cov"] = cov
    ctx["_asil"] = asil["by_function"]
    return {
        "build_number": latest.get("build_number"),
        "coverage_functions": len(cov),
        "asil_functions": len(asil["by_function"]),
        "note": "ASIL·커버리지는 최신 빌드 기준 1벌 — 행마다 다른 인덱스를 쓰면 열이 행 간 비교 불가가 된다",
    }


def _matrix_cell_path(ctx: Dict[str, Any], target_sha: Optional[str], base_sha: Optional[str]) -> Optional[Path]:
    from backend.services.build_inventory import find_build_meta
    from backend.services.change_matrix import cell_cache_name

    canon = ctx["canonical"].get(target_sha or "")
    meta = find_build_meta(ctx["with_src"], canon)
    if meta is None:
        return None
    return Path(str(meta.get("reports_dir"))) / cell_cache_name(base_sha or "")


def _read_matrix_cell(ctx: Dict[str, Any], base_sha: Optional[str], target_sha: Optional[str]) -> Optional[Dict[str, Any]]:
    """셀 캐시 조회 — 키는 (algo, baseline_sha, target_sha)뿐(조인 무관)."""
    from backend.services.change_matrix import CHANGE_MATRIX_ALGO_VERSION, cell_id

    path = _matrix_cell_path(ctx, target_sha, base_sha)
    if path is None:
        return None
    data = _read_json(path)
    if not isinstance(data, dict):
        return None
    entry = (data.get("cells") or {}).get(cell_id(base_sha or "", target_sha or ""))
    if not isinstance(entry, dict):
        return None
    src = entry.get("src") or {}
    if src.get("algo") != CHANGE_MATRIX_ALGO_VERSION or src.get("baseline_sha") != base_sha \
            or src.get("target_sha") != target_sha:
        return None
    result = entry.get("result")
    return result if isinstance(result, dict) else None


def _annotate_cell(ctx: Dict[str, Any], cell: Dict[str, Any]) -> Dict[str, Any]:
    from copy import deepcopy

    from backend.services.change_matrix import annotate_asil_coverage

    if "_asil" not in ctx:
        _matrix_join_scope(ctx)
    return annotate_asil_coverage(deepcopy(cell), asil_by_fn=ctx.get("_asil"),
                                  function_coverage=ctx.get("_cov"))


@router.post("/api/summary/change-matrix/cell")
def summary_change_matrix_cell(req: dict) -> Dict[str, Any]:
    """셀 1개(베이스라인 sha → 대상 sha)의 함수 축 계산. probe=true면 캐시만 조회(계산 0)."""
    from backend.services.build_inventory import find_build_meta
    from backend.services.change_matrix import (
        CHANGE_MATRIX_ALGO_VERSION,
        asil_column,
        cell_id,
        function_counts,
        parse_functions_memo,
    )

    body = req or {}
    ctx = _matrix_context(body)
    if "error" in ctx:
        return ctx["error"]
    target_req = _to_int(body.get("target_build"))
    target = find_build_meta(ctx["with_src"], target_req)
    if target is None:
        return {"ok": True, "available": False, "reason": "build_not_cached"}
    baseline = ctx["baseline"]
    base_sha = ctx["sha_of"](baseline)
    tgt_sha = ctx["sha_of"](target)
    cid = cell_id(base_sha or "", tgt_sha or "")
    members = sorted(ctx["groups"].get(tgt_sha or "", []), reverse=True)

    def _shape(result: Dict[str, Any], *, cached: bool) -> Dict[str, Any]:
        enriched = _annotate_cell(ctx, result)
        out = {
            "ok": True, "available": True, "cell_id": cid,
            "baseline": {**_build_meta_row(baseline), "content_sha": base_sha},
            "target": {**_build_meta_row(target), "content_sha": tgt_sha},
            "shared_with_builds": members,
            "canonical_target_build": ctx["canonical"].get(tgt_sha or ""),
            "functions": function_counts(enriched), "asil": asil_column(enriched),
            "files": enriched.get("files"),
            "function_state": {"state": "computed"},
            "cached": cached, "computed_ms": result.get("computed_ms"),
            "join_scope": _matrix_join_scope(ctx),
        }
        if body.get("detail"):
            out["detail"] = {
                "changed_detail": (enriched.get("files") or {}).get("changed_detail"),
                "gap_summary": (enriched.get("functions") or {}).get("gap_summary"),
                "asil_touched": enriched.get("asil_touched"),
            }
        return out

    if base_sha and tgt_sha and base_sha == tgt_sha:
        return {
            "ok": True, "available": True, "cell_id": cid,
            "baseline": {**_build_meta_row(baseline), "content_sha": base_sha},
            "target": {**_build_meta_row(target), "content_sha": tgt_sha},
            "shared_with_builds": members,
            "functions": {"new": 0, "deleted": 0, "signature": 0, "body": 0, "changed": 0},
            "asil": {"touched": 0, "by_grade": {}, "max": None},
            "function_state": {"state": "identical",
                               "reason": "베이스라인과 소스 트리가 바이트 동일 — 계산 없이 0으로 확정"},
            "cached": True, "computed_ms": 0,
        }

    if not body.get("force"):
        hit = _read_matrix_cell(ctx, base_sha, tgt_sha)
        if hit is not None:
            return _shape(hit, cached=True)
    if body.get("probe"):
        return {"ok": True, "available": True, "cached": False, "cell_id": cid,
                "function_state": {"state": "pending"}}

    cache_path = _matrix_cell_path(ctx, tgt_sha, base_sha)
    if cache_path is None:
        return {"ok": True, "available": False, "reason": "build_not_cached"}
    with _matrix_cell_lock(cache_path):
        if not body.get("force"):
            hit = _read_matrix_cell(ctx, base_sha, tgt_sha)  # 락 안 재확인(중복 파싱 방지)
            if hit is not None:
                return _shape(hit, cached=True)
        from backend.services.baseline_diff import compute_baseline_diff

        base_src = Path(str(baseline.get("build_root"))) / "source"
        tgt_src = Path(str(target.get("build_root"))) / "source"
        try:
            result = compute_baseline_diff(
                baseline_source=base_src, target_source=tgt_src,
                parse_fn=lambda p: parse_functions_memo(
                    p, content_sha=base_sha if p == base_src else tgt_sha),
            )
        except Exception as exc:
            _logger.warning("change-matrix cell compute failed: %s", exc, exc_info=True)
            return {"ok": True, "available": False, "reason": f"compute_failed: {type(exc).__name__}"}
        data = _read_json(cache_path)
        cells = (data.get("cells") if isinstance(data, dict) else None) or {}
        cells[cid] = {
            "src": {"algo": CHANGE_MATRIX_ALGO_VERSION, "baseline_sha": base_sha, "target_sha": tgt_sha},
            "result": result,
        }
        _write_cache_atomic(cache_path, {"cells": cells})
    return _shape(result, cached=False)


# ---------------------------------------------------------------------------
# AI 인사이트 (Phase C) — 결정론 코어 + Gemini enrichment, on-demand + 디스크 캐시
# ---------------------------------------------------------------------------

AI_INSIGHT_CACHE_NAME = "summary_ai_insight.json"


def _num_kv(v: Any) -> Optional[int]:
    """RCR summary kv의 '64,805' 콤마 문자열 정수화(jenkins_prqa_trend._num과 동일 함정)."""
    if v is None:
        return None
    try:
        return int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _headline_from_summary(reports_dir: Path) -> Dict[str, Any]:
    """analysis_summary.json 직독 — prqa-trend와 동일 소스(빌드당 RCR 재파싱 금지)."""
    data = _read_json(reports_dir / "analysis_summary.json") or {}
    prqa = data.get("prqa") if isinstance(data.get("prqa"), dict) else {}
    rcr = prqa.get("rcr") if isinstance(prqa.get("rcr"), dict) else {}
    rcr_summary = rcr.get("summary") if isinstance(rcr.get("summary"), dict) else {}
    coverage = data.get("coverage") if isinstance(data.get("coverage"), dict) else {}
    return {
        "violations": _num_kv(rcr_summary.get("Rule Violation Count")),
        "diagnostics": _num_kv(rcr_summary.get("Diagnostic Count")),
        "compliance": _num_kv(rcr_summary.get("Project Compliance Index")),
        "coverage_line": coverage.get("line_rate"),
        "coverage_branch": coverage.get("branch_rate"),
    }


def _complexity_offenders(build_root: Path, reports_dir: Path) -> List[Dict[str, Any]]:
    """HIS 메트릭(HMR xlsx) 상위 복잡도 함수 — 부재/파싱 실패는 빈 리스트(fail-soft)."""
    cands: List[Path] = []
    try:
        cands += [p for p in reports_dir.rglob("*_HMR_*.xlsx") if p.is_file()]
        if build_root != reports_dir and build_root.is_dir():
            cands += [p for p in build_root.glob("*_HMR_*.xlsx") if p.is_file()]
    except OSError:
        return []
    if not cands:
        return []
    try:
        from backend.services.jenkins_adapter import parse_prqa_his_metrics_xlsx

        latest = max(cands, key=lambda c: c.stat().st_mtime_ns)
        res = parse_prqa_his_metrics_xlsx(latest, top_n=10)
        rows = res.get("top_vg") if isinstance(res, dict) else None
        if not isinstance(rows, list):
            return []
        out = []
        for r in rows[:10]:
            if isinstance(r, dict) and r.get("function"):
                out.append({"function": r.get("function"), "vg": r.get("vg"), "file": r.get("file")})
        return out
    except Exception as exc:  # 복잡도는 부가 정보 — 실패가 인사이트 전체를 죽이지 않는다.
        _logger.debug("ai-insight HMR parse skipped: %s", exc)
        return []


def _ccn_map(reports_dir: Path, *, job_url: str = "") -> Dict[str, int]:
    """analysis_summary.json → {subprogram: ccn}.

    vectorcast_detail.aggregate_coverage.entries(구 규약)가 비면 vectorcast.ut_metrics/
    it_metrics.entries로 폴백 — 실측상 전 캐시 빌드에서 detail은 빈 {}이고 실데이터는
    형제 키에 있다(K1 교정 — 이전엔 항상 {} 반환 → 전 함수 loc_proxy). 중복 함수는 max.
    N1: 빌드 산출물에 둘 다 없으면 SCM 로드 이력의 entries로 3차 폴백한다 — 이 경로가
    없으면 KJPDS02_PV류는 ccn 조인 0%라 아키텍처 핫스팟이 전원 loc_proxy로 떨어진다.
    """
    data = _read_json(reports_dir / "analysis_summary.json") or {}
    entry_lists: List[Any] = []
    detail = data.get("vectorcast_detail") if isinstance(data.get("vectorcast_detail"), dict) else {}
    agg = detail.get("aggregate_coverage") if isinstance(detail.get("aggregate_coverage"), dict) else {}
    if agg.get("entries"):
        entry_lists.append(agg.get("entries"))
    else:
        vc = data.get("vectorcast") if isinstance(data.get("vectorcast"), dict) else {}
        for key in ("ut_metrics", "it_metrics"):
            sec = vc.get(key) if isinstance(vc.get(key), dict) else {}
            if sec.get("entries"):
                entry_lists.append(sec.get("entries"))
    if not entry_lists:
        scm = _load_scm_function_entries(job_url)
        if scm:
            for key in ("ut_entries", "it_entries"):
                if scm.get(key):
                    entry_lists.append(scm.get(key))
    out: Dict[str, int] = {}
    for entries in entry_lists:
        for e in entries or []:
            if not isinstance(e, dict):
                continue
            name = str(e.get("subprogram") or "").strip()
            try:
                ccn = int(e.get("ccn"))
            except (TypeError, ValueError):
                continue
            if name and ccn > 0:
                out[name] = max(out.get(name, 0), ccn)
    return out


ARCH_METRICS_CACHE_NAME = "summary_arch_metrics_cache.json"

# 빌드(캐시 파일)별 계산 락 — 동시 요청이 같은 스냅샷을 중복 파싱하지 않도록. 전역 단일 락은
# 서로 다른 프로젝트끼리도 직렬화시키므로 키별로 나눈다. 락 객체 자체의 생성은 _ARCH_LOCKS_GUARD로 보호.
_ARCH_BUILD_LOCKS: Dict[str, threading.Lock] = {}
_ARCH_LOCKS_GUARD = threading.Lock()
_ARCH_LOCKS_MAX = 16


def _arch_build_lock(cache_path: Path) -> threading.Lock:
    key = str(cache_path)
    with _ARCH_LOCKS_GUARD:
        lock = _ARCH_BUILD_LOCKS.get(key)
        if lock is None:
            if len(_ARCH_BUILD_LOCKS) >= _ARCH_LOCKS_MAX:
                # 무한 증식 방지. 사용 중인 락을 버려도 새 락으로 다시 직렬화될 뿐이라 안전하다
                # (락은 중복 계산 회피용 최적화이지 정확성 장치가 아님 — 캐시 쓰기는 원자적).
                _ARCH_BUILD_LOCKS.clear()
            lock = threading.Lock()
            _ARCH_BUILD_LOCKS[key] = lock
        return lock


def _arch_src_fingerprint(
    build_root: Path, *, ccn_count: int = 0, asil_count: int = 0, cov_count: int = 0,
) -> Optional[Dict[str, Any]]:
    """소스 스냅샷 지문(stat 스캔) — 캐시 히트 판정. 스냅샷 부재는 None.

    ccn/asil/coverage 조인 규모도 지문에 넣는다(N1·N5) — 소스가 그대로여도 조인 소스가
    붙거나 바뀌면 complexity_source가 loc_proxy↔vcast_ccn으로 뒤집히고(핫스팟 순위 변화),
    v4의 간섭·사분면 블록이 available:false↔true로 뒤집힌다.
    """
    source = build_root / "source"
    if not (source / ".source_complete").exists():
        return None
    file_count = 0
    total_bytes = 0
    try:
        for p in source.rglob("*"):
            if p.is_file():
                file_count += 1
                total_bytes += p.stat().st_size
    except OSError:
        return None
    from workflow.summary_arch_metrics import ARCH_METRICS_VERSION

    return {"file_count": file_count, "total_bytes": total_bytes,
            "version": ARCH_METRICS_VERSION, "ccn_count": ccn_count,
            "asil_count": asil_count, "cov_count": cov_count}


def _arch_metrics_cached(build_root: Path, reports_dir: Path, *, job_url: str = "") -> Optional[Dict[str, Any]]:
    """아키텍처 메트릭 — 스냅샷+조인 지문 키 디스크 캐시(파싱 1회화). 스냅샷 부재는 None.

    ⚠ 순환 주의: ASIL 인덱스는 요구 역전파(추적 링크)만 쓴다 — `_asil_index`를 부르면
    그 안에서 다시 이 함수를 호출해 무한 재귀가 된다(주석 ASIL은 arch 결과에서 온다).
    """
    ccn = _ccn_map(reports_dir, job_url=job_url)
    propagated = _propagated_asil(build_root, reports_dir)
    asil_index = {
        k: v.get("asil") for k, v in (propagated.get("by_function") or {}).items() if v.get("asil")
    }
    coverage_index = _coverage_index(reports_dir, job_url=job_url)
    src = _arch_src_fingerprint(build_root, ccn_count=len(ccn),
                                asil_count=len(asil_index), cov_count=len(coverage_index))
    if src is None:
        return None
    cache_path = reports_dir / ARCH_METRICS_CACHE_NAME
    cached = _read_json(cache_path)
    if cached and cached.get("src") == src and isinstance(cached.get("result"), dict):
        return {**cached["result"], "cache_hit": True}

    # 빌드별 빌드 락 — 요약탭은 아키텍처 메트릭 패널과 다이어그램 패널이 이 엔드포인트를 **동시에**
    # 부른다. 락이 없으면 캐시 미스가 겹칠 때 두 요청이 같은 스냅샷을 각각 파싱한다(실측 1.5s×2).
    # 락 안에서 캐시를 한 번 더 확인해, 먼저 끝낸 쪽의 결과를 두 번째가 그대로 쓰게 한다.
    with _arch_build_lock(cache_path):
        cached = _read_json(cache_path)
        if cached and cached.get("src") == src and isinstance(cached.get("result"), dict):
            return {**cached["result"], "cache_hit": True}
        from workflow.summary_arch_metrics import compute_architecture_metrics

        result = compute_architecture_metrics(
            build_root / "source", ccn_by_function=ccn,
            asil_by_function=asil_index, coverage_by_function=coverage_index,
        )
        if result.get("available"):
            _write_cache_atomic(cache_path, {"src": src, "result": result})
    return {**result, "cache_hit": False}


ARCH_IMPROVEMENT_CACHE_NAME = "summary_arch_improvement_cache.json"
_ARCH_IMPROVE_LOCK = threading.Lock()


@router.post("/api/summary/arch-improvement")
def summary_arch_improvement(req: dict) -> Dict[str, Any]:
    """아키텍처 개선(To-Be) 제안 — 결정론 후보 + Gemini 목표 구조(Q3).

    결정론 후보는 LLM 없이 항상 나온다(순환 끊기·계층 정돈·집중 파일 분할 + 테스트 용이성 3종).
    후보가 0이면 AI를 부르지 않는다 — 근거 없는 목표 구조는 그럴듯한 허구다.
    probe/force/RMW 캐시 규약은 rule-fix-example과 동일.
    """
    import hashlib as _hashlib

    from workflow.arch_improvement import (
        ARCH_IMPROVEMENT_NOTE,
        ARCH_IMPROVEMENT_PROMPT_VERSION,
        build_candidates,
        generate_target_design,
        summarize,
    )
    from workflow.arch_playbook import attach_playbooks, playbook_coverage

    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    if not job_url:
        return {"ok": True, "available": False, "reason": "job_url_required"}
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    builds = list_cached_builds(job_url=job_url, cache_root=cache_root)
    target = next(
        (b for b in builds if (Path(str(b.get("build_root") or "")) / "source" / ".source_complete").exists()),
        None,
    )
    if target is None:
        return {"ok": True, "available": False, "reason": "no_source_snapshot"}
    build_root = Path(str(target.get("build_root")))
    reports_dir = Path(str(target.get("reports_dir")))
    arch = _arch_metrics_cached(build_root, reports_dir, job_url=job_url)
    if not (arch and arch.get("available")):
        return {"ok": True, "available": False,
                "reason": (arch or {}).get("reason") or "no_arch_metrics"}

    # 상한 없이 한 번 세어 절단량을 알아낸다 — 표시분만 보고 '이게 전부'로 읽히면 안 된다.
    all_candidates = build_candidates(arch, top_n=10_000)
    candidates = build_candidates(arch)
    summary = summarize(candidates, omitted=max(0, len(all_candidates) - len(candidates)))
    # 상세 플레이북(결정론, LLM 무관) — "무엇을"만 있던 후보에 "어디를 어떻게"를 붙인다.
    # 재료(arch.playbook_inputs)가 없는 구 캐시에서는 detail 이 안 붙고 표는 그대로 산다.
    candidates = attach_playbooks(candidates, arch)
    playbook = playbook_coverage(candidates)
    base_payload: Dict[str, Any] = {
        "ok": True, "available": True, "reason": None,
        "build_number": target.get("build_number"),
        "candidates": candidates,
        "summary": summary,
        "playbook": playbook,
        "as_is": {
            "nodes": (arch.get("module_graph") or {}).get("nodes"),
            "edges": (arch.get("module_graph") or {}).get("edges"),
        },
        "note": ARCH_IMPROVEMENT_NOTE,
        "prompt_version": ARCH_IMPROVEMENT_PROMPT_VERSION,
    }

    # 캐시 키 = 모델 + 프롬프트 버전 + **후보 지문**. 지문에 basis(실측 수치)까지 넣는다 —
    # (kind, target)만 쓰면 같은 함수의 커버리지가 41%→85%로 바뀌어도 키가 같아, AI가
    # "구문 41%"를 인용한 낡은 목표 구조를 계속 서빙한다(model None은 빈 문자열 — join TypeError 방지).
    model = _expected_insight_model() or ""
    fingerprint = json.dumps(
        [[c.get("kind"), c.get("target"), c.get("basis")] for c in candidates], ensure_ascii=False,
    )
    key = _hashlib.sha256(
        "|".join([model, str(ARCH_IMPROVEMENT_PROMPT_VERSION), fingerprint]).encode()
    ).hexdigest()
    cache_path = reports_dir / ARCH_IMPROVEMENT_CACHE_NAME
    with _ARCH_IMPROVE_LOCK:
        hit = _fix_cache_load(cache_path).get(key)
    if hit and not bool(body.get("force")):
        # 캐시가 값을 갖는 건 **AI 섹션뿐**이다. 결정론 코어(후보·상세 플레이북)는 방금 다시
        # 계산했으므로 그쪽으로 덮는다 — 안 그러면 PLAYBOOK_VERSION 이 올라도 fingerprint 는
        # 그대로라 낡은 상세가 계속 서빙된다(캐시 키에 든 건 kind/target/basis 뿐).
        return {**hit, **base_payload, "cached": True}
    if bool(body.get("probe")):
        # 결정론 코어는 캐시 없이도 즉시 반환 — AI 섹션만 미생성 상태로 알린다.
        return {**base_payload, "cached": False, "ai_enriched": False,
                "enrich_reason": "not_generated", "target_design": None}

    gen = generate_target_design(arch=arch, candidates=candidates)
    payload = {
        **base_payload,
        "target_design": gen["target_design"],
        "ai_enriched": gen["ai_enriched"],
        "enrich_reason": gen["enrich_reason"],
        "model": gen["model"],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _ARCH_IMPROVE_LOCK:
        entries = _fix_cache_load(cache_path)
        entries[key] = payload
        _fix_cache_store(cache_path, entries)
    return {**payload, "cached": False}


@router.post("/api/summary/architecture-metrics")
def summary_architecture_metrics(req: dict) -> Dict[str, Any]:
    """소스 아키텍처 결정론 메트릭(LLM 0회) — 최신 캐시 빌드 스냅샷 기준."""
    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    if not job_url:
        return {"ok": True, "available": False, "reason": "job_url_required"}
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    builds = list_cached_builds(job_url=job_url, cache_root=cache_root)
    target = next((b for b in builds if (Path(str(b.get("build_root") or "")) / "source" / ".source_complete").exists()), None)
    if target is None:
        return {"ok": True, "available": False, "reason": "no_source_snapshot"}
    result = _arch_metrics_cached(
        Path(str(target.get("build_root"))), Path(str(target.get("reports_dir"))), job_url=job_url
    )
    if result is None or not result.get("available"):
        return {"ok": True, "available": False,
                "reason": (result or {}).get("reason") or "no_source_snapshot",
                "build_number": target.get("build_number")}
    return {"ok": True, "reason": None, "build_number": target.get("build_number"), **result}


def _vcast_failures(rag_path: Optional[Path]) -> List[Dict[str, Any]]:
    """vectorcast_rag의 failures[] — 경로는 _find_vcast_rag가 해석(하위폴더 실물 정규, L1)."""
    if rag_path is None:
        return []
    data = _read_json(rag_path) or {}
    failures = data.get("failures")
    return [f for f in failures if isinstance(f, dict)][:50] if isinstance(failures, list) else []


def _expected_insight_model() -> Optional[str]:
    """현재 배선이 인사이트 생성에 사용할 모델명(LLM 호출 0회) — 캐시 model 비교용.

    cfg 해석(_load_impact_oai_config)과 override 반영(resolve_effective_model)을 실생성
    경로와 동일하게 따라가야, 모델 교체 직후 구 모델 산출물이 cached:true로 위장하지 않는다.
    """
    try:
        from workflow.impact_ai_guide import _load_impact_oai_config
        from workflow.summary_ai_insight import resolve_effective_model

        return resolve_effective_model(_load_impact_oai_config())
    except Exception as exc:
        _logger.debug("expected insight model resolve failed: %s", exc)
        return None


def _current_rcr_src(build_root: Path, reports_dir: Path) -> Optional[Dict[str, Any]]:
    """현재 RCR 원본 지문(stat만 — 파싱 없음). AI 인사이트 캐시 히트 판정용(W1).

    같은 빌드 디렉토리의 RCR이 in-place 교체(force 재-sync)돼도 캐시가 stale로
    남지 않게, 저장 시점 지문과 현재 지문을 비교한다(신규 빌드 무효화만으로는 부족).
    """
    rcr = find_latest_rcr_html(build_root, reports_dir)
    if rcr is None:
        return None
    try:
        st = rcr.stat()
    except OSError:
        return None
    return {"path": str(rcr), "mtime_ns": st.st_mtime_ns, "size": st.st_size}


def _make_source_reader(source_root: str):
    """file_resolver(cloudium worker 인지) 기반 read-only 소스 리더 — 발췌 주입용."""
    from backend.services.file_resolver import get_resolver

    resolver = get_resolver()
    root = str(source_root or "").replace("\\", "/").rstrip("/")

    def _read(rel: str) -> str:
        if not root:
            raise FileNotFoundError(rel)
        cleaned = str(rel or "").replace("\\", "/").lstrip("/")
        # 선행 상대 프리픽스 제거 + 중간 '..' 세그먼트 전면 거부(W3 defense-in-depth) —
        # candidate는 서버 산출(RCR/change-log)이라 정상 경로엔 중간 '..'가 없다.
        parts = [seg for seg in cleaned.split("/") if seg not in ("", ".")]
        while parts and parts[0] == "..":
            parts.pop(0)
        if not parts or any(seg == ".." for seg in parts):
            raise FileNotFoundError(rel)
        return resolver.read_text(f"{root}/{'/'.join(parts)}", encoding="utf-8")

    return _read


def _write_cache_atomic(path: Path, payload: Dict[str, Any]) -> None:
    try:
        # writer별 유니크 tmp(통합 deep-review W1) — 동일 캐시 동시 writer가 고정 tmp를
        # 공유하면 바이트 인터리브 garbage가 atomic rename으로 승격된다(자가치유되나
        # LLM 재호출 낭비). uuid suffix로 각 writer가 완전한 파일만 rename하게 한다.
        tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        _logger.debug("ai-insight cache write skipped (%s): %s", path, exc)


@router.post("/api/summary/ai-insight")
def summary_ai_insight_endpoint(req: dict) -> Dict[str, Any]:
    """프로젝트 요약탭 AI 인사이트 — on-demand 생성 + 최신 빌드 디렉토리 디스크 캐시.

    probe:true → 캐시만 조회(LLM 0회, 미스면 cached:false 즉시). force:true → 재생성.
    캐시는 최신 캐시 빌드의 reports_dir에 살아서 새 빌드가 오면 자연 무효화되고,
    prompt_version 불일치(프롬프트 개정) 시에도 미스 처리한다. Gemini 비용 통제:
    생성당 LLM 호출 최대 3회(섹션당 1회) + 코드 발췌 총 16KB 캡(workflow 모듈 강제).
    """
    from workflow.summary_ai_insight import (
        PROMPT_VERSION,
        SECTIONS,
        SummaryInsightInput,
        collect_code_excerpts,
        curate_trace_summary,
        generate_summary_insight,
        top_rules_with_files,
    )

    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    if not job_url:
        return {"ok": True, "available": False, "reason": "job_url_required"}
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    builds = list_cached_builds(job_url=job_url, cache_root=cache_root)
    latest = next((b for b in builds if _to_int(b.get("build_number")) is not None), None)
    if latest is None:
        return {"ok": True, "available": False, "reason": "no_cached_build"}
    latest_build = _to_int(latest.get("build_number"))
    reports_dir = Path(str(latest.get("reports_dir") or ""))
    build_root = Path(str(latest.get("build_root") or "")) if latest.get("build_root") else reports_dir
    cache_path = reports_dir / AI_INSIGHT_CACHE_NAME

    probe = bool(body.get("probe"))
    force = bool(body.get("force"))
    cached = _read_json(cache_path)
    # 히트 조건: 프롬프트 버전 + RCR 원본 지문(stat 1회) + 모델 일치 — RCR 재-sync 교체
    # (deep-review W1)나 표준 모델 교체(Phase 0) 후 stale 산출물을 cached:true로 서빙하지 않는다.
    cache_valid = (
        bool(cached)
        and cached.get("prompt_version") == PROMPT_VERSION
        and cached.get("rcr_src") == _current_rcr_src(build_root, reports_dir)
        and cached.get("model") == _expected_insight_model()
    )
    if probe:
        if cache_valid:
            return {**cached, "cached": True, "available": True}
        return {"ok": True, "available": True, "cached": False, "latest_build": latest_build}
    if cache_valid and not force:
        return {**cached, "cached": True, "available": True}

    # ── 입력 수집 (RCR 상세는 prqa-delta와 같은 디스크 캐시 재사용 — 추가 파싱 1회화) ──
    cur = load_rcr_details_cached(build_root, reports_dir)
    base_meta = _previous_cached_build(builds, latest_build) if latest_build is not None else None
    base = (
        load_rcr_details_cached(
            Path(str(base_meta.get("build_root") or "")) if base_meta.get("build_root") else None,
            Path(str(base_meta.get("reports_dir") or "")) if base_meta.get("reports_dir") else None,
        )
        if base_meta
        else None
    )
    delta = compute_prqa_pair_delta(cur["details"], base["details"]) if (cur and base) else None

    scm_id = str(body.get("scm_id") or "").strip()
    changed = _changed_files_for_build(scm_id, latest_build) if latest_build is not None else {"available": False}
    signals: List[Dict[str, Any]] = []
    if delta and changed.get("available"):
        signals = apply_changed_file_signals(delta["files"], changed.get("files") or [])
    if delta:
        delta = {**delta, "signals": signals}

    # 코드 발췌 후보: 변경∧위반증가(signal) → 변경 파일 → delta 증가 파일 순(입력 근거 우선).
    candidates: List[str] = [str(s.get("file") or "") for s in signals]
    candidates += [str(f) for f in (changed.get("files") or [])]
    if delta:
        candidates += [str(f.get("path") or f.get("file") or "") for f in delta.get("files") or [] if (f.get("delta") or 0) > 0]
    source_root = ""
    if scm_id:
        try:
            from backend.services.scm_registry import get_registry_entry

            entry = get_registry_entry(scm_id)
            source_root = str(getattr(entry, "source_root", "") or "") if entry else ""
        except Exception as exc:
            _logger.debug("ai-insight scm entry lookup failed (%s): %s", scm_id, exc)
    excerpts: List[Dict[str, Any]] = []
    if source_root and candidates:
        excerpts = collect_code_excerpts(_make_source_reader(source_root), candidates[:12])

    sections_req = body.get("sections")
    sections = tuple(s for s in sections_req if s in SECTIONS) if isinstance(sections_req, list) and sections_req else SECTIONS

    # 아키텍처 메트릭(Phase G) — 스냅샷 지문 디스크 캐시라 재생성 비용 낮음. 부재는 None(섹션 available:false).
    arch_metrics = _arch_metrics_cached(build_root, reports_dir, job_url=job_url)

    inp = SummaryInsightInput(
        # job slug = 빌드 루트(build_N)의 부모 디렉토리명 — reports_dir.parent는 build_N이라 오라벨(W2).
        job_slug=build_root.parent.name if build_root.parent != build_root else "",
        latest_build=latest_build,
        baseline_build=_to_int(base_meta.get("build_number")) if base_meta else None,
        headline=_headline_from_summary(reports_dir),
        top_rules=top_rules_with_files(cur["details"]) if cur else [],
        delta=delta,
        signals=signals,
        complexity_offenders=_complexity_offenders(build_root, reports_dir),
        vcast_failures=_vcast_failures(_find_vcast_rag(reports_dir)),
        # 큐레이션(v3) — raw summary_raw 총계(미추적 627 등 관측치)가 LLM 조치 항목으로
        # 오변환되던 것 차단: design_gap 중심 분류 + note만 전달(기확립 진단과 lockstep).
        trace_summary=curate_trace_summary(body.get("trace_summary") if isinstance(body.get("trace_summary"), dict) else None),
        code_excerpts=excerpts,
        arch_metrics=arch_metrics if (arch_metrics and arch_metrics.get("available")) else None,
        # v4: 테스트 설계 결정론 payload(test-design 엔드포인트와 동일 조립) + 규칙 공식 설명(RCFInfo).
        test_design=_compute_test_design_payload(build_root, reports_dir, job_url=job_url),
        rule_descriptions=(cur["details"].get("rule_descriptions") or {}) if cur else {},
    )
    result = generate_summary_insight(inp, sections=sections)

    # 부분 재생성(sections ⊂ 전체) 시 나머지 섹션은 기존 캐시에서 병합(있으면).
    if cache_valid and set(sections) != set(SECTIONS):
        for name, sec in (cached.get("sections") or {}).items():
            result["sections"].setdefault(name, sec)
        result["ai_enriched"] = any(s.get("ai_enriched") for s in result["sections"].values())

    payload = {
        **result,
        "available": True,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rcr_available": bool(cur),
        "delta_available": bool(delta),
        # 캐시 히트 판정용 원본 지문(W1) — 생성 시점의 RCR stat.
        "rcr_src": _current_rcr_src(build_root, reports_dir),
    }
    _write_cache_atomic(cache_path, payload)
    return {**payload, "cached": False}
