# /app/workflow/static.py
import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from xml.etree import ElementTree as ET
import analysis_tools as tools
from .common import Issue, standardize_result

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
            except: pass
            issues.append(Issue(file=fpath, line=int(lineno), severity=sev, message=msg, id=cid, tool="clang-tidy"))
    return issues

def run_clang_tidy(project_root: Path, targets: List[Path], checks: List[str], build_dir: Path, cb: Optional[Callable] = None) -> Dict[str, Any]:
    if not tools.which("clang-tidy"): return standardize_result(False, "clang_tidy_not_found")
    if not (build_dir / "compile_commands.json").exists(): return standardize_result(False, "no_compile_commands")
    
    check_str = ",".join(checks) if checks else "bugprone-*,performance-*"
    all_issues = []
    total = len(targets)
    for i, t in enumerate(targets):
        if cb: cb(i + 1, total, f"Clang-Tidy: {t.name}")
        if t.suffix not in ('.c', '.cpp'): continue
        cmd = ["clang-tidy", "-p", str(build_dir), f"-checks=-*,{check_str}", str(t), f"--header-filter={str(project_root)}/.*"]
        _, out, _ = tools.run_command(cmd, cwd=project_root, timeout=300)
        all_issues.extend(parse_clang_tidy_output(out, project_root))
    return standardize_result(True, "completed", {"issues": [asdict(i) for i in all_issues]})

def run_cppcheck(project_root: Path, reports_dir: Path, targets: List[Path], enable: List[str], incs: List[str], suppr: str, cb: Callable, arch: str, defs: List[str]) -> Dict[str, Any]:
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
        plat_args += ["--platform=arm-none-eabi-gcc", "-D__GNUC__"] + [f"-D{d.lstrip('-D')}" for d in (defs or [])]

    total = len(targets)
    for i, t in enumerate(targets):
        if cb: cb(i + 1, total, f"Cppcheck: {t.name}")
        xml_path = cpp_dir / f"{t.name}.xml"
        cmd = ["cppcheck", f"--enable={enable_str}", "--xml", "--xml-version=2", "--inline-suppr"] + plat_args + suppr_args + inc_args + [str(t.relative_to(project_root))]
        c, _, err = tools.run_command(cmd, cwd=project_root, timeout=600)
        
        try:
            xml_path.write_text(err, encoding="utf-8")
            xml_paths.append(str(xml_path))
            root = ET.fromstring(err)
            for err_node in root.findall(".//errors/error"):
                loc = err_node.find("location")
                fpath = loc.attrib.get("file", "") if loc is not None else ""
                ln = loc.attrib.get("line", "0") if loc is not None else "0"
                issues.append(Issue(file=fpath, line=int(ln), severity=err_node.attrib.get("severity", "warning"), message=err_node.attrib.get("msg", ""), id=err_node.attrib.get("id", ""), tool="cppcheck"))
        except: overall_ok = False
        if c not in (0, 1): overall_ok = False
            
    try: (reports_dir / "cppcheck_findings.json").write_text(json.dumps([asdict(i) for i in issues], indent=2), encoding="utf-8")
    except: pass
    return standardize_result(overall_ok, "completed", {"issues": [asdict(i) for i in issues], "xml_paths": xml_paths})

def run_gcc_syntax(project_root: Path, reports_dir: Path, targets: List[Path], incs: List[str], defs: List[str], cb: Callable, arch: str) -> Dict[str, Any]:
    if arch == "native": cc, flags = "gcc", []
    else: cc, flags = ("arm-none-eabi-gcc", [f"-mcpu={arch}", "-mthumb"]) if tools.is_arm_toolchain() else ("gcc", [])
    if not tools.which(cc): return standardize_result(False, "compiler_not_found")
    
    inc_args = [f"-I{ip}" for ip in (incs or []) if ip]
    def_args = [d if d.startswith("-D") else f"-D{d}" for d in (defs or []) if d.strip()]
    
    out, all_ok, total = [], True, len(targets)
    for i, t in enumerate(targets):
        if cb: cb(i + 1, total, f"Syntax: {t.name}")
        curr_cc = cc.replace("gcc", "g++") if t.suffix in (".cpp", ".cc") and "gcc" in cc else cc
        cmd = [curr_cc, "-fsyntax-only"] + flags + def_args + inc_args + [str(t.relative_to(project_root))]
        c, _, e = tools.run_command(cmd, cwd=project_root, timeout=180)
        if c != 0: all_ok = False
        out.append({"file": str(t.relative_to(project_root)), "ok": c==0, "exit_code": c, "stderr": e.strip()[:4000]})
        
    (reports_dir / "syntax_check.json").write_text(json.dumps({"results": out, "all_ok": all_ok}, indent=2), encoding="utf-8")
    return standardize_result(all_ok, "completed", {"results": out})
