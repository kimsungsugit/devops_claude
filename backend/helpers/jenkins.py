"""Jenkins-specific domain helpers."""
import re
import os
import json
import shutil
import logging
import zipfile
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    from fastapi import HTTPException
except ImportError:
    HTTPException = Exception

try:
    from backend.schemas import JenkinsPublishRequest
except ImportError:
    JenkinsPublishRequest = None  # type: ignore[assignment,misc]

from backend.services.jenkins_helpers import _detect_reports_dir, _job_slug
from backend.services.report_parsers import (
    build_report_summary,
    classify_report_group,
    find_local_jenkins_report_dir,
    write_report_index,
)
from backend.services.paths import is_under_any

import config

from backend.helpers.common import (
    _read_json,
    _write_json,
    _set_progress,
    _is_relative_to,
)

_logger = logging.getLogger("devops_api")

repo_root = Path(__file__).resolve().parents[2]



def _jenkins_exports_dir(cache_root: str) -> Path:
    return _normalize_jenkins_cache_root(cache_root) / "exports"


def _jenkins_templates_dir(cache_root: str) -> Path:
    return _normalize_jenkins_cache_root(cache_root) / "templates"


def _jenkins_logic_dir(cache_root: str) -> Path:
    return _jenkins_exports_dir(cache_root) / "logic"


def _jenkins_sts_dir(cache_root: str) -> Path:
    return _jenkins_exports_dir(cache_root) / "sts"


def _jenkins_suts_dir(cache_root: str) -> Path:
    return _jenkins_exports_dir(cache_root) / "suts"


def _uds_meta_path(out_dir: Path, job_slug: str) -> Path:
    return out_dir / f"uds_meta_{job_slug}.json"


def _load_uds_meta(out_dir: Path, job_slug: str) -> Dict[str, Any]:
    meta = _read_json(_uds_meta_path(out_dir, job_slug), default={})
    if not isinstance(meta, dict):
        meta = {}
    labels = meta.get("labels")
    if not isinstance(labels, dict):
        meta["labels"] = {}
    return meta


def _save_uds_meta(out_dir: Path, job_slug: str, meta: Dict[str, Any]) -> None:
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(_uds_meta_path(out_dir, job_slug), meta)


def _normalize_jenkins_cache_root(cache_root: str) -> Path:
    if cache_root:
        return Path(cache_root).expanduser().resolve()
    return (Path.home() / ".devops_pro_cache").resolve()


def _resolve_cached_build_root(job_url: str, cache_root: str, build_selector: str) -> Optional[Path]:
    base = _normalize_jenkins_cache_root(cache_root)
    job_slug = _job_slug(job_url)
    job_root = (base / "jenkins" / job_slug).resolve()
    if not job_root.exists():
        return None
    if str(build_selector).isdigit():
        cand = (job_root / f"build_{int(build_selector)}").resolve()
        return cand if cand.exists() else None
    builds = sorted(job_root.glob("build_*"), reverse=True)
    return builds[0].resolve() if builds else None


def _normalize_filter_tokens(values: Optional[List[str]]) -> List[str]:
    if not values:
        return []
    out: List[str] = []
    for item in values:
        raw = str(item).replace("\\", "/").strip().strip("/")
        if raw:
            out.append(raw)
    return out


def _matches_filters(rel_path: str, include: List[str], exclude: List[str]) -> bool:
    rel_norm = rel_path.replace("\\", "/").strip("/")
    if exclude:
        for token in exclude:
            if rel_norm == token or rel_norm.startswith(f"{token}/"):
                return False
    if include:
        for token in include:
            if rel_norm == token or rel_norm.startswith(f"{token}/"):
                return True
        return False
    return True


def _create_jenkins_zip_file(
    report_dir: Path,
    out_path: Path,
    scan: Optional[Dict[str, Any]] = None,
    include_paths: Optional[List[str]] = None,
    exclude_paths: Optional[List[str]] = None,
    exts: Optional[List[str]] = None,
) -> None:
    """Jenkins 동기화 파일 ZIP 생성 헬퍼 함수"""
    include_tokens = _normalize_filter_tokens(include_paths)
    exclude_tokens = _normalize_filter_tokens(exclude_paths)
    ext_tokens = [str(x).lower().lstrip(".") for x in (exts or []) if str(x).strip()]
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 전체 파일 추가
        files_to_add = [p for p in report_dir.rglob("*") if p.is_file()]
        for p in files_to_add:
            try:
                rel = p.relative_to(report_dir)
                rel_s = str(rel).replace("\\", "/")
                if not _matches_filters(rel_s, include_tokens, exclude_tokens):
                    continue
                if ext_tokens:
                    ext = p.suffix.lower().lstrip(".")
                    if ext not in ext_tokens:
                        continue
                zf.write(p, arcname=str(rel))
            except Exception:
                continue


def _jenkins_report_publish_impl(req: JenkinsPublishRequest, job_id: str = "") -> Dict[str, Any]:
    build_root = _resolve_cached_build_root(req.job_url, req.cache_root, req.build_selector)
    if not build_root:
        raise HTTPException(status_code=404, detail="cached build not found")
    report_dir = _detect_reports_dir(build_root)
    report_dir.mkdir(parents=True, exist_ok=True)

    if req.source_dir:
        source_dir = Path(req.source_dir).expanduser().resolve()
        if not is_under_any(source_dir, [repo_root]):
            raise HTTPException(status_code=400, detail="source_dir not allowed")
    else:
        source_dir = find_local_jenkins_report_dir(repo_root, _job_slug(req.job_url))
        if not source_dir:
            raise HTTPException(status_code=404, detail="local report folder not found")

    job_url = req.job_url
    build_selector = req.build_selector
    _set_progress(
        "publish",
        job_url,
        build_selector,
        {
            "stage": "start",
            "percent": 1,
            "message": "로컬 리포트 업로드 준비 중",
            "done": False,
            "error": "",
        },
        job_id=job_id,
    )

    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_slug = _job_slug(req.job_url)
        dest_dir = (report_dir / "local_upload" / job_slug / ts).resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)
        files = [p for p in source_dir.rglob("*") if p.is_file()]
        total = max(1, len(files))
        copied = 0
        _set_progress(
            "publish",
            job_url,
            build_selector,
            {
                "stage": "copy_start",
                "percent": 5,
                "message": f"파일 복사 시작 ({total}개)",
                "current": 0,
                "total": total,
            },
            job_id=job_id,
        )
        for idx, path in enumerate(files):
            rel = path.relative_to(source_dir)
            group = classify_report_group(str(rel))
            target = (dest_dir / group / rel).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(path, target)
                copied += 1
            except Exception:
                continue
            if idx % 50 == 0 or idx + 1 == total:
                percent = 5 + int(((idx + 1) / total) * 80)
                _set_progress(
                    "publish",
                    job_url,
                    build_selector,
                    {
                        "stage": "copy",
                        "percent": percent,
                        "message": f"파일 복사 {idx + 1}/{total}",
                        "current": idx + 1,
                        "total": total,
                        "file": str(rel),
                    },
                    job_id=job_id,
                )

        _set_progress(
            "publish",
            job_url,
            build_selector,
            {
                "stage": "summary",
                "percent": 90,
                "message": "리포트 요약 생성",
            },
            job_id=job_id,
        )
        summary = build_report_summary(report_dir, project_root=repo_root)
        index_path = write_report_index(report_dir, summary)
        _set_progress(
            "publish",
            job_url,
            build_selector,
            {
                "stage": "done",
                "percent": 100,
                "message": "로컬 리포트 업로드 완료",
                "done": True,
            },
            job_id=job_id,
        )
        return {
            "ok": True,
            "source_dir": str(source_dir),
            "dest_dir": str(dest_dir),
            "index_path": str(index_path),
            "copied": copied,
        }
    except Exception as exc:
        _set_progress(
            "publish",
            job_url,
            build_selector,
            {
                "stage": "error",
                "percent": 100,
                "message": "로컬 리포트 업로드 실패",
                "done": True,
                "error": str(exc),
            },
            job_id=job_id,
        )
        raise

