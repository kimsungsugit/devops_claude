# /app/config.py
# -*- coding: utf-8 -*-
# Central configuration for DevOps analysis toolkit
# v30.8: Optimized for Gemini 3.0 Pro (Max Tokens 65536)

from __future__ import annotations

import os
from pathlib import Path

# ---------------- 기본 경로 / 타깃 설정 ----------------
_REPO_ROOT = Path(__file__).resolve().parent
_LINUX_DEFAULT_PROJECT_ROOT = Path("/app/my_lin_gateway")
if _LINUX_DEFAULT_PROJECT_ROOT.exists():
    DEFAULT_PROJECT_ROOT = str(_LINUX_DEFAULT_PROJECT_ROOT)
else:
    DEFAULT_PROJECT_ROOT = os.environ.get("DEVOPS_PROJECT_ROOT", str(_REPO_ROOT))
DEFAULT_REPORT_DIR = "reports"
DEFAULT_TARGETS_GLOB = "libs/*.c"
DEFAULT_TARGET_ARCH = "cortex-m0plus"
DEFAULT_GIT_INCREMENTAL = False
DEFAULT_GIT_BASE_REF = "main"
DEFAULT_SCM_MODE = "auto"
DEFAULT_SVN_BASE_REF = "BASE"

# include 검색 기본 경로
DEFAULT_INCLUDE_PATHS = [
    "libs",
    "include",
    "tests",
]

# PRQA 경로 매핑 규칙
# 예: {"from": "C:/ProgramData/Jenkins/.jenkins/workspace/{job}/source", "to": "D:/Project/devops/260105/PDS_64/source"}
# {job} 또는 <job> 토큰을 job_slug로 치환합니다.
PRQA_PATH_MAPPINGS = []

# Jenkins 경로 매핑 규칙
# 예: {"from": "C:/ProgramData/Jenkins/.jenkins/workspace/{job}/source", "to": "D:/Project/devops/260105/PDS_64/source"}
# {job} 또는 <job> 토큰을 job_slug로 치환합니다.
JENKINS_PATH_MAPPINGS = []

# ---------------- 정적 분석 설정 ----------------
DEFAULT_CPPCHECK_ENABLE = [
    "warning",
    "performance",
    "portability",
]

# ---------------- 품질 프리셋 / 엔진 세트 ----------------
# - high: 최대 품질 (clang-tidy + cppcheck + semgrep)
# - balanced: 균형 (clang-tidy + cppcheck)
# - fast: 빠른 분석 (cppcheck 위주)
# - custom: UI에서 개별 설정 사용
QUALITY_PRESETS = {
    "high": {"clang_tidy": True, "semgrep": True, "semgrep_config": "p/ci"},
    "balanced": {"clang_tidy": True, "semgrep": False, "semgrep_config": "p/default"},
    "fast": {"clang_tidy": False, "semgrep": False, "semgrep_config": "p/default"},
    "custom": {"clang_tidy": False, "semgrep": False, "semgrep_config": "p/default"},
}
QUALITY_PRESET_OPTIONS = ["high", "balanced", "fast", "custom"]
QUALITY_PRESET_DEFAULT = "high"

# ---------------- 빌드 전략 ----------------
# - auto: 로컬 빌드 환경 감지 후 자동 결정
# - manual: 사용자가 선택한 do_build 값을 사용
BUILD_STRATEGY_OPTIONS = ["auto", "manual"]
BUILD_STRATEGY_DEFAULT = "auto"
BUILD_FALLBACK_OPTIONS = ["jenkins", "static"]
BUILD_FALLBACK_DEFAULT = "static"

# ---------------- 자동 수정 범위 ----------------
# 선택 가능한 범위: static, syntax, build, tests
AUTO_FIX_SCOPE_OPTIONS = ["static", "syntax", "build", "tests"]
AUTO_FIX_SCOPE_DEFAULT = ["static", "syntax", "build", "tests"]

DEFAULT_COMPLEXITY_THRESHOLD = 15

# ---------------- Call Tree / 외부 함수 매핑 ----------------
# 외부 함수 매핑 (프로젝트 설정에서 override 가능)
# 형식: [{"name": "printf", "header": "stdio.h", "library": "stdio"}] 또는 {"names": [...], "header": "...", "library": "..."}
CALL_TREE_EXTERNAL_MAP = []
# 콜 트리 HTML 템플릿 ({{tree}} 또는 {{content}} 치환)
CALL_TREE_HTML_TEMPLATE = ""

# ---------------- Jenkins 스캔/리포트 성능 ----------------
# 리포트 파일 목록 캐시 TTL(초)
REPORT_FILES_CACHE_TTL = 120.0
# Jenkins 스캔 캐시 TTL(초)
JENKINS_SCAN_CACHE_TTL_SEC = 300
# Jenkins 스캔 파일 상한 (초과 시 중단)
JENKINS_SCAN_MAX_FILES = 6000
# Jenkins 스캔 시 양보 주기/슬립(ms)
JENKINS_SCAN_YIELD_EVERY = 200
JENKINS_SCAN_YIELD_SLEEP_MS = 5
# Jenkins 스캔 대상 경로 모드: auto | report_only | build_root
JENKINS_SCAN_ROOT_MODE = "auto"

# Jenkins 서버 루트 탐색 허용 경로(로컬 백엔드 기준)
# 기본값: Windows Jenkins 기본 루트
_JENKINS_SERVER_ROOTS_RAW = os.environ.get("DEVOPS_JENKINS_SERVER_ROOTS", "C:/ProgramData/Jenkins/.jenkins")
JENKINS_SERVER_ROOTS = [p.strip() for p in _JENKINS_SERVER_ROOTS_RAW.replace(";", ",").split(",") if p.strip()]

# Jenkins 서버 탐색 시 기본 문서 확장자
JENKINS_SERVER_DOC_EXTS = [
    "html",
    "htm",
    "xlsx",
    "xls",
    "xlsm",
    "xml",
    "json",
    "txt",
    "md",
    "rst",
    "pdf",
    "doc",
    "docx",
    "csv",
    "log",
]

# ---------------- UDS / Source Parsing 성능 설정 ----------------
UDS_MAX_SOURCE_FILES = int(os.environ.get("DEVOPS_UDS_MAX_FILES", "1200"))
UDS_MAX_FUNCTION_ITEMS = int(os.environ.get("DEVOPS_UDS_MAX_ITEMS", "120"))

# ---------------- VectorCAST TResultParser ----------------
VCAST_TEST_ROWS_MAX_ROWS = 5000
VCAST_TEST_ROWS_MAX_TABLES = 6
VCAST_FAILURES_TOP_N = 50

# ---------------- UDS 품질 게이트 임계값 ----------------
UDS_QUALITY_GATE_THRESHOLDS = {
    "called_min": float(os.environ.get("UDS_CALLED_MIN", "95.0")),
    "calling_min": float(os.environ.get("UDS_CALLING_MIN", "95.0")),
    "input_min": float(os.environ.get("UDS_INPUT_MIN", "90.0")),
    "output_min": float(os.environ.get("UDS_OUTPUT_MIN", "90.0")),
    "global_min": float(os.environ.get("UDS_GLOBAL_MIN", "40.0")),
    "static_min": float(os.environ.get("UDS_STATIC_MIN", "20.0")),
    "description_min": float(os.environ.get("UDS_DESCRIPTION_MIN", "90.0")),
    "asil_min": float(os.environ.get("UDS_ASIL_MIN", "50.0")),
    "related_min": float(os.environ.get("UDS_RELATED_MIN", "70.0")),
    "description_trusted_min": float(os.environ.get("UDS_DESC_TRUSTED_MIN", "60.0")),
    "asil_trusted_min": float(os.environ.get("UDS_ASIL_TRUSTED_MIN", "40.0")),
    "related_trusted_min": float(os.environ.get("UDS_RELATED_TRUSTED_MIN", "50.0")),
}

UDS_QUALITY_WARNING_THRESHOLDS = {
    "called_warn": 85.0,
    "calling_warn": 85.0,
    "input_warn": 60.0,
    "output_warn": 60.0,
    "global_warn": 30.0,
    "static_warn": 10.0,
    "description_warn": 80.0,
    "asil_warn": 30.0,
    "related_warn": 50.0,
    "description_trusted_warn": 45.0,
    "asil_trusted_warn": 25.0,
    "related_trusted_warn": 35.0,
}

# ---------------- UDS DOCX retry 타임아웃 (초) ----------------
UDS_DOCX_RETRY_STAGES = [
    ("full", 0, int(os.environ.get("UDS_DOCX_FULL_TIMEOUT", "2400"))),
    ("degraded_ai_off", 1, int(os.environ.get("UDS_DOCX_DEGRADED_TIMEOUT", "1800"))),
    ("degraded_light", 2, int(os.environ.get("UDS_DOCX_LIGHT_TIMEOUT", "900"))),
]

UDS_REPORT_TIMEOUT = int(os.environ.get("UDS_REPORT_TIMEOUT", "120"))
UDS_ACCURACY_REPORT_TIMEOUT = int(os.environ.get("UDS_ACCURACY_TIMEOUT", "300"))

# Source sections cache TTL (seconds)
UDS_SOURCE_SECTIONS_CACHE_TTL = int(os.environ.get("UDS_SOURCE_CACHE_TTL", "1800"))

# ---------------- 커버리지/테스트 임계치 설정 ----------------
DEFAULT_COVERAGE_THRESHOLD = 0.60
COVERAGE_THRESHOLD = DEFAULT_COVERAGE_THRESHOLD
DEFAULT_COVERAGE_WARN_PCT = 80
DEFAULT_COVERAGE_FAIL_PCT = 50
DEFAULT_TESTS_MIN_COUNT = 1
DEFAULT_REQUIRE_TESTS_ENABLED = True
DEFAULT_TEST_GEN_TIMEOUT_SEC = int(os.environ.get("TEST_GEN_TIMEOUT_SEC", "300"))
PLAN_GEN_RETRY = 5
PLAN_REPAIR_RETRY = 5
PLAN_MAX_FUNCTIONS = 8
PLAN_MAX_CASES_PER_FUNC = 6
TEST_PROMPT_MAX_CASES = 12
TEST_CODE_MAX_LINES = 300
TEST_CODE_MAX_TOKENS = 16384

# ---------------- LLM / 에이전트 설정 ----------------
# [TIP] 70b 모델이 너무 느리면 "llama3:8b" 또는 "phi3" 등으로 변경 고려
# 기본 모델을 제미나이로 변경하고 싶으면 아래를 수정하세요.
DEFAULT_LLM_MODEL = "gemini-2.5-flash"
DEFAULT_LLM_BASE_URL_ENV = "OLLAMA_BASE_URL"
_DEFAULT_OAI_CONFIG = _REPO_ROOT / "OAI_CONFIG_LIST"
if _DEFAULT_OAI_CONFIG.exists():
    DEFAULT_OAI_CONFIG_PATH = str(_DEFAULT_OAI_CONFIG)
else:
    DEFAULT_OAI_CONFIG_PATH = os.environ.get("DEVOPS_OAI_CONFIG_PATH", "/app/OAI_CONFIG_LIST")


def resolve_oai_api_keys(config_list: list) -> list:
    """Resolve 'ENV:VAR_NAME' placeholders in api_key fields to actual env values."""
    import json as _json
    resolved = []
    for entry in config_list:
        entry = dict(entry)
        key_val = entry.get("api_key", "")
        if isinstance(key_val, str) and key_val.startswith("ENV:"):
            env_name = key_val[4:]
            entry["api_key"] = os.environ.get(env_name, "")
        resolved.append(entry)
    return resolved


def load_oai_config_list(path: str = "") -> list:
    """Load OAI_CONFIG_LIST JSON and resolve ENV: placeholders in api_key."""
    import json as _json
    cfg_path = path or DEFAULT_OAI_CONFIG_PATH
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            raw = _json.load(f)
    except Exception:
        return []
    return resolve_oai_api_keys(raw if isinstance(raw, list) else [])
DEFAULT_LLM_TEMPERATURE = 0.3
DEFAULT_LLM_TEMPERATURE_GEMINI = 1.0
LLM_TOKEN_ESTIMATE_MARGIN_DEFAULT = 1.1
LLM_TOKEN_ESTIMATE_MARGIN_GEMINI = 1.25
LLM_WARN_INPUT_TOKENS = 200000

# Model-specific policies (auto caps, temperature, margins)
# Keys are matched by substring (case-insensitive) against model name.
LLM_MODEL_POLICIES = {
    "gemini-3": {
        "max_input_tokens": 1000000,
        "max_output_tokens": 65536,
        "max_input_tokens_by_stage": {
            "build_fix": 200000,
            "syntax_fix": 200000,
            "static": 200000,
            "domain_tests": 200000,
            "plan_repair": 200000,
            "test_plan": 200000,
            "test_code": 200000,
        },
        "token_estimate_margin": 1.25,
        "warn_input_tokens": 200000,
        "temperature_default": 1.0,
    },
    "gemini-2.0": {
        "max_input_tokens": 200000,
        "max_output_tokens": 8192,
        "max_input_tokens_by_stage": {
            "build_fix": 100000,
            "syntax_fix": 100000,
            "static": 100000,
            "domain_tests": 100000,
            "plan_repair": 100000,
            "test_plan": 100000,
            "test_code": 100000,
        },
        "token_estimate_margin": 1.2,
        "warn_input_tokens": 150000,
        "temperature_default": 0.7,
    },
    "gemini-2.5": {
        "max_input_tokens": 200000,
        "max_output_tokens": 8192,
        "max_input_tokens_by_stage": {
            "build_fix": 100000,
            "syntax_fix": 100000,
            "static": 100000,
            "domain_tests": 100000,
            "plan_repair": 100000,
            "test_plan": 100000,
            "test_code": 100000,
        },
        "token_estimate_margin": 1.2,
        "warn_input_tokens": 150000,
        "temperature_default": 0.7,
    },
}

# Jenkins Viewer: function change AI summary (applies only when changes exist)
JENKINS_FUNCTION_AI_SUMMARY_DEFAULT = True

# [MODIFIED] 런타임 환경변수는 사용자 값을 우선, 없으면 기본값 주입
DEFAULT_LLM_READ_TIMEOUT = 300  # seconds
def apply_runtime_env() -> None:
    """기본 환경변수 주입, 사용자가 설정한 값은 유지"""
    os.environ.setdefault("LLM_READ_TIMEOUT", str(DEFAULT_LLM_READ_TIMEOUT))
    os.environ.setdefault("LLM_MAX_INPUT_TOKENS", str(DEFAULT_LLM_MAX_INPUT_TOKENS))
    os.environ.setdefault("TEST_GEN_TIMEOUT_SEC", "60")

# Gemini-only 강제 사용(요청: gemini3만 사용)
# - OAI_CONFIG_LIST가 여러 모델을 포함해도, workflow는 Gemini만 선택
LLM_GEMINI_ONLY = os.environ.get("LLM_GEMINI_ONLY", "1").strip().lower() in ("1", "true", "yes")
LLM_GEMINI_PREFERRED_SUBSTRING = os.environ.get("LLM_GEMINI_PREFERRED_SUBSTRING", "gemini-2.5").strip().lower()

# [MODIFIED] 기본 출력 토큰 수 최대치로 상향 (65536)
# Gemini 3 Pro Preview 스펙에 맞춤
DEFAULT_LLM_NUM_PREDICT = 8192
DEFAULT_LLM_RETRIES = 10
DEFAULT_LLM_MAX_INPUT_TOKENS = 1000000
MAX_FINDINGS_FOR_PROMPT = 5

# 단계별 입력 토큰 상한 (비용/안정성 관리용)
# - 스테이지 값이 존재하면 해당 상한을 우선 적용
# - 없으면 DEFAULT_LLM_MAX_INPUT_TOKENS 사용
LLM_MAX_INPUT_TOKENS_BY_STAGE = {
    "build_fix": 200000,
    "syntax_fix": 200000,
    "static": 200000,
    "domain_tests": 200000,
    "plan_repair": 200000,
    "test_plan": 200000,
    "test_code": 200000,
}

# ---------------- Fuzz / QEMU 기본값 ----------------
FUZZ_DEFAULT_DURATION = 10
FUZZ_FOCUS_DURATION = 30
QEMU_LOG_ERROR_PATTERNS = [
    "HardFault",
    "UsageFault",
    "MemManage",
    "BusFault",
    "ASSERT",
    "panic",
    "Segmentation fault"
]

# ---------------- Agent Patch Mode ----------------
AGENT_PATCH_MODES = ["auto", "review", "off"]
AGENT_PATCH_MODE_DEFAULT = "auto"

# 자동 AI 복구(빌드/테스트/문법/정적 실패 시)
AUTO_FIX_ON_FAIL = True
AUTO_FIX_SCOPE_ON_FAIL = ["build", "tests", "syntax", "static"]
AUTO_FIX_PATCH_MODE = "auto"
AUTO_FIX_RUN_MODE = "auto"
AUTO_FIX_ON_FAIL_STAGES = ["build", "tests", "syntax", "static"]

# ---------------- Agent Roles / Loop ----------------
AGENT_ROLES_DEFAULT = ["planner", "generator", "fixer", "reviewer"]
AGENT_MAX_STEPS_DEFAULT = 3
AGENT_REVIEW_ENABLED_DEFAULT = True
AGENT_RAG_ENABLED_DEFAULT = True
AGENT_RAG_TOP_K_DEFAULT = 3
AGENT_RUN_MODES = ["auto", "review", "off"]
AGENT_RUN_MODE_DEFAULT = "auto"

# RAG 저장소 디렉터리 이름
KB_DIR_NAME = "kb_store"
FORCE_PGVECTOR = str(os.environ.get("FORCE_PGVECTOR", "0")).strip().lower() in (
    "1",
    "true",
    "yes",
)
FORCE_PGVECTOR_STRICT = str(os.environ.get("FORCE_PGVECTOR_STRICT", "1")).strip().lower() in (
    "1",
    "true",
    "yes",
)
_DEFAULT_KB_STORAGE = "pgvector" if FORCE_PGVECTOR else "sqlite"
KB_STORAGE = os.environ.get("KB_STORAGE", _DEFAULT_KB_STORAGE).strip().lower()
# Coverage tool auto-install
AUTO_INSTALL_GCOVR = str(os.environ.get("AUTO_INSTALL_GCOVR", "1")).strip().lower() in (
    "1",
    "true",
    "yes",
)
# 전역 KB를 사용하려면 경로 지정 (예: C:/Users/.../.devops_kb)
KB_GLOBAL_DIR = os.environ.get("KB_GLOBAL_DIR", "").strip()
KB_SOURCES_DIR = os.environ.get("KB_SOURCES_DIR", "").strip()
PGVECTOR_DSN = os.environ.get("PGVECTOR_DSN", "").strip()
PGVECTOR_URL = os.environ.get("PGVECTOR_URL", "").strip()
KB_CATEGORIES = [
    "general",
    "build",
    "syntax",
    "static",
    "structure",
    "dynamic_tests",
    "performance",
    "safety",
    "uds_description",
    "uds_globals",
    "uds_requirements",
]
RAG_CATEGORY_BY_STAGE = {
    "build_fix": "build",
    "syntax_fix": "syntax",
    "static": "static",
    "unit_tests": "dynamic_tests",
    "test_plan": ["uds", "requirements", "vectorcast", "code"],
    "test_code": ["requirements", "vectorcast", "code"],
    "chat": "general",
    "chat_summary": "general",
    "uds_description": ["uds_description", "uds_requirements", "code"],
    "uds_globals": ["uds_globals", "code"],
    "func_desc": ["uds_description", "code", "requirements"],
}

# ---------------- Chat tuning ----------------
CHAT_MAX_TURNS = 16
CHAT_LOG_LINES = 40
CHAT_SUMMARY_MAX_CHARS = 1600
CHAT_ENABLE_SUMMARY = True
CHAT_LONG_QUERY_CHARS = 800
CHAT_MODEL_FAST = "gemini-2.0-flash"
CHAT_SUMMARY_KEEP_DAYS = 7
CHAT_SUMMARY_LOAD_FROM_FILE = True
CHAT_SUMMARY_FILE_MAX_CHARS = 1200

# ---------------- RAG ingestion (VectorCAST/UDS/Requirements/Code) ----------------
RAG_INGEST_ENABLE = True
RAG_INGEST_ON_PIPELINE = True

VC_REPORTS_PATHS = os.environ.get("VC_REPORTS_PATHS", "").strip()
UDS_SPEC_PATHS = os.environ.get("UDS_SPEC_PATHS", "").strip()
REQ_DOCS_PATHS = os.environ.get("REQ_DOCS_PATHS", "").strip()
CODEBASE_PATHS = os.environ.get("CODEBASE_PATHS", "").strip()

RAG_INGEST_MAX_FILES = 200
RAG_INGEST_MAX_CHUNKS_PER_FILE = 12
RAG_CHUNK_SIZE = 1200
RAG_CHUNK_OVERLAP = 200

RAG_CHUNK_STRATEGIES = {
    "code": {"size": 800, "overlap": 100},
    "requirements": {"size": 1500, "overlap": 300},
    "docx": {"size": 2000, "overlap": 400},
    "default": {"size": RAG_CHUNK_SIZE, "overlap": RAG_CHUNK_OVERLAP},
}

# ---------------- UDS Generation Constants ----------------
UDS_MAX_SOURCE_FILES = 1200
UDS_MAX_ITEMS_PER_CATEGORY = 120
UDS_TRIM_MAX_CHARS = 24000
UDS_STYLE_EXCERPT_MAX_CHARS = 12000
UDS_FRONT_MATTER_LINES = 120
UDS_CONTENTS_LINES = 220
UDS_PARALLEL_SECTIONS = False

STATIC_VAR_PREFIXES = ("u8s_", "u16s_", "u32s_", "s8s_", "s16s_", "s32s_", "s_")
GLOBAL_VAR_PREFIXES = ("u8g_", "u16g_", "u32g_", "s8g_", "s16g_", "s32g_", "g_")

UDS_REF_SUDS_PATH = os.environ.get(
    "UDS_REF_SUDS_PATH",
    str(Path(__file__).resolve().parent / "docs" / "(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx"),
)

CODE_RAG_GLOBS = [
    "**/*.c",
    "**/*.h",
    "**/*.cpp",
    "**/*.hpp",
]

AUTO_RUN_TESTS = True
REQUIRE_REQUIREMENT_ID = True
REQUIRE_REQUIREMENT_ID_FIELD = "requirement_id"
TEST_STABILITY_GATE = True
DOMAIN_TESTS_AUTO = True
DOMAIN_TESTS_KEYWORDS = ["e2e", "gateway", "protocol", "lin"]
DOMAIN_TESTS_EXTS = [".c", ".h", ".cpp", ".hpp"]
# ---------------- 외부 도구 탐색 경로 (Windows) ----------------
_TOOL_SEARCH_PATHS_RAW = os.environ.get(
    "DEVOPS_TOOL_SEARCH_PATHS",
    r"C:\Program Files\LLVM\bin;C:\Program Files\Cppcheck;C:\msys64\mingw64\bin",
)
TOOL_SEARCH_PATHS = [p.strip() for p in _TOOL_SEARCH_PATHS_RAW.replace(";", ",").split(",") if p.strip()]

# ---------------- Health Check ----------------
REQUIRED_TOOLS = {
    "gcc": ["--version"],
    "cmake": ["--version"],
    "gcovr": ["--version"],
    "cppcheck": ["--version"],
    "qemu-system-arm": ["--version"],
}
if os.name == "nt" and os.environ.get("DEVOPS_RELAX_TOOLCHECK", "1") in ("1", "true", "yes"):
    # Windows 로컬 실행은 Jenkins Viewer 중심일 수 있어 기본 체크 완화
    REQUIRED_TOOLS = {}

# ---------------- 버전 정보 ----------------
ENGINE_NAME = "Embedded DevOps Analyzer"
ENGINE_VERSION = "30.8"

# ---------------- Jenkins Viewer 설정 ----------------
JENKINS_BASE_URL = os.environ.get("DEVOPS_JENKINS_BASE_URL", "http://<jenkins-host>:<port>")
JENKINS_USERNAME = os.environ.get("DEVOPS_JENKINS_USERNAME", "<fixed-username>")
JENKINS_API_TOKEN = os.environ.get("DEVOPS_JENKINS_API_TOKEN", "<fixed-api-token>")
JENKINS_HIDE_CREDENTIALS = os.environ.get("DEVOPS_JENKINS_HIDE_CREDENTIALS", "1") == "1"
JENKINS_VERIFY_TLS = os.environ.get("DEVOPS_JENKINS_VERIFY_TLS", "1") == "1"

# Jenkins Viewer runtime log scan limit (summary heuristics)
JENKINS_RUNTIME_LOG_SCAN_LIMIT = int(os.environ.get("DEVOPS_JENKINS_LOG_SCAN_LIMIT", "6") or "6")

# ------------------------------------------------------------
# Rule catalog (MISRA/QAC 등) - Jenkins Viewer에서 Rule 설명 표시용
# ------------------------------------------------------------
# 기본적으로 repo 루트의 rules/ 아래 *.rcf 를 자동 탐색
RULE_CATALOG_GLOBS = [
    "rules/*.rcf",
    "rules/**/*.rcf",
]

# 파싱된 rule catalog JSON 캐시(선택) - 없으면 .rcf를 즉시 파싱
RULE_CATALOG_JSON = "rules/rule_catalog.json"

# Ensure runtime env defaults are applied on import.
apply_runtime_env()
