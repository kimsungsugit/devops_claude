# /app/workflow/build.py
# -*- coding: utf-8 -*-
"""
Build & Test helpers

Host build goals
- tests/stubs 자동 생성으로 Pico SDK 의존성 대체
- CMake try_compile 단계에 영향을 주는 전역 플래그(CFLAGS/CXXFLAGS/CPPFLAGS/LDFLAGS) 제거
- coverage/sanitizer/강제 include는 CMakeLists.txt에서 target 단위로만 적용
- CTest 실패/타임아웃/ASan/TSan/CRC 등을 triage하여 AI test_fix 우선순위에 활용

v31.2
- Fix Pylance: undefined 'gen', 'ctest_out'
- Fix triage_ctest_output indentation/import crash
- Make triage richer (timeout/asan/assert/crc) and return target hints
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import analysis_tools as tools
import config
from utils.log import get_logger
from . import stubs
from .common import create_backup, standardize_result

_logger = get_logger(__name__)


def ensure_auto_generated_subdir(project_root: Path, reports_dir: Path) -> None:
    """
    reports/auto_generated 에 생성된 테스트들을 최상위 CMakeLists.txt에 연결하는 헬퍼

    - reports_dir가 세션 경로(프로젝트 외부)일 때, project_root/reports/auto_generated 으로 복사 후
      add_subdirectory(reports/auto_generated) 가 동작하도록 함.
    - auto_generated/CMakeLists.txt 가 없으면 아무 것도 하지 않음.
    - 이미 add_subdirectory(reports/auto_generated) 가 있으면 스킵.
    """
    try:
        project_root = Path(project_root).resolve()
        reports_dir = Path(reports_dir).resolve()
        src_ag = reports_dir / "auto_generated"
        tests_src = src_ag / "CMakeLists.txt"
        if not tests_src.exists():
            return

        dest_reports = project_root / "reports"
        dest_ag = dest_reports / "auto_generated"

        # 세션 경로에 있으면 프로젝트 내 reports/auto_generated 로 동기화
        try:
            reports_dir.relative_to(project_root)
            inside_project = True
        except ValueError:
            inside_project = False

        if not inside_project:
            dest_reports.mkdir(parents=True, exist_ok=True)
            if dest_ag.exists():
                shutil.rmtree(dest_ag, ignore_errors=True)
            shutil.copytree(src_ag, dest_ag, ignore=shutil.ignore_patterns("*.bak", ".git"))

        top = project_root / "CMakeLists.txt"
        if not top.exists():
            return

        txt = top.read_text(encoding="utf-8", errors="ignore")
        if "add_subdirectory(reports/auto_generated" in txt or "add_subdirectory(reports\\auto_generated" in txt:
            return

        patch = "\n# Auto-generated unit tests\nif(HOST_BUILD)\n  if(EXISTS \"${CMAKE_CURRENT_LIST_DIR}/reports/auto_generated/CMakeLists.txt\")\n    add_subdirectory(reports/auto_generated)\n  endif()\nendif()\n"
        create_backup(top)
        top.write_text(txt + patch, encoding="utf-8")
    except Exception:
        pass


def _guess_targets_from_testname(test_name: str) -> List[str]:
    n = (test_name or "").lower()
    out: List[str] = []
    if "e2e" in n:
        out.append("libs/e2e.c")
    if "lin_master" in n:
        out += ["libs/lin_master.c", "libs/lin_protocol.c", "libs/gateway_logic.c"]
    if "lin_slave" in n:
        out += ["libs/lin_slave.c", "libs/lin_protocol.c", "libs/shared_data.c"]
    if "rotary_switch" in n:
        out += ["libs/rotary_switch.c", "libs/shared_data.c"]
    if "gateway_logic" in n:
        out += ["libs/gateway_logic.c", "libs/shared_data.c"]
    if "shared_data" in n:
        out += ["libs/shared_data.c"]
    if "lin_protocol" in n:
        out += ["libs/lin_protocol.c"]
    # uniq
    uniq: List[str] = []
    for t in out:
        if t not in uniq:
            uniq.append(t)
    return uniq


def triage_ctest_output(ctest_text: str) -> Dict[str, Any]:
    """
    CTest 출력에서 흔한 실패 원인(ASan/TSan/timeout/assert/crc)을 뽑아
    - failures: 원인 목록
    - targets: 우선 수정 타깃(프로덕션 소스 위주) 힌트
    를 리턴
    """
    failures: List[Dict[str, Any]] = []
    targets: List[str] = []
    text = ctest_text or ""
    lines = text.splitlines()
    joined = "\n".join(lines)

    # 1) Timeout
    timeout_tests: List[str] = []
    for ln in lines:
        if "***Timeout" in ln:
            m = re.search(r"Start\s+\d+:\s*([A-Za-z0-9_]+)", ln)
            name = m.group(1) if m else ln.strip()
            timeout_tests.append(name)
            failures.append(
                {
                    "type": "timeout",
                    "test": name,
                    "hint": "무한루프/대기 루프 가능성, sleep/time stub 전진 여부, 큐/상태머신 종료조건 확인",
                }
            )
            targets += _guess_targets_from_testname(name)

    # 2) AddressSanitizer
    if "AddressSanitizer" in joined or "ERROR: AddressSanitizer" in joined:
        # stack frame에서 파일 경로 힌트 추출
        m = re.search(r"in\s+[A-Za-z0-9_]+\s+([^\s]+?):(\d+)", joined)
        file_path: Optional[str] = None
        line_no: Optional[int] = None
        if m:
            file_path = m.group(1)
            try:
                line_no = int(m.group(2))
            except Exception:
                line_no = None

        failures.append(
            {
                "type": "asan",
                "file": file_path,
                "line": line_no,
                "hint": "버퍼 오버플로/Use-after-free/경계 체크 미흡, memcpy/len 계산, 구조체 크기/배열 인덱스 확인",
            }
        )

        # auto_generated 안에서 발생했으면 해당 테스트 이름으로 prod 타깃 유추
        if "/reports/auto_generated/" in (file_path or "").replace("\\", "/"):
            # 우선 test 이름을 찾아 매핑
            test_name = None
            for ln in lines:
                if "Start" in ln and ":" in ln:
                    mm = re.search(r"Start\s+\d+:\s*([A-Za-z0-9_]+)", ln)
                    if mm:
                        test_name = mm.group(1)
                        break
            if test_name:
                targets += _guess_targets_from_testname(test_name)
            else:
                targets += ["libs/lin_master.c", "libs/gateway_logic.c"]
        elif file_path:
            targets.append(file_path)

    # 3) ThreadSanitizer
    if "ThreadSanitizer" in joined or "ERROR: ThreadSanitizer" in joined:
        failures.append(
            {
                "type": "tsan",
                "hint": "경쟁상태/락 누락 가능성, shared_data 접근 경로/뮤텍스/큐 처리 확인",
            }
        )
        targets += ["libs/shared_data.c", "libs/gateway_logic.c"]

    # 4) Assertion failed
    if "Assertion `" in joined and "failed" in joined:
        failures.append(
            {"type": "assert", "hint": "테스트 기대값 불일치, 초기화/상태전이/스텁 리턴값/경계값 확인"}
        )
        # 어떤 테스트인지 탐색
        for ln in lines:
            if "Start" in ln:
                m = re.search(r"Start\s+\d+:\s*([A-Za-z0-9_]+)", ln)
                if m:
                    targets += _guess_targets_from_testname(m.group(1))
                    break

    # 5) CRC mismatch (e2e)
    if "CRC8 Unit Tests" in joined and "[FAIL]" in joined:
        failures.append(
            {
                "type": "crc",
                "hint": "CRC8 파라미터(poly/init/xor/refin/refout) 또는 table/bit-order 구현 불일치 가능성",
            }
        )
        targets.append("libs/e2e.c")

    # uniq targets
    uniq_targets: List[str] = []
    for t in targets:
        if t and t not in uniq_targets:
            uniq_targets.append(t)

    return {"failures": failures, "targets": uniq_targets, "timeout_tests": timeout_tests}


def build_and_tests(
    project_root: Path,
    reports_dir: Path,
    do_coverage: bool = False,
    do_asan: bool = False,
    host_build: Optional[bool] = None,
    stability_gate: bool = False,
    build_dir_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    HOST_BUILD 기반 CMake configure/build + CTest 실행.

    반환값:
      ok: (config+build+ctest) 성공 여부
      data: 로그/triage/빌드디렉토리 등
    """
    reports_dir = Path(reports_dir)
    log = ""
    build_dir_note = ""
    if build_dir_override:
        bdir = Path(str(build_dir_override)).expanduser()
        build_dir = (project_root / bdir).resolve() if not bdir.is_absolute() else bdir.resolve()
    else:
        build_dir = reports_dir / ("build_host" if bool(host_build) or do_coverage or do_asan else "build_target")

    if build_dir.resolve() == project_root.resolve():
        safe_dir = reports_dir / ("build_host" if bool(host_build) or do_coverage or do_asan else "build_target")
        build_dir_note = f"[warn] build_dir points to project root; using {safe_dir}\n"
        build_dir = safe_dir
    tests_dir = reports_dir / ("tests_host" if bool(host_build) or do_coverage or do_asan else "tests_target")

    ensure_auto_generated_subdir(project_root, reports_dir)

    need_host = True if host_build is None else bool(host_build)
    if do_coverage or do_asan:
        need_host = True

    if need_host:
        # 0) stubs 보장
        stubs_root = project_root / "tests" / "stubs"
        try:
            stubs.ensure_stubs(stubs_root)
        except Exception as e:
            _logger.warning("ensure_stubs failed: %s", e)

        # 1) clean build dir (기본 ON)
        # Windows/MinGW에서 ASan 관련 캐시 문제를 방지하기 위해
        # SANITIZER_PROD가 변경될 때는 빌드 디렉토리를 정리
        should_clean = False
        if os.environ.get("HOST_BUILD_CLEAN", "1") == "1" and build_dir.exists():
            # CMakeLists.txt가 없으면 (잘못된 빌드 디렉토리) 삭제
            if not (build_dir / "CMakeLists.txt").exists():
                should_clean = True
            # 커버리지 활성화 시 빌드 캐시 정리 (generator/flags stale 방지)
            elif do_coverage:
                should_clean = True
            # Windows/MinGW에서 ASan이 활성화되어 있으면 캐시 정리
            elif do_asan:
                cache_file = build_dir / "CMakeCache.txt"
                if cache_file.exists():
                    try:
                        cache_content = cache_file.read_text(encoding="utf-8", errors="ignore")
                        # 이전에 ASan이 활성화되어 있었으면 캐시 정리
                        if "SANITIZER_PROD:STRING=asan" in cache_content or "-fsanitize=address" in cache_content:
                            should_clean = True
                    except Exception:
                        pass
        
        if should_clean:
            shutil.rmtree(build_dir, ignore_errors=True)

    tools.ensure_dir(build_dir)
    tools.ensure_dir(tests_dir)

# 2) CMake 옵션 구성
    extra: List[str] = ["-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"]

    sanitizer_prod = "none"
    sanitizer_tests = "none"

    # 3) 환경변수 정리 (TryCompile 보호)
    env = os.environ.copy()
    if need_host:
        extra += ["-DHOST_BUILD=1"]
        extra += [f"-DDEVOPS_COVERAGE={'ON' if do_coverage else 'OFF'}"]

        # Windows MinGW에서는 ASan을 지원하지 않으므로 비활성화
        # ASan은 Linux/Clang 환경에서만 사용 가능
        is_windows_mingw = (
            shutil.which("gcc") and 
            ("mingw" in str(shutil.which("gcc")).lower() or 
             os.name == "nt")
        )
        if do_asan and is_windows_mingw:
            sanitizer_prod = "ubsan"
            asan_warning = "[INFO] ASan unavailable on Windows MinGW → using UBSan (Undefined Behavior Sanitizer) + Stack Protector instead\n"
            log += asan_warning
            _logger.info(asan_warning.strip())
        else:
            sanitizer_prod = "asan" if do_asan else os.environ.get("DEVOPS_SANITIZER_PROD", "none")
        sanitizer_tests = os.environ.get("DEVOPS_SANITIZER_TESTS", "none")

        extra += [
            f"-DSANITIZER_PROD={sanitizer_prod}",
            f"-DSANITIZER_TESTS={sanitizer_tests}",
            "-DDEVOPS_FORCE_STUB_INCLUDE_PROD=ON",
            "-DDEVOPS_FORCE_STUB_INCLUDE_TESTS=OFF",
            f"-DCTEST_TIMEOUT_SEC={os.environ.get('CTEST_TIMEOUT_SEC', '120')}",
        ]

    toolchain_file = (os.environ.get("CMAKE_TOOLCHAIN_FILE") or "").strip()
    if toolchain_file:
        extra += [f"-DCMAKE_TOOLCHAIN_FILE={toolchain_file}"]

    detected_pico_sdk = None
    if need_host and not env.get("PICO_SDK_PATH"):
        roots = [project_root, project_root.parent, project_root.parent.parent]
        pf = os.environ.get("ProgramFiles")
        pf86 = os.environ.get("ProgramFiles(x86)")
        if pf:
            roots.append(Path(pf))
        if pf86:
            roots.append(Path(pf86))
        candidates: List[Path] = []
        for root in roots:
            candidates += [
                root / "pico-sdk",
                root / "pico_sdk",
                root / "third_party" / "pico-sdk",
                root / "third_party" / "pico_sdk",
                root / "externals" / "pico-sdk",
                root / "externals" / "pico_sdk",
            ]
        for cand in candidates:
            try:
                if cand.exists() and cand.is_dir():
                    detected_pico_sdk = str(cand.resolve())
                    env["PICO_SDK_PATH"] = detected_pico_sdk
                    break
            except Exception:
                continue

    if need_host and not env.get("PICO_SDK_PATH"):
        def _walk_depth(root: Path, max_depth: int = 4) -> Optional[str]:
            try:
                root = root.resolve()
                for dirpath, dirnames, filenames in os.walk(root):
                    rel = Path(dirpath).resolve().relative_to(root)
                    if len(rel.parts) > max_depth:
                        dirnames[:] = []
                        continue
                    if any(p.startswith("build") for p in rel.parts) or "reports" in rel.parts or ".git" in rel.parts:
                        dirnames[:] = []
                        continue
                    if "pico_sdk_init.cmake" in filenames:
                        init_path = Path(dirpath) / "pico_sdk_init.cmake"
                        if init_path.parent.name == "external":
                            return str(init_path.parent.parent.resolve())
                        return str(init_path.parent.resolve())
            except Exception:
                return None
            return None

        for root in roots:
            found = _walk_depth(root)
            if found:
                detected_pico_sdk = found
                env["PICO_SDK_PATH"] = detected_pico_sdk
                break

    if need_host:
        # HOST_BUILD 모드에서는 호스트 컴파일러(gcc/g++)를 사용해야 함
        # ARM 컴파일러는 타겟 빌드에서만 사용
        extra += [
            "-DCMAKE_C_COMPILER=gcc",
            "-DCMAKE_CXX_COMPILER=g++",
        ]
        # 환경변수에서도 호스트 컴파일러 사용
        env["CC"] = "gcc"
        env["CXX"] = "g++"

    # generator (Pylance undefined fix)
    gen: List[str] = []
    cg = (os.environ.get("CMAKE_GENERATOR") or "").strip()
    effective_generator = cg
    if not effective_generator:
        if need_host:
            if shutil.which("ninja"):
                effective_generator = "Ninja"
            elif shutil.which("mingw32-make") or shutil.which("gcc"):
                effective_generator = "MinGW Makefiles"
        elif env.get("PICO_SDK_PATH"):
            if shutil.which("ninja"):
                effective_generator = "Ninja"
    if effective_generator:
        gen = ["-G", effective_generator]
    if need_host:
        # CMake는 CFLAGS/CXXFLAGS/CPPFLAGS/LDFLAGS를 초기 플래그로 사용 -> try_compile 실패 위험
        for k in ("CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS"):
            env.pop(k, None)

    # Sanitizer runtime options
    if sanitizer_prod != "none" or sanitizer_tests != "none":
        env.setdefault("ASAN_OPTIONS", "detect_leaks=1:halt_on_error=1:abort_on_error=1")
        env.setdefault("UBSAN_OPTIONS", "halt_on_error=1:abort_on_error=1")
        env.setdefault("TSAN_OPTIONS", "halt_on_error=1:abort_on_error=1")

    # 4) CMake configure
    cmake_config_cmd = [
        "cmake",
        "-S",
        str(project_root),
        "-B",
        str(build_dir),
        "-DCMAKE_BUILD_TYPE=Debug",
        *gen,
        *extra,
    ]
    
    # CMake 명령어 로깅 (디버깅용)
    cmd_str = " ".join(shlex.quote(str(arg)) for arg in cmake_config_cmd)
    coverage_flag_log = f"DEVOPS_COVERAGE={'ON' if do_coverage else 'OFF'}" if need_host else "N/A (not host build)"
    
    c, o, e = tools.run_command(cmake_config_cmd, cwd=project_root, timeout=900, env=env if need_host else None)
    ts_header = f"[ctest] started_at={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    pico_line = ""
    if env.get("PICO_SDK_PATH"):
        pico_line = f"PICO_SDK_PATH={env.get('PICO_SDK_PATH')}\n"
    elif detected_pico_sdk:
        pico_line = f"PICO_SDK_PATH={detected_pico_sdk}\n"
    else:
        pico_line = "PICO_SDK_PATH=(not set)\n"
    gen_line = f"CMAKE_GENERATOR={effective_generator}\n" if effective_generator else "CMAKE_GENERATOR=(default)\n"
    cc_line = f"CC={env.get('CC', '(not set)')}\nCXX={env.get('CXX', '(not set)')}\n"
    coverage_line = f"Coverage enabled: {coverage_flag_log}\n"
    cmd_line = f"CMake command: {cmd_str}\n"
    log = f"{ts_header}{pico_line}{gen_line}{cc_line}{coverage_line}{cmd_line}{build_dir_note}=== CMake Config ===\n{o}\n{e}\n"

    if c != 0:
        (tests_dir / "ctest_output.txt").write_text(log, encoding="utf-8")
        return standardize_result(False, "config_fail", {"build_dir": str(build_dir), "log": log})
    
    # CMake configure 성공 후 DEVOPS_COVERAGE 설정 확인
    if do_coverage and need_host:
        cmake_cache = build_dir / "CMakeCache.txt"
        if cmake_cache.exists():
            try:
                cache_content = cmake_cache.read_text(encoding="utf-8", errors="ignore")
                if "DEVOPS_COVERAGE:BOOL=ON" not in cache_content and "DEVOPS_COVERAGE:BOOL=OFF" not in cache_content:
                    log += "\n⚠️ WARNING: DEVOPS_COVERAGE not found in CMakeCache.txt.\n"
                    log += "   CMakeLists.txt does not use DEVOPS_COVERAGE. Apply CMakeLists.txt.fixed to your project.\n"
                    log += "   Ensure HOST_BUILD branch with DEVOPS_COVERAGE check and coverage flags (-fprofile-arcs -ftest-coverage).\n"
            except Exception:
                pass

    # 5) Build
    gen_name = (effective_generator or "").lower()
    if "visual studio" in gen_name:
        build_args = ["/m"]
    elif "ninja" in gen_name or "makefile" in gen_name:
        build_args = ["-j", str(os.cpu_count() or 4)]
    else:
        build_args = []
    cmake_build_cmd = ["cmake", "--build", str(build_dir), "--", *build_args]
    c2, o2, e2 = tools.run_command(cmake_build_cmd, cwd=project_root, timeout=1800, env=env if need_host else None)
    log += f"\n=== Build ===\n{o2}\n{e2}\n"
    
    # 빌드 실패 감지: exit code가 0이 아니거나, 출력에 "FAILED" 또는 "error"가 포함된 경우
    build_failed = (c2 != 0) or ("FAILED:" in o2) or ("FAILED:" in e2) or ("error:" in e2.lower())
    if build_failed:
        (tests_dir / "ctest_output.txt").write_text(log, encoding="utf-8")
        return standardize_result(False, "build_fail", {
            "build_dir": str(build_dir), 
            "log": log,
            "build_ok": False,
            "tests_ok": False,
            "exit_code": c2
        })

    # 6) CTest (per-test execution, continue-on-fail)
    try:
        timeout_sec = int(os.environ.get("CTEST_TIMEOUT_SEC", "120") or "120")
    except (ValueError, TypeError):
        timeout_sec = 120
    timeout_sec = max(10, min(7200, timeout_sec))
    ctest_results: List[Dict[str, Any]] = []

    # 6.1) Discover test names (ctest -N). If discovery fails, fall back to one-shot ctest.
    list_cmd = ["ctest", "-N"]
    last_ctest_cmd: List[str] = list(list_cmd)
    cL, oL, eL = tools.run_command(
        list_cmd,
        cwd=build_dir,
        timeout=120,
        env=env if need_host else None,
    )
    log += f"\n=== CTest List ===\n{oL}\n{eL}\n"
    discovered: List[str] = []
    for line in (f"{oL}\n{eL}\n").splitlines():
        m = re.search(r"Test\s+#\d+:\s+(.+?)\s*$", line)
        if m:
            name = m.group(1).strip()
            if name:
                discovered.append(name)

    manual_mode = False
    if not discovered:
        # Fallback: run test executables directly if CTest discovery fails.
        manual_tests: List[Path] = []
        exe_ext = ".exe" if os.name == "nt" else ""
        for p in build_dir.rglob(f"ai_ut_*{exe_ext}"):
            if p.is_file():
                manual_tests.append(p)
        manual_tests = sorted(manual_tests, key=lambda x: x.name)
        if manual_tests:
            manual_mode = True
            log += "\n[CTest] No tests discovered (ctest -N). Running test executables directly.\n"
            for exe in manual_tests:
                per_timeout = max(300, timeout_sec + 120)
                cT, oT, eT = tools.run_command(
                    [str(exe)],
                    cwd=build_dir,
                    timeout=per_timeout,
                    env=env if need_host else None,
                )
                out_text = f"{ts_header}=== Manual Test Run @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n{oT}\n{eT}\n"
                safe_name = exe.name.replace("/", "_").replace("\\", "_")
                out_path = tests_dir / f"ctest_{safe_name}_r1.txt"
                try:
                    out_path.write_text(out_text, encoding="utf-8")
                except Exception:
                    pass
                status = "pass" if cT == 0 else ("timeout" if "Timeout" in out_text or "TIMEOUT" in out_text else "fail")
                ctest_results.append(
                    {
                        "name": exe.stem,
                        "exit_code": int(cT),
                        "status": status,
                        "output": str(out_path),
                        "round": "r1",
                    }
                )
                log += f"\n--- ManualTest: {exe.name} ---\n{oT}\n{eT}\n"
        else:
            discovered = ["__all__"]
            log += "\n[CTest] No tests discovered (ctest -N). Running ctest anyway; 'No tests were found' likely.\n"
            log += "  Causes: (1) add_subdirectory(reports/auto_generated) missing in CMakeLists.txt,\n"
            log += "          (2) no valid test_*.c in reports/auto_generated, (3) all tests in _invalid.\n"

    def _run_ctest_round(tag: str) -> List[Dict[str, Any]]:
        nonlocal log, last_ctest_cmd
        results: List[Dict[str, Any]] = []
        for name in discovered:
            if name == "__all__":
                cmd = ["ctest", "--output-on-failure", "--timeout", str(timeout_sec)]
            else:
                # Use exact regex match to avoid accidentally selecting multiple tests.
                cmd = [
                    "ctest",
                    "-R",
                    f"^{re.escape(name)}$",
                    "--output-on-failure",
                    "--timeout",
                    str(timeout_sec),
                ]

            last_ctest_cmd = list(cmd)
            # Give enough time budget for a single test run.
            per_timeout = max(300, timeout_sec + 120)
            cT, oT, eT = tools.run_command(
                cmd,
                cwd=build_dir,
                timeout=per_timeout,
                env=env if need_host else None,
            )
            out_text = f"{ts_header}=== CTest Run ({tag}) @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n{oT}\n{eT}\n"

            # Persist each test output for triage and UI display.
            safe_name = name.replace("/", "_").replace("\\", "_")
            out_path = tests_dir / (f"ctest_{safe_name}_{tag}.txt" if name != "__all__" else f"ctest_all_{tag}.txt")
            try:
                out_path.write_text(out_text, encoding="utf-8")
            except Exception:
                pass

            status = "pass" if cT == 0 else ("timeout" if "Timeout" in out_text or "TIMEOUT" in out_text else "fail")
            results.append(
                {
                    "name": None if name == "__all__" else name,
                    "exit_code": int(cT),
                    "status": status,
                    "output": str(out_path),
                    "round": tag,
                }
            )

            log += f"\n--- CTest({tag}): {name} ---\n{oT}\n{eT}\n"
        return results

    # 6.2) Run each test individually so a hang/crash does not block the rest.
    if not manual_mode:
        ctest_results = _run_ctest_round("r1")

    # 6.3) Stability gate (optional): run twice and compare
    unstable_tests: List[str] = []
    if stability_gate and not manual_mode:
        ctest_results2 = _run_ctest_round("r2")
        by_name_1 = {r.get("name") or "__all__": r for r in ctest_results}
        by_name_2 = {r.get("name") or "__all__": r for r in ctest_results2}
        for name, r1 in by_name_1.items():
            r2 = by_name_2.get(name)
            if not r2:
                unstable_tests.append(str(name))
                continue
            if r1.get("status") != r2.get("status"):
                unstable_tests.append(str(name))
        ctest_results.extend(ctest_results2)
        if unstable_tests:
            log += f"\n[Stability Gate] Unstable tests: {', '.join(unstable_tests)}\n"

    # 6.4) Overall test outcome
    if len(ctest_results) == 1 and ctest_results[0].get("name") is None:
        tests_ok = (ctest_results[0].get("exit_code", 1) == 0)
    else:
        tests_ok = all(r.get("exit_code", 1) == 0 for r in ctest_results if r.get("name") is not None)
    if unstable_tests:
        tests_ok = False

    ctest_out = ""
    for r in ctest_results:
        if r.get("exit_code", 1) != 0:
            try:
                ctest_out += Path(r["output"]).read_text(encoding="utf-8", errors="ignore") + "\n"
            except Exception:
                pass

    triage = triage_ctest_output(ctest_out) if not tests_ok else {"failures": [], "targets": [], "timeout_tests": []}

    # One integer exit-code (0 if all tests passed)
    c3 = 0 if tests_ok else 1

    ok = tests_ok
    reason = "completed" if ok else "test_fail"
    data = {
        "build_dir": str(build_dir),
        "log": log,
        "config_ok": True,
        "build_ok": True,
        "tests_ok": bool(ok),
        "asan_enabled": bool(do_asan),
        "sanitizer_prod": sanitizer_prod,
        "sanitizer_tests": sanitizer_tests,
        "coverage_enabled": bool(do_coverage),
        "ctest_exit_code": int(c3),
        "ctest_results": ctest_results,
        "triage": triage,
        "unstable_tests": unstable_tests,
        "cmake_cmd": cmd_str,
        "cmake_build_cmd": " ".join(shlex.quote(str(arg)) for arg in cmake_build_cmd),
        "ctest_cmd": " ".join(shlex.quote(str(arg)) for arg in last_ctest_cmd),
        "ctest_list_cmd": " ".join(shlex.quote(str(arg)) for arg in list_cmd),
    }
    return standardize_result(ok, reason, data)


def auto_guard_sources(
    project_root: Path,
    reports_dir: Path,
    files: List[Path],
    prefixes: List[str],
    stubs_dir: str,
    dry: bool,
    cb: Optional[Callable[[int, int, str], None]],
) -> Dict[str, Any]:
    """
    소스 코드 내의 하드웨어/플랫폼 의존 include들을 UNIT_TEST/HOST_BUILD 가드로 감싸는 유틸리티.
    """
    rep: Dict[str, Any] = {"touched_files": []}
    if not prefixes:
        return standardize_result(True, "no_prefixes", rep)

    inc_re = re.compile(r'^\s*#\s*include\s*([<"])([^">]+)([>"])', re.M)

    for idx, fp in enumerate(files):
        if cb:
            cb(idx + 1, len(files), f"Auto-Guard: {fp.name}")

        if fp.suffix not in (".c", ".h"):
            continue

        try:
            lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue

        new_lines: List[str] = []
        changed = False

        for i, line in enumerate(lines):
            m = inc_re.match(line)
            if m and any(m.group(2).startswith(p) for p in prefixes):
                chunk = "\n".join(lines[max(0, i - 5) : i + 5])
                if "UNIT_TEST" not in chunk and "stubs/" not in line:
                    guarded = (
                        "#ifdef UNIT_TEST\n"
                        f"#include \"{stubs_dir.rstrip('/')}/{m.group(2)}\"\n"
                        "#elif defined(HOST_BUILD)\n"
                        f"#include \"{stubs_dir.rstrip('/')}/{m.group(2)}\"\n"
                        "#else\n"
                        f"#include \"{m.group(2)}\"\n"
                        "#endif"
                    )
                    new_lines.append(guarded)
                    changed = True
                    continue

            new_lines.append(line)

        if changed:
            rep["touched_files"].append(str(fp))
            if not dry:
                create_backup(fp)
                fp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    return standardize_result(True, "completed", rep)
