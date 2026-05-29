from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest

from app.config import ModelProfile, ModelsConfig, ProviderTarget
from app.core.errors import ProviderError
from app.core.router import ProviderRouter
from app.providers.base import BaseProvider
from app.schemas.chat import ChatMessage
from app.schemas.provider import ProviderChatResult, ProviderStreamChunk
from app.utils.logging import get_logger


class _DummyStreamProvider(BaseProvider):
    def __init__(
        self,
        provider_name: str,
        stream_behavior: Callable[[], AsyncIterator[ProviderStreamChunk]],
    ) -> None:
        self.provider_name = provider_name
        self._stream_behavior = stream_behavior
        self.stream_calls = 0

    async def generate_chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> ProviderChatResult:
        return ProviderChatResult(provider=self.provider_name, content="unused")

    async def stream_chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[ProviderStreamChunk]:
        self.stream_calls += 1
        async for chunk in self._stream_behavior():
            yield chunk


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
                ],
            )
        }
    )


def _router_with(providers: dict[str, BaseProvider]) -> ProviderRouter:
    return ProviderRouter(models_config=_models_config(), providers=providers, logger=get_logger("test.router.stream"))


@pytest.mark.asyncio
async def test_router_stream_fallback_if_first_provider_fails_before_yield() -> None:
    async def fail_before_yield():
        raise ProviderError(provider="groq", message="stream fail", retryable=True)
        yield ProviderStreamChunk(delta="unused")

    async def success_stream():
        yield ProviderStreamChunk(delta="hello")
        yield ProviderStreamChunk(finish_reason="stop")

    groq = _DummyStreamProvider("groq", fail_before_yield)
    openrouter = _DummyStreamProvider("openrouter", success_stream)
    router = _router_with({"groq": groq, "openrouter": openrouter})

    result = await router.route_chat_stream(
        request_id="req_stream_1",
        model_alias="nesty-test",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.7,
        max_tokens=64,
    )
    chunks = []
    async for chunk in result.stream:
        chunks.append(chunk)

    assert result.provider_used == "openrouter"
    assert "".join(chunk.delta for chunk in chunks if chunk.delta) == "hello"
    assert groq.stream_calls == 1
    assert openrouter.stream_calls == 1


@pytest.mark.asyncio
async def test_router_stream_does_not_fallback_mid_stream_after_yield() -> None:
    async def partial_then_fail():
        yield ProviderStreamChunk(delta="partial")
        raise ProviderError(provider="groq", message="stream interrupted", retryable=True)

    async def backup_stream():
        yield ProviderStreamChunk(delta="backup")
        yield ProviderStreamChunk(finish_reason="stop")

    groq = _DummyStreamProvider("groq", partial_then_fail)
    openrouter = _DummyStreamProvider("openrouter", backup_stream)
    router = _router_with({"groq": groq, "openrouter": openrouter})

    result = await router.route_chat_stream(
        request_id="req_stream_2",
        model_alias="nesty-test",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.7,
        max_tokens=64,
    )

    collected = []
    with pytest.raises(ProviderError):
        async for chunk in result.stream:
            collected.append(chunk)

    assert "".join(chunk.delta for chunk in collected if chunk.delta) == "partial"
    assert openrouter.stream_calls == 0
