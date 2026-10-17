"""R7 (P4/G5) — interface contract of an integration flow (`generators/interface_contract.py`).

Everything is read from the caller's and callee's text: how a cross-module return value is used, which values it is
checked against, argument bindings, global producer → consumer. Suggested return values (never applied) come only
from the source.
"""
from __future__ import annotations

import openpyxl

from generators import c_project_context as cpc
from generators.interface_contract import (
    INTERFACE_EVIDENCE_HEADERS,
    SourceIndex,
    attach_interface_contract,
    enumerators,
    file_scope_globals,
    flow_contract,
    injection_values,
    int_defines,
    write_interface_evidence_sheet,
)

LIN = """typedef unsigned char U8;
typedef enum { ERROR_OK = 0, ERROR_LIN_TIMEOUT = 1, ERROR_LIN_CHECKSUM } Error_t;
#define LIN_READY (3U)
U8 g_lin_state;
Error_t LinRecv(U8 *buf) { buf[0] = 1U; return ERROR_OK; }
U8 LinReady(void) { return g_lin_state; }
void LinSetup(U8 id, U8 len) { g_lin_state = (U8)(id + len); }
"""
APP = """typedef unsigned char U8;
typedef enum { ERROR_OK = 0, ERROR_LIN_TIMEOUT = 1, ERROR_LIN_CHECKSUM } Error_t;
extern U8 g_lin_state;
U8 g_app_out;
void AppStep(void) {
    U8 buf[2];
    U8 id = 1U, len = 2U;
    if (LinRecv(buf) != ERROR_OK) { g_app_out = 0U; return; }
    if (LinReady() == LIN_READY) { g_app_out = 2U; }
    LinSetup(id, len);
    LinReady();
    g_app_out = g_lin_state;
}
"""


def _texts():
    return {"src/lin.c": LIN, "src/app.c": APP}


def _index():
    return SourceIndex(_texts(), cpc.shared_parser())


def test_cross_module_calls_say_how_the_return_is_used_and_what_it_is_checked_against():
    index = _index()
    c = flow_contract(["AppStep", "LinRecv", "LinReady", "LinSetup"], index, {"g_lin_state", "g_app_out"})
    by = {(p["callee"], p["line"]): p for p in c["calls"]}
    recv = next(p for (callee, _l), p in by.items() if callee == "LinRecv")
    assert recv["return_use"] == {"use": "checked", "operator": "!=", "against": "ERROR_OK"}
    ready = sorted((p for (callee, _l), p in by.items() if callee == "LinReady"), key=lambda p: p["line"])
    assert ready[0]["return_use"]["against"] == "LIN_READY" and ready[1]["return_use"] == {"use": "ignored"}
    setup = next(p for (callee, _l), p in by.items() if callee == "LinSetup")
    assert "return_use" not in setup  # void: not an interface value
    assert setup["bindings"] == [{"param": "id", "type": "U8", "arg": "id"}, {"param": "len", "type": "U8", "arg": "len"}]
    assert setup["swappable_pairs"] == [["id", "len"]]


def test_a_global_written_in_one_module_and_read_in_another_is_a_producer_consumer_pair():
    c = flow_contract(["AppStep", "LinSetup"], _index(), {"g_lin_state", "g_app_out"})
    assert c["global_flows"] == [{"global": "g_lin_state", "producer": "LinSetup", "producer_module": "lin",
                                  "consumer": "AppStep", "consumer_module": "app"}]


def test_a_call_in_the_same_module_is_not_an_interface():
    texts = {"src/a.c": "int g(void) { return 1; }\nint f(void) { return g() == 1; }\n"}
    c = flow_contract(["f", "g"], SourceIndex(texts, cpc.shared_parser()), set())
    assert c["calls"] == []


def test_injected_values_come_from_the_source_only():
    enums = enumerators(_texts(), cpc.shared_parser())
    defines = int_defines(_texts())
    assert enums["ERROR_LIN_CHECKSUM"] == (2, ("ERROR_OK", "ERROR_LIN_TIMEOUT", "ERROR_LIN_CHECKSUM"))
    assert defines["LIN_READY"] == 3

    def bounds(t):
        return (0, 255) if t == "U8" else None

    def point(**use):
        return {"return_use": use, "return_type": "U8"}
    assert injection_values(point(use="checked", operator="!=", against="ERROR_OK"), defines, enums, bounds) == (
        ["ERROR_OK (0)", "ERROR_LIN_TIMEOUT (1)"], "enum_sibling")
    assert injection_values(point(use="checked", operator="==", against="LIN_READY"), defines, enums, bounds) == (
        ["LIN_READY (3)", "4"], "compared_value_and_neighbour")
    assert injection_values(point(use="checked", operator="<", against="10"), defines, enums, bounds)[0] == ["9", "10"]
    assert injection_values(point(use="checked", operator="truth", against="0"), defines, enums, bounds) == (
        ["0", "1"], "truth_value")
    assert injection_values(point(use="assigned", to="x"), defines, enums, bounds) == (["0", "255"],
                                                                                      "return_type_bounds")
    assert injection_values({"return_use": {"use": "assigned"}, "return_type": "Foo_t"}, defines, enums, bounds) == (
        [], "return_type_bounds_unknown")
    assert injection_values(point(use="checked", operator="==", against="s_mode"), defines, enums, bounds) == (
        [], "compared_value_unresolved")


def test_a_macro_defined_twice_with_different_values_is_not_used():
    assert "X" not in int_defines({"a.h": "#define X 1\n", "b.h": "#define X 2\n"})
    assert int_defines({"a.h": "#define Y (0x10U) /* ready */\n"}) == {"Y": 16}


def test_attaching_annotates_the_flow_and_never_changes_the_test():
    # (review round 1 W1) the callee is integrated code on the flow: its return is suggested, not injected
    cases = [{"case_num": 1, "inputs": {"g_x": 0}, "expected": {"g_app_out": 0}, "precondition": "1"}]
    itc = {"tc_id": "SwITC_01", "call_chain": "AppStep -> LinRecv", "input_vars": ["g_x"],
           "expected_vars": ["g_app_out"], "sub_cases": [dict(c) for c in cases]}
    stats = attach_interface_contract([itc], _texts(), cpc.shared_parser(), lambda t: None, unreadable=["x.c"])
    assert itc["input_vars"] == ["g_x"] and itc["sub_cases"] == cases
    (recv,) = [pt for pt in itc["interface_contract"]["calls"] if pt["callee"] == "LinRecv"]
    assert recv["suggestion"] == {"column": "LinRecv() return", "values": ["ERROR_OK (0)", "ERROR_LIN_TIMEOUT (1)"],
                                  "basis": "enum_sibling"}
    assert stats["suggestion_basis:enum_sibling"] == 1 and stats["used_returns"] == 1
    assert stats["unreadable_source_files"] == 1   # (review W5) a skipped file is counted


def test_a_return_that_cannot_be_given_two_source_values_says_why():
    itc = {"tc_id": "SwITC_02", "call_chain": "AppStep -> LinReady", "input_vars": [], "expected_vars": [],
           "sub_cases": []}
    texts = dict(_texts())
    texts["src/app.c"] = texts["src/app.c"].replace("LinReady() == LIN_READY", "LinReady() == s_mode")
    stats = attach_interface_contract([itc], texts, cpc.shared_parser(), lambda t: None)
    assert stats["suggestion_skipped:compared_value_unresolved"] == 1
    skipped = [pt for pt in itc["interface_contract"]["calls"] if pt.get("suggestion")]
    assert skipped[0]["suggestion"] == {"skipped": "compared_value_unresolved"}


def _use(caller_text):
    texts = {"src/lin.c": "typedef unsigned char U8;\ntypedef unsigned short U16;\nU8 f(void) { return 1U; }\n",
             "src/app.c": "typedef unsigned char U8;\ntypedef unsigned short U16;\nU8 x;\nvoid g(void) {\n" + caller_text
             + "\n}\n"}
    c = flow_contract(["g", "f"], SourceIndex(texts, cpc.shared_parser()), set())
    return c["calls"][0]["return_use"]


def test_return_use_looks_through_casts_stored_tests_and_conditionals():
    # (review round 1 W4)
    assert _use("if ((x = f()) != 3U) { x = 0U; }") == {"use": "checked", "operator": "!=", "against": "3U"}
    assert _use("x = (U8)f();") == {"use": "assigned", "to": "x"}
    assert _use("x = f() ? 1U : 2U;")["use"] == "checked"
    assert _use("(void)f();") == {"use": "ignored", "note": "cast_to_void"}


def test_a_call_on_the_right_of_a_comparison_is_read_from_its_side():
    # (review W2) ``10U < f()`` is ``f() > 10U``: the suggested pair must fall on both sides
    use = _use("if (10U < f()) { x = 1U; }")
    assert use == {"use": "checked", "operator": ">", "against": "10U"}
    assert injection_values({"return_use": use, "return_type": "U8"}, {}, {}, lambda t: (0, 255))[0] == ["10", "11"]


def test_a_neighbour_outside_the_return_type_is_not_suggested():
    # (review W3) ``U8 f() == 0xFFU`` has no 256
    point = {"return_use": {"use": "checked", "operator": "==", "against": "0xFFU"}, "return_type": "U8"}
    assert injection_values(point, {}, {}, lambda t: (0, 255)) == ([], "neighbour_outside_return_type")


def test_two_files_with_one_name_are_two_modules_and_a_twice_defined_function_is_left_out():
    # (review W6) APP/lin.c and FBL/lin.c are not one module; ``f`` defined in both is ambiguous
    texts = {"app/lin.c": "int f(void) { return 1; }\nint h(void) { return 2; }\n",
             "fbl/lin.c": "int f(void) { return 3; }\nint k(void) { return h() == 2 && f() == 1; }\n"}
    index = SourceIndex(texts, cpc.shared_parser())
    c = flow_contract(["k", "h", "f"], index, set())
    # different files: an interface — and the call of the ambiguous ``f`` is not one (round 2 m9)
    assert [(pt["caller"], pt["callee"]) for pt in c["calls"]] == [("k", "h")]
    assert c["ambiguous_functions"] == ["f"]


def test_an_enumerator_with_two_values_in_two_enums_is_not_used():
    texts = {"a.h": "typedef enum { ST_OK = 0, ST_BAD = 1 } A;\n", "b.h": "typedef enum { ST_OK = 5 } B;\n"}
    assert "ST_OK" not in enumerators(texts, cpc.shared_parser())


def test_the_evidence_sheet_lists_suggested_and_skipped_points():
    itc = {"tc_id": "SwITC_01", "call_chain": "AppStep -> LinRecv -> LinSetup", "input_vars": [],
           "expected_vars": ["g_app_out"], "sub_cases": [{"case_num": 1, "inputs": {}, "expected": {}}]}
    attach_interface_contract([itc], _texts(), cpc.shared_parser(), lambda t: None)
    wb = openpyxl.Workbook()
    n = write_interface_evidence_sheet(wb, [itc])
    rows = list(wb["Interface Evidence"].iter_rows(values_only=True))
    assert list(rows[0]) == INTERFACE_EVIDENCE_HEADERS and n == len(rows) - 1
    recv = next(r for r in rows[1:] if r[4] == "LinRecv")
    assert recv[8] == "LinRecv() return" and recv[10] == "enum_sibling"
    assert rows[0][8] == "Suggested Stimulus (not applied)"
    setup = next(r for r in rows[1:] if r[4] == "LinSetup")
    assert setup[7] == "void" and setup[12] == "id/len"


def test_file_scope_globals_are_objects_not_functions():
    assert file_scope_globals(_texts(), cpc.shared_parser()) == {"g_lin_state", "g_app_out"}


# ── deep review round 2 ──────────────────────────────────────────────

def test_a_typedef_cast_with_a_parenthesized_operand_is_a_cast_not_a_call():
    """(W-2) ``(U16)(f())`` parses as a call of ``(U16)``: the return is assigned, and nothing is unresolved."""
    assert _use("x = (U16)(f());") == {"use": "assigned", "to": "x"}
    assert _use("x = (U8)(U16)f();") == {"use": "assigned", "to": "x"}      # nested casts (m6)
    texts = {"src/lin.c": "typedef unsigned short U16;\nU16 f(void) { return 1U; }\n",
             "src/app.c": "typedef unsigned short U16;\nU16 x;\nvoid g(void) { x = (U16)(f()); }\n"}
    c = flow_contract(["g", "f"], SourceIndex(texts, cpc.shared_parser()), set())
    assert c["unresolved_calls"] == [] and [p["callee"] for p in c["calls"]] == ["f"]


def test_a_stored_value_that_is_tested_is_checked():
    assert _use("if ((x = f())) { x = 0U; }") == {"use": "checked", "operator": "truth", "against": "0"}
    assert _use("if ((U8)(x = f()) != 3U) { x = 1U; }") == {"use": "checked", "operator": "!=", "against": "3U"}


def test_the_other_side_operators_flip_both_ways():
    # (m1) ``10U <= f()`` is ``f() >= 10U``; (m2) ``f() >= 10`` holds at 10 and not at 9
    assert _use("if (10U <= f()) { x = 1U; }") == {"use": "checked", "operator": ">=", "against": "10U"}
    assert _use("if (10U >= f()) { x = 1U; }") == {"use": "checked", "operator": "<=", "against": "10U"}
    point = {"return_use": {"use": "checked", "operator": ">=", "against": "10"}, "return_type": "U8"}
    assert injection_values(point, {}, {}, lambda t: (0, 255))[0] == ["9", "10"]
    point["return_use"]["operator"] = "<="
    assert injection_values(point, {}, {}, lambda t: (0, 255))[0] == ["10", "11"]


def test_a_conflicting_sibling_enumerator_is_not_another_value():
    """(W-1) ``Y`` has two values in two enums and is dropped: ``f() != X`` has no known other value — no KeyError."""
    enums = enumerators({"a.h": "typedef enum { X = 0, Y = 1 } A;\n", "b.h": "typedef enum { Y = 5 } B;\n"},
                        cpc.shared_parser())
    point = {"return_use": {"use": "checked", "operator": "!=", "against": "X"}, "return_type": "A"}
    assert injection_values(point, {}, enums, lambda t: None) == ([], "enum_has_no_other_value")


def test_a_definition_named_by_a_keyword_is_preprocessor_debris_not_a_function():
    """(W-5) ``else if (…)`` left at file scope by a broken ``#if`` parses as a function ``if``."""
    index = SourceIndex({"x.c": "void f(void) {\n}\n else if (LIN_T == e)\n{\n h();\n}\n"}, cpc.shared_parser())
    assert sorted(index.defs) == ["f"] and index.duplicates == set() and index.keyword_definitions == 1


def test_octal_literals_and_a_comment_inside_a_define_are_read_as_c_does():
    assert int_defines({"a.h": "#define O 010\n#define W 1U /* c */ + 2\n#define Z (0x10U) /* ok */\n"}) == {
        "O": 8, "Z": 16}


def test_the_counts_keep_the_distinct_points_apart_from_the_per_flow_sums():
    """(W-4) two flows over one call count it twice in the sums and once in the distinct counts."""
    itcs = [{"tc_id": f"SwITC_0{i}", "call_chain": "AppStep -> LinRecv", "input_vars": [], "expected_vars": [],
             "sub_cases": []} for i in (1, 2)]
    stats = attach_interface_contract(itcs, _texts(), cpc.shared_parser(), lambda t: None)
    assert (stats["cross_module_calls"], stats["distinct_cross_module_calls"]) == (2, 1)
    assert (stats["used_returns"], stats["distinct_used_returns"]) == (2, 1)


def test_a_for_loop_tests_only_its_condition():
    """(round 3 W1) ``for (i = f(); …)`` / ``for (;; i = f())`` assign; ``for (; f(); )`` tests."""
    assert _use("for (x = f(); x < 3U; x++) { }") == {"use": "assigned", "to": "x"}
    assert _use("for (;; x = f()) { }") == {"use": "assigned", "to": "x"}
    assert _use("for (; f(); ) { x = 1U; }") == {"use": "checked", "operator": "truth", "against": "0"}
    assert _use("for (f(); x < 3U; x++) { }")["use"] != "checked"


def test_headline_counts_are_recorded_at_zero():
    itc = {"tc_id": "SwITC_01", "call_chain": "AppStep -> LinSetup", "input_vars": [], "expected_vars": [],
           "sub_cases": []}
    stats = attach_interface_contract([itc], _texts(), cpc.shared_parser(), lambda t: None)
    assert stats["used_returns"] == 0 and stats["distinct_used_returns"] == 0 and stats["cross_module_calls"] == 1
