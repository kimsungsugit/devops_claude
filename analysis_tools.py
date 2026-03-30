# /app/analysis_tools.py
# -*- coding: utf-8 -*-
"""
Helper module for DevOps Workflow (v31.2)
- 공통 subprocess 실행 래퍼 + 아티팩트 로그(명령/STDOUT/STDERR) 저장
- libFuzzer 실행(compile/run) 상세 로그/결과 JSON 저장
- QEMU smoke test 상세 로그/결과 저장
- (선택) 헤더/빌드 분석을 위한 include path helper
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Sequence

import config  # type: ignore  # 프로젝트 config (있으면 사용)

CODE_BLOCK_RE = re.compile(r"```(cmake|bash|c|cpp|json)\n(.*?)\n```", re.S)


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def get_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _tail(text: str, n: int = 40) -> str:
    lines = (text or "").splitlines()
    if len(lines) <= n:
        return "\n".join(lines)
    return "\n".join(lines[-n:])


def _safe_write(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text or "", encoding="utf-8", errors="ignore")


def _cmd_to_str(cmd: Sequence[str] | str) -> str:
    if isinstance(cmd, str):
        return cmd
    return " ".join(shlex.quote(str(x)) for x in cmd)


def run_command(
    cmd: Sequence[str] | str,
    cwd: Optional[Path] = None,
    timeout: int = 300,
    env: Optional[Dict[str, str]] = None,
    *,
    artifact_dir: Optional[Path] = None,
    artifact_prefix: Optional[str] = None,
    return_meta: bool = False,
) -> Any:
    """
    공통 쉘 실행 래퍼 (하위호환 유지)

    기본 반환:
      (returncode, stdout, stderr)

    return_meta=True 인 경우:
      (returncode, stdout, stderr, meta)

    meta:
      - cmd_str, cwd, timeout, started_at, finished_at
      - stdout_path, stderr_path (artifact_dir 사용 시)
    """
    if isinstance(cmd, str):
        popen_cmd: Any = cmd
        use_shell = True
    else:
        popen_cmd = list(cmd)
        use_shell = False

    meta: Dict[str, Any] = {
        "cmd_str": _cmd_to_str(cmd),
        "cwd": str(cwd) if cwd else "",
        "timeout": timeout,
        "started_at": _now_iso(),
        "finished_at": "",
        "stdout_path": "",
        "stderr_path": "",
        "timed_out": False,
    }

    def _maybe_artifact(out: str, err: str) -> None:
        if artifact_dir and artifact_prefix:
            ensure_dir(artifact_dir)
            out_p = artifact_dir / f"{artifact_prefix}.stdout.log"
            err_p = artifact_dir / f"{artifact_prefix}.stderr.log"
            _safe_write(out_p, out)
            _safe_write(err_p, err)
            meta["stdout_path"] = str(out_p)
            meta["stderr_path"] = str(err_p)

            cmd_p = artifact_dir / f"{artifact_prefix}.cmd.txt"
            _safe_write(cmd_p, meta["cmd_str"] + ("\n" if meta["cmd_str"] else ""))

            meta_p = artifact_dir / f"{artifact_prefix}.meta.json"
            _safe_write(meta_p, json.dumps(meta, ensure_ascii=False, indent=2))

    try:
        proc = subprocess.run(
            popen_cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=use_shell,
        )
        out = proc.stdout or ""
        err = proc.stderr or ""
        meta["finished_at"] = _now_iso()
        _maybe_artifact(out, err)

        if return_meta:
            return proc.returncode, out, err, meta
        return proc.returncode, out, err

    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "")  # type: ignore[arg-type]
        err = (e.stderr or "")
        err = (err or "") + f"\n[TIMEOUT after {timeout}s]\nCMD: {meta['cmd_str']}"
        meta["finished_at"] = _now_iso()
        meta["timed_out"] = True
        _maybe_artifact(out, err)

        if return_meta:
            return 124, out, err, meta
        return 124, out, err

    except Exception as e:
        meta["finished_at"] = _now_iso()
        err = f"[EXCEPTION] {e}\nCMD: {meta['cmd_str']}"
        _maybe_artifact("", err)

        if return_meta:
            return 1, "", err, meta
        return 1, "", err



def which(name: str) -> Optional[str]:
    result = shutil.which(name)
    if result:
        return result
    import sys
    scripts_dir = Path(sys.executable).parent / "Scripts"
    if scripts_dir.is_dir():
        candidate = scripts_dir / (name + ".exe" if os.name == "nt" else name)
        if candidate.is_file():
            return str(candidate)
    return None


def is_arm_toolchain() -> bool:
    return bool(which("arm-none-eabi-gcc"))


def find_pico_sdk_path(project_root: str) -> str:
    if os.environ.get("PICO_SDK_PATH") and os.path.isdir(os.environ["PICO_SDK_PATH"]):
        return os.environ["PICO_SDK_PATH"]

    root = Path(project_root)
    candidates = [
        root / "libs" / "pico-sdk",
        root / "pico-sdk",
        root / "external" / "pico-sdk",
    ]
    if os.name != "nt":
        candidates.append(Path("/opt/pico-sdk"))
    for p in candidates:
        if (p / "pico_sdk_init.cmake").exists():
            return str(p)
    return ""


def get_arch_include_paths(target_arch: str, project_root: str) -> List[str]:
    """
    target_arch 기반 include 후보 경로 생성
    - RP2040 / Pico SDK: pico-sdk include path
    - STM32/CMSIS 등: 프로젝트 내부에서 흔히 쓰는 HAL/CMSIS 경로 탐색
    """
    paths: List[str] = []
    root = Path(project_root)
    t_arch = (target_arch or "").lower()

    if "rp2040" in t_arch or "cortex-m0plus" in t_arch:
        sdk_path = find_pico_sdk_path(project_root)
        if sdk_path:
            p = Path(sdk_path)
            paths.extend(
                [
                    str(p / "src/common/pico_base/include"),
                    str(p / "src/common/pico_stdlib/include"),
                    str(p / "src/common/pico_sync/include"),
                    str(p / "src/common/pico_time/include"),
                    str(p / "src/common/pico_util/include"),
                    str(p / "src/common/pico_binary_info/include"),
                    str(p / "src/rp2_common/pico_platform/include"),
                    str(p / "src/rp2_common/hardware_base/include"),
                    str(p / "src/rp2_common/hardware_gpio/include"),
                    str(p / "src/rp2_common/hardware_uart/include"),
                    str(p / "src/rp2_common/hardware_irq/include"),
                    str(p / "src/rp2_common/hardware_adc/include"),
                    str(p / "src/rp2_common/hardware_pio/include"),
                    str(p / "src/rp2_common/hardware_dma/include"),
                    str(p / "src/rp2_common/hardware_timer/include"),
                    str(p / "src/rp2_common/hardware_clocks/include"),
                    str(p / "src/rp2_common/hardware_spi/include"),
                    str(p / "src/rp2_common/hardware_i2c/include"),
                    str(p / "src/rp2_common/hardware_flash/include"),
                    str(p / "src/rp2_common/hardware_watchdog/include"),
                    str(p / "src/boards/include"),
                ]
            )
            tinyusb = p / "lib/tinyusb/src"
            if tinyusb.exists():
                paths.append(str(tinyusb))

    if "stm32" in t_arch or "nxp" in t_arch or "nrf" in t_arch or "cortex-m" in t_arch:
        paths.extend([str(d) for d in root.rglob("STM32*_HAL_Driver/Inc") if d.is_dir()])
        paths.extend([str(d) for d in root.rglob("CMSIS/Include") if d.is_dir()])

    # 유니크 정렬
    return sorted(list(set(x for x in paths if x)))


def _is_mingw_clang() -> bool:
    """Detect if clang targets MinGW (x86_64-w64-windows-gnu) which lacks -fsanitize=fuzzer."""
    if os.name != "nt":
        return False
    try:
        c, o, e = run_command(["clang", "--version"], timeout=15)
        combined = (o or "") + (e or "")
        return "windows-gnu" in combined.lower()
    except Exception:
        return False


_DUMB_FUZZER_DRIVER_TEMPLATE = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <signal.h>

extern int LLVMFuzzerTestOneInput(const unsigned char *data, unsigned long size);

static volatile int g_crash_detected = 0;
static const char *g_crash_type = "unknown";

static void crash_handler(int sig) {
    const char *name = "SIGNAL";
    if (sig == SIGSEGV) name = "SEGV";
    else if (sig == SIGABRT) name = "ABORT";
    else if (sig == SIGFPE) name = "FPE";
    else if (sig == SIGILL) name = "ILL";
    fprintf(stderr, "\n=== CRASH DETECTED: %s (signal %d) ===\n", name, sig);
    _exit(77);
}

int main(int argc, char **argv) {
    int duration_sec = 10;
    int max_len = 4096;
    if (argc > 1) duration_sec = atoi(argv[1]);
    if (argc > 2) max_len = atoi(argv[2]);
    if (duration_sec <= 0) duration_sec = 10;
    if (max_len <= 0 || max_len > 65536) max_len = 4096;

    signal(SIGSEGV, crash_handler);
    signal(SIGABRT, crash_handler);
    signal(SIGFPE, crash_handler);
    signal(SIGILL, crash_handler);

    unsigned char *buf = (unsigned char *)malloc(max_len);
    if (!buf) { fprintf(stderr, "OOM\n"); return 1; }

    srand((unsigned)time(NULL));
    time_t start = time(NULL);
    unsigned long iterations = 0;

    /* Phase 1: edge cases */
    unsigned char empty = 0;
    LLVMFuzzerTestOneInput(&empty, 0);
    iterations++;
    memset(buf, 0, max_len);
    LLVMFuzzerTestOneInput(buf, max_len);
    iterations++;
    memset(buf, 0xFF, max_len);
    LLVMFuzzerTestOneInput(buf, max_len);
    iterations++;

    /* Phase 2: random inputs */
    while (difftime(time(NULL), start) < duration_sec) {
        int len = rand() % (max_len + 1);
        for (int j = 0; j < len; j++) buf[j] = (unsigned char)(rand() % 256);
        LLVMFuzzerTestOneInput(buf, (unsigned long)len);
        iterations++;
    }

    free(buf);
    fprintf(stderr, "FUZZ_SUMMARY: iterations=%lu duration=%ds\n", iterations, duration_sec);
    printf("OK: %lu iterations completed in %d seconds\n", iterations, duration_sec);
    return 0;
}
"""


def run_libfuzzer(
    harness_path: Path,
    source_files: List[Path],
    include_dirs: List[str],
    work_dir: Path,
    duration_sec: Optional[int] = None,
    artifact_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """
    libFuzzer 기반 Fuzz 실행 (로그/아티팩트 강화)
    MinGW clang 환경에서는 -fsanitize=fuzzer 미지원이므로
    UBSan + dumb fuzzer 드라이버로 자동 대체.
    """
    if not which("clang"):
        return {"ok": False, "reason": "clang_not_found"}

    if duration_sec is None:
        duration_sec = getattr(config, "FUZZ_DEFAULT_DURATION", 30)

    ensure_dir(work_dir)

    prefix = artifact_prefix or "fuzz_target"
    bin_path = work_dir / prefix
    if os.name == "nt":
        bin_path = work_dir / f"{prefix}.exe"

    compile_cmd_path = work_dir / f"{prefix}_compile.cmd.txt"
    compile_out_path = work_dir / f"{prefix}_compile.stdout.log"
    compile_err_path = work_dir / f"{prefix}_compile.stderr.log"
    run_out_path = work_dir / f"{prefix}_run.stdout.log"
    run_err_path = work_dir / f"{prefix}_run.stderr.log"
    result_path = work_dir / f"{prefix}_result.json"

    use_dumb_fuzzer = _is_mingw_clang()

    if use_dumb_fuzzer:
        driver_path = work_dir / f"{prefix}_driver.c"
        try:
            driver_path.write_text(_DUMB_FUZZER_DRIVER_TEMPLATE, encoding="utf-8")
        except Exception:
            pass

        cmd_compile: List[str] = [
            "clang", "-g", "-O1",
            "-fsanitize=undefined",
            "-fsanitize-trap=all",
            "-fstack-protector-all",
            str(driver_path),
            str(harness_path),
        ]
    else:
        sanitize_flags = "-fsanitize=fuzzer,address"
        if os.name == "nt":
            sanitize_flags = "-fsanitize=fuzzer"
        cmd_compile = [
            "clang", "-g", "-O1",
            sanitize_flags,
            str(harness_path),
        ]

    for src in source_files:
        cmd_compile.append(str(src))

    for inc in include_dirs:
        if inc:
            cmd_compile.append(f"-I{inc}")

    cmd_compile.extend([
        "-DHOST_BUILD",
        "-DUNIT_TEST",
        "-DFUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION",
        "-o", str(bin_path),
    ])

    try:
        compile_cmd_path.write_text(" ".join(shlex.quote(x) for x in cmd_compile) + "\n", encoding="utf-8")
    except Exception:
        pass

    c, o, e = run_command(cmd_compile, cwd=work_dir)
    try:
        compile_out_path.write_text(o or "", encoding="utf-8")
        compile_err_path.write_text(e or "", encoding="utf-8")
    except Exception:
        pass

    if c != 0:
        res = {
            "ok": False,
            "stage": "compile",
            "exit_code": c,
            "harness": str(harness_path),
            "binary": str(bin_path),
            "mode": "dumb_fuzzer" if use_dumb_fuzzer else "libfuzzer",
            "artifacts": {
                "compile_cmd_path": str(compile_cmd_path),
                "compile_stdout_path": str(compile_out_path),
                "compile_stderr_path": str(compile_err_path),
                "run_stdout_path": str(run_out_path),
                "run_stderr_path": str(run_err_path),
                "result_path": str(result_path),
            },
        }
        try:
            result_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return res

    if use_dumb_fuzzer:
        cmd_run = [str(bin_path), str(duration_sec), "4096"]
    else:
        cmd_run = [str(bin_path), f"-max_total_time={duration_sec}"]

    c_run, o_run, e_run = run_command(
        cmd_run,
        cwd=work_dir,
        timeout=int(duration_sec) + 30,
    )

    try:
        run_out_path.write_text(o_run or "", encoding="utf-8")
        run_err_path.write_text(e_run or "", encoding="utf-8")
    except Exception:
        pass

    crash_found = c_run != 0
    crash_files: List[str] = []
    if crash_found:
        try:
            for cf in work_dir.glob("crash-*"):
                crash_files.append(str(cf))
            for cf in work_dir.glob("oom-*"):
                crash_files.append(str(cf))
            for cf in work_dir.glob("timeout-*"):
                crash_files.append(str(cf))
        except OSError:
            pass

    iterations = 0
    if use_dumb_fuzzer:
        import re as _re
        m = _re.search(r"iterations=(\d+)", (e_run or "") + (o_run or ""))
        if m:
            iterations = int(m.group(1))

    res = {
        "ok": True,
        "crash_found": crash_found,
        "crash_files": crash_files,
        "exit_code": c_run,
        "harness": str(harness_path),
        "binary": str(bin_path),
        "duration_sec": duration_sec,
        "mode": "dumb_fuzzer" if use_dumb_fuzzer else "libfuzzer",
        "iterations": iterations,
        "artifacts": {
            "compile_cmd_path": str(compile_cmd_path),
            "compile_stdout_path": str(compile_out_path),
            "compile_stderr_path": str(compile_err_path),
            "run_stdout_path": str(run_out_path),
            "run_stderr_path": str(run_err_path),
            "result_path": str(result_path),
        },
    }
    try:
        result_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return res

# ------------------------------------------------------------
# QEMU helpers
# ------------------------------------------------------------
_QEMU_MACHINE_LIST_CACHE: Optional[List[str]] = None


def _recommend_qemu_machine(target_arch: Optional[str], machines: List[str]) -> Tuple[str, str]:
    preferred = _select_qemu_machine(target_arch)
    if not machines:
        return preferred, "no_machine_list"
    if target_arch and ("rp2040" in target_arch.lower() or "cortex-m0plus" in target_arch.lower()) and not preferred:
        return "", "rp2040_no_qemu_machine"
    if preferred in machines:
        return preferred, "match"
    # Fallback to first available machine
    hint = "not_available"
    if target_arch and ("rp2040" in target_arch.lower() or "cortex-m0plus" in target_arch.lower()):
        hint = "rp2040_no_qemu_machine"
    return machines[0], hint


def check_qemu_env(target_arch: Optional[str] = None) -> Dict[str, Any]:
    qemu_path = which("qemu-system-arm") or which("qemu-system-aarch64")
    if not qemu_path:
        return {"ok": False, "reason": "qemu_not_found", "qemu_path": "", "machines": [], "selected": ""}
    machines = _list_qemu_machines()
    selected = _select_qemu_machine(target_arch)
    recommended, rec_reason = _recommend_qemu_machine(target_arch, machines)
    return {
        "ok": True,
        "reason": "ok",
        "qemu_path": qemu_path,
        "machines": machines,
        "selected": selected,
        "recommended": recommended,
        "recommend_reason": rec_reason,
    }


def _list_qemu_machines() -> List[str]:
    global _QEMU_MACHINE_LIST_CACHE
    if _QEMU_MACHINE_LIST_CACHE is not None:
        return _QEMU_MACHINE_LIST_CACHE

    if not which("qemu-system-arm"):
        _QEMU_MACHINE_LIST_CACHE = []
        return _QEMU_MACHINE_LIST_CACHE

    try:
        proc = subprocess.run(
            ["qemu-system-arm", "-machine", "help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
        )
        out = proc.stdout or ""
        machines: List[str] = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if parts:
                name = parts[0].strip()
                if name and name not in machines:
                    machines.append(name)
        _QEMU_MACHINE_LIST_CACHE = machines
        return machines
    except Exception:
        _QEMU_MACHINE_LIST_CACHE = []
        return _QEMU_MACHINE_LIST_CACHE


def _select_qemu_machine(target_arch: Optional[str] = None) -> str:
    env_machine = os.environ.get("QEMU_MACHINE", "").strip()
    if env_machine:
        return env_machine

    profile = (
        os.environ.get("DEVOPS_QEMU_PROFILE")
        or os.environ.get("QEMU_PROFILE")
        or getattr(config, "DEFAULT_QEMU_PROFILE", "")
    ).strip()

    machines_by_profile = getattr(config, "QEMU_PROFILE_MACHINES", {}) or {}
    machines_by_arch = getattr(config, "QEMU_MACHINE_BY_ARCH", {}) or {}

    candidates: List[str] = []
    if profile and isinstance(machines_by_profile, dict):
        cand = machines_by_profile.get(profile)
        if isinstance(cand, list):
            candidates.extend([str(x) for x in cand if str(x).strip()])

    if target_arch and isinstance(machines_by_arch, dict):
        cand = machines_by_arch.get(target_arch)
        if isinstance(cand, list):
            candidates.extend([str(x) for x in cand if str(x).strip()])

    if target_arch and ("rp2040" in target_arch.lower() or "cortex-m0plus" in target_arch.lower()) and not candidates:
        return ""

    default_machine = getattr(config, "QEMU_MACHINE", "lm3s6965evb")
    candidates.append(str(default_machine))

    available = set(_list_qemu_machines())
    if available:
        for c in candidates:
            if c in available:
                return c
    return candidates[0] if candidates else "lm3s6965evb"


def run_qemu_smoke_test(
    elf_path: Path,
    machine: Optional[str] = None,
    target_arch: Optional[str] = None,
    *,
    artifact_dir: Optional[Path] = None,
    artifact_prefix: str = "qemu_smoke",
) -> Dict[str, Any]:
    """
    QEMU 기반 간단 Smoke Test
    - 로그/명령/STDOUT/STDERR 아티팩트 저장
    """
    if not which("qemu-system-arm"):
        return {"ok": False, "reason": "qemu_not_found", "crashed": False}

    env_machine = os.environ.get("QEMU_MACHINE", "").strip()
    machine = env_machine or machine or _select_qemu_machine(target_arch)

    extra_args_str = os.environ.get("QEMU_EXTRA_ARGS", "")
    extra_args: List[str] = []
    if extra_args_str.strip():
        try:
            extra_args = shlex.split(extra_args_str)
        except Exception:
            extra_args = extra_args_str.split()

    cmd = [
        "qemu-system-arm",
        "-M",
        machine,
        "-kernel",
        str(elf_path),
        "-nographic",
        "-semihosting",
        "-d",
        "guest_errors,unimp",
        "-D",
        "qemu.log",
    ] + extra_args

    c, o, e, meta = run_command(
        cmd,
        cwd=elf_path.parent,
        timeout=10,
        artifact_dir=artifact_dir,
        artifact_prefix=artifact_prefix,
        return_meta=True,
    )
    log = (o or "") + (e or "")

    ok = c == 0
    crashed = not ok

    patterns = getattr(config, "QEMU_LOG_ERROR_PATTERNS", [])
    for pat in patterns:
        if pat and pat in log:
            ok = False
            crashed = True
            break

    res = {
        "ok": ok,
        "crashed": crashed,
        "exit_code": c,
        "machine": machine,
        "cmd": meta.get("cmd_str", ""),
        "stdout_path": meta.get("stdout_path", ""),
        "stderr_path": meta.get("stderr_path", ""),
        "tail": _tail(log, 60) if not ok else "",
    }
    return res


def run_doxygen(project_root: Path, output_dir: Path) -> Dict[str, Any]:
    """Run Doxygen if Doxyfile exists or generate a default one.

    Args:
        project_root: project root containing Doxyfile (or where to create it)
        output_dir: directory where HTML will be generated (e.g., <root>/reports/docs)
    """
    if not which("doxygen"):
        return {"ok": False, "reason": "doxygen_not_found", "message": "doxygen not found in PATH. Install: https://www.doxygen.nl/download.html"}
    
    cfg_path = project_root / "Doxyfile"
    
    # Doxyfile이 없으면 기본 설정으로 생성
    if not cfg_path.exists():
        print(f"[doxygen] Doxyfile not found, generating default configuration...")
        try:
            # output_dir을 project_root 기준 상대 경로로 변환
            try:
                output_dir_resolved = output_dir.resolve()
                project_root_resolved = project_root.resolve()
                if output_dir_resolved.is_relative_to(project_root_resolved):
                    out_dir_rel = str(output_dir_resolved.relative_to(project_root_resolved)).replace("\\", "/")
                else:
                    out_dir_rel = "docs"  # 기본값
            except Exception:
                out_dir_rel = "docs"
            
            default_doxyfile = f"""# Doxygen 설정 파일 (자동 생성)
PROJECT_NAME           = "{project_root.name}"
PROJECT_NUMBER         = 
PROJECT_BRIEF          = 
OUTPUT_DIRECTORY       = {out_dir_rel}
INPUT                  = . libs
INPUT_ENCODING         = UTF-8
FILE_PATTERNS          = *.c *.h *.cpp *.hpp
RECURSIVE              = YES
EXTRACT_ALL            = YES
EXTRACT_PRIVATE        = NO
EXTRACT_STATIC         = YES
GENERATE_HTML          = YES
GENERATE_LATEX         = NO
HTML_OUTPUT            = html
USE_MDFILE_AS_MAINPAGE = 
QUIET                  = NO
WARNINGS               = YES
WARN_IF_UNDOCUMENTED   = YES
"""
            cfg_path.write_text(default_doxyfile, encoding="utf-8")
            print(f"[doxygen] Created default Doxyfile at {cfg_path}")
        except Exception as e:
            return {"ok": False, "reason": "doxyfile_create_failed", "error": str(e)}

    # Compute OUTPUT_DIRECTORY relative to project_root when possible (Doxygen prefers relative)
    try:
        project_root = project_root.resolve()
        output_dir = output_dir.resolve()
        try:
            rel = output_dir.relative_to(project_root)
        except ValueError:
            rel = output_dir
        out_dir_str = str(rel).replace("\\", "/")
    except Exception:
        out_dir_str = output_dir.name

    tmp_cfg = project_root / "Doxyfile.__auto__.tmp"
    content = cfg_path.read_text(encoding="utf-8", errors="ignore")

    # Remove any existing OUTPUT_DIRECTORY lines
    content = re.sub(r"^\s*OUTPUT_DIRECTORY\s*=.*$", "", content, flags=re.MULTILINE)

    content += (
        f"\nOUTPUT_DIRECTORY = {out_dir_str}\n"
        f"RECURSIVE = YES\n"
        f"EXTRACT_ALL = YES\n"
        f"GENERATE_LATEX = NO\n"
    )
    tmp_cfg.write_text(content, encoding="utf-8")

    code, out, err = run_command(["doxygen", str(tmp_cfg)], cwd=project_root, timeout=600)
    try:
        tmp_cfg.unlink()
    except FileNotFoundError:
        pass

    return {"ok": code == 0, "stdout": out, "stderr": err}


def generate_coverage_report(project_root: Path, reports_dir: Path, build_dir: Path) -> Dict[str, Any]:
    """Generate coverage report using gcovr (XML + HTML-details).

    Returns:
        dict: {"ok": bool, "reason": str, "xml": str, "html": str, "build_dir": str, "gcda_files": List[str]}
    """
    res: Dict[str, Any] = {
        "ok": False,
        "reason": "",
        "xml": "",
        "html": "",
        "build_dir": str(build_dir),
        "gcda_files": [],
        "auto_install": False,
    }
    gcovr_cmd: Optional[List[str]] = None
    gcovr_path = which("gcovr")
    if gcovr_path:
        gcovr_cmd = [gcovr_path]
    if gcovr_cmd is None:
        try:
            c, out, err = run_command([sys.executable, "-m", "gcovr", "--version"], cwd=project_root, timeout=20)
            if c == 0:
                gcovr_cmd = [sys.executable, "-m", "gcovr"]
        except Exception:
            pass
    if gcovr_cmd is None:
        if bool(getattr(config, "AUTO_INSTALL_GCOVR", True)):
            res["auto_install"] = True
            try:
                c, out, err = run_command(
                    [sys.executable, "-m", "pip", "install", "gcovr"],
                    cwd=project_root,
                    timeout=300,
                )
                if c != 0:
                    print(f"[coverage] Auto-install gcovr failed: {err or out}")
            except Exception as e:
                print(f"[coverage] Auto-install gcovr exception: {e}")
        try:
            c, out, err = run_command([sys.executable, "-m", "gcovr", "--version"], cwd=project_root, timeout=20)
            if c == 0:
                gcovr_cmd = [sys.executable, "-m", "gcovr"]
        except Exception:
            gcovr_cmd = None
        if gcovr_cmd is None:
            res["reason"] = "gcovr_not_found"
            print(f"[coverage] gcovr not found in PATH. Please install gcovr to generate coverage reports.")
            return res
    
    # .gcda 파일 검색 및 상세 로깅
    gcda_files = list(build_dir.rglob("*.gcda"))
    res["gcda_files"] = [str(f.relative_to(build_dir)) for f in gcda_files]
    
    if not gcda_files:
        res["reason"] = "no_gcda"
        print(f"[coverage] No .gcda files found in build directory: {build_dir}")
        print(f"[coverage] Build directory exists: {build_dir.exists()}")
        if build_dir.exists():
            # 빌드 디렉토리 내용 확인
            subdirs = [d.name for d in build_dir.iterdir() if d.is_dir()]
            print(f"[coverage] Build directory subdirectories: {subdirs[:10]}")  # 처음 10개만
            # CMakeCache.txt 확인
            cmake_cache = build_dir / "CMakeCache.txt"
            if cmake_cache.exists():
                try:
                    cache_content = cmake_cache.read_text(encoding="utf-8", errors="ignore")
                    if "DEVOPS_COVERAGE:BOOL=ON" in cache_content:
                        print(f"[coverage] CMakeCache.txt shows DEVOPS_COVERAGE=ON")
                    else:
                        print(f"[coverage] CMakeCache.txt shows DEVOPS_COVERAGE=OFF or not set")
                except Exception:
                    pass
        return res

    cov_dir = reports_dir / "coverage"
    ensure_dir(cov_dir)

    proj_root = str(project_root).replace("\\", "/")
    reports_root = str(reports_dir).replace("\\", "/")
    build_root = str(build_dir).replace("\\", "/")
    stubs_root = str(project_root / "tests" / "stubs").replace("\\", "/")
    main_src = str(project_root / "main.c").replace("\\", "/")
    auto_gen_root = str(reports_dir / "auto_generated").replace("\\", "/")
    base_cmd = list(gcovr_cmd)
    base_cmd += [
        "-r",
        proj_root,
        "--merge-mode-functions=merge-use-line-min",
        "--exclude",
        stubs_root,
        "--exclude",
        main_src,
        "--exclude",
        auto_gen_root + "/.*",
    ]

    xml_out = str(cov_dir / "coverage.xml").replace("\\", "/")
    html_out = str(cov_dir / "index.html").replace("\\", "/")
    # XML
    c_xml, o_xml, e_xml = run_command(base_cmd + ["--xml", "-o", xml_out], cwd=build_dir, timeout=120)
    if c_xml != 0:
        print(f"[coverage] gcovr XML generation failed (exit={c_xml}): {e_xml or o_xml}")
        res["reason"] = "gcovr_xml_fail"
        res["error"] = (e_xml or o_xml)[:2000]
    # HTML (try multiple flag variants across gcovr versions)
    html_cmd_variants: List[List[str]] = [
        base_cmd + ["--html-details", "--output", html_out],
        base_cmd + ["--html-details", "-o", html_out],
        base_cmd + ["--html", "--html-details", "--output", html_out],
        base_cmd + ["--html-details", f"--html={html_out}"],
    ]
    html_ok = False
    last_html_err = ""
    for cmd in html_cmd_variants:
        c, o_html, e_html = run_command(cmd, cwd=build_dir, timeout=120)
        if c == 0 and Path(html_out).exists():
            html_ok = True
            break
        last_html_err = e_html or o_html
    if not html_ok:
        print(f"[coverage] gcovr HTML generation failed: {last_html_err}")
    
    xml_exists = Path(xml_out).exists() and Path(xml_out).stat().st_size > 0
    html_exists = Path(html_out).exists()
    if xml_exists:
        res.update({"ok": True, "xml": xml_out, "html": html_out if html_exists else ""})
    elif c_xml == 0:
        res["reason"] = "gcovr_empty_output"
    return res
