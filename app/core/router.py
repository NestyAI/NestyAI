from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import ModelsConfig
from app.core.errors import APIError, MissingAPIKeyError, ProviderError
from app.providers.base import BaseProvider
from app.schemas.chat import ChatMessage
from app.schemas.provider import ProviderChatResult
from app.utils.logging import log_safe


@dataclass
class RouteResult:
    provider_result: ProviderChatResult
    provider_used: str


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
