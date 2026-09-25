"""(R16b) clang check of SITS integration values — callees compiled as members of one constexpr struct.

Claims come from the interprocedural oracle itself (`evaluate_outputs` with a `CalleeProvider`); sentinels are values the
oracle would not claim. clang (``--target=msp430``) must be on PATH for the checks that compile.
"""
from __future__ import annotations

import json
import os
import shutil

import pytest

from generators import c_project_context as cpc
from generators.c_source_oracle import evaluate_outputs
from generators.integration_oracle import CalleeProvider
from scripts import integration_oracle_clang_check as ioc

ROOT = os.path.join(os.sep, "virt_r16b")
COMMON = """#ifndef COMMON_H
#define COMMON_H
typedef unsigned char U8;
typedef unsigned int U16;
typedef signed int S16;
extern U8 g_in;
extern U8 g_out;
extern U16 g_sum;
extern S16 g_s;
extern U8 g_buf[4];
enum E_T { E_A, E_B, E_C };
extern enum E_T g_e;
void b_set_e(enum E_T v);
U8 b_scale(U8 x);
void b_store(U8 v);
U8 b_branch(U8 v);
U8 b_goto(U8 v);
S16 b_over(S16 v);
U8 b_count(void);
U8 b_help(void);
U8 b_struct(void);
U8 lib_get(void);
#endif
"""
A = """#include "common.h"
#define SCALE 7U
U8 g_in;
U8 g_out;
U16 g_sum;
S16 g_s;
U8 g_buf[4];
enum E_T g_e;
static U8 helper(void) { return 5U; }
void entry(U8 k) {
    U8 r = b_scale(k);
    b_store(r);
    g_out = (U8)(b_branch(g_in) + SCALE);
}
void jumps(void) { g_out = b_goto(g_in); g_sum = 7U; }
void overflow(void) { g_s = b_over(g_s); }
void counted(void) { g_out = b_count(); g_in = b_count(); }
void collide(void) { g_out = (U8)(b_help() + helper()); }
void dep(void) { g_out = lib_get(); }
void cut(void) { g_in = b_struct(); g_out = 2U; }
void stubbed(void) { g_out = b_scale(g_in); }
void tagged(void) { b_set_e(E_C); g_out = (g_e == E_C) ? 1U : 0U; }
"""
B = """#include "common.h"
#define SCALE 3U
struct S { U8 a; };
static struct S s_obj;
static U8 s_b;
static U8 helper(void) { return 1U; }
U8 b_scale(U8 x) { return (U8)(x * SCALE); }
void b_store(U8 v) { g_sum = (U16)(g_sum + v); s_b = v; }
U8 b_branch(U8 v) { if (v > 10U) { return 3U; } return 4U; }
U8 b_goto(U8 v) { if (v) { goto done; } g_sum = 1U; done: return v; }
S16 b_over(S16 v) { return (S16)(v + 32767); }
U8 b_count(void) { static U8 n; n = 4U; n++; return n; }
U8 b_help(void) { return helper(); }
U8 b_struct(void) { s_obj.a = 1U; g_sum = 5U; return 2U; }
void b_set_e(enum E_T v) { g_e = v; }
"""
FILES = {os.path.join(ROOT, "common.h"): COMMON, os.path.join(ROOT, "a.c"): A, os.path.join(ROOT, "b.c"): B}
A_PATH = os.path.join(ROOT, "a.c")
needs_clang = pytest.mark.skipif(shutil.which("clang") is None, reason="clang (msp430 target) not installed")


@pytest.fixture(scope="module")
def project():
    ctx = cpc.build_project_context(FILES)
    scopes = cpc.build_scopes(ctx, [p for p in FILES if p.endswith(".c")])
    parser = cpc.shared_parser()
    return FILES, scopes, CalleeProvider(ctx, FILES, scopes, parser), parser


def _claims(project, name, cases):
    files, scopes, provider, _parser = project
    unit = {"name": name, "source_text": files[A_PATH], "source_path": A_PATH, "source_text_complete": True,
            "project_scope": scopes[A_PATH], "callee_provider": provider}
    out = []
    for inputs, outputs, sentinel in cases:
        rec = evaluate_outputs(unit, [inputs], [list(outputs)])[0]
        derived = {k: v["value"] for k, v in rec["outputs"].items() if "value" in v}
        # the callees the model ran, as the Test Evidence sheet records them — the rest are stubs in that run
        ip = rec.get("interprocedural") or {}
        out.append({"inputs": inputs, "outputs": {**derived, **sentinel}, "possible_ub": [], "derived": derived,
                    "interpreted": set(ip.get("inlined") or ()), "effects_only": set(ip.get("effects_only") or ())})
    return out


def _check(project, name, claims, tmp_path):
    files, scopes, provider, parser = project
    return ioc.check_group(name, A_PATH, claims, files, scopes, provider, parser, work_dir=str(tmp_path / name))


# ── without clang: what the harness is made of ──────────────────────────────────────────────────

def test_calls_of_a_renamed_function_name_its_member_only():
    text = "x = helper(1) + helper2(2) + helper (3); y = helper;"
    assert ioc._renamed(text, {"helper": "helper__oracle_1"}) == \
        "x = helper__oracle_1(1) + helper2(2) + helper__oracle_1 (3); y = helper;"


def test_static_locals_become_members_named_per_block(project):
    files, scopes, _provider, parser = project
    raw = files[os.path.join(ROOT, "b.c")].encode()
    from generators.c_source_oracle import _find_function
    fn = _find_function(parser.parse(raw).root_node, raw, "b_count", scopes[os.path.join(ROOT, "b.c")])
    body, specs, calls = ioc._hoisted(fn, raw, "b_count", scopes[os.path.join(ROOT, "b.c")], "t")
    assert [s["member"] for s in specs] == ["__oracle_sl_b_count_n_0_t"]
    assert "static" not in body and "__oracle_sl_b_count_n_0_t = 4U; __oracle_sl_b_count_n_0_t++;" in body


def test_words_in_comments_and_preprocessor_lines_are_not_calls():
    # HDPDM01 R16b: ``/* wait for conversion (ADC) */``, ``#if defined(X)`` and ``__asm("nop")`` became stubs named
    # ``conversion`` / ``defined`` / ``__asm`` — the last one broke the whole struct (466 claims unchecked)
    text = COMMON.replace("#endif\n", "") + "#endif\n" + (
        '#include "common.h"\n'
        "void w(void) {\n    /* wait for conversion (ADC) done( ) */\n#if defined(CFG_X)\n    g_out = 1U;\n#endif\n"
        '    __asm("nop");\n    b_store(g_in); // then report(x)\n}\n')
    files = {os.path.join(ROOT, "common.h"): COMMON, os.path.join(ROOT, "w.c"): text}
    ctx = cpc.build_project_context(files)
    scope = cpc.build_scopes(ctx, [os.path.join(ROOT, "w.c")])[os.path.join(ROOT, "w.c")]
    parser = cpc.shared_parser()
    raw = text.encode()
    from generators.c_source_oracle import _find_function
    fn = _find_function(parser.parse(raw).root_node, raw, "w", scope)
    rec = ioc._compiled("w", os.path.join(ROOT, "w.c"), raw, fn, scope)
    assert rec["calls"] == ["b_store"], rec["calls"]
    assert "conversion" not in rec["body"] and "report" not in rec["body"]   # comments blanked, lines kept
    assert rec["body"].count("\n") == _text_lines(fn, raw) - 1


def _text_lines(fn, raw):
    body = fn.child_by_field_name("body")
    return raw[body.start_byte:body.end_byte].count(b"\n") + 1


def test_static_helpers_of_two_units_get_a_member_each(project):
    files, scopes, provider, parser = project
    funcs, entry, unbound, cut, cnames, _scopes = ioc._closure("collide", A_PATH, files, scopes, provider, parser)
    assert entry == "collide" and not unbound and not cut
    helpers = {m: f["path"] for m, f in funcs.items() if f["name"] == "helper"}
    assert len(helpers) == 2 and all(m.startswith("helper__oracle_") for m in helpers)
    # each caller names the helper of its own unit
    mine = next(m for m, p in helpers.items() if p == A_PATH)
    assert funcs["collide"]["renames"] == {"helper": mine}
    assert funcs["b_help"]["renames"]["helper"] != mine


# ── with clang ──────────────────────────────────────────────────────────────────────────────────

@needs_clang
def test_integrated_values_agree_and_a_wrong_value_is_caught(project, tmp_path):
    claims = _claims(project, "entry", [({"k": 5, "g_in": 20, "g_sum": 100}, ["g_out", "g_sum", "s_b"], {}),
                                        ({"k": 5, "g_in": 20, "g_sum": 100}, ["g_sum"], {"g_sum": 111})])
    assert claims[0]["derived"] == {"g_out": 10, "g_sum": 115, "s_b": 15}   # b_scale uses b.c's SCALE (3), entry a.c's (7)
    final, notes = _check(project, "entry", claims, tmp_path)
    assert {k: v for k, (v, _d) in final.items()} == {(0, "g_out"): "agree", (0, "g_sum"): "agree", (0, "s_b"): "agree",
                                                       (1, "g_sum"): "mismatch"}, notes
    assert "115 == 111" in final[(1, "g_sum")][1]


@needs_clang
def test_static_locals_and_same_named_helpers_run_for_real(project, tmp_path):
    claims = _claims(project, "counted", [({}, ["g_out", "g_in"], {})]) + \
        _claims(project, "collide", [({}, ["g_out"], {})])
    assert claims[0]["derived"] == {"g_out": 5, "g_in": 5} and claims[1]["derived"] == {"g_out": 6}
    assert _check(project, "counted", claims[:1], tmp_path)[0] == {(0, "g_out"): ("agree", ""), (0, "g_in"): ("agree", "")}
    assert _check(project, "collide", claims[1:], tmp_path)[0] == {(0, "g_out"): ("agree", "")}


@needs_clang
def test_a_value_that_depends_on_an_unbound_call_is_a_contradiction(project, tmp_path):
    claims = _claims(project, "dep", [({}, ["g_out"], {"g_out": 90})])
    assert claims[0]["derived"] == {}   # the oracle does not claim it
    final, notes = _check(project, "dep", claims, tmp_path)
    assert final[(0, "g_out")][0] == "mismatch" and notes["unbound"] == {"lib_get": "no_definition_in_project"}


@needs_clang
def test_a_cut_callee_leaves_its_effects_unchecked_not_contradicted(project, tmp_path):
    claims = _claims(project, "cut", [({"g_sum": 9}, ["g_out", "g_in", "g_sum"], {})])
    assert claims[0]["derived"] == {"g_out": 2, "g_in": 2, "g_sum": 5}
    final, notes = _check(project, "cut", claims, tmp_path)
    assert notes["cut"] and next(iter(notes["cut"])) == "b_struct"
    assert final[(0, "g_out")][0] == "agree_with_cut_callees"
    assert final[(0, "g_in")][0] == final[(0, "g_sum")][0] == "unchecked:cut_callee_reached"


@needs_clang
def test_undefined_behaviour_in_a_callee_and_goto_limits(project, tmp_path):
    claims = _claims(project, "overflow", [({"g_s": 5}, ["g_s"], {"g_s": 1})])
    assert claims[0]["derived"] == {}   # the oracle refuses the run
    claims[0]["interpreted"], claims[0]["effects_only"] = None, set()   # a forced claim about the code: every body runs
    final, _notes = _check(project, "overflow", claims, tmp_path)
    assert final[(0, "g_s")][0] == "eval_error"
    assert final[(0, "g_s")][1].endswith("[in b_over (b.c)]")   # where it failed (review R2 IR2-9, R3 I3-4)
    # the sheet does not say which callees ran as effects: undefined behaviour inside one is not held against the claim
    claims[0]["effects_only"] = None
    final, _notes = _check(project, "overflow", claims, tmp_path / "unknown")
    assert final[(0, "g_s")][0] == "unchecked:callee_partly_interpreted"
    claims = _claims(project, "jumps", [({"g_in": 1}, ["g_sum"], {}), ({"g_in": 0}, ["g_sum"], {})])
    # the model reads b_goto (a goto) as effects: with its record, b_goto is a stub in both runs
    final, _notes = _check(project, "jumps", claims, tmp_path)
    assert {k: v for k, (v, _d) in final.items()} == {(0, "g_sum"): "agree_with_stubbed_callees",
                                                       (1, "g_sum"): "agree_with_stubbed_callees"}
    # every body run: the goto path is a constant-evaluation limit, the other path checks
    for c in claims:
        c["interpreted"] = None
    final, _notes = _check(project, "jumps", claims, tmp_path / "all")
    assert final[(0, "g_sum")][0] == "unchecked:constexpr_limit" and final[(1, "g_sum")][0] == "agree"


@needs_clang
def test_an_enum_written_by_its_tag_is_checked_for_every_underlying_type(project, tmp_path):
    # KJPDS02_PV R16b: ``enum en_g_DoorState g_DoorState;`` (no typedef) made 825 claims' entries fail to compile
    claims = _claims(project, "tagged", [({}, ["g_out", "g_e"], {})])
    assert claims[0]["derived"] == {"g_out": 1, "g_e": 2}
    final, notes = _check(project, "tagged", claims, tmp_path)
    assert final == {(0, "g_out"): ("agree", ""), (0, "g_e"): ("agree", "")}, notes
    assert notes["rounds"] == len(ioc._ENUM_BASES)   # every permitted underlying type was compiled


@needs_clang
def test_a_sequence_stub_replaces_the_body(project, tmp_path):
    claims = _claims(project, "stubbed", [({"g_in": 3, "b_scale() return": 50}, ["g_out"], {}),
                                          ({"g_in": 3}, ["g_out"], {})])
    assert claims[0]["derived"] == {"g_out": 50} and claims[1]["derived"] == {"g_out": 9}
    final, _notes = _check(project, "stubbed", claims, tmp_path)
    assert final == {(0, "g_out"): ("agree", ""), (1, "g_out"): ("agree", "")}


@needs_clang
def test_a_run_clang_cannot_start_is_never_a_pass(project, tmp_path):
    claims = _claims(project, "entry", [({"k": 5, "g_in": 20, "g_sum": 100}, ["g_out"], {})])
    files, scopes, provider, parser = project
    final, notes = ioc.check_group("entry", A_PATH, claims, files, scopes, provider, parser, clang="clang",
                                   target="no-such-target", work_dir=str(tmp_path / "t"))
    assert final is None and notes["failure"].startswith("canary_not_reported")


@needs_clang
def test_the_script_reads_a_sits_evidence_sheet_end_to_end(tmp_path):
    import openpyxl

    from generators.integration_oracle import TEST_EVIDENCE_HEADERS
    root = tmp_path / "src"
    root.mkdir()
    for p, text in FILES.items():
        (root / os.path.basename(p)).write_text(text, encoding="utf-8", newline="\n")
    real_a = str((root / "a.c").resolve())
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Test Evidence"
    ws.append(TEST_EVIDENCE_HEADERS)
    inputs = json.dumps({"k": 5, "g_in": 20, "g_sum": 100})
    for obs, val in (("g_out", 10), ("g_sum", 115), ("s_b", 99)):
        row = dict.fromkeys(TEST_EVIDENCE_HEADERS, "")
        row.update({"Test Case ID": "TC1", "Case": 1, "Entry function": "entry", "Observable": obs, "Expected": val,
                    "Status": "derived", "Source path": real_a, "Inputs JSON": inputs,
                    "Callees interpreted": "b_branch, b_scale, b_store"})
        ws.append([row[h] for h in TEST_EVIDENCE_HEADERS])
    xlsm = tmp_path / "s.xlsx"
    wb.save(xlsm)
    out = tmp_path / "r.json"
    rc = ioc.main(["--xlsm", str(xlsm), "--source-root", str(root), "--out", str(out), "--workers", "1"])
    report = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 1 and report["verdicts"] == {"agree": 2, "mismatch": 1}, report
    assert report["mismatches"][0]["output"] == "s_b"
