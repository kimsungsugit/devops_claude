# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

import config
import gui_utils
from tabs import analysis_views, chat, dashboard, jenkins_reports, scm

from .helpers import _detect_reports_dir
from .project_dashboard import _render_jenkins_project_dashboard
from .sidebar import _render_jenkins_sidebar_and_context


def _render_jenkins_mode() -> None:
    ctx = _render_jenkins_sidebar_and_context()

    # 프로젝트 탭은 항상 표시 (캐시 히스토리/툴 요약)
    build_root_str = ctx.get("build_root")
    build_root = Path(str(build_root_str)).resolve() if build_root_str else None

    chat_ratio = float(st.sidebar.slider("채팅 패널 폭", min_value=0.2, max_value=0.45, value=0.27, step=0.01, key="chat_panel_ratio"))
    chat_ratio = max(0.2, min(0.45, chat_ratio))
    main_col, chat_col = st.columns([1.0 - chat_ratio, chat_ratio])
    with main_col:
        tabs = st.tabs([
            "📌 프로젝트",
            "🏠 빌드 대시보드",
            "🗂️ SCM",
            "📈 복잡도",
            "🧾 로그",
            "📦 Jenkins 리포트",
        ])

        with tabs[0]:
            _render_jenkins_project_dashboard(ctx)

        if build_root is None or not build_root.exists():
            with tabs[1]:
                st.info("사이드바에서 프로젝트/빌드 선택 후 Sync 실행 필요")
            with tabs[2]:
                st.info("Sync 후 사용 가능")
            with tabs[3]:
                st.info("Sync 후 사용 가능")
            with tabs[4]:
                jenkins_reports.render_jenkins_reports(
                    build_root=None,
                    reports_dir=None,
                    build_info=ctx.get("build_info"),
                    artifacts=ctx.get("artifacts"),
                )
            return

    reports_dir = _detect_reports_dir(build_root)
    report_name = reports_dir.name
    paths = gui_utils.get_paths(str(build_root), report_name)
    summary, findings, status, history = _load_gui_data(paths)

    with tabs[1]:
        dashboard.render_dashboard(
            summary,
            findings,
            history,
            str(build_root),
            report_name,
            paths,
            cfg_do_cmake=False,
            mode="jenkins",
            build_info=ctx.get("build_info"),
            artifacts=ctx.get("artifacts"),
        )

    with tabs[2]:
        scm.render_scm(str(build_root))

    with tabs[3]:
        analysis_views.render_complexity(paths, 15)

    with tabs[4]:
        analysis_views.render_logs(paths)

    with tabs[5]:
        jenkins_reports.render_jenkins_reports(
            build_root=str(build_root),
            reports_dir=str(paths["REPORT"]),
            build_info=ctx.get("build_info"),
            artifacts=ctx.get("artifacts"),
        )

    with chat_col:
        st.markdown("#### 💬 채팅")
        chat.render_chat(
            str(build_root),
            report_name,
            getattr(config, "DEFAULT_OAI_CONFIG_PATH", "oai_config.json"),
            mode="jenkins",
        )


def _load_gui_data(paths: dict[str, Path]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], list[Any]]:
    # 신키를 기본으로 사용, 없으면 alias 키로 폴백
    summary = gui_utils.load_json(paths.get("SUMMARY") or paths.get("analysis_summary"), default={})
    findings = gui_utils.load_json(paths.get("FINDINGS") or paths.get("analysis_findings"), default=[])
    cpp_findings = gui_utils.load_json(paths.get("CPP_FINDINGS") or paths.get("cpp_findings"), default=[])
    status = gui_utils.load_json(paths.get("STATUS") or paths.get("status"), default={})
    history = gui_utils.load_json(paths.get("HISTORY") or paths.get("history"), default=[])

    if isinstance(cpp_findings, list):
        findings = (findings or []) + cpp_findings

    summary = _merge_viewer_aux_into_summary(paths, summary, status)

    if not isinstance(summary, dict):
        summary = {}
    if not isinstance(findings, list):
        findings = []
    if not isinstance(status, dict):
        status = {}
    if not isinstance(history, list):
        history = []

    return summary, findings, status, history


def _merge_viewer_aux_into_summary(paths: dict[str, Path], summary: Any, status: Any) -> Any:
    if not isinstance(summary, dict):
        return summary

    if isinstance(status, dict) and status:
        summary.setdefault("_status", status)

    js_path = paths.get("JENKINS_SCAN")
    if js_path and "jenkins_scan" not in summary:
        js = gui_utils.load_json(js_path, default={})
        if isinstance(js, dict) and js:
            summary["jenkins_scan"] = js

    return summary


__all__ = ["_render_jenkins_mode"]
