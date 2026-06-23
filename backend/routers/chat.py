"""Auto-generated router: chat"""
import asyncio
import json
import logging
import queue
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

import config
from backend.schemas import (
    ApprovalResolutionRequest,
    ChatConversationListResponse,
    ChatHistoryResponse,
    ChatJenkinsConfig,
    ChatRequest,
    ChatResponse,
    ChatTitleUpdateRequest,
)
from backend.services.assistant_service import answer_chat
from backend.services.chat_approval_store import (
    get_pending_approval,
    pop_pending_approval,
)
from backend.user_context import get_current_user

router = APIRouter()


def _max_turns() -> int:
    return int(getattr(config, "CHAT_MAX_TURNS", 16) or 16)
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
    owner: Optional[str] = None,
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
            owner=owner,
        )
    except Exception:
        # fire-and-forget 이라 사용자에게 전파되지 않음 → error 로 남겨 누락을 추적 가능하게.
        _logger.error("chat history save failed (thread_id=%s)", thread_id, exc_info=True)


def _load_server_history(thread_id: Optional[str], requester: Optional[str] = None) -> List[Dict[str, str]]:
    """thread_id가 있으면 서버에서 이전 대화 이력 로드 (소유자 검증 포함)."""
    if not thread_id:
        return []
    try:
        from backend.services.chat_history_service import load_history_as_chat_items
        return load_history_as_chat_items(thread_id, requester=requester)
    except Exception:
        _logger.warning("chat history load failed", exc_info=True)
        return []


def _merge_history(
    client_history: List[Dict[str, str]],
    server_history: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """서버 이력 + 클라이언트 이력 병합 (중복 제거, 최대 16개)."""
    max_turns = _max_turns()
    if not server_history:
        return client_history
    if not client_history:
        return server_history[-max_turns:]

    # 서버 이력 뒤에 클라이언트 이력 추가 (클라이언트 우선)
    merged = list(server_history)
    server_texts = {(m.get("role"), m.get("text")) for m in server_history}
    for item in client_history:
        key = (item.get("role"), item.get("text"))
        if key not in server_texts:
            merged.append(item)
    return merged[-max_turns:]


@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    jenkins = req.jenkins or ChatJenkinsConfig()
    requester = get_current_user()

    # 서버 이력 로드 + 클라이언트 이력 병합
    server_history = _load_server_history(req.thread_id, requester=requester)
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
        requester=requester,
    )

    # 자동 저장 (owner=requester 는 호출 스레드에서 캡처 — 백그라운드 스레드는 ContextVar 미상속)
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
                requester,
            ),
            daemon=True,
        ).start()

    return ChatResponse(**result)


@router.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    jenkins = req.jenkins or ChatJenkinsConfig()
    requester = get_current_user()
    progress_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
    cancel_event = threading.Event()

    server_history = _load_server_history(req.thread_id, requester=requester)
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
                requester=requester,
                cancel_check=cancel_event.is_set,
            )

            # 자동 저장 (W6: 별도 스레드 — WAL lock 시 done 신호 지연 방지; 취소 시 저장 생략)
            if req.save_history and result.get("ok") and not cancel_event.is_set():
                thread_id = req.thread_id or result.get("thread_id", "")
                threading.Thread(
                    target=_save_history_bg,
                    kwargs={
                        "thread_id": thread_id,
                        "session_id": req.session_id,
                        "mode": req.mode,
                        "report_dir": req.report_dir,
                        "question": req.question,
                        "answer": result.get("answer", ""),
                        "request_id": result.get("request_id", ""),
                        "llm_model": req.llm_model or "",
                        "owner": requester,
                    },
                    daemon=True,
                ).start()

            progress_queue.put({"type": "message", **result})
            progress_queue.put({"type": "done"})
        except Exception:
            # D7: 내부 예외 원문(SQL/스키마)을 클라이언트로 노출하지 않음
            _logger.exception("chat stream failed")
            progress_queue.put({"type": "error", "detail": "internal error"})

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()

    async def _event_stream():
        yield f"data: {json.dumps({'type': 'started'}, ensure_ascii=False)}\n\n"
        idle = 0
        try:
            while True:
                # 클라이언트 조기 종료 감지 → worker 협조 취소 (다음 그래프 노드 경계에서 멈춤)
                if await request.is_disconnected():
                    cancel_event.set()
                    break
                try:
                    item = progress_queue.get_nowait()
                except queue.Empty:
                    idle += 1
                    if idle >= 75:  # 약 15초(0.2s * 75)마다 keepalive
                        idle = 0
                        yield "data: {\"type\":\"keepalive\"}\n\n"
                    await asyncio.sleep(0.2)
                    continue
                idle = 0
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item.get("type") in ("done", "error"):
                    break
        finally:
            # 정상/비정상 종료 모두에서 worker 가 다음 노드 경계에서 멈추도록 신호
            cancel_event.set()

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
        **list_conversations(session_id=session_id, limit=limit, offset=offset, owner=get_current_user())
    )


@router.get("/api/chat/history/{thread_id}", response_model=ChatHistoryResponse)
def chat_history_get(
    thread_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """특정 대화의 메시지 이력 조회."""
    from backend.services.chat_history_service import load_history
    data = load_history(thread_id, limit=limit, offset=offset, requester=get_current_user())
    if data is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return ChatHistoryResponse(**data)


@router.patch("/api/chat/history/{thread_id}/title")
def chat_history_update_title(thread_id: str, req: ChatTitleUpdateRequest):
    """대화 제목 변경."""
    from backend.services.chat_history_service import update_title
    if not update_title(thread_id, req.title, requester=get_current_user()):
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"ok": True}


@router.delete("/api/chat/history/{thread_id}")
def chat_history_delete(thread_id: str):
    """대화 삭제."""
    from backend.services.chat_history_service import delete_conversation
    if not delete_conversation(thread_id, requester=get_current_user()):
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"ok": True}


# ── Approval endpoints ───────────────────────────────────────────────

@router.get("/api/chat/approval/{approval_id}")
def chat_approval_get(approval_id: str) -> Dict[str, Any]:
    record = get_pending_approval(approval_id)
    if not record:
        raise HTTPException(status_code=404, detail="approval request not found")
    # W1: 타인의 승인 레코드(질문/job_url/session 등) 열람 차단
    requester = get_current_user()
    owner = record.get("owner")
    if owner and requester and owner != requester:
        raise HTTPException(status_code=403, detail="not authorized")
    return record


@router.post("/api/chat/approval/resolve", response_model=ChatResponse)
def chat_approval_resolve(req: ApprovalResolutionRequest) -> ChatResponse:
    # C1: 권한검증을 store 뮤테이션보다 먼저 (TOCTOU/감사로그 오염 방지)
    record = get_pending_approval(req.approval_id)
    if not record:
        raise HTTPException(status_code=404, detail="approval request not found")

    # R3: 승인/거절 권한 — 위험 작업을 요청한 본인만 (owner 기록이 있으면 일치 요구)
    requester = get_current_user()
    owner = record.get("owner")
    if owner and requester and owner != requester:
        raise HTTPException(status_code=403, detail="not authorized to resolve this approval")

    decision = str(req.decision or "").strip().lower()
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be approve or reject")

    # C2: 단일 소비 보장 (double-fire 방지) — pop 이 None 이면 이미 처리됨
    pending = pop_pending_approval(req.approval_id)
    if pending is None:
        raise HTTPException(status_code=409, detail="approval already processed")
    pending["decision"] = decision
    pending["comment"] = str(req.comment or "")

    if decision == "reject":
        answer = "승인 요청이 거절되어 작업을 중단했습니다."
        payload = {
            "ok": True,
            "request_id": str(pending.get("request_id") or ""),
            "thread_id": str(pending.get("thread_id") or ""),
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
        requester=requester,
    )
    return ChatResponse(**result)
