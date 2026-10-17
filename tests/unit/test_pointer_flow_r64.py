"""(R64) A write through a pointer lands on what the pointer may hold — not on every array and address-taken object.

The source oracle runs some callees as their write closure; one that writes through a pointer made every array, every
address-taken object and every escaped local unknown (`havoc_pointer_targets`) — KJPDS02_PV ``ld_send_message`` (the
LIN reply, which writes the transport queue) alone left 149,941 expected values unknown. `generators.pointer_flow`
solves where the project's pointers may point (Andersen, flow- and context-insensitive, typed: an array decays, an
integer holds no pointer) and summarizes each function: the objects its writes through a pointer may land on, and the
parameters it writes through directly (resolved with the arguments of each call). A sequence stub has no body: it can
write only through a parameter that can hold a pointer. Where the analysis cannot follow (unseen code, an unread region,
an address-taken function, a refused context) the oracle havocs as before.

The values claimed below are checked against the program compiled with gcc where the scenario runs on a host.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from generators import c_project_context as cpc
from generators import pointer_flow
from generators.c_source_oracle import evaluate_outputs

ROOT = os.path.join(os.sep, "virt_r64")
H = "typedef unsigned char U8;\ntypedef unsigned int U16;\n"
_GCC = shutil.which("gcc") or (r"C:\msys64\mingw64\bin\gcc.exe" if os.path.exists(r"C:\msys64\mingw64\bin\gcc.exe")
                               else None)


def _ctx(files):
    return cpc.build_project_context({os.path.join(ROOT, k): v for k, v in {"t.h": H, **files}.items()}, roots=[ROOT])


def _run(files, name, inputs, outs, unit="a.c"):
    path = os.path.join(ROOT, unit)
    scope = cpc.build_scopes(_ctx(files), [path])[path]
    text = files[unit]
    u = {"name": name, "source_text": cpc.apply_body_projection(scope, text), "source_path": path,
         "source_text_complete": True, "project_scope": scope}
    (r,) = evaluate_outputs(u, [inputs], [outs])
    return {o: r["outputs"].get(o, {}).get("value", r["outputs"].get(o, {}).get("reason", r.get("reason")))
            for o in outs}


def _closure(files):
    return cpc.function_write_closure(_ctx(files))


def _gcc(tmp_path, files, main_body):
    """Compile the files with a main that runs ``main_body`` and prints what it prints; None without gcc."""
    if _GCC is None:
        return None
    for k, v in {"t.h": H, **files}.items():
        (tmp_path / k).write_text(v, encoding="utf-8")
    (tmp_path / "main.c").write_text('#include <stdio.h>\n#include "t.h"\n' + main_body, encoding="utf-8")
    srcs = [str(tmp_path / k) for k in files if k.endswith(".c")] + [str(tmp_path / "main.c")]
    exe = str(tmp_path / "prog.exe")
    subprocess.run([_GCC, "-O0", "-w", "-o", exe, *srcs], check=True, capture_output=True, timeout=120)
    return subprocess.run([exe], check=True, capture_output=True, text=True, timeout=60).stdout.split()


# ── the LIN reply: the transport queue, not the caller's buffers ─────────────────────────────────

LIN = {
    "q.h": '#include "t.h"\ntypedef U8 pdu_t[8];\n'
           "typedef struct { U8 head; U8 tail; U8 status; pdu_t *tl_pdu; } queue_t;\n"
           "extern queue_t tx_q;\nextern queue_t rx_q;\nvoid send(U16 len, const U8 *const data);\n",
    "cfg.c": '#include "q.h"\npdu_t tx_data[4];\npdu_t rx_data[4];\nqueue_t tx_q = {0, 0, 0, tx_data};\n'
             "queue_t rx_q = {0, 0, 0, rx_data};\n",
    "tl.c": '#include "q.h"\n'
            "void tl_put(const U8 *data, queue_t *queue) {\n  pdu_t *qd;\n  U8 i;\n  qd = queue->tl_pdu;\n"
            "  queue->tail++;\n  if (queue->tail >= 4U) { queue->tail = 0U; }\n"
            "  for (i = 0U; i < 8U; i++) { qd[queue->tail][i] = data[i]; }\n}\n"
            "void put_raw(const U8 *data) { tl_put(data, &tx_q); }\n"
            "void recv(const U8 *data) { tl_put(data, &rx_q); }\n"
            "void send(U16 len, const U8 *const data) {\n  pdu_t pdu;\n  U8 i;\n"
            "  for (i = 0U; i < 8U; i++) { pdu[i] = (i < len) ? data[i] : 0xAAU; }\n  put_raw(pdu);\n}\n",
    "a.c": '#include "q.h"\nU8 g_resp[8];\nU8 g_state;\n'
           "U8 uds(U8 code) { g_resp[0] = 0x62U; g_resp[1] = code; send(2U, g_resp);\n"
           "  return (U8)(g_resp[1] + g_state); }\n",
}


def test_the_lin_reply_writes_the_transport_queue_only():
    closure = _closure(LIN)
    assert closure["pointer_flow_refused"] == ""
    targets = closure["functions"]["send"]["pointer_targets"]
    objects = {o for o in targets["abs"] if not o.startswith("?")}
    assert objects == {"G:tx_q", "G:tx_data", "G:rx_data", "L:send:pdu"}, targets
    # tl_put writes through its queue parameter: resolved at each call (put_raw passes &tx_q, recv &rx_q)
    assert closure["functions"]["tl_put"]["pointer_targets"]["params"] == frozenset({1})


def test_the_callers_buffer_keeps_its_value_after_the_reply(tmp_path):
    # before R64: g_resp (an array) was unknown after send() — `callee_pointer_write:send:pointer_write`
    out = _run(LIN, "uds", {"code": 0x22, "g_state": 1}, ["return", "g_resp[1]"])
    assert out == {"return": 0x23, "g_resp[1]": 0x22}
    ran = _gcc(tmp_path, LIN, "extern U8 g_state; U8 uds(U8);\nint main(void) { g_state = 1U; "
                              'printf("%u\\n", (unsigned)uds(0x22U)); return 0; }\n')
    if ran is not None:
        assert ran == ["35"]


def test_a_queue_object_written_by_the_reply_is_unknown():
    files = dict(LIN, **{"a.c": '#include "q.h"\nU8 g_resp[8];\n'
                                 "U8 uds2(void) { tx_q.status = 5U; send(1U, g_resp); return tx_q.status; }\n"})
    assert str(_run(files, "uds2", {}, ["return"])["return"]).startswith("callee_pointer_write:send")


# ── a parameter written through is resolved with the call's argument ─────────────────────────────

CLEAR = {
    "a.c": '#include "t.h"\nU8 a1[4];\nU8 a2[4];\n'
           "static void clear(U8 *buf, U8 n) { U8 i; for (i = n; i > 0U; i--) { buf[i - 1U] = 0U; } }\n"
           "static void wrap(U8 *p) { clear(p, 2U); }\n"
           "U8 f(void) { a1[0] = 1U; a2[0] = 7U; wrap(a1); return (U8)(a1[0] + a2[0]); }\n",
}


def test_a_parameter_written_through_is_the_calls_argument(tmp_path):
    closure = _closure(CLEAR)["functions"]
    assert closure["clear"]["pointer_targets"]["params"] == frozenset({0})
    assert closure["wrap"]["pointer_targets"]["params"] == frozenset({0})   # passed on: still the parameter's
    out = _run(CLEAR, "f", {}, ["a2[0]", "a1[0]"])
    assert out["a2[0]"] == 7 and str(out["a1[0]"]).startswith("callee_pointer_write:wrap")
    ran = _gcc(tmp_path, CLEAR, 'extern U8 a2[4]; U8 f(void);\nint main(void) { f(); printf("%u\\n", (unsigned)a2[0]);'
                                " return 0; }\n")
    if ran is not None:
        assert ran == ["7"]


def test_a_local_that_shadows_the_parameter_is_not_the_parameter():
    files = {"a.c": '#include "t.h"\nU8 g_other[2];\n'
                    "void s(U8 *p) { { U8 *p = g_other; p[0] = 1U; } }\nvoid use(void) { U8 b[1]; s(b); }\n"}
    t = _closure(files)["functions"]["s"]["pointer_targets"]
    assert t["params"] == frozenset() and "G:g_other" in t["abs"]


def test_a_reassigned_parameter_is_not_the_parameter():
    files = {"a.c": '#include "t.h"\nU8 g_other[2];\nvoid s(U8 *p) { p = g_other; p[0] = 1U; }\nvoid use(void) { U8 b[1]; s(b); }\n'}
    t = _closure(files)["functions"]["s"]["pointer_targets"]
    assert t["params"] == frozenset() and "G:g_other" in t["abs"]


def test_the_function_under_test_reassigning_its_parameter_passes_what_it_assigned():
    files = {"a.c": '#include "t.h"\nU8 g_arr[2];\nstatic void clr(U8 *q) { q[0] = 0U; }\n'
                    "U8 f(U8 *p) { g_arr[0] = 4U; p = g_arr; clr(p); return g_arr[0]; }\n"}
    assert not isinstance(_run(files, "f", {"p[0]": 1}, ["return"])["return"], int)


# ── what a pointer may hold comes from every assignment the project makes ────────────────────────

def test_a_pointer_another_function_stores_reaches_its_target(tmp_path):
    files = {"a.c": '#include "t.h"\nU8 g_b2[2];\nU8 g_b3[2];\nU8 *g_p;\n'
                    "void setup(void) { g_p = g_b2; }\nstatic void wr(void) { g_p[0] = 9U; }\n"
                    "U8 f(void) { g_b2[0] = 1U; g_b3[0] = 2U; wr(); return g_b3[0]; }\n"
                    "U8 h(void) { g_b2[0] = 1U; wr(); return g_b2[0]; }\n"}
    assert _run(files, "f", {}, ["return"])["return"] == 2
    assert str(_run(files, "h", {}, ["return"])["return"]).startswith("callee_pointer_write:wr")
    ran = _gcc(tmp_path, files, "void setup(void); U8 f(void); U8 h(void);\nint main(void) { setup(); "
                                'printf("%u %u\\n", (unsigned)f(), (unsigned)h()); return 0; }\n')
    if ran is not None:
        assert ran == ["2", "9"]   # g_b3 is never touched; g_b2 is, once setup() ran


def test_a_pointer_copied_by_memcpy_carries_its_target():
    files = {"a.c": '#include "t.h"\nvoid *memcpy(void *d, const void *s, unsigned n);\n'
                    "typedef struct { U8 *p; U8 n; } S;\nU8 g_buf[2];\nS g_q1 = {g_buf, 2U};\nS g_q2;\n"
                    "void init(void) { memcpy(&g_q2, &g_q1, sizeof g_q1); }\nvoid wr2(void) { g_q2.p[0] = 1U; }\n"}
    assert "G:g_buf" in _closure(files)["functions"]["wr2"]["pointer_targets"]["abs"]


def test_an_address_taken_behind_a_typedef_cast_is_followed():
    # ``(PT)&g_x`` reads as a bitwise and to the parser: the project's typedef makes it a cast (R64)
    files = {"a.c": '#include "t.h"\ntypedef U8 *PT;\nU8 g_x;\nU8 g_y;\nU8 *g_p;\n'
                    "void init(void) { g_p = (PT)&g_x; }\nstatic void w(void) { *g_p = 3U; }\n"}
    abs_ = _closure(files)["functions"]["w"]["pointer_targets"]["abs"]
    assert "G:g_x" in abs_ and "G:g_y" not in abs_


def test_a_macro_statement_that_stores_an_address_is_followed():
    files = {"a.c": '#include "t.h"\n#define SP (g_p = &g_s)\n#define SP2 SP\nU8 *g_p;\nU8 g_s;\n'
                    "void init(void) { SP2; }\nstatic void w(void) { *g_p = 7U; }\n"}
    assert "G:g_s" in _closure(files)["functions"]["w"]["pointer_targets"]["abs"]


def test_an_integer_holds_no_pointer_and_a_constant_address_is_hardware():
    # a constant converted to a pointer addresses hardware (one object for all of it) — macro constants and casts of
    # them too; any other integer converted to a pointer may be a pointer that was converted (``(U16)&g_arr[0]``) or a
    # pointer's bytes: unknown (review rounds 3 W2, 4 K-1/K-2)
    hw = {"a.c": '#include "t.h"\nU8 g_arr[2];\n#define REG_BASE 0x40U\ntypedef U8 *PU8;\n'
                 "static void hw(void) { *(volatile U8 *)0x40U = 1U; *(PU8)(REG_BASE + 1U) = 2U; }\n"
                 "U8 f(void) { g_arr[1] = 5U; hw(); return g_arr[1]; }\n"}
    assert _closure(hw)["functions"]["hw"]["pointer_targets"]["abs"] == {pointer_flow.HARDWARE}
    assert _run(hw, "f", {}, ["return"])["return"] == 5
    files = {"a.c": '#include "t.h"\nU8 g_arr[2];\nU16 g_addr;\n'
                    "void keep(void) { g_addr = (U16)&g_arr[0]; }\n"
                    "static void hw(void) { *(volatile U8 *)0x40U = 1U; *(U8 *)g_addr = 2U; }\n"
                    "U8 f(void) { g_arr[1] = 5U; hw(); return g_arr[1]; }\n"}
    assert _closure(files)["functions"]["hw"]["pointer_targets"]["abs"] is None
    assert not isinstance(_run(files, "f", {}, ["return"])["return"], int)


# ── where the analysis cannot follow, everything a pointer may reach (as before) ─────────────────

@pytest.mark.parametrize("body, cause", [
    # cb's address is handed out: called through it with anything, it keeps that in g_keep
    ("void (*g_cb)(U8 *);\nU8 *g_keep;\nstatic void cb(U8 *p) { g_keep = p; }\nvoid reg(void) { g_cb = cb; }\n"
     "static void w(void) { g_keep[0] = 1U; }\n", "indirect_call:cb"),
    ("void ext(U8 **pp);\nstatic void w(void) { U8 *p = g_one; ext(&p); p[0] = 1U; }\n", "call:ext"),
    ("static void w(void) { __asm__ volatile (\"\" : : \"r\"(g_one)); g_one[0] = 1U; }\n", "inline_assembly"),
])
def test_unseen_code_leaves_the_targets_unknown(body, cause):
    files = {"a.c": '#include "t.h"\nU8 g_one[2];\nU8 g_two[2];\n' + body
                    + "U8 f(void) { g_two[0] = 3U; w(); return g_two[0]; }\n"}
    t = _closure(files)["functions"]["w"]["pointer_targets"]
    assert t["abs"] is None and t["why"].startswith(cause), t


def test_an_unread_include_refuses_the_analysis_and_keeps_the_old_havoc():
    files = {"a.c": '#include "t.h"\n#include "gone.h"\nU8 g_arr[2];\nstatic void clr(U8 *p) { p[0] = 0U; }\n'
                    "U8 g_b[2];\nU8 f(void) { g_b[0] = 4U; clr(g_arr); return g_b[0]; }\n"}
    closure = _closure(files)
    assert closure["pointer_flow_refused"].startswith("include_not_found") and closure["pointer_flow"] is None
    assert closure["functions"]["clr"]["pointer_targets"] is None
    assert not isinstance(_run(files, "f", {}, ["return"])["return"], int)


def test_a_callee_local_target_does_not_reach_a_same_named_local_of_the_caller():
    files = {"a.c": '#include "t.h"\nstatic void h(void) { U8 buf[2]; U8 *q = buf; q[0] = 1U; buf[1] = q[0]; }\n'
                    "static U8 rd(const U8 *p) { return p[0]; }\n"
                    "U8 f(void) { U8 buf[2]; buf[0] = 6U; (void)rd(buf); h(); return buf[0]; }\n"}
    assert "L:h:buf" in _closure(files)["functions"]["h"]["pointer_targets"]["abs"]
    assert _run(files, "f", {}, ["return"])["return"] == 6


# ── a sequence stub writes only through a parameter that can hold a pointer ──────────────────────

STUBS = {"a.c": '#include "t.h"\nU8 g_buf[4];\nU8 g_v;\nU8 *g_ptr;\n'
                "U8 rd_e2p(U16 off) { *g_ptr = 1U; return (U8)off; }\n"
                "U8 rd_out(U8 *out, U16 off) { out[0] = (U8)off; return 1U; }\n"
                "U8 f(void) { g_buf[0] = 3U; g_buf[1] = rd_e2p(5U); return g_buf[0]; }\n"
                "U8 g(void) { g_buf[0] = 3U; g_v = 4U; (void)rd_out(&g_v, 2U); return g_buf[0]; }\n"
                "U8 h(void) { g_v = 4U; (void)rd_out(&g_v, 2U); return g_v; }\n"}


def test_a_stub_without_a_pointer_parameter_writes_nothing():
    # (backlog 4-a) rd_e2p's body writes through g_ptr — its stub has no body and no pointer parameter
    assert _run(STUBS, "f", {"rd_e2p() return": 9}, ["return"])["return"] == 3


def test_a_stub_writes_what_its_pointer_argument_points_to():
    assert _run(STUBS, "g", {"rd_out() return": 1}, ["return"])["return"] == 3
    assert str(_run(STUBS, "h", {"rd_out() return": 1}, ["return"])["return"]).startswith(
        "stub_pointer_argument:rd_out")


# ── the facts ────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("decl, kind", [("U8 *a[4];", "ap"), ("unsigned char (*pa)[4];", "pa"),
                                        ("U8 **pp;", "pp"), ("U8 x;", ""), ("void (*cb)(U8);", "pf")])
def test_a_declarator_reads_its_derivations_from_the_name_outward(decl, kind):
    raw = (H + decl + "\n").encode()
    root = cpc.shared_parser().parse(raw).root_node
    d = [c for c in root.named_children if c.type == "declaration"][0]
    target = d.child_by_field_name("declarator")
    assert pointer_flow.declarator_kind(target, raw)[1] == kind


def test_the_summary_says_what_the_disclosure_needs():
    summary = pointer_flow.summarize_pointer_targets(_closure(LIN))
    assert summary["refused"] == "" and summary["known_targets"] == summary["pointer_writers"] >= 4
    from report_gen.generation_disclosures import _pointer_targets_item
    (item,) = _pointer_targets_item(summary, "suts_pointer_targets")
    assert item["tone"] == "info" and "대상 특정" in item["value"]
    refused = pointer_flow.summarize_pointer_targets(_closure({"a.c": '#include "gone.h"\nvoid w(U8 *p) { p[0] = 1U; }\n'}))
    assert refused["refused"].startswith("include_not_found")
    (item,) = _pointer_targets_item(refused, "suts_pointer_targets")
    assert item["tone"] == "warning" and "분석 거절" in item["value"]


def test_the_clang_harness_puts_only_through_the_parameters_written():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from source_oracle_clang_check import _harness

    from generators.c_source_oracle import _find_function
    path = os.path.join(ROOT, "a.c")
    scope = cpc.build_scopes(_ctx(CLEAR), [path])[path]
    raw = cpc.apply_body_projection(scope, CLEAR["a.c"]).encode()
    unit = {"name": "f", "source_text": raw.decode(), "source_path": path, "source_text_complete": True,
            "project_scope": scope}
    fn = _find_function(cpc.shared_parser().parse(raw).root_node, raw, "f", scope)
    claim = {"unit": unit, "inputs": {}, "outputs": {"a2[0]": 7}}
    source, _checks, reason, _meta = _harness(unit, [claim], fn, raw)
    assert reason == "" and "1ULL >> __oracle_i++" in source   # wrap(a1): the fill only through its first argument


# ── ``(T)(x)`` is a cast, not a call through a pointer ───────────────────────────────────────────

CASTS = {"a.c": '#include "t.h"\nU8 g_arr[2];\nU8 g_y;\nU8 g_z;\nvoid (*g_fp)(U8);\n'
                "static void inc(U8 d) { g_y = (U8)(g_y + d); }\n"
                "static void via_fn(void) { (inc)(0U); }\n"
                "static void via_ptr(void) { (g_fp)(1U); }\n"
                "U8 f(void) { g_arr[0] = 2U; g_z = 3U; inc(1U); return (U8)(g_arr[0] + g_z); }\n"
                "U8 g(void) { g_z = 3U; via_fn(); return g_z; }\n"}


def test_a_cast_to_a_typedef_is_no_unknown_callee(tmp_path):
    # tree-sitter reads ``(U8)(g_y + 1U)`` as a call through ``(U8)``: the closure called it unknown code, so every
    # caller of inc() lost every global (KJPDS02_PV 174 functions, HDPDM01 38)
    closure = _closure(CASTS)["functions"]
    assert closure["inc"]["unknown_callees"] == set() and closure["inc"]["writes"] == {"g_y"}
    assert _run(CASTS, "f", {"g_y": 1}, ["return"])["return"] == 5
    ran = _gcc(tmp_path, CASTS, 'U8 f(void);\nint main(void) { printf("%u\\n", (unsigned)f()); return 0; }\n')
    if ran is not None:
        assert ran == ["5"]


def test_a_parenthesized_function_name_is_a_call_and_a_pointer_variable_is_unknown_code():
    closure = _closure(CASTS)["functions"]
    assert "inc" in closure["via_fn"]["reaches"] and "g_y" in closure["via_fn"]["writes"]
    assert closure["via_ptr"]["unknown_callees"] == {"<indirect>"}
    assert _run(CASTS, "g", {"g_y": 1}, ["return"])["return"] == 3


def test_a_cast_before_a_decision_leaves_its_globals_verified():
    from generators.mcdc_design import build_mcdc_design
    text = ('#include "t.h"\nU8 g_a;\nU8 g_b;\nU8 g_o;\nU8 g_t;\n'
            "void d(void) { g_t = (U8)(g_t + 1U); if ((g_a == 1U) && (g_b == 2U)) { g_o = 1U; } else { g_o = 2U; } }\n")
    path = os.path.join(ROOT, "a.c")
    scope = cpc.build_scopes(_ctx({"a.c": text}), [path])[path]
    unit = {"name": "d", "source_text": text, "source_path": path, "source_text_complete": True,
            "project_scope": scope, "input_vars": ["g_a", "g_b", "g_t"]}
    (decision,) = build_mcdc_design(unit)["decisions"]
    assert decision["status"] == "designed", decision["reason"]


# ── the clang harness stands in for a struct object's unmodeled member the code reads ────────────

def _harness_module():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import source_oracle_clang_check
    return source_oracle_clang_check


def test_a_member_stand_in_has_the_depth_and_extent_the_code_reads():
    stand_ins = _harness_module()._member_stand_ins
    text = "u = q.tl_pdu[q.head][3]; v = q.tl_pdu [i] [7]; w = q.max;"
    assert stand_ins("q", ["tl_pdu", "max", "other"], text) == {
        "tl_pdu": ("__oracle_pm<2> tl_pdu;", 2), "max": ("unsigned long long max;", 0)}
    # used as a whole and with a subscript, or nested: no stand-in (the unit stays unchecked)
    assert stand_ins("q", ["p", "a.b"], "x = q.p; y = q.p[1]; z = q.a.b;") == {}


def test_a_function_reading_a_struct_pointer_member_is_checked_by_clang():
    # (R64) HDPDM01 UDS handlers read the LIN request through ``lin_tl_rx_queue.tl_pdu[h][k]``: the harness declared the
    # struct with its modeled members only and did not compile (72,765 derived cells unchecked)
    chk = _harness_module()
    files = {"a.c": '#include "t.h"\ntypedef U8 pdu_t[8];\ntypedef struct { U8 h; pdu_t *p; } Q;\nQ g_q;\n'
                    "U8 g_x;\nU8 g_o;\nvoid f(void) { g_x = g_q.p[g_q.h][2]; g_o = (U8)(g_q.h + 5U); }\n"}
    path = os.path.join(ROOT, "a.c")
    scope = cpc.build_scopes(_ctx(files), [path])[path]
    assert "p" in scope["struct_globals"]["g_q"]["unmodeled_members"]
    unit = {"name": "f", "source_text": cpc.apply_body_projection(scope, files["a.c"]), "source_path": path,
            "source_text_complete": True, "project_scope": scope}
    clang = shutil.which("clang") or (r"C:\msys64\mingw64\bin\clang.exe"
                                      if os.path.exists(r"C:\msys64\mingw64\bin\clang.exe") else None)
    if clang is None:
        pytest.skip("clang not found")
    report = chk.check_claims([{"unit": unit, "inputs": {"g_q.h": 1}, "outputs": {"g_o": 6}}], clang=clang)
    assert (report["checked"], report["agree"], report["mismatch"]) == (1, 1, 0), report
    wrong = chk.check_claims([{"unit": unit, "inputs": {"g_q.h": 1}, "outputs": {"g_o": 6, "g_x": 90}}], clang=clang)
    assert wrong["mismatch"] == 1   # a claim resting on what the stand-in holds disagrees with some fill


def test_a_parenthesized_local_is_a_call_through_it_even_when_a_typedef_has_its_name():
    # another file's ``typedef U8 handler;`` does not make ``(handler)(1U)`` on a local function pointer a cast
    files = {"b.c": '#include "t.h"\ntypedef U8 handler;\n',
             "a.c": '#include "t.h"\nU8 g_v;\nvoid set(U8 v) { g_v = v; }\n'
                    "void f(void) { void (*handler)(U8) = set; (handler)(1U); }\n"}
    closure = _closure(files)["functions"]
    assert "<indirect>" in closure["f"]["unknown_callees"]
    assert closure["f"]["pointer_targets"]["abs"] is None


# ── review round 1: every claimed value is the program's (gcc) or none ───────────────────────────

def _no_wrong_value(tmp_path, files, main_body, name, inputs, out):
    """The oracle's value for ``out`` is unknown or the one the compiled program prints (``main_body`` prints it)."""
    got = _run(files, name, inputs, [out])[out]
    ran = _gcc(tmp_path, files, main_body)
    if isinstance(got, int) and ran is not None:
        assert got == int(ran[-1]), (got, ran)
    return got


_PAD = " + 0U" * 90
_REVIEW_CASES = {
    # C-2: a local a macro declares is the macro's local, not a global of that name
    "macro_local_address": ({"a.c": '#include "t.h"\nU8 *g_p; U8 g_o;\nvoid wr(void) { *g_p = 9U; }\n'
                                    "#define M do { U8 t = 1U; g_p = &t; wr(); g_o = t; } while (0)\n"
                                    "void f(void) { M; }\n"}, "void f(void); extern U8 g_o;\n", "f()"),
    "macro_local_param_direct": ({"a.c": '#include "t.h"\nU8 g_buf[2]; U8 g_o;\nvoid clr(U8 *p) { p[0] = 9U; }\n'
                                         "#define M do { U8 *q; q = g_buf; clr(q); } while (0)\n"
                                         "void f(void) { g_buf[0] = 1U; M; g_o = g_buf[0]; }\n"},
                                 "void f(void); extern U8 g_o;\n", "f()"),
    # C-1: an object-like alias called, a macro call too long to keep, a callback no project code calls
    "object_macro_alias_callee": ({"a.c": '#include "t.h"\nU8 *g_p; U8 g_x; U8 g_o;\nvoid keep_impl(U8 *p) { g_p = p; }\n'
                                          "#define KEEP keep_impl\nvoid wr(void) { *g_p = 9U; }\n"
                                          "void init(void) { KEEP(&g_x); }\nvoid f(void) { g_x = 1U; wr(); g_o = g_x; }\n"},
                                  "void init(void); void f(void); extern U8 g_o;\n", "init(); f()"),
    "long_macro_call": ({"a.c": '#include "t.h"\nU8 *g_p; U8 g_x; U8 g_o;\nvoid keep_impl(U8 *p, U8 n) { g_p = p; (void)n; }\n'
                                "#define KEEP2(a, n) keep_impl((a), (n))\nvoid wr(void) { *g_p = 9U; }\n"
                                "void init(void) { KEEP2(&g_x, 0U" + _PAD + "); }\n"
                                "void f(void) { g_x = 1U; wr(); g_o = g_x; }\n"},
                        "void init(void); void f(void); extern U8 g_o;\n", "init(); f()"),
    # (the library got &g_x from the project — ext_register — and calls the callback with it, by name)
    "callback_no_project_caller": ({"a.c": '#include "t.h"\nU8 *g_keep; U8 g_x; U8 g_o;\nvoid ext_register(U8 *p);\n'
                                           "void l_ifc_rx(U8 *p) { g_keep = p; }\nvoid wr(void) { g_keep[0] = 9U; }\n"
                                           "void init(void) { ext_register(&g_x); }\n"
                                           "void f(void) { g_x = 1U; wr(); g_o = g_x; }\n"},
                                   "void l_ifc_rx(U8 *p); void init(void); void f(void); extern U8 g_o;\n"
                                   "void ext_register(U8 *p) { l_ifc_rx(p); }\n",
                                   "init(); f()"),
    # C-3: a macro call in lvalue position designates what its expansion does
    "macro_lvalue": ({"a.c": '#include "t.h"\n#define SLOT(i) g_ptrs[i]\nU8 *g_ptrs[4]; U8 g_x; U8 g_o;\n'
                             "void init(void) { SLOT(2) = &g_x; }\nstatic void wr(void) { *g_ptrs[2] = 7U; }\n"
                             "void f(void) { g_x = 1U; wr(); g_o = g_x; }\n"},
                     "void init(void); void f(void); extern U8 g_o;\n", "init(); f()"),
    # C-4: token pasting forms the name
    "token_paste": ({"a.c": '#include "t.h"\n#define SETP(n) g_ptr_##n = g_b\nU8 *g_ptr_rx; U8 g_b[2]; U8 g_o;\n'
                            "void init(void) { SETP(rx); }\nstatic void wr(void) { g_ptr_rx[0] = 7U; }\n"
                            "void f(void) { g_b[0] = 1U; wr(); g_o = g_b[0]; }\n"},
                    "void init(void); void f(void); extern U8 g_o;\n", "init(); f()"),
    # C-6: what a void * parameter points to may hold a pointer
    "void_pointer_parameter": ({"a.c": '#include "t.h"\ntypedef struct { U8 *p; } S;\nU8 g_b[2]; U8 g_o; S g_s;\n'
                                       "static void wr(void *c) { ((S *)c)->p[0] = 7U; }\n"
                                       "void f(void) { g_s.p = g_b; g_b[0] = 1U; wr(&g_s); g_o = g_b[0]; }\n"},
                               "void f(void); extern U8 g_o;\n", "f()"),
    # C-8: a struct with a pointer member copied byte by byte
    "byte_copy": ({"a.c": '#include "t.h"\ntypedef struct { U8 *p; U8 n; } S;\nU8 g_buf[2]; U8 g_o;\n'
                          "S g_q1 = { g_buf, 2U };\nS g_q2;\n"
                          "void copy_bytes(U8 *d, const U8 *s, U16 n) { U16 i; for (i = 0U; i < n; i++) { d[i] = s[i]; } }\n"
                          "void init(void) { copy_bytes((U8 *)&g_q2, (const U8 *)&g_q1, (U16)sizeof(S)); }\n"
                          "void wr2(void) { g_q2.p[0] = 9U; }\nvoid f(void) { g_buf[0] = 1U; wr2(); g_o = g_buf[0]; }\n"},
                  "void init(void); void f(void); extern U8 g_o;\n", "init(); f()"),
    # C-7: a parenthesized function-pointer parameter named like a typedef elsewhere is a call through it
    "paren_parameter_call": ({"b.c": '#include "t.h"\ntypedef U8 handler;\nhandler g_unrelated;\n',
                              "a.c": '#include "t.h"\nU8 g_x; U8 g_o;\nstatic void bump(U8 v) { g_x = v; }\n'
                                     "static void call_it(void (*handler)(U8)) { (handler)(9U); }\n"
                                     "void f(void) { g_x = 1U; call_it(bump); g_o = g_x; }\n"},
                             "void f(void); extern U8 g_o;\n", "f()"),
    # C-5: a macro of another unit does not rename this unit's object
    "macro_of_another_unit": ({"b.c": '#include "t.h"\n#define g_val g_other\nU8 g_other;\n',
                               "a.c": '#include "t.h"\nU8 g_val; U8 *g_p; U8 g_o;\nvoid init(void) { g_p = &g_val; }\n'
                                      "static void wr(void) { *g_p = 9U; }\nvoid f(void) { g_val = 1U; wr(); g_o = g_val; }\n"},
                              "void init(void); void f(void); extern U8 g_o;\n", "init(); f()"),
}


@pytest.mark.parametrize("case", sorted(_REVIEW_CASES))
def test_review_round_1_case_claims_no_wrong_value(tmp_path, case):
    files, decls, calls = _REVIEW_CASES[case]
    main = decls + "int main(void) { " + calls + '; printf("%u\\n", (unsigned)g_o); return 0; }\n'
    got = _no_wrong_value(tmp_path, files, main, "f", {}, "g_o")
    assert not isinstance(got, int), (case, got)   # each is a write the analysis must not exclude


def test_a_name_a_body_defines_called_refuses_the_analysis():
    files = {"a.c": '#include "t.h"\nU8 *g_p; U8 g_x;\nvoid keep_impl(U8 *p) { g_p = p; }\n'
                    "void init(void) {\n#define BK keep_impl\n BK(&g_x);\n#undef BK\n}\n"}
    closure = _closure(files)
    assert closure["pointer_flow"] is None and closure["pointer_flow_refused"] == "body_macro_call:BK"


def test_a_stub_called_inside_an_effects_only_callee_may_write_through_its_argument():
    # (review R64 I-4 — HEAD did not see it either) X runs as its write closure; G, which X calls, is stubbed with an
    # out-parameter: the stub writes g_buf[0] although G's body only reads
    files = {"a.c": '#include "t.h"\nU8 g_buf[2]; U8 g_o;\nU8 G(U8 *p) { return p[0]; }\n'
                    "void X(void) { (void)G(g_buf); }\nvoid f(void) { g_buf[0] = 1U; X(); g_o = g_buf[0]; }\n"}
    assert "?SW:G" in _closure(files)["functions"]["X"]["pointer_targets"]["abs"]
    assert not isinstance(_run(files, "f", {"G() p[0]": 5, "G() return": 0}, ["g_o"])["g_o"], int)


@pytest.mark.parametrize("macro", ["#define X X\n", "#define g_cnt (g_cnt)\n", "#define A B\n#define B A\n"])
def test_a_macro_that_names_itself_is_the_name_inside_its_expansion(macro):
    # (review R64 X-1) the expansion recursed until the stack ran out and took the SUTS generation down
    files = {"a.c": '#include "t.h"\n' + macro + "U8 X; U8 g_cnt; U8 A; U8 B; U8 g_o; U8 *g_p;\n"
                    "void init(void) { g_p = &X; g_p = &g_cnt; g_p = &A; }\nvoid f(void) { g_o = 1U; }\n"}
    closure = _closure(files)
    assert closure["pointer_flow_refused"] == "" and closure["pointer_flow"] is not None
    assert _run(files, "f", {}, ["g_o"])["g_o"] == 1


def test_an_expression_too_deep_to_read_is_an_unread_region_not_a_lost_context():
    deep = "g_o = (U8)(" + " + ".join(["g_a"] * 1500) + ");"
    files = {"a.c": '#include "t.h"\nU8 g_a; U8 g_o;\nvoid f(void) { ' + deep + " }\nvoid g(void) { g_o = 2U; }\n"}
    ctx = _ctx(files)
    assert ctx["files"] and _run(files, "g", {}, ["g_o"])["g_o"] == 2


# ── review round 2: the fixes' siblings — every claimed value is the program's (gcc) or none ────

_COPY_HEAD = '#include "t.h"\ntypedef struct { U8 *p; U8 n; } S;\nU8 g_buf[2]; U8 g_o;\nS g_q1 = { g_buf, 2U };\nS g_q2;\n'
_COPY_TAIL = ("void init(void) { copy_bytes((U8 *)&g_q2, (const U8 *)&g_q1, (U16)sizeof(S)); }\n"
              "void wr2(void) { g_q2.p[0] = 9U; }\nvoid f(void) { g_buf[0] = 1U; wr2(); g_o = g_buf[0]; }\n")
_COPY_DECLS = "void init(void); void f(void); extern U8 g_o;\n"
_SLOT_TAIL = "void wr(void) { *g_slot = 9U; }\nvoid f(void) { g_x = 1U; wr(); g_o = g_x; }\n"
_REVIEW_2_CASES = {
    # C-A/C-B: the bytes of a struct holding a pointer, through any integer path — the struct written as integers
    #   through a pointer holds unknown pointers
    **{"byte_copy_" + k: ({"a.c": _COPY_HEAD + "void copy_bytes(U8 *d, const U8 *s, U16 n) { U16 i; " + body + " }\n"
                                  + _COPY_TAIL}, _COPY_DECLS, "init(); f()")
       for k, body in {
           "local": "for (i = 0U; i < n; i++) { U8 t = s[i]; d[i] = t; }",
           "mask": "for (i = 0U; i < n; i++) { d[i] = (U8)(s[i] & 0xFFU); }",
           "compound": "for (i = 0U; i < n; i++) { d[i] = 0U; d[i] |= s[i]; }",
       }.items()},
    "byte_copy_through_a_global": ({"a.c": _COPY_HEAD + "U8 g_tmp;\nvoid copy_bytes(U8 *d, const U8 *s, U16 n) { U16 i; "
                                           "for (i = 0U; i < n; i++) { g_tmp = s[i]; d[i] = g_tmp; } }\n" + _COPY_TAIL},
                                   _COPY_DECLS, "init(); f()"),
    "byte_copy_through_a_return": ({"a.c": _COPY_HEAD + "static U8 get(const U8 *s, U16 i) { return s[i]; }\n"
                                           "void copy_bytes(U8 *d, const U8 *s, U16 n) { U16 i; "
                                           "for (i = 0U; i < n; i++) { d[i] = get(s, i); } }\n" + _COPY_TAIL},
                                   _COPY_DECLS, "init(); f()"),
    # C-B: a union's integer member copied carries the pointer member
    "union_integer_member": ({"a.c": '#include "t.h"\ntypedef union { U8 *p; unsigned long long w; } UP;\n'
                                     "UP g_u1; UP g_u2; U8 g_x; U8 g_o;\n"
                                     "void init(void) { g_u1.p = &g_x; g_u2.w = g_u1.w; }\n"
                                     "void wr(void) { *g_u2.p = 9U; }\nvoid f(void) { g_x = 1U; wr(); g_o = g_x; }\n"},
                             _COPY_DECLS, "init(); f()"),
    # C-C: a store through what a body #define names, through a statement expression, through __extension__
    "store_through_a_body_macro": ({"a.c": '#include "t.h"\nU8 *g_slot; U8 **g_pp = &g_slot; U8 g_x; U8 g_o;\n'
                                           "void init(void) {\n#define BM g_pp\n  *BM = &g_x;\n#undef BM\n}\n"
                                           + _SLOT_TAIL}, _COPY_DECLS, "init(); f()"),
    "store_through_a_statement_expression": ({"a.c": '#include "t.h"\nU8 *g_slot; U8 **g_pp = &g_slot; U8 g_x; U8 g_o;\n'
                                                     "#define PP ({ g_pp; })\nvoid init(void) { *PP = &g_x; }\n"
                                                     + _SLOT_TAIL}, _COPY_DECLS, "init(); f()"),
    "store_through_extension": ({"a.c": '#include "t.h"\nU8 *g_slot; U8 **g_tab[1] = { &g_slot }; U8 **g_p; U8 g_x; '
                                        "U8 g_o;\nvoid init2(void) { g_p = __extension__ g_tab[0]; }\n"
                                        "void init(void) { *g_p = &g_x; }\n" + _SLOT_TAIL},
                                "void init2(void); " + _COPY_DECLS, "init2(); init(); f()"),
    # C-D: a macro's lvalue that is another macro's call
    "nested_lvalue_macros": ({"a.c": '#include "t.h"\nU8 *g_ptrs[4]; U8 *g_other[4]; U8 g_x; U8 g_o;\n'
                                     "#define OTHER(i) g_other[i]\n#define INNER(i) g_ptrs[i]\n#define OUTER(i) (INNER(i))\n"
                                     "U8 dummy(void) { return 0U; }\n"
                                     "void init(void) { U8 *t; (void)dummy(); t = OTHER(1); (void)t; OUTER(2) = &g_x; }\n"
                                     "void wr(void) { *g_ptrs[2] = 9U; }\nvoid f(void) { g_x = 1U; wr(); g_o = g_x; }\n"},
                             _COPY_DECLS, "init(); f()"),
    # C-E: a call too long to keep, to a macro whose expansion pastes the callee's name
    "long_call_nested_paste": ({"a.c": '#include "t.h"\nU8 *g_q; U8 g_x; U8 g_y; U8 g_o;\n'
                                       "void handler_rx(U8 *p) { g_q = p; }\n#define INNER(n, a) handler_##n(a)\n"
                                       "#define CALL(a, k) INNER(rx, a)\nvoid init(void) { handler_rx(&g_y); }\n"
                                       "void init2(void) { CALL(&g_x, 0U" + _PAD + "); }\n"
                                       "void wr(void) { *g_q = 9U; }\nvoid f(void) { g_x = 1U; wr(); g_o = g_x; }\n"},
                               "void init2(void); " + _COPY_DECLS, "init(); init2(); f()"),
    # C-F: a macro that is several arguments
    "list_macro_argument": ({"a.c": '#include "t.h"\nU8 g_tx[4]; U8 g_o;\n#define TX_BUF g_tx, 4U\n'
                                    "void Clear(U8 *p, U8 n) { U8 i; for (i = 0U; i < n; i++) { p[i] = 9U; } }\n"
                                    "void f(void) { g_tx[0] = 1U; Clear(TX_BUF); g_o = g_tx[0]; }\n"},
                            "void f(void); extern U8 g_o;\n", "f()"),
    "function_like_list_macro_argument": ({"a.c": '#include "t.h"\nU8 g_tx[4]; U8 *g_q; U8 g_o;\n'
                                                  "#define ARGS(x) x, sizeof(x)\n"
                                                  "void Keep(U8 *p, U16 n) { g_q = p; (void)n; }\n"
                                                  "void init(void) { Keep(ARGS(g_tx)); }\nvoid wr(void) { g_q[0] = 9U; }\n"
                                                  "void f(void) { g_tx[0] = 1U; wr(); g_o = g_tx[0]; }\n"},
                                          _COPY_DECLS, "init(); f()"),
    # C-G: a macro of another unit does not rename this unit's function
    "macro_of_another_unit_names_a_function": ({"b.c": '#include "t.h"\nvoid other_impl(U8 *p);\n#define cb_impl other_impl\n'
                                                       "void use_b(void) { U8 t = 0U; other_impl(&t); }\n"
                                                       "void other_impl(U8 *p) { (void)p; }\n",
                                                "a.c": '#include "t.h"\nU8 *g_q; U8 g_x; U8 g_y; U8 g_o; '
                                                       "void (*g_fp)(U8 *);\nvoid cb_impl(U8 *p) { g_q = p; }\n"
                                                       "void init(void) { g_fp = cb_impl; cb_impl(&g_y); }\n"
                                                       "void run(void) { g_fp(&g_x); }\n"
                                                       "void wr(void) { *g_q = 9U; }\n"
                                                       "void f(void) { g_x = 1U; wr(); g_o = g_x; }\n"},
                                               "void run(void); " + _COPY_DECLS, "init(); run(); f()"),
    # W-3: a parenthesized parameter a macro calls through, a typedef of its name elsewhere
    "macro_calls_through_its_parameter": ({"b.c": '#include "t.h"\ntypedef U8 handler;\nhandler g_unrelated;\n',
                                           "a.c": '#include "t.h"\nU8 g_x; U8 g_o;\n#define CALL_CB(cb, v) (cb)(v)\n'
                                                  "static void bump(U8 v) { g_x = v; }\n"
                                                  "static void call_it(void (*handler)(U8)) { CALL_CB(handler, 9U); }\n"
                                                  "void f(void) { g_x = 1U; call_it(bump); g_o = g_x; }\n"},
                                          "void f(void); extern U8 g_o;\n", "f()"),
    # W-3: the function under test calls through a parameter a typedef of the same unit names
    "parameter_hides_a_typedef": ({"a.c": '#include "t.h"\ntypedef U8 handler;\nhandler g_unrelated;\nU8 g_x; U8 g_o;\n'
                                          "void bump(U8 v) { g_x = v; }\n"
                                          "void f(void (*handler)(U8)) { g_x = 1U; (handler)(9U); g_o = g_x; }\n"},
                                  "void bump(U8 v); void f(void (*h)(U8)); extern U8 g_o;\n", "f(bump)"),
    # W-4: a macro of another unit of a function-pointer object's name
    "macro_of_another_unit_names_a_function_pointer": ({"b.c": '#include "t.h"\nvoid other(U8 *p);\n#define g_cb(x) other(x)\n'
                                                               "void use_b(void) { U8 t; g_cb(&t); }\n"
                                                               "void other(U8 *p) { (void)p; }\n",
                                                        "a.c": '#include "t.h"\nvoid (*g_cb)(U8 *); U8 g_x; U8 g_o;\n'
                                                               "static void bump(U8 *p) { *p = 9U; }\n"
                                                               "void init(void) { g_cb = bump; }\n"
                                                               "static void X(void) { g_cb(&g_x); }\n"
                                                               "void f(void) { g_x = 1U; X(); g_o = g_x; }\n"},
                                                       _COPY_DECLS, "init(); f()"),
}


@pytest.mark.parametrize("case", sorted(_REVIEW_2_CASES))
def test_review_round_2_case_claims_no_wrong_value(tmp_path, case):
    files, decls, calls = _REVIEW_2_CASES[case]
    main = decls + "int main(void) { " + calls + '; printf("%u\\n", (unsigned)g_o); return 0; }\n'
    got = _no_wrong_value(tmp_path, files, main, "f", {}, "g_o")
    assert not isinstance(got, int), (case, got)


@pytest.mark.parametrize("files, refusal", [
    ({"a.c": '#include "t.h"\nU8 g_tx[4];\n#define TX_BUF g_tx, 4U\nvoid Clear(U8 *p, U8 n) { p[0] = n; }\n'
             "void f(void) { Clear(TX_BUF); }\n"}, "macro_argument_list:TX_BUF"),
    ({"a.c": '#include "t.h"\nU8 *g_q; U8 g_x;\nvoid handler_rx(U8 *p) { g_q = p; }\n#define CALL(n, a, k) handler_##n(a)\n'
             "void init2(void) { CALL(rx, &g_x, 0U" + _PAD + "); }\n"}, "macro_call_unexpanded:CALL"),
])
def test_what_the_flow_cannot_bind_refuses_it(files, refusal):
    assert _closure(files)["pointer_flow_refused"] == refusal


def test_a_stub_reached_when_the_flow_did_not_run_may_write_through_its_argument():
    # (W-2) the analysis refused (an include not found): a callee run as effects only that reaches a function this
    #   run stubs with a pointer parameter may have it write through what it is passed
    base = '#include "t.h"\nU8 g_buf[2]; U8 g_o;\nU8 G(U8 *p) { return p[0]; }\nvoid X(void) { (void)G(g_buf); }\n' \
           "void f(void) { g_buf[0] = 1U; X(); g_o = g_buf[0]; }\n"
    files = {"a.c": base, "b.c": '#include "t.h"\n#include "missing_vendor.h"\nU8 g_unrelated;\n'}
    assert _closure(files)["pointer_flow_refused"].startswith("include_not_found")
    got = _run(files, "f", {"G() p[0]": 5, "G() return": 0}, ["g_o"])["g_o"]
    assert got == "callee_stub_write:X:G"
    assert _run(files, "f", {}, ["g_o"])["g_o"] == 1          # nothing stubbed: X runs as its closure, writes nothing


def _analysis(files):
    flow, why = pointer_flow.analyze(_ctx(files))
    assert flow is not None, why
    return flow


def test_a_struct_of_integers_holds_no_pointer_but_an_anonymous_union_member_may():
    # (W-1) an integer written into a register union or a status struct leaves nothing unknown; an unnamed member
    #   (an anonymous union) is still read for a pointer
    flow = _analysis({"a.c": '#include "t.h"\ntypedef union { U8 byte; struct { U8 a : 1; U8 b : 7; } bit; } ST;\n'
                             "typedef struct { U8 n; union { U8 *p; U16 w; }; } AN;\n"
                             "typedef struct { U8 n; U16 w; } IN;\ntypedef struct { U8 n; U8 :4; } PAD;\n"
                             "ST g_st; AN g_an; IN g_in; PAD g_pad;\n"})
    assert not flow.holds_pointer(flow.var_type("G:g_st"))
    assert not flow.holds_pointer(flow.var_type("G:g_in"))
    assert flow.holds_pointer(flow.var_type("G:g_an"))
    # an unnamed bit-field the grammar does not parse: the body is unread, its members guesses — it may hold one
    assert flow.holds_pointer(flow.var_type("G:g_pad"))


def test_a_reach_does_not_go_through_a_token_that_stands_for_nothing():
    # (W-1) what a stub of G hands out stands for an object only where the run stubs G: what is stored through it
    #   lands in the objects the real G hands out too
    flow = _analysis({"a.c": '#include "t.h"\nU8 *g_slot; U8 g_z;\nU8 **G(void) { return &g_slot; }\n'
                             "void f(void) { U8 **p = G(); *p = &g_z; }\n"})
    # (round 4 I-1) a token holds itself only: what is stored through it is in the real objects the pointer holds
    assert flow.contents("?S:G") == {"?S:G"}
    assert flow.reach({"?S:G"}) == {"?S:G"}
    assert "G:g_z" in flow.reach({"G:g_slot"}, lambda o: not o.startswith("?S:"))


# ── review round 3: legal-C variants of the fixes' rules — every claimed value is the program's (gcc) or none ──

_REVIEW_3_CASES = {
    # a body #define that stores, used as a statement
    'B1_body_macro_statement_stores': ({'a.c': '#include "t.h"\nU8 *g_slot; U8 g_x; U8 g_o;\nvoid init(void) {\n#define SETP g_slot = &g_x\n  SETP;\n#undef SETP\n}\nvoid wr(void) { *g_slot = 9U; }\nvoid f(void) { g_x = 1U; wr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long U32;\n'},
        'extern U8 g_o; void f(void); void init(void);\nint main(void){ init(); f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # an object's address handed on as an integer and converted back in a callee
    'F1a_callee': ({'a.c': '#include "t.h"\nU8 g_buf[4]; U8 g_o;\nstatic void rd(U32 dst) { ((U8 *)dst)[0] = 0xFFU; }\nvoid f(void) { g_buf[0] = 1U; rd((U32)&g_buf[0]); g_o = g_buf[0]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void);\nint main(void){ f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # an object's address kept in an integer global
    'F1c_scalar_global_int': ({'a.c': '#include "t.h"\nU8 g_x; U32 g_addr; U8 g_o;\nvoid init(void) { g_addr = (U32)&g_x; }\nstatic void wr(void) { *(U8 *)g_addr = 9U; }\nvoid f(void) { init(); g_x = 1U; wr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void);\nint main(void){ f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # a pointer kept at an address computed as an integer
    'H1b_integer_address': ({'a.c': '#include "t.h"\ntypedef struct { U8 *p; U8 n; } SH;\nSH g_backing;\nunsigned long long g_addr;\n#define SHARED ((SH *)g_addr)\nU8 g_x; U8 g_o;\nvoid init(void) { g_addr = (unsigned long long)&g_backing; SHARED->p = &g_x; }\nvoid wr(void) { *SHARED->p = 9U; }\nvoid f(void) { g_x = 1U; wr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long U32;\n'},
        'extern U8 g_o; void f(void); void init(void);\nint main(void){ init(); f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # a list macro in an array initializer
    'L1_list_macro_array_init': ({'a.c': '#include "t.h"\nU8 g_a; U8 g_b; U8 g_o;\n#define PTRS &g_a, &g_b\nU8 *g_tab[2] = { PTRS };\nvoid init(void) { }\nvoid wr(void) { *g_tab[0] = 9U; }\nvoid f(void) { g_a = 1U; wr(); g_o = g_a; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void init(void);\nint main(void){ init(); f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # a function-like list macro in a struct initializer
    'L3_fnlike_list_macro_struct_init': ({'a.c': '#include "t.h"\ntypedef struct { U8 *p; U16 n; } S;\nU8 g_tx[4]; U8 g_o;\n#define DESC(b) b, sizeof(b)\nS g_s = { DESC(g_tx) };\nvoid init(void) { }\nvoid wr(void) { g_s.p[0] = 9U; }\nvoid f(void) { g_tx[0] = 1U; wr(); g_o = g_tx[0]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void init(void);\nint main(void){ init(); f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # a macro object-like in one unit, function-like in another
    'M1_mixed_macro_store': ({'b.c': '#include "t.h"\nU8 g_other[2];\n#define SLOT(i) g_other[i]\nvoid use_b(void) { SLOT(0) = 0U; }\n', 'a.c': '#include "t.h"\nU8 *g_slots[2]; U8 g_x; U8 g_o;\n#define SLOT g_slots\nvoid init(void) { SLOT[1] = &g_x; }\nvoid wr(void) { *g_slots[1] = 9U; }\nvoid f(void) { g_x = 1U; wr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long U32;\n'},
        'extern U8 g_o; void f(void); void init(void);\nint main(void){ init(); f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # a block-scope extern function pointer named like a typedef
    'P2_block_extern_fp': ({'c.c': '#include "t.h"\ntypedef U8 handler;\nhandler g_unrelated;\n', 'a.c': '#include "t.h"\nU8 g_x; U8 g_o;\nvoid bump(U8 v) { g_x = v; }\nstatic void call_it(void) { extern void (*handler)(U8); (handler)(9U); }\nvoid f(void) { g_x = 1U; call_it(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long U32;\n'},
        'extern U8 g_o; void f(void); void (*handler)(U8); void bump(U8);\nint main(void){ handler = bump; f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # a pointer stored into integer storage (type punning)
    'Q1_pointer_in_integer_slot': ({'a.c': '#include "t.h"\nU32 g_mbox[2]; U8 g_x; U8 g_o;\nvoid init(void) { *(U8 **)&g_mbox[0] = &g_x; }\nvoid wr(void) { **(U8 **)&g_mbox[0] = 9U; }\nvoid f(void) { g_x = 1U; wr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void init(void);\nint main(void){ init(); f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # a pointer-holding struct overlaid on an integer pool
    'Q3b_pool_direct': ({'a.c': '#include "t.h"\ntypedef struct { U8 *data; U8 len; } MSG;\nstatic U32 s_pool[8];\nstatic MSG *s_msg = (MSG *)&s_pool[0];\nU8 g_rx[4]; U8 g_o;\nvoid init(void) { s_msg->data = g_rx; s_msg->len = 4U; }\nvoid wr(void) { s_msg->data[0] = 9U; }\nvoid f(void) { g_rx[0] = 1U; wr(); g_o = g_rx[0]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void init(void);\nint main(void){ init(); f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # an integer member written through a pointer of another struct type
    'S2_m_over_d': ({'a.c': '#include "t.h"\n#include <string.h>\ntypedef struct { U8 *p; U8 n; } S;\nU8 g_buf[2]; U8 g_o;\nS g_q1 = { g_buf, 2U };\nS g_q2;\ntypedef struct { U32 w; } W;\nvoid init(void) { ((W *)&g_q2)->w = ((const W *)&g_q1)->w; }\nvoid wr2(void) { g_q2.p[0] = 9U; }\nvoid f(void) { g_buf[0] = 1U; wr2(); g_o = g_buf[0]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void init(void);\nint main(void){ init(); f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # an all-integer struct stored over a pointer-holding one
    'S3_int_struct_store': ({'a.c': '#include "t.h"\n#include <string.h>\ntypedef struct { U8 *p; U8 n; } S;\nU8 g_buf[2]; U8 g_o;\nS g_q1 = { g_buf, 2U };\nS g_q2;\ntypedef struct { U32 a; U32 b; } RAW;\nRAW g_raw;\nvoid init(void) { g_raw = *(const RAW *)&g_q1; *(RAW *)&g_q2 = g_raw; }\nvoid wr2(void) { g_q2.p[0] = 9U; }\nvoid f(void) { g_buf[0] = 1U; wr2(); g_o = g_buf[0]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void init(void);\nint main(void){ init(); f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # memcpy from a byte buffer the pointer bytes were saved in
    'S4_memcpy_from_bytes': ({'a.c': '#include "t.h"\n#include <string.h>\ntypedef struct { U8 *p; U8 n; } S;\nU8 g_buf[2]; U8 g_o;\nS g_q1 = { g_buf, 2U };\nS g_q2;\nU8 g_bytes[sizeof(S)];\nvoid init(void) { U8 i; for (i = 0U; i < sizeof(S); i++) { g_bytes[i] = ((const U8 *)&g_q1)[i]; } memcpy(&g_q2, g_bytes, sizeof(S)); }\nvoid wr2(void) { g_q2.p[0] = 9U; }\nvoid f(void) { g_buf[0] = 1U; wr2(); g_o = g_buf[0]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void init(void);\nint main(void){ init(); f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # a byte copy through a pointer whose type is a macro
    'S5_macro_dest_type': ({'a.c': '#include "t.h"\n#include <string.h>\ntypedef struct { U8 *p; U8 n; } S;\nU8 g_buf[2]; U8 g_o;\nS g_q1 = { g_buf, 2U };\nS g_q2;\n#define DPTR U8 *\nvoid copy_bytes(DPTR d, const U8 *s, U16 n) { U16 i; for (i = 0U; i < n; i++) { d[i] = s[i]; } }\nvoid init(void) { copy_bytes((U8 *)&g_q2, (const U8 *)&g_q1, (U16)sizeof(S)); }\nvoid wr2(void) { g_q2.p[0] = 9U; }\nvoid f(void) { g_buf[0] = 1U; wr2(); g_o = g_buf[0]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void init(void);\nint main(void){ init(); f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # a typedef name another unit #defines as a pointer type
    'T1_typedef_vs_macro_object': ({'b.c': '#include "t.h"\ntypedef U8 T;\nT g_unrelated;\n', 'a.c': '#include "t.h"\n#define T U8 *\nT g_p; U8 g_x; U8 g_o;\nvoid init(void) { g_p = &g_x; }\nvoid wr(void) { *g_p = 9U; }\nvoid f(void) { g_x = 1U; wr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void init(void);\nint main(void){ init(); f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # a function-local typedef shadowing the file's
    'T5_local_typedef_shadow': ({'a.c': '#include "t.h"\ntypedef U32 T;\nU8 g_x; U8 *g_q; U8 g_o;\nvoid init(void) { typedef struct { U8 *p; } T; T t; t.p = &g_x; g_q = t.p; }\nvoid wr(void) { *g_q = 9U; }\nvoid f(void) { g_x = 1U; wr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void init(void);\nint main(void){ init(); f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # an integer member of a struct inside a union
    'U1_struct_in_union': ({'a.c': '#include "t.h"\ntypedef union { U8 *p; struct { U32 w; } s; } UP;\nUP g_u1; UP g_u2; U8 g_x; U8 g_o;\nvoid init(void) { g_u1.p = &g_x; g_u2.s.w = g_u1.s.w; }\nvoid wr(void) { *g_u2.p = 9U; }\nvoid f(void) { g_x = 1U; wr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void init(void);\nint main(void){ init(); f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
    # an integer member of an array of structs inside a union
    'U2_union_array_of_structs': ({'a.c': '#include "t.h"\ntypedef union { U8 *p; struct { U8 b; } h[8]; } UP;\nUP g_u1; UP g_u2; U8 g_x; U8 g_o;\nvoid init(void) { U8 i; g_u1.p = &g_x; for (i = 0U; i < 8U; i++) { g_u2.h[i].b = g_u1.h[i].b; } }\nvoid wr(void) { *g_u2.p = 9U; }\nvoid f(void) { g_x = 1U; wr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void init(void);\nint main(void){ init(); f(); printf("%u ", (unsigned)(g_o));  return 0; }\n'),
}


@pytest.mark.parametrize("case", sorted(_REVIEW_3_CASES))
def test_review_round_3_case_claims_no_wrong_value(tmp_path, case):
    files, main = _REVIEW_3_CASES[case]
    got = _no_wrong_value(tmp_path, files, main, "f", {}, "g_o")
    assert not isinstance(got, int), (case, got)


def test_a_k_and_r_definition_writes_through_what_it_is_passed():
    # (review round 3 K1) its parameters are not read: a write through one is a write through a pointer, and a stub of
    #   it may write through its argument
    files = {"a.c": '#include "t.h"\nU8 g_buf[2]; U8 g_o;\nU8 G(p) U8 *p; { p[0] = 7U; return 0U; }\n'
                    "void f(void) { g_buf[0] = 1U; (void)G(g_buf); g_o = g_buf[0]; }\n"}
    assert not isinstance(_run(files, "f", {}, ["g_o"])["g_o"], int)
    assert _run(files, "f", {"G() return": 0}, ["g_o"])["g_o"] == "stub_pointer_argument:G"


# ── review round 4: integers that were pointers, pointers kept in integer storage, paren casts — gcc or none ──

_REVIEW_4_CASES = {
    'A1_punned_int_read': ({'a.c': '#include "t.h"\nU32 g_word; U8 g_buf[4]; U8 g_o;\nvoid put(void) { *(U8 **)&g_word = g_buf; }\nstatic void clr(void) { U8 *p = (U8 *)g_word; p[0] = 0U; }\nvoid f(void) { g_buf[0] = 5U; clr(); g_o = g_buf[0]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'A2_union_int_member_read': ({'a.c': '#include "t.h"\ntypedef union { U8 *p; U32 a; } PU;\nPU g_u; U8 g_buf[4]; U8 g_o;\nvoid put(void) { g_u.p = g_buf; }\nstatic void clr(void) { U8 *p = (U8 *)g_u.a; p[0] = 0U; }\nvoid f(void) { g_buf[0] = 5U; clr(); g_o = g_buf[0]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'A3_ptrvar_arith': ({'a.c': '#include "t.h"\nU8 g_buf[4]; U8 *g_p; U8 g_o;\nvoid put(void) { g_p = g_buf; }\nstatic void clr(void) { U8 *p = (U8 *)((U32)g_p + 1U); p[0] = 0U; }\nvoid f(void) { g_buf[1] = 5U; clr(); g_o = g_buf[1]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'A4_array_plus_offset': ({'a.c': '#include "t.h"\nU8 g_buf[4]; U32 g_addr; U8 g_o;\nvoid put(void) { g_addr = (U32)(g_buf + 1); }\nstatic void clr(void) { *(U8 *)g_addr = 0U; }\nvoid f(void) { g_buf[1] = 5U; clr(); g_o = g_buf[1]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'A5_memcpy_ptr_to_int': ({'a.c': '#include "t.h"\nvoid *memcpy(void *d, const void *s, unsigned long long n);\nU8 g_buf[4]; U32 g_word; U8 *g_p; U8 g_o;\nvoid put(void) { g_p = g_buf; memcpy(&g_word, &g_p, sizeof g_p); }\nstatic void clr(void) { *(U8 *)g_word = 0U; }\nvoid f(void) { g_buf[0] = 5U; clr(); g_o = g_buf[0]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'A6_reinterpret_ptr_storage': ({'a.c': '#include "t.h"\nU8 g_buf[4]; U32 g_word; U8 *g_p; U8 g_o;\nvoid put(void) { g_p = g_buf; g_word = *(U32 *)&g_p; }\nstatic void clr(void) { *(U8 *)g_word = 0U; }\nvoid f(void) { g_buf[0] = 5U; clr(); g_o = g_buf[0]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'A7_cond_of_addresses': ({'a.c': '#include "t.h"\nU8 g_a; U8 g_b; U32 g_addr; U8 g_sel; U8 g_o;\nvoid put(void) { g_addr = (U32)(g_sel ? &g_a : &g_b); }\nstatic void clr(void) { *(U8 *)g_addr = 0U; }\nvoid f(void) { g_b = 5U; clr(); g_o = g_b; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'A8_param_ptr_arith': ({'a.c': '#include "t.h"\nU8 g_buf[4]; U8 g_o;\nvoid put(void) { }\nstatic void clr(U8 *d) { U32 a = (U32)d; *(U8 *)(a + 1U) = 0U; }\nvoid f(void) { g_buf[1] = 5U; clr(g_buf); g_o = g_buf[1]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'A9_punned_member': ({'a.c': '#include "t.h"\ntypedef struct { U32 addr; U8 len; } DESC;\nDESC g_d; U8 g_buf[4]; U8 g_o;\nvoid put(void) { *(U8 **)&g_d.addr = g_buf; }\nstatic void clr(void) { *(U8 *)g_d.addr = 0U; }\nvoid f(void) { g_buf[0] = 5U; clr(); g_o = g_buf[0]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'B1_byte_loop_into_pool': ({'a.c': '#include "t.h"\nU8 g_pool[8]; U8 g_y; U8 *g_src; U8 g_o;\nvoid put(void) { U8 i; U8 *s; g_src = &g_y; s = (U8 *)&g_src; for (i = 0U; i < 8U; i++) { g_pool[i] = s[i]; } }\nstatic void clr(void) { U8 *p = *(U8 **)&g_pool[0]; *p = 0U; }\nvoid f(void) { g_y = 5U; clr(); g_o = g_y; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'B2_memcpy_into_pool': ({'a.c': '#include "t.h"\nvoid *memcpy(void *d, const void *s, unsigned long long n);\nU8 g_pool[8]; U8 g_y; U8 *g_src; U8 g_o;\nvoid put(void) { g_src = &g_y; memcpy(g_pool, &g_src, sizeof g_src); }\nstatic void clr(void) { U8 *p = *(U8 **)g_pool; *p = 0U; }\nvoid f(void) { g_y = 5U; clr(); g_o = g_y; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'B3_forced_pool_then_bytes': ({'a.c': '#include "t.h"\nU8 g_pool[8]; U8 g_x; U8 g_y; U8 *g_src; U8 g_o;\nvoid put(void) { U8 i; U8 *s; *(U8 **)&g_pool[0] = &g_x; g_src = &g_y; s = (U8 *)&g_src; for (i = 0U; i < 8U; i++) { g_pool[i] = s[i]; } }\nstatic void clr(void) { U8 *p = *(U8 **)&g_pool[0]; *p = 0U; }\nvoid f(void) { g_y = 5U; clr(); g_o = g_y; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'B4_word_loop_mailbox': ({'a.c': '#include "t.h"\ntypedef struct { U8 *p; } MSG;\nU32 g_box[2]; MSG g_m; U8 g_y; U8 g_o;\nvoid put(void) { U8 i; U32 *s; g_m.p = &g_y; s = (U32 *)&g_m; for (i = 0U; i < 1U; i++) { g_box[i] = s[i]; } }\nstatic void clr(void) { MSG *m = (MSG *)&g_box[0]; *m->p = 0U; }\nvoid f(void) { g_y = 5U; clr(); g_o = g_y; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'C1_paren_cast_addr': ({'a.c': '#include "t.h"\nU8 g_x; U32 g_addr; U8 g_o;\nvoid put(void) { g_addr = (U32)(&g_x); }\nstatic void clr(void) { *(U8 *)g_addr = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'C2_plain_cast_addr': ({'a.c': '#include "t.h"\nU8 g_x; U32 g_addr; U8 g_o;\nvoid put(void) { g_addr = (U32)&g_x; }\nstatic void clr(void) { *(U8 *)g_addr = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'C3_paren_cast_ptr_typedef': ({'a.c': '#include "t.h"\ntypedef U8 *PU8;\nU8 g_x; U32 g_addr; U8 g_o;\nvoid put(void) { g_addr = (U32)&g_x; }\nstatic void clr(void) { PU8 p = (PU8)(g_addr); *p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'C4_paren_cast_int_param': ({'a.c': '#include "t.h"\nU8 g_x; U8 g_o;\nvoid put(void) { }\nstatic void clr(U32 a) { *(U8 *)a = 0U; }\nvoid f(void) { g_x = 5U; clr((U32)(&g_x)); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'C5_typedef_ptr_cast': ({'a.c': '#include "t.h"\ntypedef U8 *PU8;\nU8 g_x; U32 g_addr; U8 g_o;\nvoid put(void) { g_addr = (U32)&g_x; }\nstatic void clr(void) { PU8 p = (PU8)g_addr; *p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
    'C6_macro_typedef_ptr_cast': ({'a.c': '#include "t.h"\ntypedef U8 *PU8;\n#define PBYTE PU8\nU8 g_x; U32 g_addr; U8 g_o;\nvoid put(void) { g_addr = (U32)&g_x; }\nstatic void clr(void) { PBYTE p = (PBYTE)g_addr; *p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n'),
}


@pytest.mark.parametrize("case", sorted(_REVIEW_4_CASES))
def test_review_round_4_case_claims_no_wrong_value(tmp_path, case):
    files, main = _REVIEW_4_CASES[case]
    got = _no_wrong_value(tmp_path, files, main, "f", {}, "g_o")
    assert not isinstance(got, int), (case, got)


# ── review round 5: pointers stored through integer-made pointers, call values in macros, implicit conversions ──

_REVIEW_5_CASES = {
    'A2_macro_paren_cast_ptrvar': ({'a.c': '#include "t.h"\nU8 g_x; U8 *g_p; U8 g_o;\n#define ADDR ((U32)(g_p))\nvoid put(void) { g_p = &g_x; }\nstatic void clr(void) { *(U8 *)ADDR = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, True),
    'A4_macro_int_call': ({'a.c': '#include "t.h"\nU8 g_x; U8 g_o;\nU32 get_addr(void) { return (unsigned long long)&g_x; }\n#define ADDR get_addr()\nvoid put(void) { }\nstatic void clr(void) { *(U8 *)ADDR = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, True),
    'A5_fnmacro_int_call': ({'a.c': '#include "t.h"\nU8 g_x; U8 g_o;\nU32 get_addr(U8 i) { return (unsigned long long)&g_x + i; }\n#define ADDR(i) get_addr(i)\nvoid put(void) { }\nstatic void clr(void) { *(U8 *)ADDR(0U) = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, True),
    'B1_store_through_int_ptr': ({'a.c': '#include "t.h"\nU8 *g_slot; U8 g_x; U8 g_y; U32 g_addr; U8 g_o;\nvoid put(void) { g_slot = &g_y; g_addr = (U32)&g_slot; *(U8 **)g_addr = &g_x; }\nstatic void clr(void) { *g_slot = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, True),
    'B3_store_through_int_param': ({'a.c': '#include "t.h"\nU8 *g_slot; U8 g_x; U8 g_y; U8 g_o;\nstatic void setp(U32 a, U8 *v) { *(U8 **)a = v; }\nvoid put(void) { g_slot = &g_y; setp((U32)&g_slot, &g_x); }\nstatic void clr(void) { *g_slot = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, True),
    'B4_store_through_byte_copied_ptr': ({'a.c': '#include "t.h"\nU8 *g_slot; U8 g_x; U8 g_y; U8 **g_pp; U8 **g_qq; U8 g_o;\nvoid put(void) { U8 i; U8 *d = (U8 *)&g_qq; const U8 *s = (const U8 *)&g_pp; g_slot = &g_y; g_pp = &g_slot; for (i = 0U; i < sizeof g_pp; i++) { d[i] = s[i]; } *g_qq = &g_x; }\nstatic void clr(void) { *g_slot = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, True),
    'B5_store_through_reinterpreted_int': ({'a.c': '#include "t.h"\nU8 *g_slot; U8 g_x; U8 g_y; U32 g_word; U8 g_o;\nvoid put(void) { U8 **pp; g_slot = &g_y; g_word = (unsigned long long)&g_slot; pp = *(U8 ***)&g_word; *pp = &g_x; }\nstatic void clr(void) { *g_slot = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, True),
    'C1b_implicit_store': ({'a.c': '#include "t.h"\nU8 g_x; U32 g_addr; U8 g_o;\nvoid put(void) { g_addr = (unsigned long long)&g_x; }\nstatic void clr(void) { U8 *p = g_addr; *p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'C2b_implicit_arg': ({'a.c': '#include "t.h"\nU8 g_x; U32 g_addr; U8 g_o;\nvoid put(void) { g_addr = (unsigned long long)&g_x; }\nstatic void clr(U8 *p) { *p = 0U; }\nvoid f(void) { g_x = 5U; clr(g_addr); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'C3b_implicit_return': ({'a.c': '#include "t.h"\nU8 g_x; U32 g_addr; U8 g_o;\nvoid put(void) { g_addr = (unsigned long long)&g_x; }\nstatic U8 *getp(void) { return g_addr; }\nstatic void clr(void) { *getp() = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'C4b_implicit_both': ({'a.c': '#include "t.h"\nU8 g_x; U32 g_addr; U8 g_o; U8 *g_keep;\nvoid put(void) { g_keep = &g_x; g_addr = g_keep; }\nstatic void clr(void) { U8 *p = g_addr; *p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'E1_question_reinterpreted_arg': ({'a.c': '#include "t.h"\nU8 g_x; U32 g_word; U8 g_o;\nvoid put(void) { g_word = (unsigned long long)&g_x; }\nstatic void clr(U8 *p) { *p = 0U; }\nvoid f(void) { g_x = 5U; clr(*(U8 **)&g_word); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, True),
    'E3_stub_reinterpreted_arg': ({'a.c': '#include "t.h"\nU8 g_x; U32 g_word; U8 g_o;\nvoid put(void) { g_word = (unsigned long long)&g_x; }\nU8 G(U8 *p) { p[0] = 0U; return 0U; }\nvoid f(void) { g_x = 5U; (void)G(*(U8 **)&g_word); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {'G() return': 0, 'G() p[0]': 7}, True),
    'G1_enum_vs_macro': ({'b.c': '#include "t.h"\nenum { SLOT_ADDR = 3 };\nU8 g_other_unit = SLOT_ADDR;\n', 'a.c': '#include "t.h"\nU8 g_x; U32 g_addr; U8 g_o;\n#define SLOT_ADDR (g_addr)\nvoid put(void) { g_addr = (unsigned long long)&g_x; }\nstatic void clr(void) { *(U8 *)SLOT_ADDR = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, True),
    'H1_pointer_in_hardware_as_int': ({'a.c': '#include "t.h"\n#define SHM_ADDR 0x30000000ULL\nU8 g_x; U8 g_o;\nvoid put(void) { *(volatile U32 *)SHM_ADDR = (unsigned long long)&g_x; }\nstatic void clr(void) { U8 *p = *(U8 *volatile *)SHM_ADDR; *p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        '#include <windows.h>\nextern U8 g_o; void f(void); void put(void);\nint main(void){ if (!VirtualAlloc((LPVOID)0x30000000ULL, 4096, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE)) { printf("noalloc"); return 1; } put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'H3_pointer_in_hardware_bytes': ({'a.c': '#include "t.h"\n#define SHM ((volatile U8 *)0x30000000ULL)\nU8 g_x; U8 *g_p; U8 g_o;\nvoid put(void) { U8 i; const U8 *s = (const U8 *)&g_p; g_p = &g_x; for (i = 0U; i < sizeof g_p; i++) { SHM[i] = s[i]; } }\nstatic void clr(void) { U8 *p = *(U8 *volatile *)SHM; *p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        '#include <windows.h>\nextern U8 g_o; void f(void); void put(void);\nint main(void){ if (!VirtualAlloc((LPVOID)0x30000000ULL, 4096, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE)) { printf("noalloc"); return 1; } put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'T5_macro_typed_int_ptr_store_into_words': ({'a.c': '#include "t.h"\n#define ADDR_T unsigned long long\nU32 g_words[1]; ADDR_T g_addr; U8 g_o;\nvoid put(void) { g_addr = (U32)&g_words[0] + 0U; }\nstatic void clr(void) { *(U8 **)g_addr = 0; }\nvoid f(void) { g_words[0] = 5U; clr(); g_o = (U8)g_words[0]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'T6_macro_typed_param_ptr_store': ({'a.c': '#include "t.h"\n#define ADDR_T unsigned long long\nU32 g_words[1]; U8 g_o;\nvoid put(void) { }\nstatic void clr(ADDR_T a) { *(U8 **)a = 0; }\nvoid f(void) { g_words[0] = 5U; clr((U32)&g_words[0] + 0U); g_o = (U8)g_words[0]; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
}


@pytest.mark.parametrize("case", sorted(_REVIEW_5_CASES))
def test_review_round_5_case_claims_no_wrong_value(tmp_path, case):
    # (non-portable programs — implicit int/pointer conversions, fixed-address memory — are checked for no claim only)
    files, main, inputs, portable = _REVIEW_5_CASES[case]
    if portable:
        got = _no_wrong_value(tmp_path, files, main, "f", inputs, "g_o")
    else:
        got = _run(files, "f", inputs, ["g_o"])["g_o"]
    assert not isinstance(got, int), (case, got)


# ── review round 6: unions, second-level stores, pointers kept as integers, body #define names ──

_REVIEW_6_CASES = {
    'A1_anon_union_read': ({'a.c': '#include "t.h"\ntypedef struct { union { U8 **pp; U32 w; }; U8 n; } S;\nS g_s; U8 *g_slot; U8 g_x; U8 g_y; U8 g_o;\nvoid put(void) { U32 a; g_slot = &g_y; g_s.pp = &g_slot; a = g_s.w; *(U8 **)a = &g_x; }\nstatic void clr(void) { *g_slot = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'A2_anon_union_write': ({'a.c': '#include "t.h"\ntypedef struct { union { U8 *p; U32 w; }; U8 n; } S;\nS g_s; U8 g_x; U8 g_y; U8 g_o;\nvoid put(void) { g_s.p = &g_y; g_s.w = (unsigned long long)&g_x; }\nstatic void clr(void) { *g_s.p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'A3_anon_union_write_through': ({'a.c': '#include "t.h"\ntypedef struct { union { U8 *p; U32 w; }; U8 n; } S;\nS g_s; U8 g_x; U8 g_y; U8 g_o;\nstatic void poke(S *ps, U32 v) { ps->w = v; }\nvoid put(void) { g_s.p = &g_y; poke(&g_s, (unsigned long long)&g_x); }\nstatic void clr(void) { *g_s.p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'D1_direct_int_into_forced': ({'a.c': '#include "t.h"\nU32 g_word; U8 g_x; U8 g_y; U8 g_o;\nvoid put(void) { *(U8 **)&g_word = &g_y; g_word = (U32)&g_x; }\nstatic void clr(void) { **(U8 **)&g_word = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'D1u_direct_int_into_forced': ({'a.c': '#include "t.h"\nU32 g_word; U8 g_x; U8 g_y; U8 g_o;\nvoid put(void) { *(U8 **)&g_word = &g_y; g_word = (unsigned long long)&g_x; }\nstatic void clr(void) { **(U8 **)&g_word = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'D2_direct_int_into_forced_member': ({'a.c': '#include "t.h"\ntypedef struct { U32 addr; U8 len; } DESC;\nDESC g_d; U8 g_x; U8 g_y; U8 g_o;\nvoid put(void) { *(U8 **)&g_d.addr = &g_y; g_d.addr = (U32)&g_x; }\nstatic void clr(void) { U8 *p = *(U8 **)&g_d.addr; *p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'D3_forced_arg_question': ({'a.c': '#include "t.h"\nU32 g_word; U8 g_x; U8 g_y; U8 g_o;\nvoid put(void) { *(U8 **)&g_word = &g_y; g_word = (unsigned long long)&g_x; }\nstatic void clr(U8 *p) { *p = 0U; }\nvoid f(void) { g_x = 5U; clr(*(U8 **)&g_word); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'D4_forced_stub_arg': ({'a.c': '#include "t.h"\nU32 g_word; U8 g_x; U8 g_y; U8 g_o;\nvoid put(void) { *(U8 **)&g_word = &g_y; g_word = (unsigned long long)&g_x; }\nU8 G(U8 *p) { p[0] = 0U; return 0U; }\nvoid f(void) { g_x = 5U; (void)G(*(U8 **)&g_word); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {'G() return': 0, 'G() p[0]': 0}, False),
    'D5_pool_word_question': ({'a.c': '#include "t.h"\nvoid *memcpy(void *d, const void *s, unsigned long long n);\nU32 g_pool[2]; U8 *g_src; U8 g_x; U8 g_y; U8 g_o;\nvoid put(void) { g_src = &g_y; memcpy(g_pool, &g_src, sizeof g_src); g_pool[0] = (unsigned long long)&g_x; }\nstatic void clr(U8 *p) { *p = 0U; }\nvoid f(void) { g_x = 5U; clr(*(U8 **)&g_pool[0]); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'G2_enum_vs_body_macro': ({'b.c': '#include "t.h"\nenum { SLOT_ADDR = 3 };\nU8 g_other_unit = SLOT_ADDR;\n', 'a.c': '#include "t.h"\nU8 g_x; U32 g_addr; U8 g_o;\nvoid put(void) { g_addr = (U32)&g_x; }\nstatic void clr(void) {\n#define SLOT_ADDR (g_addr)\n  *(U8 *)SLOT_ADDR = 0U;\n#undef SLOT_ADDR\n}\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'G2bu_enum_vs_body_macro_same_unit': ({'a.c': '#include "t.h"\nenum { SLOT_ADDR = 3 };\nU8 g_x; U32 g_addr; U8 g_o;\nU8 g_other_unit = SLOT_ADDR;\nvoid put(void) { g_addr = (unsigned long long)&g_x; }\nstatic void clr(void) {\n#undef SLOT_ADDR\n#define SLOT_ADDR (g_addr)\n  *(U8 *)SLOT_ADDR = 0U;\n#undef SLOT_ADDR\n}\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'G2u_enum_vs_body_macro': ({'b.c': '#include "t.h"\nenum { SLOT_ADDR = 3 };\nU8 g_other_unit = SLOT_ADDR;\n', 'a.c': '#include "t.h"\nU8 g_x; U32 g_addr; U8 g_o;\nvoid put(void) { g_addr = (unsigned long long)&g_x; }\nstatic void clr(void) {\n#define SLOT_ADDR (g_addr)\n  *(U8 *)SLOT_ADDR = 0U;\n#undef SLOT_ADDR\n}\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'K1_unknown_code_second_level': ({'a.c': '#include "t.h"\nvoid ext_keep(void *p); U32 ext_get(void);\nU8 *g_slot; U8 **g_pp; U8 g_x; U8 g_y; U8 g_o;\nvoid put(void) { g_slot = &g_y; g_pp = &g_slot; ext_keep(&g_pp); **(U8 ***)ext_get() = &g_x; }\nstatic void clr(void) { *g_slot = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nstatic unsigned long long s_kept;\nvoid ext_keep(void *p) { s_kept = (unsigned long long)p; }\nunsigned long long ext_get(void) { return s_kept; }\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'L2_second_level': ({'a.c': '#include "t.h"\nU8 *g_slot; U8 **g_pp; U8 g_x; U8 g_y; U32 g_addr; U8 g_o;\nvoid put(void) { g_slot = &g_y; g_pp = &g_slot; g_addr = (U32)&g_pp; **(U8 ***)g_addr = &g_x; }\nstatic void clr(void) { *g_slot = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'L2b_second_level_local': ({'a.c': '#include "t.h"\nU8 *g_slot; U8 **g_pp; U8 g_x; U8 g_y; U8 g_o;\nvoid put(void) { U32 a; U8 **q; g_slot = &g_y; g_pp = &g_slot; a = (U32)&g_pp; q = *(U8 ***)a; *q = &g_x; }\nstatic void clr(void) { *g_slot = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'L2c_second_level_struct': ({'a.c': '#include "t.h"\ntypedef struct { U8 *p; } IN;\ntypedef struct { IN *in; } OUT;\nIN g_in; OUT g_out; U8 g_x; U8 g_y; U8 g_o;\nvoid put(void) { U32 a; g_in.p = &g_y; g_out.in = &g_in; a = (U32)&g_out; ((OUT *)a)->in->p = &g_x; }\nstatic void clr(void) { *g_in.p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'L2d_second_level_memcpy': ({'a.c': '#include "t.h"\nvoid *memcpy(void *d, const void *s, unsigned long long n);\nU8 *g_slot; U8 **g_pp; U8 ***g_ppp; U32 g_word; U8 g_x; U8 g_y; U8 g_o;\nvoid put(void) { g_slot = &g_y; g_pp = &g_slot; g_ppp = &g_pp; memcpy(&g_word, &g_ppp, sizeof g_ppp); **(U8 ***)g_word = &g_x; }\nstatic void clr(void) { *g_slot = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'P1_implicit_ptr_to_int_store': ({'a.c': '#include "t.h"\nU8 *g_slot; U8 g_x; U8 g_y; U32 g_addr; U8 g_o;\nvoid put(void) { g_slot = &g_y; g_addr = &g_slot; *(U8 **)g_addr = &g_x; }\nstatic void clr(void) { *g_slot = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'P2_implicit_ptr_to_int_arg': ({'a.c': '#include "t.h"\nU8 *g_slot; U8 g_x; U8 g_y; U8 g_o;\nstatic void setp(U32 a, U8 *v) { *(U8 **)a = v; }\nvoid put(void) { g_slot = &g_y; setp(&g_slot, &g_x); }\nstatic void clr(void) { *g_slot = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'P3_implicit_ptr_to_int_return': ({'a.c': '#include "t.h"\nU8 *g_slot; U8 g_x; U8 g_y; U8 g_o;\nstatic U32 slot_addr(void) { return &g_slot; }\nvoid put(void) { g_slot = &g_y; *(U8 **)slot_addr() = &g_x; }\nstatic void clr(void) { *g_slot = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'P4_implicit_ptr_to_int_init': ({'a.c': '#include "t.h"\nU8 *g_slot; U8 g_x; U8 g_y; U8 g_o;\nvoid put(void) { U32 a = &g_slot; g_slot = &g_y; *(U8 **)a = &g_x; }\nstatic void clr(void) { *g_slot = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'R1_union_member_ptr_read': ({'a.c': '#include "t.h"\ntypedef struct { U32 w; } WS;\ntypedef union { U8 **pp; WS s; } PU;\nPU g_u; U8 *g_slot; U8 g_x; U8 g_y; U8 g_o;\nvoid put(void) { WS *ps = &g_u.s; U32 a; g_slot = &g_y; g_u.pp = &g_slot; a = ps->w; *(U8 **)a = &g_x; }\nstatic void clr(void) { *g_slot = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'R1b_union_member_ptr_read_param': ({'a.c': '#include "t.h"\ntypedef struct { U32 w; } WS;\ntypedef union { U8 **pp; WS s; } PU;\nPU g_u; U8 *g_slot; U8 g_x; U8 g_y; U8 g_o;\nstatic U32 word_of(const WS *ps) { return ps->w; }\nvoid put(void) { g_slot = &g_y; g_u.pp = &g_slot; *(U8 **)word_of(&g_u.s) = &g_x; }\nstatic void clr(void) { *g_slot = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'U1_macro_typed_ptr_implicit': ({'a.c': '#include "t.h"\n#define PTR_T U8 *\nPTR_T g_p; U8 g_x; U32 g_addr; U8 g_o;\nvoid put(void) { g_addr = (U32)&g_x; g_p = g_addr; }\nstatic void clr(void) { *g_p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'U2_init_list_implicit': ({'a.c': '#include "t.h"\ntypedef struct { U8 *p; U8 n; } S;\nS g_s; U8 g_x; U32 g_addr; U8 g_o;\nvoid put(void) { g_addr = (U32)&g_x; { S s = { g_addr, 1U }; g_s = s; } }\nstatic void clr(void) { *g_s.p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'U2bu_array_init_implicit': ({'a.c': '#include "t.h"\nU8 *g_tab[2]; U8 g_x; U32 g_addr; U8 g_o;\nvoid put(void) { g_addr = (unsigned long long)&g_x; { U8 *t[2] = { g_addr, 0 }; g_tab[0] = t[0]; } }\nstatic void clr(void) { *g_tab[0] = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'U2u_init_list_implicit': ({'a.c': '#include "t.h"\ntypedef struct { U8 *p; U8 n; } S;\nS g_s; U8 g_x; U32 g_addr; U8 g_o;\nvoid put(void) { g_addr = (unsigned long long)&g_x; { S s = { g_addr, 1U }; g_s = s; } }\nstatic void clr(void) { *g_s.p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'V1_unknown_typed_int_to_ptr_param': ({'a.c': '#include "t.h"\n#define ADDR_T unsigned long long\nU8 g_x; ADDR_T g_addr; U8 g_o;\nvoid put(void) { g_addr = (unsigned long long)&g_x; }\nstatic void clr(U8 *p) { *p = 0U; }\nvoid f(void) { g_x = 5U; clr(g_addr); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'V2_unknown_typed_int_to_ptr_store': ({'a.c': '#include "t.h"\n#define ADDR_T unsigned long long\nU8 g_x; ADDR_T g_addr; U8 g_o;\nvoid put(void) { g_addr = (unsigned long long)&g_x; }\nstatic void clr(void) { U8 *p = g_addr; *p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'V3_unknown_typed_int_to_ptr_return': ({'a.c': '#include "t.h"\n#define ADDR_T unsigned long long\nU8 g_x; ADDR_T g_addr; U8 g_o;\nvoid put(void) { g_addr = (unsigned long long)&g_x; }\nstatic U8 *getp(void) { return g_addr; }\nstatic void clr(void) { *getp() = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'W1_union_member_ptr_write': ({'a.c': '#include "t.h"\ntypedef struct { U32 w; } WS;\ntypedef union { U8 *p; WS s; } PU;\nPU g_u; U8 g_x; U8 g_y; U8 g_o;\nstatic void poke(WS *ps, U32 v) { ps->w = v; }\nvoid put(void) { g_u.p = &g_y; poke(&g_u.s, (U32)&g_x); }\nstatic void clr(void) { *g_u.p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'W1b_union_member_ptr_write_local': ({'a.c': '#include "t.h"\ntypedef struct { U32 w; } WS;\ntypedef union { U8 *p; WS s; } PU;\nPU g_u; U8 g_x; U8 g_y; U32 g_addr; U8 g_o;\nvoid put(void) { WS *ps = &g_u.s; g_u.p = &g_y; g_addr = (U32)&g_x; ps->w = g_addr; }\nstatic void clr(void) { *g_u.p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'W1bu_union_member_ptr_write_local': ({'a.c': '#include "t.h"\ntypedef struct { U32 w; } WS;\ntypedef union { U8 *p; WS s; } PU;\nPU g_u; U8 g_x; U8 g_y; U32 g_addr; U8 g_o;\nvoid put(void) { WS *ps = &g_u.s; g_u.p = &g_y; g_addr = (unsigned long long)&g_x; ps->w = g_addr; }\nstatic void clr(void) { *g_u.p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'W1c_union_array_member_ptr_write': ({'a.c': '#include "t.h"\ntypedef struct { U32 w; } WS;\ntypedef union { U8 *p[2]; WS s[2]; } PU;\nPU g_u; U8 g_x; U8 g_y; U8 g_o;\nstatic void poke(WS *ps, U32 v) { ps->w = v; }\nvoid put(void) { g_u.p[0] = &g_y; poke(&g_u.s[0], (U32)&g_x); }\nstatic void clr(void) { *g_u.p[0] = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'W1du_union_member_ptr_copy': ({'a.c': '#include "t.h"\ntypedef struct { U32 w; } WS;\ntypedef union { U8 *p; WS s; } PU;\nPU g_u; PU g_v; U8 g_x; U8 g_y; U8 g_o;\nstatic void cp(WS *d, const WS *s) { d->w = s->w; }\nvoid put(void) { g_u.p = &g_y; g_v.p = &g_x; cp(&g_u.s, &g_v.s); }\nstatic void clr(void) { *g_u.p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'W1eu_union_member_struct_assign': ({'a.c': '#include "t.h"\ntypedef struct { U32 w; } WS;\ntypedef union { U8 *p; WS s; } PU;\nPU g_u; U8 g_x; U8 g_y; U8 g_o;\nstatic void set(WS *d, WS v) { *d = v; }\nvoid put(void) { WS v; v.w = (unsigned long long)&g_x; g_u.p = &g_y; set(&g_u.s, v); }\nstatic void clr(void) { *g_u.p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'W1u_union_member_ptr_write': ({'a.c': '#include "t.h"\ntypedef struct { U32 w; } WS;\ntypedef union { U8 *p; WS s; } PU;\nPU g_u; U8 g_x; U8 g_y; U8 g_o;\nstatic void poke(WS *ps, U32 v) { ps->w = v; }\nvoid put(void) { g_u.p = &g_y; poke(&g_u.s, (unsigned long long)&g_x); }\nstatic void clr(void) { *g_u.p = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'X1_stub_body_macro_enum': ({'b.c': '#include "t.h"\nenum { SLOT_ADDR = 3 };\nU8 g_other_unit = SLOT_ADDR;\n', 'a.c': '#include "t.h"\nU8 g_x; U32 g_addr; U8 g_o;\nvoid put(void) { g_addr = (unsigned long long)&g_x; }\nU8 G(U8 *p) { p[0] = 0U; return 0U; }\nvoid f(void) {\n#define SLOT_ADDR (g_addr)\n  g_x = 5U; (void)G((U8 *)SLOT_ADDR); g_o = g_x;\n#undef SLOT_ADDR\n}\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {'G() return': 0, 'G() p[0]': 7}, False),
    'Y1_body_macro_typedef_call': ({'b.c': '#include "t.h"\ntypedef U8 T;\nT g_unrelated;\n', 'a.c': '#include "t.h"\nU8 *g_slot; U8 g_x; U8 g_y; U8 g_o;\nvoid keep(U8 *p) { g_slot = p; }\nvoid other(void) { keep(&g_y); }\nvoid put(void) {\n#define T keep\n  (T)(&g_x);\n#undef T\n}\nstatic void clr(void) { *g_slot = 0U; }\nvoid f(void) { g_x = 5U; clr(); g_o = g_x; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void); void put(void);\nint main(void){ put(); f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'Y2_body_macro_typedef_call_closure': ({'b.c': '#include "t.h"\ntypedef U8 T;\nT g_unrelated;\n', 'a.c': '#include "t.h"\nU8 g_cnt; U8 g_o;\nvoid bump(U8 v) { g_cnt = v; }\nstatic void step(void) {\n#define T bump\n  (T)(9U);\n#undef T\n}\nvoid f(void) { g_cnt = 5U; step(); g_o = g_cnt; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void);\nint main(void){ f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
    'Y3_same_unit_typedef_redefined': ({'a.c': '#include "t.h"\ntypedef U8 T;\nU8 g_cnt; U8 g_o;\nvoid bump(U8 v) { g_cnt = v; }\nstatic void step(void) {\n#define T bump\n  (T)(9U);\n#undef T\n}\nvoid f(void) { g_cnt = 5U; step(); g_o = g_cnt; }\n', 't.h': 'typedef unsigned char U8;\ntypedef unsigned int U16;\ntypedef unsigned long long U32;\n'},
        'extern U8 g_o; void f(void);\nint main(void){ f(); printf("%u", (unsigned)g_o); return 0; }\n', {}, False),
}


@pytest.mark.parametrize("case", sorted(_REVIEW_6_CASES))
def test_review_round_6_case_claims_no_wrong_value(tmp_path, case):
    # (non-portable programs — implicit int/pointer conversions, fixed-address memory — are checked for no claim only)
    files, main, inputs, portable = _REVIEW_6_CASES[case]
    if portable:
        got = _no_wrong_value(tmp_path, files, main, "f", inputs, "g_o")
    else:
        got = _run(files, "f", inputs, ["g_o"])["g_o"]
    assert not isinstance(got, int), (case, got)
