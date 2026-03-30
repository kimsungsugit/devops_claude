# /app/gui/tabs/analysis_views.py
from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path
import json

import ui_common
import gui_utils
from typing import Dict, List, Any, Optional


def _read_text_safe(p: Path, *, max_bytes: int = 512 * 1024) -> str:
    # MessageSizeError 방지, 대형 텍스트/로그는 tail 윈도우만 로드
    try:
        size = int(p.stat().st_size)
    except Exception:
        size = 0

    try:
        with p.open("rb") as f:
            if size > int(max_bytes):
                f.seek(size - int(max_bytes))
            data = f.read(int(max_bytes))
        return data.decode("utf-8", errors="ignore")
    except Exception:
        try:
            return p.read_text(errors="ignore")[:200000]
        except Exception:
            return ""


def _render_text_window(p: Path, *, key: str, default_kib: int = 512) -> None:
    # 대형 파일은 tail 범위만 Streamlit로 전송
    try:
        size = int(p.stat().st_size)
    except Exception:
        size = 0

    st.caption(f"{p.name}, size={size/1024/1024:.1f} MiB")
    kib = st.select_slider(
        "미리보기 범위",
        options=[64, 128, 256, 512, 1024, 2048, 4096],
        value=int(default_kib),
        key=f"{key}_kib",
        help="대형 파일은 tail 범위만 로드, 전체는 원본/다운로드로 확인",
    )
    txt = _read_text_safe(p, max_bytes=int(kib) * 1024)
    st.code(txt, language="text")


def _tail(text: str, n: int = 5000) -> str:
    if not text:
        return ""
    return text[-n:]


def render_complexity(paths, thresh):
    st.markdown("### 📈 코드 복잡도 분석 (Lizard)")

    df = None
    parse_err = None
    try:
        if paths["COMPLEXITY"].exists():
            df = pd.read_csv(paths["COMPLEXITY"])
        else:
            df = gui_utils.load_lizard_dataframe(paths.get("REPORT"))
    except Exception as e:
        parse_err = str(e)
        df = None

    if df is None or df.empty:
        st.warning(
            "복잡도 분석 결과 파일이 아직 없음\n"
            "- 사이드바에서 분석 실행 필요\n"
            "- Lizard 설치/권한 문제 가능\n"
            "- 실행은 되었는데 멈춘 것처럼 보이면 제외 폴더/대상 파일 수 확인 권장"
        )
        with st.expander("복잡도 진단 정보", expanded=False):
            st.write(f"리포트 폴더: {paths.get('REPORT')}")
            st.write(f"complexity 경로: {paths.get('COMPLEXITY')}")
            st.write(f"complexity 존재 여부: {paths['COMPLEXITY'].exists()}")
            if parse_err:
                st.code(f"파싱 오류: {parse_err}", language="text")
            last_err = gui_utils.get_last_lizard_error()
            if last_err:
                st.code(f"마지막 오류: {last_err}", language="text")
            last_path = gui_utils.get_last_lizard_path()
            st.write(f"최근 로드 경로: {last_path if last_path else '없음'}")
            cands = gui_utils.list_lizard_candidate_paths(paths.get("REPORT"), limit=20)
            if cands:
                st.write("후보 파일 (상위 20):")
                st.code("\n".join(str(p) for p in cands), language="text")
            else:
                st.write("후보 파일: 없음")
        return

    cleaned = gui_utils.clean_lizard_dataframe(df)
    if cleaned is not None:
        df = cleaned
    ccn_col = gui_utils._pick_column_case_insensitive(df, ["ccn", "cyclomatic_complexity", "complexity"])
    nloc_col = gui_utils._pick_column_case_insensitive(df, ["nloc", "loc", "lines", "nloc_total"])
    file_col = gui_utils._pick_column_case_insensitive(df, ["file", "filename", "path", "source_file", "unit"])
    func_col = gui_utils._pick_column_case_insensitive(df, ["function", "function_name", "name", "subprogram"])
    if not (ccn_col and nloc_col and file_col and func_col):
        st.info("복잡도 분석 결과를 해석할 수 없음 (필수 컬럼 누락)")
        st.dataframe(df, width="stretch")
        with st.expander("복잡도 진단 정보", expanded=False):
            st.write(f"REPORT dir: {paths.get('REPORT')}")
            st.write(f"COMPLEXITY path: {paths.get('COMPLEXITY')}")
            st.write(f"COMPLEXITY exists: {paths['COMPLEXITY'].exists()}")
            last_path = gui_utils.get_last_lizard_path()
            st.write(f"Last loaded path: {last_path if last_path else 'none'}")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("평균 복잡도 (CCN)", f"{df[ccn_col].mean():.1f}")
    c2.metric("최대 복잡도", df[ccn_col].max())
    c3.metric("분석된 함수 수", len(df))

    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("복잡도 분포 (Size vs CCN)")
        fig_scatter = px.scatter(
            df,
            x=nloc_col,
            y=ccn_col,
            size=ccn_col,
            color=ccn_col,
            hover_data=[file_col, func_col],
            color_continuous_scale="RdYlGn_r",
            labels={"nloc": "Lines of Code", "ccn": "Cyclomatic Complexity"},
        )
        fig_scatter.add_hline(
            y=thresh, line_dash="dot", line_color="red",
            annotation_text=f"Limit ({thresh})"
        )
        st.plotly_chart(fig_scatter, width="stretch")

    with col2:
        st.subheader("파일별 복잡도 히트맵")
        if file_col in df.columns and func_col in df.columns:
            fig_tree = px.treemap(
                df, path=[file_col, func_col], values=ccn_col,
                color=ccn_col, color_continuous_scale="RdYlGn_r"
            )
            st.plotly_chart(fig_tree, width="stretch")

    st.subheader("상세 데이터")
    st.dataframe(
        df.style.highlight_between(left=thresh, right=1000, subset=ccn_col, color="#ff4b4b"),
        width="stretch",
    )


def _collect_special_logs(report_dir: Path) -> Dict[str, List[Path]]:
    """
    ASan/Fuzz/QEMU 관련 로그 후보를 최대한 가볍게 수집.
    파일 패턴이 프로젝트마다 다를 수 있어 heuristic 기반.
    """
    candidates: Dict[str, List[Path]] = {"asan": [], "fuzz": [], "qemu": []}

    # 1) top-level
    for pat in ["*asan*.log", "*asan*.txt", "*ASAN*.log", "*ASAN*.txt"]:
        candidates["asan"] += list(report_dir.glob(pat))

    for pat in ["*fuzz*.log", "*fuzz*.txt", "*FUZZ*.log", "*FUZZ*.txt"]:
        candidates["fuzz"] += list(report_dir.glob(pat))

    for pat in ["*qemu*.log", "*qemu*.txt", "*QEMU*.log", "*QEMU*.txt"]:
        candidates["qemu"] += list(report_dir.glob(pat))

    # 2) known subdirs
    tests_dir = report_dir / "tests"
    if tests_dir.exists():
        # ASan 출력이 CTest 로그에 섞이는 경우 대비
        for p in tests_dir.glob("*.txt"):
            if "ctest" in p.name.lower():
                candidates["asan"].append(p)

    fuzz_dir = report_dir / "fuzz"
    if fuzz_dir.exists():
        candidates["fuzz"] += list(fuzz_dir.glob("**/*.log"))
        candidates["fuzz"] += list(fuzz_dir.glob("**/*.txt"))

    qemu_dir = report_dir / "qemu"
    if qemu_dir.exists():
        candidates["qemu"] += list(qemu_dir.glob("**/*.log"))
        candidates["qemu"] += list(qemu_dir.glob("**/*.txt"))

    # 중복 제거 + 정렬
    for k in candidates:
        uniq = sorted({p.resolve() for p in candidates[k]})
        candidates[k] = uniq

    return candidates


def _render_file_picker(files: List[Path], title: str, height: int = 360):
    if not files:
        st.info(
            f"{title} 파일이 아직 없음\n"
            "- 사이드바에서 해당 옵션 활성화 후 재실행 필요\n"
            "- 생성 경로가 다를 수 있어 reports 폴더 내 파일명 패턴 확인 권장"
        )
        return

    sel = st.selectbox(f"{title} 선택", files, format_func=lambda x: x.name)
    txt = _read_text_safe(sel)
    st.text_area(title, _tail(txt, 12000), height=height)


def render_logs(paths, status=None, mode: str = "local", **_kwargs):
    st.markdown("### 🛠️ 시스템 로그 뷰어")

    # 1) 문법 검사 에러 (Syntax)
    syntax_file = paths["REPORT"] / "syntax_check.json"
    if syntax_file.exists():
        try:
            data = json.loads(syntax_file.read_text(encoding="utf-8"))
            failures = [f for f in data.get("results", []) if not f.get("ok")]

            if failures:
                st.error(f"❌ 문법 검사 실패: {len(failures)}개 파일")
                with st.expander("상세 문법 에러 보기", expanded=True):
                    for fail in failures:
                        st.markdown(f"**File:** `{fail.get('file','')}`")
                        st.code(fail.get("stderr", ""), language="text")
            else:
                st.success("✅ 문법 검사: 모든 파일 통과")
        except Exception as e:
            ui_common.log_exception("syntax_check.json parse", e)

    # 2) 기본 로그 경로
    log_dir = paths["REPORT"] / "agent_logs"
    build_log = paths["REPORT"] / "tests" / "ctest_output.txt"
    lizard_log = paths["REPORT"] / "lizard_audit.log"

    # 3) 고급 로그 후보 수집
    special = _collect_special_logs(paths["REPORT"])

    tabs = st.tabs([
        "시스템 로그",
        "AI 에이전트 로그",
        "빌드 로그",
        "Lizard 로그",
        "ASan 로그",
        "Fuzz 로그",
        "QEMU 로그",
    ])

    # --- 시스템 로그 ---
    with tabs[0]:
        sys_log = paths["SYSTEM_LOG"]
        if sys_log.exists():
            col_a, col_b = st.columns([3, 2])
            with col_a:
                q = st.text_input("검색", key="syslog_search", placeholder="예: ERROR, FAIL, traceback")
            with col_b:
                try:
                    size = int(sys_log.stat().st_size)
                except Exception:
                    size = 0
                # 너무 큰 파일은 다운로드 데이터 메모리 사용이 커질 수 있어 경고
                if size <= 20 * 1024 * 1024:
                    ui_common.download_button_from_path(sys_log, "⬇️ System Log 다운로드", mime="text/plain", key="dl_syslog")
                else:
                    st.caption("(파일이 커서 다운로드 버튼 비활성화, 로컬에서 직접 확인 권장)")

            if q:
                txt_all = _read_text_safe(sys_log, max_bytes=2_000_000)
                ql = q.lower()
                hits = [ln for ln in txt_all.splitlines() if ql in ln.lower()]
                st.caption(f"검색 결과: {len(hits)} lines (최근 300줄 표시)")
                st.code("\n".join(hits[-300:]), language="text")
            else:
                _render_text_window(sys_log, key="syslog", default_kib=512)
        else:
            st.info(
                "System log가 아직 없음\n"
                "- 분석 실행 시 reports/system.log 로 저장되는 흐름 가정\n"
                "- Jenkins Viewer에서는 jenkins_scan.json의 log_files를 통해 개별 로그를 볼 수 있음"
            )

            # Jenkins Viewer용 로그 선택 UI (jenkins_scan.json)
            jp = paths.get("JENKINS_SCAN") or (paths.get("REPORT") / "jenkins_scan.json")
            if jp and Path(jp).exists():
                try:
                    data = json.loads(Path(jp).read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    data = {}
                log_files = (data or {}).get("files", {}).get("log", []) or (data or {}).get("log_files", []) or []
                if log_files:
                    sel = st.selectbox("Jenkins 로그 파일 선택", log_files, key="jenkins_log_select")
                    cand1 = (paths["ROOT"] / sel)
                    cand2 = (paths["REPORT"] / sel)
                    cand = cand1 if cand1.exists() else cand2
                    if cand.exists():
                        col1, col2 = st.columns([3, 2])
                        with col1:
                            q2 = st.text_input("검색", key="jenlog_search", placeholder="예: ERROR, FAIL")
                        with col2:
                            try:
                                size2 = int(cand.stat().st_size)
                            except Exception:
                                size2 = 0
                            if size2 <= 20 * 1024 * 1024:
                                ui_common.download_button_from_path(cand, "⬇️ 선택 로그 다운로드", mime="text/plain", key="dl_sel_log")
                        if q2:
                            txt2 = _read_text_safe(cand, max_bytes=2_000_000)
                            ql2 = q2.lower()
                            hits2 = [ln for ln in txt2.splitlines() if ql2 in ln.lower()]
                            st.caption(f"검색 결과: {len(hits2)} lines (최근 300줄 표시)")
                            st.code("\n".join(hits2[-300:]), language="text")
                        else:
                            _render_text_window(cand, key=f"jenlog_{Path(sel).name}", default_kib=512)
                    else:
                        st.warning(f"로그 파일을 찾을 수 없음: {sel}")
                else:
                    st.info("jenkins_scan.json에 log_files 없음")
            else:
                st.info("jenkins_scan.json 없음")



    # --- AI 에이전트 로그 ---
    with tabs[1]:
        if log_dir.exists():
            logs = sorted(log_dir.glob("*.md"), reverse=True)
            if logs:
                sel = st.selectbox("AI 세션 로그 선택", logs, format_func=lambda x: x.name)
                _render_text_window(sel, key=f'ailog_{sel.name}', default_kib=512)
            else:
                st.info("AI 로그 파일 없음")
        else:
            st.info("agent_logs 폴더 없음")

    # --- 빌드 로그 ---
    with tabs[2]:
        if build_log.exists():
            st.text_area("CMake/Build Log", _read_text_safe(build_log), height=400)
        else:
            st.info(
                "빌드 로그 파일 없음\n"
                "- do_build/do_asan 비활성화 상태일 수 있음\n"
                "- 빌드 단계가 스킵되었는지 summary 확인 권장"
            )

    # --- Lizard 로그 ---
    with tabs[3]:
        if lizard_log.exists():
            st.text_area("Audit Log", _read_text_safe(lizard_log), height=320)
        else:
            st.info(
                "Lizard 감사 로그가 아직 없음\n"
                "- 복잡도 분석이 실행되면 reports/lizard_audit.log 생성되는 흐름 가정\n"
                "- 대상 파일 수가 많을 때 지연 가능, exclude_dirs 설정 확인 권장"
            )

    # --- ASan 로그 ---
    with tabs[4]:
        _render_file_picker(special["asan"], "ASan 로그")

    # --- Fuzz 로그 ---
    with tabs[5]:
        _render_file_picker(special["fuzz"], "Fuzz 로그")

    # --- QEMU 로그 ---
    with tabs[6]:
        _render_file_picker(special["qemu"], "QEMU 로그")


def render_docs(paths):
    st.markdown("### 📚 문서 (Doxygen)")
    p = Path(paths.get("DOCS"))
    if p.exists() and p.is_file():
        ui_common.download_button_from_path(p, "📥 HTML 문서 다운로드", mime="text/html", key="dl_docs_html")
        st.caption(str(p))
    else:
        st.info("생성된 문서가 없습니다. 설정에서 Doxygen을 활성화하세요.")
