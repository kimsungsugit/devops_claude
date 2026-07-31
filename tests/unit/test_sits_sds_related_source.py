# tests/unit/test_sits_sds_related_source.py
"""SITS Related ID 의 SDS 보강 — 출처와 실적을 보이게 한다.

## 실측 (2026-07-31, 고치기 전)

`collect_integration_flows` 는 Related ID 의 SwCom 축을 SDS 맵에서 채우려 했는데,
**두 겹으로 깨져 있었고 둘 다 침묵했다**:

| # | 결함 | 실측 |
|---|---|---|
| S1 | 프로젝트 SDS 를 쓸 방법이 **없었다** | `sds_map` 파라미터 자체가 없어 `_load_default_sds_map()`(저장소 `docs/` 글롭 = HDPDM01) 고정. `generate_sits` 는 `sds_docx_path` 를 **받고 있었는데** 흐름까지 전달되지 않았다 |
| S2 | 필드명이 스키마에 **없었다** | 맵 값 스키마는 `{kind, description, related, asil, component_description, canonical}` 인데 코드는 `entry.get("swcom") or entry.get("component")` 를 읽었다 → 항상 `None` |
| — | 그 사실이 안 보였다 | 전체가 `except Exception: pass` 안. 실측 763항목 중 `swcom`/`component` 보유 **0개** |

즉 이 보강은 **한 건도 산출한 적이 없다.** 5.1MB 짜리 남의 프로젝트 문서를 파싱하고도
결과는 0이며, 아무 표면에도 안 나타났다.

`sts.py::_lookup_sds_related_ids` 는 같은 맵에서 **실재 필드 `related`** 를 읽는다 —
세 생성기가 같은 맵을 서로 다르게 읽고 있었다.

## 이 라운드에서 하지 않은 것

**대체 필드를 추측하지 않았다.** 틀린 SwCom 을 추적성 열에 넣는 건 0건보다 나쁘다.
대신 ①호출자가 프로젝트 SDS 를 줄 수 있게 하고 ②0 을 **보고**한다.
SUTS 가 같은 결함을 이미 고쳐 뒀으므로(`suts._resolve_sds_map`) 그 헬퍼를 **재사용**한다.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from generators import sits

_SITS_SRC = Path(sits.__file__)


def _flow_payload():
    """교차모듈 호출 1건 — 흐름 후보 자격은 `calls_list` + 다른 module 의 callee 다."""
    return {
        "F1": {"name": "Task_10ms", "module_name": "app.c",
               "calls_list": ["Sub_Read", "Sub_Write"],
               "inputs": ["u8 a"], "outputs": ["u8 b"], "asil": "B", "related": "SwTR_0101"},
        "F2": {"name": "Sub_Read", "module_name": "drv.c", "calls_list": [],
               "inputs": [], "outputs": [], "asil": "B"},
        "F3": {"name": "Sub_Write", "module_name": "drv.c", "calls_list": [],
               "inputs": [], "outputs": [], "asil": "B"},
    }


# --------------------------------------------------------------
# S1 — 호출자가 프로젝트 SDS 를 줄 수 있어야 한다
# --------------------------------------------------------------

class TestCallerCanSupplySds:
    def test_supplied_map_is_used_and_reported(self):
        """뮤테이션: `sds_map` 파라미터를 없애고 무조건 폴백시키면 실패."""
        stats = {}
        flows = sits.collect_integration_flows(
            _flow_payload(), max_flows=10, stats_out=stats,
            sds_map={"Task_10ms": {"swcom": "SwCom_07"}})
        assert stats["sds_source"] == "argument"
        assert stats["sds_swcom_hits"] == 1
        assert "SwCom_07" in flows[0]["related_ids"]

    def test_fallback_is_labelled_not_silent(self):
        """폴백은 **저장소 docs/ 글롭(프로젝트 무관)** 이라는 사실이 남아야 한다."""
        stats = {}
        sits.collect_integration_flows(_flow_payload(), max_flows=10, stats_out=stats)
        assert stats["sds_source"] == "repo_docs_glob"

    def test_empty_map_is_honoured_not_replaced_by_repo_glob(self):
        """빈 맵을 **명시**한 것과 안 준 것은 다르다 — 빈 맵을 저장소 문서로 바꾸지 않는다."""
        stats = {}
        sits.collect_integration_flows(_flow_payload(), max_flows=10,
                                       stats_out=stats, sds_map={})
        assert stats["sds_source"] == "argument"
        assert stats["sds_map_entries"] == 0

    def test_generate_sits_wires_the_project_sds(self):
        """`generate_sits` 가 받은 `sds_docx_path` 가 흐름 수집까지 **도달**해야 한다.

        파라미터만 만들고 배선하지 않으면 결함은 그대로다 — 이 저장소가 겪은
        "게이트는 있는데 발화하지 않음" 을 여기서 막는다.
        뮤테이션: 호출부의 `sds_map=_project_sds_map` 를 지우면 실패.
        """
        tree = ast.parse(_SITS_SRC.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "generate_sits")
        wired = False
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "collect_integration_flows"):
                wired = any(kw.arg == "sds_map" for kw in node.keywords)
        assert wired, "generate_sits 가 sds_map 을 흐름 수집으로 전달하지 않는다"

    def test_reuses_suts_resolver_instead_of_duplicating(self):
        """SUTS 가 이미 고친 판정을 **재사용**한다 — 복제하면 한쪽만 고쳐진다."""
        src = _SITS_SRC.read_text(encoding="utf-8")
        assert "from generators.suts import _resolve_sds_map" in src


# --------------------------------------------------------------
# S2 — 0 건이 보여야 한다
# --------------------------------------------------------------

class TestZeroIsReported:
    def test_counters_are_emitted(self):
        """뮤테이션: `stats_out.update({... sds_* ...})` 를 지우면 실패."""
        stats = {}
        sits.collect_integration_flows(_flow_payload(), max_flows=10,
                                       stats_out=stats, sds_map={"x": {"swcom": "S1"}})
        for key in ("sds_source", "sds_map_entries", "sds_lookups",
                    "sds_key_hits", "sds_swcom_hits"):
            assert key in stats, f"{key} 가 보고되지 않는다"

    def test_lookups_counted_even_when_nothing_matches(self):
        """조회는 했는데 0건인 것과 조회조차 안 한 것은 다르다."""
        stats = {}
        sits.collect_integration_flows(_flow_payload(), max_flows=10,
                                       stats_out=stats, sds_map={"다른함수": {"swcom": "S1"}})
        assert stats["sds_lookups"] == 1
        assert stats["sds_key_hits"] == 0
        assert stats["sds_swcom_hits"] == 0

    def test_zero_yield_warns(self, caplog):
        """조회했는데 산출 0 이면 **경고**한다 — 침묵하면 "동작한다" 로 읽힌다.

        뮤테이션: 경고 블록을 지우면 실패.
        """
        with caplog.at_level(logging.WARNING, logger="generators.sits"):
            sits.collect_integration_flows(_flow_payload(), max_flows=10,
                                           stats_out={}, sds_map={"nope": {"swcom": "S"}})
        msg = " ".join(r.getMessage() for r in caplog.records)
        assert "0건" in msg and "SwCom" in msg

    def test_no_warning_when_enrichment_works(self, caplog):
        """음성 대조군 — 정상 동작 시엔 경고하지 않는다(경고 피로 방지)."""
        with caplog.at_level(logging.WARNING, logger="generators.sits"):
            sits.collect_integration_flows(_flow_payload(), max_flows=10,
                                           stats_out={}, sds_map={"Task_10ms": {"swcom": "S7"}})
        msgs = [r.getMessage() for r in caplog.records if "0건" in r.getMessage()]
        assert not msgs

    def test_lookup_failure_is_logged_not_swallowed(self):
        """`except Exception: pass` 가 되살아나지 않아야 한다."""
        tree = ast.parse(_SITS_SRC.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "collect_integration_flows")
        silent = [h.lineno for h in ast.walk(fn)
                  if isinstance(h, ast.ExceptHandler)
                  and len(h.body) == 1 and isinstance(h.body[0], ast.Pass)]
        assert not silent, f"침묵 except 가 되살아났다: {silent}"


# --------------------------------------------------------------
# 측정된 사실의 기록 — 저장소 폴백 맵은 SwCom 을 못 준다
# --------------------------------------------------------------

class TestMeasuredSchemaGap:
    def test_repo_fallback_map_has_no_swcom_field(self):
        """실측 기록 — 저장소 폴백 맵 763항목 중 `swcom`/`component` 보유 **0개**.

        코드가 읽는 필드가 스키마에 없어 이 보강은 한 번도 산출하지 못했다.
        대체 필드는 **추측하지 않았다**(틀린 SwCom 은 0건보다 나쁘다).
        스키마가 바뀌어 필드가 생기면 여기서 실패하므로, 그때 보강을 되살리면 된다.
        """
        m = sits._load_default_sds_map()
        if not m:
            pytest.skip("저장소 docs/ 에 SDS 문서가 없다 — 이 환경에선 대조 불가")
        with_swcom = sum(1 for v in m.values()
                         if isinstance(v, dict) and (v.get("swcom") or v.get("component")))
        assert with_swcom == 0, (
            f"폴백 맵에 swcom/component 가 {with_swcom}건 생겼다 — "
            "보강 필드 매핑을 되살릴 시점이다"
        )
