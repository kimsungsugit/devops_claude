# /app/main.py
# -*- coding: utf-8 -*-
# Main CLI entrypoint (v30.2: Fixed Argument Sync with Pipeline)

from __future__ import annotations
import argparse
import inspect
import sys
import os
import shutil
import subprocess
import config

try:
    from workflow import run_cli
except Exception as e:
    print(f"[main] Failed to import workflow: {e}", file=sys.stderr)
    raise

DEFAULT_CPP_ENABLE = ",".join(config.DEFAULT_CPPCHECK_ENABLE)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="analysis-cli", description=f"{config.ENGINE_NAME} CLI")
    
    # 기본 경로 설정
    parser.add_argument("--project-root", required=True, help="Target project root")
    parser.add_argument("--report-dir", default=config.DEFAULT_REPORT_DIR)
    parser.add_argument("--targets-glob", default=config.DEFAULT_TARGETS_GLOB)
    
    # 정적 분석 옵션
    parser.add_argument("--full-analysis", action="store_true")
    parser.add_argument("--cppcheck-enable", default=DEFAULT_CPP_ENABLE)
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--do-clang-tidy", action="store_true")
    parser.add_argument("--clang-tidy-checks", default="bugprone-*,performance-*")
    
    # [FIX] 동적 분석 옵션 추가 (pipeline.py와 동기화)
    parser.add_argument("--do-build", action="store_true", help="Enable Build & Test")
    parser.add_argument("--do-asan", action="store_true", help="Enable AddressSanitizer")
    parser.add_argument("--do-fuzz", action="store_true", help="Enable AI Fuzzing")
    parser.add_argument("--do-qemu", action="store_true", help="Enable QEMU Smoke Test")
    parser.add_argument("--do-docs", action="store_true", help="Generate Doxygen Docs")
    parser.add_argument("--target-arch", default=config.DEFAULT_TARGET_ARCH, help="Target Architecture (e.g., cortex-m0plus)")
    
    # AI 에이전트 옵션
    parser.add_argument("--oai-config-path", default=config.DEFAULT_OAI_CONFIG_PATH)
    parser.add_argument("--enable-agent", action="store_true")
    parser.add_argument("--max-iterations", type=int, default=1)
    parser.add_argument("--enable-test-gen", action="store_true")
    parser.add_argument("--agent-roles", default=None, help="Comma-separated agent roles (planner,generator,fixer,reviewer)")
    parser.add_argument("--agent-max-steps", type=int, default=None)
    parser.add_argument("--agent-run-mode", default=None, choices=getattr(config, "AGENT_RUN_MODES", ["auto", "review", "off"]))
    parser.add_argument("--agent-review", action="store_true")
    parser.add_argument("--agent-no-review", action="store_true")
    parser.add_argument("--agent-rag", action="store_true")
    parser.add_argument("--agent-no-rag", action="store_true")
    parser.add_argument("--agent-rag-top-k", type=int, default=None)
    
    return parser.parse_args()


def _health_check() -> bool:
    if os.environ.get("SKIP_HEALTH_CHECK", "").strip().lower() in ("1", "true", "yes"):
        return True
    tools = getattr(config, "REQUIRED_TOOLS", {})
    if not isinstance(tools, dict) or not tools:
        return True

    missing = []
    for tool, args in tools.items():
        if not shutil.which(tool):
            missing.append(tool)
            continue
        try:
            cmd = [tool] + list(args or [])
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=5)
            first = out.splitlines()[0] if out else ""
            print(f"[health] {tool}: {first}")
        except Exception as e:
            print(f"[health] {tool}: version check failed ({e})")

    if missing:
        print("[health] Missing required tools:")
        for t in missing:
            print(f"  - {t}")
        print("Install the missing tools or set SKIP_HEALTH_CHECK=1 to bypass.")
        return False
    return True

def main() -> int:
    args = parse_args()
    # 런타임 기본 환경변수 적용(사용자가 설정한 값은 유지)
    if hasattr(config, 'apply_runtime_env'):
        try:
            config.apply_runtime_env()
        except Exception:
            pass
    if not _health_check():
        return 2
    cpp_list = [x.strip() for x in args.cppcheck_enable.split(",") if x.strip()] or config.DEFAULT_CPPCHECK_ENABLE
    tidy_list = [x.strip() for x in args.clang_tidy_checks.split(",") if x.strip()]

    agent_review = True if args.agent_review else False if args.agent_no_review else None
    agent_rag = True if args.agent_rag else False if args.agent_no_rag else None

    full_kwargs = dict(
        project_root=args.project_root,
        max_iterations=args.max_iterations,
        report_dir=args.report_dir,
        cppcheck_enable=cpp_list,
        static_only=args.static_only,
        targets_glob=args.targets_glob,
        oai_config_path=args.oai_config_path,
        full_analysis=args.full_analysis,
        enable_agent=args.enable_agent,
        enable_test_gen=args.enable_test_gen,
        agent_roles=args.agent_roles,
        agent_max_steps=args.agent_max_steps,
        agent_run_mode=args.agent_run_mode,
        agent_review=agent_review,
        agent_rag=agent_rag,
        agent_rag_top_k=args.agent_rag_top_k,
        do_clang_tidy=args.do_clang_tidy,
        clang_tidy_checks=tidy_list,
        # [FIX] 누락되었던 인자들 매핑
        do_build_and_test=args.do_build, 
        do_asan=args.do_asan,
        do_fuzz=args.do_fuzz,
        do_qemu=args.do_qemu,
        do_docs=args.do_docs,
        target_arch=args.target_arch
    )

    try:
        # run_cli 함수 시그니처에 맞는 인자만 필터링하여 전달
        sig = inspect.signature(run_cli)
        safe_kwargs = {k: v for k, v in full_kwargs.items() if k in sig.parameters.keys()}
        
        print(f"🚀 Starting {config.ENGINE_NAME} CLI (v{config.ENGINE_VERSION})...")
        print(f"   Target: {args.project_root} ({args.target_arch})")
        exit_code = run_cli(**safe_kwargs)
    except Exception as e:
        print(f"[main] run_cli crashed: {e}", file=sys.stderr)
        return 2
    return int(exit_code)

if __name__ == "__main__":
    raise SystemExit(main())
