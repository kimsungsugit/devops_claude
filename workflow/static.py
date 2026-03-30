# /app/workflow/static.py
import json
import os
import re
import time as _time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from xml.etree import ElementTree as ET
import analysis_tools as tools
from .common import Issue, standardize_result

_DEFAULT_TOTAL_TIMEOUT = 3600


def parse_clang_tidy_output(output: str, project_root: Path) -> List[Issue]:
    issues = []
    regex = re.compile(r"^([^:\n]+):(\d+):\d+:\s+(\w+):\s+(.*)\s+\[(.*)\]$")
    for line in output.splitlines():
        match = regex.match(line)
        if match:
            fpath, lineno, sev, msg, cid = match.groups()
            try:
                abs_p = Path(fpath)
                if abs_p.is_absolute() and str(project_root) in str(abs_p):
                    fpath = str(abs_p.relative_to(project_root))
            except (ValueError, OSError):
                pass
            issues.append(Issue(file=fpath, line=int(lineno), severity=sev, message=msg, id=cid, tool="clang-tidy"))
    return issues

def run_clang_tidy(project_root: Path, targets: List[Path], checks: List[str], build_dir: Path, cb: Optional[Callable] = None, max_total_sec: int = _DEFAULT_TOTAL_TIMEOUT) -> Dict[str, Any]:
    if not tools.which("clang-tidy"): return standardize_result(False, "clang_tidy_not_found")
    if not (build_dir / "compile_commands.json").exists(): return standardize_result(False, "no_compile_commands")
    
    check_str = ",".join(checks) if checks else "bugprone-*,performance-*"
    all_issues = []
    total = len(targets)
    t0 = _time.monotonic()
    skipped = 0
    for i, t in enumerate(targets):
        if (_time.monotonic() - t0) > max_total_sec:
            skipped = total - i
            break
        if cb: cb(i + 1, total, f"Clang-Tidy: {t.name}")
        if t.suffix not in ('.c', '.cpp'): continue
        cmd = ["clang-tidy", "-p", str(build_dir), f"-checks=-*,{check_str}", str(t), f"--header-filter={str(project_root)}/.*"]
        _, out, _ = tools.run_command(cmd, cwd=project_root, timeout=300)
        all_issues.extend(parse_clang_tidy_output(out, project_root))
    reason = "completed" if skipped == 0 else f"partial_timeout_{skipped}_skipped"
    return standardize_result(True, reason, {"issues": [asdict(i) for i in all_issues]})


def _parse_semgrep_results(payload: Dict[str, Any], project_root: Path) -> List[Issue]:
    issues: List[Issue] = []
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return issues
    for r in results:
        if not isinstance(r, dict):
            continue
        path = str(r.get("path") or "")
        start = r.get("start") if isinstance(r.get("start"), dict) else {}
        line = int(start.get("line") or 0)
        extra = r.get("extra") if isinstance(r.get("extra"), dict) else {}
        message = str(extra.get("message") or r.get("message") or "")
        severity = str(extra.get("severity") or r.get("severity") or "warning")
        rule = str(r.get("check_id") or r.get("rule_id") or "semgrep")
        try:
            abs_p = Path(path)
            if abs_p.is_absolute() and str(project_root) in str(abs_p):
                path = str(abs_p.relative_to(project_root))
        except Exception:
            pass
        issues.append(Issue(file=path, line=line, severity=severity, message=message, id=rule, tool="semgrep"))
    return issues


def run_semgrep(
    project_root: Path,
    reports_dir: Path,
    targets: List[Path],
    config_rule: str,
    cb: Optional[Callable] = None,
) -> Dict[str, Any]:
    if not tools.which("semgrep"):
        return standardize_result(False, "semgrep_not_found")

    sem_dir = reports_dir / "semgrep"
    tools.ensure_dir(sem_dir)
    if not targets:
        return standardize_result(True, "no_targets", {"issues": [], "json_path": ""})

    rel_targets = []
    for t in targets:
        try:
            rel_targets.append(str(t.relative_to(project_root)))
        except Exception:
            rel_targets.append(str(t))

    cmd = [
        "semgrep",
        "--quiet",
        "--json",
        "--config",
        config_rule or "p/default",
        "--no-git-ignore",
    ] + rel_targets

    c, out, err = tools.run_command(cmd, cwd=project_root, timeout=1200)
    json_path = sem_dir / "semgrep.json"
    try:
        json_path.write_text(out or "", encoding="utf-8")
    except Exception:
        pass

    raw_error = "\n".join([str(out or ""), str(err or "")]).strip()
    lowered_error = raw_error.lower()
    if (
        "certopensystemstore returned null" in lowered_error
        or "failed to create system store x509 authenticator" in lowered_error
    ):
        return standardize_result(
            True,
            "semgrep_runtime_env_error",
            {"stderr": raw_error, "json_path": str(json_path), "issues": []},
        )

    if c not in (0, 1):
        return standardize_result(False, "semgrep_failed", {"stderr": raw_error, "json_path": str(json_path)})

    try:
        payload = json.loads(out or "{}")
    except Exception:
        payload = {}
    issues = _parse_semgrep_results(payload if isinstance(payload, dict) else {}, project_root)
    return standardize_result(True, "completed", {"issues": [asdict(i) for i in issues], "json_path": str(json_path)})

def run_cppcheck(project_root: Path, reports_dir: Path, targets: List[Path], enable: List[str], incs: List[str], suppr: str, cb: Callable, arch: str, defs: List[str], max_total_sec: int = _DEFAULT_TOTAL_TIMEOUT) -> Dict[str, Any]:
    if not tools.which("cppcheck"): return standardize_result(False, "cppcheck_not_found")
    cpp_dir = reports_dir / "cppcheck"
    tools.ensure_dir(cpp_dir)
    tools.ensure_dir(reports_dir / "cppcheck_build_dir")
    
    enable_str = ",".join(enable) if enable else "warning,performance"
    issues, xml_paths, overall_ok = [], [], True
    inc_args = [f"-I{ip}" for ip in (incs or []) if ip]
    suppr_args = [f"--suppressions-list={suppr}"] if suppr and Path(suppr).exists() else []
    plat_args = [f"--cppcheck-build-dir={reports_dir}/cppcheck_build_dir"]
    if arch != "native" and tools.is_arm_toolchain():
        plat_args += ["-D__GNUC__", "-D__arm__"] + [f"-D{d.lstrip('-D')}" for d in (defs or [])]

    total = len(targets)
    t0 = _time.monotonic()
    skipped = 0
    for i, t in enumerate(targets):
        if (_time.monotonic() - t0) > max_total_sec:
            skipped = total - i
            break
        if cb: cb(i + 1, total, f"Cppcheck: {t.name}")
        xml_path = cpp_dir / f"{t.name}.xml"
        cmd = ["cppcheck", f"--enable={enable_str}", "--xml", "--xml-version=2", "--inline-suppr"] + plat_args + suppr_args + inc_args + [str(t.relative_to(project_root))]
        c, out, err = tools.run_command(cmd, cwd=project_root, timeout=600)
        
        xml_text = err
        if not xml_text or "<?xml" not in xml_text:
            xml_text = out if out and "<?xml" in out else ""
        
        try:
            xml_path.write_text(xml_text, encoding="utf-8")
            xml_paths.append(str(xml_path))
            if not xml_text.strip():
                continue
            root = ET.fromstring(xml_text)
            for err_node in root.findall(".//errors/error"):
                loc = err_node.find("location")
                fpath = loc.attrib.get("file", "") if loc is not None else ""
                ln = loc.attrib.get("line", "0") if loc is not None else "0"
                try:
                    abs_fpath = Path(fpath).resolve()
                    proj_resolved = project_root.resolve()
                    if abs_fpath.is_absolute() and not str(abs_fpath).startswith(str(proj_resolved)):
                        continue
                    if str(proj_resolved) in str(abs_fpath):
                        fpath = str(abs_fpath.relative_to(proj_resolved))
                except Exception:
                    pass
                issues.append(Issue(file=fpath, line=int(ln), severity=err_node.attrib.get("severity", "warning"), message=err_node.attrib.get("msg", ""), id=err_node.attrib.get("id", ""), tool="cppcheck"))
        except Exception as e:
            overall_ok = False
            issues.append(Issue(file=str(t.relative_to(project_root)), line=0, severity="error", message=f"cppcheck XML parse error: {e}", id="parse_error", tool="cppcheck"))
        if c not in (0, 1): overall_ok = False
            
    try:
        (reports_dir / "cppcheck_findings.json").write_text(json.dumps([asdict(i) for i in issues], indent=2), encoding="utf-8")
    except (OSError, TypeError):
        pass
    reason = "completed" if skipped == 0 else f"partial_timeout_{skipped}_skipped"
    return standardize_result(overall_ok, reason, {"issues": [asdict(i) for i in issues], "xml_paths": xml_paths})

def run_gcc_syntax(project_root: Path, reports_dir: Path, targets: List[Path], incs: List[str], defs: List[str], cb: Callable, arch: str, max_total_sec: int = _DEFAULT_TOTAL_TIMEOUT) -> Dict[str, Any]:
    if arch == "native": cc, flags = "gcc", []
    else: cc, flags = ("arm-none-eabi-gcc", [f"-mcpu={arch}", "-mthumb"]) if tools.is_arm_toolchain() else ("gcc", [])
    if not tools.which(cc): return standardize_result(False, "compiler_not_found")
    
    inc_args = [f"-I{ip}" for ip in (incs or []) if ip]
    def_args = [d if d.startswith("-D") else f"-D{d}" for d in (defs or []) if d.strip()]
    
    out, all_ok, total = [], True, len(targets)
    t0 = _time.monotonic()
    skipped = 0
    for i, t in enumerate(targets):
        if (_time.monotonic() - t0) > max_total_sec:
            skipped = total - i
            break
        if cb: cb(i + 1, total, f"Syntax: {t.name}")
        curr_cc = cc.replace("gcc", "g++") if t.suffix in (".cpp", ".cc") and "gcc" in cc else cc
        cmd = [curr_cc, "-fsyntax-only"] + flags + def_args + inc_args + [str(t.relative_to(project_root))]
        c, _, e = tools.run_command(cmd, cwd=project_root, timeout=180)
        if c != 0: all_ok = False
        out.append({"file": str(t.relative_to(project_root)), "ok": c==0, "exit_code": c, "stderr": e.strip()[:4000]})
        
    (reports_dir / "syntax_check.json").write_text(json.dumps({"results": out, "all_ok": all_ok}, indent=2), encoding="utf-8")
    reason = "completed" if skipped == 0 else f"partial_timeout_{skipped}_skipped"
    return standardize_result(all_ok, reason, {"results": out})
