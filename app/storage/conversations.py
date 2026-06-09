from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.deps import get_settings
from app.storage.db import get_connection
from app.storage.fts import init_conversation_fts, is_fts5_available, rebuild_conversation_fts, sync_message_to_fts
from app.utils.logging import get_logger, log_safe


logger = get_logger("nesty.storage.conversations")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _effective_db_path(db_path: str | None = None) -> str:
    if db_path:
        return db_path
    return get_settings().nesty_db_path


def _parse_metadata(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return data
    return None


def _parse_memory_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    tags: list[str] = []
    for item in parsed:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if cleaned:
            tags.append(cleaned)
    return tags


def _sanitize_memory_tags(tags: list[str] | None) -> list[str]:
    if tags is None:
        return []
    cleaned_tags: list[str] = []
    seen: set[str] = set()
    for item in tags:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if not cleaned:
            continue
        if len(cleaned) > 40:
            continue
        dedupe_key = cleaned.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        cleaned_tags.append(cleaned)
        if len(cleaned_tags) >= 10:
            break
    return cleaned_tags


def create_conversation(
    api_key_id: str | None,
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    conversation_id = f"conv_{uuid4().hex[:16]}"
    now = _now_iso()
    metadata_json = json.dumps(metadata or {}) if metadata is not None else None

    with get_connection(_effective_db_path(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO conversations (id, api_key_id, title, created_at, updated_at, archived_at, metadata)
            VALUES (?, ?, ?, ?, ?, NULL, ?)
            """,
            (conversation_id, api_key_id, title, now, now, metadata_json),
        )
        conn.commit()

    return {
        "id": conversation_id,
        "api_key_id": api_key_id,
        "title": title,
        "summary": None,
        "summary_updated_at": None,
        "summary_message_count": 0,
        "created_at": now,
        "updated_at": now,
        "archived_at": None,
        "metadata": metadata or None,
    }


def get_conversation(conversation_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    with get_connection(_effective_db_path(db_path)) as conn:
        row = conn.execute(
            """
            SELECT id, api_key_id, title, summary, summary_updated_at, summary_message_count,
                   created_at, updated_at, archived_at, metadata
            FROM conversations
            WHERE id = ?
            LIMIT 1
            """,
            (conversation_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "api_key_id": row["api_key_id"],
        "title": row["title"],
        "summary": row["summary"],
        "summary_updated_at": row["summary_updated_at"],
        "summary_message_count": int(row["summary_message_count"] or 0),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "archived_at": row["archived_at"],
        "metadata": _parse_metadata(row["metadata"]),
    }


def list_conversations(
    api_key_id: str | None,
    limit: int = 20,
    offset: int = 0,
    archived: str = "active",
    q: str | None = None,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    query = """
        SELECT id, api_key_id, title, summary, summary_updated_at, summary_message_count,
               created_at, updated_at, archived_at, metadata
        FROM conversations
        WHERE 1=1
    """
    params: list[Any] = []
    if archived == "active":
        query += " AND archived_at IS NULL"
    elif archived == "archived":
        query += " AND archived_at IS NOT NULL"
    elif archived == "all":
        pass
    else:
        raise ValueError("invalid archived filter")

    if api_key_id is None:
        query += " AND api_key_id IS NULL"
    else:
        query += " AND api_key_id = ?"
        params.append(api_key_id)
    query_text = (q or "").strip()
    if query_text:
        query += " AND (title LIKE ? OR summary LIKE ?)"
        like_value = f"%{query_text}%"
        params.extend([like_value, like_value])

    query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend([max(1, int(limit)), max(0, int(offset))])

    with get_connection(_effective_db_path(db_path)) as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [
        {
            "id": row["id"],
            "api_key_id": row["api_key_id"],
            "title": row["title"],
            "summary_exists": bool(str(row["summary"] or "").strip()),
            "summary_updated_at": row["summary_updated_at"],
            "summary_message_count": int(row["summary_message_count"] or 0),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "archived_at": row["archived_at"],
            "metadata": _parse_metadata(row["metadata"]),
        }
        for row in rows
    ]


def archive_conversation(
    conversation_id: str,
    api_key_id: str | None,
    db_path: str | None = None,
) -> bool:
    now = _now_iso()
    query = """
        UPDATE conversations
        SET archived_at = ?, updated_at = ?
        WHERE id = ? AND archived_at IS NULL
    """
    params: list[Any] = [now, now, conversation_id]
    if api_key_id is None:
        query += " AND api_key_id IS NULL"
    else:
        query += " AND api_key_id = ?"
        params.append(api_key_id)

    with get_connection(_effective_db_path(db_path)) as conn:
        cursor = conn.execute(query, tuple(params))
        conn.commit()
    return cursor.rowcount > 0


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    model: str | None = None,
    provider: str | None = None,
    metadata: dict[str, Any] | None = None,
    token_count: int = 0,
    db_path: str | None = None,
) -> dict[str, Any]:
    message_id = f"msg_{uuid4().hex[:16]}"
    now = _now_iso()
    metadata_json = json.dumps(metadata or {}) if metadata is not None else None
    with get_connection(_effective_db_path(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO conversation_messages
            (id, conversation_id, role, content, model, provider, token_count, memory_pinned, memory_excluded, memory_tags, memory_updated_at, created_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, NULL, ?, ?)
            """,
            (
                message_id,
                conversation_id,
                role,
                content,
                model,
                provider,
                int(token_count),
                now,
                metadata_json,
            ),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        conn.commit()

    message_payload = {
        "id": message_id,
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "model": model,
        "provider": provider,
        "token_count": int(token_count),
        "memory_pinned": False,
        "memory_excluded": False,
        "memory_tags": [],
        "memory_updated_at": None,
        "created_at": now,
        "metadata": metadata or None,
    }
    try:
        _ = sync_message_to_fts(_effective_db_path(db_path), message_payload)
    except Exception:
        # FTS sync failures must never block chat/message storage.
        pass
    return message_payload


def get_recent_messages(
    conversation_id: str,
    limit: int = 20,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    with get_connection(_effective_db_path(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT id, conversation_id, role, content, model, provider, token_count,
                   memory_pinned, memory_excluded, memory_tags, memory_updated_at, created_at, metadata
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (conversation_id, max(1, int(limit))),
        ).fetchall()
    ordered = list(reversed(rows))
    return [
        {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "role": row["role"],
            "content": row["content"],
            "model": row["model"],
            "provider": row["provider"],
            "token_count": int(row["token_count"] or 0),
            "memory_pinned": bool(int(row["memory_pinned"] or 0)),
            "memory_excluded": bool(int(row["memory_excluded"] or 0)),
            "memory_tags": _parse_memory_tags(row["memory_tags"]),
            "memory_updated_at": row["memory_updated_at"],
            "created_at": row["created_at"],
            "metadata": _parse_metadata(row["metadata"]),
        }
        for row in ordered
    ]


def list_messages(
    conversation_id: str,
    limit: int = 50,
    offset: int = 0,
    order: str = "asc",
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    order_sql = "ASC" if order == "asc" else "DESC"
    with get_connection(_effective_db_path(db_path)) as conn:
        rows = conn.execute(
            f"""
            SELECT id, conversation_id, role, content, model, provider, token_count,
                   memory_pinned, memory_excluded, memory_tags, memory_updated_at, created_at, metadata
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY created_at {order_sql}
            LIMIT ? OFFSET ?
            """,
            (
                conversation_id,
                max(1, int(limit)),
                max(0, int(offset)),
            ),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "role": row["role"],
            "content": row["content"],
            "model": row["model"],
            "provider": row["provider"],
            "token_count": int(row["token_count"] or 0),
            "memory_pinned": bool(int(row["memory_pinned"] or 0)),
            "memory_excluded": bool(int(row["memory_excluded"] or 0)),
            "memory_tags": _parse_memory_tags(row["memory_tags"]),
            "memory_updated_at": row["memory_updated_at"],
            "created_at": row["created_at"],
            "metadata": _parse_metadata(row["metadata"]),
        }
        for row in rows
    ]


def update_conversation_title(
    conversation_id: str,
    title: str,
    api_key_id: str | None = None,
    db_path: str | None = None,
) -> bool:
    now = _now_iso()
    query = "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ? AND archived_at IS NULL"
    params: list[Any] = [title, now, conversation_id]
    if api_key_id is None:
        query += " AND api_key_id IS NULL"
    else:
        query += " AND api_key_id = ?"
        params.append(api_key_id)

    with get_connection(_effective_db_path(db_path)) as conn:
        cursor = conn.execute(query, tuple(params))
        conn.commit()
    updated = cursor.rowcount > 0
    if updated:
        try:
            _ = rebuild_conversation_fts(_effective_db_path(db_path))
        except Exception:
            log_safe(
                logger,
                "conversation_fts_rebuild_after_title_update_failed",
                error_code="fts_rebuild_failed",
                conversation_id=conversation_id,
            )
    return updated


def count_messages(conversation_id: str, db_path: str | None = None) -> int:
    with get_connection(_effective_db_path(db_path)) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM conversation_messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
    return int(row["total"]) if row else 0


def get_message_count(conversation_id: str, db_path: str | None = None) -> int:
    return count_messages(conversation_id=conversation_id, db_path=db_path)


def get_conversation_summary(conversation_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    with get_connection(_effective_db_path(db_path)) as conn:
        row = conn.execute(
            """
            SELECT id, summary, summary_updated_at, summary_message_count
            FROM conversations
            WHERE id = ?
            LIMIT 1
            """,
            (conversation_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "summary": row["summary"],
        "summary_updated_at": row["summary_updated_at"],
        "summary_message_count": int(row["summary_message_count"] or 0),
    }


def update_conversation_summary(
    conversation_id: str,
    summary: str,
    summary_message_count: int,
    db_path: str | None = None,
) -> bool:
    now = _now_iso()
    with get_connection(_effective_db_path(db_path)) as conn:
        cursor = conn.execute(
            """
            UPDATE conversations
            SET summary = ?, summary_updated_at = ?, summary_message_count = ?, updated_at = ?
            WHERE id = ? AND archived_at IS NULL
            """,
            (summary, now, int(summary_message_count), now, conversation_id),
        )
        conn.commit()
    return cursor.rowcount > 0


def get_messages_after_summary(
    conversation_id: str,
    summary_message_count: int,
    limit: int,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    with get_connection(_effective_db_path(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT id, conversation_id, role, content, model, provider, token_count,
                   memory_pinned, memory_excluded, memory_tags, memory_updated_at, created_at, metadata
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            LIMIT -1 OFFSET ?
            """,
            (conversation_id, max(0, int(summary_message_count))),
        ).fetchall()

    if limit > 0:
        rows = rows[-limit:]
    return [
        {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "role": row["role"],
            "content": row["content"],
            "model": row["model"],
            "provider": row["provider"],
            "token_count": int(row["token_count"] or 0),
            "memory_pinned": bool(int(row["memory_pinned"] or 0)),
            "memory_excluded": bool(int(row["memory_excluded"] or 0)),
            "memory_tags": _parse_memory_tags(row["memory_tags"]),
            "memory_updated_at": row["memory_updated_at"],
            "created_at": row["created_at"],
            "metadata": _parse_metadata(row["metadata"]),
        }
        for row in rows
    ]


def get_conversation_stats(conversation_id: str, db_path: str | None = None) -> dict[str, Any]:
    with get_connection(_effective_db_path(db_path)) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS message_count, MAX(created_at) AS last_message_at
            FROM conversation_messages
            WHERE conversation_id = ?
            """,
            (conversation_id,),
        ).fetchone()
    return {
        "message_count": int(row["message_count"] or 0) if row else 0,
        "last_message_at": row["last_message_at"] if row else None,
    }


def clear_conversation_messages(
    conversation_id: str,
    api_key_id: str | None,
    keep_summary: bool = False,
    db_path: str | None = None,
) -> bool:
    now = _now_iso()
    owner_query = "SELECT id FROM conversations WHERE id = ? AND archived_at IS NULL"
    owner_params: list[Any] = [conversation_id]
    if api_key_id is None:
        owner_query += " AND api_key_id IS NULL"
    else:
        owner_query += " AND api_key_id = ?"
        owner_params.append(api_key_id)

    with get_connection(_effective_db_path(db_path)) as conn:
        owner_row = conn.execute(owner_query, tuple(owner_params)).fetchone()
        if owner_row is None:
            return False
        conn.execute("DELETE FROM conversation_messages WHERE conversation_id = ?", (conversation_id,))
        if keep_summary:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        else:
            conn.execute(
                """
                UPDATE conversations
                SET summary = NULL,
                    summary_updated_at = NULL,
                    summary_message_count = 0,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, conversation_id),
            )
        conn.commit()
    try:
        _ = rebuild_conversation_fts(_effective_db_path(db_path))
    except Exception:
        log_safe(
            logger,
            "conversation_fts_rebuild_after_clear_failed",
            error_code="fts_rebuild_failed",
            conversation_id=conversation_id,
        )
    return True


def reset_conversation_summary(
    conversation_id: str,
    api_key_id: str | None,
    db_path: str | None = None,
) -> bool:
    now = _now_iso()
    query = """
        UPDATE conversations
        SET summary = NULL,
            summary_updated_at = NULL,
            summary_message_count = 0,
            updated_at = ?
        WHERE id = ? AND archived_at IS NULL
    """
    params: list[Any] = [now, conversation_id]
    if api_key_id is None:
        query += " AND api_key_id IS NULL"
    else:
        query += " AND api_key_id = ?"
        params.append(api_key_id)

    with get_connection(_effective_db_path(db_path)) as conn:
        cursor = conn.execute(query, tuple(params))
        conn.commit()
    return cursor.rowcount > 0


def export_conversation(
    conversation_id: str,
    api_key_id: str | None,
    include_metadata: bool = True,
    messages_order: str = "asc",
    db_path: str | None = None,
) -> dict[str, Any] | None:
    query = """
        SELECT id, title, summary, summary_updated_at, summary_message_count,
               created_at, updated_at, archived_at, metadata
        FROM conversations
        WHERE id = ? AND archived_at IS NULL
    """
    params: list[Any] = [conversation_id]
    if api_key_id is None:
        query += " AND api_key_id IS NULL"
    else:
        query += " AND api_key_id = ?"
        params.append(api_key_id)

    with get_connection(_effective_db_path(db_path)) as conn:
        conversation_row = conn.execute(query, tuple(params)).fetchone()
        if conversation_row is None:
            return None
        order_sql = "ASC" if messages_order == "asc" else "DESC"
        message_rows = conn.execute(
            """
            SELECT id, role, content, model, provider, token_count, created_at, metadata
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY created_at
            """,
            (conversation_id,),
        ).fetchall() if order_sql == "ASC" else conn.execute(
            """
            SELECT id, role, content, model, provider, token_count, created_at, metadata
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            """,
            (conversation_id,),
        ).fetchall()

    stats = get_conversation_stats(conversation_id=conversation_id, db_path=db_path)
    conversation_payload = {
        "id": conversation_row["id"],
        "title": conversation_row["title"],
        "created_at": conversation_row["created_at"],
        "updated_at": conversation_row["updated_at"],
        "archived_at": conversation_row["archived_at"],
        "summary_exists": bool(str(conversation_row["summary"] or "").strip()),
        "summary_message_count": int(conversation_row["summary_message_count"] or 0),
        "summary_updated_at": conversation_row["summary_updated_at"],
        "message_count": stats["message_count"],
        "last_message_at": stats["last_message_at"],
    }
    if include_metadata:
        conversation_payload["metadata"] = _parse_metadata(conversation_row["metadata"])
    messages_payload = [
        {
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "model": row["model"],
            "provider": row["provider"],
            "token_count": int(row["token_count"] or 0),
            "created_at": row["created_at"],
        }
        for row in message_rows
    ]
    if include_metadata:
        for item, row in zip(messages_payload, message_rows):
            item["metadata"] = _parse_metadata(row["metadata"])
    return {
        "conversation": conversation_payload,
        "summary": conversation_row["summary"],
        "messages": messages_payload,
    }


def search_conversations(
    api_key_id: str | None,
    query: str,
    limit: int = 20,
    offset: int = 0,
    include_archived: bool = False,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT id, title, summary, summary_updated_at, summary_message_count, created_at, updated_at, archived_at
        FROM conversations
        WHERE 1=1
    """
    params: list[Any] = []
    if api_key_id is None:
        sql += " AND api_key_id IS NULL"
    else:
        sql += " AND api_key_id = ?"
        params.append(api_key_id)
    if not include_archived:
        sql += " AND archived_at IS NULL"
    like_value = f"%{query}%"
    sql += " AND (title LIKE ? OR summary LIKE ?)"
    params.extend([like_value, like_value])
    sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend([max(1, int(limit)), max(0, int(offset))])

    with get_connection(_effective_db_path(db_path)) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "archived_at": row["archived_at"],
            "summary_exists": bool(str(row["summary"] or "").strip()),
            "summary_updated_at": row["summary_updated_at"],
            "summary_message_count": int(row["summary_message_count"] or 0),
        }
        for row in rows
    ]


def search_messages(
    api_key_id: str | None,
    query: str,
    limit: int = 20,
    offset: int = 0,
    backend: str = "auto",
    conversation_id: str | None = None,
    exclude_memory_excluded: bool = True,
    db_path: str | None = None,
) -> dict[str, Any]:
    backend_mode = str(backend or "auto").strip().lower()
    if backend_mode not in {"auto", "fts", "like"}:
        raise ValueError("invalid_search_backend")

    if backend_mode == "like":
        data = _search_messages_like(
            api_key_id=api_key_id,
            query=query,
            limit=limit,
            offset=offset,
            conversation_id=conversation_id,
            exclude_memory_excluded=exclude_memory_excluded,
            db_path=db_path,
        )
        return {
            "data": data,
            "backend": "like",
            "fallback_used": False,
        }

    if backend_mode == "fts":
        if not is_fts5_available(_effective_db_path(db_path)):
            raise RuntimeError("fts_unavailable")
        data = _search_messages_fts(
            api_key_id=api_key_id,
            query=query,
            limit=limit,
            offset=offset,
            conversation_id=conversation_id,
            exclude_memory_excluded=exclude_memory_excluded,
            db_path=db_path,
        )
        return {
            "data": data,
            "backend": "fts",
            "fallback_used": False,
        }

    try:
        if not is_fts5_available(_effective_db_path(db_path)):
            raise RuntimeError("fts_unavailable")
        data = _search_messages_fts(
            api_key_id=api_key_id,
            query=query,
            limit=limit,
            offset=offset,
            conversation_id=conversation_id,
            exclude_memory_excluded=exclude_memory_excluded,
            db_path=db_path,
        )
        return {
            "data": data,
            "backend": "fts",
            "fallback_used": False,
        }
    except Exception:
        log_safe(logger, "conversation_search_fallback_like", query_length=len(query))
        data = _search_messages_like(
            api_key_id=api_key_id,
            query=query,
            limit=limit,
            offset=offset,
            conversation_id=conversation_id,
            exclude_memory_excluded=exclude_memory_excluded,
            db_path=db_path,
        )
        return {
            "data": data,
            "backend": "like",
            "fallback_used": True,
        }


def _search_messages_like(
    api_key_id: str | None,
    query: str,
    limit: int,
    offset: int,
    conversation_id: str | None = None,
    exclude_memory_excluded: bool = True,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            m.id,
            m.conversation_id,
            m.role,
            m.content,
            m.model,
            m.provider,
            m.token_count,
            m.memory_pinned,
            m.memory_excluded,
            m.memory_tags,
            m.created_at,
            m.metadata,
            c.title AS conversation_title
        FROM conversation_messages m
        JOIN conversations c ON c.id = m.conversation_id
        WHERE c.archived_at IS NULL
    """
    params: list[Any] = []
    if api_key_id is None:
        sql += " AND c.api_key_id IS NULL"
    else:
        sql += " AND c.api_key_id = ?"
        params.append(api_key_id)
    if conversation_id:
        sql += " AND m.conversation_id = ?"
        params.append(conversation_id)
    if exclude_memory_excluded:
        sql += " AND COALESCE(m.memory_excluded, 0) = 0"
    like_value = f"%{query}%"
    sql += " AND (m.content LIKE ? OR c.title LIKE ?)"
    params.extend([like_value, like_value])
    sql += " ORDER BY m.created_at DESC LIMIT ? OFFSET ?"
    params.extend([max(1, int(limit)), max(0, int(offset))])

    with get_connection(_effective_db_path(db_path)) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "conversation_title": row["conversation_title"],
            "role": row["role"],
            "content": row["content"],
            "model": row["model"],
            "provider": row["provider"],
            "token_count": int(row["token_count"] or 0),
            "created_at": row["created_at"],
            "rank": None,
            "snippet": None,
            "search_backend": "like",
            "memory_pinned": bool(int(row["memory_pinned"] or 0)) if "memory_pinned" in row.keys() else False,
            "memory_excluded": bool(int(row["memory_excluded"] or 0)) if "memory_excluded" in row.keys() else False,
            "memory_tags": _parse_memory_tags(row["memory_tags"]) if "memory_tags" in row.keys() else [],
            "metadata": _parse_metadata(row["metadata"]),
        }
        for row in rows
    ]


def get_recent_message_ids(
    conversation_id: str,
    limit: int = 20,
    db_path: str | None = None,
) -> list[str]:
    with get_connection(_effective_db_path(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT id
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (conversation_id, max(1, int(limit))),
        ).fetchall()
    return [str(row["id"]) for row in rows]


def get_message_by_id(
    message_id: str,
    api_key_id: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any] | None:
    query = """
        SELECT
            m.id,
            m.conversation_id,
            m.role,
            m.content,
            m.model,
            m.provider,
            m.token_count,
            m.memory_pinned,
            m.memory_excluded,
            m.memory_tags,
            m.memory_updated_at,
            m.created_at,
            m.metadata
        FROM conversation_messages m
        JOIN conversations c ON c.id = m.conversation_id
        WHERE m.id = ? AND c.archived_at IS NULL
    """
    params: list[Any] = [message_id]
    if api_key_id is None:
        query += " AND c.api_key_id IS NULL"
    else:
        query += " AND c.api_key_id = ?"
        params.append(api_key_id)
    query += " LIMIT 1"

    with get_connection(_effective_db_path(db_path)) as conn:
        row = conn.execute(query, tuple(params)).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "role": row["role"],
        "content": row["content"],
        "model": row["model"],
        "provider": row["provider"],
        "token_count": int(row["token_count"] or 0),
        "memory_pinned": bool(int(row["memory_pinned"] or 0)),
        "memory_excluded": bool(int(row["memory_excluded"] or 0)),
        "memory_tags": _parse_memory_tags(row["memory_tags"]),
        "memory_updated_at": row["memory_updated_at"],
        "created_at": row["created_at"],
        "metadata": _parse_metadata(row["metadata"]),
    }


def update_message_memory_controls(
    message_id: str,
    conversation_id: str,
    api_key_id: str | None,
    pinned: bool | None = None,
    excluded: bool | None = None,
    tags: list[str] | None = None,
    db_path: str | None = None,
) -> dict[str, Any] | None:
    now = _now_iso()
    query = """
        SELECT m.id, m.conversation_id, m.memory_pinned, m.memory_excluded, m.memory_tags
        FROM conversation_messages m
        JOIN conversations c ON c.id = m.conversation_id
        WHERE m.id = ? AND m.conversation_id = ? AND c.archived_at IS NULL
    """
    params: list[Any] = [message_id, conversation_id]
    if api_key_id is None:
        query += " AND c.api_key_id IS NULL"
    else:
        query += " AND c.api_key_id = ?"
        params.append(api_key_id)
    query += " LIMIT 1"

    with get_connection(_effective_db_path(db_path)) as conn:
        existing = conn.execute(query, tuple(params)).fetchone()
        if existing is None:
            return None

        current_pinned = bool(int(existing["memory_pinned"] or 0))
        current_excluded = bool(int(existing["memory_excluded"] or 0))
        current_tags = _parse_memory_tags(existing["memory_tags"])
        next_pinned = current_pinned if pinned is None else bool(pinned)
        next_excluded = current_excluded if excluded is None else bool(excluded)
        next_tags = current_tags if tags is None else _sanitize_memory_tags(tags)

        if excluded is True:
            next_excluded = True
            next_pinned = False
        elif pinned is True:
            next_pinned = True
            next_excluded = False

        tags_json = json.dumps(next_tags, ensure_ascii=True) if next_tags else None
        conn.execute(
            """
            UPDATE conversation_messages
            SET memory_pinned = ?, memory_excluded = ?, memory_tags = ?, memory_updated_at = ?
            WHERE id = ? AND conversation_id = ?
            """,
            (
                1 if next_pinned else 0,
                1 if next_excluded else 0,
                tags_json,
                now,
                message_id,
                conversation_id,
            ),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        conn.commit()

    return get_message_by_id(message_id=message_id, api_key_id=api_key_id, db_path=db_path)


def list_memory_controlled_messages(
    api_key_id: str | None,
    pinned: bool | None = None,
    excluded: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    query = """
        SELECT
            m.id,
            m.conversation_id,
            m.role,
            m.content,
            m.created_at,
            m.memory_pinned,
            m.memory_excluded,
            m.memory_tags,
            m.memory_updated_at
        FROM conversation_messages m
        JOIN conversations c ON c.id = m.conversation_id
        WHERE c.archived_at IS NULL
    """
    params: list[Any] = []
    if api_key_id is None:
        query += " AND c.api_key_id IS NULL"
    else:
        query += " AND c.api_key_id = ?"
        params.append(api_key_id)
    if pinned is not None:
        query += " AND m.memory_pinned = ?"
        params.append(1 if pinned else 0)
    if excluded is not None:
        query += " AND m.memory_excluded = ?"
        params.append(1 if excluded else 0)
    if pinned is None and excluded is None:
        query += " AND (m.memory_pinned = 1 OR m.memory_excluded = 1 OR m.memory_tags IS NOT NULL)"
    query += " ORDER BY COALESCE(m.memory_updated_at, m.created_at) DESC LIMIT ? OFFSET ?"
    params.extend([max(1, int(limit)), max(0, int(offset))])

    with get_connection(_effective_db_path(db_path)) as conn:
        rows = conn.execute(query, tuple(params)).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        preview = " ".join(str(row["content"] or "").replace("\r", " ").replace("\n", " ").split())
        if len(preview) > 200:
            preview = preview[:200].rstrip() + "..."
        items.append(
            {
                "id": row["id"],
                "conversation_id": row["conversation_id"],
                "role": row["role"],
                "created_at": row["created_at"],
                "content_preview": preview,
                "memory_pinned": bool(int(row["memory_pinned"] or 0)),
                "memory_excluded": bool(int(row["memory_excluded"] or 0)),
                "memory_tags": _parse_memory_tags(row["memory_tags"]),
                "memory_updated_at": row["memory_updated_at"],
            }
        )
    return items


def _search_messages_fts(
    api_key_id: str | None,
    query: str,
    limit: int,
    offset: int,
    conversation_id: str | None = None,
    exclude_memory_excluded: bool = True,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    if not init_conversation_fts(_effective_db_path(db_path)):
        raise RuntimeError("fts_unavailable")

    fts_query = _normalize_fts_query(query)
    sql = """
        SELECT
            m.id,
            m.conversation_id,
            m.role,
            m.content,
            m.model,
            m.provider,
            m.token_count,
            m.memory_pinned,
            m.memory_excluded,
            m.memory_tags,
            m.created_at,
            m.metadata,
            c.title AS conversation_title,
            bm25(conversation_messages_fts) AS rank,
            snippet(conversation_messages_fts, 4, '[', ']', '...', 16) AS snippet
        FROM conversation_messages_fts
        JOIN conversation_messages m ON m.id = conversation_messages_fts.message_id
        JOIN conversations c ON c.id = m.conversation_id
        WHERE conversation_messages_fts MATCH ? AND c.archived_at IS NULL
    """
    params: list[Any] = [fts_query]
    if api_key_id is None:
        sql += " AND c.api_key_id IS NULL"
    else:
        sql += " AND c.api_key_id = ?"
        params.append(api_key_id)
    if conversation_id:
        sql += " AND m.conversation_id = ?"
        params.append(conversation_id)
    if exclude_memory_excluded:
        sql += " AND COALESCE(m.memory_excluded, 0) = 0"
    sql += " ORDER BY rank ASC, m.created_at DESC LIMIT ? OFFSET ?"
    params.extend([max(1, int(limit)), max(0, int(offset))])

    with get_connection(_effective_db_path(db_path)) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()

    return [
        {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "conversation_title": row["conversation_title"],
            "role": row["role"],
            "content": row["content"],
            "model": row["model"],
            "provider": row["provider"],
            "token_count": int(row["token_count"] or 0),
            "created_at": row["created_at"],
            "rank": float(row["rank"]) if row["rank"] is not None else None,
            "snippet": str(row["snippet"] or ""),
            "search_backend": "fts",
            "memory_pinned": bool(int(row["memory_pinned"] or 0)),
            "memory_excluded": bool(int(row["memory_excluded"] or 0)),
            "memory_tags": _parse_memory_tags(row["memory_tags"]),
            "metadata": _parse_metadata(row["metadata"]),
        }
        for row in rows
    ]


def _normalize_fts_query(query: str) -> str:
    raw = str(query or "").strip()
    tokens = [token for token in re.split(r"\s+", raw) if token]
    if not tokens:
        return '""'
    escaped = [token.replace('"', '""') for token in tokens]
    return " AND ".join(f'"{token}"' for token in escaped)
