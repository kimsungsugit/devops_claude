# tests/unit/test_chat_graph.py
# -*- coding: utf-8 -*-
"""
workflow/chat_graph.py 단위 테스트
- ChatGraphState 생성 및 필드 검증
- new_chat_graph_state 팩토리 함수
- emit_graph_event 이벤트 콜백 구조 검증
- run_chat_graph 노드 순차 실행 (LangGraph 없는 폴백 경로)
- LANGGRAPH_AVAILABLE=False 시 순수 Python fallback 동작

요구사항 추적: SRS-GRAPH-001 (대화 그래프 상태 관리), SRS-GRAPH-002 (노드 순차 실행)
"""
from __future__ import annotations

import sys
import types
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# workflow.__init__ 실행 방지 및 외부 의존성 stub 처리
# ---------------------------------------------------------------------------

def _ensure_stubs() -> None:
    """workflow 패키지를 빈 ModuleType으로 등록해 __init__ 실행을 방지한다."""
    sys.modules.setdefault("analysis_tools", MagicMock())
    sys.modules.setdefault("utils", MagicMock())
    sys.modules.setdefault(
        "utils.log",
        MagicMock(get_logger=MagicMock(return_value=MagicMock())),
    )

    if not isinstance(sys.modules.get("workflow"), types.ModuleType) or \
            getattr(sys.modules.get("workflow"), "__path__", None) is None:
        _wf = types.ModuleType("workflow")
        _wf.__path__ = [str(Path(__file__).resolve().parents[2] / "workflow")]  # type: ignore[assignment]
        _wf.__package__ = "workflow"
        sys.modules["workflow"] = _wf


_ensure_stubs()


# ---------------------------------------------------------------------------
# 기본 임포트 (langgraph 존재 여부와 무관하게 모듈 자체는 임포트 가능)
# ---------------------------------------------------------------------------
try:
    import workflow.chat_graph as chat_graph_mod
except ImportError:
    chat_graph_mod = None  # type: ignore


# ---------------------------------------------------------------------------
# ChatGraphState 생성 및 필드
# ---------------------------------------------------------------------------

@pytest.mark.skipif(chat_graph_mod is None, reason="workflow.chat_graph 임포트 불가")
class TestChatGraphState:
    """SRS-GRAPH-001: ChatGraphState 데이터클래스 필드 및 기본값 검증."""

    def test_필수_필드로_객체가_생성된다(self):
        """Arrange: 최소 필수 필드만 제공
        Act: ChatGraphState 직접 생성
        Assert: 필드가 올바르게 설정된다
        """
        # Arrange & Act
        state = chat_graph_mod.ChatGraphState(
            request_id="req-001",
            thread_id="thread-001",
            mode="chat",
            question="테스트 질문입니다",
        )

        # Assert
        assert state.request_id == "req-001"
        assert state.thread_id == "thread-001"
        assert state.mode == "chat"
        assert state.question == "테스트 질문입니다"

    def test_기본_필드가_올바른_타입으로_초기화된다(self):
        """Arrange: 선택 필드 지정 없이 생성
        Act: ChatGraphState 생성
        Assert: list/dict 기본값이 빈 컨테이너로 초기화된다
        """
        # Arrange & Act
        state = chat_graph_mod.ChatGraphState(
            request_id="r",
            thread_id="t",
            mode="chat",
            question="q",
        )

        # Assert: 가변 기본값이 공유되지 않는다 (dataclass field 사용 확인)
        assert isinstance(state.history, list)
        assert isinstance(state.errors, list)
        assert isinstance(state.metrics, dict)
        assert isinstance(state.extra, dict)
        assert len(state.history) == 0

    def test_answer_기본값은_빈_문자열이다(self):
        # Arrange & Act
        state = chat_graph_mod.ChatGraphState(
            request_id="r",
            thread_id="t",
            mode="chat",
            question="q",
        )

        # Assert
        assert state.answer == ""

    def test_approval_required_기본값은_False이다(self):
        # Arrange & Act
        state = chat_graph_mod.ChatGraphState(
            request_id="r",
            thread_id="t",
            mode="chat",
            question="q",
        )

        # Assert
        assert state.approval_required is False

    def test_두_인스턴스의_가변_필드가_서로_독립적이다(self):
        """ISO 26262 안전: 상태 객체 간 필드 공유 없음 검증."""
        # Arrange
        s1 = chat_graph_mod.ChatGraphState(
            request_id="r1", thread_id="t1", mode="chat", question="q1"
        )
        s2 = chat_graph_mod.ChatGraphState(
            request_id="r2", thread_id="t2", mode="chat", question="q2"
        )

        # Act: s1의 history에만 추가
        s1.history.append({"role": "user", "content": "hi"})

        # Assert: s2의 history는 영향받지 않아야 한다
        assert len(s2.history) == 0


# ---------------------------------------------------------------------------
# new_chat_graph_state 팩토리
# ---------------------------------------------------------------------------

@pytest.mark.skipif(chat_graph_mod is None, reason="workflow.chat_graph 임포트 불가")
class TestNewChatGraphState:
    """SRS-GRAPH-001: new_chat_graph_state 팩토리 함수 검증."""

    def test_request_id가_uuid_형식으로_생성된다(self):
        """Arrange: 최소 파라미터
        Act: new_chat_graph_state 호출
        Assert: request_id가 UUID 형식이다
        """
        # Arrange & Act
        state = chat_graph_mod.new_chat_graph_state(
            mode="chat",
            question="hello",
            session_id=None,
            report_dir=None,
            ui_context=None,
            history=None,
        )

        # Assert
        try:
            uuid.UUID(state.request_id)
            valid = True
        except ValueError:
            valid = False
        assert valid

    def test_session_id_있으면_thread_id가_session_id와_같다(self):
        """Arrange: session_id 제공
        Act: new_chat_graph_state 호출
        Assert: thread_id == session_id
        """
        # Arrange
        sid = "session-abc-123"

        # Act
        state = chat_graph_mod.new_chat_graph_state(
            mode="chat",
            question="q",
            session_id=sid,
            report_dir=None,
            ui_context=None,
            history=None,
        )

        # Assert
        assert state.thread_id == sid
        assert state.session_id == sid

    def test_session_id_없으면_thread_id가_request_id와_같다(self):
        """Arrange: session_id=None
        Act: new_chat_graph_state 호출
        Assert: thread_id == request_id
        """
        # Arrange & Act
        state = chat_graph_mod.new_chat_graph_state(
            mode="chat",
            question="q",
            session_id=None,
            report_dir=None,
            ui_context=None,
            history=None,
        )

        # Assert
        assert state.thread_id == state.request_id

    def test_history가_복사되어_전달된다(self):
        """Arrange: history 리스트 제공
        Act: new_chat_graph_state 호출
        Assert: history가 독립 복사본으로 설정된다
        """
        # Arrange
        original_history = [{"role": "user", "content": "prev question"}]

        # Act
        state = chat_graph_mod.new_chat_graph_state(
            mode="chat",
            question="follow-up",
            session_id=None,
            report_dir=None,
            ui_context=None,
            history=original_history,
        )

        # Act: 원본 수정
        original_history.append({"role": "assistant", "content": "answer"})

        # Assert: 상태 내 history는 영향받지 않아야 한다
        assert len(state.history) == 1

    def test_ui_context가_None이면_빈_dict로_초기화된다(self):
        # Arrange & Act
        state = chat_graph_mod.new_chat_graph_state(
            mode="chat",
            question="q",
            session_id=None,
            report_dir=None,
            ui_context=None,
            history=None,
        )

        # Assert
        assert state.ui_context == {}

    def test_report_dir이_설정된다(self):
        # Arrange
        rdir = "/reports/run_001"

        # Act
        state = chat_graph_mod.new_chat_graph_state(
            mode="chat",
            question="q",
            session_id=None,
            report_dir=rdir,
            ui_context=None,
            history=None,
        )

        # Assert
        assert state.report_dir == rdir


# ---------------------------------------------------------------------------
# emit_graph_event
# ---------------------------------------------------------------------------

@pytest.mark.skipif(chat_graph_mod is None, reason="workflow.chat_graph 임포트 불가")
class TestEmitGraphEvent:
    """SRS-GRAPH-002: 이벤트 콜백 구조 검증."""

    def _make_state(self) -> "chat_graph_mod.ChatGraphState":
        return chat_graph_mod.ChatGraphState(
            request_id="req-emit",
            thread_id="thread-emit",
            mode="chat",
            question="event test",
        )

    def test_콜백이_올바른_이벤트_구조로_호출된다(self):
        """Arrange: 이벤트 콜백 mock
        Act: emit_graph_event 호출
        Assert: type, request_id, thread_id, ts, payload 키가 포함된다
        """
        # Arrange
        received: List[Dict[str, Any]] = []
        state = self._make_state()

        # Act
        chat_graph_mod.emit_graph_event(
            received.append,
            event_type="test_event",
            state=state,
            payload={"info": "test"},
        )

        # Assert
        assert len(received) == 1
        evt = received[0]
        assert evt["type"] == "test_event"
        assert evt["request_id"] == "req-emit"
        assert evt["thread_id"] == "thread-emit"
        assert "ts" in evt
        assert evt["payload"] == {"info": "test"}

    def test_콜백이_None이면_에러가_발생하지_않는다(self):
        """Arrange: cb=None
        Act: emit_graph_event(None, ...) 호출
        Assert: 예외 없이 정상 종료
        """
        # Arrange
        state = self._make_state()

        # Act & Assert
        chat_graph_mod.emit_graph_event(
            None,
            event_type="noop",
            state=state,
        )

    def test_payload_기본값은_빈_dict이다(self):
        """Arrange: payload 생략
        Act: emit_graph_event 호출
        Assert: payload 키가 빈 dict이다
        """
        # Arrange
        received: List[Dict[str, Any]] = []
        state = self._make_state()

        # Act
        chat_graph_mod.emit_graph_event(
            received.append,
            event_type="no_payload",
            state=state,
        )

        # Assert
        assert received[0]["payload"] == {}


# ---------------------------------------------------------------------------
# run_chat_graph — 순수 Python fallback 경로
# ---------------------------------------------------------------------------

@pytest.mark.skipif(chat_graph_mod is None, reason="workflow.chat_graph 임포트 불가")
class TestRunChatGraphFallback:
    """SRS-GRAPH-002: LangGraph 없는 환경에서의 그래프 순차 실행 검증.

    LANGGRAPH_AVAILABLE=False 경로를 강제하여
    순수 Python fallback 로직만을 대상으로 한다.
    """

    def _make_state(self, question: str = "test") -> "chat_graph_mod.ChatGraphState":
        return chat_graph_mod.new_chat_graph_state(
            mode="chat",
            question=question,
            session_id=None,
            report_dir=None,
            ui_context=None,
            history=None,
        )

    def test_노드가_순서대로_실행된다(self):
        """Arrange: 두 노드를 등록
        Act: run_chat_graph 호출 (LANGGRAPH_AVAILABLE=False 강제)
        Assert: 실행 순서가 보장된다
        """
        # Arrange
        execution_order: List[str] = []

        def node_alpha(state: chat_graph_mod.ChatGraphState) -> Dict[str, Any]:
            execution_order.append("alpha")
            return {"intent": "alpha_done"}

        def node_beta(state: chat_graph_mod.ChatGraphState) -> Dict[str, Any]:
            execution_order.append("beta")
            return {"answer": "beta answer"}

        state = self._make_state()

        # Act: fallback 경로를 직접 테스트
        with patch.object(chat_graph_mod, "LANGGRAPH_AVAILABLE", False):
            result = chat_graph_mod.run_chat_graph(
                initial_state=state,
                nodes=[("alpha", node_alpha), ("beta", node_beta)],
            )

        # Assert
        assert execution_order == ["alpha", "beta"]
        assert result.intent == "alpha_done"
        assert result.answer == "beta answer"

    def test_노드_업데이트가_상태에_반영된다(self):
        """Arrange: answer를 업데이트하는 노드
        Act: run_chat_graph 호출
        Assert: 최종 상태에 answer가 반영된다
        """
        # Arrange
        def answer_node(state: chat_graph_mod.ChatGraphState) -> Dict[str, Any]:
            return {"answer": "42"}

        state = self._make_state("the ultimate question")

        # Act
        with patch.object(chat_graph_mod, "LANGGRAPH_AVAILABLE", False):
            result = chat_graph_mod.run_chat_graph(
                initial_state=state,
                nodes=[("answerer", answer_node)],
            )

        # Assert
        assert result.answer == "42"

    def test_노드가_None을_반환해도_에러가_발생하지_않는다(self):
        """경계값: 노드가 None 반환
        Act: run_chat_graph 호출
        Assert: 예외 없이 정상 종료
        """
        # Arrange
        def noop_node(state: chat_graph_mod.ChatGraphState) -> None:
            return None

        state = self._make_state()

        # Act & Assert
        with patch.object(chat_graph_mod, "LANGGRAPH_AVAILABLE", False):
            result = chat_graph_mod.run_chat_graph(
                initial_state=state,
                nodes=[("noop", noop_node)],
            )
        assert result is state  # 동일 객체 반환

    def test_빈_노드_리스트는_상태를_그대로_반환한다(self):
        """경계값: nodes=[]
        Act: run_chat_graph(nodes=[]) 호출
        Assert: 입력 상태가 변경 없이 반환된다
        """
        # Arrange
        state = self._make_state("empty nodes test")
        original_question = state.question

        # Act
        with patch.object(chat_graph_mod, "LANGGRAPH_AVAILABLE", False):
            result = chat_graph_mod.run_chat_graph(
                initial_state=state,
                nodes=[],
            )

        # Assert
        assert result.question == original_question

    def test_이벤트_콜백이_각_노드마다_시작_종료로_호출된다(self):
        """Arrange: 이벤트 콜백과 2개 노드 등록
        Act: run_chat_graph 호출
        Assert: 노드당 started + finished 이벤트가 발생한다
        """
        # Arrange
        events: List[Dict[str, Any]] = []

        def node_a(state: chat_graph_mod.ChatGraphState) -> Dict[str, Any]:
            return {}

        def node_b(state: chat_graph_mod.ChatGraphState) -> Dict[str, Any]:
            return {}

        state = self._make_state()

        # Act
        with patch.object(chat_graph_mod, "LANGGRAPH_AVAILABLE", False):
            chat_graph_mod.run_chat_graph(
                initial_state=state,
                nodes=[("node_a", node_a), ("node_b", node_b)],
                event_callback=events.append,
            )

        # Assert: 노드 2개 × (started + finished) = 4 이벤트
        event_types = [e["type"] for e in events]
        assert event_types.count("graph_node_started") == 2
        assert event_types.count("graph_node_finished") == 2

    def test_metrics에_노드별_elapsed_ms가_기록된다(self):
        """Arrange: 노드 1개
        Act: run_chat_graph 호출
        Assert: metrics.nodes에 해당 노드의 elapsed_ms가 기록된다
        """
        # Arrange
        def timed_node(state: chat_graph_mod.ChatGraphState) -> Dict[str, Any]:
            return {}

        state = self._make_state()

        # Act
        with patch.object(chat_graph_mod, "LANGGRAPH_AVAILABLE", False):
            result = chat_graph_mod.run_chat_graph(
                initial_state=state,
                nodes=[("timed_node", timed_node)],
            )

        # Assert
        assert "nodes" in result.metrics
        assert "timed_node" in result.metrics["nodes"]
        assert "elapsed_ms" in result.metrics["nodes"]["timed_node"]

    def test_extra_필드에_알_수_없는_키가_저장된다(self):
        """Arrange: ChatGraphState에 없는 키를 노드가 반환
        Act: run_chat_graph 호출
        Assert: state.extra에 해당 키가 저장된다
        """
        # Arrange
        def node_with_extra(state: chat_graph_mod.ChatGraphState) -> Dict[str, Any]:
            return {"unknown_field_xyz": "stored in extra"}

        state = self._make_state()

        # Act
        with patch.object(chat_graph_mod, "LANGGRAPH_AVAILABLE", False):
            result = chat_graph_mod.run_chat_graph(
                initial_state=state,
                nodes=[("extra_node", node_with_extra)],
            )

        # Assert
        assert result.extra.get("unknown_field_xyz") == "stored in extra"
