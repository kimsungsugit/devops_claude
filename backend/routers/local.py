"""Auto-generated router: local"""
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
    EditorReadAbsRequest,
    EditorReadRequest,
    EditorReplaceRequest,
    EditorWriteRequest,
    FormatCodeRequest,
    GitRequest,
    KBRequest,
    ListDirRequest,
    LocalImpactTriggerRequest,
    LocalReportGenerateRequest,
    OpenFileRequest,
    OpenFolderRequest,
    PickerRequest,
    PreflightRequest,
    RagIngestRequest,
    RagQueryRequest,
    RagStatusRequest,
    RagStorageRequest,
    ReplaceTextRequest,
    ScmRequest,
    SearchRequest,
    SdsViewRequest,
    TextPreviewRequest,
)
from datetime import datetime
from backend.helpers import _apply_uds_view_filters, _augment_path, _build_excel_artifact_payload, _build_excel_artifact_summary, _build_preflight, _build_quality_evaluation, _collect_tool_paths, _compute_quick_quality_gate, _compute_uds_mapping_summary, _enrich_function_quality_fields, _generate_docx_with_retry, _get_progress, _get_source_sections_cached, _get_uds_view_payload_cached, _is_allowed_req_doc, _local_reports_dir, _local_sits_dir, _local_sts_dir, _local_suts_dir, _local_uds_dir, _open_local_path, _parse_component_map_file, _parse_path_list, _read_excel_artifact_sidecar, _resolve_local_report_path, _resolve_local_sits_path, _resolve_local_sts_path, _resolve_local_suts_path, _resolve_local_uds_path, _resolve_report_dir, _resolve_source_root_from_cfg, _run_impact_analysis_for_uds, _run_report_with_timeout, _set_progress, _validate_docx_template_bytes, _write_excel_artifact_sidecar, _write_residual_tbd_report, _write_upload_to_temp, build_vectorcast_metadata, evaluate_vectorcast_readiness, load_vectorcast_project_config
from report_generator import (
    _build_req_map_from_doc_paths,
    enrich_function_details_with_docs,
    generate_uds_source_sections,
    generate_uds_requirements_from_docs,
    generate_uds_validation_report,
    generate_uds_field_quality_gate_report,
    generate_uds_constraints_report,
    generate_uds_preview_html,
    generate_called_calling_accuracy_report,
    generate_swcom_context_report,
    generate_swcom_context_diff_report,
    generate_asil_related_confidence_report,
)
import config
from backend.services.local_service import (
    delete_kb_entry,
    format_c_code,
    git_branches,
    git_checkout,
    git_commit,
    git_create_branch,
    git_diff,
    git_log,
    git_stage,
    git_status,
    git_unstage,
    list_kb_entries,
    list_directory,
    pick_directory,
    pick_file,
    read_file_text,
    replace_in_file,
    replace_lines,
    run_git,
    run_svn,
    svn_info_url,
    search_in_files,
    write_file_text,
)
from backend.helpers.sds import build_sds_view_model
from workflow.change_trigger import build_registry_trigger
from workflow.impact_orchestrator import run_impact_update
from workflow.impact_jobs import start_impact_job
from backend.services.local_report_generator import generate_local_docx, generate_local_xlsx
from backend.services.files import read_text_limited
from backend.services.paths import is_under_any
try:
    from workflow.rag import _read_text_from_file, _read_and_chunk_file, get_kb, ingest_external_sources
except ImportError:
    _read_text_from_file = None
    _read_and_chunk_file = None
    get_kb = None
    ingest_external_sources = None
try:
    from workflow.uds_ai import generate_uds_ai_sections
except ImportError:
    generate_uds_ai_sections = None

repo_root = Path(__file__).resolve().parents[2]


router = APIRouter()
_logger = logging.getLogger("devops_api")
_api_logger = logging.getLogger("devops_api")

_MAX_PREVIEW_COLS = 20


def _pick_excel_suffix(template_path: Optional[str]) -> str:
    if template_path:
        suffix = Path(template_path).suffix.lower()
        if suffix in (".xlsm", ".xlsx"):
            return suffix
    return ".xlsx"


def _build_vectorcast_package_response(
    *,
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
        "package_dir": str(package_dir),
        "package_name": package_name,
        "manifest": manifest,
        "files": sorted(str(p.name) for p in package_dir.iterdir() if p.is_file()),
        "project_config": metadata,
        "readiness": readiness,
    }


def _build_local_excel_output(base_dir: Path, category: str, stem: str, template_path: Optional[str]) -> Tuple[str, Path]:
    if category == "sts":
        target_dir = _local_sts_dir(base_dir)
    elif category == "sits":
        target_dir = _local_sits_dir(base_dir)
    else:
        target_dir = _local_suts_dir(base_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = _pick_excel_suffix(template_path)
    filename = f"{stem}_{ts}{suffix}"
    return filename, target_dir / filename


def _excel_media_type(file_path: Path) -> str:
    if file_path.suffix.lower() == ".xlsm":
        return "application/vnd.ms-excel.sheet.macroEnabled.12"
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
        _logger.warning("uds payload sidecar write skipped: %s", exc)
        return None


def _discover_default_req_docs() -> Dict[str, List[str]]:
    docs_dir = repo_root / "docs"
    result: Dict[str, List[str]] = {"req": [], "sds": []}
    if not docs_dir.exists():
        return result
    for path in docs_dir.glob("*.docx"):
        lower = path.name.lower()
        if "srs" in lower or "sds" in lower:
            result["req"].append(str(path))
        if "sds" in lower:
            result["sds"].append(str(path))
    return result


def _dedupe_paths(paths: Optional[List[str]]) -> List[str]:
    items: List[str] = []
    seen = set()
    for raw in paths or []:
        try:
            p = str(raw or "").strip()
        except Exception:
            p = ""
        if not p or p in seen:
            continue
        seen.add(p)
        items.append(p)
    return items


def _resolve_req_doc_sets(
    req_doc_paths: Optional[List[str]] = None,
    sds_doc_paths: Optional[List[str]] = None,
) -> Tuple[List[str], List[str]]:
    defaults = _discover_default_req_docs()
    req_paths = _dedupe_paths(list(req_doc_paths or []) + list(defaults.get("req") or []))
    sds_paths = _dedupe_paths(list(sds_doc_paths or []) + list(defaults.get("sds") or []))
    return req_paths, sds_paths


def _load_sts_ai_config() -> Optional[Dict[str, Any]]:
    """Load AI config for STS enhancement from default OAI config path."""
    try:
        import config as _appconfig
        from workflow.ai import load_oai_config
        cfg_path = getattr(_appconfig, "DEFAULT_OAI_CONFIG_PATH", None)
        cfg = load_oai_config(cfg_path)
        if cfg and isinstance(cfg, dict) and cfg.get("model"):
            return cfg
    except Exception as _e:
        _logger.debug("STS ai_config load skipped: %s", _e)
    return None


def _discover_hsis_path() -> Optional[str]:
    """Auto-discover HSIS xlsx file from docs/ directory."""
    try:
        docs_dir = Path(__file__).resolve().parents[2] / "docs"
        for p in docs_dir.glob("*.xlsx"):
            if "hsis" in p.name.lower():
                return str(p)
    except Exception:
        pass
    return None


def _enrich_function_details_map(
    function_details: Optional[Dict[str, Any]],
    *,
    function_table_rows: Optional[List[List[Any]]] = None,
    req_doc_paths: Optional[List[str]] = None,
    sds_doc_paths: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    details = function_details if isinstance(function_details, dict) else {}
    req_paths, sds_paths = _resolve_req_doc_sets(req_doc_paths, sds_doc_paths)
    if details:
        try:
            enrich_function_details_with_docs(
                details,
                function_table_rows,
                req_doc_paths=req_paths,
                sds_doc_paths=sds_paths,
            )
        except Exception as exc:
            _logger.warning("function detail enrichment skipped: %s", exc)
    # HSIS enrichment: functions using HSIS signal variables get
    # description_source/related_source upgraded from "inference" to "hsis"
    _hsis_p = _discover_hsis_path()
    if _hsis_p and details:
        try:
            from generators.sts import _load_hsis_signals
            _hsis_d = _load_hsis_signals(_hsis_p)
            _hsis_sigs = _hsis_d.get("signals", [])
            if _hsis_sigs:
                _hvar: Dict[str, Dict] = {}
                for _s in _hsis_sigs:
                    _sw = str(_s.get("sw_var_name") or "")
                    for _tok in re.split(r"[\n,\s]+", _sw):
                        _tok = _tok.strip()
                        if _tok and re.match(r"^[A-Za-z_]\w+$", _tok):
                            _hvar[_tok] = _s
                for _fn_info in details.values():
                    if not isinstance(_fn_info, dict):
                        continue
                    _fvars: set = set()
                    for _x in (_fn_info.get("inputs") or []):
                        _fvars.add(str(_x.get("name") or ""))
                    for _x in (_fn_info.get("outputs") or []):
                        _fvars.add(str(_x.get("name") or ""))
                    _fvars.update((_fn_info.get("globals_write") or {}).keys())
                    _fvars.update((_fn_info.get("globals_read") or {}).keys())
                    _matched_sigs = [_hvar[v] for v in _fvars if v in _hvar]
                    if not _matched_sigs:
                        continue
                    # Upgrade description_source from inference → hsis
                    if _fn_info.get("description_source", "inference") in {"inference", ""}:
                        _fn_info["description_source"] = "hsis"
                    # Set related if currently TBD/empty
                    _cur_rel = str(_fn_info.get("related") or "").strip()
                    if not _cur_rel or _cur_rel.upper() in {"TBD", "N/A", "-"}:
                        _rel_ids = [
                            str(s.get("related_id") or "").strip()
                            for s in _matched_sigs
                            if str(s.get("related_id") or "").strip()
                        ]
                        if _rel_ids:
                            _fn_info["related"] = _rel_ids[0]
                            _fn_info["related_source"] = "hsis"
        except Exception as _hsis_exc:
            _logger.warning("HSIS UDS enrichment skipped: %s", _hsis_exc)
    return details, req_paths, sds_paths


def _enrich_source_sections_with_docs(
    source_sections: Optional[Dict[str, Any]],
    *,
    req_doc_paths: Optional[List[str]] = None,
    sds_doc_paths: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    sections = source_sections if isinstance(source_sections, dict) else {}
    details = sections.get("function_details", {})
    table_rows = sections.get("function_table_rows", [])
    details, req_paths, sds_paths = _enrich_function_details_map(
        details,
        function_table_rows=table_rows if isinstance(table_rows, list) else None,
        req_doc_paths=req_doc_paths,
        sds_doc_paths=sds_doc_paths,
    )
    sections["function_details"] = details

    rebuilt_by_name: Dict[str, Any] = {}
    for _, info in details.items():
        if not isinstance(info, dict):
            continue
        name = str(info.get("name") or "").strip()
        if name:
            rebuilt_by_name[name] = info
    sections["function_details_by_name"] = rebuilt_by_name
    return sections, req_paths, sds_paths


def _find_latest_excel_file(directory: Path) -> Optional[Path]:
    files = [
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in (".xlsm", ".xlsx")
    ]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _parse_xlsm_preview(file_path: Path, max_rows: int = 30) -> Dict[str, Any]:
    """Parse XLSM/XLSX and return sheet data as JSON for web preview."""
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl not installed")

    try:
        wb = load_workbook(str(file_path), read_only=True, data_only=True, keep_vba=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot open XLSM: {e}")

    # Safety cap: full-viewer sends large max_rows but we cap to avoid timeout
    effective_max_rows = min(max_rows, 5000)

    sheets: List[Dict[str, Any]] = []
    for sname in wb.sheetnames:
        ws = wb[sname]
        mr = ws.max_row or 0
        mc = ws.max_column or 0
        if mr == 0 or mc == 0:
            sheets.append({"name": sname, "headers": [], "rows": [], "total_rows": 0, "total_cols": 0})
            continue

        col_limit = min(mc, _MAX_PREVIEW_COLS)

        headers: List[str] = []
        rows: List[List[Any]] = []
        # Use iter_rows() — much faster than ws.cell() in read_only mode
        for row_idx, row in enumerate(ws.iter_rows(max_col=col_limit, values_only=True)):
            if row_idx == 0:
                headers = [str(v) if v is not None else f"Col{ci + 1}" for ci, v in enumerate(row)]
                continue
            if row_idx >= effective_max_rows:
                break
            row_data: List[Any] = []
            for v in row:
                if v is None:
                    row_data.append("")
                elif isinstance(v, (int, float)):
                    row_data.append(v)
                else:
                    s = str(v).strip()
                    row_data.append(s[:200] if len(s) > 200 else s)
            if any(v != "" for v in row_data):
                rows.append(row_data)

        sheets.append({
            "name": sname,
            "headers": headers,
            "rows": rows,
            "total_rows": mr,
            "total_cols": mc,
        })

    all_sheet_names = list(wb.sheetnames)
    wb.close()
    return {
        "filename": file_path.name,
        "sheets": sheets,
        "sheet_names": all_sheet_names,
    }


def _load_excel_artifact_payload(
    file_path: Path,
    artifact_type: str,
    *,
    download_url: str,
    preview_url: str,
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
        elif kind == "sits":
            from generators.sits import validate_sits_xlsm
            validation = validate_sits_xlsm(str(file_path))
            stats = validation.get("stats", {}) if isinstance(validation, dict) else {}
            result["validation"] = validation
            result["test_case_count"] = int(stats.get("tc_count") or 0)
            result["total_sub_cases"] = int(stats.get("sub_case_count") or 0)
            result["flow_count"] = int(stats.get("flow_count") or 0)
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

@router.post("/api/local/reports/generate")
def local_reports_generate(req: LocalReportGenerateRequest) -> Dict[str, Any]:
    report_dir = _resolve_report_dir(req.report_dir)
    summary_path = report_dir / "analysis_summary.json"
    if not summary_path.exists():
        raise HTTPException(status_code=404, detail="analysis_summary.json not found")
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"summary parse error: {e}")

    out_dir = _local_reports_dir(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"local_report_{ts}"
    formats = [str(f).lower() for f in (req.formats or [])]

    outputs: List[Dict[str, Any]] = []
    if "docx" in formats:
        out_path = out_dir / f"{base}.docx"
        generate_local_docx(summary, out_path)
        outputs.append({"file": out_path.name, "path": str(out_path)})
    if "xlsx" in formats:
        out_path = out_dir / f"{base}.xlsx"
        generate_local_xlsx(summary, out_path)
        outputs.append({"file": out_path.name, "path": str(out_path)})

    return {"ok": True, "files": outputs}


@router.get("/api/local/reports")
def local_reports_list(report_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    report_path = _resolve_report_dir(report_dir)
    reports_dir = _local_reports_dir(report_path)
    if not reports_dir.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for p in reports_dir.glob("local_report_*.*"):
        if not p.is_file():
            continue
        rows.append(
            {
                "file": p.name,
                "path": str(p),
                "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                "download_url": f"/api/local/reports/download/{p.name}?report_dir={report_path}",
            }
        )
    rows.sort(key=lambda x: x.get("mtime") or "", reverse=True)
    return rows


@router.get("/api/local/reports/download/{filename}")
def local_reports_download(filename: str, report_dir: Optional[str] = None) -> FileResponse:
    report_path = _resolve_report_dir(report_dir)
    file_path = _resolve_local_report_path(report_path, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="report not found")
    media = "application/octet-stream"
    if file_path.suffix.lower() == ".docx":
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif file_path.suffix.lower() == ".xlsx":
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(str(file_path), filename=file_path.name, media_type=media)


@router.post("/api/local/uds/generate")
async def local_uds_generate(
    request: Request,
    source_root: str = Form(""),
    req_files: List[UploadFile] = File(default_factory=list),
    req_paths: str = Form(""),
    template_file: UploadFile = File(default=None),
    template_strict: bool = Form(False),
    component_list: UploadFile = File(default=None),
    logic_max_children: Optional[int] = Form(None),
    logic_max_grandchildren: Optional[int] = Form(None),
    logic_max_depth: Optional[int] = Form(None),
    globals_format_order: str = Form(""),
    globals_format_sep: str = Form(""),
    globals_format_with_labels: bool = Form(True),
    call_relation_mode: str = Form("code"),
    ai_enable: bool = Form(False),
    ai_example_path: str = Form(""),
    ai_detailed: bool = Form(True),
    expand: bool = Form(False),
    doc_only: bool = Form(False),
    test_mode: bool = Form(False),
    rag_top_k: Optional[int] = Form(None),
    rag_categories: str = Form(""),
    report_dir: str = Form(""),
    req_types: str = Form(""),
    show_mapping_evidence: bool = Form(False),
) -> Dict[str, Any]:
    req_id = (request.headers.get("x-req-id") or "").strip() or f"uds-gen-{int(time.time() * 1000)}"
    _logger.info("[UDS_GENERATE][%s] start source_root=%s test_mode=%s", req_id, source_root, bool(test_mode))
    template_bytes: Optional[bytes] = None
    template_warning = ""
    if template_file and template_file.filename:
        try:
            template_bytes = await template_file.read()
        except Exception:
            template_bytes = None
        valid_tpl, tpl_err = _validate_docx_template_bytes(template_bytes)
        if not valid_tpl:
            msg = f"template invalid: {tpl_err}"
            if bool(template_strict):
                raise HTTPException(status_code=400, detail=msg)
            template_warning = msg
            template_bytes = None
    source_root_path = Path(source_root).resolve() if source_root else None
    if not source_root_path or not source_root_path.exists() or not source_root_path.is_dir():
        raise HTTPException(status_code=400, detail="source_root(코드 루트)가 필요합니다.")
    req_paths_list = _parse_path_list(req_paths)
    has_req_upload = any((f and f.filename) for f in (req_files or []))
    if not has_req_upload and not req_paths_list:
        raise HTTPException(status_code=400, detail="SRS/SDS 요구사항 문서를 최소 1개 이상 제공해주세요.")

    type_list = [t.strip().lower() for t in req_types.split(",") if t.strip()] if req_types else []

    req_texts: List[str] = []
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
    sds_doc_paths: List[str] = []
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
            fname_lower = p.name.lower()
            if "srs" in fname_lower:
                srs_texts.append(text.strip())
            elif "sds" in fname_lower:
                sds_texts.append(text.strip())
                if p.suffix.lower() in {".docx", ".doc"}:
                    sds_doc_paths.append(str(p))

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

    source_sections: Dict[str, str] = {}
    if source_root_path and source_root_path.exists():
        source_sections = generate_uds_source_sections(
            str(source_root_path),
            component_map=component_map if component_map else None,
        )
        source_sections, req_doc_paths, sds_doc_paths = _enrich_source_sections_with_docs(
            source_sections,
            req_doc_paths=req_doc_paths,
            sds_doc_paths=sds_doc_paths,
        )

    req_from_docs = generate_uds_requirements_from_docs(req_texts) if req_texts else ""
    req_map = _build_req_map_from_doc_paths(req_doc_paths, req_texts) if req_texts or req_doc_paths else {}
    req_source = source_sections.get("requirements", "")
    if req_from_docs and req_source:
        req_combined = "\n".join([req_from_docs.strip(), req_source.strip()]).strip()
    else:
        req_combined = req_from_docs or req_source

    globals_order_list = [
        x.strip()
        for x in re.split(r"[,\|;]+", globals_format_order or "")
        if x.strip()
    ]
    uds_payload = {
        "job_url": "local",
        "build_number": "",
        "project_name": source_root_path.name if source_root_path else "",
        "summary": {},
        "overview": source_sections.get("overview", ""),
        "requirements": req_combined,
        "interfaces": source_sections.get("interfaces", ""),
        "uds_frames": source_sections.get("uds_frames", ""),
        "notes": "",
        "logic_diagrams": [],
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
        "globals_format_with_labels": globals_format_with_labels,
        "call_relation_mode": call_relation_mode,
        "show_mapping_evidence": bool(show_mapping_evidence),
        "logic_max_children": logic_max_children,
        "logic_max_grandchildren": logic_max_grandchildren,
        "logic_max_depth": logic_max_depth,
        "srs_texts": srs_texts,
        "sds_texts": sds_texts,
        "sds_doc_paths": sds_doc_paths,
    }
    impact_path = _run_impact_analysis_for_uds(
        source_root_path,
        os.getenv("UDS_CHANGED_FILES", ""),
    )
    if impact_path:
        notes_text = str(uds_payload.get("notes") or "").strip()
        uds_payload["notes"] = "\n".join([x for x in [notes_text, f"impact:{impact_path.name}"] if x])

    if ai_enable:
        rag_snippets: List[Dict[str, Any]] = []
        try:
            report_path = _resolve_report_dir(report_dir)
            kb = get_kb(report_path)
            rag_query = req_combined.strip()[:2000] or (source_sections.get("overview", "") or "")[:2000]
            if rag_query:
                fn_count = len(source_sections.get("function_details_by_name") or {}) if isinstance(source_sections, dict) else 0
                default_top_k = 12 if fn_count >= 300 else 10 if fn_count >= 120 else 8 if expand else 4
                use_top_k = rag_top_k if rag_top_k and rag_top_k > 0 else int(
                    getattr(config, "AGENT_RAG_TOP_K_DEFAULT", default_top_k)
                )
                use_categories = [str(c).strip() for c in re.split(r"[,\n;]+", rag_categories or "") if str(c).strip()]
                if not use_categories:
                    use_categories = ["uds", "requirements", "code", "constraints"]
                rag_rows = kb.search(
                    rag_query,
                    top_k=use_top_k,
                    categories=use_categories,
                )
                for row in rag_rows:
                    rag_snippets.append(
                        {
                            "title": row.get("error_raw") or "",
                            "category": row.get("category") or "",
                            "source_type": "rag",
                            "source_file": row.get("source_file") or "",
                            "excerpt": str(row.get("context") or row.get("fix") or "")[:1200],
                            "score": row.get("score"),
                        }
                    )
        except Exception:
            rag_snippets = []
        example_text = ""
        template_text = ""
        if ai_example_path:
            try:
                p = Path(ai_example_path).expanduser().resolve()
                if p.exists() and p.is_file():
                    example_text = _read_text_from_file(p)
            except Exception:
                example_text = ""
        if not example_text and template_file and template_file.filename and template_bytes:
            try:
                suffix = Path(template_file.filename).suffix.lower() or ".docx"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(template_bytes)
                    template_text = _read_text_from_file(Path(tmp.name))
            except Exception:
                template_text = ""
            example_text = template_text or example_text
        if not example_text:
            try:
                ref_suds_path = Path(config.UDS_REF_SUDS_PATH)
                if ref_suds_path.exists() and ref_suds_path.is_file():
                    example_text = _read_text_from_file(ref_suds_path)
            except Exception:
                pass
        notes_text = ""
        if expand:
            doc_block = "\n\n".join(req_texts)[:40000]
            src_block = "\n\n".join(
                [
                    source_sections.get("overview", ""),
                    source_sections.get("interfaces", ""),
                    source_sections.get("uds_frames", ""),
                ]
            )
            notes_text = "\n\n".join([doc_block, src_block]).strip()
        ai_sections = generate_uds_ai_sections(
            requirements_text=req_combined,
            source_sections=source_sections,
            notes_text=notes_text,
            logic_items=[],
            example_text=example_text,
            detailed=bool(True if expand else ai_detailed),
            rag_snippets=rag_snippets,
        )
        if ai_sections:
            uds_payload["ai_sections"] = ai_sections
    _enrich_function_quality_fields(uds_payload)
    quick_quality_gate = _compute_quick_quality_gate(uds_payload)

    out_dir = _local_uds_dir(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"uds_local_{ts}.docx"
    tpl_path = None
    template_applied = False
    if template_file and template_file.filename and template_bytes:
        suffix = Path(template_file.filename).suffix.lower() or ".docx"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(template_bytes)
            tpl_tmp_path = Path(tmp.name)
            tpl_path = str(tpl_tmp_path)
        try:
            tpl_text = _read_text_from_file(Path(tpl_path))
            template_applied = "{{" in tpl_text and "}}" in tpl_text
        except Exception:
            template_applied = False
    if not tpl_path:
        # Use SUDS reference as default template for 4-level SUDS structure
        try:
            from config import UDS_REF_SUDS_PATH
            _ref_path = Path(UDS_REF_SUDS_PATH)
        except Exception:
            _ref_path = Path(__file__).resolve().parents[2] / "docs" / "(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx"
        if _ref_path.exists():
            tpl_path = str(_ref_path)
    try:
        # Inject ai_config into payload for subprocess to use in function desc enhancement
        _uds_ai_cfg = _load_sts_ai_config()
        if _uds_ai_cfg:
            uds_payload["_gen_ai_config"] = _uds_ai_cfg
        _generate_docx_with_retry(tpl_path, uds_payload, out_path)
    except Exception as docx_exc:
        tb = traceback.format_exc()
        _logger.error("[UDS_GENERATE][%s] DOCX generation error:\n%s", req_id, tb)
        err_detail = str(docx_exc)[:800]
        if "timeout" in err_detail.lower():
            raise HTTPException(
                status_code=504,
                detail=f"UDS DOCX 생성 타임아웃: {err_detail}\n\n재시도하거나 AI를 비활성화하세요.",
            )
        raise HTTPException(
            status_code=500,
            detail=f"UDS DOCX 생성 실패: {err_detail}",
        )
    _write_uds_payload_sidecar(out_path, uds_payload)
    residual_tbd_path = _write_residual_tbd_report(out_path, (uds_payload.get("summary") or {}).get("mapping") or {})
    report_timeout_short = 3600 if bool(test_mode) else 300
    report_timeout_long = 14400 if bool(test_mode) else 600
    if bool(doc_only):
        quality_evaluation = _build_quality_evaluation(
            quick_quality_gate,
            quality_gate_path=None,
            accuracy_path=None,
            template_warning=template_warning,
            doc_only_mode=True,
        )
        _logger.info("[UDS_GENERATE][%s] done file=%s (doc_only)", req_id, out_path.name)
        return {
            "ok": True,
            "filename": out_path.name,
            "path": str(out_path),
            "template_applied": template_applied,
            "download_url": f"/api/local/uds/download/{out_path.name}?report_dir={report_dir}",
            "preview_url": "",
            "preview_path": "",
            "validation_path": "",
            "accuracy_path": "",
            "swcom_context_path": "",
            "swcom_diff_path": "",
            "confidence_path": "",
            "constraints_path": "",
            "quality_gate_path": "",
            "impact_path": str(impact_path) if impact_path else "",
            "residual_tbd_report_path": str(residual_tbd_path) if residual_tbd_path else "",
            "quick_quality_gate": quick_quality_gate,
            "quality_evaluation": quality_evaluation,
        }
    validation_path = out_path.with_suffix(".validation.md")
    ok_validation, _ = _run_report_with_timeout(
        lambda: generate_uds_validation_report(str(out_path), str(validation_path)),
        timeout_seconds=report_timeout_short,
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
        timeout_seconds=report_timeout_long,
        report_name="accuracy report",
    )
    if not ok_accuracy:
        accuracy_path = None
    swcom_context_path = out_path.with_suffix(".swcom_context.md")
    ok_swcom, _ = _run_report_with_timeout(
        lambda: generate_swcom_context_report(str(out_path), str(swcom_context_path)),
        timeout_seconds=report_timeout_short,
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
        timeout_seconds=report_timeout_short,
        report_name="ASIL/Related confidence report",
    )
    if not ok_confidence:
        confidence_path = None
    constraints_path = out_path.with_suffix(".constraints.md")
    ok_constraints, _ = _run_report_with_timeout(
        lambda: generate_uds_constraints_report(uds_payload, str(constraints_path)),
        timeout_seconds=report_timeout_short,
        report_name="constraints report",
    )
    if not ok_constraints:
        constraints_path = None
    quality_gate_path = out_path.with_suffix(".quality_gate.md")
    ok_quality_gate, _ = _run_report_with_timeout(
        lambda: generate_uds_field_quality_gate_report(str(out_path), str(quality_gate_path)),
        timeout_seconds=report_timeout_short,
        report_name="field quality gate report",
    )
    if not ok_quality_gate:
        quality_gate_path = None
    preview_html = generate_uds_preview_html(uds_payload)
    preview_path = out_path.with_suffix(".html")
    preview_path.write_text(preview_html, encoding="utf-8")
    quality_evaluation = _build_quality_evaluation(
        quick_quality_gate,
        quality_gate_path=quality_gate_path,
        accuracy_path=accuracy_path,
        template_warning=template_warning,
        doc_only_mode=False,
    )
    _logger.info("[UDS_GENERATE][%s] done file=%s", req_id, out_path.name)

    return {
        "ok": True,
        "filename": out_path.name,
        "path": str(out_path),
        "template_applied": template_applied,
        "download_url": f"/api/local/uds/download/{out_path.name}?report_dir={report_dir}",
        "preview_url": f"/api/local/uds/preview/{preview_path.name}?report_dir={report_dir}",
        "preview_path": str(preview_path),
        "validation_path": str(validation_path) if validation_path else "",
        "accuracy_path": str(accuracy_path) if accuracy_path else "",
        "swcom_context_path": str(swcom_context_path) if swcom_context_path else "",
        "swcom_diff_path": str(swcom_diff_path) if swcom_diff_path else "",
        "confidence_path": str(confidence_path) if confidence_path else "",
        "constraints_path": str(constraints_path) if constraints_path else "",
        "quality_gate_path": str(quality_gate_path) if quality_gate_path else "",
        "impact_path": str(impact_path) if impact_path else "",
        "residual_tbd_report_path": str(residual_tbd_path) if residual_tbd_path else "",
        "quick_quality_gate": quick_quality_gate,
        "quality_evaluation": quality_evaluation,
    }


@router.post("/api/local/uds/generate-async")
async def local_uds_generate_async(
    request: Request,
    source_root: str = Form(""),
    req_files: List[UploadFile] = File(default_factory=list),
    req_paths: str = Form(""),
    template_file: UploadFile = File(default=None),
    template_strict: bool = Form(False),
    component_list: UploadFile = File(default=None),
    logic_max_children: Optional[int] = Form(None),
    logic_max_grandchildren: Optional[int] = Form(None),
    logic_max_depth: Optional[int] = Form(None),
    globals_format_order: str = Form(""),
    globals_format_sep: str = Form(""),
    globals_format_with_labels: bool = Form(True),
    call_relation_mode: str = Form("code"),
    ai_enable: bool = Form(False),
    ai_example_path: str = Form(""),
    ai_detailed: bool = Form(True),
    expand: bool = Form(False),
    doc_only: bool = Form(False),
    test_mode: bool = Form(False),
    rag_top_k: Optional[int] = Form(None),
    rag_categories: str = Form(""),
    report_dir: str = Form(""),
    req_types: str = Form(""),
    show_mapping_evidence: bool = Form(False),
) -> Dict[str, Any]:
    """Non-blocking local UDS generation. Returns job_id for progress polling."""
    source_root_path = Path(source_root).resolve() if source_root else None
    if not source_root_path or not source_root_path.exists() or not source_root_path.is_dir():
        raise HTTPException(status_code=400, detail="source_root(코드 루트)가 필요합니다.")
    req_paths_list = _parse_path_list(req_paths)
    has_req_upload = any((f and f.filename) for f in (req_files or []))
    if not has_req_upload and not req_paths_list:
        raise HTTPException(status_code=400, detail="SRS/SDS 요구사항 문서를 최소 1개 이상 제공해주세요.")

    job_id = uuid.uuid4().hex
    _set_progress(
        "local_uds", "local", "local",
        {"stage": "start", "percent": 1, "message": "Local UDS 생성 준비 중", "done": False, "error": ""},
        job_id=job_id,
    )

    req_file_paths: List[Path] = []
    for f in req_files:
        if not f or not f.filename:
            continue
        suffix = Path(f.filename).suffix.lower() or ".txt"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await f.read())
            req_file_paths.append(Path(tmp.name))

    template_bytes: Optional[bytes] = None
    if template_file and template_file.filename:
        try:
            template_bytes = await template_file.read()
        except Exception:
            template_bytes = None

    comp_map: Dict[str, Dict[str, str]] = {}
    if component_list and component_list.filename:
        tmp = _write_upload_to_temp(component_list, ".json")
        if tmp:
            try:
                comp_map = _parse_component_map_file(tmp)
            except Exception:
                comp_map = {}
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass

    type_list = [t.strip().lower() for t in req_types.split(",") if t.strip()] if req_types else []

    def _worker():
        try:
            _set_progress(
                "local_uds", "local", "local",
                {"stage": "source_analysis", "percent": 10, "message": "소스 코드 분석 중"},
                job_id=job_id,
            )
            source_sections = generate_uds_source_sections(
                str(source_root_path),
                component_map=comp_map if comp_map else None,
            ) if source_root_path and source_root_path.exists() else {}

            _set_progress(
                "local_uds", "local", "local",
                {"stage": "requirements", "percent": 30, "message": "요구사항 문서 처리 중"},
                job_id=job_id,
            )
            req_texts: List[str] = []
            srs_texts: List[str] = []
            sds_texts: List[str] = []
            sds_doc_paths: List[str] = []
            req_doc_paths: List[str] = []
            for idx, fp in enumerate(req_file_paths):
                try:
                    text = _read_text_from_file(fp)
                except Exception:
                    text = ""
                if fp.suffix.lower() == ".docx":
                    req_doc_paths.append(str(fp))
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
                    fname_lower = p.name.lower()
                    if "srs" in fname_lower:
                        srs_texts.append(text.strip())
                    elif "sds" in fname_lower:
                        sds_texts.append(text.strip())
                        if p.suffix.lower() in {".docx", ".doc"}:
                            sds_doc_paths.append(str(p))

            source_sections, req_doc_paths, sds_doc_paths = _enrich_source_sections_with_docs(
                source_sections,
                req_doc_paths=req_doc_paths,
                sds_doc_paths=sds_doc_paths,
            )

            req_from_docs = generate_uds_requirements_from_docs(req_texts) if req_texts else ""
            req_map = _build_req_map_from_doc_paths(req_doc_paths, req_texts) if req_texts or req_doc_paths else {}
            req_source = source_sections.get("requirements", "")
            req_combined = "\n".join([req_from_docs.strip(), req_source.strip()]).strip() if req_from_docs and req_source else (req_from_docs or req_source)

            globals_order_list = [x.strip() for x in re.split(r"[,\|;]+", globals_format_order or "") if x.strip()]
            uds_payload = {
                "job_url": "local",
                "build_number": "",
                "project_name": source_root_path.name if source_root_path else "",
                "summary": {},
                "overview": source_sections.get("overview", ""),
                "requirements": req_combined,
                "interfaces": source_sections.get("interfaces", ""),
                "uds_frames": source_sections.get("uds_frames", ""),
                "notes": "",
                "logic_diagrams": [],
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
                "globals_format_with_labels": globals_format_with_labels,
                "call_relation_mode": call_relation_mode,
                "show_mapping_evidence": bool(show_mapping_evidence),
                "logic_max_children": logic_max_children,
                "logic_max_grandchildren": logic_max_grandchildren,
                "logic_max_depth": logic_max_depth,
                "srs_texts": srs_texts,
                "sds_texts": sds_texts,
                "sds_doc_paths": sds_doc_paths,
            }

            _set_progress(
                "local_uds", "local", "local",
                {"stage": "docx_generation", "percent": 50, "message": "DOCX 생성 중"},
                job_id=job_id,
            )
            _enrich_function_quality_fields(uds_payload)
            out_dir = _local_uds_dir(report_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = out_dir / f"uds_local_{ts}.docx"

            tpl_path = None
            if template_bytes:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                    tmp.write(template_bytes)
                    tpl_path = str(Path(tmp.name))

            _uds_ai_cfg = _load_sts_ai_config()
            if _uds_ai_cfg:
                uds_payload["_gen_ai_config"] = _uds_ai_cfg
            _generate_docx_with_retry(tpl_path, uds_payload, out_path)
            _write_uds_payload_sidecar(out_path, uds_payload)
            residual_tbd_path = _write_residual_tbd_report(out_path, (uds_payload.get("summary") or {}).get("mapping") or {})

            _set_progress(
                "local_uds", "local", "local",
                {"stage": "reports", "percent": 80, "message": "리포트 생성 중"},
                job_id=job_id,
            )
            report_timeout = 3600 if bool(test_mode) else 300
            quick_qg = _compute_quick_quality_gate(uds_payload)
            if not bool(doc_only):
                _run_report_with_timeout(
                    lambda: generate_uds_validation_report(str(out_path), str(out_path.with_suffix(".validation.md"))),
                    timeout_seconds=report_timeout, report_name="validation",
                )
                _run_report_with_timeout(
                    lambda: generate_uds_field_quality_gate_report(str(out_path), str(out_path.with_suffix(".quality_gate.md"))),
                    timeout_seconds=report_timeout, report_name="quality gate",
                )

            _set_progress(
                "local_uds", "local", "local",
                {
                    "stage": "done", "percent": 100, "message": "완료",
                    "done": True, "error": "",
                    "result": {
                        "ok": True,
                        "filename": out_path.name,
                        "path": str(out_path),
                        "download_url": f"/api/local/uds/download/{out_path.name}?report_dir={report_dir}",
                        "residual_tbd_report_path": str(residual_tbd_path) if residual_tbd_path else "",
                        "quick_quality_gate": quick_qg,
                    },
                },
                job_id=job_id,
            )
            _logger.info("[UDS_ASYNC_LOCAL][%s] done file=%s", job_id, out_path.name)

        except Exception as exc:
            tb = traceback.format_exc()
            _logger.error("[UDS_ASYNC_LOCAL][%s] FAILED: %s\n%s", job_id, str(exc)[:500], tb)
            _set_progress(
                "local_uds", "local", "local",
                {"stage": "error", "percent": 100, "message": f"실패: {str(exc)[:300]}", "done": True, "error": str(exc)[:500]},
                job_id=job_id,
            )

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "job_id": job_id}


@router.get("/api/local/uds/progress")
def local_uds_progress(job_id: str = "") -> Dict[str, Any]:
    data = _get_progress("local_uds", "local", "local", job_id)
    return {"ok": bool(data), "progress": data}


@router.get("/api/local/uds/download/{filename}")
def local_uds_download(filename: str, report_dir: Optional[str] = None) -> FileResponse:
    file_path = _resolve_local_uds_path(report_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="uds report not found")
    media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return FileResponse(str(file_path), filename=file_path.name, media_type=media)


@router.get("/api/local/uds/preview/{filename}")
def local_uds_preview(filename: str, report_dir: Optional[str] = None) -> HTMLResponse:
    file_path = _resolve_local_uds_path(report_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="uds preview not found")
    return HTMLResponse(file_path.read_text(encoding="utf-8", errors="ignore"))


@router.get("/api/local/uds/files")
def local_uds_files(report_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    base = _resolve_report_dir(report_dir)
    uds_dir = _local_uds_dir(base)
    if not uds_dir.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for p in uds_dir.glob("*.docx"):
        if not p.is_file():
            continue
        rows.append(
            {
                "filename": p.name,
                "path": str(p),
                "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                "download_url": f"/api/local/uds/download/{p.name}?report_dir={report_dir or ''}",
                "preview_url": f"/api/local/uds/preview/{p.with_suffix('.html').name}?report_dir={report_dir or ''}",
            }
        )
    rows.sort(key=lambda x: x.get("mtime") or "", reverse=True)
    return rows


@router.get("/api/local/uds/view/{filename}")
def local_uds_view(
    filename: str,
    report_dir: Optional[str] = None,
    q: str = Query(default=""),
    swcom: str = Query(default="all"),
    asil: str = Query(default="all"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    trace_q: str = Query(default=""),
    trace_page: int = Query(default=1, ge=1),
    trace_page_size: int = Query(default=100, ge=1, le=500),
) -> Dict[str, Any]:
    if Path(filename).suffix.lower() != ".docx":
        raise HTTPException(status_code=400, detail="filename must be .docx")
    docx_path = _resolve_local_uds_path(report_dir, filename)
    if not docx_path.exists():
        raise HTTPException(status_code=404, detail="uds report not found")
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
    preview_name = docx_path.with_suffix(".html").name
    payload["download_url"] = f"/api/local/uds/download/{docx_path.name}?report_dir={report_dir or ''}"
    payload["preview_url"] = f"/api/local/uds/preview/{preview_name}?report_dir={report_dir or ''}"
    payload["accuracy_path"] = str(accuracy_path) if accuracy_path.exists() else ""
    payload["quality_gate_path"] = str(quality_gate_path) if quality_gate_path.exists() else ""
    residual_tbd_path = docx_path.with_suffix(".residual_tbd.md")
    payload["residual_tbd_report_path"] = str(residual_tbd_path) if residual_tbd_path.exists() else ""
    return payload


@router.get("/api/local/uds/view-by-path")
def local_uds_view_by_path(
    docx_path: str,
    q: str = Query(default=""),
    swcom: str = Query(default="all"),
    asil: str = Query(default="all"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    trace_q: str = Query(default=""),
    trace_page: int = Query(default=1, ge=1),
    trace_page_size: int = Query(default=100, ge=1, le=500),
) -> Dict[str, Any]:
    target = Path(str(docx_path or "")).expanduser().resolve()
    if target.suffix.lower() != ".docx":
        raise HTTPException(status_code=400, detail="docx_path must be .docx")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="uds report not found")
    accuracy_path = target.with_suffix(".accuracy.md")
    quality_gate_path = target.with_suffix(".quality_gate.md")
    payload = _get_uds_view_payload_cached(
        target,
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
    payload["download_url"] = ""
    payload["preview_url"] = ""
    payload["accuracy_path"] = str(accuracy_path) if accuracy_path.exists() else ""
    payload["quality_gate_path"] = str(quality_gate_path) if quality_gate_path.exists() else ""
    residual_tbd_path = target.with_suffix(".residual_tbd.md")
    payload["residual_tbd_report_path"] = str(residual_tbd_path) if residual_tbd_path.exists() else ""
    return payload


@router.post("/api/local/traceability")
def local_traceability(
    request: Request,
    source_root: str = Form(""),
    srs_path: str = Form(""),
    report_dir: str = Form(""),
) -> Dict[str, Any]:
    """Build full traceability matrix: SRS -> Functions -> Test Cases."""
    from sts_generator import (
        parse_srs_docx_tables,
        parse_requirements_structured,
        map_requirements_to_functions,
        generate_traceability_matrix,
    )
    import re as _re

    srs_docx: Optional[str] = None
    if srs_path:
        p = Path(srs_path).expanduser().resolve()
        if p.exists() and p.is_file():
            srs_docx = str(p)

    # Parse requirements
    reqs: List[Dict[str, Any]] = []
    if srs_docx:
        reqs = parse_srs_docx_tables(srs_docx)

    if not reqs:
        raise HTTPException(status_code=400, detail="SRS 문서에서 요구사항을 추출할 수 없습니다.")

    # Parse source for function details
    function_details: Dict[str, Any] = {}
    source_root_path = Path(source_root).resolve() if source_root else None
    if source_root_path and source_root_path.exists() and source_root_path.is_dir():
        try:
            sections = _get_source_sections_cached(str(source_root_path))
            function_details = sections.get("function_details", {})
        except Exception:
            pass

    # Map requirements to functions
    req_to_fids = map_requirements_to_functions(reqs, function_details)

    # Keyword-based fallback mapping if related fields are TBD
    _kw_map = {
        "battery": ["apiin", "apiout", "monitor_adc", "drvin", "vsup"],
        "voltage": ["apiin", "apiout", "monitor_adc", "drvin", "vsup"],
        "buzzer": ["buzzer"],
        "door": ["door", "motor"],
        "motor": ["door", "motor"],
        "latch": ["door"],
        "lin": ["lin", "apiin", "apiout"],
        "signal": ["lin", "apiin", "apiout"],
        "eeprom": ["eeprom"],
        "memory": ["eeprom"],
        "sleep": ["sleep", "wake"],
        "wakeup": ["sleep", "wake"],
        "diag": ["diag", "uds"],
        "diagnostic": ["diag", "uds"],
        "option": ["option"],
        "init": ["init", "main", "sysctrl"],
        "position": ["motor", "speed", "direction"],
        "sensor": ["motor", "speed", "direction"],
        "pwm": ["pwm"],
        "error": ["diag", "error"],
        "close": ["door", "motor"],
        "open": ["door", "motor"],
    }
    mapped_count_before = sum(1 for v in req_to_fids.values() if v)
    if function_details and mapped_count_before < len(reqs) * 0.3:
        for r in reqs:
            rid = r["id"]
            if req_to_fids.get(rid):
                continue
            desc = (r.get("description", "") + " " + r.get("name", "")).lower()
            keywords = set()
            for kw, fns in _kw_map.items():
                if kw in desc:
                    keywords.update(fns)
            if keywords:
                for fid, info in function_details.items():
                    if not isinstance(info, dict):
                        continue
                    fname = str(info.get("name", "")).lower()
                    if any(k in fname for k in keywords):
                        if fid not in req_to_fids[rid]:
                            req_to_fids[rid].append(fid)

    # Load STS test cases if available
    sts_test_cases: List[Dict[str, Any]] = []
    base = _resolve_report_dir(report_dir)
    sts_dir = base / "sts"
    sts_file_name = None
    if sts_dir.exists():
        latest_sts = _find_latest_excel_file(sts_dir)
        if latest_sts:
            sts_file_name = latest_sts.name
            try:
                import openpyxl
                wb = openpyxl.load_workbook(str(latest_sts), read_only=True, data_only=True)
                if "3.SW Integration Test Spec" in wb.sheetnames:
                    ws = wb["3.SW Integration Test Spec"]
                    for r in range(7, (ws.max_row or 7) + 1):
                        tc_id = ws.cell(row=r, column=2).value
                        if tc_id:
                            sts_test_cases.append({
                                "tc_id": str(tc_id),
                                "title": str(ws.cell(row=r, column=3).value or ""),
                                "method": str(ws.cell(row=r, column=6).value or ""),
                                "srs_id": str(ws.cell(row=r, column=13).value or ""),
                            })
                wb.close()
            except Exception:
                pass

    # Load SUTS test cases if available
    suts_test_cases: List[Dict[str, Any]] = []
    suts_dir = base / "suts"
    suts_file_name = None
    if suts_dir.exists():
        latest_suts = _find_latest_excel_file(suts_dir)
        if latest_suts:
            suts_file_name = latest_suts.name
            try:
                import openpyxl as _xl
                swb = _xl.load_workbook(str(latest_suts), read_only=True, data_only=True)
                if "2.SW Unit Test Spec" in swb.sheetnames:
                    sws = swb["2.SW Unit Test Spec"]
                    for sr in range(7, (sws.max_row or 7) + 1):
                        tc_id = sws.cell(row=sr, column=3).value
                        if tc_id and str(tc_id).startswith("SwUTC"):
                            related = sws.cell(row=sr, column=149).value or ""
                            n_inp = sum(1 for c in range(14, 63) if sws.cell(row=sr, column=c).value is not None)
                            n_out = sum(1 for c in range(63, 149) if sws.cell(row=sr, column=c).value is not None)
                            suts_test_cases.append({
                                "tc_id": str(tc_id),
                                "name": str(sws.cell(row=sr, column=4).value or ""),
                                "related_fid": str(related),
                                "gen_method": str(sws.cell(row=sr, column=12).value or ""),
                                "input_count": n_inp,
                                "output_count": n_out,
                            })
                swb.close()
            except Exception:
                pass

    # Build fid→suts_tc lookup
    fid_to_suts: Dict[str, List[Dict[str, Any]]] = {}
    for stc in suts_test_cases:
        fid = stc.get("related_fid", "")
        if fid:
            fid_to_suts.setdefault(fid, []).append(stc)

    # Build traceability rows
    rows: List[Dict[str, Any]] = []
    for r in reqs:
        rid = r["id"]
        fids = req_to_fids.get(rid, [])
        func_names = []
        for fid in fids[:10]:
            info = function_details.get(fid)
            if isinstance(info, dict):
                func_names.append(info.get("name", fid))

        sts_tcs = [tc for tc in sts_test_cases if tc.get("srs_id") == rid]
        suts_tcs_for_req: List[Dict[str, Any]] = []
        for fid in fids:
            suts_tcs_for_req.extend(fid_to_suts.get(fid, []))

        has_uds = len(fids) > 0
        has_sts = len(sts_tcs) > 0
        has_suts = len(suts_tcs_for_req) > 0

        if has_uds and has_sts and has_suts:
            status = "covered"
        elif has_uds and (has_sts or has_suts):
            status = "partial"
        elif has_uds or has_sts or has_suts:
            status = "partial"
        else:
            status = "uncovered"

        rows.append({
            "req_id": rid,
            "req_name": r.get("name", ""),
            "req_type": r.get("req_type", ""),
            "asil": r.get("asil", ""),
            "func_count": len(fids),
            "func_names": func_names[:5],
            "tc_count": len(sts_tcs),
            "tc_ids": [tc["tc_id"] for tc in sts_tcs[:5]],
            "suts_tc_count": len(suts_tcs_for_req),
            "suts_tc_ids": [tc["tc_id"] for tc in suts_tcs_for_req[:5]],
            "has_uds": has_uds,
            "has_sts": has_sts,
            "has_suts": has_suts,
            "status": status,
        })

    # Summary
    total = len(rows)
    covered = sum(1 for r in rows if r["status"] == "covered")
    partial = sum(1 for r in rows if r["status"] == "partial")
    uncovered = sum(1 for r in rows if r["status"] == "uncovered")
    safety_total = sum(1 for r in rows if r["asil"] and r["asil"].upper() not in ("QM", "TBD", ""))
    safety_covered = sum(1 for r in rows if r["status"] == "covered" and r["asil"] and r["asil"].upper() not in ("QM", "TBD", ""))

    type_dist: Dict[str, int] = {}
    for r in rows:
        t = r["req_type"] or "OTHER"
        type_dist[t] = type_dist.get(t, 0) + 1

    # SUTS-specific coverage
    total_suts_fns = len(suts_test_cases)
    fns_with_suts = sum(1 for fid in function_details if fid in fid_to_suts)

    return {
        "ok": True,
        "summary": {
            "total_requirements": total,
            "covered": covered,
            "partial": partial,
            "uncovered": uncovered,
            "coverage_pct": round(covered / max(total, 1) * 100, 1),
            "full_coverage_pct": round((covered + partial) / max(total, 1) * 100, 1),
            "safety_total": safety_total,
            "safety_covered": safety_covered,
            "safety_pct": round(safety_covered / max(safety_total, 1) * 100, 1),
            "total_functions": len(function_details),
            "total_sts_test_cases": len(sts_test_cases),
            "total_suts_test_cases": total_suts_fns,
            "suts_function_coverage": fns_with_suts,
            "suts_function_coverage_pct": round(fns_with_suts / max(len(function_details), 1) * 100, 1),
            "type_distribution": type_dist,
        },
        "rows": rows,
        "sts_file": sts_file_name,
        "suts_file": suts_file_name,
    }


@router.post("/api/local/sts/generate")
async def local_sts_generate(
    request: Request,
    source_root: str = Form(""),
    srs_path: str = Form(""),
    sds_path: str = Form(""),
    uds_path: str = Form(""),
    stp_path: str = Form(""),
    hsis_path: str = Form(""),
    req_paths: str = Form(""),
    req_files: List[UploadFile] = File(default_factory=list),
    template_path: str = Form(""),
    project_id: str = Form(""),
    version: str = Form("v1.00"),
    asil_level: str = Form(""),
    max_tc_per_req: int = Form(5),
    report_dir: str = Form(""),
) -> Dict[str, Any]:
    """Generate STS (Software Test Specification) Excel from SRS + source code."""
    from sts_generator import generate_sts, parse_srs_docx_tables

    req_id = (request.headers.get("x-req-id") or "").strip() or f"sts-gen-{int(time.time() * 1000)}"
    _logger.info("[STS_GENERATE][%s] start source_root=%s", req_id, source_root)

    # Resolve SRS path
    srs_docx_path: Optional[str] = None
    if srs_path:
        p = Path(srs_path).expanduser().resolve()
        if p.exists() and p.is_file():
            srs_docx_path = str(p)

    # Collect requirement text from paths/uploads
    req_paths_list = _parse_path_list(req_paths)
    req_texts: List[str] = []
    req_doc_paths: List[str] = []
    sds_doc_paths: List[str] = []

    for path_str in req_paths_list:
        try:
            p = Path(path_str).expanduser().resolve()
            if p.exists() and p.is_file():
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
            pass

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
            pass

    # Fallback: auto-discover SRS from docs/ if not yet resolved
    if not srs_docx_path:
        _auto_docs = _discover_default_req_docs()
        for _auto_p in _auto_docs.get("req", []):
            if "srs" in _auto_p.lower() and _auto_p.endswith(".docx"):
                srs_docx_path = _auto_p
                _logger.info("[STS_GENERATE][%s] auto-discovered SRS: %s", req_id, srs_docx_path)
                break

    if not req_texts and not srs_docx_path:
        raise HTTPException(status_code=400, detail="SRS 문서를 최소 1개 이상 제공해주세요.")

    # Get function_details from source root
    function_details: Dict[str, Any] = {}
    source_root_path = Path(source_root).resolve() if source_root else None
    if source_root_path and source_root_path.exists() and source_root_path.is_dir():
        try:
            sections = _get_source_sections_cached(str(source_root_path))
            function_details = sections.get("function_details", {})
            function_details, req_doc_paths, sds_doc_paths = _enrich_function_details_map(
                function_details,
                function_table_rows=sections.get("function_table_rows", []),
                req_doc_paths=req_doc_paths,
                sds_doc_paths=sds_doc_paths,
            )
            _api_logger.info("[STS_GENERATE][%s] parsed %d functions from source", req_id, len(function_details))
        except Exception as e:
            print(f"[STS_GENERATE][{req_id}] source parsing warning: {e}", flush=True)

    # Resolve optional supplementary document paths
    def _resolve_opt(val: str) -> Optional[str]:
        if not val:
            return None
        p2 = Path(val).expanduser().resolve()
        return str(p2) if p2.exists() and p2.is_file() else None

    sds_docx_path = _resolve_opt(sds_path)
    # Fallback: auto-discover SDS from docs/ if not provided
    if not sds_docx_path:
        _auto_docs = _discover_default_req_docs()
        for _auto_p in _auto_docs.get("sds", []):
            sds_docx_path = _auto_p
            _logger.info("[STS_GENERATE][%s] auto-discovered SDS: %s", req_id, sds_docx_path)
            break
    uds_file_path = _resolve_opt(uds_path)
    stp_docx_path = _resolve_opt(stp_path)
    hsis_file_path = _resolve_opt(hsis_path) or _discover_hsis_path()

    # Resolve template
    tpl_path: Optional[str] = None
    if template_path:
        p = Path(template_path).expanduser().resolve()
        if p.exists() and p.is_file():
            tpl_path = str(p)

    # Output path
    base_dir = _resolve_report_dir(report_dir)
    out_filename, out_path = _build_local_excel_output(base_dir, "sts", "sts_local", tpl_path)

    project_config = {
        "project_id": project_id or "PROJECT",
        "doc_id": f"{project_id or 'PROJECT'}_STS",
        "version": version,
        "asil_level": asil_level,
        "max_tc_per_req": max_tc_per_req,
        "default_test_env": "SwTE_01",
    }

    _sts_ai_cfg = _load_sts_ai_config()

    try:
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
            hsis_path=hsis_file_path,
            ai_config=_sts_ai_cfg,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"STS 생성 실패: {e}")

    download_url = f"/api/local/sts/download/{out_filename}"
    print(f"[STS_GENERATE][{req_id}] done tc={result.get('test_case_count')} file={out_path}", flush=True)

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
        },
        output_path=str(out_path),
        filename=out_filename,
        download_url=download_url,
        preview_url=f"/api/local/sts/preview/{out_filename}",
    )
    _write_excel_artifact_sidecar(out_path, "sts", payload)
    return payload


@router.post("/api/local/sts/generate-stream")
async def local_sts_generate_stream(
    request: Request,
    source_root: str = Form(""),
    srs_path: str = Form(""),
    sds_path: str = Form(""),
    uds_path: str = Form(""),
    stp_path: str = Form(""),
    hsis_path: str = Form(""),
    req_paths: str = Form(""),
    req_files: List[UploadFile] = File(default_factory=list),
    template_path: str = Form(""),
    project_id: str = Form(""),
    version: str = Form("v1.00"),
    asil_level: str = Form(""),
    max_tc_per_req: int = Form(5),
    report_dir: str = Form(""),
):
    """Generate STS with SSE progress streaming."""
    import json as _json
    import queue
    import threading

    from sts_generator import generate_sts

    srs_docx_path: Optional[str] = None
    if srs_path:
        p = Path(srs_path).expanduser().resolve()
        if p.exists() and p.is_file():
            srs_docx_path = str(p)

    req_paths_list = _parse_path_list(req_paths)
    req_texts: List[str] = []
    req_doc_paths: List[str] = []
    sds_doc_paths: List[str] = []
    for path_str in req_paths_list:
        try:
            p = Path(path_str).expanduser().resolve()
            if p.exists() and p.is_file():
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
            pass

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
            pass

    if not req_texts and not srs_docx_path:
        raise HTTPException(status_code=400, detail="SRS 문서를 최소 1개 이상 제공해주세요.")

    function_details: Dict[str, Any] = {}
    source_root_path = Path(source_root).resolve() if source_root else None
    if source_root_path and source_root_path.exists() and source_root_path.is_dir():
        try:
            sections = _get_source_sections_cached(str(source_root_path))
            function_details = sections.get("function_details", {})
            function_details, req_doc_paths, sds_doc_paths = _enrich_function_details_map(
                function_details,
                function_table_rows=sections.get("function_table_rows", []),
                req_doc_paths=req_doc_paths,
                sds_doc_paths=sds_doc_paths,
            )
        except Exception:
            pass

    def _resolve_opt2(val: str) -> Optional[str]:
        if not val:
            return None
        p2 = Path(val).expanduser().resolve()
        return str(p2) if p2.exists() and p2.is_file() else None

    sds_docx_path = _resolve_opt2(sds_path)
    uds_file_path = _resolve_opt2(uds_path)
    stp_docx_path = _resolve_opt2(stp_path)
    hsis_file_path2 = _resolve_opt2(hsis_path) or _discover_hsis_path()

    tpl_path: Optional[str] = None
    if template_path:
        p = Path(template_path).expanduser().resolve()
        if p.exists() and p.is_file():
            tpl_path = str(p)

    base_dir = _resolve_report_dir(report_dir)
    out_filename, out_path = _build_local_excel_output(base_dir, "sts", "sts_local", tpl_path)

    project_config = {
        "project_id": project_id or "PROJECT",
        "doc_id": f"{project_id or 'PROJECT'}_STS",
        "version": version,
        "asil_level": asil_level,
        "max_tc_per_req": max_tc_per_req,
        "default_test_env": "SwTE_01",
    }

    progress_queue: queue.Queue = queue.Queue()

    def _on_progress(pct: int, msg: str):
        progress_queue.put({"type": "progress", "pct": pct, "message": msg})

    def _run():
        _sts_ai_cfg2 = _load_sts_ai_config()
        try:
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
                hsis_path=hsis_file_path2,
                ai_config=_sts_ai_cfg2,
                on_progress=_on_progress,
            )
            download_url = f"/api/local/sts/download/{out_filename}"
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
                },
                output_path=str(out_path),
                filename=out_filename,
                download_url=download_url,
                preview_url=f"/api/local/sts/preview/{out_filename}",
            )
            _write_excel_artifact_sidecar(out_path, "sts", payload)
            progress_queue.put({"type": "done", **payload})
        except Exception as e:
            progress_queue.put({"type": "error", "detail": str(e)})

    threading.Thread(target=_run, daemon=True).start()

    def _event_stream():
        while True:
            try:
                item = progress_queue.get(timeout=120)
            except queue.Empty:
                yield "data: {\"type\":\"keepalive\"}\n\n"
                continue
            yield f"data: {_json.dumps(item, ensure_ascii=False)}\n\n"
            if item.get("type") in ("done", "error"):
                break

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@router.post("/api/local/sts/generate-async")
async def local_sts_generate_async(
    request: Request,
    source_root: str = Form(""),
    srs_path: str = Form(""),
    sds_path: str = Form(""),
    uds_path: str = Form(""),
    stp_path: str = Form(""),
    hsis_path: str = Form(""),
    req_paths: str = Form(""),
    req_files: List[UploadFile] = File(default_factory=list),
    template_path: str = Form(""),
    project_id: str = Form(""),
    version: str = Form("v1.00"),
    asil_level: str = Form(""),
    max_tc_per_req: int = Form(5),
    report_dir: str = Form(""),
) -> Dict[str, Any]:
    """Non-blocking STS generation. Returns job_id for progress polling."""
    from sts_generator import generate_sts

    srs_docx_path: Optional[str] = None
    if srs_path:
        p = Path(srs_path).expanduser().resolve()
        if p.exists() and p.is_file():
            srs_docx_path = str(p)

    req_paths_list = _parse_path_list(req_paths)
    req_texts: List[str] = []
    req_doc_paths: List[str] = []
    sds_doc_paths: List[str] = []
    for path_str in req_paths_list:
        try:
            p = Path(path_str).expanduser().resolve()
            if p.exists() and p.is_file():
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
            pass

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
            pass

    # Fallback: auto-discover SRS from docs/ if not yet resolved
    if not srs_docx_path:
        _auto_docs2 = _discover_default_req_docs()
        for _auto_p2 in _auto_docs2.get("req", []):
            if "srs" in _auto_p2.lower() and _auto_p2.endswith(".docx"):
                srs_docx_path = _auto_p2
                _logger.info("[STS_GENERATE_ASYNC] auto-discovered SRS: %s", srs_docx_path)
                break

    if not req_texts and not srs_docx_path:
        raise HTTPException(status_code=400, detail="SRS 문서를 최소 1개 이상 제공해주세요.")

    job_id = uuid.uuid4().hex
    _set_progress(
        "local_sts", "local", "local",
        {"stage": "start", "percent": 1, "message": "STS 생성 준비 중", "done": False, "error": ""},
        job_id=job_id,
    )

    def _resolve_opt3(val: str) -> Optional[str]:
        if not val:
            return None
        p2 = Path(val).expanduser().resolve()
        return str(p2) if p2.exists() and p2.is_file() else None

    sds_docx_path = _resolve_opt3(sds_path)
    # Fallback: auto-discover SDS from docs/ if not provided
    if not sds_docx_path:
        _auto_docs3 = _discover_default_req_docs()
        for _auto_p3 in _auto_docs3.get("sds", []):
            sds_docx_path = _auto_p3
            _logger.info("[STS_GENERATE_ASYNC] auto-discovered SDS: %s", sds_docx_path)
            break
    uds_file_path = _resolve_opt3(uds_path)
    stp_docx_path = _resolve_opt3(stp_path)
    hsis_file_path3 = _resolve_opt3(hsis_path) or _discover_hsis_path()

    source_root_path = Path(source_root).resolve() if source_root else None
    tpl_path: Optional[str] = None
    if template_path:
        p = Path(template_path).expanduser().resolve()
        if p.exists() and p.is_file():
            tpl_path = str(p)

    base_dir = _resolve_report_dir(report_dir)
    out_filename, out_path = _build_local_excel_output(base_dir, "sts", "sts_local", tpl_path)

    project_config = {
        "project_id": project_id or "PROJECT",
        "doc_id": f"{project_id or 'PROJECT'}_STS",
        "version": version,
        "asil_level": asil_level,
        "max_tc_per_req": max_tc_per_req,
        "default_test_env": "SwTE_01",
    }

    def _sts_on_progress(pct: int, msg: str):
        _set_progress(
            "local_sts", "local", "local",
            {"stage": "generation", "percent": max(10, min(pct, 95)), "message": msg},
            job_id=job_id,
        )

    def _worker():
        try:
            _set_progress(
                "local_sts", "local", "local",
                {"stage": "source_analysis", "percent": 10, "message": "소스 코드 분석 중"},
                job_id=job_id,
            )
            function_details: Dict[str, Any] = {}
            if source_root_path and source_root_path.exists() and source_root_path.is_dir():
                try:
                    sections = _get_source_sections_cached(str(source_root_path))
                    function_details = sections.get("function_details", {})
                    function_details, req_doc_paths, sds_doc_paths = _enrich_function_details_map(
                        function_details,
                        function_table_rows=sections.get("function_table_rows", []),
                        req_doc_paths=req_doc_paths,
                        sds_doc_paths=sds_doc_paths,
                    )
                except Exception as e:
                    _logger.warning("[STS_ASYNC][%s] source parsing warning: %s", job_id, e)

            _set_progress(
                "local_sts", "local", "local",
                {"stage": "generation", "percent": 40, "message": "STS 테스트 케이스 생성 중"},
                job_id=job_id,
            )
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
                hsis_path=hsis_file_path3,
                ai_config=_load_sts_ai_config(),
                on_progress=_sts_on_progress,
            )

            download_url = f"/api/local/sts/download/{out_filename}"
            result_payload = _build_excel_artifact_payload(
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
                },
                output_path=str(out_path),
                filename=out_filename,
                download_url=download_url,
                preview_url=f"/api/local/sts/preview/{out_filename}",
            )
            _write_excel_artifact_sidecar(out_path, "sts", result_payload)
            _set_progress(
                "local_sts", "local", "local",
                {
                    "stage": "done", "percent": 100, "message": "???",
                    "done": True, "error": "",
                    "result": result_payload,
                },
                job_id=job_id,
            )
            _logger.info("[STS_ASYNC][%s] done file=%s tc=%s", job_id, out_filename, result.get("test_case_count"))

        except Exception as exc:
            tb = traceback.format_exc()
            _logger.error("[STS_ASYNC][%s] FAILED: %s\n%s", job_id, str(exc)[:500], tb)
            _set_progress(
                "local_sts", "local", "local",
                {"stage": "error", "percent": 100, "message": f"실패: {str(exc)[:300]}", "done": True, "error": str(exc)[:500]},
                job_id=job_id,
            )

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "job_id": job_id}


@router.get("/api/local/sts/progress")
def local_sts_progress(job_id: str = "") -> Dict[str, Any]:
    data = _get_progress("local_sts", "local", "local", job_id)
    return {"ok": bool(data), "progress": data}


@router.get("/api/local/sts/download/{filename}")
def local_sts_download(filename: str, report_dir: Optional[str] = None) -> FileResponse:
    file_path = _resolve_local_sts_path(report_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="STS file not found")
    media = _excel_media_type(file_path)
    return FileResponse(str(file_path), filename=file_path.name, media_type=media)


@router.get("/api/local/sts/files")
def local_sts_files(report_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    base = _resolve_report_dir(report_dir)
    sts_dir = _local_sts_dir(base)
    if not sts_dir.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for f in sorted(sts_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix.lower() in (".xlsm", ".xlsx"):
            payload = _load_excel_artifact_payload(
                f,
                "sts",
                download_url=f"/api/local/sts/download/{f.name}",
                preview_url=f"/api/local/sts/preview/{f.name}",
            )
            rows.append({
                "filename": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                "download_url": f"/api/local/sts/download/{f.name}",
                "validation_report_path": payload.get("validation_report_path", ""),
                "residual_report_path": payload.get("residual_report_path", ""),
                "summary": payload.get("summary", {}),
            })
    return rows


@router.get("/api/local/sts/preview/{filename}")
def local_sts_preview(filename: str, report_dir: Optional[str] = None, max_rows: int = 30) -> Dict[str, Any]:
    """Preview STS Excel content as JSON table data."""
    file_path = _resolve_local_sts_path(report_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="STS file not found")
    return _parse_xlsm_preview(file_path, max_rows)


@router.get("/api/local/sts/view/{filename}")
def local_sts_view(filename: str, report_dir: Optional[str] = None) -> Dict[str, Any]:
    file_path = _resolve_local_sts_path(report_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="STS file not found")
    return _load_excel_artifact_payload(
        file_path,
        "sts",
        download_url=f"/api/local/sts/download/{file_path.name}",
        preview_url=f"/api/local/sts/preview/{file_path.name}",
    )


@router.post("/api/local/suts/generate")
async def local_suts_generate(
    request: Request,
    source_root: str = Form(""),
    template_path: str = Form(""),
    project_id: str = Form(""),
    version: str = Form("v1.00"),
    asil_level: str = Form(""),
    max_sequences: int = Form(6),
    report_dir: str = Form(""),
    srs_path: str = Form(""),
    sds_path: str = Form(""),
    uds_path: str = Form(""),
    hsis_path: str = Form(""),
) -> Dict[str, Any]:
    """Generate SUTS (Software Unit Test Specification) Excel from source code."""
    from suts_generator import generate_suts

    req_id = (request.headers.get("x-req-id") or "").strip() or f"suts-gen-{int(time.time() * 1000)}"
    print(f"[SUTS_GENERATE][{req_id}] start source_root={source_root}", flush=True)

    source_root_path = Path(source_root).resolve() if source_root else None
    if not source_root_path or not source_root_path.exists() or not source_root_path.is_dir():
        raise HTTPException(status_code=400, detail="유효한 소스 코드 루트 경로를 제공해주세요.")

    tpl_path: Optional[str] = None
    if template_path:
        p = Path(template_path).expanduser().resolve()
        if p.exists() and p.is_file():
            tpl_path = str(p)

    def _resolve_doc_path(val: str) -> Optional[str]:
        if not val:
            return None
        p2 = Path(val).expanduser().resolve()
        return str(p2) if p2.exists() and p2.is_file() else None

    srs_docx = _resolve_doc_path(srs_path)
    sds_docx = _resolve_doc_path(sds_path)
    uds_file = _resolve_doc_path(uds_path)
    # Fallback: auto-discover SRS/SDS/HSIS from docs/ if not provided
    if not srs_docx:
        _suts_defaults = _discover_default_req_docs()
        for _sp in _suts_defaults.get("req", []):
            if "srs" in _sp.lower() and _sp.endswith(".docx"):
                srs_docx = _sp
                break
    if not sds_docx:
        _suts_defaults = _discover_default_req_docs()
        for _sp in _suts_defaults.get("sds", []):
            sds_docx = _sp
            break
    hsis_suts = _resolve_doc_path(hsis_path) or _discover_hsis_path()

    base_dir = _resolve_report_dir(report_dir)
    out_filename, out_path = _build_local_excel_output(base_dir, "suts", "suts_local", tpl_path)

    project_config = {
        "project_id": project_id or "PROJECT",
        "doc_id": f"{project_id or 'PROJECT'}-SUTS",
        "version": version,
        "asil_level": asil_level,
    }

    try:
        result = generate_suts(
            source_root=str(source_root_path),
            output_path=str(out_path),
            template_path=tpl_path,
            project_config=project_config,
            max_sequences=max_sequences,
            srs_docx_path=srs_docx,
            sds_docx_path=sds_docx,
            uds_path=uds_file,
            hsis_path=hsis_suts,
            ai_config=_load_sts_ai_config(),
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"SUTS 생성 실패: {e}")

    download_url = f"/api/local/suts/download/{out_filename}"
    print(f"[SUTS_GENERATE][{req_id}] done tc={result.get('test_case_count')} file={out_path}", flush=True)

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
        },
        output_path=str(out_path),
        filename=out_filename,
        download_url=download_url,
        preview_url=f"/api/local/suts/preview/{out_filename}",
    )
    _write_excel_artifact_sidecar(out_path, "suts", payload)
    return payload


@router.post("/api/local/suts/generate-stream")
async def local_suts_generate_stream(
    request: Request,
    source_root: str = Form(""),
    template_path: str = Form(""),
    project_id: str = Form(""),
    version: str = Form("v1.00"),
    asil_level: str = Form(""),
    max_sequences: int = Form(6),
    report_dir: str = Form(""),
    srs_path: str = Form(""),
    sds_path: str = Form(""),
    uds_path: str = Form(""),
    hsis_path: str = Form(""),
):
    """Generate SUTS with SSE progress streaming."""
    import json as _json
    import queue
    import threading

    from suts_generator import generate_suts

    source_root_path = Path(source_root).resolve() if source_root else None
    if not source_root_path or not source_root_path.exists() or not source_root_path.is_dir():
        raise HTTPException(status_code=400, detail="유효한 소스 코드 루트 경로를 제공해주세요.")

    tpl_path: Optional[str] = None
    if template_path:
        p = Path(template_path).expanduser().resolve()
        if p.exists() and p.is_file():
            tpl_path = str(p)

    def _res_doc(val: str) -> Optional[str]:
        if not val:
            return None
        p2 = Path(val).expanduser().resolve()
        return str(p2) if p2.exists() and p2.is_file() else None

    srs_docx_stream = _res_doc(srs_path)
    sds_docx_stream = _res_doc(sds_path)
    uds_file_stream = _res_doc(uds_path)
    # Fallback: auto-discover SRS/SDS/HSIS from docs/ if not provided
    if not srs_docx_stream:
        _suts_defs2 = _discover_default_req_docs()
        for _sp2 in _suts_defs2.get("req", []):
            if "srs" in _sp2.lower() and _sp2.endswith(".docx"):
                srs_docx_stream = _sp2
                break
    if not sds_docx_stream:
        _suts_defs2 = _discover_default_req_docs()
        for _sp2 in _suts_defs2.get("sds", []):
            sds_docx_stream = _sp2
            break
    hsis_suts_stream = _res_doc(hsis_path) or _discover_hsis_path()

    base_dir = _resolve_report_dir(report_dir)
    out_filename, out_path = _build_local_excel_output(base_dir, "suts", "suts_local", tpl_path)

    project_config = {
        "project_id": project_id or "PROJECT",
        "doc_id": f"{project_id or 'PROJECT'}-SUTS",
        "version": version,
        "asil_level": asil_level,
    }

    progress_queue: queue.Queue = queue.Queue()

    def _on_progress(pct: int, msg: str):
        progress_queue.put({"type": "progress", "pct": pct, "message": msg})

    def _run():
        try:
            result = generate_suts(
                source_root=str(source_root_path),
                output_path=str(out_path),
                template_path=tpl_path,
                project_config=project_config,
                max_sequences=max_sequences,
                on_progress=_on_progress,
                srs_docx_path=srs_docx_stream,
                sds_docx_path=sds_docx_stream,
                uds_path=uds_file_stream,
                hsis_path=hsis_suts_stream,
                ai_config=_load_sts_ai_config(),
            )
            download_url = f"/api/local/suts/download/{out_filename}"
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
                },
                output_path=str(out_path),
                filename=out_filename,
                download_url=download_url,
                preview_url=f"/api/local/suts/preview/{out_filename}",
            )
            _write_excel_artifact_sidecar(out_path, "suts", payload)
            progress_queue.put({"type": "done", **payload})
        except Exception as e:
            progress_queue.put({"type": "error", "detail": str(e)})

    threading.Thread(target=_run, daemon=True).start()

    def _event_stream():
        while True:
            try:
                item = progress_queue.get(timeout=120)
            except queue.Empty:
                yield "data: {\"type\":\"keepalive\"}\n\n"
                continue
            yield f"data: {_json.dumps(item, ensure_ascii=False)}\n\n"
            if item.get("type") in ("done", "error"):
                break

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@router.post("/api/local/suts/generate-async")
async def local_suts_generate_async(
    request: Request,
    source_root: str = Form(""),
    template_path: str = Form(""),
    project_id: str = Form(""),
    version: str = Form("v1.00"),
    asil_level: str = Form(""),
    max_sequences: int = Form(6),
    report_dir: str = Form(""),
    srs_path: str = Form(""),
    sds_path: str = Form(""),
    uds_path: str = Form(""),
    hsis_path: str = Form(""),
) -> Dict[str, Any]:
    """Non-blocking SUTS generation. Returns job_id for progress polling."""
    from suts_generator import generate_suts

    source_root_path = Path(source_root).resolve() if source_root else None
    if not source_root_path or not source_root_path.exists() or not source_root_path.is_dir():
        raise HTTPException(status_code=400, detail="유효한 소스 코드 루트 경로를 제공해주세요.")

    job_id = uuid.uuid4().hex
    _set_progress(
        "local_suts", "local", "local",
        {"stage": "start", "percent": 1, "message": "SUTS 생성 준비 중", "done": False, "error": ""},
        job_id=job_id,
    )

    tpl_path: Optional[str] = None
    if template_path:
        p = Path(template_path).expanduser().resolve()
        if p.exists() and p.is_file():
            tpl_path = str(p)

    def _res_async(val: str) -> Optional[str]:
        if not val:
            return None
        p2 = Path(val).expanduser().resolve()
        return str(p2) if p2.exists() and p2.is_file() else None

    srs_docx_async = _res_async(srs_path)
    sds_docx_async = _res_async(sds_path)
    uds_file_async = _res_async(uds_path)
    hsis_suts_async = _res_async(hsis_path) or _discover_hsis_path()

    base_dir = _resolve_report_dir(report_dir)
    out_filename, out_path = _build_local_excel_output(base_dir, "suts", "suts_local", tpl_path)

    project_config = {
        "project_id": project_id or "PROJECT",
        "doc_id": f"{project_id or 'PROJECT'}-SUTS",
        "version": version,
        "asil_level": asil_level,
    }

    def _suts_on_progress(pct: int, msg: str):
        stage = "source_analysis" if pct < 30 else "generation"
        _set_progress(
            "local_suts", "local", "local",
            {"stage": stage, "percent": max(10, min(pct, 95)), "message": msg},
            job_id=job_id,
        )

    def _worker():
        try:
            _set_progress(
                "local_suts", "local", "local",
                {"stage": "source_analysis", "percent": 5, "message": "소스 코드 분석 시작"},
                job_id=job_id,
            )
            _logger.info("[SUTS_ASYNC][%s] calling generate_suts ...", job_id)
            result = generate_suts(
                source_root=str(source_root_path),
                output_path=str(out_path),
                template_path=tpl_path,
                project_config=project_config,
                max_sequences=max_sequences,
                on_progress=_suts_on_progress,
                srs_docx_path=srs_docx_async,
                sds_docx_path=sds_docx_async,
                uds_path=uds_file_async,
                hsis_path=hsis_suts_async,
                ai_config=_load_sts_ai_config(),
            )
            _logger.info("[SUTS_ASYNC][%s] generate_suts returned, setting done", job_id)

            download_url = f"/api/local/suts/download/{out_filename}"
            result_payload = _build_excel_artifact_payload(
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
                },
                output_path=str(out_path),
                filename=out_filename,
                download_url=download_url,
                preview_url=f"/api/local/suts/preview/{out_filename}",
            )
            _write_excel_artifact_sidecar(out_path, "suts", result_payload)
            _set_progress(
                "local_suts", "local", "local",
                {
                    "stage": "done", "percent": 100, "message": "???",
                    "done": True, "error": "",
                    "result": result_payload,
                },
                job_id=job_id,
            )
            _logger.info("[SUTS_ASYNC][%s] done file=%s tc=%s", job_id, out_filename, result.get("test_case_count"))

        except Exception as exc:
            tb = traceback.format_exc()
            _logger.error("[SUTS_ASYNC][%s] FAILED: %s\n%s", job_id, str(exc)[:500], tb)
            _set_progress(
                "local_suts", "local", "local",
                {"stage": "error", "percent": 100, "message": f"실패: {str(exc)[:300]}", "done": True, "error": str(exc)[:500]},
                job_id=job_id,
            )

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "job_id": job_id}


@router.get("/api/local/suts/progress")
def local_suts_progress(job_id: str = "") -> Dict[str, Any]:
    data = _get_progress("local_suts", "local", "local", job_id)
    return {"ok": bool(data), "progress": data}


@router.get("/api/local/suts/download/{filename}")
def local_suts_download(filename: str, report_dir: Optional[str] = None) -> FileResponse:
    file_path = _resolve_local_suts_path(report_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="SUTS file not found")
    media = _excel_media_type(file_path)
    return FileResponse(str(file_path), filename=file_path.name, media_type=media)


@router.get("/api/local/suts/files")
def local_suts_files(report_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    base = _resolve_report_dir(report_dir)
    suts_dir = _local_suts_dir(base)
    if not suts_dir.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for f in sorted(suts_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix.lower() in (".xlsm", ".xlsx"):
            payload = _load_excel_artifact_payload(
                f,
                "suts",
                download_url=f"/api/local/suts/download/{f.name}",
                preview_url=f"/api/local/suts/preview/{f.name}",
            )
            rows.append({
                "filename": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                "download_url": f"/api/local/suts/download/{f.name}",
                "validation_report_path": payload.get("validation_report_path", ""),
                "residual_report_path": payload.get("residual_report_path", ""),
                "summary": payload.get("summary", {}),
            })
    return rows


@router.get("/api/local/suts/preview/{filename}")
def local_suts_preview(filename: str, report_dir: Optional[str] = None, max_rows: int = 30) -> Dict[str, Any]:
    """Preview SUTS Excel content as JSON table data."""
    file_path = _resolve_local_suts_path(report_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="SUTS file not found")
    return _parse_xlsm_preview(file_path, max_rows)


@router.get("/api/local/suts/view/{filename}")
def local_suts_view(filename: str, report_dir: Optional[str] = None) -> Dict[str, Any]:
    file_path = _resolve_local_suts_path(report_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="SUTS file not found")
    return _load_excel_artifact_payload(
        file_path,
        "suts",
        download_url=f"/api/local/suts/download/{file_path.name}",
        preview_url=f"/api/local/suts/preview/{file_path.name}",
    )


@router.post("/api/local/sits/generate")
async def local_sits_generate(
    request: Request,
    source_root: str = Form(""),
    template_path: str = Form(""),
    project_id: str = Form(""),
    version: str = Form("v1.00"),
    asil_level: str = Form(""),
    max_subcases: int = Form(7),
    report_dir: str = Form(""),
    srs_path: str = Form(""),
    sds_path: str = Form(""),
    uds_path: str = Form(""),
    hsis_path: str = Form(""),
    stp_path: str = Form(""),
) -> Dict[str, Any]:
    """Generate SITS (Software Integration Test Specification) Excel from source code."""
    from sits_generator import generate_sits

    req_id = (request.headers.get("x-req-id") or "").strip() or f"sits-gen-{int(time.time() * 1000)}"
    print(f"[SITS_GENERATE][{req_id}] start source_root={source_root}", flush=True)

    source_root_path = Path(source_root).resolve() if source_root else None
    if not source_root_path or not source_root_path.exists() or not source_root_path.is_dir():
        raise HTTPException(status_code=400, detail="유효한 소스 코드 루트 경로를 제공해주세요.")

    tpl_path: Optional[str] = None
    if template_path:
        p = Path(template_path).expanduser().resolve()
        if p.exists() and p.is_file():
            tpl_path = str(p)

    def _resolve_doc_path_sits(val: str) -> Optional[str]:
        if not val:
            return None
        p2 = Path(val).expanduser().resolve()
        return str(p2) if p2.exists() and p2.is_file() else None

    srs_docx = _resolve_doc_path_sits(srs_path)
    sds_docx = _resolve_doc_path_sits(sds_path)
    uds_file = _resolve_doc_path_sits(uds_path)
    hsis_file = _resolve_doc_path_sits(hsis_path) or _discover_hsis_path()
    stp_file = _resolve_doc_path_sits(stp_path)

    base_dir = _resolve_report_dir(report_dir)
    out_filename, out_path = _build_local_excel_output(base_dir, "sits", "sits_local", tpl_path)

    project_config = {
        "project_id": project_id or "PROJECT",
        "doc_id": f"{project_id or 'PROJECT'}-SITS",
        "version": version,
        "asil_level": asil_level,
    }

    try:
        result = generate_sits(
            source_root=str(source_root_path),
            output_path=str(out_path),
            template_path=tpl_path,
            project_config=project_config,
            max_subcases=max_subcases,
            srs_docx_path=srs_docx,
            sds_docx_path=sds_docx,
            uds_path=uds_file,
            hsis_path=hsis_file,
            stp_path=stp_file,
            ai_config=_load_sts_ai_config(),
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"SITS 생성 실패: {e}")

    download_url = f"/api/local/sits/download/{out_filename}"
    print(f"[SITS_GENERATE][{req_id}] done tc={result.get('test_case_count')} file={out_path}", flush=True)

    payload = _build_excel_artifact_payload(
        "sits",
        {
            "ok": True,
            "output_path": str(out_path),
            "filename": out_filename,
            "download_url": download_url,
            "test_case_count": result.get("test_case_count", 0),
            "elapsed_seconds": result.get("elapsed_seconds", 0),
            "quality_report": result.get("quality_report", {}),
            "validation": result.get("validation", {}),
            "validation_report_path": result.get("validation_report_path", ""),
        },
        output_path=str(out_path),
        filename=out_filename,
        download_url=download_url,
        preview_url=f"/api/local/sits/preview/{out_filename}",
    )
    _write_excel_artifact_sidecar(out_path, "sits", payload)
    return payload


@router.post("/api/local/sits/generate-stream")
async def local_sits_generate_stream(
    request: Request,
    source_root: str = Form(""),
    template_path: str = Form(""),
    project_id: str = Form(""),
    version: str = Form("v1.00"),
    asil_level: str = Form(""),
    max_subcases: int = Form(7),
    report_dir: str = Form(""),
    srs_path: str = Form(""),
    sds_path: str = Form(""),
    uds_path: str = Form(""),
    hsis_path: str = Form(""),
    stp_path: str = Form(""),
):
    """Generate SITS with SSE progress streaming."""
    import json as _json
    import queue
    import threading

    from sits_generator import generate_sits

    source_root_path = Path(source_root).resolve() if source_root else None
    if not source_root_path or not source_root_path.exists() or not source_root_path.is_dir():
        raise HTTPException(status_code=400, detail="유효한 소스 코드 루트 경로를 제공해주세요.")

    tpl_path: Optional[str] = None
    if template_path:
        p = Path(template_path).expanduser().resolve()
        if p.exists() and p.is_file():
            tpl_path = str(p)

    def _res_doc_sits(val: str) -> Optional[str]:
        if not val:
            return None
        p2 = Path(val).expanduser().resolve()
        return str(p2) if p2.exists() and p2.is_file() else None

    srs_docx_stream = _res_doc_sits(srs_path)
    sds_docx_stream = _res_doc_sits(sds_path)
    uds_file_stream = _res_doc_sits(uds_path)
    hsis_stream = _res_doc_sits(hsis_path) or _discover_hsis_path()
    stp_stream = _res_doc_sits(stp_path)

    base_dir = _resolve_report_dir(report_dir)
    out_filename, out_path = _build_local_excel_output(base_dir, "sits", "sits_local", tpl_path)

    project_config = {
        "project_id": project_id or "PROJECT",
        "doc_id": f"{project_id or 'PROJECT'}-SITS",
        "version": version,
        "asil_level": asil_level,
    }

    progress_queue: queue.Queue = queue.Queue()

    def _on_progress(pct: int, msg: str):
        progress_queue.put({"type": "progress", "pct": pct, "message": msg})

    def _run():
        try:
            result = generate_sits(
                source_root=str(source_root_path),
                output_path=str(out_path),
                template_path=tpl_path,
                project_config=project_config,
                max_subcases=max_subcases,
                on_progress=_on_progress,
                srs_docx_path=srs_docx_stream,
                sds_docx_path=sds_docx_stream,
                uds_path=uds_file_stream,
                hsis_path=hsis_stream,
                stp_path=stp_stream,
                ai_config=_load_sts_ai_config(),
            )
            download_url = f"/api/local/sits/download/{out_filename}"
            payload = _build_excel_artifact_payload(
                "sits",
                {
                    "ok": True,
                    "output_path": str(out_path),
                    "filename": out_filename,
                    "download_url": download_url,
                    "test_case_count": result.get("test_case_count", 0),
                    "elapsed_seconds": result.get("elapsed_seconds", 0),
                    "quality_report": result.get("quality_report", {}),
                    "validation": result.get("validation", {}),
                    "validation_report_path": result.get("validation_report_path", ""),
                },
                output_path=str(out_path),
                filename=out_filename,
                download_url=download_url,
                preview_url=f"/api/local/sits/preview/{out_filename}",
            )
            _write_excel_artifact_sidecar(out_path, "sits", payload)
            progress_queue.put({"type": "done", **payload})
        except Exception as e:
            progress_queue.put({"type": "error", "detail": str(e)})

    threading.Thread(target=_run, daemon=True).start()

    def _event_stream():
        while True:
            try:
                item = progress_queue.get(timeout=120)
            except queue.Empty:
                yield "data: {\"type\":\"keepalive\"}\n\n"
                continue
            yield f"data: {_json.dumps(item, ensure_ascii=False)}\n\n"
            if item.get("type") in ("done", "error"):
                break

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@router.post("/api/local/sits/generate-async")
async def local_sits_generate_async(
    request: Request,
    source_root: str = Form(""),
    template_path: str = Form(""),
    project_id: str = Form(""),
    version: str = Form("v1.00"),
    asil_level: str = Form(""),
    max_subcases: int = Form(7),
    report_dir: str = Form(""),
    srs_path: str = Form(""),
    sds_path: str = Form(""),
    uds_path: str = Form(""),
    hsis_path: str = Form(""),
    stp_path: str = Form(""),
) -> Dict[str, Any]:
    """Non-blocking SITS generation. Returns job_id for progress polling."""
    from sits_generator import generate_sits

    source_root_path = Path(source_root).resolve() if source_root else None
    if not source_root_path or not source_root_path.exists() or not source_root_path.is_dir():
        raise HTTPException(status_code=400, detail="유효한 소스 코드 루트 경로를 제공해주세요.")

    job_id = uuid.uuid4().hex
    _set_progress(
        "local_sits", "local", "local",
        {"stage": "start", "percent": 1, "message": "SITS 생성 준비 중", "done": False, "error": ""},
        job_id=job_id,
    )

    tpl_path: Optional[str] = None
    if template_path:
        p = Path(template_path).expanduser().resolve()
        if p.exists() and p.is_file():
            tpl_path = str(p)

    def _res_async_sits(val: str) -> Optional[str]:
        if not val:
            return None
        p2 = Path(val).expanduser().resolve()
        return str(p2) if p2.exists() and p2.is_file() else None

    srs_docx_async = _res_async_sits(srs_path)
    sds_docx_async = _res_async_sits(sds_path)
    uds_file_async = _res_async_sits(uds_path)
    hsis_async = _res_async_sits(hsis_path) or _discover_hsis_path()
    stp_async = _res_async_sits(stp_path)

    base_dir = _resolve_report_dir(report_dir)
    out_filename, out_path = _build_local_excel_output(base_dir, "sits", "sits_local", tpl_path)

    project_config = {
        "project_id": project_id or "PROJECT",
        "doc_id": f"{project_id or 'PROJECT'}-SITS",
        "version": version,
        "asil_level": asil_level,
    }

    def _sits_on_progress(pct: int, msg: str):
        stage = "source_analysis" if pct < 30 else "generation"
        _set_progress(
            "local_sits", "local", "local",
            {"stage": stage, "percent": max(10, min(pct, 95)), "message": msg},
            job_id=job_id,
        )

    def _worker():
        try:
            _set_progress(
                "local_sits", "local", "local",
                {"stage": "source_analysis", "percent": 5, "message": "소스 코드 분석 시작"},
                job_id=job_id,
            )
            _logger.info("[SITS_ASYNC][%s] calling generate_sits ...", job_id)
            result = generate_sits(
                source_root=str(source_root_path),
                output_path=str(out_path),
                template_path=tpl_path,
                project_config=project_config,
                max_subcases=max_subcases,
                on_progress=_sits_on_progress,
                srs_docx_path=srs_docx_async,
                sds_docx_path=sds_docx_async,
                uds_path=uds_file_async,
                hsis_path=hsis_async,
                stp_path=stp_async,
                ai_config=_load_sts_ai_config(),
            )
            _logger.info("[SITS_ASYNC][%s] generate_sits returned, setting done", job_id)

            download_url = f"/api/local/sits/download/{out_filename}"
            result_payload = _build_excel_artifact_payload(
                "sits",
                {
                    "ok": True,
                    "output_path": str(out_path),
                    "filename": out_filename,
                    "download_url": download_url,
                    "test_case_count": result.get("test_case_count", 0),
                    "elapsed_seconds": result.get("elapsed_seconds", 0),
                    "quality_report": result.get("quality_report", {}),
                    "validation": result.get("validation", {}),
                    "validation_report_path": result.get("validation_report_path", ""),
                },
                output_path=str(out_path),
                filename=out_filename,
                download_url=download_url,
                preview_url=f"/api/local/sits/preview/{out_filename}",
            )
            _write_excel_artifact_sidecar(out_path, "sits", result_payload)
            _set_progress(
                "local_sits", "local", "local",
                {
                    "stage": "done", "percent": 100, "message": "완료",
                    "done": True, "error": "",
                    "result": result_payload,
                },
                job_id=job_id,
            )
            _logger.info("[SITS_ASYNC][%s] done file=%s tc=%s", job_id, out_filename, result.get("test_case_count"))

        except Exception as exc:
            tb = traceback.format_exc()
            _logger.error("[SITS_ASYNC][%s] FAILED: %s\n%s", job_id, str(exc)[:500], tb)
            _set_progress(
                "local_sits", "local", "local",
                {"stage": "error", "percent": 100, "message": f"실패: {str(exc)[:300]}", "done": True, "error": str(exc)[:500]},
                job_id=job_id,
            )

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "job_id": job_id}


@router.get("/api/local/sits/progress")
def local_sits_progress(job_id: str = "") -> Dict[str, Any]:
    data = _get_progress("local_sits", "local", "local", job_id)
    return {"ok": bool(data), "progress": data}


@router.get("/api/local/sits/download/{filename}")
def local_sits_download(filename: str, report_dir: Optional[str] = None) -> FileResponse:
    file_path = _resolve_local_sits_path(report_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="SITS file not found")
    media = _excel_media_type(file_path)
    return FileResponse(str(file_path), filename=file_path.name, media_type=media)


@router.get("/api/local/sits/files")
def local_sits_files(report_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    base = _resolve_report_dir(report_dir)
    sits_dir = _local_sits_dir(base)
    if not sits_dir.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for f in sorted(sits_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix.lower() in (".xlsm", ".xlsx"):
            payload = _load_excel_artifact_payload(
                f,
                "sits",
                download_url=f"/api/local/sits/download/{f.name}",
                preview_url=f"/api/local/sits/preview/{f.name}",
            )
            rows.append({
                "filename": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                "download_url": f"/api/local/sits/download/{f.name}",
                "validation_report_path": payload.get("validation_report_path", ""),
                "residual_report_path": payload.get("residual_report_path", ""),
                "summary": payload.get("summary", {}),
            })
    return rows


@router.get("/api/local/sits/preview/{filename}")
def local_sits_preview(filename: str, report_dir: Optional[str] = None, max_rows: int = 30) -> Dict[str, Any]:
    """Preview SITS Excel content as JSON table data."""
    file_path = _resolve_local_sits_path(report_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="SITS file not found")
    return _parse_xlsm_preview(file_path, max_rows)


@router.get("/api/local/sits/view/{filename}")
def local_sits_view(filename: str, report_dir: Optional[str] = None) -> Dict[str, Any]:
    file_path = _resolve_local_sits_path(report_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="SITS file not found")
    return _load_excel_artifact_payload(
        file_path,
        "sits",
        download_url=f"/api/local/sits/download/{file_path.name}",
        preview_url=f"/api/local/sits/preview/{file_path.name}",
    )


@router.post("/api/local/suts/export-vectorcast")
def local_suts_export_vectorcast(
    filename: str = Form(""),
    report_dir: str = Form(""),
    source_root: str = Form(""),
    project_id: str = Form(""),
    compiler: str = Form("CC"),
) -> Dict[str, Any]:
    """Generate a VectorCAST unit-test package from a SUTS file."""
    from tools.export_suts_vectorcast import export_suts_to_vectorcast_model
    from tools.export_vectorcast_script import export_vectorcast_package

    base_dir = _resolve_report_dir(report_dir)
    suts_dir = _local_suts_dir(base_dir)
    if filename:
        xlsm_path = suts_dir / filename
    else:
        candidates = sorted(suts_dir.glob("*.xlsm"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise HTTPException(status_code=404, detail="No SUTS file found")
        xlsm_path = candidates[0]
    if not xlsm_path.exists():
        raise HTTPException(status_code=404, detail="SUTS file not found")

    resolved_source_root = str(source_root or "").strip()
    cfg = load_vectorcast_project_config(project_id=project_id, source_root=resolved_source_root)
    effective_project_id = str(project_id or cfg.get("project_id") or "VECTORCAST").strip()
    effective_source_root = resolved_source_root or str(cfg.get("source_root") or "").strip()

    resolved_source_root = str(source_root or "").strip()
    cfg = load_vectorcast_project_config(project_id=project_id, source_root=resolved_source_root)
    effective_source_root = resolved_source_root or str(cfg.get("source_root") or "").strip()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    package_name = f"suts_vectorcast_{ts}"
    out_dir = base_dir / "vectorcast" / package_name
    out_dir.mkdir(parents=True, exist_ok=True)
    intermediate_json = out_dir / "suts_vectorcast_model.json"
    warnings_md = out_dir / "suts_vectorcast_warnings.md"

    try:
        model = export_suts_to_vectorcast_model(
            str(xlsm_path),
            str(intermediate_json),
            warnings_md=str(warnings_md),
            project_id=effective_project_id,
        )
        manifest = export_vectorcast_package(
            str(intermediate_json),
            str(out_dir),
            package_name=package_name,
            source_root=effective_source_root,
            compiler=str(cfg.get("compiler") or compiler or "CC"),
            project_config=cfg,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"VectorCAST package generation failed: {e}")

    unit_names = [str(unit.get("unit_name") or "") for unit in model.get("units") or []]
    return _build_vectorcast_package_response(
        package_dir=out_dir,
        package_name=package_name,
        manifest=manifest,
        project_config=cfg,
        units=unit_names,
    )


@router.post("/api/local/sits/export-vectorcast")
def local_sits_export_vectorcast(
    filename: str = Form(""),
    report_dir: str = Form(""),
    source_root: str = Form(""),
    project_id: str = Form(""),
    compiler: str = Form("CC"),
) -> Dict[str, Any]:
    """Generate a VectorCAST integration test package from a SITS file."""
    from tools.export_sits_vectorcast_package import export_sits_vectorcast_package

    base_dir = _resolve_report_dir(report_dir)
    sits_dir = _local_sits_dir(base_dir)

    # Locate intermediate JSON (generated alongside the XLSM by generate_sits)
    if filename:
        xlsm_path = sits_dir / filename
    else:
        # latest XLSM in sits dir
        candidates = sorted(sits_dir.glob("*.xlsm"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise HTTPException(status_code=404, detail="No SITS file found")
        xlsm_path = candidates[0]

    stem = xlsm_path.stem
    intermediate_json = xlsm_path.with_name(f"{stem}_vectorcast.json")
    if not intermediate_json.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Intermediate JSON not found: {intermediate_json.name}. Re-generate the SITS file first.",
        )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    package_name = f"sits_vectorcast_{ts}"
    out_dir = base_dir / "vectorcast" / package_name

    try:
        model = json.loads(intermediate_json.read_text(encoding="utf-8"))
        manifest = export_sits_vectorcast_package(
            str(intermediate_json),
            str(out_dir),
            package_name=package_name,
            source_root=effective_source_root,
            compiler=str(cfg.get("compiler") or compiler or "CC"),
            project_config=cfg,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"VectorCAST 패키지 생성 실패: {e}")

    unit_names = sorted(
        {
            str(step.split(".", 1)[0]).strip()
            for item in (model.get("integrations") or [])
            for step in str(item.get("call_chain") or "").split("->")
            if str(step).strip()
        }
    )
    return _build_vectorcast_package_response(
        package_dir=out_dir,
        package_name=package_name,
        manifest=manifest,
        project_config=cfg,
        units=unit_names,
    )


@router.post("/api/local/scm")
def local_scm(req: ScmRequest) -> Dict[str, Any]:
    if req.mode.lower() == "git":
        return run_git(
            project_root=req.project_root,
            workdir_rel=req.workdir_rel,
            action=req.action,
            repo_url=req.repo_url,
            branch=req.branch,
            depth=req.depth,
            timeout_sec=req.timeout_sec,
        )
    if req.mode.lower() == "svn":
        return run_svn(
            project_root=req.project_root,
            workdir_rel=req.workdir_rel,
            action=req.action,
            repo_url=req.repo_url,
            revision=req.revision,
            timeout_sec=req.timeout_sec,
        )
    raise HTTPException(status_code=400, detail="unknown scm mode")


@router.post("/api/local/impact/trigger")
def local_impact_trigger(req: LocalImpactTriggerRequest) -> Dict[str, Any]:
    try:
        trigger = build_registry_trigger(
            trigger_type="local",
            scm_id=req.scm_id,
            base_ref=req.base_ref,
            dry_run=req.dry_run,
            auto_generate=req.auto_generate,
            targets=req.targets or None,
            manual_changed_files=req.manual_changed_files or None,
            metadata={"source": "api/local/impact/trigger"},
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="registry entry not found")
    return run_impact_update(trigger)


@router.post("/api/local/impact/trigger-async")
def local_impact_trigger_async(req: LocalImpactTriggerRequest) -> Dict[str, Any]:
    try:
        trigger = build_registry_trigger(
            trigger_type="local",
            scm_id=req.scm_id,
            base_ref=req.base_ref,
            dry_run=req.dry_run,
            auto_generate=req.auto_generate,
            targets=req.targets or None,
            manual_changed_files=req.manual_changed_files or None,
            metadata={"source": "api/local/impact/trigger-async"},
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="registry entry not found")
    return start_impact_job(trigger)


@router.post("/api/local/kb/list")
def local_kb_list(req: KBRequest) -> Dict[str, Any]:
    return {"entries": list_kb_entries(req.project_root, req.report_dir)}


@router.post("/api/local/kb/delete")
def local_kb_delete(req: KBRequest) -> Dict[str, Any]:
    if not req.entry_key:
        raise HTTPException(status_code=400, detail="entry_key required")
    ok, msg = delete_kb_entry(req.entry_key, req.project_root, req.report_dir)
    return {"ok": ok, "message": msg}


@router.post("/api/local/editor/read")
def local_editor_read(req: EditorReadRequest) -> Dict[str, Any]:
    return read_file_text(req.project_root, req.rel_path, req.max_bytes)


@router.post("/api/local/editor/write")
def local_editor_write(req: EditorWriteRequest) -> Dict[str, Any]:
    return write_file_text(req.project_root, req.rel_path, req.content, req.make_backup)


@router.post("/api/local/editor/replace")
def local_editor_replace(req: EditorReplaceRequest) -> Dict[str, Any]:
    return replace_lines(req.project_root, req.rel_path, req.start_line, req.end_line, req.content)


@router.post("/api/local/format-c")
def local_format_c(req: FormatCodeRequest) -> Dict[str, Any]:
    return format_c_code(req.text, req.filename)


@router.post("/api/local/rag/status")
def local_rag_status(req: RagStatusRequest) -> Dict[str, Any]:
    cfg = req.config or {}
    report_dir = str(req.report_dir or cfg.get("report_dir") or getattr(config, "DEFAULT_REPORT_DIR", "reports"))
    report_path = (repo_root / report_dir).resolve()
    report_path.mkdir(parents=True, exist_ok=True)
    force_pg = bool(getattr(config, "FORCE_PGVECTOR", False))
    force_pg_strict = bool(getattr(config, "FORCE_PGVECTOR_STRICT", False))
    try:
        kb = get_kb(report_path)
        storage = str(getattr(kb, "storage", "sqlite"))
        pg_ok = bool(getattr(kb, "_pg_ok", False))
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "kb_storage": "pgvector" if force_pg else str(getattr(config, "KB_STORAGE", "sqlite")),
            "pgvector_forced": force_pg,
            "pgvector_strict": force_pg_strict,
            "pgvector_ready": False,
            "kb_dir": str(report_path / getattr(config, "KB_DIR_NAME", "kb_store")),
        }
    dsn = str(os.environ.get("PGVECTOR_DSN", "") or getattr(config, "PGVECTOR_DSN", ""))
    url = str(os.environ.get("PGVECTOR_URL", "") or getattr(config, "PGVECTOR_URL", ""))
    stats = {}
    try:
        stats = kb.stats()
    except Exception:
        stats = {}
    return {
        "ok": True,
        "rag_ingest_enable": bool(cfg.get("rag_ingest_enable", getattr(config, "RAG_INGEST_ENABLE", True))),
        "rag_ingest_on_pipeline": bool(cfg.get("rag_ingest_on_pipeline", getattr(config, "RAG_INGEST_ON_PIPELINE", True))),
        "agent_rag": bool(cfg.get("agent_rag", getattr(config, "AGENT_RAG_ENABLED_DEFAULT", True))),
        "kb_storage": storage,
        "pgvector_forced": force_pg,
        "pgvector_strict": force_pg_strict,
        "pgvector_configured": bool(dsn or url),
        "pgvector_ready": pg_ok if storage == "pgvector" else False,
        "kb_dir": str(report_path / getattr(config, "KB_DIR_NAME", "kb_store")),
        "stats": stats,
    }


@router.post("/api/local/rag/ingest")
def local_rag_ingest(req: RagIngestRequest) -> Dict[str, Any]:
    cfg = req.config or {}
    report_dir = str(req.report_dir or cfg.get("report_dir") or getattr(config, "DEFAULT_REPORT_DIR", "reports"))
    report_path = (repo_root / report_dir).resolve()
    report_path.mkdir(parents=True, exist_ok=True)
    kb = get_kb(report_path)
    result = ingest_external_sources(kb, cfg=cfg)
    return {"ok": True, "result": result}


@router.post("/api/local/rag/ingest-files")
async def local_rag_ingest_files(
    files: List[UploadFile] = File(default_factory=list),
    category: str = Form("general"),
    tags: str = Form(""),
    report_dir: str = Form(""),
    chunk_size: Optional[int] = Form(None),
    chunk_overlap: Optional[int] = Form(None),
    max_chunks: Optional[int] = Form(None),
) -> Dict[str, Any]:
    report_dir = str(report_dir or getattr(config, "DEFAULT_REPORT_DIR", "reports"))
    report_path = (repo_root / report_dir).resolve()
    report_path.mkdir(parents=True, exist_ok=True)
    kb = get_kb(report_path)
    tag_list = [t.strip() for t in re.split(r"[,\n;]+", str(tags or "")) if t.strip()]
    use_chunk_size = int(chunk_size or getattr(config, "RAG_CHUNK_SIZE", 1200))
    use_overlap = int(chunk_overlap or getattr(config, "RAG_CHUNK_OVERLAP", 200))
    use_max_chunks = int(max_chunks or getattr(config, "RAG_INGEST_MAX_CHUNKS_PER_FILE", 12))

    added = 0
    skipped = 0
    for f in files:
        if not f or not f.filename:
            continue
        suffix = Path(f.filename).suffix.lower() or ".txt"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await f.read())
            tmp_path = Path(tmp.name)
        try:
            chunks = _read_and_chunk_file(
                tmp_path,
                chunk_size=use_chunk_size,
                overlap=use_overlap,
                max_chunks=use_max_chunks,
            )
        except Exception:
            chunks = []
        if not chunks:
            skipped += 1
            continue
        for i, ch in enumerate(chunks):
            title = f"{category}:{Path(f.filename).name}#{i+1}"
            kb.add_document(
                title=title,
                content=ch,
                category=str(category or "general"),
                tags=tag_list,
                source_file=str(f.filename),
            )
            added += 1
    return {"ok": True, "added": added, "skipped": skipped, "category": category}


@router.post("/api/local/rag/use-pgvector")
def local_rag_use_pgvector(req: RagStorageRequest) -> Dict[str, Any]:
    dsn = str(req.pgvector_dsn or "").strip()
    url = str(req.pgvector_url or "").strip()
    if not dsn and not url:
        raise HTTPException(status_code=400, detail="pgvector dsn or url required")
    os.environ["KB_STORAGE"] = "pgvector"
    os.environ["PGVECTOR_DSN"] = dsn
    os.environ["PGVECTOR_URL"] = url
    config.KB_STORAGE = "pgvector"
    config.PGVECTOR_DSN = dsn
    config.PGVECTOR_URL = url
    config.FORCE_PGVECTOR = True
    config.FORCE_PGVECTOR_STRICT = True
    report_dir = str(req.report_dir or getattr(config, "DEFAULT_REPORT_DIR", "reports"))
    report_path = (repo_root / report_dir).resolve()
    report_path.mkdir(parents=True, exist_ok=True)
    try:
        kb = get_kb(report_path)
        pg_ok = bool(getattr(kb, "_pg_ok", False))
        return {
            "ok": pg_ok,
            "kb_storage": str(getattr(kb, "storage", "pgvector")),
            "pgvector_ready": pg_ok,
        }
    except Exception as e:
        return {
            "ok": False,
            "kb_storage": "pgvector",
            "pgvector_ready": False,
            "error": str(e),
            "hint": "pgvector 확장/권한/DSN 설정을 확인하세요 (CREATE EXTENSION vector;)",
        }


@router.post("/api/local/rag/query")
def local_rag_query(req: RagQueryRequest) -> Dict[str, Any]:
    query = str(req.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query required")
    cfg = req.config or {}
    report_dir = str(req.report_dir or cfg.get("report_dir") or getattr(config, "DEFAULT_REPORT_DIR", "reports"))
    report_path = (repo_root / report_dir).resolve()
    report_path.mkdir(parents=True, exist_ok=True)
    kb = get_kb(report_path)
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


@router.post("/api/local/pick-directory")
def api_pick_directory(req: PickerRequest) -> Dict[str, Any]:
    path, error = pick_directory(req.title or "폴더 선택")
    return {"ok": bool(path), "path": path, "error": error or None}


@router.post("/api/local/pick-file")
def api_pick_file(req: PickerRequest) -> Dict[str, Any]:
    path, error = pick_file(req.title or "파일 선택")
    return {"ok": bool(path), "path": path, "error": error or None}


@router.post("/api/local/open-file")
def api_open_file(req: OpenFileRequest) -> Dict[str, Any]:
    if not req.path:
        raise HTTPException(status_code=400, detail="path required")
    target = Path(req.path).expanduser().resolve()
    allowed_roots = [
        (Path.home() / ".devops_pro_cache").resolve(),
        repo_root.resolve(),
    ]
    if not is_under_any(target, allowed_roots):
        raise HTTPException(status_code=403, detail="path not allowed")
    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="file not found")
    try:
        _open_local_path(target)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "path": str(target)}


@router.post("/api/local/editor/read-abs")
def local_editor_read_abs(req: EditorReadAbsRequest) -> Dict[str, Any]:
    if not req.path:
        raise HTTPException(status_code=400, detail="path required")
    target = Path(req.path).expanduser().resolve()
    allowed_roots = [
        (Path.home() / ".devops_pro_cache").resolve(),
        repo_root.resolve(),
    ]
    if not is_under_any(target, allowed_roots):
        raise HTTPException(status_code=403, detail="path not allowed")
    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="file not found")
    text, truncated = read_text_limited(target, req.max_bytes)
    return {"ok": True, "path": str(target), "text": text, "truncated": truncated}


@router.post("/api/local/preview-text")
def local_preview_text(req: TextPreviewRequest) -> Dict[str, Any]:
    if not req.path:
        raise HTTPException(status_code=400, detail="path required")
    target = Path(req.path).expanduser().resolve()
    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="file not found")
    if not _is_allowed_req_doc(target):
        raise HTTPException(status_code=400, detail="unsupported file type")
    text = _read_text_from_file(target)
    max_chars = max(1000, int(req.max_chars or 0))
    truncated = False
    if max_chars and len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    return {"ok": True, "path": str(target), "text": text, "truncated": truncated}


@router.post("/api/local/sds/view")
def local_sds_view(req: SdsViewRequest) -> Dict[str, Any]:
    if not req.path:
        raise HTTPException(status_code=400, detail="path required")
    target = Path(req.path).expanduser().resolve()
    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="file not found")
    if target.suffix.lower() != ".docx":
        raise HTTPException(status_code=400, detail="SDS view supports .docx only")
    if not _is_allowed_req_doc(target):
        raise HTTPException(status_code=400, detail="unsupported file type")
    try:
        view = build_sds_view_model(
            str(target),
            max_items=max(1, int(req.max_items or 500)),
            changed_functions=dict(req.changed_functions or {}),
            changed_files=list(req.changed_files or []),
            flagged_modules=list(req.flagged_modules or []),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "view": view}


@router.post("/api/local/open-folder")
def api_open_folder(req: OpenFolderRequest) -> Dict[str, Any]:
    if not req.path:
        raise HTTPException(status_code=400, detail="path required")
    target = Path(req.path).expanduser().resolve()
    allowed_roots = [
        (Path.home() / ".devops_pro_cache").resolve(),
        repo_root.resolve(),
    ]
    if not is_under_any(target, allowed_roots):
        raise HTTPException(status_code=403, detail="path not allowed")
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="folder not found")
    try:
        _open_local_path(target)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "path": str(target)}


@router.post("/api/local/preflight")
def local_preflight(req: PreflightRequest) -> Dict[str, Any]:
    cfg = dict(req.config or {})
    resolved, root = _resolve_source_root_from_cfg(cfg, req.project_root)
    extra_paths = _collect_tool_paths()
    original_path = os.environ.get("PATH", "")
    os.environ["PATH"] = _augment_path(original_path, extra_paths)
    try:
        preflight = _build_preflight(cfg)
    finally:
        os.environ["PATH"] = original_path
    root_ok = Path(root).expanduser().resolve().exists()
    if not root_ok:
        preflight["warnings"].append("project_root_not_found")
    ready = root_ok and not preflight.get("missing")
    return {
        "ok": True,
        "ready": ready,
        "resolved": resolved,
        "project_root": root,
        "preflight": preflight,
    }


@router.post("/api/local/list-dir")
def api_list_dir(req: ListDirRequest) -> Dict[str, Any]:
    return list_directory(req.project_root, req.rel_path)


@router.post("/api/local/search")
def api_search(req: SearchRequest) -> Dict[str, Any]:
    return search_in_files(req.project_root, req.rel_path, req.query, req.max_results)


@router.post("/api/local/replace-text")
def api_replace_text(req: ReplaceTextRequest) -> Dict[str, Any]:
    return replace_in_file(req.project_root, req.rel_path, req.search, req.replace)


@router.post("/api/local/git/status")
def api_git_status(req: GitRequest) -> Dict[str, Any]:
    return git_status(req.project_root, req.workdir_rel)


@router.post("/api/local/git/diff")
def api_git_diff(req: GitRequest) -> Dict[str, Any]:
    return git_diff(req.project_root, req.workdir_rel, req.staged, req.path)


@router.post("/api/local/git/log")
def api_git_log(req: GitRequest) -> Dict[str, Any]:
    return git_log(req.project_root, req.workdir_rel, req.max_count)


@router.post("/api/local/git/branches")
def api_git_branches(req: GitRequest) -> Dict[str, Any]:
    return git_branches(req.project_root, req.workdir_rel)


@router.post("/api/local/git/checkout")
def api_git_checkout(req: GitRequest) -> Dict[str, Any]:
    return git_checkout(req.project_root, req.workdir_rel, req.branch)


@router.post("/api/local/git/create-branch")
def api_git_create_branch(req: GitRequest) -> Dict[str, Any]:
    return git_create_branch(req.project_root, req.workdir_rel, req.branch)


@router.post("/api/local/git/stage")
def api_git_stage(req: GitRequest) -> Dict[str, Any]:
    return git_stage(req.project_root, req.workdir_rel, req.paths)


@router.post("/api/local/git/unstage")
def api_git_unstage(req: GitRequest) -> Dict[str, Any]:
    return git_unstage(req.project_root, req.workdir_rel, req.paths)


@router.post("/api/local/git/commit")
def api_git_commit(req: GitRequest) -> Dict[str, Any]:
    return git_commit(req.project_root, req.workdir_rel, req.message)
