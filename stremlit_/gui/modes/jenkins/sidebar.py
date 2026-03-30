# -*- coding: utf-8 -*-
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Dict, Optional

import streamlit as st

import config
import gui_utils
from jenkins_client import JenkinsClient, JenkinsServerClient

from .helpers import _job_slug, _norm_job_url, _detect_reports_dir, _guess_project_root
from .sync import _sync_jenkins_artifacts, _sync_local_reports


def _normalize_list_input(val: Any, default: str = "") -> str:
    if isinstance(val, list):
        return ", ".join(str(x) for x in val if str(x).strip())
    if isinstance(val, str):
        return val
    return default


def _build_cfg_from_profile(profile: Dict[str, Any], overrides: Dict[str, Any], use_profile: bool) -> Dict[str, Any]:
    if not isinstance(profile, dict):
        profile = {}

    cfg: Dict[str, Any] = {
        "project_root": overrides.get("project_root"),
        "report_dir": overrides.get("report_dir", "reports_workflow"),
        "targets_glob": overrides.get("targets_glob", getattr(config, "DEFAULT_TARGETS_GLOB", "libs/*.c")),
        "exclude_dirs": _normalize_list_input(profile.get("exclude_dirs"), "build, .git, tests, external, generated"),
        "include_paths": _normalize_list_input(profile.get("include_paths"), ", ".join(getattr(config, "DEFAULT_INCLUDE_PATHS", []))),
        "clang_checks": _normalize_list_input(profile.get("clang_checks"), ""),
        "cppcheck_levels": profile.get("cppcheck_levels", getattr(config, "DEFAULT_CPPCHECK_ENABLE", [])),
        "do_build": bool(profile.get("do_build", False)),
        "do_asan": bool(profile.get("do_asan", False)),
        "do_fuzz": bool(profile.get("do_fuzz", False)),
        "do_qemu": bool(profile.get("do_qemu", False)),
        "do_docs": bool(profile.get("do_docs", False)),
        "do_clang_tidy": bool(profile.get("do_clang_tidy", False)),
        "target_arch": profile.get("target_arch", getattr(config, "DEFAULT_TARGET_ARCH", "cortex-m0plus")),
        "target_macros": profile.get("target_macros", ""),
        "complexity_threshold": int(profile.get("complexity_threshold", getattr(config, "DEFAULT_COMPLEXITY_THRESHOLD", 10))),
        "enable_agent": bool(profile.get("enable_agent", False)),
        "enable_test_gen": bool(profile.get("enable_test_gen", False)),
        "max_iterations": int(profile.get("max_iterations", 3)),
        "oai_config_path": profile.get("oai_config_path", getattr(config, "DEFAULT_OAI_CONFIG_PATH", "oai_config.json")),
        "llm_model": profile.get("llm_model", getattr(config, "DEFAULT_LLM_MODEL", "gemini-3-pro-preview")),
        "agent_roles": _normalize_list_input(profile.get("agent_roles"), ", ".join(getattr(config, "AGENT_ROLES_DEFAULT", []))),
        "agent_run_mode": profile.get("agent_run_mode", getattr(config, "AGENT_RUN_MODE_DEFAULT", "auto")),
        "agent_review": bool(profile.get("agent_review", getattr(config, "AGENT_REVIEW_ENABLED_DEFAULT", True))),
        "agent_rag": bool(profile.get("agent_rag", getattr(config, "AGENT_RAG_ENABLED_DEFAULT", True))),
        "agent_rag_top_k": int(profile.get("agent_rag_top_k", getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3))),
        "agent_max_steps": int(profile.get("agent_max_steps", getattr(config, "AGENT_MAX_STEPS_DEFAULT", 3))),
        "enable_domain_tests": bool(profile.get("enable_domain_tests", False)),
        "domain_targets": _normalize_list_input(profile.get("domain_targets"), ""),
        "agent_patch_mode": profile.get("agent_patch_mode", getattr(config, "AGENT_PATCH_MODE_DEFAULT", "auto")),
        "verbose_progress": True,
    }

    if not use_profile:
        for key in (
            "do_build",
            "do_asan",
            "do_fuzz",
            "do_qemu",
            "do_docs",
            "do_clang_tidy",
            "enable_agent",
            "enable_test_gen",
            "enable_domain_tests",
        ):
            cfg[key] = False

    for k, v in overrides.items():
        if v is not None:
            cfg[k] = v

    return cfg


def _render_workflow_runner(build_root: Optional[Path], reports_dir: Optional[Path]) -> None:
    st.sidebar.markdown("---")
    st.sidebar.subheader("🚀 워크플로우 실행(동기화 소스)")

    if not build_root or not build_root.exists():
        st.sidebar.info("동기화 이후에 실행할 수 있습니다.")
        return

    broot = Path(build_root).resolve()
    rdir = reports_dir or _detect_reports_dir(broot)
    guess_root = _guess_project_root(broot, rdir)

    seed_key = "_jenkins_wf_seed_root"
    if st.session_state.get(seed_key) != str(broot):
        st.session_state[seed_key] = str(broot)
        st.session_state["jenkins_wf_project_root"] = guess_root
        st.session_state.setdefault("jenkins_wf_report_dir", "reports_workflow")
        st.session_state.setdefault("jenkins_wf_targets_glob", getattr(config, "DEFAULT_TARGETS_GLOB", "libs/*.c"))

    project_root = st.sidebar.text_input(
        "project_root",
        value=str(st.session_state.get("jenkins_wf_project_root") or guess_root),
        key="jenkins_wf_project_root",
        help="동기화된 소스 루트를 자동 추정. 필요 시 수정하세요.",
    )
    report_dir = st.sidebar.text_input(
        "report_dir",
        value=str(st.session_state.get("jenkins_wf_report_dir") or "reports_workflow"),
        key="jenkins_wf_report_dir",
        help="소스 루트 기준 상대 경로 (기본: reports_workflow)",
    )
    targets_glob = st.sidebar.text_input(
        "targets_glob",
        value=str(st.session_state.get("jenkins_wf_targets_glob") or getattr(config, "DEFAULT_TARGETS_GLOB", "libs/*.c")),
        key="jenkins_wf_targets_glob",
    )

    profiles, last_profile = gui_utils.load_all_profiles()
    names = sorted(list(profiles.keys())) if profiles else []
    default_profile = last_profile or (names[0] if names else "")
    prof_options = ["(기본값)"] + names
    prof_default = "(기본값)" if not default_profile else default_profile
    if prof_default not in prof_options:
        prof_default = "(기본값)"
    prof_idx = prof_options.index(prof_default)
    selected_profile = st.sidebar.selectbox(
        "프로파일",
        options=prof_options,
        index=prof_idx,
        key="jenkins_wf_profile_name",
        help="로컬 모드에서 저장한 프로파일을 선택하면 대부분의 옵션을 재사용합니다.",
    )
    use_profile = st.sidebar.checkbox(
        "프로파일 설정 사용",
        value=True,
        key="jenkins_wf_use_profile",
        help="끄면 최소 정적 분석 중심으로 실행됩니다.",
    )

    oai_path = st.sidebar.text_input(
        "oai_config_path(옵션)",
        value=str(st.session_state.get("jenkins_wf_oai_path") or ""),
        key="jenkins_wf_oai_path",
    )

    prof = gui_utils.load_profile(selected_profile) if selected_profile and selected_profile != "(기본값)" else {}
    overrides = {
        "project_root": project_root,
        "report_dir": report_dir,
        "targets_glob": targets_glob,
    }
    if oai_path.strip():
        overrides["oai_config_path"] = oai_path.strip()

    cfg = _build_cfg_from_profile(prof, overrides, use_profile=bool(use_profile))
    root_ok = bool(project_root) and Path(str(project_root)).expanduser().exists()

    c_run, c_stop = st.sidebar.columns(2)
    start_btn = c_run.button("▶️ 분석 시작", type="primary", width="stretch", disabled=not root_ok)
    stop_btn = c_stop.button("⛔ 작업 중지", type="secondary", width="stretch")

    paths = gui_utils.get_paths(cfg["project_root"], cfg["report_dir"]) if root_ok else None
    stop_flag = (paths["REPORT"] / ".stop") if paths else None

    if stop_btn and paths:
        stop_flag.touch()
        run_state = st.session_state.get("jenkins_pipeline_async") or {}
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
        if paths:
            try:
                gui_utils.append_log_line(paths["SYSTEM_LOG"], "stopped by user")
            except Exception:
                pass
        st.session_state.pop("jenkins_pipeline_async", None)
        st.sidebar.warning("작업 중지 요청됨")

    if start_btn and root_ok and paths:
        if stop_flag and stop_flag.exists():
            stop_flag.unlink()
        run_state = gui_utils.start_pipeline_async(cfg, paths)
        st.session_state["jenkins_pipeline_async"] = run_state
        st.sidebar.success("분석 시작됨")
        st.rerun()

    run_state = st.session_state.get("jenkins_pipeline_async") or {}
    if run_state and run_state.get("status_path"):
        status_path = Path(str(run_state.get("status_path")))
        log_path = Path(str(run_state.get("log_path")))
        auto_refresh = st.sidebar.checkbox("Auto refresh while running", value=True, key="jenkins_auto_refresh_run")
        status_data = gui_utils.read_run_status(status_path)
        state = str(status_data.get("state") or "unknown")
        status_box = st.sidebar.status(f"분석 상태: {state}", expanded=True)
        if status_data.get("exit_code") is not None:
            status_box.update(
                label=f"분석 완료 (exit_code={status_data.get('exit_code')})",
                state="complete",
                expanded=False,
            )
        st.sidebar.code(gui_utils.tail_file(log_path, max_lines=6), language="text")
        if state == "completed":
            st.session_state.pop("jenkins_pipeline_async", None)
        elif auto_refresh:
            st.rerun()

    if not root_ok:
        st.sidebar.warning("project_root 경로가 유효하지 않습니다. 동기화된 소스 경로를 확인하세요.")


def _render_jenkins_sidebar_and_context() -> Dict[str, Any]:
    """
    Jenkins Viewer 사이드바 구성.
    - Job(프로젝트) 단위로 선택
    - 기본: 최신 성공 빌드(lastSuccessfulBuild)
    - 필요 시 빌드 번호를 직접 선택 가능
    - Sync 시 선택 빌드의 아티팩트를 캐시에 다운로드 + viewer summary 생성
    """
    st.sidebar.header("☁️ Jenkins Viewer")
    st.sidebar.caption(f"ENTRY: {__file__}")

    base_url = (getattr(config, "JENKINS_BASE_URL", "") or "").strip().rstrip("/")
    username = (getattr(config, "JENKINS_USERNAME", "") or "").strip()
    api_token = (getattr(config, "JENKINS_API_TOKEN", "") or "").strip()
    verify_tls_default = bool(getattr(config, "JENKINS_VERIFY_TLS", True))

    st.sidebar.caption(f"Base URL: {base_url}" if base_url else "Base URL 미설정")

    st.session_state["jenkins_verify_tls"] = st.sidebar.checkbox(
        "TLS verify",
        value=bool(st.session_state.get("jenkins_verify_tls", verify_tls_default)),
    )

    cache_root_str = st.sidebar.text_input(
        "캐시 루트",
        value=str(st.session_state.get("jenkins_cache_root", str(Path.home() / ".devops_pro_cache"))),
        help="로컬에 Jenkins build artifacts를 저장할 루트",
    )
    st.session_state["jenkins_cache_root"] = cache_root_str

    patterns_str = st.sidebar.text_input(
        "아티팩트 패턴(, 구분)",
        value=str(
            st.session_state.get(
                "jenkins_patterns",
                "*.html, *.htm, *.xlsx, *.xlsm, *.csv, *.log, *.txt, reports/**",
            )
        ),
        help="다운로드 대상 필터, 예: *.html, reports/**",
    )
    st.session_state["jenkins_patterns"] = patterns_str

    # ------------------------------------------------------------------
    # 소스 파일 탐색 보조(에디터/리포트에서 파일을 못 찾는 경우 대응)
    # - Jenkins 아티팩트에 소스(.c/.h)가 포함되지 않으면 Editor에서 파일 열기 실패 가능
    # - 이 경우, 아래 "소스 루트"에 로컬/컨테이너 내 소스 폴더를 추가하면 자동 탐색 가능
    # ------------------------------------------------------------------
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔎 소스 탐색 설정")

    src_roots_str = st.sidebar.text_area(
        "소스 루트(콤마/줄바꿈 구분)",
        value=str(st.session_state.get("viewer_source_roots_str", "")),
        height=70,
        help="예: /app/my_repo, /app/workspace/project\n(여러 경로 입력 가능)",
    )
    st.session_state["viewer_source_roots_str"] = src_roots_str

    def _parse_roots(s: str) -> list[str]:
        xs: list[str] = []
        for tok in (s or "").replace("\n", ",").split(","):
            t = tok.strip()
            if not t:
                continue
            xs.append(t)
        # 중복 제거(순서 유지)
        out: list[str] = []
        seen: set[str] = set()
        for x in xs:
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        return out

    viewer_source_roots: list[str] = []
    for r in _parse_roots(src_roots_str):
        try:
            p = Path(r).expanduser().resolve()
            if p.exists() and p.is_dir():
                viewer_source_roots.append(str(p))
        except Exception:
            continue
    st.session_state["viewer_source_roots"] = viewer_source_roots

    path_map_str = st.sidebar.text_area(
        "경로 매핑(FROM => TO, 줄바꿈)",
        value=str(st.session_state.get("viewer_path_maps_str", "")),
        height=70,
        help="리포트의 절대경로 prefix를 소스 루트로 치환\n예: /var/lib/jenkins/workspace/job => /app/my_repo",
    )
    st.session_state["viewer_path_maps_str"] = path_map_str

    path_maps: list[tuple[str, str]] = []
    for ln in (path_map_str or "").splitlines():
        if "=>" not in ln:
            continue
        a, b = ln.split("=>", 1)
        a = a.strip().rstrip("/")
        b = b.strip().rstrip("/")
        if a and b:
            path_maps.append((a, b))
    st.session_state["viewer_path_maps"] = path_maps

    auto_sync = st.sidebar.checkbox(
        "빌드 변경 시 자동 Sync",
        value=bool(st.session_state.get("jenkins_auto_sync", False)),
        help="빌드 선택을 바꾸면 자동으로 동기화 실행",
    )
    st.session_state["jenkins_auto_sync"] = bool(auto_sync)

    # 접속 정보 없으면 여기서 종료
    if not base_url or not username or not api_token:
        st.sidebar.error("Jenkins 접속 정보 미설정, config.py의 JENKINS_* 또는 ENV(DEVOPS_JENKINS_*) 확인 필요")
        return {"ready": False}

    # 1) 프로젝트 목록
    col_p1, col_p2 = st.sidebar.columns([2, 1])
    refresh_jobs = col_p2.button("🔄", width="stretch", help="프로젝트 목록 새로고침")

    if refresh_jobs or ("jenkins_jobs" not in st.session_state):
        try:
            srv = JenkinsServerClient(
                base_url=base_url,
                username=username,
                api_token=api_token,
                timeout_sec=30,
                verify_ssl=bool(st.session_state["jenkins_verify_tls"]),
            )
            jobs = [j.__dict__ for j in srv.list_jobs()]
            st.session_state["jenkins_jobs"] = jobs
        except Exception as e:
            st.session_state["jenkins_jobs"] = []
            st.sidebar.error(f"프로젝트 목록 조회 실패: {e}")
            st.sidebar.code(traceback.format_exc())

    jobs = st.session_state.get("jenkins_jobs", []) or []
    job_name = ""
    job_url = ""

    if jobs:
        names = [j.get("name", "") for j in jobs if j.get("name") and j.get("url")]
        names = sorted(list(dict.fromkeys(names)))
        last_name = str(st.session_state.get("jenkins_job_name") or (names[0] if names else ""))
        idx = names.index(last_name) if last_name in names else 0

        job_name = st.sidebar.selectbox("프로젝트", options=names, index=idx, key="jenkins_job_name")
        job_url = next((j.get("url", "") for j in jobs if j.get("name") == job_name), "") or ""
        job_url = _norm_job_url(job_url)
        st.session_state["jenkins_job_url"] = job_url

        # 프로젝트 바뀌면 빌드 목록/선택 초기화
        if st.session_state.get("_jenkins_last_job_name") != job_name:
            st.session_state["_jenkins_last_job_name"] = job_name
            st.session_state.pop("jenkins_builds", None)
            st.session_state["jenkins_build_mode"] = "latest_success"
            st.session_state.pop("jenkins_build_number", None)
            st.session_state.pop("jenkins_last_build", None)
    else:
        job_url = st.sidebar.text_input(
            "프로젝트 URL (fallback)",
            value=str(st.session_state.get("jenkins_job_url", "")),
            key="jenkins_job_url",
        )
        job_url = _norm_job_url(job_url)
        job_name = job_url.rstrip("/").split("/")[-1] if job_url else ""

    job_url = (job_url or "").strip()
    if not job_url:
        st.sidebar.info("프로젝트 선택 후 동기화 가능")
        return {"ready": False, "job_url": "", "job_name": ""}

    proj_paths = gui_utils.load_jenkins_project_paths()
    default_list = proj_paths.get(str(job_name or ""), [])
    local_paths_str = st.sidebar.text_area(
        "로컬 리포트 경로 (선택, 여러 줄)",
        value="\n".join(default_list),
        height=70,
        key="jenkins_local_report_dirs",
        help="Jenkins 리포트 대신 로컬 리포트 폴더를 지정할 수 있음.",
    )
    local_paths = [p.strip() for p in (local_paths_str or "").splitlines() if p.strip()]
    if st.sidebar.button("경로 목록 저장", type="secondary"):
        proj_paths[str(job_name or "")] = local_paths
        gui_utils.save_jenkins_project_paths(proj_paths)
        st.sidebar.success("경로 목록 저장됨")

    selected_local_path = ""
    if local_paths:
        selected_local_path = st.sidebar.selectbox(
            "로컬 리포트 선택",
            options=local_paths,
            index=0,
            key="jenkins_local_report_dir_pick",
        )

    use_local = st.sidebar.checkbox(
        "로컬 리포트 사용",
        value=bool(local_paths),
        key="jenkins_use_local_report_dir",
    )

    # 2) 빌드 선택: 기본 latest success + 선택 빌드 번호
    # 빌드 목록 조회는 job_url 이후 가능
    try:
        client = JenkinsClient(
            job_url=_norm_job_url(job_url),
            username=username,
            api_token=api_token,
            timeout_sec=30,
            verify_ssl=bool(st.session_state["jenkins_verify_tls"]),
        )
    except Exception:
        client = None  # type: ignore

    if client is not None:
        # 최신 성공 빌드 번호
        latest_success_num = -1
        try:
            b = client.get_build_info("lastSuccessfulBuild")
            latest_success_num = int(getattr(b, "number", -1))
        except Exception:
            latest_success_num = -1

        # 빌드 목록 (최근 N)
        col_b1, col_b2 = st.sidebar.columns([2, 1])
        limit = col_b1.number_input(
            "빌드 목록 개수",
            min_value=5,
            max_value=200,
            value=int(st.session_state.get("jenkins_builds_limit", 30)),
            step=5,
            help="최근 빌드 목록을 불러오는 개수",
        )
        st.session_state["jenkins_builds_limit"] = int(limit)
        refresh_builds = col_b2.button("↻", width="stretch", help="빌드 목록 새로고침")

        if refresh_builds or ("jenkins_builds" not in st.session_state):
            try:
                builds = client.list_builds(limit=int(limit))
                st.session_state["jenkins_builds"] = [x.__dict__ for x in builds]
            except Exception:
                st.session_state["jenkins_builds"] = []

        builds = st.session_state.get("jenkins_builds", []) or []
        build_mode = st.sidebar.radio(
            "빌드 선택",
            options=["latest_success", "pick_number"],
            index=0 if st.session_state.get("jenkins_build_mode", "latest_success") == "latest_success" else 1,
            format_func=lambda v: "최신 성공(lastSuccessfulBuild)" if v == "latest_success" else "빌드 번호 선택",
            key="jenkins_build_mode",
        )

        build_number = None
        build_selector = "lastSuccessfulBuild"

        if build_mode == "pick_number":
            nums = [int(b.get("number", -1)) for b in builds if isinstance(b, dict) and int(b.get("number", -1)) >= 0]
            nums = sorted(list(dict.fromkeys(nums)), reverse=True)
            if not nums:
                st.sidebar.warning("빌드 목록이 비어있음, 최신 성공으로 폴백")
            else:
                default_num = st.session_state.get("jenkins_build_number")
                if default_num is None:
                    default_num = latest_success_num if latest_success_num in nums else nums[0]
                default_num = int(default_num)
                if default_num not in nums:
                    default_num = nums[0]
                build_number = st.sidebar.selectbox(
                    "빌드 번호",
                    options=nums,
                    index=nums.index(default_num),
                    key="jenkins_build_number",
                )
                build_selector = str(int(build_number))
        else:
            build_selector = "lastSuccessfulBuild"
            if latest_success_num >= 0:
                st.sidebar.caption(f"Latest success: #{latest_success_num}")
            else:
                st.sidebar.caption("Latest success: (없음/조회 실패)")

        st.session_state["jenkins_build_selector"] = build_selector
    else:
        st.session_state["jenkins_build_selector"] = "lastSuccessfulBuild"

    # 3) 동기화 실행
    sync_prev = st.sidebar.checkbox(
        "이전 빌드도 동기화",
        value=bool(st.session_state.get("jenkins_sync_prev", True)),
        help="선택 빌드와 직전 빌드(가능하면)까지 함께 동기화하여 비교 요약을 활성화합니다.",
    )
    st.session_state["jenkins_sync_prev"] = bool(sync_prev)
    sync_btn = st.sidebar.button("📥 아티팩트 동기화", type="primary", width="stretch")
    do_auto = bool(st.session_state.get("jenkins_auto_sync", False))

    # build selector 변경 감지 (auto sync)
    sel = str(st.session_state.get("jenkins_build_selector") or "lastSuccessfulBuild")
    prev_sel = str(st.session_state.get("_jenkins_prev_selector") or "")
    selector_changed = sel != prev_sel
    st.session_state["_jenkins_prev_selector"] = sel

    if sync_btn or (do_auto and selector_changed):
        try:
            if use_local and str(selected_local_path or "").strip():
                local_dir = Path(str(selected_local_path)).expanduser().resolve()
                if local_dir.exists() and local_dir.is_dir():
                    build_info, build_root, reports_dir, downloaded, artifacts = _sync_local_reports(
                        job_url=job_url,
                        local_reports_dir=local_dir,
                    )
                    st.session_state["jenkins_last_build"] = int(build_info.get("number") or -1)
                    st.session_state["jenkins_build_root"] = str(build_root)
                    st.session_state["jenkins_reports_dir"] = str(reports_dir)
                    st.session_state["jenkins_artifacts"] = artifacts

                    st.session_state["viewer_build_root"] = str(build_root)
                    st.session_state["viewer_reports_dir"] = str(reports_dir)
                    st.session_state["viewer_job_url"] = str(job_url)
                    st.session_state["viewer_job_name"] = str(job_name)
                    st.session_state["viewer_job_slug"] = str(_job_slug(job_url))

                    st.sidebar.success("로컬 리포트 동기화 완료")
                    st.rerun()
                else:
                    st.sidebar.warning("로컬 리포트 경로가 유효하지 않음. Jenkins 동기화를 확인하세요.")

            cache_root = Path(cache_root_str).expanduser()
            patterns = [p.strip() for p in (patterns_str or "").split(",") if p.strip()]
            build_info, build_root, reports_dir, downloaded, artifacts = _sync_jenkins_artifacts(
                job_url=job_url,
                username=username,
                api_token=api_token,
                cache_root=cache_root,
                verify_tls=bool(st.session_state["jenkins_verify_tls"]),
                build_selector=str(st.session_state.get("jenkins_build_selector") or "lastSuccessfulBuild"),
                patterns=patterns,
            )
            st.session_state["jenkins_last_build"] = int(build_info.get("number") or -1)
            st.session_state["jenkins_build_root"] = str(build_root)
            st.session_state["jenkins_reports_dir"] = str(reports_dir)
            st.session_state["jenkins_artifacts"] = artifacts

            # Editor/Reports 탭에서 공통으로 쓰는 viewer 키(후방 호환)
            st.session_state["viewer_build_root"] = str(build_root)
            st.session_state["viewer_reports_dir"] = str(reports_dir)
            st.session_state["viewer_job_url"] = str(job_url)
            st.session_state["viewer_job_name"] = str(job_name)
            st.session_state["viewer_job_slug"] = str(_job_slug(job_url))

            # ------------------------------------------------------------------
            # Jenkins scan 결과에서 소스 루트 후보를 자동 반영
            # - 일부 job은 app/** 또는 svn_wc/** 형태로 소스가 캐시에 포함됨
            # - Editor에서 file을 못 찾는 케이스를 줄이기 위해 build_root 기준 후보를 주입
            # ------------------------------------------------------------------
            try:
                js = gui_utils.load_json(Path(str(reports_dir)) / "jenkins_scan.json", default={})
                rels = (js or {}).get("source_roots") if isinstance(js, dict) else None
                if isinstance(rels, list) and rels:
                    abs_roots: list[str] = []
                    for rel in rels:
                        if not rel:
                            continue
                        try:
                            p = (Path(str(build_root)) / str(rel)).resolve()
                            if p.exists() and p.is_dir():
                                abs_roots.append(str(p))
                        except Exception:
                            continue

                    # 사용자가 직접 입력한 소스 루트가 없을 때만 자동 주입
                    cur_str = str(st.session_state.get("viewer_source_roots_str") or "").strip()
                    if abs_roots and not cur_str:
                        st.session_state["viewer_source_roots_str"] = "\n".join(abs_roots)
                        st.session_state["viewer_source_roots"] = abs_roots
            except Exception:
                pass

            # optional: sync previous build for diff
            if sync_prev:
                prev_selector: Optional[str] = None
                try:
                    nums = [int(b.get("number", -1)) for b in builds if isinstance(b, dict)]
                    nums = sorted(list(dict.fromkeys([n for n in nums if n >= 0])), reverse=True)
                    cur_sel = str(st.session_state.get("jenkins_build_selector") or "lastSuccessfulBuild")
                    cur_num = None
                    if cur_sel.isdigit():
                        cur_num = int(cur_sel)
                    elif latest_success_num >= 0:
                        cur_num = int(latest_success_num)
                    if cur_num is not None:
                        candidates = [n for n in nums if n < cur_num]
                        if candidates:
                            prev_selector = str(max(candidates))
                    elif len(nums) >= 2:
                        prev_selector = str(nums[1])
                except Exception:
                    prev_selector = None

                if prev_selector:
                    try:
                        prev_info, prev_root, prev_reports, _, _ = _sync_jenkins_artifacts(
                            job_url=job_url,
                            username=username,
                            api_token=api_token,
                            cache_root=cache_root,
                            verify_tls=bool(st.session_state["jenkins_verify_tls"]),
                            build_selector=str(prev_selector),
                            patterns=patterns,
                        )
                        st.session_state["jenkins_prev_build"] = int(prev_info.get("number") or -1)
                        st.session_state["jenkins_prev_build_root"] = str(prev_root)
                        st.session_state["jenkins_prev_reports_dir"] = str(prev_reports)
                    except Exception:
                        st.session_state["jenkins_prev_build"] = None
                        st.session_state["jenkins_prev_build_root"] = None
                        st.session_state["jenkins_prev_reports_dir"] = None
                else:
                    st.session_state["jenkins_prev_build"] = None
                    st.session_state["jenkins_prev_build_root"] = None
                    st.session_state["jenkins_prev_reports_dir"] = None
            st.sidebar.success(f"동기화 완료, files={len(downloaded)}")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"동기화 실패: {e}")
            st.sidebar.code(traceback.format_exc())

    # 현재 컨텍스트 반환
    job_slug = _job_slug(job_url)
    job_cache_dir = (Path(cache_root_str).expanduser() / "jenkins" / job_slug).resolve()

    # 워크플로우 실행 패널 (동기화된 소스 기준)
    try:
        broot = st.session_state.get("jenkins_build_root")
        rdir = st.session_state.get("jenkins_reports_dir")
        _render_workflow_runner(Path(str(broot)) if broot else None, Path(str(rdir)) if rdir else None)
    except Exception:
        pass

    return {
        "ready": True,
        "job_name": job_name,
        "job_url": job_url,
        "job_slug": job_slug,
        "job_cache_dir": str(job_cache_dir),
        "build_selector": str(st.session_state.get("jenkins_build_selector") or "lastSuccessfulBuild"),
        "build_root": st.session_state.get("jenkins_build_root"),
        "reports_dir": st.session_state.get("jenkins_reports_dir"),
        "build_info": {
            "job_url": job_url,
            "number": st.session_state.get("jenkins_last_build"),
        },
        "artifacts": st.session_state.get("jenkins_artifacts"),
    }


__all__ = ["_render_jenkins_sidebar_and_context"]
