"""SwDS 파티션 맵 병합은 한 규칙이다 (R52 N39 · 리뷰 W2/W3).

## 왜

`generators/suts.py` 는 first-wins(필드별)이고 UDS 세 경로(jenkins 비동기 `backend/helpers/uds.py` · local 동기/비동기
`backend/routers/local.py`)는 `dict.update`(뒤 문서가 통째로 이김)였고, `requirements`·`sts`·`docx_builder` 엔 같은 루프의
손복제가 셋 더 있었다(리뷰 W3, 그중 하나는 새 키를 별칭으로 넣었다) — 같은 파티션 키가 두 SwDS 에 있으면 문서 종류에 따라
다른 ASIL 이 실렸다. 이제 `report_gen.requirements._merge_sds_partition_map` 하나다: related/description 은 first-wins,
**asil 은 max**(이 저장소의 ASIL 병합 규칙 — `_build_uds_asil_map`·커밋 05cdd1f, 리뷰 W2), 갈림은 WARNING.

⚠ `generators/sits.py::_load_default_sds_map` 은 병합이 아니라 "첫 비어 있지 않은 문서 하나" 정책이라 대상이 아니다(형제
셋의 폴백 정책이 다르다 — R52 이월 N47).
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from report_gen import requirements as RQ
from report_gen.requirements import _merge_sds_partition_map

_ROOT = Path(RQ.__file__).resolve().parents[1]
_SCAN_DIRS = ("report_gen", "generators", "backend/helpers", "backend/routers", "backend/services", "workflow")


class TestMergeSemantics:
    def test_new_key_is_copied_not_aliased(self):
        src = {"swcom_01": {"asil": "B", "related": "SwCom_01", "kind": "component"}}
        merged: dict = {}
        _merge_sds_partition_map(merged, src)
        assert merged == src and merged["swcom_01"] is not src["swcom_01"]
        src["swcom_01"]["asil"] = "D"
        assert merged["swcom_01"]["asil"] == "B"

    def test_existing_fields_win_and_blanks_are_filled(self):
        merged = {"main": {"asil": "A", "related": "", "description": ""}}
        _merge_sds_partition_map(merged, {"main": {"asil": "QM", "related": "SwCom_35", "description": "copy"}})
        assert merged["main"] == {"asil": "A", "related": "SwCom_35", "description": "copy"}

    def test_incoming_blank_never_clears(self):
        merged = {"k": {"asil": "C", "related": "SwFn_1", "description": "d"}}
        _merge_sds_partition_map(merged, {"k": {"asil": "", "related": "", "description": ""}})
        assert merged["k"] == {"asil": "C", "related": "SwFn_1", "description": "d"}

    def test_differs_from_dict_update_on_collision(self):
        """`dict.update` 였다면 뒤 문서가 통째로 이긴다 — 그 차이가 이 라운드의 대상이다."""
        first = {"k": {"asil": "B", "related": "SwCom_02"}}
        second = {"k": {"asil": "QM", "related": "SwCom_09"}}
        merged: dict = {}
        _merge_sds_partition_map(merged, first)
        _merge_sds_partition_map(merged, second)
        updated: dict = {}
        updated.update(first)
        updated.update(second)
        assert merged["k"] == {"asil": "B", "related": "SwCom_02"}
        assert updated["k"]["asil"] == "QM"


class TestAsilIsMaxMerged:
    """(리뷰 W2) 안전 필드는 문서 나열 순서가 아니라 등급이 정한다 — 낮은 쪽을 택하면 under-report."""

    def test_higher_incoming_grade_wins_and_is_reported(self, caplog):
        merged = {"k": {"asil": "QM", "related": "SwCom_02"}}
        with caplog.at_level(logging.WARNING, logger="report_generator"):
            n = _merge_sds_partition_map(merged, {"k": {"asil": "ASIL B", "related": "SwCom_09"}})
        assert n == 1
        assert merged["k"]["asil"] == "ASIL B", "문서 표기 그대로 높은 등급으로"
        assert merged["k"]["related"] == "SwCom_02", "related 는 first-wins 그대로"
        assert any("ASIL 이 갈려" in r.getMessage() for r in caplog.records), "갈림은 침묵하지 않는다"

    def test_lower_incoming_grade_does_not_downgrade_but_still_counts(self):
        merged = {"k": {"asil": "C"}}
        assert _merge_sds_partition_map(merged, {"k": {"asil": "A"}}) == 1
        assert merged["k"]["asil"] == "C"

    def test_placeholders_are_not_opinions(self):
        merged = {"k": {"asil": "TBD"}}
        assert _merge_sds_partition_map(merged, {"k": {"asil": "A"}}) == 0 and merged["k"]["asil"] == "A"
        merged = {"k": {"asil": "A"}}
        assert _merge_sds_partition_map(merged, {"k": {"asil": "TBD"}}) == 0 and merged["k"]["asil"] == "A"
        merged = {"k": {"asil": ""}}
        assert _merge_sds_partition_map(merged, {"k": {"asil": "QM"}}) == 0 and merged["k"]["asil"] == "QM"

    def test_same_grade_in_another_spelling_is_not_a_conflict(self, caplog):
        merged = {"k": {"asil": "ASIL A"}}
        with caplog.at_level(logging.WARNING, logger="report_generator"):
            assert _merge_sds_partition_map(merged, {"k": {"asil": "A"}}) == 0
        assert merged["k"]["asil"] == "ASIL A" and not caplog.records

    def test_no_conflict_returns_zero_without_warning(self, caplog):
        merged: dict = {}
        with caplog.at_level(logging.WARNING, logger="report_generator"):
            assert _merge_sds_partition_map(merged, {"a": {"asil": "B"}, "b": {"asil": "QM"}}) == 0
        assert not caplog.records


def _calls_named(tree: ast.AST, name: str):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name]


def _calls_inside_for_loops(tree: ast.AST, name: str):
    """`for` 루프 본문 안의 `name(...)` 호출 — 문서 여러 개를 도는 자리가 곧 병합 자리다."""
    found = []

    def visit(node, in_loop):
        for child in ast.iter_child_nodes(node):
            child_in_loop = in_loop or isinstance(child, (ast.For, ast.AsyncFor))
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == name and in_loop:
                found.append(child)
            visit(child, child_in_loop)

    visit(tree, False)
    return found


class TestSingleSource:
    def test_suts_and_sts_use_the_shared_helper(self):
        from generators import sts, suts
        assert suts._merge_sds_partition_map is _merge_sds_partition_map
        assert sts._merge_sds_partition_map is _merge_sds_partition_map

    @pytest.mark.parametrize("rel,loop_calls", [
        ("backend/helpers/uds.py", 1),
        ("backend/routers/local.py", 2),
        ("generators/suts.py", 1),        # + 루프 밖 1(`load_sds_map_from`, 단일 문서 — 그래도 헬퍼 경유)
        ("generators/sts.py", 1),         # + 루프 밖 1(단일 문서를 그대로 쓰는 자리 — 병합 아님)
        ("report_gen/requirements.py", 1),
        ("report_gen/docx_builder.py", 1),
    ])
    def test_every_looped_partition_extract_is_merged_through_the_helper(self, rel, loop_calls):
        src = (_ROOT / rel).read_text(encoding="utf-8")
        assert ".update(_extract_sds_partition_map(" not in src, f"{rel}: dict.update 병합이 남아 있다"
        tree = ast.parse(src)
        looped = _calls_inside_for_loops(tree, "_extract_sds_partition_map")
        assert len(looped) == loop_calls, f"{rel}: 루프 안 추출 호출 수가 바뀌었다 — 새 자리도 병합 헬퍼를 거치는지 볼 것"
        wrapped = {id(m.args[1]) for m in _calls_named(tree, "_merge_sds_partition_map") if len(m.args) == 2}
        for call in looped:
            assert id(call) in wrapped, f"{rel}:{call.lineno} 루프 안 추출 결과가 병합 헬퍼를 거치지 않는다"

    def test_no_hand_copied_merge_loop_anywhere(self):
        """(리뷰 W3) 옛 first-wins 루프의 리터럴이 스캔 디렉터리 어디에도 없다 — 헬퍼 밖에서 다시 복제되면 여기서 걸린다."""
        needle = 'for field in ("asil", "related", "description")'
        hits = []
        for d in _SCAN_DIRS:
            for py in (_ROOT / d).rglob("*.py"):
                if any(part in ("venv", ".venv", "node_modules", "site-packages") for part in py.parts):
                    continue
                if needle in py.read_text(encoding="utf-8", errors="ignore"):
                    hits.append(str(py.relative_to(_ROOT)))
        assert hits == [], f"손복제 병합 루프가 다시 생겼다: {hits}"
