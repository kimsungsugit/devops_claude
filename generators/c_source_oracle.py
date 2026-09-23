"""Source oracle over the project C context: what one function leaves in its outputs for concrete inputs.

A code-consistency oracle — not a requirement oracle, not an execution result, not reachability. It
interprets the unchanged function text with the translation unit's resolved scope
(`generators.c_project_context`): target integer widths from typedef testimony, integer macros,
enumerators, const objects, scalar globals and one-dimensional arrays. Nothing is guessed:

* a value the inputs do not determine is *unknown* with its reason — a global the sequence does not set,
  a call's return value, a volatile read, a pointer target, an out-of-type input (``U8 = -1``);
* a branch on an unknown condition runs both arms; an output is *derived* only when every path agrees;
* a call havocs what the callee may write (the project write closure, transitively); a write through a pointer
  (in the function or a callee) reaches arrays, address-taken objects and escaped locals; a callee with unknown
  effects (library, indirect) havocs every global, every escaped local and every static local;
* undefined behaviour proven on a path (signed overflow, division by zero, shift range, out-of-bounds index,
  unsequenced side effects) refuses the whole evaluation; undefined behaviour that depends on an unknown value is
  disclosed (``possible_undefined_behavior``);
* implementation-defined results (signed narrowing, an enumeration object's underlying type) are unknown
  unless every permitted choice gives the same value.
"""
from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from typing import Any

from generators import c_project_context as cpc

SCHEMA_VERSION = 1
_UB_REASONS = frozenset({"signed_overflow", "division_by_zero", "shift_count_out_of_range", "signed_left_shift_overflow",
                         "float_to_int_out_of_range"})
_EXECUTION_BUDGET = 200_000
_PATH_BUDGET = 64
_LOOP_BUDGET = 4096
ASSUMPTIONS = (
    "undefined behaviour is refused when proven on a path; where it depends on an unknown value (divisor, shift "
    "count, index, overflow of an unknown operand) it is not proven absent — derived values hold for runs without it",
    "callee effects are the project write closure (a callee is stubbed or real — outputs it may write are unknown)",
    "reachability and termination of callees are not proven",
    "fixed-address register objects are distinct objects (writes to one do not change another)",
    "an integer converted to a pointer addresses hardware, not a C object: a write through a pointer reaches only "
    "address-taken objects, arrays and locals whose address escaped",
)


class Unsupported(ValueError):
    """The evaluation as a whole has no defined result (UB on a possible path, unsupported statement, budget)."""


class Unknown:
    """A value the source and inputs do not determine. ``range``: set only on a *stored* unknown (`_Interp.convert_to`)
    — the interval of the value that was stored, lifted back to `_Val.r` when that object is read. Operators pass
    ``Unknown`` objects through to values they are not, so nothing but a load may consult it (review round 6 C1)."""
    __slots__ = ("reason", "range")

    def __init__(self, reason: str, range: tuple[int, int] | None = None):  # noqa: A002 — the interval, by name
        self.reason, self.range = reason, range

    def __repr__(self):
        return f"Unknown({self.reason})"


class _Val:
    """An evaluated expression. ``r``: an interval an unknown ``v`` is known to lie in — only ever passed explicitly
    (cast, provably in-range arithmetic, a load), so a value built from an operand without it has no interval."""
    __slots__ = ("v", "t", "r")

    def __init__(self, v, t, r=None):
        self.v, self.t, self.r = v, t, r


def _havocked(value, reason):
    """What an unknown write leaves in an object: an earlier, more specific reason stays — its interval does not, since
    it described the value before the write (review round 7 C1: ``g = (S16)u8; ext(); g * 100``)."""
    if not isinstance(value, Unknown):
        return Unknown(reason)
    return Unknown(value.reason) if value.range is not None else value


_POINTER_REASONS = ("pointer_parameter:", "pointer_local:", "pointer_value:", "array_value:")


def _untyped_overflow_tag(operands, int_bits):
    """Possible-UB tag for arithmetic with an operand of unknown type (review round 6 C2 / round 7 W1): a pointer or a
    decayed array — the result may leave the object (C11 6.5.6p8); ``sizeof`` — ``size_t`` is unsigned and at least
    16 bits, so against operands no wider than ``int`` the result is unsigned and cannot overflow (``None``); anything
    else (a call's return, an unresolved macro, ``*p``) may be a signed int."""
    untyped = [x.v.reason if isinstance(x.v, Unknown) else "" for x in operands if x.t is None]
    if any(r.startswith(_POINTER_REASONS) for r in untyped):
        return "pointer_arithmetic_untyped"
    if untyped and all(r == "sizeof_unmodeled" for r in untyped) and all(
            x.t.get("bits", 99) <= int_bits for x in operands if isinstance(x.t, dict)):
        return None
    return "signed_overflow_untyped_operand"


def _loaded(value, t):
    """The value of an object read from the store: a stored unknown's interval comes back with it."""
    return _Val(value, t, value.range if isinstance(value, Unknown) else None)


class _State:
    __slots__ = ("store", "mode", "ret", "havoc_all", "havoc_pointer", "havoc_bases", "escaped", "forks", "possible_ub",
                 "decisions")

    def __init__(self):
        self.store: dict[str, Any] = {}
        self.mode = "normal"
        self.ret: _Val | None = None
        self.havoc_all = ""
        self.havoc_pointer = ""
        self.havoc_bases: dict[str, str] = {}
        self.escaped: set[str] = set()
        self.forks: list[str] = []
        self.possible_ub: set[str] = set()
        # (R2c) decisions this path evaluated, in order: ``(key, observation)`` — see `_Interp.record_decision`
        self.decisions: list[tuple] = []

    def copy(self):
        s = _State()
        s.store, s.mode, s.ret = dict(self.store), self.mode, self.ret
        s.havoc_all, s.havoc_bases, s.escaped, s.forks = self.havoc_all, dict(self.havoc_bases), set(self.escaped), list(self.forks)
        s.possible_ub = set(self.possible_ub)
        s.decisions = list(self.decisions)
        s.havoc_pointer = self.havoc_pointer
        return s


def _text(node, raw):
    return raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _named(node):
    return [c for c in node.named_children if c.type != "comment"]


def _op(node, raw):
    o = node.child_by_field_name("operator")
    return _text(o, raw) if o is not None else ""


def _walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(n.named_children)


_SIDE_EFFECTS = frozenset({"assignment_expression", "update_expression", "call_expression", "gnu_asm_expression"})
# builtins that evaluate their argument like a function would (same list as `mcdc_design.EVALUATING_BUILTINS`)
_EVALUATING_BUILTINS = frozenset({"__builtin_expect", "__builtin_abs", "__builtin_labs", "__builtin_popcount",
                                  "__builtin_clz", "__builtin_ctz", "__builtin_bswap16", "__builtin_bswap32"})


class _Interp:
    def __init__(self, fn, raw, scope, inputs, parser, shared=None):
        """``shared``: a dict one caller keeps across the vectors of one function (same ``fn``/``raw``/``scope``) — what
        does not depend on the inputs is computed once: the body's address-taken names, macro expansion parses and
        the node lists `check_sequencing` walks (R2c: per-vector re-walking was 40% of a path search)."""
        self.fn, self.raw, self.scope, self.inputs, self.parser = fn, raw, scope, inputs, parser
        self.shared = shared if shared is not None else {}
        self.widths = (scope.get("target") or {}).get("widths") or {}
        if not self.widths.get("int"):
            # Every integer promotion goes through ``int``; other widths are needed only by the types that use them.
            raise Unsupported("target_int_width_unresolved")
        self.int_t = cpc.ctype("int", True, self.widths)
        self.lexical: list[dict[str, dict]] = []
        # A lazy constants map is an *empty* dict until asked: never ``or {}`` it away.
        self.constants = scope["constants"] if scope.get("constants") is not None else {}
        self.globals = scope.get("globals") or {}
        self.arrays = scope.get("arrays") or {}
        self.macro_status = scope.get("macro_status") or {}
        self.macro_bodies = scope.get("macro_bodies") or {}
        self.macro_params = scope.get("function_like_macro_params") or {}
        self.fmacro_bodies = scope.get("function_like_macro_bodies") or {}
        effects = scope.get("effects") or {}
        self.closure = effects.get("functions") or {}
        self.address_taken = set(effects.get("address_taken") or ())
        self.steps = 0
        # text → (node, raw of the parse): the raw buffer lives in the tuple, so sharing it keeps ids stable
        self.expansions: dict[str, tuple] = self.shared.setdefault("expansions", {})
        self.walks: dict[tuple, Any] = self.shared.setdefault("walks", {})  # node lists and "plain" flags
        self.params: dict[str, dict] = {}
        self.static_keys: set[str] = set()
        self.kept_raws: list[bytes] = []
        # (R2c) decisions to observe: ``{(start, end, type): {"key", "atoms": [node], "ir"}}`` over the function's own text
        self.fn_raw = raw
        self.watch: dict | None = None
        # (R2c) control conditions whose outcome to record (``if``/loop/``?:`` conditions guarding a watched decision)
        self.guards: dict = {}
        self.function_name = ""
        if "body_address_names" in self.shared:
            self.body_address_names = set(self.shared["body_address_names"])
            return
        body = fn.child_by_field_name("body")
        # Names whose address the body takes (``&s``): a static local among them may be reached by any pointer write.
        self.body_address_names = {
            _text(x, raw) for n in (_walk(body) if body is not None else ())
            if n.type in {"pointer_expression", "unary_expression"} and _text(n, raw).lstrip().startswith("&")
            and not _text(n, raw).lstrip().startswith("&&")
            for x in [_unwrap(n.child_by_field_name("argument"))] if x is not None and x.type == "identifier"}
        # ...and through a macro: ``SAVE(s)`` with ``#define SAVE(v) (g_p = &(v))`` (R2b review round 2 F / X6).
        for n in (_walk(body) if body is not None else ()):
            if n.type == "call_expression" and n.child_by_field_name("function") is not None:
                callee = _text(n.child_by_field_name("function"), raw)
                text = self.macro_text_closure(callee) if callee in self.macro_status else ""
                if text and cpc._MACRO_ADDRESS_RE.search(text):
                    args = n.child_by_field_name("arguments")
                    self.body_address_names.update(
                        _text(x, raw) for a in (args.named_children if args is not None else []) for x in _walk(a)
                        if x.type == "identifier")
                    self.body_address_names.update(cpc._MACRO_ADDRESS_RE.findall(text))
            elif n.type == "identifier" and _text(n, raw) in self.macro_status:
                self.body_address_names.update(cpc._MACRO_ADDRESS_RE.findall(self.macro_text_closure(_text(n, raw))))
        self.shared["body_address_names"] = frozenset(self.body_address_names)

    # ── budgets / helpers ────────────────────────────────────────────────────────────────────────
    def tick(self):
        self.steps += 1
        if self.steps > _EXECUTION_BUDGET:
            raise Unsupported("execution_budget")

    def lift(self, fn, *args):
        """cpc operation: UB refuses the evaluation, other unresolved results are an unknown value."""
        try:
            return fn(*args)
        except cpc.Unresolved as exc:
            reason = str(exc)
            if reason in _UB_REASONS:
                raise Unsupported("undefined_behavior:" + reason) from exc
            return Unknown(reason)

    def type_of(self, text):
        text = " ".join(str(text).split())
        try:
            from generators.mcdc_design import _scope_type
            return _scope_type(self.scope, text)
        except cpc.Unresolved as exc:
            return Unknown("type_unresolved:" + text + ":" + str(exc))

    def check_input(self, name, t, value):
        """An input value as the object would hold it; out-of-type values are not executable inputs."""
        if isinstance(value, str):
            s = value.strip()
            if re.fullmatch(r"[-+]?(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*", s):
                s = s.rstrip("uUlL")
                value = int(s, 16) if "x" in s.lower() else int(s, 10)
            elif s in self.constants:
                value = self.constants[s]["value"]
            else:
                return Unknown("input_not_an_integer:" + name)
        if isinstance(value, bool) or type(value) is not int:
            return Unknown("input_not_an_integer:" + name)
        if not isinstance(t, dict) or cpc.is_float(t):
            return Unknown("input_type_unmodeled:" + name)
        lo, hi = (0, 1) if t["kind"] == "_Bool" else cpc.type_range(t)
        if t.get("enum"):
            lo, hi = 0, 127  # held unchanged by every permitted underlying type (C11 6.7.2.2p4)
        if not lo <= value <= hi:
            return Unknown("input_outside_declared_type:" + name)
        return value

    # ── storage ──────────────────────────────────────────────────────────────────────────────────
    def lookup(self, name):
        for frame in reversed(self.lexical):
            if name in frame:
                return frame[name]
        return None

    def initial(self, state, key, base, t, volatile=False):
        if volatile:
            return Unknown("volatile_object:" + base)
        if state.havoc_all:
            return Unknown(state.havoc_all)
        if state.havoc_pointer and (base in self.arrays or base in self.address_taken):
            return Unknown(state.havoc_pointer)
        if base in state.havoc_bases:
            return Unknown(state.havoc_bases[base])
        if key in self.inputs:
            return self.check_input(key, t, self.inputs[key])
        return Unknown("initial_value_not_in_inputs:" + key)

    def read_key(self, state, key, base, t, volatile=False):
        if volatile:
            return Unknown("volatile_object:" + base)
        if key in state.store:
            return state.store[key]
        return self.initial(state, key, base, t)

    def havoc_base(self, state, base, reason):
        for key in list(state.store):
            if key == base or key.startswith(base + "[") or key.startswith(base + "."):
                state.store[key] = Unknown(reason)
        state.havoc_bases[base] = reason

    def havoc_everything(self, state, reason, locals_too=False):
        """``locals_too``: text that expands *in* this function (a macro we cannot model, inline assembly operands, a
        write through a macro name) can name a parameter or local directly — ``#define ZERO(n) n##_v = 0U`` writes
        ``x_v`` (R2c: found by the MC/DC path tests). A callee cannot: only escaped locals are its business."""
        for key in list(state.store):
            base = key.split("[", 1)[0]
            if base.startswith("@") and base not in state.escaped and not locals_too:
                continue  # a parameter or local whose address never left the function
            state.store[key] = _havocked(state.store[key], reason)  # an earlier, more specific reason stays
        for base in state.escaped:
            if base.startswith("@"):
                state.havoc_bases[base] = reason
        self.havoc_statics(state, reason)  # unknown code may call back into this function
        if not state.havoc_all:
            state.havoc_all = reason

    def havoc_statics(self, state, reason):
        for key in list(state.store):
            if key.split("[", 1)[0] in self.static_keys:
                state.store[key] = _havocked(state.store[key], reason)
        for base in self.static_keys:
            state.havoc_bases.setdefault(base, reason)

    def havoc_pointer_targets(self, state, reason):
        """A write through a pointer: it reaches only an object whose address was taken somewhere in the project,
        an array (arrays decay to pointers without ``&``) or a local whose address left this function — given that
        an integer converted to a pointer addresses hardware, not a C object (see ``ASSUMPTIONS``)."""
        for key in list(state.store):
            base = key.split("[", 1)[0]
            if base in state.escaped or base in self.arrays or (base in self.globals and base in self.address_taken):
                state.store[key] = _havocked(state.store[key], reason)
        for base in state.escaped:
            state.havoc_bases.setdefault(base, reason)
        if not state.havoc_pointer:
            state.havoc_pointer = reason

    def store(self, state, target, val):
        kind = target[0]
        if kind == "key":
            _, key, t, volatile = target
            if t is None or isinstance(t, Unknown):
                state.store[key] = Unknown("object_type_unresolved")
                return
            state.store[key] = self.convert_to(val, t)
        elif kind == "base":
            self.havoc_base(state, target[1], target[2])
        elif kind == "ptr":
            self.havoc_pointer_targets(state, target[1])
        elif kind == "all":
            self.havoc_everything(state, target[1], locals_too=True)  # the target may be any name in scope

    def convert_to(self, val, t):
        if isinstance(val.v, Unknown):
            # Stored with exactly the interval of the value stored — an object reused from another value may carry
            # that value's interval, which must not be stored (review round 6 C1).
            if val.r is None and val.v.range is None:
                return val.v
            return Unknown(val.v.reason, val.r)
        if cpc.is_float(t) or cpc.is_float(val.t) or val.t is None:
            return Unknown("floating_point_unmodeled" if (cpc.is_float(t) or cpc.is_float(val.t)) else "value_type_unresolved")
        if t.get("enum"):
            # An enumeration object's underlying type is implementation-defined (C11 6.7.2.2p4): the stored value
            # is known only if every permitted choice holds it unchanged.
            outs = {repr(self.lift(cpc.convert, val.v, c)) for c in self.enum_candidates()}
            return val.v if outs == {repr(val.v)} else Unknown("enum_object_type_implementation_defined")
        return self.lift(cpc.convert, val.v, t)

    def enum_candidates(self):
        return [cpc.ctype(k, s, self.widths) for k, s in (("int", True), ("int", False), ("char", True), ("char", False))]

    # ── function entry ───────────────────────────────────────────────────────────────────────────
    def bind_parameters(self, state):
        from generators.mcdc_design import _function_name
        _, fdecl = _function_name(self.fn, self.raw)
        frame: dict[str, dict] = {}
        params = fdecl.child_by_field_name("parameters")
        for p in _named(params):
            if p.type != "parameter_declaration":
                if p.type == "variadic_parameter":
                    raise Unsupported("variadic_function")
                continue
            ident, typ = p.child_by_field_name("declarator"), p.child_by_field_name("type")
            if ident is None:
                continue
            name = cpc._declared_name(ident, self.raw)
            key = "@param:" + name
            quals = [_text(c, self.raw) for c in p.named_children if c.type == "type_qualifier"]
            if ident.type == "identifier":
                t = self.type_of(" ".join(quals + [_text(typ, self.raw)]))
                volatile = "volatile" in quals or (isinstance(t, dict) and "volatile" in (t.get("qualifiers") or []))
                info = {"key": key, "type": t if isinstance(t, dict) else None, "volatile": volatile, "kind": "param"}
                if isinstance(t, Unknown):
                    state.store[key] = t
                elif name in self.inputs:
                    state.store[key] = self.check_input(name, t, self.inputs[name])
                else:
                    state.store[key] = Unknown("parameter_not_in_inputs:" + name)
            else:
                info = {"key": key, "type": None, "pointer": True, "kind": "param"}
                state.store[key] = Unknown("pointer_parameter:" + name)
            frame[name] = info
            self.params[name] = info
        self.lexical.append(frame)

    # ── statements ───────────────────────────────────────────────────────────────────────────────
    def run(self, states, node):
        """Execute ``node`` on every normal state; others pass through. Returns the resulting states."""
        active = [s for s in states if s.mode == "normal"]
        rest = [s for s in states if s.mode != "normal"]
        if not active:
            return states
        self.tick()
        out = self.statement(active, node)
        if len(out) + len(rest) > _PATH_BUDGET:
            raise Unsupported("path_budget")
        return rest + out

    def statement(self, states, n):
        k = n.type
        raw = self.raw
        if k in {"comment", "preproc_def", "preproc_function_def", "preproc_call"}:
            directive = n.child_by_field_name("directive") if k == "preproc_call" else None
            if directive is not None and _text(directive, raw).strip() == "#pragma":
                return states  # placement / diagnostics only
            if k != "comment" and self.inside_body(n):
                raise Unsupported("preprocessor_directive_in_body")
            return states
        if k == "compound_statement":
            self.lexical.append({})
            try:
                for c in n.named_children:
                    states = self.run(states, c)
            finally:
                self.lexical.pop()
            return states
        if k in {"preproc_if", "preproc_ifdef", "preproc_elif", "preproc_elifdef"}:
            verdict = cpc.pp_condition(self.scope, n, raw)
            if verdict is None:
                raise Unsupported("conditional_compilation_unresolved")
            cond, name, alt = n.child_by_field_name("condition"), n.child_by_field_name("name"), n.child_by_field_name("alternative")
            arm = [c for c in n.named_children if c not in (cond, name, alt)] if verdict else ([alt] if alt is not None else [])
            for c in arm:
                states = self.run(states, c)
            return states
        if k == "preproc_else":
            for c in n.named_children:
                states = self.run(states, c)
            return states
        if k == "expression_statement":
            inner = _named(n)
            if not inner:
                return states
            if len(inner) != 1:
                raise Unsupported("unsupported_expression_statement")
            return [self.full_expression(s, inner[0], raw, statement=True) for s in states]
        if k == "declaration":
            for s in states:
                self.declaration(s, n)
            return states
        if k == "return_statement":
            inner = _named(n)
            for s in states:
                if inner:
                    val = self.full_expression_value(s, inner[0], raw)
                    rt = self.return_type()
                    s.ret = _Val(self.convert_to(val, rt) if isinstance(rt, dict) else Unknown("return_type_unresolved"), rt)
                s.mode = "return"
            return states
        if k in {"break_statement", "continue_statement"}:
            for s in states:
                s.mode = "break" if k == "break_statement" else "continue"
            return states
        if k == "if_statement":
            cons, alt = n.child_by_field_name("consequence"), n.child_by_field_name("alternative")
            yes, no = self.branch(states, n.child_by_field_name("condition"))
            yes = self.run(yes, cons)
            if alt is not None:
                no = self.run(no, alt)
            return yes + no
        if k == "else_clause":
            for c in n.named_children:
                states = self.run(states, c)
            return states
        if k in {"while_statement", "do_statement", "for_statement"}:
            return self.loop(states, n)
        if k == "switch_statement":
            return self.switch(states, n)
        if k in {"goto_statement", "labeled_statement"}:
            raise Unsupported("goto_unmodeled")
        if k in {"case_statement"}:
            raise Unsupported("case_outside_switch")
        raise Unsupported("unsupported_statement:" + k)

    def inside_body(self, n):
        body = self.fn.child_by_field_name("body")
        return body.start_byte <= n.start_byte < body.end_byte

    def return_type(self):
        from generators.mcdc_design import _function_name
        _, fdecl = _function_name(self.fn, self.raw)
        if fdecl is not None and fdecl.parent is not None and fdecl.parent.type != "function_definition":
            return Unknown("return_type_not_scalar")
        quals = [_text(c, self.raw) for c in self.fn.named_children if c.type == "type_qualifier"]
        t = self.type_of(" ".join(quals + [_text(self.fn.child_by_field_name("type"), self.raw)]))
        return t

    def branch(self, states, cond):
        """Split states on a controlling expression: (true states, false states). Unknown → both."""
        yes, no = [], []
        guard = self.guards.get((cond.start_byte, cond.end_byte, cond.type)) if self.raw is self.fn_raw else None
        for s in states:
            val = self.full_expression_value(s, cond, self.raw)
            truth = self.truth(val)
            if guard is not None:
                s.decisions.append((guard, ("outcome", truth)))
            if truth is None:
                other = s.copy()
                reason = "branch_on_unknown:" + val.v.reason if isinstance(val.v, Unknown) else "branch_on_unknown"
                s.forks.append(reason)
                other.forks.append(reason)
                yes.append(s)
                no.append(other)
            elif truth:
                yes.append(s)
            else:
                no.append(s)
        if len(yes) + len(no) > _PATH_BUDGET:
            raise Unsupported("path_budget")
        return yes, no

    def truth(self, val):
        if isinstance(val.v, Unknown):
            return None
        return bool(val.v)

    def loop(self, states, n):
        k = n.type
        self.lexical.append({})
        try:
            if k == "for_statement":
                init = n.child_by_field_name("initializer")
                if init is not None:
                    if init.type == "declaration":
                        for s in states:
                            if s.mode == "normal":
                                self.declaration(s, init)
                    else:
                        states = [self.full_expression(s, init, self.raw) if s.mode == "normal" else s for s in states]
            cond = n.child_by_field_name("condition")
            body = n.child_by_field_name("body")
            update = n.child_by_field_name("update") if k == "for_statement" else None
            done = [s for s in states if s.mode != "normal"]
            pending = [s for s in states if s.mode == "normal"]
            first = k == "do_statement"
            iterations = 0
            while pending:
                iterations += 1
                if iterations > _LOOP_BUDGET:
                    raise Unsupported("loop_iteration_budget")
                if not first and cond is not None:
                    pending, exits = self.branch(pending, cond)
                    done.extend(exits)
                first = False
                if not pending:
                    break
                after = self.run(pending, body) if body is not None else pending
                pending = []
                for s in after:
                    if s.mode == "break":
                        s.mode = "normal"
                        done.append(s)
                    elif s.mode == "return":
                        done.append(s)
                    else:
                        s.mode = "normal"
                        pending.append(s)
                if update is not None:
                    pending = [self.full_expression(s, update, self.raw) for s in pending]
                if len(done) + len(pending) > _PATH_BUDGET:
                    raise Unsupported("path_budget")
            return done
        finally:
            self.lexical.pop()

    def switch(self, states, n):
        raw = self.raw
        body = n.child_by_field_name("body")
        cases = [c for c in _named(body)] if body is not None else []
        if any(c.type != "case_statement" for c in cases):
            raise Unsupported("switch_body_statement_outside_case")
        labels = []
        for c in cases:
            v = c.child_by_field_name("value")
            if v is None:
                labels.append(None)
                continue
            probe = _State()
            lv = self.expression(probe, v, raw)
            if isinstance(lv.v, Unknown) or not isinstance(lv.t, dict):
                raise Unsupported("case_label_unresolved:" + _text(v, raw)[:40])
            labels.append(lv)
        entering: dict[int, list] = {}
        ended = [s for s in states if s.mode != "normal"]
        for s in states:
            if s.mode != "normal":
                continue
            val = self.full_expression_value(s, n.child_by_field_name("condition"), raw)
            if isinstance(val.v, Unknown) or not isinstance(val.t, dict):
                reason = "branch_on_unknown:" + (val.v.reason if isinstance(val.v, Unknown) else "switch_type")
                targets = sorted(set(range(len(cases))) if None in labels else set(range(len(cases))) | {-1})
                for i, target in enumerate(targets):
                    t = s if i == 0 else s.copy()
                    t.forks.append(reason)
                    (ended if target == -1 else entering.setdefault(target, [])).append(t)
                continue
            ct = cpc.promote(val.t, self.widths)
            cv = self.lift(cpc.convert, val.v, ct)
            chosen = None
            for i, lab in enumerate(labels):
                if lab is not None and self.lift(cpc.convert, lab.v, ct) == cv:
                    chosen = i
                    break
            if chosen is None and None in labels:
                chosen = labels.index(None)
            if chosen is None:
                ended.append(s)
            else:
                entering.setdefault(chosen, []).append(s)
        running: list = []
        self.lexical.append({})  # declarations after a case label live in the switch body's block (review W6)
        try:
            for i, c in enumerate(cases):
                running = running + entering.get(i, [])
                value = c.child_by_field_name("value")
                for stmt in c.named_children:
                    if stmt == value or stmt.type == "comment":
                        continue
                    running = self.run(running, stmt)
        finally:
            self.lexical.pop()
        out = ended
        for s in running:
            if s.mode == "break":
                s.mode = "normal"
            out.append(s)
        if len(out) > _PATH_BUDGET:
            raise Unsupported("path_budget")
        return out

    def declaration(self, state, n):
        raw = self.raw
        quals = [_text(c, raw) for c in n.named_children if c.type in {"type_qualifier", "storage_class_specifier"}]
        typ = n.child_by_field_name("type")
        frame = self.lexical[-1]
        storage = {q for q in quals if q in {"static", "extern", "register", "auto"}}
        type_text = " ".join([q for q in quals if q in {"const", "volatile"}] + [_text(typ, raw)])
        t = self.type_of(type_text) if typ is not None and typ.type not in {"struct_specifier", "union_specifier", "enum_specifier"} \
            else Unknown("aggregate_local_type")
        for d in n.named_children:
            if d == typ or d.type in {"type_qualifier", "storage_class_specifier", "comment", "attribute_specifier"}:
                continue
            target = d.child_by_field_name("declarator") if d.type == "init_declarator" else d
            value = d.child_by_field_name("value") if d.type == "init_declarator" else None
            name = cpc._declared_name(target, raw)
            if not name:
                raise Unsupported("unsupported_declarator")
            if "extern" in storage:
                frame[name] = {"extern": True}
                continue
            key = f"@local:{name}@{id(raw)}:{target.start_byte}"  # one statement-macro expansion ≠ another (round 2 H)
            volatile = "volatile" in quals or (isinstance(t, dict) and "volatile" in (t.get("qualifiers") or []))
            if target.type == "identifier":
                info = {"key": key, "type": t if isinstance(t, dict) else None, "volatile": volatile, "kind": "local"}
                frame[name] = info
                if "static" in storage:
                    # Persistent across calls: the entry value is whatever an earlier call left — and an earlier call
                    # may have stored its address (``g_p = &s``), so ``&s`` anywhere in the body escapes it from entry.
                    self.static_keys.add(key)
                    if name in self.body_address_names:
                        state.escaped.add(key)
                    if key not in state.store:
                        state.store[key] = Unknown("static_local_state:" + name)
                    continue
                if value is None:
                    state.store[key] = Unknown("uninitialized_local:" + name)
                elif value.type == "initializer_list":
                    self.initializer(state, value, raw, 0)
                    state.store[key] = Unknown("braced_initializer")
                else:
                    val = self.full_expression_value(state, value, raw)
                    state.store[key] = self.convert_to(val, t) if isinstance(t, dict) else Unknown("local_type_unresolved:" + name)
            elif target.type == "array_declarator" and target.child_by_field_name("declarator") is not None \
                    and target.child_by_field_name("declarator").type == "identifier":
                size = target.child_by_field_name("size")
                length = None
                if size is not None:
                    lv = self.expression(_State(), size, raw)
                    if isinstance(lv.v, int) and lv.v > 0:
                        length = lv.v
                info = {"key": key, "type": t if isinstance(t, dict) else None, "array": True, "length": length,
                        "volatile": volatile, "kind": "local"}
                items = _named(value) if value is not None and value.type == "initializer_list" else None
                if length is None and items is not None and not any(i.type == "initializer_pair" for i in items):
                    length = info["length"] = len(items)
                frame[name] = info
                if "static" in storage:
                    self.static_keys.add(key)
                    state.escaped.add(key)  # a static array may have decayed into a pointer on an earlier call
                    if not any(k.startswith(key + "[") for k in state.store):
                        state.havoc_bases[key] = "static_local_state:" + name
                    continue
                if length is None:
                    if value is not None:
                        self.initializer(state, value, raw, 0)
                    state.havoc_bases[key] = "local_array_length_unresolved:" + name
                    continue
                for i in range(length):
                    state.store[f"{key}[{i}]"] = Unknown("uninitialized_local:" + name)
                if items is not None:
                    self.check_sequencing(state, value, raw)  # items are unsequenced with each other (C11 6.7.9p23)
                    if any(i.type in {"initializer_pair", "initializer_list"} for i in items) or len(items) > length:
                        self.initializer(state, value, raw, 0)
                        for i in range(length):
                            state.store[f"{key}[{i}]"] = Unknown("array_initializer_unmodeled")
                    else:
                        for i in range(length):
                            if i < len(items):
                                val = self.full_expression_value(state, items[i], raw)
                                state.store[f"{key}[{i}]"] = self.convert_to(val, t) if isinstance(t, dict) else Unknown("local_type_unresolved")
                            else:
                                state.store[f"{key}[{i}]"] = 0 if isinstance(t, dict) and not cpc.is_float(t) else Unknown("local_type_unresolved")
                elif value is not None:
                    self.initializer(state, value, raw, 0)
                    for i in range(length):
                        state.store[f"{key}[{i}]"] = Unknown("array_initializer_unmodeled")
            else:
                # Pointers and other declarators: the local exists, its value is not modeled.
                frame[name] = {"key": key, "type": None, "pointer": True, "kind": "local"}
                state.store[key] = Unknown("pointer_local:" + name)
                if value is not None:
                    self.initializer(state, value, raw, 0)

    def initializer(self, state, node, raw, depth):
        """Run an initializer for its effects: every item, nested lists and designated values (a call, ``&x``).
        The items of one list are indeterminately sequenced (C11 6.7.9p23): checked as one expression first."""
        if node.type == "initializer_list" and depth == 0:
            self.check_sequencing(state, node, raw)
        if node.type == "initializer_list":
            for item in _named(node):
                if item.type == "initializer_pair":
                    value = item.child_by_field_name("value")
                    if value is not None:
                        self.initializer(state, value, raw, depth + 1)
                else:
                    self.initializer(state, item, raw, depth + 1)
            return
        self.full_expression_value(state, node, raw)

    # ── expressions ──────────────────────────────────────────────────────────────────────────────
    def full_expression(self, state, n, raw, statement=False):
        self.check_sequencing(state, n, raw)
        if statement and n.type in {"identifier", "call_expression"}:
            expanded = self.macro_statement(state, n, raw)
            if expanded is not None:
                return expanded
        self.expression(state, n, raw)
        return state

    def full_expression_value(self, state, n, raw):
        self.check_sequencing(state, n, raw)
        return self.expression(state, n, raw)

    def check_sequencing(self, state, n, raw):
        """Refuse a full expression whose result the order of evaluation may change (C11 6.5p2, 6.5.2.2p10).

        * two writes, or a write and another access of the same object, not separated by a sequence point
          (``x + x++``, ``a[i] = i++``, ``x = x++``) — undefined;
        * a call whose callee may write an object another operand reads without a sequence point between them
          (``g_x + (rd(), 0U)``) — indeterminately sequenced;
        * a macro that expands to a write or a call inside a larger expression — the text above does not show it.
        """
        nodes = self.nodes_of(n, raw)
        if raw is self.fn_raw:
            # Without a write, a call or a macro nothing below can refuse (R2c: most conditions are plain reads).
            plain = self.walks.get(("plain", n.start_byte, n.end_byte, n.type))
            if plain is None:
                plain = self.walks[("plain", n.start_byte, n.end_byte, n.type)] = not any(
                    x.type in _SIDE_EFFECTS or (x.type == "identifier" and _text(x, raw) in self.macro_status)
                    for x in nodes)
            if plain:
                return
        writes = [x for x in nodes if x.type in {"assignment_expression", "update_expression"}]
        idents = [x for x in nodes if x.type == "identifier" and not (
            x.parent is not None and x.parent.type == "call_expression" and x.parent.child_by_field_name("function") == x)]
        # Objects whose address this very expression hands out (``&b``, a decaying local array): a callee or a
        # pointer write in the same expression may reach them (R2b review round 2 B).
        escaping = {self.resolve_alias(_text(x, raw)) for x in idents
                    if (_address_parent(x) is not None)
                    or ((self.lookup(_text(x, raw)) or {}).get("array")
                        and not (x.parent is not None and x.parent.type == "subscript_expression"
                                 and x.parent.child_by_field_name("argument") == x))}

        def target(w):
            node = w.child_by_field_name("left" if w.type == "assignment_expression" else "argument")
            base = cpc._base_identifier(node, raw) if node is not None else ""
            return self.resolve_alias(base) if base else ""

        def through_pointer(name):
            """A write target that is not a named object (``*p``, ``p[i]`` on a pointer, an unknown name)."""
            if not name:
                return True
            info = self.lookup(name)
            if info is not None and not info.get("extern"):
                # ``PT q`` (``typedef U8 *PT``) resolves to no scalar type: it may be a pointer (round 4 C2)
                return bool(info.get("pointer")) or (info.get("type") is None and not info.get("array"))
            return name not in self.globals and name not in self.arrays

        def reachable(name):
            info = self.lookup(name)
            if info is not None and not info.get("extern"):
                key = info.get("key", "")
                return key in state.escaped or name in escaping or name in self.body_address_names
            return name in self.arrays or name in self.address_taken or name in escaping or (
                name not in self.globals and name in (self.scope.get("unresolved_globals") or {}))

        def inside(a, b):
            return b.start_byte <= a.start_byte and a.end_byte <= b.end_byte and _key(a) != _key(b)

        for i, w1 in enumerate(writes):
            t1 = target(w1)
            p1 = through_pointer(t1)
            for w2 in writes[i + 1:]:
                nested = inside(w2, w1) or inside(w1, w2)
                t2 = target(w2)
                p2 = through_pointer(t2)
                if nested and ((t1 and t1 == t2) or (p1 and (p2 or reachable(t2))) or (p2 and reachable(t1))):
                    raise Unsupported("unsequenced_side_effects")
                if not nested and not _sequenced_apart(w1, w2, raw):
                    raise Unsupported("unsequenced_side_effects")
            if _key(w1) == _key(n):
                continue
            for x in idents:
                if inside(x, w1) or _sequenced_apart(x, w1, raw):
                    continue
                name = self.resolve_alias(_text(x, raw))
                if (not p1 and name == t1) or (p1 and reachable(name)):
                    raise Unsupported("unsequenced_side_effects")
        plain_target = None
        if n.type == "assignment_expression":
            # The object the assignment stores to (``g``, ``arr[i]``, ``s.f``): its base name designates storage and
            # the store is sequenced after the call — only the index expressions inside are reads.
            base = _unwrap(n.child_by_field_name("left"))
            while base is not None and base.type in {"subscript_expression", "field_expression"} \
                    and not any(ch.type == "->" for ch in base.children):
                base = _unwrap(base.child_by_field_name("argument"))
            if base is not None and base.type == "identifier":
                plain_target = _key(base)
        for c in nodes:
            if c.type != "call_expression":
                continue
            f = c.child_by_field_name("function")
            callee = _text(f, raw) if f is not None and f.type == "identifier" else "<indirect>"
            if callee in self.macro_status:
                if self.macro_effectful(callee) and _key(c) != _key(n):
                    # Even ``g = INC(g)``: the expansion may write what the assignment writes (review W2).
                    raise Unsupported("macro_side_effect_in_expression:" + callee)
                continue
            if f is not None and f.type == "parenthesized_expression":
                inner = _named(f)
                args = _named(c.child_by_field_name("arguments")) if c.child_by_field_name("arguments") is not None else []
                if len(inner) == 1 and inner[0].type in {"identifier", "type_identifier"} and len(args) == 1 \
                        and isinstance(self.type_of(_text(inner[0], raw)), dict):
                    continue  # ``(T)(x)`` is a cast
                callee = "<indirect>"  # ``(*fp)()`` / ``(fp)()``: unknown code (round 3 C5)
            for x in idents:
                if inside(x, c) or _key(x) == plain_target or _sequenced_apart(x, c, raw):
                    continue
                if self.call_may_write(callee, self.resolve_alias(_text(x, raw)), state, escaping):
                    raise Unsupported("call_unsequenced_with_access:" + callee)
        for x in idents:
            name = _text(x, raw)
            if name in self.macro_status and name not in self.macro_params and self.macro_effectful(name) \
                    and _key(x) != _key(n):
                raise Unsupported("macro_side_effect_in_expression:" + name)
        # What a non-constant macro reads or does is not in this tree. Where the order of evaluation matters — a
        # write or call below the top of the expression — refuse instead of reasoning about text (round 3 C2/C3).
        root = _unwrap(n)
        top = {_key(n), _key(root)}
        if root.type == "assignment_expression" and _unwrap(root.child_by_field_name("right")) is not None:
            left = root.child_by_field_name("left")
            # The left operand's value computations (an index) are unsequenced with the right operand (C11 6.5.16p3):
            # the right side is a safe top only when the left one hides nothing (round 4 C1).
            if not any(x.type == "identifier" and _text(x, raw) in self.macro_status and not self.macro_constant(_text(x, raw))
                       for x in _walk(left)):
                top.add(_key(_unwrap(root.child_by_field_name("right"))))
        nested = [x for x in nodes if _key(x) not in top and (
            x.type in {"assignment_expression", "update_expression", "gnu_asm_expression"}
            or (x.type == "call_expression" and not self.is_cast_call(x, raw) and not self.pure_macro_call(x, raw)))]
        if nested:
            for x in nodes:
                name = _text(x, raw) if x.type == "identifier" else ""
                if name in self.macro_status and not self.macro_constant(name) and not self.transparent_macro(name):
                    raise Unsupported("macro_in_order_dependent_expression:" + name)

    def nodes_of(self, n, raw):
        """``list(_walk(n))`` — cached for the function's own text (its buffer outlives every vector)."""
        if raw is not self.fn_raw:
            return list(_walk(n))
        key = (n.start_byte, n.end_byte, n.type)
        nodes = self.walks.get(key)
        if nodes is None:
            nodes = self.walks[key] = list(_walk(n))
        return nodes

    def macro_constant(self, name):
        return self.macro_status.get(name) == "active" and name in self.constants

    def transparent_macro(self, name, depth=0):
        """A function-like macro that neither writes nor calls and reads nothing but its parameters (and constants,
        type names, other transparent macros): whatever it reads is an argument — a node of this tree."""
        if depth > 8 or name not in self.macro_params or self.macro_effectful(name):
            return False
        params = set(self.macro_params.get(name) or ())
        for t in re.findall(r"\b[A-Za-z_]\w*\b", self.fmacro_bodies.get(name) or ""):
            if t in params or t in {"sizeof"} or self.macro_constant(t) or isinstance(self.type_of(t), dict) \
                    or cpc.base_kind(t) is not None or (t in self.macro_params and self.transparent_macro(t, depth + 1)):
                continue
            return False
        return True

    def pure_macro_call(self, c, raw):
        """A function-like macro invocation whose expansion neither writes nor calls — not an effect of its own (its
        arguments' effects are nodes of this tree). Over-refusal otherwise: ``BIT(pid, 0) ^ …`` (round 4 W1)."""
        f = c.child_by_field_name("function")
        return f is not None and f.type == "identifier" and _text(f, raw) in self.macro_params \
            and not self.macro_effectful(_text(f, raw))

    def is_cast_call(self, c, raw):
        f = c.child_by_field_name("function")
        if f is None or f.type != "parenthesized_expression":
            return False
        inner = _named(f)
        args = _named(c.child_by_field_name("arguments")) if c.child_by_field_name("arguments") is not None else []
        return len(inner) == 1 and inner[0].type in {"identifier", "type_identifier"} and len(args) == 1 \
            and isinstance(self.type_of(_text(inner[0], raw)), dict)

    def macro_text_closure(self, name, depth=0, seen=None):
        """The text of a macro and of every macro it mentions (transitively) — what an expansion may contain."""
        seen = set() if seen is None else seen
        if name in seen or depth > 8:
            return ""
        seen.add(name)
        body = (self.scope.get("function_like_macro_bodies") or {}).get(name) or (self.scope.get("macro_bodies") or {}).get(name) or ""
        parts = [body]
        for inner in re.findall(r"\b[A-Za-z_]\w*\b", body):
            if inner in self.macro_status:
                parts.append(self.macro_text_closure(inner, depth + 1, seen))
        return " ".join(parts)

    def prescan(self):
        """Refusals that do not depend on the path taken (a branch not executed here still changes the program):
        a macro name used as a declared name (C replaces it there too — round 3 C8); a multi-statement macro in an
        unbraced body (``if (c) while (x) SET_BOTH;`` runs the second statement unconditionally — round 3 C4); an
        ``else`` that would bind to an ``if`` inside a macro expansion (dangling else, at any depth); a macro the
        unit defines only *after* this function (at the function the name is not yet a macro — round 4 C7). The same
        rules apply inside every statement-macro expansion (round 4 C5)."""
        body = self.fn.child_by_field_name("body")
        from generators.mcdc_design import _function_name
        _name, fdecl = _function_name(self.fn, self.raw)
        params = fdecl.child_by_field_name("parameters") if fdecl is not None else None
        for p in (_named(params) if params is not None else []):
            d = p.child_by_field_name("declarator")
            if d is not None and cpc._declared_name(d, self.raw) in self.macro_status:
                raise Unsupported("macro_named_declarator:" + cpc._declared_name(d, self.raw))
        if body is not None:
            self.prescan_nodes([body], self.raw, 0)

    def defined_after_function(self, name):
        d = (self.scope.get("pp_bodies") or {}).get(name)
        return bool(d) and d.get("file") == self.scope.get("path") and int(d.get("pos") or 0) > self.fn.start_byte

    def prescan_nodes(self, roots, raw, depth):
        if depth > 8:
            raise Unsupported("macro_expansion_depth")
        for root in roots:
            for n in _walk(root):
                if n.type == "identifier" and self.defined_after_function(_text(n, raw)):
                    raise Unsupported("macro_defined_after_function:" + _text(n, raw))
                if n.type == "declaration":
                    for d in n.named_children:
                        if d.type in {"init_declarator", "identifier", "array_declarator", "pointer_declarator"}:
                            target = d.child_by_field_name("declarator") if d.type == "init_declarator" else d
                            name = cpc._declared_name(target, raw) if target is not None else ""
                            if name in self.macro_status:
                                raise Unsupported("macro_named_declarator:" + name)
                if n.type == "expression_statement" and len(_named(n)) == 1:
                    found = self.macro_statements(_named(n)[0], raw)
                    if found is not None:
                        if len(found[1]) > 1 and n.parent is not None \
                                and n.parent.type not in {"compound_statement", "case_statement"}:
                            raise Unsupported("multi_statement_macro_in_unbraced_body:" + found[0])
                        self.prescan_nodes(found[1], found[2], depth + 1)
                if n.type == "if_statement" and n.child_by_field_name("alternative") is not None:
                    tail = _unbraced_tail(n.child_by_field_name("consequence"))
                    if tail is not None and tail.type == "expression_statement" and len(_named(tail)) == 1:
                        found = self.macro_statements(_named(tail)[0], raw)
                        if found is not None and len(found[1]) == 1 and _open_if(found[1][0]):
                            raise Unsupported("dangling_else_in_macro:" + found[0])

    def macro_effectful(self, name, depth=0):
        """May expanding ``name`` write or call a function (transitively through other macros)?"""
        if depth > 8 or self.macro_status.get(name) != "active":
            return True
        body = self.fmacro_bodies.get(name) if name in self.macro_params else self.macro_bodies.get(name)
        if body is None:
            return True
        fx = cpc.macro_side_effects(body)
        if fx["writes"]:
            return True
        if any(c not in {"sizeof", "defined"} and (c not in self.macro_status or self.macro_effectful(c, depth + 1))
               and not isinstance(self.type_of(c), dict) for c in fx["calls"]):
            return True
        # a macro it merely mentions is expanded too (``#define WRAP INNER`` — round 3 C2)
        return any(t != name and t in self.macro_status and self.macro_effectful(t, depth + 1)
                   for t in re.findall(r"\b[A-Za-z_]\w*\b", body))

    def call_may_write(self, callee, obj, state, escaping=frozenset()):
        """Could a call to ``callee`` change the object an identifier ``obj`` names here?"""
        closure = self.closure.get(callee)
        info = self.lookup(obj)
        escaped = False
        if info is not None and not info.get("extern"):
            key = info.get("key", "")
            escaped = key in state.escaped or obj in escaping
            if key in self.static_keys and (closure is None or closure.get("unknown_callees")
                                            or self.function_name in (closure.get("reaches") or ())):
                return True  # the callee may re-enter this function (round 2 A)
            if not escaped:
                return False  # a parameter or local no pointer can reach
        elif obj not in self.globals and obj not in self.arrays and obj not in (self.scope.get("unresolved_globals") or {}):
            return False  # a constant, an enumerator, a type name
        if closure is None or closure.get("unknown_callees"):
            return True
        if obj in (closure.get("writes") or ()):
            return True
        pointer = closure.get("pointer_write") or any(w not in self.globals and w not in self.arrays
                                                      for w in closure.get("writes") or ())
        reachable = escaped or obj in self.arrays or obj in self.address_taken or obj in escaping or (
            obj not in self.globals and obj not in self.arrays)
        return bool(pointer and reachable)

    def resolve_alias(self, name, depth=0):
        """``GX`` with ``#define GX g_x`` (or ``(g_x)``) names ``g_x`` — the object a sequencing check must compare."""
        while depth < 8 and self.macro_status.get(name) == "active" and name not in self.macro_params:
            m = re.fullmatch(r"[\s(]*([A-Za-z_]\w*)[\s)]*", self.macro_bodies.get(name, ""))
            if not m:
                break
            name, depth = m.group(1), depth + 1
        return name

    def expression(self, state, n, raw, depth=0) -> _Val:
        self.tick()
        if depth > 200:
            raise Unsupported("expression_depth_budget")
        if self.watch is not None and raw is self.fn_raw:
            spec = self.watch.get((n.start_byte, n.end_byte, n.type))
            if spec is not None:
                self.record_decision(state, spec)
        k = n.type
        if k == "parenthesized_expression":
            inner = _named(n)
            if len(inner) != 1:
                raise Unsupported("unsupported_parenthesized_expression")
            return self.expression(state, inner[0], raw, depth + 1)
        if k == "number_literal":
            try:
                value, t = cpc.literal(_text(n, raw), self.widths)
            except cpc.Unresolved as exc:
                return _Val(Unknown(str(exc)), None)
            if cpc.is_float(t):
                return _Val(Unknown("floating_point_unmodeled"), t)
            return _Val(value, t)
        if k == "char_literal":
            body = _text(n, raw)
            m = re.fullmatch(r"'([ -&(-\[\]-~])'", body)  # printable ASCII except ' and \ (round 4 C8)
            return _Val(ord(m.group(1)), self.int_t) if m else _Val(Unknown("char_literal_unmodeled"), self.int_t)
        if k in {"true", "false"}:
            return _Val(Unknown("bool_keyword_unmodeled"), None)
        if k == "identifier":
            return self.read_identifier(state, _text(n, raw), n, raw, depth)
        if k == "cast_expression":
            t = self.type_of(_text(n.child_by_field_name("type"), raw))
            inner = self.expression(state, n.child_by_field_name("value"), raw, depth + 1)
            return self.cast(inner, t)
        if k == "unary_expression":
            op = _op(n, raw)
            arg = self.expression(state, n.child_by_field_name("argument"), raw, depth + 1)
            return self.unary(op, arg, state)
        if k == "binary_expression":
            return self.binary(state, n, raw, depth)
        if k == "conditional_expression":
            return self.conditional(state, n, raw, depth)
        if k == "comma_expression":
            self.expression(state, n.child_by_field_name("left"), raw, depth + 1)
            return self.expression(state, n.child_by_field_name("right"), raw, depth + 1)
        if k == "assignment_expression":
            return self.assign(state, n, raw, depth)
        if k == "update_expression":
            return self.update(state, n, raw, depth)
        if k == "subscript_expression":
            target = self.lvalue(state, n, raw, depth)
            return self.read_target(state, target)
        if k == "field_expression":
            base = self.expression_base_effects(state, n, raw, depth)
            return _Val(Unknown("field_unmodeled:" + base), None)
        if k == "pointer_expression":
            op = _text(n, raw).lstrip()[:1]
            if op == "&":
                self.address_of(state, n.child_by_field_name("argument"), raw, depth)
                return _Val(Unknown("address_value"), None)
            self.expression(state, n.child_by_field_name("argument"), raw, depth + 1)
            return _Val(Unknown("pointer_dereference"), None)
        if k == "call_expression":
            return self.call(state, n, raw, depth)
        if k in {"sizeof_expression", "alignof_expression"}:
            return _Val(Unknown("sizeof_unmodeled"), None)
        if k == "string_literal" or k == "concatenated_string":
            return _Val(Unknown("string_literal"), None)
        if k == "gnu_asm_expression":
            self.havoc_everything(state, "inline_assembly", locals_too=True)  # ``: "=r"(x)`` writes a local
            return _Val(Unknown("inline_assembly"), None)
        if k == "compound_literal_expression" or k == "initializer_list":
            inner = n.child_by_field_name("value") if k == "compound_literal_expression" else n
            if inner is not None:
                self.initializer(state, inner, raw, depth + 1)
            return _Val(Unknown("aggregate_value"), None)
        raise Unsupported("unsupported_expression:" + k)

    def expression_base_effects(self, state, n, raw, depth):
        """Evaluate the operands of a member access for their side effects; return a label for the reason."""
        arg = n.child_by_field_name("argument")
        if arg is not None and arg.type not in {"identifier"}:
            self.expression(state, arg, raw, depth + 1)
        return _text(arg, raw)[:40] if arg is not None else "?"

    # identifiers
    def read_identifier(self, state, name, n, raw, depth):
        if name in self.macro_status:
            if name in self.macro_params:
                return _Val(Unknown("function_like_macro_without_call:" + name), None)
            return self.read_macro(state, name, raw, depth)
        info = self.lookup(name)
        if info is not None and not info.get("extern"):
            if info.get("array"):
                # The array decays to a pointer to its first element: from here on a pointer may reach it.
                state.escaped.add(info["key"])
                return _Val(Unknown("array_value:" + name), None)
            if info.get("pointer"):
                return _Val(state.store.get(info["key"], Unknown("pointer_value:" + name)), None)
            value = state.store.get(info["key"], Unknown("unbound:" + name))
            if info.get("volatile"):
                value = Unknown("volatile_object:" + name)
            return _loaded(value, info["type"])
        constants = self.constants
        if name in constants:
            c = constants[name]
            if cpc.is_float(c["type"]):
                return _Val(Unknown("floating_point_unmodeled"), c["type"])
            return _Val(c["value"], c["type"])
        if name in self.globals:
            g = self.globals[name]
            return _loaded(self.read_key(state, name, name, g["type"], g.get("volatile")), g["type"])
        if name in self.arrays:
            return _Val(Unknown("array_value:" + name), None)
        return _Val(Unknown(self.unresolved_reason(name)), None)

    def unresolved_reason(self, name):
        if name in (self.scope.get("unresolved_globals") or {}):
            return f"global_unmodeled:{name}:{self.scope['unresolved_globals'][name]}"
        if name in (self.scope.get("unresolved_constants") or {}):
            return f"constant_unresolved:{name}:{self.scope['unresolved_constants'][name]}"
        return "identifier_unresolved:" + name

    def macro_node(self, text):
        """Parse a macro expansion as one expression (cached). None if it is not a single operand."""
        if text in self.expansions:
            return self.expansions[text]
        node, eraw = cpc._parse_body(text, self.parser)
        result = (node, eraw) if node is not None and cpc.self_delimiting(node) else (None, eraw)
        self.expansions[text] = result
        return result

    def read_macro(self, state, name, raw, depth):
        constants = self.constants
        if self.macro_status.get(name) == "active" and name in constants:
            c = constants[name]
            if cpc.is_float(c["type"]):
                return _Val(Unknown("floating_point_unmodeled"), c["type"])
            return _Val(c["value"], c["type"])
        reason = ""
        if self.macro_status.get(name) != "active" or name not in self.macro_bodies:
            reason = "macro_body_unknown:" + name
        elif "#" in self.macro_bodies[name] or depth > 40:
            reason = "macro_expansion_unmodeled:" + name
        else:
            node, eraw = self.macro_node(self.macro_bodies[name])
            if node is None:
                reason = "macro_body_not_an_operand:" + name
        if reason:
            if self.macro_effectful(name):
                # What we cannot evaluate may still write: its effects must not vanish (R2b review round 2 A).
                self.havoc_everything(state, reason, locals_too=True)
            return _Val(Unknown(reason), None)
        self.check_sequencing(state, node, eraw)  # the expansion's own order (``g_x + g_x++``; round 2 B)
        return self.expression(state, node, eraw, depth + 1)

    def cast(self, inner, t):
        if isinstance(t, Unknown):
            return _Val(t, None)
        if cpc.is_float(t) or cpc.is_float(inner.t):
            return _Val(Unknown("floating_point_unmodeled"), t)
        if isinstance(inner.v, Unknown):
            # The cast changes the type, not the value: keep the interval the operand was in (``(S32)s16`` is 16 bits
            # wide); a narrowing cast is caught where it is read (the interval then leaves the type's range).
            return _Val(inner.v, t, self.operand_range(inner))
        if inner.t is None:
            return _Val(Unknown("value_type_unresolved"), t)
        return _Val(self.convert_to(inner, t), t)

    def unary(self, op, arg, state=None):
        if arg.t is None and op == "-" and state is not None:
            tag = _untyped_overflow_tag((arg,), self.int_t["bits"])  # its type (and signedness) is unknown: C2
            if tag:
                state.possible_ub.add(tag)
        if arg.t is None or cpc.is_float(arg.t):
            return _Val(arg.v if isinstance(arg.v, Unknown) else Unknown("floating_point_unmodeled" if cpc.is_float(arg.t) else "value_type_unresolved"),
                        self.int_t if op == "!" else None)
        rt = self.int_t if op == "!" else cpc.promote(arg.t, self.widths)
        if isinstance(arg.v, Unknown):
            span = self.note_possible_overflow(state, op, (arg,), rt) if op == "-" and state is not None else None
            return _Val(arg.v, rt, span)
        if arg.t.get("enum") and op != "!":
            return self.enum_dual(lambda c: cpc.arith(op, None, (arg.v, c), self.widths), rt)
        value = self.lift(cpc.arith, op, None, (arg.v, arg.t), self.widths)
        return _Val(value[0] if isinstance(value, tuple) else value, rt)

    def operand_range(self, x):
        """What an operand may hold: its value when known, its type's range when not (an enumeration object: every
        permitted underlying type). ``None`` when it is not an integer."""
        if not isinstance(x.v, Unknown):
            return (x.v, x.v) if isinstance(x.v, int) and not isinstance(x.v, bool) else None
        if not isinstance(x.t, dict) or cpc.is_float(x.t):
            return None
        if x.t.get("enum"):
            ranges = [cpc.type_range(c) for c in self.enum_candidates()]
            return min(r[0] for r in ranges), max(r[1] for r in ranges)
        lo, hi = cpc.type_range(x.t)
        span = x.r
        # Trusted only inside this type's range: a conversion that kept every value in it preserved them; one that did
        # not (``U8 = s16`` holding -5) may have wrapped, and the type's range is all that is left.
        if span is not None and lo <= span[0] <= span[1] <= hi:
            return span
        return lo, hi

    def note_possible_overflow(self, state, op, operands, rt):
        """An unknown operand in *signed* arithmetic may overflow on the real run — undefined (C11 6.5p5), after which
        nothing the function does is determined. Disclosed as possible UB unless the operands' ranges prove it cannot
        (``U8 + U8`` never overflows a 16-bit int; ``S16 - S16`` can). Known operands are checked exactly by `cpc.arith`."""
        if not isinstance(rt, dict) or not rt.get("signed") or not any(isinstance(x.v, Unknown) for x in operands):
            return None
        ranges = [self.operand_range(x) for x in operands]
        lo, hi = cpc.type_range(rt)
        if any(r is None for r in ranges):
            may = True
            span = None
        elif len(ranges) == 1:
            may = -ranges[0][0] > hi                       # ``-x`` at the type's minimum
            span = (-ranges[0][1], -ranges[0][0])
        else:
            (a0, a1), (b0, b1) = ranges
            span = None
            if op in {"+", "-", "*"}:
                f = {"+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b}[op]
                ext = [f(a, b) for a in (a0, a1) for b in (b0, b1)]
                may = min(ext) < lo or max(ext) > hi
                span = (min(ext), max(ext))
            elif op == "<<":                                # a negative left operand, or bits shifted past the sign
                may = a0 < 0 or (a1 << max(0, min(b1, rt["bits"]))) > hi
            elif op in {"/", "%"}:                          # ``INT_MIN / -1``
                may = a0 <= lo and b0 <= -1 <= b1
            else:
                may = False
        if may:
            state.possible_ub.add("signed_overflow_unknown_operand")
            return None
        return span

    def enum_dual(self, compute, rt):
        """Result of an operation on an enumeration object under every permitted underlying type."""
        results = set()
        for c in self.enum_candidates():
            try:
                v, t = compute(c)
            except cpc.Unresolved:
                return _Val(Unknown("enum_object_type_implementation_defined"), rt)
            results.add((v, t["kind"], t["signed"]))
        if len(results) == 1:
            v, _kind, _signed = next(iter(results))
            return _Val(v, rt)
        return _Val(Unknown("enum_object_type_implementation_defined"), rt)

    def binary(self, state, n, raw, depth):
        op = _op(n, raw)
        left = self.expression(state, n.child_by_field_name("left"), raw, depth + 1)
        right_node = n.child_by_field_name("right")
        if op in {"&&", "||"}:
            lt = self.truth(left)
            if lt is not None:
                if (op == "&&" and not lt) or (op == "||" and lt):
                    return _Val(0 if op == "&&" else 1, self.int_t)
                right = self.expression(state, right_node, raw, depth + 1)
                rt = self.truth(right)
                return _Val(Unknown(right.v.reason) if rt is None else int(rt), self.int_t)
            # Unknown left operand: the right operand may or may not run.
            if any(x.type in _SIDE_EFFECTS for x in _walk(right_node)) or self.has_macro_call(right_node, raw):
                raise Unsupported("side_effect_under_unknown_condition")
            right = self.speculative(state, right_node, raw, depth, runs_maybe=True)
            rt = self.truth(right)
            if rt is not None and ((op == "&&" and not rt) or (op == "||" and rt)):
                return _Val(0 if op == "&&" else 1, self.int_t)
            return _Val(left.v if isinstance(left.v, Unknown) else Unknown("unknown"), self.int_t)
        right = self.expression(state, right_node, raw, depth + 1)
        return self.arith_values(op, left, right, state)

    def has_macro_call(self, n, raw):
        return any(x.type == "identifier" and _text(x, raw) in self.macro_status and
                   self.macro_status.get(_text(x, raw)) != "active" for x in _walk(n))

    def conditional(self, state, n, raw, depth):
        cond_node = n.child_by_field_name("condition")
        cond = self.expression(state, cond_node, raw, depth + 1)
        a_node, b_node = n.child_by_field_name("consequence"), n.child_by_field_name("alternative")
        truth = self.truth(cond)
        guard = self.guards.get((cond_node.start_byte, cond_node.end_byte, cond_node.type)) if raw is self.fn_raw else None
        if guard is not None:
            state.decisions.append((guard, ("outcome", truth)))
        if truth is None:
            if any(x.type in _SIDE_EFFECTS for node in (a_node, b_node) for x in _walk(node)):
                raise Unsupported("side_effect_under_unknown_condition")
            a = self.speculative(state, a_node, raw, depth, runs_maybe=True)
            b = self.speculative(state, b_node, raw, depth, runs_maybe=True)
            t = self.conditional_type(a, b)
            if not isinstance(a.v, Unknown) and not isinstance(b.v, Unknown) and isinstance(t, dict):
                va, vb = self.lift(cpc.convert, a.v, t), self.lift(cpc.convert, b.v, t)
                if not isinstance(va, Unknown) and va == vb:
                    return _Val(va, t)
            return _Val(cond.v, t if isinstance(t, dict) else None)
        chosen, other = (a_node, b_node) if truth else (b_node, a_node)
        value = self.expression(state, chosen, raw, depth + 1)
        if any(x.type in _SIDE_EFFECTS for x in _walk(other)):
            return _Val(Unknown("conditional_type_unresolved"), None)
        o = self.speculative(state, other, raw, depth)
        t = self.conditional_type(value, o) if truth else self.conditional_type(o, value)
        if not isinstance(t, dict):
            return _Val(Unknown("conditional_type_unresolved"), None)
        if isinstance(value.v, Unknown):
            return _Val(value.v, t)
        return _Val(self.lift(cpc.convert, value.v, t), t)

    def speculative(self, state, node, raw, depth, runs_maybe=False):
        """Value (and type) of an operand evaluated on a copy.

        ``runs_maybe``: the operand runs on some executions (unknown ``&&``/``||``/``?:`` condition). Anything it would
        change — a store, a havoc (a macro that expands to an assignment or call) — refuses the evaluation, since the
        copy would silently drop it (R2b review C2); what it lets escape (``&a``) is a may-fact and joins the real
        state (review C3); undefined behaviour there is only possible, and disclosed. Otherwise the operand does not
        run at all (the other arm of a decided ``?:``) and only its type is wanted."""
        probe = state.copy()
        try:
            value = self.expression(probe, node, raw, depth + 1)
        except Unsupported as exc:
            if not runs_maybe:
                return _Val(Unknown(str(exc)), None)
            if not str(exc).startswith("undefined_behavior:"):
                raise
            state.possible_ub.add("operand_under_unknown_condition")
            self.maybe_decisions(state, probe)
            return _Val(Unknown(str(exc)), None)
        if runs_maybe:
            self.maybe_decisions(state, probe)
            changed = (probe.havoc_all != state.havoc_all or probe.havoc_pointer != state.havoc_pointer
                       or probe.havoc_bases != state.havoc_bases or probe.store.keys() != state.store.keys()
                       or any(probe.store[k] is not v for k, v in state.store.items()))
            if changed:
                raise Unsupported("side_effect_under_unknown_condition")
            state.escaped |= probe.escaped
            state.possible_ub |= probe.possible_ub
        return value

    def maybe_decisions(self, state, probe):
        """(R2c) A decision inside an operand that runs on *some* executions was maybe evaluated — never an
        observation of this path, and never "not reached" either."""
        state.decisions.extend((key, ("maybe",)) for key, _obs in probe.decisions[len(state.decisions):])

    def atom_effectful(self, atom, raw):
        """(R2c) Would evaluating this condition change state? Its truth is read on a copy of the state before the
        decision runs, so a write or a call in one condition could change what a later one reads."""
        for x in _walk(atom):
            if x.type in {"assignment_expression", "update_expression", "gnu_asm_expression"}:
                return True
            if x.type == "call_expression" and not (self.is_cast_call(x, raw) or self.pure_macro_call(x, raw)):
                return True
            if x.type == "identifier" and _text(x, raw) in self.macro_status and _text(x, raw) not in self.macro_params \
                    and self.macro_effectful(_text(x, raw)):
                return True
        return False

    def record_decision(self, state, spec):
        """(R2c) Observe one evaluation of a watched decision on this path: each condition's truth in the state the
        decision starts from, which conditions the short circuit evaluates, and the outcome. A condition whose value
        the inputs do not determine (or whose evaluation is undefined) has truth ``None``; if the short circuit reaches
        it, the outcome is undetermined."""
        if state.possible_ub:
            # Undefined behaviour that depends on an unknown value may already have happened on this path: whether and
            # how the decision is reached is then not determined.
            state.decisions.append((spec["key"], ("undetermined", "possible_undefined_behavior_before_decision")))
            return
        truths, reasons = [], []
        saved, self.watch = self.watch, None
        try:
            for atom in spec["atoms"]:
                probe = state.copy()
                try:
                    v = self.expression(probe, atom, self.fn_raw)
                    truths.append(self.truth(v))
                    reasons.append(v.v.reason if isinstance(v.v, Unknown) else "")
                except Unsupported as exc:
                    truths.append(None)
                    reasons.append(str(exc))
        finally:
            self.watch = saved
        observed = [False] * len(truths)

        def visit(node):
            if node[0] == "atom":
                observed[node[1]] = True
                return truths[node[1]]
            if node[0] == "!":
                inner = visit(node[1])
                return None if inner is None else not inner
            left = visit(node[1])
            if left is None:
                return None
            if (node[0] == "&&" and not left) or (node[0] == "||" and left):
                return left
            return visit(node[2])
        outcome = visit(spec["ir"])
        if outcome is None:
            why = next((reasons[i] for i, t in enumerate(truths) if observed[i] and t is None), "") or "unknown"
            state.decisions.append((spec["key"], ("undetermined", why)))
            return
        state.decisions.append((spec["key"], ("evaluated", tuple(truths), tuple(observed), bool(outcome))))

    def conditional_type(self, a, b):
        if a.t is None or b.t is None or cpc.is_float(a.t) or cpc.is_float(b.t):
            return None
        if a.t.get("enum") or b.t.get("enum"):
            return None  # the arms' common type depends on the enumeration's underlying type (R2b review W4)
        return cpc.usual_conversion(a.t, b.t, self.widths)

    # lvalues
    def lvalue(self, state, n, raw, depth):
        """('key', key, type, volatile) | ('base', base, reason) | ('all', reason)."""
        k = n.type
        if k == "parenthesized_expression":
            inner = _named(n)
            return self.lvalue(state, inner[0], raw, depth + 1) if len(inner) == 1 else ("all", "unsupported_lvalue")
        if k == "identifier":
            name = _text(n, raw)
            if name in self.macro_status:
                if self.macro_status.get(name) != "active" or name not in self.macro_bodies or depth > 40:
                    return ("all", "write_through_unknown_macro:" + name)
                node, eraw = self.macro_node(self.macro_bodies[name])
                if node is None:
                    return ("all", "write_through_macro:" + name)
                return self.lvalue(state, node, eraw, depth + 1)
            info = self.lookup(name)
            if info is not None and not info.get("extern"):
                if info.get("array") or info.get("pointer"):
                    return ("base", info["key"], "aggregate_write:" + name)
                return ("key", info["key"], info["type"], info.get("volatile", False))
            if name in self.globals:
                g = self.globals[name]
                return ("key", name, g["type"], g.get("volatile", False))
            if name in self.arrays:
                return ("base", name, "aggregate_write:" + name)
            if name in (self.scope.get("unresolved_globals") or {}):
                return ("base", name, "unmodeled_object_written:" + name)
            return ("all", "write_to_unresolved_identifier:" + name)
        if k == "subscript_expression":
            arg, index = n.child_by_field_name("argument"), n.child_by_field_name("index")
            array = self.array_object(arg, raw, depth)
            iv = self.expression(state, index, raw, depth + 1)
            if array is None:
                # Not a directly named array object: a pointer, an array member or an array of aggregates — the
                # element written may be any object reachable through it.
                self.expression_base_effects_for_lvalue(state, arg, raw, depth)
                # ``p[i]`` is ``*(p + i)``: the element may lie outside the object ``p`` points into, as for ``p + i``
                # (R2c: clang reads ``tbl[255]`` of a 64-element buffer while the run disclosed nothing)
                state.possible_ub.add("pointer_arithmetic_untyped")
                return ("ptr", "subscript_write_through_pointer_or_aggregate")
            key, t, length, volatile = array
            if isinstance(iv.v, Unknown) or iv.t is None:
                state.possible_ub.add("index_unknown")
                return ("base", key, "index_unknown:" + (iv.v.reason if isinstance(iv.v, Unknown) else "type"))
            if length is None:
                return ("base", key, "array_length_unresolved")
            if not 0 <= iv.v < length:
                raise Unsupported("undefined_behavior:array_index_out_of_bounds")
            return ("key", f"{key}[{iv.v}]", t, volatile)
        if k == "field_expression":
            is_arrow = any(c.type == "->" for c in n.children)
            if is_arrow:
                self.expression(state, n.child_by_field_name("argument"), raw, depth + 1)
                return ("ptr", "write_through_pointer")
            arg = n.child_by_field_name("argument")
            inner = self.lvalue(state, arg, raw, depth + 1)
            if inner[0] == "key":
                return ("base", inner[1], "field_write")
            return inner
        if k == "pointer_expression":
            self.expression(state, n.child_by_field_name("argument"), raw, depth + 1)
            return ("ptr", "write_through_pointer")
        if k == "cast_expression":
            return ("ptr", "write_through_cast")
        return ("all", "unsupported_lvalue:" + k)

    def expression_base_effects_for_lvalue(self, state, arg, raw, depth):
        if arg.type != "identifier":
            self.expression(state, arg, raw, depth + 1)

    def object_base(self, name):
        info = self.lookup(name)
        if info is not None and not info.get("extern"):
            return info.get("key", "")
        if name in self.globals or name in self.arrays or name in (self.scope.get("unresolved_globals") or {}):
            return name
        return ""

    def array_object(self, arg, raw, depth):
        """(key base, element type, length, volatile) of a directly named array; None otherwise."""
        while arg.type == "parenthesized_expression" and len(_named(arg)) == 1:
            arg = _named(arg)[0]
        if arg.type != "identifier":
            return None
        name = _text(arg, raw)
        if name in self.macro_status:
            if self.macro_status.get(name) != "active" or name not in self.macro_bodies or depth > 40:
                return None
            node, eraw = self.macro_node(self.macro_bodies[name])
            return self.array_object(node, eraw, depth + 1) if node is not None else None
        info = self.lookup(name)
        if info is not None and not info.get("extern"):
            if info.get("array"):
                return info["key"], info["type"], info["length"], info.get("volatile", False)
            return None
        if name in self.arrays:
            a = self.arrays[name]
            return name, a["type"], a["length"], a.get("volatile", False)
        return None

    def read_target(self, state, target):
        if target[0] != "key":
            return _Val(Unknown(target[-1] if target[0] in ("all", "ptr") else target[2]), None)
        _, key, t, volatile = target
        base = key.split("[", 1)[0]
        if volatile:
            return _Val(Unknown("volatile_object:" + base), t)
        if key in state.store:
            return _loaded(state.store[key], t)
        if base in self.arrays and not base.startswith("@"):
            a = self.arrays[base]
            if a.get("values") is not None and a.get("const"):
                index = int(key[len(base) + 1:-1])
                return _Val(a["values"][index], t)
        if base.startswith("@"):
            return _Val(Unknown(state.havoc_bases.get(base, "uninitialized_local")), t)
        return _Val(self.initial(state, key, base, t), t)

    def address_of(self, state, arg, raw, depth):
        """``&x``: x escapes — whatever an unknown write may reach includes it from now on."""
        target = self.lvalue(state, arg, raw, depth + 1) if arg is not None else ("all", "address_of")
        if target[0] == "key":
            base = target[1].split("[", 1)[0]
            state.escaped.add(base)
            return base
        if target[0] == "base":
            state.escaped.add(target[1])
            return target[1]
        return ""

    def assign(self, state, n, raw, depth):
        op = _op(n, raw)
        left_node, right_node = n.child_by_field_name("left"), n.child_by_field_name("right")
        target = self.lvalue(state, left_node, raw, depth + 1)
        right = self.expression(state, right_node, raw, depth + 1)
        if op == "=":
            value = right
        else:
            current = self.read_target(state, target)
            value = self.arith_values(op[:-1], current, right, state)
        if target[0] == "key":
            self.store(state, target, value)
            stored = state.store[target[1]]
            return _loaded(stored, target[2])
        self.store(state, target, value)
        return _Val(Unknown(target[-1] if target[0] in ("all", "ptr") else target[2]), None)

    def arith_values(self, op, left, right, state):
        """One binary operator on evaluated operands (arithmetic, bitwise, shift, comparison)."""
        comparison = op in {"<", "<=", ">", ">=", "==", "!="}
        right_known = not isinstance(right.v, Unknown) and isinstance(right.t, dict) and not cpc.is_float(right.t)
        # Undefined whatever the other operand holds (C11 6.5.5p5, 6.5.7p3): refused even when it is unknown.
        if right_known and op in {"/", "%"} and right.v == 0:
            raise Unsupported("undefined_behavior:division_by_zero")
        if right_known and op in {"<<", ">>"} and (right.v < 0 or (
                isinstance(left.t, dict) and not cpc.is_float(left.t) and right.v >= cpc.promote(left.t, self.widths)["bits"])):
            raise Unsupported("undefined_behavior:shift_count_out_of_range")
        if not right_known and op in {"/", "%", "<<", ">>"}:
            # An unknown divisor or shift count may be undefined on the real run: disclosed, not proven absent.
            state.possible_ub.add("division_by_unknown" if op in {"/", "%"} else "shift_by_unknown")
        if ((left.t is None or right.t is None) and op in {"+", "-", "*", "/", "%", "<<"}
                and not (cpc.is_float(left.t) or cpc.is_float(right.t))):
            # An operand whose type is unknown (a call's return value, an unresolved macro, ``*p``) may be a signed
            # int that overflows: not proven otherwise, so disclosed (review round 6 C2).
            tag = _untyped_overflow_tag((left, right), self.int_t["bits"])
            if tag:
                state.possible_ub.add(tag)
        if left.t is None or right.t is None or cpc.is_float(left.t) or cpc.is_float(right.t):
            reason = next((x.v.reason for x in (left, right) if isinstance(x.v, Unknown)),
                          "floating_point_unmodeled" if cpc.is_float(left.t) or cpc.is_float(right.t) else "value_type_unresolved")
            return _Val(Unknown(reason), self.int_t if comparison else None)
        if op in {"<<", ">>"}:
            rt = cpc.promote(left.t, self.widths)
        elif comparison:
            rt = self.int_t
        else:
            rt = cpc.usual_conversion(left.t, right.t, self.widths)
        span = self.note_possible_overflow(state, op, (left, right), rt) if not comparison else None
        for x in (left, right):
            if isinstance(x.v, Unknown):
                # A result that provably stayed in range keeps its interval (``(S32)a * 1000L + b`` stays checkable).
                return _Val(x.v, rt, span)
        if left.t.get("enum") or right.t.get("enum"):
            return self.enum_dual(lambda c: cpc.arith(op, (left.v, c if left.t.get("enum") else left.t),
                                                      (right.v, c if right.t.get("enum") else right.t), self.widths), rt)
        value = self.lift(cpc.arith, op, (left.v, left.t), (right.v, right.t), self.widths)
        if isinstance(value, Unknown):
            return _Val(value, rt)
        return _Val(value[0], value[1])

    def update(self, state, n, raw, depth):
        op = _op(n, raw)
        arg = n.child_by_field_name("argument")
        prefix = n.children and n.children[0].type in {"++", "--"}
        target = self.lvalue(state, arg, raw, depth + 1)
        current = self.read_target(state, target)
        one = _Val(1, self.int_t)
        new = self.arith_values("+" if op == "++" else "-", current, one, state)
        if target[0] == "key":
            self.store(state, target, new)
            return _loaded(state.store[target[1]], target[2]) if prefix else current
        self.store(state, target, new)
        return _Val(Unknown(target[-1] if target[0] in ("all", "ptr") else target[2]), None)

    # calls
    def call(self, state, n, raw, depth):
        f, args = n.child_by_field_name("function"), n.child_by_field_name("arguments")
        arg_nodes = _named(args) if args is not None else []
        if f is not None and f.type == "parenthesized_expression":
            inner = _named(f)
            if len(inner) == 1 and inner[0].type in {"identifier", "type_identifier"} and len(arg_nodes) == 1:
                t = self.type_of(_text(inner[0], raw))
                if isinstance(t, dict):  # ``(T)(x)`` is a cast exactly when ``T`` names a type
                    return self.cast(self.expression(state, arg_nodes[0], raw, depth + 1), t)
        name = _text(f, raw) if f is not None and f.type == "identifier" else "<indirect>"
        if name in self.macro_status:
            return self.macro_call(state, name, arg_nodes, raw, depth)
        info = self.closure.get(name)
        # Declared nowhere we can read, after a missing include: it may be a macro from that header, which can write a
        # parameter or local in place (``RESET(x)``, R2c review round 1 C2) — or drop its arguments (``ASSERT(c)`` as
        # ``((void)0)``): a decision in them is maybe evaluated, never observed (round 2 N-C1).
        maybe_macro = info is None and self.lookup(name) is None and name not in (self.params or {}) \
            and name not in (self.scope.get("prototypes") or ()) and bool(self.scope.get("missing_includes"))
        if maybe_macro or (name.startswith("__builtin_") and name not in _EVALUATING_BUILTINS):
            # (review round 3 W2) ``__builtin_constant_p(x)`` does not evaluate ``x``: a decision there is maybe run
            self.unmodeled_macro_arguments(state, arg_nodes, raw, depth)
        else:
            for a in arg_nodes:
                self.argument(state, a, raw, depth)
        if info is None or name in (self.params or {}) or self.lookup(name) is not None:
            self.havoc_everything(state, "unknown_callee:" + name, locals_too=maybe_macro)
            return _Val(Unknown("call_return_value:" + name), None)
        if self.function_name and self.function_name in (info.get("reaches") or ()):
            self.havoc_statics(state, f"recursion_through:{name}")  # the callee may re-enter this function
        writes = sorted(info.get("writes") or ())
        # A written name that is not a modeled scalar or array object (a pointer, a struct with pointer members)
        # may be written *through* — to an object the closure cannot name.
        opaque = [w for w in writes if w not in self.globals and w not in self.arrays]
        if info.get("unknown_callees"):
            first = sorted(info["unknown_callees"])[0]
            self.havoc_everything(state, f"callee_effects_unknown:{name}:{first}")
        else:
            for w in writes:
                self.havoc_base(state, w, f"written_by_callee:{name}:{w}")
            if info.get("pointer_write") or opaque:
                why = "pointer_write" if info.get("pointer_write") else "writes_through:" + opaque[0]
                self.havoc_pointer_targets(state, f"callee_pointer_write:{name}:{why}")
        return _Val(Unknown("call_return_value:" + name), None)

    def argument(self, state, a, raw, depth):
        """Evaluate an argument. Passing an address (``&x``, a decayed array, a cast of either) only marks the object
        escaped; whether the callee writes through it is the call's question (``pointer_write`` in its closure)."""
        self.expression(state, a, raw, depth + 1)

    def macro_call(self, state, name, arg_nodes, raw, depth):
        body = self.fmacro_bodies.get(name)
        params = self.macro_params.get(name)
        if self.macro_status.get(name) != "active" or body is None or params is None or "..." in params \
                or "#" in body or len(params) != len(arg_nodes) or depth > 40:
            self.unmodeled_macro_arguments(state, arg_nodes, raw, depth)
            self.havoc_everything(state, "macro_call_unmodeled:" + name, locals_too=True)
            return _Val(Unknown("macro_call_unmodeled:" + name), None)
        text = _substitute(body, params, [_text(a, raw) for a in arg_nodes])
        node, eraw = self.macro_node(text)
        if node is None:
            self.unmodeled_macro_arguments(state, arg_nodes, raw, depth)
            self.havoc_everything(state, "macro_call_not_an_expression:" + name, locals_too=True)
            return _Val(Unknown("macro_call_not_an_expression:" + name), None)
        # ``DBL(g_x++)`` → ``((g_x++)+(g_x++))``: the expansion is what runs (R2b review round 2 B).
        self.check_sequencing(state, node, eraw)
        return self.expression(state, node, eraw, depth + 1)

    def unmodeled_macro_arguments(self, state, arg_nodes, raw, depth):
        """Arguments of a macro whose expansion we cannot see: their effects are kept, but whether they run at all
        (``#define DBG(...)`` drops them, ``report(#c)`` only stringifies) is unknown — a decision inside one was maybe
        evaluated, never observed (R2c review round 1 C1)."""
        mark = len(state.decisions)
        for a in arg_nodes:
            self.argument(state, a, raw, depth)
        state.decisions[mark:] = [(key, ("maybe",)) for key, _obs in state.decisions[mark:]]

    def macro_statements(self, n, raw):
        """(name, statements, raw) when ``n`` — the whole expression of a statement — is a macro invocation whose
        expansion is statements rather than one expression (``RESET();`` → ``{...}``); None otherwise."""
        name = _text(n, raw) if n.type == "identifier" else ""
        args: list = []
        if n.type == "call_expression":
            f = n.child_by_field_name("function")
            if f is None or f.type != "identifier":
                return None
            name = _text(f, raw)
            args = _named(n.child_by_field_name("arguments")) if n.child_by_field_name("arguments") is not None else []
            body, params = self.fmacro_bodies.get(name), self.macro_params.get(name)
        elif n.type == "identifier":
            body, params = self.macro_bodies.get(name), []
        else:
            return None
        if name not in self.macro_status or self.macro_status.get(name) != "active" or body is None or params is None:
            return None
        if "#" in body or "..." in params or len(params) != len(args):
            return None
        text = _substitute(body, params, [_text(a, raw) for a in args])
        node, _eraw = self.macro_node(text)
        if node is not None:
            return None  # an expression: evaluated by the ordinary path
        eraw = ("void __probe(void) { " + text + "; }").encode("utf-8")
        root = self.parser.parse(eraw).root_node
        if root.has_error:
            return None
        fn = next((x for x in _walk(root) if x.type == "function_definition"), None)
        stmts = _named(fn.child_by_field_name("body")) if fn is not None else []
        # Kept alive for the whole evaluation: local keys use ``id(raw)``, and a freed buffer's id is reused by the next
        # expansion (``M; M;`` shared one static — round 4 C4).
        self.kept_raws.append(eraw)
        return (name, stmts, eraw) if stmts else None

    def macro_statement(self, state, n, raw):
        """Run a statement that is a macro invocation expanding to statements; None if it is not one."""
        found = self.macro_statements(n, raw)
        if found is None:
            return None
        _name, stmts, eraw = found
        saved = self.raw
        self.raw = eraw
        try:
            states = [state]
            for s in stmts:
                states = self.run(states, s)
        finally:
            self.raw = saved
        if len(states) != 1 or states[0].mode != "normal":
            raise Unsupported("macro_statement_control_flow")
        return states[0]

def _substitute(body, params, args):
    """Replace every parameter by its argument text in *one* pass — ``SUB(a, b)`` called as ``SUB(b, 1U)`` must not
    turn the substituted ``b`` into ``1U`` again (R2b review C1)."""
    if not params:
        return body
    table = dict(zip(params, args, strict=True))
    names = "|".join(re.escape(x) for x in sorted(params, key=len, reverse=True))
    # Literals are matched first and kept: the preprocessor never replaces inside them (round 4 C9).
    pattern = re.compile(r"(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')|\b(" + names + r")\b")
    return pattern.sub(lambda m: m.group(1) if m.group(1) is not None else table[m.group(2)], body)


def _key(node):
    return (node.start_byte, node.end_byte, node.type)


def _ancestors(node):
    out = []
    while node is not None:
        out.append(node)
        node = node.parent
    return out


def _lca(a, b):
    seen = {_key(x) for x in _ancestors(a)}
    return next((x for x in _ancestors(b) if _key(x) in seen), None)


def _sequenced_apart(a, b, raw):
    """Is there a sequence point between the evaluations of ``a`` and ``b`` (C11 6.5.13-17)? Their nearest common
    operator decides: ``&&``/``||``/``,`` order their operands, ``?:`` orders the condition before either arm and
    runs only one arm."""
    lca = _lca(a, b)
    if lca is None:
        return True
    if lca.type in {"comma_expression", "conditional_expression"}:
        return True
    return lca.type == "binary_expression" and _op(lca, raw) in {"&&", "||"}


def _address_parent(x):
    """The ``&`` expression that takes x's address, through parentheses (``&(x)``, ``&((x))``), or None."""
    node = x.parent
    while node is not None and node.type == "parenthesized_expression":
        node = node.parent
    if node is not None and node.type in {"pointer_expression", "unary_expression"} and node.children \
            and node.children[0].type == "&":
        return node
    return None


def _unbraced_tail(node):
    """The statement an ``else`` after ``node`` would follow: through unbraced loop bodies and if arms."""
    for _ in range(64):
        if node is None:
            return None
        if node.type in {"while_statement", "for_statement"}:
            node = node.child_by_field_name("body")
        elif node.type == "if_statement":
            alt = node.child_by_field_name("alternative")
            node = (next((c for c in _named(alt)), None) if alt is not None and alt.type == "else_clause" else alt) \
                if alt is not None else node.child_by_field_name("consequence")
        else:
            return node
    return None


def _open_if(stmt):
    """Does this statement end in an ``if`` without ``else`` — one a following ``else`` would bind to?"""
    for _ in range(64):
        if stmt is None:
            return False
        if stmt.type == "if_statement":
            alt = stmt.child_by_field_name("alternative")
            if alt is None:
                return True
            stmt = next((c for c in _named(alt)), None) if alt.type == "else_clause" else alt
        elif stmt.type in {"while_statement", "for_statement"}:
            stmt = stmt.child_by_field_name("body")
        else:
            return False
    return True


def _unwrap(node):
    while node is not None and node.type == "parenthesized_expression" and len(_named(node)) == 1:
        node = _named(node)[0]
    return node


_TREES = threading.local()


def _parsed_function(parser, raw, name, scope):
    """(root, function node, shared) of ``name`` in this text — the parse, the lookup and the input-independent work of
    `_Interp` (``shared``) are cached per thread for the last few texts (R2c: a path search calls the oracle in chunks;
    re-parsing a 160 KB unit per chunk dominated its cost)."""
    cache = getattr(_TREES, "cache", None)
    if cache is None:
        cache = _TREES.cache = OrderedDict()
    key = (hashlib.sha256(raw).hexdigest(), id(parser))
    hit = cache.get(key)
    if hit is None or hit[0] != raw:
        hit = (raw, parser.parse(raw), OrderedDict())
        cache[key] = hit
        while len(cache) > 8:
            cache.popitem(last=False)
    cache.move_to_end(key)
    _raw, tree, functions = hit
    fkey = (name, id(scope))
    if fkey in functions:
        functions.move_to_end(fkey)
    while len(functions) >= 256 and fkey not in functions:
        functions.popitem(last=False)  # bounded: a long-lived backend sees new scopes on every generation (review W5)
    if fkey not in functions or functions[fkey][0] is not scope:
        # the entry holds the scope itself: while cached, its id cannot be reused by another scope
        try:
            functions[fkey] = (scope, _find_function(tree.root_node, raw, name, scope), {})
        except Unsupported as exc:
            functions[fkey] = (scope, exc, {})
    found = functions[fkey][1]
    if isinstance(found, Unsupported):
        raise Unsupported(str(found))
    return tree.root_node, found, functions[fkey][2]


def _find_function(root, raw, name, scope):
    from generators.mcdc_design import _compile_state, _function_name, _has_error
    matches, stack = [], [root]
    while stack:
        n = stack.pop()
        if n.type == "function_definition":
            if _function_name(n, raw)[0] == name:
                matches.append(n)
            continue
        stack.extend(n.named_children)
    states = scope.get("main_file_states")
    if states is not None and matches:
        compiled = [n for n in matches if _compile_state(n, states) is not None]
        if not compiled:
            raise Unsupported("function_not_compiled_in_configuration")
        if any(_compile_state(n, states) == "unknown" for n in compiled):
            raise Unsupported("conditional_compilation_unresolved")
        matches = compiled
    if len(matches) != 1:
        raise Unsupported("function_identity_missing_or_ambiguous")
    if _has_error(matches[0]):
        raise Unsupported("source_parse_error")
    return matches[0]


def _observe(interp, state, name):
    """Value an output name holds in a final state: an int, or Unknown."""
    if name == "return":
        if state.mode != "return" or state.ret is None:
            return Unknown("no_return_value_on_path")
        return state.ret.v
    m = re.fullmatch(r"([A-Za-z_]\w*)(?:\[(\d+)\])?", str(name).strip())
    if not m:
        return Unknown("observable_form_unmodeled")
    base, index = m.group(1), m.group(2)
    macro_status = interp.macro_status
    if base in macro_status:
        return Unknown("observable_is_a_macro:" + base)
    if index is None and base in interp.globals:
        g = interp.globals[base]
        return interp.read_key(state, base, base, g["type"], g.get("volatile"))
    if index is not None and base in interp.arrays:
        a = interp.arrays[base]
        if a["length"] is None or not 0 <= int(index) < a["length"]:
            return Unknown("observable_index_outside_array")
        v = interp.read_target(state, ("key", f"{base}[{int(index)}]", a["type"], a.get("volatile", False)))
        return v.v
    if base in (interp.scope.get("unresolved_globals") or {}):
        return Unknown(f"global_unmodeled:{base}:{interp.scope['unresolved_globals'][base]}")
    return Unknown("observable_not_a_modeled_object:" + base)


def _written(state, name):
    key = str(name).strip()
    return key in state.store


def _scope_assumptions(unit: dict[str, Any]) -> list[str]:
    """What the project preprocessing assumed for this unit — carried into every derived value (review round 5 W-a):
    toolchain headers taken as compiler-supplied, the typedef testimony the integer widths rest on."""
    scope = unit.get("project_scope") or {}
    out = []
    if scope.get("toolchain_includes"):
        out.append("toolchain headers (not in the source tree, resolved by the build configuration): "
                   + ", ".join(scope["toolchain_includes"][:8]) + " — assumed not to define project names")
    widths = (scope.get("target") or {}).get("widths") or {}
    if widths:
        out.append("integer widths from typedef testimony: " + ", ".join(f"{k}={v}" for k, v in sorted(widths.items())))
    return out


def scope_matches(unit: dict[str, Any]) -> bool:
    scope = unit.get("project_scope") or {}
    return bool(scope) and scope.get("schema_version") == cpc.SCHEMA_VERSION and \
        scope.get("main_file_sha256") == hashlib.sha256(str(unit.get("source_text") or "").encode()).hexdigest()


def evaluate_outputs(unit: dict[str, Any], sequences_inputs: list[dict[str, Any]], outputs: list[list[str]]) -> list[dict[str, Any]]:
    """Per sequence: ``{"status", "outputs": {name: {"value": int} | {"reason": str}}, ...}``.

    ``unit`` carries ``source_text``, ``name`` and a matching ``project_scope``. The function is parsed once;
    each sequence runs on a fresh state. Never raises.
    """
    source = str(unit.get("source_text") or "")
    digest = hashlib.sha256(source.encode()).hexdigest()
    base = {"schema_version": SCHEMA_VERSION, "execution_status": "not_run", "reachability": "unverified",
            "source_hash": digest, "function_name": str(unit.get("name") or ""), "oracle": "project_context_source",
            "assumptions": list(ASSUMPTIONS) + _scope_assumptions(unit)}
    try:
        if not source or not unit.get("source_text_complete", True):
            raise Unsupported(unit.get("source_unavailable_reason") or "authoritative_source_missing")
        if len(source) > 2_000_000:
            raise Unsupported("source_budget")
        if not scope_matches(unit):
            raise Unsupported("project_scope_missing_or_mismatched")
        scope = unit["project_scope"]
        parser = cpc.shared_parser()
        if parser is None:
            raise Unsupported("tree_sitter_unavailable")
        raw = source.encode()
        _root, fn, shared = _parsed_function(parser, raw, str(unit.get("name") or ""), scope)
    except Exception as exc:  # noqa: BLE001 — never raise into the generator; the reason is the record
        reason = str(exc) if isinstance(exc, Unsupported) else f"oracle_exception:{type(exc).__name__}"
        return [{**base, "status": "unsupported", "reason": reason,
                 "outputs": {o: {"reason": reason} for o in outs}} for outs in outputs]
    results = []
    for inputs, outs in zip(sequences_inputs, outputs, strict=True):
        record = dict(base)
        try:
            interp = _Interp(fn, raw, scope, dict(inputs or {}), parser, shared)
            interp.function_name = str(unit.get("name") or "")
            _prescan_once(interp, shared)  # path-independent refusals: once per function
            state = _State()
            interp.bind_parameters(state)
            finals = interp.run([state], fn.child_by_field_name("body"))
            if any(s.mode in {"break", "continue"} for s in finals):
                raise Unsupported("jump_outside_loop")
            values = {}
            for name in outs:
                seen = [_observe(interp, s, name) for s in finals]
                unknown = next((v for v in seen if isinstance(v, Unknown)), None)
                if unknown is not None:
                    values[name] = {"reason": unknown.reason}
                elif len(set(seen)) != 1:
                    forks = next((f for s in finals for f in s.forks), "branch_on_unknown")
                    values[name] = {"reason": "path_dependent:" + forks}
                else:
                    # ``assigned``: some path wrote it; ``unchanged_input``: no path wrote it and the value is the one the
                    # sequence set (both are code-consistent expectations; the split keeps the second from inflating).
                    assigned = name == "return" or any(_written(s, name) for s in finals)
                    values[name] = {"value": seen[0], "basis": "assigned" if assigned else "unchanged_input"}
            possible = sorted({k for s in finals for k in s.possible_ub})
            record.update(status="supported", reason="project_context_source_evaluation" +
                          (":possible_ub=" + "+".join(possible) if possible else ""),
                          outputs=values, paths=len(finals), possible_undefined_behavior=possible)
        except Unsupported as exc:
            record.update(status="unsupported", reason=str(exc), outputs={o: {"reason": str(exc)} for o in outs})
        except Exception as exc:  # noqa: BLE001 — never raise into the generator; recorded as the reason below
            reason = f"oracle_exception:{type(exc).__name__}"
            record.update(status="unsupported", reason=reason, outputs={o: {"reason": reason} for o in outs})
        results.append(record)
    return results


def _prescan_once(interp, shared):
    """Run `_Interp.prescan` once per function and remember its verdict — only once it is known: a failure that is not a
    refusal is recorded as one, never as a pass (R2c review round 1 W4: recording "" first let later vectors skip it)."""
    if "prescan" not in shared:
        try:
            interp.prescan()
            verdict = ""
        except Unsupported as exc:
            verdict = str(exc)
        except Exception as exc:  # noqa: BLE001 — the reason is the verdict (fail-closed)
            verdict = f"oracle_exception:{type(exc).__name__}"
        shared["prescan"] = verdict
    if shared["prescan"]:
        raise Unsupported(shared["prescan"])


def _node_at(root, key):
    """The node with this ``(start, end, type)`` in a parse of the same text, or None."""
    start, end, typ = key
    stack = [root]
    while stack:
        n = stack.pop()
        if n.start_byte > start or n.end_byte < end:
            continue
        if n.start_byte == start and n.end_byte == end and n.type == typ:
            return n
        stack.extend(n.children)
    return None


def _summarize(finals, key):
    """What the paths of one run say about one decision. ``evaluated`` only when every path evaluates it the same
    determined way, the same number of times (a loop evaluates it once per iteration): ``instances`` are the distinct
    evaluations in order of first occurrence. Else why not."""
    per_path = [[obs for k, obs in s.decisions if k == key] for s in finals]
    if all(not obs for obs in per_path):
        return {"state": "unreached"}
    if any(o[0] == "maybe" for obs in per_path for o in obs):
        return {"state": "maybe_evaluated"}
    if any(not obs for obs in per_path):
        return {"state": "path_dependent_reach"}
    undetermined = next((o for obs in per_path for o in obs if o[0] == "undetermined"), None)
    if undetermined is not None:
        return {"state": "undetermined", "reason": undetermined[1]}
    if len({tuple(obs) for obs in per_path}) != 1:
        return {"state": "path_dependent_value"}
    instances = list(dict.fromkeys(per_path[0]))
    return {"state": "evaluated", "evaluations": len(per_path[0]),
            "instances": [{"truth": list(t), "observed": list(o), "decision": d} for _tag, t, o, d in instances]}


def _guard_paths(finals, key):
    """Per path, the outcomes (True / False / None = undetermined) a guard condition had, in order."""
    return [[obs[1] if obs[0] == "outcome" else None for k, obs in s.decisions if k == key] for s in finals]


def observe_decisions(unit: dict[str, Any], vectors: list[dict[str, Any]],
                      decisions: list[dict[str, Any]], guards: list[list] | tuple = ()) -> list[dict[str, Any]]:
    """(R2c) Per input vector: how each decision of the function evaluates on the modeled run.

    ``decisions``: ``[{"key": [start, end, type], "atoms": [[start, end, type], ...], "ir": nested list}]`` over the
    unit's source text (the decision node, its conditions in order, and the ``&&``/``||``/``!`` structure with
    ``["atom", i]`` leaves). Per vector: ``{"status", "reason", "decisions": {index: summary}}`` where a summary is
    ``{"state": "evaluated", "evaluations", "instances": [{"truth", "observed", "decision"}]}`` only when every modeled
    path evaluates the decision the same determined way (see `_summarize`). A decision with a condition that writes or
    calls is ``effectful_condition`` for every vector (see `_Interp.atom_effectful`). ``guards``: control conditions
    (``[start, end, type]`` of an ``if``/loop/``?:`` condition) whose outcomes per path are returned under ``"guards"``
    — how far a vector gets towards a decision it does not reach. Never raises.

    Like `evaluate_outputs` this is a model of the source, not an execution: reachability here is modeled, callee
    effects are the project write closure, and undefined behaviour proven on a run makes that vector unsupported.
    """
    source = str(unit.get("source_text") or "")
    try:
        if not source or not unit.get("source_text_complete", True):
            raise Unsupported(unit.get("source_unavailable_reason") or "authoritative_source_missing")
        if len(source) > 2_000_000:
            raise Unsupported("source_budget")
        if not scope_matches(unit):
            raise Unsupported("project_scope_missing_or_mismatched")
        scope = unit["project_scope"]
        parser = cpc.shared_parser()
        if parser is None:
            raise Unsupported("tree_sitter_unavailable")
        raw = source.encode()
        _root, fn, shared = _parsed_function(parser, raw, str(unit.get("name") or ""), scope)
        guard_keys = {}
        for index, g in enumerate(guards):
            guard_keys[tuple(g)] = ("guard", index)
        specs, broken = {}, {}
        for index, d in enumerate(decisions):
            node = _node_at(fn, tuple(d["key"]))
            atoms = [_node_at(fn, tuple(a)) for a in d.get("atoms") or []]
            if node is None or not atoms or any(a is None for a in atoms):
                broken[index] = "decision_node_not_found"
                continue
            specs[(node.start_byte, node.end_byte, node.type)] = {"key": index, "atoms": atoms, "ir": _ir_tuple(d["ir"])}
    except Exception as exc:  # noqa: BLE001 — never raise into the generator; the reason is the record
        reason = str(exc) if isinstance(exc, Unsupported) else f"oracle_exception:{type(exc).__name__}"
        return [{"status": "unsupported", "reason": reason, "decisions": {}} for _ in vectors]
    probe_interp = None
    try:
        probe_interp = _Interp(fn, raw, scope, {}, parser, shared)
        _prescan_once(probe_interp, shared)  # path-independent refusals: once per function, not per vector
        for key, spec in list(specs.items()):
            if any(probe_interp.atom_effectful(a, raw) for a in spec["atoms"]):
                broken[spec["key"]] = "effectful_condition"
                del specs[key]
    except Exception as exc:  # noqa: BLE001 — never raise into the generator (R2c review round 1 W4)
        reason = str(exc) if isinstance(exc, Unsupported) else f"oracle_exception:{type(exc).__name__}"
        return [{"status": "unsupported", "reason": reason, "decisions": {}} for _ in vectors]
    results = []
    for inputs in vectors:
        record = {"status": "supported", "reason": "", "decisions": {i: {"state": why} for i, why in broken.items()}}
        interp = None
        try:
            interp = _Interp(fn, raw, scope, dict(inputs or {}), parser, shared)
            interp.function_name = str(unit.get("name") or "")
            interp.watch = specs
            interp.guards = guard_keys
            state = _State()
            interp.bind_parameters(state)
            finals = interp.run([state], fn.child_by_field_name("body"))
            if any(s.mode in {"break", "continue"} for s in finals):
                raise Unsupported("jump_outside_loop")
            record["steps"] = interp.steps  # (R2c) the run's cost: callers budget searches by it (deterministic)
            for spec in specs.values():
                record["decisions"][spec["key"]] = _summarize(finals, spec["key"])
            if guard_keys:
                record["guards"] = {index: _guard_paths(finals, ("guard", index)) for index in range(len(guards))}
            possible = sorted({k for s in finals for k in s.possible_ub})
            if possible:
                # Undefined behaviour that depends on an unknown value may happen on this run *after* the decision (an
                # observation with it before is ``undetermined``): disclosed, as for outputs.
                record["possible_undefined_behavior"] = possible
        except Unsupported as exc:
            record.update(status="unsupported", reason=str(exc), steps=interp.steps if interp is not None else 0)
        except Exception as exc:  # noqa: BLE001 — never raise into the generator; recorded as the reason
            record.update(status="unsupported", reason=f"oracle_exception:{type(exc).__name__}",
                          steps=interp.steps if interp is not None else 0)
        results.append(record)
    return results


def _ir_tuple(ir):
    """JSON form (``["&&", l, r]``, ``["!", x]``, ``["atom", i]``) → the tuple form `record_decision` walks."""
    if ir[0] == "atom":
        return ("atom", int(ir[1]))
    if ir[0] == "!":
        return ("!", _ir_tuple(ir[1]))
    return (ir[0], _ir_tuple(ir[1]), _ir_tuple(ir[2]))
