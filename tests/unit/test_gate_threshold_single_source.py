"""게이트 임계는 **한 곳에만** 적혀 있다 (R42 N6).

평가기(`evaluator.py`)가 판정에 쓰는 숫자와 어드바이저(`advisor.py`)가 제안에 쓰는 숫자가
따로 적혀 있으면, 한쪽만 고친 순간부터 두 화면이 다른 "게이트 기준" 을 말한다. 실측 시점에
**17쌍**이 값만 우연히 같은 채 복제돼 있었다. 이 가드는 그 복제가 돌아오는 것을 막는다.

⚠ 이 파일이 잡는 것은 "값이 다르다" 가 아니라 **"숫자가 두 번 적혀 있다"** 다. 값 불일치는
증상이고, 복제가 원인이다(값이 같을 때 통과시키면 가드가 아무것도 안 막는다).
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Set, Tuple

import pytest

from workflow.quality import advisor as A
from workflow.quality import thresholds as T

ROOT = Path(__file__).resolve().parents[2]
EVALUATOR = ROOT / "workflow" / "quality" / "evaluator.py"
ADVISOR = ROOT / "workflow" / "quality" / "advisor.py"

# 어드바이저 표 ↔ 임계 축은 **`advisor.advice_for` 에서 읽는다** — 여기 손으로 적지 않는다.
#
# ⚠ 첫 판에서는 이 자리에 매핑을 복제했다가, 축을 어긋내는 뮤턴트가 773건 전부 통과했다.
# 가드가 "판정 복제 금지" 를 검사하면서 자기가 복제를 하고 있었다.
def _axis_by_table() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for doc_type in A._ADVICE_BY_DOC_TYPE:
        rules, axis = A.advice_for(doc_type)
        if axis == "uds":
            continue          # UDS 는 config 정본(`threshold_key`)이라 이 표의 대상이 아니다
        for name in dir(A):
            if name.endswith("_ADVICE") and getattr(A, name) is rules:
                out[name] = axis
    return out


_AXIS_BY_TABLE: Dict[str, str] = _axis_by_table()


def _evaluator_gate_calls() -> Set[Tuple[str, str]]:
    """`_metric(..., threshold=...)` 안에서 실제로 조회하는 (축, 지표) 전부."""
    found: Set[Tuple[str, str]] = set()
    for node in ast.walk(ast.parse(EVALUATOR.read_text("utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "_gt":
            continue
        if len(node.args) == 2 and all(isinstance(a, ast.Constant) for a in node.args):
            found.add((node.args[0].value, node.args[1].value))
    return found


def _evaluator_literal_thresholds() -> list:
    """`threshold=` 로 넘어가는 **숫자 리터럴** — 있으면 그게 두 번째 출처다."""
    out = []
    src = EVALUATOR.read_text("utf-8")
    tree = ast.parse(src)

    def _literals(node: ast.AST) -> list:
        # `100.0`, `100.0 if x else None`, `_gate_if_applicable(100.0, n)` 전부 본다.
        if isinstance(node, ast.Constant):
            return [node.value] if isinstance(node.value, (int, float)) else []
        if isinstance(node, ast.IfExp):
            return _literals(node.body) + _literals(node.orelse)
        if isinstance(node, ast.Call):
            return [v for a in node.args for v in _literals(a)]
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if fname != "_metric":
            continue
        for kw in node.keywords:
            if kw.arg == "threshold":
                for v in _literals(kw.value):
                    out.append((node.args[0].value if node.args else "?", v, node.lineno))
    return out


def test_evaluator_reads_thresholds_from_the_table_not_literals() -> None:
    leftovers = _evaluator_literal_thresholds()
    assert leftovers == [], (
        "평가기가 임계를 리터럴로 들고 있다 — thresholds.GATE_THRESHOLDS 로 옮길 것: "
        f"{leftovers}"
    )


def test_advisor_has_no_duplicated_gate_numbers() -> None:
    """어드바이저 규칙 표에 게이트 임계 숫자가 남아 있으면 안 된다(UDS 는 config 정본)."""
    src = ADVISOR.read_text("utf-8")
    dupes = []
    for node in ast.parse(src).body:
        if not isinstance(node, ast.Assign):
            continue
        name = getattr(node.targets[0], "id", "")
        if name not in _AXIS_BY_TABLE or not isinstance(node.value, ast.Dict):
            continue
        for k, v in zip(node.value.keys, node.value.values, strict=True):
            if not isinstance(k, ast.Constant) or not isinstance(v, ast.Dict):
                continue
            for rk, rv in zip(v.keys, v.values, strict=True):
                if (isinstance(rk, ast.Constant) and rk.value == "threshold"
                        and isinstance(rv, ast.Constant) and rv.value is not None):
                    dupes.append((name, k.value, rv.value))
    assert dupes == [], f"어드바이저에 임계 숫자가 복제돼 있다: {dupes}"


def test_every_table_rule_resolves_to_a_number() -> None:
    """`from_table` 규칙은 반드시 표에서 값이 나와야 한다 — None 이면 제안이 조용히 사라진다."""
    unresolved = []
    for table, axis in _AXIS_BY_TABLE.items():
        for metric, rule in getattr(A, table).items():
            if not rule.get("from_table"):
                continue
            if A._rule_threshold(rule, axis, metric) is None:
                unresolved.append((table, metric))
    assert unresolved == [], f"표에서 임계를 못 찾는 규칙: {unresolved}"


def test_gate_table_has_no_dead_entries() -> None:
    """표에만 있고 평가기가 안 쓰는 임계는 **판정에 쓰이지 않는 숫자**다 — 사실 행세를 막는다."""
    used = _evaluator_gate_calls()
    declared = {(axis, m) for axis, d in T.GATE_THRESHOLDS.items() for m in d}
    dead = sorted(declared - used)
    assert dead == [], f"평가기가 쓰지 않는 게이트 임계: {dead}"


def test_every_evaluator_lookup_is_registered() -> None:
    """(리뷰 W1) 표에 없는 축을 조회하면 **프로덕션에서 기록이 통째로 사라진다**.

    `require_gate_threshold` 의 KeyError 는 `evaluate_*` → `_record_run_impl` →
    `record_run` 의 광범위 except 를 타고 `return -1` 이 된다 — 응답은 200 인데 그 실행이
    이력·보드에서 없어진다. 죽은 임계(위 테스트)보다 이쪽이 위험한데, 첫 판에서는 한쪽
    방향만 검사해 신규 미등록 조회를 그대로 통과시켰다(뮤테이션이 생존).
    """
    missing = sorted(_evaluator_gate_calls() - {(a, m) for a, d in T.GATE_THRESHOLDS.items() for m in d})
    assert missing == [], f"표에 등록되지 않은 임계 조회(런타임 KeyError): {missing}"
    # 조회가 실제로 값을 낸다는 것까지 — 표에 키만 있고 값이 깨진 경우를 막는다.
    for axis, metric in sorted(_evaluator_gate_calls()):
        assert isinstance(T.require_gate_threshold(axis, metric), float)


def test_axis_map_comes_from_the_advisor_not_a_copy() -> None:
    """축 매핑의 출처가 `advice_for` 임을 고정한다 — 이 파일이 다시 복제하면 실패한다."""
    assert _AXIS_BY_TABLE, "축 매핑이 비었다 — advisor.advice_for 를 못 읽었다"
    for table, axis in _AXIS_BY_TABLE.items():
        doc_types = [d for d in A._ADVICE_BY_DOC_TYPE
                     if A.advice_for(d)[0] is getattr(A, table)]
        assert doc_types, table
        for d in doc_types:
            assert A.advice_for(d)[1] == axis


def test_advisory_axis_is_not_a_gate_axis() -> None:
    """참고 임계는 게이트 표와 겹치면 안 된다 — 겹치면 어느 쪽이 판정인지 알 수 없다."""
    overlap = [(axis, m) for axis, d in T.ADVISORY_THRESHOLDS.items() for m in d
               if T.gate_threshold(axis, m) is not None]
    assert overlap == [], f"참고 임계가 게이트 표와 겹친다: {overlap}"


def test_missing_gate_threshold_raises_instead_of_silently_ungating() -> None:
    """표에 없는 축을 물으면 죽는다 — `None` 을 threshold 로 넘기면 무조건 통과가 된다."""
    with pytest.raises(KeyError):
        T.require_gate_threshold("sts", "no_such_metric")
    with pytest.raises(KeyError):
        T.require_gate_threshold("no_such_axis", "completeness_pct")
