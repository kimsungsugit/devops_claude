from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


_FUNC_ID_PAT = re.compile(r"(?:SwUFn_|KJPDS\d+_DV_)?0*(\d{3,5})\b", re.IGNORECASE)


def _load_json(path: str) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON object expected: {path}")
    return data


def normalize_function_id(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        match = _FUNC_ID_PAT.search(text)
        if match:
            return match.group(1).zfill(4)
    return ""


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\r", "\n").split())


def _build_design_doc_record(detail: Dict[str, Any], artifact_path: str, project_id: str) -> Dict[str, Any]:
    func_id = normalize_function_id(detail.get("id"), detail.get("name"))
    func_full_id = str(detail.get("id") or "")
    related = _clean_text(detail.get("related"))
    inputs = detail.get("inputs") or []
    outputs = detail.get("outputs") or []
    lines = [
        f"[함수 ID: {func_id or func_full_id}]",
        "[설계문서]",
        f"ID: {func_full_id or '-'}",
        f"Name: {detail.get('name') or '-'}",
        f"Description: {_clean_text(detail.get('description')) or '-'}",
        "Input Parameters:",
    ]
    if inputs:
        lines.extend(f"- {_clean_text(item)}" for item in inputs)
    else:
        lines.append("- none")
    lines.append("Output Parameters:")
    if outputs:
        lines.extend(f"- {_clean_text(item)}" for item in outputs)
    else:
        lines.append("- none")
    lines.append(f"제약조건: {_clean_text(detail.get('precondition')) or '-'}")
    if related:
        lines.append(f"Related: {related}")
    return {
        "id": f"design_doc:{func_id or func_full_id}",
        "kind": "design_doc",
        "page_content": "\n".join(lines),
        "metadata": {
            "project_id": project_id,
            "kind": "design_doc",
            "function_id": func_id,
            "func_id": func_full_id,
            "function_name": str(detail.get("name") or ""),
            "component": str(detail.get("module_name") or ""),
            "type": "function",
            "related_ids": [x.strip() for x in str(detail.get("related") or "").split(",") if x.strip()],
            "asil": str(detail.get("asil") or ""),
            "artifact_path": artifact_path,
            "description_source": str(detail.get("description_source") or ""),
        },
    }


def _build_source_code_record(detail: Dict[str, Any], artifact_path: str, project_id: str) -> Dict[str, Any]:
    func_id = normalize_function_id(detail.get("id"), detail.get("name"))
    func_full_id = str(detail.get("id") or "")
    file_path = str(detail.get("file") or "")
    snippet_lines = [
        f"[함수 ID: {func_id or func_full_id}]",
        "[소스코드]",
        f"[파일]: {file_path or '-'}",
        _clean_text(detail.get("prototype")) or f"{detail.get('name') or '-'}(...)",
    ]
    logic_condition = _clean_text(detail.get("logic_condition"))
    if logic_condition:
        snippet_lines.append(f"if ({logic_condition}) ...")
    logic_return = _clean_text(detail.get("logic_return_path"))
    if logic_return:
        snippet_lines.append(f"return path: {logic_return}")
    return {
        "id": f"source_code:{func_id or func_full_id}:{Path(file_path).name if file_path else 'unknown'}",
        "kind": "source_code",
        "page_content": "\n".join(snippet_lines),
        "metadata": {
            "project_id": project_id,
            "kind": "source_code",
            "function_id": func_id,
            "func_id": func_full_id,
            "function_name": str(detail.get("name") or ""),
            "component": str(detail.get("module_name") or ""),
            "source_file": file_path,
            "artifact_path": artifact_path,
        },
    }


def _build_testcase_records(vector_model: Dict[str, Any], artifact_path: str, project_id: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for unit in vector_model.get("units") or []:
        unit_name = str(unit.get("unit_name") or "")
        unit_fid = str(unit.get("fid") or "")
        unit_function_id = normalize_function_id(unit_fid, unit_name)
        unit_component = _clean_text(unit.get("component"))
        for case in unit.get("test_cases") or []:
            function_id = normalize_function_id(
                (case.get("metadata") or {}).get("fid"),
                unit_fid,
                case.get("base_tc_id"),
                unit_name,
            ) or unit_function_id
            related_ids = list((case.get("metadata") or {}).get("related_ids") or (unit.get("metadata") or {}).get("related_ids") or [])
            lines = [
                f"[FUNCTION_NAME] {unit_name}",
                f"[FUNCTION_ID] {function_id or unit_fid}",
                f"[TESTCASE] {case.get('name') or '-'}",
            ]
            if related_ids:
                lines.append(f"[REQUIREMENTS] {', '.join(str(x) for x in related_ids)}")
            lines.append("[INPUT DATA]")
            inputs = case.get("inputs") or {}
            if inputs:
                for name, value in inputs.items():
                    lines.append(f"- {name}: {value}")
            else:
                lines.append("- none")
            lines.append("[EXPECTED DATA]")
            expected = case.get("expected") or {}
            if expected:
                for name, value in expected.items():
                    lines.append(f"- {name}: {value}")
            else:
                lines.append("- none")
            records.append(
                {
                    "id": f"testcase:{function_id or unit_fid}:{case.get('name') or case.get('base_tc_id')}",
                    "kind": "testcase",
                    "page_content": "\n".join(lines),
                    "metadata": {
                        "project_id": project_id,
                        "kind": "testcase",
                        "function_id": function_id,
                        "func_id": unit_fid,
                        "function_name": unit_name,
                        "component": unit_component,
                        "testcase_name": str(case.get("name") or ""),
                        "env_name": str(project_id),
                        "unit_under_test": unit_component or unit_name,
                        "subprogram": unit_name,
                        "related_ids": related_ids,
                        "artifact_path": artifact_path,
                        "chunk_order": int(case.get("sequence_no") or 0) if str(case.get("sequence_no") or "").isdigit() else 0,
                    },
                }
            )
    return records


def _build_supplement_records(vector_model: Dict[str, Any], artifact_path: str, project_id: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for index, warning in enumerate(vector_model.get("export_warnings") or [], start=1):
        message = _clean_text(warning.get("message"))
        code = str(warning.get("code") or "")
        function_id = normalize_function_id(message)
        function_name = ""
        for unit in vector_model.get("units") or []:
            if function_id and normalize_function_id(unit.get("fid"), unit.get("unit_name")) == function_id:
                function_name = str(unit.get("unit_name") or "")
                break
        records.append(
            {
                "id": f"supplement:{function_id or 'unknown'}:{index:03d}",
                "kind": "supplement",
                "page_content": "\n".join(
                    [
                        f"[함수 ID: {function_id or '-'}]",
                        f"함수명: {function_name or '-'}",
                        f"[보강정보] {message or '-'}",
                    ]
                ),
                "metadata": {
                    "project_id": project_id,
                    "kind": "supplement",
                    "function_id": function_id,
                    "func_id": "",
                    "function_name": function_name,
                    "warning_code": code,
                    "artifact_path": artifact_path,
                },
            }
        )
    return records


def export_function_knowledge(
    *,
    output_json: str,
    output_jsonl: str = "",
    uds_payload: str = "",
    vectorcast_json: str = "",
    project_id: str = "HDPDM01",
) -> Dict[str, Any]:
    records: List[Dict[str, Any]] = []
    if uds_payload:
        uds_data = _load_json(uds_payload)
        func_details = uds_data.get("function_details") or {}
        artifact_path = str(uds_data.get("docx_path") or uds_payload)
        for detail in func_details.values():
            if not isinstance(detail, dict):
                continue
            records.append(_build_design_doc_record(detail, artifact_path, project_id))
            records.append(_build_source_code_record(detail, artifact_path, project_id))
    if vectorcast_json:
        vector_data = _load_json(vectorcast_json)
        artifact_path = str(vector_data.get("source", {}).get("suts_path") or vectorcast_json)
        records.extend(_build_testcase_records(vector_data, artifact_path, project_id))
        records.extend(_build_supplement_records(vector_data, artifact_path, project_id))
    payload = {
        "schema_version": "1.0",
        "project_id": project_id,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "record_count": len(records),
        "records": records,
    }
    out_json = Path(output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if output_jsonl:
        out_jsonl = Path(output_jsonl)
        out_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with out_jsonl.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export unified function knowledge records for RAG/search.")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-jsonl", default="")
    parser.add_argument("--uds-payload", default="")
    parser.add_argument("--vectorcast-json", default="")
    parser.add_argument("--project-id", default="HDPDM01")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    payload = export_function_knowledge(
        output_json=args.output_json,
        output_jsonl=args.output_jsonl,
        uds_payload=args.uds_payload,
        vectorcast_json=args.vectorcast_json,
        project_id=args.project_id,
    )
    print(f"FUNCTION_KNOWLEDGE_JSON={Path(args.output_json).resolve()}")
    if args.output_jsonl:
        print(f"FUNCTION_KNOWLEDGE_JSONL={Path(args.output_jsonl).resolve()}")
    print(f"FUNCTION_KNOWLEDGE_RECORDS={payload['record_count']}")


if __name__ == "__main__":
    main()
