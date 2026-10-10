"""SCM 입력 문서 로드 이력 → 함수단위 커버리지 회수(N1).

핵심 계약: 완료+vectorcast+ok+함수entries 보유 잡만 채택, 최신이 부적합이면 직전 잡으로 폴백,
(path, mtime_ns) 캐시, 대용량 필드(test_rows)는 집계만 승계.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _job(
    *,
    status: str = "completed",
    trigger: str = "vectorcast",
    ok: bool = True,
    ut: int = 2,
    it: int = 1,
    finished: str = "2026-07-25T11:39:22+09:00",
) -> dict:
    return {
        "job_id": "impact_x", "scm_id": "slug", "status": status, "trigger_type": trigger,
        "created_at": "2026-07-25T11:35:38+09:00", "finished_at": finished,
        "result": {
            "ok": ok,
            "data": {
                "vcast_summary": {
                    "ut_metrics": {"entries": [
                        {"unit": "Lib_a", "subprogram": f"f{i}", "ccn": i + 1,
                         "statements": {"covered": i, "total": 4, "rate": i / 4},
                         "branches": {"covered": 0, "total": 2, "rate": 0.0},
                         "pairs": {"covered": 0, "total": 0, "rate": None}}
                        for i in range(ut)
                    ]},
                    "it_metrics": {"entries": [
                        {"unit": "Ap_b", "subprogram": f"g{i}", "ccn": 1,
                         "statements": {"covered": 3, "total": 3, "rate": 1.0},
                         "branches": {"covered": 1, "total": 1, "rate": 1.0},
                         "function_calls": {"covered": 2, "total": 3, "rate": 0.667}}
                        for i in range(it)
                    ]},
                },
                "complexity_rows": [{"function": "f0", "file": "Lib_a", "unit": "Lib_a", "complexity": 1}],
                "test_rows": [{"subprogram": "SwUFn_1", "result": "PASS"}] * 5,  # 대용량 대역 — 승계 금지
                "test_rows_count_ut": 4, "test_rows_count_it": 1,
                "summary": {"total": 5, "passed": 5, "failed": 0, "pass_rate": 1.0},
                "coverage": {"statement": {"covered": 12, "total": 17, "rate": 0.7}},
                "coverage_ut": {"statement": {"covered": 10, "total": 10, "rate": 1.0}},
                "failures": [],
                "parse_warnings": ["w1"],
                "merged_sources": 4,
            },
        },
    }


@pytest.fixture(autouse=True)
def _clear_cache():
    from backend.services import scm_vcast_functions as mod

    mod.clear_cache()
    yield
    mod.clear_cache()


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_load_slices_function_blocks(tmp_path, monkeypatch):
    from backend.services import scm_vcast_functions as mod

    path = _write(tmp_path, "job_impact_20260725_113538_slug_aaaa1111.json", _job())
    monkeypatch.setattr("workflow.impact_jobs.find_job_files_by_scm", lambda s, limit=1: [path])

    out = mod.load_scm_function_metrics("http://j/job/X")
    assert out["available"] is True
    assert len(out["ut_entries"]) == 2 and len(out["it_entries"]) == 1
    assert out["ut_entries"][0]["subprogram"] == "f0"
    assert out["job_file"] == path.name
    assert out["generated_at"] == "2026-07-25T11:39:22+09:00"
    # test_rows 원본은 승계하지 않는다(메모리) — 집계만
    assert "test_rows" not in out
    assert out["test_summary"] == {"total": 5, "passed": 5, "failed": 0, "pass_rate": 1.0,
                                   "ut_rows": 4, "it_rows": 1}
    assert out["complexity_rows"][0]["function"] == "f0"
    assert out["merged_sources"] == 4


@pytest.mark.parametrize("kw", [
    {"status": "running"},      # 미완료
    {"trigger": "impact"},      # 다른 트리거(네임스페이스 오매칭 방어)
    {"ok": False},              # 실패 잡
    {"ut": 0, "it": 0},         # 로드는 됐으나 함수 커버리지 없음
])
def test_unqualified_jobs_rejected(tmp_path, monkeypatch, kw):
    from backend.services import scm_vcast_functions as mod

    path = _write(tmp_path, "job_impact_20260725_113538_slug_aaaa1111.json", _job(**kw))
    monkeypatch.setattr("workflow.impact_jobs.find_job_files_by_scm", lambda s, limit=1: [path])
    out = mod.load_scm_function_metrics("http://j/job/X")
    assert out["available"] is False
    assert out["reason"] == "no_completed_vcast_job_with_metrics"


def test_falls_back_to_older_successful_job(tmp_path, monkeypatch):
    """최신 잡이 실패면 직전 성공 잡을 쓴다(가용성 우선 — jenkins 규약 승계)."""
    from backend.services import scm_vcast_functions as mod

    newest = _write(tmp_path, "job_impact_20260725_120000_slug_bbbb2222.json", _job(ok=False))
    older = _write(tmp_path, "job_impact_20260724_090000_slug_aaaa1111.json",
                   _job(finished="2026-07-24T09:10:00+09:00"))
    monkeypatch.setattr("workflow.impact_jobs.find_job_files_by_scm", lambda s, limit=1: [newest, older])
    out = mod.load_scm_function_metrics("http://j/job/X")
    assert out["available"] is True and out["job_file"] == older.name


def test_corrupt_json_is_skipped(tmp_path, monkeypatch):
    from backend.services import scm_vcast_functions as mod

    bad = tmp_path / "job_impact_20260725_120000_slug_bbbb2222.json"
    bad.write_text("{ not json", encoding="utf-8")
    good = _write(tmp_path, "job_impact_20260724_090000_slug_aaaa1111.json", _job())
    monkeypatch.setattr("workflow.impact_jobs.find_job_files_by_scm", lambda s, limit=1: [bad, good])
    out = mod.load_scm_function_metrics("http://j/job/X")
    assert out["available"] is True and out["job_file"] == good.name


def test_cache_hit_avoids_reparse(tmp_path, monkeypatch):
    """키가 (path, mtime_ns)라 mtime이 그대로면 본문이 바뀌어도 재파싱하지 않는다.

    (완료 잡 파일은 불변이라는 전제 — 파일이 삭제되면 stat 실패로 캐시를 쓰지 않고
    다음 후보로 넘어가는 것이 옳다. 그래서 '삭제'가 아니라 'mtime 고정 덮어쓰기'로 검증한다.)
    """
    import os

    path = _write(tmp_path, "job_impact_20260725_113538_slug_aaaa1111.json", _job(ut=2))
    monkeypatch.setattr("workflow.impact_jobs.find_job_files_by_scm", lambda s, limit=1: [path])
    from backend.services import scm_vcast_functions as mod

    first = mod.load_scm_function_metrics("http://j/job/X")
    st = path.stat()
    path.write_text(json.dumps(_job(ut=9)), encoding="utf-8")
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))  # mtime 복원 → 같은 캐시 키
    second = mod.load_scm_function_metrics("http://j/job/X")
    assert first["available"] and second["available"]
    assert len(second["ut_entries"]) == 2  # 재파싱했다면 9였을 것

    # 반환은 사본이라 호출측 변형이 캐시를 오염시키지 않는다
    second["ut_entries"] = []
    assert mod.load_scm_function_metrics("http://j/job/X")["ut_entries"]


def test_missing_inputs_are_honest():
    from backend.services import scm_vcast_functions as mod

    assert mod.load_scm_function_metrics("")["reason"] == "job_url_required"


def test_no_candidates_reason(monkeypatch):
    from backend.services import scm_vcast_functions as mod

    monkeypatch.setattr("workflow.impact_jobs.find_job_files_by_scm", lambda s, limit=1: [])
    out = mod.load_scm_function_metrics("http://j/job/X")
    assert out["available"] is False and out["reason"] == "no_scm_vcast_job"
