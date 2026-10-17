"""Expected-result provenance shared by unit and integration generators."""
from __future__ import annotations

import hashlib
from typing import Any

from generators.c_source_oracle import evaluate_outputs, scope_matches
from generators.c_test_semantics import evaluate_function_inputs

VERIFY_PREFIX = "[검증 필요]"

#: The derivation fields `apply_sequence_evidence` attaches to a derived cell only. A cell a later pass downgrades to
#: unknown (a row whose stimulus is not in the document — `suts.render_row_io`, `sits_read_inputs`) drops all of them: an
#: unknown cell must not state a basis. One list for every downgrade (R93 integration: two copies drifted — the register
#: model's fields were missing from both). Guard: `tests/unit/test_sits_read_inputs.py`
#: `::test_downgrade_drops_every_derivation_field_the_oracle_sets` reads this module's ``item["…"] =`` assignments.
DERIVATION_FIELDS: tuple[str, ...] = (
    "basis", "assumptions", "stubs", "assumed_undefined", "callees_interpreted", "callees_effects_only",
    "observed_only_pointees", "exact_width_guards", "possible_ub_on_forked_path",
    "polling_loops_assumed", "storage_objects", "storage_registers",
    # (callee contract G5 / G6) the callees run as their write closure whose return was assumed / UB not analysed
    "callee_termination_assumed", "callee_ub_unanalysed")


def apply_sequence_evidence(unit: dict[str, Any], sequences: list[dict[str, Any]],
                            written: bool = False) -> list[dict[str, Any]]:
    """Replace speculative expectations and attach explicit oracle provenance.

    Source evaluation is a code-consistency oracle only. It does not establish
    requirement correctness, target execution or structural coverage.
    ``written`` (R80): each sequence the project-context oracle ran also gets ``seq["source_written"]`` — the program
    objects that run wrote, ``{name: value known}`` (the SUTS reads it for the outputs a design table omits).
    """
    source = str(unit.get("source_text") or "")
    if not unit.get("source_text_complete", True):
        source = ""
    output_lists = [list(dict.fromkeys([*(unit.get("output_vars") or []), *(s.get("expected") or {}),
                                        *(s.get("ai_expected_candidates") or {})])) for s in sequences]
    scoped = bool(source) and scope_matches(unit)
    # A project scope of another text (edited file, normalized line ends) is never used — say so (R2b review I1).
    scope_note = "project_scope_mismatch" if source and unit.get("project_scope") and not scoped else ""
    if scoped:
        # (R2b) Project-context oracle: every output — globals, array elements, return — for the whole function.
        results = evaluate_outputs(unit, [s.get("inputs") or {} for s in sequences], output_lists, written=written)
    elif source:
        results = evaluate_function_inputs(source, str(unit.get("name") or ""), [s.get("inputs") or {} for s in sequences])
    else:
        results = [{"status": "unsupported", "reason": unit.get("source_unavailable_reason") or "authoritative_source_missing"}
                   for _ in sequences]
    # (R62) the text read is the file with this function's split #if groups projected (`apply_body_projection`): its hash
    # is not the file's — say which text was hashed. (R63) and with the vendor syntax read as blanks / a bare #define's
    # trailing blanks moved (`reading_text`): the scope lists what made the difference (``read_text_changes``)
    projected = scoped and (unit.get("project_scope") or {}).get("projected_sha256") == \
        hashlib.sha256(source.encode()).hexdigest()
    changes = (unit.get("project_scope") or {}).get("read_text_changes") or ["as_read"]
    hash_scope = "captured_decoded_utf8_text_" + "_".join(changes) if projected else "captured_decoded_utf8_text"
    for seq, evaluated, outputs in zip(sequences, results, output_lists, strict=True):
        old = seq.get("expected") or {}
        candidates = seq.setdefault("expected_candidates", {})
        for key, value in old.items():
            if not str(value).startswith(VERIFY_PREFIX) and not (seq.get("expected_evidence") or {}).get(key):
                candidates.setdefault(key, value)
        expected, evidence = {}, {}
        for var in outputs:
            if scoped:
                slot = (evaluated.get("outputs") or {}).get(var) or {"reason": evaluated.get("reason", "unsupported_output_binding")}
                derived, value = "value" in slot, slot.get("value")
                reason = evaluated.get("reason", "") if derived else slot.get("reason", "unsupported_output_binding")
            else:
                derived = var == "return" and evaluated["status"] == "supported"
                value = evaluated.get("value")
                reason = evaluated.get("reason", "unsupported_output_binding") if var == "return" else "unsupported_output_binding"
            ai = (seq.get("ai_expected_candidates") or {}).get(var)
            item = {"status": "derived" if derived else ("proposed" if ai is not None else "unknown"),
                    "oracle_kind": "source" if derived else ("ai" if ai is not None else "none"),
                    "reason": reason, "execution_status": "not_run",
                    "source_hash": evaluated.get("source_hash", ""),
                    "source_hash_scope": hash_scope,
                    "source_path": str(unit.get("source_path") or ""),
                    "function_name": str(unit.get("name") or ""),
                    "requirement_verified": False}
            if scoped and derived:
                item["basis"] = slot.get("basis", "")
                item["assumptions"] = list(evaluated.get("assumptions") or ())
                if evaluated.get("stubs"):
                    # (R14 review W3) the sequence stubbed these callees — the value holds only when the tester stubs
                    # them too (recorded per sequence: an output that does not use the stub carries it as well)
                    item["stubs"] = list(evaluated["stubs"])
                if evaluated.get("assumed_undefined"):
                    # (R17) #if verdicts this value rests on: names undefined on build-configuration evidence
                    item["assumed_undefined"] = list(evaluated["assumed_undefined"])
                if evaluated.get("forked_path_undefined_behavior"):
                    # (R90 review W1) the run had undefined behaviour on a path a branch on an unknown value chose — the
                    #   value holds for runs that do not take it (`c_source_oracle._Interp.undefined`)
                    item["possible_ub_on_forked_path"] = [f"{x['kind']} (selector {x['selector']})"
                                                          for x in evaluated["forked_path_undefined_behavior"]]
                if evaluated.get("exact_width_guards"):
                    # (R83) exact-width typedefs read past an undecided `#ifndef` guard that the function names
                    item["exact_width_guards"] = list(evaluated["exact_width_guards"])
                if evaluated.get("observed_only_pointees"):
                    # (R81 review I-R2-3) pointees set up only because the row observes them (it sets no value there)
                    item["observed_only_pointees"] = list(evaluated["observed_only_pointees"])
                if evaluated.get("polling_loops_assumed"):
                    # (R90 review W1) polling loops on a register flag the run assumed to end (the harness must too)
                    item["polling_loops_assumed"] = list(evaluated["polling_loops_assumed"])
                if evaluated.get("storage_objects"):
                    # (R90 re-review W-N3) union / bit-field objects the run read or wrote through the storage model,
                    #   and the registers among them it read as harness memory
                    item["storage_objects"] = list(evaluated["storage_objects"])
                if evaluated.get("storage_registers"):
                    item["storage_registers"] = list(evaluated["storage_registers"])
                # (callee contract G5 / G6) callees run as their write closure: their return assumed / their undefined
                #   behaviour not analysed — the value holds where they return / have none (one literal key each: the
                #   derivation-field lists read these assignments)
                if evaluated.get("callee_termination_assumed"):
                    item["callee_termination_assumed"] = list(evaluated["callee_termination_assumed"])
                if evaluated.get("callee_ub_unanalysed"):
                    item["callee_ub_unanalysed"] = list(evaluated["callee_ub_unanalysed"])
                if (evaluated.get("interprocedural") or {}).get("inlined"):
                    # (R16) the value rests on these callees' interpreted bodies (integration reading, not stubs)
                    item["callees_interpreted"] = sorted(evaluated["interprocedural"]["inlined"])
                if (evaluated.get("interprocedural") or {}).get("effects_only"):
                    # (R16b review R3 W3-1) and these ran as their write closure at some call site
                    item["callees_effects_only"] = sorted(evaluated["interprocedural"]["effects_only"])
            if scope_note:
                item["project_scope"] = scope_note
                if not derived:
                    item["reason"] = f"{scope_note};{reason}"
            # Preserve intentionally omitted unknown-type/pointer value cells;
            # provenance still records that observable as unresolved.
            # (R81 review W-R3-1) except a pointer parameter whose pointee the row's observation set up (`pointer_value`):
            #   the row's other values rest on that harness object, so the cell says so instead of staying blank — a
            #   blank cell is no observation for a reader or a harness (`mutation_eval` reads the cells a row has)
            if derived or var in old or var in (seq.get("ai_expected_candidates") or {}) \
                    or (scoped and reason == "pointer_value"):
                expected[var] = value if derived else f"{VERIFY_PREFIX} {reason}"
            evidence[var] = item
        seq["expected"], seq["expected_evidence"] = expected, evidence
        seq["execution_status"] = "not_run"
        if written and "written" in evaluated:
            seq["source_written"] = dict(evaluated["written"])
        else:
            seq.pop("source_written", None)   # an earlier run's record is not this one's
        if evaluated.get("forked_path_undefined_behavior"):
            # (R90 review C1) proven on a path a branch on an unknown value chose — a finding still (`source_findings`)
            seq["forked_path_undefined_behavior"] = [dict(x) for x in evaluated["forked_path_undefined_behavior"]]
        else:
            seq.pop("forked_path_undefined_behavior", None)
        if written and evaluated.get("written_unknown"):
            seq["source_written_unknown"] = dict(evaluated["written_unknown"])   # (R81) why a written object stays unknown
        else:
            seq.pop("source_written_unknown", None)
        if written and evaluated.get("written_error"):
            seq["source_written_error"] = evaluated["written_error"]   # (review R80 W1) counted, not silent
        else:
            seq.pop("source_written_error", None)
        if evaluated.get("interprocedural") is not None:
            seq["interprocedural"] = evaluated["interprocedural"]
        # Remove earlier prose containing invented expectations as well.
        desc = str(seq.get("description") or "")
        seq["description"] = "\n".join(line for line in desc.splitlines() if not line.startswith(("Expected:", "근거: 소스 계산")))
        if expected:
            seq["description"] += "\nExpected: " + ", ".join(f"{v}={x}" for v, x in expected.items())
        if any(x["status"] == "derived" for x in evidence.values()):
            seq["description"] += "\n근거: 소스 계산 (요구 적합성 미검증, 실행 미실시)"
    return sequences


def summarize_expected_evidence(sequences: list[dict[str, Any]]) -> dict[str, int]:
    """Count all expected slots, treating absent provenance as unrecorded."""
    counts = {"derived": 0, "unknown": 0, "proposed": 0, "unrecorded": 0, "total": 0,
              # (R2b) ``derived`` split: a value the function assigned vs an output it left as the sequence set it.
              "derived_assigned": 0, "derived_unchanged_input": 0,
              # (R14) derived in a sequence that stubbed a callee return — an upper bound of the values that rest on it
              "derived_in_stubbed_sequence": 0,
              # (R17) derived where the text's #if verdicts rest on build-configuration evidence (names taken as undefined)
              "derived_on_assumed_undefined": 0,
              # (R81) derived in a row whose pointer parameter's pointee is set up only because the row observes it
              "derived_on_observed_only_pointee": 0,
              # (R83) derived in a function that names an exact-width typedef read past its `#ifndef` guard
              "derived_on_exact_width_guard": 0,
              # (R90 review W1) derived in a run with undefined behaviour proven on a path an unknown branch chose
              "derived_with_possible_ub_on_forked_path": 0,
              # (R90 review W1) derived on a run that assumed a polling loop on a register flag ends
              "derived_on_assumed_polling_exit": 0,
              # (R90 re-review W-N3) derived on a run that used the union / bit-field storage model — and that read a
              #   register as harness memory (row-level upper bounds, like the others)
              "derived_on_storage_model": 0, "derived_on_register_memory": 0,
              # (callee contract G5 / G6) derived on a run that ran a callee as its write closure: its return assumed
              #   (its text does not prove it) / its undefined behaviour not analysed
              "derived_on_assumed_callee_termination": 0, "derived_with_callee_ub_unanalysed": 0}
    for seq in sequences:
        for var in set(seq.get("expected") or {}) | set(seq.get("expected_evidence") or {}):
            item = seq.get("expected_evidence", {}).get(var) or {}
            status = item.get("status", "unrecorded")
            counts[status if status in {"derived", "unknown", "proposed"} else "unrecorded"] += 1
            counts["total"] += 1
            if status == "derived" and item.get("basis") == "unchanged_input":
                counts["derived_unchanged_input"] += 1
            elif status == "derived":
                counts["derived_assigned"] += 1
            if status == "derived" and item.get("stubs"):
                counts["derived_in_stubbed_sequence"] += 1
            if status == "derived" and item.get("assumed_undefined"):
                counts["derived_on_assumed_undefined"] += 1
            if status == "derived" and item.get("exact_width_guards"):
                counts["derived_on_exact_width_guard"] += 1
            if status == "derived" and item.get("possible_ub_on_forked_path"):
                counts["derived_with_possible_ub_on_forked_path"] += 1
            if status == "derived" and item.get("observed_only_pointees"):
                counts["derived_on_observed_only_pointee"] += 1
            if status == "derived" and item.get("polling_loops_assumed"):
                counts["derived_on_assumed_polling_exit"] += 1
            if status == "derived" and item.get("storage_objects"):
                counts["derived_on_storage_model"] += 1
            if status == "derived" and item.get("storage_registers"):
                counts["derived_on_register_memory"] += 1
            if status == "derived" and item.get("callee_termination_assumed"):
                counts["derived_on_assumed_callee_termination"] += 1
            if status == "derived" and item.get("callee_ub_unanalysed"):
                counts["derived_with_callee_ub_unanalysed"] += 1
    return counts
