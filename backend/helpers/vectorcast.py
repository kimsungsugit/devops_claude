from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


_REPO_ROOT = Path(__file__).resolve().parents[2]
VECTORCAST_CONFIG_DIR = _REPO_ROOT / "config" / "vectorcast_projects"

_DEFAULT_CONFIG: Dict[str, Any] = {
    "project_id": "",
    "env_mode": "new_env",
    "compiler": "CC",
    "linker": "",
    "compiler_options": [],
    "linker_options": [],
    "include_paths": [],
    "source_paths": [],
    "uut_sources": [],
    "uut_headers": [],
    "dependency_sources": [],
    "dependency_libs": [],
    "dependency_objects": [],
    "existing_env_file": "",
    "existing_project_file": "",
    "regression_command_template": "",
}


def _dedupe_texts(values: Iterable[Any]) -> List[str]:
    items: List[str] = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _collect_default_paths(source_root: str) -> Dict[str, List[str]]:
    root = Path(source_root).expanduser()
    if not source_root or not root.exists():
        return {"include_paths": [], "source_paths": []}
    candidates = [
        root / "Sources",
        root / "Sources" / "APP",
        root / "Sources" / "IF",
        root / "Sources" / "SYSTEM",
        root / "Lib",
        root / "Generated_Code",
        root / "Project_Headers",
        root / "Include",
    ]
    paths = [str(path.resolve()) for path in candidates if path.exists()]
    return {"include_paths": paths, "source_paths": paths}


def load_vectorcast_project_config(project_id: str = "", source_root: str = "") -> Dict[str, Any]:
    cfg: Dict[str, Any] = dict(_DEFAULT_CONFIG)
    project_token = str(project_id or "").strip()
    candidates: List[Path] = []
    if project_token:
        candidates.append(VECTORCAST_CONFIG_DIR / f"{project_token}.json")
        candidates.append(VECTORCAST_CONFIG_DIR / f"{project_token.lower()}.json")
    candidates.append(VECTORCAST_CONFIG_DIR / "default.json")

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            loaded = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(loaded, dict):
            cfg.update(loaded)
            break

    path_defaults = _collect_default_paths(source_root or str(cfg.get("source_root") or ""))
    cfg["project_id"] = str(cfg.get("project_id") or project_token or "").strip()
    cfg["source_root"] = str(source_root or cfg.get("source_root") or "").strip()
    cfg["compiler"] = str(cfg.get("compiler") or "CC").strip() or "CC"
    cfg["linker"] = str(cfg.get("linker") or "").strip()
    cfg["env_mode"] = str(cfg.get("env_mode") or "new_env").strip() or "new_env"
    cfg["existing_env_file"] = str(cfg.get("existing_env_file") or "").strip()
    cfg["existing_project_file"] = str(cfg.get("existing_project_file") or "").strip()
    cfg["regression_command_template"] = str(cfg.get("regression_command_template") or "").strip()
    cfg["compiler_options"] = _dedupe_texts(cfg.get("compiler_options") or [])
    cfg["linker_options"] = _dedupe_texts(cfg.get("linker_options") or [])
    cfg["include_paths"] = _dedupe_texts((cfg.get("include_paths") or []) or path_defaults["include_paths"])
    cfg["source_paths"] = _dedupe_texts((cfg.get("source_paths") or []) or path_defaults["source_paths"])
    for key in ("uut_sources", "uut_headers", "dependency_sources", "dependency_libs", "dependency_objects"):
        cfg[key] = _dedupe_texts(cfg.get(key) or [])
    return cfg


def build_vectorcast_metadata(
    *,
    project_config: Dict[str, Any] | None,
    source_root: str = "",
    units: Iterable[str] | None = None,
) -> Dict[str, Any]:
    cfg = dict(project_config or {})
    cfg_root = str(source_root or cfg.get("source_root") or "").strip()
    unit_names = _dedupe_texts(units or [])
    return {
        "project": {
            "project_id": str(cfg.get("project_id") or "").strip(),
            "env_mode": str(cfg.get("env_mode") or "new_env").strip() or "new_env",
            "source_root": cfg_root,
            "compiler": str(cfg.get("compiler") or "CC").strip() or "CC",
            "linker": str(cfg.get("linker") or "").strip(),
            "compiler_options": _dedupe_texts(cfg.get("compiler_options") or []),
            "linker_options": _dedupe_texts(cfg.get("linker_options") or []),
            "existing_env_file": str(cfg.get("existing_env_file") or "").strip(),
            "existing_project_file": str(cfg.get("existing_project_file") or "").strip(),
            "regression_command_template": str(cfg.get("regression_command_template") or "").strip(),
        },
        "paths": {
            "include_paths": _dedupe_texts(cfg.get("include_paths") or []),
            "source_paths": _dedupe_texts(cfg.get("source_paths") or []),
        },
        "uut": {
            "units": unit_names,
            "source_files": _dedupe_texts(cfg.get("uut_sources") or []),
            "header_files": _dedupe_texts(cfg.get("uut_headers") or []),
        },
        "dependencies": {
            "source_files": _dedupe_texts(cfg.get("dependency_sources") or []),
            "libraries": _dedupe_texts(cfg.get("dependency_libs") or []),
            "objects": _dedupe_texts(cfg.get("dependency_objects") or []),
        },
    }


def evaluate_vectorcast_readiness(metadata: Dict[str, Any]) -> Dict[str, Any]:
    project = metadata.get("project") or {}
    paths = metadata.get("paths") or {}
    deps = metadata.get("dependencies") or {}
    checks: List[Dict[str, Any]] = []

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add_check("compiler", bool(project.get("compiler")), "VectorCAST compiler must be defined.")
    add_check(
        "paths",
        bool((paths.get("include_paths") or []) or (paths.get("source_paths") or [])),
        "At least one include/source path is required.",
    )
    add_check(
        "uut",
        bool((metadata.get("uut") or {}).get("units") or (metadata.get("uut") or {}).get("source_files")),
        "At least one UUT unit or source entry is required.",
    )
    add_check(
        "dependencies",
        bool((deps.get("source_files") or []) or (deps.get("libraries") or []) or (deps.get("objects") or [])),
        "Dependency inputs are optional but recommended for import-ready status.",
    )

    env_mode = str(project.get("env_mode") or "new_env").strip().lower()
    if env_mode == "existing_env":
        add_check(
            "existing_env",
            bool(project.get("existing_env_file") or project.get("existing_project_file")),
            "existing_env mode requires .vce/.vcp/.vcm reference metadata.",
        )

    failed_required = any(not item["ok"] for item in checks if item["name"] in {"compiler", "paths", "uut"})
    failed_optional = any(not item["ok"] for item in checks if item["name"] not in {"compiler", "paths", "uut"})
    if failed_required:
        status = "TEMPLATE_ONLY"
    elif failed_optional:
        status = "PARTIALLY_READY"
    else:
        status = "IMPORT_READY"

    return {
        "status": status,
        "checks": checks,
        "summary": {
            "required_ok": not failed_required,
            "optional_ok": not failed_optional,
            "check_count": len(checks),
        },
    }
