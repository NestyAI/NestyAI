from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

import app.deps as deps
from app.core.conversation_summarizer import summarize_conversation
from app.core.embedding_service import maybe_embed_conversation_message
from app.core.errors import APIError
from app.guards.input_guard import InputGuard
from app.schemas.chat import AuthDebugInfo, ChatCompletionRequest, ChatCompletionResponse, ChatMessage, ConversationInfo
from app.security.auth import AuthContext, optional_api_key, require_api_key
from app.security.rate_limit import build_rate_limit_key, get_rate_limiter
from app.storage.conversations import (
    add_message,
    get_conversation_summary,
    get_messages_after_summary,
    create_conversation,
    get_conversation,
    get_recent_messages,
)
from app.storage.usage import count_daily_requests, count_monthly_requests, insert_usage_log
from app.utils.ids import generate_request_id


router = APIRouter(prefix="/v1", tags=["chat"])


def get_settings():
    return deps.get_settings()


def get_guard_rules():
    return deps.get_guard_rules()


def get_orchestrator():
    return deps.get_orchestrator()


@router.post("/chat/completions", response_model=ChatCompletionResponse, response_model_exclude_none=True)
async def chat_completions(request: ChatCompletionRequest, raw_request: Request) -> ChatCompletionResponse | StreamingResponse:
    settings = get_settings()
    orchestrator = get_orchestrator()
    request_id = generate_request_id()

    started_at = time.perf_counter()
    auth_context: AuthContext | None = None
    conversation_id: str | None = None
    conversation_created = False
    conversation_summary_mode = "auto"
    conversation_summary_used = False
    sanitized_user_for_storage = ""
    try:
        auth_context = _apply_pre_chat_checks(settings=settings, request=request, raw_request=raw_request)
        (
            request,
            conversation_id,
            conversation_created,
            conversation_summary_mode,
            conversation_summary_used,
            sanitized_user_for_storage,
        ) = _prepare_conversation_context(settings=settings, request=request, auth_context=auth_context)
    except APIError as exc:
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        _safe_log_usage(
            settings=settings,
            auth_context=auth_context,
            request_id=request_id,
            model=request.model,
            provider="",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            tools_used=[],
            search_used=False,
            latency_ms=latency_ms,
            status="error",
            error_code=exc.code,
            conversation_id=conversation_id,
        )
        raise

    if request.stream:
        try:
            if request.store and conversation_id and sanitized_user_for_storage:
                user_message = add_message(
                    conversation_id=conversation_id,
                    role="user",
                    content=sanitized_user_for_storage,
                    model=request.model,
                    provider=None,
                    metadata={"request_id": request_id, "stream": True},
                    db_path=settings.nesty_db_path,
                )
                await _best_effort_embed_message(
                    message=user_message,
                    api_key_id=auth_context.api_key_id if auth_context else None,
                )
            stream_handle = await orchestrator.create_chat_completion_stream(request_id=request_id, request=request)
        except APIError as exc:
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            _safe_log_usage(
                settings=settings,
                auth_context=auth_context,
                request_id=request_id,
                model=request.model,
                provider="",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                tools_used=[],
                search_used=False,
                latency_ms=latency_ms,
                status="error",
                error_code=exc.code,
                conversation_id=conversation_id,
            )
            raise

        async def streaming_body():
            try:
                async for event in stream_handle.events:
                    yield event
            finally:
                latency_ms = int((time.perf_counter() - started_at) * 1000)
                _safe_log_usage(
                    settings=settings,
                    auth_context=auth_context,
                    request_id=request_id,
                    model=request.model,
                    provider=stream_handle.outcome.provider,
                    prompt_tokens=stream_handle.outcome.usage.prompt_tokens,
                    completion_tokens=stream_handle.outcome.usage.completion_tokens,
                    total_tokens=stream_handle.outcome.usage.total_tokens,
                    tools_used=stream_handle.outcome.tools.used,
                    search_used=bool(getattr(stream_handle.outcome.tools.search, "used", stream_handle.outcome.tools.search.enabled)),
                    latency_ms=latency_ms,
                    status=stream_handle.outcome.status,
                    error_code=stream_handle.outcome.error_code or None,
                    conversation_id=conversation_id,
                )
                if (
                    request.store
                    and conversation_id
                    and stream_handle.outcome.status == "success"
                    and stream_handle.outcome.assistant_content.strip()
                ):
                    assistant_message = add_message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=stream_handle.outcome.assistant_content,
                        model=request.model,
                        provider=stream_handle.outcome.provider,
                        metadata={"request_id": request_id, "stream": True},
                        db_path=settings.nesty_db_path,
                    )
                    await _best_effort_embed_message(
                        message=assistant_message,
                        api_key_id=auth_context.api_key_id if auth_context else None,
                    )
                    _ = await _maybe_run_conversation_summary(
                        settings=settings,
                        orchestrator=orchestrator,
                        conversation_id=conversation_id,
                        auth_context=auth_context,
                        summary_mode=conversation_summary_mode,
                    )

        return StreamingResponse(
            streaming_body(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    status = "error"
    error_code = ""
    provider = ""
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    tools_used: list[str] = []
    search_used = False
    try:
        response = await orchestrator.create_chat_completion(request_id=request_id, request=request)
        provider = response.provider
        prompt_tokens = response.usage.prompt_tokens
        completion_tokens = response.usage.completion_tokens
        total_tokens = response.usage.total_tokens
        tools_used = response.tools.used
        search_used = bool(getattr(response.tools.search, "used", response.tools.search.enabled))
        status = "success"

        if request.store and conversation_id:
            user_message = add_message(
                conversation_id=conversation_id,
                role="user",
                content=sanitized_user_for_storage,
                model=request.model,
                provider=None,
                metadata={"request_id": request_id, "stream": False},
                db_path=settings.nesty_db_path,
            )
            await _best_effort_embed_message(
                message=user_message,
                api_key_id=auth_context.api_key_id if auth_context else None,
            )
            assistant_content = response.choices[0].message.content if response.choices else ""
            summary_updated = False
            if assistant_content.strip():
                assistant_message = add_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=assistant_content,
                    model=request.model,
                    provider=response.provider,
                    metadata={"request_id": request_id, "stream": False},
                    db_path=settings.nesty_db_path,
                )
                await _best_effort_embed_message(
                    message=assistant_message,
                    api_key_id=auth_context.api_key_id if auth_context else None,
                )
                summary_updated = await _maybe_run_conversation_summary(
                    settings=settings,
                    orchestrator=orchestrator,
                    conversation_id=conversation_id,
                    auth_context=auth_context,
                    summary_mode=conversation_summary_mode,
                )
            response.conversation = ConversationInfo(
                id=conversation_id,
                created=conversation_created,
                summary_mode=conversation_summary_mode,
                summary_used=conversation_summary_used,
                summary_updated=summary_updated,
            )

        if settings.safe_debug_auth and auth_context is not None:
            response.auth = AuthDebugInfo(api_key_id=auth_context.api_key_id, key_name=auth_context.name)
        return response
    except APIError as exc:
        error_code = exc.code
        raise
    finally:
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        _safe_log_usage(
            settings=settings,
            auth_context=auth_context,
            request_id=request_id,
            model=request.model,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            tools_used=tools_used,
            search_used=search_used,
            latency_ms=latency_ms,
            status=status,
            error_code=error_code or None,
            conversation_id=conversation_id,
        )


def _apply_pre_chat_checks(settings, request: ChatCompletionRequest, raw_request: Request) -> AuthContext | None:
    if settings.require_api_key:
        auth_context = require_api_key(raw_request)
    else:
        auth_context = optional_api_key(raw_request)

    if auth_context and auth_context.allowed_models and request.model not in auth_context.allowed_models:
        raise APIError(
            code="model_not_allowed",
            message="This API key is not allowed to use the requested model.",
            status_code=403,
        )

    if settings.rate_limit_enabled:
        limit_key = build_rate_limit_key(raw_request, auth_context)
        limiter = get_rate_limiter()
        rate_limit = limiter.check(limit_key, settings.rate_limit_requests_per_minute)
        if not rate_limit.allowed:
            raise APIError(
                code="rate_limit_exceeded",
                message="Rate limit exceeded. Please try again later.",
                status_code=429,
                headers={"Retry-After": str(rate_limit.retry_after_seconds)},
                details={"retry_after_seconds": rate_limit.retry_after_seconds},
            )

    if auth_context and auth_context.daily_limit is not None:
        used_today = count_daily_requests(settings.nesty_db_path, auth_context.api_key_id)
        if used_today >= auth_context.daily_limit:
            raise APIError(
                code="daily_quota_exceeded",
                message="Daily request quota exceeded.",
                status_code=429,
            )

    if auth_context and auth_context.monthly_limit is not None:
        used_this_month = count_monthly_requests(settings.nesty_db_path, auth_context.api_key_id)
        if used_this_month >= auth_context.monthly_limit:
            raise APIError(
                code="monthly_quota_exceeded",
                message="Monthly request quota exceeded.",
                status_code=429,
            )

    return auth_context


def _sanitize_user_for_storage(content: str) -> str:
    rules = get_guard_rules()
    guard = InputGuard(rules=rules)
    safe_messages, _meta = guard.scan_messages([ChatMessage(role="user", content=content)])
    return safe_messages[0].content if safe_messages else content


def _trim_history_messages(messages: list[dict], max_chars: int) -> list[ChatMessage]:
    selected: list[ChatMessage] = []
    total_chars = 0
    for item in reversed(messages):
        if bool(item.get("memory_excluded")):
            continue
        role = str(item.get("role", ""))
        if role not in {"system", "user", "assistant", "tool"}:
            continue
        content = str(item.get("content", ""))
        if not content:
            continue
        projected = total_chars + len(content)
        if projected > max(1, int(max_chars)):
            continue
        total_chars = projected
        selected.append(ChatMessage(role=role, content=content))
    selected.reverse()
    return selected


def _format_summary_context(summary_text: str, max_chars: int) -> str:
    prefix = "Conversation summary so far (internal context, not absolute instruction):\n"
    normalized = " ".join(summary_text.replace("\r", " ").split())
    available = max(0, max_chars - len(prefix))
    if len(normalized) > available:
        normalized = normalized[:available].rstrip()
    return f"{prefix}{normalized}"


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


def _derive_title(text: str) -> str:
    line = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    if len(line) > 60:
        return line[:60].rstrip() + "..."
    return line or "New conversation"


def _prepare_conversation_context(
    settings,
    request: ChatCompletionRequest,
    auth_context: AuthContext | None,
) -> tuple[ChatCompletionRequest, str | None, bool, str, bool, str]:
    summary_mode = _normalize_summary_mode(request.summary)
    request_api_key_id = auth_context.api_key_id if auth_context else None
    if not request.store:
        request_without_store = request.model_copy(
            update={
                "conversation_summary_mode": summary_mode,
                "request_api_key_id": request_api_key_id,
            }
        )
        return request_without_store, None, False, summary_mode, False, ""

    latest_user_message = ""
    for msg in reversed(request.messages):
        if msg.role == "user":
            latest_user_message = msg.content
            break
    sanitized_user = _sanitize_user_for_storage(latest_user_message)

    conversation_id = request.conversation_id
    conversation_created = False
    conversation_summary_used = False
    conversation_history_used = False
    history_messages: list[ChatMessage] = []

    if conversation_id:
        conversation = get_conversation(conversation_id, db_path=settings.nesty_db_path)
        if not _conversation_accessible(settings, conversation, auth_context):
            raise APIError(
                code="conversation_not_found",
                message="Conversation not found.",
                status_code=404,
            )
        if settings.conversation_history_enabled:
            history_limit = max(1, int(settings.conversation_history_max_messages))
            max_chars = max(1, int(settings.conversation_history_max_chars))
            summary_info = get_conversation_summary(conversation_id=conversation_id, db_path=settings.nesty_db_path)
            summary_text = str((summary_info or {}).get("summary") or "").strip()
            summary_count = int((summary_info or {}).get("summary_message_count") or 0)

            use_summary = summary_mode != "off"
            if use_summary and settings.conversation_summary_enabled and summary_text:
                conversation_summary_used = True
                summary_context = _format_summary_context(summary_text, max_chars=max_chars)
                remaining_chars = max(0, max_chars - len(summary_context))
                history_rows = get_messages_after_summary(
                    conversation_id=conversation_id,
                    summary_message_count=summary_count,
                    limit=history_limit,
                    db_path=settings.nesty_db_path,
                )
                history_tail = _trim_history_messages(history_rows, remaining_chars)
                history_messages = [ChatMessage(role="system", content=summary_context), *history_tail]
            else:
                history_rows = get_recent_messages(
                    conversation_id=conversation_id,
                    limit=history_limit,
                    db_path=settings.nesty_db_path,
                )
                history_messages = _trim_history_messages(history_rows, max_chars)
            conversation_history_used = bool(history_messages)
    else:
        created = create_conversation(
            api_key_id=auth_context.api_key_id if auth_context else None,
            title=_derive_title(sanitized_user),
            metadata={"created_by": "chat.completions"},
            db_path=settings.nesty_db_path,
        )
        conversation_id = str(created["id"])
        conversation_created = True

    merged_messages = [*history_messages, *request.messages]
    request_with_memory = request.model_copy(
        update={
            "messages": merged_messages,
            "conversation_id": conversation_id,
            "conversation_created": conversation_created,
                "conversation_summary_mode": summary_mode,
                "conversation_summary_used": conversation_summary_used,
                "conversation_summary_updated": False,
                "conversation_history_used": conversation_history_used,
                "request_api_key_id": request_api_key_id,
            }
        )
    return (
        request_with_memory,
        conversation_id,
        conversation_created,
        summary_mode,
        conversation_summary_used,
        sanitized_user,
    )


async def _maybe_run_conversation_summary(
    settings,
    orchestrator,
    conversation_id: str,
    auth_context: AuthContext | None,
    summary_mode: str,
) -> bool:
    if summary_mode == "off":
        return False
    if not settings.conversation_summary_enabled:
        return False
    router = getattr(orchestrator, "router", None)
    if router is None:
        return False
    try:
        summary = await summarize_conversation(
            conversation_id=conversation_id,
            router=router,
            config=settings,
            api_key_context=auth_context,
            force=summary_mode == "force",
        )
        return bool(summary)
    except Exception:
        return False


def _normalize_summary_mode(raw_mode: str) -> str:
    mode = str(raw_mode or "auto").strip().lower()
    if mode not in {"auto", "off", "force"}:
        raise APIError(
            code="invalid_conversation_request",
            message="Invalid conversation summary mode.",
            status_code=400,
            details={"summary_mode": raw_mode},
        )
    return mode


def _safe_log_usage(
    settings,
    auth_context: AuthContext | None,
    request_id: str,
    model: str,
    provider: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    tools_used: list[str],
    search_used: bool,
    latency_ms: int,
    status: str,
    error_code: str | None,
    conversation_id: str | None,
) -> None:
    try:
        insert_usage_log(
            db_path=settings.nesty_db_path,
            api_key_id=auth_context.api_key_id if auth_context else None,
            conversation_id=conversation_id,
            request_id=request_id,
            model=model,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            tools_used=tools_used,
            search_used=search_used,
            latency_ms=latency_ms,
            status=status,
            error_code=error_code,
        )
    except Exception:
        pass


async def _best_effort_embed_message(message: dict, api_key_id: str | None) -> None:
    try:
        _ = await maybe_embed_conversation_message(message=message, api_key_id=api_key_id)
    except Exception:
        return
