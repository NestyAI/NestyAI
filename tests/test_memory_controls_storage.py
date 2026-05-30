from __future__ import annotations

from app.storage.conversations import (
    add_message,
    create_conversation,
    get_message_by_id,
    list_memory_controlled_messages,
    update_message_memory_controls,
)
from app.storage.db import get_connection, init_db


def test_memory_control_columns_exist_after_init(tmp_path) -> None:
    db_path = str(tmp_path / "memory_controls_columns.db")
    init_db(db_path)
    with get_connection(db_path) as conn:
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(conversation_messages)").fetchall()}
    assert "memory_pinned" in columns
    assert "memory_excluded" in columns
    assert "memory_tags" in columns
    assert "memory_updated_at" in columns


def test_memory_control_columns_migrate_existing_table(tmp_path) -> None:
    db_path = str(tmp_path / "memory_controls_migrate.db")
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                model TEXT DEFAULT NULL,
                provider TEXT DEFAULT NULL,
                token_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                metadata TEXT DEFAULT NULL
            )
            """
        )
        conn.commit()

    init_db(db_path)
    with get_connection(db_path) as conn:
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(conversation_messages)").fetchall()}
    assert "memory_pinned" in columns
    assert "memory_excluded" in columns
    assert "memory_tags" in columns
    assert "memory_updated_at" in columns


def test_update_message_memory_controls_updates_flags_and_tags(tmp_path) -> None:
    db_path = str(tmp_path / "memory_controls_update.db")
    init_db(db_path)
    conv = create_conversation(api_key_id="key_1", title="A", db_path=db_path)
    msg = add_message(conversation_id=conv["id"], role="user", content="hello", db_path=db_path)

    updated = update_message_memory_controls(
        message_id=msg["id"],
        conversation_id=conv["id"],
        api_key_id="key_1",
        pinned=True,
        excluded=False,
        tags=["project", "important", "important", "", "x" * 41],
        db_path=db_path,
    )
    assert updated is not None
    assert updated["memory_pinned"] is True
    assert updated["memory_excluded"] is False
    assert updated["memory_tags"] == ["project", "important"]
    assert updated["memory_updated_at"] is not None

    excluded = update_message_memory_controls(
        message_id=msg["id"],
        conversation_id=conv["id"],
        api_key_id="key_1",
        excluded=True,
        db_path=db_path,
    )
    assert excluded is not None
    assert excluded["memory_excluded"] is True
    assert excluded["memory_pinned"] is False


def test_memory_controls_respect_ownership(tmp_path) -> None:
    db_path = str(tmp_path / "memory_controls_owner.db")
    init_db(db_path)
    conv = create_conversation(api_key_id="owner", title="A", db_path=db_path)
    msg = add_message(conversation_id=conv["id"], role="user", content="hello", db_path=db_path)

    blocked = update_message_memory_controls(
        message_id=msg["id"],
        conversation_id=conv["id"],
        api_key_id="other",
        pinned=True,
        db_path=db_path,
    )
    assert blocked is None

    owned = get_message_by_id(message_id=msg["id"], api_key_id="owner", db_path=db_path)
    other = get_message_by_id(message_id=msg["id"], api_key_id="other", db_path=db_path)
    assert owned is not None
    assert other is None


def test_list_memory_controlled_messages_filters(tmp_path) -> None:
    db_path = str(tmp_path / "memory_controls_list.db")
    init_db(db_path)
    conv = create_conversation(api_key_id="key_1", title="A", db_path=db_path)
    msg_pinned = add_message(conversation_id=conv["id"], role="user", content="pinned text", db_path=db_path)
    msg_excluded = add_message(conversation_id=conv["id"], role="assistant", content="excluded text", db_path=db_path)

    _ = update_message_memory_controls(
        message_id=msg_pinned["id"],
        conversation_id=conv["id"],
        api_key_id="key_1",
        pinned=True,
        tags=["project"],
        db_path=db_path,
    )
    _ = update_message_memory_controls(
        message_id=msg_excluded["id"],
        conversation_id=conv["id"],
        api_key_id="key_1",
        excluded=True,
        db_path=db_path,
    )

    pinned_rows = list_memory_controlled_messages(
        api_key_id="key_1",
        pinned=True,
        excluded=False,
        db_path=db_path,
    )
    assert len(pinned_rows) == 1
    assert pinned_rows[0]["id"] == msg_pinned["id"]
    assert len(pinned_rows[0]["content_preview"]) <= 203

    excluded_rows = list_memory_controlled_messages(
        api_key_id="key_1",
        excluded=True,
        db_path=db_path,
    )
    assert len(excluded_rows) == 1
    assert excluded_rows[0]["id"] == msg_excluded["id"]
