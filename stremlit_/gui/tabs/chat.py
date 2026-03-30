# /app/gui/tabs/chat.py
# -*- coding: utf-8 -*-
# Context-Aware DevOps Chat Interface (v30.7: Fix config list type error)

import streamlit as st
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, Any, Dict, List
import workflow.ai as ai_core

def load_context(root, report_dir, mode: str = "local", build_info: Optional[dict] = None, artifacts: Optional[list] = None, selected_issue: Optional[dict] = None):
    """
    현재 프로젝트의 분석 상태와 최신 로그를 로드하여 
    LLM에게 주입할 시스템 프롬프트 컨텍스트를 생성합니다.
    """
    summary_path = Path(root) / report_dir / "analysis_summary.json"
    log_path = Path(root) / report_dir / "system.log"
    
    context = "[Current System Status]\n"
    
    # 1. 분석 요약 로드 (성공/실패 여부, 이슈 개수)
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            context += f"- Last Exit Code: {summary.get('exit_code')}\n"
            context += f"- Failure Stage: {summary.get('failure_stage')}\n"
            
            # 정적 분석 이슈 개수 파악
            static_info = summary.get('static', {})
            cpp_counts = static_info.get('cppcheck', {}).get('issue_counts', {})
            
            # 구버전 호환 (cppcheck -> issues 리스트 직접 접근)
            if not cpp_counts:
                cpp_issues_list = static_info.get('cppcheck', {}).get('issues', [])
                cpp_count = len(cpp_issues_list)
            else:
                cpp_count = cpp_counts.get('total', 0)
                
            context += f"- Static Analysis Issues: {cpp_count}\n"
            
            # 동적 분석 상태
            if summary.get('build', {}).get('ok'):
                context += "- Build: SUCCESS\n"
            else:
                context += "- Build: FAILED\n"
                
        except Exception as e:
            context += f"- Analysis Summary: Error loading summary ({e})\n"
    else:
        context += "- Analysis Summary: Not available yet (Run analysis first).\n"
    
    # 2. 최근 시스템 로그 (마지막 30줄)
    if log_path.exists():
        try:
            # 로그 파일의 끝부분만 읽어서 컨텍스트에 추가
            logs = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-30:]
            context += "\n[Recent System Logs (Last 30 lines)]\n" + "\n".join(logs)
        except Exception as e:
            context += f"\n[System Log Error]: {e}"
        
    # 3. Jenkins Viewer 보조 컨텍스트 (존재 시)
    if str(mode or "").lower().startswith("jen"):
        try:
            jscan_path = Path(root) / report_dir / "jenkins_scan.json"
            if jscan_path.exists():
                jscan = json.loads(jscan_path.read_text(encoding="utf-8", errors="ignore"))
                summ = (jscan or {}).get("summary", {}) or {}
                context += "\n[Jenkins Artifact Scan]\n"
                context += f"- Files Total: {summ.get('files_total')}\n"
                context += f"- Bytes Total: {summ.get('bytes_total')}\n"
                kpi = (jscan or {}).get("kpi", {}) or {}
                if isinstance(kpi, dict) and kpi:
                    top_k = sorted(kpi.items(), key=lambda x: int(x[1] or 0), reverse=True)[:12]
                    context += "- KPI Tokens: " + ", ".join([f"{k}={v}" for k, v in top_k]) + "\n"
            # QAC/PRQA 룰 요약 캐시(있으면)
            qac_path = Path(root) / report_dir / "qac_rcr_summary.json"
            if qac_path.exists():
                qsum = json.loads(qac_path.read_text(encoding="utf-8", errors="ignore"))
                totals = (qsum or {}).get("importance_totals", {}) or {}
                context += "\n[QAC Rule Violations]\n"
                context += f"- Total Diagnostics: {qsum.get('diagnostic_count')}\n"
                if isinstance(totals, dict) and totals:
                    context += "- By Importance: " + ", ".join([f"{k}={v}" for k, v in totals.items()]) + "\n"
        except Exception as e:
            context += f"\n- Jenkins Context: Error loading ({e})\n"

    # 4. 빌드/아티팩트/선택 이슈 컨텍스트
    try:
        if build_info:
            context += "\n[Build Info]\n"
            for k in ["job_url", "job_name", "number", "result", "timestamp", "url"]:
                if k in build_info:
                    context += f"- {k}: {build_info.get(k)}\n"
        if artifacts:
            context += "\n[Artifacts]\n"
            context += f"- count: {len(artifacts)}\n"
            for a in artifacts[:20]:
                if isinstance(a, dict):
                    name = a.get("file") or a.get("path") or a.get("name") or str(a)
                else:
                    name = str(a)
                context += f"  - {name}\n"
        if selected_issue:
            context += "\n[Selected Issue]\n"
            for k in ["tool", "severity", "rule", "file", "line", "message"]:
                if k in selected_issue:
                    context += f"- {k}: {selected_issue.get(k)}\n"
    except Exception as e:
        context += f"\n[Context Error]: {e}\n"

    return context

def _build_system_prompt(sys_context: str) -> str:
    # 시스템 메시지는 대화 내내 유지되므로, 컨텍스트만 교체 가능한 형태로 구성
    return f"""
You are an Embedded DevOps Assistant.
Your goal is to help the user fix build errors, code issues, or explain analysis results.

{sys_context}

[IMPORTANT INSTRUCTIONS]
1. The user writes in Korean. Your final response MUST be in Korean.
2. Do NOT answer with generic engineering advice. Use only the provided context.
3. If context is insufficient, ask for a specific file path or ask the user to select a file/issue in the editor.
4. Be concise and propose concrete next actions or code-level hypotheses.
""".strip()



def render_chat(project_root, report_dir, oai_config_path, mode: str = "local", build_info: Optional[dict] = None, artifacts: Optional[list] = None):
    st.markdown("### 💬 DevOps AI 채팅")
    st.caption("현재 분석 결과/리포트(로컬 분석 또는 Jenkins 아티팩트)를 기반으로 AI가 답변합니다.")

    # 1. 세션 초기화 및 컨텍스트 로드
    if "messages" not in st.session_state:
        st.session_state.messages = []

    selected_issue = st.session_state.get("editor_selected_row") if isinstance(st.session_state.get("editor_selected_row"), dict) else None
    sys_context = load_context(project_root, report_dir, mode=mode, build_info=build_info, artifacts=artifacts, selected_issue=selected_issue)
    sys_prompt = _build_system_prompt(sys_context)

    # 컨텍스트 해시 기반 자동 갱신 (대화 유지)
    ctx_hash = hashlib.sha1(sys_context.encode("utf-8", errors="ignore")).hexdigest()
    prev_hash = st.session_state.get("chat_context_hash")
    if prev_hash != ctx_hash:
        st.session_state["chat_context_hash"] = ctx_hash
        st.session_state["chat_context_last_updated"] = datetime.now().isoformat(timespec="seconds")

        # system message 교체 또는 삽입
        sys_idx = None
        for i, msg in enumerate(st.session_state.messages):
            if msg.get("role") == "system":
                sys_idx = i
                break
        if sys_idx is None:
            st.session_state.messages.insert(0, {"role": "system", "content": sys_prompt})
        else:
            st.session_state.messages[sys_idx]["content"] = sys_prompt

    # 첫 실행 시 인사
    if len(st.session_state.messages) <= 1:
        # system 메시지 외 첫 assistant 메시지
        if not any(m.get("role") == "assistant" for m in st.session_state.messages):
            st.session_state.messages.append({"role": "assistant", "content": "안녕하세요! 로그를 분석해 드릴까요? (한국어로 편하게 질문해주세요.)"})

    # 2. 채팅 UI 렌더링 (대화 기록 표시) (대화 기록 표시)
    chat_container = st.container()
    with chat_container:
        for msg in st.session_state.messages:
            if msg["role"] != "system":
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

    # 3. 입력 UI (Enter + 전송 버튼)
    if "chat_input_widget" not in st.session_state:
        st.session_state.chat_input_widget = ""

    # Editor -> Chat prefill
    draft = st.session_state.pop("chat_draft", None)
    if draft and not st.session_state.chat_input_widget:
        st.session_state.chat_input_widget = str(draft)

    st.markdown("---")
    with st.form("chat_form", clear_on_submit=True):
        user_text = st.text_input(
            "질문 입력",
            placeholder="예: 빌드 에러 원인이 뭐야?",
            key="chat_input_widget",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("전송")

    if submitted and user_text.strip():
        st.session_state.messages.append({"role": "user", "content": user_text.strip()})

    # 4. AI 응답 트리거 로직
    # (handle_input에 의해 메시지가 추가된 직후 실행됨)
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        
        with chat_container:
            # 사용자 메시지가 방금 추가되었으므로 바로 AI 응답 생성 시작
            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                
                # LLM 설정 로드
                cfg = ai_core.load_oai_config(oai_config_path)
                
                response = None
                if not cfg:
                    st.error("설정 파일을 찾을 수 없습니다.")
                else:
                    if isinstance(cfg, list):
                        cfg = cfg[0]
                    
                    with st.spinner("AI가 로그를 분석하고 있습니다..."):
                        # 사용자 메시지가 이미 messages에 들어갔으므로 그대로 전달
                        response = ai_core.agent_call_text(
                            cfg,
                            st.session_state.messages,
                            role="assistant",
                            stage="chat",
                        )
                
                if response:
                    message_placeholder.markdown(response)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                else:
                    if cfg: # 설정 파일 에러가 아닐 때만 출력
                        err_msg = "AI 응답을 받아오지 못했습니다. Ollama/LLM 서버 연결을 확인해주세요."
                        message_placeholder.error(err_msg)
                        st.session_state.messages.append({"role": "assistant", "content": err_msg})
        
        # AI 응답이 완료되면 화면 갱신 (마지막 메시지 표시 보장)
        st.rerun()

    # 5. 유틸리티 버튼
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("🔄 로그 새로고침"):
            if "messages" in st.session_state:
                del st.session_state.messages
            st.rerun()
    with col2:
        st.caption("분석을 새로 돌린 후에는 반드시 새로고침을 눌러 최신 로그를 반영해주세요.")
