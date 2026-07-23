"""aggregate_stats 엔드포인트 — 대시보드 집계가 상세탭(build_report_summary)과 동일 해석을 쓰는지.

핵심 회귀 방지: 코드규모(LOC/함수)·PRQA 진단이 lizard 부재 프로젝트(KJPDS02_PV류)에서
QAC 폴백으로 채워지고, lizard 있는 프로젝트(HDPDM01류)는 기존값을 그대로 유지하는지.
"""
import json

import pytest

from backend.routers import jenkins as jenkins_mod
from backend.routers.jenkins import aggregate_stats, scm_vcast_summary
from backend.services.jenkins_helpers import _job_slug
from workflow import impact_jobs as impact_jobs_mod
from workflow.impact_jobs import _sanitize_fragment

# KJPDS02_PV 형태: code_metrics 전부 None(빌드에 lizard/complexity.csv 없음) + Helix QAC RCR/HMR 존재.
# Helix RCR은 CRR이 없고 라벨이 "... (including CMA)"/"... (including headers)"다.
_KJPDS_SUMMARY = {
    "jenkins": {"build_number": 122, "result": "SUCCESS"},
    "coverage": {},
    "tests": {},
    "code_metrics": {"code_files": None, "functions": None, "nloc": None},
    "prqa": {
        "rcr": {"ok": True, "summary": {
            "Number of Files (including CMA)": 126,
            "Lines of Code (including headers)": 67464,
            "Diagnostic Count": 496,
            "Violated Rules": 18,
            "Project Compliance Index": 92,
        }},
        "hmr": {"ok": True, "stats": {"functions_total": 881}},
    },
}

# HDPDM01 형태: complexity.csv 유래 code_metrics 존재 + PRQA CRR/RCR 존재(둘 다 diagnostic 577).
_HDPDM_SUMMARY = {
    "jenkins": {"build_number": 26, "result": "SUCCESS"},
    "coverage": {},
    "tests": {},
    "code_metrics": {"code_files": 30, "functions": 349, "nloc": 4429},
    "prqa": {
        "crr": {"diagnostic_count": 577},
        "rcr": {"ok": True, "summary": {
            "Number of Files": 38,
            "Lines of Code (source files only)": 36516,
            "Diagnostic Count": 577,
            "Violated Rules": 17,
            "Project Compliance Index": 83,
        }},
    },
}


def _place_summary(base, job_url, summary):
    """get_current_user()='default' 경로에서 안 걸리도록 legacy {base}/jenkins/{slug}/build_1에 배치.

    (user 서브디렉토리를 만들지 않으면 aggregate_stats는 legacy 공유 경로를 후보로 쓴다.)
    """
    slug = _job_slug(job_url)
    rdir = base / "jenkins" / slug / "build_1" / "report"
    rdir.mkdir(parents=True)
    (rdir / "analysis_summary.json").write_text(json.dumps(summary), encoding="utf-8")


def _project_by_name(result, name):
    return next(p for p in result["projects"] if p["name"] == name)


# ── SCM 로드 이력(VectorCAST 잡) 격리 ────────────────────────────────
# find_latest_job_file은 모듈 전역 JOB_DIR을 참조 → 실제 reports/impact_jobs와 격리해 결정성 확보.
# jenkins의 (path,mtime) 캐시도 매 테스트 비워 크로스테스트 오염을 막는다. 이력을 배치하지 않는
# 테스트는 빈 JOB_DIR → SCM 폴백 no-op(기존 동작 보존).
@pytest.fixture(autouse=True)
def _isolate_scm_job_history(tmp_path, monkeypatch):
    jobs = tmp_path / "_scm_jobs"
    jobs.mkdir()
    monkeypatch.setattr(impact_jobs_mod, "JOB_DIR", jobs)
    jenkins_mod._SCM_VCAST_METRICS_CACHE.clear()
    yield jobs
    jenkins_mod._SCM_VCAST_METRICS_CACHE.clear()


# KJPDS02_PV류 SCM VectorCAST payload(병합 shape) — 잡 result.data에 실린다.
_KJPDS_VCAST_PAYLOAD = {
    "coverage": {
        "statement": {"covered": 8579, "total": 8622, "rate": 0.995},
        "branch": {"covered": 4044, "total": 4097, "rate": 0.9871},
        "mcdc": {"covered": 0, "total": 0, "rate": None},
    },
    "test_rows_count_ut": 120, "test_rows_count_it": 45,
    "summary_ut": {"total": 120, "passed": 118, "failed": 2, "pass_rate": 0.9833},
    "summary_it": {"total": 45, "passed": 45, "failed": 0, "pass_rate": 1.0},
}


def _place_vcast_job(jobs_dir, job_url, payload, *, ts="20260720_101010", uid="abcd1234",
                     status="completed", trigger_type="vectorcast", ok=True):
    """create_job과 동일한 파일명 포맷으로 잡을 배치(find_latest_job_file가 파일명으로 매칭)."""
    slug = _job_slug(job_url)
    safe = _sanitize_fragment(slug)
    (jobs_dir / f"job_impact_{ts}_{safe}_{uid}.json").write_text(json.dumps({
        "job_id": f"impact_{ts}_{safe}_{uid}",
        "scm_id": slug,
        "trigger_type": trigger_type,
        "status": status,
        "result": {"ok": ok, "data": payload},
    }), encoding="utf-8")


class TestAggregateStatsCodeMetricsLinkage:
    def test_qac_fallback_project_gets_code_metrics_and_diagnostics(self, tmp_path):
        # KJPDS02_PV: 이전엔 loc=0/functions=0/diagnostics=0으로 빠지던 것이 QAC 폴백으로 채워져야 한다.
        url = "http://192.168.110.40:7000/job/KJPDS02_PV/"
        _place_summary(tmp_path, url, _KJPDS_SUMMARY)
        r = aggregate_stats({"job_urls": [url], "cache_root": str(tmp_path)})
        p = _project_by_name(r, "KJPDS02_PV")
        assert p["loc"] == 67464
        assert p["functions"] == 881
        assert p["diagnostics"] == 496          # RCR "Diagnostic Count" (Helix는 CRR 없음)
        assert p["code_metrics_source"] == "qac"
        assert p["rcr_compliance_index"] == 92

    def test_lizard_project_unchanged_no_regression(self, tmp_path):
        # HDPDM01: complexity.csv 유래 값 유지 + source='lizard', diagnostics는 RCR/CRR 동일(577).
        url = "http://192.168.110.40:7000/job/HDPDM01_PDS64_RD/"
        _place_summary(tmp_path, url, _HDPDM_SUMMARY)
        r = aggregate_stats({"job_urls": [url], "cache_root": str(tmp_path)})
        p = _project_by_name(r, "HDPDM01_PDS64_RD")
        assert (p["loc"], p["functions"]) == (4429, 349)
        assert p["diagnostics"] == 577
        assert p["code_metrics_source"] == "lizard"

    def test_rcr_zero_diagnostics_not_overridden_by_crr(self, tmp_path):
        # 회귀 가드: RCR 진단이 실제 0건이면 CRR로 폴백하지 않는다(진짜 0을 부재로 오인 금지).
        # 과거 `_safe_int(rcr) or _safe_int(crr)` 패턴이면 0이 falsy라 crr=999로 넘어갔다.
        url = "http://192.168.110.40:7000/job/ZERO/"
        summary = {
            "jenkins": {"build_number": 1, "result": "SUCCESS"},
            "coverage": {}, "tests": {},
            "code_metrics": {"code_files": 5, "functions": 10, "nloc": 100},
            "prqa": {
                "rcr": {"ok": True, "summary": {"Diagnostic Count": 0, "Project Compliance Index": 100}},
                "crr": {"diagnostic_count": 999},
            },
        }
        _place_summary(tmp_path, url, summary)
        r = aggregate_stats({"job_urls": [url], "cache_root": str(tmp_path)})
        assert _project_by_name(r, "ZERO")["diagnostics"] == 0

    def test_completely_absent_marks_reason(self, tmp_path):
        # lizard도 QAC도 없는 프로젝트: loc=0·source=None·reason 전달(프론트 '미집계' 각주용).
        url = "http://192.168.110.40:7000/job/NODATA/"
        summary = {
            "jenkins": {"build_number": 1, "result": "SUCCESS"},
            "coverage": {}, "tests": {},
            "code_metrics": {"code_files": None, "functions": None, "nloc": None},
            "prqa": {},
        }
        _place_summary(tmp_path, url, summary)
        p = _project_by_name(aggregate_stats({"job_urls": [url], "cache_root": str(tmp_path)}), "NODATA")
        assert p["loc"] == 0 and p["code_metrics_source"] is None
        assert p["code_metrics_reason"] == "no_complexity_csv_and_no_qac"

    def test_aggregate_totals_include_qac_fallback(self, tmp_path):
        # 상단 누적(code_metrics.total_nloc / prqa.total_diagnostics)도 QAC 폴백을 반영해야 한다.
        u1 = "http://192.168.110.40:7000/job/KJPDS02_PV/"
        u2 = "http://192.168.110.40:7000/job/HDPDM01_PDS64_RD/"
        _place_summary(tmp_path, u1, _KJPDS_SUMMARY)
        _place_summary(tmp_path, u2, _HDPDM_SUMMARY)
        r = aggregate_stats({"job_urls": [u1, u2], "cache_root": str(tmp_path)})
        assert r["project_count"] == 2
        assert r["code_metrics"]["total_nloc"] == 67464 + 4429
        assert r["code_metrics"]["total_functions"] == 881 + 349
        assert r["prqa"]["total_diagnostics"] == 496 + 577


class TestAggregateStatsScmHistoryLinkage:
    """SCM 로드 이력(reports/impact_jobs 완료 vectorcast 잡) → 대시보드 커버리지/TC 연계."""

    def test_scm_history_fills_coverage_and_tests(self, tmp_path, _isolate_scm_job_history):
        # KJPDS02_PV: 빌드엔 coverage/tests가 비어 0이던 것이 SCM 로드 이력에서 채워져야 한다.
        url = "http://192.168.110.40:7000/job/KJPDS02_PV/"
        _place_summary(tmp_path, url, _KJPDS_SUMMARY)
        _place_vcast_job(_isolate_scm_job_history, url, _KJPDS_VCAST_PAYLOAD)
        p = _project_by_name(aggregate_stats({"job_urls": [url], "cache_root": str(tmp_path)}), "KJPDS02_PV")
        assert p["line_rate"] == 0.995                 # coverage.statement.rate
        assert (p["ut_total"], p["it_total"]) == (120, 45)
        assert p["coverage_source"] == "scm_vcast"
        assert p["tests_source"] == "scm_vcast"

    def test_build_coverage_wins_over_scm_history(self, tmp_path, _isolate_scm_job_history):
        # 빌드에 coverage/tests가 있으면 SCM 이력이 있어도 빌드값 우선(무회귀·이중집계 없음).
        url = "http://192.168.110.40:7000/job/HAS_BUILD/"
        summary = {
            "jenkins": {"build_number": 5, "result": "SUCCESS"},
            "coverage": {"line_rate": 0.71, "branch_rate": 0.60, "covered": 71, "total": 100},
            "tests": {"details": {"ut": {"testcases": {"total": 8, "ok": 8}},
                                  "it": {"testcases": {"total": 3, "ok": 3}}}},
            "code_metrics": {"code_files": 1, "functions": 2, "nloc": 3}, "prqa": {},
        }
        _place_summary(tmp_path, url, summary)
        _place_vcast_job(_isolate_scm_job_history, url, _KJPDS_VCAST_PAYLOAD)  # 존재하나 무시돼야
        p = _project_by_name(aggregate_stats({"job_urls": [url], "cache_root": str(tmp_path)}), "HAS_BUILD")
        assert p["line_rate"] == 0.71                    # SCM 0.995 아님
        assert (p["ut_total"], p["it_total"]) == (8, 3)  # SCM 120/45 아님
        assert p["coverage_source"] == "build"
        assert p["tests_source"] == "build"

    def test_build_placeholder_zero_coverage_falls_back_to_scm(self, tmp_path, _isolate_scm_job_history):
        # 실측 KJPDS02_PV: 빌드 analysis_summary가 coverage.line_rate=0.0(VectorCAST가 SCM 소스라
        # 빌드에 안 담긴 자리표시 0)이라도 SCM 이력이 있으면 실제값으로 폴백(0.0을 유효 빌드값 오인 금지).
        url = "http://192.168.110.40:7000/job/KJPDS02_PV/"
        summary = {
            "jenkins": {"build_number": 122, "result": "SUCCESS"},
            "coverage": {"line_rate": 0.0, "branch_rate": 0.0, "covered": 0, "total": 0},
            "tests": {"details": {"ut": {"testcases": {"total": 0, "ok": 0}},
                                  "it": {"testcases": {"total": 0, "ok": 0}}}},
            "code_metrics": {"code_files": None, "functions": None, "nloc": None}, "prqa": {},
        }
        _place_summary(tmp_path, url, summary)
        _place_vcast_job(_isolate_scm_job_history, url, _KJPDS_VCAST_PAYLOAD)
        p = _project_by_name(aggregate_stats({"job_urls": [url], "cache_root": str(tmp_path)}), "KJPDS02_PV")
        assert p["line_rate"] == 0.995                   # 빌드 0.0 아님 — SCM 실제값
        assert p["coverage_source"] == "scm_vcast"
        assert (p["ut_total"], p["it_total"]) == (120, 45)

    def test_no_history_stays_zero_with_none_source(self, tmp_path):
        # 이력 없음: 0으로 두되 source=None(프론트 '미집계' 각주 — 실제 0과 구분).
        url = "http://192.168.110.40:7000/job/KJPDS02_PV/"
        _place_summary(tmp_path, url, _KJPDS_SUMMARY)
        p = _project_by_name(aggregate_stats({"job_urls": [url], "cache_root": str(tmp_path)}), "KJPDS02_PV")
        assert p["line_rate"] is None
        assert (p["ut_total"], p["it_total"]) == (0, 0)
        assert p["coverage_source"] is None and p["tests_source"] is None

    def test_failed_or_nonvcast_job_not_used(self, tmp_path, _isolate_scm_job_history):
        # 미완료(failed) 잡·타 트리거(impact) 잡은 이력으로 인정하지 않는다.
        url = "http://192.168.110.40:7000/job/KJPDS02_PV/"
        _place_summary(tmp_path, url, _KJPDS_SUMMARY)
        _place_vcast_job(_isolate_scm_job_history, url, _KJPDS_VCAST_PAYLOAD, status="failed", ts="20260720_101010", uid="dead0001")
        _place_vcast_job(_isolate_scm_job_history, url, _KJPDS_VCAST_PAYLOAD, trigger_type="impact", ts="20260720_090000", uid="dead0002")
        p = _project_by_name(aggregate_stats({"job_urls": [url], "cache_root": str(tmp_path)}), "KJPDS02_PV")
        assert p["coverage_source"] is None            # 완료 vectorcast 잡 없음

    def test_latest_completed_job_wins(self, tmp_path, _isolate_scm_job_history):
        # 같은 slug의 완료 잡이 여럿이면 파일명 타임스탬프 최신이 이긴다.
        url = "http://192.168.110.40:7000/job/KJPDS02_PV/"
        _place_summary(tmp_path, url, _KJPDS_SUMMARY)
        stale = {**_KJPDS_VCAST_PAYLOAD, "coverage": {
            "statement": {"covered": 1, "total": 100, "rate": 0.01},
            "branch": {"covered": 0, "total": 0, "rate": None},
            "mcdc": {"covered": 0, "total": 0, "rate": None}}}
        _place_vcast_job(_isolate_scm_job_history, url, stale, ts="20260101_000000", uid="0ld00001")
        _place_vcast_job(_isolate_scm_job_history, url, _KJPDS_VCAST_PAYLOAD, ts="20260720_101010", uid="new00001")
        p = _project_by_name(aggregate_stats({"job_urls": [url], "cache_root": str(tmp_path)}), "KJPDS02_PV")
        assert p["line_rate"] == 0.995                 # 최신(0.995) — stale(0.01) 아님

    def test_top_level_totals_include_scm_history(self, tmp_path, _isolate_scm_job_history):
        # 상단 누적(avg_line_rate·total_ut/it_cases)도 SCM 폴백을 반영해야 한다.
        u1 = "http://192.168.110.40:7000/job/KJPDS02_PV/"
        u2 = "http://192.168.110.40:7000/job/HDPDM01_PDS64_RD/"
        _place_summary(tmp_path, u1, _KJPDS_SUMMARY)
        _place_summary(tmp_path, u2, _HDPDM_SUMMARY)
        _place_vcast_job(_isolate_scm_job_history, u1, _KJPDS_VCAST_PAYLOAD)
        r = aggregate_stats({"job_urls": [u1, u2], "cache_root": str(tmp_path)})
        assert r["tests"]["total_ut_cases"] == 120     # KJPDS SCM UT + HDPDM(빌드 tests 없음) 0
        assert r["tests"]["total_it_cases"] == 45
        assert r["coverage"]["avg_line_rate"] == 0.995  # KJPDS만 non-null

    def test_failed_latest_falls_back_to_older_completed(self, tmp_path, _isolate_scm_job_history):
        # 가용성 우선: 최신 잡이 실패(cloudium timeout 등)여도 직전 성공 완료 잡으로 폴백.
        url = "http://192.168.110.40:7000/job/KJPDS02_PV/"
        _place_summary(tmp_path, url, _KJPDS_SUMMARY)
        _place_vcast_job(_isolate_scm_job_history, url, _KJPDS_VCAST_PAYLOAD, ts="20260101_000000", uid="old00001")
        _place_vcast_job(_isolate_scm_job_history, url, {}, status="failed", ts="20260720_101010", uid="fail0001")
        p = _project_by_name(aggregate_stats({"job_urls": [url], "cache_root": str(tmp_path)}), "KJPDS02_PV")
        assert p["coverage_source"] == "scm_vcast"      # 실패 최신을 건너뛰고 완료 구잡 사용
        assert (p["ut_total"], p["it_total"]) == (120, 45)

    def test_merged_legacy_payload_splits_ut_it_in_aggregate(self, tmp_path, _isolate_scm_job_history):
        # 병합 legacy payload(vcast_kind·split필드 없음, test_rows source만)도 UT/IT가 올바로 분리(Critical).
        url = "http://192.168.110.40:7000/job/KJPDS02_PV/"
        _place_summary(tmp_path, url, _KJPDS_SUMMARY)
        legacy = {
            "coverage": {"statement": {"covered": 70, "total": 100, "rate": 0.7},
                         "branch": {"covered": 0, "total": 0, "rate": None},
                         "mcdc": {"covered": 0, "total": 0, "rate": None}},
            "test_rows_count": 4,
            "test_rows": [{"source": "UT"}, {"source": "UT"}, {"source": "UT"}, {"source": "IT"}],
        }
        _place_vcast_job(_isolate_scm_job_history, url, legacy)
        p = _project_by_name(aggregate_stats({"job_urls": [url], "cache_root": str(tmp_path)}), "KJPDS02_PV")
        assert (p["ut_total"], p["it_total"]) == (3, 1)   # kind 추정이었으면 (4, 0)로 오귀속됐음
        assert p["line_rate"] == 0.7 and p["coverage_source"] == "scm_vcast"


class TestScmVcastSummaryEndpoint:
    """scm_vcast_summary — 단일 프로젝트 '빌드 & 아티팩트 요약' 카드용 SCM 이력 결과값(결합 합부 포함)."""

    def test_returns_metrics_with_combined_passfail(self, _isolate_scm_job_history):
        # 실측 KJPDS02_PV shape(병합 payload) — 결합 summary의 passed/failed/pass_rate를 카드에 공급.
        url = "http://192.168.110.40:7000/job/KJPDS02_PV/"
        payload = {
            "coverage": {"statement": {"covered": 12428, "total": 17572, "rate": 0.7073},
                         "branch": {"covered": 0, "total": 0, "rate": None},
                         "mcdc": {"covered": 0, "total": 0, "rate": None}},
            "test_rows_count_ut": 6886, "test_rows_count_it": 616,
            "summary": {"total": 7502, "passed": 7480, "failed": 22, "skipped": 0,
                        "unknown": 0, "pass_rate": 0.9971},
            "summary_ut": {"total": 6886, "passed": 6870, "failed": 16, "pass_rate": 0.9977},
            "summary_it": {"total": 616, "passed": 610, "failed": 6, "pass_rate": 0.9903},
        }
        _place_vcast_job(_isolate_scm_job_history, url, payload)
        r = scm_vcast_summary({"job_url": url})
        assert r["available"] is True
        assert (r["ut_total"], r["it_total"]) == (6886, 616)
        assert (r["passed"], r["failed"]) == (7480, 22)     # 결합 summary(카드 '통과/실패')
        assert r["pass_rate"] == 0.9971
        assert r["line_rate"] == 0.7073

    def test_no_history_available_false(self):
        # 이력 없음(autouse fixture가 빈 JOB_DIR로 격리) → available=false (프론트가 빌드 폴백).
        r = scm_vcast_summary({"job_url": "http://192.168.110.40:7000/job/KJPDS02_PV/"})
        assert r == {"available": False}

    def test_missing_or_blank_job_url(self):
        assert scm_vcast_summary({})["available"] is False
        assert scm_vcast_summary({"job_url": "   "})["available"] is False

    def test_failed_job_not_used(self, _isolate_scm_job_history):
        # 미완료(failed) 잡은 카드에도 쓰지 않는다(집계와 동일 규칙).
        url = "http://192.168.110.40:7000/job/KJPDS02_PV/"
        _place_vcast_job(_isolate_scm_job_history, url, _KJPDS_VCAST_PAYLOAD,
                         status="failed", uid="f0000001")
        assert scm_vcast_summary({"job_url": url})["available"] is False
