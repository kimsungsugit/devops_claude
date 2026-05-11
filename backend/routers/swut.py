"""SwUT (Software Unit Test) 빌더 endpoint (8차 라운드 T141).

Coverage Report / SUTR xlsx 파일을 frontend / curl에서 호출 가능하도록 노출.

## 설계
- **동기 호출 + Semaphore(2)** (사용자 의사결정): 빌드 시간 ~5초 (template-only) ~ 60초 (실데이터),
  메모리 4x 폭증 위험으로 동시 호출 2건 제한.
- **응답**: xlsx 파일 bytes (Content-Disposition attachment). summary/warnings는 X-* 헤더로 분리.
- **인증**: `X-User` 헤더 필수 (UserContextMiddleware 외 빌더 단에서도 검증).

## Endpoint
- ``POST /api/swut/coverage/build`` — Coverage Report v3.01 xlsx
- ``POST /api/swut/sutr/build`` — SUTR v3.01 xlsm
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from backend.schemas import SwUTBuildRequest
from backend.services.file_resolver import get_resolver
from backend.services.swut_coverage_aggregator import (
    CoverageBuildMeta,
    build_coverage_report,
)
from backend.services.swut_input_adapter import collect_swut_session
from backend.services.swut_sutr_aggregator import SutrBuildMeta, build_sutr

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/swut", tags=["swut"])

# T142: Semaphore(2) — 동시 호출 2건 제한 (메모리 4x × 2 = 안전 한도).
# 운영 후 메모리 모니터링 보고 조정. asyncio.Semaphore는 동일 event loop 내에서만 작동.
_BUILD_SEMAPHORE = asyncio.Semaphore(2)


def _ensure_x_user(request: Request) -> str:
    user = request.headers.get("X-User", "").strip()
    if not user:
        raise HTTPException(status_code=400, detail="X-User header required")
    return user


def _load_meta_from_config(project_id: str) -> dict[str, Any]:
    """config/swut_meta.json 에서 project별 fixed 메타 로드."""
    import os
    cfg_path = "config/swut_meta.json"
    if not os.path.isfile(cfg_path):
        return {}
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("projects", {}).get(project_id, {}) or {}
    except (OSError, json.JSONDecodeError) as e:
        _logger.warning("swut_meta.json load failed: %s", e)
        return {}


def _build_coverage_meta(req: SwUTBuildRequest) -> CoverageBuildMeta:
    cfg = _load_meta_from_config(req.project_id)
    return CoverageBuildMeta(
        project_id=req.project_id,
        project_full_name=cfg.get("project_full_name", req.project_id),
        asil_level=cfg.get("asil_level", req.asil_level),
        doc_id_base=cfg.get("doc_id_base", ""),
        doc_id_sequence=req.doc_id_sequence,
        default_author=cfg.get("approvers", {}).get("default_author", ""),
        default_reviewer=cfg.get("approvers", {}).get("default_reviewer", ""),
        default_approver=cfg.get("approvers", {}).get("default_approver", ""),
        release_sw_version=req.release_sw_version,
        hw_version=req.hw_version,
        test_date=req.test_date,
        test_engineer=req.test_engineer,
        validation_date=req.validation_date,
        reviewer_override=req.reviewer_override,
        approver_override=req.approver_override,
    )


def _build_sutr_meta(req: SwUTBuildRequest) -> SutrBuildMeta:
    cfg = _load_meta_from_config(req.project_id)
    return SutrBuildMeta(
        project_id=req.project_id,
        project_full_name=cfg.get("project_full_name", req.project_id),
        asil_level=cfg.get("asil_level", req.asil_level),
        doc_id_base=cfg.get("doc_id_base", "HDPDM01-SUTR"),
        doc_id_sequence=req.doc_id_sequence,
        default_author=cfg.get("approvers", {}).get("default_author", ""),
        default_reviewer=cfg.get("approvers", {}).get("default_reviewer", ""),
        default_approver=cfg.get("approvers", {}).get("default_approver", ""),
        release_sw_version=req.release_sw_version,
        hw_version=req.hw_version,
        test_date=req.test_date,
        test_engineer=req.test_engineer,
        validation_date=req.validation_date,
        reviewer_override=req.reviewer_override,
        approver_override=req.approver_override,
    )


def _read_template_bytes(template_path: str, project_id: str, kind: str) -> bytes:
    """template_path 명시되면 그 path에서, 아니면 config의 template path에서 read."""
    resolver = get_resolver()
    if template_path:
        return resolver.read_bytes(template_path)
    cfg = _load_meta_from_config(project_id)
    tmpl_cfg = cfg.get("template_paths", {})
    key = "coverage_report_template" if kind == "coverage" else "sutr_template"
    tpath = tmpl_cfg.get(key, "")
    if not tpath:
        raise HTTPException(
            status_code=400,
            detail=f"template_path 미지정 + config에 '{key}' 없음 ({project_id})",
        )
    return resolver.read_bytes(tpath)


def _build_result_to_response(
    *, content: bytes, filename: str, summary: dict[str, Any],
    warnings: list[str], incomplete_sheets: list[str],
    media_type: str,
) -> Response:
    """xlsx/xlsm bytes를 attachment Response로 변환.

    summary / warnings / incomplete_sheets는 X-* 헤더로 노출. HTTP 헤더는 latin-1만
    허용하므로 한글 등 비-ASCII는 ``ensure_ascii=True`` 로 ``\\uXXXX`` escape 후 송신.
    Frontend는 ``JSON.parse`` 로 decode 가능. filename도 RFC 5987 ``filename*=UTF-8`` 사용.
    """
    from urllib.parse import quote

    # 파일명은 latin-1 안전 ASCII fallback + UTF-8 quoted variant (RFC 5987).
    ascii_filename = filename.encode("ascii", errors="replace").decode("ascii")
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_filename}"; '
            f"filename*=UTF-8''{quote(filename)}"
        ),
        "X-SwUT-Summary": json.dumps(summary, ensure_ascii=True)[:1024],
        "X-SwUT-Warnings": json.dumps(warnings, ensure_ascii=True)[:1024],
        "X-SwUT-Incomplete-Sheets": ",".join(incomplete_sheets).encode(
            "ascii", errors="replace",
        ).decode("ascii")[:512],
    }
    return Response(content=content, media_type=media_type, headers=headers)


def _do_coverage_build(req: SwUTBuildRequest) -> Response:
    resolver = get_resolver()
    session = collect_swut_session(
        resolver, req.project_id,
        jenkins_build_number=req.jenkins_build_number,
        cache_root=req.cache_root,
        log_folder=req.log_folder,
    )
    template_bytes = _read_template_bytes(req.template_path, req.project_id, "coverage")
    meta = _build_coverage_meta(req)
    result = build_coverage_report(session, meta, template_bytes)
    if not result.ok:
        raise HTTPException(status_code=500, detail="빌드 실패 (ok=False)")
    return _build_result_to_response(
        content=result.xlsx_bytes,
        filename=result.filename,
        summary=result.summary,
        warnings=result.warnings,
        incomplete_sheets=result.incomplete_sheets,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )


def _do_sutr_build(req: SwUTBuildRequest) -> Response:
    resolver = get_resolver()
    session = collect_swut_session(
        resolver, req.project_id,
        jenkins_build_number=req.jenkins_build_number,
        cache_root=req.cache_root,
        log_folder=req.log_folder,
    )
    template_bytes = _read_template_bytes(req.template_path, req.project_id, "sutr")
    meta = _build_sutr_meta(req)
    result = build_sutr(session, meta, template_bytes, deviation_cases=req.deviation_cases)
    if not result.ok:
        raise HTTPException(status_code=500, detail="빌드 실패 (ok=False)")
    return _build_result_to_response(
        content=result.xlsm_bytes,
        filename=result.filename,
        summary=result.summary,
        warnings=result.warnings,
        incomplete_sheets=result.incomplete_sheets,
        media_type="application/vnd.ms-excel.sheet.macroenabled.12",
    )


@router.post("/coverage/build")
async def build_coverage(req: SwUTBuildRequest, request: Request) -> Response:
    """Coverage Report v3.01 xlsx 빌드. Semaphore(2)로 동시 호출 제한."""
    _ensure_x_user(request)
    async with _BUILD_SEMAPHORE:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do_coverage_build, req)


@router.post("/sutr/build")
async def build_sutr_endpoint(req: SwUTBuildRequest, request: Request) -> Response:
    """SUTR v3.01 xlsm 빌드 (keep_vba=True). Semaphore(2)로 동시 호출 제한."""
    _ensure_x_user(request)
    async with _BUILD_SEMAPHORE:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do_sutr_build, req)
