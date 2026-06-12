from __future__ import annotations

import pytest

from app.providers.groq import GroqProvider
from app.providers.openrouter import OpenRouterProvider


class _FakeStreamResponse:
    def __init__(self, status_code: int, lines: list[str]) -> None:
        self.status_code = status_code
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeAsyncClient:
    def __init__(self, status_code: int, lines: list[str]) -> None:
        self.status_code = status_code
        self.lines = lines

    def stream(self, method: str, url: str, json, headers):
        return _FakeStreamResponse(self.status_code, self.lines)


@pytest.mark.asyncio
async def test_groq_provider_stream_normalizes_chunks(monkeypatch) -> None:
    lines = [
        'data: {"choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"content":" world"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}',
        "data: [DONE]",
    ]
    monkeypatch.setattr(
        "app.providers.openai_compatible.get_shared_async_client",
        lambda timeout_seconds: _FakeAsyncClient(status_code=200, lines=lines),
    )

    provider = GroqProvider(api_key="test", timeout_seconds=10)
    chunks = []
    async for chunk in provider.stream_chat_completion(
        messages=[],
        model="test-model",
        temperature=0.1,
        max_tokens=16,
    ):
        chunks.append(chunk)

    text = "".join(chunk.delta for chunk in chunks if chunk.delta)
    assert text == "Hello world"
    assert any(chunk.finish_reason == "stop" for chunk in chunks)
    usage_chunks = [chunk for chunk in chunks if chunk.usage is not None]
    assert usage_chunks
    assert usage_chunks[-1].usage.total_tokens == 5


@pytest.mark.asyncio
async def test_openrouter_provider_stream_normalizes_chunks(monkeypatch) -> None:
    lines = [
        "data: not-json",
        'data: {"choices":[{"delta":{"content":"A"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"content":"B"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        "data: [DONE]",
    ]
    monkeypatch.setattr(
        "app.providers.openai_compatible.get_shared_async_client",
        lambda timeout_seconds: _FakeAsyncClient(status_code=200, lines=lines),
    )

    provider = OpenRouterProvider(api_key="test", timeout_seconds=10)
    chunks = []
    async for chunk in provider.stream_chat_completion(
        messages=[],
        model="test-model",
        temperature=0.1,
        max_tokens=16,
    ):
        chunks.append(chunk)

    assert "".join(chunk.delta for chunk in chunks if chunk.delta) == "AB"
    assert any(chunk.finish_reason == "stop" for chunk in chunks)
