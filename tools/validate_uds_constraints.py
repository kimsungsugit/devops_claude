from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import jsonschema  # type: ignore
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import report_generator as rg


def _build_payload(source_root: str) -> Dict[str, object]:
    sections = rg.generate_uds_source_sections(source_root)
    by_name = sections.get("function_details_by_name", {}) or {}
    funcs: List[Dict[str, object]] = []
    for _, info in by_name.items():
        if not isinstance(info, dict):
            continue
        funcs.append(
            {
                "id": str(info.get("id") or ""),
                "name": str(info.get("name") or ""),
                "description": str(info.get("description") or ""),
                "description_source": str(info.get("description_source") or ""),
                "asil": str(info.get("asil") or ""),
                "related": str(info.get("related") or ""),
                "inputs": list(info.get("inputs") or []),
                "outputs": list(info.get("outputs") or []),
                "globals_global": list(info.get("globals_global") or []),
                "globals_static": list(info.get("globals_static") or []),
                "called": str(info.get("called") or ""),
                "calling": str(info.get("calling") or ""),
            }
        )
    return {"functions": funcs}


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate UDS constraints by jsonschema")
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--schema", default=str(ROOT / "docs" / "uds_constraints.schema.json"))
    ap.add_argument("--out", default=str(ROOT / "reports" / "uds" / "uds_constraints_validation.md"))
    args = ap.parse_args()

    schema_path = Path(args.schema)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    payload = _build_payload(args.source_root)

    errors: List[str] = []
    validator = jsonschema.Draft202012Validator(schema)
    for err in validator.iter_errors(payload):
        path = ".".join([str(x) for x in err.absolute_path])
        errors.append(f"{path}: {err.message}")
        if len(errors) >= 300:
            break

    out_md = Path(args.out)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json = out_md.with_suffix(".json")
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: List[str] = []
    lines.append("# UDS Constraint Validation Report")
    lines.append("")
    lines.append(f"- Source root: `{args.source_root}`")
    lines.append(f"- Schema: `{schema_path}`")
    lines.append(f"- Functions: `{len(payload.get('functions') or [])}`")
    lines.append(f"- Valid: `{'False' if errors else 'True'}`")
    lines.append("")
    lines.append("## Errors (Top 300)")
    lines.extend([f"- {e}" for e in errors] if errors else ["- none"])
    lines.append("")
    lines.append(f"- Payload JSON: `{out_json}`")
    out_md.write_text("\n".join(lines), encoding="utf-8")

    print(f"CONSTRAINT_MD={out_md}")
    print(f"CONSTRAINT_JSON={out_json}")


if __name__ == "__main__":
    main()
