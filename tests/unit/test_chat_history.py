"""Tests for chat history persistence feature.

Covers: models, DB init, CRUD operations in chat_history_service.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is importable
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest

from backend.services.chat_history_db import init_db, get_engine, reset_engine, get_session
from backend.services.chat_history_models import ChatHistoryBase, ChatConversation, ChatMessage
from backend.services.chat_history_service import (
    _auto_title,
    save_message_pair,
    load_history,
    load_history_as_chat_items,
    list_conversations,
    delete_conversation,
    update_title,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path):
    """Each test gets a fresh SQLite DB in a temp directory."""
    db_file = tmp_path / "test_chat_history.sqlite"
    reset_engine()
    init_db(db_file)
    yield
    reset_engine()


# ── 1. DB initialization ───────────────────────────────────────────────


class TestDBInit:
    def test_init_db_creates_tables(self, tmp_path: Path):
        """init_db creates chat_conversations and chat_messages tables."""
        engine = get_engine()
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "chat_conversations" in tables
        assert "chat_messages" in tables

    def test_init_db_idempotent(self, tmp_path: Path):
        """Calling init_db twice does not raise errors."""
        db_file = tmp_path / "idempotent.sqlite"
        reset_engine()
        init_db(db_file)
        init_db(db_file)  # second call should be fine
        engine = get_engine()
        from sqlalchemy import inspect
        tables = inspect(engine).get_table_names()
        assert "chat_conversations" in tables


# ── 2. save_message_pair ───────────────────────────────────────────────


class TestSaveMessagePair:
    def test_creates_conversation_and_two_messages(self):
        """First save creates a conversation + user msg + assistant msg."""
        result = save_message_pair(
            thread_id="t-001",
            session_id="s-001",
            mode="local",
            report_dir="/tmp/reports",
            question="Hello?",
            answer="Hi there!",
            request_id="req-1",
            llm_model="claude-opus",
        )
        assert result["thread_id"] == "t-001"
        assert result["saved"] == 2

        history = load_history("t-001")
        assert history is not None
        assert history["total_messages"] == 2
        assert history["messages"][0]["role"] == "user"
        assert history["messages"][0]["text"] == "Hello?"
        assert history["messages"][1]["role"] == "assistant"
        assert history["messages"][1]["text"] == "Hi there!"

    def test_appends_to_existing_conversation(self):
        """Second save to same thread_id appends messages (seq 3, 4)."""
        save_message_pair(
            thread_id="t-002",
            session_id="s-001",
            mode="local",
            report_dir=None,
            question="Q1",
            answer="A1",
        )
        save_message_pair(
            thread_id="t-002",
            session_id="s-001",
            mode="local",
            report_dir=None,
            question="Q2",
            answer="A2",
        )

        history = load_history("t-002")
        assert history["total_messages"] == 4
        seqs = [m["seq"] for m in history["messages"]]
        assert seqs == [1, 2, 3, 4]

    def test_auto_title_set_on_first_save(self):
        """Title is auto-generated from the first question."""
        save_message_pair(
            thread_id="t-003",
            session_id=None,
            mode="local",
            report_dir=None,
            question="What is UDS diagnostic?",
            answer="UDS stands for...",
        )
        history = load_history("t-003")
        assert history["title"] == "What is UDS diagnostic?"

    def test_llm_model_stored(self):
        """llm_model field is persisted on assistant message."""
        save_message_pair(
            thread_id="t-004",
            session_id=None,
            mode="local",
            report_dir=None,
            question="Q",
            answer="A",
            llm_model="claude-opus-4",
        )
        history = load_history("t-004")
        assistant_msg = [m for m in history["messages"] if m["role"] == "assistant"][0]
        assert assistant_msg["llm_model"] == "claude-opus-4"


# ── 3. load_history ────────────────────────────────────────────────────


class TestLoadHistory:
    def test_returns_none_for_missing_thread(self):
        """load_history returns None when thread_id does not exist."""
        assert load_history("nonexistent") is None

    def test_messages_ordered_by_seq(self):
        """Messages come back sorted by seq."""
        save_message_pair(
            thread_id="t-order", session_id=None, mode="local",
            report_dir=None, question="Q1", answer="A1",
        )
        save_message_pair(
            thread_id="t-order", session_id=None, mode="local",
            report_dir=None, question="Q2", answer="A2",
        )
        history = load_history("t-order")
        roles = [m["role"] for m in history["messages"]]
        assert roles == ["user", "assistant", "user", "assistant"]

    def test_pagination_limit(self):
        """limit controls how many messages are returned."""
        save_message_pair(
            thread_id="t-page", session_id=None, mode="local",
            report_dir=None, question="Q1", answer="A1",
        )
        save_message_pair(
            thread_id="t-page", session_id=None, mode="local",
            report_dir=None, question="Q2", answer="A2",
        )
        history = load_history("t-page", limit=2)
        assert len(history["messages"]) == 2
        assert history["total_messages"] == 4

    def test_pagination_offset(self):
        """offset skips initial messages."""
        save_message_pair(
            thread_id="t-off", session_id=None, mode="local",
            report_dir=None, question="Q1", answer="A1",
        )
        save_message_pair(
            thread_id="t-off", session_id=None, mode="local",
            report_dir=None, question="Q2", answer="A2",
        )
        history = load_history("t-off", limit=2, offset=2)
        assert len(history["messages"]) == 2
        assert history["messages"][0]["text"] == "Q2"

    def test_result_contains_metadata(self):
        """Returned dict includes thread_id, session_id, mode, timestamps."""
        save_message_pair(
            thread_id="t-meta", session_id="s-meta", mode="remote",
            report_dir="/tmp", question="Q", answer="A",
        )
        history = load_history("t-meta")
        assert history["thread_id"] == "t-meta"
        assert history["session_id"] == "s-meta"
        assert history["mode"] == "remote"
        assert "created_at" in history
        assert "updated_at" in history


# ── 4. load_history_as_chat_items ──────────────────────────────────────


class TestLoadHistoryAsChatItems:
    def test_returns_empty_for_missing_thread(self):
        assert load_history_as_chat_items("ghost") == []

    def test_returns_role_text_dicts(self):
        save_message_pair(
            thread_id="t-items", session_id=None, mode="local",
            report_dir=None, question="Hello", answer="World",
        )
        items = load_history_as_chat_items("t-items")
        assert len(items) == 2
        assert items[0] == {"role": "user", "text": "Hello"}
        assert items[1] == {"role": "assistant", "text": "World"}

    def test_last_n_limits_messages(self):
        """Only the last N messages are returned."""
        for i in range(5):
            save_message_pair(
                thread_id="t-lastn", session_id=None, mode="local",
                report_dir=None, question=f"Q{i}", answer=f"A{i}",
            )
        items = load_history_as_chat_items("t-lastn", last_n=4)
        assert len(items) == 4
        # Should be the last 4 messages (Q3, A3, Q4, A4)
        assert items[0]["text"] == "Q3"
        assert items[3]["text"] == "A4"


# ── 5. list_conversations ─────────────────────────────────────────────


class TestListConversations:
    def test_lists_all_conversations(self):
        save_message_pair(
            thread_id="t-list-1", session_id="s1", mode="local",
            report_dir=None, question="Q1", answer="A1",
        )
        save_message_pair(
            thread_id="t-list-2", session_id="s2", mode="local",
            report_dir=None, question="Q2", answer="A2",
        )
        result = list_conversations()
        assert result["total"] == 2
        assert len(result["conversations"]) == 2

    def test_filter_by_session_id(self):
        save_message_pair(
            thread_id="t-sf-1", session_id="alpha", mode="local",
            report_dir=None, question="Q", answer="A",
        )
        save_message_pair(
            thread_id="t-sf-2", session_id="beta", mode="local",
            report_dir=None, question="Q", answer="A",
        )
        save_message_pair(
            thread_id="t-sf-3", session_id="alpha", mode="local",
            report_dir=None, question="Q", answer="A",
        )
        result = list_conversations(session_id="alpha")
        assert result["total"] == 2
        thread_ids = {c["thread_id"] for c in result["conversations"]}
        assert thread_ids == {"t-sf-1", "t-sf-3"}

    def test_conversations_include_message_count(self):
        save_message_pair(
            thread_id="t-mc", session_id=None, mode="local",
            report_dir=None, question="Q1", answer="A1",
        )
        save_message_pair(
            thread_id="t-mc", session_id=None, mode="local",
            report_dir=None, question="Q2", answer="A2",
        )
        result = list_conversations()
        conv = result["conversations"][0]
        assert conv["message_count"] == 4

    def test_ordered_by_updated_at_desc(self):
        """Most recently updated conversation comes first."""
        save_message_pair(
            thread_id="t-ord-1", session_id=None, mode="local",
            report_dir=None, question="old", answer="old",
        )
        save_message_pair(
            thread_id="t-ord-2", session_id=None, mode="local",
            report_dir=None, question="new", answer="new",
        )
        result = list_conversations()
        assert result["conversations"][0]["thread_id"] == "t-ord-2"


# ── 6. delete_conversation ─────────────────────────────────────────────


class TestDeleteConversation:
    def test_deletes_conversation_and_messages(self):
        save_message_pair(
            thread_id="t-del", session_id=None, mode="local",
            report_dir=None, question="Q", answer="A",
        )
        assert delete_conversation("t-del") is True
        assert load_history("t-del") is None

    def test_returns_false_for_nonexistent(self):
        assert delete_conversation("ghost-thread") is False

    def test_messages_cascade_deleted(self):
        """After deleting conversation, messages table has no orphans."""
        save_message_pair(
            thread_id="t-cascade", session_id=None, mode="local",
            report_dir=None, question="Q", answer="A",
        )
        delete_conversation("t-cascade")
        with get_session() as sess:
            count = sess.query(ChatMessage).count()
            assert count == 0


# ── 7. update_title ────────────────────────────────────────────────────


class TestUpdateTitle:
    def test_changes_title(self):
        save_message_pair(
            thread_id="t-title", session_id=None, mode="local",
            report_dir=None, question="Original title question", answer="A",
        )
        assert update_title("t-title", "New Title") is True
        history = load_history("t-title")
        assert history["title"] == "New Title"

    def test_returns_false_for_nonexistent(self):
        assert update_title("ghost", "Title") is False

    def test_truncates_at_200_chars(self):
        save_message_pair(
            thread_id="t-trunc", session_id=None, mode="local",
            report_dir=None, question="Q", answer="A",
        )
        long_title = "A" * 300
        update_title("t-trunc", long_title)
        history = load_history("t-trunc")
        assert len(history["title"]) == 200


# ── 8. _auto_title ────────────────────────────────────────────────────


class TestAutoTitle:
    def test_short_text_unchanged(self):
        assert _auto_title("Short question") == "Short question"

    def test_truncates_at_80_chars(self):
        long = "x" * 120
        result = _auto_title(long)
        assert len(result) == 80
        assert result == "x" * 80

    def test_strips_whitespace(self):
        assert _auto_title("  hello  ") == "hello"

    def test_replaces_newlines_with_space(self):
        assert _auto_title("line1\nline2\nline3") == "line1 line2 line3"

    def test_exactly_80_chars_unchanged(self):
        text = "a" * 80
        assert _auto_title(text) == text
        assert len(_auto_title(text)) == 80
