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
    return shutil.which(name)


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
        Path("/opt/pico-sdk"),  # 컨테이너 기본 경로(있는 경우)
    ]
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
    - harness_path: LLVMFuzzerTestOneInput를 포함한 harness C/C++ 파일
    - source_files: 함께 컴파일할 추가 소스들
    - include_dirs: -I로 추가할 include 경로들 (앞쪽일수록 우선)
    - work_dir: 빌드/실행 작업 디렉터리
    - duration_sec: fuzz 러닝 시간 (없으면 config.FUZZ_DEFAULT_DURATION 사용)
    - artifact_prefix: 아티팩트 파일명 prefix (없으면 fuzz_target)
    """
    if not which("clang"):
        return {"ok": False, "reason": "clang_not_found"}

    if duration_sec is None:
        duration_sec = getattr(config, "FUZZ_DEFAULT_DURATION", 30)

    ensure_dir(work_dir)

    prefix = artifact_prefix or "fuzz_target"
    bin_path = work_dir / prefix

    compile_cmd_path = work_dir / f"{prefix}_compile.cmd.txt"
    compile_out_path = work_dir / f"{prefix}_compile.stdout.log"
    compile_err_path = work_dir / f"{prefix}_compile.stderr.log"
    run_out_path = work_dir / f"{prefix}_run.stdout.log"
    run_err_path = work_dir / f"{prefix}_run.stderr.log"
    result_path = work_dir / f"{prefix}_result.json"

    cmd_compile: List[str] = [
        "clang",
        "-g",
        "-O1",
        "-fsanitize=fuzzer,address",
        str(harness_path),
    ]

    for src in source_files:
        cmd_compile.append(str(src))

    for inc in include_dirs:
        if inc:
            cmd_compile.append(f"-I{inc}")

    cmd_compile.extend(
        [
            "-DHOST_BUILD",
            "-DUNIT_TEST",
            "-DFUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION",
            "-o",
            str(bin_path),
        ]
    )

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

    cmd_run = [str(bin_path), f"-max_total_time={duration_sec}"]
    c_run, o_run, e_run = run_command(
        cmd_run,
        cwd=work_dir,
        timeout=int(duration_sec) + 10,
    )

    try:
        run_out_path.write_text(o_run or "", encoding="utf-8")
        run_err_path.write_text(e_run or "", encoding="utf-8")
    except Exception:
        pass

    crash_found = c_run != 0
    res = {
        "ok": True,
        "crash_found": crash_found,
        "exit_code": c_run,
        "harness": str(harness_path),
        "binary": str(bin_path),
        "duration_sec": duration_sec,
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
    """Run Doxygen if Doxyfile exists.

    Args:
        project_root: project root containing Doxyfile
        output_dir: directory where HTML will be generated (e.g., <root>/reports/docs)
    """
    cfg_path = project_root / "Doxyfile"
    if not cfg_path.exists():
        return {"ok": False, "reason": "doxyfile_not_found"}
    if not which("doxygen"):
        return {"ok": False, "reason": "doxygen_not_found"}

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
        dict: {"ok": bool, "reason": str, "xml": str, "html": str}
    """
    res: Dict[str, Any] = {"ok": False, "reason": "", "xml": "", "html": ""}
    if not which("gcovr"):
        res["reason"] = "gcovr_not_found"
        return res
    if not list(build_dir.rglob("*.gcda")):
        res["reason"] = "no_gcda"
        return res

    cov_dir = reports_dir / "coverage"
    ensure_dir(cov_dir)

    base_cmd = [
        "gcovr",
        "-r",
        str(project_root),
        "--exclude",
        str(reports_dir),
        "--exclude",
        str(build_dir),
    ]

    # XML
    run_command(base_cmd + ["--xml", "-o", str(cov_dir / "coverage.xml")], cwd=build_dir)
    # HTML
    c, _, _ = run_command(
        base_cmd + ["--html-details", "-o", str(cov_dir / "index.html")],
        cwd=build_dir,
    )
    if c == 0:
        res.update(
            {"ok": True, "xml": str(cov_dir / "coverage.xml"), "html": str(cov_dir / "index.html")}
        )
    else:
        res["reason"] = "gcovr_html_fail"
    return res