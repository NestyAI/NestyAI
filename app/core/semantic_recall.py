from __future__ import annotations

from typing import Any

from app.core.embedding_service import generate_embedding, normalize_embedding_text
from app.core.errors import APIError
from app.storage.embeddings import count_embedding_records, search_similar_embeddings
from app.utils.logging import get_logger, log_safe


logger = get_logger("nesty.semantic_recall")

_MEMORY_KEYWORDS = [
    "what did i say earlier",
    "remember",
    "based on our previous conversation",
    "nhớ",
    "trước đó",
    "lúc nãy",
    "mình đã nói",
    "dựa trên cuộc trò chuyện",
]
_FOLLOWUP_HINTS = [
    "that",
    "this project",
    "continue",
    "tiếp tục",
    "cái đó",
    "phần đó",
]


def should_use_semantic_recall(request, model_config, context_metadata, config) -> dict[str, Any]:
    requested = str(getattr(request, "semantic_recall", "auto") or "auto").strip().lower()
    decision = {
        "enabled": bool(getattr(config, "semantic_recall_enabled", False)),
        "requested": requested,
        "should_use": False,
        "reason": "disabled_global",
    }
    if requested == "off":
        decision["reason"] = "request_off"
        return decision
    if not bool(getattr(config, "semantic_recall_enabled", False)):
        decision["reason"] = "disabled_global"
        return decision
    if not bool(getattr(request, "store", False)):
        decision["reason"] = "store_false"
        return decision
    if not str(getattr(request, "conversation_id", "") or "").strip():
        decision["reason"] = "no_conversation"
        return decision
    if not bool(getattr(config, "embeddings_enabled", False)):
        decision["reason"] = "embeddings_disabled"
        return decision

    if int(count_embedding_records()) <= 0:
        decision["reason"] = "no_embeddings"
        return decision

    if requested == "on":
        decision["should_use"] = True
        decision["reason"] = "semantic_recall_enabled"
        return decision

    latest_user_message = str((context_metadata or {}).get("latest_user_message") or "").strip().lower()
    behavior_profile = str((model_config or {}).get("behavior_profile") or "balanced").strip().lower()

    explicit_memory_request = any(keyword in latest_user_message for keyword in _MEMORY_KEYWORDS)
    followup_reference = any(keyword in latest_user_message for keyword in _FOLLOWUP_HINTS)

    if behavior_profile == "flash":
        should_use = explicit_memory_request
    elif behavior_profile == "pro":
        should_use = explicit_memory_request or followup_reference
    else:
        should_use = explicit_memory_request or (followup_reference and len(latest_user_message) >= 24)

    decision["should_use"] = bool(should_use)
    decision["reason"] = "semantic_recall_enabled" if should_use else "no_matches"
    return decision


def build_recall_query_text(messages: list[dict]) -> str:
    for item in reversed(messages):
        if str(item.get("role") or "").strip().lower() == "user":
            return normalize_embedding_text(str(item.get("content") or ""), max_chars=8000)
    if messages:
        return normalize_embedding_text(str(messages[-1].get("content") or ""), max_chars=8000)
    return ""


async def retrieve_semantic_memories(
    latest_user_message: str,
    api_key_id: str | None,
    conversation_id: str | None,
    config,
    request_semantic_recall: str,
    exclude_message_ids: list[str] | None = None,
) -> dict[str, Any]:
    requested = str(request_semantic_recall or "auto").strip().lower()
    result: dict[str, Any] = {
        "enabled": bool(getattr(config, "semantic_recall_enabled", False)),
        "requested": requested,
        "used": False,
        "reason": "disabled_global",
        "query_embedded": False,
        "top_k": int(getattr(config, "semantic_recall_top_k", 5)),
        "min_score": float(getattr(config, "semantic_recall_min_score", 0.72)),
        "matches": [],
        "context_text": "",
    }
    if not bool(getattr(config, "semantic_recall_enabled", False)):
        result["reason"] = "disabled_global"
        return result
    if not bool(getattr(config, "embeddings_enabled", False)):
        result["reason"] = "embeddings_disabled"
        return result

    query_text = normalize_embedding_text(
        latest_user_message,
        max_chars=max(1, int(getattr(config, "embeddings_max_input_chars", 8000))),
    )
    if not query_text:
        result["reason"] = "no_matches"
        return result

    try:
        embedded = await generate_embedding(query_text)
        result["query_embedded"] = True
    except APIError as exc:
        log_safe(
            logger,
            "semantic_recall_query_embedding_failed",
            reason="provider_failed",
            error_code=exc.code,
        )
        result["reason"] = "provider_failed"
        return result
    except Exception:
        result["reason"] = "provider_failed"
        return result

    scope = str(getattr(config, "semantic_recall_scope", "conversation") or "conversation").strip().lower()
    include_roles = list(getattr(config, "semantic_recall_include_roles", ["user", "assistant"]) or [])
    include_roles = [str(role).strip().lower() for role in include_roles if str(role).strip()]
    top_k = max(1, int(getattr(config, "semantic_recall_top_k", 5)))
    min_score = float(getattr(config, "semantic_recall_min_score", 0.72))
    try:
        matches = search_similar_embeddings(
            query_embedding=embedded.embedding,
            api_key_id=api_key_id,
            owner_type="conversation_message",
            conversation_id=conversation_id,
            scope=scope,
            top_k=top_k,
            min_score=min_score,
            include_roles=include_roles,
            exclude_owner_ids=exclude_message_ids or [],
            candidate_limit=max(50, int(getattr(config, "semantic_recall_candidate_limit", 500))),
        )
    except Exception:
        result["reason"] = "semantic_recall_failed"
        return result

    if not matches:
        result["reason"] = "no_matches"
        return result

    context_max_chars = max(1, int(getattr(config, "semantic_recall_max_context_chars", 4000)))
    context_text = _build_memory_context(matches, context_max_chars=context_max_chars)
    if not context_text:
        result["reason"] = "no_matches"
        return result

    normalized_matches = []
    for item in matches:
        normalized_matches.append(
            {
                "message_id": item.get("owner_id"),
                "conversation_id": item.get("conversation_id"),
                "role": item.get("role"),
                "content": item.get("content"),
                "score": float(item.get("score") or 0.0),
                "created_at": item.get("created_at"),
            }
        )
    result.update(
        {
            "used": True,
            "reason": "semantic_recall_enabled",
            "top_k": top_k,
            "min_score": min_score,
            "matches": normalized_matches,
            "context_text": context_text,
        }
    )
    return result


def _build_memory_context(matches: list[dict[str, Any]], context_max_chars: int) -> str:
    blocks: list[str] = []
    for index, item in enumerate(matches, start=1):
        score = float(item.get("score") or 0.0)
        role = str(item.get("role") or "unknown")
        created_at = str(item.get("created_at") or "")
        content = normalize_embedding_text(str(item.get("content") or ""), max_chars=600)
        if not content:
            continue
        block = (
            f"[Memory {index} | score={score:.2f} | role={role} | date={created_at}]\n"
            f"{content}"
        )
        blocks.append(block)
    context = "\n\n".join(blocks).strip()
    if len(context) > context_max_chars:
        context = context[:context_max_chars].rstrip()
    return context
