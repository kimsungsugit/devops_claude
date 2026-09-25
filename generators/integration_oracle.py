"""(R16, 격차 ②) SITS expected values from the integrated code — the entry function evaluated with its callees run.

The unit oracle (`generators.c_source_oracle`) treats a callee as its write closure: whatever it may write is unknown.
An integration test runs the callees for real, so its expectation is what the **integrated** code leaves in the
observed objects. `CalleeProvider` gives the oracle the one project definition a call binds to; `_World` in the oracle
interprets it with the argument values and joins its paths back. This module wires that into SITS: per test case, the
entry function's unit (its translation unit's text and scope) plus the provider, then `apply_sequence_evidence` — the
same provenance path as SUTS, so a derived value carries its basis and assumptions, and an unknown carries its reason.

Not an execution result, not target behaviour: hardware (volatile objects), interrupts and other tasks are outside the
model, and a callee that cannot be interpreted leaves what it may write unknown. Reported per generation.
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Any

from generators.c_source_oracle import Unsupported, _parsed_function, scope_matches
from generators.test_evidence import VERIFY_PREFIX, apply_sequence_evidence

_logger = logging.getLogger(__name__)


_BUDGET_PROBE = 2   # sub-cases run before a flow that exceeds the step budget in all of them is not run further
_BUDGET_REASONS = frozenset({"execution_budget", "constant_condition_loop_unfinished"})


def _refused_for_budget(sub: dict[str, Any]) -> bool:
    """Every cell of the sub-case is unknown because the whole run exceeded the oracle's step budget."""
    evidence = sub.get("expected_evidence") or {}
    return bool(evidence) and all(ev.get("status") != "derived" and str(ev.get("reason") or "") in _BUDGET_REASONS
                                  for ev in evidence.values())


def _internal_linkage(fn, raw: bytes) -> bool:
    return any(c.type == "storage_class_specifier" and raw[c.start_byte:c.end_byte].decode("utf-8", "replace") == "static"
               for c in fn.children)


class CalleeProvider:
    """``definition(name, caller_unit)`` → ``(raw, fn, scope, shared, path)`` of the definition a call binds to.

    A call binds to a definition in the caller's own translation unit when there is one compiled there (a ``static``
    function or the external definition itself); otherwise to the one external (non-``static``) definition compiled in
    another unit of the same build (with several source roots, each root is a separate build). None, several, or a candidate that could not be read (parse error, unresolved ``#if``) — the call is
    not interpreted (`Unsupported` with the reason). A definition only in a header is not a unit's text: not interpreted.
    """

    def __init__(self, context: dict[str, Any], source_files: dict[str, str], scopes: dict[str, dict[str, Any]], parser):
        self.files, self.scopes, self.parser = source_files, scopes, parser
        self.context = context
        self.defs: dict[str, list[str]] = {}
        self.header_defs: dict[str, list[str]] = {}
        for path, rec in (context.get("files") or {}).items():
            for name in rec.get("functions") or {}:
                (self.defs if path.lower().endswith(".c") else self.header_defs).setdefault(name, []).append(path)
        self.cache: dict[tuple[str, str], Any] = {}
        self.linkage_cache: dict[int, tuple] = {}   # `_World.admit`'s per-scope entries — lives with these scopes
        self.binding_assumptions: dict[tuple[str, str], set[str]] = {}   # (R17) names a binding choice rested on
        self._statics_by_file: dict[str, Any] = {}
        # (review W-R2-1) names that denote more than one object in the project: an internal-linkage object of one
        # unit and any other object of the same name (a header ``static`` counts once per including unit)
        owners: dict[str, set[str]] = {}
        for unit, scope in scopes.items():
            for table in (scope.get("globals") or {}, scope.get("arrays") or {}):
                for name, rec in table.items():
                    owners.setdefault(name, set()).add(unit if rec.get("static") else "")
        self.ambiguous_names = frozenset(n for n, o in owners.items() if len(o) > 1)

    def definition(self, name: str, caller_unit: str):
        key = (name, caller_unit)
        if key not in self.cache:
            try:
                self.cache[key] = self._resolve(name, caller_unit)
            except Unsupported as exc:
                self.cache[key] = exc
        hit = self.cache[key]
        if isinstance(hit, Unsupported):
            raise Unsupported(str(hit))
        return hit

    def has_static_locals(self, name: str) -> bool:
        """Does some definition of ``name`` declare a ``static`` local (state a later call reads)? Unreadable → yes.
        One scan per file (review R3 I-1), with its own parse — the oracle's parse cache is not churned."""
        if name in self.header_defs:
            return True   # a header's text is not scanned here: assume it may
        for path in self.defs.get(name) or ():
            if path not in self._statics_by_file:
                self._statics_by_file[path] = self._scan_statics(path)
            found = self._statics_by_file[path]
            if found is None or name in found:
                return True
        return False

    def _scan_statics(self, path: str):
        """Names of the functions in ``path`` that declare a static local; None when the file cannot be read."""
        text = self.files.get(path)
        if not text:
            return None
        raw = text.encode()
        tree = self.parser.parse(raw)
        if tree.root_node.has_error:
            return None
        from generators.mcdc_design import _function_name
        out: set[str] = set()
        for fn in (n for n in tree.root_node.named_children if n.type == "function_definition"):
            stack = [fn.child_by_field_name("body")] if fn.child_by_field_name("body") is not None else []
            while stack:
                x = stack.pop()
                if x.type == "declaration" and any(c.type == "storage_class_specifier" and
                                                   raw[c.start_byte:c.end_byte] == b"static" for c in x.children):
                    out.add(_function_name(fn, raw)[0])
                    break
                stack.extend(x.named_children)
        return out

    def _resolve(self, name: str, caller_unit: str):
        caller_files = set((self.scopes.get(caller_unit) or {}).get("files") or ()) - {caller_unit}
        if caller_files & (set(self.header_defs.get(name) or ()) | set(self.defs.get(name) or ())):
            # (review C6, C-R2-2) a file the caller includes defines it (``static inline`` in a header, a ``.c`` included
            # into the unit): that text, under the caller's macros, is the function the call names — not interpreted
            # here, and never bound to the same file compiled on its own or to a namesake
            raise Unsupported("defined_in_included_file")
        paths = self.defs.get(name) or []
        if not paths:
            raise Unsupported("defined_in_header_only" if name in self.header_defs else "no_definition_in_project")
        if self.context.get("roots"):
            # several source roots are separate builds (APP and BOOT both define ``EEPROM_SetByte``): a call links
            # within its own build only — the same rule the context applies to a header name (`_resolve_include`)
            from generators.c_project_context import _root_of
            mine = _root_of(self.context, caller_unit)
            paths = [p for p in paths if mine and _root_of(self.context, p) == mine]
            if not paths:
                raise Unsupported("no_definition_in_own_build")
        order = ([caller_unit] if caller_unit in paths else []) + [p for p in paths if p != caller_unit]
        found, doubts = [], []
        for path in order:
            scope, text = self.scopes.get(path), self.files.get(path)
            if scope is None or not text or not scope_matches({"source_text": text, "project_scope": scope}):
                doubts.append("unit_not_scoped")
                continue
            raw = text.encode()
            try:
                _root, fn, shared = _parsed_function(self.parser, raw, name, scope)
            except Unsupported as exc:
                if str(exc) != "function_not_compiled_in_configuration":
                    doubts.append(str(exc))
                else:
                    # (R17 review R2 W2) excluded by that unit's #if verdicts: the binding rests on them too
                    self.binding_assumptions.setdefault((name, caller_unit), set()).update(
                        set(scope.get("assumed_undefined") or ()) | set(scope.get("assumed_undefined_body") or ()))
                continue
            if path == caller_unit:
                return raw, fn, scope, shared, path  # the caller's unit names its own definition
            if _internal_linkage(fn, raw):
                continue  # a static function of another unit is not what this call reaches
            found.append((raw, fn, scope, shared, path))
        if doubts:
            # a candidate we could not read may be the one this configuration links — never guess between them
            raise Unsupported("definition_uncertain:" + doubts[0])
        if len(found) != 1:
            raise Unsupported("definition_ambiguous" if found else "no_external_definition")
        return found[0]


def attach_integration_evidence(itcs: list[dict[str, Any]], report_data: dict[str, Any] | None,
                                function_details: dict[str, Any] | None, parser=None,
                                on_progress=None) -> dict[str, Any]:
    """Re-derive every SITS sub-case's expected values with the interprocedural oracle. Returns the disclosure block.

    A test case whose entry function has no single readable definition keeps its `[검증 필요]` cells, counted by
    reason (``tc_skipped``). Never raises past a test case — a failure is that test's reason.
    """
    from generators.c_project_context import SCHEMA_VERSION, build_scopes, shared_parser
    t0 = time.time()
    stats: dict[str, Any] = {"status": "", "tc_total": len(itcs), "tc_evaluated": 0, "tc_with_derived": 0,
                             "tc_skipped": {}, "sub_cases": 0, "cells": 0, "derived": 0, "derived_assigned": 0,
                             "derived_unchanged_input": 0, "unknown_reasons": {}, "inlined_calls": 0,
                             "not_inlined": {}, "units_scoped": 0, "elapsed_s": 0.0}
    context = (report_data or {}).get("project_context") or {}
    files = (report_data or {}).get("source_files") or {}
    if not context.get("files") or not files:
        stats["status"] = "no_project_context"
        return stats
    if context.get("schema_version") != SCHEMA_VERSION:
        stats["status"] = f"project_context_schema_mismatch:{context.get('schema_version')}"
        return stats
    parser = parser or shared_parser()
    if parser is None:
        stats["status"] = "tree_sitter_unavailable"
        return stats
    paths_of: dict[str, set[str]] = {}
    for info in (function_details or {}).values():
        if isinstance(info, dict) and info.get("name") and info.get("source_path"):
            paths_of.setdefault(str(info["name"]), set()).add(str(info["source_path"]))
    units = [p for p in context["files"] if p.lower().endswith(".c") and p in files]
    scopes = build_scopes(context, units)
    stats["units_scoped"] = len(scopes)
    from generators.c_project_context import summarize_build_assumptions
    stats["build_assumptions"] = summarize_build_assumptions(scopes.values())   # (R17)
    provider = CalleeProvider(context, files, scopes, parser)
    skipped: Counter = Counter()
    reasons: Counter = Counter()
    not_inlined: Counter = Counter()
    timings: list[tuple[float, str]] = []
    for position, itc in enumerate(itcs, start=1):
        if on_progress is not None:
            on_progress(position, len(itcs))
        subs = itc.get("sub_cases") or []
        entry = str(itc.get("entry_fn") or "")
        paths = paths_of.get(entry) or set()
        if not subs:
            skipped["no_sub_cases"] += 1
            continue
        if len(paths) != 1:
            skipped["entry_definition_missing" if not paths else "entry_definition_ambiguous"] += 1
            continue
        path = next(iter(paths))
        if path not in scopes:
            skipped["entry_unit_not_scoped"] += 1
            continue
        t_tc = time.time()
        unit = {"name": entry, "source_text": files[path], "source_text_complete": True, "source_path": path,
                "project_scope": scopes[path], "callee_provider": provider, "output_vars": []}
        try:
            head = subs[:_BUDGET_PROBE]
            apply_sequence_evidence(unit, head)
            if len(subs) > len(head) and all(_refused_for_budget(s) for s in head):
                # (deterministic) the flow does not finish within the step budget for its first sub-cases (``main``'s
                # endless loop): the others are not run — each cell says why instead of spending minutes to say it
                stats["tc_budget_cut"] = stats.get("tc_budget_cut", 0) + 1
                apply_sequence_evidence({**unit, "oracle_refusal":
                                         f"execution_budget:not_run_after_{len(head)}_sub_cases_exceeded_it"},
                                        subs[len(head):])
            else:
                apply_sequence_evidence(unit, subs[len(head):])
        except Exception as exc:  # noqa: BLE001 — one test's failure keeps its `[검증 필요]` cells, with the reason
            _logger.warning("SITS integration oracle failed on %s (%s)", itc.get("tc_id"), type(exc).__name__,
                            exc_info=True)
            skipped[f"error:{type(exc).__name__}"] += 1
            failed = True
        else:
            failed = False
            stats["tc_evaluated"] += 1
        derived_here = 0
        for sub in subs:
            stats["sub_cases"] += 1
            for var, ev in (sub.get("expected_evidence") or {}).items():
                if var not in (sub.get("expected") or {}):
                    continue
                stats["cells"] += 1
                if ev.get("status") == "derived":
                    derived_here += 1
                    stats["derived"] += 1
                    stats["derived_unchanged_input" if ev.get("basis") == "unchanged_input" else "derived_assigned"] += 1
                else:
                    reasons[str(ev.get("reason") or "").split(":", 1)[0] or "unrecorded"] += 1
            for name, count in ((sub.get("interprocedural") or {}).get("not_inlined") or {}).items():
                not_inlined[name] += count
            stats["inlined_calls"] += sum(((sub.get("interprocedural") or {}).get("inlined") or {}).values())
        if derived_here and not failed:
            stats["tc_with_derived"] += 1
        timings.append((round(time.time() - t_tc, 1), str(itc.get("tc_id") or entry)))
    stats["tc_skipped"] = dict(skipped.most_common())
    stats["unknown_reasons"] = dict(reasons.most_common(12))
    stats["unknown_reason_kinds"] = len(reasons)
    stats["not_inlined"] = dict(not_inlined.most_common())
    stats["slowest_tc"] = [f"{tc} {sec}s" for sec, tc in sorted(timings, reverse=True)[:5]]
    stats["status"] = "evaluated"
    stats["elapsed_s"] = round(time.time() - t0, 1)
    return stats


TEST_EVIDENCE_HEADERS = ["Test Case ID", "Case", "Entry function", "Observable", "Expected", "Status", "Oracle",
                         "Execution", "Basis", "Reason", "Callees interpreted", "Callees effects-only", "Source path",
                         "Source SHA256", "Inputs JSON", "Assumptions"]


_CELL_MAX = 32_767   # Excel's text cell limit: longer text makes the workbook "need repair" (review W7)


def _cell(text: str) -> str:
    if len(text) <= _CELL_MAX:
        return text
    note = f" …[truncated {len(text) - (_CELL_MAX - 40)} chars]"
    return text[:_CELL_MAX - len(note)] + note


def write_integration_evidence_sheet(wb, itcs: list[dict[str, Any]]) -> int:
    """(R16) 'Test Evidence' sheet — per expected cell: derived (with what it rests on) or why not. Only when some cell
    was evaluated (a SITS without the integration oracle has nothing to add to its ``[검증 필요]`` cells)."""
    import json
    rows = []
    for itc in itcs:
        for i, sub in enumerate(itc.get("sub_cases") or [], start=1):
            evidence = sub.get("expected_evidence") or {}
            for var in dict.fromkeys([*(sub.get("expected") or {}), *evidence]):
                ev = evidence.get(var) or {}
                value = (sub.get("expected") or {}).get(var, "")
                rows.append([itc.get("tc_id", ""), sub.get("case_num", i), itc.get("entry_fn", ""), var,
                             value if isinstance(value, int) else str(value), ev.get("status", "unrecorded"),
                             ev.get("oracle_kind", "none"), ev.get("execution_status", "not_run"), ev.get("basis", ""),
                             ev.get("reason", "provenance_missing"), ", ".join(ev.get("callees_interpreted") or ()),
                             ", ".join(ev.get("callees_effects_only") or ()), ev.get("source_path", ""), ev.get("source_hash", ""),
                             _cell(json.dumps(sub.get("inputs") or {}, ensure_ascii=False, sort_keys=True, default=str)),
                             _cell("; ".join(ev.get("assumptions") or ()))])
    if not any(r[6] == "source" for r in rows):
        return 0
    if "Test Evidence" in wb.sheetnames:
        del wb["Test Evidence"]
    ws = wb.create_sheet("Test Evidence")
    ws.append(TEST_EVIDENCE_HEADERS)
    for r in rows:
        ws.append(r)
    for cell in (c for row in ws.iter_rows(min_row=2) for c in row):   # scan-ok: one pass to pin text cells as text
        if isinstance(cell.value, str):
            cell.data_type = "s"   # paths / IDs starting with a formula character stay text
    ws.freeze_panes = "A2"
    return len(rows)


__all__ = ["CalleeProvider", "attach_integration_evidence", "write_integration_evidence_sheet", "VERIFY_PREFIX"]
