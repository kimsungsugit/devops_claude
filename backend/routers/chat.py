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

from backend.schemas import ApprovalResolutionRequest, ChatRequest, ChatJenkinsConfig, ChatResponse
from backend.services.chat_approval_store import get_pending_approval, mark_pending_approval_resolved, pop_pending_approval
from backend.services.assistant_service import answer_chat

router = APIRouter()
_logger = logging.getLogger("devops_api")

@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    jenkins = req.jenkins or ChatJenkinsConfig()
    result = answer_chat(
        mode=req.mode,
        question=req.question,
        report_dir=req.report_dir,
        session_id=req.session_id,
        llm_model=req.llm_model,
        oai_config_path=req.oai_config_path,
        ui_context=req.ui_context,
        history=[item.dict() for item in req.history],
        jenkins_job_url=jenkins.job_url or None,
        jenkins_cache_root=jenkins.cache_root or None,
        jenkins_build_selector=jenkins.build_selector or "lastSuccessfulBuild",
    )
    return ChatResponse(**result)


@router.post("/api/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    jenkins = req.jenkins or ChatJenkinsConfig()
    progress_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()

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
                history=[item.dict() for item in req.history],
                jenkins_job_url=jenkins.job_url or None,
                jenkins_cache_root=jenkins.cache_root or None,
                jenkins_build_selector=jenkins.build_selector or "lastSuccessfulBuild",
                progress_callback=progress_queue.put,
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
