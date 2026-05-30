from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.embedding_service import generate_and_store_embedding
from app.deps import get_settings
from app.storage.db import get_connection, init_db


async def _run(args) -> int:
    settings = get_settings()
    db_path = args.db or settings.nesty_db_path or os.getenv("NESTY_DB_PATH", "data/nesty.db")
    init_db(db_path)

    owner_type = str(args.owner_type or "conversation_message").strip()
    if owner_type != "conversation_message":
        print(f"owner_type: {owner_type}")
        print("status: unsupported_owner_type")
        return 1

    if not settings.embeddings_enabled:
        print(f"provider: {settings.embeddings_provider}")
        print(f"model: {settings.embeddings_model}")
        print("status: embeddings_disabled")
        return 0

    provider = settings.embeddings_provider
    model = settings.embeddings_model
    limit = int(args.limit) if args.limit is not None else max(1, int(settings.embeddings_backfill_batch_size))
    limit = max(1, limit)
    skip_excluded = bool(getattr(args, "skip_excluded", True))

    with get_connection(db_path) as conn:
        excluded_filter_sql = " AND COALESCE(m.memory_excluded, 0) = 0" if skip_excluded else ""
        rows = conn.execute(
            f"""
            SELECT m.id, m.conversation_id, m.role, m.content, c.api_key_id
            FROM conversation_messages m
            JOIN conversations c ON c.id = m.conversation_id
            LEFT JOIN embedding_records e
              ON e.owner_type = ? AND e.owner_id = m.id AND e.provider = ? AND e.model = ?
            WHERE e.id IS NULL
              {excluded_filter_sql}
            ORDER BY m.created_at ASC
            LIMIT ?
            """,
            (owner_type, provider, model, limit),
        ).fetchall()

    candidates = len(rows)
    embedded_count = 0
    skipped_count = 0
    failed_count = 0

    for row in rows:
        if args.dry_run:
            skipped_count += 1
            continue
        metadata: dict[str, Any] = {
            "conversation_id": str(row["conversation_id"] or ""),
            "role": str(row["role"] or ""),
            "backfill": True,
        }
        saved = await generate_and_store_embedding(
            owner_type=owner_type,
            owner_id=str(row["id"]),
            api_key_id=row["api_key_id"],
            text=str(row["content"] or ""),
            metadata=metadata,
        )
        if saved is None:
            failed_count += 1
        else:
            embedded_count += 1

    print(f"provider: {provider}")
    print(f"model: {model}")
    print(f"owner_type: {owner_type}")
    print(f"skip_excluded: {skip_excluded}")
    print(f"candidates_found: {candidates}")
    print(f"embedded_count: {embedded_count}")
    print(f"skipped_count: {skipped_count}")
    print(f"failed_count: {failed_count}")
    print("status: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill embedding records for conversation messages.")
    parser.add_argument("--db", type=str, default=None, help="Optional DB path override.")
    parser.add_argument("--owner-type", type=str, default="conversation_message")
    parser.add_argument("--limit", type=int, default=None)
    parser.set_defaults(skip_excluded=True)
    parser.add_argument("--skip-excluded", dest="skip_excluded", action="store_true")
    parser.add_argument("--include-excluded", dest="skip_excluded", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
