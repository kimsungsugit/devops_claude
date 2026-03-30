from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional


_PREFIXES = ("ap_", "g_", "s_", "v_")
_SUFFIXES = ("_pds", "_func", "_on", "_off", "_run", "_reset", "_ctrl")
_CAMEL_TOKEN_RE = re.compile(r"[A-Z][a-z0-9]+")


def _to_pascal(token: str) -> str:
    parts = [part for part in re.split(r"[_\-\s]+", str(token or "")) if part]
    return "".join(part[:1].upper() + part[1:].lower() for part in parts)


def _normalize_module_name(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    if "_" in raw or "-" in raw or " " in raw:
        return _to_pascal(raw)
    chunks = _CAMEL_TOKEN_RE.findall(raw)
    if chunks:
        return "".join(chunks)
    return raw[:1].upper() + raw[1:]


def _from_function_name(function_name: str) -> List[Dict[str, object]]:
    fn = str(function_name or "").strip().lower()
    if not fn:
        return []
    for prefix in _PREFIXES:
        if fn.startswith(prefix):
            fn = fn[len(prefix):]
            break
    for suffix in _SUFFIXES:
        if fn.endswith(suffix):
            fn = fn[: -len(suffix)]
            break
    parts = [part for part in fn.split("_") if part]
    if not parts:
        return []
    module = _normalize_module_name(parts[0])
    if len(parts) >= 2 and parts[1] == "ctrl":
        module = _normalize_module_name(parts[0] + "_" + parts[1])
    if not module:
        return []
    return [{"module_name": module, "source": "function_name", "confidence": 0.78}]


def _from_source_files(source_files: Optional[List[str]]) -> List[Dict[str, object]]:
    if not source_files:
        return []
    candidates: List[Dict[str, object]] = []
    seen = set()
    for file in source_files:
        stem = Path(str(file or "")).stem
        stem = re.sub(r"^(Ap|Lib|Drv|Hal)_", "", stem, flags=re.I)
        stem = re.sub(r"_(PDS|PDSM|RD|IT)$", "", stem, flags=re.I)
        parts = [part for part in stem.split("_") if part]
        if not parts:
            continue
        module = _normalize_module_name(parts[0] if len(parts) == 1 else "_".join(parts[:2] if parts[1].lower() == "ctrl" else parts[:1]))
        if module and module not in seen:
            seen.add(module)
            candidates.append({"module_name": module, "source": "source_file", "confidence": 0.88})
    return candidates


def infer_module_candidates(
    function_name: str,
    *,
    source_files: Optional[List[str]] = None,
    component_map: Optional[dict] = None,
) -> List[Dict[str, object]]:
    candidates: List[Dict[str, object]] = []
    seen = set()
    for candidate in [*_from_source_files(source_files), *_from_function_name(function_name)]:
        module = str(candidate.get("module_name") or "").strip()
        if not module or module in seen:
            continue
        seen.add(module)
        candidates.append(candidate)
    return sorted(candidates, key=lambda item: float(item.get("confidence") or 0), reverse=True)


def choose_best_module(candidates: List[Dict[str, object]]) -> Optional[Dict[str, object]]:
    if not candidates:
        return None
    return max(candidates, key=lambda item: float(item.get("confidence") or 0))


def build_function_module_index(
    changed_functions: Dict[str, str],
    *,
    changed_files: Optional[List[str]] = None,
    component_map: Optional[dict] = None,
) -> Dict[str, Dict[str, object]]:
    index: Dict[str, Dict[str, object]] = {}
    files = list(changed_files or [])
    for function_name, change_type in (changed_functions or {}).items():
        candidates = infer_module_candidates(function_name, source_files=files, component_map=component_map)
        best = choose_best_module(candidates) or {}
        index[str(function_name)] = {
            "function_name": str(function_name),
            "change_type": str(change_type or "").upper(),
            "module_candidates": candidates,
            "best_module": str(best.get("module_name") or ""),
            "best_confidence": float(best.get("confidence") or 0),
            "source_files": files,
        }
    return index
