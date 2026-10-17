"""Auto-generated router: config"""
import json
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, File, HTTPException, UploadFile

import config
from backend.helpers import _default_base_report_dir

router = APIRouter()
_logger = logging.getLogger("devops_api")

@router.get("/api/config/defaults")
def default_config() -> Dict[str, Any]:
    return {
        "project_root": str(Path.cwd()),
        "report_dir": _default_base_report_dir(),
        "targets_glob": getattr(config, "DEFAULT_TARGETS_GLOB", "libs/*.c"),
        "include_paths": getattr(config, "DEFAULT_INCLUDE_PATHS", []),
        "git_incremental": bool(getattr(config, "DEFAULT_GIT_INCREMENTAL", False)),
        "git_base_ref": getattr(config, "DEFAULT_GIT_BASE_REF", "main"),
        "scm_mode": getattr(config, "DEFAULT_SCM_MODE", "auto"),
        "svn_base_ref": getattr(config, "DEFAULT_SVN_BASE_REF", "BASE"),
        "quality_preset": getattr(config, "QUALITY_PRESET_DEFAULT", "high"),
        "do_build": True,
        "build_strategy": getattr(config, "BUILD_STRATEGY_DEFAULT", "auto"),
        "build_fallback": getattr(config, "BUILD_FALLBACK_DEFAULT", "static"),
        "do_asan": False,
        "do_coverage": True,
        "do_fuzz": False,
        "do_qemu": False,
        "do_docs": False,
        "do_clang_tidy": False,
        "enable_semgrep": False,
        "semgrep_config": "p/default",
        "coverage_warn_pct": getattr(config, "DEFAULT_COVERAGE_WARN_PCT", 80),
        "coverage_fail_pct": getattr(config, "DEFAULT_COVERAGE_FAIL_PCT", 50),
        "tests_min_count": getattr(config, "DEFAULT_TESTS_MIN_COUNT", 1),
        "require_tests_enabled": bool(getattr(config, "DEFAULT_REQUIRE_TESTS_ENABLED", True)),
        "test_gen_timeout_sec": int(getattr(config, "DEFAULT_TEST_GEN_TIMEOUT_SEC", 300)),
        "enable_agent": False,
        "enable_test_gen": True,
        "auto_run_tests": bool(getattr(config, "AUTO_RUN_TESTS", True)),
        "auto_fix_on_fail": bool(getattr(config, "AUTO_FIX_ON_FAIL", False)),
        "auto_fix_on_fail_stages": getattr(config, "AUTO_FIX_ON_FAIL_STAGES", ["build", "tests", "syntax"]),
        "agent_roles": getattr(config, "AGENT_ROLES_DEFAULT", ["planner", "generator", "fixer", "reviewer"]),
        "agent_run_mode": getattr(config, "AGENT_RUN_MODE_DEFAULT", "auto"),
        "agent_review": bool(getattr(config, "AGENT_REVIEW_ENABLED_DEFAULT", True)),
        "agent_rag": bool(getattr(config, "AGENT_RAG_ENABLED_DEFAULT", True)),
        "agent_rag_top_k": int(getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3)),
        "uds_rag_top_k": int(getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3)),
        "uds_rag_categories": ["uds", "requirements", "code", "vectorcast"],
        "agent_max_steps": int(getattr(config, "AGENT_MAX_STEPS_DEFAULT", 3)),
        "auto_fix_scope": getattr(config, "AUTO_FIX_SCOPE_DEFAULT", ["static", "syntax", "build", "tests"]),
        "enable_domain_tests": False,
        "domain_tests_auto": bool(getattr(config, "DOMAIN_TESTS_AUTO", True)),
        "domain_targets": [],
        "rag_ingest_enable": bool(getattr(config, "RAG_INGEST_ENABLE", True)),
        "rag_ingest_on_pipeline": bool(getattr(config, "RAG_INGEST_ON_PIPELINE", True)),
        "rag_ingest_max_files": int(getattr(config, "RAG_INGEST_MAX_FILES", 200)),
        "rag_ingest_max_chunks": int(getattr(config, "RAG_INGEST_MAX_CHUNKS_PER_FILE", 12)),
        "rag_chunk_size": int(getattr(config, "RAG_CHUNK_SIZE", 1200)),
        "rag_chunk_overlap": int(getattr(config, "RAG_CHUNK_OVERLAP", 200)),
        "rag_stage_enable": getattr(config, "RAG_STAGE_ENABLE", {}),
        "rag_stage_top_k": getattr(config, "RAG_STAGE_TOP_K", {}),
        "rag_stage_prompts": getattr(config, "RAG_STAGE_PROMPTS", {}),
        "rag_query_templates": getattr(config, "RAG_QUERY_TEMPLATES", {}),
        "vc_reports_paths": [],
        "uds_spec_paths": [],
        "req_docs_paths": [],
        "codebase_paths": [],
        "kb_storage": getattr(config, "KB_STORAGE", "sqlite"),
        "pgvector_dsn": getattr(config, "PGVECTOR_DSN", ""),
        "pgvector_url": getattr(config, "PGVECTOR_URL", ""),
        "oai_config_path": getattr(config, "DEFAULT_OAI_CONFIG_PATH", "oai_config.json"),
        "llm_model": getattr(config, "DEFAULT_LLM_MODEL", ""),
        "call_tree_external_map": getattr(config, "CALL_TREE_EXTERNAL_MAP", []),
        "call_tree_html_template": getattr(config, "CALL_TREE_HTML_TEMPLATE", ""),
    }


@router.get("/api/config/options")
def config_options() -> Dict[str, Any]:
    return {
        "quality_presets": getattr(config, "QUALITY_PRESET_OPTIONS", ["high", "balanced", "fast", "custom"]),
        "quality_presets_map": getattr(config, "QUALITY_PRESETS", {}),
        "cppcheck_levels": ["warning", "performance", "portability", "style", "information"],
        "auto_fix_scope_options": getattr(config, "AUTO_FIX_SCOPE_OPTIONS", ["static", "syntax", "build", "tests"]),
        "agent_run_modes": getattr(config, "AGENT_RUN_MODES", ["auto", "review", "off"]),
        "agent_patch_modes": getattr(config, "AGENT_PATCH_MODES", ["auto", "review", "off"]),
        "mcu_presets": getattr(config, "MCU_PRESETS", {}),
        "toolchain_profiles": getattr(config, "TOOLCHAIN_PROFILES", {}),
        "source_priority_options": ["artifact", "server", "local"],
        "artifact_success_rules": ["jenkins_api", "artifact_marker", "either"],
        "build_strategy_options": getattr(config, "BUILD_STRATEGY_OPTIONS", ["auto", "manual"]),
        "build_fallback_options": getattr(config, "BUILD_FALLBACK_OPTIONS", ["jenkins", "static"]),
    }


# ──────────────────────────────────────────────────────────────────
# Jenkins server-side config (shared across all users)
# ──────────────────────────────────────────────────────────────────

_JENKINS_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "jenkins_server_config.json"
_ADMINS_PATH = Path(__file__).resolve().parents[2] / "config" / "admins.json"


def _load_admins() -> set:
    """Load admin user list from config/admins.json. Empty file / missing = no admin restriction relaxed."""
    if not _ADMINS_PATH.exists():
        return set()  # no admins defined → will deny all writes unless file exists with users
    try:
        data = json.loads(_ADMINS_PATH.read_text(encoding="utf-8"))
        return set(data) if isinstance(data, list) else set()
    except Exception:
        return set()


def _require_admin(request_user: str) -> None:
    """Raise 403 if the caller is not an admin. Bootstrapping rule:
    if admins.json is missing, any authenticated user can save (first-time setup)."""
    if not _ADMINS_PATH.exists():
        return  # bootstrap mode — no admins configured yet
    admins = _load_admins()
    if request_user not in admins:
        raise HTTPException(status_code=403, detail="admin role required to modify server config")


@router.get("/api/config/jenkins")
def get_jenkins_config() -> Dict[str, Any]:
    """Return server-managed Jenkins connection config. All users get the same values."""
    if not _JENKINS_CONFIG_PATH.exists():
        return {
            "baseUrl": "",
            "username": "",
            "token": "",
            "cacheRoot": ".devops_pro_cache",
            "buildSelector": "lastSuccessfulBuild",
            "verifyTls": True,
        }
    try:
        data = json.loads(_JENKINS_CONFIG_PATH.read_text(encoding="utf-8"))
        # Strip internal comment fields
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception as exc:
        _logger.warning("Failed to read jenkins_server_config.json: %s", exc)
        raise HTTPException(status_code=500, detail="server config read failed")


@router.post("/api/config/jenkins")
def save_jenkins_config(req: Dict[str, Any]) -> Dict[str, Any]:
    """Save server-managed Jenkins config. Admin-only. Persistent across restarts.

    Admin role is enforced via `config/admins.json` (list of usernames).
    If the file is missing, bootstrap mode allows any authenticated user
    so the first admin can be designated.

    Previous config is backed up to `jenkins_server_config.json.bak` before
    each write for recovery from accidental overwrites.
    """
    import datetime

    from backend.user_context import get_current_user
    current_user = get_current_user()
    _require_admin(current_user)

    allowed_keys = {"baseUrl", "username", "token", "cacheRoot", "buildSelector", "verifyTls"}
    payload = {k: req[k] for k in allowed_keys if k in req}
    payload["_comment"] = "Managed server-side config — persistent across restarts."
    payload["_last_saved_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    payload["_last_saved_by"] = current_user

    _JENKINS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Backup previous config (for recovery from accidental overwrites)
    if _JENKINS_CONFIG_PATH.exists():
        try:
            backup_path = _JENKINS_CONFIG_PATH.with_suffix(".json.bak")
            backup_path.write_text(_JENKINS_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception as exc:
            _logger.warning("Jenkins config backup failed: %s", exc)

    _JENKINS_CONFIG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _logger.info("[admin:%s] Jenkins server config saved (%d keys)", current_user, len(payload))
    return {"ok": True, "saved_keys": list(payload.keys()), "saved_at": payload["_last_saved_at"]}


# ──────────────────────────────────────────────────────────────────
# UDS docx template — server-managed default (shared across all users)
# ──────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
# Path kept in sync with config.UDS_TEMPLATE_SERVER_CONFIG_PATH so the
# GET/POST handlers below and config.resolve_uds_template_path() agree.
_UDS_TEMPLATE_CONFIG_PATH = getattr(
    config, "UDS_TEMPLATE_SERVER_CONFIG_PATH",
    _REPO_ROOT / "config" / "uds_template_server_config.json",
)
_UDS_TEMPLATE_UPLOAD_DIR = _REPO_ROOT / "docs" / "uds_templates"


def _read_uds_template_config() -> Dict[str, Any]:
    if not _UDS_TEMPLATE_CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(_UDS_TEMPLATE_CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        _logger.warning("Failed to read uds_template_server_config.json: %s", exc)
        return {}


@router.get("/api/config/uds-template")
def get_uds_template_config() -> Dict[str, Any]:
    """Return the server-side UDS docx template settings.

    ``template_path``  — admin-saved absolute path (empty if unset).
    ``effective_path`` — path actually used by UDS generation at this moment
                         (falls back to env UDS_TEMPLATE_PATH when unset).
    ``exists``         — whether ``effective_path`` resolves to a real file.
    """
    cfg = _read_uds_template_config()
    saved = str(cfg.get("template_path") or "")
    effective = config.resolve_uds_template_path()
    return {
        "template_path": saved,
        "effective_path": effective,
        "exists": bool(effective) and Path(effective).exists(),
        "default_path": getattr(config, "UDS_TEMPLATE_PATH", ""),
        "last_saved_at": cfg.get("_last_saved_at", ""),
        "last_saved_by": cfg.get("_last_saved_by", ""),
    }


@router.post("/api/config/uds-template")
def save_uds_template_config(req: Dict[str, Any]) -> Dict[str, Any]:
    """Persist the admin-selected UDS template path. Admin-only.

    Body: ``{"template_path": "...absolute or repo-relative path..."}``.
    An empty path clears the override (generation falls back to env default).
    """
    import datetime

    from backend.user_context import get_current_user
    current_user = get_current_user()
    _require_admin(current_user)

    raw = str(req.get("template_path") or "").strip()
    # Allow clearing the override
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = (_REPO_ROOT / raw).resolve()
        else:
            p = p.resolve()
        # Prevent pointing at files outside the repository tree (path traversal).
        try:
            p.relative_to(_REPO_ROOT)
        except ValueError:
            raise HTTPException(status_code=400, detail="template path must be inside the repository")
        if not p.exists() or not p.is_file():
            raise HTTPException(status_code=400, detail=f"template file not found: {p}")
        if p.suffix.lower() != ".docx":
            raise HTTPException(status_code=400, detail="template must be a .docx file")
        raw = str(p)

    payload = {
        "template_path": raw,
        "_comment": "Server-managed UDS docx template — takes precedence over UDS_TEMPLATE_PATH env.",
        "_last_saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "_last_saved_by": current_user,
    }
    _UDS_TEMPLATE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _UDS_TEMPLATE_CONFIG_PATH.exists():
        try:
            backup = _UDS_TEMPLATE_CONFIG_PATH.with_suffix(".json.bak")
            backup.write_text(_UDS_TEMPLATE_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception as exc:
            _logger.warning("UDS template config backup failed: %s", exc)
    _UDS_TEMPLATE_CONFIG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _logger.info("[admin:%s] UDS template config saved: %s", current_user, raw or "(cleared)")
    return {
        "ok": True,
        "template_path": raw,
        "effective_path": config.resolve_uds_template_path(),
        "saved_at": payload["_last_saved_at"],
    }


@router.post("/api/config/uds-template/upload")
async def upload_uds_template(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Upload a docx file to the server and set it as the active UDS template. Admin-only.

    Stored under ``docs/uds_templates/<original-filename>``; overwrites existing file.
    """
    import datetime

    from backend.user_context import get_current_user
    current_user = get_current_user()
    _require_admin(current_user)

    name = (file.filename or "").strip()
    if not name.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="only .docx files are accepted")
    # Strip unsafe path components; reject names that leave nothing meaningful.
    safe_name = Path(name).name
    stem = safe_name[:-5]  # strip ".docx"
    if not stem or stem.startswith("."):
        raise HTTPException(status_code=400, detail="invalid filename")
    _UDS_TEMPLATE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = _UDS_TEMPLATE_UPLOAD_DIR / safe_name

    # Enforce an upload size limit (50 MB). Streams the body in chunks so
    # a malicious large file can't exhaust memory before detection.
    MAX_BYTES = 50 * 1024 * 1024
    written = 0
    with dest.open("wb") as fh:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_BYTES:
                fh.close()
                try:
                    dest.unlink()
                except Exception:
                    pass
                raise HTTPException(status_code=413, detail=f"file too large (>{MAX_BYTES // (1024 * 1024)} MB)")
            fh.write(chunk)

    # Update the pointer config to this upload
    payload = {
        "template_path": str(dest),
        "_comment": "Server-managed UDS docx template — uploaded via admin UI.",
        "_last_saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "_last_saved_by": current_user,
    }
    _UDS_TEMPLATE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _UDS_TEMPLATE_CONFIG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _logger.info("[admin:%s] UDS template uploaded: %s (%d bytes)", current_user, dest.name, dest.stat().st_size)
    return {
        "ok": True,
        "template_path": str(dest),
        "effective_path": config.resolve_uds_template_path(),
        "size": dest.stat().st_size,
        "saved_at": payload["_last_saved_at"],
    }

