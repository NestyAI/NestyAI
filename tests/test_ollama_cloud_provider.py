from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from app.core.errors import ProviderError
from app.providers.ollama_cloud import OllamaCloudProvider
from app.schemas.chat import ChatMessage


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeStreamResponse:
    def __init__(self, status_code: int, lines: list[str]) -> None:
        self.status_code = status_code
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse | None = None, stream_lines: list[str] | None = None) -> None:
        self.response = response or _FakeResponse(200, {})
        self.stream_lines = stream_lines or []
        self.last_post: dict | None = None
        self.last_stream: dict | None = None

    async def post(self, url: str, json, headers):
        self.last_post = {"url": url, "json": json, "headers": headers}
        return self.response

    def stream(self, method: str, url: str, json, headers):
        self.last_stream = {"method": method, "url": url, "json": json, "headers": headers}
        return _FakeStreamResponse(self.response.status_code, self.stream_lines)


@pytest.mark.asyncio
async def test_ollama_cloud_non_stream_uses_api_chat_and_bearer(monkeypatch) -> None:
    fake = _FakeAsyncClient(
        response=_FakeResponse(
            200,
            {
                "message": {"role": "assistant", "content": "OK"},
                "prompt_eval_count": 10,
                "eval_count": 5,
            },
        )
    )
    monkeypatch.setattr("app.providers.ollama_cloud.get_shared_async_client", lambda timeout_seconds: fake)

    provider = OllamaCloudProvider(api_key="test-key", timeout_seconds=30, base_url="https://ollama.com/")
    result = await provider.generate_chat_completion(
        messages=[ChatMessage(role="user", content="hello")],
        model="gemma3:12b",
        temperature=0.2,
        max_tokens=64,
    )

    assert fake.last_post is not None
    assert fake.last_post["url"] == "https://ollama.com/api/chat"
    assert fake.last_post["headers"]["Authorization"] == "Bearer test-key"
    assert fake.last_post["json"]["stream"] is False
    assert fake.last_post["json"]["model"] == "gemma3:12b"
    assert result.content == "OK"
    assert result.usage.prompt_tokens == 10
    assert result.usage.completion_tokens == 5
    assert result.usage.total_tokens == 15


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code,error_code", [(401, "provider_auth_failed"), (403, "provider_auth_failed"), (404, "provider_model_unavailable"), (429, "rate_limited")])
async def test_ollama_cloud_error_mapping_http_status(monkeypatch, status_code: int, error_code: str) -> None:
    fake = _FakeAsyncClient(response=_FakeResponse(status_code, {"error": "x"}))
    monkeypatch.setattr("app.providers.ollama_cloud.get_shared_async_client", lambda timeout_seconds: fake)
    provider = OllamaCloudProvider(api_key="test-key", timeout_seconds=30, base_url="https://ollama.com")

    with pytest.raises(ProviderError) as exc_info:
        await provider.generate_chat_completion(
            messages=[ChatMessage(role="user", content="hello")],
            model="gemma3:12b",
            temperature=0.2,
            max_tokens=64,
        )
    exc = exc_info.value
    assert exc.status_code == status_code
    if error_code == "provider_auth_failed":
        assert "authentication" in exc.message.lower()
    elif error_code == "provider_model_unavailable":
        assert "model unavailable" in exc.message.lower()
    else:
        assert "rate limited" in exc.message.lower()


@pytest.mark.asyncio
async def test_ollama_cloud_timeout_maps_provider_timeout(monkeypatch) -> None:
    class _TimeoutClient:
        async def post(self, url: str, json, headers):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("app.providers.ollama_cloud.get_shared_async_client", lambda timeout_seconds: _TimeoutClient())
    provider = OllamaCloudProvider(api_key="test-key", timeout_seconds=30, base_url="https://ollama.com")

    with pytest.raises(ProviderError) as exc_info:
        await provider.generate_chat_completion(
            messages=[ChatMessage(role="user", content="hello")],
            model="gemma3:12b",
            temperature=0.2,
            max_tokens=64,
        )
    assert "timed out" in exc_info.value.message.lower()
    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_ollama_cloud_stream_parses_ndjson_chunks(monkeypatch) -> None:
    fake = _FakeAsyncClient(
        response=_FakeResponse(200, {}),
        stream_lines=[
            '{"model":"gemma3:12b","message":{"role":"assistant","content":"Hel"},"done":false}',
            '{"model":"gemma3:12b","message":{"role":"assistant","content":"lo"},"done":false}',
            '{"model":"gemma3:12b","done":true,"prompt_eval_count":2,"eval_count":3}',
        ],
    )
    monkeypatch.setattr("app.providers.ollama_cloud.get_shared_async_client", lambda timeout_seconds: fake)
    provider = OllamaCloudProvider(api_key="test-key", timeout_seconds=30, base_url="https://ollama.com")

    chunks = []
    async for chunk in provider.stream_chat_completion(
        messages=[ChatMessage(role="user", content="hello")],
        model="gemma3:12b",
        temperature=0.2,
        max_tokens=64,
    ):
        chunks.append(chunk)

    assert fake.last_stream is not None
    assert fake.last_stream["url"] == "https://ollama.com/api/chat"
    assert fake.last_stream["json"]["stream"] is True
    assert "".join(item.delta for item in chunks if item.delta) == "Hello"
    usage_chunks = [item for item in chunks if item.usage is not None]
    assert usage_chunks
    assert usage_chunks[-1].usage.total_tokens == 5
    assert any(item.finish_reason == "stop" for item in chunks)
