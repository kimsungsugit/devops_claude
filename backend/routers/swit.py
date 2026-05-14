"""SwIT (Software Integration Test) 빌더 endpoint (33~34차 라운드).

SwUT (Unit Test) router 패턴 차용 — 81% 인프라 재활용.

## Endpoint
- ``POST /api/swit/coverage/build`` — SwIT Coverage Report v2.02 xlsx (33차)
- ``POST /api/swit/sitr/build`` — SwIT SITR v2.02 xlsm (keep_vba=True, 34차)

## 설계
- Semaphore(2) — Coverage / SITR 공유. SwUT(3)보다 보수적 시작 — 메모리 측정 후
  31차 W31 패턴으로 worst-case 갱신 권장.
- StreamingResponse + X-SwIT-* 헤더 (Coverage / SITR 명명 분리)
- ASIL 인프라 (c_source_root + swuds_docx_path) SwUT와 동일 — `_apply_function_asil_map`
  Coverage / SITR 공유

## ISO 26262
- SwIT는 ASIL B+ 이상에서 의무 (분기 커버리지 + 인터페이스 테스트)
- evidence_class "auto-generated draft" — manual review 의무
- SITR Deviation은 audit reviewer가 직접 검토 — 자동 reviewer 평가 금지
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
from typing import Any

try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]
    _HAS_PSUTIL = False

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse

from backend.schemas import SwITBuildRequest, SwITSitrBuildRequest
from backend.services.file_resolver import get_resolver
from backend.services.swit_coverage_aggregator import (
    SwitCoverageBuildResult,
    build_swit_coverage_report,
)
from backend.services.swit_input_adapter import collect_swit_session
from backend.services.swit_meta import SwitCoverageBuildMeta, SwitSitrBuildMeta
from backend.services.swit_sitr_aggregator import (
    SwitSitrBuildResult,
    build_swit_sitr_report,
)
from backend.services.swut_swuds_parser import parse_swuds_docx
from backend.user_context import get_current_user

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/swit", tags=["swit"])

# 33차: SwIT는 신규 endpoint — SwUT (Semaphore 3, worst-case 12.6MB)보다 보수적 시작.
# 메모리 운영 측정 후 31차 W31 패턴으로 worst-case 산정 docstring 갱신 권장.
_BUILD_SEMAPHORE = asyncio.Semaphore(2)


def _get_process_memory_mb() -> float | None:
    """SwUT 패턴 그대로 — RSS 메모리 측정 (psutil 미설치 시 None)."""
    if not _HAS_PSUTIL:
        return None
    try:
        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:  # pragma: no cover
        return None


def _build_swit_coverage_meta(req: SwITBuildRequest) -> SwitCoverageBuildMeta:
    """SwITBuildRequest → SwitCoverageBuildMeta. config는 SwUT와 분리 — 본 라운드는
    project_id 기반 default 없이 req 값 우선 (config/swit_meta.json 별도 만들지 않음).
    """
    return SwitCoverageBuildMeta(
        project_id=req.project_id,
        project_full_name=req.project_id,
        asil_level=req.asil_level,
        doc_id_base=f"{req.project_id}-SwIT",
        doc_id_sequence=req.doc_id_sequence,
        default_author="",
        default_reviewer="",
        default_approver="",
        release_sw_version=req.release_sw_version,
        hw_version=req.hw_version,
        test_date=req.test_date,
        test_engineer=req.test_engineer,
        validation_date=req.validation_date,
        reviewer_override=req.reviewer_override,
        approver_override=req.approver_override,
    )


def _build_swit_sitr_meta(req: SwITSitrBuildRequest) -> SwitSitrBuildMeta:
    """SwITSitrBuildRequest → SwitSitrBuildMeta (34차).

    doc_id_base는 SITR로 고정 ("{project_id}-SITR"). final_test_result는 SUTR
    대칭 "OK" default — 사용자가 req에서 override하지 않는 한 SwitSitrBuildMeta
    default 사용.
    """
    return SwitSitrBuildMeta(
        project_id=req.project_id,
        project_full_name=req.project_id,
        asil_level=req.asil_level,
        doc_id_base=f"{req.project_id}-SITR",
        doc_id_sequence=req.doc_id_sequence,
        default_author="",
        default_reviewer="",
        default_approver="",
        release_sw_version=req.release_sw_version,
        hw_version=req.hw_version,
        test_date=req.test_date,
        test_engineer=req.test_engineer,
        validation_date=req.validation_date,
        reviewer_override=req.reviewer_override,
        approver_override=req.approver_override,
    )


def _read_template_bytes(template_path: str) -> bytes:
    """template_path 명시 필수 (config 별도 없음 33차)."""
    if not template_path:
        raise HTTPException(
            status_code=400,
            detail="template_path 미지정 — SwIT는 33차에 config 미지원, 명시 입력 필수",
        )
    resolver = get_resolver()
    return resolver.read_bytes(template_path)


_CHUNK_SIZE = 64 * 1024


def _iter_bytesio(buf: "io.BytesIO", chunk_size: int = _CHUNK_SIZE):
    """SwUT 패턴 — BytesIO를 chunk로 yield."""
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
    """SwUT `_build_result_to_response` 패턴 그대로 — X-SwIT-* 헤더만 명명 분리.

    summary / warnings 1024B truncate + valid JSON 보장 (30차 W21 deep-reviewer fix).
    """
    from urllib.parse import quote

    ascii_filename = (
        filename.encode("ascii", errors="replace")
        .decode("ascii")
        .replace('"', "_")
    )

    pos = content_io.tell()
    content_io.seek(0, 2)
    size = content_io.tell()
    content_io.seek(pos)

    _summary_str = json.dumps(summary, ensure_ascii=True)
    if len(_summary_str) > 1024:
        _safe = dict(summary)
        for key in ("asil_d_function_ids", "asil_c_function_ids", "asil_b_function_ids"):
            if key in _safe and isinstance(_safe[key], list):
                _safe[key] = (
                    f"[{len(_safe[key])} ids — 헤더 한도 초과로 생략, "
                    "산출물 1.Traceability / 3.Coverage 시트 확인]"
                )
        _summary_str = json.dumps(_safe, ensure_ascii=True)[:1024]
        try:
            json.loads(_summary_str)
        except json.JSONDecodeError:
            _summary_str = json.dumps(
                {"_truncated": True, "_reason": "summary > 1024B"},
                ensure_ascii=True,
            )

    _warnings_str = json.dumps(warnings, ensure_ascii=True)
    if len(_warnings_str) > 1024:
        _warnings_str = json.dumps(
            [f"({len(warnings)} warnings — 헤더 한도 초과로 생략, 산출물 확인)"],
            ensure_ascii=True,
        )

    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_filename}"; '
            f"filename*=UTF-8''{quote(filename)}"
        ),
        "Content-Length": str(size),
        "X-SwIT-Summary": _summary_str,
        "X-SwIT-Warnings": _warnings_str,
        "X-SwIT-Incomplete-Sheets": ",".join(incomplete_sheets).encode(
            "ascii", errors="replace",
        ).decode("ascii")[:512],
    }
    return StreamingResponse(
        _iter_bytesio(content_io),
        media_type=media_type,
        headers=headers,
    )


def _run_build_safely(kind: str, fn: Any, req: SwITBuildRequest) -> Response:
    """SwUT `_run_build_safely` 패턴 — 예외 sanitize + memory log.

    SwIT 도구별 명명만 변경 ("swit.{kind}.build" log prefix).
    """
    user = get_current_user()
    mem_before = _get_process_memory_mb()
    _logger.info("swit.%s.build start: project_id=%s release=%s user=%s mem_mb=%s",
                 kind, req.project_id, req.release_sw_version, user,
                 f"{mem_before:.1f}" if mem_before is not None else "n/a")
    try:
        resp = fn(req)
        size = resp.headers.get("content-length", "?") if hasattr(resp, "headers") else "?"
        mem_after = _get_process_memory_mb()
        delta = (f"{mem_after - mem_before:+.1f}"
                 if (mem_before is not None and mem_after is not None) else "n/a")
        _logger.info("swit.%s.build done: project_id=%s bytes=%s mem_mb=%s delta=%s",
                     kind, req.project_id, size,
                     f"{mem_after:.1f}" if mem_after is not None else "n/a",
                     delta)
        return resp
    except HTTPException:
        raise
    except (FileNotFoundError, PermissionError) as e:
        _logger.exception("swit.%s.build I/O error", kind)
        raise HTTPException(
            status_code=404 if isinstance(e, FileNotFoundError) else 403,
            detail=f"파일 접근 실패: {type(e).__name__}",
        ) from e
    except ValueError as e:
        _logger.exception("swit.%s.build value error", kind)
        raise HTTPException(status_code=400, detail=f"입력 검증 실패: {e}") from e
    except Exception as e:
        _logger.exception("swit.%s.build unexpected error", kind)
        raise HTTPException(
            status_code=500,
            detail=f"빌드 실패 ({type(e).__name__})",
        ) from e


def _resolve_swuds_function_ids(req: SwITBuildRequest) -> set[str] | None:
    """SwUT 32차 동일 — SwUDS docx → function_ids set."""
    if not req.swuds_docx_path:
        return None
    try:
        resolver = get_resolver()
        docx_bytes = resolver.read_bytes(req.swuds_docx_path)
        parse_warnings: list[str] = []
        result = parse_swuds_docx(docx_bytes, parse_warnings=parse_warnings)
        if not result.ok:
            _logger.warning("SwIT SwUDS parse failed: %s", parse_warnings)
            return None
        return result.function_ids
    except (FileNotFoundError, PermissionError) as e:
        _logger.warning("SwIT SwUDS docx read failed: %s", e)
        return None


def _apply_function_asil_map(req: SwITBuildRequest, session) -> None:
    """SwIT용 thin wrapper — SwUT `_apply_function_asil_map` 정책 그대로 차용.

    Policy: c_source_root > swuds_docx_path. 충돌 시 c_source 우선.
    """
    if not (req.c_source_root or req.swuds_docx_path):
        return

    c_source_map: dict[str, str] = {}
    if req.c_source_root:
        try:
            from backend.services.swut_asil_resolver import resolve_function_asil_map
            result = resolve_function_asil_map(req.c_source_root)
            if result.warnings:
                session.parse_warnings.extend(result.warnings)
            c_source_map = dict(result.function_asil_map)
        except Exception as e:  # pragma: no cover
            _logger.warning("c_source function_asil_map resolve failed: %s", e)
            session.parse_warnings.append(
                f"c_source ASIL resolve 실패 — {type(e).__name__}"
            )

    swuds_map: dict[str, str] = {}
    if req.swuds_docx_path:
        try:
            resolver = get_resolver()
            docx_bytes = resolver.read_bytes(req.swuds_docx_path)
            result = parse_swuds_docx(docx_bytes)
            if result.ok:
                swuds_map = dict(result.function_asil_map)
        except (FileNotFoundError, PermissionError) as e:
            _logger.warning("SwIT SwUDS ASIL read failed: %s", e)

    merged = dict(swuds_map)
    conflicts = [
        (fid, swuds_map[fid], c_source_map[fid])
        for fid in c_source_map
        if fid in swuds_map and swuds_map[fid] != c_source_map[fid]
    ]
    merged.update(c_source_map)

    sources_used = []
    if req.c_source_root:
        sources_used.append(f"c_source {len(c_source_map)}건")
    if req.swuds_docx_path:
        sources_used.append(f"SwUDS {len(swuds_map)}건")
    if sources_used:
        session.parse_warnings.append(
            "function_asil_map source — "
            + ", ".join(sources_used)
            + f", merged {len(merged)}건"
        )

    for fid, swuds_val, c_val in conflicts:
        session.parse_warnings.append(
            f"ASIL 충돌 '{fid}': SwUDS={swuds_val} vs c_source={c_val} "
            "— c_source 우선 채택"
        )

    if merged and session.environments:
        session.environments[0].function_asil_map = merged


def _do_swit_coverage_build(req: SwITBuildRequest) -> Response:
    resolver = get_resolver()
    session = collect_swit_session(
        resolver, req.project_id,
        jenkins_build_number=req.jenkins_build_number,
        cache_root=req.cache_root,
        log_folder=req.log_folder,
    )
    _apply_function_asil_map(req, session)
    template_bytes = _read_template_bytes(req.template_path)
    meta = _build_swit_coverage_meta(req)
    swuds_fn_ids = _resolve_swuds_function_ids(req)
    result: SwitCoverageBuildResult = build_swit_coverage_report(
        session, meta, template_bytes, swuds_function_ids=swuds_fn_ids,
    )
    if not result.ok:
        raise HTTPException(status_code=500, detail="SwIT 빌드 실패 (ok=False)")
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


@router.post("/coverage/build")
async def build_swit_coverage(req: SwITBuildRequest) -> Response:
    """SwIT Coverage Report v2.02 xlsx 빌드. Semaphore(2)로 동시 호출 제한."""
    async with _BUILD_SEMAPHORE:
        return await asyncio.to_thread(
            _run_build_safely, "coverage", _do_swit_coverage_build, req,
        )


def _do_swit_sitr_build(req: SwITSitrBuildRequest) -> Response:
    """SwIT SITR v2.02 xlsm 빌드 entry (34차).

    Coverage와 동일 입력 source / ASIL map 정책. xlsm 출력 — media_type
    "application/vnd.ms-excel.sheet.macroenabled.12".
    """
    resolver = get_resolver()
    session = collect_swit_session(
        resolver, req.project_id,
        jenkins_build_number=req.jenkins_build_number,
        cache_root=req.cache_root,
        log_folder=req.log_folder,
    )
    _apply_function_asil_map(req, session)
    template_bytes = _read_template_bytes(req.template_path)
    meta = _build_swit_sitr_meta(req)
    swuds_fn_ids = _resolve_swuds_function_ids(req)
    result: SwitSitrBuildResult = build_swit_sitr_report(
        session, meta, template_bytes,
        deviation_cases=req.deviation_cases,
        swuds_function_ids=swuds_fn_ids,
    )
    if not result.ok:
        raise HTTPException(status_code=500, detail="SwIT SITR 빌드 실패 (ok=False)")
    return _build_result_to_response(
        content_io=result.xlsm_io,
        filename=result.filename,
        summary=result.summary,
        warnings=result.warnings,
        incomplete_sheets=result.incomplete_sheets,
        media_type="application/vnd.ms-excel.sheet.macroenabled.12",
    )


@router.post("/sitr/build")
async def build_swit_sitr(req: SwITSitrBuildRequest) -> Response:
    """SwIT SITR v2.02 xlsm 빌드 (34차). Coverage와 Semaphore(2) 공유."""
    async with _BUILD_SEMAPHORE:
        return await asyncio.to_thread(
            _run_build_safely, "sitr", _do_swit_sitr_build, req,
        )
