from __future__ import annotations

import pytest

from app.core.errors import MissingAPIKeyError, ProviderError
from app.providers.anthropic import AnthropicProvider
from app.providers.gemini import GeminiProvider
from app.schemas.chat import ChatMessage


@pytest.mark.asyncio
async def test_gemini_generate_chat_completion_parses_response(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        json={
            "candidates": [{"content": {"parts": [{"text": "Hello from Gemini"}]}}],
            "usageMetadata": {
                "promptTokenCount": 5,
                "candidatesTokenCount": 7,
                "totalTokenCount": 12,
            },
        },
    )
    provider = GeminiProvider(api_key="gemini-key", timeout_seconds=30.0)
    result = await provider.generate_chat_completion(
        messages=[ChatMessage(role="user", content="Hi")],
        model="gemini-2.0-flash",
        temperature=0.2,
        max_tokens=64,
    )
    assert result.content == "Hello from Gemini"
    assert result.usage.total_tokens == 12


@pytest.mark.asyncio
async def test_gemini_auth_error_is_sanitized(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        status_code=401,
        json={"error": {"message": "API key not valid. sk-secret-leak", "status": "UNAUTHENTICATED"}},
    )
    provider = GeminiProvider(api_key="bad-key", timeout_seconds=30.0)
    with pytest.raises(ProviderError) as exc:
        await provider.generate_chat_completion(
            messages=[ChatMessage(role="user", content="Hi")],
            model="gemini-2.0-flash",
            temperature=0.2,
            max_tokens=64,
        )
    assert exc.value.message == "Provider authentication failed."
    assert "sk-secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_gemini_stream_emits_provider_stream_chunks(httpx_mock) -> None:
    stream_body = (
        'data: {"candidates":[{"content":{"parts":[{"text":"Hel"}]}}]}\n\n'
        'data: {"candidates":[{"content":{"parts":[{"text":"lo"}]}}]}\n\n'
        'data: {"candidates":[{"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":1,"candidatesTokenCount":2,"totalTokenCount":3}}\n\n'
    )
    httpx_mock.add_response(
        url="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:streamGenerateContent?alt=sse",
        content=stream_body.encode("utf-8"),
    )
    provider = GeminiProvider(api_key="gemini-key", timeout_seconds=30.0)
    chunks = [
        chunk
        async for chunk in provider.stream_chat_completion(
            messages=[ChatMessage(role="user", content="Hi")],
            model="gemini-2.0-flash",
            temperature=0.2,
            max_tokens=64,
        )
    ]
    assert any(chunk.delta == "Hel" for chunk in chunks)
    assert any(chunk.delta == "lo" for chunk in chunks)
    assert any(chunk.finish_reason == "STOP" for chunk in chunks)


@pytest.mark.asyncio
async def test_anthropic_generate_chat_completion_parses_response(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        json={
            "content": [{"type": "text", "text": "Hello from Claude"}],
            "usage": {"input_tokens": 4, "output_tokens": 6},
        },
    )
    provider = AnthropicProvider(api_key="anthropic-key", timeout_seconds=30.0)
    result = await provider.generate_chat_completion(
        messages=[ChatMessage(role="user", content="Hi")],
        model="claude-3-5-haiku-latest",
        temperature=0.2,
        max_tokens=64,
    )
    assert result.content == "Hello from Claude"
    assert result.usage.total_tokens == 10


@pytest.mark.asyncio
async def test_anthropic_missing_api_key_raises(httpx_mock) -> None:
    provider = AnthropicProvider(api_key=None, timeout_seconds=30.0)
    with pytest.raises(MissingAPIKeyError):
        await provider.generate_chat_completion(
            messages=[ChatMessage(role="user", content="Hi")],
            model="claude-3-5-haiku-latest",
            temperature=0.2,
            max_tokens=64,
        )


@pytest.mark.asyncio
async def test_anthropic_stream_emits_provider_stream_chunks(httpx_mock) -> None:
    stream_body = (
        'event: content_block_delta\n'
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}\n\n'
        'event: message_delta\n'
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"input_tokens":1,"output_tokens":2}}\n\n'
        'event: message_stop\n'
        'data: {"type":"message_stop"}\n\n'
    )
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        content=stream_body.encode("utf-8"),
    )
    provider = AnthropicProvider(api_key="anthropic-key", timeout_seconds=30.0)
    chunks = [
        chunk
        async for chunk in provider.stream_chat_completion(
            messages=[ChatMessage(role="user", content="Hello")],
            model="claude-3-5-haiku-latest",
            temperature=0.2,
            max_tokens=64,
        )
    ]
    assert any(chunk.delta == "Hi" for chunk in chunks)
    assert any(chunk.finish_reason in {"end_turn", "stop"} for chunk in chunks)
