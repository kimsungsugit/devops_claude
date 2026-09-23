"""Independent check of source-oracle expected values with a real C front end (clang, 16-bit-int target).

`generators/c_source_oracle.py` interprets function text in Python. This script asks clang instead: every
checked function body is compiled **verbatim** inside a C++20 ``constexpr`` harness for ``--target=msp430``
(char 8 · short 16 · int 16 · long 32 — the widths HDPDM01's typedefs testify), and each claimed output value
becomes a ``static_assert``. Constant evaluation runs the body with the target's integer semantics and
rejects undefined behaviour (signed overflow, division by zero, out-of-bounds indexing) as a hard error.

Independence and its limits:

* the body, macro texts (object- and function-like) and typedef base types are the source's own; what the
  harness adds is only the *inputs*: sequence values, and for everything the claim says it does not depend
  on — globals the sequence leaves unset, callee return values — three different fill values. A claim holds
  only if all three runs give the claimed value, so an output that secretly depends on an unset global or a
  call result is caught;
* callees are stubs that return the fill value and write nothing: the oracle's claim that a callee cannot
  change an output (project write closure) is **not** checked here;
* enumerator, ``const`` object and ``const`` array element values are the engine's (as in
  ``mcdc_design_clang_oracle.py``);
* every macro is defined at the top of the harness: where a macro is defined relative to the function is not
  checked (the oracle refuses a macro the unit defines after the function);
* which macros are active and with which bodies (include resolution, ``#if`` verdicts, toolchain-header and
  typedef-width assumptions) is the engine's project context — the harness reuses it, so a wrong preprocessing
  verdict would be agreed with;
* clang evaluates operands left to right, as the oracle does: order-of-evaluation claims are not checked here — the
  oracle refuses order-dependent expressions instead (``check_sequencing``);
* C and C++ agree on integer promotions and conversions for these programs; where they differ (C++20 defines
  signed narrowing and ``<<`` of negatives) the oracle claims nothing, so no claim rests on the difference;
* a unit the harness cannot compile (register structs, ``static`` locals — not allowed in C++20 constexpr,
  vendor syntax) is counted **unchecked**, never agreed;
* the fill values are a sample (0/90/201), not a proof of independence from unset state;
* C++ sequences some things C leaves unsequenced (``=`` operands since C++17, list-initialization items): the
  oracle refuses those in C, so no claim rests on the difference — but clang cannot catch that refusal missing;
* every compilation carries a canary assertion that must fail: a run that does not report it (a missing target,
  a driver error, a crash) is a failure, never a silent pass.

Usage:
    .venv/Scripts/python.exe scripts/source_oracle_clang_check.py --xlsm OUT.xlsm --source-root ROOT [--out r.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_FILLS = (0, 90, 201)
_REAL_EVAL_ERROR = re.compile(r"outside the range of representable|division by zero|cannot refer to element|past-the-end"
                              r"|shift|uninitialized|outside its lifetime|signed integer overflow")
_IDENT = re.compile(r"\b[A-Za-z_]\w*\b")
# Which clang diagnostics a disclosed possible-UB kind explains (review round 7 W1): an evaluation error is set aside
# as "disclosed" only when what the oracle disclosed can be the cause — any other error stays a contradiction.
# Shift UB by clang's note forms — the bare word would match a callee named ``do_shift`` (review round 8 W1).
_SHIFT_NOTE = r"shift count \S+ >= width|negative shift count|left shift of negative|signed left shift discards"
_OVERFLOW_MESSAGE = re.compile(r"outside the range of representable|signed integer overflow|" + _SHIFT_NOTE)
_INDEX_MESSAGE = re.compile(r"cannot refer to element|past-the-end")
_DISCLOSED_MESSAGE = {
    "signed_overflow_unknown_operand": _OVERFLOW_MESSAGE,
    "signed_overflow_untyped_operand": _OVERFLOW_MESSAGE,
    "division_by_unknown": re.compile(r"division by zero|outside the range of representable"),
    "shift_by_unknown": re.compile(_SHIFT_NOTE),
    "index_unknown": _INDEX_MESSAGE,
    "pointer_arithmetic_untyped": _INDEX_MESSAGE,
    "operand_under_unknown_condition": re.compile(r"outside the range of representable|division by zero"
                                                  r"|cannot refer to element|past-the-end|signed integer overflow|"
                                                  + _SHIFT_NOTE),
}


def _disclosure_explains(possible_ub, message) -> bool:
    """True when one of the disclosed possible-UB kinds can produce this clang evaluation error."""
    return any(kind in _DISCLOSED_MESSAGE and _DISCLOSED_MESSAGE[kind].search(message or "")
               for kind in possible_ub or ())


_KEYWORDS = frozenset("""auto break case char const continue default do double else enum extern float for goto if int long
register return short signed sizeof static struct switch typedef union unsigned void volatile while""".split())


def _text(node, raw):
    return raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


_ENUM_BASES = ("int", "unsigned int", "unsigned char", "signed char")


def _base_type(t, enum_base="int"):
    if t.get("kind") == "_Bool":
        return "bool"
    if t.get("enum"):
        # The oracle claims a value only if every permitted underlying type agrees: each one is checked in turn.
        return enum_base
    if t.get("kind") in {"float", "double"}:
        return t["kind"]
    return ("unsigned " if not t["signed"] else "signed ") + t["kind"]


def _input_int(value, constants):
    """A sequence input as the oracle reads it (``"0x0"``, ``"5U"``, an enumerator name) — else None (round 2 I)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        if re.fullmatch(r"[-+]?(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*", s):
            s = s.rstrip("uUlL")
            return int(s, 16) if "x" in s.lower() else int(s, 10)
        if s in constants:
            return constants[s]["value"]
    return None


def _fits(value, t):
    from generators import c_project_context as cpc
    if not isinstance(value, int) or not isinstance(t, dict) or cpc.is_float(t):
        return False
    lo, hi = (0, 1) if t["kind"] == "_Bool" else cpc.type_range(t)
    if t.get("enum"):
        lo, hi = 0, 127
    return lo <= value <= hi


def _fill_for(t, fill):
    from generators import c_project_context as cpc
    if t.get("kind") == "_Bool":
        return fill & 1
    lo, hi = cpc.type_range(t)
    return max(lo, min(hi, fill))


_MAX_EVALUATIONS = 256


def _instrumented_body(fn, raw, instrument):
    """(R2c) The body text with every instrumented decision wrapped: ``(begin(d), end(d, (<decision>)))`` and each of its
    conditions ``atom(d, i, (<condition>))`` — clang then records, per evaluation of the decision, which conditions the
    short circuit evaluated with which value, and the outcome. Nested or overlapping spans: ``None`` (unchecked)."""
    body = fn.child_by_field_name("body")
    edits = []
    for d, decision in enumerate(instrument["decisions"]):
        s, e = decision["span"]
        edits.append((s, e, f"((__oracle_begin({d}), __oracle_end({d}, (", "))))"))
        for i, (a0, a1) in enumerate(decision["atoms"]):
            edits.append((a0, a1, f"__oracle_atom({d}, {i}, (", "))"))
    edits.sort(key=lambda x: (x[0], -x[1]))
    for (s1, e1, *_), (s2, e2, *_) in zip(edits, edits[1:], strict=False):
        if s2 < e1 and e2 > e1:
            return None  # overlapping, not nested
    spans = [(s, e) for s, e, *_ in edits]
    for i, (s1, e1) in enumerate(spans):
        # a decision may contain only its own conditions; decisions inside another decision are not instrumented
        inside = [j for j, (s2, e2) in enumerate(spans) if j != i and s1 <= s2 and e2 <= e1 and (s2, e2) != (s1, e1)]
        if any(edits[j][2].startswith("((__oracle_begin") for j in inside):
            return None
    if any(not (body.start_byte <= s and e <= body.end_byte) for s, e in spans):
        return None

    def render(lo, hi, items):
        out, pos, k = [], lo, 0
        while k < len(items):
            s, e, pre, post = items[k]
            inner = []
            k += 1
            while k < len(items) and items[k][0] < e:
                inner.append(items[k])
                k += 1
            out.append(raw[pos:s])
            out.append(pre.encode() + render(s, e, inner) + post.encode())
            pos = e
        out.append(raw[pos:hi])
        return b"".join(out)
    text = render(body.start_byte, body.end_byte, edits).decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _harness(unit, claims, fn, raw, enum_base="int", instrument=None):
    """C++ text for one function and its claims: (source, {line: (claim index, output, value, variant)}, reason, meta).

    ``meta``: ``callees`` (stubbed calls — callee effects are not checked), ``enum`` (an enumeration type is used).
    ``instrument`` (R2c): ``{"decisions": [{"span": (start, end), "atoms": [(start, end), ...]}]}`` — decisions whose
    evaluations the claims' outputs name through `decision_claim` expressions."""
    from generators import c_project_context as cpc
    from generators.mcdc_design import _function_name
    scope = unit["project_scope"]
    _, fdecl = _function_name(fn, raw)
    if fdecl is None or fdecl.parent is None or fdecl.parent.type != "function_definition":
        return None, {}, "function_declarator_not_direct", {}
    # CRLF sources: a ``\r`` left in the text makes clang count an extra line (R2b review W7).
    body = _text(fn.child_by_field_name("body"), raw).replace("\r\n", "\n").replace("\r", "\n")
    if instrument:
        body = _instrumented_body(fn, raw, instrument)
        if body is None:
            return None, {}, "decision_instrumentation_overlap", {}
    rtype = " ".join([_text(c, raw) for c in fn.named_children if c.type == "type_qualifier"] +
                     [_text(fn.child_by_field_name("type"), raw)])
    params = []
    for p in fdecl.child_by_field_name("parameters").named_children:
        if p.type != "parameter_declaration":
            continue
        d = p.child_by_field_name("declarator")
        if d is None:
            continue
        name = cpc._declared_name(d, raw)
        params.append((name, _text(p, raw), d.type == "identifier", _text(p.child_by_field_name("type"), raw)))
    macro_bodies = scope.get("macro_bodies") or {}
    fbodies = scope.get("function_like_macro_bodies") or {}
    fparams = scope.get("function_like_macro_params") or {}
    constants = scope["constants"]
    globals_, arrays, types = scope.get("globals") or {}, scope.get("arrays") or {}, scope.get("types") or {}
    # every identifier the body can reach through macro expansion
    tokens, pending = set(), list(_IDENT.findall(body) + _IDENT.findall(rtype) + [x for p in params for x in _IDENT.findall(p[1])])
    while pending:
        tok = pending.pop()
        if tok in tokens:
            continue
        tokens.add(tok)
        if tok in macro_bodies:
            pending.extend(_IDENT.findall(macro_bodies[tok]))
        if tok in fbodies:
            pending.extend(_IDENT.findall(fbodies[tok]))
    status = scope.get("macro_status") or {}
    macros = [t for t in sorted(tokens) if status.get(t) == "active" and (t in macro_bodies or t in fbodies)]
    if any(status.get(t) not in (None, "active") for t in tokens):
        return None, {}, "macro_not_active_in_unit", {}
    lines = ["// generated by scripts/source_oracle_clang_check.py — do not edit"]
    for name in sorted(tokens):
        t = types.get(name)
        if isinstance(t, dict) and name not in status:
            lines.append(f"typedef {_base_type(t, enum_base)} {name};")
    for name in macros:
        if name in fbodies:
            lines.append(f"#define {name}({', '.join(fparams.get(name) or [])}) {_one_line(fbodies[name])}")
        else:
            lines.append(f"#define {name} {_one_line(macro_bodies[name])}")
    for name in sorted(tokens):
        if name in status or name in globals_ or name in arrays:
            continue
        c = dict.get(constants, name) if name in constants else None
        if c is not None and c.get("kind") in {"enumerator", "const_object", "const_object_linked"}:
            t = c["type"]
            lines.append(f"#define {name} (({_base_type(t)})({c['value']}))")
    callees = sorted({m.group(1) for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", body + " " + " ".join(fbodies.get(m, "") for m in macros))
                      if m.group(1) not in status and m.group(1) not in _KEYWORDS and m.group(1) not in types
                      and m.group(1) not in globals_ and m.group(1) not in arrays and not m.group(1).startswith("__oracle")})
    used_globals = [g for g in sorted(tokens) if (g in globals_ or g in arrays) and g not in status]
    checks: dict[int, tuple] = {}
    for variant, fill in enumerate(_FILLS):
        lines.append(f"namespace __oracle_v{variant} {{")
        lines.append(f"constexpr int __oracle_stub = {fill};")
        for c in callees:
            lines.append(f"template<class... __oracle_A> constexpr int {c}(__oracle_A...) {{ return __oracle_stub; }}")
        for index, claim in enumerate(claims):
            inputs = {k: _input_int(v, constants) for k, v in claim["inputs"].items()}
            lines.append(f"constexpr long long __oracle_run_{index}(int __oracle_which) {{")
            for g in used_globals:
                if g in globals_:
                    t = globals_[g]["type"]
                    value = inputs.get(g)
                    init = value if _fits(value, t) else _fill_for(t, fill)
                    lines.append(f"  {_base_type(t, enum_base)} {g} = {init};")
                else:
                    a = arrays[g]
                    if a.get("length") is None:
                        return None, {}, "array_length_unresolved:" + g, {}
                    if a.get("const") and a.get("values") is not None:
                        elems = a["values"]
                    else:
                        elems = [inputs.get(f"{g}[{k}]") if _fits(inputs.get(f"{g}[{k}]"), a["type"]) else _fill_for(a["type"], fill)
                                 for k in range(a["length"])]
                    lines.append(f"  {_base_type(a['type'], enum_base)} {g}[{a['length']}] = {{{', '.join(str(v) for v in elems)}}};")
            args = []
            for i, (name, _decl, scalar, typ) in enumerate(params):
                if scalar:
                    try:
                        from generators.mcdc_design import _scope_type
                        t = _scope_type(scope, typ)
                    except cpc.Unresolved:
                        return None, {}, "parameter_type_unresolved:" + name, {}
                    value = inputs.get(name)
                    args.append(str(value if _fits(value, t) else _fill_for(t, fill)))
                else:
                    # the pointee varies with the fill too: what the claim does not depend on must not matter
                    lines.append(f"  {typ} __oracle_buf_{i}[64] = {{}};")
                    lines.append(f"  for (int __oracle_k = 0; __oracle_k < 64; ++__oracle_k) __oracle_buf_{i}[__oracle_k] = {fill};")
                    args.append(f"__oracle_buf_{i}")
            plist = ", ".join(p[1] for p in params)
            if instrument:
                nd = len(instrument["decisions"])
                na = max(len(d["atoms"]) for d in instrument["decisions"])
                lines.append(f"  int __oracle_cnt[{nd}] = {{}}; int __oracle_rec[{nd}][{_MAX_EVALUATIONS}][{na}] = {{}};"
                             f" int __oracle_out[{nd}][{_MAX_EVALUATIONS}] = {{}};")
                lines.append("  auto __oracle_begin = [&](int __d) -> int { ++__oracle_cnt[__d]; return 0; };")
                lines.append(f"  auto __oracle_atom = [&](int __d, int __a, bool __v) -> bool {{ if (__oracle_cnt[__d] <= "
                             f"{_MAX_EVALUATIONS}) __oracle_rec[__d][__oracle_cnt[__d] - 1][__a] = __v ? 2 : 1; return __v; }};")
                lines.append(f"  auto __oracle_end = [&](int __d, bool __v) -> bool {{ if (__oracle_cnt[__d] <= "
                             f"{_MAX_EVALUATIONS}) __oracle_out[__d][__oracle_cnt[__d] - 1] = __v ? 2 : 1; return __v; }};")
            lines.append(f"  auto __oracle_fn = [&]({plist}) -> {rtype}")
            lines.append(body)
            lines.append("  ;")
            if rtype.strip() == "void":
                lines.append(f"  __oracle_fn({', '.join(args)});")
                lines.append("  long long __oracle_ret = 0;")
            else:
                lines.append(f"  long long __oracle_ret = (long long)__oracle_fn({', '.join(args)});")
            lines.append("  switch (__oracle_which) {")
            for k, name in enumerate(claim["outputs"]):
                expr = "__oracle_ret" if name == "return" else name
                lines.append(f"    case {k}: return (long long)({expr});")
            lines.append("  }")
            lines.append("  return -999999999LL;")
            lines.append("}")
        lines.append("}")
    tags: dict[str, tuple] = {}
    lines.append('static_assert(1 == 2, "__oracle_canary");')
    for variant in range(len(_FILLS)):
        for index, claim in enumerate(claims):
            for k, (name, value) in enumerate(claim["outputs"].items()):
                tag = f"__oracle_check_{index}_{variant}_{k}"
                tags[tag] = (index, name, value, variant, f"{index}_{variant}_{k}")
                lines.append(f"static_assert(__oracle_v{variant}::__oracle_run_{index}({k}) == {int(value)}LL, \"{tag}\");")
    text = "\n".join(lines) + "\n"
    # Line numbers come from the final text (function bodies span many lines): each assertion carries a unique tag.
    for number, line in enumerate(text.split("\n"), start=1):  # clang counts only \n (\f, \v, \x85 are not lines)
        m = re.search(r'"(__oracle_check_\d+_\d+_\d+)"\);$', line)
        if m and line.startswith("static_assert("):
            checks[number] = tags[m.group(1)]
    if len(checks) != len(tags):
        return None, {}, "assertion_lines_not_unique", {}
    meta = {"callees": bool(callees), "enum": any(isinstance(types.get(x), dict) and types[x].get("enum") for x in tokens)
            or any((globals_.get(g) or arrays.get(g) or {}).get("type", {}).get("enum") for g in used_globals)}
    return text, checks, "", meta


def decision_claim(d, truth, observed, outcome):
    """(R2c) Output expression for a path-designed MC/DC claim: 1 when some evaluation of instrumented decision ``d``
    in the run had exactly these evaluated conditions (``observed``) with these values and this outcome, else 0. When
    the decision was evaluated more often than the recorder holds, the expression throws: not a constant expression, so
    the claim is counted *unchecked* (``constexpr_limit``) — neither agreed nor contradicted."""
    codes = [(2 if t else 1) if o else 0 for t, o in zip(truth, observed, strict=True)]
    atoms = " && ".join(f"__oracle_rec[{d}][__e][{i}] == {c}" for i, c in enumerate(codes))
    return (f"[&]() -> long long {{ if (__oracle_cnt[{d}] > {_MAX_EVALUATIONS}) throw 0; "
            f"for (int __e = 0; __e < __oracle_cnt[{d}]; ++__e) if ({atoms} && __oracle_out[{d}][__e] == "
            f"{2 if outcome else 1}) return 1; return 0; }}()")


def _one_line(body):
    return body.replace("\r\n", "\n").replace("\r", "\n").replace("\\\n", " ").replace("\n", " ")


_TAG = re.compile(r"__oracle_check_\d+_\d+_\d+")


def _run_tu(source, checks, path, clang, target, timeout):
    """Compile one harness. Returns ({(claim, output): verdict}, {(claim, output): detail}) or a unit-level reason."""
    Path(path).write_text(source, encoding="utf-8", newline="\n")
    try:
        proc = subprocess.run([clang, "-x", "c++", f"--target={target}", "-std=c++20", "-fsyntax-only",
                               "-ferror-limit=0", "-fconstexpr-steps=20000000", "-Wno-everything",
                               "-Werror=unsequenced", path],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, None, "clang_failed:" + type(exc).__name__
    by_tag = {}
    tag_of_line = {}
    for lineno, check in checks.items():
        tag = f"__oracle_check_{check[4]}"
        by_tag[tag] = check
        tag_of_line[lineno] = tag
    errors: dict[str, list[str]] = {}
    other_errors, unattributed = [], []
    canary = False
    current = None
    for line in (proc.stdout + proc.stderr).splitlines():
        m = re.match(r"^.*?:(\d+):\d+: (fatal error|error|note): (.*)$", line)
        if not m:
            if re.match(r"^(?:\S*clang\S*: )?(?:fatal )?error:", line.strip()):
                other_errors.append("driver: " + line.strip()[:160])  # ``clang: error: unknown target`` (round 2 C)
            continue
        lineno, kind, message = int(m.group(1)), m.group(2), m.group(3)
        if "__oracle_canary" in message:
            canary = True
            current = None
            continue
        if kind in {"error", "fatal error"}:
            tag = next((t for t in _TAG.findall(message) if t in by_tag), None) or tag_of_line.get(lineno)
            current = tag
            if tag is not None:
                errors.setdefault(tag, []).append(message)
            elif "static assertion failed" in message:
                unattributed.append(message)  # a failed claim we cannot place: fail closed below
            else:
                other_errors.append(f"{lineno}: {message}")
        elif current is not None:
            errors.setdefault(current, []).append(message)
    if not canary or proc.returncode != 1:
        # The canary must fail and nothing else may stop clang: otherwise the run proves nothing (round 2 C).
        return None, None, "canary_not_reported:" + (other_errors[0] if other_errors else f"rc={proc.returncode}")
    if unattributed:
        return None, None, "unattributed_assertion_failure"
    if any("unsequenced" in e for e in other_errors):
        return None, None, "unsequenced_in_source"
    if other_errors or proc.returncode not in (0, 1):
        return None, None, "harness_compile_error:" + (other_errors[0] if other_errors else f"rc={proc.returncode}")
    verdict: dict[tuple, str] = {}
    detail: dict[tuple, str] = {}
    for tag, (index, name, _value, variant, _tag) in by_tag.items():
        msgs = errors.get(tag)
        k = (index, name)
        if not msgs:
            verdict.setdefault(k, "agree")
            continue
        if any("static assertion failed" in x for x in msgs):
            verdict[k] = "mismatch"
            detail[k] = next((x for x in msgs if "evaluates to" in x), msgs[0]) + f" (fill={_FILLS[variant]})"
        elif verdict.get(k) != "mismatch":
            # Undefined behaviour or an indeterminate read on the path contradicts a "derived" claim; anything else
            # (``reinterpret_cast`` of an array argument, a volatile read) is a limit of the harness.
            real = any(_REAL_EVAL_ERROR.search(x) for x in msgs)
            if real or verdict.get(k) != "eval_error":
                verdict[k] = "eval_error" if real else "constexpr_limit"
            detail.setdefault(k, " | ".join(msgs[:3]))
    return verdict, detail, ""


def check_claims(claims: list[dict], clang: str = "clang", target: str = "msp430", work_dir: str | None = None,
                 timeout: int = 120) -> dict:
    """``claims``: ``[{"unit": unit-with-project_scope, "inputs": {...}, "outputs": {name: value}, "possible_ub": [...]}]``.

    ``agree`` counts claims that held for every fill value (and, when the function uses an enumeration, for every
    permitted underlying type). ``agree_with_stubbed_callees`` is the part of it whose function makes calls: the
    stubs write nothing, so for those claims the callee-effect model is *not* what clang confirmed."""
    from generators import c_project_context as cpc
    from generators.c_source_oracle import _find_function
    groups: dict[tuple, list] = {}
    for claim in claims:
        unit = claim["unit"]
        groups.setdefault((unit.get("source_path") or "", unit.get("name") or "", id(unit["project_scope"]),
                           id(claim.get("instrument"))), []).append(claim)
    report = {"target": target, "fills": list(_FILLS), "enum_bases": list(_ENUM_BASES),
              "claims": sum(len(c["outputs"]) for c in claims),
              "checked": 0, "agree": 0, "agree_with_stubbed_callees": 0, "mismatch": 0, "eval_error": 0, "unchecked": 0,
              "unchecked_reasons": Counter(), "mismatches": [], "eval_errors": []}
    work = work_dir or tempfile.mkdtemp(prefix="oracle_clang_")
    os.makedirs(work, exist_ok=True)
    parser = cpc.shared_parser()
    for gi, (_key, group) in enumerate(groups.items()):
        unit = group[0]["unit"]
        n_outputs = sum(len(c["outputs"]) for c in group)
        raw = str(unit.get("source_text") or "").encode()
        verdict: dict[tuple, str] = {}
        detail: dict[tuple, str] = {}
        failure = ""
        meta: dict = {}
        for bi, base in enumerate(_ENUM_BASES):
            try:
                fn = _find_function(parser.parse(raw).root_node, raw, unit["name"], unit["project_scope"])
                source, checks, reason, meta = _harness(unit, group, fn, raw, enum_base=base,
                                                        instrument=group[0].get("instrument"))
            except Exception as exc:  # noqa: BLE001 — any harness failure is an unchecked unit, reported by name
                source, checks, reason = None, {}, f"harness_exception:{type(exc).__name__}"
            if source is None:
                failure = reason
                break
            one, one_detail, reason = _run_tu(source, checks, os.path.join(work, f"u{gi}_{bi}.cpp"), clang, target, timeout)
            if one is None:
                failure = reason
                break
            for k, v in one.items():
                rank = {"agree": 0, "constexpr_limit": 1, "eval_error": 2, "mismatch": 3}
                if rank[v] >= rank.get(verdict.get(k, "agree"), 0):
                    verdict[k] = v
                    if k in one_detail:
                        detail[k] = one_detail[k] + ("" if base == "int" else f" (enum as {base})")
            if not meta.get("enum"):
                break  # no enumeration involved: one underlying type is the whole story
        if failure:
            if failure == "unsequenced_in_source":
                # The body itself is order-dependent: a claim on it is a real contradiction, not a harness limit.
                for index, claim in enumerate(group):
                    for name in claim["outputs"]:
                        report["checked"] += 1
                        report["eval_error"] += 1
                        report["eval_errors"].append({"function": unit["name"], "file": unit.get("source_path"),
                                                      "inputs": claim["inputs"], "output": name,
                                                      "claimed": claim["outputs"][name], "clang": failure})
                continue
            report["unchecked"] += n_outputs
            report["unchecked_reasons"][failure.split(":")[0]] += n_outputs
            if failure.startswith("harness_compile_error") or failure == "unattributed_assertion_failure":
                report.setdefault("compile_errors", []).append({"function": unit["name"], "file": unit.get("source_path"),
                                                                 "first": failure[:200]})
            if failure == "unattributed_assertion_failure":
                report["mismatch"] += n_outputs  # fail closed: a failed assertion we cannot place is a failure
                report["unchecked"] -= n_outputs
                report["checked"] += n_outputs
            continue
        for (index, name), v in verdict.items():
            if v == "eval_error" and _disclosure_explains(group[index].get("possible_ub"), detail.get((index, name))):
                # The oracle disclosed that this run may be undefined (an unknown divisor/shift/index/overflow — the
                # fill values chose one) and clang reports that kind: not a counterexample to a disclosed claim.
                v = "possible_ub_disclosed"
            if v in {"constexpr_limit", "possible_ub_disclosed"}:
                report["unchecked"] += 1
                report["unchecked_reasons"][v] += 1
                continue
            report["checked"] += 1
            report[v] += 1
            if v == "agree" and meta.get("callees"):
                report["agree_with_stubbed_callees"] += 1
            if v != "agree":
                entry = {"function": unit["name"], "file": unit.get("source_path"), "inputs": group[index]["inputs"],
                         "output": name, "claimed": group[index]["outputs"][name], "clang": detail.get((index, name))}
                report["mismatches" if v == "mismatch" else "eval_errors"].append(entry)
    report["unchecked_reasons"] = dict(report["unchecked_reasons"])
    report["work_dir"] = work
    return report


def _claims_from_xlsm(xlsm: str, source_root: str) -> tuple[list[dict], dict]:
    import openpyxl

    from generators.c_project_context import build_project_context, build_scopes
    wb = openpyxl.load_workbook(xlsm, read_only=True)
    ws = wb["Test Evidence"]
    rows = ws.iter_rows(values_only=True)
    header = list(next(rows))
    grouped: dict[tuple, dict] = {}
    for row in rows:
        d = dict(zip(header, row, strict=False))
        if d.get("Status") != "derived":
            continue
        key = (d["Source path"], d["Function"], d["Test Case ID"], d["Sequence"])
        reason = str(d.get("Reason") or "")
        g = grouped.setdefault(key, {"inputs": json.loads(d.get("Inputs JSON") or "{}"), "outputs": {},
                                     "possible_ub": reason.split("possible_ub=", 1)[1].split("+") if "possible_ub=" in reason else []})
        g["outputs"][d["Observable"]] = int(d["Expected"])
    # Several roots (``APP,BOOT``) are joined with ``,``/``;`` as in the SCM registry — one context, as generated.
    roots = [r.strip() for r in re.split(r"[,;]", source_root) if r.strip()]
    texts, unread = {}, []
    for root in roots:
        for p in sorted(Path(root).rglob("*")):
            if p.suffix.lower() in (".c", ".h") and p.is_file():
                try:
                    texts[str(p.resolve())] = p.read_bytes().decode("utf-8")
                except UnicodeDecodeError:
                    unread.append(str(p.resolve()))  # recorded: never mistaken for a toolchain header
    from generators.c_project_context import detect_build_config
    cprojects = {str(Path(r) / ".cproject"): (Path(r) / ".cproject").read_text(encoding="utf-8", errors="replace")
                 for r in roots if (Path(r) / ".cproject").is_file()}
    context = build_project_context(texts, detect_build_config(cprojects), roots=[str(Path(r).resolve()) for r in roots])
    context["incomplete_files"] = unread
    paths = sorted({k[0] for k in grouped if k[0] in texts})
    scopes = build_scopes(context, paths)
    units: dict[tuple, dict] = {}
    claims = []
    for (path, fn, _tc, _seq), g in grouped.items():
        if path not in scopes:
            continue
        unit = units.setdefault((path, fn), {"name": fn, "source_text": texts[path], "source_path": path,
                                             "project_scope": scopes[path]})
        claims.append({"unit": unit, **g})
    meta = {"xlsm": xlsm, "source_root": source_root, "derived_sequences": len(grouped),
            "sequences_with_source": len(claims)}
    return claims, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--xlsm", required=True, help="generated SUTS workbook with a 'Test Evidence' sheet")
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--clang", default="clang")
    ap.add_argument("--target", default="msp430", help="clang target with the ECU's integer widths")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    claims, meta = _claims_from_xlsm(args.xlsm, args.source_root)
    report = {**meta, **check_claims(claims, clang=args.clang, target=args.target)}
    text = json.dumps(report, ensure_ascii=False, indent=1, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    summary = {k: report[k] for k in ("claims", "checked", "agree", "mismatch", "eval_error", "unchecked", "unchecked_reasons")}
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if report["mismatch"] or report["eval_error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
