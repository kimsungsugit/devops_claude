"""(R62) A function whose ``#if`` splits an expression, an initializer or an ``if`` head was unread (``source_parse_error``
— tree-sitter reads a conditional directive only between statements). It is now read as the compiler reads it: the
groups the unit's macro table decides become blanks of the same length, the directive lines too. A function that stays
unread is counted by reason, never dropped.
"""
from __future__ import annotations

import hashlib
import os

import pytest

from generators import c_project_context as cpc
from generators.c_source_oracle import evaluate_outputs, scope_matches
from generators.mcdc_design import build_mcdc_design
from generators.test_evidence import VERIFY_PREFIX, apply_sequence_evidence

ROOT = os.path.join(os.sep, "virt_r62")
A_C = os.path.join(ROOT, "a.c")
HDR = ("#ifndef CFG_H\n#define CFG_H\ntypedef unsigned char U8;\ntypedef unsigned int U16;\n#define FEAT_ON\n"
       "#define FEAT_LEVEL 2\nextern U8 g_a;\nextern U8 g_b;\nextern U8 g_c;\nextern U8 g_o;\n#endif\n")
NO_FEAT = HDR.replace("#define FEAT_ON\n", "")
GLOBALS = '#include "cfg.h"\nU8 g_a;\nU8 g_b;\nU8 g_c;\nU8 g_o;\n'
SPLIT = GLOBALS + """void f(void)
{
    if( ( g_a == 1U )
#ifdef FEAT_ON
        && ( g_b == 2U )
#endif
      )
    {
        g_o = 7U;
    }
    else
    {
        g_o = 3U;
    }
}
"""
# the pattern of KJPDS02_PV `s_DampingDetect_HandleHolding`: an #else arm repeats the ``if (`` head
HEADS = GLOBALS + """void f(void)
{
#ifdef FEAT_ON
    if( g_a > g_b )
#else
    if( g_a > g_c )
#endif
    {
        g_o = 1U;
    }
    else
    {
        g_o = 0U;
    }
}
"""
ELIF = GLOBALS + """void f(void)
{
    if( ( g_a == 1U )
#if FEAT_LEVEL > 2
        && ( g_b == 2U )
#elif FEAT_LEVEL > 1
        && ( g_c == 3U )
#else
        && ( g_b == g_c )
#endif
      )
    {
        g_o = 7U;
    }
    else
    {
        g_o = 3U;
    }
}
"""


def _cp():
    """A build configuration whose -D set is fully read (none): a name defined nowhere is undefined (R17)."""
    config = ('<configuration name="FLASH"><folderInfo id="f" resourcePath=""><toolChain id="t" superClass="tc">'
              '<builder id="b" superClass="x.builder" /><tool id="c" superClass="com.freescale.s12z.toolchain.compiler">'
              '</tool></toolChain></folderInfo></configuration>')
    return ('<cproject><storageModule moduleId="org.eclipse.cdt.core.settings"><cconfiguration id="c0">'
            f'<storageModule moduleId="cdtBuildSystem">{config}</storageModule></cconfiguration></storageModule></cproject>')


def _context(text, hdr=HDR, build=False):
    files = {os.path.join(ROOT, "cfg.h"): hdr, A_C: text}
    return cpc.build_project_context(files, cpc.detect_build_config({os.path.join(ROOT, ".cproject"): _cp()} if build else {}),
                                     roots=[ROOT])


def _scope(text, hdr=HDR, build=False):
    return cpc.build_scopes(_context(text, hdr, build), [A_C])[A_C]


def _unit(text, scope, name="f"):
    return {"name": name, "source_text": text, "source_path": A_C, "source_text_complete": True, "project_scope": scope}


def _value(unit, inputs, out="g_o"):
    r = evaluate_outputs(unit, [inputs], [[out]])[0]
    return r["outputs"][out].get("value", r["outputs"][out].get("reason"))


# ── the projection ───────────────────────────────────────────────────────────────────────────────

def test_a_condition_split_by_an_ifdef_is_read_as_the_compiler_reads_it():
    scope = _scope(SPLIT)
    assert evaluate_outputs(_unit(SPLIT, scope), [{"g_a": 1, "g_b": 2}], [["g_o"]])[0]["reason"] == "source_parse_error"
    text = cpc.apply_body_projection(scope, SPLIT)
    # same bytes, same lines: positions in the scope (``#if`` states, macro positions) still hold
    assert len(text.encode()) == len(SPLIT.encode()) and text.count("\n") == SPLIT.count("\n")
    assert "#ifdef" not in text and "#endif" not in text and text.startswith('#include "cfg.h"')
    unit = _unit(text, scope)
    assert scope_matches(unit) and scope_matches(_unit(SPLIT, scope))
    assert [_value(unit, v) for v in ({"g_a": 1, "g_b": 2}, {"g_a": 1, "g_b": 0}, {"g_a": 0, "g_b": 2})] == [7, 3, 3]
    rec = scope["body_projection"]["functions"][0]
    assert (rec["name"], rec["line"], rec["status"], rec["conditions"]) == ("f", 6, "projected", 1)
    assert scope["body_projection"]["projected"] == 1


def test_an_arm_judged_false_is_gone_and_the_names_it_rested_on_are_recorded():
    scope = _scope(SPLIT, NO_FEAT, build=True)
    text = cpc.apply_body_projection(scope, SPLIT)
    assert "g_b == 2U" not in text
    r = evaluate_outputs(_unit(text, scope), [{"g_a": 1, "g_b": 0}], [["g_o"]])[0]
    assert r["outputs"]["g_o"]["value"] == 7
    # the run says what its value rests on although no directive is left in the text it read
    assert "FEAT_ON" in r["assumed_undefined"] and any("FEAT_ON" in a for a in r["assumptions"])
    assert "FEAT_ON" in scope["assumed_undefined_body"]
    assert cpc.summarize_body_projection([scope])["assumed_undefined"] == ["FEAT_ON"]


def test_an_else_arm_that_repeats_the_if_head_reads_the_compiled_head():
    assert evaluate_outputs(_unit(HEADS, _scope(HEADS)), [{}], [["g_o"]])[0]["reason"] == "source_parse_error"
    for hdr, expect in ((HDR, [1, 0]), (NO_FEAT, [0, 1])):
        scope = _scope(HEADS, hdr, build=True)
        unit = _unit(cpc.apply_body_projection(scope, HEADS), scope)
        assert [_value(unit, {"g_a": 5, "g_b": 1, "g_c": 9}), _value(unit, {"g_a": 5, "g_b": 9, "g_c": 1})] == expect


def test_if_elif_else_keeps_only_the_first_true_arm():
    scope = _scope(ELIF)    # FEAT_LEVEL 2: the #elif arm
    unit = _unit(cpc.apply_body_projection(scope, ELIF), scope)
    assert _value(unit, {"g_a": 1, "g_b": 0, "g_c": 3}) == 7
    assert _value(unit, {"g_a": 1, "g_b": 2, "g_c": 0}) == 3
    assert _value(unit, {"g_a": 1, "g_b": 4, "g_c": 4}) == 3


def test_an_undecided_condition_leaves_the_function_unread_and_counted():
    scope = _scope(SPLIT, NO_FEAT)   # no build evidence: a name defined nowhere is undecided
    text = cpc.apply_body_projection(scope, SPLIT)
    assert text == SPLIT and "projected_sha256" not in scope
    assert scope["body_projection"]["functions"][0]["status"] == "undecided:FEAT_ON"
    s = cpc.summarize_body_projection([scope])
    assert (s["functions_with_tree_error"], s["functions_projected"], s["not_projected"]) == (1, 0, {"undecided": 1})
    assert s["not_projected_functions"] == ["f (undecided:FEAT_ON)"]
    assert evaluate_outputs(_unit(text, scope), [{}], [["g_o"]])[0]["reason"] == "source_parse_error"


def test_a_macro_the_file_defines_after_the_function_decides_nothing_in_it():
    # The end-of-unit table holds LATE; the compiler has not seen it at f. The oracle's prescan refuses such a name in a
    # body (``defined_after_function``); a projected function has no directive left for it to see, so the projection
    # applies the same rule itself — directly and through a macro body.
    text = (GLOBALS + "void f(void) {\n#ifdef LATE\n g_o = 1U;\n#else\n g_o = 2U;\n#endif\n}\n#define LATE\n"
            "void h(void) {\n#ifdef LATE\n g_o = 1U;\n#else\n g_o = 2U;\n#endif\n}\n")
    scope = _scope(text)
    assert evaluate_outputs(_unit(text, scope), [{}], [["g_o"]])[0]["reason"] == "macro_defined_after_function:LATE"
    assert _value(_unit(text, scope, "h"), {}) == 1
    raw = text.encode()
    late = cpc.body_verdict(scope, "ifdef", "LATE", position=0)
    assert late is None and cpc.body_verdict(scope, "ifdef", "LATE", position=raw.index(b"void h")) is True
    # pp_condition takes the position of the function its node sits in
    root = cpc.shared_parser().parse(raw).root_node
    nodes = [n for n in cpc._walk(root) if n.type == "preproc_ifdef"]
    assert [cpc.pp_condition(scope, n, raw) for n in nodes] == [None, True]
    split_late = GLOBALS + "void f(void) {\n if( ( g_a == 1U )\n#ifdef LATE\n && ( g_b == 2U )\n#endif\n ) { g_o = 7U; }\n}\n#define LATE\n"
    scope = _scope(split_late)
    assert cpc.apply_body_projection(scope, split_late) == split_late
    assert scope["body_projection"]["functions"][0]["status"] == "undecided_defined_after:LATE"
    split = GLOBALS + "void f(void) {\n if( ( g_a == 1U )\n#if VIA\n && ( g_b == 2U )\n#endif\n ) { g_o = 7U; }\n}\n#define LATE2 1\n"
    scope = _scope(split, HDR.replace("#define FEAT_LEVEL 2\n", "#define FEAT_LEVEL 2\n#define VIA (LATE2)\n"))
    assert cpc.apply_body_projection(scope, split) == split
    assert scope["body_projection"]["functions"][0]["status"] == "undecided_defined_after:VIA"


def test_another_function_of_the_file_is_left_as_it_was():
    text = SPLIT + "void h(void) {\n#ifdef UNKNOWN_FEATURE\n g_o = 1U;\n#endif\n}\n"
    scope = _scope(text)
    projected = cpc.apply_body_projection(scope, text)
    assert projected[projected.index("void h"):] == text[text.index("void h"):]
    assert evaluate_outputs(_unit(projected, scope, "h"), [{}], [["g_o"]])[0]["reason"] == "conditional_compilation_unresolved"
    assert _value(_unit(projected, scope), {"g_a": 1, "g_b": 2}) == 7


def test_a_text_the_scope_was_not_built_from_is_left_alone_and_projection_is_idempotent():
    scope = _scope(SPLIT)
    other = SPLIT.replace("7U", "8U")
    assert cpc.apply_body_projection(scope, other) == other and "body_projection" not in scope
    once = cpc.apply_body_projection(scope, SPLIT)
    assert cpc.apply_body_projection(scope, once) == once and cpc.apply_body_projection(scope, SPLIT) == once
    assert not cpc.scope_text_matches(scope, hashlib.sha256(other.encode()).hexdigest())
    assert cpc.scope_text_matches(scope, hashlib.sha256(once.encode()).hexdigest())
    assert not scope_matches(_unit(other, scope))


def test_the_states_of_the_file_hold_for_the_projected_text():
    # two definitions of f under a file-level #ifdef / #else: the configuration compiles the first — on the projected
    # text too, the MC/DC design picks it by the scope's states (one definition, not "ambiguous")
    text = GLOBALS + "#ifdef FEAT_ON\n" + SPLIT[len(GLOBALS):] + "#else\nvoid f(void) { g_o = 0U; }\n#endif\n"
    scope = _scope(text)
    projected = cpc.apply_body_projection(scope, text)
    unit = {**_unit(projected, scope), "input_vars": ["g_a", "g_b"], "output_vars": ["g_o"]}
    assert [d["status"] for d in build_mcdc_design(unit)["decisions"]] == ["designed"]
    assert _value(unit, {"g_a": 1, "g_b": 2}) == 7


def test_a_function_the_configuration_may_not_compile_is_not_projected_but_counted():
    text = GLOBALS + "#ifdef UNDECIDED_X\n" + SPLIT[len(GLOBALS):] + "#endif\n"
    scope = _scope(text)    # no build evidence: UNDECIDED_X is undecided, f's state "unknown"
    assert cpc.apply_body_projection(scope, text) == text
    assert [r["status"] for r in scope["body_projection"]["functions"]] == ["conditional_compilation_unresolved"]
    assert cpc.summarize_body_projection([scope])["not_projected"] == {"conditional_compilation_unresolved": 1}
    assert evaluate_outputs(_unit(text, scope), [{}], [["g_o"]])[0]["reason"] == "conditional_compilation_unresolved"
    # a function the configuration does not compile at all is no function of the document: not counted
    text = GLOBALS + "#ifdef NOT_ON\n" + SPLIT[len(GLOBALS):] + "#endif\n"
    scope = _scope(text, build=True)
    assert cpc.apply_body_projection(scope, text) == text and scope["body_projection"]["functions"] == []


# ── review round 1 ──────────────────────────────────────────────────────────────────────────────

LATE_HDR = "#ifndef LATE_H\n#define LATE_H\n#define LATE_FEAT\n#endif\n"


def test_a_macro_a_header_included_after_the_function_defines_decides_nothing_in_it():
    # (W1) at f the compiler has not met late.h: the end-of-unit table (LATE_FEAT defined) is not f's table
    split = SPLIT.replace("FEAT_ON", "LATE_FEAT") + '#include "late.h"\nvoid h(void) { g_o = 1U; }\n'
    files = {os.path.join(ROOT, "cfg.h"): HDR, os.path.join(ROOT, "late.h"): LATE_HDR, A_C: split}
    ctx = cpc.build_project_context(files, cpc.detect_build_config({}), roots=[ROOT])
    scope = cpc.build_scopes(ctx, [A_C])[A_C]
    assert cpc.apply_body_projection(scope, split) == split
    assert scope["body_projection"]["functions"][0]["status"] == "undecided_defined_after:LATE_FEAT"
    assert cpc.macro_changed_after(scope, "LATE_FEAT", split.encode().index(b"void f"))
    assert not cpc.macro_changed_after(scope, "FEAT_ON", split.encode().index(b"void f"))
    # the statement-level path (the oracle's prescan) refuses it too — it judged by the end-of-unit table before
    stmt = (GLOBALS + "void f(void) {\n#ifdef LATE_FEAT\n g_o = 1U;\n#else\n g_o = 2U;\n#endif\n}\n"
            '#include "late.h"\n')
    files[A_C] = stmt
    ctx = cpc.build_project_context(files, cpc.detect_build_config({}), roots=[ROOT])
    scope = cpc.build_scopes(ctx, [A_C])[A_C]
    assert evaluate_outputs(_unit(stmt, scope), [{}], [["g_o"]])[0]["reason"] == "macro_defined_after_function:LATE_FEAT"
    # a header included before the function is the function's table
    before = GLOBALS.replace('#include "cfg.h"\n', '#include "cfg.h"\n#include "late.h"\n') + SPLIT[len(GLOBALS):].replace(
        "FEAT_ON", "LATE_FEAT")
    files[A_C] = before
    ctx = cpc.build_project_context(files, cpc.detect_build_config({}), roots=[ROOT])
    scope = cpc.build_scopes(ctx, [A_C])[A_C]
    assert _value(_unit(cpc.apply_body_projection(scope, before), scope), {"g_a": 1, "g_b": 0}) == 3


@pytest.mark.parametrize("directive", ["#define LOCAL_ON 1", "#undef FEAT_ON", '#include "cfg.h"'])
def test_a_table_changed_inside_the_function_is_not_projected(directive):
    # (W2) the end-of-unit table is not the one a group after an in-body #define / #undef / #include sees
    text = SPLIT.replace("{\n    if(", "{\n" + directive + "\n    if(", 1)
    scope = _scope(text, build=True)
    assert cpc.apply_body_projection(scope, text) == text
    assert scope["body_projection"]["functions"][0]["status"] == "macro_table_changed_in_function"


def test_an_undecided_reserved_name_is_told_apart_from_a_project_name():
    # (W5d) ``__CSURF__``: the implementation's to define — no project file or -D settles it
    text = SPLIT.replace("#ifdef FEAT_ON", "#ifndef __CSURF__")
    scope = _scope(text, build=True)
    cpc.apply_body_projection(scope, text)
    assert scope["body_projection"]["functions"][0]["status"] == "undecided_reserved:__CSURF__"
    assert cpc.summarize_body_projection([scope])["not_projected"] == {"undecided_reserved": 1}


def test_the_suts_summary_counts_the_document_s_functions_and_the_rest_apart():
    text = SPLIT + "void g(void)\n{\n    if( ( g_a == 1U )\n#ifdef FEAT_ON\n        && ( g_c == 2U )\n#endif\n      )\n" \
                   "    {\n        g_o = 1U;\n    }\n}\n"
    scope = _scope(text)
    cpc.apply_body_projection(scope, text)
    s = cpc.summarize_body_projection([scope], only={(A_C, "f")})
    assert (s["functions_with_tree_error"], s["functions_projected"], s["projected_functions"]) == (1, 1, ["f"])
    assert s["outside_document"] == {"projected": 1, "not_projected": 0}
    assert cpc.summarize_body_projection([scope])["functions_projected"] == 2


def test_crlf_text_projects_with_its_line_ends_kept():
    crlf = SPLIT.replace("\n", "\r\n").replace("#ifdef FEAT_ON", "#if defined(FEAT_ON) \\\r\n    && 1")
    scope = _scope(crlf)
    text = cpc.apply_body_projection(scope, crlf)
    assert text != crlf and text.count("\r\n") == crlf.count("\r\n") and len(text.encode()) == len(crlf.encode())
    assert _value(_unit(text, scope), {"g_a": 1, "g_b": 0}) == 3 and _value(_unit(text, scope), {"g_a": 1, "g_b": 2}) == 7


def test_an_apostrophe_in_an_error_message_of_a_skipped_arm_does_not_open_a_literal():
    raw = b"x(\n#if A\n#error don't build this\n#else\n2\n#endif\n)\n"
    ranges, why, _ = cpc._group_blanks(raw, 0, len(raw), lambda _k, a: {"A": False}.get(a.strip()))
    assert why == "" and cpc._blanked(raw, ranges).split() == [b"x(", b"2", b")"]
    escaped = b'x = "a\\"#if Q";\n#if A\n1\n#endif\n'   # an escaped quote does not end the literal
    assert [k for _s, _e, k, _a in cpc._directive_lines(escaped, 0, len(escaped))] == ["if", "endif"]


def test_a_name_chain_too_long_to_follow_is_undecided(monkeypatch):
    scope = _scope(SPLIT)
    bodies = {f"M{i}": {"body": f"M{i + 1}", "file": "x.h", "pos": 0} for i in range(5000)}
    monkeypatch.setitem(scope, "pp_bodies", bodies)
    monkeypatch.setitem(scope, "_defined_after_memo", {})
    assert cpc._defined_after(scope, "M0", 10) is True   # never "nothing changed" for what it could not follow
    assert cpc._defined_after(scope, "M4990", 10) is False


def test_a_projection_defect_leaves_the_file_as_read_and_is_counted(monkeypatch):
    scope = _scope(SPLIT)

    def boom(_text, _scope):
        raise ValueError("defect")
    monkeypatch.setattr(cpc, "project_body_conditionals", boom)
    assert cpc.apply_body_projection(scope, SPLIT) == SPLIT
    assert cpc.summarize_body_projection([scope])["projection_errors"] == 1


def test_the_mcdc_sheet_shows_the_projected_expression_without_blank_lines():
    import re
    expr = "( g_a == 1U )\n              \n        && ( g_b == 2U )\n      \n      "
    assert re.sub(r"\n[ \t]*(?=\n)", "", expr) == "( g_a == 1U )\n        && ( g_b == 2U )\n      "


def test_a_source_finding_names_the_hash_of_the_text_read():
    from generators.source_findings import collect_input_gap_findings
    unit = {"fid": "F1", "name": "f", "source_path": A_C, "source_text": "abc", "project_scope": {"main_file_sha256": "x"}}
    row = collect_input_gap_findings([unit], {"F1": {"g_x": {"slots": 1, "sequences": [1]}}}, {})[0]
    assert row["source_hash"] == hashlib.sha256(b"abc").hexdigest()


def test_change_impact_does_not_report_a_projected_function_as_changed(tmp_path):
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    from change_impact import impact
    (tmp_path / "cfg.h").write_text(HDR, encoding="utf-8")
    (tmp_path / "a.c").write_text(SPLIT, encoding="utf-8", newline="\n")
    path = str((tmp_path / "a.c").resolve())
    files = {str(tmp_path / "cfg.h"): HDR, path: SPLIT}
    ctx = cpc.build_project_context(files, cpc.detect_build_config({}), roots=[str(tmp_path)])
    projected = cpc.apply_body_projection(cpc.build_scopes(ctx, [path])[path], SPLIT)
    row = {"test_case": "T1", "function": "f", "sequence": 1, "observable": "g_o", "expected": "7",
           "inputs": {"g_a": 1, "g_b": 2}, "source_path": path,
           "source_hash": hashlib.sha256(projected.encode()).hexdigest()}
    out = impact([row], [tmp_path])
    assert out["status"] == {"same_value": 1} and out["changed_files"] == []
    assert row["source_text_changed"] is False


def test_the_mcdc_design_lists_the_projected_function_s_decisions():
    scope = _scope(SPLIT)
    unit = {**_unit(SPLIT, scope), "input_vars": ["g_a", "g_b"], "output_vars": ["g_o"]}
    before = build_mcdc_design(unit)["decisions"]
    assert [(d["status"], d["reason"]) for d in before] == [("unenumerated", "source_parse_error")]
    after = build_mcdc_design({**unit, "source_text": cpc.apply_body_projection(scope, SPLIT)})["decisions"]
    assert [d["status"] for d in after] == ["designed"]


# ── the directive reader and the groups ─────────────────────────────────────────────────────────

def test_directive_lines_are_read_outside_comments_and_literals():
    raw = (b'a = "#if X";\n'
           b"/* #if Y\n #if Y2 */ b;\n"
           b"// #if Z\n"
           b"c = '#';\n"
           b's = "/*";\n'                  # ``/*`` in a literal opens no comment
           b"// a /* in a line comment\n"  # nor in a line comment
           b"/* lead */ #ifdef A\n"        # a comment before ``#`` is a space: still a directive
           b"#  ifndef B\n"
           b"#if C && \\\n   D\n"           # a splice continues the line, and is gone from the argument
           b"x = 1; #if E\n"               # not at the start of a line
           b"#endif\n#endif\n#endif\n")
    got = [(k, a.strip()) for _s, _e, k, a in cpc._directive_lines(raw, 0, len(raw))]
    assert got == [("ifdef", "A"), ("ifndef", "B"), ("if", "C && D"), ("endif", ""), ("endif", ""), ("endif", "")]
    line = cpc._directive_lines(raw, 0, len(raw))[2]
    assert raw[line[0]:line[1]] == b"#if C && \\\n   D"   # the blanked range covers the continued line


def test_a_group_inside_a_skipped_arm_is_never_judged():
    # B's group — its #else included — sits in the skipped A arm: none of it is compiled, none of it is judged
    raw = b"x(\n#if A\n#if B\n1\n#else\n4\n#endif\n#elif C\n2\n#else\n3\n#endif\n)\n"
    asked = []

    def verdict(_k, a):
        asked.append(a.strip())
        return {"A": False, "C": True}.get(a.strip())
    ranges, why, decided = cpc._group_blanks(raw, 0, len(raw), verdict)
    assert asked == ["A", "C"] and (why, decided) == ("", 2)
    out = cpc._blanked(raw, ranges)
    assert out.split() == [b"x(", b"2", b")"] and len(out) == len(raw) and out.count(b"\n") == raw.count(b"\n")


def test_an_elif_after_a_taken_arm_is_never_judged():
    asked = []
    raw = b"#if A\n1\n#elif B\n2\n#else\n3\n#endif\n"
    ranges, _why, decided = cpc._group_blanks(raw, 0, len(raw), lambda _k, a: asked.append(a.strip()) or True)
    assert asked == ["A"] and decided == 1 and cpc._blanked(raw, ranges).split() == [b"1"]


@pytest.mark.parametrize("raw,why", [
    (b"a\n#endif\n", "unbalanced"),
    (b"#if A\na\n", "unbalanced"),
    (b"#else\na\n", "unbalanced"),
    (b"a = 1;\n#pragma x\n", "no_conditional_directive"),
])
def test_what_is_not_projected_says_why(raw, why):
    assert cpc._group_blanks(raw, 0, len(raw), lambda _k, _a: True)[:2] == (None, why)


def test_a_directive_line_reads_through_a_comment_spanning_lines():
    # (round 5 W-1) a comment is one blank: ``#if A /* … */`` goes on after the comment's end, and the blanked range
    # covers the lines the comment spans
    raw = b"x(\n#if A /* spans\n lines */ && B\n1\n#else\n2\n#endif\n)\n"
    asked = []
    ranges, why, _ = cpc._group_blanks(raw, 0, len(raw), lambda _k, a: asked.append(a) or False)
    assert why == "" and asked == ["A && B"]
    assert cpc._blanked(raw, ranges).split() == [b"x(", b"2", b")"]


def test_an_undecided_condition_stops_the_projection():
    raw = b"#if A\n1\n#endif\n"
    assert cpc._group_blanks(raw, 0, len(raw), lambda _k, _a: None)[:2] == (None, "undecided:A")


def test_a_projection_that_disturbs_another_function_is_refused():
    parser = cpc.shared_parser()
    new = b"void f(void) { }\nvoid g(void) { }\n"
    f_key, g_key = (0, "f"), (new.index(b"void g"), "g")
    assert cpc._projection_check(parser, new, {f_key: True, g_key: False}, f_key) == "projected"
    assert cpc._projection_check(parser, new, {f_key: True}, f_key) == "function_set_changed"
    bad = b"void f(void) { }\nvoid g(void) { x = ; }\n"
    assert cpc._projection_check(parser, bad, {f_key: True, (bad.index(b"void g"), "g"): False}, f_key) \
        == "error_moved_to_another_function"
    assert cpc._projection_check(parser, b"void f(void) { x = ; }\n", {f_key: True}, f_key) == "still_error"


# ── the directive's spelling ────────────────────────────────────────────────────────────────────

def test_a_spaced_ifndef_is_an_ifndef_in_a_body_and_at_file_level():
    body = GLOBALS + "void f(void) {\n#  ifndef FEAT_ON\n g_o = 1U;\n#  else\n g_o = 2U;\n#  endif\n}\n"
    assert _value(_unit(body, _scope(body)), {}) == 2
    top = GLOBALS + "#  ifndef FEAT_ON\nvoid f(void) { g_o = 1U; }\n#  endif\n"
    r = evaluate_outputs(_unit(top, _scope(top)), [{}], [["g_o"]])[0]
    assert r["reason"] == "function_not_compiled_in_configuration"


# ── consumers ───────────────────────────────────────────────────────────────────────────────────

def test_the_evidence_says_its_hash_is_of_the_projected_text():
    scope = _scope(SPLIT)
    text = cpc.apply_body_projection(scope, SPLIT)
    seqs = [{"inputs": {"g_a": 1, "g_b": 2}, "expected": {"g_o": f"{VERIFY_PREFIX} x"}}]
    apply_sequence_evidence({**_unit(text, scope), "output_vars": ["g_o"]}, seqs)
    ev = seqs[0]["expected_evidence"]["g_o"]
    assert seqs[0]["expected"]["g_o"] == 7 and ev["source_hash"] == hashlib.sha256(text.encode()).hexdigest()
    assert ev["source_hash_scope"] == "captured_decoded_utf8_text_body_conditionals_projected"
    plain = GLOBALS + "void f(void) { g_o = 1U; }\n"
    seqs = [{"inputs": {}, "expected": {"g_o": f"{VERIFY_PREFIX} x"}}]
    apply_sequence_evidence({**_unit(plain, _scope(plain)), "output_vars": ["g_o"]}, seqs)
    assert seqs[0]["expected_evidence"]["g_o"]["source_hash_scope"] == "captured_decoded_utf8_text"


def test_suts_units_of_a_file_share_the_projected_text_and_the_summary_counts_it():
    from generators.suts import attach_unit_sources
    own = "void own(void) { }\n"
    units = [{"name": "f", "source_path": A_C}, {"name": "f2", "source_path": A_C},
             {"name": "own", "source_path": A_C, "source_text": own}]
    stats: dict = {}
    attach_unit_sources(units, {A_C: SPLIT}, _context(SPLIT), stats=stats)
    assert units[0]["source_text"] is units[1]["source_text"] and units[0]["source_text"] != SPLIT
    assert units[2]["source_text"] == own   # a unit's own, different text is not swapped for the file's
    assert (stats["functions_projected"], stats["projected_functions"], stats["files_projected"]) == (1, ["f"], 1)


def test_sits_reads_the_projected_unit_and_leaves_the_source_stage_map_alone():
    from generators.integration_oracle import attach_integration_evidence
    files = {os.path.join(ROOT, "cfg.h"): HDR, A_C: SPLIT}
    subs = [{"inputs": {"g_a": 1, "g_b": 2}, "expected": {"g_o": f"{VERIFY_PREFIX} x"}}]
    stats = attach_integration_evidence([{"tc_id": "T1", "entry_fn": "f", "sub_cases": subs}],
                                        {"project_context": _context(SPLIT), "source_files": files},
                                        {"x": {"name": "f", "source_path": A_C}})
    assert subs[0]["expected"]["g_o"] == 7
    assert stats["body_projection"]["functions_projected"] == 1
    assert files[A_C] == SPLIT


def test_the_disclosure_counts_projected_and_unread_functions_by_reason():
    from report_gen.generation_disclosures import build_disclosures
    block = {"files_projected": 1, "functions_with_tree_error": 3, "functions_projected": 1, "conditions_decided": 2,
             "not_projected": {"undecided": 1, "no_conditional_directive": 1}, "projected_functions": ["f"],
             "not_projected_functions": ["g (undecided:X)", "h (no_conditional_directive)"],
             "assumed_undefined": ["FEAT_ON"]}
    item = {i["key"]: i for i in build_disclosures("suts", {"body_projection": block})}["suts_body_projection"]
    assert item["value"] == "투영 1 · 남은 파싱 오류 2 / 트리 오류 함수 3" and item["tone"] == "warning"
    for part in ("판정 못 하는 #if 조건 1", "인라인 어셈블리", "FEAT_ON", "투영한 함수: f", "판정한 조건 2개", "채워지면 다음 생성에서 투영된다"):
        assert part in item["note"], part
    assert "모델 밖 문법이라 투영으로 풀리지 않는다" in item["note"]          # no "fill it in" for what filling cannot fix
    assert "남은 함수: g (undecided:X), h (no_conditional_directive)" in item["note"]
    assert "MC/DC 결정 · 기대값은 비어 있다" in item["note"] and "해시 범위 열" in item["note"]
    sits = {i["key"]: i for i in build_disclosures("sits", {"integration_oracle": {"body_projection": block}})}
    assert sits["sits_body_projection"]["value"] == item["value"]
    assert "통합 기대값은 미상" in sits["sits_body_projection"]["note"] and "MC/DC" not in sits["sits_body_projection"]["note"]
    assert "해시 범위 열" not in sits["sits_body_projection"]["note"]   # SITS Test Evidence has no such column
    reserved = {**block, "not_projected": {"undecided_reserved": 1}}
    note = {i["key"]: i for i in build_disclosures("suts", {"body_projection": reserved})}["suts_body_projection"]["note"]
    assert "대상 컴파일러가 그 이름을 정의하는지 확인" in note and "채워지면 다음 생성에서 투영된다" not in note
    only_outside = {"functions_with_tree_error": 0, "functions_projected": 0, "outside_document": {"projected": 1,
                                                                                                  "not_projected": 0}}
    out = {i["key"]: i for i in build_disclosures("suts", {"body_projection": only_outside})}["suts_body_projection"]
    assert out["value"] == "투영 0 · 남은 파싱 오류 0 / 트리 오류 함수 0" and "문서에 행이 없는 함수: 투영 1" in out["note"]
    quiet = {**block, "functions_with_tree_error": 1, "not_projected": {}, "functions_projected": 1}
    assert {i["key"]: i for i in build_disclosures("suts", {"body_projection": quiet})}["suts_body_projection"]["tone"] == "info"
    assert "suts_body_projection" not in {i["key"] for i in build_disclosures("suts", {"body_projection": {}})}


def test_every_tool_that_builds_scopes_reads_the_projected_text():
    """(review W3) A tool that builds scopes from texts and reads a unit's text on the raw text sees a projected function
    as ``source_parse_error`` and a generated row's hash as "changed". New callers must project or be exempted here."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    exempt = {"generators/c_project_context.py": "defines build_scopes and the projection"}
    missing = []
    for folder in ("generators", "scripts", "backend", "report_gen", "workflow", "tools"):
        for path in (root / folder).rglob("*.py"):
            rel = path.relative_to(root).as_posix()
            if "venv" in rel or "node_modules" in rel:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "build_scopes(" not in text or rel in exempt:
                continue
            if not any(k in text for k in ("apply_body_projection", "projected_texts")):
                missing.append(rel)
    assert missing == []


def test_the_unread_list_is_cut_at_40_and_says_how_many_there_were():
    recs = [{"name": f"f{i:02d}", "status": "undecided:X", "conditions": 0, "assumed_undefined": []} for i in range(45)]
    s = cpc.summarize_body_projection([{"path": A_C, "body_projection": {"functions": recs, "projected": 0}}])
    assert len(s["not_projected_functions"]) == 40 and s["not_projected_total"] == 45
    assert s["not_projected"] == {"undecided": 45} and s["functions_with_tree_error"] == 45


# ── review round 2 ──────────────────────────────────────────────────────────────────────────────

def _ctx_files(files, build=False):
    return cpc.build_project_context(files, cpc.detect_build_config({os.path.join(ROOT, ".cproject"): _cp()} if build
                                                                     else {}), roots=[ROOT])


def _status(scope, name="f"):
    return {r["name"]: r["status"] for r in scope["body_projection"]["functions"]}[name]


def test_the_same_definition_met_again_after_the_function_changes_nothing():
    # (W-A) an unguarded header included again after f re-#defines FEAT_LEVEL identically; #undef of a name never
    # defined changes nothing either — f still sees its table (HEAD evaluated these, the first fix refused them)
    dup = "#define FEAT_LEVEL 2\n#define K_ON 1U\n"
    text = (GLOBALS + '#include "dup.h"\nvoid f(void) {\n#if FEAT_LEVEL == 2\n g_o = K_ON;\n#else\n g_o = 5U;\n#endif\n}\n'
            '#include "dup.h"\n#undef NEVER_DEFINED\n')
    files = {os.path.join(ROOT, "cfg.h"): HDR, os.path.join(ROOT, "dup.h"): dup, A_C: text}
    scope = cpc.build_scopes(_ctx_files(files), [A_C])[A_C]
    assert _value(_unit(text, scope), {}) == 1
    at_f = text.encode().index(b"void f")
    assert not cpc.macro_changed_after(scope, "K_ON", at_f) and not cpc.macro_changed_after(scope, "NEVER_DEFINED", at_f)
    # a different body after f is a change
    files[A_C] = text.replace("#undef NEVER_DEFINED", "#undef K_ON\n#define K_ON 2U")
    scope = cpc.build_scopes(_ctx_files(files), [A_C])[A_C]
    assert cpc.macro_changed_after(scope, "K_ON", files[A_C].encode().index(b"void f"))


def test_a_table_change_the_file_level_walk_does_not_read_stops_every_body_verdict_of_the_unit():
    # (W-B, round 4 W-1) e's #undef FEAT_ON is in a body: the walk never applied it — the unit's body #if are undecided
    # (f is not projected; the statement-level #if is refused), and the name varies on the value path
    e = "void e(void) {\n#undef FEAT_ON\n g_o = 0U;\n}\n"
    text = GLOBALS + e + SPLIT[len(GLOBALS):]
    scope = _scope(text, build=True)
    assert "FEAT_ON" in scope["pp_varied"] and scope["body_table_unknown"] == ["stray_directive:a.c:#undef FEAT_ON"]
    assert cpc.apply_body_projection(scope, text) == text
    assert _status(scope) == "body_table_unknown:stray_directive:a.c:#undef FEAT_ON"
    stmt = GLOBALS + e + "void f(void) {\n#ifdef FEAT_ON\n g_o = 1U;\n#else\n g_o = 2U;\n#endif\n}\n"
    scope = _scope(stmt, build=True)
    assert evaluate_outputs(_unit(stmt, scope), [{}], [["g_o"]])[0]["reason"] == "conditional_compilation_unresolved"
    # a name only an earlier body defines is not "defined nowhere" on build evidence
    local = GLOBALS + "void e(void) {\n#define LOCAL_X 1\n g_o = 0U;\n}\n" + \
        SPLIT[len(GLOBALS):].replace("#ifdef FEAT_ON", "#if defined(LOCAL_X) || !defined(FEAT_ON)")
    scope = _scope(local, build=True)
    assert "LOCAL_X" in scope["pp_defined_anywhere"] and cpc.apply_body_projection(scope, local) == local


def test_a_body_change_that_steers_a_later_file_level_if_is_not_projected_on():
    # (round 4 G1) e #undefs FEAT_ON; a later file-level #ifdef FEAT_ON chooses LVL — the walk chose with FEAT_ON
    # defined (LVL 1), the compiler without (LVL 3): f's split #if LVL > 2 must not be projected (gcc: 3; it was 7)
    hdr = HDR.replace("#define FEAT_LEVEL 2\n", "")
    text = (GLOBALS + "void e(void) {\n#undef FEAT_ON\n g_o = 0U;\n}\n#ifdef FEAT_ON\n#define LVL 1\n#else\n#define LVL 3\n"
            "#endif\n" + SPLIT[len(GLOBALS):].replace("#ifdef FEAT_ON", "#if LVL > 2"))
    scope = _scope(text, hdr, build=True)
    assert cpc.apply_body_projection(scope, text) == text and _status(scope).startswith("body_table_unknown:")


def test_a_header_s_inline_function_body_change_counts_for_the_unit():
    # (round 4 P3c) inl.h's inline function #undefs and redefines FEAT_LEVEL before f
    inl = "static inline void h(void) {\n#undef FEAT_LEVEL\n#define FEAT_LEVEL 3\n}\n"
    text = (GLOBALS.replace('#include "cfg.h"\n', '#include "cfg.h"\n#include "inl.h"\n')
            + SPLIT[len(GLOBALS):].replace("#ifdef FEAT_ON", "#if FEAT_LEVEL > 2"))
    files = {os.path.join(ROOT, "cfg.h"): HDR, os.path.join(ROOT, "inl.h"): inl, A_C: text}
    scope = cpc.build_scopes(_ctx_files(files, build=True), [A_C])[A_C]
    assert "FEAT_LEVEL" in scope["pp_varied"] and cpc.apply_body_projection(scope, text) == text
    assert _status(scope).startswith("body_table_unknown:stray_directive:inl.h:")


def test_a_directive_in_a_construct_the_parser_did_not_recognize_is_still_read():
    # (round 4 S11) d's #else arm repeats the ``if (`` head; its body's #undef sits under an ERROR node — no function
    # definition — and is still a change of the table. (R63) The walk reads it from the lexer where it stands: FEAT_ON
    # varies in the unit (no longer an unknown table), and f's ``#ifdef FEAT_ON`` is not decided
    d = ("void d(void)\n{\n#if NOPE_X\n    if (g_a) {\n#else\n    if (g_b) {\n#endif\n        g_o = 1U;\n#undef FEAT_ON\n"
         "    }\n}\n")
    text = GLOBALS + d + SPLIT[len(GLOBALS):]
    scope = _scope(text, build=True)
    assert "FEAT_ON" in scope["pp_varied"] and scope["body_table_unknown"] == []
    assert cpc.apply_body_projection(scope, text) == text and _status(scope) == "undecided_varied:FEAT_ON"


@pytest.mark.parametrize("spelling", ["#/**/undef FEAT_ON", "# /*c*/ undef FEAT_ON", "#\\\nundef FEAT_ON",
                                      "#un\\\ndef FEAT_ON", "#undef/*c*/FEAT_ON"])
def test_the_keyword_is_read_after_comments_and_splices(spelling):
    # (round 4 W-3) translation phases 2-3 come first: these are all ``#undef FEAT_ON``
    text = GLOBALS + "void e(void) {\n" + spelling + "\n g_o = 0U;\n}\n" + SPLIT[len(GLOBALS):]
    scope = _scope(text, build=True)
    assert "FEAT_ON" in scope["pp_varied"] and cpc.apply_body_projection(scope, text) == text


def test_a_local_macro_defined_and_undefined_in_one_body_changes_no_table():
    # the KJPDS02_PV ``linuds.c`` shape: a name the project defines nowhere else, #define'd and #undef'd in one body
    e = "void e(void) {\n#define LOCAL_DLC (0x02U)\n g_o = LOCAL_DLC;\n#undef LOCAL_DLC\n}\n"
    text = GLOBALS + e + SPLIT[len(GLOBALS):]
    scope = _scope(text, build=True)
    assert scope["body_table_unknown"] == [] and "LOCAL_DLC" not in scope["pp_varied"]
    assert _value(_unit(cpc.apply_body_projection(scope, text), scope), {"g_a": 1, "g_b": 2}) == 7
    # the same pair on a name the project defines elsewhere leaves it undefined after e: a change
    other = text.replace("LOCAL_DLC", "FEAT_ON")
    scope = _scope(other, build=True)
    assert scope["body_table_unknown"] and cpc.apply_body_projection(scope, other) == other


def test_an_include_inside_a_function_body_stops_the_unit_and_varies_what_it_changes():
    # (round 3 W-2) e's body includes mode_b.h, which sets FEAT_LEVEL to 3
    mode_b = "#undef FEAT_LEVEL\n#define FEAT_LEVEL 3\n"
    text = (GLOBALS + 'void e(void) {\n#include "mode_b.h"\n g_o = 0U;\n}\n'
            + SPLIT[len(GLOBALS):].replace("#ifdef FEAT_ON", "#if FEAT_LEVEL > 2"))
    files = {os.path.join(ROOT, "cfg.h"): HDR, os.path.join(ROOT, "mode_b.h"): mode_b, A_C: text}
    scope = cpc.build_scopes(_ctx_files(files, build=True), [A_C])[A_C]
    assert "FEAT_LEVEL" in scope["pp_varied"] and scope["body_includes"] == ["mode_b.h"]
    assert scope["body_table_unknown"] == ["stray_directive:a.c:#include mode_b.h"]
    assert cpc.apply_body_projection(scope, text) == text
    # an include that cannot be found also says so
    text2 = text.replace("mode_b.h", "nowhere.h")
    scope = _scope(text2, build=True)
    assert scope["body_table_unknown"] == ["stray_directive:a.c:#include nowhere.h", "unresolved_include:nowhere.h"]
    assert cpc.body_verdict(scope, "ifdef", "FEAT_ON", position=0) is None
    cpc.apply_body_projection(scope, text2)
    assert _status(scope).startswith("body_table_unknown:")   # not "fill in a -D"


def test_the_scan_records_stray_directives_and_the_cache_versions_move_together():
    raw = b'#define TOP 1\nvoid e(void) {\n#define A 1\n#undef B\n#include "x.h"\n}\n#undef TOP\n'
    got = cpc._stray_directives(cpc.shared_parser().parse(raw).root_node, raw)
    assert [(d["op"], d["name"], d["fn"]) for d in got["directives"]] == [
        ("define", "A", raw.index(b"void e")), ("undef", "B", raw.index(b"void e")), ("include", "x.h", raw.index(b"void e"))]
    # the file-level #define / #undef are events, not strays; a directive line running into a comment is still read
    long = b"void e(void) {\n#undef B /* spans\n two lines */\n}\n"
    assert [(d["op"], d["name"]) for d in cpc._stray_directives(cpc.shared_parser().parse(long).root_node, long)[
        "directives"]] == [("undef", "B")]
    from backend.helpers.uds import _SOURCE_SECTIONS_SCHEMA_VERSION
    assert (cpc.SCHEMA_VERSION, _SOURCE_SECTIONS_SCHEMA_VERSION) == (24, "v53")


def test_undecided_reasons_say_whether_an_input_can_settle_them():
    from report_gen.generation_disclosures import build_disclosures
    block = {"functions_with_tree_error": 2, "functions_projected": 0, "not_projected": {"undecided_varied": 1,
             "undecided_defined_after": 1}, "projected_functions": [], "not_projected_functions": [],
             "assumed_undefined": []}
    note = {i["key"]: i for i in build_disclosures("suts", {"body_projection": block})}["suts_body_projection"]["note"]
    assert note.count("입력을 채워서는 풀리지 않는다") == 2 and "채워지면 다음 생성에서 투영된다" not in note
    assert "값이 바뀌는 매크로" in note and "함수보다 뒤에서" in note


# ── review round 3 ──────────────────────────────────────────────────────────────────────────────

def test_a_body_directive_running_into_a_long_comment_is_read_and_stops_the_unit():
    # (round 3 W-1 · round 5 W-1) never "nothing there": the #undef is read through the comment
    text = GLOBALS + "void e(void) {\n#undef FEAT_ON /* a comment that\n ends on the next line */\n g_o = 0U;\n}\n" + \
        SPLIT[len(GLOBALS):]
    scope = _scope(text, build=True)
    assert scope["body_table_unknown"] == ["stray_directive:a.c:#undef FEAT_ON"]
    assert cpc.apply_body_projection(scope, text) == text
    # a define / undef with no readable name still stops the unit
    nameless = GLOBALS + "void e(void) {\n#undef 1X\n g_o = 0U;\n}\n" + SPLIT[len(GLOBALS):]
    scope = _scope(nameless, build=True)
    assert scope["body_table_unknown"] == ["unreadable_directive:a.c"]
    assert cpc.apply_body_projection(scope, nameless) == nameless
    assert _status(scope) == "body_table_unknown:unreadable_directive:a.c"


def test_an_include_guard_first_defined_after_the_function_is_a_change():
    # (I-1) the guard's #define is not in the macro bodies (the scan looks through the guard): it is still the first
    # definition of the name — f, before the include, sees it undefined
    split = SPLIT.replace("#ifdef FEAT_ON", "#ifdef LATE_H") + '#include "late.h"\n'
    files = {os.path.join(ROOT, "cfg.h"): HDR, os.path.join(ROOT, "late.h"): LATE_HDR, A_C: split}
    scope = cpc.build_scopes(_ctx_files(files), [A_C])[A_C]
    cpc.apply_body_projection(scope, split)
    assert scope["body_projection"]["functions"][0]["status"] == "undecided_defined_after:LATE_H"
    stmt = GLOBALS + "void f(void) {\n#ifdef LATE_H\n g_o = 1U;\n#else\n g_o = 2U;\n#endif\n}\n" + '#include "late.h"\n'
    files[A_C] = stmt
    scope = cpc.build_scopes(_ctx_files(files), [A_C])[A_C]
    assert evaluate_outputs(_unit(stmt, scope), [{}], [["g_o"]])[0]["reason"] == "macro_defined_after_function:LATE_H"


def test_a_function_the_configuration_leaves_out_changes_no_table():
    # (I-3) e sits in an #ifdef the configuration does not compile: its #undef is no change
    text = GLOBALS + "#ifdef NOT_COMPILED\nvoid e(void) {\n#undef FEAT_ON\n g_o = 0U;\n}\n#endif\n" + SPLIT[len(GLOBALS):]
    scope = _scope(text, build=True)
    assert "FEAT_ON" not in scope["pp_varied"] and scope["body_table_unknown"] == []
    assert _value(_unit(cpc.apply_body_projection(scope, text), scope), {"g_a": 1, "g_b": 0}) == 3


def test_a_unit_with_a_stray_change_has_no_union_view_and_is_counted():
    text = GLOBALS + "void e(void) {\n#define FEAT_LEVEL 3\n g_o = 0U;\n}\n" + SPLIT[len(GLOBALS):]
    scope = _scope(text)
    assert "FEAT_LEVEL" in scope["body_directive_names"] and cpc.undecided_macro_view(scope, "FEAT_LEVEL") is None
    cpc.apply_body_projection(scope, text)
    s = cpc.summarize_body_projection([scope])
    assert s["units_table_unknown"] == 1 and s["table_unknown_reasons"] == ["stray_directive:a.c:#define FEAT_LEVEL"]


def test_the_suts_summary_counts_the_units_left_after_the_test_scope():
    # (R62 measurement) a unit the SwUDS test scope drops (`apply_scope`) has no rows: its projection is outside the
    # document (HDPDM01: the LIN stack's projected function was counted as this document's)
    from generators.suts import attach_unit_sources, summarize_document_body_projection
    text = SPLIT + "void g(void)\n{\n    if( ( g_a == 1U )\n#ifdef FEAT_ON\n        && ( g_c == 2U )\n#endif\n      )\n" \
                   "    {\n        g_o = 1U;\n    }\n}\n"
    units = [{"name": "f", "source_path": A_C}, {"name": "g", "source_path": A_C}]
    attach_unit_sources(units, {A_C: text}, _context(text))
    kept = [u for u in units if u["name"] == "f"]           # what the test scope keeps
    s = summarize_document_body_projection(kept)
    assert (s["functions_projected"], s["projected_functions"], s["outside_document"]) == (1, ["f"], {"projected": 1,
                                                                                                     "not_projected": 0})
    assert summarize_document_body_projection([{"name": "x"}]) == {}


# ── review round 4 ──────────────────────────────────────────────────────────────────────────────

def test_a_directive_the_walk_reads_in_a_recovery_container_is_no_stray():
    # a top-level compound_statement (parse recovery) holds a #define the walk reads (R63: every file-level line, from
    # the lexer)
    raw = b"x = {\n#define IN_ERR 1\n1};\nvoid f(void) { }\n"
    root = cpc.shared_parser().parse(raw).root_node
    assert [e["name"] for e in cpc._file_walk(root, raw)["events"] if e["op"] == "define"] == ["IN_ERR"]
    assert cpc._stray_directives(root, raw)["directives"] == []



def test_a_definition_the_walk_never_met_stops_the_conditions_resting_on_it():
    # (round 4) a #define the walk does not read (R63: one in a header's inline function body — a body directive) of a
    # name the project defines nowhere else: a condition naming it, or a name a file-level #if testing it chose, is not
    # decided
    regs = "static inline void reg_init(void) {\n#define REG_B0_MASK 1U\n}\n"
    hdr = HDR.replace("#define FEAT_LEVEL 2\n", "") + regs
    text = (GLOBALS + "#ifdef REG_B0_MASK\n#define LVL 1\n#else\n#define LVL 3\n#endif\n"
            + SPLIT[len(GLOBALS):].replace("#ifdef FEAT_ON", "#if LVL > 2"))
    scope = _scope(text, hdr, build=True)
    assert scope["missed_definition_names"] == ["REG_B0_MASK"]
    # (round 5 F-A) the walk chose ``#ifdef REG_B0_MASK`` without the name: the unit's table is unknown
    assert scope["body_table_unknown"] == ["file_if_on_missed_definition:REG_B0_MASK"]
    assert cpc.apply_body_projection(scope, text) == text
    assert _status(scope) == "body_table_unknown:file_if_on_missed_definition:REG_B0_MASK"
    direct = GLOBALS + SPLIT[len(GLOBALS):].replace("#ifdef FEAT_ON", "#ifdef REG_B0_MASK")
    scope = _scope(direct, hdr, build=True)
    cpc.apply_body_projection(scope, direct)
    assert _status(scope) == "undecided_missed_definition:REG_B0_MASK"
    s = cpc.summarize_body_projection([scope])
    assert s["units_with_missed_definitions"] == 1 and s["missed_definitions"] >= 1


def test_a_value_less_define_with_trailing_blanks_keeps_its_own_line():
    # (round 5 C-4, KJPDS02_PV / HDPDM01 lin_cfg.h) tree-sitter read ``#define _CFG_H_ `` + blanks + newline +
    # ``#include "hw.h"`` as one macro — the walk never included hw.h there. `_parse_safe` moves the blanks past the
    # newline (same length), so the include is an event, in order, and no stray
    raw = b'#ifndef _CFG_H_\n#define _CFG_H_  \n#include "hw.h"\n#endif\n'
    safe = cpc._parse_safe(raw)
    assert len(safe) == len(raw) and safe.index(b"#include") == raw.index(b"#include")
    assert safe.startswith(b'#ifndef _CFG_H_\n#define _CFG_H_\n  #include')
    rec = cpc._scan_file("lcfg.h", raw.decode(), cpc.shared_parser())
    assert rec["includes"] == ["hw.h"] and rec["stray_directives"]["directives"] == []
    assert rec["sha256"] == hashlib.sha256(raw).hexdigest()   # the facts are of the text as read
    assert cpc._parse_safe(b"#define K 1  \n") == b"#define K 1  \n"   # a value is no bare #define


def test_a_unit_whose_table_the_walk_does_not_know_whole_has_no_union_view():
    # a macro under an undecided #if has a union view (R35) — not when a stray change makes the unit's table unknown
    hdr = HDR + "#ifdef UNDECIDED_Q\n#define VIEWED (g_a)\n#endif\n"
    plain = GLOBALS + SPLIT[len(GLOBALS):]
    scope = _scope(plain, hdr)
    assert cpc.undecided_macro_view(scope, "VIEWED") is not None
    stray = GLOBALS + "void e(void) {\n#undef FEAT_ON\n g_o = 0U;\n}\n" + SPLIT[len(GLOBALS):]
    scope = _scope(stray, hdr)
    assert scope["body_table_unknown"] and cpc.undecided_macro_view(scope, "VIEWED") is None

# ── review round 5 ──────────────────────────────────────────────────────────────────────────────

E_DEFX = "void e(void)\n{\n#define FEAT_X 1\n    g_c = 1U;\n}\n"


@pytest.mark.parametrize("label,tail", [
    # M1: the missed FEAT_X chooses which f the configuration compiles
    ("M1", "#if FEAT_X\n" + SPLIT[len(GLOBALS):] + "#else\n" + SPLIT[len(GLOBALS):].replace("#ifdef FEAT_ON", "#ifndef FEAT_ON")
     + "#endif\n"),
    # M2: through an alias
    ("M2", "#define ALIAS FEAT_X\n#if ALIAS\n#define LVL 1\n#else\n#define LVL 3\n#endif\n"
     + SPLIT[len(GLOBALS):].replace("#ifdef FEAT_ON", "#if LVL > 2")),
    # M3: transitively
    ("M3", "#ifdef FEAT_X\n#define A_X 1\n#endif\n#ifdef A_X\n#define LVL 1\n#else\n#define LVL 3\n#endif\n"
     + SPLIT[len(GLOBALS):].replace("#ifdef FEAT_ON", "#if LVL > 2")),
    # M12: a function under the missed name's #ifdef changes the table
    ("M12", "#ifdef FEAT_X\nvoid g(void) {\n#undef FEAT_ON\n g_o = 0U;\n}\n#endif\n" + SPLIT[len(GLOBALS):]),
])
def test_a_file_level_if_resting_on_a_missed_name_stops_the_unit(label, tail):
    # (round 5 F-A) the walk chose those #if without the name the body defined
    text = GLOBALS + E_DEFX + tail
    scope = _scope(text, build=True)
    assert any(r.startswith("file_if_on_missed_definition:") for r in scope["body_table_unknown"]), label
    assert cpc.apply_body_projection(scope, text) == text, label


def test_a_guarded_header_first_included_in_a_body_stops_the_unit():
    # (round 5 C-4 M5) the hidden-include no-op is gone: an in-body #include is a table change the walk did not follow
    late = "#ifndef LATE_H\n#define LATE_H\n#define LATE_MODE 1\n#endif\n"
    text = (GLOBALS + 'void e(void)\n{\n#include "late.h"\n    g_c = 1U;\n}\n'
            + "#ifdef LATE_MODE\n#define LVL 1\n#else\n#define LVL 3\n#endif\n"
            + SPLIT[len(GLOBALS):].replace("#ifdef FEAT_ON", "#if LVL > 2") + '#include "late.h"\n')
    files = {os.path.join(ROOT, "cfg.h"): HDR, os.path.join(ROOT, "late.h"): late, A_C: text}
    scope = cpc.build_scopes(_ctx_files(files), [A_C])[A_C]
    assert "stray_directive:a.c:#include late.h" in scope["body_table_unknown"]
    assert cpc.apply_body_projection(scope, text) == text


@pytest.mark.parametrize("body", [
    "#define LOCAL_DLC 2U\n g_o = LOCAL_DLC;\n#if 0\n#undef LOCAL_DLC\n#endif\n",     # M11: the #undef may not run
    "#define LOCAL_DLC 2U\n g_o = LOCAL_DLC;\n#ifdef FEAT_ON\n#undef LOCAL_DLC\n#endif\n",
])
def test_a_local_macro_with_a_conditional_between_is_no_local_macro(body):
    # (round 5 F-D) LOCAL_DLC may stay defined after e: a name the walk never met — conditions on it are refused
    text = GLOBALS + "void e(void) {\n" + body + "}\n" + SPLIT[len(GLOBALS):].replace("#ifdef FEAT_ON", "#ifdef LOCAL_DLC")
    scope = _scope(text, build=True)
    assert "LOCAL_DLC" in scope["missed_definition_names"]
    assert cpc.apply_body_projection(scope, text) == text
    assert _status(scope) == "undecided_missed_definition:LOCAL_DLC"


@pytest.mark.parametrize("spelling", ["#  undef FEAT_ON", "#\tundef FEAT_ON"])
def test_a_spaced_undef_at_file_level_is_an_undef(spelling):
    # (round 5 C-2 N1/N4) ``#  undef`` was dropped by the walk (``directive == "#undef"``): FEAT_ON stayed defined and the
    # projection kept the arm (3; gcc 7). Read, the #undef of a defined name varies it in the unit: not decided
    text = GLOBALS + spelling + "\n" + SPLIT[len(GLOBALS):]
    scope = _scope(text, build=True)
    assert "FEAT_ON" not in scope["pp_macros"] and "FEAT_ON" in scope["pp_varied"]
    assert cpc.apply_body_projection(scope, text) == text and _status(scope) == "undecided_varied:FEAT_ON"
    rec = cpc._scan_file("x.h", spelling + "\n", cpc.shared_parser())
    assert rec["undefs"] == ["FEAT_ON"] and [e["op"] for e in rec["events"]] == ["undef"]


def test_a_directive_the_lexer_reads_as_another_kind_is_read_by_the_walk():
    # (round 5 C-2 N2) ``#un\<NL>def FEAT_ON``: tree-sitter reads ``#un``, the compiler ``#undef``. (R63) The walk reads
    # file-level lines from the lexer: an #undef of a defined name — FEAT_ON varies in the unit, f is not decided
    text = GLOBALS + "#un\\\ndef FEAT_ON\n" + SPLIT[len(GLOBALS):]
    scope = _scope(text, build=True)
    assert scope["body_table_unknown"] == [] and "FEAT_ON" in scope["pp_varied"]
    assert cpc.apply_body_projection(scope, text) == text and _status(scope) == "undecided_varied:FEAT_ON"


def test_a_header_whose_directive_runs_into_a_long_comment_is_read():
    # (round 5 W-1 U1) ``#endif /* CFG_H`` + newline + `` */`` no longer makes the file unreadable for every unit
    hdr = HDR.replace("#endif\n", "#endif /* CFG_H\n */\n")
    scope = _scope(SPLIT, hdr, build=True)
    assert scope["body_table_unknown"] == []
    assert _value(_unit(cpc.apply_body_projection(scope, SPLIT), scope), {"g_a": 1, "g_b": 2}) == 7
