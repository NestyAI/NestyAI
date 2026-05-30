from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.deps import get_settings
from app.storage.db import get_connection, init_db


def _iso_cutoff(days: int | None) -> str | None:
    if days is None:
        return None
    days = max(0, int(days))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff.isoformat()


def _build_query(conversation_id: str | None, cutoff_iso: str | None) -> tuple[str, list]:
    sql = """
        SELECT m.id
        FROM conversation_messages m
        JOIN conversations c ON c.id = m.conversation_id
        WHERE c.archived_at IS NULL
          AND COALESCE(m.memory_excluded, 0) = 1
    """
    params: list = []
    if conversation_id:
        sql += " AND m.conversation_id = ?"
        params.append(conversation_id)
    if cutoff_iso:
        sql += " AND m.created_at <= ?"
        params.append(cutoff_iso)
    return sql, params


def _run(args) -> int:
    settings = get_settings()
    db_path = args.db or settings.nesty_db_path
    init_db(db_path)

    cutoff_iso = _iso_cutoff(args.older_than_days)
    conversation_id = str(args.conversation_id or "").strip() or None
    dry_run = not bool(args.apply)

    sql, params = _build_query(conversation_id=conversation_id, cutoff_iso=cutoff_iso)
    with get_connection(db_path) as conn:
        excluded_rows = conn.execute(sql, tuple(params)).fetchall()
        excluded_ids = [str(row["id"]) for row in excluded_rows]
        excluded_count = len(excluded_ids)
        embeddings_count = 0
        deleted_count = 0
        if args.delete_embeddings_for_excluded and excluded_ids:
            placeholders = ",".join("?" for _ in excluded_ids)
            embeddings_count_row = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM embedding_records
                WHERE owner_type = 'conversation_message'
                  AND owner_id IN ({placeholders})
                """,
                tuple(excluded_ids),
            ).fetchone()
            embeddings_count = int(embeddings_count_row["total"] or 0) if embeddings_count_row else 0

            if not dry_run:
                cursor = conn.execute(
                    f"""
                    DELETE FROM embedding_records
                    WHERE owner_type = 'conversation_message'
                      AND owner_id IN ({placeholders})
                    """,
                    tuple(excluded_ids),
                )
                deleted_count = int(cursor.rowcount or 0)
                conn.commit()

    print(f"dry_run: {dry_run}")
    print(f"apply: {bool(args.apply)}")
    print(f"delete_embeddings_for_excluded: {bool(args.delete_embeddings_for_excluded)}")
    print(f"conversation_id: {conversation_id or ''}")
    print(f"older_than_days: {args.older_than_days if args.older_than_days is not None else ''}")
    print(f"excluded_messages_count: {excluded_count}")
    print(f"excluded_with_embeddings_count: {embeddings_count}")
    print(f"deleted_embeddings_count: {deleted_count}")
    print("status: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup helper for semantic memory controls.")
    parser.add_argument("--db", type=str, default=None, help="Optional DB path override.")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Default mode is dry-run.")
    parser.add_argument("--delete-embeddings-for-excluded", action="store_true")
    parser.add_argument("--conversation-id", type=str, default=None)
    parser.add_argument("--older-than-days", type=int, default=None)
    args = parser.parse_args()
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
