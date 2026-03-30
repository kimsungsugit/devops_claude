"""Auto-generated router: config"""
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import FileResponse, HTMLResponse
from typing import Any, Dict, List, Optional
import json
import traceback
import logging
from pathlib import Path
from backend.helpers import _default_base_report_dir
import config


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

