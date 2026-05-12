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

try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]
    _HAS_PSUTIL = False


def _get_process_memory_mb() -> float | None:
    """20차 T182: 현재 프로세스 RSS 메모리 (MB). psutil 미설치 시 None.

    Semaphore(3) 운영 안전 측정용 — _run_build_safely 시작/종료에서 로깅.
    """
    if not _HAS_PSUTIL:
        return None
    try:
        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:  # pragma: no cover — psutil error fail-safe
        return None

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse

from backend.schemas import SwUTBrowseRequest, SwUTBuildRequest, SwUTConsistencyCheckRequest
from backend.services.file_resolver import get_resolver
from backend.services.swut_consistency_checker import check_swut_consistency
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

# 17차 T173: Semaphore(2) → (3) 상향. 14차 W1 메모리 1배 절감 (BytesIO/StreamingResponse)
# 으로 worst-case 1.8MB × 3 = 5.4MB — 운영 안전 한도. 동시 처리량 1.5x 증가.
_BUILD_SEMAPHORE = asyncio.Semaphore(3)

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
    mem_before = _get_process_memory_mb()
    _logger.info("swut.%s.build start: project_id=%s release=%s user=%s mem_mb=%s",
                 kind, req.project_id, req.release_sw_version, user,
                 f"{mem_before:.1f}" if mem_before is not None else "n/a")
    try:
        resp = fn(req)
        # 14차 W1: StreamingResponse는 .body 없음 — Content-Length 헤더로 크기 보고.
        size = resp.headers.get("content-length", "?") if hasattr(resp, "headers") else "?"
        mem_after = _get_process_memory_mb()
        delta = (f"{mem_after - mem_before:+.1f}"
                 if (mem_before is not None and mem_after is not None) else "n/a")
        _logger.info("swut.%s.build done: project_id=%s bytes=%s mem_mb=%s delta=%s",
                     kind, req.project_id, size,
                     f"{mem_after:.1f}" if mem_after is not None else "n/a",
                     delta)
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
    # 17차 T172: SwUDS docx 처리 — Coverage builder와 대칭.
    swuds_fn_ids = _resolve_swuds_function_ids(req)
    result = build_sutr(
        session, meta, template_bytes,
        deviation_cases=req.deviation_cases,
        swuds_function_ids=swuds_fn_ids,
    )
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


# ── 18차 T177: Coverage ↔ SUTR cross-validation endpoint ──────────────

def _do_consistency_check(req: SwUTConsistencyCheckRequest) -> dict[str, Any]:
    """파일 resolver로 두 산출물 bytes 읽기 + check_swut_consistency 호출.

    실패 type별 sanitize는 호출자(_run_consistency_safely)가 처리.
    """
    resolver = get_resolver()
    cov_bytes = resolver.read_bytes(req.coverage_path)
    sutr_bytes = resolver.read_bytes(req.sutr_path)
    report = check_swut_consistency(cov_bytes, sutr_bytes)
    return report.to_dict()


def _run_consistency_safely(req: SwUTConsistencyCheckRequest) -> dict[str, Any]:
    """W4 패턴 재사용 — exception sanitize + logger.exception traceback 보존."""
    user = get_current_user()
    mem_before = _get_process_memory_mb()
    _logger.info("swut.consistency.check start: coverage=%s sutr=%s user=%s mem_mb=%s",
                 req.coverage_path[:80], req.sutr_path[:80], user,
                 f"{mem_before:.1f}" if mem_before is not None else "n/a")
    try:
        result = _do_consistency_check(req)
        ok = result.get("ok")
        n_issues = len(result.get("issues") or [])
        mem_after = _get_process_memory_mb()
        _logger.info("swut.consistency.check done: ok=%s issues=%d mem_mb=%s",
                     ok, n_issues,
                     f"{mem_after:.1f}" if mem_after is not None else "n/a")
        return result
    except HTTPException:
        raise
    except (FileNotFoundError, PermissionError) as e:
        _logger.exception("swut.consistency.check I/O error")
        raise HTTPException(
            status_code=404 if isinstance(e, FileNotFoundError) else 403,
            detail=f"파일 접근 실패: {type(e).__name__}",
        ) from e
    except ValueError as e:
        _logger.exception("swut.consistency.check value error")
        raise HTTPException(status_code=400, detail=f"입력 검증 실패: {e}") from e
    except Exception as e:
        _logger.exception("swut.consistency.check unexpected error")
        raise HTTPException(
            status_code=500,
            detail=f"일관성 검증 실패 ({type(e).__name__})",
        ) from e


@router.post("/consistency/check")
async def consistency_check(req: SwUTConsistencyCheckRequest) -> dict[str, Any]:
    """Coverage Report ↔ SUTR cross-validation (18차).

    swut_consistency_checker.py의 4가지 검증 (uncovered_mismatch /
    exception_deviation / total_tc / final_result) 결과를 JSON으로 반환.
    빌드 endpoint와 달리 Semaphore 미적용 (read-only, 메모리 풋프린트 작음).
    """
    return await asyncio.to_thread(_run_consistency_safely, req)


# ── 21차 T185: Path picker dialog용 browse endpoint ──────────────────

# 디렉토리 listing 한도 — 2000건 초과 시 truncate (DoS 차단).
_BROWSE_MAX_ITEMS = 2000


def _do_browse(req: SwUTBrowseRequest) -> dict[str, Any]:
    """file_resolver.list_dir 활용 — cloudium / local 통합 navigate.

    Returns:
        {"current": str, "parent": str, "dirs": [str], "files": [str], "truncated": bool}
    """
    import os as _os
    from pathlib import Path as _Path

    resolver = get_resolver()
    raw_path = (req.path or "").strip() or _os.getcwd()
    # 정규화 (단, resolver.resolve()는 cloudium 모드에서 worker 호출이라 비용 큼 — Path 정규화만)
    try:
        current = str(_Path(raw_path))
        parent = str(_Path(raw_path).parent) if _Path(raw_path).parent != _Path(raw_path) else ""
    except (OSError, ValueError):
        current = raw_path
        parent = ""

    patterns = [p.strip() for p in req.pattern.split(",") if p.strip()] or ["*"]
    all_files: list[str] = []
    for pat in patterns:
        # file_resolver.list_dir는 파일만 반환 (디렉토리 제외) — 그대로 활용.
        items = resolver.list_dir(raw_path, pattern=pat, recursive=False)
        all_files.extend(items)

    # 디렉토리는 file_resolver 인터페이스 외부 — Path.iterdir로 별도 수집.
    all_dirs: list[str] = []
    try:
        for entry in _Path(raw_path).iterdir():
            if entry.is_dir():
                all_dirs.append(str(entry))
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        # raw_path가 파일 / 권한 부족 / 부재 — caller(_run_browse_safely)가 sanitize
        raise
    except OSError:
        # cloudium 모드 또는 기타 OSError — 디렉토리 list 불가, files만 반환
        pass

    dirs = sorted(set(all_dirs))
    files = sorted(set(all_files))
    truncated = False
    if len(dirs) + len(files) > _BROWSE_MAX_ITEMS:
        # files 우선 truncate (디렉토리는 navigate에 필수)
        budget = _BROWSE_MAX_ITEMS - len(dirs)
        files = files[: max(0, budget)]
        truncated = True

    return {
        "ok": True,
        "current": current,
        "parent": parent,
        "dirs": dirs,
        "files": files,
        "truncated": truncated,
    }


def _run_browse_safely(req: SwUTBrowseRequest) -> dict[str, Any]:
    user = get_current_user()
    _logger.info("swut.browse: path=%s pattern=%s user=%s",
                 req.path[:80], req.pattern, user)
    try:
        return _do_browse(req)
    except HTTPException:
        raise
    except (FileNotFoundError, NotADirectoryError) as e:
        _logger.exception("swut.browse not found")
        raise HTTPException(
            status_code=404,
            detail=f"경로 접근 실패: {type(e).__name__}",
        ) from e
    except PermissionError as e:
        _logger.exception("swut.browse permission")
        raise HTTPException(status_code=403, detail=f"권한 부족: {type(e).__name__}") from e
    except Exception as e:
        _logger.exception("swut.browse unexpected error")
        raise HTTPException(
            status_code=500, detail=f"browse 실패 ({type(e).__name__})",
        ) from e


@router.post("/browse")
async def browse_path(req: SwUTBrowseRequest) -> dict[str, Any]:
    """디렉토리 탐색 — frontend PathPickerDialog 용 (21차).

    file_resolver 통합 (cloudium 모드면 worker 위임, local 모드면 직접).
    Read-only — Semaphore 미적용.
    """
    return await asyncio.to_thread(_run_browse_safely, req)
