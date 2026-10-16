"""Source oracle over the project C context: what one function leaves in its outputs for concrete inputs.

A code-consistency oracle — not a requirement oracle, not an execution result, not reachability. It
interprets the unchanged function text with the translation unit's resolved scope
(`generators.c_project_context`): target integer widths from typedef testimony, integer macros,
enumerators, const objects, scalar globals and one-dimensional arrays. Nothing is guessed:

* a value the inputs do not determine is *unknown* with its reason — a global the sequence does not set,
  a call's return value, a volatile read, a pointer target, an out-of-type input (``U8 = -1``);
* a branch on an unknown condition runs both arms; an output is *derived* only when every path agrees;
* a call havocs what the callee may write (the project write closure, transitively) — a call the sequence stubs
  (``F() return`` / ``F() p[0]``) writes no global or static, only what a pointer argument may reach (R38); a write through a pointer
  (in the function or a callee) reaches arrays, address-taken objects and escaped locals; a callee with unknown
  effects (library, indirect) havocs every global, every escaped local and every static local;
* undefined behaviour proven on a path (signed overflow, division by zero, shift range, out-of-bounds index,
  unsequenced side effects) refuses the whole evaluation when that path is the run's only one; undefined behaviour that
  depends on an unknown value — a value, or (R90) a branch on one that chose the path it was proven on (the faulting
  result is then unknown and the path runs on) — is disclosed (``possible_undefined_behavior``);
* implementation-defined results (signed narrowing, an enumeration object's underlying type) are unknown
  unless every permitted choice gives the same value.
"""
from __future__ import annotations

import contextlib
import hashlib
import itertools
import math
import os
import re
import threading
from collections import OrderedDict
from typing import Any

from generators import c_project_context as cpc
from generators import pointer_flow

SCHEMA_VERSION = 5   # 2 (R14): a record may rest on sequence stubs (``stubs``) — ``F() return`` inputs are taken
#                      3 (R38): a sequence stub writes no global or static (VectorCAST replaces the body — `stubbed_call`)
#                      4 (backlog 2-c): an output no final path read nor wrote gives `UNWRITTEN_OUTPUT_PREFIX`, not
#                        `INITIAL_VALUE_PREFIX` (the function did not read it — the observation needs its initial value)
#                      5 (R90): UB proven on a path a branch on an unknown value chose no longer refuses the record — it is
#                        possible UB (``forked_path_undefined_behavior``, `_Interp.undefined`); ``sizeof`` of a character
#                        type / array is evaluated
# (backlog 2-c) the two reasons an unset initial value gives — one vocabulary for the oracle and its readers
INITIAL_VALUE_PREFIX = "initial_value_not_in_inputs:"
UNWRITTEN_OUTPUT_PREFIX = "unwritten_output_initial_not_in_inputs:"
# an enum-typed input: the values every permitted underlying type holds unchanged (C11 6.7.2.2p4) — one range for the
#   oracle's input check and the SUTS widening over the enumerators (review R80 W4)
ENUM_INPUT_RANGE = (0, 127)


def enum_member_span(scope, t) -> tuple[int, int] | None:
    """(R90 review W4) The least and greatest member value of the enumeration type ``t`` (``t["enum"]`` — its one
    definition in the unit, `c_project_context` ``enum_types``), or None when the unit does not give every member a
    value."""
    key = (t or {}).get("enum") if isinstance(t, dict) else None
    rec = ((scope or {}).get("enum_types") or {}).get(key) if key else None
    members = (rec or {}).get("members") or []
    constants = scope.get("constants") if isinstance(scope, dict) and scope.get("constants") is not None else {}
    values = []
    for m in members:
        value = (constants.get(m.get("name")) or {}).get("value")
        if type(value) is not int:
            return None
        values.append(value)
    return (min(values), max(values)) if values else None


def enum_input_range(scope, t) -> tuple[int, int]:
    """(R90 review W4) The values an input of enumeration type ``t`` may hold under every permitted underlying type: the
    type the implementation picks holds every member (C11 6.7.2.2p4) and 0..127 (every char or int type, signed or not —
    `ENUM_INPUT_RANGE`), so it holds the interval spanning both. HDPDM01 service ids 0xB0 · 0xB2 · 0xB7 are members —
    an input of one was refused as outside the type. Only 0..127 when a member's value is not known."""
    lo, hi = ENUM_INPUT_RANGE
    span = enum_member_span(scope, t)
    return (min(lo, span[0]), max(hi, span[1])) if span else (lo, hi)
_UB_REASONS = frozenset({"signed_overflow", "division_by_zero", "shift_count_out_of_range", "signed_left_shift_overflow",
                         "float_to_int_out_of_range"})
_EXECUTION_BUDGET = 200_000
_PATH_BUDGET = 64
_LOOP_BUDGET = 4096
# (R90 re-review C-N1 a) register values a polling loop's way out is searched over, per staying path (the product over the
#   polled members — `_Interp.polling_way_out`); over it the loop is not assumed to end
_POLL_SEARCH_BUDGET = 4096
_BUDGET_REASONS = frozenset({"loop_iteration_budget", "execution_budget", "path_budget"})
# (R90 re-review 3 W-R3-2) searches of a polling loop's way out as members read only under other flag values join
_POLL_MEMBER_ROUNDS = 4
_PROBE_FAILED = object()
# (re-review 3 W-R3-1) what a hypothetical probe (`_Interp.hypothetical`) may record — put back after it
_HYPOTHETICAL_TABLES = ("stubs_used", "linked_reads", "stub_keys", "assumed_undefined", "storage_used",
                        "storage_volatile_reads", "volatile_polls", "volatile_poll_members", "polling_assumed",
                        "storage_narrow", "storage_unspecified", "static_keys", "pointees", "observed_only_pointees",
                        "harness_buffers", "buffer_reach", "buffer_reach_unknown", "pointer_member_keys")
_HYPOTHETICAL_WORLD_TABLES = ("inlined", "not_inlined", "effects_only", "static_keys", "array_names", "global_names",
                              "admitted")
# world tables that only gain keys (``setdefault`` / a value an existing key already holds): put back by dropping the keys
#   added after the probe began — a dict keeps insertion order — instead of copying them for every probe
_HYPOTHETICAL_WORLD_GROWING = ("failed", "linkage", "objects", "types", "storage_scopes", "storage_signatures")
# (re-review 4 X5) what a hypothetical probe leaves as it found it, or must not put back — and why. Every attribute an
#   activation or the world sets is in a list above or here (`tests/unit/test_register_model_r90.py` holds them to it)
_HYPOTHETICAL_EXEMPT = {
    # the activation's fixed context (``raw`` is swapped and put back around a statement macro)
    **dict.fromkeys(("fn", "raw", "scope", "inputs", "parser", "fn_raw", "function_name", "world", "param_prefix",
                     "limit"), "the activation's fixed context"),
    # the unit's scope, read only
    **dict.fromkeys(("widths", "int_t", "constants", "globals", "arrays", "array_shapes", "struct_globals", "storage",
                     "macro_status", "macro_bodies", "macro_params", "fmacro_bodies", "closure", "address_taken"),
                    "the unit's scope, read only"),
    # caches of the text — what a probe adds a real run would add alike
    **dict.fromkeys(("shared", "macro_memo", "expansions", "walks", "fn_names", "body_address_names",
                     "storage_inputs"), "a cache of the text or of the row's inputs: the same whoever fills it"),
    # (re-review 5 I-R5-3) a call site a probe found order-dependent stays marked: the real run then reads that site as
    #   its effects only — less precise, never a value the program does not give
    "no_inline": "call sites marked order-dependent (a probe's mark only costs precision at that site)",
    "lexical": "pushed and popped in pairs by the statements a probe runs",
    "no_inline_depth": "raised and lowered in pairs around a call",
    "steps": "the run's budget: the steps a probe spends stay spent",
    "params": "bound when the activation starts — a probe binds none",
    "kept_raws": "expansion buffers stay alive: their ids are in keys",
    "watch": "put back by the probe itself (no decision is observed on it)",
    **dict.fromkeys(("guards", "statement_marks", "operand_marks", "write_marks", "perturb", "observed"),
                    "what the caller asked to observe, set before the run"),
    # the world
    **dict.fromkeys(("provider", "linkage_cache", "ambiguous", "ambiguous_roots"), "the run's fixed context"),
    "stack": "pushed and popped in pairs by an inline",
    "activations": "names the parameter keys of an activation: must stay unique",
    "kept": "expansion buffers of finished activations stay alive: their ids are in keys",
    **dict.fromkeys(("pointer_havocs", "all_havocs"), "statistics nothing reads"),
}


def _table_copy(t):
    """One level deeper than ``copy``: the sets / lists / dicts a table holds are copied too."""
    if isinstance(t, dict):
        return {k: (v.copy() if isinstance(v, (set, list, dict)) else v) for k, v in t.items()}
    return t.copy()


def _table_restore(live, old):
    """Put ``old`` back into ``live`` in place — whoever holds the table sees it as it was."""
    if isinstance(live, list):
        live[:] = old
    else:
        live.clear()
        live.update(old)


ASSUMPTIONS = (
    "undefined behaviour is refused when proven on the run's only path; where it depends on an unknown value (divisor, "
    "shift count, index, overflow of an unknown operand, or a branch on an unknown value that chose the path it was "
    "proven on — that path runs on with the faulting result unknown) it is not proven absent — derived values hold for "
    "runs without it",
    "callee effects are the project write closure (a callee that runs — outputs it may write are unknown); a callee "
    "the sequence stubs writes no global or static (what it may put through a pointer argument is unknown)",
    "reachability and termination of callees are not proven",
    "fixed-address register objects are distinct objects (writes to one do not change another)",
    "an integer converted to a pointer addresses hardware — no C object but (R90) the registers, the @-placed union / "
    "bit-field objects the model holds values of: a write through a pointer reaches address-taken objects, arrays, locals "
    "whose address escaped and every register",
    "(R64) a write a callee or a stub makes through a pointer reaches what the project-wide points-to analysis says "
    "that pointer may hold (every definition and initializer the context read, an object of integer type holding no "
    "pointer — an object that may hold pointers written as bytes holds unknown ones, an integer object a pointer "
    "is stored into holds it, an integer that is not a constant converted to a pointer (with a cast or without) and a "
    "pointer read from integer storage or fixed-address memory may point anywhere — the objects pointers that became "
    "integers pointed to, and what they reach, may then hold any pointer); code outside the project reaches a project object only through what the project hands it and calls a "
    "project function only through an address handed out or as an entry point no project code calls; inline assembly "
    "reaches C objects only through its operands and the names its text mentions; pointer arithmetic stays inside its "
    "object — where the analysis cannot follow, every address-taken object, array and escaped local",
    "a write through a struct member array stays inside that member (beyond it is undefined behaviour)",
    "a pointer parameter whose pointee the sequence sets or observes (p[0] / p[0].a as an input or an expected value, "
    "or the parameter itself as an output) points to a harness object of its own — not null, not a program object, "
    "not another parameter's pointee",
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
_STORAGE_ADDRESS = "address_value:"   # (R90 review C2) + root: the address of a union / bit-field object
# (R90 review C2) `havoc_bases` mark: a write through a pointer may have landed on any volatile union / bit-field object
#   (a register: ``@``-placed next to the others, so an offset from one reaches the next)
_VOLATILE_STORAGE = "@storage:volatile"
# (R90 re-review 4 C-R4-1) why the registers are unknown after a callee the run did not interpret (+ the next ones — I-R5-4)
_CALLEE_REGISTERS = "register_read_by_callee_not_interpreted:"


def _untyped_overflow_tag(operands, int_bits):
    """Possible-UB tag for arithmetic with an operand of unknown type (review round 6 C2 / round 7 W1): a pointer or a
    decayed array — the result may leave the object (C11 6.5.6p8); ``sizeof`` — ``size_t`` is unsigned and at least
    16 bits, so against operands no wider than ``int`` the result is unsigned and cannot overflow (``None``); anything
    else (a call's return, an unresolved macro, ``*p``) may be a signed int."""
    untyped = [x.v.reason if isinstance(x.v, Unknown) else "" for x in operands if x.t is None]
    if any(r.startswith(_STORAGE_ADDRESS) for r in untyped):
        # (R90 review C2) ``(T *)&REG_FCCOB2 + j``: a register's address offset by what is not 0 leaves the object (the
        #   next register on the target — C11 6.5.6p8 makes the access undefined)
        others = [x for x in operands if not (x.t is None and isinstance(x.v, Unknown)
                                              and x.v.reason.startswith(_STORAGE_ADDRESS))]
        return None if others and all(_known_int(x) == 0 for x in others) else "pointer_past_object"
    if any(r.startswith(_POINTER_REASONS) for r in untyped):
        return "pointer_arithmetic_untyped"
    if untyped and all(r in ("sizeof_unmodeled", _SIZE_REASON) for r in untyped) and all(
            x.t.get("bits", 99) <= int_bits for x in operands if isinstance(x.t, dict)):
        return None
    return "signed_overflow_untyped_operand"


# (R90) a ``sizeof`` whose value C fixes (`_Interp.sizeof_value`) — or a result exact under every choice of its type
#   (`_Interp.size_arith`): the value rides in ``_Val.r`` (an interval no operator reads on an untyped value — `operand_range`
#   wants a type), so every reader that does not ask `_size_value` sees an unknown of unknown type, as before R90
_SIZE_REASON = "sizeof_type_unspecified"
# (R90 review C1) undefined behaviour proven on a path a branch on an unknown value chose (`_Interp.undefined`): the
#   possible-UB tag ``<kind>_on_unknown_branch(selector=<that branch's reason>)`` — `source_findings` keeps it as a finding
#   of the kind — and the reason of the faulting operation's unknown result
FORKED_UB_SUFFIX = "_on_unknown_branch"
FORKED_UB_REASON = "possible_undefined_behavior_on_unknown_branch:"
_FORKED_UB_TAG = re.compile(r"([a-z_]+)" + FORKED_UB_SUFFIX + r"\(selector=(.*)\)")


FORKED_UB_SELECTOR_SEP = " · "
FORKED_UB_SELECTORS_SHOWN = 4


def selector_text(selectors) -> str:
    """(R90 review W1) Every branch on an unknown value that chose a path, in order, once each — up to
    `FORKED_UB_SELECTORS_SHOWN`, then how many more (``… N more``: not one of them, so never read as an open input)."""
    names: list[str] = []
    for s in selectors:
        s = s[len("branch_on_unknown:"):] if s.startswith("branch_on_unknown:") else s
        s = s[:80].replace("+", " ")    # `+` joins the reason's possible-UB tags
        if s not in names:
            names.append(s)
    shown = names[:FORKED_UB_SELECTORS_SHOWN]
    if len(names) > len(shown):
        shown.append(f"… {len(names) - len(shown)} more")
    return FORKED_UB_SELECTOR_SEP.join(shown)


def forked_path_ub(tags) -> list[tuple[str, str]]:
    """(R90 review C1) ``(kind, selector)`` of every possible-UB tag `_Interp.undefined` gave, sorted."""
    return sorted({(m.group(1), m.group(2)) for t in tags or () for m in [_FORKED_UB_TAG.fullmatch(str(t))] if m})


def _size_value(x):
    """(R90) The value of ``x`` when it is a ``sizeof`` value (`_SIZE_REASON`) — known, of the implementation's ``size_t``
    (an unsigned type of at least 16 bits whose rank the source does not say: C11 6.5.3.4p5, 7.19p2, 7.20.3) — else None.
    A value passed through an operator that is not `_Interp.size_arith` loses ``r`` (``_Val(x.v, None)``), so it is no
    longer one."""
    if x.t is None and isinstance(x.v, Unknown) and x.v.reason == _SIZE_REASON and x.r is not None \
            and x.r[0] == x.r[1]:
        return x.r[0]
    return None


class _Pointer:
    """(R40) A pointer value the model knows: to the pointee a test sequence set up for pointer parameter ``target`` (a
    harness object of its own), or null (``target`` None). Only ``==`` / ``!=`` / ``!``, a truth test and a cast to a
    pointer type read it; it carries no C type, so everything else makes it an unknown value."""
    __slots__ = ("target",)

    def __init__(self, target):
        self.target = target

    def __bool__(self):
        return self.target is not None

    def __eq__(self, other):
        return isinstance(other, _Pointer) and other.target == self.target

    def __hash__(self):
        return hash(("_Pointer", self.target))

    def __repr__(self):
        return f"_Pointer({self.target!r})"


class _Bits:
    """(R90) What a run left in one byte of a union / bit-field object (store key ``REG.@order:byte``): ``written`` — the
    bits it wrote, ``known`` (within them) — those of known value, ``value`` — their values, ``reason`` — why the other
    written ones are unknown. A bit it did not write holds what the object held before the run (`_Interp.storage_value`).
    Immutable; equal records compare equal (a join keeps a byte every path left alike)."""
    __slots__ = ("written", "known", "value", "reason")

    def __init__(self, written: int, known: int, value: int, reason: str):
        self.written, self.known, self.value, self.reason = written, known, value & known, reason

    def __eq__(self, other):
        return isinstance(other, _Bits) and (self.written, self.known, self.value, self.reason) == (
            other.written, other.known, other.value, other.reason)

    def __hash__(self):
        return hash(("_Bits", self.written, self.known, self.value, self.reason))

    def __repr__(self):
        return f"_Bits(w={self.written:#04x}, k={self.known:#04x}, v={self.value:#04x}, {self.reason!r})"


def _byte_state(v):
    """(R90) ``(written, known, value, reason)`` of a stored byte — none written when absent; a byte a havoc made
    ``Unknown`` is written and unknown whole."""
    if isinstance(v, _Bits):
        return v.written, v.known, v.value, v.reason
    if v is None or v is _MISSING:
        return 0, 0, 0, ""
    return 0xFF, 0, 0, v.reason if isinstance(v, Unknown) else "storage_byte_unmodeled"


def _join_bytes(values, why):
    """(R90) A storage byte after paths that left it differently: a bit every path wrote with one known value keeps it,
    a bit no path wrote still holds the object's earlier value, any other written bit is unknown (``why``)."""
    states = [_byte_state(v) for v in values]
    written = 0
    for w, _k, _v, _r in states:
        written |= w
    known, value = written, 0
    for w, k, v, _r in states:
        known &= w & k
    for bit in (1 << i for i in range(8)):
        if known & bit:
            seen = {s[2] & bit for s in states}
            if len(seen) != 1:
                known &= ~bit
            else:
                value |= seen.pop()
    return _Bits(written, known, value, why if written & ~known else "")


def _state_key(s):
    """(R90 review W1) What a loop's next iteration reads of a path: its objects (stored values compare by value —
    an unknown by identity, so a path that re-stores one is never taken for unchanged), its havoc marks and escapes."""
    return (s.mode, tuple(sorted(s.store.items())), s.havoc_all, s.havoc_pointer, tuple(sorted(s.havoc_bases.items())),
            frozenset(s.escaped))


def _ir_outcome(ir, truths):
    """(R79) A decision's outcome from its conditions' truths with C's short circuit (tuple IR) — None when it reads an
    undetermined one."""
    kind = ir[0]
    if kind == "atom":
        return truths[ir[1]]
    if kind == "!":
        inner = _ir_outcome(ir[1], truths)
        return None if inner is None else not inner
    left = _ir_outcome(ir[1], truths)
    if left is None:
        return None
    if (kind == "&&" and not left) or (kind == "||" and left):
        return left
    return _ir_outcome(ir[2], truths)


def _known_int(val):
    """(R79) An evaluated integer value, or None (unknown, pointer, floating point, no type)."""
    v = getattr(val, "v", None)
    return v if isinstance(v, int) and not isinstance(v, bool) and isinstance(getattr(val, "t", None), dict) \
        and not cpc.is_float(val.t) else None


def _loaded(value, t):
    """The value of an object read from the store: a stored unknown's interval comes back with it."""
    return _Val(value, t, value.range if isinstance(value, Unknown) else None)


class _State:
    __slots__ = ("store", "mode", "ret", "havoc_all", "havoc_pointer", "havoc_bases", "escaped", "forks", "possible_ub",
                 "decisions", "initial_reads", "rebound", "selectors", "ub_proven")

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
        # (backlog 2-c) keys this path read while their initial value was not in the inputs — a read is not stored, so
        #   the store alone cannot tell 'read in a condition, never written' from 'never touched'
        self.initial_reads: set[str] = set()
        # (review R82 C1) pointer members of a harness object (`@pointee:msg[0].data`) the path wrote or may have written
        #   — they no longer point to the harness buffer: an access through them is through an unknown pointer again
        self.rebound: set[str] = set()
        # (R90 review C1) the branches on an unknown value that chose this path among others in this run — unlike
        #   ``forks``, not those of a callee whose paths were joined back into one (`_World.inline`): the joined state is
        #   every callee path, not a choice among them. Empty: this is the run's only path
        self.selectors: list[str] = []
        # (R90 review C1) the kind of the first undefined behaviour proven on this very path (`_Interp.undefined`), or ""
        #   — a joined callee state has it only when every callee path had it; every final path with it refuses the run
        self.ub_proven = ""

    def copy(self, records=True):
        """A copy of the path — (R79 review I-R2-3) without its records (``records=False``) for a probe that reads only
        what its own evaluation records."""
        s = _State()
        s.store, s.mode, s.ret = dict(self.store), self.mode, self.ret
        s.havoc_all, s.havoc_bases, s.escaped, s.forks = self.havoc_all, dict(self.havoc_bases), set(self.escaped), list(self.forks)
        s.possible_ub = set(self.possible_ub)
        s.decisions = list(self.decisions) if records else []
        s.havoc_pointer = self.havoc_pointer
        s.initial_reads = set(self.initial_reads)
        s.rebound = set(self.rebound)
        s.selectors = list(self.selectors)
        s.ub_proven = self.ub_proven
        return s


def _text(node, raw):
    return raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _named(node):
    return [c for c in node.named_children if c.type != "comment"]


#: (R90) conditional groups (`_Interp.switch_items`)
_PP_GROUPS = frozenset({"preproc_if", "preproc_ifdef", "preproc_elif", "preproc_elifdef"})


def _group_holds(node, kinds: frozenset) -> bool:
    """(R90) A node of ``kinds`` directly in an arm of this conditional group (through nested groups and ``#else``, not
    into blocks) — in a switch body, a label of that switch or a declaration in the switch block's scope."""
    for c in node.named_children:
        if c.type in kinds or (c.type in _PP_GROUPS | {"preproc_else"} and _group_holds(c, kinds)):
            return True
    return False


#: (R90) what a group in a switch body must be decided for before the switch runs (`_Interp.switch_items`): a label is
#   a jump target, and a declaration is in scope at every later label — a jump past it passes it (C11 6.2.1p4, R16b
#   review C2 `skipped_decls`) whether or not the path ran its group
_SWITCH_EAGER = frozenset({"case_statement", "declaration"})


def _op(node, raw):
    o = node.child_by_field_name("operator")
    return _text(o, raw) if o is not None else ""


def cast_call_operand(c, raw, scope):
    """The operand of ``(T)(x)`` when ``c`` is that cast — tree-sitter parses a cast to a typedef name as a call — else
    None. ``T`` is a type when the scope resolves it (`_Interp.type_of`: normalised text, `mcdc_design._scope_type`; an
    unresolved name is not a type). The one cast judgement (R26) — the interpreter and R31's constant walk share it."""
    if c is None or c.type != "call_expression":
        return None
    f = c.child_by_field_name("function")
    if f is None or f.type != "parenthesized_expression":
        return None
    inner = _named(f)
    args = _named(c.child_by_field_name("arguments")) if c.child_by_field_name("arguments") is not None else []
    if len(inner) != 1 or inner[0].type not in {"identifier", "type_identifier"} or len(args) != 1:
        return None
    from generators.mcdc_design import _scope_type
    name = " ".join(_text(inner[0], raw).split())
    try:
        is_type = isinstance(_scope_type(scope, name), dict)
    except cpc.Unresolved:
        is_type = False
    # (review R64 W-3) a parameter or local of the function hides a typedef of its name: a call through it
    return args[0] if is_type and not _declared_in_function(c, name, raw) else None


def cast_unary_operand(n, raw, scope):
    """(R67) ``(T)-x`` / ``(T)+x`` — the grammar's subtraction / addition with a parenthesized name (`cpc.paren_cast_unary`)
    — read as the cast it is when ``T`` is a type here: ``(T, sign, operand)``, else None. The judgment is
    `cast_call_operand`'s (the scope resolves ``T``, no parameter or local hides it) plus no macro of that name in the unit
    (the preprocessor replaces it first). ``operand`` is None when the grammar grouped the right side under the misparse —
    the reader leaves that unknown (`cast_operand_grouping_unread`)."""
    shape = cpc.paren_cast_unary(n, raw)
    if shape is None or not isinstance(scope, dict) or shape[0] in (scope.get("macro_status") or {}):
        return None
    from generators.mcdc_design import _scope_type
    try:
        is_type = isinstance(_scope_type(scope, shape[0]), dict)
    except cpc.Unresolved:
        is_type = False
    return shape if is_type and not _declared_in_function(n, shape[0], raw) else None


_DECLARED_NAMES: dict[tuple, tuple] = {}


def _declared_in_function(node, name, raw) -> bool:
    """Whether the function around ``node`` declares a parameter or local ``name`` anywhere — a declaration hides a
    typedef of that name in its scope (C11 6.2.1p4); reading a cast as a call only loses a value."""
    fn = node
    while fn is not None and fn.type != "function_definition":
        fn = fn.parent
    if fn is None:
        return False
    key = (id(raw), fn.start_byte, fn.end_byte)
    hit = _DECLARED_NAMES.get(key)
    if hit is None or hit[0] is not raw:
        names = set()
        for n in _walk(fn):
            if n.type in ("parameter_declaration", "declaration"):
                for d in n.children_by_field_name("declarator"):
                    if d.type == "init_declarator":
                        d = d.child_by_field_name("declarator")
                    if d is not None:
                        names.add(pointer_flow.declarator_kind(d, raw)[0])
        if len(_DECLARED_NAMES) > 4096:
            _DECLARED_NAMES.clear()
        hit = _DECLARED_NAMES[key] = (raw, frozenset(names))
    return name in hit[1]


def _walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(n.named_children)


_SIDE_EFFECTS = frozenset({"assignment_expression", "update_expression", "call_expression", "gnu_asm_expression"})
_REF_INT = re.compile(r"[-+]?(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*")
# ``en_s_Buzzer_3_Flashing_Long(5)`` / ``ERROR_OK (0)`` — how a reference writes an enumerator with its value (R14)
_REF_NAMED = re.compile(r"([A-Za-z_]\w*)\s*\(\s*([-+]?(?:0[xX][0-9a-fA-F]+|[0-9]+))[uUlL]*\s*\)")
REFERENCE_NO_VALUE = frozenset({"", "-", "—", "N/A", "n/a", "NA"})
# every kind `read_reference_cell` returns — a consumer that maps kinds maps all of them (R26 review X5)
REFERENCE_CELL_KINDS = frozenset({"int", "symbol", "named", "named_unconfirmed", "conflict", "no_value", "function_like",
                                  "not_integer"})


def _ref_int(text):
    text = text.rstrip("uUlL")
    return int(text, 16) if "x" in text.lower() else int(text, 10)


def read_reference_cell(value, constants=None, function_like=()) -> tuple[int | None, str]:
    """(R26) The one reader of a suite cell — an input or an expected value — for the oracle and every measurement script
    (R3 alignment, R4 mutants, R24 replay, the clang checks). Before, the oracle read ``NAME(5)`` in inputs while the
    scripts' reader dropped it in expected cells (R24 review r3 C1). Returns ``(value, kind)``:

    * ``int`` — a number (a spreadsheet value, or decimal/hex text; ``08`` and ``010`` are 8 and 10: a cell is not C
      source),
    * ``symbol`` — a constant's name, read through the unit's current value,
    * ``named`` — ``NAME(5)`` where the unit's ``NAME`` is 5; ``named_unconfirmed`` — the unit does not resolve ``NAME``:
      the value in parentheses is the cell's own statement,

    else ``None`` with ``no_value`` (``-``, ``N/A``, blank — ``NA`` only when the unit defines no constant ``NA``),
    ``conflict`` (``NAME(5)`` where the unit's ``NAME`` is 4 — which value the cell means is unknown), ``function_like``
    (``MS(100)``: a macro call, not the value in its parentheses) or ``not_integer`` (floats, booleans, register text).
    Kinds: `REFERENCE_CELL_KINDS`."""
    if isinstance(value, bool):
        return None, "not_integer"
    if isinstance(value, int):
        return value, "int"
    if isinstance(value, float):
        return (int(value), "int") if value.is_integer() else (None, "not_integer")
    text = str(value if value is not None else "").strip()
    if _REF_INT.fullmatch(text):
        return _ref_int(text), "int"
    constants = constants if constants is not None else {}
    if text and text in constants:
        # before the no-value words: a unit's own ``NA`` is a value (as the readers before R26 read it — review I2)
        known = (constants[text] or {}).get("value")
        return (known, "symbol") if isinstance(known, int) and not isinstance(known, bool) else (None, "not_integer")
    if text in REFERENCE_NO_VALUE:
        return None, "no_value"
    m = _REF_NAMED.fullmatch(text)
    if m is None:
        return None, "not_integer"
    if m.group(1) in set(function_like or ()):
        return None, "function_like"
    stated = _ref_int(m.group(2))
    known = (constants.get(m.group(1)) or {}).get("value")
    if isinstance(known, (int, float)) and not isinstance(known, bool):
        # the unit resolves the name — a float ``K_GAIN`` 1.5 against ``K_GAIN(1)`` is a conflict (review r2 I-b)
        return (stated, "named") if known == stated else (None, "conflict")
    return stated, "named_unconfirmed"


# builtins that evaluate their argument like a function would (same list as `mcdc_design.EVALUATING_BUILTINS`)
_EVALUATING_BUILTINS = frozenset({"__builtin_expect", "__builtin_abs", "__builtin_labs", "__builtin_popcount",
                                  "__builtin_clz", "__builtin_ctz", "__builtin_bswap16", "__builtin_bswap32"})


class _Interp:
    def __init__(self, fn, raw, scope, inputs, parser, shared=None):
        """``shared``: a dict one caller keeps across the vectors of one function (same ``fn``/``raw``/``scope``) — what
        does not depend on the inputs is computed once: the body's address-taken names, macro expansion parses and
        the node lists `check_sequencing` walks (R2c: per-vector re-walking was 40% of a path search)."""
        self.fn, self.raw, self.scope, self.inputs, self.parser = fn, raw, scope, inputs, parser
        self.stubs_used: set[str] = set()   # (R14, R38) callees the sequence stubs (``F() return`` / ``F() p[0]``)
        # (R67 review I-2) const objects / tables whose value came from their definition in another unit — the record's
        #   source hash covers the function's own file only, so the value's footing is named in its assumptions
        self.linked_reads: set[str] = set()
        # (R38) the sequence's stub inputs by callee name (``F() return`` / ``F() p[0]``) — `stub_view` asks per call
        self.stub_keys: dict[str, list[str]] = {}
        for key in inputs or ():
            head, sep, _rest = str(key).partition("() ")
            if sep and head:
                self.stub_keys.setdefault(head, []).append(key)
        # (R17) names a function-body #if took as undefined on build-configuration evidence (see `_scope_assumptions`) —
        # (R62) from the start, those the projection of this function's split conditionals took (no directive is left
        # in its text to record them during the run)
        self.assumed_undefined: set[str] = cpc.projected_assumptions(scope, fn.start_byte)
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
        # (R83) multi-dimensional array objects' dimensions — an element access is bounded, not pointer arithmetic
        self.array_shapes = scope.get("array_shapes") or {}
        # (R39) struct objects whose scalar members are objects of their own (``g.a`` in globals, ``g.b`` in arrays)
        self.struct_globals = scope.get("struct_globals") or {}
        # (R90) union / bit-field objects whose members share one storage (`cpc._storage_object` — laid out when first
        #   asked): their bytes are store keys ``REG.@order:byte`` (`_Bits`), a member's value is read from them
        #   (`read_storage`)
        self.storage = scope.get("storage_globals")
        self.storage_inputs: dict[str, dict] = {}   # root → the row's input bits per layout order (`storage_input_bits`)
        self.storage_used: set[str] = set()   # objects this run read, wrote or observed through the model
        self.storage_volatile_reads: set[str] = set()   # volatile ones among them the run read or observed (registers)
        # (R90 review W1) every volatile storage read, in order (a loop's condition reads are a slice of it), and the
        #   polling loops on such a flag this run assumed to end
        self.volatile_polls: list[str] = []
        # (R90 re-review C-N1 a) the member each of those reads went through (``(root, member path)`` — aligned with
        #   `volatile_polls`): the values a polling loop's way out is searched over (`polling_way_out`)
        self.volatile_poll_members: list[tuple[str, str]] = []
        self.polling_assumed: list[str] = []
        # (R90 re-review I-1) union members narrower than their union the run stored through (root → their spans —
        #   `cpc._storage_layout` ``narrow``), and the objects it then read across bytes such a store left unspecified
        self.storage_narrow: dict[str, set] = {}
        self.storage_unspecified: set[str] = set()
        self.macro_status = scope.get("macro_status") or {}
        self.macro_bodies = scope.get("macro_bodies") or {}
        self.macro_params = scope.get("function_like_macro_params") or {}
        self.fmacro_bodies = scope.get("function_like_macro_bodies") or {}
        effects = scope.get("effects") or {}
        self.closure = effects.get("functions") or {}
        self.address_taken = set(effects.get("address_taken") or ())
        # (R35) name → judgment of an undecided macro (`macro_effectful` / `inert_macro` at the top of a question)
        self.macro_memo: dict[tuple[str, str, int], bool] = self.shared.setdefault("undecided_macro_memo", {})
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
        # (R78) statements whose execution to record — ``{(start, end, type): ("reach", index)}`` (see `run`)
        self.statement_marks: dict = {}
        # (R79) operators whose operands to record (``{(start, end, type): ("operand", index)}`` — `binary`) and
        #   assignments whose replaced value to record (``("write", index)`` — `assign`): where a fault would show
        self.operand_marks: dict = {}
        self.write_marks: dict = {}
        # (R84) one site whose value a propagation check changes — ``(kind, (start, end, type))`` over the function's own
        #   text (`perturbed_binary` · `assign`); None on every other run
        self.perturb: tuple | None = None
        # (R40) pointer parameter → the layout of the pointee the sequence set up for it (`pointee_binding`)
        self.pointees: dict[str, dict] = {}
        # (R81) the names the run is observed by (the row's outputs): a pointee the row observes is set up too
        self.observed: frozenset = frozenset()
        self.observed_only_pointees: set[str] = set()   # set up because observed, though the row sets none of it
        # (R82) harness buffers met so far: base key (`@pointee:p` · `@pointee:msg[0].data`) → the elements the row names
        #   (inputs ∪ observed — the harness allocates what the test names: a write past them is past the buffer), None
        #   for a member the row names by itself (as long as the function reaches)
        self.harness_buffers: dict[str, int | None] = {}
        # (review R82 I-R4-3) the last element index the run reached in each — the size a harness needs for an unbounded one
        self.buffer_reach: dict[str, int] = {}
        # (review R82 I-R5-7) buffers the run indexed by a value it does not know — the reach above may be short of them
        self.buffer_reach_unknown: set[str] = set()
        # (review R82 C1) every one-level pointer member of a set-up pointee (`@pointee:msg[0].data`) — a write that may
        #   reach it rebinds it (`rebind_under`)
        self.pointer_member_keys: set[str] = set()
        self.function_name = ""
        # (R16) interprocedural: the evaluation's `_World` (None = callees are effects only, as before), this
        # activation's parameter keys (a callee's ``@param:x`` must not be the caller's) and its step ceiling.
        self.world: Any = None
        # (R16 review C-R2-1) call sites whose order against another effectful call is unspecified: run as effects only
        self.no_inline: set[tuple] = set()
        self.no_inline_depth = 0
        self.param_prefix = "@param:"
        self.limit = _EXECUTION_BUDGET
        if "fn_names" not in self.shared:
            # (R35 review round 3 C3) parameters, block-scope objects and statics this function declares: an undecided
            # macro whose expansion may name one of them may hand out its address (``&OBJ``, a decaying ``ARR``,
            # ``put(ARR)``) — the text of the macro holds no ``&`` to see
            def declared(d):
                # ``U8 (*cb)(U8)`` / ``U8 (*pfa)[4]``: through the parenthesized declarator too (review round 4 W1)
                while d is not None and d.type != "identifier":
                    d = (next((c for c in d.named_children if c.type != "comment"), None)
                         if d.type == "parenthesized_declarator" else d.child_by_field_name("declarator"))
                return _text(d, raw) if d is not None else ""
            self.shared["fn_names"] = frozenset(
                declared(d) for x in _walk(fn)
                for d in ([x.child_by_field_name("declarator")] if x.type == "parameter_declaration" else
                          [c for c in x.named_children
                           if c.type in {"init_declarator", "identifier", "array_declarator", "pointer_declarator",
                                         "function_declarator", "parenthesized_declarator", "attributed_declarator"}]
                          if x.type == "declaration" else []) if d is not None) - {""}
        self.fn_names = self.shared["fn_names"]
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
            elif cpc.is_name_node(n) and _text(n, raw) in self.macro_status:
                self.body_address_names.update(cpc._MACRO_ADDRESS_RE.findall(self.macro_text_closure(_text(n, raw))))
        self.shared["body_address_names"] = frozenset(self.body_address_names)

    # ── budgets / helpers ────────────────────────────────────────────────────────────────────────
    def raw_tag(self, raw):
        """What a local's key says about the text it is declared in. The function's own unit text is named by its unit
        (R16 review C1: callers in different units handed the same callee text as different buffers — one ``static``
        became two objects); a statement-macro expansion by its buffer, which is kept alive (`kept_raws`)."""
        if raw is self.fn_raw and self.scope.get("path"):
            return "u:" + str(self.scope["path"])
        return f"e{id(raw)}"

    def tick(self):
        self.steps += 1
        if self.steps > self.limit:
            raise Unsupported("execution_budget")

    def lift(self, fn, *args, state=None):
        """cpc operation: UB refuses the evaluation (`undefined` — on ``state``, the path being evaluated, when the
        caller names it), other unresolved results are an unknown value."""
        try:
            return fn(*args)
        except cpc.Unresolved as exc:
            reason = str(exc)
            if reason in _UB_REASONS:
                return self.undefined(state, reason)
            return Unknown(reason)

    def undefined(self, state, kind):
        """(R90 review C1) Undefined behaviour ``kind`` proven on the path ``state``. On the run's only path (no branch on
        an unknown value chose it — `_State.selectors`; ``state`` None: not known) it refuses the evaluation, as before.
        On a path such a branch chose, the run may or may not take it: possible undefined behaviour of the run, as an
        unknown divisor is (when every final path has proven one, no run is without it — refused at the end,
        `_every_path_undefined`) — disclosed (``<kind>_on_unknown_branch(selector=…)``, every branch that chose the path, in
        order — review W1: the last one alone named an open input where a register had chosen the path before it)
        and the faulting operation's result is unknown (the caller: an unknown value, an out-of-bounds write unknown in
        the whole object). The path runs on. It is never dropped: dropping it would take "the program has no undefined
        behaviour" as evidence about the unknown that chose it — ``if (g_mode == 1U) { g_out = g_tbl[5]; } else
        { g_out = 2U; }`` would derive ``g_out = 2`` where ``g_tbl[1]`` in its place leaves it unknown (HDPDM01
        `lin_tl_make_slaveres_pdu`: the path a callee's pointer write chose was the one the real run takes)."""
        if state is None or not state.selectors:
            raise Unsupported("undefined_behavior:" + kind)
        state.possible_ub.add(f"{kind}{FORKED_UB_SUFFIX}(selector={selector_text(state.selectors)})")
        state.ub_proven = state.ub_proven or kind   # every final path with it: no run without it (`_every_path_undefined`)
        return Unknown(FORKED_UB_REASON + kind)

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
            # (R26) the shared cell reader: ``5U``, ``0x1F``, a constant's name, ``ERROR_OK (0)`` (R14)
            value, kind = read_reference_cell(value, self.constants, self.scope.get("function_like_macros"))
            if kind == "conflict":
                return Unknown("input_name_value_conflict:" + name)
            if kind == "function_like":
                return Unknown("input_macro_call_not_a_value:" + name)
            if value is None:
                return Unknown("input_not_an_integer:" + name)
        if isinstance(value, bool) or type(value) is not int:
            return Unknown("input_not_an_integer:" + name)
        if not isinstance(t, dict) or cpc.is_float(t):
            return Unknown("input_type_unmodeled:" + name)
        lo, hi = (0, 1) if t["kind"] == "_Bool" else cpc.type_range(t)
        if t.get("enum"):
            lo, hi = enum_input_range(self.scope, t)   # (R90 review W4)
        if not lo <= value <= hi:
            return Unknown("input_outside_declared_type:" + name)
        return value

    def row_no_value(self, value):
        """Whether a row cell holds nothing (``-``, blank — `REFERENCE_NO_VALUE`)."""
        if value is None:
            return True
        return isinstance(value, str) and read_reference_cell(value, self.constants)[1] == "no_value"

    def row_integer(self, value):
        """Whether a row cell holds an integer value (``5U``, ``0x1F``, a constant's name) — `check_input`'s reading."""
        if isinstance(value, str):
            value, kind = read_reference_cell(value, self.constants, self.scope.get("function_like_macros"))
            if kind in ("conflict", "function_like"):
                return False
        return type(value) is int

    # ── storage ──────────────────────────────────────────────────────────────────────────────────
    def lookup(self, name):
        for frame in reversed(self.lexical):
            if name in frame:
                return frame[name]
        return None

    def initial(self, state, key, base, t, volatile=False):
        if volatile:
            return Unknown("volatile_object:" + base)
        if self.world is not None and (base in self.world.ambiguous or self.world.ambiguous_root(base)):
            # (R16 review W-R2-1) ``static U8 s_init`` in two units: an input named ``s_init`` means neither for sure
            return Unknown("object_name_ambiguous_in_project:" + base)
        if state.havoc_all:
            return Unknown(state.havoc_all)
        root = _root_object(base)   # (R39) a member ``g.s.x`` is written whenever its struct ``g`` is
        if state.havoc_pointer and (base in self.arrays or base in self.address_taken or root in self.address_taken
                                    or (self.world is not None and base in self.world.array_names)):
            return Unknown(state.havoc_pointer)
        if base in state.havoc_bases:
            return Unknown(state.havoc_bases[base])
        for prefix in _object_prefixes(base):   # ``g.s = h`` made every ``g.s.*`` unknown
            if prefix in state.havoc_bases:
                return Unknown(state.havoc_bases[prefix])
        g = self.globals.get(base)
        if g is not None and g.get("const"):
            # (R67 review W-B) a const object the scope does not hold the value of (its initializer did not evaluate, or
            #   it is defined in no unit this one links to): the program's value, not an input — as for tables
            why = (self.scope.get("unresolved_constants") or {}).get(base) or (
                "definition_not_linked" if g.get("declared_only") else "no_initializer_value")
            return Unknown("const_values_unread:" + base + ":" + str(why))
        if key in self.inputs:
            return self.check_input(key, t, self.inputs[key])
        state.initial_reads.add(key)   # (backlog 2-c)
        return Unknown(INITIAL_VALUE_PREFIX + key)

    def read_key(self, state, key, base, t, volatile=False):
        if volatile:
            return Unknown("volatile_object:" + base)
        if key in state.store:
            return state.store[key]
        return self.initial(state, key, base, t)

    def havoc_base(self, state, base, reason):
        if "." in base and not base.startswith("@") and self.storage_root(_root_object(base), world=True) is not None:
            base = _root_object(base)   # (R90) a write to part of a union / bit-field object changes every member of it
        for key in list(state.store):
            if key == base or key.startswith(base + "[") or key.startswith(base + "."):
                state.store[key] = Unknown(reason)
        state.havoc_bases[base] = reason

    def rebind_under(self, state, base):
        """(review R82 C1) A write that may reach the pointer members of a harness object under ``base`` (the member
        itself — ``msg->data = g_buf`` —, the whole object — ``*msg = tmpl`` —, or a write through a pointer that may reach
        it): from here those members point who knows where. What the harness buffer held is no longer what an access
        through them reads (it stays unknown for an observation of it), and an access through them is through an unknown
        pointer, as before R82."""
        # the members are the function under test's (a callee activation writing through a pointer may rebind them too)
        for key in sorted(self.entry_interp().pointer_member_keys):
            if (key == base or key.startswith(base + ".") or key.startswith(base + "[")) and key not in state.rebound:
                state.rebound.add(key)
                self.havoc_base(state, key, "pointer_member_rebound:" + key[len("@pointee:"):])

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
        for base in (state.escaped if not locals_too else {k.split("[", 1)[0]
                                                           for k in self.entry_interp().pointer_member_keys}):
            if base.startswith("@pointee:"):
                self.rebind_under(state, base)   # (review R82 C1) the unknown code may rebind its pointer members
        self.havoc_statics(state, reason)  # unknown code may call back into this function
        # (backlog 2-c review round 3 W1) unknown code may read anything too: no output is unread after it
        state.initial_reads.add(_UNPLACED_READ)
        if not state.havoc_all:
            state.havoc_all = reason
        if self.world is not None:
            self.world.all_havocs += 1

    def havoc_statics(self, state, reason):
        # (R16) with callees interpreted, the static locals of every activation this evaluation ran are in the store:
        # code that may re-enter this function may re-enter any of them too
        statics = self.static_keys if self.world is None else self.world.all_statics() | self.static_keys
        for key in list(state.store):
            if key.split("[", 1)[0] in statics:
                state.store[key] = _havocked(state.store[key], reason)
        for base in statics:
            state.havoc_bases.setdefault(base, reason)

    def havoc_pointer_targets(self, state, reason):
        """A write through a pointer: it reaches only an object whose address was taken somewhere in the project,
        an array (arrays decay to pointers without ``&``) or a local whose address left this function — given that
        an integer converted to a pointer addresses hardware, not a C object (see ``ASSUMPTIONS``) — and (R90 re-review
        5 C-R5-1) every register: the hardware it addresses is where the @-placed registers are (``*(volatile U8 *)
        0x390U``, a global pointer that may hold one)."""
        world = self.world
        arrays, globals_ = self.arrays, self.globals
        other_arrays = world.array_names if world is not None else ()
        other_globals = world.global_names if world is not None else ()
        for key in list(state.store):
            base = key.split("[", 1)[0]
            # (R16 review C4) with callees interpreted, the store holds objects of other units: judged by all of them
            # (R39) a struct member is reachable when its struct's address was taken (``&g`` → ``g.a``)
            if base in state.escaped or base in arrays or base in other_arrays or (
                    (base in globals_ or base in other_globals)
                    and (base in self.address_taken or _root_object(base) in self.address_taken)) or (
                    # (R90) a bit of a union / bit-field object whose address was taken or escaped
                    ".@" in base and (_root_object(base) in state.escaped or _root_object(base) in self.address_taken)):
                state.store[key] = _havocked(state.store[key], reason)
        for base in state.escaped:
            state.havoc_bases.setdefault(base, reason)
            if base.startswith("@pointee:"):
                self.rebind_under(state, base)   # (review R82 C1) a write through a pointer may rebind its pointer members
        # (R90 review C2 · re-review 5 C-R5-1) whatever the project takes the address of: a pointer it cannot follow may
        #   hold an integer address — the hardware, where the registers are
        self.havoc_volatile_storage(state, reason)
        if not state.havoc_pointer:
            state.havoc_pointer = reason
        if world is not None:
            world.pointer_havocs += 1

    def store(self, state, target, val):
        kind = target[0]
        if kind == "key":
            _, key, t, volatile = target
            st = self.storage_member(key)
            if st is not None:
                self.write_storage(state, key, st, val)   # (R90) into the bits every member of the object shares
                return
            if key.startswith("@pointee:") and key.endswith("]"):
                base, _, index = key[:-1].rpartition("[")
                extent = self.harness_buffers.get(base)
                if extent is not None and index.isdigit() and int(index) >= extent:
                    # (review R82 W1 · W-R2-1) past the elements the row names: past the buffer the harness allocated —
                    #   the write may land on any object a pointer reaches (as a write through an unknown pointer), and
                    #   what it wrote is no element of the buffer either
                    state.possible_ub.add("harness_buffer_write_beyond_row")
                    self.havoc_pointer_targets(state, "harness_buffer_write_beyond_row:" + base[len("@pointee:"):])
                    state.store[key] = Unknown("harness_buffer_write_beyond_row:" + base[len("@pointee:"):])
                    return
            if t is None or isinstance(t, Unknown):
                state.store[key] = Unknown("object_type_unresolved")
                return
            state.store[key] = self.convert_to(val, t)
        elif kind == "base":
            self.havoc_base(state, target[1], target[2])
            if str(target[2]).startswith("pointee_write:"):
                self.rebind_under(state, target[1])   # (review R82 C1) `msg->data = …` · `*msg = …`
            elif str(target[2]).startswith("index_unknown") and self.harness_buffers.get(target[1]) is not None:
                # (review R82 W-R3-2) `p[g_idx] = …` on a buffer of the elements the row names: the index may be past
                #   them — as a write past the allocation
                state.possible_ub.add("harness_buffer_write_beyond_row")
                self.havoc_pointer_targets(state, "harness_buffer_write_beyond_row:" + target[1][len("@pointee:"):])
        elif kind == "ptr":
            self.havoc_pointer_targets(state, target[1])
        elif kind == "all":
            self.havoc_everything(state, target[1], locals_too=True)  # the target may be any name in scope

    def convert_to(self, val, t):
        value = _size_value(val)
        if value is not None:
            # (R90) a ``sizeof`` value converts by its value alone (C11 6.3.1.3 — a non-negative value, whatever unsigned
            #   type ``size_t`` is); never stored as the marked unknown it is (`_size_value` reads no stored object)
            if not isinstance(t, dict) or cpc.is_float(t):
                return Unknown("floating_point_unmodeled" if cpc.is_float(t) else "sizeof_unmodeled")
        elif isinstance(val.v, Unknown):
            # Stored with exactly the interval of the value stored — an object reused from another value may carry
            # that value's interval, which must not be stored (review round 6 C1).
            if val.r is None and val.v.range is None:
                return val.v
            return Unknown(val.v.reason, val.r)
        elif cpc.is_float(t) or cpc.is_float(val.t) or val.t is None:
            return Unknown("floating_point_unmodeled" if (cpc.is_float(t) or cpc.is_float(val.t)) else "value_type_unresolved")
        else:
            value = val.v
        if t.get("enum"):
            # An enumeration object's underlying type is implementation-defined (C11 6.7.2.2p4): the stored value
            # is known only if every permitted choice holds it unchanged.
            outs = {repr(self.lift(cpc.convert, value, c)) for c in self.enum_candidates(t)}
            return value if outs == {repr(value)} else Unknown("enum_object_type_implementation_defined")
        return self.lift(cpc.convert, value, t)

    def enum_candidates(self, t=None):
        """(R67) one list for the oracle and constant expressions — (R90 review W4) for the enumeration ``t`` only the
        types that hold every member of it (C11 6.7.2.2p4: ``E_SID_B2 = 0xB2`` rules out ``signed char``)."""
        candidates = cpc.enum_candidates(self.widths)
        span = enum_member_span(self.scope, t) if t is not None else None
        if span is None:
            return candidates
        held = [c for c in candidates if cpc.type_range(c)[0] <= span[0] and span[1] <= cpc.type_range(c)[1]]
        return held or candidates

    # ── function entry ───────────────────────────────────────────────────────────────────────────
    def bind_parameters(self, state, args=None):
        """Parameters from the sequence's inputs — or, for an interpreted callee (R16), from the caller's argument
        values (``args``: `_Val` per argument, in order; a count that does not match refuses the activation)."""
        from generators.mcdc_design import _function_name
        _, fdecl = _function_name(self.fn, self.raw)
        frame: dict[str, dict] = {}
        params = fdecl.child_by_field_name("parameters")
        position = 0
        for p in _named(params):
            if p.type != "parameter_declaration":
                if p.type == "variadic_parameter":
                    raise Unsupported("variadic_function")
                continue
            ident, typ = p.child_by_field_name("declarator"), p.child_by_field_name("type")
            if ident is None:
                continue
            name = cpc._declared_name(ident, self.raw)
            key = self.param_prefix + name
            quals = [_text(c, self.raw) for c in p.named_children if c.type == "type_qualifier"]
            arg = None
            if args is not None:
                if position >= len(args):
                    raise Unsupported("argument_count_mismatch")
                arg = args[position]
            position += 1
            if ident.type == "identifier":
                t = self.type_of(" ".join(quals + [_text(typ, self.raw)]))
                volatile = "volatile" in quals or (isinstance(t, dict) and "volatile" in (t.get("qualifiers") or []))
                info = {"key": key, "type": t if isinstance(t, dict) else None, "volatile": volatile, "kind": "param"}
                if isinstance(t, Unknown):
                    state.store[key] = t
                elif args is not None:
                    # C11 6.5.2.2p7: the argument is converted, as if by assignment, to the parameter's type
                    state.store[key] = self.convert_to(arg, t) if arg is not None else Unknown("argument_missing:" + name)
                elif name in self.inputs:
                    state.store[key] = self.check_input(name, t, self.inputs[name])
                else:
                    state.store[key] = Unknown("parameter_not_in_inputs:" + name)
            else:
                info = {"key": key, "type": None, "pointer": True, "kind": "param"}
                state.store[key] = Unknown("pointer_parameter:" + name)
                pointee = self.pointee_binding(ident, typ, quals, name) if args is None else None
                if pointee is not None:
                    # (R40) the sequence sets up the pointee (``p[0]`` / ``p[0].a``): a harness object of its own that
                    # any write through a pointer may reach (the pointer can be passed on)
                    info["pointee"] = pointee
                    self.pointees[name] = pointee
                    state.store[key] = _Pointer(name)
                    state.escaped.add("@pointee:" + name)
                    self.pointer_member_keys |= {f"@pointee:{name}[0]{p}" for p in (pointee.get("pointers") or {})}
            frame[name] = info
            self.params[name] = info
        if args is not None and position != len(args):
            raise Unsupported("argument_count_mismatch")
        self.lexical.append(frame)

    # ── statements ───────────────────────────────────────────────────────────────────────────────
    def run(self, states, node):
        """Execute ``node`` on every normal state; others pass through. Returns the resulting states."""
        active = [s for s in states if s.mode == "normal"]
        rest = [s for s in states if s.mode != "normal"]
        if not active:
            return states
        self.tick()
        if self.statement_marks and self.raw is self.fn_raw:
            # (R78) a watched statement this path executes: True when no branch on an unknown value came before it
            #   (the path is the run's only one so far — the statement is certainly executed), False when it is one fork
            mark = self.statement_marks.get((node.start_byte, node.end_byte, node.type))
            if mark is not None:
                for s in active:
                    s.decisions.append((mark, ("outcome", not s.forks)))
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
            verdict = cpc.pp_condition(self.scope, n, raw, self.assumed_undefined)
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
                s.selectors.append(reason)       # (R90 review C1)
                other.selectors.append(reason)
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
        size = _size_value(val)
        if size is not None:
            return bool(size)   # (R90) a ``sizeof`` value: its value is known, whatever its type
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
            if pending and self.world is not None and _endless(n, cond, self.raw, self):
                # (R16 review C-R2-3) ``while (1U) {}`` with no way out: the path never returns to its caller — what
                # a test observes then is not a return state. Refused, never assumed to return.
                raise Unsupported("non_terminating_loop")
            exits_before = len(done)
            try:
                return self.loop_iterations(pending, done, first, cond, body, update, n)
            except Unsupported as exc:
                # (R16 review C-R3-3) a loop whose controlling expression is constant is not one the implementation may
                # assume to terminate (C11 6.8.5p6): out of budget with no path out yet, it may never end — never
                # assumed to return. (W-R4-3) once some path left it (a polled register), the caller's fallback stands.
                # (R90 re-review 3 W-R3-3) a budget reason may name what spent it (``execution_budget:polling_…``)
                if self.world is not None and str(exc).split(":", 1)[0] in _BUDGET_REASONS \
                        and len(done) == exits_before and _constant_condition(cond, self.raw, self):
                    raise Unsupported("constant_condition_loop_unfinished") from exc
                raise
        finally:
            self.lexical.pop()

    def loop_iterations(self, pending, done, first, cond, body, update, node=None):
        iterations = 0
        # (R90 review W1, W4) ``polled``: the registers the last condition read when it let no path out; ``last``: the paths
        #   at the start of that iteration — the next one starting from the very same paths runs the same forever
        polled, prev, last = frozenset(), None, None
        # (R90 re-review C-N1 b, c) decided at the FIRST iteration whose condition polled a register and let no path out:
        #   "" — the condition left the paths as they came to it, its body (+ update) left them as the condition did and
        #   read no polled register, so the state after the loop is the same however many polls the flag takes; else why
        #   the loop is not assumed to end (the state after it would depend on when the hardware changes the flag).
        #   ``cond_read_register``: the last condition read a register — the paths before the next one are kept to compare
        #   (as in the first iterations: a loop that never polls pays for a few)
        verdict, members, cond_read_register = None, (), False
        body_reads: set[str] = set()   # (re-review 4 C-R4-3) registers the body (+ update) read, every iteration
        while pending:
            iterations += 1
            if iterations > _LOOP_BUDGET:
                raise Unsupported("loop_iteration_budget")
            prev = [_state_key(s) for s in pending] if polled else None
            if prev is not None and prev == last:
                if verdict:
                    raise Unsupported(verdict)
                return self.polling_exit(pending, done, polled, node, cond, members, body_reads)
            last = prev
            pre = None
            if verdict is None and not first and cond is not None and (cond_read_register or iterations <= 8):
                # by path: a path the condition lets out has nothing to compare (re-review 3 I-R3-1)
                pre = dict(zip((id(s) for s in pending), prev if prev is not None else [_state_key(s) for s in pending],
                               strict=True))
            mark = len(self.volatile_polls)
            if not first and cond is not None:
                pending, exits = self.branch(pending, cond)
                done.extend(exits)
            cond_read_register = len(self.volatile_polls) > mark
            # (snapshots are taken only after a condition that read a register and kept a path) — (re-review 3 I-R3-1)
            #   whatever it let out leaves as any exit does: a flag the model reads as unknown (``while (RSTA == 1U) {}``
            #   after another such loop) lets a copy out each iteration and keeps the path the hardware has to end
            polled = frozenset(self.volatile_polls[mark:]) if pending and cond is not None else frozenset()
            members = tuple(dict.fromkeys(self.volatile_poll_members[mark:])) if polled else ()
            first = False
            if not pending:
                break
            stay = [_state_key(s) for s in pending] if polled and verdict is None else None
            if stay is not None and (pre is None or [pre.get(id(s)) for s in pending] != stay):
                # ``while ((FLW_RSTA == 0U) && (step() != 0U))`` with ``step`` counting: the poll itself changes what the
                #   next one sees (a first poll whose paths were not kept to compare is not checked — not assumed either)
                verdict = "polling_loop_condition_changes_state" if pre is not None else "polling_loop_first_poll_unchecked"
            body_mark = len(self.volatile_polls)
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
            body_reads.update(self.volatile_polls[body_mark:])
            if polled and not verdict:
                # (C-N1 c) a body that reads the flag sees a value that depends on when the hardware changes it — (re-review
                #   3 C-R3-2) through a callee the run interprets too (its reads are merged into this activation's)
                flag_reads = polled.intersection(self.volatile_polls[body_mark:])
                if flag_reads:
                    verdict = "polling_loop_body_reads_flag:" + "+".join(sorted(flag_reads))
            if stay is not None and verdict is None:
                # (C-N1 b) ``if (n < 3U) { n++; } else { err = 1U; }``: the paths a poll keeps are not the paths the next
                #   poll sees — the loop's last iteration is not what the program leaves after k polls
                verdict = "" if [_state_key(s) for s in pending] == stay else "polling_loop_body_changes_state"
            if len(done) + len(pending) > _PATH_BUDGET:
                raise Unsupported("path_budget")
        return done

    def switch_layout(self, n, body) -> list:
        """(R90 review) `switch_items` of the switch ``n``, once per function: ``shared`` is kept for one ``fn`` / ``raw`` /
        ``scope`` across the vectors and loop passes, and the layout rests on the unit's preprocessing only, never on the
        inputs. The names its verdicts took as undefined are kept with it and added to every run that uses it (each run
        records its own); an undecided group's refusal is kept as a refusal."""
        memo = self.shared.setdefault("switch_layouts", {})
        key = (n.start_byte, n.end_byte)
        hit = memo.get(key)
        if hit is None:
            assumed: set[str] = set()
            try:
                hit = ("ok", self.switch_items(_named(body) if body is not None else [], [], assumed), frozenset(assumed))
            except Unsupported as exc:
                hit = ("refused", str(exc), frozenset(assumed))
            memo[key] = hit
        self.assumed_undefined |= hit[2]
        if hit[0] == "refused":
            raise Unsupported(hit[1])
        return hit[1]

    def switch_items(self, nodes, out: list, assumed: set) -> list:
        """(R90) The switch body as the compiler reads it: ``("label", case_statement)`` and ``("stmt", node)`` in source
        order. A conditional group with a ``case`` / ``default`` label in an arm (``#if (LIN_PROTOCOL == PROTOCOL_21)``
        around five ``case`` labels — HDPDM01 ``lin_tl_make_slaveres_pdu`` / ``lin_tl_attach_service``) is replaced by the
        arm the unit's preprocessing decides (`cpc.pp_condition` — the verdict `statement` gives a group between
        statements, with its assumptions); the other arm is absent. Undecided → ``conditional_compilation_unresolved``.
        So is a group holding a declaration (in scope at every later label, `_SWITCH_EAGER`). A group with neither stays
        one statement (`statement` decides it when a path reaches it). The parser ends a
        case's statement list at a directive, so the group and the statements after its ``#endif`` are children of the
        switch body: in source order they belong to the label before them, as for the compiler (before R90 they made
        the whole switch `switch_body_statement_outside_case`). A group is never a child of a ``case_statement`` in
        this grammar; walking a case's children keeps the order should one be."""
        for x in nodes:
            if x.type == "comment":
                continue
            if x.type == "case_statement":
                value = x.child_by_field_name("value")
                out.append(("label", x))
                self.switch_items([c for c in x.named_children if c != value], out, assumed)
                continue
            if x.type == "preproc_else":   # the arm a decided group chose (below)
                self.switch_items(x.named_children, out, assumed)
                continue
            if x.type in _PP_GROUPS and _group_holds(x, _SWITCH_EAGER):
                verdict = cpc.pp_condition(self.scope, x, self.raw, assumed)
                if verdict is None:
                    raise Unsupported("conditional_compilation_unresolved")
                cond, name, alt = (x.child_by_field_name(f) for f in ("condition", "name", "alternative"))
                arm = [c for c in x.named_children if c not in (cond, name, alt)] if verdict else \
                    ([alt] if alt is not None else [])
                self.switch_items(arm, out, assumed)
                continue
            out.append(("stmt", x))
        return out

    def polling_exit(self, pending, done, polled, node, cond=None, members=(), body_reads=frozenset()):
        """(R90 review W1) A loop that, on the paths it runs, reads a register flag and changes nothing — ``while
        (ADC0FLWCTL_RSTA == big_SET) {}``: under the model (a register is memory) it never ends; on the target the hardware
        clears the flag. The run goes on as if it did: the polled registers hold an unknown value after the loop, nothing
        else changes, and the record says so (`STORAGE_POLLING_ASSUMPTION`) — a harness must stub or simulate the flag.
        (R90 re-review C-N1 a) Only when, on every path the loop keeps, some value of the polled registers makes the
        condition false without changing anything else (`polling_way_out`): a condition no register value can end
        (``FLW_RSTA <= 1U``) never ends on the target either. (re-review 3 W-R3-2) The registers the condition reads only
        for another flag value (``(RSTA == 1U) || (B_RSTA == 1U)``) are polled too: unknown after the loop as well.
        (re-review 4 C-R4-3) ``body_reads``: the registers the body (+ update) read in any iteration — one of the final
        polled registers among them is a body that reads the flag (as `loop_iterations` refuses for the condition's own),
        and the members the search added are reads of this loop on the target (an enclosing loop's body read them)."""
        extra_ub: set[str] = set()
        roots = set(polled)
        searched: list[tuple[str, str]] = []
        for s in pending:
            why, ub, read = self.polling_way_out(s, cond, members)
            if why:
                raise Unsupported(why)
            extra_ub |= ub
            roots |= {r for r, _p in read}
            searched.extend(m for m in read if m not in members and m not in searched)
        flag_reads = roots & set(body_reads)
        if flag_reads:
            raise Unsupported("polling_loop_body_reads_flag:" + "+".join(sorted(flag_reads)))
        for root, path in searched:   # aligned lists (`read_storage`)
            self.volatile_polls.append(root)
            self.volatile_poll_members.append((root, path))
        line = node.start_point[0] + 1 if node is not None else 0
        self.polling_assumed.append(f"{self.function_name or '?'}:{line}:{'+'.join(sorted(roots))}")
        for s in pending:
            for root in sorted(roots):
                self.havoc_base(s, root, "polling_loop_exit_assumed:" + root)
            s.possible_ub |= extra_ub   # what the condition may do with the value the hardware leaves
            s.mode = "normal"
            done.append(s)
        return done

    def polling_way_out(self, state, cond, members):
        """(R90 re-review C-N1 a) ``("", possible undefined behaviour, polled members)`` when some value of the polled
        members (``(root, member path)``) lets the path ``state`` out of the loop: the condition, evaluated on a copy of the
        path with them set to it, is false — and every value tried leaves the path as it was (the state after the loop
        does not depend on which one the hardware leaves). Else ``(why not, …)``. A member of at most 8 bits takes every
        value, a wider one 0, all ones and the inverse of what it holds; the product over the members is bounded
        (`_POLL_SEARCH_BUDGET`). (re-review 3 W-R3-2) A member the condition reads only under another value (the short
        circuit of ``(RSTA == 1U) || (BUSY == 1U)``) joins the members and the search runs again — only a search that
        varied every member the condition read, each over all its values, proves that no value ends the loop
        (``non_terminating_loop``). Each probe is hypothetical (`hypothetical`): what it records is put back. (re-review
        4) Nothing is kept from one search for another: every run searches (its steps are its own)."""
        if cond is None or not members:
            return "polling_flag_unmodeled", set(), ()
        return self.polling_search_rounds(state, cond, list(members))

    def polling_search_rounds(self, state, cond, members):
        """(re-review 3 W-R3-2) `polling_search` until no new member is read (at most `_POLL_MEMBER_ROUNDS` searches)."""
        result = None
        for _round in range(_POLL_MEMBER_ROUNDS):
            result = self.polling_search(state, cond, members)
            if isinstance(result, str):
                return result, set(), ()
            new = [m for m in result[4] if m not in members]
            if not new:
                break
            members = members + new
        else:
            # a member still came up in the last search: its values were not varied — no proof either way
            return "polling_loop_exit_search_incomplete", set(), ()
        out, undetermined, ub, exhaustive, _new = result
        if out:
            return "", ub, members
        if undetermined:
            return "polling_loop_exit_undetermined:" + undetermined, set(), ()
        return ("non_terminating_loop" if exhaustive else "polling_loop_exit_not_found"), set(), ()

    def polling_search(self, state, cond, members):
        """One search over the values of ``members``: ``(a way out found, why undetermined, possible UB, every value
        tried, members read that are not among them)`` — or the reason it cannot run or must refuse."""
        choices, exhaustive = [], True
        for root, path in members:
            st = self.storage_member(f"{root}.{path}", world=True)
            if st is None:
                return "polling_flag_unmodeled:" + root
            w = st[2]["width"]
            if w <= 8:
                values = list(range(1 << w))
            else:
                exhaustive = False
                full = (1 << w) - 1
                held = self.storage_value(state, root, st[1], st[2], f"{root}.{path}", observe=True)
                # (re-review 4 I-R4-1) and the value it holds: another member varied beside it
                values = list(dict.fromkeys([0, full] + ([held & full, ~held & full] if type(held) is int else [])))
            choices.append((st, values))
        total = math.prod(len(v) for _st, v in choices)
        if total > _POLL_SEARCH_BUDGET:
            return f"polling_loop_exit_search_budget:{total}"
        out, undetermined, ub, new = False, "", set(), []
        for combo in itertools.product(*(v for _st, v in choices)):
            with self.hypothetical():
                c = state.copy(records=False)
                # (re-review 5 W-R5-1) undefined behaviour on a flag value raises here whatever branch chose the path (F5
                #   `selectors`): every value is the run's own question — `polling_flag_value:` discloses it
                c.selectors, c.ub_proven = [], ""
                for (st, _v), value in zip(choices, combo, strict=True):
                    self.store_bits(c, st[0], st[1], st[2], value)
                before = _state_key(c)
                mark = len(self.volatile_poll_members)
                try:
                    truth = self.truth(self.full_expression_value(c, cond, self.raw))
                except Unsupported as exc:
                    if str(exc) == "execution_budget":
                        # (re-review 3 W-R3-3) the run's budget went on hypothetical polls: say so
                        raise Unsupported("execution_budget:polling_way_out_search") from exc
                    if str(exc).split(":", 1)[0] in _BUDGET_REASONS:
                        raise
                    undetermined = undetermined or str(exc)
                    if str(exc).startswith("undefined_behavior:"):
                        # undefined on a value the hardware may leave: possible on the run, never proven on it
                        ub.add("polling_flag_value:" + str(exc).split(":", 1)[1])
                    truth = _PROBE_FAILED
                new.extend(m for m in self.volatile_poll_members[mark:] if m not in members and m not in new)
                if truth is _PROBE_FAILED:
                    continue
                if _state_key(c) != before:
                    # ``(FLW == 0U) || (g_x = 5U, 0)``: the poll that ends the loop (or one with another value of the
                    #   flag) writes what the polls the loop kept did not — the state after it depends on the flag's values
                    return "polling_loop_condition_changes_state"
                if truth is None:
                    undetermined = undetermined or "condition_unknown_for_a_flag_value"
                elif not truth:
                    out = True
                    ub |= c.possible_ub - state.possible_ub
        return out, undetermined, ub, exhaustive, new

    @contextlib.contextmanager
    def hypothetical(self):
        """(R90 re-review 3 W-R3-1) A run that is not the program's — a probe of the polling way-out search: everything
        it records on this activation and on the world (callee failures, effects-only and inline counts, admitted units,
        stubs, storage and polling records, register reads, harness buffers, …) is put back after it, and no decision is
        observed on it (as `record_decision`'s probes). A callee that fails on a hypothetical flag value has not failed
        for the real run. The steps it spends stay spent (the budget is the run's). (re-review 4 X5) Every attribute of an
        activation and of the world is in one of the lists or in `_HYPOTHETICAL_EXEMPT` with why it needs no putting back
        — a structural test holds the lists to the constructors."""
        tables = [getattr(self, a) for a in _HYPOTHETICAL_TABLES]
        world = self.world
        growing: list = []
        if world is not None:
            tables += [getattr(world, a) for a in _HYPOTHETICAL_WORLD_TABLES]
            growing = [(d, len(d)) for d in (getattr(world, a) for a in _HYPOTHETICAL_WORLD_GROWING)]
        saved = [_table_copy(t) for t in tables]
        saved_watch, self.watch = self.watch, None
        try:
            yield
        finally:
            self.watch = saved_watch
            for live, old in zip(tables, saved, strict=True):
                _table_restore(live, old)
            for d, n in growing:
                if len(d) != n:
                    for k in list(itertools.islice(d, n, None)):
                        del d[k]

    def switch(self, states, n):
        raw = self.raw
        body = n.child_by_field_name("body")
        # (R90) labels and statements after deciding the conditional groups that hold labels (`switch_items`)
        cases: list[tuple[Any, list]] = []
        for kind, x in self.switch_layout(n, body):
            if kind == "label":
                cases.append((x, []))
            elif not cases:
                raise Unsupported("switch_body_statement_outside_case")
            else:
                cases[-1][1].append(x)
        # (R16b review R2 WR2-3) a label inside a block of an earlier case (``else { case 3U: … }``) is a jump target
        # of this switch too — only direct labels are modelled, so such a switch is not interpreted
        stack = [x for _c, stmts in cases for x in stmts]
        while stack:
            x = stack.pop()
            if x.type == "case_statement":
                raise Unsupported("case_label_in_nested_block")
            if x.type != "switch_statement":   # a nested switch's labels are its own
                stack.extend(_named(x))
        labels = []
        for c, _stmts in cases:
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
            reason = ""
            if isinstance(val.v, Unknown) or not isinstance(val.t, dict):
                reason = "branch_on_unknown:" + (val.v.reason if isinstance(val.v, Unknown) else "switch_type")
            else:
                # (R67 review W-R4-3) an enumeration promotes to int or unsigned int — for its values (0..127 here)
                #   either converts every label alike, so the labels convert to the plain promoted type
                ct = {k: v for k, v in cpc.promote(val.t, self.widths).items() if k != "enum"}
                cv = self.lift(cpc.convert, val.v, ct)
                lvs = [None if lab is None else self.lift(cpc.convert, lab.v, ct) for lab in labels]
                if isinstance(cv, Unknown):
                    reason = "branch_on_unknown:" + cv.reason
                elif not any(lv is not None and not isinstance(lv, Unknown) and lv == cv for lv in lvs):
                    # (R67 review C-R3-1 · W-R4-3) converted labels are distinct (C11 6.8.4.2p3), so an exact match is
                    #   certain; with none, a label that did not convert may be the one — no default by accident
                    bad = next((lv for lv in lvs if isinstance(lv, Unknown)), None)
                    if bad is not None:
                        reason = "branch_on_unknown:" + bad.reason
            if reason:
                targets = sorted(set(range(len(cases))) if None in labels else set(range(len(cases))) | {-1})
                for i, target in enumerate(targets):
                    t = s if i == 0 else s.copy()
                    t.forks.append(reason)
                    t.selectors.append(reason)   # (R90 review C1)
                    (ended if target == -1 else entering.setdefault(target, [])).append(t)
                continue
            chosen = None
            for i, lv in enumerate(lvs):
                if lv is not None and not isinstance(lv, Unknown) and lv == cv:
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
            skipped_decls: list = []
            for i, (_c, stmts) in enumerate(cases):
                for s in entering.get(i, []):
                    # (R16b review C2) a jump to this label passes the declarations of the earlier cases: their names
                    # are in scope to the end of the switch block (C11 6.2.1p4) — a later ``cnt`` is that local, not a
                    # global of the same name — but their initializers did not run (6.8.4.2p7)
                    for d in skipped_decls:
                        self.declaration(s, d, skipped=True)
                running = running + entering.get(i, [])
                skipped_decls.extend(stmt for stmt in stmts if stmt.type == "declaration")
                for stmt in stmts:
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

    def declaration(self, state, n, skipped=False):
        """``skipped``: the declaration was jumped over (a later ``case``) — its name is in scope, its initializer
        did not run: a non-static local holds an indeterminate value, a static one its persistent state."""
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
            key = f"@local:{name}@{self.raw_tag(raw)}:{target.start_byte}"  # one macro expansion ≠ another (round 2 H)
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
                if value is None or skipped:
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
                        "volatile": volatile, "kind": "local", "type_name": _text(typ, raw) if typ is not None else ""}
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
                    if value is not None and not skipped:
                        self.initializer(state, value, raw, 0)
                    state.havoc_bases[key] = "local_array_length_unresolved:" + name
                    continue
                for i in range(length):
                    state.store[f"{key}[{i}]"] = Unknown("uninitialized_local:" + name)
                if skipped:
                    continue
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
                if value is not None and not skipped:
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
                    x.type in _SIDE_EFFECTS or (cpc.is_name_node(x) and _text(x, raw) in self.macro_status)
                    for x in nodes)
            if plain:
                return
        writes = [x for x in nodes if x.type in {"assignment_expression", "update_expression"}]
        idents = [x for x in nodes if cpc.is_name_node(x) and not (
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

        def through_pointer(name, w):
            """A write target that is not a named object (``*p``, ``p[i]`` on a pointer, an unknown name)."""
            if not name:
                return True
            node = _unwrap(w.child_by_field_name("left" if w.type == "assignment_expression" else "argument"))
            if node is not None and node.type == "identifier" and name not in self.macro_status and (
                    (self.lookup(name) is not None and not self.lookup(name).get("extern")) or name in self.globals
                    or name in self.arrays or name in (self.scope.get("unresolved_globals") or {})):
                # (R90) ``p++`` · ``p = q``: the pointer object itself is written, not what it points to — HDPDM01
                #   `sf_Crc32Cal` ``crc = s_Crc32Table[(crc ^ *p++) & 0xFFu] ^ (crc >> 8u)`` was refused as a write
                #   through ``p`` beside a read of the table (no access of ``p`` but the increment's own)
                return False
            info = self.lookup(name)
            if info is not None and not info.get("extern"):
                # ``PT q`` (``typedef U8 *PT``) resolves to no scalar type: it may be a pointer (round 4 C2)
                return bool(info.get("pointer")) or (info.get("type") is None and not info.get("array"))
            return name not in self.globals and name not in self.arrays

        def reachable(name):
            info = self.lookup(name)
            if info is not None and not info.get("extern"):
                key = info.get("key", "")
                if info.get("pointee") and "@pointee:" + name in state.escaped:
                    return True   # (review R40 W2) ``p->a`` beside ``*g_ptr = …``: g_ptr may point into the pointee
                return key in state.escaped or name in escaping or name in self.body_address_names
            return name in self.arrays or name in self.address_taken or name in escaping or (
                name not in self.globals and name in (self.scope.get("unresolved_globals") or {}))

        def inside(a, b):
            return b.start_byte <= a.start_byte and a.end_byte <= b.end_byte and _key(a) != _key(b)

        for i, w1 in enumerate(writes):
            t1 = target(w1)
            p1 = through_pointer(t1, w1)
            for w2 in writes[i + 1:]:
                nested = inside(w2, w1) or inside(w1, w2)
                t2 = target(w2)
                p2 = through_pointer(t2, w2)
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
        plain_target = store_through = None
        if n.type == "assignment_expression":
            # The object the assignment stores to (``g``, ``arr[i]``, ``s.f``): its base name designates storage and
            # the store is sequenced after the call — only the index expressions inside are reads.
            left = _unwrap(n.child_by_field_name("left"))
            base = left
            while base is not None and base.type in {"subscript_expression", "field_expression"} \
                    and not any(ch.type == "->" for ch in base.children):
                base = _unwrap(base.child_by_field_name("argument"))
            if base is not None and base.type == "identifier":
                info = self.lookup(_text(base, raw)) or {}
                if info.get("pointer") and isinstance(state.store.get(info.get("key")), _Pointer):
                    # (review R40 round 2 W-B) ``p[0].a = f(&p)``: on a known pointer the store's address computation
                    #   reads ``p`` — unsequenced with the call (an array's name only designates storage). Through an
                    #   unknown pointer the store is a write through any pointer whichever ``p`` it uses (round 3 I-1)
                    store_through = _key(base)
                else:
                    plain_target = _key(base)
            elif left is not None and _text(n.child_by_field_name("operator"), raw) == "=" \
                    and self.pointee_target(state, left, raw) is not None:
                # (review R40 W1) ``p->a = f(…)``: the pointee the store lands in is not read and the store follows the
                # call (C11 6.5.16p3) — beside the call only the pointer ``p`` itself is read
                pointer = left
                while pointer is not None and pointer.type != "identifier":
                    pointer = _unwrap(pointer.child_by_field_name("argument"))
                store_through = _key(pointer) if pointer is not None else None
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
                if self.is_cast_call(c, raw):
                    continue  # ``(T)(x)`` is a cast
                callee = "<indirect>"  # ``(*fp)()`` / ``(fp)()``: unknown code (round 3 C5)
            for x in idents:
                if inside(x, c) or _key(x) == plain_target or _sequenced_apart(x, c, raw):
                    continue
                if self.call_may_write(callee, self.resolve_alias(_text(x, raw)), state, escaping,
                                       pointee=_key(x) != store_through):
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
            if not any(cpc.is_name_node(x) and _text(x, raw) in self.macro_status and not self.macro_constant(_text(x, raw))
                       and not self.inert_macro(_text(x, raw)) for x in _walk(left)):
                top.add(_key(_unwrap(root.child_by_field_name("right"))))
        if self.world is not None:
            self.mark_unordered_calls(nodes, raw, inside, state)
        # (R38) a call the sequence stubs writes nothing a pointer argument cannot reach (`stub_call_inert`): whichever
        # order it runs in, what the macro reads is the same
        nested = [x for x in nodes if _key(x) not in top and (
            x.type in {"assignment_expression", "update_expression", "gnu_asm_expression"}
            or (x.type == "call_expression" and not self.is_cast_call(x, raw) and not self.pure_macro_call(x, raw)
                and not self.stub_call_inert(x, raw)))]
        if nested:
            for x in nodes:
                name = _text(x, raw) if cpc.is_name_node(x) else ""
                if name in self.macro_status and not self.macro_constant(name) and not self.transparent_macro(name) \
                        and not self.inert_macro(name):
                    raise Unsupported("macro_in_order_dependent_expression:" + name)

    def mark_unordered_calls(self, nodes, raw, inside, state):
        """(R16 review C-R2-1, C-R3-1/2) A call's body runs indeterminately sequenced with the rest of its full expression
        (C11 6.5.2.2p10): ``Rd() - Rd()``, ``Rd() + (g_in = 5U)``, ``Rd() + (Ext(), 0U)``. Interpreting it in text order
        would present one order's result as the program's. A project call (or a function-like macro whose arguments
        hold one — its expansion runs from another buffer) that is unordered with a write, with unknown code, or with an
        effectful call runs as effects only (its result unknown), as it would without a world."""
        sites = []   # (node, markable, effectful, kind)
        for x in nodes:
            if x.type in {"assignment_expression", "update_expression", "gnu_asm_expression"}:
                sites.append((x, False, True, "write"))
            elif x.type == "call_expression" and not self.is_cast_call(x, raw):
                f = x.child_by_field_name("function")
                name = _text(f, raw) if f is not None and f.type == "identifier" else ""
                if name and name in self.macro_status:
                    if name in self.macro_params:
                        args = x.child_by_field_name("arguments")
                        inner = [c for c in _walk(args) if c.type == "call_expression"] if args is not None else []
                        if inner:
                            sites.append((x, True, True, "macro"))
                elif name and name in self.closure:
                    sites.append((x, True, self.world.effectful(name, self.closure), "call"))
                else:
                    sites.append((x, False, True, "unknown"))   # no definition we model, or an indirect call
        for x in nodes:
            if x.type == "assignment_expression" and _op(x, raw) not in {"=", ""}:
                # (review C-R4-1) ``g op= f()``: the read of ``g`` is unsequenced with ``f()``'s body — a callee that
                # may write ``g`` makes the result order-dependent (C11 6.5.16p3, 6.5.2.2p10). A target no callee can
                # reach (``u8t_err |= Check()``, a local whose address never left) keeps the call interpreted.
                right = x.child_by_field_name("right")
                left = x.child_by_field_name("left")
                base = cpc._base_identifier(left, raw) if left is not None else ""
                plain = left is not None and _unwrap(left) is not None and _unwrap(left).type == "identifier"
                for node, markable, effectful, kind in sites:
                    if not (markable and effectful and right is not None and right.start_byte <= node.start_byte
                            and node.end_byte <= right.end_byte):
                        continue
                    if kind == "call" and base and plain:
                        f = node.child_by_field_name("function")
                        if not self.call_may_write(_text(f, raw), self.resolve_alias(base), state):
                            continue
                    self.no_inline.add((id(raw), node.start_byte, node.end_byte))
        if len(sites) < 2:
            return
        for i, (a, ma, ea, _ka) in enumerate(sites):
            for b, mb, eb, _kb in sites[i + 1:]:
                if not (ma or mb) or not (ea or eb):
                    continue
                if inside(a, b) or inside(b, a) or _sequenced_apart(a, b, raw):
                    continue   # nested: an argument (or assigned value) is evaluated before its call (store)
                for node, markable in ((a, ma), (b, mb)):
                    if markable:
                        self.no_inline.add((id(raw), node.start_byte, node.end_byte))

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

    def inert_macro(self, name, depth=0):
        """(R35) An undecided object-like macro that reads no object, writes nothing and calls nothing in any definition
        the tree has (numbers, type names, constants, other inert macros): its value is unknown, but no order of
        evaluation can change it. (``union["writes"]`` is also refused earlier — `check_sequencing` rejects an
        effectful macro before it asks this — and is kept here so the judgment stands on its own.)"""
        if depth > 8 or self.macro_status.get(name) == "active" or name in self.macro_params:
            return False
        if ("inert", name, depth) in self.macro_memo:
            return self.macro_memo[("inert", name, depth)]
        union = cpc.undecided_macro_view(self.scope, name)
        verdict = not (union is None or union.get("function_like") or union["writes"] or "names" not in union) and all(
            t in {"sizeof"} or self.macro_constant(t) or isinstance(self.type_of(t), dict) or cpc.base_kind(t) is not None
            or (t != name and t in self.macro_status and self.inert_macro(t, depth + 1)) for t in union["names"])
        # keyed by depth: the verdict is then a function of (name, depth) alone — a cut-off reached from one question
        # never answers another asked shallower (review round 3 W1: row order changed cells)
        self.macro_memo[("inert", name, depth)] = verdict
        return verdict

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
        """``(T)(x)`` — tree-sitter's parse of a cast whose type is a typedef name — is a cast when ``T`` names a type.
        (R26) The one judgement: evaluation (`call`), sequencing, the effect questions (`operand_effectful`,
        `atom_effectful`, `mark_unordered_calls`) and the loop-constant walk all ask it — and (R31) the robustness rows'
        compared-constant walk (`boundary_rows.compared_constants`), through `cast_call_operand`."""
        return cast_call_operand(c, raw, self.scope) is not None

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
        # (R62 review W1) a header included after the function changes the table there too, not only the unit's own text
        return cpc.macro_changed_after(self.scope, name, self.fn.start_byte)

    def prescan_nodes(self, roots, raw, depth):
        if depth > 8:
            raise Unsupported("macro_expansion_depth")
        for root in roots:
            for n in _walk(root):
                if cpc.is_name_node(n) and self.defined_after_function(_text(n, raw)):
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
        if depth > 8:
            return True
        if self.macro_status.get(name) != "active":
            # (R35) an undecided macro whose every definition in the tree neither writes nor calls — and none hides
            # what it does from the text scan (`cpc.undecided_macro_view`) — expands to something effect-free whichever
            # one the build picks (``#ifdef __MISRA__ TRUE 1u #else TRUE 1``)
            if ("effectful", name, depth) in self.macro_memo:
                return self.macro_memo[("effectful", name, depth)]
            union = cpc.undecided_macro_view(self.scope, name)
            calls = set(union["calls"]) if union is not None else set()
            verdict = union is None or union["writes"] or union.get("reach_names") is None \
                or bool(set(union["reach_names"]) & self.fn_names) \
                or any(
                c not in {"sizeof", "defined"} and (c not in self.macro_status or self.macro_effectful(c, depth + 1))
                and not isinstance(self.type_of(c), dict) for c in sorted(calls)) or any(
                # a macro of this unit it mentions is expanded too (a build -D the tree union does not know; I4)
                t != name and t in self.macro_status and self.macro_effectful(t, depth + 1)
                for t in sorted(set(union.get("names", ())) - calls))
            # keyed by depth: deterministic whatever was asked before (review round 3 W1)
            self.macro_memo[("effectful", name, depth)] = verdict
            return verdict
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

    def call_may_write(self, callee, obj, state, escaping=frozenset(), pointee=True):
        """Could a call to ``callee`` change the object an identifier ``obj`` names here? ``pointee``: for a pointer
        parameter whose pointee the sequence set up, the question is about that pointee (``p->a``) unless the
        identifier only designates where a store lands (`check_sequencing`) — then about the pointer ``p`` itself."""
        closure = self.closure.get(callee)
        pointee_info = self.lookup(obj)
        if pointee and pointee_info is not None and pointee_info.get("pointee"):
            # (R40) ``p->a`` beside ``f(…)``: f may write the pointee through any pointer (p passed on, stored)
            view = self.stub_view(callee)
            if view is not None:
                return view["pointer"]
            if closure is None or closure.get("pointer_write") or closure.get("unknown_callees"):
                return True
            # (review R40 C1) a write to a name that is no modeled object is a write through it — ``g_q[0].cnt = 5U``
            #   through a global pointer that may hold p (the same judgment as the call's own havoc)
            return bool(self.opaque_writes(closure))
        view = self.stub_view(callee)
        if view is None and self.volatile_register_operand(obj):
            # (R90 re-review 4 C-R4-4) the hardware may change a register while the callee runs — it may wait on one
            #   (a poll), or reach one the closure cannot name: beside any call but a sequence stub's, a register read is
            #   indeterminately sequenced with the call (C11 6.5.2.2p10)
            return True
        if view is not None:
            # (R38) a sequence stub (`stubbed_call`) writes no global or static and runs nothing — at most what a
            # pointer argument reaches
            closure = {"writes": [], "unknown_callees": [], "reaches": [], "pointer_write": view["pointer"]}
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
        pointer = closure.get("pointer_write") or self.opaque_writes(closure)
        reachable = escaped or obj in self.arrays or obj in self.address_taken or obj in escaping or (
            obj not in self.globals and obj not in self.arrays)
        return bool(pointer and reachable)

    def volatile_register_operand(self, name):
        """(R90 re-review 4 C-R4-4) Does the operand ``name`` read a volatile union / bit-field object — the object
        (``REG_FLW`` of ``REG_FLW.Byte``) or a macro of one of its members (``#define FLW REG_FLW.Byte``)?"""
        if not name or self.lookup(name) is not None:
            return False
        if self.macro_status.get(name) == "active" and name not in self.macro_params:
            m = re.match(r"[\s(]*([A-Za-z_]\w*)\s*\.", self.macro_bodies.get(name, ""))
            if m is None:
                return False
            name = m.group(1)
        return self.storage_volatile(name)

    def opaque_writes(self, closure):
        """A written name that is not a modeled scalar or array object (a pointer, a struct with pointer members) may
        be written *through* — to an object the closure cannot name. Sorted: the first names the havoc."""
        return sorted(w for w in closure.get("writes") or ()
                      if w not in self.globals and w not in self.arrays and not self.plain_struct(w))

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
        if k == "null":
            # (R40) ``NULL`` (a keyword node to tree-sitter) is the project's macro; ``nullptr`` a null pointer
            text = _text(n, raw).strip()
            if text == "nullptr":
                return _Val(_Pointer(None), None)
            return self.read_identifier(state, text, n, raw, depth)
        if k in cpc.NAME_NODE_TYPES:
            # (R35) ``TRUE``/``FALSE`` (and ``true``/``false``) parse as keywords, but the preprocessor sees names — a
            #   project's ``#define TRUE 1U`` (Processor Expert drivers, KJPDS02_PV) or <stdbool.h>. Read it as the
            #   identifier it is: a macro the unit defines gives its value, anything else stays unknown
            return self.read_identifier(state, _text(n, raw), n, raw, depth)
        if k == "cast_expression":
            type_text = _text(n.child_by_field_name("type"), raw)
            head = re.match(r"\s*([A-Za-z_]\w*)\s*\(", type_text)
            if head and head.group(1) not in _TYPE_WORDS and not isinstance(self.type_of(head.group(1)), dict):
                # (R16 review C-R3-4, W-R4-2) ``(Inc()) + 1U`` parses as a cast of ``+1U`` to the "type" ``Inc()``: the
                # call would never run. A name that is no type followed by ``(`` is that misparse — refused. A real
                # type (``void (*)(void)``, ``U8 (*)[4]``) keeps the old behaviour: an unknown value.
                raise Unsupported("cast_parse_of_parenthesized_expression")
            if "*" in type_text:
                # (R40) a cast to a pointer type keeps a known pointer; the constant 0 becomes the null pointer
                inner = self.expression(state, n.child_by_field_name("value"), raw, depth + 1)
                if isinstance(inner.v, _Pointer):
                    return inner
                if isinstance(inner.v, int) and not isinstance(inner.v, bool) and inner.v == 0:
                    return _Val(_Pointer(None), None)
                return _Val(inner.v if isinstance(inner.v, Unknown) else Unknown("pointer_cast"), None)
            t = self.type_of(type_text)
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
            arg = n.child_by_field_name("argument")
            if arg is not None and arg.type == "call_expression" and self.is_cast_call(arg, raw) \
                    and len(_named(arg.child_by_field_name("arguments"))) == 1:
                # (R82) ``(T)(d)[k]`` — tree-sitter takes the cast-call ``(T)(d)`` as what is subscripted; C binds the
                #   subscript first: ``(T)((d)[k])`` (`LINTP_MF_GET_LEN(d)` reads both length bytes of a LIN frame so).
                #   ``(T)(a, b)[k]`` (a comma expression, two named arguments) stays as it was
                inner = _named(arg.child_by_field_name("arguments"))[0]
                node, eraw = self.macro_node("(" + _text(inner, raw) + ")[" + _text(n.child_by_field_name("index"), raw) + "]")
                if node is not None:
                    return self.cast(self.expression(state, node, eraw, depth + 1),
                                     self.type_of(_text(_named(arg.child_by_field_name("function"))[0], raw)))
            target = self.lvalue(state, n, raw, depth)
            return self.read_target(state, target)
        if k == "field_expression":
            pt = self.pointee_target(state, n, raw)
            if pt is not None:
                return self.read_pointee_access(state, *pt)
            path = self.member_path(n, raw)
            if path is not None and path in self.globals:
                g = self.globals[path]
                return _loaded(self.read_key(state, path, path, g["type"], g.get("volatile")), g["type"])
            st = self.storage_member(path) if path is not None else None
            if st is not None:
                return self.read_storage(state, path, st)   # (R90)
            if path is not None and path in self.arrays:
                return _Val(Unknown("array_value:" + path), None)   # decays to a pointer, as a named array does
            base = self.expression_base_effects(state, n, raw, depth)
            # (backlog 2-c review W1) ``p->a`` through an unknown pointer, ``s.a`` of an unmodeled object: a read
            if "->" in _text(n, raw):
                state.initial_reads.add(_ANY_POINTER_READ)
            else:
                self.record_unplaced_read(state, base)
            return _Val(Unknown("field_unmodeled:" + base), None)
        if k == "pointer_expression":
            op = _text(n, raw).lstrip()[:1]
            if op == "&":
                base = self.address_of(state, n.child_by_field_name("argument"), raw, depth)
                if base and base[0] != "@" and self.storage_root(_root_object(base), world=True) is not None:
                    return _Val(Unknown(_STORAGE_ADDRESS + _root_object(base)), None)   # (R90 review C2)
                return _Val(Unknown("address_value"), None)
            pt = self.pointee_target(state, n, raw)
            if pt is not None:
                return self.read_pointee_access(state, *pt)
            self.expression(state, n.child_by_field_name("argument"), raw, depth + 1)
            state.initial_reads.add(_ANY_POINTER_READ)   # (backlog 2-c review W1) ``*p``, p unknown
            return _Val(Unknown("pointer_dereference"), None)
        if k == "call_expression":
            return self.call(state, n, raw, depth)
        if k == "sizeof_expression":
            return self.sizeof_value(n, raw)   # (R90)
        if k == "alignof_expression":
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

    def pointee_binding(self, ident, typ, quals, name):
        """(R40) The pointee layout of pointer parameter ``name`` (``T *name``, one level) when the sequence sets one of
        its values (``name[0]`` / ``name[0].a`` — a harness allocates it) or (R81) observes it (`observes_pointee`);
        None otherwise: the pointer stays unknown."""
        if ident.type != "pointer_declarator":
            return None
        inner = ident.child_by_field_name("declarator")
        if inner is None or inner.type != "identifier" or typ is None:
            return None
        prefix = name + "[0]"
        if name in self.inputs and not self.row_no_value(self.inputs[name]):
            return None   # (review R40 W4) the row states the pointer itself (``NULL``, an address): not a harness object
        sets = any((k == prefix or str(k).startswith(prefix + ".") or str(k).startswith(prefix + "[")
                    or _is_buffer_element(k, name)) and self.row_integer(self.inputs[k]) for k in self.inputs)
        if not sets and not self.observes_pointee(name):
            return None   # (review R40 W4) only a value the row really sets (not ``-``) implies the harness allocated it
        core = " ".join(w for w in _text(typ, self.raw).split() if w not in {"const", "volatile"})
        layout = (self.scope.get("pointee_types") or {}).get(core)
        if not layout or layout.get("reason"):
            return None
        if not sets:
            self.observed_only_pointees.add(name)   # (review R81 W3) said in the record's assumptions
        # (R82) a scalar pointee is a harness buffer: `p[k]` is an element of its own (`pData[1]` — the reference sets
        #   both bytes a frame parser reads); `*p` / `p[0]` is its first
        buffer = set(layout.get("members") or {}) == {""} and not layout.get("arrays")
        return {**layout, "const": "const" in quals, "volatile": "volatile" in quals, "buffer": buffer}

    def observes_pointee(self, name):
        """(R81) Whether the row observes what pointer parameter ``name`` points to — an output naming its pointee
        (``p[0]`` · ``p[0].a`` · ``p[0].b[2]``) or the parameter itself (a design's output table names the out-parameter,
        not its pointee): a test that states what the function leaves there allocates the object (an expected value on
        ``p[0].a`` needs one). An out-parameter the function only writes is otherwise never set up — its writes land
        nowhere the model can place and the observation is unknown (R40 left `out[0]` to this round)."""
        prefix = name + "[0]"
        return any(o == name or o == prefix or o.startswith(prefix + ".") or o.startswith(prefix + "[")
                   or _is_buffer_element(o, name) for o in self.observed)

    def pointee_target(self, state, n, raw):
        """(R40) ``(target, path)`` of an access to a known pointer's pointee — ``*p`` · ``p[0]`` · ``p->a`` ·
        ``(*p).a`` · ``p[0].a`` · ``p->s.x`` — or None (not through a known pointer). Through null: undefined."""
        parts = []
        while True:
            while n is not None and n.type == "parenthesized_expression" and len(_named(n)) == 1:
                n = _named(n)[0]
            if n is None:
                return None
            if n.type == "field_expression":
                field = n.child_by_field_name("field")
                if field is None:
                    return None
                parts.append(_text(field, raw))
                arrow = any(c.type == "->" for c in n.children)
                n = n.child_by_field_name("argument")
                if arrow:
                    base = n
                    break
                continue
            if n.type == "pointer_expression" and _text(n, raw).lstrip().startswith("*"):
                base = n.child_by_field_name("argument")
                break
            if n.type == "subscript_expression":
                index = n.child_by_field_name("index")
                if index is None or index.type != "number_literal" or _text(index, raw).strip().rstrip("uUlL") != "0":
                    return None
                base = n.child_by_field_name("argument")
                break
            return None
        while base is not None and base.type == "parenthesized_expression" and len(_named(base)) == 1:
            base = _named(base)[0]
        if base is None or base.type != "identifier":
            return None
        info = self.lookup(_text(base, raw))
        if info is None or not info.get("pointer"):
            return None
        value = state.store.get(info["key"])
        if not isinstance(value, _Pointer):
            return None
        if value.target is None:
            self.undefined(state, "null_pointer_dereference")   # (R90 review C1) a chosen path: through an unknown pointer
            return None
        return value.target, "".join("." + x for x in reversed(parts))

    def pointee_object(self, target, path, state=None):
        """(R40) What ``target[0]<path>`` is: ``("leaf", key, type, volatile)``, ``("array", key, type, length,
        volatile)`` or ``("other", key)`` (the whole pointee, a nested struct, an unmodeled member)."""
        layout = self.pointees.get(target) or {}
        key = f"@pointee:{target}[0]{path}"
        volatile = bool(layout.get("volatile"))
        rec = (layout.get("members") or {}).get(path)
        if rec is not None:
            return ("leaf", key, rec["type"], volatile or bool(rec.get("volatile")))
        rec = (layout.get("arrays") or {}).get(path)
        if rec is not None:
            return ("array", key, rec["type"], rec["length"], volatile or bool(rec.get("volatile")))
        rec = (layout.get("pointers") or {}).get(path)
        name = f"{target}[0]{path}"
        if rec is not None and not (state is not None and key in state.rebound) and self.names_buffer(name, member=True):
            # (R82) a one-level pointer member of the harness object (`RespMsg->data`) the row names (the member itself —
            #   the SwUDS lists `RespMsg->data` — or an element `p[0].data[k]`; review R82 W1: else the harness leaves it
            #   unset): the harness points it to a buffer of its own (the reference sets `RespMsg[0].data` to a
            #   VectorCAST buffer). Not once a write may have rebound it (review R82 C1). Recorded when the run reaches it
            #   (review R82 W-R3-3: an observation alone puts no buffer in the row's assumptions); a member the row names
            #   by itself stays as long as the function reaches though the extended profile adds element columns too
            #   (review R82 W-R3-1: R80 · the prior-value pass name `data[0]` — the design still names `data`)
            if state is not None:
                self.harness_buffers.setdefault(
                    key, None if any(str(k).strip() == name for k in (*self.inputs, *self.observed))
                    else self.buffer_extent(name))
            return ("array", key, rec["type"], HARNESS_BUFFER_LENGTH, volatile or bool(rec.get("volatile")))
        return ("other", key)

    def names_buffer(self, name, member=False):
        """(R82) Whether the row names harness buffer ``name`` (``msg[0].data`` · ``p``): an element ``name[k]`` it sets
        or observes, or — a pointer member — the member itself."""
        return any((member and str(k).strip() == name) or _element_index(k, name) is not None
                   for k in (*self.inputs, *self.observed))

    def buffer_extent(self, name):
        """(review R82 W1) How many elements of harness buffer ``name`` the harness allocated: up to the last one the row
        sets or observes (``pData[1]`` → 2; a pointer member the row names itself is as long as the function reaches —
        `pointee_object`, review R82 W-R2-1 · W-R3-1). The model
        reads past them (an element the row does not set is unknown); a write past them is a write past the buffer
        (`store`)."""
        return max((i + 1 for k in (*self.inputs, *self.observed) for i in [_element_index(k, name)] if i is not None),
                   default=0)

    def read_pointee_access(self, state, target, path):
        obj = self.pointee_object(target, path, state)
        if obj[0] == "leaf":
            return _loaded(self.read_pointee(state, obj[1], obj[2], obj[3]), obj[2])
        if obj[0] == "array":
            return _Val(Unknown("array_value:" + obj[1][len("@pointee:"):]), None)
        state.initial_reads.add(_BASE_READ + str(obj[1]))   # (backlog 2-c review W1) an unmodeled part of it
        return _Val(Unknown("pointee_member_unmodeled:" + obj[1][len("@pointee:"):]), None)

    def read_pointee(self, state, key, t, volatile=False):
        """(R40) A pointee value: stored, or what the sequence set (``p[0].a``) unless a write may have reached it."""
        if volatile:
            return Unknown("volatile_object:" + key[len("@pointee:"):])
        if key in state.store:
            return state.store[key]
        if state.havoc_all:
            return Unknown(state.havoc_all)
        root = key.split("[", 1)[0]
        for base in [root, key.rsplit("[", 1)[0] if key.endswith("]") else ""] + _object_prefixes(key):
            if base and base in state.havoc_bases:
                return Unknown(state.havoc_bases[base])
        name = key[len("@pointee:"):]
        if name in self.inputs:
            return self.check_input(name, t, self.inputs[name])
        state.initial_reads.add(key)   # (backlog 2-c)
        return Unknown(INITIAL_VALUE_PREFIX + name)

    def pointer_compare(self, op, left, right):
        """(R40) ``p == NULL`` · ``p != q``: known pointers compare by what they point to (each pointer parameter's
        pointee is a harness object of its own); a null pointer constant is ``0``. Anything else is unknown."""
        def as_pointer(v):
            if isinstance(v.v, _Pointer):
                return v.v
            if isinstance(v.v, int) and not isinstance(v.v, bool) and v.v == 0:
                return _Pointer(None)
            return None
        a, b = as_pointer(left), as_pointer(right)
        if op not in ("==", "!=") or a is None or b is None:
            return _Val(Unknown("pointer_operation_unmodeled"), None)
        equal = a.target == b.target
        return _Val(int(equal if op == "==" else not equal), self.int_t)

    def plain_struct(self, name):
        """(R39) A modeled struct object with no pointer or unmodeled member: a write to it is a write to its members
        (`havoc_base` covers ``name.*``), never one through something the members do not name. (R90) A union / bit-field
        object the storage model lays out holds integers only: the same."""
        rec = self.struct_globals.get(name)
        return (rec is not None and not rec.get("opaque_members")) or self.storage_root(name) is not None

    # ── (R90) union / bit-field storage objects ─────────────────────────────────────────────────────────────────────
    # A union object (a register ``REG_X`` with ``Byte`` / ``Word`` / ``Bits.TEN`` / ``Overlap_STR…`` members) or a struct
    # with bit-fields is one storage: its bytes are store keys ``REG_X.@order:byte`` (`_Bits` — the bits the run wrote)
    # for each layout the target may use
    # (`cpc.STORAGE_ORDERS` — byte order and bit-field unit; an 8-bit register has one), a member's value is read from
    # the bits it occupies and is known only when every layout gives the same one. A bit the run did not write holds what
    # the row's inputs set (any member, or the object's name for its whole-object member), else it is unknown. A volatile
    # one (a register) is read as memory: the VectorCAST harness holds it as an ordinary object.
    def storage_root(self, root, world=False):
        """(R90) The storage layout of object ``root`` as this unit sees it — with ``world``, else as the unit of an
        activation of this run that declares it (an observable the entry's unit does not see). None when ``root`` is
        no such object here (a local or a macro of that name hides it, a layout the model cannot state)."""
        if not root or root[0] == "@" or root in self.macro_status or self.lookup(root) is not None:
            return None
        table = self.storage
        layout = table[root] if table is not None and root in table else None
        if layout is None and world and self.world is not None:
            layout = self.world.storage_layout(root)
        if layout is not None and self.world is not None:
            self.world.same_storage(root, layout)
        return layout

    def storage_member(self, path, world=False):
        """(R90) ``(root, layout, leaf)`` when ``path`` names a scalar member of a storage object (``REG.Bits.TEN``)."""
        if "." not in path or path[0] == "@" or "[" in path:
            return None
        root, _, rest = path.partition(".")
        layout = self.storage_root(root, world)
        leaf = layout["leaves"].get(rest) if layout is not None else None
        return (root, layout, leaf) if leaf is not None else None

    def storage_refusal(self, root):
        """(R90) Why ``root`` — a union / bit-field object a unit of this run declares — has no layout, or ""."""
        table = self.storage
        if table is not None and root not in table:
            why = (self.scope.get("storage_unresolved") or {}).get(root)
            if why:
                return why
        return self.world.storage_refusal(root) if self.world is not None else ""

    def storage_observable(self, name):
        """(R90) What an observable names in a storage object: ``(root, layout, leaf, member path)`` — the object itself
        is its whole-object member (``Byte`` / ``Word``) —, an Unknown with the reason when it is one the model gives no
        value of, None when it names no union / bit-field object."""
        root = name.split(".", 1)[0]
        layout = self.storage_root(root, world=True)
        if layout is None:
            why = self.storage_refusal(root)
            return Unknown(f"storage_layout_unmodeled:{root}:{why}") if why else None
        if name == root:
            path = layout.get("whole")
            if path is None:
                return Unknown("storage_whole_object_member_ambiguous:" + root)
        else:
            path = name[len(root) + 1:]
            if path not in layout["leaves"]:
                return Unknown("observable_not_a_storage_member:" + name)
        return root, layout, layout["leaves"][path], path

    def storage_base(self, state, root):
        """(R90) Why the bits of ``root`` the run did not write are unknown on this path (`initial`'s judgment), or None
        — then they hold what the row's inputs set."""
        if self.world is not None and (root in self.world.ambiguous or root in self.world.ambiguous_roots):
            return "object_name_ambiguous_in_project:" + root
        if state.havoc_all:
            return state.havoc_all
        if state.havoc_pointer and (root in self.address_taken or root in state.escaped):
            return state.havoc_pointer
        for base, why in state.havoc_bases.items():
            if base == root or base.startswith(root + "."):
                return why   # (re-review 4) a havoc of this object names its own reason before the any-register mark
        if _VOLATILE_STORAGE in state.havoc_bases and self.storage_volatile(root):
            # (R90 review C2) a pointer write may have landed on any register — (re-review 4 C-R4-1) or a callee the run
            #   did not interpret may have waited on one
            return state.havoc_bases[_VOLATILE_STORAGE]
        return None

    def storage_volatile(self, root):
        """(R90 review C2) Whether ``root`` is a volatile union / bit-field object (a register)."""
        layout = self.storage_root(root, world=True) if root and root[0] != "@" else None
        return bool(layout and layout.get("volatile"))

    def havoc_volatile_storage(self, state, reason):
        """(R90 review C2) A write through a pointer that may alias a register: every volatile union / bit-field object
        holds an unknown value from here (its stored bytes, and through `storage_base` the ones it did not write).
        (re-review 5 I-R5-4) Every callee the run did not interpret is named on the mark
        (``register_read_by_callee_not_interpreted:A+B``) — the first alone named one where several left the registers
        unknown; another cause keeps the first one's name."""
        for key in list(state.store):
            if ".@" in key and self.storage_volatile(_root_object(key)):
                state.store[key] = _havocked(state.store[key], reason)
        first = state.havoc_bases.get(_VOLATILE_STORAGE)
        if first is None:
            state.havoc_bases[_VOLATILE_STORAGE] = reason
        elif first != reason and first.startswith(_CALLEE_REGISTERS) and reason.startswith(_CALLEE_REGISTERS):
            names = first[len(_CALLEE_REGISTERS):].split("+")
            if reason[len(_CALLEE_REGISTERS):] not in names:
                state.havoc_bases[_VOLATILE_STORAGE] = first + "+" + reason[len(_CALLEE_REGISTERS):]

    def storage_input_bits(self, root, layout):
        """(R90) The object's bits as the row's inputs set them, per layout order: 0 / 1, a reason (a value the member
        cannot hold, two inputs that disagree on the bit, an input naming no member) or None (no input sets it). An input
        names a member (``REG.Bits.TEN``, ``REG.Byte``) or the object (``REG`` — its whole-object member). Two inputs may
        set one bit (``REG.Byte`` and ``REG.Bits.TEN``): the harness sets both in an order of its own, so a bit they
        disagree on is unknown."""
        cached = self.storage_inputs.get(root)
        if cached is not None:
            return cached
        n = layout["size"] * 8
        bits = {o: [None] * n for o in layout["orders"]}
        bad: dict[str, dict[int, str]] = {o: {} for o in layout["orders"]}
        prefix = root + "."
        for key, raw_value in (self.inputs or {}).items():
            key = str(key)
            if key == root:
                path = layout.get("whole")
                if path is None:
                    for o in bad:
                        for m in range(n):
                            bad[o].setdefault(m, "storage_whole_object_member_ambiguous:" + root)
                    continue
            elif key.startswith(prefix):
                path = key[len(prefix):]
                if path not in layout["leaves"]:
                    for o in bad:
                        for m in range(n):
                            bad[o].setdefault(m, "input_names_no_member:" + key)
                    continue
            else:
                continue
            leaf = layout["leaves"][path]
            t = {**leaf["type"], "bits": leaf["width"], "signed": False} if leaf["bitfield"] else leaf["type"]
            value = self.check_input(key, t, raw_value)
            for o in bits:
                for k, m in enumerate(leaf["bits"][o]):
                    if isinstance(value, Unknown):
                        bad[o].setdefault(m, value.reason)
                    elif bits[o][m] is None:
                        bits[o][m] = (value >> k) & 1
                    elif bits[o][m] != (value >> k) & 1:
                        bad[o].setdefault(m, "input_members_disagree:" + root)
        for o, reasons in bad.items():
            for m, why in reasons.items():
                bits[o][m] = why
        self.storage_inputs[root] = bits
        return bits

    def storage_value(self, state, root, layout, leaf, name, observe=False):
        """(R90) The member's value: the same under every layout order (else unknown — which byte order or bit-field
        unit the target uses decides it), each bit as the run last wrote it, or as the inputs set it. An unwritten bit
        no input sets is an initial value the row lacks (``INITIAL_VALUE_PREFIX + name``) — a read of the object (2-c)
        unless ``observe``."""
        why = self.storage_base(state, root)
        inputs = self.storage_input_bits(root, layout) if why is None else None
        values, reason, initial = set(), "", False
        # (R90 review C1) a signed member that is no bit-field (the model takes none) reads its bits in two's complement
        sign = 1 << (leaf["width"] - 1) if not leaf["bitfield"] and leaf["type"].get("signed") else 0
        store = state.store
        for o in layout["orders"]:
            v, bytes_ = 0, {}
            for k, m in enumerate(leaf["bits"][o]):
                byte, i = divmod(m, 8)
                if byte not in bytes_:
                    bytes_[byte] = _byte_state(store.get(f"{root}.@{o}:{byte}"))
                written, known, value, why_written = bytes_[byte]
                if written >> i & 1:
                    b = (value >> i & 1) if known >> i & 1 else why_written
                else:
                    b = why if why is not None else inputs[o][m]   # what the object held before the run
                if type(b) is int:
                    if v is not None:
                        v |= b << k
                    continue
                if b is None:
                    initial = True
                else:
                    reason = reason or str(b)
                v = None
            if v is not None and v & sign:
                v -= sign << 1
            values.add(v)
        if initial and not observe:
            state.initial_reads.add(_BASE_READ + root)
        if None in values:
            return Unknown(reason or INITIAL_VALUE_PREFIX + name)
        if len(values) != 1:
            return Unknown("storage_member_layout_dependent:" + name)
        return values.pop()

    def storage_read_type(self, leaf):
        """(R90) The type a member's value has as an operand: a bit-field narrower than ``int`` is an ``int`` (C11
        6.3.1.1p2); one of all its type's bits (at least ``int``'s) is of its type; any other width is the
        implementation's (None)."""
        t = leaf["type"]
        if not leaf["bitfield"]:
            return t
        w, int_bits = leaf["width"], self.int_t["bits"]
        if w < int_bits:
            return self.int_t
        return t if w == t.get("bits") and w >= int_bits else None

    def read_storage(self, state, key, st, observe=False, name=None):
        """(R90) Read the member ``key`` of a storage object (``st``: `storage_member`)."""
        root, layout, leaf = st
        self.storage_used.add(root)
        if layout.get("volatile"):
            # (review W3) an observed one too: its expected value rests on the harness holding it as memory
            self.storage_volatile_reads.add(root)
            if not observe and leaf.get("volatile", True):
                # (review W1) what a loop condition reads (`loop_iterations`) — (re-review W-N1) through a volatile
                #   lvalue: a plain member of a type with a volatile one is no read the compiler must repeat
                self.volatile_polls.append(root)
                self.volatile_poll_members.append((root, key[len(root) + 1:]))
        spans = self.storage_narrow.get(root)
        if spans and root not in self.storage_unspecified:
            # (re-review I-1) a byte of the union outside the narrow member stored through: C11 6.2.6.1p7
            covered = {m // 8 for o in layout["orders"] for m in leaf["bits"][o]}
            if any(uo <= b < uo + us and not mo <= b < mo + ms for mo, ms, uo, us in spans for b in covered):
                self.storage_unspecified.add(root)
        t = self.storage_read_type(leaf)
        if t is None:
            return _Val(Unknown("bit_field_promotion_implementation_defined:" + key), None)
        value = self.storage_value(state, root, layout, leaf, name or key, observe)
        span = (0, (1 << leaf["width"]) - 1) if leaf["bitfield"] and isinstance(value, Unknown) else None
        return _Val(value, t, span)

    def write_storage(self, state, key, st, val):
        """(R90) Store ``val`` into the member ``key``: converted to it (a bit-field keeps its low ``width`` bits — the
        model takes no signed one), then into the bits it occupies under every layout order — what the other members of
        the object read from there on."""
        root, layout, leaf = st
        self.storage_used.add(root)
        if leaf.get("narrow"):
            self.storage_narrow.setdefault(root, set()).add(tuple(leaf["narrow"]))   # (re-review I-1)
        if leaf["bitfield"]:
            if isinstance(val.v, Unknown):
                new = Unknown(val.v.reason)
            elif val.t is None or cpc.is_float(val.t) or type(val.v) is not int:
                new = Unknown("floating_point_unmodeled" if cpc.is_float(val.t) else "value_type_unresolved")
            else:
                new = val.v % (1 << leaf["width"])
        else:
            new = self.convert_to(val, leaf["type"])
            if isinstance(new, Unknown):
                new = Unknown(new.reason)   # a bit holds no interval
            elif type(new) is not int:
                new = Unknown("value_type_unresolved")
        self.store_bits(state, root, layout, leaf, new)

    def store_bits(self, state, root, layout, leaf, new):
        """(R90) ``new`` — an int (its low bits, two's complement) or an Unknown — into the bits ``leaf`` occupies, under
        every layout order."""
        for o in layout["orders"]:
            touched: dict[int, list] = {}
            for k, m in enumerate(leaf["bits"][o]):
                byte, i = divmod(m, 8)
                if byte not in touched:
                    touched[byte] = list(_byte_state(state.store.get(f"{root}.@{o}:{byte}")))
                rec, bit = touched[byte], 1 << i
                rec[0] |= bit
                if type(new) is int:
                    rec[1] |= bit
                    rec[2] = (rec[2] & ~bit) | ((new >> k & 1) << i)
                else:
                    rec[1] &= ~bit
                    rec[3] = new.reason
            for byte, (written, known, value, reason) in touched.items():
                state.store[f"{root}.@{o}:{byte}"] = _Bits(written, known, value, reason if written & ~known else "")

    def storage_written(self, state, st):
        """(R90) Did the run write a bit the member occupies (through it or another member of the object)?"""
        root, layout, leaf = st[0], st[1], st[2]
        for o in layout["orders"]:
            for m in leaf["bits"][o]:
                if _byte_state(state.store.get(f"{root}.@{o}:{m // 8}"))[0] >> (m % 8) & 1:
                    return True
        return False

    def stored_value(self, state, target):
        """The value an object holds right after a store to it (``target``: a ``key`` lvalue) — (R90) a storage
        member's is read back from its bits."""
        st = self.storage_member(target[1])
        if st is not None:
            return self.read_storage(state, target[1], st, observe=True).v
        return state.store[target[1]]

    def member_path(self, n, raw):
        """(R39) ``g.a`` · ``g.s.x`` · ``(g).a`` on a struct object whose members are modeled (`struct_globals`): the
        member's flattened name, or None — ``->`` (through a pointer), a parameter or local struct, a macro standing
        for the object, a subscript on the way (an array of structs) are not modeled members."""
        parts = []
        while True:
            while n.type == "parenthesized_expression" and len(_named(n)) == 1:
                n = _named(n)[0]
            if n.type != "field_expression":
                break
            if any(c.type == "->" for c in n.children):
                return None
            field = n.child_by_field_name("field")
            if field is None:
                return None
            parts.append(_text(field, raw))
            n = n.child_by_field_name("argument")
            if n is None:
                return None
        if not parts or n.type != "identifier":
            return None
        name = _text(n, raw)
        if (name not in self.struct_globals and self.storage_root(name) is None) or name in self.macro_status \
                or self.lookup(name) is not None:
            return None   # (R90) or a member of a union / bit-field object the storage model lays out
        return name + "." + ".".join(reversed(parts))

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
            if c.get("kind") == "const_object_linked":
                self.linked_reads.add(f"{name} ({os.path.basename(str(c.get('file') or ''))})")
            return _Val(c["value"], c["type"])
        if name in self.globals:
            g = self.globals[name]
            return _loaded(self.read_key(state, name, name, g["type"], g.get("volatile")), g["type"])
        if name in self.arrays:
            return _Val(Unknown("array_value:" + name), None)
        # (backlog 2-c review round 2 W1) a whole struct object (``t = g_s``), an unmodeled global, a name the model
        #   cannot resolve: a read — of that object, or of what the name may stand for
        self.record_unplaced_read(state, name)
        return _Val(Unknown(self.unresolved_reason(name)), None)

    def record_unplaced_read(self, state, text):
        """(backlog 2-c review round 2 W1) A read of what ``text`` names that the model does not evaluate: the object it
        names (a global, an array, a struct, a local — read as a whole), what a macro it names may read, or — anything
        else — a read nothing can be reported as unread after."""
        m = _OBJECT_PATH_RE.match(str(text or "").strip())
        word = m.group(0) if m else ""
        root = word.split(".", 1)[0]
        if root and root in self.macro_status and self.lookup(root) is None:
            self.record_macro_reads(state, root)
        elif root and (self.lookup(root) is not None or root in self.globals or root in self.arrays
                       or root in (self.scope.get("unresolved_globals") or {}) or root in self.struct_globals):
            state.initial_reads.add(_BASE_READ + word)
        else:
            state.initial_reads.add(_UNPLACED_READ)

    def record_macro_reads(self, state, name):
        """(backlog 2-c review round 2 W1) What a macro the model does not evaluate may read (`macro_read_marks`). A
        decision observation run observes no output, so it records nothing (review round 3 W2 — the MC/DC search
        evaluates the same macros on thousands of vectors)."""
        if self.watch is not None:
            return
        memo = self.shared.setdefault("macro_read_marks", {})
        marks = memo.get(name)
        if marks is None:
            marks = memo[name] = self.macro_read_marks(name)
        state.initial_reads |= marks

    def macro_read_marks(self, name):
        """Every name the macro's definition mentions and, through the macros those name, theirs (an undecided macro:
        every definition the tree has — `cpc.undecided_macro_view`) as part-read marks; an unplaced read when that is
        not the whole story (no body, token pasting, opaque text, a missing include, a build ``-D``). Iterative, once
        per macro and function (memoised in ``shared`` — the unit's macro table does not change between vectors)."""
        marks: set[str] = set()
        seen: set[str] = set()
        stack = [name]
        while stack:
            m = stack.pop()
            if m in seen:
                continue
            seen.add(m)
            if self.macro_status.get(m) == "active":
                body = self.macro_bodies.get(m)
                if body is None:
                    body = self.fmacro_bodies.get(m)
                if body is None or "#" in body:
                    return frozenset({_UNPLACED_READ})
                names = re.findall(r"\b[A-Za-z_]\w*\b", body)
            else:
                view = cpc.undecided_macro_view(self.scope, m)
                if view is None or "names" not in view:
                    return frozenset({_UNPLACED_READ})
                names = list(view["names"])
            for t in names:
                marks.add(_BASE_READ + t)
                if t in self.macro_status and t not in seen:
                    stack.append(t)
        return frozenset(marks)

    def unresolved_reason(self, name):
        if name in (self.scope.get("unresolved_globals") or {}):
            return f"global_unmodeled:{name}:{self.scope['unresolved_globals'][name]}"
        if name in (self.scope.get("unresolved_constants") or {}):
            return f"constant_unresolved:{name}:{self.scope['unresolved_constants'][name]}"
        if name in (self.scope.get("typedef_names") or ()) and name not in (self.scope.get("macro_status") or {}):
            # (R67) a type name read as a value: the grammar split a cast ``(T)`` from its operand (``(U16)-1 + (U16)+2``
            #   parses as ``((U16) - 1 + (U16)) + 2``) — not an undeclared identifier. (review I-7) a typedef the model
            #   cannot use as a scalar (a pointer, a struct) is said so
            from generators.mcdc_design import _scope_type
            try:
                scalar = isinstance(_scope_type(self.scope, name), dict)
            except cpc.Unresolved:
                scalar = False
            return ("cast_operand_split_by_grammar:" if scalar else "cast_type_unmodeled:") + name
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
            self.record_macro_reads(state, name)   # (backlog 2-c review round 2 W1) and it may read
            return _Val(Unknown(reason), None)
        self.check_sequencing(state, node, eraw)  # the expansion's own order (``g_x + g_x++``; round 2 B)
        return self.expression(state, node, eraw, depth + 1)

    def sizeof_value(self, n, raw):
        """(R90) ``sizeof`` where C fixes the size whatever the implementation pads: a character type is 1 (C11 6.5.3.4p4)
        and an array of one with a known length is that length (p4, 6.2.5p20) — HDPDM01 `sf_Crc32Init` loops ``i <
        sizeof(p) / sizeof(UINT8)`` over ``static const UINT8 p[] = {…14 items…}``; unread, every pass of that loop was a
        branch on an unknown value and the pass past 14 indexed past ``p`` — undefined behaviour that refused every SITS
        row through `CheckProgDependencies`. The operand is not evaluated (p2): only its type is read. The value is known,
        its type is ``size_t`` (`_size_value`). Anything else stays ``sizeof_unmodeled``: ``sizeof(U16)`` is 2 only
        without padding bits, a struct only with its layout, a parameter declared as an array is a pointer."""
        size = None
        tnode, operand = n.child_by_field_name("type"), n.child_by_field_name("value")
        if tnode is not None:
            if tnode.child_by_field_name("declarator") is None:   # ``sizeof(U8 *)`` is a pointer's size
                size = self.char_type_size(_text(tnode, raw))
        elif operand is not None:
            size = self.object_size(operand, raw)
        if size is None:
            return _Val(Unknown("sizeof_unmodeled"), None)
        return _Val(Unknown(_SIZE_REASON), None, (size, size))

    def char_type_size(self, text):
        """(R90) 1 when ``text`` names a character type (plain ``char`` too — its signedness does not change its size),
        else None."""
        words = [w for w in str(text).split() if w not in {"const", "volatile"}]
        if not words:
            return None
        t = self.type_of(" ".join(words))
        if isinstance(t, dict):
            return 1 if t.get("kind") == "char" and not t.get("enum") and not cpc.is_float(t) else None
        kind = cpc.base_kind(" ".join(words))
        return 1 if kind is not None and kind[0] == "char" else None

    def object_size(self, node, raw):
        """(R90) The size `sizeof_value` may take of an expression operand: an object of a character type (1), an
        element of a character array (1), a character array of known length (its length) — named directly; a parameter,
        a macro or anything else is None."""
        while node.type == "parenthesized_expression" and len(_named(node)) == 1:
            node = _named(node)[0]
        element = node.type == "subscript_expression"
        if element:
            node = node.child_by_field_name("argument")
            while node is not None and node.type == "parenthesized_expression" and len(_named(node)) == 1:
                node = _named(node)[0]
        if node is None or node.type != "identifier":
            return None
        name = _text(node, raw)
        if name in self.macro_status:
            return None
        info = self.lookup(name)
        if info is not None and not info.get("extern"):
            if info.get("pointer"):   # a pointer — a parameter declared as an array is one (C11 6.7.6.3p7)
                return None
            is_array, t = bool(info.get("array")), info.get("type")
            if is_array and not isinstance(t, dict):
                # ``static const UINT8 p[]``: the qualified name is no type the scope holds — the element's size is not
                #   the qualifier's (6.2.5p26)
                t = self.type_of(" ".join(w for w in str(info.get("type_name") or "").split()
                                          if w not in {"const", "volatile"}) or "?")
            length = info.get("length") if is_array else None
        elif name in self.arrays:
            is_array, t, length = True, self.arrays[name]["type"], self.arrays[name]["length"]
        elif name in self.globals:
            is_array, t, length = False, self.globals[name]["type"], None
        elif element or name in (self.scope.get("unresolved_globals") or {}) or _declared_in_function(node, name, raw):
            return None
        else:
            # ``sizeof (UINT8)``: the grammar reads a parenthesized type name as a parenthesized expression — a name no
            #   object in scope has is the typedef it names, if the scope resolves one
            return self.char_type_size(name)
        if (element and not is_array) or not isinstance(t, dict) or t.get("kind") != "char" or t.get("enum"):
            return None
        if element or not is_array:
            return 1
        return length if isinstance(length, int) and length > 0 else None

    def cast(self, inner, t):
        if isinstance(t, Unknown):
            return _Val(t, None)
        if _size_value(inner) is not None and not cpc.is_float(t):
            return _Val(self.convert_to(inner, t), t)   # (R90) ``(U8)sizeof(buf)``: by its value (`convert_to`)
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
        if isinstance(arg.v, _Pointer):   # (R40) ``!p``
            return _Val(int(not arg.v), self.int_t) if op == "!" else _Val(Unknown("pointer_operation_unmodeled"), None)
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
            return self.enum_dual(lambda c: cpc.arith(op, None, (arg.v, c), self.widths), rt, arg.t)
        value = self.lift(cpc.arith, op, None, (arg.v, arg.t), self.widths, state=state)
        return _Val(value[0] if isinstance(value, tuple) else value, rt)

    def operand_range(self, x):
        """What an operand may hold: its value when known, its type's range when not (an enumeration object: every
        permitted underlying type). ``None`` when it is not an integer."""
        if not isinstance(x.v, Unknown):
            return (x.v, x.v) if isinstance(x.v, int) and not isinstance(x.v, bool) else None
        if not isinstance(x.t, dict) or cpc.is_float(x.t):
            return None
        if x.t.get("enum"):
            ranges = [cpc.type_range(c) for c in self.enum_candidates(x.t)]
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

    def enum_dual(self, compute, rt, et=None):
        """Result of an operation on an enumeration object under every permitted underlying type (``et``: the one
        enumeration type it reads — (R90 review W4) the types that hold its members)."""
        results = set()
        for c in self.enum_candidates(et):
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
        shape = cast_unary_operand(n, raw, self.scope)
        if shape is not None:
            # (R67) ``(S16)-1800`` is a cast of ``-1800``; a right side the grammar grouped under the misparse is refused
            #   like the other parenthesized-cast misparse (``(Inc()) + 1U``) — its grouping is not the program's
            if shape[2] is None:
                raise Unsupported("cast_operand_grouping_unread:" + shape[0])
            arg = self.expression(state, shape[2], raw, depth + 1)
            return self.cast(self.unary(shape[1], arg, state), self.type_of(shape[0]))
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
            if self.operand_effectful(right_node, raw) or self.has_macro_call(right_node, raw):
                raise Unsupported("side_effect_under_unknown_condition")
            right = self.speculative(state, right_node, raw, depth, runs_maybe=True)
            rt = self.truth(right)
            if rt is not None and ((op == "&&" and not rt) or (op == "||" and rt)):
                return _Val(0 if op == "&&" else 1, self.int_t)
            return _Val(left.v if isinstance(left.v, Unknown) else Unknown("unknown"), self.int_t)
        right = self.expression(state, right_node, raw, depth + 1)
        if isinstance(left.v, _Pointer) or isinstance(right.v, _Pointer):
            return self.pointer_compare(op, left, right)
        if self.operand_marks and raw is self.fn_raw:
            mark = self.operand_marks.get((n.start_byte, n.end_byte, n.type))
            if mark is not None:
                # (R79) what this evaluation of a watched operator saw — a fault there changes the result only for
                #   some operand values (equal sides of a comparison, a non-zero addend, a multiple of the divisor)
                state.decisions.append((mark, ("outcome", self.watched_pair(left, right))))
        if self.perturb is not None and raw is self.fn_raw and self.perturb[1] == (n.start_byte, n.end_byte, n.type):
            return self.perturbed_binary(op, left, right, state)
        return self.arith_values(op, left, right, state)

    def perturbed_binary(self, op, left, right, state):
        """(R84) The watched operator's result changed the way a propagation check asks (``self.perturb``): a data-state
        perturbation at that site (Voas, PIE) — not a mutant of the measuring tool. ``flip``: a comparison's result negated
        on every evaluation (a condition taking the other outcome); ``flip_equal``: negated only where its two sides are
        equal (the comparison's boundary point — what an off-by-one there changes); ``drop_right``: ``+`` ``-`` ``*`` as if
        the right operand were the identity (a missing term or factor); ``step``: ``/`` ``%`` one unit off (the quotient's
        step). A result the model does not know, or an operator the kind does not fit, stays as it is."""
        kind = self.perturb[0]
        value = self.arith_values(op, left, right, state)
        if kind in ("flip", "flip_equal") and op in {"<", "<=", ">", ">=", "==", "!="}:
            v = _known_int(value)
            if v is None:
                return value
            if kind == "flip_equal":
                a, b = self.watched_pair(left, right)
                if a is None or b is None or a != b:
                    return value
            return _Val(0 if v else 1, value.t)
        if kind == "drop_right" and op in {"+", "-", "*"} and isinstance(right.t, dict) and not cpc.is_float(right.t):
            return self.arith_values(op, left, _Val(0 if op in {"+", "-"} else 1, right.t), state)
        if kind == "step" and op in {"/", "%"}:
            v = _known_int(value)
            if v is None:
                return value
            lo, hi = cpc.type_range(value.t) if value.t["kind"] != "_Bool" else (0, 1)
            return _Val(v + 1 if v + 1 <= hi else v - 1, value.t) if lo <= v - 1 or v + 1 <= hi else value
        return value

    def operand_effectful(self, node, raw):
        """Can evaluating this operand change state — asked of the right operand of ``&&``/``||`` under an unknown left
        and of the arms of ``?:``. (R26) ``(U8)(x)`` parses as a call of ``(U8)``: it is a cast here as it is where it is
        evaluated (`call`), not a side effect — its argument is still walked (``(U8)(g++)`` is one)."""
        return any(x.type in _SIDE_EFFECTS and not (x.type == "call_expression" and self.is_cast_call(x, raw))
                   for x in _walk(node))

    def has_macro_call(self, n, raw):
        # (R35) an undecided macro hides a call only if some definition in the tree has one (or the tree is not the
        # whole story) — the same judgment `macro_effectful` makes of it
        return any(cpc.is_name_node(x) and _text(x, raw) in self.macro_status and
                   self.macro_status.get(_text(x, raw)) != "active" and self.macro_effectful(_text(x, raw))
                   for x in _walk(n))

    def conditional(self, state, n, raw, depth):
        cond_node = n.child_by_field_name("condition")
        cond = self.expression(state, cond_node, raw, depth + 1)
        a_node, b_node = n.child_by_field_name("consequence"), n.child_by_field_name("alternative")
        truth = self.truth(cond)
        guard = self.guards.get((cond_node.start_byte, cond_node.end_byte, cond_node.type)) if raw is self.fn_raw else None
        if guard is not None:
            state.decisions.append((guard, ("outcome", truth)))
        if truth is None:
            if any(self.operand_effectful(node, raw) for node in (a_node, b_node)):
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
        if self.operand_effectful(other, raw):
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
        # (R90 review W2) an operand that runs on some executions is judged as on the run's only path: undefined behaviour
        #   there is possible whatever path this is (`operand_under_unknown_condition`) — on a forked path it was tagged
        #   with the branch that chose the path, not with the condition that runs the operand
        probe.selectors = []
        try:
            value = self.expression(probe, node, raw, depth + 1)
        except Unsupported as exc:
            if not runs_maybe:
                return _Val(Unknown(str(exc)), None)
            if not str(exc).startswith("undefined_behavior:"):
                raise
            state.possible_ub.add("operand_under_unknown_condition")
            self.maybe_decisions(state, probe)
            state.initial_reads |= probe.initial_reads   # (backlog 2-c review C2) it runs on some executions
            return _Val(Unknown(str(exc)), None)
        if runs_maybe:
            self.maybe_decisions(state, probe)
            # (backlog 2-c review C2) what it reads, it reads on the executions where it runs: ``(a > 1U) && (g_s > 1U)``
            #   reads g_s whenever a > 1 — the decided ``?:`` arm (``runs_maybe`` false) does not run and reads nothing
            state.initial_reads |= probe.initial_reads
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
        decision runs, so a write or a call in one condition could change what a later one reads. (R37) A call the run
        stubs changes nothing (`stub_call_inert`)."""
        for x in _walk(atom):
            if x.type in {"assignment_expression", "update_expression", "gnu_asm_expression"}:
                return True
            if x.type == "call_expression" and not (self.is_cast_call(x, raw) or self.pure_macro_call(x, raw)
                                                    or self.stub_call_inert(x, raw)):
                return True
            if cpc.is_name_node(x) and _text(x, raw) in self.macro_status and _text(x, raw) not in self.macro_params \
                    and self.macro_effectful(_text(x, raw)):
                return True
        return False

    def stub_call_inert(self, node, raw):
        """(R37) ``F(…)`` in a condition, where the run stubs F (the row sets ``F() return``): its value is the row's and
        a stub writes no global or static (R38 — `stubbed_call`, the same model as a stubbed call outside a condition),
        so evaluating the condition on the state the decision starts from is what the sequential run sees. Not when the
        stub may put something through a pointer argument (the sequence sets one of its out-parameters, or F's closure
        writes through a pointer or calls unknown code), nor when the called name is not the project function."""
        f = node.child_by_field_name("function")
        if f is None or f.type != "identifier":
            return False
        view = self.stub_view(_text(f, raw))
        return view is not None and not view["pointer"]

    def stub_view(self, name):
        """(R38) The one judgment every site asks of a call to ``name``: None when the sequence does not stub it, else
        ``{"pointer": whether the stub may put something through a pointer argument}``. The sequence stubs F when it
        sets one of F's stub inputs (``F() return``, or an out-parameter ``F() p[0]`` — R23) — not the function under
        test (it runs for real in its own test), not a name the function declares or sees in scope (review R37 W1:
        ``U8 (*get)(void)`` is what is called), not a macro, not a function without a project definition. The stub
        may write through a pointer when the sequence sets one of its out-parameters (VectorCAST writes the test
        case's value), or when F's closure writes through a pointer or calls code the closure cannot see."""
        prefix = name + "() "
        keys = self.stub_keys.get(name)
        if not keys or name == self.function_name or name in self.macro_status or name in self.fn_names \
                or name in (self.params or {}) or self.lookup(name) is not None:
            return None
        info = self.closure.get(name)
        if info is None:
            return None
        out_params = any(k != prefix + "return" for k in keys)
        hedge = bool(info.get("pointer_write") or info.get("unknown_callees"))
        # (R64, backlog 4-a) the body does not run: a stub can put something only through a parameter that can hold a
        #   pointer (or a variadic argument) — without one it writes through nothing, whatever F's closure does; with
        #   one, the hedge stands and what it may reach is the arguments' (`stub_targets`)
        flow = self.pointer_flow()
        params = flow.params(name) if flow is not None else None
        if params is not None:
            carries = flow.variadic(name) or any(_maybe_pointer(flow, p) for p in params)
            return {"pointer": bool(out_params or (carries and hedge))}
        defs = (flow.functions.get(name) or []) if flow is not None else []
        if defs:
            # (review R64 round 3 K1) parameters the flow cannot read (K&R) may carry anything; definitions that differ
            #   carry what any of them does
            if any(not d or d.get("params_unreadable") for d in defs):
                return {"pointer": True}
            carries = any(d.get("variadic") or any(_maybe_pointer(flow, p) for p in d.get("params") or ()) for d in defs)
            return {"pointer": bool(out_params or (carries and hedge))}
        return {"pointer": bool(out_params or hedge)}

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
        truths, reasons, sides = [], [], []
        saved, self.watch = self.watch, None
        try:
            for atom in spec["atoms"]:
                probe = state.copy(records=False)   # its records are discarded; only this evaluation's are read
                mark = self.operand_marks.get((atom.start_byte, atom.end_byte, atom.type)) if self.operand_marks \
                    else None
                before = len(probe.decisions)
                try:
                    v = self.expression(probe, atom, self.fn_raw)
                    truths.append(self.truth(v))
                    reasons.append(v.v.reason if isinstance(v.v, Unknown) else "")
                except Unsupported as exc:
                    truths.append(None)
                    reasons.append(str(exc))
                # (R79) a watched comparison's operands on this very evaluation (its `binary` record on the probe)
                sides.append(next(((mark, obs[1]) for k, obs in reversed(probe.decisions[before:])
                                   if k == mark and obs[0] == "outcome"), None) if mark is not None else None)
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
        for i, side in enumerate(sides):
            if side is None or not observed[i] or truths[i] is None:
                continue
            # (R79 review W1) the operands and whether this condition decides, on the same evaluation — in a loop the
            #   sides may be equal on one pass and the condition decide on another
            flipped = list(truths)
            flipped[i] = not truths[i]
            other = _ir_outcome(spec["ir"], flipped)
            state.decisions.append((("decide", side[0][1]), ("outcome", (*side[1], other is not None
                                                                          and other != bool(outcome)))))

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
            pt = self.pointee_target(state, n, raw)
            if pt is not None:
                return self.pointee_lvalue(*pt, state)
            arg, index = n.child_by_field_name("argument"), n.child_by_field_name("index")
            array = self.array_object(arg, raw, depth, state)
            iv = self.expression(state, index, raw, depth + 1)
            if array is None:
                shaped = self.shaped_element(state, n, raw, depth, iv)
                if shaped is not None:
                    return shaped
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
                if key in self.harness_buffers:
                    self.buffer_reach_unknown.add(key)   # (review R82 I-R5-7)
                return ("base", key, "index_unknown:" + (iv.v.reason if isinstance(iv.v, Unknown) else "type"))
            if length is None:
                return ("base", key, "array_length_unresolved")
            if not 0 <= iv.v < length:
                if key in self.harness_buffers and iv.v >= 0:
                    # (review R82 I6) past the length the model gives a harness buffer — a limit of the model, not C's
                    raise Unsupported("harness_buffer_index_beyond_model:" + str(iv.v))
                # (R90 review C1) on a chosen path: a read is unknown, a write leaves the whole array unknown
                return ("base", key, self.undefined(state, "array_index_out_of_bounds").reason)
            if key in self.harness_buffers:
                self.buffer_reach[key] = max(self.buffer_reach.get(key, -1), int(iv.v))
            return ("key", f"{key}[{iv.v}]", t, volatile)
        if k == "field_expression":
            pt = self.pointee_target(state, n, raw)
            if pt is not None:
                return self.pointee_lvalue(*pt, state)
            is_arrow = any(c.type == "->" for c in n.children)
            if is_arrow:
                self.expression(state, n.child_by_field_name("argument"), raw, depth + 1)
                return ("ptr", "write_through_pointer")
            path = self.member_path(n, raw)
            if path is not None:
                if path in self.globals:
                    g = self.globals[path]
                    return ("key", path, g["type"], g.get("volatile", False))
                st = self.storage_member(path)
                if st is not None:   # (R90) a member of a union / bit-field object: `store` writes its bits
                    return ("key", path, self.storage_read_type(st[2]) or st[2]["type"], False)
                # (R39) a member of a modeled struct that is no scalar member (``g.s = h`` — a nested struct, a pointer
                # or unmodeled member): only what lies under it changes
                return ("base", path, "field_write:" + path)
            arg = n.child_by_field_name("argument")
            inner = self.lvalue(state, arg, raw, depth + 1)
            if inner[0] == "key":
                return ("base", inner[1], "field_write")
            return inner
        if k == "pointer_expression":
            pt = self.pointee_target(state, n, raw)
            if pt is not None:
                return self.pointee_lvalue(*pt, state)
            self.expression(state, n.child_by_field_name("argument"), raw, depth + 1)
            return ("ptr", "write_through_pointer")
        if k == "cast_expression":
            return ("ptr", "write_through_cast")
        return ("all", "unsupported_lvalue:" + k)

    def pointee_lvalue(self, target, path, state=None):
        """(R40) Where a write through a known pointer lands: a pointee member (``p->a``), or everything under a
        non-leaf path (``*p = s`` · ``p->in = h``)."""
        obj = self.pointee_object(target, path, state)
        if obj[0] == "leaf":
            return ("key", obj[1], obj[2], obj[3])
        return ("base", obj[1], "pointee_write:" + obj[1][len("@pointee:"):])

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

    def shaped_element(self, state, n, raw, depth, last):
        """(R83) ``t[i][j][k]`` — an element of a multi-dimensional array object the unit declares (`array_shapes`), one
        index per dimension: that object and no other when every index lies inside its dimension. The object is no
        modeled one (a read is unknown, a write leaves it unknown — ``base``), but the access is no pointer arithmetic
        that may leave it (KJPDS02_PV `s_SetPWMTableValue`: ``s16g_…Table[roll][pitch][pos] = v`` on every table path was a
        possible UB, so the scenario search reached those paths only uncleanly and no row took table 1 or 2). A known
        index outside its dimension is undefined (C11 J.2), an unknown one may be (``index_unknown``, as for one
        dimension). None — as before — for a sub-array (``t[i]`` decays to a pointer), a local or parameter of the name,
        a macro. ``last``: the last index's value — the caller evaluated it."""
        indices = []
        node = n
        while node is not None and node.type == "subscript_expression":
            indices.append(node.child_by_field_name("index"))
            node = node.child_by_field_name("argument")
            while node is not None and node.type == "parenthesized_expression" and len(_named(node)) == 1:
                node = _named(node)[0]
        if node is None or node.type != "identifier" or None in indices:
            return None
        name = _text(node, raw)
        shape = self.array_shapes.get(name)
        info = self.lookup(name)
        if shape is None or name in self.macro_status or (info is not None and not info.get("extern")) \
                or len(indices) != len(shape["dims"]):
            return None
        values = [self.expression(state, x, raw, depth + 1) for x in reversed(indices[1:])] + [last]   # outermost first
        known = [None if isinstance(v.v, Unknown) or v.t is None else int(v.v) for v in values]
        if any(k is not None and (k < 0 or (d is not None and k >= d)) for k, d in zip(known, shape["dims"], strict=True)):
            return ("base", name, self.undefined(state, "array_index_out_of_bounds").reason)   # (R90 review C1)
        if None in known:
            state.possible_ub.add("index_unknown")
            v = values[known.index(None)]
            return ("base", name, "index_unknown:" + (v.v.reason if isinstance(v.v, Unknown) else "type"))
        return ("base", name, "array_element_unmodeled:" + name)

    def array_object(self, arg, raw, depth, state=None):
        """(key base, element type, length, volatile) of a directly named array; None otherwise."""
        while arg.type == "parenthesized_expression" and len(_named(arg)) == 1:
            arg = _named(arg)[0]
        if state is not None and arg.type == "field_expression":
            # (R40) a member array of a known pointer's pointee: ``p->b[i]``
            pt = self.pointee_target(state, arg, raw)
            if pt is not None:
                obj = self.pointee_object(*pt, state)
                return (obj[1], obj[2], obj[3], obj[4]) if obj[0] == "array" else None
        if arg.type == "field_expression":
            # (R39) a member array of a modeled struct object: ``g.b[i]``
            path = self.member_path(arg, raw)
            if path is not None and path in self.arrays:
                a = self.arrays[path]
                return path, a["type"], a["length"], a.get("volatile", False)
            return None
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
            pointee = info.get("pointee")
            value = state.store.get(info.get("key")) if state is not None else None
            if isinstance(pointee, dict) and pointee.get("buffer") and isinstance(value, _Pointer) \
                    and value.target == name:
                # (R82) `p[i]` of a pointer parameter whose scalar pointee the row set up: an element of the harness
                #   buffer (`@pointee:p[i]` — `p[0]` / `*p` is the same object as before)
                rec = pointee["members"][""]
                self.harness_buffers.setdefault(f"@pointee:{name}", max(1, self.buffer_extent(name)))
                return (f"@pointee:{name}", rec["type"], HARNESS_BUFFER_LENGTH,
                        bool(pointee.get("volatile") or rec.get("volatile")))
            return None
        if name in self.arrays:
            a = self.arrays[name]
            return name, a["type"], a["length"], a.get("volatile", False)
        return None

    def read_target(self, state, target):
        if target[0] != "key":
            # (backlog 2-c review W1) a read the model cannot place: through an unknown pointer (any object a pointer
            #   may reach) or of an unknown part of one object (index unknown, an aggregate) — recorded, so no output it
            #   may have read is reported as unread
            state.initial_reads.add(_ANY_POINTER_READ if target[0] in ("all", "ptr") else _BASE_READ + str(target[1]))
            return _Val(Unknown(target[-1] if target[0] in ("all", "ptr") else target[2]), None)
        _, key, t, volatile = target
        st = self.storage_member(key)
        if st is not None:
            return self.read_storage(state, key, st)   # (R90)
        if key.startswith("@pointee:"):
            return _loaded(self.read_pointee(state, key, t, volatile), t)   # (R40)
        base = key.split("[", 1)[0]
        if volatile:
            return _Val(Unknown("volatile_object:" + base), t)
        if key in state.store:
            return _loaded(state.store[key], t)
        if base in self.arrays and not base.startswith("@"):
            a = self.arrays[base]
            if a.get("values") is not None and a.get("const"):
                index = int(key[len(base) + 1:-1])
                if str(a.get("values_source") or "").startswith("linked:"):
                    self.linked_reads.add(f"{base} ({os.path.basename(a['values_source'][len('linked:'):])})")
                return _Val(a["values"][index], t)
            if a.get("const") and not a.get("volatile"):
                # (R67, audit #45) a const table whose values this unit does not hold: the program's values are its
                #   initializer, not an input the test could set — say why they are not held, and do not count it as a
                #   read the inputs lack (`initial_value_not_in_inputs` made a false source finding of it)
                return _Val(Unknown("const_values_unread:" + base + ":" + str(a.get("values_unread") or "unknown")), t)
        if base.startswith("@"):
            return _Val(Unknown(state.havoc_bases.get(base, "uninitialized_local")), t)
        return _Val(self.initial(state, key, base, t), t)

    def address_of(self, state, arg, raw, depth):
        """``&x``: x escapes — whatever an unknown write may reach includes it from now on."""
        target = self.lvalue(state, arg, raw, depth + 1) if arg is not None else ("all", "address_of")
        if target[0] == "key":
            base = target[1].split("[", 1)[0]
            if self.storage_member(base) is not None:
                base = _root_object(base)   # (R90) a member's address reaches every member of the storage object
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
        if self.perturb is not None and self.perturb[0] == "skip_write" and op == "=" and raw is self.fn_raw and \
                self.perturb[1] == (n.start_byte, n.end_byte, n.type):
            # (R84) the write left out — the object keeps the value it held (its target and right side still evaluated)
            return right
        mark = self.write_marks.get((n.start_byte, n.end_byte, n.type)) if self.write_marks and raw is self.fn_raw \
            else None
        old = self.peek_target(state, target) if mark is not None else None
        if op == "=":
            value = right
        else:
            current = self.read_target(state, target)
            value = self.arith_values(op[:-1], current, right, state)
        if target[0] == "key":
            self.store(state, target, value)
            stored = self.stored_value(state, target)
            loaded = _loaded(stored, target[2])
            if mark is not None:
                # (R79) the value replaced and the value written: deleting the assignment shows only where they differ
                state.decisions.append((mark, ("outcome", (old, _known_int(loaded)))))
            return loaded
        self.store(state, target, value)
        if mark is not None:
            state.decisions.append((mark, ("outcome", (old, None))))
        return _Val(Unknown(target[-1] if target[0] in ("all", "ptr") else target[2]), None)

    def peek_target(self, state, target):
        """(R79) The integer an object holds before a watched assignment, or None. `read_target` takes no step and
        writes nothing to the store; the read it would record is kept apart, so `initial_reads` stays what it was
        without the watch (review R79 I2: no copy of the path — that grew with the path's records in a loop)."""
        if target[0] != "key":
            return None
        kept, state.initial_reads = state.initial_reads, set()
        try:
            return _known_int(self.read_target(state, target))
        except Exception:  # noqa: BLE001  # silent-ok — a watch never fails its run: the value is then unknown
            return None
        finally:
            state.initial_reads = kept

    def watched_pair(self, left, right):
        """(R79 review I3) A watched operator's operands as it uses them — after the usual arithmetic conversions
        (``S16 -1`` against ``U16 65535`` compares equals; ``-100 / 50U`` divides 65436) — or as evaluated where the
        two have no common integer type (an enumeration, an unknown type)."""
        a, b = _known_int(left), _known_int(right)
        if a is None or b is None or left.t.get("enum") or right.t.get("enum"):
            return a, b
        try:
            t = cpc.usual_conversion(left.t, right.t, self.widths)
            return int(cpc.convert(a, t)), int(cpc.convert(b, t))
        except Exception:  # noqa: BLE001  # silent-ok — no common integer type: the values as evaluated
            return a, b

    def size_arith(self, op, left, right):
        """(R90) An operator with a ``sizeof`` value (`_size_value`): its value is known, its type is ``size_t`` — an
        unsigned type of at least 16 bits (SIZE_MAX >= 65535, C11 7.20.3) whose rank the source does not say, so the
        common type is not known. With both operands' values known and non-negative the result does not depend on it
        where it is exact in every such type: a comparison (each value is representable in the common type, whichever
        it is — 6.3.1.8 — so it compares the values; ``int``), ``/`` ``%`` (no wrap, no overflow), ``+`` ``-`` ``*`` ``&``
        ``|`` ``^`` with a result in 0..32767 (representable in ``int`` and in every unsigned type, so no wrap and no
        overflow), ``>>`` of a ``sizeof`` value by a count below 16 (no type is narrower). Then the result is again a value
        of a type the source does not say. None otherwise — the operator then reads it as an unknown of unknown type, as
        before R90."""
        a, b = _size_value(left), _size_value(right)
        if a is None and b is None:
            return None
        sized_left = a is not None
        a = a if a is not None else _known_int(left)
        b = b if b is not None else _known_int(right)
        if a is None or b is None or a < 0 or b < 0:
            return None
        if op in {"<", "<=", ">", ">=", "==", "!="}:
            return _Val(int({"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b, "==": a == b, "!=": a != b}[op]),
                        self.int_t)
        if op in {"/", "%"} and b:
            r = a // b if op == "/" else a % b
        elif op in {"+", "-", "*", "&", "|", "^"}:
            r = {"+": a + b, "-": a - b, "*": a * b, "&": a & b, "|": a | b, "^": a ^ b}[op]
        elif op == ">>" and sized_left and b < 16:
            r = a >> b
        else:
            return None
        if not 0 <= r <= 32767:
            return None
        return _Val(Unknown(_SIZE_REASON), None, (r, r))

    def faulted(self, state, kind, op, left, right):
        """(R90 review C1) An operator whose undefined behaviour ``kind`` is proven whatever the other operand holds: refused
        on the run's only path (`undefined`), an unknown result of the operator's type on a path an unknown branch chose."""
        reason = self.undefined(state, kind)
        typed = all(isinstance(x.t, dict) and not cpc.is_float(x.t) and not x.t.get("enum") for x in (left, right))
        rt = (cpc.promote(left.t, self.widths) if op in {"<<", ">>"} else cpc.usual_conversion(left.t, right.t, self.widths)) \
            if typed else None
        return _Val(reason, rt)

    def arith_values(self, op, left, right, state):
        """One binary operator on evaluated operands (arithmetic, bitwise, shift, comparison)."""
        comparison = op in {"<", "<=", ">", ">=", "==", "!="}
        right_known = not isinstance(right.v, Unknown) and isinstance(right.t, dict) and not cpc.is_float(right.t)
        # Undefined whatever the other operand holds (C11 6.5.5p5, 6.5.7p3): refused even when it is unknown.
        if right_known and op in {"/", "%"} and right.v == 0:
            return self.faulted(state, "division_by_zero", op, left, right)
        if right_known and op in {"<<", ">>"} and (right.v < 0 or (
                isinstance(left.t, dict) and not cpc.is_float(left.t) and right.v >= cpc.promote(left.t, self.widths)["bits"])):
            return self.faulted(state, "shift_count_out_of_range", op, left, right)
        sized = self.size_arith(op, left, right)
        if sized is not None:
            return sized   # (R90)
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
            # (R90 review W4) one enumeration operand: the types that hold its members; two: every choice, as before
            et = None if left.t.get("enum") and right.t.get("enum") else (left.t if left.t.get("enum") else right.t)
            return self.enum_dual(lambda c: cpc.arith(op, (left.v, c if left.t.get("enum") else left.t),
                                                      (right.v, c if right.t.get("enum") else right.t), self.widths), rt, et)
        value = self.lift(cpc.arith, op, (left.v, left.t), (right.v, right.t), self.widths, state=state)
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
            return _loaded(self.stored_value(state, target), target[2]) if prefix else current
        self.store(state, target, new)
        return _Val(Unknown(target[-1] if target[0] in ("all", "ptr") else target[2]), None)

    # calls
    def call(self, state, n, raw, depth):
        f, args = n.child_by_field_name("function"), n.child_by_field_name("arguments")
        arg_nodes = _named(args) if args is not None else []
        if self.is_cast_call(n, raw):
            # ``(T)(x)`` is a cast exactly when ``T`` names a type — the one judgement every site asks (R26 review W4)
            return self.cast(self.expression(state, arg_nodes[0], raw, depth + 1), self.type_of(_text(_named(f)[0], raw)))
        name = _text(f, raw) if f is not None and f.type == "identifier" else "<indirect>"
        if name in self.macro_status:
            if (id(raw), n.start_byte, n.end_byte) in self.no_inline:
                # (review C-R3-2) the expansion is parsed from its own buffer: the mark on this site covers it all
                self.no_inline_depth += 1
                try:
                    return self.macro_call(state, name, arg_nodes, raw, depth)
                finally:
                    self.no_inline_depth -= 1
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
            values = None
        else:
            values = [self.argument(state, a, raw, depth) for a in arg_nodes]
        if info is None or name in (self.params or {}) or self.lookup(name) is not None:
            self.havoc_everything(state, "unknown_callee:" + name, locals_too=maybe_macro)
            return _Val(Unknown("call_return_value:" + name), None)
        view = self.stub_view(name)
        if view is not None:
            return self.stubbed_call(state, name, info, view, arg_nodes, raw)
        if self.world is not None and values is not None and f"{name}() return" not in self.inputs \
                and not self.no_inline_depth and (id(raw), n.start_byte, n.end_byte) not in self.no_inline:
            # (R16) a callee with one definition in the project runs for real on this state; when it cannot (no
            # definition, recursion, an unsupported statement, its share of the budget) the effects below stand.
            returned = self.world.inline(self, state, name, values)
            if returned is not None:
                return returned
        if self.world is not None:
            self.world.effects_only[name] = self.world.effects_only.get(name, 0) + 1
            # (R16 review C2) a callee run as effects only may run any function it reaches — among them one this
            # evaluation interpreted (its static locals are in the store) or one on the call stack
            touched = set(info.get("reaches") or ()) | {name}
            if info.get("unknown_callees") or touched & self.world.interpreted_names():
                self.havoc_statics(state, f"callee_not_interpreted:{name}")
        elif self.function_name and self.function_name in (info.get("reaches") or ()):
            self.havoc_statics(state, f"recursion_through:{name}")  # the callee may re-enter this function
        # (backlog 2-c review round 2) run as its effects only: it may read what its closure names, and through a pointer
        state.initial_reads.add(_CALLEE_READS + name)
        state.initial_reads.add(_ANY_POINTER_READ)
        # (R90 re-review 3 C-R3-1) first: a write below names its own reason where it reaches the same register
        self.havoc_registers_read_by(state, name, info)
        writes = sorted(info.get("writes") or ())
        opaque = self.opaque_writes(info)
        if info.get("unknown_callees"):
            first = sorted(info["unknown_callees"])[0]
            self.havoc_everything(state, f"callee_effects_unknown:{name}:{first}")
        else:
            for w in writes:
                self.havoc_base(state, w, f"written_by_callee:{name}:{w}")
            if info.get("pointer_write") or opaque:
                why = "pointer_write" if info.get("pointer_write") else "writes_through:" + opaque[0]
                self.havoc_objects(state, self.callee_targets(name, info, arg_nodes, raw, state),
                                   f"callee_pointer_write:{name}:{why}", direct=frozenset(writes),
                                   through_pointer=bool(info.get("pointer_write")))
            else:
                # (review R64 I-4) a callee it calls that this run stubs may write through what it is passed, whatever
                #   that callee's body does — named by the flow, or (round 2 W-2) when the flow did not run or could not
                #   name the targets, any function it reaches this run stubs with pointer parameters
                summary = info.get("pointer_targets") or {}
                if summary.get("abs") is None:
                    stubbed = sorted(g for g in info.get("reaches") or ()
                                     if (v := self.stub_view(g)) is not None and v["pointer"])
                    if stubbed:
                        self.havoc_pointer_targets(state, f"callee_stub_write:{name}:{stubbed[0]}")
                else:
                    stub_writes = {t for t in summary["abs"] if t.startswith("?SW:")}
                    if stub_writes:
                        self.havoc_objects(state, stub_writes, f"callee_stub_write:{name}")
        return self.stub_return(name, info)

    def havoc_registers_read_by(self, state, name, info):
        """(R90 re-review 3 C-R3-1, re-review 4 C-R4-1) A callee this run does not interpret (its write closure stands for
        it — a unit run, or an inline that failed: a refused polling loop, a budget, recursion) may wait on a register
        flag: under the model (a register is memory) such a callee never returns, under the polling assumption the flag
        changed — neither leaves the register as the row set it. Every volatile union / bit-field object is unknown after
        the call: the closure's ``reads`` do not see a register the callee reaches through a pointer (``WaitP(&FLW)``,
        ``*g_pFlw``) or through a ``#define`` in its body. (Unknown code, an unmodeled macro: `havoc_everything` covers
        every object.) A sequence stub (R38) is not this: the harness replaces the body, nothing polls, and a register
        keeps what the row set."""
        self.havoc_volatile_storage(state, _CALLEE_REGISTERS + name)

    def stubbed_call(self, state, name, info, view, arg_nodes=(), raw=b""):
        """(R38) The sequence stubs F (`stub_view`): R14 — the harness replaces F's body, as VectorCAST does and the
        clang check's stubs do. The body does not run, so nothing F would write to a global or a static happens and
        nothing it calls runs (no re-entry). A stub may still put a test-case value through a pointer argument (the
        reference sets ``F() p[0]`` — R23): (R64) then what those arguments may point to — and what that reaches — is
        unknown (`stub_targets`); everything a pointer may reach when the arguments cannot be followed."""
        self.stubs_used.add(name)   # the record rests on the stub even when its value is not usable
        if view["pointer"]:
            self.havoc_objects(state, self.stub_targets(name, arg_nodes, raw, state), f"stub_pointer_argument:{name}")
        return self.stub_return(name, info)

    # ── (R64) where a write through a pointer lands ─────────────────────────────────────────────────
    def pointer_flow(self):
        return (self.scope.get("effects") or {}).get("pointer_flow")

    def entry_interp(self):
        """The activation of the function under test (the harness calls it; its parameters are the harness's)."""
        return self.world.stack[0] if self.world is not None and self.world.stack else self

    def argument_objects(self, node, raw):
        """Objects an argument's value may point to by the project points-to analysis (`pointer_flow`), or None."""
        flow = self.pointer_flow()
        if flow is None or node is None:
            return None
        entry = self.entry_interp().function_name
        # the answer depends on the argument's text, the names local where it stands and the run's entry — the vectors
        # of one function share it (keyed by text: an expansion buffer's id is no stable name)
        cache = self.shared.setdefault("argument_objects", {})
        key = (raw[node.start_byte:node.end_byte], self.function_name, entry,
               tuple(sorted(n for frame in self.lexical for n, i in frame.items() if not i.get("extern"))))
        if key in cache:
            return cache[key]

        def is_local(name):
            info = self.lookup(name)
            return info is not None and not info.get("extern")
        tree, records = pointer_flow.expression_tree(node, raw, is_local)
        cache[key] = flow.question(self.function_name, tree, records, entry, self.fn_names, as_pointer=True)
        return cache[key]

    def harness_buffer_key(self, state, node, raw):
        """(R82) The harness buffer an argument points into — a pointer parameter's scalar pointee (``p``, ``&p[k]``) or
        a pointer member's buffer (``p->data``, ``&p->data[k]``) — as its base key (`@pointee:p` · `@pointee:p[0].data`),
        else None. A callee writing through it stays inside it (beyond the buffer is undefined in the harness the
        record assumes): the project points-to analysis cannot follow a pointer the harness loaded into its object."""
        while node is not None and node.type == "parenthesized_expression" and len(_named(node)) == 1:
            node = _named(node)[0]
        if node is not None and node.type == "pointer_expression" and _text(node, raw).lstrip().startswith("&"):
            inner = node.child_by_field_name("argument")
            while inner is not None and inner.type == "parenthesized_expression" and len(_named(inner)) == 1:
                inner = _named(inner)[0]
            node = inner.child_by_field_name("argument") if inner is not None and \
                inner.type == "subscript_expression" else None
        if state is None or node is None or node.type not in ("identifier", "field_expression"):
            return None
        array = self.array_object(node, raw, 0, state)
        if array is None or array[0] not in self.harness_buffers:   # (review R82 I6) the buffer by name, not by length
            return None
        return array[0]

    def callee_targets(self, name, info, arg_nodes, raw, state=None):
        """(R64) The objects a callee run as its write closure may write through a pointer: its summary's ``abs`` and
        what this call's arguments for the parameters it writes through directly point to — None when the analysis
        cannot say (refused, unknown code reached, an argument it cannot follow). (R82) An argument into a harness
        buffer names that buffer (``@B:`` + its base key)."""
        summary = info.get("pointer_targets")
        if not summary or summary.get("abs") is None:
            return None
        out = set(summary["abs"])
        for i in summary.get("params") or ():
            if i >= len(arg_nodes):
                return None
            buffer = self.harness_buffer_key(state, arg_nodes[i], raw)
            if buffer is not None:
                out.add("@B:" + buffer)
                continue
            objs = self.argument_objects(arg_nodes[i], raw)
            if objs is None:
                return None
            out |= objs
        return out

    def stub_targets(self, name, arg_nodes, raw, state=None):
        """(R64) What a sequence stub of ``name`` may write: the objects each argument for a parameter that can hold a
        pointer points to, and what those reach — None when the analysis cannot say. (R82) An argument into a harness
        buffer of integers names that buffer only (it holds no pointer to reach further)."""
        flow = self.pointer_flow()
        params = flow.params(name) if flow is not None else None
        if params is None:
            return None
        out: set = set()
        for i, node in enumerate(arg_nodes):
            if i < len(params) and not _maybe_pointer(flow, params[i]):
                continue
            buffer = self.harness_buffer_key(state, node, raw)
            if buffer is not None:
                out.add("@B:" + buffer)
                continue
            objs = self.argument_objects(node, raw)
            if objs is None:
                return None
            out |= flow.reach(objs, self.token_in_run)
        return out

    def token_in_run(self, obj) -> bool:
        """(R64 review round 2) Whether an object of the flow stands for one in this run: what a stub of G hands out
        (``?S:G``) only where this run stubs G, the harness's pointers (``?P:F:p``, ``?T:F``) only for the function
        under test — elsewhere the objects the pointer also holds are the real ones."""
        if obj.startswith("?S:"):
            return self.stub_view(obj[3:]) is not None
        if obj.startswith("?P:"):
            return obj.split(":", 2)[1] == self.entry_interp().function_name
        if obj.startswith("?T:"):
            return obj[3:] == self.entry_interp().function_name
        return True

    def havoc_objects(self, state, targets, reason, direct=frozenset(), through_pointer=True):
        """(R64) Make the objects a write through a pointer may reach unknown — or, when they are not known (None, an
        unknown token, a harness pointer of this run), everything a pointer may reach (`havoc_pointer_targets`).
        Objects are ``G:name`` (a global), ``L:fn:name`` (a parameter or local — of an activation this evaluation runs),
        ``?P:F:p`` (the pointee the harness passes the function under test), ``?T:F`` (a pointer the harness hands it),
        ``?S:G`` (what a stub of G hands out — meaningful only where this run stubs G); ``F:``/``R:`` name no object.
        (R90 review C2) A register among the objects reached through a pointer — the callee writes through one
        (``through_pointer``), or reaches a register it does not write by name (not in ``direct``) — may be offset to its
        neighbours: every register is unknown then."""
        if targets is None:
            self.havoc_pointer_targets(state, reason)
            return
        entry = self.entry_interp()
        active = {self.function_name} | ({it.function_name for it in self.world.stack} | set(self.world.inlined)
                                         if self.world is not None else set())
        locals_, pointees, globals_, buffers = set(), set(), set(), set()
        for t in targets:
            if t.startswith("@B:"):
                buffers.add(t[3:])   # (R82) a harness buffer the argument points into (`harness_buffer_key`)
            elif t.startswith("G:"):
                globals_.add(t[2:])
            elif t.startswith("L:"):
                _l, fn, local = t.split(":", 2)
                if fn in active:
                    locals_.add(local)
            elif t.startswith("?P:"):
                _p, fn, param = t.split(":", 2)
                if fn != entry.function_name:
                    continue
                if param not in entry.pointees:
                    self.havoc_pointer_targets(state, reason)   # a harness pointer this run does not set up
                    return
                pointees.add("@pointee:" + param)
            elif t.startswith("?T:"):
                if t[3:] == entry.function_name:
                    self.havoc_pointer_targets(state, reason)
                    return
            elif t.startswith("?S:"):
                if self.stub_view(t[3:]) is not None:
                    self.havoc_pointer_targets(state, reason)
                    return
            elif t.startswith("?SW:"):
                # (review R64 I-4) a callee this run stubs, called inside, may write through what it is passed
                view = self.stub_view(t[4:])
                if view is not None and view["pointer"]:
                    self.havoc_pointer_targets(state, reason)
                    return
            elif t.startswith("?"):
                self.havoc_pointer_targets(state, reason)
                return
        for g in sorted(globals_):
            self.havoc_base(state, g, reason)
        if any(self.storage_volatile(g) and (through_pointer or g not in direct) for g in globals_) \
                or pointer_flow.HARDWARE[2:] in globals_:
            # (R90 review C2) a register reached: its neighbours too — (re-review 5 C-R5-1) or an integer address (the
            #   analysis's one hardware object): where the @-placed registers are
            self.havoc_volatile_storage(state, reason)
        for b in sorted(buffers):
            self.havoc_base(state, b, reason)   # (R82) its elements only — the struct holding the pointer stays
        if locals_ or pointees:
            for key in list(state.store):
                base = key.split("[", 1)[0]
                if _local_name(base) in locals_ or base.split(".", 1)[0] in pointees:
                    state.store[key] = _havocked(state.store[key], reason)
            for base in list(state.escaped) + sorted(pointees):
                if _local_name(base) in locals_ or base in pointees:
                    state.havoc_bases.setdefault(base, reason)
            for base in sorted(pointees):
                entry.rebind_under(state, base)   # (review R82 C1) the callee may rebind the harness object's members
        if self.world is not None:
            self.world.pointer_havocs += 1

    def stub_return(self, name, info):
        """(R14) A sequence that sets ``F() return`` declares F a stub for this run (the unit-test convention the
        reference follows): the call returns that value in F's declared return type (a value outside it is refused as
        ``input_outside_declared_type``, never wrapped). What the stub does to state is `stubbed_call`'s (R38). Without
        the input, or when F's return type is not a resolvable integer type, the value is unknown as before."""
        key = f"{name}() return"
        if key not in self.inputs:
            return _Val(Unknown("call_return_value:" + name), None)
        if name == self.function_name:
            # (review R14 W1) the function under test runs for real in its own test — a recursive call is not a stub
            return _Val(Unknown("stub_of_function_under_test:" + name), None)
        text = str((info or {}).get("return_type") or "")
        if not text or "*" in text:
            return _Val(Unknown("stub_return_type_unresolved:" + name), None)
        t = self.type_of(text)
        if not isinstance(t, dict) or cpc.is_float(t):
            return _Val(Unknown("stub_return_type_unresolved:" + name), None)
        value = self.check_input(key, t, self.inputs[key])
        if isinstance(value, Unknown):
            return _Val(value, None)
        self.stubs_used.add(name)
        return _Val(value, t)

    def argument(self, state, a, raw, depth):
        """Evaluate an argument. Passing an address (``&x``, a decayed array, a cast of either) only marks the object
        escaped; whether the callee writes through it is the call's question (``pointer_write`` in its closure)."""
        return self.expression(state, a, raw, depth + 1)

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

_INLINE_DEPTH = 12          # (R16) callee activations below the function under test
_MISSING = object()
# (R16 review W-R2-4, C-R2-3) a callee's refusal that is about the program, not the model: undefined behaviour (6.5p2
# unsequenced side effects), a path that never returns — the integrated run has no return state to observe
_REFUSING_IN_CALLEE = frozenset({"unsequenced_side_effects", "non_terminating_loop",
                                 "constant_condition_loop_unfinished",
                                 # (review W-R4-1) the hidden call is in no write closure: effects-only would drop it
                                 "cast_parse_of_parenthesized_expression"})
_TYPE_WORDS = frozenset({"void", "char", "short", "int", "long", "float", "double", "signed", "unsigned", "_Bool",
                         "struct", "union", "enum", "const", "volatile", "__typeof__", "__typeof", "typeof"})


def _constant_condition(cond, raw, interp):
    """The loop's controlling expression is absent or a nonzero integer constant expression: only literals, constant
    macros and constants (review W-R3-1 — not a macro that reads state or calls; evaluated on no state at all)."""
    if cond is None:
        return True
    stack = [cond]
    while stack:
        x = stack.pop()
        if x.type == "call_expression" and interp.is_cast_call(x, raw):
            # (R26) ``while ((U8)(1U))``: a cast — its type name is not a value to judge, its argument is
            stack.extend(_named(x.child_by_field_name("arguments")))
            continue
        stack.extend(x.named_children)
        if x.type in _SIDE_EFFECTS:
            return False
        if cpc.is_name_node(x):  # (R35) ``while (TRUE)``
            name = _text(x, raw)
            if not (interp.macro_constant(name) if name in interp.macro_status else name in interp.constants):
                return False
    saved, interp.world = interp.world, None   # no callee can run while judging a constant
    try:
        v = interp.expression(_State(), cond, raw)
    except Unsupported:
        return False
    finally:
        interp.world = saved
    return isinstance(v.v, int) and v.v != 0


def _endless(n, cond, raw, interp):
    """A loop with a constant nonzero (or absent) condition and no way out: no ``break`` that leaves it, no
    ``return``/``goto``/``longjmp`` anywhere in its body."""
    if not _constant_condition(cond, raw, interp):
        return False
    body = n.child_by_field_name("body")
    if body is None:
        return True
    stack = [(body, False)]
    while stack:
        x, nested = stack.pop()
        if x.type in {"return_statement", "goto_statement"}:
            return False
        if x.type == "break_statement" and not nested:
            return False
        if x.type == "call_expression":
            f = x.child_by_field_name("function")
            if f is not None and _text(f, raw) in {"longjmp", "_longjmp", "siglongjmp", "exit", "_Exit", "abort"}:
                return False
        inner = nested or x.type in {"while_statement", "do_statement", "for_statement", "switch_statement"}
        stack.extend((c, inner) for c in x.named_children)
    return True


def _linkage_entries(scope, cache):
    """(name, owner, kind, record) of a scope's modeled objects — owner is the unit for ``static``, else "". ``cache``
    lives as long as the scopes it holds (the provider's — review W5: a module-level cache kept scopes of every past
    generation and was shared across threads)."""
    hit = cache.get(id(scope))
    if hit is not None and hit[0] is scope:
        return hit[1]
    unit = str(scope.get("path") or "")
    # (R90) and the union / bit-field objects the unit may lay out (`storage_candidates`): one object per name too
    entries = tuple((name, unit if rec.get("static") else "", kind, rec)
                    for kind, table in (("global", scope.get("globals") or {}), ("array", scope.get("arrays") or {}),
                                        ("storage", scope.get("storage_candidates") or {}))
                    for name, rec in table.items())
    cache[id(scope)] = (scope, entries)
    return entries


class _World:
    """(R16) One evaluation's interprocedural context — callees with a definition in the project run for real.

    ``provider.definition(name, caller_path)`` gives ``(raw, fn, scope, shared, path)`` of the one definition a call
    binds to (or raises `Unsupported`). The callee runs on a copy of the caller's state, its parameters bound to the
    argument values; its final paths are **joined** back into the caller's one state: an object on which paths
    disagree becomes unknown (``path_dependent_in_callee``), as does a return value they disagree on. Nothing the
    callee does is dropped: havoc marks, escapes, possible UB and forks carry over; UB proven inside it is judged as it
    would be in the caller — (R90 review C1) on a callee path a branch on an unknown value chose (in the callee or before
    the call) it is possible UB of that path, which runs on (`_Interp.undefined`); on the only path it refuses the
    evaluation. A call that cannot run (no definition, recursion, depth, an unsupported
    statement, its budget share) falls back to the write-closure effects — the same unknowns as without a world.

    Globals are keyed by name across translation units, so a name must mean one object: an internal-linkage object
    (``static``) belongs to its translation unit, and a callee whose unit sees a same-named object of another
    linkage is not run (``linkage_collision``)."""

    def __init__(self, provider, entry, path):
        self.provider = provider
        self.stack = [entry]
        self.linkage: dict[str, str] = {}
        self.objects: dict[str, tuple[str, dict]] = {}   # name → ("global" | "array", record) of every admitted unit
        self.failed: dict[str, str] = {}
        self.inlined: dict[str, int] = {}
        self.not_inlined: dict[str, int] = {}
        # (R16b review R3 W3-1) callees run as their write closure at some call site (budget, depth, an unsequenced
        #   site, no definition, …; a sequence stub is neither — R38) — a callee may be in both this and `inlined`
        self.effects_only: dict[str, int] = {}
        self.activations = 0
        self.admitted: set[int] = set()   # ids of scopes held alive by the provider / the entry unit
        self.static_keys: set[str] = set()   # static locals of every callee activation run so far
        self.types: dict[str, str] = {}     # declared type of each external object name (review W1)
        self.array_names: set[str] = set()
        self.global_names: set[str] = set()
        self.kept: list[bytes] = []          # macro-expansion buffers of finished activations (their ids are in keys)
        self.pointer_havocs = 0
        self.all_havocs = 0
        # (R90) union / bit-field objects: the first admitted unit declaring each (its layout answers an observation the
        #   entry's unit cannot) and the layout signature every unit that uses one must agree with
        self.storage_scopes: dict[str, dict] = {}
        self.storage_signatures: dict[str, tuple] = {}
        cache = getattr(provider, "linkage_cache", None)
        self.linkage_cache = cache if isinstance(cache, dict) else {}
        ambiguous_for = getattr(provider, "ambiguous_for", None)
        if callable(ambiguous_for):   # (R89) the entry's build only — another build's namesake is another program's
            self.ambiguous, self.ambiguous_roots = ambiguous_for(path)
        else:
            self.ambiguous = getattr(provider, "ambiguous_names", None) or frozenset()
            self.ambiguous_roots = getattr(provider, "ambiguous_struct_roots", None) or frozenset()
        if self.admit(entry.scope) is not None:  # one unit cannot collide with itself
            raise Unsupported("linkage_collision_in_entry_unit")

    def admit(self, scope):
        """The first name whose linkage differs from what an earlier unit said, or None (then the unit is recorded)."""
        if id(scope) in self.admitted:
            return None
        entries = _linkage_entries(scope, self.linkage_cache)
        for name, owner, _kind, rec in entries:
            if self.linkage.get(name, owner) != owner:
                return name
            if not owner and name in self.types and self.types[name] != str(rec.get("typename") or ""):
                return name   # ``extern U8 g`` here, ``U16 g`` there: not one object as far as this model can tell
        for name, owner, kind, rec in entries:
            self.linkage[name] = owner
            if not owner:
                self.types.setdefault(name, str(rec.get("typename") or ""))
            if kind == "storage":
                self.storage_scopes.setdefault(name, scope)   # (R90) laid out when an activation asks
                continue
            self.objects.setdefault(name, (kind, rec))
            (self.array_names if kind == "array" else self.global_names).add(name)
        self.admitted.add(id(scope))
        return None

    def storage_layout(self, root):
        """(R90) The layout of union / bit-field object ``root`` in the first admitted unit declaring it, or None."""
        scope = self.storage_scopes.get(root)
        table = scope.get("storage_globals") if scope is not None else None
        return table[root] if table is not None and root in table else None

    def storage_refusal(self, root):
        """(R90) Why the admitted unit declaring ``root`` gives it no layout, or ""."""
        scope = self.storage_scopes.get(root)
        if scope is None or self.storage_layout(root) is not None:
            return ""
        return str((scope.get("storage_unresolved") or {}).get(root) or "")

    def same_storage(self, root, layout):
        """(R90) Every unit of this run lays ``root`` out alike — the bits one writes are the bits another reads."""
        seen = self.storage_signatures.setdefault(root, layout["signature"])
        if seen != layout["signature"]:
            raise Unsupported("storage_layout_differs_between_units:" + root)

    def ambiguous_root(self, base):
        """(R39 review C3) A struct member whose struct names more than one object in the project."""
        root = _root_object(base)
        return root != base and root in self.ambiguous_roots

    def all_statics(self):
        """Static locals of every activation this evaluation ran or is running."""
        out = set(self.static_keys)
        for it in self.stack:
            out |= it.static_keys
        return out

    def interpreted_names(self):
        return set(self.inlined) | {it.function_name for it in self.stack}

    def effectful(self, name, closure):
        """Could calling ``name`` change anything another call reads — a write, a pointer write, unknown code, or a
        static local in it or anything it reaches? (Unknown → yes.)"""
        info = closure.get(name)
        if info is None or info.get("writes") or info.get("pointer_write") or info.get("unknown_callees"):
            return True
        has_statics = getattr(self.provider, "has_static_locals", None)
        if has_statics is None:
            return True
        return any(has_statics(f) for f in {name} | set(info.get("reaches") or ()))

    def fail(self, name, reason):
        self.failed.setdefault(name, reason)
        key = reason.split(":", 1)[0]
        self.not_inlined[key] = self.not_inlined.get(key, 0) + 1
        return None

    def inline(self, caller, state, name, args):
        if name in self.failed:
            return self.fail(name, self.failed[name])
        if any(it.function_name == name for it in self.stack):
            # the callee re-enters a running activation: its static locals may change (the fallback havocs the rest)
            for it in self.stack:
                it.havoc_statics(state, "recursion_through:" + name)
            return self.fail(name, "recursion")
        if len(self.stack) > _INLINE_DEPTH:
            return self.fail(name, "inline_depth")
        try:
            raw, fn, scope, shared, _path = self.provider.definition(name, str(caller.scope.get("path") or ""))
        except Unsupported as exc:
            return self.fail(name, "definition:" + str(exc))
        collision = self.admit(scope)
        if collision is not None:
            return self.fail(name, "linkage_collision:" + collision)
        sub = _Interp(fn, raw, scope, caller.inputs, caller.parser, shared)
        sub.function_name, sub.world = name, self
        self.activations += 1
        sub.param_prefix = f"@param{self.activations}:"
        # a callee may spend at most half of what is left: a failed callee still leaves the caller room to finish
        sub.steps, sub.limit = caller.steps, caller.steps + max(1, (caller.limit - caller.steps) // 2)
        entry = state.copy()
        before = set(entry.store)
        self.stack.append(sub)
        try:
            _prescan_once(sub, shared)
            sub.bind_parameters(entry, args)
            finals = sub.run([entry], fn.child_by_field_name("body"))
            if any(s.mode in {"break", "continue"} for s in finals):
                raise Unsupported("jump_outside_loop")
        except Unsupported as exc:
            caller.steps = sub.steps
            if str(exc).startswith("undefined_behavior:") or str(exc) in _REFUSING_IN_CALLEE:
                raise  # proven on the run's only path (`_Interp.undefined`): the evaluation has no defined result
            return self.fail(name, str(exc))
        finally:
            self.stack.pop()
            self.kept.extend(sub.kept_raws)   # their ids are in local keys (review I2)
            # (R90 re-review 3 C-R3-2) the registers the callee read are the caller's reads too — a loop body (or
            #   condition) that reads its flag through a callee reads it (`loop_iterations`); aligned lists
            caller.volatile_polls.extend(sub.volatile_polls)
            caller.volatile_poll_members.extend(sub.volatile_poll_members)
        caller.steps = sub.steps
        caller.stubs_used |= sub.stubs_used
        caller.linked_reads |= sub.linked_reads
        caller.storage_used |= sub.storage_used   # (R90)
        caller.storage_volatile_reads |= sub.storage_volatile_reads
        caller.polling_assumed.extend(sub.polling_assumed)   # (R90 review W1)
        for root, spans in sub.storage_narrow.items():   # (R90 re-review I-1)
            caller.storage_narrow.setdefault(root, set()).update(spans)
        caller.storage_unspecified |= sub.storage_unspecified
        # (R17 review W2) the callee's unit text rests on its own #if verdicts too
        caller.assumed_undefined |= sub.assumed_undefined | set(scope.get("assumed_undefined") or ())
        caller.assumed_undefined |= set((getattr(self.provider, "binding_assumptions", None) or {}).get(
            (name, str(caller.scope.get("path") or "")), ()))
        self.static_keys |= sub.static_keys
        merged, returned = self.join(sub, finals, name)
        for key in list(merged.store):  # the callee's parameters and automatic locals end with its activation
            base = key.split("[", 1)[0]
            if key not in before and key.startswith("@") and base not in self.static_keys and base not in merged.escaped:
                del merged.store[key]   # (review I1) statics of callees it called stay too
        ret, selectors = state.ret, list(state.selectors)
        for slot in _State.__slots__:
            setattr(state, slot, getattr(merged, slot))
        # (R90 review C1) the joined state is every callee path: the call chose no path of the caller's
        state.mode, state.ret, state.selectors = "normal", ret, selectors
        # (review C3, W-R2-2) no re-application here: the callee's own havoc already judges by every admitted unit's
        # objects and every activation's static locals (`havoc_pointer_targets`, `all_statics`).
        self.inlined[name] = self.inlined.get(name, 0) + 1
        return returned

    @staticmethod
    def join(sub, finals, name):
        """One state and the returned value from the callee's final paths (see the class doc)."""
        rt = sub.return_type()
        void = isinstance(rt, Unknown) and rt.reason != "return_type_not_scalar" \
            and _text(sub.fn.child_by_field_name("type"), sub.raw).strip() == "void"
        if len(finals) == 1:
            merged = finals[0]
        else:
            merged = finals[0].copy()
            why = "path_dependent_in_callee:" + name
            # only the keys some path holds differently (the paths share most objects by identity — compared in C)
            try:
                first_items = set(finals[0].store.items())
                differing = set()
                for s in finals[1:]:
                    differing.update(k for k, _v in first_items.symmetric_difference(s.store.items()))
            except TypeError:  # a value that does not hash: compare every key
                differing = set().union(*(s.store for s in finals))
            for key in differing:
                values = [s.store.get(key, _MISSING) for s in finals]
                if ".@" in key:
                    merged.store[key] = _join_bytes(values, why)   # (R90) a union / bit-field object's byte
                    continue
                first = values[0]
                if first is _MISSING or isinstance(first, Unknown) or any(
                        v is _MISSING or isinstance(v, Unknown) or v != first for v in values[1:]):
                    known = next((v for v in values if isinstance(v, Unknown)), None)
                    same_unknown = known is not None and all(isinstance(v, Unknown) and v.reason == known.reason
                                                             for v in values)
                    merged.store[key] = Unknown(known.reason) if same_unknown else Unknown(why)
            for s in finals[1:]:
                merged.havoc_all = merged.havoc_all or s.havoc_all
                merged.havoc_pointer = merged.havoc_pointer or s.havoc_pointer
                for base, reason in s.havoc_bases.items():
                    merged.havoc_bases.setdefault(base, reason)
                merged.escaped |= s.escaped
                merged.possible_ub |= s.possible_ub
                merged.rebound |= s.rebound               # (review R82 C1) rebound on any callee path
                merged.initial_reads |= s.initial_reads   # (backlog 2-c) a read on any callee path is a read
                merged.forks.extend(f for f in s.forks if f not in merged.forks)
            if "callee_paths:" + name not in merged.forks:   # a loop joins the same callee many times: once is the fact
                merged.forks.append("callee_paths:" + name)
            # (R90 review C1) the joined state is every callee path: it proved undefined behaviour only if each did
            merged.ub_proven = finals[0].ub_proven if all(s.ub_proven for s in finals) else ""
        if void:
            return merged, _Val(Unknown("void_call_value:" + name), None)
        if not isinstance(rt, dict):
            return merged, _Val(Unknown(rt.reason if isinstance(rt, Unknown) else "return_type_unresolved"), None)
        rets = [s.ret if s.mode == "return" else None for s in finals]
        if any(r is None for r in rets):
            return merged, _Val(Unknown("no_return_value_on_path:" + name), rt)
        values = [r.v for r in rets]
        if all(not isinstance(v, Unknown) for v in values) and len(set(values)) == 1:
            return merged, _Val(values[0], rt)
        if len(values) == 1:
            return merged, _loaded(values[0], rt)
        return merged, _Val(Unknown("path_dependent_in_callee:" + name), rt)


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


def _observe(interp, state, name, reads=None, escaped=None):
    """Value an output name holds in a final state: an int, or Unknown. ``reads`` / ``escaped``: what any final path
    read / let escape (2-c)."""
    value = _observe_value(interp, state, name, reads, escaped)
    return Unknown("pointer_value") if isinstance(value, _Pointer) else value   # (R40) an address is no expected value


_POINTEE_NAME_RE = re.compile(r"([A-Za-z_]\w*)\[0\]((?:\.[A-Za-z_]\w*)*)(?:\[(\d+)\])?")
# (R82) an element of a pointer parameter's scalar pointee taken as a harness buffer (`pData[1]` — the reference's name)
_BUFFER_ELEMENT_RE = re.compile(r"([A-Za-z_]\w*)\[(\d+)\]")
HARNESS_BUFFER_LENGTH = 1 << 16   # (R82) a buffer as long as the function reaches; beyond any index a 16-bit count gives


def _pointee_key(interp, name):
    """(R40) ``p[0].a`` / ``p[0]`` / ``p[0].b[2]`` → ``(key, type, volatile)`` of a pointee the run set up, else None.
    (R82) ``p[k]`` — an element of a scalar pointee the harness holds as a buffer."""
    m = _POINTEE_NAME_RE.fullmatch(str(name).strip())
    if not m:
        b = _BUFFER_ELEMENT_RE.fullmatch(str(name).strip())
        layout = getattr(interp, "pointees", {}).get(b.group(1)) if b else None
        if not layout or not layout.get("buffer") or not 0 <= int(b.group(2)) < HARNESS_BUFFER_LENGTH:
            return None
        rec = layout["members"][""]
        return (f"@pointee:{b.group(1)}[{int(b.group(2))}]", rec["type"],
                bool(layout.get("volatile") or rec.get("volatile")))
    if m.group(1) not in getattr(interp, "pointees", {}):
        return None
    obj = interp.pointee_object(m.group(1), m.group(2))
    if obj[0] == "leaf" and m.group(3) is None:
        return obj[1], obj[2], obj[3]
    if obj[0] == "array" and m.group(3) is not None and 0 <= int(m.group(3)) < obj[3]:
        return f"{obj[1]}[{int(m.group(3))}]", obj[2], obj[4]
    return None


# (backlog 2-c) An output the path did not write holds its initial value. When the sequence did not set it, the oracle
#   cannot give the final value — and when no final path read it either (`_State.initial_reads`), it is the observation
#   that needs it, not the function. The old reason (`INITIAL_VALUE_PREFIX`) made R19 add X and the source findings call
#   it 'read before written, missing from the input list' — false for an output written only on some paths (`g_o` set
#   only inside an `if`). Read on any path — in a condition, in an operand that runs on some executions, as an unknown
#   part of its object, through a pointer the model cannot place when one may reach it, by a callee run as its effects
#   only (what its body and macros name), through a macro or a name the model does not evaluate — keeps the old reason.
#   Fail-closed (review round 2): a read the model cannot attribute (`_UNPLACED_READ`) leaves nothing unread.


_ANY_POINTER_READ = "@read_through_unknown_pointer"
_BASE_READ = "@read_part_of:"
_CALLEE_READS = "@read_by_callee:"     # + name: a callee run as its effects only — reads what its closure names
_UNPLACED_READ = "@read_unplaced"      # a read the model cannot attribute at all — nothing is reported as unread
_OBJECT_PATH_RE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")


def _containers(key):
    """``g_t.t[3]`` → ``g_t``, ``g_t.t``, ``g_t.t[3]``: the objects a key lies in, outermost first, itself last."""
    key = str(key)
    return [key[:i] for i in range(1, len(key)) if key[i] in ".["] + [key]


def _key_root(key):
    """The object a store key belongs to: ``g_buf[2]`` → ``g_buf``, ``g.s.x`` → ``g``, ``@pointee:p[0].a`` → ``@pointee:p``."""
    return str(key).split("[", 1)[0].split(".", 1)[0]


def _pointer_reachable(interp, escaped, key):
    """May a pointer reach this object (`havoc_pointer_targets`' judgment): a parameter's pointee, an array (arrays
    decay), an object whose address left this function on some final path (``escaped`` — review I-c) or was taken
    anywhere in the project."""
    base, root = str(key).split("[", 1)[0], _key_root(key)
    world = interp.world
    return root.startswith("@pointee:") or root in escaped or base in escaped or base in interp.arrays \
        or root in interp.arrays or (world is not None and (base in world.array_names or root in world.array_names)) \
        or base in interp.address_taken or root in interp.address_taken


def _read_on_some_path(interp, key, reads, escaped):
    """(backlog 2-c) Did some final path read ``key`` while unset — itself, the object it lies in (an unknown part of
    it), through a pointer the model cannot place (when one may reach it), in a callee run as its effects only (a name
    its closure mentions — or anything, when the closure cannot say), or anything at all (a read the model cannot
    attribute). Fail-closed: only what no recorded read may reach is unread."""
    if _UNPLACED_READ in reads or key in reads or any(_BASE_READ + c in reads for c in _containers(key)):
        return True
    if _ANY_POINTER_READ in reads and _pointer_reachable(interp, escaped, key):
        return True
    root = _key_root(key)
    for r in reads:
        if r.startswith(_CALLEE_READS):
            info = interp.closure.get(r[len(_CALLEE_READS):]) or {}
            if not info.get("reads_complete") or root in (info.get("reads") or ()):
                return True
    return False


def _unwritten(read, key, name, state, interp, reads=None, escaped=None):
    """The observed value of ``key``; when no final path read it (``reads``: the union of their reads — review C1: the
    first path's verdict alone depended on the order of the arms) and its initial value is not in the inputs, the reason
    says so (a written value can carry the initial-value reason of ``key`` only through a read of ``key``, which that
    path recorded). The observation's own read is not the function's: it is taken back, so observing an output twice on
    one state gives the same answer."""
    reads = state.initial_reads if reads is None else reads
    escaped = state.escaped if escaped is None else escaped
    read_before = _read_on_some_path(interp, key, reads, escaped)
    recorded = key in state.initial_reads
    value = read()
    if not recorded:
        state.initial_reads.discard(key)
    if not read_before and isinstance(value, Unknown) and value.reason == INITIAL_VALUE_PREFIX + name:
        return Unknown(UNWRITTEN_OUTPUT_PREFIX + name)
    return value


def _observe_value(interp, state, name, reads=None, escaped=None):
    if name == "return":
        if state.mode != "return" or state.ret is None:
            return Unknown("no_return_value_on_path")
        return state.ret.v
    pointee = _pointee_key(interp, name)
    if pointee is not None:
        return _unwritten(lambda: interp.read_pointee(state, *pointee), pointee[0], pointee[0][len("@pointee:"):],
                          state, interp, reads, escaped)
    if str(name).strip() in getattr(interp, "pointees", {}):
        # (R81) the out-parameter itself, observed: its pointee was set up and is observed by its own names
        return Unknown("pointer_value")
    # (R39) a struct member ``g.s.x`` / ``g.b[2]`` is a modeled object of its own name
    m = re.fullmatch(r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)(?:\[(\d+)\])?", str(name).strip())
    if not m:
        return Unknown("observable_form_unmodeled")
    base, index = m.group(1), m.group(2)
    macro_status = interp.macro_status
    if base in macro_status:
        return Unknown("observable_is_a_macro:" + base)
    globals_, arrays = interp.globals, interp.arrays
    if interp.world is not None and (base in interp.world.ambiguous or interp.world.ambiguous_root(base)):
        return Unknown("observable_name_ambiguous_in_project:" + base)
    if base not in globals_ and base not in arrays and interp.world is not None and base in interp.world.objects:
        # (R16) an object of another translation unit an interpreted callee saw (one linkage — `_World.admit`)
        kind, rec = interp.world.objects[base]
        globals_, arrays = ({base: rec}, {}) if kind == "global" else ({}, {base: rec})
    if index is None and base in globals_:
        g = globals_[base]
        return _unwritten(lambda: interp.read_key(state, base, base, g["type"], g.get("volatile")), base, base, state,
                          interp, reads, escaped)
    if index is not None and base in arrays:
        a = arrays[base]
        if a["length"] is None or not 0 <= int(index) < a["length"]:
            return Unknown("observable_index_outside_array")
        key = f"{base}[{int(index)}]"
        return _unwritten(lambda: interp.read_target(state, ("key", key, a["type"], a.get("volatile", False))).v, key, key,
                          state, interp, reads, escaped)
    storage = interp.storage_observable(base) if index is None and hasattr(interp, "storage_observable") else None
    if isinstance(storage, Unknown):
        return storage   # (R90) a union / bit-field object the model gives no value of here — why
    if storage is not None:
        # (R90) a member of a union / bit-field object (the object itself: its whole-object member) — from its bits
        key = f"{storage[0]}.{storage[3]}"
        return _unwritten(lambda: interp.read_storage(state, key, storage[:3], observe=True, name=base).v, key, base,
                          state, interp, reads, escaped)
    if base in (interp.scope.get("unresolved_globals") or {}):
        return Unknown(f"global_unmodeled:{base}:{interp.scope['unresolved_globals'][base]}")
    return Unknown("observable_not_a_modeled_object:" + base)


def _local_name(base):
    """(R64) The name of the parameter or local a store base belongs to (``@local:buf@u:…:12`` → ``buf``,
    ``@param2:p`` → ``p``), or None."""
    if base.startswith("@local:"):
        return base[len("@local:"):].split("@", 1)[0]
    m = re.match(r"@param\d*:(.+)$", base)
    return m.group(1) if m else None


def _maybe_pointer(flow, param):
    """(R64) Whether a parameter ``[name, base, kind]`` can hold a pointer a stub may write through: a pointer or an
    array parameter, a struct passed by value (its members may), a type the analysis cannot follow."""
    t = flow.norm((param[1], param[2]))
    if t is None:
        return True
    return t[1][:1] in ("p", "a") or (t[1] == "" and t[0].startswith("struct:"))


def _root_object(base):
    """(R39) The object a store key's base belongs to — ``g`` for a struct member ``g.s.x`` or member array ``g.b``."""
    return base.split(".", 1)[0]


def _object_prefixes(base):
    """(R39) The enclosing objects of a struct member, outermost first: ``g.s.x`` → ``g``, ``g.s``."""
    parts = base.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts))]


def _written(state, name, interp=None):
    key = str(name).strip()
    storage = interp.storage_observable(key) if interp is not None and hasattr(interp, "storage_observable") else None
    if storage is not None and not isinstance(storage, Unknown):
        return interp.storage_written(state, storage)   # (R90) a bit it occupies, through any member of the object
    pointee = _pointee_key(interp, key) if interp is not None else None
    return (pointee[0] if pointee is not None else key) in state.store


def _signature_types(fn, raw: bytes, body: bytes) -> bytes:
    """(review R83 W-R5-1) The type text of a function definition's return and of each parameter its body names (by the
    parameter's identifier) — the names only, never the parameters' own names."""
    words = set(re.findall(rb"[A-Za-z_]\w*", body))
    out = []
    t = fn.child_by_field_name("type")
    if t is not None:
        out.append(raw[t.start_byte:t.end_byte])
    decl = fn.child_by_field_name("declarator")
    while decl is not None and decl.type != "function_declarator":
        decl = decl.child_by_field_name("declarator")
    plist = decl.child_by_field_name("parameters") if decl is not None else None
    for prm in plist.named_children if plist is not None else ():
        if prm.type != "parameter_declaration":
            continue
        d = prm.child_by_field_name("declarator")
        while d is not None and d.type != "identifier":
            d = d.child_by_field_name("declarator")
        pt = prm.child_by_field_name("type")
        if d is not None and pt is not None and raw[d.start_byte:d.end_byte] in words:
            out.append(raw[pt.start_byte:pt.end_byte])
    return b" ".join(out)


def _exact_width_uses(scope: dict[str, Any], body: bytes, fn_name: str, signature: bytes = b"") -> set[str]:
    """(R83, review W3 · W-R2-3 · W-R3-4) The exact-width typedefs read past their `#ifndef` guard that a function's text
    body uses — or its return type, or the declared type of a parameter the body names (``signature``, review W-R5-1):
    the name, an alias of it (TPE_ErrCode), or an object of a type that rests on it — a global (a struct's
    member ``g.a`` by the struct's name, so any member counts: generous), an array (const tables too), the pointee of a
    pointer parameter the body names (any member). Not seen: a use only inside a macro body or a callee, a const scalar
    (a lookup would resolve every word of the body as a constant and record the failures in the shared scope), a stub's
    declared return type — the build-assumption summary counts every unit that read such a typedef."""
    if not scope.get("exact_width_guards"):
        return set()
    words = {w.decode() for w in re.findall(rb"[A-Za-z_]\w*", body)}
    # the signature's type names (return type, used parameters' types) — types only, so no parameter's name enters
    type_words = words | {w.decode() for w in re.findall(rb"[A-Za-z_]\w*", signature)}

    def mark(t: Any) -> str | None:
        return t.get("exact_width_guard") if isinstance(t, dict) else None

    out: set[str] = set()
    types = scope.get("types") or {}
    for table in (scope.get("globals") or {}, scope.get("arrays") or {}):
        for n, rec in table.items():
            if n.split(".", 1)[0] in words and isinstance(rec, dict) and (m := mark(rec.get("type"))):
                out.add(m)
    for w in type_words:
        if (m := mark(types.get(w))):
            out.add(m)
    for p in ((scope.get("pointer_params") or {}).get(fn_name) or []):
        layout = (scope.get("pointee_types") or {}).get(" ".join(
            w for w in str(p.get("type") or "").split() if w not in {"const", "volatile"})) or {}
        if p.get("name") in words:
            for part in ("members", "arrays", "pointers"):
                for rec in (layout.get(part) or {}).values():
                    if isinstance(rec, dict) and (m := mark(rec.get("type"))):
                        out.add(m)
    return out


def _scope_assumptions(unit: dict[str, Any]) -> list[str]:
    """What the project preprocessing assumed for this unit — carried into every derived value (review round 5 W-a):
    toolchain headers taken as compiler-supplied, the typedef testimony the integer widths rest on."""
    scope = unit.get("project_scope") or {}
    out = []
    if scope.get("toolchain_includes"):
        out.append("toolchain headers (not in the source tree, resolved by the build configuration): "
                   + ", ".join(scope["toolchain_includes"][:8]) + " — assumed not to define project names")
    if scope.get("assumed_undefined"):
        # (R17) the #if verdicts the unit's text rests on: names taken as undefined on build-configuration evidence
        out.append("undefined in #if on build-configuration evidence (no -D, not an implementation name): "
                   + ", ".join(scope["assumed_undefined"][:12])
                   + (f" (+{len(scope['assumed_undefined']) - 12})" if len(scope["assumed_undefined"]) > 12 else ""))
    widths = (scope.get("target") or {}).get("widths") or {}
    if widths:
        out.append("integer widths from typedef testimony: " + ", ".join(f"{k}={v}" for k, v in sorted(widths.items())))
    return out


def scope_matches(unit: dict[str, Any]) -> bool:
    """Is the unit's text the one its scope was built from — as read, or with its body conditionals projected (R62)?"""
    scope = unit.get("project_scope") or {}
    return bool(scope) and scope.get("schema_version") == cpc.SCHEMA_VERSION and \
        cpc.scope_text_matches(scope, hashlib.sha256(str(unit.get("source_text") or "").encode()).hexdigest())


def evaluate_outputs(unit: dict[str, Any], sequences_inputs: list[dict[str, Any]], outputs: list[list[str]],
                     written: bool = False) -> list[dict[str, Any]]:
    """Per sequence: ``{"status", "outputs": {name: {"value": int} | {"reason": str}}, ...}``.

    ``unit`` carries ``source_text``, ``name`` and a matching ``project_scope``. The function is parsed once;
    each sequence runs on a fresh state. Never raises. ``written`` (R80): a supported record also carries
    ``"written"`` — the program objects of this translation unit the run wrote (`_written_objects`).
    """
    source = str(unit.get("source_text") or "")
    digest = hashlib.sha256(source.encode()).hexdigest()
    base = {"schema_version": SCHEMA_VERSION, "execution_status": "not_run", "reachability": "unverified",
            "source_hash": digest, "function_name": str(unit.get("name") or ""), "oracle": "project_context_source",
            "assumptions": list(ASSUMPTIONS) + _scope_assumptions(unit)}
    try:
        if not source or not unit.get("source_text_complete", True):
            raise Unsupported(unit.get("source_unavailable_reason") or "authoritative_source_missing")
        if unit.get("oracle_refusal"):
            raise Unsupported(str(unit["oracle_refusal"]))  # (R16) the caller decided not to run these sequences — why
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
        # (R83, review W3 · W-R2-3) the exact-width typedefs read past their `#ifndef` guard that this function's text
        #   uses — by the name, an alias of it (TPE_ErrCode) or a global declared with it; a use only inside a macro body
        #   or a callee is not seen (the build-assumption summary counts every unit that read such a typedef)
        # (review R83 I-R4-2a · W-R5-1) the body, the return type, and the declared types of the parameters the body
        #   names — the declarator names every parameter whether the body uses it or not
        _body = fn.child_by_field_name("body") or fn
        _text_body = raw[_body.start_byte:_body.end_byte]
        exact = sorted(_exact_width_uses(scope, _text_body, str(unit.get("name") or ""),
                                         _signature_types(fn, raw, _text_body)))
        if exact:
            base["assumptions"] = list(base["assumptions"]) + [
                "the tree's typedef of " + ", ".join(exact) + " is read past its undecided `#ifndef` guard: a header "
                "outside the tree that made the name a macro would name the implementation's exact-width type of the "
                "same width and signedness (C11 7.20.1.1), which computes alike"]
            base["exact_width_guards"] = exact
    except Exception as exc:  # noqa: BLE001 — never raise into the generator; the reason is the record
        reason = str(exc) if isinstance(exc, Unsupported) else f"oracle_exception:{type(exc).__name__}"
        return [{**base, "status": "unsupported", "reason": reason,
                 "outputs": {o: {"reason": reason} for o in outs}} for outs in outputs]
    provider = unit.get("callee_provider")
    if provider is not None:
        # (R16) integration reading: callees with a project definition run for real (see `_World`)
        base["assumptions"] = [a for a in base["assumptions"] if not a.startswith("callee effects are")] + [
            "callees with one definition in the project are interpreted with the argument values (the integrated "
            "code, not stubs); where a callee cannot be interpreted its effects are the project write closure — "
            "outputs it may write are unknown",
            "hardware, interrupts and concurrent tasks do not change objects during the run (volatile reads are unknown)"]
        base["oracle"] = "project_context_source_interprocedural"
    results = []
    for inputs, outs in zip(sequences_inputs, outputs, strict=True):
        record = dict(base)
        interp = None
        try:
            interp = _Interp(fn, raw, scope, dict(inputs or {}), parser, shared)
            interp.function_name = str(unit.get("name") or "")
            interp.observed = _observed_names(unit, outs)   # (R81) before the parameters bind
            world = None
            if provider is not None:
                interp.world = world = _World(provider, interp, str(unit.get("source_path") or ""))
            _prescan_once(interp, shared)  # path-independent refusals: once per function
            state = _State()
            interp.bind_parameters(state)
            finals = interp.run([state], fn.child_by_field_name("body"))
            if any(s.mode in {"break", "continue"} for s in finals):
                raise Unsupported("jump_outside_loop")
            _every_path_undefined(finals)   # (R90 review C1)
            values = _final_outputs(interp, finals, outs)
            possible = sorted({k for s in finals for k in s.possible_ub})
            if interp.storage_used:
                record["assumptions"] = _storage_assumptions(record["assumptions"], interp)   # (R90)
                record["storage_objects"] = sorted(interp.storage_used)
                if interp.storage_volatile_reads:
                    # (re-review W-N3) registers the run read as harness memory (`STORAGE_VOLATILE_ASSUMPTION`)
                    record["storage_registers"] = sorted(interp.storage_volatile_reads)
                if interp.polling_assumed:
                    record["polling_loops_assumed"] = list(interp.polling_assumed)   # (R90 review W1)
            if interp.stubs_used:
                record["assumptions"] = list(record["assumptions"]) + [
                    "stubbed by the sequence: " + ", ".join(
                        f"{n}() returns the value set in '{n}() return'" if f"{n}() return" in interp.inputs
                        else f"{n}() is a stub (the sequence sets its out-parameters, not its return value)"
                        for n in sorted(interp.stubs_used))
                    + " (a stub writes no global or static; what it may put through a pointer argument stays unknown)"]
                record["stubs"] = sorted(interp.stubs_used)
            if interp.observed_only_pointees:
                # (review R81 W3) the row sets none of these pointees' values: the harness object rests on what the row
                #   observes (its expected values name them) — say so on this row's values
                names = sorted(interp.observed_only_pointees)
                record["assumptions"] = list(record["assumptions"]) + [
                    "pointer parameter(s) " + ", ".join(names) + " point to a harness object because the row observes "
                    "what the function leaves there (its expected values name the pointee); the row sets no value in it"]
                record["observed_only_pointees"] = names
            if interp.harness_buffers:
                # (review R82 W-R2-3) the harness buffers this row's values rest on — said on this row only (a function
                #   with no buffer keeps its assumptions as they were)
                bufs = {k[len("@pointee:"):]: (v if v is not None else "unbounded")
                        for k, v in sorted(interp.harness_buffers.items())}
                reach = {k[len("@pointee:"):]: v for k, v in sorted(interp.buffer_reach.items())}
                unknown = sorted(k[len("@pointee:"):] for k in interp.buffer_reach_unknown)
                record["assumptions"] = list(record["assumptions"]) + [
                    "harness buffers: a pointer parameter's scalar pointee and a pointer member the row names (p[k], "
                    "p[0].m[k]) are buffers of their own — not null, no alias with another object; allocated up to the last "
                    "element the row names (a member the row names itself, element columns or not: as far as the function "
                    "reaches); an element the row does not set is unknown; a write past the allocation may reach any object "
                    "(possible UB); a callee writing through a buffer argument writes inside it; the value in a pointer "
                    "member's own column is not used as a pointer (" + ", ".join(
                        f"{n} {e}" + (f" — reached [{reach[n]}]" if n in reach else "")
                        + (" — also at an index the run does not know" if n in unknown else "")
                        for n, e in bufs.items()) + ")"]
                record["harness_buffers"] = bufs
                if reach:
                    record["harness_buffer_reach"] = reach
                if unknown:
                    record["harness_buffer_reach_unknown"] = unknown
            if interp.linked_reads:
                record["assumptions"] = list(record["assumptions"]) + [
                    "const values taken from the one definition in another unit (the source hash covers this function's "
                    "file only): " + ", ".join(sorted(interp.linked_reads)[:12])
                    + (f" (+{len(interp.linked_reads) - 12})" if len(interp.linked_reads) > 12 else "")]
            own = set((unit.get("project_scope") or {}).get("assumed_undefined") or ())
            if interp.assumed_undefined - own:
                # (R17) #if verdicts this run rested on beyond the unit's file-level ones: function bodies, callee units
                extra = sorted(interp.assumed_undefined - own)
                record["assumptions"] = list(record["assumptions"]) + [
                    "undefined in #if on build-configuration evidence (function bodies / interpreted callee units): "
                    + ", ".join(extra[:12]) + (f" (+{len(extra) - 12})" if len(extra) > 12 else "")]
                record["assumed_undefined"] = sorted(interp.assumed_undefined | own)
            elif own:
                record["assumed_undefined"] = sorted(own)
            if world is not None:
                # (R16) which callees ran for real and why the others did not (per sequence — the value's footing)
                record["interprocedural"] = {"inlined": dict(sorted(world.inlined.items())),
                                             "not_inlined": dict(sorted(world.not_inlined.items())),
                                             "effects_only": dict(sorted(world.effects_only.items())),
                                             "failed": dict(sorted(world.failed.items()))}
            record.update(status="supported", reason="project_context_source_evaluation" +
                          (":possible_ub=" + "+".join(possible) if possible else ""),
                          outputs=values, paths=len(finals), possible_undefined_behavior=possible)
            forked = forked_path_ub(possible)
            if forked:
                # (R90 review C1) proven on a path an unknown branch chose — the path ran on with the faulting result
                #   unknown; still a defect candidate of the source (`source_findings`), said on every derived value
                record["forked_path_undefined_behavior"] = [{"kind": k, "selector": sel} for k, sel in forked]
                record["assumptions"] = list(record["assumptions"]) + [
                    "possible_ub_on_forked_path: undefined behaviour proven on a path a branch on an unknown value chose ("
                    + "; ".join(f"{k} — chosen by {sel}" for k, sel in forked[:6])
                    + (f"; +{len(forked) - 6}" if len(forked) > 6 else "") + ") — that path ran on with the faulting "
                    "operation's result unknown (an out-of-bounds write: the whole array); a value derived here holds for "
                    "runs that do not take it"]
            if written:
                try:
                    why: dict[str, str] = {}
                    record["written"] = _written_objects(interp, finals, why)
                    if why:
                        record["written_unknown"] = why   # (R81)
                except Exception as exc:  # noqa: BLE001 — (review R80 W1) a side record; the derived values stand
                    record["written_error"] = f"oracle_exception:{type(exc).__name__}"
        except Unsupported as exc:
            record.update(status="unsupported", reason=str(exc), outputs={o: {"reason": str(exc)} for o in outs})
            if interp is not None and interp.storage_used:
                # (R90 re-review 4 W-R4-4) refused, but on the storage model: a UB-probe claim on it is not clang-checked
                record["storage_objects"] = sorted(interp.storage_used)
        except Exception as exc:  # noqa: BLE001 — never raise into the generator; recorded as the reason below
            reason = f"oracle_exception:{type(exc).__name__}"
            record.update(status="unsupported", reason=reason, outputs={o: {"reason": reason} for o in outs})
        results.append(record)
    return results


def _every_path_undefined(finals):
    """(R90 review C1) Refuse a run whose every final path proved undefined behaviour (`_Interp.undefined` tolerates it
    on a path an unknown branch chose): whichever way those branches go, the run has it — ``if (u) { x = 10U / 0U; }
    else { y = 20U / 0U; }`` is no run without undefined behaviour."""
    if finals and all(s.ub_proven for s in finals):
        raise Unsupported("undefined_behavior:" + finals[0].ub_proven)


STORAGE_ASSUMPTION = (
    "(R90) a union / bit-field object is one storage of its size every member reads and writes: members at their "
    "offsets (a layout padding could change is not modeled), bit-fields allocated from the end of their unit the "
    "bit-field allocation below names (a layout the header's NAME_MASK / NAME_BITNUM macros contradict is dropped), a "
    "signed member that is no bit-field in two's complement; a value is given only where every byte order, bit-field "
    "unit and allocation end kept gives the same one; a bit the run did not write holds the value the row sets for a member (or for the object, read as its "
    "whole-object member) — two members the row sets that disagree on a bit leave it unknown; a write through a pointer "
    "that may reach a register (one whose address is taken, offset to its neighbours) leaves every register unknown, "
    "as does a callee the run does not interpret (it may wait on one; a sequence stub does not), and a register read "
    "beside any call but a sequence stub's in one expression is refused as unsequenced")
STORAGE_VOLATILE_ASSUMPTION = (
    "(R90) a volatile union / bit-field object (a register) is memory in the test harness: it reads what the run "
    "last wrote to it, else what the row sets — hardware does not change it during the run")
STORAGE_POLLING_ASSUMPTION = (
    "(R90) polling loop on a hardware flag assumed to terminate — the harness must stub or simulate the flag (under the "
    "model the register keeps its value and the loop never ends): taken only where a value of the flag ends the loop "
    "and a poll changes nothing else (body, update and condition — the state after it is the same after any number of "
    "polls); after the loop the polled register is unknown")
# (R90 re-review I-1) C11 6.2.6.1p7 — a store through a union member leaves the union's bytes that member does not cover
#   unspecified; the model keeps what they held
STORAGE_NARROW_ASSUMPTION = (
    "(R90) a store through a union member narrower than its union leaves the union's other bytes holding what they "
    "held (C11 6.2.6.1p7 leaves them unspecified) — read through a wider member")


def _storage_assumptions(assumptions, interp):
    """(R90) The record's assumptions with what its values on union / bit-field objects rest on (`STORAGE_ASSUMPTION`,
    the byte order of each object's layout — review W2 —, the harness memory of registers, the polling loops assumed to
    end — review W1). Never contradictory: the blanket "volatile reads are unknown" names its exceptions."""
    used = sorted(interp.storage_used)
    out = [a for a in assumptions]
    layouts = [interp.storage_root(r, world=True) or {} for r in used]
    bases = sorted({str(lay.get("byte_order_basis") or "none assumed") for lay in layouts})
    # (re-review W-N2) and the end of a unit bit-fields are allocated from
    ends = sorted({str(lay.get("bit_order_basis") or "unrecorded") for lay in layouts})
    out.append(STORAGE_ASSUMPTION + "; byte order: " + " / ".join(bases) + "; bit-field allocation: " + " / ".join(ends)
               + ": " + ", ".join(used[:12]) + (f" (+{len(used) - 12})" if len(used) > 12 else ""))
    if interp.storage_unspecified:
        narrow = sorted(interp.storage_unspecified)
        out.append(STORAGE_NARROW_ASSUMPTION + ": " + ", ".join(narrow[:12])
                   + (f" (+{len(narrow) - 12})" if len(narrow) > 12 else ""))
    if interp.storage_volatile_reads or interp.polling_assumed:
        vol = sorted(interp.storage_volatile_reads)
        exception = "registers (R90)" + (" and polled flags assumed to clear" if interp.polling_assumed else "")
        out = [a.replace("do not change objects during the run (volatile reads are unknown)",
                         "do not change objects during the run, except as stated for " + exception
                         + " (other volatile reads are unknown)") for a in out]
        if vol:
            out.append(STORAGE_VOLATILE_ASSUMPTION + ": " + ", ".join(vol[:12])
                       + (f" (+{len(vol) - 12})" if len(vol) > 12 else ""))
    if interp.polling_assumed:
        loops = list(dict.fromkeys(interp.polling_assumed))
        out.append(STORAGE_POLLING_ASSUMPTION + f" — {len(loops)} loop(s): " + ", ".join(loops[:8])
                   + (f" (+{len(loops) - 8})" if len(loops) > 8 else ""))
    return out


def _final_outputs(interp, finals, outs):
    """``{name: {"value", "basis"} | {"reason"}}`` for the outputs ``outs`` after a run ending in the paths ``finals`` —
    one reading for `evaluate_outputs` and `observe_decisions` (R78: a search that ranks runs by their derived outputs
    reads them as the evidence will)."""
    values = {}
    reads = set().union(*(s.initial_reads for s in finals))   # (backlog 2-c review C1) any path's read
    escaped = set().union(*(s.escaped for s in finals))       # (review round 2 I-c) any path's escape
    for name in outs:
        seen = [_observe(interp, s, name, reads, escaped) for s in finals]
        unknown = next((v for v in seen if isinstance(v, Unknown)), None)
        if unknown is not None:
            values[name] = {"reason": unknown.reason}
        elif len(set(seen)) != 1:
            forks = next((f for s in finals for f in s.forks), "branch_on_unknown")
            values[name] = {"reason": "path_dependent:" + forks}
        else:
            # ``assigned``: some path wrote it; ``unchanged_input``: no path wrote it and the value is the one the
            # sequence set (both are code-consistent expectations; the split keeps the second from inflating).
            assigned = name == "return" or any(_written(s, name, interp) for s in finals)
            values[name] = {"value": seen[0], "basis": "assigned" if assigned else "unchanged_input"}
    return values


def _is_buffer_element(name, param):
    """(R82) Whether ``name`` is ``param[k]`` — an element of the parameter's pointee taken as a harness buffer."""
    m = _BUFFER_ELEMENT_RE.fullmatch(str(name).strip())
    return bool(m) and m.group(1) == param


def _element_index(name, base):
    """(R82) ``k`` when ``name`` is ``base[k]`` (``pData[1]`` of ``pData`` · ``msg[0].data[3]`` of ``msg[0].data``), else
    None."""
    text = str(name).strip()
    if not text.startswith(base + "[") or not text.endswith("]"):
        return None
    index = text[len(base) + 1:-1]
    return int(index) if index.isdigit() else None


def _observed_names(unit, outs):
    """(R81) The names a run is observed by: the row's outputs and the unit's (``output_vars`` — every row of a SUTS unit
    states its output columns, so its searches see the pointees its evidence sets up)."""
    return frozenset(str(o) for o in outs) | frozenset(str(o) for o in (unit.get("output_vars") or ()))


def _written_objects(interp, finals, why=None):
    """(R80) ``{name: known}`` — the program objects of this translation unit some final path of the run *wrote* (a store
    key: a read is not stored; a parameter or local is an ``@`` key), ``known`` when the value after the run is one
    integer on every path (as `_final_outputs` reads an output). An object only a callee's write closure or a pointer
    write may change is havocked where it was stored and never stored otherwise — no value to expect, not here. Only this
    unit's objects (an interpreted callee of another unit stores its own — R16). (R81) A pointer parameter's pointee the
    row set up (`pointee_binding`) is the harness object an out-parameter writes: its written members and elements are
    named as the reference writes them (``p[0]`` · ``p[0].a`` · ``p[0].b[2]``); a whole pointee or nested struct is not.
    ``why`` (R81): filled with the reason of each one not known — a counter written from its own initial value
    (``s_cnt++``) names the input it lacks, which no expected value names while the object is no column yet."""
    keys = sorted({k for s in finals for k in s.store if not k.startswith("@") or k.startswith("@pointee:")})
    if not keys:
        return {}
    reads = set().union(*(s.initial_reads for s in finals))
    escaped = set().union(*(s.escaped for s in finals))
    out = {}
    for key in keys:
        if key.startswith("@pointee:"):
            name = key[len("@pointee:"):]
            found = _pointee_key(interp, name)
            if found is None or found[0] != key:
                continue
        else:
            name, base = key, key.split("[", 1)[0]
            if ("[" in key and base not in interp.arrays) or ("[" not in key and base not in interp.globals):
                continue
        seen = [_observe(interp, s, name, reads, escaped) for s in finals]
        out[name] = not any(isinstance(v, Unknown) for v in seen) and len(set(seen)) == 1
        if not out[name] and why is not None:
            unknown = next((v for v in seen if isinstance(v, Unknown)), None)
            why[name] = unknown.reason if unknown is not None else "path_dependent"
    return out


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


def _paths_by_key(finals, tag, count):
    """(R79 review I-R2-3) `_guard_paths` for every index of one tag (``("reach", i)``, ``("operand", i)`` …) in one
    pass over each path's records — per index, per path, the outcomes in order."""
    out = {i: [[] for _ in finals] for i in range(count)}
    for p, s in enumerate(finals):
        for k, obs in s.decisions:
            if type(k) is tuple and len(k) == 2 and k[0] == tag and k[1] in out:
                out[k[1]][p].append(obs[1] if obs[0] == "outcome" else None)
    return out


def observe_decisions(unit: dict[str, Any], vectors: list[dict[str, Any]],
                      decisions: list[dict[str, Any]], guards: list[list] | tuple = (),
                      step_limit: int | None = None, inert_stub_calls: bool = False, reach: list[list] | tuple = (),
                      outputs: list[str] | None = None, operands: list[list] | tuple = (),
                      writes: list[list] | tuple = (), perturb: list | tuple | None = None) -> list[dict[str, Any]]:
    """(R2c) Per input vector: how each decision of the function evaluates on the modeled run.

    ``decisions``: ``[{"key": [start, end, type], "atoms": [[start, end, type], ...], "ir": nested list}]`` over the
    unit's source text (the decision node, its conditions in order, and the ``&&``/``||``/``!`` structure with
    ``["atom", i]`` leaves). Per vector: ``{"status", "reason", "decisions": {index: summary}}`` where a summary is
    ``{"state": "evaluated", "evaluations", "instances": [{"truth", "observed", "decision"}]}`` only when every modeled
    path evaluates the decision the same determined way (see `_summarize`). A decision with a condition that writes or
    calls is ``effectful_condition`` for every vector (see `_Interp.atom_effectful`). ``guards``: control conditions
    (``[start, end, type]`` of an ``if``/loop/``?:`` condition) whose outcomes per path are returned under ``"guards"``
    — how far a vector gets towards a decision it does not reach. Never raises.

    (R78) ``reach``: statements (``[start, end, type]``) — per path, one flag per execution under ``"reach"`` (True: no
    branch on an unknown value before it on that path). ``outputs``: names read after the run as `evaluate_outputs` reads
    them, under ``"outputs"``. Every supported run also says whether it branched on an unknown value (``"forked"``).

    (R79) ``operands``: binary operators (``[start, end, type]``) — per path, the ``(left, right)`` integers of each
    evaluation under ``"operands"`` (None where a side is not a known integer). ``writes``: assignment expressions — per
    path, ``(replaced, written)`` of each execution under ``"writes"``. Operands are recorded as the operator uses them
    (after the usual arithmetic conversions). A watched comparison that is a condition of a watched decision also gets
    ``(left, right, decides)`` per evaluation under ``"decides"`` (one evaluation: in a loop the sides may be equal on
    one pass and the condition decide on another). Watching adds no step to a run and no read to ``initial_reads``.

    (R84) ``perturb``: ``[kind, [start, end, type]]`` — every run of this call changes that one site's value
    (`_Interp.perturbed_binary` · a ``skip_write`` assignment): what a propagation check compares with the plain run.

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
        reach_keys = {tuple(k): ("reach", index) for index, k in enumerate(reach)}
        operand_keys = {tuple(k): ("operand", index) for index, k in enumerate(operands)}
        write_keys = {tuple(k): ("write", index) for index, k in enumerate(writes)}
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
    # (R37) stubs every vector sets: a call to one of them in a condition may be judged by its write closure — asked
    # for by the call-in-condition decisions' own search only (``inert_stub_calls``): every other search sees such a
    # condition as effectful, as before R37 (review round 4 C1: the judgment leaked into R36's stub search)
    stubbed = set.intersection(*(set(v or ()) for v in vectors)) if vectors and inert_stub_calls else set()
    probe_inputs = {k: 0 for k in stubbed if k.endswith("() return")}
    if probe_inputs:
        # (R38 review W3) a stub whose out-parameter any vector sets writes through its pointers on that run: the
        # probe's pointer judgment (`stub_view`) is at least as broad as every vector's
        probe_inputs.update({k: 0 for v in vectors for k in (v or ())
                             if "() " in str(k) and not str(k).endswith("() return")})
    try:
        probe_interp = _Interp(fn, raw, scope, probe_inputs, parser, shared)
        probe_interp.function_name = str(unit.get("name") or "")
        _prescan_once(probe_interp, shared)  # path-independent refusals: once per function, not per vector
        for key, spec in list(specs.items()):
            if any(probe_interp.atom_effectful(a, raw) for a in spec["atoms"]):
                broken[spec["key"]] = "effectful_condition"
                del specs[key]
    except Exception as exc:  # noqa: BLE001 — never raise into the generator (R2c review round 1 W4)
        reason = str(exc) if isinstance(exc, Unsupported) else f"oracle_exception:{type(exc).__name__}"
        return [{"status": "unsupported", "reason": reason, "decisions": {}} for _ in vectors]
    results = []
    # (R36) ``step_limit``: the caller's search budget left. A run may use a quarter of what is left (at least 2,000
    # steps while that much is left) and a vector after it is spent does not run — one loop that a stub value never lets
    # end (``while (st() != 3U)``) would otherwise run to the loop budget and take the whole search with it
    remaining = step_limit
    for inputs in vectors:
        record = {"status": "supported", "reason": "", "decisions": {i: {"state": why} for i, why in broken.items()}}
        if remaining is not None and remaining <= 0:
            record.update(status="unsupported", reason="search_step_budget", steps=0)
            results.append(record)
            continue
        interp = None
        try:
            interp = _Interp(fn, raw, scope, dict(inputs or {}), parser, shared)
            if remaining is not None:
                interp.limit = min(interp.limit, max(remaining // 4, min(remaining, 2_000)))
            interp.function_name = str(unit.get("name") or "")
            # (R81) a search sees the pointees its rows' evidence will set up — the unit's outputs (and the asked ones)
            interp.observed = _observed_names(unit, outputs or ())
            interp.watch = specs
            interp.guards = guard_keys
            interp.statement_marks = reach_keys
            interp.operand_marks = operand_keys
            interp.write_marks = write_keys
            interp.perturb = (str(perturb[0]), tuple(perturb[1])) if perturb else None
            state = _State()
            interp.bind_parameters(state)
            finals = interp.run([state], fn.child_by_field_name("body"))
            if any(s.mode in {"break", "continue"} for s in finals):
                raise Unsupported("jump_outside_loop")
            _every_path_undefined(finals)   # (R90 review C1)
            record["steps"] = interp.steps  # (R2c) the run's cost: callers budget searches by it (deterministic)
            for spec in specs.values():
                record["decisions"][spec["key"]] = _summarize(finals, spec["key"])
            if guard_keys:
                record["guards"] = _paths_by_key(finals, "guard", len(guards))
            if reach_keys:
                record["reach"] = _paths_by_key(finals, "reach", len(reach))
                # (R78) objects a path read whose initial value the vector does not give — what a search must set too
                record["initial_reads"] = sorted(set().union(*(s.initial_reads for s in finals)))
            if operand_keys:
                record["operands"] = _paths_by_key(finals, "operand", len(operands))
                # (R79 review W1) a watched comparison that is a condition of a watched decision: per evaluation
                #   ``(left, right, decides)`` — the operands and whether flipping it flips the decision, together
                record["decides"] = _paths_by_key(finals, "decide", len(operands))
            if write_keys:
                record["writes"] = _paths_by_key(finals, "write", len(writes))
            if outputs is not None:
                record["outputs"] = _final_outputs(interp, finals, outputs)
            record["forked"] = any(s.forks for s in finals)
            possible = sorted({k for s in finals for k in s.possible_ub})
            if possible:
                # Undefined behaviour that depends on an unknown value may happen on this run *after* the decision (an
                # observation with it before is ``undetermined``): disclosed, as for outputs.
                record["possible_undefined_behavior"] = possible
            if interp.storage_used:
                # (R90 re-review 4 W-R4-4) the run rests on the union / bit-field storage model: a decision claim on it
                #   is not one the clang checks can reproduce (`unchecked:storage_model`)
                record["storage_objects"] = sorted(interp.storage_used)
        except Unsupported as exc:
            record.update(status="unsupported", reason=str(exc), steps=interp.steps if interp is not None else 0)
        except Exception as exc:  # noqa: BLE001 — never raise into the generator; recorded as the reason
            record.update(status="unsupported", reason=f"oracle_exception:{type(exc).__name__}",
                          steps=interp.steps if interp is not None else 0)
        if remaining is not None:
            remaining -= int(record.get("steps") or 0)
        results.append(record)
    return results


def _ir_tuple(ir):
    """JSON form (``["&&", l, r]``, ``["!", x]``, ``["atom", i]``) → the tuple form `record_decision` walks."""
    if ir[0] == "atom":
        return ("atom", int(ir[1]))
    if ir[0] == "!":
        return ("!", _ir_tuple(ir[1]))
    return (ir[0], _ir_tuple(ir[1]), _ir_tuple(ir[2]))
