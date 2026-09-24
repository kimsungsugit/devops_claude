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

import hashlib
import os
import re
import struct
import threading
from fractions import Fraction
from typing import Any

from workflow.code_parser.c_parser import _make_parser

# 2: preprocessor events look into parse-recovery containers; file-level `address_taken`; function `idents`.
SCHEMA_VERSION = 7  # 3: per-file `prototypes`; closure `macros` (tree union)
# 4 (R2b): global `dims`/`array_init` (arrays, const lookup tables) and function-like macro `params`.
# 5 (R2b): `build` — toolchain include directories from the build configuration (``.cproject``).
# 6 (R2b): `roots` — several source roots are separate builds; a shared header name resolves per root.
# 7 (R14): function `return_type` (declared text) and closure `return_type` — one when every definition agrees.
_ARRAY_INIT_BUDGET = 20000

_RANKS = {"_Bool": 0, "char": 1, "short": 2, "int": 3, "long": 4, "long long": 5}
_WIDTH_NAME_RE = re.compile(r"^[vl]?_?(?P<sign>u|s|uint|sint|int)(?P<bits>8|16|32|64)(?:_t)?$", re.I)
_LITERAL_RE = re.compile(r"^(?P<sign>[-+]?)(?P<digits>0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)"
                         r"(?P<suffix>[uU](?:ll|LL|l|L)?|(?:ll|LL|l|L)[uU]?)?$")
_FLOAT_RE = re.compile(r"^(?P<sign>[-+]?)(?P<number>(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?|[0-9]+[eE][-+]?[0-9]+)"
                       r"(?P<suffix>[fFlL]?)$")
FLOAT = {"kind": "float", "bits": 32, "signed": True, "rank": 10}
DOUBLE = {"kind": "double", "bits": 64, "signed": True, "rank": 11}
_STD_TYPES = frozenset({"uint8_t", "int8_t", "uint16_t", "int16_t", "uint32_t", "int32_t", "uint64_t", "int64_t"})


class Unresolved(ValueError):
    """A value or type the declarations do not determine."""


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
        return truncated
    if t["kind"] == "_Bool":
        return int(bool(value))
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
    if _text(items[0], raw).lstrip().startswith("#ifndef"):
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
        else:
            yield n, conditional


def _declarators(decl):
    typ = decl.child_by_field_name("type")
    for child in decl.named_children:
        if child != typ and child.type not in {"storage_class_specifier", "type_qualifier", "attribute_specifier", "ms_declspec_modifier", "comment"}:
            yield child


def _scan_file(path: str, text: str, parser) -> dict[str, Any]:
    raw = text.encode("utf-8")
    root = parser.parse(raw).root_node
    rec: dict[str, Any] = {"path": path, "includes": [], "system_includes": [], "typedefs": {}, "macros": {}, "undefs": [],
                           "enums": {}, "enumerators": {}, "globals": {}, "functions": {}, "parse_error": root.has_error,
                           "sha256": hashlib.sha256(raw).hexdigest(), "events": _events(root.named_children, raw),
                           # ``&x`` anywhere in the file — file-scope initializers (``{&g_cnt}``) included (review C3d).
                           "address_taken": sorted(_address_taken(root, raw))}
    for node, conditional in _items(_guard_body(root, raw), raw):
        line = node.start_point[0] + 1
        pos = node.start_byte
        if node.type == "preproc_include":
            target = _text(node.child_by_field_name("path"), raw).strip()
            (rec["includes"] if target.startswith('"') else rec["system_includes"]).append(target.strip('"<>'))
        elif node.type in {"preproc_def", "preproc_function_def"}:
            name = _text(node.child_by_field_name("name"), raw)
            value = node.child_by_field_name("value")
            entry = {"body": strip_comments(_text(value, raw)) if value is not None else "", "line": line, "pos": pos,
                     "conditional": conditional, "function_like": node.type == "preproc_function_def"}
            if entry["function_like"]:
                # Parameter names let a consumer expand an invocation (R2b source oracle); ``...`` is kept as a token.
                plist = node.child_by_field_name("parameters")
                entry["params"] = ([_text(c, raw) for c in plist.children if c.type in {"identifier", "..."}]
                                   if plist is not None else [])
            rec["macros"].setdefault(name, []).append(entry)
        elif node.type == "preproc_call" and _text(node.child_by_field_name("directive"), raw).strip() == "#undef":
            arg = node.child_by_field_name("argument")
            if arg is not None:
                rec["undefs"].append(_text(arg, raw).strip())
        elif node.type == "type_definition":
            typ = node.child_by_field_name("type")
            base = " ".join(_text(c, raw) for c in node.named_children if c.type == "type_qualifier" or c == typ)
            _collect_enum(typ, raw, rec, conditional, line, pos)
            aggregate = typ is not None and typ.type in {"struct_specifier", "union_specifier"}
            for d in node.named_children:
                if d.type == "type_identifier" and d != typ and aggregate:
                    rec["typedefs"].setdefault(_text(d, raw), []).append({"base": "", "shape": "struct", "line": line,
                                                                         "pos": pos, "conditional": conditional})
                elif d.type == "type_identifier" and d != typ:
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
        elif node.type == "declaration":
            typ = node.child_by_field_name("type")
            _collect_enum(typ, raw, rec, conditional, line, pos)
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
                                                              "conditional": conditional})
    return rec


def _address_taken(root, raw):
    names = set()
    for n in _walk(root):
        if n.type in {"unary_expression", "pointer_expression"} and _text(n, raw).lstrip().startswith("&") \
                and not _text(n, raw).lstrip().startswith("&&"):
            base = _base_identifier(n.child_by_field_name("argument"), raw)
            if base:
                names.add(base)
    return names


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


def _function_effects(fn, raw):
    """Direct writes, address-taken identifiers, pointer writes and callees of one function body."""
    writes, taken, calls, locals_, idents = set(), set(), set(), set(), set()
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
        elif n.type == "call_expression":
            f = n.child_by_field_name("function")
            if f is not None and f.type == "identifier":
                calls.add(_text(f, raw))
                args = n.child_by_field_name("arguments")
                # Argument base names per callee: a function-like macro ``#define SAVE(v) (g_p = &(v))`` takes the
                # address of what the call passes (R2b review round 2 F).
                call_args.setdefault(_text(f, raw), set()).update(
                    b for a in (args.named_children if args is not None else []) for b in [_base_identifier(a, raw)] if b)
            else:
                calls.add("<indirect>")
        elif n.type == "declaration":
            # A block-scope ``extern`` names the global itself, not a local (review C3f).
            if not any(c.type == "storage_class_specifier" and _text(c, raw) == "extern" for c in n.named_children):
                for d in _declarators(n):
                    name = _declared_name(d, raw)
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
        name = _declared_name(p.child_by_field_name("declarator"), raw) if p.child_by_field_name("declarator") is not None else ""
        if name:
            params.add(name)
    every_local = locals_ | params
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
            "return_type": return_type}


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
    """Toolchain include directories a build configuration names (Eclipse/CodeWarrior ``.cproject``).

    Evidence for one question only: a quoted ``#include`` found nowhere in the source tree — C11 6.10.2p3 retries it
    as ``<...>``, i.e. in these directories — is the toolchain's header (``hidef.h``), not a project header that went
    missing. Without such evidence the include stays a gap (everything after it undecided)."""
    dirs: set[str] = set()
    for text in cproject_texts.values():
        dirs.update(_TOOLCHAIN_INCLUDE_RE.findall(text or ""))
    return {"toolchain_include_dirs": sorted(dirs), "evidence": sorted(p for p, t in cproject_texts.items()
                                                                      if _TOOLCHAIN_INCLUDE_RE.search(t or ""))}


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


def _events(nodes, raw):
    """Preprocessor-relevant structure of a file, in order: includes, (un)defines, conditionals, declarations."""
    out = []
    for n in nodes:
        t = n.type
        if t == "comment":
            continue
        if t == "preproc_include":
            target = _text(n.child_by_field_name("path"), raw).strip()
            out.append({"op": "include", "name": target.strip('"<>'), "system": not target.startswith('"')})
        elif t in {"preproc_def", "preproc_function_def"}:
            out.append({"op": "define", "name": _text(n.child_by_field_name("name"), raw), "pos": n.start_byte})
        elif t == "preproc_call":
            directive = _text(n.child_by_field_name("directive"), raw).strip()
            arg = n.child_by_field_name("argument")
            if directive == "#undef" and arg is not None:
                out.append({"op": "undef", "name": _text(arg, raw).strip()})
            elif directive == "#error":
                out.append({"op": "error", "text": _text(arg, raw).strip()[:120] if arg is not None else ""})
        elif t in _IF_NODES:
            out.append(_if_event(n, raw))
        elif t in {"ERROR", "compound_statement"}:
            # Parse-recovery container at file level (see `_items`): its contents are ordinary top-level items.
            out.extend(_events(n.named_children, raw))
        else:
            out.append({"op": "decl", "pos": n.start_byte})
    return out


def _if_event(n, raw):
    cond, name, alt = n.child_by_field_name("condition"), n.child_by_field_name("name"), n.child_by_field_name("alternative")
    body = [c for c in n.named_children if c != cond and c != name and c != alt]
    ev: dict[str, Any] = {"op": "if", "then": _events(body, raw), "else": [], "line": n.start_point[0] + 1}
    if n.type in {"preproc_ifdef", "preproc_elifdef"}:
        head = _text(n, raw).lstrip()
        ev["defined"] = _text(name, raw) if name is not None else ""
        ev["negate"] = head.startswith("#ifndef") or head.startswith("#elifndef")
    else:
        ev["expr"] = strip_comments(_text(cond, raw)) if cond is not None else ""
    if alt is not None:
        ev["else"] = _events(alt.named_children, raw) if alt.type == "preproc_else" else [_if_event(alt, raw)]
    return ev


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
    if t in {"identifier", "number_literal", "char_literal", "parenthesized_expression", "call_expression",
             "field_expression", "subscript_expression"}:  # postfix expressions bind tighter than any operator
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
    if name not in env["defined_anywhere"] or env["gap"]:
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
    if t == "identifier":
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


def pp_condition(scope: dict[str, Any], node, raw: bytes) -> bool | None:
    """Verdict of an ``#if``/``#ifdef``/``#elif`` node inside a function of this unit (None = undecided).

    The table is the one at the end of the unit, so a macro whose value changed during the unit decides
    nothing here (R81 review W1 — the function may sit before or after the change).
    """
    parser = shared_parser()
    if parser is None:
        return None
    name, cond = node.child_by_field_name("name"), node.child_by_field_name("condition")
    if node.type in {"preproc_ifdef", "preproc_elifdef"}:
        head = _text(node, raw).lstrip()
        ev = {"defined": _text(name, raw) if name is not None else "",
              "negate": head.startswith("#ifndef") or head.startswith("#elifndef")}
    else:
        ev = {"expr": strip_comments(_text(cond, raw)) if cond is not None else ""}
    env = {"macros": scope.get("pp_macros") or {}, "bodies": scope.get("pp_bodies") or {}, "parser": parser,
           "defined_anywhere": scope.get("pp_defined_anywhere") or set(), "gap": bool(scope.get("missing_includes")),
           "varied": set(scope.get("pp_varied") or ())}
    return _pp_condition(ev, env)


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


def preprocess_unit(context: dict[str, Any], main: str, bodies: dict | None = None,
                    defines: dict[str, str] | None = None, known_names: set[str] | None = None) -> dict[str, Any]:
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
                           "defined_after_gaps": {}}
    env = {"macros": macros, "bodies": bodies, "parser": parser, "gap": False, "varied": set(),
           "defined_anywhere": (known_names if known_names is not None else defined_names(context)) | set(defines or ())}
    out["defined_anywhere"] = env["defined_anywhere"]
    stack: list[str] = []

    def run(path, events, mode, depth):
        for ev in events:
            op = ev["op"]
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
                             "missing_includes": [], "system_includes": [], "files": []}
    if path not in files:
        scope["status"] = "file_not_in_project_context"
        return scope
    pp = preprocess_unit(context, path, bodies, known_names=known_names)
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
        elif (bk := base_kind(core)) is not None:
            if bk[1] is None:
                raise Unresolved("plain_char_signedness_unknown")
            t = ctype(bk[0], bk[1], widths)
        elif core in _STD_TYPES:
            # The width is fixed but the underlying type (and so its conversion rank) is the target's choice.
            raise Unresolved("stdint_type_rank_unknown:" + core)
        elif core in raw_typedefs:
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
        d = next((x for x in files[p]["macros"].get(name, []) if x.get("pos") == pos), None)
        if d is not None:
            macro_defs[name] = [{**d, "file": p, "conditional": False}]
    undefs = set(pp["varied"])
    # Final macro table for ``#if`` inside function bodies (``pp_condition``) — bodies after every header.
    scope["pp_macros"] = {name: (_UNKNOWN if key == _UNKNOWN else name) for name, key in pp["macros"].items()}
    scope["pp_bodies"] = {name: d[0] for name, d in macro_defs.items() if pp["macros"].get(name) != _UNKNOWN}
    scope["pp_varied"] = sorted(pp["varied"])
    scope["pp_defined_anywhere"] = pp["defined_anywhere"]
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
        "a name some project file #defines is not also a build -D (only names the tree never defines are undecided)",
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

    # globals visible to this translation unit
    for name, defs in global_defs.items():
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
            scope["globals"][name] = {"type": t, "typename": d["type"], "file": d["file"], "line": d["line"],
                                      "volatile": volatile, "const": const}
        except Unresolved as exc:
            scope["unresolved_globals"][name] = str(exc)
    scope["status"] = "resolved" if not scope["missing_includes"] else "partial"
    return scope


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
                  "line": defs[0]["line"], "volatile": volatile, "const": const, "values": None}
        inits = [x for x in defs if x.get("array_init") or x.get("array_init_truncated")]
        if const and not volatile and len(inits) == 1 and inits[0].get("array_init"):
            record["values"] = _array_values(inits[0]["array_init"], elem, length, agreeing, parser)
            if record["values"] is not None and length is None:
                record["length"] = len(record["values"])
        scope["arrays"][name] = record
    except Unresolved:
        return


def _array_values(text, elem, length, agreeing, parser):
    """Element values of ``{a, b, c}`` (positional only; trailing elements are 0 as in C). None when any
    element is not an integer constant expression, a designator is used, or the list overruns the length."""
    raw = ("int __probe[] = " + text + ";").encode("utf-8")
    root = parser.parse(raw).root_node
    init = next((x for x in _walk(root) if x.type == "initializer_list"), None)
    if root.has_error or init is None or _text(init, raw) != text.strip():
        return None
    items = [c for c in init.named_children if c.type != "comment"]
    if any(c.type in {"initializer_pair", "initializer_list"} for c in items):
        return None
    if length is not None and len(items) > length:
        return None
    values = []
    for c in items:
        try:
            value, t, _extra = agreeing(_text(c, raw), macro_body=False)
        except Unresolved:
            return None
        if is_float(t) or is_float(elem):
            return None
        try:
            values.append(convert(value, elem))
        except Unresolved:
            return None
    if length is not None:
        values.extend([0] * (length - len(values)))
    return values


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
    t = env["type_of"](" ".join(_text(type_node, env["raw"]).split()))
    if is_float(t):
        env["flags"]["float"] = True
    return convert(operand[0], t, env["mode"]), t


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
    if kind == "identifier":
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
            defs = external.get(name) or []
            if g.get("const") and not g.get("volatile") and len(defs) == 1 and defs[0].get("typename") == g.get("typename"):
                scope["constants"][name] = {**defs[0], "kind": "const_object_linked"}
                del scope["globals"][name]
    return {path: scopes[path] for path in wanted}


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
    for rec in (context.get("files") or {}).values():
        taken.update(rec.get("address_taken") or ())
        for name, defs in rec["macros"].items():
            fx = macro_fx.setdefault(name, {"writes": False, "calls": set()})
            for d in defs:
                one = macro_side_effects(d.get("body") or "")
                fx["writes"] = fx["writes"] or one["writes"]
                fx["calls"].update(one["calls"])
        for name, defs in rec["functions"].items():
            entry = direct.setdefault(name, {"writes": set(), "calls": set(), "idents": set(), "pointer_write": False,
                                             "return_types": set()})
            for d in defs:
                entry["return_types"].add(d.get("return_type") or "")
                entry["writes"].update(d["writes"])
                entry["calls"].update(d["calls"])
                entry["idents"].update(d.get("idents") or ())
                entry["pointer_write"] = entry["pointer_write"] or d["pointer_write"]
                taken.update(d["address_taken"])
    macro_text: dict[str, list[str]] = {}
    for rec in (context.get("files") or {}).values():
        for mname, defs in rec["macros"].items():
            macro_text.setdefault(mname, []).extend(d.get("body") or "" for d in defs)
    # A macro that *mentions* another macro expands it (``#define WRAP INNER``, ``#define AGAIN() CALL_F``): follow it
    # like a call, so its writes and its calls count (R2b review round 3 C1/C2 — only ``NAME(`` was followed).
    for mname, texts in macro_text.items():
        macro_fx[mname]["calls"].update(t for text in texts for t in re.findall(r"\b[A-Za-z_]\w*\b", text)
                                        if t in macro_fx and t != mname)
    closure: dict[str, dict[str, Any]] = {}
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
            if entry is None:
                if fx is None:
                    unknown.add(current)
                continue
            writes |= entry["writes"]
            # A write through a macro name (``G_ALIAS = 0U`` with ``#define G_ALIAS g_cnt``) targets whatever the
            # macro expands to — not something the closure can name (review round 2 C1).
            unknown.update("macro_write:" + w for w in entry["writes"] if w in macro_fx)
            pointer_write = pointer_write or entry["pointer_write"]
            stack.extend(entry["calls"])
            stack.extend(i for i in entry["idents"] if i in macro_fx and i not in direct)
        # ``reaches``: every function this one may (transitively) call — itself included when some path calls it
        # again (recursion, direct or through others): the caller's static locals may change (R2b review W1, round 2 A).
        recursive = any(name in (direct[x]["calls"] if x in direct else ()) or
                        name in ((macro_fx.get(x) or {}).get("calls") or ()) or
                        (x in macro_fx and re.search(r"\b" + re.escape(name) + r"\b", " ".join(macro_text.get(x, ()))))
                        for x in seen)  # through a macro too: ``#define AGAIN() f(0U)`` (round 3 C1)
        rtypes = direct[name]["return_types"]
        closure[name] = {"writes": writes, "unknown_callees": unknown, "pointer_write": pointer_write,
                         "reaches": (seen - {name}) | ({name} if recursive else set()),
                         # (R14) one declared type when every definition says the same; "" when they differ / unknown
                         "return_type": next(iter(rtypes)) if len(rtypes) == 1 else ""}
    # ``&g`` inside a macro body (``#define CFG_PTR (&g_cfg)``) takes g's address wherever the macro is used — the
    # function scan only sees ``CFG_PTR`` (R2b review C6).
    type_names = frozenset(n for rec in (context.get("files") or {}).values() for n in rec.get("typedefs") or ())
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
    macros = {name: {"writes": fx["writes"], "calls": sorted(fx["calls"])} for name, fx in macro_fx.items()}
    return {"functions": closure, "address_taken": taken, "macros": macros}
