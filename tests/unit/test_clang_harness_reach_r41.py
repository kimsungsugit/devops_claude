"""R41 — the SUTS clang harness compiles the units it used to lose to three harness gaps.

The independent clang check (`scripts/source_oracle_clang_check.py`) counted a unit *unchecked* whenever its harness
did not compile. In the R40 generated SUTS that was HDPDM01 2,672 and KJPDS02_PV 8,598 derived cells; three causes
were the harness's own, not the source's:

* an output the body never names — a global the oracle holds at its input value because nothing the function runs
  writes it — was not declared (``use of undeclared identifier``);
* ``enum TAG`` written without a typedef (``void f(enum en_g_DoorState s)``) is a forward reference C++ forbids — the
  integrated harness already named it by an underlying-type typedef (R16b), this one did not;
* a ``<stdint.h>`` name the project typedefs under ``#ifndef uint16_t`` stays unresolved in the scope (a reserved name
  the model does not decide) — a local ``uint16_t t;`` did not compile. The harness now spells it by the target's
  widths when every permitted underlying type gives the same values.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from generators import c_project_context as cpc  # noqa: E402

H = """typedef unsigned char U8;
typedef unsigned int U16;
typedef unsigned short int vu16;
typedef signed long S32;
#ifndef uint16_t
typedef unsigned int uint16_t;
#endif
#ifndef int32_t
typedef signed long int32_t;
#endif
enum en_state { ST_IDLE = 0, ST_RUN = 1, ST_STOP = 2 };
typedef struct { U8 a; U16 b; } TS;
"""
C = """#include "h.h"
enum en_state g_state;
U8 g_out;
U8 g_keep;
U8 g_arr[4];
TS g_s;
U16 g_w;

void f_keep(U8 x) { g_out = (U8)(x + 1U); }
void f_enum(enum en_state s) { if (s == ST_RUN) { g_out = 1U; } else { g_out = 2U; } }
void f_enum_local(U8 x) { enum en_state t; t = (enum en_state)x; g_state = t; }
U16 f_std(U16 v) { uint16_t t; int32_t d; t = (uint16_t)(v + 1U); d = (int32_t)t - 3; g_w = t; return (U16)d; }
void f_enum_cast(U8 x) { enum en_state t; t = (enum en_state)x; g_out = (U8)(t == 200); }
void f_penum(enum en_state *p) { g_out = (U8)(p[0] == ST_RUN); }
#define AS_STATE(x) ((enum en_state)(x))
void f_macro_enum(U8 x) { g_state = AS_STATE(x); }
void ext_call(void);
void f_call(U8 x) { g_out = x; ext_call(); }
void f_comment(U8 x) { g_out = x; /* g_keep = 1U; */ // g_keep++;
}
"""


@pytest.fixture(scope="module")
def units(tmp_path_factory):
    from reference_alignment import _load_source
    root = tmp_path_factory.mktemp("r41") / "src"
    root.mkdir()
    for name, text in (("h.h", H), ("u.c", C)):
        (root / name).write_text(text, encoding="utf-8", newline="\n")
    texts, context, _ = _load_source([root])
    path = next(p for p in texts if p.endswith("u.c"))
    scope = cpc.build_scopes(context, [path])[path]
    return scope, (lambda fn: {"name": fn, "source_text": texts[path], "source_path": path,
                               "source_text_complete": True, "project_scope": scope})


def _check(claims):
    if shutil.which("clang") is None:
        pytest.skip("clang not installed")
    from source_oracle_clang_check import check_claims
    return check_claims(claims)


def _tally(report):
    return report["checked"], report["agree"], report["mismatch"], report["eval_error"], report["unchecked"]


def test_the_fixture_is_what_the_real_trees_look_like(units):
    scope, _ = units
    assert "uint16_t" in scope["unresolved_types"] and "int32_t" in scope["unresolved_types"]
    assert "enum en_state" in scope["types"] and "en_state" not in scope["types"]
    assert "g_s" in scope["struct_globals"] and "g_keep" in scope["globals"] and "g_arr" in scope["arrays"]


def test_an_output_the_body_never_names_is_declared_with_its_input_value(units):
    _, unit = units
    inputs = {"x": 4, "g_keep": 9, "g_arr[2]": 5, "g_s.a": 3}
    claim = {"unit": unit("f_keep"), "inputs": inputs, "outputs": {"g_out": 5, "g_keep": 9, "g_arr[2]": 5, "g_s.a": 3}}
    report = _check([claim])
    # the unit compiles and its named output is checked; the three it never names are no check — clang only returns
    #   the value the harness declared them with (review W1): unchecked, and listed for review
    assert _tally(report) == (1, 1, 0, 0, 3)
    assert report["unchecked_reasons"] == {"output_not_named_by_body": 3}
    assert list(report["outputs_not_named_by_body"].values()) == [["g_arr[2]", "g_keep", "g_s.a"]]
    assert claim["verdicts"] == {"g_out": "agree", "g_keep": "unchecked:output_not_named_by_body",
                                 "g_arr[2]": "unchecked:output_not_named_by_body",
                                 "g_s.a": "unchecked:output_not_named_by_body"}
    # the harness really holds the claim's input: a different value is a contradiction, not an agreement
    wrong = _check([{"unit": unit("f_keep"), "inputs": inputs, "outputs": {"g_keep": 8, "g_arr[2]": 6, "g_s.a": 4}}])
    assert _tally(wrong) == (3, 0, 3, 0, 0)
    # (review I-R3-1) the review list is structural: a mismatch on an unnamed output is listed too
    assert list(wrong["outputs_not_named_by_body"].values()) == [["g_arr[2]", "g_keep", "g_s.a"]]


def test_an_output_the_claim_does_not_set_takes_the_fills_and_is_not_agreed(units):
    # an unnamed output the claim leaves unset varies with the fills (0 / 90 / 201): no single claimed value holds
    _, unit = units
    report = _check([{"unit": unit("f_keep"), "inputs": {"x": 4}, "outputs": {"g_keep": 0}}])
    assert report["agree"] == 0 and report["mismatch"] == 1


def test_an_untagged_enum_parameter_and_local_compile(units):
    _, unit = units
    report = _check([{"unit": unit("f_enum"), "inputs": {"s": 1}, "outputs": {"g_out": 1}},
                     {"unit": unit("f_enum"), "inputs": {"s": 2}, "outputs": {"g_out": 2}},
                     {"unit": unit("f_enum_local"), "inputs": {"x": 2}, "outputs": {"g_state": 2}}])
    assert _tally(report) == (3, 3, 0, 0, 0)
    wrong = _check([{"unit": unit("f_enum"), "inputs": {"s": 1}, "outputs": {"g_out": 2}}])
    assert wrong["mismatch"] == 1


def test_an_untagged_enum_is_checked_under_every_permitted_underlying_type(units):
    # ``(enum en_state)200`` is 200 for an int or unsigned base but -56 for a signed char one: a claim that holds for one
    # permitted type only is a contradiction — the enum-base loop must run although no enum *typedef* is named
    _, unit = units
    report = _check([{"unit": unit("f_enum_cast"), "inputs": {"x": 200}, "outputs": {"g_out": 1}}])
    assert report["agree"] == 0 and report["mismatch"] == 1
    fine = _check([{"unit": unit("f_enum_cast"), "inputs": {"x": 2}, "outputs": {"g_out": 0}}])
    assert _tally(fine) == (1, 1, 0, 0, 0)


def test_an_unresolved_stdint_name_is_spelled_by_the_target_widths(units):
    _, unit = units
    report = _check([{"unit": unit("f_std"), "inputs": {"v": 5}, "outputs": {"return": 3, "g_w": 6}},
                     {"unit": unit("f_std"), "inputs": {"v": 65535}, "outputs": {"return": 65533, "g_w": 0}}])
    assert _tally(report) == (4, 4, 0, 0, 0)
    wrong = _check([{"unit": unit("f_std"), "inputs": {"v": 5}, "outputs": {"return": 4}}])
    assert wrong["mismatch"] == 1


def test_stdint_spelling_only_where_the_widths_fix_the_values():
    from source_oracle_clang_check import _stdint_spelling
    msp430 = {"char": 8, "short": 16, "int": 16, "long": 32}
    assert _stdint_spelling("uint16_t", msp430) == "unsigned int"      # short and int of one width promote alike
    assert _stdint_spelling("int16_t", msp430) == "signed int"
    assert _stdint_spelling("int32_t", msp430) == "signed long"
    assert _stdint_spelling("uint8_t", msp430) == "unsigned char"
    assert _stdint_spelling("uint64_t", msp430) is None                # no width testimony: not guessed
    ilp32 = {"char": 8, "short": 16, "int": 32, "long": 32}
    assert _stdint_spelling("int32_t", ilp32) is None                  # int and long: two types (conservative)
    assert _stdint_spelling("uint16_t", {"short": 16, "int": 32}) == "unsigned short"
    assert _stdint_spelling("uint16_t", {}) is None


def test_a_resolved_project_typedef_is_left_as_the_scope_says(tmp_path):
    # a stdint name the scope resolves (an unconditional project typedef) keeps the scope's typedef — the width rule is
    # for unresolved names only. Here the scope says ``unsigned short`` where the rule would spell ``unsigned int``: a
    # second typedef would be a redefinition with a different type, and the unit would not compile (unchecked)
    from reference_alignment import _load_source
    root = tmp_path / "src"
    root.mkdir()
    (root / "h.h").write_text("typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned short uint16_t;\n",
                              encoding="utf-8", newline="\n")
    (root / "u.c").write_text('#include "h.h"\nU16 g_o;\nvoid f(U8 x) { uint16_t t; t = (uint16_t)(x + 200U); '
                              "g_o = t; }\n", encoding="utf-8", newline="\n")
    texts, context, _ = _load_source([root])
    path = next(p for p in texts if p.endswith("u.c"))
    scope = cpc.build_scopes(context, [path])[path]
    assert scope["types"]["uint16_t"]["kind"] == "short" and "uint16_t" not in scope["unresolved_types"]
    unit = {"name": "f", "source_text": texts[path], "source_path": path, "source_text_complete": True,
            "project_scope": scope}
    report = _check([{"unit": unit, "inputs": {"x": 100}, "outputs": {"g_o": 300}}])
    assert _tally(report) == (1, 1, 0, 0, 0)


def test_an_unnamed_output_of_a_unit_with_calls_is_not_a_stubbed_agreement(units):
    # (review W3 c) the stubs write nothing either way: an unnamed output stays "not named", never an agreement
    _, unit = units
    claim = {"unit": unit("f_call"), "inputs": {"x": 3, "g_keep": 9}, "outputs": {"g_out": 3, "g_keep": 9}}
    report = _check([claim])
    assert claim["verdicts"] == {"g_out": "agree_with_stubbed_callees", "g_keep": "unchecked:output_not_named_by_body"}
    assert (report["agree"], report["agree_with_stubbed_callees"], report["unchecked"]) == (1, 1, 1)


def test_a_pointer_to_an_untagged_enum_and_an_enum_in_a_macro_compile(units):
    # (review W3 a · I1) the pointee buffer's type and a macro body's ``enum TAG`` are renamed too
    _, unit = units
    report = _check([{"unit": unit("f_penum"), "inputs": {"p[0]": 1}, "outputs": {"g_out": 1}},
                     {"unit": unit("f_macro_enum"), "inputs": {"x": 2}, "outputs": {"g_state": 2}}])
    assert _tally(report) == (2, 2, 0, 0, 0)


def test_a_width_the_target_does_not_have_leaves_the_unit_unchecked(units):
    # (review W2) testimony that ``int`` is 32 bits spells ``int32_t`` as ``signed int`` — 16 bits on msp430: the
    #   width assertion fails. That is the harness disagreeing with the target, not a contradiction of the oracle,
    #   in the check and in the UB probe (where a counted run would read as "not reproduced")
    scope, unit = units
    u = dict(unit("f_std"))
    u["project_scope"] = {**scope, "target": {"widths": {"char": 8, "short": 16, "int": 32}}}
    claim = {"unit": u, "inputs": {"v": 5}, "outputs": {"return": 3, "g_w": 6}}
    report = _check([claim])
    assert _tally(report) == (0, 0, 0, 0, 2)
    assert report["unchecked_reasons"] == {"stdint_width_disagrees_with_target": 2}
    assert claim["verdicts"] == {"return": "unchecked:stdint_width_disagrees_with_target",
                                 "g_w": "unchecked:stdint_width_disagrees_with_target"}
    from source_oracle_clang_check import check_claims
    probe = check_claims([{"unit": u, "inputs": {"v": 5}, "outputs": {"g_w": 0}}], ub_probe=True)
    assert (probe["checked"], probe["eval_error"], probe["mismatch"]) == (0, 0, 0)


def test_the_ub_probe_counts_an_unnamed_output_as_evaluated(units):
    # (review W-R2-1) in the probe the asserted value is a placeholder: agree and mismatch both say "no UB on the run" —
    #   an unnamed observable whose input happens to be 0 must still count as evaluated (else a model false positive
    #   would drop out of the false-positive rate)
    if shutil.which("clang") is None:
        pytest.skip("clang not installed")   # (review W-R3-1) check_claims is called directly
    _, unit = units
    from source_oracle_clang_check import check_claims
    probe = check_claims([{"unit": unit("f_keep"), "inputs": {"x": 4, "g_keep": 0}, "outputs": {"g_keep": 0}}],
                         ub_probe=True)
    assert (probe["checked"], probe["eval_error"], probe["unchecked"]) == (1, 0, 0)
    assert "outputs_not_named_by_body" not in probe


def test_a_name_left_in_a_comment_is_not_named_by_the_code(units):
    # (review I-R2-1) ``/* g_keep = 1U; */`` is no write: the output is still one the code never names
    _, unit = units
    claim = {"unit": unit("f_comment"), "inputs": {"x": 1, "g_keep": 9}, "outputs": {"g_out": 1, "g_keep": 9}}
    report = _check([claim])
    assert claim["verdicts"] == {"g_out": "agree", "g_keep": "unchecked:output_not_named_by_body"}
    assert (report["agree"], report["unchecked"]) == (1, 1)
