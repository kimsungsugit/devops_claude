

# ===== gui_sidebar.py =====
# /app/gui/gui_sidebar.py
# -*- coding: utf-8 -*-
# Streamlit 사이드바(UI)에서 파이프라인 설정을 구성하는 모듈
# v30.7: Fix TypeError in text_input widgets (Ensure session_state values are strings)

from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

import config
import gui_utils


def _ensure_state(key: str, default: Any) -> None:
    """Streamlit session_state에 기본값을 한 번만 주입하는 헬퍼"""
    if key not in st.session_state:
        st.session_state[key] = default


def render_sidebar() -> Dict[str, Any]:
    # ------------------------------
    # 0. 저장된 프로파일 / 기본값 로딩
    # ------------------------------
    profiles, last_profile = gui_utils.load_all_profiles()
    default_profile_name = last_profile or "default"

    _ensure_state("cfg_profile_name", default_profile_name)
    active_profile_name = st.session_state["cfg_profile_name"]

    profile_data = profiles.get(active_profile_name, {}) or {}

    # 각 필드별 기본값 계산 & 타입 변환 (List -> Comma separated String)

    # 1) Exclude Dirs
    ex_prof = profile_data.get("exclude_dirs")
    if isinstance(ex_prof, list):
        ex_default = ", ".join(ex_prof)
    elif isinstance(ex_prof, str):
        ex_default = ex_prof
    else:
        ex_default = "build, .git, tests, external, generated"

    # 2) Include Paths
    inc_prof = profile_data.get("include_paths")
    if isinstance(inc_prof, list):
        inc_default = ", ".join(inc_prof)
    elif isinstance(inc_prof, str):
        inc_default = inc_prof
    else:
        inc_default = ", ".join(getattr(config, "DEFAULT_INCLUDE_PATHS", []))

    # 3) Clang Checks
    chk_prof = profile_data.get("clang_checks")
    if isinstance(chk_prof, list):
        chk_default = ", ".join(chk_prof)
    elif isinstance(chk_prof, str):
        chk_default = chk_prof
    else:
        chk_default = ""

    # 4) Domain Targets
    dom_prof = profile_data.get("domain_targets")
    if isinstance(dom_prof, list):
        dom_default = ", ".join(dom_prof)
    else:
        dom_default = str(dom_prof) if dom_prof else ""

    # 5) Cppcheck Levels
    cpp_prof = profile_data.get("cppcheck_levels")
    if not isinstance(cpp_prof, list) or not cpp_prof:
        cpp_prof = getattr(config, "DEFAULT_CPPCHECK_ENABLE", [])

    # Agent Patch Mode 기본값
    default_patch_mode = getattr(config, "AGENT_PATCH_MODE_DEFAULT", "auto")

    # 기본값 세팅 (session_state 초기 주입)
    _ensure_state(
        "cfg_project_root",
        profile_data.get("project_root", getattr(config, "DEFAULT_PROJECT_ROOT", ".")),
    )
    _ensure_state(
        "cfg_report_dir",
        profile_data.get("report_dir", getattr(config, "DEFAULT_REPORT_DIR", "reports")),
    )
    _ensure_state(
        "cfg_targets_glob",
        profile_data.get("targets_glob", getattr(config, "DEFAULT_TARGETS_GLOB", "libs/*.c")),
    )
    _ensure_state("cfg_exclude_dirs", ex_default)

    _ensure_state("cfg_cppcheck_levels", cpp_prof)
    _ensure_state("cfg_do_clang_tidy", bool(profile_data.get("do_clang_tidy", False)))
    _ensure_state("cfg_clang_checks", chk_default)
    _ensure_state(
        "cfg_complexity_threshold",
        int(profile_data.get("complexity_threshold", getattr(config, "DEFAULT_COMPLEXITY_THRESHOLD", 10))),
    )

    _ensure_state("cfg_do_build", bool(profile_data.get("do_build", False)))
    _ensure_state("cfg_do_asan", bool(profile_data.get("do_asan", False)))
    _ensure_state("cfg_do_fuzz", bool(profile_data.get("do_fuzz", False)))
    _ensure_state("cfg_do_qemu", bool(profile_data.get("do_qemu", False)))
    _ensure_state("cfg_do_docs", bool(profile_data.get("do_docs", False)))

    _ensure_state(
        "cfg_target_arch",
        profile_data.get("target_arch", getattr(config, "DEFAULT_TARGET_ARCH", "cortex-m0plus")),
    )
    _ensure_state("cfg_target_macros", profile_data.get("target_macros", ""))
    _ensure_state("cfg_include_paths", inc_default)

    _ensure_state("cfg_enable_agent", bool(profile_data.get("enable_agent", False)))
    _ensure_state("cfg_enable_test_gen", bool(profile_data.get("enable_test_gen", False)))
    _ensure_state("cfg_max_iterations", int(profile_data.get("max_iterations", 3)))
    _ensure_state(
        "cfg_oai_config_path",
        profile_data.get("oai_config_path", getattr(config, "DEFAULT_OAI_CONFIG_PATH", "oai_config.json")),
    )
    _ensure_state(
        "cfg_llm_model",
        profile_data.get("llm_model", getattr(config, "DEFAULT_LLM_MODEL", "gemini-3-pro-preview")),
    )

    default_agent_roles = ", ".join(
        getattr(config, "AGENT_ROLES_DEFAULT", ["planner", "generator", "fixer", "reviewer"])
    )
    _ensure_state("cfg_agent_roles", profile_data.get("agent_roles", default_agent_roles))
    _ensure_state(
        "cfg_agent_run_mode",
        profile_data.get("agent_run_mode", getattr(config, "AGENT_RUN_MODE_DEFAULT", "auto")),
    )
    _ensure_state(
        "cfg_agent_review",
        bool(profile_data.get("agent_review", getattr(config, "AGENT_REVIEW_ENABLED_DEFAULT", True))),
    )
    _ensure_state(
        "cfg_agent_rag",
        bool(profile_data.get("agent_rag", getattr(config, "AGENT_RAG_ENABLED_DEFAULT", True))),
    )
    _ensure_state(
        "cfg_agent_rag_top_k",
        int(profile_data.get("agent_rag_top_k", getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3))),
    )
    _ensure_state(
        "cfg_agent_max_steps",
        int(profile_data.get("agent_max_steps", getattr(config, "AGENT_MAX_STEPS_DEFAULT", 3))),
    )

    _ensure_state("cfg_enable_domain_tests", bool(profile_data.get("enable_domain_tests", False)))
    _ensure_state("cfg_domain_targets", dom_default)

    # Agent Patch Mode
    _ensure_state(
        "cfg_patch_mode",
        profile_data.get("agent_patch_mode", default_patch_mode),
    )

    # [SAFETY FIX] session_state 내의 리스트 타입 값을 문자열로 강제 변환
    # Streamlit text_input 위젯이 리스트를 받으면 TypeError 발생함
    for key in ["cfg_exclude_dirs", "cfg_include_paths", "cfg_clang_checks", "cfg_domain_targets", "cfg_agent_roles"]:
        if key in st.session_state:
            val = st.session_state[key]
            if isinstance(val, list):
                st.session_state[key] = ", ".join(str(v) for v in val)

    # ------------------------------
    # 1. 프로파일 헤더
    # ------------------------------
    st.sidebar.header("🔧 환경 설정")

    with st.sidebar.expander("💾 설정 프로파일", expanded=True):
        existing_names: List[str] = sorted(profiles.keys()) if profiles else []

        if existing_names:
            selected = st.selectbox(
                "저장된 프로파일",
                options=["(선택 안 함)"] + existing_names,
                index=(existing_names.index(active_profile_name) + 1)
                if active_profile_name in existing_names
                else 0,
            )
            if selected != "(선택 안 함)":
                st.session_state["cfg_profile_name"] = selected

        profile_name = st.text_input("프로파일 이름", key="cfg_profile_name")
        profile_name = (profile_name or "").strip()
        st.caption(f"설정 파일: `{gui_utils.get_settings_file_path()}`")

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("불러오기", width="stretch"):
                if not profile_name:
                    st.warning("프로파일 이름을 입력해 주세요.")
                else:
                    prof = gui_utils.load_profile(profile_name)
                    if not prof:
                        st.warning("해당 이름의 프로파일이 없습니다.")
                    else:
                        st.session_state["cfg_project_root"] = prof.get(
                            "project_root", getattr(config, "DEFAULT_PROJECT_ROOT", ".")
                        )
                        st.session_state["cfg_report_dir"] = prof.get(
                            "report_dir", getattr(config, "DEFAULT_REPORT_DIR", "reports")
                        )
                        st.session_state["cfg_targets_glob"] = prof.get(
                            "targets_glob", getattr(config, "DEFAULT_TARGETS_GLOB", "libs/*.c")
                        )

                        ex = prof.get("exclude_dirs", [])
                        st.session_state["cfg_exclude_dirs"] = (
                            ", ".join(ex) if isinstance(ex, list) else (ex or "")
                        )

                        st.session_state["cfg_cppcheck_levels"] = prof.get(
                            "cppcheck_levels", getattr(config, "DEFAULT_CPPCHECK_ENABLE", [])
                        )
                        st.session_state["cfg_do_clang_tidy"] = bool(prof.get("do_clang_tidy", False))

                        ch = prof.get("clang_checks", "")
                        st.session_state["cfg_clang_checks"] = (
                            ", ".join(ch) if isinstance(ch, list) else (ch or "")
                        )

                        st.session_state["cfg_complexity_threshold"] = int(
                            prof.get(
                                "complexity_threshold",
                                getattr(config, "DEFAULT_COMPLEXITY_THRESHOLD", 10),
                            )
                        )

                        st.session_state["cfg_do_build"] = bool(prof.get("do_build", False))
                        st.session_state["cfg_do_asan"] = bool(prof.get("do_asan", False))
                        st.session_state["cfg_do_fuzz"] = bool(prof.get("do_fuzz", False))
                        st.session_state["cfg_do_qemu"] = bool(prof.get("do_qemu", False))
                        st.session_state["cfg_do_docs"] = bool(prof.get("do_docs", False))

                        st.session_state["cfg_target_arch"] = prof.get(
                            "target_arch",
                            getattr(config, "DEFAULT_TARGET_ARCH", "cortex-m0plus"),
                        )
                        st.session_state["cfg_target_macros"] = prof.get("target_macros", "")

                        inc = prof.get("include_paths", "")
                        st.session_state["cfg_include_paths"] = (
                            ", ".join(inc) if isinstance(inc, list) else (inc or "")
                        )

                        st.session_state["cfg_enable_agent"] = bool(prof.get("enable_agent", False))
                        st.session_state["cfg_enable_test_gen"] = bool(prof.get("enable_test_gen", False))
                        st.session_state["cfg_max_iterations"] = int(prof.get("max_iterations", 3))
                        st.session_state["cfg_oai_config_path"] = prof.get(
                            "oai_config_path",
                            getattr(config, "DEFAULT_OAI_CONFIG_PATH", "oai_config.json"),
                        )
                        st.session_state["cfg_llm_model"] = prof.get(
                            "llm_model",
                            getattr(config, "DEFAULT_LLM_MODEL", "gemini-3-pro-preview"),
                        )
                        roles = prof.get("agent_roles", default_agent_roles)
                        st.session_state["cfg_agent_roles"] = (
                            ", ".join(roles) if isinstance(roles, list) else (roles or default_agent_roles)
                        )
                        st.session_state["cfg_agent_run_mode"] = prof.get(
                            "agent_run_mode",
                            getattr(config, "AGENT_RUN_MODE_DEFAULT", "auto"),
                        )
                        st.session_state["cfg_agent_review"] = bool(
                            prof.get("agent_review", getattr(config, "AGENT_REVIEW_ENABLED_DEFAULT", True))
                        )
                        st.session_state["cfg_agent_rag"] = bool(
                            prof.get("agent_rag", getattr(config, "AGENT_RAG_ENABLED_DEFAULT", True))
                        )
                        st.session_state["cfg_agent_rag_top_k"] = int(
                            prof.get("agent_rag_top_k", getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3))
                        )
                        st.session_state["cfg_agent_max_steps"] = int(
                            prof.get("agent_max_steps", getattr(config, "AGENT_MAX_STEPS_DEFAULT", 3))
                        )

                        st.session_state["cfg_enable_domain_tests"] = bool(
                            prof.get("enable_domain_tests", False)
                        )
                        dom_val = prof.get("domain_targets", "")
                        st.session_state["cfg_domain_targets"] = (
                            ", ".join(dom_val)
                            if isinstance(dom_val, list)
                            else (dom_val or "")
                        )

                        st.session_state["cfg_patch_mode"] = prof.get(
                            "agent_patch_mode", default_patch_mode
                        )

                        st.success("프로파일을 불러왔습니다.")
                        st.rerun()

        with col2:
            if st.button("저장", width="stretch"):
                if not profile_name:
                    st.warning("프로파일 이름을 입력해 주세요.")
                else:
                    cfg_to_save = _build_cfg_from_state()
                    gui_utils.save_profile(profile_name, cfg_to_save)
                    gui_utils.set_last_profile(profile_name)
                    st.success("프로파일을 저장했습니다.")
                    st.rerun()

        with col3:
            if st.button("초기화", width="stretch"):
                st.session_state["cfg_project_root"] = getattr(config, "DEFAULT_PROJECT_ROOT", ".")
                st.session_state["cfg_report_dir"] = getattr(config, "DEFAULT_REPORT_DIR", "reports")
                st.session_state["cfg_targets_glob"] = getattr(config, "DEFAULT_TARGETS_GLOB", "libs/*.c")
                st.session_state["cfg_exclude_dirs"] = "build, .git, tests, external, generated"

                st.session_state["cfg_cppcheck_levels"] = getattr(config, "DEFAULT_CPPCHECK_ENABLE", [])
                st.session_state["cfg_do_clang_tidy"] = False
                st.session_state["cfg_clang_checks"] = ""
                st.session_state["cfg_complexity_threshold"] = getattr(
                    config, "DEFAULT_COMPLEXITY_THRESHOLD", 10
                )

                st.session_state["cfg_do_build"] = False
                st.session_state["cfg_do_asan"] = False
                st.session_state["cfg_do_fuzz"] = False
                st.session_state["cfg_do_qemu"] = False
                st.session_state["cfg_do_docs"] = False

                st.session_state["cfg_target_arch"] = getattr(config, "DEFAULT_TARGET_ARCH", "cortex-m0plus")
                st.session_state["cfg_target_macros"] = ""
                st.session_state["cfg_include_paths"] = ", ".join(
                    getattr(config, "DEFAULT_INCLUDE_PATHS", [])
                )

                st.session_state["cfg_enable_agent"] = False
                st.session_state["cfg_enable_test_gen"] = False
                st.session_state["cfg_max_iterations"] = 3
                st.session_state["cfg_oai_config_path"] = getattr(
                    config, "DEFAULT_OAI_CONFIG_PATH", "oai_config.json"
                )
                st.session_state["cfg_llm_model"] = getattr(
                    config, "DEFAULT_LLM_MODEL", "gemini-3-pro-preview"
                )
                st.session_state["cfg_agent_roles"] = default_agent_roles
                st.session_state["cfg_agent_run_mode"] = getattr(
                    config, "AGENT_RUN_MODE_DEFAULT", "auto"
                )
                st.session_state["cfg_agent_review"] = bool(
                    getattr(config, "AGENT_REVIEW_ENABLED_DEFAULT", True)
                )
                st.session_state["cfg_agent_rag"] = bool(
                    getattr(config, "AGENT_RAG_ENABLED_DEFAULT", True)
                )
                st.session_state["cfg_agent_rag_top_k"] = int(
                    getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3)
                )
                st.session_state["cfg_agent_max_steps"] = int(
                    getattr(config, "AGENT_MAX_STEPS_DEFAULT", 3)
                )

                st.session_state["cfg_enable_domain_tests"] = False
                st.session_state["cfg_domain_targets"] = ""
                st.session_state["cfg_patch_mode"] = default_patch_mode

                st.success("설정을 초기화했습니다.")
                st.rerun()

    # ------------------------------
    # 2. 실제 옵션 입력 UI
    # ------------------------------

    with st.sidebar.expander("📁 프로젝트 경로", expanded=True):
        st.text_input("프로젝트 루트", key="cfg_project_root")
        st.text_input("리포트 경로", key="cfg_report_dir")
        st.text_input("파일 패턴 (glob)", key="cfg_targets_glob")
        st.text_input("제외 폴더 (쉼표 구분)", key="cfg_exclude_dirs")

    with st.sidebar.expander("📊 정적 분석", expanded=False):
        cpp_options = ["warning", "performance", "portability", "style", "information"]
        st.multiselect(
            "Cppcheck 항목",
            cpp_options,
            key="cfg_cppcheck_levels",
        )
        st.checkbox("Clang-Tidy 활성화", key="cfg_do_clang_tidy")
        st.text_input("Clang-Tidy Checks (쉼표 또는 세미콜론 구분)", key="cfg_clang_checks")
        st.number_input(
            "복잡도 경고 기준(CCN)",
            min_value=1,
            max_value=100,
            step=1,
            key="cfg_complexity_threshold",
        )

    with st.sidebar.expander("⚙️ 빌드 & 동적 분석", expanded=False):
        st.checkbox("CMake Build + CTest 실행", key="cfg_do_build")
        st.checkbox("AddressSanitizer 사용", key="cfg_do_asan")
        st.checkbox("AI Fuzzing 실행", key="cfg_do_fuzz")
        st.checkbox("QEMU Smoke Test 실행", key="cfg_do_qemu")
        st.checkbox("Doxygen 문서 생성", key="cfg_do_docs")

    with st.sidebar.expander("🎯 타깃 / 컴파일", expanded=False):
        st.text_input("타깃 아키텍처", key="cfg_target_arch")
        st.text_input("추가 매크로 (공백/쉼표 구분)", key="cfg_target_macros")
        st.text_input("추가 include 경로 (쉼표 구분)", key="cfg_include_paths")

    with st.sidebar.expander("🤖 AI 에이전트", expanded=False):
        st.checkbox("AI 자동 수정 에이전트 사용", key="cfg_enable_agent")
        st.checkbox("AI 유닛 테스트 자동 생성", key="cfg_enable_test_gen")

        st.number_input(
            "최대 수정 라운드",
            min_value=1,
            max_value=10,
            step=1,
            key="cfg_max_iterations",
        )

        st.number_input(
            "에이전트 단계 최대 반복",
            min_value=1,
            max_value=10,
            step=1,
            key="cfg_agent_max_steps",
        )
        st.text_input(
            "에이전트 역할(쉼표 구분)",
            key="cfg_agent_roles",
        )
        run_modes = getattr(config, "AGENT_RUN_MODES", ["auto", "review", "off"])
        st.selectbox(
            "에이전트 실행 모드",
            options=run_modes,
            key="cfg_agent_run_mode",
        )
        st.checkbox("에이전트 리뷰어 사용", key="cfg_agent_review")
        st.checkbox("RAG/지식베이스 사용", key="cfg_agent_rag")
        st.number_input(
            "RAG Top-K",
            min_value=1,
            max_value=10,
            step=1,
            key="cfg_agent_rag_top_k",
        )

        patch_modes = getattr(config, "AGENT_PATCH_MODES", ["auto", "review", "off"])
        current_patch = st.session_state.get("cfg_patch_mode", default_patch_mode)
        if current_patch not in patch_modes:
            current_patch = default_patch_mode
            st.session_state["cfg_patch_mode"] = current_patch

        st.radio(
            "패치 모드",
            options=patch_modes,
            key="cfg_patch_mode",
            horizontal=True,
            help=(
                "auto: LLM 패치를 바로 적용"
                "review: 패치 제안만 파일로 저장 (코드 미수정)"
                "off: 에이전트 동작은 하되 코드 패치는 하지 않음"
            ),
        )

        st.text_input("LLM 설정 파일 경로", key="cfg_oai_config_path")
        model_opts: List[str] = []
        cfg_path = st.session_state.get("cfg_oai_config_path") or getattr(
            config, "DEFAULT_OAI_CONFIG_PATH", "oai_config.json"
        )
        try:
            data = gui_utils.load_json(cfg_path, default=[])
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("model"):
                        m = str(item.get("model") or "").strip()
                        if m and "gemini" in m.lower():
                            model_opts.append(m)
            elif isinstance(data, dict):
                m = str(data.get("model") or "").strip()
                if m and "gemini" in m.lower():
                    model_opts.append(m)
        except Exception:
            model_opts = []
        if "gemini-2.0-flash-exp" not in model_opts:
            model_opts.append("gemini-2.0-flash-exp")
        default_model = getattr(config, "DEFAULT_LLM_MODEL", "gemini-3-pro-preview")
        if default_model not in model_opts:
            model_opts.append(default_model)
        model_opts = sorted(list({m for m in model_opts if m}))
        current_model = st.session_state.get("cfg_llm_model", default_model)
        if current_model not in model_opts and model_opts:
            current_model = model_opts[0]
            st.session_state["cfg_llm_model"] = current_model
        st.selectbox("LLM 모델", options=model_opts, key="cfg_llm_model")

    # ------------------------------
    # Git / Jenkins (읽기 전용 정보)
    # ------------------------------
    with st.sidebar.expander("🔗 Git / Jenkins (읽기 전용)", expanded=False):
        # 프로젝트 루트 기준으로 Git / CI 상태 조회
        project_root = st.session_state.get(
            "cfg_project_root", getattr(config, "DEFAULT_PROJECT_ROOT", ".")
        )

        try:
            git_info = gui_utils.get_git_status(project_root)
        except Exception:
            git_info = {}

        try:
            ci_info = gui_utils.get_ci_env_info()
        except Exception:
            ci_info = {}

        st.markdown("**Git 상태**")
        st.write(
            {
                "branch": git_info.get("branch") or "-",
                "commit": git_info.get("commit") or "-",
                "working_tree": git_info.get("dirty") or "-",
            }
        )

        st.markdown("**CI / Jenkins 환경 변수**")
        is_jenkins = ci_info.get("is_jenkins")
        st.write(
            {
                "is_jenkins": bool(is_jenkins),
                "job_name": ci_info.get("job_name"),
                "build_number": ci_info.get("build_number"),
            }
        )
        build_url = ci_info.get("build_url")
        if build_url:
            st.markdown(f"[Build URL]({build_url})")


    with st.sidebar.expander("🧪 도메인 테스트 패널", expanded=False):
        st.checkbox("도메인 전용 테스트 패널 실행", key="cfg_enable_domain_tests")
        st.text_input("타깃 파일(상대 경로, 쉼표 구분)", key="cfg_domain_targets")

    cfg = _build_cfg_from_state()
    return cfg


def _build_cfg_from_state() -> Dict[str, Any]:
    """
    Streamlit session_state에 들어 있는 값들을
    파이프라인에서 바로 쓸 수 있는 cfg(dict)로 변환
    """
    ex_str = st.session_state.get("cfg_exclude_dirs", "")
    exclude = [d.strip() for d in ex_str.split(",") if d.strip()]

    inc_str = st.session_state.get("cfg_include_paths", "")
    include_paths = [p.strip() for p in inc_str.split(",") if p.strip()]

    chk_str = st.session_state.get("cfg_clang_checks", "")
    clang_checks = [c.strip() for c in chk_str.replace(";", ",").split(",") if c.strip()]

    domain_str = st.session_state.get("cfg_domain_targets", "")
    domain_targets = [t.strip() for t in domain_str.split(",") if t.strip()]

    roles_str = st.session_state.get("cfg_agent_roles", "")
    agent_roles = [r.strip() for r in str(roles_str).split(",") if r.strip()]

    cfg: Dict[str, Any] = {
        "project_root": st.session_state.get("cfg_project_root", getattr(config, "DEFAULT_PROJECT_ROOT", ".")),
        "report_dir": st.session_state.get("cfg_report_dir", getattr(config, "DEFAULT_REPORT_DIR", "reports")),
        "targets_glob": st.session_state.get("cfg_targets_glob", getattr(config, "DEFAULT_TARGETS_GLOB", "libs/*.c")),
        "exclude_dirs": exclude,

        "cppcheck_levels": st.session_state.get(
            "cfg_cppcheck_levels", getattr(config, "DEFAULT_CPPCHECK_ENABLE", [])
        ),
        "do_clang_tidy": st.session_state.get("cfg_do_clang_tidy", False),
        "clang_checks": clang_checks,
        "complexity_threshold": int(
            st.session_state.get("cfg_complexity_threshold", getattr(config, "DEFAULT_COMPLEXITY_THRESHOLD", 10))
        ),

        "do_build": st.session_state.get("cfg_do_build", False),
        "do_asan": st.session_state.get("cfg_do_asan", False),
        "do_fuzz": st.session_state.get("cfg_do_fuzz", False),
        "do_qemu": st.session_state.get("cfg_do_qemu", False),
        "do_docs": st.session_state.get("cfg_do_docs", False),

        "target_arch": st.session_state.get(
            "cfg_target_arch", getattr(config, "DEFAULT_TARGET_ARCH", "cortex-m0plus")
        ),
        "target_macros": st.session_state.get("cfg_target_macros", ""),
        "include_paths": include_paths,

        "enable_agent": st.session_state.get("cfg_enable_agent", False),
        "enable_test_gen": st.session_state.get("cfg_enable_test_gen", False),
        "max_iterations": int(st.session_state.get("cfg_max_iterations", 3)),
        "oai_config_path": st.session_state.get(
            "cfg_oai_config_path", getattr(config, "DEFAULT_OAI_CONFIG_PATH", "oai_config.json")
        ),
        "llm_model": st.session_state.get(
            "cfg_llm_model", getattr(config, "DEFAULT_LLM_MODEL", "gemini-3-pro-preview")
        ),
        "agent_roles": agent_roles,
        "agent_run_mode": st.session_state.get(
            "cfg_agent_run_mode",
            getattr(config, "AGENT_RUN_MODE_DEFAULT", "auto"),
        ),
        "agent_review": bool(st.session_state.get("cfg_agent_review", True)),
        "agent_rag": bool(st.session_state.get("cfg_agent_rag", True)),
        "agent_rag_top_k": int(
            st.session_state.get("cfg_agent_rag_top_k", getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3))
        ),
        "agent_max_steps": int(
            st.session_state.get("cfg_agent_max_steps", getattr(config, "AGENT_MAX_STEPS_DEFAULT", 3))
        ),

        "enable_domain_tests": st.session_state.get("cfg_enable_domain_tests", False),
        "domain_targets": domain_targets,

        "agent_patch_mode": st.session_state.get(
            "cfg_patch_mode",
            getattr(config, "AGENT_PATCH_MODE_DEFAULT", "auto"),
        ),
    }
    return cfg
