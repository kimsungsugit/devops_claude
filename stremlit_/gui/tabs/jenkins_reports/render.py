# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

import gui_utils

from .file_browser import _collect_files, _render_xlsx
from .findings_collector import (
    _collect_findings_for_editor,
    _collect_source_roots,
    _guess_project_root,
    _render_findings_editor_bridge,
)
from .html_renderer import _render_html
from .overview import _build_ext_df, _build_kpi_df, _render_overview
from .prqa import _render_prqa, _render_prqa_rcr_detail
from .utils import _as_path, _job_slug, _normalize_rule_id, _read_json
from .vectorcast import _render_vectorcast


try:
    # 패키지 구조인 경우
    from gui.tabs import editor as editor_tab  # type: ignore
except Exception:  # pragma: no cover
    try:
        # 상대 import 가능한 경우
        from .. import editor as editor_tab  # type: ignore
    except Exception:  # pragma: no cover
        editor_tab = None  # type: ignore


def render_jenkins_reports(
    *,
    build_root: Optional[str],
    reports_dir: Optional[str],
    build_info: Optional[Dict[str, Any]] = None,
    artifacts: Optional[List[dict]] = None,
):
    """
    Jenkins Viewer 탭
    - reports_dir의 analysis_summary/status/jenkins_scan 기반 요약 + 차트
    - 파일(HTML/XLSX/CSV) 브라우저/미리보기
    """
    broot = _as_path(build_root)
    rdir = _as_path(reports_dir)

    # load summaries
    summary = _read_json(rdir / "analysis_summary.json" if rdir else None, default={})
    status = _read_json(rdir / "status.json" if rdir else None, default={})
    jscan = _read_json(rdir / "jenkins_scan.json" if rdir else None, default={})

    if not broot and not rdir:
        st.info("Jenkins 동기화 후 build_root/reports_dir가 설정되면 표시됨")
        return

    st.session_state.setdefault("auto_fill_findings_json", True)
    st.session_state.setdefault("jr_prefer_sur_findings", True)
    st.checkbox("Prefer SUR for Editor", value=bool(st.session_state.get("jr_prefer_sur_findings")), key="jr_prefer_sur_findings")
    # findings for Editor bridge
    findings_items = _collect_findings_for_editor(
        broot,
        rdir,
        summary if isinstance(summary, dict) else {},
        prefer_sur=bool(st.session_state.get("jr_prefer_sur_findings", True)),
    )
    # rule label normalization (설명 매핑 통일)
    try:
        for it in findings_items:
            if isinstance(it, dict) and it.get("rule") is not None:
                it["rule"] = _normalize_rule_id(it.get("rule"))
    except Exception:
        pass

    # pseudo-tabs (수평 토글)
    st.session_state.setdefault("jr_view_mode", "📦 Reports")
    # jr_view_mode 위젯 생성 전, 요청된 뷰 모드 적용 처리
    next_vm = st.session_state.pop("_jr_view_mode_next", None)
    if next_vm:
        st.session_state["jr_view_mode"] = next_vm

    view_mode = st.radio("보기", options=["📦 Reports", "🧩 Editor"], horizontal=True, key="jr_view_mode")

    if view_mode == "🧩 Editor":
        st.header("🧩 Editor (Jenkins Viewer)")
        if editor_tab is None or not hasattr(editor_tab, "render_editor"):
            st.error("editor 모듈 로드 실패, /app/gui/tabs/editor.py 경로 및 import 구조 확인 필요")
            return
        # build/job 정보 추출 (키/캐시용)
        job_url = (summary or {}).get("jenkins", {}).get("job_url", "") or (build_info or {}).get("job_url", "")
        build_no = (summary or {}).get("jenkins", {}).get("build_number", "") or (build_info or {}).get("build_number", "")
        if not build_no and broot:
            build_no = str(broot.name).replace("build_", "")
        key_base = f"{_job_slug(job_url)}:{build_no}"

        source_roots = _collect_source_roots(broot, rdir, summary if isinstance(summary, dict) else {})
        project_root_guess = _guess_project_root(broot, rdir, summary if isinstance(summary, dict) else {})
        if not source_roots:
            source_roots = [project_root_guess]

        # 선택값 복원/저장
        ss_key = f"jr_code_root:{key_base}"
        st.session_state.setdefault(ss_key, source_roots[0])
        try:
            cur = st.session_state.get(ss_key) or source_roots[0]
        except Exception:
            cur = source_roots[0]
        try:
            idx0 = source_roots.index(cur) if cur in source_roots else 0
        except Exception:
            idx0 = 0

        sel_root = st.selectbox("코드 루트", options=source_roots, index=idx0, key=f"jr_code_root_sel:{key_base}")
        st.session_state[ss_key] = sel_root
        st.session_state["viewer_project_root"] = sel_root
        st.session_state["viewer_code_root"] = sel_root
        st.session_state["viewer_source_roots"] = source_roots
        st.caption(f"project_root: {sel_root}")

        # AI 설정 경로는 환경마다 다름, 필요 시 수동 입력
        st.session_state.setdefault("jr_oai_config_path", "")
        oai_path = st.text_input(
            "oai_config_path(옵션)",
            value=str(st.session_state.get("jr_oai_config_path") or ""),
            key="jr_oai_config_path",
        )
        editor_prefix = f"jr_editor:{key_base}"

        editor_tab.render_editor(
            sel_root,
            findings_items,
            status,
            oai_config_path=oai_path or None,
            suppressions_path=None,
            reports_dir=rdir,
            rule_catalog=gui_utils.load_rule_catalog(Path.cwd(), extra_roots=[p for p in [broot, rdir, (rdir.parent if rdir else None)] if p]),
            widget_key_prefix=editor_prefix,
        )
        return

    # ---- Overview ----
    st.header("📦 Jenkins 리포트 (요약/분석)")
    if summary:
        _render_overview(summary)

    # KPI / EXT charts
    with st.expander("📌 Jenkins 스캔 요약", expanded=True):
        kpi_df = _build_kpi_df(jscan)
        ext_df = _build_ext_df(jscan)

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("FAIL/ERROR/WARN/PASS 토큰")
            if not kpi_df.empty:
                st.dataframe(kpi_df, width="stretch", height=220)
                st.bar_chart(kpi_df.set_index("KPI"), height=260)
        with c2:
            st.subheader("확장자 분포(Top 25)")
            if not ext_df.empty:
                st.dataframe(ext_df, width="stretch", height=220)
                st.bar_chart(ext_df.set_index("ext"), height=260)

        summ = (jscan or {}).get("summary", {})
        st.caption(f"files_total={summ.get('files_total')}, bytes_total={summ.get('bytes_total')}")

    # ---- Findings -> Editor bridge ----
    with st.expander("🧩 룰 위반/이슈 → Editor 열기", expanded=False):
        _render_findings_editor_bridge(findings_items, broot=broot, rdir=rdir)

    # ---- Deeper summaries ----
    with st.expander("🧪 VectorCAST 요약", expanded=False):
        _render_vectorcast(summary)

        # complexity.csv
        if rdir:
            cpath = rdir / "complexity.csv"
            if cpath.exists():
                try:
                    cdf = pd.read_csv(cpath)
                    st.subheader("복잡도(Top 20)")
                    top = cdf.sort_values("ccn", ascending=False).head(20)
                    st.dataframe(top, width="stretch", height=360)
                    st.bar_chart(top.set_index("function")[["ccn"]], height=320)
                except Exception as e:
                    st.caption(f"complexity.csv 읽기 실패: {e}")

    with st.expander("🧾 PRQA(QAC) 요약", expanded=False):
        _render_prqa(summary)

    with st.expander("📏 PRQA Rule Compliance(RCR) 상세", expanded=False):
        _render_prqa_rcr_detail(broot, rdir, artifacts)

    # ---- File browser ----
    st.divider()
    st.subheader("파일 탐색/미리보기")

    files = _collect_files(broot, rdir, artifacts)
    # filter
    ext_options = sorted({p.suffix.lower() for p in files if p.suffix})
    default_cands = [".html", ".xlsx", ".csv"]
    default_ext = [x for x in default_cands if x in ext_options]

    # 세션에 저장된 이전 선택값이 options 밖이면 Streamlit이 예외 발생, 교집합으로 정규화
    prev = st.session_state.get("jr_ext_filter")
    if isinstance(prev, str):
        prev = [prev]
    if isinstance(prev, (list, tuple, set)):
        st.session_state["jr_ext_filter"] = [x for x in list(prev) if x in ext_options]

    only = st.multiselect(
        "확장자 필터",
        options=ext_options,
        default=default_ext,
        key="jr_ext_filter",
    )
    view_files = [p for p in files if (not only or p.suffix.lower() in only)]
    labels = []
    for p in view_files:
        try:
            size = p.stat().st_size
        except Exception:
            size = 0
        labels.append(f"{p.name}  ({size} bytes)")

    if not view_files:
        st.info("표시할 파일 없음")
        return

    sel_idx = st.selectbox("파일 선택", range(len(view_files)), format_func=lambda i: labels[i])
    sel = view_files[int(sel_idx)]

    st.caption(str(sel))
    c1, c2 = st.columns([1, 1])
    with c1:
        from .utils import _download_button  # local import to avoid cycle

        _download_button(sel, "📥 파일 다운로드")
    with c2:
        st.caption(f"mtime={sel.stat().st_mtime if sel.exists() else '-'}")

    # preview
    suffix = sel.suffix.lower()
    if suffix in (".html", ".htm"):
        _render_html(sel, height=760)
    elif suffix in (".xlsx", ".xlsm", ".xls"):
        _render_xlsx(sel)
    elif suffix in (".csv",):
        try:
            df = pd.read_csv(sel)
            st.dataframe(df, width="stretch", height=520)
        except Exception:
            st.text(sel.read_text(errors="ignore")[:200000])
    else:
        st.caption(f"{sel.name}  ({sel.stat().st_size} bytes)")
        try:
            st.text(sel.read_text(errors="ignore")[:200000])
        except Exception:
            st.info("텍스트로 표시 불가(바이너리 가능)")


__all__ = ["render_jenkins_reports"]
