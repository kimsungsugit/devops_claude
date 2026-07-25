"""baseline_diff — 파일 sha1 3분류·함수 파서 권위·ASIL 조인·캐시/force·기본 쌍·정직 실패."""
from __future__ import annotations

from pathlib import Path

from backend.services.baseline_diff import compute_baseline_diff, snapshot_fingerprint


def _snap(root: Path, files: dict) -> Path:
    src = root / "source"
    for rel, text in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (src / ".source_complete").write_text("scm=svn\nrevision=1\n", encoding="utf-8")
    return src


BASE_FILES = {
    "APP/a.c": (
        "/** @asil C */\n"
        "void safe_fn(int a) { int x = a; }\n"
        "void body_fn(void) { int y = 1; }\n"
        "void gone_fn(void) { }\n"
    ),
    "APP/same.c": "void same_fn(void) { }\n",
    "APP/removed.c": "void removed_file_fn(void) { }\n",
}
TGT_FILES = {
    "APP/a.c": (
        "/** @asil C */\n"
        "void safe_fn(int a, int b) { int x = a + b; }\n"   # SIGNATURE (+ASIL)
        "void body_fn(void) { int y = 2; }\n"                # BODY
        "void new_fn(void) { }\n"                            # NEW
    ),
    "APP/same.c": "void same_fn(void) { }\n",
    "APP/added.c": "void added_file_fn(void) { }\n",
}


def test_file_and_function_classification(tmp_path):
    base = _snap(tmp_path / "b122", BASE_FILES)
    tgt = _snap(tmp_path / "b125", TGT_FILES)
    r = compute_baseline_diff(baseline_source=base, target_source=tgt)

    assert r["files"]["added"] == ["APP/added.c"]
    assert r["files"]["deleted"] == ["APP/removed.c"]
    assert [m["path"] for m in r["files"]["modified"]] == ["APP/a.c"]
    assert r["files"]["unchanged"] == 1
    mod = r["files"]["modified"][0]
    assert mod["lines_added"] and mod["lines_removed"]

    fns = r["functions"]
    new_names = {f["name"] for f in fns["new"]}
    del_names = {f["name"] for f in fns["deleted"]}
    assert "new_fn" in new_names and "added_file_fn" in new_names
    assert "gone_fn" in del_names and "removed_file_fn" in del_names
    sig = {f["name"]: f for f in fns["signature_changed"]}
    assert "safe_fn" in sig
    assert "int a, int b" in sig["safe_fn"]["after"] and "int a, int b" not in sig["safe_fn"]["before"]
    body = {f["name"] for f in fns["body_changed"]}
    assert "body_fn" in body and "same_fn" not in body
    assert fns["counts"]["signature"] == 1 and fns["counts"]["body"] == 1

    # ASIL 주석 함수 변경 강조
    asil = {(a["name"], a["change_kind"]) for a in r["asil_touched"]}
    assert ("safe_fn", "SIGNATURE") in asil
    assert r["method"]["functions"].startswith("parse_c_project")


def test_whitespace_reformat_not_reported_as_change(tmp_path):
    """공백/개행 리포맷만은 함수 변경으로 보고하지 않는다(정규화 비교)."""
    base = _snap(tmp_path / "b1", {"a.c": "void f(void) { int x = 1; }\n"})
    tgt = _snap(tmp_path / "b2", {"a.c": "void f(void)\n{\n    int x = 1;\n}\n"})
    r = compute_baseline_diff(baseline_source=base, target_source=tgt)
    assert r["functions"]["counts"] == {"new": 0, "deleted": 0, "signature": 0, "body": 0}
    # 파일 자체는 sha1이 달라 modified로 정직 표기(함수 의미 변화와 구분).
    assert [m["path"] for m in r["files"]["modified"]] == ["a.c"]


def test_fingerprint_requires_sentinel(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "a.c").write_text("int x;", encoding="utf-8")
    assert snapshot_fingerprint(src) is None  # 센티널 없음 = 미완결
    (src / ".source_complete").write_text("ok", encoding="utf-8")
    fp = snapshot_fingerprint(src)
    assert fp and fp["file_count"] == 2 and fp["algo_version"] >= 1


# ── 엔드포인트 ──────────────────────────────────────────────────────────────

def _metas(tmp_path, nums, *, src=True):
    rows = []
    for n in sorted(nums, reverse=True):
        root = tmp_path / f"build_{n}"
        (root / "report").mkdir(parents=True, exist_ok=True)
        rows.append({
            "build_number": n, "build_root": str(root), "reports_dir": str(root / "report"),
            "has_source": src and (root / "source" / ".source_complete").exists(),
            "revision": None, "timestamp_iso": None,
        })
    return rows


def test_endpoint_default_pair_oldest_to_newest_and_cache(tmp_path, monkeypatch):
    from backend.routers import summary_insight as si

    _snap(tmp_path / "build_122", BASE_FILES)
    _snap(tmp_path / "build_125", TGT_FILES)
    monkeypatch.setattr(
        "backend.services.build_inventory.list_cached_builds_meta",
        lambda **k: _metas(tmp_path, [125, 122]),
    )
    body = {"job_url": "http://j/", "cache_root": str(tmp_path / "cr")}
    r1 = si.summary_baseline_diff(body)
    assert r1["available"] is True and r1["cached"] is False
    assert r1["baseline"]["build_number"] == 122 and r1["target"]["build_number"] == 125
    assert r1["independent_of_change_log"] is True
    r2 = si.summary_baseline_diff(body)
    assert r2["cached"] is True
    r3 = si.summary_baseline_diff({**body, "force": True})
    assert r3["cached"] is False


def test_endpoint_honest_failures(tmp_path, monkeypatch):
    from backend.routers import summary_insight as si

    # 소스 스냅샷 0개
    monkeypatch.setattr(
        "backend.services.build_inventory.list_cached_builds_meta",
        lambda **k: _metas(tmp_path, [125], src=False),
    )
    r = si.summary_baseline_diff({"job_url": "http://j/"})
    assert r["available"] is False and r["reason"] == "no_source_snapshot"

    # 스냅샷 1개뿐
    _snap(tmp_path / "build_125", TGT_FILES)
    monkeypatch.setattr(
        "backend.services.build_inventory.list_cached_builds_meta",
        lambda **k: _metas(tmp_path, [125]),
    )
    r2 = si.summary_baseline_diff({"job_url": "http://j/"})
    assert r2["available"] is False and r2["reason"] == "single_build_cached"

    # 같은 빌드 쌍
    _snap(tmp_path / "build_122", BASE_FILES)
    monkeypatch.setattr(
        "backend.services.build_inventory.list_cached_builds_meta",
        lambda **k: _metas(tmp_path, [125, 122]),
    )
    r3 = si.summary_baseline_diff({"job_url": "http://j/", "baseline_build": 125, "target_build": 125})
    assert r3["available"] is False and r3["reason"] == "same_build_pair"


# ── N3: 파일 → 함수 트리 + 커버리지/ASIL 조인 ───────────────────────────────

_COV = {
    # safe_fn은 미커버(0%), body_fn은 부분, new_fn은 인덱스에 없음(미조인)
    "safe_fn": {"statement": 0.0, "branch": 0.0, "ccn": 7, "metric_source": "ut"},
    "body_fn": {"statement": 0.6, "branch": 0.5, "ccn": 3, "metric_source": "ut"},
    "added_file_fn": {"statement": 1.0, "branch": 1.0, "ccn": 1, "metric_source": "it"},
}


def test_changed_detail_groups_functions_under_files(tmp_path):
    base = _snap(tmp_path / "b122", BASE_FILES)
    tgt = _snap(tmp_path / "b125", TGT_FILES)
    r = compute_baseline_diff(baseline_source=base, target_source=tgt, function_coverage=_COV)

    detail = {row["path"]: row for row in r["files"]["changed_detail"]}
    assert set(detail) == {"APP/a.c", "APP/added.c", "APP/removed.c"}  # 무변경 파일은 없음
    a = detail["APP/a.c"]
    assert a["change_kind"] == "modified"
    kinds = {f["name"]: f["kind"] for f in a["functions"]}
    # gone_fn은 파일은 남고 함수만 사라진 케이스 — 파일 행 아래 DELETE로 보여야 한다
    assert kinds == {"safe_fn": "SIGNATURE", "body_fn": "BODY", "new_fn": "NEW", "gone_fn": "DELETE"}
    assert a["counts"] == {"new": 1, "deleted": 1, "signature": 1, "body": 1}
    # 커버리지 조인: 값이 붙고, 미조인은 null(0%로 위장 금지)
    by_name = {f["name"]: f for f in a["functions"]}
    assert by_name["safe_fn"]["statement"] == 0.0 and by_name["safe_fn"]["ccn"] == 7
    assert by_name["body_fn"]["statement"] == 0.6
    assert by_name["new_fn"]["statement"] is None and by_name["new_fn"]["ccn"] is None
    assert a["worst_statement"] == 0.0 and a["coverage_matched"] == 2
    assert a["asil_max"] == "C"  # @asil C 주석 보유 함수(safe_fn) 변경

    # 삭제 파일도 그 파일의 함수가 DELETE로 붙는다
    assert [f["kind"] for f in detail["APP/removed.c"]["functions"]] == ["DELETE"]
    assert detail["APP/added.c"]["functions"][0]["metric_source"] == "it"


def test_changed_detail_risk_first_ordering(tmp_path):
    base = _snap(tmp_path / "b122", BASE_FILES)
    tgt = _snap(tmp_path / "b125", TGT_FILES)
    r = compute_baseline_diff(baseline_source=base, target_source=tgt, function_coverage=_COV)
    # ASIL 보유 파일이 최상단(위험 우선 정렬)
    assert r["files"]["changed_detail"][0]["path"] == "APP/a.c"


def test_gap_summary_and_join_transparency(tmp_path):
    base = _snap(tmp_path / "b122", BASE_FILES)
    tgt = _snap(tmp_path / "b125", TGT_FILES)
    r = compute_baseline_diff(baseline_source=base, target_source=tgt, function_coverage=_COV)
    gap = r["functions"]["gap_summary"]
    # a.c의 SIGNATURE/BODY/NEW/DELETE 4 + added_file_fn + removed_file_fn
    assert gap["changed_functions"] == 6
    assert gap["with_coverage"] == 3
    assert gap["uncovered"] == 1              # safe_fn 0%
    assert gap["below_full"] == 1             # body_fn 60%
    assert gap["asil_touched"] == 1
    assert gap["coverage_unmatched"] == 3     # new_fn, gone_fn, removed_file_fn
    assert r["coverage_join"] == {"injected": True, "functions_in_index": 3,
                                  "matched": 3, "unmatched": 3}
    assert r["asil_join"] == {"injected": False, "functions_in_index": 0}


def test_injected_asil_revives_axis_without_comments(tmp_path):
    """주석 @asil이 없는 프로젝트에서도 요구 역전파 등급이 트리에 실려야 한다(N2 연동)."""
    no_comment = {k: v.replace("/** @asil C */\n", "") for k, v in BASE_FILES.items()}
    no_comment_t = {k: v.replace("/** @asil C */\n", "") for k, v in TGT_FILES.items()}
    base = _snap(tmp_path / "b122", no_comment)
    tgt = _snap(tmp_path / "b125", no_comment_t)
    injected = {"safe_fn": {"asil": "D", "source": "uds_link"}}
    r = compute_baseline_diff(baseline_source=base, target_source=tgt, asil_by_fn=injected)
    rows = {f["name"]: f for row in r["files"]["changed_detail"] for f in row["functions"]}
    assert rows["safe_fn"]["asil"] == "D" and rows["safe_fn"]["asil_source"] == "uds_link"
    assert rows["body_fn"]["asil"] is None  # 미상은 QM으로 단정하지 않는다
    assert r["asil_join"]["injected"] is True


def test_comment_and_injected_asil_merge_safely(tmp_path):
    """주석 C vs 역전파 D면 안전측(D) 채택 — under-report 금지."""
    base = _snap(tmp_path / "b122", BASE_FILES)
    tgt = _snap(tmp_path / "b125", TGT_FILES)
    r = compute_baseline_diff(baseline_source=base, target_source=tgt,
                              asil_by_fn={"safe_fn": {"asil": "D", "source": "uds_link"}})
    rows = {f["name"]: f for row in r["files"]["changed_detail"] for f in row["functions"]}
    assert rows["safe_fn"]["asil"] == "D" and rows["safe_fn"]["asil_source"] == "uds_link"
    # 같은 등급이면 both로 표기
    r2 = compute_baseline_diff(baseline_source=base, target_source=tgt,
                               asil_by_fn={"safe_fn": {"asil": "C", "source": "uds_link"}})
    rows2 = {f["name"]: f for row in r2["files"]["changed_detail"] for f in row["functions"]}
    assert rows2["safe_fn"]["asil"] == "C" and rows2["safe_fn"]["asil_source"] == "both"


def test_algo_version_bumped_for_cache_invalidation():
    from backend.services.baseline_diff import BASELINE_DIFF_ALGO_VERSION

    assert BASELINE_DIFF_ALGO_VERSION >= 2  # v1 캐시(changed_detail 없음)를 재사용하면 안 된다
