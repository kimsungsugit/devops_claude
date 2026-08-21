"""Auto-generated router: exports"""
import logging
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.error_handler import APIError
from backend.helpers import (
    _exports_dir,
    _invalidate_session_cache,
    _load_session_meta,
    _resolve_base_dir,
    _resolve_export_path,
    _safe_extract_zip,
    _save_session_meta,
    _session_dir,
)
from backend.services.paths import confine

router = APIRouter()
_logger = logging.getLogger("devops_api")


# ── PDF export models ──────────────────────────────────────────────
class PdfConvertRequest(BaseModel):
    source_path: str
    output_path: Optional[str] = None
    sheet_name: Optional[str] = None


class PdfSection(BaseModel):
    heading: str = ""
    content: Any = ""


class PdfReportRequest(BaseModel):
    title: str
    sections: List[PdfSection]
    output_path: str
    subtitle: str = ""


# ── PDF export endpoints ───────────────────────────────────────────
@router.post("/api/exports/pdf/convert")
def convert_to_pdf(req: PdfConvertRequest) -> Dict[str, Any]:
    """Convert DOCX or XLSX file to PDF.

    Automatically selects converter based on file extension.
    """
    from backend.services.pdf_converter import docx_to_pdf, xlsx_to_pdf

    # ⚠ `source_path` 는 **봉인하지 않는다**. 요구문서·산출물은 저장소 밖에 사는 것이
    #   이 앱의 설계다(`_is_allowed_req_doc` 이 확장자만 보는 이유). 읽기를 여기서만
    #   좁히면 정상 사용이 깨지고 다른 읽기 경로와도 어긋난다.
    #   **쓰기는 다르다** — 산출물을 임의 위치에 떨궈도 되는 근거가 이 저장소엔 없고,
    #   `local_editor_write` 는 이미 같은 루트로 잠겨 있다. `output_path` 만 봉인한다.
    source = Path(req.source_path)
    output = confine(req.output_path, what="output_path") if req.output_path else None
    ext = source.suffix.lower()

    try:
        if ext == ".docx":
            result = docx_to_pdf(source, output)
        elif ext in (".xlsx", ".xls"):
            result = xlsx_to_pdf(source, output, sheet_name=req.sheet_name)
        else:
            raise APIError(
                status_code=400,
                message=f"Unsupported file type: {ext}. Use .docx or .xlsx",
                code="UNSUPPORTED_FILE_TYPE",
            )
    except FileNotFoundError as exc:
        raise APIError(status_code=404, message=str(exc), code="FILE_NOT_FOUND")
    except APIError:
        raise
    except RuntimeError as exc:
        raise APIError(status_code=500, message=str(exc), code="CONVERSION_ERROR")
    except Exception:
        _logger.error("PDF conversion failed:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="PDF 변환 중 오류 발생")

    return {
        "ok": True,
        "pdf_path": str(result),
        "size_mb": round(result.stat().st_size / (1024 * 1024), 2),
    }


@router.post("/api/exports/pdf/report")
def generate_pdf_report(req: PdfReportRequest) -> Dict[str, Any]:
    """Generate a structured PDF report from provided sections."""
    from backend.services.pdf_converter import generate_report_pdf

    sections = [s.model_dump() for s in req.sections]

    # ⚠ 여기는 **경로도 내용도** 클라이언트가 정한다(`output_path` + `title`/`sections`).
    #   봉인이 없으면 임의 위치에 임의 내용의 파일을 만들 수 있다. 봉인은 try 밖에서 —
    #   안에 두면 아래 `except Exception` 이 403 을 500 으로 바꾼다.
    pdf_path = confine(req.output_path, what="output_path")

    try:
        result = generate_report_pdf(
            title=req.title,
            sections=sections,
            pdf_path=pdf_path,
            subtitle=req.subtitle,
        )
    except Exception:
        _logger.error("PDF report generation failed:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="PDF 리포트 생성 중 오류 발생")

    return {
        "ok": True,
        "pdf_path": str(result),
        "size_mb": round(result.stat().st_size / (1024 * 1024), 2),
    }

@router.get("/api/exports")
def list_exports(
    base: Optional[str] = None,
    session_id: Optional[str] = Query(default=None),
) -> List[Dict[str, Any]]:
    base_dir = _resolve_base_dir(base)
    exports = _exports_dir(str(base_dir))
    if not exports.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for p in exports.glob("session_*.zip"):
        if session_id and session_id not in p.name:
            continue
        rows.append(
            {
                "file": p.name,
                "path": str(p),
                "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                "download_url": f"/api/exports/download/{p.name}",
            }
        )
    rows.sort(key=lambda x: x.get("mtime") or "", reverse=True)
    return rows


@router.delete("/api/exports/{filename}")
def delete_export(filename: str, base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    export_path = _resolve_export_path(base_dir, filename)
    if not export_path.exists():
        raise HTTPException(status_code=404, detail="export not found")
    export_path.unlink()
    return {"ok": True, "file": filename}


@router.post("/api/exports/restore/{filename}")
def restore_export(filename: str, base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    export_path = _resolve_export_path(base_dir, filename)
    if not export_path.exists():
        raise HTTPException(status_code=404, detail="export not found")

    session_id = uuid.uuid4().hex[:8]
    session_dir = _session_dir(str(base_dir), session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    file_count = _safe_extract_zip(export_path, session_dir)

    meta = _load_session_meta(session_dir)
    if not meta:
        meta = {"name": f"restored_{session_id}"}
    meta["last_opened"] = datetime.now().isoformat(timespec="seconds")
    _save_session_meta(session_dir, meta)
    _invalidate_session_cache(base_dir)

    return {
        "ok": True,
        "session_id": session_id,
        "name": meta.get("name"),
        "restored_files": file_count,
    }


@router.get("/api/exports/download/{filename}")
def download_export(filename: str, base: Optional[str] = None) -> FileResponse:
    base_dir = _resolve_base_dir(base)
    export_path = _resolve_export_path(base_dir, filename)
    if not export_path.exists():
        raise HTTPException(status_code=404, detail="export not found")
    return FileResponse(export_path, filename=export_path.name, media_type="application/zip")


@router.post("/api/exports/cleanup")
def cleanup_exports(days: int = Query(default=30, ge=1), base: Optional[str] = None) -> Dict[str, Any]:
    base_dir = _resolve_base_dir(base)
    exports = _exports_dir(str(base_dir))
    if not exports.exists():
        return {"deleted": 0}
    cutoff = datetime.now().timestamp() - (days * 86400)
    deleted = 0
    for p in exports.glob("session_*.zip"):
        if p.stat().st_mtime < cutoff:
            p.unlink()
            deleted += 1
    return {"deleted": deleted}


