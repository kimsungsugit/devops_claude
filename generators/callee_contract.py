"""The callee summary contract: what a call does, said once (`callee_contract_design`, steps 2–4).

A call is produced four ways — **interpreted** (`_World.inline` runs the callee's body on the caller's state), **effects
only** (its project write closure stands for it: a unit run, or a world that did not interpret it), a **sequence stub**
(R14 / R38: the row sets ``F() return`` / ``F() p[0]`` — the harness replaces the body) and **unknown code** (a prototype
only, a function pointer, a name a missing include may make a macro). Before this module each judgement point read the
closure fields itself (``writes``, ``pointer_write``, ``unknown_callees``, ``reads`` …) and each producer applied its own
effects in its own order — an aspect added in one place was missed in another mode (the gaps of the design: G4–G13).

Two layers:

* `CalleeSummary` — static, per (build closure, name): what the callee's text (or the row's stub) may do. `summary_for`
  gives the stub summary of a call the row stubs (never cached — it rests on the row) or the closure summary (cached in
  ``interp.shared["callee_summaries"]`` by the closure's identity, which the entry keeps alive), None for unknown code.
  The judgement points ask its predicates — never its fields (`tests/unit/test_callee_contract_structure.py` holds the
  oracle to that): `CalleeSummary.may_change` (J1 — sequencing), `CalleeSummary.effectful` (J3 — an unordered call
  site), `CalleeSummary.inert` (J2 / J6 — a call in a condition or beside a macro), `CalleeSummary.may_read` (J9 —
  `_read_on_some_path`), `CalleeSummary.volatile_reads` (the F6 register havoc), `CalleeSummary.stub_hedge` (the hedge
  of `_Interp.stub_view`).
* `CallOutcome` — dynamic, per call site and row: what this call did, aspect by aspect (`ASPECTS`). Four producers make
  one (`interpreted_outcome`, `effects_outcome`, `stub_outcome`, `unknown_outcome`); `apply_call_outcome` applies it with
  one consumer per aspect (`CONSUMERS`). Every dataclass is frozen, keyword-only and has **no defaults**: an aspect (or a
  field) added later is a TypeError in every producer until each says what it does there (`MODE_RULES` says it in
  words, for every mode and aspect), and a field no consumer reads yet is listed with the step that will
  (`NOT_YET_CONSUMED` in the structure test).

Steps 2–3 changed no behaviour (golden byte-identical: the conformance shapes in every mode, the HD known-target cells as
a unit and an integrated run, the oracle tests). Step 4b (G5) and 4c (G6) are the effects-only call's Termination and
Paths: a callee whose own text never returns refuses the run (as interpreted), one whose termination the text does not
prove and every one whose undefined behaviour is not analysed is named on the record (``callee_termination_assumed`` ·
``callee_ub_unanalysed`` and an assumption each).

What the structure does not promise — kept here so a reader does not take it for more:

* (producer purity — I4) a producer *judges*, it does not apply: no store, havoc mark, escape or activation table
  changes before `apply_call_outcome`. Three exceptions are caches or facts any later run would record alike: the
  points-to answers of an argument (``shared["argument_objects"]``), a harness buffer the argument names
  (``harness_buffers`` — `_Interp.array_object`), and possible undefined behaviour a known null pointer an argument
  dereferences on a path an unknown branch chose (`_Interp.pointee_target` → `_Interp.undefined`). A structure test
  holds every other producer effect to none on the conformance shapes.
* (judgement order — I2 c) a producer judges before the consumers apply, where the code before step 3 interleaved:
  a judgement that refuses (two units laying a storage object out differently, a null pointer an argument dereferences
  on the run's only path) now refuses before the call's state changes. The state is discarded either way (every catcher
  of `Unsupported` runs on a copy); what can differ: (a) which reason wins when two different refusals would both fire;
  (b) a storage signature registered before the refusal (only ever fail-closed: more later layout conflicts, never
  fewer); (c) the read marks an effects-only call adds (``_CALLEE_READS`` · ``_ANY_POINTER_READ``) are not added when it
  refuses — an operand that runs on some executions (`speculative`, undefined behaviour) merges its probe's reads, so
  an output's reason may read ``unwritten_output_…`` where it read ``initial_value_not_in_inputs`` (reason text only).
  No corpus case of any was found (the deep review's fuzzing and HD-wide runs: records and steps identical).
* (refusal heads — I7) `REFUSAL_CLASS` is read by a reason's head, the text before its first ``:``. The former rules
  matched ``unsequenced_side_effects`` · ``non_terminating_loop`` · ``constant_condition_loop_unfinished`` exactly and
  ``undefined_behavior:`` as a prefix; on every reason the code raises the head reading is the same (none of the first
  three is raised with a detail — an effects-only callee that never returns is ``non_terminating_loop:<callee>``, step
  4b, which propagates out of an interpreted caller as the bare reason does — and ``undefined_behavior`` never bare).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# (cycle) the oracle imports this module at its top: names of it are read inside functions only, never at import
from generators import c_source_oracle as cso

# ── layer 1: the static summary ─────────────────────────────────────────────────────────────────────────────────────

CLOSURE, STUB, UNKNOWN = "closure", "stub", "unknown"
# termination verdicts — RETURNS: proven (the joined paths returned; the harness returns from a stub; a callee text with
#   no loop, goto, recursion, jump or unknown code) · NEVER: proven not to return (an interpreted callee's
#   ``non_terminating_loop``; a callee text whose own body loops for ever — `cpc._termination_fact`) · MAY_NOT: the text
#   does not prove it (a loop, a goto, recursion, a jump, unknown code, a macro that loops) · ASSUMED: nothing said (unknown
#   code; a context read before the termination fact)
RETURNS, ASSUMED, MAY_NOT, NEVER = "returns", "assumed", "may_not", "never"
TERMINATION_VERDICTS = (RETURNS, ASSUMED, MAY_NOT, NEVER)
# the closure's ``termination`` (`cpc._closure_termination`) → a verdict and what it rests on
_CLOSURE_TERMINATION = {
    "returns": (RETURNS, "its text and every function and macro it reaches have no loop, goto, recursion, jump or "
                         "unknown code"),
    "never": (NEVER, "its own body loops for ever: a statement of it is a loop with no way out and no path returns"),
    "may_not": (MAY_NOT, "a loop, a goto, recursion, a jump or unknown code it reaches: its text does not prove it returns"),
}


@dataclass(frozen=True, kw_only=True, slots=True)
class CalleeSummary:
    """What a call to ``name`` may do, read from its project write closure (`cpc.function_write_closure` — one per build,
    R89) or from the row's sequence stub. ``kind``: `CLOSURE` · `STUB` · `UNKNOWN` (unknown code)."""
    name: str
    kind: str
    reads: frozenset | None         # names its body and what it reaches mention — None: anything (a hidden macro, unknown)
    writes: frozenset               # objects it may write by name, through any callee
    pointer_write: bool             # it (or what it reaches) writes through a pointer; a stub: through a pointer argument
    pointer_abs: frozenset | None   # where its pointer writes land (`pointer_flow` ``abs``) — None: not known
    pointer_params: tuple           # the parameters it writes through directly (``params``, in the flow's order)
    unknown_callees: tuple          # unknown code it reaches, sorted (the first names the havoc)
    reaches: frozenset              # functions it may call — itself too when some path calls it again
    return_type: str                # its one declared return type ("" when definitions differ or it is unknown)
    stub_pointer: bool              # a stub: the row may put a test-case value through one of its pointer arguments
    termination: str                # `TERMINATION_VERDICTS`
    termination_evidence: str

    def opaque_writes(self, interp) -> list[str]:
        """Written names that are no modeled scalar or array object of the caller's unit (a pointer, a struct with
        pointer members): they may be written *through* — to an object the closure cannot name. Sorted: the first
        names the havoc. (Per unit: the caller's tables say what is modeled.)"""
        return sorted(w for w in self.writes
                      if w not in interp.globals and w not in interp.arrays and not interp.plain_struct(w))

    def may_change(self, interp, obj, state, *, escaping=frozenset(), pointee=True) -> bool:
        """(J1) Could this call change the object an identifier ``obj`` names in ``interp``? ``pointee``: for a pointer
        parameter whose pointee the sequence set up, the question is about that pointee (``p->a``) unless the identifier
        only designates where a store lands (`check_sequencing`) — then about the pointer ``p`` itself."""
        found = interp.lookup(obj)
        if pointee and found is not None and found.get("pointee"):
            # (R40) ``p->a`` beside ``f(…)``: f may write the pointee through any pointer (p passed on, stored)
            if self.kind == STUB:
                return self.stub_pointer
            if self.kind == UNKNOWN or self.pointer_write or self.unknown_callees:
                return True
            # (review R40 C1) a write to a name that is no modeled object is a write through it — ``g_q[0].cnt = 5U``
            #   through a global pointer that may hold p (the same judgment as the call's own havoc)
            return bool(self.opaque_writes(interp))
        if self.kind != STUB and interp.volatile_register_operand(obj):
            # (R90 re-review 4 C-R4-4) the hardware may change a register while the callee runs — it may wait on one
            #   (a poll), or reach one the closure cannot name: beside any call but a sequence stub's, a register read is
            #   indeterminately sequenced with the call (C11 6.5.2.2p10). (G4, step 4a: the registers it may read)
            return True
        escaped = False
        if found is not None and not found.get("extern"):
            key = found.get("key", "")
            escaped = key in state.escaped or obj in escaping
            if key in interp.static_keys and (self.kind == UNKNOWN or self.unknown_callees
                                              or interp.function_name in self.reaches):
                return True  # the callee may re-enter this function (round 2 A)
            if not escaped:
                return False  # a parameter or local no pointer can reach
        elif obj not in interp.globals and obj not in interp.arrays \
                and obj not in (interp.scope.get("unresolved_globals") or {}):
            return False  # a constant, an enumerator, a type name
        if self.kind == UNKNOWN or self.unknown_callees:
            return True
        if obj in self.writes:
            return True
        pointer = self.pointer_write or self.opaque_writes(interp)
        reachable = escaped or obj in interp.arrays or obj in interp.address_taken or obj in escaping or (
            obj not in interp.globals and obj not in interp.arrays)
        return bool(pointer and reachable)

    def effectful(self, interp) -> bool:
        """(J3) Could the call change anything another call reads — a write, a pointer write, unknown code, or a static
        local in it or anything it reaches (`CalleeProvider.has_static_locals`)? Unknown → yes. A stub writes nothing but
        what its pointer arguments reach and runs nothing (R38) — asked of a stub only from step 4 on (G8: the
        unordered-site judgement still reads the stubbed callee's closure)."""
        if self.kind == UNKNOWN:
            return True
        if self.kind == STUB:
            return self.stub_pointer
        if self.writes or self.pointer_write or self.unknown_callees:
            return True
        provider = interp.world.provider if interp.world is not None else None
        has_statics = getattr(provider, "has_static_locals", None)
        if has_statics is None:
            return True
        return any(has_statics(f) for f in {self.name} | set(self.reaches))

    def inert(self, interp) -> bool:
        """(J2 · J6, R37 / R38) Evaluating the call changes nothing: a sequence stub that puts nothing through a pointer
        argument (its value is the row's; it writes no global or static). A closure is never inert here — even one that
        writes nothing may wait on a register (F6)."""
        return self.kind == STUB and not self.stub_pointer

    def may_read(self, root: str) -> bool:
        """(J9, backlog 2-c) May the call read the object ``root`` — a name its closure mentions, or anything when the
        closure cannot say (a macro that hides its text, unknown code)?"""
        return self.reads is None or root in self.reads

    def stub_hedge(self) -> bool:
        """(R38 / R64) May a sequence stub of this function put something through a pointer argument because of what its
        body does — it writes through a pointer or calls code the closure cannot see (`_Interp.stub_view` asks)?"""
        return self.kind == UNKNOWN or bool(self.pointer_write or self.unknown_callees)

    def volatile_reads(self, interp) -> frozenset | None:
        """The volatile union / bit-field objects (registers) the call may read — and so wait on: after a call not
        interpreted, the hardware may have changed them. None: any (F6, conservative — the closure's ``reads`` do not
        see a register the callee reaches through a pointer, ``WaitP(&FLW)``, or through a ``#define`` in its body).
        A sequence stub reads none (the harness replaces the body, nothing polls — R38). (Step 4: a closure with no loop,
        goto, recursion or unknown callee cannot wait for hardware.)"""
        if self.kind == STUB:
            return frozenset()
        return None


_UNKNOWN_SUMMARY = CalleeSummary(name="", kind=UNKNOWN, reads=None, writes=frozenset(), pointer_write=True,
                                 pointer_abs=None, pointer_params=(), unknown_callees=(), reaches=frozenset(),
                                 return_type="", stub_pointer=False, termination=ASSUMED,
                                 termination_evidence="unknown code: termination not proven")


def _from_closure(name: str, info: dict[str, Any]) -> CalleeSummary:
    pt = info.get("pointer_targets")
    found = pt.get("abs") if pt else None
    verdict, evidence = _CLOSURE_TERMINATION.get(info.get("termination") or "", (
        ASSUMED, "run as its write closure: termination not proven (the blanket assumption)"))
    return CalleeSummary(
        name=name, kind=CLOSURE,
        reads=frozenset(info.get("reads") or ()) if info.get("reads_complete") else None,
        writes=frozenset(info.get("writes") or ()),
        pointer_write=bool(info.get("pointer_write")),
        pointer_abs=frozenset(found) if found is not None else None,
        pointer_params=tuple(pt.get("params") or ()) if found is not None else (),
        unknown_callees=tuple(sorted(info.get("unknown_callees") or ())),
        reaches=frozenset(info.get("reaches") or ()),
        return_type=str(info.get("return_type") or ""),
        stub_pointer=False, termination=verdict, termination_evidence=evidence)


def closure_summary(interp, name: str) -> CalleeSummary | None:
    """The summary of ``name``'s project write closure as ``interp``'s build sees it (``scope["effects"]`` — one per
    build, R89), None when the closure has no function of that name. Cached per closure object (kept alive by the
    entry: an id is never reused while the cache holds it) — not an empty closure (a scope without effects gives each
    activation a fresh ``{}``: nothing to keep, and its ids would only fill the cache)."""
    closure = interp.closure
    if not closure:
        return None
    cache = interp.shared.setdefault("callee_summaries", {})
    key = (id(closure), name)
    hit = cache.get(key)
    if hit is not None and hit[0] is closure:
        return hit[1]
    info = closure.get(name)
    summary = _from_closure(name, info) if info is not None else None
    cache[key] = (closure, summary)
    return summary


def stub_summary(interp, name: str) -> CalleeSummary | None:
    """The summary of the row's sequence stub of ``name`` (`_Interp.stub_view` — it rests on the row and on the names in
    scope, so it is never cached), None when the row does not stub it."""
    view = interp.stub_view(name)
    if view is None:
        return None
    base = closure_summary(interp, name)   # a stub stands for a project function: its closure is there (`stub_view`)
    return CalleeSummary(name=name, kind=STUB, reads=frozenset(), writes=frozenset(), pointer_write=view["pointer"],
                         pointer_abs=None, pointer_params=(), unknown_callees=(), reaches=frozenset(),
                         return_type=base.return_type, stub_pointer=view["pointer"], termination=RETURNS,
                         termination_evidence="the harness replaces the body and returns (R38)")


def summary_for(interp, name: str) -> CalleeSummary | None:
    """What a call to ``name`` in ``interp`` may do: the row's stub, else the closure, else None (unknown code)."""
    stub = stub_summary(interp, name)
    return stub if stub is not None else closure_summary(interp, name)


def summary_or_unknown(interp, name: str) -> CalleeSummary:
    """`summary_for`, unknown code standing for None (it may do anything)."""
    return summary_for(interp, name) or _UNKNOWN_SUMMARY


# ── refusals: one table ─────────────────────────────────────────────────────────────────────────────────────────────

# The head of a refusal reason (before the first ``:``) → (its class, what ran out). ``program_ub`` / ``program_termination``
#   are about the program (the run has no defined result / no return state); ``budget`` is the model's step, iteration,
#   path or search budget; anything else is ``model`` (the model gave up). ``run``: the run's own budget ran out (in a
#   loop with a constant condition it becomes ``constant_condition_loop_unfinished`` — still the run's budget); ``loop`` /
#   ``paths``: a loop's iterations / the live paths; ``search``: the polling way-out search's fixed cap (a property of
#   the loop, not of how far the run got).
REFUSAL_CLASS: dict[str, tuple[str, str]] = {
    "undefined_behavior": ("program_ub", ""),
    "unsequenced_side_effects": ("program_ub", ""),
    "non_terminating_loop": ("program_termination", ""),
    "constant_condition_loop_unfinished": ("program_termination", "run"),
    "execution_budget": ("budget", "run"),
    "loop_iteration_budget": ("budget", "loop"),
    "path_budget": ("budget", "paths"),
    "polling_loop_exit_search_budget": ("budget", "search"),
}
REFUSAL_CLASSES = ("program_ub", "program_termination", "budget", "model")
# (G11, step 4e) a model refusal a callee still propagates: the hidden call of ``(Inc()) + 1U`` (review W-R4-1) — its
#   closure holds it since cpc `_cast_hidden_call`
REFUSING_MODEL_IN_CALLEE = frozenset({"cast_parse_of_parenthesized_expression"})


def _refusal_row(reason: str) -> tuple[str, str]:
    return REFUSAL_CLASS.get(str(reason).split(":", 1)[0], ("model", ""))


def refusal_class(reason: str) -> str:
    """``program_ub`` · ``program_termination`` · ``budget`` · ``model`` (`REFUSAL_CLASS`)."""
    return _refusal_row(reason)[0]


def refuses_in_callee(reason: str) -> bool:
    """(`_World.inline`) A callee's refusal the integrated run inherits — about the program, not the model: undefined
    behaviour (6.5p2 unsequenced side effects too) or a path that never returns (no return state to observe). Any other
    refusal makes the call fall back to its write closure."""
    return refusal_class(reason) in ("program_ub", "program_termination") or reason in REFUSING_MODEL_IN_CALLEE


def iteration_budget(reason: str) -> bool:
    """(`_Interp.loop` · `_Interp.polling_search`) A budget the run spent iterating — steps, a loop's iterations, the
    live paths — not the polling search's fixed cap. A loop with a constant condition out of it with no path out yet may
    never end (C11 6.8.5p6): ``constant_condition_loop_unfinished``."""
    cls, spent = _refusal_row(reason)
    return cls == "budget" and spent in ("run", "loop", "paths")


def run_budget(reason: str) -> bool:
    """(`integration_oracle._refused_for_budget`) The run's own step budget ran out — in a constant-condition loop or
    anywhere: the sub-cases after it would spend it alike."""
    return _refusal_row(reason)[1] == "run"


# ── layer 2: the outcome of one call ────────────────────────────────────────────────────────────────────────────────

MODES = ("I", "Ew", "E0", "S", "U")   # interpreted · effects only in a world / without one · sequence stub · unknown code


@dataclass(frozen=True, kw_only=True, slots=True)
class Reads:
    names: frozenset | None         # what the call may read of the caller's objects — None: anything
    through_pointer: bool           # … and through a pointer
    upward_exposed: frozenset       # (I) keys the callee read while unset — step 5 (the joined state carries them now)
    marks: tuple                    # `_State.initial_reads` marks the call adds (`_read_on_some_path` reads them)


@dataclass(frozen=True, kw_only=True, slots=True)
class Writes:
    replace_state: Any              # (I) the callee's final paths joined — the caller's state from here; None
    reentry: tuple                  # ((scope, reason), …): static locals re-entered code may change — ``stack``: every
    #                                 activation on the stack (`_World.inline` found recursion), ``self``: `havoc_statics`
    everything: str                 # unknown code: every object a callee can reach (`havoc_everything`) — its reason; ""
    locals_too: bool                # with ``everything``: the text expands here (a maybe-macro) — locals too
    named: tuple                    # ((object, reason), …) written by name, in that order
    pointer_reason: str             # a write through a pointer — its reason; "" none
    pointer_targets: frozenset | None   # where it may land (`havoc_objects`); None: anything a pointer may reach
    pointer_direct: frozenset       # what it also writes by name (a register reached otherwise is reached by offset)
    through_pointer_write: bool     # the callee writes through a pointer itself (not only a stub it reaches)


@dataclass(frozen=True, kw_only=True, slots=True)
class Registers:
    havoc: frozenset | None         # registers (volatile union / bit-field objects) unknown after the call; None: every one
    havoc_reason: str
    havoc_callee: str               # (I-R5-4) the callee not interpreted the register mark names too (`name_callee_…`); ""
    polls: tuple                    # ((root, member path), …) register reads the call adds to the caller's poll log
    #                                 beyond what a run it made logged itself (`RunLog`, `absorb_run`) — step 4 (G4)
    polling_assumed: tuple          # (I) polling loops the callee assumed to end
    volatile_reads: frozenset       # (I) registers it read as harness memory
    storage_used: frozenset         # (I) storage objects it read, wrote or observed
    narrow: tuple                   # (I) ((root, frozenset(spans)), …) union members narrower than their union it stored
    unspecified: frozenset          # (I) objects it read across bytes such a store left unspecified


@dataclass(frozen=True, kw_only=True, slots=True)
class Return:
    value: Any                      # the call's `_Val`
    declared_type: str              # the callee's declared return type ("" unknown)
    void: bool


@dataclass(frozen=True, kw_only=True, slots=True)
class Termination:
    verdict: str                    # `TERMINATION_VERDICTS` — whether this call returns
    evidence: str                   # what the verdict rests on (NEVER: the refusal reason)
    assumed: frozenset              # (G5) callees whose return the call's value assumes, named on the record — E: this
    #                                 one when its text does not prove it; I: those of the joined run


@dataclass(frozen=True, kw_only=True, slots=True)
class Paths:
    joined: bool                    # (I) the callee's final paths were joined into one state — counted ``inlined``
    refusal: str                    # the call leaves no state to go on from: the evaluation is refused with it; ""
    ub_unanalysed: frozenset        # (G6) callees whose undefined behaviour the run did not judge, named on the record —
    #                                 E: this one (its body does not run); I: those of the joined run
    fallback: str                   # why a world ran it as effects only — counted ``effects_only``; ""


@dataclass(frozen=True, kw_only=True, slots=True)
class Provenance:
    stubs_entered: frozenset        # (S) a stub the call entered: the record rests on it even when the call refuses (R38)
    stubs_used: frozenset           # sequence stubs the value rests on (applied when the call completes)
    linked_reads: frozenset         # const values read from another unit's definition
    assumed_undefined: frozenset    # #if verdicts it rests on (its unit's, the definition binding's)
    static_keys: frozenset          # (I) static locals of the activation — every later re-entry havoc names them


@dataclass(frozen=True, kw_only=True, slots=True)
class CallOutcome:
    name: str
    mode: str                       # `MODES`
    paths: Paths
    termination: Termination
    reads: Reads
    registers: Registers
    writes: Writes
    provenance: Provenance
    ret: Return


# the aspects, in the order `apply_call_outcome` applies them
ASPECTS = ("paths", "termination", "reads", "registers", "writes", "provenance", "ret")

NO_READS = Reads(names=frozenset(), through_pointer=False, upward_exposed=frozenset(), marks=())
NO_WRITES = Writes(replace_state=None, reentry=(), everything="", locals_too=False, named=(), pointer_reason="",
                   pointer_targets=None, pointer_direct=frozenset(), through_pointer_write=False)
NO_REGISTERS = Registers(havoc=frozenset(), havoc_reason="", havoc_callee="", polls=(), polling_assumed=(),
                         volatile_reads=frozenset(), storage_used=frozenset(), narrow=(), unspecified=frozenset())
NO_PROVENANCE = Provenance(stubs_entered=frozenset(), stubs_used=frozenset(), linked_reads=frozenset(),
                           assumed_undefined=frozenset(), static_keys=frozenset())


# What `_World.inline` gives back — it never changes the caller (activation or state): the consumers do.
@dataclass(frozen=True, kw_only=True, slots=True)
class RunLog:
    """What the callee's run spent and read — the caller activation's, whatever the outcome (`absorb_run`): its steps
    (the run's budget, R36's search budget) and the register reads it made, in order (aligned lists — a loop body or
    condition that read its flag through the callee read it, `loop_iterations`)."""
    steps: int
    polls: tuple
    poll_members: tuple


@dataclass(frozen=True, kw_only=True, slots=True)
class Result:
    """The callee ran: its final paths joined (`_World.join`), its parameters and automatic locals ended."""
    name: str
    log: RunLog
    sub: Any                        # the finished activation (its tables)
    merged: Any                     # the joined `_State`
    returned: Any                   # the joined return value (`_Val`)
    assumed_undefined: frozenset    # its #if verdicts, its unit's and the definition binding's (R17)


@dataclass(frozen=True, kw_only=True, slots=True)
class Failure:
    """The world did not interpret the callee — its write closure stands for it (`effects_outcome`)."""
    name: str
    reason: str
    log: RunLog | None              # None: nothing ran (cached failure, recursion, depth, no definition, a collision)
    reentered: bool                 # recursion: the call re-enters a running activation (its static locals may change)


@dataclass(frozen=True, kw_only=True, slots=True)
class Refused:
    """The callee's run proved the program has no defined result or never returns there (`refuses_in_callee`)."""
    name: str
    reason: str
    log: RunLog


def absorb_run(caller, log: RunLog | None) -> None:
    """The caller activation takes what a callee's run spent and read (its steps, its register reads) — whatever came
    of the call: the reads happened before any refusal, and the steps are the run's budget."""
    if log is None:
        return
    caller.steps = log.steps
    caller.volatile_polls.extend(log.polls)
    caller.volatile_poll_members.extend(log.poll_members)


# ── the producers ───────────────────────────────────────────────────────────────────────────────────────────────────

def _returned(summary: CalleeSummary | None, value) -> Return:
    declared = summary.return_type if summary is not None else ""
    return Return(value=value, declared_type=declared, void=declared.strip() == "void")


def _refused(name: str, mode: str, reason: str, paths: Paths, provenance: Provenance) -> CallOutcome:
    """An outcome that refuses the evaluation — after its paths' disclosure (`_consume_paths`) and with what the call
    entered (`Provenance.stubs_entered` — `apply_call_outcome` applies it whatever happens)."""
    return CallOutcome(name=name, mode=mode, paths=Paths(joined=False, refusal=reason, ub_unanalysed=paths.ub_unanalysed,
                                                         fallback=paths.fallback),
                       termination=Termination(verdict=ASSUMED, evidence="refused: " + reason, assumed=frozenset()),
                       reads=NO_READS, registers=NO_REGISTERS, writes=NO_WRITES, provenance=provenance,
                       ret=_returned(None, None))


def interpreted_outcome(interp, state, summary: CalleeSummary, done) -> CallOutcome:
    """(I) The world ran the callee (`Result`) — or its run refused the evaluation (`Refused`)."""
    name = done.name
    if isinstance(done, Refused):
        verdict = NEVER if refusal_class(done.reason) == "program_termination" else ASSUMED
        return CallOutcome(name=name, mode="I",
                           paths=Paths(joined=False, refusal=done.reason, ub_unanalysed=frozenset(), fallback=""),
                           termination=Termination(verdict=verdict, evidence=done.reason, assumed=frozenset()),
                           reads=NO_READS, registers=NO_REGISTERS, writes=NO_WRITES, provenance=NO_PROVENANCE,
                           ret=_returned(summary, None))
    sub, merged = done.sub, done.merged
    return CallOutcome(
        name=name, mode="I",
        # (G6) the callee's body was judged — what it ran as effects only was not, and the record names it
        paths=Paths(joined=True, refusal="", ub_unanalysed=frozenset(sub.callee_ub_unanalysed), fallback=""),
        termination=Termination(verdict=RETURNS, evidence="every joined path of the callee returned",
                                assumed=frozenset(sub.callee_termination_assumed)),
        # (what the callee read unset is in the joined state's ``initial_reads`` — `Writes.replace_state`)
        reads=NO_READS,
        registers=Registers(havoc=frozenset(), havoc_reason="", havoc_callee="", polls=(),
                            polling_assumed=tuple(sub.polling_assumed),
                            volatile_reads=frozenset(sub.storage_volatile_reads),
                            storage_used=frozenset(sub.storage_used),
                            narrow=tuple((root, frozenset(spans)) for root, spans in sub.storage_narrow.items()),
                            unspecified=frozenset(sub.storage_unspecified)),
        writes=Writes(replace_state=merged, reentry=(), everything="", locals_too=False, named=(), pointer_reason="",
                      pointer_targets=None, pointer_direct=frozenset(), through_pointer_write=False),
        provenance=Provenance(stubs_entered=frozenset(), stubs_used=frozenset(sub.stubs_used),
                              linked_reads=frozenset(sub.linked_reads), assumed_undefined=done.assumed_undefined,
                              static_keys=frozenset(sub.static_keys)),
        ret=_returned(summary, done.returned))


def effects_termination(name: str, summary: CalleeSummary) -> Termination:
    """(G5, step 4b) Whether an effects-only call returns, from its closure (`cpc._closure_termination`): NEVER refuses
    the run as an interpreted call does (``non_terminating_loop`` — the same class, `REFUSAL_CLASS`); RETURNS needs no
    word; MAY_NOT / ASSUMED keep the value and name the callee (``callee_termination_assumed``)."""
    if summary.termination == NEVER:
        return Termination(verdict=NEVER, evidence="non_terminating_loop:" + name, assumed=frozenset())
    assumed = frozenset() if summary.termination == RETURNS else frozenset({name})
    return Termination(verdict=summary.termination, evidence=summary.termination_evidence, assumed=assumed)


def effects_ub_unanalysed(name: str, summary: CalleeSummary) -> frozenset:
    """(G6, step 4c) An effects-only call's body does not run: undefined behaviour in it is not judged — the record names
    the callee (``callee_ub_unanalysed``); the values stand (a value derived here holds for runs without it)."""
    return frozenset({name})


def effects_outcome(interp, state, name: str, summary: CalleeSummary, arg_nodes, raw, fallback: Failure | None,
                    why: str) -> CallOutcome:
    """(Ew · E0) The callee's write closure stands for it: it may read what the closure names (and through a pointer),
    wait on any register, write what the closure says — by name, through a pointer (`callee_targets`), through a stub
    it reaches — re-enter static locals, and returns the row's ``F() return`` value when one is set; whether it returns
    is its text's (`effects_termination`), its undefined behaviour is not judged (`effects_ub_unanalysed`).
    ``fallback``: the world's `Failure`, or None — then ``why`` the world did not try (every effects-only call in a world
    is counted)."""
    world = interp.world
    mode = "Ew" if world is not None else "E0"
    paths = Paths(joined=False, refusal="", ub_unanalysed=effects_ub_unanalysed(name, summary),
                  fallback=((fallback.reason if fallback is not None else why) or "not_attempted")
                  if world is not None else "")
    try:
        reentry = []
        if fallback is not None and fallback.reentered:
            # the callee re-enters a running activation: its static locals may change (the rest below)
            reentry.append(("stack", "recursion_through:" + name))
        if world is not None:
            # (R16 review C2) a callee run as effects only may run any function it reaches — among them one this
            # evaluation interpreted (its static locals are in the store) or one on the call stack
            if summary.unknown_callees or (set(summary.reaches) | {name}) & world.interpreted_names():
                reentry.append(("self", f"callee_not_interpreted:{name}"))
        elif interp.function_name and interp.function_name in summary.reaches:
            reentry.append(("self", f"recursion_through:{name}"))   # the callee may re-enter this function
        regs = summary.volatile_reads(interp)
        named: tuple = ()
        everything, pointer = "", ("", None, frozenset(), False)
        opaque = summary.opaque_writes(interp)
        if summary.unknown_callees:
            everything = f"callee_effects_unknown:{name}:{summary.unknown_callees[0]}"
        else:
            named = tuple((w, f"written_by_callee:{name}:{w}") for w in sorted(summary.writes))
            if summary.pointer_write or opaque:
                why_ptr = "pointer_write" if summary.pointer_write else "writes_through:" + opaque[0]
                targets = interp.callee_targets(name, summary, arg_nodes, raw, state)
                pointer = (f"callee_pointer_write:{name}:{why_ptr}",
                           frozenset(targets) if targets is not None else None,
                           frozenset(summary.writes), summary.pointer_write)
            elif summary.pointer_abs is None:
                # (review R64 I-4) a callee it calls that this run stubs may write through what it is passed, whatever
                #   that callee's body does — named by the flow, or (round 2 W-2) when the flow did not run or could not
                #   name the targets, any function it reaches this run stubs with pointer parameters
                stubbed = sorted(g for g in summary.reaches if (v := interp.stub_view(g)) is not None and v["pointer"])
                if stubbed:
                    pointer = (f"callee_stub_write:{name}:{stubbed[0]}", None, frozenset(), True)
            else:
                stub_writes = frozenset(t for t in summary.pointer_abs if t.startswith("?SW:"))
                if stub_writes:
                    pointer = (f"callee_stub_write:{name}", stub_writes, frozenset(), True)
        value, stubbed_return = interp.stub_return(name, summary.return_type)
    except cso.Unsupported as exc:
        # a judgement that refuses (a storage layout two units disagree on, a null pointer an argument dereferences):
        #   the call's own disclosure stands, then the refusal (as when it raised half-way through the effects)
        return _refused(name, mode, str(exc), paths, NO_PROVENANCE)
    return CallOutcome(
        name=name, mode=mode, paths=paths,
        termination=effects_termination(name, summary),
        # (backlog 2-c review round 2) it may read what its closure names, and through a pointer
        reads=Reads(names=summary.reads, through_pointer=True, upward_exposed=frozenset(),
                    marks=(cso._CALLEE_READS + name, cso._ANY_POINTER_READ)),
        # (R90 re-review 3 C-R3-1, re-review 4 C-R4-1) it may wait on a register flag: under the model (a register is
        #   memory) such a callee never returns, under the polling assumption the flag changed — neither leaves the
        #   register as the row set it. Before the writes: a write names its own reason where it reaches the same one
        registers=Registers(havoc=regs, havoc_reason=cso._CALLEE_REGISTERS + name, havoc_callee=name, polls=(),
                            polling_assumed=(), volatile_reads=frozenset(), storage_used=frozenset(), narrow=(),
                            unspecified=frozenset()),
        writes=Writes(replace_state=None, reentry=tuple(reentry), everything=everything, locals_too=False, named=named,
                      pointer_reason=pointer[0], pointer_targets=pointer[1], pointer_direct=pointer[2],
                      through_pointer_write=pointer[3]),
        provenance=Provenance(stubs_entered=frozenset(), stubs_used=frozenset({name}) if stubbed_return else frozenset(),
                              linked_reads=frozenset(), assumed_undefined=frozenset(), static_keys=frozenset()),
        ret=_returned(summary, value))


def stub_outcome(interp, state, name: str, summary: CalleeSummary, view, arg_nodes, raw) -> CallOutcome:
    """(S, R38) The row stubs ``name``: the harness replaces its body — nothing it would write to a global or a static
    happens and nothing it calls runs. It may put a test-case value through a pointer argument (the row sets
    ``F() p[0]`` — R23): (R64) what those arguments may point to, and what that reaches, is unknown (`stub_targets`).
    The record rests on the stub even when its value is not usable — and when the call refuses (I1)."""
    paths = Paths(joined=False, refusal="", ub_unanalysed=frozenset(), fallback="")
    entered = Provenance(stubs_entered=frozenset({name}), stubs_used=frozenset(), linked_reads=frozenset(),
                         assumed_undefined=frozenset(), static_keys=frozenset())
    try:
        pointer = ("", None)
        if view["pointer"]:
            targets = interp.stub_targets(name, arg_nodes, raw, state)
            pointer = ("stub_pointer_argument:" + name, frozenset(targets) if targets is not None else None)
        value, _stubbed = interp.stub_return(name, summary.return_type)
    except cso.Unsupported as exc:
        return _refused(name, "S", str(exc), paths, entered)
    return CallOutcome(
        name=name, mode="S", paths=paths,
        termination=Termination(verdict=RETURNS, evidence="the harness replaces the body and returns (R38)",
                                assumed=frozenset()),
        reads=NO_READS, registers=NO_REGISTERS,
        writes=Writes(replace_state=None, reentry=(), everything="", locals_too=False, named=(),
                      pointer_reason=pointer[0], pointer_targets=pointer[1], pointer_direct=frozenset(),
                      through_pointer_write=True),
        provenance=entered, ret=_returned(summary, value))


def unknown_outcome(interp, name: str, locals_too: bool) -> CallOutcome:
    """(U) Unknown code — a name with no project definition, a function pointer, a parameter or local of the name, a
    name a missing include may make a macro (``locals_too``: it may write a parameter or local in place): it may read and
    write anything, every register included (`havoc_everything`), and its value is unknown. What it does is the blanket
    assumption's (`ASSUMPTIONS`) — no name to put on the record."""
    return CallOutcome(
        name=name, mode="U",
        paths=Paths(joined=False, refusal="", ub_unanalysed=frozenset(), fallback=""),
        termination=Termination(verdict=ASSUMED, evidence="unknown code: termination not proven", assumed=frozenset()),
        reads=Reads(names=None, through_pointer=True, upward_exposed=frozenset(), marks=(cso._UNPLACED_READ,)),
        registers=NO_REGISTERS,
        writes=Writes(replace_state=None, reentry=(), everything="unknown_callee:" + name, locals_too=locals_too,
                      named=(), pointer_reason="", pointer_targets=None, pointer_direct=frozenset(),
                      through_pointer_write=False),
        provenance=NO_PROVENANCE,
        ret=Return(value=cso._Val(cso.Unknown("call_return_value:" + name), None), declared_type="", void=False))


# ── the consumers: one per aspect ───────────────────────────────────────────────────────────────────────────────────
# A consumer never ticks (`_Interp.tick`): the steps are the run's — what a run spent comes in by `absorb_run`.

def _consume_paths(interp, state, name, paths: Paths) -> None:
    """Disclose (the world's counts; the callees whose undefined behaviour the run did not judge — G6), then refuse when
    the call leaves no state to go on from."""
    world = interp.world
    if paths.joined:
        world.inlined[name] = world.inlined.get(name, 0) + 1
    if paths.fallback:
        world.effects_only[name] = world.effects_only.get(name, 0) + 1
    interp.callee_ub_unanalysed |= paths.ub_unanalysed
    if paths.refusal:
        raise cso.Unsupported(paths.refusal)


def _consume_termination(interp, state, name, termination: Termination) -> None:
    """NEVER leaves no return state: the evaluation is refused with the evidence (a ``program_termination`` reason).
    Otherwise the callees whose return the value assumes are named on the record (G5)."""
    if termination.verdict == NEVER:
        raise cso.Unsupported(termination.evidence or "non_terminating_loop")
    if termination.verdict not in TERMINATION_VERDICTS:
        raise ValueError(f"termination verdict {termination.verdict!r}")
    interp.callee_termination_assumed |= termination.assumed


def _consume_reads(interp, state, name, reads: Reads) -> None:
    state.initial_reads.update(reads.marks)


def name_callee_on_register_mark(state, callee: str) -> None:
    """(R90 re-review 5 I-R5-4) Every callee the run did not interpret is named on the register mark
    (``register_read_by_callee_not_interpreted:A+B``) — the first alone named one where several left the registers
    unknown. A mark another cause set (a write through a pointer) keeps its reason; so does one that names it already."""
    mark = state.havoc_bases.get(cso._VOLATILE_STORAGE)
    prefix = cso._CALLEE_REGISTERS
    if mark is not None and mark.startswith(prefix) and callee not in mark[len(prefix):].split("+"):
        state.havoc_bases[cso._VOLATILE_STORAGE] = mark + "+" + callee


def _consume_registers(interp, state, name, registers: Registers) -> None:
    if registers.havoc is None:
        interp.havoc_volatile_storage(state, registers.havoc_reason)   # the mark: the first cause's reason
        if registers.havoc_callee:
            name_callee_on_register_mark(state, registers.havoc_callee)
    elif registers.havoc:
        raise NotImplementedError("a named register havoc has no producer before step 4 (G4)")
    for root, path in registers.polls:   # aligned lists (`read_storage`)
        interp.volatile_polls.append(root)
        interp.volatile_poll_members.append((root, path))
    interp.storage_used |= registers.storage_used
    interp.storage_volatile_reads |= registers.volatile_reads
    interp.polling_assumed.extend(registers.polling_assumed)
    for root, spans in registers.narrow:
        interp.storage_narrow.setdefault(root, set()).update(spans)
    interp.storage_unspecified |= registers.unspecified


def _consume_writes(interp, state, name, writes: Writes) -> None:
    for scope, reason in writes.reentry:
        if scope == "stack":
            for it in interp.world.stack:
                it.havoc_statics(state, reason)
        else:
            interp.havoc_statics(state, reason)
    if writes.replace_state is not None:
        # (R90 review C1) the joined state is every callee path: the call chose no path of the caller's
        ret, selectors = state.ret, list(state.selectors)
        for slot in cso._State.__slots__:
            setattr(state, slot, getattr(writes.replace_state, slot))
        state.mode, state.ret, state.selectors = "normal", ret, selectors
    if writes.everything:
        interp.havoc_everything(state, writes.everything, locals_too=writes.locals_too)
    for obj, reason in writes.named:
        interp.havoc_base(state, obj, reason)
    if writes.pointer_reason:
        interp.havoc_objects(state, writes.pointer_targets, writes.pointer_reason, direct=writes.pointer_direct,
                             through_pointer=writes.through_pointer_write)


def _consume_provenance(interp, state, name, provenance: Provenance, completed: bool) -> None:
    """What the record rests on: a stub the call entered whatever came of it (R38 — `stubbed_call` recorded it first);
    the rest only once the call completed (its value, its joined run)."""
    interp.stubs_used |= provenance.stubs_entered
    if not completed:
        return
    interp.stubs_used |= provenance.stubs_used
    interp.linked_reads |= provenance.linked_reads
    interp.assumed_undefined |= provenance.assumed_undefined
    if provenance.static_keys:
        interp.world.static_keys |= provenance.static_keys


def _consume_ret(interp, state, name, ret: Return):
    return ret.value


CONSUMERS = {"paths": _consume_paths, "termination": _consume_termination, "reads": _consume_reads,
             "registers": _consume_registers, "writes": _consume_writes, "provenance": _consume_provenance,
             "ret": _consume_ret}


def apply_call_outcome(interp, state, outcome: CallOutcome):
    """Apply one call's outcome to the calling activation ``interp`` and its path ``state``; the call's value.

    The order is the one the producers kept before (`_Interp.call`): paths refusal → termination → writes re-entry →
    reads → registers → writes → paths disclosure → provenance → return value — registers before writes, so a write
    names its own reason where it reaches the same register. Each aspect has one consumer, called once, so two phases
    meet: the paths consumer discloses (the world's ``inlined`` / ``effects_only`` counts, G6's names) right before it
    refuses — no consumer reads those, and an effects-only call that refused half-way had counted itself — and the writes
    consumer re-enters static locals right before it writes — the reads (``initial_reads`` marks) and the register havoc
    (`.@` bytes of a volatile root, the ``@storage:volatile`` mark) touch no static local, and `storage_base` never
    meets a static's ``@`` base. Provenance is applied whatever happens: a stub the call entered stays on the record (I1);
    the rest only when the call completed."""
    name = outcome.name
    completed = False
    try:
        _consume_paths(interp, state, name, outcome.paths)
        _consume_termination(interp, state, name, outcome.termination)
        _consume_reads(interp, state, name, outcome.reads)
        _consume_registers(interp, state, name, outcome.registers)
        _consume_writes(interp, state, name, outcome.writes)
        completed = True
    finally:
        _consume_provenance(interp, state, name, outcome.provenance, completed)
    return _consume_ret(interp, state, name, outcome.ret)


# ── what each mode does, aspect by aspect ───────────────────────────────────────────────────────────────────────────
# A rule name with what it means; ``n/a:`` — the mode leaves the aspect empty by construction (why). Total over
#   MODES × ASPECTS (`tests/unit/test_callee_contract_structure.py`); every other cell is met by a conformance shape.
MODE_RULES: dict[tuple[str, str], str] = {
    ("I", "paths"): "joined: the callee's final paths join into one state (counted inlined); a program refusal "
                    "(undefined behaviour, a path that never returns) refuses the evaluation; what the run did not "
                    "judge (its effects-only callees, G6) is named",
    ("I", "termination"): "returns: every joined path returned; the callees the run assumed to return are named (G5)",
    ("I", "reads"): "n/a: what the callee read unset is in the joined state's initial_reads (Writes.replace_state) — "
                    "step 5 (read_set) fills upward_exposed",
    ("I", "registers"): "callee_tables: storage used, registers read, polling loops assumed, narrow stores — the poll "
                        "log and the steps are the run's (absorb_run)",
    ("I", "writes"): "replace_state: the joined state becomes the caller's (its return value and path selectors kept)",
    ("I", "provenance"): "callee_tables: stubs used, linked reads, #if verdicts (its unit's, the binding's), statics",
    ("I", "ret"): "joined_value: the value every final path returned, else unknown (_World.join)",
    ("Ew", "paths"): "fallback: counted effects_only (why: the world's failure, or the call was not attempted — an "
                     "unordered site, arguments not evaluated, a stub return input); its undefined behaviour is not "
                     "judged — named (G6)",
    ("Ew", "termination"): "closure_text: never returns → refused non_terminating_loop:<callee>; not proven → the value "
                           "stands and the callee is named (G5); proven → nothing to say. Known difference (R95 review "
                           "round 3): an endless loop holding a name no file read defines (it may be a macro that "
                           "leaves) is not proven here, while the interpreted path's _endless refuses it — no wrong "
                           "value either way",
    ("Ew", "reads"): "closure_reads: what its closure names, and through any pointer (_CALLEE_READS, _ANY_POINTER_READ)",
    ("Ew", "registers"): "havoc_all_volatile: it may wait on any register (F6 — volatile_reads None); the mark names "
                         "every such callee (I-R5-4)",
    ("Ew", "writes"): "write_closure: re-entered statics (recursion on the stack, an interpreted function it reaches), "
                      "named writes, through a pointer (callee_targets), a stub it reaches; unknown code: everything",
    ("Ew", "provenance"): "stub_return: the row's F() return value where F is not stubbable here",
    ("Ew", "ret"): "stub_return: the row's F() return value in F's declared type, else unknown",
    ("E0", "paths"): "ub_unanalysed: no world — nothing joined, nothing counted; its undefined behaviour is not judged — "
                     "named (G6)",
    ("E0", "termination"): "closure_text: as Ew",
    ("E0", "reads"): "closure_reads: as Ew",
    ("E0", "registers"): "havoc_all_volatile: as Ew",
    ("E0", "writes"): "write_closure: as Ew — re-entry only when it reaches the function under test",
    ("E0", "provenance"): "stub_return: as Ew",
    ("E0", "ret"): "stub_return: as Ew",
    ("S", "paths"): "n/a: the body does not run — no paths, nothing counted, nothing to judge",
    ("S", "termination"): "returns: the harness returns",
    ("S", "reads"): "n/a: the body does not run — a stub reads nothing",
    ("S", "registers"): "n/a: nothing polls — a register keeps what the row set (R38)",
    ("S", "writes"): "pointer_arguments: what its pointer arguments reach (stub_targets), when it may put a value "
                     "through one (R64); no global or static",
    ("S", "provenance"): "stubs_entered: the record rests on the stub — even when the call refuses (I1)",
    ("S", "ret"): "stub_return: the row's F() return value in F's declared type, else unknown",
    ("U", "paths"): "n/a: unknown code — nothing joined, nothing counted; not named on the record (deferred: naming a "
                    "prototype-only callee or a function pointer — R95 review W2); the blanket assumption covers it",
    ("U", "termination"): "assumed: the blanket assumption (not named — deferred, as paths)",
    ("U", "reads"): "anything: an unplaced read (_UNPLACED_READ)",
    ("U", "registers"): "n/a: Writes.everything covers every object, registers included",
    ("U", "writes"): "everything: havoc_everything (a maybe-macro: locals too)",
    ("U", "provenance"): "n/a: unknown code rests on nothing a record names",
    ("U", "ret"): "unknown: call_return_value",
}
