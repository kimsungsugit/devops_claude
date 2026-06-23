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
import io
import json
import logging
import re
from typing import Any

# 38차 I2: psutil / _get_process_memory_mb / _run_*_safely 함수 제거.
# backend/routers/_safety.run_build_safely / run_consistency_safely 내부 처리.
from fastapi import APIRouter, Depends, HTTPException, Response

from backend.dependencies.admin import require_admin
from backend.routers._safety import run_build_safely, run_consistency_safely, run_preview_safely
from backend.schemas import (
    LogFolderPreviewRequest,
    SwUTBrowseRequest,
    SwUTBuildRequest,
    SwUTConsistencyCheckRequest,
)
from backend.services.file_resolver import get_resolver
from backend.services.path_mode_check import check_log_folder_mode_compat
from backend.services.swut_comprehensive_aggregator import (
    SwutcrBuildMeta,
    build_swutcr_report,
)
from backend.services.swut_consistency_checker import check_swut_consistency
from backend.services.swut_coverage_aggregator import (
    CoverageBuildMeta,
    build_coverage_report,
)
from backend.services.swut_input_adapter import collect_swut_session
from backend.services.swut_sutr_aggregator import SutrBuildMeta, build_sutr
from backend.user_context import get_current_user

_logger = logging.getLogger(__name__)

# 41차 W3: 라우터 전체 admin only — 5 endpoint 모두 require_admin 적용 (40차 통합).
router = APIRouter(
    prefix="/api/swut",
    tags=["swut"],
    dependencies=[Depends(require_admin)],
)

# 17차 T173: Semaphore(2) → (3) 상향. 14차 W1 메모리 1배 절감 (BytesIO/StreamingResponse)
# 으로 빌드 자체 worst-case 1.8MB × 3 = 5.4MB.
# 31차 W31: 30차 W21 c_source_root 도입 후 parse_c_project 동시 호출시 추가 메모리.
#   - tree-sitter Parser instance per call + os.walk 트리 + read_bytes
#   - max_files=300 × 평균 8KB = 2.4MB × 3 = 7.2MB 추가 worst-case
#   - 총 worst-case = 5.4MB (빌드) + 7.2MB (c_parser) ≈ 12.6MB. 운영 안전 한도 내.
# 향후 worst-case 갱신 시 본 docstring + CLAUDE.md "메모리 / 동시성" 섹션 동기 갱신.
_BUILD_SEMAPHORE = asyncio.Semaphore(3)

# 54차 T281 — DRY 통합. _load_meta_from_config 본체는 swut_meta_resolver로 이동.
# 라우터 layer에는 monkeypatch 호환을 위한 thin wrapper만 유지.
from backend.services import swut_meta_resolver as _resolver_mod  # noqa: E402
from backend.services.swut_meta_resolver import (  # noqa: E402
    apply_function_asil_map as _resolver_apply_function_asil_map,
)
from backend.services.swut_meta_resolver import (
    resolve_c_source_root as _resolver_resolve_c_source_root,
)
from backend.services.swut_meta_resolver import (
    resolve_hmr_html_bytes as _resolver_resolve_hmr_html_bytes,
)
from backend.services.swut_meta_resolver import (
    resolve_swuds_function_asil_map as _resolver_resolve_swuds_function_asil_map,
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

# Backward compat alias — 기존 회귀가 `monkeypatch.setattr(swut, '_META_CONFIG_PATH', ...)`
# 또는 `swut._read_meta_config_raw.cache_clear()`로 의존. 본 모듈에서 변수만 patch해도
# resolver 모듈로 자동 sync (_load_meta_from_config thin wrapper에서 동기화).
_META_CONFIG_PATH = _resolver_mod._META_CONFIG_PATH
_read_meta_config_raw = _resolver_mod._read_meta_config_raw  # lru_cache alias


def _load_meta_from_config(project_id: str) -> dict[str, Any]:
    """Thin wrapper — 54차 DRY 통합 (swut_meta_resolver로 이전).

    monkeypatch이 본 모듈의 `_META_CONFIG_PATH`를 변경했으면 resolver 모듈로 동기.
    """
    if _resolver_mod._META_CONFIG_PATH != _META_CONFIG_PATH:
        _resolver_mod._META_CONFIG_PATH = _META_CONFIG_PATH
    return _resolver_mod.load_meta_from_config(project_id)


def _resolve_swut_log_folders(req: SwUTBuildRequest) -> list[str]:
    """B2 — log_folder 다중 입력 해석. 빈 list 반환 가능 (Jenkins-only 빌드).

    우선순위:
        1. req.log_folders (비어있지 않으면 — APP+BOOT 다중 폴더)
        2. req.log_folder (기존 단일)
        3. config `swut_log_folders` (신규 list 키 — config 에이전트 담당)
        4. config `swut_log_folder` (기존 단일 str)
    """
    if req.log_folders:
        folders = [f for f in req.log_folders if f]
        if folders:
            return folders
    if req.log_folder:
        return [req.log_folder]
    cfg = _load_meta_from_config(req.project_id)
    cfg_list = cfg.get("swut_log_folders")
    if isinstance(cfg_list, (list, tuple)):
        folders = [str(f) for f in cfg_list if f]
        if folders:
            return folders
    single = cfg.get("swut_log_folder")
    return [str(single)] if single else []


def _resolve_swut_log_folder(req: SwUTBuildRequest) -> str | None:
    """Return request log_folder or project default SwUT VectorCAST log folder.

    Backward compat — 첫 폴더 단일 반환 (기존 회귀 계약 유지). 신규 코드는
    `_resolve_swut_log_folders` (list 반환) 사용.
    """
    folders = _resolve_swut_log_folders(req)
    return folders[0] if folders else None


def _build_coverage_meta(req: SwUTBuildRequest) -> CoverageBuildMeta:
    cfg = _load_meta_from_config(req.project_id)
    approvers = cfg.get("approvers", {}) or {}
    # 라운드 89: 출력 파일명 패턴 (config doc_filenames[coverage]). 없으면 빌더 default.
    doc_filenames = cfg.get("doc_filenames", {}) or {}
    return CoverageBuildMeta(
        project_id=req.project_id,
        project_full_name=cfg.get("project_full_name", req.project_id),
        asil_level=cfg.get("asil_level", req.asil_level),
        doc_id_base=cfg.get("doc_id_base", ""),
        doc_id_sequence=req.doc_id_sequence,
        default_author=approvers.get("default_author", ""),
        default_reviewer=approvers.get("default_reviewer", ""),
        default_approver=approvers.get("default_approver", ""),
        doc_filename_pattern=doc_filenames.get("coverage", ""),
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
    doc_filenames = cfg.get("doc_filenames", {}) or {}
    return SutrBuildMeta(
        project_id=req.project_id,
        project_full_name=cfg.get("project_full_name", req.project_id),
        asil_level=cfg.get("asil_level", req.asil_level),
        doc_id_base=cfg.get("doc_id_base", "HDPDM01-SUTR"),
        doc_id_sequence=req.doc_id_sequence,
        default_author=approvers.get("default_author", ""),
        default_reviewer=approvers.get("default_reviewer", ""),
        default_approver=approvers.get("default_approver", ""),
        doc_filename_pattern=doc_filenames.get("sutr", ""),
        release_sw_version=req.release_sw_version,
        hw_version=req.hw_version,
        test_date=req.test_date,
        test_engineer=req.test_engineer,
        validation_date=req.validation_date,
        reviewer_override=req.reviewer_override,
        approver_override=req.approver_override,
        deviation_empty=bool(cfg.get("sutr_deviation_empty", False)),
    )


def _build_swutcr_meta(req: SwUTBuildRequest) -> SwutcrBuildMeta:
    cfg = _load_meta_from_config(req.project_id)
    approvers = cfg.get("approvers", {}) or {}
    doc_filenames = cfg.get("doc_filenames", {}) or {}
    return SwutcrBuildMeta(
        project_id=req.project_id,
        project_full_name=cfg.get("project_full_name", req.project_id),
        asil_level=cfg.get("asil_level", req.asil_level),
        doc_id_base=cfg.get("swutcr_doc_id_base", f"{req.project_id}-SwUTCR"),
        doc_id_sequence=req.doc_id_sequence,
        default_author=approvers.get("default_author", ""),
        default_reviewer=approvers.get("default_reviewer", ""),
        default_approver=approvers.get("default_approver", ""),
        doc_filename_pattern=doc_filenames.get("swutcr", ""),
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
    """template_path 명시되면 그 path에서, 아니면 config의 template path에서 read."""
    resolver = get_resolver()
    if template_path:
        return resolver.read_bytes(template_path)
    cfg = _load_meta_from_config(project_id)
    tmpl_cfg = cfg.get("template_paths", {})
    if kind == "coverage":
        key = "coverage_report_template"
    elif kind == "swutcr":
        key = "swutcr_template"
    else:
        key = "sutr_template"
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
    """xlsx/xlsm BytesIO를 attachment Response로 변환.

    summary / warnings / incomplete_sheets는 X-* 헤더로 노출. HTTP 헤더는 latin-1만
    허용하므로 한글 등 비-ASCII는 ``ensure_ascii=True`` 로 ``\\uXXXX`` escape 후 송신.
    Frontend는 ``JSON.parse`` 로 decode 가능. filename도 RFC 5987 ``filename*=UTF-8`` 사용.

    56차 T312: StreamingResponse + 명시 Content-Length 조합이 T307 ASGI 리팩토링 후
    h11 LocalProtocolError("Too little data for declared Content-Length") 발생 → 단순
    Response(bytes 직접)로 변경. h11이 Content-Length 자동 계산 + 100% 일치 보장.
    14차 W1 메모리 절감 일부 반납 (worst ~5.4MB → 7.2MB) 대신 안정성 확보.
    """
    from urllib.parse import quote

    ascii_filename = (
        filename.encode("ascii", errors="replace")
        .decode("ascii")
        .replace('"', "_")
    )

    # 56차 T312: BytesIO 전체 bytes 추출 — Content-Length 명시 + chunk yield 조합이
    # h11 LocalProtocolError 발생. Response가 bytes content로 받으면 자동 일치.
    content_io.seek(0)
    body_bytes = content_io.read()

    # 30차 W21 deep-reviewer fix: truncate 시 frontend JSON.parse 실패 방지.
    # asil_d_function_ids 같은 list가 1024B 초과 시 string 중간 잘림 → invalid JSON.
    # 대안: 잘림 감지 시 sentinel summary로 교체 + 사용자에게 안내.
    _summary_str = json.dumps(summary, ensure_ascii=True)
    if len(_summary_str) > 1024:
        # asil_d_function_ids 만 list 길이로 축약 (정확 함수 ID 알고 싶으면 산출물 열어 확인).
        _safe = dict(summary)
        if "asil_d_function_ids" in _safe and isinstance(_safe["asil_d_function_ids"], list):
            _safe["asil_d_function_ids"] = (
                f"[{len(_safe['asil_d_function_ids'])} ids — 헤더 한도 초과로 생략, "
                "산출물 1.Traceability 시트 / 3.Coverage 시트 확인]"
            )
        _summary_str = json.dumps(_safe, ensure_ascii=True)[:1024]
        # 그래도 초과 시 안전 fallback (절단 후 valid JSON 강제 — sentinel object).
        try:
            json.loads(_summary_str)
        except json.JSONDecodeError:
            _summary_str = json.dumps(
                {"_truncated": True, "_reason": "summary > 1024B"},
                ensure_ascii=True,
            )

    _warnings_str = json.dumps(warnings, ensure_ascii=True)
    if len(_warnings_str) > 1024:
        # F6 Round 5 NF3 fix: breakdown 카테고리 단일 출처
        # (`backend.services.warning_categories`) 사용 — SwUT/SwIT prefix 동시 변경
        # 누락 방지. Round 3 NC1 partial + Round 4 NW7/NW8 fix는 그 모듈에 통합.
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
        "X-SwUT-Summary": _summary_str,
        "X-SwUT-Warnings": _warnings_str,
        "X-SwUT-Incomplete-Sheets": ",".join(incomplete_sheets).encode(
            "ascii", errors="replace",
        ).decode("ascii")[:512],
    }
    return Response(
        content=body_bytes,
        media_type=media_type,
        headers=headers,
    )


# 38차 I2: _run_build_safely 함수 제거 → backend/routers/_safety.run_build_safely
# 사용. 호출 사이트는 endpoint에서 직접 키워드 인자로 전달.


# 54차 T281 — 본체는 backend.services.swut_meta_resolver로 이전.
# 라우터 layer thin wrapper — monkeypatch 의존 회귀 호환 (`mocker.patch(
# 'backend.routers.swut._apply_function_asil_map')` 등 import 경로 무영향).

def _resolve_swuds_path(req: SwUTBuildRequest) -> str:
    """Thin wrapper — 49차 정책 동일."""
    return _resolver_resolve_swuds_path(req, req.project_id)


def _resolve_c_source_root(req: SwUTBuildRequest) -> str:
    """Thin wrapper — 49차 정책 동일."""
    return _resolver_resolve_c_source_root(req, req.project_id)


def _resolve_swuds_function_ids(req: SwUTBuildRequest) -> set[str] | None:
    """Thin wrapper — 16차/49차 정책 동일."""
    return _resolver_resolve_swuds_function_ids(req, req.project_id)


def _resolve_swuds_function_asil_map(req: SwUTBuildRequest) -> dict[str, str]:
    """Thin wrapper — 32차 W28 + 49차 정책 동일."""
    return _resolver_resolve_swuds_function_asil_map(req, req.project_id)


def _apply_function_asil_map(req: SwUTBuildRequest, session) -> None:
    """Thin wrapper — 30차 W21 + 32차 W28 + 50차 W4/W5 정책 동일."""
    _resolver_apply_function_asil_map(req, session, req.project_id)


def _apply_c_function_map(req: SwUTBuildRequest, session) -> None:
    """Parse configured C source so SwUTCR can draft reason/action evidence."""
    c_source_root = _resolve_c_source_root(req)
    if not c_source_root:
        return

    from pathlib import Path

    from backend.services.swut_asil_resolver import is_blocked_source_root

    if is_blocked_source_root(c_source_root):
        session.parse_warnings.append(
            f"[c_source] system directory rejected for reason/action draft: {c_source_root}"
        )
        return

    root = Path(c_source_root)
    if not root.exists() or not root.is_dir():
        session.parse_warnings.append(
            f"[c_source] c_source_root not found for reason/action draft: {c_source_root}"
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
            f"[c_source] parsed {len(functions)} C functions for SwUTCR reason/action "
            f"drafts from {c_source_root}"
        )
    except Exception as exc:  # pragma: no cover - defensive endpoint fallback
        session.parse_warnings.append(
            f"[c_source] reason/action C parse failed: {type(exc).__name__}: {exc}"
        )


def _coverage_stats_incomplete(stats: Any) -> bool:
    total = int(getattr(stats, "total", 0) or 0)
    covered = int(getattr(stats, "covered", 0) or 0)
    return total > 0 and covered < total


def _session_uncovered_function_names(session) -> set[str]:
    names: set[str] = set()
    for env in getattr(session, "environments", []) or []:
        for fc in getattr(env, "function_coverage", []) or []:
            if not (
                _coverage_stats_incomplete(getattr(fc, "statement", None))
                or _coverage_stats_incomplete(getattr(fc, "branch", None))
                or _coverage_stats_incomplete(getattr(fc, "mcdc", None))
            ):
                continue
            for value in (getattr(fc, "name", ""), getattr(fc, "unit_id", "")):
                name = str(value or "").strip()
                if name:
                    names.add(name)
    return names


def _clean_vcast_source_line(text: str) -> str:
    line = str(text or "").replace("\xa0", " ").replace("\r", " ")
    line = re.sub(r"\s+", " ", line).strip()
    # Aggregate source spans often start with VectorCAST counters/markers,
    # e.g. "3338 58 0 (T) * if (...)" before the original C source.
    line = re.sub(r"^\d+\s+\d+\s+\d+\s*(?:\([A-Za-z]\))?\s*", "", line)
    line = re.sub(r"^\*\s*", "", line)
    c_keywords = {
        "auto", "break", "case", "char", "const", "continue", "default", "do",
        "double", "else", "enum", "extern", "float", "for", "goto", "if",
        "inline", "int", "long", "register", "restrict", "return", "short",
        "signed", "sizeof", "static", "struct", "switch", "typedef", "union",
        "unsigned", "void", "volatile", "while",
    }
    if re.fullmatch(r"[A-Za-z_]\w*", line) and line not in c_keywords:
        return ""
    return line.strip()


def _vcast_source_lines_from_html(html_text: str) -> list[str]:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_text, "html.parser")
        raw_lines = [span.get_text(" ", strip=True) for span in soup.find_all("span")]
        if not raw_lines:
            raw_lines = soup.get_text("\n").splitlines()
    except Exception:  # pragma: no cover - bs4 is expected, regex fallback is defensive
        raw_lines = re.sub(r"<br\s*/?>", "\n", html_text, flags=re.I).splitlines()

    cleaned: list[str] = []
    for raw in raw_lines:
        line = _clean_vcast_source_line(raw)
        if line:
            cleaned.append(line)
    return cleaned


def _extract_vcast_function(lines: list[str], function_name: str) -> dict[str, Any] | None:
    escaped = re.escape(function_name)
    signature_pat = re.compile(rf"\b{escaped}\s*\(")

    for idx, line in enumerate(lines):
        if not signature_pat.search(line):
            continue
        if line.rstrip().endswith(";"):
            continue

        collected: list[str] = []
        brace_depth = 0
        started = False
        for current in lines[idx: min(len(lines), idx + 400)]:
            collected.append(current)
            brace_depth += current.count("{") - current.count("}")
            if "{" in current:
                started = True
            if started and brace_depth <= 0:
                break
        if not started or len(collected) < 2:
            continue

        signature = collected[0].strip()
        body = "\n".join(collected[1:]).strip()
        return {
            "name": function_name,
            "signature": signature,
            "body": body,
            "is_static": signature.startswith("static "),
            "calls": [],
            "used_globals": [],
            "source_origin": "vectorcast_aggregate_html",
        }
    return None


def _extract_vcast_functions_from_html(
    html_text: str,
    wanted_names: set[str],
    source_name: str,
) -> dict[str, dict[str, Any]]:
    lines = _vcast_source_lines_from_html(html_text)
    extracted: dict[str, dict[str, Any]] = {}
    for name in sorted(wanted_names):
        c_entry = _extract_vcast_function(lines, name)
        if c_entry:
            c_entry["file"] = source_name
            extracted[name] = c_entry
    return extracted


def _apply_vcast_source_fallback(session, resolver: Any, log_folder: str) -> None:
    """Fill missing SwUTCR C evidence from VectorCAST AggregateCoverageReport HTML."""
    wanted_names = _session_uncovered_function_names(session)
    if not wanted_names:
        return

    c_map = getattr(session, "c_function_map", None) or {}
    missing = {name for name in wanted_names if name not in c_map}
    if not missing or not log_folder:
        return

    normalized_log_folder = log_folder.rstrip("/\\")
    aggregate_folder = f"{normalized_log_folder}\\Aggregate"
    try:
        report_paths = resolver.list_dir(
            aggregate_folder,
            pattern="*AggregateCoverageReport.html",
            recursive=False,
        )
    except Exception as exc:  # pragma: no cover - defensive endpoint fallback
        session.parse_warnings.append(
            f"[c_source] VectorCAST aggregate source fallback list failed: "
            f"{type(exc).__name__}: {exc}"
        )
        return

    matched = 0
    for report_path in report_paths:
        if not missing:
            break
        try:
            raw = resolver.read_bytes(report_path)
            html_text = raw.decode("utf-8", errors="replace")
        except Exception as exc:  # pragma: no cover - defensive endpoint fallback
            session.parse_warnings.append(
                f"[c_source] VectorCAST aggregate source fallback read failed "
                f"({report_path}): {type(exc).__name__}: {exc}"
            )
            continue

        source_name = str(report_path).replace("\\", "/").rsplit("/", 1)[-1]
        extracted = _extract_vcast_functions_from_html(html_text, missing, source_name)
        for name, c_entry in extracted.items():
            c_map.setdefault(name, c_entry)
        matched += len(extracted)
        missing.difference_update(extracted)

    if matched:
        session.c_function_map = c_map
        session.parse_warnings.append(
            f"[c_source] VectorCAST aggregate source fallback applied: "
            f"{matched} functions from {len(report_paths)} reports"
        )


def _do_coverage_build(req: SwUTBuildRequest) -> Response:
    resolver = get_resolver()
    # 56차 T308 — log_folder UNC + Local 모드 pre-flight check (B2 — 폴더별 적용)
    log_folders = _resolve_swut_log_folders(req)
    for _lf in log_folders:
        check_log_folder_mode_compat(_lf, resolver)
    # 57차 T319 diag — Coverage build session params (SUTR과 비교용)
    import logging as _logging
    _logging.getLogger(__name__).info(
        f"Coverage build req: project_id={req.project_id!r}, jenkins_build_number="
        f"{req.jenkins_build_number!r}, cache_root={req.cache_root!r}, "
        f"log_folder={req.log_folder!r}, log_folders={req.log_folders!r}, "
        f"resolved_log_folders={log_folders!r}, "
        f"coverage_template_path={req.coverage_template_path!r}"
    )
    session = collect_swut_session(
        resolver, req.project_id,
        jenkins_build_number=req.jenkins_build_number,
        cache_root=req.cache_root,
        log_folders=log_folders,
    )
    _logging.getLogger(__name__).info(
        f"Coverage build session collected: environments={len(session.environments)}, "
        f"total_tcs={sum(len(env.test_cases) for env in session.environments)}"
    )
    # 30차 W21: function 별 ASIL 매핑 (옵션 c_source_root).
    _apply_function_asil_map(req, session)
    # 51차 — Coverage 양식 전용 path 사용 (config fallback: coverage_report_template).
    template_bytes = _read_template_bytes(req.coverage_template_path, req.project_id, "coverage")
    meta = _build_coverage_meta(req)
    swuds_fn_ids = _resolve_swuds_function_ids(req)
    # 60차 F6-C: HMR HTML 옵션 — VectorCAST aggregate metrics report에서 함수별
    # Function Calls coverage 추출 → 3.Coverage 시트 row 6 stamp (KJPDS02 v1.01).
    # F6 Round 1 W1: hmr read 실패 시 result.warnings에 사유 push (silent 차단).
    _hmr_warnings: list[str] = []
    hmr_html_bytes = _resolver_resolve_hmr_html_bytes(
        req, req.project_id, out_warnings=_hmr_warnings,
    )
    _swuts_warnings: list[str] = []
    swuts_map = _resolver_resolve_swuts_test_specs(
        req, req.project_id, out_warnings=_swuts_warnings,
    )
    result = build_coverage_report(session, meta, template_bytes,
                                    swuds_function_ids=swuds_fn_ids,
                                    swuts_map=swuts_map,
                                    hmr_html_bytes=hmr_html_bytes)
    if _hmr_warnings:
        result.warnings.extend(_hmr_warnings)
    if _swuts_warnings:
        result.warnings.extend(_swuts_warnings)
    if not result.ok:
        raise HTTPException(status_code=500, detail="빌드 실패 (ok=False)")
    # Quality DB recording (non-fatal). Coverage 빌더 = SwUT 커버리지(구문/분기/MC-DC) 출처.
    try:
        from workflow.quality.recorder import record_run
        record_run(
            "swut", result.summary,
            project_root=str(getattr(req, "project_id", "") or ""),
            meta={
                "asil_level": str(getattr(meta, "asil_level", "") or ""),
                "kind": "coverage",
                "release_sw_version": str(getattr(req, "release_sw_version", "") or ""),
            },
        )
    except Exception:
        pass
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


def _is_sutr_spec_based(req: SwUTBuildRequest, cfg: dict[str, Any]) -> bool:
    """라운드 91 — spec-based SUTR 경로 사용 여부.

    config `sutr_spec_based: true` 가 명시되면 우선. 미명시 시 False
    (backward-compat — 기존 build_sutr 표준 양식 유지).

    spec xlsm path는 swut_meta_resolver.resolve_swuts_path 로 별도 해결.
    """
    return bool(cfg.get("sutr_spec_based", False))


def _do_sutr_build_spec_based(
    req: SwUTBuildRequest, session, meta, cfg: dict[str, Any],
) -> Response:
    """라운드 91 — SwUTS spec 시트 기반 SUTR '3.Test Log' 빌드 (회사 감사본 양식).

    SwUTS spec xlsm 을 베이스로 복사 (Input/Expected 보존) + VectorCAST Actual/
    Pass-Fail/Log 추가. 기존 build_sutr (표준 38열 양식)와 분리된 신규 경로.
    """
    from backend.services.swut_meta_resolver import resolve_swuts_path
    from backend.services.swut_sutr_spec_builder import build_sutr_from_spec

    spec_path = resolve_swuts_path(req, req.project_id)
    if not spec_path:
        raise HTTPException(
            status_code=400,
            detail=(
                "spec-based SUTR 빌드에 SwUTS spec xlsm path가 필요합니다 "
                "(config swuts_docx_path 또는 req.swuts_docx_path)"
            ),
        )
    resolver = get_resolver()
    try:
        spec_bytes = resolver.read_bytes(spec_path)
    except (FileNotFoundError, PermissionError, OSError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"SwUTS spec xlsm 읽기 실패: {type(e).__name__}: {e}",
        ) from e

    # 라운드 92 — 표준 SUTR 템플릿을 베이스로 로드 (Cover/History/1.Test Summary/
    # 2.Deviation 보유). spec 와이드 시트만 '3.Test Log'로 이식하여 레퍼런스 시트
    # 구성 정합. 표준 템플릿 미해결 시 spec wb 베이스 fallback (라운드 91 호환).
    template_bytes: bytes | None = None
    try:
        template_bytes = _read_template_bytes(
            req.sutr_template_path, req.project_id, "sutr",
        )
    except HTTPException as te:
        # 표준 템플릿 미지정/미발견 — fallback 경로 (warning은 builder가 누적).
        _logger.warning(
            "spec-based SUTR 표준 템플릿 미해결 — spec wb 베이스 fallback: %s",
            te.detail,
        )

    # aggregate에서 ASIL 매핑 추출 (anchor 시각 강조용).
    from backend.services.swut_input_adapter import aggregate_session
    agg = aggregate_session(session)
    function_asil_map = agg.get("function_asil_map") or {}

    result = build_sutr_from_spec(
        session, meta, spec_bytes,
        template_xlsm_bytes=template_bytes,
        function_asil_map=function_asil_map,
        deviation_cases=req.deviation_cases,
    )
    if not result.ok:
        raise HTTPException(
            status_code=500,
            detail=f"spec-based SUTR 빌드 실패: {'; '.join(result.warnings[:3])}",
        )
    return _build_result_to_response(
        content_io=result.xlsm_io,
        filename=result.filename,
        summary=result.summary,
        warnings=result.warnings,
        incomplete_sheets=result.incomplete_sheets,
        media_type="application/vnd.ms-excel.sheet.macroenabled.12",
    )


def _do_sutr_build(req: SwUTBuildRequest) -> Response:
    resolver = get_resolver()
    # 56차 T308 — log_folder UNC + Local 모드 pre-flight check (B2 — 폴더별 적용)
    log_folders = _resolve_swut_log_folders(req)
    for _lf in log_folders:
        check_log_folder_mode_compat(_lf, resolver)
    # 57차 T319 diag — SUTR build session params 확인 (Coverage와 비교용)
    import logging as _logging
    _logging.getLogger(__name__).info(
        f"SUTR build req: project_id={req.project_id!r}, jenkins_build_number="
        f"{req.jenkins_build_number!r}, cache_root={req.cache_root!r}, "
        f"log_folder={req.log_folder!r}, log_folders={req.log_folders!r}, "
        f"resolved_log_folders={log_folders!r}, "
        f"sutr_template_path={req.sutr_template_path!r}"
    )
    session = collect_swut_session(
        resolver, req.project_id,
        jenkins_build_number=req.jenkins_build_number,
        cache_root=req.cache_root,
        log_folders=log_folders,
    )
    _logging.getLogger(__name__).info(
        f"SUTR build session collected: environments={len(session.environments)}, "
        f"total_tcs={sum(len(env.test_cases) for env in session.environments)}"
    )
    # 30차 W21: function 별 ASIL 매핑 — Coverage builder와 대칭.
    _apply_function_asil_map(req, session)
    meta = _build_sutr_meta(req)

    # 라운드 91 — spec-based SUTR 분기. config `sutr_spec_based: true` (또는 SwUTS
    # spec xlsm path 보유)면 회사 감사본 양식 (spec 시트 통째 복사 + Actual/Pass-Fail
    # 추가) 신규 경로 사용. 기존 build_sutr (표준 38열 함수블록 양식)는 보존.
    _cfg = _load_meta_from_config(req.project_id)
    if _is_sutr_spec_based(req, _cfg):
        return _do_sutr_build_spec_based(req, session, meta, _cfg)

    # 51차 — SUTR 양식 전용 path 사용 (config fallback: sutr_template).
    template_bytes = _read_template_bytes(req.sutr_template_path, req.project_id, "sutr")
    # 17차 T172: SwUDS docx 처리 — Coverage builder와 대칭.
    swuds_fn_ids = _resolve_swuds_function_ids(req)
    # 60차 F6-A: SwUTS xlsm/docx → spec data dict (Test Log B/C/D + Precondition stamp).
    # None이면 build_sutr 내부에서 기존 하드코딩 fallback (backward-compat).
    # F6 Round 1 W1: parse/read 실패 사유는 result.warnings에 push (silent 차단).
    _swuts_warnings: list[str] = []
    swuts_map = _resolver_resolve_swuts_test_specs(
        req, req.project_id, out_warnings=_swuts_warnings,
    )
    result = build_sutr(
        session, meta, template_bytes,
        deviation_cases=req.deviation_cases,
        swuds_function_ids=swuds_fn_ids,
        swuts_map=swuts_map,
    )
    if _swuts_warnings:
        result.warnings.extend(_swuts_warnings)
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


def _resolve_spec_fi_for_swutcr(
    req: SwUTBuildRequest,
    cfg: dict[str, Any],
    resolver: Any,
    out_warnings: list[str],
    *,
    preloaded_spec_bytes: bytes | None = None,
) -> dict[str, Any] | None:
    """확정 규칙(2026-06-12) — UT201 FI spec 자동 산출 입력 준비.

    config ``swutcr_metadata.fault_injection_total/passed`` 가 **둘 다 부재**할
    때만 SwUTS spec을 로드해 FI 블록/iteration을 추출한다:

    - config 키가 하나라도 있으면 None — ``_write_ut201`` 기존 config 분기
      그대로 (heavy spec 로드 비용 회피).
    - spec path 미해결이면 None — 기존 노란 마킹 유지 (HDPDM01 무회귀).
    - xlsm/xlsx 외 확장자(docx 류)는 FI 자동 산출 미지원 — silent skip 아닌
      사유 warning + None (라운드 108 INFO-8).
    - 읽기/추출 실패는 out_warnings에 사유 push + None (실측 위장 금지).
    - ``preloaded_spec_bytes`` — 라운드 108 MINOR-5: caller가
      ``resolve_swuts_test_specs(out_xlsm_bytes=...)`` 로 이미 읽은 동일
      spec bytes(동일 ``resolve_swuts_path`` 해결 경로)를 전달하면 재차
      read하지 않는다 (PV ~20s 중복 read 제거). None이면 기존대로 직접 read.
    """
    md = cfg.get("swutcr_metadata", {}) or {}
    fi_total = md.get("fault_injection_total")
    fi_passed = md.get("fault_injection_passed")
    if not (fi_total in (None, "") and fi_passed in (None, "")):
        return None
    from backend.services.swut_meta_resolver import resolve_swuts_path
    spec_path = resolve_swuts_path(req, req.project_id)
    if not spec_path:
        return None
    spec_name = str(spec_path).replace("\\", "/").rsplit("/", 1)[-1]
    if not spec_name.lower().endswith((".xlsm", ".xlsx")):
        out_warnings.append(
            "[swutcr] UT201 FI spec 자동 산출 skip — spec 확장자가 xlsm/xlsx "
            f"아님 (docx 류 미지원): {spec_name} — 노란 마킹 유지"
        )
        return None
    if preloaded_spec_bytes is not None:
        spec_bytes = preloaded_spec_bytes
    else:
        try:
            spec_bytes = resolver.read_bytes(spec_path)
        except (FileNotFoundError, PermissionError, OSError) as e:
            out_warnings.append(
                "[swutcr] UT201 FI spec 읽기 실패 — 자동 산출 skip (노란 마킹 "
                f"유지). path={spec_path}, {type(e).__name__}: {e}"
            )
            return None
    from backend.services.swut_sutr_spec_builder import extract_spec_fi_stats
    return extract_spec_fi_stats(
        spec_bytes, spec_filename=spec_name, out_warnings=out_warnings,
    )


def _do_swutcr_build(req: SwUTBuildRequest) -> Response:
    resolver = get_resolver()
    # B2 — 다중 log_folder: pre-flight check 폴더별 적용
    log_folders = _resolve_swut_log_folders(req)
    for _lf in log_folders:
        check_log_folder_mode_compat(_lf, resolver)
    import logging as _logging
    _logging.getLogger(__name__).info(
        f"SwUTCR build req: project_id={req.project_id!r}, jenkins_build_number="
        f"{req.jenkins_build_number!r}, cache_root={req.cache_root!r}, "
        f"log_folder={req.log_folder!r}, log_folders={req.log_folders!r}, "
        f"resolved_log_folders={log_folders!r}, "
        f"swutcr_template_path={req.swutcr_template_path!r}"
    )
    session = collect_swut_session(
        resolver, req.project_id,
        jenkins_build_number=req.jenkins_build_number,
        cache_root=req.cache_root,
        log_folders=log_folders,
    )
    _apply_function_asil_map(req, session)
    _apply_c_function_map(req, session)
    # B2 — 모든 폴더의 {log_folder}\Aggregate를 순회. missing이 소진되면 내부
    # early-return (wanted/missing 재계산이 호출마다 수행 — first-wins 유지).
    for _lf in log_folders:
        _apply_vcast_source_fallback(session, resolver, _lf)
    template_bytes = _read_template_bytes(req.swutcr_template_path, req.project_id, "swutcr")
    meta = _build_swutcr_meta(req)
    swuds_fn_ids = _resolve_swuds_function_ids(req)
    hmr_warnings: list[str] = []
    hmr_html_bytes = _resolver_resolve_hmr_html_bytes(
        req, req.project_id, out_warnings=hmr_warnings,
    )
    swuts_warnings: list[str] = []
    # 라운드 108 MINOR-5 — 동일 SwUTS spec 2회 read 제거: resolve_swuts_test_specs
    # 가 read한 bytes를 out-param으로 받아 FI 자동 산출에 재사용 (두 소비자 모두
    # resolve_swuts_path 동일 해결 경로 — bytes 동일성 보장).
    _spec_bytes_box: list[bytes] = []
    swuts_map = _resolver_resolve_swuts_test_specs(
        req, req.project_id, out_warnings=swuts_warnings,
        out_xlsm_bytes=_spec_bytes_box,
    )
    # 확정 규칙(2026-06-12) — UT201 FI spec 자동 산출. config FI 키 둘 다 부재
    # 시에만 spec 로드 (config 존재 시 기존 동작, spec도 없으면 노란 마킹).
    fi_spec_warnings: list[str] = []
    spec_fi = _resolve_spec_fi_for_swutcr(
        req, meta.project_config or {}, resolver, fi_spec_warnings,
        preloaded_spec_bytes=_spec_bytes_box[0] if _spec_bytes_box else None,
    )
    result = build_swutcr_report(
        session, meta, template_bytes,
        deviation_cases=req.deviation_cases,
        swuds_function_ids=swuds_fn_ids,
        swuts_map=swuts_map,
        hmr_html_bytes=hmr_html_bytes,
        spec_fi=spec_fi,
    )
    if hmr_warnings:
        result.warnings.extend(hmr_warnings)
    if swuts_warnings:
        result.warnings.extend(swuts_warnings)
    if fi_spec_warnings:
        result.warnings.extend(fi_spec_warnings)
    if not result.ok:
        raise HTTPException(status_code=500, detail="SwUTCR build failed (ok=False)")
    return _build_result_to_response(
        content_io=result.xlsm_io,
        filename=result.filename,
        summary=result.summary,
        warnings=result.warnings,
        incomplete_sheets=result.incomplete_sheets,
        media_type="application/vnd.ms-excel.sheet.macroenabled.12",
    )


@router.post("/coverage/build")
async def build_coverage(
    req: SwUTBuildRequest,
) -> Response:
    """Coverage Report v3.01 xlsx 빌드. Semaphore(2)로 동시 호출 제한."""
    async with _BUILD_SEMAPHORE:
        return await asyncio.to_thread(
            run_build_safely, series="swut", kind="coverage",
            build_fn=_do_coverage_build, req=req, logger=_logger,
        )


@router.post("/sutr/build")
async def build_sutr_endpoint(
    req: SwUTBuildRequest,
) -> Response:
    """SUTR v3.01 xlsm 빌드 (keep_vba=True). Semaphore(2)로 동시 호출 제한."""
    async with _BUILD_SEMAPHORE:
        return await asyncio.to_thread(
            run_build_safely, series="swut", kind="sutr",
            build_fn=_do_sutr_build, req=req, logger=_logger,
        )


# ── 18차 T177: Coverage ↔ SUTR cross-validation endpoint ──────────────

@router.post("/swutcr/build")
async def build_swutcr_endpoint(
    req: SwUTBuildRequest,
) -> Response:
    """SwUTCR xlsm build. Preserves the comprehensive result template."""
    async with _BUILD_SEMAPHORE:
        return await asyncio.to_thread(
            run_build_safely, series="swut", kind="swutcr",
            build_fn=_do_swutcr_build, req=req, logger=_logger,
        )


def _do_consistency_check(req: SwUTConsistencyCheckRequest) -> dict[str, Any]:
    """파일 resolver로 두 산출물 bytes 읽기 + check_swut_consistency 호출.

    실패 type별 sanitize는 호출자(_run_consistency_safely)가 처리.
    """
    resolver = get_resolver()
    cov_bytes = resolver.read_bytes(req.coverage_path)
    sutr_bytes = resolver.read_bytes(req.sutr_path)
    report = check_swut_consistency(cov_bytes, sutr_bytes)
    return report.to_dict()


# 38차 I2: _run_consistency_safely 함수 제거 → backend/routers/_safety.run_consistency_safely


@router.post("/consistency/check")
async def consistency_check(
    req: SwUTConsistencyCheckRequest,
) -> dict[str, Any]:
    """Coverage Report ↔ SUTR cross-validation (18차).

    swut_consistency_checker.py의 4가지 검증 (uncovered_mismatch /
    exception_deviation / total_tc / final_result) 결과를 JSON으로 반환.
    빌드 endpoint와 달리 Semaphore 미적용 (read-only, 메모리 풋프린트 작음).
    """
    return await asyncio.to_thread(
        run_consistency_safely, series="swut",
        check_fn=_do_consistency_check, req=req, logger=_logger,
    )


# ─────────────────────────────────────────────────────────────────────
# 38차 W4 — log_folder dry-run preview (SwUT용)
# ─────────────────────────────────────────────────────────────────────

def _do_swut_log_folder_preview(req: LogFolderPreviewRequest) -> dict[str, Any]:
    """SwUT용 preview — default env_prefix='SWTE'."""
    from backend.services.swut_input_adapter import preview_release_candidates
    resolver = get_resolver()
    return preview_release_candidates(resolver, req.log_folder)


@router.post("/log-folder/preview")
async def swut_log_folder_preview(
    req: LogFolderPreviewRequest,
) -> dict[str, Any]:
    """38차 W4: 빌드 전 release 후보 list + 자동 선택될 latest 미리보기 (SwUT).

    38차 reviewer W2 fix: run_preview_safely 사용 — log prefix 'log-folder.preview'.
    이전 run_consistency_safely 재사용은 'consistency.check'로 오기록.
    """
    return await asyncio.to_thread(
        run_preview_safely, series="swut",
        check_fn=_do_swut_log_folder_preview, req=req, logger=_logger,
    )


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
    # 22차 T190: cloudium 모드에서 backend python은 권한 없으므로 PermissionError
    # 발생 가능. 그 경우 silent pass + cloudium_hint 응답 → 사용자가 path 직접 입력.
    all_dirs: list[str] = []
    iterdir_failed = False
    try:
        for entry in _Path(raw_path).iterdir():
            if entry.is_dir():
                all_dirs.append(str(entry))
    except (FileNotFoundError, NotADirectoryError):
        # local 모드 + 경로 부재 — caller(_run_browse_safely)가 sanitize → 404
        raise
    except (PermissionError, OSError):
        # cloudium 모드 또는 OS 권한 부족 — silent + hint로 안내
        iterdir_failed = True

    dirs = sorted(set(all_dirs))
    files = sorted(set(all_files))
    truncated = False
    if len(dirs) + len(files) > _BROWSE_MAX_ITEMS:
        # files 우선 truncate (디렉토리는 navigate에 필수)
        budget = _BROWSE_MAX_ITEMS - len(dirs)
        files = files[: max(0, budget)]
        truncated = True

    # 22차 T190: cloudium 모드 hint — backend python은 cloudium 권한 없어서
    # iterdir()가 PermissionError. silent pass 후 사유를 frontend에 안내.
    file_mode = getattr(resolver, "mode", "local")
    cloudium_hint = ""
    if iterdir_failed:
        if file_mode == "cloudium":
            cloudium_hint = (
                "Cloudium 모드 — backend python이 디렉토리 navigate 권한 없음. "
                "파일 list는 worker IPC로 받지만 디렉토리 list는 미지원. "
                "상위 경로를 직접 입력해서 이동하세요."
            )
        else:
            cloudium_hint = "디렉토리 list 권한 부족 — 상위 경로를 직접 입력하세요."

    return {
        "ok": True,
        "current": current,
        "parent": parent,
        "dirs": dirs,
        "files": files,
        "truncated": truncated,
        "file_mode": file_mode,
        "cloudium_hint": cloudium_hint,
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
async def browse_path(
    req: SwUTBrowseRequest,
) -> dict[str, Any]:
    """디렉토리 탐색 — frontend PathPickerDialog 용 (21차).

    file_resolver 통합 (cloudium 모드면 worker 위임, local 모드면 직접).
    Read-only — Semaphore 미적용.
    """
    return await asyncio.to_thread(_run_browse_safely, req)
