"""38차 I2 — 라우터 공통 safety wrapper (build + consistency).

35차 비판적 평가 I2: swut.py와 swit.py에 `_run_build_safely` / `_run_consistency_safely` /
`_run_swit_consistency_safely` 함수 4개가 거의 동일 try/except 패턴 반복. 본 모듈로
추출해 단일 출처 보장.

## 패턴

builder/consistency 함수 호출 + 예외 분류:
  - HTTPException → 재raise (의도된 client error)
  - FileNotFoundError → 404
  - PermissionError → 403
  - ValueError → 400 (Pydantic 또는 builder 내부 입력 검증 실패)
  - 기타 Exception → 500 (메시지 본문 미노출, type 이름만)

`logger.exception`은 traceback 보존 — 서버 로그에서 디버깅 가능.
`detail`은 client-safe 메시지 — sensitive path leak 차단.

## 호출자
- swut.py: build_coverage / build_sutr / consistency_check
- swit.py: build_swit_coverage / build_swit_sitr / swit_consistency_check
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]
    _HAS_PSUTIL = False

from fastapi import HTTPException

from backend.user_context import get_current_user


def get_process_memory_mb() -> float | None:
    """RSS 메모리 측정 (psutil 미설치 시 None)."""
    if not _HAS_PSUTIL:
        return None
    try:
        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:  # pragma: no cover
        return None


def run_build_safely(
    *,
    series: str,
    kind: str,
    build_fn: Callable[..., Any],
    req: Any,
    logger: logging.Logger,
    req_summary: str = "",
) -> Any:
    """빌더 호출 safety wrapper.

    Args:
        series: "swut" or "swit" — log prefix.
        kind: "coverage" or "sutr" or "sitr" — log subprefix.
        build_fn: 실제 빌더 entry (req → Response).
        req: Pydantic request.
        logger: 호출자 모듈의 logger (메시지 namespace 일관성).
        req_summary: log에 추가할 req 정보 (예: "project_id=HDPDM01 release=2.02").
            제공 안 하면 req 객체에서 project_id/release_sw_version 자동 추출 시도.

    Returns:
        builder의 Response (StreamingResponse 등).

    Raises:
        HTTPException — sanitize된 client error.
    """
    user = get_current_user()
    mem_before = get_process_memory_mb()
    if not req_summary:
        # SwUT/SwIT build request 공통 필드 패턴
        pid = getattr(req, "project_id", "?")
        ver = getattr(req, "release_sw_version", "?")
        req_summary = f"project_id={pid} release={ver}"

    logger.info(
        "%s.%s.build start: %s user=%s mem_mb=%s",
        series, kind, req_summary, user,
        f"{mem_before:.1f}" if mem_before is not None else "n/a",
    )
    try:
        resp = build_fn(req)
        size = (
            resp.headers.get("content-length", "?")
            if hasattr(resp, "headers") else "?"
        )
        mem_after = get_process_memory_mb()
        delta = (
            f"{mem_after - mem_before:+.1f}"
            if (mem_before is not None and mem_after is not None) else "n/a"
        )
        logger.info(
            "%s.%s.build done: %s bytes=%s mem_mb=%s delta=%s",
            series, kind, req_summary, size,
            f"{mem_after:.1f}" if mem_after is not None else "n/a",
            delta,
        )
        return resp
    except HTTPException:
        raise
    except (FileNotFoundError, PermissionError) as e:
        logger.exception("%s.%s.build I/O error", series, kind)
        raise HTTPException(
            status_code=404 if isinstance(e, FileNotFoundError) else 403,
            detail=f"파일 접근 실패: {type(e).__name__}",
        ) from e
    except ValueError as e:
        logger.exception("%s.%s.build value error", series, kind)
        raise HTTPException(
            status_code=400, detail=f"입력 검증 실패: {e}",
        ) from e
    except Exception as e:
        logger.exception("%s.%s.build unexpected error", series, kind)
        raise HTTPException(
            status_code=500,
            detail=f"빌드 실패 ({type(e).__name__})",
        ) from e


def run_consistency_safely(
    *,
    series: str,
    check_fn: Callable[..., Any],
    req: Any,
    logger: logging.Logger,
    req_summary: str = "",
) -> Any:
    """Consistency check 호출 safety wrapper — read-only 패턴.

    Args:
        series: "swut" or "swit" — log prefix.
        check_fn: 실제 검증 entry (req → dict).
        req: Pydantic request.
        logger: 호출자 모듈의 logger.
        req_summary: log에 추가할 req 정보. 제공 안 하면 coverage_path + (sutr_path|sitr_path)
            첫 80자 자동 추출.

    Returns:
        check_fn의 결과 (보통 dict).

    Raises:
        HTTPException — sanitize된 client error.
    """
    user = get_current_user()
    mem_before = get_process_memory_mb()
    if not req_summary:
        cov = getattr(req, "coverage_path", "?")[:80]
        other = (
            getattr(req, "sutr_path", None)
            or getattr(req, "sitr_path", None)
            or "?"
        )[:80]
        req_summary = f"coverage={cov} other={other}"

    logger.info(
        "%s.consistency.check start: %s user=%s mem_mb=%s",
        series, req_summary, user,
        f"{mem_before:.1f}" if mem_before is not None else "n/a",
    )
    try:
        result = check_fn(req)
        ok = result.get("ok") if isinstance(result, dict) else None
        n_issues = (
            len(result.get("issues") or [])
            if isinstance(result, dict) else 0
        )
        mem_after = get_process_memory_mb()
        logger.info(
            "%s.consistency.check done: ok=%s issues=%d mem_mb=%s",
            series, ok, n_issues,
            f"{mem_after:.1f}" if mem_after is not None else "n/a",
        )
        return result
    except HTTPException:
        raise
    except (FileNotFoundError, PermissionError) as e:
        logger.exception("%s.consistency.check I/O error", series)
        raise HTTPException(
            status_code=404 if isinstance(e, FileNotFoundError) else 403,
            detail=f"파일 접근 실패: {type(e).__name__}",
        ) from e
    except ValueError as e:
        logger.exception("%s.consistency.check value error", series)
        raise HTTPException(
            status_code=400, detail=f"입력 검증 실패: {e}",
        ) from e
    except Exception as e:
        logger.exception("%s.consistency.check unexpected error", series)
        raise HTTPException(
            status_code=500,
            detail=f"일관성 검증 실패 ({type(e).__name__})",
        ) from e


def run_preview_safely(
    *,
    series: str,
    check_fn: Callable[..., Any],
    req: Any,
    logger: logging.Logger,
) -> Any:
    """38차 reviewer W2 fix — preview endpoint 전용 wrapper.

    `run_consistency_safely`를 재사용하면 log prefix가 'consistency.check'로
    찍혀 운영 로그 검색 시 혼동. 별도 wrapper로 'preview' prefix 명시.

    Args:
        series: "swut" or "swit".
        check_fn: preview_release_candidates 호출 entry.
        req: LogFolderPreviewRequest.
        logger: 호출자 모듈의 logger.

    Returns:
        check_fn 결과 dict.

    Raises:
        HTTPException — sanitize.
    """
    user = get_current_user()
    log_folder_short = getattr(req, "log_folder", "?")[:80]
    logger.info(
        "%s.log-folder.preview start: log_folder=%s user=%s",
        series, log_folder_short, user,
    )
    try:
        result = check_fn(req)
        n_candidates = (
            len(result.get("candidates") or [])
            if isinstance(result, dict) else 0
        )
        auto = (
            result.get("auto_resolved")
            if isinstance(result, dict) else None
        )
        logger.info(
            "%s.log-folder.preview done: candidates=%d auto_resolved=%s",
            series, n_candidates, auto,
        )
        return result
    except HTTPException:
        raise
    except (FileNotFoundError, PermissionError) as e:
        logger.exception("%s.log-folder.preview I/O error", series)
        raise HTTPException(
            status_code=404 if isinstance(e, FileNotFoundError) else 403,
            detail=f"파일 접근 실패: {type(e).__name__}",
        ) from e
    except ValueError as e:
        logger.exception("%s.log-folder.preview value error", series)
        raise HTTPException(
            status_code=400, detail=f"입력 검증 실패: {e}",
        ) from e
    except Exception as e:
        logger.exception("%s.log-folder.preview unexpected error", series)
        raise HTTPException(
            status_code=500,
            detail=f"미리보기 실패 ({type(e).__name__})",
        ) from e


__all__ = [
    "get_process_memory_mb",
    "run_build_safely",
    "run_consistency_safely",
    "run_preview_safely",
]
