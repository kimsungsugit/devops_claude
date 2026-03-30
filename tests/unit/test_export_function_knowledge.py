from __future__ import annotations

import json
from pathlib import Path

from tools.export_function_knowledge import export_function_knowledge, normalize_function_id


def test_normalize_function_id_extracts_numeric_portion() -> None:
    assert normalize_function_id("SwUFn_0101") == "0101"
    assert normalize_function_id("KJPDS02_DV_0121") == "0121"
    assert normalize_function_id("0121") == "0121"


def test_export_function_knowledge_writes_records(tmp_path: Path) -> None:
    uds_path = tmp_path / "uds.payload.json"
    vector_path = tmp_path / "vector.json"
    out_json = tmp_path / "knowledge.json"
    out_jsonl = tmp_path / "knowledge.jsonl"

    uds_path.write_text(
        json.dumps(
            {
                "docx_path": "D:/tmp/sample.docx",
                "function_details": {
                    "SwUFn_0101": {
                        "id": "SwUFn_0101",
                        "name": "g_TestFunc",
                        "prototype": "void g_TestFunc(void)",
                        "description": "sample desc",
                        "related": "SwTR_0001",
                        "inputs": ["[IN] a"],
                        "outputs": ["[OUT] return 0"],
                        "precondition": "none",
                        "file": "D:/tmp/test.c",
                        "module_name": "Ap_Test",
                        "asil": "QM",
                        "description_source": "sds",
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    vector_path.write_text(
        json.dumps(
            {
                "project_id": "TEST",
                "source": {"suts_path": "D:/tmp/suts.xlsm"},
                "units": [
                    {
                        "unit_name": "g_TestFunc",
                        "component": "Ap_Test",
                        "fid": "SwUFn_0101",
                        "metadata": {"related_ids": ["SwTR_0001"]},
                        "test_cases": [
                            {
                                "name": "SwUTC_SwUFn_0101__SEQ_01",
                                "base_tc_id": "SwUTC_SwUFn_0101",
                                "sequence_no": 1,
                                "inputs": {"a": 1},
                                "expected": {"ret": 0},
                                "metadata": {"fid": "SwUFn_0101", "related_ids": ["SwTR_0001"]},
                            }
                        ],
                    }
                ],
                "export_warnings": [{"code": "empty_expected", "message": "SwUFn_0101 seq 1 warning"}],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = export_function_knowledge(
        output_json=str(out_json),
        output_jsonl=str(out_jsonl),
        uds_payload=str(uds_path),
        vectorcast_json=str(vector_path),
        project_id="TEST",
    )

    assert payload["record_count"] == 4
    assert out_json.exists()
    assert out_jsonl.exists()

    kinds = [record["kind"] for record in payload["records"]]
    assert "design_doc" in kinds
    assert "source_code" in kinds
    assert "testcase" in kinds
    assert "supplement" in kinds
