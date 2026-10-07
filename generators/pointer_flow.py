"""(R64) Where a write through a pointer can land — a project-wide points-to analysis.

Until R64 a callee the source oracle runs as its write closure that writes through a pointer (``pointer_write``), and
a sequence stub that may put a value through a pointer, made *every* object a pointer can reach unknown: every array,
every object whose address the project takes anywhere, every escaped local (`havoc_pointer_targets`). In KJPDS02_PV
that was 57% of the unknown expected values — ``ld_send_message`` (the LIN reply, which writes the transport queue)
alone 149,941 cells — and an EEPROM read stub without a single pointer parameter cleared every buffer of the caller.

This module answers *which* objects, or says it cannot:

* **facts** (`function_facts`, `file_facts`, read from the tree when the project context scans a file and cached with
  it). A function's facts are records: a store (``lvalue = value``, ``++``/``--``, an initializer), a call (callee,
  each argument, the call's text for a macro), a ``return``, what escapes to unseen code, and what the facts cannot
  hold (an ``ERROR`` region, inline assembly). Lvalues and values are small trees — a variable, ``*v``, a member, a
  value, an address, a cast, pointer arithmetic, a call's value — so the solver can follow the declared types: whether
  ``qd[h]`` is an array (its address) or a pointer (what it holds) is the type's to say, not a guess. A file's facts add
  its objects' declared kinds, initializers, typedef derivations and struct members;
* **solution** (`analyze`) — inclusion-based (Andersen), flow- and context-insensitive, over every definition and
  initializer the context read. Objects are globals (by name), each function's parameters and locals, return slots;
  a struct is one object (field-insensitive). An object or a value of integer type holds no pointer: an integer
  converted to a pointer addresses hardware, not a C object (the assumption the source oracle already discloses —
  ``ASSUMPTIONS``: a constant converted to a pointer — a literal, an enumerator, a macro of one, arithmetic of
  those — addresses one object `HARDWARE`) — nor does a struct or union every member of which is an integer. What
  keeps that sound: any other integer converted to a pointer may be a pointer converted to an integer and back, or a
  pointer's bytes — unknown (``?U:integer_to_pointer``; review R64 rounds 3–5, implicit conversions in a store, an
  argument, a return too); a pointer read from an object that cannot hold one, or from fixed-address memory, is
  unknown (``?U:integer_reinterpreted``, ``?U:hardware``); every object a pointer that became an integer pointed to
  (a cast, a pointer stored, passed or returned as an integer, its bytes read as integers, an integer read of a union
  or of integer storage holding pointers — the integer referents) and everything reachable from them holds an unknown
  pointer, so a pointer stored through an integer-made pointer, which the graph does not follow, is seen as unknown by
  whoever reads it (rounds 5 B, 6 C2/C3); a non-constant integer item of an initializer of an object that may hold
  pointers is read as one converted to a pointer (round 6 W1); an integer object a pointer is stored into —
  directly or by a library copy (a pool, a mailbox slot — type punning) — holds it after all, and no byte write over
  it counts as its own type. A token object (``?U``, ``?S``, ``?T``) holds itself only. Bytes are not values: what is not a pointer
  written over an object that may hold pointers — through a pointer whose type is not the object's (a byte copy
  ``d[i] = s[i]``, a cast overlay; a character pointer reaches every byte, so a member of its type is no proof) or
  through a union member anywhere on the path, or a library copy from bytes — leaves the pointers it holds unknown,
  whatever path the bytes took (review R64 C-8, rounds 2 and 3; settled on the solution, `Analysis.settle`). Where a
  declared type cannot be followed both readings are kept (an over-approximation), and an object whose type is not
  known — a struct whose body does not parse or names a macro as a member, a typedef name a unit #defines or a
  function declares in its block — may hold anything. What the analysis cannot see
  is an unknown token ``?U:<cause>`` that flows like any object; a write whose pointer may hold one has unknown targets:
  a call to code without a project definition (it may keep or hand back whatever its arguments reach), a function
  whose address is taken (an indirect call passes anything), an unread region, inline assembly, a macro whose text hides
  what it does, a name a function body ``#define``s;
* **harness tokens** — what the test harness puts in, meaningful only in the run that has it: ``?P:F:p`` the object a
  sequence passes as F's pointer parameter ``p`` when F is the function under test (R40 binds it to ``@pointee:p``),
  ``?T:F`` a pointer held in that object, ``?S:G`` what a stub of G hands back or puts through its pointer parameters
  when the run stubs G;
* **summaries** (`Analysis.summary`) — per function, over everything it reaches: the objects a write through a pointer
  may land on (``abs``) and the parameters written through *directly* (``params``: ``p[i] = …`` on a parameter never
  reassigned, or passed on to a parameter that is) — those are resolved with the arguments of the call at hand
  (``g_Lib_u8bit_ArrayClear(u8s_Buf, n)`` clears ``u8s_Buf``, not every buffer some caller passes).

The analysis is refused whole when the context did not read every file or include (`designator_gap`) or a function
body holds a directive line the walk could not read: a flow there is not one the facts hold.
"""
from __future__ import annotations

import re
from typing import Any

# Expression node types `_Facts.value` reads; a statement walk hands any of these to it whole.
_EXPRESSIONS = frozenset({
    "extension_expression",
    "identifier", "true", "false", "null", "number_literal", "char_literal", "string_literal", "concatenated_string",
    "parenthesized_expression", "cast_expression", "pointer_expression", "unary_expression", "binary_expression",
    "update_expression", "assignment_expression", "conditional_expression", "comma_expression", "call_expression",
    "field_expression", "subscript_expression", "sizeof_expression", "alignof_expression", "offsetof_expression",
    "compound_literal_expression", "initializer_list", "gnu_asm_expression", "generic_expression"})
_CONSTANTS = frozenset({"true", "false", "null", "number_literal", "char_literal", "string_literal",
                        "concatenated_string", "sizeof_expression", "alignof_expression", "offsetof_expression"})
_PREPROC_SKIP = frozenset({"preproc_def", "preproc_function_def", "preproc_call", "preproc_include"})
_PREPROC_IF = frozenset({"preproc_if", "preproc_ifdef", "preproc_elif", "preproc_elifdef"})
# operators whose result is a truth value or a count — never a pointer
_NO_POINTER_OPS = frozenset({"==", "!=", "<", ">", "<=", ">=", "&&", "||"})
_ARITH_WORDS = frozenset({"char", "short", "int", "long", "float", "double", "signed", "unsigned", "_Bool", "bool",
                          "void"})
_QUALIFIER_WORDS = frozenset({"const", "volatile", "register", "static", "extern", "auto", "inline", "restrict",
                              "__inline", "__restrict", "far", "near", "__far", "__near"})
# A call text kept for a macro expansion at solve time; a longer call is expanded as unknown.
_CALL_TEXT_BUDGET = 400
_MACRO_DEPTH = 12
_TYPE_DEPTH = 16
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_ASSIGNS = re.compile(r"\+\+|--|<<=|>>=|[-+*/%&|^]=|(?<![=!<>])=(?!=)")
# Library functions whose pointer behaviour is known, when the project defines no function of that name: the argument
# whose value the call returns, and whether pointer contents flow from the second argument's objects to the first's.
_LIBRARY = {"memcpy": (0, True), "memmove": (0, True), "memset": (0, False), "strcpy": (0, False),
            "strncpy": (0, False), "strcat": (0, False), "strncat": (0, False), "memcmp": (None, False),
            "strcmp": (None, False), "strncmp": (None, False), "strlen": (None, False)}
_NONE = ["n"]
_BYTE_COPIES = frozenset({"memcpy", "memmove", "strcpy", "strncpy", "strcat", "strncat"})
HARDWARE = "G:<hardware>"   # what an integer constant converted to a pointer addresses (one object for all of it)


def type_words_only(text: str, type_names) -> bool:
    """A macro body that is a type name (``unsigned char``, ``U8 *``, ``const BYTE``) — words of C types, qualifiers and
    the tree's typedef names, and ``*``."""
    words = re.findall(r"[A-Za-z_]\w*|\S", text)
    return bool(words) and all(w == "*" or w in _ARITH_WORDS or w in _QUALIFIER_WORDS or w in ("struct", "union", "enum")
                               or w in type_names for w in words)


def _text(node, raw: bytes) -> str:
    return raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _named(node):
    return [c for c in node.named_children if c.type != "comment"] if node is not None else []


def _walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def _unwrap(n):
    while n is not None and n.type in ("parenthesized_expression", "cast_expression"):
        n = n.child_by_field_name("value") if n.type == "cast_expression" else next(iter(_named(n)), None)
    return n


def declarator_kind(d, raw, param=False) -> tuple[str, str]:
    """(name, kind) of a declarator: kind lists the derivations from the name outward — ``p`` pointer, ``a`` array,
    ``f`` function — so ``U8 *a[4]`` is ``ap`` (an array of pointers) and ``U8 (*pa)[4]`` ``pa``. A parameter declared
    as an array is a pointer (C11 6.7.6.3p7)."""
    kinds = []
    while d is not None and d.type not in ("identifier", "field_identifier", "type_identifier", "primitive_type"):
        if d.type == "pointer_declarator":
            kinds.append("p")
        elif d.type == "array_declarator":
            kinds.append("a")
        elif d.type == "function_declarator":
            kinds.append("f")
        if d.type == "parenthesized_declarator":
            d = next((c for c in d.named_children if c.type != "comment"), None)
        else:
            d = d.child_by_field_name("declarator")
    kind = "".join(reversed(kinds))
    if param and kind.startswith("a"):
        kind = "p" + kind[1:]
    return (_text(d, raw) if d is not None else ""), kind


def _specifier_base(typ, raw, path) -> str:
    """The base a declaration's type specifier names: ``struct:<key>`` for a struct or union (the key
    `_collect_struct` gives it), ``enum``, or the specifier's words (a primitive type, a typedef name)."""
    if typ is None:
        return ""
    if typ.type in ("struct_specifier", "union_specifier"):
        kind = "union" if typ.type == "union_specifier" else "struct"
        tag = typ.child_by_field_name("name")
        return "struct:" + (f"{kind} {_text(tag, raw)}" if tag is not None else f"{kind} @{path}:{typ.start_byte}")
    if typ.type == "enum_specifier":
        return "enum"
    return " ".join(_text(typ, raw).split())[:120]


class _Facts:
    """One function body (or one file's file-level items) read into records — see the module doc for the trees."""

    def __init__(self, raw: bytes, path: str = "", scope_names=None):
        self.raw = raw
        self.path = path
        self.scopes: list[set[str]] = [set()]
        self.params: list[list[str]] = []
        self.locals: dict[str, list[list]] = {}
        self.records: list[list] = []
        self.reassigned: set[str] = set()
        self.variadic = False
        self.block_names: set[str] = set()   # (review R64 round 3 C4) a block-scope extern or prototype here
        # (a macro expanded at solve time) the names the calling function declares: such a name in a macro's text may
        # be the caller's local or the global of that name — both are kept
        self.scope_names = scope_names
        self.ncalls = 0

    # ── names ─────────────────────────────────────────────────────────────────────────────────────
    def var(self, name):
        if any(name in s for s in self.scopes):
            return ["v", "L", name]          # declared in this text (a macro's own block too — review R64 C-2)
        if self.scope_names is not None:
            if name in self.scope_names:
                return ["any", [["v", "L", name], ["v", "N", name]]]
            return ["v", "N", name]
        return ["v", "N", name]

    def may_be_local(self, name) -> bool:
        """A name that is (or, in a macro's expansion, may be) a local or parameter here (review R64 W-3)."""
        v = self.var(name)
        return v[:2] == ["v", "L"] or (v[0] == "any" and any(x[:2] == ["v", "L"] for x in v[1]))

    def discard(self, tree):
        """A value read for its effects only (an expression statement, a condition, a comma's left): a name in it may
        be a macro whose expansion stores (``#define SP (g_p = &s)`` used as ``SP;``) — the solver evaluates it."""
        if _has_names(tree):
            self.records.append(["v", tree])
        return tree

    def opaque(self, node, cause):
        names = sorted({_text(x, self.raw) for x in _walk(node) if x.type == "identifier"})
        if names:
            self.records.append(["o", names, cause])
        self.records.append(["x", cause])

    # ── statements ────────────────────────────────────────────────────────────────────────────────
    def statement(self, n):
        t = n.type
        if t in ("compound_statement", "for_statement"):
            self.scopes.append(set())
            for c in _named(n):
                self.statement(c)
            self.scopes.pop()
        elif t == "declaration":
            self.declaration(n)
        elif t == "return_statement":
            vals = [self.value(c) for c in _named(n)]
            if vals:
                self.records.append(["r", vals[-1]])
        elif t == "ERROR":
            self.opaque(n, "parse_error")
        elif t in _PREPROC_SKIP or t in {"type_definition", "statement_identifier", "goto_statement"}:
            return
        elif t in _PREPROC_IF:
            # the condition is the preprocessor's, not code — only the arms are
            skip = {id(n.child_by_field_name("condition")), id(n.child_by_field_name("name"))}
            for c in _named(n):
                if id(c) not in skip:
                    self.statement(c)
        elif t in _EXPRESSIONS:
            self.discard(self.value(n))
        else:
            for c in _named(n):
                self.statement(c)

    def declaration(self, n, file_level=False):
        raw = self.raw
        typ = n.child_by_field_name("type")
        storage = {_text(c, raw) for c in n.named_children if c.type == "storage_class_specifier"}
        base = _specifier_base(typ, raw, self.path)
        for d in n.named_children:
            if d == typ or d.type in {"storage_class_specifier", "type_qualifier", "attribute_specifier",
                                      "ms_declspec_modifier", "comment"}:
                continue
            target = d.child_by_field_name("declarator") if d.type == "init_declarator" else d
            value = d.child_by_field_name("value") if d.type == "init_declarator" else None
            name, kind = declarator_kind(target, raw)
            if name and not file_level and (kind.startswith("f") or "extern" in storage):
                self.block_names.add(name)   # (review R64 round 3 C4) it hides a typedef of its name in the block
            if not name or kind.startswith("f"):
                continue   # a prototype
            if file_level or "extern" in storage:
                if file_level:
                    self.locals.setdefault(name, []).append([base, kind])
                lv = ["v", "N", name]
            else:
                self.locals.setdefault(name, []).append([base, kind])
                self.scopes[-1].add(name)
                if any(p[0] == name for p in self.params) or (self.scope_names is not None and name in self.scope_names):
                    # a local of a parameter's name (in the function, or a macro's block): one object here, not the
                    # parameter
                    self.reassigned.add(name)
                lv = ["v", "L", name]
            if value is not None:
                self.initializer(lv, value)

    def initializer(self, lv, value):
        """``T x = v`` / ``= { … }``: every item is stored into the object (field-insensitive) — with the declared type
        of the object, so an item that is the address of an array element still lands as a pointer."""
        if value.type == "initializer_list":
            for item in _named(value):
                v = item.child_by_field_name("value") if item.type == "initializer_pair" else item
                if v is not None:
                    self.initializer(["init", lv], v)
            return
        self.records.append(["s", lv, self.value(value)])

    # ── expressions ───────────────────────────────────────────────────────────────────────────────
    def value(self, n) -> list:
        """The value tree of ``n``; its stores and calls are recorded on the way."""
        raw = self.raw
        t = n.type
        if t in _CONSTANTS:
            return _NONE
        if t == "identifier":
            return ["l", self.var(_text(n, raw))]
        if t == "parenthesized_expression":
            inner = _named(n)
            if len(inner) == 1 and inner[0].type in _EXPRESSIONS:
                return self.value(inner[0])
            if len(inner) == 1 and inner[0].type == "compound_statement":
                # ``({ …; e; })`` (GNU): its statements run and it has the value of its last expression statement
                # (review R64 C-C — it was an unknown value, and a store through it was lost)
                self.scopes.append(set())
                stmts = _named(inner[0])
                for st in stmts[:-1]:
                    self.statement(st)
                last = stmts[-1] if stmts else None
                if last is not None and last.type == "expression_statement" and _named(last):
                    value = self.value(_named(last)[0])
                else:
                    if last is not None:
                        self.statement(last)
                    value = ["um", "statement_expression"]
                self.scopes.pop()
                return value
            for c in inner:
                self.statement(c)
            return ["um", "statement_expression"]
        if t == "extension_expression":
            inner = _named(n)
            return self.value(inner[0]) if inner else _NONE
        if t == "cast_expression":
            v = n.child_by_field_name("value")
            ty = n.child_by_field_name("type")
            inner = self.value(v) if v is not None else _NONE
            if ty is None:
                return inner
            spec = ty.child_by_field_name("type")
            return ["c", _specifier_base(spec, raw, self.path), _abstract_kind(ty.child_by_field_name("declarator")),
                    inner]
        if t == "pointer_expression":
            arg = n.child_by_field_name("argument")
            op = _text(n.child_by_field_name("operator"), raw) if n.child_by_field_name("operator") is not None else ""
            if op == "&":
                return ["a", self.address(arg)]
            return ["l", ["d", self.value(arg)]]
        if t in ("field_expression", "subscript_expression"):
            return ["l", self.lvalue(n)]
        if t == "binary_expression":
            op = _text(n.child_by_field_name("operator"), raw) if n.child_by_field_name("operator") is not None else ""
            lnode, rnode = n.child_by_field_name("left"), n.child_by_field_name("right")
            left = self.value(lnode)
            right = self.value(rnode)
            binary = _NONE if op in _NO_POINTER_OPS else ["+", op, [left, right]]
            inner = _named(lnode) if lnode is not None and lnode.type == "parenthesized_expression" else []
            if op in ("&", "*", "+", "-") and len(inner) == 1 and inner[0].type == "identifier" and rnode is not None:
                # ``(PT)&g_x``: a cast of ``&g_x`` when PT names a type — the tree reads a bitwise and (R64 — what
                # tree-sitter cannot know without the typedef names); the solver decides by the project's types
                unary = {"&": lambda: ["a", self.address(rnode)], "*": lambda: ["l", ["d", right]]}.get(
                    op, lambda: right)()
                return ["amb", _text(inner[0], raw), ["c", _text(inner[0], raw), "", unary], binary]
            return binary
        if t == "unary_expression":
            arg = n.child_by_field_name("argument")
            v = self.value(arg) if arg is not None else _NONE
            op = _text(n.child_by_field_name("operator"), raw) if n.child_by_field_name("operator") is not None else ""
            return _NONE if op == "!" else ["+", op, [v]]
        if t == "update_expression":
            arg = n.child_by_field_name("argument")
            v = self.value(arg)
            self.records.append(["s", self.lvalue(arg), _NONE])
            return v
        if t == "assignment_expression":
            left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
            op = _text(n.child_by_field_name("operator"), raw) if n.child_by_field_name("operator") is not None else "="
            r = self.value(right) if right is not None else _NONE
            target = self.lvalue(left)
            vals = r if op == "=" else ["+", op[:-1], [["l", target], r]]
            self.records.append(["s", target, vals])
            bare = _unwrap(left)
            if bare is not None and bare.type == "identifier" and op not in ("+=", "-="):
                self.reassigned.add(_text(bare, raw))
            return vals
        if t == "conditional_expression":
            cond = n.child_by_field_name("condition")
            c = self.value(cond) if cond is not None else _NONE
            cons, alt = n.child_by_field_name("consequence"), n.child_by_field_name("alternative")
            a = self.value(cons) if cons is not None else c       # GNU ``a ?: b``
            if cons is not None:
                self.discard(c)
            b = self.value(alt) if alt is not None else _NONE
            return ["?", [a, b]]
        if t == "comma_expression":
            # both operands: a list macro read as one expression (``{ PTRS }`` with ``#define PTRS &g_a, &g_b``) is a
            # list (review R64 round 3 C2) — keeping the left value of a true comma too is an over-approximation
            left = self.discard(self.value(n.child_by_field_name("left")))
            return ["?", [left, self.value(n.child_by_field_name("right"))]]
        if t == "call_expression":
            return self.call(n)
        if t == "initializer_list":
            items = []
            for item in _named(n):
                v = item.child_by_field_name("value") if item.type == "initializer_pair" else item
                if v is not None:
                    items.append(self.value(v))
            return ["?", items]
        if t == "compound_literal_expression":
            v = n.child_by_field_name("value")
            if v is not None:
                self.discard(self.value(v))
            return ["u", "compound_literal"]
        if t == "gnu_asm_expression":
            return self.asm(n)
        if t == "ERROR":
            self.opaque(n, "parse_error")
            return ["u", "parse_error"]
        for c in _named(n):          # an expression form not modeled: what it contains still runs
            if c.type in _EXPRESSIONS:
                self.discard(self.value(c))
            else:
                self.statement(c)
        # its value may designate any object of the program: a store through it is one the graph cannot follow
        return ["um", "unmodeled:" + t]

    def address(self, arg) -> list:
        """The lvalue tree ``&arg`` takes the address of."""
        bare = _unwrap(arg)
        if bare is not None and bare.type == "identifier":
            self.reassigned.add(_text(bare, self.raw))   # a parameter whose address is taken may change anywhere
        return self.lvalue(arg)

    def lvalue(self, n) -> list:
        """The lvalue tree of ``n``: a variable, ``["d", value]`` (what a value points to), ``["m", lvalue, field]``."""
        raw = self.raw
        if n is None:
            return ["u", "lvalue_missing"]
        t = n.type
        if t == "identifier":
            return self.var(_text(n, raw))
        if t == "parenthesized_expression":
            inner = _named(n)
            return self.lvalue(inner[0]) if len(inner) == 1 else ["u", "lvalue:" + t]
        if t == "pointer_expression":
            arg = n.child_by_field_name("argument")
            op = _text(n.child_by_field_name("operator"), raw) if n.child_by_field_name("operator") is not None else ""
            return ["d", self.value(arg)] if op == "*" else ["u", "lvalue:address"]
        if t == "field_expression":
            arg = n.child_by_field_name("argument")
            field = n.child_by_field_name("field")
            name = _text(field, raw) if field is not None else ""
            if any(c.type == "->" for c in n.children):
                return ["m", ["d", self.value(arg)], name]
            return ["m", self.lvalue(arg), name]
        if t == "subscript_expression":
            base, index = n.child_by_field_name("argument"), n.child_by_field_name("index")
            if base is not None and base.type == "number_literal" and index is not None:
                base, index = index, base    # ``3[p]``
            iv = self.value(index) if index is not None else _NONE
            return ["d", ["+", "+", [self.value(base), iv]]]
        if t == "cast_expression":
            return self.lvalue(n.child_by_field_name("value"))
        if t == "extension_expression":
            inner = _named(n)
            return self.lvalue(inner[0]) if inner else ["u", "lvalue_missing"]
        if t == "call_expression":
            return ["mc", self.call(n)[1]]     # ``SLOT(2) = &x``: what the macro's expansion designates
        if t == "conditional_expression":
            cond = n.child_by_field_name("condition")
            if cond is not None:
                self.discard(self.value(cond))
            return ["any", [self.lvalue(n.child_by_field_name("consequence")),
                            self.lvalue(n.child_by_field_name("alternative"))]]
        self.discard(self.value(n))
        return ["u", "lvalue:" + t]

    def call(self, n) -> list:
        raw = self.raw
        f, args = n.child_by_field_name("function"), n.child_by_field_name("arguments")
        arg_nodes = _named(args)
        if f is not None and f.type == "identifier":
            callee = _text(f, raw)
        elif f is not None and f.type == "parenthesized_expression" and len(_named(f)) == 1 \
                and _named(f)[0].type == "identifier" and not self.may_be_local(_text(_named(f)[0], raw)) \
                and _text(_named(f)[0], raw) not in self.block_names:
            # ``(T)(x)`` a cast if T is a type, else a call — never a cast on a parameter or local (a call through it)
            callee = "(" + _text(_named(f)[0], raw) + ")"
        else:
            if f is not None:
                self.discard(self.value(f))
            callee = "<indirect>"
        trees = [self.value(a) for a in arg_nodes]
        text = _text(n, raw)
        index = self.ncalls
        self.ncalls += 1
        self.records.append(["c", callee, trees, text if len(text) <= _CALL_TEXT_BUDGET else ""])
        return ["r", index]

    def asm(self, n) -> list:
        """Inline assembly: its outputs may be written with anything, what its inputs point to may be kept anywhere,
        and a name its text mentions may be read or written (the assumption: nothing else)."""
        raw = self.raw
        for c in _walk(n):
            if c.type == "gnu_asm_output_operand":
                v = c.child_by_field_name("value")
                if v is not None:
                    self.records.append(["s", self.lvalue(v), ["u", "inline_assembly"]])
            elif c.type == "gnu_asm_input_operand":
                v = c.child_by_field_name("value")
                if v is not None:
                    self.records.append(["e", self.value(v), "inline_assembly"])
        code = n.child_by_field_name("assembly_code")
        text = _text(code, raw) if code is not None else ""
        words = sorted(set(_IDENT_RE.findall(text)) | {w.lstrip("_") for w in _IDENT_RE.findall(text)} - {""})
        if words:
            self.records.append(["o", words, "inline_assembly"])
        self.records.append(["x", "inline_assembly"])
        return ["u", "inline_assembly"]

    def expansion(self, body) -> tuple[list, list | None]:
        """(value tree, lvalue tree or None) of a macro text parsed as a wrapper function's body: one expression is a
        value (and, read as an lvalue, objects); statements are run for their records."""
        stmts = [s for s in _named(body) if s.type != "expression_statement" or _named(s)]
        if len(stmts) == 1 and stmts[0].type == "expression_statement":
            e = _named(stmts[0])[0]
            v = self.value(e)
            lv = None
            if e.type in ("identifier", "parenthesized_expression", "pointer_expression", "field_expression",
                          "subscript_expression"):
                lv = self.lvalue(e)
            return v, lv
        for st in _named(body):
            self.statement(st)
        return _NONE, None


def _abstract_kind(d) -> str:
    """Derivations of an abstract declarator (a cast's or ``sizeof``'s type name): ``U8 *`` → ``p``."""
    kinds = []
    while d is not None:
        if d.type == "abstract_pointer_declarator":
            kinds.append("p")
        elif d.type == "abstract_array_declarator":
            kinds.append("a")
        elif d.type == "abstract_function_declarator":
            kinds.append("f")
        if d.type == "abstract_parenthesized_declarator":
            d = next((c for c in d.named_children if c.type != "comment"), None)
        else:
            d = d.child_by_field_name("declarator")
    return "".join(reversed(kinds))


def function_facts(fn, raw: bytes, path: str = "") -> dict[str, Any]:
    """The pointer-flow facts of one function definition (cached with the project context). A body too deep to read
    (review R64 W-1) is an unread region: every name in it may hold anything."""
    try:
        return _function_facts(fn, raw, path)
    except RecursionError:
        facts = _Facts(raw, path)
        facts.opaque(fn, "facts_depth")
        return {"params": [], "variadic": True, "locals": {}, "records": facts.records, "ret": ["", ""],
                "reassigned": [], "name": "", "unreadable": True}


def _function_facts(fn, raw: bytes, path: str = "") -> dict[str, Any]:
    facts = _Facts(raw, path)
    decl = fn.child_by_field_name("declarator")
    fname, fkind = declarator_kind(decl, raw) if decl is not None else ("", "")
    while decl is not None and decl.type != "function_declarator":
        decl = decl.child_by_field_name("declarator")
    plist = decl.child_by_field_name("parameters") if decl is not None else None
    params_known = True
    for p in _named(plist):
        if p.type == "variadic_parameter":
            facts.variadic = True
        elif p.type == "parameter_declaration":
            d = p.child_by_field_name("declarator")
            if d is None:
                continue   # ``(void)``, an unnamed parameter
            name, kind = declarator_kind(d, raw, param=True)
            facts.params.append([name, _specifier_base(p.child_by_field_name("type"), raw, path), kind])
            facts.scopes[0].add(name)
        else:
            params_known = False   # K&R, a parse error: the binding of arguments is not readable
    body = fn.child_by_field_name("body")
    if body is not None:
        facts.statement(body)
    if fn.has_error or not params_known:
        # (fail-closed) a tree with an error or a missing token may hold a flow the records do not: every name in the
        # function may be written with anything, and so may whatever it writes through
        facts.opaque(fn, "parse_error" if fn.has_error else "parameters_unreadable")
    # the return type: the specifier and the derivations after the function's own (``U8 *f(void)`` → ``p``)
    ret_kind = fkind[fkind.index("f") + 1:] if "f" in fkind else ""
    return {"params": facts.params, "params_unreadable": not params_known, "variadic": facts.variadic, "locals": facts.locals, "records": facts.records,
            "ret": [_specifier_base(fn.child_by_field_name("type"), raw, path), ret_kind],
            "reassigned": sorted(facts.reassigned & {p[0] for p in facts.params}), "name": fname}


def file_facts(root, raw: bytes, path: str = "") -> dict[str, Any]:
    """File-level pointer-flow facts: every file-scope declaration's kind and initializer, wherever it stands (an
    ``#if`` arm, a recovery container), typedef derivations, struct and union members, and the names in a parse-error
    region outside every function definition."""
    facts = _Facts(raw, path)
    types: dict[str, list] = {}
    local_types: set[str] = set()
    structs: dict[str, dict] = {}
    stack = [root]
    while stack:
        n = stack.pop()
        t = n.type
        if t == "function_definition":
            stack.extend(c for c in _walk(n) if c.type in ("struct_specifier", "union_specifier") and c is not n)
            for c in _walk(n):   # (review R64 round 3 C3) a typedef inside a function hides the file's in its block
                if c.type == "type_definition":
                    ctyp = c.child_by_field_name("type")
                    for d in c.named_children:
                        if d != ctyp and d.type not in ("type_qualifier", "comment"):
                            local_types.add(declarator_kind(d, raw)[0])
            continue
        if t == "declaration":
            try:
                facts.declaration(n, file_level=True)
            except RecursionError:   # (review R64 W-1) an initializer too deep to read: its names may hold anything
                facts.records.append(["o", sorted({_text(x, raw) for x in _walk(n) if x.type == "identifier"}),
                                      "facts_depth"])
        elif t == "type_definition":
            typ = n.child_by_field_name("type")
            base = _specifier_base(typ, raw, path)
            for d in n.named_children:
                if d == typ or d.type in ("type_qualifier", "comment"):
                    continue
                name, kind = declarator_kind(d, raw)
                if name:
                    types.setdefault(name, []).append([base, kind])
        elif t in ("struct_specifier", "union_specifier"):
            body = n.child_by_field_name("body")
            if body is not None:
                key = _specifier_base(n, raw, path)[len("struct:"):]
                members: dict[str, list] = {}
                for fd in _walk(body):
                    if fd.type != "field_declaration" or fd.parent is None:
                        continue
                    if fd.parent != body and fd.parent.type not in _PREPROC_IF | {"preproc_else"}:
                        continue   # a nested struct's own member
                    ftyp = fd.child_by_field_name("type")
                    fbase = _specifier_base(ftyp, raw, path)
                    declarators = fd.children_by_field_name("declarator")
                    if not declarators:   # an anonymous struct or union, a bit-field's padding: its type still counts
                        members.setdefault(ANONYMOUS_MEMBER, []).append([fbase, ""])
                    for d in declarators:
                        name, kind = declarator_kind(d, raw)
                        members.setdefault(name or ANONYMOUS_MEMBER, []).append([fbase, kind])
                structs.setdefault(key, {"members": {}})
                for name, forms in members.items():
                    structs[key]["members"].setdefault(name, []).extend(forms)
                if any(x.type == "ERROR" or x.is_missing for x in _walk(body)):
                    structs[key]["unread"] = True     # its member names are guesses
        elif t == "ERROR":
            names = sorted({_text(x, raw) for x in _walk_outside_functions(n) if x.type == "identifier"})
            if names:
                facts.records.append(["o", names, "file_parse_error"])
        elif t == "gnu_asm_expression":
            facts.asm(n)
            continue
        stack.extend(reversed(n.named_children))
    return {"objects": facts.locals, "records": facts.records, "types": types, "structs": structs,
            "local_types": sorted(local_types - {""})}


def _walk_outside_functions(node):
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "function_definition":
            continue
        yield n
        stack.extend(reversed(n.children))


def expression_tree(node, raw: bytes, is_local) -> tuple[list, list]:
    """(value tree, records) of one expression of a function body read where it stands — the source oracle asks this
    of a call's arguments. ``is_local(name)``: whether the name is a parameter or local there."""
    facts = _Facts(raw)

    def var(name):
        return ["v", "L" if is_local(name) else "N", name]
    facts.var = var   # type: ignore[method-assign]
    return facts.value(node), facts.records


# ── solution ────────────────────────────────────────────────────────────────────────────────────

class Analysis:
    """The solved points-to graph of one project context (see the module doc). The memo keeps the parses of macro
    texts it expanded (tree-sitter nodes): an analysis is not to be pickled or copied."""

    def __init__(self, context: dict[str, Any]):
        files = context.get("files") or {}
        self.functions: dict[str, list[dict]] = {}
        self.objects: dict[str, list[list]] = {}     # global name → [[base, kind], …]
        self.types: dict[str, list[list]] = {}       # typedef name → [[base, kind], …]
        self.structs: dict[str, list[dict]] = {}     # struct key → [member name → [[base, kind], …], …]
        self.unread_structs: set[str] = set()          # struct keys whose body does not parse
        self.local_typedefs: set[str] = set()          # names a typedef inside some function declares
        self.macros: dict[str, list[dict]] = {}
        self.enumerators: set[str] = set()
        self.prototypes: set[str] = set()
        file_records = []
        for rec in files.values():
            for name, defs in (rec.get("functions") or {}).items():
                for d in defs:
                    self.functions.setdefault(name, []).append(d.get("flow") or {})
            flow = rec.get("flow") or {}
            for name, decls in (flow.get("objects") or {}).items():
                self.objects.setdefault(name, []).extend(decls)
            for name, forms in (flow.get("types") or {}).items():
                self.types.setdefault(name, []).extend(forms)
            for key, entry in (flow.get("structs") or {}).items():
                self.structs.setdefault(key, []).append(entry.get("members") or {})
                if entry.get("unread"):
                    self.unread_structs.add(key)
            self.local_typedefs.update(flow.get("local_types") or ())
            file_records.append(flow.get("records") or [])
            for name, defs in (rec.get("macros") or {}).items():
                self.macros.setdefault(name, []).extend(defs)
            for entries in (rec.get("enums") or {}).values():
                for e in entries:
                    self.enumerators.update(m.get("name") for m in e.get("members") or () if m.get("name"))
            self.prototypes.update(rec.get("prototypes") or ())
        # (R62 strays) a name a function body #defines or #undefs: what it expands to there is not the walk's
        self.body_macros = {d.get("name") or "" for rec in files.values()
                            for d in (rec.get("stray_directives") or {}).get("directives") or ()
                            if d.get("op") in ("define", "undef")} - {""}
        # (review R64 round 3 W3) a body #define whose text may assign, take an address or call: a use of it does what
        #   the facts do not show — the analysis is refused there (a constant like a frame length is only unknown)
        self.effectful_body_macros = {d.get("name") or "" for rec in files.values()
                                      for d in (rec.get("stray_directives") or {}).get("directives") or ()
                                      if d.get("op") == "define" and _effectful_text(d.get("body"))} - {""}
        for cfg in ((context.get("build") or {}).get("configurations") or {}).values():
            for name, value in (cfg.get("defines") or {}).items():
                self.macros.setdefault(name, []).append({"body": str(value if value is not None else "1"),
                                                         "function_like": False})
        self.memo: dict[tuple, Any] = {}
        self.nodes: dict[Any, int] = {}
        self.pts: list[set[int]] = []
        self.succ: list[set[int]] = []
        self.loads: list[list[int]] = []
        self.stores: list[list[int]] = []
        self.names: list[Any] = []
        self.capable: list[bool] = []
        self.address_taken_functions: set[str] = set()
        self.writes: dict[str, list[tuple]] = {}      # function → [(node, parameter name | None, facts)]
        self.calls: dict[str, list[tuple]] = {}       # function → [(callee, [(direct parameter | None, node)], facts)]
        self.unknown_writes: dict[str, list[str]] = {}
        self.unknown_calls: dict[str, set[str]] = {}
        self.extra_reassigned: dict[str, set[str]] = {}   # parameters a macro expanded in the function assigns
        self.bound_callees: set[str] = set()            # functions some call the facts bind arguments to
        self.extra_locals: dict[str, dict[str, list]] = {}  # locals a macro expanded in the function declares
        self.stub_calls: dict[str, set[str]] = {}       # function → callees it passes something that may be a pointer
        self.model_unknown: dict[int, str] = {}         # ?U objects of lvalues the facts could not follow → cause
        self.store_pairs: list[tuple[int, int]] = []    # (destination, value) of every store
        self.byte_writes: list[tuple] = []              # (destination, access type | None) of non-pointer writes
        self.byte_copies: list[tuple] = []              # (destination, source | None) of library byte copies
        self.forced_capable: set[str] = set()           # integer objects a pointer is stored into (type punning)
        self.integer_reads: dict[int, set] = {}         # lvalue node → (union on path, through a pointer, access)
        self.referent_sources: set[int] = set()         # objects whose pointers integer reads carry
        self.refusals: list[str] = []
        self.macro_texts = {name: [d.get("body") or "" for d in defs] for name, defs in self.macros.items()}
        for name, defs in self.functions.items():
            for d in defs:
                self.add_function(name, d)
        for records in file_records:
            self.add_records("", records, ((), frozenset(), None))
        # a function whose address is taken may be called through it with anything; one no project code calls is an
        # entry point — called by code the context did not read (a library's callback by name) with anything
        # (review R64 C-1)
        for name in sorted(self.functions):
            if name in self.address_taken_functions:
                cause = "indirect_call:" + name
            elif name not in self.bound_callees:
                cause = "no_caller:" + name
            else:
                continue
            for d in self.functions.get(name, ()):
                for p in d.get("params") or ():
                    self.seed(self.obj(f"L:{name}:{p[0]}"), self.obj("?U:" + cause))
        self.settle()
        # (review R64 C-3) a value that may hold a pointer stored where the facts could not follow: the object it lands in
        # is not one the graph knows — no target set can be trusted
        model_ids = set(self.model_unknown)
        for dst, src in self.store_pairs:
            hit = self.pts[dst] & model_ids
            if hit and self.pts[src]:
                self.refusals.append("unknown_store:" + self.model_unknown[min(hit)])
                break
        self.refused = self.refusals[0] if self.refusals else ""
        self.summaries = self.summarize()

    # ── types ─────────────────────────────────────────────────────────────────────────────────────
    def norm(self, t, depth=0):
        """A type ``(base, kind)`` with every typedef replaced by what it names — ``kind`` lists the derivations from
        the object outward, ``base`` is ``struct:<key>``, ``enum`` or primitive words. None when not known."""
        if t is None or depth > _TYPE_DEPTH:
            return None
        base, kind = t
        words = [w for w in str(base or "").split() if w not in _QUALIFIER_WORDS]
        if not words:
            return None
        if words[0].startswith("struct:") or words[0] == "enum" or all(w in _ARITH_WORDS for w in words):
            return (" ".join(words), kind)
        if words[0] in ("struct", "union") and len(words) >= 2:
            return (f"struct:{words[0]} {words[1]}", kind)
        if len(words) == 1:
            if self.object_macro(words[0]) or words[0] in self.local_typedefs:
                # (review R64 round 3 C3) a name some unit #defines, or a typedef some function declares in its block:
                #   the type a declaration of it has depends on where it is
                return None
            forms = {tuple(f) for f in self.types.get(words[0]) or ()}
            if len(forms) == 1:
                fbase, fkind = forms.pop()
                return self.norm((fbase, kind + fkind), depth + 1)
        return None

    def var_type(self, obj: str):
        """The declared type of an object when every declaration agrees, else None."""
        if obj.startswith("L:"):
            _l, fn, name = obj.split(":", 2)
            forms = set()
            for d in self.functions.get(fn) or ():
                forms |= {(p[1], p[2]) for p in d.get("params") or () if p[0] == name}
                forms |= {tuple(x) for x in (d.get("locals") or {}).get(name) or ()}
            forms |= {tuple(x) for x in self.extra_locals.get(fn, {}).get(name) or ()}
        elif obj.startswith("G:"):
            forms = {tuple(x) for x in self.objects.get(obj[2:]) or ()}
        elif obj.startswith("R:"):
            forms = {tuple(d.get("ret") or ("", "")) for d in self.functions.get(obj[2:]) or ()}
        else:
            return None
        if len(forms) != 1:
            # ``extern U8 a[];`` and ``U8 a[4] = …;`` — the same derivations are the same type
            kinds = {k for _b, k in forms}
            bases = {self.norm((b, "")) for b, _k in forms}
            if len(kinds) == 1 and len(bases) == 1 and None not in bases:
                return self.norm((forms.pop()[0], kinds.pop()))
            return None
        return self.norm(forms.pop())

    def member(self, t, field):
        """The type of a struct's member ``field`` (every definition of the struct key agreeing), else None."""
        t = self.norm(t)
        if t is None or t[1] or not t[0].startswith("struct:"):
            return None
        forms = set()
        for members in self.structs.get(t[0][len("struct:"):]) or ():
            forms |= {tuple(f) for f in members.get(field) or ()}
        if len(forms) != 1:
            return None
        return self.norm(forms.pop())

    # ── graph ─────────────────────────────────────────────────────────────────────────────────────
    def node(self, key, capable=True) -> int:
        n = self.nodes.get(key)
        if n is None:
            n = self.nodes[key] = len(self.pts)
            self.pts.append(set())
            self.succ.append(set())
            self.loads.append([])
            self.stores.append([])
            self.names.append(key)
            self.capable.append(capable)
        return n

    def holds_pointer(self, t, depth=0) -> bool:
        """Whether an object of type ``t`` can hold a pointer value: a pointer, an array of what can, a struct or union
        some member of which can (unnamed members too — `ANONYMOUS_MEMBER`), a type the analysis cannot follow — not an
        integer, an array of integers, a struct of integers (a register union, a status word)."""
        t = self.norm(t)
        if t is None or depth > _TYPE_DEPTH:
            return True
        base, kind = t
        if kind.startswith("p"):
            return True
        if kind.startswith("f"):
            return False
        if kind.startswith("a"):
            return self.holds_pointer((base, kind[1:]), depth + 1)
        if base.startswith("struct:"):
            key = ("hp", base)
            if key not in self.memo:
                tag = base[len("struct:"):]
                defs = self.structs.get(tag)
                # a member the text does not show — a body that does not parse, a member name that is a macro
                #   (``U8 MEMBERS;`` with ``#define MEMBERS a; U8 *hp``), a type a macro names — may be a pointer
                self.memo[key] = not defs or tag in self.unread_structs \
                    or any(name in self.macros for members in defs for name in members) \
                    or any(f[0] in self.macros or self.holds_pointer(tuple(f), depth + 1)
                           for members in defs for forms in members.values() for f in forms)
            return self.memo[key]
        return not self.integer_type(t)

    def union_on_path(self, fn, tree) -> bool:
        """An lvalue with a union anywhere on its member path — through members (``g_u.s.w``) and array members
        (``g_u.h[i].b``), not through a pointer it holds: its storage is the other members' too."""
        for _ in range(64):
            if not tree:
                return False
            if tree[0] == "m":
                t = self.norm(self.lv_type(fn, tree[1]))
                if t is not None and t[1] == "" and t[0].startswith("struct:union"):
                    return True
                tree = tree[1]
            elif tree[0] == "d":
                v = tree[1]
                if v and v[0] == "+" and len(v) > 2 and v[2]:
                    v = v[2][0]
                if v and v[0] == "l":
                    t = self.norm(self.lv_type(fn, v[1]))
                    if t is not None and t[1][:1] == "a":
                        tree = v[1]       # an array member indexed: the same object
                        continue
                return False
            else:
                return False
        return True

    def access_type(self, fn, tree):
        """What a write through a pointer says is there: ``("member", S)`` for ``p->m`` (the struct ``*p``),
        ``("scalar", T)`` for ``*p`` / ``d[i]`` (the type written) — or None when the pointer's type is not known."""
        member = tree and tree[0] == "m"
        while tree and tree[0] == "m":
            tree = tree[1]
        if tree and tree[0] == "d":
            t = self.norm(self.lv_type(fn, tree))
            return (("member" if member else "scalar"), t) if t is not None else None
        return None

    def compatible(self, obj_type, access) -> bool:
        """Whether a write the pointer's type describes (`access_type`) stays what the object holds: a member access
        through ``S *`` into an object holding an ``S`` (itself, an element, a member); a scalar access of type ``T``
        into an object that is a ``T`` or an array of them — a character pointer reaches every byte, so a member of
        the same type is no proof (review R64 round 3 C1)."""
        if obj_type is None or access is None:
            return False
        kind, t = access
        if kind == "member":
            return self.contains_type(obj_type, t)
        while True:
            if obj_type == t:
                return True
            if not obj_type[1].startswith("a"):
                return False
            obj_type = (obj_type[0], obj_type[1][1:])

    def object_type(self, name):
        if name in self.forced_capable:
            return None   # (review R64 round 4 K-3) an integer object holding pointers: no byte write is its own type
        if name.startswith("?P:"):
            t = self.norm(self.var_type("L:" + name[3:]))
            return (t[0], t[1][1:]) if t is not None and t[1][:1] == "p" else None
        if name.startswith(("G:", "L:")):
            return self.norm(self.var_type(name))
        return None

    def contains_type(self, outer, inner, depth=0) -> bool:
        """Whether an object of type ``outer`` has a part (itself, an element, a member, recursively) of type ``inner``."""
        if outer is None or inner is None or depth > _TYPE_DEPTH:
            return False
        while True:
            if outer == inner:
                return True
            if not outer[1].startswith("a"):
                break
            outer = (outer[0], outer[1][1:])
        # (review R64 round 6 C1) not inside a union: a struct member access through one of its members is the other
        #   members' bytes too
        if outer[1] == "" and outer[0].startswith("struct:") and not outer[0].startswith("struct:union"):
            for members in self.structs.get(outer[0][len("struct:"):]) or ():
                for forms in members.values():
                    for f in forms:
                        if self.contains_type(self.norm(tuple(f)), inner, depth + 1):
                            return True
        return False

    def poisonable(self, o) -> bool:
        """An object whose pointers bytes written over it leave unknown: a program object or the harness's pointee —
        not a token (already unknown, or meaningful only where its run makes it so), a function, hardware."""
        name = self.names[o]
        return isinstance(name, str) and (name.startswith(("G:", "L:", "?P:"))) and name != HARDWARE \
            and self.capable[o]

    def settle(self):
        """Solve; then what depends on the solution, until nothing changes: an object of integer type a pointer is
        stored into holds it after all (type punning — a pool, a mailbox slot; review R64 round 3 W1), and bytes
        written over an object that may hold pointers (`byte_writes`, `byte_copies`) leave them unknown."""
        token = None
        for _ in range(64):
            self.solve()
            changed = False
            for dst, src in self.store_pairs:
                if not self.pts[src]:
                    continue
                for o in list(self.pts[dst]):
                    name = self.names[o]
                    if not self.capable[o] and isinstance(name, str) and name.startswith(("G:", "L:", "?P:")):
                        self.capable[o] = True
                        self.forced_capable.add(name)
                        changed = True
            # (review R64 round 5 B) an integer read that carries the pointers an object holds — through a pointer of
            #   another type (bytes), of a union member, of integer storage a pointer was put in — adds them to the
            #   integer referents
            ref = self.integer_referents()
            for node, kinds in self.integer_reads.items():
                for o in list(self.pts[node]):
                    if o in self.referent_sources or not self.capable[o]:
                        continue
                    name = self.names[o]
                    if not (isinstance(name, str) and name.startswith(("G:", "L:", "?P:"))):
                        continue
                    if any(union or name in self.forced_capable
                           or (through and not self.compatible(self.object_type(name), access))
                           for union, through, access in kinds):
                        self.referent_sources.add(o)
                        self.copy(ref, o)
                        changed = True
            # every object a pointer an integer made may designate holds an unknown pointer: a pointer stored through
            #   such a pointer is not followed, and whoever reads one from these objects sees unknown
            int_token = self.obj("?U:integer_to_pointer")
            # (review R64 round 6 C2) what is reachable from them too: a store two dereferences deep lands there
            for o in [self.nodes[x] for x in self.reach(self.objects_of(ref)) if x in self.nodes]:
                name = self.names[o]
                if self.capable[o] and int_token not in self.pts[o] and isinstance(name, str) \
                        and name.startswith(("G:", "L:", "?P:")):
                    self.pts[o].add(int_token)
                    changed = True
            if token is None:
                token = self.obj("?U:integer_write")
            for dst, access in self.byte_writes:
                for o in list(self.pts[dst]):
                    if self.poisonable(o) and token not in self.pts[o] \
                            and not self.compatible(self.object_type(self.names[o]), access):
                        self.pts[o].add(token)
                        changed = True
            for dst, src in self.byte_copies:
                sources = list(self.pts[src]) if src is not None else []
                for o in list(self.pts[dst]):
                    if not self.poisonable(o) or token in self.pts[o]:
                        continue
                    ot = self.object_type(self.names[o])
                    st = [self.object_type(self.names[s]) for s in sources]
                    if not sources or any(not self.capable[s] or not str(self.names[s]).startswith(("G:", "L:", "?P:"))
                                          for s in sources) or any(t is None or t != ot for t in st):
                        self.pts[o].add(token)
                        changed = True
            if not changed:
                return
        self.refusals.append("settle_unbounded")

    def integer_referents(self) -> int:
        """(review R64 round 5 B) The node of the objects pointers that became integers pointed to — what a pointer an
        integer made (converted, read from integer storage, written as bytes, read from hardware) may designate. Each
        holds an unknown pointer (`settle`)."""
        return self.node(("integer_referents",))

    def note_integer_read(self, fn, tree, node):
        """An integer read of an lvalue: whether it may carry pointer bytes is settled on the solution (`settle`)."""
        through = _through_pointer(tree)
        self.integer_reads.setdefault(node, set()).add(
            (self.union_on_path(fn, tree), through, self.access_type(fn, tree) if through else None))

    def as_pointer(self, fn, node, value_type, target_type, tree, ctx):
        """A value stored, passed or returned where a pointer is expected: an integer converted (implicitly — review
        R64 round 5 C) — a constant addresses hardware, any other may be anything; otherwise the value as it is."""
        vt = self.norm(value_type)
        target = self.norm(target_type)
        if node is not None and target is not None and self.integer_type(target) \
                and not (vt is not None and self.integer_type(vt)):
            self.copy(self.integer_referents(), node)   # (review R64 round 6 C3) a pointer passed or returned as one
        if vt is None or not self.integer_type(vt):
            return node
        tt = self.norm(target_type)
        if tt is None or tt[1][:1] != "p":
            return None   # an integer holds no pointer (the oracle's assumption)
        if self.constant_tree(fn, tree, ctx, False):
            return self.holding(self.obj(HARDWARE))
        return self.unknown("integer_to_pointer")

    def q_reread(self, objs) -> bool:
        """(review R64 round 5 E) A question's read from an object that cannot hold a pointer — the solve's P4u."""
        for o in objs:
            if o.startswith(("G:", "L:", "?P:")):
                n = self.nodes.get(o)
                if n is not None and (not self.capable[n] or o in self.forced_capable):
                    return True   # (review R64 round 6 C4) integer storage a pointer was put in, as the solve read it
        return False

    def constant_tree(self, fn, tree, ctx, question, depth=0) -> bool:
        """A value tree that is a constant — a literal, an enumerator, arithmetic of those, an object-like macro whose
        expansion is one (``#define SCI_BASE 0x0700U``): an integer constant converted to a pointer addresses hardware.
        ``question``: read-only (a question expands with `q_expand`)."""
        if depth > _TYPE_DEPTH or not tree:
            return False
        k = tree[0]
        if k == "n":
            return True
        if k == "c":
            return self.constant_tree(fn, tree[3], ctx, question, depth + 1)
        if k == "+":
            return all(self.constant_tree(fn, x, ctx, question, depth + 1) for x in tree[2])
        if k == "?":
            return all(self.constant_tree(fn, x, ctx, question, depth + 1) for x in tree[1])
        if k == "l" and tree[1][:2] == ["v", "N"]:
            name = tree[1][2]
            if self.object_macro(name) and not self.declared(name) and name not in self.body_macros:
                # (review R64 round 5 G1) a macro somewhere: its reading decides (an enumerator elsewhere is no proof)
                if question:
                    if name in ctx[3]:
                        return False
                    vt = self.q_expand(name, None, ctx[0])[0]
                else:
                    if name in ctx[0]:
                        return False
                    vt = self.expand(fn, name, None, ctx)[0]
                return self.constant_tree(fn, vt, ctx, question, depth + 1)
            if name in self.enumerators and not self.declared(name) and name not in self.macros \
                    and name not in self.body_macros:
                return True
        return False

    def body_macro_use(self, name) -> int:
        """A use of a name a function body #defines: what it designates the graph cannot follow; one whose text does
        something (assigns, takes an address, calls) refuses the analysis (review R64 round 3 W3)."""
        if name in self.effectful_body_macros:
            self.refusals.append("body_macro_effect:" + name)
        return self.unknown_place("body_macro:" + name)

    def integer_type(self, t) -> bool:
        """A known arithmetic or enumeration type (no derivation): it holds no pointer."""
        t = self.norm(t)
        return t is not None and t[1] == "" and (t[0] == "enum" or all(w in _ARITH_WORDS and w != "void"
                                                                       for w in t[0].split()))

    def obj(self, name: str) -> int:
        """The node of an object — its points-to set is the object's contents (nothing for an integer object or a
        function)."""
        n = self.nodes.get(name)
        if n is not None:
            return n
        if name.startswith("?P:"):
            t = self.norm(self.var_type("L:" + name[3:]))
            capable = t is None or t[1][:1] != "p" or self.holds_pointer((t[0], t[1][1:]))
        else:
            capable = not name.startswith("F:") and (name.startswith("?") or self.holds_pointer(self.var_type(name)))
        n = self.node(name, capable)
        if name.startswith("?P:"):
            if capable:
                self.pts[n].add(self.obj("?T:" + name.split(":", 2)[1]))
        elif name.startswith("?"):
            # an unknown or harness token holds pointers of its own kind — and nothing else: a pointer that may hold
            #   it is unknown already (?U), or stands for a stub's or the harness's own object (?S, ?T — the oracle
            #   wipes or ignores it by the run), so what is stored through it says nothing more; gathering it made every
            #   token a hub joining unrelated regions (review R64 round 4 I-1)
            self.pts[n].add(n)
            self.capable[n] = False
        elif name == HARDWARE:
            # (review R64 round 5 H) a pointer read from fixed-address memory may be any bytes put there
            self.pts[n].add(self.obj("?U:hardware"))
        return n

    def seed(self, node: int, obj: int):
        """``node ⊇ {obj}`` — nothing for an object that holds no pointer."""
        if self.capable[node]:
            self.pts[node].add(obj)

    def copy(self, dst, src):
        if dst is not None and src is not None and dst != src:
            self.succ[src].add(dst)

    def temp(self) -> int:
        return self.node(("t", len(self.pts)))

    def holding(self, *objs) -> int:
        key = ("h",) + tuple(sorted(objs))
        if key not in self.nodes:
            n = self.node(key)
            self.pts[n] |= set(objs)
        return self.nodes[key]

    def load(self, src):
        if src is None:
            return None
        key = ("l", src)
        if key in self.nodes:
            return self.nodes[key]
        n = self.node(key)
        self.loads[src].append(n)
        return n

    def union(self, nodes):
        nodes = list(dict.fromkeys(x for x in nodes if x is not None))
        if not nodes:
            return None
        if len(nodes) == 1:
            return nodes[0]
        key = ("U",) + tuple(sorted(nodes))
        if key not in self.nodes:
            n = self.node(key)
            for x in nodes:
                self.copy(n, x)
        return self.nodes[key]

    def unknown(self, cause: str) -> int:
        return self.holding(self.obj("?U:" + cause))

    def unknown_place(self, cause: str) -> int:
        """An lvalue the facts could not follow (review R64 C-3): what is stored there lands in an object the graph does
        not know — recorded, and the analysis is refused if a pointer may be stored there."""
        node = self.unknown("model:" + cause)
        self.model_unknown[self.obj("?U:model:" + cause)] = cause
        return node

    def escape(self, src, token):
        """Everything ``src`` reaches may be given the token's objects — one node per token gathers what reaches it
        (the same answer as one per site: every site stores the same token)."""
        if src is None:
            return
        key = ("esc", token)
        if key not in self.nodes:
            e = self.node(key)
            self.loads[e].append(e)
            self.stores[e].append(token)
        self.copy(self.nodes[key], src)

    # ── trees ─────────────────────────────────────────────────────────────────────────────────────
    def paren_cast(self, name, nargs) -> bool:
        """``(name)(x)`` is a cast (`paren_is_cast` — the write closure's rule too) — never a name a function body
        #defines (review R64 round 6 C6)."""
        if name in self.body_macros:
            return False
        return paren_is_cast(name, nargs, set(self.functions) | self.prototypes, self.objects, self.macro_texts,
                             self.types)

    def cast_reading(self, fn, name) -> str:
        """``(name)op x``: "cast" when ``name`` is a type of the project, "binary" when it is an object, a constant or
        a parameter or local of ``fn``, "" (both readings) when the analysis cannot tell (a macro, a name it never saw)."""
        if name in self.types or name in _ARITH_WORDS:
            return "cast"
        if name in self.macros or name in self.body_macros:
            return ""
        if name in self.objects or name in self.enumerators or name in self.functions:
            return "binary"
        if fn and any(name == p[0] for d in self.functions.get(fn) or () for p in d.get("params") or ()) \
                or fn and any(name in (d.get("locals") or {}) for d in self.functions.get(fn) or ()):
            return "binary"
        return ""

    def declared(self, name) -> bool:
        """A name some file declares as an object or a function (a macro of that name elsewhere does not hide it —
        review R64 C-5, C-G)."""
        return name in self.objects or name in self.functions or name in self.prototypes

    def alternatives(self, parts):
        """The readings of a macro's name that is the caller's local here (``["v", "L", x]`` / ``["v", "N", x]``): the
        global reading only when some file declares a global, a function or a macro of that name — an undeclared
        global would be one object every caller's local of that name pours into."""
        out = []
        for x in parts:
            if x[:2] == ["v", "N"] and any(y[:2] == ["v", "L"] and y[2] == x[2] for y in parts) \
                    and x[2] not in self.objects and x[2] not in self.functions and x[2] not in self.prototypes \
                    and x[2] not in self.macros and x[2] not in self.enumerators:
                continue
            out.append(x)
        return out

    def object_macro(self, name: str) -> bool:
        """A name some unit defines as an object-like macro (review R64 round 3 M1: object-like in one unit and
        function-like in another is read as both — `macro_parses` keeps only the object-like definitions here)."""
        return name in self.macros and any(not d.get("function_like") for d in self.macros[name])

    def object_of(self, fn: str, ns: str, name: str) -> str | None:
        if ns == "L":
            return f"L:{fn}:{name}"
        if name in self.functions or name in self.prototypes:
            return "F:" + name
        if name in self.enumerators:
            return None
        return "G:" + name

    def lv(self, fn, tree, ctx):
        """(node whose objects the lvalue designates, its type) — node None: none."""
        k = tree[0]
        if k == "v":
            ns, name = tree[1], tree[2]
            if ns == "N" and name in self.body_macros:
                return self.body_macro_use(name), None
            if ns == "N" and self.object_macro(name) and name not in ctx[0]:
                # (review R64 X-1) a macro's name inside its own expansion is the name, not the macro again
                _v, lvt = self.expand(fn, name, None, ctx)
                inner = self.lv(fn, lvt, _push(ctx, name)) if lvt is not None else (None, None)
                if self.declared(name):
                    # (C-5) the macro is the tree's: a unit that does not see it names the object
                    plain = self.lv(fn, tree, _push(ctx, name))
                    return self.union([inner[0], plain[0]]), (inner[1] if inner[1] == plain[1] else None)
                return inner
            if ns == "N" and name in self.macros and name not in self.functions and name not in self.objects \
                    and name not in ctx[0]:
                return None, None
            obj = self.object_of(fn, ns, name)
            if obj is None:
                return None, None
            if obj.startswith("F:"):
                self.address_taken_functions.add(obj[2:])
                return self.holding(self.obj(obj)), ("void", "f")
            return self.holding(self.obj(obj)), self.var_type(obj)
        if k == "d":
            n, t = self.rv(fn, tree[1], ctx)
            t = self.norm(t)
            return n, ((t[0], t[1][1:]) if t is not None and t[1][:1] in ("p", "a") else None)
        if k == "m":
            n, t = self.lv(fn, tree[1], ctx)
            return n, self.member(t, tree[2])
        if k == "any":
            parts = [self.lv(fn, x, ctx) for x in self.alternatives(tree[1])]
            types = {p[1] for p in parts}
            return self.union([p[0] for p in parts]), (types.pop() if len(types) == 1 else None)
        if k == "init":
            # an initializer item lands in the object; its type is a member's or element's — not followed
            n, _t = self.lv(fn, tree[1], ctx)
            return n, None
        if k == "mc":
            entry = ctx[3].get(tree[1]) if len(ctx) > 3 else None
            if entry is not None and len(entry) > 2 and entry[2] is not None:
                lt, callee = entry[2]
                return self.lv(fn, lt, _push(ctx, callee))
            return self.unknown_place("lvalue_call"), None
        if k == "MC":
            lt, callee = tree[1]
            return self.lv(fn, lt, _push(ctx, callee))
        return self.unknown_place(str(tree[1]) if len(tree) > 1 else "lvalue"), None

    def rv(self, fn, tree, ctx):
        """(node holding the objects the value may point to, its type)."""
        k = tree[0]
        if k == "n":
            return None, None
        if k == "l":
            inner = tree[1]
            name = inner[2] if inner[0] == "v" and inner[1] == "N" else ""
            if name and self.object_macro(name) and name not in self.body_macros and name not in ctx[0]:
                vt, _lt = self.expand(fn, name, None, ctx)
                val = self.rv(fn, vt, _push(ctx, name))
                if self.declared(name):   # (C-5) a unit that does not see the macro reads the object
                    plain = self.rv(fn, tree, _push(ctx, name))
                    return self.union([val[0], plain[0]]), (val[1] if val[1] == plain[1] else None)
                return val
            n, t = self.lv(fn, tree[1], ctx)
            t = self.norm(t)
            if t is not None and t[1].startswith("a"):
                return n, (t[0], "p" + t[1][1:])        # an array is the address of its first element
            if t is not None and t[1].startswith("f"):
                return n, (t[0], "p" + t[1])            # a function designator: its address
            if t is not None and self.integer_type(t):
                if n is not None:
                    self.note_integer_read(fn, tree[1], n)
                return None, t                          # an integer value: no pointer
            if t is not None:
                return self.load(n), t
            return self.union([n, self.load(n)]), None   # array or not: both readings
        if k == "a":
            n, t = self.lv(fn, tree[1], ctx)
            t = self.norm(t)
            return n, ((t[0], "p" + t[1]) if t is not None else None)
        if k == "c":
            n, ot = self.rv(fn, tree[3], ctx)
            t = self.norm((tree[1], tree[2]))
            if t is not None and self.integer_type(t):
                if n is not None and not (ot is not None and self.integer_type(ot)):
                    self.copy(self.integer_referents(), n)   # what an integer converted back may designate
                return None, t        # a pointer as an integer: an integer holds no pointer
            if tree[2].startswith("p") or t is None or t[1][:1] == "p":
                if n is None or ot is None or self.integer_type(ot):
                    # an integer as a pointer (or a value or a type not known): a constant addresses hardware (the
                    #   oracle's assumption); any other may be a pointer converted to an integer and back, or a pointer's
                    #   bytes — unknown (review R64 round 3 W2, round 4 K-1/K-2, round 5 T)
                    if self.constant_tree(fn, tree[3], ctx, False):
                        return self.holding(self.obj(HARDWARE)), t
                    unknown = self.unknown("integer_to_pointer")
                    return (self.union([n, unknown]) if n is not None else unknown), t
            return n, t
        if k == "+":
            parts = [self.rv(fn, x, ctx) for x in tree[2]]
            pointers = [p for p in parts if p[1] is not None and p[1][1][:1] == "p"]
            if tree[1] == "-" and len(pointers) == 2:
                return None, None                       # pointer difference: a count
            t = pointers[0][1] if len(pointers) == 1 else None
            return self.union([p[0] for p in parts if not self.integer_type(p[1])]), t
        if k == "?":
            parts = [self.rv(fn, x, ctx) for x in tree[1]]
            types = {p[1] for p in parts if p[0] is not None}
            return self.union([p[0] for p in parts]), (types.pop() if len(types) == 1 else None)
        if k == "r":
            entry = ctx[3].get(tree[1]) if len(ctx) > 3 else None
            return entry[:2] if entry is not None else (None, None)
        if k == "K":
            return tree[1], (tree[2] if len(tree) > 2 else None)
        if k == "I":
            return None, (tree[1] if len(tree) > 1 and tree[1] else ("int", ""))
        if k == "amb":
            reading = self.cast_reading(fn, tree[1])
            return self.rv(fn, tree[2] if reading == "cast" else tree[3] if reading == "binary" else ["?", tree[2:4]],
                           ctx)
        if k == "P":
            return self.holding(self.obj(f"?P:{tree[1]}:{tree[2]}")), self.var_type(f"L:{tree[1]}:{tree[2]}")
        if k == "um":
            return self.unknown_place(str(tree[1])), None
        return self.unknown(str(tree[1]) if len(tree) > 1 else "value"), None

    # ── records ───────────────────────────────────────────────────────────────────────────────────
    def add_function(self, name: str, facts: dict):
        if not facts:
            self.unknown_writes.setdefault(name, []).append("facts_missing")
            return
        params = facts.get("params") or []
        for p in params:
            self.seed(self.obj(f"L:{name}:{p[0]}"), self.obj(f"?P:{name}:{p[0]}"))
        scope_names = frozenset({p[0] for p in params} | set(facts.get("locals") or {}))
        self.add_records(name, facts.get("records") or [], ((), scope_names, facts))

    def integer_tree(self, fn, tree) -> bool:
        """A value tree of integer type by its static type (a constant, an integer object, arithmetic of those) — it
        cannot be the pointer operand."""
        if not tree or tree[0] == "n":
            return True
        return self.integer_type(self.rv_type(fn, tree))

    def passed_param(self, fn, facts, tree) -> str | None:
        """The parameter of ``fn`` whose pointer value a value tree is — ``p``, ``p + n``, a cast of it, ``&p->m``, an
        array member ``p->buf`` (the objects ``p`` points to, unchanged) — or None."""
        if not facts:
            return None
        params = {p[0] for p in facts.get("params") or ()}
        for _ in range(_TYPE_DEPTH):
            if not tree:
                return None
            if tree[0] == "c":
                tree = tree[3]
            elif tree[0] == "+":
                live = [x for x in tree[2] if not self.integer_tree(fn, x)]
                if len(live) != 1 or tree[1] not in ("+", "-"):
                    return None
                tree = live[0]
            elif tree[0] == "a":
                return self.lvalue_param(fn, facts, tree[1])
            elif tree[0] == "l":
                inner = tree[1]
                if inner and inner[0] == "any":
                    alts = self.alternatives(inner[1])
                    inner = alts[0] if len(alts) == 1 else inner
                if inner[0] == "v":
                    if inner[1] != "L" or inner[2] not in params:
                        return None
                    # (review R64 round 3 W2) only a parameter declared a pointer binds the call's argument objects —
                    #   an integer (or a type not known) cast back to a pointer addresses what the graph says instead
                    t = self.norm(self.var_type(f"L:{fn}:{inner[2]}"))
                    return inner[2] if t is not None and t[1][:1] in ("p", "a") else None
                n_t = self.lv_type(fn, inner)
                if n_t is not None and n_t[1].startswith("a"):
                    return self.lvalue_param(fn, facts, inner)   # an array inside what the parameter points to
                return None
            else:
                return None
        return None

    def lvalue_param(self, fn, facts, tree) -> str | None:
        """The parameter an lvalue designates through directly (``*p``, ``p[i]``, ``p->m``, ``p->a[i]``) — or None."""
        while tree and tree[0] == "m":
            tree = tree[1]
        if not tree or tree[0] != "d":
            return None
        return self.passed_param(fn, facts, tree[1])

    def lv_type(self, fn, tree):
        """The static type of an lvalue tree (no node is built), or None."""
        k = tree[0] if tree else ""
        if k == "v":
            obj = self.object_of(fn, tree[1], tree[2])
            return self.var_type(obj) if obj is not None and not obj.startswith("F:") else None
        if k == "d":
            t = self.norm(self.rv_type(fn, tree[1]))
            return (t[0], t[1][1:]) if t is not None and t[1][:1] in ("p", "a") else None
        if k == "m":
            return self.member(self.lv_type(fn, tree[1]), tree[2])
        return None

    def rv_type(self, fn, tree):
        k = tree[0] if tree else ""
        if k == "l":
            t = self.norm(self.lv_type(fn, tree[1]))
            if t is not None and t[1][:1] in ("a", "f"):
                return (t[0], "p" + t[1][1:]) if t[1].startswith("a") else (t[0], "p" + t[1])
            return t
        if k == "a":
            t = self.norm(self.lv_type(fn, tree[1]))
            return (t[0], "p" + t[1]) if t is not None else None
        if k == "c":
            return self.norm((tree[1], tree[2]))
        if k == "amb":
            reading = self.cast_reading(fn, tree[1])
            return self.rv_type(fn, tree[2]) if reading == "cast" else self.rv_type(fn, tree[3]) \
                if reading == "binary" else None
        if k == "n":
            return ("int", "")
        if k == "I":
            return tree[1] if len(tree) > 1 and tree[1] else ("int", "")
        if k == "K":
            return tree[2] if len(tree) > 2 else None
        if k == "+":
            types = [self.norm(self.rv_type(fn, x)) for x in tree[2]]
            pointers = [t for t in types if t is not None and t[1][:1] == "p"]
            if len(pointers) == 1 and tree[1] in ("+", "-"):
                return pointers[0]
            if types and all(t is not None and self.integer_type(t) for t in types):
                return ("int", "")
        return None

    def add_records(self, fn: str, records, ctx):
        """Read one list of records of ``fn`` (``""``: file level); ``ctx`` = (macro stack, the function's declared
        names, its facts). Returns the call value of each call record (index → (node, type))."""
        rmap: dict[int, tuple] = {}
        full = (ctx[0], ctx[1], ctx[2], rmap, [r[1] for r in records if r[0] == "c"])
        facts = ctx[2]
        index = 0
        for r in records:
            kind = r[0]
            if kind == "s":
                src, st = self.rv(fn, r[2], full)
                dst, dt = self.lv(fn, r[1], full)
                if dt is not None and self.integer_type(dt):
                    if src is not None and not (st is not None and self.integer_type(st)):
                        # (review R64 round 6 C3) a pointer (or a value not known) stored as an integer: converted back
                        #   it may designate what it did
                        self.copy(self.integer_referents(), src)
                    src = None   # an integer lvalue holds no pointer (the oracle's assumption)
                elif st is not None and self.integer_type(st):
                    # an integer value holds no pointer (the assumption) — stored as a pointer (no cast: C constraint
                    #   violation compilers accept) it is converted like a cast (review R64 round 5 B, C); an initializer
                    #   item's own type is a member's or element's the facts do not follow: of an object that may hold
                    #   pointers, it may be one (round 6 W1)
                    target = dt
                    if dt is None and r[1] and r[1][0] == "init":
                        whole = r[1]
                        while whole and whole[0] == "init":
                            whole = whole[1]
                        if self.holds_pointer(self.lv_type(fn, whole)):
                            target = ("void", "p")
                    src = self.as_pointer(fn, src, st, target, r[2], full)
                if dst is None:
                    if src is None:
                        continue
                    # (review R64 round 3 X7) a value that may hold a pointer stored where the trees cannot say
                    dst = self.unknown_place("lvalue_unresolved")
                # bytes are not values: what is not a pointer written over an object that may hold pointers leaves them
                #   unknown — through a pointer whose type is not the object's (a byte copy, a cast overlay) or through a
                #   union member anywhere on the path, whatever path the bytes took (review R64 C-8, round 2 C-A/C-B,
                #   round 3 C1/S2/S3/U1/U2); which objects, the solution says (`settle`)
                if dt is None or not self.holds_pointer(dt):
                    if self.union_on_path(fn, r[1]):
                        self.byte_writes.append((dst, None))
                    elif _through_pointer(r[1]):
                        self.byte_writes.append((dst, self.access_type(fn, r[1])))
                root = _lvalue_root(r[1])
                if root and root[1] == "N" and root[2] in self.body_macros:
                    # a store into what a body #define names: an object the graph cannot follow (review R64 C-3)
                    dst = self.union([dst, self.unknown_place("body_macro:" + root[2])])
                if src is not None:
                    self.stores[dst].append(src)
                    self.store_pairs.append((dst, src))
                if _through_pointer(r[1]) or self.macro_lvalue(r[1]):
                    self.writes.setdefault(fn, []).append((dst, self.written_param(fn, facts, r[1]), facts))
            elif kind == "c":
                rmap[index] = self.add_call(fn, r[1], r[2], r[3], full)
                index += 1
            elif kind == "r":
                src, rt = self.rv(fn, r[1], full)
                if fn:
                    self.copy(self.obj("R:" + fn), self.as_pointer(fn, src, rt, self.var_type("R:" + fn), r[1], full))
            elif kind == "e":
                n, _t = self.rv(fn, r[1], full)
                self.escape(n, self.unknown(r[2]))
            elif kind == "v":
                self.rv(fn, r[1], full)     # for what a macro in it stores
            elif kind == "o":
                self.opaque_names(fn, r[1], r[2], ctx[1], set())
            elif kind == "x":
                if fn:
                    self.unknown_writes.setdefault(fn, []).append(r[1])
        return rmap

    def macro_lvalue(self, tree) -> bool:
        """An lvalue rooted at a macro name: what it expands to may go through a pointer."""
        while tree and tree[0] == "m":
            tree = tree[1]
        return bool(tree) and tree[0] == "v" and tree[1] == "N" and (tree[2] in self.macros or
                                                                     tree[2] in self.body_macros)

    def written_param(self, fn, facts, tree) -> str | None:
        return self.lvalue_param(fn, facts, tree) if _through_pointer(tree) else None

    def opaque_names(self, fn, names, cause, scope_names, seen):
        """Every object a region the facts could not read names may hold anything, and every function it names may
        be called with anything (through a macro it names too)."""
        token = self.obj("?U:" + cause + (":" + fn if fn else ""))
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            if name in self.macros:
                for d in self.macros[name]:
                    self.opaque_names(fn, _IDENT_RE.findall(d.get("body") or ""), cause, scope_names, seen)
            for obj in ([f"L:{fn}:{name}"] if fn and name in scope_names else []) + ["G:" + name]:
                self.seed(self.obj(obj), token)
                # what the object points to may be written there too (``*g_pp = &x`` in an unread region)
                self.escape(self.holding(self.obj(obj)), self.holding(token))
            if name in self.functions:
                self.address_taken_functions.add(name)

    def macro_closure_texts(self, name) -> list[str]:
        """The definitions of a macro and of every macro they mention, transitively — what its expansion may contain."""
        out, seen, stack = [], set(), [name]
        while stack:
            m = stack.pop()
            if m in seen or m not in self.macro_texts:
                continue
            seen.add(m)
            for t in self.macro_texts[m]:
                out.append(t)
                stack.extend(w for w in _IDENT_RE.findall(t) if w in self.macro_texts)
        return out

    def list_macro(self, name, depth=0) -> bool:
        """A macro some definition of which is a list at its top level (``#define TX_BUF g_tx, 4U``,
        ``#define ARGS(x) x, 4U``) or names one (``#define WRAP(x) ARGS(x)``): written as one argument it is several
        (review R64 C-F)."""
        if depth > _MACRO_DEPTH:
            return True
        for t in self.macro_texts.get(name, ()):
            parts = _call_arguments("(" + t + ")")
            if parts is None or len(parts) > 1:
                return True
            head = re.match(r"\s*([A-Za-z_]\w*)\s*(?:\(|$)", t)
            if head and head.group(1) != name and head.group(1) in self.macro_texts                     and self.list_macro(head.group(1), depth + 1):
                return True
        return False

    def comma_macro(self, tree, records=None) -> str:
        """The name of an object-like macro in a tree whose definition is a list (``#define TX_BUF g_tx, 4U``) — used
        in an argument it is several arguments (review R64 C-F) — or ""."""
        if not isinstance(tree, list) or not tree:
            return ""
        if tree[0] == "v" and tree[1] == "N" and self.object_macro(tree[2]) and self.list_macro(tree[2]):
            return tree[2]
        if tree[0] == "r" and records is not None and isinstance(tree[1], int) and tree[1] < len(records):
            # an argument that is a function-like macro's call (``Keep(ARGS(g_tx))``) — ``records``: the callee of
            # each call by ordinal
            callee = records[tree[1]]
            if callee in self.macros and self.list_macro(callee):
                return callee
        for x in tree:
            found = self.comma_macro(x, records) if isinstance(x, list) else ""
            if found:
                return found
        return ""

    def add_call(self, fn, callee, trees, text, ctx):
        """The value of a call: (node, type, (lvalue tree of a macro's expansion, macro) or None)."""
        stack, facts = ctx[0], ctx[2]
        callees = ctx[4] if len(ctx) > 4 else None
        listed = next((m for m in (self.comma_macro(t, callees) for t in trees) if m), "")
        if listed:
            self.refusals.append("macro_argument_list:" + listed)   # which argument binds to which parameter: unknown
        args = [self.rv(fn, t, ctx) for t in trees]
        nodes = [a[0] for a in args]
        if callee.startswith("(") and callee.endswith(")"):
            name = callee[1:-1]
            if self.paren_cast(name, len(trees)):
                # ``(T)(x)``: a cast — with what a cast does (review R64 round 4 K-1)
                return self.rv(fn, ["c", name, "", trees[0]], ctx) if trees else (None, None)
            callee = name if name in self.functions or name in self.macros or name in self.body_macros \
                else "<indirect>"
        if callee in self.body_macros:
            # a name a function body #defines, called: what it calls is not known — no function's arguments are
            # (review R64 C-1)
            self.refusals.append("body_macro_call:" + callee)
            return self.opaque_call(fn, nodes, "body_macro:" + callee), None
        values = []
        lvalue = None
        # (review R64 C-1) an object-like alias called (``#define KEEP keep_impl`` … ``KEEP(&g_x)``) expands too
        macro = callee in self.macros and callee not in stack
        if macro:
            if not text or len(stack) > _MACRO_DEPTH:
                # the call cannot be expanded: what its text could call may get anything — and a body that pastes
                # names or assigns may reach what no name in it says (review R64 C-E): refused
                texts = self.macro_closure_texts(callee)
                if any("##" in t or _ASSIGNS.search(t) for t in texts):
                    self.refusals.append("macro_call_unexpanded:" + callee)
                self.opaque_names(fn, [w for t in texts for w in _IDENT_RE.findall(t)],
                                  "macro_call:" + callee, ctx[1], set())
                return self.opaque_call(fn, nodes, "macro_call:" + callee), None
            vt, lt = self.expand(fn, callee, text, ctx)
            values.append(self.rv(fn, vt, _push(ctx, callee)))
            lvalue = (lt, callee) if lt is not None else None
            if callee in self.objects:
                # (review R64 W-4) a unit that does not see the macro calls through the object of that name
                values.append((self.opaque_call(fn, nodes, "call:" + callee), None))
        defs = self.functions.get(callee)
        if defs:
            self.bound_callees.add(callee)
            if any(n is not None for n in nodes):
                # (review R64 I-4) a stub of the callee may write through what it is passed
                self.stub_calls.setdefault(fn, set()).add(callee)
            self.calls.setdefault(fn, []).append(
                (callee, [(self.passed_param(fn, facts, t), n) for t, n in zip(trees, nodes, strict=True)], facts))
            for d in defs:
                params = d.get("params") or []
                for i, n in enumerate(nodes):
                    if i < len(params):
                        n = self.as_pointer(fn, n, args[i][1], (params[i][1], params[i][2]), trees[i], ctx)
                        self.copy(self.obj(f"L:{callee}:{params[i][0]}"), n)
                    else:
                        self.escape(n, self.unknown("extra_argument:" + callee))
            # a stub of the callee may hand back, or put through a pointer argument, a pointer of its own
            token = self.holding(self.obj("?S:" + callee))
            for n in nodes:
                self.escape(n, token)
            key = ("cv", callee)
            if key not in self.nodes:
                cv = self.node(key)
                self.pts[cv].add(self.obj("?S:" + callee))
                self.copy(cv, self.obj("R:" + callee))
            values.append((self.nodes[key], self.var_type("R:" + callee)))
        elif not macro:
            if callee in _LIBRARY:
                ret, contents = _LIBRARY[callee]
                loaded = self.load(nodes[1]) if contents and len(nodes) >= 2 else None
                if nodes and nodes[0] is not None and loaded is not None:
                    self.stores[nodes[0]].append(loaded)
                    self.store_pairs.append((nodes[0], loaded))   # (round 4 K-2) a pointer copied into an integer
                if callee in _BYTE_COPIES and nodes and nodes[0] is not None:
                    # (review R64 round 3 C1) bytes copied from what holds no pointer (``U8 saved[]``) over what may
                    self.byte_copies.append((nodes[0], nodes[1] if len(nodes) >= 2 else None))
                self.unknown_calls.setdefault(fn, set()).add("call:" + callee)
                return args[ret] if ret is not None and ret < len(args) else (None, None)
            return self.opaque_call(fn, nodes, "call:" + callee), None
        types = {v[1] for v in values}
        return self.union([v[0] for v in values]), (types.pop() if len(types) == 1 else None), lvalue

    def opaque_call(self, fn, nodes, cause):
        token = self.unknown(cause)
        for n in nodes:
            self.escape(n, token)
        self.unknown_calls.setdefault(fn, set()).add(cause)
        return token

    def expand(self, fn, name, call_text, ctx):
        """(value tree, lvalue tree) of a macro's expansion in ``fn`` — every definition — its records added to
        ``fn``'s once; trees whose call values are nodes (``["K", node]``). ``call_text``: the invocation of a
        function-like macro (None for an object-like one)."""
        key = ("x", fn, name, call_text)
        if key in self.memo:
            return self.memo[key]
        stack, scope_names, facts = ctx[0], ctx[1], ctx[2]
        recursion = ["u", "macro_recursion:" + name]
        if name in stack or len(stack) > _MACRO_DEPTH:
            return recursion, recursion
        self.memo[key] = (recursion, recursion)
        values, lvalues = [], []
        for body, raw, root in self.macro_parses(name, call_text):
            if root is None:
                out = self.opaque_macro(fn, name, body, call_text, scope_names)
                self.memo[key] = out
                return out
            sub = _Facts(raw, scope_names=set(scope_names))
            v, lvt = sub.expansion(root)
            self.extra_reassigned.setdefault(fn, set()).update(sub.reassigned)
            for local, decls in sub.locals.items():   # (a local the macro declares keeps its declared type)
                self.extra_locals.setdefault(fn, {}).setdefault(local, []).extend(decls)
            sub_map = self.add_records(fn, sub.records, (tuple(stack) + (name,), scope_names, facts))
            values.append(_rekey(v, sub_map))
            if lvt is not None:
                lvalues.append(_rekey(lvt, sub_map))
        if not values:
            out = (_NONE, None)
        else:
            out = (values[0] if len(values) == 1 else ["?", values],
                   None if not lvalues else lvalues[0] if len(lvalues) == 1 else ["any", lvalues])
        self.memo[key] = out
        return out

    def macro_parses(self, name, call_text):
        """(text, raw, the parsed body — None when the text does not parse) per definition: an object-like macro read
        as a name, a function-like one called (``call_text``) with its arguments in, an object-like one called — an
        alias of what it names (``#define KEEP keep_impl``)."""
        from generators.c_project_context import shared_parser
        key = ("p", name, call_text)
        if key in self.memo:
            return self.memo[key]
        out = []
        for d in self.macros.get(name) or ():
            body = d.get("body") or ""
            if call_text is None:
                if d.get("function_like"):
                    continue
                body = _paste(body)
            elif d.get("function_like"):
                args = _call_arguments(call_text)
                body = _substitute(body, d.get("params") or [], args) if args is not None else None
                if body is None:
                    out.append((d.get("body") or "", b"", None))
                    continue
            else:
                head = re.match(r"\s*" + re.escape(name) + r"\b", call_text)
                if head is None:
                    out.append((body, b"", None))
                    continue
                body = "(" + _paste(body) + ")" + call_text[head.end():]
            raw = ("void __pf_m(void) {\n" + body + "\n;}").encode("utf-8")
            root = shared_parser().parse(raw).root_node
            fdef = next((c for c in root.named_children if c.type == "function_definition"), None)
            out.append((body, raw, None if root.has_error or fdef is None else fdef.child_by_field_name("body")))
        self.memo[key] = out
        return out

    def opaque_macro(self, fn, name, body, call_text, scope_names=frozenset()):
        cause = "opaque_macro:" + name
        names = _IDENT_RE.findall(body) + (_IDENT_RE.findall(call_text) if call_text else [])
        self.opaque_names(fn, names, cause, scope_names, set())
        if fn:
            self.unknown_writes.setdefault(fn, []).append(cause)
        return ["u", cause], ["u", cause]

    # ── solving ───────────────────────────────────────────────────────────────────────────────────
    def solve(self):
        """Inclusion constraints to their least solution (difference propagation): ``succ`` copy edges, ``loads``
        (``a ⊇ *n``) and ``stores`` (``*n ⊇ b``) wired to each object as it reaches ``n``; a node passes on only what
        it has not passed on yet."""
        from collections import deque
        pts, succ, loads, stores = self.pts, self.succ, self.loads, self.stores
        # (review R64 round 4 K-3) what is read from an object that cannot hold a pointer — an integer object, bytes a
        #   pointer was copied into — read as anything but an integer, may be such a pointer: unknown
        reread = self.unknown("integer_reinterpreted")
        names = self.names
        delta = [set(p) for p in pts]
        work = deque(n for n in range(len(pts)) if pts[n])
        queued = set(work)

        capable = self.capable

        def push(objs, m):
            if not capable[m]:
                return
            new = objs - pts[m]
            if new:
                pts[m] |= new
                delta[m] |= new
                if m not in queued:
                    queued.add(m)
                    work.append(m)

        while work:
            n = work.popleft()
            queued.discard(n)
            d = delta[n]
            if not d:
                continue
            delta[n] = set()
            for o in d:
                for a in loads[n]:
                    if not capable[o] and a not in succ[reread] and not str(names[o]).startswith(("F:", "?")):
                        succ[reread].add(a)
                        push(pts[reread], a)
                    if a not in succ[o]:
                        succ[o].add(a)
                        push(pts[o], a)
                for b in stores[n]:
                    if o not in succ[b]:
                        succ[b].add(o)
                        push(pts[b], o)
            for m in list(succ[n]):
                push(d, m)

    # ── summaries ─────────────────────────────────────────────────────────────────────────────────
    def objects_of(self, node) -> frozenset:
        if node is None:
            return frozenset()
        return frozenset(self.names[o] for o in self.pts[node])

    def summarize(self) -> dict[str, dict]:
        """Per function: the objects a write through a pointer anywhere in what it reaches may land on, and the
        parameters written through directly — a fixpoint over the call graph."""
        abs_: dict[str, set] = {}
        direct: dict[str, set] = {}
        for fn in self.functions:
            a, d = set(), set()
            for node, param, facts in self.writes.get(fn, ()):
                index = self.param_position(fn, facts, param)
                if index is not None:
                    d.add(index)
                else:
                    a |= self.objects_of(node)
            for cause in self.unknown_writes.get(fn, ()):
                a.add("?U:" + cause)
            for cause in self.unknown_calls.get(fn, ()):
                a.add("?U:" + cause)
            for callee in self.stub_calls.get(fn, ()):
                a.add("?SW:" + callee)    # meaningful only where the run stubs that callee
            abs_[fn], direct[fn] = a, d
        rows_of = {}
        for fn, calls in self.calls.items():
            rows = []
            for callee, args, facts in calls:
                rows.append((callee, [(self.param_position(fn, facts, p), self.objects_of(n)) for p, n in args]))
            rows_of[fn] = rows
        changed = True
        while changed:
            changed = False
            for fn, rows in rows_of.items():
                if fn not in abs_:
                    continue
                a, d = abs_[fn], direct[fn]
                before = (len(a), len(d))
                for callee, info in rows:
                    a |= abs_.get(callee, set())
                    for j in direct.get(callee, ()):
                        if j < len(info):
                            index, objs = info[j]
                            if index is not None:
                                d.add(index)
                            else:
                                a |= objs
                if (len(a), len(d)) != before:
                    changed = True
        out = {}
        for fn in self.functions:
            unknown = sorted(o for o in abs_[fn] if o.startswith("?U:"))
            out[fn] = {"abs": None if unknown else frozenset(abs_[fn]), "params": frozenset(direct[fn]),
                       "why": unknown[0][3:] if unknown else ""}
        return out

    def param_position(self, fn, facts, name) -> int | None:
        """The position of parameter ``name`` of ``fn`` when it is never reassigned there (nor by a macro expanded
        there) and every definition of ``fn`` names the same parameters."""
        if name is None or not facts:
            return None
        params = [p[0] for p in facts.get("params") or ()]
        if name not in params or name in (facts.get("reassigned") or ()) or name in self.extra_reassigned.get(fn, ()):
            return None
        if any([p[0] for p in d.get("params") or ()] != params for d in self.functions.get(fn) or ()):
            return None
        return params.index(name)

    # ── questions ─────────────────────────────────────────────────────────────────────────────────
    def summary(self, name: str) -> dict | None:
        return self.summaries.get(name)

    def params(self, name: str) -> list | None:
        """Parameters ``[name, base, kind]`` when every definition of ``name`` agrees on them, else None."""
        defs = self.functions.get(name) or []
        if not defs or any(not d or d.get("params_unreadable") for d in defs):
            return None   # (review R64 round 3 Info) a K&R definition: which argument binds to which is not read
        first = defs[0].get("params") or []
        if any((d.get("params") or []) != first for d in defs):
            return None
        return first

    def variadic(self, name: str) -> bool:
        return any(d.get("variadic") for d in self.functions.get(name) or ())

    def contents(self, obj: str) -> frozenset:
        n = self.nodes.get(obj)
        return self.objects_of(n) if n is not None else frozenset()

    def reach(self, objs, through=None) -> frozenset:
        """Objects reachable from ``objs`` through the pointers they hold — not through an object ``through`` refuses
        (a harness token that stands for nothing in a run: what is stored through it was stored in the objects the
        pointer also holds)."""
        out, stack = set(objs), list(objs)
        while stack:
            x = stack.pop()
            if through is not None and not through(x):
                continue
            for x in self.contents(x):
                if x not in out:
                    out.add(x)
                    stack.append(x)
        return frozenset(out)

    def question(self, fn, tree, records, entry="", scope_names=frozenset(), as_pointer=False) -> frozenset:
        """Objects a value tree read in ``fn`` may point to by the solution (``records``: the calls its ``["r", i]``
        name). Read-only: nothing is added to the graph. The function under test (``entry``) gets its pointer
        parameters from the harness alone. An argument that is a macro expanding to a list is no one argument
        (review R64 C-F): unknown."""
        if self.comma_macro(tree, [r[1] for r in records if r[0] == "c"]):
            return frozenset({"?U:macro_argument_list"})
        if entry and fn == entry:
            kept = {p[0] for p in self.params(fn) or ()} - self.reassigned_params(fn)
            tree = _entry_parameters(tree, kept, fn)
        rmap = self.q_calls(fn, records, scope_names, 0, ())
        ctx = (scope_names, rmap, 0, ())
        objs, t = self.q_rv(fn, tree, ctx)
        t = self.norm(t)
        if as_pointer and not objs and t is not None and self.integer_type(t):
            # (review R64 round 5 C) an integer passed for a pointer parameter is converted to one: a constant addresses
            #   hardware, any other may be anything — as `as_pointer` binds it in the graph
            return frozenset({HARDWARE}) if self.constant_tree(fn, tree, ctx, True) \
                else frozenset({"?U:integer_to_pointer"})
        return objs

    def reassigned_params(self, fn) -> set:
        out = set(self.extra_reassigned.get(fn, ()))
        for d in self.functions.get(fn) or ():
            out |= set(d.get("reassigned") or ())
        return out

    def q_calls(self, fn, records, scope_names, depth, stack):
        rmap: dict[int, tuple] = {}
        index = 0
        callees = [r[1] for r in records if r[0] == "c"]
        for r in records:
            if r[0] == "c":
                if any(self.comma_macro(t, callees) for t in r[2]):
                    rmap[index] = (frozenset({"?U:macro_argument_list"}), None)
                else:
                    rmap[index] = self.q_call(fn, r, (scope_names, rmap, depth, stack))
                index += 1
        return rmap

    def q_sub(self, fn, ctx, name, recs):
        """The question context for a macro's expansion: its own calls, one level deeper, the macro on the stack."""
        scope_names, _rmap, depth, stack = ctx
        return (scope_names, self.q_calls(fn, recs, scope_names, depth + 1, stack + (name,)), depth + 1, stack + (name,))

    def q_contents(self, objs) -> frozenset:
        return frozenset(x for o in objs for x in self.contents(o))

    def q_lv(self, fn, tree, ctx):
        k = tree[0] if tree else ""
        scope_names, _rmap, depth, stack = ctx
        if depth > _MACRO_DEPTH:
            return frozenset({"?U:macro_recursion"}), None
        if k == "v":
            ns, name = tree[1], tree[2]
            if ns == "N" and name in self.body_macros:
                return frozenset({"?U:body_macro:" + name}), None
            if ns == "N" and self.object_macro(name) and name not in stack:
                _v, lvt, recs = self.q_expand(name, None, scope_names)
                inner = self.q_lv(fn, lvt, self.q_sub(fn, ctx, name, recs)) if lvt is not None else (frozenset(), None)
                if self.declared(name):   # (C-5)
                    plain = self.q_lv(fn, tree, (scope_names, ctx[1], depth, stack + (name,)))
                    return inner[0] | plain[0], (inner[1] if inner[1] == plain[1] else None)
                return inner
            if ns == "N" and name in self.macros and name not in self.functions and name not in self.objects \
                    and name not in stack:
                return frozenset(), None
            obj = self.object_of(fn, ns, name)
            if obj is None:
                return frozenset(), None
            if obj.startswith("F:"):
                return frozenset({obj}), ("void", "f")
            return frozenset({obj}), self.var_type(obj)
        if k == "d":
            objs, t = self.q_rv(fn, tree[1], ctx)
            t = self.norm(t)
            return objs, ((t[0], t[1][1:]) if t is not None and t[1][:1] in ("p", "a") else None)
        if k == "m":
            objs, t = self.q_lv(fn, tree[1], ctx)
            return objs, self.member(t, tree[2])
        if k == "any":
            parts = [self.q_lv(fn, x, ctx) for x in self.alternatives(tree[1])]
            types = {p[1] for p in parts}
            return frozenset().union(*(p[0] for p in parts)), (types.pop() if len(types) == 1 else None)
        if k == "mc":
            entry = ctx[1].get(tree[1])
            if entry is not None and len(entry) > 2 and entry[2] is not None:
                lt, recs, callee = entry[2]
                return self.q_lv(fn, lt, self.q_sub(fn, ctx, callee, recs))
        return frozenset({"?U:" + (str(tree[1]) if len(tree) > 1 else "lvalue")}), None

    def q_rv(self, fn, tree, ctx):
        k = tree[0] if tree else "n"
        if k == "n":
            return frozenset(), None
        if k == "P":
            obj = f"L:{tree[1]}:{tree[2]}"
            return frozenset({f"?P:{tree[1]}:{tree[2]}"}), self.var_type(obj)
        if k == "l":
            inner = tree[1]
            name = inner[2] if inner[0] == "v" and inner[1] == "N" else ""
            scope_names, _rmap, depth, stack = ctx
            if name and self.object_macro(name) and name not in self.body_macros and name not in stack:
                if depth > _MACRO_DEPTH:
                    return frozenset({"?U:macro_recursion"}), None
                vt, _lt, recs = self.q_expand(name, None, scope_names)
                val = self.q_rv(fn, vt, self.q_sub(fn, ctx, name, recs))
                if self.declared(name):   # (C-5)
                    plain = self.q_rv(fn, tree, (scope_names, ctx[1], depth, stack + (name,)))
                    return val[0] | plain[0], (val[1] if val[1] == plain[1] else None)
                return val
            objs, t = self.q_lv(fn, tree[1], ctx)
            t = self.norm(t)
            if t is not None and t[1].startswith("a"):
                return objs, (t[0], "p" + t[1][1:])
            if t is not None and t[1].startswith("f"):
                return objs, (t[0], "p" + t[1])
            if t is not None and self.integer_type(t):
                return frozenset(), t
            reread = frozenset({"?U:integer_reinterpreted"}) if self.q_reread(objs) else frozenset()
            if t is not None:
                return self.q_contents(objs) | reread, t
            return objs | self.q_contents(objs) | reread, None
        if k == "a":
            objs, t = self.q_lv(fn, tree[1], ctx)
            t = self.norm(t)
            return objs, ((t[0], "p" + t[1]) if t is not None else None)
        if k == "c":
            objs, ot = self.q_rv(fn, tree[3], ctx)
            t = self.norm((tree[1], tree[2]))
            if t is not None and self.integer_type(t):
                return frozenset(), t
            if tree[2].startswith("p") or t is None or t[1][:1] == "p":
                if ot is None or self.integer_type(ot):
                    if self.constant_tree(fn, tree[3], ctx, True):
                        return frozenset({HARDWARE}), t
                    return objs | {"?U:integer_to_pointer"}, t
            return objs, t
        if k == "+":
            parts = [self.q_rv(fn, x, ctx) for x in tree[2]]
            pointers = [p for p in parts if p[1] is not None and p[1][1][:1] == "p"]
            if tree[1] == "-" and len(pointers) == 2:
                return frozenset(), None
            return (frozenset().union(*(p[0] for p in parts if not self.integer_type(p[1]))),
                    pointers[0][1] if len(pointers) == 1 else None)
        if k == "?":
            parts = [self.q_rv(fn, x, ctx) for x in tree[1]]
            types = {p[1] for p in parts if p[0]}
            return frozenset().union(*(p[0] for p in parts)), (types.pop() if len(types) == 1 else None)
        if k == "r":
            return ctx[1].get(tree[1], (frozenset({"?U:call_value_unmodeled"}), None))[:2]
        if k == "amb":
            reading = self.cast_reading(fn, tree[1])
            return self.q_rv(fn, tree[2] if reading == "cast" else tree[3] if reading == "binary" else ["?", tree[2:4]],
                             ctx)
        if k == "um":
            return frozenset({"?U:model:" + str(tree[1])}), None
        return frozenset({"?U:" + (str(tree[1]) if len(tree) > 1 else "value")}), None

    def q_call(self, fn, r, ctx):
        """A call inside a question: its value only (and a macro's lvalue tree, for ``SLOT(2)`` designating)."""
        scope_names, _rmap, depth, stack = ctx
        callee, trees, text = r[1], r[2], r[3]
        if callee.startswith("(") and callee.endswith(")"):
            name = callee[1:-1]
            if self.paren_cast(name, len(trees)):
                return self.q_rv(fn, ["c", name, "", trees[0]], ctx) if trees else (frozenset(), None)
            callee = name if name in self.functions or name in self.macros or name in self.body_macros \
                else "<indirect>"
        if callee in self.body_macros:
            return frozenset({"?U:body_macro:" + callee}), None
        out: set = set()
        types = set()
        lvalue = None
        macro = callee in self.macros and callee not in stack
        if macro:
            if not text or depth > _MACRO_DEPTH:
                return frozenset({"?U:macro_call:" + callee}), None
            vt, lt, recs = self.q_expand(callee, text, scope_names)
            objs, t = self.q_rv(fn, vt, self.q_sub(fn, ctx, callee, recs))
            out |= objs
            types.add(t)
            lvalue = (lt, recs, callee) if lt is not None else None
            if callee in self.objects:   # (review R64 W-4) a unit that does not see the macro calls the object
                out.add("?U:call:" + callee)
        if callee in self.functions:
            out |= {"?S:" + callee} | self.contents("R:" + callee)
            types.add(self.var_type("R:" + callee))
        elif not macro:
            if callee in _LIBRARY:
                ret = _LIBRARY[callee][0]
                return self.q_rv(fn, trees[ret], ctx) if ret is not None and ret < len(trees) else (frozenset(), None)
            return frozenset({"?U:call:" + callee}), None
        return frozenset(out), (types.pop() if len(types) == 1 else None), lvalue

    def q_expand(self, name, call_text, scope_names):
        """(value tree, lvalue tree, records) of a macro read for a question — nothing is added to the graph."""
        key = ("q", name, call_text, frozenset(scope_names))
        if key in self.memo:
            return self.memo[key]
        values, lvalues, records = [], [], []
        for body, raw, root in self.macro_parses(name, call_text):
            if root is None:
                values.append(["u", "opaque_macro:" + name])
                lvalues.append(["u", "opaque_macro:" + name])
                continue
            sub = _Facts(raw, scope_names=set(scope_names))
            sub.ncalls = len([r for r in records if r[0] == "c"])
            v, lvt = sub.expansion(root)
            values.append(v)
            if lvt is not None:
                lvalues.append(lvt)
            records += sub.records
        out = (values[0] if len(values) == 1 else ["?", values],
               (lvalues[0] if len(lvalues) == 1 else ["any", lvalues]) if lvalues else None, records)
        self.memo[key] = out
        return out


ANONYMOUS_MEMBER = "<anon>"   # an unnamed member of a struct's facts (no expression names it)


def _effectful_text(text) -> bool:
    """A macro body that may assign, take an address, call or paste — or one not read (None)."""
    if text is None:
        return True
    return bool(_ASSIGNS.search(text) or "&" in text.replace("&&", "") or "##" in text
                or re.search(r"[A-Za-z_]\w*\s*\(", text))


def _lvalue_root(tree):
    """The variable an lvalue tree is a member path of (``["v", ns, name]``), or None."""
    while tree and tree[0] == "m":
        tree = tree[1]
    return tree if tree and tree[0] == "v" else None


def _push(ctx, name):
    """``ctx`` with macro ``name`` on its expansion stack."""
    return (tuple(ctx[0]) + (name,),) + tuple(ctx[1:])


def _through_pointer(tree) -> bool:
    """An lvalue tree that designates its objects through a pointer value (``*p``, ``p[i]``, ``p->m``) — not a named
    object or a member of one."""
    while tree and tree[0] == "m":
        tree = tree[1]
    if not tree:
        return True
    if tree[0] == "any":
        return any(_through_pointer(x) for x in tree[1])
    if tree[0] == "init":
        return False
    return tree[0] != "v"


def _has_names(tree) -> bool:
    """Whether a tree reads a name the solver resolves (``N``) — the only place a macro can hide."""
    if not isinstance(tree, list) or not tree:
        return False
    if tree[0] == "v":
        return tree[1] == "N"
    return any(_has_names(x) for x in tree if isinstance(x, list))


def _rekey(tree, sub_map):
    """A tree of an expansion with its call values replaced by nodes (``["K", node]``) and its call lvalues by what
    those calls' expansions designate (``["MC", (lvalue tree, macro)]`` — review R64 C-D)."""
    if tree is None or not isinstance(tree, list) or not tree:
        return tree
    if tree[0] == "r":
        entry = sub_map.get(tree[1])
        if entry is None:
            return ["u", "call_value_unmodeled"]
        # (review R64 round 5 A) the call's type goes with its node; a value with no node (an integer) is no constant
        if entry[0] is None:
            return ["I", entry[1] if len(entry) > 1 else None]
        return ["K", entry[0], entry[1] if len(entry) > 1 else None]
    if tree[0] == "mc":
        entry = sub_map.get(tree[1])
        if entry is not None and len(entry) > 2 and entry[2] is not None:
            return ["MC", entry[2]]
        return ["u", "lvalue_call"]
    return [_rekey(x, sub_map) if isinstance(x, list) else x for x in tree]


def _entry_parameters(tree, params, fn):
    """A value tree in the function under test with each of its parameters read as the harness's object."""
    if not isinstance(tree, list) or not tree:
        return tree
    if tree[0] == "l" and isinstance(tree[1], list) and tree[1][:2] == ["v", "L"] and tree[1][2] in params:
        return ["P", fn, tree[1][2]]
    return [_entry_parameters(x, params, fn) if isinstance(x, list) else x for x in tree]


def _call_arguments(text: str) -> list[str] | None:
    """The argument texts of a call text ``M(a, (b, c))`` — split at top-level commas; None when unbalanced."""
    start = text.find("(")
    if start < 0 or not text.rstrip().endswith(")"):
        return None
    inner = text[start + 1:text.rstrip().rfind(")")]
    args, depth, cur, i = [], 0, [], 0
    while i < len(inner):
        ch = inner[i]
        if ch in "\"'":
            j = i + 1
            while j < len(inner) and inner[j] != ch:
                j += 2 if inner[j] == "\\" else 1
            cur.append(inner[i:j + 1])
            i = j + 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return None
        if ch == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    if depth != 0:
        return None
    last = "".join(cur).strip()
    if args or last:
        args.append(last)
    return args


def _substitute(body: str, params, args) -> str | None:
    """A function-like macro's body with its arguments in (review R64 C-4): ``#p`` a string literal, every other
    parameter its argument text, then ``a ## b`` pasted into one token — literals kept. A variadic macro takes the rest
    of the arguments as ``__VA_ARGS__``. None when the arguments do not fit the parameters."""
    params = list(params)
    if params and params[-1] == "...":
        fixed = params[:-1]
        if len(args) < len(fixed):
            return None
        table = dict(zip(fixed, args[:len(fixed)], strict=True))
        table["__VA_ARGS__"] = ", ".join(args[len(fixed):])
    elif params and params[-1].endswith("..."):
        fixed = params[:-1]
        if len(args) < len(fixed):
            return None
        table = dict(zip(fixed, args[:len(fixed)], strict=True))
        table[params[-1][:-3]] = ", ".join(args[len(fixed):])
    else:
        if len(params) != len(args):
            return None
        table = dict(zip(params, args, strict=True))
    if table:
        names = "|".join(re.escape(x) for x in sorted(table, key=len, reverse=True))
        literal = r"(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"
        stringize = re.compile(literal + r"|(?<!#)#\s*\b(" + names + r")\b")
        body = stringize.sub(lambda m: m.group(1) if m.group(1) is not None else
                             '"' + table[m.group(2)].replace("\\", "\\\\").replace('"', '\\"') + '"', body)
        pattern = re.compile(literal + r"|\b(" + names + r")\b")
        body = pattern.sub(lambda m: m.group(1) if m.group(1) is not None else table[m.group(2)], body)
    return _paste(body)


def _paste(body: str) -> str:
    """``a ## b`` → ``ab`` (outside literals)."""
    out, i = [], 0
    for m in re.finditer(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", body):
        out.append(re.sub(r"\s*##\s*", "", body[i:m.start()]))
        out.append(m.group(0))
        i = m.end()
    out.append(re.sub(r"\s*##\s*", "", body[i:]))
    return "".join(out)


def paren_is_cast(name: str, nargs: int, functions, objects, macro_texts, type_names) -> bool:
    """``(name)(x)`` is a cast — one rule for the write closure and the pointer flow (review R64 I-6): ``name`` is a
    typedef of the tree or a C type word and no function or object of it, or a macro every definition of which is type
    words (``#define BYTE unsigned char``). Otherwise a call — to the function or macro of that name, or through a
    function pointer."""
    if nargs != 1 or name in functions or name in objects:
        return False
    if name in macro_texts:
        return all(type_words_only(t, type_names) for t in macro_texts[name])
    return name in type_names or name in _ARITH_WORDS


def summarize_pointer_targets(effects: dict[str, Any] | None) -> dict[str, Any]:
    """(R64) For the generation disclosure: whether the analysis ran (``refused`` — why not), how many functions write
    through a pointer (``pointer_writers``), how many of them have known targets (``known_targets``, of which
    ``through_parameters`` write through a parameter resolved at each call), and why the rest do not
    (``unknown_causes`` — cause kind → count, ``unknown_samples`` — kind → up to three ``function:cause``). Empty when
    no scope carried a closure."""
    if not isinstance(effects, dict) or "functions" not in effects:
        return {}
    closure = effects.get("functions") or {}
    refused = str(effects.get("pointer_flow_refused") or "")
    writers = sorted(n for n, c in closure.items() if c.get("pointer_write"))
    known = through = 0
    causes: dict[str, int] = {}
    samples: dict[str, list[str]] = {}
    for name in writers:
        pt = closure[name].get("pointer_targets")
        unknown_callees = sorted(closure[name].get("unknown_callees") or ())
        if pt and pt.get("abs") is not None and not unknown_callees:
            known += 1
            through += bool(pt.get("params"))
            continue
        # (review R64 I-1) a closure that reaches unknown code havocs everything whatever its targets say
        why = ("unknown_callee:" + unknown_callees[0]) if unknown_callees and pt and pt.get("abs") is not None else \
            (pt or {}).get("why") or ("refused:" + refused if refused else "refused")
        kind = why.split(":", 1)[0]
        causes[kind] = causes.get(kind, 0) + 1
        if len(samples.setdefault(kind, [])) < 3:
            samples[kind].append(f"{name}:{why}")
    return {"refused": refused, "pointer_writers": len(writers), "known_targets": known,
            "through_parameters": through,
            "unknown_causes": dict(sorted(causes.items(), key=lambda kv: (-kv[1], kv[0]))),
            "unknown_samples": samples}


def analyze(context: dict[str, Any] | None) -> tuple[Analysis | None, str]:
    """The project's solved points-to graph, or (None, why it is refused)."""
    from generators import c_project_context as cpc
    if not context or not context.get("files"):
        return None, "no_context"
    gap = cpc.designator_gap(context)
    if gap:
        return None, gap
    for rec in context["files"].values():
        if "flow" not in rec:
            return None, "facts_missing"
        for d in (rec.get("stray_directives") or {}).get("directives") or ():
            if d.get("op") == "unreadable":
                return None, "unreadable_directive"
    try:
        analysis = Analysis(context)
    except Exception as exc:
        # (review R64 X-1 / W-1) the analysis failing must not take the generation down: refused, the old havoc stands
        return None, "analysis_failed:" + type(exc).__name__
    if analysis.refused:
        return None, analysis.refused
    return analysis, ""
