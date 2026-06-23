"""Chat 어시스턴트 보안·회귀 테스트.

커버:
- R1  answer_chat: LLM config 부재 시 UnboundLocalError(500) 회귀 방지
- R2  소유권(IDOR): 타 사용자의 대화 read/title/delete/list 차단, 레거시(owner None) 허용
- R3  승인 record 에 owner 저장
- R5  승인 store TTL 만료
- R6  chat_history_db 경로 절대 anchor
- R7  ChatRequest/ChatJenkinsConfig 입력 검증
- R8  run_chat_graph cancel_check 협조 취소
- R13 CHAT_MAX_TURNS config 반영
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest

from backend.services.chat_history_db import init_db, reset_engine
from backend.services.chat_history_service import (
    delete_conversation,
    list_conversations,
    load_history,
    load_history_as_chat_items,
    save_message_pair,
    update_title,
)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path):
    reset_engine()
    init_db(tmp_path / "test_chat_security.sqlite")
    yield
    reset_engine()


def _save(thread_id: str, *, owner=None, question="q", answer="a") -> None:
    save_message_pair(
        thread_id=thread_id,
        session_id="s",
        mode="local",
        report_dir=None,
        question=question,
        answer=answer,
        owner=owner,
    )


# ── R2 소유권 (IDOR) ────────────────────────────────────────────────────

class TestOwnership:
    def test_load_rejects_other_owner(self):
        _save("t1", owner="alice")
        assert load_history("t1", requester="bob") is None
        assert load_history("t1", requester="alice") is not None

    def test_load_legacy_owner_none_allowed(self):
        _save("t2")  # owner 미지정 (레거시)
        assert load_history("t2", requester="bob") is not None

    def test_chat_items_rejects_other_owner(self):
        _save("t3", owner="alice")
        assert load_history_as_chat_items("t3", requester="bob") == []
        assert load_history_as_chat_items("t3", requester="alice") != []

    def test_delete_and_title_reject_other_owner(self):
        _save("t4", owner="alice")
        assert delete_conversation("t4", requester="bob") is False
        assert update_title("t4", "x", requester="bob") is False
        # 본인은 허용
        assert update_title("t4", "ok", requester="alice") is True
        assert delete_conversation("t4", requester="alice") is True

    def test_list_owner_filter_includes_legacy(self):
        _save("ta", owner="alice")
        _save("tb", owner="bob")
        _save("tc")  # legacy
        threads = {c["thread_id"] for c in list_conversations(owner="alice")["conversations"]}
        assert "ta" in threads
        assert "tb" not in threads
        assert "tc" in threads  # 레거시(owner None)는 함께 노출

    def test_list_message_count_no_n_plus_1(self):
        _save("tm", owner="alice")  # user+assistant 2개
        res = list_conversations(owner="alice")
        item = next(c for c in res["conversations"] if c["thread_id"] == "tm")
        assert item["message_count"] == 2


# ── R3/R5 승인 store ────────────────────────────────────────────────────

class TestApprovalStore:
    def test_owner_persisted(self):
        import backend.services.chat_approval_store as store
        store.save_pending_approval("a1", {"owner": "alice", "question": "deploy now"})
        rec = store.get_pending_approval("a1")
        assert rec is not None and rec["owner"] == "alice"
        store.pop_pending_approval("a1")

    def test_ttl_expiry(self, monkeypatch):
        import time

        import backend.services.chat_approval_store as store
        store.save_pending_approval("a2", {"owner": "alice"})
        assert store.get_pending_approval("a2") is not None
        monkeypatch.setattr(store, "_ttl_seconds", lambda: 0.0)
        time.sleep(0.01)
        assert store.get_pending_approval("a2") is None


# ── R6/R13 경로·config ──────────────────────────────────────────────────

class TestConfigAnchoring:
    def test_default_db_path_absolute(self):
        from backend.services.chat_history_db import _default_db_path
        p = _default_db_path()
        assert p.is_absolute()
        assert p.name == "chat_history.sqlite"

    def test_max_turns_uses_config(self, monkeypatch):
        import config
        from backend.services.chat_history_service import _max_turns
        monkeypatch.setattr(config, "CHAT_MAX_TURNS", 4, raising=False)
        assert _max_turns() == 4


# ── R7 입력 검증 ────────────────────────────────────────────────────────

class TestInputValidation:
    def test_question_max_length(self):
        import pydantic

        from backend.schemas import ChatRequest
        with pytest.raises(pydantic.ValidationError):
            ChatRequest(question="x" * 8001)
        assert ChatRequest(question="ok").question == "ok"

    def test_job_url_must_be_http(self):
        import pydantic

        from backend.schemas import ChatJenkinsConfig
        with pytest.raises(pydantic.ValidationError):
            ChatJenkinsConfig(job_url="ftp://evil/x")
        assert ChatJenkinsConfig(job_url="https://ci/job/x").job_url == "https://ci/job/x"
        assert ChatJenkinsConfig(job_url="").job_url == ""

    def test_title_max_length(self):
        import pydantic

        from backend.schemas import ChatTitleUpdateRequest
        with pytest.raises(pydantic.ValidationError):
            ChatTitleUpdateRequest(title="t" * 501)


# ── R8 그래프 협조 취소 ──────────────────────────────────────────────────

class TestGraphCancel:
    def test_cancel_before_first_node(self):
        from workflow.chat_graph import new_chat_graph_state, run_chat_graph
        state = new_chat_graph_state(
            mode="local", question="q", session_id=None, report_dir=None, ui_context=None, history=None,
        )
        calls = []
        nodes = [("n1", lambda s: calls.append("n1") or {}), ("n2", lambda s: calls.append("n2") or {})]
        run_chat_graph(initial_state=state, nodes=nodes, cancel_check=lambda: True)
        assert calls == []

    def test_cancel_midway(self):
        from workflow.chat_graph import new_chat_graph_state, run_chat_graph
        state = new_chat_graph_state(
            mode="local", question="q", session_id=None, report_dir=None, ui_context=None, history=None,
        )
        calls = []
        counter = {"n": 0}

        def cancel():
            counter["n"] += 1
            return counter["n"] > 1  # 첫 체크는 통과, 둘째부터 취소

        nodes = [
            ("n1", lambda s: calls.append("n1") or {}),
            ("n2", lambda s: calls.append("n2") or {}),
            ("n3", lambda s: calls.append("n3") or {}),
        ]
        run_chat_graph(initial_state=state, nodes=nodes, cancel_check=cancel)
        assert "n1" in calls
        assert "n2" not in calls and "n3" not in calls


# ── R1 회귀: LLM config 부재 시 500(UnboundLocalError) 방지 ───────────────

class TestAnswerChatRegression:
    def test_missing_llm_config_no_unbound_error(self, monkeypatch):
        import backend.services.assistant_service as asvc

        # 컨텍스트 빌드/LLM config 로딩을 가볍게 대체 → select_model 이 missing_llm_config 유발
        monkeypatch.setattr(asvc, "_build_context", lambda **kw: ("", [], []))
        monkeypatch.setattr(asvc, "load_oai_config", lambda *a, **k: {})
        monkeypatch.setattr(asvc, "load_oai_configs", lambda *a, **k: [])

        res = asvc.answer_chat(
            mode="local",
            question="현재 상태 알려줘",
            report_dir=None,
            session_id=None,
            llm_model=None,
            oai_config_path=None,
            ui_context=None,
            history=None,
        )
        # fix 이전에는 evidence UnboundLocalError 로 500 → 이제 정상 dict 반환
        assert res["ok"] is False
        assert isinstance(res["evidence"], list)
        assert "LLM" in res["answer"]


# ── C1/C2 승인 resolve: TOCTOU / double-fire (HTTP 레벨) ───────────────────

class TestApprovalResolve:
    @staticmethod
    def _req(approval_id, decision="approve"):
        from backend.schemas import ApprovalResolutionRequest
        return ApprovalResolutionRequest(approval_id=approval_id, decision=decision)

    def test_403_other_owner_no_store_mutation(self, monkeypatch):
        from fastapi import HTTPException

        import backend.routers.chat as chatmod
        import backend.services.chat_approval_store as store
        store.save_pending_approval("ap1", {"owner": "alice", "mode": "local", "question": "deploy"})
        monkeypatch.setattr(chatmod, "get_current_user", lambda: "bob")
        with pytest.raises(HTTPException) as ei:
            chatmod.chat_approval_resolve(self._req("ap1"))
        assert ei.value.status_code == 403
        # C1: 403 이어도 store 가 소비/오염되지 않아야 함
        rec = store.get_pending_approval("ap1")
        assert rec is not None and "decision" not in rec
        store.pop_pending_approval("ap1")

    def test_double_fire_blocked(self, monkeypatch):
        from fastapi import HTTPException

        import backend.routers.chat as chatmod
        import backend.services.chat_approval_store as store
        store.save_pending_approval("ap2", {"owner": "alice", "mode": "local", "question": "hi"})
        monkeypatch.setattr(chatmod, "get_current_user", lambda: "alice")
        calls = []

        def _fake_answer(**kw):
            calls.append(1)
            return {
                "ok": True, "request_id": "r", "thread_id": "t", "answer": "a",
                "sources": [], "citations": [], "evidence": [], "next_steps": [],
                "structured": {"answer": "a", "evidence": [], "next_steps": []},
                "approval_required": False, "approval_request": None,
            }

        monkeypatch.setattr(chatmod, "answer_chat", _fake_answer)
        r1 = chatmod.chat_approval_resolve(self._req("ap2"))
        assert r1.ok is True and len(calls) == 1
        # C2: 두 번째 동일 승인은 이미 소비되어 거부, answer_chat 재실행 없음
        with pytest.raises(HTTPException) as ei:
            chatmod.chat_approval_resolve(self._req("ap2"))
        assert ei.value.status_code in (404, 409)
        assert len(calls) == 1  # double-fire 방지

    def test_409_on_concurrent_pop(self, monkeypatch):
        from fastapi import HTTPException

        import backend.routers.chat as chatmod
        import backend.services.chat_approval_store as store
        store.save_pending_approval("ap4", {"owner": "alice", "mode": "local", "question": "hi"})
        monkeypatch.setattr(chatmod, "get_current_user", lambda: "alice")
        # 검증 통과 후 pop 시점에 다른 요청이 이미 소비한 상황 → 409
        monkeypatch.setattr(chatmod, "pop_pending_approval", lambda aid: None)
        with pytest.raises(HTTPException) as ei:
            chatmod.chat_approval_resolve(self._req("ap4"))
        assert ei.value.status_code == 409
        store.pop_pending_approval("ap4")

    def test_reject_owner_consumes(self, monkeypatch):
        import backend.routers.chat as chatmod
        import backend.services.chat_approval_store as store
        store.save_pending_approval("ap3", {"owner": "alice", "request_id": "rq", "thread_id": "th"})
        monkeypatch.setattr(chatmod, "get_current_user", lambda: "alice")
        r = chatmod.chat_approval_resolve(self._req("ap3", decision="reject"))
        assert r.ok is True
        assert store.get_pending_approval("ap3") is None


# ── D3 그래프 노드 예외 흡수 / D1 seq UNIQUE ──────────────────────────────

class TestRobustness:
    def test_node_exception_absorbed(self):
        # D3: 노드가 raise 해도 전체 500 대신 errors 로 흡수
        from workflow.chat_graph import new_chat_graph_state, run_chat_graph

        state = new_chat_graph_state(
            mode="local", question="q", session_id=None, report_dir=None, ui_context=None, history=None,
        )

        def boom(_s):
            raise RuntimeError("node fail")

        res = run_chat_graph(initial_state=state, nodes=[("boom", boom)])
        assert res.errors
        assert any(e.get("code") == "node_error" for e in res.errors)

    def test_seq_unique_constraint(self):
        # D1: (conversation_id, seq) UNIQUE — 동일 seq 중복 INSERT 차단
        import uuid as _uuid

        from sqlalchemy.exc import IntegrityError

        from backend.services.chat_history_db import get_session
        from backend.services.chat_history_models import ChatConversation, ChatMessage

        with get_session() as s:
            conv = ChatConversation(thread_id=str(_uuid.uuid4()))
            s.add(conv)
            s.flush()
            cid = conv.id
        with pytest.raises(IntegrityError):
            with get_session() as s:
                s.add(ChatMessage(conversation_id=cid, seq=1, role="user", text="a"))
                s.add(ChatMessage(conversation_id=cid, seq=1, role="user", text="b"))
