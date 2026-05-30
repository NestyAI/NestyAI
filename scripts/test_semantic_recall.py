from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.semantic_recall import retrieve_semantic_memories
from app.deps import get_settings


async def _run(args) -> int:
    settings = get_settings()
    if not settings.embeddings_enabled:
        print("status: embeddings_disabled")
        return 0
    if not settings.semantic_recall_enabled:
        print("status: semantic_recall_disabled")
        return 0

    original_top_k = settings.semantic_recall_top_k
    original_min_score = settings.semantic_recall_min_score
    try:
        if args.top_k is not None:
            settings.semantic_recall_top_k = int(args.top_k)
        if args.min_score is not None:
            settings.semantic_recall_min_score = float(args.min_score)
        result = await retrieve_semantic_memories(
            latest_user_message=args.text,
            api_key_id=args.api_key_id,
            conversation_id=args.conversation_id,
            config=settings,
            request_semantic_recall="on",
            exclude_message_ids=[],
        )
    finally:
        settings.semantic_recall_top_k = original_top_k
        settings.semantic_recall_min_score = original_min_score

    print(f"query_embedded: {bool(result.get('query_embedded'))}")
    print(f"reason: {str(result.get('reason') or '')}")
    matches = result.get("matches") or []
    print(f"matches_count: {len(matches)}")
    for idx, item in enumerate(matches, start=1):
        preview = str(item.get("content") or "").strip()
        if len(preview) > 160:
            preview = preview[:160].rstrip() + "..."
        print(
            f"- {idx}. score={float(item.get('score') or 0.0):.3f} "
            f"role={str(item.get('role') or '')} "
            f"conversation_id={str(item.get('conversation_id') or '')} "
            f"preview={preview}"
        )
    print("status: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Test semantic recall over local embedding records.")
    parser.add_argument("--text", type=str, required=True)
    parser.add_argument("--conversation-id", type=str, default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument("--api-key-id", type=str, default=None)
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
