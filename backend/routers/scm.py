from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from backend.dependencies.admin import require_admin
from backend.schemas import ScmLinkedDocs, ScmRegisterRequest, ScmUpdateRequest
from backend.services.scm_registry import (
    ScmValidationError,
    delete_entry,
    get_registry_entry,
    list_registry_entries,
    register_entry,
    replace_linked_docs,
    update_entry,
)
from backend.services.local_service import svn_info_url
from workflow.impact_audit import list_impact_audits
from workflow.impact_changes import (
    build_timeline,
    list_change_logs,
    list_function_history,
    list_module_history,
    load_change_log,
)
from workflow.impact_jobs import list_job_summaries, list_jobs, load_job


router = APIRouter()


# **N15 fix**: _merge_paths가 read-resolver-state → switch_mode write 패턴이라
# 두 SCM 등록 동시 호출 시 last-writer-wins로 한 쪽 prefix 누락 가능.
# Lock으로 read+modify+write 원자성 보장. 단일 사용자 환경이지만 frontend가
# 여러 SCM 등록을 연속 POST하는 케이스 안전성 확보.
_MERGE_LOCK = threading.Lock()


def merge_all_scm_paths_to_cloudium() -> dict:
    """N18 fix: 등록된 모든 SCM entry의 path를 cloudium allowed_prefixes에 일괄 merge.

    backend startup + cloudium 모드 전환 시 호출. 사용자가 SCM 등록 후
    backend 재시작 또는 처음 cloudium 전환 시 자동으로 모든 path 권한 복원 →
    사용자가 SCM 수정 저장 안 해도 추적성/분석 endpoint 통과.

    Returns: {"merged_entries": int, "mode": "cloudium" | "skipped_local"}
    """
    from backend.services.file_resolver import CloudiumFileResolver, get_resolver
    from backend.services.scm_registry import list_registry_entries

    if not isinstance(get_resolver(), CloudiumFileResolver):
        return {"merged_entries": 0, "mode": "skipped_local"}

    count = 0
    for entry in list_registry_entries():
        try:
            _merge_paths_to_cloudium_prefixes(entry)
            count += 1
        except Exception as e:
            import logging
            logging.getLogger("devops_api").warning(
                "SCM entry %s allowed_prefixes merge 실패: %s",
                getattr(entry, "id", "?"), e,
            )
    return {"merged_entries": count, "mode": "cloudium"}


def _merge_paths_to_cloudium_prefixes(entry: Any) -> None:
    """N9 fix (C): cloudium 모드에서 SCM 등록/수정 시 entry의 source_root 및
    linked_docs 부모 디렉토리를 allowed_prefixes에 자동 merge.

    사용자가 SCM 등록 후 별도로 cloudium allowed_prefixes를 갱신하지 않아도
    sync/impact/doc-gen이 곧바로 통과하도록 단일 출처에서 처리.
    local 모드면 no-op. backend 자체 작업 디렉토리(workspace)는 _check_allowed의
    bypass로 별도 처리되므로 여기서는 외부 path만 의미가 있다.

    N15: _MERGE_LOCK으로 read-modify-write race 차단.
    """
    import os
    from backend.services.file_resolver import (
        CloudiumFileResolver,
        get_resolver,
        switch_mode,
    )
    from backend.helpers.common import _parse_path_list

    with _MERGE_LOCK:
        resolver = get_resolver()
        if not isinstance(resolver, CloudiumFileResolver):
            return

        candidates: set[str] = set()
        # source_root는 multi-path string (콤마/세미콜론/뉴라인 구분) 일 수 있음
        src = (getattr(entry, "source_root", "") or "").strip()
        if src:
            for p in _parse_path_list(src):
                parent = os.path.dirname(p.rstrip("/\\")) or p
                if parent:
                    candidates.add(parent)

        linked = getattr(entry, "linked_docs", None)
        if linked is not None:
            try:
                doc_paths = list(linked.model_dump().values())
            except AttributeError:
                doc_paths = [linked.get(k, "") for k in ("srs", "sds", "uds", "sts", "suts", "sits", "hsis", "stp", "syrs", "syts", "syits", "vectorcast")]
            # vectorcast는 복수 경로 list — 단일 string 필드와 함께 평탄화한다.
            flat: list[str] = []
            for v in doc_paths:
                if isinstance(v, (list, tuple)):
                    flat.extend(str(x) for x in v)
                else:
                    flat.append(str(v or ""))
            for v in flat:
                v = (v or "").strip()
                if v:
                    parent = os.path.dirname(v.rstrip("/\\")) or v
                    candidates.add(parent)

        if not candidates:
            return

        existing = list(resolver.allowed_prefixes or [])
        existing_norm = {CloudiumFileResolver._normalize_for_compare(p).rstrip("/") for p in existing}
        new_paths: list[str] = []
        for p in candidates:
            np = CloudiumFileResolver._normalize_for_compare(p).rstrip("/")
            if np in existing_norm:
                continue
            # 이미 존재하는 prefix의 하위 디렉토리면 추가 불필요
            if any(np == ep or np.startswith(ep + "/") for ep in existing_norm):
                continue
            new_paths.append(p)
            existing_norm.add(np)

        if not new_paths:
            return

        merged = ",".join(existing + new_paths)
        switch_mode(
            "cloudium",
            allowed_prefixes=merged,
            gate_process=resolver.gate_process,
        )


def _git_status(entry: Any) -> Dict[str, Any]:
    source_root = Path(str(entry.source_root or "")).expanduser()
    git_ok = shutil.which("git") is not None
    root_ok = source_root.exists() and source_root.is_dir()
    repo_ok = (source_root / ".git").exists() if root_ok else False
    branch = ""
    head = ""
    if git_ok and root_ok and repo_ok:
        try:
            branch = subprocess.check_output(
                ["git", "branch", "--show-current"],
                cwd=str(source_root),
                text=True,
                timeout=15,
            ).strip()
        except Exception:
            branch = ""
        try:
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=str(source_root),
                text=True,
                timeout=15,
            ).strip()
        except Exception:
            head = ""
    return {
        "tool_available": git_ok,
        "source_root_exists": root_ok,
        "repo_detected": repo_ok,
        "branch": branch,
        "head": head,
        "ok": bool(git_ok and root_ok),
    }


def _svn_status(entry: Any) -> Dict[str, Any]:
    svn_ok = shutil.which("svn") is not None
    source_root = Path(str(entry.source_root or "")).expanduser()
    root_ok = source_root.exists() and source_root.is_dir()
    return {
        "tool_available": svn_ok,
        "source_root_exists": root_ok,
        "repo_detected": (source_root / ".svn").exists() if root_ok else False,
        "ok": bool(svn_ok and (root_ok or str(entry.scm_url or "").strip())),
    }


# ── 권한 정책 (2026-08-04, 보안 표면 감사 + 사용자 결정) ─────────────────────
#
# **쓰기 5종만 admin, 읽기는 개방.** 형제 evidence 라우터(swut/swit/swsa/swreport/quality)는
# 라우터 전체가 admin 인데 scm 만 `require_admin` 이 **0건**이었다 — 의도된 예외가 아니라
# 누락이다(`git log -S require_admin -- backend/routers/scm.py` = 이력 전무이고,
# 의도적 비게이트인 file-mode 는 `health.py:233-239` 에 사유 주석이 있는데 여기엔 없다).
#
# 무권한으로 재현된 것(비관리자 헤더 하나, tmp 사본 대상):
#   POST   /api/scm/register        -> 200, entry 생성 + cloudium 읽기 경계 라이브 확장
#   PUT    /api/scm/update/{id}     -> 200, 운영 entry 의 scm_url·scm_username·scm_password_env 변조
#   POST   /api/scm/{id}/link-docs  -> 200, 연결문서 전면 교체(나머지 필드 공란화)
#   DELETE /api/scm/delete/{id}     -> 200, entry 삭제(→ 영향도·문서생성·추적성 탭 전멸)
#   POST   /api/scm/test/{id}       -> 200, **공격자 URL 로 아웃바운드** svn info 시도
#
# `update` 가 특히 중요하다: `scm_url` 재지정 + `scm_password_env` 유지는
# `resolve_scm_credentials`(Jenkins sync·impact_orchestrator 가 쓴다)를 통해
# **`DEVOPS_SCM_PASSWORD` 가 설정되는 순간 자격 유출로 활성화**되는 잠복 경로다
# (현재 그 env 가 비어 있어 유출은 잠복, URL 재지정과 아웃바운드는 라이브였다).
#
# ⚠ **읽기(list/status/audit/change-history/impact-job/build-timeline)는 잠그지 않는다.**
#    형제 라우터와 달리 scm 읽기는 UI 전반에 배선돼 있다 — Dashboard·projectLoader·
#    DocGen·SrsSds·ProjectSummary·Analysis·ImpactGuide 가 앱 초기 로드에 `GET /api/scm/list`
#    를 부른다. 라우터 통짜 게이트는 비관리자 사용자가 생기는 순간 **조회 화면을 통째로**
#    깨뜨린다. 오늘은 등록 사용자가 1명(admin)뿐이라 파손 0이지만, 그건 잠글 이유이지
#    통짜로 잠글 이유는 아니다. (사용자 결정: 읽기 개방 유지)
@router.post("/api/scm/register", dependencies=[Depends(require_admin)])
def scm_register(req: ScmRegisterRequest) -> Dict[str, Any]:
    try:
        entry = register_entry(req)
    except ScmValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        # Remaining ValueError path = "id already exists" → conflict.
        raise HTTPException(status_code=409, detail=str(exc))
    _merge_paths_to_cloudium_prefixes(entry)
    return {"ok": True, "item": entry.model_dump(mode="json")}


@router.get("/api/scm/list")
def scm_list() -> Dict[str, Any]:
    items = [entry.model_dump(mode="json") for entry in list_registry_entries()]
    return {"ok": True, "items": items, "count": len(items)}


@router.put("/api/scm/update/{entry_id}", dependencies=[Depends(require_admin)])
def scm_update(entry_id: str, req: ScmUpdateRequest) -> Dict[str, Any]:
    try:
        entry = update_entry(entry_id, req)
    except KeyError:
        raise HTTPException(status_code=404, detail="registry entry not found")
    except ScmValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _merge_paths_to_cloudium_prefixes(entry)
    return {"ok": True, "item": entry.model_dump(mode="json")}


@router.delete("/api/scm/delete/{entry_id}", dependencies=[Depends(require_admin)])
def scm_delete(entry_id: str) -> Dict[str, Any]:
    deleted = delete_entry(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="registry entry not found")
    return {"ok": True, "deleted": entry_id}


@router.get("/api/scm/linked-docs-status/{entry_id}")
def scm_linked_docs_status(entry_id: str) -> Dict[str, Any]:
    """등록된 연결 문서가 **실제로 존재하는지** 확인한다(레지스트리 경로 전용).

    ## 왜 필요한가

    화면의 '입력 문서 현황'은 경로 **문자열이 비어 있지 않다**는 것만 보고 `등록됨`
    배지를 달았다 — 파일 존재를 확인한 적이 없다. 그래서 문서가 개정되며 파일명이
    바뀌면 배지는 `등록됨` 인데 매트릭스는 "SRS 없음"으로 실패하고, 사용자에게는
    *"문서가 있는데 없다고 나온다"* 로 보인다(실제 보고).

    실측(2026-08-06): `kjpds02` 항목은 등록된 11개 중 **8개가 실물 없음**이었고,
    SRS 는 `_v2.03_…docx` 로 등록돼 있는데 폴더엔 `_v3.01_…_R.docx` 하나뿐이었다.

    ## 입력 표면

    경로는 **레지스트리에서만** 온다 — 사용자 제출 경로를 받지 않으므로 새 입력
    표면이 없다(임의 경로 존재 여부 probe 방지). cloudium 모드에서는 resolver 가
    allowed_prefixes 를 검사한 뒤 worker IPC 로 확인한다.

    실측 비용: 16경로 약 200ms(평균 13ms). ``def`` 라 FastAPI 가 워커 스레드로
    보내므로 이벤트 루프를 막지 않는다.
    """
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")

    from backend.services.file_resolver import get_resolver
    resolver = get_resolver()

    def _probe(path: str) -> Dict[str, Any]:
        try:
            return {"exists": bool(resolver.exists(path)), "reason": ""}
        except PermissionError as exc:
            return {"exists": None, "reason": f"접근 거부 — {str(exc)[:160]}"}
        except Exception as exc:  # noqa: BLE001 — resolver/IPC 계열이 광범위
            # ⚠ 확인 실패를 `exists: false` 로 접지 않는다. "없다"와 "못 봤다"는
            #   다른 말이고, 접으면 멀쩡한 문서를 없다고 보고하게 된다.
            return {"exists": None, "reason": f"확인 실패 ({type(exc).__name__}: {str(exc)[:120]})"}

    # ── 다른 프로젝트 문서가 등록돼 있는가 ────────────────────────────────
    # 존재 확인만으로는 이걸 못 본다. 실측(2026-08-07): `hdpdm01` 항목의 `uds` 가
    # `(KJPDS02_SwUDS)…` 였는데, 파일이 없어서 "파일 없음"으로만 보고됐다 — **진짜 문제가
    # 가려진 것**이다. 파일이 있었다면 다른 프로젝트의 설계서가 이 프로젝트의 추적성
    # 증거로 조용히 들어갔을 것이고, ISO 26262 산출물에서 그건 되돌리기 어렵다.
    # (같은 사고를 저장소가 이미 두 번 고쳤다 — `_pick_doc_path` 저장소 docs/ 바꿔치기,
    #  SUTS ASIL 이 HDPDM01 로 채워지던 건. 여긴 등록 단계라 더 앞이다.)
    from report_gen.doc_kind import cross_project_verdict
    owner_texts = [entry_id, entry.name, entry.source_root, entry.scm_url]

    def _identity(path: str) -> Dict[str, Any]:
        v = cross_project_verdict(owner_texts, path)
        # ⚠ same_project=None(판정 불가)을 '확인됨'으로 접지 않는다 — 그대로 올려서
        #   화면이 "확인함"과 "모름"을 구분할 수 있게 한다.
        return {"same_project": v["same_project"], "identity_reason": v["reason"],
                "doc_tokens": v.get("doc_tokens") or []}

    items: Dict[str, Any] = {}
    for key, value in entry.linked_docs.model_dump(mode="json").items():
        if isinstance(value, list):
            paths = [p for p in value if str(p or "").strip()]
            probed = [_probe(p) for p in paths]
            ids = [_identity(str(p)) for p in paths]
            items[key] = {
                "total": len(probed),
                "missing": sum(1 for r in probed if r["exists"] is False),
                "unknown": sum(1 for r in probed if r["exists"] is None),
                "foreign_project": sum(1 for r in ids if r["same_project"] is False),
            }
        elif str(value or "").strip():
            items[key] = {**_probe(str(value)), **_identity(str(value))}
    foreign = sorted(k for k, v in items.items()
                     if v.get("same_project") is False or v.get("foreign_project"))
    return {"ok": True, "entry_id": entry_id, "items": items,
            "foreign_project_keys": foreign}


@router.get("/api/scm/status/{entry_id}")
def scm_status(entry_id: str) -> Dict[str, Any]:
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")
    mode = str(entry.scm_type or "git").lower()
    if mode == "svn":
        status = _svn_status(entry)
    else:
        status = _git_status(entry)
    if entry.scm_password_env:
        status["password_env_present"] = bool(__import__("os").environ.get(entry.scm_password_env))
    if entry.webhook_secret_env:
        status["webhook_secret_env_present"] = bool(__import__("os").environ.get(entry.webhook_secret_env))
    return {"ok": True, "item": entry.model_dump(mode="json"), "status": status}


@router.post("/api/scm/test/{entry_id}", dependencies=[Depends(require_admin)])
def scm_test(entry_id: str) -> Dict[str, Any]:
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")
    scm_type = str(entry.scm_type or "git").lower()
    if scm_type == "svn":
        info = svn_info_url(repo_url=entry.scm_url, username=entry.scm_username or "")
        return {"ok": info.get("rc") == 0, "result": info}
    status = _git_status(entry)
    return {"ok": bool(status.get("ok")), "result": status}


@router.post("/api/scm/{entry_id}/link-docs", dependencies=[Depends(require_admin)])
def scm_link_docs(entry_id: str, linked_docs: ScmLinkedDocs) -> Dict[str, Any]:
    try:
        entry = replace_linked_docs(entry_id, linked_docs)
    except KeyError:
        raise HTTPException(status_code=404, detail="registry entry not found")
    return {"ok": True, "item": entry.model_dump(mode="json")}


@router.get("/api/scm/audit/{entry_id}")
def scm_audit(entry_id: str, limit: int = 10) -> Dict[str, Any]:
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")
    items = list_impact_audits(entry_id, limit=limit)
    return {"ok": True, "items": items, "count": len(items)}


@router.get("/api/scm/impact-job/{job_id}")
def scm_impact_job(job_id: str) -> Dict[str, Any]:
    try:
        job = load_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="impact job not found")
    return {"ok": True, "job": job}


@router.get("/api/scm/impact-job/{job_id}/result")
def scm_impact_job_result(job_id: str) -> Dict[str, Any]:
    try:
        job = load_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="impact job not found")
    status = str(job.get("status") or "")
    if status == "completed":
        return {"ok": True, "job": job, "result": job.get("result") or {}}
    if status == "failed":
        return {
            "ok": False,
            "job": job,
            "error": job.get("error") or {},
        }
    raise HTTPException(status_code=409, detail="impact job still running")


@router.get("/api/scm/impact-jobs/{entry_id}")
def scm_impact_jobs(entry_id: str, limit: int = 10, summary: bool = False) -> Dict[str, Any]:
    """SCM의 영향도 잡 이력.

    summary=1이면 result 본문을 뺀 경량 투영(빌드/리비전 metadata + 규모 카운트)만 내려준다.
    이력 드롭다운은 이 모드를 쓴다 — full은 잡당 수백 KB~MB라 limit배로 불어난다.
    기본값 False라 기존 호출자의 응답 shape는 불변(하위호환).
    """
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")
    items = (
        list_job_summaries(scm_id=entry_id, limit=limit)
        if summary
        else list_jobs(scm_id=entry_id, limit=limit)
    )
    return {"ok": True, "items": items, "count": len(items)}


@router.get("/api/scm/change-history/{entry_id}")
def scm_change_history(entry_id: str, limit: int = 20) -> Dict[str, Any]:
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")
    items = list_change_logs(entry_id, limit=limit)
    return {"ok": True, "items": items, "count": len(items)}


@router.get("/api/scm/change-history/detail/{run_id}")
def scm_change_history_detail(run_id: str) -> Dict[str, Any]:
    try:
        item = load_change_log(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="change log not found")
    return {"ok": True, "item": item}


@router.get("/api/scm/change-history/function/{entry_id}/{function_name}")
def scm_change_history_function(entry_id: str, function_name: str, limit: int = 20) -> Dict[str, Any]:
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")
    items = list_function_history(entry_id, function_name, limit=limit)
    return {"ok": True, "items": items, "count": len(items)}


@router.get("/api/scm/change-history/module/{entry_id}/{module_name}")
def scm_change_history_module(entry_id: str, module_name: str, limit: int = 20) -> Dict[str, Any]:
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")
    items = list_module_history(entry_id, module_name, limit=limit)
    return {"ok": True, "items": items, "count": len(items)}


@router.get("/api/scm/build-timeline/{entry_id}")
def scm_build_timeline(entry_id: str, limit: int = 50, job_url: str = "", include_all: bool = False,
                       cache_root: str = "") -> Dict[str, Any]:
    """프로젝트 요약 탭 — 분석된 빌드별 변경 영향 타임라인 + 누적 롤업(항상 빠름).

    분석된 빌드는 durable change-log(impact_changes.build_timeline, 잡 pruning 무관)에서 impact
    데이터로 채운다(rows에 analyzed:true). ⚠ **기본은 Jenkins를 조회하지 않는다**(list_builds가
    미도달 시 ~30s hang → 타임라인 로드 지연). '전체 빌드'는 프론트가 `/api/jenkins/builds`를 별도
    비차단으로 가져와 클라이언트에서 병합한다. include_all=true(opt-in)일 때만 서버가 list_builds로
    미분석 빌드를 병합한다(**서버 자격정보만**, SSRF fail-closed). 롤업은 분석된 빌드 기준이라 불변.

    cache_root(opt-in, job_url 동반 필수): 로컬 캐시 빌드(오프라인 메타 — status.json/센티널)를
    추가 병합한다. Jenkins 미도달 환경에서 '캐시에 있는 모든 빌드'를 표면화하는 경로 — 분석 안 된
    캐시 빌드는 {analyzed:false, cached:true} 행으로 추가된다(응답 cache_merge에 병합 통계).
    """
    entry = get_registry_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="registry entry not found")

    data = build_timeline(entry_id, limit=limit)
    rows = data.get("rows") or []
    for r in rows:
        r["analyzed"] = True  # change-log 행 = 분석된 빌드
    enrich_note = ""
    cache_merge: Dict[str, Any] = {"attempted": False, "merged": 0, "added": 0}

    ju = str(job_url or "").strip()
    cr = str(cache_root or "").strip()
    if ju and cr:
        # 로컬 캐시 병합 — Jenkins/네트워크 무관(디스크 직독)이라 항상 빠르고 안전.
        try:
            from backend.helpers.jenkins import _normalize_jenkins_cache_root
            from backend.services.build_inventory import list_cached_builds_meta

            cache_merge["attempted"] = True
            cached_rows = list_cached_builds_meta(job_url=ju, cache_root=_normalize_jenkins_cache_root(cr))
            by_num = {str(r.get("build_number")): r for r in rows if r.get("build_number") is not None}
            for cb in cached_rows:
                num = cb.get("build_number")
                if num is None or int(num) < 0:
                    continue
                existing = by_num.get(str(num))
                if existing is not None:
                    existing["cached"] = True
                    if not existing.get("build_result") and cb.get("result"):
                        existing["build_result"] = cb.get("result")
                    if not existing.get("build_revision") and cb.get("revision"):
                        existing["build_revision"] = cb.get("revision")
                    cache_merge["merged"] += 1
                    continue
                rows.append({
                    "run_id": f"__cached_{num}",
                    "analyzed": False,
                    "cached": True,
                    "build_number": num,
                    "build_revision": cb.get("revision"),
                    "build_revision_is_head": False,
                    "build_result": cb.get("result"),
                    "timestamp": cb.get("timestamp_iso") or "",
                    "changed_files_count": None,
                    "changed_functions_count": None,
                    "impact_counts": {},
                    "max_asil": "",
                    "max_asil_bucket": "unknown",
                    "mcdc_required": False,
                    "auto_docs": 0,
                    "flag_docs": 0,
                    "coverage_measured": False,
                    "coverage_regressed": 0,
                    "coverage_unmeasured_safety": 0,
                    "partial_failure": False,
                })
                cache_merge["added"] += 1
            if cache_merge["added"]:
                rows.sort(key=lambda r: (r.get("build_number") is not None, r.get("build_number") or 0), reverse=True)
        except Exception as exc:
            # best-effort — 캐시 병합 실패해도 분석 타임라인은 유지(침묵 아님: note).
            enrich_note = f"캐시 빌드 병합 실패(무시): {type(exc).__name__}"
    if ju and include_all:
        try:
            from datetime import datetime

            from backend.routers.config import get_jenkins_config
            from backend.services.jenkins_service import list_builds, map_builds_to_svn_revisions

            cfg = get_jenkins_config()
            base_url = str(cfg.get("baseUrl") or "").strip().rstrip("/")
            job_l = ju.lower().rstrip("/")
            under_base = bool(base_url) and (
                job_l == base_url.lower() or job_l.startswith(base_url.lower() + "/")
            )
            if (not under_base) or (".." in ju):
                # SSRF fail-closed: baseUrl 하위가 아니거나 '..'(경로 traversal) 포함이면 서버 토큰을
                # 싣지 않는다. jenkins.py의 _resolve_jenkins_changed_files와 동일 방어.
                enrich_note = "job_url이 서버 Jenkins baseUrl 하위가 아니거나 '..'를 포함해 빌드 조회 안 함(SSRF 차단)"
            elif not (cfg.get("username") and cfg.get("token")):
                enrich_note = "서버 Jenkins 자격정보 미설정 — 빌드 조회 안 함"
            else:
                builds = list_builds(
                    job_url=ju,
                    username=str(cfg.get("username") or ""),
                    api_token=str(cfg.get("token") or ""),
                    limit=200,
                    verify_tls=bool(cfg.get("verifyTls", True)),
                )
                # svn 리비전 best-effort 부착(분석·미분석 행 일관 표시).
                if builds and str(getattr(entry, "scm_type", "") or "").lower() == "svn" and getattr(entry, "scm_url", ""):
                    try:
                        map_builds_to_svn_revisions(
                            repo_url=str(entry.scm_url), builds=builds,
                            username=str(getattr(entry, "scm_username", "") or ""), password="", max_resolve=200,
                        )
                    except Exception:  # silent-ok: 리비전은 best-effort 표시 — 실패해도 빌드 행은 유지
                        pass
                by_num = {
                    str(b.get("number")): b
                    for b in builds
                    if isinstance(b, dict) and b.get("number") is not None
                }
                analyzed_nums = {str(r.get("build_number")) for r in rows if r.get("build_number") is not None}
                # 분석 행 보강(결과/소요/리비전 폴백).
                for row in rows:
                    b = by_num.get(str(row.get("build_number"))) if row.get("build_number") is not None else None
                    if isinstance(b, dict):
                        row["build_result"] = b.get("result")
                        row["build_duration"] = b.get("duration")
                        row["building"] = bool(b.get("building"))
                        if not row.get("build_revision") and b.get("revision"):
                            row["build_revision"] = b.get("revision")
                # 미분석 빌드 최소 행 추가(전체 빌드 이력).
                if include_all:
                    for b in builds:
                        num = b.get("number")
                        if num is None or str(num) in analyzed_nums:
                            continue
                        ts_iso = ""
                        try:
                            if b.get("timestamp"):
                                ts_iso = datetime.fromtimestamp(int(b["timestamp"]) / 1000).isoformat(timespec="seconds")
                        except (TypeError, ValueError, OSError):
                            ts_iso = ""
                        rows.append({
                            "run_id": f"__build_{num}",
                            "analyzed": False,
                            "build_number": num,
                            "build_revision": b.get("revision"),
                            "build_revision_is_head": False,
                            "build_result": b.get("result"),
                            "build_duration": b.get("duration"),
                            "building": bool(b.get("building")),
                            "timestamp": ts_iso,
                            "changed_files_count": None,
                            "changed_functions_count": None,
                            "impact_counts": {},
                            "max_asil": "",
                            "max_asil_bucket": "unknown",
                            "mcdc_required": False,
                            "auto_docs": 0,
                            "flag_docs": 0,
                            "coverage_measured": False,
                            "coverage_regressed": 0,
                            "coverage_unmeasured_safety": 0,
                            "partial_failure": False,
                        })
                    # build_number 내림차순(미매핑 None 마지막).
                    rows.sort(key=lambda r: (r.get("build_number") is not None, r.get("build_number") or 0), reverse=True)
        except Exception as exc:
            # best-effort — 실패해도 분석된 빌드 타임라인은 그대로(침묵 아님: note+로그).
            enrich_note = f"빌드 조회 실패(무시): {type(exc).__name__}"
            import logging

            logging.getLogger("devops_api").warning("build-timeline Jenkins 조회 실패: %s", exc)

    return {
        "ok": True,
        "entry_id": entry_id,
        "rows": rows,
        "rollup": data.get("rollup") or {},
        "enrich_note": enrich_note,
        "cache_merge": cache_merge,
        "snapshot_note": "정적·동적 분석은 현재 SCM 스냅샷 — 빌드별 결과는 추후 Jenkins 산출물 연동 시 각 빌드 행에 표시",
    }
