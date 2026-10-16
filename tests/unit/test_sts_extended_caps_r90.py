"""R90 — the default (extended) STS document carries every branch and every step the caps used to cut, without moving
any TC that was already there.

User: "설정이나 이런건 최대 우리 효율이 나올 수 있는 걸로 디폴트 값을 변경해야해". The per-function TC cap
(`max_tc_per_req`, 5) and the per-TC step cap (`max_steps_per_tc`, 15) cut real branches (no test for them) and the tail
of long TCs (an action without its expected result), silently. Review R90: lifting the cap inside the extended pass moved
302 of 694 HDPDM01 extended TC IDs onto other functions and still left functions the reference block had partly tested
(W1) — so the TCs the old caps produce keep their place, ID and branch (a truncated one gets its steps back under the
same ID), and what the caps cut goes at the end of the requirement under new IDs. Losses are counted per function (W2).
"""
from __future__ import annotations

import copy

from generators.sts import (
    _EXTENDED_UNCAPPED,
    _cap_losses,
    _generate_steps_from_flow,
    _pair_branches,
    _renumber_cap_appended,
    _step_key,
    generate_test_cases,
)
from report_gen.generation_disclosures import build_disclosures

_SWITCH = [{"type": "switch", "expr": "mode", "cases": [{"label": f"M{i}", "body": [f"Do{i}"]} for i in range(8)]}]
_LONG = [{"type": "if", "condition": "n > 1",
          "true_body": [{"type": "call", "name": f"Step{i}"} for i in range(30)],
          "false_body": [{"type": "call", "name": "Other"}]}]


def _fn(name, flow):
    return {"id": name, "name": name, "prototype": f"void {name}(U8 n)", "inputs": ["[IN] U8 n"], "outputs": [],
            "calls_list": [], "logic_flow": flow}


def _gen(profile, fd, mapping, max_tc=2, max_steps=None):
    stats: dict = {}
    cfg = {"max_tc_per_req": max_tc, "tc_profile": profile}
    if max_steps:
        cfg["max_steps_per_tc"] = max_steps
    tcs = generate_test_cases(copy.deepcopy([{"id": "SwTR_0001", "req_type": "TR"}]), fd, mapping, cfg, stats_out=stats)
    return tcs, stats


def _of(tcs, name):
    return [t for t in tcs if t["title"].endswith(f" - {name}")]


def _all(name, flow):
    return [t for t in _generate_steps_from_flow(flow, _fn(name, flow), max_steps=_EXTENDED_UNCAPPED,
                                                 max_tc=_EXTENDED_UNCAPPED, keep_boundary=True) if t]


def test_every_branch_of_every_function_is_in_the_default_document():
    # `Ref` gets 2 TCs in the reference block (req cap 2), `E1`/`E2` go to the extended pass
    fd = {"F1": _fn("Ref", _SWITCH), "F2": _fn("E1", _SWITCH), "F3": _fn("E2", _SWITCH)}
    tcs, st = _gen("extended", fd, {"SwTR_0001": ["F1", "F2", "F3"]})
    for name in ("Ref", "E1", "E2"):
        assert len(_of(tcs, name)) == len(_all(name, _SWITCH)), name   # 8 cases + boundary, nothing cut
    assert st["cap_lost_tcs"] == 0 and st["cap_lost_functions"] == 0 and st["extended_appended_tcs"] > 0


def test_the_ids_the_old_caps_produced_do_not_move():
    # old rule: E1 phase (2 + boundary) then E2 phase — E2's first TC id must stay where it was; the cut cases come after
    fd = {"F1": _fn("Ref", _SWITCH), "F2": _fn("E1", _SWITCH), "F3": _fn("E2", _SWITCH)}
    tcs, _st = _gen("extended", fd, {"SwTR_0001": ["F1", "F2", "F3"]})
    ids = [t["id"] for t in tcs]
    capped = [t for t in _generate_steps_from_flow(_SWITCH, _fn("E1", _SWITCH), max_steps=15, max_tc=2, keep_boundary=True) if t]
    e1, e2 = _of(tcs, "E1"), _of(tcs, "E2")
    first_e1 = ids.index(e1[0]["id"])
    # E1's capped TCs, then E2's capped TCs, contiguous — exactly the old layout
    assert [t["id"] for t in tcs[first_e1:first_e1 + 2 * len(capped)]] == \
        [t["id"] for t in e1[:len(capped)]] + [t["id"] for t in e2[:len(capped)]]
    # every TC after that block is an appended one (no old TC moved behind them)
    assert all(ids.index(t["id"]) >= first_e1 + 2 * len(capped) for t in e1[len(capped):] + e2[len(capped):])


def test_a_long_tc_keeps_its_id_and_gets_its_steps_back():
    fd = {"F1": _fn("Ref", _SWITCH), "F2": _fn("Long", _LONG)}
    tcs, st = _gen("extended", fd, {"SwTR_0001": ["F1", "F2"]}, max_tc=2, max_steps=15)
    assert max(len(t["steps"]) for t in _of(tcs, "Long")) > 15
    assert st["cap_cut_step_tcs"] == 0


def test_the_reference_profile_still_caps_and_says_how_much_per_function():
    fd = {"F1": _fn("Only", _SWITCH)}
    tcs, st = _gen("reference", fd, {"SwTR_0001": ["F1"]}, max_tc=5, max_steps=3)
    assert len(tcs) == 5 and max(len(t["steps"]) for t in tcs) <= 3
    assert (st["cap_lost_functions"], st["cap_lost_tcs"]) == (1, len(_all("Only", _SWITCH)) - 5)
    assert st["cap_cut_step_tcs"] == 0 and st["extended_appended_tcs"] == 0   # the 5 kept cases have 2 steps each
    _t, st2 = _gen("reference", {"F1": _fn("Long", _LONG)}, {"SwTR_0001": ["F1"]}, max_tc=5, max_steps=15)
    assert st2["cap_cut_step_tcs"] >= 1, "a TC that lost its tail steps is counted"


def test_branch_matching_is_exact_first_then_prefix_and_one_to_one():
    a = [{"action": "x", "expected": "1"}, {"action": "y", "expected": "2"}]
    full = [a, list(a), [{"action": "z", "expected": "3"}]]
    # the whole TC takes the first identical branch; the cut one (a prefix) takes what is left
    assert _pair_branches(full, [a[:1], a]) == {1: 0, 0: 1}
    assert _cap_losses(full, [[a[:1], a]]) == ([2], 1)


# Review C1: a nested branch's TC carries its parent's steps in front and comes before it — prefix-first pairing matched the
#   parent TC with the sibling the cap dropped (that sibling "was in the document", loss 0) and filled the parent's ID with
#   the sibling's steps.
_INNER = {"type": "if", "condition": "b == 0", "true_body": [{"type": "call", "name": "X"}],
          "elif_chains": [{"condition": f"b == {i}", "body": [{"type": "call", "name": f"Y{i}"}]} for i in range(1, 6)],
          "false_body": []}
_LADDER = [{"type": "if", "condition": "a > 0", "true_body": [_INNER], "false_body": [{"type": "call", "name": "Z"}]}]


def _branches(tcs, name, flow, enrich):
    """Which full branch each document TC is (the longest full TC its steps start with — the document may add min steps)."""
    fkeys = [_step_key(t) for t in _generate_steps_from_flow(
        copy.deepcopy(flow), _fn(name, flow), max_steps=_EXTENDED_UNCAPPED, max_tc=_EXTENDED_UNCAPPED, keep_boundary=True,
        enrich=enrich) if t]
    out = []
    for t in _of(tcs, name):
        k = _step_key(t["steps"])
        hits = [j for j, fk in enumerate(fkeys) if k[:len(fk)] == fk]
        out.append(max(hits, key=lambda j: len(fkeys[j])) if hits else None)
    return out, len(fkeys)


def test_a_nested_else_if_ladder_loses_no_branch_and_lists_none_twice():
    for where in ("reference_block", "extended_pass"):
        fd = {"F1": _fn("Ext", _LADDER)}
        mapping = {"SwTR_0001": ["F1"]}
        if where == "extended_pass":     # the reference block fills the requirement first, so `Ext` goes to the extended pass
            fd["F0"] = _fn("Ref", _SWITCH)
            mapping = {"SwTR_0001": ["F0", "F1"]}
        tcs, st = _gen("extended", fd, mapping, max_tc=5)
        got, n_full = _branches(tcs, "Ext", _LADDER, enrich=True)
        assert sorted(got) == list(range(n_full)), (where, got)       # every branch once — none dropped, none twice
        assert (st["cap_lost_tcs"], st["cap_cut_step_tcs"]) == (0, 0), where
        ref, st_ref = _gen("reference", fd, mapping, max_tc=5)
        ref_got, _n = _branches(ref, "Ext", _LADDER, enrich=False)
        if ref_got:
            assert st_ref["cap_lost_tcs"] == n_full - len(set(ref_got)), "the reference document counts what it lost"


def test_the_old_ids_keep_their_branch_in_the_extended_pass():
    # the IDs the old caps gave `Ext` keep the old branch (the parent TC did not become the dropped sibling)
    fd = {"F0": _fn("Ref", _SWITCH), "F1": _fn("Ext", _LADDER)}
    mapping = {"SwTR_0001": ["F0", "F1"]}
    tcs, _st = _gen("extended", fd, mapping, max_tc=5)
    old = [t for t in _generate_steps_from_flow(copy.deepcopy(_LADDER), _fn("Ext", _LADDER), max_steps=15, max_tc=5,
                                                keep_boundary=True, enrich=True) if t]
    ext = [t for t in _of(tcs, "Ext") if not t.get("cap_appended")]
    assert [_step_key(t["steps"])[:len(o)] for t, o in zip(ext, old, strict=True)] == [_step_key(o) for o in old]


def test_a_function_repeated_under_two_requirements_is_not_counted_as_whole():
    # the same capped emission under two requirements: the second parent copy must not pair with a dropped child
    a = [{"action": "p", "expected": "1"}]
    child = a + [{"action": "c", "expected": "2"}]
    full = [child, a, [{"action": "s", "expected": "3"}]]
    assert _cap_losses(full, [[a], [a]]) == ([0, 2], 0)


def test_the_reference_block_fills_its_cut_tcs_in_the_extended_document():
    # review W2: a long function the reference block carries — the extended document fills it at the same ID
    fd = {"F1": _fn("Long", _LONG)}
    ext, st = _gen("extended", fd, {"SwTR_0001": ["F1"]}, max_tc=5, max_steps=15)
    ref, st_ref = _gen("reference", fd, {"SwTR_0001": ["F1"]}, max_tc=5, max_steps=15)
    assert st_ref["cap_cut_step_tcs"] >= 1 and st["cap_cut_step_tcs"] == 0
    assert [t["id"] for t in ref] == [t["id"] for t in ext[:len(ref)]]
    assert max(len(t["steps"]) for t in ext) > 15


def test_appended_tcs_go_after_their_requirement_without_reordering_the_document():
    # review I6: a requirement id listed twice — the document's order stays as it was
    tcs = [{"id": "SwTC_R1_01", "srs_id": "R1"}, {"id": "SwTC_R0_01", "srs_id": "R0"}, {"id": "SwTC_R1_02", "srs_id": "R1"}]
    reqs = [{"id": "R0"}, {"id": "R1"}, {"id": "R0"}]
    _renumber_cap_appended(tcs, [{"id": "x", "srs_id": "R0"}, {"id": "y", "srs_id": "R1"}], reqs)
    assert [t["id"] for t in tcs] == ["SwTC_R1_01", "SwTC_R0_01", "SwTC_R0_02", "SwTC_R1_02", "SwTC_R1_03"]


def test_the_disclosure_is_per_function_and_warns_on_loss():
    fd = {"F1": _fn("Only", _SWITCH)}
    _t, ref = _gen("reference", fd, {"SwTR_0001": ["F1"]}, max_tc=5)
    item = {i["key"]: i for i in build_disclosures("sts", {"generation_stats": ref})}["sts_caps_cut"]
    assert "함수 1" in item["value"] and item["tone"] != "info", item
    _t2, ext = _gen("extended", fd, {"SwTR_0001": ["F1"]}, max_tc=5)
    item2 = {i["key"]: i for i in build_disclosures("sts", {"generation_stats": ext})}["sts_caps_cut"]
    assert "버린 TC 0" in item2["value"] and "새 ID" in item2["note"]
    assert "새 ID" not in item["note"], "the reference document does not claim the extended behaviour"
    # review W1: the cap lines of the extended document say where the capped tests went (not "they are not in this document")
    d_ext = {i["key"]: i for i in build_disclosures("sts", {"generation_stats": ext})}
    d_ref = {i["key"]: i for i in build_disclosures("sts", {"generation_stats": ref})}
    assert "새 ID" in d_ext["sts_max_tc_per_req"]["note"] and "이 문서에 없다" not in d_ext["sts_max_tc_per_req"]["note"]
    assert "이 문서에 없다" in d_ref["sts_max_tc_per_req"]["note"]
    assert "sts_caps_cut" not in {i["key"] for i in build_disclosures("sts", {"generation_stats": {"max_tc_per_req": 5}})}


def test_the_gate_describes_what_the_extension_does():
    from backend.routers.docgen_preflight import _CAPS_LIFTED_BY_EXTENDED

    assert "새 ID" in _CAPS_LIFTED_BY_EXTENDED["max_tc_per_req"]
    assert "AI" in _CAPS_LIFTED_BY_EXTENDED["max_steps_per_tc"], "the AI path keeps the step cap — the gate says so"


def test_a_branch_is_matched_whatever_evidence_marks_the_document_stripped():
    # the reference block strips evidence marks from its step dicts in place — a mark must not make one branch look like
    # two (S_Fn_1's boundary TC was listed twice)
    a = {"action": "x", "expected": "1", "_evidence": "derived"}
    assert _pair_branches([[dict(a)]], [[{"action": "x", "expected": "1"}]]) == {0: 0}
    assert _cap_losses([[dict(a)]], [[[{"action": "x", "expected": "1"}]]]) == ([], 0)
