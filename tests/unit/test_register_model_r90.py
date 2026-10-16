"""R90 — union / bit-field objects (memory-mapped registers) are one storage every member reads and writes.

HDPDM01's SITS refused ~10,400 expected cells on registers: ``REG_LP0CR.Bits.LPE`` was ``observable_not_a_modeled_object``,
``REG_TIM0TC2`` ``global_unmodeled:typedef_not_scalar`` — a union was never laid out, a bit-field member never kept, and a
volatile read was unknown. The project context now keeps a union's and a bit-field struct's members (widths, unnamed
padding fields, ``#define`` lines among them) and lays a union / bit-field global out on first use (`_storage_object`):
each member's value bits at fixed storage bits, under each layout the target may use (byte order, bit-field unit),
checked against the header's own ``NAME_MASK`` / ``NAME_BITNUM`` macros. The source oracle keeps the object's bits in
the store (``REG.@order:bit``): a write through one member is what every other member reads, a bit the run did not
write holds what the row's inputs set (any member, or the object's name for its whole-object member), a value is given
only where every layout agrees, and a volatile register is read as memory (the VectorCAST harness holds it as one).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from generators import c_project_context as cpc
from generators.c_source_oracle import evaluate_outputs

ROOT = os.path.join(os.sep, "p90")
H = """typedef unsigned char U8;
typedef unsigned int U16;
typedef signed char S8;
/*** LP0CR - an 8-bit register (Processor Expert layout) ***/
typedef union {
  U8 Byte;
  struct {
    U8 LPPUE       :1;
    U8 LPWUE       :1;
    U8             :1;
    U8 LPE         :1;
    U8 MODE        :2;
    U8             :1;
    U8             :1;
  } Bits;
} LP0CRSTR;
extern volatile LP0CRSTR REG_LP0CR @0x00000981;
#define LP0CR                           REG_LP0CR.Byte
#define LP0CR_LPPUE                     REG_LP0CR.Bits.LPPUE
#define LP0CR_LPE                       REG_LP0CR.Bits.LPE
#define LP0CR_MODE                      REG_LP0CR.Bits.MODE
#define LP0CR_LPPUE_MASK                0x01U
#define LP0CR_LPE_MASK                  0x08U
#define LP0CR_MODE_MASK                 0x30U
#define LP0CR_MODE_BITNUM               0x04U
/*** CTL - a 16-bit register: a word, two overlapped bytes, 16-bit bit-fields ***/
typedef union {
  U16 Word;
  struct {
    union {
      U8 Byte;
      #define CTL0                      REG_CTL.Overlap_STR.CTL0STR.Byte
    } CTL0STR;
    union {
      U8 Byte;
      struct {
        U8 LOW0 :1;
        U8      :7;
      } Bits;
    } CTL1STR;
  } Overlap_STR;
  struct {
    U16 LOW0   :1;
    U16        :7;
    U16 HIGH0  :1;
    U16        :7;
  } Bits;
} CTLSTR;
extern volatile CTLSTR REG_CTL @0x00000600;
#define CTL                             REG_CTL.Word
#define CTL1                            REG_CTL.Overlap_STR.CTL1STR.Byte
#define CTL_LOW0                        REG_CTL.Bits.LOW0
#define CTL_HIGH0                       REG_CTL.Bits.HIGH0
#define CTL_LOW0_MASK                   0x01U
#define CTL_HIGH0_MASK                  0x0100U
/* an address a macro hands out (Processor Expert ``…_ARR``) */
#define LP0CR_PTR                       ((volatile U8 *)&LP0CR)
/* the same 16-bit register without a mask: byte-by-byte bit-field allocation is not ruled out */
typedef union {
  U16 Word;
  struct {
    U16 LOW0   :1;
    U16        :7;
    U16 HIGH0  :1;
    U16        :7;
  } Bits;
} NMSTR;
extern volatile NMSTR REG_NM @0x00000700;
/* a mask the LSB-first allocation contradicts */
typedef union { U8 Byte; struct { U8 A :1; U8 :7; } Bits; } BADSTR;
extern volatile BADSTR REG_BAD @0x00000800;
#define BAD_A REG_BAD.Bits.A
#define BAD_A_MASK 0x80U
/* layouts the model does not state */
typedef union { U8 Byte; struct { S8 s :3; U8 :5; } Bits; } SGNSTR;
typedef union { U8 Byte; struct { U8 a :6; U8 b :4; } Bits; } STRSTR;
typedef union { U16 w; struct { U8 a; U16 b; } s; } PADSTR;
typedef union { U8 Byte; struct { U8 a :1; } Bits; U8 arr[1]; } ARRSTR;
typedef union { U16 Word; struct { U16 a :4; } Bits; } PARTSTR;
typedef union { U8 Byte; U8 Raw; } TWOSTR;
SGNSTR g_sgn;
STRSTR g_str;
PADSTR g_pad;
ARRSTR g_arr;
PARTSTR g_part;
TWOSTR g_two;
/* a plain struct with bit-fields (no register) */
typedef struct { U8 f :3; U8 k; } TB;
/* a merged field crossing a byte: the masks of the single bits rule the byte-by-byte allocation out */
typedef union {
  U16 Word;
  struct { U16 B0 :1; U16 :7; U16 B8 :1; U16 :7; } Bits;
  struct { U16 :1; U16 grp :15; } MergedBits;
} MRGSTR;
extern volatile MRGSTR REG_MRG @0x00000900;
#define MRG_B8 REG_MRG.Bits.B8
#define MRG_B8_MASK 0x0100U
/* ... and without a mask: where a byte-by-byte allocation puts it is the compiler's */
typedef union { U16 Word; struct { U16 :1; U16 grp :15; } MergedBits; } MRG2STR;
MRG2STR g_mrg2;
/* a struct R39 does not flatten for a reason of its own (no member it models): no storage object either */
typedef struct { U8 *p; } TPS;
TPS g_tps;
/* (review C1) signed members that are no bit-fields */
typedef signed int S16;
typedef struct { U8 f :3; S8 k; } TS;
TS g_ts;
typedef union { U8 Byte; S8 sb; } SBSTR;
SBSTR g_sb;
typedef union { U16 Word; S16 sw; } SWSTR;
SWSTR g_sw;
/* (review C2) registers placed next to each other (FCCOB2..FCCOB5 on S12Z) */
typedef union { U8 Byte; } R8STR;
extern volatile R8STR REG_R0 @0x00000380;
extern volatile R8STR REG_R1 @0x00000381;
#define R0 REG_R0.Byte
#define R1 REG_R1.Byte
/* (review W1) a polled hardware flag */
typedef union { U8 Byte; struct { U8 RSTA :1; U8 :7; } Bits; } FLWSTR;
extern volatile FLWSTR REG_FLW @0x00000390;
#define FLW REG_FLW.Byte
#define FLW_RSTA REG_FLW.Bits.RSTA
#define FLW_RSTA_MASK 0x01U
"""
C = """#include "h.h"
U8 g_o;
U16 g_w;
TB gb;
U8 *g_p;
void ext(void);
void nowhere(void);
void w_byte_then_bit(void) { LP0CR = 0x05U; LP0CR_LPE = 1U; }
void w_bit(void) { LP0CR_LPE = 1U; }
void w_field(void) { LP0CR_MODE = 7U; g_o = (U8)LP0CR; }
void w_or(void) { LP0CR |= 0x40U; }
void w_inc(void) { LP0CR_MODE++; }
void w_value(void) { g_o = (U8)(REG_LP0CR.Bits.MODE = 5U); }
void w_word(void) { CTL = 0x1234U; g_o = CTL1; g_w = CTL; }
void w_low_byte(void) { CTL1 = 0x56U; g_w = CTL; }
void w_high_bit(void) { CTL_HIGH0 = 1U; g_w = CTL; }
void w_nm(void) { REG_NM.Bits.HIGH0 = 1U; g_w = REG_NM.Word; }
void r_bit(void) { if (LP0CR_LPE) { g_o = 1U; } else { g_o = 2U; } }
void r_volatile(void) { LP0CR = 0x21U; g_o = LP0CR; }
void w_then_ext(void) { LP0CR = 0x05U; ext(); }
void w_then_unknown(void) { LP0CR = 0x05U; nowhere(); }
void w_escape(void) { LP0CR = 0x05U; g_p = &REG_LP0CR.Byte; *g_p = 9U; }
void w_struct(void) { gb.f = 9U; gb.k = 4U; }
void w_part(void) { g_part.Bits.a = 1U; }
LP0CRSTR g_save;
U8 g_tab[4];
void wr_reg(void);
void w_sub(void) { LP0CR = 0x05U; REG_LP0CR.Bits = g_save.Bits; }
void w_unknown_then_read(void) { nowhere(); g_o = LP0CR_LPE; }
void r_promote(void) { g_w = (U16)((REG_CTL.Bits.HIGH0 - 2) < 0); }
void w_plain(void) { g_tab[0] = 1U; wr_reg(); g_o = g_tab[0]; }
U8 rd_reg(void);
void w_seq(void) { g_tab[0] = 2U; g_o = (U8)(g_tab[0] + rd_reg()); }
void w_escape_macro(void) { LP0CR = 0x05U; g_p = LP0CR_PTR; *g_p = 9U; }
void cond_bit(U8 c);
void wr_r0_next(void);
void w_join(U8 c) { cond_bit(c); }
S8 g_s8;
S16 g_s16;
void c1_ts(void) { g_ts.k = -5; g_o = (U8)(g_ts.k + 10); }
void c1_sb(void) { g_sb.Byte = 0xFFU; g_s8 = g_sb.sb; }
void c1_sw(void) { g_sw.Word = 0x8000U; g_s16 = g_sw.sw; }
void c1_in(void) { g_s8 = g_sb.sb; }
void c2_offset(void) { R0 = 1U; R1 = 2U; *((volatile U8 *)&R0 + 1) = 9U; }
void c2_zero(void) { R1 = 2U; *((volatile U8 *)&R0 + 0) = 9U; }
void c2_via_callee(void) { R1 = 2U; wr_r0_next(); }
void w1_poll(void) { FLW = 0x01U; while (FLW_RSTA == 1U) {} g_o = 7U; }
void w1_poll_input(void) { while (FLW_RSTA == 1U) {} g_o = 8U; }
void w1_plain(void) { while (g_o == 1U) {} }
void w3_none(void) { g_o = 1U; }
void cfg(void);
void w_by_name(void) { cfg(); }
void w_escape_ram(void) { g_sb.Byte = 5U; g_p = &g_sb.Byte; *g_p = 9U; }
"""
LIB = """#include "h.h"
extern LP0CRSTR g_save;
void ext(void) { g_o = 0U; }
void set_lpe(void) { LP0CR_LPE = 1U; }
void cfg(void) { LP0CR = 0x10U; set_lpe(); }
void wr_reg(void) { REG_LP0CR = g_save; }
U8 rd_reg(void) { REG_LP0CR = g_save; return 1U; }
void cond_bit(U8 c) { if (c != 0U) { LP0CR_LPE = 1U; LP0CR_LPPUE = 1U; } else { LP0CR_LPPUE = 1U; } }
void wr_r0_next(void) { volatile U8 *p = &R0; p[1] = 9U; }
"""
# (world) an entry whose unit does not declare the register; a static register-like object in two units; one name laid
#   out differently by two headers
EXTRA = {
    "n.c": "void cfg(void);\nvoid nodecl(void) { cfg(); }\n",
    "s1.c": '#include "h.h"\nstatic LP0CRSTR s_reg;\nvoid s2(void);\nvoid s1(void) { s_reg.Byte = 1U; s2(); }\n',
    "s2.c": '#include "h.h"\nstatic LP0CRSTR s_reg;\nvoid s2(void) { s_reg.Byte = 2U; }\n',
    "ha.h": "typedef unsigned char U8;\ntypedef union { U8 Byte; struct { U8 a :1; U8 :7; } Bits; } QSTR;\n"
            "extern volatile QSTR REG_Q;\n",
    "hb.h": "typedef unsigned char U8;\ntypedef union { U8 Byte; struct { U8 :7; U8 a :1; } Bits; } QSTR;\n"
            "extern volatile QSTR REG_Q;\n",
    "qa.c": '#include "ha.h"\nvoid qb(void);\nvoid qa(void) { REG_Q.Bits.a = 1U; qb(); }\n',
    "qb.c": '#include "hb.h"\nvoid qb(void) { REG_Q.Bits.a = 0U; }\n',
}


def _context():
    files = {os.path.join(ROOT, "h.h"): H, os.path.join(ROOT, "u.c"): C, os.path.join(ROOT, "l.c"): LIB,
             **{os.path.join(ROOT, k): v for k, v in EXTRA.items()}}
    return files, cpc.build_project_context(files)


FILES, CONTEXT = _context()
PATH = os.path.join(ROOT, "u.c")
LPATH = os.path.join(ROOT, "l.c")
UNITS = [p for p in FILES if p.endswith(".c")]
SCOPES = cpc.build_scopes(CONTEXT, UNITS)
SCOPE = SCOPES[PATH]


def _provider():
    from generators.integration_oracle import CalleeProvider
    return CalleeProvider(CONTEXT, FILES, SCOPES, cpc.shared_parser())


def _run(name, inputs, outs, path=PATH, provider=None):
    unit = {"name": name, "source_text": FILES[path], "source_path": path, "source_text_complete": True,
            "project_scope": SCOPES[path]}
    if provider is not None:
        unit["callee_provider"] = provider
    (r,) = evaluate_outputs(unit, [inputs], [outs])
    return r


def _out(name, inputs, outs, **kw):
    return _run(name, inputs, outs, **kw)["outputs"]


def _layout(name):
    table = SCOPE["storage_globals"]
    return table[name] if name in table else None


# ── project context: what the header's bodies record ──────────────────────────────────────────────────────────────

def _structs():
    return CONTEXT["files"][os.path.join(ROOT, "h.h")]["structs"]


def _body(typedef):
    structs = _structs()
    return structs[structs[typedef][0]["alias"]][0]


def test_a_union_keeps_its_members_and_bit_widths_and_padding():
    body = _body("LP0CRSTR")
    assert [m["name"] for m in body["members"]] == ["Byte", "Bits"]
    bits = _structs()[body["members"][1]["type"]][0]
    assert [(m["name"], m["bits"]) for m in bits["members"]] == [
        ("LPPUE", "1"), ("LPWUE", "1"), ("", "1"), ("LPE", "1"), ("MODE", "2"), ("", "1"), ("", "1")]
    # an unnamed bit-field is padding: it hides nothing from the storage model; R39 still reads the body as hidden
    assert not bits["storage_hidden"] and bits["hidden"]


def test_a_define_among_members_hides_nothing_from_the_storage_model_but_r39_still_refuses():
    overlap = _structs()[_body("CTLSTR")["members"][1]["type"]][0]
    ctl0 = _structs()[overlap["members"][0]["type"]][0]
    assert [m["name"] for m in ctl0["members"]] == ["Byte"] and not ctl0["storage_hidden"] and ctl0["hidden"]


def test_an_if_around_a_member_hides_it():
    files = {os.path.join(ROOT, "x.h"): "typedef unsigned char U8;\ntypedef union {\n U8 a;\n#if X\n U8 b;\n#endif\n} XU;\n"}
    ctx = cpc.build_project_context(files)
    rec = ctx["files"][os.path.join(ROOT, "x.h")]["structs"]
    body = rec[rec["XU"][0]["alias"]][0]
    assert body["storage_hidden"] and body["hidden"]


# ── layouts ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_8_bit_register_is_one_layout_and_its_masks_confirm_it():
    lay = _layout("REG_LP0CR")
    assert lay["size"] == 1 and lay["orders"] == ["le"] and lay["whole"] == "Byte" and lay["volatile"]
    assert lay["masks_checked"] == 3   # LPPUE, LPE, MODE (MASK + BITNUM)
    assert {p: leaf["bits"]["le"] for p, leaf in lay["leaves"].items()} == {
        "Byte": tuple(range(8)), "Bits.LPPUE": (0,), "Bits.LPWUE": (1,), "Bits.LPE": (3,), "Bits.MODE": (4, 5)}


def test_a_16_bit_register_keeps_both_byte_orders_and_its_mask_rules_out_byte_units():
    lay = _layout("REG_CTL")
    assert lay["size"] == 2 and lay["whole"] == "Word" and lay["orders"] == ["le", "be"]
    leaves = lay["leaves"]
    assert leaves["Bits.HIGH0"]["bits"] == {"le": (8,), "be": (0,)}       # bit 8 of the word, either order
    assert leaves["Overlap_STR.CTL0STR.Byte"]["bits"]["be"] == tuple(range(8))   # byte 0: the word's high byte on S12Z
    assert leaves["Word"]["bits"]["be"][8:] == tuple(range(8))
    assert leaves["Overlap_STR.CTL1STR.Bits.LOW0"]["bits"] == {"le": (8,), "be": (8,)}
    nm = _layout("REG_NM")   # no mask: a byte-by-byte allocation stays possible — (re-review W-N2) and, no build target
    #   naming the compiler, an allocation from the most significant bit
    assert nm["orders"] == ["le", "be", "be_bytes", "le_msb", "be_msb"]
    assert nm["leaves"]["Bits.HIGH0"]["bits"]["be_bytes"] == (8,)
    assert nm["leaves"]["Bits.HIGH0"]["bits"]["le_msb"] == (7,) and nm["leaves"]["Bits.LOW0"]["bits"]["be_msb"] == (7,)


def test_a_mask_the_layout_contradicts_refuses_the_object():
    assert _layout("REG_BAD") is None
    assert SCOPE["storage_unresolved"]["REG_BAD"] == "layout_contradicts_header_mask:BAD_A_MASK"


@pytest.mark.parametrize("name, reason", [
    ("g_sgn", "signed_bit_field:Bits.s"),
    ("g_str", "bit_field_straddles_unit:Bits.b"),
    ("g_pad", "layout_padding_implementation_defined:s.b"),
    ("g_arr", "member_not_scalar:arr:array"),
    ("g_part", "bit_field_unit_not_full:Bits"),
])
def test_a_layout_the_model_cannot_state_is_refused_with_its_reason(name, reason):
    assert _layout(name) is None
    assert SCOPE["storage_unresolved"][name] == reason


def test_a_field_crossing_a_byte_is_placed_when_a_mask_rules_byte_units_out():
    lay = _layout("REG_MRG")
    assert lay["orders"] == ["le", "be"] and lay["leaves"]["MergedBits.grp"]["bits"]["le"] == tuple(range(1, 16))
    assert _layout("g_mrg2") is None
    assert SCOPE["storage_unresolved"]["g_mrg2"] == "bit_field_byte_allocation_unmodeled"


def test_a_struct_without_a_union_or_a_bit_field_stays_r39s():
    assert "g_tps" not in SCOPE["storage_candidates"] and "g_tps" not in SCOPE["struct_globals"]
    assert _out("w_bit", {}, ["g_tps.p"])["g_tps.p"]["reason"] == "observable_not_a_modeled_object:g_tps.p"


def test_two_whole_object_members_leave_the_object_without_one():
    assert _layout("g_two")["whole"] is None


def test_a_plain_struct_with_bit_fields_is_laid_out_and_r39_still_does_not_flatten_it():
    lay = _layout("gb")
    assert lay["leaves"]["f"]["bits"]["le"] == (0, 1, 2) and lay["leaves"]["k"]["bits"]["le"] == tuple(range(8, 16))
    assert "gb" not in SCOPE["struct_globals"]


# ── source oracle: one storage behind every member ───────────────────────────────────────────────────────────────

def test_a_write_through_the_byte_is_what_the_bits_read_and_the_reverse():
    out = _out("w_byte_then_bit", {}, ["REG_LP0CR.Byte", "REG_LP0CR.Bits.LPE", "REG_LP0CR.Bits.LPPUE",
                                       "REG_LP0CR.Bits.MODE", "REG_LP0CR"])
    assert out["REG_LP0CR.Byte"] == {"value": 0x0D, "basis": "assigned"}
    assert out["REG_LP0CR.Bits.LPE"]["value"] == 1 and out["REG_LP0CR.Bits.LPPUE"]["value"] == 1
    assert out["REG_LP0CR.Bits.MODE"]["value"] == 0
    assert out["REG_LP0CR"] == {"value": 0x0D, "basis": "assigned"}   # the object: its whole-object member


def test_a_partial_write_keeps_the_other_bits_from_the_inputs():
    out = _out("w_bit", {"REG_LP0CR.Byte": 0x31}, ["REG_LP0CR.Byte", "REG_LP0CR.Bits.LPPUE", "REG_LP0CR.Bits.LPE"])
    assert out["REG_LP0CR.Byte"]["value"] == 0x39
    assert out["REG_LP0CR.Bits.LPPUE"] == {"value": 1, "basis": "unchanged_input"}
    assert out["REG_LP0CR.Bits.LPE"] == {"value": 1, "basis": "assigned"}


def test_a_partial_write_without_inputs_leaves_the_rest_unknown_never_invented():
    out = _out("w_bit", {}, ["REG_LP0CR.Byte", "REG_LP0CR.Bits.LPE", "REG_LP0CR.Bits.LPPUE"])
    assert out["REG_LP0CR.Bits.LPE"]["value"] == 1
    assert "value" not in out["REG_LP0CR.Byte"] and "value" not in out["REG_LP0CR.Bits.LPPUE"]
    assert out["REG_LP0CR.Byte"]["reason"].endswith("initial_not_in_inputs:REG_LP0CR.Byte")


def test_a_bit_field_keeps_its_low_bits_and_the_byte_reads_them():
    out = _out("w_field", {"REG_LP0CR": 0}, ["g_o", "REG_LP0CR.Bits.MODE"])
    assert out["g_o"]["value"] == 0x30 and out["REG_LP0CR.Bits.MODE"]["value"] == 3


def test_compound_and_increment_writes_read_the_storage_first():
    # ``|=`` stores the whole byte: every bit of it is written (with the value it held where the mask has 0)
    assert _out("w_or", {"REG_LP0CR.Byte": 0x05}, ["REG_LP0CR.Bits.LPPUE", "REG_LP0CR.Byte"]) == {
        "REG_LP0CR.Bits.LPPUE": {"value": 1, "basis": "assigned"}, "REG_LP0CR.Byte": {"value": 0x45, "basis": "assigned"}}
    out = _out("w_inc", {"REG_LP0CR.Byte": 0x30}, ["REG_LP0CR.Bits.MODE", "REG_LP0CR.Byte"])
    assert out["REG_LP0CR.Bits.MODE"]["value"] == 0 and out["REG_LP0CR.Byte"]["value"] == 0   # 3 + 1 wraps in 2 bits


def test_an_assignment_to_a_bit_field_has_the_stored_value():
    assert _out("w_value", {"REG_LP0CR.Byte": 0}, ["g_o"])["g_o"]["value"] == 1   # 5 in 2 bits


def test_inputs_set_any_member_and_a_bit_they_disagree_on_is_unknown():
    assert _out("r_bit", {"REG_LP0CR.Byte": 0x08}, ["g_o"])["g_o"]["value"] == 1
    assert _out("r_bit", {"REG_LP0CR.Bits.LPE": 0}, ["g_o"])["g_o"]["value"] == 2
    assert _out("r_bit", {"REG_LP0CR": 0x08}, ["g_o"])["g_o"]["value"] == 1   # the object's name: its whole member
    assert _out("r_bit", {"REG_LP0CR.Byte": 0x08, "REG_LP0CR.Bits.LPE": 1}, ["g_o"])["g_o"]["value"] == 1
    out = _out("r_bit", {"REG_LP0CR.Byte": 0x08, "REG_LP0CR.Bits.LPE": 0}, ["g_o"])
    assert "value" not in out["g_o"] and "input_members_disagree:REG_LP0CR" in out["g_o"]["reason"]
    # members that disagree on other bits only: the bit read is still known
    assert _out("r_bit", {"REG_LP0CR.Byte": 0x09, "REG_LP0CR.Bits.LPPUE": 0}, ["g_o"])["g_o"]["value"] == 1


def test_an_input_a_member_cannot_hold_leaves_its_bits_unknown():
    out = _out("r_bit", {"REG_LP0CR.Bits.LPE": 127}, ["g_o"])
    assert "input_outside_declared_type:REG_LP0CR.Bits.LPE" in out["g_o"]["reason"]
    # the written bits do not need it
    assert _out("w_bit", {"REG_LP0CR": 0, "REG_LP0CR.Bits.LPE": 127}, ["REG_LP0CR"])["REG_LP0CR"]["value"] == 0x08
    out = _out("w_bit", {"REG_LP0CR": 0, "REG_LP0CR.Bits.MODE": 9}, ["REG_LP0CR"])
    assert "input_outside_declared_type:REG_LP0CR.Bits.MODE" in out["REG_LP0CR"]["reason"]


def test_a_volatile_register_reads_what_the_run_wrote_and_the_assumption_says_so():
    r = _run("r_volatile", {}, ["g_o"])
    assert r["outputs"]["g_o"]["value"] == 0x21
    assert any(a.startswith("(R90) a volatile union / bit-field object") and a.endswith("REG_LP0CR")
               for a in r["assumptions"])
    assert any(a.startswith("(R90) a union / bit-field object is one storage") for a in r["assumptions"])
    assert r["storage_objects"] == ["REG_LP0CR"]


def test_a_value_through_a_member_of_another_width_needs_every_byte_order_to_agree():
    out = _out("w_word", {}, ["g_o", "g_w", "REG_CTL.Overlap_STR.CTL0STR.Byte"])
    assert out["g_w"]["value"] == 0x1234
    assert out["g_o"]["reason"] == "storage_member_layout_dependent:REG_CTL.Overlap_STR.CTL1STR.Byte"
    assert out["REG_CTL.Overlap_STR.CTL0STR.Byte"]["reason"].startswith("storage_member_layout_dependent:")
    out = _out("w_low_byte", {"REG_CTL.Word": 0x5656}, ["g_w", "REG_CTL.Overlap_STR.CTL1STR.Byte"])
    assert out["g_w"]["value"] == 0x5656   # both byte orders agree when both bytes are the same
    assert out["REG_CTL.Overlap_STR.CTL1STR.Byte"]["value"] == 0x56
    assert "value" not in _out("w_low_byte", {"REG_CTL.Word": 0x1234}, ["g_w"])["g_w"]


def test_a_16_bit_bit_field_reads_into_the_word_where_the_mask_pins_the_unit():
    out = _out("w_high_bit", {"REG_CTL": 0}, ["g_w", "REG_CTL.Bits.HIGH0", "REG_CTL.Bits.LOW0"])
    assert out["g_w"]["value"] == 0x0100 and out["REG_CTL.Bits.HIGH0"]["value"] == 1
    assert out["REG_CTL.Bits.LOW0"] == {"value": 0, "basis": "unchanged_input"}
    # without a mask the byte-by-byte allocation would put HIGH0 elsewhere in the word: no value
    assert _out("w_nm", {"REG_NM.Word": 0}, ["g_w"])["g_w"]["reason"] == "storage_member_layout_dependent:REG_NM.Word"


def test_an_unknown_callee_or_a_pointer_write_makes_the_object_unknown():
    # (re-review 4 C-R4-1) a callee the run does not interpret — its closure names no register — may still wait on one
    #   (through a pointer, a macro of its body): every register is unknown after it, the one the caller wrote too
    assert _out("w_then_ext", {}, ["REG_LP0CR.Bits.LPPUE"])["REG_LP0CR.Bits.LPPUE"] == {
        "reason": "register_read_by_callee_not_interpreted:ext"}
    out = _out("w_then_unknown", {}, ["REG_LP0CR.Byte", "REG_LP0CR.Bits.LPE"])
    assert all("value" not in v and v["reason"] == "unknown_callee:nowhere" for v in out.values())
    out = _out("w_escape", {}, ["REG_LP0CR.Bits.LPE", "REG_LP0CR.Byte"])
    assert all("value" not in v for v in out.values())


def test_a_pointer_write_reaches_an_ordinary_union_whose_address_escaped():
    out = _out("w_escape_ram", {"REG_CTL.Word": 0x1234}, ["g_sb.Byte", "g_sb.sb", "REG_CTL.Word"])
    assert "value" not in out["g_sb.Byte"] and "value" not in out["g_sb.sb"]
    # (review C2) and, since this project takes a register's address (``LP0CR_PTR``, ``&R0``), every register too
    assert out["REG_CTL.Word"] == {"reason": "write_through_pointer"}


def test_a_plain_bit_field_struct_is_modeled_too():
    out = _out("w_struct", {}, ["gb.f", "gb.k"])
    assert out == {"gb.f": {"value": 1, "basis": "assigned"}, "gb.k": {"value": 4, "basis": "assigned"}}


def test_an_object_without_a_layout_says_why():
    assert _out("w_part", {}, ["g_part.Bits.a"])["g_part.Bits.a"]["reason"] == \
        "storage_layout_unmodeled:g_part:bit_field_unit_not_full:Bits"
    assert _out("w_bit", {}, ["g_two"])["g_two"]["reason"] == "storage_whole_object_member_ambiguous:g_two"
    assert _out("w_bit", {}, ["REG_LP0CR.Bits"])["REG_LP0CR.Bits"]["reason"] == \
        "observable_not_a_storage_member:REG_LP0CR.Bits"


def test_integration_a_callee_writes_the_register_the_entry_observes():
    r = _run("cfg", {"REG_LP0CR.Bits.LPPUE": 1}, ["REG_LP0CR", "REG_LP0CR.Bits.LPE", "REG_LP0CR.Bits.LPPUE"],
             path=LPATH, provider=_provider())
    assert r["outputs"]["REG_LP0CR"]["value"] == 0x18 and r["outputs"]["REG_LP0CR.Bits.LPE"]["value"] == 1
    assert r["outputs"]["REG_LP0CR.Bits.LPPUE"] == {"value": 0, "basis": "assigned"}   # the byte write cleared it
    assert r["interprocedural"]["inlined"] == {"set_lpe": 1}


def test_a_write_to_part_of_the_object_changes_every_member():
    out = _out("w_sub", {}, ["REG_LP0CR.Byte", "REG_LP0CR.Bits.LPE"])
    assert all("value" not in v for v in out.values())


def test_an_unknown_callee_makes_the_unwritten_bits_unknown_too():
    out = _out("w_unknown_then_read", {"REG_LP0CR.Byte": 0x08}, ["g_o", "REG_LP0CR.Bits.LPPUE"])
    assert out["g_o"]["reason"] == "unknown_callee:nowhere" and "value" not in out["REG_LP0CR.Bits.LPPUE"]


def test_a_narrow_bit_field_is_an_int_operand_even_of_a_16_bit_unsigned_type():
    assert _out("r_promote", {"REG_CTL.Bits.HIGH0": 1}, ["g_w"])["g_w"]["value"] == 1   # 1 - 2 < 0 in int


def test_writing_the_whole_object_writes_nothing_through_it():
    # a union of integers holds no pointer: a callee run as its effects only that writes it reaches nothing else
    assert _out("w_plain", {}, ["g_o"])["g_o"]["value"] == 1
    # ... nor beside an array read in the same expression: the call is not unsequenced with ``g_tab[0]``
    r = _run("w_seq", {}, ["g_o"], provider=_provider())
    assert r["status"] == "supported" and r["outputs"]["g_o"]["value"] == 3


def test_a_callee_that_writes_a_bit_on_some_paths_leaves_the_rest_of_the_byte_known():
    r = _run("w_join", {"REG_LP0CR.Byte": 0}, ["REG_LP0CR.Bits.LPE", "REG_LP0CR.Bits.LPPUE", "REG_LP0CR.Bits.LPWUE"],
             provider=_provider())
    out = r["outputs"]
    assert r["interprocedural"]["inlined"] == {"cond_bit": 1}
    assert out["REG_LP0CR.Bits.LPE"]["reason"] == "path_dependent_in_callee:cond_bit"   # written on one path only
    assert out["REG_LP0CR.Bits.LPPUE"] == {"value": 1, "basis": "assigned"}             # written alike on both
    assert out["REG_LP0CR.Bits.LPWUE"] == {"value": 0, "basis": "unchanged_input"}      # written on none


def test_an_address_a_macro_hands_out_reaches_every_member():
    out = _out("w_escape_macro", {}, ["REG_LP0CR.Bits.LPE", "REG_LP0CR.Byte"])
    assert all("value" not in v for v in out.values()), out


def test_an_object_only_a_callee_unit_declares_is_observed_through_that_unit():
    r = _run("nodecl", {"REG_LP0CR.Byte": 0x01}, ["REG_LP0CR.Byte", "REG_LP0CR.Bits.LPE"],
             path=os.path.join(ROOT, "n.c"), provider=_provider())
    assert r["interprocedural"]["inlined"] == {"cfg": 1, "set_lpe": 1}
    assert r["outputs"]["REG_LP0CR.Byte"]["value"] == 0x18 and r["outputs"]["REG_LP0CR.Bits.LPE"]["value"] == 1


def test_a_static_object_of_two_units_is_ambiguous_in_the_integrated_run():
    r = _run("s1", {}, ["s_reg.Byte"], path=os.path.join(ROOT, "s1.c"), provider=_provider())
    assert r["outputs"]["s_reg.Byte"]["reason"].startswith("observable_name_ambiguous_in_project:")


def test_two_units_laying_one_object_out_differently_are_not_mixed():
    r = _run("qa", {"REG_Q.Byte": 0}, ["REG_Q.Byte"], path=os.path.join(ROOT, "qa.c"), provider=_provider())
    assert r["interprocedural"]["failed"] == {"qb": "storage_layout_differs_between_units:REG_Q"}
    assert "value" not in r["outputs"]["REG_Q.Byte"]


# ── the real S12Z header (read-only; skipped where the tree is absent) ───────────────────────────────────────────────

_S12Z = Path(r"D:\Project\Ados\PDS64_RD\Project_Headers\MC9S12ZVL64MLF_it_PDS.h")
_COMMON = _S12Z.with_name("Common_it_PDS.h")


@pytest.mark.skipif(not (_S12Z.is_file() and _COMMON.is_file()), reason="HDPDM01 headers not present")
def test_the_s12z_registers_lay_out_and_their_masks_agree():
    files = {str(_S12Z): _S12Z.read_bytes().decode("utf-8", "replace"),
             str(_COMMON): _COMMON.read_bytes().decode("utf-8", "replace"),
             os.path.join(str(_S12Z.parent), "probe_r90.c"): '#include "MC9S12ZVL64MLF_it_PDS.h"\n'}
    ctx = cpc.build_project_context(files)
    unit = os.path.join(str(_S12Z.parent), "probe_r90.c")
    scope = cpc.build_scopes(ctx, [unit])[unit]
    table = scope["storage_globals"]
    lp0cr = table["REG_LP0CR"]
    assert lp0cr["orders"] == ["le"] and lp0cr["leaves"]["Bits.LPE"]["bits"]["le"] == (3,) and lp0cr["masks_checked"] == 4
    tsc = table["REG_TIM0TSCR1"]
    assert tsc["leaves"]["Bits.TEN"]["bits"]["le"] == (7,) and tsc["whole"] == "Byte"
    adc = table["REG_ADC0CTL"]   # a word, two overlapped bytes with bits, 16-bit bits: masks rule out byte units
    assert adc["orders"] == ["le", "be"] and adc["masks_checked"] >= 20
    assert adc["leaves"]["Bits.MOD_CFG"]["bits"] == {"le": (8,), "be": (0,)}
    assert adc["leaves"]["Overlap_STR.ADC0CTL_0STR.Bits.MOD_CFG"]["bits"] == {"le": (0,), "be": (0,)}
    assert table["REG_TIM0TC2"]["whole"] == "Word"
    laid = sum(1 for n in scope["storage_candidates"] if n in table)
    assert laid >= 300, (laid, sorted(scope["storage_unresolved"].items())[:5])
    assert not any(v.startswith("layout_contradicts_header_mask") for v in scope["storage_unresolved"].values())


# ── (review C1) a signed member reads two's complement ──────────────────────────────────────────────────────────────

def test_a_signed_member_reads_back_its_value_not_its_bit_pattern():
    out = _out("c1_ts", {}, ["g_ts.k", "g_o"])
    assert out["g_ts.k"]["value"] == -5 and out["g_o"]["value"] == 5
    assert _out("c1_sb", {}, ["g_s8", "g_sb.sb", "g_sb.Byte"]) == {
        "g_s8": {"value": -1, "basis": "assigned"}, "g_sb.sb": {"value": -1, "basis": "assigned"},
        "g_sb.Byte": {"value": 255, "basis": "assigned"}}
    out = _out("c1_sw", {}, ["g_s16", "g_sw.Word"])
    assert out["g_s16"]["value"] == -32768 and out["g_sw.Word"]["value"] == 0x8000


def test_a_signed_member_input_is_its_value_and_sets_the_other_members_bits():
    assert _out("c1_in", {"g_sb.sb": -3}, ["g_s8", "g_sb.Byte"]) == {
        "g_s8": {"value": -3, "basis": "assigned"}, "g_sb.Byte": {"value": 253, "basis": "unchanged_input"}}
    assert _out("c1_in", {"g_sb.Byte": 0xFD}, ["g_s8"])["g_s8"]["value"] == -3
    assert "input_outside_declared_type" in _out("c1_in", {"g_sb.sb": 200}, ["g_s8"])["g_s8"]["reason"]


def test_the_assumption_names_twos_complement():
    r = _run("c1_sb", {}, ["g_s8"])
    assert any("signed member that is no bit-field in two's complement" in a for a in r["assumptions"])


# ── (review C2) an offset from one register's address writes the next one ─────────────────────────────────────────

def test_a_write_through_a_register_address_plus_an_offset_leaves_every_register_unknown():
    r = _run("c2_offset", {"REG_CTL.Word": 0x1234}, ["REG_R1.Byte", "REG_R0.Byte", "REG_LP0CR.Byte", "REG_CTL.Word"])
    assert all("value" not in v for v in r["outputs"].values()), r["outputs"]   # REG_CTL: unwritten, set by the row
    assert r["outputs"]["REG_R1.Byte"]["reason"] == "write_through_pointer"
    assert "pointer_past_object" in r["possible_undefined_behavior"]
    assert "signed_overflow_untyped_operand" not in r["possible_undefined_behavior"]


def test_an_offset_of_zero_is_no_access_past_the_object_but_the_write_may_alias_any_register():
    r = _run("c2_zero", {}, ["REG_R1.Byte"])
    assert "pointer_past_object" not in r["possible_undefined_behavior"]
    assert "value" not in r["outputs"]["REG_R1.Byte"]


def test_a_callee_writing_through_a_register_pointer_leaves_every_register_unknown():
    out = _out("c2_via_callee", {}, ["REG_R1.Byte", "REG_LP0CR.Byte"])
    assert all("value" not in v for v in out.values()), out
    # a callee run as its effects only: every register unknown (re-review 4 C-R4-1); the one it writes says so
    out = _out("w_by_name", {"REG_CTL.Word": 0x1234}, ["REG_CTL.Word", "REG_LP0CR.Byte"])   # cfg: effects only
    assert out["REG_CTL.Word"] == {"reason": "register_read_by_callee_not_interpreted:cfg"}
    assert out["REG_LP0CR.Byte"]["reason"].startswith("callee_pointer_write:cfg:writes_through:LP0CR")


# ── (review W1, W4) a polling loop on a register flag ─────────────────────────────────────────────────────────────

def test_a_polling_loop_on_a_register_flag_is_assumed_to_end_and_says_so():
    r = _run("w1_poll", {}, ["g_o", "REG_FLW.Byte", "REG_FLW.Bits.RSTA"])
    assert r["status"] == "supported" and r["outputs"]["g_o"]["value"] == 7
    assert r["outputs"]["REG_FLW.Bits.RSTA"]["reason"] == "polling_loop_exit_assumed:REG_FLW"
    assert "value" not in r["outputs"]["REG_FLW.Byte"]   # the hardware changed the flag: the register is unknown
    assert r["polling_loops_assumed"] == ["w1_poll:" + str(C.count("\n", 0, C.index("void w1_poll(")) + 1) + ":REG_FLW"]
    assert any(a.startswith("(R90) polling loop on a hardware flag assumed to terminate") and "1 loop(s)" in a
               for a in r["assumptions"])
    # the integrated reading's blanket "hardware does not change objects" names the exception — the record does not
    #   contradict itself
    r = _run("w1_poll", {}, ["g_o"], provider=_provider())
    assert r["outputs"]["g_o"]["value"] == 7
    assert not any("(volatile reads are unknown)" in a for a in r["assumptions"])
    assert any("except as stated for registers (R90) and polled flags assumed to clear" in a for a in r["assumptions"])


def test_a_polling_loop_on_an_input_flag_stops_without_spinning():
    import time
    t0 = time.time()
    r = _run("w1_poll_input", {"REG_FLW.Byte": 1}, ["g_o"])
    assert r["outputs"]["g_o"]["value"] == 8 and r["polling_loops_assumed"]
    assert time.time() - t0 < 5
    # a flag the row clears: the loop does not run, nothing is assumed
    r = _run("w1_poll_input", {"REG_FLW.Byte": 0}, ["g_o"])
    assert r["outputs"]["g_o"]["value"] == 8 and "polling_loops_assumed" not in r


def test_a_loop_on_an_ordinary_object_is_no_polling_loop():
    r = _run("w1_plain", {"g_o": 1}, ["g_o"])
    assert r["status"] == "unsupported" and r["reason"] == "loop_iteration_budget"


def test_the_polling_assumption_is_counted_in_the_evidence():
    from generators.test_evidence import apply_sequence_evidence, summarize_expected_evidence
    unit = {"name": "w1_poll", "source_text": C, "source_path": PATH, "source_text_complete": True,
            "project_scope": SCOPE}
    seqs = [{"inputs": {}, "expected": {"g_o": "", "REG_LP0CR.Byte": ""}}]
    apply_sequence_evidence(unit, seqs)
    assert seqs[0]["expected_evidence"]["g_o"]["polling_loops_assumed"]
    assert summarize_expected_evidence(seqs)["derived_on_assumed_polling_exit"] == 1


# ── (review W3) an observed register carries the harness-memory assumption ────────────────────────────────────────

def test_an_observed_volatile_register_carries_the_harness_memory_assumption():
    r = _run("w3_none", {"REG_LP0CR.Byte": 5}, ["REG_LP0CR.Byte"])
    assert r["outputs"]["REG_LP0CR.Byte"] == {"value": 5, "basis": "unchanged_input"}
    assert any(a.startswith("(R90) a volatile union / bit-field object (a register) is memory") for a in r["assumptions"])


# ── (review W2) the byte order of the build target ─────────────────────────────────────────────────────────────────

_CPROJECT = ('<?xml version="1.0"?><cproject><configuration><toolChain superClass="com.freescale.s12z.toolchain.release">'
             '<tool superClass="com.freescale.s12z.toolchain.compiler.1"/></toolChain></configuration></cproject>')


def _target_scope(monkeypatch, setting=None):
    if setting is None:
        monkeypatch.delenv(cpc.STORAGE_BYTE_ORDER_ENV, raising=False)
    else:
        monkeypatch.setenv(cpc.STORAGE_BYTE_ORDER_ENV, setting)
    files = {os.path.join(ROOT, "h.h"): H, os.path.join(ROOT, "u.c"): C}
    build = cpc.detect_build_config({os.path.join(ROOT, ".cproject"): _CPROJECT})
    ctx = cpc.build_project_context(files, build)
    return ctx, cpc.build_scopes(ctx, [PATH])[PATH]


def test_the_build_target_decides_the_byte_order(monkeypatch):
    ctx, scope = _target_scope(monkeypatch)
    assert ctx["build"]["targets"] == {os.path.join(ROOT, ".cproject"): "s12z"}
    assert scope["storage_byte_order"]["order"] == "be"
    lay = scope["storage_globals"]["REG_CTL"]
    assert lay["orders"] == ["be"] and lay["byte_order"] == "be" and "s12z" in lay["byte_order_basis"]
    unit = {"name": "w_word", "source_text": C, "source_path": PATH, "source_text_complete": True, "project_scope": scope}
    (r,) = evaluate_outputs(unit, [{}], [["g_o", "REG_CTL.Overlap_STR.CTL0STR.Byte"]])
    # big-endian: the low byte of the word is the second
    assert r["outputs"]["g_o"]["value"] == 0x34 and r["outputs"]["REG_CTL.Overlap_STR.CTL0STR.Byte"]["value"] == 0x12
    assert any("byte order: the build target (s12z" in a for a in r["assumptions"])


def test_a_configured_byte_order_wins_and_any_keeps_every_layout(monkeypatch):
    assert _target_scope(monkeypatch, "le")[1]["storage_globals"]["REG_CTL"]["orders"] == ["le"]
    assert _target_scope(monkeypatch, "any")[1]["storage_globals"]["REG_CTL"]["orders"] == ["le", "be"]
    assert SCOPE["storage_byte_order"] == {"order": None,
                                           "basis": "none assumed (no build target names a byte order)"}


# ── the VectorCAST reference SUTS of HDPDM01 (read-only; skipped where it or the tree is absent) ───────────────────

_REFERENCE = Path(r"D:\Project\devops\260105\docs\(HDPDM01_SUTS) Software Unit Test Specification_v3.01_240221_R.xlsm")
_TREE = [Path(r"D:\Project\Ados\PDS64_RD"), Path(r"D:\Project\Ados\PDS64_FBL")]


@pytest.mark.skipif(not (_REFERENCE.is_file() and all(r.is_dir() for r in _TREE)),
                    reason="HDPDM01 reference SUTS or source tree not present")
def test_the_reference_suts_register_cells_agree():
    """Every register cell the reference states and the oracle derives from the reference's own inputs agrees — and
    the five ``REG_SCI0BD.Word`` cells (written through its two bytes) agree only big-endian: the reference was run on
    the S12Z byte order, which the build target gives."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from reference_alignment import _convert_inputs, _definitions, _load_source, _param_types

    from generators.c_source_oracle import read_reference_cell
    from tools.export_suts_vectorcast import bare_fn_name, build_vectorcast_model
    model = build_vectorcast_model(str(_REFERENCE))
    texts, context, _unread = _load_source(_TREE)
    defs = _definitions(texts)
    units = [u for u in model["units"] if any(str(s).startswith("REG_") for c in u["test_cases"]
                                              for s in (c.get("expected") or {}))]
    paths = sorted({p for u in units for p in defs.get(bare_fn_name(u["unit_name"]), [])})
    scopes = cpc.build_scopes(context, paths)
    files = cpc.projected_texts(scopes, texts)
    kinds, sci0bd = {"agree": 0, "disagree": 0, "unknown": 0}, 0
    for u in units:
        name = bare_fn_name(u["unit_name"])
        for path in defs.get(name, []):
            unit = {"name": name, "source_text": files[path], "source_path": path, "source_text_complete": True,
                    "project_scope": scopes[path]}
            params = _param_types(unit)
            vectors = [_convert_inputs(scopes[path], params, c.get("inputs") or {})[0] for c in u["test_cases"]]
            outs = [list((c.get("expected") or {}).keys()) for c in u["test_cases"]]
            constants = scopes[path].get("constants") if scopes[path].get("constants") is not None else {}
            for case, result in zip(u["test_cases"], evaluate_outputs(unit, vectors, outs), strict=True):
                for slot, raw in (case.get("expected") or {}).items():
                    if not str(slot).startswith("REG_"):
                        continue
                    expected = read_reference_cell(raw, constants, scopes[path].get("function_like_macros") or ())[0]
                    got = result["outputs"].get(slot) or {}
                    if expected is None or "value" not in got:
                        kinds["unknown"] += 1
                    elif got["value"] == expected:
                        kinds["agree"] += 1
                        sci0bd += slot == "REG_SCI0BD.Word"
                    else:
                        kinds["disagree"] += 1
    assert kinds["disagree"] == 0 and kinds["agree"] >= 250, kinds
    assert sci0bd >= 5


# ── an independent check: the host compiler runs the same code on the same storage ──────────────────────────────────
# A derived value must hold under every layout the model keeps — the host (little-endian, bit-fields from the least
# significant bit in units of their declared type) is one of them. Each case runs three times with the objects' memory
# filled differently before the row's inputs are stored: a value that rests on a bit the model calls unknown would differ.

_HOST_CASES = [
    ("w_byte_then_bit", {}, ["REG_LP0CR.Byte", "REG_LP0CR.Bits.LPE", "REG_LP0CR.Bits.MODE", "REG_LP0CR"]),
    ("w_bit", {"REG_LP0CR.Byte": 0x31}, ["REG_LP0CR.Byte", "REG_LP0CR.Bits.LPPUE", "REG_LP0CR.Bits.LPE"]),
    ("w_bit", {}, ["REG_LP0CR.Byte", "REG_LP0CR.Bits.LPE", "REG_LP0CR.Bits.LPPUE"]),
    ("w_field", {"REG_LP0CR": 0}, ["g_o", "REG_LP0CR.Bits.MODE"]),
    ("w_or", {"REG_LP0CR.Byte": 0x05}, ["REG_LP0CR.Bits.LPPUE", "REG_LP0CR.Byte"]),
    ("w_inc", {"REG_LP0CR.Byte": 0x30}, ["REG_LP0CR.Bits.MODE", "REG_LP0CR.Byte"]),
    ("w_inc", {"REG_LP0CR.Bits.MODE": 2}, ["REG_LP0CR.Bits.MODE", "REG_LP0CR.Byte", "REG_LP0CR.Bits.LPE"]),
    ("w_value", {"REG_LP0CR.Byte": 0}, ["g_o"]),
    ("r_bit", {"REG_LP0CR.Byte": 0x08}, ["g_o"]),
    ("r_bit", {"REG_LP0CR.Bits.LPE": 0}, ["g_o"]),
    ("r_bit", {"REG_LP0CR.Byte": 0x09, "REG_LP0CR.Bits.LPPUE": 0}, ["g_o"]),
    ("w_bit", {"REG_LP0CR": 0, "REG_LP0CR.Bits.LPE": 1}, ["REG_LP0CR", "REG_LP0CR.Byte"]),
    ("r_volatile", {}, ["g_o"]),
    ("w_word", {}, ["g_o", "g_w", "REG_CTL.Overlap_STR.CTL0STR.Byte"]),
    ("w_low_byte", {"REG_CTL.Word": 0x5656}, ["g_w", "REG_CTL.Overlap_STR.CTL1STR.Byte"]),
    ("w_high_bit", {"REG_CTL": 0}, ["g_w", "REG_CTL.Bits.HIGH0", "REG_CTL.Bits.LOW0"]),
    ("w_high_bit", {"REG_CTL.Overlap_STR.CTL1STR.Byte": 0x81}, ["g_w", "REG_CTL.Bits.LOW0",
                                                                "REG_CTL.Overlap_STR.CTL1STR.Bits.LOW0"]),
    ("w_nm", {"REG_NM.Word": 0}, ["g_w", "REG_NM.Bits.HIGH0"]),
    ("w_then_ext", {}, ["REG_LP0CR.Bits.LPPUE", "REG_LP0CR.Byte"]),
    ("w_struct", {}, ["gb.f", "gb.k"]),
    # (review C1) signed members
    ("c1_ts", {}, ["g_ts.k", "g_o"]),
    ("c1_sb", {}, ["g_s8", "g_sb.sb", "g_sb.Byte"]),
    ("c1_sw", {}, ["g_s16", "g_sw.sw", "g_sw.Word"]),
    ("c1_in", {"g_sb.sb": -3}, ["g_s8", "g_sb.Byte"]),
    ("c1_in", {"g_sb.Byte": 0xFD}, ["g_s8"]),
]
_OBJECTS = {"REG_LP0CR": "Byte", "REG_CTL": "Word", "REG_NM": "Word", "gb": None, "g_ts": None, "g_sb": None,
            "g_sw": None}


def _host_compiler():
    import shutil
    return shutil.which("gcc") or shutil.which("clang")


@pytest.mark.skipif(_host_compiler() is None, reason="no host C compiler")
def test_a_host_compiler_agrees_with_every_derived_value(tmp_path):
    import re
    import subprocess
    header = re.sub(r"extern (volatile \w+ \w+) @0x[0-9A-Fa-f]+;", r"\1;", H).replace(
        "typedef unsigned int U16;", "typedef unsigned short U16;").replace(
        "typedef signed int S16;", "typedef signed short S16;")   # the target's 16-bit int
    body = C.replace('#include "h.h"', "") + LIB.replace('#include "h.h"', "") + "void nowhere(void) {}\n"
    lines = ["#include <stdio.h>", "#include <string.h>", header, body, "int main(void) {"]
    derived: dict[tuple[int, str], int] = {}
    for i, (fn, inputs, outs) in enumerate(_HOST_CASES):
        values = _out(fn, inputs, outs)
        for o in outs:
            if "value" in values[o]:
                derived[(i, o)] = values[o]["value"]
        for fill in (0x00, 0xA5, 0xFF):
            for obj in _OBJECTS:
                lines.append(f"  memset((void *)&{obj}, {fill}, sizeof {obj});")
            lines.append("  g_o = 0; g_w = 0;")
            for key, value in inputs.items():
                target = f"{key}.{_OBJECTS[key]}" if key in _OBJECTS else key
                lines.append(f"  {target} = {value};")
            lines.append(f"  {fn}();")
            for o in outs:
                target = f"{o}.{_OBJECTS[o]}" if o in _OBJECTS else o
                lines.append(f'  printf("{i} {o} %ld\\n", (long)({target}));')
    lines += ["  return 0;", "}"]
    src, exe = tmp_path / "host.c", tmp_path / "host.exe"
    src.write_text("\n".join(lines), encoding="utf-8")
    subprocess.run([_host_compiler(), "-std=c99", "-O0", "-w", "-o", str(exe), str(src)], check=True, timeout=120)
    seen: dict[tuple[int, str], set[int]] = {}
    for row in subprocess.run([str(exe)], capture_output=True, text=True, check=True, timeout=60).stdout.split("\n"):
        if row.strip():
            i, o, v = row.split()
            seen.setdefault((int(i), o), set()).add(int(v))
    assert len(derived) >= 30
    wrong = {k: (v, seen.get(k)) for k, v in derived.items() if seen.get(k) != {v}}
    assert not wrong


# ══ (R90 re-review) a second project: polling loops, volatility, allocation order, disclosures, mutation gaps ══════════

ROOT3 = os.path.join(os.sep, "p90b")
H3 = """typedef unsigned char U8;
typedef unsigned int U16;
typedef union { U8 Byte; struct { U8 RSTA :1; U8 :7; } Bits; } FLWSTR;
extern volatile FLWSTR REG_FLW @0x00000390;
#define FLW REG_FLW.Byte
#define FLW_RSTA REG_FLW.Bits.RSTA
#define FLW_RSTA_MASK 0x01U
typedef union { U16 Word; struct { U8 HI; U8 LO; } Overlap_STR; } WSTR;
extern volatile WSTR REG_W @0x00000392;
/* (W-N1) volatile through the typedef, through every member, through one member */
typedef volatile union { U8 Byte; struct { U8 RDY :1; U8 :7; } Bits; } VSTR;
extern VSTR REG_V @0x00000500;
#define V_RDY REG_V.Bits.RDY
#define V_RDY_MASK 0x01U
typedef union { volatile U8 Byte; struct { volatile U8 RDY :1; volatile U8 :7; } Bits; } MSTR;
extern MSTR REG_M @0x00000501;
#define M_RDY REG_M.Bits.RDY
#define M_RDY_MASK 0x01U
typedef union { U8 Byte; struct { volatile U8 RDY :1; U8 :7; } Bits; } PSTR;
PSTR g_pv;
/* an ordinary union, a union with a member narrower than it, a register whose header states no mask */
typedef union { U8 Byte; struct { U8 A :1; U8 :7; } Bits; } XSTR;
XSTR g_x;
typedef union { U16 Word; U8 Lo; } NRSTR;
NRSTR g_nr;
typedef union { U8 Byte; struct { U8 A :1; U8 :7; } Bits; } NOMSTR;
extern volatile NOMSTR REG_NOM @0x00000910;
#define BAD3_A REG_BAD3.Bits.A
#define BAD3_A_MASK 0x80U
extern volatile NOMSTR REG_BAD3 @0x00000911;
"""
C3 = """#include "h3.h"
U8 g_o;
U16 g_w;
U8 g_x1;
U8 g_cnt;
U8 g_err;
U8 g_in;
U8 *g_p;
void q1_always_true_field(void) { while (FLW_RSTA <= 1U) {} g_o = 8U; }
void q2_or_constant(void) { while ((FLW | 1U) != 0U) {} g_o = 8U; }
void q3_or_object(void) { while ((FLW_RSTA == 1U) || (g_x1 == 1U)) {} g_o = 8U; }
void q4_wide_not_found(void) { while (REG_W.Word != 0x1234U) {} g_o = 8U; }
void q5_wide(void) { while (REG_W.Word == 0x1234U) {} g_o = 8U; }
void q6_cond_writes(void) { while ((REG_FLW.Bits.RSTA == 1U) || ((g_x1 = 5U) == 0U)) {} g_o = g_x1; }
void q7_two_bytes(void) { while ((FLW != 0U) && (REG_NOM.Byte != 0U)) {} g_o = 8U; }
void q8_div(void) { while ((100U / FLW) == 100U) {} g_o = 8U; }
void q8_div_forked(void) { if (g_x1 != 0U) { g_cnt = 1U; } while ((100U / FLW) == 100U) {} g_o = 8U; }
U8 sat_step(void) { if (g_cnt < 3U) { g_cnt++; } return 1U; }
void q9_cond_counts(void) { g_cnt = 0U; while ((REG_FLW.Bits.RSTA == 0U) && (sat_step() != 0U)) {} g_o = g_cnt; }
void s1_saturating(void) { g_cnt = 0U; while (FLW_RSTA == 1U) { if (g_cnt < 3U) { g_cnt++; } } g_o = g_cnt; }
void s2_timeout_flag(void) {
    g_cnt = 0U; g_err = 0U;
    while (FLW_RSTA == 0U) { if (g_cnt < 3U) { g_cnt++; } else { g_err = 1U; } }
}
void c1_body_reads(void) { while (FLW_RSTA == 0U) { (void)FLW; } g_o = 1U; }
void c2_body_copies(void) { while (FLW_RSTA == 0U) { g_o = FLW; } }
void hd_wait_set(void) { while (FLW_RSTA == 1U) {} g_o = 2U; }
void hd_wait_clear(void) { while (FLW_RSTA == 0U) {} g_o = 3U; }
void hd_break(U8 c) { while (FLW_RSTA == 0U) { if (c != 0U) { break; } } g_o = 4U; }
void v1_typedef(void) { while (V_RDY == 0U) {} g_o = 5U; }
void v2_reads(void) { g_o = V_RDY; g_w = M_RDY; }
void pv_byte(void) { while (g_pv.Byte == 0U) {} g_o = 1U; }
void pv_bit(void) { while (g_pv.Bits.RDY == 0U) {} g_o = 1U; }
void o3_take(void) { g_p = &g_x.Byte; }
void o3_write(void) { *g_p = 9U; g_o = g_x.Byte; }
void o7_unknown(void) { g_x.Byte = 0U; g_x.Bits.A = g_in; g_o = g_x.Byte; }
void i1_narrow(void) { g_nr.Word = 0x1234U; g_nr.Lo = 0x56U; g_w = g_nr.Word; }
void i1_wide_only(void) { g_nr.Word = 0x1234U; g_w = g_nr.Word; }
void nom_read(void) { g_o = REG_NOM.Bits.A; }
U8 is_ready(void);
void wait_flw(void);
void cond_unknown(U8 c);
void e1(void) { if (is_ready() != 0U) { g_o = 1U; } else { g_o = 2U; } }
void e2(void) { wait_flw(); g_o = 6U; }
void e3(U8 c) { cond_unknown(c); }
"""
L3 = """#include "h3.h"
extern U8 g_in;
U8 is_ready(void) { return (U8)REG_FLW.Bits.RSTA; }
void wait_flw(void) { while (FLW_RSTA == 0U) {} }
void cond_unknown(U8 c) { if (c != 0U) { g_x.Bits.A = g_in; } else { g_x.Bits.A = 0U; } }
"""
# layouts the model refuses, one reason each (the mutation run's survivors L07 · L09 · L12 · L14 · L15 · L24 · L27)
HL = """typedef unsigned char U8;
typedef unsigned int U16;
typedef union { U16 w; struct { U16 a; U8 b; } s; } PADU;
PADU g_pad3;
typedef union { U16 Word; U16 f :12; } WBFU;
WBFU g_wbf;
typedef union { U8 Byte; U8 Raw; } KU;
const KU g_k = {0};
#define FOO A
typedef union { U8 Byte; struct { U8 FOO :1; U8 :7; } Bits; } MACU;
MACU g_mac;
#ifdef FEATURE_X
typedef union { U8 Byte; struct { U8 A :1; U8 :7; } Bits; } CONDU;
#endif
CONDU g_cond;
typedef union { U8 Byte; struct { U8 A :1; U8 :7; }; } ANONU;
ANONU g_anon;
typedef union { U8 Byte; U8 a b; } ERRU;
ERRU g_err3;
"""
EXTRA3 = {
    "s3a.c": '#include "h3.h"\nstatic XSTR s_reg;\nU8 g_o3;\nvoid s3a(void) { g_o3 = s_reg.Byte; }\n',
    "s3b.c": '#include "h3.h"\nstatic XSTR s_reg;\nvoid s3b(void) { s_reg.Byte = 2U; }\n',
    "hl.h": HL,
    "ul.c": '#include "hl.h"\nvoid ul(void) { }\n',
    "ug.c": '#include "missing_r90.h"\n#include "h3.h"\nvoid ug(void) { }\n',
    "hp.h": "typedef unsigned char U8;\n#pragma reverse_bitfields on\ntypedef union { U8 Byte; U8 Raw; } RPU;\nRPU g_rp;\n",
    "up.c": '#include "hp.h"\nvoid up(void) { }\n',
    "hq.h": 'typedef unsigned char U8;\n_Pragma("bitfields=reversed")\ntypedef union { U8 Byte; U8 Raw; } RQU;\nRQU g_rq;\n',
    "uq.c": '#include "hq.h"\nvoid uq(void) { }\n',
}
FILES3 = {os.path.join(ROOT3, "h3.h"): H3, os.path.join(ROOT3, "u3.c"): C3, os.path.join(ROOT3, "l3.c"): L3,
          **{os.path.join(ROOT3, k): v for k, v in EXTRA3.items()}}
CONTEXT3 = cpc.build_project_context(FILES3)
U3 = os.path.join(ROOT3, "u3.c")
SCOPES3 = cpc.build_scopes(CONTEXT3, [p for p in FILES3 if p.endswith(".c")])


def _provider3():
    from generators.integration_oracle import CalleeProvider
    return CalleeProvider(CONTEXT3, FILES3, SCOPES3, cpc.shared_parser())


def _run3(name, inputs, outs, path=U3, provider=None, scopes=None):
    scopes = scopes or SCOPES3
    unit = {"name": name, "source_text": FILES3[path], "source_path": path, "source_text_complete": True,
            "project_scope": scopes[path]}
    if provider is not None:
        unit["callee_provider"] = provider
    (r,) = evaluate_outputs(unit, [inputs], [outs])
    return r


def _scope3(unit):
    return SCOPES3[os.path.join(ROOT3, unit)]


def _refused(r, reason):
    return r["status"] == "unsupported" and r["reason"] == reason and all("value" not in v for v in r["outputs"].values())


# ── (C-N1 a) a polling loop is assumed to end only where a value of the flag ends it ─────────────────────────────────

@pytest.mark.parametrize("fn, inputs", [
    ("q1_always_true_field", {"REG_FLW.Byte": 0}),           # a 1-bit field is <= 1 whatever it holds
    ("q2_or_constant", {"REG_FLW.Byte": 0}),                 # (FLW | 1) != 0 for every byte
    ("q3_or_object", {"REG_FLW.Byte": 0, "g_x1": 1}),       # held true by another object
])
def test_a_loop_no_flag_value_can_end_is_refused_not_assumed_to_end(fn, inputs):
    r = _run3(fn, inputs, ["g_o"])
    assert _refused(r, "non_terminating_loop"), r
    assert "polling_loops_assumed" not in r


def test_a_loop_another_flag_value_ends_is_assumed_to_end():
    r = _run3("q3_or_object", {"REG_FLW.Byte": 1, "g_x1": 0}, ["g_o"])
    assert r["outputs"]["g_o"] == {"value": 8, "basis": "assigned"} and r["polling_loops_assumed"]
    # ... but not where, with the other flag value, the condition reads an object the row does not set
    r = _run3("q3_or_object", {"REG_FLW.Byte": 1}, ["g_o"])
    assert _refused(r, "polling_loop_exit_undetermined:condition_unknown_for_a_flag_value"), r


def test_a_wide_flag_is_searched_over_some_values_and_a_miss_is_not_called_non_terminating():
    r = _run3("q4_wide_not_found", {"REG_W.Word": 0}, ["g_o"])   # 0x1234 would end it: not among 0 / 0xFFFF / ~0
    assert _refused(r, "polling_loop_exit_not_found"), r
    r = _run3("q5_wide", {"REG_W.Word": 0x1234}, ["g_o"])
    assert r["outputs"]["g_o"]["value"] == 8 and r["polling_loops_assumed"]


def test_a_condition_that_writes_when_the_flag_ends_the_loop_is_refused():
    r = _run3("q6_cond_writes", {"REG_FLW.Byte": 1, "g_x1": 0}, ["g_o", "g_x1"])
    assert _refused(r, "polling_loop_condition_changes_state"), r


def test_a_flag_value_the_condition_divides_by_is_possible_undefined_behaviour():
    r = _run3("q8_div", {"REG_FLW.Byte": 1}, ["g_o"])
    assert r["outputs"]["g_o"]["value"] == 8 and r["polling_loops_assumed"]
    assert "polling_flag_value:division_by_zero" in r["possible_undefined_behavior"]
    # (re-review 5 W-R5-1) on a path a branch on an unknown value chose too: the probe judges the flag value as the run's
    for provider in (None, _provider3()):
        r = _run3("q8_div_forked", {"REG_FLW.Byte": 1}, ["g_o"], provider=provider)
        assert r["outputs"]["g_o"]["value"] == 8, r
        assert "polling_flag_value:division_by_zero" in r["possible_undefined_behavior"], r["possible_undefined_behavior"]


def test_a_search_over_too_many_flag_values_is_refused():
    r = _run3("q7_two_bytes", {"REG_FLW.Byte": 1, "REG_NOM.Byte": 1}, ["g_o"])
    assert _refused(r, "polling_loop_exit_search_budget:65536"), r


# ── (C-N1 b) a body that changes what the next poll sees is no polling loop ──────────────────────────────────────────

def test_a_timeout_counter_is_not_frozen_at_its_last_iteration():
    r = _run3("s2_timeout_flag", {"REG_FLW.Byte": 0}, ["g_err", "g_cnt"])
    assert _refused(r, "polling_loop_body_changes_state"), r   # g_err = 1 was the timeout path, not k polls
    r = _run3("s1_saturating", {"REG_FLW.Byte": 1}, ["g_o", "g_cnt"])
    assert _refused(r, "polling_loop_body_changes_state"), r


def test_a_condition_that_counts_its_polls_is_not_frozen_at_its_last_one():
    # the counter saturates at 3 after three polls: the state after the loop is 1, 2 or 3 depending on when the flag
    #   changes — the poll itself changes what the next one sees
    r = _run3("q9_cond_counts", {"REG_FLW.Byte": 0}, ["g_o", "g_cnt"], provider=_provider3())
    assert _refused(r, "polling_loop_condition_changes_state"), r


# ── (C-N1 c) a body that reads the flag sees the hardware's timing ──────────────────────────────────────────────────

@pytest.mark.parametrize("fn", ["c1_body_reads", "c2_body_copies"])
def test_a_body_that_reads_the_polled_flag_is_refused(fn):
    r = _run3(fn, {"REG_FLW.Byte": 0}, ["g_o"])
    assert _refused(r, "polling_loop_body_reads_flag:REG_FLW"), r


# ── the HD pattern keeps its value ──────────────────────────────────────────────────────────────────────────────────

def test_the_hd_wait_on_a_one_bit_flag_still_ends_with_its_value():
    r = _run3("hd_wait_set", {"REG_FLW.Byte": 1}, ["g_o", "REG_FLW.Bits.RSTA"])
    assert r["outputs"]["g_o"] == {"value": 2, "basis": "assigned"}
    assert r["outputs"]["REG_FLW.Bits.RSTA"]["reason"] == "polling_loop_exit_assumed:REG_FLW"
    assert r["polling_loops_assumed"] == ["hd_wait_set:" + str(C3.count("\n", 0, C3.index("void hd_wait_set(")) + 1)
                                          + ":REG_FLW"]
    assert any(a.startswith("(R90) polling loop on a hardware flag assumed to terminate") for a in r["assumptions"])
    r = _run3("hd_wait_clear", {"REG_FLW.Bits.RSTA": 0}, ["g_o"])
    assert r["outputs"]["g_o"]["value"] == 3 and r["polling_loops_assumed"]
    # a break on an unknown parameter is a way out of its own; the path that stays is left as the poll found it
    r = _run3("hd_break", {"REG_FLW.Byte": 0}, ["g_o"])
    assert r["outputs"]["g_o"]["value"] == 4 and r["polling_loops_assumed"]


# ── (W-N1) a register volatile through its typedef or its members ───────────────────────────────────────────────────

def test_volatility_of_the_typedef_or_a_member_makes_a_register():
    cands = _scope3("u3.c")["storage_candidates"]
    assert cands["REG_V"]["volatile"] and cands["REG_V"]["object_volatile"]       # typedef volatile union
    assert cands["REG_M"]["volatile"] and not cands["REG_M"]["object_volatile"]   # every member volatile
    assert cands["g_pv"]["volatile"] and not cands["g_x"]["volatile"]
    pv = _scope3("u3.c")["storage_globals"]["g_pv"]
    assert pv["volatile"] and pv["leaves"]["Bits.RDY"]["volatile"] and not pv["leaves"]["Byte"]["volatile"]
    r = _run3("v2_reads", {"REG_V.Bits.RDY": 1, "REG_M.Bits.RDY": 1}, ["g_o", "g_w"])
    assert r["outputs"]["g_o"]["value"] == 1 and r["outputs"]["g_w"]["value"] == 1
    assert any(a.startswith("(R90) a volatile union / bit-field object (a register) is memory")
               and a.endswith("REG_M, REG_V") for a in r["assumptions"])
    r = _run3("v2_reads", {"REG_V.Bits.RDY": 1, "REG_M.Bits.RDY": 1}, ["g_o"], provider=_provider3())
    assert not any("(volatile reads are unknown)" in a for a in r["assumptions"])
    assert r["storage_registers"] == ["REG_M", "REG_V"]


def test_a_poll_is_a_read_through_a_volatile_lvalue():
    r = _run3("v1_typedef", {"REG_V.Bits.RDY": 0}, ["g_o"])
    assert r["outputs"]["g_o"]["value"] == 5 and r["polling_loops_assumed"]
    assert _run3("pv_bit", {"g_pv.Bits.RDY": 0}, ["g_o"])["polling_loops_assumed"]
    # the plain member of a type with one volatile member: no read the compiler must repeat — never assumed to end
    r = _run3("pv_byte", {"g_pv.Byte": 0}, ["g_o"])
    assert _refused(r, "loop_iteration_budget"), r


# ── (W-N2) the allocation order of bit-fields ───────────────────────────────────────────────────────────────────────

def _target_scopes3(monkeypatch):
    monkeypatch.delenv(cpc.STORAGE_BYTE_ORDER_ENV, raising=False)
    build = cpc.detect_build_config({os.path.join(ROOT3, ".cproject"): _CPROJECT})
    ctx = cpc.build_project_context(FILES3, build)
    return cpc.build_scopes(ctx, [U3])


def test_without_a_build_target_a_bit_field_read_through_another_member_needs_both_allocation_ends(monkeypatch):
    monkeypatch.delenv(cpc.STORAGE_BYTE_ORDER_ENV, raising=False)
    scope = _scope3("u3.c")
    assert scope["storage_bit_order"]["order"] is None and scope["storage_bit_order"]["basis"].startswith("either end")
    assert scope["storage_globals"]["REG_NOM"]["orders"] == ["le", "le_msb"]
    r = _run3("nom_read", {"REG_NOM.Byte": 1}, ["g_o"])
    assert r["outputs"]["g_o"]["reason"] == "storage_member_layout_dependent:REG_NOM.Bits.A"
    assert any("bit-field allocation: either end" in a for a in r["assumptions"])
    assert _run3("nom_read", {"REG_NOM.Bits.A": 1}, ["g_o"])["outputs"]["g_o"]["value"] == 1   # the member itself
    # a mask that only an allocation from the most significant bit meets is no evidence for it: refused
    assert "REG_BAD3" not in scope["storage_globals"]
    assert scope["storage_unresolved"]["REG_BAD3"] == "layout_contradicts_header_mask:BAD3_A_MASK"
    # the build target's compiler allocates from the least significant bit: one layout, the value
    scopes = _target_scopes3(monkeypatch)
    assert scopes[U3]["storage_globals"]["REG_NOM"]["orders"] == ["be"]
    r = _run3("nom_read", {"REG_NOM.Byte": 1}, ["g_o"], scopes=scopes)
    assert r["outputs"]["g_o"]["value"] == 1
    assert any("bit-field allocation: from the least significant bit (the build target s12z" in a
               for a in r["assumptions"])


def test_a_pragma_that_may_reverse_bit_fields_refuses_the_units_objects():
    assert "g_rp" not in _scope3("up.c")["storage_globals"]
    assert _scope3("up.c")["storage_unresolved"]["g_rp"] == "storage_order_pragma:hp.h:2:reverse_bitfields on"
    assert "g_rq" not in _scope3("uq.c")["storage_globals"]
    assert _scope3("uq.c")["storage_unresolved"]["g_rq"].startswith("storage_order_pragma:hq.h:2:_Pragma bitfields=")


def test_a_file_record_without_the_pragma_scan_lays_nothing_out():
    import copy
    ctx = copy.deepcopy(CONTEXT3)
    del ctx["files"][os.path.join(ROOT3, "h3.h")]["storage_order_pragmas"]
    scope = cpc.build_scopes(ctx, [U3])[U3]
    assert "REG_FLW" not in scope["storage_globals"]
    assert scope["storage_unresolved"]["REG_FLW"] == "storage_order_pragmas_not_scanned:h3.h"


def test_an_invalid_byte_order_setting_is_disclosed_not_ignored(monkeypatch, caplog):
    import logging
    import uuid
    bogus = "big-" + uuid.uuid4().hex[:6]
    monkeypatch.setenv(cpc.STORAGE_BYTE_ORDER_ENV, bogus)
    with caplog.at_level(logging.WARNING):
        order, basis = cpc.storage_byte_order(CONTEXT3, U3)
    assert order is None and basis == f"none assumed ({cpc.STORAGE_BYTE_ORDER_ENV}={bogus!r} is not one of " \
                                      "target/be/le/any)"
    assert any(bogus in rec.getMessage() for rec in caplog.records)


def test_two_build_families_in_one_configuration_name_no_target():
    text = _CPROJECT.replace("</toolChain>", '<tool superClass="com.freescale.hcs12x.toolchain.linker"/></toolChain>')
    assert cpc.detect_build_config({os.path.join(ROOT3, ".cproject"): text})["targets"] == {}


# ── (I-1) a store through a member narrower than its union ──────────────────────────────────────────────────────────

def test_a_narrow_member_store_read_through_the_wider_one_names_c11_6_2_6_1p7(monkeypatch):
    r = _run3("i1_narrow", {}, ["g_w"])
    assert any("C11 6.2.6.1p7" in a and a.endswith("g_nr") for a in r["assumptions"])
    r = _run3("i1_narrow", {}, ["g_w"], scopes=_target_scopes3(monkeypatch))
    assert r["outputs"]["g_w"]["value"] == 0x5634   # big-endian: the narrow member is the word's high byte
    assert not any("6.2.6.1p7" in a for a in _run3("i1_wide_only", {}, ["g_w"])["assumptions"])
    assert not any("6.2.6.1p7" in a for a in _run("w_low_byte", {"REG_CTL.Word": 0x5656}, ["g_w"])["assumptions"])


# ── (W-N5) the mutation run's harmful survivors ─────────────────────────────────────────────────────────────────────

def test_a_pointer_write_reaches_an_address_taken_union_s_unwritten_bits():   # O03
    out = _run3("o3_write", {"g_x.Byte": 5}, ["g_o", "g_x.Bits.A"])["outputs"]
    assert all("value" not in v for v in out.values()), out


def test_an_unknown_value_written_to_a_bit_makes_the_byte_unknown():   # O07
    out = _run3("o7_unknown", {}, ["g_o", "g_x.Bits.A"])["outputs"]
    assert all("value" not in v for v in out.values()), out


def test_a_callee_s_register_use_reaches_the_entry_s_record():   # O11 · O12 · O13
    r = _run3("e1", {"REG_FLW.Byte": 1}, ["g_o"], provider=_provider3())
    assert r["outputs"]["g_o"]["value"] == 1 and r["interprocedural"]["inlined"] == {"is_ready": 1}
    assert r["storage_objects"] == ["REG_FLW"] and r["storage_registers"] == ["REG_FLW"]
    assert any(a.startswith("(R90) a union / bit-field object is one storage") for a in r["assumptions"])
    assert any(a.startswith("(R90) a volatile union / bit-field object (a register) is memory") for a in r["assumptions"])
    r = _run3("e2", {"REG_FLW.Byte": 0}, ["g_o"], provider=_provider3())
    assert r["outputs"]["g_o"]["value"] == 6
    assert r["polling_loops_assumed"] == ["wait_flw:4:REG_FLW"]


def test_a_bit_one_callee_path_writes_unknown_is_unknown_after_the_join():   # O08
    r = _run3("e3", {"g_x.Byte": 0}, ["g_x.Bits.A", "g_x.Byte"], provider=_provider3())
    assert r["interprocedural"]["inlined"] == {"cond_unknown": 1}
    assert all("value" not in v for v in r["outputs"].values()), r["outputs"]


def test_a_union_name_static_in_two_units_is_never_read_from_the_row():   # O04
    r = _run3("s3a", {"s_reg.Byte": 3}, ["g_o3"], path=os.path.join(ROOT3, "s3a.c"), provider=_provider3())
    assert "value" not in r["outputs"]["g_o3"], r["outputs"]


@pytest.mark.parametrize("name, reason", [
    ("g_pad3", "layout_padding_implementation_defined:s"),        # L09: an aggregate's size no multiple of its alignment
    ("g_wbf", "bit_field_byte_allocation_unmodeled"),            # L07: a union bit-field wider than a byte
    ("g_k", "const_object"),                                     # L15
    ("g_mac", "storage_member_named_by_macro:Bits.FOO"),         # L24
    ("g_cond", "storage_definition_missing_or_ambiguous:object"),   # L27: a body under an undecided #ifdef
    ("g_anon", "storage_body_hides_members:object"),             # L14: an anonymous member
    ("g_err3", "storage_body_hides_members:object"),             # L12: a member declaration that does not parse
])
def test_a_layout_the_model_cannot_state_is_refused_second_set(name, reason):
    scope = _scope3("ul.c")
    assert name not in scope["storage_globals"]
    assert scope["storage_unresolved"][name] == reason


def test_an_unreadable_include_and_an_older_body_record_lay_nothing_out():   # L16 · L11
    scope = _scope3("ug.c")
    assert "REG_FLW" not in scope["storage_globals"] and scope["storage_unresolved"]["REG_FLW"] == "preprocessing_gaps"
    raw = {"union U": [{"union": True, "members": [{"name": "Byte", "type": "U8", "shape": "scalar", "bitfield": False,
                                                     "bits": "", "dims": []}]}]}
    with pytest.raises(cpc.Unresolved, match="storage_body_hides_members:object"):
        cpc._storage_layout("union U", raw, lambda t: {"bits": 8, "signed": False}, int)


# ── (W-N3) counted and disclosed ────────────────────────────────────────────────────────────────────────────────────

def test_register_cells_are_counted_and_disclosed():
    from generators.test_evidence import apply_sequence_evidence, summarize_expected_evidence
    from report_gen.generation_disclosures import build_disclosures
    unit = {"name": "hd_wait_set", "source_text": C3, "source_path": U3, "source_text_complete": True,
            "project_scope": SCOPES3[U3]}
    seqs = [{"inputs": {"REG_FLW.Byte": 1}, "expected": {"g_o": ""}}, {"inputs": {}, "expected": {"g_w": ""}}]
    apply_sequence_evidence(unit, seqs)
    counts = summarize_expected_evidence(seqs)
    assert (counts["derived_on_storage_model"], counts["derived_on_register_memory"],
            counts["derived_on_assumed_polling_exit"]) == (1, 1, 1)
    (item,) = [i for i in build_disclosures("suts", {"expected_evidence_summary": counts})
               if i["key"] == "suts_expected_evidence"]
    for text in ("1칸은 공용체 · 비트필드 객체를 한 저장소로 배치한 모델", "scripts/source_oracle_clang_check.py",
                 "1칸은 volatile 레지스터를 하네스 메모리로 읽은", "1칸은 레지스터 플래그를 기다리는 폴링 루프가 끝난다고 가정"):
        assert text in item["note"], item["note"]


def test_the_integration_stats_count_register_cells():   # E02
    from generators.integration_oracle import attach_integration_evidence
    from report_gen.generation_disclosures import build_disclosures
    subs = [{"inputs": {"REG_FLW.Byte": 1}, "expected": {"g_o": "N/A"}}]
    stats = attach_integration_evidence([{"tc_id": "T1", "entry_fn": "hd_wait_set", "sub_cases": subs}],
                                        {"project_context": CONTEXT3, "source_files": FILES3},
                                        {"f": {"name": "hd_wait_set", "source_path": U3}})
    assert subs[0]["expected"] == {"g_o": 2}
    assert (stats["derived_on_assumed_polling_exit"], stats["derived_on_storage_model"],
            stats["derived_on_register_memory"]) == (1, 1, 1)
    (item,) = [i for i in build_disclosures("sits", {"integration_oracle": stats}) if i["key"] == "sits_integration_oracle"]
    assert "scripts/integration_oracle_clang_check.py 의 clang 대조는 공용체 멤버의" in item["note"], item["note"]


# ══ (R90 re-review 3) the callee boundary, hypothetical probes, members read under another value, cost ═══════════════

ROOT4 = os.path.join(os.sep, "p90c")
H4 = """typedef unsigned char U8;
typedef unsigned int U16;
typedef union { U8 Byte; struct { U8 RSTA :1; U8 BUSY :1; U8 :6; } Bits; } FLWSTR;
extern volatile FLWSTR REG_FLW @0x00000390;
extern volatile FLWSTR REG_B @0x00000391;
#define FLW REG_FLW.Byte
#define FLW_RSTA REG_FLW.Bits.RSTA
#define FLW_BUSY REG_FLW.Bits.BUSY
#define FLW_RSTA_MASK 0x01U
#define FLW_BUSY_MASK 0x02U
#define B_RSTA REG_B.Bits.RSTA
#define B_RSTA_MASK 0x01U
#define B_BUSY_MASK 0x02U
typedef union { U8 Byte; struct { U8 A :1; U8 :7; } Bits; } XSTR;
XSTR g_u;
#define U_A g_u.Bits.A
#define U_A_MASK 0x01U
#define TP(n) REG_##n.Bits.RSTA
extern volatile FLWSTR REG_C @0x00000394;
extern volatile FLWSTR REG_D @0x00000395;
extern volatile FLWSTR REG_E @0x00000396;
extern volatile FLWSTR REG_F @0x00000397;
#define C_RSTA REG_C.Bits.RSTA
#define C_RSTA_MASK 0x01U
#define C_BUSY REG_C.Bits.BUSY
#define C_BUSY_MASK 0x02U
#define D_RSTA REG_D.Bits.RSTA
#define D_RSTA_MASK 0x01U
#define E_RSTA REG_E.Bits.RSTA
#define E_RSTA_MASK 0x01U
#define F_RSTA REG_F.Bits.RSTA
#define F_RSTA_MASK 0x01U
typedef union { U16 Word; struct { U8 H; U8 L; } Bytes; } WSTR;
extern volatile WSTR REG_W @0x00000398;
"""
C4 = """#include "h4.h"
U8 g_o; U8 g_p; U8 g_n; U8 g_m; U8 g_side; U8 g_x;
void Wait_ok(void) { while (REG_FLW.Bits.RSTA == 1U) {} }
void Wait_sat(void) { U8 n = 0U; while (REG_FLW.Bits.RSTA == 1U) { if (n < 3U) { n++; } } g_side = n; }
void Wait_readflag(void) { while (REG_FLW.Bits.RSTA == 1U) { g_n = REG_FLW.Byte; } }
void c_ok(void) { Wait_ok(); g_o = REG_FLW.Byte; g_p = 7U; }
void c_sat(void) { Wait_sat(); g_o = REG_FLW.Byte; g_p = 7U; }
void c_readflag(void) { Wait_readflag(); g_o = REG_FLW.Byte; g_p = 7U; }
void c_other(void) { Wait_ok(); g_o = REG_B.Byte; }
U8 Is_Busy(void) { return (U8)REG_FLW.Bits.RSTA; }
void Latch(void) { g_m = REG_FLW.Byte; }
void v1(void) { g_n = 1U; while (REG_FLW.Bits.RSTA == 1U) { g_n = Is_Busy(); } g_o = g_n; }
void v2(void) { g_m = 1U; while (REG_FLW.Bits.RSTA == 1U) { Latch(); } g_o = g_m; }
void v3(void) { g_n = 0U; while (REG_FLW.Bits.RSTA == 1U) { if (Is_Busy() == 0U) { g_n = 7U; } } g_o = g_n; }
void i2_callee_cond(void) { while (Is_Busy() != 0U) {} g_o = 8U; }
U8 Rec(void);
U8 Helper(U8 v) { if (v == 0x80U) { return Rec(); } return (U8)(v + 1U); }
U8 Rec(void) { return Helper(1U); }
void lk1(void) { while ((REG_FLW.Byte != 0U) && (Helper(REG_FLW.Byte) != 0U)) {} g_o = Helper(4U); }
void w_same(void) { while ((REG_FLW.Bits.RSTA == 1U) || (REG_FLW.Bits.BUSY == 1U)) {} }
void n1(void) { while ((REG_FLW.Bits.RSTA == 1U) || (REG_FLW.Bits.BUSY == 1U)) {} g_o = 8U; }
void n2(void) { g_p = 7U; w_same(); g_o = 8U; }
void a4_or_exit_on_b(void) { while ((FLW_RSTA == 1U) || (B_RSTA == 1U)) {} g_o = REG_B.Byte; }
void f3_in_counter(void) { U8 i; for (i = 0U; i < 3U; i++) { while (FLW_RSTA == 1U) {} g_o = i; } }
void f4_two_seq(void) { while (FLW_RSTA == 1U) {} while (FLW_RSTA == 1U) {} g_o = 8U; }
void m1_input(void) { while ((REG_FLW.Bits.RSTA == 1U) || (g_x == 1U)) {} g_o = 8U; }
void m2_union(void) { while ((REG_FLW.Bits.RSTA == 1U) || (U_A == 1U)) {} g_o = 8U; }
void w8(void) { while (FLW != 0U) {} g_o = 8U; }
void Wait_tp(void) { while (TP(FLW) == 1U) {} }
volatile U8 *const g_pFlw = &REG_FLW.Byte;
#define RD(p) (*(p))
void WaitP(volatile U8 *p) { while ((*p & 0x01U) != 0U) {} }
void WaitG(void) { while ((*g_pFlw & 0x01U) != 0U) {} }
void WaitM(volatile U8 *p) { while ((RD(p) & 0x01U) != 0U) {} }
void WaitBM(void) {
#define LOCAL_FLAG REG_FLW.Bits.RSTA
    while (LOCAL_FLAG == 1U) {}
#undef LOCAL_FLAG
}
void c_param(void) { WaitP(&FLW); g_o = FLW_RSTA; g_p = 7U; }
void c_global(void) { WaitG(); g_o = FLW_RSTA; g_p = 7U; }
void c_macro(void) { WaitM(&REG_FLW.Byte); g_o = FLW_RSTA; g_p = 7U; }
void c_bodymacro(void) { WaitBM(); g_o = REG_FLW.Byte; g_p = 7U; }
U8 WaitR(void) { while (REG_FLW.Bits.RSTA == 1U) {} return 2U; }
void c_ret(void) { g_x = WaitR(); g_o = REG_FLW.Byte; g_p = 7U; }
void body_if_b(void) { g_n = 0U; while ((REG_FLW.Bits.RSTA == 1U) || (REG_B.Bits.RSTA == 1U)) { if (REG_B.Bits.RSTA == 0U) { g_n = 9U; } } g_o = 4U; }
void body_copy_b(void) { g_n = 1U; while ((REG_FLW.Bits.RSTA == 1U) || (REG_B.Bits.RSTA == 1U)) { g_n = REG_B.Byte; } g_o = 4U; }
void outer_inner(void) { while (REG_C.Bits.RSTA == 1U) { while ((REG_FLW.Bits.RSTA == 1U) || (REG_C.Bits.BUSY == 1U)) {} } g_o = 4U; }
U8 Clr(void) { REG_FLW.Byte = 0U; return 2U; }
U8 Wseq(void) { while (REG_FLW.Bits.RSTA == 1U) {} return 2U; }
void c_wait(void) { g_o = (U8)(REG_FLW.Byte + Wseq()); }
void c_wait_macro(void) { g_o = (U8)(FLW + Wseq()); }
void c_clr(void) { g_o = (U8)(REG_FLW.Byte + Clr()); }
void c_wait_stub(void) { g_o = (U8)(REG_FLW.Byte + Wseq()); }
void Esc(U8 *p) { (void)p; }
void F(U8 *p) { (void)p; }
void mstub(void) { Esc(&g_x); g_x = 3U; while ((REG_FLW.Bits.RSTA == 1U) || (F(&g_x), 0U)) {} g_o = g_x; }
U8 g_a; U8 g_b; U8 g_c; U8 g_d;
void mub(void) { (void)(g_a / g_b); while ((REG_FLW.Bits.RSTA == 1U) || ((g_c % g_d), 0U)) {} g_o = 4U; }
void chain6(void) {
    while ((REG_FLW.Bits.RSTA == 1U) || ((REG_B.Bits.RSTA == 1U) || ((REG_C.Bits.RSTA == 1U) ||
           ((REG_D.Bits.RSTA == 1U) || ((REG_E.Bits.RSTA == 1U) || (REG_F.Bits.RSTA == 1U)))))) {}
    g_o = 5U;
}
void wide_held(void) { while ((REG_FLW.Bits.RSTA == 1U) || (REG_W.Word != 0x1234U)) {} g_o = 6U; }
void k15(void) { for (;;) { while ((REG_FLW.Bits.RSTA == 1U) || (REG_FLW.Bits.BUSY == 1U)) {} if (g_x == 1U) { break; } } }
void dec_reg(void) { if (REG_B.Bits.RSTA == 1U) { g_o = 1U; } else { g_o = 2U; } }
volatile U8 *g_vp;
#define FLW_ADDR ((volatile U8 *)0x00000390UL)
void WaitW(volatile U8 *p) { *p = 1U; }
void St(volatile U8 *p) { *p = 9U; }
void int_addr_write(void) { *(volatile U8 *)0x390U = 0x01U; g_o = FLW_RSTA; }
void int_addr_local(void) { volatile U8 *p = (volatile U8 *)0x390U; *p = 0x01U; g_o = FLW_RSTA; }
void int_addr_callee(void) { WaitW((volatile U8 *)0x390U); g_o = FLW_RSTA; }
void global_ptr_write(void) { *g_vp = 0x01U; g_o = FLW_RSTA; }
void int_addr_index(void) { ((volatile U8 *)0x380U)[16] = 0x01U; g_o = FLW_RSTA; }
void stub_hw(void) { St((volatile U8 *)0x390U); g_o = FLW; }
void stub_hw_macro(void) { St(FLW_ADDR); g_o = FLW; }
void direct_hw_macro(void) { *FLW_ADDR = 0x01U; g_o = FLW; }
void two_callees(void) { Wait_ok(); Wait_readflag(); Wait_ok(); g_o = REG_B.Byte; }
void ub_reg(void) { g_o = (U8)(100U / REG_FLW.Byte); }
void c_tp(void) { Wait_tp(); g_o = REG_FLW.Byte; g_p = REG_B.Byte; }
"""
FILES4 = {os.path.join(ROOT4, "h4.h"): H4, os.path.join(ROOT4, "u4.c"): C4}
CONTEXT4 = cpc.build_project_context(FILES4)
U4 = os.path.join(ROOT4, "u4.c")
SCOPES4 = cpc.build_scopes(CONTEXT4, [U4])


def _provider4():
    from generators.integration_oracle import CalleeProvider
    return CalleeProvider(CONTEXT4, FILES4, SCOPES4, cpc.shared_parser())


def _run4(name, rows, provider=None, text=C4):
    """One record per row (``rows``: one inputs dict, or a list of them — they share the function's kept answers)."""
    unit = {"name": name, "source_text": text, "source_path": U4, "source_text_complete": True,
            "project_scope": SCOPES4[U4]}
    if provider is not None:
        unit["callee_provider"] = provider
    many = isinstance(rows, list)
    rows = rows if many else [rows]
    out = evaluate_outputs(unit, rows, [["g_o", "g_p"]] * len(rows))
    return out if many else out[0]


# ── (C-R3-1) a callee the run does not interpret leaves the registers it reads unknown ──────────────────────────────

@pytest.mark.parametrize("fn, integrated", [("c_ok", False), ("c_sat", False), ("c_readflag", False),
                                            ("c_sat", True), ("c_readflag", True)])
def test_a_callee_not_interpreted_leaves_the_registers_it_reads_unknown(fn, integrated):
    # under the model a poll whose flag never changes does not return, under the polling assumption the flag changed:
    #   the row's 1 is the register's value under neither (the unit run; the integrated run where the poll is refused)
    r = _run4(fn, {"REG_FLW.Byte": 1, "REG_B.Byte": 1, "g_o": 0}, provider=_provider4() if integrated else None)
    callee = {"c_ok": "Wait_ok", "c_sat": "Wait_sat", "c_readflag": "Wait_readflag"}[fn]
    assert r["outputs"]["g_o"] == {"reason": "register_read_by_callee_not_interpreted:" + callee}, r["outputs"]
    assert r["outputs"]["g_p"] == {"value": 7, "basis": "assigned"}


def test_a_callee_whose_text_hides_its_names_leaves_every_register_unknown():
    # ``REG_##n`` (token pasting): the closure cannot name what it reads — no register keeps the row's value
    r = _run4("c_tp", {"REG_FLW.Byte": 1, "REG_B.Byte": 5})
    assert r["outputs"]["g_o"] == {"reason": "register_read_by_callee_not_interpreted:Wait_tp"}, r["outputs"]
    assert r["outputs"]["g_p"] == {"reason": "register_read_by_callee_not_interpreted:Wait_tp"}, r["outputs"]


def test_a_register_the_closure_does_not_name_is_unknown_too():
    # (re-review 4 C-R4-1) Wait_ok's closure names REG_FLW only — a callee may reach any register through a pointer
    r = _run4("c_other", {"REG_FLW.Byte": 1, "REG_B.Byte": 5})
    assert r["outputs"]["g_o"] == {"reason": "register_read_by_callee_not_interpreted:Wait_ok"}


@pytest.mark.parametrize("fn", ["c_param", "c_global", "c_macro", "c_bodymacro"])
def test_a_callee_reaching_the_register_through_a_pointer_or_a_body_macro_leaves_it_unknown(fn):
    # WaitP(&FLW) · *g_pFlw · RD(p) · a #define in the callee's body: no closure names REG_FLW
    for provider in (None, _provider4()):
        r = _run4(fn, {"REG_FLW.Byte": 1, "g_o": 9}, provider=provider)
        assert "value" not in r["outputs"]["g_o"], (fn, provider, r["outputs"])
        assert r["outputs"]["g_p"] == {"value": 7, "basis": "assigned"}


def test_a_sequence_stub_keeps_the_register_the_row_set():
    # the harness replaces the body (R38): nothing polls — the register is the row's
    r = _run4("c_ret", {"REG_FLW.Byte": 1, "WaitR() return": 5})
    assert r["outputs"]["g_o"] == {"value": 1, "basis": "assigned"} and r["stubs"] == ["WaitR"]
    assert _run4("c_ret", {"REG_FLW.Byte": 1})["outputs"]["g_o"] == {
        "reason": "register_read_by_callee_not_interpreted:WaitR"}


# ── (C-R3-2) a body that reads the flag through a callee ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("fn", ["v1", "v2", "v3"])
def test_a_body_that_reads_the_flag_through_an_interpreted_callee_is_refused(fn):
    r = _run4(fn, {"REG_FLW.Byte": 1}, provider=_provider4())
    assert _refused(r, "polling_loop_body_reads_flag:REG_FLW"), r


def test_a_condition_that_reads_the_flag_through_a_callee_is_a_poll():
    r = _run4("i2_callee_cond", {"REG_FLW.Byte": 1}, provider=_provider4())
    assert r["outputs"]["g_o"]["value"] == 8 and r["polling_loops_assumed"] == [
        "i2_callee_cond:" + str(C4.count("\n", 0, C4.index("void i2_callee_cond(")) + 1) + ":REG_FLW"]


# ── (W-R3-1) a hypothetical probe leaves nothing behind ────────────────────────────────────────────────────────────

def test_a_callee_that_fails_on_a_hypothetical_flag_value_refuses_the_loop():
    # flag 0x80 makes Helper re-enter itself (recursion: it fails) — run as its effects only on that probe, it may wait
    #   on any register (re-review 4 C-R4-1): the poll that ends the loop may change state, never assumed
    r = _run4("lk1", {"REG_FLW.Byte": 1}, provider=_provider4())
    assert _refused(r, "polling_loop_condition_changes_state"), r


def test_a_hypothetical_probe_puts_back_what_it_records(monkeypatch):
    # (W-R3-1, X5) whatever a probe records on the activation and on the world is gone after it — a callee failure, an
    #   inline count, an admitted object, a register read, the storage used
    from generators import c_source_oracle as cso
    seen = []
    search = cso._Interp.polling_search

    def probing(self, state, cond, members):
        world = self.world
        before = (dict(world.failed), dict(world.inlined), dict(world.not_inlined), dict(world.effects_only),
                  set(world.static_keys), dict(world.objects), list(self.volatile_polls),
                  list(self.volatile_poll_members), set(self.storage_used), set(self.stubs_used), list(self.polling_assumed))
        with self.hypothetical():
            world.fail("Ghost", "probe")
            world.inlined["Ghost"] = 9
            world.effects_only["Ghost"] = 9
            world.static_keys.add("@ghost")
            world.objects["ghost"] = ("global", {})
            self.volatile_polls.append("GHOST")
            self.volatile_poll_members.append(("GHOST", "Byte"))
            self.storage_used.add("GHOST")
            self.stubs_used.add("Ghost")
            self.polling_assumed.append("ghost:1:GHOST")
        after = (dict(world.failed), dict(world.inlined), dict(world.not_inlined), dict(world.effects_only),
                 set(world.static_keys), dict(world.objects), list(self.volatile_polls),
                 list(self.volatile_poll_members), set(self.storage_used), set(self.stubs_used), list(self.polling_assumed))
        seen.append(before == after)
        return search(self, state, cond, members)
    monkeypatch.setattr(cso._Interp, "polling_search", probing)
    r = _run4("i2_callee_cond", {"REG_FLW.Byte": 1}, provider=_provider4())
    assert seen and all(seen) and r["outputs"]["g_o"]["value"] == 8


def test_a_probe_s_reads_are_not_the_record_s():
    # a union only the hypothetical value reads (g_u, read when RSTA = 0) is not among the run's storage objects, and the
    #   callee a probe inlines is counted as often as the run itself calls it
    r = _run4("m2_union", {"REG_FLW.Byte": 1, "g_u.Byte": 0})
    assert r["outputs"]["g_o"]["value"] == 8 and r["storage_objects"] == ["REG_FLW"]
    r = _run4("i2_callee_cond", {"REG_FLW.Byte": 1}, provider=_provider4())
    assert r["interprocedural"]["inlined"] == {"Is_Busy": 2}, r["interprocedural"]   # two real polls, not the probes'


def test_the_search_rounds_end_with_no_proof_when_members_keep_coming():
    # each round finds the next register of the chain: after the last round one is still unread under some value
    r = _run4("chain6", {"REG_FLW.Byte": 1, "REG_B.Byte": 1, "REG_C.Byte": 1, "REG_D.Byte": 1, "REG_E.Byte": 1,
                         "REG_F.Byte": 1})
    assert _refused(r, "polling_loop_exit_search_incomplete"), r


# ── (W-R3-2) a member the condition reads only under another flag value ─────────────────────────────────────────────

def test_a_member_read_only_under_another_flag_value_is_varied_too():
    # RSTA = 1 short-circuits BUSY away; RSTA = BUSY = 0 ends the loop — no "non_terminating_loop"
    for integrated in (False, True):
        r = _run4("n1", {"REG_FLW.Byte": 3}, provider=_provider4() if integrated else None)
        assert r["outputs"]["g_o"]["value"] == 8 and r["polling_loops_assumed"]
    r = _run4("n2", {"REG_FLW.Byte": 3}, provider=_provider4())   # was: the whole row refused
    assert r["outputs"] == {"g_o": {"value": 8, "basis": "assigned"}, "g_p": {"value": 7, "basis": "assigned"}}
    # a register read only then is polled as well: unknown after the loop, never the row's value
    r = _run4("a4_or_exit_on_b", {"REG_FLW.Byte": 1, "REG_B.Byte": 0})
    assert r["outputs"]["g_o"] == {"reason": "polling_loop_exit_assumed:REG_B"}
    assert r["polling_loops_assumed"][0].endswith(":REG_B+REG_FLW")


# ── (I-R3-1) a flag the model reads as unknown keeps the path the hardware ends ─────────────────────────────────────

def test_consecutive_and_nested_polls_end_with_their_values():
    assert _run4("f4_two_seq", {"REG_FLW.Byte": 1})["outputs"]["g_o"] == {"value": 8, "basis": "assigned"}
    r = _run4("f3_in_counter", {"REG_FLW.Byte": 1})
    assert r["outputs"]["g_o"] == {"value": 2, "basis": "assigned"} and len(r["polling_loops_assumed"]) == 3


# ── (W-R3-3) the way-out search is kept per function, for the inputs it read ─────────────────────────────────────────

def _fresh_function_cache(monkeypatch):
    """A new per-text cache (`c_source_oracle._parsed_function` — its ``shared`` holds the kept way-out answers)."""
    from collections import OrderedDict

    from generators import c_source_oracle as cso
    monkeypatch.setattr(cso._TREES, "cache", OrderedDict(), raising=False)
    return cso


def test_every_row_searches_its_own_way_out():
    # (re-review 4: nothing is kept between rows) the condition reads g_x — g_x = 1 has no way out, g_x = 0 has one
    a, b, c = _run4("m1_input", [{"REG_FLW.Byte": 1, "g_x": 1}, {"REG_FLW.Byte": 1, "g_x": 0},
                                 {"REG_FLW.Byte": 1, "g_x": 1}])
    assert _refused(a, "non_terminating_loop") and _refused(c, "non_terminating_loop"), (a, c)
    assert b["outputs"]["g_o"]["value"] == 8
    a, b = _run4("m2_union", [{"REG_FLW.Byte": 1, "g_u.Byte": 1}, {"REG_FLW.Byte": 1, "g_u.Byte": 0}])
    assert _refused(a, "non_terminating_loop") and b["outputs"]["g_o"]["value"] == 8, (a, b)
    # (C-R4-2) a row whose stub writes through the condition's call refuses after a row that does not stub it
    b, a = _run4("mstub", [{"REG_FLW.Byte": 1}, {"REG_FLW.Byte": 1, "F() p[0]": 5}], provider=_provider4())
    assert b["outputs"]["g_o"] == {"value": 3, "basis": "assigned"}
    assert _refused(a, "polling_loop_condition_changes_state"), a
    # (W-R4-1) the possible UB of the way-out poll is the row's own: not lost after a row that had it already
    one, two = _run4("mub", [{"REG_FLW.Byte": 1, "g_a": 4, "g_c": 1}, {"REG_FLW.Byte": 1, "g_a": 4, "g_b": 2, "g_c": 1}])
    assert one["possible_undefined_behavior"] == two["possible_undefined_behavior"] == ["division_by_unknown"], (one, two)


def test_a_budget_the_way_out_search_spent_says_so(monkeypatch):
    cso = _fresh_function_cache(monkeypatch)
    monkeypatch.setattr(cso, "_EXECUTION_BUDGET", 60)
    r = _run4("n1", {"REG_FLW.Byte": 3})
    assert r["reason"] == "execution_budget:polling_way_out_search", r


# ── (W-R3-4) the clang checks do not judge a cell that rests on the storage model ────────────────────────────────────

def test_the_clang_checks_leave_storage_model_cells_unchecked(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import openpyxl

    from generators.c_source_oracle import STORAGE_ASSUMPTION
    from scripts.integration_oracle_clang_check import _read_claims
    from scripts.source_oracle_clang_check import _STORAGE_MARK, check_claims
    assert STORAGE_ASSUMPTION.startswith(_STORAGE_MARK)
    unit = {"name": "c_other", "source_text": C4, "source_path": U4, "project_scope": SCOPES4[U4]}
    claims = [{"unit": unit, "inputs": {"REG_B.Byte": 5}, "outputs": {"g_o": 5}, "storage_objects": ["REG_B"]}]
    report = check_claims(claims, work_dir=str(tmp_path))
    assert claims[0]["verdicts"] == {"g_o": "unchecked:storage_model"}
    assert report["unchecked_reasons"]["storage_model"] == 1 and report["checked"] == 0
    # the integration check reads the same mark off a SITS 'Test Evidence' row
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Test Evidence"
    ws.append(["Status", "Source path", "Entry function", "Test Case ID", "Case", "Observable", "Expected", "Reason",
               "Inputs JSON", "Source SHA256", "Assumptions"])
    ws.append(["derived", U4, "c_other", "T1", 1, "g_o", 5, "", "{}", "", STORAGE_ASSUMPTION + ": REG_B"])
    ws.append(["derived", U4, "c_ok", "T2", 1, "g_p", 7, "", "{}", "", "other"])
    path = tmp_path / "sits.xlsx"
    wb.save(path)
    grouped, _unreadable = _read_claims(str(path))
    assert [bool(g.get("storage_model")) for g in grouped.values()] == [True, False]


# ══ (R90 re-review 4) conservative callees, body reads of every polled flag, sequencing, decision claims ═════════════

# ── (C-R4-3) a body that reads a register the search added to the polled ones ───────────────────────────────────────

@pytest.mark.parametrize("fn", ["body_if_b", "body_copy_b"])
def test_a_body_that_reads_a_flag_the_condition_reads_only_under_another_value_is_refused(fn):
    # the body's last run comes before the poll that ends the loop: REG_B may already be 0 then (g_n = 9 / 0)
    for provider in (None, _provider4()):
        r = _run4(fn, {"REG_FLW.Byte": 1, "REG_B.Byte": 1}, provider=provider)
        assert _refused(r, "polling_loop_body_reads_flag:REG_B"), (fn, r)


def test_an_inner_loop_s_searched_flag_is_a_read_of_the_outer_body():
    # the inner loop reads REG_C.BUSY only under another value of REG_FLW — on the target it reads it: the outer loop
    #   polls REG_C and its body reads it — never a value (the refusal is whichever budget or verdict comes first)
    r = _run4("outer_inner", {"REG_FLW.Byte": 1, "REG_C.Byte": 1})
    assert r["status"] == "unsupported" and "value" not in r["outputs"]["g_o"], r


# ── (C-R4-4) a register read beside a call is indeterminately sequenced with it ──────────────────────────────────────

@pytest.mark.parametrize("fn", ["c_wait", "c_wait_macro", "c_clr"])
def test_a_register_read_beside_a_call_is_refused_as_unsequenced(fn):
    for provider in (None, _provider4()):
        r = _run4(fn, {"REG_FLW.Byte": 1}, provider=provider)
        assert r["status"] == "unsupported" and r["reason"].startswith("call_unsequenced_with_access:"), (fn, r)


def test_a_register_read_beside_a_sequence_stub_is_sequenced():
    r = _run4("c_wait_stub", {"REG_FLW.Byte": 1, "Wseq() return": 2})
    assert r["outputs"]["g_o"] == {"value": 3, "basis": "assigned"}, r


# ── (I-R4-1) a wide member is varied over the value it holds too ────────────────────────────────────────────────────

def test_a_wide_member_keeps_its_held_value_among_the_tried_ones():
    # RSTA = 0 with the word still 0x1234 ends the loop: 0 / 0xFFFF / ~0x1234 alone would find no way out
    r = _run4("wide_held", {"REG_FLW.Byte": 1, "REG_W.Word": 0x1234})
    assert r["outputs"]["g_o"]["value"] == 6 and r["polling_loops_assumed"][0].endswith(":REG_FLW+REG_W"), r


# ── budget reasons by their head (K13 · K14 · K15) ──────────────────────────────────────────────────────────────────

def test_a_budget_reason_that_names_its_spender_is_a_budget_everywhere(monkeypatch):
    from generators.integration_oracle import _refused_for_budget
    from generators.scenario_rows import _stopped_by_budget
    named = "execution_budget:polling_way_out_search"
    assert _refused_for_budget({"expected_evidence": {"g_o": {"status": "unknown", "reason": named}}})
    assert _stopped_by_budget(named) and not _stopped_by_budget("polling_loop_body_changes_state")
    # a constant-condition loop the search's budget stopped with no way out yet: never assumed to return
    cso = _fresh_function_cache(monkeypatch)
    monkeypatch.setattr(cso, "_EXECUTION_BUDGET", 60)
    r = _run4("k15", {"REG_FLW.Byte": 3, "g_x": 1}, provider=_provider4())
    assert r["reason"] == "constant_condition_loop_unfinished", r


# ── (W-R4-4) decision claims on the storage model are not clang-checked ─────────────────────────────────────────────

def _if_condition_spec(fn):
    """The decision spec (`observe_decisions`) of the first ``if`` condition in ``fn`` — one atom."""
    from generators import c_source_oracle as cso
    raw = C4.encode()
    start = raw.index(("void " + fn + "(").encode())
    stack, found = [cso.cpc.shared_parser().parse(raw).root_node], []
    while stack:
        n = stack.pop()
        if n.type == "if_statement" and n.start_byte > start:
            found.append(n)
        stack.extend(n.children)
    cond = min(found, key=lambda n: n.start_byte).child_by_field_name("condition")
    inner = [c for c in cond.named_children if c.type != "comment"][0]
    key = [inner.start_byte, inner.end_byte, inner.type]
    return {"key": key, "atoms": [key], "ir": ["atom", 0]}


def test_a_decision_run_on_the_storage_model_says_so_and_its_claims_are_unchecked(tmp_path):
    import sys

    from generators import c_source_oracle as cso
    from generators.mcdc_design import _Pairer
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from source_findings import _storage_objects
    from source_oracle_clang_check import check_claims
    unit = {"name": "dec_reg", "source_text": C4, "source_path": U4, "source_text_complete": True,
            "project_scope": SCOPES4[U4]}
    (rec,) = cso.observe_decisions(unit, [{"REG_B.Byte": 1}], [_if_condition_spec("dec_reg")])
    assert rec["status"] == "supported" and rec["storage_objects"] == ["REG_B"], rec
    pairer = _Pairer("D1", 1)
    pairer.add({"x": 1}, {"truth": [True], "decision": True, "observed": [True]}, [], rec["storage_objects"])
    pairer.add({"x": 2}, {"truth": [False], "decision": False, "observed": [True]}, [], [])
    assert pairer.pairs[0]["storage_objects_a"] == ["REG_B"] and "storage_objects_b" not in pairer.pairs[0]
    # a UB-probe claim: the oracle's run of the example — refused here — names the storage objects it used
    assert _storage_objects({**unit, "name": "ub_reg"}, {"inputs": {"REG_FLW.Byte": 0}, "observable": "g_o"}) == [
        "REG_FLW"]
    claims = [{"unit": unit, "inputs": {}, "outputs": {"g_o": 4}, "storage_objects": ["REG_B"]}]
    assert check_claims(claims, work_dir=str(tmp_path))["unchecked_reasons"] == {"storage_model": 1}
    # the MC/DC claims a path-designed pair makes carry the side's storage objects into that check
    from mcdc_design_clang_oracle import _path_claims
    spec = _if_condition_spec("dec_reg")
    pair = {"pair_id": "D1:C1:P1", "inputs_a": {"REG_B.Byte": 1}, "truth_a": [True], "observed_a": [True],
            "decision_a": True, "storage_objects_a": ["REG_B"], "inputs_b": {"REG_B.Byte": 0}, "truth_b": [False],
            "observed_b": [True], "decision_b": False}
    report = {"function": "dec_reg", "decisions": [{"evaluation": "source_path", "pairs": [pair], "path_spec": spec}]}
    assert [c["storage_objects"] for c in _path_claims(unit, report)] == [["REG_B"], []]


# ── (X5) every attribute of an activation and of the world is put back by a probe, or exempt with a reason ──────────

def test_the_hypothetical_lists_cover_every_attribute():
    import ast

    from generators import c_source_oracle as cso
    tree = ast.parse(Path(cso.__file__).read_text(encoding="utf-8"))
    listed = set(cso._HYPOTHETICAL_TABLES) | set(cso._HYPOTHETICAL_WORLD_TABLES) | set(cso._HYPOTHETICAL_WORLD_GROWING)
    exempt = cso._HYPOTHETICAL_EXEMPT
    assert not listed & set(exempt) and all(isinstance(v, str) and v.strip() for v in exempt.values())
    found = set()
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in ("_Interp", "_World")):
        for n in ast.walk(cls):
            targets = n.targets if isinstance(n, ast.Assign) else \
                [n.target] if isinstance(n, (ast.AnnAssign, ast.AugAssign)) else []
            for tg in targets:
                for e in (tg.elts if isinstance(tg, ast.Tuple) else [tg]):
                    if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id == "self":
                        found.add(e.attr)
    assert found - listed - set(exempt) == set(), sorted(found - listed - set(exempt))
    assert len(found) >= 80   # the walk saw the constructors


# ══ (R90 re-review 5) writes through integer addresses, probes on forked paths, attributes at run time ══════════════

# ── (C-R5-1) an integer address is the hardware — where the @-placed registers are ───────────────────────────────────

@pytest.mark.parametrize("fn", ["int_addr_write", "int_addr_local", "int_addr_callee", "global_ptr_write",
                                "int_addr_index", "direct_hw_macro"])
def test_a_write_through_an_integer_address_or_an_unknown_pointer_leaves_the_registers_unknown(fn):
    # the row's REG_FLW.Byte = 0 is not what FLW_RSTA reads after ``*(volatile U8 *)0x390U = 1U`` (the target: 1)
    for provider in (None, _provider4()):
        r = _run4(fn, {"REG_FLW.Byte": 0}, provider=provider)
        assert "value" not in r["outputs"]["g_o"], (fn, provider, r["outputs"])


@pytest.mark.parametrize("fn", ["stub_hw", "stub_hw_macro"])
def test_a_stub_writing_its_out_parameter_at_an_integer_address_leaves_the_registers_unknown(fn):
    # VectorCAST's stub writes the row's ``St() p[0]`` at 0x390 — REG_FLW — whether or not a stub is set
    for inputs in ({"REG_FLW.Byte": 1, "St() p[0]": 5}, {"REG_FLW.Byte": 1}):
        for provider in (None, _provider4()):
            r = _run4(fn, inputs, provider=provider)
            assert "value" not in r["outputs"]["g_o"], (fn, inputs, provider, r["outputs"])
    r = _run4(fn, {"REG_FLW.Byte": 1, "St() p[0]": 5})
    assert r["stubs"] == ["St"] and r["outputs"]["g_o"] == {"reason": "stub_pointer_argument:St"}


# ── (I-R5-4) every callee the run did not interpret is named ─────────────────────────────────────────────────────

def test_the_reason_names_every_callee_not_interpreted():
    r = _run4("two_callees", {"REG_FLW.Byte": 0, "REG_B.Byte": 5})
    assert r["outputs"]["g_o"] == {"reason": "register_read_by_callee_not_interpreted:Wait_ok+Wait_readflag"}


# ── (I-R5-2) the members a search added are reads of the loop ───────────────────────────────────────────────────

def test_the_members_the_search_added_are_the_loop_s_reads(monkeypatch):
    from generators import c_source_oracle as cso
    added = []
    exit_ = cso._Interp.polling_exit

    def recording(self, pending, done, polled, node, cond=None, members=(), body_reads=frozenset()):
        mark = len(self.volatile_polls)
        out = exit_(self, pending, done, polled, node, cond, members, body_reads)
        added.append((self.volatile_polls[mark:], self.volatile_poll_members[mark:]))
        return out
    monkeypatch.setattr(cso._Interp, "polling_exit", recording)
    r = _run4("a4_or_exit_on_b", {"REG_FLW.Byte": 1, "REG_B.Byte": 0})
    assert r["polling_loops_assumed"] and added == [(["REG_B"], [("REG_B", "Bits.RSTA")])], added


# ── (I-R5-1) every attribute an activation or the world has after a run is restored by a probe or exempt ─────────────

def test_every_attribute_of_a_run_is_listed(monkeypatch):
    from generators import c_source_oracle as cso
    listed = set(cso._HYPOTHETICAL_TABLES) | set(cso._HYPOTHETICAL_WORLD_TABLES) | set(cso._HYPOTHETICAL_WORLD_GROWING)
    known = listed | set(cso._HYPOTHETICAL_EXEMPT)
    seen = {}
    tick = cso._Interp.tick

    def collecting(self):
        seen.setdefault(id(self), self)
        return tick(self)
    monkeypatch.setattr(cso._Interp, "tick", collecting)
    # an integrated run: an entry, an inlined callee in a polling condition, a stub, a failed inline
    r = _run4("i2_callee_cond", {"REG_FLW.Byte": 1}, provider=_provider4())
    assert r["outputs"]["g_o"]["value"] == 8
    _run4("c_sat", {"REG_FLW.Byte": 1}, provider=_provider4())
    _run4("c_ret", {"REG_FLW.Byte": 1, "WaitR() return": 5}, provider=_provider4())
    interps = list(seen.values())
    assert len(interps) >= 4
    for it in interps:
        assert set(vars(it)) <= known, sorted(set(vars(it)) - known)
        if it.world is not None:
            assert set(vars(it.world)) <= known, sorted(set(vars(it.world)) - known)


def test_the_points_to_hardware_object_reaches_every_register(monkeypatch):
    # (C-R5-1 ①) a callee / stub summary that names only `G:<hardware>` — an integer address — reaches the registers:
    #   white-box, since the analysis names an integer address `?U:hardware` too wherever these probes reach it
    from generators import c_source_oracle as cso
    from generators.pointer_flow import HARDWARE
    seen = []
    tick = cso._Interp.tick

    def collecting(self):
        if not seen:
            seen.append(self)
        return tick(self)
    monkeypatch.setattr(cso._Interp, "tick", collecting)
    _run4("dec_reg", {"REG_B.Byte": 1})
    state = cso._State()
    seen[0].havoc_objects(state, {HARDWARE}, "hw_write", direct=frozenset(), through_pointer=True)
    assert state.havoc_bases.get(cso._VOLATILE_STORAGE) == "hw_write", state.havoc_bases
