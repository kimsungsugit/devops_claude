from __future__ import annotations

import json
from pathlib import Path

from backend.helpers.vectorcast import build_vectorcast_metadata, evaluate_vectorcast_readiness, load_vectorcast_project_config


def test_load_vectorcast_project_config_uses_default_paths(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "Sources").mkdir(parents=True)
    (src / "Project_Headers").mkdir(parents=True)

    cfg = load_vectorcast_project_config(project_id="missing", source_root=str(src))

    assert cfg["compiler"] == "CC"
    assert str((src / "Sources").resolve()) in cfg["include_paths"]
    assert str((src / "Project_Headers").resolve()) in cfg["source_paths"]


def test_load_vectorcast_project_config_reads_project_file(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "vectorcast_projects"
    config_dir.mkdir(parents=True)
    (config_dir / "demo.json").write_text(
        json.dumps(
            {
                "project_id": "demo",
                "compiler": "GHS",
                "dependency_libs": ["demo.lib"],
                "regression_command_template": "vcast -e demo_env",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("backend.helpers.vectorcast.VECTORCAST_CONFIG_DIR", config_dir)

    cfg = load_vectorcast_project_config(project_id="demo")

    assert cfg["compiler"] == "GHS"
    assert cfg["dependency_libs"] == ["demo.lib"]
    assert cfg["regression_command_template"] == "vcast -e demo_env"


def test_vectorcast_readiness_reports_import_ready() -> None:
    metadata = build_vectorcast_metadata(
        project_config={
            "project_id": "demo",
            "compiler": "CC",
            "include_paths": ["D:/src/Include"],
            "source_paths": ["D:/src/Sources"],
            "dependency_libs": ["dep.lib"],
        },
        source_root="D:/src",
        units=["UnitA"],
    )

    readiness = evaluate_vectorcast_readiness(metadata)

    assert readiness["status"] == "IMPORT_READY"
    assert readiness["summary"]["required_ok"] is True


def test_vectorcast_readiness_reports_template_only_when_required_missing() -> None:
    metadata = build_vectorcast_metadata(project_config={"project_id": "demo"}, units=[])

    readiness = evaluate_vectorcast_readiness(metadata)

    assert readiness["status"] == "TEMPLATE_ONLY"
    assert any(item["name"] == "paths" and item["ok"] is False for item in readiness["checks"])


def test_load_builtin_hdpdm01_config() -> None:
    cfg = load_vectorcast_project_config(project_id="hdpdm01")

    assert cfg["project_id"] == "HDPDM01"
    assert cfg["source_root"].endswith("PDS64_RD")
    assert any(path.endswith("Project_Headers") for path in cfg["include_paths"])
