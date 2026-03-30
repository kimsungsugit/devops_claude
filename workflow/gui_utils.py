# /app/workflow/gui_utils.py
# -*- coding: utf-8 -*-
# Workflow 보조 유틸 (Logic Layer)
# v30.7: Lizard 대상 수집 안정화, 기본 exclude 강화, 대형 트리 분석 지연 완화

from __future__ import annotations

import json
import shutil
import threading
import time
import os
import re
import subprocess
import sys
import platform
import hashlib
import uuid
import zipfile
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional, Callable

import xml.etree.ElementTree as ET
import pandas as pd
import lizard  # 코드 복잡도 분석

import workflow       # 실제 파이프라인 (workflow.run_cli 노출)
import report_generator
import config
from utils.log import get_logger

_logger = get_logger(__name__)


# -----------------------------
# 경로 / 파일 유틸
# -----------------------------

def get_paths(root_dir: str, report_dir_name: str) -> Dict[str, Path]:
    """
    프로젝트 루트와 리포트 디렉터리 기준으로
    자주 쓰는 경로들을 한 번에 계산해서 반환하는 함수
    """
    root = Path(root_dir).resolve()
    report_dir = (root / report_dir_name).resolve()

    # 기본 리포트 디렉터리 생성
    report_dir.mkdir(parents=True, exist_ok=True)

    paths: Dict[str, Path] = {
        "ROOT": root,
        "REPORT": report_dir,
        "SUMMARY": report_dir / "analysis_summary.json",
        "FINDINGS": report_dir / "findings_flat.json",
        "FINDINGS_PROD": report_dir / "findings_flat_prod.json",
        "FINDINGS_TEST": report_dir / "findings_flat_test.json",
        "CPP_FINDINGS": report_dir / "cppcheck_findings.json",
        "HISTORY": report_dir / "history.json",
        "COMPLEXITY": report_dir / "complexity.csv",
        "LIZARD_LOG": report_dir / "lizard_audit.log",
        "DOCS": report_dir / "docs" / "html" / "index.html",
        "PDF": report_dir / "report.pdf",
        "SYSTEM_LOG": report_dir / "system.log",
        "JENKINS_SCAN": report_dir / "jenkins_scan.json",
        "STATUS": report_dir / "status.json",
        "SUPPRESSIONS": report_dir / "suppressions.txt",
    }
    
    # ------------------------------------------------------------------
    # Backward-compatible aliases (older app.py / tabs used different keys)
    # ------------------------------------------------------------------
    # Old key style
    paths.setdefault("analysis_summary", paths.get("SUMMARY", report_dir / "analysis_summary.json"))
    paths.setdefault("analysis_findings", paths.get("FINDINGS", report_dir / "findings_flat.json"))
    paths.setdefault("analysis_findings_prod", paths.get("FINDINGS_PROD", report_dir / "findings_flat_prod.json"))
    paths.setdefault("analysis_findings_test", paths.get("FINDINGS_TEST", report_dir / "findings_flat_test.json"))
    paths.setdefault("cpp_findings", paths.get("CPP_FINDINGS", report_dir / "cppcheck_findings.json"))
    paths.setdefault("history", paths.get("HISTORY", report_dir / "history.json"))
    paths.setdefault("status", paths.get("STATUS", report_dir / "status.json"))
    paths.setdefault("system_log", paths.get("SYSTEM_LOG", report_dir / "system.log"))
    paths.setdefault("complexity", paths.get("COMPLEXITY", report_dir / "complexity.csv"))
    paths.setdefault("docs_index", paths.get("DOCS", report_dir / "docs" / "html" / "index.html"))
    paths.setdefault("report_pdf", paths.get("PDF", report_dir / "report.pdf"))
    paths.setdefault("suppressions", paths.get("SUPPRESSIONS", report_dir / "suppressions.txt"))
    paths.setdefault("jenkins_scan", paths.get("JENKINS_SCAN", report_dir / "jenkins_scan.json"))
    
    # New key style mirror for convenience (no-op if already exists)
    paths.setdefault("SUMMARY", paths.get("analysis_summary", report_dir / "analysis_summary.json"))
    paths.setdefault("FINDINGS", paths.get("analysis_findings", report_dir / "findings_flat.json"))
    paths.setdefault("HISTORY", paths.get("history", report_dir / "history.json"))
    paths.setdefault("STATUS", paths.get("status", report_dir / "status.json"))

    return paths


def _find_cmake_root(root: Path, max_depth: int = 4) -> Optional[Path]:
    """
    root 하위에서 CMakeLists.txt 위치를 탐색해 적절한 루트를 반환
    - depth 제한으로 과도한 탐색 방지
    - build/reports/.git 등은 제외
    """
    try:
        root = Path(root).resolve()
        exclude_names = {"build", "reports", ".git", ".svn", "node_modules", ".venv", "venv", "__pycache__"}
        candidates: List[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            rel = Path(dirpath).resolve().relative_to(root)
            depth = len(rel.parts)
            if depth > max_depth:
                dirnames[:] = []
                continue
            if any(p in exclude_names for p in rel.parts):
                dirnames[:] = []
                continue
            if "CMakeLists.txt" in filenames:
                candidates.append(Path(dirpath))
        if not candidates:
            return None
        candidates.sort(key=lambda p: (len(p.resolve().relative_to(root).parts), str(p)))
        return candidates[0].resolve()
    except Exception:
        return None


_SESSION_STATE: Dict[str, Any] = {}


def get_session_id() -> str:
    sid = _SESSION_STATE.get("session_id")
    if not sid:
        sid = uuid.uuid4().hex[:8]
        _SESSION_STATE["session_id"] = sid
    return str(sid)


def new_session_id() -> str:
    sid = uuid.uuid4().hex[:8]
    _SESSION_STATE["session_id"] = sid
    return str(sid)


def get_session_report_dir(base_report_dir: str) -> str:
    base = Path(str(base_report_dir or "reports")).as_posix().rstrip("/")
    sid = get_session_id()
    session_dir = str(Path(base) / "sessions" / sid)
    _SESSION_STATE["session_report_dir"] = session_dir
    _SESSION_STATE["session_report_base"] = base
    return session_dir


def _session_meta_path(session_dir: Path) -> Path:
    return session_dir / "session_meta.json"


def load_session_meta(session_dir: Path) -> Dict[str, Any]:
    try:
        meta_path = _session_meta_path(session_dir)
        if meta_path.exists():
            return load_json(meta_path, default={})
    except Exception:
        return {}
    return {}


def save_session_meta(session_dir: Path, meta: Dict[str, Any]) -> None:
    try:
        meta_path = _session_meta_path(session_dir)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
        save_json(meta_path, meta)
    except Exception:
        pass


def set_session_name(session_dir: Path, name: str) -> None:
    meta = load_session_meta(session_dir)
    meta["name"] = str(name or "").strip()
    save_session_meta(session_dir, meta)


def touch_session(session_dir: Path) -> None:
    meta = load_session_meta(session_dir)
    meta["last_opened"] = datetime.now().isoformat(timespec="seconds")
    save_session_meta(session_dir, meta)


def list_session_reports(base_report_dir: str) -> List[Dict[str, Any]]:
    base = Path(str(base_report_dir or "reports")).resolve()
    sessions_dir = base / "sessions"
    if not sessions_dir.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for p in sessions_dir.iterdir():
        if not p.is_dir():
            continue
        summary_path = p / "analysis_summary.json"
        meta = load_session_meta(p)
        generated_at = ""
        if summary_path.exists():
            try:
                data = load_json(summary_path, default={})
                if isinstance(data, dict):
                    generated_at = str(data.get("generated_at") or "")
            except Exception:
                generated_at = ""
        ts = generated_at
        if not ts:
            try:
                ts = datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
            except Exception:
                ts = ""
        rows.append(
            {
                "id": p.name,
                "path": str(p),
                "generated_at": ts,
                "name": str(meta.get("name") or ""),
                "last_opened": str(meta.get("last_opened") or ""),
            }
        )
    rows.sort(key=lambda x: x.get("generated_at") or "", reverse=True)
    return rows


def cleanup_sessions(base_report_dir: str, keep_days: int, *, keep_ids: Optional[List[str]] = None) -> int:
    if keep_days <= 0:
        return 0
    base = Path(str(base_report_dir or "reports")).resolve()
    sessions_dir = base / "sessions"
    if not sessions_dir.exists():
        return 0
    keep_ids = keep_ids or []
    cutoff = datetime.now().timestamp() - (keep_days * 86400)
    removed = 0
    for p in sessions_dir.iterdir():
        if not p.is_dir():
            continue
        if p.name in keep_ids:
            continue
        try:
            meta = load_session_meta(p)
            ts = meta.get("last_opened") or meta.get("updated_at") or ""
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    mtime = dt.timestamp()
                except Exception:
                    mtime = p.stat().st_mtime
            else:
                mtime = p.stat().st_mtime
            if mtime < cutoff:
                import shutil
                shutil.rmtree(p)
                removed += 1
        except Exception:
            continue
    return removed


def export_session_archive(session_dir: Path, out_dir: Path) -> Optional[Path]:
    try:
        if not session_dir.exists() or not session_dir.is_dir():
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"session_{session_dir.name}_{ts}.zip"
        out_path = out_dir / name
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in session_dir.rglob("*"):
                if p.is_file():
                    rel = p.relative_to(session_dir)
                    zf.write(p, arcname=str(rel))
        meta = load_session_meta(session_dir)
        meta["last_export"] = datetime.now().isoformat(timespec="seconds")
        meta["last_export_path"] = str(out_path)
        save_session_meta(session_dir, meta)
        return out_path
    except Exception:
        return None


def list_session_exports(base_report_dir: str, *, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
    base = Path(str(base_report_dir or "reports")).resolve()
    exports_dir = base / "exports"
    if not exports_dir.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for p in exports_dir.glob("session_*.zip"):
        try:
            name = p.name
            sid = name.split("_")[1] if "_" in name else ""
            if session_id and sid != session_id:
                continue
            rows.append(
                {
                    "file": name,
                    "path": str(p),
                    "session_id": sid,
                    "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                    "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                }
            )
        except Exception:
            continue
    rows.sort(key=lambda x: x.get("mtime") or "", reverse=True)
    return rows


def load_json(path: Path | str, default: Any = None) -> Any:
    if default is None:
        default = {}
    p = Path(path)
    if not p.exists():
        return default
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path | str, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(p)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


# -----------------------------
# 프론트 프로파일(설정) 저장/불러오기
# -----------------------------

SETTINGS_FILE = Path.home() / ".devops_gui_profiles.json"


def _load_raw_profiles() -> Dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return {"profiles": {}, "last_profile": None, "jenkins_project_paths": {}}
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"profiles": {}, "last_profile": None, "jenkins_project_paths": {}}
    if not isinstance(raw, dict):
        return {"profiles": {}, "last_profile": None, "jenkins_project_paths": {}}
    raw.setdefault("profiles", {})
    raw.setdefault("last_profile", None)
    raw.setdefault("jenkins_project_paths", {})
    return raw


def load_all_profiles() -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    raw = _load_raw_profiles()
    profiles = raw.get("profiles", {}) or {}
    if not isinstance(profiles, dict):
        profiles = {}
    last = raw.get("last_profile")
    if last not in profiles:
        last = None
    return profiles, last


def load_profile(name: str) -> Dict[str, Any]:
    profiles, _ = load_all_profiles()
    prof = profiles.get(name, {})
    return prof if isinstance(prof, dict) else {}


def save_profile(name: str, cfg: Dict[str, Any]) -> None:
    raw = _load_raw_profiles()

    # 리스트형 옵션은 저장 시 리스트로 정규화
    def _split_csv(val: Any) -> List[str]:
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            return [s.strip() for s in val.split(",") if s.strip()]
        return []

    profiles = raw.get("profiles", {})
    profiles[name] = {
        "project_root": cfg.get("project_root"),
        "report_dir": cfg.get("report_dir"),
        "targets_glob": cfg.get("targets_glob"),
        "git_incremental": bool(cfg.get("git_incremental", False)),
        "git_base_ref": cfg.get("git_base_ref"),
        "scm_mode": cfg.get("scm_mode"),
        "svn_base_ref": cfg.get("svn_base_ref"),
        "exclude_dirs": _split_csv(cfg.get("exclude_dirs")),
        "include_paths": _split_csv(cfg.get("include_paths")),
        "clang_checks": _split_csv(cfg.get("clang_checks")),
        "cppcheck_levels": cfg.get("cppcheck_levels", []),
        "quality_preset": cfg.get("quality_preset"),
        "do_build": bool(cfg.get("do_build", False)),
        "build_strategy": cfg.get("build_strategy"),
        "build_fallback": cfg.get("build_fallback"),
        "do_asan": bool(cfg.get("do_asan", False)),
        "do_fuzz": bool(cfg.get("do_fuzz", False)),
        "do_qemu": bool(cfg.get("do_qemu", False)),
        "do_docs": bool(cfg.get("do_docs", False)),
        "do_clang_tidy": bool(cfg.get("do_clang_tidy", False)),
        "enable_semgrep": bool(cfg.get("enable_semgrep", False)),
        "semgrep_config": cfg.get("semgrep_config"),
        "target_arch": cfg.get("target_arch"),
        "mcu_preset": cfg.get("mcu_preset"),
        "toolchain_profile": cfg.get("toolchain_profile"),
        "cmake_toolchain_file": cfg.get("cmake_toolchain_file"),
        "cmake_generator": cfg.get("cmake_generator"),
        "target_macros": cfg.get("target_macros"),
        "complexity_threshold": int(cfg.get("complexity_threshold", getattr(config, "DEFAULT_COMPLEXITY_THRESHOLD", 10))),
        "enable_agent": bool(cfg.get("enable_agent", False)),
        "enable_test_gen": bool(cfg.get("enable_test_gen", False)),
        "auto_run_tests": bool(cfg.get("auto_run_tests", False)),
        "max_iterations": int(cfg.get("max_iterations", 3)),
        "oai_config_path": cfg.get("oai_config_path"),
        "llm_model": cfg.get("llm_model"),
        "agent_roles": _split_csv(cfg.get("agent_roles")),
        "agent_run_mode": cfg.get("agent_run_mode"),
        "agent_review": bool(cfg.get("agent_review", True)),
        "agent_rag": bool(cfg.get("agent_rag", True)),
        "agent_rag_top_k": int(cfg.get("agent_rag_top_k", getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3))),
        "agent_max_steps": int(cfg.get("agent_max_steps", getattr(config, "AGENT_MAX_STEPS_DEFAULT", 3))),
        "auto_fix_scope": cfg.get("auto_fix_scope", []),
        "enable_domain_tests": bool(cfg.get("enable_domain_tests", False)),
        "domain_tests_auto": bool(cfg.get("domain_tests_auto", getattr(config, "DOMAIN_TESTS_AUTO", True))),
        "domain_targets": _split_csv(cfg.get("domain_targets")),
        "agent_patch_mode": cfg.get("agent_patch_mode"),
        "source_priority": _split_csv(cfg.get("source_priority")),
        "local_source_roots": _split_csv(cfg.get("local_source_roots")),
        "artifact_success_rule": cfg.get("artifact_success_rule"),
        "artifact_source_root": cfg.get("artifact_source_root"),
        "rag_ingest_enable": bool(cfg.get("rag_ingest_enable", True)),
        "vc_reports_paths": _split_csv(cfg.get("vc_reports_paths")),
        "uds_spec_paths": _split_csv(cfg.get("uds_spec_paths")),
        "req_docs_paths": _split_csv(cfg.get("req_docs_paths")),
        "codebase_paths": _split_csv(cfg.get("codebase_paths")),
    }
    raw["profiles"] = profiles
    raw["last_profile"] = name
    raw["updated_at"] = datetime.now().isoformat()

    SETTINGS_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")


# 🔹 여기부터 새로 추가
def set_last_profile(name: Optional[str]) -> None:
    """
    마지막으로 사용한 프로파일 이름만 업데이트하는 헬퍼
    - 사이드바에서 프로파일 선택/저장 시 호출
    """
    raw = _load_raw_profiles()
    raw["last_profile"] = name
    raw["updated_at"] = datetime.now().isoformat()
    SETTINGS_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
# 🔹 여기까지 추가

def get_settings_file_path() -> Path:
    return SETTINGS_FILE


def load_jenkins_project_paths() -> Dict[str, List[str]]:
    raw = _load_raw_profiles()
    paths = raw.get("jenkins_project_paths", {})
    if not isinstance(paths, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for k, v in paths.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, str):
            out[k] = [v]
        elif isinstance(v, list):
            clean = [str(x).strip() for x in v if isinstance(x, str) and str(x).strip()]
            if clean:
                out[k] = clean
    return out


def save_jenkins_project_paths(paths: Dict[str, List[str]]) -> None:
    raw = _load_raw_profiles()
    raw["jenkins_project_paths"] = paths
    SETTINGS_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")


# -----------------------------
# 로컬 폴더 선택 (OS 파일 다이얼로그)
# -----------------------------
def pick_directory(title: str = "폴더 선택") -> str:
    """
    로컬 폴더 선택 다이얼로그를 띄우고 선택된 경로를 반환.
    - UI 환경이 아니면 빈 문자열 반환
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return ""

    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.wm_attributes("-topmost", 1)
        except Exception:
            pass
        path = filedialog.askdirectory(title=title) or ""
        root.destroy()
        return str(path)
    except Exception:
        try:
            root.destroy()
        except Exception:
            pass
        return ""


# -----------------------------
# Jenkins/소스 선택 보조
# -----------------------------
def _parse_list_str(val: Any) -> List[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    s = str(val or "").strip()
    if not s:
        return []
    items = [x.strip() for x in s.replace("\n", ",").split(",")]
    return [x for x in items if x]


def _has_source_indicators(root: Path, max_depth: int = 4) -> bool:
    try:
        if not root.exists() or not root.is_dir():
            return False
    except Exception:
        return False

    # Quick indicators
    for name in ("CMakeLists.txt", "Makefile", "meson.build"):
        if (root / name).exists():
            return True
    for sub in ("src", "source", "Sources", "include", "libs", "app"):
        if (root / sub).exists():
            return True

    exts = (".c", ".h", ".cpp", ".hpp")
    base_depth = len(root.parts)
    try:
        for r, d, f in os.walk(root):
            depth = len(Path(r).parts) - base_depth
            if depth > max_depth:
                d[:] = []
                continue
            for fn in f:
                if fn.endswith(exts):
                    return True
    except Exception:
        return False
    return False


def detect_artifact_source_root(build_root: Path, reports_dir: Optional[Path] = None) -> str:
    broot = Path(build_root).resolve()
    rdir = Path(reports_dir).resolve() if reports_dir else None

    # 1) Jenkins scan hint
    if rdir and (rdir / "jenkins_scan.json").exists():
        try:
            jscan = load_json(rdir / "jenkins_scan.json", default={})
            rels = jscan.get("source_roots") if isinstance(jscan, dict) else None
            if isinstance(rels, list):
                for rel in rels:
                    if not rel:
                        continue
                    cand = (broot / str(rel)).resolve()
                    if cand.exists() and cand.is_dir() and _has_source_indicators(cand):
                        return str(cand)
        except Exception:
            pass

    # 2) Common layout hints
    for rel in (
        "svn_wc",
        "svn_wc/Sources",
        "svn_wc/Sources/APP",
        "svn_wc/Sources/App",
        "svn_wc/source",
        "svn_wc/src",
        "workspace",
        "repo",
        "project",
        "code",
        "app",
        "app/Sources",
        "app/source",
        "app/src",
        "Sources",
        "source",
        "src",
    ):
        cand = (broot / rel).resolve()
        if cand.exists() and cand.is_dir() and _has_source_indicators(cand):
            return str(cand)

    # 3) build_root 자체 검사
    if _has_source_indicators(broot):
        return str(broot)

    return ""


def _artifact_marker_success(reports_dir: Optional[Path]) -> bool:
    if not reports_dir:
        return False
    rdir = Path(reports_dir).resolve()
    # analysis_summary.json 우선
    try:
        summary = load_json(rdir / "analysis_summary.json", default={})
        if isinstance(summary, dict):
            exit_code = summary.get("exit_code")
            if exit_code is not None and int(exit_code) == 0:
                return True
    except Exception:
        pass

    # runner status
    try:
        status = load_json(rdir / "run_status.json", default={})
        if isinstance(status, dict):
            if str(status.get("state")) == "completed" and int(status.get("exit_code", 1)) == 0:
                return True
    except Exception:
        pass

    # system.log keyword
    try:
        log_path = rdir / "system.log"
        if log_path.exists():
            text = log_path.read_text(encoding="utf-8", errors="ignore")
            if "Exit Code: 0" in text or "exit_code=0" in text:
                return True
    except Exception:
        pass

    return False


def is_artifact_build_success(
    build_info: Optional[Dict[str, Any]],
    reports_dir: Optional[Path],
    success_rule: str = "either",
) -> bool:
    rule = (success_rule or "either").strip().lower()
    build_ok = False
    if isinstance(build_info, dict):
        result = str(build_info.get("result") or "").upper()
        build_ok = result in ("SUCCESS", "LOCAL")
    marker_ok = _artifact_marker_success(reports_dir)

    if rule == "jenkins_api":
        return build_ok
    if rule == "artifact_marker":
        return marker_ok
    return bool(build_ok or marker_ok)


def resolve_source_root(cfg: Dict[str, Any]) -> Dict[str, Any]:
    priority = _parse_list_str(cfg.get("source_priority")) or ["local"]
    priority = [p.strip().lower() for p in priority if p.strip()]
    build_root = cfg.get("artifact_build_root") or cfg.get("jenkins_build_root")
    reports_dir = cfg.get("artifact_reports_dir") or cfg.get("jenkins_reports_dir")
    build_info = cfg.get("artifact_build_info")
    success_rule = cfg.get("artifact_success_rule") or "either"
    prefer_artifact_root = str(cfg.get("artifact_source_root") or "").strip()

    # 1) artifact priority
    if "artifact" in priority and build_root:
        broot = Path(str(build_root)).expanduser().resolve()
        rdir = Path(str(reports_dir)).expanduser().resolve() if reports_dir else None
        if broot.exists() and broot.is_dir():
            if is_artifact_build_success(build_info, rdir, success_rule=success_rule):
                if prefer_artifact_root:
                    try:
                        p = Path(prefer_artifact_root).expanduser().resolve()
                        if p.exists() and p.is_dir():
                            return {"root": str(p), "source": "artifact", "reason": "manual_override"}
                    except Exception:
                        pass
                detected = detect_artifact_source_root(broot, rdir)
                if detected:
                    return {"root": detected, "source": "artifact", "reason": "auto_detect"}

    # 2) server/local priority
    if "server" in priority or "local" in priority:
        local_roots = _parse_list_str(cfg.get("local_source_roots"))
        for r in local_roots:
            try:
                p = Path(r).expanduser().resolve()
                if p.exists() and p.is_dir():
                    return {"root": str(p), "source": "local", "reason": "fallback_list"}
            except Exception:
                continue

    # 3) fallback to cfg project_root
    root = str(cfg.get("project_root") or ".")
    return {"root": root, "source": "cfg", "reason": "default"}


# -----------------------------
# Git / CI 보조 함수
# -----------------------------

def get_git_status(project_root: str | Path) -> Dict[str, Optional[str]]:
    """
    간단한 Git 상태 조회
    - 현재 브랜치
    - 최신 커밋 해시(짧게)
    - 워킹 트리 변경 여부(dirty)
    실패 시 각 항목은 None
    """
    root = Path(project_root or ".")
    info: Dict[str, Optional[str]] = {
        "branch": None,
        "commit": None,
        "dirty": None,
    }

    try:
        import subprocess

        # git 리포지터리가 아니면 바로 리턴
        if not (root / ".git").exists():
            return info

        # 현재 브랜치
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            )
            info["branch"] = res.stdout.strip() or None
        except Exception:
            pass

        # 최신 커밋 (짧은 해시)
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            )
            info["commit"] = res.stdout.strip() or None
        except Exception:
            pass

        # 변경사항 존재 여부
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            )
            dirty = bool(res.stdout.strip())
            info["dirty"] = "DIRTY" if dirty else "CLEAN"
        except Exception:
            pass

    except Exception:
        # git 명령이 없거나 기타 오류
        return info

    return info


def get_ci_env_info() -> Dict[str, Optional[str]]:
    """
    Jenkins 등 CI 환경에서 넘어오는 환경변수 요약
    - JENKINS_HOME 존재 여부로 Jenkins 감지
    - JOB_NAME / BUILD_NUMBER / BUILD_URL
    - GIT_BRANCH / GIT_COMMIT
    """
    env = os.environ
    return {
        "is_jenkins": env.get("JENKINS_HOME") is not None,
        "job_name": env.get("JOB_NAME"),
        "build_number": env.get("BUILD_NUMBER"),
        "build_url": env.get("BUILD_URL"),
        "git_branch": env.get("GIT_BRANCH"),
        "git_commit": env.get("GIT_COMMIT"),
    }


def get_svn_info(project_root: str | Path) -> Dict[str, Optional[str]]:
    """
    SVN 상태 조회 (작업복사본일 때만 유효)
    - url / revision / author / date / dirty
    """
    root = Path(project_root or ".")
    info: Dict[str, Optional[str]] = {
        "url": None,
        "revision": None,
        "author": None,
        "date": None,
        "dirty": None,
    }
    try:
        import subprocess

        if not (root / ".svn").exists():
            return info
        res = subprocess.run(
            ["svn", "info", "--show-item", "url"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return info
        info["url"] = res.stdout.strip() or None
        res = subprocess.run(
            ["svn", "info", "--show-item", "revision"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            info["revision"] = res.stdout.strip() or None
        res = subprocess.run(
            ["svn", "info", "--show-item", "last-changed-author"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            info["author"] = res.stdout.strip() or None
        res = subprocess.run(
            ["svn", "info", "--show-item", "last-changed-date"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            info["date"] = res.stdout.strip() or None
        res = subprocess.run(
            ["svn", "status", "--short"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            info["dirty"] = "DIRTY" if bool(res.stdout.strip()) else "CLEAN"
    except Exception:
        return info
    return info


def get_svn_recent_revisions(project_root: str | Path, limit: int = 20) -> List[Dict[str, str]]:
    """
    SVN 최근 로그 조회 (revision/author/date/message)
    """
    root = Path(project_root or ".")
    if not (root / ".svn").exists():
        return []
    try:
        import subprocess
        import xml.etree.ElementTree as ET

        res = subprocess.run(
            ["svn", "log", "-l", str(int(limit)), "--xml"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0 or not (res.stdout or "").strip():
            return []
        xml_text = res.stdout
        entries: List[Dict[str, str]] = []
        try:
            root_xml = ET.fromstring(xml_text)
        except Exception:
            return []
        url_prefix = None
        try:
            info = get_svn_info(project_root)
            if isinstance(info, dict):
                url_prefix = str(info.get("url") or "")
        except Exception:
            url_prefix = None
        if url_prefix:
            if "/trunk" in url_prefix:
                url_prefix = url_prefix.split("/trunk")[0]
            elif "/branches/" in url_prefix:
                url_prefix = url_prefix.split("/branches/")[0]
            elif "/tags/" in url_prefix:
                url_prefix = url_prefix.split("/tags/")[0]

        for logentry in root_xml.findall("logentry"):
            rev = logentry.attrib.get("revision", "")
            author = (logentry.findtext("author") or "").strip()
            date = (logentry.findtext("date") or "").strip()
            msg = (logentry.findtext("msg") or "").strip().splitlines()[0] if logentry.findtext("msg") else ""
            branch_url = ""
            try:
                for pnode in logentry.findall(".//path"):
                    if pnode is None or not pnode.text:
                        continue
                    ptxt = pnode.text.strip()
                    if not ptxt:
                        continue
                    if ptxt.startswith(("/trunk", "/branches/", "/tags/")):
                        if url_prefix:
                            branch_url = f"{url_prefix}{ptxt}"
                        else:
                            branch_url = ptxt
                        break
            except Exception:
                branch_url = ""
            entries.append(
                {
                    "revision": rev,
                    "author": author,
                    "date": date,
                    "message": msg,
                    "branch_url": branch_url,
                }
            )
        return entries
    except Exception:
        return []


# -----------------------------
# 커버리지 보조 함수
# -----------------------------


def normalize_rate_0_1(value):
    """Normalize a coverage rate that may be given as fraction(0~1) or percent(0~100).

    Heuristics
    - 0.0 ~ 1.0   : treat as fraction
    - 1.0 ~ 100.0 : treat as percent -> /100
    - 100 ~ 10000 : treat as percent*100 -> /10000 (rare, but seen in some exports)
    """
    if value is None:
        return None
    try:
        v = float(value)
    except Exception:
        return None
    if v <= 1.0:
        return v
    if v <= 100.0:
        return v / 100.0
    if v <= 10000.0:
        return v / 10000.0
    return v

def _extract_coverage_rate(summary: Dict[str, Any], report_dir: Path) -> Optional[float]:
    cov = summary.get("coverage")
    if isinstance(cov, dict):
        lr = cov.get("line_rate")
        if isinstance(lr, (int, float)):
            return normalize_rate_0_1(lr)

    try:
        xml_path = report_dir / "coverage" / "coverage.xml"
        if xml_path.exists():
            root = ET.parse(xml_path).getroot()
            rate_str = root.get("line-rate", "0")
            rate = float(rate_str)
            return normalize_rate_0_1(rate)
    except Exception:
        pass

    return None


# -----------------------------
# 히스토리 관리
# -----------------------------

_history_lock = threading.Lock()


def save_history(paths: Dict[str, Path], summary: Dict[str, Any] | None, avg_complexity: Optional[float]) -> None:
    if not summary:
        return

    with _history_lock:
        _save_history_inner(paths, summary, avg_complexity)


def _save_history_inner(paths: Dict[str, Path], summary: Dict[str, Any] | None, avg_complexity: Optional[float]) -> None:
    hist = load_json(paths["HISTORY"], []) or []
    if not isinstance(hist, list):
        hist = []

    static_res = summary.get("static", {}) or {}
    cpp_res = static_res.get("cppcheck", {}) or {}
    tidy_res = static_res.get("clang_tidy", {}) or {}
    semgrep_res = static_res.get("semgrep", {}) or {}

    def _count_issues(block: Dict[str, Any]) -> int:
        data = block.get("data")
        if isinstance(data, dict) and isinstance(data.get("issues"), list):
            return len(data["issues"])
        if isinstance(block.get("issues"), list):
            return len(block["issues"])
        if isinstance(block.get("issue_counts"), dict):
            return int(block["issue_counts"].get("total", 0))
        return 0

    cpp_issues = _count_issues(cpp_res)
    tidy_issues = _count_issues(tidy_res)
    semgrep_issues = _count_issues(semgrep_res)
    total_issues = cpp_issues + tidy_issues + semgrep_issues

    build_res = summary.get("build", {}) or {}
    fuzz_res = summary.get("fuzzing", {}) or {}
    qemu_res = summary.get("qemu", {}) or {}
    tests_res = summary.get("tests", {}) or {}
    domain_res = summary.get("domain_tests", {}) or {}

    tests_results = tests_res.get("results")
    if not isinstance(tests_results, list):
        tests_results = []
    tests_total = len(tests_results)
    tests_ok_count = sum(1 for r in tests_results if isinstance(r, dict) and r.get("ok"))
    tests_fail_count = tests_total - tests_ok_count
    tests_compile_failed = sum(
        1
        for r in tests_results
        if isinstance(r, dict)
        and (
            r.get("reason") == "compile_failed"
            or (isinstance(r.get("compile"), dict) and r.get("compile", {}).get("ok") is False)
        )
    )
    tests_cmake = tests_res.get("cmake", {}) or {}
    tests_execution = tests_res.get("execution", {}) or {}

    report_health = summary.get("report_health", {}) or {}
    missing_reports = report_health.get("missing")
    if not isinstance(missing_reports, list):
        missing_reports = []

    coverage_rate = _extract_coverage_rate(summary, paths["REPORT"])
    cov_block = summary.get("coverage", {}) or {}
    coverage_below = bool(cov_block.get("below_threshold"))
    coverage_threshold = normalize_rate_0_1(cov_block.get("threshold"))
    coverage_missing = (
        "coverage_xml" in missing_reports or "coverage_html" in missing_reports
    )

    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "total_issues": total_issues,
        "cpp_issues": cpp_issues,
        "tidy_issues": tidy_issues,
        "build_ok": build_res.get("ok"),
        "build_reason": build_res.get("reason"),
        "fuzz_enabled": fuzz_res.get("enabled"),
        "qemu_enabled": qemu_res.get("enabled"),
        "tests_enabled": tests_res.get("enabled"),
        "tests_mode": tests_res.get("mode") or tests_res.get("generation_mode"),
        "tests_generated": tests_ok_count,
        "tests_failed": tests_fail_count,
        "tests_total": tests_total,
        "tests_compile_failed": tests_compile_failed,
        "tests_exec_ok": tests_execution.get("ok"),
        "tests_exec_count": tests_execution.get("count"),
        "tests_exec_passed": tests_execution.get("passed"),
        "tests_exec_failed": tests_execution.get("failed"),
        "tests_exec_note": tests_execution.get("note"),
        "tests_cmake_generated": tests_cmake.get("generated"),
        "domain_enabled": domain_res.get("enabled"),
        "coverage": coverage_rate,
        "coverage_below_threshold": coverage_below,
        "coverage_threshold": coverage_threshold,
        "coverage_ok": cov_block.get("ok"),
        "coverage_missing": coverage_missing,
        "coverage_reason": cov_block.get("reason") or cov_block.get("parse_error"),
        "complexity_avg": avg_complexity,
        "exit_code": summary.get("exit_code"),
        "failure_stage": summary.get("failure_stage"),
        "change_mode": summary.get("change_mode", "full"),
    }

    hist.append(record)
    hist = hist[-50:]
    save_json(paths["HISTORY"], hist)


# -----------------------------
# Lizard 대상 수집 보조
# -----------------------------

def _parse_list_str(val: Any) -> List[str]:
    if val is None:
        return []
    if isinstance(val, (list, tuple, set)):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        # 콤마/개행/세미콜론 구분 허용
        parts = re.split(r"[,\n;]+", val)
        return [p.strip() for p in parts if p.strip()]
    return []


def _merge_excludes(user_excludes: Any) -> List[str]:
    default_ex = getattr(
        config,
        "DEFAULT_LIZARD_EXCLUDE_DIRS",
        ["pico-sdk", ".git", "build", "reports", "__pycache__", "venv", ".venv", "node_modules", "dist"],
    )
    base = _parse_list_str(default_ex)
    user = _parse_list_str(user_excludes)
    merged = []
    seen = set()
    for x in base + user:
        if x not in seen:
            merged.append(x)
            seen.add(x)
    return merged


def _is_excluded_path(p: Path, excludes: List[str]) -> bool:
    parts = set(p.parts)
    return any(e in parts for e in excludes)


def _collect_sources_by_glob(root_p: Path, patterns: List[str], excludes: List[str]) -> List[str]:
    files: List[str] = []
    exts = (".c", ".cpp", ".cc", ".h", ".hpp", ".py")
    for pat in patterns:
        try:
            for p in root_p.glob(pat):
                if not p.is_file():
                    continue
                if p.suffix.lower() not in exts:
                    continue
                if _is_excluded_path(p, excludes):
                    continue
                files.append(str(p))
        except Exception:
            continue
    # 중복 제거
    uniq = {}
    for f in files:
        uniq[f] = f
    return sorted(uniq.keys())


def _collect_sources_by_walk(root_p: Path, excludes: List[str]) -> List[str]:
    files: List[str] = []
    exts = (".c", ".cpp", ".cc", ".h", ".hpp", ".py")
    for r, d, f in os.walk(root_p):
        d[:] = [dn for dn in d if dn not in excludes]
        for file in f:
            if file.endswith(exts):
                p = Path(r) / file
                if _is_excluded_path(p, excludes):
                    continue
                files.append(str(p))
    return files


def _detect_local_build_env(project_root: Path) -> Dict[str, Any]:
    cmake_path = shutil.which("cmake") or ""
    build_tool = shutil.which("ninja") or shutil.which("make") or ""
    cmake_lists = (project_root / "CMakeLists.txt")
    cmake_lists_ok = cmake_lists.exists()
    ok = bool(cmake_path and build_tool and cmake_lists_ok)
    missing: List[str] = []
    if not cmake_lists_ok:
        missing.append("CMakeLists.txt")
    if not cmake_path:
        missing.append("cmake")
    if not build_tool:
        missing.append("ninja/make")
    return {
        "ok": ok,
        "missing": missing,
        "cmake": cmake_path,
        "build_tool": build_tool,
        "cmake_lists": str(cmake_lists),
    }


# -----------------------------
# 파이프라인 실행 (UI → Workflow)
# -----------------------------

def run_pipeline(cfg: Dict[str, Any], status_box, progress_bar, log_callback: Optional[Callable] = None) -> int:
    """
    UI/백엔드에서 호출하는 파이프라인 엔트리
    - cfg: UI 설정
    - status_box, progress_bar: 진행/상태 출력 핸들
    - log_callback: 로그 출력 콜백
    """
    resolved = resolve_source_root(cfg)
    resolved_root = str(resolved.get("root") or cfg.get("project_root") or ".")
    cfg["project_root"] = resolved_root
    cfg["resolved_source"] = resolved

    sys_log_path: Optional[Path] = None

    def _log_cb(msg: str) -> None:
        _logger.info("%s", msg)
        try:
            if sys_log_path:
                with sys_log_path.open("a", encoding="utf-8") as f:
                    f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except Exception:
            pass
        if log_callback:
            log_callback(msg)
        try:
            if status_box:
                status_box.write(msg)
        except Exception:
            pass

    cmake_root = Path(resolved_root) / "CMakeLists.txt"
    if not cmake_root.exists():
        detected = _find_cmake_root(Path(resolved_root))
        if detected and (detected / "CMakeLists.txt").exists():
            cfg["project_root"] = str(detected)
            resolved["root"] = str(detected)
            resolved["reason"] = "cmake_detect"
            cfg["resolved_source"] = resolved
            _log_cb(f"📦 CMakeLists.txt 자동 감지 → root={detected}")
        else:
            _log_cb("⚠️ CMakeLists.txt를 찾지 못했습니다. 프로젝트 루트 확인 필요")

    build_strategy = str(cfg.get("build_strategy") or getattr(config, "BUILD_STRATEGY_DEFAULT", "auto")).strip().lower()
    build_fallback = str(cfg.get("build_fallback") or getattr(config, "BUILD_FALLBACK_DEFAULT", "static")).strip().lower()
    if build_strategy not in getattr(config, "BUILD_STRATEGY_OPTIONS", ["auto", "manual"]):
        build_strategy = getattr(config, "BUILD_STRATEGY_DEFAULT", "auto")
    if build_fallback not in getattr(config, "BUILD_FALLBACK_OPTIONS", ["jenkins", "static"]):
        build_fallback = getattr(config, "BUILD_FALLBACK_DEFAULT", "static")

    build_decision: Optional[str] = None
    if build_strategy == "auto":
        env_info = _detect_local_build_env(Path(resolved_root))
        cfg["local_build_env"] = env_info
        if env_info.get("ok"):
            cfg["do_build"] = True
            build_decision = "local"
        else:
            cfg["do_build"] = False
            if build_fallback == "jenkins":
                priority = _parse_list_str(cfg.get("source_priority")) or ["local"]
                if "artifact" not in priority:
                    priority = ["artifact"] + [p for p in priority if p != "artifact"]
                    cfg["source_priority"] = priority
                resolved2 = resolve_source_root(cfg)
                resolved2_root = str(resolved2.get("root") or cfg.get("project_root") or ".")
                if resolved2_root and resolved2_root != resolved_root:
                    resolved = resolved2
                    resolved_root = resolved2_root
                    cfg["project_root"] = resolved_root
                    cfg["resolved_source"] = resolved
                build_decision = "jenkins" if resolved.get("source") == "artifact" else "static"
            else:
                build_decision = "static"

    cfg["build_strategy_effective"] = build_strategy
    cfg["build_fallback_effective"] = build_fallback
    if build_decision:
        cfg["build_decision"] = build_decision

    paths = get_paths(cfg["project_root"], cfg["report_dir"])
    report_dir = paths["REPORT"]

    # 0. 기존 리포트 백업
    backup_dir = report_dir / "backup_last"
    try:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        if report_dir.exists():
            tmp = report_dir.parent / (report_dir.name + "_prev")
            if tmp.exists():
                shutil.rmtree(tmp)
            
            # Windows 경로 문제가 있는 파일/디렉토리 제외
            def ignore_problematic_paths(src, names):
                ignored = []
                for name in names:
                    src_path = Path(src) / name
                    # CMake가 생성한 문제가 있는 경로 패턴 제외
                    # C_\\Program_Files\\ 같은 패턴이나 너무 긴 경로
                    if 'C_' in name or 'Program_Files' in name or len(str(src_path)) > 260:
                        ignored.append(name)
                    # build_host/CMakeFiles 내부의 복잡한 경로 제외
                    if 'CMakeFiles' in str(src_path) and ('C_' in str(src_path) or len(str(src_path)) > 200):
                        ignored.append(name)
                return ignored
            
            shutil.copytree(report_dir, tmp, ignore=ignore_problematic_paths, dirs_exist_ok=True)
            tmp.rename(backup_dir)
    except Exception as e:
        # 백업 실패는 경고만 출력 (워크플로우 실행에는 영향 없음)
        _logger.warning("report backup failed: %s (non-fatal, workflow continues)", e)

    # 시스템 로그 파일 초기화
    sys_log_path = paths["SYSTEM_LOG"]
    sys_log_path.parent.mkdir(parents=True, exist_ok=True)
    with sys_log_path.open("w", encoding="utf-8") as f:
        f.write(f"=== Analysis Started at {datetime.now()} ===\n")

    # 1. 진행률/로그 콜백 정의
    verbose_progress = bool(cfg.get("verbose_progress", True))
    last_progress_msg = ""
    last_progress_step = -1
    last_progress_ts = 0.0

    def _progress_cb(step: int, total: int, message: str) -> None:
        nonlocal last_progress_msg, last_progress_step, last_progress_ts
        try:
            ratio = 0.0
            if total > 0:
                ratio = min(1.0, max(0.0, (step + 1) / total))
            if progress_bar is not None:
                progress_bar.progress(ratio, text=message)
        except Exception:
            pass
        if not verbose_progress:
            return
        # Avoid spamming identical progress lines.
        now = time.time()
        if message and (message != last_progress_msg or step != last_progress_step):
            if (now - last_progress_ts) >= 0.25:
                _log_cb(f"[progress] {message}")
                last_progress_msg = message
                last_progress_step = step
                last_progress_ts = now

    if resolved_root:
        _log_cb(
            f"📌 소스 선택: {resolved.get('source')} ({resolved.get('reason')}), root={resolved_root}"
        )
    if str(cfg.get("build_strategy_effective") or "").lower() == "auto":
        decision = str(cfg.get("build_decision") or "")
        if decision == "local":
            _log_cb("🛠️ 로컬 빌드 환경 감지됨 → 로컬 빌드/테스트 실행")
        elif decision == "jenkins":
            _log_cb("🧱 로컬 빌드 환경 미탐지 → Jenkins 아티팩트 우선")
        elif decision == "static":
            _log_cb("🧱 로컬 빌드 환경 미탐지 → 빌드 없이 진행")
        env_info = cfg.get("local_build_env") or {}
        missing = env_info.get("missing") if isinstance(env_info, dict) else None
        if isinstance(missing, list) and missing:
            _log_cb(f"⚠️ 로컬 빌드 미탐지 사유: {', '.join(missing)}")

    # 2. 파이프라인 인자 정리
    include_paths_raw = cfg.get("include_paths", [])
    if isinstance(include_paths_raw, str):
        include_paths: List[str] = [p.strip() for p in include_paths_raw.split(",") if p.strip()]
    else:
        include_paths = list(include_paths_raw or [])

    # Prefer stubs for Pico headers during host syntax checks.
    stubs_root = str(cfg.get("stubs_root") or "tests/stubs").strip() or "tests/stubs"
    try:
        stubs_dir = (Path(cfg.get("project_root") or ".") / stubs_root).resolve()
        if stubs_dir.exists():
            include_paths = [str(stubs_dir)] + [p for p in include_paths if str(p) != str(stubs_dir)]
    except Exception:
        pass

    macros_raw = cfg.get("target_macros", "")
    if isinstance(macros_raw, str):
        defines = [m.strip() for m in macros_raw.replace(",", " ").split() if m.strip()]
    else:
        defines = list(macros_raw or [])

    cpp_lv = cfg.get("cppcheck_levels") or getattr(config, "DEFAULT_CPPCHECK_ENABLE", [])

    domain_targets_raw = cfg.get("domain_targets") or ""
    if isinstance(domain_targets_raw, str):
        domain_targets = [t.strip() for t in domain_targets_raw.split(",") if t.strip()] or None
    else:
        domain_targets = list(domain_targets_raw) or None

    patch_mode = cfg.get("agent_patch_mode") or cfg.get("patch_mode")
    if patch_mode is None:
        patch_mode = getattr(config, "AGENT_PATCH_MODE_DEFAULT", "auto")

    # 3. 실제 파이프라인 실행
    _log_cb("🚀 파이프라인 실행 시작...")
    t0 = time.time()
    exit_code = 0

    prev_model_override = os.environ.get("LLM_MODEL_OVERRIDE")
    prev_toolchain = os.environ.get("CMAKE_TOOLCHAIN_FILE")
    prev_generator = os.environ.get("CMAKE_GENERATOR")
    new_override = str(cfg.get("llm_model") or "").strip()
    if new_override:
        os.environ["LLM_MODEL_OVERRIDE"] = new_override
    else:
        os.environ.pop("LLM_MODEL_OVERRIDE", None)
    toolchain_file = str(cfg.get("cmake_toolchain_file") or "").strip()
    if toolchain_file:
        tf_path = Path(toolchain_file).expanduser()
        if tf_path.exists() and tf_path.is_file():
            os.environ["CMAKE_TOOLCHAIN_FILE"] = str(tf_path.resolve())
        else:
            os.environ.pop("CMAKE_TOOLCHAIN_FILE", None)
            _log_cb(f"⚠️ CMake Toolchain 파일이 유효하지 않아 무시됨: {toolchain_file}")
    else:
        os.environ.pop("CMAKE_TOOLCHAIN_FILE", None)
    cmake_gen = str(cfg.get("cmake_generator") or "").strip()
    if cmake_gen:
        os.environ["CMAKE_GENERATOR"] = cmake_gen
    else:
        os.environ.pop("CMAKE_GENERATOR", None)
    try:
        # 커버리지 활성화 시 빌드도 자동으로 활성화 (커버리지 수집을 위해 빌드 필요)
        do_build_setting = cfg.get("do_build", False)
        do_coverage_setting = True  # 로컬 워크플로우에서는 항상 True
        if do_coverage_setting and not do_build_setting:
            do_build_setting = True
        
        exit_code = workflow.run_cli(
            project_root=cfg["project_root"],
            report_dir=cfg["report_dir"],
            targets_glob=cfg.get("targets_glob", getattr(config, "DEFAULT_TARGETS_GLOB", "libs/*.c")),
            include_paths=include_paths,
            do_cmake_analysis=True,
            do_syntax_check=True,
            do_build_and_test=do_build_setting,
            do_coverage=do_coverage_setting,
            do_asan=cfg.get("do_asan", False),
            do_fuzz=cfg.get("do_fuzz", False),
            do_qemu=cfg.get("do_qemu", False),
            do_docs=cfg.get("do_docs", False),
            static_only=not cfg.get("enable_agent", False),
            enable_agent=cfg.get("enable_agent", False),
            max_iterations=int(cfg.get("max_iterations", 1)),
            oai_config_path=cfg.get("oai_config_path") or getattr(config, "DEFAULT_OAI_CONFIG_PATH", "oai_config.json"),
            enable_test_gen=cfg.get("enable_test_gen", False),
            test_gen_stub_only=cfg.get("test_gen_stub_only", False),
            test_gen_excludes=_parse_list_str(cfg.get("test_gen_excludes")),
            test_gen_timeout_sec=cfg.get("test_gen_timeout_sec"),
            auto_run_tests=cfg.get("auto_run_tests", getattr(config, "AUTO_RUN_TESTS", False)),
            agent_roles=cfg.get("agent_roles") or [],
            agent_max_steps=int(cfg.get("agent_max_steps", getattr(config, "AGENT_MAX_STEPS_DEFAULT", 3))),
            agent_run_mode=cfg.get("agent_run_mode"),
            agent_review=cfg.get("agent_review", None),
            agent_rag=cfg.get("agent_rag", None),
            agent_rag_top_k=int(cfg.get("agent_rag_top_k", getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3))),
            target_arch=cfg.get("target_arch", getattr(config, "DEFAULT_TARGET_ARCH", "cortex-m0plus")),
            defines=defines,
            extra_defines=[],
            cppcheck_enable=cpp_lv,
            do_clang_tidy=cfg.get("do_clang_tidy", False),
            clang_tidy_checks=cfg.get("clang_checks") or [],
            quality_preset=cfg.get("quality_preset"),
            enable_semgrep=cfg.get("enable_semgrep", False),
            semgrep_config=cfg.get("semgrep_config"),
            enable_domain_tests=cfg.get("enable_domain_tests", False),
            domain_tests_auto=cfg.get("domain_tests_auto", getattr(config, "DOMAIN_TESTS_AUTO", True)),
            domain_targets=domain_targets,
            full_analysis=not bool(cfg.get("git_incremental", False)),
            progress_callback=_progress_cb,
            log_callback=_log_cb,
            patch_mode=patch_mode,
            auto_fix_scope=cfg.get("auto_fix_scope"),
            auto_fix_on_fail=cfg.get("auto_fix_on_fail", False),
            auto_fix_on_fail_stages=cfg.get("auto_fix_on_fail_stages"),
            git_base_ref=cfg.get("git_base_ref"),
            scm_mode=cfg.get("scm_mode"),
            svn_base_ref=cfg.get("svn_base_ref"),
            rag_ingest_enable=cfg.get("rag_ingest_enable", True),
            vc_reports_paths=cfg.get("vc_reports_paths", []),
            uds_spec_paths=cfg.get("uds_spec_paths", []),
            req_docs_paths=cfg.get("req_docs_paths", []),
            codebase_paths=cfg.get("codebase_paths", []),
            build_dir_override=cfg.get("build_dir"),
            suppressions_path=str(paths["SUPPRESSIONS"]) if paths["SUPPRESSIONS"].exists() else None,
        )
    except Exception as e:
        _log_cb(f"❌ 치명적 오류 발생: {e}")
        return 1
    finally:
        if prev_model_override is None:
            os.environ.pop("LLM_MODEL_OVERRIDE", None)
        else:
            os.environ["LLM_MODEL_OVERRIDE"] = prev_model_override
        if prev_toolchain is None:
            os.environ.pop("CMAKE_TOOLCHAIN_FILE", None)
        else:
            os.environ["CMAKE_TOOLCHAIN_FILE"] = prev_toolchain
        if prev_generator is None:
            os.environ.pop("CMAKE_GENERATOR", None)
        else:
            os.environ["CMAKE_GENERATOR"] = prev_generator

    elapsed = time.time() - t0
    _log_cb(f"⏱️ 파이프라인 종료 (소요 시간: {elapsed:0.1f}s, exit_code={exit_code})")

    # 4. 복잡도 분석 (Lizard)
    _log_cb("📊 코드 복잡도 분석 (Lizard) 시작...")
    avg_ccn: Optional[float] = None

    audit_lines = [f"=== Lizard Complexity Analysis Started at {datetime.now()} ==="]
    audit_lines.append(f"Root: {cfg['project_root']}")

    try:
        root_p = Path(cfg["project_root"])
        excludes = _merge_excludes(cfg.get("exclude_dirs", []))
        audit_lines.append(f"Excludes: {', '.join(excludes) if excludes else '(none)'}")

        # targets_glob 기반 수집 우선
        patterns = _parse_list_str(cfg.get("targets_glob", ""))
        source_files: List[str] = []

        if patterns:
            source_files = _collect_sources_by_glob(root_p, patterns, excludes)
            audit_lines.append(f"Collection: glob patterns = {patterns}")
        else:
            source_files = _collect_sources_by_walk(root_p, excludes)
            audit_lines.append("Collection: os.walk fallback")

        audit_lines.append(f"Found {len(source_files)} source files.")

        # 너무 많은 파일이면 threads 줄임(체감 멈춤 완화)
        threads = 1 if len(source_files) > 1200 else 4
        audit_lines.append(f"Threads: {threads}")

        if source_files:
            lz_result = lizard.analyze_files(source_files, threads=threads)
            complexity_data: List[Dict[str, Any]] = []

            for f in lz_result:
                try:
                    rel_name = str(Path(f.filename).relative_to(root_p))
                except Exception:
                    rel_name = str(f.filename)
                audit_lines.append(f"[OK] {rel_name}")

                for func in f.function_list:
                    complexity_data.append(
                        {
                            "file": rel_name,
                            "function": func.name,
                            "ccn": func.cyclomatic_complexity,
                            "nloc": func.nloc,
                            "params": func.parameter_count,
                        }
                    )

            if complexity_data:
                df = pd.DataFrame(complexity_data)
                df.to_csv(paths["COMPLEXITY"], index=False)
                avg_ccn = float(df["ccn"].mean())
                _log_cb(f"✅ 복잡도 분석 완료 (평균 CCN: {avg_ccn:.1f})")
            else:
                _log_cb("⚠️ 복잡도 데이터 없음 (함수 미탐지)")
        else:
            _log_cb("⚠️ 분석할 소스 파일 없음")

    except Exception as e:
        err_msg = f"Lizard Analysis Failed: {e}"
        _logger.warning("%s", err_msg)
        audit_lines.append(f"[ERROR] {err_msg}")

    audit_lines.append(f"\n=== Finished at {datetime.now()} ===")

    try:
        paths["LIZARD_LOG"].write_text("\n".join(audit_lines), encoding="utf-8")
    except Exception:
        pass

    # 5. 히스토리 저장
    try:
        summary_data = load_json(paths["SUMMARY"])
        if isinstance(summary_data, dict):
            save_history(paths, summary_data, avg_ccn)
    except Exception as e:
        _logger.warning("History save failed: %s", e)

    _log_cb("✅ 모든 작업 완료!")
    return exit_code


def start_pipeline_async(cfg: Dict[str, Any], paths: Dict[str, Path]) -> Dict[str, Any]:
    """Launch pipeline in a separate process for non-blocking UI."""
    report_dir = paths["REPORT"]
    cfg_path = report_dir / "run_config.json"
    status_path = report_dir / "run_status.json"
    log_path = paths["SYSTEM_LOG"]

    try:
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    cmd = [
        sys.executable,
        "-m",
        "workflow.runner",
        "--config",
        str(cfg_path),
        "--status",
        str(status_path),
        "--log",
        str(log_path),
    ]

    try:
        proc = subprocess.Popen(cmd, cwd=str(Path.cwd()))
        return {
            "pid": proc.pid,
            "status_path": str(status_path),
            "log_path": str(log_path),
            "config_path": str(cfg_path),
        }
    except Exception as e:
        return {"error": str(e), "status_path": str(status_path), "log_path": str(log_path)}


def read_run_status(status_path: Path) -> Dict[str, Any]:
    try:
        return load_json(status_path, default={})
    except Exception:
        return {}


def tail_file(path: Path, max_lines: int = 80, max_bytes: int = 256 * 1024) -> str:
    try:
        if not path.exists() or not path.is_file():
            return ""
        data = path.read_bytes()
        if len(data) > max_bytes:
            data = data[-max_bytes:]
        text = data.decode("utf-8", errors="ignore")
        lines = text.splitlines()
        return "\n".join(lines[-max_lines:])
    except Exception:
        return ""


def append_log_line(path: Path, msg: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def terminate_process(pid: int) -> bool:
    """Best-effort termination for background runner."""
    try:
        if pid <= 0:
            return False
        if platform.system().lower().startswith("win"):
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True)
        else:
            os.kill(pid, 15)
        return True
    except Exception:
        return False


def build_sample_summary(project_root: Path) -> Dict[str, Any]:
    """리포트가 없을 때 대시보드에 뿌려줄 샘플 summary 구조"""
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "generated_at": now,
        "project_root": str(project_root),
        "is_sample": True,
        "meta": {
            "note": "샘플 데이터 (아직 실제 파이프라인 실행 전)",
            "created_at": now,
        },
        "pipeline_plan": [
            {
                "step": 1,
                "name": "Syntax Check",
                "enabled": True,
                "status": "NOT_RUN",
                "option_source": "config + ENV",
                "output": "reports/build/syntax.log",
            },
            {
                "step": 2,
                "name": "Host Build",
                "enabled": True,
                "status": "NOT_RUN",
                "option_source": "CMake HOST_BUILD",
                "output": "reports/build/",
            },
            {
                "step": 3,
                "name": "Unit Tests",
                "enabled": True,
                "status": "NOT_RUN",
                "option_source": "ENABLE_UNIT_TESTS",
                "output": "reports/tests/",
            },
            {
                "step": 4,
                "name": "Coverage",
                "enabled": True,
                "status": "NOT_RUN",
                "option_source": "CI_ENABLE_COVERAGE",
                "output": "reports/coverage/",
            },
            {
                "step": 5,
                "name": "Fuzzing",
                "enabled": False,
                "status": "DISABLED",
                "option_source": "CI_ENABLE_FUZZ",
                "output": "reports/fuzz/",
            },
            {
                "step": 6,
                "name": "Emulator / QEMU",
                "enabled": False,
                "status": "DISABLED",
                "option_source": "CI_ENABLE_QEMU",
                "output": "reports/qemu/",
            },
            {
                "step": 7,
                "name": "Static Analysis",
                "enabled": True,
                "status": "NOT_RUN",
                "option_source": "CI_ENABLE_STATIC",
                "output": "reports/static/",
            },
            {
                "step": 8,
                "name": "Domain Test Panel",
                "enabled": False,
                "status": "DISABLED",
                "option_source": "CI_ENABLE_DOMAIN_TESTS",
                "output": "reports/domain_tests/",
            },
            {
                "step": 9,
                "name": "LLM Self-Healing",
                "enabled": True,
                "status": "NOT_RUN",
                "option_source": "agent_mode / cfg.enable_llm_fix",
                "output": "reports/agent_patches/",
            },
            {
                "step": 10,
                "name": "Docs / Reports",
                "enabled": True,
                "status": "NOT_RUN",
                "option_source": "cfg.enable_docs",
                "output": "reports/docs/",
            },
        ],
        "build": {
            "status": "NOT_RUN",
            "elapsed_sec": 0.0,
        },
        "tests": {
            "status": "NOT_RUN",
            "total": 0,
            "failed": 0,
            "passed": 0,
        },
        "coverage": {
            "status": "NOT_RUN",
            "line_rate": 0.0,
            "branch_rate": 0.0,
        },
        "static": {
            "status": "NOT_RUN",
            "cppcheck": {"warnings": 0, "errors": 0},
            "clang_tidy": {"warnings": 0, "errors": 0},
            "semgrep": {"warnings": 0, "errors": 0},
        },
        "qac": {
            "status": "NOT_RUN",
            "total_violations": 0,
            "total_deviations": 0,
            "rules_with_violations": 0,
        },
        "agent": {
            "mode": "review",
            "applied_changes": [],
        },
        "history": [],
    }
    
def load_summary_with_fallback(paths: Dict[str, Path]) -> Tuple[Dict[str, Any], bool]:
    """
    - 분석 summary 파일이 있으면: 그걸 로드, is_sample=False
    - 없거나 내용이 비정상/빈 dict면: 샘플 summary 생성, is_sample=True
    """
    summary_path = paths.get("SUMMARY")
    root = paths.get("ROOT", Path("."))

    # 기본값은 빈 dict
    summary = {}
    is_sample = False

    try:
        if summary_path and summary_path.exists():
            with summary_path.open("r", encoding="utf-8") as f:
                summary = json.load(f)
    except Exception as e:
        _logger.warning("Failed to load real summary: %s", e)
        summary = {}

    # 유효한 실제 summary가 있으면 그대로 사용
    if isinstance(summary, dict) and summary.get("generated_at"):
        return summary, False

    # 없으면 샘플로 대체
    sample = build_sample_summary(root)
    return sample, True


# ============================================================
# Rule catalog / Deviation helpers (Jenkins Viewer 품질 개선)
# - PRQA/Helix QAC *.rcf 에서 MISRA Rule 설명을 파싱해
#   Jenkins 리포트/에디터에서 "Rule 5-3" -> 규칙 설명 표시
# - Deviation(데비에이션) 소명 기록을 reports/deviations.json에 저장
# ============================================================

_RULE_CATALOG_CACHE: Dict[str, Dict[str, str]] = {}
_DEVIATIONS_CACHE: Dict[str, List[Dict[str, Any]]] = {}


def _normalize_rule_label(rule: str) -> str:
    """다양한 rule 표기를 'Rule 5-3' 형태로 정규화"""
    if not rule:
        return ""
    s = str(rule).strip()
    if not s:
        return ""

    # 예: 'Rule-5.3', 'Rule 5-3', '5.3', '5-3', 'Rule-13.1'
    s = re.sub(r"\s+", " ", s)
    s = s.replace("MISRA ", "").replace("MISRA-", "").strip()

    prefix = "Rule"
    if s.lower().startswith("dir") or s.lower().startswith("directive") or s.lower().startswith("d-") or s.lower().startswith("dir-"):
        prefix = "Dir"

    # rcf id: Rule-5.3 / Dir-1.1
    m = re.search(r"(Rule|Dir)[\s\-_:]*([0-9]+)[\.-]([0-9]+)", s, flags=re.IGNORECASE)
    if m:
        a = m.group(2)
        b = m.group(3)
        return f"{prefix} {a}-{b}"

    # already: 5.3 / 5-3
    m2 = re.search(r"(^|\b)([0-9]+)[\.-]([0-9]+)(\b|$)", s)
    if m2:
        a = m2.group(2)
        b = m2.group(3)
        return f"{prefix} {a}-{b}"

    # fallback
    return s


def _parse_rcf_rule_catalog(rcf_path: Path) -> Dict[str, str]:
    """PRQA/Helix QAC *.rcf(XML)에서 rule id -> 설명(text) 추출"""
    out: Dict[str, str] = {}
    try:
        tree = ET.parse(str(rcf_path))
        root = tree.getroot()
    except Exception:
        return out

    for node in root.iter():
        try:
            if node.tag.lower().endswith("rule") and "id" in node.attrib:
                rid = str(node.attrib.get("id") or "").strip()
                if not rid:
                    continue
                # Rule-5.3 / Dir-1.1 같은 형식 위주로만
                if not re.search(r"^(Rule|Dir)[\-_]?[0-9]+\.[0-9]+$", rid, flags=re.IGNORECASE):
                    continue
                label = _normalize_rule_label(rid)
                # text 노드가 여러 형태로 존재 가능
                desc = ""
                t = node.find("text")
                if t is not None and (t.text or "").strip():
                    desc = (t.text or "").strip()
                else:
                    # 혹시 하위에 text가 있는 경우
                    t2 = node.find(".//text")
                    if t2 is not None:
                        desc = (t2.text or "").strip()
                if desc:
                    # 중복 시 더 긴 설명 우선
                    prev = out.get(label, "")
                    if (not prev) or (len(desc) > len(prev)):
                        out[label] = desc
        except Exception:
            continue
    return out


def _discover_rule_rcf_files(project_root: Optional[Path] = None) -> List[Path]:
    """repo rules/ 아래 *.rcf 자동 탐색 + ENV override 지원"""
    roots: List[Path] = []
    if project_root:
        roots.append(project_root)
    else:
        roots.append(Path.cwd())

    # env override: DEVOPS_RULE_RCF_FILES=/abs/a.rcf,/abs/b.rcf
    env = os.environ.get("DEVOPS_RULE_RCF_FILES", "").strip()
    files: List[Path] = []
    if env:
        for p in [x.strip() for x in env.split(",") if x.strip()]:
            pp = Path(p)
            if pp.exists() and pp.suffix.lower() == ".rcf":
                files.append(pp)

    globs = getattr(config, "RULE_CATALOG_GLOBS", ["rules/*.rcf", "rules/**/*.rcf"])
    for r in roots:
        for g in globs:
            try:
                for p in r.glob(g):
                    if p.exists() and p.is_file() and p.suffix.lower() == ".rcf":
                        files.append(p.resolve())
            except Exception:
                continue

    # 중복 제거
    uniq: List[Path] = []
    seen = set()
    for p in files:
        sp = str(p)
        if sp not in seen:
            uniq.append(p)
            seen.add(sp)
    return uniq



def _uniq_paths(items: List[Path]) -> List[Path]:
    """경로 리스트 중복 제거 (순서 유지)"""
    out: List[Path] = []
    seen: set[str] = set()
    for p in items:
        try:
            key = str(p.resolve())
        except Exception:
            key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out

def load_rule_catalog(
    project_root: Optional[Path] = None,
    force: bool = False,
    extra_roots: Optional[List[Path]] = None,
) -> Dict[str, str]:
    """rule catalog 로드 (JSON 캐시 우선, 없으면 *.rcf 파싱)
    - 기본 루트: project_root 또는 cwd
    - 추가 루트: extra_roots + ENV(DEVOPS_RULE_ROOTS)
    - 각 루트의 상위 디렉터리(최대 2레벨)도 함께 탐색
    """
    base_root = (project_root or Path.cwd()).resolve()

    roots: List[Path] = [base_root]
    # extra roots
    if extra_roots:
        for r in extra_roots:
            try:
                if r:
                    roots.append(Path(r).resolve())
            except Exception:
                pass
    # env roots
    env_roots = (os.environ.get("DEVOPS_RULE_ROOTS") or "").strip()
    if env_roots:
        for s in env_roots.split(","):
            s = s.strip()
            if not s:
                continue
            try:
                roots.append(Path(s).expanduser().resolve())
            except Exception:
                pass

    # add parents (up to 2)
    roots2: List[Path] = []
    for r in roots:
        roots2.append(r)
        try:
            p1 = r.parent
            if p1 and p1 != r:
                roots2.append(p1)
                p2 = p1.parent
                if p2 and p2 != p1:
                    roots2.append(p2)
        except Exception:
            pass
    roots = _uniq_paths(roots2)

    cache_key = "|".join([str(p) for p in roots])
    if (not force) and cache_key in _RULE_CATALOG_CACHE:
        return _RULE_CATALOG_CACHE[cache_key]

    catalog: Dict[str, str] = {}
    json_rel = getattr(config, "RULE_CATALOG_JSON", "rules/rule_catalog.json")

    for root in roots:
        # 1) JSON cache
        json_path = (root / json_rel).resolve()
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8", errors="ignore") or "{}")
                if isinstance(data, dict):
                    for k, v in data.items():
                        if not k:
                            continue
                        kk = _normalize_rule_label(str(k))
                        vv = str(v or "").strip()
                        if vv and (kk not in catalog or len(vv) > len(catalog.get(kk, ""))):
                            catalog[kk] = vv
            except Exception:
                pass

        # 2) parse rcf (only if needed)
        try:
            for rcf in _discover_rule_rcf_files(root):
                part = _parse_rcf_rule_catalog(rcf)
                for k, v in part.items():
                    if k not in catalog or len(v) > len(catalog.get(k, "")):
                        catalog[k] = v
        except Exception:
            pass

    # persist to base_root cache path (best effort)
    try:
        if catalog:
            json_path = (base_root / json_rel).resolve()
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    _RULE_CATALOG_CACHE[cache_key] = catalog
    return catalog


def normalize_rule_label(rule: str) -> str:
    """Normalize rule labels to match catalog keys."""
    return _normalize_rule_label(str(rule or ""))


def rule_desc(rule: str, catalog: Optional[Dict[str, str]] = None, project_root: Optional[Path] = None) -> str:
    if not rule:
        return ""
    cat = catalog if isinstance(catalog, dict) else load_rule_catalog(project_root)
    key = _normalize_rule_label(str(rule))
    return str(cat.get(key, ""))


def deviation_path(reports_dir: Path) -> Path:
    return (Path(reports_dir).resolve() / "deviations.json")


def _read_text_smart(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except Exception:
        return ""
    sample = raw[:4096]
    encodings = ["utf-8", "cp949", "latin-1"]
    if b"\x00" in sample:
        encodings = ["utf-16", "utf-16-le", "utf-16-be"] + encodings
    for enc in encodings:
        try:
            return raw.decode(enc, errors="ignore")
        except Exception:
            continue
    return ""


def _resolve_deviation_source(reports_dir: Path, file_rel: str) -> Optional[Path]:
    if not file_rel:
        return None
    p = Path(str(file_rel))
    if p.is_absolute() and p.exists():
        return p

    rdir = Path(reports_dir).resolve()
    build_root = rdir.parent
    roots: List[Path] = []
    jscan = rdir / "jenkins_scan.json"
    try:
        js = load_json(jscan, default={})
        rels = (js or {}).get("source_roots") if isinstance(js, dict) else None
        if isinstance(rels, list):
            for rel in rels:
                try:
                    cand = (build_root / str(rel)).resolve()
                    if cand.exists() and cand.is_dir():
                        roots.append(cand)
                except Exception:
                    continue
    except Exception:
        pass
    roots.extend([
        build_root,
        build_root / "svn_wc",
        build_root / "svn_wc" / "Sources",
        build_root / "svn_wc" / "Sources" / "APP",
        build_root / "app",
        build_root / "app" / "PDSM" / "Sources",
        build_root / "app" / "PDSM" / "Sources" / "APP",
        build_root / "Sources",
        build_root / "src",
        build_root / "source",
    ])

    rel_norm = str(file_rel).replace("\\", "/").lstrip("./")
    name = Path(rel_norm).name.lower()
    for root in roots:
        try:
            if root.is_dir():
                cand = (root / rel_norm).resolve()
                if cand.exists() and cand.is_file():
                    return cand
                # fallback: name-only match
                for hit in root.rglob("*"):
                    if not hit.is_file():
                        continue
                    if hit.name.lower() == name:
                        return hit
        except Exception:
            continue
    return None


def _extract_deviation_snippet(path: Path, line_num: int, *, context: int = 6) -> str:
    text = _read_text_smart(path)
    if not text:
        return ""
    lines = text.splitlines()
    if not lines:
        return ""
    if line_num <= 0 or line_num > len(lines):
        return ""
    start = max(1, line_num - context)
    end = min(len(lines), line_num + context)
    return "\n".join(lines[start - 1:end]).strip()


def load_deviations(reports_dir: Path, force: bool = False) -> List[Dict[str, Any]]:
    rdir = Path(reports_dir).resolve()
    key = str(rdir)
    if (not force) and key in _DEVIATIONS_CACHE:
        return _DEVIATIONS_CACHE[key]
    p = deviation_path(rdir)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="ignore") or "[]")
            if isinstance(data, list):
                _DEVIATIONS_CACHE[key] = data
                return data
        except Exception:
            pass
    _DEVIATIONS_CACHE[key] = []
    return []


def _deviation_id(rule_label: str, file_rel: str, line_num: int, message: str) -> str:
    import hashlib
    base = f"{rule_label}|{file_rel}|{line_num}|{message}".encode("utf-8", errors="ignore")
    return hashlib.sha1(base).hexdigest()[:16]


def upsert_deviation(reports_dir: Path, record: Dict[str, Any]) -> str:
    rdir = Path(reports_dir).resolve()
    rdir.mkdir(parents=True, exist_ok=True)
    items = load_deviations(rdir, force=True)
    rid = str(record.get("id") or "").strip()
    if not rid:
        rid = _deviation_id(
            str(record.get("rule") or ""),
            str(record.get("file") or ""),
            int(record.get("line") or 0),
            str(record.get("message") or ""),
        )
        record["id"] = rid

    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    record.setdefault("created_at", now)
    record["updated_at"] = now

    replaced = False
    for i, it in enumerate(items):
        if str(it.get("id") or "") == rid:
            items[i] = record
            replaced = True
            break
    if not replaced:
        items.append(record)

    p = deviation_path(rdir)
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    _DEVIATIONS_CACHE[str(rdir)] = items
    return rid


def get_deviation_for_issue(
    reports_dir: Path,
    rule: str,
    file_rel: str,
    line_num: int,
    message: str,
) -> Optional[Dict[str, Any]]:
    rdir = Path(reports_dir).resolve()
    rule_label = _normalize_rule_label(rule)
    rid = _deviation_id(rule_label, file_rel, int(line_num or 0), str(message or ""))
    for it in load_deviations(rdir):
        if str(it.get("id") or "") == rid:
            return it
    return None


def delete_deviation(reports_dir: Path, deviation_id: str) -> bool:
    rdir = Path(reports_dir).resolve()
    did = str(deviation_id or "").strip()
    if not did:
        return False
    items = load_deviations(rdir, force=True)
    new_items = [it for it in items if str(it.get("id") or "") != did]
    if len(new_items) == len(items):
        return False
    p = deviation_path(rdir)
    p.write_text(json.dumps(new_items, ensure_ascii=False, indent=2), encoding="utf-8")
    _DEVIATIONS_CACHE[str(rdir)] = new_items
    return True


# -----------------------------
# 코드 규모/함수 diff 보조 함수 (Jenkins/Local 공용)
# -----------------------------

_LIZARD_CACHE: dict[str, tuple[float, Any]] = {}  # path -> (mtime, df)
_LAST_LIZARD_PATH: Optional[Path] = None
_LAST_LIZARD_ERROR: Optional[str] = None



def _is_warning_severity(sev: str) -> bool:
    s = str(sev or "").strip().lower()
    if not s:
        return False
    if "warn" in s or "warning" in s:
        return True
    if s in ("w", "wrn"):
        return True
    if any(k in s for k in ("mandatory", "required", "advisory")):
        return True
    return False


def auto_deviations_for_findings(
    findings: List[Dict[str, Any]],
    reports_dir: Path,
    *,
    rule_catalog: Optional[Dict[str, str]] = None,
    only_warnings: bool = True,
    default_author: str = "",
    status: str = "Pending",
) -> Dict[str, Any]:
    items = []
    created = 0
    skipped = 0
    skipped_non_warn = 0
    skipped_duplicate = 0
    skipped_invalid = 0
    total = 0
    batch_id = datetime.utcnow().strftime("%Y%m%dT%H%M%S")

    for it in findings or []:
        if not isinstance(it, dict):
            skipped += 1
            skipped_invalid += 1
            continue
        total += 1
        sev = str(it.get("severity") or it.get("level") or it.get("grade") or "").strip()
        if only_warnings and sev and not _is_warning_severity(sev):
            skipped += 1
            skipped_non_warn += 1
            continue

        rule = str(it.get("rule") or it.get("check") or it.get("id") or "").strip()
        tool = str(it.get("tool") or it.get("source") or "").strip()
        if not rule:
            rule = f"{tool}:UNSPECIFIED" if tool else "UNSPECIFIED"

        file_rel = str(it.get("file") or it.get("path") or it.get("filename") or "").strip()
        if not file_rel:
            file_rel = "unknown"
        line_num = int(it.get("line") or it.get("lineNumber") or it.get("line_num") or 0)
        message = str(it.get("message") or it.get("msg") or it.get("text") or "")

        if get_deviation_for_issue(reports_dir, rule, file_rel, line_num, message):
            skipped += 1
            skipped_duplicate += 1
            continue

        rule_label = _normalize_rule_label(rule)
        desc = rule_desc(rule_label, rule_catalog)
        context = f"Rule {rule_label} in {file_rel}:{line_num}. {message}".strip()
        if desc:
            context = f"{context} (Rule desc: {desc})"

        rec = {
            "rule": rule_label,
            "rule_raw": rule,
            "tool": tool,
            "severity": sev,
            "file": file_rel,
            "line": int(line_num or 0),
            "message": message,
            "type": "Other (??)",
            "status": status,
            "context": context,
            "safety_argument": "Reviewed and accepted with documented constraints.",
            "mitigation": "Monitor in future releases and add tests if needed.",
            "evidence": "",
            "reviewer": "",
            "author": str(default_author or "auto"),
            "batch_id": batch_id,
            "source": "auto_batch",
        }
        did = upsert_deviation(reports_dir, rec)
        rec["id"] = did
        created += 1
        items.append(rec)

    return {
        "created": created,
        "skipped": skipped,
        "skipped_non_warn": skipped_non_warn,
        "skipped_duplicate": skipped_duplicate,
        "skipped_invalid": skipped_invalid,
        "total": total,
        "batch_id": batch_id,
        "items": items,
    }


def export_deviations_xlsx(reports_dir: Path, out_path: Optional[Path] = None) -> Optional[Path]:
    pd = _import_pandas()
    if pd is None:
        return None
    rdir = Path(reports_dir).resolve()
    rows = load_deviations(rdir, force=True)
    if not isinstance(rows, list):
        rows = []
    for r in rows:
        try:
            file_rel = str(r.get("file") or "")
            line_num = int(r.get("line") or 0)
        except Exception:
            file_rel = ""
            line_num = 0
        resolved = _resolve_deviation_source(rdir, file_rel)
        snippet = ""
        status = "ok"
        if resolved is None:
            status = "file_not_found"
        elif line_num <= 0:
            status = "line_invalid"
        else:
            snippet = _extract_deviation_snippet(resolved, line_num, context=6)
            if not snippet:
                status = "snippet_missing"
        r["resolved_path"] = str(resolved) if resolved else ""
        r["code_snippet"] = snippet
        r["snippet_status"] = status
    df = pd.DataFrame(rows)
    out = Path(out_path) if out_path else deviation_path(rdir).with_suffix(".xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out, index=False)
    return out


def _import_pandas():
    try:
        import pandas as _pd  # type: ignore
        return _pd
    except Exception:
        return None

def _pick_column_case_insensitive(df, candidates: List[str]) -> Optional[str]:
    try:
        cols = list(df.columns)
    except Exception:
        return None
    lower = {str(c).lower(): str(c) for c in cols}
    for c in candidates:
        if c in cols:
            return c
        if str(c).lower() in lower:
            return lower[str(c).lower()]
    return None


def _set_last_lizard_path(p: Path) -> None:
    global _LAST_LIZARD_PATH
    try:
        _LAST_LIZARD_PATH = Path(str(p)).resolve()
    except Exception:
        _LAST_LIZARD_PATH = Path(str(p))


def get_last_lizard_path() -> Optional[Path]:
    return _LAST_LIZARD_PATH


def _set_last_lizard_error(msg: Optional[str]) -> None:
    global _LAST_LIZARD_ERROR
    _LAST_LIZARD_ERROR = str(msg) if msg else None


def get_last_lizard_error() -> Optional[str]:
    return _LAST_LIZARD_ERROR


def load_lizard_dataframe(report_dir: Path) -> Optional["pd.DataFrame"]:
    """
    Lizard/complexity CSV를 찾아 DataFrame으로 로드

    탐색 디렉터리
    - report_dir
    - report_dir가 build_root/reports 인 경우 build_root/report도 함께 탐색

    우선순위
    - 고정 후보 경로
    - fallback rglob(*lizard*.csv, *complexity*.csv)  (최대 30개 후보)
    """
    try:
        import pandas as pd  # type: ignore
    except Exception:
        return None

    if not report_dir:
        return None

    base = Path(str(report_dir))

    if base.exists() and base.is_file():
        df = _read_lizard_csv_cached(base)
        if df is not None:
            _set_last_lizard_path(base)
        return df

    # 탐색 디렉터리 후보 구성
    search_dirs: List[Path] = []
    try:
        if base.exists() and base.is_dir():
            search_dirs.append(base)
            for sub in ("reports", "report"):
                cand = (base / sub).resolve()
                if cand.exists() and cand.is_dir():
                    search_dirs.append(cand)
    except Exception:
        pass

    alt_dir: Optional[Path] = None
    try:
        cand = (base.parent / "report").resolve()
        if cand.exists() and cand.is_dir() and cand != base:
            alt_dir = cand
            search_dirs.append(cand)
    except Exception:
        alt_dir = None

    try:
        if base.name.lower() in ("reports", "report"):
            cand = base.parent.resolve()
            if cand.exists() and cand.is_dir():
                search_dirs.append(cand)
    except Exception:
        pass

    if not search_dirs:
        return None

    # 1) 고정 후보 경로 우선
    fixed_names = [
        "lizard.csv",
        "Lizard.csv",
        "lizard_report.csv",
        "Lizard_Report.csv",
        "lizard_functions.csv",
        "lizard-functions.csv",
        "complexity.csv",
        "Complexity.csv",
    ]

    fixed_subpaths = [
        ("complexity", "lizard.csv"),
        ("complexity", "lizard_report.csv"),
        ("complexity", "lizard_functions.csv"),
        ("complexity", "complexity.csv"),
        ("complexity", "Complexity.csv"),
        ("complexity", "complexity_report.csv"),
        ("build_host", "complexity.csv"),
        ("build_target", "complexity.csv"),
        ("build_host", "lizard.csv"),
        ("build_target", "lizard.csv"),
        ("reports", "build_host", "complexity.csv"),
        ("reports", "build_target", "complexity.csv"),
        ("reports", "build_host", "lizard.csv"),
        ("reports", "build_target", "lizard.csv"),
        ("report", "complexity.csv"),
        ("report", "complexity", "complexity.csv"),
        ("report", "complexity", "lizard.csv"),
        ("report", "complexity", "lizard_report.csv"),
    ]

    candidates: List[Path] = []
    for d in search_dirs:
        for nm in fixed_names:
            candidates.append(d / nm)
        for sp in fixed_subpaths:
            candidates.append(d.joinpath(*sp))

    for p in candidates:
        try:
            if p.exists() and p.is_file() and p.stat().st_size > 0:
                df = _read_lizard_csv_cached(p)
                if df is not None:
                    _set_last_lizard_path(p)
                    return df
        except Exception:
            continue

    # 2) fallback: rglob (후보 제한, report_dir + alt_dir 포함)
    try:
        hits: List[Path] = []
        glob_pats = [
            "*lizard*.csv",
            "*Lizard*.csv",
            "*complexity*.csv",
            "*Complexity*.csv",
            "*COMPLEXITY*.csv",
        ]
        for d in search_dirs:
            for gp in glob_pats:
                for p in d.rglob(gp):
                    if not p.is_file():
                        continue
                    try:
                        sz = p.stat().st_size
                        if sz <= 0:
                            continue
                        # 너무 큰 파일은 제외 (UI 프리징 방지)
                        if sz > 80 * 1024 * 1024:
                            continue
                    except Exception:
                        continue
                    hits.append(p)
                    if len(hits) >= 30:
                        break
                if len(hits) >= 30:
                    break
            if len(hits) >= 30:
                break

        # function+file 컬럼 있는 것을 우선 선택
        for p in hits:
            df = _read_lizard_csv_cached(p)
            if df is None:
                continue
            fcol = _pick_column_case_insensitive(df, ["function", "function_name", "name", "subprogram"])
            filecol = _pick_column_case_insensitive(df, ["file", "filename", "path", "source_file", "unit"])
            if fcol and filecol:
                _set_last_lizard_path(p)
                return df

        if hits:
            df0 = _read_lizard_csv_cached(hits[0])
            if df0 is not None:
                _set_last_lizard_path(hits[0])
            return df0
    except Exception:
        return None

    # 3) Jenkins cache fallback (last resort)
    try:
        cache_root = Path.home() / ".devops_pro_cache" / "jenkins"
        if cache_root.exists() and cache_root.is_dir():
            hits = []
            for p in cache_root.rglob("reports/complexity.csv"):
                if p.is_file():
                    hits.append(p)
                    if len(hits) >= 30:
                        break
            if hits:
                hits.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
                df = _read_lizard_csv_cached(hits[0])
                if df is not None:
                    _set_last_lizard_path(hits[0])
                    return df
    except Exception:
        return None

    return None


def list_lizard_candidate_paths(report_dir: Path, limit: int = 30) -> List[Path]:
    if not report_dir:
        return []
    base = Path(str(report_dir))
    search_dirs: List[Path] = []
    try:
        if base.exists() and base.is_dir():
            search_dirs.append(base)
            for sub in ("reports", "report"):
                cand = (base / sub).resolve()
                if cand.exists() and cand.is_dir():
                    search_dirs.append(cand)
    except Exception:
        pass
    try:
        if base.name.lower() in ("reports", "report"):
            cand = base.parent.resolve()
            if cand.exists() and cand.is_dir():
                search_dirs.append(cand)
    except Exception:
        pass

    fixed_names = [
        "lizard.csv",
        "Lizard.csv",
        "lizard_report.csv",
        "Lizard_Report.csv",
        "lizard_functions.csv",
        "lizard-functions.csv",
        "complexity.csv",
        "Complexity.csv",
    ]
    fixed_subpaths = [
        ("complexity", "lizard.csv"),
        ("complexity", "lizard_report.csv"),
        ("complexity", "lizard_functions.csv"),
        ("complexity", "complexity.csv"),
        ("complexity", "Complexity.csv"),
        ("complexity", "complexity_report.csv"),
        ("build_host", "complexity.csv"),
        ("build_target", "complexity.csv"),
        ("build_host", "lizard.csv"),
        ("build_target", "lizard.csv"),
        ("reports", "build_host", "complexity.csv"),
        ("reports", "build_target", "complexity.csv"),
        ("reports", "build_host", "lizard.csv"),
        ("reports", "build_target", "lizard.csv"),
        ("report", "complexity.csv"),
        ("report", "complexity", "complexity.csv"),
        ("report", "complexity", "lizard.csv"),
        ("report", "complexity", "lizard_report.csv"),
    ]

    hits: List[Path] = []
    for d in search_dirs:
        for nm in fixed_names:
            p = d / nm
            if p.exists() and p.is_file():
                hits.append(p)
        for sp in fixed_subpaths:
            p = d.joinpath(*sp)
            if p.exists() and p.is_file():
                hits.append(p)

    glob_pats = [
        "*lizard*.csv",
        "*Lizard*.csv",
        "*complexity*.csv",
        "*Complexity*.csv",
        "*COMPLEXITY*.csv",
    ]
    for d in search_dirs:
        for gp in glob_pats:
            try:
                for p in d.rglob(gp):
                    if not p.is_file():
                        continue
                    hits.append(p)
                    if len(hits) >= limit:
                        break
            except Exception:
                continue
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break

    uniq: List[Path] = []
    seen = set()
    for p in hits:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
        if len(uniq) >= limit:
            break
    return uniq


def compute_artifacts_hash(artifacts: Optional[List[Dict[str, Any]]]) -> str:
    try:
        items: List[str] = []
        for a in artifacts or []:
            if not isinstance(a, dict):
                continue
            rel = str(a.get("relativePath") or a.get("relative_path") or a.get("path") or "")
            name = str(a.get("fileName") or a.get("file_name") or "")
            items.append(f"{rel}::{name}")
        items = sorted(set([s for s in items if s.strip()]))
        raw = "\n".join(items)
        return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()
    except Exception:
        return ""

def _is_totals_label(s: str) -> bool:
    u = str(s or "").strip().upper()
    return u in ("TOTALS", "TOTAL", "GRAND TOTALS", "GRAND_TOTALS", "GRANDTOTALS")


def _looks_numeric(s: str) -> bool:
    try:
        return bool(re.fullmatch(r"[+-]?\d+(?:\.\d+)?", str(s or "").strip()))
    except Exception:
        return False


def clean_lizard_dataframe(df: Optional["pd.DataFrame"]) -> Optional["pd.DataFrame"]:
    """Lizard/complexity CSV 로드 후 클린업, TOTALS/요약행/이상치 제거"""
    if df is None:
        return None
    try:
        import pandas as pd  # type: ignore
    except Exception:
        return df

    try:
        file_col = _pick_column_case_insensitive(df, ["file", "filename", "path", "source_file", "unit"])
        func_col = _pick_column_case_insensitive(df, ["function", "function_name", "name", "subprogram"])
        if not file_col or not func_col:
            return df

        d2 = df.copy()

        # 문자열 정리
        d2[file_col] = d2[file_col].astype(str).fillna("").map(lambda x: str(x).strip())
        d2[func_col] = d2[func_col].astype(str).fillna("").map(lambda x: str(x).strip())

        # 빈 값 제거
        d2 = d2[(d2[file_col] != "") & (d2[func_col] != "")]

        # TOTALS/GRAND TOTALS 제거
        f_u = d2[file_col].astype(str).str.upper()
        fn_u = d2[func_col].astype(str).str.upper()
        d2 = d2[~(f_u.map(_is_totals_label) | fn_u.map(_is_totals_label))]

        # 일부 리포트에서 TOTALS가 file에 들어가고 function이 숫자(개수/합계)로 들어오는 케이스 제거
        f_u2 = d2[file_col].astype(str).str.upper()
        mask_bad = (f_u2 == "TOTALS") & d2[func_col].astype(str).map(_looks_numeric)
        d2 = d2[~mask_bad]

        # 중복 제거(파일+함수 기준)
        key = d2[file_col].astype(str) + "::" + d2[func_col].astype(str)
        d2 = d2.loc[~key.duplicated(keep="first")]

        return d2.reset_index(drop=True)
    except Exception:
        return df



def _read_lizard_csv_cached(p: Path) -> Optional["pd.DataFrame"]:
    """
    Lizard/complexity CSV reader
    - 인코딩: utf-8 / utf-8-sig / cp949
    - 구분자: 자동 추정(, ; \t), 필요 시 헤더 라인 탐색 후 skiprows 적용
    """
    try:
        import pandas as pd  # type: ignore
    except Exception:
        return None

    try:
        p = Path(str(p))
        st = p.stat()
        key = str(p)
        cached = _LIZARD_CACHE.get(key)
        if cached and cached[0] == st.st_mtime:
            return cached[1]  # type: ignore[index]

        encs = ("utf-8", "utf-8-sig", "cp949", "utf-16", "utf-16-le", "utf-16-be")

        def _try_read(*, sep: Optional[str], enc: str, skiprows: int = 0) -> "pd.DataFrame":
            # sep=None -> python engine sniffing
            return pd.read_csv(
                p,
                encoding=enc,
                engine="python",
                sep=sep,
                on_bad_lines="skip",
                skiprows=skiprows if skiprows > 0 else None,
            )

        def _has_cols(df: "pd.DataFrame") -> bool:
            fcol = _pick_column_case_insensitive(df, ["file", "filename", "path", "source_file", "unit"])
            fncol = _pick_column_case_insensitive(df, ["function", "function_name", "name", "subprogram"])
            return bool(fcol and fncol)

        # 1) 기본 시도: sep 자동 추정(None) -> 실패 시 , 고정 -> ; -> \t
        last_e: Optional[Exception] = None
        df: Optional["pd.DataFrame"] = None

        for enc in encs:
            try:
                df = _try_read(sep=None, enc=enc)
                last_e = None
                break
            except Exception as e:
                last_e = e
                df = None

        if df is None:
            for enc in encs:
                for sep in (",", ";", "\t"):
                    try:
                        df = _try_read(sep=sep, enc=enc)
                        last_e = None
                        break
                    except Exception as e:
                        last_e = e
                        df = None
                if df is not None:
                    break

        if df is None:
            # Fallback: minimal CSV parsing without pandas inference.
            raw = None
            used_enc = "utf-8"
            for enc in encs:
                try:
                    raw = p.read_text(encoding=enc, errors="ignore")
                    used_enc = enc
                    break
                except Exception:
                    raw = None
            if raw:
                try:
                    lines = raw.splitlines()
                    header_idx = None
                    header_line = ""
                    for i, ln in enumerate(lines[:80]):
                        lnu = (ln or "").strip().lower()
                        if not lnu:
                            continue
                        if ("file" in lnu and "function" in lnu) or ("unit" in lnu and "subprogram" in lnu):
                            header_idx = i
                            header_line = ln
                            break
                    if header_idx is not None:
                        delim = "," if ";" not in header_line and "\t" not in header_line else (";" if ";" in header_line else "\t")
                        import csv as _csv
                        from io import StringIO
                        sio = StringIO("\n".join(lines[header_idx:]))
                        reader = _csv.DictReader(sio, delimiter=delim)
                        rows: List[Dict[str, Any]] = []
                        for row in reader:
                            if not isinstance(row, dict):
                                continue
                            rows.append(row)
                        if rows:
                            df = pd.DataFrame(rows)
                except Exception:
                    df = None
            if df is None:
                raise last_e or RuntimeError("read_csv failed")

        # 2) 단일 컬럼/헤더 이상 감지 시, 헤더 라인 탐색 후 재시도
        if not _has_cols(df) or len(df.columns) == 1:
            try:
                raw = None
                used_enc = "utf-8"
                for enc in encs:
                    try:
                        raw = p.read_text(encoding=enc, errors="ignore")
                        used_enc = enc
                        break
                    except Exception:
                        continue
                if raw:
                    lines = raw.splitlines()
                    header_idx = None
                    header_sep = None
                    for i, ln in enumerate(lines[:80]):
                        lnu = ln.strip().lower()
                        if not lnu:
                            continue
                        # 헤더 후보: file/function 또는 unit/subprogram 조합
                        if ("file" in lnu and "function" in lnu) or ("unit" in lnu and "subprogram" in lnu):
                            # sep 추정
                            if ";" in ln:
                                header_sep = ";"
                            elif "\t" in ln:
                                header_sep = "\t"
                            else:
                                header_sep = ","
                            header_idx = i
                            break
                    if header_idx is not None:
                        df2 = _try_read(sep=header_sep, enc=used_enc, skiprows=header_idx)
                        if df2 is not None and len(df2.columns) >= 2:
                            df = df2
            except Exception:
                pass

        cleaned = clean_lizard_dataframe(df)
        if cleaned is not None:
            df = cleaned
        _LIZARD_CACHE[key] = (st.st_mtime, df)
        _set_last_lizard_error(None)
        return df
    except Exception as e:
        _set_last_lizard_error(f"{type(e).__name__}: {e}")
        return None

def code_metrics_from_lizard(df: Optional["pd.DataFrame"]) -> Dict[str, Optional[float]]:
    """
    반환 키
    - code_files: 소스 파일 수(함수 목록 기준 unique file)
    - functions: 함수 수(파일+함수 unique)
    - nloc: NLOC 합계(가능한 경우, 파일+함수 unique 기준)
    """
    out: Dict[str, Optional[float]] = {"code_files": None, "functions": None, "nloc": None}
    if df is None:
        return out

    try:
        import pandas as pd  # type: ignore
    except Exception:
        return out

    try:
        d2 = clean_lizard_dataframe(df)
        if d2 is None:
            d2 = df

        file_col = _pick_column_case_insensitive(d2, ["file", "filename", "path", "source_file", "unit"])
        func_col = _pick_column_case_insensitive(d2, ["function", "function_name", "name", "subprogram"])
        nloc_col = _pick_column_case_insensitive(d2, ["nloc", "NLOC", "loc", "lines", "line_count"])

        if not file_col or not func_col:
            return out

        # key
        k = d2[file_col].astype(str).fillna("").map(lambda x: str(x).strip()) + "::" + d2[func_col].astype(str).fillna("").map(lambda x: str(x).strip())
        d2 = d2.copy()
        d2["_key"] = k
        d2 = d2[d2["_key"] != "::"]

        out["code_files"] = float(d2[file_col].astype(str).nunique())
        out["functions"] = float(d2["_key"].nunique())

        if nloc_col and nloc_col in d2.columns:
            s = pd.to_numeric(d2[nloc_col], errors="coerce").fillna(0.0)
            d2["_nloc"] = s
            # 중복 키는 최대값을 사용(리포트 중복 행 방어)
            out["nloc"] = float(d2.groupby("_key")["_nloc"].max().sum())
    except Exception:
        return out

    return out


def function_keys_from_lizard(df: Optional["pd.DataFrame"]) -> set[str]:
    """함수 diff용 키 집합 생성(file::function)"""
    if df is None:
        return set()
    try:
        import pandas as pd  # type: ignore
    except Exception:
        return set()

    try:
        d2 = clean_lizard_dataframe(df)
        if d2 is None:
            d2 = df
        file_col = _pick_column_case_insensitive(d2, ["file", "filename", "path", "source_file", "unit"])
        func_col = _pick_column_case_insensitive(d2, ["function", "function_name", "name", "subprogram"])
        if not file_col or not func_col:
            return set()

        f = d2[file_col].astype(str).fillna("").map(lambda x: str(x).strip())
        fn = d2[func_col].astype(str).fillna("").map(lambda x: str(x).strip())
        keys = (f + "::" + fn).tolist()
        return set([k for k in keys if k and k != "::"])
    except Exception:
        return set()


def _function_metric_maps(df: Optional["pd.DataFrame"]) -> Dict[str, Dict[str, Any]]:
    """key(file::func) -> metrics(ccn/nloc)"""
    out: Dict[str, Dict[str, Any]] = {}
    if df is None:
        return out
    try:
        import pandas as pd  # type: ignore
    except Exception:
        return out

    try:
        d2 = clean_lizard_dataframe(df)
        if d2 is None:
            d2 = df
        file_col = _pick_column_case_insensitive(d2, ["file", "filename", "path", "source_file", "unit"])
        func_col = _pick_column_case_insensitive(d2, ["function", "function_name", "name", "subprogram"])
        ccn_col = _pick_column_case_insensitive(d2, ["ccn", "cyclomatic_complexity", "complexity", "v(g)", "vg"])
        nloc_col = _pick_column_case_insensitive(d2, ["nloc", "loc", "lines", "line_count"])

        if not file_col or not func_col:
            return out

        f = d2[file_col].astype(str).fillna("").map(lambda x: str(x).strip())
        fn = d2[func_col].astype(str).fillna("").map(lambda x: str(x).strip())
        key = (f + "::" + fn).tolist()

        ccn_s = None
        if ccn_col and ccn_col in d2.columns:
            ccn_s = pd.to_numeric(d2[ccn_col], errors="coerce").fillna(0).astype(int).tolist()

        nloc_s = None
        if nloc_col and nloc_col in d2.columns:
            nloc_s = pd.to_numeric(d2[nloc_col], errors="coerce").fillna(0).astype(int).tolist()

        for i, k in enumerate(key):
            if not k or k == "::":
                continue
            if k in out:
                continue  # 첫 값 유지(중복 방어)
            out[k] = {}
            if ccn_s is not None:
                out[k]["ccn"] = ccn_s[i]
            if nloc_s is not None:
                out[k]["nloc"] = nloc_s[i]
        return out
    except Exception:
        return out


def summarize_function_diff(cur_df: Optional["pd.DataFrame"], prev_df: Optional["pd.DataFrame"], limit: int = 30) -> Dict[str, Any]:
    """
    함수 추가/삭제 + (가능한 경우) 복잡도/라인 변경 요약
    - added/removed는 file::func 기준
    - modified는 동일 key에서 CCN/NLOC 변화가 있는 항목
    """
    cur_keys = function_keys_from_lizard(cur_df)
    prev_keys = function_keys_from_lizard(prev_df)

    added_keys = sorted(list(cur_keys - prev_keys))
    removed_keys = sorted(list(prev_keys - cur_keys))

    cur_map = _function_metric_maps(cur_df)
    prev_map = _function_metric_maps(prev_df)

    # modified(교집합 중 CCN/NLOC 변화)
    modified: List[Dict[str, Any]] = []
    if cur_map and prev_map:
        for k in (cur_keys & prev_keys):
            c = cur_map.get(k) or {}
            p = prev_map.get(k) or {}
            d_ccn = None
            d_nloc = None
            if "ccn" in c and "ccn" in p:
                d_ccn = int(c.get("ccn", 0)) - int(p.get("ccn", 0))
            if "nloc" in c and "nloc" in p:
                d_nloc = int(c.get("nloc", 0)) - int(p.get("nloc", 0))

            if (d_ccn is not None and d_ccn != 0) or (d_nloc is not None and d_nloc != 0):
                score = abs(int(d_nloc or 0)) + abs(int(d_ccn or 0)) * 10
                modified.append({
                    "key": k,
                    "d_ccn": d_ccn,
                    "d_nloc": d_nloc,
                    "score": score,
                })

        modified.sort(key=lambda x: int(x.get("score") or 0), reverse=True)

    def _pretty_key(k: str) -> str:
        parts = k.split("::")
        if len(parts) >= 2:
            return f"{parts[0]} :: {parts[1]}"
        return k

    def _pretty_with_metrics(k: str, *, mode: str) -> str:
        base = _pretty_key(k)
        m = cur_map.get(k) if mode == "cur" else prev_map.get(k)
        if not m:
            return base
        ccn = m.get("ccn")
        nloc = m.get("nloc")
        if ccn is None and nloc is None:
            return base
        tail = []
        if ccn is not None:
            tail.append(f"CCN {int(ccn)}")
        if nloc is not None:
            tail.append(f"NLOC {int(nloc)}")
        return f"{base} ({', '.join(tail)})"

    def _pretty_modified(d: Dict[str, Any]) -> str:
        k = str(d.get("key") or "")
        base = _pretty_key(k)
        d_ccn = d.get("d_ccn")
        d_nloc = d.get("d_nloc")
        tail = []
        if d_ccn is not None and int(d_ccn) != 0:
            tail.append(f"CCN {int(d_ccn):+d}")
        if d_nloc is not None and int(d_nloc) != 0:
            tail.append(f"NLOC {int(d_nloc):+d}")
        if not tail:
            return base
        return f"{base} ({', '.join(tail)})"

    added_list = [_pretty_with_metrics(k, mode="cur") for k in added_keys[:limit]]
    removed_list = [_pretty_with_metrics(k, mode="prev") for k in removed_keys[:limit]]
    modified_list = [_pretty_modified(d) for d in modified[:limit]]

    return {
        "added_count": len(added_keys),
        "removed_count": len(removed_keys),
        "modified_count": len(modified),
        "added_list": added_list,
        "removed_list": removed_list,
        "modified_list": modified_list,
    }


def generate_function_change_summary(
    current_report_dir: Path,
    prev_report_dir: Optional[Path],
    *,
    output_dir: Path,
    build_id: Optional[str] = None,
    artifacts_hash: Optional[str] = None,
    enable_ai: bool = True,
    oai_config_path: Optional[str] = None,
    limit: int = 50,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Create function change summaries (JSON + Markdown) based on lizard/complexity CSVs.
    - AI summary is appended only when changes exist.
    - If the latest summary already matches build_id, no-op.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    latest_json = output_dir / "function_changes.json"
    history_json = output_dir / "function_changes_history.json"
    latest_md = output_dir / "function_changes.md"

    if latest_json.exists() and build_id and not force:
        try:
            last = load_json(latest_json, default={})
            if isinstance(last, dict) and str(last.get("build_id") or "") == str(build_id):
                if artifacts_hash and str(last.get("artifacts_hash") or "") != str(artifacts_hash):
                    pass
                else:
                    return last
        except Exception:
            pass

    cur_df = load_lizard_dataframe(current_report_dir)
    prev_df = load_lizard_dataframe(prev_report_dir) if prev_report_dir else None
    baseline = prev_df is None
    diff = summarize_function_diff(cur_df, prev_df, limit=limit)

    changed = bool(
        (diff.get("added_count") or 0)
        or (diff.get("removed_count") or 0)
        or (diff.get("modified_count") or 0)
    )

    top_functions = _top_functions_from_df(cur_df, limit=200)
    summary: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "build_id": build_id,
        "current_report_dir": str(current_report_dir) if current_report_dir else None,
        "prev_report_dir": str(prev_report_dir) if prev_report_dir else None,
        "baseline": baseline,
        "changed": changed,
        "diff": diff,
        "top_functions": top_functions,
        "artifacts_hash": artifacts_hash,
        "ai_summary": None,
        "ai_model": None,
    }

    ai_text: Optional[str] = None
    ai_error: Optional[str] = None
    if enable_ai:
        try:
            from workflow import ai as ai_mod  # type: ignore
        except Exception:
            ai_mod = None  # type: ignore
        if ai_mod:
            try:
                cfg = ai_mod.load_oai_config(oai_config_path)
                if cfg:
                    if changed:
                        prompt = (
                            "코드 리뷰 로그용 함수 변화 요약을 작성해줘.\n"
                            "삭제/변경으로 인한 위험도와 동작 영향 중심으로 간결하게 정리해줘.\n"
                            "형식은 짧은 항목형 요약이 좋음.\n\n"
                            f"추가 ({diff.get('added_count', 0)}):\n"
                            + "\n".join(diff.get("added_list") or [])
                            + "\n\n삭제 ({diff.get('removed_count', 0)}):\n"
                            + "\n".join(diff.get("removed_list") or [])
                            + "\n\n변경 ({diff.get('modified_count', 0)}):\n"
                            + "\n".join(diff.get("modified_list") or [])
                        )
                    else:
                        prompt = (
                            "코드 리뷰 로그용 전체 함수 요약을 작성해줘.\n"
                            "규모/복잡도가 큰 모듈과 잠재 위험 구간 중심으로 간결하게 정리해줘.\n"
                            "형식은 짧은 항목형 요약이 좋음.\n\n"
                            "상위 함수 (file :: function, CCN, NLOC):\n"
                            + "\n".join(
                                [
                                    f"{t.get('file')} :: {t.get('function')} (CCN {t.get('ccn')}, NLOC {t.get('nloc')})"
                                    for t in top_functions[:50]
                                ]
                            )
                        )
                    messages = [{"role": "user", "content": prompt}]
                    meta: Dict[str, Any] = {}
                    ai_text = ai_mod.llm_call(cfg, messages, log_dir=output_dir, meta_out=meta, stage="function_diff")
                    summary["ai_summary"] = (ai_text or "").strip() or None
                    summary["ai_model"] = meta.get("model")
            except Exception:
                summary["ai_summary"] = None
                ai_error = "ai_call_failed"
        else:
            ai_error = "ai_module_unavailable"
    else:
        ai_error = "ai_disabled"
    if ai_error:
        summary["ai_error"] = ai_error

    try:
        latest_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    try:
        hist = load_json(history_json, default=[])
        if not isinstance(hist, list):
            hist = []
        hist.append(summary)
        hist = hist[-100:]
        history_json.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    try:
        lines = [
            "# Function Change Summary",
            f"- generated_at: {summary.get('generated_at')}",
            f"- build_id: {summary.get('build_id')}",
            f"- changed: {summary.get('changed')}",
            "",
            "## Added",
        ]
        for item in diff.get("added_list") or []:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("## Removed")
        for item in diff.get("removed_list") or []:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("## Modified")
        for item in diff.get("modified_list") or []:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("## AI Summary")
        if ai_text:
            lines.append(ai_text.strip())
        else:
            lines.append("(not generated)")
        latest_md.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    except Exception:
        pass

    return summary


def generate_custom_code_summary(
    *,
    report_dir: Path,
    prompt: str,
    oai_config_path: Optional[str],
    output_name: str,
) -> Dict[str, Any]:
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "prompt": prompt,
        "ai_summary": None,
        "ai_model": None,
        "ai_error": None,
    }
    try:
        from workflow import ai as ai_mod  # type: ignore
    except Exception:
        out["ai_error"] = "ai_module_unavailable"
        return out

    try:
        cfg = ai_mod.load_oai_config(oai_config_path)
        if not cfg:
            out["ai_error"] = "missing_config"
            return out
        if isinstance(cfg, list):
            cfg = cfg[0]
        messages = [{"role": "user", "content": prompt}]
        meta: Dict[str, Any] = {}
        ai_text = ai_mod.llm_call(cfg, messages, log_dir=report_dir, meta_out=meta, stage="code_summary")
        out["ai_summary"] = (ai_text or "").strip() or None
        out["ai_model"] = meta.get("model")
    except Exception:
        out["ai_error"] = "ai_call_failed"

    try:
        p = Path(report_dir) / output_name
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return out


def _top_functions_from_df(df: Optional["pd.DataFrame"], limit: int = 200) -> List[Dict[str, Any]]:
    if df is None:
        return []
    try:
        d2 = clean_lizard_dataframe(df)
        if d2 is None:
            d2 = df
        file_col = _pick_column_case_insensitive(d2, ["file", "filename", "path", "source_file", "unit"])
        func_col = _pick_column_case_insensitive(d2, ["function", "function_name", "name", "subprogram"])
        ccn_col = _pick_column_case_insensitive(d2, ["ccn", "cyclomatic_complexity", "complexity", "v(g)", "vg"])
        nloc_col = _pick_column_case_insensitive(d2, ["nloc", "NLOC", "loc", "lines", "line_count"])
        if not (file_col and func_col):
            return []
        d3 = d2.copy()
        if ccn_col and ccn_col in d3.columns:
            d3["_ccn"] = pd.to_numeric(d3[ccn_col], errors="coerce").fillna(0.0)
        else:
            d3["_ccn"] = 0.0
        if nloc_col and nloc_col in d3.columns:
            d3["_nloc"] = pd.to_numeric(d3[nloc_col], errors="coerce").fillna(0.0)
        else:
            d3["_nloc"] = 0.0
        d3 = d3.sort_values(["_ccn", "_nloc"], ascending=[False, False])
        rows: List[Dict[str, Any]] = []
        for _, r in d3.head(limit).iterrows():
            rows.append(
                {
                    "file": str(r.get(file_col, "")),
                    "function": str(r.get(func_col, "")),
                    "ccn": int(r.get("_ccn") or 0),
                    "nloc": int(r.get("_nloc") or 0),
                }
            )
        return rows
    except Exception:
        return []


def find_prev_build_dir(build_root: Path) -> Optional[Path]:
    """
    build_### 디렉터리 기준 이전 빌드 디렉터리 탐색
    - 동일 parent의 build_* 중 현재 번호보다 작은 최대값 선택
    """
    try:
        build_root = Path(str(build_root))
        parent = build_root.parent
        m = re.search(r"(\d+)$", build_root.name)
        cur_num = int(m.group(1)) if m else None
        if cur_num is None:
            return None

        best_num: Optional[int] = None
        best_path: Optional[Path] = None
        for p in parent.iterdir():
            if not p.is_dir():
                continue
            m2 = re.search(r"build_(\d+)$", p.name)
            if not m2:
                continue
            n = int(m2.group(1))
            if n < cur_num and (best_num is None or n > best_num):
                best_num = n
                best_path = p
        return best_path
    except Exception:
        return None
