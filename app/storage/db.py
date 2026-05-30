from __future__ import annotations

import sqlite3
from pathlib import Path

from app.utils.logging import get_logger, log_safe


logger = get_logger("nesty.storage.db")


def _resolve_db_path(db_path: str) -> Path:
    path = Path(db_path)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def init_db(db_path: str) -> None:
    resolved = _resolve_db_path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(resolved) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                key_hash TEXT NOT NULL UNIQUE,
                key_prefix TEXT NOT NULL,
                environment TEXT NOT NULL DEFAULT 'dev',
                is_active INTEGER NOT NULL DEFAULT 1,
                daily_limit INTEGER DEFAULT NULL,
                monthly_limit INTEGER DEFAULT NULL,
                allowed_models TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT DEFAULT NULL,
                revoked_at TEXT DEFAULT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usage_logs (
                id TEXT PRIMARY KEY,
                api_key_id TEXT,
                request_id TEXT NOT NULL,
                conversation_id TEXT DEFAULT NULL,
                model TEXT,
                provider TEXT,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                tools_used TEXT DEFAULT NULL,
                search_used INTEGER DEFAULT 0,
                latency_ms INTEGER DEFAULT 0,
                status TEXT NOT NULL,
                error_code TEXT DEFAULT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                api_key_id TEXT DEFAULT NULL,
                title TEXT DEFAULT NULL,
                summary TEXT DEFAULT NULL,
                summary_updated_at TEXT DEFAULT NULL,
                summary_message_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived_at TEXT DEFAULT NULL,
                metadata TEXT DEFAULT NULL
            )
            """
        )
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
                memory_pinned INTEGER NOT NULL DEFAULT 0,
                memory_excluded INTEGER NOT NULL DEFAULT 0,
                memory_tags TEXT DEFAULT NULL,
                memory_updated_at TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                metadata TEXT DEFAULT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversation_messages_conv_created "
            "ON conversation_messages(conversation_id, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_api_key_updated "
            "ON conversations(api_key_id, updated_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS model_config_overrides (
                id TEXT PRIMARY KEY,
                model_id TEXT NOT NULL UNIQUE,
                config_json TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by_api_key_id TEXT DEFAULT NULL,
                updated_by_label TEXT DEFAULT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS model_config_audit_logs (
                id TEXT PRIMARY KEY,
                model_id TEXT NOT NULL,
                old_config_json TEXT DEFAULT NULL,
                new_config_json TEXT DEFAULT NULL,
                action TEXT NOT NULL,
                changed_by_api_key_id TEXT DEFAULT NULL,
                changed_by_label TEXT DEFAULT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_model_config_overrides_model_id_active "
            "ON model_config_overrides(model_id, is_active)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_model_config_audit_model_id_created "
            "ON model_config_audit_logs(model_id, created_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS embedding_records (
                id TEXT PRIMARY KEY,
                owner_type TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                api_key_id TEXT DEFAULT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                dimensions INTEGER DEFAULT NULL,
                content_hash TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                metadata TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_embedding_records_owner "
            "ON embedding_records(owner_type, owner_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_embedding_records_api_key_owner "
            "ON embedding_records(api_key_id, owner_type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_embedding_records_provider_model "
            "ON embedding_records(provider, model)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_embedding_records_content_hash "
            "ON embedding_records(content_hash)"
        )
        _ensure_usage_logs_has_conversation_id(conn)
        _ensure_conversations_summary_columns(conn)
        _ensure_conversation_messages_memory_columns(conn)
        conn.commit()
    _try_init_conversation_fts(db_path)


def _ensure_usage_logs_has_conversation_id(conn: sqlite3.Connection) -> None:
    rows = conn.execute("PRAGMA table_info(usage_logs)").fetchall()
    column_names = {str(row[1]) for row in rows}
    if "conversation_id" not in column_names:
        conn.execute("ALTER TABLE usage_logs ADD COLUMN conversation_id TEXT DEFAULT NULL")


def _ensure_conversations_summary_columns(conn: sqlite3.Connection) -> None:
    rows = conn.execute("PRAGMA table_info(conversations)").fetchall()
    column_names = {str(row[1]) for row in rows}
    if "summary" not in column_names:
        conn.execute("ALTER TABLE conversations ADD COLUMN summary TEXT DEFAULT NULL")
    if "summary_updated_at" not in column_names:
        conn.execute("ALTER TABLE conversations ADD COLUMN summary_updated_at TEXT DEFAULT NULL")
    if "summary_message_count" not in column_names:
        conn.execute("ALTER TABLE conversations ADD COLUMN summary_message_count INTEGER DEFAULT 0")


def _ensure_conversation_messages_memory_columns(conn: sqlite3.Connection) -> None:
    rows = conn.execute("PRAGMA table_info(conversation_messages)").fetchall()
    column_names = {str(row[1]) for row in rows}
    if "memory_pinned" not in column_names:
        conn.execute("ALTER TABLE conversation_messages ADD COLUMN memory_pinned INTEGER NOT NULL DEFAULT 0")
    if "memory_excluded" not in column_names:
        conn.execute("ALTER TABLE conversation_messages ADD COLUMN memory_excluded INTEGER NOT NULL DEFAULT 0")
    if "memory_tags" not in column_names:
        conn.execute("ALTER TABLE conversation_messages ADD COLUMN memory_tags TEXT DEFAULT NULL")
    if "memory_updated_at" not in column_names:
        conn.execute("ALTER TABLE conversation_messages ADD COLUMN memory_updated_at TEXT DEFAULT NULL")


def get_connection(db_path: str) -> sqlite3.Connection:
    resolved = _resolve_db_path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _try_init_conversation_fts(db_path: str) -> None:
    try:
        from app.storage.fts import init_conversation_fts

        enabled = init_conversation_fts(db_path)
        if enabled:
            log_safe(logger, "conversation_fts_ready", enabled=True)
        else:
            log_safe(logger, "conversation_fts_unavailable", enabled=False)
    except Exception:
        log_safe(logger, "conversation_fts_init_failed", error_code="fts_init_failed")

