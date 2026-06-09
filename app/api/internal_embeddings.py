from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

import app.deps as deps
from app.core.embedding_service import generate_embedding
from app.core.errors import APIError
from app.core.semantic_recall import retrieve_semantic_memories
from app.security.internal_auth import require_internal_admin


router = APIRouter(
    prefix="/internal/embeddings",
    tags=["internal-embeddings"],
    dependencies=[Depends(require_internal_admin)],
)


def get_settings():
    return deps.get_settings()


class InternalEmbeddingTestRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    provider: str | None = None
    model: str | None = None


class InternalRecallTestRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    scope: str = Field(default="conversation")
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float = Field(default=0.72, ge=0.0, le=1.0)
    api_key_id: str | None = None
    include_pinned_boost: bool = True


@router.post("/test")
async def test_embedding_provider(body: InternalEmbeddingTestRequest) -> dict:
    settings = get_settings()
    if not settings.embeddings_enabled:
        raise APIError(
            code="embedding_config_invalid",
            message="Embeddings are disabled.",
            status_code=400,
        )
    try:
        result = await generate_embedding(
            text=body.text,
            provider=body.provider,
            model=body.model,
        )
    except APIError:
        raise
    except Exception as exc:
        raise APIError(
            code="embedding_generation_failed",
            message="Failed to generate embedding.",
            status_code=502,
        ) from exc
    return {
        "ok": True,
        "provider": result.provider,
        "model": result.model,
        "dimensions": result.dimensions,
        "latency_ms": result.latency_ms,
    }


@router.post("/recall-test")
async def test_semantic_recall(body: InternalRecallTestRequest) -> dict:
    settings = get_settings()
    if not settings.semantic_recall_enabled:
        raise APIError(
            code="semantic_recall_unavailable",
            message="Semantic recall is disabled.",
            status_code=400,
        )

    scope = str(body.scope or settings.semantic_recall_scope or "conversation").strip().lower()
    if scope not in {"conversation", "api_key", "all_accessible"}:
        raise APIError(
            code="semantic_recall_failed",
            message="Invalid semantic recall scope.",
            status_code=400,
        )

    effective_config = type("RecallCfg", (), settings.model_dump() if hasattr(settings, "model_dump") else dict(settings.__dict__))()
    effective_config.semantic_recall_scope = scope
    effective_config.semantic_recall_top_k = int(body.top_k)
    effective_config.semantic_recall_min_score = float(body.min_score)
    try:
        recall = await retrieve_semantic_memories(
            latest_user_message=body.text,
            api_key_id=body.api_key_id,
            conversation_id=body.conversation_id,
            config=effective_config,
            request_semantic_recall="on",
            exclude_message_ids=[],
            include_pinned_boost=bool(body.include_pinned_boost),
        )
    except Exception as exc:
        raise APIError(
            code="memory_eval_failed",
            message="Failed to evaluate semantic recall.",
            status_code=500,
        ) from exc

    matches = []
    for item in recall.get("matches") or []:
        if bool(item.get("excluded")):
            continue
        preview = str(item.get("content") or "").strip()
        if len(preview) > 200:
            preview = preview[:200].rstrip() + "..."
        matches.append(
            {
                "message_id": item.get("message_id"),
                "conversation_id": item.get("conversation_id"),
                "role": item.get("role"),
                "score": float(item.get("score") or 0.0),
                "raw_score": (
                    float(item.get("raw_score") or 0.0)
                    if body.include_pinned_boost and item.get("raw_score") is not None
                    else None
                ),
                "pinned": bool(item.get("pinned")),
                "excluded": False,
                "tags": list(item.get("tags") or []),
                "content_preview": preview,
            }
        )
    return {
        "ok": True,
        "query_embedded": bool(recall.get("query_embedded")),
        "reason": str(recall.get("reason") or ""),
        "scope": str(recall.get("scope") or scope),
        "matches_count": len(matches),
        "pinned_matches_count": int(recall.get("pinned_matches_count") or 0),
        "excluded_matches_count": int(recall.get("excluded_matches_count") or 0),
        "deduped_count": int(recall.get("deduped_count") or 0),
        "candidate_count": int(recall.get("candidate_count") or 0),
        "max_score": recall.get("max_score"),
        "min_returned_score": recall.get("min_returned_score"),
        "matches": matches,
    }
