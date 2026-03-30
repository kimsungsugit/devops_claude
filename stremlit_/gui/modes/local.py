# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

import config
import gui_sidebar
import gui_utils
from tabs import analysis_views, chat, dashboard, editor, knowledge, scm


class PipelineStopRequested(Exception):
    pass


def _render_local_mode() -> None:
    cfg = gui_sidebar.render_sidebar()
    cfg = dict(cfg) if isinstance(cfg, dict) else {}

    cfg.setdefault("project_root", str(Path.cwd()))
    cfg.setdefault("report_dir", "reports")

    paths = gui_utils.get_paths(cfg["project_root"], cfg["report_dir"])
    stop_flag = paths["REPORT"] / ".stop"

    def stop_check_callback():
        if stop_flag.exists():
            raise PipelineStopRequested("사용자 중지 요청")

    # 실행 버튼
    c_run, c_stop = st.sidebar.columns(2)
    start_btn = c_run.button("▶️ 분석 시작", type="primary", width="stretch")
    stop_btn = c_stop.button("⛔ 작업 중지", type="secondary", width="stretch")

    if stop_btn:
        stop_flag.touch()
        run_state = st.session_state.get("pipeline_async") or {}
        pid = int(run_state.get("pid") or 0)
        status_path = run_state.get("status_path")
        status_data = {}
        if status_path:
            status_data = gui_utils.read_run_status(Path(str(status_path)))
        state = str(status_data.get("state") or "")
        if pid and state != "completed":
            gui_utils.terminate_process(pid)
        if status_path and state != "completed":
            try:
                gui_utils.save_json(Path(str(status_path)), {"state": "stopped", "reason": "user"})
            except Exception:
                pass
        try:
            gui_utils.append_log_line(paths["SYSTEM_LOG"], "stopped by user")
        except Exception:
            pass
        st.session_state.pop("pipeline_async", None)
        st.sidebar.warning("작업 중지 요청됨")

    if start_btn:
        if stop_flag.exists():
            stop_flag.unlink()

        run_state = gui_utils.start_pipeline_async(cfg, paths)
        st.session_state["pipeline_async"] = run_state
        st.sidebar.success("분석 시작됨")
        st.rerun()

    run_state = st.session_state.get("pipeline_async") or {}
    if run_state and run_state.get("status_path"):
        status_path = Path(str(run_state.get("status_path")))
        log_path = Path(str(run_state.get("log_path")))
        auto_refresh = st.sidebar.checkbox("Auto refresh while running", value=True, key="auto_refresh_run")

        status_data = gui_utils.read_run_status(status_path)
        state = str(status_data.get("state") or "unknown")
        status_box = st.status(f"분석 상태: {state}", expanded=True)
        if status_data.get("exit_code") is not None:
            status_box.update(
                label=f"분석 완료 (exit_code={status_data.get('exit_code')})",
                state="complete",
                expanded=False,
            )
        log_area = st.empty()
        log_area.code(gui_utils.tail_file(log_path, max_lines=10), language="text")

        if state == "completed":
            st.session_state.pop("pipeline_async", None)
        elif auto_refresh:
            time.sleep(1.0)
            st.rerun()

    # 데이터 로드
    summary, findings, status, history = _load_gui_data(paths)

    chat_ratio = float(st.sidebar.slider("채팅 패널 폭", min_value=0.2, max_value=0.45, value=0.27, step=0.01, key="chat_panel_ratio"))
    chat_ratio = max(0.2, min(0.45, chat_ratio))
    main_col, chat_col = st.columns([1.0 - chat_ratio, chat_ratio])
    with main_col:
        tabs = st.tabs([
            "🏠 대시보드",
            "🧩 에디터",
            "🗂️ SCM",
            "📚 지식 베이스",
            "📈 복잡도",
            "📄 문서",
            "🧾 로그",
        ])

        with tabs[0]:
            dashboard.render_dashboard(summary, findings, history, cfg["project_root"], cfg["report_dir"], paths, cfg_do_cmake=True)

        with tabs[1]:
            suppr_path = paths.get("SUPPRESSIONS", paths["REPORT"] / "suppressions.txt")
            editor.render_editor(cfg["project_root"], findings, status, cfg.get("oai_config_path"), suppr_path, widget_key_prefix="local_editor")

        with tabs[2]:
            scm.render_scm(cfg.get("project_root") or str(Path.cwd()))

        with tabs[3]:
            knowledge.render_knowledge_base(cfg["project_root"], cfg["report_dir"])

        with tabs[4]:
            analysis_views.render_complexity(paths, cfg.get("complexity_threshold", 15))

        with tabs[5]:
            analysis_views.render_docs(paths)

        with tabs[6]:
            analysis_views.render_logs(paths)

    with chat_col:
        st.markdown("#### 💬 채팅")
        chat.render_chat(
            cfg["project_root"],
            cfg["report_dir"],
            cfg.get("oai_config_path", getattr(config, "DEFAULT_OAI_CONFIG_PATH", "oai_config.json")),
            mode="local",
        )


def _load_gui_data(paths: dict[str, Path]) -> tuple[dict, list, dict, list]:
    summary = gui_utils.load_json(paths.get("SUMMARY") or paths.get("analysis_summary"), default={})
    findings = gui_utils.load_json(paths.get("FINDINGS") or paths.get("analysis_findings"), default=[])
    cpp_findings = gui_utils.load_json(paths.get("CPP_FINDINGS") or paths.get("cpp_findings"), default=[])
    status = gui_utils.load_json(paths.get("STATUS") or paths.get("status"), default={})
    history = gui_utils.load_json(paths.get("HISTORY") or paths.get("history"), default=[])

    if isinstance(cpp_findings, list):
        findings = (findings or []) + cpp_findings

    if not isinstance(summary, dict):
        summary = {}
    if not isinstance(findings, list):
        findings = []
    if not isinstance(status, dict):
        status = {}
    if not isinstance(history, list):
        history = []

    return summary, findings, status, history


__all__ = ["_render_local_mode", "PipelineStopRequested"]
