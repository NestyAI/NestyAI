from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.errors import APIError
from app.core.semantic_recall import retrieve_semantic_memories
from app.deps import get_settings
from app.storage.embeddings import count_embedding_records


def _build_effective_config(settings, scope: str, top_k: int, min_score: float):
    effective = type("RecallCfg", (), settings.model_dump() if hasattr(settings, "model_dump") else dict(settings.__dict__))()
    effective.semantic_recall_scope = scope
    effective.semantic_recall_top_k = int(top_k)
    effective.semantic_recall_min_score = float(min_score)
    return effective


def _preview_text(text: str, max_chars: int = 300) -> str:
    cleaned = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    if len(cleaned) > max_chars:
        return cleaned[:max_chars].rstrip() + "..."
    return cleaned


async def _run(args) -> int:
    settings = get_settings()
    query = str(args.query or "").strip()
    if not query:
        query = input("query: ").strip()
    if not query:
        print("status: missing_query")
        return 1

    if not settings.embeddings_enabled:
        print("status: embeddings_disabled")
        print("hint: set EMBEDDINGS_ENABLED=true")
        print("hint: set EMBEDDINGS_STORE_MESSAGE_EMBEDDINGS=true")
        print("hint: run scripts/rebuild_embeddings.py")
        return 0
    if int(count_embedding_records()) <= 0:
        print("status: no_embedding_records")
        print("hint: set EMBEDDINGS_STORE_MESSAGE_EMBEDDINGS=true")
        print("hint: run scripts/rebuild_embeddings.py")
        return 0

    scope = str(args.scope or settings.semantic_recall_scope or "conversation").strip().lower()
    if scope not in {"conversation", "api_key"}:
        print("status: invalid_scope")
        return 1

    top_k = int(args.top_k) if args.top_k is not None else int(settings.semantic_recall_top_k)
    min_score = float(args.min_score) if args.min_score is not None else float(settings.semantic_recall_min_score)
    effective_config = _build_effective_config(settings, scope=scope, top_k=top_k, min_score=min_score)

    try:
        recall = await retrieve_semantic_memories(
            latest_user_message=query,
            api_key_id=None,
            conversation_id=args.conversation_id,
            config=effective_config,
            request_semantic_recall="on",
            exclude_message_ids=[],
            include_pinned_boost=True,
        )
    except APIError as exc:
        print(f"status: memory_eval_failed")
        print(f"error_code: {exc.code}")
        return 1
    except Exception:
        print("status: memory_eval_failed")
        return 1

    matches = []
    for item in recall.get("matches") or []:
        row = {
            "message_id": item.get("message_id"),
            "conversation_id": item.get("conversation_id"),
            "role": item.get("role"),
            "score": float(item.get("score") or 0.0),
            "pinned": bool(item.get("pinned")),
            "excluded": bool(item.get("excluded")),
            "created_at": item.get("created_at"),
        }
        if args.show_content_preview:
            row["preview"] = _preview_text(str(item.get("content") or ""), max_chars=300)
        matches.append(row)

    payload = {
        "query": query,
        "provider": settings.embeddings_provider,
        "model": settings.embeddings_model,
        "scope": scope,
        "top_k": top_k,
        "min_score": min_score,
        "reason": str(recall.get("reason") or ""),
        "matches_count": len(matches),
        "pinned_matches_count": int(recall.get("pinned_matches_count") or 0),
        "excluded_matches_count": int(recall.get("excluded_matches_count") or 0),
        "deduped_count": int(recall.get("deduped_count") or 0),
        "candidate_count": int(recall.get("candidate_count") or 0),
        "max_score": recall.get("max_score"),
        "min_returned_score": recall.get("min_returned_score"),
        "matches": matches,
        "status": "ok",
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=True))
        return 0

    print(f"query: {payload['query']}")
    print(f"provider: {payload['provider']}")
    print(f"model: {payload['model']}")
    print(f"scope: {payload['scope']}")
    print(f"reason: {payload['reason']}")
    print(f"matches_count: {payload['matches_count']}")
    print(f"pinned_matches_count: {payload['pinned_matches_count']}")
    print(f"excluded_matches_count: {payload['excluded_matches_count']}")
    print(f"deduped_count: {payload['deduped_count']}")
    print(f"candidate_count: {payload['candidate_count']}")
    for idx, row in enumerate(matches, start=1):
        line = (
            f"- {idx}. message_id={row['message_id']} conversation_id={row['conversation_id']} "
            f"role={row['role']} score={row['score']:.3f} pinned={row['pinned']} excluded={row['excluded']} "
            f"created_at={row['created_at']}"
        )
        print(line)
        if args.show_content_preview:
            print(f"  preview={row.get('preview')}")
    print("status: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate semantic recall quality over local stored conversation memory.")
    parser.add_argument("--query", type=str, default=None)
    parser.add_argument("--conversation-id", type=str, default=None)
    parser.add_argument("--scope", type=str, default="conversation")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument("--show-content-preview", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
