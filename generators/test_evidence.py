"""Expected-result provenance shared by unit and integration generators."""
from __future__ import annotations

from typing import Any

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
    results = evaluate_function_inputs(source, str(unit.get("name") or ""), [s.get("inputs") or {} for s in sequences]) if source else [
        {"status": "unsupported", "reason": unit.get("source_unavailable_reason") or "authoritative_source_missing"} for _ in sequences]
    for seq, evaluated in zip(sequences, results, strict=True):
        old = seq.get("expected") or {}
        candidates = seq.setdefault("expected_candidates", {})
        for key, value in old.items():
            if not str(value).startswith(VERIFY_PREFIX) and not (seq.get("expected_evidence") or {}).get(key):
                candidates.setdefault(key, value)
        outputs = list(dict.fromkeys([*(unit.get("output_vars") or []), *old, *(seq.get("ai_expected_candidates") or {})]))
        expected, evidence = {}, {}
        for var in outputs:
            derived = var == "return" and evaluated["status"] == "supported"
            ai = (seq.get("ai_expected_candidates") or {}).get(var)
            reason = evaluated.get("reason", "unsupported_output_binding") if var == "return" else "unsupported_output_binding"
            item = {"status": "derived" if derived else ("proposed" if ai is not None else "unknown"),
                    "oracle_kind": "source" if derived else ("ai" if ai is not None else "none"),
                    "reason": reason, "execution_status": "not_run",
                    "source_hash": evaluated.get("source_hash", ""),
                    "source_hash_scope": "captured_decoded_utf8_text",
                    "source_path": str(unit.get("source_path") or ""),
                    "function_name": str(unit.get("name") or ""),
                    "requirement_verified": False}
            # Preserve intentionally omitted unknown-type/pointer value cells;
            # provenance still records that observable as unresolved.
            if derived or var in old or var in (seq.get("ai_expected_candidates") or {}):
                expected[var] = evaluated["value"] if derived else f"{VERIFY_PREFIX} {reason}"
            evidence[var] = item
        seq["expected"], seq["expected_evidence"] = expected, evidence
        seq["execution_status"] = "not_run"
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
    counts = {"derived": 0, "unknown": 0, "proposed": 0, "unrecorded": 0, "total": 0}
    for seq in sequences:
        for var in set(seq.get("expected") or {}) | set(seq.get("expected_evidence") or {}):
            status = (seq.get("expected_evidence", {}).get(var) or {}).get("status", "unrecorded")
            counts[status if status in counts and status != "total" else "unrecorded"] += 1
            counts["total"] += 1
    return counts
