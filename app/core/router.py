from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.config import ModelsConfig
from app.core.errors import APIError, MissingAPIKeyError, ProviderError, StreamingNotSupportedError
from app.providers.base import BaseProvider
from app.schemas.chat import ChatMessage
from app.schemas.provider import ProviderChatResult, ProviderStreamChunk
from app.utils.logging import log_safe


@dataclass
class RouteResult:
    provider_result: ProviderChatResult
    provider_used: str


@dataclass
class StreamRouteResult:
    provider_used: str
    stream: AsyncIterator[ProviderStreamChunk]


class ProviderRouter:
    def __init__(
        self,
        models_config: ModelsConfig,
        providers: dict[str, BaseProvider],
        logger: Any,
    ) -> None:
        self.models_config = models_config
        self.providers = providers
        self.logger = logger

    async def route_chat(
        self,
        request_id: str,
        model_alias: str,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int,
    ) -> RouteResult:
        profile = self.models_config.models.get(model_alias)
        if not profile:
            raise APIError(
                code="invalid_model",
                message=f"Model '{model_alias}' is not supported.",
                status_code=400,
            )

        attempted_providers: list[str] = []
        last_error_code = "provider_unavailable"
        had_missing_api_key = False
        had_non_missing_failure = False

        for target in profile.provider_chain:
            provider_name = target.provider
            attempted_providers.append(provider_name)
            provider = self.providers.get(provider_name)

            if not provider:
                log_safe(
                    self.logger,
                    "provider_missing",
                    request_id=request_id,
                    model_alias=model_alias,
                    provider=provider_name,
                    error_code="provider_unavailable",
                )
                continue

            try:
                provider_result = await provider.generate_chat_completion(
                    messages=messages,
                    model=target.model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return RouteResult(provider_result=provider_result, provider_used=provider_name)
            except MissingAPIKeyError:
                last_error_code = "missing_api_key"
                had_missing_api_key = True
                log_safe(
                    self.logger,
                    "provider_failed",
                    request_id=request_id,
                    model_alias=model_alias,
                    provider=provider_name,
                    error_code="missing_api_key",
                )
                continue
            except ProviderError as exc:
                last_error_code = "provider_unavailable"
                had_non_missing_failure = True
                log_safe(
                    self.logger,
                    "provider_failed",
                    request_id=request_id,
                    model_alias=model_alias,
                    provider=provider_name,
                    error_code="provider_unavailable",
                )
                if exc.retryable:
                    continue
                raise APIError(
                    code="provider_unavailable",
                    message="Provider unavailable for this request.",
                    status_code=502,
                ) from exc

        if not attempted_providers:
            raise APIError(
                code="provider_unavailable",
                message="No provider chain configured for this model.",
                status_code=502,
            )

        if had_missing_api_key and not had_non_missing_failure:
            raise APIError(
                code="missing_api_key",
                message="Missing API key for all configured providers.",
                status_code=503,
                details={"attempted_providers": attempted_providers},
            )

        raise APIError(
            code="all_providers_failed",
            message="All configured providers failed for this request.",
            status_code=503,
            details={
                "attempted_providers": attempted_providers,
                "last_error_code": last_error_code,
            },
        )

    async def route_chat_stream(
        self,
        request_id: str,
        model_alias: str,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int,
    ) -> StreamRouteResult:
        profile = self.models_config.models.get(model_alias)
        if not profile:
            raise APIError(
                code="invalid_model",
                message=f"Model '{model_alias}' is not supported.",
                status_code=400,
            )

        attempted_providers: list[str] = []
        last_error_code = "stream_provider_failed"
        had_missing_api_key = False
        had_non_missing_failure = False
        had_streaming_not_supported = False

        for target in profile.provider_chain:
            provider_name = target.provider
            attempted_providers.append(provider_name)
            provider = self.providers.get(provider_name)

            if not provider:
                log_safe(
                    self.logger,
                    "provider_missing",
                    request_id=request_id,
                    model_alias=model_alias,
                    provider=provider_name,
                    error_code="provider_unavailable",
                )
                continue

            try:
                provider_stream = provider.stream_chat_completion(
                    messages=messages,
                    model=target.model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                first_chunk = await anext(provider_stream)
                return StreamRouteResult(
                    provider_used=provider_name,
                    stream=self._prepend_stream_chunk(first_chunk, provider_stream),
                )
            except StopAsyncIteration:
                had_non_missing_failure = True
                last_error_code = "stream_provider_failed"
                log_safe(
                    self.logger,
                    "provider_stream_failed",
                    request_id=request_id,
                    model_alias=model_alias,
                    provider=provider_name,
                    error_code="stream_provider_failed",
                )
                continue
            except MissingAPIKeyError:
                last_error_code = "missing_api_key"
                had_missing_api_key = True
                log_safe(
                    self.logger,
                    "provider_stream_failed",
                    request_id=request_id,
                    model_alias=model_alias,
                    provider=provider_name,
                    error_code="missing_api_key",
                )
                continue
            except StreamingNotSupportedError:
                had_streaming_not_supported = True
                last_error_code = "streaming_not_supported"
                log_safe(
                    self.logger,
                    "provider_stream_failed",
                    request_id=request_id,
                    model_alias=model_alias,
                    provider=provider_name,
                    error_code="streaming_not_supported",
                )
                continue
            except ProviderError as exc:
                had_non_missing_failure = True
                last_error_code = "stream_provider_failed"
                log_safe(
                    self.logger,
                    "provider_stream_failed",
                    request_id=request_id,
                    model_alias=model_alias,
                    provider=provider_name,
                    error_code="stream_provider_failed",
                )
                if exc.retryable:
                    continue
                raise APIError(
                    code="stream_provider_failed",
                    message="Provider streaming failed for this request.",
                    status_code=502,
                ) from exc

        if not attempted_providers:
            raise APIError(
                code="provider_unavailable",
                message="No provider chain configured for this model.",
                status_code=502,
            )

        if had_missing_api_key and not had_non_missing_failure and not had_streaming_not_supported:
            raise APIError(
                code="missing_api_key",
                message="Missing API key for all configured providers.",
                status_code=503,
                details={"attempted_providers": attempted_providers},
            )

        if had_streaming_not_supported and not had_non_missing_failure:
            raise APIError(
                code="streaming_not_supported",
                message="Streaming is not supported by configured providers for this model.",
                status_code=501,
                details={"attempted_providers": attempted_providers},
            )

        raise APIError(
            code="all_providers_failed",
            message="All configured providers failed for this request.",
            status_code=503,
            details={
                "attempted_providers": attempted_providers,
                "last_error_code": last_error_code,
            },
        )

    async def _prepend_stream_chunk(
        self,
        first_chunk: ProviderStreamChunk,
        stream: AsyncIterator[ProviderStreamChunk],
    ) -> AsyncIterator[ProviderStreamChunk]:
        yield first_chunk
        async for chunk in stream:
            yield chunk
