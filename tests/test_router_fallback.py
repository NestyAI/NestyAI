from __future__ import annotations

from collections.abc import Callable

import pytest

from app.config import ModelProfile, ModelsConfig, ProviderTarget
from app.core.errors import APIError, MissingAPIKeyError, ProviderError
from app.core.router import ProviderRouter
from app.providers.base import BaseProvider
from app.schemas.chat import ChatMessage
from app.schemas.provider import ProviderChatResult
from app.utils.logging import get_logger


class DummyProvider(BaseProvider):
    def __init__(self, provider_name: str, behavior: Callable[[], ProviderChatResult]) -> None:
        self.provider_name = provider_name
        self._behavior = behavior
        self.calls = 0

    async def generate_chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> ProviderChatResult:
        self.calls += 1
        return self._behavior()


def _models_config() -> ModelsConfig:
    return ModelsConfig(
        models={
            "nesty-test": ModelProfile(
                display_name="Nesty Test",
                description="Test profile",
                strategy="balanced",
                search_mode="off",
                max_tool_calls=0,
                max_search_results=0,
                max_context_chars=1000,
                provider_chain=[
                    ProviderTarget(provider="groq", model="m1"),
                    ProviderTarget(provider="openrouter", model="m2"),
                    ProviderTarget(provider="nvidia", model="m3"),
                ],
            )
        }
    )


def _router_with(providers: dict[str, BaseProvider]) -> ProviderRouter:
    return ProviderRouter(
        models_config=_models_config(),
        providers=providers,
        logger=get_logger("test.router"),
    )


@pytest.mark.asyncio
async def test_router_fallback_missing_api_key_then_success() -> None:
    def missing():
        raise MissingAPIKeyError("groq")

    def success():
        return ProviderChatResult(provider="openrouter", content="ok")

    groq = DummyProvider("groq", missing)
    openrouter = DummyProvider("openrouter", success)
    router = _router_with({"groq": groq, "openrouter": openrouter})

    result = await router.route_chat(
        request_id="req_test",
        model_alias="nesty-test",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.7,
        max_tokens=128,
    )
    assert result.provider_used == "openrouter"
    assert result.provider_result.content == "ok"
    assert groq.calls == 1
    assert openrouter.calls == 1


@pytest.mark.asyncio
async def test_router_fallback_timeout_then_success() -> None:
    def timeout():
        raise ProviderError(provider="groq", message="timeout", retryable=True)

    def success():
        return ProviderChatResult(provider="openrouter", content="ok-timeout")

    router = _router_with(
        {
            "groq": DummyProvider("groq", timeout),
            "openrouter": DummyProvider("openrouter", success),
        }
    )

    result = await router.route_chat(
        request_id="req_test",
        model_alias="nesty-test",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.7,
        max_tokens=128,
    )
    assert result.provider_used == "openrouter"
    assert result.provider_result.content == "ok-timeout"


@pytest.mark.asyncio
async def test_router_fallback_429_then_success() -> None:
    def throttled():
        raise ProviderError(provider="groq", message="429", retryable=True, status_code=429)

    def success():
        return ProviderChatResult(provider="openrouter", content="ok-429")

    router = _router_with(
        {
            "groq": DummyProvider("groq", throttled),
            "openrouter": DummyProvider("openrouter", success),
        }
    )

    result = await router.route_chat(
        request_id="req_test",
        model_alias="nesty-test",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.7,
        max_tokens=128,
    )
    assert result.provider_used == "openrouter"
    assert result.provider_result.content == "ok-429"


@pytest.mark.asyncio
async def test_router_all_providers_fail_structured_error() -> None:
    def fail_retryable():
        raise ProviderError(provider="groq", message="down", retryable=True, status_code=503)

    router = _router_with(
        {
            "groq": DummyProvider("groq", fail_retryable),
            "openrouter": DummyProvider("openrouter", fail_retryable),
            "nvidia": DummyProvider("nvidia", fail_retryable),
        }
    )

    with pytest.raises(APIError) as exc_info:
        await router.route_chat(
            request_id="req_test",
            model_alias="nesty-test",
            messages=[ChatMessage(role="user", content="hello")],
            temperature=0.7,
            max_tokens=128,
        )

    exc = exc_info.value
    assert exc.code == "all_providers_failed"
    assert "attempted_providers" in exc.details
    assert exc.details["attempted_providers"] == ["groq", "openrouter", "nvidia"]

