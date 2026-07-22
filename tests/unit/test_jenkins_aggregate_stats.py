"""aggregate_stats 엔드포인트 — 대시보드 집계가 상세탭(build_report_summary)과 동일 해석을 쓰는지.

핵심 회귀 방지: 코드규모(LOC/함수)·PRQA 진단이 lizard 부재 프로젝트(KJPDS02_PV류)에서
QAC 폴백으로 채워지고, lizard 있는 프로젝트(HDPDM01류)는 기존값을 그대로 유지하는지.
"""
import json

from backend.routers.jenkins import aggregate_stats
from backend.services.jenkins_helpers import _job_slug

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
