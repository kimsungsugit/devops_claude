"""Project-level C context for test design: target widths, typedefs, integer macros, enumerators, globals.

Built once per source tree from the unchanged files. Every resolved value traces to a declaration
(file + line). Anything the preprocessor configuration or the target could change is left
unresolved with a reason — never guessed:

* integer widths come only from typedef *testimony* (``typedef unsigned int U16;`` says this
  target's ``unsigned int`` is 16 bits); conflicting testimony leaves the width unknown;
* an object-like macro is a constant only if every definition visible to the translation unit
  is unconditional, identical, never ``#undef``-ed and evaluates under C integer rules;
* a global is an input only through a declaration visible to the file, with a resolved scalar
  integer type; its entry value stays bound only if no callee (transitively) can write it.

The result is JSON-serializable (it rides in the source-sections cache).
"""
from __future__ import annotations

import bisect
import hashlib
import os
import re
import struct
import threading
from fractions import Fraction
from typing import Any

from generators import pointer_flow
from workflow.code_parser.c_parser import _make_parser

# 2: preprocessor events look into parse-recovery containers; file-level `address_taken`; function `idents`.
SCHEMA_VERSION = 24  # 3: per-file `prototypes`; closure `macros` (tree union)
# 4 (R2b): global `dims`/`array_init` (arrays, const lookup tables) and function-like macro `params`.
# 5 (R2b): `build` — toolchain include directories from the build configuration (``.cproject``).
# 6 (R2b): `roots` — several source roots are separate builds; a shared header name resolves per root.
# 7 (R14): function `return_type` (declared text) and closure `return_type` — one when every definition agrees.
# 8 (R16): a function-type "cast" (``(F()) + 1U``, tree-sitter's reading of a parenthesized call) is the call ``F`` in the
#    function's `calls` — the write closure used to miss it.
# 9 (R17): `build.configurations` — the -D set of each `.cproject` and whether it is complete (names neither the tree nor
#    the build defines become undefined in #if instead of undecided).
# 10 (R17): per-file `body_condition_names` (identifiers of function-body #if conditions — the scope's
#    `assumed_undefined_body`).
# 11 (R17): `build.configurations` fails closed on more -D spellings and C++/C tool disagreement.
# 12 (R16b): a typedef whose new name the grammar knows as a primitive (``typedef unsigned char bool;``,
#    ``typedef signed char int8_t;``) is recorded — it was dropped, so ``bool`` stayed ``_Bool``.
# (R35, no bump) closure `macros` entries gained `names` · `function_like` · `opaque` · `conditional_ops` (see
#    `undecided_macro_view`). The closure is built from the context each time scopes are built (`build_scopes`), never
#    stored with it: a cached context gets the new fields as it is. Bumping here without the source-stage cache version
#    (`backend/helpers/uds.py` `_SOURCE_SECTIONS_SCHEMA_VERSION`) makes every cached context refuse its scopes.
# 13 (R39): per-file `structs` (struct/union member lists, `_collect_struct`) and a global's `struct_key` — a scope
#    flattens a struct object's scalar members into `globals`/`arrays` (`g.a`, `g.b`) and lists it in `struct_globals`.
#    Paired with `_SOURCE_SECTIONS_SCHEMA_VERSION` v41.
# 14 (R39 review round 2): a struct body with a parse error in a member, or with bit-fields, keeps no members (``hidden`` /
#    ``bit_fields``) — a context cached by 13 lacks them. Paired with v42.
# 15 (R40): a function's `pointer_params` (``T *p`` — name and pointee type text); a scope lays out those pointee types
#    (`pointee_types`). Paired with v43.
# 16 (R40 review round 1): a struct pointee of a unit with preprocessing gaps keeps no layout (as a struct global —
#    a member may sit under an #if the unit cannot decide) — a context cached by 15 lays it out. Paired with v44.
# 17 (R62): per-file `body_directives` (#define / #undef / #include inside function bodies — those names vary in the unit,
#    an in-body #include is a gap), and a file-level ``#  ifndef`` (blank after ``#``) read as ``#ifndef`` in `events` and
#    the include guard (`_directive_keyword`) — a context cached by 16 lacks the first and read the second as ``#ifdef``.
#    Paired with v45.
# 18 (R62 review round 4): per-file `stray_directives` replaces `body_directives` — every #define / #undef / #include
#    line the file-level walk does not read (bodies, unrecognized constructs, headers' inline functions), keyword read
#    after splices and comments. Paired with v46.
# 19 (R62 review round 5): facts read from `_parse_safe` text (a value-less ``#define NAME `` keeps its own line — the
#    next line was its value), ``#  undef`` read as ``#undef``, `stray_directives` compare the directive kind per row
#    and record the conditional lines met (`conditionals`). Paired with v47.
# 20 (R63): file-level directives read from the lexer (`_file_walk`) — #defines among struct members, in ERROR nodes and
#    in ``extern "C" { }``, macro bodies without line splices — from `reading_text` (vendor syntax as blanks); per-file
#    `reading` facts. Paired with v48.
# 21 (R64): per-function `flow` and per-file `flow` — the pointer-flow facts (`pointer_flow.function_facts` /
#    `file_facts`: stores, calls, returns, declared kinds, what the facts cannot hold) a context cached by 20 lacks; the
#    closure's `pointer_targets` rest on them. Paired with v49.
# 22 (R64 review): the flow facts of a struct record its unnamed members (an anonymous union's pointer counts when an
#    object of it may hold one) — 21 lacks them. Paired with v50.
# 23 (R64 review round 3): flow facts carry function-local typedef names (`local_types`) and K&R definitions
#    (`params_unreadable`); a body `#define` stray carries its text (`body`) — 22 lacks them. Paired with v51.
# 24 (R64 review round 4): per-file `paren_amp` — ``(T)&x`` read as a bitwise and — 23 lacks it. Paired with v52.
_ARRAY_INIT_BUDGET = 20000
#: (R67 review I-1) element values a const table may hold in the scope — a designator index or a declared length past it
#   (``{ [2000000] = 1U }``) is no lookup table; its values stay unread
_ARRAY_VALUES_BUDGET = 65536

_RANKS = {"_Bool": 0, "char": 1, "short": 2, "int": 3, "long": 4, "long long": 5}
_WIDTH_NAME_RE = re.compile(r"^[vl]?_?(?P<sign>u|s|uint|sint|int)(?P<bits>8|16|32|64)(?:_t)?$", re.I)
_LITERAL_RE = re.compile(r"^(?P<sign>[-+]?)(?P<digits>0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)"
                         r"(?P<suffix>[uU](?:ll|LL|l|L)?|(?:ll|LL|l|L)[uU]?)?$")
_FLOAT_RE = re.compile(r"^(?P<sign>[-+]?)(?P<number>(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?|[0-9]+[eE][-+]?[0-9]+)"
                       r"(?P<suffix>[fFlL]?)$")
FLOAT = {"kind": "float", "bits": 32, "signed": True, "rank": 10}
DOUBLE = {"kind": "double", "bits": 64, "signed": True, "rank": 11}
_STD_TYPES = frozenset({"uint8_t", "int8_t", "uint16_t", "int16_t", "uint32_t", "int32_t", "uint64_t", "int64_t"})
# names the grammar or the library gives a meaning that a project's own typedef overrides (R16b review R2)
_PROJECT_MAY_TYPEDEF = _STD_TYPES | {"bool"}


class Unresolved(ValueError):
    """A value or type the declarations do not determine."""


# (R35) tree-sitter-c parses ``TRUE``/``FALSE`` (and ``true``/``false``) as ``true``/``false`` keyword nodes outside
# ``#if``; the preprocessor sees names — a project's ``#define TRUE 1U``, <stdbool.h>'s ``true``. Wherever a node is asked
# "is this a name (a macro, a constant, an object)?", these node types answer like ``identifier``.
NAME_NODE_TYPES = frozenset({"identifier", "true", "false"})


def is_name_node(node) -> bool:
    return node is not None and node.type in NAME_NODE_TYPES


# ── C integer types ─────────────────────────────────────────────────────────────────────────────

def base_kind(text: str) -> tuple[str, bool | None] | None:
    """``unsigned short int`` → (``short``, False). Plain ``char`` signedness is implementation-defined (None)."""
    tokens = [t for t in str(text or "").replace("\t", " ").split() if t not in {"const", "volatile", "register", "static", "extern"}]
    if not tokens:
        return None
    if tokens in (["_Bool"], ["bool"]):
        return ("_Bool", False)
    if tokens in (["float"], ["double"]):
        return (tokens[0], True)
    known = {"signed", "unsigned", "char", "short", "int", "long"}
    if any(t not in known for t in tokens):
        return None
    signed = False if "unsigned" in tokens else (True if "signed" in tokens else None)
    longs = tokens.count("long")
    if "char" in tokens:
        kind = "char"
    elif "short" in tokens:
        kind = "short"
    elif longs >= 2:
        kind = "long long"
    elif longs == 1:
        kind = "long"
    else:
        kind = "int"
    if signed is None and kind != "char":
        signed = True
    return kind, signed


def ctype(kind: str, signed: bool, widths: dict[str, int]) -> dict[str, Any]:
    if kind == "float":
        return dict(FLOAT)
    if kind == "double":
        return dict(DOUBLE)
    if kind == "_Bool":
        return {"kind": "_Bool", "bits": 1, "signed": False, "rank": 0}
    bits = widths.get(kind)
    if not bits:
        raise Unresolved("target_width_unknown:" + kind)
    return {"kind": kind, "bits": bits, "signed": signed, "rank": _RANKS[kind]}


def type_range(t: dict[str, Any]) -> tuple[int, int]:
    if t["signed"]:
        return -(1 << (t["bits"] - 1)), (1 << (t["bits"] - 1)) - 1
    return 0, (1 << t["bits"]) - 1


def promote(t: dict[str, Any], widths: dict[str, int]) -> dict[str, Any]:
    if t["rank"] >= _RANKS["int"]:
        return t
    int_t = ctype("int", True, widths)
    lo, hi = type_range(t)
    ilo, ihi = type_range(int_t)
    return int_t if ilo <= lo and hi <= ihi else ctype("int", False, widths)


def usual_conversion(a: dict[str, Any], b: dict[str, Any], widths: dict[str, int]) -> dict[str, Any]:
    """C11 6.3.1.8 usual arithmetic conversions for two integer types."""
    a, b = promote(a, widths), promote(b, widths)
    if (a["kind"], a["signed"]) == (b["kind"], b["signed"]):
        return a
    if a["signed"] == b["signed"]:
        return a if a["rank"] >= b["rank"] else b
    u, s = (a, b) if not a["signed"] else (b, a)
    if u["rank"] >= s["rank"]:
        return u
    if s["bits"] > u["bits"]:
        return s
    return {**s, "signed": False}


def is_float(t: dict[str, Any] | None) -> bool:
    return bool(t) and t.get("kind") in {"float", "double"}


FLOAT_MODES = ("f64", "f32", "wide")


def _round_float(value: float, t: dict[str, Any], mode: str) -> float:
    """Round to the evaluation format. The source does not say how the target evaluates floating expressions, so
    callers evaluate in every mode and require one integer answer:

    * ``f64`` — FLT_EVAL_METHOD 0 with a 64-bit ``double`` (``float`` ops in single precision);
    * ``f32`` — ``double`` is 32 bits (a common embedded compiler option);
    * ``wide`` — FLT_EVAL_METHOD 1/2: operations and floating constants kept in wider precision.
    """
    if mode == "wide":
        return float(value)
    if t["kind"] == "float" or mode == "f32":
        try:
            return struct.unpack("<f", struct.pack("<f", value))[0]
        except OverflowError as exc:
            raise Unresolved("float_overflow") from exc
    return float(value)


def convert(value: int | float, t: dict[str, Any], mode: str = "f64") -> int | float:
    if is_float(t):
        return _round_float(float(value), t, mode)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise Unresolved("float_not_finite")
        truncated = int(value)
        lo, hi = type_range(t) if t["kind"] != "_Bool" else (0, 1)
        if t["kind"] == "_Bool":
            return int(value != 0)
        if not lo <= truncated <= hi:
            raise Unresolved("float_to_int_out_of_range")  # undefined behavior (C11 6.3.1.4)
        if t.get("enum") and not 0 <= truncated <= 127:
            # (R67 review round 5) the enumeration's type is implementation-defined — as for an integer below
            raise Unresolved("enum_underlying_type_implementation_defined")
        return truncated
    if t["kind"] == "_Bool":
        return int(bool(value))
    if t.get("enum") and not 0 <= value <= 127:
        # (R67 review C-1) an enumeration's type is implementation-defined (C11 6.7.2.2p4) — char or int, signed or
        #   unsigned: only 0..127 converts alike under every choice (the oracle's `enum_candidates`). ``((ETYPE)-1)`` is
        #   UINT_MAX under gcc's unsigned choice, 255 under -fshort-enums — no one value
        raise Unresolved("enum_underlying_type_implementation_defined")
    if not t["signed"]:
        return value % (1 << t["bits"])
    lo, hi = type_range(t)
    if not lo <= value <= hi:
        raise Unresolved("implementation_defined_signed_conversion")
    return value


def literal(text: str, widths: dict[str, int], mode: str = "f64") -> tuple[int | float, dict[str, Any]]:
    """Value and C type of an integer (C11 6.4.4.1 candidate lists) or floating (``F`` = float, none = double)
    literal. A leading sign is applied as the unary operator it is."""
    fm = _FLOAT_RE.match(text.strip())
    if fm:
        if fm.group("suffix") in {"l", "L"}:
            raise Unresolved("long_double_unsupported")
        t = FLOAT if fm.group("suffix") in {"f", "F"} else DOUBLE
        exact = Fraction(fm.group("number"))
        # Round the *decimal* once (decimal → double → float could round twice). Round-to-nearest is assumed for
        # literals (C11 6.4.4.2p3 lets it be implementation-defined; IEC 60559 / Annex F targets round to nearest).
        value = float(exact) if mode == "wide" or t is DOUBLE and mode != "f32" else _nearest_f32(exact)
        return (-value if fm.group("sign") == "-" else value), t
    m = _LITERAL_RE.match(text.strip())
    if not m:
        raise Unresolved("unsupported_literal:" + text.strip()[:20])
    digits, suffix = m.group("digits"), (m.group("suffix") or "").lower()
    value = int(digits, 16) if digits[:2].lower() == "0x" else (int(digits, 8) if digits.startswith("0") and len(digits) > 1 else int(digits))
    decimal = not digits.startswith("0") or digits == "0"
    unsigned, longs = "u" in suffix, suffix.count("l")
    order = [("int", True), ("int", False), ("long", True), ("long", False), ("long long", True), ("long long", False)]
    start = {0: 0, 1: 2, 2: 4}[longs]
    candidates = [c for c in order[start:] if (not unsigned or not c[1]) and (unsigned or not decimal or c[1])]
    for kind, signed in candidates:
        t = ctype(kind, signed, widths)
        lo, hi = type_range(t)
        if lo <= value <= hi:
            if m.group("sign") == "-":
                return arith("-", None, (value, t), widths)
            return value, t
    raise Unresolved("literal_out_of_range:" + text.strip()[:20])


def arith(op: str, left: tuple[Any, dict] | None, right: tuple[Any, dict], widths: dict[str, int],
          mode: str = "f64") -> tuple[Any, dict[str, Any]]:
    """One C operation on typed values. Undefined or implementation-defined behavior is refused.

    Floating operands support ``+ - * /`` and comparisons only, rounded to the operand type in ``mode``.
    """
    if is_float(right[1]) or (left is not None and is_float(left[1])):
        return _float_arith(op, left, right, widths, mode)
    if right[1].get("enum") or (left is not None and left[1].get("enum")):
        return _enum_arith(op, left, right, widths, mode)
    if left is None:  # unary
        v, t = right
        t = promote(t, widths)
        v = convert(v, t)
        if op == "+":
            return v, t
        if op == "-":
            return _fit(-v, t), t
        if op == "~":
            return convert(~v, t) if not t["signed"] else _fit(~v, t), t
        if op == "!":
            return int(not v), ctype("int", True, widths)
        raise Unresolved("unsupported_operator:" + op)
    (a, ta), (b, tb) = left, right
    int_t = ctype("int", True, widths)
    if op in {"&&", "||"}:
        return int(bool(a) and bool(b)) if op == "&&" else int(bool(a) or bool(b)), int_t
    if op in {"<<", ">>"}:
        t = promote(ta, widths)
        a = convert(a, t)
        if b < 0 or b >= t["bits"]:
            raise Unresolved("shift_count_out_of_range")
        if op == "<<":
            if t["signed"] and (a < 0 or (a << b) > type_range(t)[1]):
                raise Unresolved("signed_left_shift_overflow")
            return convert(a << b, t), t
        if t["signed"] and a < 0:
            raise Unresolved("implementation_defined_right_shift")
        return a >> b, t
    t = usual_conversion(ta, tb, widths)
    a, b = convert(a, t), convert(b, t)
    if op in {"<", "<=", ">", ">=", "==", "!="}:
        return int({"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b, "==": a == b, "!=": a != b}[op]), int_t
    if op in {"/", "%"}:
        if b == 0:
            raise Unresolved("division_by_zero")
        if t["signed"] and b == -1 and a == type_range(t)[0]:
            raise Unresolved("signed_overflow")  # INT_MIN / -1 and INT_MIN % -1 are both undefined (C11 6.5.5p6)
        q = abs(a) // abs(b) * (1 if (a >= 0) == (b >= 0) else -1)
        return (_fit(q, t) if op == "/" else _fit(a - b * q, t)), t
    result = {"+": a + b, "-": a - b, "*": a * b, "&": a & b, "|": a | b, "^": a ^ b}.get(op)
    if result is None:
        raise Unresolved("unsupported_operator:" + op)
    return _fit(result, t), t


def enum_candidates(widths: dict[str, int]) -> list[dict[str, Any]]:
    """The types an implementation may give an enumeration (C11 6.7.2.2p4: ``char``, a signed or an unsigned integer
    type able to hold every member) as this model enumerates them — the oracle's `_Interp.enum_candidates`."""
    return [ctype(k, s, widths) for k, s in (("int", True), ("int", False), ("char", True), ("char", False))]


def _enum_arith(op, left, right, widths, mode):
    """(R67 review W-R3-2) An operation on an enumeration-typed operand (``E_ONE - 2`` with ``#define E_ONE ((ETYPE)1)``):
    its value is the program's only if every permitted type gives the same value and signedness — 1 - 2 is -1 for int
    and UINT_MAX for unsigned int. The oracle's `enum_dual` judgment, for constant expressions."""
    results = set()
    refusals = set()
    got = None
    for c in enum_candidates(widths):
        lhs = None if left is None else (left[0], c if left[1].get("enum") else left[1])
        rhs = (right[0], c if right[1].get("enum") else right[1])
        try:
            got = arith(op, lhs, rhs, widths, mode)
        except Unresolved as exc:
            refusals.add(str(exc))
            continue
        results.add((got[0], got[1]["kind"], got[1]["signed"]))
    if refusals and not results and len(refusals) == 1:
        raise Unresolved(next(iter(refusals)))       # (review round 4 I-2) every choice refuses alike: ``E_ONE / 0``
    if refusals or len(results) != 1:
        raise Unresolved("enum_underlying_type_implementation_defined")
    return got


def _f32_bits(x: float) -> int:
    return struct.unpack("<I", struct.pack("<f", x))[0]


def _nearest_f32(exact: Fraction) -> float:
    """The IEEE single value nearest the exact rational (ties to even) — one rounding, not two."""
    try:
        guess = struct.unpack("<f", struct.pack("<f", float(exact)))[0]
    except OverflowError as exc:
        raise Unresolved("float_overflow") from exc
    candidates = {guess}
    bits = _f32_bits(guess)
    for delta in (-1, 1):
        neighbour = bits + delta
        if 0 <= neighbour < 0x7F800000 or 0x80000000 <= neighbour < 0xFF800000:
            candidates.add(struct.unpack("<f", struct.pack("<I", neighbour))[0])
    return min(candidates, key=lambda c: (abs(Fraction(c) - exact), _f32_bits(c) & 1))


def _float_arith(op, left, right, widths, mode):
    if left is None:
        v, t = right
        if op in {"+", "-"}:
            return (v if op == "+" else -v), t
        if op == "!":
            return int(not v), ctype("int", True, widths)
        raise Unresolved("unsupported_float_operator:" + op)
    (a, ta), (b, tb) = left, right
    t = ta if is_float(ta) and (not is_float(tb) or ta["rank"] >= tb["rank"]) else tb
    a, b = convert(a, t, mode), convert(b, t, mode)
    if op in {"<", "<=", ">", ">=", "==", "!="}:
        return int({"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b, "==": a == b, "!=": a != b}[op]), ctype("int", True, widths)
    if op == "/" and b == 0:
        raise Unresolved("division_by_zero")
    if op not in {"+", "-", "*", "/"}:
        raise Unresolved("unsupported_float_operator:" + op)
    return _round_float({"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else 0.0}[op], t, mode), t


def _fit(value: int, t: dict[str, Any]) -> int:
    if not t["signed"]:
        return value % (1 << t["bits"])
    lo, hi = type_range(t)
    if not lo <= value <= hi:
        raise Unresolved("signed_overflow")
    return value


# ── Project scan ────────────────────────────────────────────────────────────────────────────────

def _text(node, raw: bytes) -> str:
    return raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _function_name(fn, raw):
    d = fn.child_by_field_name("declarator")
    while d is not None and d.type != "function_declarator":
        d = d.child_by_field_name("declarator")
    ident = d.child_by_field_name("declarator") if d is not None else None
    return (_text(ident, raw) if ident is not None and ident.type == "identifier" else ""), d


def _defines_guard(node, guard, raw):
    return node.type == "preproc_def" and node.child_by_field_name("value") is None \
        and _text(node.child_by_field_name("name"), raw) == _text(guard, raw)


def _directive_keyword(node, raw) -> str:
    """``ifndef`` for ``#ifndef X`` and for ``#  ifndef X`` alike (C allows blanks after ``#``; R62)."""
    m = re.match(r"\s*#\s*(\w+)", _text(node, raw))
    return m.group(1) if m else ""


def _guard_body(root, raw):
    """Children of a translation unit, looking through an include guard. Two forms are guards (their body is
    unconditional for the first inclusion, which is the one that defines anything):

    * ``#ifndef X / #define X ... #endif``
    * ``#ifdef X / #error ... / #else / #define X ... #endif`` (re-inclusion is a hard error)
    """
    items = [c for c in root.named_children if c.type != "comment"]
    if len(items) != 1 or items[0].type != "preproc_ifdef":
        return root.named_children
    guard = items[0].child_by_field_name("name")
    inner = [c for c in items[0].named_children if c.type != "comment" and c != guard]
    if guard is None or not inner:
        return root.named_children
    if _directive_keyword(items[0], raw) == "ifndef":   # ``#  ifndef`` too (R62 review I4)
        if _defines_guard(inner[0], guard, raw) and not any(
                c.type in {"preproc_else", "preproc_elif", "preproc_elifdef"} for c in inner):
            return inner[1:]
        return root.named_children
    if len(inner) == 2 and inner[0].type == "preproc_call" and inner[1].type == "preproc_else" \
            and _text(inner[0].child_by_field_name("directive"), raw).strip() == "#error":
        body = [c for c in inner[1].named_children if c.type != "comment"]
        if body and _defines_guard(body[0], guard, raw):
            return body[1:]
    return root.named_children


def strip_comments(text: str) -> str:
    """Remove ``/* */`` and ``//`` comments outside string/char literals (a ``#define`` value runs to end of line)."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            j = i + 1
            while j < n and text[j] != ch:
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            out.append(" ")
            i = n if j < 0 else j + 2
        elif text.startswith("//", i):
            break
        else:
            out.append(ch)
            i += 1
    return " ".join("".join(out).split())


def _items(nodes, raw, conditional=False):
    """(node, conditional) for top-level items; ``#if`` blocks contribute their contents as conditional.

    Parse-recovery containers are looked into: vendor syntax (``__attribute__ ((aligned (4))) = {...};``) leaves
    an ``ERROR`` node and a top-level ``compound_statement`` that swallows every function after it (HDPDM01
    ``Monitor_ADC.c``: 7 functions). Those functions are still compiled; their writes and address-of uses must
    count (R81 review W5)."""
    for n in nodes:
        if n.type in {"preproc_if", "preproc_ifdef", "preproc_else", "preproc_elif", "preproc_elifdef"}:
            yield from _items(n.named_children, raw, True)
        elif n.type in {"ERROR", "compound_statement"}:
            yield from _items(n.named_children, raw, conditional)
        elif n.type == "linkage_specification" and (n.child_by_field_name("body") or n).type == "declaration_list":
            # (R63) ``extern "C" { … }`` (under ``#ifdef __cplusplus``): to a C compiler, file-level declarations
            yield from _items(n.child_by_field_name("body").named_children, raw, conditional)
        else:
            yield n, conditional


def _declarators(decl):
    typ = decl.child_by_field_name("type")
    for child in decl.named_children:
        if child != typ and child.type not in {"storage_class_specifier", "type_qualifier", "attribute_specifier", "ms_declspec_modifier", "comment"}:
            yield child


_BARE_DEFINE_RE = re.compile(rb"(?m)^([ \t]*#[ \t]*define[ \t]+[A-Za-z_]\w*(?:\([^)\n]*\))?)([ \t]+)(\r?\n)")


def _parse_safe(raw: bytes) -> bytes:
    """``raw`` with each value-less ``#define NAME`` + trailing blanks written as ``#define NAME`` + newline + those
    blanks at the start of the next line — same length, the same bytes everywhere else. tree-sitter-c reads the blanks
    as extras and then takes the *next line* as the macro's value (KJPDS02_PV / HDPDM01 ``lin_cfg.h``:
    ``#define _LIN_CFG_H_ `` swallowed ``#include "lin_hw_cfg.h"``, so the walk included that header late — R62 review
    round 5 C-4)."""
    return _BARE_DEFINE_RE.sub(rb"\1\3\2", raw)


# (R63) comments, literals and directive lines of a file, to be masked before looking for vendor syntax in its code
_LEXEME_RE = re.compile(rb'//(?:[^\n\\]|\\\r?\n|\\.)*|/\*.*?(?:\*/|\Z)|"(?:\\\r?\n|\\.|[^"\\\n])*"?'
                        rb"|'(?:\\\r?\n|\\.|[^'\\\n])*'?", re.S)
_DIRECTIVE_LINE_RE = re.compile(rb"(?m)^[ \t]*#(?:[^\n]*\\\r?\n)*[^\n]*")
_VENDOR_RE = re.compile(rb"@[ \t]*(?:0[xX][0-9A-Fa-f]+|[0-9]+)[uUlL]*|\b__attribute__\b|\b__interrupt\b|\b__far\b|\b__near\b")


def _code_mask(raw: bytes) -> bytes:
    """``raw`` with comments, string / character literals and directive lines as blanks (newlines kept)."""
    def blank(m):
        return re.sub(rb"[^\r\n]", b" ", m.group(0))
    return _DIRECTIVE_LINE_RE.sub(blank, _LEXEME_RE.sub(blank, raw))


# (R63 review round 1 W3) GCC attributes that place, keep or annotate an object or function without changing a value the
#   model computes — ``mode(QI)`` · ``vector_size`` · ``packed`` (a width, a layout) are not among them and stay unread
#   — nor ``weak``: a strong definition elsewhere replaces it at link time (review round 2 I1)
_NEUTRAL_ATTRIBUTES = frozenset({"aligned", "section", "used", "unused", "noreturn", "noinline", "always_inline",
                                 "deprecated", "visibility", "cold", "hot", "nonnull", "warn_unused_result", "interrupt"})


def _attributes_value_neutral(inner: str) -> bool:
    """Is every attribute of an ``__attribute__((…))`` list (its inner text) one of `_NEUTRAL_ATTRIBUTES`?"""
    depth, start, names = 0, 0, []
    for i, ch in enumerate(inner + ","):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            names.append(inner[start:i].strip())
            start = i + 1
    for item in names:
        m = re.match(r"([A-Za-z_]\w*)", item)
        if not m or m.group(1).strip("_") not in _NEUTRAL_ATTRIBUTES:
            return False
    return bool(names)


def _reading_blanks(raw: bytes) -> list[tuple[int, int, str]]:
    """(R63) ``(start, end, kind)`` of the target compiler's syntax that tree-sitter-c does not know and that changes no
    value the model computes — read as blanks, so the declaration or function around it parses:

    * ``address_placement`` — ``@0x000002C0`` after a declarator (CodeWarrior: ``extern volatile PTPSTR _PTP @0x2C0;``;
      every register of ``IO_Map.h`` was an ERROR, KJPDS02_PV 719 · HDPDM01 359);
    * ``attribute`` — GCC ``__attribute__ ((aligned (4)))`` (balanced parentheses);
    * ``interrupt`` — the ``__interrupt`` function specifier (``__interrupt void SCI0_ISR(void)`` was unread);
    * ``far_near`` — the ``__far`` / ``__near`` pointer qualifiers (memory model, not value).

    Outside comments, literals and directive lines. ``asm`` is never blanked: what it does is not value-neutral."""
    mask = _code_mask(raw)
    out: list[tuple[int, int, str]] = []
    for m in _VENDOR_RE.finditer(mask):
        word = m.group(0)
        if word.startswith(b"@"):
            out.append((m.start(), m.end(), "address_placement"))
        elif word == b"__attribute__":
            i = m.end()
            while i < len(mask) and mask[i:i + 1] in (b" ", b"\t", b"\r", b"\n"):
                i += 1
            if mask[i:i + 2] != b"((":
                continue
            depth, j = 0, i
            while j < len(mask):
                ch = mask[j:j + 1]
                depth += 1 if ch == b"(" else -1 if ch == b")" else 0
                j += 1
                if depth == 0:
                    break
            if depth == 0 and _attributes_value_neutral(mask[i + 2:j - 2].decode("utf-8", "replace")):
                out.append((m.start(), j, "attribute"))
        elif word == b"__interrupt":
            out.append((m.start(), m.end(), "interrupt"))
        else:
            out.append((m.start(), m.end(), "far_near"))
    return out


def reading_text(raw: bytes) -> tuple[bytes, dict[str, int]]:
    """(R63) The bytes every reader of a C file parses — the project context (`_scan_file`) and every consumer of a unit
    (`project_body_conditionals`) alike, so a declaration's position means the same thing to both: `_parse_safe`, then
    the vendor syntax of `_reading_blanks` as blanks. Same length, same newlines. Returns the bytes and the blanks per
    kind."""
    raw = _parse_safe(raw)
    blanks = _reading_blanks(raw)
    if not blanks:
        return raw, {}
    counts: dict[str, int] = {}
    for _a, _b, kind in blanks:
        counts[kind] = counts.get(kind, 0) + 1
    return _blanked(raw, [(a, b) for a, b, _k in blanks]), counts


def _scan_file(path: str, text: str, parser) -> dict[str, Any]:
    raw, blanked = reading_text(text.encode("utf-8"))
    root = parser.parse(raw).root_node
    walk = _file_walk(root, raw)
    rec: dict[str, Any] = {"path": path, "includes": walk["includes"], "system_includes": walk["system_includes"],
                           "typedefs": {}, "macros": {}, "undefs": walk["undefs"],
                           "enums": {}, "enumerators": {}, "globals": {}, "functions": {}, "parse_error": root.has_error,
                           "structs": {},   # (R39) struct/union bodies by key and typedef name (`_collect_struct`)
                           "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                           # (R63) read from the directive lines, not the parser's directive nodes (`_file_walk`)
                           "events": walk["events"],
                           # (R17) identifiers of #if/#ifdef/#elif inside function bodies (pp_condition decides them)
                           "body_condition_names": _body_condition_names(root, raw),
                           # (R62 review rounds 2-4) #define / #undef / #include lines the file-level walk never reads —
                           # in function bodies — yet the compiler applies them where they stand
                           "stray_directives": {"directives": walk["strays"]},
                           # (R63) how the file was read: vendor syntax read as blanks (`reading_text`), the parse errors
                           # left (`_parse_error_leaves`), file-level directive lines the parser's tree did not show
                           # (read from the lexer all the same) and unbalanced conditional lines
                           "reading": {"blanked": blanked, "errors": _parse_error_leaves(root, raw, walk["spans"]),
                                       "directives_beyond_tree": walk["beyond_tree"],
                                       "spliced_defines": walk["spliced_defines"],
                                       "unbalanced_brace_macros": walk["unbalanced_brace_macros"][:20],
                                       "unbalanced_directives": walk["problems"]},
                           # ``&x`` anywhere in the file — file-scope initializers (``{&g_cnt}``) included (review C3d).
                           "address_taken": sorted(_address_taken(root, raw)),
                           # (R64 review round 4 W-1) ``(T)&x`` — the grammar reads a bitwise and; the closure decides
                           #   with the tree's type names whether ``T`` is a type
                           "paren_amp": _paren_amp(root, raw),
                           # (R64) file-scope objects' declared kinds and initializers, unread regions (`pointer_flow`)
                           "flow": pointer_flow.file_facts(root, raw, path)}
    for d in walk["defines"]:
        entry = {"body": d["body"], "line": d["line"], "pos": d["pos"], "conditional": d["conditional"],
                 "function_like": d["function_like"]}
        if d["function_like"]:
            # Parameter names let a consumer expand an invocation (R2b source oracle); ``...`` is kept as a token.
            entry["params"] = d["params"]
        rec["macros"].setdefault(d["name"], []).append(entry)
    for node, conditional in _items(_guard_body(root, raw), raw):
        line = node.start_point[0] + 1
        pos = node.start_byte
        if node.type in _PREPROC_LINE_NODES:
            continue   # (R63) directives come from `_file_walk`
        elif node.type == "type_definition":
            typ = node.child_by_field_name("type")
            base = " ".join(_text(c, raw) for c in node.named_children if c.type == "type_qualifier" or c == typ)
            _collect_enum(typ, raw, rec, conditional, line, pos)
            aggregate = typ is not None and typ.type in {"struct_specifier", "union_specifier"}
            # the new name is a ``type_identifier`` — or a ``primitive_type`` when the grammar knows the name
            # (``typedef unsigned char bool;``, ``typedef signed char int8_t;`` in KJPDS02 PE_Types.h: dropped before
            # R16b, so ``bool`` stayed ``_Bool`` and ``uint8_t`` stayed rank-unknown)
            def is_name(d):   # a primitive only for the names a project may typedef (a misparse of
                return d != typ and (d.type == "type_identifier" or   # ``typedef FAR unsigned char X;`` is no ``char``)
                                     (d.type == "primitive_type" and _text(d, raw) in _PROJECT_MAY_TYPEDEF))
            if aggregate:
                _collect_struct(typ, raw, rec, line, pos, conditional,
                                names=[_text(d, raw) for d in node.named_children if is_name(d)],
                                quals={_text(c, raw) for c in node.named_children if c.type == "type_qualifier"})
            for d in node.named_children:
                if is_name(d) and aggregate:
                    rec["typedefs"].setdefault(_text(d, raw), []).append({"base": "", "shape": "struct", "line": line,
                                                                         "pos": pos, "conditional": conditional})
                elif is_name(d):
                    shape = "enum" if typ is not None and typ.type == "enum_specifier" else "scalar"
                    enum_tag = ""
                    if shape == "enum":
                        tag = typ.child_by_field_name("name")
                        enum_tag = "enum " + _text(tag, raw) if tag is not None else f"enum @{path}:{typ.start_byte}"
                    rec["typedefs"].setdefault(_text(d, raw), []).append({
                        "base": enum_tag or " ".join(_text(typ, raw).split()) if typ is not None else "",
                        "volatile": "volatile" in base.split(), "shape": shape, "line": line, "pos": pos,
                        "conditional": conditional})
                elif d != typ and d.type not in {"type_qualifier", "comment"}:
                    name = _declared_name(d, raw)
                    if name:
                        rec["typedefs"].setdefault(name, []).append({"base": "", "shape": d.type, "line": line,
                                                                     "pos": pos, "conditional": conditional})
        elif node.type == "enum_specifier":
            _collect_enum(node, raw, rec, conditional, line, pos)
        elif node.type in {"struct_specifier", "union_specifier"}:
            _collect_struct(node, raw, rec, line, pos, conditional)   # (R39) ``struct tag { … };``
        elif node.type == "declaration":
            typ = node.child_by_field_name("type")
            _collect_enum(typ, raw, rec, conditional, line, pos)
            struct_key = _collect_struct(typ, raw, rec, line, pos, conditional)   # (R39) "" unless a struct/union
            quals = {_text(c, raw) for c in node.named_children if c.type in {"type_qualifier", "storage_class_specifier"}}
            if typ is not None and typ.type in {"struct_specifier", "union_specifier"}:
                typename = "struct"
            elif typ is not None and typ.type == "enum_specifier":
                tag = typ.child_by_field_name("name")
                typename = "enum " + _text(tag, raw) if tag is not None else f"enum @{path}:{typ.start_byte}"
            else:
                typename = " ".join(_text(typ, raw).split()) if typ is not None else ""
            for d in _declarators(node):
                target = d.child_by_field_name("declarator") if d.type == "init_declarator" else d
                if _declares_function(target):
                    name = _declared_name(target, raw)
                    if name:
                        rec.setdefault("prototypes", []).append(name)
                    continue
                name = _declared_name(target, raw) if target is not None else ""
                if not name:
                    continue
                shape = "scalar" if target.type == "identifier" else target.type.replace("_declarator", "")
                dims, inner = [], target
                while inner is not None and inner.type == "array_declarator":
                    size = inner.child_by_field_name("size")
                    dims.append(strip_comments(_text(size, raw)).strip() if size is not None else "")
                    inner = inner.child_by_field_name("declarator")
                if dims and (inner is None or inner.type != "identifier"):
                    shape = "array_of_" + (inner.type.replace("_declarator", "") if inner is not None else "unknown")
                init_node = d.child_by_field_name("value") if d.type == "init_declarator" else None
                init_text = strip_comments(_text(init_node, raw)) if init_node is not None else ""
                for call in (_walk(init_node) if init_node is not None else ()):
                    f = call.child_by_field_name("function") if call.type == "call_expression" else None
                    if f is not None and f.type == "identifier":
                        args = call.child_by_field_name("arguments")
                        rec.setdefault("file_call_args", {}).setdefault(_text(f, raw), []).extend(
                            re.findall(r"\b[A-Za-z_]\w*\b", _text(args, raw)) if args is not None else [])
                rec["globals"].setdefault(name, []).append({
                    "type": typename, "shape": shape, "line": line, "pos": pos, "conditional": conditional,
                    "struct_key": struct_key,
                    "extern": "extern" in quals, "static": "static" in quals,
                    "volatile": "volatile" in quals, "const": "const" in quals,
                    "initialized": d.type == "init_declarator",
                    "init": init_text[:400],
                    # Array dimensions outermost first (``U8 a[2][3]`` → ["2", "3"]; ``extern U8 a[]`` → [""]). A const
                    # array's full initializer (a lookup table) is kept up to a budget; beyond it the value is unknown.
                    "dims": list(reversed(dims)) if dims else [],
                    "array_init": init_text if dims and "const" in quals and len(init_text) <= _ARRAY_INIT_BUDGET else "",
                    "array_init_truncated": bool(dims and "const" in quals and len(init_text) > _ARRAY_INIT_BUDGET)})
        elif node.type == "function_definition":
            name, _ = _function_name(node, raw)
            if name:
                rec["functions"].setdefault(name, []).append({**_function_effects(node, raw), "line": line, "pos": pos,
                                                              "pointer_params": _pointer_params(node, raw),
                                                              "conditional": conditional,
                                                              # (R64) stores · calls · returns for the points-to analysis
                                                              "flow": pointer_flow.function_facts(node, raw, path)})
    return rec


def _cast_hidden_call(n, raw) -> str:
    """The callee a function-type "cast" is (``(F())`` read as a cast to ``F()``), or ""."""
    t = n.child_by_field_name("type")
    if t is None:
        return ""
    decl = t.child_by_field_name("declarator")
    if decl is None or decl.type != "abstract_function_declarator" or decl.child_by_field_name("declarator") is not None:
        return ""
    spec = t.child_by_field_name("type")
    return _text(spec, raw) if spec is not None and spec.type == "type_identifier" else "<indirect>"


def _body_condition_names(root, raw) -> list[str]:
    names: set[str] = set()
    for fn in (n for n in _walk(root) if n.type == "function_definition"):
        for n in _walk(fn):
            if n.type in {"preproc_if", "preproc_ifdef", "preproc_elif", "preproc_elifdef"}:
                for part in (n.child_by_field_name("condition"), n.child_by_field_name("name")):
                    if part is not None:
                        names.update(_text(x, raw) for x in _walk(part) if x.type == "identifier")
    names.discard("defined")
    return sorted(names)


def _call_keyword(node, raw) -> str:
    """The keyword of a ``preproc_call`` (``undef`` for ``#undef`` and ``#  undef`` alike)."""
    return "".join(_text(node.child_by_field_name("directive"), raw).split()).lstrip("#")


def _event_directive_lines(nodes, raw, out: dict[int, str] | None = None) -> dict[int, str]:
    """Row → keyword of each directive the parser's tree shows at file level (top level, #if arms, recovery containers)
    — what the walk read before R63; `_file_walk` counts the file-level lines beyond it (``directives_beyond_tree``).
    A row the lexer reads as another directive (``#un\\<NL>def``) is not one the tree showed."""
    out = {} if out is None else out
    for n in nodes:
        t = n.type
        if t == "preproc_include":
            out[n.start_point[0]] = "include"
        elif t in ("preproc_def", "preproc_function_def"):
            out[n.start_point[0]] = "define"
        elif t == "preproc_call":
            out[n.start_point[0]] = _call_keyword(n, raw)
        elif t in _IF_NODES:
            out[n.start_point[0]] = "if"
            cond, name, alt = n.child_by_field_name("condition"), n.child_by_field_name("name"), n.child_by_field_name("alternative")
            _event_directive_lines([c for c in n.named_children if c not in (cond, name, alt)], raw, out)
            if alt is not None:
                _event_directive_lines(alt.named_children if alt.type == "preproc_else" else [alt], raw, out)
        elif t in ("ERROR", "compound_statement"):
            _event_directive_lines(n.named_children, raw, out)
    return out


def _stray_directives(root, raw) -> dict[str, Any]:
    """``#define`` / ``#undef`` / ``#include`` lines of the file that the file-level walk (`_file_walk`) does not read:
    those inside a function body (this file's or a header's inline function), and a define / undef with no readable
    name (``op: "unreadable"`` — never "nothing there"). ``{"directives": [{"op", "name", "pos", "fn",
    "conditionals"}]}`` — ``fn`` is the start of the function definition it sits in, ``conditionals`` the conditional
    directive lines of the file before it. (R63: a file-level line the parser did not recognize — inside a struct
    declaration, in an ERROR — is no longer a stray: the walk reads every file-level line from the lexer.)"""
    return {"directives": _file_walk(root, raw)["strays"]}


def _function_spans(root) -> list[tuple[int, int]]:
    """The outermost function definitions of a tree as ``(start, end)``, sorted (a definition the parser nested in
    another's recovery counts as the outer one's)."""
    spans: list[tuple[int, int]] = []
    for a, b in sorted((n.start_byte, n.end_byte) for n in _walk(root) if n.type == "function_definition"):
        if spans and a < spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], b))
        else:
            spans.append((a, b))
    return spans


_PREPROC_LINE_NODES = frozenset({"preproc_include", "preproc_def", "preproc_function_def", "preproc_call"})


def _decl_positions(nodes, out: list[int]) -> list[int]:
    """Start of every file-level item that is not a directive: through #if arms, parse-recovery containers (`_items`)
    and ``extern "C" { … }`` bodies (R63: ``#ifdef __cplusplus`` around ``extern "C" {`` — the C compiler sees the
    declarations inside as file-level ones; KJPDS02_PV ``HKMC_SecureFlash.h``)."""
    for n in nodes:
        t = n.type
        if t == "comment" or t in _PREPROC_LINE_NODES:
            continue
        if t in _IF_NODES or t == "preproc_else":
            cond, name, alt = n.child_by_field_name("condition"), n.child_by_field_name("name"), n.child_by_field_name("alternative")
            _decl_positions([c for c in n.named_children if c not in (cond, name, alt)], out)
            if alt is not None:
                _decl_positions([alt], out)
        elif t in ("ERROR", "compound_statement"):
            _decl_positions(n.named_children, out)
        elif t == "linkage_specification" and (n.child_by_field_name("body") or n).type == "declaration_list":
            _decl_positions(n.child_by_field_name("body").named_children, out)
        else:
            out.append(n.start_byte)
    return out


def _lexed_if(keyword: str, argument: str, line: int) -> dict[str, Any]:
    ev: dict[str, Any] = {"op": "if", "then": [], "else": [], "line": line}
    if keyword in ("ifdef", "ifndef", "elifdef", "elifndef"):
        m = re.match(r"([A-Za-z_]\w*)", argument)
        ev["defined"] = m.group(1) if m else ""
        ev["negate"] = keyword in ("ifndef", "elifndef")
    else:
        ev["expr"] = argument
    return ev


def _lexed_define(argument: str) -> dict[str, Any] | None:
    """``#define`` argument (splices removed, comments as blanks) → name, body, function-likeness and parameters.
    Function-like only when ``(`` follows the name with nothing between (C11 6.10.3p3 — a comment is a blank)."""
    m = re.match(r"([A-Za-z_]\w*)\(([^)]*)\)\s*(.*)", argument, re.S)
    if m:
        params = [p.strip() for p in m.group(2).split(",")]
        return {"name": m.group(1), "body": m.group(3).strip(), "function_like": True,
                "params": [p for p in params if re.fullmatch(r"[A-Za-z_]\w*|\.\.\.", p)]}
    m = re.match(r"([A-Za-z_]\w*)\s*(.*)", argument, re.S)
    if m and not argument[len(m.group(1)):].startswith("("):
        return {"name": m.group(1), "body": m.group(2).strip(), "function_like": False}
    return None


def _file_walk(root, raw) -> dict[str, Any]:
    """(R63) The preprocessor's view of a file, read from its directive lines (`_directive_lines` — splices, comments and
    literals known) instead of the parser's directive nodes. tree-sitter shows a directive only where its grammar puts
    one: a ``#define`` among the members of a register struct (Processor Expert ``IO_Map.h`` — KJPDS02_PV 2,114 ·
    HDPDM01 1,057), a multi-line macro with a comment before a line splice (pin macros ``X_GetVal()``) or one inside
    ``extern "C" {`` never reached the macro table, and a multi-line body kept its backslashes (``l_u8_rd_…()`` LIN
    signal readers: unparseable, 576 · 201 definitions). Every file-level line is read here, in order; declarations come
    from the tree (`_decl_positions`) and go into the group open at their start.

    A line inside a function body is not file-level: a conditional group wholly inside one function is the function's
    own (`pp_condition` / `project_body_conditionals`), its #define / #undef / #include are ``strays`` (`_effective_strays`).
    A group a function does not close (``#if`` choosing between two function heads) is read at file level, so the file's
    groups stay balanced.

    Returns ``events`` (as `preprocess_unit` walks them), ``defines`` (macro entries with ``pos`` / ``line`` /
    ``conditional``), ``undefs``, ``includes`` · ``system_includes``, ``strays`` and ``problems`` (unbalanced lines)."""
    hashes: list[int] = []
    lines = _directive_lines(raw, 0, len(raw), hashes)
    newlines = [m.start() for m in re.finditer(rb"\n", raw)]
    spans = _function_spans(root)
    span_starts = [a for a, _b in spans]

    def function_of(pos: int) -> int:
        k = bisect.bisect_right(span_starts, pos) - 1
        return spans[k][0] if k >= 0 and pos < spans[k][1] else -1

    recs = [{"pos": h, "end": end, "keyword": kw, "argument": arg, "fn": function_of(h),
             "line": bisect.bisect_left(newlines, h) + 1} for (_s, end, kw, arg), h in zip(lines, hashes, strict=True)]
    # groups a function body does not balance on its own are read at file level
    open_in: dict[int, int] = {}
    unbalanced: set[int] = set()
    for r in recs:
        fn, kw = r["fn"], r["keyword"]
        if fn < 0 or kw not in _GROUP_DIRECTIVES:
            continue
        depth = open_in.get(fn, 0)
        if kw in ("if", "ifdef", "ifndef"):
            depth += 1
        elif kw == "endif":
            depth -= 1
        elif depth == 0:
            unbalanced.add(fn)
        if depth < 0:
            unbalanced.add(fn)
        open_in[fn] = depth
    unbalanced |= {fn for fn, depth in open_in.items() if depth}
    strays: list[dict[str, Any]] = []
    file_level: list[dict[str, Any]] = []
    conditionals = 0   # (R62 round 5 F-D) conditional directive lines met so far: a local macro has none between
    for r in recs:
        kw = r["keyword"]
        if kw in _GROUP_DIRECTIVES:
            conditionals += 1
            if r["fn"] < 0 or r["fn"] in unbalanced:
                file_level.append(r)
            continue
        if kw not in ("define", "undef", "include", "error"):
            continue
        named = re.match(r"([A-Za-z_]\w*)", r["argument"])
        if kw in ("define", "undef") and (not named or (kw == "define" and _lexed_define(r["argument"]) is None)):
            strays.append({"op": "unreadable", "name": "", "pos": r["pos"], "fn": r["fn"], "conditionals": conditionals})
            continue
        if r["fn"] >= 0:
            if kw != "error":
                strays.append({"op": kw, "name": (r["argument"].strip().strip('"<>') if kw == "include"
                                                  else named.group(1)),
                               "pos": r["pos"], "fn": r["fn"], "conditionals": conditionals})
                if kw == "define":   # (R64 review round 3 W3) what a use of it does — the pointer flow reads it
                    strays[-1]["body"] = ((_lexed_define(r["argument"]) or {}).get("body") or "")[:2000]
            continue
        file_level.append(r)
    # declarations, minus anything the parser made of a directive line's text (a pin macro it could not read)
    spans_d = sorted((r["pos"], r["end"]) for r in recs)
    d_starts = [a for a, _b in spans_d]
    # file-level #define / #undef / #include lines the parser's own directive nodes did not show (read all the same)
    seen = _event_directive_lines(root.named_children, raw)
    beyond: dict[str, int] = {}
    for r in file_level:
        if r["keyword"] in ("define", "undef", "include") and seen.get(r["line"] - 1) != r["keyword"]:
            beyond[r["keyword"]] = beyond.get(r["keyword"], 0) + 1
    decls = []
    for pos in _decl_positions(root.named_children, []):
        k = bisect.bisect_right(d_starts, pos) - 1
        if k >= 0 and pos < spans_d[k][1]:
            continue
        decls.append(pos)
    items = sorted([(p, 0, None) for p in decls] + [(r["pos"], 1, r) for r in file_level], key=lambda x: (x[0], x[1]))
    events: list[dict[str, Any]] = []
    cur = events
    stack: list[dict[str, Any]] = []
    out: dict[str, Any] = {"events": events, "defines": [], "undefs": [], "includes": [], "system_includes": [],
                           "strays": strays, "problems": {}, "spans": spans_d, "beyond_tree": beyond,
                           "spliced_defines": 0, "unbalanced_brace_macros": []}

    def problem(kind):
        out["problems"][kind] = out["problems"].get(kind, 0) + 1

    for pos, _kind, r in items:
        if r is None:
            cur.append({"op": "decl", "pos": pos})
            continue
        kw, arg = r["keyword"], r["argument"]
        if kw in ("if", "ifdef", "ifndef"):
            ev = _lexed_if(kw, arg, r["line"])
            cur.append(ev)
            stack.append({"link": ev, "parent": cur, "in_else": False})
            cur = ev["then"]
        elif kw in ("elif", "elifdef", "elifndef"):
            if not stack or stack[-1]["in_else"]:
                problem("misplaced_" + kw)
                continue
            ev = _lexed_if(kw, arg, r["line"])
            stack[-1]["link"]["else"] = [ev]
            stack[-1]["link"] = ev
            cur = ev["then"]
        elif kw == "else":
            if not stack or stack[-1]["in_else"]:
                problem("misplaced_else")
                continue
            stack[-1]["in_else"] = True
            cur = stack[-1]["link"]["else"]
        elif kw == "endif":
            if not stack:
                problem("misplaced_endif")
                continue
            cur = stack.pop()["parent"]
        elif kw == "define":
            d = _lexed_define(arg)
            cur.append({"op": "define", "name": d["name"], "pos": pos})
            if b"\\\n" in raw[pos:r["end"]] or b"\\\r\n" in raw[pos:r["end"] + 1]:
                out["spliced_defines"] += 1
            braces = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', "", d["body"])   # not in literals (round 3 I5)
            if braces.count("{") != braces.count("}"):
                # (review round 2 W1) a macro that opens or closes a brace for its user: the parser reads the code it
                #   is used in with the brace missing — a function cut short, the rest of a file something else
                out["unbalanced_brace_macros"].append(d["name"])
            out["defines"].append({**d, "pos": pos, "line": r["line"], "depth": len(stack),
                                   "outer": (id(stack[0]["link"]), stack[0]["in_else"]) if stack else None})
        elif kw == "undef":
            name = re.match(r"([A-Za-z_]\w*)", arg).group(1)
            cur.append({"op": "undef", "name": name})
            out["undefs"].append(name)
        elif kw == "include":
            target = arg.strip()
            system = not target.startswith('"')
            if target.startswith('"') and '"' in target[1:]:
                target = target[1:target.index('"', 1)]
            elif target.startswith("<") and ">" in target:
                target = target[1:target.index(">")]
            cur.append({"op": "include", "name": target.strip('"<>'), "system": system})
            (out["system_includes"] if system else out["includes"]).append(target.strip('"<>'))
        else:   # error
            cur.append({"op": "error", "text": arg.strip()[:120]})
    if stack:
        problem("unterminated_group")
    # the include guard's group is no condition (`_guard_body`): the first inclusion is the one that defines anything
    guard, guard_define = None, -1
    if len(events) == 1 and events[0]["op"] == "if" and events[0].get("defined"):
        ev, g = events[0], events[0]["defined"]
        bodies = {d["pos"]: d for d in out["defines"]}

        def bare(e):
            d = bodies.get(e.get("pos")) if e.get("op") == "define" else None
            return d is not None and d["name"] == g and not d["body"] and not d["function_like"]
        if ev.get("negate") and ev["then"] and bare(ev["then"][0]) and not ev["else"]:
            guard, guard_define = (id(ev), False), ev["then"][0]["pos"]
        elif not ev.get("negate") and [e["op"] for e in ev["then"]] == ["error"] and ev["else"] and bare(ev["else"][0]):
            guard, guard_define = (id(ev), True), ev["else"][0]["pos"]
    for d in out["defines"]:
        depth = d.pop("depth") - (1 if guard is not None and d["outer"] == guard else 0)
        d.pop("outer")
        d["conditional"] = depth > 0
    if guard is not None:
        # the guard's own #define is an event, not a macro body (as `_guard_body` left it)
        out["defines"] = [d for d in out["defines"] if d["pos"] != guard_define]
    return out


_ASM_RE = re.compile(r"\b(?:__asm__|__asm|asm)\b")
_ASM_BLOCK_RE = re.compile(rb"\b(?:__asm__|__asm|asm)\b\s*\{")


def _asm_spans(raw: bytes) -> list[tuple[int, int]]:
    """(R63 review round 1 W1) ``asm { … }`` blocks of a file — their lines need not say ``asm`` (``DBNE D6, loop``)."""
    mask = _code_mask(raw)
    out = []
    for m in _ASM_BLOCK_RE.finditer(mask):
        depth, j = 0, m.end() - 1
        while j < len(mask):
            depth += {123: 1, 125: -1}.get(mask[j], 0)
            j += 1
            if depth == 0:
                break
        out.append((m.start(), j))
    return out


def _parse_error_leaves(root, raw, spans: list[tuple[int, int]]) -> dict[str, Any]:
    """(R63) The parse errors left after `reading_text` — innermost ERROR and MISSING nodes, by kind — and up to three
    ``(line, kind, text)`` samples. Kinds: ``directive`` (on a directive line — the walk reads it from the lexer),
    ``unnamed_bitfield`` (``U8 :1;`` — the grammar lacks unnamed bit-fields; a struct with bit-fields is never
    flattened, so nothing is lost), ``asm`` (inline assembly — its function stays unread), ``in_function`` (a function's
    own: `project_body_conditionals` reports it) and ``declaration`` (a file-level construct the reader does not know:
    the declarations it covers may be missing)."""
    if not root.has_error:
        return {}
    starts = [a for a, _b in spans]
    fn_spans = _function_spans(root)
    fn_starts = [a for a, _b in fn_spans]
    counts: dict[str, int] = {}
    samples: list[list[Any]] = []
    asm: list[tuple[int, int]] | None = None
    stack = [root]
    while stack:
        n = stack.pop()
        if not (n.has_error or n.is_missing):
            continue
        inner = [c for c in n.children if c.has_error or c.type == "ERROR" or c.is_missing]
        if n.type != "ERROR" and not n.is_missing:
            stack.extend(inner)
            continue
        if n.type == "ERROR" and any(c.type == "ERROR" for c in inner):
            stack.extend(inner)
            continue
        pos = n.start_byte
        line_start = raw.rfind(b"\n", 0, pos) + 1
        line_end = raw.find(b"\n", pos)
        line = raw[line_start:line_end if line_end >= 0 else len(raw)].decode("utf-8", "replace")
        k = bisect.bisect_right(starts, pos) - 1
        f = bisect.bisect_right(fn_starts, pos) - 1
        if asm is None:
            asm = _asm_spans(raw)
        a = bisect.bisect_right([s for s, _e in asm], pos) - 1
        text = _text(n, raw).strip()
        if k >= 0 and pos < spans[k][1]:
            kind = "directive"
        elif n.is_missing and n.type == "field_identifier" and n.parent is not None \
                and any(c.type == "bitfield_clause" for c in n.parent.children):
            kind = "unnamed_bitfield"
        elif _ASM_RE.search(line) or (a >= 0 and pos < asm[a][1]):
            kind = "asm"
        elif f >= 0 and pos < fn_spans[f][1]:
            kind = "in_function"
        elif n.is_missing and n.type in ("}", ")", "]"):
            # (review round 2 W1) a closing bracket the parser supplied: the structure was cut (a macro that hides a
            #   brace — ``#define CRIT_END() }`` — makes the rest of the file something else)
            kind = "lost_structure"
        elif n.is_missing:
            # (review round 1 W1) a name or ``;`` the parser supplied — ``typedef enum { … };`` with no name: the
            # construct around it was read
            kind = "missing_token"
        elif text in ("{", "}"):
            # the ``}`` closing ``extern "C" {`` under ``#ifdef __cplusplus`` is no brace a C compiler sees; any other is
            # lost structure (``#define IF_READY if (g_ready) {`` cuts the function it is used in — review round 2 W1)
            # (round 3 I2) only between a line opening a ``__cplusplus`` group and the ``#endif`` that closes it
            k2 = bisect.bisect_right(starts, pos) - 1
            prev = raw[spans[k2][0]:spans[k2][1]] if k2 >= 0 else b""
            after = raw[spans[k2 + 1][0]:spans[k2 + 1][1]] if k2 + 1 < len(spans) else b""
            opens = re.match(rb"\s*#\s*(?:ifdef\s+__cplusplus\b|if\s+defined\s*\(?\s*__cplusplus\b)", prev)
            kind = "cplusplus_brace" if opens and re.match(rb"\s*#\s*endif\b", after) else "unmatched_brace"
        else:
            kind = "declaration"
        counts[kind] = counts.get(kind, 0) + 1
        # up to three samples of each kind that may cost something (round 3 I3: an asm-heavy file hid its one
        #   unknown-declaration sample)
        if kind not in ("directive", "unnamed_bitfield", "cplusplus_brace") and \
                sum(1 for s in samples if s[1] == kind) < 3:
            samples.append([raw.count(b"\n", 0, pos) + 1, kind, " ".join(line.split())[:100]])
    return {"kinds": counts, "samples": samples}


def _effective_strays(strays: list[dict[str, Any]], defined: set[str], states: dict,
                      declared: dict[str, set[int]]) -> list[dict[str, Any]]:
    """The stray directives that change the unit's table. Left out: those in a function this configuration does not
    compile (a declaration event with no state — review round 3 I-3), and a local macro — a function body that defines
    a name the project defines nowhere else and #undefs it again before its end (KJPDS02_PV ``linuds.c``
    ``LINUDS_ECU_RESET_RESPONSE_DLC``): the table after the function is the one before it."""
    kept = [d for d in strays if not (d["fn"] >= 0 and d["fn"] in declared.get(d["file"], set())
                                       and states.get((d["file"], d["fn"])) is None)]
    by_fn: dict[tuple, list[dict[str, Any]]] = {}
    for d in kept:
        if d["fn"] >= 0:
            by_fn.setdefault((d["file"], d["fn"]), []).append(d)
    local: set[tuple] = set()
    for key, ds in by_fn.items():
        ds = sorted(ds, key=lambda x: x["pos"])
        for name in {d["name"] for d in ds if d["op"] in ("define", "undef") and d["name"]}:
            mine = [d for d in ds if d.get("name") == name and d["op"] in ("define", "undef")]
            # (round 5 F-D) an #undef under an in-body #if may not run: no conditional line between the two
            if mine[0]["op"] == "define" and mine[-1]["op"] == "undef" and name not in defined \
                    and mine[0].get("conditionals") == mine[-1].get("conditionals"):
                local.add((key, name))
    return [d for d in kept if not (d["fn"] >= 0 and ((d["file"], d["fn"]), d.get("name")) in local)]


def _file_if_on(files: dict[str, Any], unit_files: list[str], names: set[str], bodies: dict) -> str:
    """The first name of ``names`` a file-level #if of the unit's files tests — directly or through any definition's
    body (an alias ``#define ALIAS M_X``), else "". The walk chose that #if without the name: what it defined, which
    declarations it kept (`main_file_states`) and what stood under it may all be wrong (R62 review round 5 F-A)."""
    if not names:
        return ""
    by_name: dict[str, list[str]] = {}
    for d in bodies.values():
        by_name.setdefault(d.get("name") or "", []).append(str(d.get("body") or ""))
    for f in unit_files:
        stack = list((files.get(f) or {}).get("events") or [])
        while stack:
            ev = stack.pop()
            if ev["op"] != "if":
                continue
            stack.extend(ev["then"])
            stack.extend(ev["else"])
            seen: set[str] = set()
            pending = [ev.get("defined") or ""] + re.findall(r"[A-Za-z_]\w*", str(ev.get("expr") or ""))
            while pending and len(seen) < 4096:
                n = pending.pop()
                if n in seen:
                    continue
                seen.add(n)
                if n in names:
                    return n
                for body in by_name.get(n, ()):
                    pending.extend(re.findall(r"[A-Za-z_]\w*", body))
    return ""


def _declared_positions(rec: dict[str, Any]) -> set[int]:
    """Positions of every declaration event of a file, in any #if arm."""
    declared: set[int] = set()
    stack = list(rec.get("events") or [])
    while stack:
        ev = stack.pop()
        if ev["op"] == "decl":
            declared.add(int(ev["pos"]))
        elif ev["op"] == "if":
            stack.extend(ev["then"])
            stack.extend(ev["else"])
    return declared


def _names_a_file_changes(files: dict[str, Any], context: dict[str, Any], path: str) -> tuple[set[str], bool]:
    """Every name ``path`` (and what it includes, transitively) #defines or #undefines, in any arm or function body —
    and whether that walk was complete (a cap of 512 files, an include it could not resolve: review round 4 I-1)."""
    names: set[str] = set()
    seen: set[str] = set()
    pending = [path]
    complete = True
    while pending:
        if len(seen) >= 512:
            return names, False
        p = pending.pop()
        if p in seen or p not in files:
            continue
        seen.add(p)
        stack = list(files[p].get("events") or [])
        while stack:
            ev = stack.pop()
            if ev["op"] in ("define", "undef"):
                names.add(ev["name"])
            elif ev["op"] == "if":
                stack.extend(ev["then"])
                stack.extend(ev["else"])
            elif ev["op"] == "include" and not ev.get("system"):
                found = _resolve_include(context, p, ev["name"])
                if found:
                    pending.append(found)
                elif not _toolchain_header(context, ev["name"]):
                    complete = False
        stray = files[p].get("stray_directives") or {}
        names |= {d["name"] for d in stray.get("directives") or () if d.get("name") and d["op"] != "include"}
        if any(d["op"] in ("include", "unreadable") for d in stray.get("directives") or ()):
            complete = False
    return names, complete


def _address_taken(root, raw):
    names = set()
    for n in _walk(root):
        if n.type in {"unary_expression", "pointer_expression"} and _text(n, raw).lstrip().startswith("&") \
                and not _text(n, raw).lstrip().startswith("&&"):
            base = _base_identifier(n.child_by_field_name("argument"), raw)
            if base:
                names.add(base)
    return names


#: (R67) a unary ``-`` / ``+`` after a cast to a typedef name: the grammar does not know ``T`` is a type and reads
#   ``(S16)-1800`` as ``S16 - 1800``. KJPDS02_PV writes 23 (comparison limits ``s16t_Angle < ( S16 )-1800`` in motor
#   control, clamps, a macro ``((S16)-20)``, const lookup tables ``{ (S16)-4000, … }``) and each read as an undeclared name.
_CAST_UNARY_OPS = frozenset({"-", "+"})
#: a right operand the grammar grouped *under* the misparse: the cast's operand is then no subtree of it, so the text stays
#   unread — never regrouped by guess. (R67 review I-6) tree-sitter already parses ``(T)-a * b`` · ``/`` · ``%`` as a cast
#   (a multiplicative right side is never grouped under it); of these only ``(T)-a = b`` is reachable — the rest guard
#   a grammar change
_GROUPED_OPERANDS = frozenset({"binary_expression", "conditional_expression", "assignment_expression", "comma_expression"})


def paren_cast_unary(node, raw):
    """(R67) ``(T)-x`` / ``(T)+x`` as the grammar parses it — a binary ``-``/``+`` whose left operand is one parenthesized
    name: ``(name, sign, operand)`` (operand None when the right side is a grouped expression, `_GROUPED_OPERANDS`), else
    None. Whether ``T`` is a type — so whether this is a cast (C11 6.5.4) — is each reader's own judgment against its
    scope, like ``(T)(x)`` (`c_source_oracle.cast_call_operand`). Other shapes of the same ambiguity (``a - (T)-b`` parses
    as ``(a - (T)) - b``) keep the parenthesized name as an operand and stay unknown."""
    if node is None or node.type != "binary_expression":
        return None
    left = node.child_by_field_name("left")      # (review I-c) on every binary evaluation — the cheap test first
    if left is None or left.type != "parenthesized_expression":
        return None
    op, right = node.child_by_field_name("operator"), node.child_by_field_name("right")
    if op is None or right is None:
        return None
    sign = _text(op, raw)
    if sign not in _CAST_UNARY_OPS:
        return None
    inner = [c for c in left.named_children if c.type != "comment"]
    if len(inner) != 1 or inner[0].type not in ("identifier", "type_identifier"):
        return None
    return " ".join(_text(inner[0], raw).split()), sign, (None if right.type in _GROUPED_OPERANDS else right)


def _paren_amp(root, raw) -> list[list[str]]:
    """``(T)&x`` read by the grammar as ``(T) & x``: ``[T, x]`` for each — x's address is taken when T is a type."""
    out = set()
    for n in _walk(root):
        if n.type != "binary_expression" or n.child_by_field_name("operator") is None \
                or _text(n.child_by_field_name("operator"), raw) != "&":
            continue
        left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
        inner = [c for c in left.named_children if c.type != "comment"] if left is not None and \
            left.type == "parenthesized_expression" else []
        if len(inner) == 1 and inner[0].type in ("identifier", "type_identifier") and right is not None:
            base = _base_identifier(right, raw)
            if base:
                out.add((_text(inner[0], raw), base))
    return [list(x) for x in sorted(out)]


_ASSIGN_RE = re.compile(r"\+\+|--|<<=|>>=|[-+*/%&|^]=|(?<![=!<>])=(?!=)")
_ADDRESS_OF_RE = re.compile(r"(?:^|[(,=!~?:;{}]|&&|\|\||\breturn\b)\s*&(?!&)")
_CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
# Unary ``&``: at the start of the body, after ``(`` ``,`` ``=`` or another operator, or after a pointer cast
# (``((U8 *)&g)``) — never a binary ``(v) & (m)`` (R2b review round 2 F, round 3 W1).
_MACRO_ADDRESS_RE = re.compile(r"(?:(?:^|[(,=!~?:;{}+\-*/%<>|^]|\breturn\b)|\(\s*[A-Za-z_][\w\s]*\*[\w\s*]*\))\s*&(?!&)[\s(]*([A-Za-z_]\w*)")
# ``(NAME)&x``: a cast exactly when NAME is a type — decided against the project's type names (round 4 C6).
_PAREN_AMP_RE = re.compile(r"\(\s*([A-Za-z_][\w\s*]*?)\s*\)\s*&(?!&)[\s(]*([A-Za-z_]\w*)")
_TYPE_WORDS = frozenset({"const", "volatile", "unsigned", "signed", "char", "short", "int", "long", "float", "double",
                         "_Bool", "void", "struct", "union", "enum"})


def macro_addresses(body: str, type_names=frozenset()) -> set[str]:
    """Names whose address a macro body may take: unary ``&``, ``return &x``, and ``&x`` after a cast to a type."""
    names = set(_MACRO_ADDRESS_RE.findall(body))
    for group, name in _PAREN_AMP_RE.findall(body):
        words = [w for w in re.split(r"[\s*]+", group) if w]
        if words and all(w in type_names or w in _TYPE_WORDS for w in words):
            names.add(name)
    return names


def _call_through_expression(body: str, type_names=frozenset(), cast_words: set | None = None) -> bool:
    """A call whose callee is not a name: ``(*g_fp)()``, ``(fp)()``, ``tbl[i]()``, ``((a) ? f : g)(x)``, ``f(x)(y)``.
    ``(T)(x)`` is a cast when every word of ``T`` is a type — decided against the project's type names; the words of
    such a ``T`` go to ``cast_words`` (a unit that does not see them as types reads a call there: review R35 round 3
    W2, `undecided_macro_view`)."""
    for m in re.finditer(r"([\])])\s*\(", body):
        if m.group(1) == "]":
            return True
        end, depth, i = m.start(1), 0, m.start(1)
        while i >= 0:
            depth += {")": 1, "(": -1}.get(body[i], 0)
            if depth == 0:
                break
            i -= 1
        words = [w for w in re.split(r"[\s*]+", body[i + 1:end]) if w] if i >= 0 else []
        if not words or not all(w in type_names or w in _TYPE_WORDS for w in words):
            return True
        if cast_words is not None:
            cast_words.update(w for w in words if w not in _TYPE_WORDS)
    return False


_TEXT_LITERAL_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'')


def _brackets_balanced(body: str) -> bool:
    """``()``/``[]``/``{}`` pair up outside string and character literals. ``#define LP (`` + ``(wr LP 0U))``: the
    text of neither shows the call their expansion forms (review R35 round 3 W3)."""
    stack = []
    for ch in _TEXT_LITERAL_RE.sub('""', body):
        if ch in "([{":
            stack.append(ch)
        elif ch in ")]}":
            if not stack or stack.pop() != {")": "(", "]": "[", "}": "{"}[ch]:
                return False
    return not stack


def macro_body_opaque(body: str, type_names=frozenset(), cast_words: set | None = None) -> bool:
    """(R35) May a macro body do what the text-level `macro_side_effects` cannot see? Token pasting or stringizing
    (``W##R`` forms a name no scan reads), a line splice the body kept (``wr \\ ()`` — the scan's ``name(`` and
    ``)(`` do not match across it; review round 2 C2), a call through an expression (`_call_through_expression`), or
    an address taken where `_ADDRESS_OF_RE` does not look (``((U8 *)&loc)`` — `macro_addresses`). Only a macro none
    of whose definitions is opaque — nor any macro they mention (`function_write_closure` closes it) — can be judged
    by the union of their text (review R35 round 1 C1, round 2 C1')."""
    return "#" in body or "\\" in body or not _brackets_balanced(body) \
        or _call_through_expression(body, type_names, cast_words) or bool(macro_addresses(body, type_names))


def undecided_macro_view(scope: dict[str, Any], name: str) -> dict[str, Any] | None:
    """(R35) What a macro this unit cannot pin down (defined under an undecided ``#if``, or redefined) may expand to,
    judged by every definition the tree has — ``None`` when that is not the whole story: no tree definition, a missing
    include (it may define the name), a build ``-D`` of that name (a body outside the tree), or a definition whose
    text hides what it does, itself or through a macro it mentions (`macro_body_opaque`, `_macro_closure`), or a word
    read as a cast that is not an unconditional typedef of this unit (``scope["typedef_names"]``). One judgment for the source oracle and the MC/DC design (review R35 round 1 W3). Headers outside the
    tree (``<...>``, toolchain) are not read: the scope's disclosed assumption that they define no project name. A
    ``#define`` inside a function body is in neither the union nor the unit's macro table: since R62 such a name is
    "varied" in the unit, and its view is None (the union of the file-level definitions is not the whole story)."""
    effects = scope.get("effects") or {}
    if name in set(scope.get("body_directive_names") or ()) or scope.get("body_table_unknown"):
        return None
    if name not in (effects.get("macros") or {}) or scope.get("missing_includes") \
            or name in ((scope.get("build_defines") or {}).get("defines") or {}):
        return None
    view = _macro_closure(effects, name)
    if view["opaque"]:
        return None
    if view["cast_words"] and (not set(view["cast_words"]) <= set(scope.get("typedef_names") or ())
                               or set(view["cast_words"]) & set(scope.get("macro_status") or ())):
        # ``((Hook)())`` read as a cast because ``Hook`` is a typedef somewhere in the tree — not an unconditional
        # typedef this unit sees, where it may be the function pointer being called (review R35 rounds 3 W2 / 4 C4);
        # nor a word that is also a macro here: ``#define Hook g_fp`` rescans ``(Hook)()`` into a call (round 5 W1)
        return None
    return view


def _macro_closure(effects: dict[str, Any], name: str) -> dict[str, Any]:
    """(R35) A tree macro's union entry with what it adds up to through every macro its bodies mention (transitively):
    ``opaque`` (``#define HOOK CALL_FP`` with ``#define CALL_FP ((*g_fp)())`` hides a call too — review round 2 C1'),
    ``reach_names`` (every name the expansion may contain: ``#define ARR2 LP`` with ``#define LP (la)`` may hand out
    a local array — round 3 C3) and ``cast_words``. Computed for the names a view is asked about and kept in
    ``effects`` (one depth-first walk each — a fixpoint over the whole tree was quadratic in forward-reference chains:
    round 4 W2). An entry without ``opaque`` (a closure built by code before R35) counts as opaque. ``name`` must be
    a key of ``effects["macros"]`` (the view checks); the result is shared and read-only — it holds the union's own
    ``calls``/``names`` lists."""
    cache = effects.setdefault("_macro_closure", {})
    if name in cache:
        return cache[name]
    macros = effects.get("macros") or {}
    opaque, reach, casts, seen, stack = False, set(), set(), set(), [name]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        entry = macros.get(current)
        if entry is None:
            continue
        opaque = opaque or entry.get("opaque", True)
        reach.update(entry.get("names") or ())
        casts.update(entry.get("cast_words") or ())
        stack.extend(c for c in entry.get("calls") or () if c in macros)
    view = {**macros[name], "opaque": opaque, "reach_names": tuple(sorted(reach)), "cast_words": tuple(sorted(casts))}
    cache[name] = view
    return view


def _paren_param_call(body: str, params) -> bool:
    """``(param)(`` in a macro body: a call through what the macro is given (review R64 W-3)."""
    return any(re.search(r"[(]\s*" + re.escape(p) + r"\s*[)]\s*[(]", body) for p in params)


def macro_side_effects(body: str) -> dict[str, Any]:
    """What expanding a macro body may do: write (assignment of any kind, ``++``/``--``, ``&`` escaping an
    operand) and which names it invokes. Text-level, so it over-approximates — it is used only to *refuse*."""
    return {"writes": bool(_ASSIGN_RE.search(body) or _ADDRESS_OF_RE.search(body)),
            "calls": sorted(set(_CALL_RE.findall(body)))}


def _declares_function(node):
    while node is not None:
        if node.type == "function_declarator":
            return True
        node = node.child_by_field_name("declarator")
    return False


def _declared_name(node, raw):
    while node is not None and node.type != "identifier" and node.type != "type_identifier":
        node = node.child_by_field_name("declarator")
    return _text(node, raw) if node is not None else ""


def _collect_enum(node, raw, rec, conditional, line, pos=0):
    if node is None or node.type != "enum_specifier":
        return
    body = node.child_by_field_name("body")
    if body is None:
        return
    tag = node.child_by_field_name("name")
    key = "enum " + _text(tag, raw) if tag is not None else f"enum @{rec['path']}:{node.start_byte}"
    members = []
    for e in body.named_children:
        if e.type != "enumerator":
            continue
        name = _text(e.child_by_field_name("name"), raw)
        value = e.child_by_field_name("value")
        members.append({"name": name, "value": " ".join(_text(value, raw).split()) if value is not None else None})
    rec["enums"].setdefault(key, []).append({"members": members, "line": line, "pos": pos, "conditional": conditional})


def _field_name(node, raw):
    """The member a field declarator names (``a``, ``*p``, ``b[4]``, ``(*f)(void)``), or ""."""
    while node is not None and node.type != "field_identifier":
        if node.type == "parenthesized_declarator":   # ``(*f)`` — the grammar gives its content no field name
            node = node.named_children[0] if node.named_children else None
            continue
        node = node.child_by_field_name("declarator")
    return _text(node, raw) if node is not None else ""


def _collect_struct(spec, raw, rec, line, pos, conditional, names=(), quals=()):
    """(R39) Record a struct/union body's members under its key — ``struct tag`` / ``union tag``, or one key per anonymous
    body — and an alias to the key under each typedef name in ``names`` (with the typedef's own qualifiers ``quals``:
    ``typedef volatile struct {…} VT;`` makes every ``VT`` object volatile — review C1). Returns the key ("" when
    ``spec`` is not a struct/union specifier). Members keep their declared type text, array dimensions (outermost
    first), shape (``scalar`` · ``array`` · the declarator kind otherwise) and bit-field / qualifier flags; an anonymous
    nested body is recorded under its own key, which is then the member's type. A body with anything but plain member
    declarations — an ``#if`` around a member, an unnamed struct/union member, a parse error — is ``hidden``: its
    members cannot all be named (review C2). A union's members are not kept (a union is never flattened)."""
    if spec is None or spec.type not in {"struct_specifier", "union_specifier"}:
        return ""
    kind = "union" if spec.type == "union_specifier" else "struct"
    tag = spec.child_by_field_name("name")
    key = f"{kind} {_text(tag, raw)}" if tag is not None else f"{kind} @{rec['path']}:{spec.start_byte}"
    structs = rec.setdefault("structs", {})
    alias = {"alias": key, "volatile": "volatile" in quals, "const": "const" in quals, "line": line, "pos": pos,
             "conditional": conditional}
    for n in names:
        structs.setdefault(n, []).append(alias)
    body = spec.child_by_field_name("body")
    if body is None:
        return key
    members, hidden = [], False
    for fd in body.named_children:
        if fd.type == "comment":
            continue
        if fd.type != "field_declaration" or fd.has_error:
            hidden = True   # ``#if FEATURE`` around a member, a parse error, …
            continue
        ft = fd.child_by_field_name("type")
        fquals = {_text(c, raw) for c in fd.named_children if c.type == "type_qualifier"}
        if ft is not None and ft.type in {"struct_specifier", "union_specifier"}:
            typename = _collect_struct(ft, raw, rec, line, pos, conditional)
        elif ft is not None and ft.type == "enum_specifier":
            etag = ft.child_by_field_name("name")
            typename = "enum " + _text(etag, raw) if etag is not None else f"enum @{rec['path']}:{ft.start_byte}"
        else:
            typename = " ".join(_text(ft, raw).split()) if ft is not None else ""
        bitfield = any(c.type == "bitfield_clause" for c in fd.named_children)
        declarators = fd.children_by_field_name("declarator")
        if not declarators:
            hidden = True   # an unnamed struct/union member (C11 anonymous member): its members are this struct's
            continue
        for d in declarators:
            dims, inner = [], d
            while inner is not None and inner.type == "array_declarator":
                size = inner.child_by_field_name("size")
                dims.append(strip_comments(_text(size, raw)).strip() if size is not None else "")
                inner = inner.child_by_field_name("declarator")
            if inner is not None and inner.type == "field_identifier":
                shape = "array" if dims else "scalar"
            else:
                shape = inner.type.replace("_declarator", "") if inner is not None else "unknown"
            members.append({"name": _field_name(d, raw), "type": typename, "dims": list(reversed(dims)), "shape": shape,
                            "bitfield": bitfield, "volatile": "volatile" in fquals, "const": "const" in fquals})
    bit_fields = any(m["bitfield"] for m in members)   # never flattened: the members are not kept (review I-e)
    structs.setdefault(key, []).append({"union": kind == "union", "hidden": hidden, "bit_fields": bit_fields,
                                        "members": [] if kind == "union" or bit_fields else members,
                                        "line": line, "pos": pos, "conditional": conditional})
    return key


def _function_effects(fn, raw):
    """Direct writes, address-taken identifiers, pointer writes and callees of one function body."""
    writes, taken, calls, locals_, idents = set(), set(), set(), set(), set()
    block_externs: set[str] = set()   # (review R64 round 3 C4) block-scope ``extern`` names: no locals, but no typedef
    # (R64) ``(T)(x)``: a cast when T names a type, a call otherwise — decided over the tree (`function_write_closure`)
    paren_calls: set[str] = set()
    local_arrays, indirect, top_locals = set(), set(), set()
    call_args: dict[str, set[str]] = {}
    pointer_write = False
    body = fn.child_by_field_name("body")
    stack = [body] if body is not None else []
    while stack:
        n = stack.pop()
        stack.extend(n.named_children)
        target = None
        if n.type == "assignment_expression":
            target = n.child_by_field_name("left")
        elif n.type == "update_expression":
            target = n.child_by_field_name("argument")
        elif n.type == "unary_expression" and _text(n.child_by_field_name("operator"), raw) == "&":
            arg = n.child_by_field_name("argument")
            base = _base_identifier(arg, raw)
            if base:
                taken.add(base)
        elif n.type == "pointer_expression" and _text(n, raw).startswith("&"):
            base = _base_identifier(n.child_by_field_name("argument"), raw)
            if base:
                taken.add(base)
        elif n.type == "cast_expression" and (hidden := _cast_hidden_call(n, raw)):
            # (R16 review W-R4-1) ``(Inc()) + 1U`` parses as a cast of ``+1U`` to the function type ``Inc()`` — no C
            # cast has a function type, so it is the call ``Inc()``: its effects belong to this function's closure
            calls.add(hidden)
        elif n.type == "call_expression":
            f = n.child_by_field_name("function")
            if f is not None and f.type == "identifier":
                calls.add(_text(f, raw))
                args = n.child_by_field_name("arguments")
                # Argument base names per callee: a function-like macro ``#define SAVE(v) (g_p = &(v))`` takes the
                # address of what the call passes (R2b review round 2 F).
                call_args.setdefault(_text(f, raw), set()).update(
                    b for a in (args.named_children if args is not None else []) for b in [_base_identifier(a, raw)] if b)
            elif _paren_callee(n, raw):
                paren_calls.add(_paren_callee(n, raw))
            else:
                calls.add("<indirect>")
        elif n.type == "declaration":
            # A block-scope ``extern`` names the global itself, not a local (review C3f) — it still hides a typedef of
            #   its name: ``(handler)(x)`` calls through it (review R64 round 3 C4)
            if any(c.type == "storage_class_specifier" and _text(c, raw) == "extern" for c in n.named_children):
                for d in _declarators(n):
                    block_externs.add(_declared_name(d, raw) or pointer_flow.declarator_kind(
                        d.child_by_field_name("declarator") if d.type == "init_declarator" else d, raw)[0])
            else:
                for d in _declarators(n):
                    # (R64) ``void (*cb)(U8)``: through the parenthesized declarator too
                    name = _declared_name(d, raw) or pointer_flow.declarator_kind(
                        d.child_by_field_name("declarator") if d.type == "init_declarator" else d, raw)[0]
                    if name:
                        locals_.add(name)
                        if n.parent is not None and n.parent == body:
                            top_locals.add(name)  # declared at function level: shadows for the whole body
                        inner = d.child_by_field_name("declarator") if d.type == "init_declarator" else d
                        if inner is not None and inner.type == "array_declarator":
                            local_arrays.add(name)
        elif n.type == "identifier":
            idents.add(_text(n, raw))
        if target is not None:
            base = _base_identifier(target, raw)
            if base:
                writes.add(base)
                bare = target
                while bare.type == "parenthesized_expression" and bare.named_children:
                    bare = bare.named_children[0]  # ``(p[0]) = 0U`` is ``p[0] = 0U`` (R2b review C5)
                if bare.type != "identifier":
                    # ``p[i] = …`` / ``s.f = …``: through a pointer when ``p`` is one. Only a single ``a[i]`` on a local
                    # array stays inside it — ``ps[0][0]``, ``a[0].p[0]`` go through what the element holds (round 4 C3).
                    arg = bare.child_by_field_name("argument") if bare.type == "subscript_expression" else None
                    while arg is not None and arg.type == "parenthesized_expression" and arg.named_children:
                        arg = arg.named_children[0]
                    single = arg is not None and arg.type == "identifier"
                    indirect.add((base, single))
            else:
                pointer_write = True
    params = set()
    _, fdecl = _function_name(fn, raw)
    plist = fdecl.child_by_field_name("parameters") if fdecl is not None else None
    for p in plist.named_children if plist is not None else []:
        if p.type == "identifier":
            # (review R64 round 3 K1) a K&R parameter list: the parameters are declared where this walk reads them as
            #   names of nothing — a write through one is a write through a pointer the closure cannot name
            pointer_write = True
            continue
        d = p.child_by_field_name("declarator")
        # (R64 review C-7) ``void (*handler)(U8)``: through the parenthesized declarator too
        name = (_declared_name(d, raw) or pointer_flow.declarator_kind(d, raw)[0]) if d is not None else ""
        if name:
            params.add(name)
    every_local = locals_ | params
    # (R64) ``(cb)(x)`` on a parameter or local is a call through it — a typedef of that name elsewhere is no cast here
    if paren_calls & (every_local | block_externs):
        calls.add("<indirect>")
        paren_calls -= every_local | block_externs
    # A subscript/member write on a parameter or a non-array local writes *through* it (``void clr(U8 *p) { p[0] = 0U; }``)
    # — to an object the closure cannot name. It used to vanish with the shadowed name (R2b source oracle).
    pointer_write = pointer_write or any(b in every_local and not (b in local_arrays and single) for b, single in indirect)
    # Only names declared for the whole body (parameters, function-level locals) hide a global of the same name: one
    # declared in a nested block does so only inside it, so a write elsewhere may be the global's (round 4 C10).
    shadow = top_locals | params
    # ``idents``: every name the body uses — an object-like macro among them may have side effects (``CLEAR_FLAG;``).
    # (R14) the declared return type as written (``U8``, ``Error_t``, ``U8 *``) — a stub's value is converted to it
    rtype = fn.child_by_field_name("type")
    rdecl = fn.child_by_field_name("declarator")
    return_type = (_text(rtype, raw).strip() + (" *" if rdecl is not None and rdecl.type == "pointer_declarator"
                                                  else "")) if rtype is not None else ""
    return {"writes": sorted(writes - shadow), "address_taken": sorted(taken - shadow), "calls": sorted(calls),
            "pointer_write": pointer_write, "idents": sorted(idents - every_local - calls),
            "call_args": {k: sorted(v - shadow) for k, v in call_args.items() if v - shadow},
            "return_type": return_type, "paren_calls": sorted(paren_calls)}


def _paren_callee(n, raw) -> str:
    """``T`` of a call ``(T)(x)`` — one parenthesized name, one argument: tree-sitter's parse of a cast to a typedef
    name (``(U8)(a + 1U)``) and of a call through a parenthesized name alike — else ""."""
    f = n.child_by_field_name("function")
    if f is None or f.type != "parenthesized_expression":
        return ""
    inner = [c for c in f.named_children if c.type != "comment"]
    args = n.child_by_field_name("arguments")
    operands = [c for c in args.named_children if c.type != "comment"] if args is not None else []
    if len(inner) != 1 or inner[0].type not in ("identifier", "type_identifier") or len(operands) != 1:
        return ""
    return _text(inner[0], raw)


def paren_call_is_cast(name: str, type_names, functions, objects, macro_text) -> bool:
    """(R64) ``(name)(x)`` is a cast — the pointer flow's rule (`pointer_flow.paren_is_cast`, one operand)."""
    return pointer_flow.paren_is_cast(name, 1, functions, objects, macro_text, type_names)


def _base_identifier(node, raw):
    """``g`` for ``g``, ``g.x``, ``g[i]``, ``(g)``; empty for writes through pointers (``*p``, ``p->x``)."""
    while node is not None:
        if node.type == "identifier":
            return _text(node, raw)
        if node.type == "parenthesized_expression":
            node = node.named_children[0] if node.named_children else None
        elif node.type == "field_expression":
            if any(c.type == "->" for c in node.children):
                return ""
            node = node.child_by_field_name("argument")
        elif node.type == "subscript_expression":
            node = node.child_by_field_name("argument")
        else:
            return ""
    return ""


_TOOLCHAIN_INCLUDE_RE = re.compile(r"\$\{MCUToolsBaseDir\}[^\"&]*?/include(?=&quot;|\")")


def _toolchain_header(context: dict[str, Any], name: str) -> bool:
    """A quoted include the tree cannot resolve is the toolchain's only when (R2b review round 5 C-A/C-B):
    the build configuration names toolchain include directories; no file of that name exists in the tree (an
    *ambiguous* project header — two ``cfg.h`` — is not a toolchain header); no file of that name failed to be read
    and the scan was not cut at its file cap (an unread project header is not one either); and it is a ``.h``."""
    if not (context.get("build") or {}).get("toolchain_include_dirs"):
        return False
    base = os.path.basename(name).lower()
    if not base.endswith(".h") or context.get("file_cap_reached"):
        return False
    if (context.get("headers") or {}).get(base):
        return False
    return base not in {os.path.basename(p).lower() for p in context.get("incomplete_files") or ()}


def detect_build_config(cproject_texts: dict[str, str]) -> dict[str, Any]:
    """What a build configuration (Eclipse/CodeWarrior ``.cproject``) says, as evidence for two questions:

    * toolchain include directories — a quoted ``#include`` found nowhere in the source tree (C11 6.10.2p3 retries it as
      ``<...>``, i.e. in these directories) is the toolchain's header (``hidef.h``), not a project header that went
      missing. Without such evidence the include stays a gap (everything after it undecided);
    * (R17) the macros the build defines — per configuration file: every ``-D`` the compiler tools' options carry (a
      preprocessor-symbols list option, ``-D`` tokens in "other flags"). ``complete`` only when the file declares compiler
      tools and every build configuration in it defines the same set: a name that neither the tree nor this set defines
      is then undefined in ``#if`` (`_pp_undefined`) instead of undecided."""
    dirs: set[str] = set()
    for text in cproject_texts.values():
        dirs.update(_TOOLCHAIN_INCLUDE_RE.findall(text or ""))
    return {"toolchain_include_dirs": sorted(dirs), "evidence": sorted(p for p, t in cproject_texts.items()
                                                                      if _TOOLCHAIN_INCLUDE_RE.search(t or "")),
            "configurations": {p: _build_defines(t or "") for p, t in sorted(cproject_texts.items())}}


_DEFINE_TOKEN = re.compile(r"-D([A-Za-z_]\w*)(?:=([^\s\"'$`\\]*))?")
_RISKY_FLAG = re.compile(r"(?:^|\s)[\"']?-(?:D|U|include|prefix|imacros|AddIncl)")   # case matters: -double_size
# (review R2 W3) flags that pull options from elsewhere — HIWARE ``-Env"COMPOPTIONS=-DX"``, ``-Prod=project.ini``,
# ``-ArgFile``, response files ``@file``, ``--preinclude``: what they define is not in this file
# the command-line placeholders CDT fills itself (the option values, inputs, outputs, tool directories)
_CDT_PLACEHOLDER = re.compile(r"\$\{(?:COMMAND|FLAGS|INPUTS|OUTPUT|OUTPUT_FLAG|OUTPUT_PREFIX|EXTENSION|ProjDirPath|ProjName|MCUToolsBaseDir|[A-Za-z0-9]+_ToolsDir)\}")
_INDIRECT_FLAG = re.compile(
    r"(?:^|\s)[\"']?(?:-Env|-Prod|-ArgFile|--preinclude|--define|--undefine|--include|--imacros|-W[pP],|-Xpreprocessor"
    r"|/[DU]|@\S)|\$[({]")   # (review R3 W-R3-2) other spellings of -D/-U/forced includes, build variables


def _build_defines(text: str) -> dict[str, Any]:
    """``{"defines": {name: body}, "complete": bool, "reason": str}`` of one ``.cproject`` — fail closed.

    Read: the C compiler tool of the project-wide folder (``folderInfo resourcePath=""``) of every build configuration
    (a ``configuration`` with a ``toolChain``): a preprocessor-symbols list (``valueType="definedSymbols"``) and plain
    ``-DNAME[=VALUE]`` tokens in string options. Anything this reading cannot account for makes the file *incomplete*
    (names stay undecided, as without it): a user makefile (``managedBuildOn="false"``); an undefine list or ``-U``;
    a quoted, expanded or spaced ``-D``; a forced include (``-include``/``-prefix``/"additional include files"); any
    option with a value on a file or sub-folder (``fileInfo``, ``folderInfo`` with a ``resourcePath``) or on the
    preprocessor tool; configurations that define different sets (which one is built is not recorded)."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {"defines": {}, "complete": False, "reason": "cproject_unparsable"}

    def incomplete(reason):
        return {"defines": {}, "complete": False, "reason": reason}

    def has_value(opt):
        return bool((opt.get("value") or "").strip()) or any(
            (v.get("value") or "").strip() for v in opt.iter("listOptionValue"))

    configs = [c for c in root.iter("configuration") if c.find(".//toolChain") is not None]
    if not configs:
        return incomplete("no_build_configuration")
    sets = []
    for config in configs:
        for builder in config.iter("builder"):
            if (builder.get("managedBuildOn") or "").lower() == "false":
                return incomplete("unmanaged_build")
        scoped = [x for x in config if x.tag == "fileInfo" or (x.tag == "folderInfo" and (x.get("resourcePath") or ""))]
        if any(has_value(o) for x in scoped for o in x.iter("option")):
            return incomplete("resource_scoped_options")
        bases = [x for x in config if x.tag == "folderInfo" and not (x.get("resourcePath") or "")]
        if len(bases) != 1:
            return incomplete("no_project_folder_options" if not bases else "several_project_folder_options")
        base = bases[0]
        for chain in base.iter("toolChain"):
            if any(has_value(o) for o in chain.findall("option")):
                return incomplete("toolchain_options")   # (review R2 W3) options of the tool chain itself
        for element in list(base.iter("tool")) + list(config.iter("builder")):
            for a in ("command", "commandLinePattern", "arguments"):
                text = _CDT_PLACEHOLDER.sub(" ", element.get(a) or "")   # ${COMMAND} ${FLAGS} ${INPUTS} … are the tool's own
                if _RISKY_FLAG.search(text) or _INDIRECT_FLAG.search(text):
                    return incomplete("tool_command_flags")
        # (review R3 W-R3-2) the C compiler: a C++ tool's defines do not reach a .c unit
        compilers = [t for t in base.iter("tool") if "compiler" in (t.get("superClass") or "").lower()
                     and not re.search(r"cpp|c\+\+|g\+\+|cxx", (t.get("superClass") or "").lower())]
        if not compilers:
            return incomplete("configuration_without_compiler_tool")
        for t in base.iter("tool"):
            if "preprocessor" in (t.get("superClass") or "").lower() and any(has_value(o) for o in t.iter("option")):
                return incomplete("preprocessor_tool_options")
        defines: dict[str, str] = {}
        per_tool: list[dict[str, str]] = []
        for tool in compilers:
            before = dict(defines)
            defines = {}
            for opt in tool.iter("option"):
                kind = ((opt.get("superClass") or "") + " " + (opt.get("name") or "") + " "
                        + (opt.get("valueType") or "")).lower()
                values = [v.get("value") or "" for v in opt.iter("listOptionValue")]
                if "undef" in kind:
                    if has_value(opt):
                        return incomplete("undefine_option")
                    continue
                if any(k in kind for k in ("addincl", "includefiles", "include files", "prefix", "forced")):
                    if has_value(opt):
                        return incomplete("forced_include_option")
                    continue
                vtype = (opt.get("valueType") or "").lower()
                if vtype in {"boolean", "enumerated", "includepath"}:
                    continue   # a switch ("Generate debug symbols") or search directories — no macro comes from them
                if "definedsymbols" in kind or any(k in kind for k in ("defin", "symbol", "macro")):
                    if (opt.get("value") or "").strip():
                        return incomplete("define_option_value_unreadable")
                    for v in values:
                        name, eq, body = v.strip().partition("=")
                        if not re.fullmatch(r"[A-Za-z_]\w*", name) or any(c in body for c in "\"'$`\\ "):
                            return incomplete("define_value_unreadable")
                        defines[name] = body if eq else "1"
                    continue
                if values and vtype != "string":
                    # (review R2 W3) a list option this reading does not know (``dOpts = BARE``): its entries may be
                    # macros under another spelling — not evidence
                    return incomplete("compiler_list_option_unrecognized")
                for text_value in [opt.get("value") or ""] + values:
                    if _INDIRECT_FLAG.search(text_value):
                        return incomplete("compiler_flag_indirection")   # -Env"COMPOPTIONS=…", -Prod, -ArgFile, @file
                    if not _RISKY_FLAG.search(text_value):
                        continue
                    rest = _DEFINE_TOKEN.sub(" ", text_value)
                    if _RISKY_FLAG.search(rest):
                        return incomplete("compiler_flag_unreadable")   # -U, quoted/expanded -D, forced include
                    for tok in text_value.split():
                        m = _DEFINE_TOKEN.fullmatch(tok)
                        if m is None and re.search(r"-D", tok):   # ``"-DFOO"``, ``-D${X}``, ``-DV="1 2"``
                            return incomplete("compiler_flag_unreadable")
                        if m:
                            defines[m.group(1)] = m.group(2) if m.group(2) is not None else "1"
            per_tool.append(defines)
            defines = {**before, **defines}
        if len(compilers) > 1 and len({tuple(sorted(d.items())) for d in per_tool}) > 1:
            return incomplete("compiler_tools_disagree")
        sets.append(defines)
    if any(d != sets[0] for d in sets[1:]):
        return incomplete("configurations_disagree")
    # (R63 review round 2 I2) a compiler option that may compile C as C++ (CodeWarrior ``-C++f`` · a "C++" switch set):
    #   then ``__cplusplus`` is not decided undefined (`_pp_undefined`)
    cplusplus = False
    for config in configs:
        for tool in config.iter("tool"):
            if "compiler" not in (tool.get("superClass") or "").lower():
                continue
            for opt in tool.iter("option"):
                kind = ((opt.get("superClass") or "") + " " + (opt.get("name") or "")).lower()
                values = [opt.get("value") or ""] + [v.get("value") or "" for v in opt.iter("listOptionValue")]
                if any(re.search(r"(?:^|\s)-C\+\+", v) for v in values) or (
                        re.search(r"c\+\+|cplusplus", kind) and any(v.strip().lower() not in ("", "false") for v in values)):
                    cplusplus = True
    return {"defines": sets[0], "complete": True, "reason": "", "cplusplus_mode": cplusplus}


# (R17) Names an implementation may define: reserved identifiers (C11 7.1.3 — any leading underscore, conservatively),
# the standard library's names and its reserved families (C11 7.31: E[0-9A-Z]…, SIG…, LC_…, PRI/SCN…, FE_…, ATOMIC_…,
# TIME_…, FLT_/DBL_/LDBL_…) and the toolchain's own header names seen in these trees (hidef.h). Never taken as
# undefined on build evidence.
_STANDARD_NAME_RE = re.compile(
    r"^(?:u?int(?:_least|_fast)?\d+_t|u?intptr_t|u?intmax_t|size_t|ptrdiff_t|wchar_t|wint_t|bool|true|false|NULL|EOF|WEOF|"
    r"CHAR_BIT|MB_LEN_MAX|[A-Z0-9_]*_(?:MAX|MIN|EPSILON|DIG|MANT_DIG|RADIX)|U?INT\w*_C|offsetof|va_\w+|errno|"
    r"E[0-9A-Z]\w*|SIG[A-Z_]\w*|LC_[A-Z]\w*|PRI[a-zX]\w*|SCN[a-zX]\w*|FE_[A-Z]\w*|ATOMIC_[A-Z]\w*|TIME_[A-Z]\w*|"
    r"(?:FLT|DBL|LDBL)_\w+|EXIT_(?:SUCCESS|FAILURE)|SEEK_(?:SET|CUR|END)|BUFSIZ|FILENAME_MAX|FOPEN_MAX|L_tmpnam|TMP_MAX|"
    r"CLOCKS_PER_SEC|HUGE_VALL?|HUGE_VALF|INFINITY|NAN|FP_\w+|math_errhandling|stdin|stdout|stderr|assert|NDEBUG|"
    r"static_assert|alignas|alignof|noreturn|thread_local|complex|imaginary|I|"
    r"EnableInterrupts|DisableInterrupts|asm|interrupt|near|far|TRUE|FALSE|"
    r"(?:is|to|str|mem|wcs|atomic_|memory_order_|cnd_|mtx_|thrd_|tss_)[a-z_]\w*|CMPLX\w*|getc|putchar|setjmp)$")


def _implementation_may_define(name: str) -> bool:
    return name.startswith("_") or bool(_STANDARD_NAME_RE.match(name))


def build_project_context(files: dict[str, str], build: dict[str, Any] | None = None,
                          roots: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    """Scan every complete ``.c``/``.h`` text once. ``files`` maps path → complete source text.
    ``build``: `detect_build_config` of the tree's build configuration, when there is one. ``roots``: the source roots
    when there are several (separate builds) — a header name both have resolves within the includer's own root."""
    parser = _make_parser()
    context: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "files": {}, "headers": {}, "target": {},
                               "build": dict(build or {}), "roots": [str(r) for r in roots if r]}
    if parser is None:
        context["status"] = "tree_sitter_unavailable"
        return context
    for path in sorted(files):
        if not path.lower().endswith((".c", ".h")) or not files[path]:
            continue
        context["files"][path] = _scan_file(path, files[path], parser)
        if path.lower().endswith(".h"):
            context["headers"].setdefault(os.path.basename(path).lower(), []).append(path)
    context["target"] = _target_widths(context)
    context["status"] = "built"
    return context


def _target_widths(context):
    testimony: dict[str, set[int]] = {}
    evidence: dict[str, list[str]] = {}
    for path, rec in context["files"].items():
        for alias, defs in rec["typedefs"].items():
            m = _WIDTH_NAME_RE.match(alias)
            for d in defs:
                kind = base_kind(d.get("base", "")) if d.get("shape") == "scalar" and not d.get("conditional") else None
                if not m or kind is None or kind[0] == "_Bool":
                    continue
                unsigned = m.group("sign").lower() in {"u", "uint"}
                if kind[1] is not None and kind[1] == unsigned:
                    continue  # the name's signedness contradicts the declaration — not testimony
                testimony.setdefault(kind[0], set()).add(int(m.group("bits")))
                evidence.setdefault(kind[0], []).append(f"{os.path.basename(path)}:{d['line']} typedef {d['base']} {alias}")
    widths = {kind: next(iter(bits)) for kind, bits in testimony.items() if len(bits) == 1}
    return {"widths": widths, "conflicts": sorted(k for k, b in testimony.items() if len(b) > 1),
            "evidence": {k: sorted(v)[:3] for k, v in evidence.items()},
            "basis": "typedef_name_testimony"}


# ── Restricted preprocessor (per translation unit) ─────────────────────────────────────────────

_IF_NODES = frozenset({"preproc_if", "preproc_ifdef", "preproc_elif", "preproc_elifdef"})
_UNKNOWN = "unknown"


class _PPUnknown(Exception):
    """The condition depends on something the preprocessor state does not determine."""


def self_delimiting(node) -> bool:
    """Is a macro body one operand wherever it is substituted?

    C replaces the macro name by the body *text*: ``#define MASK 0x01U | 0x02U`` makes ``x & MASK`` mean
    ``(x & 0x01U) | 0x02U``. Only a body that is a single primary (identifier, literal, parenthesized
    expression, call) or a cast / unary operator applied to one binds as a unit; anything else has no single
    value independent of the use site (R81 review C1).
    """
    t = node.type
    if t in NAME_NODE_TYPES or t in {"number_literal", "char_literal", "parenthesized_expression", "call_expression",
                                     "field_expression", "subscript_expression"}:  # postfix binds tighter than any operator
        return True
    if t == "cast_expression":
        return self_delimiting(node.child_by_field_name("value"))
    if t == "unary_expression":
        return self_delimiting(node.child_by_field_name("argument"))
    return False


def _parse_body(text, parser):
    raw = ("int __probe = (" + text + ");").encode("utf-8")
    root = parser.parse(raw).root_node
    init = next((x for x in _walk(root) if x.type == "init_declarator"), None)
    value = init.child_by_field_name("value") if init is not None else None
    if root.has_error or value is None or _text(value, raw) != "(" + text + ")":
        return None, raw
    inner = [c for c in value.named_children if c.type != "comment"]
    return (inner[0] if len(inner) == 1 else None), raw


def _pp_undefined(name, env):
    """An identifier with no definition in scope: 0 in ``#if`` — but only when the tree is the whole story.

    A name the project never defines anywhere can only come from the build (``-D``) or the compiler; after a
    missing include, any name might have been defined there. Both are undecided, never 0 (R81 review C2).
    """
    if env["gap"]:
        raise _PPUnknown("undefined_outside_tree:" + name)
    if name not in env["defined_anywhere"]:
        # (R63 review round 1 I3) a C implementation shall not predefine ``__cplusplus`` (C11 6.10.8p3): reserved as it
        #   is, with the -D set read it is undefined — ``#ifdef __cplusplus`` around ``extern "C" {`` is decided
        if env.get("build_defines_complete") and ((name == "__cplusplus" and env.get("c_language"))
                                                  or not _implementation_may_define(name)):
            # (R17) the build configuration lists every -D (none for this name) and the name is not the
            # implementation's to define: undefined, 0 (C11 6.10.1p4) — recorded as an assumption of the unit
            env["assumed_undefined"].add(name)
            return 0
        raise _PPUnknown("undefined_outside_tree:" + name)
    return 0


def _pp_value(node, raw, env, depth):
    """``#if`` arithmetic (intmax_t). ``defined`` asks the macro table; see `_pp_undefined` for absent names."""
    if depth > 48:
        raise _PPUnknown("depth")
    macros, bodies = env["macros"], env["bodies"]
    t = node.type
    if t == "parenthesized_expression":
        inner = [c for c in node.named_children if c.type != "comment"]
        if len(inner) != 1:
            raise _PPUnknown("paren")
        return _pp_value(inner[0], raw, env, depth + 1)
    if t == "preproc_defined":
        ident = next((c for c in node.named_children if c.type == "identifier"), None)
        name = _text(ident, raw) if ident is not None else ""
        if macros.get(name) == _UNKNOWN or name in env["varied"]:
            raise _PPUnknown("defined:" + name)
        return 1 if name in macros else _pp_undefined(name, env)
    if t == "number_literal":
        text = _text(node, raw)
        digits = text.rstrip("uUlL")
        if "u" in text[len(digits):].lower():
            env["unsigned"] = True
        try:
            return int(digits, 16) if digits[:2].lower() == "0x" else (int(digits, 8) if digits.startswith("0") and len(digits) > 1 else int(digits))
        except ValueError as exc:
            raise _PPUnknown("literal") from exc
    if t in NAME_NODE_TYPES:  # (R35) a macro body parsed as an expression: ``#define TRUE (!FALSE)``
        name = _text(node, raw)
        if name in env["varied"]:
            raise _PPUnknown("macro_varies:" + name)
        entry = macros.get(name)
        if entry is None:
            return _pp_undefined(name, env)
        if entry == _UNKNOWN:
            raise _PPUnknown("macro:" + name)
        body = bodies.get(entry)
        if body is None or body.get("function_like") or not body.get("body"):
            raise _PPUnknown("macro_body:" + name)
        value, sub = _parse_body(body["body"], env["parser"])
        if value is None or not self_delimiting(value):
            raise _PPUnknown("macro_body_not_parenthesized:" + name)
        return _pp_value(value, sub, env, depth + 1)
    if t == "unary_expression":
        op = _text(node.child_by_field_name("operator"), raw)
        v = _pp_value(node.child_by_field_name("argument"), raw, env, depth + 1)
        if op not in {"!", "-", "+", "~"}:
            raise _PPUnknown(op)
        return {"!": int(not v), "-": -v, "+": v, "~": ~v}[op]
    if t == "binary_expression":
        op = _text(node.child_by_field_name("operator"), raw)
        a = _pp_value(node.child_by_field_name("left"), raw, env, depth + 1)
        if op == "&&" and not a:
            return 0
        if op == "||" and a:
            return 1
        b = _pp_value(node.child_by_field_name("right"), raw, env, depth + 1)
        if env["unsigned"] and (a < 0 or b < 0):
            # uintmax_t arithmetic would reinterpret the negative operand (``-1 > 0u`` is true) — not modeled.
            raise _PPUnknown("unsigned_arithmetic")
        if op in {"/", "%"}:
            if b == 0:
                raise _PPUnknown("division_by_zero")
            q = abs(a) // abs(b) * (1 if (a >= 0) == (b >= 0) else -1)
            return q if op == "/" else a - b * q
        if op in {"<<", ">>"} and not 0 <= b < 64:
            raise _PPUnknown("shift")
        ops = {"&&": lambda: int(bool(b)), "||": lambda: int(bool(b)), "==": lambda: int(a == b), "!=": lambda: int(a != b),
               "<": lambda: int(a < b), "<=": lambda: int(a <= b), ">": lambda: int(a > b), ">=": lambda: int(a >= b),
               "+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b, "&": lambda: a & b, "|": lambda: a | b,
               "^": lambda: a ^ b, "<<": lambda: a << b, ">>": lambda: a >> b}
        if op not in ops:
            raise _PPUnknown(op)
        return ops[op]()
    if t == "conditional_expression":
        c = _pp_value(node.child_by_field_name("condition"), raw, env, depth + 1)
        return _pp_value(node.child_by_field_name("consequence" if c else "alternative"), raw, env, depth + 1)
    raise _PPUnknown(t)


def _pp_condition(ev, env):
    """True / False, or None when the macro state does not determine the branch."""
    env = {**env, "unsigned": False}
    try:
        if "defined" in ev:
            name = ev["defined"]
            if env["macros"].get(name) == _UNKNOWN or name in env["varied"]:
                return None
            present = name in env["macros"] or bool(_pp_undefined(name, env))
            return present != ev["negate"]
        raw = ("#if " + ev["expr"] + "\n#endif\n").encode("utf-8")
        root = env["parser"].parse(raw).root_node
        node = root.named_children[0].child_by_field_name("condition") if root.named_children else None
        if root.has_error or node is None:
            return None
        return bool(_pp_value(node, raw, env, 0))
    except (_PPUnknown, RecursionError, ValueError):
        return None


_PARSERS = threading.local()


def shared_parser():
    """One validated tree-sitter parser per thread (``_make_parser`` builds and probes a new one each call)."""
    parser = getattr(_PARSERS, "parser", None)
    if parser is None:
        parser = _make_parser()
        _PARSERS.parser = parser
    return parser


def macro_changed_after(scope: dict[str, Any], name: str, position: int) -> bool:
    """Is ``name`` #defined or #undefined after ``position`` of the unit's own text — in that text, or in a header it
    includes there (R62 review W1)? At ``position`` the compiler has not met that change; the end-of-unit table has.
    Only real changes count (`_changes_table`): the same definition met again after the function is the one it saw —
    the final definition's position alone (``pp_bodies``) would say "after" for it (review round 2 W-A)."""
    return int((scope.get("pp_changed_at") or {}).get(name, -1)) >= position


def _defined_after(scope: dict[str, Any], text: str, position: int | None) -> bool:
    """(R62) Does ``text`` rest — directly or through a macro body — on a macro the unit changes only after ``position``
    (the function; `macro_changed_after`)? The end-of-unit table has it; the compiler has not seen it there yet.
    Memoized per scope; a name set too large to follow counts as resting on one (fail closed)."""
    if position is None:
        return False
    memo = scope.setdefault("_defined_after_memo", {})
    key = (text, position)
    if key in memo:
        return memo[key]
    bodies = scope.get("pp_bodies") or {}
    seen: set[str] = set()
    pending = re.findall(r"\b[A-Za-z_]\w*\b", text)
    found = False
    while pending:
        if len(seen) >= 4096:
            found = True   # (review I1) not followed to the end: undecided, never "nothing changed"
            break
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        if macro_changed_after(scope, name, position):
            found = True
            break
        d = bodies.get(name)
        if d:
            pending.extend(re.findall(r"\b[A-Za-z_]\w*\b", str(d.get("body") or "")))
    memo[key] = found
    return found


def _rests_on_missed(scope: dict[str, Any], text: str) -> bool:
    """(R62 review round 4) Does ``text`` name — directly or through a macro body — a name the walk never met though a
    file of the unit #defines it (`missed_definition_names`)? Memoized per scope."""
    missed = scope.get("missed_definition_names")
    if not missed:
        return False
    memo = scope.setdefault("_missed_memo", {})
    if text in memo:
        return memo[text]
    missed_set = scope.setdefault("_missed_set", set(missed))
    bodies = scope.get("pp_bodies") or {}
    seen: set[str] = set()
    pending = re.findall(r"\b[A-Za-z_]\w*\b", text)
    found = False
    while pending:
        if len(seen) >= 4096:
            found = True
            break
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        if name in missed_set:
            found = True
            break
        d = bodies.get(name)
        if d:
            pending.extend(re.findall(r"\b[A-Za-z_]\w*\b", str(d.get("body") or "")))
    memo[text] = found
    return found


def body_verdict(scope: dict[str, Any], keyword: str, argument: str, assumed: set | None = None,
                 position: int | None = None) -> bool | None:
    """Verdict of a conditional directive inside a function of this unit — ``keyword`` is ``if`` / ``ifdef`` /
    ``ifndef`` / ``elif`` / ``elifdef`` / ``elifndef``, ``argument`` its text — or None (undecided).

    The table is the one at the end of the unit, so a macro whose value changed during the unit decides nothing here
    (R81 review W1 — the function may sit before or after the change), nor does one the unit's file defines only after
    ``position`` (R62). Names taken as undefined on build evidence go to ``assumed`` (R17 review W1).
    """
    parser = shared_parser()
    if parser is None or scope.get("body_table_unknown"):
        return None   # (round 3) a body directive could not be read / an in-body include could not be resolved
    text = strip_comments(argument).strip()
    if _defined_after(scope, text, position) or _rests_on_missed(scope, text):
        return None
    if keyword in ("ifdef", "ifndef", "elifdef", "elifndef"):
        m = re.match(r"[A-Za-z_]\w*", text)
        if m is None:
            return None
        ev: dict[str, Any] = {"defined": m.group(0), "negate": keyword in ("ifndef", "elifndef")}
    elif keyword in ("if", "elif"):
        ev = {"expr": text}
    else:
        return None
    env = {"macros": scope.get("pp_macros") or {}, "bodies": scope.get("pp_bodies") or {}, "parser": parser,
           "defined_anywhere": scope.get("pp_defined_anywhere") or set(),
           # an #include inside a function body (review round 2 W-B) may define any name, as a missing header may
           "gap": bool(scope.get("missing_includes")) or bool(scope.get("body_includes")),
           "varied": set(scope.get("pp_varied") or ()),
           "build_defines_complete": bool((scope.get("build_defines") or {}).get("complete")),
           "c_language": (scope.get("build_defines") or {}).get("cplusplus_mode") is False,
           "assumed_undefined": assumed if assumed is not None else set()}
    return _pp_condition(ev, env)


def pp_condition(scope: dict[str, Any], node, raw: bytes, assumed: set | None = None) -> bool | None:
    """Verdict of an ``#if``/``#ifdef``/``#elif`` node inside a function of this unit (None = undecided) — see
    `body_verdict`. The directive's own spelling says ``ifdef`` or ``ifndef`` (``#  ifndef`` too, R62)."""
    name, cond = node.child_by_field_name("name"), node.child_by_field_name("condition")
    if node.type in {"preproc_ifdef", "preproc_elifdef"}:
        keyword = _directive_keyword(node, raw)
        argument = _text(name, raw) if name is not None else ""
    else:
        keyword = "elif" if node.type == "preproc_elif" else "if"
        argument = _text(cond, raw) if cond is not None else ""
    fn = node.parent
    while fn is not None and fn.type != "function_definition":
        fn = fn.parent
    return body_verdict(scope, keyword, argument, assumed, fn.start_byte if fn is not None else None)


# ── (R62) Conditional groups that split an expression inside a function ──────────────────────────────

_GROUP_DIRECTIVES = frozenset({"if", "ifdef", "ifndef", "elif", "elifdef", "elifndef", "else", "endif"})


def _directive_lines(raw: bytes, start: int, end: int, hashes: list[int] | None = None) -> list[tuple[int, int, str, str]]:
    """Preprocessor directive lines in ``raw[start:end]`` outside comments and literals: ``(line_start, line_end,
    keyword, argument)``, ``line_end`` being the newline that ends the logical line (a backslash-newline continues it;
    a block comment is one blank, so a directive line running into a comment that spans lines goes on after it).
    ``hashes`` (R63), when given, receives each line's ``#`` position (a comment before it on the line is a blank)."""
    out: list[tuple[int, int, str, str]] = []
    i, state, only_space, line_start = start, "code", True, start
    head: int | None = None
    hash_at = start
    while i < end:
        c = raw[i:i + 1]
        if c == b"\\" and raw[i + 1:i + 2] == b"\n":
            i += 2
            continue
        if c == b"\\" and raw[i + 1:i + 3] == b"\r\n":
            i += 3
            continue
        if state == "block":
            # a comment is one blank (translation phase 3): a directive line running into a comment that spans lines
            # goes on after it (R62 review round 5 W-1 — it was "unreadable", stopping every unit including the file)
            if raw[i:i + 2] == b"*/":
                state, i = "code", i + 2
                continue
            i += 1
            continue
        if state in ("string", "char"):
            if c == b"\\":
                i += 2
                continue
            if c == b"\n":
                state = "code"   # an unterminated literal ends with its line; the newline is handled below
                continue
            if c == (b'"' if state == "string" else b"'"):
                state = "code"
            i += 1
            continue
        if c == b"\n":
            if head is not None:
                out.append((head, i, *_directive_head(raw[hash_at + 1:i])))
                if hashes is not None:
                    hashes.append(hash_at)
            state, only_space, line_start, head = "code", True, i + 1, None
            i += 1
            continue
        if state == "line":
            i += 1
            continue
        if raw[i:i + 2] == b"/*":
            state, i = "block", i + 2
            continue
        if raw[i:i + 2] == b"//":
            state, i = "line", i + 2
            continue
        if c in (b" ", b"\t", b"\r", b"\f", b"\v"):
            i += 1
            continue
        if c == b"#" and only_space and head is None:
            # the keyword is read at the line's end, after splices and comments (``#/**/undef``, ``#un\<NL>def`` —
            # translation phases 2-3; R62 review round 4 W-3)
            head, hash_at, only_space = line_start, i, False
            i += 1
            continue
        only_space = False
        if c == b'"':
            state = "string"
        elif c == b"'":
            state = "char"
        i += 1
    if head is not None:
        out.append((head, end, *_directive_head(raw[hash_at + 1:end])))
        if hashes is not None:
            hashes.append(hash_at)
    return out


def _directive_head(rest: bytes) -> tuple[str, str]:
    """``(keyword, argument)`` of a directive line after its ``#``: splices removed, comments as spaces."""
    text = strip_comments(_spliced(rest))
    m = re.match(r"([A-Za-z_]\w*)\s*(.*)", text, re.S)
    return (m.group(1), m.group(2)) if m else ("", text)


def _spliced(argument: bytes) -> str:
    """A directive's argument with its line splices removed (translation phase 2 joins the lines without a space)."""
    return argument.replace(b"\\\r\n", b"").replace(b"\\\n", b"").decode("utf-8", errors="replace")


def _group_blanks(raw: bytes, start: int, end: int, verdict) -> tuple[list[tuple[int, int]] | None, str, int]:
    """Byte ranges to blank so that only the arms this configuration compiles stay in ``raw[start:end]``: every
    conditional directive line, and every group whose condition is false (C11 6.10.1p6). An arm inside a skipped group
    is never judged — the compiler does not evaluate it either. ``(ranges, "", decided)`` or ``(None, reason, 0)``;
    ``verdict(keyword, argument)`` is True / False / None (undecided)."""
    lines = _directive_lines(raw, start, end)
    if any(x[2] in ("define", "undef", "include") for x in lines):
        # (R62 review W2) the table changes inside the function: the end-of-unit table is not the one these groups see
        return None, "macro_table_changed_in_function", 0
    lines = [x for x in lines if x[2] in _GROUP_DIRECTIVES]
    if not lines:
        return None, "no_conditional_directive", 0
    blanks: list[tuple[int, int]] = []
    stack: list[dict[str, bool]] = []
    active, after, decided = True, start, 0
    for line_start, line_end, keyword, argument in lines:
        if not active:
            blanks.append((after, line_start))
        blanks.append((line_start, line_end))
        after = line_end
        if keyword in ("if", "ifdef", "ifndef"):
            stack.append({"outer": active, "taken": False})
        elif not stack:
            return None, "unbalanced", 0
        top = stack[-1]
        if keyword in ("if", "ifdef", "ifndef", "elif", "elifdef", "elifndef"):
            if keyword.startswith("el") and (not top["outer"] or top["taken"]):
                active = False
                continue
            if not top["outer"]:
                active = False
                continue
            v = verdict(keyword, argument)
            if v is None:
                return None, "undecided:" + " ".join(argument.split()), 0
            decided += 1
            active = top["taken"] = bool(v)
        elif keyword == "else":
            active = top["outer"] and not top["taken"]
            top["taken"] = True
        else:  # endif
            active = stack.pop()["outer"]
    if stack:
        return None, "unbalanced", 0
    return blanks, "", decided


def _blanked(raw: bytes, ranges) -> bytes:
    buf = bytearray(raw)
    for a, b in ranges:
        for k in range(a, b):
            if buf[k] not in (0x0A, 0x0D):
                buf[k] = 0x20
    return bytes(buf)


def _tree_has_error(node) -> bool:
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "ERROR" or n.is_missing:
            return True
        stack.extend(n.children)
    return False


def _function_nodes(root, raw) -> dict[tuple[int, str], Any]:
    """Every function definition the tree shows — through parse-recovery containers, as `mcdc_design` finds them."""
    out, stack = {}, [root]
    while stack:
        n = stack.pop()
        if n.type == "function_definition":
            out[(n.start_byte, _function_name(n, raw)[0])] = n
            continue
        stack.extend(n.named_children)
    return out


def project_body_conditionals(text: str, scope: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """(R62) ``text`` as the compiler reads each function that an ``#if`` splits mid-expression.

    tree-sitter reads a conditional directive only between statements; one inside an expression, an initializer or an
    ``if`` head (``if( a == 1 ⏎ #ifdef X ⏎ && b == 0 ⏎ #endif ⏎ )``, an ``#else`` arm that repeats the ``if (`` head)
    leaves an error in the function and the whole function was unread (`source_parse_error`). For each function of
    this configuration ("active" in ``main_file_states``) whose tree has an error, every conditional directive line and
    every group the unit's macro table judges false become blanks — same length, newlines kept, so byte positions and
    line numbers stay — and the file is parsed again. A function is projected only when every condition it meets in a
    compiled arm is decided (`body_verdict`), the re-parsed function has no error at the same position, and no other
    function of the file moves, appears or disappears. Returns the text to read and the report
    ``{"functions": [{"name", "line", "status", "conditions", "assumed_undefined"}], "projected": n}`` — ``status``
    ``projected`` or why not.
    """
    report: dict[str, Any] = {"functions": [], "projected": 0}
    parser = shared_parser()
    if parser is None or not text:
        return text, report
    raw = text.encode()
    if scope.get("main_file_sha256") != hashlib.sha256(raw).hexdigest():
        return text, report
    # (R63) from the bytes the project context read (`reading_text`): vendor syntax as blanks — a function the context saw
    #   (``__interrupt void SCI0_ISR(void)``) is the function its consumers parse, at the same position
    raw, blanked = reading_text(raw)
    report["blanked"] = blanked
    root = parser.parse(raw).root_node
    if not root.has_error:
        return (raw.decode("utf-8") if blanked or raw != text.encode() else text), report
    states = scope.get("main_file_states") or {}
    before = _function_nodes(root, raw)
    shape = {key: _tree_has_error(n) for key, n in before.items()}
    accepted: list[tuple[tuple[int, str], dict[str, Any], list[tuple[int, int]]]] = []
    for key, fn in sorted(before.items()):
        state = states.get(key[0])
        if not shape[key] or state is None:
            continue   # no error, or not compiled in this configuration (no function of the document)
        rec: dict[str, Any] = {"name": key[1], "line": fn.start_point[0] + 1, "start": key[0], "conditions": 0,
                               "assumed_undefined": []}
        report["functions"].append(rec)
        if state != "active":
            # (review W5b) whether the configuration compiles it at all is undecided: counted, never projected
            rec["status"] = "conditional_compilation_unresolved"
            continue
        assumed: set[str] = set()
        ranges, why, decided = _group_blanks(
            raw, fn.start_byte, fn.end_byte, lambda k, a, _s=key[0]: body_verdict(scope, k, a, assumed, _s))
        if ranges is None:
            rec["status"] = _undecided_kind(scope, why, key[0])[:200]   # classified on the whole condition
            continue
        rec.update(conditions=decided, assumed_undefined=sorted(assumed))
        rec["status"] = _projection_check(parser, _blanked(raw, ranges), shape, key)
        if rec["status"] == "projected":
            accepted.append((key, rec, ranges))
    while accepted:
        new = _blanked(raw, [r for _key, _rec, ranges in accepted for r in ranges])
        failed = [rec for key, rec, _r in accepted if _projection_check(parser, new, shape, key) != "projected"]
        if not failed:
            report["projected"] = len(accepted)
            return new.decode("utf-8"), report
        for rec in failed:   # projections that disturb each other: the rest are tried together again
            rec["status"] = "conflicts_with_another_projection"
        accepted = [x for x in accepted if x[1] not in failed]
    return (raw.decode("utf-8") if raw != text.encode() else text), report


def _undecided_kind(scope: dict[str, Any], why: str, position: int | None = None) -> str:
    """(review W5d · round 2 W-C) Why an ``undecided:`` condition is undecided, as far as filling an input can help:
    ``undecided_defined_after:`` (a macro the unit changes only after the function — `macro_changed_after`),
    ``undecided_varied:`` (its value changes inside the unit), ``undecided_reserved:`` (a name the implementation may
    define and the tree does not — no project file or -D settles it); plain ``undecided:`` otherwise (a name defined
    nowhere, or under an undecided #if: a definition or -D settles it). Other reasons as they are."""
    if not why.startswith("undecided:"):
        return why
    condition = why.split(":", 1)[1]
    if scope.get("body_table_unknown"):
        # (round 3) an unreadable body directive / unresolved in-body include stopped every body verdict of the unit
        return "body_table_unknown:" + ",".join(scope["body_table_unknown"])[:120]
    if _rests_on_missed(scope, condition):
        return "undecided_missed_definition:" + condition
    if position is not None and _defined_after(scope, condition, position):
        return "undecided_defined_after:" + condition
    names = set(re.findall(r"[A-Za-z_]\w*", condition)) - {"defined"}
    if names & set(scope.get("pp_varied") or ()):
        return "undecided_varied:" + condition
    defined = scope.get("pp_defined_anywhere") or set()
    if any(_implementation_may_define(n) and n not in defined for n in names):
        return "undecided_reserved:" + condition
    return why


def _projection_check(parser, new: bytes, shape: dict[tuple[int, str], bool], key: tuple[int, str]) -> str:
    """``projected`` when ``key``'s function parses without an error in ``new`` and every other function stays where it
    was with no new error; else why not."""
    after = _function_nodes(parser.parse(new).root_node, new)
    if set(after) != set(shape):
        return "function_set_changed"
    if _tree_has_error(after[key]):
        return "still_error"
    if any(_tree_has_error(n) and not shape[k] for k, n in after.items() if k != key):
        return "error_moved_to_another_function"
    return "projected"


def apply_body_projection(scope: dict[str, Any] | None, text: str) -> str:
    """(R62) The text a unit's consumers read: `project_body_conditionals` of ``text``, recorded in the scope —
    ``body_projection`` (the report), ``projected_sha256`` (so `scope_text_matches` accepts the projected text) and the
    names projected arms took as undefined (``assumed_undefined_body``, and per function ``assumed_at`` by start byte for
    the oracle's run record). Unchanged text when nothing was projected or the scope is of another text."""
    if not scope or not text:
        return text
    digest = hashlib.sha256(text.encode()).hexdigest()
    if digest == scope.get("projected_sha256"):
        return text
    if digest != scope.get("main_file_sha256"):
        return text
    try:
        new, report = project_body_conditionals(text, scope)
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, RecursionError, UnicodeError) as exc:
        # (review I6) a defect here leaves this file as it was read — counted, never stopping the document
        scope["body_projection"] = {"functions": [], "projected": 0, "error": f"projection_exception:{type(exc).__name__}"}
        return text
    scope["body_projection"] = report
    if new == text:
        return text
    scope["projected_sha256"] = hashlib.sha256(new.encode()).hexdigest()
    # (R63) what makes the text read differ from the file — the evidence's hash scope says it (`test_evidence`)
    scope["read_text_changes"] = [name for name, changed in (
        ("vendor_syntax_blanked", bool(report.get("blanked"))),
        ("bare_define_blanks_moved", _parse_safe(text.encode()) != text.encode()),
        ("body_conditionals_projected", bool(report.get("projected")))) if changed]
    assumed_at: dict[int, list[str]] = {}
    names: set[str] = set(scope.get("assumed_undefined_body") or ())
    for rec in report["functions"]:
        if rec["status"] == "projected" and rec["assumed_undefined"]:
            assumed_at[rec["start"]] = list(rec["assumed_undefined"])   # positions are kept by the projection
            names |= set(rec["assumed_undefined"])
    report["assumed_at"] = assumed_at
    scope["assumed_undefined_body"] = sorted(names)
    return new


def projected_texts(scopes: dict[str, dict[str, Any]], texts: dict[str, str]) -> dict[str, str]:
    """(R62 review W3) A new map: ``texts`` with each scoped unit as the generators read it (`apply_body_projection`).
    Every tool that builds scopes from texts and then reads or hashes a unit's text goes through this — a tool on the
    raw text sees the projected functions as ``source_parse_error`` and a generated row's hash as "changed"."""
    return {**texts, **{p: apply_body_projection(s, texts[p]) for p, s in scopes.items() if p in texts}}


def scope_text_matches(scope: dict[str, Any] | None, digest: str) -> bool:
    """Is ``digest`` the scope's own text — as read, or as `apply_body_projection` projected it?"""
    return bool(scope) and bool(digest) and digest in {scope.get("main_file_sha256"), scope.get("projected_sha256")}


def projected_assumptions(scope: dict[str, Any] | None, start: int) -> set[str]:
    """(R62) Names a projected arm of the function at ``start`` took as undefined (`apply_body_projection`)."""
    return set((((scope or {}).get("body_projection") or {}).get("assumed_at") or {}).get(start) or ())


def summarize_body_projection(scopes, only: set | None = None) -> dict[str, Any]:
    """(R62) The scopes' `body_projection` reports, totalled for a generator's summary: what was projected, and every
    compiled function whose tree still has an error, by reason — a parse failure is counted, never dropped.

    ``functions_with_tree_error`` counts the functions whose tree had an error and that the configuration compiles or
    may compile (projected ones included). ``only`` — ``{(scope path, function name)}`` of the functions the document
    has rows for (SUTS units): the others go to ``outside_document`` only (review W5a). ``not_projected_functions``
    lists at most 40 (``not_projected_total`` says how many)."""
    out: dict[str, Any] = {"files_projected": 0, "functions_with_tree_error": 0, "functions_projected": 0,
                           "conditions_decided": 0, "not_projected": {}, "projected_functions": [],
                           "not_projected_functions": [], "not_projected_total": 0, "assumed_undefined": [],
                           "outside_document": {"projected": 0, "not_projected": 0}, "projection_errors": 0,
                           "units_table_unknown": 0, "table_unknown_reasons": [],
                           "units_with_missed_definitions": 0, "missed_definitions": 0}
    assumed: set[str] = set()
    unknown_reasons: set[str] = set()
    for scope in scopes:
        if (scope or {}).get("body_table_unknown"):
            out["units_table_unknown"] += 1
            unknown_reasons.update(scope["body_table_unknown"])
        if (scope or {}).get("missed_definition_names"):
            out["units_with_missed_definitions"] += 1
            out["missed_definitions"] = max(out["missed_definitions"], len(scope["missed_definition_names"]))
        report = (scope or {}).get("body_projection") or {}
        if report.get("error"):
            out["projection_errors"] += 1
        path = (scope or {}).get("path")
        files_counted = False
        for rec in report.get("functions") or []:
            projected = rec.get("status") == "projected"
            if only is not None and (path, rec.get("name")) not in only:
                out["outside_document"]["projected" if projected else "not_projected"] += 1
                continue
            out["functions_with_tree_error"] += 1
            if projected:
                if not files_counted:
                    out["files_projected"] += 1
                    files_counted = True
                out["functions_projected"] += 1
                out["conditions_decided"] += int(rec.get("conditions") or 0)
                out["projected_functions"].append(rec.get("name") or "")
                assumed.update(rec.get("assumed_undefined") or ())
            else:
                reason = str(rec.get("status") or "")
                kind = reason.split(":", 1)[0]
                out["not_projected"][kind] = out["not_projected"].get(kind, 0) + 1
                out["not_projected_functions"].append(f"{rec.get('name') or '(이름 없음)'} ({reason[:60]})")
    out["projected_functions"] = sorted(out["projected_functions"])
    out["not_projected_total"] = len(out["not_projected_functions"])
    out["not_projected_functions"] = sorted(out["not_projected_functions"])[:40]
    out["assumed_undefined"] = sorted(assumed)
    out["table_unknown_reasons"] = sorted(unknown_reasons)[:20]
    return out


def summarize_source_reading(context: dict[str, Any] | None, scopes) -> dict[str, Any]:
    """(R63) How the C files a document's units read were read (each unit's scope ``files`` — its own file and every
    header it includes): vendor syntax read as blanks (`reading_text`), file-level directives read from the lexer that the
    parser's tree did not show (`_file_walk`), multi-line macros read without their line splices, the parse errors left
    by kind (`_parse_error_leaves`, with samples of the file-level ones the reader does not know) and the files the project
    context could not read at all (``incomplete_files`` · ``file_cap_reached`` of the source stage). {} when no unit has a
    scope."""
    files = (context or {}).get("files") or {}
    scopes = [s for s in scopes if s]
    reached = sorted({f for s in scopes for f in (s.get("files") or ()) if f in files})
    if not reached:
        return {}
    unread = list((context or {}).get("incomplete_files") or [])
    missing = {os.path.basename(m).lower() for s in scopes for m in (s.get("missing_includes") or ())}
    changed: dict[str, list[str]] = {}
    for s in scopes:
        if s.get("read_text_changes"):
            changed[s.get("path") or ""] = list(s["read_text_changes"])
    out: dict[str, Any] = {"files_read": len(reached), "vendor_blanks": {}, "files_with_vendor_syntax": 0,
                           "directives_beyond_tree": {}, "files_with_directives_beyond_tree": 0,
                           "spliced_macro_definitions": 0, "parse_errors": {}, "files_with_unknown_declarations": 0,
                           "unknown_declaration_samples": [], "files_with_asm": 0, "unbalanced_directives": {},
                           # (review round 1 I7) unread files of the whole tree, and those a unit of the document
                           # includes (a missing include of a reached scope names it)
                           "context_unread_files": len(unread),
                           "context_unread_sample": [os.path.basename(p) for p in unread[:8]],
                           "context_unread_included": sorted({os.path.basename(p) for p in unread
                                                              if os.path.basename(p).lower() in missing})[:8],
                           "context_file_cap_reached": bool((context or {}).get("file_cap_reached")),
                           # (review round 1 W2) units whose text read differs from the file — their evidence hash is of
                           # the text read (`apply_body_projection` · `read_text_changes`)
                           # (review round 4 I1) when a macro alias write is not resolved to its object anywhere
                           "alias_writes_unresolved": designator_gap(context) or (
                               "unreadable_directive" if any(d.get("op") == "unreadable" for rec in files.values()
                                                             for d in (rec.get("stray_directives") or {}).get("directives")
                                                             or ()) else ""),
                           "unit_files_text_changed": len(changed),
                           "text_change_kinds": {k: sum(1 for v in changed.values() if k in v)
                                                 for k in sorted({k for v in changed.values() for k in v})}}

    def add(into, counts):
        for k, v in (counts or {}).items():
            into[k] = into.get(k, 0) + int(v)
    for f in reached:
        reading = files[f].get("reading") or {}
        if reading.get("blanked"):
            out["files_with_vendor_syntax"] += 1
            add(out["vendor_blanks"], reading["blanked"])
        if reading.get("directives_beyond_tree"):
            out["files_with_directives_beyond_tree"] += 1
            add(out["directives_beyond_tree"], reading["directives_beyond_tree"])
        out["spliced_macro_definitions"] += int(reading.get("spliced_defines") or 0)
        for name in reading.get("unbalanced_brace_macros") or ():
            out.setdefault("unbalanced_brace_macros", [])
            if len(out["unbalanced_brace_macros"]) < 10:
                out["unbalanced_brace_macros"].append(f"{os.path.basename(f)}:{name}")
        errors = reading.get("errors") or {}
        kinds = errors.get("kinds") or {}
        add(out["parse_errors"], kinds)
        if kinds.get("declaration"):
            out["files_with_unknown_declarations"] += 1
            for line, kind, text in errors.get("samples") or []:
                if kind == "declaration" and len(out["unknown_declaration_samples"]) < 10:
                    out["unknown_declaration_samples"].append(f"{os.path.basename(f)}:{line} {text}")
        if kinds.get("asm"):
            out["files_with_asm"] += 1
        add(out["unbalanced_directives"], reading.get("unbalanced_directives"))
    return out


def macro_bodies(context: dict[str, Any]) -> dict[tuple[str, int], dict]:
    """Every ``#define`` of the project keyed by (file, position) — built once, shared by all units."""
    bodies: dict[tuple[str, int], dict] = {}
    for path, rec in (context.get("files") or {}).items():
        for name, defs in rec["macros"].items():
            for d in defs:
                bodies[(path, d["pos"])] = {**d, "name": name, "file": path}
    return bodies


def defined_names(context: dict[str, Any]) -> set[str]:
    """Every name some ``#define`` in the project defines — include guards included (they are events, not bodies)."""
    names: set[str] = set()
    stack = [ev for rec in (context.get("files") or {}).values() for ev in rec.get("events") or []]
    while stack:
        ev = stack.pop()
        if ev["op"] == "define":
            names.add(ev["name"])
        elif ev["op"] == "if":
            stack.extend(ev["then"])
            stack.extend(ev["else"])
    return names


def _changes_table(ev: dict[str, Any], path: str, mode: str, macros: dict[str, Any], bodies: dict) -> bool:
    """Does this ``#define``/``#undef`` event change the macro table (before it is applied)? In an undecided region it
    may — yes. A definition with the same body, function-likeness and parameters as the one in force does not; nor an
    ``#undef`` of a name that is not defined."""
    if mode != "active":
        return True
    prev = macros.get(ev["name"])
    if ev["op"] == "undef":
        return prev is not None
    if prev is None or prev == _UNKNOWN:
        return True
    old, new = bodies.get(prev) or {}, bodies.get((path, ev["pos"])) or {}

    def shape(d):
        return d.get("body"), bool(d.get("function_like")), tuple(d.get("params") or ())
    return shape(old) != shape(new)


def preprocess_unit(context: dict[str, Any], main: str, bodies: dict | None = None,
                    defines: dict[str, str] | None = None, known_names: set[str] | None = None,
                    build_defines_complete: bool = False, c_language: bool = False) -> dict[str, Any]:
    """Walk ``main`` and its quoted includes in order, tracking the macro table like the compiler would.

    Returns declaration states ``{(file, pos): "active" | "unknown"}`` (absent = not compiled in this
    configuration), the final macro table, macros whose value changed during the unit, and include facts.
    A condition that depends on an unknown macro makes *both* branches "unknown" — never a guess.
    ``defines`` are build-configuration macros (``-D``), when known; without them a name the tree never
    defines is undecided, not 0.
    """
    files = context.get("files") or {}
    parser = shared_parser()
    bodies = dict(bodies if bodies is not None else macro_bodies(context))
    macros: dict[str, Any] = {}
    for name, body in (defines or {}).items():
        bodies[("<build>", name)] = {"name": name, "body": body, "function_like": False, "file": "<build>", "line": 0}
        macros[name] = ("<build>", name)
    out: dict[str, Any] = {"states": {}, "macros": macros, "varied": set(), "missing_includes": [], "system_includes": [],
                           "toolchain_includes": [], "files": [], "errors": [], "unknown_conditions": 0, "gaps": 0,
                           "defined_after_gaps": {},
                           # (R62 review W1) name → the latest position in ``main`` (its last declaration or #define seen so
                           # far) at which a #define/#undef of the name — in any file — was met: a header included after a
                           # function changes the table after that function, though its definition sits in another file
                           "changed_at_main": {}}
    last_main = [-1]
    env = {"macros": macros, "bodies": bodies, "parser": parser, "gap": False, "varied": set(),
           "defined_anywhere": (known_names if known_names is not None else defined_names(context)) | set(defines or ()),
           "build_defines_complete": build_defines_complete, "assumed_undefined": set(),
           # (R63) no option compiles this C unit as C++: ``__cplusplus`` is no name the implementation defines
           "c_language": c_language}
    out["defined_anywhere"] = env["defined_anywhere"]
    out["assumed_undefined"] = env["assumed_undefined"]
    stack: list[str] = []

    def run(path, events, mode, depth):
        for ev in events:
            op = ev["op"]
            if path == main and op in ("decl", "define"):
                last_main[0] = max(last_main[0], int(ev["pos"]))
            if op in ("define", "undef") and _changes_table(ev, path, mode, macros, bodies):
                # (review round 2 W-A) only a real change: the same definition again (an unguarded header included
                # twice, ``#pragma once``) or ``#undef`` of an undefined name leaves the table as the function saw it
                changed = out["changed_at_main"]
                changed[ev["name"]] = max(changed.get(ev["name"], -1), last_main[0])
            if op == "decl":
                key = (path, ev["pos"])
                if mode == "active" or out["states"].get(key) != "active":
                    out["states"][key] = mode
            elif op == "define":
                key = (path, ev["pos"])
                if mode == "active":
                    prev = macros.get(ev["name"])
                    if prev is not None and (prev == _UNKNOWN or bodies.get(prev, {}).get("body") != bodies.get(key, {}).get("body")):
                        out["varied"].add(ev["name"])
                    macros[ev["name"]] = key
                else:
                    macros[ev["name"]] = _UNKNOWN
                # How many missing includes preceded this definition: one after it may #undef/redefine it.
                out["defined_after_gaps"][ev["name"]] = out["gaps"]
            elif op == "undef":
                if mode == "active":
                    if ev["name"] in macros:
                        out["varied"].add(ev["name"])
                    macros.pop(ev["name"], None)
                else:
                    macros[ev["name"]] = _UNKNOWN
            elif op == "error":
                if mode == "active":
                    out["errors"].append(f"{os.path.basename(path)}: #error {ev['text']}")
            elif op == "include":
                if ev["system"]:
                    if ev["name"] not in out["system_includes"]:
                        out["system_includes"].append(ev["name"])
                    continue
                found = _resolve_include(context, path, ev["name"])
                if not found and _toolchain_header(context, ev["name"]):
                    # Found nowhere in the tree, and the build searches toolchain directories: the compiler's header
                    # (C11 6.10.2p3 retries a failed quoted include as <...>). Treated like a system header.
                    if ev["name"] not in out["toolchain_includes"]:
                        out["toolchain_includes"].append(ev["name"])
                    continue
                if not found:
                    if ev["name"] not in out["missing_includes"]:
                        out["missing_includes"].append(ev["name"])
                    env["gap"] = True  # from here on, an absent name may be defined in the missing header
                    out["gaps"] += 1
                    continue
                if found in stack or depth > 32:
                    continue
                if found not in out["files"]:
                    out["files"].append(found)
                stack.append(found)
                run(found, files[found].get("events") or [], mode, depth + 1)
                stack.pop()
            elif op == "if":
                # Decided conditions are decided inside an undecided region too: whether the region runs does not
                # change the table before it. Not evaluating them re-ran a guarded header's whole body as "unknown"
                # when it was included again under an undecided ``#if`` — every macro it defines became unknown
                # (KJPDS02_PV: 5,923 of 5,933 macros, ``#ifndef COMMON_IT_H`` already defined; R2b).
                verdict = None if parser is None else _pp_condition(ev, env)
                if verdict is None:
                    if mode == "active":
                        out["unknown_conditions"] += 1
                    run(path, ev["then"], _UNKNOWN, depth)
                    run(path, ev["else"], _UNKNOWN, depth)
                else:
                    run(path, ev["then"] if verdict else ev["else"], mode, depth)

    if main in files:
        out["files"].append(main)
        stack.append(main)
        run(main, files[main].get("events") or [], "active", 0)
    return out


# ── Per translation unit scope ──────────────────────────────────────────────────────────────────

def translation_unit_scope(context: dict[str, Any], path: str, bodies: dict | None = None,
                           known_names: set[str] | None = None) -> dict[str, Any]:
    """Everything the ``.c`` file at ``path`` can see through its quoted includes (transitively), resolved."""
    files = context.get("files") or {}
    widths = (context.get("target") or {}).get("widths") or {}
    scope: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "path": path, "target": {"widths": widths},
                             "types": {}, "unresolved_types": {}, "constants": {}, "unresolved_constants": {},
                             "enum_types": {}, "globals": {}, "unresolved_globals": {}, "function_like_macros": [],
                             "function_like_macro_bodies": {}, "function_like_macro_params": {}, "arrays": {},
                             "struct_globals": {},   # (R39) struct objects whose members are modeled (`_scope_struct`)
                             "pointee_types": {},   # (R40) pointer parameters' pointee layouts (`_pointee_layout`)
                             "pointer_params": {},   # (R40) function → its ``T *p`` parameters (one definition only)
                             # (R39 review C3) the objects this unit does not model (a struct it cannot flatten among
                             # them) → internal linkage: another unit's modeled member of the same root may not be it
                             "unmodeled_object_linkage": {},
                             "missing_includes": [], "system_includes": [], "files": []}
    if path not in files:
        scope["status"] = "file_not_in_project_context"
        return scope
    build = _unit_build_defines(context, path)
    pp = preprocess_unit(context, path, bodies, defines=build["defines"], known_names=known_names,
                         build_defines_complete=build["complete"], c_language=not build.get("cplusplus_mode", True))
    # (R62 review round 2 W-B) a #define / #undef inside a function body of this unit changes the table for the code
    #   after it, where the file-level walk does not look: those names vary in the unit (undecided everywhere, never
    #   "undefined" on build evidence); an #include there may define anything (`body_includes` — a gap for body #if)
    # (R62 review rounds 2-4) a #define / #undef / #include the file-level walk does not read — in a function body (this
    #   file's or a header's inline function), in a construct the parser did not recognize, inside a struct / union
    #   declaration (Processor Expert ``IO_Map.h``: 1,057 #defines among the register struct members) — still acts where
    #   it stands. Judged by its effect on the table the walk built (local macros and functions the configuration leaves
    #   out aside, `_effective_strays`):
    #   · it changes a name the walk knows (#undef / #define of a known name), an #include, or a line not read → the
    #     walk's later choices may be wrong (round 4 G1): no body #if of the unit is decided (`body_table_unknown`), and
    #     the changed names vary on the value path;
    #   · it defines a name the walk never met → the table lacks that name: a condition resting on it is not decided
    #     (`missed_definition_names`), and a file-level #if testing it makes the table unknown (`_file_if_on`) — the
    #     walk chose that #if without it; values stay as before R62.
    strays = []
    for f in pp["files"]:
        stray = (files.get(f) or {}).get("stray_directives") or {}
        strays += [{**d, "file": f} for d in stray.get("directives") or ()]
    known = set(pp["defined_anywhere"])
    strays = _effective_strays(strays, known, pp["states"],
                               {f: _declared_positions(files.get(f) or {}) for f in {d["file"] for d in strays}})
    unknown: set[str] = set()
    changed: set[str] = set()
    missed: set[str] = set()
    includes: set[str] = set()
    for d in strays:
        where = os.path.basename(d["file"])
        if d["op"] == "unreadable":
            unknown.add("unreadable_directive:" + where)
        elif d["op"] == "include":
            found = _resolve_include(context, d["file"], d["name"])
            includes.add(d["name"])
            unknown.add(f"stray_directive:{where}:#include {d['name']}"[:120])
            names, complete = _names_a_file_changes(files, context, found) if found else (set(), False)
            changed |= names
            if not complete:
                unknown.add("unresolved_include:" + d["name"])
        elif d["name"] in known:
            unknown.add(f"stray_directive:{where}:#{d['op']} {d['name']}"[:120])
            changed.add(d["name"])
        else:
            missed.add(d["name"])
    on_missed = _file_if_on(files, pp["files"], missed, bodies)
    if on_missed:
        unknown.add("file_if_on_missed_definition:" + on_missed)
    scope["body_includes"] = sorted(includes)
    scope["missed_definition_names"] = sorted(missed)
    scope["body_directive_names"] = sorted(changed | missed)
    if changed:
        pp["varied"] |= changed
    if changed | missed:
        pp["defined_anywhere"] = set(pp["defined_anywhere"]) | changed | missed
    scope["body_table_unknown"] = sorted(unknown)
    scope["build_defines"] = {"evidence": build["evidence"], "complete": build["complete"], "reason": build["reason"],
                              "defines": dict(build["defines"]), "cplusplus_mode": build.get("cplusplus_mode", True)}
    scope["assumed_undefined"] = sorted(pp["assumed_undefined"])
    # (R17 review R2 W1) names a function-body #if of this unit takes as undefined on the same evidence (every body
    # condition's names — the MC/DC design and the disclosures read this; one oracle run records only what it met)
    scope["missing_includes"], scope["system_includes"], scope["files"] = pp["missing_includes"], pp["system_includes"], pp["files"]
    scope["toolchain_includes"] = pp["toolchain_includes"]
    scope["preprocessor"] = {"unknown_conditions": pp["unknown_conditions"], "errors": pp["errors"][:5],
                             "varied_macros": sorted(pp["varied"])[:20]}
    states = pp["states"]
    # Declarations this configuration compiles: "active", or "unknown" (under a condition the macro state does not
    # decide — kept, flagged conditional). Anything else is not compiled here and is not visible at all.
    scope["main_file_states"] = {pos: state for (p, pos), state in states.items() if p == path}
    scope["main_file_sha256"] = files[path]["sha256"]
    recs = [(p, files[p]) for p in pp["files"]]

    def visible(p, defs):
        for d in defs:
            state = states.get((p, d.get("pos")))
            if state is not None:
                yield {**d, "file": p, "conditional": state == _UNKNOWN}

    # typedefs
    raw_typedefs: dict[str, list[dict]] = {}
    for p, rec in recs:
        for name, defs in rec["typedefs"].items():
            raw_typedefs.setdefault(name, []).extend(visible(p, defs))
    raw_typedefs = {k: v for k, v in raw_typedefs.items() if v}
    # (R39) struct/union bodies this unit sees (by ``struct tag``, anonymous body key and typedef name)
    raw_structs: dict[str, list[dict]] = {}
    for p, rec in recs:
        for key, defs in (rec.get("structs") or {}).items():
            raw_structs.setdefault(key, []).extend(visible(p, defs))
    raw_structs = {k: v for k, v in raw_structs.items() if v}
    # (R35 review round 4 C4) the typedef names this unit sees, none defined under an undecided #if: a word a macro body
    # uses as a cast is one only if it is here. Fixed at build time — ``unresolved_types`` also holds conditional
    # typedefs and grows with every name a constant evaluation tried as a type (``type_undeclared:X``)
    scope["typedef_names"] = sorted(n for n, defs in raw_typedefs.items() if not any(d["conditional"] for d in defs))
    enums: dict[str, list[dict]] = {}
    for p, rec in recs:
        for key, defs in rec["enums"].items():
            enums.setdefault(key, []).extend(visible(p, defs))
    enums = {k: v for k, v in enums.items() if v}

    def resolve_type(name, depth=0):
        if name in scope["types"]:
            return scope["types"][name]
        if name in scope["unresolved_types"] or depth > 8:
            raise Unresolved(scope["unresolved_types"].get(name, "typedef_chain_too_deep"))
        tokens = name.split()
        qualifiers = {t for t in tokens if t in {"const", "volatile"}}
        core = " ".join(t for t in tokens if t not in {"const", "volatile"})
        if core.startswith("enum "):
            defs = enums.get(core) or []
            if len(defs) != 1 or defs[0]["conditional"]:
                raise Unresolved("enum_definition_missing_or_ambiguous")
            t = {**ctype("int", True, widths), "enum": core}
        elif core in raw_typedefs and (core in _PROJECT_MAY_TYPEDEF or base_kind(core) is None):
            # ``bool`` (not a keyword before C23 — ``<stdbool.h>`` makes it ``_Bool``) and the ``<stdint.h>`` names are
            # what the project says when it typedefs them itself: ``typedef unsigned char bool;`` keeps 2 as 2, not 1
            # (R16b review R2 — the clang check found the model normalising it)
            defs = raw_typedefs[core]
            bases = {d.get("base") for d in defs}
            if any(d.get("conditional") for d in defs) or len(bases) != 1:
                raise Unresolved("typedef_conditional_or_conflicting:" + core)
            d = defs[0]
            if d.get("shape") not in {"scalar", "enum"} or not d.get("base"):
                raise Unresolved("typedef_not_scalar:" + core)
            t = dict(resolve_type(d["base"], depth + 1))
            t["typedef"] = core
            if d.get("volatile"):
                qualifiers.add("volatile")
        elif (bk := base_kind(core)) is not None:
            if bk[1] is None:
                raise Unresolved("plain_char_signedness_unknown")
            t = ctype(bk[0], bk[1], widths)
        elif core in _STD_TYPES:
            # The width is fixed but the underlying type (and so its conversion rank) is the target's choice.
            raise Unresolved("stdint_type_rank_unknown:" + core)
        else:
            raise Unresolved("type_undeclared:" + core)
        if qualifiers:
            t = {**t, "qualifiers": sorted(qualifiers | set(t.get("qualifiers") or []))}
        return t

    def type_of(name):
        try:
            t = resolve_type(name)
            scope["types"][name] = t
            return t
        except Unresolved as exc:
            scope["unresolved_types"][name] = str(exc)
            raise

    for name in raw_typedefs:
        try:
            type_of(name)
        except Unresolved:
            pass  # recorded in unresolved_types
    for key, defs in enums.items():
        if len(defs) == 1 and not defs[0]["conditional"]:
            scope["enum_types"][key] = defs[0]

    # macros / enumerators → constants
    # The macro table at the end of the unit, as the preprocessor left it. A macro whose value changed during the
    # unit (redefinition, #undef) is not one constant for every use.
    macro_defs: dict[str, list[dict]] = {}
    for name, key in pp["macros"].items():
        if key == _UNKNOWN:
            macro_defs[name] = [{"body": "", "function_like": False, "conditional": True, "file": "", "line": 0}]
            continue
        p, pos = key
        if p == "<build>":
            # (R17) a -D of the build configuration: its body is the one the configuration gives
            macro_defs[name] = [{"body": str(build["defines"].get(name, "1")), "function_like": False,
                                 "conditional": False, "file": "<build>", "line": 0, "params": None}]
            continue
        d = next((x for x in files[p]["macros"].get(name, []) if x.get("pos") == pos), None)
        if d is not None:
            macro_defs[name] = [{**d, "file": p, "conditional": False}]
    undefs = set(pp["varied"])
    # (review R3 W-R3-1) through macro bodies too: ``#if FEATURE_X`` with ``#define FEATURE_X (CFG_B)`` rests on CFG_B
    reached, pending = set(), list(files[path].get("body_condition_names") or ())
    while pending and len(reached) < 4096:
        n = pending.pop()
        if n in reached:
            continue
        reached.add(n)
        for d in macro_defs.get(n) or ():
            pending.extend(re.findall(r"\b[A-Za-z_]\w*\b", str(d.get("body") or "")))
    scope["assumed_undefined_body"] = sorted(
        n for n in reached
        if build["complete"] and not pp.get("gaps") and n not in pp["defined_anywhere"]
        and not _implementation_may_define(n))
    # Final macro table for ``#if`` inside function bodies (``pp_condition``) — bodies after every header.
    scope["pp_macros"] = {name: (_UNKNOWN if key == _UNKNOWN else name) for name, key in pp["macros"].items()}
    scope["pp_bodies"] = {name: d[0] for name, d in macro_defs.items() if pp["macros"].get(name) != _UNKNOWN}
    scope["pp_varied"] = sorted(pp["varied"])
    scope["pp_defined_anywhere"] = pp["defined_anywhere"]
    # (R62 review W1) where in this unit's own text each macro last changed — see `macro_changed_after`
    scope["pp_changed_at"] = dict(pp["changed_at_main"])
    # Every active macro body (object-like too): what a macro *statement* or invocation does (callee checks).
    scope["macro_bodies"] = {name: d[0]["body"] for name, d in macro_defs.items()
                             if pp["macros"].get(name) != _UNKNOWN and name not in pp["varied"]}
    # Is this name a macro, and do we know its one body? "unknown" (defined under an undecided #if) and "varied"
    # (value changes in the unit) macros may expand to anything — including writes (R81 review round 2 C1).
    scope["macro_status"] = {name: ("unknown" if key == _UNKNOWN else "varied" if name in pp["varied"] else "active")
                             for name, key in pp["macros"].items()}
    scope["macro_status"].update({name: "varied" for name in pp["varied"] if name not in scope["macro_status"]})
    scope["prototypes"] = sorted({n for p, rec in recs for n in rec.get("prototypes") or ()})
    scope["pp_assumptions"] = [
        "a name some project file #defines is not also a build -D (a name the tree never defines is undecided unless "
        "the build configuration's -D set is known — see below)",
        *(["the build configuration " + os.path.basename(os.path.dirname(scope["build_defines"]["evidence"])) + "/.cproject "
           "defines only the macros its compiler options list (" + (", ".join(sorted(scope["build_defines"]["defines"]))
                                                                    or "none") + "); a name that neither the tree nor "
           "the build defines and that is not the implementation's (no leading underscore, no standard name — or is "
           "__cplusplus, which no C implementation predefines, C11 6.10.8p3) is undefined "
           "in #if — assuming the toolchain plugin's default options add no -D (the file stores only non-default values), "
           "the compiler predefines only reserved names, headers outside the tree (toolchain hidef.h/stdtypes.h, <...>) "
           "and the build environment (COMPOPTIONS, DEFAULT.ENV) define none of these: "
           + ", ".join(scope["assumed_undefined"][:12])
           + (f" (+{len(scope['assumed_undefined']) - 12})" if len(scope["assumed_undefined"]) > 12 else "")]
          if scope["assumed_undefined"] else []),
        "system headers (<...>) do not define names the project defines",
        "a quoted include found nowhere in the source tree, in a build whose configuration lists toolchain include "
        "directories, is a toolchain header (C11 6.10.2p3) and, like <...> headers, does not define project names",
        "floating literals round to nearest (IEC 60559)",
        "a call to a name declared nowhere (unit without missing includes) is a function, not a -D macro",
        "inline assembly does not write C objects by name",
    ]
    enumerators: dict[str, list[tuple[str, int, dict]]] = {}
    for key, defs in enums.items():
        for d in defs:
            for position, member in enumerate(d["members"]):
                enumerators.setdefault(member["name"], []).append((key, position, d))
    global_defs: dict[str, list[dict]] = {}
    for p, rec in recs:
        for name, defs in rec["globals"].items():
            global_defs.setdefault(name, []).extend(visible(p, defs))
    global_defs = {k: v for k, v in global_defs.items() if v}
    parser = _make_parser()
    evaluating: set[str] = set()

    def constant(name, mode="f64"):
        if dict.__contains__(scope["constants"], name):
            c = dict.__getitem__(scope["constants"], name)
            return (c.get("float_values") or {}).get(mode, c["value"]), c["type"]
        if name in scope["unresolved_constants"]:
            raise Unresolved(scope["unresolved_constants"][name])
        if name in evaluating:
            raise Unresolved("macro_recursion")
        evaluating.add(name)
        try:
            value, t, origin = _constant(name)
            dict.__setitem__(scope["constants"], name, {"value": value, "type": t, **origin})
            return (origin.get("float_values") or {}).get(mode, value), t
        except Unresolved as exc:
            if str(exc) != "identifier_undeclared":  # not a macro/enumerator at all: nothing to record here
                scope["unresolved_constants"][name] = str(exc)
            raise
        finally:
            evaluating.discard(name)

    def agreeing(text, *, macro_body):
        """Value of a constant expression, the same in every floating evaluation format (review W4: macros,
        enumerators and const initializers alike). A macro body must also bind as one operand (review C1)."""
        if macro_body:
            node, _raw = _parse_body(text, parser)
            if node is not None and not self_delimiting(node):
                raise Unresolved("macro_body_not_parenthesized")
        flags: dict[str, bool] = {}
        value, t = evaluate_constant_expression(text, parser, widths, constant, type_of, global_defs, "f64", flags)
        extra: dict[str, Any] = {}
        if flags.get("float"):
            others = {m: evaluate_constant_expression(text, parser, widths, constant, type_of, global_defs, m, {})[0]
                      for m in FLOAT_MODES[1:]}
            if is_float(t):
                extra["float_values"] = others
            elif any(v != value for v in others.values()):
                raise Unresolved("float_precision_dependent:" + "/".join(
                    f"{m}={v}" for m, v in {"f64": value, **others}.items()))
            extra["float_evaluation"] = True
        return value, t, extra

    def _constant(name):
        if name in macro_defs:
            defs = macro_defs[name]
            if name in undefs:
                raise Unresolved("macro_value_varies_in_unit")
            if pp["defined_after_gaps"].get(name, 0) < pp["gaps"]:
                # A quoted include after this definition could not be read: it may #undef or redefine it (review W2).
                raise Unresolved("macro_unverified_missing_include")
            if any(d["conditional"] for d in defs):
                raise Unresolved("macro_defined_conditionally")
            if any(d["function_like"] for d in defs):
                raise Unresolved("function_like_macro")
            if len({d["body"] for d in defs}) != 1:
                raise Unresolved("macro_redefined_differently")
            if not defs[0]["body"]:
                raise Unresolved("macro_without_value")
            origin = {"kind": "macro", "file": defs[0]["file"], "line": defs[0]["line"], "text": defs[0]["body"][:120]}
            # The evaluation format is the target's choice (FLT_EVAL_METHOD, double width): an integer result must
            # be the same in every mode, or it is not a value the source determines.
            value, t, extra = agreeing(defs[0]["body"], macro_body=True)
            return value, t, {**origin, **extra}
        if name in enumerators:
            if len(enumerators[name]) != 1:
                raise Unresolved("enumerator_ambiguous")
            key, position, d = enumerators[name][0]
            if d["conditional"]:
                raise Unresolved("enum_defined_conditionally")
            value = -1
            for member in d["members"][:position + 1]:
                if member["value"] is None:
                    value = value + 1
                else:
                    value, member_t, _extra = agreeing(member["value"], macro_body=False)
                    if is_float(member_t):
                        raise Unresolved("enumerator_not_integer")
            t = ctype("int", True, widths)
            lo, hi = type_range(t)
            if not lo <= value <= hi:
                raise Unresolved("enumerator_out_of_int_range")
            return value, t, {"kind": "enumerator", "enum": key, "line": d["line"]}
        raise Unresolved("identifier_undeclared")

    for name in macro_defs:
        if any(d["function_like"] for d in macro_defs[name]):
            scope["function_like_macros"].append(name)
            defs = macro_defs[name]
            if name not in undefs and not any(d["conditional"] for d in defs) and len({d["body"] for d in defs}) == 1:
                # Only an unambiguous body can show what an invocation does (callee side-effect checks).
                scope["function_like_macro_bodies"][name] = defs[0]["body"]
                if "params" in defs[0]:
                    scope["function_like_macro_params"][name] = list(defs[0]["params"])
    # Constants are resolved on first lookup (review W7: evaluating every visible macro up front — the 671 KB
    # register header, in every unit — was most of the scope cost). Lookups populate `unresolved_constants`.
    scope["constants"] = _LazyConstants(constant)

    # (R39 review round 3 W-r3) every name a visible file defines or undefines as a macro — ``#define MEMBERS …`` used in a
    # struct body and ``#undef``-ed after it is not in the end-of-unit table, yet it named the members
    every_macro_name = {n for _p, rec in recs for n in (rec.get("macros") or {})} | \
        {u for _p, rec in recs for u in (rec.get("undefs") or [])}

    # globals visible to this translation unit
    for name, defs in global_defs.items():
        is_static = any(x.get("static") for x in defs)
        try:
            if name in macro_defs or name in enumerators:
                raise Unresolved("name_is_also_a_macro_or_constant")
            if any(d["conditional"] for d in defs):
                raise Unresolved("global_declared_conditionally")
            if len({(d["type"], d["shape"]) for d in defs}) != 1:
                raise Unresolved("global_declarations_disagree")
            d = defs[0]
            if d["shape"] == "array" and d["type"] != "struct":
                _scope_array(scope, name, defs, pp, type_of, agreeing, parser)
            if d["shape"] == "scalar":
                _scope_struct(scope, name, defs, raw_structs, pp, type_of, agreeing,   # (R39) no-op unless a struct
                              macro_names=every_macro_name)
            if d["shape"] != "scalar":
                raise Unresolved("global_not_scalar:" + d["shape"])
            if d["type"] == "struct":
                raise Unresolved("global_not_scalar:struct")
            if pp["gaps"]:
                # A header this unit includes could not be read: it may turn this name into a macro (review W2).
                raise Unresolved("global_unverified_missing_include")
            t = type_of(d["type"])
            volatile = any(x["volatile"] for x in defs) or "volatile" in (t.get("qualifiers") or [])
            const = any(x["const"] for x in defs) or "const" in (t.get("qualifiers") or [])
            inits = [x for x in defs if x.get("init")]
            if const and not volatile and len(inits) == 1 and not inits[0]["init"].startswith("{"):
                # A const object's value is its initializer (modifying it is undefined behavior) — when the one
                # initialized definition is visible to this unit, it is a constant, not an input.
                try:
                    value, _vt, _extra = agreeing(inits[0]["init"], macro_body=False)
                    scope["constants"][name] = {"value": convert(value, t), "type": t, "kind": "const_object",
                                                "file": inits[0]["file"], "line": inits[0]["line"],
                                                "static": bool(inits[0].get("static")), "typename": d["type"],
                                                "text": inits[0]["init"][:120]}
                    continue
                except Unresolved as exc:
                    scope["unresolved_constants"][name] = "const_initializer_unresolved:" + str(exc)
            if const and not volatile and not inits and any(x.get("static") for x in defs) \
                    and not any(x.get("initialized") for x in defs) and not all(x.get("extern") for x in defs):
                # (R67 review W-1) ``static const U8 k;`` — a tentative definition with internal linkage is 0 at the end
                #   of the unit (C11 6.9.2p2): a constant, never another unit's definition of the name
                scope["constants"][name] = {"value": 0, "type": t, "kind": "const_object", "file": d["file"],
                                            "line": d["line"], "static": True, "typename": d["type"],
                                            "text": "tentative_definition"}
                continue
            # ``static``: internal linkage — the object belongs to this translation unit (R16: an interpreted callee of
            # another unit must not read it by the same name)
            scope["globals"][name] = {"type": t, "typename": d["type"], "file": d["file"], "line": d["line"],
                                      "volatile": volatile, "const": const, "static": any(x.get("static") for x in defs),
                                      # (R67 review W-1) only a unit that merely declares it takes another unit's value
                                      "declared_only": all(x.get("extern") for x in defs)}
        except Unresolved as exc:
            scope["unresolved_globals"][name] = str(exc)
            scope["unmodeled_object_linkage"][name] = is_static
    # (R40) what the pointer parameters of this unit's functions point to — a test sequence sets the pointee by
    # ``p[0]`` / ``p[0].a`` (the reference writes ``pProfile[0].s32_SOP``). Only the types the unit's own functions take:
    # a layout per struct type in every unit would hold every register block of every header
    for fn_name, fn_defs in (files[path].get("functions") or {}).items():
        if len(fn_defs) == 1:
            scope["pointer_params"][fn_name] = list(fn_defs[0].get("pointer_params") or [])
        for fd in fn_defs:
            for pp_ in fd.get("pointer_params") or []:
                core = " ".join(w for w in str(pp_.get("type") or "").split() if w not in {"const", "volatile"})
                if not core or core in scope["pointee_types"]:
                    continue
                scope["pointee_types"][core] = _pointee_layout(core, raw_structs, type_of, agreeing, every_macro_name,
                                                               gaps=bool(pp["gaps"]))
    scope["status"] = "resolved" if not scope["missing_includes"] else "partial"
    return scope


def _flatten_struct(key, raw_structs, type_of, agreeing, macro_names=(), volatile=False):
    """(R39, R40) The scalar members of the struct ``key`` → ({path: (kind, record)}, [unmodeled member paths]).
    Unresolved when the body cannot be flattened (see `_scope_struct` — the rules a struct object and a pointer
    parameter's pointee share)."""
    unmodeled: list[str] = []

    def walk(k, prefix, volatile, depth):
        """The scalar members under ``k`` → {path: (kind, record)}; Unresolved when the body cannot be flattened."""
        entries = raw_structs.get(k) or []
        if depth > 4 or len(entries) != 1 or entries[0].get("conditional"):
            raise Unresolved("struct_definition_missing_or_ambiguous")
        e = entries[0]
        if e.get("alias"):
            if e.get("const"):
                raise Unresolved("const_struct_type")   # ``typedef const struct {…} CT;`` (review C1)
            return walk(e["alias"], prefix, volatile or bool(e.get("volatile")), depth + 1)
        if e.get("union"):
            raise Unresolved("union")
        if e.get("hidden"):
            raise Unresolved("struct_body_hides_members")   # ``#if`` around a member, an unnamed member (review C2)
        if e.get("bit_fields"):
            raise Unresolved("bit_field_member")
        out: dict[str, tuple[str, dict]] = {}
        for m in e["members"]:
            if not m.get("name"):
                raise Unresolved("unnamed_member")
            if m["name"] in macro_names or any(w in macro_names for w in str(m.get("type") or "").split()):
                # (review round 2 W2) ``U8 MEMBERS;`` with ``#define MEMBERS a; U8 *hp``: the text is not the members
                raise Unresolved("struct_member_named_by_macro")
            path = f"{prefix}.{m['name']}" if prefix else m["name"]
            vol = volatile or bool(m.get("volatile"))
            core = " ".join(w for w in str(m.get("type") or "").split() if w not in {"const", "volatile"})
            if m.get("const") or m.get("shape") not in {"scalar", "array"}:
                unmodeled.append(path)   # a const or pointer / function-pointer member: no input slot
                continue
            if core in raw_structs:
                if m.get("dims"):
                    unmodeled.append(path)   # an array of structs
                    continue
                try:
                    out.update(walk(core, path, vol, depth + 1))
                except Unresolved:
                    unmodeled.append(path)   # a nested struct that cannot be flattened: none of its members
                continue
            try:
                t = type_of(m["type"])
            except Unresolved:
                unmodeled.append(path)
                continue
            vol = vol or "volatile" in (t.get("qualifiers") or [])
            dims = m.get("dims") or []
            if not dims:
                out[path] = ("scalar", {"type": t, "typename": core, "volatile": vol})
                continue
            length = None
            if len(dims) == 1 and dims[0]:
                try:
                    value, lt, _extra = agreeing(dims[0], macro_body=False)
                    if not is_float(lt) and type(value) is int and value > 0:
                        length = value
                except Unresolved:
                    length = None
            if length is None:
                unmodeled.append(path)   # a multi-dimensional member or one whose length is not a known constant
                continue
            out[path] = ("array", {"type": t, "typename": core, "volatile": vol, "length": length})
        return out

    return walk(key, "", volatile, 0), unmodeled


def _pointer_params(fn, raw):
    """(R40) ``{"name", "type"}`` of each parameter declared ``T *name`` — one level, a plain name (``T **pp``,
    ``T *a[]``, a function pointer are not); ``type`` is the pointee type with the declaration's own qualifiers
    (``const T *p`` → ``const T``; a qualifier after the ``*`` is the pointer's, not kept)."""
    _, fdecl = _function_name(fn, raw)
    plist = fdecl.child_by_field_name("parameters") if fdecl is not None else None
    out = []
    for prm in plist.named_children if plist is not None else []:
        if prm.type != "parameter_declaration":
            continue
        d = prm.child_by_field_name("declarator")
        if d is None or d.type != "pointer_declarator":
            continue
        inner = d.child_by_field_name("declarator")
        typ = prm.child_by_field_name("type")
        if inner is None or inner.type != "identifier" or typ is None:
            continue
        quals = [_text(c, raw) for c in prm.named_children if c.type == "type_qualifier"]
        out.append({"name": _text(inner, raw), "type": " ".join(quals + [" ".join(_text(typ, raw).split())])})
    return out


def _pointee_layout(core, raw_structs, type_of, agreeing, macro_names, gaps=False):
    """(R40) What a ``core *`` parameter points to: ``{"members": {path: rec}, "arrays": {path: rec}, "opaque": bool}``
    — a scalar type is the one member ``""`` (``p[0]``), a struct its flattened members (``.a`` → ``p[0].a``, the rules
    of `_flatten_struct`); ``{"reason": …}`` when neither. ``gaps``: the unit's preprocessing left gaps (an unreadable
    include, an undecided #if) — a struct body may hold members it cannot see (review R40 I4, as `_scope_struct`)."""
    if core in raw_structs:
        if gaps:
            return {"reason": "preprocessing_gaps"}
        try:
            leaves, unmodeled = _flatten_struct(core, raw_structs, type_of, agreeing, macro_names)
        except Unresolved as exc:
            return {"reason": str(exc)}
        members = {"." + path: r for path, (kind, r) in leaves.items() if kind == "scalar"}
        arrays = {"." + path: r for path, (kind, r) in leaves.items() if kind == "array"}
        return {"members": members, "arrays": arrays, "opaque": bool(unmodeled)}
    try:
        t = type_of(core)
    except Unresolved as exc:
        return {"reason": str(exc)}
    if not isinstance(t, dict):
        return {"reason": "pointee_type_unresolved"}
    return {"members": {"": {"type": t, "typename": core, "volatile": "volatile" in (t.get("qualifiers") or [])}},
            "arrays": {}, "opaque": False}


def _scope_struct(scope, name, defs, raw_structs, pp, type_of, agreeing, macro_names=()):
    """(R39) A global of a struct type the unit sees the body of: each scalar member — nested structs flattened, one-
    dimensional member arrays — becomes an object of its own, ``g.a`` in ``globals`` and ``g.b`` in ``arrays``: the
    name a test sequence sets it by (the reference writes ``lin_tl_rx_queue.queue_header``). The struct object itself
    stays unresolved (a whole-struct read or write is not modeled). Not modeled at all: a union (members alias), a
    bit-field member, a ``const`` object, an array of structs, a body seen more than once or under an undecided #if,
    an unreadable include. A pointer member, a member of an unresolved type or shape is left out and flags the struct
    ``opaque_members`` (a write to the object may go through something no member names)."""
    d = defs[0]
    words = [w for w in str(d["type"]).split() if w not in {"const", "volatile"}]
    key = d.get("struct_key") if d["type"] == "struct" else " ".join(words)
    if not key or key not in raw_structs or pp["gaps"] or any(x.get("const") for x in defs) \
            or any(x.get("dims") for x in defs):
        return
    try:
        leaves, unmodeled = _flatten_struct(key, raw_structs, type_of, agreeing, macro_names,
                                            any(x.get("volatile") for x in defs))
    except Unresolved:
        return
    if not leaves:
        return
    static = any(x.get("static") for x in defs)
    for path, (kind, r) in leaves.items():
        rec = {"type": r["type"], "typename": r["typename"], "file": d["file"], "line": d["line"],
               "volatile": r["volatile"], "const": False, "static": static, "member_of": name}
        if kind == "scalar":
            scope["globals"][f"{name}.{path}"] = rec
        else:
            scope["arrays"][f"{name}.{path}"] = {**rec, "length": r["length"], "values": None}
    scope["struct_globals"][name] = {"typename": key, "file": d["file"], "line": d["line"], "static": static,
                                     "members": sorted(leaves), "unmodeled_members": unmodeled[:20],
                                     "opaque_members": bool(unmodeled)}


def _scope_array(scope, name, defs, pp, type_of, agreeing, parser):
    """A one-dimensional array of a resolved scalar element type: element type, length and — for a ``const``
    object with one visible initialized definition — its element values. Anything else stays unrecorded (the
    array is then no modeled object; ``unresolved_globals`` keeps its reason)."""
    dims = {tuple(x.get("dims") or ()) for x in defs}
    lengths = {x[0] for x in dims if len(x) == 1 and x[0]}
    if any(len(x) != 1 for x in dims) or len(lengths) > 1 or pp["gaps"]:
        return
    try:
        elem = type_of(defs[0]["type"])
        length = None
        if lengths:
            value, t, _extra = agreeing(next(iter(lengths)), macro_body=False)
            if is_float(t) or type(value) is not int or value <= 0:
                return
            length = value
        volatile = any(x["volatile"] for x in defs) or "volatile" in (elem.get("qualifiers") or [])
        const = any(x["const"] for x in defs) or "const" in (elem.get("qualifiers") or [])
        record = {"type": elem, "typename": defs[0]["type"], "length": length, "file": defs[0]["file"],
                  "line": defs[0]["line"], "volatile": volatile, "const": const, "values": None,
                  "static": any(x.get("static") for x in defs)}
        inits = [x for x in defs if x.get("array_init") or x.get("array_init_truncated")]
        if const and not volatile and len(inits) == 1 and inits[0].get("array_init"):
            record["values"], unread = _array_values(inits[0]["array_init"], elem, length, agreeing, parser)
            if record["values"] is not None and length is None:
                record["length"] = len(record["values"])
            if unread:
                record["values_unread"] = unread
        elif const and not volatile:
            # (R67, audit #45) why a const table's values are not held — the reader then says so instead of asking the
            #   test for an initial value it cannot set (a definition in another unit is linked in `build_scopes`)
            if inits:
                record["values_unread"] = ("initializer_over_budget" if any(x.get("array_init_truncated") for x in inits)
                                           else "initialized_in_several_definitions")
            elif any(x.get("initialized") for x in defs):
                # (review round 3 I-4) ``typedef const U8 CU8; static CU8 t[3] = {…};`` — the declaration does not say
                #   const, so its initializer was not kept
                record["values_unread"] = "const_by_typedef_initializer_not_kept"
            elif all(x.get("extern") for x in defs):
                record["values_unread"] = "no_initializer_in_unit"        # declared only: `_link_const_arrays`
            elif any(x.get("static") for x in defs) and not any(x.get("initialized") for x in defs) \
                    and length is not None and length <= _ARRAY_VALUES_BUDGET:
                # (R67 review W-1) ``static const U8 t[3];`` — a tentative definition with internal linkage: zero at the
                #   end of the unit (C11 6.9.2p2), never another unit's table
                record["values"], record["values_source"] = [0] * length, "tentative_definition"
            else:
                record["values_unread"] = "tentative_definition"          # an external one: no other unit's table either
        scope["arrays"][name] = record
    except Unresolved:
        return


def _array_values(text, elem, length, agreeing, parser):
    """Element values of a const array's initializer → ``(values, "")``, or ``(None, reason)``.

    Positional items and (R67) index designators ``[k] = v`` (C11 6.7.9p17: a designator moves the position, the next
    item continues after it, a later initializer of the same element overrides it); elements no initializer names are 0
    (6.7.9p10), and with no declared length the largest index sets it (6.7.9p22). Not read (reason): a nested list (a 2-D
    table, struct elements), a member designator, an item that is no integer constant expression, a float, an index past
    the declared length."""
    raw = ("int __probe[] = " + text + ";").encode("utf-8")
    root = parser.parse(raw).root_node
    init = next((x for x in _walk(root) if x.type == "initializer_list"), None)
    if root.has_error or init is None or _text(init, raw) != text.strip():
        return None, "initializer_unparsed"
    if is_float(elem):
        return None, "floating_elements"
    if length is not None and length > _ARRAY_VALUES_BUDGET:
        return None, "length_over_budget"
    values: dict[int, int] = {}
    position = 0
    for c in (x for x in init.named_children if x.type != "comment"):
        node = c
        if c.type == "initializer_pair":
            designators = c.children_by_field_name("designator")
            node = c.child_by_field_name("value")
            index_nodes = [x for x in designators[0].named_children if x.type != "comment"] \
                if len(designators) == 1 and designators[0].type == "subscript_designator" else []
            if len(index_nodes) != 1 or node is None:
                return None, "designator_unsupported"
            try:
                index, it, _extra = agreeing(_text(index_nodes[0], raw), macro_body=False)
            except Unresolved as exc:
                return None, "designator_index_unresolved:" + str(exc)
            if is_float(it) or type(index) is not int or index < 0:
                return None, "designator_index_not_an_index"
            if index >= _ARRAY_VALUES_BUDGET:
                return None, "length_over_budget"
            position = index
        if node.type == "initializer_list":
            return None, "nested_initializer_list"
        if length is not None and position >= length:
            return None, "initializer_past_length"
        try:
            value, t, _extra = agreeing(_text(node, raw), macro_body=False)
        except Unresolved as exc:
            return None, "element_unresolved:" + str(exc)
        if is_float(t):
            return None, "floating_element"
        try:
            values[position] = convert(value, elem)
        except Unresolved as exc:
            return None, "element_unresolved:" + str(exc)
        position += 1
    size = length if length is not None else (max(values) + 1 if values else 0)
    return [values.get(i, 0) for i in range(size)], ""


class _LazyConstants(dict):
    """A unit's constants, resolved when first asked for (``name in constants`` / ``constants[name]``)."""

    def __init__(self, resolve):
        super().__init__()
        self._resolve = resolve

    def __contains__(self, name):
        if dict.__contains__(self, name):
            return True
        if not isinstance(name, str):
            return False
        try:
            self._resolve(name)
        except (Unresolved, RecursionError):
            return False
        return dict.__contains__(self, name)

    def __getitem__(self, name):
        if name not in self:
            raise KeyError(name)
        return dict.__getitem__(self, name)

    def get(self, name, default=None):
        return self[name] if name in self else default


def _resolve_include(context, current, name):
    """Quoted include → project header. Same directory first, then a unique basename match (case-insensitive, as the
    Windows build resolves it). Ambiguous basenames stay unresolved rather than picking one."""
    local = os.path.normcase(os.path.normpath(os.path.join(os.path.dirname(current), name)))
    for p in context["files"]:
        if os.path.normcase(os.path.normpath(p)) == local:
            return p
    candidates = context["headers"].get(os.path.basename(name).lower()) or []
    if len(candidates) > 1 and context.get("roots"):
        # Several source roots are separate builds (APP and BOOT both have ``lin.h``): each sees its own tree only.
        mine = _root_of(context, current)
        candidates = [c for c in candidates if mine and _root_of(context, c) == mine]
    return candidates[0] if len(candidates) == 1 else ""


def summarize_build_assumptions(scopes) -> dict[str, Any]:
    """(R17) What the #if verdicts of these units rest on, for a generation's disclosure: how many units had complete
    build-configuration evidence, why the others did not, and which names were taken as undefined on it."""
    from collections import Counter
    seen, reasons, names, units, complete, with_names = set(), Counter(), set(), 0, 0, 0
    for scope in scopes:
        if not isinstance(scope, dict) or id(scope) in seen:
            continue
        seen.add(id(scope))
        units += 1
        build = scope.get("build_defines") or {}
        if build.get("complete"):
            complete += 1
        else:
            reasons[str(build.get("reason") or "no_build_configuration_for_unit")] += 1
        assumed = set(scope.get("assumed_undefined") or ()) | set(scope.get("assumed_undefined_body") or ())
        if assumed:
            with_names += 1
            names.update(assumed)
    return {"units": units, "units_with_complete_build_evidence": complete, "incomplete_reasons": dict(reasons),
            "units_with_assumed_undefined": with_names, "assumed_undefined_names": sorted(names)[:40],
            "assumed_undefined_total": len(names)}


def _unit_build_defines(context, path):
    """(R17) The build configuration that compiles ``path``: the ``.cproject`` of its source root (the only one when the
    context has one root and one configuration). Unknown → not complete (names stay undecided, as before)."""
    configs = ((context.get("build") or {}).get("configurations") or {})
    root = _root_of(context, path)
    chosen = None
    if root:
        chosen = next((p for p in configs if os.path.normcase(os.path.dirname(os.path.normpath(p))) == root), None)
    elif len(configs) == 1 and not (context.get("roots") or ()):
        chosen = next(iter(configs))   # (review I4) a unit outside the one root is not that build's
    if chosen is None:
        return {"evidence": "", "complete": False, "reason": "no_build_configuration_for_unit", "defines": {}}
    rec = configs[chosen]
    return {"evidence": chosen, "complete": bool(rec.get("complete")), "reason": rec.get("reason", ""),
            "defines": dict(rec.get("defines") or {}), "cplusplus_mode": bool(rec.get("cplusplus_mode", True))}


def _same_build(context, a, b) -> bool:
    """(R67) Two files of one build: the same source root (APP and BOOT are separate builds). Without roots there is one
    build; a file outside every root belongs to none (review round 3 I-5 — ``"" == ""`` linked them)."""
    if not context.get("roots"):
        return True
    root = _root_of(context, a)
    return bool(root) and root == _root_of(context, b)


def _root_of(context, path):
    p = os.path.normcase(os.path.normpath(path))
    for r in context.get("roots") or ():
        rn = os.path.normcase(os.path.normpath(r))
        if p == rn or p.startswith(rn.rstrip("\\/") + os.sep):
            return rn
    return ""


def evaluate_constant_expression(text, parser, widths, constant, type_of, global_defs=None, mode="f64", flags=None):
    """Constant expression → (value, C type). Identifiers resolve through ``constant(name, mode)``; casts through
    ``type_of``. ``flags["float"]`` is set when floating arithmetic took part (the caller then re-checks in f32)."""
    if parser is None:
        raise Unresolved("tree_sitter_unavailable")
    if len(text) > 2000:
        raise Unresolved("macro_body_budget")
    raw = ("int __probe = (" + text + ");").encode("utf-8")
    root = parser.parse(raw).root_node
    if root.has_error:
        raise Unresolved("macro_body_not_an_expression")
    init = next((n for n in _walk(root) if n.type == "init_declarator"), None)
    value = init.child_by_field_name("value") if init is not None else None
    if value is None or _text(value, raw) != "(" + text + ")":
        raise Unresolved("macro_body_not_an_expression")
    env = {"raw": raw, "widths": widths, "constant": constant, "type_of": type_of, "globals": global_defs or {},
           "mode": mode, "flags": flags if flags is not None else {}}
    return _eval(value, env, 0)


def _walk(node):
    stack = [node]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(reversed(item.named_children))


def _cast(env, type_node, operand):
    return _cast_to(env, " ".join(_text(type_node, env["raw"]).split()), operand)


def _cast_to(env, type_text, operand):
    t = env["type_of"](type_text)
    if is_float(t):
        env["flags"]["float"] = True
    return convert(operand[0], t, env["mode"]), t


def _names_type(env, name) -> bool:
    """(R67) Whether a parenthesized name in a constant expression is a type: not an object, a macro or an enumerator of
    that name (the preprocessor runs first; objects and typedef names share C's one ordinary namespace), and the scope
    resolves it as a type (an object's name is no typedef there, so ``(g)-1`` stays a subtraction)."""
    try:
        env["constant"](name, env["mode"])
        return False                       # a macro / enumerator value — the subtraction it reads as
    except Unresolved as exc:
        if str(exc) != "identifier_undeclared":
            return False                   # a macro, enumerator or object that does not evaluate: no type read into it
    try:
        return isinstance(env["type_of"](name), dict)
    except Unresolved:
        return False


def _eval(n, env, depth):
    if depth > 64:
        raise Unresolved("expression_depth_budget")
    raw, widths, mode = env["raw"], env["widths"], env["mode"]
    kind = n.type
    if kind == "parenthesized_expression":
        children = [c for c in n.named_children if c.type != "comment"]
        if len(children) != 1:
            raise Unresolved("unsupported_parenthesized_expression")
        return _eval(children[0], env, depth + 1)
    if kind == "number_literal":
        value, t = literal(_text(n, raw), widths, mode)
        if is_float(t):
            env["flags"]["float"] = True
        return value, t
    if kind == "char_literal":
        raise Unresolved("char_literal_unsupported")
    if kind in NAME_NODE_TYPES:  # (R35) ``TRUE``/``FALSE`` are names here too
        name = _text(n, raw)
        if name in env["globals"]:
            raise Unresolved("depends_on_variable:" + name)
        value, t = env["constant"](name, mode)
        if is_float(t):
            env["flags"]["float"] = True
        return value, t
    if kind == "cast_expression":
        return _cast(env, n.child_by_field_name("type"), _eval(n.child_by_field_name("value"), env, depth + 1))
    if kind == "call_expression":
        f = n.child_by_field_name("function")
        args = n.child_by_field_name("arguments")
        inner = [c for c in f.named_children if c.type != "comment"] if f is not None and f.type == "parenthesized_expression" else []
        arg_nodes = [c for c in args.named_children if c.type != "comment"] if args is not None else []
        if len(inner) == 1 and inner[0].type in {"identifier", "type_identifier"} and len(arg_nodes) == 1:
            # ``(T)(x)`` parses as a call of a parenthesized name; it is a cast exactly when the name is a type.
            return _cast(env, inner[0], _eval(arg_nodes[0], env, depth + 1))
        raise Unresolved("call_in_constant_expression")
    if kind == "unary_expression":
        op = _text(n.child_by_field_name("operator"), raw)
        return arith(op, None, _eval(n.child_by_field_name("argument"), env, depth + 1), widths, mode)
    if kind == "binary_expression":
        shape = paren_cast_unary(n, raw)
        if shape is not None and _names_type(env, shape[0]):
            # (R67) ``(S16)-4000`` is a cast of ``-4000``
            if shape[2] is None:
                raise Unresolved("cast_operand_grouping_unread:" + shape[0])
            return _cast_to(env, shape[0], arith(shape[1], None, _eval(shape[2], env, depth + 1), widths, mode))
        op = _text(n.child_by_field_name("operator"), raw)
        left = _eval(n.child_by_field_name("left"), env, depth + 1)
        if op == "&&" and not left[0]:
            return 0, ctype("int", True, widths)
        if op == "||" and left[0]:
            return 1, ctype("int", True, widths)
        right = _eval(n.child_by_field_name("right"), env, depth + 1)
        return arith(op, left, right, widths, mode)
    if kind == "conditional_expression":
        cond, _t = _eval(n.child_by_field_name("condition"), env, depth + 1)
        a = _eval(n.child_by_field_name("consequence"), env, depth + 1)
        b = _eval(n.child_by_field_name("alternative"), env, depth + 1)
        if is_float(a[1]) or is_float(b[1]):
            raise Unresolved("float_conditional_unsupported")
        if a[1].get("enum") or b[1].get("enum"):
            # (R67 review W-R4-1) the result type rests on the enumeration's implementation-defined type — the oracle
            #   refuses the same (`conditional_type`); `usual_conversion` would hand back whichever arm came first
            raise Unresolved("enum_underlying_type_implementation_defined")
        t = usual_conversion(a[1], b[1], widths)
        return convert(a[0] if cond else b[0], t), t
    if kind == "field_expression":
        raise Unresolved("register_or_struct_field")
    raise Unresolved("unsupported_constant_expression:" + kind)


def build_scopes(context: dict[str, Any], paths) -> dict[str, dict[str, Any]]:
    """Scopes for the given translation units, sharing one project-wide callee write closure (``scope["effects"]``).

    Linkage: an ``extern const`` object seen in a unit takes its value from the one external, initialized
    definition in the project (same declared type). Only the units that define such an object are scoped for it
    (review W7 — every unit used to be scoped on every call, including the one-function impact proposal).
    """
    effects = function_write_closure(context)
    bodies = macro_bodies(context)
    names = defined_names(context)
    files = context.get("files") or {}
    wanted = [p for p in dict.fromkeys(paths) if p]
    scopes: dict[str, dict[str, Any]] = {}

    def scope_of(path):
        if path not in scopes:
            scope = translation_unit_scope(context, path, bodies, known_names=names)
            scope["effects"] = effects
            scopes[path] = scope
        return scopes[path]

    for path in wanted:
        scope_of(path)
    needed = {name for path in wanted for name, g in scopes[path]["globals"].items() if g.get("const") and not g.get("volatile")}
    external: dict[str, list[dict]] = {}
    for path, rec in files.items():
        if not path.lower().endswith(".c"):
            continue
        for name in needed & set(rec["globals"]):
            if any(d.get("init") and not d.get("static") and not d.get("extern") for d in rec["globals"][name]):
                c = dict.get(scope_of(path)["constants"], name)
                if c is not None and c.get("kind") == "const_object" and not c.get("static") and c.get("file") == path:
                    external.setdefault(name, []).append(c)
    for path in wanted:
        scope = scopes[path]
        for name in list(scope["globals"]):
            g = scope["globals"][name]
            # (R67 review I-d) as for tables: APP and BOOT are separate builds — the definition in this unit's root
            defs = [d for d in external.get(name) or [] if _same_build(context, str(d.get("file") or ""), path)]
            if g.get("const") and not g.get("volatile") and g.get("declared_only") and len(defs) == 1 \
                    and defs[0].get("typename") == g.get("typename"):
                scope["constants"][name] = {**defs[0], "kind": "const_object_linked"}
                del scope["globals"][name]
                # (R17 review R2 W2) the value was decided in the defining unit, under that unit's #if verdicts
                owner = scopes.get(defs[0].get("file")) if defs[0].get("file") in scopes else None
                if owner is not None and owner.get("assumed_undefined"):
                    scope["assumed_undefined"] = sorted(set(scope["assumed_undefined"]) | set(owner["assumed_undefined"]))
    _link_const_arrays(context, scopes, wanted, scope_of)
    return {path: scopes[path] for path in wanted}


def _link_const_arrays(context, scopes, wanted, scope_of) -> None:
    """(R67, audit #45) An ``extern const`` table a unit only declares takes the values of its one external definition:
    a non-static, initialized const definition in a ``.c`` of the same source root (APP and BOOT are separate builds)
    whose unit reads the values, with the same element type and length. ``lin_configuration_ROM`` is declared in every
    LIN-including unit of HDPDM01 (46) and KJPDS02_PV (35) and defined once in ``lin_cfg.c``. Anything else keeps
    ``values_unread`` (several or no definitions, a definition that disagrees)."""
    files = context.get("files") or {}
    needed = {name for path in wanted for name, a in scopes[path]["arrays"].items()
              if a.get("values_unread") == "no_initializer_in_unit" and not a.get("member_of")}
    if not needed:
        return
    defined: dict[str, list[tuple[str, dict]]] = {}
    for path, rec in files.items():
        if not path.lower().endswith(".c"):
            continue
        for name in needed & set(rec.get("globals") or {}):
            if any(d.get("array_init") and d.get("const") and not d.get("static") and not d.get("extern")
                   for d in rec["globals"][name]):
                defined.setdefault(name, []).append((path, scope_of(path)["arrays"].get(name)))
    for path in wanted:
        scope = scopes[path]
        for name, a in scope["arrays"].items():
            if name not in needed or a.get("values_unread") != "no_initializer_in_unit" or a.get("member_of"):
                continue
            mine = [(p, d) for p, d in defined.get(name, []) if _same_build(context, p, path)]
            if len(mine) != 1:
                if mine:
                    a["values_unread"] = "defined_in_several_units"
                continue
            p, d = mine[0]
            if not isinstance(d, dict) or d.get("values") is None:
                a["values_unread"] = "linked_definition_unread:" + str((d or {}).get("values_unread") or "unmodeled")
                continue
            if d.get("typename") != a.get("typename") or a.get("length") not in (None, d.get("length")):
                a["values_unread"] = "linked_definition_disagrees"
                continue
            a.update(values=list(d["values"]), length=d["length"], values_source="linked:" + p)
            a.pop("values_unread", None)
            # (as for a linked const object) the values were decided under the defining unit's #if verdicts
            owner = scopes.get(p)
            if owner is not None and owner.get("assumed_undefined"):
                scope["assumed_undefined"] = sorted(set(scope["assumed_undefined"]) | set(owner["assumed_undefined"]))


_DESIGNATOR_RE = re.compile(r"\(*\s*([A-Za-z_]\w*)(?:\s*\.\s*[A-Za-z_]\w*|\s*\[\s*(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*\s*\])*\s*\)*")


def _designator_targets(name: str, macro_text: dict[str, list[str]], unsettled: set[str] | None,
                        objects: frozenset[str] | set[str] = frozenset(), depth: int = 0) -> set[str] | None:
    """(R63) What a write through the macro ``name`` may write, when every definition of it — and of every macro its
    root names, in any file — is a plain designator: an identifier with ``.member`` / ``[constant]`` steps in balanced
    parentheses (``#define PTADL _PTAD.Overlap_STR.PTADLSTR.Byte``). Every name on the chain is in the set (review round 1
    C1: ``#define ALIAS g_c`` is ``g_c`` in a unit where ``g_c`` is an object even when another file makes ``g_c`` a
    macro). None — not something the closure can name — for a call, a pointer step or an operator, a chain deeper than 8
    or through itself, and for a name ``unsettled`` lists (a #define / #undef inside a function body: the walk does not
    follow the table there; None as ``unsettled`` — a body directive the lexer could not read — refuses every macro).
    Every chain end must be an object some read file declares (``objects``, review round 2 C1': a name defined nowhere the
    context read — an unread header's macro, a -D — may be anything)."""
    if unsettled is None or name in unsettled:
        return None
    out: set[str] = set()
    for body in macro_text.get(name) or [""]:
        m = _DESIGNATOR_RE.fullmatch(body.strip())
        if not m or body.count("(") != body.count(")"):
            return None
        root = m.group(1)
        out.add(root)
        if root in macro_text:
            if depth >= 8 or root == name:
                return None
            more = _designator_targets(root, macro_text, unsettled, objects, depth + 1)
            if more is None:
                return None
            out |= more
        elif root not in objects:
            return None
    return out


def designator_gap(context: dict[str, Any] | None) -> str:
    """(R63 review rounds 3-4) Why a write through a macro alias is not resolved to its object anywhere in the tree
    (`_designator_targets`): a file the source stage could not read, or a quoted include found nowhere that is no
    toolchain header — a name defined there may be another unit's object here. "" when the context read everything."""
    files = (context or {}).get("files") or {}
    if (context or {}).get("incomplete_files"):
        return "unread_files:" + ", ".join(os.path.basename(p) for p in context["incomplete_files"][:3])
    for path, rec in files.items():
        for inc in rec.get("includes") or ():
            if not _resolve_include(context, path, inc) and not _toolchain_header(context, inc):
                return f"include_not_found:{os.path.basename(path)}:{inc}"
    return ""


def function_write_closure(context: dict[str, Any]) -> dict[str, Any]:
    """Per function name: globals it may write (directly or through callees), whether it calls unknown code,
    and the project-wide address-taken set. Same-named static functions in different files are merged
    (union) — the conservative reading.

    Macros count as callees (review C3): a macro a body *uses* (object-like statement ``CLEAR_FLAG;`` or a
    function-like invocation) is followed through its text. A macro that may write (assignment, ``++``, ``&``)
    writes something the closure cannot name — it is an unknown callee; one that only computes is transparent.
    """
    direct: dict[str, dict[str, Any]] = {}
    taken: set[str] = set()
    macro_fx: dict[str, dict[str, Any]] = {}
    type_names = frozenset(n for rec in (context.get("files") or {}).values() for n in rec.get("typedefs") or ())
    for rec in (context.get("files") or {}).values():
        taken.update(rec.get("address_taken") or ())
        # (review R64 round 3 W3) ``&x`` in a function body's #define: the tree walk does not read its text
        for d in (rec.get("stray_directives") or {}).get("directives") or ():
            if d.get("op") == "define":
                taken.update(macro_addresses(d.get("body") or "", type_names))
        for name, defs in rec["macros"].items():
            fx = macro_fx.setdefault(name, {"writes": False, "calls": set(), "names": set(), "function_like": False,
                                            "opaque": False, "conditional_ops": False, "cast_words": set()})
            for d in defs:
                body = d.get("body") or ""
                one = macro_side_effects(body)
                fx["writes"] = fx["writes"] or one["writes"]
                fx["calls"].update(one["calls"])
                # (R35) every name any definition mentions — what reading an undecided macro may read — and whether
                # some definition's text hides its effects (then the union says nothing) or holds a decision operator
                fx["names"].update(re.findall(r"\b[A-Za-z_]\w*\b", body))
                fx["function_like"] = fx["function_like"] or bool(d.get("function_like"))
                fx["opaque"] = fx["opaque"] or macro_body_opaque(body, type_names, fx["cast_words"])
                fx["conditional_ops"] = fx["conditional_ops"] or bool(re.search(r"&&|\|\||\?", body))
        for name, defs in rec["functions"].items():
            entry = direct.setdefault(name, {"writes": set(), "calls": set(), "idents": set(), "pointer_write": False,
                                             "return_types": set(), "paren_calls": set()})
            for d in defs:
                entry["return_types"].add(d.get("return_type") or "")
                entry["writes"].update(d["writes"])
                entry["calls"].update(d["calls"])
                entry["paren_calls"].update(d.get("paren_calls") or ())
                entry["idents"].update(d.get("idents") or ())
                entry["pointer_write"] = entry["pointer_write"] or d["pointer_write"]
                taken.update(d["address_taken"])
    macro_text: dict[str, list[str]] = {}
    for rec in (context.get("files") or {}).values():
        for mname, defs in rec["macros"].items():
            macro_text.setdefault(mname, []).extend(d.get("body") or "" for d in defs)
    # (R64 review round 4 W-1) ``(T)&x``: x's address is taken when T names a type (a typedef, type words, a macro of
    #   type words) — the fallback havoc reaches it
    for rec in (context.get("files") or {}).values():
        for tname, base in rec.get("paren_amp") or ():
            if tname in type_names or tname in _TYPE_WORDS or (
                    tname in macro_text and all(pointer_flow.type_words_only(t, type_names) for t in macro_text[tname])):
                taken.add(base)
    # (R64) ``(T)(x)`` read as a call by the parser: a cast to a type — no callee — or a call to what T names (a
    #   function, a macro), or through a function pointer (unknown code). Before R64 every one was unknown code: 174
    #   KJPDS02_PV and 38 HDPDM01 functions whose only "indirect call" was ``(U8)(…)``
    prototypes = {n for rec in (context.get("files") or {}).values() for n in rec.get("prototypes") or ()}
    object_names = {n for rec in (context.get("files") or {}).values() for n in rec.get("globals") or ()}
    # (review R64 round 6 C6) a name some function body #defines is no type there: ``(T)(x)`` calls what it names
    body_defined = {d.get("name") or "" for rec in (context.get("files") or {}).values()
                    for d in (rec.get("stray_directives") or {}).get("directives") or ()
                    if d.get("op") in ("define", "undef")} - {""}
    for entry in direct.values():
        for t in sorted(entry.pop("paren_calls", ())):
            if t not in body_defined and paren_call_is_cast(t, type_names, set(direct) | prototypes, object_names,
                                                             macro_text):
                continue
            entry["calls"].add(t if t in direct or t in macro_fx or t in prototypes else "<indirect>")
    # (R63 review round 1 C1) names a function body #defines or #undefs somewhere: the table there is not the walk's, so a
    #   write through such a macro is not resolved to an object (`_designator_targets`) — and a write through such a name
    #   itself is no write the closure can name (round 2 W3 — checked even when designators are refused, round 3 I1)
    body_names: set[str] = set()
    unreadable = False
    files_ = context.get("files") or {}
    for rec in files_.values():
        for d in (rec.get("stray_directives") or {}).get("directives") or ():
            if d.get("op") == "unreadable":
                unreadable = True
            elif d.get("op") in ("define", "undef"):
                body_names.add(d.get("name") or "")
    # (round 3 C1'') a name may be defined where the context did not read — a file it could not read, a quoted include
    #   found nowhere (a toolchain header aside), a build -D: then no designator chain is resolved (an object of one file
    #   may be another unit's macro from that header); a -D name on a chain is refused too
    gappy = unreadable or bool(designator_gap(context))
    build_names = {n for cfg in ((context.get("build") or {}).get("configurations") or {}).values()
                   for n in (cfg.get("defines") or {})}
    unsettled: set[str] | None = None if gappy else body_names | build_names
    objects = frozenset(n for rec in files_.values() for n in rec.get("globals") or ())
    # A macro that *mentions* another macro expands it (``#define WRAP INNER``, ``#define AGAIN() CALL_F``): follow it
    # like a call, so its writes and its calls count (R2b review round 3 C1/C2 — only ``NAME(`` was followed).
    for mname, texts in macro_text.items():
        macro_fx[mname]["calls"].update(t for text in texts for t in re.findall(r"\b[A-Za-z_]\w*\b", text)
                                        if t in macro_fx and t != mname)
    closure: dict[str, dict[str, Any]] = {}
    # (R64) where a write through a pointer can land — refused whole when the context is not complete (`pointer_flow`)
    flow, flow_refused = pointer_flow.analyze(context)
    # (review R64 W-3, W-4) unknown code the flow found a function calling — in a macro's expansion (``(cb)(v)``
    #   through the argument it is given), through an object a macro elsewhere shares a name with — is an unknown
    #   callee of it; without the flow, a macro that calls through a parenthesized parameter calls unknown code
    flow_unknown: dict[str, set[str]] = {}
    if flow is not None:
        for name in direct:
            found = {c[5:] for c in flow.unknown_calls.get(name, ()) if c.startswith("call:") and c[5:] not in direct}
            if found:
                flow_unknown[name] = found
    else:
        for mname, fx in macro_fx.items():
            if any(_paren_param_call(d.get("body") or "", d.get("params") or ())
                   for rec in files_.values() for d in rec["macros"].get(mname, ())):
                fx["calls"].add("<indirect>")
    for name in direct:
        writes, unknown, pointer_write, seen, stack = set(), set(), False, set(), [name]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            entry = direct.get(current)
            fx = macro_fx.get(current)
            if fx is not None:
                # A macro of this name is expanded before any function of the same name is called (review round 3
                # C1): follow the macro — and, where it is not visible, the function too (union).
                if fx["writes"]:
                    unknown.add("macro:" + current)
                else:
                    stack.extend(fx["calls"])
                    unknown.update(c for c in fx["calls"] if c in macro_fx and c in objects and c not in direct)
            if entry is None:
                if fx is None:
                    unknown.add(current)
                continue
            writes |= entry["writes"]
            unknown |= flow_unknown.get(current, set())
            # A write through a macro name (``G_ALIAS = 0U`` with ``#define G_ALIAS g_cnt``) targets whatever the
            # macro expands to — not something the closure can name (review round 2 C1) — unless every definition is a
            # plain designator of one object (R63: ``#define PTADL _PTAD.Overlap_STR.PTADLSTR.Byte`` writes ``_PTAD``)
            for w in entry["writes"]:
                if w in macro_fx:
                    targets = _designator_targets(w, macro_text, unsettled, objects)
                    if targets is not None:
                        writes |= targets
                    else:
                        unknown.add("macro_write:" + w)
                elif w in body_names or w in build_names:
                    # (review round 2 W3) a name only a function body #defines (a local macro), or (round 4, as HEAD) only
                    #   a build -D: what a write through it reaches is not the walk's to say
                    unknown.add("macro_write:" + w)
            pointer_write = pointer_write or entry["pointer_write"]
            stack.extend(entry["calls"])
            # (review R64 W-4) a call to a name that is a macro somewhere and an object (a function pointer) too: a
            #   unit that does not see the macro calls through the object — unknown code
            unknown.update(c for c in entry["calls"] if c in macro_fx and c in objects and c not in direct)
            stack.extend(i for i in entry["idents"] if i in macro_fx and i not in direct)
        # ``reaches``: every function this one may (transitively) call — itself included when some path calls it
        # again (recursion, direct or through others): the caller's static locals may change (R2b review W1, round 2 A).
        recursive = any(name in (direct[x]["calls"] if x in direct else ()) or
                        name in ((macro_fx.get(x) or {}).get("calls") or ()) or
                        (x in macro_fx and re.search(r"\b" + re.escape(name) + r"\b", " ".join(macro_text.get(x, ()))))
                        for x in seen)  # through a macro too: ``#define AGAIN() f(0U)`` (round 3 C1)
        rtypes = direct[name]["return_types"]
        # (backlog 2-c) every name the function and what it reaches mention — what a caller that does not interpret it
        #   must assume it may read (identifiers of the bodies — locals and calls excluded — and of the macros reached);
        #   complete unless a macro reached hides its text (``##``, `macro_body_opaque`)
        reads: set[str] = set()
        reads_complete = not unknown
        for x in seen:
            if x in direct:
                reads |= direct[x]["idents"]
            if x in macro_fx:
                reads |= macro_fx[x]["names"]
                reads_complete = reads_complete and not macro_fx[x]["opaque"]
        closure[name] = {"writes": writes, "unknown_callees": unknown, "pointer_write": pointer_write,
                         # (R64) where its writes through a pointer may land (`pointer_flow`): ``{"abs", "params", "why"}``
                         # — ``abs`` None when unknown; None as a whole when the analysis is refused
                         "pointer_targets": flow.summary(name) if flow is not None else None,
                         "reads": frozenset(reads), "reads_complete": reads_complete,
                         "reaches": (seen - {name}) | ({name} if recursive else set()),
                         # (R14) one declared type when every definition says the same; "" when they differ / unknown
                         "return_type": next(iter(rtypes)) if len(rtypes) == 1 else ""}
    # ``&g`` inside a macro body (``#define CFG_PTR (&g_cfg)``) takes g's address wherever the macro is used — the
    # function scan only sees ``CFG_PTR`` (R2b review C6).
    for rec in (context.get("files") or {}).values():
        for defs in rec["macros"].values():
            for d in defs:
                taken.update(macro_addresses(d.get("body") or "", type_names))
    # A macro that takes an address — in its own text or through a macro it invokes (closed transitively; round 3
    # C7): every name passed to it may have its address taken, wherever the invocation is (function body, file-scope
    # initializer, another macro's body). Over-approximates (any argument, not only ``&param``): only refuses more.
    address_params = {name for name, texts in macro_text.items() if any(macro_addresses(t, type_names) for t in texts)}
    changed = True
    while changed:
        changed = False
        for name, texts in macro_text.items():
            if name not in address_params and any(address_params & set(re.findall(r"\b[A-Za-z_]\w*\b", t)) for t in texts):
                address_params.add(name)
                changed = True
    for rec in (context.get("files") or {}).values():
        for macro in address_params & set(rec.get("file_call_args") or {}):
            taken.update(rec["file_call_args"][macro])
        for defs in rec["functions"].values():
            for d in defs:
                for macro in address_params & set(d.get("call_args") or {}):
                    taken.update(d["call_args"][macro])
    # ...and where another macro's body invokes it (``#define CFG_PTR ADDR(g_cfg)``): every name in the arguments.
    if address_params:
        invoke = re.compile(r"\b(" + "|".join(re.escape(m) for m in sorted(address_params)) + r")\s*\(")
        for rec in (context.get("files") or {}).values():
            for defs in rec["macros"].values():
                for d in defs:
                    body = d.get("body") or ""
                    for m in invoke.finditer(body):
                        depth, end = 1, m.end()
                        while end < len(body) and depth:
                            depth += {"(": 1, ")": -1}.get(body[end], 0)
                            end += 1
                        taken.update(re.findall(r"\b[A-Za-z_]\w*\b", body[m.end():end - 1]))
    # ``&ALIAS`` takes the address of what the macro names: expand alias macros into their identifiers.
    pending, expanded = [t for t in taken if t in macro_fx], set()
    while pending:  # to a fixpoint: ``#define A1 A2`` / ``#define A2 g_c`` (review round 3 C1)
        name = pending.pop()
        if name in expanded:
            continue
        expanded.add(name)
        for rec in (context.get("files") or {}).values():
            for d in rec["macros"].get(name, []):
                names = set(re.findall(r"\b[A-Za-z_]\w*\b", d.get("body") or ""))
                taken.update(names)
                pending.extend(n for n in names if n in macro_fx)
    # One view of a macro across the tree (union of every definition), shared with the per-function engine so an
    # undecided macro is judged the same way in both places (review round 3 W1 / X5).
    # (R35) ``names``/``function_like``/``opaque``/``conditional_ops``/``cast_words`` — each definition's own text;
    # what they add up to through the macros a body mentions is `undecided_macro_view`'s (`_macro_closure`)
    macros = {name: {"writes": fx["writes"], "calls": sorted(fx["calls"]), "names": sorted(fx["names"]),
                     "function_like": fx["function_like"], "opaque": fx["opaque"],
                     "conditional_ops": fx["conditional_ops"], "cast_words": sorted(fx["cast_words"])}
              for name, fx in macro_fx.items()}
    return {"functions": closure, "address_taken": taken, "macros": macros,
            # (R64) the solved points-to graph (questions at a call site: a stub's arguments, a callee's parameters)
            "pointer_flow": flow, "pointer_flow_refused": flow_refused}
