from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.config import ModelProfile, ModelsConfig
from app.core.model_config_loader import get_effective_model_config
from app.core.provider_health_service import should_skip_provider_target
from app.core.runtime_gateway_state import is_provider_runtime_disabled
from app.core.errors import APIError, MissingAPIKeyError, ProviderError, StreamingNotSupportedError
from app.providers.base import BaseProvider
from app.schemas.chat import ChatMessage
from app.schemas.provider import ProviderChatResult, ProviderStreamChunk
from app.utils.logging import log_safe


@dataclass
class RouteResult:
    provider_result: ProviderChatResult
    provider_used: str
    provider_health: dict[str, Any] | None = None


@dataclass
class StreamRouteResult:
    provider_used: str
    stream: AsyncIterator[ProviderStreamChunk]
    provider_health: dict[str, Any] | None = None


class ProviderRouter:
    def __init__(
        self,
        models_config: ModelsConfig,
        providers: dict[str, BaseProvider],
        logger: Any,
        settings: Any | None = None,
    ) -> None:
        self.models_config = models_config
        self.providers = providers
        self.logger = logger
        self.settings = settings

    async def route_chat(
        self,
        request_id: str,
        model_alias: str,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int,
    ) -> RouteResult:
        profile = self._resolve_model_profile(model_alias)
        if not profile:
            raise APIError(
                code="invalid_model",
                message=f"Model '{model_alias}' is not supported.",
                status_code=400,
            )
        return await self.generate_with_provider_chain(
            request_id=request_id,
            provider_chain=profile.provider_chain,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            trace_label=model_alias,
            model_alias=model_alias,
        )

    async def generate_with_provider_chain(
        self,
        request_id: str,
        provider_chain,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int,
        trace_label: str = "custom_chain",
        model_alias: str | None = None,
        role: str | None = None,
    ) -> RouteResult:
        targets = self._normalize_provider_chain(provider_chain)
        provider_health_meta, eligible_targets = self._apply_health_awareness(
            targets=targets,
            model_alias=model_alias,
            role=role,
        )
        runtime_meta, eligible_targets = self._apply_runtime_provider_disable(eligible_targets)
        provider_health_meta = self._merge_provider_routing_meta(provider_health_meta, runtime_meta)
        attempted_providers: list[str] = []
        provider_errors: list[dict[str, Any]] = []
        last_error_code = "provider_unavailable"
        had_missing_api_key = False
        had_non_missing_failure = False

        for provider_name, provider_model in eligible_targets:
            attempted_providers.append(provider_name)
            provider = self.providers.get(provider_name)

            if not provider:
                provider_errors.append(
                    {
                        "provider": provider_name,
                        "model": provider_model,
                        "error_code": "provider_unavailable",
                    }
                )
                log_safe(
                    self.logger,
                    "provider_missing",
                    request_id=request_id,
                    model_alias=trace_label,
                    provider=provider_name,
                    error_code="provider_unavailable",
                )
                continue

            try:
                provider_result = await provider.generate_chat_completion(
                    messages=messages,
                    model=provider_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return RouteResult(
                    provider_result=provider_result,
                    provider_used=provider_name,
                    provider_health=provider_health_meta,
                )
            except MissingAPIKeyError:
                last_error_code = "missing_api_key"
                had_missing_api_key = True
                provider_errors.append(
                    {
                        "provider": provider_name,
                        "model": provider_model,
                        "error_code": "provider_auth_failed",
                    }
                )
                log_safe(
                    self.logger,
                    "provider_failed",
                    request_id=request_id,
                    model_alias=trace_label,
                    provider=provider_name,
                    error_code="missing_api_key",
                )
                continue
            except ProviderError as exc:
                had_non_missing_failure = True
                error_code = self._classify_provider_error(exc)
                last_error_code = error_code
                provider_errors.append(
                    {
                        "provider": provider_name,
                        "model": provider_model,
                        "error_code": error_code,
                        "upstream_status": int(exc.status_code) if exc.status_code else None,
                    }
                )
                log_safe(
                    self.logger,
                    "provider_failed",
                    request_id=request_id,
                    model_alias=trace_label,
                    provider=provider_name,
                    error_code=error_code,
                )
                if self._is_fallbackable_provider_error(error_code):
                    continue
                raise APIError(
                    code="provider_unavailable",
                    message="Provider unavailable for this request.",
                    status_code=502,
                    details={
                        "attempted_providers": attempted_providers,
                        "provider_errors": provider_errors,
                        "fallback_used": len(attempted_providers) > 1,
                    },
                ) from exc

        if not attempted_providers:
            if (
                targets
                and provider_health_meta
                and provider_health_meta.get("aware_routing")
                and provider_health_meta.get("strict_mode")
                and provider_health_meta.get("all_targets_skipped")
            ):
                raise APIError(
                    code="provider_health_strict_blocked",
                    message="All configured providers are blocked by strict provider health routing.",
                    status_code=503,
                    details={"provider_health": provider_health_meta},
                )
            raise APIError(
                code="provider_unavailable",
                message="No provider chain configured for this request.",
                status_code=502,
            )

        if had_missing_api_key and not had_non_missing_failure:
            raise APIError(
                code="missing_api_key",
                message="Missing API key for all configured providers.",
                status_code=503,
                details={
                    "attempted_providers": attempted_providers,
                    "provider_errors": provider_errors,
                    "fallback_used": len(attempted_providers) > 1,
                },
            )

        raise APIError(
            code="all_providers_failed",
            message="All configured providers failed for this request.",
            status_code=503,
            details={
                "attempted_providers": attempted_providers,
                "provider_errors": provider_errors,
                "last_error_code": last_error_code,
                "fallback_used": len(attempted_providers) > 1,
                "fallback_reason": last_error_code,
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
        profile = self._resolve_model_profile(model_alias)
        if not profile:
            raise APIError(
                code="invalid_model",
                message=f"Model '{model_alias}' is not supported.",
                status_code=400,
            )

        attempted_providers: list[str] = []
        provider_errors: list[dict[str, Any]] = []
        last_error_code = "stream_provider_failed"
        had_missing_api_key = False
        had_non_missing_failure = False
        had_streaming_not_supported = False

        targets = self._normalize_provider_chain(profile.provider_chain)
        provider_health_meta, eligible_targets = self._apply_health_awareness(
            targets=targets,
            model_alias=model_alias,
            role="main",
        )
        runtime_meta, eligible_targets = self._apply_runtime_provider_disable(eligible_targets)
        provider_health_meta = self._merge_provider_routing_meta(provider_health_meta, runtime_meta)

        for provider_name, provider_model in eligible_targets:
            attempted_providers.append(provider_name)
            provider = self.providers.get(provider_name)

            if not provider:
                provider_errors.append(
                    {
                        "provider": provider_name,
                        "model": provider_model,
                        "error_code": "provider_unavailable",
                    }
                )
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
                    model=provider_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                first_chunk = await anext(provider_stream)
                return StreamRouteResult(
                    provider_used=provider_name,
                    stream=self._prepend_stream_chunk(first_chunk, provider_stream),
                    provider_health=provider_health_meta,
                )
            except StopAsyncIteration:
                had_non_missing_failure = True
                last_error_code = "stream_provider_failed"
                provider_errors.append(
                    {
                        "provider": provider_name,
                        "model": provider_model,
                        "error_code": "stream_provider_failed",
                    }
                )
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
                provider_errors.append(
                    {
                        "provider": provider_name,
                        "model": provider_model,
                        "error_code": "provider_auth_failed",
                    }
                )
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
                provider_errors.append(
                    {
                        "provider": provider_name,
                        "model": provider_model,
                        "error_code": "streaming_not_supported",
                    }
                )
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
                error_code = self._classify_provider_error(exc, is_stream=True)
                last_error_code = error_code
                provider_errors.append(
                    {
                        "provider": provider_name,
                        "model": provider_model,
                        "error_code": error_code,
                        "upstream_status": int(exc.status_code) if exc.status_code else None,
                    }
                )
                log_safe(
                    self.logger,
                    "provider_stream_failed",
                    request_id=request_id,
                    model_alias=model_alias,
                    provider=provider_name,
                    error_code=error_code,
                )
                if self._is_fallbackable_provider_error(error_code):
                    continue
                raise APIError(
                    code="stream_provider_failed",
                    message="Provider streaming failed for this request.",
                    status_code=502,
                    details={
                        "attempted_providers": attempted_providers,
                        "provider_errors": provider_errors,
                        "fallback_used": len(attempted_providers) > 1,
                    },
                ) from exc

        if not attempted_providers:
            if (
                targets
                and provider_health_meta
                and provider_health_meta.get("aware_routing")
                and provider_health_meta.get("strict_mode")
                and provider_health_meta.get("all_targets_skipped")
            ):
                raise APIError(
                    code="provider_health_strict_blocked",
                    message="All configured providers are blocked by strict provider health routing.",
                    status_code=503,
                    details={"provider_health": provider_health_meta},
                )
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
                details={
                    "attempted_providers": attempted_providers,
                    "provider_errors": provider_errors,
                    "fallback_used": len(attempted_providers) > 1,
                },
            )

        if had_streaming_not_supported and not had_non_missing_failure:
            raise APIError(
                code="streaming_not_supported",
                message="Streaming is not supported by configured providers for this model.",
                status_code=501,
                details={
                    "attempted_providers": attempted_providers,
                    "provider_errors": provider_errors,
                    "fallback_used": len(attempted_providers) > 1,
                },
            )

        raise APIError(
            code="all_providers_failed",
            message="All configured providers failed for this request.",
            status_code=503,
            details={
                "attempted_providers": attempted_providers,
                "provider_errors": provider_errors,
                "last_error_code": last_error_code,
                "fallback_used": len(attempted_providers) > 1,
                "fallback_reason": last_error_code,
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

    @staticmethod
    def _normalize_provider_chain(provider_chain) -> list[tuple[str, str]]:
        normalized: list[tuple[str, str]] = []
        for target in provider_chain or []:
            provider_name = ""
            model_name = ""
            if hasattr(target, "provider") and hasattr(target, "model"):
                provider_name = str(getattr(target, "provider") or "").strip()
                model_name = str(getattr(target, "model") or "").strip()
            elif isinstance(target, dict):
                provider_name = str(target.get("provider") or "").strip()
                model_name = str(target.get("model") or "").strip()
            if not provider_name or not model_name:
                continue
            normalized.append((provider_name, model_name))
        return normalized

    def _resolve_model_profile(self, model_alias: str) -> ModelProfile | None:
        try:
            effective = get_effective_model_config(model_alias)
            if isinstance(effective, dict):
                return ModelProfile.model_validate(effective)
        except Exception:
            pass
        return self.models_config.models.get(model_alias)

    def _apply_health_awareness(
        self,
        targets: list[tuple[str, str]],
        model_alias: str | None,
        role: str | None,
    ) -> tuple[dict[str, Any] | None, list[tuple[str, str]]]:
        settings = self.settings
        if settings is None:
            try:
                from app.deps import get_settings as deps_get_settings

                settings = deps_get_settings()
            except Exception:
                settings = None
        if settings is None:
            return None, targets
        aware = bool(getattr(settings, "provider_health_aware_routing", False))
        if not aware:
            return None, targets

        skipped_targets: list[dict[str, str]] = []
        eligible_targets: list[tuple[str, str]] = []
        strict_mode = bool(getattr(settings, "provider_health_strict_mode", False))

        for provider_name, provider_model in targets:
            try:
                decision = should_skip_provider_target(
                    provider=provider_name,
                    model=provider_model,
                    model_alias=model_alias,
                    role=role,
                    config=settings,
                )
            except Exception:
                decision = {
                    "healthy": True,
                    "skip": False,
                    "reason": "no_recent_health",
                    "latest_status": None,
                    "bad_count": 0,
                    "checked_at": None,
                }
            if bool(decision.get("skip")):
                skipped_targets.append(
                    {
                        "provider": provider_name,
                        "model": provider_model,
                        "reason": str(decision.get("reason") or "recent_failures"),
                    }
                )
                continue
            eligible_targets.append((provider_name, provider_model))

        fallback_to_unhealthy_allowed = False
        all_targets_skipped = bool(targets) and not bool(eligible_targets)
        if not eligible_targets and not strict_mode:
            eligible_targets = list(targets)
            fallback_to_unhealthy_allowed = True

        provider_health_meta = {
            "aware_routing": True,
            "strict_mode": strict_mode,
            "skipped_targets": skipped_targets,
            "fallback_to_unhealthy_allowed": fallback_to_unhealthy_allowed,
            "all_targets_skipped": all_targets_skipped,
        }
        return provider_health_meta, eligible_targets

    @staticmethod
    def _merge_provider_routing_meta(
        base_meta: dict[str, Any] | None,
        extra_meta: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not base_meta and not extra_meta:
            return None
        merged: dict[str, Any] = dict(base_meta or {})
        if extra_meta:
            merged.update(extra_meta)
        return merged

    def _apply_runtime_provider_disable(
        self,
        targets: list[tuple[str, str]],
    ) -> tuple[dict[str, Any] | None, list[tuple[str, str]]]:
        disabled_targets: list[dict[str, str]] = []
        eligible_targets: list[tuple[str, str]] = []
        for provider_name, provider_model in targets:
            if is_provider_runtime_disabled(provider_name):
                disabled_targets.append(
                    {
                        "provider": provider_name,
                        "model": provider_model,
                        "reason": "runtime_disabled",
                    }
                )
                continue
            eligible_targets.append((provider_name, provider_model))
        if not disabled_targets:
            return None, eligible_targets
        return {"runtime_disabled_targets": disabled_targets}, eligible_targets

    @staticmethod
    def _classify_provider_error(exc: ProviderError, is_stream: bool = False) -> str:
        message = str(exc.message or "").strip().lower()
        status_code = int(exc.status_code or 0)
        if "timeout" in message or "timed out" in message:
            return "provider_timeout"
        if status_code in {401, 403}:
            return "provider_auth_failed"
        if status_code == 404 or "model unavailable" in message or "model not found" in message:
            return "provider_model_unavailable"
        if status_code == 429 or "rate limit" in message or "rate limited" in message:
            return "rate_limited"
        if status_code >= 500 or "temporarily unavailable" in message or "connection" in message:
            return "provider_unavailable"
        if is_stream:
            return "stream_provider_failed"
        return "provider_failed"

    @staticmethod
    def _is_fallbackable_provider_error(error_code: str) -> bool:
        return error_code in {
            "provider_auth_failed",
            "provider_model_unavailable",
            "rate_limited",
            "provider_timeout",
            "provider_unavailable",
            "provider_failed",
            "stream_provider_failed",
            "streaming_not_supported",
        }
