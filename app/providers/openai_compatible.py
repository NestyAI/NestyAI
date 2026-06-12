from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.core.errors import MissingAPIKeyError, ProviderError, StreamingNotSupportedError
from app.core.http_client import get_shared_async_client
from app.providers.base import BaseProvider
from app.providers.content_extract import extract_choice_message_content, extract_delta_content
from app.schemas.chat import ChatMessage
from app.schemas.provider import ProviderChatResult, ProviderStreamChunk, ProviderUsage


class OpenAICompatibleChatProvider(BaseProvider):
    def __init__(
        self,
        *,
        provider_name: str,
        api_key: str | None,
        timeout_seconds: float,
        endpoint: str,
        extra_headers: dict[str, str] | None = None,
        supports_streaming: bool = True,
        require_api_key: bool = True,
    ) -> None:
        self.provider_name = provider_name
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.endpoint = endpoint.rstrip("/")
        self.extra_headers = dict(extra_headers or {})
        self.supports_streaming = supports_streaming
        self.require_api_key = require_api_key

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self.require_api_key:
            if not self.api_key:
                raise MissingAPIKeyError(self.provider_name)
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def generate_chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> ProviderChatResult:
        headers = self._build_headers()

        payload = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
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

        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderError(
                provider=self.provider_name,
                message="Provider temporarily unavailable.",
                retryable=True,
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise ProviderError(
                provider=self.provider_name,
                message="Provider rejected request.",
                retryable=False,
                status_code=response.status_code,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                provider=self.provider_name,
                message="Invalid provider response format.",
                retryable=True,
                status_code=response.status_code,
            ) from exc
        choices = data.get("choices") or []
        first_choice = choices[0] if choices else {}
        content = extract_choice_message_content(first_choice if isinstance(first_choice, dict) else {})
        usage_raw = data.get("usage", {})
        usage = ProviderUsage(
            prompt_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
            total_tokens=int(usage_raw.get("total_tokens", 0) or 0),
        )
        return ProviderChatResult(provider=self.provider_name, content=content, usage=usage)

    async def stream_chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[ProviderStreamChunk]:
        if not self.supports_streaming:
            raise StreamingNotSupportedError(self.provider_name)
        headers = self._build_headers()

        payload = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        try:
            client = get_shared_async_client(timeout_seconds=self.timeout_seconds)
            async with client.stream("POST", self.endpoint, json=payload, headers=headers) as response:
                if response.status_code == 429 or response.status_code >= 500:
                    raise ProviderError(
                        provider=self.provider_name,
                        message="Provider temporarily unavailable.",
                        retryable=True,
                        status_code=response.status_code,
                    )
                if response.status_code >= 400:
                    raise ProviderError(
                        provider=self.provider_name,
                        message="Provider rejected request.",
                        retryable=False,
                        status_code=response.status_code,
                    )

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    raw_data = line[len("data:") :].strip()
                    if raw_data == "[DONE]":
                        break
                    try:
                        data = json.loads(raw_data)
                    except json.JSONDecodeError:
                        continue

                    usage_raw = data.get("usage")
                    if isinstance(usage_raw, dict):
                        yield ProviderStreamChunk(
                            usage=ProviderUsage(
                                prompt_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
                                completion_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
                                total_tokens=int(usage_raw.get("total_tokens", 0) or 0),
                            )
                        )

                    choices = data.get("choices") or []
                    for choice in choices:
                        delta_obj = choice.get("delta") or {}
                        content = extract_delta_content(delta_obj if isinstance(delta_obj, dict) else {})
                        finish_reason = choice.get("finish_reason")
                        yield ProviderStreamChunk(
                            delta=content,
                            finish_reason=str(finish_reason) if finish_reason else None,
                        )
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
