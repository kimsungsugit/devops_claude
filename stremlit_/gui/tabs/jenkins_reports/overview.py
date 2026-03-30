# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

import pandas as pd
import streamlit as st


def _top_n(df: pd.DataFrame, col: str, n: int = 15) -> pd.DataFrame:
    if df is None or df.empty or col not in df.columns:
        return pd.DataFrame()
    return df.sort_values(col, ascending=False).head(n)


def _build_kpi_df(jscan: dict) -> pd.DataFrame:
    summ = (jscan or {}).get("summary", {})
    rows = [
        {"KPI": "FAIL", "count": int(summ.get("FAIL_token", 0))},
        {"KPI": "ERROR", "count": int(summ.get("ERROR_token", 0))},
        {"KPI": "WARN", "count": int(summ.get("WARN_token", 0))},
        {"KPI": "PASS", "count": int(summ.get("PASS_token", 0))},
    ]
    return pd.DataFrame(rows)


def _build_ext_df(jscan: dict) -> pd.DataFrame:
    summ = (jscan or {}).get("summary", {})
    ext = (summ or {}).get("ext_counts", {}) or {}
    rows = [{"ext": k, "count": int(v)} for k, v in ext.items()]
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("count", ascending=False).head(25)
    return df


def _render_overview(summary: dict):
    j = (summary or {}).get("jenkins", {}) or {}
    cov = (summary or {}).get("coverage", {}) or {}
    tests = (summary or {}).get("tests", {}) or {}

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("빌드 번호", str(j.get("build_number", "-")))
        st.caption(j.get("job_url", ""))
    with c2:
        st.metric("빌드 결과", str(j.get("result") or ""))
        st.caption(j.get("build_url", ""))
    with c3:
        rate = cov.get("line_rate")
        thr = cov.get("threshold")
        st.metric("라인 커버리지", f"{(float(rate) * 100.0):.1f}%" if isinstance(rate, (int, float)) else "-")
        st.caption(f"threshold {(float(thr) * 100.0):.1f}%" if isinstance(thr, (int, float)) else "")
    with c4:
        ok = tests.get("ok")
        st.metric("테스트", "OK" if ok else "FAIL")
        basis = cov.get("basis", "")
        st.caption(basis)

    # progress bars
    if isinstance(cov.get("line_rate"), (int, float)):
        st.progress(min(max(float(cov["line_rate"]), 0.0), 1.0), text=f"Line: {float(cov['line_rate'])*100.0:.1f}%")
    if isinstance(cov.get("branch_rate"), (int, float)):
        st.progress(min(max(float(cov["branch_rate"]), 0.0), 1.0), text=f"Branch: {float(cov['branch_rate'])*100.0:.1f}%")
    if isinstance(cov.get("call_rate"), (int, float)):
        st.progress(min(max(float(cov["call_rate"]), 0.0), 1.0), text=f"Call: {float(cov['call_rate'])*100.0:.1f}%")


# -----------------------------------------------------------------------------
# Jenkins 캐시 빌드 히스토리(다운로드된 build_* 폴더 기준)
# -----------------------------------------------------------------------------


def _scan_cached_builds_from_build_root(broot: Optional[Path]) -> pd.DataFrame:
    if broot is None:
        return pd.DataFrame()
    p = Path(broot)
    job_dir = p.parent if p.name.startswith("build_") else p
    if not job_dir.exists():
        return pd.DataFrame()

    rows: List[dict] = []
    for d in job_dir.glob("build_*"):
        if not d.is_dir():
            continue
        m = re.match(r"build_(\d+)", d.name)
        bnum = int(m.group(1)) if m else -1

        # 기본 메타(폴더 mtime)
        dt = datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

        rep_dir = d / "reports"
        summ_p = rep_dir / "analysis_summary.json"
        status_p = rep_dir / "status.json"

        result = ""
        tests_fail = None
        cov_line = None
        prqa_total = None

        if summ_p.exists():
            try:
                summ = json.loads(summ_p.read_text(encoding="utf-8", errors="ignore"))
                # Jenkins build result
                jb = summ.get("jenkins_build") or summ.get("build") or {}
                if isinstance(jb, dict):
                    result = str(jb.get("result") or jb.get("status") or "")
                # tests
                tests = summ.get("tests") or {}
                if isinstance(tests, dict):
                    tests_fail = tests.get("failed") or tests.get("failures")
                # coverage
                cov = summ.get("coverage") or {}
                if isinstance(cov, dict):
                    cov_line = cov.get("line_rate") or cov.get("line") or cov.get("line_coverage")
                # prqa totals(있으면)
                prqa = summ.get("prqa") or {}
                if isinstance(prqa, dict):
                    prqa_total = prqa.get("total") or prqa.get("violations_total")
            except Exception:
                pass

        if status_p.exists() and not result:
            try:
                stj = json.loads(status_p.read_text(encoding="utf-8", errors="ignore"))
                if isinstance(stj, dict):
                    result = str(stj.get("result") or stj.get("status") or result)
            except Exception:
                pass

        rows.append(
            {
                "build": bnum if bnum >= 0 else d.name,
                "mtime": dt,
                "result": result,
                "tests_failed": tests_fail,
                "coverage_line": cov_line,
                "prqa_total": prqa_total,
                "reports_dir": str(rep_dir) if rep_dir.exists() else "",
            }
        )

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # 정렬: build 번호 내림차순
    if "build" in df.columns:
        # build가 숫자 아닌 경우 대비
        try:
            df["_build_num"] = pd.to_numeric(df["build"], errors="coerce")
            df = df.sort_values(["_build_num", "mtime"], ascending=[False, False]).drop(columns=["_build_num"])
        except Exception:
            df = df.sort_values("mtime", ascending=False)
    return df


def _render_build_history(broot: Optional[Path]) -> None:
    st.subheader("📅 빌드 히스토리(캐시 기준)")
    df = _scan_cached_builds_from_build_root(broot)
    if df.empty:
        st.info("캐시된 build_* 폴더 미발견, Sync를 여러 빌드에 대해 수행 시 표시")
        return
    st.dataframe(df, width="stretch", height=360)
    # 간단 차트
    if "tests_failed" in df.columns:
        try:
            dft = df[["build", "tests_failed"]].copy()
            dft["tests_failed"] = pd.to_numeric(dft["tests_failed"], errors="coerce")
            dft = dft.dropna()
            if not dft.empty:
                st.bar_chart(dft.set_index("build")[["tests_failed"]], height=240)
        except Exception:
            pass
    if "coverage_line" in df.columns:
        try:
            dfc = df[["build", "coverage_line"]].copy()
            dfc["coverage_line"] = pd.to_numeric(dfc["coverage_line"], errors="coerce")
            dfc = dfc.dropna()
            if not dfc.empty:
                st.bar_chart(dfc.set_index("build")[["coverage_line"]], height=240)
        except Exception:
            pass


__all__ = [
    "_top_n",
    "_build_kpi_df",
    "_build_ext_df",
    "_render_overview",
    "_scan_cached_builds_from_build_root",
    "_render_build_history",
]
