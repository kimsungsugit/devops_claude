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
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from backend.dependencies.admin import require_admin
from backend.routers._safety import run_build_safely, run_consistency_safely, run_preview_safely
from backend.schemas import (
    LogFolderPreviewRequest,
    SwITBuildRequest,
    SwITConsistencyCheckRequest,
    SwITDocSummaryRequest,
    SwITSitrBuildRequest,
)

# 49차 — SwIT는 별도 config 없이 swut_meta.json HDPDM01 슬롯 재활용.
# c_source_root + swuds_docx_path 공유, template_paths는 swit_coverage_template /
# swit_sitr_template 별도 키 (v2.02 양식이 SwUT v3.01과 다름).
# 54차 T281 — DRY 통합. swut_meta_resolver로 path/ASIL 로직 이전.
from backend.services import swut_meta_resolver as _resolver_mod
from backend.services.file_resolver import get_resolver
from backend.services.path_mode_check import check_log_folder_mode_compat
from backend.services.swit_comprehensive_aggregator import (
    SwitcrBuildMeta,
    SwitcrBuildResult,
    build_switcr_report,
)
from backend.services.swit_consistency_checker import (
    check_swit_consistency,
    summarize_swit_coverage_report,
    summarize_swit_test_report,
)
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
from backend.services.swut_meta_resolver import (
    apply_function_asil_map as _resolver_apply_function_asil_map,
)
from backend.services.swut_meta_resolver import (
    resolve_c_source_root as _resolver_resolve_c_source_root,
)
from backend.services.swut_meta_resolver import (
    resolve_hmr_html_bytes as _resolver_resolve_hmr_html_bytes,
)
from backend.services.swut_meta_resolver import (
    resolve_swuds_function_ids as _resolver_resolve_swuds_function_ids,
)
from backend.services.swut_meta_resolver import (
    resolve_swuds_path as _resolver_resolve_swuds_path,
)
from backend.services.swut_meta_resolver import (
    resolve_swuts_test_specs as _resolver_resolve_swuts_test_specs,
)

# 54-fix W2: swut.py와 동일 backward compat alias — 회귀가 swit_mod._META_CONFIG_PATH
# 만 patch해도 정상 동작. swut.py의 단방향 동기화 패턴 (resolver_mod._META_CONFIG_PATH
# 가 alias와 불일치 시 강제 sync)을 대칭으로 swit.py에도 적용.
_META_CONFIG_PATH = _resolver_mod._META_CONFIG_PATH
_read_meta_config_raw = _resolver_mod._read_meta_config_raw  # lru_cache alias


def _load_meta_from_config(project_id: str) -> dict[str, Any]:
    """Thin wrapper — 54차 DRY 통합 (swut_meta_resolver로 이전).

    monkeypatch이 본 모듈의 `_META_CONFIG_PATH`를 변경했으면 resolver로 동기.
    """
    if _resolver_mod._META_CONFIG_PATH != _META_CONFIG_PATH:
        _resolver_mod._META_CONFIG_PATH = _META_CONFIG_PATH
    return _resolver_mod.load_meta_from_config(project_id)

_logger = logging.getLogger(__name__)

# 41차 W3: 라우터 전체 admin only — router dependencies=[Depends(require_admin)]로
# 모든 endpoint에 일괄 적용 (신규 endpoint 자동 포함; 개수 명시는 drift 방지 위해 지양).
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
    doc_filenames = cfg.get("doc_filenames", {}) or {}
    return SwitCoverageBuildMeta(
        project_id=req.project_id,
        project_full_name=cfg.get("project_full_name", req.project_id),
        asil_level=req.asil_level,  # SwIT default "ASIL B" (req) — config asil_level은 SwUT용 (ASIL A) 무시
        doc_id_base=f"{req.project_id}-SwIT",
        doc_id_sequence=req.doc_id_sequence,
        default_author=approvers.get("default_author", ""),
        default_reviewer=approvers.get("default_reviewer", ""),
        default_approver=approvers.get("default_approver", ""),
        doc_filename_pattern=(
            doc_filenames.get("switcv")
            or doc_filenames.get("swit_coverage")
            or ""
        ),
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
    doc_filenames = cfg.get("doc_filenames", {}) or {}
    return SwitSitrBuildMeta(
        project_id=req.project_id,
        project_full_name=cfg.get("project_full_name", req.project_id),
        asil_level=req.asil_level,
        doc_id_base=f"{req.project_id}-SITR",
        doc_id_sequence=req.doc_id_sequence,
        default_author=approvers.get("default_author", ""),
        default_reviewer=approvers.get("default_reviewer", ""),
        default_approver=approvers.get("default_approver", ""),
        doc_filename_pattern=(
            doc_filenames.get("switr")
            or doc_filenames.get("sitr")
            or doc_filenames.get("swit_sitr")
            or ""
        ),
        release_sw_version=req.release_sw_version,
        hw_version=req.hw_version,
        test_date=req.test_date,
        test_engineer=req.test_engineer,
        validation_date=req.validation_date,
        reviewer_override=req.reviewer_override,
        approver_override=req.approver_override,
        # 2026-06-19 — spec-based 2.Deviation 모드. true면 커버리지 미달 함수 목록을
        # 기재하지 않고 '해당 사항 없음'으로 비워둔다. SwUTR `sutr_deviation_empty`
        # 대칭. SwIT deviation(Functions/Function Calls 미달성 사유 H열)은 시험
        # 엔지니어 수기 작성이라 자동 재현 불가 → 자동생성 미달 목록을 비움.
        deviation_empty=bool(cfg.get("sitr_deviation_empty", False)),
    )


def _build_switcr_meta(req: SwITBuildRequest) -> SwitcrBuildMeta:
    """SwITBuildRequest -> SwitcrBuildMeta."""
    cfg = _load_meta_from_config(req.project_id)
    approvers = cfg.get("approvers", {}) or {}
    doc_filenames = cfg.get("doc_filenames", {}) or {}
    return SwitcrBuildMeta(
        project_id=req.project_id,
        project_full_name=cfg.get("project_full_name", req.project_id),
        asil_level=req.asil_level,
        doc_id_base=cfg.get("switcr_doc_id_base", f"{req.project_id}-SwITCR"),
        doc_id_sequence=req.doc_id_sequence,
        default_author=approvers.get("default_author", ""),
        default_reviewer=approvers.get("default_reviewer", ""),
        default_approver=approvers.get("default_approver", ""),
        doc_filename_pattern=(
            doc_filenames.get("switcr")
            or doc_filenames.get("swit_cr")
            or ""
        ),
        release_sw_version=req.release_sw_version,
        hw_version=req.hw_version,
        test_date=req.test_date,
        test_engineer=req.test_engineer,
        validation_date=req.validation_date,
        reviewer_override=req.reviewer_override,
        approver_override=req.approver_override,
        project_config=cfg,
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
    key_by_kind = {
        "coverage": "swit_coverage_template",
        "sitr": "swit_sitr_template",
        "switcr": "switcr_template",
    }
    key = key_by_kind.get(kind)
    if key is None:
        raise HTTPException(status_code=400, detail=f"unknown SwIT template kind: {kind}")
    tpath = (tmpl_cfg.get(key) or "").strip()
    if not tpath:
        raise HTTPException(
            status_code=400,
            detail=f"template_path 미지정 + config/swut_meta.json에 '{key}' 없음 ({project_id})",
        )
    return resolver.read_bytes(tpath)


def _read_optional_config_file(req_path: str, project_id: str, config_key: str) -> bytes | None:
    """Read optional SwITCR evidence workbook from request path or project config."""
    resolver = get_resolver()
    path = (req_path or "").strip()
    if not path:
        cfg = _load_meta_from_config(project_id)
        path = str((cfg.get("template_paths", {}) or {}).get(config_key) or "").strip()
    if not path:
        return None
    return resolver.read_bytes(path)


def _discover_metric_report_bytes(resolver: Any, log_folders: list[str]) -> list[bytes]:
    """라운드 102 (2026-06-24) — IT 로그 폴더에서 VectorCAST Metric report HTML 자동 발견.

    SwITCV Functions O/X(커버리지 달성) + Function Called 실측 소스. 회사 PV IT 로그는
    각 폴더에 `*_Metric_report_*.html`(APP) 또는 `*_IT_*.html`(BOOT, 일반명) 형태로
    Metrics Report를 둔다(04.MetricsReport 서브폴더 아님). 파일명이 일정치 않아
    content-detect: .html을 읽어 parse_hmr_html ok 여부로 판별. 폴더당 html 소수라
    저렴. 실패/부재는 silent(값 정확도 미적용 → 기존 동작 fallback).
    """
    import os as _os

    from backend.services.vcast_hmr_parser import parse_hmr_html as _php
    out: list[bytes] = []
    # 라운드 102 reviewer X6 — log_folders는 config 순서(APP→BOOT) 결정적이나,
    # 폴더 내 list_dir 반환 순서는 드라이브/OS 의존(NTFS mtime/SMB 서버순). 폴더당
    # metric html은 보통 1개라 positional 매칭에 영향 없지만, 다중 html 폴더 대비
    # 사전순 정렬로 결정성 확보 (동명함수 positional 매칭 안정화).
    for folder in log_folders or []:
        try:
            entries = sorted(resolver.list_dir(folder), key=lambda x: str(x).lower())
        except Exception:
            continue
        for e in entries:
            # reviewer W1 — basename만 추출해 `..` 등 traversal 토큰 원천 차단
            # (defense-in-depth; resolver 게이트와 별개 레이어).
            base = _os.path.basename(str(e).rstrip("\\/").replace("\\", "/"))
            if not base.lower().endswith((".html", ".htm")):
                continue
            full = e if (e.startswith("U:") or e.startswith("/")) else folder.rstrip("\\/") + "\\" + base
            try:
                data = resolver.read_bytes(full)
            except Exception:
                continue
            if not data:
                continue
            try:
                if _php(data).ok:
                    out.append(data)
            except Exception:
                continue
    return out


def _resolve_swit_swuds_path(req: "SwITBuildRequest | SwITSitrBuildRequest") -> str:
    """Thin wrapper — 49차 정책 동일 (54차 DRY 통합 → swut_meta_resolver)."""
    return _resolver_resolve_swuds_path(req, req.project_id)


def _resolve_swit_c_source_root(req: "SwITBuildRequest | SwITSitrBuildRequest") -> str:
    """Thin wrapper — 49차 정책 동일 (54차 DRY 통합)."""
    return _resolver_resolve_c_source_root(req, req.project_id)


def _resolve_swit_log_folders(req: "SwITBuildRequest | SwITSitrBuildRequest") -> list[str]:
    """B2 대칭 (SwIT) — log_folder 다중 입력 해석. 빈 list 반환 가능 (Jenkins-only 빌드).

    SwUT `_resolve_swut_log_folders` 패턴 동일. 우선순위:
        1. req.log_folders (비어있지 않으면 — APP+BOOT 다중 폴더)
        2. req.log_folder (기존 단일)
        3. config `swit_log_folders` (신규 list 키 — KJPDS02 PV APP+BOOT)
        4. config `swit_log_folder` (기존 단일 str) / log_folders dict 키
    """
    if req.log_folders:
        folders = [f for f in req.log_folders if f]
        if folders:
            return folders
    if req.log_folder:
        return [req.log_folder]
    cfg = _load_meta_from_config(req.project_id)
    cfg_list = cfg.get("swit_log_folders")
    if isinstance(cfg_list, (list, tuple)):
        folders = [str(f) for f in cfg_list if f]
        if folders:
            return folders
    log_folders = cfg.get("log_folders", {}) or {}
    single = (
        cfg.get("swit_log_folder")
        or log_folders.get("swit")
        or log_folders.get("integration")
        or None
    )
    return [str(single)] if single else []


def _resolve_swit_log_folder(req: "SwITBuildRequest | SwITSitrBuildRequest") -> str | None:
    """Backward compat — 첫 폴더 단일 반환 (기존 회귀 계약 유지).

    신규 코드는 `_resolve_swit_log_folders` (list 반환) 사용.
    """
    folders = _resolve_swit_log_folders(req)
    return folders[0] if folders else None


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

    # 56차 T312: BytesIO 전체 bytes 추출 (StreamingResponse + Content-Length 명시
    # 조합이 T307 ASGI 리팩토링 후 h11 LocalProtocolError 발생 → Response 전환).
    content_io.seek(0)
    body_bytes = content_io.read()

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
        # F6 Round 5 NF3 fix: SwUT와 동일 `warning_categories` 단일 출처 사용.
        from backend.services.warning_categories import format_breakdown_label
        _warnings_str = json.dumps(
            [
                f"({len(warnings)} warnings — 헤더 한도 초과로 생략, "
                f"breakdown: {format_breakdown_label(warnings)})"
            ],
            ensure_ascii=True,
        )

    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_filename}"; '
            f"filename*=UTF-8''{quote(filename)}"
        ),
        # Content-Length는 Response가 body_bytes로 자동 계산 (h11 일치 보장)
        "X-SwIT-Summary": _summary_str,
        "X-SwIT-Warnings": _warnings_str,
        "X-SwIT-Incomplete-Sheets": ",".join(incomplete_sheets).encode(
            "ascii", errors="replace",
        ).decode("ascii")[:512],
    }
    return Response(
        content=body_bytes,
        media_type=media_type,
        headers=headers,
    )


# 38차 I2: _run_build_safely 함수 제거 → backend/routers/_safety.run_build_safely 사용.


def _resolve_swuds_function_ids(
    req: SwITBuildRequest,
    out_warnings: list[str] | None = None,
) -> set[str] | None:
    """Thin wrapper — SwUT 32차 + 49차 정책 동일 (54차 DRY 통합).

    `out_warnings` 는 2026-08-04 추가 — SwUT 쪽과 lockstep. 상세는
    `swut_meta_resolver.resolve_swuds_function_ids` docstring.
    """
    return _resolver_resolve_swuds_function_ids(
        req, req.project_id, out_warnings=out_warnings,
    )


def _apply_function_asil_map(req: SwITBuildRequest, session) -> None:
    """Thin wrapper — c_source_root > swuds_docx_path 정책 (54차 DRY 통합)."""
    _resolver_apply_function_asil_map(req, session, req.project_id)


def _apply_c_function_map(req: SwITBuildRequest, session) -> None:
    """Parse configured C source so SwITCR can draft reason/action evidence."""
    c_source_root = _resolver_resolve_c_source_root(req, req.project_id)
    if not c_source_root:
        return

    from backend.services.swut_asil_resolver import is_blocked_source_root

    if is_blocked_source_root(c_source_root):
        session.parse_warnings.append(
            f"[c_source] system directory rejected for SwITCR reason/action draft: {c_source_root}"
        )
        return

    root = Path(c_source_root)
    if not root.exists() or not root.is_dir():
        session.parse_warnings.append(
            f"[c_source] c_source_root not found for SwITCR reason/action draft: {c_source_root}"
        )
        return

    try:
        from workflow.code_parser.c_parser import parse_c_project

        parsed = parse_c_project(str(root), max_files=300)
        functions = parsed.get("functions", []) if isinstance(parsed, dict) else parsed
        c_map: dict[str, dict[str, Any]] = {}
        for fn in functions:
            if not isinstance(fn, dict):
                continue
            name = str(fn.get("name") or "").strip()
            if name:
                c_map[name] = fn
            related = str(fn.get("comment_related") or "")
            for swufn_id in re.findall(r"SwUFn_\d+", related):
                c_map.setdefault(swufn_id, fn)
        session.c_function_map = c_map
        session.parse_warnings.append(
            f"[c_source] parsed {len(functions)} C functions for SwITCR reason/action "
            f"drafts from {c_source_root}"
        )
    except Exception as exc:  # pragma: no cover - defensive endpoint fallback
        session.parse_warnings.append(
            f"[c_source] SwITCR reason/action C parse failed: {type(exc).__name__}: {exc}"
        )


def _do_swit_coverage_build(req: SwITBuildRequest) -> Response:
    resolver = get_resolver()
    # B2 대칭 — 다중 log_folder (56차 T308 pre-flight check 폴더별 적용)
    log_folders = _resolve_swit_log_folders(req)
    for _lf in log_folders:
        check_log_folder_mode_compat(_lf, resolver)
    session = collect_swit_session(
        resolver, req.project_id,
        jenkins_build_number=req.jenkins_build_number,
        cache_root=req.cache_root,
        log_folders=log_folders,
    )
    _apply_function_asil_map(req, session)
    # 51차 — Coverage 양식 전용 path 사용 (config fallback: swit_coverage_template).
    template_bytes = _read_template_bytes(req.coverage_template_path, req.project_id, "coverage")
    meta = _build_swit_coverage_meta(req)
    # 2026-08-04: SwUDS 읽기/parse 실패 사유 누적 (SwUT 와 lockstep).
    _swuds_warnings: list[str] = []
    swuds_fn_ids = _resolve_swuds_function_ids(req, out_warnings=_swuds_warnings)
    # 60차 F6-C: HMR HTML 옵션 — VectorCAST aggregate metrics report 매핑.
    # F6 Round 1 W1: hmr 실패 사유 누적 (silent 차단).
    _hmr_warnings: list[str] = []
    hmr_html_bytes = _resolver_resolve_hmr_html_bytes(
        req, req.project_id, out_warnings=_hmr_warnings,
    )
    # 라운드 102 (2026-06-24) — IT 로그 폴더의 Metric report HTML 자동 발견 →
    # Functions O/X(달성) + Function Called 실측 산출 소스 (HMR 명시 path 없어도 동작).
    _metric_report_bytes = _discover_metric_report_bytes(resolver, log_folders)
    if _metric_report_bytes:
        _hmr_warnings.append(
            f"[swit-cov] Metric report 자동발견 {len(_metric_report_bytes)}건 "
            "(IT 로그 폴더) — Functions 달성+Function Calls 실측 적용"
        )
    # 60차 F6-A / 라운드 73 T807: SwITS spec 전체를 Traceability에 활용.
    # SwITCV도 SITR과 동일하게 spec parse 실패 사유를 warnings로 노출한다.
    _swits_warnings: list[str] = []
    swits_map = _resolver_resolve_swuts_test_specs(
        req, req.project_id, out_warnings=_swits_warnings,
    )
    result: SwitCoverageBuildResult = build_swit_coverage_report(
        session, meta, template_bytes, swuds_function_ids=swuds_fn_ids,
        hmr_html_bytes=hmr_html_bytes,
        swits_map=swits_map,
        hmr_html_bytes_list=_metric_report_bytes or None,
        swuds_skip_reason="; ".join(_swuds_warnings),
    )
    if _swuds_warnings:
        result.warnings.extend(_swuds_warnings)
    if _hmr_warnings:
        result.warnings.extend(_hmr_warnings)
    if _swits_warnings:
        result.warnings.extend(_swits_warnings)
    if not result.ok:
        raise HTTPException(status_code=500, detail="SwIT 빌드 실패 (ok=False)")
    # Quality DB recording (non-fatal). SwIT Coverage 빌더 = 통합 커버리지 출처.
    try:
        from workflow.quality.recorder import record_run
        record_run(
            "swit", result.summary,
            project_root=str(getattr(req, "project_id", "") or ""),
            meta={
                "asil_level": str(getattr(meta, "asil_level", "") or ""),
                "kind": "coverage",
                "release_sw_version": str(getattr(req, "release_sw_version", "") or ""),
            },
        )
    except Exception:
        # non-fatal 은 유지하되 침묵은 금지 (608f849 — 동일 블록이 NameError 를 몇 년간 삼킴).
        _logger.exception("SwIT quality record skipped (non-fatal)")
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


def _is_sitr_spec_based(req: SwITSitrBuildRequest, cfg: dict[str, Any]) -> bool:
    """SwITR spec-based 경로 사용 여부 (SwUTR `_is_sutr_spec_based` 대칭).

    config `sitr_spec_based: true` 가 명시되면 우선. 미명시 시 False
    (backward-compat — 기존 build_swit_sitr_report 표준 양식 유지).

    spec xlsm path는 swut_meta_resolver.resolve_swuts_path 로 별도 해결
    (SwIT 요청 타입이면 config swits_docx_path/swits_xlsm_path 우선 분기).
    """
    return bool(cfg.get("sitr_spec_based", False))


def _do_swit_sitr_build_spec_based(
    req: SwITSitrBuildRequest, session, meta, cfg: dict[str, Any],
) -> Response:
    """SwITS spec 시트 기반 SwITR '3.Test Log' 빌드 (회사 PV v0.10 양식).

    SwITS spec xlsm 을 베이스로 복사 (Input/Expected 보존) + VectorCAST Actual/
    Pass-Fail/Log 추가 + 2.Deviation(커버리지 미달) 신규 시트. 기존
    build_swit_sitr_report (구 v1.01 4시트 양식)와 분리된 신규 경로.
    """
    from backend.services.swit_sitr_spec_builder import build_sitr_from_spec
    from backend.services.swut_meta_resolver import resolve_swuts_path

    spec_path = resolve_swuts_path(req, req.project_id)
    if not spec_path:
        raise HTTPException(
            status_code=400,
            detail=(
                "spec-based SwITR 빌드에 SwITS spec xlsm path가 필요합니다 "
                "(config swits_docx_path 또는 req.swuts_docx_path)"
            ),
        )
    resolver = get_resolver()
    try:
        spec_bytes = resolver.read_bytes(spec_path)
    except (FileNotFoundError, PermissionError, OSError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"SwITS spec xlsm 읽기 실패: {type(e).__name__}: {e}",
        ) from e

    # v0.10 SwITR 템플릿을 베이스로 로드 (Cover/History/1.Test Summary 보유, 좁은
    # 2.Test Log는 builder가 삭제 후 spec 와이드 시트를 '3.Test Log'로 이식 +
    # 2.Deviation 신규 생성). 템플릿 미해결 시 spec wb 베이스 fallback.
    template_bytes: bytes | None = None
    try:
        template_bytes = _read_template_bytes(
            req.sitr_template_path, req.project_id, "sitr",
        )
    except HTTPException as te:
        _logger.warning(
            "spec-based SwITR 표준 템플릿 미해결 — spec wb 베이스 fallback: %s",
            te.detail,
        )

    from backend.services.swut_input_adapter import aggregate_session
    agg = aggregate_session(session)
    function_asil_map = agg.get("function_asil_map") or {}

    result = build_sitr_from_spec(
        session, meta, spec_bytes,
        template_xlsm_bytes=template_bytes,
        function_asil_map=function_asil_map,
        deviation_cases=req.deviation_cases,
    )
    if not result.ok:
        raise HTTPException(
            status_code=500,
            detail=f"spec-based SwITR 빌드 실패: {'; '.join(result.warnings[:3])}",
        )
    return _build_result_to_response(
        content_io=result.xlsm_io,
        filename=result.filename,
        summary=result.summary,
        warnings=result.warnings,
        incomplete_sheets=result.incomplete_sheets,
        media_type="application/vnd.ms-excel.sheet.macroenabled.12",
    )


def _do_swit_sitr_build(req: SwITSitrBuildRequest) -> Response:
    """SwIT SITR v2.02 xlsm 빌드 entry (34차).

    Coverage와 동일 입력 source / ASIL map 정책. xlsm 출력 — media_type
    "application/vnd.ms-excel.sheet.macroenabled.12".
    """
    resolver = get_resolver()
    # B2 대칭 — 다중 log_folder (56차 T308 pre-flight check 폴더별 적용)
    log_folders = _resolve_swit_log_folders(req)
    for _lf in log_folders:
        check_log_folder_mode_compat(_lf, resolver)
    session = collect_swit_session(
        resolver, req.project_id,
        jenkins_build_number=req.jenkins_build_number,
        cache_root=req.cache_root,
        log_folders=log_folders,
    )
    _apply_function_asil_map(req, session)
    meta = _build_swit_sitr_meta(req)

    # SwITR spec-based 분기 (SwUTR _do_sutr_build 대칭) — config sitr_spec_based:true 면
    # SwITS spec 시트 기반 '3.Test Log' + 2.Deviation 신규 양식(swit_sitr_spec_builder).
    # 표준 build_swit_sitr_report(구 v1.01 4시트)는 분기 아래 그대로 보존.
    _cfg = _load_meta_from_config(req.project_id)
    if _is_sitr_spec_based(req, _cfg):
        return _do_swit_sitr_build_spec_based(req, session, meta, _cfg)

    # 51차 — SITR 양식 전용 path 사용 (config fallback: swit_sitr_template).
    template_bytes = _read_template_bytes(req.sitr_template_path, req.project_id, "sitr")
    # 2026-08-04: 실패 사유 누적 (SwIT coverage / SwUT 3경로와 lockstep).
    _swuds_warnings: list[str] = []
    swuds_fn_ids = _resolve_swuds_function_ids(req, out_warnings=_swuds_warnings)
    # 60차 F6-A: SwITS xlsm/docx → spec data dict (Test Log B/C/D + Precondition stamp).
    # F6 Round 1 W1: spec 실패 사유 누적 (silent 차단).
    _swuts_warnings: list[str] = []
    swuts_map = _resolver_resolve_swuts_test_specs(
        req, req.project_id, out_warnings=_swuts_warnings,
    )
    result: SwitSitrBuildResult = build_swit_sitr_report(
        session, meta, template_bytes,
        deviation_cases=req.deviation_cases,
        swuds_function_ids=swuds_fn_ids,
        swuts_map=swuts_map,
        swuds_skip_reason="; ".join(_swuds_warnings),
    )
    if _swuds_warnings:
        result.warnings.extend(_swuds_warnings)
    if _swuts_warnings:
        result.warnings.extend(_swuts_warnings)
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

def _do_switcr_build(req: SwITBuildRequest) -> Response:
    """SwITCR xlsm build entry."""
    resolver = get_resolver()
    # B2 대칭 — 다중 log_folder (pre-flight check 폴더별 적용)
    log_folders = _resolve_swit_log_folders(req)
    for _lf in log_folders:
        check_log_folder_mode_compat(_lf, resolver)
    session = collect_swit_session(
        resolver, req.project_id,
        jenkins_build_number=req.jenkins_build_number,
        cache_root=req.cache_root,
        log_folders=log_folders,
    )
    _apply_function_asil_map(req, session)
    _apply_c_function_map(req, session)
    template_bytes = _read_template_bytes(
        req.switcr_template_path, req.project_id, "switcr",
    )
    meta = _build_switcr_meta(req)
    _swits_warnings: list[str] = []
    swits_map = _resolver_resolve_swuts_test_specs(
        req, req.project_id, out_warnings=_swits_warnings,
    )
    switcv_bytes = _read_optional_config_file(
        req.switcv_path, req.project_id, "swit_coverage_template",
    )
    switr_bytes = _read_optional_config_file(
        req.switr_path, req.project_id, "swit_sitr_template",
    )
    fault_injection_bytes = _read_optional_config_file(
        req.fault_injection_result_path, req.project_id, "fault_injection_result",
    )
    switcr_reference_bytes = _read_optional_config_file(
        getattr(req, "switcr_reference_path", ""), req.project_id, "switcr_reference",
    )
    result: SwitcrBuildResult = build_switcr_report(
        session,
        meta,
        template_bytes,
        swits_map=swits_map,
        switcv_bytes=switcv_bytes,
        switr_bytes=switr_bytes,
        fault_injection_bytes=fault_injection_bytes,
        switcr_reference_bytes=switcr_reference_bytes,
    )
    if _swits_warnings:
        result.warnings.extend(_swits_warnings)
    if not result.ok:
        raise HTTPException(status_code=500, detail="SwITCR build failed (ok=False)")
    return _build_result_to_response(
        content_io=result.xlsm_io,
        filename=result.filename,
        summary=result.summary,
        warnings=result.warnings,
        incomplete_sheets=result.incomplete_sheets,
        media_type="application/vnd.ms-excel.sheet.macroenabled.12",
    )


@router.post("/switcr/build")
async def build_switcr(
    req: SwITBuildRequest,
) -> Response:
    """SwITCR comprehensive result xlsm build."""
    async with _BUILD_SEMAPHORE:
        return await asyncio.to_thread(
            run_build_safely, series="swit", kind="switcr",
            build_fn=_do_switcr_build, req=req, logger=_logger,
        )


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


def _do_swit_doc_summary(req: SwITDocSummaryRequest) -> dict[str, Any]:
    """단일 산출물(Coverage xlsx | SITR xlsm) bytes를 읽어 해당 결과 요약만 추출(비교 없음).

    정합성 검증(_do_swit_consistency_check)은 두 문서를 cross-validate하지만, 여기서는
    빌더 산출물 1개만으로 그 문서의 결과(미커버 함수·Exception·Final Result 또는
    SITR 통과/실패/미실행/Deviation)를 바로 본다.
    """
    resolver = get_resolver()
    data = resolver.read_bytes(req.path)
    if req.kind == "coverage":
        return summarize_swit_coverage_report(data)
    return summarize_swit_test_report(data)


@router.post("/doc/summary")
async def swit_doc_summary(req: SwITDocSummaryRequest) -> dict[str, Any]:
    """SwITCV Coverage 또는 SITR 산출물 1개를 직접 파싱해 결과 요약 반환.

    35차 정합성 비교(/consistency/check)의 단일 문서판 — 두 문서 쌍이 없어도
    한 산출물의 결과를 표시. read-only, Semaphore 미적용.
    """
    return await asyncio.to_thread(
        run_consistency_safely, series="swit",
        check_fn=_do_swit_doc_summary, req=req, logger=_logger,
        req_summary=f"doc kind={req.kind} path={req.path[:80]}",
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
