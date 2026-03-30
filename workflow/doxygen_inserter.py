# workflow/doxygen_inserter.py
"""Auto @brief comment insertion - inject Doxygen comments from AI-generated descriptions.

Takes function descriptions from UDS AI generation and inserts @brief comments
into the corresponding C source files.
"""

from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_FUNC_DEF_PAT = re.compile(
    r"^(\s*)(?:static\s+)?(?:inline\s+)?(?:const\s+)?"
    r"(?:void|int|uint\d+_t|U\d+|S\d+|bool|BOOL|float|double|char|unsigned|signed|size_t|ssize_t)"
    r"\s+(\w+)\s*\(",
    re.MULTILINE,
)


def _has_existing_doxygen(lines: List[str], func_line_idx: int) -> bool:
    """Check if a function already has a Doxygen comment block above it."""
    for i in range(func_line_idx - 1, max(func_line_idx - 10, -1), -1):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if stripped.startswith("/**") or stripped.startswith("///") or stripped.startswith("* @brief"):
            return True
        if stripped.endswith("*/"):
            return True
        if stripped.startswith("*"):
            continue
        break
    return False


def _build_doxygen_block(
    description: str,
    prototype: str = "",
    params: Optional[List[str]] = None,
    return_type: str = "",
    indent: str = "",
) -> List[str]:
    """Build a Doxygen comment block."""
    lines = [f"{indent}/**"]
    lines.append(f"{indent} * @brief {description}")

    if params:
        lines.append(f"{indent} *")
        for param in params:
            param_clean = re.sub(r"^\[(?:IN|OUT|INOUT)\]\s*", "", param).strip()
            m = re.match(r"(\w+)\s+(\w+)", param_clean)
            if m:
                lines.append(f"{indent} * @param {m.group(2)} {m.group(1)} type parameter")
            elif param_clean:
                lines.append(f"{indent} * @param {param_clean}")

    if return_type and return_type.lower() not in ("void", ""):
        lines.append(f"{indent} * @return {return_type}")

    lines.append(f"{indent} */")
    return lines


def insert_doxygen_comments(
    source_path: str,
    function_descriptions: Dict[str, Dict[str, Any]],
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Insert @brief comments into a C source file.

    Args:
        source_path: Path to .c file
        function_descriptions: Dict mapping function name (lowercase) to info dict
            with keys: description, prototype, inputs, outputs
        dry_run: If True, don't write changes, just report what would be done

    Returns:
        Dict with inserted_count, skipped_count, and details
    """
    path = Path(source_path)
    if not path.exists():
        return {"error": f"File not found: {source_path}", "inserted": 0, "skipped": 0}

    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()

    insertions: List[Tuple[int, List[str]]] = []
    skipped: List[str] = []

    for m in _FUNC_DEF_PAT.finditer(content):
        indent = m.group(1)
        func_name = m.group(2)
        func_key = func_name.lower()

        if func_key not in function_descriptions:
            continue

        line_num = content[:m.start()].count("\n")

        if _has_existing_doxygen(lines, line_num):
            skipped.append(func_name)
            continue

        info = function_descriptions[func_key]
        desc = info.get("description", "")
        if not desc or len(desc) < 5:
            skipped.append(func_name)
            continue

        inputs = info.get("inputs", [])
        prototype = info.get("prototype", "")
        ret_match = re.match(r"(\w+)\s+", prototype) if prototype else None
        ret_type = ret_match.group(1) if ret_match else ""

        block = _build_doxygen_block(desc, prototype, inputs, ret_type, indent)
        insertions.append((line_num, block))

    if not insertions:
        return {
            "file": str(source_path),
            "inserted": 0,
            "skipped": len(skipped),
            "skipped_functions": skipped,
        }

    for line_num, block in reversed(insertions):
        lines[line_num:line_num] = block

    if not dry_run:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "file": str(source_path),
        "inserted": len(insertions),
        "skipped": len(skipped),
        "skipped_functions": skipped,
        "inserted_functions": [lines[ln + len(block) - 1] for ln, block in insertions] if insertions else [],
        "dry_run": dry_run,
    }


def batch_insert_doxygen(
    source_root: str,
    function_details: Dict[str, Dict[str, Any]],
    *,
    dry_run: bool = False,
    file_pattern: str = "*.c",
) -> Dict[str, Any]:
    """Insert Doxygen comments across all matching source files."""
    root = Path(source_root)
    if not root.exists():
        return {"error": f"Source root not found: {source_root}"}

    name_to_info: Dict[str, Dict[str, Any]] = {}
    for fid, info in function_details.items():
        if not isinstance(info, dict):
            continue
        name = info.get("name", "")
        desc = info.get("description", "")
        if name and desc and len(desc) > 5:
            name_to_info[name.lower()] = info

    results: List[Dict[str, Any]] = []
    total_inserted = 0
    total_skipped = 0

    for src_file in root.rglob(file_pattern):
        result = insert_doxygen_comments(str(src_file), name_to_info, dry_run=dry_run)
        if result.get("inserted", 0) > 0 or result.get("skipped", 0) > 0:
            results.append(result)
            total_inserted += result.get("inserted", 0)
            total_skipped += result.get("skipped", 0)

    return {
        "source_root": str(source_root),
        "files_processed": len(results),
        "total_inserted": total_inserted,
        "total_skipped": total_skipped,
        "file_results": results,
        "dry_run": dry_run,
    }
