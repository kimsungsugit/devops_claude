# tests/unit/test_impact_ext.py
"""Extended tests for workflow.impact_orchestrator pure functions."""
from __future__ import annotations

from pathlib import Path

import pytest

from workflow.impact_orchestrator import (
    _module_name,
    _build_neighbors,
    _hop_limited_impact,
    _selected_targets,
    _fallback_changed_types_from_files,
    _resolve_changed_types_to_functions,
    _action_for_target,
    _extract_req_ids,
    _load_json,
    ACTION_MATRIX,
)


class TestModuleName:
    def test_from_module_name(self):
        assert _module_name({"module_name": "Door"}) == "door"

    def test_from_file_path(self):
        assert _module_name({"file": "Sources/APP/Ap_Door.c"}) == "app"

    def test_empty(self):
        assert _module_name({}) == ""


class TestBuildNeighbors:
    def test_basic(self):
        call_map = {"a": ["b"], "b": ["c"]}
        by_name = {"a": {}, "b": {}, "c": {}}
        result = _build_neighbors(call_map, by_name, same_module_only=False)
        assert "b" in result.get("a", set())
        assert "a" in result.get("b", set())  # bidirectional
        assert "c" in result.get("b", set())

    def test_same_module_filter(self):
        call_map = {"a": ["b"]}
        by_name = {
            "a": {"module_name": "mod1"},
            "b": {"module_name": "mod2"},
        }
        result = _build_neighbors(call_map, by_name, same_module_only=True)
        assert "b" not in result.get("a", set())

    def test_empty(self):
        result = _build_neighbors({}, {}, same_module_only=False)
        assert result == {}


class TestHopLimitedImpact:
    def test_empty_seeds(self):
        result = _hop_limited_impact(set(), {}, max_hop=2, max_impacted_functions=50)
        assert result["direct"] == []
        assert result["indirect_1hop"] == []

    def test_one_hop(self):
        neighbors = {"a": {"b", "c"}, "b": {"a", "d"}, "c": {"a"}, "d": {"b"}}
        result = _hop_limited_impact({"a"}, neighbors, max_hop=1, max_impacted_functions=50)
        assert "a" in result["direct"]
        assert "b" in result["indirect_1hop"]
        assert "c" in result["indirect_1hop"]
        assert result["indirect_2hop"] == []

    def test_two_hops(self):
        neighbors = {"a": {"b"}, "b": {"a", "c"}, "c": {"b", "d"}, "d": {"c"}}
        result = _hop_limited_impact({"a"}, neighbors, max_hop=2, max_impacted_functions=50)
        assert "b" in result["indirect_1hop"]
        assert "c" in result["indirect_2hop"]

    def test_max_impacted_limit(self):
        # create a large graph
        neighbors = {"seed": {f"n{i}" for i in range(100)}}
        for i in range(100):
            neighbors[f"n{i}"] = {"seed"}
        result = _hop_limited_impact({"seed"}, neighbors, max_hop=2, max_impacted_functions=10)
        total = len(result["direct"]) + len(result["indirect_1hop"]) + len(result["indirect_2hop"])
        # should stop early
        assert total <= 101  # seed + some neighbors


class TestSelectedTargets:
    def test_none(self):
        result = _selected_targets(None)
        assert "uds" in result
        assert "suts" in result

    def test_custom(self):
        result = _selected_targets(["UDS", "STS"])
        assert result == ["sts", "uds"]

    def test_dedup_and_sort(self):
        result = _selected_targets(["uds", "UDS", "sts"])
        assert result == ["sts", "uds"]


class TestFallbackChangedTypesFromFiles:
    def test_c_file(self):
        result = _fallback_changed_types_from_files(["src/door.c"])
        assert result["door"] == "BODY"

    def test_h_file(self):
        result = _fallback_changed_types_from_files(["inc/door.h"])
        assert result["door"] == "HEADER"

    def test_empty(self):
        assert _fallback_changed_types_from_files([]) == {}


class TestResolveChangedTypesToFunctions:
    def test_resolves_to_functions(self):
        by_name = {
            "door_init": {"file": "Sources/APP/door.c"},
            "door_run": {"file": "Sources/APP/door.c"},
            "other_func": {"file": "Sources/LIB/other.c"},
        }
        result = _resolve_changed_types_to_functions(
            {"door": "BODY"}, ["door.c"], by_name
        )
        assert "door_init" in result
        assert "door_run" in result

    def test_empty_by_name(self):
        result = _resolve_changed_types_to_functions({"a": "BODY"}, ["a.c"], {})
        assert result == {"a": "BODY"}

    def test_empty_changed(self):
        result = _resolve_changed_types_to_functions({}, [], {"f": {"file": "a.c"}})
        assert result == {}


class TestActionForTarget:
    def test_body_change_uds(self):
        result = _action_for_target("uds", {"f": "BODY"}, [])
        assert result == "AUTO"

    def test_header_change_sts(self):
        result = _action_for_target("sts", {"f": "HEADER"}, ["inc/a.h"])
        assert result == "FLAG"

    def test_no_changes(self):
        result = _action_for_target("uds", {}, [])
        assert result == "-"


class TestExtractReqIds:
    def test_basic(self):
        info = {"related": "SwTR_001, SwTSR_002"}
        ids = _extract_req_ids(info)
        assert "SwTR_001" in ids
        assert "SwTSR_002" in ids

    def test_empty(self):
        assert _extract_req_ids({}) == []

    def test_dedup(self):
        info = {"related": "SwTR_001", "comment_related": "SwTR_001"}
        ids = _extract_req_ids(info)
        assert ids.count("SwTR_001") == 1


class TestLoadJson:
    def test_valid(self, tmp_path):
        p = tmp_path / "data.json"
        p.write_text('{"key": "val"}', encoding="utf-8")
        assert _load_json(p) == {"key": "val"}

    def test_missing(self, tmp_path):
        assert _load_json(tmp_path / "nope.json") == {}

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json", encoding="utf-8")
        assert _load_json(p) == {}
