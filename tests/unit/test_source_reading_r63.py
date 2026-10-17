"""(R63) The C files are read as the target compiler reads them before anything is built on them.

* every file-level directive line is read from the lexer (`_file_walk`): a ``#define`` among a register struct's members,
  a multi-line macro with a comment before its line splice, one inside ``extern "C" { }`` — the parser's tree showed
  none of them, so the macro table lacked them;
* a multi-line macro body is read without its line splices (it kept its backslashes and could not be parsed);
* the vendor syntax that changes no value (``@0x2C0`` placement, ``__attribute__``, ``__interrupt``, ``__far``) is read
  as blanks of the same length — the declarations and functions around it parse, at the same positions, for the
  project context and for every consumer of a unit (`reading_text`);
* what is left unread is counted by kind and disclosed (`summarize_source_reading`).
"""
from __future__ import annotations

import os

from generators import c_project_context as cpc
from generators.c_source_oracle import evaluate_outputs

ROOT = os.path.join(os.sep, "virt_r63")
A_C = os.path.join(ROOT, "a.c")
# the target's widths come from typedef testimony anywhere in the tree (`_target_widths`) — an unconditional one
TYPES = "typedef unsigned char U8;\ntypedef unsigned int U16;\n"


def _cp():
    """A build configuration whose -D set is fully read (none) — as `test_body_projection_r62._cp`."""
    config = ('<configuration name="FLASH"><folderInfo id="f" resourcePath=""><toolChain id="t" superClass="tc">'
              '<builder id="b" superClass="x.builder" /><tool id="c" superClass="com.freescale.s12z.toolchain.compiler">'
              '</tool></toolChain></folderInfo></configuration>')
    return ('<cproject><storageModule moduleId="org.eclipse.cdt.core.settings"><cconfiguration id="c0">'
            f'<storageModule moduleId="cdtBuildSystem">{config}</storageModule></cconfiguration></storageModule></cproject>')


def _ctx(files):
    files = {"w.h": TYPES, **files}
    return cpc.build_project_context({os.path.join(ROOT, k): v for k, v in files.items()}, roots=[ROOT])


def _scope(files):
    return cpc.build_scopes(_ctx(files), [A_C])[A_C]


def _walk(text):
    raw = text.encode()
    return cpc._file_walk(cpc.shared_parser().parse(raw).root_node, raw)


def _run(text, scope, inputs, out="g_o", name="f"):
    unit = {"name": name, "source_text": cpc.apply_body_projection(scope, text), "source_path": A_C,
            "source_text_complete": True, "project_scope": scope}
    r = evaluate_outputs(unit, [inputs], [[out]])[0]
    return r["outputs"].get(out, {}).get("value", r["outputs"].get(out, {}).get("reason", r.get("reason")))


# ── vendor syntax read as blanks ─────────────────────────────────────────────────────────────────

def test_vendor_syntax_is_read_as_blanks_of_the_same_length():
    raw = (b"extern volatile U8 _PTP @0x000002C0;\nstatic U8 buf[4] __attribute__ ((aligned (4))) = {1};\n"
           b"__interrupt void isr(void) { }\nvoid g(__far const U8 *p);\n")
    out, counts = cpc.reading_text(raw)
    assert len(out) == len(raw) and out.count(b"\n") == raw.count(b"\n")
    assert counts == {"address_placement": 1, "attribute": 1, "interrupt": 1, "far_near": 1}
    assert b"@" not in out and b"__attribute__" not in out and b"__interrupt" not in out and b"__far" not in out
    assert out.index(b"void isr") == raw.index(b"void isr")
    assert not cpc.shared_parser().parse(out).root_node.has_error


def test_vendor_words_in_comments_literals_and_directives_stay():
    raw = (b'/* @0x10 __far */\nconst char *s = "__interrupt @0x2";\n#define ATTR __attribute__((packed))\n'
           b"// __near\nU8 a;\n")
    out, counts = cpc.reading_text(raw)
    assert out == raw and counts == {}


def test_an_attribute_without_its_double_parenthesis_is_not_touched():
    raw = b"U8 __attribute__ x;\n"
    assert cpc.reading_text(raw) == (raw, {})


def test_asm_is_never_blanked():
    raw = b"void f(void) { asm(BGND); __asm CLI; }\n"
    assert cpc.reading_text(raw)[0] == raw


def test_a_register_declared_at_an_address_is_a_global():
    hdr = TYPES + "typedef union { U8 Byte; } PTPSTR;\nextern volatile PTPSTR _PTP @0x000002C0;\n#define PTP _PTP.Byte\n"
    ctx = _ctx({"r.h": hdr, "a.c": '#include "r.h"\n'})
    rec = ctx["files"][os.path.join(ROOT, "r.h")]
    assert rec["globals"]["_PTP"][0]["extern"] and rec["globals"]["_PTP"][0]["volatile"]
    assert rec["reading"]["blanked"] == {"address_placement": 1} and not rec["parse_error"]


def test_an_interrupt_function_is_read_by_the_context_and_its_consumers_alike():
    text = (TYPES + "U8 g_a;\nU8 g_o;\n__interrupt void f(void)\n{\n    if (g_a > 2U) { g_o = 1U; } else { g_o = 0U; }\n}\n")
    scope = _scope({"a.c": text})
    start = text.encode().index(b"void f")
    assert scope["main_file_states"].get(start) == "active"   # the function starts after the blanks, for both readers
    assert cpc.apply_body_projection(scope, text) != text and cpc.scope_text_matches(scope, scope["projected_sha256"])
    assert [_run(text, scope, {"g_a": v}) for v in (3, 2)] == [1, 0]


# ── directives the parser's tree did not show ─────────────────────────────────────────────────────

REGS = (TYPES + "typedef union {\n  U8 Byte;\n  struct {\n    U8 B0 :1;\n    U8    :7;\n  } Bits;\n"
        "#define REG_B0_MASK 1U\n#define REG_BYTE _REG.Byte\n} REGSTR;\nextern volatile REGSTR _REG @0x10;\n")


def test_a_define_among_struct_members_is_in_the_macro_table():
    rec = _ctx({"r.h": REGS, "a.c": '#include "r.h"\n'})["files"][os.path.join(ROOT, "r.h")]
    assert rec["macros"]["REG_B0_MASK"][0]["body"] == "1U" and not rec["macros"]["REG_B0_MASK"][0]["conditional"]
    assert rec["reading"]["directives_beyond_tree"] == {"define": 2} and rec["stray_directives"]["directives"] == []
    text = '#include "r.h"\nU8 g_a;\nU8 g_o;\nvoid f(void) { g_o = (U8)(g_a & REG_B0_MASK); }\n'
    scope = _scope({"r.h": REGS, "a.c": text})
    assert scope["missed_definition_names"] == [] and [_run(text, scope, {"g_a": v}) for v in (3, 2)] == [1, 0]


def test_an_unnamed_bit_field_is_counted_as_the_grammar_s_gap_not_a_loss():
    rec = _ctx({"r.h": REGS, "a.c": '#include "r.h"\n'})["files"][os.path.join(ROOT, "r.h")]
    kinds = rec["reading"]["errors"]["kinds"]
    assert kinds.get("unnamed_bitfield") == 1 and "declaration" not in kinds


def test_a_multi_line_macro_is_read_without_its_splices():
    hdr = (TYPES + "#define SIG_RD() \\\n    ((U8) ((g_buf[3] & \\\n    0x0FU) >> 0))\n"
           "#define PIN_GET() ( \\\n    (U8)((g_buf[0] & 0x10U))   /* Return port data */ \\\n  )\nextern U8 g_buf[8];\n")
    rec = _ctx({"s.h": hdr, "a.c": '#include "s.h"\n'})["files"][os.path.join(ROOT, "s.h")]
    assert rec["macros"]["SIG_RD"][0]["body"] == "((U8) ((g_buf[3] & 0x0FU) >> 0))"
    assert rec["macros"]["PIN_GET"][0]["body"] == "( (U8)((g_buf[0] & 0x10U)) )"   # the comment is a blank, then gone
    assert rec["macros"]["PIN_GET"][0]["function_like"] and rec["macros"]["PIN_GET"][0]["params"] == []
    assert rec["reading"]["spliced_defines"] == 2
    text = '#include "s.h"\nU8 g_buf[8];\nU8 g_o;\nvoid f(void) { g_o = SIG_RD(); }\n'
    scope = _scope({"s.h": hdr, "a.c": text})
    assert _run(text, scope, {"g_buf[3]": 0x5A}) == 0x0A


def test_a_splice_in_an_if_expression_is_read_through():
    ev = _walk("#if defined(A) || \\\n  defined(B)\nint x;\n#endif\n")["events"][0]
    assert ev["expr"] == "defined(A) || defined(B)"


def test_declarations_inside_extern_c_are_file_level_for_a_c_compiler():
    hdr = ("#ifndef SF_H\n#define SF_H\n#ifdef __cplusplus\nextern \"C\" {\n#endif\n#ifndef u32_defined\n"
           "typedef unsigned long u32;\n#define u32_defined\n#endif\n#define KEY_BYTES 256U\n"
           "typedef struct { u32 n; } SF_RT;\n#ifdef __cplusplus\n}\n#endif\n#endif\n")
    rec = _ctx({"sf.h": hdr, "a.c": '#include "sf.h"\n'})["files"][os.path.join(ROOT, "sf.h")]
    assert {"u32", "SF_RT"} <= set(rec["typedefs"]) and rec["macros"]["KEY_BYTES"][0]["body"] == "256U"
    scope = _scope({"sf.h": hdr, "a.c": '#include "sf.h"\n'})
    assert scope["constants"]["KEY_BYTES"]["value"] == 256
    # (review round 1 I1) the unit sees the typedefs (they were `type_undeclared` when the body was not descended)
    assert {"u32", "SF_RT"} <= set(scope["types"]) | set(scope["unresolved_types"]) | set(scope["typedef_names"])
    assert "u32" in scope["typedef_names"] and "SF_RT" in scope["typedef_names"]


def test_cplusplus_is_undefined_for_a_c_unit_once_the_build_is_read():
    # (review round 1 I3) C11 6.10.8p3: no C implementation predefines __cplusplus — with the -D set read it is decided
    hdr = "#ifdef __cplusplus\nextern \"C\" {\n#endif\nint k;\n#ifdef __cplusplus\n}\n#endif\n"
    files = {os.path.join(ROOT, "w.h"): TYPES, os.path.join(ROOT, "x.h"): hdr, A_C: '#include "x.h"\n'}
    built = cpc.build_project_context(files, cpc.detect_build_config({os.path.join(ROOT, ".cproject"): _cp()}),
                                      roots=[ROOT])
    scope = cpc.build_scopes(built, [A_C])[A_C]
    assert scope["preprocessor"]["unknown_conditions"] == 0 and "__cplusplus" in scope["assumed_undefined"]
    unbuilt = cpc.build_scopes(_ctx({"x.h": hdr, "a.c": '#include "x.h"\n'}), [A_C])[A_C]
    assert unbuilt["preprocessor"]["unknown_conditions"] == 2   # without the -D set: a -D could define it
    # (review round 2 I2) an option that may compile C as C++: not decided
    cpp = _cp().replace('superClass="com.freescale.s12z.toolchain.compiler">',
                        'superClass="com.freescale.s12z.toolchain.compiler"><option id="o" superClass="x.compiler.option.'
                        'other" value="-C++f" valueType="string"/>')
    assert cpc.detect_build_config({"p": cpp})["configurations"]["p"]["cplusplus_mode"] is True
    built = cpc.build_project_context(files, cpc.detect_build_config({os.path.join(ROOT, ".cproject"): cpp}), roots=[ROOT])
    assert cpc.build_scopes(built, [A_C])[A_C]["preprocessor"]["unknown_conditions"] == 2


def test_an_endif_with_trailing_tokens_still_closes_the_guard():
    w = _walk("#ifndef G_H\n#define G_H\n#define K 1\n#endif G_H\n")
    assert [d["name"] for d in w["defines"]] == ["K"] and not w["defines"][0]["conditional"] and w["problems"] == {}


# ── what the walk keeps from before ───────────────────────────────────────────────────────────────

def test_the_walk_matches_the_parser_on_well_formed_code():
    text = ('#include "t.h"\n#include <sys.h>\n#define A 1\n#ifdef A\nint x;\n#elif B > 1\nint y;\n#else\nint z;\n#endif\n'
            "#undef A\n#error stop\nvoid f(void) { }\n")
    w = _walk(text)
    raw = text.encode()
    ops = [(e["op"], e.get("name") or e.get("defined") or e.get("pos")) for e in w["events"]]
    assert ops == [("include", "t.h"), ("include", "sys.h"), ("define", "A"), ("if", "A"), ("undef", "A"),
                   ("error", None), ("decl", raw.index(b"void f"))]
    ev = w["events"][3]
    assert ev["then"] == [{"op": "decl", "pos": raw.index(b"int x")}] and ev["else"][0]["expr"] == "B > 1"
    assert ev["else"][0]["else"] == [{"op": "decl", "pos": raw.index(b"int z")}]
    assert w["events"][1]["system"] and not w["events"][0]["system"]
    assert w["includes"] == ["t.h"] and w["system_includes"] == ["sys.h"] and w["undefs"] == ["A"]


def test_directives_in_a_function_body_stay_strays_and_its_own_groups_stay_its_own():
    text = "int g;\nvoid f(void)\n{\n#ifdef X\n g = 1;\n#endif\n#define LOCAL 1\n}\n"
    w = _walk(text)
    assert [e["op"] for e in w["events"]] == ["decl", "decl"]
    assert [(d["op"], d["name"]) for d in w["strays"]] == [("define", "LOCAL")]


def test_a_group_a_function_does_not_close_is_read_at_file_level():
    text = "#ifdef A\nvoid f(int a)\n{\n#else\nvoid f(int a, int b)\n{\n#endif\n  (void)a;\n}\nint after;\n"
    w = _walk(text)
    assert w["problems"] == {} and w["events"][0]["op"] == "if"
    assert w["events"][-1] == {"op": "decl", "pos": text.encode().index(b"int after")}


def test_a_misplaced_line_is_counted_not_crashed():
    w = _walk("#endif\n#else\n#if A\nint x;\n")
    assert w["problems"] == {"misplaced_endif": 1, "misplaced_else": 1, "unterminated_group": 1}


# ── writes through an alias macro ─────────────────────────────────────────────────────────────────

def test_a_write_through_a_designator_macro_writes_its_object():
    hdr = (TYPES + "typedef union { U8 Byte; } RSTR;\nextern volatile RSTR _PTAD @0x10;\n#define PTADL _PTAD.Byte\n"
           "#define ALIAS2 (PTADL)\n#define DEREF (*g_p)\nextern U8 *g_p;\n")
    text = '#include "r.h"\nvoid w1(void) { PTADL = 1U; }\nvoid w2(void) { ALIAS2 = 2U; }\nvoid w3(void) { DEREF = 3U; }\n'
    closure = cpc.function_write_closure(_ctx({"r.h": hdr, "a.c": text}))["functions"]
    assert closure["w1"]["writes"] >= {"_PTAD"} and not closure["w1"]["unknown_callees"]
    assert closure["w2"]["writes"] >= {"_PTAD"} and not closure["w2"]["unknown_callees"]
    assert closure["w3"]["unknown_callees"] == {"macro_write:DEREF"}


def test_a_macro_defined_two_ways_writes_whatever_any_definition_names():
    def t(name, text, unsettled, objects=frozenset({"g", "h", "g_c", "boot"})):
        return cpc._designator_targets(name, text, unsettled, objects)
    assert t("M", {"M": ["g.a", "(g.b)"]}, set()) == {"g"} and t("M", {"M": ["g.a", "h.a"]}, set()) == {"g", "h"}
    assert t("M", {"M": ["g[i]"]}, set()) is None and t("M", {"M": ["g[3U]"]}, set()) == {"g"}
    assert t("M", {"M": ["M"]}, set()) is None and t("M", {"M": ["f(x)"]}, set()) is None
    # every name on the chain: ``g_c`` is an object in the unit that writes ALIAS, a macro in another file (C1)
    assert t("ALIAS", {"ALIAS": ["g_c"], "g_c": ["boot.s"]}, set()) == {"g_c", "boot"}
    # a name a function body (re)defines, or a body directive the lexer could not read: not resolved
    assert t("ALIAS", {"ALIAS": ["g_c"]}, {"ALIAS"}) is None and t("ALIAS", {"ALIAS": ["g_c"]}, None) is None
    # (review round 2 C1') a chain end no read file declares — an unread header's macro, a -D — may be anything
    assert t("ALIAS", {"ALIAS": ["MID"]}, set()) is None and t("ALIAS", {"ALIAS": ["MID"]}, set(), {"MID"}) == {"MID"}


def test_a_write_through_an_alias_of_an_unread_name_stays_an_unknown_callee():
    # (review round 2 C1', gcc: 2 — ``MID`` is ``boot.s`` in the header the context could not read)
    text = '#include "w.h"\n#include "cfg.h"\n#define ALIAS MID\nvoid reset(void) { ALIAS = 0U; }\n'
    closure = cpc.function_write_closure(_ctx({"a.c": text}))["functions"]
    assert closure["reset"]["unknown_callees"] == {"macro_write:ALIAS"}


def test_no_alias_is_resolved_when_the_context_has_an_unread_header():
    # (review round 3 C1'', gcc: 2) ``MID`` is a global in o.c and, for r.c, the unread cfg.h's ``#define MID boot.s``:
    # with a quoted include found nowhere (or a file the source stage could not read) no chain is resolved
    files = {"a.c": '#include "w.h"\n#include "cfg.h"\n#define ALIAS MID\nvoid reset(void) { ALIAS = 0U; }\n',
             "o.c": '#include "w.h"\nU8 MID;\n'}
    assert cpc.function_write_closure(_ctx(files))["functions"]["reset"]["unknown_callees"] == {"macro_write:ALIAS"}
    files["a.c"] = files["a.c"].replace('#include "cfg.h"\n', "")
    assert not cpc.function_write_closure(_ctx(files))["functions"]["reset"]["unknown_callees"]
    built = _ctx(files)
    built["incomplete_files"] = [os.path.join(ROOT, "gone.h")]
    assert cpc.function_write_closure(built)["functions"]["reset"]["unknown_callees"] == {"macro_write:ALIAS"}
    # (review round 4 I1) said where it is said: the reading summary and its disclosure
    assert cpc.designator_gap(built) == "unread_files:gone.h" and cpc.designator_gap(_ctx(files)) == ""
    files["a.c"] = '#include "cfg.h"\n' + files["a.c"]
    assert cpc.designator_gap(_ctx(files)) == "include_not_found:a.c:cfg.h"


def test_a_write_through_a_build_define_stays_an_unknown_callee():
    # (review round 4, as HEAD; gcc -DALIAS=g_c: 2) a name only the build defines is no object the closure can name
    cp = _cp().replace('superClass="com.freescale.s12z.toolchain.compiler">',
                       'superClass="com.freescale.s12z.toolchain.compiler"><option id="d" superClass="x.compiler.option.'
                       'defs" valueType="definedSymbols"><listOptionValue value="ALIAS=g_c"/></option>')
    files = {os.path.join(ROOT, "w.h"): TYPES,
             A_C: '#include "w.h"\nU8 g_c;\nvoid reset(void) { ALIAS = 0U; }\n'}
    built = cpc.build_project_context(files, cpc.detect_build_config({os.path.join(ROOT, ".cproject"): cp}), roots=[ROOT])
    assert built["build"]["configurations"][os.path.join(ROOT, ".cproject")]["defines"] == {"ALIAS": "g_c"}
    assert cpc.function_write_closure(built)["functions"]["reset"]["unknown_callees"] == {"macro_write:ALIAS"}


def test_a_brace_near_a_cplusplus_line_is_benign_only_inside_its_group():
    # (review round 3 I2) ``#endif /* __cplusplus */`` before a lone ``}`` is no extern "C" group
    ok = b'#ifdef __cplusplus\nextern "C" {\n#endif\nint k;\n#ifdef __cplusplus\n}\n#endif\n'
    bad = b"#ifdef __cplusplus\n#endif /* __cplusplus */\nint g;\n}\nint h;\n"
    for raw, kind in ((bad, "unmatched_brace"),):
        out, _ = cpc.reading_text(raw)
        root = cpc.shared_parser().parse(out).root_node
        assert kind in cpc._parse_error_leaves(root, out, cpc._file_walk(root, out)["spans"])["kinds"]
    out, _ = cpc.reading_text(ok)
    root = cpc.shared_parser().parse(out).root_node
    kinds = cpc._parse_error_leaves(root, out, cpc._file_walk(root, out)["spans"])["kinds"]
    assert "unmatched_brace" not in kinds and "lost_structure" not in kinds


def test_a_write_through_a_body_local_macro_stays_an_unknown_callee():
    # (review round 2 W3, gcc: 2) ``#define ALIAS2 g_tmp`` only inside other(): the write is g_tmp's, not "ALIAS2"'s
    text = ('#include "w.h"\nU8 g_tmp;\nvoid other(void) {\n#define ALIAS2 g_tmp\n ALIAS2 = 0U;\n#undef ALIAS2\n}\n')
    closure = cpc.function_write_closure(_ctx({"a.c": text}))["functions"]
    assert closure["other"]["unknown_callees"] == {"macro_write:ALIAS2"}


def test_a_write_through_an_alias_a_body_redefines_stays_an_unknown_callee():
    # (review round 1 C1, gcc: 2 — the body's #define ALIAS g_other is the one the write uses)
    text = ('#include "w.h"\nU8 g_c;\nU8 g_other;\n#define ALIAS g_c\n'
            "void reset(void) {\n#undef ALIAS\n#define ALIAS g_other\n ALIAS = 0U;\n}\n")
    closure = cpc.function_write_closure(_ctx({"a.c": text}))["functions"]
    assert closure["reset"]["unknown_callees"] == {"macro_write:ALIAS"}


# ── what is left, disclosed ───────────────────────────────────────────────────────────────────────

def test_parse_errors_left_are_counted_by_kind():
    raw = b"void f(void) { asm PSH CCL; }\nint x;\n) ) (\nint y;\n"
    out, _ = cpc.reading_text(raw)
    root = cpc.shared_parser().parse(out).root_node
    kinds = cpc._parse_error_leaves(root, out, [])["kinds"]
    assert kinds.get("asm") and kinds.get("declaration")


def test_benign_parse_errors_are_not_unknown_declarations():
    # (review round 1 W1) a parser-supplied token, a brace a C++ linkage block leaves, an asm block's own lines
    for raw, kind in ((b"typedef enum { A_IDX, B_IDX };\nint x;\n", "missing_token"),
                      (b"int x;\n}\nint y;\n", "unmatched_brace"),
                      (b"static void z(void)\n{\n  __asm {\n    LD Y, x\n    DBNE D6, loop\n  end:\n  }\n}\n", "asm")):
        out, _ = cpc.reading_text(raw)
        kinds = cpc._parse_error_leaves(cpc.shared_parser().parse(out).root_node, out, [])["kinds"]
        assert kind in kinds and "declaration" not in kinds, (raw, kinds)


def test_errors_on_an_asm_block_s_own_lines_are_asm():
    # (review round 2 I3) ``DBNE D6, loop`` says no ``asm`` — the block around it does (`_asm_spans`)
    raw = (b"static void DoZero(void)\n{\n  __asm\n  {\n    zeroOutLoop:\n    DBNE D6, zeroOutLoop\n  end:\n  }\n}\n"
           b"int after;\n")
    out, _ = cpc.reading_text(raw)
    root = cpc.shared_parser().parse(out).root_node
    assert set(cpc._parse_error_leaves(root, out, cpc._file_walk(root, out)["spans"])["kinds"]) == {"asm"}


def test_a_macro_that_hides_a_brace_is_lost_structure_not_harmless():
    # (review round 2 W1) the opening brace hidden: the function is cut short; the closing one hidden: the rest of the
    # file is something else. Both are told, and the macros are named
    from report_gen.generation_disclosures import build_disclosures
    for raw, kind, macro in ((b"int g_ready, g_o;\n#define IF_READY if (g_ready) {\nvoid f(void) { IF_READY g_o = 1U; } }\n",
                              "unmatched_brace", "IF_READY"),
                             (b"int g_a;\n#define CRIT_END() }\nvoid f(void) { if (g_a) { g_a = 1; CRIT_END() }\nint g_after;\n",
                              "lost_structure", "CRIT_END")):
        out, _ = cpc.reading_text(raw)
        root = cpc.shared_parser().parse(out).root_node
        w = cpc._file_walk(root, out)
        assert kind in cpc._parse_error_leaves(root, out, w["spans"])["kinds"] and w["unbalanced_brace_macros"] == [macro]
    item = [i for i in build_disclosures("suts", {"source_reading": {"files_read": 1, "parse_errors": {kind: 1},
                                                                     "unbalanced_brace_macros": ["a.c:CRIT_END"]}})
            if i["key"] == "suts_source_reading"][0]
    assert item["tone"] == "warning" and "CRIT_END" in item["note"]


def test_only_value_neutral_attributes_are_blanked():
    # (review round 1 W3) ``mode`` / ``vector_size`` / ``packed`` change a width or a layout: left unread
    assert cpc.reading_text(b"int x __attribute__((aligned(4), unused));\n")[1] == {"attribute": 1}
    for attr in (b"mode(QI)", b"vector_size(8)", b"packed", b"aligned(4), packed"):
        raw = b"int x __attribute__((" + attr + b"));\n"
        assert cpc.reading_text(raw) == (raw, {})


def test_a_crlf_splice_continues_a_line_comment_for_the_mask():
    # (review round 1 I5) ``// x \<CR><LF> __far`` is still the comment: nothing blanked
    raw = b"// note \\\r\n __far @0x10\r\nint x;\r\n"
    assert cpc.reading_text(raw) == (raw, {})


def test_the_reading_is_summarized_for_the_document_and_disclosed():
    from report_gen.generation_disclosures import build_disclosures
    ctx = _ctx({"r.h": REGS, "a.c": '#include "r.h"\nvoid f(void) { asm(BGND); }\n'})
    ctx["incomplete_files"] = [os.path.join(ROOT, "gone.c")]
    scope = cpc.build_scopes(ctx, [A_C])[A_C]
    s = cpc.summarize_source_reading(ctx, [scope])
    assert s["files_read"] == 2 and s["vendor_blanks"] == {"address_placement": 1}
    assert s["directives_beyond_tree"] == {"define": 2} and s["files_with_asm"] == 1 and s["context_unread_files"] == 1
    assert s["context_unread_included"] == [] and s["unit_files_text_changed"] == 0
    assert cpc.summarize_source_reading(ctx, [None]) == {}
    items = [i for i in build_disclosures("suts", {"source_reading": s}) if i["key"] == "suts_source_reading"]
    assert len(items) == 1 and items[0]["tone"] == "warning"
    assert "@주소 배치 1" in items[0]["note"] and "gone.c" in items[0]["note"] and "#define 2" in items[0]["note"]
    sits = [i for i in build_disclosures("sits", {"integration_oracle": {"source_reading": s}})
            if i["key"] == "sits_source_reading"]
    assert len(sits) == 1
    assert not [i for i in build_disclosures("suts", {"source_reading": {}}) if i["key"] == "suts_source_reading"]


# ── the independent clang check reaches the register-writing functions ────────────────────────────

def test_a_register_the_scope_does_not_model_gets_a_stand_in_in_the_clang_harness():
    # (R63) ``#define REG_BYTE _REG.Byte`` is readable now; the harness did not declare ``_REG`` (a volatile union of the
    # register header) and the whole function was unchecked. A struct of the member paths the code names stands in —
    # the oracle claims nothing resting on a register's value
    import shutil
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parents[2] / "scripts"))
    from source_oracle_clang_check import _harness, _register_struct_text, check_claims

    from generators.c_source_oracle import _find_function
    assert _register_struct_text(["Byte", "Bits.PTP3"]) == \
        "struct { unsigned long long Byte; struct { unsigned long long PTP3; } Bits; }"
    assert _register_struct_text(["Bits", "Bits.PTP3"]) is None
    text = '#include "r.h"\nU8 g_a;\nU8 g_o;\nvoid f(void) { REG_BYTE = g_a; g_o = (U8)(g_a + 1U); }\n'
    scope = _scope({"r.h": REGS, "a.c": text})
    assert "_REG" in scope["unresolved_globals"]
    raw = cpc.apply_body_projection(scope, text).encode()
    unit = {"name": "f", "source_text": raw.decode(), "source_path": A_C, "source_text_complete": True,
            "project_scope": scope}
    fn = _find_function(cpc.shared_parser().parse(raw).root_node, raw, "f", scope)
    claim = {"unit": unit, "inputs": {"g_a": 3}, "outputs": {"g_o": 4}}
    source, _checks, reason, _meta = _harness(unit, [claim], fn, raw)
    assert reason == "" and "struct { unsigned long long Byte; } _REG = {};" in source
    clang = shutil.which("clang") or (r"C:\msys64\mingw64\bin\clang.exe" if _P(r"C:\msys64\mingw64\bin\clang.exe").exists()
                                      else None)
    if clang:
        report = check_claims([claim], clang=clang)
        assert (report["checked"], report["agree"], report["mismatch"]) == (1, 1, 0)

