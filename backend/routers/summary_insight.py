"""프로젝트 요약탭 심층 데이터 라우터 — 빌드간 PRQA 위반 delta + AI 인사이트.

jenkins.py(6천 줄, 동시 세션 편집 잦음)를 더 키우지 않기 위해 요약탭 신규 API를 이
파일로 분리한다. 경로는 기존 관례(/api/jenkins/*, /api/summary/*)를 따른다.
응답 정직성 규약: 계산 불가는 항상 available:false + reason — 부분 delta나 침묵 0으로
위장하지 않는다. AI 인사이트는 on-demand + 빌드 디렉토리 디스크 캐시(비용 통제).
"""
from __future__ import annotations

import json
import logging
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


def _vcast_failures(reports_dir: Path) -> List[Dict[str, Any]]:
    data = _read_json(reports_dir / "vectorcast_rag.json") or {}
    failures = data.get("failures")
    return [f for f in failures if isinstance(f, dict)][:50] if isinstance(failures, list) else []


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
        tmp = path.with_suffix(".json.tmp")
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
    # 히트 조건: 프롬프트 버전 + RCR 원본 지문(stat 1회) 일치 — 같은 빌드 디렉토리에서
    # RCR이 교체되면(재-sync) stale 인사이트를 cached:true로 서빙하지 않는다(deep-review W1).
    cache_valid = (
        bool(cached)
        and cached.get("prompt_version") == PROMPT_VERSION
        and cached.get("rcr_src") == _current_rcr_src(build_root, reports_dir)
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
        vcast_failures=_vcast_failures(reports_dir),
        trace_summary=body.get("trace_summary") if isinstance(body.get("trace_summary"), dict) else None,
        code_excerpts=excerpts,
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
