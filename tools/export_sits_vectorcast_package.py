"""SITS → VectorCAST Integration Test Package Exporter

Reads the intermediate JSON saved by generate_sits() and writes:
  - manifest.json
  - cases.csv
  - vectorcast_integration_tests.template.tst
  - vectorcast_environment.template.env
  - run_vectorcast_import.cmd
  - import_instructions.md
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load_json(path: str) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("intermediate model must be a JSON object")
    return data


def _parse_call_chain(call_chain: str) -> List[Tuple[str, str]]:
    """Parse 'Module_A.func_a -> Module_B.func_b' into [(module, func), ...]."""
    pairs: List[Tuple[str, str]] = []
    for token in re.split(r"\s*->\s*", str(call_chain or "").strip()):
        token = token.strip()
        if not token:
            continue
        if "." in token:
            parts = token.split(".", 1)
            pairs.append((parts[0].strip(), parts[1].strip()))
        else:
            pairs.append(("UNKNOWN", token))
    return pairs


def _entry_unit_subprogram(call_chain: str, module_name: str, entry_fn: str) -> Tuple[str, str]:
    """Return (unit, subprogram) for the entry (first) node of the call chain."""
    pairs = _parse_call_chain(call_chain)
    if pairs:
        return pairs[0]
    # fallback
    return (module_name or "UNKNOWN", entry_fn or "UNKNOWN")


def _integration_nodes(call_chain: str) -> List[Tuple[str, str]]:
    """Return all nodes after the first (the called/integrated functions)."""
    pairs = _parse_call_chain(call_chain)
    return pairs[1:] if len(pairs) > 1 else []


def _build_case_name(tc_id: str, sub_case_num: Any) -> str:
    num = int(sub_case_num) if str(sub_case_num).isdigit() else 1
    return f"{tc_id}.{num:03d}"


def _render_value(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

def _iter_rows(model: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for itc in model.get("integrations") or []:
        tc_id = str(itc.get("tc_id") or "")
        entry_fn = str(itc.get("entry_fn") or "")
        call_chain = str(itc.get("call_chain") or "")
        module_name = str(itc.get("module_name") or "")
        gen_method = str(itc.get("gen_method") or "")
        asil = str(itc.get("asil") or "QM")
        related_ids = ", ".join(
            str(x) for x in (itc.get("metadata") or {}).get("related_ids", []) if str(x).strip()
        )
        unit, subprogram = _entry_unit_subprogram(call_chain, module_name, entry_fn)
        for sc in itc.get("sub_cases") or []:
            case_num = sc.get("case_num", 1)
            yield {
                "tc_id": tc_id,
                "case_name": _build_case_name(tc_id, case_num),
                "case_label": sc.get("case_label", str(case_num)),
                "entry_unit": unit,
                "entry_subprogram": subprogram,
                "call_chain": call_chain,
                "gen_method": gen_method,
                "asil": asil,
                "precondition": sc.get("precondition", ""),
                "related_ids": related_ids,
                "inputs_json": json.dumps(sc.get("inputs") or {}, ensure_ascii=False),
                "expected_json": json.dumps(sc.get("expected") or {}, ensure_ascii=False),
            }


def _write_cases_csv(model: Dict[str, Any], out_path: Path) -> int:
    rows = list(_iter_rows(model))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "tc_id", "case_name", "case_label", "entry_unit", "entry_subprogram",
        "call_chain", "gen_method", "asil", "precondition",
        "related_ids", "inputs_json", "expected_json",
    ]
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------

def _build_manifest(model: Dict[str, Any], *, package_name: str, csv_name: str) -> Dict[str, Any]:
    integrations = model.get("integrations") or []
    total_cases = sum(len(itc.get("sub_cases") or []) for itc in integrations)
    return {
        "package_name": package_name,
        "schema_version": "1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": model.get("source") or {},
        "summary": {
            "integration_count": len(integrations),
            "sub_case_count": total_cases,
            "warning_count": len(model.get("export_warnings") or []),
        },
        "artifacts": {
            "cases_csv": csv_name,
            "import_instructions": "import_instructions.md",
            "import_stub_cmd": "run_vectorcast_import.cmd",
            "test_script_template": "vectorcast_integration_tests.template.tst",
            "environment_template": "vectorcast_environment.template.env",
            "uut_manifest": "uut_manifest.json",
            "dependency_manifest": "dependency_manifest.json",
            "mapping_report": "mapping_report.json",
        },
    }


# ---------------------------------------------------------------------------
# import instructions
# ---------------------------------------------------------------------------

def _write_instructions(model: Dict[str, Any], manifest: Dict[str, Any], out_path: Path) -> None:
    summary = manifest.get("summary") or {}
    source = model.get("source") or {}
    lines = [
        "# VectorCAST SITS Integration Test Import Package",
        "",
        f"- Package: `{manifest.get('package_name')}`",
        f"- Source SITS: `{source.get('sits_path') or '-'}`",
        f"- Integration TCs: `{summary.get('integration_count')}`",
        f"- Sub-cases: `{summary.get('sub_case_count')}`",
        f"- Export warnings: `{summary.get('warning_count')}`",
        "",
        "## Included Files",
        "",
        "- `manifest.json`",
        "- `cases.csv`",
        "- `vectorcast_integration_tests.template.tst`",
        "- `vectorcast_environment.template.env`",
        "- `run_vectorcast_import.cmd`",
        "",
        "## Key Differences from Unit Test (SUTS) Package",
        "",
        "- Integration tests use **Function Call Coverage** (not just Statement+Branch).",
        "- Called functions in the call chain **must NOT be stubbed** — real integration is the intent.",
        "- Each TC maps to a call chain entry point (`entry_unit.entry_subprogram`).",
        "- `call_chain` column in `cases.csv` lists the full integration path.",
        "",
        "## Recommended Import Workflow",
        "",
        "1. Open `vectorcast_environment.template.env` and confirm compiler, search paths, and unit list.",
        "2. Set `ENVIRO.COVERAGE_TYPE: Function+Call` (not Statement) to capture integration coverage.",
        "3. For each unit in the call chain, **remove** any `TEST.STUB` that would break integration.",
        "4. Review `vectorcast_integration_tests.template.tst` — replace `REVIEW PATH` placeholders with real VectorCAST object paths.",
        "5. Use `cases.csv` as the canonical source for case names, inputs, expected outputs, and traceability.",
        "",
        "## ASIL Notes",
        "",
        "- Cases with ASIL-B or higher require stricter review before VectorCAST import.",
        "- `related_ids` in `cases.csv` should be copied to VectorCAST requirement trace fields.",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# .tst template writer
# ---------------------------------------------------------------------------

def _write_tst_template(model: Dict[str, Any], out_path: Path) -> None:
    lines: List[str] = [
        "-- VectorCAST Integration Test template generated from SITS intermediate JSON",
        "-- REVIEW REQUIRED: adjust TEST.UNIT / TEST.SUBPROGRAM paths and remove stubs for integration.",
        "--",
        "",
    ]

    for itc in model.get("integrations") or []:
        tc_id = str(itc.get("tc_id") or "")
        call_chain = str(itc.get("call_chain") or "")
        entry_fn = str(itc.get("entry_fn") or "")
        module_name = str(itc.get("module_name") or "")
        asil = str(itc.get("asil") or "QM")
        related_ids = (itc.get("metadata") or {}).get("related_ids") or []

        unit, subprogram = _entry_unit_subprogram(call_chain, module_name, entry_fn)
        integration_nodes = _integration_nodes(call_chain)

        lines.append(f"-- ===== {tc_id} =====")
        lines.append(f"-- Call Chain : {call_chain or entry_fn}")
        lines.append(f"-- ASIL       : {asil}")
        lines.append("")

        for sc in itc.get("sub_cases") or []:
            case_num = sc.get("case_num", 1)
            case_name = _build_case_name(tc_id, case_num)
            case_label = sc.get("case_label", str(case_num))
            precondition = sc.get("precondition", "")
            inputs = sc.get("inputs") or {}
            expected = sc.get("expected") or {}

            lines.extend([
                f"-- Test Case: {case_name}  [{case_label}]",
                f"TEST.UNIT:{unit}",
                f"TEST.SUBPROGRAM:{subprogram}",
                "TEST.NEW",
                f"TEST.NAME:{case_name}",
                "TEST.NOTES:",
            ])
            if related_ids:
                lines.extend(str(r) for r in related_ids if str(r).strip())
            else:
                lines.append("TRACE/REVIEW_REQUIRED")
            lines.append("TEST.END_NOTES:")

            if precondition:
                lines.append(f"-- Precondition: {precondition}")

            # Integration nodes — must NOT be stubbed
            if integration_nodes:
                lines.append("-- Integration calls (do NOT stub — real integration required):")
                for iunit, ifunc in integration_nodes:
                    lines.append(f"--   [INTEGRATION] {iunit}.{ifunc}")

            # Input values
            for param, value in inputs.items():
                rendered = _render_value(value)
                lines.append(f"-- REVIEW PATH: TEST.VALUE:{unit}.{subprogram}.{param}:{rendered}")

            # Expected values
            for param, value in expected.items():
                rendered = _render_value(value)
                lines.append(f"-- REVIEW PATH: TEST.EXPECTED:{unit}.<<GLOBAL>>.{param}:{rendered}")

            lines.append("TEST.END")
            lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# .env template writer
# ---------------------------------------------------------------------------

def _collect_all_units(model: Dict[str, Any]) -> List[str]:
    """Collect all distinct unit names from all call chains."""
    seen: set = set()
    units: List[str] = []
    for itc in model.get("integrations") or []:
        call_chain = str(itc.get("call_chain") or "")
        for unit, _ in _parse_call_chain(call_chain):
            if unit and unit not in seen and unit != "UNKNOWN":
                seen.add(unit)
                units.append(unit)
    return units


def _write_env_template(
    model: Dict[str, Any],
    out_path: Path,
    *,
    source_root: str = "",
    compiler: str = "CC",
    project_config: Dict[str, Any] | None = None,
) -> None:
    cfg = dict(project_config or {})
    root = Path(source_root) if source_root else None
    search_paths: List[str] = []
    include_paths = [str(x).strip() for x in (cfg.get("include_paths") or []) if str(x).strip()]
    source_paths = [str(x).strip() for x in (cfg.get("source_paths") or []) if str(x).strip()]
    if include_paths or source_paths:
        for raw_path in include_paths + source_paths:
            candidate = Path(raw_path)
            if root and root.exists():
                try:
                    rel = candidate.relative_to(root)
                    search_paths.append(
                        f"ENVIRO.SEARCH_LIST: $(PROJECT_DIR)\\{rel.as_posix().replace('/', chr(92))}"
                    )
                    continue
                except Exception:
                    pass
            search_paths.append(f"ENVIRO.SEARCH_LIST: {raw_path}")
    elif root and root.exists():
        candidates = [
            root / "Sources",
            root / "Sources" / "APP",
            root / "Sources" / "IF",
            root / "Sources" / "SYSTEM",
            root / "Lib",
            root / "Generated_Code",
            root / "Project_Headers",
        ]
        for candidate in candidates:
            if candidate.exists():
                search_paths.append(
                    f"ENVIRO.SEARCH_LIST: $(PROJECT_DIR)\\{candidate.relative_to(root).as_posix().replace('/', chr(92))}"
                )

    env_name = str(model.get("project_id") or "SITS_VECTORCAST_ENV").upper()
    all_units = _collect_all_units(model)

    lines = [
        "ENVIRO.NEW",
        f"ENVIRO.NAME: {env_name}",
        f"ENVIRO.BASE_DIRECTORY: PROJECT_DIR={source_root or 'C:\\\\workspace\\\\REVIEW_REQUIRED'}",
        "ENVIRO.STUB_BY_FUNCTION: REVIEW_REQUIRED",
        "ENVIRO.WHITE_BOX: YES",
        "ENVIRO.VCDB_FILENAME: ",
        "ENVIRO.VCDB_CMD_VERB: ",
        "-- Integration coverage: use Function+Call to capture inter-unit calls",
        "ENVIRO.COVERAGE_TYPE: Function+Call",
        "ENVIRO.LIBRARY_STUBS:  ",
        "-- IMPORTANT: stub only units NOT in the integration call chains",
        "ENVIRO.STUB: ALL_BY_PROTOTYPE",
        f"ENVIRO.COMPILER: {str(cfg.get('compiler') or compiler or 'CC').strip() or 'CC'}",
        "ENVIRO.TYPE_HANDLED_DIRS_ALLOWED: ",
    ]
    lines.extend(search_paths or ["ENVIRO.SEARCH_LIST: $(PROJECT_DIR)\\Sources"])
    if cfg.get("compiler_options"):
        lines.append(f"-- Compiler Options: {' '.join(str(x) for x in cfg.get('compiler_options') or [])}")
    if cfg.get("linker"):
        lines.append(f"-- Linker: {cfg.get('linker')}")
    if cfg.get("linker_options"):
        lines.append(f"-- Linker Options: {' '.join(str(x) for x in cfg.get('linker_options') or [])}")
    if cfg.get("existing_env_file"):
        lines.append(f"-- Existing Environment File: {cfg.get('existing_env_file')}")
    if cfg.get("existing_project_file"):
        lines.append(f"-- Existing Project File: {cfg.get('existing_project_file')}")

    if all_units:
        lines.append("-- Units under test (from SITS call chains):")
        for u in all_units:
            lines.append(f"ENVIRO.UNIT_USED: {u}")

    lines.append("ENVIRO.END")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# import stub
# ---------------------------------------------------------------------------

def _write_import_stub(out_path: Path, *, project_config: Dict[str, Any] | None = None) -> None:
    cfg = dict(project_config or {})
    regression_cmd = str(cfg.get("regression_command_template") or "").strip()
    lines = [
        "@echo off",
        "setlocal",
        "REM VectorCAST SITS Integration Test import stub",
        "REM Set VECTORCAST_CLI and VECTORCAST_ENV before adapting this script.",
        "if \"%VECTORCAST_CLI%\"==\"\" (",
        "  echo [INFO] VECTORCAST_CLI is not set.",
        "  echo [INFO] Review cases.csv and import_instructions.md, then adapt this stub.",
        "  exit /b 0",
        ")",
        "if \"%VECTORCAST_ENV%\"==\"\" (",
        "  echo [INFO] VECTORCAST_ENV is not set.",
        "  exit /b 0",
        ")",
        "echo [INFO] VectorCAST SITS CLI stub prepared.",
        "echo [INFO] CLI = %VECTORCAST_CLI%",
        "echo [INFO] ENV = %VECTORCAST_ENV%",
        "echo [INFO] Adapt vectorcast_integration_tests.template.tst to your environment paths.",
        "echo [INFO] Ensure integration units are NOT stubbed before importing.",
    ]
    if regression_cmd:
        lines.extend(
            [
                "echo [INFO] Suggested regression command template:",
                f"echo [INFO] {regression_cmd}",
            ]
        )
    lines.extend([
        "exit /b 0",
    ])
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_supporting_metadata(
    model: Dict[str, Any],
    manifest: Dict[str, Any],
    out_dir: Path,
    *,
    project_config: Dict[str, Any] | None = None,
) -> None:
    cfg = dict(project_config or {})
    uut_payload = {
        "project_id": str(cfg.get("project_id") or model.get("project_id") or "").strip(),
        "units": _collect_all_units(model),
        "configured_sources": cfg.get("uut_sources") or [],
        "configured_headers": cfg.get("uut_headers") or [],
    }
    dependency_payload = {
        "dependency_sources": cfg.get("dependency_sources") or [],
        "dependency_libs": cfg.get("dependency_libs") or [],
        "dependency_objects": cfg.get("dependency_objects") or [],
        "compiler": cfg.get("compiler") or "",
        "linker": cfg.get("linker") or "",
        "compiler_options": cfg.get("compiler_options") or [],
        "linker_options": cfg.get("linker_options") or [],
        "include_paths": cfg.get("include_paths") or [],
        "source_paths": cfg.get("source_paths") or [],
    }
    mapping_payload = {
        "package_name": manifest.get("package_name"),
        "warning_count": len(model.get("export_warnings") or []),
        "warnings": model.get("export_warnings") or [],
        "integration_count": len(model.get("integrations") or []),
    }
    (out_dir / "uut_manifest.json").write_text(json.dumps(uut_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "dependency_manifest.json").write_text(
        json.dumps(dependency_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "mapping_report.json").write_text(json.dumps(mapping_payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# main entry
# ---------------------------------------------------------------------------

def export_sits_vectorcast_package(
    intermediate_json: str,
    out_dir: str,
    *,
    package_name: str = "",
    source_root: str = "",
    compiler: str = "CC",
    project_config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Generate a VectorCAST integration test package from SITS intermediate JSON.

    Args:
        intermediate_json: Path to *_vectorcast.json produced by generate_sits()
        out_dir:           Output directory for the package
        package_name:      Optional package name (defaults to out_dir stem)
        source_root:       Source code root for ENVIRO search paths
        compiler:          VectorCAST compiler name (default: CC)

    Returns:
        manifest dict with summary stats
    """
    model = _load_json(intermediate_json)
    target_dir = Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    if not package_name:
        package_name = target_dir.name

    csv_path = target_dir / "cases.csv"
    _write_cases_csv(model, csv_path)

    manifest = _build_manifest(model, package_name=package_name, csv_name=csv_path.name)
    (target_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_instructions(model, manifest, target_dir / "import_instructions.md")
    _write_tst_template(model, target_dir / "vectorcast_integration_tests.template.tst")
    _write_env_template(
        model, target_dir / "vectorcast_environment.template.env",
        source_root=source_root, compiler=compiler, project_config=project_config,
    )
    _write_import_stub(target_dir / "run_vectorcast_import.cmd", project_config=project_config)
    _write_supporting_metadata(model, manifest, target_dir, project_config=project_config)
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export VectorCAST integration test package from SITS intermediate JSON."
    )
    parser.add_argument("--input-json", required=True, help="Path to *_vectorcast.json from SITS")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    parser.add_argument("--package-name", default="")
    parser.add_argument("--source-root", default="")
    parser.add_argument("--compiler", default="CC")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    manifest = export_sits_vectorcast_package(
        args.input_json,
        args.out_dir,
        package_name=args.package_name,
        source_root=args.source_root,
        compiler=args.compiler,
    )
    summary = manifest.get("summary", {})
    print(f"SITS_VECTORCAST_PACKAGE={Path(args.out_dir).resolve()}")
    print(f"SITS_VECTORCAST_INTEGRATIONS={summary.get('integration_count')}")
    print(f"SITS_VECTORCAST_SUBCASES={summary.get('sub_case_count')}")
    print(f"SITS_VECTORCAST_WARNINGS={summary.get('warning_count')}")


if __name__ == "__main__":
    main()
