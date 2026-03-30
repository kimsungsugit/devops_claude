from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable

import config

from backend.services.jenkins_client import JenkinsClient, JenkinsServerClient
from backend.services.jenkins_adapter import ensure_frontend_summary
from backend.services.local_service import run_git, run_svn
from backend.services.jenkins_helpers import _detect_reports_dir, _job_slug, _norm_job_url, _safe_artifact_path


def list_jobs(
    *,
    base_url: str,
    username: str,
    api_token: str,
    recursive: bool = True,
    max_depth: int = 2,
    verify_tls: bool = True,
) -> List[Dict[str, Any]]:
    srv = JenkinsServerClient(
        base_url=base_url,
        username=username,
        api_token=api_token,
        timeout_sec=30,
        verify_ssl=bool(verify_tls),
    )
    return [asdict(j) for j in srv.list_jobs(recursive=recursive, max_depth=max_depth)]


def list_builds(
    *,
    job_url: str,
    username: str,
    api_token: str,
    limit: int = 30,
    verify_tls: bool = True,
) -> List[Dict[str, Any]]:
    client = JenkinsClient(
        job_url=_norm_job_url(job_url),
        username=username,
        api_token=api_token,
        timeout_sec=30,
        verify_ssl=bool(verify_tls),
    )
    api = f"{client.job_url}api/json?tree=builds[number,result,timestamp,url,building,duration]"
    data = client._open_json(api)  # type: ignore[attr-defined]
    builds: List[Dict[str, Any]] = []
    for b in data.get("builds", []) or []:
        if not isinstance(b, dict):
            continue
        builds.append(
            {
                "number": b.get("number"),
                "result": b.get("result"),
                "timestamp": b.get("timestamp"),
                "url": b.get("url"),
                "building": b.get("building"),
                "duration": b.get("duration"),
            }
        )
    return builds[: max(1, int(limit))]


def _dir_has_entries(path: Path) -> bool:
    try:
        return any(path.iterdir())
    except Exception:
        return False


def ensure_source_checkout(
    *,
    build_root: Path,
    client: JenkinsClient,
    build_selector: str,
    progress_cb: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    source_dir = Path(build_root) / "source"
    if source_dir.exists() and _dir_has_entries(source_dir):
        if progress_cb:
            try:
                progress_cb("scm_done", {"path": str(source_dir), "skipped": True})
            except Exception:
                pass
        return {"ok": True, "path": str(source_dir), "scm": "cached"}
    try:
        meta = client.get_scm_meta(build_selector=build_selector or "lastSuccessfulBuild")
    except Exception:
        meta = {}
    repo_urls = meta.get("repo_urls") if isinstance(meta, dict) else None
    if not repo_urls:
        if progress_cb:
            try:
                progress_cb("scm_failed", {"reason": "repo_url_missing"})
            except Exception:
                pass
        return {"ok": False, "error": "repo_url_missing", "meta": meta}
    repo_url = str(repo_urls[0])
    scm = str(meta.get("scm") or meta.get("scm_type") or "git").lower()
    branch = str(meta.get("git_branch") or meta.get("scm_branch") or "").strip()
    revision = str(meta.get("scm_revision") or meta.get("git_commit") or meta.get("svn_revision") or "").strip()
    if progress_cb:
        try:
            progress_cb(
                "scm_clone",
                {"repo_url": repo_url, "branch": branch, "scm": scm},
            )
        except Exception:
            pass
    if scm == "svn":
        result = run_svn(
            project_root=str(build_root),
            workdir_rel="source",
            action="checkout",
            repo_url=repo_url,
            revision=revision,
        )
    else:
        result = run_git(
            project_root=str(build_root),
            workdir_rel="source",
            action="clone",
            repo_url=repo_url,
            branch=branch,
            depth=0,
        )
    if result.get("rc") != 0:
        if progress_cb:
            try:
                progress_cb(
                    "scm_failed",
                    {"reason": "checkout_failed", "output": result.get("output", "")},
                )
            except Exception:
                pass
        return {
            "ok": False,
            "error": "checkout_failed",
            "scm": scm,
            "repo_url": repo_url,
            "branch": branch,
            "revision": revision,
            "output": result.get("output", ""),
        }
    if progress_cb:
        try:
            progress_cb("scm_done", {"path": str(source_dir)})
        except Exception:
            pass
    return {
        "ok": True,
        "path": str(source_dir),
        "scm": scm,
        "repo_url": repo_url,
        "branch": branch,
        "revision": revision,
    }


def get_build_info(
    *,
    job_url: str,
    username: str,
    api_token: str,
    build_selector: str,
    verify_tls: bool = True,
) -> Dict[str, Any]:
    client = JenkinsClient(
        job_url=_norm_job_url(job_url),
        username=username,
        api_token=api_token,
        timeout_sec=30,
        verify_ssl=bool(verify_tls),
    )
    build, artifacts = client.list_artifacts(build_selector or "lastSuccessfulBuild")
    return {
        "build": asdict(build),
        "artifacts": [asdict(a) for a in artifacts],
    }


def sync_local_reports(*, job_url: str, local_reports_dir: Path) -> Tuple[Dict[str, Any], Path, Path, List[str], List[Dict[str, Any]]]:
    reports_dir = Path(local_reports_dir).resolve()
    build_root = reports_dir.parent
    build_info: Dict[str, Any] = {
        "number": -1,
        "result": "LOCAL",
        "timestamp": None,
        "url": "",
        "job_url": job_url,
    }
    ensure_frontend_summary(
        reports_dir=reports_dir,
        build_root=build_root,
        build_info=build_info,
        progress_cb=progress_cb,
    )
    return build_info, build_root, reports_dir, [], []


def sync_jenkins_artifacts(
    *,
    job_url: str,
    username: str,
    api_token: str,
    cache_root: Path,
    verify_tls: bool,
    build_selector: str,
    patterns: List[str],
    progress_cb: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    scan_mode: Optional[str] = None,
    scan_max_files: Optional[int] = None,
) -> Tuple[Dict[str, Any], Path, Path, List[str], List[Dict[str, Any]]]:
    client = JenkinsClient(
        job_url=_norm_job_url(job_url),
        username=username,
        api_token=api_token,
        timeout_sec=30,
        verify_ssl=bool(verify_tls),
    )

    build, artifacts = client.list_artifacts(build_selector or "lastSuccessfulBuild")
    if progress_cb:
        try:
            progress_cb("list_artifacts", {"count": len(artifacts)})
        except Exception:
            pass
    if getattr(build, "number", -1) < 0:
        raise RuntimeError("빌드 정보 조회 실패")

    job_slug = _job_slug(job_url)
    build_root = (Path(cache_root) / "jenkins" / job_slug / f"build_{build.number}").resolve()
    build_root.mkdir(parents=True, exist_ok=True)

    want = client.filter_artifacts(artifacts, patterns or [])
    if progress_cb:
        try:
            progress_cb("download_start", {"total": len(want)})
        except Exception:
            pass
    downloaded: List[str] = []

    total = max(1, len(want))
    for idx, a in enumerate(want):
        rel = getattr(a, "relativePath", "")
        if progress_cb:
            try:
                progress_cb(
                    "download",
                    {"current": idx + 1, "total": total, "file": str(rel)},
                )
            except Exception:
                pass
        dst = _safe_artifact_path(build_root, str(rel))
        if not dst:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        client.download_artifact(a, str(dst))
        try:
            downloaded.append(dst.resolve().relative_to(Path(build_root).resolve()).as_posix())
        except Exception:
            downloaded.append(str(rel).replace("\\", "/"))

    try:
        console_max = int(getattr(config, "JENKINS_CONSOLE_LOG_MAX_BYTES", 2_000_000))
    except Exception:
        console_max = 2_000_000
    try:
        console_path = build_root / "jenkins_console.log"
        if progress_cb:
            try:
                progress_cb("download_console", {"path": str(console_path.name)})
            except Exception:
                pass
        client.download_console_log(
            build_selector=build_selector or "lastSuccessfulBuild",
            dst_path=str(console_path),
            max_bytes=console_max,
        )
        try:
            downloaded.append(console_path.resolve().relative_to(Path(build_root).resolve()).as_posix())
        except Exception:
            downloaded.append(str(console_path.name))
    except Exception:
        pass

    ensure_source_checkout(
        build_root=build_root,
        client=client,
        build_selector=build_selector,
        progress_cb=progress_cb,
    )

    reports_dir = _detect_reports_dir(build_root)
    reports_dir.mkdir(parents=True, exist_ok=True)

    build_info: Dict[str, Any] = {
        "number": int(getattr(build, "number", -1)),
        "result": getattr(build, "result", None),
        "timestamp": getattr(build, "timestamp", None),
        "url": getattr(build, "url", None),
        "job_url": job_url,
    }

    if progress_cb:
        try:
            progress_cb("scan_start", {})
        except Exception:
            pass
    ensure_frontend_summary(
        reports_dir=reports_dir,
        build_root=build_root,
        build_info=build_info,
        progress_cb=progress_cb,
        scan_mode=scan_mode,
        scan_max_files=scan_max_files,
    )
    if progress_cb:
        try:
            progress_cb("scan_done", {})
        except Exception:
            pass

    arts = [asdict(x) for x in artifacts]
    return build_info, build_root, reports_dir, downloaded, arts


def list_cached_builds(*, job_url: str, cache_root: Path) -> List[Dict[str, Any]]:
    job_slug = _job_slug(job_url)
    job_cache_dir = (Path(cache_root) / "jenkins" / job_slug).resolve()
    rows: List[Dict[str, Any]] = []
    if not job_cache_dir.exists():
        return rows
    for p in sorted(job_cache_dir.glob("build_*")):
        if not p.is_dir():
            continue
        num = -1
        try:
            num = int(p.name.replace("build_", ""))
        except Exception:
            pass
        reports_dir = _detect_reports_dir(p)
        rows.append(
            {
                "build_root": str(p),
                "build_number": num,
                "reports_dir": str(reports_dir),
                "mtime": p.stat().st_mtime,
            }
        )
    rows.sort(key=lambda x: x.get("build_number", -1), reverse=True)
    return rows
