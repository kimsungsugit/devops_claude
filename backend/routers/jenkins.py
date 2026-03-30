"""Auto-generated router: jenkins"""
from fastapi import APIRouter, HTTPException, Request, Query, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from typing import Any, Dict, List, Optional, Tuple
import json
import os
import re
import tempfile
import threading
import traceback
import logging
import time
import asyncio
import uuid
from pathlib import Path

from backend.schemas import (
    CallTreePreviewRequest,
    JenkinsBuildInfoRequest,
    JenkinsBuildsRequest,
    JenkinsCacheRequest,
    JenkinsCallTreeRequest,
    JenkinsJobsRequest,
    JenkinsImpactTriggerRequest,
    JenkinsPublishRequest,
    JenkinsRagQueryRequest,
    JenkinsReportRequest,
    JenkinsReportZipRequest,
    JenkinsScmInfoRequest,
    JenkinsServerFilesRequest,
    JenkinsSourceDownloadRequest,
    JenkinsSyncLocalRequest,
    JenkinsSyncRequest,
    ReportZipRequest,
    UdsDeleteRequest,
    UdsDiffRequest,
    UdsLabelRequest,
    UdsPublishRequest,
    UdsTraceabilityMatrixRequest,
)
from datetime import datetime
import config
from backend.helpers import _apply_uds_view_filters, _build_excel_artifact_payload, _build_excel_artifact_summary, _compute_uds_mapping_summary, _create_jenkins_zip_file, _generate_docx_with_retry, _get_progress, _get_uds_view_payload_cached, _is_allowed_req_doc, _jenkins_exports_dir, _jenkins_logic_dir, _jenkins_report_publish_impl, _jenkins_sts_dir, _jenkins_suts_dir, _jenkins_templates_dir, _load_uds_meta, _load_vectorcast_rag, _normalize_jenkins_cache_root, _parse_component_map_file, _parse_path_list, _read_excel_artifact_sidecar, _resolve_cached_build_root, _run_impact_analysis_for_uds, _run_report_with_timeout, _safe_extract_zip, _safe_int, _save_uds_meta, _set_progress, _split_csv, _uds_generate_from_paths, _write_excel_artifact_sidecar, _write_residual_tbd_report, _write_upload_to_temp, build_vectorcast_metadata, evaluate_vectorcast_readiness, load_vectorcast_project_config
from backend.services.jenkins_helpers import _detect_reports_dir, _safe_artifact_path, _job_slug
from backend.services.jenkins_client import JenkinsClient
from backend.services.jenkins_service import (
    get_build_info,
    list_builds,
    list_jobs,
    ensure_source_checkout,
    sync_jenkins_artifacts,
    sync_local_reports,
)
from backend.services.report_parsers import (
    build_report_summary,
    find_jenkins_source_root,
    find_project_report_dirs,
    write_report_index,
    build_report_comparisons,
)
from backend.services.paths import is_under_any
from report_generator import (
    _build_req_map_from_doc_paths,
    enrich_function_details_with_docs,
    generate_uds_source_sections,
    generate_uds_requirements_from_docs,
    generate_uds_validation_report,
    generate_uds_field_quality_gate_report,
    generate_uds_constraints_report,
    generate_uds_preview_html,
)
try:
    from workflow.rag import _read_text_from_file, get_kb, ingest_external_sources
except ImportError:
    _read_text_from_file = None
    get_kb = None
    ingest_external_sources = None
try:
    from workflow.uds_ai import generate_uds_ai_sections
except ImportError:
    generate_uds_ai_sections = None
from workflow.change_trigger import build_registry_trigger
from workflow.impact_orchestrator import run_impact_update
from workflow.impact_jobs import start_impact_job

repo_root = Path(__file__).resolve().parents[2]


router = APIRouter()
_logger = logging.getLogger("devops_api")
_api_logger = _logger


def _write_uds_payload_sidecar(out_path: Path, uds_payload: Dict[str, Any]) -> Optional[Path]:
    try:
        details = uds_payload.get("function_details")
        if not isinstance(details, dict):
            return None
        summary = uds_payload.get("summary")
        if not isinstance(summary, dict):
            summary = {}
        summary["mapping"] = _compute_uds_mapping_summary(details)
        uds_payload["summary"] = summary
        sidecar = out_path.with_suffix(".payload.json")
        payload = {
            "docx_path": str(out_path),
            "summary": summary,
            "function_details": details,
        }
        sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return sidecar
    except Exception as exc:
        _logger.warning("jenkins uds payload sidecar write skipped: %s", exc)
        return None


def _build_jenkins_excel_output(cache_root: str, category: str, stem: str, template_path: Optional[str]) -> Tuple[str, Path]:
    target_dir = _jenkins_sts_dir(cache_root) if category == "sts" else _jenkins_suts_dir(cache_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = Path(template_path).suffix.lower() if template_path and Path(template_path).suffix.lower() in {".xlsx", ".xlsm"} else ".xlsx"
    filename = f"{stem}_{ts}{suffix}"
    return filename, target_dir / filename


def _excel_media_type(file_path: Path) -> str:
    if file_path.suffix.lower() == ".xlsm":
        return "application/vnd.ms-excel.sheet.macroEnabled.12"
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _build_label(job_url: str, cache_root: str, build_selector: str) -> str:
    build_root = _resolve_cached_build_root(job_url, cache_root, build_selector)
    if not build_root:
        return str(build_selector or "").strip()
    m = re.search(r"build_(\d+)$", build_root.name, flags=re.I)
    if m:
        return f"Build {m.group(1)}"
    return build_root.name


def _build_jenkins_vectorcast_response(
    *,
    job_url: str,
    cache_root: str,
    build_selector: str,
    package_dir: Path,
    package_name: str,
    manifest: Dict[str, Any],
    project_config: Dict[str, Any],
    units: List[str],
) -> Dict[str, Any]:
    metadata = build_vectorcast_metadata(
        project_config=project_config,
        source_root=str(project_config.get("source_root") or ""),
        units=units,
    )
    readiness = evaluate_vectorcast_readiness(metadata)
    return {
        "ok": True,
        "job_url": job_url,
        "cache_root": cache_root,
        "build_label": _build_label(job_url, cache_root, build_selector),
        "package_dir": str(package_dir),
        "package_name": package_name,
        "manifest": manifest,
        "files": sorted(str(p.name) for p in package_dir.iterdir() if p.is_file()),
        "project_config": metadata,
        "readiness": readiness,
    }


def _infer_build_label_for_artifact(job_url: str, cache_root: str, artifact_path: Path, build_selector: str) -> str:
    direct = _build_label(job_url, cache_root, build_selector)
    if direct and direct != str(build_selector or "").strip():
        return direct
    base = Path(cache_root).expanduser().resolve() if cache_root else (Path.home() / ".devops_pro_cache").resolve()
    job_root = (base / "jenkins" / _job_slug(job_url)).resolve()
    if not job_root.exists():
        return direct
    build_dirs = [p for p in job_root.glob("build_*") if p.is_dir()]
    if not build_dirs:
        return direct
    if len(build_dirs) == 1:
        m = re.search(r"build_(\d+)$", build_dirs[0].name, flags=re.I)
        return f"Build {m.group(1)}" if m else build_dirs[0].name
    artifact_mtime = artifact_path.stat().st_mtime
    def _score(path: Path) -> Tuple[float, float]:
        delta = abs(path.stat().st_mtime - artifact_mtime)
        prefer_past = 0.0 if path.stat().st_mtime <= artifact_mtime else 1.0
        return (prefer_past, delta)
    best = sorted(build_dirs, key=_score)[0]
    m = re.search(r"build_(\d+)$", best.name, flags=re.I)
    return f"Build {m.group(1)}" if m else best.name


def _load_excel_artifact_payload(
    file_path: Path,
    artifact_type: str,
    *,
    download_url: str,
    preview_url: str,
    build_label: str = "",
) -> Dict[str, Any]:
    payload = _read_excel_artifact_sidecar(file_path)
    if not payload:
        payload = _repair_excel_artifact_payload(
            file_path,
            artifact_type,
            download_url=download_url,
            preview_url=preview_url,
        )
    payload["filename"] = file_path.name
    payload["output_path"] = str(file_path)
    payload["download_url"] = download_url
    payload["preview_url"] = preview_url
    if build_label:
        payload["build_label"] = build_label
    if not str(payload.get("validation_report_path") or "").strip():
        validation_path = file_path.with_suffix(".validation.md")
        payload["validation_report_path"] = str(validation_path) if validation_path.exists() else ""
    if not str(payload.get("residual_report_path") or "").strip():
        residual_path = file_path.with_suffix(".residual.md")
        if not residual_path.exists():
            residual_path = file_path.with_suffix(".residual_tbd.md")
        payload["residual_report_path"] = str(residual_path) if residual_path.exists() else ""
    if not isinstance(payload.get("summary"), dict):
        payload["summary"] = _build_excel_artifact_summary(artifact_type, payload.get("raw_result") or payload)
    if build_label:
        payload["summary"]["build_label"] = build_label
    return payload


def _repair_excel_artifact_payload(
    file_path: Path,
    artifact_type: str,
    *,
    download_url: str,
    preview_url: str,
) -> Dict[str, Any]:
    kind = str(artifact_type or "").strip().lower()
    result: Dict[str, Any] = {
        "ok": True,
        "output_path": str(file_path),
        "filename": file_path.name,
        "download_url": download_url,
        "preview_url": preview_url,
    }
    validation_path = file_path.with_suffix(".validation.md")
    if validation_path.exists():
        result["validation_report_path"] = str(validation_path)
    residual_path = file_path.with_suffix(".residual_tbd.md")
    if residual_path.exists():
        result["residual_report_path"] = str(residual_path)
    try:
        if kind == "sts":
            from generators.suts import validate_sts_xlsm
            validation = validate_sts_xlsm(str(file_path))
            stats = validation.get("stats", {}) if isinstance(validation, dict) else {}
            result["validation"] = validation
            result["test_case_count"] = int(stats.get("tc_count") or 0)
        elif kind == "suts":
            from generators.suts import validate_suts_xlsm
            validation = validate_suts_xlsm(str(file_path))
            stats = validation.get("stats", {}) if isinstance(validation, dict) else {}
            result["validation"] = validation
            result["test_case_count"] = int(stats.get("tc_count") or 0)
            result["total_sequences"] = int(stats.get("seq_count") or 0)
            result["quality_report"] = {
                "avg_sequences_per_tc": float(stats.get("avg_seq_per_tc") or 0),
            }
    except Exception:
        result.setdefault("validation", {})
    payload = _build_excel_artifact_payload(
        kind,
        result,
        output_path=str(file_path),
        filename=file_path.name,
        download_url=download_url,
        preview_url=preview_url,
    )
    _write_excel_artifact_sidecar(file_path, kind, payload)
    return payload

@router.post("/api/jenkins/jobs")
def jenkins_jobs(req: JenkinsJobsRequest) -> Dict[str, Any]:
    base_url = (req.base_url or "").strip().rstrip("/")
    username = (req.username or "").strip()
    api_token = (req.api_token or "").strip()
    _api_logger.info("[jenkins/jobs] base_url=%s, username=%s, token_len=%d, verify_tls=%s", base_url, username, len(api_token), req.verify_tls)
    if not api_token:
        raise HTTPException(status_code=400, detail="API Token이 비어 있습니다. 토큰을 입력해주세요.")
    try:
        jobs = list_jobs(
            base_url=base_url,
            username=username,
            api_token=api_token,
            recursive=req.recursive,
            max_depth=req.max_depth,
            verify_tls=req.verify_tls,
        )
        return {"jobs": jobs}
    except Exception as e:
        error_msg = str(e)
        import traceback
        traceback.print_exc()  # 상세한 스택 트레이스 출력
        _api_logger.error("[jenkins/jobs] error: %s", error_msg)
        
        # 에러 타입에 따라 적절한 HTTP 상태 코드 반환
        error_lower = error_msg.lower()
        if "401" in error_lower or "unauthorized" in error_lower:
            status_code = 401
        elif "403" in error_lower or "forbidden" in error_lower:
            status_code = 403
        elif "404" in error_lower or "not found" in error_lower:
            status_code = 404
        elif "timeout" in error_lower or "timed out" in error_lower:
            status_code = 504
        elif "connection" in error_lower or "refused" in error_lower:
            status_code = 503
        else:
            status_code = 500
            
        raise HTTPException(
            status_code=status_code,
            detail=f"Jenkins 프로젝트 목록 조회 실패: {error_msg}"
        )


@router.post("/api/jenkins/builds")
def jenkins_builds(req: JenkinsBuildsRequest) -> Dict[str, Any]:
    job_url = (req.job_url or "").strip().rstrip("/")
    username = (req.username or "").strip()
    api_token = (req.api_token or "").strip()
    _api_logger.info("[jenkins/builds] job_url=%s, username=%s, token_len=%d", job_url, username, len(api_token))
    if not job_url:
        raise HTTPException(status_code=400, detail="Job URL이 비어 있습니다. Job을 선택해주세요.")
    if not api_token:
        raise HTTPException(status_code=400, detail="API Token이 비어 있습니다.")
    try:
        builds = list_builds(
            job_url=job_url,
            username=username,
            api_token=api_token,
            limit=req.limit,
            verify_tls=req.verify_tls,
        )
        _api_logger.info("[jenkins/builds] success: builds=%d", len(builds))
        return {"builds": builds}
    except Exception as e:
        err = str(e)
        _logger.error("[jenkins/builds] 오류: %s", err)
        import traceback
        traceback.print_exc()
        if "401" in err.lower() or "unauthorized" in err.lower():
            raise HTTPException(status_code=401, detail=f"Jenkins 빌드 목록 조회 실패: {err}")
        if "403" in err.lower() or "forbidden" in err.lower():
            raise HTTPException(status_code=403, detail=f"Jenkins 빌드 목록 조회 실패: {err}")
        if "404" in err.lower() or "not found" in err.lower():
            raise HTTPException(status_code=404, detail=f"Jenkins 빌드 목록 조회 실패: {err}")
        if "timeout" in err.lower() or "timed out" in err.lower():
            raise HTTPException(status_code=504, detail=f"Jenkins 빌드 목록 조회 실패: {err}")
        raise HTTPException(status_code=500, detail=f"Jenkins 빌드 목록 조회 실패: {err}")


@router.post("/api/jenkins/build-info")
def jenkins_build_info(req: JenkinsBuildInfoRequest) -> Dict[str, Any]:
    data = get_build_info(
        job_url=req.job_url,
        username=req.username,
        api_token=req.api_token,
        build_selector=req.build_selector,
        verify_tls=req.verify_tls,
    )
    return data


@router.get("/api/jenkins/progress")
def jenkins_progress(
    action: str,
    job_url: str,
    build_selector: str = "lastSuccessfulBuild",
    job_id: str = "",
) -> Dict[str, Any]:
    data = _get_progress(action, job_url, build_selector, job_id)
    return {"ok": bool(data), "progress": data}


@router.post("/api/jenkins/sync")
def jenkins_sync(req: JenkinsSyncRequest) -> Dict[str, Any]:
    job_url = req.job_url
    build_selector = req.build_selector
    _set_progress(
        "sync",
        job_url,
        build_selector,
        {
            "stage": "start",
            "percent": 1,
            "message": "동기화 준비 중",
            "done": False,
            "error": "",
        },
    )

    def _progress_cb(stage: str, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            data = {}
        percent = 5
        message = ""
        if stage == "list_artifacts":
            percent = 8
            message = f"아티팩트 목록 조회 ({data.get('count', 0)}개)"
        elif stage == "download_start":
            percent = 12
            message = f"아티팩트 다운로드 시작 ({data.get('total', 0)}개)"
        elif stage == "download":
            cur = int(data.get("current") or 0)
            total = max(1, int(data.get("total") or 1))
            percent = 12 + int((cur / total) * 60)
            message = f"다운로드 {cur}/{total}: {data.get('file') or ''}".strip()
        elif stage == "download_console":
            percent = 75
            message = "콘솔 로그 다운로드"
        elif stage == "scan_prepare":
            percent = 80
            message = "리포트 스캔 준비"
        elif stage == "scan_files":
            cur = int(data.get("current") or 0)
            total = max(1, int(data.get("max_files") or 1))
            percent = 80 + int(min(cur, total) / total * 15)
            message = f"리포트 스캔 {cur}개 파일"
        elif stage == "scan_cached":
            percent = 90
            message = "리포트 스캔 캐시 사용"
        elif stage == "scm_clone":
            percent = 78
            message = "SCM 소스 체크아웃"
        elif stage == "scm_done":
            percent = 79
            message = "SCM 소스 체크아웃 완료"
        elif stage == "scm_failed":
            percent = 79
            message = "SCM 소스 체크아웃 실패"
        elif stage == "scan_start":
            percent = 82
            message = "리포트 스캔/요약 생성"
        elif stage == "scan_done":
            percent = 95
            message = "리포트 요약 완료"
        _set_progress(
            "sync",
            job_url,
            build_selector,
            {
                "stage": stage,
                "percent": percent,
                "message": message,
                "current": data.get("current"),
                "total": data.get("total"),
                "file": data.get("file"),
            },
        )

    try:
        build_info, build_root, reports_dir, downloaded, artifacts = sync_jenkins_artifacts(
            job_url=req.job_url,
            username=req.username,
            api_token=req.api_token,
            cache_root=_normalize_jenkins_cache_root(req.cache_root),
            verify_tls=req.verify_tls,
            build_selector=req.build_selector,
            patterns=req.patterns,
            progress_cb=_progress_cb,
            scan_mode=req.scan_mode,
            scan_max_files=req.scan_max_files,
        )
        _set_progress(
            "sync",
            job_url,
            build_selector,
            {
                "stage": "done",
                "percent": 100,
                "message": "동기화 완료",
                "done": True,
            },
        )
        return {
            "build_info": build_info,
            "build_root": str(build_root),
            "reports_dir": str(reports_dir),
            "downloaded": downloaded,
            "artifacts": artifacts,
            "data": read_report_bundle(reports_dir),
        }
    except Exception as exc:
        tb = traceback.format_exc()
        _set_progress(
            "sync",
            job_url,
            build_selector,
            {
                "stage": "error",
                "percent": 100,
                "message": "동기화 실패",
                "done": True,
                "error": str(exc),
                "error_detail": tb,
            },
        )
        raise


@router.post("/api/jenkins/sync-async")
def jenkins_sync_async(req: JenkinsSyncRequest) -> Dict[str, Any]:
    job_url = req.job_url
    build_selector = req.build_selector
    job_id = uuid.uuid4().hex
    _set_progress(
        "sync",
        job_url,
        build_selector,
        {
            "stage": "start",
            "percent": 1,
            "message": "동기화 준비 중",
            "done": False,
            "error": "",
        },
        job_id=job_id,
    )

    def _progress_cb(stage: str, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            data = {}
        percent = 5
        message = ""
        if stage == "list_artifacts":
            percent = 8
            message = f"아티팩트 목록 조회 ({data.get('count', 0)}개)"
        elif stage == "download_start":
            percent = 12
            message = f"아티팩트 다운로드 시작 ({data.get('total', 0)}개)"
        elif stage == "download":
            cur = int(data.get("current") or 0)
            total = max(1, int(data.get("total") or 1))
            percent = 12 + int((cur / total) * 60)
            message = f"다운로드 {cur}/{total}: {data.get('file') or ''}".strip()
        elif stage == "download_console":
            percent = 75
            message = "콘솔 로그 다운로드"
        elif stage == "scan_prepare":
            percent = 80
            message = "리포트 스캔 준비"
        elif stage == "scan_files":
            cur = int(data.get("current") or 0)
            total = max(1, int(data.get("max_files") or 1))
            percent = 80 + int(min(cur, total) / total * 15)
            message = f"리포트 스캔 {cur}개 파일"
        elif stage == "scan_cached":
            percent = 90
            message = "리포트 스캔 캐시 사용"
        elif stage == "scm_clone":
            percent = 78
            message = "SCM 소스 체크아웃"
        elif stage == "scm_done":
            percent = 79
            message = "SCM 소스 체크아웃 완료"
        elif stage == "scm_failed":
            percent = 79
            message = "SCM 소스 체크아웃 실패"
        elif stage == "scan_start":
            percent = 82
            message = "리포트 스캔/요약 생성"
        elif stage == "scan_done":
            percent = 95
            message = "리포트 요약 완료"
        _set_progress(
            "sync",
            job_url,
            build_selector,
            {
                "stage": stage,
                "percent": percent,
                "message": message,
                "current": data.get("current"),
                "total": data.get("total"),
                "file": data.get("file"),
            },
            job_id=job_id,
        )

    def _run_sync() -> None:
        try:
            sync_jenkins_artifacts(
                job_url=req.job_url,
                username=req.username,
                api_token=req.api_token,
                cache_root=_normalize_jenkins_cache_root(req.cache_root),
                verify_tls=req.verify_tls,
                build_selector=req.build_selector,
                patterns=req.patterns,
                progress_cb=_progress_cb,
                scan_mode=req.scan_mode,
                scan_max_files=req.scan_max_files,
            )
            _set_progress(
                "sync",
                job_url,
                build_selector,
                {
                    "stage": "done",
                    "percent": 100,
                    "message": "동기화 완료",
                    "done": True,
                },
                job_id=job_id,
            )
        except Exception as exc:
            tb = traceback.format_exc()
            _set_progress(
                "sync",
                job_url,
                build_selector,
                {
                    "stage": "error",
                    "percent": 100,
                    "message": "동기화 실패",
                    "done": True,
                    "error": str(exc),
                    "error_detail": tb,
                },
                job_id=job_id,
            )

    t = threading.Thread(target=_run_sync, daemon=True)
    t.start()
    return {"ok": True, "job_id": job_id}


@router.post("/api/jenkins/sync-local")
def jenkins_sync_local(req: JenkinsSyncLocalRequest) -> Dict[str, Any]:
    build_info, build_root, reports_dir, downloaded, artifacts = sync_local_reports(
        job_url=req.job_url,
        local_reports_dir=Path(req.local_reports_dir),
    )
    return {
        "build_info": build_info,
        "build_root": str(build_root),
        "reports_dir": str(reports_dir),
        "downloaded": downloaded,
        "artifacts": artifacts,
        "data": read_report_bundle(reports_dir),
    }


@router.post("/api/jenkins/cache")
def jenkins_cache(req: JenkinsCacheRequest) -> Dict[str, Any]:
    rows = list_cached_builds(job_url=req.job_url, cache_root=_normalize_jenkins_cache_root(req.cache_root))
    return {"builds": rows}


@router.post("/api/jenkins/report/data")
def jenkins_report_data(req: JenkinsReportRequest) -> Dict[str, Any]:
    build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    reports_dir = (build_root / "reports").resolve()
    return read_report_bundle(reports_dir)


@router.post("/api/jenkins/rag/query")
def jenkins_rag_query(req: JenkinsRagQueryRequest) -> Dict[str, Any]:
    query = str(req.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query required")
    build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    report_dir = _detect_reports_dir(build_root)
    kb = get_kb(report_dir)
    top_k = max(1, int(req.top_k or 5))
    categories = [str(c).strip() for c in (req.categories or []) if str(c).strip()]
    rows = kb.search(query, top_k=top_k, categories=categories or None)
    items = []
    for row in rows:
        items.append(
            {
                "title": row.get("error_raw") or "",
                "category": row.get("category") or "",
                "source_file": row.get("source_file") or "",
                "score": float(row.get("score") or 0.0),
                "snippet": str(row.get("fix") or "")[:1200],
            }
        )
    return {"ok": True, "items": items}


@router.post("/api/jenkins/report/complexity")
def jenkins_complexity(req: JenkinsReportRequest) -> Dict[str, Any]:
    build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    report_dir = _detect_reports_dir(build_root)
    return {"rows": read_csv_rows(report_dir / "complexity.csv")}


@router.post("/api/jenkins/report/docs")
def jenkins_docs(req: JenkinsReportRequest) -> Dict[str, Any]:
    build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    report_dir = _detect_reports_dir(build_root)
    doc_path = (report_dir / "docs" / "html" / "index.html").resolve()
    if not doc_path.exists():
        return {"ok": False, "html": ""}
    return {"ok": True, "html": doc_path.read_text(encoding="utf-8", errors="ignore")}


@router.post("/api/jenkins/report/logs")
def jenkins_logs(req: JenkinsReportRequest) -> Dict[str, Any]:
    build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    report_dir = _detect_reports_dir(build_root)
    logs = list_log_candidates(report_dir)
    out = {k: [str(p.relative_to(report_dir)) for p in v] for k, v in logs.items()}
    return {"logs": out}


@router.post("/api/jenkins/report/logs/read")
def jenkins_logs_read(req: JenkinsReportRequest, path: str) -> Dict[str, Any]:
    build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    report_dir = _detect_reports_dir(build_root)
    try:
        target = safe_resolve_under(report_dir, path)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid path")
    if not target.exists():
        raise HTTPException(status_code=404, detail="log not found")
    return {"path": str(target), "text": tail_text(target)}


@router.post("/api/jenkins/report/summary")
def jenkins_report_summary(req: JenkinsReportRequest) -> Dict[str, Any]:
    build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    report_dir = _detect_reports_dir(build_root)
    return build_report_summary(report_dir, project_root=repo_root)


@router.post("/api/jenkins/report/vectorcast-rag")
def jenkins_vectorcast_rag(req: JenkinsReportRequest) -> Dict[str, Any]:
    build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    payload = _load_vectorcast_rag(build_root)
    if not payload:
        return {"ok": False, "error": "missing"}

    comparison: Dict[str, Any] = {}
    try:
        builds = list_cached_builds(job_url=req.job_url, cache_root=_normalize_jenkins_cache_root(req.cache_root))
        summaries: List[Dict[str, Any]] = []
        for row in builds:
            cand_root = Path(row.get("build_root", ""))
            if not cand_root.exists():
                continue
            rag = _load_vectorcast_rag(cand_root)
            if not isinstance(rag, dict) or not rag.get("summary"):
                continue
            summaries.append({"summary": rag.get("summary") or {}, "build": row})
            if len(summaries) >= 2:
                break
        if len(summaries) >= 2:
            cur = summaries[0]["summary"]
            prev = summaries[1]["summary"]
            comparison = {
                "current": cur,
                "previous": prev,
                "delta": {
                    "total": (cur.get("total") or 0) - (prev.get("total") or 0),
                    "passed": (cur.get("passed") or 0) - (prev.get("passed") or 0),
                    "failed": (cur.get("failed") or 0) - (prev.get("failed") or 0),
                    "skipped": (cur.get("skipped") or 0) - (prev.get("skipped") or 0),
                    "pass_rate": (cur.get("pass_rate") or 0) - (prev.get("pass_rate") or 0),
                },
            }
    except Exception:
        comparison = {}

    return {"ok": True, "data": payload, "comparison": comparison}


@router.post("/api/jenkins/source-root")
def jenkins_source_root(req: JenkinsReportRequest) -> Dict[str, Any]:
    build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    return find_jenkins_source_root(build_root)


@router.post("/api/jenkins/source-root/download")
def jenkins_source_root_download(req: JenkinsSourceDownloadRequest) -> Dict[str, Any]:
    build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    source_dir = (Path(build_root) / "source").resolve()
    client = JenkinsClient(
        job_url=req.job_url,
        username=req.username,
        api_token=req.api_token,
        timeout_sec=30,
        verify_ssl=bool(req.verify_tls),
    )
    artifact_info: Dict[str, Any] | None = None

    def _download_artifact_url(artifact_url: str) -> Optional[Path]:
        if not artifact_url:
            return None
        parsed = urlparse(artifact_url)
        if not parsed.scheme or "/artifact/" not in parsed.path:
            return None
        rel = unquote(parsed.path.split("/artifact/", 1)[1]).lstrip("/")
        if not rel:
            return None
        dst = _safe_artifact_path(Path(build_root), rel)
        if not dst:
            dst = (Path(build_root) / "artifact_source" / Path(rel).name).resolve()
        dst.parent.mkdir(parents=True, exist_ok=True)
        req_obj = client._auth_req(artifact_url, accept="application/octet-stream")
        raw = client._open_bytes(req_obj)
        dst.write_bytes(raw)
        return dst
    checkout_result = ensure_source_checkout(
        build_root=build_root,
        client=client,
        build_selector=req.build_selector,
        progress_cb=None,
    )
    def _dir_has_entries(path: Path) -> bool:
        try:
            return path.exists() and path.is_dir() and any(path.iterdir())
        except Exception:
            return False
    if _dir_has_entries(source_dir):
        return {
            "ok": True,
            "path": str(source_dir),
            "build_root": str(build_root),
            "scm": checkout_result.get("scm"),
            "repo_url": checkout_result.get("repo_url"),
            "branch": checkout_result.get("branch"),
            "revision": checkout_result.get("revision"),
        }
    if req.scm_url:
        scm_type = (req.scm_type or "svn").lower()
        if scm_type == "svn":
            alt = run_svn(
                project_root=str(build_root),
                workdir_rel="source",
                action="checkout",
                repo_url=req.scm_url,
                revision=req.scm_revision or "",
                username=req.scm_username or "",
                password=req.scm_password or "",
            )
            if alt.get("rc") == 0 and _dir_has_entries(source_dir):
                return {
                    "ok": True,
                    "path": str(source_dir),
                    "build_root": str(build_root),
                    "source": "scm_manual",
                    "scm": "svn",
                    "repo_url": req.scm_url,
                    "revision": req.scm_revision,
                }
    if req.source_root:
        try:
            artifact_path = _download_artifact_url(req.source_root)
            if artifact_path:
                artifact_info = {"path": str(artifact_path), "source_root": req.source_root}
                if artifact_path.suffix.lower() == ".zip":
                    _safe_extract_zip(artifact_path, source_dir)
        except Exception as exc:
            artifact_info = {"error": str(exc), "source_root": req.source_root}
    if _dir_has_entries(source_dir):
        return {
            "ok": True,
            "path": str(source_dir),
            "build_root": str(build_root),
            "source": "artifact_zip",
            "scm": checkout_result.get("scm"),
            "repo_url": checkout_result.get("repo_url"),
            "branch": checkout_result.get("branch"),
            "revision": checkout_result.get("revision"),
            "artifact": artifact_info,
        }
    # fallback: source may exist in artifacts under a different path
    source_root_info = find_jenkins_source_root(Path(build_root))
    for cand in source_root_info.get("candidates", []):
        cand_path = Path(cand.get("path", ""))
        if _dir_has_entries(cand_path):
            return {
                "ok": True,
                "path": str(cand_path),
                "build_root": str(build_root),
                "source": "artifact",
                "scm": checkout_result.get("scm"),
                "repo_url": checkout_result.get("repo_url"),
                "branch": checkout_result.get("branch"),
                "revision": checkout_result.get("revision"),
                "candidates": source_root_info.get("candidates", []),
                "artifact": artifact_info,
            }
    return {
        "ok": False,
        "error": "source_dir_missing",
        "build_root": str(build_root),
        "source_dir": str(source_dir),
        "scm": checkout_result.get("scm"),
        "repo_url": checkout_result.get("repo_url"),
        "branch": checkout_result.get("branch"),
        "revision": checkout_result.get("revision"),
        "checkout_error": checkout_result.get("error"),
        "checkout_output": checkout_result.get("output"),
        "candidates": source_root_info.get("candidates", []),
        "artifact": artifact_info,
    }


@router.post("/api/jenkins/scm-info")
def jenkins_scm_info(req: JenkinsScmInfoRequest) -> Dict[str, Any]:
    if not req.scm_url:
        raise HTTPException(status_code=400, detail="scm_url required")
    scm_type = (req.scm_type or "svn").lower()
    if scm_type == "svn":
        info = svn_info_url(
            repo_url=req.scm_url,
            username=req.scm_username or "",
            password=req.scm_password or "",
        )
        if info.get("rc") != 0:
            raise HTTPException(status_code=500, detail=info.get("output") or "svn info failed")
        return {"ok": True, "scm": "svn", "revision": info.get("revision") or "", "output": info.get("output")}
    raise HTTPException(status_code=400, detail="unsupported scm_type")


@router.post("/api/jenkins/impact/trigger")
def jenkins_impact_trigger(req: JenkinsImpactTriggerRequest) -> Dict[str, Any]:
    try:
        trigger = build_registry_trigger(
            trigger_type="jenkins",
            scm_id=req.scm_id,
            base_ref=req.base_ref,
            dry_run=req.dry_run,
            targets=req.targets or None,
            metadata={
                "source": "api/jenkins/impact/trigger",
                "build_number": req.build_number,
                "job_url": req.job_url,
            },
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="registry entry not found")
    return run_impact_update(trigger)


@router.post("/api/jenkins/impact/trigger-async")
def jenkins_impact_trigger_async(req: JenkinsImpactTriggerRequest) -> Dict[str, Any]:
    try:
        trigger = build_registry_trigger(
            trigger_type="jenkins",
            scm_id=req.scm_id,
            base_ref=req.base_ref,
            dry_run=req.dry_run,
            targets=req.targets or None,
            metadata={
                "source": "api/jenkins/impact/trigger-async",
                "build_number": req.build_number,
                "job_url": req.job_url,
            },
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="registry entry not found")
    return start_impact_job(trigger)


@router.post("/api/jenkins/uds/template-upload")
async def jenkins_uds_template_upload(
    file: UploadFile = File(...),
    job_url: str = Form(...),
    cache_root: str = Form(""),
    build_selector: str = Form("lastSuccessfulBuild"),
) -> Dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="template filename required")
    job_slug = _job_slug(job_url)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = Path(file.filename).suffix.lower() or ".docx"
    out_dir = _jenkins_templates_dir(cache_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"uds_template_{job_slug}_{ts}{ext}"
    content = await file.read()
    out_path.write_bytes(content)
    return {
        "ok": True,
        "template_path": str(out_path),
        "filename": out_path.name,
        "build_selector": build_selector,
    }


@router.post("/api/jenkins/uds/generate")
async def jenkins_uds_generate(
    job_url: str = Form(...),
    cache_root: str = Form(""),
    build_selector: str = Form("lastSuccessfulBuild"),
    template_path: str = Form(""),
    source_root: str = Form(""),
    source_only: bool = Form(False),
    req_files: List[UploadFile] = File(default_factory=list),
    req_paths: str = Form(""),
    logic_files: List[UploadFile] = File(default_factory=list),
    files: List[UploadFile] = File(default_factory=list),
    component_list: UploadFile = File(default=None),
    call_relation_mode: str = Form("code"),
    req_types: str = Form(""),
    show_mapping_evidence: bool = Form(False),
) -> Dict[str, Any]:
    source_root_path = Path(source_root).resolve() if source_root else None
    if not source_root_path or not source_root_path.exists() or not source_root_path.is_dir():
        raise HTTPException(status_code=400, detail="source_root(코드 루트)가 필요합니다.")
    req_paths_list = _parse_path_list(req_paths)
    has_req_upload = any((f and f.filename) for f in (req_files or []))
    if not has_req_upload and not req_paths_list:
        raise HTTPException(status_code=400, detail="SRS/SDS 요구사항 문서를 최소 1개 이상 제공해주세요.")

    type_list = [t.strip().lower() for t in req_types.split(",") if t.strip()] if req_types else []

    build_root = _resolve_cached_build_root(job_url, cache_root, build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    report_dir = _detect_reports_dir(build_root)
    summary = build_report_summary(report_dir, project_root=repo_root)

    notes: List[str] = []
    for f in files:
        if not f or not f.filename:
            continue
        suffix = Path(f.filename).suffix.lower() or ".txt"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await f.read())
            tmp_path = Path(tmp.name)
        try:
            text = _read_text_from_file(tmp_path)
        except Exception:
            text = ""
        if text:
            notes.append(text.strip())

    req_texts: List[str] = []
    component_map: Dict[str, Dict[str, str]] = {}
    if component_list and component_list.filename:
        tmp = _write_upload_to_temp(component_list, ".json")
        if tmp:
            try:
                component_map = _parse_component_map_file(tmp)
            except Exception:
                component_map = {}
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
    srs_texts: List[str] = []
    sds_texts: List[str] = []
    req_doc_paths: List[str] = []
    for idx, f in enumerate(req_files):
        if not f or not f.filename:
            continue
        suffix = Path(f.filename).suffix.lower() or ".txt"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await f.read())
            tmp_path = Path(tmp.name)
        try:
            text = _read_text_from_file(tmp_path)
        except Exception:
            text = ""
        if tmp_path.suffix.lower() == ".docx":
            req_doc_paths.append(str(tmp_path))
        if text:
            req_texts.append(text.strip())
            ftype = type_list[idx] if idx < len(type_list) else ""
            if ftype == "srs":
                srs_texts.append(text.strip())
            elif ftype == "sds":
                sds_texts.append(text.strip())
    for path_str in req_paths_list:
        try:
            p = Path(path_str).expanduser().resolve()
            if not p.exists() or not p.is_file():
                continue
            if not _is_allowed_req_doc(p):
                continue
            text = _read_text_from_file(p)
        except Exception:
            text = ""
        if text:
            req_texts.append(text.strip())
            if p.suffix.lower() == ".docx":
                req_doc_paths.append(str(p))

    jenkins_meta = summary.get("jenkins") if isinstance(summary, dict) else {}
    if not isinstance(jenkins_meta, dict):
        jenkins_meta = {}
    summary_text = summary.get("summary_text", "") if isinstance(summary, dict) else ""
    source_sections: Dict[str, str] = {}
    if source_root_path and source_root_path.exists():
        source_sections = generate_uds_source_sections(
            str(source_root_path),
            component_map=component_map if component_map else None,
        )
    sds_doc_paths: List[str] = []
    for p in req_doc_paths:
        if "sds" in Path(p).name.lower():
            sds_doc_paths.append(str(p))
    if source_sections:
        details = source_sections.get("function_details", {})
        if isinstance(details, dict):
            enrich_function_details_with_docs(
                details,
                source_sections.get("function_table_rows", []),
                req_doc_paths=req_doc_paths,
                sds_doc_paths=sds_doc_paths,
            )
            source_sections["function_details"] = details
            rebuilt_by_name: Dict[str, Any] = {}
            for _, info in details.items():
                if not isinstance(info, dict):
                    continue
                name = str(info.get("name") or "").strip().lower()
                if name:
                    rebuilt_by_name[name] = info
            source_sections["function_details_by_name"] = rebuilt_by_name
    req_from_docs = generate_uds_requirements_from_docs(req_texts) if req_texts else ""
    req_map = _build_req_map_from_doc_paths(req_doc_paths, req_texts) if req_texts or req_doc_paths else {}
    logic_items: List[Dict[str, Any]] = []
    if logic_files:
        logic_dir = _jenkins_logic_dir(cache_root)
        logic_dir.mkdir(parents=True, exist_ok=True)
        ts_logic = datetime.now().strftime("%Y%m%d_%H%M%S")
        for f in logic_files:
            if not f or not f.filename:
                continue
            suffix = Path(f.filename).suffix.lower() or ".png"
            safe_name = "".join(c for c in Path(f.filename).stem if c.isalnum() or c in ("-", "_"))
            out_name = f"logic_{safe_name}_{ts_logic}{suffix}"
            out_path = logic_dir / out_name
            out_path.write_bytes(await f.read())
            logic_items.append(
                {
                    "title": f.filename,
                    "path": str(out_path),
                    "url": f"/api/jenkins/uds/logic?job_url={job_url}&cache_root={cache_root}&filename={out_name}",
                }
            )

    req_source = source_sections.get("requirements", "")
    if source_only:
        req_combined = req_source
    elif req_from_docs and req_source:
        req_combined = "\n".join([req_from_docs.strip(), req_source.strip()]).strip()
    else:
        req_combined = req_from_docs or req_source
    globals_order_list: List[str] = []
    globals_format_sep = ""
    logic_max_children = None
    logic_max_grandchildren = None
    logic_max_depth = None
    uds_payload = {
        "job_url": job_url,
        "build_number": jenkins_meta.get("build_number"),
        "project_name": summary.get("project") if isinstance(summary, dict) else "",
        "summary": summary,
        "overview": summary_text or source_sections.get("overview", ""),
        "requirements": req_combined,
        "interfaces": source_sections.get("interfaces", ""),
        "uds_frames": source_sections.get("uds_frames", ""),
        "notes": "\n".join(notes),
        "logic_diagrams": logic_items,
        "software_unit_design": source_sections.get("software_unit_design", ""),
        "unit_structure": source_sections.get("unit_structure", ""),
        "global_data": source_sections.get("global_data", ""),
        "interface_functions": source_sections.get("interface_functions", ""),
        "internal_functions": source_sections.get("internal_functions", ""),
        "function_table_rows": source_sections.get("function_table_rows", []),
        "global_vars": source_sections.get("global_vars", []),
        "static_vars": source_sections.get("static_vars", []),
        "macro_defs": source_sections.get("macro_defs", []),
        "calibration_params": source_sections.get("calibration_params", []),
        "function_details": source_sections.get("function_details", {}),
        "function_details_by_name": source_sections.get("function_details_by_name", {}),
        "call_map": source_sections.get("call_map", {}),
        "module_map": source_sections.get("module_map", {}),
        "req_map": req_map,
        "globals_info_map": source_sections.get("globals_info_map", {}),
        "common_macros": source_sections.get("common_macros", []),
        "type_defs": source_sections.get("type_defs", []),
        "param_defs": source_sections.get("param_defs", []),
        "version_defs": source_sections.get("version_defs", []),
        "globals_format_order": globals_order_list,
        "globals_format_sep": globals_format_sep,
        "logic_max_children": logic_max_children,
        "logic_max_grandchildren": logic_max_grandchildren,
        "logic_max_depth": logic_max_depth,
        "call_relation_mode": call_relation_mode,
        "show_mapping_evidence": bool(show_mapping_evidence),
        "srs_texts": srs_texts,
        "sds_texts": sds_texts,
    }
    impact_path = _run_impact_analysis_for_uds(
        source_root_path,
        os.getenv("UDS_CHANGED_FILES", ""),
    )
    if impact_path:
        notes_text = str(uds_payload.get("notes") or "").strip()
        uds_payload["notes"] = "\n".join([x for x in [notes_text, f"impact:{impact_path.name}"] if x])
    if source_only and source_sections.get("notes"):
        uds_payload["notes"] = (uds_payload.get("notes") or "").strip()
        uds_payload["notes"] = "\n".join(
            [x for x in [uds_payload["notes"], source_sections.get("notes")] if x]
        )
    job_slug = _job_slug(job_url)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = _jenkins_exports_dir(cache_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"uds_spec_{job_slug}_{ts}.docx"
    tpl = str(template_path).strip() or None
    _generate_docx_with_retry(tpl, uds_payload, out_path)
    _write_uds_payload_sidecar(out_path, uds_payload)
    residual_tbd_path = _write_residual_tbd_report(out_path, (uds_payload.get("summary") or {}).get("mapping") or {})
    validation_path = out_path.with_suffix(".validation.md")
    _jenkins_report_short = 300
    _jenkins_report_long = 600
    ok_validation, _ = _run_report_with_timeout(
        lambda: generate_uds_validation_report(str(out_path), str(validation_path)),
        timeout_seconds=_jenkins_report_short,
        report_name="validation report",
    )
    if not ok_validation:
        validation_path = None
    accuracy_path = out_path.with_suffix(".accuracy.md")
    src_root = str(source_root_path) if source_root_path else ""
    ok_accuracy, _ = _run_report_with_timeout(
        lambda: generate_called_calling_accuracy_report(
            str(out_path),
            src_root,
            str(accuracy_path),
            relation_mode=str(call_relation_mode or "code"),
        ),
        timeout_seconds=_jenkins_report_long,
        report_name="accuracy report",
    )
    if not ok_accuracy:
        accuracy_path = None
    swcom_context_path = out_path.with_suffix(".swcom_context.md")
    ok_swcom, _ = _run_report_with_timeout(
        lambda: generate_swcom_context_report(str(out_path), str(swcom_context_path)),
        timeout_seconds=_jenkins_report_short,
        report_name="swcom context report",
    )
    if not ok_swcom:
        swcom_context_path = None
    swcom_diff_path = None
    confidence_path = out_path.with_suffix(".field_confidence.md")
    ok_confidence, _ = _run_report_with_timeout(
        lambda: generate_asil_related_confidence_report(
            uds_payload,
            str(confidence_path),
            str(out_path),
        ),
        timeout_seconds=_jenkins_report_long,
        report_name="ASIL/Related confidence report",
    )
    if not ok_confidence:
        confidence_path = None
    constraints_path = out_path.with_suffix(".constraints.md")
    ok_constraints, _ = _run_report_with_timeout(
        lambda: generate_uds_constraints_report(uds_payload, str(constraints_path)),
        timeout_seconds=_jenkins_report_short,
        report_name="constraints report",
    )
    if not ok_constraints:
        constraints_path = None
    quality_gate_path = out_path.with_suffix(".quality_gate.md")
    ok_quality_gate, _ = _run_report_with_timeout(
        lambda: generate_uds_field_quality_gate_report(str(out_path), str(quality_gate_path)),
        timeout_seconds=_jenkins_report_short,
        report_name="field quality gate report",
    )
    if not ok_quality_gate:
        quality_gate_path = None
    preview_html = generate_uds_preview_html(uds_payload)
    preview_path = out_path.with_suffix(".html")
    preview_path.write_text(preview_html, encoding="utf-8")
    return {
        "ok": True,
        "filename": out_path.name,
        "download_url": f"/api/jenkins/uds/download?job_url={job_url}&cache_root={cache_root}&filename={out_path.name}",
        "preview_url": f"/api/jenkins/uds/preview?job_url={job_url}&cache_root={cache_root}&filename={preview_path.name}",
        "validation_path": str(validation_path) if validation_path else "",
        "accuracy_path": str(accuracy_path) if accuracy_path else "",
        "swcom_context_path": str(swcom_context_path) if swcom_context_path else "",
        "swcom_diff_path": str(swcom_diff_path) if swcom_diff_path else "",
        "confidence_path": str(confidence_path) if confidence_path else "",
        "constraints_path": str(constraints_path) if constraints_path else "",
        "quality_gate_path": str(quality_gate_path) if quality_gate_path else "",
        "impact_path": str(impact_path) if impact_path else "",
        "residual_tbd_report_path": str(residual_tbd_path) if residual_tbd_path else "",
    }


@router.post("/api/jenkins/uds/generate-async")
async def jenkins_uds_generate_async(
    job_url: str = Form(...),
    cache_root: str = Form(""),
    build_selector: str = Form("lastSuccessfulBuild"),
    template_path: str = Form(""),
    source_root: str = Form(""),
    source_only: bool = Form(False),
    req_files: List[UploadFile] = File(default_factory=list),
    req_paths: str = Form(""),
    logic_files: List[UploadFile] = File(default_factory=list),
    files: List[UploadFile] = File(default_factory=list),
    component_list: UploadFile = File(default=None),
    logic_source: str = Form(""),
    logic_max_children: Optional[int] = Form(None),
    logic_max_grandchildren: Optional[int] = Form(None),
    logic_max_depth: Optional[int] = Form(None),
    globals_format_order: str = Form(""),
    globals_format_sep: str = Form(""),
    globals_format_with_labels: bool = Form(True),
    ai_enable: bool = Form(False),
    ai_example_path: str = Form(""),
    ai_example_file: UploadFile = File(default=None),
    ai_detailed: bool = Form(True),
    rag_top_k: Optional[int] = Form(None),
    rag_categories: str = Form(""),
) -> Dict[str, Any]:
    source_root_path = Path(source_root).resolve() if source_root else None
    if not source_root_path or not source_root_path.exists() or not source_root_path.is_dir():
        raise HTTPException(status_code=400, detail="source_root(코드 루트)가 필요합니다.")
    job_id = uuid.uuid4().hex
    _set_progress(
        "uds",
        job_url,
        build_selector,
        {
            "stage": "start",
            "percent": 1,
            "message": "UDS 생성 준비 중",
            "done": False,
            "error": "",
        },
        job_id=job_id,
    )

    req_paths_list = _parse_path_list(req_paths)
    has_req_upload = any((f and f.filename) for f in (req_files or []))
    if not has_req_upload and not req_paths_list:
        raise HTTPException(status_code=400, detail="SRS/SDS 요구사항 문서를 최소 1개 이상 제공해주세요.")
    globals_order_list = [
        x.strip()
        for x in re.split(r"[,\|;]+", globals_format_order or "")
        if x.strip()
    ]
    req_file_paths: List[Path] = []
    logic_file_paths: List[Path] = []
    note_file_paths: List[Path] = []
    ai_example_text = ""
    component_map: Dict[str, Dict[str, str]] = {}

    for f in req_files:
        if not f or not f.filename:
            continue
        suffix = Path(f.filename).suffix.lower() or ".txt"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await f.read())
            req_file_paths.append(Path(tmp.name))

    for f in logic_files:
        if not f or not f.filename:
            continue
        suffix = Path(f.filename).suffix.lower() or ".png"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await f.read())
            logic_file_paths.append(Path(tmp.name))

    for f in files:
        if not f or not f.filename:
            continue
        suffix = Path(f.filename).suffix.lower() or ".txt"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await f.read())
            note_file_paths.append(Path(tmp.name))

    if component_list and component_list.filename:
        tmp = _write_upload_to_temp(component_list, ".json")
        if tmp:
            try:
                component_map = _parse_component_map_file(tmp)
            except Exception:
                component_map = {}
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass

    if ai_example_path:
        try:
            p = Path(ai_example_path).expanduser().resolve()
            if p.exists() and p.is_file():
                ai_example_text = _read_text_from_file(p)
        except Exception:
            ai_example_text = ""
    if ai_example_file and ai_example_file.filename:
        try:
            suffix = Path(ai_example_file.filename).suffix.lower() or ".txt"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(await ai_example_file.read())
                ai_example_text = _read_text_from_file(Path(tmp.name))
        except Exception:
            ai_example_text = ai_example_text or ""
    if ai_enable and not ai_example_text:
        for cand in [
            repo_root / "docs" / "UDSPDM01_UDS.txt",
            repo_root / "docs" / "HDPDM01_UDS.txt",
        ]:
            try:
                if cand.exists() and cand.is_file():
                    ai_example_text = _read_text_from_file(cand)
                    break
            except Exception:
                continue
    if ai_enable and not ai_example_text:
        try:
            ref_suds_path = Path(config.UDS_REF_SUDS_PATH)
            if ref_suds_path.exists() and ref_suds_path.is_file():
                ai_example_text = _read_text_from_file(ref_suds_path)
        except Exception:
            pass

    def _progress_cb(stage: str, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            data = {}
        _set_progress(
            "uds",
            job_url,
            build_selector,
            data,
            job_id=job_id,
        )

    def _worker() -> None:
        try:
            result = _uds_generate_from_paths(
                job_url=job_url,
                cache_root=cache_root,
                build_selector=build_selector,
                template_path=template_path,
                source_root=source_root,
                source_only=source_only,
                req_file_paths=req_file_paths,
                note_file_paths=note_file_paths,
                logic_file_paths=logic_file_paths,
                req_paths=req_paths_list,
                logic_source=logic_source,
                logic_max_children=logic_max_children,
                logic_max_grandchildren=logic_max_grandchildren,
                logic_max_depth=logic_max_depth,
                globals_format_order=",".join(globals_order_list),
                globals_format_sep=globals_format_sep,
                globals_format_with_labels=globals_format_with_labels,
                ai_enable=bool(ai_enable),
                ai_example_text=ai_example_text,
                ai_detailed=bool(ai_detailed),
                rag_top_k=_safe_int(rag_top_k, getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3))
                if rag_top_k is not None
                else None,
                rag_categories=_split_csv(rag_categories),
                progress_cb=_progress_cb,
                component_map=component_map if component_map else None,
            )
            _set_progress(
                "uds",
                job_url,
                build_selector,
                {
                    "stage": "done",
                    "percent": 100,
                    "message": "UDS 생성 완료",
                    "done": True,
                    "result": result,
                },
                job_id=job_id,
            )
        except Exception as exc:
            tb = traceback.format_exc()
            err_summary = str(exc)[:500]
            _logger.error("[UDS_ASYNC][%s] FAILED: %s\n%s", job_id, err_summary, tb)
            _set_progress(
                "uds",
                job_url,
                build_selector,
                {
                    "stage": "error",
                    "percent": 100,
                    "message": f"UDS 생성 실패: {err_summary}",
                    "done": True,
                    "error": err_summary,
                    "error_detail": tb,
                },
                job_id=job_id,
            )

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "job_id": job_id}


@router.get("/api/jenkins/uds/download")
def jenkins_uds_download(job_url: str, cache_root: str, filename: str) -> FileResponse:
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")
    out_dir = _jenkins_exports_dir(cache_root)
    target = (out_dir / filename).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(str(target), filename=target.name)


@router.get("/api/jenkins/uds/preview")
def jenkins_uds_preview(job_url: str, cache_root: str, filename: str) -> Dict[str, Any]:
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")
    out_dir = _jenkins_exports_dir(cache_root)
    try:
        target = safe_resolve_under(out_dir, filename)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid filename")
    if not target.exists():
        raise HTTPException(status_code=404, detail="file not found")
    try:
        text = target.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        text = ""
    if target.suffix.lower() == ".md":
        escaped = (
            "<pre>"
            + text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            + "</pre>"
        )
        return {"ok": True, "html": escaped}
    return {"ok": True, "html": text}


@router.get("/api/jenkins/uds/logic")
def jenkins_uds_logic(job_url: str, cache_root: str, filename: str) -> FileResponse:
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")
    logic_dir = _jenkins_logic_dir(cache_root)
    try:
        target = safe_resolve_under(logic_dir, filename)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid filename")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(str(target), filename=target.name)


@router.get("/api/jenkins/uds/list")
def jenkins_uds_list(job_url: str, cache_root: str) -> Dict[str, Any]:
    job_slug = _job_slug(job_url)
    out_dir = _jenkins_exports_dir(cache_root)
    if not out_dir.exists():
        return {"ok": True, "items": [], "placeholders": UDS_PLACEHOLDERS}
    meta = _load_uds_meta(out_dir, job_slug)
    labels = meta.get("labels") if isinstance(meta.get("labels"), dict) else {}
    items: List[Dict[str, Any]] = []
    for p in sorted(out_dir.glob(f"uds_spec_{job_slug}_*.docx"), reverse=True):
        try:
            stat = p.stat()
            preview_html = p.with_suffix(".html")
            preview_md = p.with_suffix(".md")
            preview = preview_html if preview_html.exists() else preview_md
            items.append(
                {
                    "filename": p.name,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "label": labels.get(p.name, ""),
                    "download_url": f"/api/jenkins/uds/download?job_url={job_url}&cache_root={cache_root}&filename={p.name}",
                    "preview_url": f"/api/jenkins/uds/preview?job_url={job_url}&cache_root={cache_root}&filename={preview.name}"
                    if preview.exists()
                    else "",
                }
            )
        except Exception:
            continue
    return {"ok": True, "items": items, "placeholders": UDS_PLACEHOLDERS}


@router.get("/api/jenkins/uds/view")
def jenkins_uds_view(
    job_url: str,
    cache_root: str,
    filename: str,
    q: str = Query(default=""),
    swcom: str = Query(default="all"),
    asil: str = Query(default="all"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    trace_q: str = Query(default=""),
    trace_page: int = Query(default=1, ge=1),
    trace_page_size: int = Query(default=100, ge=1, le=500),
) -> Dict[str, Any]:
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")
    if Path(filename).suffix.lower() != ".docx":
        raise HTTPException(status_code=400, detail="filename must be .docx")
    out_dir = _jenkins_exports_dir(cache_root)
    try:
        docx_path = safe_resolve_under(out_dir, filename)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid filename")
    if not docx_path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    accuracy_path = docx_path.with_suffix(".accuracy.md")
    quality_gate_path = docx_path.with_suffix(".quality_gate.md")
    payload = _get_uds_view_payload_cached(
        docx_path,
        accuracy_path if accuracy_path.exists() else None,
        quality_gate_path if quality_gate_path.exists() else None,
    )
    payload = _apply_uds_view_filters(
        payload,
        q=q,
        swcom=swcom,
        asil=asil,
        page=page,
        page_size=page_size,
        trace_q=trace_q,
        trace_page=trace_page,
        trace_page_size=trace_page_size,
    )
    payload["download_url"] = (
        f"/api/jenkins/uds/download?job_url={job_url}&cache_root={cache_root}&filename={docx_path.name}"
    )
    preview_candidate = docx_path.with_suffix(".html")
    if not preview_candidate.exists():
        preview_candidate = docx_path.with_suffix(".md")
    payload["preview_url"] = (
        f"/api/jenkins/uds/preview?job_url={job_url}&cache_root={cache_root}&filename={preview_candidate.name}"
        if preview_candidate.exists()
        else ""
    )
    payload["accuracy_path"] = str(accuracy_path) if accuracy_path.exists() else ""
    payload["quality_gate_path"] = str(quality_gate_path) if quality_gate_path.exists() else ""
    residual_tbd_path = docx_path.with_suffix(".residual_tbd.md")
    payload["residual_tbd_report_path"] = str(residual_tbd_path) if residual_tbd_path.exists() else ""
    return payload


def _parse_excel_preview(file_path: Path, max_rows: int = 30) -> Dict[str, Any]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl not installed")
    wb = load_workbook(str(file_path), read_only=True, data_only=True, keep_vba=False)
    sheets: List[Dict[str, Any]] = []
    for sname in wb.sheetnames:
        ws = wb[sname]
        mr = ws.max_row or 0
        mc = ws.max_column or 0
        headers: List[str] = []
        rows: List[List[Any]] = []
        if mr and mc:
            col_limit = min(mc, 20)
            for c in range(1, col_limit + 1):
                val = ws.cell(row=1, column=c).value
                headers.append(str(val) if val is not None else f"Col{c}")
            for r in range(1, min(mr + 1, 1 + max_rows)):
                row_data: List[Any] = []
                for c in range(1, col_limit + 1):
                    cell_val = ws.cell(row=r, column=c).value
                    if cell_val is None:
                        row_data.append("")
                    else:
                        row_data.append(cell_val if isinstance(cell_val, (int, float)) else str(cell_val).strip()[:200])
                if any(v != "" for v in row_data):
                    rows.append(row_data)
        sheets.append({"name": sname, "headers": headers, "rows": rows, "total_rows": mr, "total_cols": mc})
    names = list(wb.sheetnames)
    wb.close()
    return {"filename": file_path.name, "sheets": sheets, "sheet_names": names}


def _build_sts_function_details(source_root_path: Path, req_doc_paths: List[str], sds_doc_paths: List[str]) -> Dict[str, Any]:
    sections = generate_uds_source_sections(str(source_root_path))
    details = sections.get("function_details", {}) if isinstance(sections, dict) else {}
    if isinstance(details, dict):
        enrich_function_details_with_docs(
            details,
            sections.get("function_table_rows", []) if isinstance(sections, dict) else [],
            req_doc_paths=req_doc_paths,
            sds_doc_paths=sds_doc_paths,
        )
    return details if isinstance(details, dict) else {}


@router.post("/api/jenkins/sts/generate-async")
async def jenkins_sts_generate_async(
    job_url: str = Form(...),
    cache_root: str = Form(""),
    build_selector: str = Form("lastSuccessfulBuild"),
    source_root: str = Form(""),
    srs_path: str = Form(""),
    sds_path: str = Form(""),
    uds_path: str = Form(""),
    stp_path: str = Form(""),
    req_paths: str = Form(""),
    req_files: List[UploadFile] = File(default_factory=list),
    template_path: str = Form(""),
    project_id: str = Form(""),
    version: str = Form("v1.00"),
    asil_level: str = Form(""),
    max_tc_per_req: int = Form(5),
) -> Dict[str, Any]:
    from sts_generator import generate_sts

    source_root_path = Path(source_root).resolve() if source_root else None
    if not source_root_path or not source_root_path.exists() or not source_root_path.is_dir():
        raise HTTPException(status_code=400, detail="source_root is required")
    job_id = uuid.uuid4().hex
    req_paths_list = _parse_path_list(req_paths)
    req_texts: List[str] = []
    req_doc_paths: List[str] = []
    sds_doc_paths: List[str] = []
    srs_docx_path: Optional[str] = ""
    if srs_path:
        p = Path(srs_path).expanduser().resolve()
        if p.exists() and p.is_file():
            srs_docx_path = str(p)
    for path_str in req_paths_list:
        try:
            p = Path(path_str).expanduser().resolve()
            if not p.exists() or not p.is_file():
                continue
            text = _read_text_from_file(p)
            if text:
                req_texts.append(text.strip())
                if p.suffix.lower() == ".docx":
                    req_doc_paths.append(str(p))
                if "sds" in p.name.lower():
                    sds_doc_paths.append(str(p))
                if not srs_docx_path and "srs" in p.name.lower() and p.suffix.lower() == ".docx":
                    srs_docx_path = str(p)
        except Exception:
            continue
    for f in (req_files or []):
        if not f or not f.filename:
            continue
        suffix = Path(f.filename).suffix.lower() or ".txt"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await f.read())
            tmp_path = Path(tmp.name)
        try:
            text = _read_text_from_file(tmp_path)
            if text:
                req_texts.append(text.strip())
                if tmp_path.suffix.lower() == ".docx":
                    req_doc_paths.append(str(tmp_path))
                if "sds" in f.filename.lower():
                    sds_doc_paths.append(str(tmp_path))
                if not srs_docx_path and "srs" in f.filename.lower() and suffix == ".docx":
                    srs_docx_path = str(tmp_path)
        except Exception:
            continue
    if not req_texts and not srs_docx_path:
        raise HTTPException(status_code=400, detail="SRS document is required")
    def _resolve_opt_j(val: str) -> Optional[str]:
        if not val:
            return None
        p2 = Path(val).expanduser().resolve()
        return str(p2) if p2.exists() and p2.is_file() else None

    sds_docx_path = _resolve_opt_j(sds_path)
    uds_file_path = _resolve_opt_j(uds_path)
    stp_docx_path = _resolve_opt_j(stp_path)

    tpl_path: Optional[str] = None
    if template_path:
        p = Path(template_path).expanduser().resolve()
        if p.exists() and p.is_file():
            tpl_path = str(p)
    out_filename, out_path = _build_jenkins_excel_output(cache_root, "sts", f"sts_{_job_slug(job_url)}", tpl_path)
    project_config = {
        "project_id": project_id or "PROJECT",
        "doc_id": f"{project_id or 'PROJECT'}_STS",
        "version": version,
        "asil_level": asil_level,
        "max_tc_per_req": max_tc_per_req,
        "default_test_env": "SwTE_01",
    }
    _set_progress("jenkins_sts", job_url, build_selector, {"stage": "start", "percent": 1, "message": "STS start", "done": False, "error": ""}, job_id=job_id)

    def _on_progress(pct: int, msg: str):
        _set_progress("jenkins_sts", job_url, build_selector, {"stage": "generation", "percent": max(10, min(pct, 95)), "message": msg}, job_id=job_id)

    def _worker() -> None:
        try:
            _set_progress("jenkins_sts", job_url, build_selector, {"stage": "source_analysis", "percent": 5, "message": "Analyzing source"}, job_id=job_id)
            function_details = _build_sts_function_details(source_root_path, req_doc_paths, sds_doc_paths)
            result = generate_sts(
                requirements_text=req_texts,
                function_details=function_details,
                output_path=str(out_path),
                template_path=tpl_path,
                project_config=project_config,
                srs_docx_path=srs_docx_path,
                sds_docx_path=sds_docx_path,
                uds_path=uds_file_path,
                stp_path=stp_docx_path,
                on_progress=_on_progress,
            )
            download_url = f"/api/jenkins/sts/download?job_url={job_url}&cache_root={cache_root}&filename={out_filename}"
            preview_url = f"/api/jenkins/sts/preview?job_url={job_url}&cache_root={cache_root}&filename={out_filename}"
            payload = _build_excel_artifact_payload(
                "sts",
                {
                    "ok": True,
                    "output_path": str(out_path),
                    "filename": out_filename,
                    "download_url": download_url,
                    "test_case_count": result.get("test_case_count", 0),
                    "elapsed_seconds": result.get("elapsed_seconds", 0),
                    "quality_report": result.get("quality_report", {}),
                    "trace_coverage": result.get("trace_coverage", {}),
                    "validation": result.get("validation", {}),
                    "validation_report_path": result.get("validation_report_path", ""),
                    "build_label": _build_label(job_url, cache_root, build_selector),
                },
                output_path=str(out_path),
                filename=out_filename,
                download_url=download_url,
                preview_url=preview_url,
            )
            _write_excel_artifact_sidecar(out_path, "sts", payload)
            _set_progress("jenkins_sts", job_url, build_selector, {"stage": "done", "percent": 100, "message": "STS complete", "done": True, "error": "", "result": payload}, job_id=job_id)
        except Exception as exc:
            _set_progress("jenkins_sts", job_url, build_selector, {"stage": "error", "percent": 100, "message": str(exc)[:300], "done": True, "error": str(exc)[:500]}, job_id=job_id)

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "job_id": job_id}


@router.get("/api/jenkins/sts/progress")
def jenkins_sts_progress(job_url: str, build_selector: str = "lastSuccessfulBuild", job_id: str = "") -> Dict[str, Any]:
    data = _get_progress("jenkins_sts", job_url, build_selector, job_id)
    return {"ok": bool(data), "progress": data}


@router.get("/api/jenkins/sts/download")
def jenkins_sts_download(job_url: str, cache_root: str, filename: str) -> FileResponse:
    target = (_jenkins_sts_dir(cache_root) / filename).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail="STS file not found")
    return FileResponse(str(target), filename=target.name, media_type=_excel_media_type(target))


@router.get("/api/jenkins/sts/list")
def jenkins_sts_list(job_url: str, cache_root: str) -> Dict[str, Any]:
    out_dir = _jenkins_sts_dir(cache_root)
    if not out_dir.exists():
        return {"ok": True, "items": []}
    items: List[Dict[str, Any]] = []
    for p in sorted(out_dir.glob("*.xls*"), reverse=True):
        payload = _load_excel_artifact_payload(
            p,
            "sts",
            download_url=f"/api/jenkins/sts/download?job_url={job_url}&cache_root={cache_root}&filename={p.name}",
            preview_url=f"/api/jenkins/sts/preview?job_url={job_url}&cache_root={cache_root}&filename={p.name}",
            build_label=_infer_build_label_for_artifact(job_url, cache_root, p, "lastSuccessfulBuild"),
        )
        items.append({
            "filename": p.name,
            "size": p.stat().st_size,
            "mtime": p.stat().st_mtime,
            "download_url": f"/api/jenkins/sts/download?job_url={job_url}&cache_root={cache_root}&filename={p.name}",
            "preview_url": f"/api/jenkins/sts/preview?job_url={job_url}&cache_root={cache_root}&filename={p.name}",
            "validation_report_path": payload.get("validation_report_path", ""),
            "residual_report_path": payload.get("residual_report_path", ""),
            "summary": payload.get("summary", {}),
        })
    return {"ok": True, "items": items}


@router.get("/api/jenkins/sts/preview")
def jenkins_sts_preview(job_url: str, cache_root: str, filename: str, max_rows: int = 30) -> Dict[str, Any]:
    target = (_jenkins_sts_dir(cache_root) / filename).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail="STS file not found")
    return _parse_excel_preview(target, max_rows)


@router.get("/api/jenkins/sts/view")
def jenkins_sts_view(job_url: str, cache_root: str, filename: str) -> Dict[str, Any]:
    target = (_jenkins_sts_dir(cache_root) / filename).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail="STS file not found")
    return _load_excel_artifact_payload(
        target,
        "sts",
        download_url=f"/api/jenkins/sts/download?job_url={job_url}&cache_root={cache_root}&filename={target.name}",
        preview_url=f"/api/jenkins/sts/preview?job_url={job_url}&cache_root={cache_root}&filename={target.name}",
        build_label=_infer_build_label_for_artifact(job_url, cache_root, target, "lastSuccessfulBuild"),
    )


@router.post("/api/jenkins/suts/generate-async")
async def jenkins_suts_generate_async(
    job_url: str = Form(...),
    cache_root: str = Form(""),
    build_selector: str = Form("lastSuccessfulBuild"),
    source_root: str = Form(""),
    template_path: str = Form(""),
    project_id: str = Form(""),
    version: str = Form("v1.00"),
    asil_level: str = Form(""),
    max_sequences: int = Form(6),
) -> Dict[str, Any]:
    from suts_generator import generate_suts

    source_root_path = Path(source_root).resolve() if source_root else None
    if not source_root_path or not source_root_path.exists() or not source_root_path.is_dir():
        raise HTTPException(status_code=400, detail="source_root is required")
    tpl_path: Optional[str] = None
    if template_path:
        p = Path(template_path).expanduser().resolve()
        if p.exists() and p.is_file():
            tpl_path = str(p)
    out_filename, out_path = _build_jenkins_excel_output(cache_root, "suts", f"suts_{_job_slug(job_url)}", tpl_path)
    project_config = {
        "project_id": project_id or "PROJECT",
        "doc_id": f"{project_id or 'PROJECT'}-SUTS",
        "version": version,
        "asil_level": asil_level,
    }
    job_id = uuid.uuid4().hex
    _set_progress("jenkins_suts", job_url, build_selector, {"stage": "start", "percent": 1, "message": "SUTS start", "done": False, "error": ""}, job_id=job_id)

    def _on_progress(pct: int, msg: str):
        _set_progress("jenkins_suts", job_url, build_selector, {"stage": "generation", "percent": max(10, min(pct, 95)), "message": msg}, job_id=job_id)

    def _worker() -> None:
        try:
            _set_progress("jenkins_suts", job_url, build_selector, {"stage": "source_analysis", "percent": 5, "message": "Analyzing source"}, job_id=job_id)
            result = generate_suts(
                source_root=str(source_root_path),
                output_path=str(out_path),
                template_path=tpl_path,
                project_config=project_config,
                max_sequences=max_sequences,
                on_progress=_on_progress,
            )
            download_url = f"/api/jenkins/suts/download?job_url={job_url}&cache_root={cache_root}&filename={out_filename}"
            preview_url = f"/api/jenkins/suts/preview?job_url={job_url}&cache_root={cache_root}&filename={out_filename}"
            payload = _build_excel_artifact_payload(
                "suts",
                {
                    "ok": True,
                    "output_path": str(out_path),
                    "filename": out_filename,
                    "download_url": download_url,
                    "test_case_count": result.get("test_case_count", 0),
                    "total_sequences": result.get("total_sequences", 0),
                    "elapsed_seconds": result.get("elapsed_seconds", 0),
                    "quality_report": result.get("quality_report", {}),
                    "validation": result.get("validation", {}),
                    "validation_report_path": result.get("validation_report_path", ""),
                    "build_label": _build_label(job_url, cache_root, build_selector),
                },
                output_path=str(out_path),
                filename=out_filename,
                download_url=download_url,
                preview_url=preview_url,
            )
            _write_excel_artifact_sidecar(out_path, "suts", payload)
            _set_progress("jenkins_suts", job_url, build_selector, {"stage": "done", "percent": 100, "message": "SUTS complete", "done": True, "error": "", "result": payload}, job_id=job_id)
        except Exception as exc:
            _set_progress("jenkins_suts", job_url, build_selector, {"stage": "error", "percent": 100, "message": str(exc)[:300], "done": True, "error": str(exc)[:500]}, job_id=job_id)

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "job_id": job_id}


@router.get("/api/jenkins/suts/progress")
def jenkins_suts_progress(job_url: str, build_selector: str = "lastSuccessfulBuild", job_id: str = "") -> Dict[str, Any]:
    data = _get_progress("jenkins_suts", job_url, build_selector, job_id)
    return {"ok": bool(data), "progress": data}


@router.get("/api/jenkins/suts/download")
def jenkins_suts_download(job_url: str, cache_root: str, filename: str) -> FileResponse:
    target = (_jenkins_suts_dir(cache_root) / filename).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail="SUTS file not found")
    return FileResponse(str(target), filename=target.name, media_type=_excel_media_type(target))


@router.get("/api/jenkins/suts/list")
def jenkins_suts_list(job_url: str, cache_root: str) -> Dict[str, Any]:
    out_dir = _jenkins_suts_dir(cache_root)
    if not out_dir.exists():
        return {"ok": True, "items": []}
    items: List[Dict[str, Any]] = []
    for p in sorted(out_dir.glob("*.xls*"), reverse=True):
        payload = _load_excel_artifact_payload(
            p,
            "suts",
            download_url=f"/api/jenkins/suts/download?job_url={job_url}&cache_root={cache_root}&filename={p.name}",
            preview_url=f"/api/jenkins/suts/preview?job_url={job_url}&cache_root={cache_root}&filename={p.name}",
            build_label=_infer_build_label_for_artifact(job_url, cache_root, p, "lastSuccessfulBuild"),
        )
        items.append({
            "filename": p.name,
            "size": p.stat().st_size,
            "mtime": p.stat().st_mtime,
            "download_url": f"/api/jenkins/suts/download?job_url={job_url}&cache_root={cache_root}&filename={p.name}",
            "preview_url": f"/api/jenkins/suts/preview?job_url={job_url}&cache_root={cache_root}&filename={p.name}",
            "validation_report_path": payload.get("validation_report_path", ""),
            "residual_report_path": payload.get("residual_report_path", ""),
            "summary": payload.get("summary", {}),
        })
    return {"ok": True, "items": items}


@router.get("/api/jenkins/suts/preview")
def jenkins_suts_preview(job_url: str, cache_root: str, filename: str, max_rows: int = 30) -> Dict[str, Any]:
    target = (_jenkins_suts_dir(cache_root) / filename).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail="SUTS file not found")
    return _parse_excel_preview(target, max_rows)


@router.get("/api/jenkins/suts/view")
def jenkins_suts_view(job_url: str, cache_root: str, filename: str) -> Dict[str, Any]:
    target = (_jenkins_suts_dir(cache_root) / filename).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail="SUTS file not found")
    return _load_excel_artifact_payload(
        target,
        "suts",
        download_url=f"/api/jenkins/suts/download?job_url={job_url}&cache_root={cache_root}&filename={target.name}",
        preview_url=f"/api/jenkins/suts/preview?job_url={job_url}&cache_root={cache_root}&filename={target.name}",
        build_label=_infer_build_label_for_artifact(job_url, cache_root, target, "lastSuccessfulBuild"),
    )


@router.post("/api/jenkins/suts/export-vectorcast")
def jenkins_suts_export_vectorcast(
    job_url: str = Form(...),
    cache_root: str = Form(""),
    build_selector: str = Form("lastSuccessfulBuild"),
    filename: str = Form(""),
    source_root: str = Form(""),
    project_id: str = Form(""),
    compiler: str = Form("CC"),
) -> Dict[str, Any]:
    """Generate a VectorCAST unit-test package from a Jenkins SUTS artifact."""
    from tools.export_suts_vectorcast import export_suts_to_vectorcast_model
    from tools.export_vectorcast_script import export_vectorcast_package

    out_dir = _jenkins_suts_dir(cache_root)
    if filename:
        xlsm_path = (out_dir / filename).resolve()
    else:
        candidates = sorted(out_dir.glob("*.xlsm"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise HTTPException(status_code=404, detail="No Jenkins SUTS file found")
        xlsm_path = candidates[0].resolve()
    if not xlsm_path.exists():
        raise HTTPException(status_code=404, detail="SUTS file not found")

    resolved_source_root = str(source_root or "").strip()
    cfg = load_vectorcast_project_config(project_id=project_id, source_root=resolved_source_root)
    effective_project_id = str(project_id or cfg.get("project_id") or "VECTORCAST").strip()
    effective_source_root = resolved_source_root or str(cfg.get("source_root") or "").strip()

    package_name = f"suts_vectorcast_{_job_slug(job_url)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    package_dir = _jenkins_exports_dir(cache_root) / "vectorcast" / package_name
    package_dir.mkdir(parents=True, exist_ok=True)
    intermediate_json = package_dir / "suts_vectorcast_model.json"
    warnings_md = package_dir / "suts_vectorcast_warnings.md"

    try:
        model = export_suts_to_vectorcast_model(
            str(xlsm_path),
            str(intermediate_json),
            warnings_md=str(warnings_md),
            project_id=effective_project_id,
        )
        manifest = export_vectorcast_package(
            str(intermediate_json),
            str(package_dir),
            package_name=package_name,
            source_root=effective_source_root,
            compiler=str(cfg.get("compiler") or compiler or "CC"),
            project_config=cfg,
        )
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"VectorCAST package generation failed: {exc}")

    unit_names = [str(unit.get("unit_name") or "") for unit in model.get("units") or []]
    return _build_jenkins_vectorcast_response(
        job_url=job_url,
        cache_root=cache_root,
        build_selector=build_selector,
        package_dir=package_dir,
        package_name=package_name,
        manifest=manifest,
        project_config=cfg,
        units=unit_names,
    )


@router.post("/api/jenkins/uds/requirements-preview")
async def jenkins_uds_requirements_preview(
    req_files: List[UploadFile] = File(default_factory=list),
    req_paths: str = Form(""),
    source_root: str = Form(""),
) -> Dict[str, Any]:
    req_texts: List[str] = []
    for f in req_files:
        if not f or not f.filename:
            continue
        suffix = Path(f.filename).suffix.lower() or ".txt"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await f.read())
            tmp_path = Path(tmp.name)
        try:
            text = _read_text_from_file(tmp_path)
        except Exception:
            text = ""
        if text:
            req_texts.append(text.strip())
    for path_str in _parse_path_list(req_paths):
        try:
            p = Path(path_str).expanduser().resolve()
            if not p.exists() or not p.is_file():
                continue
            if not _is_allowed_req_doc(p):
                continue
            text = _read_text_from_file(p)
        except Exception:
            text = ""
        if text:
            req_texts.append(text.strip())
    preview = generate_uds_requirements_preview(req_texts)
    mapping = generate_uds_requirements_mapping(preview.get("items") or [])
    compare = None
    function_mapping = None
    if source_root:
        try:
            compare = generate_uds_requirements_compare(preview.get("items") or [], source_root)
        except Exception:
            compare = None
        try:
            function_mapping = generate_uds_function_mapping(req_texts, source_root)
        except Exception:
            function_mapping = None
    return {
        "ok": True,
        "preview": preview,
        "mapping": mapping,
        "compare": compare,
        "function_mapping": function_mapping,
    }


@router.post("/api/jenkins/uds/diff")
def jenkins_uds_diff(req: UdsDiffRequest) -> Dict[str, Any]:
    out_dir = _jenkins_exports_dir(req.cache_root)
    try:
        a_path = safe_resolve_under(out_dir, req.filename_a)
        b_path = safe_resolve_under(out_dir, req.filename_b)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid filename")
    if a_path.suffix.lower() == ".docx":
        html = a_path.with_suffix(".html")
        if html.exists():
            a_path = html
    if b_path.suffix.lower() == ".docx":
        html = b_path.with_suffix(".html")
        if html.exists():
            b_path = html
    if not a_path.exists() or not b_path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    a_html = a_path.read_text(encoding="utf-8", errors="ignore")
    b_html = b_path.read_text(encoding="utf-8", errors="ignore")
    a_sections = parse_uds_preview_html(a_html)
    b_sections = parse_uds_preview_html(b_html)
    diff: Dict[str, Any] = {}
    for key in sorted(set(a_sections.keys()) | set(b_sections.keys())):
        a_items = a_sections.get(key, [])
        b_items = b_sections.get(key, [])
        added = [x for x in b_items if x not in a_items]
        removed = [x for x in a_items if x not in b_items]
        diff[key] = {"added": added, "removed": removed}
    return {"ok": True, "diff": diff}


@router.post("/api/jenkins/uds/traceability-matrix")
def jenkins_uds_traceability_matrix(req: UdsTraceabilityMatrixRequest) -> Dict[str, Any]:
    try:
        matrix = generate_uds_traceability_matrix(
            req.requirement_items or [],
            mapping_pairs=req.mapping_pairs or [],
            vcast_rows=req.vcast_rows or [],
        )
        return {"ok": True, "matrix": matrix}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/jenkins/uds/publish")
def jenkins_uds_publish(req: UdsPublishRequest) -> Dict[str, Any]:
    out_dir = _jenkins_exports_dir(req.cache_root)
    try:
        target = safe_resolve_under(out_dir, req.filename)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid filename")
    if not target.exists():
        raise HTTPException(status_code=404, detail="file not found")
    docs_dir = (repo_root / req.target_dir).resolve()
    docs_dir.mkdir(parents=True, exist_ok=True)
    out_path = docs_dir / target.name
    out_path.write_bytes(target.read_bytes())
    return {"ok": True, "path": str(out_path)}


@router.post("/api/jenkins/uds/label")
def jenkins_uds_label(req: UdsLabelRequest) -> Dict[str, Any]:
    job_slug = _job_slug(req.job_url)
    out_dir = _jenkins_exports_dir(req.cache_root)
    if not out_dir.exists():
        raise HTTPException(status_code=404, detail="export dir not found")
    try:
        target = safe_resolve_under(out_dir, req.filename)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid filename")
    if not target.exists():
        raise HTTPException(status_code=404, detail="file not found")
    meta = _load_uds_meta(out_dir, job_slug)
    labels = meta.get("labels")
    if not isinstance(labels, dict):
        labels = {}
    label = (req.label or "").strip()
    if label:
        labels[req.filename] = label
    else:
        labels.pop(req.filename, None)
    meta["labels"] = labels
    _save_uds_meta(out_dir, job_slug, meta)
    return {"ok": True, "filename": req.filename, "label": label}


@router.post("/api/jenkins/uds/delete")
def jenkins_uds_delete(req: UdsDeleteRequest) -> Dict[str, Any]:
    job_slug = _job_slug(req.job_url)
    out_dir = _jenkins_exports_dir(req.cache_root)
    if not out_dir.exists():
        raise HTTPException(status_code=404, detail="export dir not found")
    try:
        target = safe_resolve_under(out_dir, req.filename)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid filename")
    if not target.exists():
        raise HTTPException(status_code=404, detail="file not found")
    removed: List[str] = []
    for candidate in [target, target.with_suffix(".html"), target.with_suffix(".md")]:
        if candidate.exists():
            try:
                candidate.unlink()
                removed.append(candidate.name)
            except Exception:
                continue
    meta = _load_uds_meta(out_dir, job_slug)
    labels = meta.get("labels")
    if isinstance(labels, dict):
        labels.pop(req.filename, None)
        meta["labels"] = labels
    _save_uds_meta(out_dir, job_slug, meta)
    return {"ok": True, "removed": removed}


@router.post("/api/jenkins/call-tree")
def jenkins_call_tree(req: JenkinsCallTreeRequest) -> Dict[str, Any]:
    build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    source_root = Path(req.source_root).resolve() if req.source_root else build_root
    entries = [x.strip() for x in str(req.entry or "").replace("\n", ",").split(",") if x.strip()]
    if not entries:
        raise HTTPException(status_code=400, detail="entry required")
    if not source_root.exists():
        raise HTTPException(status_code=404, detail="source_root not found")
    compile_db = Path(req.compile_commands_path).resolve() if req.compile_commands_path else None
    payload = build_call_tree(
        source_root,
        entries,
        include_paths=req.include_paths or [],
        exclude_paths=req.exclude_paths or [],
        max_depth=max(1, int(req.max_depth or 5)),
        max_files=max(1, int(req.max_files or 2000)),
        include_external=bool(req.include_external),
        compile_commands_path=compile_db,
        external_map=req.external_map or [],
    )
    payload["meta"] = {
        "job_url": req.job_url,
        "build_selector": req.build_selector,
        "build_root": str(build_root),
    }
    return payload


@router.post("/api/jenkins/call-tree/save")
def jenkins_call_tree_save(req: JenkinsCallTreeRequest) -> Dict[str, Any]:
    payload = jenkins_call_tree(req)
    out_dir = _jenkins_exports_dir(req.cache_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_slug = _job_slug(req.job_url)
    sel = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in str(req.build_selector))
    fmt = str(req.output_format or "json").strip().lower()
    if fmt not in ("json", "html", "csv"):
        raise HTTPException(status_code=400, detail="invalid output_format")
    if fmt == "html":
        out_path = out_dir / f"jenkins_call_tree_{job_slug}_{sel}_{ts}.html"
        out_path.write_text(call_tree_to_html(payload, req.html_template), encoding="utf-8")
    elif fmt == "csv":
        out_path = out_dir / f"jenkins_call_tree_{job_slug}_{sel}_{ts}.csv"
        out_path.write_text(call_tree_to_csv(payload), encoding="utf-8")
    else:
        out_path = out_dir / f"jenkins_call_tree_{job_slug}_{sel}_{ts}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"filename": out_path.name, "path": str(out_path), "format": fmt}


@router.post("/api/jenkins/call-tree/preview-html")
def jenkins_call_tree_preview(req: CallTreePreviewRequest) -> Dict[str, Any]:
    payload = req.call_tree or {}
    html = call_tree_to_html(payload, req.html_template)
    return {"html": html}


@router.get("/api/jenkins/call-tree/download")
def jenkins_call_tree_download(job_url: str, cache_root: str, filename: str) -> FileResponse:
    out_dir = _jenkins_exports_dir(cache_root)
    try:
        target = safe_resolve_under(out_dir, filename)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid filename")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    media = "application/json"
    if target.suffix.lower() == ".html":
        media = "text/html"
    elif target.suffix.lower() == ".csv":
        media = "text/csv"
    return FileResponse(str(target), filename=target.name, media_type=media)


@router.post("/api/jenkins/report/files")
def jenkins_report_files(req: JenkinsReportRequest) -> Dict[str, Any]:
    build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    # Jenkins 동기화된 빌드 루트 전체에서 파일 목록을 제공
    return list_report_files(build_root)


@router.post("/api/jenkins/server/files")
def jenkins_server_files(req: JenkinsServerFilesRequest) -> Dict[str, Any]:
    roots = getattr(config, "JENKINS_SERVER_ROOTS", [])
    allowed = [Path(p).expanduser().resolve() for p in roots if p]
    if not allowed:
        raise HTTPException(status_code=400, detail="jenkins server roots not configured")
    base = Path(req.root or "").expanduser().resolve()
    if not is_under_any(base, allowed) and base not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"server root not allowed: {base}",
        )
    rel = req.rel_path or "."
    try:
        scan_root = safe_resolve_under(base, rel)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail=f"invalid rel_path: {rel}",
        )
    if not scan_root.exists() or not scan_root.is_dir():
        raise HTTPException(status_code=404, detail=f"root not found: {scan_root}")

    exts = [e.lower().lstrip(".") for e in (req.exts or []) if str(e).strip()]
    if not exts:
        exts = [e.lower() for e in getattr(config, "JENKINS_SERVER_DOC_EXTS", [])]
    max_files = max(1, int(req.max_files or 5000))

    files = []
    scanned = 0
    for dirpath, _, filenames in os.walk(scan_root):
        for name in filenames:
            scanned += 1
            if scanned > max_files:
                return {
                    "ok": True,
                    "root": str(base),
                    "scan_root": str(scan_root),
                    "files": files,
                    "scanned": scanned,
                    "truncated": True,
                }
            p = Path(dirpath) / name
            ext = p.suffix.lower().lstrip(".")
            if exts and ext not in exts:
                continue
            try:
                rel_path = str(p.relative_to(base)).replace("\\", "/")
            except Exception:
                continue
            try:
                stat = p.stat()
                size = int(stat.st_size)
                mtime = int(stat.st_mtime)
            except Exception:
                size = 0
                mtime = 0
            files.append(
                {
                    "rel_path": rel_path,
                    "path": str(p),
                    "ext": ext,
                    "size": size,
                    "mtime": mtime,
                }
            )
    return {
        "ok": True,
        "root": str(base),
        "scan_root": str(scan_root),
        "files": files,
        "scanned": scanned,
        "truncated": False,
    }


@router.post("/api/jenkins/report/files/download")
def jenkins_report_files_download(req: JenkinsReportRequest, path: str) -> FileResponse:
    build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    try:
        target = safe_resolve_under(build_root, path)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(str(target), filename=target.name)


@router.post("/api/jenkins/report/files/download/zip")
def jenkins_report_files_download_zip(req: JenkinsReportZipRequest) -> FileResponse:
    build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    report_dir = build_root
    scope = str(req.scope or "all").strip().lower()
    if scope in ("report", "reports"):
        report_dir = _detect_reports_dir(build_root)
    out_dir = _jenkins_exports_dir(req.cache_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_slug = _job_slug(req.job_url)
    sel = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in str(req.build_selector))
    out_path = out_dir / f"jenkins_reports_{job_slug}_{sel}_{ts}.zip"
    _create_jenkins_zip_file(
        report_dir,
        out_path,
        include_paths=req.include_paths,
        exclude_paths=req.exclude_paths,
        exts=req.exts,
    )
    return FileResponse(out_path, filename=out_path.name, media_type="application/zip")


@router.post("/api/jenkins/report/files/download/zip/select")
def jenkins_report_files_download_zip_select(req: JenkinsReportRequest, sel: ReportZipRequest) -> FileResponse:
    build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    report_dir = build_root
    out_dir = _jenkins_exports_dir(req.cache_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_slug = _job_slug(req.job_url)
    sel_key = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in str(req.build_selector))
    out_path = out_dir / f"jenkins_reports_{job_slug}_{sel_key}_{ts}.zip"
    paths = sel.paths or []
    if not paths:
        raise HTTPException(status_code=400, detail="paths required")
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in paths:
            try:
                target = safe_resolve_under(report_dir, rel)
            except Exception:
                continue
            if target.exists() and target.is_file():
                zf.write(target, arcname=rel)
    return FileResponse(out_path, filename=out_path.name, media_type="application/zip")


@router.post("/api/jenkins/report/publish")
def jenkins_report_publish(req: JenkinsPublishRequest) -> Dict[str, Any]:
    return _jenkins_report_publish_impl(req)


@router.post("/api/jenkins/report/publish-async")
def jenkins_report_publish_async(req: JenkinsPublishRequest) -> Dict[str, Any]:
    job_url = req.job_url
    build_selector = req.build_selector
    job_id = uuid.uuid4().hex
    _set_progress(
        "publish",
        job_url,
        build_selector,
        {
            "stage": "start",
            "percent": 1,
            "message": "로컬 리포트 업로드 준비 중",
            "done": False,
            "error": "",
        },
        job_id=job_id,
    )

    def _run_publish() -> None:
        try:
            _jenkins_report_publish_impl(req, job_id=job_id)
        except Exception as exc:
            _set_progress(
                "publish",
                job_url,
                build_selector,
                {
                    "stage": "error",
                    "percent": 100,
                    "message": "로컬 리포트 업로드 실패",
                    "done": True,
                    "error": str(exc),
                },
                job_id=job_id,
            )
            return
        _set_progress(
            "publish",
            job_url,
            build_selector,
            {
                "stage": "done",
                "percent": 100,
                "message": "로컬 리포트 업로드 완료",
                "done": True,
            },
            job_id=job_id,
        )

    t = threading.Thread(target=_run_publish, daemon=True)
    t.start()
    return {"ok": True, "job_id": job_id}
