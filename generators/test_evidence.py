"""Expected-result provenance shared by unit and integration generators."""
from __future__ import annotations

from typing import Any

from generators.c_source_oracle import evaluate_outputs, scope_matches
from generators.c_test_semantics import evaluate_function_inputs

VERIFY_PREFIX = "[검증 필요]"


def apply_sequence_evidence(unit: dict[str, Any], sequences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace speculative expectations and attach explicit oracle provenance.

    Source evaluation is a code-consistency oracle only. It does not establish
    requirement correctness, target execution or structural coverage.
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
        results = evaluate_outputs(unit, [s.get("inputs") or {} for s in sequences], output_lists)
    elif source:
        results = evaluate_function_inputs(source, str(unit.get("name") or ""), [s.get("inputs") or {} for s in sequences])
    else:
        results = [{"status": "unsupported", "reason": unit.get("source_unavailable_reason") or "authoritative_source_missing"}
                   for _ in sequences]
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
                    "source_hash_scope": "captured_decoded_utf8_text",
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
            if derived or var in old or var in (seq.get("ai_expected_candidates") or {}):
                expected[var] = value if derived else f"{VERIFY_PREFIX} {reason}"
            evidence[var] = item
        seq["expected"], seq["expected_evidence"] = expected, evidence
        seq["execution_status"] = "not_run"
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
              "derived_on_assumed_undefined": 0}
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
    return counts
