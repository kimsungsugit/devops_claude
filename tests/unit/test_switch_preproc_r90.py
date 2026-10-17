"""(R90) A conditional group holding ``case`` labels inside a ``switch`` body.

``switch (sid) { #if (LIN_PROTOCOL == PROTOCOL_21) case …: … #endif default: … }`` (HDPDM01 ``lin_tl_make_slaveres_pdu``,
``lin_tl_attach_service``) was refused whole (`switch_body_statement_outside_case`, 1,617 SITS cells). The switch now reads
its body as the compiler does: the arm the unit's preprocessing decides (`cpc.pp_condition`, as for a group between
statements) is part of the body, the other arm is absent; an undecided group holding labels is refused with
``conditional_compilation_unresolved``.
"""
from __future__ import annotations

import os

import pytest

from generators import c_project_context as cpc
from generators.c_source_oracle import evaluate_outputs

ROOT = os.path.join(os.sep, "virt_r90s")
CPROJECT = """<?xml version="1.0" encoding="UTF-8"?><cproject><storageModule moduleId="org.eclipse.cdt.core.settings">
<cconfiguration id="c1"><storageModule moduleId="cdtBuildSystem"><configuration artifactName="app" name="FLASH">
<folderInfo id="f"><toolChain id="t" superClass="com.freescale.s12z.toolchain">
<tool id="c" superClass="com.freescale.s12z.toolchain.compiler"></tool></toolChain></folderInfo>
</configuration></storageModule></cconfiguration></storageModule></cproject>"""


def _hdr(proto: int) -> str:
    return (f"#ifndef CFG_H\n#define CFG_H\n#define PROTOCOL_21 0\n#define LIN_PROTOCOL {proto}\n"
            "typedef unsigned char U8;\ntypedef unsigned int U16;\n#endif\n")


def _run(body: str, inputs: list[dict], proto: int = 0, with_build: bool = True,
         outputs: tuple[str, ...] = ("g_o",)) -> list[dict]:
    unit = f'#include "cfg.h"\nU8 g_o;\nU8 cnt;\nvoid f(U8 s) {{\n    switch (s)\n    {{\n{body}    }}\n}}\n'
    files = {os.path.join(ROOT, "cfg.h"): _hdr(proto), os.path.join(ROOT, "a.c"): unit}
    cp = {os.path.join(ROOT, ".cproject"): CPROJECT} if with_build else {}
    ctx = cpc.build_project_context(files, cpc.detect_build_config(cp), roots=[ROOT])
    scope = cpc.build_scopes(ctx, [os.path.join(ROOT, "a.c")])[os.path.join(ROOT, "a.c")]
    rec = {"name": "f", "source_text": unit, "source_path": os.path.join(ROOT, "a.c"), "source_text_complete": True,
           "project_scope": scope}
    return evaluate_outputs(rec, inputs, [list(outputs)] * len(inputs))


def _values(results: list[dict]) -> list:
    return [r["outputs"]["g_o"].get("value", r.get("reason") or r["outputs"]["g_o"].get("reason")) for r in results]


GROUP = ("#if (LIN_PROTOCOL == PROTOCOL_21)\n        case 1U: g_o = 1U; break;\n        case 2U: g_o = 2U; break;\n"
         "#endif\n        default: g_o = 9U; break;\n")
INPUTS = [{"s": 1, "g_o": 0}, {"s": 2, "g_o": 0}, {"s": 5, "g_o": 0}]


def test_a_decided_group_s_labels_are_the_switch_s():
    assert _values(_run(GROUP, INPUTS)) == [1, 2, 9]


def test_the_excluded_arm_s_labels_are_absent():
    assert _values(_run(GROUP, INPUTS, proto=1)) == [9, 9, 9]


def test_the_else_and_elif_arms():
    body = ("#if (LIN_PROTOCOL == 1)\n        case 1U: g_o = 1U; break;\n#elif (LIN_PROTOCOL == 2)\n"
            "        case 1U: g_o = 21U; break;\n#else\n        case 1U: g_o = 11U; break;\n        case 2U:\n#endif\n"
            "        default: g_o = 9U; break;\n")
    assert _values(_run(body, INPUTS, proto=0)) == [11, 9, 9]   # ``case 2U:`` falls into ``default``
    assert _values(_run(body, INPUTS, proto=1)) == [1, 9, 9]
    assert _values(_run(body, INPUTS, proto=2)) == [21, 9, 9]


def test_a_group_inside_a_case_falls_through_in_source_order():
    body = ("        case 1U: g_o = 1U;\n#if (LIN_PROTOCOL == PROTOCOL_21)\n        case 2U: g_o = (U8)(g_o + 2U);\n"
            "#endif\n        g_o = (U8)(g_o + 10U); break;\n        default: g_o = 9U; break;\n")
    # PROTOCOL_21: ``case 2U`` is a label, the statement after #endif belongs to it — 1 + 2 + 10; 0 + 2 + 10
    assert _values(_run(body, INPUTS)) == [13, 12, 9]
    # otherwise there is no ``case 2U``: 1 + 10, and 2 goes to default
    assert _values(_run(body, INPUTS, proto=1)) == [11, 9, 9]


def test_an_undecided_group_holding_labels_is_refused_with_the_reason():
    body = "#ifdef UNKNOWN_BUILD_SWITCH\n        case 1U: g_o = 1U; break;\n#endif\n        default: g_o = 9U; break;\n"
    results = _run(body, INPUTS[:1], with_build=False)   # no build evidence: a name defined nowhere is undecided
    assert results[0]["status"] == "unsupported" and results[0]["reason"] == "conditional_compilation_unresolved"


def test_a_name_taken_as_undefined_on_build_evidence_is_carried():
    body = "#ifndef TESTCODE_FOR_JIG\n        case 1U: g_o = 1U; break;\n#endif\n        default: g_o = 9U; break;\n"
    r = _run(body, INPUTS[:1])[0]
    assert r["outputs"]["g_o"]["value"] == 1 and r["assumed_undefined"] == ["TESTCODE_FOR_JIG"]


@pytest.mark.parametrize("body,reason", [
    # a statement before the first label of the body (in a decided group) is still outside every case
    ("#if (LIN_PROTOCOL == PROTOCOL_21)\n        g_o = 7U;\n        case 1U: g_o = 1U; break;\n#endif\n"
     "        default: g_o = 9U; break;\n", "switch_body_statement_outside_case"),
    # a label inside a block of a case — under a group or not — is not modelled
    ("        case 1U: if (g_o == 0U) {\n#if (LIN_PROTOCOL == PROTOCOL_21)\n        case 2U: g_o = 2U;\n#endif\n"
     "        } break;\n        default: g_o = 9U; break;\n", "case_label_in_nested_block"),
])
def test_what_stays_refused(body, reason):
    r = _run(body, INPUTS[:1])[0]
    assert r["status"] == "unsupported" and r["reason"] == reason


def test_labels_only_in_the_else_arm():
    body = ("        case 2U: g_o = 2U;\n#if (LIN_PROTOCOL == 1)\n            g_o = 5U;\n#else\n        case 1U: g_o = (U8)(g_o + 11U);\n"
            "#endif\n            break;\n        default: g_o = 9U; break;\n")
    # PROTOCOL_21: ``case 1U`` exists and ``case 2U`` falls into it (2 + 11); otherwise 2 then 5
    assert _values(_run(body, [{"s": 1, "g_o": 0}, {"s": 2, "g_o": 0}, {"s": 5, "g_o": 0}])) == [11, 13, 9]
    assert _values(_run(body, [{"s": 1, "g_o": 0}, {"s": 2, "g_o": 0}], proto=1)) == [9, 5]


def test_an_undecided_group_without_labels_matters_only_on_a_path_that_reaches_it():
    body = ("        case 1U:\n#ifdef UNKNOWN_BUILD_SWITCH\n            g_o = 3U;\n#endif\n            break;\n"
            "        default: g_o = 9U; break;\n")
    results = _run(body, [{"s": 5, "g_o": 0}, {"s": 1, "g_o": 0}], with_build=False)
    assert results[0]["outputs"]["g_o"]["value"] == 9
    assert results[1]["status"] == "unsupported" and results[1]["reason"] == "conditional_compilation_unresolved"


def test_a_declaration_in_a_decided_group_is_in_scope_at_a_later_label():
    # a jump to ``case 2U`` passes the group's ``U8 cnt`` (C11 6.2.1p4): ``cnt`` there is that local, not the global
    body = ("        case 1U: g_o = 1U;\n#if (LIN_PROTOCOL == PROTOCOL_21)\n            U8 cnt = 5U;\n#endif\n"
            "            break;\n        case 2U: cnt = 7U; g_o = 2U; break;\n        default: g_o = 9U; break;\n")
    r = _run(body, [{"s": 2, "g_o": 0, "cnt": 3}], outputs=("g_o", "cnt"))[0]
    assert r["outputs"]["g_o"]["value"] == 2 and r["outputs"]["cnt"]["value"] == 3   # the global is not written
    r = _run(body, [{"s": 2, "g_o": 0, "cnt": 3}], proto=1, outputs=("g_o", "cnt"))[0]
    assert r["outputs"]["cnt"]["value"] == 7   # excluded arm: no local, the global is written


def test_an_undecided_group_holding_a_declaration_is_refused_before_the_switch_runs():
    # whether a later label sees a local of that name is undecided — even the ``default`` path is not interpreted
    body = ("        case 1U: g_o = 1U;\n#ifdef UNKNOWN_BUILD_SWITCH\n            U8 cnt = 5U;\n#endif\n"
            "            break;\n        default: g_o = 9U; break;\n")
    r = _run(body, [{"s": 5, "g_o": 0}], with_build=False)[0]
    assert r["status"] == "unsupported" and r["reason"] == "conditional_compilation_unresolved"


def test_a_group_without_labels_between_a_case_s_statements_belongs_to_that_case():
    # the parser ends a case's statement list at a directive: the group and the ``break`` after it are children of
    # the switch body — before R90 the whole switch was refused (`switch_body_statement_outside_case`)
    body = ("        case 1U:\n#if (LIN_PROTOCOL == PROTOCOL_21)\n            g_o = 3U;\n#else\n            g_o = 4U;\n#endif\n"
            "            break;\n        default: g_o = 9U; break;\n")
    assert _values(_run(body, INPUTS)) == [3, 9, 9]
    assert _values(_run(body, INPUTS, proto=1)) == [4, 9, 9]


def _counting(monkeypatch) -> list:
    calls: list = []
    real = cpc.pp_condition

    def counted(scope, node, raw, assumed=None):
        calls.append((node.start_byte, node.type))
        return real(scope, node, raw, assumed)
    monkeypatch.setattr(cpc, "pp_condition", counted)
    return calls


def test_a_switch_s_layout_is_decided_once_per_function(monkeypatch):
    # (review) the layout rests on the unit's preprocessing only: a switch in a loop, three passes, two vectors — one verdict
    calls = _counting(monkeypatch)
    body = ("#ifndef TESTCODE_FOR_JIG\n        case 1U: g_o = (U8)(g_o + 1U); break;\n#endif\n"
            "        default: g_o = 9U; break;\n")
    unit = (f'#include "cfg.h"\nU8 g_o;\nvoid f(U8 s) {{\n    U8 k;\n    for (k = 0U; k < 3U; k++)\n    {{\n'
            f'    switch (s)\n    {{\n{body}    }}\n    }}\n}}\n')
    files = {os.path.join(ROOT, "cfg.h"): _hdr(0), os.path.join(ROOT, "a.c"): unit}
    ctx = cpc.build_project_context(files, cpc.detect_build_config({os.path.join(ROOT, ".cproject"): CPROJECT}),
                                    roots=[ROOT])
    scope = cpc.build_scopes(ctx, [os.path.join(ROOT, "a.c")])[os.path.join(ROOT, "a.c")]
    rec = {"name": "f", "source_text": unit, "source_path": os.path.join(ROOT, "a.c"), "source_text_complete": True,
           "project_scope": scope}
    results = evaluate_outputs(rec, [{"s": 1, "g_o": 0}, {"s": 1, "g_o": 10}], [["g_o"], ["g_o"]])
    assert [r["outputs"]["g_o"]["value"] for r in results] == [3, 13]
    assert len(calls) == 1
    # the run that used the kept layout records the name its verdict took as undefined, as the first did
    assert [r["assumed_undefined"] for r in results] == [["TESTCODE_FOR_JIG"], ["TESTCODE_FOR_JIG"]]


def test_a_kept_refusal_refuses_every_run():
    body = "#ifdef UNKNOWN_BUILD_SWITCH\n        case 1U: g_o = 1U; break;\n#endif\n        default: g_o = 9U; break;\n"
    results = _run(body, [{"s": 1, "g_o": 0}, {"s": 5, "g_o": 0}], with_build=False)
    assert [(r["status"], r["reason"]) for r in results] == [("unsupported", "conditional_compilation_unresolved")] * 2


def test_two_switches_of_one_function_keep_their_own_layouts():
    body = ("#if (LIN_PROTOCOL == PROTOCOL_21)\n        case 1U: g_o = 1U; break;\n#endif\n        default: g_o = 9U; break;\n"
            "    }\n    switch (s)\n    {\n#if (LIN_PROTOCOL != PROTOCOL_21)\n        case 1U: g_o = (U8)(g_o + 20U); break;\n"
            "#endif\n        default: g_o = (U8)(g_o + 100U); break;\n")
    # first switch: label 1 kept (1); second: label 1 absent, default (+100)
    assert _values(_run(body, [{"s": 1, "g_o": 0}])) == [101]


HD = r"D:\Project\Ados\PDS64_RD"
LIN_TL = os.path.join(HD, "Sources", "LIN", "LIN_driver", "transport", "lin_commontl_proto.c")


@pytest.mark.skipif(not os.path.isfile(LIN_TL), reason="HDPDM01 source tree not on this machine")
def test_hdpdm01_slave_response_switch_is_read():
    from pathlib import Path

    from scripts.reference_alignment import _load_source
    texts, context, _unread = _load_source([Path(HD), Path(r"D:\Project\Ados\PDS64_FBL")])
    path = str(Path(LIN_TL).resolve())
    scope = cpc.build_scopes(context, [path])[path]
    text = cpc.apply_body_projection(scope, texts[path])
    rec = {"name": "lin_tl_make_slaveres_pdu", "source_text": text, "source_path": path, "source_text_complete": True,
           "project_scope": scope}
    # SERVICE_ASSIGN_FRAME_ID_RANGE (0xB7): a label of the PROTOCOL_21 group; 0x00: default — both run
    for sid in (0xB7, 0x00):
        r = evaluate_outputs(rec, [{"sid": sid, "res_type": 1, "error_code": 0, "lin_configured_NAD": 5}],
                             [["lin_configured_NAD"]])[0]
        assert r["status"] == "supported" and r["outputs"]["lin_configured_NAD"]["value"] == 5, r.get("reason")
    # SERVICE_READ_BY_IDENTIFY (0xB2), positive, a user-defined id the callout does not serve (40): the data stays
    #   0xFF and ``for (i = 4; i >= 0; i --)`` on an ``l_u8 i`` reads ``data_callout[255]`` — the group's arm is run,
    #   and what it does is refused. (R90 F5) The read past the array is on a path a branch on an unknown value chose: its
    #   result is unknown and the path runs on (never dropped — `_Interp.undefined`); ``i >= 0`` on an unsigned ``i``
    #   never ends, so the run exhausts its budget — refused either way, never a value
    r = evaluate_outputs(rec, [{"sid": 0xB2, "res_type": 1, "error_code": 40}], [["lin_configured_NAD"]])[0]
    assert (r["status"], r["reason"]) == ("unsupported", "path_budget"), r.get("reason")
