from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.errors import MissingAPIKeyError, ProviderError
from app.core.http_client import get_shared_async_client
from app.providers.base import BaseProvider
from app.schemas.chat import ChatMessage
from app.schemas.provider import ProviderChatResult, ProviderStreamChunk, ProviderUsage


class OllamaCloudProvider(BaseProvider):
    provider_name = "ollama_cloud"

    def __init__(self, api_key: str | None, timeout_seconds: float, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.base_url = str(base_url or "https://ollama.com").strip().rstrip("/")

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/api/chat"):
            return self.base_url
        return f"{self.base_url}/api/chat"

    async def generate_chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> ProviderChatResult:
        if not self.api_key:
            raise MissingAPIKeyError(self.provider_name)

        payload = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            client = get_shared_async_client(timeout_seconds=self.timeout_seconds)
            response = await client.post(self.endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                provider=self.provider_name,
                message="Provider request timed out.",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderError(
                provider=self.provider_name,
                message="Network error while calling provider.",
                retryable=True,
            ) from exc

        self._raise_for_http_error(response.status_code)
        data = self._parse_json(response)

        message_obj = data.get("message") if isinstance(data.get("message"), dict) else {}
        content = message_obj.get("content")
        if content is None:
            content = data.get("response", "")
        if not isinstance(content, str):
            content = str(content or "")
        usage = self._usage_from_ollama(data)
        return ProviderChatResult(provider=self.provider_name, content=content, usage=usage)

    async def stream_chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[ProviderStreamChunk]:
        if not self.api_key:
            raise MissingAPIKeyError(self.provider_name)

        payload = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            client = get_shared_async_client(timeout_seconds=self.timeout_seconds)
            async with client.stream("POST", self.endpoint, json=payload, headers=headers) as response:
                self._raise_for_http_error(response.status_code)
                async for line in response.aiter_lines():
                    raw = str(line or "").strip()
                    if not raw:
                        continue
                    if raw.startswith("data:"):
                        raw = raw[len("data:") :].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(data, dict):
                        continue

                    message_obj = data.get("message") if isinstance(data.get("message"), dict) else {}
                    delta = message_obj.get("content")
                    if delta is not None and str(delta):
                        yield ProviderStreamChunk(delta=str(delta))

                    if bool(data.get("done")):
                        usage = self._usage_from_ollama(data)
                        if usage.total_tokens > 0:
                            yield ProviderStreamChunk(usage=usage)
                        yield ProviderStreamChunk(finish_reason="stop")
                        break
        except httpx.TimeoutException as exc:
            raise ProviderError(
                provider=self.provider_name,
                message="Provider request timed out.",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderError(
                provider=self.provider_name,
                message="Network error while calling provider.",
                retryable=True,
            ) from exc

    def _raise_for_http_error(self, status_code: int) -> None:
        if status_code in {401, 403}:
            raise ProviderError(
                provider=self.provider_name,
                message="Provider authentication failed.",
                retryable=True,
                status_code=status_code,
            )
        if status_code == 404:
            raise ProviderError(
                provider=self.provider_name,
                message="Provider model unavailable.",
                retryable=True,
                status_code=status_code,
            )
        if status_code == 429:
            raise ProviderError(
                provider=self.provider_name,
                message="Provider rate limited this request.",
                retryable=True,
                status_code=status_code,
            )
        if status_code >= 500:
            raise ProviderError(
                provider=self.provider_name,
                message="Provider temporarily unavailable.",
                retryable=True,
                status_code=status_code,
            )
        if status_code >= 400:
            raise ProviderError(
                provider=self.provider_name,
                message="Provider request failed.",
                retryable=True,
                status_code=status_code,
            )

    def _parse_json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                provider=self.provider_name,
                message="Invalid provider response format.",
                retryable=True,
                status_code=response.status_code,
            ) from exc
        if not isinstance(data, dict):
            raise ProviderError(
                provider=self.provider_name,
                message="Invalid provider response format.",
                retryable=True,
                status_code=response.status_code,
            )
        return data

    @staticmethod
    def _usage_from_ollama(data: dict[str, Any]) -> ProviderUsage:
        prompt_tokens = int(data.get("prompt_eval_count", 0) or 0)
        completion_tokens = int(data.get("eval_count", 0) or 0)
        total_tokens = int(data.get("total_tokens", 0) or 0)
        if total_tokens <= 0:
            total_tokens = prompt_tokens + completion_tokens
        return ProviderUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
