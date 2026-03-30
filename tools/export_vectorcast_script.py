from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List


_FID_PAT = re.compile(r"(SwUFn_\d+)")


def _load_json(path: str) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("intermediate model must be a JSON object")
    return data


def _build_script_case_name(base_tc_id: str, fid: str, sequence_no: Any, fallback_name: str) -> str:
    stem = ""
    for candidate in (fid, base_tc_id, fallback_name):
        match = _FID_PAT.search(str(candidate or ""))
        if match:
            stem = match.group(1)
            break
    if not stem:
        return fallback_name
    seq_text = str(sequence_no or "").strip()
    if seq_text.isdigit():
        return f"{stem}.{int(seq_text):03d}"
    return f"{stem}.{seq_text or '001'}"


def _normalize_component_name(component: str, unit_name: str) -> str:
    value = " ".join(str(component or "").replace("\r", "\n").split()).strip()
    if not value:
        return str(unit_name or "").strip()
    paren_matches = re.findall(r"\(([^()]+)\)", value)
    if paren_matches:
        value = paren_matches[-1].strip()
    for suffix in ("_PDS", "_C", ".c"):
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value


def _iter_case_rows(model: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for unit in model.get("units") or []:
        unit_name = str(unit.get("unit_name") or "")
        fid = str(unit.get("fid") or "")
        component = str(unit.get("component") or "")
        unit_scope = _normalize_component_name(component, unit_name)
        unit_meta = unit.get("metadata") or {}
        unit_related = unit_meta.get("related_ids") or []
        unit_warning_count = len(unit.get("warnings") or [])
        for case in unit.get("test_cases") or []:
            case_meta = case.get("metadata") or {}
            related_ids = case_meta.get("related_ids") or unit_related
            sequence_no = case.get("sequence_no")
            script_case_name = _build_script_case_name(
                str(case.get("base_tc_id") or ""),
                fid or str(case_meta.get("fid") or ""),
                sequence_no,
                str(case.get("name") or ""),
            )
            yield {
                "unit_name": unit_name,
                "unit_scope": unit_scope,
                "fid": fid or str(case_meta.get("fid") or ""),
                "component": component or str(case_meta.get("component") or ""),
                "test_case_name": str(case.get("name") or ""),
                "vectorcast_script_name": script_case_name,
                "base_tc_id": str(case.get("base_tc_id") or ""),
                "sequence_no": sequence_no,
                "description": str(case.get("description") or ""),
                "precondition": str(case.get("precondition") or ""),
                "test_method": str((case.get("notes") or {}).get("test_method") or unit_meta.get("test_method") or ""),
                "strategy": str((case.get("notes") or {}).get("strategy") or unit_meta.get("gen_method") or ""),
                "related_ids": ", ".join(str(x) for x in related_ids if str(x).strip()),
                "inputs_json": json.dumps(case.get("inputs") or {}, ensure_ascii=False),
                "expected_json": json.dumps(case.get("expected") or {}, ensure_ascii=False),
                "source_sheet": str((case.get("source") or {}).get("sheet") or ""),
                "source_tc_row": (case.get("source") or {}).get("tc_row"),
                "source_sequence_row": (case.get("source") or {}).get("sequence_row"),
                "unit_warning_count": unit_warning_count,
            }


def _write_cases_csv(model: Dict[str, Any], out_path: Path) -> int:
    rows = list(_iter_case_rows(model))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "unit_name",
        "unit_scope",
        "fid",
        "component",
        "test_case_name",
        "vectorcast_script_name",
        "base_tc_id",
        "sequence_no",
        "description",
        "precondition",
        "test_method",
        "strategy",
        "related_ids",
        "inputs_json",
        "expected_json",
        "source_sheet",
        "source_tc_row",
        "source_sequence_row",
        "unit_warning_count",
    ]
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def _build_manifest(model: Dict[str, Any], *, package_name: str, csv_name: str) -> Dict[str, Any]:
    units = list(model.get("units") or [])
    total_cases = sum(len(unit.get("test_cases") or []) for unit in units)
    return {
        "package_name": package_name,
        "schema_version": "1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": model.get("source") or {},
        "summary": {
            "unit_count": len(units),
            "test_case_count": total_cases,
            "warning_count": len(model.get("export_warnings") or []),
        },
        "artifacts": {
            "cases_csv": csv_name,
            "import_instructions": "import_instructions.md",
            "import_stub_cmd": "run_vectorcast_import.cmd",
            "test_script_template": "vectorcast_tests.template.tst",
            "environment_template": "vectorcast_environment.template.env",
            "uut_manifest": "uut_manifest.json",
            "dependency_manifest": "dependency_manifest.json",
            "mapping_report": "mapping_report.json",
        },
    }


def _write_instructions(model: Dict[str, Any], manifest: Dict[str, Any], out_path: Path) -> None:
    summary = manifest.get("summary") or {}
    source = model.get("source") or {}
    lines = [
        "# VectorCAST Import Package",
        "",
        f"- Package: `{manifest.get('package_name')}`",
        f"- Source SUTS: `{source.get('suts_path') or '-'}`",
        f"- Units: `{summary.get('unit_count')}`",
        f"- Test cases: `{summary.get('test_case_count')}`",
        f"- Export warnings: `{summary.get('warning_count')}`",
        "",
        "## Included Files",
        "",
        "- `manifest.json`",
        "- `cases.csv`",
        "- `vectorcast_tests.template.tst`",
        "- `vectorcast_environment.template.env`",
        "- `run_vectorcast_import.cmd`",
        "",
        "## Mapping Notes",
        "",
        "- `test_case_name` maps to the VectorCAST test case name candidate.",
        "- `vectorcast_script_name` follows the `SwUFn_xxxx.001` style observed in existing VectorCAST `.tst` samples.",
        "- `inputs_json` and `expected_json` keep original scalar assignments from SUTS.",
        "- Any value marked with `verification_required=true` must be reviewed before import.",
        "- `related_ids` can be copied into VectorCAST notes or trace fields.",
        "",
        "## Recommended Import Workflow",
        "",
        "1. Review `vectorcast_environment.template.env` and align compiler/search paths with the local VectorCAST environment.",
        "2. Review `vectorcast_tests.template.tst` and replace placeholder object paths with actual parameter/global paths from the environment.",
        "3. Use `cases.csv` as the review source for test case names, inputs, and expected outputs.",
        "4. Review rows that correspond to warnings before creating final test cases.",
        "5. Record the environment name and any manual stub/global setup needed.",
        "",
        "## Warning Policy",
        "",
        "- This package is aligned to the `.tst/.env` structure observed under `TResultParser`, but still requires environment-specific object path review.",
        "- The provided `.cmd` file is a stub/template, not a guaranteed direct importer.",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


def _render_vectorcast_value(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("verification_required"):
            return str(value.get("raw") or "")
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _write_test_script_template(model: Dict[str, Any], out_path: Path) -> None:
    lines: List[str] = [
        "-- VectorCAST template script generated from SUTS intermediate JSON",
        "-- REVIEW REQUIRED: adjust TEST.UNIT / TEST.SUBPROGRAM object paths and stub commands before import.",
        "--",
        "",
    ]
    for unit in model.get("units") or []:
        unit_name = str(unit.get("unit_name") or "")
        unit_scope = _normalize_component_name(str(unit.get("component") or ""), unit_name)
        lines.append(f"-- Unit: {unit_scope}")
        lines.append(f"-- Subprogram: {unit_name}")
        lines.append("")
        for case in unit.get("test_cases") or []:
            case_name = _build_script_case_name(
                str(case.get("base_tc_id") or ""),
                str(unit.get("fid") or ""),
                case.get("sequence_no"),
                str(case.get("name") or ""),
            )
            related_ids = (case.get("metadata") or {}).get("related_ids") or (unit.get("metadata") or {}).get("related_ids") or []
            lines.extend(
                [
                    f"-- Test Case: {case_name}",
                    f"TEST.UNIT:{unit_scope}",
                    f"TEST.SUBPROGRAM:{unit_name}",
                    "TEST.NEW",
                    f"TEST.NAME:{case_name}",
                    "TEST.NOTES:",
                ]
            )
            if related_ids:
                lines.extend(str(x) for x in related_ids if str(x).strip())
            else:
                lines.append("TRACE/REVIEW_REQUIRED")
            lines.append("TEST.END_NOTES:")
            for name, value in (case.get("inputs") or {}).items():
                rendered = _render_vectorcast_value(value)
                lines.append(f"-- REVIEW PATH: TEST.VALUE:{unit_scope}.{unit_name}.{name}:{rendered}")
            for name, value in (case.get("expected") or {}).items():
                rendered = _render_vectorcast_value(value)
                if isinstance(value, dict) and value.get("verification_required"):
                    lines.append(f"-- REVIEW EXPECTED: {name} => {rendered}")
                else:
                    lines.append(f"-- REVIEW PATH: TEST.EXPECTED:{unit_scope}.<<GLOBAL>>.{name}:{rendered}")
            lines.append("TEST.END")
            lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def _write_environment_template(
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
                    search_paths.append(f"ENVIRO.SEARCH_LIST: $(PROJECT_DIR)\\{rel.as_posix().replace('/', chr(92))}")
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
                search_paths.append(f"ENVIRO.SEARCH_LIST: $(PROJECT_DIR)\\{candidate.relative_to(root).as_posix().replace('/', '\\')}")
    env_name = str(model.get("project_id") or "VECTORCAST_ENV").upper()
    lines = [
        "ENVIRO.NEW",
        f"ENVIRO.NAME: {env_name}",
        f"ENVIRO.BASE_DIRECTORY: PROJECT_DIR={source_root or 'C:\\\\workspace\\\\REVIEW_REQUIRED'}",
        "ENVIRO.STUB_BY_FUNCTION: REVIEW_REQUIRED",
        "ENVIRO.WHITE_BOX: YES",
        "ENVIRO.VCDB_FILENAME: ",
        "ENVIRO.VCDB_CMD_VERB: ",
        "ENVIRO.COVERAGE_TYPE: Statement+Branch",
        "ENVIRO.LIBRARY_STUBS:  ",
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
    lines.append("ENVIRO.END")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_import_stub(out_path: Path, *, project_config: Dict[str, Any] | None = None) -> None:
    cfg = dict(project_config or {})
    regression_cmd = str(cfg.get("regression_command_template") or "").strip()
    lines = [
        "@echo off",
        "setlocal",
        "REM VectorCAST import stub template",
        "REM Set VECTORCAST_CLI and VECTORCAST_ENV before adapting this script to your local VectorCAST installation.",
        "if \"%VECTORCAST_CLI%\"==\"\" (",
        "  echo [INFO] VECTORCAST_CLI is not set.",
        "  echo [INFO] Review cases.csv and import_instructions.md, then adapt this stub for your environment.",
        "  exit /b 0",
        ")",
        "if \"%VECTORCAST_ENV%\"==\"\" (",
        "  echo [INFO] VECTORCAST_ENV is not set.",
        "  echo [INFO] Review cases.csv and import_instructions.md, then adapt this stub for your environment.",
        "  exit /b 0",
        ")",
        "echo [INFO] VectorCAST CLI stub prepared.",
        "echo [INFO] CLI = %VECTORCAST_CLI%",
        "echo [INFO] ENV = %VECTORCAST_ENV%",
        "echo [INFO] Replace this file with project-specific import commands after confirming local VectorCAST syntax.",
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
        "units": [
            {
                "unit_name": str(unit.get("unit_name") or ""),
                "component": str(unit.get("component") or ""),
                "fid": str(unit.get("fid") or ""),
                "test_case_count": len(unit.get("test_cases") or []),
            }
            for unit in model.get("units") or []
        ],
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
        "units_with_manual_review": [
            str(unit.get("unit_name") or "")
            for unit in model.get("units") or []
            if unit.get("warnings")
        ],
    }
    (out_dir / "uut_manifest.json").write_text(json.dumps(uut_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "dependency_manifest.json").write_text(
        json.dumps(dependency_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "mapping_report.json").write_text(json.dumps(mapping_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def export_vectorcast_package(
    intermediate_json: str,
    out_dir: str,
    *,
    package_name: str = "",
    source_root: str = "",
    compiler: str = "CC",
    project_config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    model = _load_json(intermediate_json)
    target_dir = Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    if not package_name:
        package_name = target_dir.name
    csv_path = target_dir / "cases.csv"
    _write_cases_csv(model, csv_path)
    manifest = _build_manifest(model, package_name=package_name, csv_name=csv_path.name)
    (target_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_instructions(model, manifest, target_dir / "import_instructions.md")
    _write_test_script_template(model, target_dir / "vectorcast_tests.template.tst")
    _write_environment_template(
        model,
        target_dir / "vectorcast_environment.template.env",
        source_root=source_root,
        compiler=compiler,
        project_config=project_config,
    )
    _write_import_stub(target_dir / "run_vectorcast_import.cmd", project_config=project_config)
    _write_supporting_metadata(model, manifest, target_dir, project_config=project_config)
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export VectorCAST package from intermediate SUTS JSON.")
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--package-name", default="")
    parser.add_argument("--source-root", default="")
    parser.add_argument("--compiler", default="CC")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    manifest = export_vectorcast_package(
        args.input_json,
        args.out_dir,
        package_name=args.package_name,
        source_root=args.source_root,
        compiler=args.compiler,
    )
    print(f"VECTORCAST_PACKAGE={Path(args.out_dir).resolve()}")
    print(f"VECTORCAST_CASES={manifest['summary']['test_case_count']}")
    print(f"VECTORCAST_UNITS={manifest['summary']['unit_count']}")
    print(f"VECTORCAST_WARNINGS={manifest['summary']['warning_count']}")


if __name__ == "__main__":
    main()
