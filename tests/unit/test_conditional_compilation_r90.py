"""(R90) Include guards of headers a unit does not read.

``#if (_LIN_GPIO_ == 0) && !defined(_MC9S08SC4_H)`` (the LIN driver picking a derivative by the guard of the CodeWarrior
derivative header ``mc9s08sc4.h``) stayed undecided: a leading underscore is a name the implementation may define (R17).
A reserved name of include-guard form (``_X_H``) is defined by the header it guards, which a unit reading no header from
outside the tree (no ``<...>``, no toolchain header, no missing include) up to the ``#if`` has not included — with the
build's -D set read and no tree file defining it, it is undefined, recorded as an assumption (`assumed_header_guards`).
Any other reserved name, or the guard after a header from outside the tree, stays undecided.
"""
from __future__ import annotations

import os

import pytest

from generators import c_project_context as cpc
from generators.c_source_oracle import evaluate_outputs

ROOT = os.path.join(os.sep, "virt_r90")
CPROJECT = """<?xml version="1.0" encoding="UTF-8"?><cproject><storageModule moduleId="org.eclipse.cdt.core.settings">
<cconfiguration id="c1"><storageModule moduleId="cdtBuildSystem"><configuration artifactName="app" name="FLASH">
<folderInfo id="f"><toolChain id="t" superClass="com.freescale.s12z.toolchain">
<tool id="c" superClass="com.freescale.s12z.toolchain.compiler">{options}</tool></toolChain></folderInfo>
</configuration></storageModule></cconfiguration></storageModule></cproject>"""
TOOLCHAIN_DIRS = ('<option id="i" superClass="x.compiler.include" valueType="includePath"><listOptionValue '
                  'value="&quot;${MCUToolsBaseDir}/S12lisa_Support/s12lisac/include&quot;"/></option>')
CFG = "#ifndef LIN_CFG_H\n#define LIN_CFG_H\n#define _LIN_GPIO_ 0\ntypedef unsigned char U8;\ntypedef unsigned int U16;\n#endif\n"


def _unit(before: str = "", condition: str = "(_LIN_GPIO_ == 0) && !defined(_MC9S08SC4_H)", after: str = "") -> str:
    return (f'#include "lin_cfg.h"\n{before}U8 g_o;\n#if {condition}\nvoid f(void) {{ g_o = 1U; }}\n#endif\n'
            f"{after}void h(void) {{ g_o = 2U; }}\n")


def _scope(unit: str, options: str = "", with_build: bool = True, extra: dict | None = None):
    files = {os.path.join(ROOT, "lin_cfg.h"): CFG, os.path.join(ROOT, "a.c"): unit, **(extra or {})}
    cp = {os.path.join(ROOT, ".cproject"): CPROJECT.format(options=options)} if with_build else {}
    ctx = cpc.build_project_context(files, cpc.detect_build_config(cp), roots=[ROOT])
    return cpc.build_scopes(ctx, [os.path.join(ROOT, "a.c")])[os.path.join(ROOT, "a.c")]


def _state_of_f(scope: dict, unit: str) -> str | None:
    return scope["main_file_states"].get(unit.encode().index(b"void f"))


def test_a_guard_no_tree_file_defines_is_undefined_in_a_unit_reading_only_the_tree():
    unit = _unit()
    scope = _scope(unit)
    assert _state_of_f(scope, unit) == "active"
    assert scope["assumed_header_guards"] == ["_MC9S08SC4_H"]
    assert "_MC9S08SC4_H" in scope["assumed_undefined"]   # every reader of the unit's assumptions sees it
    said = [a for a in scope["pp_assumptions"] if "_MC9S08SC4_H" in a]
    assert len(said) == 1 and "include guards" in said[0] and "outside the tree" in said[0]


@pytest.mark.parametrize("before", [
    "#include <mc9s12zvl64.h>\n",    # a system header (the derivative header) may define any guard
    '#include "hidef.h"\n',          # a toolchain header (found nowhere in the tree, toolchain dirs listed)
])
def test_a_header_from_outside_the_tree_before_the_test_keeps_it_undecided(before):
    unit = _unit(before=before)
    scope = _scope(unit, options=TOOLCHAIN_DIRS)
    assert _state_of_f(scope, unit) == "unknown"
    assert scope["assumed_header_guards"] == []


def test_a_missing_include_keeps_it_undecided():
    unit = _unit(before='#include "nowhere.h"\n')
    scope = _scope(unit)   # no toolchain include directories: a missing project header, a gap
    assert scope["missing_includes"] == ["nowhere.h"] and _state_of_f(scope, unit) == "unknown"


def test_a_header_from_outside_the_tree_after_the_test_does_not_reach_back():
    unit = _unit(after="#include <mc9s12zvl64.h>\n")
    scope = _scope(unit)
    assert _state_of_f(scope, unit) == "active" and scope["assumed_header_guards"] == ["_MC9S08SC4_H"]


def test_without_complete_build_evidence_it_stays_undecided():
    unit = _unit()
    assert _state_of_f(_scope(unit, with_build=False), unit) == "unknown"
    # a -U / quoted -D the reading cannot account for: incomplete as well
    opts = '<option id="o" name="Other Flags" superClass="x.compiler.general.otherFlags" value="-UFOO"/>'
    scope = _scope(unit, options=opts)
    assert scope["build_defines"]["complete"] is False and _state_of_f(scope, unit) == "unknown"


def test_a_build_define_of_the_guard_is_the_build_s():
    unit = _unit()
    opts = '<option id="o" name="Other Flags" superClass="x.compiler.general.otherFlags" value="-D_MC9S08SC4_H"/>'
    scope = _scope(unit, options=opts)
    assert _state_of_f(scope, unit) is None   # defined: ``!defined`` false, f not compiled
    assert scope["assumed_header_guards"] == []


def test_a_tree_header_s_guard_follows_its_include_as_before():
    hdr = "#ifndef _MC9S08SC4_H\n#define _MC9S08SC4_H\n#endif\n"
    extra = {os.path.join(ROOT, "mc9s08sc4.h"): hdr}
    included = _unit(before='#include "mc9s08sc4.h"\n')
    scope = _scope(included, extra=extra)
    assert _state_of_f(scope, included) is None and scope["assumed_header_guards"] == []
    not_included = _unit()
    scope = _scope(not_included, extra=extra)
    # a name the tree defines and the unit did not include: 0, as before R90 — not this round's assumption
    assert _state_of_f(scope, not_included) == "active" and scope["assumed_header_guards"] == []


@pytest.mark.parametrize("condition", [
    "!defined(__MISRA__)", "!defined(_lint)", "!defined(__MC9S08SC4_H)", "!defined(_mc9s08sc4_h)",
    "!defined(_MC9S08SC4_HX)", "!defined(__ALIGN_STACK_OPT__)", "!defined(_MC9S08SC4)",
])
def test_other_reserved_names_stay_undecided(condition):
    unit = _unit(condition=condition)
    scope = _scope(unit)
    assert _state_of_f(scope, unit) == "unknown" and scope["assumed_header_guards"] == []


def test_the_guard_form():
    for name in ("_MC9S08SC4_H", "_MC9S12ZVML128_H", "_MM9Z1J638_H", "_LIN_CFG_H_", "_A_H"):
        assert cpc._header_guard_name(name), name
    for name in ("__MC9S08SC4_H", "_mc9s08sc4_h", "_H", "_MC9S08SC4", "MC9S08SC4_H", "__ALIGN_STACK_OPT__", "_lint",
                 "_A_HH", "_A_H__"):
        assert not cpc._header_guard_name(name), name


def test_an_include_the_file_level_walk_does_not_follow_keeps_it_undecided():
    # an #include in a function body (a stray directive) may read a header from outside the tree
    unit = _unit(before='void g(void) {\n#include "body_part.h"\n}\n')
    scope = _scope(unit, extra={os.path.join(ROOT, "body_part.h"): "g_o = 3U;\n"})
    assert scope["body_includes"] == ["body_part.h"]
    assert _state_of_f(scope, unit) == "unknown" and scope["assumed_header_guards"] == []


BODY = ('#include "lin_cfg.h"\n{before}U8 g_o;\nvoid f(void) {{\n#if !defined(_MC9S08SC4_H)\n g_o = 1U;\n#else\n'
        ' g_o = 2U;\n#endif\n}}\n')


def test_a_function_body_condition_on_a_guard_is_decided_and_carried_by_the_value():
    unit = BODY.format(before="")
    scope = _scope(unit)
    assert "_MC9S08SC4_H" in scope["assumed_undefined_body"] and scope["assumed_header_guards"] == ["_MC9S08SC4_H"]
    rec = {"name": "f", "source_text": unit, "source_path": os.path.join(ROOT, "a.c"), "source_text_complete": True,
           "project_scope": scope}
    r = evaluate_outputs(rec, [{}], [["g_o"]])[0]
    assert r["outputs"]["g_o"]["value"] == 1 and "_MC9S08SC4_H" in r["assumed_undefined"]
    # with a system header in the unit (the end-of-unit table, as body verdicts read it): undecided
    unit = BODY.format(before="#include <mc9s12zvl64.h>\n")
    scope = _scope(unit)
    assert "_MC9S08SC4_H" not in scope["assumed_undefined_body"]
    r = evaluate_outputs({**rec, "source_text": unit, "project_scope": scope}, [{}], [["g_o"]])[0]
    assert r["status"] == "unsupported" and r["reason"] == "conditional_compilation_unresolved"


@pytest.mark.parametrize("include,options", [
    ("#include <mc9s12zvl64.h>", ""),          # a system header, only inside a function body
    ('#include "hidef.h"', TOOLCHAIN_DIRS),    # a toolchain header, only inside a function body
])
def test_a_header_from_outside_the_tree_read_only_in_a_function_body_turns_the_rule_off_for_body_conditions(
        include, options):
    unit = ('#include "lin_cfg.h"\nU8 g_o;\nvoid g(void) {\n' + include + "\n}\n"
            + BODY.format(before="").split("U8 g_o;\n", 1)[1])
    scope = _scope(unit, options=options)
    assert scope["body_includes"] == [include.split()[1].strip('<>"')]
    assert scope["system_includes"] == [] and scope["toolchain_includes"] == []   # the file-level walk never met it
    assert cpc.body_verdict(scope, "if", "!defined(_MC9S08SC4_H)") is None
    # no assumption is recorded for it — not in the unit's body names, not among the include guards
    assert "_MC9S08SC4_H" not in scope["assumed_undefined_body"] and scope["assumed_header_guards"] == []
    rec = {"name": "f", "source_text": unit, "source_path": os.path.join(ROOT, "a.c"), "source_text_complete": True,
           "project_scope": scope}
    r = evaluate_outputs(rec, [{}], [["g_o"]])[0]
    assert r["status"] == "unsupported" and r["reason"] == "conditional_compilation_unresolved"


def test_a_toolchain_header_before_the_function_turns_the_rule_off_for_its_body_conditions():
    unit = BODY.format(before='#include "hidef.h"\n')
    scope = _scope(unit, options=TOOLCHAIN_DIRS)
    assert scope["toolchain_includes"] == ["hidef.h"] and scope["missing_includes"] == []
    assert "_MC9S08SC4_H" not in scope["assumed_undefined_body"] and scope["assumed_header_guards"] == []
    rec = {"name": "f", "source_text": unit, "source_path": os.path.join(ROOT, "a.c"), "source_text_complete": True,
           "project_scope": scope}
    r = evaluate_outputs(rec, [{}], [["g_o"]])[0]
    assert r["status"] == "unsupported" and r["reason"] == "conditional_compilation_unresolved"


def test_the_assumption_is_summarized_and_disclosed():
    from report_gen.generation_disclosures import build_disclosures
    scope = _scope(_unit())
    block = cpc.summarize_build_assumptions([scope])
    assert block["units_with_header_guards"] == 1 and block["header_guard_names"] == ["_MC9S08SC4_H"]
    assert "_MC9S08SC4_H" in block["assumed_undefined_names"]
    item = {i["key"]: i for i in build_disclosures("sits", {"integration_oracle": {"build_assumptions": block}})}
    note = item["sits_build_assumptions"]["note"]
    assert "include 가드" in note and "_MC9S08SC4_H" in note


HD_ROOTS = [r"D:\Project\Ados\PDS64_RD", r"D:\Project\Ados\PDS64_FBL"]


@pytest.mark.skipif(not all(os.path.isdir(r) for r in HD_ROOTS), reason="HDPDM01 source tree not on this machine")
def test_hdpdm01_lin_units_decide_their_derivative_guards():
    from pathlib import Path

    from scripts.reference_alignment import _load_source
    _texts, context, _unread = _load_source([Path(r) for r in HD_ROOTS])
    lin = os.path.join(HD_ROOTS[0], "Sources", "LIN", "LIN_driver")
    units = [os.path.join(lin, "transport", "lin_commontl_proto.c"), os.path.join(lin, "transport", "lin_commontl_api.c"),
             os.path.join(lin, "coreapi", "lin_common_proto.c"),
             os.path.join(lin, "diagnostic", "lin_diagnostic_service.c")]
    units = [str(Path(u).resolve()) for u in units]
    scopes = cpc.build_scopes(context, units)
    for path in units:
        scope = scopes[path]
        assert scope["system_includes"] == [] and scope["toolchain_includes"] == [] and scope["missing_includes"] == []
        assert not [p for p, s in scope["main_file_states"].items() if s == cpc._UNKNOWN], path
        assert "_MC9S08SC4_H" in scope["assumed_header_guards"], path
