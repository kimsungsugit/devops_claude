# workflow/delta_update.py
"""Delta Update - identify changed functions and regenerate only affected UDS sections.

Uses git/svn diff to find changed files, then cross-references with the call graph
to determine the full impact set of functions that need UDS regeneration.
"""

from __future__ import annotations

import subprocess
import re
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


_FUNC_DECL_LINE = re.compile(
    r"^[+-]\s*(?:static\s+)?"
    r"(?:void|int|uint\d+_t|int\d+_t|U\d+|S\d+|bool|float|double|char|unsigned|signed|CONSTP2VAR|P2FUNC)"
    r"[\w\s\*]*\s+(\w+)\s*\(",
    re.MULTILINE,
)
_FUNC_PROTO_LINE = re.compile(
    r"^[+-]\s*(?:(?:extern|static|inline|volatile|const)\s+)*"
    r"(?:void|int|uint\d+_t|int\d+_t|U\d+|S\d+|bool|float|double|char|unsigned|signed|CONSTP2VAR|P2FUNC|FUNC)"
    r"[\w\s\*\(\),]*?\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*;",
    re.MULTILINE,
)
_HUNK_FUNC = re.compile(r"^@@.*@@\s*(?:.*?\s)?(\w+)\s*\(", re.MULTILINE)
_VAR_DECL_LINE = re.compile(
    r"^[+-]\s*(?:static\s+)?(?:const\s+|volatile\s+|unsigned\s+|signed\s+)*"
    r"(?:void|char|bool|float|double|int|long|short|u?int\d+(?:_t)?|U\d+|S\d+|[A-Za-z_]\w*_t)\b"
    r"(?!.*\()"
    r".*?\b([sg]_[A-Za-z0-9_]+|[A-Za-z0-9_]+)\b\s*(?:\[.*\])?\s*(?:=|;|,)",
    re.MULTILINE,
)


def _run_unified_diff(
    project_root: str,
    *,
    base_ref: str,
    scm_type: str,
    file_path: Optional[str] = None,
) -> str:
    root = Path(project_root)

    if scm_type == "svn":
        cmd = ["svn", "diff"]
        if str(base_ref or "").strip():
            cmd.extend(["-r", base_ref])
        cmd.extend(["--diff-cmd", "diff", "-x", "-U3"])
        if file_path:
            cmd.append(file_path)
    else:
        cmd = ["git", "diff", base_ref]
        if file_path:
            cmd.extend(["--", file_path])

    result = subprocess.run(
        cmd,
        cwd=str(root),
        capture_output=True,
        text=True,
        errors="ignore",
        timeout=30,
    )
    if result.returncode == 0 and result.stdout:
        return result.stdout

    if scm_type == "svn":
        fallback_cmd = ["svn", "diff"]
        if file_path:
            fallback_cmd.append(file_path)
        fallback = subprocess.run(
            fallback_cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            errors="ignore",
            timeout=30,
        )
        if fallback.returncode == 0:
            return fallback.stdout
    return ""


def get_changed_files(
    project_root: str,
    *,
    base_ref: str = "HEAD~1",
    scm_type: str = "git",
) -> List[str]:
    """Get list of changed .c/.h files since base_ref."""
    root = Path(project_root)
    changed: List[str] = []

    try:
        if scm_type == "git":
            result = subprocess.run(
                ["git", "diff", "--name-only", base_ref, "--", "*.c", "*.h"],
                cwd=str(root), capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                changed = [f.strip() for f in result.stdout.splitlines() if f.strip()]
        elif scm_type == "svn":
            if str(base_ref or "").strip():
                cmd = ["svn", "diff", "--summarize", "-r", base_ref]
            else:
                cmd = ["svn", "status"]
            result = subprocess.run(
                cmd,
                cwd=str(root), capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if not parts:
                        continue
                    fpath = parts[-1].strip()
                    if fpath.endswith((".c", ".h")):
                        changed.append(fpath)
    except Exception as e:
        logger.warning("Failed to get changed files via %s: %s", scm_type, e)

    return changed


def get_changed_functions(
    project_root: str,
    changed_files: List[str],
    *,
    base_ref: str = "HEAD~1",
    scm_type: str = "git",
) -> Set[str]:
    """Extract function names that were modified in the diff."""
    changed_funcs: Set[str] = set()

    for fpath in changed_files:
        try:
            diff_text = _run_unified_diff(
                project_root,
                base_ref=base_ref,
                scm_type=scm_type,
                file_path=fpath,
            )
            for m in _FUNC_DECL_LINE.finditer(diff_text):
                changed_funcs.add(m.group(1))
            for m in _HUNK_FUNC.finditer(diff_text):
                changed_funcs.add(m.group(1))
        except Exception as e:
            logger.warning("Failed to parse diff for %s: %s", fpath, e)

    return changed_funcs


def _classify_from_edit_types(
    changed_files: List[str], edit_types: Dict[str, str]
) -> Dict[str, str]:
    """Jenkins changeSet editType(파일경로→add/edit/delete) 기반 파일 단위 분류.

    cloudium/원격에서 로컬 working-copy diff가 불가할 때 사용. diff(subprocess) 없이
    add→NEW / delete→DELETE / edit·미상→.h:HEADER·.c:BODY로 분류한다. SIGNATURE는 diff
    없이 구분 불가하므로 BODY로 보수 처리(영향 과대평가=안전측). 키는 파일 stem(소문자)로,
    _resolve_changed_types_to_functions가 by_name을 통해 실제 함수에 재매핑한다.
    """
    norm = {
        str(k).replace("\\", "/").strip().lower(): str(v or "").strip().lower()
        for k, v in (edit_types or {}).items()
    }
    out: Dict[str, str] = {}
    for fpath in changed_files:
        raw = str(fpath or "").strip()
        if not raw:
            continue
        stem = Path(raw).stem.lower()
        if not stem:
            continue
        et = norm.get(raw.replace("\\", "/").lower(), "edit")
        if et == "add":
            kind = "NEW"
        elif et == "delete":
            kind = "DELETE"
        else:  # edit/modify/기타
            kind = "HEADER" if raw.lower().endswith(".h") else "BODY"
        # 동일 stem 다중 파일: 구조적 변경(NEW/DELETE)은 단순 edit이 덮어쓰지 않게 보존.
        if out.get(stem) in {"NEW", "DELETE"}:
            continue
        out[stem] = kind
    return out


def classify_changed_functions(
    project_root: str,
    changed_files: List[str],
    *,
    scm_type: str = "git",
    base_ref: str = "HEAD~1",
    edit_types: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Classify changed functions conservatively from unified diff text.

    edit_types(Jenkins changeSet의 파일별 add/edit/delete)가 주어지면 git/svn diff를
    생략하고 editType 기반 파일 단위 분류로 직행한다(원격/cloudium에서 로컬 working-copy
    부재 대응). 상세는 _classify_from_edit_types 참조.
    """
    if edit_types:
        return _classify_from_edit_types(changed_files, edit_types)

    classifications: Dict[str, str] = {}

    for fpath in changed_files:
        try:
            diff_text = _run_unified_diff(
                project_root,
                base_ref=base_ref,
                scm_type=scm_type,
                file_path=fpath,
            )
            if not diff_text:
                continue

            hunk_funcs = {m.group(1) for m in _HUNK_FUNC.finditer(diff_text)}
            # 제어 키워드(if/for/while...)는 '(' 앞에 와도 함수 선언이 아님 — 오탐 제외.
            # (최종 SIGNATURE/NEW/DELETE 판정은 func_decl_names AND 게이트가 추가로 거르지만,
            #  added/removed_decl 자체의 노이즈를 줄여 경계 케이스 오분류를 방지한다.)
            _CTRL_KW = {"if", "for", "while", "switch", "return", "sizeof", "do", "else", "case"}
            added_decl = {m.group(1) for m in re.finditer(r"^\+\s*.*?\b(\w+)\s*\(", diff_text, re.MULTILINE) if m.group(1) not in _CTRL_KW}
            removed_decl = {m.group(1) for m in re.finditer(r"^-\s*.*?\b(\w+)\s*\(", diff_text, re.MULTILINE) if m.group(1) not in _CTRL_KW}
            func_decl_names = {m.group(1) for m in _FUNC_DECL_LINE.finditer(diff_text)}
            func_proto_names = {m.group(1) for m in _FUNC_PROTO_LINE.finditer(diff_text)}
            var_changed = bool(_VAR_DECL_LINE.search(diff_text))
            is_header = fpath.endswith(".h")

            candidates = hunk_funcs | func_decl_names | (func_proto_names if is_header else set())
            for func in sorted(candidates):
                current = classifications.get(func)
                new_kind = "BODY"

                if is_header:
                    new_kind = "HEADER"
                elif func in added_decl and func in removed_decl and func in func_decl_names:
                    new_kind = "SIGNATURE"
                elif func in added_decl and func in func_decl_names:
                    new_kind = "NEW"
                elif func in removed_decl and func in func_decl_names:
                    new_kind = "DELETE"
                elif var_changed:
                    new_kind = "VARIABLE"

                if current in {"NEW", "DELETE", "SIGNATURE", "HEADER"}:
                    continue
                classifications[func] = new_kind
        except Exception as e:
            logger.warning("Failed to classify diff for %s: %s", fpath, e)

    return classifications


def compute_impact_set(
    changed_functions: Set[str],
    call_map: Dict[str, List[str]],
    *,
    max_depth: int = 3,
) -> Set[str]:
    """Given changed functions and a call graph, compute the full impact set.

    Traverses callers (reverse call graph) up to max_depth levels to find all
    functions that may be affected by the changes.
    """
    reverse_map: Dict[str, Set[str]] = {}
    for caller, callees in call_map.items():
        for callee in callees:
            reverse_map.setdefault(callee, set()).add(caller)

    impact: Set[str] = set(changed_functions)
    frontier = set(changed_functions)

    for _ in range(max_depth):
        next_frontier: Set[str] = set()
        for func in frontier:
            callers = reverse_map.get(func, set())
            for caller in callers:
                if caller not in impact:
                    impact.add(caller)
                    next_frontier.add(caller)
            callees = call_map.get(func, [])
            for callee in callees:
                if callee not in impact:
                    impact.add(callee)
                    next_frontier.add(callee)
        if not next_frontier:
            break
        frontier = next_frontier

    return impact


def filter_function_details(
    function_details: Dict[str, Dict[str, Any]],
    impact_set: Set[str],
) -> Dict[str, Dict[str, Any]]:
    """Filter function_details to only include functions in the impact set."""
    filtered = {}
    for fid, info in function_details.items():
        if not isinstance(info, dict):
            continue
        name = info.get("name", "")
        if name in impact_set or name.lower() in {f.lower() for f in impact_set}:
            filtered[fid] = info
    return filtered


def compute_delta_summary(
    project_root: str,
    function_details: Dict[str, Dict[str, Any]],
    call_map: Dict[str, List[str]],
    *,
    base_ref: str = "HEAD~1",
    scm_type: str = "git",
) -> Dict[str, Any]:
    """Full delta analysis: changed files -> changed functions -> impact set -> filtered details."""
    changed_files = get_changed_files(project_root, base_ref=base_ref, scm_type=scm_type)
    if not changed_files:
        return {
            "changed_files": [],
            "changed_functions": [],
            "impact_set": [],
            "filtered_count": 0,
            "total_count": len(function_details),
            "skip_ratio": 1.0,
        }

    changed_types = classify_changed_functions(
        project_root,
        changed_files,
        base_ref=base_ref,
        scm_type=scm_type,
    )
    changed_funcs = set(changed_types)
    impact = compute_impact_set(changed_funcs, call_map)
    filtered = filter_function_details(function_details, impact)

    total = len(function_details)
    skip_ratio = 1.0 - (len(filtered) / total) if total > 0 else 0.0

    logger.info(
        "Delta update: %d changed files, %d changed functions, "
        "%d impact set, %d/%d functions to regenerate (skip %.0f%%)",
        len(changed_files), len(changed_funcs), len(impact),
        len(filtered), total, skip_ratio * 100,
    )

    return {
        "changed_files": changed_files,
        "changed_functions": sorted(changed_funcs),
        "changed_function_types": dict(sorted(changed_types.items())),
        "impact_set": sorted(impact),
        "filtered_count": len(filtered),
        "total_count": total,
        "skip_ratio": skip_ratio,
        "filtered_details": filtered,
    }
