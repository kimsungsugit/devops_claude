from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List


def preprocess_c_file(path: Path) -> str:
    try:
        result = subprocess.run(
            ["gcc", "-E", "-P", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except Exception:
        pass
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def extract_functions(text: str) -> List[str]:
    if not text:
        return []
    keywords = {"if", "for", "while", "switch", "return", "sizeof"}
    names: List[str] = []
    for match in re.finditer(
        r"^[\t ]*(?:static\s+)?[A-Za-z_][\w\s\*\(\),]*?\s+([A-Za-z_]\w*)\s*\([^;]*?\)\s*\{",
        text,
        flags=re.M,
    ):
        name = match.group(1)
        if name in keywords:
            continue
        names.append(name)
    return names


def parse_source_root(source_root: str, max_files: int = 400) -> Dict[str, Any]:
    root = Path(source_root).resolve()
    if not root.exists():
        return {"functions": [], "scanned": 0}
    allowed = {".c", ".h", ".cpp", ".hpp"}
    functions: List[str] = []
    scanned = 0
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext not in allowed:
                continue
            p = Path(dirpath) / name
            scanned += 1
            if scanned > max_files:
                break
            text = preprocess_c_file(p)
            for fn in extract_functions(text):
                if fn not in functions:
                    functions.append(fn)
        if scanned > max_files:
            break
    return {"functions": functions, "scanned": scanned}
