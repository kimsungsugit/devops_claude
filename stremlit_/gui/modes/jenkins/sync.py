# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import config
import gui_utils
import jenkins_adapter
from jenkins_client import JenkinsClient

from .helpers import _detect_reports_dir, _job_slug, _norm_job_url, _safe_artifact_path


def _sync_local_reports(
    *,
    job_url: str,
    local_reports_dir: Path,
) -> Tuple[Dict[str, Any], Path, Path, List[str], List[Dict[str, Any]]]:
    reports_dir = Path(local_reports_dir).resolve()
    build_root = reports_dir.parent
    build_info: Dict[str, Any] = {
        "number": -1,
        "result": "LOCAL",
        "timestamp": None,
        "url": "",
        "job_url": job_url,
    }

    jenkins_adapter.ensure_gui_summary(
        reports_dir=reports_dir,
        build_root=build_root,
        build_info=build_info,
    )

    return build_info, build_root, reports_dir, [], []


def _sync_jenkins_artifacts(
    *,
    job_url: str,
    username: str,
    api_token: str,
    cache_root: Path,
    verify_tls: bool,
    build_selector: str,
    patterns: List[str],
) -> Tuple[Dict[str, Any], Path, Path, List[str], List[Dict[str, Any]]]:
    """
    Jenkins build artifacts -> local cache download + viewer summary 생성
    - build_root: cache_root/jenkins/<job_slug>/build_<n>
    - reports_dir: build_root/reports
    """
    client = JenkinsClient(
        job_url=_norm_job_url(job_url),
        username=username,
        api_token=api_token,
        timeout_sec=30,
        verify_ssl=bool(verify_tls),
    )

    build, artifacts = client.list_artifacts(build_selector or "lastSuccessfulBuild")
    if getattr(build, "number", -1) < 0:
        raise RuntimeError("빌드 정보 조회 실패")

    job_slug = _job_slug(job_url)
    build_root = (cache_root / "jenkins" / job_slug / f"build_{build.number}").resolve()
    build_root.mkdir(parents=True, exist_ok=True)

    want = client.filter_artifacts(artifacts, patterns or [])
    downloaded: List[str] = []

    for a in want:
        rel = getattr(a, "relativePath", "")
        dst = _safe_artifact_path(build_root, str(rel))
        if not dst:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        client.download_artifact(a, str(dst))
        try:
            downloaded.append(dst.resolve().relative_to(Path(build_root).resolve()).as_posix())
        except Exception:
            downloaded.append(str(rel).replace("\\", "/"))

    reports_dir = _detect_reports_dir(build_root)
    reports_dir.mkdir(parents=True, exist_ok=True)

    build_info: Dict[str, Any] = {
        "number": int(getattr(build, "number", -1)),
        "result": getattr(build, "result", None),
        "timestamp": getattr(build, "timestamp", None),
        "url": getattr(build, "url", None),
        "job_url": job_url,
    }

    # viewer summary 생성
    jenkins_adapter.ensure_gui_summary(
        reports_dir=reports_dir,
        build_root=build_root,
        build_info=build_info,
    )

    # function change summary (Jenkins Viewer)
    try:
        prev_build_dir = gui_utils.find_prev_build_dir(build_root)
        prev_reports_dir = _detect_reports_dir(prev_build_dir) if prev_build_dir else None
        enable_ai = bool(getattr(config, "JENKINS_FUNCTION_AI_SUMMARY_DEFAULT", True))
        artifacts_list = [
            {"fileName": x.fileName, "relativePath": x.relativePath}
            for x in artifacts
            if hasattr(x, "fileName") and hasattr(x, "relativePath")
        ]
        artifacts_hash = gui_utils.compute_artifacts_hash(artifacts_list)
        gui_utils.generate_function_change_summary(
            current_report_dir=reports_dir,
            prev_report_dir=prev_reports_dir,
            output_dir=reports_dir,
            build_id=str(build_info.get("number") or ""),
            artifacts_hash=artifacts_hash,
            enable_ai=enable_ai,
            oai_config_path=getattr(config, "DEFAULT_OAI_CONFIG_PATH", None),
            limit=50,
        )
    except Exception:
        pass

    # update summary with build_id/artifacts_hash for traceability
    try:
        summary_path = reports_dir / "analysis_summary.json"
        if summary_path.exists():
            s = gui_utils.load_json(summary_path, default={})
            if isinstance(s, dict):
                s["build_id"] = str(build_info.get("number") or "")
                s["artifacts_hash"] = artifacts_hash
                gui_utils.save_json(summary_path, s)
    except Exception:
        pass

    arts = [{"fileName": x.fileName, "relativePath": x.relativePath, "url": x.url} for x in artifacts]
    return build_info, build_root, reports_dir, downloaded, arts


__all__ = ["_sync_local_reports", "_sync_jenkins_artifacts"]
