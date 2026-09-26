"""Historical change replay on the current source (G1 b).

A unit-test log keeps the code it tested: a VectorCAST aggregate coverage report lists every line of the unit as it was
instrumented (macros expanded). Two logs of one project — an older and a newer run — therefore give an older and a newer
body of every function whose listed code changed in between. "Changed" means the macro-expanded text changed: a
calibration value or version byte that came in through a macro is a change too (flagged ``literal_only``). Each pair is
replayed on the current source: the older and the newer body are each put in place of the function in its current file
and run by the source oracle (`generators/c_source_oracle.py`) on the vectors of both suites (the reference SUTS and a
generated SUTS), a deterministic sample over every typed object either body mentions (the R4 harness's sampler,
`scripts/mutation_eval.py` — reads, and the starting value of what a body writes), and vectors at each integer literal
the two bodies do not share, ±1 (a calibration change bites only there).

A pair is **distinguished** when a vector gives a different determined value to a slot a suite states or to an object
either body writes — a plain identifier or a constant-index element ``a[3]`` (``distinguishing_example`` shows the
vector, the slot and both values; ``separated_on_suite_inputs`` says whether a suite's own vector does it). Each suite
then gets a verdict: **detected** — one of its stated values that the newer body reproduces (it passes after the change)
comes out different on the older body (it fails before): "FAIL before the fix, PASS after"; **undetermined** — a value
it states passes after while the older value at its own input is unknown (a starting value it never sets), or the
newer value is unknown and the older one fails or is unknown too, or it could not be read where its own case does not
show the two bodies equal: whether that case would fail is not decidable here; **missed** — otherwise.
``missed_by_both`` counts only pairs both suites miss; a pair that is not replayed carries no verdict. Suite cells are
read as the R3 reader does, plus the ``NAME(5)`` notation a reference writes for an enumerator (not a function-like
macro call); ``-``/``N/A`` state no value (``suite_cells`` counts them per suite and role).

A pair that is compared and never distinguished stays *undecided* (the bodies may be equivalent on these vectors) —
unless the bodies write members, pointers or computed indices differently, directly or through the value of a local
that feeds such a write (*unobserved difference*: the oracle does not observe those), one body writes an object that was
never compared
(*difference not compared*), or only numbers changed and no vector reached them (*calibration not reached*: a float or
a computed threshold the literal vectors miss); none is counted as detected or missed. A pair the two bodies never
determine the same slot of is *not comparable*; one where a body determines nothing is *not replayable* (the older code
reads a name the current code no longer declares, state no suite sets, a callee return the oracle does not know, or a
construct it refuses — the reasons are kept); a changed parameter list is *signature changed* (the suites' inputs name
the newer parameters; ``rename`` when only the names changed).

A changed body is not a defect by itself: most changes between two logs are features, refactors and tuning. A change
counts as a **documented fix** only through an evidence file (``--evidence``) that quotes the project document (problem
list, release sheet) describing it; the replay reports every change and the documented subset separately and never
infers a defect from the code.

Detections are source-consistency detections, as in R4: the generated suite's expected values come from the current
code, so a detection shows that its inputs separate the older behaviour from the newer — a regression to the older code
would not pass unnoticed — not that the suite would have found the defect before it was fixed. A pair whose newer body
no longer matches the current function on the vectors (the code changed again later) is replayed all the same and
marked ``current_equals_new: false`` (``None`` when the two never determine the same slot).

The listing's unit is matched to the current file by name: an application and a boot loader that both have a file of
that name are not told apart here (the alignment decides which definition the suites belong to).

Usage:
    .venv/Scripts/python.exe scripts/history_replay.py --old-log DIR --new-log DIR --reference REF.xlsm
        --generated GEN.xlsm --source-root ROOT[,ROOT] --alignment align.json [--evidence ev.json] --out replay.json
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_PRE = re.compile(r'<pre class="aggregate-coverage">(.*?)</pre>', re.S)
_UNIT_CELL = re.compile(r"<th>Unit</th>\s*<td>([^<]+)</td>")
_TAG = re.compile(r"<[^>]+>")
# VectorCAST 2025 puts the source line number in a leading ``<strong>`` column
_LINE_NO = re.compile(r'^(?:<span class="[^"]*">)?<strong>[^<]*</strong> ?')
# a coverage mark: ``(T)`` ``(F)`` and ``( )`` for an outcome the run did not reach (``( )(F)``, ``(T)( )``)
_MARK = r"\((?:[A-Z]| )\)"
# ``2 0     (T)    s_SystemOperation``: the function entry marker line, not a line of code
_ENTRY = re.compile(rf"^\s*\d+\s+0\s+{_MARK}\s+[A-Za-z_]\w*\s*$")
_PREFIX = 15   # ``<fn> <stmt> <marks>`` then the code, in fixed columns
_PREFIX_OK = re.compile(rf"^\s*(?:\d+\s+\d+\s+(?:{_MARK})*\*?)?\s*$")
_PREFIX_FALLBACK = re.compile(rf"^\s*\d+\s+\d+\s+(?:{_MARK})*\*?")
# a mark the layout does not know (``(TT)``) left in front of the code — on either path — tags the line and its function
# is never compared (a listing the parser did not read is not a changed function). Marks are capital letters or a blank
# followed by white space: ``(U8)x``, ``(void)``, ``(*p)`` are code.
_LEFTOVER = re.compile(r"^\s*(?:\((?:[A-Z]{1,2}|\s)\)){1,4}(?=\s|$)")
UNREAD = "/*history_replay:unread-coverage-column*/"
_LITERAL = re.compile(r"\b(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?)[uUlLfF]*\b")
# ``en_s_Buzzer_3_Flashing_Long(5)`` — how a reference writes an enumerator with its value
_NAMED_VALUE = re.compile(r"\s*([A-Za-z_]\w*)\s*\(\s*([-+]?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*)\s*\)\s*")
_NO_VALUE = frozenset({"", "-", "—", "N/A", "n/a", "NA"})   # a cell that states no value (the R3 reader's reading)
_STATUSES = ("replayed", "undecided", "unobserved_difference", "difference_not_compared", "calibration_not_reached",
             "not_comparable", "not_replayable", "signature_changed", "no_suite", "unit_mismatch", "ambiguous_name",
             "ambiguous_listing", "listing_unparsed")


def listing_units(report_html: str) -> dict[str, str]:
    """Unit name → the source text an aggregate coverage report lists for it (its ``<pre class="aggregate-coverage">``
    block, the unit named by the ``Unit`` cell before it)."""
    out: dict[str, str] = {}
    for m in _PRE.finditer(report_html):
        units = _UNIT_CELL.findall(report_html, 0, m.start())
        if not units:
            continue
        lines = []
        for line in m.group(1).split("\n"):
            text = html.unescape(_TAG.sub("", _LINE_NO.sub("", line)))
            if _ENTRY.match(text):
                continue
            head = text[:_PREFIX]
            if _PREFIX_OK.match(head):
                code = text[_PREFIX:]
            else:   # a column wider than the fixed layout
                code = _PREFIX_FALLBACK.sub("", text)
            if _LEFTOVER.match(code):
                code = UNREAD + code
            lines.append(code)
        out.setdefault(units[-1].strip(), "\n".join(lines) + "\n")
    return out


def _tree(text: str):
    from generators import c_project_context as cpc
    raw = text.encode()
    return cpc.shared_parser().parse(raw).root_node, raw


def _function_bodies(text: str) -> dict[str, str]:
    from generators.mcdc_design import _function_name
    root, raw = _tree(text)
    out: dict[str, str] = {}
    stack = [root]
    while stack:
        n = stack.pop()
        if n.type == "function_definition":
            name = _function_name(n, raw)[0]
            if name:
                out.setdefault(name, raw[n.start_byte:n.end_byte].decode())
            continue
        stack.extend(n.named_children)
    return out


def listing_functions(log_dir: Path) -> tuple[dict[tuple[str, str], str], dict[str, Any]]:
    """(unit, function) → body over every aggregate coverage report under ``log_dir``, and what the listing says about
    itself: a unit listed by two reports (an application's and a boot loader's ``EEPROM``, an inline-header report)
    keeps both — a function the two list with different bodies is ambiguous (which one a later run compares is decided
    by nothing but file order); functions whose body still carries a coverage column were not read."""
    found: dict[tuple[str, str], list[str]] = defaultdict(list)
    reports: dict[str, list[str]] = defaultdict(list)
    residue, scanned, without = 0, 0, []
    for f in sorted(log_dir.rglob("*.html")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if "aggregate-coverage" not in text:
            continue
        scanned += 1
        units = listing_units(text)
        if not units:   # e.g. "File Is Not Instrumented For Coverage." — the run kept no code for that unit
            without.append(f.name)
        for unit, source in units.items():
            reports[unit].append(f.name)
            residue += source.count(UNREAD)
            for name, body in _function_bodies(source).items():
                found[(unit, name)].append(body)
    functions = {k: bodies[0] for k, bodies in sorted(found.items())}
    stats = {"reports": scanned, "reports_without_listing": without,
             "units": len(reports), "units_in_several_reports": sorted(u for u, fs in reports.items() if len(fs) > 1),
             "ambiguous_functions": sorted(k for k, bodies in found.items() if len({normalized(b) for b in bodies}) > 1),
             "residue_lines": residue,
             "unparsed_functions": sorted(k for k, bodies in found.items() if any(UNREAD in b for b in bodies))}
    return functions, stats


def normalized(body: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"/\*.*?\*/|//[^\n]*", " ", body, flags=re.S)).strip()


def changed_functions(old: dict, new: dict) -> dict[str, list]:
    """Functions whose body differs between two listings (comments and white space aside), and the ones only one has
    (split by whether the other log lists the unit at all — a unit missing from a run is not code removed)."""
    both = sorted(set(old) & set(new))
    old_units, new_units = {u for u, _n in old}, {u for u, _n in new}
    return {"changed": [k for k in both if normalized(old[k]) != normalized(new[k])],
            "added": sorted(k for k in set(new) - set(old) if k[0] in old_units),
            "removed": sorted(k for k in set(old) - set(new) if k[0] in new_units),
            "units_only_old": sorted(old_units - new_units), "units_only_new": sorted(new_units - old_units)}


def _rows(results: list[dict]) -> list[dict]:
    return [{s: o["value"] for s, o in r["outputs"].items() if "value" in o} for r in results]


def _reasons(results: list[dict], top: int = 3) -> list[list]:
    """The oracle's most frequent reasons for the slots it did not determine."""
    return [[k, v] for k, v in Counter(o["reason"] for r in results for o in r["outputs"].values()
                                       if "value" not in o and o.get("reason")).most_common(top)]


def _int_literal(text: str) -> int | None:
    """A C integer literal's value — hexadecimal, octal (``010`` is 8) or decimal, suffix dropped."""
    m = re.fullmatch(r"(0[xX][0-9a-fA-F]+|0[0-7]*|[1-9]\d*)[uUlL]*", text.strip())
    if m is None:
        return None
    digits = m.group(1)
    if digits[:2].lower() == "0x":
        return int(digits, 16)
    return int(digits, 8) if digits.startswith("0") and len(digits) > 1 else int(digits, 10)


_CAST = re.compile(r"\(\s*[A-Za-z_]\w*\s*\)(?=\s*\()")


def _constant_index(text: str) -> int | None:
    """An index that is a literal, possibly in parentheses and casts — the form a macro expands to (``((U8)(0x00U))``)."""
    stripped = re.sub(r"[()\s]", "", _CAST.sub("", text))
    return _int_literal(stripped) if stripped else None


def _declared_name(decl) -> Any:
    """The identifier a declarator declares, through pointers, arrays, functions and parentheses (``(*cb)(void)``)."""
    while decl is not None and decl.type != "identifier":
        nxt = decl.child_by_field_name("declarator")
        decl = nxt if nxt is not None else next((c for c in decl.named_children if c.type.endswith("declarator")
                                                  or c.type == "identifier"), None)
    return decl


def _body_facts(body: str) -> dict[str, Any]:
    """What a body writes and mentions.

    ``writes`` — the write targets the oracle observes: plain identifiers and constant-index array elements
    (``a[3]``, the index possibly a macro-expanded cast literal), seen through parentheses; ``other_writes`` — every
    other write (a member, a pointer — an output parameter too —, a computed index, a function-level ``static``) as its
    normalized statement text with the body's own names replaced by their declaration order (``$L0``, ``$L1`` — a renamed
    loop index is not a change, review r4 W-B): the oracle does not observe those, so a difference there is reported,
    never compared; ``mentions`` — every identifier (reads, write targets — their starting value — and callees; the
    sampler keeps only typed objects); ``params`` / ``param_types`` — the parameter list with and without the parameter
    names (``U8 *p`` ≡ ``U8* p``). A name the body declares (a local, a parameter — not a block-scope ``extern``, and a
    ``static`` is the unit's state) is not an object of the unit; a plain assignment to one is not a write to the unit's
    state."""
    root, raw = _tree(body)

    def text(n):
        return raw[n.start_byte:n.end_byte].decode()
    fn = next((c for c in root.named_children if c.type == "function_definition"), None)
    d = fn.child_by_field_name("declarator") if fn is not None else None
    while d is not None and d.type != "function_declarator":
        d = d.child_by_field_name("declarator")
    p = d.child_by_field_name("parameters") if d is not None else None
    params, types = [], []
    for pd in (p.named_children if p is not None else []):
        if pd.type != "parameter_declaration":
            continue
        ident = _declared_name(pd.child_by_field_name("declarator"))
        whole = re.sub(r"\s+", " ", re.sub(r"/\*.*?\*/|//[^\n]*", " ", text(pd), flags=re.S)).strip()
        whole = re.sub(r"\s*\*\s*", "*", whole)
        params.append(whole)
        if ident is not None:
            whole = re.sub(rf"\b{re.escape(text(ident))}\b", "_", whole)
        types.append(whole)
    if types in ([], ["void"]):
        params, types = [], []
    nodes = []
    stack = [root]
    while stack:
        n = stack.pop()
        nodes.append(n)
        stack.extend(n.children)
    nodes.sort(key=lambda x: (x.start_byte, -x.end_byte))
    local, static_local, order = set(), set(), []
    for n in nodes:
        if n.type in {"declaration", "parameter_declaration"}:
            storage = {text(c) for c in n.children if c.type == "storage_class_specifier"}
            if "extern" in storage:
                continue
            for decl in n.children_by_field_name("declarator"):
                ident = _declared_name(decl)
                if ident is None:
                    continue
                name = text(ident)
                (static_local if "static" in storage and n.type == "declaration" else local).add(name)
                if name not in order:
                    order.append(name)
    renamed = {name: f"$L{i}" for i, name in enumerate(order)}

    def statement(n):
        out = re.sub(r"\s+", "", text(n))
        return re.sub(r"\b[A-Za-z_]\w*\b", lambda m: renamed.get(m.group(0), m.group(0)), out) if renamed else out
    writes, other, mentions = set(), set(), set()
    local_writes: dict[str, set] = defaultdict(set)
    for n in nodes:
        target = n.child_by_field_name("left") if n.type == "assignment_expression" else \
            n.child_by_field_name("argument") if n.type == "update_expression" else None
        while target is not None and target.type == "parenthesized_expression" and target.named_child_count == 1:
            target = target.named_children[0]
        if target is not None:
            if target.type == "identifier" and text(target) in local:
                # a plain local is not the unit's state — but what it holds may flow into a write kept below
                local_writes[renamed[text(target)]].add(statement(n))
            elif target.type == "identifier" and text(target) not in static_local:
                writes.add(text(target))
            elif target.type == "subscript_expression" and \
                    (arg := target.child_by_field_name("argument")) is not None and arg.type == "identifier" and \
                    text(arg) not in local and text(arg) not in static_local and \
                    (idx := target.child_by_field_name("index")) is not None and \
                    (k := _constant_index(text(idx))) is not None:
                writes.add(f"{text(arg)}[{k}]")
            else:
                other.add(statement(n))
        if n.type == "identifier":
            mentions.add(text(n))
    # (review r5 W1) a kept write that uses a local carries that local's assignments with it, transitively — a byte-order
    # swap computed into ``u16t_ReadData`` and then stored through a member is a difference in the unit's state
    pending, followed = [v for st in other for v in re.findall(r"[$]L[0-9]+", st)], set()
    while pending:
        v = pending.pop()
        if v in followed:
            continue
        followed.add(v)
        for st in local_writes.get(v, ()):
            other.add(st)
            pending.extend(re.findall(r"[$]L[0-9]+", st))
    return {"writes": writes, "other_writes": other, "mentions": mentions - local - static_local, "params": params,
            "param_types": types}


def literal_only(old_body: str, new_body: str) -> bool:
    """Only numbers changed — typically a calibration value that came in through a macro."""
    return normalized(_LITERAL.sub("#", old_body)) == normalized(_LITERAL.sub("#", new_body))


def _changed_literals(old_body: str, new_body: str, limit: int = 8) -> list[int]:
    """Integer literals one body has and the other does not (``100U`` → ``300U``), then those on the lines that changed
    (``> 10U`` → ``>= 10U`` keeps its literal, review r4 I3) — where a change bites."""
    def values(text):
        return [v for t in _LITERAL.findall(text) if (v := _int_literal(t)) is not None]
    old, new = Counter(values(normalized(old_body))), Counter(values(normalized(new_body)))
    unshared = sorted(set((old - new) + (new - old)))
    # lines compared without white space, literals read from the lines as written (``return 10U`` → ``return10U``
    # would hide the literal — review r5 I2)
    old_lines = {re.sub(r"\s+", "", ln): ln for ln in old_body.split("\n")}
    new_lines = {re.sub(r"\s+", "", ln): ln for ln in new_body.split("\n")}
    changed = [old_lines.get(k) or new_lines[k] for k in set(old_lines) ^ set(new_lines)]
    on_changed = sorted({v for ln in changed for v in values(ln)} - set(unshared))
    return (unshared + on_changed)[:limit]


def _literal_vectors(names: list[str], scope: dict, params: dict, values: list[int]) -> list[dict]:
    """Vectors that put every typed input at a changed literal and one either side of it (clamped to its type) — the
    random sample rarely lands between an old and a new constant."""
    from reference_alignment import _object_type

    from generators import c_project_context as cpc
    domains = {}
    for name in names:
        t = _object_type(scope, params, name)
        if isinstance(t, dict) and not cpc.is_float(t) and not t.get("enum"):
            domains[name] = (0, 1) if t.get("kind") == "_Bool" else cpc.type_range(t)
    return [{n: min(max(v + d, lo), hi) for n, (lo, hi) in domains.items()} for v in values for d in (-1, 0, 1)
            if domains]


def replay_function(texts: dict[str, str], context: dict, path: str, name: str, old_body: str, new_body: str,
                    suites: dict[str, list[dict]], sample: int = 24) -> dict[str, Any]:
    """Run the current function, the newer and the older body (each put in place of the current definition) on the
    suites' vectors plus a sample; ``suites`` is {"reference"|"generated": [{"inputs", "expected": {slot: raw}}]}."""
    from mutation_eval import _sample_vectors
    from reference_alignment import _convert_inputs, _param_types, reference_value

    from generators import c_project_context as cpc
    from generators.c_project_context import build_project_context, build_scopes
    from generators.c_source_oracle import Unsupported, _parsed_function, evaluate_outputs

    def run(body: str | None) -> list[dict]:
        if body is None:
            return evaluate_outputs(unit, vectors, [all_slots] * len(vectors))
        text = (raw[:fn.start_byte] + body.encode() + raw[fn.end_byte:]).decode()
        files = dict(texts)
        files[path] = text
        ctx = build_project_context(files, context.get("build"), roots=context.get("roots"))
        for key, value in context.items():   # what the loader added after building (unread files) — same context
            ctx.setdefault(key, value)
        spliced = {"name": name, "source_text": text, "source_path": path, "source_text_complete": True,
                   "project_scope": build_scopes(ctx, [path])[path]}
        return evaluate_outputs(spliced, vectors, [all_slots] * len(vectors))

    try:
        scope = build_scopes(context, [path])[path]
        current = texts[path]
        raw = current.encode()
        _root, fn, _shared = _parsed_function(cpc.shared_parser(), raw, name, scope)
        unit = {"name": name, "source_text": current, "source_path": path, "source_text_complete": True,
                "project_scope": scope}
        params = _param_types(unit)
        constants = scope.get("constants") if scope.get("constants") is not None else {}
        cells: Counter = Counter()
        function_like = set(scope.get("function_like_macros") or ())

        def cell(raw_value, where: str) -> tuple[int | None, str]:
            # the reference's integer, or the ``NAME(5)`` notation a reference writes for an enumerator — the number in
            # parentheses is the value it states (review r3 C1: the shared reader dropped KJPDS02_PV's expected cells in
            # this notation; the oracle already read the input ones, r4 I1). Not a function-like macro call
            # (``MS(100)``); a NAME the unit defines with another value is a conflict; ``-``/``N/A`` state no value
            v = reference_value(raw_value, constants)
            if v is not None:
                return v, "int"
            text_value = str(raw_value if raw_value is not None else "").strip()
            if text_value in _NO_VALUE:
                cells[f"{where}_no_value"] += 1
                return None, "no_value"
            m = _NAMED_VALUE.fullmatch(text_value)
            number = m.group(2) if m is not None else ""
            stated = _int_literal(number.lstrip("+-")) if m is not None and m.group(1) not in function_like else None
            if stated is None:
                cells[f"{where}_unreadable"] += 1
                return None, "unreadable"
            stated = -stated if number.startswith("-") else stated
            known = (constants.get(m.group(1)) or {}).get("value")
            if isinstance(known, int) and known != stated:
                cells[f"{where}_named_conflict"] += 1
                return None, "conflict"
            cells[f"{where}_named"] += 1
            return stated, "named"
        cases: dict[str, list[dict]] = {}
        for label in ("reference", "generated"):
            cases[label] = []
            for case in suites.get(label) or []:
                named_inputs = {}
                for k, raw_value in (case["inputs"] or {}).items():
                    if _NAMED_VALUE.fullmatch(str(raw_value or "").strip()):
                        v, _kind = cell(raw_value, f"{label}_inputs")
                        if v is not None:
                            named_inputs[k] = v
                inputs, _conversions = _convert_inputs(scope, params, {**case["inputs"], **named_inputs})
                expected, unreadable = {}, set()
                for s, raw_value in case["expected"].items():
                    v, kind = cell(raw_value, f"{label}_expected")
                    if v is not None:
                        expected[s] = v
                    elif kind != "no_value":
                        unreadable.add(s)
                cases[label].append({"inputs": inputs, "expected": expected, "unreadable": unreadable})
        slots = sorted({s for group in cases.values() for c in group for s in c["expected"]})
        new_facts, old_facts = _body_facts(new_body), _body_facts(old_body)
        if new_facts["params"] != old_facts["params"]:
            # the suites' inputs name the newer parameters: the older body cannot be run on them as it was called
            # (``rename`` — the same types, other names: its inputs would bind to nothing)
            return {"status": "signature_changed",
                    "signature_change": "rename" if new_facts["param_types"] == old_facts["param_types"] else "types",
                    "params": {"new": new_facts["params"], "old": old_facts["params"]}}
        # objects either body writes are compared too: a change on an output no suite states is still a change
        all_slots = slots + sorted((new_facts["writes"] | old_facts["writes"]) - set(slots))
        # and every object either body mentions is sampled — the older code may read what no current input names, and a
        # written object's starting value is an input as well
        names = sorted({k for group in cases.values() for c in group for k in c["inputs"]} | set(params)
                       | new_facts["mentions"] | old_facts["mentions"])
        suite_vectors = [c["inputs"] for group in cases.values() for c in group]
        literals = _changed_literals(old_body, new_body)
        vectors = suite_vectors + _sample_vectors(names, scope, params, sample, f"{path}:{name}") + \
            _literal_vectors(names, scope, params, literals)
        now_results, new_results, old_results = run(None), run(new_body), run(old_body)
    except Unsupported as exc:
        return {"status": "not_replayable", "reason": f"unsupported:{exc}"[:300]}
    except (ValueError, KeyError, TypeError, RecursionError) as exc:   # recorded per function; the run goes on
        return {"status": "not_replayable", "reason": f"harness_error:{type(exc).__name__}: {exc}"[:300]}
    now, new, old = _rows(now_results), _rows(new_results), _rows(old_results)
    stated = set(slots)

    def compare(a_rows, b_rows, keys=None):
        common = [(a[k], b[k]) for a, b in zip(a_rows, b_rows, strict=True) for k in set(a) & set(b)
                  if keys is None or k in keys]
        return len(common), sum(x != y for x, y in common)
    cur_n, cur_diff = compare(now, new)
    pair_n, pair_diff = compare(new, old)
    _suite_n, suite_diff = compare(new, old, stated)
    # where the pair separates: (vector, slot) with both values determined and different
    separating = [(i, k) for i, (a, b) in enumerate(zip(new, old, strict=True)) for k in sorted(set(a) & set(b))
                  if a[k] != b[k]]
    n_suite = len(suite_vectors)
    compared_keys = {k for a, b in zip(new, old, strict=True) for k in set(a) & set(b)}
    record: dict[str, Any] = {
        "vectors": len(vectors), "literal_vectors": len(vectors) - n_suite - sample if literals else 0,
        "slots": {"stated": len(slots), "written_only": len(all_slots) - len(slots)},
        # per suite and role: named (``NAME(5)``) · named_conflict · no_value (``-``) · unreadable
        "suite_cells": dict(sorted(cells.items())),
        "determined": {"current": sum(map(len, now)), "new": sum(map(len, new)), "old": sum(map(len, old))},
        "compared_slots": pair_n,
        "compared_share": round(pair_n / (len(vectors) * len(all_slots)), 4) if all_slots and vectors else 0,
        "current_equals_new": None if cur_n == 0 else cur_diff == 0, "current_new_compared_slots": cur_n,
        "current_only_determined": sum(len(set(a) - set(b)) for a, b in zip(now, new, strict=True)),
        "distinguished": pair_diff > 0, "distinguished_only_on_unstated": pair_diff > 0 and suite_diff == 0,
        "separated_on_suite_inputs": any(i < n_suite for i, _k in separating),
        "unobserved_write_difference": new_facts["other_writes"] != old_facts["other_writes"]}
    if separating:
        i, k = min(separating, key=lambda x: (x[0] >= n_suite, x))   # a suite's own vector first
        where = ("reference", i) if i < len(cases["reference"]) else ("generated", i - len(cases["reference"])) \
            if i < n_suite else ("sample", i - n_suite)
        record["distinguishing_example"] = {"vector": f"{where[0]}#{where[1] + 1}", "slot": k, "new": new[i][k],
                                            "old": old[i][k], "inputs": dict(list(vectors[i].items())[:12]),
                                            "inputs_total": len(vectors[i])}
    if not any(new) and not any(old):
        # nothing either listed body computes is determined — whether or not the current one is (review r2 M28)
        record.update(status="not_replayable",
                      reason="no_body_determines_output" if not any(now) else "neither_body_determines_output",
                      oracle_reasons=_reasons(new_results))
        return record
    # a body that determines nothing cannot be compared — that is "not replayable", not "equivalent" (undecided)
    for label, rows, results in (("new", new, new_results), ("old", old, old_results)):
        if not any(rows):
            record.update(status="not_replayable", reason=f"{label}_body_determines_no_output",
                          oracle_reasons=_reasons(results))
            return record
    offset = 0
    for label in ("reference", "generated"):
        group = cases[label]
        passing, fails, unknown = 0, [], set()
        for i, c in enumerate(group):
            after, before = new[offset + i], old[offset + i]
            for s, e in c["expected"].items():
                if after.get(s) == e:                      # passes after the change
                    passing += 1
                    if s not in before:
                        unknown.add((i, s))                # (r2 C, r3 W1 A) the older value is unknown at its input
                    elif before[s] != e:
                        fails.append((i, s))               # FAIL before, PASS after
                elif s not in after and (s not in before or before[s] != e):
                    unknown.add((i, s))                    # (r3 W1 B, r4 W-A) after is unknown: before fails or is
                                                           # unknown too — whether this case fails is not decidable
            # (r3 C1, r4 W-C) a value it states that could not be read, where this case's own vector does not show
            # the two bodies equal on that slot
            unknown |= {(i, s) for s in c["unreadable"] if not (s in after and s in before and after[s] == before[s])}
        verdict = "detected" if fails else "undetermined" if unknown else "missed"
        record[label] = {"cases": len(group), "slots_passing_after": passing, "slots_failing_before": len(fails),
                         "detects": bool(fails), "verdict": verdict, "slots_unknown": len(unknown),
                         "examples": [{"case": i + 1, "slot": s, "expected": group[i]["expected"][s],
                                       "before": old[offset + i][s]} for i, s in fails[:3]]}
        offset += len(group)
    only_one_writes = (new_facts["writes"] ^ old_facts["writes"]) - compared_keys
    if pair_n == 0:
        record["status"] = "not_comparable"
    elif record["distinguished"]:
        record["status"] = "replayed"
    elif record["unobserved_write_difference"]:
        record["status"] = "unobserved_difference"   # the bodies write members/pointers differently: not "equivalent"
    elif only_one_writes:
        # (r3 W5) one body writes an object the other does not, and that object was never compared (both undetermined)
        record["status"] = "difference_not_compared"
        record["never_compared_writes"] = sorted(only_one_writes)
    elif literal_only(old_body, new_body):
        # (r3 W3) a calibration change no vector reached — a float or a computed threshold the literal vectors miss
        record["status"] = "calibration_not_reached"
    else:
        record["status"] = "undecided"
    if record["status"] != "replayed":
        for label in ("reference", "generated"):
            record[label]["verdict"] = None   # (r3 W2) a pair nothing separates has no detection verdict
    return record


def evaluate(reference: str, generated: str, roots: list[Path], alignment: dict, old_log: Path, new_log: Path,
             evidence: dict | None = None, sample: int = 24, derived_only: bool = True) -> dict[str, Any]:
    """``derived_only``: the generated suite states only the slots its Test Evidence marks ``derived`` (as in R4)."""
    from mutation_eval import _suite_from_workbook
    from reference_alignment import _load_source

    (old, old_stats), (new, new_stats) = listing_functions(old_log), listing_functions(new_log)
    diff = changed_functions(old, new)
    ref_suite, ref_dup = _suite_from_workbook(reference, generated=False)
    gen_suite, gen_dup = _suite_from_workbook(generated, generated=derived_only)
    texts, context, _unread = _load_source(roots)
    duplicates = set(alignment.get("summary", {}).get("duplicate_reference_names") or []) | set(ref_dup) | set(gen_dup)
    where = {f["function"]: f.get("source_path") for f in alignment["functions"] if f["status"] == "aligned"}
    documented = (evidence or {}).get("functions") or {}
    listed_names = Counter(name for _unit, name in set(old) | set(new))
    ambiguous = set(map(tuple, old_stats["ambiguous_functions"])) | set(map(tuple, new_stats["ambiguous_functions"]))
    unparsed = set(map(tuple, old_stats["unparsed_functions"])) | set(map(tuple, new_stats["unparsed_functions"]))
    records = []
    totals = Counter({k: 0 for k in _STATUSES + ("detected_by_reference", "detected_by_generated", "only_reference",
                                                  "only_generated", "undetermined_reference", "undetermined_generated",
                                                  "missed_by_both", "separated_on_suite_inputs",
                                                  "distinguished_only_on_unstated", "current_differs_from_new",
                                                  "literal_only")})
    reasons = Counter()
    for unit, name in diff["changed"]:
        rec: dict[str, Any] = {"unit": unit, "function": name}
        if documented.get(name):
            rec["documented_fix"] = documented[name]
        if literal_only(old[(unit, name)], new[(unit, name)]):
            rec["literal_only"] = True
            totals["literal_only"] += 1
        path = where.get(name)
        if (unit, name) in unparsed:
            rec["status"] = "listing_unparsed"    # a coverage column is left in the body: never compare it
        elif (unit, name) in ambiguous:
            rec["status"] = "ambiguous_listing"   # two reports of one run list the unit with different bodies
        elif listed_names[name] > 1 or name in duplicates:
            rec["status"] = "ambiguous_name"      # two units define it: which body is which is not decidable by name
        elif not path or name not in ref_suite or name not in gen_suite:
            rec["status"] = "no_suite"            # not aligned with the reference, or one suite has no unit for it
        elif Path(path).stem.lower() != unit.lower():
            rec["status"] = "unit_mismatch"       # the listing's unit is not the file the function lives in now
            rec["source_path"] = path
        else:
            rec["source_path"] = path
            suites = {"reference": ref_suite[name], "generated": gen_suite[name]}
            rec.update(replay_function(texts, context, path, name, old[(unit, name)], new[(unit, name)], suites, sample))
        totals[rec["status"]] += 1
        for key, value in (rec.get("suite_cells") or {}).items():
            totals[f"suite_cells_{key}"] += value
        if rec["status"] == "not_replayable":
            reasons[(rec.get("reason") or "").split(":")[0]] += 1
        if rec["status"] == "replayed":
            ref, gen = rec["reference"]["verdict"], rec["generated"]["verdict"]
            totals["detected_by_reference"] += ref == "detected"
            totals["detected_by_generated"] += gen == "detected"
            totals["only_reference"] += ref == "detected" and gen != "detected"
            totals["only_generated"] += gen == "detected" and ref != "detected"
            totals["undetermined_reference"] += ref == "undetermined"
            totals["undetermined_generated"] += gen == "undetermined"
            # a miss only where both suites' own inputs decide it (review r2 C): not where a value is unknown
            totals["missed_by_both"] += ref == "missed" and gen == "missed"
            totals["separated_on_suite_inputs"] += rec["separated_on_suite_inputs"]
            totals["distinguished_only_on_unstated"] += rec["distinguished_only_on_unstated"]
            totals["current_differs_from_new"] += rec["current_equals_new"] is False
        records.append(rec)

    def subset(rows: list[dict]) -> dict[str, Any]:
        done = [r for r in rows if r["status"] == "replayed"]
        return {"changes": len(rows), "replayed": len(done), **{f"detected_by_{k}": sum(r[k]["detects"] for r in done)
                                                                for k in ("reference", "generated")},
                "statuses": dict(Counter(r["status"] for r in rows))}
    unmatched = sorted(set(documented) - {r["function"] for r in records})
    return {"kind": "historical change replay (unit level, source oracle); detections are source-consistency — not "
                    "requirement conformance, not a target run",
            "old_log": str(old_log), "new_log": str(new_log), "reference": reference, "generated": generated,
            "source_roots": [str(r) for r in roots], "execution_status": "not_run",
            "listing": {"old_functions": len(old), "new_functions": len(new), "changed": len(diff["changed"]),
                        "added": len(diff["added"]), "removed": len(diff["removed"]),
                        "units_only_old": diff["units_only_old"], "units_only_new": diff["units_only_new"],
                        "old": old_stats, "new": new_stats},
            "summary": {**dict(totals), "changes": len(records), "not_replayable_reasons": dict(reasons)},
            "documented_fixes": {**subset([r for r in records if r.get("documented_fix")]),
                                 "evidence_functions_not_changed_here": unmatched},
            "functions": records}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--old-log", required=True, help="folder of the older run's aggregate coverage reports")
    ap.add_argument("--new-log", required=True, help="folder of the newer run's aggregate coverage reports")
    ap.add_argument("--reference", required=True)
    ap.add_argument("--generated", required=True)
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--alignment", required=True, help="R3 alignment JSON: only its aligned functions are replayed")
    ap.add_argument("--evidence", default="", help="JSON {functions: {name: [{document, id, quote}]}}")
    ap.add_argument("--sample", type=int, default=24)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    roots = [Path(r.strip()) for r in re.split(r"[,;]", args.source_root) if r.strip()]
    from reference_alignment import _guard_output
    for log in (args.old_log, args.new_log):
        if Path(args.out).resolve().is_relative_to(Path(log).resolve()):
            raise SystemExit(f"refusing to write {args.out}: inside the log folder {log}")
    _guard_output(Path(args.out), args.reference, roots, inputs=(args.generated, args.alignment, args.evidence))
    alignment = json.loads(Path(args.alignment).read_text(encoding="utf-8"))
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8")) if args.evidence else None
    report = evaluate(args.reference, args.generated, roots, alignment, Path(args.old_log), Path(args.new_log),
                      evidence, sample=args.sample)
    out = Path(args.out)
    tmp = out.with_name(f"{out.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        os.replace(tmp, out)   # a reader never sees a half-written report
    finally:
        tmp.unlink(missing_ok=True)
    print(json.dumps({"listing": {k: v for k, v in report["listing"].items() if k not in ("old", "new")},
                      "summary": report["summary"], "documented_fixes": report["documented_fixes"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
