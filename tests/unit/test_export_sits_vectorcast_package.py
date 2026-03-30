from __future__ import annotations

import json
from pathlib import Path

from tools.export_sits_vectorcast_package import export_sits_vectorcast_package


def _sample_model() -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "TEST",
        "source": {"sits_path": "D:/tmp/sample.xlsm"},
        "integrations": [
            {
                "tc_id": "SwITC_01",
                "entry_fn": "MainEntry",
                "call_chain": "Cpu.MainEntry -> Eeprom.Init",
                "module_name": "Cpu",
                "gen_method": "AOR",
                "asil": "QM",
                "metadata": {"related_ids": ["SwTR_0001"]},
                "sub_cases": [
                    {
                        "case_num": 1,
                        "case_label": "1",
                        "precondition": "power on",
                        "inputs": {"InputA": 1},
                        "expected": {"OutputA": 2},
                    }
                ],
            }
        ],
        "export_warnings": [{"code": "review", "message": "manual review"}],
    }


def test_export_sits_vectorcast_package_writes_supporting_metadata(tmp_path: Path) -> None:
    input_json = tmp_path / "input.json"
    out_dir = tmp_path / "pkg"
    input_json.write_text(json.dumps(_sample_model(), ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = export_sits_vectorcast_package(
        str(input_json),
        str(out_dir),
        project_config={
            "project_id": "TEST",
            "compiler": "GHS",
            "include_paths": ["D:/Project/Ados/PDS64_RD/Sources"],
            "dependency_objects": ["startup.obj"],
        },
    )

    assert manifest["artifacts"]["uut_manifest"] == "uut_manifest.json"
    assert (out_dir / "uut_manifest.json").exists()
    assert (out_dir / "dependency_manifest.json").exists()
    assert (out_dir / "mapping_report.json").exists()

    env_text = (out_dir / "vectorcast_environment.template.env").read_text(encoding="utf-8")
    dep = json.loads((out_dir / "dependency_manifest.json").read_text(encoding="utf-8"))

    assert "ENVIRO.COMPILER: GHS" in env_text
    assert dep["dependency_objects"] == ["startup.obj"]
