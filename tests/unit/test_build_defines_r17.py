"""(R17) Build-configuration evidence for macro names: a name neither the tree nor the build (its ``.cproject`` -D set)
defines is undefined in ``#if`` — unless the implementation may define it (a leading underscore, a standard name) or an
include is missing. Without complete build evidence nothing changes (undecided, as before)."""
from __future__ import annotations

import os

from generators import c_project_context as cpc

ROOT = os.path.join(os.sep, "virt_r17")
CPROJECT = """<?xml version="1.0" encoding="UTF-8"?><cproject><storageModule moduleId="org.eclipse.cdt.core.settings">
<cconfiguration id="c1"><storageModule moduleId="cdtBuildSystem"><configuration artifactName="app" name="FLASH">
<folderInfo id="f"><toolChain id="t" superClass="com.freescale.s12z.toolchain">
<tool id="c" superClass="com.freescale.s12z.toolchain.compiler">{options}</tool></toolChain></folderInfo>
</configuration></storageModule></cconfiguration></storageModule>
<storageModule moduleId="refreshScope"><configuration configurationName="FLASH"><resource name="" type="4"/></configuration>
</storageModule></cproject>"""
HDR = """#ifndef CFG_H
#define CFG_H
#ifdef TESTCODE_FOR_VEHICLE
#define SCI_VERSION 5
#else
#define SCI_VERSION 6
#endif
#ifdef _lint
#define LINT_ONLY 1
#endif
#ifdef int8_t
#define HAVE_INT8 1
#endif
typedef unsigned char U8;
typedef unsigned int U16;
#endif
"""
UNIT = '#include "cfg.h"\nU8 g_o;\nvoid f(void) { g_o = (U8)SCI_VERSION; }\n'


def _scope(options="", with_build=True, unit=UNIT, header=HDR):
    files = {os.path.join(ROOT, "cfg.h"): header, os.path.join(ROOT, "a.c"): unit}
    cp = {os.path.join(ROOT, ".cproject"): CPROJECT.format(options=options)} if with_build else {}
    ctx = cpc.build_project_context(files, cpc.detect_build_config(cp), roots=[ROOT])
    return cpc.build_scopes(ctx, [os.path.join(ROOT, "a.c")])[os.path.join(ROOT, "a.c")]


def test_build_without_defines_makes_tree_undefined_names_zero():
    scope = _scope()
    assert scope["build_defines"]["complete"] is True and scope["build_defines"]["defines"] == {}
    assert scope["macro_status"].get("SCI_VERSION") == "active"
    assert scope["constants"]["SCI_VERSION"]["value"] == 6
    assert scope["assumed_undefined"] == ["TESTCODE_FOR_VEHICLE"]
    assert any("TESTCODE_FOR_VEHICLE" in a for a in scope["pp_assumptions"])


def test_implementation_names_stay_undecided():
    scope = _scope()
    # ``#ifdef _lint`` / ``#ifdef int8_t``: an implementation (lint, <stdint.h>) may define them — never assumed
    assert scope["macro_status"].get("LINT_ONLY") == "unknown"
    assert scope["macro_status"].get("HAVE_INT8") == "unknown"


def test_a_define_in_the_build_is_used():
    opt = ('<option id="d" superClass="com.freescale.s12z.toolchain.compiler.input.definedSymbols" valueType="definedSymbols">'
           '<listOptionValue builtIn="false" value="TESTCODE_FOR_VEHICLE"/></option>')
    scope = _scope(opt)
    assert scope["build_defines"]["defines"] == {"TESTCODE_FOR_VEHICLE": "1"}
    assert scope["constants"]["SCI_VERSION"]["value"] == 5 and scope["assumed_undefined"] == []


def test_a_define_in_other_flags_is_used():
    opt = '<option id="o" name="Other Flags" superClass="com.freescale.s12z.toolchain.compiler.general.otherFlags" value="-DTESTCODE_FOR_VEHICLE -Os"/>'
    assert _scope(opt)["constants"]["SCI_VERSION"]["value"] == 5


def test_without_build_evidence_nothing_changes():
    scope = _scope(with_build=False)
    assert scope["macro_status"].get("SCI_VERSION") == "unknown" and scope["assumed_undefined"] == []


def test_configurations_that_disagree_are_not_evidence():
    two = CPROJECT.replace("</cconfiguration>", "</cconfiguration>" + CPROJECT.split("<storageModule moduleId=\"org.eclipse.cdt.core.settings\">")[1]
                           .split("</storageModule>\n<storageModule moduleId=\"refreshScope\">")[0].replace(
                               "{options}", '<option id="o" name="Other Flags" superClass="x.compiler.general.otherFlags" value="-DA_B"/>'))
    rec = cpc._build_defines(two.format(options=""))
    assert rec["complete"] is False and rec["reason"] == "configurations_disagree"


def test_a_missing_include_keeps_names_undecided():
    unit = '#include "cfg.h"\n#include "absent.h"\n#ifdef LATE\n#define V 1\n#else\n#define V 2\n#endif\nU8 g_o;\n'
    scope = _scope(unit=unit)
    assert scope["macro_status"].get("V") == "unknown"
