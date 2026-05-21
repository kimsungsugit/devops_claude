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
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from backend.dependencies.admin import require_admin
from fastapi.responses import StreamingResponse

from backend.routers._safety import run_build_safely, run_consistency_safely, run_preview_safely
from backend.schemas import (
    LogFolderPreviewRequest,
    SwITBuildRequest,
    SwITConsistencyCheckRequest,
    SwITSitrBuildRequest,
)
from backend.services.file_resolver import get_resolver
from backend.services.swit_consistency_checker import check_swit_consistency
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
# 49차 — SwIT는 별도 config 없이 swut_meta.json HDPDM01 슬롯 재활용.
# c_source_root + swuds_docx_path 공유, template_paths는 swit_coverage_template /
# swit_sitr_template 별도 키 (v2.02 양식이 SwUT v3.01과 다름).
# 54차 T281 — DRY 통합. swut_meta_resolver로 path/ASIL 로직 이전.
from backend.services.swut_meta_resolver import (
    apply_function_asil_map as _resolver_apply_function_asil_map,
    load_meta_from_config as _resolver_load_meta_from_config,
    resolve_c_source_root as _resolver_resolve_c_source_root,
    resolve_swuds_function_ids as _resolver_resolve_swuds_function_ids,
    resolve_swuds_path as _resolver_resolve_swuds_path,
)


def _load_meta_from_config(project_id: str) -> dict[str, Any]:
    """Thin wrapper — 54차 DRY 통합 (swut_meta_resolver로 이전)."""
    return _resolver_load_meta_from_config(project_id)

_logger = logging.getLogger(__name__)

# 41차 W3: 라우터 전체 admin only — 4 endpoint 모두 require_admin 적용 (40차 통합).
# endpoint signature에서 `_admin: str = Depends(require_admin)` 중복 제거.
router = APIRouter(
    prefix="/api/swit",
    tags=["swit"],
    dependencies=[Depends(require_admin)],
)

# 33차: SwIT는 신규 endpoint — SwUT (Semaphore 3, worst-case 12.6MB)보다 보수적 시작.
# 메모리 운영 측정 후 31차 W31 패턴으로 worst-case 산정 docstring 갱신 권장.
_BUILD_SEMAPHORE = asyncio.Semaphore(2)

# 38차 I2: get_process_memory_mb / get_current_user / _run_*_safely 함수들 제거.
# backend/routers/_safety.run_build_safely / run_consistency_safely 가 내부 처리.


def _build_swit_coverage_meta(req: SwITBuildRequest) -> SwitCoverageBuildMeta:
    """SwITBuildRequest → SwitCoverageBuildMeta. 50차 — SwUT와 동일하게 config의
    approvers + project_full_name fallback 적용. doc_id_base는 SwIT 고유 ("{project_id}-SwIT").
    """
    cfg = _load_meta_from_config(req.project_id)
    approvers = cfg.get("approvers", {}) or {}
    return SwitCoverageBuildMeta(
        project_id=req.project_id,
        project_full_name=cfg.get("project_full_name", req.project_id),
        asil_level=req.asil_level,  # SwIT default "ASIL B" (req) — config asil_level은 SwUT용 (ASIL A) 무시
        doc_id_base=f"{req.project_id}-SwIT",
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


def _build_swit_sitr_meta(req: SwITSitrBuildRequest) -> SwitSitrBuildMeta:
    """SwITSitrBuildRequest → SwitSitrBuildMeta (34차). 50차 — config approvers + project_full_name fallback.

    doc_id_base는 SITR로 고정 ("{project_id}-SITR"). final_test_result는 SUTR
    대칭 "OK" default — 사용자가 req에서 override하지 않는 한 SwitSitrBuildMeta
    default 사용.
    """
    cfg = _load_meta_from_config(req.project_id)
    approvers = cfg.get("approvers", {}) or {}
    return SwitSitrBuildMeta(
        project_id=req.project_id,
        project_full_name=cfg.get("project_full_name", req.project_id),
        asil_level=req.asil_level,
        doc_id_base=f"{req.project_id}-SITR",
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
    """template_path 명시되면 그 path에서, 아니면 config의 swit_*_template fallback (49차).

    kind: "coverage" → swit_coverage_template / "sitr" → swit_sitr_template.
    """
    resolver = get_resolver()
    if template_path:
        return resolver.read_bytes(template_path)
    cfg = _load_meta_from_config(project_id)
    tmpl_cfg = cfg.get("template_paths", {})
    key = "swit_coverage_template" if kind == "coverage" else "swit_sitr_template"
    tpath = (tmpl_cfg.get(key) or "").strip()
    if not tpath:
        raise HTTPException(
            status_code=400,
            detail=f"template_path 미지정 + config/swut_meta.json에 '{key}' 없음 ({project_id})",
        )
    return resolver.read_bytes(tpath)


def _resolve_swit_swuds_path(req: "SwITBuildRequest | SwITSitrBuildRequest") -> str:
    """Thin wrapper — 49차 정책 동일 (54차 DRY 통합 → swut_meta_resolver)."""
    return _resolver_resolve_swuds_path(req, req.project_id)


def _resolve_swit_c_source_root(req: "SwITBuildRequest | SwITSitrBuildRequest") -> str:
    """Thin wrapper — 49차 정책 동일 (54차 DRY 통합)."""
    return _resolver_resolve_c_source_root(req, req.project_id)


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


# 38차 I2: _run_build_safely 함수 제거 → backend/routers/_safety.run_build_safely 사용.


def _resolve_swuds_function_ids(req: SwITBuildRequest) -> set[str] | None:
    """Thin wrapper — SwUT 32차 + 49차 정책 동일 (54차 DRY 통합)."""
    return _resolver_resolve_swuds_function_ids(req, req.project_id)


def _apply_function_asil_map(req: SwITBuildRequest, session) -> None:
    """Thin wrapper — c_source_root > swuds_docx_path 정책 (54차 DRY 통합)."""
    _resolver_apply_function_asil_map(req, session, req.project_id)


def _do_swit_coverage_build(req: SwITBuildRequest) -> Response:
    resolver = get_resolver()
    session = collect_swit_session(
        resolver, req.project_id,
        jenkins_build_number=req.jenkins_build_number,
        cache_root=req.cache_root,
        log_folder=req.log_folder,
    )
    _apply_function_asil_map(req, session)
    # 51차 — Coverage 양식 전용 path 사용 (config fallback: swit_coverage_template).
    template_bytes = _read_template_bytes(req.coverage_template_path, req.project_id, "coverage")
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
async def build_swit_coverage(
    req: SwITBuildRequest,
) -> Response:
    """SwIT Coverage Report v2.02 xlsx 빌드. Semaphore(2)로 동시 호출 제한."""
    async with _BUILD_SEMAPHORE:
        return await asyncio.to_thread(
            run_build_safely, series="swit", kind="coverage",
            build_fn=_do_swit_coverage_build, req=req, logger=_logger,
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
    # 51차 — SITR 양식 전용 path 사용 (config fallback: swit_sitr_template).
    template_bytes = _read_template_bytes(req.sitr_template_path, req.project_id, "sitr")
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
async def build_swit_sitr(
    req: SwITSitrBuildRequest,
) -> Response:
    """SwIT SITR v2.02 xlsm 빌드 (34차). Coverage와 Semaphore(2) 공유."""
    async with _BUILD_SEMAPHORE:
        return await asyncio.to_thread(
            run_build_safely, series="swit", kind="sitr",
            build_fn=_do_swit_sitr_build, req=req, logger=_logger,
        )


# ─────────────────────────────────────────────────────────────────────
# 35차 — SwIT Coverage ↔ SITR cross-validation
# ─────────────────────────────────────────────────────────────────────

def _do_swit_consistency_check(req: SwITConsistencyCheckRequest) -> dict[str, Any]:
    """파일 resolver로 Coverage xlsx + SITR xlsm bytes 읽기 + check_swit_consistency 호출.

    실패 type별 sanitize는 호출자(_run_swit_consistency_safely)가 처리.
    """
    resolver = get_resolver()
    cov_bytes = resolver.read_bytes(req.coverage_path)
    sitr_bytes = resolver.read_bytes(req.sitr_path)
    report = check_swit_consistency(cov_bytes, sitr_bytes)
    return report.to_dict()


# 38차 I2: _run_swit_consistency_safely 함수 제거 → backend/routers/_safety.run_consistency_safely


@router.post("/consistency/check")
async def swit_consistency_check(
    req: SwITConsistencyCheckRequest,
) -> dict[str, Any]:
    """SwIT Coverage Report ↔ SITR cross-validation (35차).

    swit_consistency_checker.py 4가지 검증 (uncovered_mismatch /
    exception_deviation / total_tc / final_result) 결과를 JSON으로 반환.
    빌드 endpoint와 달리 Semaphore 미적용 (read-only, 메모리 풋프린트 작음).
    """
    return await asyncio.to_thread(
        run_consistency_safely, series="swit",
        check_fn=_do_swit_consistency_check, req=req, logger=_logger,
    )


# ─────────────────────────────────────────────────────────────────────
# 38차 W4 — log_folder dry-run preview (frontend pre-build UX)
# ─────────────────────────────────────────────────────────────────────

def _do_swit_log_folder_preview(req: LogFolderPreviewRequest) -> dict[str, Any]:
    """36-fix env_prefix='SwITC' + 37차 auto-resolved 의 미리보기.

    빌드 없이 후보 list + 자동 선택될 release만 반환.
    """
    from backend.services.swut_input_adapter import preview_release_candidates
    resolver = get_resolver()
    return preview_release_candidates(resolver, req.log_folder)


@router.post("/log-folder/preview")
async def swit_log_folder_preview(
    req: LogFolderPreviewRequest,
) -> dict[str, Any]:
    """38차 W4: 빌드 전 release 후보 list + 자동 선택될 latest 미리보기.

    사용자가 `01.Log/` 상위 폴더만 입력해도 어떤 release가 선택될지 사전 확인 가능.
    실 빌드는 따로 호출 (Coverage/SITR endpoint).

    38차 reviewer W2 fix: run_preview_safely 사용 (consistency 재사용 → preview 분리).
    """
    return await asyncio.to_thread(
        run_preview_safely, series="swit",
        check_fn=_do_swit_log_folder_preview, req=req, logger=_logger,
    )
