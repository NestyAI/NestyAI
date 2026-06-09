from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Request

import app.deps as deps
from app.core.conversation_summarizer import summarize_conversation
from app.core.errors import APIError
from app.security.auth import AuthContext, optional_api_key, require_api_key
from app.storage.conversations import (
    archive_conversation,
    clear_conversation_messages,
    count_messages,
    export_conversation,
    get_conversation,
    get_conversation_stats,
    get_recent_messages,
    list_memory_controlled_messages,
    list_conversations,
    list_messages,
    update_message_memory_controls,
    reset_conversation_summary,
    search_conversations,
    search_messages,
    update_conversation_title,
)


router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


def get_settings():
    return deps.get_settings()


def get_orchestrator():
    return deps.get_orchestrator()


class UpdateConversationTitleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ClearConversationRequest(BaseModel):
    keep_summary: bool = False


class UpdateMessageMemoryRequest(BaseModel):
    pinned: bool | None = None
    excluded: bool | None = None
    tags: list[str] | None = None


def _resolve_auth_context(settings, request: Request) -> AuthContext | None:
    if settings.require_api_key:
        return require_api_key(request)
    return optional_api_key(request)


def _conversation_accessible(settings, conversation: dict | None, auth_context: AuthContext | None) -> bool:
    if conversation is None:
        return False
    if conversation.get("archived_at"):
        return False

    owner = conversation.get("api_key_id")
    if settings.require_api_key:
        return bool(auth_context and owner == auth_context.api_key_id)

    if owner is None:
        return True
    if auth_context is None:
        return False
    return owner == auth_context.api_key_id


def _validate_limit_offset(limit: int, offset: int) -> tuple[int, int]:
    if offset < 0:
        raise APIError(
            code="invalid_conversation_request",
            message="Invalid pagination offset.",
            status_code=400,
        )
    if limit < 1 or limit > 100:
        raise APIError(
            code="invalid_conversation_request",
            message="Invalid pagination limit.",
            status_code=400,
        )
    return limit, offset


def _validate_query(query: str) -> str:
    cleaned = query.strip()
    if not cleaned:
        raise APIError(
            code="invalid_conversation_request",
            message="Search query must not be empty.",
            status_code=400,
        )
    if len(cleaned) > 200:
        raise APIError(
            code="invalid_conversation_request",
            message="Search query is too long.",
            status_code=400,
        )
    return cleaned


def _validate_memory_filters(pinned: bool | None, excluded: bool | None) -> tuple[bool | None, bool | None]:
    if pinned is not None:
        pinned = bool(pinned)
    if excluded is not None:
        excluded = bool(excluded)
    return pinned, excluded


@router.get("")
async def get_conversations(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    archived: str = "active",
    q: str | None = None,
) -> dict:
    settings = get_settings()
    auth_context = _resolve_auth_context(settings, request)
    api_key_id = auth_context.api_key_id if auth_context else None
    limit, offset = _validate_limit_offset(limit, offset)

    archived_mode = archived.strip().lower()
    if archived_mode not in {"active", "archived", "all"}:
        raise APIError(
            code="invalid_conversation_request",
            message="Invalid archived filter.",
            status_code=400,
        )

    query = q.strip() if q else ""
    if q is not None:
        if not query:
            raise APIError(
                code="invalid_conversation_request",
                message="Search query must not be empty.",
                status_code=400,
            )
        if len(query) > 200:
            raise APIError(
                code="invalid_conversation_request",
                message="Search query is too long.",
                status_code=400,
            )

    items = list_conversations(
        api_key_id=api_key_id,
        limit=limit,
        offset=offset,
        archived=archived_mode,
        q=query or None,
        db_path=settings.nesty_db_path,
    )
    with_counts = []
    for item in items:
        stats = get_conversation_stats(str(item["id"]), db_path=settings.nesty_db_path)
        with_counts.append(
            {
                "id": item["id"],
                "title": item["title"],
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
                "archived_at": item.get("archived_at"),
                "message_count": int(stats.get("message_count") or 0),
                "last_message_at": stats.get("last_message_at"),
                "summary_exists": bool(item.get("summary_exists")),
                "summary_updated_at": item.get("summary_updated_at"),
                "summary_message_count": int(item.get("summary_message_count") or 0),
            }
        )
    return {"object": "list", "data": with_counts}


@router.get("/memory-controls")
async def get_memory_controls(
    request: Request,
    pinned: bool | None = None,
    excluded: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    settings = get_settings()
    auth_context = _resolve_auth_context(settings, request)
    api_key_id = auth_context.api_key_id if auth_context else None
    limit, offset = _validate_limit_offset(limit, offset)
    pinned, excluded = _validate_memory_filters(pinned, excluded)

    rows = list_memory_controlled_messages(
        api_key_id=api_key_id,
        pinned=pinned,
        excluded=excluded,
        limit=limit + 1,
        offset=offset,
        db_path=settings.nesty_db_path,
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "object": "list",
        "data": rows,
        "filters": {
            "pinned": pinned,
            "excluded": excluded,
        },
        "pagination": {
            "limit": limit,
            "offset": offset,
            "count": len(rows),
            "has_more": has_more,
        },
    }


@router.get("/search")
async def search_conversations_endpoint(
    request: Request,
    q: str,
    limit: int = 20,
    offset: int = 0,
    scope: str = "all",
    backend: str = "auto",
) -> dict:
    settings = get_settings()
    auth_context = _resolve_auth_context(settings, request)
    api_key_id = auth_context.api_key_id if auth_context else None
    limit, offset = _validate_limit_offset(limit, offset)
    query = _validate_query(q)

    scope_mode = scope.strip().lower()
    if scope_mode not in {"conversations", "messages", "all"}:
        raise APIError(
            code="invalid_conversation_request",
            message="Invalid search scope.",
            status_code=400,
        )
    backend_mode = backend.strip().lower()
    if backend_mode not in {"auto", "fts", "like"}:
        raise APIError(
            code="invalid_search_backend",
            message="Search backend must be one of: auto, fts, like.",
            status_code=400,
        )

    conversations_data: list[dict] = []
    messages_data: list[dict] = []
    has_more = False
    message_backend_used = "like"
    message_fallback_used = False

    if scope_mode in {"conversations", "all"}:
        rows = search_conversations(
            api_key_id=api_key_id,
            query=query,
            limit=limit + 1,
            offset=offset,
            include_archived=False,
            db_path=settings.nesty_db_path,
        )
        has_more = has_more or len(rows) > limit
        conversations_data = rows[:limit]

    if scope_mode in {"messages", "all"}:
        try:
            message_result = search_messages(
                api_key_id=api_key_id,
                query=query,
                limit=limit + 1,
                offset=offset,
                backend=backend_mode,
                db_path=settings.nesty_db_path,
            )
        except ValueError:
            raise APIError(
                code="invalid_search_backend",
                message="Search backend must be one of: auto, fts, like.",
                status_code=400,
            )
        except RuntimeError as exc:
            if str(exc) == "fts_unavailable":
                raise APIError(
                    code="fts_unavailable",
                    message="SQLite FTS5 search is not available.",
                    status_code=503,
                )
            raise

        rows = message_result["data"]
        has_more = has_more or len(rows) > limit
        messages_data = rows[:limit]
        message_backend_used = str(message_result.get("backend") or "like")
        message_fallback_used = bool(message_result.get("fallback_used"))

    return {
        "object": "conversation.search_results",
        "query": query,
        "conversations": conversations_data,
        "messages": messages_data,
        "search": {
            "backend": message_backend_used if scope_mode in {"messages", "all"} else backend_mode,
            "fallback_used": message_fallback_used if scope_mode in {"messages", "all"} else False,
            "query": query,
            "scope": scope_mode,
        },
        "pagination": {
            "limit": limit,
            "offset": offset,
            "count": len(conversations_data) + len(messages_data),
            "has_more": has_more,
        },
    }


@router.patch("/{conversation_id}/messages/{message_id}/memory")
async def patch_message_memory_controls(
    request: Request,
    conversation_id: str,
    message_id: str,
    body: UpdateMessageMemoryRequest,
) -> dict:
    settings = get_settings()
    auth_context = _resolve_auth_context(settings, request)
    conversation = get_conversation(conversation_id, db_path=settings.nesty_db_path)
    if not _conversation_accessible(settings, conversation, auth_context):
        raise APIError(
            code="conversation_not_found",
            message="Conversation not found.",
            status_code=404,
        )

    if body.pinned is True and body.excluded is True:
        raise APIError(
            code="invalid_memory_control_request",
            message="Message memory cannot be pinned and excluded at the same time.",
            status_code=400,
        )

    api_key_id = auth_context.api_key_id if auth_context else None
    try:
        updated = update_message_memory_controls(
            message_id=message_id,
            conversation_id=conversation_id,
            api_key_id=api_key_id,
            pinned=body.pinned,
            excluded=body.excluded,
            tags=body.tags,
            db_path=settings.nesty_db_path,
        )
    except Exception as exc:
        raise APIError(
            code="memory_control_update_failed",
            message="Failed to update message memory controls.",
            status_code=500,
        ) from exc

    if updated is None:
        raise APIError(
            code="conversation_not_found",
            message="Conversation not found.",
            status_code=404,
        )

    return {
        "ok": True,
        "message": {
            "id": updated["id"],
            "memory_pinned": bool(updated.get("memory_pinned")),
            "memory_excluded": bool(updated.get("memory_excluded")),
            "memory_tags": list(updated.get("memory_tags") or []),
            "memory_updated_at": updated.get("memory_updated_at"),
        },
    }


@router.get("/{conversation_id}/messages")
async def get_conversation_messages(
    request: Request,
    conversation_id: str,
    limit: int = 50,
    offset: int = 0,
    order: str = "asc",
) -> dict:
    settings = get_settings()
    auth_context = _resolve_auth_context(settings, request)
    limit, offset = _validate_limit_offset(limit, offset)

    order_mode = order.strip().lower()
    if order_mode not in {"asc", "desc"}:
        raise APIError(
            code="invalid_conversation_request",
            message="Invalid messages order.",
            status_code=400,
        )

    conversation = get_conversation(conversation_id, db_path=settings.nesty_db_path)
    if not _conversation_accessible(settings, conversation, auth_context):
        raise APIError(
            code="conversation_not_found",
            message="Conversation not found.",
            status_code=404,
        )

    rows = list_messages(
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
        order=order_mode,
        db_path=settings.nesty_db_path,
    )
    total = count_messages(conversation_id=conversation_id, db_path=settings.nesty_db_path)
    return {
        "object": "list",
        "conversation_id": conversation_id,
        "data": rows,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "count": len(rows),
            "has_more": (offset + len(rows)) < total,
        },
    }


@router.get("/{conversation_id}")
async def get_conversation_detail(request: Request, conversation_id: str, limit: int = 20) -> dict:
    settings = get_settings()
    auth_context = _resolve_auth_context(settings, request)
    if limit < 1 or limit > 200:
        raise APIError(
            code="invalid_conversation_request",
            message="Invalid messages limit.",
            status_code=400,
        )

    conversation = get_conversation(conversation_id, db_path=settings.nesty_db_path)
    if not _conversation_accessible(settings, conversation, auth_context):
        raise APIError(
            code="conversation_not_found",
            message="Conversation not found.",
            status_code=404,
        )

    messages = get_recent_messages(
        conversation_id=conversation_id,
        limit=limit,
        db_path=settings.nesty_db_path,
    )
    stats = get_conversation_stats(conversation_id, db_path=settings.nesty_db_path)
    return {
        "conversation": {
            "id": conversation["id"],
            "title": conversation["title"],
            "created_at": conversation["created_at"],
            "updated_at": conversation["updated_at"],
            "archived_at": conversation.get("archived_at"),
            "message_count": int(stats.get("message_count") or 0),
            "last_message_at": stats.get("last_message_at"),
            "summary_exists": bool(str(conversation.get("summary") or "").strip()),
            "summary": conversation.get("summary"),
            "summary_updated_at": conversation.get("summary_updated_at"),
            "summary_message_count": int(conversation.get("summary_message_count") or 0),
        },
        "messages": [
            {
                "id": item["id"],
                "role": item["role"],
                "content": item["content"],
                "model": item["model"],
                "provider": item["provider"],
                "created_at": item["created_at"],
            }
            for item in messages
        ],
    }


@router.delete("/{conversation_id}")
async def delete_conversation(request: Request, conversation_id: str) -> dict:
    settings = get_settings()
    auth_context = _resolve_auth_context(settings, request)
    api_key_id = auth_context.api_key_id if auth_context else None

    ok = archive_conversation(
        conversation_id=conversation_id,
        api_key_id=api_key_id,
        db_path=settings.nesty_db_path,
    )
    if not ok:
        raise APIError(
            code="conversation_not_found",
            message="Conversation not found.",
            status_code=404,
        )
    return {"ok": True}


@router.patch("/{conversation_id}")
async def patch_conversation_title(request: Request, conversation_id: str, body: UpdateConversationTitleRequest) -> dict:
    settings = get_settings()
    auth_context = _resolve_auth_context(settings, request)
    api_key_id = auth_context.api_key_id if auth_context else None

    ok = update_conversation_title(
        conversation_id=conversation_id,
        title=body.title.strip(),
        api_key_id=api_key_id,
        db_path=settings.nesty_db_path,
    )
    if not ok:
        raise APIError(
            code="conversation_not_found",
            message="Conversation not found.",
            status_code=404,
        )
    return {"ok": True}


@router.post("/{conversation_id}/summarize")
async def summarize_conversation_endpoint(request: Request, conversation_id: str) -> dict:
    settings = get_settings()
    auth_context = _resolve_auth_context(settings, request)
    conversation = get_conversation(conversation_id, db_path=settings.nesty_db_path)
    if not _conversation_accessible(settings, conversation, auth_context):
        raise APIError(
            code="conversation_not_found",
            message="Conversation not found.",
            status_code=404,
        )

    stats = get_conversation_stats(conversation_id=conversation_id, db_path=settings.nesty_db_path)
    if int(stats.get("message_count") or 0) <= 0:
        return {"ok": True, "summary_updated": False, "summary_message_count": 0}

    orchestrator = get_orchestrator()
    router = getattr(orchestrator, "router", None)
    if router is None:
        raise APIError(
            code="conversation_summary_failed",
            message="Conversation summarization failed.",
            status_code=500,
        )

    try:
        updated_summary = await summarize_conversation(
            conversation_id=conversation_id,
            router=router,
            config=settings,
            api_key_context=auth_context,
            force=True,
            raise_on_error=True,
        )
    except Exception:
        raise APIError(
            code="conversation_summary_failed",
            message="Conversation summarization failed.",
            status_code=502,
        )

    refreshed = get_conversation(conversation_id, db_path=settings.nesty_db_path) or {}
    return {
        "ok": True,
        "summary_updated": bool(updated_summary),
        "summary_message_count": int(refreshed.get("summary_message_count") or 0),
    }


@router.post("/{conversation_id}/clear")
async def clear_conversation_endpoint(request: Request, conversation_id: str, body: ClearConversationRequest) -> dict:
    settings = get_settings()
    auth_context = _resolve_auth_context(settings, request)
    api_key_id = auth_context.api_key_id if auth_context else None

    ok = clear_conversation_messages(
        conversation_id=conversation_id,
        api_key_id=api_key_id,
        keep_summary=bool(body.keep_summary),
        db_path=settings.nesty_db_path,
    )
    if not ok:
        raise APIError(
            code="conversation_not_found",
            message="Conversation not found.",
            status_code=404,
        )
    return {"ok": True}


@router.post("/{conversation_id}/reset-summary")
async def reset_summary_endpoint(request: Request, conversation_id: str) -> dict:
    settings = get_settings()
    auth_context = _resolve_auth_context(settings, request)
    api_key_id = auth_context.api_key_id if auth_context else None

    ok = reset_conversation_summary(
        conversation_id=conversation_id,
        api_key_id=api_key_id,
        db_path=settings.nesty_db_path,
    )
    if not ok:
        raise APIError(
            code="conversation_not_found",
            message="Conversation not found.",
            status_code=404,
        )
    return {"ok": True}


@router.get("/{conversation_id}/export")
async def export_conversation_endpoint(
    request: Request,
    conversation_id: str,
    include_metadata: bool = True,
    messages_order: str = "asc",
) -> dict:
    settings = get_settings()
    auth_context = _resolve_auth_context(settings, request)
    api_key_id = auth_context.api_key_id if auth_context else None

    order_mode = messages_order.strip().lower()
    if order_mode not in {"asc", "desc"}:
        raise APIError(
            code="invalid_conversation_request",
            message="Invalid export message order.",
            status_code=400,
        )

    exported = export_conversation(
        conversation_id=conversation_id,
        api_key_id=api_key_id,
        include_metadata=include_metadata,
        messages_order=order_mode,
        db_path=settings.nesty_db_path,
    )
    if exported is None:
        raise APIError(
            code="conversation_not_found",
            message="Conversation not found.",
            status_code=404,
        )
    return exported
