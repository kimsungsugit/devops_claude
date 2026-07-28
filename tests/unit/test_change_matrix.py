"""change_matrix — 베이스라인 고정 → 각 빌드의 누적 변화(change-log 비의존).

핵심 계약:
- 동일 트리는 셀 하나를 공유하고, 베이스라인과 바이트 동일한 빌드는 **파싱 없이** 함수 0 확정
- 함수 미계산은 0이 아니라 null + reason (ISO 정직성)
- 셀 캐시는 조인(커버리지/ASIL) 무관 — 새 빌드가 들어와도 무효화되지 않는다
- 셀 캐시 파일명이 `summary_baseline_diff_*` 글롭에 걸리면 test-design의 '변경 축'이 오염된다
"""
from __future__ import annotations

from pathlib import Path

import pytest

BASE_FILES = {
    "APP/a.c": "void keep_fn(void) { int x = 1; }\nvoid gone_fn(void) { }\n",
    "APP/same.c": "void same_fn(void) { }\n",
}
TGT_FILES = {
    "APP/a.c": "void keep_fn(void) { int x = 2; }\nvoid new_fn(void) { }\n",   # BODY + NEW + DELETE
    "APP/same.c": "void same_fn(void) { }\n",
}


def _snap(root: Path, files: dict) -> Path:
    src = root / "source"
    for rel, text in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (src / ".source_complete").write_text("scm=svn\nrevision=1\n", encoding="utf-8")
    (root / "report").mkdir(parents=True, exist_ok=True)
    return root


def _metas(tmp_path: Path, nums) -> list:
    rows = []
    for n in sorted(nums, reverse=True):
        root = tmp_path / f"build_{n}"
        rows.append({
            "build_number": n, "build_root": str(root), "reports_dir": str(root / "report"),
            "has_source": (root / "source" / ".source_complete").exists(),
            "revision": None, "timestamp_iso": None, "result": "SUCCESS",
        })
    return rows


@pytest.fixture
def matrix_env(tmp_path, monkeypatch):
    """#10·#11·#13 동일 트리(베이스라인과 같음) + #12·#14 서로 다른 트리."""
    from backend.routers import summary_insight as si
    from backend.services import change_matrix as cm

    _snap(tmp_path / "build_10", BASE_FILES)
    _snap(tmp_path / "build_11", BASE_FILES)
    _snap(tmp_path / "build_13", BASE_FILES)
    _snap(tmp_path / "build_12", TGT_FILES)
    _snap(tmp_path / "build_14", {**TGT_FILES, "APP/extra.c": "void extra_fn(void) { }\n"})
    monkeypatch.setattr("backend.services.build_inventory.list_cached_builds_meta",
                        lambda **k: _metas(tmp_path, [14, 13, 12, 11, 10]))
    # 조인은 이 테스트의 관심사가 아니다 — 비용/노이즈 제거.
    monkeypatch.setattr(si, "_coverage_index", lambda *a, **k: {})
    monkeypatch.setattr(si, "_asil_index", lambda *a, **k: {"by_function": {}, "counts": {}, "propagation": {}})
    cm.clear_parse_memo()
    return {"si": si, "cm": cm, "tmp": tmp_path,
            "body": {"job_url": "http://j/", "cache_root": str(tmp_path / "cr"), "baseline_build": 10}}


def test_identical_snapshots_resolve_without_parsing(matrix_env, monkeypatch):
    """베이스라인과 바이트 동일한 빌드는 **파서를 부르지 않고** 함수 0으로 확정된다.

    증명이지 가정이 아니다 — 두 트리가 동일하면 파서 산출도 동일하고 (파일,함수명) 차집합은
    공집합이다. 실측 13빌드 중 9행이 이 경로로 즉시 완성된다.
    """
    import backend.services.baseline_diff as bd

    monkeypatch.setattr(bd, "_parse_functions",
                        lambda *a, **k: pytest.fail("동일 스냅샷에 파서가 호출되면 안 된다"))
    r = matrix_env["si"].summary_change_matrix({**matrix_env["body"], "level": "functions"})
    by = {row["build_number"]: row for row in r["rows"]}
    for n in (11, 13):
        assert by[n]["identical_to_baseline"] is True
        assert by[n]["functions"] == {"new": 0, "deleted": 0, "signature": 0, "body": 0, "changed": 0}
        assert by[n]["function_state"]["state"] == "identical"
        assert by[n]["asil"]["touched"] == 0
    assert by[10]["is_baseline"] is True and by[10]["function_state"]["state"] == "baseline"


def test_level_files_never_computes_functions(matrix_env, monkeypatch):
    """level=files는 함수 축을 계산하지 않는다 — null + reason(0 위장 금지)."""
    import backend.services.baseline_diff as bd

    monkeypatch.setattr(bd, "_parse_functions",
                        lambda *a, **k: pytest.fail("level=files에서 파서 호출 금지"))
    r = matrix_env["si"].summary_change_matrix({**matrix_env["body"], "level": "files"})
    by = {row["build_number"]: row for row in r["rows"]}
    assert by[12]["functions"] is None and by[12]["asil"] is None       # ← 0이 아니라 null
    assert by[12]["function_state"] == {"state": "not_computed", "reason": "level_files"}
    assert by[12]["files"]["changed"] == 1                              # 파일 축은 즉시 나온다
    assert by[14]["files"]["changed"] == 2                              # a.c 수정 + extra.c 추가


def test_pending_cells_deduped_by_content_sha(matrix_env):
    """pending은 고유 sha 쌍 단위 — 동일 트리 빌드가 pending을 뻥튀기하지 않는다."""
    r = matrix_env["si"].summary_change_matrix({**matrix_env["body"], "level": "functions"})
    assert len(r["rows"]) == 5
    # 서로 다른 트리 2개(#12·#14)만 pending. #11·#13은 identical, #10은 baseline.
    assert sorted(p["target_build"] for p in r["pending_cells"]) == [12, 14]
    groups = {g["count"] for g in r["snapshot_groups"]}
    assert 3 in groups   # #10·#11·#13이 한 그룹


def test_one_cell_fills_and_is_join_independent(matrix_env):
    """셀 1건 계산 → 재조회 시 캐시 히트. 조인 규모가 바뀌어도 캐시는 살아 있어야 한다."""
    si, body = matrix_env["si"], matrix_env["body"]
    c = si.summary_change_matrix_cell({**body, "target_build": 12})
    assert c["cached"] is False and c["functions"]["changed"] > 0
    assert c["functions"]["new"] == 1 and c["functions"]["deleted"] == 1 and c["functions"]["body"] == 1

    r = si.summary_change_matrix({**body, "level": "functions"})
    by = {row["build_number"]: row for row in r["rows"]}
    assert by[12]["function_state"]["state"] == "computed"
    assert by[12]["functions"]["changed"] == c["functions"]["changed"]
    assert r["stats"]["function_cells_cached"] == 1

    # 조인 인덱스 크기를 바꿔도(=새 빌드 유입 상황) 셀 캐시는 유효해야 한다.
    si_mod = matrix_env["si"]
    orig = si_mod._asil_index
    si_mod._asil_index = lambda *a, **k: {"by_function": {"keep_fn": {"asil": "C", "source": "x"}},
                                          "counts": {}, "propagation": {}}
    try:
        c2 = si_mod.summary_change_matrix_cell({**body, "target_build": 12})
        assert c2["cached"] is True                       # 재계산 없음
        assert c2["asil"]["touched"] >= 1                 # 등급은 읽을 때 새로 부착됨
    finally:
        si_mod._asil_index = orig


def test_probe_never_computes(matrix_env, monkeypatch):
    """probe는 캐시만 본다 — 미스여도 파서를 부르지 않고 pending을 알린다."""
    import backend.services.baseline_diff as bd

    monkeypatch.setattr(bd, "_parse_functions", lambda *a, **k: pytest.fail("probe가 계산하면 안 된다"))
    c = matrix_env["si"].summary_change_matrix_cell({**matrix_env["body"], "target_build": 12, "probe": True})
    assert c["available"] is True and c["cached"] is False
    assert c["function_state"]["state"] == "pending"


def test_cell_cache_does_not_pollute_baseline_diff_glob(matrix_env):
    """⚠ 셀 캐시 파일명이 `summary_baseline_diff_*` 글롭에 걸리면 test-design의 '변경 축'이 오염된다.

    `_changed_functions_from_cache`가 그 글롭의 mtime 최신 3개를 읽어 변경 함수 집합을 만든다.
    """
    si, body, tmp = matrix_env["si"], matrix_env["body"], matrix_env["tmp"]
    si.summary_change_matrix_cell({**body, "target_build": 12})
    si.summary_change_matrix_cell({**body, "target_build": 14})
    written = [p.name for p in (tmp / "build_12" / "report").glob("*.json")]
    assert any(n.startswith("summary_change_cell_") for n in written)
    for reports in (tmp / "build_12" / "report", tmp / "build_14" / "report"):
        assert list(reports.glob("summary_baseline_diff_*.json")) == []
    # 변경 축 소비자가 매트릭스 산출물을 집어가지 않는다 — 셀이 2개 있어도 '캐시 없음'이어야 한다.
    axis = si._changed_functions_from_cache(tmp / "build_12" / "report")
    assert axis["available"] is False and axis["reason"] == "no_baseline_diff_cache"
    assert axis["functions"] == set()


def test_canonical_build_is_min_and_groups_include_singletons():
    """그룹 대표는 min — 같은 트리로 새 빌드가 들어와도 캐시 키가 바뀌지 않는다."""
    from backend.services.change_matrix import canonical_build, cell_cache_name, cell_id, group_by_content_sha

    metas = [{"build_number": n} for n in (14, 13, 12, 11, 10)]
    sha = {14: "z", 13: "a", 12: "b", 11: "a", 10: "a"}
    groups = group_by_content_sha(metas, lambda m: sha[m["build_number"]])
    assert groups == {"z": [14], "a": [13, 11, 10], "b": [12]}   # 단독 그룹도 포함
    assert canonical_build(groups["a"]) == 10
    assert canonical_build([]) is None
    assert cell_cache_name("de6809e76230abcdef") == "summary_change_cell_de6809e76230.json"
    assert cell_id("de6809e76230", "db67421f4d59") == "de6809e7__db67421f"


def test_parse_memo_keyed_by_content_not_path(tmp_path):
    """파싱 메모는 **내용 지문**이 키 — 경로가 달라도 같은 트리면 1회만 파싱한다."""
    import backend.services.baseline_diff as bd
    from backend.services import change_matrix as cm

    cm.clear_parse_memo()
    calls: list = []
    orig = bd._parse_functions
    bd._parse_functions = lambda source, **k: (calls.append(str(source)), {})[1]
    try:
        a = _snap(tmp_path / "a", BASE_FILES) / "source"
        b = _snap(tmp_path / "b", BASE_FILES) / "source"   # 다른 경로, 같은 내용
        cm.parse_functions_memo(a, content_sha="same")
        cm.parse_functions_memo(b, content_sha="same")
        assert len(calls) == 1
        cm.parse_functions_memo(b, content_sha="other")
        assert len(calls) == 2
        # 지문이 없으면 메모하지 않는다(잘못된 키로 오염 금지)
        cm.parse_functions_memo(a, content_sha=None)
        cm.parse_functions_memo(a, content_sha=None)
        assert len(calls) == 4
    finally:
        bd._parse_functions = orig
        cm.clear_parse_memo()


def test_matrix_honest_failures(tmp_path, monkeypatch):
    from backend.routers import summary_insight as si

    monkeypatch.setattr("backend.services.build_inventory.list_cached_builds_meta", lambda **k: [])
    assert si.summary_change_matrix({"job_url": "http://j/"})["reason"] == "no_source_snapshot"
    assert si.summary_change_matrix({})["reason"] == "job_url_required"
