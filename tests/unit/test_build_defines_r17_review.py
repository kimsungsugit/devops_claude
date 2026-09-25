"""(R17 review round 1) The build configuration is evidence only when every way it could define a macro is accounted
for — anything else leaves names undecided (fail closed). Also: function-body ``#if`` and the disclosure path."""
from __future__ import annotations

import os

import pytest

from generators import c_project_context as cpc
from generators.c_source_oracle import evaluate_outputs


def _cp(compiler_opts="", tool_extra="", builder="", after_folder="", configs=1):
    config = (f'<configuration name="FLASH"><folderInfo id="f" resourcePath=""><toolChain id="t" superClass="tc">'
              f'<builder id="b" superClass="x.builder" {builder}/>'
              f'<tool id="c" superClass="com.freescale.s12z.toolchain.compiler">{compiler_opts}</tool>{tool_extra}'
              f'</toolChain></folderInfo>{after_folder}</configuration>')
    body = "".join(f'<cconfiguration id="c{i}"><storageModule moduleId="cdtBuildSystem">{config}</storageModule>'
                   f'</cconfiguration>' for i in range(configs))
    return f'<cproject><storageModule moduleId="org.eclipse.cdt.core.settings">{body}</storageModule></cproject>'


def _flags(value):
    return f'<option id="o" name="Other Flags" superClass="x.compiler.general.otherFlags" value="{value}"/>'


def _list(name, super_class, value_type, *values):
    items = "".join(f'<listOptionValue builtIn="false" value="{v}"/>' for v in values)
    return f'<option id="l" name="{name}" superClass="{super_class}" valueType="{value_type}">{items}</option>'


@pytest.mark.parametrize("text,reason", [
    (_cp(_list("Undefined symbols (-U)", "x.compiler.input.undefinedSymbols", "undefDefinedSymbols", "FOO")),
     "undefine_option"),
    (_cp(after_folder='<fileInfo id="fi" resourcePath="Sources/a.c"><tool id="c2" superClass="x.compiler">'
                      + _list("Defined Macros", "x.compiler.definedSymbols", "definedSymbols", "ONLY_A")
                      + "</tool></fileInfo>"), "resource_scoped_options"),
    (_cp(after_folder='<folderInfo id="fo" resourcePath="Sources/LIN"><toolChain id="t2" superClass="x">'
                      '<tool id="c3" superClass="x.compiler">' + _list("Defined Macros", "x.compiler.definedSymbols",
                                                                      "definedSymbols", "LIN_ONLY")
                      + "</tool></toolChain></folderInfo>"), "resource_scoped_options"),
    (_cp(_flags("&quot;-DFOO&quot; -Os")), "compiler_flag_unreadable"),
    (_cp(_flags("-D${BUILD_VARIANT}")), "compiler_flag_indirection"),   # a build variable (round 3)
    (_cp(_flags("-DVER=&quot;1 2&quot;")), "compiler_flag_unreadable"),
    (_cp(_flags("-D FOO")), "compiler_flag_unreadable"),
    (_cp(_flags("-DFOO -UFOO")), "compiler_flag_unreadable"),
    (_cp(_flags("-include cfg_variant.h")), "compiler_flag_unreadable"),
    (_cp(_list("Additional Include Files", "x.compiler.input.addIncl", "stringList", "variant.h")),
     "forced_include_option"),
    (_cp(builder='managedBuildOn="false"'), "unmanaged_build"),
    (_cp(tool_extra='<tool id="pp" superClass="com.freescale.s12z.toolchain.preprocessor">'
                    + _list("Defined Macros", "x.preprocessor.definedSymbols", "definedSymbols", "PP_ONLY") + "</tool>"),
     "preprocessor_tool_options"),
    ("<cproject><broken", "cproject_unparsable"),
])
def test_what_the_reading_cannot_account_for_is_not_evidence(text, reason):
    rec = cpc._build_defines(text)
    assert rec["complete"] is False and rec["reason"] == reason


def test_what_it_can_read_is_the_define_set():
    ok = cpc._build_defines(_cp(_list("Defined Macros", "x.compiler.definedSymbols", "definedSymbols", "A", "B=2")
                                + _flags("-DC -DD= -Os -double_size=8")
                                + '<option id="g" name="Generate debug symbols" superClass="x.compiler.debugSymbols" '
                                  'value="true" valueType="boolean"/>',
                                tool_extra='<tool id="a" superClass="com.freescale.s12z.toolchain.assembler">'
                                           + _list("Defined Symbols", "x.asm.definedSymbols", "definedSymbols", "ASM")
                                           + "</tool>"))
    # the assembler's symbols are not the C compiler's; ``-double_size`` is no ``-D``; ``-DD=`` is an empty body
    assert ok == {"defines": {"A": "1", "B": "2", "C": "1", "D": ""}, "complete": True, "reason": ""}


def test_configurations_that_disagree_are_not_evidence():
    text = _cp(configs=2).replace('<tool id="c" superClass="com.freescale.s12z.toolchain.compiler"></tool>',
                                  '<tool id="c" superClass="com.freescale.s12z.toolchain.compiler">' + _flags("-DX")
                                  + "</tool>", 1)
    assert cpc._build_defines(text)["reason"] == "configurations_disagree"
    assert cpc._build_defines(_cp(configs=2))["complete"] is True   # two configurations, same (empty) set


ROOT = os.path.join(os.sep, "virt_r17r")
HDR = "#ifndef CFG_H\n#define CFG_H\ntypedef unsigned char U8;\ntypedef unsigned int U16;\n#endif\n"
UNIT = '#include "cfg.h"\nU8 g_o;\nvoid f(void) {\n#ifdef TESTCODE_FOR_JIG\n g_o = 1U;\n#else\n g_o = 2U;\n#endif\n}\n'


def _ctx(roots, cprojects, files):
    return cpc.build_project_context(files, cpc.detect_build_config(cprojects), roots=roots)


def test_a_function_body_condition_follows_the_build_evidence_and_says_so():
    files = {os.path.join(ROOT, "cfg.h"): HDR, os.path.join(ROOT, "a.c"): UNIT}
    ctx = _ctx([ROOT], {os.path.join(ROOT, ".cproject"): _cp()}, files)
    scope = cpc.build_scopes(ctx, [os.path.join(ROOT, "a.c")])[os.path.join(ROOT, "a.c")]
    unit = {"name": "f", "source_text": UNIT, "source_path": os.path.join(ROOT, "a.c"), "source_text_complete": True,
            "project_scope": scope}
    r = evaluate_outputs(unit, [{}], [["g_o"]])[0]
    assert r["outputs"]["g_o"]["value"] == 2
    assert r["assumed_undefined"] == ["TESTCODE_FOR_JIG"]
    assert any("TESTCODE_FOR_JIG" in a for a in r["assumptions"])
    # without build evidence the body condition stays undecided, as before R17
    ctx = _ctx([ROOT], {}, files)
    scope = cpc.build_scopes(ctx, [os.path.join(ROOT, "a.c")])[os.path.join(ROOT, "a.c")]
    r = evaluate_outputs({**unit, "project_scope": scope}, [{}], [["g_o"]])[0]
    assert r["status"] == "unsupported" and r["reason"] == "conditional_compilation_unresolved"


def test_each_root_is_judged_by_its_own_build_and_a_unit_outside_every_root_by_none():
    app, boot, other = (os.path.join(ROOT, x) for x in ("app", "boot", "other"))
    files = {os.path.join(d, "cfg.h"): HDR for d in (app, boot, other)}
    files.update({os.path.join(d, "a.c"): UNIT for d in (app, boot, other)})
    ctx = _ctx([app, boot], {os.path.join(app, ".cproject"): _cp(),
                             os.path.join(boot, ".cproject"): _cp(_flags("-DTESTCODE_FOR_JIG"))}, files)
    scopes = cpc.build_scopes(ctx, [os.path.join(d, "a.c") for d in (app, boot, other)])
    assert scopes[os.path.join(app, "a.c")]["build_defines"]["defines"] == {}
    assert scopes[os.path.join(boot, "a.c")]["build_defines"]["defines"] == {"TESTCODE_FOR_JIG": "1"}
    assert scopes[os.path.join(other, "a.c")]["build_defines"]["complete"] is False


def test_implementation_name_families_stay_undecided():
    for name in ("_lint", "__MISRA__", "int8_t", "EXIT_SUCCESS", "SIGINT", "PRIu8", "ENOMEM", "FLT_EPSILON", "NDEBUG",
                 "EnableInterrupts"):
        assert cpc._implementation_may_define(name), name
    for name in ("TESTCODE_FOR_VEHICLE", "S12ZVL64_MCU", "RELEASE_BUILD", "TPE_Float"):
        assert not cpc._implementation_may_define(name), name


def test_the_assumption_is_disclosed_for_suts_and_sits():
    from report_gen.generation_disclosures import build_disclosures
    block = cpc.summarize_build_assumptions([
        {"build_defines": {"complete": True}, "assumed_undefined": ["TESTCODE_FOR_VEHICLE", "S12ZVL64_MCU"]},
        {"build_defines": {"complete": False, "reason": "unmanaged_build"}, "assumed_undefined": []}])
    assert block == {"units": 2, "units_with_complete_build_evidence": 1, "incomplete_reasons": {"unmanaged_build": 1},
                     "units_with_assumed_undefined": 1, "assumed_undefined_names": ["S12ZVL64_MCU", "TESTCODE_FOR_VEHICLE"],
                     "assumed_undefined_total": 2}
    suts = {i["key"]: i for i in build_disclosures("suts", {"build_assumptions": block})}["suts_build_assumptions"]
    assert suts["value"] == "완전한 빌드 설정 1/2 unit · 정의 없음으로 본 이름 2개"
    assert "TESTCODE_FOR_VEHICLE" in suts["note"] and "unmanaged_build 1" in suts["note"] and "C11 6.10.1p4" in suts["note"]
    sits = {i["key"] for i in build_disclosures("sits", {"integration_oracle": {"status": "evaluated",
                                                                               "build_assumptions": block}})}
    assert "sits_build_assumptions" in sits
    assert "suts_build_assumptions" not in {i["key"] for i in build_disclosures("suts", {})}   # old outputs: no item


# ── round 2 ──────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,reason", [
    (_cp().replace('<tool id="c" superClass="com.freescale.s12z.toolchain.compiler"></tool>', ""),
     "configuration_without_compiler_tool"),
    (_cp('<option id="d" name="Defined Macros" superClass="x.compiler.definedSymbols" valueType="definedSymbols" '
         'value="A"/>'), "define_option_value_unreadable"),
    (_cp(_list("Defined Macros", "x.compiler.definedSymbols", "definedSymbols", "V=a b")), "define_value_unreadable"),
    (_cp(_list("Defined Macros", "x.compiler.definedSymbols", "definedSymbols", "1BAD")), "define_value_unreadable"),
    (_cp().replace('</folderInfo>', '</folderInfo><folderInfo id="f2" resourcePath=""><toolChain id="t3" superClass="x">'
                                    '</toolChain></folderInfo>'), "several_project_folder_options"),
    (_cp().replace('<builder id="b"', '<option id="tco" superClass="x.toolchain.opt" value="-DX"/><builder id="b"'),
     "toolchain_options"),
    (_cp().replace('superClass="com.freescale.s12z.toolchain.compiler">',
                   'superClass="com.freescale.s12z.toolchain.compiler" commandLinePattern="${COMMAND} -DHID ${INPUTS}">'),
     "tool_command_flags"),
    (_cp(_list("D options", "x.compiler.input.dOpts", "stringList", "BARE")), "compiler_list_option_unrecognized"),
    (_cp(_flags("-Env&quot;COMPOPTIONS=-DX&quot;")), "compiler_flag_indirection"),
    (_cp(_flags("-Prod=project.ini")), "compiler_flag_indirection"),
    (_cp(_flags("@opts.txt")), "compiler_flag_indirection"),
])
def test_round2_what_the_reading_cannot_account_for(text, reason):
    rec = cpc._build_defines(text)
    assert rec["complete"] is False and rec["reason"] == reason


def test_a_unit_outside_the_only_root_gets_no_configuration():
    app = os.path.join(ROOT, "app1")
    other = os.path.join(ROOT, "else1")
    files = {os.path.join(app, "cfg.h"): HDR, os.path.join(app, "a.c"): UNIT,
             os.path.join(other, "cfg.h"): HDR, os.path.join(other, "a.c"): UNIT}
    ctx = _ctx([app], {os.path.join(app, ".cproject"): _cp()}, files)
    scopes = cpc.build_scopes(ctx, [os.path.join(app, "a.c"), os.path.join(other, "a.c")])
    assert scopes[os.path.join(app, "a.c")]["build_defines"]["complete"] is True
    assert scopes[os.path.join(other, "a.c")]["build_defines"]["complete"] is False


def test_body_level_names_reach_the_scope_the_summary_and_the_mcdc_report():
    from generators.mcdc_design import build_mcdc_design
    unit_text = ('#include "cfg.h"\nU8 g_o;\nU8 g_a;\nvoid f(void) {\n#ifdef CRC_DEBUG_ENABLE\n if (g_a > 1U) { g_o = 1U; }\n'
                 '#endif\n if (g_a > 2U) { g_o = 2U; }\n}\n')
    files = {os.path.join(ROOT, "cfg.h"): HDR, os.path.join(ROOT, "a.c"): unit_text}
    ctx = _ctx([ROOT], {os.path.join(ROOT, ".cproject"): _cp()}, files)
    scope = cpc.build_scopes(ctx, [os.path.join(ROOT, "a.c")])[os.path.join(ROOT, "a.c")]
    assert scope["assumed_undefined"] == [] and scope["assumed_undefined_body"] == ["CRC_DEBUG_ENABLE"]
    block = cpc.summarize_build_assumptions([scope, scope])   # the same scope twice counts once
    assert block["units"] == 1 and block["assumed_undefined_names"] == ["CRC_DEBUG_ENABLE"]
    report = build_mcdc_design({"name": "f", "source_text": unit_text, "source_path": os.path.join(ROOT, "a.c"),
                                "source_text_complete": True, "project_scope": scope, "input_vars": ["g_a"]})
    assert report.get("assumed_undefined") == ["CRC_DEBUG_ENABLE"]


def test_file_level_names_are_in_every_derived_value_and_counted():
    from generators.test_evidence import apply_sequence_evidence, summarize_expected_evidence
    hdr = HDR.replace("#endif\n", "#ifdef VARIANT_B\n#define GAIN 3U\n#else\n#define GAIN 2U\n#endif\n#endif\n")
    unit_text = '#include "cfg.h"\nU8 g_o;\nU8 g_a;\nvoid f(void) { g_o = (U8)(g_a * GAIN); }\n'
    files = {os.path.join(ROOT, "cfg.h"): hdr, os.path.join(ROOT, "a.c"): unit_text}
    ctx = _ctx([ROOT], {os.path.join(ROOT, ".cproject"): _cp()}, files)
    scope = cpc.build_scopes(ctx, [os.path.join(ROOT, "a.c")])[os.path.join(ROOT, "a.c")]
    unit = {"name": "f", "source_text": unit_text, "source_path": os.path.join(ROOT, "a.c"), "source_text_complete": True,
            "project_scope": scope}
    seqs = apply_sequence_evidence(unit, [{"inputs": {"g_a": 3}, "expected": {"g_o": "x"}}])
    item = seqs[0]["expected_evidence"]["g_o"]
    assert seqs[0]["expected"]["g_o"] == 6 and item["assumed_undefined"] == ["VARIANT_B"]
    assert any("VARIANT_B" in a for a in item["assumptions"])
    assert summarize_expected_evidence(seqs)["derived_on_assumed_undefined"] == 1


def test_a_callee_units_names_and_a_binding_choice_reach_the_callers_record():
    from generators.integration_oracle import CalleeProvider
    b = '#include "cfg.h"\n#ifdef SIDE_B\n#define K 7U\n#else\n#define K 5U\n#endif\nU8 get_k(void) { return K; }\n'
    c = '#include "cfg.h"\n#ifdef OTHER_EXCLUDER\nU8 other(void) { return 1U; }\n#endif\n'
    d = '#include "cfg.h"\nU8 other(void) { return 9U; }\n'
    a = ('#include "cfg.h"\nU8 g_o;\nU8 g_p;\nU8 get_k(void);\nU8 other(void);\n'
         'void f(void) { g_o = get_k(); g_p = other(); }\n')
    files = {os.path.join(ROOT, "cfg.h"): HDR, **{os.path.join(ROOT, n): t for n, t in
                                                  (("a.c", a), ("b.c", b), ("c.c", c), ("d.c", d))}}
    ctx = _ctx([ROOT], {os.path.join(ROOT, ".cproject"): _cp()}, files)
    scopes = cpc.build_scopes(ctx, [p for p in files if p.endswith(".c")])
    unit = {"name": "f", "source_text": a, "source_path": os.path.join(ROOT, "a.c"), "source_text_complete": True,
            "project_scope": scopes[os.path.join(ROOT, "a.c")],
            "callee_provider": CalleeProvider(ctx, files, scopes, cpc.shared_parser())}
    r = evaluate_outputs(unit, [{}], [["g_o", "g_p"]])[0]
    assert (r["outputs"]["g_o"]["value"], r["outputs"]["g_p"]["value"]) == (5, 9)
    # get_k's unit decided SIDE_B; other() bound to d.c because c.c's #ifdef OTHER_EXCLUDER was taken as 0
    assert {"SIDE_B", "OTHER_EXCLUDER"} <= set(r["assumed_undefined"])


def test_no_item_when_no_unit_had_a_scope():
    from report_gen.generation_disclosures import build_disclosures
    empty = cpc.summarize_build_assumptions([])
    assert "suts_build_assumptions" not in {i["key"] for i in build_disclosures("suts", {"build_assumptions": empty})}


# ── round 3 ──────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("flags", ["--define=FOO", "--define-macro FOO", "-Wp,-DFOO", "/DFOO", "${EXTRA_FLAGS}",
                                   "--include=x.h", "$(EXTRA)"])
def test_round3_other_spellings_are_not_evidence(flags):
    rec = cpc._build_defines(_cp(_flags(flags)))
    assert rec["complete"] is False and rec["reason"] == "compiler_flag_indirection"


def test_round3_cpp_tool_defines_do_not_reach_c_and_c_tools_must_agree():
    cpp = '<tool id="x" superClass="com.freescale.s12z.toolchain.cpp.compiler">' + _flags("-DCPP_ONLY") + "</tool>"
    assert cpc._build_defines(_cp(tool_extra=cpp)) == {"defines": {}, "complete": True, "reason": ""}
    other_c = '<tool id="y" superClass="x.c.compiler.second">' + _flags("-DSECOND") + "</tool>"
    assert cpc._build_defines(_cp(tool_extra=other_c))["reason"] == "compiler_tools_disagree"


def test_round3_cdt_placeholders_in_a_tool_command_are_the_tools_own():
    ok = _cp().replace('superClass="com.freescale.s12z.toolchain.compiler">',
                       'superClass="com.freescale.s12z.toolchain.compiler" command="&quot;${S12Z_ToolsDir}/mwcc&quot;" '
                       'commandLinePattern="${COMMAND} -c ${FLAGS} ${OUTPUT_FLAG} ${OUTPUT_PREFIX}${OUTPUT} ${INPUTS}">')
    assert cpc._build_defines(ok)["complete"] is True
    bad = ok.replace("${INPUTS}", "${EXTRA_FLAGS} ${INPUTS}")
    assert cpc._build_defines(bad)["reason"] == "tool_command_flags"


def test_round3_a_name_reached_through_a_macro_in_a_body_condition_is_disclosed():
    hdr = HDR.replace("#endif\n", "#define FEATURE_X (CFG_B)\n#endif\n")
    unit_text = '#include "cfg.h"\nU8 g_o;\nvoid f(void) {\n#if FEATURE_X\n g_o = 1U;\n#else\n g_o = 2U;\n#endif\n}\n'
    files = {os.path.join(ROOT, "cfg.h"): hdr, os.path.join(ROOT, "a.c"): unit_text}
    ctx = _ctx([ROOT], {os.path.join(ROOT, ".cproject"): _cp()}, files)
    scope = cpc.build_scopes(ctx, [os.path.join(ROOT, "a.c")])[os.path.join(ROOT, "a.c")]
    assert scope["assumed_undefined_body"] == ["CFG_B"]
    assert cpc.summarize_build_assumptions([scope])["assumed_undefined_names"] == ["CFG_B"]


def test_round3_the_counter_is_in_the_suts_disclosure():
    from report_gen.generation_disclosures import build_disclosures
    qr = {"expected_evidence_summary": {"derived": 10, "unknown": 0, "proposed": 0, "unrecorded": 0, "total": 10,
                                        "derived_assigned": 10, "derived_unchanged_input": 0,
                                        "derived_in_stubbed_sequence": 0, "derived_on_assumed_undefined": 4}}
    items = {i["key"]: i for i in build_disclosures("suts", qr)}
    assert "4칸은 빌드 설정 증거로" in items["suts_expected_evidence"]["note"]
