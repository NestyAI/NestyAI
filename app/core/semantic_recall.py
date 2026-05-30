from __future__ import annotations

import hashlib
from difflib import SequenceMatcher
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
    "nhá»›",
    "trÆ°á»›c Ä‘Ã³",
    "lÃºc nÃ£y",
    "mÃ¬nh Ä‘Ã£ nÃ³i",
    "dá»±a trÃªn cuá»™c trÃ² chuyá»‡n",
]
_FOLLOWUP_HINTS = [
    "that",
    "this project",
    "continue",
    "tiáº¿p tá»¥c",
    "cÃ¡i Ä‘Ã³",
    "pháº§n Ä‘Ã³",
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


def _normalize_for_dedup(text: str) -> str:
    return normalize_embedding_text(text, max_chars=8000).strip().lower()


def _hash_normalized_content(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_summary_duplicate(content_normalized: str, summary_normalized: str, dedup_similarity: float) -> bool:
    if not content_normalized or not summary_normalized:
        return False
    if content_normalized in summary_normalized or summary_normalized in content_normalized:
        return True
    similarity = SequenceMatcher(a=content_normalized, b=summary_normalized).ratio()
    return similarity >= dedup_similarity


def _is_near_duplicate(
    content_normalized: str,
    existing_normalized: list[str],
    dedup_similarity: float,
) -> bool:
    for existing in existing_normalized:
        if content_normalized == existing:
            return True
        similarity = SequenceMatcher(a=content_normalized, b=existing).ratio()
        if similarity >= dedup_similarity:
            return True
    return False


async def retrieve_semantic_memories(
    latest_user_message: str,
    api_key_id: str | None,
    conversation_id: str | None,
    config,
    request_semantic_recall: str,
    exclude_message_ids: list[str] | None = None,
    summary_text: str | None = None,
    include_pinned_boost: bool = True,
) -> dict[str, Any]:
    requested = str(request_semantic_recall or "auto").strip().lower()
    top_k = max(1, int(getattr(config, "semantic_recall_top_k", 5)))
    min_score = float(getattr(config, "semantic_recall_min_score", 0.72))
    scope = str(getattr(config, "semantic_recall_scope", "conversation") or "conversation").strip().lower()
    pinned_boost = float(getattr(config, "semantic_recall_pinned_boost", 0.08))
    dedup_similarity = float(getattr(config, "semantic_recall_dedup_similarity", 0.96))
    max_per_conversation = max(1, int(getattr(config, "semantic_recall_max_per_conversation", 3)))
    exclude_memory_excluded = bool(getattr(config, "semantic_recall_exclude_memory_excluded", True))
    result: dict[str, Any] = {
        "enabled": bool(getattr(config, "semantic_recall_enabled", False)),
        "requested": requested,
        "used": False,
        "reason": "disabled_global",
        "query_embedded": False,
        "top_k": top_k,
        "min_score": min_score,
        "matches": [],
        "context_text": "",
        "pinned_matches_count": 0,
        "excluded_matches_count": 0,
        "deduped_count": 0,
        "max_score": None,
        "min_returned_score": None,
        "scope": scope,
        "candidate_count": 0,
        "used_context_chars": 0,
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

    include_roles = list(getattr(config, "semantic_recall_include_roles", ["user", "assistant"]) or [])
    include_roles = [str(role).strip().lower() for role in include_roles if str(role).strip()]
    candidate_limit = max(50, int(getattr(config, "semantic_recall_candidate_limit", 500)))
    similarity_top_k = max(top_k, candidate_limit)
    pre_filter_min = max(0.0, min_score - (pinned_boost if include_pinned_boost else 0.0))
    try:
        raw_matches = search_similar_embeddings(
            query_embedding=embedded.embedding,
            api_key_id=api_key_id,
            owner_type="conversation_message",
            conversation_id=conversation_id,
            scope=scope,
            top_k=similarity_top_k,
            min_score=pre_filter_min,
            include_roles=include_roles,
            exclude_owner_ids=exclude_message_ids or [],
            candidate_limit=candidate_limit,
            exclude_memory_excluded=exclude_memory_excluded,
        )
    except Exception:
        result["reason"] = "semantic_recall_failed"
        return result

    result["candidate_count"] = len(raw_matches)
    if not raw_matches:
        result["reason"] = "no_matches"
        return result

    exclude_ids = {str(item).strip() for item in (exclude_message_ids or []) if str(item).strip()}
    summary_normalized = _normalize_for_dedup(str(summary_text or ""))
    seen_message_ids: set[str] = set()
    seen_content_hashes: set[str] = set()
    kept_normalized_contents: list[str] = []
    per_conversation_count: dict[str, int] = {}
    normalized_matches: list[dict[str, Any]] = []
    deduped_count = 0
    excluded_matches_count = 0

    for item in raw_matches:
        message_id = str(item.get("owner_id") or "").strip()
        if not message_id:
            deduped_count += 1
            continue
        if message_id in exclude_ids or message_id in seen_message_ids:
            deduped_count += 1
            continue

        memory_excluded = bool(item.get("memory_excluded"))
        if memory_excluded:
            excluded_matches_count += 1
            deduped_count += 1
            continue

        content = str(item.get("content") or "")
        content_normalized = _normalize_for_dedup(content)
        if not content_normalized:
            deduped_count += 1
            continue
        if _is_summary_duplicate(content_normalized, summary_normalized, dedup_similarity):
            deduped_count += 1
            continue

        content_hash = _hash_normalized_content(content_normalized)
        if content_hash in seen_content_hashes:
            deduped_count += 1
            continue
        if _is_near_duplicate(content_normalized, kept_normalized_contents, dedup_similarity):
            deduped_count += 1
            continue

        conversation_key = str(item.get("conversation_id") or "")
        used_in_conversation = per_conversation_count.get(conversation_key, 0)
        if used_in_conversation >= max_per_conversation:
            deduped_count += 1
            continue

        raw_score = float(item.get("score") or 0.0)
        pinned = bool(item.get("memory_pinned"))
        boosted_score = raw_score
        if pinned and include_pinned_boost:
            boosted_score = min(1.0, raw_score + pinned_boost)
        if boosted_score < min_score:
            continue

        seen_message_ids.add(message_id)
        seen_content_hashes.add(content_hash)
        kept_normalized_contents.append(content_normalized)
        per_conversation_count[conversation_key] = used_in_conversation + 1
        normalized_matches.append(
            {
                "message_id": message_id,
                "conversation_id": conversation_key,
                "role": item.get("role"),
                "content": content,
                "score": boosted_score,
                "raw_score": raw_score,
                "pinned": pinned,
                "excluded": False,
                "tags": list(item.get("memory_tags") or []),
                "created_at": item.get("created_at"),
            }
        )

    if not normalized_matches:
        result.update(
            {
                "reason": "no_matches",
                "excluded_matches_count": excluded_matches_count,
                "deduped_count": deduped_count,
            }
        )
        return result

    normalized_matches.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    normalized_matches = normalized_matches[:top_k]
    pinned_matches_count = sum(1 for item in normalized_matches if bool(item.get("pinned")))
    max_score = max(float(item.get("score") or 0.0) for item in normalized_matches)
    min_returned_score = min(float(item.get("score") or 0.0) for item in normalized_matches)
    context_max_chars = max(1, int(getattr(config, "semantic_recall_max_context_chars", 4000)))
    context_text = _build_memory_context(normalized_matches, context_max_chars=context_max_chars)
    if not context_text:
        result.update(
            {
                "reason": "no_matches",
                "excluded_matches_count": excluded_matches_count,
                "deduped_count": deduped_count,
            }
        )
        return result

    result.update(
        {
            "used": True,
            "reason": "semantic_recall_enabled",
            "matches": normalized_matches,
            "context_text": context_text,
            "pinned_matches_count": pinned_matches_count,
            "excluded_matches_count": excluded_matches_count,
            "deduped_count": deduped_count,
            "max_score": max_score,
            "min_returned_score": min_returned_score,
            "scope": scope,
            "used_context_chars": len(context_text),
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
        pinned_text = " | pinned" if bool(item.get("pinned")) else ""
        block = (
            f"[Memory {index} | score={score:.2f}{pinned_text} | role={role} | date={created_at}]\n"
            f"{content}"
        )
        blocks.append(block)
    context = "\n\n".join(blocks).strip()
    if len(context) > context_max_chars:
        context = context[:context_max_chars].rstrip()
    return context
