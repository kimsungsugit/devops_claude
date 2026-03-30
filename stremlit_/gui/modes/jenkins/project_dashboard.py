# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
import streamlit as st

try:
    import plotly.express as px  # type: ignore
    import plotly.graph_objects as go  # type: ignore
except Exception:  # pragma: no cover
    px = None  # type: ignore
    go = None  # type: ignore

import gui_utils

from .helpers import _detect_reports_dir


def _render_jenkins_project_dashboard(ctx: Dict[str, Any]) -> None:
    """
    Jenkins Viewer - 프로젝트(잡) 단위 대시보드
    목표
    - 로컬 분석 전용 UI 제거, Jenkins 캐시(build_*) 기준 요약/추세 제공
    - build_*/reports/jenkins_scan.json / analysis_summary.json / status.json 기반으로 빠르게 집계
    """
    job_name = str(ctx.get("job_name") or "")
    job_url = str(ctx.get("job_url") or "")
    job_cache_dir = Path(str(ctx.get("job_cache_dir") or "")).expanduser()

    st.subheader("📌 프로젝트 대시보드(Jenkins)")
    if job_name:
        st.caption(f"{job_name}  ·  {job_url}".strip("  · "))
    else:
        st.caption(job_url)

    if not job_cache_dir.exists():
        st.info("캐시 디렉터리 없음, 사이드바에서 Sync 실행 필요")
        return

    # -------------------------
    # 1) build_* 수집
    # -------------------------
    build_dirs: List[Tuple[int, Path]] = []
    for d in sorted(job_cache_dir.glob("build_*")):
        try:
            num = int(str(d.name).split("_", 1)[-1])
            build_dirs.append((num, d))
        except Exception:
            continue
    build_dirs.sort(key=lambda x: x[0], reverse=True)

    if not build_dirs:
        st.info("캐시에 build_* 없음, 사이드바에서 Sync 실행 필요")
        return

    # 표시 범위 선택
    max_n = len(build_dirs)
    if max_n <= 1:
        n = 1
        st.caption("표시 빌드 수: 1")
    else:
        default_n = 30 if max_n >= 30 else max_n
        # Streamlit slider는 min < max 조건 필요
        n = st.slider("표시 빌드 수", min_value=1, max_value=max_n, value=default_n, step=1, key="jenkins_proj_n")
    sel = build_dirs[: int(n)]

    # -------------------------
    # 2) 빌드 요약 로드(빠른 경로)
    # -------------------------
    def _read_json(p: Path) -> Dict[str, Any]:
        try:
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return {}
        return {}

    def _any_match(paths: List[str], *, contains_any: List[str] = None, ends_any: List[str] = None) -> int:
        contains_any = contains_any or []
        ends_any = ends_any or []
        c = 0
        for s in paths or []:
            low = str(s).lower()
            ok = False
            for t in contains_any:
                if t and t.lower() in low:
                    ok = True
                    break
            if not ok:
                for e in ends_any:
                    if e and low.endswith(e.lower()):
                        ok = True
                        break
            if ok:
                c += 1
        return int(c)

    rows: List[Dict[str, Any]] = []
    all_source_roots: List[str] = []

    for num, d in sel:
        rep = _detect_reports_dir(d)
        status = _read_json(rep / "status.json")
        summary = _read_json(rep / "analysis_summary.json")
        jscan = _read_json(rep / "jenkins_scan.json")

        # status/result/timestamp
        result = str(status.get("result") or status.get("status") or "")
        if not result:
            # BUILDING 표시 (Jenkins result null 케이스)
            try:
                bld = bool(status.get("building")) if isinstance(status, dict) else False
                if not bld:
                    j = summary.get("jenkins") or {}
                    if isinstance(j, dict):
                        bld = bool(j.get("building"))
                if not result and bld:
                    result = "BUILDING"
            except Exception:
                pass
            try:
                j = summary.get("jenkins") or {}
                if isinstance(j, dict):
                    result = str(j.get("result") or "")
            except Exception:
                pass

        ts = str(status.get("timestamp") or status.get("generated_at") or "")
        if not ts:
            try:
                ts = str(summary.get("generated_at") or summary.get("timestamp") or "")
            except Exception:
                ts = ""

        # Jenkins timestamp(ms epoch) -> ISO
        try:
            if ts and re.fullmatch(r"\d{10,}", ts):
                tsv = float(ts)
                if tsv > 1e12:
                    ts = datetime.fromtimestamp(tsv / 1000.0).isoformat(timespec="seconds")
        except Exception:
            pass
        if not ts:
            try:
                ts = datetime.fromtimestamp(d.stat().st_mtime).isoformat(timespec="seconds")
            except Exception:
                ts = ""

        # coverage
        cov = summary.get("coverage") or {}
        line_rate = cov.get("line_rate_pct")
        if line_rate is None:
            line_rate = cov.get("line_rate")
        branch_rate = cov.get("branch_rate")
        try:
            line_rate = float(line_rate) if line_rate is not None else None
        except Exception:
            line_rate = None
        try:
            branch_rate = float(branch_rate) if branch_rate is not None else None
        except Exception:
            branch_rate = None

        # findings count
        static = summary.get("static") or {}
        findings_cnt = static.get("findings") or static.get("total_findings") or summary.get("findings_total")
        try:
            findings_cnt = int(findings_cnt) if findings_cnt is not None else None
        except Exception:
            findings_cnt = None

        # dynamic totals (asan/timeout/assert/crc/ubsan)
        dyn = summary.get("dynamic") or summary.get("runtime") or {}
        dyn_total = 0
        if isinstance(dyn, dict):
            for k in ["asan", "timeout", "assert", "crc_mismatch", "ubsan", "hardfault", "busfault"]:
                v = dyn.get(k)
                if isinstance(v, dict) and "count" in v:
                    try:
                        dyn_total += int(v.get("count") or 0)
                    except Exception:
                        pass
                elif isinstance(v, list):
                    dyn_total += len(v)

        # scan 기반 tool presence
        files = (jscan.get("files") or {}) if isinstance(jscan, dict) else {}
        htmls = files.get("html") or []
        xlsxs = files.get("xlsx") or []
        others = files.get("other") or []
        all_files = []
        try:
            all_files = list(htmls) + list(xlsxs) + list(others)
        except Exception:
            all_files = []

        # ext summary
        summ = jscan.get("summary") or {}
        bytes_total = summ.get("bytes_total")
        files_total = summ.get("files_total")
        try:
            bytes_total = int(bytes_total) if bytes_total is not None else None
        except Exception:
            bytes_total = None
        try:
            files_total = int(files_total) if files_total is not None else None
        except Exception:
            files_total = None

        # QAC summary(있으면)
        qsum = _read_json(rep / "qac_rcr_summary.json")
        if not qsum:
            try:
                prqa = summary.get("prqa") if isinstance(summary, dict) else None
                rcr = prqa.get("rcr") if isinstance(prqa, dict) else None
                qsum = (rcr.get("summary") if isinstance(rcr, dict) else {}) or {}
            except Exception:
                qsum = {}
        mand = None
        req = None
        try:
            it = qsum.get("importance_totals") or {}
            if isinstance(it, dict):
                for k, v in it.items():
                    if "Mandatory" in str(k):
                        mand = int(v)
                    if "Required" in str(k):
                        req = int(v)
        except Exception:
            pass
        if mand is None:
            try:
                diag = qsum.get("Diagnostic Count")
                if diag is None:
                    diag = qsum.get("diagnostic_count")
                mand = int(diag) if diag is not None else None
            except Exception:
                mand = mand

        # VectorCAST / HelixQAC / CodeSonar / Trace32 존재 여부(스캔 기반)
        vectorcast = _any_match(all_files, contains_any=["vectorcast", "vcast", "metrics_report", "full_report", "ut_", "it_"])
        helix = _any_match(all_files, contains_any=["_rcr_", "_hmr_", "_crr_", "helix", "qac"])
        codesonar = _any_match(all_files, contains_any=["codesonar", "code sonar"])
        trace32 = _any_match(all_files, contains_any=["trace32", "t32"], ends_any=[".cmm", ".pbi", ".t32"])

        # UT/IT 테스트케이스 요약(VectorCAST metrics 기반)
        ut_tc_ok = None
        ut_tc_total = None
        it_tc_ok = None
        it_tc_total = None
        ut_pass = None
        it_pass = None
        try:
            tblock = summary.get("tests") or {}
            details = tblock.get("details") if isinstance(tblock, dict) else {}
            if isinstance(details, dict):
                ut = details.get("ut") or {}
                it = details.get("it") or {}
                if isinstance(ut, dict):
                    tc = ut.get("testcases") or {}
                    if isinstance(tc, dict):
                        ut_tc_ok = int(tc.get("ok")) if tc.get("ok") is not None else None
                        ut_tc_total = int(tc.get("total")) if tc.get("total") is not None else None
                if isinstance(it, dict):
                    tc = it.get("testcases") or {}
                    if isinstance(tc, dict):
                        it_tc_ok = int(tc.get("ok")) if tc.get("ok") is not None else None
                        it_tc_total = int(tc.get("total")) if tc.get("total") is not None else None
            if ut_tc_total and ut_tc_total > 0 and ut_tc_ok is not None:
                ut_pass = float(ut_tc_ok) / float(ut_tc_total) * 100.0
            if it_tc_total and it_tc_total > 0 and it_tc_ok is not None:
                it_pass = float(it_tc_ok) / float(it_tc_total) * 100.0
        except Exception:
            pass

        # source roots
        sroots = jscan.get("source_roots")
        if isinstance(sroots, list):
            for s in sroots:
                s = str(s)
                if s and s not in all_source_roots:
                    all_source_roots.append(s)
        lr01 = gui_utils.normalize_rate_0_1(line_rate) if line_rate is not None else None
        br01 = gui_utils.normalize_rate_0_1(branch_rate) if branch_rate is not None else None
        # 코드 규모(가능한 경우: summary 우선, 없으면 Lizard/complexity CSV 기반)
        code_files = None
        nloc = None
        func_count = None
        try:
            cm = summary.get("code_metrics") or {}
            if isinstance(cm, dict) and (cm.get("code_files") is not None or cm.get("nloc") is not None or cm.get("functions") is not None):
                try:
                    if cm.get("code_files") is not None:
                        code_files = int(cm.get("code_files") or 0)
                except Exception:
                    code_files = None
                try:
                    if cm.get("nloc") is not None:
                        nloc = int(cm.get("nloc") or 0)
                except Exception:
                    nloc = None
                try:
                    if cm.get("functions") is not None:
                        func_count = int(cm.get("functions") or 0)
                except Exception:
                    func_count = None
            else:
                report_dir = (d / "reports")
                df_liz = gui_utils.load_lizard_dataframe(report_dir)
                if df_liz is None:
                    df_liz = gui_utils.load_lizard_dataframe(d)
                met = gui_utils.code_metrics_from_lizard(df_liz)
                try:
                    if met.get("code_files") is not None:
                        code_files = int(round(float(met.get("code_files") or 0)))
                except Exception:
                    code_files = None
                try:
                    if met.get("nloc") is not None:
                        nloc = int(round(float(met.get("nloc") or 0)))
                except Exception:
                    nloc = None
                try:
                    if met.get("functions") is not None:
                        func_count = int(round(float(met.get("functions") or 0)))
                except Exception:
                    func_count = None
        except Exception:
            pass

        rows.append(
            {
                "build": int(num),
                "result": result,
                "timestamp": ts,
                "line_rate_%": (lr01 * 100.0) if lr01 is not None else None,
                "branch_rate_%": (br01 * 100.0) if br01 is not None else None,
                "UT_pass_%": ut_pass,
                "IT_pass_%": it_pass,
                "UT_ok": ut_tc_ok,
                "UT_total": ut_tc_total,
                "IT_ok": it_tc_ok,
                "IT_total": it_tc_total,
                "findings": findings_cnt,
                "dyn_total": int(dyn_total) if dyn_total else 0,
                "QAC_Mandatory": mand,
                "QAC_Required": req,
                "VectorCAST_files": vectorcast,
                "HelixQAC_files": helix,
                "CodeSonar_files": codesonar,
                "Trace32_files": trace32,
                "files_total": files_total,
                "bytes_total": bytes_total,
                "code_files": code_files,
                "nloc": nloc,
                "functions": func_count,
                "_dir": str(d),
            }
        )

    # -------------------------
    # 3) 추세 차트
    # -------------------------
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("표시할 빌드 요약 없음")
        return

    df = df.sort_values("build")
    df_idx = df.set_index("build")

    # -------------------------
    # 2-1) 최신 빌드 함수 변경 요약
    # -------------------------
    try:
        latest_build_dir = build_dirs[0][1] if build_dirs else None
        prev_build_dir = build_dirs[1][1] if len(build_dirs) > 1 else None
        if latest_build_dir:
            latest_rep = _detect_reports_dir(latest_build_dir)
            prev_rep = _detect_reports_dir(prev_build_dir) if prev_build_dir else None
            cur_df = gui_utils.load_lizard_dataframe(latest_rep)
            if cur_df is None:
                cur_df = gui_utils.load_lizard_dataframe(latest_build_dir)
            prev_df = gui_utils.load_lizard_dataframe(prev_rep) if prev_rep else None
            if prev_df is None and prev_build_dir:
                prev_df = gui_utils.load_lizard_dataframe(prev_build_dir)
            diff = gui_utils.summarize_function_diff(cur_df, prev_df, limit=40)

            with st.expander("함수 변경 요약(최신 빌드 기준)", expanded=False):
                ac = int(diff.get("added_count") or 0)
                rc = int(diff.get("removed_count") or 0)
                mc = int(diff.get("modified_count") or 0)
                st.caption(f"추가 {ac} · 제거 {rc} · 변경 {mc}")
                c1_, c2_, c3_ = st.columns(3)
                with c1_:
                    st.caption("추가 함수")
                    for s in diff.get("added_list") or []:
                        st.write(f"- {s}")
                with c2_:
                    st.caption("제거 함수")
                    for s in diff.get("removed_list") or []:
                        st.write(f"- {s}")
                with c3_:
                    st.caption("변경 함수")
                    for s in diff.get("modified_list") or []:
                        st.write(f"- {s}")
    except Exception:
        pass

    # -------------------------
    # 3-0) KPI/요약 (통계 + 시각화)
    # -------------------------
    def _norm_result(v: Any) -> str:
        s = str(v or "").strip().upper()
        if s in ("SUCCESS", "PASSED", "PASS", "OK"):
            return "SUCCESS"
        if s in ("FAILURE", "FAILED", "FAIL", "ERROR"):
            return "FAILURE"
        if s in ("UNSTABLE",):
            return "UNSTABLE"
        if s in ("ABORTED", "CANCELED", "CANCELLED"):
            return "ABORTED"
        return s or "-"

    df["result_norm"] = df["result"].map(_norm_result)

    # pass rate / streak
    try:
        pass_rate = float((df["result_norm"] == "SUCCESS").mean() * 100.0)
    except Exception:
        pass_rate = 0.0

    streak = 0
    try:
        for r in reversed(df["result_norm"].tolist()):
            if r == "SUCCESS":
                streak += 1
            else:
                break
    except Exception:
        streak = 0

    latest = df.iloc[-1].to_dict() if len(df) >= 1 else {}
    prev = df.iloc[-2].to_dict() if len(df) >= 2 else {}

    def _clean_scalar(v: Any) -> Any:
        """None/NaN을 None으로 정규화"""
        try:
            if v is None:
                return None
            # pandas/numpy NaN 처리
            if pd.isna(v):  # type: ignore[arg-type]
                return None
        except Exception:
            pass
        return v

    def _delta(key: str) -> Any:
        try:
            a = _clean_scalar(latest.get(key))
            b = _clean_scalar(prev.get(key))
            if a is None or b is None:
                return None
            return float(a) - float(b)
        except Exception:
            return None

    def _fmt_int(v: Any) -> Any:
        v = _clean_scalar(v)
        if v is None:
            return None
        try:
            return int(round(float(v)))
        except Exception:
            return None

    def _fmt_delta_int(v: Any) -> Optional[str]:
        v = _clean_scalar(v)
        if v is None:
            return None
        try:
            return f"{int(round(float(v))):+d}"
        except Exception:
            return None

    st.markdown("##### 📊 프로젝트 KPI")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _b = _fmt_int(latest.get("build"))
        _bd = _fmt_int(_delta("build")) if len(df) >= 2 else None
        st.metric("최근 빌드", _b if _b is not None else -1, delta=_bd)
    with c2:
        st.metric("결과", str(latest.get("result_norm") or "-"), help="Jenkins result 정규화(SUCCESS/FAILURE/UNSTABLE/ABORTED)")
    with c3:
        st.metric("PASS 비율", f"{pass_rate:.1f}%", help=f"표시된 {len(df)}개 빌드 기준, 연속 PASS {streak}회")
    with c4:
        cov = _clean_scalar(latest.get("line_rate_%"))
        d = _delta("line_rate_%")
        if cov is None:
            st.metric("Coverage(line)", "N/A")
        else:
            st.metric("Coverage(line)", f"{float(cov):.1f}%", delta=(f"{float(d):+.1f}%" if d is not None else None))

    # -------------------------
    # 3-0b) 코드 규모 KPI
    # -------------------------
    st.markdown("##### 🧱 코드 규모 KPI")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        v = _fmt_int(latest.get("nloc"))
        dlt = _delta("nloc")
        st.metric("라인 수(NLOC)", v if v is not None else "N/A", delta=_fmt_delta_int(dlt))
    with c2:
        v = _fmt_int(latest.get("functions"))
        dlt = _delta("functions")
        st.metric("함수 수", v if v is not None else "N/A", delta=_fmt_delta_int(dlt))
    with c3:
        v = _fmt_int(latest.get("code_files"))
        dlt = _delta("code_files")
        st.metric("소스 파일 수", v if v is not None else "N/A", delta=_fmt_delta_int(dlt))
    with c4:
        # 함수 diff(가능한 경우: 최신 빌드 vs 이전 빌드)
        try:
            latest_dir = Path(str(latest.get("_dir") or "")).resolve()
            cur_report_dir = latest_dir / "reports"
            cur_df = gui_utils.load_lizard_dataframe(cur_report_dir)
            if cur_df is None:
                cur_df = gui_utils.load_lizard_dataframe(latest_dir)
            prev_dir = gui_utils.find_prev_build_dir(latest_dir)
            prev_df = gui_utils.load_lizard_dataframe(prev_dir / "reports") if prev_dir else None
            if prev_df is None and prev_dir:
                prev_df = gui_utils.load_lizard_dataframe(prev_dir)

            _fdiff = gui_utils.summarize_function_diff(cur_df, prev_df, limit=40)
            st.metric(
                "추가/삭제/변경 함수",
                f"+{int(_fdiff.get('added_count') or 0)} / -{int(_fdiff.get('removed_count') or 0)} / Δ{int(_fdiff.get('modified_count') or 0)}",
            )

            with st.expander("🧩 함수 변경 및 목록(최신 빌드)", expanded=False):
                t1, t2 = st.tabs(["변경", "함수 목록"])
                with t1:
                    cA, cB, cC = st.columns(3)
                    with cA:
                        st.caption("추가된 함수(상위 40)")
                        al = _fdiff.get("added_list") or []
                        if not al:
                            st.caption("추가 없음")
                        for s in al:
                            st.write(f"- {s}")
                    with cB:
                        st.caption("삭제된 함수(상위 40)")
                        rl = _fdiff.get("removed_list") or []
                        if not rl:
                            st.caption("삭제 없음")
                        for s in rl:
                            st.write(f"- {s}")
                    with cC:
                        st.caption("변경된 함수(복잡도/라인 변화, 상위 40)")
                        ml = _fdiff.get("modified_list") or []
                        if not ml:
                            st.caption("변경 없음(또는 CCN/NLOC 미제공)")
                        for s in ml:
                            st.write(f"- {s}")

                with t2:
                    df0 = gui_utils.clean_lizard_dataframe(cur_df)
                    if df0 is None:
                        st.caption("함수 목록 없음(lizard/complexity.csv 미탐지)")
                    else:
                        file_col = gui_utils._pick_column_case_insensitive(df0, ["file", "filename", "path", "source_file", "unit"])  # type: ignore[attr-defined]
                        func_col = gui_utils._pick_column_case_insensitive(df0, ["function", "function_name", "name", "subprogram"])  # type: ignore[attr-defined]
                        ccn_col = gui_utils._pick_column_case_insensitive(df0, ["ccn", "cyclomatic_complexity", "complexity", "v(g)", "vg"])  # type: ignore[attr-defined]
                        nloc_col = gui_utils._pick_column_case_insensitive(df0, ["nloc", "loc", "lines", "line_count"])  # type: ignore[attr-defined]

                        cols = [c for c in [file_col, func_col, ccn_col, nloc_col] if c and c in df0.columns]
                        view = df0[cols].copy() if cols else df0.copy()

                        c1_, c2_, c3_ = st.columns(3)
                        with c1_:
                            file_opts = ["(All)"] + sorted({str(x) for x in view[file_col].unique()}) if file_col and file_col in view.columns else ["(All)"]
                            sel_file = st.selectbox("File", options=file_opts, index=0, key="proj_func_file")
                        with c2_:
                            q = st.text_input("Search(Function)", value="", key="proj_func_q")
                        with c3_:
                            sort_mode = st.selectbox("Sort", options=["file/function", "NLOC desc", "CCN desc"], index=0, key="proj_func_sort")

                        try:
                            limit_n = int(st.slider("Rows", min_value=50, max_value=2000, value=200, step=50, key="proj_func_rows"))
                        except Exception:
                            limit_n = 200

                        if file_col and sel_file != "(All)":
                            view = view[view[file_col].astype(str) == str(sel_file)]
                        if func_col and q.strip():
                            qq = q.strip().lower()
                            view = view[view[func_col].astype(str).str.lower().str.contains(qq, na=False)]

                        if sort_mode == "NLOC desc" and nloc_col and nloc_col in view.columns:
                            view["_nloc"] = pd.to_numeric(view[nloc_col], errors="coerce").fillna(0)
                            view = view.sort_values("_nloc", ascending=False).drop(columns=["_nloc"], errors="ignore")
                        elif sort_mode == "CCN desc" and ccn_col and ccn_col in view.columns:
                            view["_ccn"] = pd.to_numeric(view[ccn_col], errors="coerce").fillna(0)
                            view = view.sort_values("_ccn", ascending=False).drop(columns=["_ccn"], errors="ignore")
                        else:
                            if file_col and func_col and file_col in view.columns and func_col in view.columns:
                                view = view.sort_values([file_col, func_col], ascending=True)

                        st.dataframe(view.head(limit_n), width="stretch", height=420)
        except Exception:
            st.metric("추가/삭제/변경 함수", "N/A")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        v = latest.get("findings")
        d = _delta("findings")
        st.metric("Findings", int(v or 0), delta=(int(d) if d is not None else None))
    with c2:
        v = latest.get("dyn_total")
        d = _delta("dyn_total")
        st.metric("Dynamic Total", int(v or 0), delta=(int(d) if d is not None else None))
    with c3:
        v = latest.get("QAC_Mandatory")
        d = _delta("QAC_Mandatory")
        st.metric("QAC Mandatory", int(v or 0), delta=(int(d) if d is not None else None))
    with c4:
        v = latest.get("bytes_total")
        if v is None:
            st.metric("Artifacts Size", "N/A")
        else:
            try:
                mb = float(v) / (1024.0 * 1024.0)
                st.metric("Artifacts Size", f"{mb:.1f} MB")
            except Exception:
                st.metric("Artifacts Size", str(v))

    # 통계표
    st.markdown("##### 🧮 요약 통계(표시 빌드 기준)")
    stat_cols = [c for c in ["findings", "dyn_total", "line_rate_%", "branch_rate_%", "QAC_Mandatory", "QAC_Required", "code_files", "nloc", "functions"] if c in df.columns]
    if stat_cols:
        try:
            sdf = df[stat_cols].copy()
            for c in stat_cols:
                sdf[c] = pd.to_numeric(sdf[c], errors="coerce")
            desc = sdf.describe(percentiles=[0.25, 0.5, 0.75]).T
            desc = desc.rename(columns={"50%": "median"}).loc[:, [c for c in ["count", "mean", "std", "min", "25%", "median", "75%", "max"] if c in desc.columns]]
            st.dataframe(desc.round(3), width="stretch", height=360)
        except Exception:
            st.info("요약 통계 생성 실패")
    else:
        st.info("통계 대상 컬럼 없음")

    # 시각화(가능 시)
    st.markdown("##### 🧭 시각화")
    if px is not None and go is not None:
        try:
            c1, c2 = st.columns(2)
            with c1:
                # 결과 타임라인
                dfx = df.copy()
                dfx["pass_flag"] = (dfx["result_norm"] == "SUCCESS").astype(int)
                fig = px.scatter(
                    dfx,
                    x="build",
                    y="pass_flag",
                    color="result_norm",
                    hover_data=["timestamp", "findings", "dyn_total", "line_rate_%"],
                    title="Result Timeline",
                )
                fig.update_yaxes(tickvals=[0, 1], ticktext=["FAIL", "PASS"])
                st.plotly_chart(fig, width="stretch")
            with c2:
                # Findings/Dynamic 추세(Plotly)
                y_cols = [c for c in ["findings", "dyn_total"] if c in df.columns]
                if y_cols:
                    fig = go.Figure()
                    for c in y_cols:
                        fig.add_trace(go.Scatter(x=df["build"], y=df[c], mode="lines+markers", name=c))
                    fig.update_layout(title="Findings & Dynamic Trend", xaxis_title="build")
                    st.plotly_chart(fig, width="stretch")
                else:
                    st.info("추세 지표 없음")
        except Exception:
            st.info("Plotly 시각화 생성 실패, 기본 차트로 표시")

        # 상관/분포
        try:
            c1, c2 = st.columns(2)
            with c1:
                if "line_rate_%" in df.columns and "findings" in df.columns:
                    fig = px.scatter(
                        df,
                        x="line_rate_%",
                        y="findings",
                        color="result_norm",
                        hover_data=["build", "timestamp"],
                        title="Coverage vs Findings",
                    )
                    st.plotly_chart(fig, width="stretch")
            with c2:
                if "findings" in df.columns:
                    fig = px.box(df, y="findings", color="result_norm", title="Findings Distribution")
                    st.plotly_chart(fig, width="stretch")
        except Exception:
            pass

        # 툴 리포트 존재율 히트맵
        try:
            tool_cols = [c for c in ["VectorCAST_files", "HelixQAC_files", "CodeSonar_files", "Trace32_files"] if c in df.columns]
            if tool_cols:
                mat = df[["build"] + tool_cols].copy()
                for c in tool_cols:
                    mat[c] = pd.to_numeric(mat[c], errors="coerce").fillna(0).astype(int)
                    mat[c] = (mat[c] > 0).astype(int)
                mat = mat.set_index("build").T
                fig = px.imshow(mat, aspect="auto", title="Tool Report Presence (1=present)")
                st.plotly_chart(fig, width="stretch")
        except Exception:
            pass
    else:
        st.info("Plotly 미설치/비활성 상태, 기본 차트만 표시")

    st.markdown("##### 📈 추세")
    c1, c2 = st.columns(2)
    with c1:
        cols = [c for c in ["findings", "dyn_total", "QAC_Mandatory", "QAC_Required"] if c in df_idx.columns]
        if cols:
            st.line_chart(df_idx[cols])
        else:
            st.info("추세 데이터 없음")
    with c2:
        cov_cols = [c for c in ["line_rate_%", "branch_rate_%"] if c in df_idx.columns]
        if cov_cols:
            st.line_chart(df_idx[cov_cols])
        else:
            st.info("커버리지 데이터 없음")

    # 코드 규모 추세(요약) - PM/개발자/테스터 공통 지표
    with st.expander("🧱 코드 규모 추세", expanded=False):
        try:
            if "nloc" in df_idx.columns:
                st.caption("라인 수(NLOC)")
                st.line_chart(df_idx[["nloc"]])
            if "functions" in df_idx.columns:
                st.caption("함수 수")
                st.line_chart(df_idx[["functions"]])
            if "code_files" in df_idx.columns:
                st.caption("소스 파일 수")
                st.line_chart(df_idx[["code_files"]])
        except Exception:
            st.info("코드 규모 추세 생성 실패")

    # source_roots 표시
    if all_source_roots:
        with st.expander("📁 자동 탐지된 소스 루트", expanded=False):
            for s in all_source_roots[:50]:
                st.write(f"- {s}")
            if len(all_source_roots) > 50:
                st.caption(f"+{len(all_source_roots) - 50} more")

    st.divider()
    st.markdown("##### 🧾 빌드 목록")
    show_cols = [c for c in ["build", "result", "timestamp", "line_rate_%", "branch_rate_%", "findings", "dyn_total", "QAC_Mandatory", "QAC_Required", "code_files", "nloc", "functions"] if c in df.columns]
    st.dataframe(df[show_cols], width="stretch")

    # -------------------------
    # 4) 빌드 선택/전환
    # -------------------------
    current = int(st.session_state.get("jenkins_last_build") or df["build"].max())
    build_options = list(reversed(sorted(df["build"].astype(int).tolist())))
    pick = st.selectbox("빌드 선택", build_options, index=(build_options.index(current) if current in build_options else 0), key="jenkins_pick_build")

    col1, col2 = st.columns([2, 1])
    with col1:
        st.caption("선택 빌드로 전환 시 빌드 대시보드/로그/리포트가 해당 build_* 기준으로 갱신")
    with col2:
        if st.button("열기", type="primary", width="stretch"):
            target = df[df["build"].astype(int) == int(pick)]
            if not target.empty:
                root = Path(str(target.iloc[0].get("_dir"))).resolve()
                st.session_state["jenkins_last_build"] = int(pick)
                st.session_state["jenkins_build_root"] = str(root)
                rep = _detect_reports_dir(root)
                st.session_state["jenkins_reports_dir"] = str(rep)
                st.session_state["jenkins_build_selector"] = str(int(pick))

                # viewer compat keys
                st.session_state["viewer_build_root"] = str(root)
                st.session_state["viewer_reports_dir"] = str(rep)
                st.session_state["viewer_job_url"] = str(ctx.get("job_url") or "")
                st.session_state["viewer_job_name"] = str(ctx.get("job_name") or "")
                st.session_state["viewer_job_slug"] = str(ctx.get("job_slug") or "")
                st.success(f"선택 빌드로 전환: build_{pick}")
                st.rerun()

    st.caption("툴별 카운트는 Jenkins 스캔 파일 기반 요약, 상세는 '📦 Jenkins 리포트' 탭에서 확인 가능")


__all__ = ["_render_jenkins_project_dashboard"]
