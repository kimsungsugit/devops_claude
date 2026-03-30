from __future__ import annotations

import csv
import json
from pathlib import Path

from tools.export_vectorcast_script import export_vectorcast_package


def _sample_model() -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "TEST",
        "source": {"suts_path": "D:/tmp/sample.xlsm"},
        "units": [
            {
                "unit_name": "g_TestFunc",
                "prototype": "void g_TestFunc(void)",
                "component": "SwCom_01",
                "fid": "SwUFn_0001",
                "metadata": {"related_ids": ["SwTR_0001"], "gen_method": "ABV", "test_method": "FIT"},
                "warnings": [{"code": "verification_required_expected", "message": "manual review"}],
                "test_cases": [
                    {
                        "name": "SwUTC_SwUFn_0001__SEQ_01",
                        "base_tc_id": "SwUTC_SwUFn_0001",
                        "sequence_no": 1,
                        "description": "desc",
                        "precondition": "pre",
                        "inputs": {"u8g_Input": 1},
                        "expected": {"u8s_Output": 2},
                        "notes": {"strategy": "ABV", "test_method": "FIT"},
                        "metadata": {"related_ids": ["SwTR_0001"], "fid": "SwUFn_0001", "component": "SwCom_01"},
                        "source": {"sheet": "2.SW Unit Test Spec", "tc_row": 7, "sequence_row": 8},
                    }
                ],
            }
        ],
        "export_warnings": [{"code": "verification_required_expected", "message": "manual review"}],
    }


def test_export_vectorcast_package_writes_expected_files(tmp_path: Path) -> None:
    input_json = tmp_path / "input.json"
    out_dir = tmp_path / "pkg"
    input_json.write_text(json.dumps(_sample_model(), ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = export_vectorcast_package(str(input_json), str(out_dir), package_name="sample_pkg")

    assert manifest["package_name"] == "sample_pkg"
    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "cases.csv").exists()
    assert (out_dir / "import_instructions.md").exists()
    assert (out_dir / "run_vectorcast_import.cmd").exists()
    assert (out_dir / "vectorcast_tests.template.tst").exists()
    assert (out_dir / "vectorcast_environment.template.env").exists()
    assert (out_dir / "uut_manifest.json").exists()
    assert (out_dir / "dependency_manifest.json").exists()
    assert (out_dir / "mapping_report.json").exists()


def test_export_vectorcast_package_csv_contains_case_rows(tmp_path: Path) -> None:
    input_json = tmp_path / "input.json"
    out_dir = tmp_path / "pkg"
    input_json.write_text(json.dumps(_sample_model(), ensure_ascii=False, indent=2), encoding="utf-8")

    export_vectorcast_package(str(input_json), str(out_dir))

    with (out_dir / "cases.csv").open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["unit_name"] == "g_TestFunc"
    assert rows[0]["test_case_name"] == "SwUTC_SwUFn_0001__SEQ_01"
    assert rows[0]["vectorcast_script_name"] == "SwUFn_0001.001"


def test_export_vectorcast_package_writes_template_content(tmp_path: Path) -> None:
    input_json = tmp_path / "input.json"
    out_dir = tmp_path / "pkg"
    input_json.write_text(json.dumps(_sample_model(), ensure_ascii=False, indent=2), encoding="utf-8")

    export_vectorcast_package(str(input_json), str(out_dir), source_root="D:/Project/Ados/PDS64_RD")

    tst_text = (out_dir / "vectorcast_tests.template.tst").read_text(encoding="utf-8")
    env_text = (out_dir / "vectorcast_environment.template.env").read_text(encoding="utf-8")

    assert "TEST.UNIT:SwCom_01" in tst_text
    assert "TEST.SUBPROGRAM:g_TestFunc" in tst_text
    assert "TEST.NAME:SwUFn_0001.001" in tst_text
    assert "ENVIRO.NEW" in env_text
    assert "ENVIRO.COMPILER: CC" in env_text


def test_export_vectorcast_package_applies_project_config_metadata(tmp_path: Path) -> None:
    input_json = tmp_path / "input.json"
    out_dir = tmp_path / "pkg"
    input_json.write_text(json.dumps(_sample_model(), ensure_ascii=False, indent=2), encoding="utf-8")

    export_vectorcast_package(
        str(input_json),
        str(out_dir),
        project_config={
            "project_id": "TEST",
            "compiler": "GHS",
            "linker": "ghsld",
            "include_paths": ["D:/Project/Ados/PDS64_RD/Project_Headers"],
            "dependency_libs": ["libhal.lib"],
            "regression_command_template": "vcastcli -e TEST",
        },
    )

    env_text = (out_dir / "vectorcast_environment.template.env").read_text(encoding="utf-8")
    dep = json.loads((out_dir / "dependency_manifest.json").read_text(encoding="utf-8"))
    bat_text = (out_dir / "run_vectorcast_import.cmd").read_text(encoding="utf-8")

    assert "ENVIRO.COMPILER: GHS" in env_text
    assert "-- Linker: ghsld" in env_text
    assert dep["dependency_libs"] == ["libhal.lib"]
    assert "Suggested regression command template" in bat_text
