# /app/gui/app.py
# -*- coding: utf-8 -*-
"""
DevOps Pro GUI entry (Streamlit)
- 상위 모드 분리: 로컬 분석 / Jenkins Viewer
- 모드별 사이드바/탭/데이터 루트 완전 분리
"""

from __future__ import annotations

import os
import sys

# 프로젝트 루트 import 경로 확보 (/app 기준)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

import config
from modes.jenkins.mode import _render_jenkins_mode
from modes.local import _render_local_mode


def main() -> None:
    st.set_page_config(
        page_title=f"DevOps Pro v{getattr(config, 'ENGINE_VERSION', 'dev')}",
        page_icon="🛠️",
        layout="wide",
    )

    st.sidebar.header("🧭 모드 선택")
    mode_label = st.sidebar.radio(
        "실행 모드",
        options=["🖥️ 로컬 분석", "☁️ Jenkins Viewer"],
        index=0 if st.session_state.get("app_mode", "local") == "local" else 1,
        key="app_mode_label",
    )
    mode = "local" if mode_label.startswith("🖥️") else "jenkins"
    st.session_state["app_mode"] = mode

    st.title(f"🛠️ DevOps Pro v{getattr(config, 'ENGINE_VERSION', 'dev')}")

    if mode == "local":
        _render_local_mode()
    else:
        _render_jenkins_mode()


if __name__ == "__main__":
    main()
