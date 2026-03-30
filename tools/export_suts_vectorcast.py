from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from openpyxl import load_workbook


_TC_SHEET = "2.SW Unit Test Spec"
_DATA_START_ROW = 7
_COMPONENT_COL = 2
_TC_ID_COL = 3
_NAME_COL = 4
_DESCRIPTION_COL = 5
_TEST_METHOD_COL = 8
_GEN_METHOD_COL = 9
_PRECONDITION_COL = 10
_SEQUENCE_TEXT_COL = 11
_TC_GEN_METHOD_COL = 12
_SEQ_NO_COL = 13
_INPUT_COL_START = 14
_INPUT_COL_END = 62
_OUTPUT_COL_START = 63
_OUTPUT_COL_END = 148
_RELATED_COL = 149
_REQ_PAT = re.compile(r"\b(?:Sw|Sy)[A-Za-z_]*_\d+\b")


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    return text


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value).strip()
    if not text or text.upper() == "N/A":
        return None
    if text.startswith("[검증 필요]"):
        return {"verification_required": True, "raw": text}
    if re.fullmatch(r"-?\d+", text):
        try:
            return int(text)
        except Exception:
            return text
    if re.fullmatch(r"-?\d+\.\d+", text):
        try:
            return float(text)
        except Exception:
            return text
    return text


def _extract_related_ids(*texts: str) -> List[str]:
    ids: List[str] = []
    for text in texts:
        for req_id in _REQ_PAT.findall(str(text or "")):
            if req_id not in ids:
                ids.append(req_id)
    return ids


def _iter_tc_blocks(ws: Any) -> Iterable[Tuple[int, int]]:
    row = _DATA_START_ROW
    max_row = ws.max_row
    while row <= max_row:
        if _clean_text(ws.cell(row=row, column=_TC_ID_COL).value):
            start = row
            row += 1
            while row <= max_row and not _clean_text(ws.cell(row=row, column=_TC_ID_COL).value):
                row += 1
            yield start, row - 1
        else:
            row += 1


def _header_names(ws: Any, row: int, col_start: int, col_end: int) -> List[Tuple[int, str]]:
    headers: List[Tuple[int, str]] = []
    for col in range(col_start, col_end + 1):
        name = _clean_text(ws.cell(row=row, column=col).value)
        if name:
            headers.append((col, name))
    return headers


def _parse_sequence_row(
    ws: Any,
    row: int,
    input_headers: List[Tuple[int, str]],
    output_headers: List[Tuple[int, str]],
    unit_meta: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    warnings: List[Dict[str, str]] = []
    seq_no = ws.cell(row=row, column=_SEQ_NO_COL).value
    seq_no_text = _clean_text(seq_no)
    sequence_no = int(seq_no) if isinstance(seq_no, int) else seq_no_text
    base_tc_id = str(unit_meta["base_tc_id"])
    sequence = {
        "name": f"{base_tc_id}__SEQ_{int(sequence_no):02d}" if str(sequence_no).isdigit() else f"{base_tc_id}__SEQ_{sequence_no_text or row}",
        "base_tc_id": base_tc_id,
        "sequence_no": sequence_no,
        "description": _clean_text(ws.cell(row=row, column=_SEQUENCE_TEXT_COL).value),
        "precondition": unit_meta.get("precondition", ""),
        "inputs": {},
        "expected": {},
        "notes": {
            "strategy": unit_meta.get("gen_method", ""),
            "test_method": unit_meta.get("test_method", ""),
        },
    }
    for col, name in input_headers:
        value = _normalize_scalar(ws.cell(row=row, column=col).value)
        if value is not None:
            sequence["inputs"][name] = value
    for col, name in output_headers:
        value = _normalize_scalar(ws.cell(row=row, column=col).value)
        if value is not None:
            sequence["expected"][name] = value
            if isinstance(value, dict) and value.get("verification_required"):
                warnings.append(
                    {
                        "code": "verification_required_expected",
                        "message": f"{unit_meta['unit_name']} seq {sequence_no}: expected '{name}' needs manual verification.",
                    }
                )
    if not sequence["expected"]:
        warnings.append(
            {
                "code": "empty_expected",
                "message": f"{unit_meta['unit_name']} seq {sequence_no}: no expected outputs mapped.",
            }
        )
    return sequence, warnings


def _parse_tc_block(ws: Any, start_row: int, end_row: int) -> Dict[str, Any]:
    component = _clean_text(ws.cell(row=start_row, column=_COMPONENT_COL).value)
    tc_id = _clean_text(ws.cell(row=start_row, column=_TC_ID_COL).value)
    unit_name = _clean_text(ws.cell(row=start_row, column=_NAME_COL).value)
    description = _clean_text(ws.cell(row=start_row, column=_DESCRIPTION_COL).value)
    precondition = _clean_text(ws.cell(row=start_row, column=_PRECONDITION_COL).value)
    test_method = _clean_text(ws.cell(row=start_row, column=_TEST_METHOD_COL).value)
    gen_method = _clean_text(ws.cell(row=start_row, column=_GEN_METHOD_COL).value) or _clean_text(
        ws.cell(row=start_row, column=_TC_GEN_METHOD_COL).value
    )
    related_token = _clean_text(ws.cell(row=start_row, column=_RELATED_COL).value)
    related_ids = _extract_related_ids(description, precondition)
    input_headers = _header_names(ws, start_row, _INPUT_COL_START, _INPUT_COL_END)
    output_headers = _header_names(ws, start_row, _OUTPUT_COL_START, _OUTPUT_COL_END)
    unit = {
        "unit_name": unit_name,
        "prototype": "",
        "component": component,
        "fid": related_token,
        "metadata": {
            "gen_method": gen_method,
            "test_method": test_method,
            "related_ids": related_ids,
        },
        "test_cases": [],
        "warnings": [],
    }
    unit_meta = {
        "unit_name": unit_name,
        "base_tc_id": tc_id,
        "precondition": precondition,
        "gen_method": gen_method,
        "test_method": test_method,
    }
    for row in range(start_row + 1, end_row + 1):
        if ws.cell(row=row, column=_SEQ_NO_COL).value in (None, ""):
            continue
        test_case, warnings = _parse_sequence_row(ws, row, input_headers, output_headers, unit_meta)
        test_case["metadata"] = {
            "related_ids": related_ids,
            "fid": related_token,
            "component": component,
        }
        test_case["source"] = {
            "sheet": _TC_SHEET,
            "tc_row": start_row,
            "sequence_row": row,
        }
        unit["test_cases"].append(test_case)
        unit["warnings"].extend(warnings)
    if not unit["test_cases"]:
        unit["warnings"].append(
            {"code": "empty_test_case_block", "message": f"{unit_name or tc_id}: no sequence rows found."}
        )
    return unit


def build_vectorcast_model(
    suts_path: str,
    *,
    project_id: str = "HDPDM01",
    target_functions: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    target_set = {str(x or "").strip().lower() for x in (target_functions or []) if str(x or "").strip()}
    workbook = load_workbook(suts_path, keep_vba=True, data_only=False)
    if _TC_SHEET not in workbook.sheetnames:
        raise ValueError(f"missing worksheet: {_TC_SHEET}")
    ws = workbook[_TC_SHEET]
    units: List[Dict[str, Any]] = []
    export_warnings: List[Dict[str, str]] = []
    for start_row, end_row in _iter_tc_blocks(ws):
        unit = _parse_tc_block(ws, start_row, end_row)
        if target_set and unit["unit_name"].strip().lower() not in target_set:
            continue
        if not unit["unit_name"]:
            export_warnings.append(
                {"code": "missing_unit_name", "message": f"TC row {start_row}: unit name is empty."}
            )
        if unit["warnings"]:
            export_warnings.extend(unit["warnings"])
        units.append(unit)
    workbook.close()
    return {
        "schema_version": "1.0",
        "project_id": project_id,
        "source": {
            "suts_path": str(Path(suts_path).resolve()),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
        "units": units,
        "export_warnings": export_warnings,
    }


def write_warnings_md(model: Dict[str, Any], out_path: str) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    warnings = list(model.get("export_warnings") or [])
    lines = [
        "# SUTS -> VectorCAST Export Warnings",
        "",
        f"- Units: `{len(model.get('units') or [])}`",
        f"- Warnings: `{len(warnings)}`",
        "",
    ]
    if not warnings:
        lines.append("- none")
    else:
        for item in warnings:
            lines.append(f"- `{item.get('code')}`: {item.get('message')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_suts_to_vectorcast_model(
    suts_path: str,
    output_json: str,
    *,
    warnings_md: str = "",
    target_functions: Optional[Iterable[str]] = None,
    project_id: str = "HDPDM01",
) -> Dict[str, Any]:
    model = build_vectorcast_model(
        suts_path,
        project_id=project_id,
        target_functions=target_functions,
    )
    out_path = Path(output_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    if warnings_md:
        write_warnings_md(model, warnings_md)
    return model


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export SUTS XLSM to VectorCAST intermediate JSON.")
    parser.add_argument("--suts-path", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--warnings-md", default="")
    parser.add_argument("--target-functions", default="")
    parser.add_argument("--project-id", default="HDPDM01")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    targets = [x.strip() for x in str(args.target_functions or "").split(",") if x.strip()]
    model = export_suts_to_vectorcast_model(
        args.suts_path,
        args.output_json,
        warnings_md=args.warnings_md,
        target_functions=targets,
        project_id=args.project_id,
    )
    print(f"VECTORCAST_JSON={Path(args.output_json).resolve()}")
    print(f"VECTORCAST_UNITS={len(model.get('units') or [])}")
    print(f"VECTORCAST_WARNINGS={len(model.get('export_warnings') or [])}")
    if args.warnings_md:
        print(f"VECTORCAST_WARNINGS_MD={Path(args.warnings_md).resolve()}")


if __name__ == "__main__":
    main()
