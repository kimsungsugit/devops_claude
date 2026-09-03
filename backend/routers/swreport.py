"""SW Test Result Report — 전 레벨 통합 Summary endpoint (ES95411 master).

완성된 레벨별 결과 산출물(SwUTCR/SwITCR/SwSA 등 — ES95411-style ``NN.<TestID>``
detail 시트를 가진 xlsm)을 파싱하여, 마스터 리포트(ES95411)의 ``Summary`` 시트
(ST 정적·UT 단위·IT 통합·ET 시스템)를 한 표로 채운 ``.xlsm`` 을 생성한다.

## 설계 (swut.py / swit.py 패턴 동일)
- 라우터 전체 ``Depends(require_admin)`` — admin-only.
- 입력 표면: JSON body(Pydantic) 단일 — path 문자열을 ``file_resolver`` 로 read
  (cloudium worker / local 공통). UploadFile/Form/Query 미사용.
- build는 ``Semaphore`` + ``asyncio.to_thread(run_build_safely)``; preview는 read-only
  (``run_consistency_safely``).
- 응답: build = xlsm bytes attachment + ``X-SwReport-*`` 헤더; preview = JSON.

## Endpoint
- ``POST /api/swreport/summary/build``   — 통합 Summary .xlsm
- ``POST /api/swreport/summary/preview`` — 통합 표 행 + 집계 JSON (Excel 미빌드)

## 제약 (backend/services/CLAUDE.md)
- Cloudium worker read-only — 산출물은 Response bytes로만 반환, 파일 직접 쓰기 금지.
- backend/services·routers·schemas·main.py 변경 후 uvicorn 재시작 의무.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response

from backend.dependencies.admin import require_admin
from backend.routers._safety import run_build_safely, run_consistency_safely
from backend.schemas import SwReportBuildRequest
from backend.services.file_resolver import get_resolver
from backend.services.swreport_summary_aggregator import (
    SwReportBuildMeta,
    build_summary_report,
    preview_summary_report,
)
from backend.services.swut_meta_resolver import (
    TemplateNotResolved,
    load_meta_from_config,
    read_template_from_keys,
)

_logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/swreport",
    tags=["swreport"],
    dependencies=[Depends(require_admin)],
)

# 통합 Summary 빌드는 워크북 여러 개를 동시에 메모리에 로드(template + N source).
# ES95411 master는 16MB 수준이므로 보수적으로 동시 2건 제한.
_BUILD_SEMAPHORE = asyncio.Semaphore(2)

_XLSM_MEDIA = "application/vnd.ms-excel.sheet.macroenabled.12"

# config template_paths fallback 키 (req.template_path 미지정 시).
_TEMPLATE_CONFIG_KEYS = (
    "es95411_template",
    "test_result_report_template",
    "swreport_template",
)


def _build_meta(req: SwReportBuildRequest) -> SwReportBuildMeta:
    return SwReportBuildMeta(
        project_id=req.project_id,
        project_full_name=req.project_full_name or req.project_id,
        asil_level=req.asil_level or "ASIL A",
        doc_id_sequence=req.doc_id_sequence,
        release_sw_version=req.release_sw_version,
        hw_version=req.hw_version or "1.00",
        test_date=req.test_date,
        test_engineer=req.test_engineer,
        validation_date=req.validation_date,
        reviewer_override=req.reviewer_override,
        approver_override=req.approver_override,
        phase=req.phase,
        product=req.product,
        test_target=req.test_target,
        compiler=req.compiler,
        mcu=req.mcu,
        software_platform_ver=req.software_platform_ver,
    )


def _resolve_template_bytes(req: SwReportBuildRequest) -> bytes:
    """template_path 명시 시 그 경로, 아니면 config template_paths fallback."""
    resolver = get_resolver()
    if req.template_path:
        return resolver.read_bytes(req.template_path)
    cfg = load_meta_from_config(req.project_id)
    tmpl_cfg = cfg.get("template_paths", {}) if isinstance(cfg, dict) else {}
    # ⚠ 예전엔 "값이 있는 첫 키" 에서 곧장 read 했다 — 그 경로가 낡으면 뒤 후보를
    #   시도조차 못 하고 raw FileNotFoundError 가 500 으로 나갔다. 실측:
    #   `es95411_template` 이 v1.02 를 가리키는데 그 세대가 v2.01_260629_R 로
    #   교체돼 사라졌다. 이제 읽힐 때까지 순회하고, 실패해도 어느 키가 왜
    #   안 됐는지 폴더 내용과 함께 400 으로 낸다(준비 게이트와 같은 문장).
    try:
        return read_template_from_keys(
            resolver, tmpl_cfg, _TEMPLATE_CONFIG_KEYS,
            project_id=req.project_id, label="ES95411 통합 Summary",
        )
    except TemplateNotResolved as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def planned_source_paths(source_paths: list[str] | None) -> list[str]:
    """빌드가 **실제로 읽을** 레벨별 산출물 경로 — 판정 단일 출처.

    빈 항목만 걸러내고 나머지는 **전부** `read_bytes` 한다. 즉 하나라도 없으면 부분 결손이
    아니라 빌드 실패(500)다. 준비 게이트(`docgen_preflight`)가 이 함수를 그대로 불러 같은
    목록을 확인한다 — 게이트가 자기 규칙으로 목록을 만들면 "진행해도 된다" 고 한 조건에서
    생성이 죽는다(2026-09-03 R26 리뷰 C1). 목록이 비면 호출자는 양식 자체를 source 로 쓴다.
    """
    return [str(p).strip() for p in (source_paths or []) if str(p or "").strip()]


def _resolve_source_workbooks(
    req: SwReportBuildRequest, template_bytes: bytes,
) -> list[tuple[str, bytes]]:
    """source_paths를 resolver로 read. 비면 template 자체를 source로 (단일파일 refresh)."""
    resolver = get_resolver()
    paths = planned_source_paths(req.source_paths)
    if not paths:
        return [("template-self", template_bytes)]
    out: list[tuple[str, bytes]] = []
    for p in paths:
        label = p.replace("\\", "/").rsplit("/", 1)[-1] or p
        out.append((label, resolver.read_bytes(p)))
    return out


# ── build ────────────────────────────────────────────────────────────────
def _do_summary_build(req: SwReportBuildRequest) -> Response:
    _logger.info(
        "SwReport summary build req: project_id=%r version=%r template=%r sources=%d",
        req.project_id, req.release_sw_version, req.template_path, len(req.source_paths),
    )
    template_bytes = _resolve_template_bytes(req)
    sources = _resolve_source_workbooks(req, template_bytes)
    result = build_summary_report(template_bytes, sources, _build_meta(req))
    if not result.ok:
        raise HTTPException(status_code=500, detail="SwReport Summary build failed (ok=False)")
    # Quality DB recording (non-fatal). output_path 없음(BytesIO 응답, Cloudium read-only).
    try:
        from workflow.quality.recorder import record_run
        record_run(
            "swreport", result.summary,
            project_root=str(getattr(req, "project_id", "") or ""),
            # ⚠ 통합 Summary 의 `project_id` 는 프로젝트가 아니라 **마스터 양식 ID**(ES95411)
            #   라 project_root 에서 프로젝트를 추측할 수가 없다. 화면이 아는 축을 싣는다.
            scm_id=str(getattr(req, "scm_id", "") or "") or None,
            meta={"release_sw_version": getattr(req, "release_sw_version", "")},
        )
    except Exception:
        # non-fatal 은 유지하되 침묵은 금지 (608f849 — 동일 블록이 NameError 를 몇 년간 삼킴).
        _logger.exception("SwReport quality record skipped (non-fatal)")
    return _build_result_to_response(
        content_io=result.xlsm_io,
        filename=result.filename,
        summary=result.summary,
        warnings=result.warnings,
        incomplete=result.incomplete_rows,
    )


def _build_result_to_response(
    *, content_io, filename: str, summary: dict[str, Any],
    warnings: list[str], incomplete: list[str],
) -> Response:
    """xlsm BytesIO → attachment Response. summary/warnings를 X-SwReport-* 헤더로.

    HTTP 헤더는 latin-1만 — 한글은 ``ensure_ascii=True`` 로 escape. filename은 RFC 5987
    ``filename*=UTF-8``. 헤더 1024B 한도 초과 시 valid-JSON sentinel로 축약(swut.py 패턴).
    """
    content_io.seek(0)
    body_bytes = content_io.read()
    ascii_filename = (
        filename.encode("ascii", errors="replace").decode("ascii").replace('"', "_")
    )

    summary_str = json.dumps(summary, ensure_ascii=True)
    if len(summary_str) > 1024:
        safe = dict(summary)
        if isinstance(safe.get("fail_ids"), list):
            safe["fail_ids"] = f"[{len(safe['fail_ids'])} ids — 헤더 한도 초과로 생략]"
        summary_str = json.dumps(safe, ensure_ascii=True)[:1024]
        try:
            json.loads(summary_str)
        except json.JSONDecodeError:
            summary_str = json.dumps({"_truncated": True}, ensure_ascii=True)

    # 예산 초과 시 **들어가는 만큼 싣고 못 실은 개수를 말한다** — 예전엔 본문을 통째로
    # 버려서, 방금 낸 경고가 사용자에게 닿지 않았다(2026-08-25 SwITCR 17건 실측).
    # 판정/포맷은 `warning_categories` 단일 출처 — 라우터 3곳이 갈라지지 않게.
    from backend.services.warning_categories import warnings_header_json
    warnings_str = warnings_header_json(warnings)

    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_filename}"; '
            f"filename*=UTF-8''{quote(filename)}"
        ),
        "X-SwReport-Summary": summary_str,
        "X-SwReport-Warnings": warnings_str,
        "X-SwReport-Incomplete": ",".join(incomplete).encode(
            "ascii", errors="replace",
        ).decode("ascii")[:512],
    }
    return Response(content=body_bytes, media_type=_XLSM_MEDIA, headers=headers)


# ── preview ────────────────────────────────────────────────────────────────
def _do_summary_preview(req: SwReportBuildRequest) -> dict[str, Any]:
    template_bytes = _resolve_template_bytes(req)
    sources = _resolve_source_workbooks(req, template_bytes)
    return preview_summary_report(template_bytes, sources, _build_meta(req))


# ── endpoints ───────────────────────────────────────────────────────────────
@router.post("/summary/build")
async def summary_build(req: SwReportBuildRequest) -> Response:
    """ES95411 통합 Summary .xlsm 빌드. Semaphore(2)로 동시 호출 제한."""
    async with _BUILD_SEMAPHORE:
        return await asyncio.to_thread(
            run_build_safely, series="swreport", kind="summary",
            build_fn=_do_summary_build, req=req, logger=_logger,
        )


@router.post("/summary/preview")
async def summary_preview(req: SwReportBuildRequest) -> dict[str, Any]:
    """통합 표 행 + 집계 JSON (Excel 미빌드). read-only.

    preview도 source 산출물을 메모리 적재하므로(16MB×N) build와 동일 Semaphore로
    동시 적재를 제한한다 (리뷰 P3).
    """
    async with _BUILD_SEMAPHORE:
        return await asyncio.to_thread(
            run_consistency_safely, series="swreport",
            check_fn=_do_summary_preview, req=req, logger=_logger,
        )
