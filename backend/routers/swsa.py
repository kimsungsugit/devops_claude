"""SwSA(Software Static Analysis Report) 빌드 라우터.

POST /api/swsa/report/build — 로그 폴더 + 템플릿 경로 + 메타만으로 자동 빌드.
SwUT/SwIT 라우터 패턴(Semaphore + Response + X-* 헤더 + run_build_safely) 재사용.

흐름: get_resolver → collect_swsa_inputs(로그 자동 발견/파싱/병합) →
template read → build_swsa_report → Response(xlsm).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from backend.dependencies.admin import require_admin
from backend.routers._safety import run_build_safely
from backend.schemas import SwSABuildRequest
from backend.services.file_resolver import get_resolver
from backend.services.path_mode_check import check_log_folder_mode_compat
from backend.services.swsa_aggregator import build_swsa_report
from backend.services.swsa_input_adapter import collect_swsa_inputs
from backend.services.swsa_meta import SwsaBuildMeta

_logger = logging.getLogger("devops_api")

# SwUT/SwIT(40차)와 동일 — 라우터 전체 admin only. ASIL evidence 생성 + 임의 경로
# read 방지 (local 모드는 미들웨어 우회 가능 → endpoint gate 가 유일 방어선).
router = APIRouter(prefix="/api/swsa", tags=["swsa"], dependencies=[Depends(require_admin)])

# SwIT 와 동일 보수적 시작 (신규 도구). worst-case 측정 후 상향 검토.
_BUILD_SEMAPHORE = asyncio.Semaphore(2)

_MEDIA_XLSM = "application/vnd.ms-excel.sheet.macroEnabled.12"
_HEADER_LIMIT = 1024


def _build_meta(req: SwSABuildRequest) -> SwsaBuildMeta:
    return SwsaBuildMeta(
        project_id=req.project_id,
        asil_level=req.asil_level,
        doc_id_base=req.doc_id_base,
        doc_id_sequence=req.doc_id_sequence,
        doc_version=req.doc_version,
        doc_status=req.doc_status,
        test_date=req.test_date,
        test_engineer=req.test_engineer,
        release_sw_version=req.release_sw_version,
        validation_date=req.validation_date,
        reviewer_override=req.reviewer_override,
        approver_override=req.approver_override,
        phase=req.phase,
        platform_version=req.platform_version,
        product=req.product,
        verification_target=req.verification_target,
        compiler=req.compiler,
        mcu=req.mcu,
        history_description=req.history_description,
        analysis_round=req.analysis_round,
        debugger=req.debugger,
        misra_rule_version=req.misra_rule_version,
        secure_rule_version=req.secure_rule_version,
    )


def _read_template_bytes(req: SwSABuildRequest) -> bytes:
    resolver = get_resolver()
    if req.template_path:
        return resolver.read_bytes(req.template_path)
    raise HTTPException(status_code=400, detail="template_path 미지정 (SwSA 양식 경로 필요)")


def _json_header(obj: Any) -> str:
    """HTTP 헤더용 JSON. 헤더는 latin-1 만 허용 → ensure_ascii=True (한글 \\uXXXX 이스케이프).
    1024B 초과 시 안전 축약 (JSON valid 유지)."""
    value = json.dumps(obj, ensure_ascii=True)
    if len(value.encode("latin-1", errors="replace")) <= _HEADER_LIMIT:
        return value
    return json.dumps({"truncated": True, "len": len(value)}, ensure_ascii=True)


def _to_response(res: Any, meta: SwsaBuildMeta, inputs: Any) -> Response:
    data = res.xlsm_io.getvalue()
    filename = f"({meta.project_id}_SwSA) Software Static Analysis Report_{meta.doc_version}_{meta.test_date}.xlsm"
    # CR/LF 는 valid ASCII 라 encode(replace)로 안 걸러짐 → 헤더 인젝션/500(h11) 방지 위해 제거
    ascii_name = (
        filename.encode("ascii", errors="replace").decode("ascii")
        .replace('"', "_").replace("\r", " ").replace("\n", " ")
    )

    summary = {
        "sheets_filled": res.sheets_filled,
        "filled_cells": res.filled_cells,
        "user_input_cells": res.user_input_cells,
        "vba_preserved": res.vba_preserved,
        "modules": getattr(inputs, "modules", []),
        "logs_discovered": getattr(getattr(inputs, "log_set", None), "total", 0),
    }
    warnings = list(res.warnings) + list(getattr(inputs, "warnings", []))
    headers = {
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}",
        "Content-Length": str(len(data)),
        "X-SwSA-Summary": _json_header(summary),
        "X-SwSA-Warnings": _json_header(warnings[:20]),
    }
    return Response(content=data, media_type=_MEDIA_XLSM, headers=headers)


def _do_build(req: SwSABuildRequest) -> Response:
    resolver = get_resolver()
    log_folder = req.log_folder.strip()
    if log_folder:
        # local/cloudium 모드 ↔ 경로 형식 불일치 사전 진단 (swit 대칭, UX + UNC 차단)
        check_log_folder_mode_compat(log_folder, resolver)
    inputs = collect_swsa_inputs(resolver, log_folder) if log_folder else None
    template_bytes = _read_template_bytes(req)
    meta = _build_meta(req)
    res = build_swsa_report(
        template_bytes, meta,
        qac_xml=getattr(inputs, "qac_xml", None),
        st201=getattr(inputs, "st201", None),
        pmd=getattr(inputs, "pmd", None),
    )
    return _to_response(res, meta, inputs)


@router.post("/report/build")
async def build_swsa_report_endpoint(req: SwSABuildRequest) -> Response:
    """SwSA 보고서 자동 빌드 (xlsm, keep_vba). Semaphore(2)로 동시 제한."""
    async with _BUILD_SEMAPHORE:
        return await asyncio.to_thread(
            run_build_safely,
            series="swsa", kind="report", build_fn=_do_build, req=req, logger=_logger,
        )
