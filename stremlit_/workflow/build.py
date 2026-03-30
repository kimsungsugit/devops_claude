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
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import analysis_tools as tools
import config
from . import stubs
from .common import create_backup, standardize_result


def ensure_auto_generated_subdir(project_root: Path, reports_dir: Path) -> None:
    """
    reports/auto_generated 에 생성된 테스트들을 최상위 CMakeLists.txt에 연결하는 헬퍼

    - auto_generated/CMakeLists.txt 가 존재하지 않으면 아무 것도 하지 않음
    - 최상위 CMakeLists.txt에 이미 add_subdirectory(reports/auto_generated) 가 있으면 스킵
    """
    try:
        tests_src = reports_dir / "auto_generated" / "CMakeLists.txt"
        if not tests_src.exists():
            return

        top = project_root / "CMakeLists.txt"
        if not top.exists():
            return

        txt = top.read_text(encoding="utf-8", errors="ignore")
        if "add_subdirectory(reports/auto_generated" in txt:
            return

        # HOST_BUILD 케이스 내에만 넣고 싶지만, 간단히 파일 끝에 추가
        # (이미 HOST_BUILD 조건문 내에서 add_subdirectory를 호출하는 구조라면 중복이 될 수 있어 위에서 방지)
        patch = "\n# Auto-generated unit tests\nif(HOST_BUILD)\n  if(EXISTS \"${CMAKE_CURRENT_LIST_DIR}/reports/auto_generated/CMakeLists.txt\")\n    add_subdirectory(reports/auto_generated)\n  endif()\nendif()\n"
        create_backup(top)
        top.write_text(txt + patch, encoding="utf-8")
    except Exception:
        # 조용히 무시 (파이프라인 파괴 방지)
        return


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
) -> Dict[str, Any]:
    """
    HOST_BUILD 기반 CMake configure/build + CTest 실행.

    반환값:
      ok: (config+build+ctest) 성공 여부
      data: 로그/triage/빌드디렉토리 등
    """
    reports_dir = Path(reports_dir)
    build_dir = reports_dir / ("build_host" if bool(host_build) or do_coverage or do_asan else "build_target")
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
            print(f"[WARN] ensure_stubs failed: {e}")

        # 1) clean build dir (기본 ON)
        if os.environ.get("HOST_BUILD_CLEAN", "1") == "1" and build_dir.exists():
            shutil.rmtree(build_dir, ignore_errors=True)

    tools.ensure_dir(build_dir)
    tools.ensure_dir(tests_dir)

    # 2) CMake 옵션 구성
    extra: List[str] = ["-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"]

    sanitizer_prod = "none"
    sanitizer_tests = "none"
    if need_host:
        extra += [
            "-DHOST_BUILD=1",
            "-DCMAKE_C_COMPILER=gcc",
            "-DCMAKE_CXX_COMPILER=g++",
        ]
        extra += [f"-DDEVOPS_COVERAGE={'ON' if do_coverage else 'OFF'}"]

        sanitizer_prod = "asan" if do_asan else os.environ.get("DEVOPS_SANITIZER_PROD", "none")
        sanitizer_tests = os.environ.get("DEVOPS_SANITIZER_TESTS", "none")

        extra += [
            f"-DSANITIZER_PROD={sanitizer_prod}",
            f"-DSANITIZER_TESTS={sanitizer_tests}",
            "-DDEVOPS_FORCE_STUB_INCLUDE_PROD=ON",
            "-DDEVOPS_FORCE_STUB_INCLUDE_TESTS=OFF",
            f"-DCTEST_TIMEOUT_SEC={os.environ.get('CTEST_TIMEOUT_SEC', '120')}",
        ]

    # generator (Pylance undefined fix)
    gen: List[str] = []
    cg = (os.environ.get("CMAKE_GENERATOR") or "").strip()
    if cg:
        gen = ["-G", cg]

    # 3) 환경변수 정리 (TryCompile 보호)
    env = os.environ.copy()
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
    c, o, e = tools.run_command(cmake_config_cmd, cwd=project_root, timeout=900, env=env if need_host else None)
    ts_header = f"[ctest] started_at={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    log = f"{ts_header}=== CMake Config ===\n{o}\n{e}\n"

    if c != 0:
        (tests_dir / "ctest_output.txt").write_text(log, encoding="utf-8")
        return standardize_result(False, "config_fail", {"build_dir": str(build_dir), "log": log})

    # 5) Build
    cmake_build_cmd = ["cmake", "--build", str(build_dir), "--", "-j", str(os.cpu_count() or 4)]
    c2, o2, e2 = tools.run_command(cmake_build_cmd, cwd=project_root, timeout=1800, env=env if need_host else None)
    log += f"\n=== Build ===\n{o2}\n{e2}\n"
    if c2 != 0:
        (tests_dir / "ctest_output.txt").write_text(log, encoding="utf-8")
        return standardize_result(False, "build_fail", {"build_dir": str(build_dir), "log": log})

    # 6) CTest (per-test execution, continue-on-fail)
    timeout_sec = int(os.environ.get("CTEST_TIMEOUT_SEC", "120") or "120")
    ctest_results: List[Dict[str, Any]] = []

    # 6.1) Discover test names (ctest -N). If discovery fails, fall back to one-shot ctest.
    list_cmd = ["ctest", "-N"]
    cL, oL, eL = tools.run_command(
        list_cmd,
        cwd=build_dir,
        timeout=120,
        env=env if need_host else None,
    )
    discovered: List[str] = []
    for line in (f"{oL}\n{eL}\n").splitlines():
        m = re.search(r"Test\s+#\d+:\s+(.+?)\s*$", line)
        if m:
            name = m.group(1).strip()
            if name:
                discovered.append(name)

    if not discovered:
        discovered = ["__all__"]

    # 6.2) Run each test individually so a hang/crash does not block the rest.
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

        # Give enough time budget for a single test run.
        per_timeout = max(300, timeout_sec + 120)
        cT, oT, eT = tools.run_command(
            cmd,
            cwd=build_dir,
            timeout=per_timeout,
            env=env if need_host else None,
        )
        out_text = f"{ts_header}=== CTest Run @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n{oT}\n{eT}\n"

        # Persist each test output for triage and GUI display.
        safe_name = name.replace("/", "_").replace("\\", "_")
        out_path = tests_dir / (f"ctest_{safe_name}.txt" if name != "__all__" else "ctest_all.txt")
        try:
            out_path.write_text(out_text, encoding="utf-8")
        except Exception:
            pass

        status = "pass" if cT == 0 else ("timeout" if "Timeout" in out_text or "TIMEOUT" in out_text else "fail")
        ctest_results.append(
            {
                "name": None if name == "__all__" else name,
                "exit_code": int(cT),
                "status": status,
                "output": str(out_path),
            }
        )

        log += f"\n--- CTest: {name} ---\n{oT}\n{eT}\n"

    # 6.3) Overall test outcome
    if len(ctest_results) == 1 and ctest_results[0].get("name") is None:
        tests_ok = (ctest_results[0].get("exit_code", 1) == 0)
    else:
        tests_ok = all(r.get("exit_code", 1) == 0 for r in ctest_results if r.get("name") is not None)

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
        "coverage_enabled": bool(do_coverage),
        "ctest_exit_code": int(c3),
        "ctest_results": ctest_results,
        "triage": triage,
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
