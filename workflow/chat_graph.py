from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional
from typing_extensions import TypedDict

try:  # pragma: no cover
    from langgraph.graph import END, START, StateGraph  # type: ignore
    LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover
    LANGGRAPH_AVAILABLE = False
    StateGraph = None  # type: ignore
    START = "__start__"  # type: ignore
    END = "__end__"  # type: ignore


GraphNodeFn = Callable[["ChatGraphState"], Dict[str, Any]]
GraphEventCallback = Callable[[Dict[str, Any]], None]


@dataclass
class ChatGraphState:
    request_id: str
    thread_id: str
    mode: str
    question: str
    session_id: Optional[str] = None
    report_dir: Optional[str] = None
    ui_context: Optional[Dict[str, Any]] = None
    history: List[Dict[str, str]] = field(default_factory=list)
    selected_model: str = ""
    intent: str = ""
    context_policy: Dict[str, Any] = field(default_factory=dict)
    retrieval_hits: List[Dict[str, Any]] = field(default_factory=list)
    tool_plan: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    approval_required: bool = False
    approval_request: Optional[Dict[str, Any]] = None
    errors: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)


class LangGraphState(TypedDict, total=False):
    request_id: str
    thread_id: str
    mode: str
    question: str
    session_id: Optional[str]
    report_dir: Optional[str]
    ui_context: Optional[Dict[str, Any]]
    history: List[Dict[str, str]]
    selected_model: str
    intent: str
    context_policy: Dict[str, Any]
    retrieval_hits: List[Dict[str, Any]]
    tool_plan: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]
    evidence: List[Dict[str, Any]]
    citations: List[Dict[str, Any]]
    answer: str
    approval_required: bool
    approval_request: Optional[Dict[str, Any]]
    errors: List[Dict[str, Any]]
    metrics: Dict[str, Any]
    extra: Dict[str, Any]


def new_chat_graph_state(
    *,
    mode: str,
    question: str,
    session_id: Optional[str],
    report_dir: Optional[str],
    ui_context: Optional[Dict[str, Any]],
    history: Optional[List[Dict[str, str]]],
) -> ChatGraphState:
    request_id = str(uuid.uuid4())
    thread_id = str(session_id or request_id)
    return ChatGraphState(
        request_id=request_id,
        thread_id=thread_id,
        mode=mode,
        question=question,
        session_id=session_id,
        report_dir=report_dir,
        ui_context=ui_context or {},
        history=list(history or []),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit_graph_event(
    cb: Optional[GraphEventCallback],
    *,
    event_type: str,
    state: ChatGraphState,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    if cb is None:
        return
    cb(
        {
            "type": event_type,
            "request_id": state.request_id,
            "thread_id": state.thread_id,
            "ts": _utc_now(),
            "payload": payload or {},
        }
    )


def run_chat_graph(
    *,
    initial_state: ChatGraphState,
    nodes: Iterable[tuple[str, GraphNodeFn]],
    event_callback: Optional[GraphEventCallback] = None,
) -> ChatGraphState:
    if LANGGRAPH_AVAILABLE and StateGraph is not None:
        graph = StateGraph(LangGraphState)
        node_names: List[str] = []

        def _make_wrapped(node_name: str, node_fn: GraphNodeFn):
            def _wrapped(state_dict: LangGraphState) -> Dict[str, Any]:
                state_obj = ChatGraphState(**{k: v for k, v in state_dict.items() if k in ChatGraphState.__dataclass_fields__})
                emit_graph_event(
                    event_callback,
                    event_type="graph_node_started",
                    state=state_obj,
                    payload={"node": node_name},
                )
                started = time.perf_counter()
                updates = node_fn(state_obj) or {}
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                metrics = dict(state_dict.get("metrics") or {})
                node_metrics = dict(metrics.get("nodes") or {})
                node_metrics[node_name] = {"elapsed_ms": round(elapsed_ms, 1)}
                metrics["nodes"] = node_metrics
                updates["metrics"] = metrics
                emit_graph_event(
                    event_callback,
                    event_type="graph_node_finished",
                    state=state_obj,
                    payload={"node": node_name, "elapsed_ms": round(elapsed_ms, 1)},
                )
                return updates
            return _wrapped

        for name, fn in nodes:
            graph.add_node(name, _make_wrapped(name, fn))
            node_names.append(name)
        if node_names:
            graph.add_edge(START, node_names[0])
            for prev, nxt in zip(node_names, node_names[1:]):
                graph.add_edge(prev, nxt)
            graph.add_edge(node_names[-1], END)
        compiled = graph.compile()
        total_started = time.perf_counter()
        result = compiled.invoke(initial_state.__dict__.copy())
        initial_state.metrics["graph_total_ms"] = round((time.perf_counter() - total_started) * 1000.0, 1)
        for key, value in result.items():
            if hasattr(initial_state, key):
                setattr(initial_state, key, value)
            else:
                initial_state.extra[key] = value
        return initial_state

    state = initial_state
    total_started = time.perf_counter()
    for node_name, node_fn in nodes:
        emit_graph_event(
            event_callback,
            event_type="graph_node_started",
            state=state,
            payload={"node": node_name},
        )
        started = time.perf_counter()
        updates: Dict[str, Any] = node_fn(state) or {}
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        for key, value in updates.items():
            if hasattr(state, key):
                setattr(state, key, value)
            else:
                state.extra[key] = value
        node_metrics = dict(state.metrics.get("nodes") or {})
        node_metrics[node_name] = {"elapsed_ms": round(elapsed_ms, 1)}
        state.metrics["nodes"] = node_metrics
        emit_graph_event(
            event_callback,
            event_type="graph_node_finished",
            state=state,
            payload={
                "node": node_name,
                "elapsed_ms": round(elapsed_ms, 1),
            },
        )
    state.metrics["graph_total_ms"] = round((time.perf_counter() - total_started) * 1000.0, 1)
    return state
