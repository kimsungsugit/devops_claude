# /app/gui/tabs/scm.py
# -*- coding: utf-8 -*-
"""SCM tools (Local mode)
- SVN checkout / update
- Git clone / pull / checkout
주의
- credential은 가능한 SSH 키/credential helper 사용 권장
- UI에 비밀번호 직접 입력 지양
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

import streamlit as st

import gui_utils
import ui_common


def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def _run_cmd(args: List[str], cwd: Path, timeout_sec: int = 900) -> Tuple[int, str]:
    # shell 사용 금지, 인자 리스트만 허용
    try:
        p = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
        return int(p.returncode), out.strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout expired"
    except Exception as e:
        return 1, f"exception: {e}"


def render_scm(project_root: str) -> None:
    root = Path(project_root or ".").resolve()

    st.subheader("🗂️ SCM, SVN / Git")
    st.caption("로컬 분석/ Jenkins Viewer 공용, Jenkins Viewer에서는 소스 확보·확인 용도 권장")

    c1, c2 = st.columns([2, 1])
    with c1:
        dest_rel = st.text_input("작업 디렉터리(프로젝트 루트 기준 상대 경로)", value=".", help="예: ., workspace, src")
    with c2:
        timeout_sec = st.number_input("timeout(sec)", min_value=30, max_value=3600, value=900, step=30)

    try:
        workdir = ui_common.safe_resolve_under(root, dest_rel or ".")
    except Exception as e:
        st.error("작업 디렉터리 경로가 유효하지 않음, 경로 탈출 차단")
        ui_common.log_exception("SCM workdir containment", e)
        return
    st.write({"project_root": str(root), "workdir": str(workdir)})

    st.divider()
    mode = st.radio("SCM 종류", options=["Git", "SVN"], horizontal=True)

    log_key = "scm_last_output"
    if log_key not in st.session_state:
        st.session_state[log_key] = ""

    def show_output(rc: int, out: str) -> None:
        # 과도한 출력 방지
        max_chars = 40000
        if len(out) > max_chars:
            out = "(tail)\n" + out[-max_chars:]
        st.session_state[log_key] = out
        if rc == 0:
            st.success("완료")
            # 성공 시 현재 dest를 에디터 기준 프로젝트 루트로 기억
            try:
                if "dest" in locals() and isinstance(dest, Path) and dest.exists():
                    st.session_state["viewer_project_root"] = str(dest.resolve())
            except Exception:
                pass
        else:
            st.error(f"실패, rc={rc}")
        st.code(out or "(no output)", language="text")

    if mode == "Git":
        git_bin = _which("git")
        if not git_bin:
            st.error("git 미설치 상태")
            return

        repo_url = st.text_input("Git URL", value="", placeholder="ssh 또는 https URL")
        branch = st.text_input("branch(optional)", value="", placeholder="예: main")
        depth = st.number_input("depth(optional, 0=full)", min_value=0, max_value=1000, value=0, step=1)

        dest_dir = st.text_input("clone destination(상대 경로)", value=".", help="workdir 기준, 예: . 또는 repo")
        dest = ui_common.safe_resolve_under(workdir, dest_dir or ".")

        cc1, cc2, cc3, cc4 = st.columns(4)
        do_clone = cc1.button("Clone", width="stretch")
        do_pull = cc2.button("Pull", width="stretch")
        do_fetch = cc3.button("Fetch", width="stretch")
        do_checkout = cc4.button("Checkout", width="stretch")

        if do_clone:
            if not repo_url:
                st.warning("Git URL 필요")
            else:
                args: List[str] = [git_bin, "clone"]
                if branch.strip():
                    args += ["--branch", branch.strip()]
                if int(depth) > 0:
                    args += ["--depth", str(int(depth))]
                args += [repo_url.strip(), str(dest)]
                rc, out = _run_cmd(args, cwd=workdir, timeout_sec=int(timeout_sec))
                show_output(rc, out)

        if do_fetch:
            if not (dest / ".git").exists():
                st.warning("대상 디렉터리에 .git 없음, 먼저 clone 필요")
            else:
                rc, out = _run_cmd([git_bin, "fetch", "--all", "--prune"], cwd=dest, timeout_sec=int(timeout_sec))
                show_output(rc, out)

        if do_pull:
            if not (dest / ".git").exists():
                st.warning("대상 디렉터리에 .git 없음, 먼저 clone 필요")
            else:
                rc, out = _run_cmd([git_bin, "pull", "--ff-only"], cwd=dest, timeout_sec=int(timeout_sec))
                show_output(rc, out)

        if do_checkout:
            if not (dest / ".git").exists():
                st.warning("대상 디렉터리에 .git 없음")
            elif not branch.strip():
                st.warning("branch 입력 필요")
            else:
                rc, out = _run_cmd([git_bin, "checkout", branch.strip()], cwd=dest, timeout_sec=int(timeout_sec))
                show_output(rc, out)

        st.divider()
        st.markdown("**Git 상태**")
        try:
            info = gui_utils.get_git_status(str(dest))
        except Exception:
            info = {}
        st.write(info or {})

    else:
        svn_bin = _which("svn")
        if not svn_bin:
            st.error("svn(Subversion) 미설치 상태")
            return

        repo_url = st.text_input("SVN URL", value="", placeholder="svn:// 또는 https:// ...")
        revision = st.text_input("revision(optional)", value="", placeholder="예: 12345")
        dest_dir = st.text_input("checkout destination(상대 경로)", value=".", help="workdir 기준, 예: . 또는 repo")
        dest = ui_common.safe_resolve_under(workdir, dest_dir or ".")

        cc1, cc2, cc3 = st.columns(3)
        do_checkout = cc1.button("Checkout", width="stretch")
        do_update = cc2.button("Update", width="stretch")
        do_info = cc3.button("Info", width="stretch")

        if do_checkout:
            if not repo_url:
                st.warning("SVN URL 필요")
            else:
                args: List[str] = [svn_bin, "checkout"]
                if revision.strip():
                    args += ["-r", revision.strip()]
                args += [repo_url.strip(), str(dest)]
                rc, out = _run_cmd(args, cwd=workdir, timeout_sec=int(timeout_sec))
                show_output(rc, out)

        if do_update:
            if not dest.exists():
                st.warning("대상 디렉터리 없음, 먼저 checkout 필요")
            else:
                rc, out = _run_cmd([svn_bin, "update"], cwd=dest, timeout_sec=int(timeout_sec))
                show_output(rc, out)

        if do_info:
            if not dest.exists():
                st.warning("대상 디렉터리 없음")
            else:
                rc, out = _run_cmd([svn_bin, "info"], cwd=dest, timeout_sec=int(timeout_sec))
                show_output(rc, out)

    st.divider()
    st.markdown("**최근 실행 로그**")
    st.code(st.session_state.get(log_key, "") or "(empty)", language="text")
