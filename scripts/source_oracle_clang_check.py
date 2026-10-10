"""Independent check of source-oracle expected values with a real C front end (clang, 16-bit-int target).

`generators/c_source_oracle.py` interprets function text in Python. This script asks clang instead: every
checked function body is compiled **verbatim** inside a C++20 ``constexpr`` harness for ``--target=msp430``
(char 8 · short 16 · int 16 · long 32 — the widths HDPDM01's typedefs testify), and each claimed output value
becomes a ``static_assert``. Constant evaluation runs the body with the target's integer semantics and
rejects undefined behaviour (signed overflow, division by zero, out-of-bounds indexing) as a hard error.

Independence and its limits:

* the body, macro texts (object- and function-like) and typedef base types are the source's own; what the
  harness adds is only the *inputs*: sequence values, and for everything the claim says it does not depend
  on — globals the sequence leaves unset, callee return values — three different fill values. A claim holds
  only if all three runs give the claimed value, so an output that secretly depends on an unset global or a
  call result is caught;
* callees are stubs that return the fill value; one the project write closure says may write through a pointer
  (``pointer_write``, or unknown code) writes the fill value through each non-const scalar pointer argument (R36 — the
  oracle holds such a pointee as any value; before, the constexpr run stopped at the uninitialized local — and a
  missing havoc of a scalar pointee was agreed with). (R64) Where the project points-to analysis names the callee's
  targets, only the arguments of the parameters it writes through directly (``pointer_targets.params``) get the fill:
  the oracle havocs what those point to and keeps an object the callee cannot reach — the analysis itself is not
  checked here (an object it wrongly leaves out keeps the same value in both). Only ``*p`` is written: the other elements of an array, a
  struct's members and an enum pointee are not, so a missing havoc there is still not caught. The rest write nothing:
  the oracle's claim that a callee cannot change an output (project write closure) is **not** checked here;
* enumerator, ``const`` object and ``const`` array element values are the engine's (as in
  ``mcdc_design_clang_oracle.py``);
* every macro is defined at the top of the harness: where a macro is defined relative to the function is not
  checked (the oracle refuses a macro the unit defines after the function);
* which macros are active and with which bodies (include resolution, ``#if`` verdicts, toolchain-header and
  typedef-width assumptions) is the engine's project context — the harness reuses it, so a wrong preprocessing
  verdict would be agreed with;
* clang evaluates operands left to right, as the oracle does: order-of-evaluation claims are not checked here — the
  oracle refuses order-dependent expressions instead (``check_sequencing``);
* C and C++ agree on integer promotions and conversions for these programs; where they differ (C++20 defines
  signed narrowing and ``<<`` of negatives) the oracle claims nothing, so no claim rests on the difference;
* a unit the harness cannot compile (register structs, ``static`` locals — not allowed in C++20 constexpr,
  vendor syntax) is counted **unchecked**, never agreed;
* (R41) three spellings are the harness's, not the source's: ``enum TAG`` without a typedef is a typedef of the
  underlying type (varied like any enum); a ``<stdint.h>`` name the scope leaves unresolved (the project typedefs it
  under ``#ifndef uint16_t``) is the standard type the target's widths fix — only where every permitted underlying
  type gives the same values (`_stdint_spelling`), else the unit stays unchecked (a width ``static_assert`` that fails
  makes the unit ``unchecked:stdint_width_disagrees_with_target``, never a contradiction); an output global the body
  never names is declared with the claim's input value (else the fill) so the unit compiles and its other outputs are
  checked — that output itself is ``unchecked:output_not_named_by_body`` (clang would only hand back the harness's own
  value; a mismatch there stays a mismatch) and listed in ``outputs_not_named_by_body`` for review;
* stand-ins (R63, R64): a register object the scope does not model is a struct of the member paths the code names, and
  a struct object's member the oracle does not model (a pointer member read as ``q.tl_pdu[h][3]``) is an object that
  gives the fill value however it is indexed (`_member_stand_ins`) — the oracle reads both as unknown, so no claim
  may rest on them, and the fill varies by run so a claim that does is caught;
* the fill values are a sample (0/90/201), not a proof of independence from unset state;
* C++ sequences some things C leaves unsequenced (``=`` operands since C++17, list-initialization items): the
  oracle refuses those in C, so no claim rests on the difference — but clang cannot catch that refusal missing;
* every compilation carries a canary assertion that must fail: a run that does not report it (a missing target,
  a driver error, a crash) is a failure, never a silent pass.

Usage:
    .venv/Scripts/python.exe scripts/source_oracle_clang_check.py --xlsm OUT.xlsm --source-root ROOT [--out r.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_FILLS = (0, 90, 201)
# How the fills of one claim combine. Checking a claim, a contradiction wins over a harness limit. Probing for undefined
#   behaviour (R10), an evaluation error anywhere is the answer, and a fill clang could not evaluate at all outranks a
#   placeholder mismatch — "not reproduced" needs every fill evaluated to a value (review R10 round 2 W3).
_CHECK_RANK = {"agree": 0, "constexpr_limit": 1, "eval_error": 2, "mismatch": 3}
_PROBE_RANK = {"agree": 0, "mismatch": 1, "constexpr_limit": 2, "eval_error": 4}
_REAL_EVAL_ERROR = re.compile(r"outside the range of representable|division by zero|cannot refer to element|past-the-end"
                              r"|shift|uninitialized|outside its lifetime|signed integer overflow")
_IDENT = re.compile(r"\b[A-Za-z_]\w*\b")
# Which clang diagnostics a disclosed possible-UB kind explains (review round 7 W1): an evaluation error is set aside
# as "disclosed" only when what the oracle disclosed can be the cause — any other error stays a contradiction.
# Shift UB by clang's note forms — the bare word would match a callee named ``do_shift`` (review round 8 W1).
_SHIFT_NOTE = r"shift count \S+ >= width|negative shift count|left shift of negative|signed left shift discards"
_OVERFLOW_MESSAGE = re.compile(r"outside the range of representable|signed integer overflow|" + _SHIFT_NOTE)
_INDEX_MESSAGE = re.compile(r"cannot refer to element|past-the-end")
_DISCLOSED_MESSAGE = {
    "signed_overflow_unknown_operand": _OVERFLOW_MESSAGE,
    "signed_overflow_untyped_operand": _OVERFLOW_MESSAGE,
    "division_by_unknown": re.compile(r"division by zero|outside the range of representable"),
    "shift_by_unknown": re.compile(_SHIFT_NOTE),
    "index_unknown": _INDEX_MESSAGE,
    "pointer_arithmetic_untyped": _INDEX_MESSAGE,
    "operand_under_unknown_condition": re.compile(r"outside the range of representable|division by zero"
                                                  r"|cannot refer to element|past-the-end|signed integer overflow|"
                                                  + _SHIFT_NOTE),
}


def _disclosure_explains(possible_ub, message) -> bool:
    """True when one of the disclosed possible-UB kinds can produce this clang evaluation error."""
    return any(kind in _DISCLOSED_MESSAGE and _DISCLOSED_MESSAGE[kind].search(message or "")
               for kind in possible_ub or ())


_KEYWORDS = frozenset("""auto break case char const continue default do double else enum extern float for goto if int long
register return short signed sizeof static struct switch typedef union unsigned void volatile while""".split())
# Type names a C project may typedef that C++ reserves (KJPDS02 PE_Types.h: ``typedef unsigned char bool;``): the harness
# names them ``__oracle_td_<name>`` in the function's text — C++ cannot redeclare them (R16b review R3 W3-3)
CXX_KEYWORD_TYPEDEFS = frozenset({"bool", "wchar_t", "char8_t", "char16_t", "char32_t"})


def kw_typedef_renamed(text: str, names) -> str:
    """``text`` with each of ``names`` (C++ keyword typedef names) spelled ``__oracle_td_<name>``."""
    if not names:
        return text
    pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(names)) + r")\b")
    return pattern.sub(lambda m: "__oracle_td_" + m.group(1), text)


def _text(node, raw):
    return raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


_ENUM_BASES = ("int", "unsigned int", "unsigned char", "signed char")


def _base_type(t, enum_base="int"):
    if t.get("kind") == "_Bool":
        return "bool"
    if t.get("enum"):
        # The oracle claims a value only if every permitted underlying type agrees: each one is checked in turn.
        return enum_base
    if t.get("kind") in {"float", "double"}:
        return t["kind"]
    return ("unsigned " if not t["signed"] else "signed ") + t["kind"]


def _input_int(value, constants, function_like=()):
    """A sequence input as the oracle reads it (``"0x0"``, ``"5U"``, an enumerator name, ``ERROR_OK (0)``) — else None
    (round 2 I). (R26) The oracle's own reader, so a ``NAME(5)`` whose name the unit defines otherwise or a macro call
    (``MS(100)``) is unread here exactly as the oracle leaves it unknown; a non-string input is an ``int`` or nothing
    (`_Interp.check_input`)."""
    from generators.c_source_oracle import read_reference_cell
    if isinstance(value, str):
        return read_reference_cell(value, constants, function_like)[0]
    return value if type(value) is int else None


def _struct_text(root, members, globals_, arrays, enum_base="int", extra=None):
    """(R39) ``struct { U8 a; U16 b[4]; struct { U8 x; } s; }`` from the members of a flattened struct object. (R64)
    ``extra``: member name → declaration of a stand-in for a member the oracle does not model (`_member_stand_ins`)."""
    tree: dict = {}
    for path in members:
        node = tree
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = path

    def render(node):
        out = []
        for name, sub in node.items():
            if isinstance(sub, dict):
                out.append(f"struct {{ {render(sub)} }} {name};")
                continue
            full = f"{root}.{sub}"
            if full in globals_:
                out.append(f"{_base_type(globals_[full]['type'], enum_base)} {name};")
            else:
                a = arrays[full]
                out.append(f"{_base_type(a['type'], enum_base)} {name}[{a['length']}];")
        return " ".join(out)

    return f"struct {{ {render(tree)} {' '.join((extra or {}).values())} }}"


# (R64) a stand-in for a member read through ``k`` subscripts: indexing it ``k`` times gives the fill value, any index
_STAND_IN_TEMPLATE = ("template<int __D> struct __oracle_pm { int __f; constexpr auto operator[](long long) const "
                      "{ if constexpr (__D > 1) return __oracle_pm<__D - 1>{__f}; else return (unsigned char)__f; } "
                      "constexpr auto operator*() const { return (*this)[0]; } };")


def _member_stand_ins(root, unmodeled, text):
    """(R64) Stand-ins for the unmodeled members of struct object ``root`` the code reads (``lin_tl_rx_queue.tl_pdu[h][3]``
    — a pointer member the oracle reads as unknown): name → (declaration, depth). A member used without a subscript is
    a wide unsigned scalar; one used with ``k`` subscripts an object that gives the fill value when indexed ``k`` times
    (`_STAND_IN_TEMPLATE` — any index). The oracle claims nothing that rests on what such a member holds — the fill
    varies by run, so a claim that does is caught. A use the stand-in cannot take (the member assigned to a typed
    pointer, written through) does not compile and the unit stays unchecked; no stand-in when a member is used with
    different depths."""
    out = {}
    for m in unmodeled:
        if "." in m:
            continue
        depths = set()
        for hit in re.finditer(rf"\b{re.escape(root)}\s*\.\s*{re.escape(m)}\b", text):
            i, depth = hit.end(), 0
            while True:
                j = i
                while j < len(text) and text[j].isspace():
                    j += 1
                if j >= len(text) or text[j] != "[":
                    break
                k, level = j + 1, 1
                while k < len(text) and level:
                    level += {"[": 1, "]": -1}.get(text[k], 0)
                    k += 1
                depth, i = depth + 1, k
            depths.add(depth)
        if len(depths) != 1:
            continue
        depth = depths.pop()
        if depth > 3:
            continue
        out[m] = (f"unsigned long long {m};", 0) if depth == 0 else (f"__oracle_pm<{depth}> {m};", depth)
    return out


def _register_struct_text(paths):
    """(R63) A stand-in for an object the scope declares but does not model — a volatile register union of the target's
    header (``REG_PTP.Bits.PTP3`` through ``#define PTP_PTP3 REG_PTP.Bits.PTP3``, readable since R63): a plain struct of
    just the member paths the code names, wide unsigned leaves. The oracle reads such an object as unknown, so no claim
    rests on its value; the stand-in lets the rest of the function compile and be checked. What it does not reproduce —
    union aliasing (``Byte`` / ``Bits``), the placement address — no claim depends on. None when a path is used both as a
    member and as a whole."""
    tree: dict = {}
    for path in paths:
        node = tree
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                return None
        if isinstance(node.get(parts[-1]), dict):
            return None
        node.setdefault(parts[-1], "leaf")

    def render(node):
        return " ".join(f"struct {{ {render(sub)} }} {name};" if isinstance(sub, dict) else f"unsigned long long {name};"
                        for name, sub in node.items())
    return f"struct {{ {render(tree)} }}"


_COMMENT_OR_LITERAL = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', re.S)


def _code_text(text):
    """``text`` with comments and string / character literals blanked (R41 review I-R2-1)."""
    return _COMMENT_OR_LITERAL.sub(" ", text)


def _untagged(text, enum_tags):
    """``enum TAG`` (not a definition ``enum TAG {``) → the harness typedef ``__oracle_enum_TAG``: C++ sees an undefined
    ``enum TAG`` as a forward reference it forbids. The typedef is the underlying type the enum-base loop varies."""
    if not enum_tags:
        return text
    pattern = re.compile(r"\benum\s+(" + "|".join(re.escape(t) for t in sorted(enum_tags, key=len, reverse=True))
                         + r")\b(?!\s*\{)")
    return pattern.sub(lambda m: "__oracle_enum_" + m.group(1), text)


_STDINT_NAMES = {"int8_t": (8, True), "uint8_t": (8, False), "int16_t": (16, True), "uint16_t": (16, False),
                 "int32_t": (32, True), "uint32_t": (32, False), "int64_t": (64, True), "uint64_t": (64, False)}
_WIDTH_TAG = "__oracle_stdint_width_"
# (R41 review W1) an output the body never names: what clang returns for it is the value the harness put there
UNNAMED_OUTPUT = "output_not_named_by_body"


def _stdint_spelling(name, widths):
    """(R41) The C++ type for a ``<stdint.h>`` name the unit leaves unresolved (the project's typedef sits under
    ``#ifndef uint16_t`` — a reserved name the model does not decide), or None. Only a type the target's widths fix:
    exactly one standard type of that width, or ``short`` and ``int`` of one width — they promote alike (C11 6.3.1.1p2),
    so every permitted underlying type gives the same values. Two candidates of other ranks (``int``/``long`` of one
    width) give conversions of different types — the values agree, but the rule stays with a type the widths fix: None
    (the unit stays unchecked; conservative)."""
    bits, signed = _STDINT_NAMES[name]
    kinds = [k for k in ("char", "short", "int", "long", "long long") if widths.get(k) == bits]
    if not kinds or (len(kinds) > 1 and set(kinds) != {"short", "int"}):
        return None
    return ("signed " if signed else "unsigned ") + ("int" if len(kinds) > 1 else kinds[0])


def _fits(value, t):
    from generators import c_project_context as cpc
    if not isinstance(value, int) or not isinstance(t, dict) or cpc.is_float(t):
        return False
    lo, hi = (0, 1) if t["kind"] == "_Bool" else cpc.type_range(t)
    if t.get("enum"):
        lo, hi = 0, 127
    return lo <= value <= hi


def _fill_for(t, fill):
    from generators import c_project_context as cpc
    if t.get("kind") == "_Bool":
        return fill & 1
    lo, hi = cpc.type_range(t)
    return max(lo, min(hi, fill))


_MAX_EVALUATIONS = 256


def _instrumented_body(fn, raw, instrument):
    """(R2c) The body text with every instrumented decision wrapped: ``(begin(d), end(d, (<decision>)))`` and each of its
    conditions ``atom(d, i, (<condition>))`` — clang then records, per evaluation of the decision, which conditions the
    short circuit evaluated with which value, and the outcome. Nested or overlapping spans: ``None`` (unchecked)."""
    body = fn.child_by_field_name("body")
    edits = []
    for d, decision in enumerate(instrument["decisions"]):
        s, e = decision["span"]
        edits.append((s, e, f"((__oracle_begin({d}), __oracle_end({d}, (", "))))"))
        for i, (a0, a1) in enumerate(decision["atoms"]):
            edits.append((a0, a1, f"__oracle_atom({d}, {i}, (", "))"))
    edits.sort(key=lambda x: (x[0], -x[1]))
    for (s1, e1, *_), (s2, e2, *_) in zip(edits, edits[1:], strict=False):
        if s2 < e1 and e2 > e1:
            return None  # overlapping, not nested
    spans = [(s, e) for s, e, *_ in edits]
    for i, (s1, e1) in enumerate(spans):
        # a decision may contain only its own conditions; decisions inside another decision are not instrumented
        inside = [j for j, (s2, e2) in enumerate(spans) if j != i and s1 <= s2 and e2 <= e1 and (s2, e2) != (s1, e1)]
        if any(edits[j][2].startswith("((__oracle_begin") for j in inside):
            return None
    if any(not (body.start_byte <= s and e <= body.end_byte) for s, e in spans):
        return None

    def render(lo, hi, items):
        out, pos, k = [], lo, 0
        while k < len(items):
            s, e, pre, post = items[k]
            inner = []
            k += 1
            while k < len(items) and items[k][0] < e:
                inner.append(items[k])
                k += 1
            out.append(raw[pos:s])
            out.append(pre.encode() + render(s, e, inner) + post.encode())
            pos = e
        out.append(raw[pos:hi])
        return b"".join(out)
    text = render(body.start_byte, body.end_byte, edits).decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _harness(unit, claims, fn, raw, enum_base="int", instrument=None):
    """C++ text for one function and its claims: (source, {line: (claim index, output, value, variant)}, reason, meta).

    ``meta``: ``callees`` (stubbed calls — callee effects are not checked), ``enum`` (an enumeration type is used).
    ``instrument`` (R2c): ``{"decisions": [{"span": (start, end), "atoms": [(start, end), ...]}]}`` — decisions whose
    evaluations the claims' outputs name through `decision_claim` expressions."""
    from generators import c_project_context as cpc
    from generators.mcdc_design import _function_name
    scope = unit["project_scope"]
    _, fdecl = _function_name(fn, raw)
    if fdecl is None or fdecl.parent is None or fdecl.parent.type != "function_definition":
        return None, {}, "function_declarator_not_direct", {}
    # CRLF sources: a ``\r`` left in the text makes clang count an extra line (R2b review W7).
    body = _text(fn.child_by_field_name("body"), raw).replace("\r\n", "\n").replace("\r", "\n")
    if instrument:
        body = _instrumented_body(fn, raw, instrument)
        if body is None:
            return None, {}, "decision_instrumentation_overlap", {}
    rtype = " ".join([_text(c, raw) for c in fn.named_children if c.type == "type_qualifier"] +
                     [_text(fn.child_by_field_name("type"), raw)])
    params = []
    for p in fdecl.child_by_field_name("parameters").named_children:
        if p.type != "parameter_declaration":
            continue
        d = p.child_by_field_name("declarator")
        if d is None:
            continue
        name = cpc._declared_name(d, raw)
        params.append((name, _text(p, raw), d.type == "identifier", _text(p.child_by_field_name("type"), raw)))
    macro_bodies = scope.get("macro_bodies") or {}
    fbodies = scope.get("function_like_macro_bodies") or {}
    fparams = scope.get("function_like_macro_params") or {}
    constants = scope["constants"]
    globals_, arrays, types = scope.get("globals") or {}, scope.get("arrays") or {}, scope.get("types") or {}
    # every identifier the body can reach through macro expansion
    def expand(seed):
        found, pending = set(), list(seed)
        while pending:
            tok = pending.pop()
            if tok in found:
                continue
            found.add(tok)
            if tok in macro_bodies:
                pending.extend(_IDENT.findall(macro_bodies[tok]))
            if tok in fbodies:
                pending.extend(_IDENT.findall(fbodies[tok]))
        return found

    head = _IDENT.findall(rtype) + [x for p in params for x in _IDENT.findall(p[1])]
    tokens = expand(_IDENT.findall(body) + head)
    # (R41 review I-R2-1) what the code names — comments and literals stripped: a write left in a comment is no write
    code_tokens = expand(_IDENT.findall(_code_text(body)) + head)
    status = scope.get("macro_status") or {}
    macros = [t for t in sorted(tokens) if status.get(t) == "active" and (t in macro_bodies or t in fbodies)]
    if any(status.get(t) not in (None, "active") for t in tokens):
        return None, {}, "macro_not_active_in_unit", {}
    kw = sorted(t for t in tokens if t in CXX_KEYWORD_TYPEDEFS and isinstance(types.get(t), dict) and t not in status)
    if kw:
        body, rtype = kw_typedef_renamed(body, kw), kw_typedef_renamed(rtype, kw)
        params = [(n, kw_typedef_renamed(decl, kw), scalar, typ) for n, decl, scalar, typ in params]
    # (R41) ``enum TAG`` written without a typedef (``enum en_g_DoorState x`` — a parameter, a local, a cast): named by a
    #   typedef of the underlying type as in `integration_oracle_clang_check`. A parameter's ``typ`` keeps the C spelling
    #   (the scope resolves it); only the C++ text is renamed.
    enum_tags = {k.split(None, 1)[1]: v for k, v in types.items()
                 if isinstance(k, str) and k.startswith("enum ") and isinstance(v, dict) and k.split(None, 1)[1] in tokens}
    if enum_tags:
        body, rtype = _untagged(body, enum_tags), _untagged(rtype, enum_tags)
        params = [(n, _untagged(decl, enum_tags), scalar, typ) for n, decl, scalar, typ in params]
    lines = ["// generated by scripts/source_oracle_clang_check.py — do not edit"]
    for name in sorted(tokens):
        t = types.get(name)
        if isinstance(t, dict) and name not in status:
            lines.append(f"typedef {_base_type(t, enum_base)} {kw_typedef_renamed(name, kw)};")
    for tag, t in sorted(enum_tags.items()):
        lines.append(f"typedef {_base_type(t, enum_base)} __oracle_enum_{tag};")
    unresolved_types = scope.get("unresolved_types") or {}
    widths = (scope.get("target") or {}).get("widths") or {}
    for name in sorted(tokens):
        if name in _STDINT_NAMES and name not in types and name not in status and name in unresolved_types:
            spelled = _stdint_spelling(name, widths)
            if spelled is not None:
                lines.append(f"typedef {spelled} {name};")
                # (R41 review W2) tagged: a failure is the harness disagreeing with the target (the unit is unchecked
                #   — `_run_tu`), never an unattributed assertion counted against the oracle
                lines.append(f'static_assert(sizeof({name}) * __CHAR_BIT__ == {_STDINT_NAMES[name][0]}, '
                             f'"{_WIDTH_TAG}{name}");')
    # (R40) a pointer parameter whose pointee the unit lays out: a struct pointee's type is declared with the members
    #   the oracle models (code using any other does not compile → unchecked); the claim sets ``p[0]`` / ``p[0].a``
    pointee_layouts = scope.get("pointee_types") or {}
    pointees: dict[str, tuple] = {}
    for pname, _decl, scalar, typ in params:
        if scalar:
            continue
        core = " ".join(w for w in str(typ).split() if w not in {"const", "volatile"})
        layout = pointee_layouts.get(core) or {}
        p_members = {m: r for m, r in (layout.get("members") or {}).items()}
        p_arrays = {m: r for m, r in (layout.get("arrays") or {}).items()}
        if not p_members and not p_arrays:
            continue
        pointees[pname] = (core, p_members, p_arrays)
        if "" in p_members or any(x[0] == core for q, x in pointees.items() if q != pname):
            continue   # a scalar pointee (its typedef is above) or a struct type already declared
        paths = sorted([m[1:] for m in p_members] + [m[1:] for m in p_arrays])
        text = _struct_text("__p", paths, {"__p" + m: r for m, r in p_members.items()},
                            {"__p" + m: r for m, r in p_arrays.items()}, enum_base)
        lines.append(f"{core} {text[len('struct '):]};" if core.startswith("struct ") else f"typedef {text} {core};")
    for name in macros:
        # (R41 review I1) a macro body's ``enum TAG`` is renamed like the function text's (the SITS harness does too)
        if name in fbodies:
            lines.append(f"#define {name}({', '.join(fparams.get(name) or [])}) "
                         f"{_untagged(kw_typedef_renamed(_one_line(fbodies[name]), kw), enum_tags)}")
        else:
            lines.append(f"#define {name} {_untagged(kw_typedef_renamed(_one_line(macro_bodies[name]), kw), enum_tags)}")
    for name in sorted(tokens):
        if name in status or name in globals_ or name in arrays:
            continue
        c = dict.get(constants, name) if name in constants else None
        if c is not None and c.get("kind") in {"enumerator", "const_object", "const_object_linked"}:
            t = c["type"]
            lines.append(f"#define {name} (({_base_type(t)})({c['value']}))")
    callees = sorted({m.group(1) for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", body + " " + " ".join(fbodies.get(m, "") for m in macros))
                      if m.group(1) not in status and m.group(1) not in _KEYWORDS and m.group(1) not in types
                      and m.group(1) not in globals_ and m.group(1) not in arrays and not m.group(1).startswith("__oracle")})
    used_globals = [g for g in sorted(tokens) if (g in globals_ or g in arrays) and g not in status]
    # (R39) struct objects the body names whose members the oracle models (``g.a`` objects): a local struct of those
    #   members stands for each — a member the oracle does not model is absent, so code using it does not compile
    struct_globals = scope.get("struct_globals") or {}
    used_structs = [g for g in sorted(tokens) if g in struct_globals and g not in status]
    # (R41) an output the body never names — a global the oracle holds at its input value because nothing the function
    #   runs writes it — is declared like the named ones (its input value, else the fill), so the claim is compiled and
    #   checked instead of failing the whole unit (``use of undeclared identifier``). The stubs write nothing, so this
    #   checks the value flow only, not the write-closure claim (module docstring).
    param_names = {p[0] for p in params}
    body_globals, body_structs = list(used_globals), list(used_structs)
    unnamed_outputs = set()   # (review W1) clang returns what the harness put there: reported apart, not "agree"
    for out_name in sorted({str(n) for c in claims for n in c["outputs"]}):
        root = re.match(r"[A-Za-z_]\w*", out_name)
        if root is None or root.group(0) in param_names or root.group(0) in status:
            continue
        rest, g = out_name[root.end():], root.group(0)
        if g in code_tokens:
            continue
        if not rest and g in globals_:
            used_globals.append(g)
        elif re.fullmatch(r"\[\d+\]", rest) and g in arrays:
            used_globals.append(g)
        elif rest.startswith((".", "[")) and g in struct_globals:
            used_structs.append(g)
        else:
            continue
        unnamed_outputs.add(out_name)
    used_globals, used_structs = list(dict.fromkeys(used_globals)), list(dict.fromkeys(used_structs))
    # (R63) register objects the code reaches only through member paths (`_register_struct_text`) — every use a member
    #   path, the object declared in the unit but not modeled (``unresolved_globals``)
    unresolved_g = scope.get("unresolved_globals") or {}
    reach_text = _code_text(body) + " " + " ".join(f"{macro_bodies.get(m, '')} {fbodies.get(m, '')}" for m in macros)
    registers: dict[str, str] = {}
    for root in sorted(code_tokens):
        if (root in status or root in globals_ or root in arrays or root in struct_globals or root in param_names
                or root in types or root not in unresolved_g):
            continue
        uses = re.findall(rf"\b{re.escape(root)}\b((?:\s*\.\s*[A-Za-z_]\w*)*)", reach_text)
        if not uses or any(not u.strip() for u in uses):
            continue   # used as a whole (an address, a copy): no stand-in
        text = _register_struct_text(sorted({re.sub(r"\s+", "", u)[1:] for u in uses}))
        if text is not None:
            registers[root] = text
    checks: dict[int, tuple] = {}
    closure = (scope.get("effects") or {}).get("functions") or {}

    def writes_through_pointer(callee):
        info = closure.get(callee)
        return info is None or bool(info.get("pointer_write") or info.get("unknown_callees"))

    def put_text(callee):
        """(R64) The fill put through a callee's arguments: every one, none, or the parameters it writes through
        directly (the oracle's `callee_targets`)."""
        if not writes_through_pointer(callee):
            return ""
        info = closure.get(callee) or {}
        targets = info.get("pointer_targets")
        if info.get("unknown_callees") or not targets or targets.get("abs") is None:
            return "(__oracle_put(__a), ...); "
        mask = sum(1 << i for i in targets.get("params") or () if i < 64)
        if not mask:
            return ""
        return (f"int __oracle_i = 0; ((((({mask}ULL >> __oracle_i++) & 1ULL) != 0ULL) ? __oracle_put(__a) : void()), "
                "...); ")

    lines.append(_STAND_IN_TEMPLATE)   # (R64) used only by `_member_stand_ins` members
    for variant, fill in enumerate(_FILLS):
        lines.append(f"namespace __oracle_v{variant} {{")
        lines.append(f"constexpr int __oracle_stub = {fill};")
        # (R36) what a pointer-writing stub leaves in a scalar pointee: the fill value (the oracle holds any value)
        lines.append("template<class __oracle_T> constexpr void __oracle_put(const __oracle_T&) {}")
        lines.append("template<class __oracle_T> constexpr void __oracle_put(__oracle_T* __p) { if constexpr "
                     "(__is_arithmetic(__oracle_T) && !__is_const(__oracle_T)) { if (__p) *__p = (__oracle_T)__oracle_stub; } }")
        for c in callees:
            put = put_text(c)
            lines.append(f"template<class... __oracle_A> constexpr int {c}([[maybe_unused]] __oracle_A... __a) "
                         f"{{ {put}return __oracle_stub; }}")
        for index, claim in enumerate(claims):
            inputs = {k: _input_int(v, constants, scope.get("function_like_macros")) for k, v in claim["inputs"].items()}
            lines.append(f"constexpr long long __oracle_run_{index}(int __oracle_which) {{")
            for g in used_globals:
                if g in globals_:
                    t = globals_[g]["type"]
                    value = inputs.get(g)
                    init = value if _fits(value, t) else _fill_for(t, fill)
                    lines.append(f"  {_base_type(t, enum_base)} {g} = {init};")
                else:
                    a = arrays[g]
                    if a.get("length") is None:
                        return None, {}, "array_length_unresolved:" + g, {}
                    if a.get("const") and a.get("values") is not None:
                        elems = a["values"]
                    else:
                        elems = [inputs.get(f"{g}[{k}]") if _fits(inputs.get(f"{g}[{k}]"), a["type"]) else _fill_for(a["type"], fill)
                                 for k in range(a["length"])]
                    lines.append(f"  {_base_type(a['type'], enum_base)} {g}[{a['length']}] = {{{', '.join(str(v) for v in elems)}}};")
            for root, text in registers.items():
                lines.append(f"  {text} {root} = {{}};")
            for g in used_structs:
                members = struct_globals[g].get("members") or []
                stands = _member_stand_ins(g, struct_globals[g].get("unmodeled_members") or [], reach_text)
                lines.append(f"  {_struct_text(g, members, globals_, arrays, enum_base, {m: d for m, (d, _x) in stands.items()})} "
                             f"{g} = {{}};")
                for m, (_decl, depth) in stands.items():
                    lines.append(f"  {g}.{m} = (unsigned long long){fill};" if not depth else
                                 f"  {g}.{m} = __oracle_pm<{depth}>{{{fill}}};")
                for path in members:
                    full = f"{g}.{path}"
                    if full in globals_:
                        t = globals_[full]["type"]
                        value = inputs.get(full)
                        lines.append(f"  {full} = {value if _fits(value, t) else _fill_for(t, fill)};")
                        continue
                    a = arrays[full]
                    for k in range(a["length"]):
                        value = inputs.get(f"{full}[{k}]")
                        lines.append(f"  {full}[{k}] = {value if _fits(value, a['type']) else _fill_for(a['type'], fill)};")
            args = []
            for i, (name, _decl, scalar, typ) in enumerate(params):
                if scalar:
                    try:
                        from generators.mcdc_design import _scope_type
                        t = _scope_type(scope, typ)
                    except cpc.Unresolved:
                        return None, {}, "parameter_type_unresolved:" + name, {}
                    value = inputs.get(name)
                    args.append(str(value if _fits(value, t) else _fill_for(t, fill)))
                elif name in pointees and "" not in pointees[name][1]:
                    # (R40) a struct pointee: element 0 holds what the claim set, the rest of it the fill
                    _core, p_members, p_arrays = pointees[name]
                    lines.append(f"  {_core} __oracle_buf_{i}[64] = {{}};")
                    for m, r in sorted(p_members.items()):
                        value = inputs.get(f"{name}[0]{m}")
                        lines.append(f"  __oracle_buf_{i}[0]{m} = {value if _fits(value, r['type']) else _fill_for(r['type'], fill)};")
                    for m, r in sorted(p_arrays.items()):
                        for k in range(r["length"]):
                            value = inputs.get(f"{name}[0]{m}[{k}]")
                            lines.append(f"  __oracle_buf_{i}[0]{m}[{k}] = "
                                         f"{value if _fits(value, r['type']) else _fill_for(r['type'], fill)};")
                    args.append(f"__oracle_buf_{i}")
                else:
                    # the pointee varies with the fill too: what the claim does not depend on must not matter
                    lines.append(f"  {_untagged(typ, enum_tags)} __oracle_buf_{i}[64] = {{}};")
                    lines.append(f"  for (int __oracle_k = 0; __oracle_k < 64; ++__oracle_k) __oracle_buf_{i}[__oracle_k] = {fill};")
                    if name in pointees:   # (R40) a scalar pointee the claim set: ``p[0]``
                        rec = pointees[name][1][""]
                        value = inputs.get(f"{name}[0]")
                        if _fits(value, rec["type"]):
                            lines.append(f"  __oracle_buf_{i}[0] = {value};")
                    args.append(f"__oracle_buf_{i}")
            # (R14) a callee the claim's sequence stubs (``F() return``) returns that value, in F's declared type — a
            #   local lambda shadows the namespace stub for this run only (the oracle takes the same value)
            for c in callees:
                key = f"{c}() return"
                # (R38 review W1) a sequence that sets one of the stub's out-parameters (``F() p[0]``) has the stub
                #   write through its pointers whatever F's body does — the oracle holds the pointee unknown
                out_params = any(k.startswith(c + "() ") and k != key for k in claim["inputs"])
                if key not in claim["inputs"]:
                    if out_params:
                        # (review round 2 Info 1) an out-parameter-only stub: its return is not the claim's to use
                        lines.append(f"  auto {c} = [&]([[maybe_unused]] auto... __a) -> int "
                                     "{ (__oracle_put(__a), ...); return __oracle_stub; };")
                    continue
                rt_text = str((((scope.get("effects") or {}).get("functions") or {}).get(c) or {}).get("return_type")
                              or "")
                sv = _input_int(claim["inputs"][key], constants, scope.get("function_like_macros"))
                if not rt_text or "*" in rt_text or sv is None:
                    continue
                try:
                    from generators.mcdc_design import _scope_type
                    rt = _scope_type(scope, rt_text)
                except cpc.Unresolved:
                    continue
                if _fits(sv, rt):
                    put = "(__oracle_put(__a), ...); " if out_params or writes_through_pointer(c) else ""
                    lines.append(f"  auto {c} = [&]([[maybe_unused]] auto... __a) -> {_base_type(rt, enum_base)} "
                                 f"{{ {put}return {sv}; }};")
            plist = ", ".join(p[1] for p in params)
            if instrument:
                nd = len(instrument["decisions"])
                na = max(len(d["atoms"]) for d in instrument["decisions"])
                lines.append(f"  int __oracle_cnt[{nd}] = {{}}; int __oracle_rec[{nd}][{_MAX_EVALUATIONS}][{na}] = {{}};"
                             f" int __oracle_out[{nd}][{_MAX_EVALUATIONS}] = {{}};")
                lines.append("  auto __oracle_begin = [&](int __d) -> int { ++__oracle_cnt[__d]; return 0; };")
                lines.append(f"  auto __oracle_atom = [&](int __d, int __a, bool __v) -> bool {{ if (__oracle_cnt[__d] <= "
                             f"{_MAX_EVALUATIONS}) __oracle_rec[__d][__oracle_cnt[__d] - 1][__a] = __v ? 2 : 1; return __v; }};")
                lines.append(f"  auto __oracle_end = [&](int __d, bool __v) -> bool {{ if (__oracle_cnt[__d] <= "
                             f"{_MAX_EVALUATIONS}) __oracle_out[__d][__oracle_cnt[__d] - 1] = __v ? 2 : 1; return __v; }};")
            lines.append(f"  auto __oracle_fn = [&]({plist}) -> {rtype}")
            lines.append(body)
            lines.append("  ;")
            if rtype.strip() == "void":
                lines.append(f"  __oracle_fn({', '.join(args)});")
                lines.append("  long long __oracle_ret = 0;")
            else:
                lines.append(f"  long long __oracle_ret = (long long)__oracle_fn({', '.join(args)});")
            lines.append("  switch (__oracle_which) {")
            buffers = {pn: j for j, (pn, _d, sc, _t) in enumerate(params) if not sc and pn in pointees}
            for k, name in enumerate(claim["outputs"]):
                expr = "__oracle_ret" if name == "return" else name
                m = re.fullmatch(r"([A-Za-z_]\w*)(\[0\].*)", str(name))
                if m and m.group(1) in buffers:
                    expr = f"__oracle_buf_{buffers[m.group(1)]}{m.group(2)}"   # (R40) a pointee output
                lines.append(f"    case {k}: return (long long)({expr});")
            lines.append("  }")
            lines.append("  return -999999999LL;")
            lines.append("}")
        lines.append("}")
    tags: dict[str, tuple] = {}
    lines.append('static_assert(1 == 2, "__oracle_canary");')
    for variant in range(len(_FILLS)):
        for index, claim in enumerate(claims):
            for k, (name, value) in enumerate(claim["outputs"].items()):
                tag = f"__oracle_check_{index}_{variant}_{k}"
                tags[tag] = (index, name, value, variant, f"{index}_{variant}_{k}")
                lines.append(f"static_assert(__oracle_v{variant}::__oracle_run_{index}({k}) == {int(value)}LL, \"{tag}\");")
    text = "\n".join(lines) + "\n"
    # Line numbers come from the final text (function bodies span many lines): each assertion carries a unique tag.
    for number, line in enumerate(text.split("\n"), start=1):  # clang counts only \n (\f, \v, \x85 are not lines)
        m = re.search(r'"(__oracle_check_\d+_\d+_\d+)"\);$', line)
        if m and line.startswith("static_assert("):
            checks[number] = tags[m.group(1)]
    if len(checks) != len(tags):
        return None, {}, "assertion_lines_not_unique", {}
    # (review I4) an output the body never names does not make the unit an enum one: its value is the harness's own
    meta = {"callees": bool(callees), "unnamed_outputs": unnamed_outputs, "enum": bool(enum_tags)
            or any(isinstance(types.get(x), dict) and types[x].get("enum") for x in tokens)
            or any((globals_.get(g) or arrays.get(g) or {}).get("type", {}).get("enum") for g in body_globals)
            or any((globals_.get(f"{g}.{m}") or arrays.get(f"{g}.{m}") or {}).get("type", {}).get("enum")
                   for g in body_structs for m in struct_globals[g].get("members") or [])}
    return text, checks, "", meta


def decision_claim(d, truth, observed, outcome):
    """(R2c) Output expression for a path-designed MC/DC claim: 1 when some evaluation of instrumented decision ``d``
    in the run had exactly these evaluated conditions (``observed``) with these values and this outcome, else 0. When
    the decision was evaluated more often than the recorder holds, the expression throws: not a constant expression, so
    the claim is counted *unchecked* (``constexpr_limit``) — neither agreed nor contradicted."""
    codes = [(2 if t else 1) if o else 0 for t, o in zip(truth, observed, strict=True)]
    atoms = " && ".join(f"__oracle_rec[{d}][__e][{i}] == {c}" for i, c in enumerate(codes))
    return (f"[&]() -> long long {{ if (__oracle_cnt[{d}] > {_MAX_EVALUATIONS}) throw 0; "
            f"for (int __e = 0; __e < __oracle_cnt[{d}]; ++__e) if ({atoms} && __oracle_out[{d}][__e] == "
            f"{2 if outcome else 1}) return 1; return 0; }}()")


def _one_line(body):
    return body.replace("\r\n", "\n").replace("\r", "\n").replace("\\\n", " ").replace("\n", " ")


_TAG = re.compile(r"__oracle_check_\d+_\d+_\d+")


def _run_tu(source, checks, path, clang, target, timeout, ub_probe=False):
    """Compile one harness. Returns ({(claim, output): verdict}, {(claim, output): detail}) or a unit-level reason."""
    Path(path).write_text(source, encoding="utf-8", newline="\n")
    try:
        proc = subprocess.run([clang, "-x", "c++", f"--target={target}", "-std=c++20", "-fsyntax-only",
                               "-ferror-limit=0", "-fconstexpr-steps=20000000", "-Wno-everything",
                               "-Werror=unsequenced", path],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, None, "clang_failed:" + type(exc).__name__
    by_tag = {}
    tag_of_line = {}
    for lineno, check in checks.items():
        tag = f"__oracle_check_{check[4]}"
        by_tag[tag] = check
        tag_of_line[lineno] = tag
    errors: dict[str, list[str]] = {}
    other_errors, unattributed = [], []
    width_disagrees = []
    canary = False
    current = None
    for line in (proc.stdout + proc.stderr).splitlines():
        m = re.match(r"^.*?:(\d+):\d+: (fatal error|error|note): (.*)$", line)
        if not m:
            if re.match(r"^(?:\S*clang\S*: )?(?:fatal )?error:", line.strip()):
                other_errors.append("driver: " + line.strip()[:160])  # ``clang: error: unknown target`` (round 2 C)
            continue
        lineno, kind, message = int(m.group(1)), m.group(2), m.group(3)
        if "__oracle_canary" in message:
            canary = True
            current = None
            continue
        if _WIDTH_TAG in message:
            width_disagrees.append(message)   # (R41 review W2) the harness's typedef, not a claim: the unit is unchecked
            current = None
            continue
        if kind in {"error", "fatal error"}:
            tag = next((t for t in _TAG.findall(message) if t in by_tag), None) or tag_of_line.get(lineno)
            current = tag
            if tag is not None:
                errors.setdefault(tag, []).append(message)
            elif "static assertion failed" in message:
                unattributed.append(message)  # a failed claim we cannot place: fail closed below
            else:
                other_errors.append(f"{lineno}: {message}")
        elif current is not None:
            errors.setdefault(current, []).append(message)
    if not canary or proc.returncode != 1:
        # The canary must fail and nothing else may stop clang: otherwise the run proves nothing (round 2 C).
        return None, None, "canary_not_reported:" + (other_errors[0] if other_errors else f"rc={proc.returncode}")
    if width_disagrees:
        return None, None, "stdint_width_disagrees_with_target"
    if unattributed:
        return None, None, "unattributed_assertion_failure"
    if any("unsequenced" in e for e in other_errors):
        return None, None, "unsequenced_in_source"
    if other_errors or proc.returncode not in (0, 1):
        return None, None, "harness_compile_error:" + (other_errors[0] if other_errors else f"rc={proc.returncode}")
    verdict: dict[tuple, str] = {}
    detail: dict[tuple, str] = {}
    rank = _PROBE_RANK if ub_probe else _CHECK_RANK
    for tag, (index, name, _value, variant, _tag) in by_tag.items():
        msgs = errors.get(tag)
        k = (index, name)
        if not msgs:
            one = "agree"
        elif any(_REAL_EVAL_ERROR.search(x) for x in msgs) and (ub_probe or not any("static assertion failed" in x
                                                                               for x in msgs)):
            # Undefined behaviour or an indeterminate read on the path contradicts a "derived" claim (and, probing, is
            # the answer — the asserted value is a placeholder: review round 1 W6)
            one = "eval_error"
        elif any("static assertion failed" in x for x in msgs):
            one = "mismatch"
        else:
            one = "constexpr_limit"   # ``reinterpret_cast`` of an array argument, a volatile read: a harness limit
        if rank[one] > rank[verdict.get(k, "agree")] or k not in verdict:
            verdict[k] = one
            if msgs:
                text = next((x for x in msgs if "evaluates to" in x), None) if one == "mismatch" else None
                detail[k] = (text or " | ".join(msgs[:3])) + f" (fill={_FILLS[variant]})"
    return verdict, detail, ""


def check_claims(claims: list[dict], clang: str = "clang", target: str = "msp430", work_dir: str | None = None,
                 timeout: int = 120, ub_probe: bool = False) -> dict:
    """``claims``: ``[{"unit": unit-with-project_scope, "inputs": {...}, "outputs": {name: value}, "possible_ub": [...]}]``.

    ``agree`` counts claims that held for every fill value (and, when the function uses an enumeration, for every
    permitted underlying type). ``agree_with_stubbed_callees`` is the part of it whose function makes calls: the
    stubs write nothing, so for those claims the callee-effect model is *not* what clang confirmed."""
    from generators import c_project_context as cpc
    from generators.c_source_oracle import _find_function
    groups: dict[tuple, list] = {}
    for claim in claims:
        unit = claim["unit"]
        groups.setdefault((unit.get("source_path") or "", unit.get("name") or "", id(unit["project_scope"]),
                           id(claim.get("instrument"))), []).append(claim)
    report = {"target": target, "fills": list(_FILLS), "enum_bases": list(_ENUM_BASES),
              "claims": sum(len(c["outputs"]) for c in claims),
              "checked": 0, "agree": 0, "agree_with_stubbed_callees": 0, "mismatch": 0, "eval_error": 0, "unchecked": 0,
              "unchecked_reasons": Counter(), "mismatches": [], "eval_errors": []}
    work = work_dir or tempfile.mkdtemp(prefix="oracle_clang_")
    os.makedirs(work, exist_ok=True)
    parser = cpc.shared_parser()
    for gi, (_key, group) in enumerate(groups.items()):
        unit = group[0]["unit"]
        n_outputs = sum(len(c["outputs"]) for c in group)
        raw = str(unit.get("source_text") or "").encode()
        # (R62) same length as ``raw`` — the projected tree's positions index it. (R63) vendor syntax clang does not know
        #   (``__interrupt`` · ``__far`` · ``@0x…``) read as blanks, as the generator read it; the #if lines stay for clang
        original = cpc.reading_text(str(unit.get("source_text_original") or unit.get("source_text") or "").encode())[0]
        verdict: dict[tuple, str] = {}
        detail: dict[tuple, str] = {}
        failure = ""
        meta: dict = {}
        for bi, base in enumerate(_ENUM_BASES):
            try:
                fn = _find_function(parser.parse(raw).root_node, raw, unit["name"], unit["project_scope"])
                source, checks, reason, meta = _harness(unit, group, fn, original, enum_base=base,
                                                        instrument=group[0].get("instrument"))
            except Exception as exc:  # noqa: BLE001 — any harness failure is an unchecked unit, reported by name
                source, checks, reason = None, {}, f"harness_exception:{type(exc).__name__}"
            if source is None:
                failure = reason
                break
            one, one_detail, reason = _run_tu(source, checks, os.path.join(work, f"u{gi}_{bi}.cpp"), clang, target, timeout,
                                              ub_probe=ub_probe)
            if one is None:
                failure = reason
                break
            rank = _PROBE_RANK if ub_probe else _CHECK_RANK
            for k, v in one.items():
                if rank[v] >= rank.get(verdict.get(k, "agree"), 0):
                    verdict[k] = v
                    if k in one_detail:
                        detail[k] = one_detail[k] + ("" if base == "int" else f" (enum as {base})")
            if not meta.get("enum"):
                break  # no enumeration involved: one underlying type is the whole story
        if failure:
            for claim in group:   # (R11) every output of the group gets this verdict
                verdicts_of = claim.setdefault("verdicts", {})
                for name in claim["outputs"]:
                    verdicts_of[name] = ("eval_error" if failure == "unsequenced_in_source" else
                                         "mismatch" if failure == "unattributed_assertion_failure" else
                                         "unchecked:" + failure.split(":")[0])
            if failure == "unsequenced_in_source":
                # The body itself is order-dependent: a claim on it is a real contradiction, not a harness limit.
                for index, claim in enumerate(group):
                    for name in claim["outputs"]:
                        report["checked"] += 1
                        report["eval_error"] += 1
                        report["eval_errors"].append({"function": unit["name"], "file": unit.get("source_path"),
                                                      "inputs": claim["inputs"], "output": name,
                                                      "claimed": claim["outputs"][name], "clang": failure})
                continue
            report["unchecked"] += n_outputs
            report["unchecked_reasons"][failure.split(":")[0]] += n_outputs
            if failure.startswith("harness_compile_error") or failure == "unattributed_assertion_failure":
                report.setdefault("compile_errors", []).append({"function": unit["name"], "file": unit.get("source_path"),
                                                                 "first": failure[:200]})
            if failure == "unattributed_assertion_failure":
                report["mismatch"] += n_outputs  # fail closed: a failed assertion we cannot place is a failure
                report["unchecked"] -= n_outputs
                report["checked"] += n_outputs
            continue
        unnamed = meta.get("unnamed_outputs") or set()
        for (index, name), v in verdict.items():
            if v == "eval_error" and _disclosure_explains(group[index].get("possible_ub"), detail.get((index, name))):
                # The oracle disclosed that this run may be undefined (an unknown divisor/shift/index/overflow — the
                # fill values chose one) and clang reports that kind: not a counterexample to a disclosed claim.
                v = "possible_ub_disclosed"
            if v == "agree" and name in unnamed and not ub_probe:
                # (R41 review W1) clang returned the value the harness declared the output with: nothing it computed.
                #   A mismatch there stays one (the claim is not even its own input); an agreement is no check.
                #   (review W-R2-1) Not in the UB probe: there the asserted value is a placeholder and agree/mismatch
                #   both say "evaluated without UB" — the probe's answer, whatever the output is
                v = UNNAMED_OUTPUT
            if name in unnamed and not ub_probe:
                # (review I-R3-1) the review list is structural — whatever the verdict (a constexpr limit, a mismatch)
                report.setdefault("outputs_not_named_by_body", {}).setdefault(
                    f"{unit['name']} ({unit.get('source_path')})", set()).add(name)
            # (R11) the verdict per claim output, for callers that annotate rows
            group[index].setdefault("verdicts", {})[name] = (
                "unchecked:" + v if v in {"constexpr_limit", "possible_ub_disclosed", UNNAMED_OUTPUT} else
                "agree_with_stubbed_callees" if v == "agree" and meta.get("callees") else v)
            if v in {"constexpr_limit", "possible_ub_disclosed", UNNAMED_OUTPUT}:
                report["unchecked"] += 1
                report["unchecked_reasons"][v] += 1
                continue
            report["checked"] += 1
            report[v] += 1
            if v == "agree" and meta.get("callees"):
                report["agree_with_stubbed_callees"] += 1
            if v != "agree":
                entry = {"function": unit["name"], "file": unit.get("source_path"), "inputs": group[index]["inputs"],
                         "output": name, "claimed": group[index]["outputs"][name], "clang": detail.get((index, name))}
                report["mismatches" if v == "mismatch" else "eval_errors"].append(entry)
    report["unchecked_reasons"] = dict(report["unchecked_reasons"])
    if "outputs_not_named_by_body" in report:
        # observables a function cannot change (no write to them in its text): a document-side finding to review
        #   (e.g. a unit test that observes ``u8s_X`` while the function writes ``u8s_X2``)
        report["outputs_not_named_by_body"] = {k: sorted(v) for k, v in sorted(report["outputs_not_named_by_body"].items())}
    report["work_dir"] = work
    return report


def _claims_from_xlsm(xlsm: str, source_root: str) -> tuple[list[dict], dict]:
    import openpyxl

    from generators.c_project_context import build_project_context, build_scopes
    wb = openpyxl.load_workbook(xlsm, read_only=True)
    ws = wb["Test Evidence"]
    rows = ws.iter_rows(values_only=True)
    header = list(next(rows))
    grouped: dict[tuple, dict] = {}
    for row in rows:
        d = dict(zip(header, row, strict=False))
        if d.get("Status") != "derived":
            continue
        key = (d["Source path"], d["Function"], d["Test Case ID"], d["Sequence"])
        reason = str(d.get("Reason") or "")
        g = grouped.setdefault(key, {"inputs": json.loads(d.get("Inputs JSON") or "{}"), "outputs": {},
                                     "source_hash": str(d.get("Source SHA256") or ""),
                                     "possible_ub": reason.split("possible_ub=", 1)[1].split("+") if "possible_ub=" in reason else []})
        g["outputs"][d["Observable"]] = int(d["Expected"])
    # Several roots (``APP,BOOT``) are joined with ``,``/``;`` as in the SCM registry — one context, as generated.
    roots = [r.strip() for r in re.split(r"[,;]", source_root) if r.strip()]
    texts, unread = {}, []
    for root in roots:
        for p in sorted(Path(root).rglob("*")):
            if p.suffix.lower() in (".c", ".h") and p.is_file():
                try:
                    texts[str(p.resolve())] = p.read_bytes().decode("utf-8")
                except UnicodeDecodeError:
                    unread.append(str(p.resolve()))  # recorded: never mistaken for a toolchain header
    from generators.c_project_context import detect_build_config
    cprojects = {str(Path(r) / ".cproject"): (Path(r) / ".cproject").read_text(encoding="utf-8", errors="replace")
                 for r in roots if (Path(r) / ".cproject").is_file()}
    context = build_project_context(texts, detect_build_config(cprojects), roots=[str(Path(r).resolve()) for r in roots])
    context["incomplete_files"] = unread
    paths = sorted({k[0] for k in grouped if k[0] in texts})
    scopes = build_scopes(context, paths)
    # (R62) the generator reads a function an #if splits mid-expression projected (`apply_body_projection`): the unit is
    #   that text (its hash is the row's), and the harness compiles the *original* body at the same positions — clang's
    #   own preprocessor then decides the #if again, under the macros the harness defines from the unit's table
    from generators.c_project_context import apply_body_projection
    projected = {p: apply_body_projection(scopes[p], texts[p]) for p in paths}
    units: dict[tuple, dict] = {}
    claims = []
    skipped: dict[tuple, str] = {}
    for (path, fn, _tc, _seq), g in grouped.items():
        if path not in scopes:
            skipped[(path, fn, _tc, _seq)] = "source_missing"
            continue
        # (review R11 W4) the row was derived from the text its hash names: a changed file is not what it claims about
        if g["source_hash"] and g["source_hash"] not in _text_hashes(texts[path]) | _text_hashes(projected[path]):
            skipped[(path, fn, _tc, _seq)] = "source_changed"
            continue
        unit = units.setdefault((path, fn), {"name": fn, "source_text": projected[path], "source_path": path,
                                             "source_text_original": texts[path], "project_scope": scopes[path]})
        claims.append({"unit": unit, "key": (path, fn, _tc, _seq), **g})
    meta = {"xlsm": xlsm, "source_root": source_root, "derived_sequences": len(grouped),
            "sequences_with_source": len(claims), "skipped_sequences": skipped,
            "skipped_reasons": dict(Counter(skipped.values()))}
    return claims, meta


def _text_hashes(text: str) -> set[str]:
    """The text's SHA-256 as read and with CRLF → LF (the generator's local mode reads with universal newlines)."""
    return {hashlib.sha256(text.encode()).hexdigest(), hashlib.sha256(text.replace("\r\n", "\n").encode()).hexdigest()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--xlsm", required=True, help="generated SUTS workbook with a 'Test Evidence' sheet")
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--clang", default="clang")
    ap.add_argument("--target", default="msp430", help="clang target with the ECU's integer widths")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    claims, meta = _claims_from_xlsm(args.xlsm, args.source_root)
    meta = {k: v for k, v in meta.items() if k != "skipped_sequences"}
    report = {**meta, **check_claims(claims, clang=args.clang, target=args.target)}
    text = json.dumps(report, ensure_ascii=False, indent=1, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    summary = {k: report[k] for k in ("claims", "checked", "agree", "mismatch", "eval_error", "unchecked", "unchecked_reasons")}
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if report["mismatch"] or report["eval_error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
