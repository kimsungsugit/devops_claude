# /app/workflow/ci_entry.py
# -*- coding: utf-8 -*-
"""
CI 전용 엔트리 포인트
- Jenkins (또는 다른 CI)에서 이 모듈만 호출하면 전체 파이프라인 실행
- exit code 를 Jenkins 빌드 결과와 연결
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import List, Optional

from . import pipeline


def _bool_env(name: str, default: bool = False) -> bool:
    """환경변수에서 bool 값 읽기용 헬퍼 (Jenkins에서 override 용도)"""
    v = os.environ.get(name)
    if v is None:
        return default
    v = v.strip().lower()
    return v in ("1", "true", "yes", "on")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="CI entry for my_lin_gateway workflow")
    parser.add_argument(
        "--project-root",
        default=".",
        help="분석 대상 프로젝트 루트 경로 (기본값: 현재 디렉터리)",
    )
    parser.add_argument(
        "--report-dir",
        default="reports",
        help="리포트 출력 디렉터리 (기본값: reports)",
    )
    parser.add_argument(
        "--targets-glob",
        default="libs/*.c",
        help="분석 대상 소스 glob 패턴 (기본값: libs/*.c)",
    )
    parser.add_argument(
        "--oai-config",
        default=os.environ.get("OAI_CONFIG_PATH", ""),
        help="LLM 설정 파일 경로 (선택)",
    )

    # Jenkins에서 환경변수로도 제어할 수 있게 하고, CLI 인자는 override 용도
    parser.add_argument("--no-fuzz", action="store_true", help="Fuzzing 비활성화")
    parser.add_argument("--no-qemu", action="store_true", help="QEMU 비활성화")
    parser.add_argument("--no-domain", action="store_true", help="Domain Test 비활성화")
    parser.add_argument("--no-coverage", action="store_true", help="Coverage 비활성화")
    parser.add_argument("--static-only", action="store_true", help="정적 분석만 수행")
    parser.add_argument("--no-auto-guard", action="store_true", help="Auto-Guard(하드웨어 include 보호) 비활성화")
    parser.add_argument("--no-fast-fail", action="store_true", help="Fast-Fail(사전 문법/정적 체크) 비활성화")
    parser.add_argument("--ignore-static-failure", action="store_true", help="정적 분석 이슈가 있어도 빌드 실패로 처리하지 않음")

    args = parser.parse_args(argv)

    proj_root = str(Path(args.project_root).resolve())
    report_dir = args.report_dir

    # 환경변수 기반 기본값
    do_fuzz = _bool_env("CI_ENABLE_FUZZ", True) and not args.no_fuzz
    do_qemu = _bool_env("CI_ENABLE_QEMU", True) and not args.no_qemu
    do_domain = _bool_env("CI_ENABLE_DOMAIN_TESTS", True) and not args.no_domain
    do_coverage = _bool_env("CI_ENABLE_COVERAGE", True) and not args.no_coverage

    # 정적 분석만 할지 여부
    static_only = args.static_only

    # 기본 정책: CI에서는 auto_guard, fast_fail 켜고, 정적 실패는 기본적으로 실패로 처리
    auto_guard = _bool_env("CI_AUTO_GUARD", True) and (not args.no_auto_guard)
    fast_fail = _bool_env("CI_FAST_FAIL", True) and (not args.no_fast_fail)
    ignore_static_failure = (_bool_env("CI_IGNORE_STATIC_FAILURE", False) or args.ignore_static_failure)


    # CI 기본 전략
    # - cmake build + unit test + coverage + fuzz + qemu + domain tests
    # - agent patch 는 review 모드거나 off 로 두고, Jenkins 측에서는 코드 변경 X 추천
    exit_code = pipeline.run_cli(
        project_root=proj_root,
        report_dir=report_dir,
        targets_glob=args.targets_glob,
        include_paths=None,
        suppressions_path=None,
        do_cmake_analysis=False,
        do_syntax_check=True,
        do_build_and_test=True,
        do_coverage=do_coverage,
        static_only=static_only,
        enable_agent=False,     # Jenkins에서는 기본 false, 필요하면 나중에 review 모드로
        max_iterations=1,
        oai_config_path=args.oai_config or None,
        pico_sdk_path_override=os.environ.get("PICO_SDK_PATH") or None,
        auto_guard=auto_guard,
        fast_fail=fast_fail,
        ignore_static_failure=ignore_static_failure,
        # auto_guard 설정, guard_profiles 등은 필요하면 나중에 CI용 프로파일 추가
        target_arch=os.environ.get("TARGET_ARCH", "cortex-m0plus"),
        extra_defines=None,
        cppcheck_enable=None,
        enable_test_gen=_bool_env("CI_ENABLE_TEST_GEN", True),
        do_clang_tidy=True,
        clang_tidy_checks=None,
        do_asan=True,           # CI에선 AddressSanitizer 켜두는 편
        do_fuzz=do_fuzz,
        do_qemu=do_qemu,
        do_docs=True,
        enable_domain_tests=do_domain,
        domain_targets=None,
        # full_analysis / log_callback 등 뒤에 추가 파라미터가 있다면
        # 파이프라인 실제 시그니처에 맞게 이어서 넣어주기
    )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())