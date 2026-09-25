"""(R16b) Independent check of SITS integration expected values with clang — the callees compiled, not modelled.

`generators.integration_oracle` derives a SITS expected value by interpreting the entry function *and the project
callees it binds to* (`_World` in `generators.c_source_oracle`). This script asks clang instead. The entry and every
project function it can reach are compiled **verbatim** as ``constexpr`` member functions of one C++20 struct whose data
members are the program's objects (``--target=msp430``: char 8 · short 16 · int 16 · long 32; the widths each unit's
typedefs testify are asserted against the target — a mismatch fails the group); the claim's inputs are stored into a
fresh instance, the entry is called once per fill value, and every claimed observable becomes a ``static_assert``.
Constant evaluation runs each body with the target's integer semantics — conversions, promotions, control flow, argument
passing, what a callee writes and returns, writes through pointers into other objects — and rejects most undefined
behaviour (signed overflow, division by zero, out-of-bounds indexing, reads of indeterminate locals) as a hard error.

Shared with the model (a wrong verdict there would be agreed with, as in `source_oracle_clang_check`): which definition
a call binds to (the project's `CalleeProvider`), which macros are active with which bodies (the project context,
including R17's build-configuration assumptions), typedef widths, enumerator and ``const`` values. Objects the claim
leaves unset and the values of functions the harness does not run take three fill values (0/90/201): a claim holds only
if all three runs give the claimed value — a sample, not a proof of independence. An enumeration is compiled once per
permitted underlying type; a claim must hold for each.

Functions the harness does not run are of two kinds, and the struct counts, per run, how often each was reached:

* **unbound** — the model could not bind the call either (no definition, only in a header, ambiguous, …): it treated it
  as unknown code (its write closure), so no claimed value may rest on its effects. It returns the fill value and
  writes nothing. A run that reached one and agreed is ``agree_with_stubbed_callees`` (as in the unit check); a
  mismatch is still a contradiction — the value then depends on what the unknown call returns;
* **cut** — the model ran it but the harness cannot compile it (a struct object, vendor syntax, an undecided macro):
  its writes are missing here, so a mismatch proves nothing (``unchecked:cut_callee_reached``) and an agreement is
  only ``agree_with_cut_callees``.

Only ``agree`` — nothing left out on the path clang ran, for every fill and enum type — checks the integrated value.

Limits (carried over from the unit check, and this harness's own):

* hardware (volatile objects, registers), interrupts and other tasks are outside both; ``goto``, reinterpreting casts
  and reads clang cannot evaluate at compile time make a run ``unchecked:constexpr_limit``;
* C++ sequences some things C leaves unsequenced (``=`` operands since C++17, list-initialization items) and defines
  some C undefined behaviour (``<<`` of a negative value, signed overflow in ``<<``): the model refuses those in C, so
  no claim rests on the difference — but clang cannot catch that refusal missing. clang's own unsequenced warning is
  kept: a run that reaches a function it flags is ``unchecked:unsequenced_function_reached`` (listed in the report);
* ``static`` locals become struct members (entry value: the fills, as the model reads them unknown); same-named
  ``static`` objects and helpers of different units get one member each, named per unit;
* struct and union objects are not modelled — a function using one is cut, an entry using one fails its group;
* only the entry unit's text is checked against the hash the claim recorded: a changed callee unit or header is not
  detected (the harness would compile newer code than the claim was derived from);
* every compilation carries a canary assertion with a per-compilation nonce that must fail: a run that does not report
  exactly that canary (another source, a missing target, a driver error, a crash) is a failure, never a silent pass.

Usage:
    .venv/Scripts/python.exe scripts/integration_oracle_clang_check.py --xlsm SITS.xlsm --source-root ROOT[,ROOT] [--out r.json]

Exit code: 0 all checked claims agree · 1 a mismatch or evaluation error · 2 nothing was checked (no claims, every group
failed) or a compilation could not prove it ran.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.source_oracle_clang_check import (  # noqa: E402
    _CHECK_RANK,
    _ENUM_BASES,
    _FILLS,
    _IDENT,
    _KEYWORDS,
    _REAL_EVAL_ERROR,
    _base_type,
    _disclosure_explains,
    _fill_for,
    _fits,
    _input_int,
    _one_line,
    _text,
    _text_hashes,
)

_CUT_ROUNDS = 8                     # compile → cut the functions clang rejects → compile again
_ELEMENT = re.compile(r"^([A-Za-z_]\w*)\[(\d+)\]$")
_STUB_KEY = re.compile(r"^([A-Za-z_]\w*)\(\) return$")
_CALL = re.compile(r"(?<!\.)(?<!->)\b([A-Za-z_]\w*)\s*\(")
_NAMED = re.compile(r"(?<!\.)(?<!->)\b([A-Za-z_]\w*)\b")
_DIAG = re.compile(r"^.*?:(\d+):\d+: (fatal error|error|warning|note): (.*)$")
# pseudo outputs, claimed 0: how often a cut / unbound / unsequenced-flagged function was reached in the run
_CUT, _UNBOUND, _UNSEQ = "__oracle_cut", "__oracle_unbound", "__oracle_unseq"
_PSEUDO = (_CUT, _UNBOUND, _UNSEQ)
_CONST_KINDS = {"enumerator", "const_object", "const_object_linked"}
# Names a C program may use that C++ reserves (or that are compiler keywords, not functions): never a member or a stub
_NOT_A_MEMBER = frozenset("""alignas alignof and and_eq asm bitand bitor bool catch char8_t char16_t char32_t class compl
concept consteval constexpr constinit const_cast co_await co_return co_yield decltype delete dynamic_cast explicit export
false friend inline mutable namespace new noexcept not not_eq nullptr operator or or_eq private protected public
reinterpret_cast requires static_assert static_cast template this thread_local throw true try typeid typename using
virtual wchar_t xor xor_eq __asm __asm__ __attribute__ __declspec __extension__ __typeof__ typeof defined offsetof
_Alignof _Generic _Static_assert""".split())
_WIDTH_TYPES = {"char": "char", "short": "short", "int": "int", "long": "long", "long long": "long long"}
# Final verdicts, worst first when several enum types disagree: a contradiction for one permitted type is a contradiction
_FINAL_RANK = {"mismatch": 6, "eval_error": 5, "unchecked": 4, "agree_with_cut_callees": 3,
               "agree_with_stubbed_callees": 2, "agree": 0}
# The Python side (tree-sitter parser, lazily resolved scope tables) is not shared across threads: builds hold this
# lock, clang runs outside it (review R1 I2)
_PY_LOCK = threading.Lock()


class _Failure(Exception):
    """The whole group cannot be checked (the reason is reported for all its claims)."""


def _blank(raw: bytes) -> bytes:
    """Spaces for ``raw``, its line ends kept (line numbers stay those of the source)."""
    return bytes(b if b in b"\r\n" else 32 for b in raw)


def _enclosing_block(node):
    """The ``{…}`` a declaration's scope ends with — through ``case``/label wrappers: a declaration after ``case 0:``
    is in scope to the end of the switch body (C11 6.2.1p4; review R1 C2)."""
    block = node.parent
    while block is not None and block.type != "compound_statement":
        block = block.parent
    return block


def _hoisted(fn, raw, fname, scope, unit_tag):
    """The body with comments blanked and every ``static`` local made a member of the struct (C++20 constant evaluation
    has no static storage in a function): ``(body text, [member spec], {call names})`` or a reason. A static local keeps
    its value across calls, and on entry holds whatever an earlier call left — the oracle reads it as unknown
    (``static_local_state``), so the member takes the fill values like any unset object; a ``const`` one keeps its
    initializer. Each use after the declaration, to the end of its block, names the member (an inner block's namesake
    wins inside that block). Calls are the body's call expressions — not words in comments or ``#if defined(…)``."""
    from generators import c_project_context as cpc
    from generators.mcdc_design import _scope_type
    body = fn.child_by_field_name("body")
    decls, idents, comments, calls, stack = [], [], [], set(), [body]
    while stack:
        n = stack.pop()
        if n.type == "declaration" and any(c.type == "storage_class_specifier" and _text(c, raw) == "static"
                                           for c in n.children):
            decls.append(n)
        elif n.type == "identifier":
            idents.append(n)
        elif n.type == "comment":
            comments.append(n)
        elif n.type == "call_expression":
            f = n.child_by_field_name("function")
            if f is not None and f.type == "identifier":
                calls.add(_text(f, raw))
        stack.extend(n.named_children)
    edits: dict[tuple[int, int], bytes] = {(c.start_byte, c.end_byte): _blank(raw[c.start_byte:c.end_byte])
                                           for c in comments}
    specs = []
    # outer blocks first: an inner block's static of the same name overrides the rename inside that block
    decls.sort(key=lambda d: -(_enclosing_block(d).end_byte - _enclosing_block(d).start_byte))
    for k, d in enumerate(decls):
        typ = d.child_by_field_name("type")
        if typ is None or typ.type in {"struct_specifier", "union_specifier", "enum_specifier"}:
            return "static_local_aggregate_type"
        quals = {_text(c, raw) for c in d.named_children if c.type == "type_qualifier"}
        try:
            t = _scope_type(scope, _text(typ, raw))
        except cpc.Unresolved:
            return "static_local_type_unresolved"
        block = _enclosing_block(d)
        if block is None:
            return "static_local_scope"
        for x in d.named_children:
            if x == typ or x.type in {"type_qualifier", "storage_class_specifier", "comment", "attribute_specifier"}:
                continue
            target = x.child_by_field_name("declarator") if x.type == "init_declarator" else x
            value = x.child_by_field_name("value") if x.type == "init_declarator" else None
            name = cpc._declared_name(target, raw)
            if not name:
                return "static_local_declarator"
            spec = {"name": name, "member": f"__oracle_sl_{fname}_{name}_{k}_{unit_tag}", "type": t,
                    "const": "const" in quals, "init": None, "size": None, "texts": [_text(typ, raw)]}
            if "const" in quals:
                if value is None:
                    return "static_const_local_without_initializer"
                spec["init"] = _text(value, raw)
                spec["texts"].append(spec["init"])
            if target.type == "array_declarator":
                inner, size = target.child_by_field_name("declarator"), target.child_by_field_name("size")
                if inner is None or inner.type != "identifier":
                    return "static_local_declarator"
                if size is not None:
                    spec["size"] = _text(size, raw)
                    spec["texts"].append(spec["size"])
                elif value is not None and value.type == "initializer_list" and \
                        not any(i.type == "initializer_pair" for i in value.named_children):
                    spec["size"] = str(len(value.named_children))
                else:
                    return "static_local_array_length"
            elif target.type != "identifier":
                return "static_local_declarator"
            specs.append(spec)
            for i in idents:
                if d.end_byte <= i.start_byte < block.end_byte and _text(i, raw) == name:
                    edits[(i.start_byte, i.end_byte)] = spec["member"].encode()
        edits[(d.start_byte, d.end_byte)] = _blank(raw[d.start_byte:d.end_byte])
    out, pos = [], body.start_byte
    for (s, e), rep in sorted(edits.items()):
        if s < pos:
            continue   # inside a removed declaration or comment
        out.append(raw[pos:s])
        out.append(rep)
        pos = e
    out.append(raw[pos:body.end_byte])
    text = b"".join(out).decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    return text, specs, calls


def _parts(fn, raw, fname, scope, unit_tag):
    """(return type text, [(name, declaration text, scalar, type text)], body text with LF line ends, static local
    member specs, call names) of a definition, or a reason."""
    from generators import c_project_context as cpc
    from generators.mcdc_design import _function_name
    _, fdecl = _function_name(fn, raw)
    if fdecl is None or fdecl.parent is None or fdecl.parent.type != "function_definition":
        return "function_declarator_not_direct"
    hoisted = _hoisted(fn, raw, fname, scope, unit_tag)
    if isinstance(hoisted, str):
        return hoisted
    body, statics, calls = hoisted
    rtype = " ".join([_text(c, raw) for c in fn.named_children if c.type == "type_qualifier"] +
                     [_text(fn.child_by_field_name("type"), raw)])
    params = []
    for p in fdecl.child_by_field_name("parameters").named_children:
        if p.type == "variadic_parameter":
            return "variadic_parameters"
        if p.type != "parameter_declaration":
            continue
        d = p.child_by_field_name("declarator")
        if d is None:
            if _text(p, raw).strip() != "void":
                return "unnamed_parameter"
            continue
        params.append((cpc._declared_name(d, raw), _text(p, raw), d.type == "identifier",
                       _text(p.child_by_field_name("type"), raw)))
    return rtype, params, body, statics, calls


def _unit_tag(path: str) -> str:
    return hashlib.sha1(os.path.normcase(path).encode("utf-8")).hexdigest()[:6]


def _compiled(name, path, raw, fn, scope, known_functions=frozenset()):
    """What the harness needs of one definition (a dict), or the reason it cannot compile it (a str)."""
    if name in _NOT_A_MEMBER:
        return "name_reserved_in_cxx"
    parts = _parts(fn, raw, name, scope, _unit_tag(path))
    if isinstance(parts, str):
        return parts
    rtype, params, body, statics, body_calls = parts
    macro_bodies = scope.get("macro_bodies") or {}
    fbodies = scope.get("function_like_macro_bodies") or {}
    status = scope.get("macro_status") or {}
    pending = _IDENT.findall(body) + _IDENT.findall(rtype) + [x for p in params for x in _IDENT.findall(p[1])]
    pending += [x for sp in statics for text in sp["texts"] for x in _IDENT.findall(text)]   # review R1 W11
    tokens: set[str] = set()
    while pending:
        tok = pending.pop()
        if tok in tokens:
            continue
        tokens.add(tok)
        pending.extend(_IDENT.findall(macro_bodies.get(tok, "")) + _IDENT.findall(fbodies.get(tok, "")))
    if any(status.get(t) not in (None, "active") for t in tokens):
        return "macro_not_active_in_unit"
    macros = sorted(t for t in tokens if status.get(t) == "active" and (t in macro_bodies or t in fbodies))
    macro_text = " ".join(macro_bodies.get(m, "") + " " + fbodies.get(m, "") for m in macros)
    if {sp["name"] for sp in statics} & set(_IDENT.findall(macro_text)):
        return "static_local_named_in_macro"   # the rename does not reach a macro's expansion
    globals_, arrays, types = scope.get("globals") or {}, scope.get("arrays") or {}, scope.get("types") or {}
    constants = scope["constants"]
    consts = {}
    for t in sorted(tokens):
        if t in status or t in globals_ or t in arrays or t not in constants:
            continue
        c = dict.get(constants, t)   # `in` above resolved it (lazy table): a plain read, no second resolution
        if c is not None and c.get("kind") in _CONST_KINDS:
            consts[t] = c
    objects = {t: ("array", arrays[t]) if t in arrays else ("global", globals_[t])
               for t in sorted(tokens) if (t in globals_ or t in arrays) and t not in status}
    typedefs = {t: types[t] for t in sorted(tokens) if isinstance(types.get(t), dict) and t not in status}
    # ``enum TAG`` written without a typedef (``enum en_g_DoorState g_DoorState;``): C++ would see an undefined enum —
    # the harness names it by a typedef of the underlying type, which the enum-base loop varies like any enum typedef
    enum_tags = {k.split(None, 1)[1]: v for k, v in types.items()
                 if isinstance(k, str) and k.startswith("enum ") and isinstance(v, dict) and k.split(None, 1)[1] in tokens}
    if enum_tags:
        body, rtype = _untagged(body, enum_tags), _untagged(rtype, enum_tags)
        params = [(n, _untagged(decl, enum_tags), scalar, typ) for n, decl, scalar, typ in params]
        typedefs.update({f"__oracle_enum_{tag}": t for tag, t in enum_tags.items()})
    # a typedef named like a C++ keyword (``typedef unsigned char bool;`` in PE_Types.h): C++ cannot redeclare it —
    # the block names it ``__oracle_td_bool`` through a ``#define`` (review R2 IR2-4)
    kw_typedefs = sorted(t for t in typedefs if t in _NOT_A_MEMBER)
    for t in kw_typedefs:
        typedefs[f"__oracle_td_{t}"] = typedefs.pop(t)
    param_names = {p[0] for p in params}
    # calls: the body's call expressions and those its macros spell — and a project function a macro only names
    # (``#define Read Drv_Read``: the call site says ``Read(…)``; review R1 I6)
    # (not a member name after ``.``/``->``: ``REG_SCI0SR2.Bits.AMAP`` names a bit field, even where a register
    # header's parse lists ``AMAP`` among the functions — HDPDM01 R16b)
    macro_calls = {m.group(1) for m in _CALL.finditer(macro_text)} | (
        {m.group(1) for m in _NAMED.finditer(macro_text)} & known_functions)
    calls = sorted(c for c in body_calls | macro_calls
                   if c not in status and c not in _KEYWORDS and c not in _NOT_A_MEMBER and c not in types
                   and c not in globals_ and c not in arrays and c not in param_names
                   and not c.startswith(("__oracle", "__builtin_")))
    enum = any(t.get("enum") for t in typedefs.values()) or any(rec.get("type", {}).get("enum")
                                                               for _k, rec in objects.values())
    return {"name": name, "path": path, "scope": scope, "rtype": rtype, "params": params, "body": body,
            "enum_tags": enum_tags, "statics": statics, "macros": macros, "consts": consts, "objects": objects,
            "typedefs": typedefs, "kw_typedefs": kw_typedefs, "calls": calls, "enum": enum}


def _untagged(text, enum_tags):
    """``enum TAG`` (not a definition ``enum TAG {``) → the harness typedef ``__oracle_enum_TAG``."""
    if not enum_tags:
        return text
    pattern = re.compile(r"\benum\s+(" + "|".join(re.escape(t) for t in sorted(enum_tags, key=len, reverse=True))
                         + r")\b(?!\s*\{)")
    return pattern.sub(lambda m: "__oracle_enum_" + m.group(1), text)


def _closure(entry_name, entry_path, files, scopes, provider, parser):
    """The entry and every project function it reaches that the harness compiles (member name → record), the entry's
    member name, the calls it stubs by kind (member → reason), the C name of each stub, and the unit scopes seen.

    A C name that reaches one thing keeps it as the member name. One that reaches several (``static`` helpers of two
    units, a name one caller binds and another cannot) gets a member per target, and each caller's call sites are
    renamed to the member its own call binds to — as the model binds per caller unit."""
    from generators.c_source_oracle import Unsupported, _find_function
    known = frozenset(getattr(provider, "defs", {}) or {}) | frozenset(getattr(provider, "header_defs", {}) or {})
    raw = files[entry_path].encode()
    try:
        fn = _find_function(parser.parse(raw).root_node, raw, entry_name, scopes[entry_path])
    except Unsupported as exc:
        raise _Failure("entry:" + str(exc)) from None
    entry = _compiled(entry_name, entry_path, raw, fn, scopes[entry_path], known)
    if isinstance(entry, str):
        raise _Failure("entry_not_compilable:" + entry)
    unbound_mark = "\0unbound"
    nodes = {(entry_name, entry_path): entry}
    edges: dict[tuple, dict[str, tuple]] = {}
    cut_reason: dict[tuple, str] = {}
    unbound_reason: dict[str, str] = {}
    bound_scopes = {entry_path: scopes[entry_path]}
    queue = [(entry_name, entry_path)]
    while queue:
        key = queue.pop()
        caller = nodes[key]
        edges[key] = {}
        for name in caller["calls"]:
            try:
                raw_c, fn_c, scope_c, _shared, path_c = provider.definition(name, caller["path"])
            except Unsupported as exc:
                edges[key][name] = (name, unbound_mark)
                unbound_reason.setdefault(name, str(exc))
                continue
            target = (name, path_c)
            edges[key][name] = target
            if target in nodes or target in cut_reason:
                continue
            bound_scopes.setdefault(path_c, scope_c)
            rec = _compiled(name, path_c, raw_c, fn_c, scope_c, known)
            if isinstance(rec, str):
                cut_reason[target] = rec
                continue
            nodes[target] = rec
            queue.append(target)
    targets_of: dict[str, set] = {}
    for tk in set(nodes) | set(cut_reason) | {t for e in edges.values() for t in e.values()}:
        targets_of.setdefault(tk[0], set()).add(tk)
    member_of = {}
    for cname, tks in targets_of.items():
        ordered = sorted(tks, key=lambda t: (t[1] == unbound_mark, t[1]))
        for i, tk in enumerate(ordered):
            member_of[tk] = cname if len(ordered) == 1 else f"{cname}__oracle_{i}"
    funcs, unbound, cut, cnames = {}, {}, {}, {}
    for tk, rec in nodes.items():
        rec["member"] = member_of[tk]
        rec["renames"] = {c: member_of[t] for c, t in edges.get(tk, {}).items() if member_of[t] != c}
        funcs[member_of[tk]] = rec
    for tk, reason in cut_reason.items():
        cut[member_of[tk]], cnames[member_of[tk]] = reason, tk[0]
    for e in edges.values():
        for cname, tk in e.items():
            if tk[1] == unbound_mark:
                unbound[member_of[tk]], cnames[member_of[tk]] = unbound_reason[cname], cname
    return funcs, member_of[(entry_name, entry_path)], unbound, cut, cnames, bound_scopes


def _renamed(text, renames):
    """``text`` with each call of a renamed C function naming its member (``f(`` → ``f__oracle_1(``)."""
    if not renames:
        return text
    pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(renames, key=len, reverse=True)) + r")(?=\s*\()")
    return pattern.sub(lambda m: renames[m.group(1)], text)


def _merge_record(kind, a, b, name):
    """One program object seen through two declarations (``extern const U8 tab[4];`` here, ``… = {1,2,3,4}`` there):
    the known length and the initializer values win; a real disagreement is not one object (review R1 C3)."""
    if _base_type(a["type"]) != _base_type(b["type"]):
        raise _Failure("object_name_denotes_two_objects:" + name)
    la, lb = a.get("length"), b.get("length")
    if la is not None and lb is not None and la != lb:
        raise _Failure("object_name_denotes_two_objects:" + name)
    va, vb = a.get("values"), b.get("values")
    if va is not None and vb is not None and list(va) != list(vb):
        raise _Failure("object_initializers_differ:" + name)
    out = dict(a)
    if la is None and lb is not None:
        out["length"] = lb
    if va is None and vb is not None:
        out["values"] = vb
    out["const"] = bool(a.get("const") or b.get("const"))
    return out


def _world(funcs):
    """The program objects the compiled functions use: ``{member: (kind, record)}``, per function the members its
    names denote when they differ (``{function member: {name: member}}``), and ``{name: {owner: member}}``. An
    internal-linkage object belongs to its unit: same-named ``static`` objects of two units are two members
    (``s_state__oracle_u<tag>``; review R1 W12)."""
    by_key: dict[tuple, tuple[str, dict]] = {}
    for f in funcs.values():
        for name, (kind, rec) in f["objects"].items():
            key = (name, f["path"] if rec.get("static") else "")
            if key in by_key:
                if by_key[key][0] != kind:
                    raise _Failure("object_name_denotes_two_objects:" + name)
                by_key[key] = (kind, _merge_record(kind, by_key[key][1], rec, name))
            else:
                by_key[key] = (kind, dict(rec))
    owners: dict[str, list[str]] = {}
    for name, owner in by_key:
        owners.setdefault(name, []).append(owner)
    member_of = {key: key[0] if len(owners[key[0]]) == 1 else f"{key[0]}__oracle_u{_unit_tag(key[1] or 'extern')}"
                 for key in by_key}
    objects = {member_of[key]: value for key, value in by_key.items()}
    aliases = {}
    for m, f in funcs.items():
        aliases[m] = {name: member_of[(name, f["path"] if rec.get("static") else "")]
                      for name, (_kind, rec) in f["objects"].items()
                      if member_of[(name, f["path"] if rec.get("static") else "")] != name}
    members: dict[str, dict[str, str]] = {}
    for key, member in member_of.items():
        members.setdefault(key[0], {})[key[1]] = member
    return objects, aliases, members


def _base_name(n: str) -> str:
    el = _ELEMENT.match(n)
    return el.group(1) if el else n


def _declared(scope, name):
    """``(kind, record)`` of the object ``name`` denotes in this unit's scope, or None."""
    if name in (scope.get("macro_status") or {}):
        return None
    for kind, table in (("global", scope.get("globals") or {}), ("array", scope.get("arrays") or {})):
        rec = table.get(name)
        if rec is not None:
            return kind, rec
    return None


def _fresh_member(objects, name):
    member, i = name, 0
    while member in objects:
        i += 1
        member = f"{name}__oracle_n{i}"
    return member


def _place_names(wanted, objects, members, entry_path, bound_scopes):
    """``{name: member}`` — what the claims mean by an input or observable name: the object the **entry's own unit**
    declares under it (added as a member when no compiled function uses it — review R2 WR2-1: the entry's view, not
    whichever unit happens to use the name); else the one object of that name the compiled functions use; else the one
    a bound unit declares. Several candidates and none the entry's → not placed (the claim cannot be checked)."""
    names = {}
    for name in wanted:
        mine = _declared(bound_scopes[entry_path], name)
        if mine is not None:
            kind, rec = mine
            owner = entry_path if rec.get("static") else ""
            member = members.get(name, {}).get(owner)
            if member is None:
                member = _fresh_member(objects, name)
                objects[member] = (kind, dict(rec))
                members.setdefault(name, {})[owner] = member
            names[name] = member
            continue
        known = members.get(name, {})
        if len(known) == 1:
            names[name] = next(iter(known.values()))
            continue
        if known:
            continue   # several objects of that name, none the entry unit's
        found = []
        for path in sorted(p for p in bound_scopes if p != entry_path):
            d = _declared(bound_scopes[path], name)
            if d is not None:
                found.append((path if d[1].get("static") else "", d[0], d[1]))
        if len({(o, k) for o, k, _r in found}) != 1:
            continue
        rec = found[0][2]
        try:
            for _o, _k, other in found[1:]:
                rec = _merge_record(found[0][1], rec, other, name)
        except _Failure:
            continue
        member = _fresh_member(objects, name)
        objects[member] = (found[0][1], rec)
        members.setdefault(name, {})[found[0][0]] = member
        names[name] = member
    return names


def _typedefs(funcs):
    out = {}
    for f in funcs.values():
        for name, t in f["typedefs"].items():
            if name in out and _base_type(out[name]) != _base_type(t):
                raise _Failure("typedef_differs_between_units:" + name)
            out[name] = t
    return out


def _stub_rtype(name, scopes):
    """The declared return type of a function the harness stubs, as its callers' units declare it — or ``int``."""
    from generators import c_project_context as cpc
    from generators.mcdc_design import _scope_type
    for scope in scopes:
        text = str((((scope.get("effects") or {}).get("functions") or {}).get(name) or {}).get("return_type") or "")
        if not text or "*" in text:
            continue
        if text.strip() == "void":
            return "void"
        try:
            return _base_type(_scope_type(scope, text))
        except cpc.Unresolved:
            continue
    return "int"


class _Text:
    """Lines of the harness with their numbers (a function body spans many lines)."""

    def __init__(self):
        self.parts: list[str] = []
        self.line = 0          # number of the last line emitted

    def emit(self, text: str) -> int:
        """Append ``text`` (may hold newlines); return the number of its first line."""
        first = self.line + 1
        self.parts.append(text)
        self.line += text.count("\n") + 1
        return first

    def source(self) -> str:
        return "\n".join(self.parts) + "\n"


def _input_value(value, scopes):
    """A claim input as an integer, read with the constants of every unit that may read it (the model resolves a name
    such as ``K_RUN`` in the unit that uses it): ``(value, "")``, ``(None, "")`` when no unit can read it (the model
    could not either — the fills stand in), or ``(None, reason)`` when units disagree (review R1 W3)."""
    seen = set()
    for scope in scopes:
        v = _input_int(value, scope["constants"])
        if v is not None:
            seen.add(v)
    if len(seen) > 1:
        return None, "input_value_differs_between_units"
    return (next(iter(seen)) if seen else None), ""


def _build(entry_member, entry_path, funcs, unbound, cut, cnames, bound_scopes, claims, outputs, enum_base, nonce):
    """C++ text for one entry and its claims, and its layout: where each claim run, assertion and function block is,
    the outputs the struct cannot name (``unobservable``) and the claims whose inputs cannot be placed."""
    from generators import c_project_context as cpc
    from generators.mcdc_design import _scope_type
    entry = funcs[entry_member]
    objects, aliases, members = _world(funcs)
    wanted = {_base_name(n) for n in outputs if n != "return"} | {_base_name(k) for c in claims for k in c["inputs"]}
    names = _place_names(sorted(wanted), objects, members, entry_path, bound_scopes)

    def place(n):
        """The struct expression an observable / input name denotes, or None."""
        el = _ELEMENT.match(n)
        member = names.get(el.group(1) if el else n)
        if member is None:
            return None
        kind, rec = objects[member]
        if el:
            if kind != "array" or rec.get("length") is None or int(el.group(2)) >= rec["length"]:
                return None
            return f"{member}[{el.group(2)}]"
        return member if kind == "global" else None

    placed = {n: ("__oracle_ret" if n == "return" and entry["rtype"].strip() != "void" else
                  None if n == "return" else place(n)) for n in outputs}
    unobservable = {n for n, e in placed.items() if e is None}
    outputs = [n for n in outputs if n not in unobservable]
    typedefs = _typedefs(funcs)
    order = [n for n in sorted(funcs) if n != entry_member] + [entry_member]
    stub_values = sorted({m.group(1) for c in claims for k in c["inputs"] if (m := _STUB_KEY.match(k))})
    all_scopes = [bound_scopes[entry_path]] + [s for p, s in sorted(bound_scopes.items()) if p != entry_path]
    out = _Text()
    layout = {"var": {}, "check": {}, "blocks": [], "unobservable": unobservable, "claim_unchecked": {},
              "claims_with_off": set()}
    # per claim, the compiled callees the model did not run (it read their write closure) — stubbed in that run
    off_of = {}
    for index, claim in enumerate(claims):
        ran = claim.get("interpreted")
        off_of[index] = [] if ran is None else [m for m in order if m != entry_member and funcs[m]["name"] not in ran]
        if off_of[index]:
            layout["claims_with_off"].add(index)
    out.emit("// generated by scripts/integration_oracle_clang_check.py — do not edit")
    widths = {}
    for scope in all_scopes:
        for k, w in ((scope.get("target") or {}).get("widths") or {}).items():
            if widths.setdefault(k, w) != w:
                raise _Failure("target_widths_differ_between_units:" + k)
    for k, w in sorted(widths.items()):
        if k in _WIDTH_TYPES:   # the target must have the widths the project's typedefs testify (review R1 W8)
            out.emit(f'static_assert(sizeof({_WIDTH_TYPES[k]}) * 8 == {int(w)}, "__oracle_width_{k.replace(" ", "_")}");')
    for name, t in sorted(typedefs.items()):
        out.emit(f"typedef {_base_type(t, enum_base)} {name};")
    k_of = {name: k for k, name in enumerate(outputs)}
    slot_of = {p: i for i, p in enumerate(_PSEUDO)}
    for variant, fill in enumerate(_FILLS):
        out.emit(f"namespace __oracle_v{variant} {{")
        out.emit(f"constexpr int __oracle_stub = {fill};")
        out.emit("struct __oracle_world {")
        for member, (kind, rec) in sorted(objects.items()):
            t = rec["type"]
            if kind == "global":
                out.emit(f"  {_base_type(t, enum_base)} {member} = {_fill_for(t, fill)};")
                continue
            if rec.get("length") is None:
                raise _Failure("array_length_unresolved:" + member)
            elems = rec["values"] if rec.get("const") and rec.get("values") is not None else \
                [_fill_for(t, fill)] * rec["length"]
            out.emit(f"  {_base_type(t, enum_base)} {member}[{rec['length']}] = {{{', '.join(str(v) for v in elems)}}};")
        out.emit("  " + " ".join(f"long long {p}_calls = 0;" for p in _PSEUDO))
        for s in stub_values:
            out.emit(f"  bool __oracle_son_{s} = false; long long __oracle_sval_{s} = 0;")
        callees = [m for m in order if m != entry_member]
        if callees:
            out.emit("  " + " ".join(f"bool __oracle_off_{m} = false;" for m in callees))
        for kind, table in ((_UNBOUND, unbound), (_CUT, cut)):
            for name in sorted(table):
                cname = cnames.get(name, name)
                if cname in _NOT_A_MEMBER:
                    continue   # a call site of it cannot compile: its caller is cut
                rt = _stub_rtype(cname, [f["scope"] for f in funcs.values() if cname in f["calls"]] + all_scopes)
                given = f"if (__oracle_son_{cname}) return ({rt})__oracle_sval_{cname}; " \
                    if cname in stub_values and rt != "void" else ""
                ret = "return;" if rt == "void" else f"return ({rt})__oracle_stub;"
                out.emit(f"  template<class... __oracle_A> constexpr {rt} {name}(__oracle_A...) "
                         f"{{ {given}++{kind}_calls; {ret} }}")
        ctor: list[str] = []
        for name in order:
            f = funcs[name]
            block_start = out.line + 1
            defined = list(f["macros"]) + list(f["consts"]) + list(aliases.get(name, {})) + list(f["kw_typedefs"])
            for m in defined:
                out.emit(f"#undef {m}")
            fb = f["scope"].get("function_like_macro_bodies") or {}
            fp = f["scope"].get("function_like_macro_params") or {}
            mb = f["scope"].get("macro_bodies") or {}
            for alias, member in aliases.get(name, {}).items():
                out.emit(f"#define {alias} {member}")   # this unit's object of that name (review R1 W12)
            for t in f["kw_typedefs"]:
                out.emit(f"#define {t} __oracle_td_{t}")   # ``typedef unsigned char bool;`` (review R2 IR2-4)
            for m in f["macros"]:
                if m in fb:
                    text = _untagged(_renamed(_one_line(fb[m]), f["renames"]), f["enum_tags"])
                    out.emit(f"#define {m}({', '.join(fp.get(m) or [])}) {text}")
                else:
                    out.emit(f"#define {m} {_untagged(_renamed(_one_line(mb[m]), f['renames']), f['enum_tags'])}")
            for m, c in f["consts"].items():
                out.emit(f"#define {m} (({_base_type(c['type'])})({c['value']}))")
            prefix = []
            if f["name"] in stub_values and name != entry_member:
                # a sequence stub replaces the callee — never the function under test (review R1 W4)
                prefix.append("if (__oracle_son_%s) return%s;" % (f["name"], "" if f["rtype"].strip() == "void"
                                                                   else f" ({f['rtype']})__oracle_sval_{f['name']}"))
            if name != entry_member:
                # (review R2 CR2-1) a callee the model did not run in this claim (budget, linkage, depth, …) — it read
                # its write closure instead: here it is an unbound stub for that claim, never a body whose undefined
                # behaviour the model had no chance to see
                prefix.append("if (__oracle_off_%s) { ++%s_calls; return%s; }" % (
                    name, _UNBOUND, "" if f["rtype"].strip() == "void" else f" ({f['rtype']})__oracle_stub"))
            if f.get("unsequenced"):
                prefix.append(f"++{_UNSEQ}_calls;")
            for spec in f["statics"]:
                base = _base_type(spec["type"], enum_base)
                dims = f"[{spec['size']}]" if spec["size"] is not None else ""
                if spec["const"]:
                    out.emit(f"  const {base} {spec['member']}{dims} = {spec['init']};")
                elif dims:
                    out.emit(f"  {base} {spec['member']}{dims};")
                    ctor.append(f"for (auto &__oracle_x : {spec['member']}) __oracle_x = {_fill_for(spec['type'], fill)};")
                else:
                    out.emit(f"  {base} {spec['member']} = {_fill_for(spec['type'], fill)};")
            params = ", ".join(p[1] for p in f["params"])
            body = _renamed(f["body"], f["renames"])
            if prefix:
                body = "{ " + " ".join(prefix) + " " + body + " }"
            out.emit(f"  constexpr {f['rtype']} {name}({params}) {body}")
            layout["blocks"].append((block_start, out.line, name))
            for m in defined:
                out.emit(f"#undef {m}")
        # the observer reads the struct with no unit's macros active: an observable that is an object elsewhere is
        # never read as the entry unit's constant of the same name (review R1 W2)
        lines = ["  constexpr long long __oracle_observe(int __oracle_k, long long __oracle_ret) {",
                 "    switch (__oracle_k) {"]
        lines += [f"      case {-1 - i}: return {p}_calls;" for i, p in enumerate(_PSEUDO)]
        lines += [f"      case {k}: return (long long)({placed[n]});" for n, k in k_of.items()]
        lines += ["    }", "    return -999999999LL;", "  }"]
        start = out.emit("\n".join(lines))
        layout["blocks"].append((start, out.line, "__oracle_observe"))
        out.emit("  constexpr __oracle_world() { " + " ".join(ctor) + " }")
        out.emit("};")
        out.emit(f"struct __oracle_res {{ long long v[{len(outputs) + len(_PSEUDO)}]; }};")
        for index, claim in enumerate(claims):
            body = ["  __oracle_world __w{};"]
            if off_of[index]:
                body.append("  " + " ".join(f"__w.__oracle_off_{m} = true;" for m in off_of[index]))
            for key, value in claim["inputs"].items():
                m = _STUB_KEY.match(key)
                v, why = _input_value(value, all_scopes)
                if why:
                    layout["claim_unchecked"][index] = why
                if m:
                    if v is not None and m.group(1) in stub_values:
                        body.append(f"  __w.__oracle_son_{m.group(1)} = true; __w.__oracle_sval_{m.group(1)} = {v}LL;")
                    continue
                target = place(key)
                if target is None:
                    continue
                el = _ELEMENT.match(key)
                kind, rec = objects[names[el.group(1) if el else key]]
                if v is None or not _fits(v, rec["type"]) or (kind == "array" and rec.get("const")):
                    continue
                body.append(f"  __w.{target} = {v};")
            args = []
            for i, (pname, _decl, scalar, typ) in enumerate(entry["params"]):
                try:
                    t = _scope_type(entry["scope"], typ)
                except cpc.Unresolved:
                    raise _Failure("parameter_type_unresolved:" + pname) from None
                if scalar:
                    v, why = _input_value(claim["inputs"].get(pname), all_scopes[:1])
                    args.append(str(v if _fits(v, t) else _fill_for(t, fill)))
                else:
                    body.append(f"  {_base_type(t, enum_base)} __oracle_buf_{i}[64] = {{}};")
                    body.append(f"  for (int __oracle_j = 0; __oracle_j < 64; ++__oracle_j) __oracle_buf_{i}[__oracle_j] = "
                                f"{_fill_for(t, fill)};")
                    args.append(f"__oracle_buf_{i}")
            call = f"__w.{entry_member}({', '.join(args)})"
            if entry["rtype"].strip() == "void":
                body.append(f"  {call}; long long __oracle_ret = 0;")
            else:
                body.append(f"  long long __oracle_ret = (long long){call};")
            body.append("  __oracle_res __r{};")
            for i, _p in enumerate(_PSEUDO):
                body.append(f"  __r.v[{i}] = __w.__oracle_observe({-1 - i}, __oracle_ret);")
            for name_o in claim["outputs"]:
                if name_o in k_of:
                    body.append(f"  __r.v[{k_of[name_o] + len(_PSEUDO)}] = __w.__oracle_observe({k_of[name_o]}, __oracle_ret);")
            body.append("  return __r;")
            out.emit(f"constexpr __oracle_res __oracle_run_{index}() {{\n" + "\n".join(body) + "\n}")
            layout["var"][out.emit(f"constexpr __oracle_res __oracle_r_{index} = __oracle_run_{index}();")] = (index, variant)
            for name_o, value in [*((p, 0) for p in _PSEUDO), *((n, v) for n, v in claim["outputs"].items() if n in k_of)]:
                slot = slot_of[name_o] if name_o in slot_of else k_of[name_o] + len(_PSEUDO)
                tag = f"__oracle_check_{index}_{variant}_{slot}"
                line = out.emit(f"static_assert(__oracle_r_{index}.v[{slot}] == {int(value)}LL, \"{tag}\");")
                layout["check"][line] = (index, name_o, variant)
        out.emit("}")
    out.emit(f'static_assert(1 == 2, "__oracle_canary_{nonce}");')
    meta = {"enum": any(f["enum"] for f in funcs.values())}
    return out.source(), layout, meta


def _compile(source, layout, path, clang, target, timeout, nonce):
    """Run clang once; attribute every diagnostic to a claim run, an assertion, a function block, or 'other'."""
    Path(path).write_text(source, encoding="utf-8", newline="\n")
    try:
        # ``-Wunsequenced`` as a warning: a function clang flags still compiles, and runs that reach it are set aside
        proc = subprocess.run([clang, "-x", "c++", f"--target={target}", "-std=c++20", "-fsyntax-only",
                               "-ferror-limit=0", "-fconstexpr-steps=20000000", "-fconstexpr-backtrace-limit=0",
                               "-Wno-everything", "-Wunsequenced", path],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"failure": "clang_failed:" + type(exc).__name__}
    res = {"failure": "", "var": {}, "check": {}, "block": {}, "unsequenced": set(), "other": []}
    canary, current = False, None
    for line in (proc.stdout + proc.stderr).splitlines():
        m = _DIAG.match(line)
        if not m:
            if re.match(r"^(?:\S*clang\S*: )?(?:fatal )?error:", line.strip()):
                res["other"].append("driver: " + line.strip()[:160])
            continue
        lineno, kind, message = int(m.group(1)), m.group(2), m.group(3)
        if f"__oracle_canary_{nonce}" in message:
            canary, current = True, None   # exactly this compilation's canary (review R1 C1)
            continue
        block = next((b[2] for b in layout["blocks"] if b[0] <= lineno <= b[1]), None)
        if kind == "warning":
            if "unsequenced" in message and block is not None:
                res["unsequenced"].add(block)
            current = None
            continue
        if kind == "note":
            if current is not None:
                current.append(message)
            continue
        if lineno in layout["var"]:
            current = res["var"].setdefault(layout["var"][lineno], [])
        elif lineno in layout["check"]:
            current = res["check"].setdefault(layout["check"][lineno], [])
        elif block is not None and block != "__oracle_observe":
            current = res["block"].setdefault(block, [])
        else:
            res["other"].append(f"{lineno}: {message}")
            current = None
            continue
        current.append(message)
    if not canary or proc.returncode != 1:
        res["failure"] = "canary_not_reported:" + (res["other"][0] if res["other"] else f"rc={proc.returncode}")
    elif res["other"]:
        width = next((o for o in res["other"] if "__oracle_width_" in o), None)
        res["failure"] = ("target_width_mismatch:" + width) if width else "harness_compile_error:" + res["other"][0]
    return res


def _unquoted(message: str) -> str:
    """A diagnostic without its quoted names: ``in call to 'this->do_shift(1)'`` does not say "shift" (review R1 W1)."""
    return re.sub(r"'[^']*'", "''", message or "")


def _verdicts(claims, res, unobservable):
    """(index, output) → (worst verdict over the fills, detail, [(verdict, messages) per failing fill])."""
    out: dict[tuple, tuple] = {}
    for index, claim in enumerate(claims):
        for name in [*_PSEUDO, *(n for n in claim["outputs"] if n not in unobservable)]:
            worst, detail, failing = "agree", "", []
            for variant in range(len(_FILLS)):
                run = res["var"].get((index, variant))
                if run:
                    one = "eval_error" if any(_REAL_EVAL_ERROR.search(_unquoted(x)) for x in run) else "constexpr_limit"
                    msgs = run
                else:
                    msgs = res["check"].get((index, name, variant)) or []
                    one = "agree" if not msgs else ("mismatch" if any("static assertion failed" in x for x in msgs)
                                                    else "constexpr_limit")
                if one != "agree":
                    failing.append((one, msgs))
                if _CHECK_RANK[one] > _CHECK_RANK[worst]:
                    worst = one
                    text = next((x for x in msgs if "evaluates to" in x), None) if one == "mismatch" else None
                    detail = (text or " | ".join(msgs[:3])) + f" (fill={_FILLS[variant]})"
            out[(index, name)] = (worst, detail, failing)
    return out


_CALL_NOTE = re.compile(r"in call to 'this->(\w+)\(")


def _classify(claims, verdict, unobservable, claim_unchecked, cut, unbound, unsequenced, claims_with_off=frozenset(),
              cname_of=None, where_of=None):
    """The final verdict of every claimed output for one compilation (one enum type). ``cname_of``: member → C name,
    ``where_of``: member → ``name (file)`` for the report."""
    cname_of, where_of = cname_of or {}, where_of or {}
    final = {}
    for index, claim in enumerate(claims):
        # a run that did not finish cannot say what it reached: with such a function in the struct, assume it did
        cut_reached = bool(cut) and verdict[(index, _CUT)][0] != "agree"
        unbound_reached = (bool(unbound) or index in claims_with_off) and verdict[(index, _UNBOUND)][0] != "agree"
        unseq_reached = bool(unsequenced) and verdict[(index, _UNSEQ)][0] != "agree"
        for name in claim["outputs"]:
            if name in unobservable:
                final[(index, name)] = ("unchecked:observable_not_in_harness", "")
                continue
            v, d, failing = verdict[(index, name)]
            # the member functions on clang's call stack where it failed, innermost first
            frames = [m.group(1) for one, msgs in failing if one == "eval_error" for x in msgs
                      for m in _CALL_NOTE.finditer(x)]
            effects = claim.get("effects_only")
            partly = [f for f in frames if effects is None or cname_of.get(f, f) in effects]
            if not partly and (effects is None or effects) and any(
                    "calls in backtrace" in x for one, msgs in failing if one == "eval_error" for x in msgs):
                # clang cut the call stack (``skipping N calls in backtrace``): an effects-only frame may be among the
                # skipped ones — not a contradiction we can place (review R4 W4-1; the backtrace limit is 0 above)
                partly = ["<skipped frames>"]
            if index in claim_unchecked:
                v = "unchecked:" + claim_unchecked[index]
            elif v == "eval_error" and partly:
                # (review R3 W3-1) the model ran this callee as its write closure at some call site (or the sheet does
                # not say): undefined behaviour on a path through it is one the model may never have seen
                v = "unchecked:callee_partly_interpreted"
            elif v == "eval_error" and all(_disclosure_explains(claim.get("possible_ub"), _unquoted(" | ".join(msgs)))
                                           for one, msgs in failing if one == "eval_error"):
                # every fill that failed is explained by what the model disclosed (review R1 W6)
                v = "unchecked:possible_ub_disclosed"
            elif v == "constexpr_limit":
                v = "unchecked:constexpr_limit"
            elif unseq_reached:
                v = "unchecked:unsequenced_function_reached"
            elif cut_reached:
                v = "agree_with_cut_callees" if v == "agree" else "unchecked:cut_callee_reached"
            elif v == "agree" and unbound_reached:
                v = "agree_with_stubbed_callees"
            if v == "eval_error":
                # where it failed: the innermost function of clang's call notes, by C name and file (R2 IR2-9, R3 I3-4;
                # a failed assertion carries no call notes — a mismatch says nothing here)
                d = d + (f" [in {where_of.get(frames[0], frames[0])}]" if frames else " [in the entry]")
            final[(index, name)] = (v, d)
    return final


def check_group(entry_name, entry_path, claims, files, scopes, provider, parser, clang="clang", target="msp430",
                work_dir=None, timeout=600):
    """Verdicts for the claims of one entry function: ``{(claim index, output): (verdict, detail)}``, and group notes.
    ``work_dir`` must be this group's own directory (two groups sharing a file would read each other's result)."""
    notes: dict = {"cut": {}, "unbound": {}, "unsequenced": [], "functions": 0, "rounds": 0}
    outputs = list(dict.fromkeys(n for c in claims for n in c["outputs"]))
    try:
        with _PY_LOCK:
            funcs, entry_member, unbound, cut, cnames, bound_scopes = _closure(entry_name, entry_path, files, scopes,
                                                                               provider, parser)
        work = work_dir or tempfile.mkdtemp(prefix="oracle_world_")
        os.makedirs(work, exist_ok=True)
        final: dict[tuple, tuple[str, str]] = {}
        for bi, base in enumerate(_ENUM_BASES):
            try:
                res, layout, meta = _compile_base(bi, base, entry_member, entry_path, funcs, unbound, cut, cnames,
                                                  bound_scopes, claims, outputs, notes, work, clang, target, timeout)
            except _Failure as exc:
                if not final:
                    raise
                # (review R2 IR2-1) a later enum type failed: what the earlier ones proved stays — a contradiction is
                # still one; everything else is unchecked with the reason
                notes["failure_partial"] = f"enum_base_{base}:{exc}"
                final = {k: (v, d) if v in {"mismatch", "eval_error"} else ("unchecked:enum_base_failed", str(exc)[:120])
                         for k, (v, d) in final.items()}
                break
            with _PY_LOCK:
                verdict = _verdicts(claims, res, layout["unobservable"])
            # (review R1 I10) each enum type judged with its own compilation's cut set, then the worst verdict kept
            unsequenced = [n for n, f in funcs.items() if f.get("unsequenced")]
            cname_of = {m: f["name"] for m, f in funcs.items()}
            where_of = {m: f"{f['name']} ({os.path.basename(f['path'])})" for m, f in funcs.items()}
            for k, (v, d) in _classify(claims, verdict, layout["unobservable"], layout["claim_unchecked"], cut,
                                       unbound, unsequenced, layout["claims_with_off"], cname_of, where_of).items():
                d = d + ("" if base == "int" else f" (enum as {base})")
                if k not in final or _FINAL_RANK[v.split(":", 1)[0]] > _FINAL_RANK[final[k][0].split(":", 1)[0]]:
                    final[k] = (v, d)
            if not meta["enum"]:
                break
    except _Failure as exc:
        return None, {**notes, "failure": str(exc)}
    except Exception as exc:  # noqa: BLE001 — one group's harness failure is that group's reason, never the whole report's
        return None, {**notes, "failure": f"harness_exception:{type(exc).__name__}:{str(exc)[:120]}"}
    notes["cut"], notes["unbound"] = dict(cut), dict(unbound)
    notes["unsequenced"] = sorted(n for n, f in funcs.items() if f.get("unsequenced"))
    notes["functions"] = len(funcs)
    return final, notes


def _compile_base(bi, base, entry_member, entry_path, funcs, unbound, cut, cnames, bound_scopes, claims, outputs,
                  notes, work, clang, target, timeout):
    """Compile for one enum type until nothing more is cut or flagged: ``(result, layout, meta)``. A function clang
    rejects is cut (the entry cannot be); one clang flags unsequenced is instrumented and compiled again."""
    for _round in range(_CUT_ROUNDS):
        notes["rounds"] += 1
        nonce = secrets.token_hex(8)
        with _PY_LOCK:
            source, layout, meta = _build(entry_member, entry_path, funcs, unbound, cut, cnames, bound_scopes,
                                          claims, outputs, base, nonce)
        res = _compile(source, layout, os.path.join(work, f"b{bi}_r{notes['rounds']}.cpp"), clang, target, timeout,
                       nonce)
        if res["failure"]:
            raise _Failure(res["failure"])
        fresh = {b for b in res["unsequenced"] if not funcs.get(b, {}).get("unsequenced")}
        for b in fresh:
            funcs[b]["unsequenced"] = True   # compiled, but a run that reaches it is set aside
        if res["block"]:
            if entry_member in res["block"]:
                raise _Failure("entry_does_not_compile:" + res["block"][entry_member][0][:160])
            for name, msgs in res["block"].items():
                cut[name], cnames[name] = "harness_compile_error:" + msgs[0][:120], funcs[name]["name"]
                del funcs[name]
            continue
        if not fresh:
            return res, layout, meta
    raise _Failure("cut_rounds_exhausted")


def _read_claims(xlsm):
    import openpyxl
    wb = openpyxl.load_workbook(xlsm, read_only=True)
    ws = wb["Test Evidence"]
    rows = ws.iter_rows(values_only=True)
    header = list(next(rows))
    grouped: dict[tuple, dict] = {}
    unreadable = Counter()
    for row in rows:
        d = dict(zip(header, row, strict=False))
        if d.get("Status") != "derived":
            continue
        key = (str(d["Source path"]), str(d["Entry function"]), str(d["Test Case ID"]), str(d["Case"]))
        reason = str(d.get("Reason") or "")
        if key not in grouped:
            try:
                inputs = json.loads(d.get("Inputs JSON") or "{}")
            except (TypeError, ValueError):
                unreadable["inputs_json_unreadable"] += 1   # a truncated cell (32,767 chars) — not guessed
                continue
            grouped[key] = {"inputs": inputs, "outputs": {}, "source_hash": str(d.get("Source SHA256") or ""),
                            "possible_ub": reason.split("possible_ub=", 1)[1].split("+") if "possible_ub=" in reason else [],
                            # (review R2 CR2-1) the callees the model ran for this case; the rest it read as effects
                            "interpreted": set() if "Callees interpreted" in header else None,
                            # (review R3 W3-1) and the ones it read as effects at some call site (None: not recorded)
                            "effects_only": set() if "Callees effects-only" in header else None}
        grouped[key]["outputs"][str(d["Observable"])] = int(d["Expected"])
        for field, column in (("interpreted", "Callees interpreted"), ("effects_only", "Callees effects-only")):
            if grouped[key][field] is not None:
                grouped[key][field] |= {c.strip() for c in str(d.get(column) or "").split(",") if c.strip()}
    wb.close()
    return grouped, unreadable


def _project(source_root):
    from generators.c_project_context import build_project_context, build_scopes, detect_build_config, shared_parser
    from generators.integration_oracle import CalleeProvider
    roots = [r.strip() for r in re.split(r"[,;]", source_root) if r.strip()]
    texts, unread = {}, []
    for root in roots:
        for p in sorted(Path(root).rglob("*")):
            if p.suffix.lower() in (".c", ".h") and p.is_file():
                try:
                    texts[str(p.resolve())] = p.read_bytes().decode("utf-8")
                except UnicodeDecodeError:
                    unread.append(str(p.resolve()))
    cprojects = {str(Path(r) / ".cproject"): (Path(r) / ".cproject").read_text(encoding="utf-8", errors="replace")
                 for r in roots if (Path(r) / ".cproject").is_file()}
    context = build_project_context(texts, detect_build_config(cprojects), roots=[str(Path(r).resolve()) for r in roots])
    context["incomplete_files"] = unread
    units = [p for p in context["files"] if p.lower().endswith(".c") and p in texts]
    scopes = build_scopes(context, units)
    parser = shared_parser()
    return texts, scopes, CalleeProvider(context, texts, scopes, parser), parser


def _shape(message: str) -> str:
    """A diagnostic without its names and numbers — what kind of limit it is (``read of volatile …``)."""
    return re.sub(r"\d+", "N", re.sub(r"'[^']*'", "'…'", message or ""))[:120]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--xlsm", required=True, help="generated SITS workbook with a 'Test Evidence' sheet")
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--clang", default="clang")
    ap.add_argument("--target", default="msp430")
    ap.add_argument("--out", default="")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args(argv)
    t0 = time.time()
    grouped, unreadable = _read_claims(args.xlsm)
    texts, scopes, provider, parser = _project(args.source_root)
    by_norm = {os.path.normcase(os.path.abspath(p)): p for p in scopes}   # the sheet's path as the OS names it (I8)
    by_entry: dict[tuple, list] = {}
    skipped = Counter(unreadable)
    for (path, entry, tc, case), g in grouped.items():
        real = by_norm.get(os.path.normcase(os.path.abspath(path)))
        if real is None:
            skipped["source_missing"] += len(g["outputs"])
            continue
        if g["source_hash"] and g["source_hash"] not in _text_hashes(texts[real]):
            skipped["source_changed"] += len(g["outputs"])
            continue
        by_entry.setdefault((real, entry), []).append({**g, "key": (tc, case)})
    print(f"claims {sum(len(g['outputs']) for g in grouped.values())} · sequences {len(grouped)} · entries "
          f"{len(by_entry)} · skipped {dict(skipped)} · {time.time() - t0:.0f}s", flush=True)
    work = tempfile.mkdtemp(prefix="oracle_world_")
    items = sorted(by_entry.items(), key=lambda x: -len(x[1]))

    def run(indexed):
        index, ((path, entry), claims) = indexed
        # one directory per group, never shared: names that differ only in case (``Init``/``init``) or share a long
        # prefix would otherwise compile each other's source (review R1 C1)
        folder = os.path.join(work, f"g{index:04d}_" + re.sub(r"\W", "_", entry)[:32])
        return (path, entry), claims, check_group(entry, path, claims, texts, scopes, provider, parser, clang=args.clang,
                                                  target=args.target, work_dir=folder, timeout=args.timeout)

    report = {"xlsm": args.xlsm, "source_root": args.source_root, "target": args.target, "fills": list(_FILLS),
              "claims": 0, "verdicts": Counter(), "unchecked_reasons": Counter(), "group_failures": Counter(),
              "mismatches": [], "eval_errors": [], "cut": Counter(), "cut_messages": Counter(), "unbound": Counter(),
              "limit_notes": Counter(), "unsequenced_functions": Counter(), "entries": {}, "skipped": dict(skipped)}
    done, groups_checked, canary_failures = 0, 0, 0
    # (thread pool) the work is clang subprocesses; the Python side builds under `_PY_LOCK`
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for (path, entry), claims, (final, notes) in pool.map(run, enumerate(items)):
            n = sum(len(c["outputs"]) for c in claims)
            report["claims"] += n
            if final is None:
                reason = notes["failure"].split(":", 1)[0]
                canary_failures += reason in {"canary_not_reported", "clang_failed"}
                report["verdicts"]["unchecked"] += n
                report["unchecked_reasons"]["group:" + reason] += n
                report["group_failures"][notes["failure"][:160]] += n
            else:
                groups_checked += 1
                for (index, name), (v, d) in final.items():
                    report["verdicts"][v.split(":", 1)[0]] += 1
                    if v.startswith("unchecked:"):
                        report["unchecked_reasons"][v.split(":", 1)[1]] += 1
                    if v == "unchecked:constexpr_limit":
                        report["limit_notes"][_shape(d.split(" | ")[1] if " | " in d else d)] += 1
                    listed = {"mismatch": "mismatches", "eval_error": "eval_errors"}.get(v)
                    if listed and len(report[listed]) < 200:
                        report[listed].append(
                            {"entry": entry, "file": path, "tc": claims[index]["key"], "output": name,
                             "claimed": claims[index]["outputs"][name], "clang": d,
                             "inputs": dict(list(claims[index]["inputs"].items())[:12])})
                for why in notes["cut"].values():
                    report["cut"][why.split(":", 1)[0]] += 1
                    report["cut_messages"][_shape(why)] += 1
                for why in notes["unbound"].values():
                    report["unbound"][why.split(":", 1)[0]] += 1
                for name in notes["unsequenced"]:
                    report["unsequenced_functions"][name] += 1
            report["entries"][f"{entry} ({path})"] = {   # the full path: APP and BOOT both have ``main (main.c)``
                "claims": n, "functions": notes.get("functions"), "rounds": notes.get("rounds"),
                "failure": notes.get("failure", ""), "cut": sorted(notes.get("cut") or {})[:20],
                "unbound": len(notes.get("unbound") or {})}
            done += 1
            print(f"{done}/{len(by_entry)} entries · {time.time() - t0:.0f}s · {dict(report['verdicts'])}", flush=True)
    for k in ("verdicts", "unchecked_reasons", "group_failures", "cut", "cut_messages", "unbound", "limit_notes",
              "unsequenced_functions"):
        report[k] = dict(report[k].most_common(40))
    report["groups_checked"] = groups_checked
    report["elapsed_s"] = round(time.time() - t0, 1)
    report["work_dir"] = work
    text = json.dumps(report, ensure_ascii=False, indent=1, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("claims", "verdicts", "unchecked_reasons", "skipped", "groups_checked",
                                             "elapsed_s")}, ensure_ascii=False))
    if report["verdicts"].get("mismatch") or report["verdicts"].get("eval_error"):
        return 1
    agreed = sum(n for v, n in report["verdicts"].items() if v.startswith("agree"))
    if report["claims"] == 0 or groups_checked == 0 or canary_failures or agreed == 0:
        # nothing checked (every claim unchecked counts too — review R2 WR2-2), or a compilation that could not prove
        # it ran (review R1 W7)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
