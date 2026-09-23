"""Whole-function subset checks independent of the selected input path."""
import pytest

from generators.c_test_semantics import evaluate_function


@pytest.mark.parametrize("value", [0, 1])
def test_assignment_in_return_rejected_even_when_branch_is_untaken(value):
    source = "int f(int x) { if (x) return (x = 2); return 0; }"
    result = evaluate_function(source, "f", {"x": value})
    assert result["status"] == "unsupported"
    assert result["reason"] == "assignment_expression_context_unsupported"


def test_standalone_assignment_remains_supported():
    source = "int f(int x) { int y = x; if (x) y = 2; return y; }"
    assert evaluate_function(source, "f", {"x": 0})["value"] == 0
    assert evaluate_function(source, "f", {"x": 1})["value"] == 2


@pytest.mark.parametrize("literal", ["1.5", "1U", "32768"])
def test_unsupported_literal_is_rejected_in_untaken_branch(literal):
    source = f"int f(int x) {{ if (x) return {literal}; return 0; }}"
    assert evaluate_function(source, "f", {"x": 0})["status"] == "unsupported"


@pytest.mark.parametrize("statement", ["return;", "x + 1;", ";"])
def test_unsupported_statement_form_is_rejected_in_untaken_branch(statement):
    source = f"int f(int x) {{ if (x) {{ {statement} }} return 0; }}"
    assert evaluate_function(source, "f", {"x": 0})["status"] == "unsupported"
