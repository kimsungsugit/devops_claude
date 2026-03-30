"""Auto-generated router: impact"""
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import FileResponse, HTMLResponse
from typing import Any, Dict, List, Optional
import json
import re
import subprocess
import sys
import traceback
import logging
import uuid
from pathlib import Path
from datetime import datetime

from backend.schemas import (
    ImpactAnalyzeRequest,
)

repo_root = Path(__file__).resolve().parents[2]

router = APIRouter()
_logger = logging.getLogger("devops_api")

@router.post("/api/impact/analyze")
def impact_analyze(req: ImpactAnalyzeRequest) -> Dict[str, Any]:
    source_root = Path(str(req.source_root or "")).expanduser().resolve()
    if not source_root.exists() or not source_root.is_dir():
        raise HTTPException(status_code=400, detail="source_root not found or not directory")
    changed_rows = [str(x).strip() for x in (req.changed_files or []) if str(x).strip()]
    if not changed_rows and str(req.changed_raw or "").strip():
        changed_rows = [x.strip() for x in re.split(r"[\n,;]+", str(req.changed_raw)) if x.strip()]
    if not changed_rows:
        raise HTTPException(status_code=400, detail="changed_files or changed_raw required")
    out_dir = repo_root / "reports" / "uds"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / f"impact_analysis_api_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.md"
    cmd = [
        sys.executable,
        str(repo_root / "tools" / "impact_analysis.py"),
        "--source-root",
        str(source_root),
        "--changed",
        ",".join(changed_rows),
        "--out",
        str(out_md),
    ]
    run = subprocess.run(
        cmd,
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    out_json = out_md.with_suffix(".json")
    if run.returncode != 0:
        err = ((run.stderr or "") + "\n" + (run.stdout or "")).strip()[-3000:]
        raise HTTPException(status_code=500, detail=f"impact analyze failed: {err}")
    if not out_json.exists():
        raise HTTPException(status_code=500, detail="impact json output not found")
    try:
        data = json.loads(out_json.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"impact json parse failed: {exc}")
    return {
        "ok": True,
        "result": data,
        "report_path": str(out_md),
        "json_path": str(out_json),
    }


