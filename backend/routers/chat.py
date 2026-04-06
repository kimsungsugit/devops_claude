"""Auto-generated router: chat"""
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from typing import Any, Dict, List, Optional
import json
import traceback
import logging
import queue
import threading
from pathlib import Path

from backend.schemas import (
    ApprovalResolutionRequest,
    ChatConversationListResponse,
    ChatHistoryResponse,
    ChatJenkinsConfig,
    ChatRequest,
    ChatResponse,
    ChatTitleUpdateRequest,
)
from backend.services.chat_approval_store import get_pending_approval, mark_pending_approval_resolved, pop_pending_approval
from backend.services.assistant_service import answer_chat

router = APIRouter()
_logger = logging.getLogger("devops_api")


def _save_history_bg(
    thread_id: str,
    session_id: Optional[str],
    mode: str,
    report_dir: Optional[str],
    question: str,
    answer: str,
    request_id: str = "",
    llm_model: str = "",
) -> None:
    """백그라운드로 대화 이력 저장 (응답 지연 방지)."""
    try:
        from backend.services.chat_history_service import save_message_pair
        save_message_pair(
            thread_id=thread_id,
            session_id=session_id,
            mode=mode,
            report_dir=report_dir,
            question=question,
            answer=answer,
            request_id=request_id,
            llm_model=llm_model,
        )
    except Exception:
        _logger.warning("chat history save failed", exc_info=True)


def _load_server_history(thread_id: Optional[str]) -> List[Dict[str, str]]:
    """thread_id가 있으면 서버에서 이전 대화 이력 로드."""
    if not thread_id:
        return []
    try:
        from backend.services.chat_history_service import load_history_as_chat_items
        return load_history_as_chat_items(thread_id, last_n=16)
    except Exception:
        _logger.warning("chat history load failed", exc_info=True)
        return []


def _merge_history(
    client_history: List[Dict[str, str]],
    server_history: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """서버 이력 + 클라이언트 이력 병합 (중복 제거, 최대 16개)."""
    if not server_history:
        return client_history
    if not client_history:
        return server_history[-16:]

    # 서버 이력 뒤에 클라이언트 이력 추가 (클라이언트 우선)
    merged = list(server_history)
    server_texts = {(m.get("role"), m.get("text")) for m in server_history}
    for item in client_history:
        key = (item.get("role"), item.get("text"))
        if key not in server_texts:
            merged.append(item)
    return merged[-16:]


@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    jenkins = req.jenkins or ChatJenkinsConfig()

    # 서버 이력 로드 + 클라이언트 이력 병합
    server_history = _load_server_history(req.thread_id)
    client_history = [item.dict() for item in req.history]
    merged = _merge_history(client_history, server_history)

    result = answer_chat(
        mode=req.mode,
        question=req.question,
        report_dir=req.report_dir,
        session_id=req.session_id,
        llm_model=req.llm_model,
        oai_config_path=req.oai_config_path,
        ui_context=req.ui_context,
        history=merged,
        jenkins_job_url=jenkins.job_url or None,
        jenkins_cache_root=jenkins.cache_root or None,
        jenkins_build_selector=jenkins.build_selector or "lastSuccessfulBuild",
    )

    # 자동 저장
    if req.save_history and result.get("ok"):
        thread_id = req.thread_id or result.get("thread_id", "")
        threading.Thread(
            target=_save_history_bg,
            args=(
                thread_id,
                req.session_id,
                req.mode,
                req.report_dir,
                req.question,
                result.get("answer", ""),
                result.get("request_id", ""),
                req.llm_model or "",
            ),
            daemon=True,
        ).start()

    return ChatResponse(**result)


@router.post("/api/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    jenkins = req.jenkins or ChatJenkinsConfig()
    progress_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()

    server_history = _load_server_history(req.thread_id)
    client_history = [item.dict() for item in req.history]
    merged = _merge_history(client_history, server_history)

    def _run() -> None:
        try:
            result = answer_chat(
                mode=req.mode,
                question=req.question,
                report_dir=req.report_dir,
                session_id=req.session_id,
                llm_model=req.llm_model,
                oai_config_path=req.oai_config_path,
                ui_context=req.ui_context,
                history=merged,
                jenkins_job_url=jenkins.job_url or None,
                jenkins_cache_root=jenkins.cache_root or None,
                jenkins_build_selector=jenkins.build_selector or "lastSuccessfulBuild",
                progress_callback=progress_queue.put,
            )

            # 자동 저장
            if req.save_history and result.get("ok"):
                thread_id = req.thread_id or result.get("thread_id", "")
                _save_history_bg(
                    thread_id=thread_id,
                    session_id=req.session_id,
                    mode=req.mode,
                    report_dir=req.report_dir,
                    question=req.question,
                    answer=result.get("answer", ""),
                    request_id=result.get("request_id", ""),
                    llm_model=req.llm_model or "",
                )

            progress_queue.put({"type": "message", **result})
            progress_queue.put({"type": "done"})
        except Exception as e:
            _logger.exception("chat stream failed")
            progress_queue.put({"type": "error", "detail": str(e)})

    threading.Thread(target=_run, daemon=True).start()

    def _event_stream():
        yield f"data: {json.dumps({'type': 'started'}, ensure_ascii=False)}\n\n"
        while True:
            try:
                item = progress_queue.get(timeout=15)
            except queue.Empty:
                yield "data: {\"type\":\"keepalive\"}\n\n"
                continue
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            if item.get("type") in ("done", "error"):
                break

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


# ── History endpoints ────────────────────────────────────────────────

@router.get("/api/chat/history", response_model=ChatConversationListResponse)
def chat_history_list(
    session_id: Optional[str] = Query(None),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """대화 목록 조회."""
    from backend.services.chat_history_service import list_conversations
    return ChatConversationListResponse(
        **list_conversations(session_id=session_id, limit=limit, offset=offset)
    )


@router.get("/api/chat/history/{thread_id}", response_model=ChatHistoryResponse)
def chat_history_get(
    thread_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """특정 대화의 메시지 이력 조회."""
    from backend.services.chat_history_service import load_history
    data = load_history(thread_id, limit=limit, offset=offset)
    if data is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return ChatHistoryResponse(**data)


@router.patch("/api/chat/history/{thread_id}/title")
def chat_history_update_title(thread_id: str, req: ChatTitleUpdateRequest):
    """대화 제목 변경."""
    from backend.services.chat_history_service import update_title
    if not update_title(thread_id, req.title):
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"ok": True}


@router.delete("/api/chat/history/{thread_id}")
def chat_history_delete(thread_id: str):
    """대화 삭제."""
    from backend.services.chat_history_service import delete_conversation
    if not delete_conversation(thread_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"ok": True}


# ── Approval endpoints ───────────────────────────────────────────────

@router.get("/api/chat/approval/{approval_id}")
def chat_approval_get(approval_id: str) -> Dict[str, Any]:
    record = get_pending_approval(approval_id)
    if not record:
        raise HTTPException(status_code=404, detail="approval request not found")
    return record


@router.post("/api/chat/approval/resolve", response_model=ChatResponse)
def chat_approval_resolve(req: ApprovalResolutionRequest) -> ChatResponse:
    record = mark_pending_approval_resolved(req.approval_id, req.decision, req.comment)
    if not record:
        raise HTTPException(status_code=404, detail="approval request not found")

    decision = str(req.decision or "").strip().lower()
    if decision == "reject":
        popped = pop_pending_approval(req.approval_id) or record
        answer = "승인 요청이 거절되어 작업을 중단했습니다."
        payload = {
            "ok": True,
            "request_id": str(popped.get("request_id") or ""),
            "thread_id": str(popped.get("thread_id") or ""),
            "answer": answer,
            "sources": [],
            "citations": [],
            "evidence": [],
            "next_steps": ["필요하면 더 안전한 읽기 전용 작업으로 다시 요청합니다."],
            "structured": {
                "answer": answer,
                "evidence": [],
                "next_steps": ["필요하면 더 안전한 읽기 전용 작업으로 다시 요청합니다."],
            },
            "approval_required": False,
            "approval_request": None,
        }
        return ChatResponse(**payload)

    if decision != "approve":
        raise HTTPException(status_code=400, detail="decision must be approve or reject")

    pending = pop_pending_approval(req.approval_id) or record
    ui_context = dict(pending.get("ui_context") or {})
    approved_ids = list(ui_context.get("approved_approval_ids") or [])
    approved_ids.append(req.approval_id)
    ui_context["approved_approval_ids"] = approved_ids
    if pending.get("approval_request"):
        ui_context["approval_request"] = dict(pending.get("approval_request") or {})

    result = answer_chat(
        mode=str(pending.get("mode") or "local"),
        question=str(pending.get("question") or ""),
        report_dir=pending.get("report_dir"),
        session_id=pending.get("session_id"),
        llm_model=pending.get("llm_model"),
        oai_config_path=pending.get("oai_config_path"),
        ui_context=ui_context,
        history=list(pending.get("history") or []),
        jenkins_job_url=pending.get("jenkins_job_url"),
        jenkins_cache_root=pending.get("jenkins_cache_root"),
        jenkins_build_selector=pending.get("jenkins_build_selector"),
    )
    return ChatResponse(**result)
