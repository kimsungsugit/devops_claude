from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional


def _read_json(path: Path, default: Any) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _norm_job_url(job_url: str) -> str:
    u = (job_url or "").strip()
    if not u:
        return ""
    return u if u.endswith("/") else (u + "/")


def _job_slug(job_url: str) -> str:
    u = _norm_job_url(job_url).rstrip("/")
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", u) or "job"


def _sanitize_relpath(rel: str) -> str:
    """Legacy helper (kept for backward compatibility)."""
    rel = (rel or "").replace("\\", "/").lstrip("/")
    return rel


def _safe_artifact_path(build_root: "Path", rel: str) -> "Path|None":
    """Create a safe destination path under build_root for a Jenkins artifact."""
    try:
        from pathlib import PurePosixPath
    except Exception:
        PurePosixPath = None  # type: ignore

    raw = (rel or "").replace("\\", "/").strip()
    if not raw:
        return None
    if raw.startswith("/") or raw.startswith("~"):
        return None
    if re.match(r"^[A-Za-z]:", raw):
        return None

    parts = []
    if PurePosixPath is not None:
        p = PurePosixPath(raw)
        for part in p.parts:
            if part in ("", "."):
                continue
            if part == "..":
                return None
            parts.append(part)
    else:
        for part in raw.split("/"):
            if not part or part == ".":
                continue
            if part == "..":
                return None
            parts.append(part)

    safe_rel = "/".join(parts) if parts else ""
    if not safe_rel:
        return None

    try:
        br = Path(build_root).resolve()
        out = (br / safe_rel).resolve()
        if not out.is_relative_to(br):
            return None
        return out
    except Exception:
        return None


def _detect_reports_dir(build_root: Path) -> Path:
    """Pick reports directory under build_root without hardcoding."""
    for name in ("reports", "report", "REPORTS", "Report"):
        cand = (build_root / name).resolve()
        if cand.exists() and cand.is_dir():
            return cand
    return (build_root / "reports").resolve()


def _guess_project_root(build_root: Optional[Path], reports_dir: Optional[Path]) -> str:
    """Heuristic project_root selection for synced Jenkins artifacts."""
    broot = Path(build_root).resolve() if build_root else None
    rdir = Path(reports_dir).resolve() if reports_dir else None

    summary = {}
    if rdir and (rdir / "analysis_summary.json").exists():
        try:
            summary = _read_json(rdir / "analysis_summary.json", default={})
        except Exception:
            summary = {}

    if isinstance(summary, dict):
        paths = summary.get("paths") or {}
        if isinstance(paths, dict):
            pr = paths.get("project_root") or paths.get("root") or ""
            if pr:
                try:
                    return str(Path(str(pr)).resolve())
                except Exception:
                    return str(pr)
        pr2 = summary.get("project_root") or ""
        if pr2:
            try:
                return str(Path(str(pr2)).resolve())
            except Exception:
                return str(pr2)

    jscan = None
    if isinstance(summary, dict) and isinstance(summary.get("jenkins_scan"), dict):
        jscan = summary.get("jenkins_scan")
    elif rdir and (rdir / "jenkins_scan.json").exists():
        try:
            jscan = _read_json(rdir / "jenkins_scan.json", default={})
        except Exception:
            jscan = None
    if broot and isinstance(jscan, dict):
        rels = jscan.get("source_roots")
        if isinstance(rels, list):
            for rel in rels:
                if not rel:
                    continue
                try:
                    cand = (broot / str(rel)).resolve()
                    if cand.exists() and cand.is_dir():
                        return str(cand)
                except Exception:
                    continue

    if broot:
        for rel in (
            "svn_wc",
            "svn_wc/Sources",
            "svn_wc/Sources/APP",
            "svn_wc/Sources/App",
            "svn_wc/source",
            "svn_wc/src",
        ):
            cand = broot / rel
            if cand.exists() and cand.is_dir():
                return str(cand.resolve())

    for base in [broot, rdir, (rdir.parent if rdir else None)]:
        if not base:
            continue
        for rel in (
            "app/PDSM/Sources",
            "app/PDSM/Source",
            "app/PDSM/src",
            "app/Sources",
            "Sources",
            "source",
            "src",
        ):
            cand = Path(base) / rel
            if cand.exists() and cand.is_dir():
                return str(cand.resolve())

    for base in [broot, (broot.parent if broot else None), rdir]:
        if not base:
            continue
        for name in ("workspace", "repo", "source", "src", "project", "code"):
            cand = Path(base) / name
            if cand.exists() and cand.is_dir():
                return str(cand.resolve())

    return str((broot or rdir or Path(".")).resolve())


__all__ = [
    "_norm_job_url",
    "_job_slug",
    "_sanitize_relpath",
    "_safe_artifact_path",
    "_detect_reports_dir",
    "_guess_project_root",
]
