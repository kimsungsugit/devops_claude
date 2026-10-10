"""build_inventory — 캐시 빌드 오프라인 메타(Jenkins 무의존). 부재=null(0 위장 금지)."""
from __future__ import annotations

import json
from pathlib import Path


def _mk_build(tmp_path: Path, n: int, *, status: dict | None = None, sentinel: str | None = None,
              rcr: bool = False, summary: bool = False) -> Path:
    root = tmp_path / "jenkins" / "http_j_job_X" / f"build_{n}"
    (root / "report").mkdir(parents=True)
    if status is not None:
        (root / "report" / "status.json").write_text(json.dumps(status), encoding="utf-8")
    if sentinel is not None:
        (root / "source").mkdir()
        (root / "source" / ".source_complete").write_text(sentinel, encoding="utf-8")
    if rcr:
        (root / "X_RCR_01012026.html").write_text("<html></html>", encoding="utf-8")
    if summary:
        (root / "report" / "analysis_summary.json").write_text("{}", encoding="utf-8")
    return root


def test_meta_merged_from_status_and_sentinel(tmp_path):
    from backend.services.build_inventory import list_cached_builds_meta

    _mk_build(
        tmp_path, 125,
        status={"result": "SUCCESS", "timestamp": "2026-07-24T13:00:11", "build_url": "http://j/125/"},
        sentinel="scm=svn\nrevision=1075\nbranch=trunk\n",
        rcr=True, summary=True,
    )
    rows = list_cached_builds_meta(job_url="http://j/job/X/", cache_root=tmp_path)
    assert len(rows) == 1
    r = rows[0]
    assert r["build_number"] == 125
    assert r["result"] == "SUCCESS"
    assert r["timestamp_iso"] == "2026-07-24T13:00:11"  # ISO 문자열 그대로(변환 왜곡 금지)
    assert r["revision"] == "1075" and r["branch"] == "trunk" and r["scm"] == "svn"
    assert r["has_source"] is True and r["has_rcr"] is True and r["has_analysis_summary"] is True


def test_missing_meta_yields_null_not_zero(tmp_path):
    """status.json/센티널 부재 → null 필드 + has_* False (0/빈문자 위장 금지)."""
    from backend.services.build_inventory import list_cached_builds_meta

    _mk_build(tmp_path, 7)  # 산출물 없음
    r = list_cached_builds_meta(job_url="http://j/job/X/", cache_root=tmp_path)[0]
    assert r["result"] is None and r["timestamp_iso"] is None and r["revision"] is None
    assert r["has_source"] is False and r["has_rcr"] is False and r["has_analysis_summary"] is False


def test_corrupt_status_and_sentinel_fail_soft(tmp_path):
    from backend.services.build_inventory import list_cached_builds_meta

    root = _mk_build(tmp_path, 9)
    (root / "report" / "status.json").write_text("{corrupt", encoding="utf-8")
    (root / "source").mkdir()
    (root / "source" / ".source_complete").write_text("no equals lines\n===\n", encoding="utf-8")
    r = list_cached_builds_meta(job_url="http://j/job/X/", cache_root=tmp_path)[0]
    assert r["result"] is None
    assert r["revision"] is None
    assert r["has_source"] is True  # 센티널 존재 자체는 사실


def test_rows_sorted_latest_first_and_find_helper(tmp_path):
    from backend.services.build_inventory import find_build_meta, list_cached_builds_meta

    _mk_build(tmp_path, 122, status={"result": "SUCCESS"})
    _mk_build(tmp_path, 125, status={"result": "FAILURE"})
    rows = list_cached_builds_meta(job_url="http://j/job/X/", cache_root=tmp_path)
    assert [r["build_number"] for r in rows] == [125, 122]
    assert find_build_meta(rows, 122)["result"] == "SUCCESS"
    assert find_build_meta(rows, 999) is None
    assert find_build_meta(rows, None) is None
