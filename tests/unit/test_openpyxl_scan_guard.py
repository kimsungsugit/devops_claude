"""R13 — performance guard: no openpyxl whole-sheet scan inside a loop in the document generators.

openpyxl computes ``ws.max_row`` / ``ws.max_column`` (and ``dimensions``, ``ws.rows``, ``ws.values``, a bare
``ws.iter_rows()``, ``ws[row]`` through ``max_column``) by walking every stored cell. Done once, that is linear; done in
a loop over rows it is quadratic — the R2b Test Evidence sheet took 30+ minutes on KJPDS02_PV that way. This guard
fails on such a read placed in the body of a loop (or in a comprehension's element/condition), in any module under
``generators/``. Reading it in a loop *header* (``for r in range(1, ws.max_row + 1)``) evaluates once and is allowed.
A line that reads the attribute of something that is not a worksheet (a merged ``CellRange.max_row``) says so with a
``# scan-ok`` comment.

``iter_rows`` / ``iter_cols`` in a loop must bound both axes: without ``max_col`` (``max_row``) openpyxl 3.1 computes
``max_column`` (``max_row``) by a full scan on every call (review round 2 W6). A sheet is a name like ``ws``/``sheet``,
an attribute like ``self.ws`` / ``wb.active``, or ``wb["Name"]``.

Not caught (stated, review rounds 1 W10 / 2 W6): random ``.cell()`` access on a *read-only* sheet (quadratic too —
whether a sheet is read-only is not visible in the syntax), a scan hidden in a helper function called from a loop, and a
sheet held under an unrelated name (``s = wb.active``) — the name patterns above are the contract.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SCAN_ATTRS = {"max_row", "max_column", "min_row", "min_column", "dimensions", "rows", "values"}
_SHEET_NAME = re.compile(r"^(?:ws|sheet|worksheet)\w*$|^\w*_ws$")
_BOOK_NAME = re.compile(r"^(?:wb|book|workbook)\w*$|^\w*_wb$")
_COLUMN_KEY = re.compile(r"^[A-Za-z]{1,3}(?::[A-Za-z]{1,3})?$")   # ``ws["A"]`` / ``ws["A:C"]``: a whole column


def _loop_body_nodes(tree: ast.AST):
    """Nodes evaluated once per iteration: loop bodies/else and comprehension elements/conditions/later iterables."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            for stmt in node.body + node.orelse:
                yield from ast.walk(stmt)
            if isinstance(node, ast.While):
                yield from ast.walk(node.test)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            elts = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
            for e in elts:
                yield from ast.walk(e)
            for i, gen in enumerate(node.generators):
                if i:
                    yield from ast.walk(gen.iter)
                for cond in gen.ifs:
                    yield from ast.walk(cond)


def _is_sheet(node) -> bool:
    if isinstance(node, ast.Name):
        return bool(_SHEET_NAME.match(node.id))
    if isinstance(node, ast.Attribute):   # ``self.ws`` / ``wb.active``
        return bool(_SHEET_NAME.match(node.attr)) or node.attr == "active"
    return isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and bool(_BOOK_NAME.match(node.value.id))


def scan_violations(source: str, name: str = "<src>") -> list[str]:
    tree = ast.parse(source)
    lines = source.splitlines()
    seen, out = set(), []

    def flag(node, what):
        if id(node) in seen or "scan-ok" in lines[node.lineno - 1]:
            return
        seen.add(id(node))
        out.append(f"{name}:{node.lineno}: {what} inside a loop")

    for node in _loop_body_nodes(tree):
        if isinstance(node, ast.Attribute) and node.attr in _SCAN_ATTRS and \
                (node.attr in {"max_row", "max_column"} or _is_sheet(node.value)):
            flag(node, f".{node.attr}")
        elif isinstance(node, ast.Subscript) and _is_sheet(node.value) and not (
                isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)
                and not _COLUMN_KEY.match(node.slice.value)):
            flag(node, "ws[...]")   # ``ws[r]`` / ``ws["A"]`` scan a row or column; ``ws["G26"]`` is one cell
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and _is_sheet(node.func.value):
            given = {k.arg for k in node.keywords}
            if node.func.attr == "calculate_dimension":
                flag(node, ".calculate_dimension()")
            elif node.func.attr == "iter_rows" and not {"max_row", "max_col"} <= given:
                flag(node, ".iter_rows() without max_row and max_col")
            elif node.func.attr == "iter_cols" and not {"max_row", "max_col"} <= given:
                flag(node, ".iter_cols() without max_row and max_col")
    return out


def test_the_guard_sees_a_scan_in_a_loop_and_allows_one_in_the_header():
    assert scan_violations("for r in rows:\n    n = ws.max_row\n") == ["<src>:2: .max_row inside a loop"]
    assert scan_violations("x = [ws.max_column for c in cols]\n") == ["<src>:1: .max_column inside a loop"]
    assert scan_violations("while ws.max_row < 3:\n    pass\n")
    assert scan_violations("for r in range(1, ws.max_row + 1):\n    ws.cell(r, 1)\n") == []
    assert scan_violations("n = ws.max_row\nfor r in range(n):\n    pass\n") == []


def test_the_guard_sees_the_other_whole_sheet_reads():
    # (review round 1 W10)
    assert scan_violations("for r in rs:\n    row = ws[r]\n") == ["<src>:2: ws[...] inside a loop"]
    assert scan_violations("for c, v in cells:\n    ws['G26'] = v\n") == []   # one cell by address
    assert scan_violations("for r in rs:\n    d = sheet.dimensions\n") == ["<src>:2: .dimensions inside a loop"]
    assert scan_violations("for r in rs:\n    for x in ws.iter_rows():\n        pass\n")
    # (review round 2 W6) without ``max_col`` openpyxl scans for ``max_column`` on every call
    assert scan_violations("for r in rs:\n    for x in ws.iter_rows(min_row=r, max_row=r):\n        pass\n")
    assert scan_violations("for r in rs:\n    for x in ws.iter_rows(min_row=r, max_row=r, max_col=9):\n"
                           "        pass\n") == []
    assert scan_violations("for r in rs:\n    ws.calculate_dimension()\n")


def test_a_non_sheet_range_can_say_so():
    assert scan_violations("for rng in merged:\n    end = rng.max_row  # scan-ok: a CellRange, not a sheet\n") == []
    assert scan_violations("for rng in merged:\n    end = rng.max_row\n")   # unmarked: flagged


@pytest.mark.parametrize("path", sorted((ROOT / "generators").glob("*.py")), ids=lambda p: p.name)
def test_no_generator_scans_a_whole_sheet_inside_a_loop(path):
    assert scan_violations(path.read_text(encoding="utf-8"), path.name) == []


def test_the_guard_sees_sheets_held_as_attributes_and_whole_columns():
    # (review round 2 W6)
    assert scan_violations("for r in rs:\n    n = self.ws.rows\n")
    assert scan_violations("for r in rs:\n    x = list(wb.active.iter_rows())\n")
    assert scan_violations("for r in rs:\n    row = wb['S'][r]\n")
    assert scan_violations("for r in rs:\n    col = ws['A']\n")
    assert scan_violations("for r in rs:\n    for c in ws.iter_cols():\n        pass\n")
    assert scan_violations("for r in rs:\n    v = ws['A1']\n") == []
