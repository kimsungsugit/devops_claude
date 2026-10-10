"""Conservative C source oracle, not a requirement oracle or execution result.

Only integer, side-effect-free functions with local assignments and if/return
are supported. Every target AST node is checked, including untaken branches.
Arithmetic is deliberately limited to the portable signed-int range; no ABI,
overflow, cast, macro, call, pointer or floating-point behavior is guessed.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any


class Unsupported(ValueError):
    """The complete function cannot be interpreted safely."""


_TYPES = {
    "int": (-32767, 32767), "signed int": (-32767, 32767),
    "int8_t": (-128, 127), "uint8_t": (0, 255),
    "int16_t": (-32768, 32767), "uint16_t": (0, 65535),
    "int32_t": (-2147483648, 2147483647), "uint32_t": (0, 4294967295),
}
_ALLOWED = {
    "compound_statement", "return_statement", "if_statement", "else_clause",
    "expression_statement", "assignment_expression", "declaration", "init_declarator",
    "identifier", "primitive_type", "type_identifier", "sized_type_specifier",
    "number_literal", "binary_expression", "unary_expression", "parenthesized_expression",
    "comment",
}


def evaluate_function(source_text: str, function_name: str, inputs: dict[str, Any], *, _context: dict | None = None) -> dict[str, Any]:
    """Derive a return value from a complete, restricted C translation unit.

    Args:
        source_text: Captured source, including the complete function definition.
        function_name: Exact, unambiguous function identifier.
        inputs: Concrete parameter values; extra state inputs are rejected.

    Returns:
        Supported value or explicit unsupported reason, always not_run.
    """
    result = {"status": "unsupported", "execution_status": "not_run",
              "source_hash": hashlib.sha256(source_text.encode()).hexdigest(),
              "function_name": function_name}
    try:
        if not source_text or len(source_text) > 2_000_000:
            raise Unsupported("missing_source_or_source_budget")
        raw = source_text.encode()
        if _context is not None and _context.get("source_hash") != result["source_hash"]:
            _context.clear()
            _context["source_hash"] = result["source_hash"]
        root = (_context or {}).get("root")
        if root is None:
            from workflow.code_parser.c_parser import _make_parser
            parser = _make_parser()
            if parser is None:
                raise Unsupported("tree_sitter_unavailable")
            root = parser.parse(raw).root_node
            if _context is not None:
                _context["root"] = root
        if root.has_error:
            raise Unsupported("source_parse_error")
        def txt(n):
            return raw[n.start_byte:n.end_byte].decode()
        def walk(n):
            yield n
            for child in n.named_children:
                yield from walk(child)
        all_nodes = (_context or {}).get("nodes")
        if all_nodes is None:
            all_nodes = list(walk(root))
            if _context is not None:
                _context["nodes"] = all_nodes
        if len(all_nodes) > 20000:
            raise Unsupported("ast_budget")
        for n in all_nodes:
            if n.type.startswith("preproc_") and not (
                n.type == "preproc_include" and txt(n).strip() == "#include <stdint.h>"
            ):
                raise Unsupported("preprocessor_context_unsupported")
        has_stdint = any(n.type == "preproc_include" and txt(n).strip() == "#include <stdint.h>" for n in all_nodes)
        types = {name: bounds for name, bounds in _TYPES.items() if has_stdint or name in {"int", "signed int"}}
        for n in root.named_children:
            if n.type == "type_definition":
                t, d = n.child_by_field_name("type"), n.child_by_field_name("declarator")
                if d is None or d.type != "type_identifier" or txt(t) not in types or len(n.named_children) != 2:
                    raise Unsupported("unresolved_typedef")
                if txt(d) in types:
                    raise Unsupported("typedef_redefinition")
                types[txt(d)] = types[txt(t)]
        matches = []
        for n in root.named_children:
            if n.type == "function_definition":
                d = n.child_by_field_name("declarator")
                ident = d.child_by_field_name("declarator") if d is not None else None
                if ident is not None and txt(ident) == function_name:
                    matches.append(n)
        if len(matches) != 1:
            raise Unsupported("function_identity_missing_or_ambiguous")
        fn = matches[0]
        body = fn.child_by_field_name("body")
        for n in walk(body):
            if n.type not in _ALLOWED:
                raise Unsupported("unsupported_ast:" + n.type)
        def get_type(n):
            if n is None or txt(n) not in types:
                raise Unsupported("unknown_type:" + (txt(n) if n else "missing"))
            return types[txt(n)]
        return_type = get_type(fn.child_by_field_name("type"))
        if any(n.type not in {"primitive_type", "type_identifier", "sized_type_specifier",
                              "function_declarator", "compound_statement", "storage_class_specifier"}
               for n in fn.named_children):
            raise Unsupported("unsupported_function_qualifier")
        env, declarations = {}, {}
        def checked(v, typ):
            if type(v) is not int or not typ[0] <= v <= typ[1]:
                raise Unsupported("value_outside_declared_type")
            return v
        params = fn.child_by_field_name("declarator").child_by_field_name("parameters")
        for p in params.named_children:
            if len(params.named_children) == 1 and txt(p) == "void" and p.type in {"primitive_type", "parameter_declaration"}:
                continue
            d = p.child_by_field_name("declarator")
            if p.type != "parameter_declaration" or d is None or d.type != "identifier" or len(p.named_children) != 2:
                raise Unsupported("unsupported_parameter")
            name, typ = txt(d), get_type(p.child_by_field_name("type"))
            if name in declarations or name not in inputs:
                raise Unsupported("missing_or_duplicate_parameter")
            v = inputs[name]
            if isinstance(v, str) and re.fullmatch(r"-?(?:0x[0-9a-fA-F]+|[0-9]+)", v):
                v = int(v, 16 if "0x" in v else 10)
            env[name], declarations[name] = checked(v, typ), typ
        if set(inputs) != set(declarations):
            raise Unsupported("unbound_state_input")
        known = set(declarations)
        def validate_bindings(n):
            if n.type == "declaration":
                if n.parent != body:
                    raise Unsupported("nested_local_scope_unsupported")
                for d in n.named_children:
                    if d == n.child_by_field_name("type"):
                        continue
                    if d.type != "init_declarator":
                        raise Unsupported("local_requires_simple_initializer")
                    ident = d.child_by_field_name("declarator")
                    if ident is None or ident.type != "identifier" or txt(ident) in known:
                        raise Unsupported("unsupported_or_shadowed_local")
                    validate_bindings(d.child_by_field_name("value"))
                    known.add(txt(ident))
                return
            if n.type == "identifier" and txt(n) not in known:
                raise Unsupported("unbound_identifier:" + txt(n))
            for c in n.named_children:
                validate_bindings(c)
        validate_bindings(body)
        # Validate operators and declarations even when the branch is not taken.
        for n in walk(body):
            if n.type == "number_literal":
                if not re.fullmatch(r"(?:0|[1-9][0-9]*|0[xX][0-9a-fA-F]+)", txt(n)):
                    raise Unsupported("unsupported_literal")
                checked(int(txt(n), 16 if "x" in txt(n).lower() else 10), (-32767, 32767))
            if n.type == "return_statement" and len(n.named_children) != 1:
                raise Unsupported("unsupported_return_statement")
            if n.type == "expression_statement" and (
                len(n.named_children) != 1 or n.named_children[0].type != "assignment_expression"
            ):
                raise Unsupported("unsupported_expression_statement")
            if n.type == "binary_expression" and txt(n.child_by_field_name("operator")) not in {"+", "-", "*", "<", "<=", ">", ">=", "==", "!=", "&&", "||"}:
                raise Unsupported("unsupported_binary_operator")
            if n.type == "unary_expression" and txt(n.child_by_field_name("operator")) not in {"-", "+", "!"}:
                raise Unsupported("unsupported_unary_operator")
            if n.type == "assignment_expression" and txt(n.child_by_field_name("operator")) != "=":
                raise Unsupported("unsupported_assignment")
            if n.type == "assignment_expression" and (
                n.parent.type != "expression_statement"
                or n.child_by_field_name("left").type != "identifier"
            ):
                raise Unsupported("assignment_expression_context_unsupported")
            if n.type == "declaration":
                get_type(n.child_by_field_name("type"))
                if n.parent != body:
                    raise Unsupported("nested_local_scope_unsupported")
                if any(c != n.child_by_field_name("type") and c.type != "init_declarator" for c in n.named_children):
                    raise Unsupported("local_requires_simple_initializer")
        def expr(n):
            k = n.type
            if k == "identifier":
                if txt(n) not in env:
                    raise Unsupported("unbound_identifier:" + txt(n))
                return env[txt(n)]
            if k == "number_literal":
                return int(txt(n), 16 if "x" in txt(n).lower() else 10)
            if k == "parenthesized_expression":
                return expr(n.named_children[0])
            if k == "unary_expression":
                v = expr(n.child_by_field_name("argument"))
                op = txt(n.child_by_field_name("operator"))
                if op == "!":
                    return int(not v)
                if any(declarations.get(txt(x), (0, 0))[0] == 0 and declarations.get(txt(x), (0, 0))[1] > 32767 for x in walk(n) if x.type == "identifier"):
                    raise Unsupported("target_dependent_unsigned_unary")
                return checked(v if op == "+" else -v, (-32767, 32767))
            if k == "binary_expression":
                a = expr(n.child_by_field_name("left"))
                op = txt(n.child_by_field_name("operator"))
                if op == "&&" and not a:
                    return 0
                if op == "||" and a:
                    return 1
                b = expr(n.child_by_field_name("right"))
                checked(a, (-32767, 32767))
                checked(b, (-32767, 32767))
                # Wide unsigned promotions depend on the target int width.
                if (a < 0 or b < 0) and any(declarations.get(txt(x), (0, 0))[1] > 32767 and declarations.get(txt(x), (0, 0))[0] == 0 for x in walk(n) if x.type == "identifier"):
                    raise Unsupported("target_dependent_unsigned_conversion")
                values = {"+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b,
                          "<": lambda: int(a < b), "<=": lambda: int(a <= b),
                          ">": lambda: int(a > b), ">=": lambda: int(a >= b),
                          "==": lambda: int(a == b), "!=": lambda: int(a != b),
                          "&&": lambda: int(bool(a) and bool(b)), "||": lambda: int(bool(a) or bool(b))}
                value = values[op]()
                if value < 0 and any(declarations.get(txt(x), (0, 0))[0] == 0 and declarations.get(txt(x), (0, 0))[1] > 32767 for x in walk(n) if x.type == "identifier"):
                    raise Unsupported("unsigned_arithmetic_wrap")
                return checked(value, (-32767, 32767))
            raise Unsupported("unsupported_expression:" + k)
        def statement(n):
            k = n.type
            if k == "comment":
                return None
            if k in {"compound_statement", "else_clause"}:
                for c in n.named_children:
                    ret = statement(c)
                    if ret is not None:
                        return ret
                return None
            if k == "return_statement":
                return (checked(expr(n.named_children[0]), return_type),)
            if k == "if_statement":
                branch = "consequence" if expr(n.child_by_field_name("condition")) else "alternative"
                child = n.child_by_field_name(branch)
                return statement(child) if child is not None else None
            if k == "declaration":
                typ = get_type(n.child_by_field_name("type"))
                ds = [c for c in n.named_children if c != n.child_by_field_name("type")]
                for d in ds:
                    if d.type != "init_declarator" or d.child_by_field_name("declarator").type != "identifier":
                        raise Unsupported("local_requires_simple_initializer")
                    name = txt(d.child_by_field_name("declarator"))
                    if name in declarations:
                        raise Unsupported("shadowed_variable")
                    env[name] = checked(expr(d.child_by_field_name("value")), typ)
                    declarations[name] = typ
                return None
            if k == "expression_statement" and len(n.named_children) == 1:
                a = n.named_children[0]
                if a.type == "assignment_expression":
                    left = a.child_by_field_name("left")
                    name = txt(left)
                    if left.type == "identifier" and name in declarations:
                        env[name] = checked(expr(a.child_by_field_name("right")), declarations[name])
                        return None
            raise Unsupported("unsupported_statement:" + k)
        returned = statement(body)
        if returned is None:
            raise Unsupported("missing_return")
        result.update(status="supported", value=returned[0], reason="restricted_source_evaluation")
    except (Unsupported, ValueError, TypeError, AttributeError, IndexError, KeyError, RecursionError) as exc:
        result["reason"] = str(exc) or type(exc).__name__
    return result


def evaluate_function_inputs(source_text: str, function_name: str, inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evaluate one source snapshot for several inputs without reparsing it.

    The context is confined to this call; source contents are never cached
    globally or reused for another translation unit.
    """
    context: dict[str, Any] = {}
    return [evaluate_function(source_text, function_name, values, _context=context) for values in inputs]
