"""R89 — several source roots are separate builds, everywhere SITS reads the call graph.

HDPDM01 is two programs: APP (``PDS64_RD``) and BOOT (``PDS64_FBL``). 11 functions are defined in both (``main``,
``EEPROM_SetByte``, ``lin_lld_sci_init`` …). The callee binding already linked within the caller's build
(`CalleeProvider._resolve`), but four readers keyed by function name only:

- the callee write closure (`build_scopes`) — one union for both builds' namesakes;
- the object-name ambiguity check (`CalleeProvider`) — APP's ``static`` and BOOT's external object of one name refused;
- the SITS flow collection (`collect_integration_flows`) — one ``name → info`` and one call graph: BOOT entry points got
  APP objects as observables (3,800 expected cells of the generated HDPDM01 SITS named an object their build lacks);
- the oracle's entry definition (`attach_integration_evidence`) — an entry defined in both builds was skipped.
"""
from __future__ import annotations

import os

from generators import c_project_context as cpc
from generators.c_source_oracle import evaluate_outputs
from generators.integration_oracle import CalleeProvider, attach_integration_evidence
from generators.sits import collect_integration_flows, generate_itc_list

ROOT = os.path.abspath(os.path.join(os.sep, "r89_virtual"))
APP, BOOT = os.path.join(ROOT, "app"), os.path.join(ROOT, "boot")
HDR = "typedef unsigned char U8;\ntypedef unsigned int U16;\nvoid store(U8 v);\n"


def _files():
    return {
        os.path.join(APP, "m.h"): HDR + "extern U8 g_app;\n",
        os.path.join(BOOT, "m.h"): HDR + "extern U8 g_boot;\n",
        os.path.join(APP, "main.c"): '#include "m.h"\nU8 g_app;\nstatic U8 s_x;\n'
                                     'void run(U8 v) { store(v); s_x = v; }\nint main(void) { run(1U); return 0; }\n',
        os.path.join(APP, "eep.c"): '#include "m.h"\nvoid store(U8 v) { g_app = v; }\n',
        os.path.join(BOOT, "main.c"): '#include "m.h"\nU8 g_boot;\nU8 s_x;\n'
                                      'int main(void) { store(3U); s_x = 1U; return 0; }\n',
        os.path.join(BOOT, "eep.c"): '#include "m.h"\nvoid store(U8 v) { g_boot = v; }\n',
    }


def _project():
    files = _files()
    ctx = cpc.build_project_context(files, roots=[APP, BOOT])
    scopes = cpc.build_scopes(ctx, [p for p in files if p.endswith(".c")])
    return files, ctx, scopes


def test_the_write_closure_is_the_callers_build():
    _files_, _ctx, scopes = _project()
    app = scopes[os.path.join(APP, "main.c")]["effects"]["functions"]
    boot = scopes[os.path.join(BOOT, "main.c")]["effects"]["functions"]
    # one closure for the tree said both builds' `store` write g_app and g_boot
    assert set(app["store"]["writes"]) == {"g_app"} and set(boot["store"]["writes"]) == {"g_boot"}
    assert "g_app" in app["run"]["writes"] and "g_boot" not in app["run"]["writes"]


def test_one_root_keeps_one_closure():
    files = _files()
    ctx = cpc.build_project_context(files)   # no roots: one build, as before R89
    scopes = cpc.build_scopes(ctx, [p for p in files if p.endswith(".c")])
    assert set(scopes[os.path.join(APP, "main.c")]["effects"]["functions"]["store"]["writes"]) == {"g_app", "g_boot"}


def test_build_context_keeps_the_files_of_one_root():
    files = _files()
    ctx = cpc.build_project_context(files, roots=[APP, BOOT])
    one = cpc.build_context(ctx, APP)
    assert set(one["files"]) == {p for p in ctx["files"] if p.startswith(APP)}
    assert cpc.build_context(cpc.build_project_context(files), APP)["files"] == cpc.build_project_context(files)["files"]


def test_an_object_name_is_ambiguous_only_within_its_build():
    files, ctx, scopes = _project()
    provider = CalleeProvider(ctx, files, scopes, cpc.shared_parser())
    # APP's `static s_x` and BOOT's external `s_x` are two programs' objects, never one evaluation's
    assert "s_x" not in provider.ambiguous_for(os.path.join(APP, "main.c"))[0]
    main = os.path.join(APP, "main.c")
    unit = {"name": "run", "source_text": files[main], "source_path": main, "source_text_complete": True,
            "project_scope": scopes[main], "callee_provider": provider}
    r = evaluate_outputs(unit, [{"v": 9}], [["s_x", "g_app"]])[0]
    assert (r["outputs"]["s_x"].get("value"), r["outputs"]["g_app"].get("value")) == (9, 9), r["outputs"]


def test_within_one_build_a_shared_name_stays_ambiguous():
    files = _files()
    files[os.path.join(APP, "eep.c")] += "static U8 s_x;\nvoid touch(void) { s_x = 2U; }\n"
    ctx = cpc.build_project_context(files, roots=[APP, BOOT])
    scopes = cpc.build_scopes(ctx, [p for p in files if p.endswith(".c")])
    provider = CalleeProvider(ctx, files, scopes, cpc.shared_parser())
    assert "s_x" in provider.ambiguous_for(os.path.join(APP, "main.c"))[0]
    assert "s_x" not in provider.ambiguous_for(os.path.join(BOOT, "main.c"))[0]
    # the evaluation reads its own build's verdict: APP's two `static s_x` do not refuse BOOT's one object
    boot = os.path.join(BOOT, "main.c")
    unit = {"name": "main", "source_text": files[boot], "source_path": boot, "source_text_complete": True,
            "project_scope": scopes[boot], "callee_provider": provider}
    r = evaluate_outputs(unit, [{}], [["s_x", "g_boot"]])[0]
    assert (r["outputs"]["s_x"].get("value"), r["outputs"]["g_boot"].get("value")) == (1, 3), r["outputs"]


def _details():
    def f(name, root, file, calls, globals_=()):
        return {"name": name, "file": file, "source_path": os.path.join(root, file), "calls_list": list(calls),
                "inputs": [], "outputs": [], "globals_global": list(globals_), "globals_static": [], "asil": "B"}
    return {
        "A1": f("main", APP, "main.c", ["run"]),
        "A2": f("run", APP, "main.c", ["store"], ["s_x"]),
        "A3": f("store", APP, "eep.c", [], ["g_app"]),
        "B1": f("main", BOOT, "main.c", ["store"], ["s_x"]),
        "B2": f("store", BOOT, "eep.c", [], ["g_boot"]),
    }


def _flows():
    stats: dict = {}
    flows = collect_integration_flows(_details(), max_flows=None, stats_out=stats, source_roots=[APP, BOOT])
    return flows, stats


def test_each_build_has_its_own_flow_and_observables():
    flows, _stats = _flows()
    mains = {os.path.basename(f["build"]): f for f in flows if f["entry_fn"] == "main"}
    assert set(mains) == {"app", "boot"}, [(f["entry_fn"], f["build"]) for f in flows]
    boot = mains["boot"]
    seen = set(boot["input_vars"]) | set(boot["expected_vars"])
    assert "g_boot" in seen and "g_app" not in seen, seen
    assert boot["entry_source_path"] == os.path.join(BOOT, "main.c")
    app_seen = set(mains["app"]["input_vars"]) | set(mains["app"]["expected_vars"])
    assert "g_boot" not in app_seen


def test_one_root_merges_as_before():
    flows = collect_integration_flows(_details(), max_flows=None, source_roots=[APP])
    assert [f["entry_fn"] for f in flows].count("main") == 1 and all(f["build"] == "" for f in flows)


def test_a_namesake_entry_takes_no_design_id():
    flows, stats = _flows()
    itcs = generate_itc_list(flows, design_ids={"by_name": {"main": "SwUFn_0001", "run": "SwUFn_0002"}},
                             stats_out=stats)
    ids = [t["tc_id"] for t in itcs if t["entry_fn"] == "main"]
    assert len(ids) == 2 and len(set(ids)) == 2 and not any("SwUFn_0001" in i for i in ids), ids
    assert stats["design_id_ambiguous_builds"] == 2
    assert {t["build"] for t in itcs if t["entry_fn"] == "main"} == {os.path.normcase(APP), os.path.normcase(BOOT)}


def test_the_oracle_runs_both_namesake_entries():
    files, ctx, _scopes = _project()
    flows, stats = _flows()
    itcs = generate_itc_list(flows, design_ids=None, stats_out=stats)
    out = attach_integration_evidence(itcs, {"project_context": ctx, "source_files": files}, _details(),
                                      cpc.shared_parser())
    assert "entry_definition_ambiguous" not in (out.get("tc_skipped") or {}), out.get("tc_skipped")
    evaluated = {t["entry_fn"] + "@" + os.path.basename(t["build"]) for t in itcs if t.get("sub_cases")
                 and any(s.get("expected_evidence") for s in t["sub_cases"])}
    assert {"main@app", "main@boot"} <= evaluated, evaluated


def test_generate_sits_splits_builds_by_the_parsers_roots(tmp_path, monkeypatch):
    # the roots as typed (relative, trailing slash) are not how the parser wrote the functions' paths: the split uses the
    # roots the parser read (`project_context["roots"]`), so the web form's spelling cannot change the document
    import generators.sits as sits_mod

    for root, reg in (("app", "g_app"), ("boot", "g_boot")):
        d = tmp_path / root
        d.mkdir()
        (d / "m.h").write_text(f"typedef unsigned char U8;\ntypedef unsigned int U16;\nextern U8 {reg};\nvoid store(U8 v);\n",
                               encoding="utf-8")
        (d / "main.c").write_text(f'#include "m.h"\nU8 {reg};\nint main(void) {{ store(1U); return 0; }}\n',
                                  encoding="utf-8")
        (d / "eep.c").write_text(f'#include "m.h"\nvoid store(U8 v) {{ {reg} = v; }}\n', encoding="utf-8")
    seen: list = []
    real = sits_mod.generate_itc_list

    def spy(flows, *a, **k):
        seen.extend(flows)
        return real(flows, *a, **k)
    monkeypatch.setattr(sits_mod, "generate_itc_list", spy)
    monkeypatch.chdir(tmp_path)
    sits_mod.generate_sits("app/,boot/", str(tmp_path / "out.xlsx"))
    mains = [f for f in seen if f["entry_fn"] == "main"]
    assert len(mains) == 2 and len({f["build"] for f in mains}) == 2 and all(f["build"] for f in mains), \
        [(f["entry_fn"], f["build"]) for f in seen]


def test_the_pointer_target_disclosure_sums_every_build():
    # (리뷰 W2) one closure per build: reporting only the first scope's said HDPDM01 had 42 pointer writers, not 164
    from generators.pointer_flow import summarize_pointer_targets_all

    def fx(names):
        return {"functions": {n: {"pointer_write": True, "pointer_targets": {"abs": [], "params": []},
                                  "unknown_callees": ()} for n in names}}
    a, b = fx(["f1", "f2"]), fx(["g1"])
    got = summarize_pointer_targets_all([a, a, b, None])
    assert (got["pointer_writers"], got["known_targets"], got["builds"]) == (3, 3, 2)


def test_the_design_id_refusal_does_not_depend_on_the_cap():
    # (리뷰 W3) with one `main` cut by the cap, counting the selected flows gave the other one the design ID back
    flows = collect_integration_flows(_details(), max_flows=None, source_roots=[APP, BOOT])
    app_main = [f for f in flows if f["entry_fn"] == "main" and os.path.basename(f["build"]) == "app"]
    assert app_main and app_main[0]["entry_builds"] == 2
    itcs = generate_itc_list(app_main, design_ids={"by_name": {"main": "SwUFn_0001"}})
    assert "SwUFn_0001" not in itcs[0]["tc_id"]


def test_the_strategy_tree_is_drawn_with_the_flows_build():
    # (리뷰 W6) BOOT `main` calls only `store`; APP `main` calls `run` → `store`. One merged graph drew APP's tree for both
    import openpyxl

    from generators.sits import _build_calls_map, _split_by_build, _write_strategy_sheet

    parts = _split_by_build(_details(), [APP, BOOT])
    views = {b: (_build_calls_map(p), {}, {}) for b, p in parts.items() if b}
    flows = [f for f in collect_integration_flows(_details(), max_flows=None, source_roots=[APP, BOOT])
             if f["entry_fn"] == "main"]
    boot = [f for f in flows if os.path.basename(f["build"]) == "boot"]
    wb = openpyxl.Workbook()
    _write_strategy_sheet(wb, boot, _build_calls_map(_details()), {}, {}, views_by_build=views)
    cells = {str(c.value) for row in wb["2.SW Integration Strategy"].iter_rows() for c in row if c.value is not None}
    assert "store" in cells and "run" not in cells, cells


def test_a_struct_root_is_ambiguous_only_within_its_build():
    # (리뷰 W6) the struct-root check (`s.a` names `s`) is per build like the object check
    files = _files()
    hdr = "typedef struct { U8 a; U8 b; } S;\n"
    files[os.path.join(APP, "main.c")] = files[os.path.join(APP, "main.c")].replace(
        '#include "m.h"\n', '#include "m.h"\n' + hdr + "static S s_cfg;\n")
    files[os.path.join(APP, "eep.c")] += hdr + "static S s_cfg;\nvoid other(void) { s_cfg.a = 2U; }\n"
    files[os.path.join(BOOT, "main.c")] = files[os.path.join(BOOT, "main.c")].replace(
        '#include "m.h"\n', '#include "m.h"\n' + hdr + "S s_cfg;\n")
    ctx = cpc.build_project_context(files, roots=[APP, BOOT])
    scopes = cpc.build_scopes(ctx, [p for p in files if p.endswith(".c")])
    provider = CalleeProvider(ctx, files, scopes, cpc.shared_parser())
    assert "s_cfg" in provider.ambiguous_for(os.path.join(APP, "main.c"))[1]
    assert "s_cfg" not in provider.ambiguous_for(os.path.join(BOOT, "main.c"))[1]


def test_the_readiness_gate_counts_the_documents_flows():
    # (리뷰 W4) the gate measured with one merged build: both builds' `main` were one flow
    from backend.services.docgen_test_materials import _measure_sits

    merged = _measure_sits(_details(), {}, "")
    split = _measure_sits(_details(), {}, "", source_roots=[APP, BOOT])
    assert split["flows_total"] == merged["flows_total"] + 1, (merged["flows_total"], split["flows_total"])
