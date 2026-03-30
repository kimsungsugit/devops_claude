# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

import gui_utils

from .file_browser import _collect_files
from .utils import _normalize_rule_id

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore


def _render_prqa(summary: dict):
    prqa = (summary or {}).get("prqa", {}) or {}
    if not prqa:
        st.info("PRQA(QAC) 요약 없음")
        return

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("CRR(Code Review) 요약")
        crr = prqa.get("crr") or {}
        if crr.get("ok"):
            st.json(crr.get("summary", {}))
        else:
            st.caption("CRR 없음/파싱 실패")
    with c2:
        st.subheader("RCR(Rule Compliance) 요약")
        rcr = prqa.get("rcr") or {}
        if rcr.get("ok"):
            st.json(rcr.get("summary", {}))
        else:
            st.caption("RCR 없음/파싱 실패")

    hmr = prqa.get("hmr") or {}
    if not hmr.get("ok"):
        st.caption("HMR(xlsx) 없음/파싱 실패")
        return

    st.subheader("HMR(HIS Metrics) 복잡도(v(G)) 분석")
    stats = hmr.get("stats", {}) or {}
    st.caption(f"functions_total={stats.get('functions_total')}, vg_max={stats.get('vg_max')}, vg_p95={stats.get('vg_p95')}, vg_mean={stats.get('vg_mean')}")

    rows = hmr.get("rows") or hmr.get("top_vg") or []
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("HMR 데이터 없음")
        return

    # normalize columns
    for col in ("file", "function"):
        if col in df.columns:
            df[col] = df[col].astype(str)
    if "vg" in df.columns:
        df["vg"] = pd.to_numeric(df["vg"], errors="coerce").fillna(0).astype(int)

    max_vg = int(df["vg"].max() if "vg" in df.columns and not df.empty else 0)
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        min_vg = st.slider("min v(G)", 0, max(0, max_vg), value=min(10, max_vg), key="hmr_min_vg")
    with c2:
        topn = st.number_input("Top N(필터 적용 후)", min_value=10, max_value=1000, value=200, step=10, key="hmr_topn")
    with c3:
        file_q = st.text_input("파일 필터(부분 일치)", value="", key="hmr_file_q")

    df_f = df.copy()
    if file_q.strip():
        df_f = df_f[df_f["file"].str.contains(file_q.strip(), case=False, na=False)]
    df_f = df_f[df_f["vg"] >= int(min_vg)]

    # file-level grouping (chart/table)
    with st.expander("📁 소스 파일별 그룹핑", expanded=True):
        g = df_f.groupby("file", dropna=False).agg(
            functions=("function", "count"),
            vg_max=("vg", "max"),
            vg_mean=("vg", "mean"),
            calls_sum=("calls", "sum") if "calls" in df_f.columns else ("vg", "count"),
        ).reset_index()
        g = g.sort_values(["vg_max", "functions"], ascending=[False, False])
        st.dataframe(g.head(60), width="stretch", height=360)
        try:
            st.bar_chart(g.head(30).set_index("file")[["vg_max"]], height=320)
        except Exception:
            pass

    # choose files to drilldown
    files = sorted([x for x in df_f["file"].dropna().unique().tolist() if str(x).strip()])
    picked_files = st.multiselect("드릴다운 파일 선택(미선택=자동 Top)", options=files, default=[], key="hmr_files")
    if picked_files:
        df_d = df_f[df_f["file"].isin(picked_files)].copy()
    else:
        # auto: top files by vg_max
        top_files = df_f.groupby("file")["vg"].max().sort_values(ascending=False).head(10).index.tolist()
        df_d = df_f[df_f["file"].isin(top_files)].copy()

    # function-level table (after filters)
    df_d = df_d.sort_values(["vg", "calls"], ascending=[False, False]) if "calls" in df_d.columns else df_d.sort_values(["vg"], ascending=[False])
    df_d = df_d.head(int(topn))

    st.subheader("🔎 함수 단위 상세(파일별)")
    if df_d.empty:
        st.info("필터 조건에서 표시할 항목 없음")
        return

    show_cols = [c for c in ["function", "vg", "calls", "calling", "level", "file"] if c in df_d.columns]
    for f, sub in df_d.groupby("file"):
        vmax = int(sub["vg"].max()) if "vg" in sub.columns and not sub.empty else 0
        with st.expander(f"{f}  (n={len(sub)}, max v(G)={vmax})", expanded=False):
            st.dataframe(sub[show_cols], width="stretch", height=420)


def _find_latest_matching(files: List[Path], patterns: List[str]) -> Optional[Path]:
    """파일 리스트에서 패턴(정규식/대소문자 무시)에 매칭되는 최신 파일 반환"""
    if not files:
        return None
    regs = [re.compile(p, re.I) for p in patterns if p]
    cand: List[Path] = []
    for p in files:
        name = p.name
        if any(r.search(name) for r in regs):
            cand.append(p)
    if not cand:
        return None
    cand.sort(key=lambda x: (x.stat().st_mtime if x.exists() else 0, x.name), reverse=True)
    return cand[0]


def _html_table_to_df(table) -> pd.DataFrame:
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        rows.append([c.get_text(" ", strip=True) for c in cells])
    if not rows:
        return pd.DataFrame()
    header = rows[0]
    body = rows[1:]
    # header 중복/빈칸 처리
    header2 = []
    seen = {}
    for h in header:
        h = (h or "").strip() or "col"
        if h in seen:
            seen[h] += 1
            h = f"{h}_{seen[h]}"
        else:
            seen[h] = 0
        header2.append(h)
    df = pd.DataFrame(body, columns=header2)
    return df


def _parse_prqa_rcr_html(html_path: Path) -> Dict[str, Any]:
    """
    PRQA Rule Compliance Report(RCR)에서 주요 표 파싱
    - Diagnostics Per Parent Rules: 중요도(공통/의무/필수/합계) 파일별 분포
    - Most Violated Rules: 상위 룰 매트릭스(파일 x 룰)
    - File Status(있을 경우): 파일별 상태
    """
    if not html_path or not html_path.exists():
        return {}
    if BeautifulSoup is None:
        return {"_error": "bs4(BeautifulSoup) 미설치, pip install beautifulsoup4 필요"}
    try:
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    except Exception as e:
        return {"_error": f"RCR HTML 로드 실패: {e}"}

    def find_table_after_heading(title: str):
        h = soup.find(lambda tag: tag.name in ("h1", "h2", "h3", "h4") and title.lower() in tag.get_text(" ", strip=True).lower())
        if not h:
            return None
        return h.find_next("table")

    out: Dict[str, Any] = {}

    # 1) Diagnostics Per Parent Rules
    t1 = find_table_after_heading("Diagnostics Per Parent Rules")
    if t1:
        df1 = _html_table_to_df(t1)
        if not df1.empty:
            # 숫자 컬럼 변환
            for c in df1.columns:
                if c.lower() != "files":
                    df1[c] = pd.to_numeric(df1[c].astype(str).str.replace(",", ""), errors="coerce").fillna(0).astype(int)
            out["diagnostics_per_parent_rules"] = df1

    # 2) Most Violated Rules
    t2 = find_table_after_heading("Most Violated Rules")
    if t2:
        df2 = _html_table_to_df(t2)
        if not df2.empty:
            # 첫 컬럼 파일명, 나머지 룰 count
            for c in df2.columns[1:]:
                df2[c] = pd.to_numeric(df2[c].astype(str).str.replace(",", ""), errors="coerce").fillna(0).astype(int)
            out["most_violated_rules_matrix"] = df2

            # 룰별 합계
            rule_totals = df2.drop(columns=[df2.columns[0]]).sum(axis=0).sort_values(ascending=False)
            out["rule_totals"] = rule_totals.reset_index().rename(columns={"index": "rule", 0: "count"})

    # 3) File Status(있으면)
    t3 = find_table_after_heading("File Status")
    if t3:
        df3 = _html_table_to_df(t3)
        if not df3.empty:
            out["file_status"] = df3

    out["source_file"] = str(html_path)
    return out


def _render_prqa_rcr_detail(broot: Optional[Path], rdir: Optional[Path], artifacts: Optional[List[dict]]):
    st.subheader("📏 PRQA Rule Compliance(RCR) 상세")
    files = _collect_files(broot, rdir, artifacts)
    rcr = _find_latest_matching(files, [r"_RCR_.*\.html?$", r"rule.*compliance.*\.html?$"])
    if not rcr:
        st.info("RCR(룰 컴플라이언스) HTML 미발견, 아티팩트 패턴에 '*_RCR_*.html' 포함 확인 필요")
        return

    # Load the comprehensive rule catalog
    try:
        rule_catalog = gui_utils.load_rule_catalog(Path.cwd(), extra_roots=[p for p in [broot, rdir, (rdir.parent if rdir else None)] if p])
    except Exception:
        rule_catalog = {}

    parsed = _parse_prqa_rcr_html(rcr)
    if not parsed:
        st.warning("RCR 파싱 결과 없음")
        return
    if isinstance(parsed, dict) and parsed.get("_error"):
        st.error(parsed.get("_error"))
        st.caption(f"대상 파일: {rcr.name}")
        return

    st.caption(f"대상 파일: {rcr.name}")

    # 1) Diagnostics Per Parent Rules
    df_diag = parsed.get("diagnostics_per_parent_rules")
    if isinstance(df_diag, pd.DataFrame) and not df_diag.empty:
        st.markdown("#### 중요도(Parent Rules) 파일별 분포")
        show_n = st.slider("표시 파일 수(Top N)", min_value=10, max_value=200, value=50, step=10, key="rcr_topn_files")
        dfv = df_diag.copy()
        # Total Violations 컬럼 우선 정렬
        total_col = next((c for c in dfv.columns if "total" in c.lower()), None)
        if total_col:
            dfv = dfv.sort_values(total_col, ascending=False)
        st.dataframe(dfv.head(show_n), width="stretch", height=360)

        # 차트(Top 30)
        topc = dfv.head(min(30, len(dfv))).set_index(dfv.columns[0])
        # 범주 컬럼만 선택
        num_cols = [c for c in topc.columns if c != dfv.columns[0]]
        if num_cols:
            st.bar_chart(topc[num_cols], height=320)

        # 룰 위반 합계
        st.markdown("##### 전체 합계")
        sums = dfv.drop(columns=[dfv.columns[0]]).sum(axis=0).sort_values(ascending=False)
        sdf = sums.reset_index().rename(columns={"index": "category", 0: "count"})
        st.dataframe(sdf, width="stretch", height=200)

    # 2) Most violated rules
    df_rules = parsed.get("rule_totals")
    df_mat = parsed.get("most_violated_rules_matrix")
    if isinstance(df_rules, pd.DataFrame) and not df_rules.empty:
        st.markdown("#### 최다 위반 룰 Top")
        topn = st.slider("표시 룰 수(Top N)", min_value=5, max_value=50, value=15, step=5, key="rcr_topn_rules")

        df_show = df_rules.copy()
        if "rule" in df_show.columns and rule_catalog:
            df_show["설명"] = df_show["rule"].astype(str).map(lambda x: gui_utils.rule_desc(_normalize_rule_id(x), rule_catalog))
        st.dataframe(df_show.head(topn), width="stretch", height=320)

        st.bar_chart(df_rules.head(min(30, len(df_rules))).set_index("rule")[["count"]], height=320)

    if isinstance(df_mat, pd.DataFrame) and not df_mat.empty:
        st.markdown("#### 파일 x 룰 매트릭스(상위 룰)")
        # 사용자가 선택한 룰만 보기
        rule_cols = list(df_mat.columns[1:])
        default_sel = rule_cols[: min(8, len(rule_cols))]
        sel_rules = st.multiselect("표시할 룰", options=rule_cols, default=default_sel, key="rcr_rules_sel")
        cols = [df_mat.columns[0]] + (sel_rules or [])
        dfm = df_mat[cols].copy() if cols else df_mat.copy()
        st.dataframe(dfm.head(100), width="stretch", height=420)
        st.caption("표가 크면 상위 100행만 표시, 다운로드는 '파일 탐색/미리보기'에서 원본 HTML 선택 후 다운로드 권장")

    # 3) File status
    df_fs = parsed.get("file_status")
    if isinstance(df_fs, pd.DataFrame) and not df_fs.empty:
        with st.expander("File Status 표", expanded=False):
            st.dataframe(df_fs.head(200), width="stretch", height=420)


__all__ = ["_render_prqa", "_render_prqa_rcr_detail", "_parse_prqa_rcr_html", "_find_latest_matching", "_html_table_to_df"]
