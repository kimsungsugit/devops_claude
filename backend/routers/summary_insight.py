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

    cached_numbers = {
        n for n in (
            _to_int(b.get("build_number"))
            for b in list_cached_builds_meta(job_url=job_url, cache_root=cache_root)
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
    started = start_backfill(
        job_url=job_url, username=username, api_token=api_token, cache_root=cache_root,
        verify_tls=verify_tls, patterns=[str(p) for p in patterns],
        build_numbers=accepted,
        scm_username=str(body.get("scm_username") or ""), scm_id=str(body.get("scm_id") or ""),
    )
    if not started.get("accepted"):
        return {"ok": True, "available": False, "reason": started.get("reason"), "job_id": started.get("job_id")}
    return {
        "ok": True, "available": True, "reason": None,
        "job_id": started["job_id"], "accepted": accepted, "skipped_cached": skipped,
        "total": len(accepted),
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


@router.post("/api/summary/rule-unresolved-evidence")
def summary_rule_unresolved_evidence(req: dict) -> Dict[str, Any]:
    """미해소 규칙 × 파일의 구간 증거(결정론, LLM 0회) — '변경에도 위반 유지' vs '무변경 잔존'.

    라인 레벨 위반 데이터가 없어(RCR=파일×규칙 카운트가 최상세) 코드 수준 근거는 빌드
    스냅샷 diff가 유일 경로다. '파일 무변경'은 실패가 아니라 그 자체로 유효 증거(위반이
    잔존하는 파일이 구간 내 수정된 적 없음)라 available:true + file_changed:false로 반환한다.
    """
    from backend.services.build_inventory import find_build_meta, list_cached_builds_meta
    from backend.services.prqa_delta import load_rcr_details_cached
    from backend.services.prqa_rule_trend import file_rule_counts
    from backend.services.rule_fix_examples import collect_fix_evidence

    body = req or {}
    job_url = str(body.get("job_url") or "").strip()
    rule = str(body.get("rule") or "").strip()
    file = str(body.get("file") or "").strip()
    from_build = _to_int(body.get("from_build"))
    to_build = _to_int(body.get("to_build"))
    if not job_url or not rule or not file or from_build is None or to_build is None:
        return {"ok": True, "available": False, "reason": "params_required"}
    cache_root = _normalize_jenkins_cache_root(str(body.get("cache_root") or ""))
    metas = list_cached_builds_meta(job_url=job_url, cache_root=cache_root)
    from_meta = find_build_meta(metas, from_build)
    to_meta = find_build_meta(metas, to_build)
    if from_meta is None or to_meta is None:
        return {"ok": True, "available": False, "reason": "build_not_cached"}

    # (rule, file) 구간 카운트 — diff 증거와 독립(RCR 캐시 실패 시 counts만 결측 표기, 0 위장 금지).
    counts: Dict[str, Any] = {"from": None, "to": None}
    counts_reason: Optional[str] = None
    for label, meta in (("from", from_meta), ("to", to_meta)):
        loaded = load_rcr_details_cached(
            Path(str(meta.get("build_root") or "")), Path(str(meta.get("reports_dir") or ""))
        )
        if loaded is None:
            counts_reason = "no_rcr"
            continue
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


RULE_DEF_CACHE_NAME = "summary_rule_definition_cache.json"
_RULE_DEF_CACHE_LOCK = threading.Lock()


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
    from backend.services.rule_fix_examples import collect_fix_evidence, resolve_snapshot_file
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

    # 증거 조립(결정론) — ①해소 구간 diff ≤2 ②미해소 파일 발췌 ≤2(최신 analyzed 스냅샷 head).
    evidence_diffs: List[Dict[str, Any]] = []
    for f in (row.get("decreased_files") or [])[:2]:
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
            evidence_diffs.append(
                {"file": f.get("path"), "text": ev["diff"]["text"], "diff_sha": ev["diff_sha"]}
            )
    unresolved_excerpts: List[Dict[str, Any]] = []
    if to_meta is not None:
        for f in (row.get("files_latest") or [])[:2]:
            p = resolve_snapshot_file(Path(str(to_meta.get("build_root"))), str(f.get("path") or ""))
            if p is None:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")[:2000]
            except OSError:
                continue
            if text.strip():
                unresolved_excerpts.append({"file": f.get("path"), "text": text})
    if not evidence_diffs and not unresolved_excerpts:
        return {"ok": True, "available": False, "reason": "no_code_evidence", "rule": rule}

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


def _aggregate_ut_coverage(entries: List[Dict[str, Any]], worst_limit: int) -> Dict[str, Any]:
    """UT(구문/분기) 함수단위 집계 — 구 quality-detail 로직 이관 + 분기 totals 합산(L1)."""
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
    }


_IT_AXES = ("functions", "function_calls", "statements", "branches")


def _cell_pair(cell: Any) -> Optional[tuple]:
    """{covered,total} → (covered,total). 축 자체가 없거나 비수치면 None(0으로 위장 금지)."""
    if not isinstance(cell, dict):
        return None
    try:
        return int(cell.get("covered")), int(cell.get("total"))
    except (TypeError, ValueError):
        return None


def _aggregate_it_coverage(entries: List[Dict[str, Any]], worst_limit: int) -> Dict[str, Any]:
    """IT 집계 — 소스마다 축이 다르므로 **존재하는 축만** 집계한다.

    실측 스키마 편차:
      - 빌드 산출물 IT: functions(진입) · function_calls (구문/분기 없음)
      - SCM 로드 이력 IT: statements · branches · function_calls (**functions 없음**)
    구 코드는 functions 결측 행을 통째로 skip해 SCM 소스에선 IT가 전부 사라졌다. 축별로
    독립 합산하고 metrics_present로 보유 축을 표기한다(결측 축은 None — 0% 위장 금지).
    unit엔 env 인스턴스 접미사('N)가 붙을 수 있어 표기용으로 정규화한다.
    """
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
    baseline = find_build_meta(with_src, baseline_req) if baseline_req is not None else with_src[-1]  # 최고령
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
                     "timestamp_iso": baseline.get("timestamp_iso")},
        "target": {"build_number": target.get("build_number"), "revision": target.get("revision"),
                   "timestamp_iso": target.get("timestamp_iso")},
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
