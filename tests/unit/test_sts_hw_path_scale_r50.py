"""R50 — the monitor path through HSIS, the monitor-node scale through the HW design specification.

R49 left most HW tolerance notes "감시 경로 미정" (a hub system block links several HW blocks) and a node tolerance
(``Monitor전압: 2.5V(±0.15V)``) "척도 불명" at a 4.85 V threshold. Two documents already in the project settle part of it
without a guess:

* the HSIS row of the fact's SW signal (``u16g_ApiIn_Vsup`` · ``u16g_ApiIn_MagnetLevel`` — the same name, or the same name
  under another layer, ``u16g_DrvIn_Vsup``; the direction kept) names system IDs and a net: the one candidate block that
  alone cites one of those IDs, or whose text names that net as a whole token, is the path — unless that block's name is
  another signal's (``Hall Sensor Block 전원 Monitor`` for ``V_MAGNET_MON``): then the documents disagree and it is shown;
* the HW design specification's component block citing a HW requirement block that writes a monitor node gives the node's
  ratio (``모니터 전압 = Hall Sensor Power *0.5``): the node tolerance ``±0.3V`` is ``±0.6V`` on the supply's scale —
  applied only where the value is off the node's scale and on the converted one, and not where the fact's HSIS row names
  another node than the formula.
"""
from __future__ import annotations

from collections import Counter

import docx
import openpyxl
import pytest

from generators.sts import _build_tc_dict, _classify_steps, _make_tc_id
from generators.sts_requirement_tc import (
    MAX_HW_TOLERANCES,
    REQUIREMENT_EVIDENCE_HEADERS,
    _formula_scales,
    _hsis_pick,
    _hsis_row,
    _tolerance_note,
    append_requirement_boundary_tcs,
    apply_hw_design,
    boundary_steps,
    hsis_rows_from_signals,
    hw_tolerance_summary,
    hw_tolerances_for,
    load_hw_design,
    parse_hw_design_docx,
    parse_hw_requirement_docx,
    write_requirement_evidence_sheet,
)

BATTERY = {"name": "Battery Voltage Monitor", "related": ["SySM_04", "SyTSR_0116"],
           "tolerances": [{"text": "허용 오차: ±3%", "value": "3", "unit": "%", "measured_units": ["V"]}],
           "ranges": [{"lo": "9", "hi": "16", "unit": "V"}], "nominals": [], "monitor_node": False,
           "full_text": "Battery Voltage Monitor\nMultiLink Debugger를 통해 V-BAT 변수 값 확인", "scales": []}
NODE = {"name": "Hall Sensor Block 전원 Monitor", "related": ["SySM_04", "SyTSR_0114"],
        "tolerances": [{"text": "허용 오차: ±0.3V", "value": "0.3", "unit": "V", "measured_units": []}],
        "ranges": [], "nominals": [{"value": "2.5", "unit": "V"}], "monitor_node": True,
        "full_text": "Hall Sensor Block 전원 Monitor전압: 2.5V(±0.3V)", "scales": []}
HALL_SCALE = {"k": "0.5", "side": "lhs", "to_source": "2", "source": "design",
              "via": "HwC_07 Sensor Power Switch: 모니터 전압 = Hall Sensor Power *0.5",
              "formula": "모니터 전압 = Hall Sensor Power *0.5"}
ROWS = [{"id": "HSI_30", "vars": ["u16g_DrvIn_Vsup"], "ids": ["SyEI_01", "SySM_04"], "nets": ["V-BAT"], "name": "V-BAT"},
        {"id": "HSI_24", "vars": ["u16g_ApiIn_MagnetLevel"], "ids": ["SySM_04", "SyTSR_0114"],
         "nets": ["V_MAGNET_MON"], "name": "V_MAGNET_MON"},
        {"id": "HSI_23", "vars": ["u16g_ApiIn_HallSnsrLevel"], "ids": ["SyTSR_0109"], "nets": ["VCC_HALL_MON"],
         "name": "VCC_HALL_MON"}]


# (R54) the HW tolerance column by name — an AI column follows it
_HW_COL = REQUIREMENT_EVIDENCE_HEADERS.index("HW Tolerance (Quoted)")

def _req(desc, related, rid="SwTSR_0101"):
    return {"id": rid, "name": "n", "description": desc, "verification": "", "asil": "B", "related_id": related}


def _evidence(desc, related="SySM_04"):
    (g,) = [g for g in boundary_steps(_req(desc, related)) if g["evidence"]["kind"] == "threshold"]
    return g["evidence"]


def _hw(**blocks):
    return {k: {**v, "related": list(v["related"])} for k, v in blocks.items()}


def _row(signal, rows=ROWS):
    return _hsis_row(signal, rows)


def test_a_formula_names_which_side_is_the_monitor_node():
    assert _formula_scales("Sensor Power Monitor = Sensor Power *0.5") == [
        {"k": "0.5", "side": "lhs", "to_source": "2", "via": "Sensor Power Monitor = Sensor Power *0.5",
         "formula": "Sensor Power Monitor = Sensor Power *0.5"}]
    assert _formula_scales("모니터 전압 = Hall Sensor Power *0.5")[0]["to_source"] == "2"
    assert _formula_scales("Battery Voltage = Monitor Voltage * 9")[0]["to_source"] == "9"
    # both or neither side a monitor: which is the node is not written
    assert _formula_scales("Monitor A = Monitor B * 2") == [] and _formula_scales("Speed = Frequency * 12") == []


def test_a_formula_that_is_no_divider_ratio():
    """(review W3a · I4) HDPDM01 HwTSR_0101 ``모터사용 전류(A) = 모니터 전압((V)*6`` converts volts to amperes; an offset
    after the factor, or a time, is no ratio; a non-terminating ratio is rounded up, never printed to 28 digits."""
    assert _formula_scales("모터사용 전류(A) = 모니터 전압((V)*6") == []
    assert _formula_scales("Monitor Current = Sense Voltage * 2") == []
    assert _formula_scales("Monitor Voltage = Output Signal * 0.2 + 0.1") == []
    assert _formula_scales("Monitoring Period = Base Period * 10") == []
    assert _formula_scales("Monitor Voltage = Output Signal * 0.3")[0]["to_source"] == "3.333334"
    # the unit written after the factor is no offset
    assert _formula_scales("Buzzer(ON) Monitor 전압 = Buzzer 출력 전압 * 0.2V , (오차: ±10%)")[0]["to_source"] == "5"


def _docx(path, tables):
    d = docx.Document()
    for rows in tables:
        t = d.add_table(rows=len(rows), cols=2)
        for row, (k, v) in zip(t.rows, rows, strict=True):
            row.cells[0].text, row.cells[1].text = k, v
    d.save(path)
    return str(path)


def test_the_design_block_citing_the_requirement_gives_its_ratio(tmp_path):
    path = _docx(tmp_path / "hds.docx", [
        [("ID", "HwC_07"), ("Name", "Sensor Power Switch"),
         ("Description", "전원을 공급하거나 차단 / 모니터 전압 = Hall Sensor Power *0.5"), ("Related ID", "HwTR_0701, HwTSR_0203")],
        [("ID", "HwI_14"), ("Name", "Motor Speed"), ("Description", "펄스"), ("Related ID", "HwTR_0605")],
    ])
    design = parse_hw_design_docx(path)
    assert design["HwC_07"] == {"name": "Sensor Power Switch", "related": ["HwTR_0701", "HwTSR_0203"],
                                "scales": [{"k": "0.5", "side": "lhs", "to_source": "2", "source": "design",
                                            "formula": "모니터 전압 = Hall Sensor Power *0.5",
                                            "via": "HwC_07 Sensor Power Switch: 모니터 전압 = Hall Sensor Power *0.5"}]}
    _d, record = load_hw_design(path)
    assert record == {"file": "hds.docx", "blocks": 2, "blocks_with_formula": 1}
    assert load_hw_design(None) == (None, None) and "error" in load_hw_design(str(tmp_path / "x.docx"))[1]
    # (review W3b) the power switch HwTR_0701 (its 5 V is the source) takes no ratio: it writes no monitor node
    switch = {**NODE, "name": "Motor Encoder Block Power Switch", "monitor_node": False, "related": ["SyTR_0604"]}
    hw = _hw(HwTSR_0203=NODE, HwTSR_0204=BATTERY, HwTR_0701=switch)
    assert apply_hw_design(hw, design) == {"design": 1, "own": 0}
    assert (hw["HwTSR_0203"]["to_source"], hw["HwTSR_0203"]["scale"]["source"]) == ("2", "design")
    assert "to_source" not in hw["HwTSR_0204"] and "scale" not in hw["HwTR_0701"]
    # two different ratios for one block: a conflict, never a choice
    conflict = {"HwC_01": {"name": "a", "related": ["HwTSR_0203"],
                           "scales": [{**HALL_SCALE, "k": "3", "side": "rhs", "to_source": "3", "via": "x"}]}}
    hw = _hw(HwTSR_0203=NODE)
    assert apply_hw_design(hw, {**design, **conflict}) == {"design": 0, "own": 0}
    assert len(hw["HwTSR_0203"]["scale_conflict"]) == 2


def test_a_block_own_formula_is_counted_as_its_own():
    """(review W4) a ratio the HW requirement block writes itself is not the design's — counted and said apart."""
    own = {**NODE, "scales": [{**HALL_SCALE, "source": "own", "via": "HwTSR_0203: Monitor = Hall Sensor Power *0.5"}]}
    hw = _hw(HwTSR_0203=own)
    assert apply_hw_design(hw, None) == {"design": 0, "own": 1}
    assert hw["HwTSR_0203"]["scale"]["source"] == "own"


def test_a_design_field_over_two_rows_is_read_whole(tmp_path):
    """(review I4) the HW requirement parser joins a field written over several rows — the design parser too."""
    path = _docx(tmp_path / "hds.docx", [[("ID", "HwC_07"), ("Name", "Sensor Power Switch"), ("Description", "전원 차단"),
                                         ("Description", "Sensor Power Monitor = Sensor Power *0.5"),
                                         ("Related ID", "HwTSR_0203")]])
    assert parse_hw_design_docx(path)["HwC_07"]["scales"][0]["to_source"] == "2"


def test_a_node_tolerance_is_put_on_the_value_scale_only_where_it_fits():
    """PV HwTSR_0203 ``2.5V(±0.3V)`` × 2 (HwC_07): at 4.85 V (supply side) ±0.6V; at 8.9 V (battery) still unknown."""
    hw = _hw(HwTSR_0203={**NODE, "scale": HALL_SCALE})
    (t,) = hw_tolerances_for(_req("", "SySM_04"), _evidence("- u16g_ApiIn_HallSnsrLevel 이 4.85V 이하 시 고장"), hw)
    assert (t["scale_known"], t["size"], t["scaled_by"].startswith("HwC_07")) == (True, "0.6", True)
    assert t["scale"] == {"via": HALL_SCALE["via"], "source": "design", "check": "no_hsis"}
    (t,) = hw_tolerances_for(_req("", "SySM_04"), _evidence("- u16g_ApiIn_HallSnsrLevel 이 4.85V 이하 시 고장"), hw, ROWS)
    assert t["scale"]["check"] == "confirmed"           # VCC_HALL_MON · HallSnsrLevel name the hall node
    (t,) = hw_tolerances_for(_req("", "SySM_04"), _evidence("- 입력전원 8.9V 미만 시 저전압"), hw)
    assert (t["scale_known"], t["scaled_by"]) == (False, None)
    # a relative tolerance is never "scaled"
    (t,) = hw_tolerances_for(_req("", "SySM_04"), _evidence("- 입력전원 8.9V 미만 시 저전압"),
                             {"HwTSR_0204": {**BATTERY, "scale": {**HALL_SCALE, "k": "9", "side": "rhs"}}})
    assert t["scaled_by"] is None and t["size"] == "0.267"


def test_a_formula_of_another_node_is_not_applied():
    """(review W2) HDPDM01: HSIS writes MagnetLevel on ``V_MAGNET_MON`` (PAD7); HwC_07's formula is the Hall supply's
    (``VCC_HALL_MON`` — PAD5). The magnet threshold is not scaled by it: shown, not computed."""
    hw = _hw(HwTSR_0203={**NODE, "scale": HALL_SCALE})
    (t,) = hw_tolerances_for(_req("", "SySM_04"), _evidence("- u16g_ApiIn_MagnetLevel 이 4.85V 이하 시 고장"), hw, ROWS)
    assert (t["scale_known"], t["scaled_by"]) == (False, None)
    assert t["scale_net_mismatch"] == {"formula": HALL_SCALE["via"], "row": "HSI_24", "name": "V_MAGNET_MON"}
    e = _evidence("- u16g_ApiIn_MagnetLevel 이 4.85V 이하 시 고장")
    e["hw_tolerance"] = [t]
    wb = openpyxl.Workbook()
    write_requirement_evidence_sheet(wb, [{"id": "T", "srs_id": "SwTSR_0101", "requirement_evidence": [e]}])
    cell = list(wb["Requirement Evidence"].iter_rows(values_only=True))[1][_HW_COL]
    assert "HSIS HSI_24(V_MAGNET_MON) 와 다른 노드 — 환산 안 함" in cell


def test_two_ratios_are_shown_not_chosen():
    """(review W6) the conflict is in the cell and the summary — 'scale unknown' alone hides that two documents differ."""
    hw = _hw(HwTSR_0203={**NODE, "scale_conflict": ["HwC_07: a *0.5", "HwC_01: b *3"]})
    e = _evidence("- u16g_ApiIn_HallSnsrLevel 이 4.85V 이하 시 고장")
    e["hw_tolerance"] = hw_tolerances_for(_req("", "SySM_04"), e, hw)
    assert e["hw_tolerance"][0]["scale_conflict"] == ["HwC_07: a *0.5", "HwC_01: b *3"]
    assert hw_tolerance_summary(e)["scale_conflict"] is True
    wb = openpyxl.Workbook()
    write_requirement_evidence_sheet(wb, [{"id": "T", "srs_id": "SwTSR_0101", "requirement_evidence": [e]}])
    assert "척도 불명 — 분압비 충돌: HwC_07: a *0.5 ↔ HwC_01: b *3" in \
        list(wb["Requirement Evidence"].iter_rows(values_only=True))[1][_HW_COL]


def test_the_hsis_row_of_a_sw_signal():
    assert _row("u16g_ApiIn_MagnetLevel")["id"] == "HSI_24"
    row = _row("u16g_ApiIn_Vsup")                                     # another layer, the same name
    assert (row["id"], row["matched"]) == ("HSI_30", "u16g_DrvIn_Vsup")
    assert _row("입력전원") is None and _row("u16g_ApiIn_Other") is None
    twice = ROWS + [{"id": "HSI_31", "vars": ["u16g_SrvIn_Vsup"], "ids": [], "nets": []}]
    assert _row("u16g_ApiIn_Vsup", twice) is None                      # two rows: no one row
    # (review I2) the direction is part of the name: a LIN output row is not an input's
    lin = [{"id": "HSI_13", "vars": ["u8g_ApiOut_BattLvl"], "ids": ["SyEIF_01"], "nets": ["LIN_BUS"]}]
    assert _row("u8g_ApiIn_BattLvl", lin) is None and _row("u8g_DrvOut_BattLvl", lin)["matched"] == "u8g_ApiOut_BattLvl"


def test_hsis_rows_come_from_the_generator_reader():
    """(review I3) one HSIS reader: the rows are `_load_hsis_signals`' signals (header-based, both layouts)."""
    signals = [{"id": "HSI_30", "signal_name": "VCC_BAT", "sw_var_name": "u16g_DrvIn_Vsup", "related_id": "SyTR_0401"},
               {"id": "HSI_13", "signal_name": "LIN_BUS", "sw_var_name": "u8g_ApiOut_DoorAngle,\nu8g_ApiOut_BattLvl",
                "related_id": "SyEIF_01"},
               {"id": "", "signal_name": "Battery Power", "sw_var_name": "u16g_ApiIn_Vsup", "related_id": "SyEI_01"},
               {"id": "HSI_07", "signal_name": "GO_SENSORPWR_EN", "sw_var_name": "PTADL_PTADL4", "related_id": ""}]
    rows = hsis_rows_from_signals(signals)
    assert rows == [
        {"id": "HSI_30", "vars": ["u16g_DrvIn_Vsup"], "ids": ["SyTR_0401"], "nets": ["VCC_BAT"], "name": "VCC_BAT"},
        {"id": "HSI_13", "vars": ["u8g_ApiOut_DoorAngle", "u8g_ApiOut_BattLvl"], "ids": ["SyEIF_01"],
         "nets": ["LIN_BUS"], "name": "LIN_BUS"},
        {"id": "", "vars": ["u16g_ApiIn_Vsup"], "ids": ["SyEI_01"], "nets": [], "name": "Battery Power"}]
    assert hsis_rows_from_signals(None) == []


def test_the_row_picks_the_block_by_its_own_id_or_net():
    hw = _hw(HwTSR_0203=NODE, HwTSR_0204=BATTERY)
    cands = [{"hw_id": "HwTSR_0203"}, {"hw_id": "HwTSR_0204"}]
    hall = [{"id": "HSI_23", "vars": ["u16g_ApiIn_HallSnsrLevel"], "ids": ["SyTSR_0114"], "nets": ["VCC_HALL_MON"],
             "name": "VCC_HALL_MON"}]
    # SyTSR_0114 only the node monitor cites; SySM_04 (the hub) both cite — it decides nothing
    pick, refused = _hsis_pick(_row("u16g_ApiIn_HallSnsrLevel", hall), cands, hw)
    assert (pick["hw_id"], pick["by"], pick["anchor"], pick["row"], pick["names_checked"], refused) == \
        ("HwTSR_0203", "system_id", "SyTSR_0114", "HSI_23", True, None)
    # no own ID in the row: its net ``V-BAT`` is in the Battery monitor's verification text alone (a whole token)
    pick, _r = _hsis_pick(_row("u16g_ApiIn_Vsup"), cands, hw)
    assert (pick["hw_id"], pick["by"], pick["anchor"], pick["var"]) == ("HwTSR_0204", "net", "V-BAT", "u16g_DrvIn_Vsup")
    # neither: undecided stays undecided
    assert _hsis_pick(_row("u16g_ApiIn_HallSnsrLevel"), cands, hw) == (None, None)
    assert _hsis_pick(_row("u16g_ApiIn_Vsup"), cands[:1], hw) == (None, None)         # one candidate only
    assert _hsis_pick(None, cands, hw) == (None, None)


def test_the_row_pointing_to_another_signal_block_is_refused():
    """(review W2) HDPDM01 MagnetLevel: HSIS HSI_24 (V_MAGNET_MON) names SyTSR_0114, which only HwTSR_0203 'Hall Sensor
    Block 전원 Monitor' cites — two documents, two different signals: no path, and the TC says so."""
    hw = _hw(HwTSR_0203=NODE, HwTSR_0204=BATTERY)
    pick, refused = _hsis_pick(_row("u16g_ApiIn_MagnetLevel"), [{"hw_id": "HwTSR_0203"}, {"hw_id": "HwTSR_0204"}], hw)
    assert pick is None and (refused["hw_id"], refused["row_name"], refused["block_name"]) == \
        ("HwTSR_0203", "V_MAGNET_MON", "Hall Sensor Block 전원 Monitor")
    tcs = []

    def build(**kw):
        return _build_tc_dict(test_env="HILS", derive_inputs=False, is_safety=False, **kw)
    stats = append_requirement_boundary_tcs(
        tcs, [_req("- u16g_ApiIn_MagnetLevel 가 4.85V 미만 시 고장", "SySM_04", "SwTSR_0101")], build, _make_tc_id,
        _classify_steps, hw={"HwTSR_0203": {**NODE, "nominals": [{"value": "5", "unit": "V"}]}, "HwTSR_0204": BATTERY},
        hsis_rows=ROWS)
    note = tcs[0]["precondition"]
    assert "감시 경로 미정" in note and "HSIS HSI_24(V_MAGNET_MON) 가 가리키는 HwTSR_0203(Hall Sensor Block 전원 Monitor) 는 " \
        "이름이 다른 신호 — 감시 블록이 후보 밖이거나 문서가 서로 다름, 경로로 쓰지 않음(확인)" in note
    assert (stats["hw_tolerance_path_refused"], stats["hw_tolerance_path_by_hsis"]) == (1, 0)


def test_a_net_is_matched_as_a_whole_token_among_the_blocks_the_ids_left():
    """(review W5) ``VCC_BAT`` is not in ``VCC_BAT_MON``; an ID that left two blocks keeps the net search among them."""
    a = {**BATTERY, "name": "Battery A", "full_text": "VCC_BAT_MON 측정", "related": ["SySM_04", "SyX_01"]}
    b = {**BATTERY, "name": "Battery B", "full_text": "VCC_BAT 측정", "related": ["SySM_04", "SyX_02"]}
    c = {**BATTERY, "name": "Battery C", "full_text": "VCC_BAT 측정", "related": ["SySM_04"]}
    row = {"id": "HSI_30", "vars": ["u16g_DrvIn_Vsup"], "ids": ["SyX_01", "SyX_02"], "nets": ["VCC_BAT"],
           "name": "VCC_BAT", "matched": "u16g_DrvIn_Vsup"}
    hw = _hw(HwA_01=a, HwB_01=b, HwC_01=c)
    pick, _r = _hsis_pick(row, [{"hw_id": k} for k in hw], hw)
    assert (pick["hw_id"], pick["by"]) == ("HwB_01", "net")          # C names the net too, but the IDs left A · B
    # (review I1) the variable shown is the one the fact's signal matched, not the row's first
    two = dict(row, vars=["u16g_DrvIn_Other", "u16g_DrvIn_Vsup"])
    assert _hsis_pick(_row("u16g_ApiIn_Vsup", [two]), [{"hw_id": k} for k in hw], hw)[0]["var"] == "u16g_DrvIn_Vsup"
    by_id = dict(two, ids=["SyX_02"])
    assert _hsis_pick(_row("u16g_ApiIn_Vsup", [by_id]), [{"hw_id": k} for k in hw], hw)[0]["var"] == "u16g_DrvIn_Vsup"


def test_the_hsis_block_is_kept_when_the_candidates_are_cut():
    """(review C1) four indirect candidates, the HSIS row's block sorting last by shared IDs: it is moved ahead of the
    other indirect ones — the evidence keeps three, and the note cites from them (IndexError lost every boundary TC)."""
    hub = {"name": "Power Monitor", "tolerances": [{"text": "허용 오차: ±0.5V", "value": "0.5", "unit": "V",
                                                    "measured_units": []}],
           "ranges": [{"lo": "0", "hi": "10", "unit": "V"}], "nominals": [], "monitor_node": False, "full_text": "",
           "scales": []}
    hw = {f"HwA_0{i}": {**hub, "name": f"Power Monitor {i}", "related": ["SySM_04", "SyEL_01", "SyEL_02"]}
          for i in range(1, 4)}
    hw["HwZ_09"] = {**hub, "name": "Magnet Monitor", "related": ["SySM_04", "SyTSR_0114"]}
    rows = [{"id": "HSI_24", "vars": ["u16g_ApiIn_MagnetLevel"], "ids": ["SyTSR_0114"], "nets": [], "name": "Magnet"}]
    req = _req("- u16g_ApiIn_MagnetLevel 가 4.85V 미만 시 고장", "SySM_04, SyEL_01, SyEL_02, SyTSR_0114")
    cands = hw_tolerances_for(req, _evidence(req["description"], req["related_id"]), hw, rows)
    assert [t["hw_id"] for t in cands][0] == "HwZ_09" and cands[0]["hsis"]["anchor"] == "SyTSR_0114"
    tcs = []

    def build(**kw):
        return _build_tc_dict(test_env="HILS", derive_inputs=False, is_safety=False, **kw)
    stats = append_requirement_boundary_tcs(tcs, [req], build, _make_tc_id, _classify_steps, hw=hw, hsis_rows=rows)
    assert "error" not in stats and len(tcs[0]["requirement_evidence"][0]["hw_tolerance"]) == MAX_HW_TOLERANCES
    assert "HW 측정 허용오차(HwZ_09 ±0.5V, HSIS HSI_24 로 경로 확정)가" in tcs[0]["precondition"]


def test_the_summary_the_note_and_the_cell():
    hw = _hw(HwTSR_0203=NODE, HwTSR_0204=BATTERY)
    e = _evidence("- u16g_ApiIn_Vsup 가 8.50V 미만 시 저전압")
    e["hw_tolerance"] = hw_tolerances_for(_req("", "SySM_04"), e, hw, ROWS)
    s = hw_tolerance_summary(e)
    assert (s["certain"], s["by_hsis"], s["blocks"], s["largest"]) == (True, True, ["HwTSR_0204"], "0.255")
    tcs = []

    def build(**kw):
        return _build_tc_dict(test_env="HILS", derive_inputs=False, is_safety=False, **kw)
    stats = append_requirement_boundary_tcs(tcs, [_req("- u16g_ApiIn_Vsup 가 8.50V 미만 시 저전압", "SySM_04", "SwTSR_0104")],
                                            build, _make_tc_id, _classify_steps, hw=hw, hsis_rows=ROWS)
    assert "HW 측정 허용오차(HwTSR_0204 ±0.255V, HSIS HSI_30 로 경로 확정)가" in tcs[0]["precondition"]
    assert (stats["hw_tolerance_path_by_hsis"], stats["hw_tolerance_path_undecided"], stats["hw_tolerance_scaled"]) == \
        (1, 0, 0)
    wb = openpyxl.Workbook()
    write_requirement_evidence_sheet(wb, tcs)
    cell = list(wb["Requirement Evidence"].iter_rows(values_only=True))[1][_HW_COL]
    assert "[HSIS HSI_30 u16g_DrvIn_Vsup → 네트 V-BAT]" in cell and not cell.startswith("감시 경로 미정")
    # the fact's own system block still comes first: a direct candidate is never overridden by HSIS
    direct = [dict(t, direct=t["hw_id"] == "HwTSR_0203") for t in e["hw_tolerance"]]
    assert hw_tolerance_summary(e, direct)["blocks"] == ["HwTSR_0203"]


def test_the_note_says_where_the_ratio_came_from_and_what_checked_it():
    """(review W4) a ratio from the HW requirement's own formula is not the design's; (W2) one not checked against the
    fact's HSIS row says so."""
    e = _evidence("- u16g_ApiIn_HallSnsrLevel 이 4.85V 이하 시 고장")
    e["hw_tolerance"] = hw_tolerances_for(_req("", "SySM_04"), e, _hw(HwTSR_0203={**NODE, "scale": {
        **HALL_SCALE, "source": "own", "via": "HwTSR_0203: Monitor = Hall Sensor Power *0.5"}}), [])
    note = _tolerance_note(e)
    assert "HW 요구 블록의 식으로 척도 환산(HSIS 에 이 신호 행 없음 — 네트 미확인)" in note
    assert hw_tolerance_summary(e)["scale_unconfirmed"] is True
    # a Korean subject is no SW variable: no row could be looked up — said so, not "no row"
    k = _evidence("- 센서 전원 4.85V 이하 시 고장")
    (t,) = hw_tolerances_for(_req("", "SySM_04"), k, _hw(HwTSR_0203={**NODE, "scale": HALL_SCALE}), [])
    assert t["scale"]["check"] == "not_sw"


def test_why_hsis_did_not_narrow_is_counted():
    """(review I8) PV: SRS ``u16g_ApiIn_HallSnsrLevel`` · HSIS ``DrvIn_VCC_HALL_MON`` — no row; a Korean subject is no
    SW variable. Both counted, so the disclosure says why the path stayed undecided."""
    hw = _hw(HwTSR_0203={**NODE, "nominals": [{"value": "5", "unit": "V"}]}, HwTSR_0204=BATTERY)
    tcs = []

    def build(**kw):
        return _build_tc_dict(test_env="HILS", derive_inputs=False, is_safety=False, **kw)
    reqs = [_req("- u16g_ApiIn_OtherLevel 가 4.85V 미만 시 고장", "SySM_04", "SwTSR_0101"),
            _req("- 입력전원 4.85V 미만 시 고장", "SySM_04", "SwTSR_0102"),
            # a row that names nothing only one candidate has (HSI_23's SyTSR_0109 — neither block cites it)
            _req("- u16g_ApiIn_HallSnsrLevel 가 4.85V 미만 시 고장", "SySM_04", "SwTSR_0103")]
    stats = append_requirement_boundary_tcs(tcs, reqs, build, _make_tc_id, _classify_steps, hw=hw, hsis_rows=ROWS)
    assert (stats["hw_tolerance_undecided_no_row"], stats["hw_tolerance_undecided_not_sw"],
            stats["hw_tolerance_undecided_row_silent"]) == (1, 1, 1)
    bare = append_requirement_boundary_tcs([], reqs, build, _make_tc_id, _classify_steps, hw=hw)
    assert "hw_tolerance_undecided_no_row" not in bare           # HSIS not given: not "0 without a row"


def test_the_generator_records_the_design_and_the_hsis(tmp_path):
    from generators.sts import generate_sts
    text = ["SwTSR_0101: u16g_ApiIn_HallSnsrLevel 이 4.85V 이하 시 고장을 검출한다. Related ID: SySM_04"]
    hrs = _docx(tmp_path / "hrs.docx", [[("ID", "HwTSR_0203"), ("Name", "Hall Sensor Block 전원 Monitor"),
                                         ("Description", "Monitor전압: 2.5V(±0.3V) / 허용 오차: ±0.3V"),
                                         ("Related ID", "SySM_04")]])
    hds = _docx(tmp_path / "hds.docx", [[("ID", "HwC_07"), ("Name", "Sensor Power Switch"),
                                         ("Description", "Sensor Power Monitor = Sensor Power *0.5"),
                                         ("Related ID", "HwTSR_0203")]])
    ok = generate_sts(text, {}, str(tmp_path / "a.xlsm"), project_config={"project_id": "T"}, hwrs_path=hrs, hwds_path=hds)
    rb = ok["quality_report"]["generation_stats"]["requirement_boundary"]
    assert rb["hw_design_document"] == {"file": "hds.docx", "blocks": 1, "blocks_with_formula": 1, "ratios": 1,
                                        "ratios_by_source": {"design": 1, "own": 0}}
    assert rb["hw_hsis"] == {"given": False} and rb["hw_tolerance_scaled"] == 1 and rb["hw_tolerance_scale_unconfirmed"] == 1
    # the HSIS given: its rows are the generator's HSIS signals (one reader)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "2. HSIS"
    ws.append(["", "", "", "", "", "ID", "Signal Name", "Signal Type", "", "", "", "Direction", "Characteristics", "", "",
               "", "", "", "", "SW Variable Name", "Related ID"])
    ws.append(["", "", "", "", "", "HSI_23", "VCC_HALL_MON", "Analog", "", "", "", "IN", "Analog Input", "", "", "", "",
               "", "", "u16g_ApiIn_HallSnsrLevel", "SyTSR_0109"])
    wb.save(tmp_path / "hsis.xlsx")
    with_hsis = generate_sts(text, {}, str(tmp_path / "h.xlsm"), project_config={"project_id": "T"}, hwrs_path=hrs,
                             hwds_path=hds, hsis_path=str(tmp_path / "hsis.xlsx"))
    rb = with_hsis["quality_report"]["generation_stats"]["requirement_boundary"]
    assert rb["hw_hsis"] == {"given": True, "rows": 1, "signals": 1} and rb["hw_tolerance_scale_unconfirmed"] == 0
    # not given / not localised (the HwDS reason is the design record's, not the system documents')
    none = generate_sts(text, {}, str(tmp_path / "b.xlsm"), project_config={"project_id": "T"}, hwrs_path=hrs,
                        system_input_skips=["HwDS: 파일 없음 (x)"])
    rb = none["quality_report"]["generation_stats"]["requirement_boundary"]
    assert rb["hw_design_document"] == {"file": "", "error": "HwDS: 파일 없음 (x)", "ratios": 0,
                                        "ratios_by_source": {"design": 0, "own": 0}}
    assert not rb.get("system_input_skips")
    # (review I5) a HW design without the HW requirements: recorded as unused, never silently dropped
    bare = generate_sts(text, {}, str(tmp_path / "c.xlsm"), project_config={"project_id": "T"}, hwds_path=hds)
    rb = bare["quality_report"]["generation_stats"]["requirement_boundary"]
    assert rb["hw_design_document"]["unused"] == "no_hwrs" and rb["hw_document"] == {"given": False}
    assert "HW 설계서는 줬지만 그것이 환산할 HW 요구사항서가 없어 쓰지 않았다" in _disclosure(rb)["note"]


def _disclosure(rb):
    from report_gen.generation_disclosures import build_disclosures
    items = {i["key"]: i for i in build_disclosures("sts", {"generation_stats": {"requirement_boundary": rb}})}
    return items.get("sts_hw_tolerance")


def test_the_disclosure_says_what_narrowed_and_what_would():
    base = {"tcs": 1, "steps": 3, "facts": 1, "facts_used": 1, "hw_tolerance_groups": 10, "hw_tolerance_inside_step": 9,
            "hw_document": {"file": "hrs.docx", "blocks": 47, "blocks_with_tolerance": 4}}
    assert "HSIS" not in _disclosure(base)["note"]                      # before R50: nothing said
    note = _disclosure({**base, "hw_design_document": {"given": False, "ratios": 0}, "hw_hsis": {"given": False}})["note"]
    assert "HSIS 를 주면" in note and "HW 설계서(HwDS)를 주면" in note
    note = _disclosure({**base, "hw_tolerance_path_by_hsis": 4, "hw_tolerance_scaled": 9, "hw_tolerance_path_refused": 2,
                        "hw_tolerance_undecided_no_row": 3,
                        "hw_design_document": {"file": "hds.docx", "blocks": 45, "blocks_with_formula": 2, "ratios": 1,
                                               "ratios_by_source": {"design": 1, "own": 0}},
                        "hw_hsis": {"given": True, "rows": 11}})["note"]
    assert "HSIS 로 감시 경로를 정한 경계 4 개" in note and "척도를 환산한 경계 9 개" in note
    assert "분압식이 있는 감시 노드 블록 HW 설계서 1 · HW 요구 자체 식 0 개" in note
    assert "경로로 쓰지 않은 경계 2 개(감시 블록이 후보 밖이거나 문서가 서로 다름" in note
    assert "SW 변수의 HSIS 행 없음 3(이름 확인)" in note
    note = _disclosure({**base, "hw_tolerance_undecided_row_silent": 4, "hw_hsis": {"given": True, "rows": 11}})["note"]
    assert "HSIS 행이 후보 하나만 가진 시스템 ID·네트를 적지 않음 4" in note


def test_the_gate_board_keeps_the_guidance():
    """(review I6) the board keeps the first 230 and the last 120 characters: '주면 …' is the tail, not the fixed text."""
    from workflow.quality.issues import _MESSAGE_CAP  # noqa: F401 — the clip the order is for
    base = {"tcs": 1, "steps": 3, "facts": 1, "facts_used": 1, "hw_tolerance_groups": 10, "hw_tolerance_inside_step": 9,
            "hw_document": {"file": "hrs.docx", "blocks": 47, "blocks_with_tolerance": 4},
            "hw_design_document": {"given": False, "ratios": 0}, "hw_hsis": {"given": False}}
    note = _disclosure(base)["note"]
    assert "HSIS 를 주면" in note[-120:] and "점은 옮기지 않음" not in note[-120:]


def test_the_input_is_wired_like_the_hw_requirements(monkeypatch):
    import inspect

    from backend.main import app
    from backend.middleware import _CLOUDIUM_PATH_KEYS
    from backend.routers.docgen_preflight import _DOC_KEY_TO_INPUT
    from backend.schemas import ScmLinkedDocs
    from backend.services import resolver_helpers
    from backend.services.docgen_requirements import IN_HWDS, INPUT_LABELS, requirements_for
    assert ScmLinkedDocs().hwds == "" and "hwds_path" in _CLOUDIUM_PATH_KEYS and _DOC_KEY_TO_INPUT["hwds"] == IN_HWDS
    assert INPUT_LABELS[IN_HWDS].startswith("HwDS") and "분압식" in requirements_for("sts")["optional"][IN_HWDS]
    for path in ("/api/jenkins/sts/generate-async", "/api/local/sts/generate", "/api/local/sts/generate-stream",
                 "/api/local/sts/generate-async"):
        route = next(r for r in app.routes if getattr(r, "path", "") == path and "POST" in getattr(r, "methods", set()))
        params = inspect.signature(route.endpoint).parameters
        # (review W1) the web STS path (Jenkins) dropped the HSIS the screen sends
        assert "hwds_path" in params and "hsis_path" in params, path
    monkeypatch.setattr(resolver_helpers, "resolve_builder_input", lambda p, label, reasons: p or None)
    assert resolver_helpers.resolve_system_requirement_docs("", "", "", "hds.docx")["hwds_path"] == "hds.docx"


def test_the_jenkins_sts_handler_passes_the_hsis_to_the_generator(monkeypatch, tmp_path):
    """(review W1) not only declared: resolved and handed to `generate_sts` (the screen sends it on every STS)."""
    import asyncio

    from backend.routers import jenkins
    from backend.services import resolver_helpers
    seen = {}
    monkeypatch.setattr(resolver_helpers, "resolve_builder_input", lambda p, label="", reasons=None: p or None)
    monkeypatch.setattr(jenkins, "_build_sts_function_details", lambda *a, **k: {})

    def fake_generate_sts(**kw):
        seen.update(kw)
        return {"output_path": kw["output_path"]}
    import sts_generator
    monkeypatch.setattr(sts_generator, "generate_sts", fake_generate_sts)

    class _Now:
        def __init__(self, target, daemon=True):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(jenkins.threading, "Thread", _Now)
    srs = tmp_path / "SRS.txt"
    srs.write_text("SwTSR_0101: x", encoding="utf-8")
    asyncio.run(jenkins.jenkins_sts_generate_async(
        job_url="http://j/job/x/", cache_root=str(tmp_path), build_selector="lastSuccessfulBuild", source_root=str(tmp_path),
        srs_path="", sds_path="", uds_path="", stp_path="", req_paths=str(srs), req_files=[], template_path="",
        reference_doc_path="", template_source="", project_id="T", version="v1.00", asil_level="", max_tc_per_req=5,
        max_steps_per_tc=None, tc_profile="", syrs_path="", syds_path="", hwrs_path="", hwds_path="",
        hsis_path=str(tmp_path / "hsis.xlsx")))
    assert seen.get("hsis_path") == str(tmp_path / "hsis.xlsx")


@pytest.mark.parametrize("real", ["hd", "pv"])
def test_real_design_documents_give_the_hall_monitor_its_ratio(real):
    """HDPDM01 HDS / KJPDS02 HwDS copies (Cloudium scan 2026-09-30): ``HwC_07`` writes the Hall supply monitor's 0.5;
    of the HW requirement blocks only the Hall supply monitor (a node) takes a ratio — the power switch, the V→A motor
    current formula and the block with no tolerance do not (review W3)."""
    from pathlib import Path
    folder = Path(__file__).resolve().parents[2] / ".codex_tmp" / "hw_docs" / real
    found = [p for p in folder.glob("*.docx") if "_HDS)" in p.name or "_HwDS)" in p.name] if folder.exists() else []
    hrs = [p for p in folder.glob("*.docx") if "_HRS)" in p.name or "_HwRS)" in p.name] if folder.exists() else []
    if not found or not hrs:
        pytest.skip("HW document copies not present (.codex_tmp/hw_docs)")
    design = parse_hw_design_docx(str(found[0]))
    assert Counter(s["to_source"] for d in design.values() if "HwTSR_0203" in d["related"] for s in d["scales"]) == {"2": 1}
    hw = parse_hw_requirement_docx(str(hrs[0]))
    apply_hw_design(hw, design)
    assert sorted(h for h, b in hw.items() if b.get("scale")) == ["HwTSR_0203"]


# ── R50 review round 2 ─────────────────────────────────────────────────────────────────────────────────────────────


def test_an_id_shared_with_a_block_outside_the_candidates_decides_nothing():
    """(r2 W2) HD ``SyTSR_0114``: HwTSR_0203 and HwTSR_0202 'Position Sensor 전원 Monitor' (no tolerance — no candidate)
    both cite it. Unique among the candidates is not unique: the monitor block may be outside them — said, not decided
    (a 'Position Sensor Power' row would otherwise have 'confirmed' the Hall block through the word 'sensor')."""
    position = {**NODE, "name": "Position Sensor 전원 Monitor", "tolerances": [], "monitor_node": False}
    hw = _hw(HwTSR_0203=NODE, HwTSR_0204=BATTERY, HwTSR_0202=position)
    row = {"id": "HSI_99", "vars": ["u16g_ApiIn_PosSnsrPwr"], "ids": ["SyTSR_0114"], "nets": [],
           "name": "Position Sensor Power"}
    pick, refused = _hsis_pick(_row("u16g_ApiIn_PosSnsrPwr", [row]), [{"hw_id": "HwTSR_0203"}, {"hw_id": "HwTSR_0204"}],
                               hw)
    assert pick is None and (refused["kind"], refused["anchor"], refused["outside"]) == \
        ("outside", "SyTSR_0114", ["HwTSR_0202 Position Sensor 전원 Monitor"])
    tcs = []

    def build(**kw):
        return _build_tc_dict(test_env="HILS", derive_inputs=False, is_safety=False, **kw)
    stats = append_requirement_boundary_tcs(
        tcs, [_req("- u16g_ApiIn_PosSnsrPwr 가 4.85V 미만 시 고장", "SySM_04", "SwTSR_0101")], build, _make_tc_id,
        _classify_steps, hw={**hw, "HwTSR_0203": {**NODE, "nominals": [{"value": "5", "unit": "V"}]}}, hsis_rows=[row])
    assert "HSIS HSI_99 의 시스템 ID SyTSR_0114 를 허용오차 없는 HW 블록 HwTSR_0202 Position Sensor 전원 Monitor 도 인용 — " \
        "감시 블록이 후보 밖일 수 있어 경로 미정(확인)" in tcs[0]["precondition"]
    assert (stats["hw_tolerance_path_outside"], stats["hw_tolerance_path_refused"]) == (1, 0)


def test_the_row_words_are_its_name_nets_and_matched_variable():
    """(r2 I1) HD's LIN row lists 32 variables — all of them made its words agree with any block name; Korean against
    Latin names cannot be compared (not 'different')."""
    from generators.sts_requirement_tc import _name_words, _names_agree, _row_words
    lin = {"id": "HSI_13", "vars": ["u8g_ApiOut_DoorAngle", "u8g_ApiOut_MotorCurrent", "u8g_ApiIn_LinRx_IgnSwSta"],
           "ids": [], "nets": ["LIN_BUS"], "name": "LIN_BUS", "matched": "u8g_ApiOut_DoorAngle"}
    assert _names_agree(_name_words("Motor Current Monitor"), _row_words(lin)) is False
    assert _names_agree(_name_words("배터리 전압 모니터"), _name_words("Battery Power")) is None


def test_a_fraction_or_an_exponent_after_the_factor_is_no_ratio():
    """(r2 I2) ``* 10/43`` and ``* 2e3`` were read as 10 and 2."""
    assert _formula_scales("Monitor Voltage = Input * 10/43") == []
    assert _formula_scales("Monitor Voltage = Input * 10 / (10+33)") == []
    assert _formula_scales("Monitor Voltage = Input * 2e3") == []


def test_hsis_picks_nothing_where_the_fact_cites_its_block():
    """(r2 I3) direct candidates decide first: no HSIS mark on a candidate the summary does not use."""
    hw = _hw(HwTSR_0203=NODE, HwTSR_0204=BATTERY)
    e = _evidence("- u16g_ApiIn_Vsup 가 8.50V 미만 시 저전압")
    e["source"] = {"doc": "SyRS", "id": "SySM_04", "field": "Description"}      # both cite SySM_04: two direct
    cands = hw_tolerances_for(_req("", "SySM_04"), e, hw, ROWS)
    assert all(t["direct"] for t in cands) and not any(t["hsis"] for t in cands)


def test_an_ambiguous_row_is_not_no_row():
    """(r2 I7) two rows match the variable: counted and said as such."""
    twice = ROWS + [{"id": "HSI_31", "vars": ["u16g_SrvIn_Vsup"], "ids": [], "nets": [], "name": "x"}]
    hw = _hw(HwTSR_0203={**NODE, "scale": HALL_SCALE})
    (t,) = hw_tolerances_for(_req("", "SySM_04"), _evidence("- u16g_ApiIn_Vsup 이 4.85V 이하 시 고장"), hw, twice)
    assert t["scale"]["check"] == "row_ambiguous"
    tcs = []

    def build(**kw):
        return _build_tc_dict(test_env="HILS", derive_inputs=False, is_safety=False, **kw)
    stats = append_requirement_boundary_tcs(
        tcs, [_req("- u16g_ApiIn_Vsup 가 4.85V 미만 시 고장", "SySM_04")], build, _make_tc_id, _classify_steps,
        hw=_hw(HwTSR_0203={**NODE, "nominals": [{"value": "5", "unit": "V"}]}, HwTSR_0204=BATTERY), hsis_rows=twice)
    assert (stats["hw_tolerance_undecided_row_ambiguous"], stats["hw_tolerance_undecided_no_row"]) == (1, 0)


def test_a_hsis_given_but_unread_is_never_not_given(tmp_path, monkeypatch):
    """(r2 W1) the handler's localisation reason reaches the disclosure — the output never says '미입력 — 주면 …' to a
    user who gave it; read but with no signal is the file's layout, never 'fix the variable names'."""
    from backend.services import resolver_helpers
    from generators.sts import generate_sts
    docs = {"syrs_path": None, "system_input_skips": []}

    def unresolved(p, label="", reasons=None):
        reasons.append(f"{label}: 파일 없음 (h.xlsx)")
    monkeypatch.setattr(resolver_helpers, "resolve_builder_input", unresolved)
    logged = []
    assert resolver_helpers.attach_sts_hsis(docs, "U:/h.xlsx", logged) is None
    assert docs["system_input_skips"] == ["HSIS: 파일 없음 (h.xlsx)"] and logged == docs["system_input_skips"]
    text = ["SwTSR_0101: u16g_ApiIn_HallSnsrLevel 이 4.85V 이하 시 고장을 검출한다. Related ID: SySM_04"]
    hrs = _docx(tmp_path / "hrs.docx", [[("ID", "HwTSR_0203"), ("Name", "Hall Sensor Block 전원 Monitor"),
                                         ("Description", "Monitor전압: 2.5V(±0.3V) / 허용 오차: ±0.3V"),
                                         ("Related ID", "SySM_04")]])
    out = generate_sts(text, {}, str(tmp_path / "a.xlsm"), project_config={"project_id": "T"}, hwrs_path=hrs,
                       system_input_skips=["HSIS: 파일 없음 (h.xlsx)"])
    rb = out["quality_report"]["generation_stats"]["requirement_boundary"]
    assert rb["hw_hsis"] == {"given": True, "error": "HSIS: 파일 없음 (h.xlsx)"} and not rb.get("system_input_skips")
    note = _disclosure(rb)["note"]
    assert "HSIS 를 읽지 못해" in note and "HSIS 를 주면" not in note
    base = {"tcs": 1, "steps": 3, "facts": 1, "facts_used": 1, "hw_tolerance_groups": 10, "hw_tolerance_inside_step": 9,
            "hw_tolerance_undecided_no_row": 3, "hw_document": {"file": "hrs.docx", "blocks": 47, "blocks_with_tolerance": 4},
            "hw_hsis": {"given": True, "rows": 0, "signals": 0}}
    note = _disclosure(base)["note"]
    assert "HSIS 에서 SW 신호를 하나도 읽지 못해" in note and "이름 확인" not in note


def test_the_value_counts_what_to_settle_and_a_design_not_given_is_not_zero():
    """(r2 I4) the board keeps the value whole — the document checks are counted there; (r2 I5) no 'HW 설계서 0'."""
    base = {"tcs": 1, "steps": 3, "facts": 1, "facts_used": 1, "hw_tolerance_groups": 10, "hw_tolerance_inside_step": 9,
            "hw_document": {"file": "hrs.docx", "blocks": 47, "blocks_with_tolerance": 4}, "hw_hsis": {"given": False}}
    item = _disclosure({**base, "hw_tolerance_path_refused": 1, "hw_tolerance_scale_net_mismatch": 2,
                        "hw_tolerance_to_settle": 2,
                        "hw_design_document": {"given": False, "ratios": 0, "ratios_by_source": {"design": 0, "own": 0}}})
    assert item["value"].endswith(" · 문서 확인 2") and "HW 설계서 0" not in item["note"]
    item = _disclosure({**base, "hw_tolerance_scaled": 2, "hw_design_document": {
        "file": "", "error": "HwDS: 파일 없음", "ratios": 1, "ratios_by_source": {"design": 0, "own": 1}}})
    assert "분압식이 있는 감시 노드 블록 HW 요구 자체 식 1 개, 척도를 환산한 경계 2 개" in item["note"]


def test_the_sts_gate_lists_the_hsis():
    """(r2 W3) the four STS handlers take it and the disclosure guides to it: the readiness gate shows it too."""
    from backend.services.docgen_requirements import IN_HSIS, requirements_for
    assert "HSIS 행" in requirements_for("sts")["optional"][IN_HSIS]


# ── R50 review round 3 ─────────────────────────────────────────────────────────────────────────────────────────────


def test_any_unshared_anchor_decides_and_the_wording_follows_the_outside_blocks():
    """(r3 Info 1) the row names two IDs only the Hall block cites among the candidates: one is shared with a block
    outside, the other is not — the clean one decides (it was the sorted first, and the answer turned on the order);
    (r3 W4) an outside block that writes a tolerance (in another unit) is 'not a candidate', not 'without tolerance'."""
    node = {**NODE, "related": ["SySM_04", "SyX_1", "SyX_2"]}
    current = {**BATTERY, "name": "Motor Current Monitor", "related": ["SyX_1"],
               "tolerances": [{"text": "허용 오차: ±3%", "value": "3", "unit": "%", "measured_units": ["A"]}]}
    row = {"id": "HSI_77", "vars": ["u16g_ApiIn_HallSnsrLevel"], "ids": ["SyX_1", "SyX_2"], "nets": [],
           "name": "VCC_HALL_MON"}
    cands = [{"hw_id": "HwTSR_0203"}, {"hw_id": "HwTSR_0204"}]
    hw = _hw(HwTSR_0203=node, HwTSR_0204=BATTERY, HwTSR_0301=current)
    pick, refused = _hsis_pick(_row("u16g_ApiIn_HallSnsrLevel", [row]), cands, hw)
    assert (pick["hw_id"], pick["anchor"], refused) == ("HwTSR_0203", "SyX_2", None)
    one = dict(row, ids=["SyX_1"])
    pick, refused = _hsis_pick(_row("u16g_ApiIn_HallSnsrLevel", [one]), cands, hw)
    assert pick is None and refused["outside_without_tolerance"] is False
    from generators.sts_requirement_tc import _refusal_text
    assert "후보가 아닌 HW 블록 HwTSR_0301 Motor Current Monitor 도 인용" in _refusal_text(refused)


def test_a_boundary_to_settle_is_counted_once_and_the_hub_is_a_reason():
    """(r3 W1) HD MagnetLevel is refused (outside) and not scaled (another node) — one boundary to settle, not two;
    (r3 W3) a group whose own system block several HW blocks cite says so (HSIS is not applied there)."""
    position = {**NODE, "name": "Position Sensor 전원 Monitor", "tolerances": [], "monitor_node": False}
    hw = _hw(HwTSR_0203={**NODE, "scale": HALL_SCALE}, HwTSR_0204=BATTERY, HwTSR_0202=position)
    tcs = []

    def build(**kw):
        return _build_tc_dict(test_env="HILS", derive_inputs=False, is_safety=False, **kw)
    stats = append_requirement_boundary_tcs(
        tcs, [_req("- u16g_ApiIn_MagnetLevel 가 4.85V 미만 시 고장", "SySM_04, SyTSR_0114", "SwTSR_0101")], build,
        _make_tc_id, _classify_steps, hw=hw, hsis_rows=ROWS)
    assert (stats["hw_tolerance_path_outside"], stats["hw_tolerance_scale_net_mismatch"],
            stats["hw_tolerance_to_settle"]) == (1, 1, 1)
    base = {"tcs": 1, "steps": 3, "facts": 1, "facts_used": 1, "hw_tolerance_groups": 10, "hw_tolerance_inside_step": 9,
            "hw_document": {"file": "hrs.docx", "blocks": 47, "blocks_with_tolerance": 4},
            "hw_hsis": {"given": True, "rows": 11, "signals": 21}}
    item = _disclosure({**base, **{k: v for k, v in stats.items() if k.startswith("hw_tolerance_path_outside")
                                   or k in ("hw_tolerance_scale_net_mismatch", "hw_tolerance_to_settle")}})
    assert item["value"].endswith(" · 문서 확인 1")
    assert "HW 블록 여럿이 인용(허브 — HSIS 를 쓰지 않음) 35" in _disclosure(
        {**base, "hw_tolerance_undecided_direct_hub": 35})["note"]


def test_signals_without_a_sw_variable_column_is_the_layout_and_an_empty_design_is_said():
    """(r3 Info 7) signals read but no SW-variable row: the layout — never 'fix the names'; (r3 Info 5) a HW design read
    with no design table is said, not silent."""
    base = {"tcs": 1, "steps": 3, "facts": 1, "facts_used": 1, "hw_tolerance_groups": 10, "hw_tolerance_inside_step": 9,
            "hw_tolerance_undecided_no_row": 3, "hw_document": {"file": "hrs.docx", "blocks": 47, "blocks_with_tolerance": 4}}
    note = _disclosure({**base, "hw_hsis": {"given": True, "rows": 0, "signals": 21}})["note"]
    assert "HSIS 신호 21 개를 읽었지만 SW 변수 이름을 적은 행이 없어" in note and "이름 확인" not in note
    note = _disclosure({**base, "hw_design_document": {"file": "x.docx", "blocks": 0, "blocks_with_formula": 0,
                                                        "ratios": 0, "ratios_by_source": {"design": 0, "own": 0}}})["note"]
    assert "HW 설계서에서 설계 표(ID `Hw…`)를 하나도 찾지 못했다" in note


def test_a_hub_is_counted_by_the_generator():
    """(r3 W3) a traced fact's own system block (SySM_04) cited by two HW blocks: undecided, HSIS not applied — counted."""
    system = {"SySM_04": {"doc": "SyDS", "fields": {"Description": "- u16g_ApiIn_Vsup 가 8.50V 미만 시 저전압"}}}
    tcs = []

    def build(**kw):
        return _build_tc_dict(test_env="HILS", derive_inputs=False, is_safety=False, **kw)
    stats = append_requirement_boundary_tcs(
        tcs, [{"id": "SwTSR_0104", "name": "n", "description": "저전압 판정", "verification": "", "asil": "B",
               "related_id": "SySM_04"}], build, _make_tc_id, _classify_steps, system=system,
        hw=_hw(HwTSR_0203=NODE, HwTSR_0204=BATTERY), hsis_rows=ROWS)
    assert stats["hw_tolerance_undecided_direct_hub"] == 1 and stats["hw_tolerance_path_by_hsis"] == 0


def test_an_unused_or_unread_design_is_said_and_the_reasons_add_up():
    """(r4 I-B) a HW design with the HW requirements unread is said unused; its own read failure is not hidden behind
    'not used'; (r4 I-C) the refusals told above are in the reasons too, so they add up to the undecided."""
    base = {"tcs": 1, "steps": 3, "facts": 1, "facts_used": 1}
    unread = _disclosure({**base, "hw_document": {"file": "hrs.docx", "error": "BadZipFile: x"},
                          "hw_design_document": {"file": "hds.docx", "blocks": 2, "unused": "no_hwrs"}})["note"]
    assert "HW 설계서는 줬지만 그것이 환산할 HW 요구사항서가 읽지 못해 쓰지 않았다" in unread
    both = _disclosure({**base, "hw_document": {"given": False},
                        "hw_design_document": {"file": "", "error": "HwDS: 파일 없음", "unused": "no_hwrs"}})["note"]
    assert "HW 설계서도 읽지 못했다(HwDS: 파일 없음)" in both and "쓰지 않았다" not in both
    note = _disclosure({**base, "hw_tolerance_groups": 10, "hw_tolerance_inside_step": 9,
                        "hw_document": {"file": "hrs.docx", "blocks": 47, "blocks_with_tolerance": 4},
                        "hw_hsis": {"given": True, "rows": 11, "signals": 21}, "hw_tolerance_undecided_direct_hub": 35,
                        "hw_tolerance_path_outside": 2})["note"]
    assert "허브 — HSIS 를 쓰지 않음) 35 · 후보 밖 블록도 같은 ID 인용 2(위)" in note
