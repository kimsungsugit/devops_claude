"""SwUT (Software Unit Test) 빌더 endpoint (8차/12차 라운드).

Coverage Report / SUTR xlsx 파일을 frontend / curl에서 호출 가능하도록 노출.

## 설계
- **동기 호출 + Semaphore(2)** (사용자 의사결정): 빌드 시간 ~5초 (template-only) ~ 60초 (실데이터),
  메모리 4x 폭증 위험으로 동시 호출 2건 제한.
- **응답**: xlsx 파일 bytes (Content-Disposition attachment). summary/warnings는 X-* 헤더로 분리.
- **인증**: ``UserContextMiddleware`` 가 ``X-User`` 검증 후 ``request.state`` 에 user 주입.
  endpoint에서는 ``get_current_user()`` 로 가져와 logging 용.

## Endpoint
- ``POST /api/swut/coverage/build`` — Coverage Report v3.01 xlsx
- ``POST /api/swut/sutr/build`` — SUTR v3.01 xlsm

## 12차 라운드 개선
- C2: ``_load_meta_from_config`` lru_cache + mtime 기반 invalidate
- W4: builder exception try/except — sanitize + ``logger.exception`` traceback 보존
- W5: ``asyncio.to_thread`` 마이그레이션 (deprecated ``get_event_loop`` 제거)
- W6: ``_ensure_x_user`` dead code 제거 — middleware가 이미 401
"""
from __future__ import annotations

import asyncio
import functools
import io
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse

from backend.schemas import SwUTBuildRequest
from backend.services.file_resolver import get_resolver
from backend.services.swut_coverage_aggregator import (
    CoverageBuildMeta,
    build_coverage_report,
)
from backend.services.swut_input_adapter import collect_swut_session
from backend.services.swut_sutr_aggregator import SutrBuildMeta, build_sutr
from backend.services.swut_swuds_parser import parse_swuds_docx
from backend.user_context import get_current_user

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/swut", tags=["swut"])

_BUILD_SEMAPHORE = asyncio.Semaphore(2)

_META_CONFIG_PATH = "config/swut_meta.json"


@functools.lru_cache(maxsize=1)
def _read_meta_config_raw(mtime: float) -> dict[str, Any]:  # noqa: ARG001
    """lru_cache key = mtime. config 파일 수정 시 자동 cache miss → reload.

    ``mtime`` 인자는 본문에서 사용하지 않지만 ``functools.lru_cache`` 의 hash key 역할.
    호출자가 ``os.path.getmtime()`` 으로 전달하면 파일 수정 시 자동 invalidate.
    """
    if not os.path.isfile(_META_CONFIG_PATH):
        return {}
    try:
        with open(_META_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, json.JSONDecodeError) as e:
        _logger.warning("swut_meta.json load failed: %s", e)
        return {}


def _load_meta_from_config(project_id: str) -> dict[str, Any]:
    """config/swut_meta.json 에서 project별 fixed 메타 로드 — mtime 기반 캐시."""
    try:
        mtime = os.path.getmtime(_META_CONFIG_PATH)
    except OSError:
        return {}
    cfg = _read_meta_config_raw(mtime)
    return cfg.get("projects", {}).get(project_id, {}) or {}


def _build_coverage_meta(req: SwUTBuildRequest) -> CoverageBuildMeta:
    cfg = _load_meta_from_config(req.project_id)
    approvers = cfg.get("approvers", {}) or {}
    return CoverageBuildMeta(
        project_id=req.project_id,
        project_full_name=cfg.get("project_full_name", req.project_id),
        asil_level=cfg.get("asil_level", req.asil_level),
        doc_id_base=cfg.get("doc_id_base", ""),
        doc_id_sequence=req.doc_id_sequence,
        default_author=approvers.get("default_author", ""),
        default_reviewer=approvers.get("default_reviewer", ""),
        default_approver=approvers.get("default_approver", ""),
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
    approvers = cfg.get("approvers", {}) or {}
    return SutrBuildMeta(
        project_id=req.project_id,
        project_full_name=cfg.get("project_full_name", req.project_id),
        asil_level=cfg.get("asil_level", req.asil_level),
        doc_id_base=cfg.get("doc_id_base", "HDPDM01-SUTR"),
        doc_id_sequence=req.doc_id_sequence,
        default_author=approvers.get("default_author", ""),
        default_reviewer=approvers.get("default_reviewer", ""),
        default_approver=approvers.get("default_approver", ""),
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


_CHUNK_SIZE = 64 * 1024  # 64KB — starlette 기본 chunk와 일치


def _iter_bytesio(buf: "io.BytesIO", chunk_size: int = _CHUNK_SIZE):
    """BytesIO를 chunk로 yield — StreamingResponse 용. 14차 W1."""
    buf.seek(0)
    while True:
        chunk = buf.read(chunk_size)
        if not chunk:
            break
        yield chunk


def _build_result_to_response(
    *, content_io: "io.BytesIO", filename: str, summary: dict[str, Any],
    warnings: list[str], incomplete_sheets: list[str],
    media_type: str,
) -> Response:
    """xlsx/xlsm BytesIO를 attachment StreamingResponse로 변환 (14차 W1).

    summary / warnings / incomplete_sheets는 X-* 헤더로 노출. HTTP 헤더는 latin-1만
    허용하므로 한글 등 비-ASCII는 ``ensure_ascii=True`` 로 ``\\uXXXX`` escape 후 송신.
    Frontend는 ``JSON.parse`` 로 decode 가능. filename도 RFC 5987 ``filename*=UTF-8`` 사용.

    StreamingResponse는 ``Content-Length`` 를 자동 설정하지 않으므로 헤더에 명시.
    """
    from urllib.parse import quote

    ascii_filename = (
        filename.encode("ascii", errors="replace")
        .decode("ascii")
        .replace('"', "_")
    )

    # 14차 W1: BytesIO 크기 측정 (full copy 회피).
    pos = content_io.tell()
    content_io.seek(0, 2)
    size = content_io.tell()
    content_io.seek(pos)

    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_filename}"; '
            f"filename*=UTF-8''{quote(filename)}"
        ),
        "Content-Length": str(size),
        "X-SwUT-Summary": json.dumps(summary, ensure_ascii=True)[:1024],
        "X-SwUT-Warnings": json.dumps(warnings, ensure_ascii=True)[:1024],
        "X-SwUT-Incomplete-Sheets": ",".join(incomplete_sheets).encode(
            "ascii", errors="replace",
        ).decode("ascii")[:512],
    }
    return StreamingResponse(
        _iter_bytesio(content_io),
        media_type=media_type,
        headers=headers,
    )


def _run_build_safely(kind: str, fn: Any, req: SwUTBuildRequest) -> Response:
    """W4: builder exception 통합 처리 — sanitize + logger.exception traceback 보존.

    detail은 외부에 leak 가능하므로 client-safe 메시지로 변환.
    """
    user = get_current_user()
    _logger.info("swut.%s.build start: project_id=%s release=%s user=%s",
                 kind, req.project_id, req.release_sw_version, user)
    try:
        resp = fn(req)
        # 14차 W1: StreamingResponse는 .body 없음 — Content-Length 헤더로 크기 보고.
        size = resp.headers.get("content-length", "?") if hasattr(resp, "headers") else "?"
        _logger.info("swut.%s.build done: project_id=%s bytes=%s",
                     kind, req.project_id, size)
        return resp
    except HTTPException:
        raise  # 의도된 client error는 그대로
    except (FileNotFoundError, PermissionError) as e:
        _logger.exception("swut.%s.build I/O error", kind)
        raise HTTPException(
            status_code=404 if isinstance(e, FileNotFoundError) else 403,
            detail=f"파일 접근 실패: {type(e).__name__}",
        ) from e
    except ValueError as e:
        _logger.exception("swut.%s.build value error", kind)
        # ValueError detail은 builder 내부 메시지 — 사용자 입력 관련 메시지만 leak
        raise HTTPException(status_code=400, detail=f"입력 검증 실패: {e}") from e
    except Exception as e:
        _logger.exception("swut.%s.build unexpected error", kind)
        raise HTTPException(
            status_code=500,
            detail=f"빌드 실패 ({type(e).__name__})",  # 메시지 본문 미노출
        ) from e


def _resolve_swuds_function_ids(req: SwUTBuildRequest) -> set[str] | None:
    """16차: req.swuds_docx_path가 있으면 docx 파싱 → 함수 ID set 반환.

    실패 시 None 반환 — caller는 SwUDS 비교 skip + warnings에 사유 누적.
    """
    if not req.swuds_docx_path:
        return None
    try:
        resolver = get_resolver()
        docx_bytes = resolver.read_bytes(req.swuds_docx_path)
        parse_warnings: list[str] = []
        result = parse_swuds_docx(docx_bytes, parse_warnings=parse_warnings)
        if not result.ok:
            _logger.warning("SwUDS parse failed: %s", parse_warnings)
            return None
        return result.function_ids
    except (FileNotFoundError, PermissionError) as e:
        _logger.warning("SwUDS docx read failed: %s", e)
        return None


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
    swuds_fn_ids = _resolve_swuds_function_ids(req)
    result = build_coverage_report(session, meta, template_bytes,
                                    swuds_function_ids=swuds_fn_ids)
    if not result.ok:
        raise HTTPException(status_code=500, detail="빌드 실패 (ok=False)")
    return _build_result_to_response(
        content_io=result.xlsx_io,
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
        content_io=result.xlsm_io,
        filename=result.filename,
        summary=result.summary,
        warnings=result.warnings,
        incomplete_sheets=result.incomplete_sheets,
        media_type="application/vnd.ms-excel.sheet.macroenabled.12",
    )


@router.post("/coverage/build")
async def build_coverage(req: SwUTBuildRequest) -> Response:
    """Coverage Report v3.01 xlsx 빌드. Semaphore(2)로 동시 호출 제한."""
    async with _BUILD_SEMAPHORE:
        return await asyncio.to_thread(_run_build_safely, "coverage", _do_coverage_build, req)


@router.post("/sutr/build")
async def build_sutr_endpoint(req: SwUTBuildRequest) -> Response:
    """SUTR v3.01 xlsm 빌드 (keep_vba=True). Semaphore(2)로 동시 호출 제한."""
    async with _BUILD_SEMAPHORE:
        return await asyncio.to_thread(_run_build_safely, "sutr", _do_sutr_build, req)
