"""Session and profile management domain helpers."""
import re
import os
import sys
import json
import shutil
import logging
import zipfile
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    from fastapi import HTTPException
except ImportError:
    HTTPException = Exception

from backend.state import (
    session_list_cache as _session_list_cache,
    running_processes as _running_processes,
)

import config

from backend.helpers.common import (
    _read_json,
    _write_json,
    _is_relative_to,
    _split_csv,
    _safe_int,
    SETTINGS_FILE,
)
from backend.services.jenkins_helpers import _detect_reports_dir

_logger = logging.getLogger("devops_api")

repo_root = Path(__file__).resolve().parents[2]



def _load_vectorcast_rag(build_root: Path) -> Dict[str, Any]:
    report_dir = _detect_reports_dir(build_root)
    rag_path = report_dir / "vectorcast_rag" / "vectorcast_rag.json"
    return _read_json(rag_path, default={})


def _session_dir(base_report_dir: str, session_id: str) -> Path:
    base = Path(base_report_dir).resolve()
    return base / "sessions" / session_id


def _session_meta_path(session_dir: Path) -> Path:
    return session_dir / "session_meta.json"


def _load_session_meta(session_dir: Path) -> Dict[str, Any]:
    return _read_json(_session_meta_path(session_dir), default={})


def _save_session_meta(session_dir: Path, meta: Dict[str, Any]) -> None:
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(_session_meta_path(session_dir), meta)


def _default_base_report_dir() -> str:
    return str(getattr(config, "DEFAULT_REPORT_DIR", "reports"))


def _exports_dir(base_report_dir: str) -> Path:
    return Path(base_report_dir).resolve() / "exports"


def _resolve_base_dir(base: Optional[str]) -> Path:
    default_base = Path(_default_base_report_dir()).resolve()
    if not base:
        return default_base
    candidate = Path(base).resolve()
    allow_override = bool(getattr(config, "ALLOW_BASE_OVERRIDE", False))
    if allow_override:
        return candidate
    if _is_relative_to(candidate, default_base):
        return candidate
    raise HTTPException(status_code=403, detail="base override not allowed")


def _resolve_export_path(base_dir: Path, filename: str) -> Path:
    exports_dir = _exports_dir(str(base_dir)).resolve()
    candidate = (exports_dir / filename).resolve()
    if not _is_relative_to(candidate, exports_dir):
        raise HTTPException(status_code=400, detail="invalid export path")
    return candidate


def _resolve_report_dir(report_dir: Optional[str]) -> Path:
    base_dir = _resolve_base_dir(None)
    if not report_dir:
        return base_dir
    candidate = Path(report_dir).resolve()
    if not _is_relative_to(candidate, base_dir) and candidate != base_dir:
        raise HTTPException(status_code=403, detail="report_dir not allowed")
    return candidate


def _local_reports_dir(report_dir: Path) -> Path:
    return report_dir / "local_reports"


def _resolve_local_report_path(report_dir: Path, filename: str) -> Path:
    reports_dir = _local_reports_dir(report_dir).resolve()
    candidate = (reports_dir / filename).resolve()
    if not _is_relative_to(candidate, reports_dir):
        raise HTTPException(status_code=400, detail="invalid report path")
    return candidate


def _load_raw_profiles() -> Dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return {"profiles": {}, "last_profile": None}
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"profiles": {}, "last_profile": None}
    if not isinstance(raw, dict):
        return {"profiles": {}, "last_profile": None}
    raw.setdefault("profiles", {})
    raw.setdefault("last_profile", None)
    return raw


def _save_raw_profiles(raw: Dict[str, Any]) -> None:
    SETTINGS_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_profile(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
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
        "complexity_threshold": _safe_int(
            cfg.get("complexity_threshold"),
            getattr(config, "DEFAULT_COMPLEXITY_THRESHOLD", 10),
        ),
        "coverage_warn_pct": _safe_int(
            cfg.get("coverage_warn_pct"),
            getattr(config, "DEFAULT_COVERAGE_WARN_PCT", 80),
        ),
        "coverage_fail_pct": _safe_int(
            cfg.get("coverage_fail_pct"),
            getattr(config, "DEFAULT_COVERAGE_FAIL_PCT", 50),
        ),
        "tests_min_count": _safe_int(
            cfg.get("tests_min_count"),
            getattr(config, "DEFAULT_TESTS_MIN_COUNT", 1),
        ),
        "test_gen_timeout_sec": _safe_int(
            cfg.get("test_gen_timeout_sec"),
            getattr(config, "DEFAULT_TEST_GEN_TIMEOUT_SEC", 300),
        ),
        "require_tests_enabled": bool(cfg.get("require_tests_enabled", getattr(config, "DEFAULT_REQUIRE_TESTS_ENABLED", True))),
        "enable_agent": bool(cfg.get("enable_agent", False)),
        "enable_test_gen": bool(cfg.get("enable_test_gen", False)),
        "auto_run_tests": bool(cfg.get("auto_run_tests", False)),
        "max_iterations": _safe_int(cfg.get("max_iterations"), 3),
        "oai_config_path": cfg.get("oai_config_path"),
        "llm_model": cfg.get("llm_model"),
        "agent_roles": _split_csv(cfg.get("agent_roles")),
        "agent_run_mode": cfg.get("agent_run_mode"),
        "agent_review": bool(cfg.get("agent_review", True)),
        "agent_rag": bool(cfg.get("agent_rag", True)),
        "agent_rag_top_k": _safe_int(
            cfg.get("agent_rag_top_k"),
            getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3),
        ),
        "uds_rag_top_k": _safe_int(
            cfg.get("uds_rag_top_k"),
            getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3),
        ),
        "uds_rag_categories": _split_csv(cfg.get("uds_rag_categories")),
        "agent_max_steps": _safe_int(
            cfg.get("agent_max_steps"),
            getattr(config, "AGENT_MAX_STEPS_DEFAULT", 3),
        ),
        "auto_fix_scope": cfg.get("auto_fix_scope", []),
        "auto_fix_on_fail": bool(cfg.get("auto_fix_on_fail", False)),
        "auto_fix_on_fail_stages": cfg.get("auto_fix_on_fail_stages", []),
        "enable_domain_tests": bool(cfg.get("enable_domain_tests", False)),
        "domain_tests_auto": bool(cfg.get("domain_tests_auto", getattr(config, "DOMAIN_TESTS_AUTO", True))),
        "domain_targets": _split_csv(cfg.get("domain_targets")),
        "agent_patch_mode": cfg.get("agent_patch_mode"),
        "source_priority": _split_csv(cfg.get("source_priority")),
        "local_source_roots": _split_csv(cfg.get("local_source_roots")),
        "artifact_success_rule": cfg.get("artifact_success_rule"),
        "artifact_source_root": cfg.get("artifact_source_root"),
        "rag_ingest_enable": bool(cfg.get("rag_ingest_enable", True)),
        "rag_ingest_on_pipeline": bool(cfg.get("rag_ingest_on_pipeline", getattr(config, "RAG_INGEST_ON_PIPELINE", True))),
        "rag_ingest_max_files": _safe_int(cfg.get("rag_ingest_max_files"), getattr(config, "RAG_INGEST_MAX_FILES", 200)),
        "rag_ingest_max_chunks": _safe_int(cfg.get("rag_ingest_max_chunks"), getattr(config, "RAG_INGEST_MAX_CHUNKS_PER_FILE", 12)),
        "rag_chunk_size": _safe_int(cfg.get("rag_chunk_size"), getattr(config, "RAG_CHUNK_SIZE", 1200)),
        "rag_chunk_overlap": _safe_int(cfg.get("rag_chunk_overlap"), getattr(config, "RAG_CHUNK_OVERLAP", 200)),
        "vc_reports_paths": _split_csv(cfg.get("vc_reports_paths")),
        "uds_spec_paths": _split_csv(cfg.get("uds_spec_paths")),
        "req_docs_paths": _split_csv(cfg.get("req_docs_paths")),
        "codebase_paths": _split_csv(cfg.get("codebase_paths")),
        "kb_storage": cfg.get("kb_storage"),
        "pgvector_dsn": cfg.get("pgvector_dsn"),
        "pgvector_url": cfg.get("pgvector_url"),
        # D-1: Multi-project profile fields
        "llm_provider": cfg.get("llm_provider"),
        "uds_template_path": cfg.get("uds_template_path"),
        "uds_ai_enabled": bool(cfg.get("uds_ai_enabled", False)),
        "uds_ai_detailed": bool(cfg.get("uds_ai_detailed", True)),
        "uds_logic_source": cfg.get("uds_logic_source", "call_tree"),
        "sts_max_tc_per_req": _safe_int(cfg.get("sts_max_tc_per_req"), 6),
        "suts_max_seq": _safe_int(cfg.get("suts_max_seq"), 6),
        "quality_gate_thresholds": cfg.get("quality_gate_thresholds", {}),
        "delta_update_enabled": bool(cfg.get("delta_update_enabled", False)),
        "doxygen_auto_insert": bool(cfg.get("doxygen_auto_insert", False)),
        # Jenkins connection fields
        "jenkins_base_url": cfg.get("jenkins_base_url", ""),
        "jenkins_username": cfg.get("jenkins_username", ""),
        "jenkins_api_token": cfg.get("jenkins_api_token", ""),
        "jenkins_verify_tls": bool(cfg.get("jenkins_verify_tls", True)),
        "jenkins_cache_root": cfg.get("jenkins_cache_root", ""),
        "jenkins_build_selector": cfg.get("jenkins_build_selector", "latest"),
        "jenkins_server_root": cfg.get("jenkins_server_root", ""),
        "jenkins_server_rel_path": cfg.get("jenkins_server_rel_path", ""),
    }


def _resolve_source_root_from_cfg(cfg: Dict[str, Any], fallback_root: Optional[str]) -> Tuple[Dict[str, Any], str]:
    try:
        from workflow import gui_utils  # type: ignore

        resolved = gui_utils.resolve_source_root(cfg)
    except Exception:
        resolved = {
            "root": fallback_root or cfg.get("project_root") or ".",
            "source": "cfg",
            "reason": "fallback",
        }
    root = str(resolved.get("root") or fallback_root or cfg.get("project_root") or ".")
    resolved["root"] = root
    return resolved, root


def _build_preflight(cfg: Dict[str, Any]) -> Dict[str, Any]:
    def _check_any(names: List[str]) -> str:
        for name in names:
            if shutil.which(name):
                return name
        return ""

    full_analysis = not bool(cfg.get("git_incremental", False))
    do_build_and_test = bool(cfg.get("do_build", False))
    do_asan = bool(cfg.get("do_asan", False))
    do_coverage = bool(cfg.get("do_coverage", False))
    enable_test_gen = bool(cfg.get("enable_test_gen", False))
    auto_run_tests = bool(cfg.get("auto_run_tests", getattr(config, "AUTO_RUN_TESTS", False)))
    do_clang_tidy = bool(cfg.get("do_clang_tidy", False))
    enable_semgrep = bool(cfg.get("enable_semgrep", False))
    do_syntax_check = bool(cfg.get("do_syntax_check", True))
    do_qemu = bool(cfg.get("do_qemu", False))
    do_docs = bool(cfg.get("do_docs", False))
    do_fuzz = bool(cfg.get("do_fuzz", False))
    cppcheck_enable = cfg.get("cppcheck_levels") or cfg.get("cppcheck_enable") or []

    if do_coverage or do_asan:
        do_build_and_test = True
    if enable_test_gen and auto_run_tests:
        do_build_and_test = True

    preflight: Dict[str, Any] = {"tools": {}, "missing": [], "warnings": []}

    def _record(key: str, names: List[str], required: bool) -> None:
        found = _check_any(names)
        preflight["tools"][key] = found
        if required and not found:
            preflight["missing"].append(key)

    _record("git", ["git"], required=not full_analysis)
    if do_build_and_test:
        _record("cmake", ["cmake"], required=True)
        _record("build_tool", ["ninja", "make"], required=False)
        _record("cc", ["gcc", "clang", "arm-none-eabi-gcc"], required=False)
    if cppcheck_enable:
        _record("cppcheck", ["cppcheck"], required=True)
    if do_clang_tidy:
        _record("clang_tidy", ["clang-tidy"], required=True)
    if enable_semgrep:
        found = _check_any(["semgrep"])
        preflight["tools"]["semgrep"] = found
        if not found:
            preflight["warnings"].append("semgrep_missing_disabled")
    if do_syntax_check:
        _record("gcc_syntax", ["gcc", "clang", "arm-none-eabi-gcc"], required=False)
    if do_qemu:
        _record("qemu", ["qemu-system-arm", "qemu-system-aarch64"], required=False)
    if do_docs:
        _record("doxygen", ["doxygen"], required=False)
    if do_fuzz:
        _record("fuzzer", ["clang", "gcc"], required=False)
    if preflight["missing"]:
        preflight["warnings"].append("missing_required_tools")
    return preflight


def _collect_tool_paths() -> List[str]:
    candidates = list(getattr(config, "TOOL_SEARCH_PATHS", []) or [])
    venv_scripts = str((repo_root / "backend" / "venv" / "Scripts").resolve())
    if venv_scripts not in candidates:
        candidates.insert(0, venv_scripts)
    if len(candidates) == 1:
        candidates.extend(
            [
                r"C:\Program Files\LLVM\bin",
                r"C:\Program Files\Cppcheck",
                r"C:\msys64\mingw64\bin",
            ]
        )
    return [p for p in candidates if Path(p).exists()]


def _augment_path(path_value: str, extra_paths: Optional[List[str]] = None) -> str:
    existing = [p for p in (path_value or "").split(os.pathsep) if p]
    extras = [p for p in (extra_paths or []) if p]
    merged = existing[:]
    for p in extras:
        if p not in merged:
            merged.insert(0, p)
    return os.pathsep.join(merged)


def _invalidate_session_cache(base_dir: Optional[Path] = None) -> None:
    """세션 목록 캐시 무효화"""
    if base_dir:
        cache_key = str(base_dir.resolve())
        _session_list_cache.pop(cache_key, None)
    else:
        _session_list_cache.clear()


def _track_process(session_id: str, pid: int, status_path: str) -> None:
    _running_processes[session_id] = {"pid": pid, "status_path": status_path, "started_at": datetime.now().isoformat()}


def _local_uds_dir(report_dir: Optional[str]) -> Path:
    report_path = _resolve_report_dir(report_dir)
    return report_path / "uds_local"


def _resolve_local_uds_path(report_dir: Optional[str], filename: str) -> Path:
    base = _local_uds_dir(report_dir).resolve()
    target = (base / filename).resolve()
    if str(target).startswith(str(base)):
        return target
    return base / Path(filename).name


def _local_sts_dir(base: Path) -> Path:
    return base / "sts"


def _resolve_local_sts_path(report_dir: Optional[str], filename: str) -> Path:
    base = _resolve_report_dir(report_dir)
    return _local_sts_dir(base) / Path(filename).name


def _local_suts_dir(base: Path) -> Path:
    return base / "suts"


def _resolve_local_suts_path(report_dir: Optional[str], filename: str) -> Path:
    base = _resolve_report_dir(report_dir)
    return _local_suts_dir(base) / Path(filename).name


def _local_sits_dir(base: Path) -> Path:
    return base / "sits"


def _resolve_local_sits_path(report_dir: Optional[str], filename: str) -> Path:
    base = _resolve_report_dir(report_dir)
    return _local_sits_dir(base) / Path(filename).name


def _open_local_path(target: Path) -> None:
    if os.name == "nt":
        os.startfile(str(target))  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
        return
    subprocess.Popen(["xdg-open", str(target)])


def _create_zip_file(session_dir: Path, out_path: Path) -> None:
    """ZIP 파일 생성 헬퍼 함수 (백그라운드에서 실행 가능)"""
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 파일 목록을 먼저 수집하여 진행 상황 추적 가능하게 함
        files_to_add = [p for p in session_dir.rglob("*") if p.is_file()]
        for p in files_to_add:
            try:
                rel = p.relative_to(session_dir)
                zf.write(p, arcname=str(rel))
            except Exception:
                continue  # 개별 파일 오류는 무시하고 계속 진행
