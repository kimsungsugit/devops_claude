from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook

from tools.export_suts_vectorcast import build_vectorcast_model, export_suts_to_vectorcast_model


def _make_sample_suts(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "2.SW Unit Test Spec"
    ws.cell(row=6, column=2, value="Component")
    ws.cell(row=6, column=3, value="TC ID")
    ws.cell(row=6, column=4, value="Name")
    ws.cell(row=6, column=5, value="Description")
    ws.cell(row=6, column=8, value="Test Method")
    ws.cell(row=6, column=9, value="Gen.Method")
    ws.cell(row=6, column=10, value="Precondition")
    ws.cell(row=6, column=11, value="Sequence")
    ws.cell(row=6, column=12, value="Test Case Gen.Method")
    ws.cell(row=6, column=13, value="Seq. No.")

    # TC block 1
    ws.cell(row=7, column=2, value="SwCom_01")
    ws.cell(row=7, column=3, value="SwUTC_SwUFn_0001")
    ws.cell(row=7, column=4, value="g_TestFunc")
    ws.cell(row=7, column=5, value="desc\n[SRS: SwTR_0001]")
    ws.cell(row=7, column=8, value="FIT")
    ws.cell(row=7, column=9, value="ABV")
    ws.cell(row=7, column=10, value="precondition")
    ws.cell(row=7, column=14, value="u8g_InA")
    ws.cell(row=7, column=15, value="u8g_InB")
    ws.cell(row=7, column=63, value="u8s_OutA")
    ws.cell(row=7, column=149, value="SwUFn_0001")

    ws.cell(row=8, column=11, value="seq-1")
    ws.cell(row=8, column=13, value=1)
    ws.cell(row=8, column=14, value=1)
    ws.cell(row=8, column=15, value=2)
    ws.cell(row=8, column=63, value=3)

    ws.cell(row=9, column=11, value="seq-2")
    ws.cell(row=9, column=13, value=2)
    ws.cell(row=9, column=14, value=10)
    ws.cell(row=9, column=15, value=20)
    ws.cell(row=9, column=63, value="[검증 필요] 30")

    # TC block 2
    ws.cell(row=10, column=2, value="SwCom_02")
    ws.cell(row=10, column=3, value="SwUTC_SwUFn_0002")
    ws.cell(row=10, column=4, value="s_AnotherFunc")
    ws.cell(row=10, column=5, value="another desc")
    ws.cell(row=10, column=8, value="FNCT")
    ws.cell(row=10, column=9, value="AEC, ABV")
    ws.cell(row=10, column=14, value="g_Input")
    ws.cell(row=10, column=63, value="g_Output")
    ws.cell(row=10, column=149, value="SwUFn_0002")

    ws.cell(row=11, column=11, value="seq-1")
    ws.cell(row=11, column=13, value=1)
    ws.cell(row=11, column=14, value=0)
    ws.cell(row=11, column=63, value=1)

    wb.save(path)
    wb.close()


def test_build_vectorcast_model_parses_tc_blocks(tmp_path: Path) -> None:
    suts_path = tmp_path / "sample.xlsm"
    _make_sample_suts(suts_path)

    model = build_vectorcast_model(str(suts_path), project_id="TEST")

    assert model["project_id"] == "TEST"
    assert len(model["units"]) == 2
    assert model["units"][0]["unit_name"] == "g_TestFunc"
    assert len(model["units"][0]["test_cases"]) == 2
    assert model["units"][0]["test_cases"][0]["inputs"] == {"u8g_InA": 1, "u8g_InB": 2}
    assert model["units"][0]["test_cases"][0]["expected"] == {"u8s_OutA": 3}
    assert model["units"][0]["test_cases"][1]["expected"]["u8s_OutA"]["verification_required"] is True


def test_build_vectorcast_model_filters_target_functions(tmp_path: Path) -> None:
    suts_path = tmp_path / "sample.xlsm"
    _make_sample_suts(suts_path)

    model = build_vectorcast_model(str(suts_path), target_functions=["s_AnotherFunc"])

    assert len(model["units"]) == 1
    assert model["units"][0]["unit_name"] == "s_AnotherFunc"


def test_export_suts_to_vectorcast_model_writes_outputs(tmp_path: Path) -> None:
    suts_path = tmp_path / "sample.xlsm"
    json_path = tmp_path / "out.json"
    warnings_path = tmp_path / "warnings.md"
    _make_sample_suts(suts_path)

    model = export_suts_to_vectorcast_model(
        str(suts_path),
        str(json_path),
        warnings_md=str(warnings_path),
    )

    assert json_path.exists()
    assert warnings_path.exists()
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == "1.0"
    assert len(model["export_warnings"]) >= 1
