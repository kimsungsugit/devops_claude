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

# include 검색 기본 경로
DEFAULT_INCLUDE_PATHS = [
    "libs",
    "include",
    "tests",
]

# ---------------- 정적 분석 설정 ----------------
DEFAULT_CPPCHECK_ENABLE = [
    "warning",
    "performance",
    "portability",
]

DEFAULT_COMPLEXITY_THRESHOLD = 15

# ---------------- 커버리지 설정 ----------------
DEFAULT_COVERAGE_THRESHOLD = 0.60
COVERAGE_THRESHOLD = DEFAULT_COVERAGE_THRESHOLD

# ---------------- LLM / 에이전트 설정 ----------------
# [TIP] 70b 모델이 너무 느리면 "llama3:8b" 또는 "phi3" 등으로 변경 고려
# 기본 모델을 제미나이로 변경하고 싶으면 아래를 수정하세요.
DEFAULT_LLM_MODEL = "gemini-3-pro-preview" 
DEFAULT_LLM_BASE_URL_ENV = "OLLAMA_BASE_URL"
_DEFAULT_OAI_CONFIG = _REPO_ROOT / "OAI_CONFIG_LIST"
if _DEFAULT_OAI_CONFIG.exists():
    DEFAULT_OAI_CONFIG_PATH = str(_DEFAULT_OAI_CONFIG)
else:
    DEFAULT_OAI_CONFIG_PATH = os.environ.get("DEVOPS_OAI_CONFIG_PATH", "/app/OAI_CONFIG_LIST")
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
}

# Jenkins Viewer: function change AI summary (applies only when changes exist)
JENKINS_FUNCTION_AI_SUMMARY_DEFAULT = True

# [MODIFIED] 런타임 환경변수는 사용자 값을 우선, 없으면 기본값 주입
DEFAULT_LLM_READ_TIMEOUT = 1200  # seconds
def apply_runtime_env() -> None:
    """기본 환경변수 주입, 사용자가 설정한 값은 유지"""
    os.environ.setdefault("LLM_READ_TIMEOUT", str(DEFAULT_LLM_READ_TIMEOUT))
    os.environ.setdefault("LLM_MAX_INPUT_TOKENS", str(DEFAULT_LLM_MAX_INPUT_TOKENS))

# Gemini-only 강제 사용(요청: gemini3만 사용)
# - OAI_CONFIG_LIST가 여러 모델을 포함해도, workflow는 Gemini만 선택
LLM_GEMINI_ONLY = os.environ.get("LLM_GEMINI_ONLY", "1").strip().lower() in ("1", "true", "yes")
LLM_GEMINI_PREFERRED_SUBSTRING = os.environ.get("LLM_GEMINI_PREFERRED_SUBSTRING", "gemini-3").strip().lower()

# [MODIFIED] 기본 출력 토큰 수 최대치로 상향 (65536)
# Gemini 3 Pro Preview 스펙에 맞춤
DEFAULT_LLM_NUM_PREDICT = 65536
DEFAULT_LLM_RETRIES = 2
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
import os as _os

JENKINS_BASE_URL = _os.environ.get("DEVOPS_JENKINS_BASE_URL", "http://<jenkins-host>:<port>")
JENKINS_USERNAME = _os.environ.get("DEVOPS_JENKINS_USERNAME", "<fixed-username>")
JENKINS_API_TOKEN = _os.environ.get("DEVOPS_JENKINS_API_TOKEN", "<fixed-api-token>")
JENKINS_HIDE_CREDENTIALS = _os.environ.get("DEVOPS_JENKINS_HIDE_CREDENTIALS", "1") == "1"
JENKINS_VERIFY_TLS = _os.environ.get("DEVOPS_JENKINS_VERIFY_TLS", "1") == "1"

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
