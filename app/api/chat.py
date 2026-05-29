from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import StreamingResponse

from app.core.errors import APIError
from app.deps import get_orchestrator
from app.deps import get_settings
from app.schemas.chat import AuthDebugInfo, ChatCompletionRequest, ChatCompletionResponse
from app.security.auth import AuthContext, optional_api_key, require_api_key
from app.security.rate_limit import build_rate_limit_key, get_rate_limiter
from app.storage.usage import count_daily_requests, count_monthly_requests, insert_usage_log
from app.utils.ids import generate_request_id


router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat/completions", response_model=ChatCompletionResponse, response_model_exclude_none=True)
async def chat_completions(request: ChatCompletionRequest, raw_request: Request) -> ChatCompletionResponse | StreamingResponse:
    settings = get_settings()
    orchestrator = get_orchestrator()
    request_id = generate_request_id()

    started_at = time.perf_counter()
    auth_context: AuthContext | None = None
    try:
        auth_context = _apply_pre_chat_checks(settings=settings, request=request, raw_request=raw_request)
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
        )
        raise

    if request.stream:
        try:
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
                    search_used=stream_handle.outcome.tools.search.enabled,
                    latency_ms=latency_ms,
                    status=stream_handle.outcome.status,
                    error_code=stream_handle.outcome.error_code or None,
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
        search_used = response.tools.search.enabled
        status = "success"

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
) -> None:
    try:
        insert_usage_log(
            db_path=settings.nesty_db_path,
            api_key_id=auth_context.api_key_id if auth_context else None,
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

