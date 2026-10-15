"""R86 — the reference-scale SUTS on the extension's columns (`suts.reference_unit_sequences`).

Measured (R85 code, three suites on one denominator): of the mutants only the reference killed, KJPDS02_PV 246 ·
HDPDM01 158, most were a column the reference-scale document lacked — an input the function reads that the design table
does not list, so the output values stayed unknown (`s_MotorSpeedModeSelection_RearSet`: 2 design inputs, the extension
adds 12 and states 4 outputs), or an input the reference sets that the generated columns did not have (the response
buffer elements of `sf_LinUdsSecurityAccess`). R19 · R80 found those columns but only the extended profile used them.
The extended document begins with the reference-scale block (R85: names, order and values the same in every function of
both projects); judging that block on the extension's columns killed PV 2,559 → 3,225 · HD 2,062 → 2,621 and lost
nothing. The reference-scale document is now that block — the rows of the reference-scale profile, the columns the
extended generation decides. No mutant is made or consulted here."""
from __future__ import annotations

import pytest

from generators import suts
from generators.suts import (
    _WRITTEN_RECOUNT_KEYS,
    generate_sequences,
    is_extended_strategy,
    reference_unit_sequences,
    summarize_reference_columns,
)
from report_gen.generation_disclosures import build_disclosures
from tests.unit.test_reference_code_rows_r85 import TYPES, _unit


def _design_unit():
    # the design lists g_mode in · g_res out; the body also reads g_tmr (and g_cnt) and writes g_cnt
    return _unit(input_vars=["g_mode"], output_vars=["g_res"])


def _rows(seqs):
    return [(s["strategy"], s["inputs"], s["expected"]) for s in seqs]


@pytest.fixture(autouse=True)
def _types(monkeypatch):
    monkeypatch.setattr(suts, "_globals_type_cache", dict(TYPES))


def test_the_reference_scale_document_is_the_extended_documents_block_with_its_columns():
    ref_unit, ext_unit = _design_unit(), _design_unit()
    ref = reference_unit_sequences(ref_unit, 24)
    ext = suts.extended_unit_sequences(ext_unit, 24)
    block = [s for s in ext if not is_extended_strategy(s["strategy"])]
    assert len(block) < len(ext), "the fixture must have extended rows to leave out"
    assert _rows(ref) == _rows(block)
    assert not any(is_extended_strategy(s["strategy"]) for s in ref)
    assert ref_unit["input_vars"] == ext_unit["input_vars"] and ref_unit["output_vars"] == ext_unit["output_vars"]


def test_the_columns_the_design_lacks_are_now_in_the_reference_scale_document():
    old_unit, unit = _design_unit(), _design_unit()
    old = generate_sequences(old_unit, 24)
    ref = reference_unit_sequences(unit, 24)
    assert old_unit["input_vars"] == ["g_mode"]
    assert {"g_tmr", "g_cnt"} <= set(unit["input_vars"]) and "g_cnt" in unit["output_vars"]
    rec = unit["reference_columns"]
    assert rec["error"] is None and rec["inputs_added"] >= 2 and rec["outputs_added"] == 1
    # the catalogue rows hold the added inputs at one fixed value — the design columns are the old document's
    bv = next(s for s in ref if s["strategy"] == "BV_MID")
    old_bv = next(s for s in old if s["strategy"] == "BV_MID")
    assert bv["inputs"]["g_mode"] == old_bv["inputs"]["g_mode"] and "g_tmr" in bv["inputs"]
    assert len({s["inputs"]["g_tmr"] for s in ref if "g_tmr" in s["inputs"] and not s["strategy"].startswith("MCDC_")}) == 1
    # a value the function writes is stated where the old document had no column for it
    assert any(isinstance(s["expected"].get("g_cnt"), int) for s in ref)
    assert not any("g_cnt" in s["expected"] for s in old)
    assert [s["strategy"] for s in ref] == [s["strategy"] for s in old], "the same rows (R85 block) — only the columns"


def test_the_extended_generations_other_records_are_not_left_on_the_unit():
    unit = _design_unit()
    ref = reference_unit_sequences(unit, 24)
    for key in ("boundary_search", "scenario_rows", "mcdc_fill", "stub_apart", "propagation_rows", "robustness_rows",
                "observable_mcdc", "_boundary_ctx", "_code_rows_cache"):
        assert key not in unit, key
    n = len(ref)
    for d in (unit.get("mcdc_design") or {}).get("decisions") or []:
        for p in d.get("pairs") or []:
            for k in ("seq_a", "seq_b"):
                assert p.get(k) is None or 1 <= p[k] <= n, (k, p.get(k), n)
    dup = unit["duplicate_rows"]
    assert dup["extended_rows_dropped"] == 0 and dup["extended_rows_duplicated_kept"] == 0
    assert [s["seq_num"] for s in ref] == list(range(1, n + 1))


def test_a_failed_extended_generation_keeps_the_design_columns(monkeypatch):
    old_unit, unit = _design_unit(), _design_unit()
    old = generate_sequences(old_unit, 24)

    def boom(u, cap=None, **_kw):
        u["input_vars"] = list(u["input_vars"]) + ["g_tmr"]   # a half-done generation must not leak its columns
        u["scenario_rows"] = {"rows": 3}
        raise RuntimeError("boom")
    monkeypatch.setattr(suts, "extended_unit_sequences", boom)
    ref = reference_unit_sequences(unit, 24)
    assert _rows(ref) == _rows(old)
    assert unit["input_vars"] == ["g_mode"] and unit["output_vars"] == ["g_res"]
    assert "scenario_rows" not in unit and "source_read_inputs" not in unit
    assert unit["reference_columns"] == {"error": "RuntimeError", "extension_errors": {}, "block_mismatch": None,
                                         "inputs_added": 0, "outputs_added": 0}


def test_an_added_output_no_reference_scale_row_states_is_dropped(monkeypatch):
    # the extension keeps a written output when ANY of its rows derives it; the reference-scale rows must derive it too
    real = suts.extended_unit_sequences

    def with_phantom(u, cap=None, **kw):
        seqs = real(u, cap, **kw)
        u["output_vars"] = list(u["output_vars"]) + ["g_phantom"]
        (u["source_written_outputs"].setdefault("added", {}))["g_phantom"] = {"round": "final", "sequences": [99]}
        return seqs
    monkeypatch.setattr(suts, "extended_unit_sequences", with_phantom)
    unit = _design_unit()
    ref = reference_unit_sequences(unit, 24)
    assert "g_phantom" not in unit["output_vars"] and not any("g_phantom" in s["expected"] for s in ref)
    assert "g_phantom" in unit["source_written_outputs"]["dropped"]
    assert unit["reference_columns"]["outputs_added"] == 1


def test_the_code_rows_hold_the_added_inputs_at_the_extended_blocks_value():
    # two design inputs (R85's code rows search them); g_cnt is read and written but not in the design table
    ref_unit, ext_unit = (_unit(input_vars=["g_mode", "g_tmr"], output_vars=["g_res"]) for _ in range(2))
    ref = reference_unit_sequences(ref_unit, 24)
    block = [s for s in suts.extended_unit_sequences(ext_unit, 24) if not is_extended_strategy(s["strategy"])]
    code = [s for s in ref if s["strategy"].startswith(suts.CODE_PREFIX)]
    assert code, "the fixture must have code rows"
    assert [s["inputs"] for s in code] == [s["inputs"] for s in block if s["strategy"].startswith(suts.CODE_PREFIX)]
    assert "g_cnt" in ref_unit["input_vars"] and all("g_cnt" in s["inputs"] for s in code)


def test_summary_and_disclosure():
    units = [_design_unit(), _design_unit()]
    reference_unit_sequences(units[0], 24)
    units[1]["reference_columns"] = {"error": "RuntimeError", "inputs_added": 0, "outputs_added": 0}
    s = summarize_reference_columns(units)
    assert s["units"] == 2 and s["units_with_added_inputs"] == 1 and s["units_with_added_outputs"] == 1
    assert s["errors"] == {"RuntimeError": 1} and s["outputs_added"] == 1
    items = {i["key"]: i for i in build_disclosures("suts", {"reference_columns": s})}
    item = items["suts_reference_columns"]
    assert "RuntimeError 1" in item["note"] and item["tone"] == "warning"
    assert "suts_reference_columns" not in {i["key"] for i in build_disclosures("suts", {})}


def test_generate_suts_reports_the_reference_columns(tmp_path):
    (tmp_path / "m.c").write_text("typedef unsigned char U8;\nU8 g_cnt;\nU8 g_lim;\nU8 Fn(U8 a)\n{\n"
                                  "    if (a > g_lim) { g_cnt = 5U; }\n    return a;\n}\n", encoding="utf-8")
    ref = suts.generate_suts(source_root=str(tmp_path), output_path=str(tmp_path / "r.xlsm"), scope="source")[
        "quality_report"]
    ext = suts.generate_suts(source_root=str(tmp_path), output_path=str(tmp_path / "e.xlsm"), scope="source",
                             tc_profile="extended")["quality_report"]
    assert ref["reference_columns"]["units"] >= 1 and "reference_columns" not in ext
    assert "source_read_inputs" in ref and "source_written_outputs" in ref
    assert ref["extended_sequences"] == 0


def test_the_block_is_compared_with_the_extended_documents_block():
    # (review R86 W2) the reference-scale rows are checked against the extended document's block on every unit
    unit = _design_unit()
    reference_unit_sequences(unit, 24)
    assert unit["reference_columns"]["block_mismatch"] is None
    assert "_code_rows_kept" not in unit and "_code_rows_cache" not in unit


def test_a_block_that_differs_is_recorded(monkeypatch):
    real = suts.extended_unit_sequences

    def shifted(u, cap=None, **kw):
        seqs = real(u, cap, **kw)
        for s in seqs:
            if s["strategy"] == "BV_MID":
                s["inputs"] = dict(s["inputs"], g_mode=7)   # the extended block no longer matches the reference rows
        return seqs
    monkeypatch.setattr(suts, "extended_unit_sequences", shifted)
    unit = _design_unit()
    reference_unit_sequences(unit, 24)
    assert unit["reference_columns"]["block_mismatch"] == "inputs"
    s = summarize_reference_columns([unit])
    assert s["units_block_mismatch"] == 1
    item = {i["key"]: i for i in build_disclosures("suts", {"reference_columns": s})}["suts_reference_columns"]
    assert "확장 문서의 앞 블록과 다른 unit 1" in item["note"] and item["tone"] == "warning"


def test_a_failure_on_the_extended_columns_falls_back_to_the_design_columns(monkeypatch):
    # (review R86 I1) the second pass never costs the document
    old_unit, unit = _design_unit(), _design_unit()
    old = generate_sequences(old_unit, 24)
    real = suts.generate_sequences

    def fail_on_added(u, max_seq=None, **kw):
        if "g_tmr" in (u.get("input_vars") or []) and not kw.get("extended"):
            raise ValueError("pass 2")
        return real(u, max_seq, **kw)
    monkeypatch.setattr(suts, "generate_sequences", fail_on_added)
    ref = reference_unit_sequences(unit, 24)
    assert _rows(ref) == _rows(old) and unit["input_vars"] == ["g_mode"]
    assert unit["reference_columns"]["error"] == "reference_pass:ValueError"
    assert "source_read_inputs" not in unit and "source_written_outputs" not in unit


def test_an_error_inside_the_extended_generation_is_said(monkeypatch):
    # (review R86 I2) the completion's own fallback keeps the design columns — the record says so
    def fail(*a, **k):
        raise KeyError("x")
    monkeypatch.setattr(suts, "complete_source_read_inputs", fail)
    unit = _design_unit()
    reference_unit_sequences(unit, 24)
    rc = unit["reference_columns"]
    assert rc["error"] is None and rc["extension_errors"].get("source_read_inputs") == "KeyError"
    assert rc["inputs_added"] == 0
    assert summarize_reference_columns([unit])["units_extension_errors"] == 1


def test_the_written_output_counts_are_the_reference_rows(monkeypatch):
    # (review R86 W1) what pass 1 counted on extended rows does not survive into the reference-scale record
    real = suts.extended_unit_sequences

    def stale(u, cap=None, **kw):
        seqs = real(u, cap, **kw)
        rec = u["source_written_outputs"]
        rec.update(written_past_allocation=["pData[9]"], final_initial_not_in_inputs=["g_gone"],
                   pointee_rerun_cap_reached=True)
        return seqs
    monkeypatch.setattr(suts, "extended_unit_sequences", stale)
    unit = _design_unit()
    reference_unit_sequences(unit, 24)
    rec = unit["source_written_outputs"]
    assert not any(rec.get(k) for k in _WRITTEN_RECOUNT_KEYS), {k: rec.get(k) for k in _WRITTEN_RECOUNT_KEYS}


def test_the_disclosures_speak_of_the_rows_this_document_has():
    # (review R86 C1) the reference-scale document has no OAT · boundary rows, no second MC/DC design, no post-round rows
    sr = {"units": 1, "units_with_added": 1, "names_added": 2, "max_rounds": 2}
    sw = {"units": 1, "units_with_added": 1, "names_added": 1, "max_rounds": 2}
    ref = {i["key"]: i["note"] for i in build_disclosures(
        "suts", {"tc_profile": "reference", "source_read_inputs": sr, "source_written_outputs": sw})}
    ext = {i["key"]: i["note"] for i in build_disclosures(
        "suts", {"tc_profile": "extended", "source_read_inputs": sr, "source_written_outputs": sw})}
    assert "단독 경계(OAT)·행동 경계 행은 확장 문서에만 있다" in ref["suts_source_read_inputs"]
    assert "'Input Scope'" not in ref["suts_source_read_inputs"] and "'Input Scope'" in ext["suts_source_read_inputs"]
    assert "확장 생성의 행으로" in ref["suts_source_written_outputs"]
    assert "확장 문서에서 회차 뒤에 붙는 행" in ref["suts_source_written_outputs"]
    assert "이 문서의 행으로" in ext["suts_source_written_outputs"]
    assert "행동 경계 행이 움직인다" in ext["suts_source_read_inputs"]


def test_the_second_pass_reuses_the_code_rows_the_extended_rounds_found(monkeypatch):
    # (review R86 W-R2-3 · W2) a fresh search in pass 2 may see other outputs / buffers and find other rows; the block
    #   must be the extended document's — the second pass runs no code-row search of its own
    real_fs, real_ext = suts.find_scenarios, suts.extended_unit_sequences
    phase, searches = {"p": 1}, {1: 0, 2: 0}

    def fs(*a, **k):
        if k.get("covered") is not None:
            searches[phase["p"]] += 1
        return real_fs(*a, **k)

    def ext(*a, **k):
        try:
            return real_ext(*a, **k)
        finally:
            phase["p"] = 2
    monkeypatch.setattr(suts, "find_scenarios", fs)
    monkeypatch.setattr(suts, "extended_unit_sequences", ext)
    unit = _unit(input_vars=["g_mode", "g_tmr"], output_vars=["g_res"])
    reference_unit_sequences(unit, 24)
    assert searches[1] >= 1 and searches[2] == 0, searches
    assert unit["reference_columns"]["block_mismatch"] is None


def test_the_type_cache_reaches_every_generation(monkeypatch):
    # (review R86 W-R2-3 · W3) the impact draft passes its own type map and never seeds the process-global one —
    #   a wrong global must not change the draft
    clean_unit, unit = _design_unit(), _design_unit()
    clean = reference_unit_sequences(clean_unit, 24)
    monkeypatch.setattr(suts, "_globals_type_cache", {k: "U16" if v == "U8" else "U8" for k, v in TYPES.items()})
    drafted = reference_unit_sequences(unit, 24, type_cache=dict(TYPES))
    assert _rows(drafted) == _rows(clean)
    assert unit["input_vars"] == clean_unit["input_vars"] and unit["output_vars"] == clean_unit["output_vars"]
    assert unit["reference_columns"]["block_mismatch"] is None   # pass 1 (the columns, the code rows) typed alike too


def test_a_block_whose_expected_values_differ_is_recorded(monkeypatch):
    real = suts.extended_unit_sequences

    def restated(u, cap=None, **kw):
        seqs = real(u, cap, **kw)
        for s in seqs:
            if s["strategy"] == "BV_MID" and isinstance(s["expected"].get("g_res"), int):
                s["expected"] = dict(s["expected"], g_res=s["expected"]["g_res"] + 1)
        return seqs
    monkeypatch.setattr(suts, "extended_unit_sequences", restated)
    unit = _design_unit()
    reference_unit_sequences(unit, 24)
    assert unit["reference_columns"]["block_mismatch"] == "expected"


def test_the_mcdc_rows_say_an_added_input_is_blank_by_design():
    # (review R86 I-R2-7) a source-read input has a declared domain — its blank in an MC/DC vector row is the vector's
    unit = _design_unit()
    ref = reference_unit_sequences(unit, 24)
    mcdc = [s for s in ref if s["strategy"].startswith("MCDC_")]
    assert mcdc
    blank = [s for s in mcdc if "g_tmr" not in s["inputs"]]
    assert blank and all("소스가 읽어 더한 입력(공란" in s["description"] for s in blank)
    assert not any("도메인 미상): g_tmr" in s["description"] or "도메인 미상): g_cnt" in s["description"] for s in mcdc)


def test_a_final_step_failure_is_said_as_one(monkeypatch):
    # (review R86 W-R3-2 · I-R3-1 M1) the extended generation's last written-output step failed: the round columns stay,
    #   only the late outputs went back — said apart from a round failure
    real_add, real_ext = suts._add_written_outputs, suts.extended_unit_sequences
    phase = {"p": 1}

    def add(u, rows, record, round_):
        if round_ == "final" and phase["p"] == 1:
            raise RuntimeError("final")
        return real_add(u, rows, record, round_)

    def ext(*a, **k):
        try:
            return real_ext(*a, **k)
        finally:
            phase["p"] = 2
    monkeypatch.setattr(suts, "_add_written_outputs", add)
    monkeypatch.setattr(suts, "extended_unit_sequences", ext)
    unit = _design_unit()
    reference_unit_sequences(unit, 24)
    rc = unit["reference_columns"]
    assert rc["error"] is None and rc["extension_errors"] == {"source_written_outputs.final": "RuntimeError"}
    assert rc["inputs_added"] >= 2 and "final_error" not in unit["source_written_outputs"]
    s = summarize_reference_columns([unit])
    assert s["units_extension_final_errors"] == 1 and s["units_extension_round_errors"] == 0
    assert s["units_extension_output_errors"] == 0   # (review R86 I-R5-2)
    note = {i["key"]: i for i in build_disclosures("suts", {"reference_columns": s})}["suts_reference_columns"]["note"]
    assert "마지막 출력 보완만 실패" in note and "설계서 열로 둔 unit" not in note


def test_the_remaining_names_are_counted_on_this_documents_rows(monkeypatch):
    # (review R86 I-R3-1 M7) the disclosure says the remaining names are this document's — the count runs on its rows
    real = suts._record_remaining
    seen = []

    def spy(u, rows):
        seen.append(rows)
        return real(u, rows)
    monkeypatch.setattr(suts, "_record_remaining", spy)
    unit = _design_unit()
    ref = reference_unit_sequences(unit, 24)
    assert len(seen) >= 2 and seen[-1] is ref and all(r is not ref for r in seen[:-1])   # pass 1's calls, then these rows


def test_an_mcdc_row_names_a_blank_prior_value_as_one():
    # (review R86 I-R3-2) an input added only as a write's prior value is written, not read
    unit = _design_unit()
    ref = reference_unit_sequences(unit, 24)
    prior = suts._prior_input_names(unit)
    assert prior, "the fixture must have a prior-value input (g_res: written, never read)"
    rows = [s for s in ref if s["strategy"].startswith("MCDC_") and any(p not in s["inputs"] for p in prior)]
    assert rows and all("쓰기 전 값(공란" in s["description"] for s in rows)
    assert not any(any(f"{p}" in s["description"].split("소스가 읽어 더한 입력(공란")[-1].split(" · 쓰기 전 값")[0]
                       for p in prior) for s in rows if "소스가 읽어 더한 입력(공란" in s["description"])


def test_the_late_outputs_initial_values_are_counted_on_this_documents_rows(monkeypatch):
    # (review R86 I-R3-1 M6) pass 2 recounts on the rows it returns
    real = suts._recount_final_initial
    seen = []

    def spy(u, rows):
        seen.append(rows)
        return real(u, rows)
    monkeypatch.setattr(suts, "_recount_final_initial", spy)
    unit = _design_unit()
    ref = reference_unit_sequences(unit, 24)
    assert len(seen) == 1 and seen[0] is ref
    rec = {"added": {"g_x": {"round": "final"}, "g_y": {"round": 1}}, "final_initial_not_in_inputs": ["g_stale"]}
    u = {"source_written_outputs": rec}
    why = {"status": "unknown", "reason": suts.UNWRITTEN_OUTPUT_PREFIX + ":g_x"}
    real(u, [{"expected_evidence": {"g_x": why, "g_y": why}}])
    assert rec["final_initial_not_in_inputs"] == ["g_x"]
    real(u, [{"expected_evidence": {}}])
    assert "final_initial_not_in_inputs" not in rec


def test_an_output_axis_stopped_in_a_round_is_not_said_as_design_columns(monkeypatch):
    # (review R86 W-R4-1) the written-output axis failing inside the rounds keeps the input columns
    def add(*a, **k):
        raise RuntimeError("axis")
    monkeypatch.setattr(suts, "_add_written_outputs", add)
    unit = _design_unit()
    reference_unit_sequences(unit, 24)
    rc = unit["reference_columns"]
    assert rc["extension_errors"].get("source_written_outputs") == "RuntimeError" and rc["inputs_added"] >= 2
    s = summarize_reference_columns([unit])
    assert s["units_extension_output_errors"] == 1 and s["units_extension_round_errors"] == 0
    note = {i["key"]: i for i in build_disclosures("suts", {"reference_columns": s})}["suts_reference_columns"]["note"]
    assert "출력 보완이 회차 중 멈춰" in note and "설계서 열로 둔 unit" not in note


def test_an_input_completion_failure_is_said_as_design_columns(monkeypatch):
    def fail(*a, **k):
        raise KeyError("x")
    monkeypatch.setattr(suts, "complete_source_read_inputs", fail)
    unit = _design_unit()
    reference_unit_sequences(unit, 24)
    s = summarize_reference_columns([unit])
    assert s["units_extension_round_errors"] == 1 and s["units_extension_output_errors"] == 0
    note = {i["key"]: i for i in build_disclosures("suts", {"reference_columns": s})}["suts_reference_columns"]["note"]
    assert "입력 보완이 실패해 그 열을 설계서 열로 둔 unit 1" in note


def test_a_unit_with_two_failures_is_counted_once():
    # (review R86 I-R5-1) the final step also runs after an earlier failure — the unit is said by the earlier one
    recs = [{"reference_columns": {"extension_errors": {"source_written_outputs": "E", "source_written_outputs.final": "E"}}},
            {"reference_columns": {"extension_errors": {"source_read_inputs": "E", "source_written_outputs": "E",
                                                        "source_written_outputs.final": "E"}}}]
    s = summarize_reference_columns(recs)
    assert (s["units_extension_round_errors"], s["units_extension_output_errors"], s["units_extension_final_errors"]) == (1, 1, 0)
