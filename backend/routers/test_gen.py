"""Auto-generated router: test_gen"""
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import FileResponse, HTMLResponse
from typing import Any, Dict, List, Optional
import json
import re
import traceback
import logging
from pathlib import Path

from backend.schemas import (
    TestGenerateRequest,
)
from backend.helpers import _build_test_cases_for_signature, _get_source_sections_cached, _safe_int


router = APIRouter()
_logger = logging.getLogger("devops_api")

@router.post("/api/test/generate")
def test_generate(req: TestGenerateRequest) -> Dict[str, Any]:
    fn_name = str(req.target_function or "").strip()
    if not fn_name:
        raise HTTPException(status_code=400, detail="target_function required")
    max_cases = _safe_int(req.max_cases, default=20, low=1, high=200)
    sections = _get_source_sections_cached(req.source_root, max_files=1200)
    by_name = (
        sections.get("function_details_by_name")
        if isinstance(sections.get("function_details_by_name"), dict)
        else {}
    )
    info = by_name.get(fn_name.lower()) if isinstance(by_name, dict) else None
    if not isinstance(info, dict):
        raise HTTPException(status_code=404, detail="target function not found")
    signature = str(info.get("signature") or "").strip()
    cases = _build_test_cases_for_signature(
        function_name=fn_name,
        signature=signature,
        strategy=req.strategy,
        max_cases=max_cases,
    )
    lines = [
        f"// Auto-generated test scaffold for {fn_name}",
        f"// strategy: {req.strategy}",
        "",
        f"void test_{re.sub(r'[^a-zA-Z0-9_]', '_', fn_name)}(void) {{",
        "  // TODO: setup",
    ]
    for row in cases[: min(10, len(cases))]:
        lines.append(f"  // case: {row.get('name')} inputs={json.dumps(row.get('inputs') or {}, ensure_ascii=False)}")
    lines += [
        "  // TODO: call function and assert",
        "}",
    ]
    return {
        "ok": True,
        "target_function": fn_name,
        "strategy": str(req.strategy or "boundary"),
        "signature": signature,
        "cases": cases,
        "test_code": "\n".join(lines),
    }


