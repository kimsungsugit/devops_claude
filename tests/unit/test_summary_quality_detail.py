"""quality-detail — 함수단위 커버리지 worst 정렬·미커버·섹션별 available 분리."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _prep(tmp_path: Path, *, detail: bool = True, rag: bool = True) -> dict:
    root = tmp_path / "build_125"
    rd = root / "report"
    rd.mkdir(parents=True)
    summary: dict = {}
    if detail:
        summary["vectorcast_detail"] = {
            "aggregate_coverage": {
                "ok": True,
                "entries": [
                    {"unit": "u1", "subprogram": "full_fn", "ccn": 3,
                     "statements": {"covered": 10, "total": 10, "rate": 100.0},
                     "branches": {"covered": 4, "total": 4, "rate": 100.0}},
                    {"unit": "u1", "subprogram": "half_fn", "ccn": 8,
                     "statements": {"covered": 5, "total": 10, "rate": 50.0},
                     "branches": {"covered": 1, "total": 6, "rate": 16.7}},
                    {"unit": "u2", "subprogram": "zero_fn", "ccn": 22,
                     "statements": {"covered": 0, "total": 40, "rate": 0.0},
                     "branches": {"covered": 0, "total": 18, "rate": 0.0}},
                ],
            }
        }
    (rd / "analysis_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    if rag:
        (rd / "vectorcast_rag.json").write_text(json.dumps({
            "failures": [{"testcase": "TC_zero_1", "result": "FAIL"}],
        }), encoding="utf-8")
    return {"build_root": str(root), "build_number": 125, "reports_dir": str(rd), "mtime": 0}


def test_quality_detail_worst_sorted_and_totals(tmp_path, monkeypatch):
    from backend.routers import summary_insight as si

    meta = _prep(tmp_path)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    resp = si.summary_quality_detail({"job_url": "http://j/"})
    assert resp["available"] is True and resp["build_number"] == 125
    fc = resp["function_coverage"]
    assert fc["available"] is True
    assert fc["totals"]["functions"] == 3
    assert fc["totals"]["fully_covered"] == 1
    assert fc["totals"]["uncovered"] == 1
    assert fc["totals"]["statements"] == {"covered": 15, "total": 60, "rate": 25.0}
    # worst는 rate 오름차순 — zero_fn 먼저
    assert [w["subprogram"] for w in fc["worst"]] == ["zero_fn", "half_fn", "full_fn"]
    assert fc["uncovered"] == [{"unit": "u2", "subprogram": "zero_fn"}]
    ft = resp["failed_testcases"]
    assert ft["available"] is True and ft["count"] == 1
    assert ft["items"][0]["testcase"] == "TC_zero_1"


def test_quality_detail_sections_independent(tmp_path, monkeypatch):
    """vectorcast_detail 부재여도 실패 TC 섹션은 산다(역도 성립) — 증거부재≠0."""
    from backend.routers import summary_insight as si

    meta = _prep(tmp_path, detail=False, rag=True)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    resp = si.summary_quality_detail({"job_url": "http://j/"})
    assert resp["function_coverage"]["available"] is False
    # L1: 소스가 detail 한 종이 아니게 되면서 reason 명칭 일반화(진단 문자열 — 프론트 분기 없음)
    assert resp["function_coverage"]["reason"] == "no_function_coverage_source"
    assert resp["failed_testcases"]["available"] is True

    meta2 = _prep(tmp_path / "x", detail=True, rag=False)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta2])
    resp2 = si.summary_quality_detail({"job_url": "http://j/"})
    assert resp2["function_coverage"]["available"] is True
    assert resp2["failed_testcases"]["available"] is False


def test_quality_detail_no_cached_build(monkeypatch):
    from backend.routers import summary_insight as si

    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [])
    resp = si.summary_quality_detail({"job_url": "http://j/"})
    assert resp["available"] is False and resp["reason"] == "no_cached_build"


# ── K1: _ccn_map — vectorcast_detail(빈 규약) → vectorcast.ut/it_metrics 폴백 ──

def test_ccn_map_vectorcast_metrics_fallback(tmp_path):
    from backend.routers.summary_insight import _ccn_map

    (tmp_path / "analysis_summary.json").write_text(json.dumps({
        "vectorcast_detail": {},  # 실측: 전 캐시 빌드에서 빈 dict — 구 코드는 여기서 {} 반환
        "vectorcast": {
            "ut_metrics": {"entries": [{"subprogram": "f1", "ccn": 3}]},
            "it_metrics": {"entries": [{"subprogram": "f1", "ccn": 5}, {"subprogram": "g", "ccn": 2}]},
        },
    }), encoding="utf-8")
    assert _ccn_map(tmp_path) == {"f1": 5, "g": 2}  # UT/IT 병합, 중복 함수는 max


def test_ccn_map_detail_takes_precedence_when_populated(tmp_path):
    from backend.routers.summary_insight import _ccn_map

    (tmp_path / "analysis_summary.json").write_text(json.dumps({
        "vectorcast_detail": {"aggregate_coverage": {"entries": [{"subprogram": "d", "ccn": 9}]}},
        "vectorcast": {"ut_metrics": {"entries": [{"subprogram": "f1", "ccn": 3}]}},
    }), encoding="utf-8")
    assert _ccn_map(tmp_path) == {"d": 9}  # 구 규약이 채워져 있으면 그대로(폴백 미발동)


# ── L1: 소스 폴백·IT 분리·rag 경로 교정 ─────────────────────────────────────

def _prep_metrics(tmp_path: Path, *, rag_nested: bool = False) -> dict:
    """실측 규약: vectorcast_detail은 빈 {} — 실데이터는 vectorcast.ut/it_metrics.entries."""
    root = tmp_path / "build_26"
    rd = root / "report"
    rd.mkdir(parents=True)
    summary = {
        "vectorcast_detail": {},
        "vectorcast": {
            "ut_metrics": {"entries": [
                {"unit": "a.c", "subprogram": "f_full", "ccn": 2,
                 "statements": {"covered": 8, "total": 8, "rate": 1.0},
                 "branches": {"covered": 2, "total": 2, "rate": 1.0}},
                {"unit": "a.c", "subprogram": "f_half", "ccn": 5,
                 "statements": {"covered": 5, "total": 10, "rate": 0.5},
                 "branches": {"covered": 1, "total": 4, "rate": 0.25}},
            ]},
            "it_metrics": {"entries": [
                {"unit": "b.c'1", "subprogram": "g_it", "ccn": 1,
                 "functions": {"covered": 0, "total": 1, "rate": 0.0},
                 "function_calls": {"covered": 0, "total": 3, "rate": 0.0}},
            ]},
        },
    }
    (rd / "analysis_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    if rag_nested:
        sub = rd / "vectorcast_rag"
        sub.mkdir()
        (sub / "vectorcast_rag.json").write_text(json.dumps({"failures": []}), encoding="utf-8")
    return {"build_root": str(root), "build_number": 26, "reports_dir": str(rd), "mtime": 0}


def test_fallback_to_vectorcast_metrics_available(tmp_path, monkeypatch):
    """회귀 고정 핵심: detail 빈 {}여도 ut_metrics로 available:true (이전엔 전 빌드 false)."""
    from backend.routers import summary_insight as si

    meta = _prep_metrics(tmp_path)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    resp = si.summary_quality_detail({"job_url": "http://j/"})
    fc = resp["function_coverage"]
    assert fc["available"] is True and fc["source"] == "vectorcast_metrics"
    assert fc["totals"]["statements"] == {"covered": 13, "total": 18, "rate": 72.2}
    assert fc["totals"]["branches"] == {"covered": 3, "total": 6, "rate": 50.0}  # L1: 분기 totals 신설
    assert [w["subprogram"] for w in fc["worst"]] == ["f_half", "f_full"]


def test_it_coverage_section_independent_and_unit_normalized(tmp_path, monkeypatch):
    from backend.routers import summary_insight as si

    meta = _prep_metrics(tmp_path)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    resp = si.summary_quality_detail({"job_url": "http://j/"})
    it = resp["it_coverage"]
    assert it["available"] is True
    assert it["totals"]["functions"] == {"covered": 0, "total": 1, "rate": 0.0}
    assert it["totals"]["function_calls"]["total"] == 3
    assert it["worst"][0]["unit"] == "b.c"  # env 인스턴스 접미사('1) 정규화
    # 구 규약(detail)만 있는 빌드는 IT 섹션이 정직하게 부재
    meta2 = _prep(tmp_path / "x", detail=True, rag=False)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta2])
    resp2 = si.summary_quality_detail({"job_url": "http://j/"})
    assert resp2["it_coverage"] == {"available": False, "reason": "no_it_metrics"}


def test_fold_repeated_measurements_not_summed(tmp_path, monkeypatch):
    """환경별 반복 측정을 합산하면 분모가 배수로 부푼다 — 접어서 집계해야 한다.

    실측 회귀 고정(KJPDS02_PV): IT 712행 = 259함수 × 최대 5환경인데 합산하면 구문 분모가
    2854 → 7438(2.61배)이 되어 커버리지가 31.6%로 허위 하락했다. `s_System_MainLoop`는
    covered=[0,4,4,0,0]/total=[4,4,4,4,4] — 합산 8/20(40%)은 오답이고 접으면 4/4(100%).
    """
    from backend.routers import summary_insight as si

    root = tmp_path / "build_9"
    rd = root / "report"
    rd.mkdir(parents=True)
    # 같은 (unit, subprogram)이 3환경에서 측정 — 값이 서로 다르다(divergent).
    it_entries = [
        {"unit": "m.c", "subprogram": "loop", "statements": {"covered": c, "total": 4}}
        for c in (0, 4, 4)
    ]
    it_entries.append({"unit": "m.c", "subprogram": "solo", "statements": {"covered": 1, "total": 2}})
    ut_entries = [
        {"unit": "m.c", "subprogram": "dup", "ccn": c,
         "statements": {"covered": s, "total": 10, "rate": s * 10.0},
         "branches": {"covered": 0, "total": 2}}
        for c, s in ((3, 2), (7, 9))
    ]
    (rd / "analysis_summary.json").write_text(json.dumps({"vectorcast": {
        "ut_metrics": {"entries": ut_entries}, "it_metrics": {"entries": it_entries},
    }}), encoding="utf-8")
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [
        {"build_root": str(root), "build_number": 9, "reports_dir": str(rd), "mtime": 0}])
    resp = si.summary_quality_detail({"job_url": "http://j/"})

    it = resp["it_coverage"]
    # 합산이면 8/16, 접으면 (4/4)+(1/2) = 5/6.
    assert it["totals"]["statements"] == {"covered": 5, "total": 6, "rate": 83.3}
    assert it["totals"]["entries"] == 2                      # 4행 → 2함수
    assert it["fold"]["raw_entries"] == 4 and it["fold"]["folded_entries"] == 2
    assert it["fold"]["duplicated_keys"] == 1 and it["fold"]["divergent_keys"] == 1
    assert it["fold"]["method"] == "max_covered_max_total"

    fc = resp["function_coverage"]
    assert fc["totals"]["functions"] == 1                     # 2행 → 1함수
    assert fc["totals"]["statements"] == {"covered": 9, "total": 10, "rate": 90.0}
    assert fc["totals"]["fully_covered"] == 0
    assert fc["worst"][0]["ccn"] == 7                         # ccn은 최대값 채택
    assert fc["worst"][0]["measurements"] == 2 and fc["worst"][0]["divergent"] is True
    # 최악값은 버리지 않는다 — '재검증할 함수' 판단 근거.
    assert fc["worst"][0]["statements"]["worst_covered"] == 2


def test_fold_absent_when_no_duplicates(tmp_path, monkeypatch):
    """중복이 없으면 접힘 통계는 0 — 정상 데이터에 불필요한 각주를 띄우지 않는다."""
    from backend.routers import summary_insight as si

    meta = _prep(tmp_path)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    fc = si.summary_quality_detail({"job_url": "http://j/"})["function_coverage"]
    assert fc["fold"]["duplicated_keys"] == 0
    assert fc["fold"]["raw_entries"] == fc["fold"]["folded_entries"] == 3
    assert all("measurements" not in w for w in fc["worst"])


def test_rag_subfolder_path_regression(tmp_path, monkeypatch):
    """경로 버그 회귀 고정: 실물은 vectorcast_rag/ 하위폴더 — 이전엔 항상 available:false."""
    from backend.routers import summary_insight as si

    meta = _prep_metrics(tmp_path, rag_nested=True)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    resp = si.summary_quality_detail({"job_url": "http://j/"})
    ft = resp["failed_testcases"]
    assert ft["available"] is True and ft["count"] == 0
    assert ft["source_path"].replace("\\", "/").endswith("vectorcast_rag/vectorcast_rag.json")


# ── N1: SCM 입력 문서 폴백(빌드 우선) + IT 축 스키마 이원화 ────────────────

_SCM_PAYLOAD = {
    "available": True,
    "job_file": "job_impact_20260725_113538_slug_a.json",
    "generated_at": "2026-07-25T11:39:22+09:00",
    "merged_sources": 4,
    "complexity_rows": [{"function": "s_fn", "unit": "Lib_a", "complexity": 3}],
    "ut_entries": [
        {"unit": "Lib_a", "subprogram": "s_fn", "ccn": 3,
         "statements": {"covered": 2, "total": 4, "rate": 0.5},
         "branches": {"covered": 0, "total": 2, "rate": 0.0},
         "pairs": {"covered": 0, "total": 0, "rate": None}},
    ],
    # 실측 스키마: SCM IT엔 functions 축이 없다(구문/분기/호출) — 구 코드는 전 행을 skip했다.
    "it_entries": [
        {"unit": "Ap_b'1", "subprogram": "g_it", "ccn": 1,
         "statements": {"covered": 1, "total": 3, "rate": 0.333},
         "branches": {"covered": 1, "total": 1, "rate": 1.0},
         "function_calls": {"covered": 2, "total": 3, "rate": 0.667}},
    ],
    "failures": [{"testcase": "TC_scm_1"}],
    "test_summary": {"total": 5, "passed": 4, "failed": 1, "pass_rate": 0.8, "ut_rows": 4, "it_rows": 1},
}


def _prep_empty_build(tmp_path: Path) -> dict:
    """빌드 산출물에 함수 커버리지가 전혀 없는 상태(실측 KJPDS02_PV)."""
    root = tmp_path / "build_124"
    rd = root / "report"
    rd.mkdir(parents=True)
    (rd / "analysis_summary.json").write_text(json.dumps({"vectorcast_detail": {}}), encoding="utf-8")
    return {"build_root": str(root), "build_number": 124, "reports_dir": str(rd), "mtime": 0}


def test_scm_fallback_when_build_has_no_function_coverage(tmp_path, monkeypatch):
    from backend.routers import summary_insight as si

    meta = _prep_empty_build(tmp_path)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    monkeypatch.setattr(si, "_load_scm_function_entries", lambda job_url: dict(_SCM_PAYLOAD))
    resp = si.summary_quality_detail({"job_url": "http://j/"})
    fc = resp["function_coverage"]
    assert fc["available"] is True and fc["source"] == "scm_vcast_job"
    assert resp["coverage_source"] == "scm_vcast_job"
    assert resp["coverage_source_detail"]["job_file"].startswith("job_impact_")
    assert resp["coverage_source_detail"]["generated_at"] == "2026-07-25T11:39:22+09:00"
    assert fc["totals"]["statements"] == {"covered": 2, "total": 4, "rate": 50.0}
    # 빌드에 vectorcast_rag가 없으면 실패 TC도 SCM 이력으로 폴백
    ft = resp["failed_testcases"]
    assert ft["available"] is True and ft["source"] == "scm_vcast_job" and ft["count"] == 1
    assert ft["test_summary"]["pass_rate"] == 0.8


def test_build_source_takes_precedence_over_scm(tmp_path, monkeypatch):
    """사용자 결정 고정: 빌드 산출물이 있으면 커버리지는 SCM으로 넘어가지 않는다.

    (실패 TC 섹션은 별개 축이라 빌드에 vectorcast_rag가 없으면 SCM으로 폴백한다 —
    섹션별 독립 규약. 여기서 고정하는 것은 '커버리지 소스' 우선순위뿐이다.)
    """
    from backend.routers import summary_insight as si

    meta = _prep_metrics(tmp_path, rag_nested=True)  # 빌드에 실행 로그도 있어 SCM 경로 미발동
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    monkeypatch.setattr(si, "_load_scm_function_entries",
                        lambda job_url: pytest.fail("빌드 소스가 있는데 SCM을 조회했다"))
    resp = si.summary_quality_detail({"job_url": "http://j/"})
    assert resp["function_coverage"]["source"] == "vectorcast_metrics"
    assert resp["coverage_source"] == "vectorcast_metrics"
    assert resp["failed_testcases"]["source"] == "build_artifact"


def test_it_axes_dynamic_for_scm_schema(tmp_path, monkeypatch):
    """SCM IT엔 functions가 없다 — 구 코드는 전 행 skip이었고, 이제 축별로 집계한다."""
    from backend.routers import summary_insight as si

    meta = _prep_empty_build(tmp_path)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    monkeypatch.setattr(si, "_load_scm_function_entries", lambda job_url: dict(_SCM_PAYLOAD))
    it = si.summary_quality_detail({"job_url": "http://j/"})["it_coverage"]
    assert it["available"] is True
    assert it["metrics_present"] == {"functions": False, "function_calls": True,
                                     "statements": True, "branches": True}
    assert it["totals"]["functions"] is None          # 부재 축은 0/0이 아니라 None
    assert it["totals"]["statements"] == {"covered": 1, "total": 3, "rate": 33.3}
    assert it["totals"]["function_calls"]["total"] == 3
    assert it["worst"][0]["unit"] == "Ap_b"           # env 인스턴스 접미사 정규화 유지


def test_it_axes_dynamic_for_build_schema(tmp_path, monkeypatch):
    """빌드 IT(진입/호출)는 구문/분기가 없다 — 회귀 고정."""
    from backend.routers import summary_insight as si

    meta = _prep_metrics(tmp_path)
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    it = si.summary_quality_detail({"job_url": "http://j/"})["it_coverage"]
    assert it["metrics_present"] == {"functions": True, "function_calls": True,
                                     "statements": False, "branches": False}
    assert it["totals"]["functions"] == {"covered": 0, "total": 1, "rate": 0.0}
    assert it["totals"]["statements"] is None


def test_ccn_map_scm_fallback(tmp_path, monkeypatch):
    """ccn 3차 폴백 — 없으면 아키텍처 핫스팟이 전원 loc_proxy로 떨어진다."""
    from backend.routers import summary_insight as si

    (tmp_path / "analysis_summary.json").write_text(
        json.dumps({"vectorcast_detail": {}}), encoding="utf-8")
    # 실제 헬퍼와 같은 계약: job_url이 비면 조회하지 않고 None
    monkeypatch.setattr(si, "_load_scm_function_entries",
                        lambda job_url: dict(_SCM_PAYLOAD) if job_url else None)
    assert si._ccn_map(tmp_path, job_url="http://j/") == {"s_fn": 3, "g_it": 1}
    assert si._ccn_map(tmp_path) == {}  # job_url 없으면 폴백 없음(호출 계약 유지)


def test_rag_deep_rglob_latest_mtime(tmp_path, monkeypatch):
    import os

    from backend.routers import summary_insight as si

    meta = _prep_metrics(tmp_path)
    rd = Path(meta["reports_dir"])
    old = rd / "local_upload" / "a" / "vectorcast_rag.json"
    new = rd / "local_upload" / "b" / "vectorcast_rag.json"
    for i, p in enumerate([old, new]):
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"failures": [{"testcase": f"T{i}"}]}), encoding="utf-8")
    os.utime(old, (1_000_000, 1_000_000))  # old를 과거로 — mtime 최신(new) 채택 검증
    monkeypatch.setattr(si, "list_cached_builds", lambda **k: [meta])
    resp = si.summary_quality_detail({"job_url": "http://j/"})
    ft = resp["failed_testcases"]
    assert ft["available"] is True and ft["items"][0]["testcase"] == "T1"
