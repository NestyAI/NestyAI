from __future__ import annotations

import hashlib
from typing import Any

from app.core.errors import APIError, MissingAPIKeyError, ProviderError
from app.embeddings.provider import build_embedding_provider, sanitize_embedding_usage
from app.schemas.embeddings import EmbeddingResult
from app.storage.embeddings import upsert_embedding_record
from app.utils.logging import get_logger, log_safe


logger = get_logger("nesty.embedding_service")


def get_settings():
    from app.deps import get_settings as deps_get_settings

    return deps_get_settings()


def normalize_embedding_text(text: str, max_chars: int) -> str:
    normalized = " ".join(str(text or "").replace("\r", " ").split())
    if max_chars <= 0:
        return normalized
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip()


def hash_embedding_content(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def generate_embedding(
    text: str,
    provider: str | None = None,
    model: str | None = None,
) -> EmbeddingResult:
    settings = get_settings()
    provider_name = str(provider or settings.embeddings_provider or "").strip().lower()
    model_name = str(model or settings.embeddings_model or "").strip()
    if not provider_name or not model_name:
        raise APIError(
            code="embedding_config_invalid",
            message="Embeddings provider/model is not configured.",
            status_code=400,
        )

    normalized = normalize_embedding_text(text, max(1, int(settings.embeddings_max_input_chars)))
    if not normalized:
        raise APIError(
            code="embedding_config_invalid",
            message="Embedding input text is empty after normalization.",
            status_code=400,
        )

    provider_client = build_embedding_provider(settings=settings, provider_name=provider_name)
    try:
        result = await provider_client.embed_text(text=normalized, model=model_name)
    except MissingAPIKeyError as exc:
        raise APIError(
            code="embedding_provider_unavailable",
            message="Embedding provider API key is missing.",
            status_code=503,
            details={"provider": provider_name},
        ) from exc
    except ProviderError as exc:
        raise APIError(
            code="embedding_provider_unavailable",
            message="Embedding provider is unavailable.",
            status_code=502,
            details={"provider": provider_name},
        ) from exc

    usage = sanitize_embedding_usage(result.usage)
    dimensions = int(result.dimensions or len(result.embedding) or 0)
    if dimensions <= 0:
        raise APIError(
            code="embedding_generation_failed",
            message="Embedding provider returned invalid vector.",
            status_code=502,
        )
    return EmbeddingResult(
        provider=result.provider,
        model=result.model,
        embedding=[float(item) for item in result.embedding],
        dimensions=dimensions,
        usage=usage,
        latency_ms=result.latency_ms,
    )


async def generate_and_store_embedding(
    owner_type: str,
    owner_id: str,
    api_key_id: str | None,
    text: str,
    metadata: dict | None = None,
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.embeddings_enabled:
        return None

    normalized = normalize_embedding_text(text, max(1, int(settings.embeddings_max_input_chars)))
    if not normalized:
        return None
    content_hash = hash_embedding_content(normalized)
    try:
        result = await generate_embedding(
            text=normalized,
            provider=settings.embeddings_provider,
            model=settings.embeddings_model,
        )
    except APIError as exc:
        log_safe(
            logger,
            "embedding_generation_failed",
            owner_type=owner_type,
            owner_id=owner_id,
            provider=settings.embeddings_provider,
            model=settings.embeddings_model,
            error_code=exc.code,
        )
        return None

    try:
        saved = upsert_embedding_record(
            owner_type=owner_type,
            owner_id=owner_id,
            api_key_id=api_key_id,
            provider=result.provider,
            model=result.model,
            embedding=result.embedding,
            content_hash=content_hash,
            metadata=metadata,
        )
    except Exception:
        log_safe(
            logger,
            "embedding_storage_failed",
            owner_type=owner_type,
            owner_id=owner_id,
            provider=result.provider,
            model=result.model,
            error_code="embedding_storage_failed",
        )
        return None
    return saved


async def maybe_embed_conversation_message(message: dict, api_key_id: str | None) -> dict | None:
    settings = get_settings()
    if not settings.embeddings_enabled:
        return None
    if not settings.embeddings_store_message_embeddings:
        return None
    if not isinstance(message, dict):
        return None
    owner_id = str(message.get("id") or "").strip()
    content = str(message.get("content") or "")
    if not owner_id or not content.strip():
        return None
    metadata = {
        "conversation_id": str(message.get("conversation_id") or ""),
        "role": str(message.get("role") or ""),
        "created_at": str(message.get("created_at") or ""),
    }
    try:
        return await generate_and_store_embedding(
            owner_type="conversation_message",
            owner_id=owner_id,
            api_key_id=api_key_id,
            text=content,
            metadata=metadata,
        )
    except Exception:
        # Embedding is best-effort and must never break chat flow.
        return None
