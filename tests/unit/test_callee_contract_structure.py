"""Callee summary contract — steps 2–4: the structure that keeps a new aspect from being missed in some mode.

`generators.callee_contract` says what a call does once: a static `CalleeSummary` (the judgement points ask its
predicates) and a per-call `CallOutcome` (four producers make one, `apply_call_outcome` applies it with one consumer per
aspect). These tests hold the structure, not modelling choices (the conformance harness,
`test_callee_contract_conformance.py`, holds the relations between modes):

1. every contract dataclass is frozen, keyword-only and has no defaults — a new field is a TypeError in every producer;
2. one consumer per aspect, each called once by `apply_call_outcome`, in the documented order, none ticking the budget —
   and each consumer reads every field of its aspect but those `NOT_YET_CONSUMED` names with the step that will;
3. `MODE_RULES` is total over modes × aspects;
4. the conformance shapes meet every rule that is not ``n/a`` (and an ``n/a`` cell is empty in every shape);
5. no closure field is read by string key outside the contract's owners, in any form (subscript, ``.get``, ``in``,
   ``itemgetter``, a tuple of keys) — and no judgement point reads a `CalleeSummary` field instead of asking a predicate
   (fixed allow-lists, each entry with why);
6. what the consumers set on an activation or the world is put back by a hypothetical probe (or exempt, with why) —
   and `_World.inline` changes neither the caller activation nor its state; a producer changes nothing either (I4);
7. one refusal table: each site's former rule is reproduced exactly (step 3 changes no behaviour);
8. a producer's refusal (`_refused`) counts and discloses, then refuses — and a stub the call entered stays on the
   record whichever way the call refuses (W1 · I1).
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import re
import tempfile
import types
from pathlib import Path

import pytest

from generators import c_source_oracle as cso
from generators import callee_contract as cc
from tests.unit._source_probe import source_of

ROOT = Path(__file__).resolve().parents[2]

# ── 1. frozen, keyword-only, no defaults ────────────────────────────────────────────────────────────────────────────

CONTRACT_DATACLASSES = ("CalleeSummary", "Reads", "Writes", "Registers", "Return", "Termination", "Paths",
                        "Provenance", "CallOutcome", "RunLog", "Result", "Failure", "Refused")


def test_every_contract_dataclass_is_frozen_keyword_only_without_defaults():
    found = sorted(n for n, v in vars(cc).items()
                   if inspect.isclass(v) and dataclasses.is_dataclass(v) and v.__module__ == cc.__name__)
    assert found == sorted(CONTRACT_DATACLASSES)
    for name in CONTRACT_DATACLASSES:
        cls = getattr(cc, name)
        assert cls.__dataclass_params__.frozen, name
        for f in dataclasses.fields(cls):
            assert f.kw_only, (name, f.name)
            assert f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING, (name, f.name)


def _full_outcome():
    return dict(name="f", mode="U",
                paths=cc.Paths(joined=False, refusal="", ub_unanalysed=frozenset(), fallback=""),
                termination=cc.Termination(verdict=cc.ASSUMED, evidence="", assumed=frozenset()), reads=cc.NO_READS,
                registers=cc.NO_REGISTERS, writes=cc.NO_WRITES, provenance=cc.NO_PROVENANCE,
                ret=cc.Return(value=None, declared_type="", void=False))


def test_an_outcome_missing_an_aspect_is_a_type_error():
    full = _full_outcome()
    cc.CallOutcome(**full)
    for aspect in cc.ASPECTS:
        with pytest.raises(TypeError):
            cc.CallOutcome(**{k: v for k, v in full.items() if k != aspect})
    with pytest.raises(TypeError):
        cc.CallOutcome("f", "U", *[full[a] for a in cc.ASPECTS])   # keyword-only


# ── 2. one consumer per aspect, called once, in order, reading every field ─────────────────────────────────────────

def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


def _function(path: Path, qualname: str) -> ast.AST:
    nodes = _tree(path).body
    parts = qualname.split(".")
    for i, part in enumerate(parts):
        node = next(n for n in nodes if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == part)
        if i == len(parts) - 1:
            return node
        nodes = node.body
    raise AssertionError(qualname)


def test_aspects_are_the_outcome_fields_and_each_has_one_consumer():
    fields = [f.name for f in dataclasses.fields(cc.CallOutcome)]
    assert fields[:2] == ["name", "mode"] and tuple(fields[2:]) == cc.ASPECTS
    assert set(cc.CONSUMERS) == set(cc.ASPECTS)
    assert len({id(f) for f in cc.CONSUMERS.values()}) == len(cc.ASPECTS)   # one function per aspect


def test_apply_calls_each_consumer_once_in_the_documented_order_with_its_own_aspect():
    fn = _function(Path(cc.__file__), "apply_call_outcome")
    by_name = {f.__name__: aspect for aspect, f in cc.CONSUMERS.items()}
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id in by_name]
    calls.sort(key=lambda n: (n.lineno, n.col_offset))
    assert [by_name[c.func.id] for c in calls] == list(cc.ASPECTS)   # each once, in order
    for c in calls:
        aspects = [a for a in c.args if isinstance(a, ast.Attribute)]
        assert [a.attr for a in aspects] == [by_name[c.func.id]], ast.dump(c)


def test_nothing_in_the_contract_ticks_the_budget():
    # the steps are the run's (R36's search budget): what a callee's run spent comes in by `absorb_run` only
    tree = _tree(Path(cc.__file__))
    assert not [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "tick"]
    absorb = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "absorb_run")
    steps = [n.lineno for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AugAssign))
             for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
             if isinstance(t, ast.Attribute) and t.attr == "steps"]
    assert steps and all(absorb.lineno <= line <= absorb.end_lineno for line in steps), steps


# (W3) a field no consumer reads is a field a producer may fill in vain: listed here with the step that will read it —
#   a consumer that starts reading one must take it off the list
NOT_YET_CONSUMED: dict[str, str] = {
    "Reads.names": "step 5 (read_set): what a call may read becomes the read set's candidates",
    "Reads.through_pointer": "step 5 (read_set): a read through a pointer leaves the read set incomplete",
    "Reads.upward_exposed": "step 5 (read_set): the interpreted call leaves it empty — the joined state carries them",
    "Return.declared_type": "step 4f (G9): an effects-only call's unknown return typed by the callee's declaration",
    "Return.void": "step 4f (G9): a void effects-only call has no value to type",
    "Failure.name": "step 4d (G7): the failed run's provenance names its callee",
}
# who reads a record the world hands back (the variable it is bound to there)
_RESULT_READERS = {
    "RunLog": [(cc.__file__, "absorb_run", "log")],
    "Result": [(cc.__file__, "interpreted_outcome", "done"), (cso.__file__, "_Interp.call", "done")],
    "Refused": [(cc.__file__, "interpreted_outcome", "done"), (cso.__file__, "_Interp.call", "done")],
    "Failure": [(cc.__file__, "effects_outcome", "fallback"), (cso.__file__, "_Interp.call", "done")],
}


def _attributes_read(fn: ast.AST, var: str) -> set[str]:
    return {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id == var and isinstance(n.ctx, ast.Load)}


def _read_fields() -> dict[str, set[str]]:
    """``{class: fields read}`` — an aspect by its consumer (its last parameter), a world record by its readers."""
    out = {}
    for aspect, consumer in cc.CONSUMERS.items():
        cls = type(getattr(cc.CallOutcome(**_full_outcome()), aspect)).__name__
        fn = _function(Path(cc.__file__), consumer.__name__)
        param = [a.arg for a in fn.args.args][3]   # (interp, state, name, aspect, …)
        out[cls] = _attributes_read(fn, param)
    for cls, readers in _RESULT_READERS.items():
        out[cls] = set().union(*(_attributes_read(_function(Path(p), q), v) for p, q, v in readers))
    return out


def test_every_field_is_consumed_or_listed_with_the_step_that_will():
    read = _read_fields()
    for cls, fields_read in read.items():
        fields = {f.name for f in dataclasses.fields(getattr(cc, cls))}
        waiting = {k.split(".", 1)[1] for k in NOT_YET_CONSUMED if k.split(".", 1)[0] == cls}
        assert fields - waiting <= fields_read, (cls, sorted(fields - waiting - fields_read))
        assert not waiting & fields_read, (cls, "consumed now — take off NOT_YET_CONSUMED:", sorted(waiting & fields_read))
    assert all(k.split(".", 1)[0] in read and re.match(r"step \d", v) for k, v in NOT_YET_CONSUMED.items())


def test_the_field_check_can_fail():
    # the walk sees a consumer's reads: dropping one of them is reported
    fn = _function(Path(cc.__file__), "_consume_paths")
    assert {"joined", "fallback", "ub_unanalysed", "refusal"} <= _attributes_read(fn, "paths")
    assert "upward_exposed" not in _attributes_read(_function(Path(cc.__file__), "_consume_reads"), "reads")


# ── 3. MODE_RULES total ─────────────────────────────────────────────────────────────────────────────────────────────

def test_mode_rules_are_total_over_modes_and_aspects():
    assert set(cc.MODE_RULES) == {(m, a) for m in cc.MODES for a in cc.ASPECTS}
    assert all(isinstance(r, str) and r.split(":", 1)[0].strip() and ":" in r for r in cc.MODE_RULES.values())


# ── 4. the conformance shapes meet every rule ───────────────────────────────────────────────────────────────────────

def _active(aspect, value) -> bool:
    if aspect == "paths":
        return bool(value.joined or value.refusal or value.fallback or value.ub_unanalysed)
    empty = {"reads": cc.NO_READS, "registers": cc.NO_REGISTERS, "writes": cc.NO_WRITES,
             "provenance": cc.NO_PROVENANCE}.get(aspect)
    return empty is None or value != empty


def _not_applicable(rule: str) -> bool:
    return rule.startswith("n/a:")


# Two cells the step-1 shapes do not meet (their callees keep no static, and a row's ``F() return`` always stubs F
#   there): built on the harness — its header, its units, its modes — in a project of their own
_COV = """#include "h.h"
U8 Count(void) { static U8 s_n = 0U; s_n = (U8)(s_n + 1U); return s_n; }
void x1(void) { g_o = Count(); g_p = 7U; }
void x2(void) { { U8 GetG = 1U; g_q = GetG; } g_o = GetG(); g_p = 7U; }
"""


def _coverage_shapes(conf):
    files = {**conf.FILES, conf._p("cov.c"): _COV}
    build = conf.cpc.detect_build_config({conf._p(".cproject"): conf._CPROJECT})
    ctx = conf.cpc.build_project_context(files, build)
    project = conf.Project(files, ctx, conf.cpc.build_scopes(ctx, [p for p in files if p.endswith(".c")]),
                           conf._p("cov.c"))
    return {"cov": project}, (
        # (I · provenance) a callee's static local: every later re-entry havoc names it (`Provenance.static_keys`)
        conf.Shape("X1", "a callee with a static local", {"I": "x1", "Ew": "x1", "E0": "x1"}, ({},), ("g_o", "g_p"),
                   frozenset({"Count"}), project="cov"),
        # (Ew · E0 · provenance) ``GetG() return`` set while GetG is no stub here (the function declares the name — R37
        #   W1): the effects-only call returns the row's value and the record rests on it
        conf.Shape("X2", "a row's F() return where F is not stubbable", {"Ew": "x2", "E0": "x2"},
                   ({"GetG() return": 6, "g_k": 4},), ("g_o", "g_q", "g_p"), frozenset({"GetG"}), project="cov"))


def _all_shapes(conf):
    projects = conf._build_projects()
    extra, shapes = _coverage_shapes(conf)
    return {**projects, **extra}, list(conf.SHAPES) + list(shapes)


@pytest.fixture(scope="module")
def shape_cells():
    """``{(mode, aspect)}`` some conformance shape's call outcome had non-empty, with every outcome's mode."""
    from tests.unit import test_callee_contract_conformance as conf
    seen, modes = set(), set()
    original = cc.apply_call_outcome

    def recording(interp, state, outcome):
        modes.add(outcome.mode)
        seen.update((outcome.mode, a) for a in cc.ASPECTS if _active(a, getattr(outcome, a)))
        return original(interp, state, outcome)
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv(conf.cpc.STORAGE_BYTE_ORDER_ENV, raising=False)
        mp.setattr(cc, "apply_call_outcome", recording)
        projects, shapes = _all_shapes(conf)
        for shape in shapes:
            conf.run_shape(projects, shape)
    return seen, modes


def test_the_coverage_shapes_give_the_values_they_are_built_for():
    from tests.unit import test_callee_contract_conformance as conf
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv(conf.cpc.STORAGE_BYTE_ORDER_ENV, raising=False)
        extra, (x1, x2) = _coverage_shapes(conf)
        r1, r2 = conf.run_shape(extra, x1), conf.run_shape(extra, x2)
    # interpreted, the static local starts as the program left it — unknown; run as effects only it is unknown too
    assert r1["I"][0][0]["g_p"].value == 7 and r1["I"][0][1]["interprocedural"]["inlined"] == {"Count": 1}
    for mode in ("Ew", "E0"):
        cells, record = r2[mode][0]
        assert (cells["g_o"].value, cells["g_q"].value, cells["g_p"].value) == (6, 1, 7), (mode, cells)
        assert record["stubs"] == ["GetG"], record


def test_every_mode_is_produced_by_some_shape(shape_cells):
    _seen, modes = shape_cells
    assert modes == set(cc.MODES), modes


def test_the_shapes_meet_every_rule_that_applies(shape_cells):
    seen, _modes = shape_cells
    needed = {cell for cell, rule in cc.MODE_RULES.items() if not _not_applicable(rule)}
    assert needed - seen == set(), sorted(needed - seen)


def test_a_rule_that_does_not_apply_is_empty_in_every_shape(shape_cells):
    seen, _modes = shape_cells
    idle = {cell for cell, rule in cc.MODE_RULES.items() if _not_applicable(rule)}
    assert idle & seen == set(), sorted(idle & seen)


# ── 5. closure fields are read in the contract's owners only ────────────────────────────────────────────────────────

CLOSURE_FIELDS = frozenset({"writes", "reads", "reads_complete", "pointer_write", "unknown_callees", "reaches",
                            "pointer_targets", "return_type", "termination"})
OWNERS = frozenset({"generators/callee_contract.py", "generators/c_project_context.py", "generators/pointer_flow.py"})
# a module holds a callee closure when it takes ``functions`` out of a build's ``effects`` — by ``.get``, by subscript, or
#   from `function_write_closure` itself — or reads an activation's ``closure`` (I3: every form the deep review found)
_HOLDS_CLOSURE = re.compile(r"""effects["']?\)?[^\n]{0,30}\.get\(["']functions["']"""
                            r"""|\[["']effects["']\]\s*\[["']functions["']\]|function_write_closure\(|\.closure\b""")
# (file, function) → why a string-key read of a closure field there stays (or why the dict read is no closure). Fixed:
#   a new site is a judgement point that bypasses the contract — ask a `CalleeSummary` instead
_MACRO_VIEW = "not a closure: a macro's view (`cpc.undecided_macro_view` · `cpc.macro_side_effects`) — ``writes`` is " \
              "whether a definition assigns"
_WALK_RECORDS = "not a closure: the MC/DC decision walk's own write records (``extra['writes']``)"
_CLANG_HARNESS = "the clang check writes its own harness from the closure (a verifier of the oracle, not a judgement " \
                 "point of it): "
ALLOWED: dict[tuple[str, str], str] = {
    ("generators/c_source_oracle.py", "_Interp.inert_macro"): _MACRO_VIEW,
    ("generators/c_source_oracle.py", "_Interp.macro_effectful"): _MACRO_VIEW,
    ("generators/mcdc_design.py", "_scoped_source_decisions"): _MACRO_VIEW,
    ("generators/mcdc_design.py", "_scoped_source_decisions.macro_writes"): _MACRO_VIEW,
    ("generators/mcdc_design.py", "_scoped_source_decisions.record_writes"): _WALK_RECORDS,
    ("generators/mcdc_design.py", "_rebinding_write"): _WALK_RECORDS,
    ("generators/mcdc_design.py", "_element_binding_issue"): _WALK_RECORDS,
    ("generators/mcdc_design.py", "_callee_writes"): "(J10) MC/DC: may a callee run before the decision rebind a "
                                                     "global input — its closure's writes / unknown callees (and macro "
                                                     "views); registers not yet (G13, step 4)",
    ("generators/mcdc_design.py", "_function_reaches"): "(R77) MC/DC element binding: may a callee write the array "
                                                        "through a pointer — its closure's pointer summary (no activation "
                                                        "to ask a summary from)",
    ("generators/mcdc_design.py", "_stub_return_domain"): "(R36) a stub return input's domain: the closure's declared "
                                                          "return type (the field `CalleeSummary.return_type` reads)",
    ("generators/suts.py", "listed_outputs_not_written"): "(J11, R80) the function under test's own closure, not a "
                                                          "call's — outputs nothing writes (G12, step 4)",
    ("scripts/integration_oracle_clang_check.py", "_stub_rtype"): _CLANG_HARNESS + "a stub's declared return type",
    ("scripts/source_oracle_clang_check.py", "_harness"): _CLANG_HARNESS + "a stub's declared return type",
    ("scripts/source_oracle_clang_check.py", "_harness.put_text"): _CLANG_HARNESS + "the fill a stub puts through "
                                                                   "the arguments `callee_targets` names",
    ("scripts/source_oracle_clang_check.py", "_harness.writes_through_pointer"): _CLANG_HARNESS + "whether a stub may "
                                                                                 "write through its arguments",
}


def _constant_keys(node) -> list[str]:
    """The string keys a node reads a dict by: ``x["f"]`` (Load), ``x.get("f")``, ``"f" in x``, ``itemgetter("f", …)``,
    a literal tuple / list / set of keys (``for k in ("f", "g"): x[k]``)."""
    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) and isinstance(node.slice, ast.Constant):
        return [node.slice.value]
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "get" and node.args and isinstance(node.args[0], ast.Constant):
            return [node.args[0].value]
        if (isinstance(f, ast.Name) and f.id == "itemgetter") or (isinstance(f, ast.Attribute)
                                                                  and f.attr == "itemgetter"):
            return [a.value for a in node.args if isinstance(a, ast.Constant)]
    if isinstance(node, ast.Compare) and isinstance(node.left, ast.Constant) \
            and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
        return [node.left.value]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)) and isinstance(getattr(node, "ctx", ast.Load()), ast.Load):
        return [e.value for e in node.elts if isinstance(e, ast.Constant)]
    return []


def _field_reads(path: Path):
    """``[(function qualname, field, line)]`` — a closure field read by string key, in any of `_constant_keys`' forms."""
    tree = _tree(path)
    out = []

    def visit(node, scope):
        for child in ast.iter_child_nodes(node):
            inner = scope + [child.name] if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                else scope
            for key in _constant_keys(child):
                if isinstance(key, str) and key in CLOSURE_FIELDS:
                    out.append((".".join(scope) or "<module>", key, child.lineno))
            visit(child, inner)
    visit(tree, [])
    return out


def _closure_field_sites():
    sites = {}
    for path in sorted(list((ROOT / "generators").glob("*.py")) + list((ROOT / "scripts").glob("*.py"))):
        rel = path.relative_to(ROOT).as_posix()
        if rel in OWNERS or not _HOLDS_CLOSURE.search(path.read_text(encoding="utf-8")):
            continue
        for qual, key, line in _field_reads(path):
            sites.setdefault((rel, qual), []).append((key, line))
    return sites


def test_closure_fields_are_read_by_the_contract_only():
    sites = _closure_field_sites()
    assert set(sites) - set(ALLOWED) == set(), {k: v for k, v in sites.items() if k not in ALLOWED}
    assert set(ALLOWED) - set(sites) == set(), "an allowed site is gone — drop it from ALLOWED"
    assert len(ALLOWED) == 15 and all(r.strip() for r in ALLOWED.values())


def test_the_oracle_holds_no_closure_field_read():
    # the judgement points J1 · J3 · J6 · J9, the stub hedge and the register havoc ask a `CalleeSummary`
    assert [s for s in _closure_field_sites() if s[0] == "generators/c_source_oracle.py"
            and not ALLOWED.get(s, "").startswith("not a closure")] == []


@pytest.mark.parametrize("form, text", [
    ("subscript", 'def judge(scope, name):\n    return scope["effects"]["functions"][name]["writes"]\n'),
    ("write_closure_call", "from generators import c_project_context as cpc\ndef judge(ctx, n):\n"
                           '    fx = cpc.function_write_closure(ctx)\n    return fx["functions"][n].get("pointer_write")\n'),
    ("itemgetter", 'import operator\ndef judge(interp, n):\n    return operator.itemgetter("writes")(interp.closure[n])\n'),
    ("tuple_keys", 'def judge(interp, n):\n    info = interp.closure[n]\n'
                   '    return any(info[k] for k in ("pointer_write", "unknown_callees"))\n'),
    ("plain", 'def judge(interp, n):\n    return interp.closure[n]["writes"]\n'),
])
def test_every_bypass_form_is_caught(form, text):
    # (I3) the forms the deep review's `ratchet_probe.py` found sneaking past: each is now scanned and read
    assert _HOLDS_CLOSURE.search(text), form
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "m.py"
        p.write_text(text, encoding="utf-8")
        assert _field_reads(p), form


# (I3) a judgement point asks a predicate (`may_change`, `effectful`, `inert`, `may_read`, `stub_hedge`,
#   `volatile_reads`) — it does not read the summary's fields. (file, function) → why a read stays. Fixed.
SUMMARY_FIELDS = frozenset(f.name for f in dataclasses.fields(cc.CalleeSummary)) - {"name", "kind"}
SUMMARY_READS_ALLOWED: dict[tuple[str, str], str] = {
    ("generators/c_source_oracle.py", "_Interp.callee_targets"): "the effects-only producer's write targets, resolved "
                                                                 "on the activation (harness buffers, the points-to "
                                                                 "answers of its arguments) — part of the producer",
}


def _summary_field_sites():
    sites = {}
    for path in sorted((ROOT / "generators").glob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel == "generators/callee_contract.py":
            continue
        tree = _tree(path)
        called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        uses_contract = "callee_contract" in path.read_text(encoding="utf-8")

        def visit(node, scope):
            for child in ast.iter_child_nodes(node):
                inner = scope + [child.name] if isinstance(child, (ast.FunctionDef, ast.ClassDef)) else scope
                if uses_contract and isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Load) \
                        and child.attr in SUMMARY_FIELDS and id(child) not in called:
                    sites.setdefault((rel, ".".join(scope)), set()).add(child.attr)
                visit(child, inner)
        visit(tree, [])
    return sites


def test_judgement_points_ask_the_summary_never_read_its_fields():
    sites = _summary_field_sites()
    assert set(sites) == set(SUMMARY_READS_ALLOWED), sites
    assert len(SUMMARY_READS_ALLOWED) == 1 and all(r.strip() for r in SUMMARY_READS_ALLOWED.values())


# ── 6. hypothetical probes put back what the consumers set; inline and the producers change no caller ──────────────

_ACTIVATION_NAMES = frozenset({"interp", "caller", "it"})
_MUTATORS = frozenset({"append", "extend", "add", "update", "setdefault", "clear", "pop", "discard", "remove"})


def _set_attributes(tree):
    """``{("activation" | "world", attribute)}`` the code changes on an activation or on the world."""
    out = set()

    def owner_attr(node):
        if not isinstance(node, ast.Attribute):
            return None
        v = node.value
        if isinstance(v, ast.Name) and v.id in _ACTIVATION_NAMES:
            return "activation", node.attr
        if (isinstance(v, ast.Name) and v.id == "world") or (isinstance(v, ast.Attribute) and v.attr == "world"):
            return "world", node.attr
        return None
    for n in ast.walk(tree):
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AugAssign) else []
        for t in targets:
            for e in (t.elts if isinstance(t, ast.Tuple) else [t]):
                hit = owner_attr(e.value if isinstance(e, ast.Subscript) else e)
                if hit:
                    out.add(hit)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _MUTATORS:
            hit = owner_attr(n.func.value)
            if hit:
                out.add(hit)
    return out


def test_what_the_consumers_set_is_put_back_by_a_hypothetical_probe():
    changed = _set_attributes(_tree(Path(cc.__file__)))
    activation = set(cso._HYPOTHETICAL_TABLES) | set(cso._HYPOTHETICAL_EXEMPT)
    world = set(cso._HYPOTHETICAL_WORLD_TABLES) | set(cso._HYPOTHETICAL_WORLD_GROWING) | set(cso._HYPOTHETICAL_EXEMPT)
    assert {a for k, a in changed if k == "activation"} - activation == set()
    assert {a for k, a in changed if k == "world"} - world == set()
    # the walk saw the consumers (registers, provenance, the world's counts, G5 / G6's names) and the run log
    assert {("activation", "stubs_used"), ("activation", "storage_used"), ("activation", "steps"),
            ("activation", "volatile_polls"), ("activation", "callee_termination_assumed"),
            ("activation", "callee_ub_unanalysed"), ("world", "inlined"), ("world", "effects_only"),
            ("world", "static_keys")} <= changed
    # the summary cache lives in ``shared`` — a cache of the text, the same whoever fills it
    assert "shared" in cso._HYPOTHETICAL_EXEMPT


def test_inline_changes_neither_the_caller_nor_its_state():
    fn = _function(Path(cso.__file__), "_World.inline")
    bad = []
    for n in ast.walk(fn):
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AugAssign) else []
        for t in targets:
            root = t
            while isinstance(root, (ast.Attribute, ast.Subscript)):
                root = root.value
            if isinstance(root, ast.Name) and root.id in ("caller", "state") and root is not t:
                bad.append(n.lineno)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Attribute) \
                and isinstance(n.func.value.value, ast.Name) and n.func.value.value.id in ("caller", "state") \
                and n.func.attr in _MUTATORS:
            bad.append(n.lineno)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr.startswith("havoc"):
            bad.append(n.lineno)   # a havoc on the caller's state (the recursion statics are `Writes.reentry`'s)
    assert bad == []


# the producer effects the module docstring names (I4): caches and facts any later run would record alike
_PRODUCER_MAY_SET = frozenset({"harness_buffers"})


def _snapshot(interp, state):
    tables = {a: cso._table_copy(getattr(interp, a)) for a in cso._HYPOTHETICAL_TABLES if a not in _PRODUCER_MAY_SET}
    world = interp.world
    if world is not None:
        tables.update({"world." + a: cso._table_copy(getattr(world, a))
                       for a in cso._HYPOTHETICAL_WORLD_TABLES + cso._HYPOTHETICAL_WORLD_GROWING})
    path = (tuple((k, id(v)) for k, v in state.store.items()), state.mode, state.ret, state.havoc_all,
            state.havoc_pointer, dict(state.havoc_bases), set(state.escaped), list(state.forks), set(state.possible_ub),
            len(state.decisions), set(state.initial_reads), set(state.rebound), list(state.selectors), state.ub_proven)
    return tables, path, interp.steps


def test_a_producer_judges_and_changes_nothing():
    # (I4) on every conformance shape in every mode: what each producer leaves on the activation, the world and the path
    from tests.unit import test_callee_contract_conformance as conf
    calls = []

    def pure(producer, at):
        def wrapper(interp, *a, **k):
            state = a[at]
            before = _snapshot(interp, state)
            out = producer(interp, *a, **k)
            calls.append(producer.__name__)
            assert _snapshot(interp, state) == before, producer.__name__
            return out
        return wrapper
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv(conf.cpc.STORAGE_BYTE_ORDER_ENV, raising=False)
        for name in ("interpreted_outcome", "effects_outcome", "stub_outcome"):
            mp.setattr(cc, name, pure(getattr(cc, name), 0))
        projects, shapes = _all_shapes(conf)
        for shape in shapes:
            conf.run_shape(projects, shape)
    assert {"interpreted_outcome", "effects_outcome", "stub_outcome"} <= set(calls)
    assert "state" not in inspect.signature(cc.unknown_outcome).parameters   # it is handed no path to change


# ── 7. one refusal table ────────────────────────────────────────────────────────────────────────────────────────────
# The rules each site kept before step 3 — the table must give exactly these (behaviour unchanged)

def _former_inline(reason):
    return reason.startswith("undefined_behavior:") or reason in {
        "unsequenced_side_effects", "non_terminating_loop", "constant_condition_loop_unfinished",
        "cast_parse_of_parenthesized_expression"}


def _former_loop(reason):
    return reason.split(":", 1)[0] in {"loop_iteration_budget", "execution_budget", "path_budget"}


def _former_ioc(reason):
    return reason.split(":", 1)[0] in {"execution_budget", "constant_condition_loop_unfinished"}


def _reasons():
    """Every refusal reason the code raised before step 4, in the form it is raised: a literal ``Unsupported("head")``
    bare, a literal ``Unsupported("head:" + …)`` with a detail, and the reasons raised from a variable (the polling
    verdicts, the budgets, a prescan verdict). The former inline rule matched ``unsequenced_side_effects`` ·
    ``non_terminating_loop`` · ``constant_condition_loop_unfinished`` exactly and ``undefined_behavior:`` as a prefix;
    the table reads heads — the same on every reason raised (none of the first three is raised with a detail before step
    4b, ``undefined_behavior`` never bare)."""
    reasons = {"", "execution_budget:polling_way_out_search", "polling_loop_exit_search_budget:65536",
               "polling_loop_exit_undetermined:condition_unknown_for_a_flag_value", "polling_flag_unmodeled",
               "polling_flag_unmodeled:REG_A", "non_terminating_loop", "polling_loop_exit_not_found",
               "polling_loop_exit_search_incomplete", "polling_loop_condition_changes_state",
               "polling_loop_body_changes_state", "polling_loop_first_poll_unchecked",
               "polling_loop_body_reads_flag:REG_A", "oracle_exception:KeyError", "forced_effects_only"}
    for path in (ROOT / "generators").glob("*.py"):
        for head, colon in re.findall(r'Unsupported\(f?"([a-z_]+)(:?)', path.read_text(encoding="utf-8")):
            reasons.add(head + (":detail" if colon else ""))
    return sorted(reasons)


def test_the_refusal_table_keeps_every_former_rule():
    reasons = _reasons()
    assert len(reasons) > 100   # the scan found the generators' literals (115 at step 3)
    for r in reasons:
        assert cc.refuses_in_callee(r) == _former_inline(r), r
        assert cc.iteration_budget(r) == _former_loop(r), r
        assert cc.run_budget(r) == _former_ioc(r), r


def test_an_effects_only_callee_that_never_returns_refuses_as_an_interpreted_one():
    # (step 4b) `non_terminating_loop:<callee>` is the class an interpreted callee's loop refuses with — it propagates
    #   out of an interpreted caller the same way (`refuses_in_callee`), and is no budget
    reason = cc.effects_termination("Halt", types.SimpleNamespace(termination=cc.NEVER)).evidence
    assert reason == "non_terminating_loop:Halt"
    assert cc.refusal_class(reason) == cc.refusal_class("non_terminating_loop") == "program_termination"
    assert cc.refuses_in_callee(reason) and not cc.iteration_budget(reason) and not cc.run_budget(reason)


def test_the_refusal_table_is_the_conformance_harness_classes():
    from tests.unit import test_callee_contract_conformance as conf
    for r in _reasons() + ["non_terminating_loop:Halt"]:
        assert cc.refusal_class(r) == conf.refusal_class(r), r
    assert set(c for c, _spent in cc.REFUSAL_CLASS.values()) | {"model"} == set(cc.REFUSAL_CLASSES)


def test_the_sites_ask_the_table():
    from generators import integration_oracle as ioc
    src = {p: Path(p).read_text(encoding="utf-8") for p in (cso.__file__, ioc.__file__)}
    assert "cc.refuses_in_callee(" in source_of(cso._World.inline)
    assert "cc.iteration_budget(" in source_of(cso._Interp.loop)
    assert "cc.iteration_budget(" in source_of(cso._Interp.polling_search)
    assert "run_budget(" in source_of(ioc._refused_for_budget)
    assert not any("_BUDGET_REASONS" in s or "_REFUSING_IN_CALLEE" in s for s in src.values())


# ── 8. a producer's refusal; what a refused call leaves on the record ──────────────────────────────────────────────

def _bare_activation(world=None):
    return types.SimpleNamespace(world=world, stubs_used=set(), linked_reads=set(), assumed_undefined=set(),
                                 callee_ub_unanalysed=set(), callee_termination_assumed=set())


def test_a_refused_outcome_counts_and_discloses_then_refuses():
    # (W1) `_refused` directly: the world's count and G6's name stand, nothing else applies, the refusal is the reason
    paths = cc.Paths(joined=False, refusal="", ub_unanalysed=frozenset({"F"}), fallback="definition:x")
    out = cc._refused("F", "Ew", "x", paths, cc.NO_PROVENANCE)
    assert (out.paths.refusal, out.paths.fallback, out.paths.ub_unanalysed) == ("x", "definition:x", {"F"})
    assert (out.reads, out.registers, out.writes, out.provenance) == (cc.NO_READS, cc.NO_REGISTERS, cc.NO_WRITES,
                                                                      cc.NO_PROVENANCE)
    world = types.SimpleNamespace(inlined={}, effects_only={}, static_keys=set())
    interp = _bare_activation(world)
    with pytest.raises(cso.Unsupported, match=r"^x$"):
        cc.apply_call_outcome(interp, cso._State(), out)
    assert world.effects_only == {"F": 1} and interp.callee_ub_unanalysed == {"F"} and interp.stubs_used == set()
    # (I1) a stub's refusal keeps the stub it entered
    entered = cc.Provenance(stubs_entered=frozenset({"S"}), stubs_used=frozenset(), linked_reads=frozenset(),
                            assumed_undefined=frozenset(), static_keys=frozenset())
    interp = _bare_activation()
    stub_paths = cc.Paths(joined=False, refusal="", ub_unanalysed=frozenset(), fallback="")
    with pytest.raises(cso.Unsupported, match=r"^y$"):
        cc.apply_call_outcome(interp, cso._State(), cc._refused("S", "S", "y", stub_paths, entered))
    assert interp.stubs_used == {"S"}


@pytest.fixture()
def conformance(monkeypatch):
    from tests.unit import test_callee_contract_conformance as conf
    monkeypatch.delenv(conf.cpc.STORAGE_BYTE_ORDER_ENV, raising=False)
    monkeypatch.setattr(cso._TREES, "cache", __import__("collections").OrderedDict(), raising=False)
    return conf, conf._build_projects()["main"], conf.SHAPE_BY_ID["S3"]


def test_a_producer_refusal_in_a_run_is_the_record_s_reason_and_counted_once(conformance, monkeypatch):
    # (W1) `Put(&t)` writes through its pointer: run as effects only, its targets are asked — a refusal there is the
    #   record's reason, after the world counted the call (once: the run stops there)
    conf, project, s3 = conformance
    worlds = []
    init = cso._World.__init__

    def recording(self, *a, **k):
        init(self, *a, **k)
        worlds.append(self)

    def refusing(self, *a, **k):
        raise cso.Unsupported("x")
    monkeypatch.setattr(cso._World, "__init__", recording)
    monkeypatch.setattr(cso._Interp, "callee_targets", refusing)
    for mode in ("Ew", "E0"):
        worlds.clear()
        (cells, record), = conf.run_mode(project, s3, mode)
        assert record["status"] == "unsupported" and record["reason"] == "x", (mode, record)
        if mode == "Ew":
            assert [w.effects_only for w in worlds] == [{"Put": 1}], worlds
        else:
            assert worlds == []


@pytest.mark.parametrize("where", ["stub_targets", "havoc_objects"])
def test_a_stub_s_refusal_keeps_the_stub_it_entered(conformance, monkeypatch, where):
    # (I1) `Put() p[0]` stubs Put: a refusal while the stub's targets are judged (the producer) or while what they reach
    #   is havocked (the writes consumer — `storage_layout_differs_between_units`) keeps Put among the stubs used
    conf, project, s3 = conformance
    seen = []

    def refusing(self, *a, **k):
        seen.append(self)
        raise cso.Unsupported("storage_layout_differs_between_units:REG_A")
    monkeypatch.setattr(cso._Interp, where, refusing)
    (cells, record), = conf.run_mode(project, s3, "S")
    assert record["reason"] == "storage_layout_differs_between_units:REG_A", record
    assert seen and "Put" in seen[0].stubs_used
