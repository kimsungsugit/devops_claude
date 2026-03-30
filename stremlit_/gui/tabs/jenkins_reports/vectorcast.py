# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import streamlit as st

from .html_renderer import _render_html


def _render_vectorcast(summary: dict):
    vc = (summary or {}).get("vectorcast", {}) or {}
    if not vc:
        st.info("VectorCAST 리포트 파싱 결과 없음")
        return

    # UT/IT grand totals (metrics report)
    c1, c2 = st.columns(2)
    for col, (label, key) in zip([c1, c2], [("UT", "ut_metrics"), ("IT", "it_metrics")]):
        with col:
            m = vc.get(key) or {}
            gt = (m.get("grand_totals") or {}) if isinstance(m, dict) else {}
            st_cov = (gt.get("statements") or {}) if isinstance(gt, dict) else {}
            br_cov = (gt.get("branches") or {}) if isinstance(gt, dict) else {}
            if isinstance(st_cov, dict) and st_cov.get("total", 0):
                st.metric(f"{label} Statements", f"{float(st_cov.get('rate', 0.0))*100.0:.1f}%")
            if isinstance(br_cov, dict) and br_cov.get("total", 0):
                st.metric(f"{label} Branches", f"{float(br_cov.get('rate', 0.0))*100.0:.1f}%")

    # --- worst coverage drilldown (environment report) ---
    st.session_state.setdefault("vc_env_open", {"path": "", "file": ""})

    for label, key in [("UT", "ut_env"), ("IT", "it_env")]:
        env = vc.get(key)
        if not isinstance(env, dict) or not env.get("ok"):
            continue

        env_path = str(env.get("path") or "")
        p = Path(env_path) if env_path else None
        st.subheader(f"{label} 환경별 커버리지(파일 기준)")

        metric = st.radio(
            f"{label} worst 기준",
            options=["Statements", "Branches"],
            horizontal=True,
            key=f"vc_{label}_worst_metric",
        )
        worst = env.get("worst_statements") if metric == "Statements" else env.get("worst_branches")
        worst = worst or []

        # 목록(파일 클릭 시 해당 HTML에서 해당 행으로 점프)
        head = st.columns([3, 1, 1])
        head[0].markdown("**file**")
        head[1].markdown("**statements%**")
        head[2].markdown("**branches%**")

        for i, r in enumerate(worst[:20]):
            st_cov = (r.get("statements") or {}).get("rate")
            br_cov = (r.get("branches") or {}).get("rate")
            f = str(r.get("file") or "")
            cols = st.columns([3, 1, 1])
            with cols[0]:
                if st.button(f, key=f"vc_file_{label}_{metric}_{i}") and p and p.exists():
                    st.session_state["vc_env_open"] = {"path": str(p), "file": f, "label": label}
            cols[1].write(f"{float(st_cov)*100.0:.1f}" if isinstance(st_cov, (int, float)) else "-")
            cols[2].write(f"{float(br_cov)*100.0:.1f}" if isinstance(br_cov, (int, float)) else "-")

        # 미리보기
        opened = st.session_state.get("vc_env_open") or {}
        if opened.get("label") == label and opened.get("path"):
            op = Path(str(opened.get("path")))
            if op.exists():
                st.caption(f"Environment report: {op.name}  | jump: {opened.get('file')}")
                _render_html(op, height=760, env_row_target=str(opened.get("file") or ""))
            else:
                st.warning("선택한 HTML 파일이 존재하지 않음")

    # complexity.csv preview (if exists in reports_dir)
    # handled in main render below


__all__ = ["_render_vectorcast"]
