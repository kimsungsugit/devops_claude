from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


REQUIRED_PY_MODULES = {
    "tree_sitter": "tree-sitter",
    "tree_sitter_c": "tree-sitter-c",
    "clang.cindex": "clang",
    "jsonschema": "jsonschema",
    "networkx": "networkx",
}

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _check_module(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def _pip_install(pkgs: List[str]) -> str:
    if not pkgs:
        return "no-op"
    cmd = [sys.executable, "-m", "pip", "install", *pkgs]
    run = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if run.returncode == 0:
        return "ok"
    return ((run.stderr or "") + "\n" + (run.stdout or "")).strip()[-2000:]


def _find_clang_tools() -> Dict[str, str]:
    return {
        "clang": shutil.which("clang") or "",
        "clangd": shutil.which("clangd") or "",
        "ctags": shutil.which("ctags") or "",
    }


def _resolve_libclang_path() -> str:
    # 1) existing env
    env_path = os.getenv("LIBCLANG_PATH", "").strip()
    if env_path and Path(env_path).exists():
        return env_path
    # 2) from python clang package
    try:
        import clang  # type: ignore

        base = Path(clang.__file__).resolve().parent
        candidates = [
            base / "native" / "libclang.dll",
            base / "native" / "libclang.so",
            base / "native" / "libclang.dylib",
            base / "libclang.dll",
        ]
        for c in candidates:
            if c.exists():
                return str(c.parent)
    except Exception:
        pass
    # 3) common windows install
    common = [
        Path(r"C:\Program Files\LLVM\bin"),
        Path(r"C:\Program Files\LLVM\lib"),
    ]
    for p in common:
        if p.exists():
            return str(p)
    return ""


def _run_parse_smoke(source_root: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "source_root": source_root,
        "ok": False,
        "functions": 0,
        "globals": 0,
        "scanned": 0,
        "error": "",
    }
    try:
        from workflow.code_parser import parse_c_project  # type: ignore
        parsed = parse_c_project(source_root, max_files=30, preprocess=True)
        if not (parsed.get("scanned", []) or []):
            parsed = parse_c_project(source_root, max_files=30, preprocess=False)
        funcs = parsed.get("functions", []) or []
        globs = parsed.get("globals", []) or []
        scanned = parsed.get("scanned", []) or []
        result["functions"] = len(funcs)
        result["globals"] = len(globs)
        result["scanned"] = len(scanned)
        result["ok"] = len(scanned) > 0
    except Exception as exc:
        result["error"] = str(exc)
    return result


def main() -> None:
    status: Dict[str, Any] = {
        "python": sys.executable,
        "modules": {},
        "installed": [],
        "install_result": "",
        "tools": _find_clang_tools(),
        "libclang_path": "",
        "parse_smoke": {},
        "notes": [],
    }

    missing_pkgs: List[str] = []
    for mod, pkg in REQUIRED_PY_MODULES.items():
        ok = _check_module(mod)
        status["modules"][mod] = ok
        if not ok:
            missing_pkgs.append(pkg)

    if missing_pkgs:
        # De-duplicate package names.
        to_install = sorted(set(missing_pkgs))
        status["installed"] = to_install
        status["install_result"] = _pip_install(to_install)
        # Re-check after install.
        for mod in REQUIRED_PY_MODULES.keys():
            status["modules"][mod] = _check_module(mod)

    libclang_path = _resolve_libclang_path()
    status["libclang_path"] = libclang_path
    if libclang_path:
        os.environ["LIBCLANG_PATH"] = libclang_path
        status["notes"].append(f"set LIBCLANG_PATH={libclang_path}")
    else:
        status["notes"].append("LIBCLANG_PATH not found automatically")

    source_root = os.getenv("SOURCE_ROOT", r"D:\Project\Ados\PDS_64_RD")
    if Path(source_root).exists():
        status["parse_smoke"] = _run_parse_smoke(source_root)
    else:
        status["parse_smoke"] = {
            "source_root": source_root,
            "ok": False,
            "error": "source root not found",
        }

    reports_dir = Path(r"D:\Project\devops\260105\reports\uds")
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / "parser_toolchain_status.json"
    out.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"STATUS_JSON={out}")
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
